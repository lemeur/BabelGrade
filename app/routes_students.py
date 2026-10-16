"""Student roster routes: CRUD, per-student stats, classroom purge, CSV.

Extracted from main.py (2026-10-16 split).
"""
from fastapi import APIRouter, HTTPException, Query

from . import db
from fastapi import File, UploadFile
from fastapi.responses import Response
import csv as _csv
import io

router = APIRouter()


@router.get("/api/students")
def list_students():
    return db.list_students()

@router.post("/api/students")
def create_student(payload: dict):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "student name required")
    sid = db.create_student(name, payload.get("classroom") or "")
    return db.get_student(sid)

@router.put("/api/students/{student_id}")
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

@router.get("/api/students/{student_id:int}/stats")
def student_stats_endpoint(student_id: int):
    """Chronological level evolution of one student (per-student "Stats"
    time chart, 2026-10-12): every evaluated submission as a point in
    time, global series + per evaluation type (comprehension/expression
    × written/oral). Only analyses with a usable level count."""
    stats = db.stats_for_student(student_id)
    if stats is None:
        raise HTTPException(404, "Student not found")
    return stats

@router.delete("/api/students/{student_id}")
def delete_student(student_id: int,
                   cascade: bool = Query(False, description=
                    "Also delete the student's submissions + analyses "
                    "(and their stored files). Default keeps submissions.")):
    res = db.delete_student(student_id, cascade=cascade)
    if res.get("not_found"):
        raise HTTPException(404, "student not found")
    return res

@router.get("/api/students/purge")
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

@router.delete("/api/students")
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

@router.get("/api/students/csv")
def export_students_csv():
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

@router.post("/api/students/csv")
def import_students_csv(file: UploadFile = File(...)):
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

