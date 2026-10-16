"""Admin routes: database reset (type-RESET-confirmed).

Extracted from main.py (2026-10-16 split).
"""
from fastapi import APIRouter, HTTPException

from . import auth, db
from .media import seed_rubrics
from . import config

router = APIRouter()


@router.post("/api/admin/reset-database")
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
        config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        for f in config.UPLOAD_DIR.iterdir():
            if f.is_file():
                f.unlink()
                removed_files += 1
    return {
        "reset": True,
        "rubrics_reseded": len(db.list_rubrics()),
        "files_removed": removed_files,
        "students": len(db.list_students()),
    }

