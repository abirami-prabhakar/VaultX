from collections import Counter
from datetime import date, timedelta, timezone
import hashlib
import hmac
from pathlib import Path
import threading

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .extraction import ExtractionFailure, demo_extract, gemma_extract, ocr_available, read_pages, inference_verified
from .ocr import status as ocr_status
from .models import AuditEvent, Base, Document, DocumentScreening, Extraction, Finding, Instrument, ReviewDecision, SecurityLabRun, configure_sqlite, protect_history, uid, utcnow
from .prompt_guard import build_prompt_guard
from .request_security import SecurityBoundaryMiddleware
from .upload_security import verify_document, safe_display_filename, write_private_document
from .samples import SAMPLES, sample_pdf
from .schemas import ExtractRequest, ExtractionFields, FIELD_NAMES, ReviewRequest, parse_date
from .validation import canonical_number, evaluate

TERMINAL = {'approved', 'rejected'}
STATUSES = {'uploaded', 'pending_review', 'clarification_requested', 'approved', 'rejected'}


def iso(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def audit_dict(event):
    return {key: getattr(event, key) for key in ('id', 'instrument_id', 'action', 'actor', 'reason', 'from_status', 'to_status', 'details')} | {'timestamp': iso(event.timestamp)}


def audit(db, instrument, action, actor, reason, previous=None, details=None):
    db.add(AuditEvent(instrument_id=instrument.id, action=action, actor=actor, reason=reason,
                      from_status=previous, to_status=instrument.status, details=details or {}))


def effective_fields(instrument):
    fields = dict.fromkeys(FIELD_NAMES)
    if instrument.extractions:
        fields.update(instrument.extractions[-1].payload['fields'])
    fields.update(instrument.corrected_fields or {})
    return fields


def instrument_dict(db, instrument, detail=False):
    doc = instrument.document
    extraction = instrument.extractions[-1] if instrument.extractions else None
    result = {
        'id': instrument.id, 'status': instrument.status,
        'created_at': iso(instrument.created_at), 'updated_at': iso(instrument.updated_at),
        'filename': doc.filename, 'mime_type': doc.mime_type, 'size_bytes': doc.size_bytes,
        'fields': effective_fields(instrument), 'corrected_fields': instrument.corrected_fields,
        'original_extraction': (extraction.payload | {'mode': extraction.mode, 'model': extraction.model}) if extraction else None,
        'extraction_mode': extraction.mode if extraction else None,
        'extraction_error': instrument.extraction_error,
        'prompt_guard': instrument.screenings[-1].result if instrument.screenings else None,
        'findings': [{key: getattr(item, key) for key in ('id', 'rule_id', 'severity', 'field', 'observed_value', 'expected_value', 'explanation', 'resolved', 'resolution_reason')}
                     for item in instrument.findings if item.active],
    }
    if detail:
        result['audit'] = [audit_dict(event) for event in db.scalars(select(AuditEvent).where(AuditEvent.instrument_id == instrument.id).order_by(AuditEvent.timestamp))]
    return result


def validate_instrument(db, instrument, settings, actor, reason='Deterministic validation completed'):
    fields = effective_fields(instrument)
    number = canonical_number(fields.get('instrument_number'))
    duplicates = []
    if number:
        duplicates = [other.id for other in db.scalars(select(Instrument))
                      if other.id != instrument.id and canonical_number(effective_fields(other).get('instrument_number')) == number]
    extraction = instrument.extractions[-1] if instrument.extractions else None
    generated = evaluate(fields, extraction.payload if extraction else None,
                         extraction.page_texts if extraction else [], instrument.corrected_fields,
                         duplicates, settings)
    if instrument.screenings:
        screening = instrument.screenings[-1].result
        if screening['status'] == 'flagged':
            generated.append(dict(rule_id='PROMPT_INJECTION_REVIEW', severity='warning', field=None,
                                  observed_value=f"{screening['model']}: score {screening['score']}",
                                  expected_value='A human review of possible document instructions',
                                  explanation='The optional classifier flagged possible prompt injection. This may be a false positive; inspect the document and record a reason before resolving.' +
                                              (' Screening was incomplete; also inspect the unscreened remainder.' if not screening['complete'] else '')))
        elif settings.prompt_guard_enabled and screening['status'] != 'disabled' and (not screening['complete'] or screening['status'] in ('error', 'unavailable')):
            generated.append(dict(rule_id='PROMPT_SCREENING_INCOMPLETE', severity='warning', field=None,
                                  observed_value=screening['status'], expected_value='Explicit human review of unscreened document text',
                                  explanation='Optional prompt screening did not fully complete. The document is not certified safe; review its contents manually.'))
    previous = {(f.rule_id, f.field, f.observed_value, f.expected_value, f.explanation): f for f in instrument.findings if f.active}
    for item in instrument.findings:
        item.active = False
    for values in generated:
        signature = tuple(values[key] for key in ('rule_id', 'field', 'observed_value', 'expected_value', 'explanation'))
        finding = previous.get(signature)
        if finding:
            finding.active = True
        else:
            db.add(Finding(instrument_id=instrument.id, **values))
    instrument.updated_at = utcnow()
    audit(db, instrument, 'validation', actor, reason, details={'finding_count': len(generated), 'rules_disabled': settings.disabled_rules})
    db.flush()
    db.expire(instrument, ['findings'])


def refresh_duplicates(db, changed, settings, actor):
    # Recheck peers in the same transaction; resolving one side never hides the other.
    for other in db.scalars(select(Instrument)):
        if other.id != changed.id and other.extractions:
            validate_instrument(db, other, settings, actor, 'Revalidated after a related record changed')


def register_document(db, data, filename, mime, settings, actor, seed_key=None):
    verified_mime, page_count = verify_document(data, filename, mime, settings)
    instrument = Instrument(id=uid(), seed_key=seed_key)
    db.add(instrument)
    db.flush()
    location = write_private_document(settings.storage_dir, data, Path(filename).suffix.lower())
    storage_name = location.name
    db.info.setdefault('created_files', []).append(location)
    document = Document(instrument_id=instrument.id, filename=safe_display_filename(filename),
                        mime_type=verified_mime, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                        storage_name=storage_name, page_count=page_count)
    db.add(document)
    db.flush()
    db.expire(instrument, ['document'])
    audit(db, instrument, 'upload', actor, 'Document registered in private storage', details={'filename': document.filename, 'sha256': document.sha256, 'synthetic': bool(seed_key)})
    db.flush()
    return instrument


def extract_instrument(db, instrument, mode, settings, actor, guard=None):
    if instrument.status in TERMINAL:
        raise HTTPException(409, 'Finalized records cannot be extracted again')
    if instrument.corrected_fields:
        raise HTTPException(409, 'Extraction cannot replace reviewed corrections. Continue with manual corrections and validation.')
    previous = instrument.status
    try:
        page_result = read_pages(settings.storage_dir / instrument.document.storage_name, instrument.document.mime_type, settings)
        texts, images = page_result
        screening = (guard or build_prompt_guard(settings)).screen('\n\n'.join(texts))
        db.add(DocumentScreening(instrument_id=instrument.id, result=screening.model_dump()))
        audit(db, instrument, 'document_screening', actor, screening.reason, previous,
              {'screening': screening.model_dump(), 'advisory_only': True, 'images_screened': False})
        db.flush()
        db.expire(instrument, ['screenings'])
        payload = demo_extract(texts) if mode == 'demo' else gemma_extract(texts, images, settings)
    except (ExtractionFailure, RuntimeError, ValueError, OSError) as exc:
        message = str(exc) if isinstance(exc, ExtractionFailure) else 'The document could not be processed safely. Inspect the original or request clarification.'
        instrument.extraction_error = message
        instrument.updated_at = utcnow()
        audit(db, instrument, 'extraction_failed', actor, message, previous, {'mode': mode})
        db.flush()
        return
    provenance = {'field_extractor': 'labelled_parser' if mode == 'demo' else 'model',
                  'labelled_evidence_hints': mode == 'gemma',
                  'model_repair_attempts': payload._repair_attempts,
                  'pages': getattr(page_result, 'sources', [])}
    extraction = Extraction(instrument_id=instrument.id, mode=mode,
                            model=settings.gemma_model if mode == 'gemma' else None,
                            payload=payload.model_dump() | {'provenance': provenance}, page_texts=texts)
    db.add(extraction)
    instrument.extraction_error = None
    instrument.status = 'pending_review'
    instrument.updated_at = utcnow()
    db.flush()
    db.expire(instrument, ['extractions'])
    audit(db, instrument, 'extraction', actor,
          'Sample labelled-text parser completed; no live AI inference was performed' if mode == 'demo' else 'Configured model returned schema-valid extraction; human review remains required',
          previous, {'mode': mode, 'model': extraction.model, 'extraction_id': extraction.id, 'provenance': provenance})
    validate_instrument(db, instrument, settings, actor)
    refresh_duplicates(db, instrument, settings, actor)


def create_app(settings: Settings | None = None, *, prompt_guard=None, include_security_lab=True):
    settings = settings or Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    url = make_url(settings.database_url)
    if url.drivername.startswith('sqlite') and url.database and url.database != ':memory:':
        Path(url.database).resolve().parent.mkdir(parents=True, exist_ok=True)
    kwargs = {'connect_args': {'check_same_thread': False}} if url.drivername.startswith('sqlite') else {}
    if url.database == ':memory:':
        from sqlalchemy.pool import StaticPool
        kwargs['poolclass'] = StaticPool
    engine = create_engine(settings.database_url, **kwargs)
    configure_sqlite(engine)
    Base.metadata.create_all(engine)
    protect_history(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI(title='VaultX', version='1.0.0', description='Verify with evidence. Decide with confidence. Local demonstration of assisted document review. Findings are review issues, not bank verification or proof of fraud.')
    app.state.engine = engine
    app.state.settings = settings
    guard = prompt_guard if prompt_guard is not None else build_prompt_guard(settings)
    app.state.prompt_guard = guard
    app.add_middleware(SecurityBoundaryMiddleware, settings=settings)
    app.add_middleware(CORSMiddleware, allow_origins=[origin.strip() for origin in settings.frontend_origins.split(',') if origin.strip()],
                       allow_credentials=False, allow_methods=['GET', 'POST'], allow_headers=['Content-Type', 'X-API-Key', 'X-Actor'])

    def authorized(x_api_key: str = Header(default=''), x_actor: str = Header(default='Local reviewer')):
        if not hmac.compare_digest(x_api_key.encode('utf-8'), settings.api_key.encode('utf-8')):
            raise HTTPException(401, 'A valid reviewer API key is required')
        actor = x_actor.strip()
        if not actor or len(actor) > 120:
            raise HTTPException(422, 'Actor must contain 1 to 120 characters')
        return actor

    def database():
        with sessions() as db:
            try:
                # Serialize local SQLite writes so duplicate checking and decisions are atomic.
                if engine.dialect.name == 'sqlite':
                    db.execute(text('BEGIN IMMEDIATE'))
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                for path in db.info.get('created_files', []):
                    path.unlink(missing_ok=True)
                raise

    def get_instrument(db, instrument_id):
        instrument = db.get(Instrument, instrument_id)
        if not instrument:
            raise HTTPException(404, 'FDR record not found')
        return instrument

    @app.get('/health')
    def health():
        return {'status': 'ok', 'extraction_mode': settings.extraction_mode,
                'model': settings.gemma_model or None, 'model_verified': False,
                'ocr_available': ocr_available(settings), 'ocr_runtime_verified': ocr_status(settings)['runtime_verified'],
                'ocr_engine': settings.ocr_engine, 'inference_runtime_verified': inference_verified(settings),
                'max_upload_mb': settings.max_upload_mb, 'max_document_pages': settings.max_pages,
                'prompt_guard': guard.status(), 'security_lab_enabled': settings.security_lab_enabled,
                'demo_auth': True}

    @app.get('/instruments')
    def list_instruments(q: str = Query(default='', max_length=200), status: str | None = None,
                         page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
                         actor=Depends(authorized), db=Depends(database)):
        if status and status not in STATUSES:
            raise HTTPException(422, 'Unknown record status')
        records = list(db.scalars(select(Instrument).order_by(Instrument.created_at.desc())))
        records = [record for record in records if not status or record.status == status]
        if q.strip():
            search = q.strip().casefold()
            records = [record for record in records if search in (' '.join(str(value or '') for value in effective_fields(record).values()) + ' ' + record.id + ' ' + record.document.filename).casefold()]
        return {'items': [instrument_dict(db, record) for record in records[(page - 1) * page_size:page * page_size]],
                'total': len(records), 'page': page, 'page_size': page_size}

    @app.post('/instruments/upload', status_code=201)
    async def upload(file: UploadFile, actor=Depends(authorized), db=Depends(database)):
        data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
        await file.close()
        instrument = register_document(db, data, file.filename or '', file.content_type, settings, actor)
        return instrument_dict(db, instrument, True)

    @app.get('/instruments/{instrument_id}')
    def detail(instrument_id: str, actor=Depends(authorized), db=Depends(database)):
        return instrument_dict(db, get_instrument(db, instrument_id), True)

    @app.post('/instruments/{instrument_id}/extract')
    def extract(instrument_id: str, request: ExtractRequest = Body(default=ExtractRequest()), actor=Depends(authorized), db=Depends(database)):
        instrument = get_instrument(db, instrument_id)
        extract_instrument(db, instrument, request.mode or settings.extraction_mode, settings, actor, guard)
        return instrument_dict(db, instrument, True)

    @app.post('/instruments/{instrument_id}/validate')
    def validate(instrument_id: str, actor=Depends(authorized), db=Depends(database)):
        instrument = get_instrument(db, instrument_id)
        if instrument.status in TERMINAL:
            raise HTTPException(409, 'Finalized records cannot be changed')
        validate_instrument(db, instrument, settings, actor)
        return instrument_dict(db, instrument, True)

    @app.post('/instruments/{instrument_id}/review')
    def review(instrument_id: str, request: ReviewRequest, actor=Depends(authorized), db=Depends(database)):
        instrument = get_instrument(db, instrument_id)
        if instrument.status in TERMINAL:
            raise HTTPException(409, 'Finalized records are read-only')
        previous = instrument.status
        changes = None
        if request.action == 'correct':
            if not instrument.extractions:
                raise HTTPException(409, 'Run extraction before correcting fields')
            if instrument.extraction_error:
                raise HTTPException(409, 'Retry extraction successfully before correcting fields; explicitly select sample mode if live inference is unavailable')
            changes = request.fields.model_dump(exclude_unset=True) if request.fields else {}
            if not changes:
                raise HTTPException(422, 'Provide at least one field correction')
            before = effective_fields(instrument)
            instrument.corrected_fields = (instrument.corrected_fields or {}) | changes
            instrument.status = 'pending_review'
            audit(db, instrument, 'correction', actor, request.reason, previous, {'before': {key: before[key] for key in changes}, 'after': changes})
            validate_instrument(db, instrument, settings, actor, 'Revalidated after reviewer correction')
            refresh_duplicates(db, instrument, settings, actor)
        elif request.action == 'resolve':
            finding = next((item for item in instrument.findings if item.id == request.finding_id and item.active), None)
            if not finding:
                raise HTTPException(404, 'Active finding not found')
            if finding.resolved:
                raise HTTPException(409, 'Finding is already resolved')
            finding.resolved = True
            finding.resolution_reason = request.reason
            audit(db, instrument, 'finding_resolved', actor, request.reason, previous, {'finding_id': finding.id, 'rule_id': finding.rule_id})
        elif request.action == 'clarify':
            instrument.status = 'clarification_requested'
            audit(db, instrument, 'clarification_requested', actor, request.reason, previous)
        else:
            if instrument.status == 'uploaded' or not instrument.extractions:
                raise HTTPException(409, 'Run extraction and review the record before a final decision')
            if request.action == 'approve':
                if instrument.status != 'pending_review':
                    raise HTTPException(409, 'Correct or re-extract the record to return clarification to pending review before approval')
                validate_instrument(db, instrument, settings, actor, 'Validation before approval')
                if any(item.active and not item.resolved for item in instrument.findings):
                    raise HTTPException(409, 'Resolve every active finding before approval')
                if instrument.extraction_error:
                    raise HTTPException(409, 'A failed extraction must be addressed before approval')
            instrument.status = 'approved' if request.action == 'approve' else 'rejected'
            audit(db, instrument, request.action, actor, request.reason, previous)
        instrument.updated_at = utcnow()
        db.add(ReviewDecision(instrument_id=instrument.id, action=request.action, actor=actor, reason=request.reason, fields=changes))
        db.flush()
        return instrument_dict(db, instrument, True)

    @app.get('/instruments/{instrument_id}/audit')
    def record_audit(instrument_id: str, actor=Depends(authorized), db=Depends(database)):
        get_instrument(db, instrument_id)
        return [audit_dict(event) for event in db.scalars(select(AuditEvent).where(AuditEvent.instrument_id == instrument_id).order_by(AuditEvent.timestamp))]

    @app.get('/audit')
    def all_audit(limit: int = Query(default=100, ge=1, le=500), actor=Depends(authorized), db=Depends(database)):
        return [audit_dict(event) for event in db.scalars(select(AuditEvent).order_by(AuditEvent.timestamp.desc()).limit(limit))]

    @app.get('/instruments/{instrument_id}/document')
    def document(instrument_id: str, actor=Depends(authorized), db=Depends(database)):
        instrument = get_instrument(db, instrument_id)
        path = settings.storage_dir / instrument.document.storage_name
        if not path.is_file():
            raise HTTPException(404, 'Private document file is missing')
        return FileResponse(path, media_type=instrument.document.mime_type, filename=instrument.document.filename,
                            content_disposition_type='inline', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @app.get('/dashboard')
    def dashboard(actor=Depends(authorized), db=Depends(database)):
        records = list(db.scalars(select(Instrument)))
        counts = Counter(record.status for record in records)
        due = []
        today, end = date.today(), date.today() + timedelta(days=settings.reminder_days)
        for record in records:
            try:
                maturity = parse_date(effective_fields(record).get('maturity_date'))
            except ValueError:
                continue
            if record.status != 'rejected' and maturity and today <= maturity <= end:
                due.append((maturity, record))
        due.sort(key=lambda pair: pair[0])
        return {'total': len(records), 'pending': sum(counts[s] for s in ('uploaded', 'pending_review', 'clarification_requested')),
                'flagged': sum(any(f.active and not f.resolved for f in record.findings) for record in records),
                'upcoming': len(due), 'upcoming_instruments': [instrument_dict(db, record) for _, record in due[:10]],
                'by_status': dict(counts), 'reminder_days': settings.reminder_days,
                'minimum_amount': str(settings.minimum_amount), 'currency': settings.currency, 'extraction_mode': settings.extraction_mode,
                'activity': [audit_dict(event) for event in db.scalars(select(AuditEvent).order_by(AuditEvent.timestamp.desc()).limit(8))]}

    @app.get('/samples')
    def samples(actor=Depends(authorized)):
        return SAMPLES

    @app.get('/samples/{name}')
    def sample(name: str, actor=Depends(authorized)):
        if name not in {entry['name'] for entry in SAMPLES}:
            raise HTTPException(404, 'Synthetic sample not found')
        return Response(sample_pdf(name), media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="{name}"'})

    @app.post('/demo/seed')
    def seed(actor=Depends(authorized), db=Depends(database)):
        created = []
        for entry in SAMPLES:
            if db.scalar(select(Instrument).where(Instrument.seed_key == entry['name'])):
                continue
            instrument = register_document(db, sample_pdf(entry['name']), entry['name'], 'application/pdf', settings, actor, entry['name'])
            extract_instrument(db, instrument, 'demo', settings, actor, guard)
            created.append(instrument.id)
        return {'created': len(created), 'instrument_ids': created, 'message': 'Synthetic samples only; no bank verification or live model inference performed.'}

    if settings.security_lab_enabled and include_security_lab:
        from .security_lab import CONTROLS, guard_status, run_security_lab

        lab_lock = threading.Lock()

        @app.get('/security-lab')
        def security_lab_inventory(actor=Depends(authorized), db=Depends(database)):
            latest = db.scalar(select(SecurityLabRun).order_by(SecurityLabRun.created_at.desc()).limit(1))
            return {'controls': CONTROLS, 'guard': guard_status(guard), 'last_run': latest.report if latest else None}

        @app.post('/security-lab/run')
        def security_lab_run(actor=Depends(authorized)):
            if not lab_lock.acquire(blocking=False):
                raise HTTPException(409, 'A Security Lab run is already in progress')
            try:
                report = run_security_lab(settings, guard, create_app)
                with sessions.begin() as db:
                    db.add(SecurityLabRun(id=report['id'], actor=actor, report=report))
                return report
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(503, 'The isolated Security Lab could not complete or persist its report. No successful result was recorded.') from exc
            finally:
                lab_lock.release()

    return app


app = create_app()
