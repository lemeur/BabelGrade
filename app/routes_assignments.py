"""Assignment CRUD + stats routes (the "work to be assessed" entities).

Extracted from main.py (2026-10-16 split).
"""
import json

from fastapi import APIRouter, Form, HTTPException, UploadFile

from . import assess, auth, db
from .media import _extract_pdf, _read_image_uploads, _transcribe_doc_audio
from typing import List

router = APIRouter()


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

@router.get("/api/assignments")
def list_assignments_endpoint():
    return db.list_assignments()

@router.get("/api/assignments/{assignment_id}")
def get_assignment_endpoint(assignment_id: int):
    t = db.get_assignment(assignment_id)
    if not t:
        raise HTTPException(404, "Assignment not found")
    return t

@router.get("/api/assignments/{assignment_id}/stats")
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

@router.post("/api/assignments/{assignment_id}/stats-ai")
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

@router.get("/api/assignments/{assignment_id}/stats-ai")
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

@router.delete("/api/assignments/{assignment_id}/stats-ai")
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

@router.post("/api/assignments")
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

@router.put("/api/assignments/{assignment_id}")
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

@router.delete("/api/assignments/{assignment_id}")
def delete_assignment_endpoint(assignment_id: int):
    if not db.get_assignment(assignment_id):
        raise HTTPException(404, "Assignment not found")
    return db.delete_assignment(assignment_id)

