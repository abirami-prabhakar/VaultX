"""Exercise committed synthetic documents against independent expected JSON."""
import json
from pathlib import Path

import pymupdf as fitz
import pytest

from app.demo_dataset import DEMO_SAMPLES, INJECTION_TEXT, WATERMARK, demo_pdf


DATASET = Path(__file__).resolve().parents[2] / 'samples' / 'vaultx'
NAMES = [sample['name'] for sample in DEMO_SAMPLES]


def truth(name):
    return json.loads((DATASET / name.replace('.pdf', '.ground-truth.json')).read_text(encoding='utf-8'))


def upload_extract(client, name):
    response = client.post('/instruments/upload', files={'file': (name, (DATASET / name).read_bytes(), 'application/pdf')})
    assert response.status_code == 201, response.text
    record = response.json()
    response = client.post(f'/instruments/{record["id"]}/extract', json={'mode': 'demo'})
    assert response.status_code == 200, response.text
    assert response.json()['extraction_error'] is None
    return response.json()


@pytest.mark.parametrize('name', NAMES)
def test_reproducible_pdf_has_exact_watermark_and_readable_text(name):
    committed = (DATASET / name).read_bytes()
    assert committed == demo_pdf(name) == demo_pdf(name)
    with fitz.open(stream=committed, filetype='pdf') as document:
        assert len(document) == 1
        for page in document:
            text = page.get_text()
            assert WATERMARK in text
            assert 'VaultX' in text
            assert 'FDR Number:' in text
            assert 'FDR Intelligence' not in text
            if name == '05_prompt_injection_fdr.pdf':
                assert INJECTION_TEXT in text


@pytest.mark.parametrize('name', NAMES)
def test_actual_text_extraction_matches_independent_ground_truth(client, name):
    expected = truth(name)
    record = upload_extract(client, name)
    assert record['fields'] == expected['fields']
    assert set(record['original_extraction']['missing_fields']) == set(expected['missing_fields'])
    assert set(record['original_extraction']['uncertain_fields']) == set(expected['uncertain_fields'])
    assert {finding['rule_id'] for finding in record['findings']} == set(expected['expected_rule_ids_when_alone'])
    assert record['status'] == expected['expected_status_after_extraction']
    assert record['extraction_mode'] == 'demo'
    assert record['original_extraction']['model'] is None
    assert len(record['original_extraction']['evidence']) == sum(value is not None for value in expected['fields'].values())
    assert not any(event['action'] in ('approve', 'reject') for event in record['audit'])


def test_duplicate_fixture_requires_documented_upload_order_and_preserves_decision(client):
    first = upload_extract(client, '01_valid_fdr.pdf')
    assert first['findings'] == []
    approved = client.post(f'/instruments/{first["id"]}/review', json={'action': 'approve', 'reason': 'Human reviewed the synthetic source and available evidence.'})
    assert approved.status_code == 200
    assert approved.json()['status'] == 'approved'
    duplicate = upload_extract(client, '03_duplicate_fdr.pdf')
    expected = truth('03_duplicate_fdr.pdf')
    assert {f['rule_id'] for f in duplicate['findings']} == set(expected['expected_rule_ids_after_uploading'])
    first = client.get(f'/instruments/{first["id"]}').json()
    assert first['status'] == 'approved'
    assert {f['rule_id'] for f in first['findings']} == set(truth('01_valid_fdr.pdf')['expected_rule_ids_after_duplicate'])
    assert len([e for e in first['audit'] if e['action'] == 'approve']) == 1


def test_ambiguous_holder_and_missing_maturity_require_reasoned_human_correction(client):
    record = upload_extract(client, '04_missing_fields_fdr.pdf')
    assert record['fields']['holder_name'] is None
    assert record['fields']['maturity_date'] is None
    assert sum(f['rule_id'] == 'REQUIRED_FIELD' for f in record['findings']) == 2
    endpoint = f'/instruments/{record["id"]}/review'
    assert client.post(endpoint, json={'action': 'approve', 'reason': 'Attempted incomplete synthetic review.'}).status_code == 409
    original = record['original_extraction']
    correction = {'action': 'correct', 'fields': {'holder_name': 'Confirmed fictional institution', 'maturity_date': '2027-02-01'}, 'reason': 'Confirmed values from a separate fictional clarification fixture.'}
    response = client.post(endpoint, json=correction)
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated['original_extraction'] == original
    assert updated['corrected_fields'] == correction['fields']
    assert updated['findings'] == []
    assert any(e['action'] == 'correction' and e['reason'] == correction['reason'] for e in updated['audit'])
    assert client.post(endpoint, json={'action': 'approve', 'reason': 'Human reviewed the synthetic clarification and preserved original evidence.'}).status_code == 200


def test_injection_text_cannot_make_a_human_review_decision(client):
    record = upload_extract(client, '05_prompt_injection_fdr.pdf')
    assert record['status'] == 'pending_review'
    assert not any(event['action'] in truth('05_prompt_injection_fdr.pdf')['forbidden_automatic_actions'] for event in record['audit'])
    endpoint = f'/instruments/{record["id"]}/review'
    assert client.post(endpoint, json={'action': 'approve', 'reason': ''}).status_code == 422
    response = client.post(endpoint, headers={'X-API-Key': ''}, json={'action': 'approve', 'reason': INJECTION_TEXT})
    assert response.status_code == 401
    assert client.get(f'/instruments/{record["id"]}').json()['status'] == 'pending_review'


def test_scanned_copy_without_ocr_preserves_unknown_fields(client):
    """Rasterize a real fixture; an unreadable scan must not reuse its truth."""
    with fitz.open(DATASET / '01_valid_fdr.pdf') as source, fitz.open() as scan:
        page = source[0]
        image = page.get_pixmap(alpha=False)
        scan.new_page(width=page.rect.width, height=page.rect.height).insert_image(
            page.rect, stream=image.tobytes('png'))
        scanned_pdf = scan.tobytes()
    with fitz.open(stream=scanned_pdf, filetype='pdf') as document:
        assert not document[0].get_text().strip()

    response = client.post('/instruments/upload', files={
        'file': ('scanned-synthetic-fdr.pdf', scanned_pdf, 'application/pdf'),
    })
    assert response.status_code == 201, response.text
    record_id = response.json()['id']
    response = client.post(f'/instruments/{record_id}/extract', json={'mode': 'demo'})
    assert response.status_code == 200, response.text
    record = response.json()
    expected_fields = {field: None for field in truth('01_valid_fdr.pdf')['fields']}
    assert record['extraction_error'] is None
    assert record['fields'] == expected_fields
    assert set(record['original_extraction']['missing_fields']) == set(expected_fields)
    assert record['original_extraction']['evidence'] == []
    assert record['original_extraction']['model'] is None
    assert record['status'] == 'pending_review'
    assert {finding['field'] for finding in record['findings']
            if finding['rule_id'] == 'REQUIRED_FIELD'} == set(expected_fields)
    assert client.post(f'/instruments/{record_id}/review', json={
        'action': 'approve', 'reason': 'Attempted review without readable source evidence.',
    }).status_code == 409


def test_dataset_generator_does_not_accept_arbitrary_paths():
    with pytest.raises(KeyError):
        demo_pdf('../../private.pdf')
