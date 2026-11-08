"""Class roster photo import: extract class identity + student names from
photos of the school's student list, then create the students.

Flow (2026-11-08, tibo-approved plan):
* POST /api/students/import-photos
    multipart (photos[] + optional class_code hint) -> validate + stage the
    photos into data/uploads/ (roster-* names) -> enqueue a roster_import
    JOB (ONE LLM vision call over all photos) -> return the job handle.
    The job is LONG (the LLM is slow: one call over up to 10 photos), so it
    rides the standard async queue; the UI follows /api/jobs/{id}/events.
    Result: the EXTRACTED roster draft (nothing is created yet) persisted
    on the job row (jobs.result_json) — like stats_ai.
* GET  /api/students/import-photos/{job_id}
    -> {status, draft: {school_name, class_name, class_code_hint,
        students: [{first_name, last_name}], warnings}} or 404/409.
* POST /api/students/import-photos/{job_id}/commit
    -> teacher-reviewed roster (names edited, rows dropped, classroom code
    chosen): idempotent upsert (name+classroom match = update, else create),
    photos deleted. Returns {created, updated, skipped}.

No new tables: students + jobs only. Owner-scoped like every students
route (the job row carries owner_id; run_job re-sets the owner context).
"""
import json
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from . import assess, config, db

router = APIRouter()

MAX_ROSTER_PHOTOS = 10


def _staged_roster_names(job_id: int) -> list | None:
    """The roster photo names of a roster_import job (from its payload)."""
    j = db.job_get(job_id)
    if not j or j.get("kind") != "roster_import":
        return None
    p = j.get("payload") or {}
    return p.get("photo_names") or []


def _roster_draft(job: dict) -> dict:
    """Parse the job's result_json into the roster draft (None if not done)."""
    raw = job.get("result_json")
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(d, dict) or "roster" not in d:
        return None
    return d.get("roster")


@router.post("/api/students/import-photos")
async def import_roster_photos(
        photos: list[UploadFile] = File(default=[]),
        class_code: str = Form(default=""),
        ui_language: str = Form(default="")):
    """Stage the roster photos + enqueue the extraction job (no LLM here —
    the request thread only validates and writes files, then returns the
    job handle immediately)."""
    files = [p for p in (photos or []) if p and p.filename]
    if not files:
        raise HTTPException(422, "at least one photo required")
    if len(files) > MAX_ROSTER_PHOTOS:
        raise HTTPException(422, f"at most {MAX_ROSTER_PHOTOS} photos")
    staged = []
    for f in files:
        ext = (f.filename.rsplit(".", 1)[-1] or "").lower()
        if ext not in config.ALLOWED_IMAGE:
            raise HTTPException(422, f"unsupported image type '.{ext}'")
        data = await f.read()
        if len(data) > config.MAX_IMAGE_BYTES:
            raise HTTPException(422, f"photo '{f.filename}' too large")
        name = f"roster-{uuid.uuid4().hex}.{ext}"
        (config.UPLOAD_DIR / name).write_bytes(data)
        staged.append(name)

    # dedupe guard: one in-flight roster import per teacher
    o = db._owner()
    with db._LOCK:
        c = db._conn()
        q = ("SELECT COUNT(*) FROM jobs WHERE kind='roster_import' "
             "AND status IN ('queued','running')")
        a: list = []
        if o is not None:
            q += " AND owner_id=?"
            a.append(o)
        n = c.execute(q, a).fetchone()[0]
    if n:
        for name in staged:
            try:
                (config.UPLOAD_DIR / name).unlink(missing_ok=True)
            except OSError:
                pass
        raise HTTPException(409, "a roster import is already in progress")

    job_id = db.create_job(
        "roster_import",
        {"photo_names": staged,
         "class_code_hint": (class_code or "").strip(),
         "ui_language": assess._ui_language(ui_language)})
    job = db.job_get(job_id)
    return {"job_id": job_id, "job_status": job.get("status"),
            "job_kind": "roster_import",
            "photo_count": len(staged),
            "enqueued": True,
            "follow_url": f"/api/jobs/{job_id}/events"}


@router.get("/api/students/import-photos/{job_id}")
def import_roster_status(job_id: int):
    """Job status + the extracted roster draft (once done)."""
    j = db.job_get(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    if j.get("kind") != "roster_import":
        raise HTTPException(404, "job not found")
    draft = _roster_draft(j) if j.get("status") == "done" else None
    return {"job_id": job_id, "status": j.get("status"),
            "phase": j.get("phase"), "error": j.get("error"),
            "draft": draft,
            "photo_names": (j.get("payload") or {}).get("photo_names") or []}


@router.post("/api/students/import-photos/{job_id}/commit")
def import_roster_commit(job_id: int, payload: dict):
    """Commit the teacher-reviewed roster: upsert each row as a student.

    payload = {school_name, class_name, classroom (the code the rows get),
               students: [{first_name, last_name, include: bool}]}
    """
    j = db.job_get(job_id)
    if not j or j.get("kind") != "roster_import":
        raise HTTPException(404, "job not found")
    if j.get("status") != "done" or _roster_draft(j) is None:
        raise HTTPException(409, "extraction not finished yet")
    data = payload or {}
    classroom = (data.get("classroom") or "").strip()
    rows = data.get("students") or []
    created, updated, skipped = 0, 0, []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        if row.get("include") is False:
            continue
        first = str(row.get("first_name") or "").strip()
        last = str(row.get("last_name") or "").strip()
        name = f"{first} {last}".strip()
        if not name:
            skipped.append(f"row {i + 1}: empty name")
            continue
        # idempotent match on (name, classroom) so re-commits don't duplicate
        existing = None
        for s in db.list_students():
            if s["name"].lower() == name.lower() and \
                    (s.get("classroom") or "") == classroom:
                existing = s["id"]
                break
        if existing:
            db.update_student(existing, name=name, classroom=classroom)
            updated += 1
        else:
            db.create_student(name, classroom)
            created += 1
    # the roster sheet has served its purpose — drop the photos
    for name in (j.get("payload") or {}).get("photo_names") or []:
        try:
            (config.UPLOAD_DIR / name).unlink(missing_ok=True)
        except OSError:
            pass
    return {"job_id": job_id, "created": created, "updated": updated,
            "skipped": skipped, "classroom": classroom}
