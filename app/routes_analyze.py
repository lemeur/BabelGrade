"""The long analysis endpoints: /api/analyze, /api/analyze/stream,
/api/evaluate, /api/analyses/{id}/run-ai.

Extracted from main.py (2026-10-16 split). These are the only routes that
enqueue background jobs; the shared job plumbing (_stage_submission_payloads,
_enqueue_and_handle, _job_events) lives here too, because only these
endpoints use it.
"""
import asyncio
import json

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from . import assess, config, db, jobs
from .config import ALLOWED_AUDIO, MAX_AUDIO_BYTES
from .media import _default_title, _ext, _read_image_uploads, _resolve_assignment_materials
import uuid
from typing import List

router = APIRouter()


async def _stage_submission_payloads(
        kind: str, written_text: str, rubric_id: str,
        image, images, audio,
        instruction, instruction_pdf, instruction_photos,
        doc_text, doc_audio, doc_pdf, doc_photos,
        eval_notes, eval_notes_pdf, eval_notes_photos,
        title: str, student_id: int, assignment_id: int,
        target_level: str, language: str, accommodations: str,
        analyze_kind: str, ui_lang: str = "") -> dict:
    """Validate + persist ALL uploads and the placeholder submission/analysis
    rows; return the job payload. Long work (whisper/pymupdf/LLM) is
    deferred to the job worker — only file I/O + validation happens here.

    Raises HTTPException(4xx) on bad input BEFORE anything is persisted,
    and 409 when an analysis for the same submission is already queued.
    """
    kind = kind or "written"
    if kind not in ("written", "oral"):
        raise HTTPException(422, "kind must be written|oral")
    target = (target_level or "").strip().upper()
    if target and target not in ("A1", "A2", "B1", "B2", "C1", "C2"):
        raise HTTPException(422, "target_level must be A1-A2-B1-B2-C1-C2")
    rubric = db.get_rubric(rubric_id) if rubric_id else None
    if not rubric:
        raise HTTPException(422, "valid rubric_id required")
    if not db.rubric_matches_mode(rubric, kind):
        raise HTTPException(422, f"rubric '{rubric['name']}' does not apply to a {kind} submission")

    mats = await _resolve_assignment_materials(
        assignment_id, instruction, instruction_pdf, instruction_photos,
        doc_text, doc_audio, doc_pdf, doc_photos, eval_notes,
        eval_notes_pdf, eval_notes_photos)

    image_data_urls: list = []
    image_paths: list = []
    if kind == "oral":
        if not audio or not audio.filename:
            raise HTTPException(422, f"oral {analyze_kind} requires an audio upload")
        ext = _ext(audio.filename)
        if ext not in ALLOWED_AUDIO:
            raise HTTPException(422, f"unsupported audio type '.{ext}'")
        data = await audio.read()
        if len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(422, "audio file too large")
        audio_name = f"aud-{uuid.uuid4().hex}.{ext}"
        (config.UPLOAD_DIR / audio_name).write_bytes(data)
    else:
        audio_name = None
        uploads = list(images or [])
        if image and image.filename:
            uploads.append(image)
        image_data_urls, image_paths = await _read_image_uploads(uploads)
        if not written_text.strip() and not image_data_urls:
            raise HTTPException(422, "provide written text or page photo(s)")

    student_name = db.get_student(student_id)["name"] if student_id else ""
    # (2026-10-14) media ownership: the uploaded files (audio / page
    # photos) are recorded on the submission IMMEDIATELY — not only when
    # the job finishes — so /api/files ownership enforcement is airtight
    # even for queued/in-flight submissions. The worker re-writes the same
    # meta at completion (no change to stored values).
    initial_meta: dict = {}
    if audio_name:
        initial_meta["audio_name"] = audio_name
    if image_paths:
        initial_meta["page_paths"] = image_paths
        initial_meta["page_count"] = len(image_paths)
    sub_id = db.create_submission(
        kind=kind, source_type="pending",
        payload_path="",
        title=title or _default_title(kind, student_name,
                                      mats["assignment"]["name"] if assignment_id else ""),
        student_id=student_id or None,
        assignment_id=assignment_id or None,
        target_level=(target or mats["inherited_target"]) or None,
        context=mats["context_persisted"],
        eval_notes=mats["eval_notes_persisted"],
        accommodations=(accommodations or "").strip() or None,
        payload_meta=initial_meta or None,
    )
    analysis_id = db.create_analysis(sub_id, rubric["id"], status="processing")
    db.update_analysis(analysis_id, status="queued")
    # Ad-hoc material file names must ride in the payload: the job worker
    # rebuilds the ad-hoc context from these names (assignment-linked
    # material is re-read from the assignment row, so it needs none of this).
    # mats context/eval are the stripped dicts (no data-URLs) — the worker
    # re-attaches page images from the names. (Fix: ad-hoc photos/PDF were
    # silently dropped because these keys were never carried to the worker.)
    ctxp = mats.get("context_persisted") or {}
    enp = mats.get("eval_notes_persisted") or {}
    payload = {
        "kind": kind,
        "rubric_id": rubric["id"],
        "student_id": student_id or 0,
        "assignment_id": assignment_id or 0,
        "title": title or "",
        "language": language or "en",
        "target_level": target or "",
        "written_text": written_text or "",
        "image_names": image_paths,
        "audio_name": audio_name,
        "accommodations": (accommodations or "").strip(),
        "ui_language": assess._ui_language(ui_lang),
        # ad-hoc material names (ignored when assignment_id is set)
        "instruction": ctxp.get("instruction"),
        "doc_text": ctxp.get("document_text"),
        "instruction_pdf_name": ctxp.get("instruction_pdf_name"),
        "instruction_photo_names": ctxp.get("instruction_photo_names") or [],
        "doc_audio_name": ctxp.get("document_audio_name"),
        "doc_pdf_name": ctxp.get("document_pdf_name"),
        "doc_pdf_page_names": ctxp.get("document_pdf_page_names") or [],
        "doc_photo_names": ctxp.get("document_photo_names") or [],
        "eval_notes": enp.get("text"),
        "eval_notes_pdf_name": enp.get("pdf_name"),
        "eval_notes_photo_names": enp.get("photo_names") or [],
    }
    return {"payload": payload, "submission_id": sub_id,
            "analysis_id": analysis_id}

def _job_handle(job_id: int, job: dict, analysis: dict) -> dict:
    return {"job_id": job_id,
            "job_status": job.get("status"),
            "job_kind": job.get("kind"),
            "analysis_id": job.get("analysis_id"),
            "submission_id": job.get("submission_id"),
            "created_at": job.get("created_at"),
            "enqueued": True,
            "follow_url": f"/api/jobs/{job_id}/events",
            "analysis": db.enrich_analysis(analysis) if analysis else None}

async def _enqueue_and_handle(kind: str, payload: dict,
                              submission_id: int, analysis_id: int,
                              analysis: dict | None = None) -> dict:
    """Persist the job row, then return its handle (the worker picks it up
    within ~0.5 s)."""
    job_id = db.create_job(kind, payload,
                           submission_id=submission_id,
                           analysis_id=analysis_id)
    job = db.job_get(job_id)
    return _job_handle(job_id, job, analysis)

async def _job_events(job_id: int):
    """SSE stream of a job's live progress: meta → phase* → token* →
    result → done | cancelled | error.

    Late subscribers get the full log replayed; when the in-memory log has
    been GC'd (finished > 15 min ago), the terminal state is rebuilt from
    the DB. Terminal events close the stream."""
    j = db.job_get(job_id)
    if not j:
        raise HTTPException(404, "job not found")

    def ev(event, data_obj):
        return f"event: {event}\ndata: {json.dumps(data_obj, ensure_ascii=False)}\n\n"

    async def gen():
        # NOTE: must not REASSIGN `j` inside this generator — Python would
        # then treat `j` as a local and the first read would raise
        # UnboundLocalError (killing the stream before the first byte).
        job_row = j
        stream = jobs.get_stream(job_id)
        if stream is None and job_row["status"] not in ("done", "error", "cancelled"):
            # RACE: the UI opens this stream immediately after the POST
            # returns, but the scheduler claims the job (and creates the
            # in-memory stream in run_job) up to ~0.5 s later. A fresh
            # subscriber must not get a dead-end "job stream unavailable"
            # error — wait for the claim instead. If the job reaches a
            # terminal state while waiting, fall through to the DB
            # rebuild below (the 15-minute in-memory log replay also
            # covers it).
            for _ in range(60):  # up to ~15 s
                await asyncio.sleep(0.25)
                j2 = db.job_get(job_id)
                if j2 is None:
                    raise HTTPException(404, "job not found")
                if j2["status"] in ("done", "error", "cancelled"):
                    job_row = j2
                    break
                stream = jobs.get_stream(job_id)
                if stream is not None:
                    break
        if stream is not None:
            # The claim (started_at written) may have happened mid-wait —
            # re-read so the prelude meta below carries real times.
            job_row = db.job_get(job_id) or job_row
        # Real wall-clock times (DB is authoritative — the meta event
        # pushed by run_job at claim time only knows "running"): the UI's
        # follow card uses these to place the clock on the job's ACTUAL
        # start instead of the click time.
        created = job_row.get("created_at")
        started = job_row.get("started_at")
        finished = job_row.get("finished_at")
        elapsed = job_row.get("elapsed_s")
        if stream is not None:
            # DB prelude: the job's real timeline (created/started/
            # finished/elapsed). Replayed AFTER the in-memory log, so it
            # also covers a job that already reached a terminal state.
            yield ev("meta", {"job_id": job_id, "kind": job_row["kind"],
                              "status": job_row["status"], "phase": None,
                              "created_at": created, "started_at": started,
                              "finished_at": finished,
                              "elapsed_s": elapsed,
                              "submission_id": job_row.get("submission_id"),
                              "analysis_id": job_row.get("analysis_id")})
            q = stream.subscribe()
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(q.get(), timeout=60)
                    except asyncio.TimeoutError:
                        # heartbeat so the connection survives proxies
                        yield ev("ping", {})
                        continue
                    if item is None:
                        break
                    event, data = item
                    yield ev(event, data)
            finally:
                stream.unsubscribe(q)
        else:
            # no live stream: rebuild from the DB. job_row carries the
            # FRESH status (may have been refreshed by the wait loop above).
            yield ev("meta", {"job_id": job_id, "kind": job_row["kind"],
                              "status": job_row["status"], "phase": None,
                              "created_at": created, "started_at": started,
                              "finished_at": finished,
                              "elapsed_s": elapsed,
                              "submission_id": job_row.get("submission_id"),
                              "analysis_id": job_row.get("analysis_id")})
            if job_row["status"] == "done" and job_row.get("analysis_id"):
                a = db.get_analysis(job_row["analysis_id"])
                if a:
                    try:
                        matrix = json.loads(a["matrix_json"]) if a.get("matrix_json") else None
                    except Exception:
                        matrix = None
                    yield ev("result", jobs._report_payload(job_row["analysis_id"],
                            parsed=bool(matrix), raw=a.get("raw_markdown") or ""))
            if job_row["status"] in ("done", "error", "cancelled"):
                yield ev(job_row["status"], {"job_id": job_id,
                                       "error": job_row.get("error"),
                                       "elapsed_s": elapsed})
            else:  # queued / running but its stream was GC'd (shouldn't happen)
                yield ev("error", {"error": "job stream unavailable"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})

# ---------------------------------------------------------------- analyze
@router.post("/api/analyze")
async def analyze(written_text: str = Form(""),
                  kind: str = Form("written"),
                  rubric_id: str = Form(""),
                  student_id: int = Form(0),
                  assignment_id: int = Form(0),
                  title: str = Form(""),
                  language: str = Form("en"),
                  target_level: str = Form(""),
                  instruction: str = Form(""),
                  doc_text: str = Form(""),
                  image: UploadFile | None = None,
                  images: List[UploadFile] = Form([]),
                  audio: UploadFile | None = None,
                  doc_audio: UploadFile | None = None,
                  instruction_pdf: UploadFile | None = None,
                  doc_pdf: UploadFile | None = None,
                  instruction_photos: List[UploadFile] = Form([]),
                  doc_photos: List[UploadFile] = Form([]),
                  eval_notes: str = Form(""),
                  eval_notes_pdf: UploadFile | None = None,
                  eval_notes_photos: List[UploadFile] = Form([]),
                  accommodations: str = Form(""),
                  ui_language: str = Form("")):
    """Enqueue the analysis as a background job and return its handle.

    Follow the job at `follow_url` (SSE: meta → phase* → token* → result →
    done|error|cancelled). Legacy blocking endpoint removed: the async
    queue is now the only analyze path."""
    staged = await _stage_submission_payloads(
        kind, written_text, rubric_id, image, images, audio,
        instruction, instruction_pdf, instruction_photos,
        doc_text, doc_audio, doc_pdf, doc_photos,
        eval_notes, eval_notes_pdf, eval_notes_photos,
        title, student_id, assignment_id, target_level, language,
        accommodations, "analysis", ui_language)
    sub = db.get_submission(staged["submission_id"])
    if db.job_active_for(staged["analysis_id"], ("analyze",)):
        db.delete_submission(staged["submission_id"])
        raise HTTPException(409, "an analysis for this submission is already in the queue")
    return await _enqueue_and_handle("analyze", staged["payload"],
                                     staged["submission_id"],
                                     staged["analysis_id"], sub)

# ------------------------------------------------------------- stream analyze
@router.post("/api/analyze/stream")
async def analyze_stream(written_text: str = Form(""),
                         kind: str = Form("written"),
                         rubric_id: str = Form(""),
                         student_id: int = Form(0),
                         assignment_id: int = Form(0),
                         title: str = Form(""),
                         language: str = Form("en"),
                         target_level: str = Form(""),
                         instruction: str = Form(""),
                         doc_text: str = Form(""),
                         image: UploadFile | None = None,
                         images: List[UploadFile] = Form([]),
                         audio: UploadFile | None = None,
                         doc_audio: UploadFile | None = None,
                         instruction_pdf: UploadFile | None = None,
                         doc_pdf: UploadFile | None = None,
                         instruction_photos: List[UploadFile] = Form([]),
                         doc_photos: List[UploadFile] = Form([]),
                         eval_notes: str = Form(""),
                         eval_notes_pdf: UploadFile | None = None,
                         eval_notes_photos: List[UploadFile] = Form([]),
                         accommodations: str = Form(""),
                         ui_language: str = Form("")):
    """SSE wrapper around the async analyze job (legacy URL kept for
    compatibility): enqueues the job, then streams its live events."""
    staged = await _stage_submission_payloads(
        kind, written_text, rubric_id, image, images, audio,
        instruction, instruction_pdf, instruction_photos,
        doc_text, doc_audio, doc_pdf, doc_photos,
        eval_notes, eval_notes_pdf, eval_notes_photos,
        title, student_id, assignment_id, target_level, language,
        accommodations, "analysis", ui_language)
    sub = db.get_submission(staged["submission_id"])
    if db.job_active_for(staged["analysis_id"], ("analyze",)):
        db.delete_submission(staged["submission_id"])
        raise HTTPException(409, "an analysis for this submission is already in the queue")
    handle = await _enqueue_and_handle("analyze", staged["payload"],
                                       staged["submission_id"],
                                       staged["analysis_id"], sub)
    return await _job_events(handle["job_id"])

# --------------------------------------------------- evaluate first (no AI)
@router.post("/api/evaluate")
async def evaluate(written_text: str = Form(""),
                   kind: str = Form("written"),
                   rubric_id: str = Form(""),
                   student_id: int = Form(0),
                   assignment_id: int = Form(0),
                   title: str = Form(""),
                   language: str = Form("en"),
                   target_level: str = Form(""),
                   instruction: str = Form(""),
                   doc_text: str = Form(""),
                   image: UploadFile | None = None,
                   images: List[UploadFile] = Form([]),
                   audio: UploadFile | None = None,
                   doc_audio: UploadFile | None = None,
                   instruction_pdf: UploadFile | None = None,
                   doc_pdf: UploadFile | None = None,
                   instruction_photos: List[UploadFile] = Form([]),
                   doc_photos: List[UploadFile] = Form([]),
                   eval_notes: str = Form(""),
                   eval_notes_pdf: UploadFile | None = None,
                   eval_notes_photos: List[UploadFile] = Form([]),
                   accommodations: str = Form(""),
                   ui_language: str = Form("")):
    """Enqueue the "evaluate first" job: stage the submission (+ transcribe
    oral audio in the worker), then create the empty skeleton matrix. No LLM.
    Returns the job handle; follow it at `follow_url`."""
    staged = await _stage_submission_payloads(
        kind, written_text, rubric_id, image, images, audio,
        instruction, instruction_pdf, instruction_photos,
        doc_text, doc_audio, doc_pdf, doc_photos,
        eval_notes, eval_notes_pdf, eval_notes_photos,
        title, student_id, assignment_id, target_level, language,
        accommodations, "evaluation", ui_language)
    sub = db.get_submission(staged["submission_id"])
    if db.job_active_for(staged["analysis_id"], ("evaluate",)):
        db.delete_submission(staged["submission_id"])
        raise HTTPException(409, "an evaluation for this submission is already in the queue")
    return await _enqueue_and_handle("evaluate", staged["payload"],
                                     staged["submission_id"],
                                     staged["analysis_id"], sub)

# ------------------------------------------------------- AI after (SSE)
@router.post("/api/analyses/{analysis_id}/run-ai")
async def run_ai(analysis_id: int, body: dict = {}):
    """Run (or re-run) the AI analysis on an EXISTING evaluation — now a
    queued background job.

    body: {"mode": "blind" | "aware", "ui_language": "fr" | ...}
    Blind = the AI grades independently; aware = the AI receives the
    teacher's current per-criterion levels and must confirm or refute each.
    ui_language = the teacher's active UI language; the AI writes its
    prose fields (executive summary, justifications, feedback) in it —
    verbatim quotes from the student's English work stay in English.
    The AI result is stored in ai_matrix_json — re-running OVERWRITES the
    previous AI opinion. The teacher's levels (matrix_json) are never
    touched. Returns the job handle; follow it at `follow_url`."""
    mode = str((body or {}).get("mode") or "blind").strip().lower()
    if mode not in ("blind", "aware"):
        raise HTTPException(422, "mode must be blind|aware")
    ui_language = assess._ui_language(
        str((body or {}).get("ui_language") or ""))
    a = db.get_analysis(analysis_id)
    if not a:
        raise HTTPException(404, "analysis not found")
    if db.job_active_for(analysis_id, ("run_ai",)):
        raise HTTPException(409, "an AI run for this analysis is already in the queue")
    handle = await _enqueue_and_handle("run_ai", {"analysis_id": analysis_id,
                                                  "mode": mode,
                                                  "ui_language": ui_language},
                                       a.get("submission_id"), analysis_id,
                                       a)
    return handle


@router.post("/api/analyses/{analysis_id}/reanalyze")
async def reanalyze(analysis_id: int, body: dict = {}):
    """Re-run the FULL grading LLM on this analysis's stored submission and
    replace its grade in place — the "Nouvelle analyse" retry.

    Unlike /run-ai (which only refreshes the AI opinion in ai_matrix_json),
    this rewrites matrix_json + overall_level + raw_markdown and clears the
    previous teacher validation / 20-point note / AI snapshot, so a failed or
    unstructured analysis can be retried without re-uploading the work.
    The submission already holds the student's materials + assignment
    context. The job's analysis_id is this row — no new submission/analysis
    is created. Returns the job handle; follow it at `follow_url`.
    """
    a = db.get_analysis(analysis_id)
    if not a:
        raise HTTPException(404, "analysis not found")
    sub = db.get_submission(a.get("submission_id") or 0)
    if not sub:
        raise HTTPException(404, "submission not found")
    if db.job_active_for(analysis_id, ("reanalyze",)):
        raise HTTPException(409, "a re-analysis for this analysis is already in the queue")
    ui_language = assess._ui_language(str((body or {}).get("ui_language") or ""))
    handle = await _enqueue_and_handle(
        "reanalyze", {"analysis_id": analysis_id, "ui_language": ui_language},
        sub["id"], analysis_id, a)
    return handle

