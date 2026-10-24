# Gemma 3 with the existing VaultX runtime

Gemma support uses the existing llama.cpp/OpenAI-compatible adapter, RapidOCR pipeline, schemas, deterministic validators and human review. Qwen remains a separately selected local profile; no fallback is automatic.

## Selection and original failure

The original configuration contained no Gemma endpoint/model and no Ollama installation. Only about 1.1 GiB RAM was free during the earlier run, so a working Qwen CPU alternative was installed. The local launcher and downloader then hardcoded Qwen's filename and alias; changing `GEMMA_MODEL` alone could not load Gemma. They now share explicit, pinned model profiles, and reject alias/profile mismatches.

Current inspection found an **Intel Core Ultra 5 225H**, **14 logical CPUs**, **15.40 GiB total RAM**, **3.82 GiB free RAM**, **20.73 GiB available commit**, **37.45 GiB free disk**, Python **3.11.9**, and Node **24.14.1**. Free memory is an observation, not a guaranteed minimum. No GPU is needed for the selected profile.

Selected model: **Gemma 3 1B Instruct, Q4_K_M**, a text-only Google Gemma 3 model quantized to GGUF by Unsloth. The actual file is **806,058,272 bytes**, `gemma-3-1b-it-Q4_K_M.gguf`. This is distinct from Qwen and from Gemma 4 E2B. The latter's larger download/runtime was unnecessary for this machine. Keep context at 4096, one inference slot and two CPU threads to limit memory/CPU use; larger documents can exceed the context budget and must fail visibly.

Primary sources:

- [Google Gemma 3 model card](https://ai.google.dev/gemma/docs/core/model_card_3) establishes the model family, instruction-tuned variants and capabilities. The 1B model is text-only; scanned input reaches it through RapidOCR.
- [Unsloth's Gemma 3 1B GGUF distribution](https://huggingface.co/unsloth/gemma-3-1b-it-GGUF) provides this quantization of Google's model; it is not represented as a Google-published GGUF file.
- [llama.cpp b11852](https://github.com/ggml-org/llama.cpp/releases/tag/b11852), already installed, supports the Gemma 3 architecture and serves the existing JSON-schema chat endpoint.
- [Gemma Terms of Use](https://ai.google.dev/gemma/terms) apply to Gemma 3 weights and derivatives. They are free to obtain/use subject to those terms, not Apache-2.0. VaultX's existing AGPL application license is unchanged. No gated login or license-acceptance click is automated.

## Install, select and run

From the repository root, with the existing venv and backend dependencies:

```powershell
.\.venv\Scripts\python.exe scripts/setup-inference.py --model gemma --model-host modelscope
npm run model:select -- gemma
npm run dev
```

The installer downloads the public Unsloth distribution at pinned revision `bb305d6417a2e1a2e56e87a3264fad59714ce8e2` from ModelScope, verifies its published checksum against the pinned profile, and activates it only after matching SHA-256:

```text
8270790f3ab69fdfe860b7b64008d9a19986d8df7e407bb018184caa08798ebd
```

It also verifies/reuses the existing official CPU runtime. `--model-host huggingface` is an alternative download host; host availability/gating can differ. Downloads resume after interruption and are bounded to the selected file's expected size. Weights remain in ignored `.models/`, runtime files in ignored `.local/llama.cpp/`. Startup checks file size and SHA-256 again, using a bounded buffer instead of loading the whole file into JavaScript memory. An absent/wrong file stops startup instead of loading Qwen under a Gemma alias.

The selector changes only the model profile, local endpoint, model alias and extraction-mode settings in private `.env`:

```dotenv
LOCAL_MODEL_ENABLED=true
LOCAL_MODEL_PROFILE=gemma
EXTRACTION_MODE=gemma
GEMMA_BASE_URL=http://127.0.0.1:8081/v1
GEMMA_MODEL=gemma-3-1b-it-q4_k_m
GEMMA_SUPPORTS_VISION=false
```

Keep `GEMMA_TIMEOUT_SECONDS=180`, `GEMMA_RESPONSE_FORMAT=json_schema`, `GEMMA_MAX_TOKENS=1600`, `OCR_ENABLED=true` and `OCR_ENGINE=rapidocr` from the working configuration. Reviewer keys, provider keys, OCR configuration and storage/database paths are preserved. Restart running servers after selection. `npm run dev` starts the selected model, backend and frontend; open **http://127.0.0.1:5173**.

The runtime schema requires all seven nullable field keys and the evidence/missing/uncertain arrays. Readable explicit labels set a minimum evidence coverage; page quotes and field values are still checked after generation. Gemma initially omitted holder evidence and abbreviated an identifier. `GEMMA_REPAIR_ATTEMPTS=1` permits one targeted request to the same model for unsupported/missing values or evidence, using the same total inference deadline. Exhausted repairs leave fields null. Malformed JSON, truncation and timeouts fail immediately. No parser value is copied into a model response. Provenance records the actual number of repair attempts.

To run just the selected model, use `npm run model`. The server listens on loopback **8081**, uses the GGUF chat template, and reports the selected alias in responses. The backend rejects a different returned model ID; extraction snapshots and UI provenance record the actual configured alias. Schema validation and source grounding cannot make review decisions. Unknown/unsupported values remain null, while original evidence, corrections and audit entries stay separate.

## Explicit Qwen fallback

Stop the running app, then:

```powershell
npm run model:select -- qwen
npm run dev
```

The existing Qwen model file is preserved. A clean checkout can install it with `python scripts/setup-inference.py --model qwen --model-host modelscope` using the venv interpreter. The alias is `qwen2.5-0.5b-instruct`. A model error never triggers an automatic switch. The separate labelled parser remains an explicit extraction-mode choice in the UI.

## Real verification

With the selected server running, use a second terminal:

```powershell
.\.venv\Scripts\python.exe scripts/verify-inference-ocr.py --failure-probes
```

This runs actual model inference and actual OCR with temporary SQLite storage and synthetic documents only. Assertions compare fields to independent JSON, require traceable evidence for populated fields, preserve null ambiguous/missing fields, reject brand/issuer confusion, check injection cannot create a decision, and require all fields null when evidence is insufficient. No model check is mocked or skipped. Ten cases cover PDFs, scans, PNG/JPEG, mixed content and model-specific failures of interest.

Reports are saved separately per model under `.local/inference-ocr-<alias>.json`; the compatibility file `.local/inference-ocr-verification.json` also contains the latest run. Full backend regressions additionally test malformed JSON, truncation, timeouts, wrong model IDs, explicit parser fallback, unauthorized actions, duplicate handling, corrections and audit restrictions. Setup tests cover both profiles, key preservation, wrong aliases, missing weights and same-size file tampering.

`--failure-probes` also makes two actual runtime requests: one with a 128-token output budget to force truncation, and one with a 10 ms client deadline. Both must persist extraction failure without partial accepted fields or a decision. Malformed JSON is covered by regression transport fixtures because schema-constrained generation deliberately prevents arbitrary malformed JSON from being accepted.

```powershell
npm run test:backend
npm test
npm run test:setup
npm run build
```

These are a small synthetic evaluation, not a guarantee on arbitrary receipts or adaptive prompt attacks. Both text-only models rely on OCR for scans. There is no bank connection or proof of authenticity, and final review stays with an authorized human.
