# VaultX MVP verification (baseline before inference/OCR fixes)

**Superseded for model/OCR status:** see [the current inference/OCR guide](inference-ocr.md) and its real verifier. The results below record the earlier baseline; they are not the current runtime status.


Observed **24 October 2026**, Windows, Python **3.11.9**, Node **24.14.1**, npm **11.11.0**. Existing uncommitted work was preserved. Dependencies were already installed; no new package or model installation was necessary. Results describe these fixtures and configuration, not future documents or production security.

## Executed checks

| Command / check | Final observed result |
| --- | --- |
| `.\.venv\Scripts\python.exe -m pytest backend/tests -q` | **156 passed, 0 failed, 1 skipped**, one installed Starlette/httpx deprecation warning. |
| `npm run test:backend` (final wrapper rerun after legacy sample branding) | **156 passed, 0 failed, 1 skipped**, same deprecation warning. |
| `.\.venv\Scripts\python.exe -m pytest backend/tests/test_demo_dataset.py -q` | **15 passed, 0 failed**; included in the full backend total. |
| `npm --prefix frontend test` | **16 passed, 0 failed**. |
| `npm run test:setup` | **4 passed, 0 failed**. |
| `npm run build` | **Passed**, including `tsc -b` and Vite production bundling. |
| Production asset inspection | Synthetic key sentinel and configured local reviewer keys absent from all three built asset files. |
| `node scripts/smoke-browser.mjs` against Vite development | **12 passed, 0 failed**. |
| Same browser script against production preview on port 4173 | **12 passed, 0 failed**, including runtime reviewer-key entry. |
| `node .local/verify-live.mjs` (ad hoc live API probe) | **8 passed, 0 failed**: all five canonical PDFs against independent JSON, unauthorized access, audit deletion rejection, isolated Lab run. |
| Live `POST /security-lab/run` | **12 passed, 0 failed, 3 not run** of 15 cases. Real classifier evaluations were unavailable. |
| `npm --prefix frontend audit --json` | **0 reported vulnerabilities**. |
| `.\.venv\Scripts\python.exe -m pip check` | **No broken requirements found**; this checks compatibility, not vulnerability advisories. |
| `npm run setup`, `npm run samples` | **Passed**; generated private local configuration and all five reproducible PDFs without rewriting ground truth. |
| `git diff --check` | **Passed**; Git emitted Windows line-ending notices. |

The backend suite covers schema and model-response contracts, deterministic financial/evidence checks, safe uploads, early authorization, body deadlines, rate limits, private documents, review transitions/reasons, original/correction separation, immutable database history, rollback, dataset ground truth, unreadable scans and honest Lab reports. Model doubles are explicitly simulated and do not establish real model accuracy. The single skipped pytest requires opt-in real Prompt Guard inference and a compatible cache. No lint command/configuration exists; TypeScript checking is part of the build.

The first setup test execution exposed a real empty-key parsing bug: whitespace matching crossed into the next environment line. It was fixed and all four setup regressions passed. Node/esbuild subprocess launches initially hit sandbox `EPERM`; approved reruns succeeded. Stale frontend tests were repaired for explicit reviewer-key behavior. No unresolved automated test failures remain in the executed checks.

## Live workflow and persistence

The browser exercised dashboard/seed data, register search/filtering, PDF upload and authenticated blob preview, evidence display, finding resolution, clarification/correction, approval/rejection, audit filtering, Security Lab results/evidence/reload, and six mobile screens. Both runs recorded zero application console exceptions or failed application requests.

The canonical PDF uploads used actual HTTP multipart requests against the running backend. Their extracted fields and expected rule IDs matched the separate JSON; no automatic approval/rejection appeared. The missing holder/maturity stayed null, the duplicate was detected, and injection text left its record pending review. These are parser/authority-boundary results, not evidence of a model detecting injection.

The live Lab retained **14 operational records before and 14 after** its run. Persisted SQLite inspection found **14 instruments, 14 extractions, 175 audit events and 3 Lab reports** in the isolated verification database. The normal `.data/` workspace was not used for these browser/API writes.

Ignored local evidence in this workspace:

- `.local/browser-smoke-development.json` and `.local/browser-smoke.json` (production).
- `.local/api-verification.json` and `.local/security-lab-report.json`.
- `.local/dashboard.png`, `.local/security-lab.png`.
- `.local/demo-verification.db` and `.local/demo-verification-documents/`.

The ad hoc live probe and its results remain local QA artifacts, not tracked application features. The committed dataset pytest reproduces the independent ground-truth assertions in a clean checkout.

To reproduce browser checks without writing to your normal workspace, use a dedicated database/storage path from the repository root:

```powershell
npm run setup
$env:DATABASE_URL = 'sqlite:///./.local/demo-verification.db'
$env:STORAGE_DIR = './.local/demo-verification-documents'
npm run dev
```

In another terminal:

```powershell
node scripts/smoke-browser.mjs
```

For the production frontend, keep the backend running, run `npm run build` followed by `npm --prefix frontend run preview -- --port 4173 --strictPort`, then set `$env:SMOKE_FRONTEND_URL = 'http://127.0.0.1:4173'` before the browser command. The script loads the private root key and enters it when required. Use `CHROME_BIN` for a nonstandard installed Chrome path. Browser checks create synthetic records; do not point them at operational financial data.

## Actual inference and OCR status

**Gemma inference: not run.** Exact verified optional runtime tag: **`gemma4:e2b`**, Apache-2.0. No Ollama executable or configured endpoint was available. No model weights were downloaded. The replaceable OpenAI-compatible adapter and strict response/error handling are tested with doubles, never represented as live inference. See [model configuration and official references](../README.md#extraction-modes-and-gemma-4). After separately installing a suitable runtime and checking memory/disk, the next optional command is `ollama pull gemma4:e2b`, then configure the documented endpoint/model and perform an extraction. That download can be several GB and was not executed here.

**Embedded PDF text: working. Scanned-image OCR: not run.** PyMuPDF reads all five canonical PDFs. No `paddleocr`, `paddle`, `torch` or `transformers` was installed. The rasterized scan regression verifies safe nulls and blocked approval with OCR disabled; it does not verify OCR. Optional CPU setup commands, adapted from the [official PaddleOCR quickstart](https://www.paddleocr.ai/main/en/quick_start.html), are:

```powershell
.\.venv\Scripts\python.exe -m pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
.\.venv\Scripts\python.exe -m pip install "paddleocr>=3,<4"
```

Check platform/runtime compatibility before using those optional commands; they were not executed. Set `OCR_ENABLED=true`, restart, and extract an image-only document to verify actual OCR. Initialization may fetch OCR assets.

**Prompt Guard: not run.** Three live classifier checks and one pytest evaluation are explicitly unavailable/skipped. Follow [separate runtime/cache/license setup](prompt-guard.md); no Meta license acceptance or model download was performed. The current host's RAM/GPU query was denied, so current available memory/GPU capability was not verified.

## Completed changes and remaining limits

Setup and dataset script entry points work, VaultX branding is consistent, and the existing dashboard/upload/evidence/review/audit UI is preserved. Request deadlines/rate budgets, signed amount evidence, explicit extraction coverage limits, production key omission, and reviewer-key handling now have regression coverage. Original values remain separate from corrections, and human decisions require server-side authorization, valid state and a reason. Existing history triggers were tested, not described as tamper-proof.

Important files: `backend/app/{config,main,request_security,extraction,validation}.py`, backend security/config/extraction/dataset tests, `frontend/src/{App,api,api.test,styles}`, `frontend/vite.config.ts`, `scripts/{setup,setup.test,generate-demo,smoke-browser}.mjs`, `samples/vaultx/`, `.env.example`, `README.md`, and `SECURITY.md`.

Known limits: shared-key single-workspace access has no personal accounts, roles or tenant ownership; `X-Actor` is self-asserted. Native parsers/OCR have no killable processing deadline. Rate budgets are per process/IP. Database administrators can bypass history triggers. SQLite transactions serialize work, including inference calls; migrations, durable backups and production concurrency remain work. Interest-rate extraction is not implemented. Conservative PDF policy can reject harmless active features. Real model/OCR quality and remote deployment are unverified. Existing AGPL-3.0 license was preserved.

For a live demo, run `npm run dev`, open **http://127.0.0.1:5173**, and upload `samples/vaultx/01` through `05` in order using the labelled parser. Show valid evidence/checks before introducing the duplicate, then missing values, reasoned correction/decision, and audit history. Run Security Lab and explain its three NOT RUN classifier cases. Present this as decision support, never proof of authenticity or a live banking verification service. [Render preparation](deployment.md) is documented but not deployed or live-verified.
