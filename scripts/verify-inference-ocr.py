"""Run real local inference/OCR on synthetic documents in a disposable database.

No mocks, optional skips, operational database writes or automatic approvals.
Requires the configured model endpoint and installed OCR dependencies.
"""
from dataclasses import replace
import argparse
import io
import json
from pathlib import Path
import sys
import re
from tempfile import TemporaryDirectory
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from fastapi.testclient import TestClient
import pymupdf as fitz
from PIL import Image
from app.config import Settings
from app.main import create_app


def scan_document(source):
    with fitz.open(source) as pdf:
        image = pdf[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes('png')
        with fitz.open() as scan:
            page = scan.new_page(width=pdf[0].rect.width, height=pdf[0].rect.height)
            page.insert_image(page.rect, stream=image)
            assert not page.get_text().strip()
            return image, scan.tobytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--failure-probes', action='store_true', help='Also exercise real-runtime truncation and timeout failure paths')
    args = parser.parse_args()
    results = []
    failure_probes = []
    config = Settings()
    with TemporaryDirectory(prefix='vaultx-real-') as folder:
        settings = replace(config, database_url=f'sqlite:///{Path(folder).as_posix()}/test.db',
                           storage_dir=Path(folder) / 'documents', ocr_enabled=True,
                           prompt_guard_enabled=False, rate_limit_requests=10000)
        app = create_app(settings, include_security_lab=False)
        def run(name, data, mime, mode, expected):
            started = perf_counter()
            uploaded = client.post('/instruments/upload', files={'file': (name, data, mime)})
            assert uploaded.status_code == 201, uploaded.text
            record = client.post(f'/instruments/{uploaded.json()["id"]}/extract', json={'mode': mode}).json()
            assert not record['extraction_error'], record['extraction_error']
            assert record['fields'] == expected, json.dumps({'expected': expected, 'actual': record['fields']})
            assert not any(f['rule_id'] in ('EVIDENCE_MISSING', 'EVIDENCE_CONFLICT', 'VALUE_EVIDENCE_CONFLICT', 'EVIDENCE_UNVERIFIABLE') for f in record['findings']), record['findings']
            if mode == 'gemma':
                assert record['original_extraction']['model'] == settings.gemma_model
            assert record['status'] == 'pending_review'
            assert not any(e['action'] in ('approve', 'reject') for e in record['audit'])
            results.append({'name': name, 'mode': mode, 'passed': True, 'seconds': round(perf_counter() - started, 2),
                            'fields': record['fields'], 'provenance': record['original_extraction']['provenance'],
                            'findings': [f['rule_id'] for f in record['findings']]})
            print(f'PASS {name} ({mode}, {results[-1]["seconds"]}s)', flush=True)
            return record
        try:
            with TestClient(app, headers={'X-API-Key': settings.api_key, 'X-Actor': 'Synthetic real-inference verifier'}) as client:
                dataset = ROOT / 'samples' / 'vaultx'
                valid = dataset / '01_valid_fdr.pdf'
                expected = json.loads(valid.with_suffix('.ground-truth.json').read_text(encoding='utf-8'))['fields']
                png, scan = scan_document(valid)
                run('synthetic-scan.pdf', scan, 'application/pdf', 'demo', expected)
                run('synthetic-image.png', png, 'image/png', 'demo', expected)
                jpeg = io.BytesIO()
                with Image.open(io.BytesIO(png)) as image:
                    image.convert('RGB').save(jpeg, format='JPEG', quality=90)
                run('synthetic-image.jpg', jpeg.getvalue(), 'image/jpeg', 'demo', expected)
                with fitz.open(valid) as mixed, fitz.open(stream=scan, filetype='pdf') as scan_pdf:
                    mixed.insert_pdf(scan_pdf)
                    run('synthetic-mixed.pdf', mixed.tobytes(), 'application/pdf', 'demo', expected)
                with fitz.open() as hybrid:
                    page = hybrid.new_page(width=595, height=882)
                    page.insert_text((25, 20), 'VaultX synthetic mixed-content digital header')
                    page.insert_image(fitz.Rect(0, 40, 595, 882), stream=png)
                    assert len(page.get_text().strip()) > 20
                    run('synthetic-hybrid-page.pdf', hybrid.tobytes(), 'application/pdf', 'demo', expected)
                run('synthetic-text-model.pdf', valid.read_bytes(), 'application/pdf', 'gemma', expected)
                run('synthetic-scan-model.pdf', scan, 'application/pdf', 'gemma', expected)
                for name in ('04_missing_fields_fdr', '05_prompt_injection_fdr'):
                    truth = json.loads((dataset / f'{name}.ground-truth.json').read_text(encoding='utf-8'))['fields']
                    run(f'{name}.pdf', (dataset / f'{name}.pdf').read_bytes(), 'application/pdf', 'gemma', truth)
                with fitz.open() as unreadable:
                    page = unreadable.new_page()
                    page.insert_text((40, 40), 'SYNTHETIC DEMO - NOT A REAL BANK DOCUMENT\nVaultX review workspace\nThe receipt details are unreadable.')
                    run('synthetic-insufficient-evidence.pdf', unreadable.tobytes(), 'application/pdf', 'gemma', dict.fromkeys(expected))
                health = client.get('/health').json()
                assert health['ocr_runtime_verified'] and health['inference_runtime_verified']
                if args.failure_probes:
                    for failure in ('truncated', 'timed out'):
                        uploaded = client.post('/instruments/upload', files={'file': ('synthetic-runtime-failure.pdf', valid.read_bytes(), 'application/pdf')})
                        assert uploaded.status_code == 201, uploaded.text
                        token_limit, timeout = settings.gemma_max_tokens, settings.gemma_timeout
                        try:
                            if failure == 'truncated':
                                settings.gemma_max_tokens = 128
                            else:
                                settings.gemma_timeout = 0.01
                            failed = client.post(f'/instruments/{uploaded.json()["id"]}/extract', json={'mode': 'gemma'}).json()
                        finally:
                            settings.gemma_max_tokens, settings.gemma_timeout = token_limit, timeout
                        assert failure in (failed['extraction_error'] or ''), failed
                        assert failed['status'] == 'uploaded' and failed['original_extraction'] is None
                        assert all(value is None for value in failed['fields'].values())
                        assert any(e['action'] == 'extraction_failed' for e in failed['audit'])
                        assert not any(e['action'] in ('extraction', 'approve', 'reject') for e in failed['audit'])
                        failure_probes.append({'case': failure, 'passed': True, 'observed': failed['extraction_error']})
                        print(f'PASS real-runtime fail-closed probe: {failure}', flush=True)
        finally:
            app.state.engine.dispose()
            output = ROOT / '.local' / 'inference-ocr-verification.json'
            output.parent.mkdir(exist_ok=True)
            report = json.dumps({'model': settings.gemma_model, 'ocr_engine': settings.ocr_engine,
                                 'passed': len(results), 'expected_checks': 10,
                                 'completed': len(results) == 10 and len(failure_probes) == (2 if args.failure_probes else 0),
                                 'expected_failure_probes': 2 if args.failure_probes else 0,
                                 'failure_probes': failure_probes, 'results': results}, indent=2)
            output.write_text(report, encoding='utf-8')
            model_slug = re.sub(r'[^A-Za-z0-9._-]', '_', settings.gemma_model)[:100]
            output.with_name(f'inference-ocr-{model_slug}.json').write_text(report, encoding='utf-8')
    print(f'{len(results)}/10 real inference/OCR checks passed ({settings.gemma_model})', flush=True)
    if args.failure_probes:
        print(f'{len(failure_probes)}/2 real-runtime failure probes passed', flush=True)


if __name__ == '__main__':
    main()
