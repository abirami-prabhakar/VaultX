"""Generate complete, unique fictional FDRs without changing application behavior.

Only PyMuPDF is required. Each run creates a new batch and never overwrites one.
The manifest records source values for a separate extractor/verifier to compare.
"""
import argparse
import json
from pathlib import Path
import re
from uuid import uuid4

import pymupdf as fitz


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / 'samples' / 'vaultx' / 'clean-demo'
WATERMARK = 'SYNTHETIC DEMO — NOT A REAL BANK DOCUMENT'
LABELS = {
    'instrument_number': 'FDR Number',
    'bank_name': 'Bank Name',
    'holder_name': 'Holder Name',
    'amount': 'Deposit Amount',
    'currency': 'Currency',
    'issue_date': 'Issue Date',
    'maturity_date': 'Maturity Date',
}
CASES = (
    ('01_complete_text.pdf', 'text', 'Cedar', 'Amber', '250000.00', '2027-10-01'),
    ('02_complete_text.pdf', 'text', 'Juniper', 'Coral', '300000.00', '2027-11-01'),
    ('03_complete_text.pdf', 'text', 'Harbor', 'Indigo', '450000.00', '2027-12-01'),
    ('04_complete_scan.pdf', 'scanned', 'Willow', 'Ivory', '600000.00', '2028-01-01'),
    ('05_complete_mixed.pdf', 'mixed', 'Maple', 'Teal', '750000.00', '2028-02-01'),
)


def text(page, point, value, *, size=13, bold=False, color=(0.063, 0.106, 0.2)):
    writer = fitz.TextWriter(page.rect)
    writer.append(point, value, font=fitz.Font('hebo' if bold else 'helv'), fontsize=size)
    writer.write_text(page, color=color)


def receipt_page(document, fields):
    page = document.new_page(width=595, height=842)
    page.draw_rect(fitz.Rect(35, 30, 560, 812), color=(0.063, 0.106, 0.2), width=1)
    page.draw_rect(fitz.Rect(35, 30, 560, 110), color=None, fill=(0.063, 0.106, 0.2))
    text(page, (55, 70), 'VaultX', size=28, bold=True, color=(1, 1, 1))
    text(page, (55, 94), 'Verify with evidence. Decide with confidence.', size=11,
         color=(0.62, 0.91, 0.87))
    page.draw_rect(fitz.Rect(45, 128, 550, 164), color=None, fill=(1, 0.94, 0.78))
    text(page, (56, 151), WATERMARK, size=13, bold=True)
    text(page, (55, 199), 'FICTIONAL FIXED DEPOSIT RECEIPT', size=14, bold=True)
    text(page, (55, 222), 'Complete test data. No real institution, person, or funds.', size=11)
    for index, (field, label) in enumerate(LABELS.items()):
        text(page, (55, 274 + index * 45), f'{label}: {fields[field]}', size=13)
    text(page, (55, 670), 'All issuing institutions and depositors are explicitly fictional.', size=11)
    text(page, (55, 750), 'SYNTHETIC SOFTWARE TESTING ONLY', size=13, bold=True)
    text(page, (55, 774), 'No bank seal, signature, authenticity claim, or real deposit.', size=11)
    return page


def receipt_pdf(fields, kind):
    with fitz.open() as source, fitz.open() as output:
        page = receipt_page(source, fields)
        if kind in ('text', 'mixed'):
            output.insert_pdf(source)
        if kind in ('scanned', 'mixed'):
            # Rasterize the complete, watermarked page at 144 DPI. There is no
            # hidden text layer: the application must genuinely use OCR/vision.
            raster = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            output.new_page(width=page.rect.width, height=page.rect.height).insert_image(
                page.rect, stream=raster.tobytes('png'))
        output.set_metadata({
            'title': 'VaultX complete fictional FDR — synthetic testing only',
            'author': 'VaultX synthetic dataset generator',
            'subject': 'No real issuing bank, depositor, deposit, seal, or signature',
            'creationDate': 'D:20261001000000Z',
            'modDate': 'D:20261001000000Z',
        })
        return output.tobytes(no_new_id=True)


def generate(batch_id):
    if not re.fullmatch(r'[A-Za-z0-9]{1,8}', batch_id, flags=re.ASCII):
        raise ValueError('Batch ID must contain 1–8 ASCII letters or digits.')
    batch_path = DESTINATION / batch_id
    # Atomic directory creation rejects an existing batch before any file write.
    batch_path.mkdir(parents=True, exist_ok=False)
    manifest = {
        'batch_id': batch_id,
        'synthetic': True,
        'watermark': WATERMARK,
        'generated_with': 'scripts/generate-clean-dataset.py (PyMuPDF)',
        'expected_configuration': {'minimum_amount': '10000', 'currency': 'INR'},
        'documents': [],
    }
    for number, (filename, kind, bank, holder, amount, maturity) in enumerate(CASES, 1):
        fields = {
            'instrument_number': f'VX-CLEAN-{batch_id.upper()}-{number:03d}',
            'bank_name': f'Fictional {bank} Demo Institution',
            'holder_name': f'Fictional {holder} Test Depositor',
            'amount': amount,
            'currency': 'INR',
            'issue_date': '2026-10-01',
            'maturity_date': maturity,
        }
        with (batch_path / filename).open('xb') as output:
            output.write(receipt_pdf(fields, kind))
        manifest['documents'].append({
            'filename': filename,
            'kind': kind,
            'page_count': 2 if kind == 'mixed' else 1,
            'expected_fields': fields,
        })
    with (batch_path / 'manifest.json').open('x', encoding='utf-8', newline='\n') as output:
        json.dump(manifest, output, indent=2, ensure_ascii=False)
        output.write('\n')
    readme = f'''# VaultX complete synthetic demo batch `{batch_id}`

Every page displays **{WATERMARK}**. All institutions, holders,
identifiers and deposits are fictional. There are no bank seals or signatures.

This batch contains three text PDFs, one image-only scanned PDF, and one mixed
PDF with a digital page followed by a scanned page showing the same values.
The scan pages have no hidden text; they require working OCR or vision inference.
`manifest.json` contains the seven exact source values for each document, its
kind and its page count. It is separate from actual extraction results.

Import each PDF **once**. Each receipt has a complete set of labelled fields,
a unique batch-specific FDR number, an INR amount of at least 250000.00, and
consistent dates. With the default INR/10000 minimum rules, the expected
configured checks pass when extraction faithfully preserves these values.
This expectation is not an executed test result or proof of authenticity.
Importing the same identifiers again correctly creates duplicate findings.

A successful extraction stays **pending human review**; no automatic approval is
expected or authorized. No rule, security check, or existing failure fixture was
changed to make this dataset pass.

Generate another fresh batch from the repository root:

```powershell
.\\.venv\\Scripts\\python.exe scripts/generate-clean-dataset.py
```

The default is a fresh eight-character UUID prefix. To choose a repeatable short
batch identifier, append `--batch MyDemo01` (1–8 ASCII letters or digits).
Existing batch directories are never overwritten. This batch was generated with
`--batch {batch_id}`.
'''
    (batch_path / 'README.md').write_text(readme, encoding='utf-8', newline='\n')
    return batch_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', default=uuid4().hex[:8],
                        help='Optional 1–8 ASCII letter/digit identifier; must not already exist.')
    args = parser.parse_args()
    try:
        batch_path = generate(args.batch)
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    print(f'Created five synthetic FDR PDFs: {batch_path}')
    print(f'Independent verification manifest: {batch_path / "manifest.json"}')


if __name__ == '__main__':
    main()
