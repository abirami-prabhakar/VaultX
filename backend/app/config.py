from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import math
import os

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env')


@dataclass
class Settings:
    database_url: str = os.getenv('DATABASE_URL', f'sqlite:///{(ROOT / ".data" / "fdr.db").as_posix()}')
    storage_dir: Path = Path(os.getenv('STORAGE_DIR', str(ROOT / '.data' / 'documents'))).resolve()
    api_key: str = os.getenv('API_KEY', '')
    frontend_origins: str = os.getenv('FRONTEND_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173')
    extraction_mode: str = os.getenv('EXTRACTION_MODE', 'demo')
    gemma_base_url: str = os.getenv('GEMMA_BASE_URL', '')
    gemma_model: str = os.getenv('GEMMA_MODEL', '')
    gemma_api_key: str = os.getenv('GEMMA_API_KEY', '')
    gemma_timeout: float = float(os.getenv('GEMMA_TIMEOUT_SECONDS', '180'))
    max_upload_mb: int = int(os.getenv('MAX_UPLOAD_MB', '10'))
    max_pages: int = int(os.getenv('MAX_DOCUMENT_PAGES', '30'))
    minimum_amount: Decimal = Decimal(os.getenv('MINIMUM_AMOUNT', '10000'))
    currency: str = os.getenv('DEFAULT_CURRENCY', 'INR')
    reminder_days: int = int(os.getenv('REMINDER_DAYS', '30'))
    ocr_enabled: bool = os.getenv('OCR_ENABLED', 'true').lower() == 'true'
    ocr_engine: str = os.getenv('OCR_ENGINE', 'rapidocr')
    ocr_dpi: int = int(os.getenv('OCR_DPI', '200'))
    gemma_response_format: str = os.getenv('GEMMA_RESPONSE_FORMAT', 'json_schema')
    gemma_max_tokens: int = int(os.getenv('GEMMA_MAX_TOKENS', '1600'))
    gemma_repair_attempts: int = int(os.getenv('GEMMA_REPAIR_ATTEMPTS', '1'))
    gemma_supports_vision: bool = os.getenv('GEMMA_SUPPORTS_VISION', 'false').lower() == 'true'
    required_fields: str = os.getenv('REQUIRED_FIELDS', 'instrument_number,bank_name,amount,currency,issue_date,maturity_date,holder_name')
    disabled_rules: str = os.getenv('DISABLED_RULES', '')
    prompt_guard_enabled: bool = os.getenv('PROMPT_GUARD_ENABLED', 'false').lower() == 'true'
    prompt_guard_model: str = os.getenv('PROMPT_GUARD_MODEL', 'meta-llama/Llama-Prompt-Guard-2-22M')
    prompt_guard_threshold: float = float(os.getenv('PROMPT_GUARD_THRESHOLD', '0.5'))
    prompt_guard_device: str = os.getenv('PROMPT_GUARD_DEVICE', 'cpu')
    prompt_guard_max_chunks: int = int(os.getenv('PROMPT_GUARD_MAX_CHUNKS', '64'))
    prompt_guard_cache_dir: str = os.getenv('PROMPT_GUARD_CACHE_DIR', '')
    security_lab_enabled: bool = os.getenv('SECURITY_LAB_ENABLED', 'true').lower() == 'true'
    request_timeout_seconds: float = float(os.getenv('REQUEST_TIMEOUT_SECONDS', '30'))
    rate_limit_requests: int = int(os.getenv('RATE_LIMIT_REQUESTS', '600'))
    rate_limit_window_seconds: float = float(os.getenv('RATE_LIMIT_WINDOW_SECONDS', '60'))

    def __post_init__(self):
        if not self.api_key.strip():
            raise ValueError('API_KEY is required. Run npm run setup locally, or configure a unique backend API_KEY.')
        if self.extraction_mode not in ('demo', 'gemma'):
            raise ValueError('EXTRACTION_MODE must be demo or gemma')
        if self.ocr_engine not in ('rapidocr', 'paddleocr') or not 100 <= self.ocr_dpi <= 300:
            raise ValueError('OCR_ENGINE must be rapidocr or paddleocr; OCR_DPI must be 100–300')
        if self.gemma_response_format not in ('json_schema', 'json_object') or not 128 <= self.gemma_max_tokens <= 4096:
            raise ValueError('Invalid inference response format or token budget')
        if self.gemma_repair_attempts not in (0, 1):
            raise ValueError('GEMMA_REPAIR_ATTEMPTS must be 0 or 1')
        if not self.minimum_amount.is_finite() or self.minimum_amount < 0:
            raise ValueError('MINIMUM_AMOUNT must be a finite non-negative decimal')
        if self.max_upload_mb < 1 or self.max_pages < 1 or self.reminder_days < 0:
            raise ValueError('File, page and reminder limits are invalid')
        if not math.isfinite(self.prompt_guard_threshold) or not 0 < self.prompt_guard_threshold < 1:
            raise ValueError('PROMPT_GUARD_THRESHOLD must be between zero and one')
        if not 1 <= self.prompt_guard_max_chunks <= 512:
            raise ValueError('PROMPT_GUARD_MAX_CHUNKS must be between 1 and 512')
        if not math.isfinite(self.gemma_timeout) or self.gemma_timeout <= 0:
            raise ValueError('GEMMA_TIMEOUT_SECONDS must be finite and positive')
        if not math.isfinite(self.request_timeout_seconds) or self.request_timeout_seconds <= 0:
            raise ValueError('REQUEST_TIMEOUT_SECONDS must be finite and positive')
        if self.rate_limit_requests < 1 or not math.isfinite(self.rate_limit_window_seconds) or self.rate_limit_window_seconds <= 0:
            raise ValueError('Rate limit count and window must be positive')
