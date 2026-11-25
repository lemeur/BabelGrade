"""Async job queue for the long processing steps (Whisper transcription,
PDF/scan extraction, LLM analysis, run-ai).

Design
------
* The request handlers in main.py stage (validate + save) all uploads fast,
  create the submission + analysis rows, then enqueue a **job** and return a
  job handle immediately. Nothing heavy happens in the request thread.
* A small worker pool (size = the configurable ``max_workers`` setting,
  default 1) claims jobs from the persisted ``jobs`` table and runs them in
  the background. Because jobs are persisted, the queue survives a restart:
  on boot any job left ``running`` is re-queued.
* Each job's progress (phases + LLM tokens) is streamed to any live SSE
  subscriber via an in-memory :class:`JobStream`. Late subscribers (or a
  subscriber that connects after the job already finished) get the full log
  replayed, and once the in-memory log has been GC'd the terminal state is
  rebuilt from the DB.

The heavy, blocking calls (whisper, pymupdf, the LLM HTTP call) are run in a
thread pool via ``asyncio.to_thread`` so the event loop stays responsive.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path

from . import assess, auth, config, db, llm_client, whisper
from .rubrics import compute_attestation

# media.py's staging helpers (deferred import to avoid a circular import at
# module load — media imports jobs at top level, so jobs imports media
# lazily; the redirect used to target main.py before the 2026-10-16 split).
def _media():
    from . import media
    return media


# --------------------------------------------------------------------- settings
# V5-C2 (2026-11-24): default raised 1 -> 3. Three concurrent "Analyze with AI"
# jobs used to SERIALIZE (the 3rd waited 3-4 min). Proven safe: a live SGLang
# probe (3 parallel chat requests) showed ~1.6x wall-clock speedup vs serial,
# i.e. SGLang batches them. Override with BABELGRADE_MAX_WORKERS (1..4) — e.g.
# drop to 1 on a memory-constrained box or raise to 4 once capacity is proven.
DEFAULT_MAX_WORKERS = 3
MAX_WORKERS_CAP = 4


def max_workers() -> int:
    # Priority: BABELGRADE_MAX_WORKERS env > stored DB setting > default.
    env = os.environ.get("BABELGRADE_MAX_WORKERS")
    if env:
        try:
            return max(1, min(int(env), MAX_WORKERS_CAP))
        except (TypeError, ValueError):
            pass
    try:
        v = int(db.get_setting("max_workers", str(DEFAULT_MAX_WORKERS)) or DEFAULT_MAX_WORKERS)
    except (TypeError, ValueError):
        v = DEFAULT_MAX_WORKERS
    return max(1, min(v, MAX_WORKERS_CAP))


# --------------------------------------------------------------------- streams
class JobStream:
    """Thread-safe per-job event log + live subscriber fan-out.

    ``push`` is called both from the event loop and from the worker thread
    (the LLM stream iterator). Subscribers are ``asyncio.Queue``s; items are
    delivered to them via ``loop.call_soon_threadsafe`` so it is safe to push
    from the worker thread.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.log: list[tuple[str, dict]] = []
        self._subs: list[asyncio.Queue] = []
        self._lock = threading.Lock()
        self.finished = False
        self._created = time.time()

    def push(self, event: str, data: dict) -> None:
        item = (event, data)
        with self._lock:
            self.log.append(item)
            subs = list(self._subs)
            fin = self.finished
        for q in subs:
            self._safe(q.put_nowait, item)
        if fin:
            for q in subs:
                self._safe(q.put_nowait, None)

    def finish(self) -> None:
        with self._lock:
            self.finished = True
            subs = list(self._subs)
        for q in subs:
            self._safe(q.put_nowait, None)

    def _safe(self, fn, *a, **k):
        try:
            self.loop.call_soon_threadsafe(fn, *a, **k)
        except RuntimeError:  # loop closed / task cancelling
            pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subs.append(q)
            replay = list(self.log)
            fin = self.finished
        for e, d in replay:
            q.put_nowait((e, d))
        if fin:
            q.put_nowait(None)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)


_STREAMS: dict[int, JobStream] = {}
_STREAMS_LOCK = threading.Lock()
_LOOP: asyncio.AbstractEventLoop | None = None
STREAM_TTL_S = 15 * 60   # keep a finished job's log this long for late readers


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _LOOP
    _LOOP = loop


def _new_stream(job_id: int) -> JobStream:
    loop = _LOOP or asyncio.get_running_loop()
    js = JobStream(loop)
    with _STREAMS_LOCK:
        _STREAMS[job_id] = js
    return js


def get_stream(job_id: int) -> JobStream | None:
    with _STREAMS_LOCK:
        return _STREAMS.get(job_id)


def drop_stream(job_id: int) -> None:
    with _STREAMS_LOCK:
        js = _STREAMS.pop(job_id, None)
    if js:
        js.finish()


def _gc_streams() -> None:
    """Drop finished in-memory streams older than STREAM_TTL_S."""
    now = time.time()
    with _STREAMS_LOCK:
        stale = [jid for jid, js in _STREAMS.items()
                 if js.finished and now - js._created > STREAM_TTL_S]
    for jid in stale:
        drop_stream(jid)


# --------------------------------------------------------------------- phases
PHASE_PREPARING = "preparing"
PHASE_TRANSCRIBING = "transcribing"
PHASE_OCRING = "ocring"
PHASE_ANALYZING = "analyzing"
PHASE_PERSISTING = "persisting"


def _set_phase(job_id: int, phase: str, js: JobStream) -> None:
    db.job_update(job_id, phase=phase)
    js.push("phase", {"phase": phase})


def _cancelled(job_id: int) -> bool:
    j = db.job_get(job_id)
    return bool(j and j.get("cancel_flag"))


def ensure_copy_ocr(sub_id: int | None) -> int | None:
    """Auto-OCR: enqueue the LLM OCR job for a written submission's page
    photos when it hasn't run yet.

    A written photo copy analyzed by the AI should already have its Annoter
    transcription available afterwards (the teacher may want to check what
    the AI read, or annotate the copy immediately). OCR is a SEPARATE LLM
    pass from the analysis (the analyze job never writes ocr_json), so this
    helper chains it automatically — called at the end of the ``analyze``
    and ``run_ai`` jobs.

    Idempotent: a finished OCR or a queued/running OCR job → no-op. Never
    raises (a failure here must never fail the analysis job). Returns the
    new OCR job id when enqueued, else None.
    """
    if not sub_id:
        return None
    try:
        sub = db.get_submission(sub_id)
    except Exception:
        return None
    if not sub or sub.get("kind") != "written":
        return None
    if sub.get("ocr"):
        return None
    if not (sub.get("payload_meta") or {}).get("page_paths"):
        return None
    try:
        with db._LOCK:
            n = db._conn().execute(
                "SELECT COUNT(*) FROM jobs WHERE submission_id=? AND kind='ocr' "
                "AND status IN ('queued','running')", (sub_id,)).fetchone()[0]
        if n:
            return None
        return db.create_job("ocr", {"submission_id": sub_id},
                             submission_id=sub_id)
    except Exception:
        return None


# --------------------------------------------------------------------- helpers
def _data_urls_from_names(names: list) -> list:
    m = _media()
    return m._data_urls_from_names(names)


def _extract_pdf_file(pdf_path: Path, label: str, page_prefix: str) -> tuple[str, list, list]:
    """Extract text from a SAVED pdf; render scanned pages to JPEGs in uploads.

    Returns (text, page_data_urls, page_names). Mirrors main._extract_pdf but
    reads from a file on disk instead of an UploadFile.
    """
    m = _media()
    data = pdf_path.read_bytes()
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    n_pages = doc.page_count
    text = "\n".join(p.get_text("text") for p in doc).strip()
    page_urls: list = []
    page_names: list = []
    if not text:  # scanned PDF without a text layer -> vision
        for i in range(min(n_pages, config.MAX_DOC_PDF_PAGES)):
            pix = doc[i].get_pixmap(dpi=150)
            name = f"{page_prefix}-p{i + 1}.jpg"
            (config.UPLOAD_DIR / name).write_bytes(pix.tobytes("jpeg"))
            page_names.append(name)
            page_urls.append(m._b64_from_bytes(pix.tobytes("jpeg"), "image/jpeg"))
    doc.close()
    return text, page_urls, page_names


def _student_work_pdf(p: dict) -> tuple[str, list, list]:
    """Render the student's work PDF (2026-11-25): (text, page_data_urls,
    page_names).

    A student may hand in the copy as a single PDF instead of page photos.
    Same pipeline as a task-context PDF: if the PDF carries a text layer,
    its text becomes the written work; if it is scanned (no text layer),
    its pages are rendered to JPEGs in uploads and used like page photos.
    The rendered page names are returned so they can replace the submission's
    page_paths (Annoter OCR + media ownership follow from there).
    """
    name = p.get("copy_pdf_name")
    if not name:
        return "", [], []
    pp = config.UPLOAD_DIR / name
    if not pp.is_file():
        return "", [], []
    text, page_urls, page_names = _extract_pdf_file(
        pp, "student work", f"pdf-{name[4:36]}")
    return text, page_urls, page_names


# --------------------------------------------------------------------- report
def _copy_text_basis(sub_id: int | None) -> dict | None:
    """What the teacher can READ about a written copy in the report.

    The analyze LLM pass grades the grid and never transcribes the copy, so
    the teacher had no way to see "what the AI actually read" (and the
    Annoter needed the OCR before it could be used at all). This helper
    reports the copy's text basis for the report's "Copy transcription" card:

      - written + page photos, OCR ready   -> {mode:"ocr", text}
      - written + page photos, OCR queued/running -> {mode:"running",
        job_id}   (the UI auto-refreshes once the auto-OCR job lands)
      - written + page photos, no OCR yet  -> {mode:"none"}
      - written pasted text                -> {mode:"text", text}
      - oral                                -> None (the transcript card
        already shows the ASR transcript + timestamps)
    """
    if not sub_id:
        return None
    try:
        sub = db.get_submission(sub_id)
    except Exception:
        return None
    if not sub:
        return None
    if sub.get("kind") != "written":
        return None
    if (sub.get("payload_meta") or {}).get("page_paths"):
        ocr = sub.get("ocr")
        if ocr and ocr.get("pages"):
            lines = []
            for pg in ocr["pages"]:
                for ln in pg.get("lines") or []:
                    if (ln.get("text") or "").strip():
                        lines.append(ln["text"])
            return {"mode": "ocr",
                    "text": "\n".join(lines).strip() or None}
        with db._LOCK:
            row = db._conn().execute(
                "SELECT id FROM jobs WHERE submission_id=? AND kind='ocr' "
                "AND status IN ('queued','running') LIMIT 1",
                (sub_id,)).fetchone()
        if row:
            return {"mode": "running", "job_id": row[0]}
        return {"mode": "none"}
    return {"mode": "text", "text": (sub.get("payload_path") or "").strip() or None}


def _report_payload(analysis_id: int, *, parsed: bool = True,
                    raw: str = "", warnings: list | None = None,
                    attestation: dict | None = None) -> dict:
    """UI-ready report dict (the shape renderReport() expects, keyed `data`)."""
    a = db.get_analysis(analysis_id) or {}
    rubric = db.get_rubric(a.get("rubric_id") or "") if a.get("rubric_id") else None
    matrix = a.get("matrix")
    try:
        matrix = json.loads(a["matrix_json"]) if a.get("matrix_json") else None
    except Exception:
        matrix = None
    ai_matrix = None
    try:
        ai_matrix = json.loads(a["ai_matrix_json"]) if a.get("ai_matrix_json") else None
    except Exception:
        ai_matrix = None
    fluency = None
    try:
        fluency = json.loads(a["fluency_json"]) if a.get("fluency_json") else None
    except Exception:
        fluency = None
    transcript = None
    try:
        transcript = json.loads(a["transcript_json"]) if a.get("transcript_json") else None
    except Exception:
        transcript = None
    note20 = None
    try:
        note20 = json.loads(a["note20_json"]) if a.get("note20_json") else None
    except Exception:
        note20 = None
    transcript_correction = None
    try:
        transcript_correction = (json.loads(a["transcript_correction_json"])
                                 if a.get("transcript_correction_json") else None)
    except Exception:
        transcript_correction = None
    if attestation is None and rubric and rubric.get("attestation") and matrix:
        attestation = compute_attestation(rubric, matrix.get("rubric_mapping", []))
    return {
        "id": analysis_id,
        "submission_id": a.get("submission_id"),
        "data": matrix,
        "ai_data": ai_matrix,
        "aiMode": a.get("ai_mode"),
        "aiAt": a.get("ai_at"),
        "parsed": parsed,
        "raw": raw or (a.get("raw_markdown") or ""),
        "warnings": warnings or [],
        "fluency": fluency,
        "transcript": transcript,
        "copy_text": _copy_text_basis(a.get("submission_id")),
        "transcript_correction": transcript_correction,
        "transcript_mode": a.get("transcript_mode"),
        "annotations": db.list_annotations(a.get("submission_id")) if a.get("submission_id") else [],
        "attestation": attestation,
        "validated": bool(a.get("validated_at")),
        "note20": note20,
        "rubric_id": a.get("rubric_id"),
        "rubric_name": rubric.get("name") if rubric else None,
    }


# --------------------------------------------------------------------- analyze
async def _stage_and_run_analyze(job_id: int, js: JobStream, payload: dict) -> None:
    m = _media()
    p = payload
    kind = p.get("kind") or "written"
    rubric = db.get_rubric(p.get("rubric_id") or "")
    if not rubric:
        raise ValueError("valid rubric_id required")
    if not db.rubric_matches_mode(rubric, kind):
        raise ValueError(f"rubric '{rubric['name']}' does not apply to a {kind} submission")

    # assignment (linked) materials are resolved from stored rows; ad-hoc uses
    # the staged files referenced in the payload.
    assignment_id = p.get("assignment_id") or None
    assignment = db.get_assignment(assignment_id) if assignment_id else None
    if assignment_id and not assignment:
        raise ValueError("assignment not found")

    _set_phase(job_id, PHASE_PREPARING, js)

    # ---- context (instruction + source document) ----
    if assignment:
        assignment_context = m._assignment_context_from_assignment(assignment)
        eval_notes = m._assignment_eval_notes_from_assignment(assignment)
        inherited_target = assignment.get("target_level")
    else:
        assignment_context, eval_notes = await asyncio.to_thread(
            _build_adhoc_context, p)
        inherited_target = None

    # ---- student work: written pages / oral audio ----
    written_text = (p.get("written_text") or "").strip()
    image_names = p.get("image_names") or []
    audio_name = p.get("audio_name")
    image_data_urls: list = []
    transcript = None

    if kind == "oral":
        if not audio_name:
            raise ValueError("oral analysis requires an audio upload")
        _set_phase(job_id, PHASE_TRANSCRIBING, js)
        if _cancelled(job_id):
            return _mark_cancelled(job_id, js)
        lang = p.get("language") or "en"
        transcript = await asyncio.to_thread(
            whisper.transcribe, str(config.UPLOAD_DIR / audio_name), lang)
    else:
        if not written_text and not image_names and not p.get("copy_pdf_name"):
            raise ValueError("provide written text or page photo(s) or the PDF")
        if image_names:
            image_data_urls = _data_urls_from_names(image_names)
        # 2026-11-25: work-as-PDF. A text-layer PDF supplements the written
        # text; a scanned PDF renders its pages to JPEGs that act as the
        # page photos (they replace image_names so they are persisted as
        # page_paths -> Annoter OCR + media ownership follow from there).
        pdf_text, pdf_urls, pdf_names = _student_work_pdf(p)
        if pdf_text:
            written_text = (written_text + "\n\n" + pdf_text).strip()
        if pdf_urls:
            image_data_urls = pdf_urls
            image_names = pdf_names

    # ---- persistence: submission + analysis already created by the request
    # handler (ids carried in the job row); fill them in now. ----
    sub_id = db.job_get(job_id).get("submission_id")
    analysis_id = db.job_get(job_id).get("analysis_id")
    effective_target = (p.get("target_level") or inherited_target or None)

    sub_payload, source_type = _payload_of(kind, written_text, image_data_urls,
                                           transcript, image_names)
    db.update_submission(sub_id, payload_path=sub_payload, source_type=source_type,
                         language=(transcript["language"] if transcript else p.get("language") or ""),
                         duration_s=(transcript["duration_s"] if transcript else None),
                         target_level=effective_target,
                         payload_meta=_submission_payload_meta(kind, audio_name,
                                                               image_names,
                                                               p.get("copy_pdf_name")),
                         context=m._strip_persist_context(assignment_context)
                         if assignment else _strip_ctx(assignment_context),
                         eval_notes=m._strip_persist_eval_notes(eval_notes)
                         if assignment else _strip_en(eval_notes),
                         accommodations=p.get("accommodations") or None)

    fluency = assess.fluency_metrics(transcript) if transcript else None
    transcript_blob = ({"text": transcript["text"], "segments": transcript["segments"],
                        "duration_s": transcript["duration_s"],
                        "language": transcript["language"],
                        "words": transcript.get("words") or []}
                       if transcript else None)

    ctx_lines = []
    if p.get("student_id"):
        ctx_lines.append(f"Student id: {p['student_id']}")
    if assignment_id:
        ctx_lines.append(f"Linked assignment: {assignment['name']}")

    messages = assess.build_messages(
        kind=kind, rubric=rubric, student_context="\n".join(ctx_lines),
        written_text=(written_text or None) if kind == "written" else None,
        image_data_urls=image_data_urls if kind == "written" else None,
        oral_transcript=(assess.transcript_with_timestamps(transcript)
                         if transcript else None),
        oral_metadata=fluency,
        target_level=effective_target,
        assignment_context=assignment_context,
        eval_notes=eval_notes,
        accommodations=p.get("accommodations") or None,
        ui_language=p.get("ui_language") or None,
    )

    _set_phase(job_id, PHASE_ANALYZING, js)
    if _cancelled(job_id):
        return _mark_cancelled(job_id, js)

    full, usage = await _run_llm_stream(job_id, js, messages)

    parsed = assess.parse_result(full)
    data = parsed["data"]
    warnings = assess.validate_matrix(data, rubric) if data else [parsed["error"]]
    attestation = compute_attestation(rubric, (data or {}).get("rubric_mapping", []))
    if attestation and attestation.get("unmapped"):
        warnings.append("Certains critères n'ont pas pu être notés sur la "
                        "échelle A1–C2 ; le score d'attestation est à valider.")
    if not parsed["ok"] and usage.get("truncated"):
        warnings.append("The model hit the token limit before finishing its "
                        "reply; the analysis may be incomplete. Try again.")

    _set_phase(job_id, PHASE_PERSISTING, js)
    db.update_analysis(
        analysis_id,
        raw_markdown=full,
        overall_level=(data or {}).get("overall_level"),
        matrix_json=json.dumps(data, ensure_ascii=False) if data else None,
        feedback=json.dumps((data or {}).get("student_feedback"), ensure_ascii=False),
        fluency_json=json.dumps(fluency, ensure_ascii=False) if fluency else None,
        transcript_json=json.dumps(transcript_blob, ensure_ascii=False),
        ai_matrix_json=json.dumps(data, ensure_ascii=False) if data else None,
        ai_mode="blind",
        ai_at=db.now_iso(),
        status="done",
    )
    # Auto-OCR: a written photo copy should have its Annoter transcription
    # ready right after the analysis. The analyze LLM pass never writes
    # ocr_json (it only grades the grid), so enqueue the OCR job in the
    # background here — the Annoter follows it live. Idempotent + no-op for
    # oral / text-only / already-OCRed copies.
    ensure_copy_ocr(sub_id)
    _finalize(job_id, js, "done", report=_report_payload(analysis_id,
                parsed=parsed["ok"], raw=full, warnings=warnings,
                attestation=attestation))


# ------------------------------------------------------------------ evaluate
async def _stage_and_run_evaluate(job_id: int, js: JobStream, payload: dict) -> None:
    """Teacher-first flow: stage + (if oral) transcribe, then create the empty
    skeleton matrix. No LLM call — the AI is added later via run_ai."""
    m = _media()
    p = payload
    kind = p.get("kind") or "written"
    rubric = db.get_rubric(p.get("rubric_id") or "")
    if not rubric:
        raise ValueError("valid rubric_id required")
    if not db.rubric_matches_mode(rubric, kind):
        raise ValueError(f"rubric '{rubric['name']}' does not apply to a {kind} submission")

    assignment_id = p.get("assignment_id") or None
    assignment = db.get_assignment(assignment_id) if assignment_id else None
    if assignment_id and not assignment:
        raise ValueError("assignment not found")

    _set_phase(job_id, PHASE_PREPARING, js)
    if assignment:
        assignment_context = m._assignment_context_from_assignment(assignment)
        eval_notes = m._assignment_eval_notes_from_assignment(assignment)
        inherited_target = assignment.get("target_level")
    else:
        assignment_context, eval_notes = await asyncio.to_thread(
            _build_adhoc_context, p)
        inherited_target = None

    written_text = (p.get("written_text") or "").strip()
    image_names = p.get("image_names") or []
    audio_name = p.get("audio_name")
    image_data_urls: list = []
    transcript = None

    if kind == "oral":
        if not audio_name:
            raise ValueError("oral evaluation requires an audio upload")
        _set_phase(job_id, PHASE_TRANSCRIBING, js)
        if _cancelled(job_id):
            return _mark_cancelled(job_id, js)
        lang = p.get("language") or "en"
        transcript = await asyncio.to_thread(
            whisper.transcribe, str(config.UPLOAD_DIR / audio_name), lang)
    else:
        if not written_text and not image_names and not p.get("copy_pdf_name"):
            raise ValueError("provide written text or page photo(s) or the PDF")
        if image_names:
            image_data_urls = _data_urls_from_names(image_names)
        # 2026-11-25: work-as-PDF. A text-layer PDF supplements the written
        # text; a scanned PDF renders its pages to JPEGs that act as the
        # page photos (they replace image_names so they are persisted as
        # page_paths -> Annoter OCR + media ownership follow from there).
        pdf_text, pdf_urls, pdf_names = _student_work_pdf(p)
        if pdf_text:
            written_text = (written_text + "\n\n" + pdf_text).strip()
        if pdf_urls:
            image_data_urls = pdf_urls
            image_names = pdf_names

    sub_id = db.job_get(job_id).get("submission_id")
    analysis_id = db.job_get(job_id).get("analysis_id")
    effective_target = (p.get("target_level") or inherited_target or None)
    sub_payload, source_type = _payload_of(kind, written_text, image_data_urls,
                                           transcript, image_names)
    db.update_submission(sub_id, payload_path=sub_payload, source_type=source_type,
                         language=(transcript["language"] if transcript else p.get("language") or ""),
                         duration_s=(transcript["duration_s"] if transcript else None),
                         target_level=effective_target,
                         payload_meta=_submission_payload_meta(kind, audio_name,
                                                               image_names,
                                                               p.get("copy_pdf_name")),
                         context=m._strip_persist_context(assignment_context)
                         if assignment else _strip_ctx(assignment_context),
                         eval_notes=m._strip_persist_eval_notes(eval_notes)
                         if assignment else _strip_en(eval_notes),
                         accommodations=p.get("accommodations") or None)

    fluency = assess.fluency_metrics(transcript) if transcript else None
    transcript_blob = ({"text": transcript["text"], "segments": transcript["segments"],
                        "duration_s": transcript["duration_s"],
                        "language": transcript["language"],
                        "words": transcript.get("words") or []}
                       if transcript else None)

    _set_phase(job_id, PHASE_PERSISTING, js)
    db.update_analysis(
        analysis_id,
        matrix_json=json.dumps(m._skeleton_matrix(rubric), ensure_ascii=False),
        fluency_json=json.dumps(fluency, ensure_ascii=False) if fluency else None,
        transcript_json=json.dumps(transcript_blob, ensure_ascii=False),
        status="teacher",
    )
    _finalize(job_id, js, "done",
              report=_report_payload(analysis_id, parsed=True, raw=""))


# --------------------------------------------------------------------- run-ai
async def _stage_and_run_runai(job_id: int, js: JobStream, payload: dict) -> None:
    m = _media()
    p = payload
    analysis_id = p["analysis_id"]
    mode = p.get("mode") or "blind"
    a = db.get_analysis(analysis_id)
    if not a:
        raise ValueError("analysis not found")
    sub = db.get_submission(a.get("submission_id") or 0)
    if not sub:
        raise ValueError("submission not found")
    rubric = db.get_rubric(a.get("rubric_id") or "")
    if not rubric:
        raise ValueError("rubric not found")

    _set_phase(job_id, PHASE_PREPARING, js)
    mats = await m._submission_materials(sub, a)
    kind = mats["kind"]
    transcript = mats["transcript"]
    fluency = assess.fluency_metrics(transcript) if transcript else None

    teacher_levels = None
    if mode == "aware":
        try:
            mm = json.loads(a["matrix_json"]) if a.get("matrix_json") else None
        except Exception:
            mm = None
        if isinstance(mm, dict) and isinstance(mm.get("rubric_mapping"), list):
            teacher_levels = {e.get("criterion"): e.get("suggested_level", "")
                              for e in mm["rubric_mapping"] if e.get("criterion")}

    ctx_lines = []
    if sub.get("student_name"):
        ctx_lines.append(f"Student: {sub['student_name']}")
    if sub.get("assignment_name"):
        ctx_lines.append(f"Linked assignment: {sub['assignment_name']}")
    wt = (mats["written_text"] or "").strip()
    if wt.startswith("(transcribed from"):
        wt = ""

    messages = assess.build_messages(
        kind=kind, rubric=rubric, student_context="\n".join(ctx_lines),
        written_text=(wt or None) if kind == "written" else None,
        image_data_urls=mats["image_data_urls"] if kind == "written" else None,
        oral_transcript=(assess.transcript_with_timestamps(transcript)
                         if transcript else None),
        oral_metadata=fluency,
        target_level=mats["target"],
        assignment_context=mats["assignment_context"],
        eval_notes=mats["eval_notes"],
        accommodations=mats["accommodations"],
        teacher_levels=teacher_levels,
        pre_annotations=mats.get("pre_annotations") or None,
        transcript_corrected=bool(mats.get("transcript_corrected")),
        ui_language=p.get("ui_language") or None,
    )

    _set_phase(job_id, PHASE_ANALYZING, js)
    if _cancelled(job_id):
        return _mark_cancelled(job_id, js)
    full, usage = await _run_llm_stream(job_id, js, messages)

    parsed = assess.parse_result(full)
    data = parsed["data"]
    warnings = assess.validate_matrix(data, rubric) if data else [parsed["error"]]
    attestation = compute_attestation(rubric, (data or {}).get("rubric_mapping", []))
    if attestation and attestation.get("unmapped"):
        warnings.append("Certains critères n'ont pas pu être notés sur la "
                        "échelle A1–C2 ; le score d'attestation est à valider.")
    if not parsed["ok"]:
        warnings.append("The AI reply could not be parsed into the expected "
                        "structure; the raw response is shown instead.")

    _set_phase(job_id, PHASE_PERSISTING, js)
    # LAST AI OPINION WINS: overwrite the previous AI matrix; the teacher's
    # matrix_json + overall_level are never touched.
    db.update_analysis(
        analysis_id,
        raw_markdown=full,
        ai_matrix_json=json.dumps(data, ensure_ascii=False) if data else None,
        ai_mode=mode,
        ai_at=db.now_iso(),
        status="done",
    )
    # Auto-OCR (re-run safe, idempotent): a written photo copy should have its
    # Annoter transcription ready after the AI pass too. `sub` here is the
    # SUBMISSION row (fetched above via a["submission_id"]) — pass that id.
    ensure_copy_ocr(a.get("submission_id"))
    _finalize(job_id, js, "done", report=_report_payload(analysis_id,
                parsed=parsed["ok"], raw=full, warnings=warnings,
                attestation=attestation))


# --------------------------------------------------------- reanalyze (retry)
async def _stage_and_run_reanalyze(job_id: int, js: JobStream, payload: dict) -> None:
    """Re-run the FULL grading LLM on an existing, STORED submission and
    replace the analysis's grade in place.

    This is the "Nouvelle analyse" action: the submission already holds the
    student's work (page photos / audio / pasted text) + the assignment
    context, so no re-upload is needed. Unlike run_ai (which only refreshes
    the AI opinion in ai_matrix_json), this rewrites matrix_json +
    overall_level + raw_markdown and — because a fresh grade is being
    produced — clears the previous teacher-validated state (validated_at,
    /20 note) and the prior AI snapshot so the analysis shows the new
    result cleanly. The job's analysis_id points at the analysis row to
    overwrite (no new submission/analysis row is created)."""
    m = _media()
    p = payload
    analysis_id = p["analysis_id"]
    a = db.get_analysis(analysis_id)
    if not a:
        raise ValueError("analysis not found")
    sub = db.get_submission(a.get("submission_id") or 0)
    if not sub:
        raise ValueError("submission not found")
    rubric = db.get_rubric(a.get("rubric_id") or "")
    if not rubric:
        raise ValueError("rubric not found")
    kind = sub.get("kind") or "written"

    _set_phase(job_id, PHASE_PREPARING, js)
    mats = await m._submission_materials(sub, a)
    transcript = mats["transcript"]
    fluency = assess.fluency_metrics(transcript) if transcript else None
    ctx_lines = []
    if sub.get("student_name"):
        ctx_lines.append(f"Student: {sub['student_name']}")
    if sub.get("assignment_name"):
        ctx_lines.append(f"Linked assignment: {sub['assignment_name']}")
    wt = (mats["written_text"] or "").strip()
    if wt.startswith("(transcribed from"):
        wt = ""
    # An oral re-analysis that lost its transcript (e.g. the first run
    # failed before persisting it) must re-transcribe from the stored audio.
    if kind == "oral" and not transcript:
        audio_name = ((sub.get("payload_meta") or {}).get("audio_name")
                      if isinstance(sub.get("payload_meta"), dict) else None)
        if not audio_name:
            raise ValueError("oral submission has no stored audio to re-transcribe")
        _set_phase(job_id, PHASE_TRANSCRIBING, js)
        lang = sub.get("language") or "en"
        transcript = await asyncio.to_thread(
            whisper.transcribe, str(config.UPLOAD_DIR / audio_name), lang)
        fluency = assess.fluency_metrics(transcript)

    messages = assess.build_messages(
        kind=kind, rubric=rubric, student_context="\n".join(ctx_lines),
        written_text=(wt or None) if kind == "written" else None,
        image_data_urls=mats["image_data_urls"] if kind == "written" else None,
        oral_transcript=(assess.transcript_with_timestamps(transcript)
                         if transcript else None),
        oral_metadata=fluency,
        target_level=mats["target"],
        assignment_context=mats["assignment_context"],
        eval_notes=mats["eval_notes"],
        accommodations=mats["accommodations"],
        pre_annotations=mats.get("pre_annotations") or None,
        transcript_corrected=bool(mats.get("transcript_corrected")),
        ui_language=p.get("ui_language") or None,
    )

    _set_phase(job_id, PHASE_ANALYZING, js)
    if _cancelled(job_id):
        return _mark_cancelled(job_id, js)
    full, usage = await _run_llm_stream(job_id, js, messages)

    parsed = assess.parse_result(full)
    data = parsed["data"]
    warnings = assess.validate_matrix(data, rubric) if data else [parsed["error"]]
    attestation = compute_attestation(rubric, (data or {}).get("rubric_mapping", []))
    if attestation and attestation.get("unmapped"):
        warnings.append("Certains critères n'ont pas pu être notés sur l'"
                        "échelle A1–C2 ; le score d'attestation est à valider.")
    if not parsed["ok"] and usage.get("truncated"):
        warnings.append("The model hit the token limit before finishing its "
                        "reply; the analysis may be incomplete. Try again.")

    _set_phase(job_id, PHASE_PERSISTING, js)
    # Replace the grade wholesale (mirror the canonical analyze persist), but
    # because a fresh analysis is being produced, also invalidate the previous
    # teacher-validated state (validated_at, /20 note) and the prior AI
    # snapshot so the report shows only the new result.
    db.update_analysis(
        analysis_id,
        raw_markdown=full,
        overall_level=(data or {}).get("overall_level"),
        matrix_json=json.dumps(data, ensure_ascii=False) if data else None,
        feedback=json.dumps((data or {}).get("student_feedback"), ensure_ascii=False)
        if data else None,
        fluency_json=json.dumps(fluency, ensure_ascii=False) if fluency else None,
        transcript_json=(json.dumps(
            {"text": transcript["text"], "segments": transcript["segments"],
             "duration_s": transcript["duration_s"],
             "language": transcript["language"],
             "words": transcript.get("words") or []}, ensure_ascii=False)
            if transcript else None),
        ai_matrix_json=json.dumps(data, ensure_ascii=False) if data else None,
        ai_mode="blind",
        ai_at=db.now_iso(),
        validated_at=db._CLEAR,  # type: ignore[assignment]
        note20_json=db._CLEAR,  # type: ignore[assignment]
        status="done",
        error=None,
    )
    ensure_copy_ocr(a.get("submission_id"))
    _finalize(job_id, js, "done", report=_report_payload(analysis_id,
                parsed=parsed["ok"], raw=full, warnings=warnings,
                attestation=attestation))


# ------------------------------------------------- stats-ai (class insight)
async def _stage_and_run_statsai(job_id: int, js: JobStream, payload: dict) -> None:
    """AI class insight for an assignment's Stats view: read the assignment
    (instruction + document + repères), the per-student evaluations and the
    per-class statistics, produce a JSON class analysis. The result is stored
    on the JOB row (jobs.result_json) — there is no analysis to write to."""
    p = payload
    assignment_id = p.get("assignment_id")
    assignment = db.get_assignment(assignment_id) if assignment_id else None
    if not assignment:
        raise ValueError("assignment not found")
    # The stats snapshot was captured at enqueue time — the analysis reads the
    # same data the teacher saw when clicking "Avis IA" (levels edited meanwhile
    # would otherwise desync input from output).
    stats = p.get("stats") or {}
    if not (stats.get("evaluations") or 0):
        raise ValueError("no evaluation with a filled level yet on this assignment")

    _set_phase(job_id, PHASE_PREPARING, js)
    messages = assess.build_class_insight_messages(
        assignment=assignment, stats=stats,
        ui_language=p.get("ui_language") or None)

    _set_phase(job_id, PHASE_ANALYZING, js)
    if _cancelled(job_id):
        return _mark_cancelled(job_id, js)
    full, usage = await _run_llm_stream(job_id, js, messages)

    parsed = llm_client.extract_json(full)
    warnings: list[str] = []
    if not isinstance(parsed, dict) or not parsed.get("class_level"):
        warnings.append("The AI reply could not be parsed into the expected "
                        "structure; the raw response is shown instead.")
    if usage.get("truncated"):
        warnings.append("The model hit the token limit before finishing its "
                        "reply; the analysis may be incomplete. Try again.")

    _set_phase(job_id, PHASE_PERSISTING, js)
    data = parsed if isinstance(parsed, dict) else None
    _finalize(job_id, js, "done", report={
        "assignment_id": assignment_id,
        "data": data,
        "raw": full,
        "warnings": warnings,
    })


# --------------------------------------------------------------------- LLM
async def _run_llm_stream(job_id: int, js: JobStream, messages: list) -> tuple[str, dict]:
    """Run the LLM in a thread, forwarding each token to the job stream.

    Returns (full_text, usage_dict). The ``truncated`` flag (finish_reason) is
    surfaced in the usage dict.
    """
    result: dict = {"full": [], "usage": {"truncated": False}}

    def _worker():
        buf = []
        try:
            for piece in llm_client.stream_chat(messages, temperature=0.1,
                                                max_tokens=10000,
                                                thinking_budget=4000,
                                                truncated=result["usage"]):
                if _cancelled(job_id):
                    break
                buf.append(piece)
                js.push("token", {"t": piece})
            result["full"] = buf
        except Exception as e:  # surfaced to the caller
            result["error"] = str(e)

    await asyncio.to_thread(_worker)
    full = "".join(result["full"])
    if result.get("error"):
        raise RuntimeError(result["error"])
    return full, result["usage"]


# --------------------------------------------------------------------- helpers
def _submission_payload_meta(kind: str, audio_name, image_names: list,
                             copy_pdf_name) -> dict | None:
    """The submission's stored payload_meta (media file names) at the end of
    a worker run. Written copies: page photos (page_paths) + the work PDF
    (copy_pdf_name, kept on disk so run_ai / reanalyze can re-read it);
    oral: the audio file. None when there is nothing to persist."""
    meta: dict = {}
    if kind == "oral" and audio_name:
        meta["audio_name"] = audio_name
    if kind != "oral":
        if image_names:
            meta["page_paths"] = image_names
            meta["page_count"] = len(image_names)
        if copy_pdf_name:
            meta["copy_pdf_name"] = copy_pdf_name
    return meta or None


def _payload_of(kind, written_text, image_data_urls, transcript, image_names):
    if kind == "oral" and transcript:
        return transcript["text"], "audio"
    if image_data_urls:
        return (written_text or
                f"(transcribed from {len(image_data_urls)} page photo(s))"), "image"
    return written_text, "text"


def _build_adhoc_context(p: dict) -> tuple[dict | None, dict | None]:
    """Rebuild the ad-hoc assignment context + eval notes from staged files.

    Priority mirrors main._build_assignment_context:
      instruction: text/PDF > photos
      document:    text > audio > PDF > photos
    Runs in a worker thread (whisper + pymupdf are blocking).
    """
    instruction = (p.get("instruction") or "").strip()
    instr_pdf_name = p.get("instruction_pdf_name")
    instr_photo_names = p.get("instruction_photo_names") or []
    if instr_pdf_name:
        pp = config.UPLOAD_DIR / instr_pdf_name
        if pp.is_file():
            text, _u, _n = _extract_pdf_file(pp, "instruction",
                                             f"pdf-{instr_pdf_name[4:36]}")
            if text:
                instruction = (instruction + "\n\n" + text).strip()

    instr_photo_urls = _data_urls_from_names(instr_photo_names) if instr_photo_names else []
    if not instruction and instr_photo_urls:
        instruction = None  # photos carry the instruction

    doc_text = (p.get("doc_text") or "").strip()
    doc_audio_name = p.get("doc_audio_name")
    doc_pdf_name = p.get("doc_pdf_name")
    doc_photo_names = p.get("doc_photo_names") or []
    doc_pdf_urls: list = []
    if doc_audio_name:
        ap = config.UPLOAD_DIR / doc_audio_name
        if ap.is_file():
            t = whisper.transcribe(str(ap), "en")
            doc_text = (t or {}).get("text", "") or ""
    elif doc_pdf_name:
        pp = config.UPLOAD_DIR / doc_pdf_name
        if pp.is_file():
            text, doc_pdf_urls, _n = _extract_pdf_file(pp, "source document",
                                                       f"pdf-{doc_pdf_name[4:36]}")
            doc_text = text
    elif doc_photo_names:
        doc_text = ""  # photos carry the document

    doc_photo_urls = _data_urls_from_names(doc_photo_names) if doc_photo_names else []

    if not (instruction or instr_photo_urls or doc_text or doc_pdf_urls
            or doc_photo_urls):
        ctx = None
    else:
        ctx = {
            "instruction": instruction,
            "document_text": doc_text,
            "document_source": ("audio" if doc_audio_name
                                else ("pdf" if (doc_pdf_name or doc_pdf_urls)
                                      else ("photos" if doc_photo_urls
                                            else ("text" if doc_text else None)))),
            "document_audio_name": doc_audio_name or None,
            "document_pdf_name": doc_pdf_name or None,
            "instruction_pdf_name": instr_pdf_name or None,
            "document_images": doc_pdf_urls,
            "instruction_photo_urls": instr_photo_urls,
            "document_photo_urls": doc_photo_urls,
            "instruction_photo_names": instr_photo_names,
            "document_photo_names": doc_photo_names,
        }

    # eval notes (text + optional PDF + photos of the instructions)
    en_text = (p.get("eval_notes") or "").strip()
    en_pdf_name = p.get("eval_notes_pdf_name")
    en_pdf_pages: list = []
    if en_pdf_name:
        pp = config.UPLOAD_DIR / en_pdf_name
        if pp.is_file():
            t, en_pdf_pages, _n = _extract_pdf_file(pp, "evaluation instructions",
                                                    f"pdf-{en_pdf_name[4:36]}")
            if t:
                en_text = (en_text + "\n\n" + t).strip()
    en_photo_names = p.get("eval_notes_photo_names") or []
    en_photo_urls = _data_urls_from_names(en_photo_names) if en_photo_names else []
    if not en_text and not en_pdf_pages and not en_photo_urls:
        en = None
    else:
        en = {"text": en_text or None, "pdf_name": en_pdf_name or None,
              "pdf_pages": en_pdf_pages, "pdf_page_count": len(en_pdf_pages),
              "photo_names": en_photo_names, "photo_urls": en_photo_urls}
    return ctx, en


def _strip_ctx(context: dict | None) -> dict | None:
    if not context:
        return None
    return {k: v for k, v in context.items()
            if k != "document_images" and not k.endswith("_urls")}


def _strip_en(eval_notes: dict | None) -> dict | None:
    if not eval_notes:
        return None
    return {k: v for k, v in eval_notes.items()
            if k not in ("pdf_pages", "photo_urls")}


def _mark_cancelled(job_id: int, js: JobStream) -> None:
    j = db.job_get(job_id)
    if j and j.get("analysis_id"):
        _fail_analysis(j["analysis_id"], "cancelled")
    _finalize(job_id, js, "cancelled")


def _fail_analysis(analysis_id: int, err: str) -> None:
    try:
        db.update_analysis(analysis_id, status="error", error=err, raw_markdown="")
    except Exception:
        pass


def _finalize(job_id: int, js: JobStream, status: str,
              report: dict | None = None, error: str | None = None) -> None:
    j = db.job_get(job_id) or {}
    started = j.get("started_at")
    elapsed = None
    if started:
        try:
            from datetime import datetime
            s = datetime.fromisoformat(started)
            elapsed = round((datetime.now(s.tzinfo) - s).total_seconds(), 1)
        except Exception:
            elapsed = None
    if status == "done":
        db.job_update(job_id, status="done", elapsed_s=elapsed,
                      result=report if isinstance(report, dict) else None,
                      finished=True)
        if report is not None:
            js.push("result", report)
        js.push("done", {"job_id": job_id, "status": "done", "elapsed_s": elapsed})
    elif status == "cancelled":
        db.job_update(job_id, status="cancelled", elapsed_s=elapsed, finished=True)
        js.push("cancelled", {"job_id": job_id, "elapsed_s": elapsed})
    else:  # error
        db.job_update(job_id, status="error", error=error, elapsed_s=elapsed,
                      finished=True)
        js.push("error", {"error": error, "elapsed_s": elapsed})
    if report is not None and status == "done":
        pass  # result already pushed by the caller
    js.finish()


# --------------------------------------------------------------------- dispatch
async def _run_roster_import(job_id: int, js: JobStream, payload: dict) -> None:
    """Class-roster photo import (2026-11-08): ONE LLM vision call over ALL
    the roster photos -> strict JSON {class_name, school_name, students,
    warnings}. The draft is persisted on the job row (jobs.result_json);
    NOTHING is created until the teacher commits it
    (POST /api/students/import-photos/{id}/commit). No submission/analysis
    rows involved — the job row alone carries the payload, like stats_ai.

    tibo note (2026-11-08): the LLM is slow — the chat call gets an extended
    timeout (1200 s, 3 retries on transient errors) instead of the 600 s
    default, so a 30–60 s reasoning+generation over several photos cannot
    time out mid-stream."""
    p = payload or {}
    names = p.get("photo_names") or []
    if not names:
        raise ValueError("no roster photos in the job payload")

    _set_phase(job_id, PHASE_PREPARING, js)
    if _cancelled(job_id):
        return _mark_cancelled(job_id, js)
    image_data_urls = await asyncio.to_thread(_data_urls_from_names, names)

    _set_phase(job_id, PHASE_ANALYZING, js)
    if _cancelled(job_id):
        return _mark_cancelled(job_id, js)
    messages = assess.build_roster_import_messages(
        image_data_urls=image_data_urls,
        ui_language=p.get("ui_language") or None)
    resp = await asyncio.to_thread(
        llm_client.chat, messages, temperature=0.0,
        max_tokens=4000, thinking_budget=2000, timeout=1200)
    full = resp.get("content") or ""
    truncated = bool(resp.get("truncated"))

    parsed = llm_client.extract_json(full)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("students"), list):
        raise ValueError("the model reply is not a valid roster JSON "
                         "(students list missing)")

    warnings: list[str] = []
    students: list[dict] = []
    for s in parsed.get("students") or []:
        if not isinstance(s, dict):
            continue
        first = str(s.get("first_name") or s.get("prenom") or "").strip()
        last = str(s.get("last_name") or s.get("nom") or "").strip()
        if not first and not last:
            whole = str(s.get("name") or s.get("full_name") or "").strip()
            parts = whole.split()
            first = whole if len(parts) <= 1 else " ".join(parts[:-1])
            last = parts[-1] if len(parts) > 1 else ""
        if not (first or last):
            warnings.append("Une ligne de la liste n'a pas de nom lisible.")
            continue
        students.append({"first_name": first, "last_name": last})
    draft = {
        "school_name": (str(parsed.get("school_name") or "").strip() or None),
        "class_name": (str(parsed.get("class_name") or "").strip() or None),
        "class_code_hint": (p.get("class_code_hint") or "").strip() or None,
        "students": students,
        "warnings": [str(w) for w in (parsed.get("warnings") or [])
                     if str(w).strip()] + warnings,
    }
    if not students:
        warnings.append("Aucun élève n'a pu être extrait — vérifiez la "
                        "lisibilité des photos.")
    if truncated:
        warnings.append("Le modèle a atteint sa limite de tokens avant de "
                        "terminer : la liste peut être incomplète.")

    _set_phase(job_id, PHASE_PERSISTING, js)
    _finalize(job_id, js, "done", report={
        "roster": draft, "photo_names": names,
        "raw": full, "warnings": warnings})


async def _run_ocr(job_id: int, js: JobStream, payload: dict) -> None:
    """LLM-direct OCR job for a written submission's page photos (the LLM
    vision engine transcribes each page directly, with per-line bounding
    boxes), persisted on submissions.ocr_json. No analysis row involved
    (the job row carries only the submission)."""
    from . import ocr
    sub_id = db.job_get(job_id).get("submission_id")
    sub = db.get_submission(sub_id)
    if not sub:
        raise ValueError("submission not found")
    if sub.get("kind") != "written":
        raise ValueError("OCR is only available for written submissions")
    meta = sub.get("payload_meta") or {}
    image_names = list(meta.get("page_paths") or [])
    if not image_names:
        raise ValueError("this submission has no page photos to OCR")
    _set_phase(job_id, PHASE_OCRING, js)
    result = await asyncio.to_thread(
        ocr.ocr_submission, image_names, config.UPLOAD_DIR,
        language=sub.get("language"),
        progress=lambda ph: js.push("phase", {"phase": ph}),
        check_cancel=lambda: _cancelled(job_id))
    if _cancelled(job_id):
        return _mark_cancelled(job_id, js)
    db.set_submission_ocr(sub_id, result)
    _finalize(job_id, js, "done",
              report={"submission_id": sub_id, "ocr": result})


_RUNNERS = {
    "analyze": _stage_and_run_analyze,
    "evaluate": _stage_and_run_evaluate,
    "run_ai": _stage_and_run_runai,
    "reanalyze": _stage_and_run_reanalyze,
    "ocr": _run_ocr,
    "stats_ai": _stage_and_run_statsai,
    "roster_import": _run_roster_import,
}


async def run_job(job: dict) -> None:
    job_id = job["id"]
    # Multi-user (2026-10-13): run this job's db calls in the context of its
    # OWN user. The worker scheduler has no owner (system context); if we
    # didn't set owner_var here, db._scoped() would return no WHERE clause
    # and a job could read/write ANOTHER teacher's rows (e.g. job_get in the
    # cancel check, db.update_analysis in the finalize paths). run_job runs
    # as a fresh asyncio task (its own contextvars copy), so this is
    # task-local and needs no reset.
    owner = job.get("owner_id")
    if owner is not None:
        auth.owner_var.set(owner)
    js = _new_stream(job_id)
    kind = job.get("kind")
    payload = db.job_get(job_id).get("payload") or {}
    js.push("meta", {"job_id": job_id, "kind": kind,
                     "status": "running", "phase": None,
                     "created_at": job.get("created_at"),
                     "started_at": job.get("started_at"),
                     "finished_at": None, "elapsed_s": None,
                     "submission_id": job.get("submission_id"),
                     "analysis_id": job.get("analysis_id")})
    try:
        runner = _RUNNERS.get(kind)
        if not runner:
            raise ValueError(f"unknown job kind {kind!r}")
        await runner(job_id, js, payload)
    except Exception as e:
        j = db.job_get(job_id) or {}
        if j.get("analysis_id") and not _cancelled(job_id):
            _fail_analysis(j["analysis_id"], str(e))
        _finalize(job_id, js, "error", error=str(e))


# --------------------------------------------------------------------- workers
_SCHED: asyncio.Task | None = None
_SHUTDOWN: asyncio.Event | None = None


async def _scheduler() -> None:
    global _SHUTDOWN
    _SHUTDOWN = asyncio.Event()
    inflight: set[asyncio.Task] = set()
    while not _SHUTDOWN.is_set():
        try:
            cap = max_workers()
            # reap finished tasks so we count only live ones
            inflight = {t for t in inflight if not t.done()}
            while len(inflight) < cap:
                job = await asyncio.to_thread(db.job_claim_next)
                if not job:
                    break
                t = asyncio.create_task(run_job(job))
                inflight.add(t)
            _gc_streams()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        try:
            await asyncio.wait_for(_SHUTDOWN.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass
    # on shutdown, cancel any in-flight tasks
    for t in list(inflight):
        t.cancel()
    if inflight:
        await asyncio.gather(*inflight, return_exceptions=True)


def recover_orphans() -> int:
    """Re-queue any job left 'running' by a previous (crashed) process."""
    with db._LOCK:
        c = db._conn()
        cur = c.execute("UPDATE jobs SET status='queued', started_at=NULL "
                        "WHERE status='running'")
        c.commit()
        return cur.rowcount


def start_workers() -> None:
    """Start the background scheduler (idempotent)."""
    global _SCHED
    loop = asyncio.get_running_loop()
    set_loop(loop)
    recover_orphans()
    if _SCHED is None or _SCHED.done():
        _SCHED = asyncio.create_task(_scheduler())
        import logging
        logging.getLogger("elt.jobs").info(
            "job scheduler started (max_workers=%s)", max_workers())


def stop_workers() -> None:
    global _SCHED
    ev = _SHUTDOWN
    if ev and not ev.is_set():
        ev.set()
    if _SCHED:
        _SCHED.cancel()
        _SCHED = None
