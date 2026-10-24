"""Optional, advisory Prompt Guard 2 classification. No review or access authority.

The default adapter never downloads weights or executes model repository code.
Tests can inject a small backend to exercise application behavior without claiming
that a real classifier ran. Real inference is deliberately an optional dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import math
import re
from threading import Lock
from typing import Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


SUPPORTED_MODELS = (
    'meta-llama/Llama-Prompt-Guard-2-22M',
    'meta-llama/Llama-Prompt-Guard-2-86M',
)
PROVIDER = 'llama-prompt-guard-2'
CONTEXT_TOKENS = 512
OVERLAP_TOKENS = 64
MAX_TEXT_CHARS = 200_000


class GuardResult(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    status: Literal['disabled', 'unavailable', 'flagged', 'clear', 'error']
    provider: Literal['llama-prompt-guard-2'] = PROVIDER
    model: str = Field(max_length=200)
    score: float | None = Field(default=None, ge=0, le=1)
    threshold: float = Field(ge=0, le=1)
    reason: str = Field(max_length=1000)
    screened_chars: int = Field(default=0, ge=0)
    total_chars: int = Field(default=0, ge=0)
    complete: bool = False
    chunks_screened: int = Field(default=0, ge=0)


class PromptGuard(Protocol):
    def screen(self, text: str) -> GuardResult: ...

    def status(self) -> dict: ...


@dataclass(frozen=True)
class TokenizedText:
    ids: list[int]
    # Original character offsets let the adapter report coverage truthfully.
    offsets: list[tuple[int, int]]


class ClassifierBackend(Protocol):
    special_tokens: int

    def tokenize(self, text: str) -> TokenizedText: ...

    def malicious_score(self, token_ids: list[int]) -> float: ...


def malicious_label_index(id2label: dict) -> int:
    """Refuse generic LABEL_0 guesses and Prompt Guard 1's different schema."""
    labels = {int(index): str(label).upper() for index, label in id2label.items()}
    if set(labels) != {0, 1} or set(labels.values()) != {'BENIGN', 'MALICIOUS'}:
        raise ValueError('Expected the verified binary Prompt Guard 2 label schema')
    return next(index for index, label in labels.items() if label == 'MALICIOUS')


class TransformersBackend:
    """Cache-only HF Auto classes, matching Meta's sequence-classifier example."""

    def __init__(self, model: str, device: str, cache_dir: str | None):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        if device.startswith('cuda') and not torch.cuda.is_available():
            raise RuntimeError('Configured CUDA device is not available')
        options = {'local_files_only': True, 'trust_remote_code': False}
        if cache_dir:
            options['cache_dir'] = cache_dir
        self.tokenizer = AutoTokenizer.from_pretrained(model, use_fast=True, **options)
        if not self.tokenizer.is_fast:
            raise ValueError('A fast tokenizer with character offsets is required')
        # Pickled PyTorch weights and model-provided code are never loaded.
        self.model = AutoModelForSequenceClassification.from_pretrained(
            model, use_safetensors=True, **options,
        )
        if self.model.config.model_type != 'deberta-v2' or self.model.config.num_labels != 2:
            raise ValueError('Unsupported Prompt Guard classifier architecture')
        self.malicious_index = malicious_label_index(self.model.config.id2label)
        self.model.to(device)
        self.model.eval()
        self.device = device
        self.torch = torch
        self.special_tokens = self.tokenizer.num_special_tokens_to_add(pair=False)
        if not 0 < self.special_tokens < CONTEXT_TOKENS - OVERLAP_TOKENS:
            raise ValueError('Unsupported tokenizer special-token budget')

    def tokenize(self, text: str) -> TokenizedText:
        encoded = self.tokenizer(
            text, add_special_tokens=False, truncation=False,
            return_offsets_mapping=True, return_attention_mask=False,
        )
        return TokenizedText(list(encoded['input_ids']), [tuple(offset) for offset in encoded['offset_mapping']])

    def malicious_score(self, token_ids: list[int]) -> float:
        prepared = self.tokenizer.prepare_for_model(
            token_ids, add_special_tokens=True, truncation=False,
            return_attention_mask=True, return_tensors='pt',
        )
        if prepared['input_ids'].shape[-1] > CONTEXT_TOKENS:
            raise ValueError('Classifier window exceeds verified context length')
        inputs = {name: value.to(self.device) for name, value in prepared.items()}
        with self.torch.inference_mode():
            logits = self.model(**inputs).logits
            if tuple(logits.shape) != (1, 2):
                raise ValueError('Classifier returned an incompatible shape')
            probabilities = self.torch.softmax(logits, dim=-1)
            return float(probabilities[0, self.malicious_index].item())


def optional_dependencies_available() -> bool:
    try:
        return all(importlib.util.find_spec(module) is not None for module in ('torch', 'transformers'))
    except (ImportError, ValueError):
        return False


class LocalPromptGuard:
    """An optional classifier whose result is evidence for human review only."""

    def __init__(
        self, *, enabled: bool = False, model: str = SUPPORTED_MODELS[0],
        threshold: float = 0.5, device: str = 'cpu', max_chunks: int = 64,
        cache_dir: str | None = None,
        backend_factory: Callable[[], ClassifierBackend] | None = None,
    ):
        self.enabled = enabled
        self.model = model
        self.threshold = threshold if math.isfinite(threshold) and 0 <= threshold <= 1 else 0.5
        self.device = device
        self.max_chunks = max_chunks
        self.cache_dir = cache_dir
        self._backend_factory = backend_factory
        self._backend: ClassifierBackend | None = None
        self._attempted_load = False
        self._runtime_verified = False
        self._load_error: str | None = None
        self._lock = Lock()
        if model not in SUPPORTED_MODELS:
            self._load_error = 'Configured model is not one of the supported official Prompt Guard 2 classifiers.'
        elif not math.isfinite(threshold) or not 0 <= threshold <= 1:
            self._load_error = 'Prompt Guard threshold must be a finite number between zero and one.'
        elif not re.fullmatch(r'cpu|cuda(?::\d+)?', device):
            self._load_error = 'Prompt Guard device must be cpu or a supported cuda device.'
        elif not isinstance(max_chunks, int) or isinstance(max_chunks, bool) or not 1 <= max_chunks <= 512:
            self._load_error = 'Prompt Guard chunk limit must be between 1 and 512.'

    def status(self) -> dict:
        # No model import, initialization, or download during health checks.
        dependencies = optional_dependencies_available()
        if not self.enabled:
            reason = 'Optional Prompt Guard screening is disabled.'
        elif self._load_error:
            reason = self._load_error
        elif self._backend is not None:
            reason = 'Local classifier loaded; predictions remain advisory and can be wrong.'
        elif not dependencies and self._backend_factory is None:
            reason = 'Optional torch/transformers dependencies are not installed.'
        else:
            reason = 'Not loaded. Cached model compatibility is checked on first screening.'
        return {
            'status': 'disabled' if not self.enabled else 'available' if self._backend is not None else 'unavailable',
            'enabled': self.enabled, 'available': self._backend is not None,
            'runtime_verified': self._runtime_verified,
            'dependencies_available': dependencies, 'provider': PROVIDER,
            'model': self.model[:200], 'threshold': self.threshold,
            'device': self.device, 'reason': reason,
        }

    def _result(self, status, text, reason, **values) -> GuardResult:
        return GuardResult(status=status, model=self.model[:200], threshold=self.threshold,
                           total_chars=len(text), reason=reason, **values)

    def _load(self) -> bool:
        if self._backend is not None:
            return True
        if self._attempted_load or self._load_error:
            return False
        self._attempted_load = True
        if self._backend_factory is None and not optional_dependencies_available():
            self._load_error = 'Optional torch/transformers dependencies are not installed. Screening did not run.'
            return False
        try:
            self._backend = self._backend_factory() if self._backend_factory else TransformersBackend(
                self.model, self.device, self.cache_dir,
            )
            if not 0 <= self._backend.special_tokens < CONTEXT_TOKENS - OVERLAP_TOKENS:
                raise ValueError('Unsupported classifier window configuration')
            return True
        except Exception:
            # Model/cache exceptions may embed private local paths, tokens, or text.
            self._backend = None
            self._load_error = ('Local classifier or authorized cached model files are unavailable or incompatible. '
                                'Check optional dependencies, model access, cache and device, then restart. Screening did not run.')
            return False

    def screen(self, text: str) -> GuardResult:
        if not self.enabled:
            return self._result('disabled', text, 'Optional Prompt Guard screening is disabled; no detection was performed.')
        if not text.strip():
            return self._result('unavailable', text, 'No readable text was available to screen. Page images were not classified.')
        with self._lock:
            if not self._load():
                return self._result('unavailable', text, self._load_error or 'Classifier unavailable; screening did not run.')
            screened_chars, chunks, maximum = 0, 0, None
            try:
                selected_text = text[:MAX_TEXT_CHARS]
                tokens = self._backend.tokenize(selected_text)
                if len(tokens.ids) != len(tokens.offsets) or not tokens.ids:
                    raise ValueError('Tokenizer returned no usable character offsets')
                budget = CONTEXT_TOKENS - self._backend.special_tokens
                step = budget - OVERLAP_TOKENS
                end = 0
                for start in range(0, len(tokens.ids), step):
                    if chunks >= self.max_chunks:
                        break
                    end = min(start + budget, len(tokens.ids))
                    score = self._backend.malicious_score(tokens.ids[start:end])
                    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
                        raise ValueError('Classifier returned an invalid score')
                    maximum = max(maximum if maximum is not None else 0.0, float(score))
                    chunks += 1
                    self._runtime_verified = True
                    screened_chars = max(screened_chars, min(len(selected_text), tokens.offsets[end - 1][1]))
                    if end == len(tokens.ids):
                        break
                complete = end == len(tokens.ids) and len(selected_text) == len(text)
                if complete:
                    screened_chars = len(text)
                self._runtime_verified = chunks > 0
                if maximum is not None and maximum >= self.threshold:
                    state = 'flagged'
                    reason = 'Classifier score reached the configured review threshold. This is a possible prompt attack, not a proven attack.'
                    if not complete:
                        reason += ' Only part of the text was screened.'
                elif not complete:
                    state = 'error'
                    reason = 'Screening reached its text or chunk limit. The remaining content was not classified; no clear result is claimed.'
                else:
                    state = 'clear'
                    reason = 'No score reached the configured threshold in the screened text. This does not establish safety; false negatives remain possible.'
                return self._result(state, text, reason, score=maximum, screened_chars=screened_chars,
                                    complete=complete, chunks_screened=chunks)
            except Exception:
                if maximum is not None and maximum >= self.threshold:
                    return self._result('flagged', text, 'A screened window reached the review threshold, but further processing failed. Coverage is incomplete; this is a possible attack, not a proven attack.',
                                        score=maximum, screened_chars=screened_chars, chunks_screened=chunks)
                return self._result('error', text, 'Local classifier processing failed. No safety conclusion was accepted.',
                                    score=maximum, screened_chars=screened_chars, chunks_screened=chunks)


def build_prompt_guard(settings) -> PromptGuard:
    return LocalPromptGuard(
        enabled=getattr(settings, 'prompt_guard_enabled', False),
        model=getattr(settings, 'prompt_guard_model', SUPPORTED_MODELS[0]),
        threshold=getattr(settings, 'prompt_guard_threshold', 0.5),
        device=getattr(settings, 'prompt_guard_device', 'cpu'),
        max_chunks=getattr(settings, 'prompt_guard_max_chunks', 64),
        cache_dir=getattr(settings, 'prompt_guard_cache_dir', None) or None,
    )
