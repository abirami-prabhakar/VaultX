# Security scope and observed controls

VaultX is a local single-user review MVP. These controls reduce specific risks; they do not establish guaranteed security, bank authenticity, regulatory compliance, or a safe model output. Do not use real customer documents in Security Lab fixtures or disclose documents/secrets in a public issue.

## Inspection before this enhancement

The existing application already checked extensions/MIME, PDF signatures and parsing, upload size, page counts, PDF/image dimensions, encryption, and private UUID document paths. It already required the backend shared key on record/review/document/audit endpoints, validated model JSON with Pydantic and amounts with Decimal, required review reasons, retained separate original/corrected values, committed changes with audit events, and used SQLite append-only triggers for extraction, decision and audit history. Those controls were retained and regression-tested.

The confirmed gaps addressed here were request limits based only on declared Content-Length, authorization occurring after multipart parsing, image identification without full pixel decoding, no conservative PDF action/attachment policy, incomplete display-name cleanup and storage failure handling, and no optional prompt classifier or executable Security Lab.

## Upload and request boundaries

- A pure ASGI boundary authenticates protected routes before parsing any body. Missing, wrong, duplicate, and non-ASCII keys fail with controlled errors. CORS preflight remains handled by the configured origin allowlist. Claimed frontend/admin roles cannot supply authorization.
- Actual received request bytes are capped at `MAX_UPLOAD_MB + 1 MiB` for multipart overhead, including chunked/missing or misleading Content-Length requests. Malformed/ambiguous lengths are rejected. The document itself must still fit `MAX_UPLOAD_MB`.
- PDF intake checks signatures, parsing without repair, encryption, object counts/metadata budgets, page counts and dimensions. Parsed dictionaries reject JavaScript, launch/remote/form actions, open/additional actions, attachments and other selected active features. Benign quoted text mentioning JavaScript is not treated as an action. This is a deliberately conservative receipt policy: a harmless attachment or opening destination can still be rejected.
- PNG/JPEG must identify as the declared supported format, stay within 25 million pixels, be single-frame, pass structural verification, and fully decode. Animated/multipage images and malformed pixel streams are rejected.
- Client filenames are display metadata only. Basenames are normalized and controls/bidirectional marks removed. Disk writes use generated UUID names with exclusive creation, flush/fsync, and partial-file cleanup on failures. POSIX creation mode is 0600; Windows needs appropriate storage ACLs. Upload/database/audit failures roll back the operation and clean up newly created files where the filesystem permits it.
- Files remain outside frontend assets; originals are returned through an authenticated no-store endpoint. There is no public upload directory.

The boundary uses a bounded in-memory body buffer, a configured total body-receive deadline (408), and a bounded process-local per-client-IP rate budget including unauthorized attempts (429 with `Retry-After`). Forwarded headers do not supply a trusted client identity, and users behind a proxy can share a budget. These controls are not a total concurrent-memory quota, distributed rate limiter, reverse proxy, antivirus, or native-parser execution sandbox. A valid compressed PDF can remain computationally expensive after receipt. Filesystem/SQLite coordination is not a crash-safe distributed transaction. Production needs process isolation, resource/time quotas, private filesystem permissions, and operational monitoring.

Page/total extracted-text limits and a six-unreadable-image-page limit fail explicitly rather than silently omitting content. Numeric evidence comparisons retain minus signs and accounting parentheses to avoid supporting positive values with negative source amounts. These checks do not establish semantic correctness or document authenticity.

## Optional prompt-injection screening

Llama Prompt Guard 2 is separate from Gemma extraction, strict Pydantic response validation, and deterministic rules. It is disabled by default, lazy-loaded from an authorized local cache, and never downloads weights or runs repository-provided model code. Missing packages, incompatible models, missing cache, processing errors and partial coverage are explicit outcomes. Supported official 22M/86M classifiers have verified binary BENIGN/MALICIOUS labels and 512-token windows. Longer extracted text uses bounded overlapping windows.

Each extraction attempt with readable document processing stores an append-only screening result and an audit event. Results retain model, score when available, threshold, coverage, completion and generic errors. No raw document text or credential-bearing exception is copied into classifier diagnostics. The extraction snapshot and its page evidence remain separate.

`PROMPT_INJECTION_REVIEW` is an advisory finding for a possible injection. It can be a false positive. Enabled but unavailable/incomplete/error screening produces `PROMPT_SCREENING_INCOMPLETE` for manual review. Disabled screening makes no detection claim and preserves the credential-free demo workflow. A low score cannot certify safety, and the classifier never authenticates a request or creates a final decision. Screening is advisory rather than an inference firewall: Gemma can still receive text flagged for review. The human must resolve findings and provide a reason before approval.

The classifier screens extracted text only, not original page pixels. OCR errors, extractor text limits, skipped text/images, different languages, attacks across window boundaries, or adaptive attacks may escape it. At most 200,000 extracted characters and the configured chunk budget are processed. `complete` refers to that supplied extracted text, not all information present in the original document. A flagged partial result remains flagged, and an unflagged incomplete result does not claim `clear`.

See [Prompt Guard setup and licensing](docs/prompt-guard.md). Current checks confirmed no torch/transformers. No Prompt Guard dependencies or weights were installed, and actual classifier inference is unverified. Its weights use the **Llama 4 Community License**, not the application's AGPL license or Gemma's Apache-2.0 license. Review Meta's gating, use and attribution conditions before separately acquiring it.

Local extraction profiles support Gemma 3 1B and Qwen2.5 0.5B through llama.cpp and RapidOCR/ONNX Runtime; see [Gemma setup and verification](docs/gemma.md). Model selection, pinned filenames/hashes and served aliases must agree; there is no automatic fallback. Source label candidates guide inference, never replace an absent model response. After inference, grounding nulls unsupported values and label conflicts. A bounded repair round asks the same model only about failed fields, retaining grounded fields and using the remaining inference timeout budget. Labelled repair values remain nullable and source quotes/pages are constrained to actual document spans. Private server-generated provenance records repair counts; model output cannot set it. Original snapshots, corrections and audit events remain separate. OCR failures, malformed output, truncation and timeouts fail explicitly. These fixtures do not guarantee accuracy or security on other documents.

## Authorization, decisions and audit

The backend requires a configured unique shared API key on every protected route, including Security Lab and private documents. Local setup generates an ignored private configuration and preserves operator settings. Production frontend builds omit the local development key; reviewers enter it at runtime, held in tab session storage or page memory. The same valid key can access all local records: **there is no per-record owner/tenant isolation or verified personal identity**. `X-Actor` is self-asserted audit metadata. A frontend key/name/role is not real multi-user authentication. Individual accounts, authorization policies, key rotation and access logging remain production work.

Gemma/classifier responses have no tool or database authority. Extraction output accepts fields/evidence only; approval/fund-action keys fail the schema. Final decisions remain reason-required human API actions with server-side transition checks. Corrections preserve original snapshots. Append-only SQLite triggers now also cover screening snapshots and Lab reports. There are no edit/delete history or report routes. A filesystem/database administrator can still alter the database or drop triggers; this is not externally tamper-proof logging.

## Security Lab and test interpretation

Open **Security Lab** in the sidebar and click **Run security checks**. Both inventory and run endpoints require the shared key. The runner executes only predefined probes against fresh temporary SQLite storage and synthetic documents. It does not execute user code, shell commands or operator-provided URLs; it does not modify operational FDRs. One run per application process is allowed at a time. Reports are appended to the main database after completion and show timestamps, expected/observed results, errors and evidence.

The suite currently contains 12 application/control probes and 3 optional real-classifier probes:

| Group | What is actually exercised |
| --- | --- |
| Invalid and benign uploads | Actual API rejections for malformed/disguised content, size/page/attachment limits, supported PDF/PNG/JPEG acceptance, private generated names and preview. |
| Missing fields | Null values, actual required-field findings, and blocked approval. Disabled rules are reported as skipped when applicable. |
| Financial discrepancies | Actual Decimal threshold correction/revalidation and direct deterministic evidence/date conflict checks. |
| Unauthorized access | Missing/wrong keys on record, document, extraction, validation, review and audit, even with a claimed admin role; record/history remain unchanged. |
| Injection authority boundary | Injected synthetic PDF cannot create a decision; Pydantic rejects approval/fund fields. This uses the labelled demo parser and is **not model-detection evidence**. |
| Audit changes | Mandatory correction reasons, original retention, rejected PATCH/DELETE requests, actual SQLite UPDATE/DELETE trigger failures, finalized decision immutability. |
| Real Prompt Guard evaluation | Malicious instruction, ordinary benign receipt, and a benign quotation challenging false positives. Uses the configured adapter; a missed attack or flagged benign fixture is a failure. |

Missing/disabled/error/partial classifier evaluations are skipped rather than passed. Partially computed scores and coverage remain visible as evidence, not silently discarded. Other unexpected failures remain failures; no successful outcome is hardcoded. Rules intentionally disabled by configuration are identified rather than claimed to have passed. Large configured page limits can exceed the Lab's bounded fixture budget and produce a skip.

Pytest additionally exercises actual streamed-size bypass attempts, malformed decoded images, escaped PDF action names, disk-write rollback, original application behavior, classifier label/window/score errors, simulated false positives/negatives, persisted report isolation and immutable new tables. Classifier-contract tests use clearly labelled doubles to test integration without weights. They do **not** establish real detection accuracy. The explicit real-model pytest evaluation is skipped unless enabled and available.

The Lab is not an exhaustive benchmark, penetration test, audit attestation or security guarantee. A passed run is evidence only for the reported fixtures and configuration at its timestamp. Cached reports can become stale after configuration changes. Remote model accuracy/availability, OCR quality, production identity, native-parser isolation and concurrent resource exhaustion remain outside the verified scope.
