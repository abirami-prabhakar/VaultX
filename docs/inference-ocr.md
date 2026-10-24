# Local inference and scanned-document OCR

The original deployment had empty model configuration, no running inference service, OCR disabled and no OCR dependencies. Its scan heuristic skipped image-bearing pages with a digital header and rasterized other scans at 72 DPI. The adapters now support CPU OCR, explicit coverage, constrained JSON, actionable failures and per-page provenance.

## Windows CPU profile

The current machine had about 1.1 GiB available RAM at inspection. Use the free Apache-2.0 **Qwen2.5 0.5B Instruct Q4_K_M** alternative with a two-thread, one-slot llama.cpp CPU server. This is Qwen, not Gemma; the existing `gemma` API mode and `GEMMA_*` adapter variables are retained for compatibility.

Install the backend and verified official runtime/model from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-lock.txt
.\.venv\Scripts\python.exe scripts/setup-inference.py --model-host modelscope
```

The bounded Windows x64 installer downloads official llama.cpp release **b11852** (~24 MB) and Qwen's **491,400,032-byte** GGUF, checks SHA-256, supports interrupted-download resumption, and writes only ignored `.local/llama.cpp/` and `.models/`. It never changes keys or accepts gated licenses. Hugging Face connections were reset in this environment, so the reachable [official Qwen ModelScope repository](https://modelscope.cn/models/Qwen/Qwen2.5-0.5B-Instruct-GGUF) is the default; `--model-host huggingface` uses [Qwen's Hugging Face repository](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF). The [runtime source/release](https://github.com/ggml-org/llama.cpp/releases/tag/b11852) is MIT-licensed.

Configure the private root `.env`:

```dotenv
EXTRACTION_MODE=gemma
LOCAL_MODEL_ENABLED=true
GEMMA_BASE_URL=http://127.0.0.1:8081/v1
GEMMA_MODEL=qwen2.5-0.5b-instruct
GEMMA_API_KEY=
GEMMA_TIMEOUT_SECONDS=180
GEMMA_RESPONSE_FORMAT=json_schema
GEMMA_MAX_TOKENS=1600
GEMMA_SUPPORTS_VISION=false
OCR_ENABLED=true
OCR_ENGINE=rapidocr
OCR_DPI=200
```

`npm run dev` starts the model, backend and frontend with this profile. Alternatively, start `npm run model` separately before the existing backend/frontend commands. The model binds only loopback on port 8081; it needs no local model API key. Do not expose the model service publicly. Free memory changes over time; the small model reduces resource use but cannot guarantee extraction quality or safety. Original evidence and human review remain necessary.

On Linux/macOS, install an appropriate official llama.cpp build and the same GGUF, or use an independently installed Ollama runtime; the bounded installer deliberately rejects non-Windows platforms. `LLAMA_SERVER` can name an existing platform-compatible server binary.

## Gemma and Ollama remain supported

For a separate machine with enough resources, serve an exact installed Gemma model and configure its ID. Ollama URLs at its root, `/api`, `/v1`, or the complete `/v1/chat/completions` path are normalized correctly. For example:

```dotenv
LOCAL_MODEL_ENABLED=false
GEMMA_BASE_URL=http://127.0.0.1:11434/v1
GEMMA_MODEL=gemma4:e2b
GEMMA_SUPPORTS_VISION=true
```

Verify `ollama list` and `ollama show gemma4:e2b`; run `ollama pull gemma4:e2b` only after checking the several-GB download and runtime memory. Gemma itself has not run merely because Qwen ran. [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs) and [llama.cpp server](https://github.com/ggml-org/llama.cpp/tree/master/tools/server) support schema-constrained JSON. `GEMMA_RESPONSE_FORMAT=json_object` is an explicit compatibility setting for runtimes without schema support; failures do not automatically weaken the response contract.

Requests are non-streaming, with a connect timeout, a configurable inference timeout and output-token budget. Refusals, truncation, wrong model IDs, malformed JSON, invalid schemas and HTTP failures persist `extraction_failed` and preserve prior snapshots. Responses cannot contain approval or fund actions. Missing fields are null; no automatic parser fallback disguises a model failure. Select **Sample / deterministic demo** explicitly to use the existing labelled parser.

The small model receives labelled evidence candidates derived from the uploaded text, alongside the original untrusted pages. It still produces the extraction response; candidate values are never substituted for missing model fields. A deterministic grounding pass discards text values without supporting page quotes and values contradicted by explicit labels; conflicting labelled holders remain null. Provenance identifies the use of these hints. The small model can over-report uncertainty, so extra manual-review findings are a known limitation, not suppressed warnings.

## OCR engines and mixed pages

CPU [RapidOCR](https://github.com/RapidAI/RapidOCR) and ONNX Runtime are included in backend requirements. To upgrade an existing core-only environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-ocr.txt
```

The lazy engine is reused rather than initialized per page. PDF scans render at configured DPI with a 25-million-pixel cap. Images receive EXIF orientation, transparent-background compositing, contrast normalization and bounded upscaling. Detected words are reassembled into visual rows so labels and values reach the parser together. Embedded text is retained and combined with OCR on image-bearing pages; source conflicts remain visible instead of being silently overwritten.

`OCR_ENGINE=paddleocr` retains a separate optional PaddleOCR 3.x adapter; install PaddleOCR/PaddlePaddle independently before selecting it. The live CPU verification uses RapidOCR, not PaddleOCR. Enabled but missing/broken OCR fails explicitly. `OCR_ENABLED=false` is an explicit text-only setting; unreadable image pages require a vision-capable model or manual clarification. Scans never silently become known fields.

API `original_extraction.provenance` and extraction audit metadata identify the field extractor, page number, embedded-text/OCR/image method and OCR engine. The UI displays these methods beside the configured model. `/health` reports OCR/inference execution only after a successful adapter call in that process; `model_verified` remains false because execution does not authenticate weight identity.

## Real verification

With `npm run model` running and the configuration above, execute:

```powershell
.\.venv\Scripts\python.exe scripts/verify-inference-ocr.py
```

This command uses actual OCR and model calls, a disposable SQLite database, and only synthetic data. It compares text PDFs, rasterized scanned PDFs, PNG images, mixed PDFs, missing/conflicting fields and an injection document against independent ground-truth JSON. It fails if any check fails; no real checks are skipped or mocked. Results are written under ignored `.local/inference-ocr-verification.json`, including actual extracted fields, methods and duration. The command never approves documents.

## Observed verification

On 24 October 2026 (Windows, Python 3.11.9, Node 24.14.1):

| Executed check | Result |
| --- | --- |
| `npm run test:backend` | **186 passed, 0 failed, 1 skipped**. The pre-existing optional real Prompt Guard evaluation remains skipped; one Starlette/httpx deprecation warning remains. |
| `npm test` | **16 passed, 0 failed**. |
| `npm run test:setup` | **4 passed, 0 failed**. |
| `npm run build` | **Passed**, including TypeScript and Vite. |
| `python scripts/verify-inference-ocr.py` with the venv interpreter | **9/9 real checks passed**, no skips/mocks. |
| `node scripts/smoke-browser.mjs` | **12/12 browser checks passed** against the integrated model/backend/frontend startup and isolated synthetic storage. |
| `python -m pip check` with the venv interpreter | **No broken requirements found**. |

Real checks cover scanned PDF, PNG, JPEG, mixed-page PDF, a single page combining a digital header with a scan, model extraction from text, model extraction after OCR, missing/conflicting fields, and prompt injection. All extracted fields matched separate ground truth; every record stayed pending human review. Typical warm OCR calls took about 2–3 seconds and model calls about 11–16 seconds on these fixtures. Runtime and model files passed official-source SHA-256 checks before activation.

The first real run passed five checks and failed the missing-fields case: the small model misidentified the bank and combined conflicting names. Source-derived label hints and deterministic grounding were added, with regressions; the final nine-check run then passed without relaxing the ground-truth assertions. No missing model fields are filled from parser output. The small model still over-reports uncertainty on the ambiguous fixture, producing extra review findings; this limitation is retained visibly.

Hugging Face connections reset and PyPI's OpenCV download repeatedly stalled. The identical official Qwen repository on ModelScope was reachable; the OpenCV mirror wheel was checked against PyPI's official SHA-256. Both installations completed. There is no remaining installation blocker for this CPU profile. Gemma weights and PaddleOCR were not run; the verified alternatives are Qwen and RapidOCR. Prompt Guard remains an independent, unavailable optional classifier.

Normal regressions remain `npm run test:backend`, `npm test`, `npm run test:setup`, and `npm run build`. Native OCR/PDF processing still needs worker isolation for hostile production workloads; timeout settings do not kill native parser threads. Existing AGPL license and human authorization controls remain unchanged.
