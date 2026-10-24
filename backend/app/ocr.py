"""Lazy CPU OCR adapters. Text is evidence, never review authority."""
from functools import lru_cache
import importlib.util
import json
import threading

from PIL import Image, ImageOps

_lock = threading.Lock()
_verified = set()


def available(settings):
    modules = ('rapidocr', 'onnxruntime') if settings.ocr_engine == 'rapidocr' else ('paddleocr', 'paddle')
    return settings.ocr_enabled and all(importlib.util.find_spec(name) is not None for name in modules)


def status(settings):
    return {'engine': settings.ocr_engine, 'enabled': settings.ocr_enabled,
            'available': available(settings), 'runtime_verified': settings.ocr_enabled and settings.ocr_engine in _verified}


@lru_cache(maxsize=2)
def engine(provider):
    if provider == 'rapidocr':
        from rapidocr import RapidOCR
        return RapidOCR(params={'EngineConfig.onnxruntime.intra_op_num_threads': 2,
                                'EngineConfig.onnxruntime.inter_op_num_threads': 1})
    from paddleocr import PaddleOCR
    return PaddleOCR(lang='en', use_doc_orientation_classify=False,
                     use_doc_unwarping=False, use_textline_orientation=False)


def lines_from_boxes(boxes, texts):
    """Keep labels/values on the same visual row instead of one line per box."""
    rows = []
    for box, text in sorted(zip(boxes, texts), key=lambda item: min(p[1] for p in item[0])):
        top, bottom = min(p[1] for p in box), max(p[1] for p in box)
        center, height = (top + bottom) / 2, max(1, bottom - top)
        row = next((r for r in rows if abs(r['center'] - center) <= min(r['height'], height) * 0.5), None)
        if row is None:
            row = {'center': center, 'height': height, 'items': []}
            rows.append(row)
        row['items'].append((min(p[0] for p in box), str(text)))
    return '\n'.join(' '.join(text for _, text in sorted(row['items'])) for row in rows)


def read_image(image, settings):
    if not settings.ocr_enabled:
        return ''
    if not available(settings):
        raise RuntimeError(f'Configured OCR engine {settings.ocr_engine} is unavailable. Install backend/requirements-ocr.txt or explicitly disable OCR.')
    import numpy as np
    picture = ImageOps.exif_transpose(image).convert('RGBA')
    background = Image.new('RGBA', picture.size, 'white')
    background.alpha_composite(picture)
    picture = ImageOps.autocontrast(background.convert('RGB'))
    if max(picture.size) < 1200:
        factor = min(2, 1200 / max(picture.size))
        picture = picture.resize((round(picture.width * factor), round(picture.height * factor)), Image.Resampling.LANCZOS)
    with _lock:
        runtime = engine(settings.ocr_engine)
        if settings.ocr_engine == 'rapidocr':
            result = runtime(np.array(picture))
            texts = list(result.txts) if result.txts is not None else []
            text = lines_from_boxes(result.boxes, texts) if texts else ''
        else:
            texts = []
            for result in runtime.predict(np.array(picture)):
                data = result.json if hasattr(result, 'json') else result
                if callable(data):
                    data = data()
                if isinstance(data, str):
                    data = json.loads(data)
                texts.extend(data.get('res', data).get('rec_texts', []))
            text = '\n'.join(texts)
        _verified.add(settings.ocr_engine)
    return text
