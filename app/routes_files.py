"""Media file serving route (/api/files/{path}) with ownership enforcement.

Extracted from main.py (2026-10-16 split).
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from . import auth, db
from . import config

router = APIRouter()


@router.get("/api/files/{path:path}")
def get_file(path: str):
    p = (config.UPLOAD_DIR / path).resolve()
    if not str(p).startswith(str(config.UPLOAD_DIR.resolve())) or not p.exists():
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

