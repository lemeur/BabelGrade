"""Media file serving route (/api/files/{path}) with ownership enforcement.

Extracted from main.py (2026-10-16 split).
"""
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from . import auth, db
from . import config
from .media import _ext, _mime_for, _normalize_orientation

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


@router.post("/api/media/normalize")
async def normalize_photo(file: UploadFile = File(...)):
    """Run the upload-time orientation fix (EXIF transpose + deterministic
    deskew, ``media._normalize_orientation``) on an image and return the
    result so the CLIENT can preview — and upload — exactly what the
    backend will persist (the stored/OCR/LLM copy).

    Called by the photo mode-panels at selection time: the thumbnail shows
    the normalized photo immediately instead of the raw camera pixels.
    The function NEVER raises and returns the original bytes unchanged
    when no correction applies — the response carries ``changed`` so the
    client can skip the blob swap in that case.
    """
    from .config import MAX_IMAGE_BYTES
    ext = _ext(file.filename or "")
    if ext not in ("jpg", "jpeg", "png", "webp"):
        raise HTTPException(422, f"unsupported image type '.{ext}'")
    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(422, "image too large")
    out = _normalize_orientation(data, ext)
    changed = out is not data
    return Response(content=out, media_type=_mime_for(ext),
                    headers={"X-Changed": "1" if changed else "0"})

