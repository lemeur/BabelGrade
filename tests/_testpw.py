"""Live-server test credentials — the ONLY place they are exposed to tests.

The real test login/password live in ``tests/.credentials`` (gitignored) or in
the environment. No test file or doc hardcodes the literal password, so it never
enters the repo working tree or git history.
"""
import os
from pathlib import Path

_CRED = Path(__file__).resolve().parent / ".credentials"


def _read_cred_file():
    user = pw = None
    if _CRED.exists():
        for line in _CRED.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("BABELGRADE_TEST_USERNAME="):
                user = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("BABELGRADE_TEST_PASSWORD="):
                pw = line.split("=", 1)[1].strip().strip('"').strip("'")
    return user, pw


_u, _p = _read_cred_file()
USERNAME = os.environ.get("BABELGRADE_TEST_USERNAME", _u or "tibo")
PASSWORD = os.environ.get("BABELGRADE_TEST_PASSWORD", _p or "")


def pw():
    """Return the live-server test password, or fail with setup help."""
    if not PASSWORD:
        raise SystemExit(
            "BABELGRADE_TEST_PASSWORD is empty. Fill it in tests/.credentials "
            "(gitignored) or export BABELGRADE_TEST_PASSWORD, then re-run."
        )
    return PASSWORD
