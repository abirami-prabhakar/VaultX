from dataclasses import replace

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
import pytest

from app.main import create_app
from app.models import AuditEvent, Instrument, SecurityLabRun
from app.prompt_guard import GuardResult
from app.samples import sample_pdf


class FixedGuard:
    """Labelled adapter double: these tests do not measure a real model."""
    def __init__(self, state='flagged', complete=True):
        self.state = state
        self.complete = complete

    def status(self):
        return {'enabled': True, 'available': True, 'runtime_verified': False, 'status': 'available',
                'model': 'test-double-not-a-real-model', 'threshold': .5, 'reason': 'Synthetic adapter contract double'}

    def screen(self, text):
        return GuardResult(status=self.state, provider='llama-prompt-guard-2', model='test-double-not-a-real-model',
                           score=.9 if self.state == 'flagged' else .1, threshold=.5,
                           reason='Synthetic classifier output; no model inference', screened_chars=len(text) if self.complete else 0,
                           total_chars=len(text), complete=self.complete, chunks_screened=1)


def test_lab_authorization_no_initial_results_and_isolated_live_report(client, settings):
    for route, method in [('/security-lab', 'GET'), ('/security-lab/run', 'POST')]:
        assert client.request(method, route, headers={'X-API-Key': ''}).status_code == 401
    initial = client.get('/security-lab').json()
    assert initial['last_run'] is None
    assert initial['guard']['enabled'] is False
    response = client.post('/security-lab/run')
    assert response.status_code == 200, response.text
    report = response.json()
    assert report['summary']['failed'] == 0, [(c['id'], c['error']) for c in report['cases'] if c['status'] == 'failed']
    assert report['summary']['passed'] >= 10
    model_cases = [c for c in report['cases'] if c['method'] == 'classifier']
    assert len(model_cases) == 3 and all(c['status'] == 'skipped' for c in model_cases)
    assert any('false positive' in c['title'].lower() for c in model_cases)
    assert all(c['evidence'] for c in report['cases'])
    assert client.get('/security-lab').json()['last_run'] == report
    assert client.get('/instruments').json()['total'] == 0
    assert client.get('/audit').json() == []
    assert list(settings.storage_dir.iterdir()) == []
    app = create_app(settings)
    try:
        with TestClient(app, headers={'X-API-Key': settings.api_key}) as reopened:
            assert reopened.get('/security-lab').json()['last_run']['id'] == report['id']
        with Session(app.state.engine) as db:
            assert db.scalar(select(func.count()).select_from(Instrument)) == 0
            assert db.scalar(select(func.count()).select_from(AuditEvent)) == 0
            assert db.scalar(select(func.count()).select_from(SecurityLabRun)) == 1
        for operation in ('UPDATE security_lab_runs SET actor=actor', 'DELETE FROM security_lab_runs'):
            with pytest.raises(DBAPIError, match='append-only'):
                with app.state.engine.begin() as connection:
                    connection.execute(text(operation))
    finally:
        app.state.engine.dispose()


@pytest.mark.parametrize('state,failures', [('flagged', 2), ('clear', 1)])
def test_lab_records_real_classifier_false_positive_and_false_negative_errors(settings, state, failures):
    app = create_app(settings, prompt_guard=FixedGuard(state))
    try:
        with TestClient(app, headers={'X-API-Key': settings.api_key}) as client:
            report = client.post('/security-lab/run').json()
        predictions = {c['id']: c for c in report['cases'] if c['method'] == 'classifier'}
        assert predictions['classifier-malicious']['status'] == ('passed' if state == 'flagged' else 'failed')
        assert predictions['classifier-benign']['status'] == ('failed' if state == 'flagged' else 'passed')
        assert predictions['classifier-false-positive']['status'] == ('failed' if state == 'flagged' else 'passed')
        failed = predictions['classifier-false-positive'] if state == 'flagged' else predictions['classifier-malicious']
        assert failed['evidence']['result']['score'] == (.9 if state == 'flagged' else .1)
        assert 'false positive or false negative' in failed['error']
        assert report['summary']['failed'] == failures
        assert all('test-double' in c['evidence']['result']['model'] for c in predictions.values())
    finally:
        app.state.engine.dispose()


@pytest.mark.parametrize('state,expected_rule', [('flagged', 'PROMPT_INJECTION_REVIEW'), ('unavailable', 'PROMPT_SCREENING_INCOMPLETE')])
def test_screening_is_advisory_audited_and_cannot_decide(settings, state, expected_rule):
    app = create_app(replace(settings, prompt_guard_enabled=True), prompt_guard=FixedGuard(state))
    try:
        with TestClient(app, headers={'X-API-Key': settings.api_key}) as client:
            record = client.post('/instruments/upload', files={'file': ('valid-fdr.pdf', sample_pdf('valid-fdr.pdf'), 'application/pdf')}).json()
            result = client.post(f'/instruments/{record["id"]}/extract', json={'mode': 'demo'}).json()
            assert result['status'] == 'pending_review'
            assert result['prompt_guard']['status'] == state
            finding = next(f for f in result['findings'] if f['rule_id'] == expected_rule)
            events = result['audit']
            assert any(e['action'] == 'document_screening' and e['details']['advisory_only'] for e in events)
            assert not any(e['action'] in ('approve', 'reject') for e in events)
            endpoint = f'/instruments/{record["id"]}/review'
            assert client.post(endpoint, json={'action': 'approve', 'reason': 'Inspected original'}).status_code == 409
            assert client.post(endpoint, json={'action': 'resolve', 'finding_id': finding['id'], 'reason': 'Human inspected the synthetic document; classifier signal is advisory.'}).status_code == 200
            assert client.post(endpoint, json={'action': 'approve', 'reason': 'Human decision after resolving the signal.'}).status_code == 200
    finally:
        app.state.engine.dispose()


def test_incomplete_screening_never_counts_as_a_clear_test_result(settings):
    app = create_app(settings, prompt_guard=FixedGuard('clear', complete=False))
    try:
        with TestClient(app, headers={'X-API-Key': settings.api_key}) as client:
            report = client.post('/security-lab/run').json()
        assert all(case['status'] == 'skipped' for case in report['cases'] if case['method'] == 'classifier')
        for case in report['cases']:
            if case['method'] == 'classifier':
                assert case['evidence']['evaluated'] is True
                assert case['evidence']['complete'] is False
                assert case['evidence']['result']['score'] == .1
                assert case['evidence']['result']['chunks_screened'] == 1
    finally:
        app.state.engine.dispose()


def test_security_lab_can_be_disabled(settings):
    app = create_app(replace(settings, security_lab_enabled=False))
    try:
        with TestClient(app, headers={'X-API-Key': settings.api_key}) as client:
            assert client.get('/security-lab').status_code == 404
            assert client.post('/security-lab/run').status_code == 404
    finally:
        app.state.engine.dispose()


def test_lab_does_not_claim_disabled_rules_were_tested(settings):
    app = create_app(replace(settings, disabled_rules=' MINIMUM_AMOUNT , REQUIRED_FIELD, DATE_ORDER '))
    try:
        with TestClient(app, headers={'X-API-Key': settings.api_key}) as client:
            response = client.post('/security-lab/run')
            assert response.status_code == 200
            report = response.json()
        assert report['summary']['failed'] == 0
        for case in report['cases']:
            if case['id'] in ('missing-fields', 'financial-minimum', 'financial-evidence'):
                assert case['status'] == 'skipped'
                assert 'disabled' in case['observed']
    finally:
        app.state.engine.dispose()
