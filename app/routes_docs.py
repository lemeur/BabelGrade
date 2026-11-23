"""SPA index route.

Extracted from main.py (2026-10-16 split). The in-app Docs view was removed
in 2026-11 — documentation now lives on the project's GitHub Pages site
(lemeur.github.io/BabelGrade, built into site/ by scripts/build_site.py).
"""
from fastapi import APIRouter
from fastapi.responses import FileResponse

from .config import STATIC_DIR

router = APIRouter()


@router.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))

