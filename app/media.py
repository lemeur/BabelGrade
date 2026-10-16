"""Upload handling + task/assignment material staging helpers.

Extracted from main.py (2026-10-16 split): everything that is NOT a route
handler — file-size/type validation, PDF extraction (text layer + scanned-page
JPEGs for vision), doc audio transcription, assignment context/eval-notes
assembly, image uploads, submission material re-hydration.

Imported by the routes_* modules and lazily by jobs.py (workers re-stage
queued payloads).
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import UploadFile, HTTPException

from . import db, whisper
from . import config
from .config import (MAX_AUDIO_BYTES, MAX_DOC_PDF_BYTES, MAX_DOC_PDF_PAGES,
                     MAX_IMAGE_BYTES, MAX_PAGES, ALLOWED_AUDIO, ALLOWED_IMAGE)
from .rubrics import PRESETS

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
    (config.UPLOAD_DIR / saved_name).write_bytes(data)
    try:
        transcript = await asyncio.to_thread(
            whisper.transcribe, str(config.UPLOAD_DIR / saved_name), "en")
    except Exception as e:
        raise HTTPException(500, f"source-document transcription failed: {e}")
    return (transcript or {}).get("text", "") or "", saved_name


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
    (config.UPLOAD_DIR / saved_name).write_bytes(data)
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
                (config.UPLOAD_DIR / name).write_bytes(pix.tobytes("jpeg"))
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


def _assignment_context_from_assignment(assignment: dict) -> dict | None:
    """Rebuild the assignment-context dict (as consumed by assess.build_messages)
    from a stored assignment row, re-attaching image data-URLs from the files
    saved in uploads.
    """
    def data_url_from_names(names: list) -> list:
        out = []
        for name in (names or []):
            p = config.UPLOAD_DIR / name
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
        p = config.UPLOAD_DIR / name
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
        p = config.UPLOAD_DIR / f"pg-{uuid.uuid4().hex}-{i}.{ext}"
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
        p = config.UPLOAD_DIR / name
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

