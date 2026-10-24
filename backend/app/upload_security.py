"""Conservative receipt intake policy, not a document sandbox or malware scanner."""
import io
import logging
import math
import os
from pathlib import Path
import re
import unicodedata
from uuid import uuid4
import warnings

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
import pymupdf as fitz

logger = logging.getLogger(__name__)
FORMATS = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}
MAX_IMAGE_PIXELS = 25_000_000
MAX_PDF_OBJECTS = 20_000
MAX_PDF_DICTIONARY_TEXT = 2_000_000

# The parsed object representations normalize escaped PDF names. This strict
# policy also rejects open/destination actions and attachments, even benign ones.
# It is deliberately narrower than a general-purpose PDF viewer.
ACTIVE_PDF_NAME = re.compile(
    r'/(?:JavaScript|JS|OpenAction|AA|Launch|SubmitForm|ImportData|GoToR|GoToE|'
    r'RichMedia|EmbeddedFile|EmbeddedFiles|Filespec|FileAttachment|XFA)(?=[\s/<>()\[\]]|$)'
)


def _pdf_dictionary_names(source: str):
    """Read names from the parser's normalized object text, ignoring strings.

    Receipt text or metadata discussing JavaScript is data, not a PDF action.
    Canonical object text is used instead of searching raw compressed bytes.
    """
    index = 0
    while index < len(source):
        character = source[index]
        if character == '(':
            depth = 1
            index += 1
            while index < len(source) and depth:
                if source[index] == '\\':
                    index += 2
                    continue
                depth += (source[index] == '(') - (source[index] == ')')
                index += 1
        elif source[index:index + 2] == '<<':
            index += 2
        elif character == '<':
            end = source.find('>', index + 1)
            index = len(source) if end < 0 else end + 1
        elif character == '%':
            end = source.find('\n', index + 1)
            index = len(source) if end < 0 else end + 1
        elif character == '/':
            end = index + 1
            while end < len(source) and not source[end].isspace() and source[end] not in '/<>()[]{}%':
                end += 1
            yield source[index:end]
            index = end
        else:
            index += 1


def safe_display_filename(filename: str) -> str:
    """Display metadata only; never use a client-supplied name for disk storage."""
    name = filename.replace('\\', '/').rsplit('/', 1)[-1]
    name = unicodedata.normalize('NFKC', name)
    name = ''.join(character for character in name if not unicodedata.category(character).startswith('C'))
    name = re.sub(r'[<>:"/\\|?*]', '_', name).strip(' .')
    return name[:255] or 'document'


def _verify_pdf(data: bytes, settings) -> tuple[str, int]:
    if not data.startswith(b'%PDF-'):
        raise ValueError('Missing PDF signature')
    with fitz.open(stream=data, filetype='pdf') as pdf:
        if not pdf.is_pdf or pdf.needs_pass or pdf.is_repaired or not 1 <= len(pdf) <= settings.max_pages:
            raise ValueError('Encrypted, empty, or over-limit PDF')
        if pdf.embfile_count():
            raise ValueError('PDF attachments are outside receipt intake policy')
        if pdf.xref_length() > MAX_PDF_OBJECTS:
            raise ValueError('PDF object count exceeds processing limit')
        total = 0
        for xref in range(1, pdf.xref_length()):
            source = pdf.xref_object(xref, compressed=True)
            total += len(source)
            if total > MAX_PDF_DICTIONARY_TEXT:
                raise ValueError('PDF object metadata exceeds processing limit')
            if any(ACTIVE_PDF_NAME.fullmatch(name) for name in _pdf_dictionary_names(source)):
                raise ValueError('PDF active content is outside receipt intake policy')
        for page in pdf:
            rectangle = page.rect
            dimensions = (rectangle.width, rectangle.height)
            if rectangle.is_empty or any(not math.isfinite(size) or size <= 0 or size > 4000 for size in dimensions):
                raise ValueError('Unsupported PDF page dimensions')
            page.get_text()
        return 'application/pdf', len(pdf)


def _verify_image(data: bytes, mime: str) -> tuple[str, int]:
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data), formats=('PNG', 'JPEG')) as image:
            actual = {'PNG': 'image/png', 'JPEG': 'image/jpeg'}.get(image.format)
            if actual != mime or not (0 < image.width * image.height <= MAX_IMAGE_PIXELS):
                raise ValueError('Image type or dimensions are outside policy')
            if getattr(image, 'n_frames', 1) != 1 or getattr(image, 'is_animated', False):
                raise ValueError('Animated/multipage images are outside receipt intake policy')
            image.verify()
        # Pillow identification/verify does not guarantee pixel data can decode.
        # Reopen and force the decoder before retaining a private original.
        with Image.open(io.BytesIO(data), formats=('PNG', 'JPEG')) as image:
            image.load()
    return mime, 1


def verify_document(data: bytes, filename: str, supplied_type: str | None, settings) -> tuple[str, int]:
    suffix = Path(filename).suffix.lower()
    if suffix not in FORMATS:
        raise HTTPException(415, 'Only PDF, PNG and JPEG files are accepted')
    mime = FORMATS[suffix]
    if supplied_type and supplied_type not in (mime, 'application/octet-stream'):
        raise HTTPException(415, 'File content type does not match its extension')
    if not data:
        raise HTTPException(400, 'The uploaded file is empty')
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f'File exceeds the {settings.max_upload_mb} MB limit')
    try:
        return _verify_pdf(data, settings) if mime == 'application/pdf' else _verify_image(data, mime)
    except (ValueError, RuntimeError, fitz.FileDataError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, SyntaxError) as exc:
        raise HTTPException(400, 'Malformed, encrypted, active, or over-limit document content') from exc


def write_private_document(storage_dir: Path, data: bytes, suffix: str) -> Path:
    """Write exclusively to a generated private path; never replace another file.

    POSIX creation mode is 0600. Windows storage still needs appropriate ACLs;
    a Unix mode is not claimed to establish equivalent Windows permissions.
    """
    suffix = suffix.lower()
    if suffix not in FORMATS:
        raise HTTPException(415, 'Unsupported document extension')
    location = None
    created = False
    try:
        storage_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        for _ in range(3):
            location = storage_dir / f'{uuid4()}{suffix}'
            try:
                descriptor = os.open(location, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
                created = True
                break
            except FileExistsError:
                continue
        else:
            raise OSError('Unable to reserve a private document name')
        with os.fdopen(descriptor, 'wb') as stream:
            if stream.write(data) != len(data):
                raise OSError('Incomplete private document write')
            stream.flush()
            os.fsync(stream.fileno())
        return location
    except OSError as exc:
        if created and location is not None:
            try:
                location.unlink(missing_ok=True)
            except OSError:
                logger.error('Private document cleanup failed after a storage error; operator intervention is required')
        raise HTTPException(503, 'Private document storage is unavailable; no record was registered') from exc
