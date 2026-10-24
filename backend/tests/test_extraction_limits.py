"""Reject incomplete processing rather than silently discarding source evidence."""
import io

import pymupdf as fitz
from PIL import Image
import pytest

from app.extraction import MAX_DOCUMENT_TEXT_CHARS, MAX_PAGE_TEXT_CHARS


def text_pdf(page_texts):
    with fitz.open() as document:
        for text in page_texts:
            page = document.new_page()
            page.insert_text((30, 30), text, fontsize=3)
        return document.tobytes(deflate=True)


def extract_uploaded(client, filename, data, mime='application/pdf'):
    response = client.post('/instruments/upload', files={'file': (filename, data, mime)})
    assert response.status_code == 201, response.text
    record = response.json()
    response = client.post(f'/instruments/{record["id"]}/extract', json={'mode': 'demo'})
    assert response.status_code == 200, response.text
    return response.json()


def assert_failed_without_partial_values(record, limit):
    assert limit in record['extraction_error']
    assert 'No partial extraction was accepted' in record['extraction_error'] or 'no partial extraction was accepted' in record['extraction_error']
    assert record['status'] == 'uploaded'
    assert record['original_extraction'] is None
    assert all(value is None for value in record['fields'].values())
    assert any(event['action'] == 'extraction_failed' for event in record['audit'])
    assert not any(event['action'] in ('extraction', 'approve', 'reject') for event in record['audit'])


def test_overlong_page_cannot_hide_a_conflicting_holder_after_the_limit(client):
    text = 'Holder Name: Fictional Cedar Trust\n' + ('X' * 210 + '\n') * 100 + 'Holder Name: Fictional Amber Trust'
    data = text_pdf([text])
    with fitz.open(stream=data, filetype='pdf') as document:
        extracted = document[0].get_text()
        assert len(extracted) > MAX_PAGE_TEXT_CHARS
        assert extracted.index('Holder Name: Fictional Amber Trust') > MAX_PAGE_TEXT_CHARS
    assert_failed_without_partial_values(extract_uploaded(client, 'overlong.pdf', data), '20,000')


def test_total_document_text_limit_fails_before_any_partial_extraction(client):
    data = text_pdf([('X' * 190 + '\n') * 100] * 11)
    with fitz.open(stream=data, filetype='pdf') as document:
        lengths = [len(page.get_text()) for page in document]
        assert max(lengths) < MAX_PAGE_TEXT_CHARS
        assert sum(lengths) > MAX_DOCUMENT_TEXT_CHARS
    assert_failed_without_partial_values(extract_uploaded(client, 'long-document.pdf', data), '200,000')


def test_seventh_unreadable_page_is_not_silently_omitted_from_vision_input(client):
    with fitz.open() as document:
        for _ in range(7):
            document.new_page(width=100, height=100)
        data = document.tobytes()
    assert_failed_without_partial_values(extract_uploaded(client, 'seven-unreadable-pages.pdf', data), 'six-page')


@pytest.mark.parametrize('mime,filename', [('image/png', 'scan.png'), ('application/pdf', 'scan.pdf')])
def test_oversized_ocr_output_is_rejected_without_truncation(client, monkeypatch, mime, filename):
    monkeypatch.setattr('app.extraction.ocr_image', lambda *_: 'X' * (MAX_PAGE_TEXT_CHARS + 1))
    if mime == 'image/png':
        buffer = io.BytesIO()
        Image.new('RGB', (100, 100), 'white').save(buffer, format='PNG')
        data = buffer.getvalue()
    else:
        data = text_pdf([''])
    assert_failed_without_partial_values(extract_uploaded(client, filename, data, mime), '20,000')
