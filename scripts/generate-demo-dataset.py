"""Write the five reproducible VaultX demo PDFs, never extraction results/truth."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.demo_dataset import DEMO_SAMPLES, demo_pdf

destination = ROOT / 'samples' / 'vaultx'
destination.mkdir(parents=True, exist_ok=True)
for sample in DEMO_SAMPLES:
    path = destination / sample['name']
    data = demo_pdf(sample['name'])
    path.write_bytes(data)
    print(f"Wrote fictional demo PDF: {path.name} ({len(data)} bytes)")
print('Independent ground-truth JSON was left unchanged.')
