"""ELT Assessor - FastAPI application.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8090
"""
import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from typing import List

from fastapi import FastAPI, HTTPException, UploadFile, Form, Query, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import assess, auth, db, jobs, llm_client, whisper
from .rubrics import (PRESETS, compute_attestation, note_bands,
                      NOTE_THRESHOLDS, NOTE_VISE)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR.parent / "static"
UPLOAD_DIR = BASE_DIR.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_AUDIO_BYTES = 100 * 1024 * 1024
_SET_NULL = object()  # sentinel: force a column to NULL in teacher-update SQL
ALLOWED_IMAGE = {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff", "heic"}
ALLOWED_AUDIO = {"wav", "mp3", "m4a", "aac", "ogg", "opus", "flac", "mp4"}


def _ext(name: str) -> str:
    return (name.rsplit(".", 1)[-1] if "." in name else "").lower()


def _b64_from_bytes(b: bytes, mime: str) -> str:
    import base64
    return f"data:{mime};base64,{base64.b64encode(b).decode()}"


def _mime_for(ext: str) -> str:
    return {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp",
        "tiff": "image/tiff", "heic": "image/heic",
        "mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4",
        "aac": "audio/aac", "ogg": "audio/ogg", "opus": "audio/opus",
        "flac": "audio/flac", "mp4": "video/mp4",
    }.get(ext, "application/octet-stream")


def _default_title(kind: str, student_name: str = "", assignment_name: str = "",
                   when_iso: str | None = None) -> str:
    """Point 8: smart default title for untitled submissions.

    The old fallback was the useless constant "written submission" /
    "oral submission" (22 identical rows topped the history list).
    Now: "<Student> · <Assignment> · 04/10/2026" with empty segments dropped,
    e.g. "Marie D. · Bac blanc 2026 · 04/10/2026".
    """
    parts = [p.strip() for p in (student_name, assignment_name) if p and p.strip()]
    d = (when_iso or datetime.now(timezone.utc).isoformat()).split("T")[0]
    parts.append(f"{d[8:10]}/{d[5:7]}/{d[0:4]}")
    return " · ".join(parts)


def _migrate_default_titles() -> int:
    """Point 8: backfill legacy placeholder titles ("written submission",
    "oral submission", "(transcribed from …)", "(from …)") with the smart
    Student · Assignment · date fallback. Runs at startup; only touches rows
    still carrying a legacy placeholder. Returns the number updated.
    """
    with db._LOCK:
        c = db._conn()
        legacy = c.execute(
            "SELECT id, kind, student_id, assignment_id, created_at "
            "FROM submissions "
            "WHERE title IS NULL OR title='' OR title IN ('written submission','oral submission') "
            "OR title LIKE '(transcribed from %' OR title LIKE '(from %'").fetchall()
        if not legacy:
            return 0
        students = {r["student_id"]: db.get_student(r["student_id"])["name"]
                    for r in legacy if r["student_id"]}
        assignments_map = {r["assignment_id"]: db.get_assignment(r["assignment_id"])["name"]
                 for r in legacy if r["assignment_id"]}
        for r in legacy:
            c.execute("UPDATE submissions SET title=? WHERE id=?",
                      (_default_title(r["kind"],
                                      students.get(r["student_id"], ""),
                                      assignments_map.get(r["assignment_id"], ""),
                                      r["created_at"]), r["id"]))
        c.commit()
        return len(legacy)


async def _transcribe_doc_audio(doc_audio: UploadFile) -> tuple[str, str]:
    """Validate + persist the source-document audio, transcribe it locally.

    Returns (transcript_text, saved_filename).
    """
    if not doc_audio or not doc_audio.filename:
        return "", ""
    ext = _ext(doc_audio.filename)
    if ext not in ALLOWED_AUDIO:
        raise HTTPException(422, f"unsupported source-document audio type '.{ext}'")
    data = await doc_audio.read()
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(422, "source-document audio file too large")
    saved_name = f"doc-{uuid.uuid4().hex}.{ext}"
    (UPLOAD_DIR / saved_name).write_bytes(data)
    try:
        transcript = await asyncio.to_thread(
            whisper.transcribe, str(UPLOAD_DIR / saved_name), "en")
    except Exception as e:
        raise HTTPException(500, f"source-document transcription failed: {e}")
    return (transcript or {}).get("text", "") or "", saved_name


MAX_DOC_PDF_BYTES = 25 * 1024 * 1024
MAX_DOC_PDF_PAGES = 20


async def _extract_pdf(uf: UploadFile, label: str) -> tuple[str, str, list, list]:
    """Validate + persist an uploaded PDF and extract its text (PyMuPDF).

    Returns (text, saved_filename, page_data_urls, page_names). Scanned
    pages are rendered to JPEGs, SAVED in uploads (so an assignment can re-use
    them later) and also returned as data-URLs for this analysis.
    """
    if not uf or not uf.filename:
        return "", "", [], []
    ext = _ext(uf.filename)
    if ext != "pdf":
        raise HTTPException(422, f"{label} must be a .pdf file (got '.{ext}')")
    data = await uf.read()
    if len(data) > MAX_DOC_PDF_BYTES:
        raise HTTPException(422, f"{label} PDF too large (max 25 MB)")
    saved_name = f"pdf-{uuid.uuid4().hex}.pdf"
    (UPLOAD_DIR / saved_name).write_bytes(data)
    try:
        import pymupdf
        doc = pymupdf.open(stream=data, filetype="pdf")
        n_pages = doc.page_count
        text = "\n".join(p.get_text("text") for p in doc).strip()
        page_urls: list = []
        page_names: list = []
        if not text:  # scanned PDF without a text layer -> use vision
            prefix = f"pdf-{saved_name[4:36]}"
            for i in range(min(n_pages, MAX_DOC_PDF_PAGES)):
                pix = doc[i].get_pixmap(dpi=150)
                name = f"{prefix}-p{i + 1}.jpg"
                (UPLOAD_DIR / name).write_bytes(pix.tobytes("jpeg"))
                page_names.append(name)
                page_urls.append(_b64_from_bytes(pix.tobytes("jpeg"), "image/jpeg"))
        doc.close()
    except Exception as e:
        raise HTTPException(422, f"could not read the {label} PDF: {e}")
    return text, saved_name, page_urls, page_names


async def _build_eval_notes(eval_notes: str, eval_notes_pdf, eval_notes_photos) -> dict | None:
    """Assemble the teacher's evaluation notes (what to check) from the
    analyze() form fields.

    Text + PDF merge when both are given. A PDF without a text layer is
    rendered to page JPEGs for the vision model (no data URLs are ever
    persisted — the PDF stays in uploads, referenced by name). Photos of the
    evaluation instructions are read as page images the same way (the
    filenames are persisted, the data-URLs stripped).
    """
    text = (eval_notes or "").strip()
    pdf_name = ""
    pdf_pages: list = []
    if eval_notes_pdf and eval_notes_pdf.filename:
        pdf_text, pdf_name, pdf_pages = await _extract_pdf(
            eval_notes_pdf, "evaluation instructions")
        if pdf_text:
            text = (text + "\n\n" + pdf_text).strip()
    photo_urls: list = []
    photo_names: list = []
    if eval_notes_photos:
        photo_urls, photo_names = await _read_image_uploads(
            list(eval_notes_photos))
    if not text and not pdf_pages and not photo_urls:
        return None
    return {
        "text": text or None,
        "pdf_name": pdf_name or None,
        "pdf_pages": pdf_pages,   # data-URLs (vision) — stripped before persisting
        "pdf_page_count": len(pdf_pages),
        "photo_names": photo_names,
    }


async def _build_assignment_context(*, instruction: str, instruction_pdf,
                              instruction_photos,
                              doc_text: str, doc_audio, doc_pdf,
                              doc_photos) -> dict | None:
    """Assemble the assignment-context dict from the analyze() form fields.

    Priority (first non-empty wins; text-ish forms beat photos):
      instruction: text/PDF > photos
      document:    text > audio > PDF > photos
    Photo pages and scanned-PDF pages are attached as image data-URLs for
    the vision model; only their filenames are persisted.
    """
    instruction = (instruction or "").strip()
    instr_pdf_name = ""
    if instruction_pdf and instruction_pdf.filename:
        instr_pdf, instr_pdf_name, _imgs = await _extract_pdf(
            instruction_pdf, "instruction")
        if instr_pdf:
            instruction = (instruction + "\n\n" + instr_pdf).strip()

    instr_photo_urls: list = []
    instr_photo_names: list = []
    if not instruction and instruction_photos:
        instr_photo_urls, instr_photo_names = await _read_image_uploads(
            list(instruction_photos))

    doc_text = (doc_text or "").strip()
    doc_audio_name = ""
    doc_pdf_name = ""
    doc_images: list = []
    doc_image_names: list = []
    doc_photo_urls: list = []
    doc_photo_names: list = []
    if doc_audio and doc_audio.filename:
        doc_audio_text, doc_audio_name = await _transcribe_doc_audio(doc_audio)
        doc_text = doc_audio_text
    elif doc_pdf and doc_pdf.filename:
        doc_pdf_text, doc_pdf_name, doc_images, doc_image_names = \
            await _extract_pdf(doc_pdf, "source document")
        doc_text = doc_pdf_text
    elif doc_photos:
        doc_photo_urls, doc_photo_names = await _read_image_uploads(
            list(doc_photos))

    if not (instruction or instr_photo_urls or doc_text
            or doc_images or doc_photo_urls):
        return None
    return {
        "instruction": instruction,
        "document_text": doc_text,
        "document_source": ("audio" if doc_audio_name
                            else ("pdf" if (doc_pdf_name or doc_images)
                                  else ("photos" if doc_photo_urls
                                        else ("text" if doc_text else None)))),
        "document_audio_name": doc_audio_name or None,
        "document_pdf_name": doc_pdf_name or None,
        "instruction_pdf_name": instr_pdf_name or None,
        "document_images": doc_images,
        "instruction_photo_urls": instr_photo_urls,
        "document_photo_urls": doc_photo_urls,
        "instruction_photo_names": instr_photo_names,
        "document_photo_names": doc_photo_names,
        # scanned-PDF page images (saved in uploads) so the ad-hoc context
        # survives a persist/re-attach round-trip (run-ai on a stored submission)
        "document_pdf_page_names": doc_image_names or [],
    }


MAX_PAGES = 20


def _assignment_context_from_assignment(assignment: dict) -> dict | None:
    """Rebuild the assignment-context dict (as consumed by assess.build_messages)
    from a stored assignment row, re-attaching image data-URLs from the files
    saved in uploads.
    """
    def data_url_from_names(names: list) -> list:
        out = []
        for name in (names or []):
            p = UPLOAD_DIR / name
            if p.is_file():
                out.append(_b64_from_bytes(p.read_bytes(),
                                           _mime_for(_ext(name))))
        return out

    instruction = (assignment.get("instruction") or "").strip()
    doc_text = (assignment.get("document_text") or "").strip()
    doc_pdf_pages = data_url_from_names(assignment.get("document_pdf_page_names") or [])
    doc_photos = data_url_from_names(assignment.get("document_photo_names") or [])
    instr_photos = data_url_from_names(assignment.get("instruction_photo_names") or [])
    if not (instruction or doc_text or doc_pdf_pages or doc_photos or instr_photos):
        return None
    return {
        "instruction": instruction,
        "document_text": doc_text,
        "document_source": ("pdf" if (assignment.get("document_pdf_name") or doc_pdf_pages)
                            else ("photos" if doc_photos
                                  else ("audio" if assignment.get("document_audio_name")
                                        else ("text" if doc_text else None)))),
        "document_audio_name": assignment.get("document_audio_name"),
        "document_pdf_name": assignment.get("document_pdf_name"),
        "document_images": doc_pdf_pages,
        "instruction_photo_urls": instr_photos,
        "document_photo_urls": doc_photos,
        "document_pdf_page_names": assignment.get("document_pdf_page_names") or [],
        "instruction_photo_names": assignment.get("instruction_photo_names") or [],
        "document_photo_names": assignment.get("document_photo_names") or [],
    }


def _assignment_eval_notes_from_assignment(assignment: dict) -> dict | None:
    """Rebuild the eval-notes dict from a stored assignment. The PDF page
    images are not persisted, but they are re-rendered on demand when the PDF
    has no text layer; the instruction photos ARE re-attached from their
    stored filenames (data-URLs only live in the request/worker lifetime)."""
    text = (assignment.get("eval_notes") or "").strip()
    pdf_name = assignment.get("eval_notes_pdf_name")
    photo_names = list(assignment.get("eval_notes_photo_names") or [])
    if not text and not pdf_name and not photo_names:
        return None
    photo_urls = []
    for name in photo_names:
        p = UPLOAD_DIR / name
        if p.is_file():
            photo_urls.append(_b64_from_bytes(p.read_bytes(),
                                             _mime_for(_ext(name))))
    return {"text": text or None, "pdf_name": pdf_name,
            "pdf_pages": [], "pdf_page_count": 0,
            "photo_names": photo_names, "photo_urls": photo_urls}


def _strip_persist_context(context: dict | None) -> dict | None:
    """Drop data-URL / image payloads from a context dict before storing it."""
    if not context:
        return None
    return {k: v for k, v in context.items()
            if k != "document_images" and not k.endswith("_urls")}


def _strip_persist_eval_notes(eval_notes: dict | None) -> dict | None:
    if not eval_notes:
        return None
    return {k: v for k, v in eval_notes.items()
            if k not in ("pdf_pages", "photo_urls")}


async def _resolve_assignment_materials(assignment_id: int,
                                  instruction: str, instruction_pdf,
                                  instruction_photos, doc_text: str, doc_audio,
                                  doc_pdf, doc_photos, eval_notes: str,
                                  eval_notes_pdf, eval_notes_photos=None) -> dict:
    """Resolve the assignment context + eval notes + inherited target level.

    When `assignment_id` is set, the assignment's stored instruction / source document /
    evaluation instructions are used (inline context fields are ignored —
    they are redundant for an assignment-linked submission). Otherwise the inline
    fields are assembled (ad-hoc submission). Returns:
      {context, context_persisted, eval_notes, eval_notes_persisted,
       inherited_target}
    """
    if assignment_id:
        assignment = db.get_assignment(assignment_id)
        if not assignment:
            raise HTTPException(404, "Assignment not found")
        context = _assignment_context_from_assignment(assignment)
        en = _assignment_eval_notes_from_assignment(assignment)
        return {
            "context": context,
            "context_persisted": _strip_persist_context(context),
            "eval_notes": en,
            "eval_notes_persisted": _strip_persist_eval_notes(en),
            "inherited_target": assignment.get("target_level"),
            "assignment": assignment,
        }
    # ad-hoc: assemble from the inline form fields (existing behaviour)
    context = await _build_assignment_context(
        instruction=instruction, instruction_pdf=instruction_pdf,
        instruction_photos=instruction_photos,
        doc_text=doc_text, doc_audio=doc_audio, doc_pdf=doc_pdf,
        doc_photos=doc_photos)
    en = await _build_eval_notes(eval_notes, eval_notes_pdf,
                                 eval_notes_photos)
    return {
        "context": context,
        "context_persisted": _strip_persist_context(context),
        "eval_notes": en,
        "eval_notes_persisted": _strip_persist_eval_notes(en),
        "inherited_target": None,
        "assignment": None,
    }


async def _read_image_uploads(files: list) -> tuple[list, list]:
    """Validate + read page photos. Returns (data_urls, saved_paths), in order."""
    files = [f for f in files if f and f.filename]
    if len(files) > MAX_PAGES:
        raise HTTPException(422, f"too many page photos (max {MAX_PAGES})")
    data_urls: list = []
    saved: list = []
    for i, f in enumerate(files, 1):
        ext = _ext(f.filename)
        if ext not in ALLOWED_IMAGE:
            raise HTTPException(422, f"unsupported image type '.{ext}' (photo {i})")
        data = await f.read()
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(422, f"image too large (photo {i})")
        p = UPLOAD_DIR / f"pg-{uuid.uuid4().hex}-{i}.{ext}"
        p.write_bytes(data)
        saved.append(p.name)
        data_urls.append(_b64_from_bytes(data, _mime_for(ext)))
    return data_urls, saved


def seed_rubrics() -> None:
    for r in PRESETS:
        db.upsert_rubric(r)


def _skeleton_matrix(rubric: dict) -> dict:
    """Empty evaluation matrix: one entry per criterion, level to be filled
    by the teacher (used by the "evaluate first" flow — no AI involved)."""
    return {
        "executive_summary": "",
        "overall_level": "",
        "versus_target": "n/a",
        "confidence": "n/a",
        "strong_points": [],
        "areas_for_improvement": [],
        "rubric_mapping": [
            {"criterion": c["name"], "suggested_level": "",
             "justification": "", "evidence": []}
            for c in rubric["criteria"]
        ],
        "student_feedback": {"key_success": "", "target_area": "",
                             "comment": ""},
    }


def _data_urls_from_names(names: list) -> list:
    """Re-attach stored media files (data/uploads/<name>) as data-URLs."""
    out = []
    for name in (names or []):
        p = UPLOAD_DIR / name
        if p.is_file():
            out.append(_b64_from_bytes(p.read_bytes(),
                                      _mime_for(_ext(name))))
    return out


async def _submission_materials(sub: dict, analysis: dict | None = None) -> dict:
    """Rebuild everything the LLM prompt needs from a STORED submission
    (for re-running the AI after the teacher already graded it).

    The transcript is stored on the ANALYSIS row (not the submission), so it
    is passed in via `analysis`. Returns {kind, written_text,
    image_data_urls, transcript, assignment_context, eval_notes, target,
    accommodations, assignment}.
    """
    context = sub.get("context") or {}
    if sub.get("assignment_id"):
        assignment = db.get_assignment(sub["assignment_id"])
        assignment_context = _assignment_context_from_assignment(assignment) if assignment else None
    else:
        assignment = None
        # ad-hoc context was persisted without data-URLs: re-attach images
        context = dict(context)
        for key in ("instruction_photo_names", "document_photo_names",
                    "document_pdf_page_names"):
            if context.get(key):
                context[key.replace("_names", "_urls")] = \
                    _data_urls_from_names(context[key])
        assignment_context = context or None
    en = sub.get("eval_notes") or {}
    eval_notes = {"text": en.get("text"), "pdf_name": en.get("pdf_name"),
                  "pdf_pages": [], "pdf_page_count": 0,
                  "photo_names": list(en.get("photo_names") or [])} or None
    # evaluation-instruction photos: re-attach the page images from their
    # stored filenames (only the names survive the persist round-trip).
    if eval_notes and eval_notes["photo_names"]:
        eval_notes["photo_urls"] = _data_urls_from_names(
            eval_notes["photo_names"])
    transcript = None
    transcript_corrected = False
    if analysis:
        try:
            transcript = (json.loads(analysis["transcript_json"])
                          if analysis.get("transcript_json") else None)
        except Exception:
            transcript = None
        # teacher's transcript correction: when the active mode is "corrected",
        # swap the segment TEXTS for the corrected ones (timestamps/fluency
        # come from the original ASR pass — only the wording changes).
        correction = None
        try:
            correction = (json.loads(analysis["transcript_correction_json"])
                          if analysis.get("transcript_correction_json") else None)
        except Exception:
            correction = None
        if (correction and transcript is not None
                and (analysis.get("transcript_mode") or "original") == "corrected"
                and correction.get("segments")):
            by_time = {round(c["start"], 1): c["text"]
                       for c in correction["segments"] if c.get("text")}
            changed = False
            for seg in transcript.get("segments", []):
                t = by_time.get(round(seg.get("start", 0), 1))
                if t is not None:
                    seg["text"] = t
                    changed = True
            if changed:
                transcript["text"] = " ".join(
                    s.get("text", "") for s in transcript.get("segments", [])).strip()
                transcript_corrected = True
    page_names = []
    try:
        page_names = ((sub.get("payload_meta") or {}).get("page_paths")
                      if isinstance(sub.get("payload_meta"), dict) else []) or []
    except Exception:
        page_names = []
    return {
        "kind": sub["kind"],
        "written_text": sub.get("payload_path") or "",
        "image_data_urls": _data_urls_from_names(page_names),
        "transcript": transcript,
        "transcript_corrected": transcript_corrected,
        "pre_annotations": db.annotations_for_prompt(sub["id"]),
        "assignment_context": assignment_context,
        "eval_notes": eval_notes,
        "target": sub.get("target_level"),
        "accommodations": sub.get("accommodations"),
        "assignment": assignment,
    }


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # First-boot: create the initial account when no user exists yet
        # (login from ELT_INITIAL_LOGIN env, password from
        # ELT_INITIAL_PASSWORD; without a password the account has none and
        # login stays 401 — the operator sets it via the in-app flow or by
        # re-running with the env var). The owner backfill in
        # db._migrate_multiuser already ran in init_db; it attaches legacy
        # rows to user #1, which is exactly this account.
        import logging
        if auth.bootstrap_admin():
            logging.getLogger("elt.auth").info(
                "first boot: created initial account (%s)",
                os.environ.get("ELT_INITIAL_LOGIN", "tibo"))
            # The owner backfill already ran once at init_db time — but on a
            # true first boot there was no account yet, so it was a no-op.
            # Re-run it now that the initial account exists: attach every
            # legacy row (students, assignments, submissions, analyses,
            # annotations, jobs, non-preset rubrics) to it. Idempotent.
            db._migrate_multiuser()
        jobs.start_workers()
        yield
        jobs.stop_workers()

    app = FastAPI(title="ELT Assessor", version="1.0",
                 lifespan=lifespan,
                 # Global auth gate: every /api/* route (except PUBLIC_PATHS
                 # + static) requires the session cookie. Runs in the
                 # endpoint's task, so owner_var propagates to run_in_
                 # threadpool / to_thread db calls inside the handler.
                 dependencies=[__import__("fastapi").Depends(auth.auth_dependency)])
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])
    db.init_db()
    seed_rubrics()
    _migrate_default_titles()   # point 8: smart titles for legacy rows

    # ---------------------------------------------------------------- health
    @app.get("/api/health")
    def health():
        return {
            "ok": True,
            "llm": llm_client.health(),
            "whisper": {"available": "lazy", "model": whisper.MODEL_NAME},
        }

    # ---------------------------------------------------------------- auth
    @app.get("/api/auth/me")
    def auth_me(request: Request):
        """Who am I? {user, has_password, has_account}.

        has_account = at least one account exists on this deployment.
        has_password = whether MY account has a login password set.
        The login screen uses these to decide between "log in" /
        "first account, create one" / "account creation closed".
        """
        o = auth.current_owner()
        u = auth.get_user(o) if o is not None else None
        return {
            "user": auth._user_public(u),
            "has_password": bool(u and u.get("password_hash")),
            "has_account": auth.count_users() > 0,
        }

    @app.post("/api/auth/register")
    def auth_register(payload: dict, request: Request, response: Response):
        """Create an account — open only while NO account exists yet
        (first-boot flow); 403 once the first account exists, so nobody can
        squat a login on a running deployment."""
        if auth.count_users() > 0:
            raise HTTPException(403, "account creation is closed — the first "
                                     "account already exists")
        try:
            uid = auth.create_user(payload.get("username", ""),
                                   payload.get("password", ""))
        except ValueError as e:
            raise HTTPException(422, str(e))
        # First account on this deployment: the gate just attached the
        # operator's identity to the whole legacy dataset (students,
        # assignments, submissions, analyses, non-preset rubrics, jobs) —
        # the owner backfill targets user #1, which is this very account.
        # Idempotent (only NULL-owner rows are ever touched).
        db._migrate_multiuser()
        tok = auth.create_session(uid)
        auth.set_session_cookie(response, tok)
        return {"id": uid, "username": auth.get_user(uid)["username"]}

    @app.post("/api/auth/login")
    def auth_login(payload: dict, response: Response):
        user = auth.user_by_username(payload.get("username", ""))
        if not user or not auth.verify_password(
                payload.get("password", ""), user.get("password_hash")):
            raise HTTPException(401, "invalid credentials")
        tok = auth.create_session(user["id"])
        auth.set_session_cookie(response, tok)
        return auth._user_public(user)

    @app.post("/api/auth/set-password")
    def auth_set_password(payload: dict):
        """Change the caller's password (current one required — it's a change,
        not a takeover)."""
        o = auth.current_owner()
        if o is None:
            raise HTTPException(401, "authentication required")
        u = auth.get_user(o)
        if not u or not u.get("password_hash"):
            raise HTTPException(401, "authentication required")
        pw = (payload.get("password") or "").strip()
        if len(pw) < 8:
            raise HTTPException(422, "password must be at least 8 characters")
        cur = (payload.get("current") or "").strip()
        if not auth.verify_password(cur, u["password_hash"]):
            raise HTTPException(401, "current password is incorrect")
        from . import db
        with db._LOCK:
            db._conn().execute(
                "UPDATE users SET password_hash=? WHERE id=?",
                (auth.hash_password(pw), o))
            db._conn().commit()
        return {"password_set": True}

    @app.post("/api/auth/logout")
    def auth_logout(request: Request, response: Response):
        tok = request.cookies.get(auth.SESSION_COOKIE, "")
        if tok:
            auth.delete_session(tok)
        auth.clear_session_cookie(response)
        return {"logged_out": True}

    # ---------------------------------------------------------------- rubrics
    @app.get("/api/rubrics")
    def list_rubrics(mode: str = ""):
        return db.list_rubrics(mode or None)

    @app.get("/api/rubrics/{rubric_id}")
    def get_rubric(rubric_id: str):
        r = db.get_rubric(rubric_id)
        if not r:
            raise HTTPException(404, "Rubric not found")
        return r

    @app.post("/api/rubrics")
    def create_rubric(payload: dict):
        pid = payload.get("id") or f"custom-{uuid.uuid4().hex[:8]}"
        payload["id"] = pid
        payload["name"] = payload.get("name") or "Untitled rubric"
        payload["mode"] = payload.get("mode") or "written"
        if payload["mode"] not in ("written", "oral"):
            raise HTTPException(422, "mode must be 'written' or 'oral'")
        payload["criteria"] = payload.get("criteria") or []
        if not payload["criteria"]:
            raise HTTPException(422, "at least one criterion required")
        db.upsert_rubric(payload)
        return db.get_rubric(pid)

    @app.delete("/api/rubrics/{rubric_id}")
    def delete_rubric(rubric_id: str):
        r = db.get_rubric(rubric_id)
        if not r:
            raise HTTPException(404, "Rubric not found")
        if r.get("is_preset"):
            raise HTTPException(400, "Preset rubrics cannot be deleted")
        db.delete_rubric(rubric_id)
        return {"deleted": rubric_id}

    @app.get("/api/note-bands")
    def get_note_bands(modalite: str = "", classe: str = "", track: str = ""):
        """Official conversion-table reference (note sur 20 -> attestation).

        Bands are in "points score" units (comprehension /90, expression /120),
        each mapping to a CEFR level; the tables also print a "Note sur 20"
        reference row. The app does NOT grade off these — they are a teacher
        reference to cross-check against the official document. `verified`
        marks bands whose level label is explicitly printed in the document.
        """
        if not (modalite and classe and track):
            raise HTTPException(422, "modalite, classe and track are required")
        bands = note_bands(modalite, classe, track)
        return {"modalite": modalite, "classe": classe, "track": track,
                "bands": bands,
                "vise": NOTE_VISE.get((modalite, classe, track), ""),
                "thresholds": NOTE_THRESHOLDS.get(modalite, ""),
                "verified": all(b.get("verified", False) for b in bands) if bands else False,
                "note": "Référence issue des tableaux de conversion officiels "
                        "(note sur 20 / points score). L'attestation de l'app est "
                        "calculée sur le score /120, pas sur ces bandes."}

    # ---------------------------------------------------------------- students
    @app.get("/api/students")
    def list_students():
        return db.list_students()

    @app.post("/api/students")
    def create_student(payload: dict):
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(422, "student name required")
        sid = db.create_student(name, payload.get("classroom") or "")
        return db.get_student(sid)

    @app.put("/api/students/{student_id}")
    def update_student(student_id: int, payload: dict):
        name = payload.get("name")
        classroom = payload.get("classroom")
        if name is None and classroom is None:
            raise HTTPException(422, "nothing to update")
        updated = db.update_student(
            student_id,
            name=(name or "").strip() if name is not None else None,
            classroom=(classroom or "").strip() if classroom is not None else None)
        if not updated:
            raise HTTPException(404, "student not found")
        return updated

    @app.get("/api/students/{student_id:int}/stats")
    def student_stats_endpoint(student_id: int):
        """Chronological level evolution of one student (per-student "Stats"
        time chart, 2026-10-12): every evaluated submission as a point in
        time, global series + per evaluation type (comprehension/expression
        × written/oral). Only analyses with a usable level count."""
        stats = db.stats_for_student(student_id)
        if stats is None:
            raise HTTPException(404, "Student not found")
        return stats

    @app.delete("/api/students/{student_id}")
    def delete_student(student_id: int,
                       cascade: bool = Query(False, description=
                        "Also delete the student's submissions + analyses "
                        "(and their stored files). Default keeps submissions.")):
        res = db.delete_student(student_id, cascade=cascade)
        if res.get("not_found"):
            raise HTTPException(404, "student not found")
        return res

    # ---------------------------------------------------------------- assignments
    def _validate_assignment_type(skill: str, kind: str) -> tuple[str | None, str | None]:
        """Normalize the exercise type: skill (comprehension|expression) +
        channel kind (written|oral). Empty values stay None (legacy subjects
        without a type keep working)."""
        skill = (skill or "").strip().lower()
        kind = (kind or "").strip().lower()
        if skill and skill not in ("comprehension", "expression"):
            raise HTTPException(422, "skill must be 'comprehension' or 'expression'")
        if kind and kind not in ("written", "oral"):
            raise HTTPException(422, "kind must be 'written' or 'oral'")
        return skill or None, kind or None

    @app.get("/api/assignments")
    def list_assignments_endpoint():
        return db.list_assignments()

    @app.get("/api/assignments/{assignment_id}")
    def get_assignment_endpoint(assignment_id: int):
        t = db.get_assignment(assignment_id)
        if not t:
            raise HTTPException(404, "Assignment not found")
        return t

    @app.get("/api/assignments/{assignment_id}/stats")
    def assignment_stats_endpoint(assignment_id: int):
        """Aggregate statistics of every evaluation made on this assignment:
        per-class tables with per-criterion and global level distributions
        (gaussians) + mean / median / sigma on the /120 point scale. Only
        analyses with at least one filled level (overall or criterion)
        count as an evaluation."""
        stats = db.stats_for_assignment(assignment_id)
        if stats is None:
            raise HTTPException(404, "Assignment not found")
        return stats

    @app.post("/api/assignments/{assignment_id}/stats-ai")
    async def assignment_stats_ai(assignment_id: int, body: dict | None = None):
        """AI class insight for the Stats view: reads the assignment
        (instruction + document + repères), every evaluation (levels + AI
        summary) and the per-class statistics, and produces a JSON class
        analysis (class level, heterogeneity, what worked well, what caused
        problems, recommendations). ASYNC: returns a job handle; progress at
        /api/jobs/{id}/events, terminal payload in jobs.result_json."""
        assignment = db.get_assignment(assignment_id)
        if not assignment:
            raise HTTPException(404, "Assignment not found")
        stats = db.stats_for_assignment(assignment_id)
        if not (stats.get("evaluations") or 0):
            raise HTTPException(422, "No evaluation with a filled level yet on "
                                     "this assignment")
        job_id = db.create_job(
            "stats_ai",
            {"assignment_id": assignment_id,
             "ui_language": assess._ui_language(
                 str((body or {}).get("ui_language") or "")),
             "stats": {"evaluations": stats["evaluations"],
                       "by_class": stats["by_class"],
                       "evaluations_detail": stats["evaluations_detail"]}})
        return {"job_id": job_id, "job_status": "queued",
                "job_kind": "stats_ai", "assignment_id": assignment_id,
                "enqueued": True, "follow_url": f"/api/jobs/{job_id}/events"}

    @app.get("/api/assignments/{assignment_id}/stats-ai")
    def assignment_stats_ai_result(assignment_id: int):
        """Latest saved AI class insight of this assignment (jobs kind
        stats_ai), or 404 when never run / none finished yet.

        (2026-10-14) owner-scoped: only the assignment's owner sees the
        saved insight."""
        o = auth.current_owner()
        owhere = " AND owner_id=?" if o is not None else ""
        oargs = (o,) if o is not None else ()
        rows = db._conn().execute(
            "SELECT id, result_json, created_at, finished_at, elapsed_s, error "
            "FROM jobs WHERE kind='stats_ai' AND status='done' "
            + owhere +
            " AND json_extract(payload_json,'$.assignment_id')=? "
            "ORDER BY id DESC LIMIT 1", oargs + (assignment_id,)).fetchall()
        if not rows:
            raise HTTPException(404, "No saved AI insight yet")
        r = dict(rows[0])
        try:
            r["result"] = json.loads(r.pop("result_json")) if r.get("result_json") else None
        except Exception:
            r["result"] = None
            r.pop("result_json", None)
        return r

    @app.delete("/api/assignments/{assignment_id}/stats-ai")
    def assignment_stats_ai_delete(assignment_id: int):
        """Forget the saved AI insights of this assignment (jobs kind
        stats_ai) — the button goes back to 'run' state.

        (2026-10-14) owner-scoped: a teacher can only erase the AI insights of
        their OWN assignment."""
        o = auth.current_owner()
        owhere = " AND owner_id=?" if o is not None else ""
        oargs = (o,) if o is not None else ()
        with db._LOCK:
            c = db._conn()
            cur = c.execute(
                "DELETE FROM jobs WHERE kind='stats_ai' AND status='done' "
                + owhere +
                " AND json_extract(payload_json,'$.assignment_id')=?",
                oargs + (assignment_id,))
            c.commit()
            deleted = cur.rowcount
        return {"deleted": deleted}

    @app.post("/api/assignments")
    async def create_assignment(name: str = Form(...),
                          description: str = Form(""),
                          target_level: str = Form(""),
                          skill: str = Form(""),
                          kind: str = Form(""),
                          instruction: str = Form(""),
                          doc_text: str = Form(""),
                          doc_audio: UploadFile | None = None,
                          doc_pdf: UploadFile | None = None,
                          doc_photos: List[UploadFile] = Form([]),
                          instruction_pdf: UploadFile | None = None,
                          instruction_photos: List[UploadFile] = Form([]),
                          eval_notes: str = Form(""),
                          eval_notes_pdf: UploadFile | None = None,
                          eval_notes_photos: List[UploadFile] = Form([])):
        """Create an assignment: instruction + source document (text/audio/PDF/photos)
        + target level + optional evaluation instructions.
        """
        target = (target_level or "").strip().upper()
        if target and target not in ("A1", "A2", "B1", "B2", "C1", "C2"):
            raise HTTPException(422, "target_level must be A1-A2-B1-B2-C1-C2")
        skill_v, kind_v = _validate_assignment_type(skill, kind)
        instruction = (instruction or "").strip()
        instr_pdf_name = ""
        if instruction_pdf and instruction_pdf.filename:
            instr_pdf, instr_pdf_name, _u, _n = await _extract_pdf(
                instruction_pdf, "instruction")
            if instr_pdf:
                instruction = (instruction + "\n\n" + instr_pdf).strip()
        instr_photo_urls, instr_photo_names = await _read_image_uploads(
            list(instruction_photos))
        doc_text = (doc_text or "").strip()
        doc_audio_name = ""
        doc_pdf_name = ""
        doc_pdf_pages: list = []
        doc_pdf_page_names: list = []
        doc_photo_urls: list = []
        doc_photo_names: list = []
        if doc_audio and doc_audio.filename:
            doc_audio_text, doc_audio_name = await _transcribe_doc_audio(doc_audio)
            doc_text = doc_audio_text
        elif doc_pdf and doc_pdf.filename:
            doc_pdf_text, doc_pdf_name, doc_pdf_pages, doc_pdf_page_names = \
                await _extract_pdf(doc_pdf, "source document")
            doc_text = doc_pdf_text
        elif doc_photos:
            doc_photo_urls, doc_photo_names = await _read_image_uploads(
                list(doc_photos))
        en_text = (eval_notes or "").strip()
        en_pdf_name = ""
        if eval_notes_pdf and eval_notes_pdf.filename:
            en_pdf_text, en_pdf_name, _u, _n = await _extract_pdf(
                eval_notes_pdf, "evaluation instructions")
            if en_pdf_text:
                en_text = (en_text + "\n\n" + en_pdf_text).strip()
        _en_photo_urls, en_photo_names = await _read_image_uploads(
            list(eval_notes_photos))
        assignment_id = db.create_assignment(
            name=(name or "").strip() or "Untitled assignment",
            description=description,
            target_level=target or None,
            skill=skill_v,
            kind=kind_v,
            instruction=instruction,
            instruction_pdf_name=instr_pdf_name or None,
            instruction_photo_names=instr_photo_names or None,
            document_text=doc_text,
            document_pdf_name=doc_pdf_name or None,
            document_pdf_page_names=doc_pdf_page_names or None,
            document_photo_names=doc_photo_names or None,
            document_audio_name=doc_audio_name or None,
            eval_notes=en_text,
            eval_notes_pdf_name=en_pdf_name or None,
            eval_notes_photo_names=en_photo_names or None,
        )
        return db.get_assignment(assignment_id)

    @app.put("/api/assignments/{assignment_id}")
    async def update_assignment_endpoint(assignment_id: int,
                                   name: str = Form(""),
                                   target_level: str = Form(""),
                                   skill: str = Form(""),
                                   kind: str = Form(""),
                                   instruction: str = Form(""),
                                   doc_text: str = Form(""),
                                   eval_notes: str = Form(""),
                                   instruction_pdf: UploadFile | None = None,
                                   instruction_photos: List[UploadFile] = Form([]),
                                   doc_pdf: UploadFile | None = None,
                                   doc_audio: UploadFile | None = None,
                                   doc_photos: List[UploadFile] = Form([]),
                                   eval_notes_pdf: UploadFile | None = None,
                                   eval_notes_photos: List[UploadFile] = Form([]),
                                   rm_instr_pdf: bool = Form(False),
                                   rm_instr_photos: bool = Form(False),
                                   rm_doc_pdf: bool = Form(False),
                                   rm_doc_audio: bool = Form(False),
                                   rm_doc_photos: bool = Form(False),
                                   rm_eval_pdf: bool = Form(False),
                                   rm_eval_photos: bool = Form(False)):
        """Update an assignment's text fields and/or its attached files (multipart).

        Semantics per file slot: upload a file = REPLACE the current one
        (the old file is removed afterwards if no submission or assignment still
        references it); send the matching rm_* flag = REMOVE the current
        file; send neither = keep the current file as-is. Text-only edits
        work the same way (no file parts at all).
        """
        assignment = db.get_assignment(assignment_id)
        if not assignment:
            raise HTTPException(404, "Assignment not found")
        target = (target_level or "").strip().upper()
        if target and target not in ("A1", "A2", "B1", "B2", "C1", "C2"):
            raise HTTPException(422, "target_level must be A1-A2-B1-B2-C1-C2")
        skill_v, kind_v = _validate_assignment_type(skill, kind)
        fields: dict = {
            "name": (name or "").strip() or assignment["name"],
            "target_level": target or None,
            "skill": skill_v,
            "kind": kind_v,
            "instruction": (instruction or "").strip(),
            "document_text": (doc_text or "").strip(),
            "eval_notes": (eval_notes or "").strip(),
        }
        # -- instruction files
        if instruction_pdf and instruction_pdf.filename:
            instr_pdf, instr_pdf_name, _u, _pn = await _extract_pdf(
                instruction_pdf, "instruction")
            if instr_pdf:
                fields["instruction"] = (
                    fields["instruction"] + "\n\n" + instr_pdf).strip()
            fields["instruction_pdf_name"] = instr_pdf_name or None
        elif rm_instr_pdf:
            fields["instruction_pdf_name"] = None
        if instruction_photos:
            _urls, instr_photo_names = await _read_image_uploads(
                list(instruction_photos))
            fields["instruction_photo_names"] = instr_photo_names
        elif rm_instr_photos:
            fields["instruction_photo_names"] = None
        # -- source-document files (audio > pdf > photos, mirrors create)
        if doc_audio and doc_audio.filename:
            doc_audio_text, doc_audio_name = await _transcribe_doc_audio(doc_audio)
            fields["document_text"] = doc_audio_text
            fields["document_audio_name"] = doc_audio_name
        elif doc_pdf and doc_pdf.filename:
            doc_pdf_text, doc_pdf_name, _pn_urls, doc_pdf_page_names = \
                await _extract_pdf(doc_pdf, "source document")
            fields["document_text"] = doc_pdf_text
            fields["document_pdf_name"] = doc_pdf_name or None
            fields["document_pdf_page_names"] = doc_pdf_page_names or None
        elif doc_photos:
            _urls, doc_photo_names = await _read_image_uploads(list(doc_photos))
            fields["document_photo_names"] = doc_photo_names
        if rm_doc_pdf:
            fields["document_pdf_name"] = None
            fields["document_pdf_page_names"] = None
        if rm_doc_audio:
            fields["document_audio_name"] = None
        if rm_doc_photos:
            fields["document_photo_names"] = None
        # -- evaluation-instructions PDF
        if eval_notes_pdf and eval_notes_pdf.filename:
            en_pdf_text, en_pdf_name, _u, _pn = await _extract_pdf(
                eval_notes_pdf, "evaluation instructions")
            if en_pdf_text:
                fields["eval_notes"] = (
                    fields["eval_notes"] + "\n\n" + en_pdf_text).strip()
            fields["eval_notes_pdf_name"] = en_pdf_name or None
        elif rm_eval_pdf:
            fields["eval_notes_pdf_name"] = None
        # -- evaluation-instructions photos (independent slot: upload replaces,
        #    rm removes, neither keeps)
        if eval_notes_photos:
            _urls, en_photo_names = await _read_image_uploads(
                list(eval_notes_photos))
            fields["eval_notes_photo_names"] = en_photo_names
        elif rm_eval_photos:
            fields["eval_notes_photo_names"] = None
        db.update_assignment(assignment_id, **fields)
        return db.get_assignment(assignment_id)

    @app.delete("/api/assignments/{assignment_id}")
    def delete_assignment_endpoint(assignment_id: int):
        if not db.get_assignment(assignment_id):
            raise HTTPException(404, "Assignment not found")
        return db.delete_assignment(assignment_id)

    @app.get("/api/students/purge")
    def preview_purge(prefix: str = Query("", description=
            "Preview the prefix purge: students whose classroom starts with "
            "this prefix (e.g. '25/26'). Read-only.")):
        students = db.count_students_classroom_prefix(prefix)
        if not prefix.strip():
            raise HTTPException(422, "classroom prefix required")
        return {"dry_run": True,
                "would_delete": len(students),
                "would_unlink_submissions": sum(s["submissions"] for s in students),
                "matches": students}

    @app.delete("/api/students")
    def purge_students_classroom(prefix: str = Query("", description=
            "Delete every student whose classroom starts with this prefix "
            "(e.g. '25/26'). Preview first via GET /api/students/purge."),
            cascade: bool = Query(False, description=
            "Also delete their submissions + analyses. Default keeps them "
            "(they lose the student name).")):
        if not prefix.strip():
            raise HTTPException(422, "classroom prefix required")
        res = db.delete_students_classroom_prefix(prefix, cascade=cascade)
        return {"deleted": len(res["deleted"]),
                "deleted_ids": res["deleted"],
                "submissions_deleted": res["submissions_deleted"],
                "unlinked_submissions": res["submissions_unlinked"]}

    # ---------------- students CSV import / export ----------------
    @app.post("/api/admin/reset-database")
    def reset_database(payload: dict):
        """Wipe the caller's app data (their students, submissions, analyses,
        custom rubrics, jobs) and re-seed the shared preset rubrics.
        Requires `{"confirm": "RESET"}`.

        Scoped to the authenticated user in multi-user mode — it can only
        wipe the caller's own workspace, never another teacher's data.
        Optional `wipe_files: true` also deletes stored media (data/uploads/*)
        — the default keeps them on disk.
        """
        if (payload.get("confirm") or "").strip() != "RESET":
            raise HTTPException(422, 'confirmation required: send {"confirm": "RESET"}')
        wipe_files = bool(payload.get("wipe_files"))
        o = auth.current_owner()
        # owner filter as a bound parameter (one ? per occurrence)
        own = " AND owner_id=?" if o is not None else ""
        a = (o,) if o is not None else ()
        with db._LOCK:
            c = db._conn()
            c.execute(f"DELETE FROM passage_links WHERE analysis_id IN "
                      f"(SELECT id FROM analyses{own})", a)
            c.execute(f"DELETE FROM annotations WHERE submission_id IN "
                      f"(SELECT id FROM submissions{own})", a)
            c.execute(f"DELETE FROM analyses{own}", a)
            c.execute(f"DELETE FROM annotations{own}", a)
            c.execute(f"DELETE FROM submissions{own}", a)
            c.execute(f"DELETE FROM students{own}", a)
            c.execute(f"DELETE FROM assignments{own}", a)
            c.execute(f"DELETE FROM jobs{own}", a)
            # rubrics: only the caller's OWN custom rubrics (shared presets are
            # preserved and re-seeded below; other teachers' custom rubrics are
            # never touched).
            if o is not None:
                c.execute("DELETE FROM rubrics WHERE owner_id=? AND is_preset=0",
                          (o,))
            c.commit()
        seed_rubrics()
        removed_files = 0
        if wipe_files:
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            for f in UPLOAD_DIR.iterdir():
                if f.is_file():
                    f.unlink()
                    removed_files += 1
        return {
            "reset": True,
            "rubrics_reseded": len(db.list_rubrics()),
            "files_removed": removed_files,
            "students": len(db.list_students()),
        }

    @app.get("/api/students/csv")
    def export_students_csv():
        import csv as _csv
        import io
        buf = io.StringIO()
        w = _csv.writer(buf)
        w.writerow(["id", "name", "classroom", "created_at"])
        for s in db.students_as_rows():
            w.writerow([s["id"], s["name"], s.get("classroom") or "",
                        s["created_at"]])
        return Response(content=buf.getvalue().encode("utf-8-sig"),
                        media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition":
                                 'attachment; filename="students.csv"'})

    @app.post("/api/students/csv")
    def import_students_csv(file: UploadFile = File(...)):
        import csv as _csv
        import io
        raw = file.file.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        rows = list(_csv.DictReader(io.StringIO(text)))
        if not rows:
            raise HTTPException(422, "empty CSV")
        created, updated, skipped = 0, 0, []
        for i, row in enumerate(rows, start=2):  # line 1 = header
            name = (row.get("name") or "").strip()
            classroom = (row.get("classroom") or "").strip()
            sid = (row.get("id") or "").strip()
            if not name:
                skipped.append(f"line {i}: no name")
                continue
            existing_id = None
            if sid.isdigit():
                s = db.get_student(int(sid))
                if s:
                    existing_id = int(sid)
            if existing_id is None:
                # fall back to name+classroom match so re-imports don't duplicate
                for s in db.list_students():
                    if s["name"].lower() == name.lower() and \
                            (s.get("classroom") or "") == classroom:
                        existing_id = s["id"]
                        break
            try:
                if existing_id:
                    db.update_student(existing_id, name=name, classroom=classroom)
                    updated += 1
                else:
                    db.upsert_student_csv(name=name, classroom=classroom)
                    created += 1
            except Exception as e:
                skipped.append(f"line {i}: {e}")
        return {"created": created, "updated": updated,
                "skipped": skipped, "total_rows": len(rows)}

    # ---------------------------------------------------- job staging helpers
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
            (UPLOAD_DIR / audio_name).write_bytes(data)
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
                "analysis": _enrich_analysis(analysis) if analysis else None}

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
    @app.post("/api/analyze")
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
    @app.post("/api/analyze/stream")
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
    @app.post("/api/evaluate")
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
    @app.post("/api/analyses/{analysis_id}/run-ai")
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

    # ---------------------------------------------------------------- jobs
    @app.get("/api/jobs/counts")
    def job_counts():
        return {"counts": db.job_counts(), "max_workers": jobs.max_workers()}

    @app.get("/api/jobs")
    def list_jobs(status: str = "", limit: int = 100):
        """Job queue + history. status: queued|running|done|error|cancelled|''."""
        return {"jobs": db.job_list(status=status, limit=min(max(limit, 1), 500)),
                "counts": db.job_counts(),
                "max_workers": jobs.max_workers()}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: int):
        j = db.job_get(job_id)
        if not j:
            raise HTTPException(404, "job not found")
        out = {k: j.get(k) for k in ("id", "kind", "status", "phase",
                                     "submission_id", "analysis_id",
                                     "created_at", "started_at", "finished_at",
                                     "elapsed_s", "error", "cancel_flag")}
        out["job_id"] = j["id"]
        out["payload"] = j.get("payload")
        return out

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: int):
        """Cancel a queued job, or signal a running job to stop after its
        current step."""
        j = db.job_get(job_id)
        if not j:
            raise HTTPException(404, "job not found")
        if j["status"] not in ("queued", "running"):
            raise HTTPException(409, f"job is {j['status']}, not cancellable")
        db.job_update(job_id, cancel_flag=1)
        if j["status"] == "queued":
            db.job_update(job_id, status="cancelled", finished=True)
        return {"job_id": job_id, "cancelled": True}

    @app.post("/api/jobs/settings")
    def set_job_settings(payload: dict):
        """Set the number of simultaneous workers (1-4, persisted)."""
        try:
            v = int((payload or {}).get("max_workers"))
        except (TypeError, ValueError):
            raise HTTPException(422, "max_workers must be an integer")
        if not (1 <= v <= jobs.MAX_WORKERS_CAP):
            raise HTTPException(422, f"max_workers must be 1-{jobs.MAX_WORKERS_CAP}")
        db.set_setting("max_workers", str(v))
        return {"max_workers": jobs.max_workers()}

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: int):
        return await _job_events(job_id)


    # ---------------------------------------------------------------- history
    def _enrich_analysis(a: dict) -> dict:
        """Hydrate JSON columns + recompute attestation from the stored matrix."""
        try:
            a["matrix"] = json.loads(a["matrix_json"]) if a.get("matrix_json") else None
        except Exception:
            a["matrix"] = None
        try:
            a["fluency"] = json.loads(a["fluency_json"]) if a.get("fluency_json") else None
        except Exception:
            a["fluency"] = None
        try:
            a["transcript"] = json.loads(a["transcript_json"]) if a.get("transcript_json") else None
        except Exception:
            a["transcript"] = None
        try:
            a["transcript_correction"] = (json.loads(a["transcript_correction_json"])
                                          if a.get("transcript_correction_json") else None)
        except Exception:
            a["transcript_correction"] = None
        a["transcript_mode"] = a.get("transcript_mode") or ("original" if a.get("transcript") else None)
        try:
            a["note20"] = json.loads(a["note20_json"]) if a.get("note20_json") else None
        except Exception:
            a["note20"] = None
        a["validated"] = bool(a.get("validated_at"))
        # ai_has is a lightweight "ai_matrix_json IS NOT NULL" flag exposed by the
        # LIST query (which does not load the full blob); detail rows load the
        # blob itself. Use whichever is present so both paths backfill.
        a["has_ai_snapshot"] = bool(a.get("ai_matrix_json") or a.get("ai_has"))
        # Original AI recommendation, snapshotted on first validation. The UI's
        # Mode Évaluation shows the AI badge from THIS (not the current matrix,
        # which carries the teacher's levels once a counter-proposal is saved).
        try:
            a["ai_matrix"] = json.loads(a["ai_matrix_json"]) if a.get("ai_matrix_json") else None
        except Exception:
            a["ai_matrix"] = None
        # AI opinion metadata (dual-mode): which mode the last run used, and
        # when. Null until an AI run has happened (or it was stored directly
        # by the legacy analyze endpoints, mode "blind").
        a["ai_mode"] = a.get("ai_mode") or ("blind" if a["has_ai_snapshot"] else None)
        a["ai_at"] = a.get("ai_at") or None
        a["attestation"] = None
        if a.get("matrix") and a.get("rubric_name"):
            r = db.get_rubric(a.get("rubric_id") or "")
            if r and r.get("attestation"):
                a["attestation"] = compute_attestation(
                    r, a["matrix"].get("rubric_mapping", []))
        return a

    @app.get("/api/analyses")
    def list_analyses(student_id: int = 0, limit: int = 200,
                     classroom_prefix: str = "", title: str = "",
                     assignment_id: int = 0):
        return [_enrich_analysis(a) for a in
                db.list_submissions(student_id=student_id or None, limit=limit,
                                     classroom_prefix=classroom_prefix,
                                     title=title,
                                     assignment_id=assignment_id or None)]

    @app.get("/api/analyses/{analysis_id}")
    def get_analysis(analysis_id: int):
        a = db.get_analysis(analysis_id)
        if not a:
            raise HTTPException(404, "analysis not found")
        return _enrich_analysis(a)

    @app.delete("/api/analyses/{analysis_id}")
    def delete_analysis(analysis_id: int):
        # (2026-10-14) owner-scoped: get_analysis() already 404s a foreign
        # analysis for the caller, so only delete rows the caller owns.
        a = db.get_analysis(analysis_id)
        if not a:
            raise HTTPException(404, "analysis not found")
        with db._LOCK:
            db._conn().execute("DELETE FROM analyses WHERE id=?", (analysis_id,))
            db._conn().commit()
        return {"deleted": analysis_id}

    @app.put("/api/analyses/{analysis_id}")
    def update_analysis_teacher(analysis_id: int, body: dict):
        """Teacher's counter-proposal: save edited per-criterion levels, the
        hand-set /20 note, and mark the attestation as validated.

        body: {
          "levels": {criterion_name: "A1".."C2"|"", ...}  optional,
          "note20": {"modalite","classe","track","note"} | null   optional,
          "validate": true | "revert"   optional
        }
        `validate` writes `validated_at` (and snapshots the original AI matrix
        into ai_matrix_json on the FIRST validation only, so "revert" can go
        back to the AI's proposal); "revert" restores the AI matrix and clears
        the validation. Levels are stored INTO matrix_json (rubric_mapping
        suggested_level) so every read path recomputes the attestation from
        the teacher's levels. The /120 score stays the single source of truth
        — the /20 note is reference-only (never graded from).
        """
        a = db.get_analysis(analysis_id)
        if not a:
            raise HTTPException(404, "analysis not found")
        body = body or {}
        sets: dict = {}
        levels = body.get("levels")
        if isinstance(levels, dict):
            m = a.get("matrix_json")
            data = json.loads(m) if m else None
            if not isinstance(data, dict) or not isinstance(data.get("rubric_mapping"), list):
                raise HTTPException(400, "analysis has no editable rubric mapping")
            allowed = set()
            r = db.get_rubric(a.get("rubric_id") or "")
            if r:
                allowed = {c["name"] for c in r.get("criteria", [])}
            for entry in data["rubric_mapping"]:
                name = entry.get("criterion")
                if name in levels and (not allowed or name in allowed):
                    lvl = str(levels.get(name) or "").strip().upper()
                    if lvl and lvl not in ("A1", "A2", "B1", "B2", "C1", "C2"):
                        raise HTTPException(422, f"invalid level for criterion {name!r}")
                    entry["suggested_level"] = lvl
            sets["matrix_json"] = json.dumps(data, ensure_ascii=False)
            # For attestation rubrics, the stored overall level is the
            # attestation level derived from the TEACHER's levels (this is
            # what the history list/detail shows). Non-attestation rubrics
            # keep the AI's overall_level.
            if r and r.get("attestation"):
                att = compute_attestation(r, data.get("rubric_mapping", []))
                if att:
                    sets["overall_level"] = att["attestation"]
        # note20: key ABSENT = no change; null = clear; dict = save.
        if "note20" in body:
            note20 = body.get("note20")
            if note20 is None:
                sets["note20_json"] = _SET_NULL
            else:
                if not isinstance(note20, dict):
                    raise HTTPException(422, "note20 must be an object or null")
                try:
                    note = float(note20.get("note"))
                except (TypeError, ValueError):
                    raise HTTPException(422, "note20.note must be a number")
                if not (0 <= note <= 45):
                    raise HTTPException(422, "note20.note out of range 0–45")
                sets["note20_json"] = json.dumps({
                    "modalite": note20.get("modalite") or "",
                    "classe": note20.get("classe") or "",
                    "track": note20.get("track") or "",
                    "note": note,
                }, ensure_ascii=False)
        val = body.get("validate")
        if val in (True, "yes", "true"):
            sets["validated_at"] = db.now_iso()
            if not a.get("ai_matrix_json"):
                # first validation: keep the AI's original matrix for "revert"
                sets["ai_matrix_json"] = a.get("matrix_json")
        elif val in ("revert", False):
            if not a.get("ai_matrix_json"):
                raise HTTPException(409, "no AI snapshot to revert to yet")
            sets["matrix_json"] = a["ai_matrix_json"]
            sets["validated_at"] = _SET_NULL  # type: ignore[assignment]
        if not sets:
            return _enrich_analysis(a)
        with db._LOCK:
            c = db._conn()
            col_exprs = []
            args = []
            for k, v in sets.items():
                if v is _SET_NULL:
                    col_exprs.append(f"{k}=NULL")
                else:
                    col_exprs.append(f"{k}=?")
                    args.append(v)
            c.execute("UPDATE analyses SET " + ", ".join(col_exprs)
                      + " WHERE id=?", args + [analysis_id])
            c.commit()
        return _enrich_analysis(db.get_analysis(analysis_id))

    @app.post("/api/submissions/{sub_id}/ocr")
    def start_ocr(sub_id: int):
        """Enqueue the hybrid OCR job (tesseract line boxes + LLM vision
        polish) for a written submission's page photos. Returns the job
        handle; follow it at `follow_url` (SSE). The result is persisted on
        submissions.ocr_json and served by GET /api/submissions/{id}.ocr."""
        sub = db.get_submission(sub_id)
        if not sub:
            raise HTTPException(404, "submission not found")
        if sub.get("kind") != "written":
            raise HTTPException(422, "OCR is only available for written submissions")
        meta = sub.get("payload_meta") or {}
        if not meta.get("page_paths"):
            raise HTTPException(422, "this submission has no page photos")
        with db._LOCK:
            c = db._conn()
            n = c.execute(
                "SELECT COUNT(*) FROM jobs WHERE submission_id=? AND kind='ocr' "
                "AND status IN ('queued','running')", (sub_id,)).fetchone()[0]
        if n:
            raise HTTPException(409, "an OCR job for this submission is already in the queue")
        job_id = db.create_job("ocr", {"submission_id": sub_id},
                               submission_id=sub_id, analysis_id=None)
        job = db.job_get(job_id)
        return {"job_id": job_id, "job_status": job.get("status"),
                "job_kind": "ocr", "submission_id": sub_id,
                "enqueued": True, "follow_url": f"/api/jobs/{job_id}/events"}

    @app.get("/api/submissions/{sub_id}.ocr")
    def get_ocr(sub_id: int):
        sub = db.get_submission(sub_id)
        if not sub:
            raise HTTPException(404, "submission not found")
        ocr_data = sub.get("ocr")
        with db._LOCK:
            c = db._conn()
            job = c.execute(
                "SELECT * FROM jobs WHERE submission_id=? AND kind='ocr' "
                "ORDER BY id DESC LIMIT 1", (sub_id,)).fetchone()
        running = bool(job and job["status"] in ("queued", "running"))
        return {"submission_id": sub_id, "ocr": ocr_data, "running": running,
                "job_id": job["id"] if job else None}

    # ------------------------------------------------------------- annotations
    def _validate_annotation_span(body: dict, sub: dict, span: dict):
        """Validate/clamp an annotation span against the submission's content.

        Returns (clean_span, page_idx, quote). Raises ValueError on bad input."""
        kind = sub["kind"]
        if kind == "written":
            ocr_data = sub.get("ocr") or {}
            pages = ocr_data.get("pages") or []
            if not pages:
                raise ValueError("no OCR lines available for this copy yet")
            page = int(span.get("page", 0))
            if not (0 <= page < len(pages)):
                raise ValueError("page out of range")
            lines = pages[page].get("lines") or []

            def clamp(li: int, ch: int) -> int:
                if not (0 <= li < len(lines)):
                    raise ValueError("line out of range")
                ln = lines[li]
                L = len(ln.get("text") or "")
                return max(0, min(int(ch), L))

            raw_sl = int(span.get("start_line", 0))
            raw_el = int(span.get("end_line", raw_sl))
            # reject inverted RAW ranges before clamping can mask them
            if raw_el < raw_sl or (raw_el == raw_sl
                    and int(span.get("end_char", 0)) < int(span.get("start_char", 0))):
                raise ValueError("annotation range is inverted or empty")
            # NOTE: clamp(li, ch) validates the LINE `li` (raises if out of range)
            # but RETURNS the clamped CHARACTER offset, not the line. So the line
            # index must come from the raw values, and clamp is only used for the
            # char offsets (2026-10-10 bug: `sl_line = clamp(raw_sl, 0)` always
            # returned 0, pinning every annotation to line 0).
            sl_line = raw_sl
            el_line = raw_el
            sc = clamp(sl_line, int(span.get("start_char", 0)))
            ec = clamp(el_line, int(span.get("end_char", 0)))
            if (el_line, ec) < (sl_line, sc):
                raise ValueError("annotation range is inverted or empty")
            # quoted passage, possibly spanning several lines
            parts = []
            for li in range(sl_line, el_line + 1):
                ln_text = lines[li].get("text") or ""
                a = 0 if li > sl_line else sc
                b = len(ln_text) if li < el_line else ec
                seg = ln_text[a:b].strip()
                if seg:
                    parts.append(seg)
            quote = " ".join(parts)
            clean = {"page": page, "start_line": sl_line, "start_char": sc,
                     "end_line": el_line, "end_char": ec}
            return clean, page, quote
        # oral
        tr = None
        analysis = db.latest_analysis_for_submission(sub["id"])
        if analysis and analysis.get("transcript_json"):
            try:
                tr = json.loads(analysis["transcript_json"])
            except Exception:
                tr = None
        dur = (tr or {}).get("duration_s") or sub.get("duration_s") or 0
        s = float(span.get("start_s", 0))
        e = float(span.get("end_s", 0))
        if dur:
            s, e = max(0.0, s), min(e, dur)
        if e - s < 0.2:
            raise ValueError("time range too short (min 0.2 s)")
        # quoted text = the transcript words/segments overlapping the range
        quote = ""
        if tr:
            segs = []
            for seg in tr.get("segments") or []:
                if seg.get("end", 0) <= s or seg.get("start", 0) >= e:
                    continue
                segs.append(seg.get("text", "").strip())
            quote = " ".join(t for t in segs if t)
        return {"start_s": round(s, 2), "end_s": round(e, 2)}, None, quote

    @app.get("/api/submissions/{sub_id}/annotations")
    def list_annotations(sub_id: int):
        sub = db.get_submission(sub_id)
        if not sub:
            raise HTTPException(404, "submission not found")
        return {"annotations": db.list_annotations(sub_id)}

    @app.post("/api/submissions/{sub_id}/annotations")
    def create_annotation(sub_id: int, body: dict):
        """Create one annotation. body: {kind?, span, sticker?, level?, note?}.
        For written copies the quote is derived server-side from the OCR lines
        (never trusted from the client); for oral recordings from the segments."""
        sub = db.get_submission(sub_id)
        if not sub:
            raise HTTPException(404, "submission not found")
        body = body or {}
        span = body.get("span") or {}
        if not isinstance(span, dict):
            raise HTTPException(422, "span object required")
        level = (body.get("level") or "").strip().upper()
        if level and level not in ("A1", "A2", "B1", "B2", "C1", "C2"):
            raise HTTPException(422, "level must be A1..C2 or empty")
        sticker = (body.get("sticker") or "").strip() or None
        note = (body.get("note") or "").strip() or None
        try:
            clean_span, page_idx, quote = _validate_annotation_span(body, sub, span)
        except (ValueError, TypeError) as e:
            raise HTTPException(422, str(e))
        a_id = db.create_annotation(
            submission_id=sub_id, kind=sub["kind"], span=clean_span,
            quote=quote, sticker=sticker, level=level or None, note=note,
            page_idx=page_idx,
            analysis_id=(body.get("analysis_id") if isinstance(body.get("analysis_id"), int) else None))
        return db.get_annotation(a_id)

    @app.put("/api/annotations/{annotation_id}")
    def update_annotation_endpoint(annotation_id: int, body: dict):
        a = db.get_annotation(annotation_id)
        if not a:
            raise HTTPException(404, "annotation not found")
        body = body or {}
        level = body.get("level")
        if level is not None:
            level = (level or "").strip().upper()
            if level and level not in ("A1", "A2", "B1", "B2", "C1", "C2"):
                raise HTTPException(422, "level must be A1..C2 or empty")
        sticker = body.get("sticker")
        if sticker is not None:
            sticker = (sticker or "").strip() or None
        note = body.get("note")
        if note is not None:
            note = (note or "").strip() or None
        span = body.get("span")
        quote = None  # None = keep the stored quote
        page_idx = None
        if span is not None:
            if not isinstance(span, dict):
                raise HTTPException(422, "span object required")
            sub = db.get_submission(a["submission_id"])
            try:
                span, page_idx, quote = _validate_annotation_span(body, sub, span)
            except (ValueError, TypeError) as e:
                raise HTTPException(422, str(e))
        out = db.update_annotation(
            annotation_id, quote=quote, sticker=sticker,
            level=None if level is None else (level or None),
            note=None if note is None else note,
            span=span,
            page_idx=page_idx)
        if not out:
            raise HTTPException(404, "annotation not found")
        return out

    @app.delete("/api/annotations/{annotation_id}")
    def delete_annotation_endpoint(annotation_id: int):
        if not db.get_annotation(annotation_id):
            raise HTTPException(404, "annotation not found")
        db.delete_annotation(annotation_id)
        return {"deleted": annotation_id}

    @app.post("/api/analyses/{analysis_id}/transcript-correction")
    def save_transcript_correction(analysis_id: int, body: dict):
        """Save the teacher's corrected transcript (the ASR misheard some words).

        body: {
          "segments": [{"start": 0.0, "end": 3.2, "text": "…"}, ...],  // REQUIRED
          "mode": "original" | "corrected"   // which version the evaluator's
                                              // AI should use next (default:
                                              // "corrected" when saving)
        }
        Both versions are kept: the original stays in transcript_json, the
        correction in transcript_correction_json. `mode` switches which one the
        run-ai prompt receives (and which one the UI shows as active). The
        original Whisper timestamps/fluency metrics are kept (they are the
        audio's ground truth); only the text is replaced in the prompt.
        """
        a = db.get_analysis(analysis_id)
        if not a:
            raise HTTPException(404, "analysis not found")
        sub = db.get_submission(a["submission_id"])
        if not sub or sub.get("kind") != "oral":
            raise HTTPException(422, "transcript correction requires an oral analysis")
        body = body or {}
        segs = body.get("segments")
        if not isinstance(segs, list) or not segs:
            raise HTTPException(422, "segments list required")
        clean = []
        for s in segs:
            try:
                clean.append({"start": round(float(s.get("start", 0)), 2),
                              "end": round(float(s.get("end", 0)), 2),
                              "text": str(s.get("text", "")).strip()})
            except (TypeError, ValueError):
                raise HTTPException(422, "bad segment")
        mode = str(body.get("mode") or "corrected").strip().lower()
        if mode not in ("original", "corrected"):
            raise HTTPException(422, "mode must be original|corrected")
        db.update_analysis(
            analysis_id,
            transcript_correction_json=json.dumps(
                {"segments": clean, "updated_at": db.now_iso()},
                ensure_ascii=False),
            transcript_mode=mode,
        )
        return {"analysis_id": analysis_id, "transcript_mode": mode,
                "segments": clean}

    @app.delete("/api/analyses/{analysis_id}/transcript-correction")
    def clear_transcript_correction(analysis_id: int):
        """Remove the teacher's correction (the original ASR transcript becomes
        the sole source again)."""
        a = db.get_analysis(analysis_id)
        if not a:
            raise HTTPException(404, "analysis not found")
        db.update_analysis(
            analysis_id,
            transcript_correction_json=db._CLEAR,
            transcript_mode="original",
        )
        return {"analysis_id": analysis_id, "cleared": True}

    @app.get("/api/analyses/{analysis_id}/passage-links")
    def list_passage_links(analysis_id: int):
        a = db.get_analysis(analysis_id)
        if not a:
            raise HTTPException(404, "analysis not found")
        return {"links": db.passage_links(analysis_id)}

    @app.post("/api/analyses/{analysis_id}/passage-links")
    def add_passage_link(analysis_id: int, body: dict):
        """Link an annotated passage to a criterion: body {annotation_id, criterion}."""
        a = db.get_analysis(analysis_id)
        if not a:
            raise HTTPException(404, "analysis not found")
        body = body or {}
        ann_id = body.get("annotation_id")
        criterion = str(body.get("criterion") or "").strip()
        if not isinstance(ann_id, int) or not criterion:
            raise HTTPException(422, "annotation_id and criterion required")
        ann = db.get_annotation(ann_id)
        if not ann or ann["submission_id"] != a["submission_id"]:
            raise HTTPException(422, "annotation not found for this analysis")
        # criterion must belong to the analysis's rubric
        rubric = db.get_rubric(a.get("rubric_id") or "")
        names = {c["name"] for c in rubric["criteria"]} if rubric else set()
        if names and criterion not in names:
            raise HTTPException(422, f"unknown criterion '{criterion}'")
        link_id = db.link_passage(analysis_id, ann_id, criterion)
        return {"link_id": link_id, "linked": True}

    @app.delete("/api/analyses/{analysis_id}/passage-links")
    def remove_passage_link(analysis_id: int, annotation_id: int,
                            criterion: str = ""):
        a = db.get_analysis(analysis_id)
        if not a:
            raise HTTPException(404, "analysis not found")
        ok = db.unlink_passage(analysis_id, annotation_id, criterion)
        return {"deleted": ok}

    @app.get("/api/submissions/{sub_id}")
    def get_submission(sub_id: int):
        s = db.get_submission(sub_id)
        if not s:
            raise HTTPException(404, "submission not found")
        return s

    @app.delete("/api/submissions/{sub_id}")
    def delete_submission(sub_id: int):
        db.delete_submission(sub_id)
        return {"deleted": sub_id}

    # ---------------------------------------------------------------- files
    @app.get("/api/files/{path:path}")
    def get_file(path: str):
        p = (UPLOAD_DIR / path).resolve()
        if not str(p).startswith(str(UPLOAD_DIR.resolve())) or not p.exists():
            raise HTTPException(404, "not found")
        # (2026-10-14) ownership enforcement: a media file is served ONLY to
        # its owner (or the unscoped/system context). Random uuid4 names make
        # guessing infeasible, but a leaked URL must not leak student copies
        # or another teacher's assignment material — foreign AND untracked
        # (referenced by no data row) files 404 exactly like missing ones
        # (no existence oracle). Verified 2026-10-14: every file on disk is
        # referenced, so this strict rule cannot break legitimate serving.
        o = auth.current_owner()
        if o is not None:
            owner = db.media_owner_map().get(path)
            if owner != o:
                raise HTTPException(404, "not found")
        return FileResponse(str(p))

    # ---------------------------------------------------------------- docs
    DOCS_DIR = BASE_DIR.parent / "docs"
    # P1.4: two-section docs view — "user" (the user guide) is the default;
    # "dev" (async-jobs / readme / ux-audit) is isolated behind a Dev sub-tab.
    DOCS_INDEX = {
        "userguide": {"path": DOCS_DIR / "userguide.md", "category": "user"},
        "async-jobs": {"path": DOCS_DIR / "async-jobs.md", "category": "dev"},
        "ux-audit": {"path": BASE_DIR.parent / "ux-audit1.md", "category": "dev"},
        "readme": {"path": BASE_DIR.parent / "README.md", "category": "dev"},
    }

    @app.get("/api/docs")
    def list_docs():
        out = []
        for slug, meta in DOCS_INDEX.items():
            if meta["path"].exists():
                out.append({"slug": slug, "exists": True,
                            "category": meta["category"],
                            "bytes": meta["path"].stat().st_size})
        return {"docs": out}

    @app.get("/api/docs/{slug}")
    def get_doc(slug: str):
        meta = DOCS_INDEX.get(slug)
        if not meta or not meta["path"].exists():
            raise HTTPException(404, "document not found")
        return {"slug": slug, "category": meta["category"],
                "markdown": meta["path"].read_text(encoding="utf-8")}

    @app.get("/")
    def index():
        return FileResponse(str(STATIC_DIR / "index.html"))

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    if DOCS_DIR.exists():
        app.mount("/docs-static", StaticFiles(directory=str(DOCS_DIR)), name="docs-static")
    return app


app = create_app()
