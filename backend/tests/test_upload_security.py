"""Regression tests for upload/content limits and the early ASGI boundary."""
import asyncio
import io
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from PIL import Image
import pymupdf as fitz
import pytest

from app.request_security import SecurityBoundaryMiddleware
from app.samples import sample_pdf
from app.upload_security import safe_display_filename, verify_document, write_private_document


def settings(**values):
    return SimpleNamespace(api_key='test-key', max_upload_mb=1, max_pages=2, **values)


def image_bytes(format='PNG', **options):
    buffer = io.BytesIO()
    Image.new('RGB', (32, 24), 'white').save(buffer, format=format, **options)
    return buffer.getvalue()


@pytest.mark.parametrize(('filename', 'mime', 'data'), [
    ('receipt.pdf', 'application/pdf', lambda: sample_pdf('valid-fdr.pdf')),
    ('receipt.png', 'image/png', image_bytes),
    ('receipt.jpeg', 'image/jpeg', lambda: image_bytes('JPEG')),
])
def test_benign_supported_documents_decode(filename, mime, data):
    assert verify_document(data(), filename, mime, settings()) == (mime, 1)


def test_pdf_pages_encryption_dimensions_and_attachments_are_rejected():
    documents = []
    with fitz.open() as document:
        for _ in range(3):
            document.new_page()
        documents.append(document.tobytes())
    with fitz.open() as document:
        document.new_page(width=5000, height=5000)
        documents.append(document.tobytes())
    with fitz.open() as document:
        document.new_page()
        document.embfile_add('not-a-receipt.txt', b'synthetic attachment')
        documents.append(document.tobytes())
    with fitz.open() as document:
        document.new_page()
        documents.append(document.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='user'))
    for data in documents:
        with pytest.raises(HTTPException) as failure:
            verify_document(data, 'receipt.pdf', 'application/pdf', settings())
        assert failure.value.status_code == 400


@pytest.mark.parametrize('action', [
    '/OpenAction<</S/JavaScript/JS(app.alert(1))>>',
    '/Open#41ction<</S/Java#53cript/JS(app.alert(1))>>',
    '/AA<</O<</S/Launch/F(fake.exe)>>>>',
])
def test_active_pdf_actions_including_escaped_names_are_rejected(action):
    with fitz.open() as document:
        document.new_page()
        document.update_object(document.pdf_catalog(), f'<</Type/Catalog/Pages 2 0 R{action}>>')
        data = document.tobytes()
    with pytest.raises(HTTPException) as failure:
        verify_document(data, 'receipt.pdf', 'application/pdf', settings())
    assert failure.value.status_code == 400


def test_pdf_metadata_and_text_mentions_are_not_confused_with_active_names():
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((50, 60), 'Benign documentation mentions /JavaScript and /OpenAction as text.')
        document.set_metadata({'title': 'Guide: /JavaScript (examples) and /JS are data'})
        data = document.tobytes()
    assert verify_document(data, 'guide.pdf', 'application/pdf', settings()) == ('application/pdf', 1)


@pytest.mark.parametrize(('filename', 'mime', 'data', 'status'), [
    ('script.svg', 'image/svg+xml', b'<svg/>', 415),
    ('fake.pdf', 'application/pdf', b'%PDF-not-a-real-document', 400),
    ('wrong.png', 'image/png', b'<!doctype html><script>alert(1)</script>', 400),
    ('wrong.png', 'image/jpeg', b'anything', 415),
    ('huge.pdf', 'application/pdf', b'%PDF-' + b'X' * (1024 * 1024), 413),
], ids=['svg', 'malformed-pdf', 'html-image', 'mime-mismatch', 'size-limit'])
def test_untrusted_content_and_size_reject_cleanly(filename, mime, data, status):
    with pytest.raises(HTTPException) as failure:
        verify_document(data, filename, mime, settings())
    assert failure.value.status_code == status


def test_truncated_jpeg_must_fully_decode_and_animation_is_rejected():
    # JPEG's verify() alone succeeds despite missing the pixel stream tail.
    jpeg = image_bytes('JPEG')[:-20]
    with Image.open(io.BytesIO(jpeg)) as image:
        image.verify()
    with pytest.raises(HTTPException):
        verify_document(jpeg, 'truncated.jpg', 'image/jpeg', settings())
    buffer = io.BytesIO()
    Image.new('RGB', (24, 24), 'white').save(buffer, format='PNG', save_all=True,
        append_images=[Image.new('RGB', (24, 24), 'black')], duration=100, loop=0)
    with pytest.raises(HTTPException):
        verify_document(buffer.getvalue(), 'animated.png', 'image/png', settings())


def test_image_pixel_limit_is_checked_before_decode(monkeypatch):
    monkeypatch.setattr('app.upload_security.MAX_IMAGE_PIXELS', 100)
    with pytest.raises(HTTPException) as failure:
        verify_document(image_bytes(), 'oversized.png', 'image/png', settings())
    assert failure.value.status_code == 400


def test_display_names_remove_traversal_controls_and_bidi():
    assert safe_display_filename('../../receipt.pdf') == 'receipt.pdf'
    assert safe_display_filename('C:\\private\\receipt.pdf') == 'receipt.pdf'
    assert safe_display_filename('unsafe\r\n\x00\u202ename.pdf') == 'unsafename.pdf'
    assert safe_display_filename('...') == 'document'


def test_private_write_names_are_generated_and_unique(tmp_path):
    first = write_private_document(tmp_path, b'one', '.pdf')
    second = write_private_document(tmp_path, b'two', '.pdf')
    assert first != second
    assert first.parent == tmp_path and second.parent == tmp_path
    assert first.suffix == '.pdf' and len(first.stem) == 36
    assert first.read_bytes() == b'one' and second.read_bytes() == b'two'
    if os.name != 'nt':
        assert first.stat().st_mode & 0o777 == 0o600


def test_storage_failure_cleans_partial_document_and_hides_host_paths(tmp_path, monkeypatch):
    monkeypatch.setattr('app.upload_security.os.fsync', lambda _: (_ for _ in ()).throw(OSError('/private/host/path')))
    with pytest.raises(HTTPException) as failure:
        write_private_document(tmp_path, b'synthetic data', '.pdf')
    assert failure.value.status_code == 503
    assert '/private/host/path' not in failure.value.detail
    assert list(tmp_path.iterdir()) == []


def boundary_request(body_chunks, headers=(), path='/instruments/upload', method='POST'):
    sent, delivered = [], []
    pending = list(body_chunks)
    calls = {'app': 0, 'receive': 0}

    async def receive():
        calls['receive'] += 1
        if pending:
            return pending.pop(0)
        return {'type': 'http.disconnect'}

    async def send(message):
        sent.append(message)

    async def app(scope, receive, send):
        calls['app'] += 1
        message = await receive()
        delivered.append(message['body'])
        await send({'type': 'http.response.start', 'status': 204, 'headers': []})
        await send({'type': 'http.response.body', 'body': b''})

    scope = {'type': 'http', 'method': method, 'path': path, 'headers': list(headers)}
    asyncio.run(SecurityBoundaryMiddleware(app, settings())(scope, receive, send))
    return sent, delivered, calls


def test_unauthorized_malformed_upload_is_rejected_before_reading_or_parsing():
    sent, _, calls = boundary_request([{'type': 'http.request', 'body': b'bad multipart'}])
    assert sent[0]['status'] == 401
    assert calls == {'app': 0, 'receive': 0}


@pytest.mark.parametrize('key', [b'wrong', b'wrong-\xe9'])
def test_wrong_keys_fail_cleanly_before_body_read(key):
    sent, _, calls = boundary_request([], headers=[(b'x-api-key', key)])
    assert sent[0]['status'] == 401 and calls['receive'] == 0


def test_streamed_body_limit_cannot_be_bypassed_by_missing_length_or_lying_length():
    chunks = [
        {'type': 'http.request', 'body': b'x' * (1024 * 1024), 'more_body': True},
        {'type': 'http.request', 'body': b'x' * (1024 * 1024 + 1), 'more_body': False},
    ]
    for extra in [[], [(b'content-length', b'1')]]:
        sent, delivered, calls = boundary_request(chunks, headers=[(b'x-api-key', b'test-key'), *extra])
        assert sent[0]['status'] == 413
        assert not delivered and calls['app'] == 0


def test_chunked_benign_body_is_replayed_after_bounded_read():
    chunks = [{'type': 'http.request', 'body': b'part ', 'more_body': True},
              {'type': 'http.request', 'body': b'two', 'more_body': False}]
    sent, delivered, calls = boundary_request(chunks, headers=[(b'x-api-key', b'test-key')])
    assert sent[0]['status'] == 204 and delivered == [b'part two']
    assert calls['app'] == 1


@pytest.mark.parametrize('length', [b'-1', b'+1', b'invalid', b'9' * 30])
def test_invalid_content_length_fails_before_parsing(length):
    sent, _, calls = boundary_request([], headers=[(b'x-api-key', b'test-key'), (b'content-length', length)])
    assert sent[0]['status'] == 400 and calls['receive'] == 0


def test_length_mismatch_and_duplicate_authorization_are_rejected():
    sent, _, calls = boundary_request([{'type': 'http.request', 'body': b'abc'}],
        headers=[(b'x-api-key', b'test-key'), (b'content-length', b'1')])
    assert sent[0]['status'] == 400 and calls['app'] == 0
    sent, _, calls = boundary_request([], headers=[(b'x-api-key', b'test-key'), (b'x-api-key', b'test-key')])
    assert sent[0]['status'] == 401 and calls['receive'] == 0


def test_health_remains_public_but_path_prefix_does_not_bypass_auth():
    body = [{'type': 'http.request', 'body': b''}]
    assert boundary_request(body, path='/health', method='GET')[0][0]['status'] == 204
    assert boundary_request(body, path='/health/private', method='GET')[0][0]['status'] == 401


def test_route_rejects_active_pdf_without_persisting_private_content(client, settings):
    with fitz.open() as document:
        document.new_page()
        document.xref_set_key(document.pdf_catalog(), 'OpenAction', '<</S/JavaScript/JS(app.alert(1))>>')
        data = document.tobytes()
    response = client.post('/instruments/upload', files={'file': ('active.pdf', data, 'application/pdf')})
    assert response.status_code == 400
    assert client.get('/instruments').json()['total'] == 0
    assert not list(settings.storage_dir.iterdir())


def test_route_storage_failure_rolls_back_business_and_audit(client, settings, monkeypatch):
    monkeypatch.setattr('app.upload_security.os.fsync', lambda _: (_ for _ in ()).throw(OSError('disk failure')))
    response = client.post('/instruments/upload', files={'file': ('receipt.pdf', sample_pdf('valid-fdr.pdf'), 'application/pdf')})
    assert response.status_code == 503
    assert client.get('/instruments').json()['total'] == 0
    assert client.get('/audit').json() == []
    assert not list(settings.storage_dir.iterdir())


def test_route_rejects_unauthorized_invalid_multipart_before_parser(client):
    response = client.post('/instruments/upload', content=b'not valid multipart',
        headers={'X-API-Key': '', 'Content-Type': 'multipart/form-data; boundary=invalid'})
    assert response.status_code == 401


def test_request_deadline_stops_a_stalled_upload_before_parsing():
    sent, called = [], []

    async def receive():
        await asyncio.sleep(1)
        return {'type': 'http.request', 'body': b'late'}

    async def send(message):
        sent.append(message)

    async def app(*args):
        called.append(True)

    scope = {'type': 'http', 'method': 'POST', 'path': '/instruments/upload',
             'headers': [(b'x-api-key', b'test-key')]}
    middleware = SecurityBoundaryMiddleware(app, settings(request_timeout_seconds=0.01))
    asyncio.run(middleware(scope, receive, send))
    assert sent[0]['status'] == 408
    assert not called


def test_process_rate_limit_counts_bad_keys_and_expires_without_trusting_headers(monkeypatch):
    clock = {'now': 100.0}
    monkeypatch.setattr('app.request_security.time.monotonic', lambda: clock['now'])
    middleware = SecurityBoundaryMiddleware(None, settings(rate_limit_requests=2, rate_limit_window_seconds=10))

    async def request(source, key=b'wrong', path='/instruments'):
        sent = []

        async def receive():
            return {'type': 'http.request', 'body': b''}

        async def send(message):
            sent.append(message)

        scope = {'type': 'http', 'method': 'GET', 'path': path, 'client': (source, 12345),
                 'headers': [(b'x-api-key', key), (b'x-forwarded-for', b'untrusted-new-client')]}
        await middleware(scope, receive, send)
        return sent[0]

    async def exercise():
        assert (await request('127.0.0.1'))['status'] == 401
        assert (await request('127.0.0.1'))['status'] == 401
        limited = await request('127.0.0.1')
        assert limited['status'] == 429
        assert (b'retry-after', b'10') in limited['headers']
        assert (await request('127.0.0.2'))['status'] == 401
        clock['now'] += 11
        assert (await request('127.0.0.1'))['status'] == 401

    asyncio.run(exercise())


def test_public_health_is_available_after_protected_rate_limit(settings):
    from app.main import create_app
    from fastapi.testclient import TestClient

    settings.rate_limit_requests = 1
    app = create_app(settings)
    try:
        with TestClient(app, headers={'X-API-Key': 'test-key'}) as client:
            assert client.get('/instruments').status_code == 200
            assert client.get('/instruments').status_code == 429
            assert client.get('/health').status_code == 200
    finally:
        app.state.engine.dispose()
