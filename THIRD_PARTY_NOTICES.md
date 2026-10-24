# Third-party notices

The application is distributed under AGPL-3.0-only because its required PyMuPDF/MuPDF integration uses the AGPL licensing option. Dependency licenses and notices remain applicable. Dependencies are obtained through package managers; this repository does not bundle model weights.

| Component | License / reference |
| --- | --- |
| PyMuPDF / MuPDF | GNU Affero GPL 3.0 or Artifex commercial terms; this MVP uses the AGPL option. [Official licensing](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright). |
| React / React DOM | MIT. |
| Vite / Vitest | MIT. |
| TypeScript | Apache-2.0. |
| Tailwind CSS | MIT. |
| Lucide | ISC for library code; icon assets include ISC and MIT notices. See the installed `lucide-react/LICENSE`. |
| FastAPI / Pydantic | MIT. |
| Starlette | BSD-3-Clause. |
| SQLAlchemy | MIT. |
| Uvicorn / HTTPX | BSD-3-Clause. |
| Pillow | MIT-CMU (historical PIL license); bundled image libraries have additional notices. |
| RapidOCR and bundled default OCR assets | Apache-2.0; [official project](https://github.com/RapidAI/RapidOCR). Installed separately through backend requirements, not committed here. |
| ONNX Runtime | MIT; CPU inference engine. |
| OpenCV headless | Apache-2.0; installed wheel includes additional third-party notices. |
| NumPy / Shapely | BSD-3-Clause. |
| Qwen2.5 0.5B Instruct GGUF (local alternative) | Apache-2.0; [official repository](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF). Downloaded separately into ignored storage. |
| Gemma 3 1B Instruct Q4_K_M (local Gemma profile) | [Gemma Terms of Use](https://ai.google.dev/gemma/terms); **not Apache-2.0**. Google's model converted to GGUF by [Unsloth](https://huggingface.co/unsloth/gemma-3-1b-it-GGUF). Downloaded separately into ignored storage; terms remain applicable to weights/derivatives. |
| llama.cpp (local CPU runtime) | MIT; [official release](https://github.com/ggml-org/llama.cpp/releases/tag/b11852). Downloaded separately into ignored storage. |
| python-multipart / python-dotenv | Apache-2.0 / BSD-3-Clause. |
| pytest | MIT. |
| Gemma 4 (optional external weights) | Apache-2.0; [official model card](https://ai.google.dev/gemma/docs/core/model_card_4). |
| PaddleOCR (optional external install) | Apache-2.0; [official license](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE). PaddlePaddle, OCR model assets, and transitive dependencies have their own terms. |
| Llama Prompt Guard 2 (optional separately acquired weights) | Meta Llama 4 Community License Agreement and acceptable use conditions; gated access, **not Apache-2.0**. No weights or license acceptance bundled. Review attribution and usage conditions in the [official license](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-22M/blob/main/LICENSE). |
| Transformers / safetensors / SentencePiece (optional) | Apache-2.0; not installed in the tested core environment. |
| PyTorch (optional) | BSD-3-Clause and bundled third-party notices; select an appropriate CPU/CUDA distribution separately. |

For authoritative copies of all transitive license texts, consult each installed Python distribution's `*.dist-info` metadata/licenses and npm package's `LICENSE`/`NOTICE` files. Installing a hosted inference client or configuring a hosted endpoint does not make that provider's service open source. Commercial PyMuPDF licensing, model-hosting terms, and any separately installed dependencies must be evaluated independently before redistribution or deployment.
