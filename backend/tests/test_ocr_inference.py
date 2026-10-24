"""Regression contracts; real CPU inference/OCR is exercised by the live verifier."""
import io
import json

import httpx
import pymupdf as fitz
from PIL import Image
import pytest

from app import extraction, ocr
from app.schemas import ExtractionPayload


def fake_runtime(monkeypatch, callback):
    real_client = httpx.Client
    monkeypatch.setattr(extraction.httpx, 'Client', lambda **kw: real_client(transport=httpx.MockTransport(callback), **kw))


@pytest.mark.parametrize('base', ['http://localhost:11434', 'http://localhost:11434/api', 'http://localhost:11434/v1', 'http://localhost:11434/v1/chat/completions'])
def test_ollama_urls_and_constrained_nonstreaming_json(settings, monkeypatch, base):
    settings.gemma_base_url, settings.gemma_model = base, 'synthetic-model'
    def runtime(request):
        assert request.url.path == '/v1/chat/completions'
        body = json.loads(request.content)
        assert body['stream'] is False
        assert body['response_format']['json_schema']['schema']['additionalProperties'] is False
        schema = body['response_format']['json_schema']['schema']
        assert set(schema['required']) == {'fields', 'evidence', 'uncertain_fields', 'missing_fields'}
        assert set(schema['$defs']['ExtractionFields']['required']) == {'instrument_number', 'bank_name', 'amount', 'currency', 'issue_date', 'maturity_date', 'holder_name'}
        assert 'untrusted evidence' in body['messages'][0]['content']
        return httpx.Response(200, json={'model': 'synthetic-model', 'choices': [{'finish_reason': 'stop', 'message': {'content': '{"fields":{"amount":"unknown"}}'}}]})
    fake_runtime(monkeypatch, runtime)
    result = extraction.gemma_extract(['fictional receipt'], [], settings)
    assert result.fields.amount is None
    assert set(result.missing_fields) == set(result.fields.model_dump())


@pytest.mark.parametrize('response', [
    {'choices': [{'finish_reason': 'length', 'message': {'content': '{"fields":{}}'}}]},
    {'choices': [{'message': {'refusal': 'refused', 'content': '{"fields":{}}'}}]},
    {'choices': [{'message': {'content': '{"fields":{"amount":123}}'}}]},
    {'choices': None}, {'choices': [{'message': []}]},
    {'model': 'unexpected-model', 'choices': [{'message': {'content': '{"fields":{}}'}}]},
    {'choices': [{'message': {'content': '{"fields":{},"approve":true}'}}]},
])
def test_invalid_model_responses_never_become_extractions(settings, monkeypatch, response):
    settings.gemma_base_url, settings.gemma_model = 'http://localhost:8081/v1', 'synthetic-model'
    fake_runtime(monkeypatch, lambda _: httpx.Response(200, json=response))
    with pytest.raises(extraction.ExtractionFailure):
        extraction.gemma_extract(['fictional receipt'], [], settings)


def test_text_model_refuses_unreadable_images_instead_of_ignoring_them(settings):
    settings.gemma_base_url, settings.gemma_model = 'http://localhost:8081/v1', 'synthetic-model'
    settings.gemma_supports_vision = False
    with pytest.raises(extraction.ExtractionFailure, match='text-only'):
        extraction.gemma_extract(['Some digital header'], [(1, 'synthetic-image')], settings)


@pytest.mark.parametrize('status,expected', [(404, 'not found'), (400, 'schema'), (503, 'availability')])
def test_runtime_errors_are_actionable_without_private_response_leaks(settings, monkeypatch, status, expected):
    settings.gemma_base_url, settings.gemma_model = 'http://localhost:8081/v1', 'synthetic-model'
    fake_runtime(monkeypatch, lambda _: httpx.Response(status, text='private provider credential'))
    with pytest.raises(extraction.ExtractionFailure) as error:
        extraction.gemma_extract(['fictional receipt'], [], settings)
    assert expected in str(error.value)
    assert 'private provider credential' not in str(error.value)


def test_visual_boxes_reassemble_label_and_value_in_reading_order():
    boxes = [[[100, 10], [200, 10], [200, 30], [100, 30]],
             [[0, 11], [90, 11], [90, 31], [0, 31]],
             [[0, 50], [100, 50], [100, 70], [0, 70]]]
    assert ocr.lines_from_boxes(boxes, ['12345.00', 'Amount:', 'Currency: INR']) == 'Amount: 12345.00\nCurrency: INR'


def mixed_pdf():
    buffer = io.BytesIO()
    Image.new('RGB', (500, 300), 'white').save(buffer, format='PNG')
    with fitz.open() as pdf:
        pdf.new_page().insert_text((40, 40), 'FDR Number: SYNTHETIC-MIXED-001')
        page = pdf.new_page()
        page.insert_text((40, 40), 'A digital header long enough to suppress the old OCR path')
        page.insert_image(fitz.Rect(40, 80, 540, 380), stream=buffer.getvalue())
        return pdf.tobytes()


def test_mixed_pdf_ocr_reaches_validation_and_preserves_page_provenance(client, settings, monkeypatch):
    settings.ocr_enabled = True
    calls = []
    def recognize(image, _):
        calls.append(image.size)
        return 'Deposit Amount: 500.00\nCurrency: INR\nHolder Name: Fictional Scan Holder'
    monkeypatch.setattr(extraction, 'ocr_image', recognize)
    record = client.post('/instruments/upload', files={'file': ('mixed.pdf', mixed_pdf(), 'application/pdf')}).json()
    record = client.post(f'/instruments/{record["id"]}/extract', json={'mode': 'demo'}).json()
    assert len(calls) == 1
    assert min(calls[0]) > 1000
    assert record['fields']['instrument_number'] == 'SYNTHETIC-MIXED-001'
    assert record['fields']['amount'] == '500.00'
    assert record['fields']['maturity_date'] is None
    assert 'MINIMUM_AMOUNT' in {f['rule_id'] for f in record['findings']}
    original = record['original_extraction']
    assert original['provenance']['pages'][0]['method'] == 'embedded_text'
    assert original['provenance']['pages'][1]['method'] == 'embedded_text+ocr'
    assert next(e['page'] for e in original['evidence'] if e['field'] == 'amount') == 2
    assert any(e['details'].get('provenance') == original['provenance'] for e in record['audit'])
    assert record['status'] == 'pending_review'


def test_ocr_failure_is_persisted_instead_of_claiming_parser_success(client, settings, monkeypatch):
    settings.ocr_enabled = True
    def fail(*_):
        raise extraction.ExtractionFailure('Synthetic OCR initialization failure')
    monkeypatch.setattr(extraction, 'ocr_image', fail)
    record = client.post('/instruments/upload', files={'file': ('mixed.pdf', mixed_pdf(), 'application/pdf')}).json()
    record = client.post(f'/instruments/{record["id"]}/extract', json={'mode': 'demo'}).json()
    assert record['original_extraction'] is None
    assert record['extraction_error'] == 'Synthetic OCR initialization failure'
    assert any(e['action'] == 'extraction_failed' for e in record['audit'])


def test_model_timeout_has_no_silent_fallback_but_explicit_parser_retry_works(client, settings, monkeypatch):
    settings.gemma_base_url, settings.gemma_model = 'http://localhost:8081/v1', 'synthetic-model'
    def timeout(request):
        raise httpx.ReadTimeout('synthetic timeout', request=request)
    fake_runtime(monkeypatch, timeout)
    from app.demo_dataset import demo_pdf
    record = client.post('/instruments/upload', files={'file': ('synthetic.pdf', demo_pdf('01_valid_fdr.pdf'), 'application/pdf')}).json()
    failed = client.post(f'/instruments/{record["id"]}/extract', json={'mode': 'gemma'}).json()
    assert failed['original_extraction'] is None
    assert 'timed out' in failed['extraction_error']
    fallback = client.post(f'/instruments/{record["id"]}/extract', json={'mode': 'demo'}).json()
    assert fallback['extraction_error'] is None
    assert fallback['original_extraction']['provenance']['field_extractor'] == 'labelled_parser'
    assert fallback['fields']['amount'] == '250000.00'


def test_grounding_rejects_document_brand_as_bank_and_conflicting_holder():
    texts = ['VaultX\nBank Name: Fictional Harbor Bank\nHolder Name: Avery Example\nHolder Name: Jordan Sample']
    payload = ExtractionPayload.model_validate({'fields': {'bank_name': 'VaultX', 'holder_name': 'Avery Example'}, 'evidence': [
        {'field': 'bank_name', 'page': 1, 'quote': 'VaultX'},
        {'field': 'holder_name', 'page': 1, 'quote': 'Holder Name: Avery Example'}]})
    grounded = extraction.ground_model_payload(payload, texts, False)
    assert grounded.fields.bank_name is None and grounded.fields.holder_name is None
    assert {'bank_name', 'holder_name'} <= set(grounded.uncertain_fields)


def test_grounding_never_substitutes_parser_values_for_missing_model_fields():
    grounded = extraction.ground_model_payload(ExtractionPayload(fields={}), ['Bank Name: Fictional Harbor Bank'], False)
    assert grounded.fields.bank_name is None


def test_grounding_rejects_invented_evidence_and_unsupported_values():
    payload = ExtractionPayload.model_validate({'fields': {'amount': '10000.00'}, 'evidence': [
        {'field': 'amount', 'page': 2, 'quote': 'Amount: 10000.00'}]})
    result = extraction.ground_model_payload(payload, ['Amount: 999.00'], False)
    assert result.fields.amount is None
    assert 'amount' in result.missing_fields


def test_cpu_ocr_preprocessing_and_blank_results_do_not_invent_text(settings, monkeypatch):
    from types import SimpleNamespace
    settings.ocr_enabled = True
    seen = []
    def recognize(pixels):
        seen.append(pixels)
        return SimpleNamespace(txts=None, boxes=None)
    monkeypatch.setattr(ocr, 'available', lambda _: True)
    monkeypatch.setattr(ocr, 'engine', lambda _: recognize)
    assert ocr.read_image(Image.new('RGBA', (200, 100), (0, 0, 0, 0)), settings) == ''
    assert seen[0].shape == (200, 400, 3)
    assert seen[0].min() == 255


def test_enabled_missing_ocr_dependencies_fail_explicitly(settings, monkeypatch):
    settings.ocr_enabled = True
    monkeypatch.setattr(ocr, 'available', lambda _: False)
    with pytest.raises(extraction.ExtractionFailure, match='OCR failed'):
        extraction.ocr_image(Image.new('RGB', (100, 100), 'white'), settings)


@pytest.mark.parametrize('change', [
    {'ocr_engine': 'unknown'}, {'ocr_dpi': 99}, {'ocr_dpi': 301},
    {'gemma_response_format': 'arbitrary'}, {'gemma_max_tokens': 0}, {'gemma_max_tokens': 5000},
    {'gemma_repair_attempts': -1}, {'gemma_repair_attempts': 2},
])
def test_invalid_ocr_and_inference_configuration_fails_early(settings, change):
    from dataclasses import replace
    with pytest.raises(ValueError):
        replace(settings, **change)


def repair_runtime(settings, monkeypatch, *, repair_succeeds=True, clock=None):
    settings.gemma_base_url, settings.gemma_model = 'http://localhost:8081/v1', 'synthetic-gemma'
    settings.gemma_repair_attempts = 1
    calls = []
    def runtime(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body['response_format']['json_schema']['schema']['properties']['evidence']['minItems'] == 1
        if clock is not None:
            clock['now'] = 2
        value = 'SYN-2026-001' if len(calls) == 2 and repair_succeeds else 'SYN-26-001'
        payload = {'fields': {'instrument_number': value}, 'evidence': [
            {'field': 'instrument_number', 'page': 1, 'quote': 'FDR Number: SYN-2026-001'}]}
        return httpx.Response(200, json={'model': settings.gemma_model, 'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(payload)}}]})
    fake_runtime(monkeypatch, runtime)
    return calls


def test_grounding_repair_requires_a_new_model_response_and_records_attempts(settings, monkeypatch):
    calls = repair_runtime(settings, monkeypatch)
    result = extraction.gemma_extract(['FDR Number: SYN-2026-001'], [], settings)
    assert len(calls) == 2
    assert len(calls[1]['messages']) == 4
    assert 'source grounding' in calls[1]['messages'][-1]['content']
    assert result.fields.instrument_number == 'SYN-2026-001'
    assert result._repair_attempts == 1
    assert '_repair_attempts' not in result.model_dump()


def test_repair_exhaustion_stays_null_and_never_copies_parser_values(settings, monkeypatch):
    calls = repair_runtime(settings, monkeypatch, repair_succeeds=False)
    result = extraction.gemma_extract(['FDR Number: SYN-2026-001'], [], settings)
    assert len(calls) == 2
    assert result.fields.instrument_number is None
    assert 'instrument_number' in result.missing_fields


def test_repair_cannot_extend_the_total_inference_timeout(settings, monkeypatch):
    clock = {'now': 0}
    settings.gemma_timeout = 1
    monkeypatch.setattr(extraction.time, 'monotonic', lambda: clock['now'])
    calls = repair_runtime(settings, monkeypatch, clock=clock)
    with pytest.raises(extraction.ExtractionFailure, match='timed out'):
        extraction.gemma_extract(['FDR Number: SYN-2026-001'], [], settings)
    assert len(calls) == 1


def test_model_cannot_claim_its_own_trusted_repair_provenance():
    with pytest.raises(extraction.ExtractionFailure, match='malformed'):
        extraction.parse_model_response('{"fields":{},"_repair_attempts":0}')


@pytest.mark.parametrize('alter_grounded_field', [False, True])
def test_scoped_repair_retains_grounded_fields_and_rejects_outside_changes(settings, monkeypatch, alter_grounded_field):
    settings.gemma_base_url, settings.gemma_model = 'http://localhost:8081/v1', 'synthetic-gemma'
    calls = []
    def runtime(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            payload = {'fields': {'instrument_number': 'SYN-26-001', 'bank_name': 'Fictional Example Bank'}, 'evidence': [
                {'field': 'instrument_number', 'page': 1, 'quote': 'FDR Number: SYN-2026-001'},
                {'field': 'bank_name', 'page': 1, 'quote': 'Bank Name: Fictional Example Bank'}]}
        else:
            schema = body['response_format']['json_schema']['schema']
            assert schema['$defs']['ExtractionFields']['required'] == ['instrument_number']
            assert schema['$defs']['ExtractionFields']['properties']['instrument_number']['enum'] == ['SYN-2026-001', None]
            assert schema['$defs']['Evidence']['properties']['quote']['enum'] == ['FDR Number: SYN-2026-001']
            assert schema['$defs']['Evidence']['properties']['page']['enum'] == [1]
            assert schema['properties']['evidence']['maxItems'] == 1
            payload = {'fields': {'instrument_number': 'SYN-2026-001'}, 'evidence': [
                {'field': 'instrument_number', 'page': 1, 'quote': 'FDR Number: SYN-2026-001'}]}
            if alter_grounded_field:
                payload['fields']['bank_name'] = 'An unrequested bank change'
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(payload)}}]})
    fake_runtime(monkeypatch, runtime)
    texts = ['FDR Number: SYN-2026-001\nBank Name: Fictional Example Bank']
    if alter_grounded_field:
        with pytest.raises(extraction.ExtractionFailure, match='outside'):
            extraction.gemma_extract(texts, [], settings)
    else:
        result = extraction.gemma_extract(texts, [], settings)
        assert result.fields.bank_name == 'Fictional Example Bank'
        assert result.fields.instrument_number == 'SYN-2026-001'
        assert {e.field for e in result.evidence} == {'bank_name', 'instrument_number'}


def test_ambiguous_source_values_are_not_repaired_into_known_values(settings, monkeypatch):
    settings.gemma_base_url, settings.gemma_model = 'http://localhost:8081/v1', 'synthetic-gemma'
    calls = []
    def runtime(request):
        calls.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'fields': {'holder_name': 'Avery Example'}, 'evidence': [
            {'field': 'holder_name', 'page': 1, 'quote': 'Holder Name: Avery Example'}]})}}]})
    fake_runtime(monkeypatch, runtime)
    result = extraction.gemma_extract(['Holder Name: Avery Example\nHolder Name: Jordan Sample'], [], settings)
    assert result.fields.holder_name is None
    assert result._repair_attempts == 0
    assert len(calls) == 1


def test_multiple_failed_fields_get_one_focused_repair_each(settings, monkeypatch):
    settings.gemma_base_url, settings.gemma_model = 'http://localhost:8081/v1', 'synthetic-gemma'
    values = {'instrument_number': 'SYN-2026-001', 'holder_name': 'Fictional Example Holder', 'bank_name': 'Fictional Example Bank'}
    calls = []
    def runtime(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            payload = {'fields': {**values, 'instrument_number': 'SYN-26-001'}, 'evidence': [
                {'field': 'bank_name', 'page': 1, 'quote': 'Bank Name: Fictional Example Bank'},
                {'field': 'instrument_number', 'page': 1, 'quote': 'FDR Number: SYN-2026-001'}]}
        else:
            names = body['response_format']['json_schema']['schema']['$defs']['ExtractionFields']['required']
            assert len(names) == 1 and len(body['messages']) == 4
            field = names[0]
            payload = {'fields': {field: values[field]}, 'evidence': [{'field': field, 'page': 1, 'quote': values[field]}]}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(payload)}}]})
    fake_runtime(monkeypatch, runtime)
    result = extraction.gemma_extract(['FDR Number: SYN-2026-001\nBank Name: Fictional Example Bank\nHolder Name: Fictional Example Holder'], [], settings)
    assert len(calls) == 3 and result._repair_attempts == 2
    assert all(getattr(result.fields, field) == value for field, value in values.items())


def test_repair_null_is_preserved_even_when_source_candidate_is_available(settings, monkeypatch):
    settings.gemma_base_url, settings.gemma_model = 'http://localhost:8081/v1', 'synthetic-gemma'
    calls = []
    def runtime(request):
        calls.append(request)
        value = 'SYN-26-001' if len(calls) == 1 else None
        payload = {'fields': {'instrument_number': value}, 'evidence': [
            {'field': 'instrument_number', 'page': 1, 'quote': 'FDR Number: SYN-2026-001'}]}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(payload)}}]})
    fake_runtime(monkeypatch, runtime)
    result = extraction.gemma_extract(['FDR Number: SYN-2026-001'], [], settings)
    assert len(calls) == 2 and result.fields.instrument_number is None
    assert 'instrument_number' in result.missing_fields
