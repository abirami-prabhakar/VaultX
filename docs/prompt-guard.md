# Optional Prompt Guard 2 screening

The application can screen extracted document text with **Llama Prompt Guard 2**, independently of Gemma extraction and deterministic Pydantic/Python validation. The classifier produces an advisory score, never access permissions, FDR decisions, bank verification, or fund actions. A low score does not prove safety, and a high score does not prove a malicious document.

## Compatibility and resources checked before installation

The official model supports the Transformers `AutoTokenizer` and `AutoModelForSequenceClassification` interfaces, binary **BENIGN / MALICIOUS** labels, and a **512-token** context. The adapter verifies a loaded classifier's DeBERTa-v2 architecture, two labels, and actual label mapping instead of guessing `LABEL_0` meanings. It uses overlapping windows for longer extracted text. Supported identifiers are `meta-llama/Llama-Prompt-Guard-2-22M` and `meta-llama/Llama-Prompt-Guard-2-86M`. The smaller model is less suitable for multilingual use. See the [official model card](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-22M).

Earlier development notes recorded Python 3.11.9, 14 logical CPUs, 15.4 GiB total RAM, approximately **0.8 GiB available RAM**, and 38.3 GiB free workspace disk. Current verification confirmed absent `torch` and `transformers`; current RAM/GPU queries were denied, so the earlier resource figures were not re-verified. Available memory changes over time; these notes are not a minimum specification or a promise of compatibility.

The official file lists show about **283 MB** of safetensors weights for [22M](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-22M/tree/main) and **1.12 GB** for [86M](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M/tree/main), excluding tokenizer files, PyTorch dependencies, and runtime memory. Model names denote backbone sizes, not complete installation size. With little free RAM and no inference dependencies, installing a model was not appropriate for this run. **No weights were downloaded, and actual Prompt Guard inference remains unverified.**

## Optional setup

The normal application works with `PROMPT_GUARD_ENABLED=false`. The Security Lab reports unavailable model evaluations as **skipped**, not passed.

Before enabling the adapter, inspect the official model files, ensure sufficient RAM/disk for the runtime as well as the weights, and select a CPU/CUDA PyTorch build appropriate for the machine. The [official Transformers installation documentation](https://huggingface.co/docs/transformers/main/en/installation) describes Python/PyTorch compatibility and offline caching. The optional requirements file is a compatibility target; this exact dependency set was not installed or runtime-tested here.

After deciding to install locally, from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-prompt-guard.txt
```

Obtain authorized access to the selected Meta model separately and review its license. Using the Hugging Face CLI installed with its runtime dependencies, cache its files explicitly:

```sh
hf auth login
hf download meta-llama/Llama-Prompt-Guard-2-22M
```

These optional commands can download packages and model data and may require accepting Meta's access conditions. They were not executed during implementation. Keep Hugging Face tokens out of frontend variables, source files, and audit events.

Then add to the root `.env` and restart the backend:

```dotenv
PROMPT_GUARD_ENABLED=true
PROMPT_GUARD_MODEL=meta-llama/Llama-Prompt-Guard-2-22M
PROMPT_GUARD_THRESHOLD=0.5
PROMPT_GUARD_DEVICE=cpu
PROMPT_GUARD_MAX_CHUNKS=64
# Optional: the Hugging Face hub cache directory, not a remote model URL.
# PROMPT_GUARD_CACHE_DIR=C:/path/to/huggingface/hub
```

The backend only loads existing cached files using `local_files_only=True`; it does **not** download missing weights. It rejects custom model IDs, repository-provided code (`trust_remote_code=False`), and pickled model weights (`use_safetensors=True`). CPU is the default. Configured CUDA must actually be available. A missing package, cache file, incompatible model, or unavailable device produces an explicit unavailable result. Loading is attempted once per process; restart after changing dependencies, cached files, or configuration.

## Results and failure behavior

Each result contains the provider and model ID, status, threshold, score when inference ran, generic reason, character coverage, window count, and completion flag. Health/status checks do not load model weights. `available` becomes true only after loading; `runtime_verified` becomes true only after successful classification in that process. This reports runtime execution, not cryptographic model identity or detection quality.

- **disabled:** no classification was attempted.
- **unavailable:** no usable classifier or readable text was available.
- **flagged:** at least one window reached the configured review threshold; human review is required.
- **clear:** complete text screening produced no score at the threshold; attacks may still be missed.
- **error:** processing failed or an input/window limit prevented a complete unflagged result.

Screening is bounded to 200,000 characters and the configured number of windows, with 64-token overlap. It reports partial coverage explicitly and never reports `clear` for an unscreened remainder. An already flagged partial input remains flagged with `complete=false`. Raw document text and exception details are excluded from diagnostics to avoid leaking holders, keys, or local cache paths. No readable text means no image-screening claim: this adapter is text-only, and OCR availability is a separate concern.

Prompt Guard errors do not disable the independent upload, authorization, validation, or human review controls. Screening results and audit history are retained separately from original extraction. A classifier warning is an issue for a reviewer, not an automatic approval or rejection. Configuring a higher threshold can reduce false positives while increasing missed attacks; this repository does not recommend a threshold as universally safe.

## Tests and honest evaluation

`backend/tests/test_prompt_guard.py` runs deterministic adapter-contract tests without downloading models. Its injected classifiers are explicitly simulated: tests cover benign and malicious fixtures, a deliberately flagged benign security quotation (false positive), a deliberately missed malicious instruction (false negative), threshold behavior, window boundaries/coverage, invalid scores, disabled/missing runtimes, incompatible labels, and private error handling. Passing these tests proves the exercised adapter behavior, **not** the actual model's accuracy.

After obtaining a suitable real runtime/cache, optional model evaluation can be requested explicitly:

```powershell
$env:RUN_PROMPT_GUARD_MODEL_TESTS = 'true'
.\.venv\Scripts\python.exe -m pytest backend/tests/test_prompt_guard.py -q
```

The real-model test is skipped by default, and skips with an explicit reason if the configured model cannot load. When inference runs, a missed attack or a flagged known-benign fixture causes a real test failure. The Security Lab likewise reports the configured model's actual malicious/benign/quotation results, with unavailable evaluations marked skipped. These small fixtures are regression checks, not an exhaustive benchmark, penetration test, or guarantee against adaptive attacks.

## Model license

Prompt Guard 2 weights are distributed under Meta's **Llama 4 Community License Agreement**, with gated access and an acceptable use policy; they are **not Apache-2.0**. The agreement includes conditions for products/services containing Llama materials, such as attribution and the **Built with Llama** notice. Read the [official model license](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-22M/blob/main/LICENSE) and use policy before acquisition, use, hosting, or redistribution. No weights or Meta license acceptance are bundled with this repository. The optional adapter's source follows the application license; separately acquired model materials retain their own terms. No hosted classifier service is claimed to be open source.
