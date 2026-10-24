# VaultX

**Verify with evidence. Decide with confidence.**

A runnable, local-first MVP for **human-led Fixed Deposit Receipt review**. Upload a receipt, extract fields with page evidence, run deterministic checks, record corrections and decisions, and retain an append-only audit history. The application does not contact banks, establish authenticity, decide legal compliance, declare fraud, or release funds.

React + TypeScript + Vite + Tailwind CSS · FastAPI + Pydantic + SQLAlchemy · SQLite · PyMuPDF + Pillow · RapidOCR CPU OCR and optional PaddleOCR · configurable Gemma 4 adapter.

The **Security Lab** page runs real, isolated synthetic probes and retains their evidence, failures and skips. Optional Llama Prompt Guard 2 screening is disabled by default and never makes authorization or review decisions. See [security controls and limitations](SECURITY.md) and [classifier setup/licensing](docs/prompt-guard.md).

## Architecture

The browser calls `/api` through Vite's local proxy to FastAPI. FastAPI validates requests, reads private documents, runs extraction and deterministic rules, and commits business changes with audit events to SQLite. The Gemma and OCR adapters run only in the backend. Uploaded files use generated private storage names; document previews are fetched with the shared API key and rendered from browser blob URLs.

```text
React review workspace -> /api proxy -> FastAPI -> SQLite records + audit
                                          |----> private document storage
                                          |----> PyMuPDF / Pillow / optional OCR
                                          '----> sample parser OR configured Gemma runtime
```

## Quick start

Prerequisites: **Python 3.11** (tested) and **Node 24** or Node **22.12+**. No model credentials are needed for labelled-parser mode; the backend requirements now include CPU OCR. Run all commands from this repository root.

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-lock.txt
npm --prefix frontend ci
npm run setup
npm run dev
```

macOS / Linux:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-lock.txt
npm --prefix frontend ci
npm run setup
npm run dev
```

Open **http://127.0.0.1:5173**. The backend runs on **http://127.0.0.1:8001**, and interactive API documentation is at **http://127.0.0.1:8001/docs**. SQLite tables and private storage initialize automatically under ignored `.data/`. Stop both processes with Ctrl+C. `FDR_PYTHON` can override the interpreter used by the convenience scripts.

`npm run setup` creates an ignored `.env` with a unique random reviewer key. It preserves existing settings and fills a missing backend key. The local Vite development server may read the matching `VITE_API_KEY` as a convenience; production builds always omit that key and show **Connect your review workspace**. Enter the backend `API_KEY` from your private configuration when prompted. This shared key authorizes demo access; it is not a personal account or verified identity. Never commit `.env` or share its key publicly.

To run the servers separately:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001
```

```powershell
npm --prefix frontend run dev
```

The default port is 8001 because port 8000 was unavailable in the development environment. Set `BACKEND_PORT` in the root `.env` to change both the convenience launcher and Vite proxy; pass that port explicitly when running Uvicorn separately. `frontend/vite.config.ts` reads the root `.env`. Restart the servers after configuration changes. There is no deployment or public hosting requirement for this local Python application.

## Try the complete workflow

1. On Overview, click **Load sample workspace**. This idempotently registers five synthetic PDFs, extracts their labelled fields, validates them, and creates real database/audit entries. Dashboard totals are computed by the API.
2. Open **Review queue** and search or filter records. Inspect the original document beside extracted fields and page evidence.
3. Open the missing-fields receipt. Request clarification with a reason, then correct holder and maturity values with a reason to return it to pending review. Corrections trigger validation and leave original model/parser values intact.
4. In **Findings**, resolve an exception with an explanation or correct its underlying value. Approval requires successful extraction, pending review status, and every active finding resolved. Rejection also requires an extracted record and a reason.
5. Approve or reject, then inspect the record's **History** tab or workspace **Audit history**. Final decisions are read-only. Later duplicate records can still add findings to a previously finalized peer; its decision is preserved.
6. On **Upload FDR**, download a synthetic sample or choose a PDF, PNG, or JPEG. **Register & extract** performs actual API requests. A failed extraction preserves the uploaded record and an error event so you can retry explicitly.
7. Open **Security Lab** and click **Run security checks**. The predefined probes run against disposable synthetic databases/files. Inspect actual expected/observed results and expandable evidence. An unavailable classifier produces explicit skips, not successful detection results; reports remain available after refresh.

The canonical demo dataset is [`samples/vaultx/`](samples/vaultx/README.md): five fictional PDFs, each prominently watermarked **SYNTHETIC DEMO — NOT A REAL BANK DOCUMENT**, with independent ground-truth JSON. In a fresh database, upload them in numerical order using **Upload FDR** and choose sample mode: valid, low amount, duplicate, missing/ambiguous fields, then prompt injection. Review case 01 before uploading case 03 to demonstrate passing checks followed by duplicate detection. Unknown holder/maturity values remain null; the embedded instruction in case 05 cannot create a review decision. Regenerate with `npm run samples`; ground truth is never read by the generator or extraction adapters.

The existing **Load sample workspace** button and API downloads retain the older five fixtures in `samples/` for compatibility, including an invalid-dates case. Their valid/duplicate pair deliberately produces findings on both. Downloadable legacy dates follow generation time; seeded records retain their uploaded dates. The canonical dataset uses fixed fictional dates and is the set to use for the five-case MVP demonstration.

## Extraction modes and Gemma 4

The working local CPU profile uses **Qwen2.5 0.5B Instruct Q4_K_M** through llama.cpp, plus RapidOCR. See [installation, actual verification and model/OCR fixes](docs/inference-ocr.md). The existing `gemma` API mode and `GEMMA_*` variables support both Gemma and compatible alternatives. The UI identifies the exact model and per-page reading method; the parser remains an explicit choice.


**`EXTRACTION_MODE=demo` (default):** a conservative parser reads explicitly labelled embedded PDF text, or OCR text when OCR is enabled. This mode makes no model request, manufactures no values, and is labelled **Sample extraction · no AI inference**. Missing, unreadable, or conflicting values remain null. A scan without working OCR produces missing-field findings rather than invented sample values.

**`EXTRACTION_MODE=gemma`:** a backend-only adapter calls an OpenAI-compatible `/chat/completions` endpoint. Embedded PDF text is read with PyMuPDF. Scanned pages and images use optional OCR; when text is unavailable, up to six page images are sent to a vision-capable runtime. The adapter bounds input, uses a timeout, treats content as untrusted, and accepts only schema-valid JSON. It cannot make review decisions. Credentials never go into a model prompt or a frontend variable.

For an independently installed Ollama runtime, an example configuration is:

```dotenv
EXTRACTION_MODE=gemma
GEMMA_BASE_URL=http://127.0.0.1:11434/v1
GEMMA_MODEL=gemma4:e2b
GEMMA_API_KEY=ollama
GEMMA_TIMEOUT_SECONDS=180
```

Ollama's local API ignores its placeholder API key. Remote services require `GEMMA_API_KEY`. The base URL must include `/v1` when that is your runtime's OpenAI-compatible path; the adapter appends `/chat/completions`.

Before selecting a model, verify that the runtime supports the exact **Gemma 4** identifier, JSON responses, and images if you need scanned-document inference:

```sh
ollama pull gemma4:e2b
ollama list
ollama show gemma4:e2b
curl http://127.0.0.1:11434/v1/models
```

These are optional runtime setup commands; model downloads can be large. Use a suitable supported Gemma 4 variant for your hardware. Inspect the served model's metadata, perform an extraction, and inspect its retained evidence. A configured model name is not proof of its identity: `/health` deliberately reports `model_verified: false`. Regression tests simulate provider errors; the real local verifier exercises Qwen inference. **Gemma weights themselves have not been runtime-tested here**. Official references: [Gemma 4 model card](https://ai.google.dev/gemma/docs/core/model_card_4), [Ollama Gemma 4 library](https://ollama.com/library/gemma4), and [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility).

The exact optional example is **`gemma4:e2b`**, distributed under Apache-2.0. Google's [memory estimates](https://ai.google.dev/gemma/docs/core) list approximately 11.4 GB BF16, 5.7 GB SFP8, or 2.9 GB Q4_0 just to load E2B; context and runtime add memory. The [Ollama tag](https://ollama.com/library/gemma4:e2b) currently lists platform-dependent 4.6 GB llama.cpp / 7.5 GB MLX downloads. Ollama, torch and transformers are absent; a bounded llama.cpp CPU runtime and a smaller Qwen model were installed instead. RapidOCR runs on ONNX Runtime. Do not describe Qwen or the labelled parser as Gemma inference.

Missing configuration, malformed model JSON, unsupported endpoints, timeouts, and service failures create `extraction_failed` audit events and populate `extraction_error`. They never silently fall back to sample mode. The extract API returns the persisted record with HTTP 200 on these processing failures; clients must inspect `extraction_error`. The frontend does so and shows failure. Choose sample mode explicitly to recover without credentials. Failed retries preserve earlier extraction history; retry extraction successfully before correcting fields.

### Scanned PDFs and images

CPU RapidOCR and ONNX Runtime are included in the backend requirements. `OCR_ENABLED=true`, `OCR_ENGINE=rapidocr`, and `OCR_DPI=200` read raster scans and image-bearing mixed pages. Embedded text remains available, OCR words are reconstructed into rows, and each extraction retains page methods and engine provenance. Enabled but missing/broken OCR produces a persisted failure; it cannot silently claim successful reading. PaddleOCR remains an optional separate engine.

`ocr_available` reports dependency availability; `ocr_runtime_verified` becomes true only after successful execution in that process. The [real verifier](docs/inference-ocr.md#real-verification) checks scanned PDF, PNG and mixed-page fixtures against independent ground truth, separately from mocked regression tests. Explicitly disabling OCR keeps text-only processing; unreadable image input then requires a compatible vision model or clarification.

## Configuration

Copy [`.env.example`](.env.example) to `.env`. Backend settings read the root file; Vite exposes only `VITE_` variables to the browser.

| Variable | Default / purpose |
| --- | --- |
| `API_KEY` | Required unique shared reviewer key; generated locally by `npm run setup`. No built-in default. |
| `VITE_API_KEY` | Optional local development convenience only; always omitted from production builds. |
| `BACKEND_PORT` | `8001`; convenience launcher and Vite proxy. |
| `FRONTEND_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173`; explicit CORS allowlist. |
| `DATABASE_URL` | Absolute SQLite URL for `.data/fdr.db`. |
| `STORAGE_DIR` | Absolute path to `.data/documents`. |
| `MAX_UPLOAD_MB` / `MAX_DOCUMENT_PAGES` | `10` / `30`. |
| `REQUEST_TIMEOUT_SECONDS` | `30`; deadline to receive a request body, not a native parser execution deadline. |
| `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` | `600` / `60`; process-local per-client-IP budget including invalid-key attempts. |
| `MINIMUM_AMOUNT` / `DEFAULT_CURRENCY` | `10000` / `INR`; Decimal threshold, no FX conversion. |
| `REQUIRED_FIELDS` | All seven extraction field names, comma-separated. |
| `DISABLED_RULES` | Empty; optional comma-separated rule IDs below. |
| `REMINDER_DAYS` | `30`; inclusive current date through reminder date. |
| `EXTRACTION_MODE` | `demo` or `gemma`; UI can explicitly choose either. |
| `GEMMA_BASE_URL` / `GEMMA_MODEL` / `GEMMA_API_KEY` | Runtime URL, exact served model identifier, backend credential. |
| `GEMMA_TIMEOUT_SECONDS` | `180`; includes room for CPU inference and model loading. |
| `GEMMA_RESPONSE_FORMAT` / `GEMMA_MAX_TOKENS` | `json_schema` / `1600`; explicit `json_object` compatibility mode is available. |
| `GEMMA_SUPPORTS_VISION` | `false`; unreadable pages are rejected for text-only models. |
| `LOCAL_MODEL_ENABLED` | `false`; opt-in local CPU model startup in `npm run dev`. |
| `OCR_ENABLED` / `OCR_ENGINE` / `OCR_DPI` | `true` / `rapidocr` / `200`; CPU OCR. |
| `PROMPT_GUARD_ENABLED` | `false`; optional cache-only text classifier. |
| `PROMPT_GUARD_MODEL` | `meta-llama/Llama-Prompt-Guard-2-22M`; official 86M variant also supported. |
| `PROMPT_GUARD_THRESHOLD` / `PROMPT_GUARD_MAX_CHUNKS` | `0.5` / `64`; advisory score threshold and bounded windows. |
| `PROMPT_GUARD_DEVICE` / `PROMPT_GUARD_CACHE_DIR` | `cpu` / default HF cache; no automatic downloads. |
| `SECURITY_LAB_ENABLED` | `true`; authenticated predefined security probes and persisted reports. |
| `VITE_API_BASE_URL` | `/api`; override for a separate frontend/API deployment. |
| `VITE_API_PROXY_TARGET` | Optional Vite development/preview proxy override. |

Relative custom database/storage paths resolve from the server working directory; the automatic defaults always use the repository root. Configure currency and rules consistently. A different currency produces a manual-review finding and does not undergo an invented conversion.

## Rules, review states, and persistence

Extracted fields are `instrument_number`, `bank_name`, `amount`, `currency`, `issue_date`, `maturity_date`, and `holder_name`. Values are strings or null. Amount validation uses Python `Decimal`, and dates require valid ISO `YYYY-MM-DD` calendar dates. Decimal amounts support two fractional digits and at most `999999999999999999.99`. Frontend amount formatting preserves decimal precision.

Rules emit structured findings with ID, rule ID, severity, field, observed/expected values, explanation, resolution flag, and resolution reason:

`REQUIRED_FIELD`, `DUPLICATE_NUMBER`, `INVALID_AMOUNT`, `MINIMUM_AMOUNT`, `CURRENCY_REVIEW`, `INVALID_DATE`, `DATE_ORDER`, `EXTRACTION_REQUIRED`, `UNCERTAIN_EXTRACTION`, `EVIDENCE_MISSING`, `EVIDENCE_UNVERIFIABLE`, `EVIDENCE_CONFLICT`, `VALUE_EVIDENCE_CONFLICT`. These configurable validation rules remain separate from optional screening findings `PROMPT_INJECTION_REVIEW` and `PROMPT_SCREENING_INCOMPLETE`; the latter are resolved through explicit human review.

Evidence quotes are checked against page text and values, with exact Decimal matching for amounts and boundaries for instrument identifiers. Images without extracted text require human evidence review. A human correction and its reason supersede automatic evidence checks for the corrected field. Duplicate comparisons ignore case and whitespace; changing duplicate peers reopens affected findings, including on finalized peers, without altering previous decisions. Rules flag review issues, not proof of fraud.

Normal states:

```text
uploaded -> pending_review -> approved | rejected
                    |
                    v
          clarification_requested
                    |
             correction/re-extraction
                    v
              pending_review
```

All corrections, finding resolutions, clarification requests, and decisions require a reason. Approval runs validation again and requires pending review, a successful extraction, and no unresolved findings. Rejection is also allowed from clarification after extraction. Extraction and corrections are blocked after a final decision. Re-extraction is blocked after manual corrections to avoid overwriting reviewed values. Explicit same-value manual confirmation is available through the API with a reason.

SQLAlchemy models persist instruments, one private document per instrument, append-only extraction snapshots, corrected values, versioned findings, review actions, audit events, screening snapshots and Security Lab reports. Original extraction values/evidence remain separate from corrections. Each business change and its audit event commit in the same transaction. Failed writes roll back and remove newly created files. SQLite triggers prevent updates/deletes of extraction, review, audit, screening and Lab report history. There is no history edit/delete API. New screening/report tables are created automatically without changing existing instrument columns; existing data is preserved. General schema migrations are outside this MVP.

## API

`/health`, `/docs`, and `/openapi.json` are public. Other routes require `X-API-Key`; optional `X-Actor` supplies the demo audit name (default `Local reviewer`). Reviewer identity is self-asserted, not authenticated identity.

| Method | Route | Behavior |
| --- | --- | --- |
| GET | `/health` | Process/configuration/adapter availability. |
| GET | `/dashboard` | Real totals, recent activity, upcoming maturities. |
| GET | `/instruments` | `q`, `status`, `page`, `page_size` (1–100). |
| GET | `/instruments/{id}` | Effective fields, original extraction, findings, audit. |
| POST | `/instruments/upload` | Multipart `file`; PDF/PNG/JPEG; HTTP 201. |
| POST | `/instruments/{id}/extract` | Optional `{"mode":"demo"}` or `{"mode":"gemma"}`; validates successful output. |
| POST | `/instruments/{id}/validate` | Re-run deterministic rules. |
| POST | `/instruments/{id}/review` | `correct`, `resolve`, `clarify`, `approve`, `reject`. |
| GET | `/instruments/{id}/document` | Authenticated original file, no-store response. |
| GET | `/instruments/{id}/audit` | Full record history, oldest first. |
| GET | `/audit` | Recent workspace events; `limit` default 100, maximum 500. |
| GET | `/samples`, `/samples/{name}` | Synthetic fixture list / generated PDF. |
| POST | `/demo/seed` | Idempotent synthetic sample registration and extraction. |
| GET | `/security-lab` | Implemented-control inventory, truthful classifier status, latest saved report. |
| POST | `/security-lab/run` | Run predefined isolated probes, retain actual results/evidence; one concurrent run per process. |

Example review bodies:

```json
{"action":"correct","fields":{"holder_name":"Confirmed institution"},"reason":"Confirmed against supplied supporting evidence."}
```

```json
{"action":"resolve","finding_id":"<finding UUID>","reason":"Compared both records and documented the duplicate registration."}
```

```json
{"action":"approve","reason":"Reviewed the original and resolved every exception."}
```

Errors include 400 malformed/active documents or invalid request framing, 401 invalid key, 404 missing record/finding/file, 408 body-receive timeout, 409 invalid transitions/unresolved findings or an active Lab run, 413 size limit, 415 unsupported/mismatched file type, 422 invalid input, 429 rate limit (with `Retry-After`), and 503 unavailable private storage/Lab execution. Model-processing errors follow the persisted-record behavior described above.

## Verification

```powershell
npm run test:backend
npm test
npm run test:setup
npm run build
```

Or run `python -m pytest backend/tests -q` with the virtual environment interpreter. Backend tests use temporary databases/storage and synthetic fixtures. Coverage includes valid and unreadable receipts, duplicate peers, amount/date rules, exact evidence checks and Unicode, malformed uploads, model schema errors/timeouts/service failures, corrections, clarification/decision transitions, persistence, rollback, private file authorization, maturity windows, and immutable history. Frontend tests verify authenticated API requests, required reasons, error propagation, filters, precision, and extraction failures. `backend/requirements-lock.txt` and `frontend/package-lock.json` record tested dependencies; `backend/requirements.txt` contains direct requirements. SQLAlchemy is pinned to the version compatible with the tested Windows environment.

With both servers running and Chrome installed, an optional dependency-free browser check exercises the real UI against synthetic documents:

```sh
node scripts/smoke-browser.mjs
```

Set `CHROME_BIN` outside Windows or for a nonstandard browser location. Optional overrides are `SMOKE_FRONTEND_URL`, `SMOKE_BACKEND_URL`, `SMOKE_API_KEY`, and `SMOKE_DEBUG_PORT`. The script reads the private root `API_KEY` when `SMOKE_API_KEY` is absent, and handles the runtime connection screen. It writes screenshots/results under ignored `.local/` and creates synthetic review records in the running database. Do not point it at real operational data. See [verification evidence](docs/security-verification.md) for isolated database commands.

The original 43 backend regression tests remain part of the expanded security suite. Security-specific pytest coverage includes streamed limits, malformed/benign documents, private storage failures, simulated classifier false positives/negatives, schema/authority boundaries, real API authorization, immutable history and honest Lab reports. Real model evaluation is explicitly skipped without an enabled compatible cache. The backend suite emits one installed Starlette/httpx TestClient deprecation warning; it does not fail the tests. Gemma weights, Prompt Guard and PaddleOCR remain unverified; the separate real verifier exercises the installed Qwen/RapidOCR profile. See [SECURITY.md](SECURITY.md) for the distinction between tested controls and guaranteed security.

See the current [inference/OCR verification](docs/inference-ocr.md#observed-verification) for executed commands, exact results, unavailable inference/OCR, and browser evidence. No lint command is configured; the production build includes TypeScript checks.

## Security and limits

This is a **local, single-user demonstration**, not a secure multi-user production system. A frontend key or reviewer name is not real authentication. Keep both servers on loopback; add server-side identity, per-user authorization, deployment hardening, and audit retention controls before public use. Documents live outside public frontend assets and are fetched with the shared key. Authorization precedes body parsing, actual request bytes are bounded, and documents undergo content validation. Conservative PDF action/attachment/repaired-file checks and full image decoding augment existing size/page/dimension limits. Files use exclusive generated names with storage-failure cleanup. Secrets, uploaded documents, databases, environments, local model weights and QA artifacts are ignored by Git. These checks do not provide malware isolation or a detection guarantee.

Request bodies have a receive deadline and a process-local rate limit. The limit does not trust forwarded IP headers and can group users behind a reverse proxy. Native PDF/OCR execution is not terminated by that deadline; hostile production documents require worker process isolation and resource limits. Extraction rejects page/total text limits and excessive unreadable page images explicitly, rather than silently dropping content. Evidence amount comparisons preserve source signs, including accounting parentheses. Interest rate extraction is not implemented; the seven required fields above define this MVP.

The SQLite implementation serializes transactions, including reads. A live inference call holds its transaction, so concurrent requests can wait or reach the busy timeout. It is designed for local review, not concurrent production workloads. Dashboard/search load records in memory; workspace audit shows the latest 100 events by default while record history remains complete. Filesystem writes and SQLite are coordinated with rollback cleanup, but are not a distributed crash-safe transaction. Native document parsers should be isolated for hostile production workloads.

Maturity reminders are in-app and calculated when the dashboard loads; there is no background scheduler, email integration, bank integration, fund transfer, or authenticity guarantee. Real inference and OCR quality depend on the configured runtime and document. Real Qwen and RapidOCR execution is checked with synthetic fixtures; this does not establish performance on arbitrary financial documents. Configuration does not prove model identity. The model never has permission to approve, reject, modify audits, or act on funds.

## Optional deployment preparation

Optional [Render preparation](docs/deployment.md) documents separate backend/static services and persistent storage requirements. It was not deployed or live-verified; the local workflow remains the recommended demo.

## License and contributing

**AGPL-3.0-only**, see the existing [LICENSE](LICENSE), which was preserved. Required PyMuPDF/MuPDF uses [AGPL or a separate commercial license](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright). No license change was made.

Gemma 4 weights use [Apache-2.0](https://ai.google.dev/gemma/docs/core/model_card_4), and PaddleOCR uses [Apache-2.0](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE). React, Vite, Tailwind, FastAPI, Pydantic, SQLAlchemy, and other dependencies retain their respective licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Hosted inference services have independent terms and are not claimed to be open source. No model weights or hosted service are tracked in this repository; local setup stores separately downloaded weights in ignored folders.

Optional Llama Prompt Guard 2 weights use the [Llama 4 Community License](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-22M/blob/main/LICENSE), with separate access, use and attribution conditions, **not Apache-2.0**. No weights or acceptance of Meta's terms are bundled. The UI includes conditional **Built with Llama** attribution when screening is enabled. Review [optional setup](docs/prompt-guard.md) before acquiring model files; no additional model installation is needed to run the core application or Security Lab.

Contributions should retain nulls for unknown values, require reasons for review changes, keep original extractions/audits intact, and include regression tests for business-rule changes. Use only synthetic or properly authorized, private test data. Never commit receipts, credentials, local databases, or model access tokens.
