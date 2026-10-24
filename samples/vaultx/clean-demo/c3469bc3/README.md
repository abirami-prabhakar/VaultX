# VaultX complete synthetic demo batch `c3469bc3`

Every page displays **SYNTHETIC DEMO — NOT A REAL BANK DOCUMENT**. All institutions, holders,
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
.\.venv\Scripts\python.exe scripts/generate-clean-dataset.py
```

The default is a fresh eight-character UUID prefix. To choose a repeatable short
batch identifier, append `--batch MyDemo01` (1–8 ASCII letters or digits).
Existing batch directories are never overwritten. This batch was generated with
`--batch c3469bc3`.
