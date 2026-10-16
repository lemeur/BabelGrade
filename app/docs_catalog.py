"""In-app Docs view: which markdown documents the UI can render.

P1.4: two-section docs view — "user" (the user guide) is the default;
"dev" (async-jobs / readme / ux-audit) is isolated behind a Dev sub-tab.
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = _ROOT / "docs"

DOCS_INDEX = {
    "userguide": {"path": DOCS_DIR / "userguide.md", "category": "user"},
    "async-jobs": {"path": DOCS_DIR / "async-jobs.md", "category": "dev"},
    "ux-audit": {"path": _ROOT / "ux-audit1.md", "category": "dev"},
    "readme": {"path": _ROOT / "README.md", "category": "dev"},
}


def doc_path(slug: str):
    meta = DOCS_INDEX.get(slug)
    return meta["path"] if meta and meta["path"].exists() else None
