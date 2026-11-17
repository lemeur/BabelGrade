"""pytest bootstrap: make the project root importable no matter where
pytest is launched from (``pytest tests/`` from the repo root, from
``-p no:cacheprovider`` CI, or from a venv activated elsewhere).

The test modules themselves already set up ``sys.path`` when run as
standalone scripts; this is the belt-and-suspenders for pytest, which
imports them as top-level modules.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)
