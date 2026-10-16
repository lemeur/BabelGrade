"""In-app Docs routes + SPA index.

Extracted from main.py (2026-10-16 split).
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .config import STATIC_DIR
from . import docs_catalog

router = APIRouter()


@router.get("/api/docs")
def list_docs():
    out = []
    for slug, meta in docs_catalog.DOCS_INDEX.items():
        if meta["path"].exists():
            out.append({"slug": slug, "exists": True,
                        "category": meta["category"],
                        "bytes": meta["path"].stat().st_size})
    return {"docs": out}

@router.get("/api/docs/{slug}")
def get_doc(slug: str):
    meta = docs_catalog.DOCS_INDEX.get(slug)
    if not meta or not meta["path"].exists():
        raise HTTPException(404, "document not found")
    return {"slug": slug, "category": meta["category"],
            "markdown": meta["path"].read_text(encoding="utf-8")}

@router.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))

