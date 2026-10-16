"""Multi-user authentication (2026-10-13).

Local login/password auth. Every app object (students, assignments,
submissions, analyses, annotations, jobs, custom rubrics) carries an
``owner_id``; the authenticated user is propagated through a contextvar
(``owner_var``) that the db layer reads to scope queries. Preset rubrics
(official LVA/LVB grids) have owner_id = NULL and are shared by everyone.

* Passwords: PBKDF2-HMAC-SHA256 (hashlib, stdlib — no extra deps).
* Sessions: random 32-byte tokens stored in the ``sessions`` table, sent as
  an HttpOnly SameSite=Lax cookie (``elt_session``), 30-day lifetime.
"""
from __future__ import annotations

import contextvars
import hashlib
import hmac
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response

SESSION_COOKIE = "elt_session"
SESSION_DAYS = 30
_PBKDF2_ITERATIONS = 600_000
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,30}$")
_MIN_PASSWORD = 8

# contextvar: the authenticated user's id for the current request/job.
# main.py's middleware sets it from the session cookie; the job worker sets
# it from the job's owner_id; db.py reads it to scope every query.
owner_var: contextvars.ContextVar = contextvars.ContextVar("elt_owner", default=None)


def current_owner() -> int | None:
    """Owner id of the current request (None = unauthenticated/system)."""
    return owner_var.get()


# --------------------------------------------------------------------- hashing
def _pepper() -> str:
    # Static application pepper layered on top of the per-password salt so a
    # DB leak alone is not enough to replay the hash parameters.
    return "elt-assessor-2026"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                             salt, _PBKDF2_ITERATIONS,
                             dklen=32)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not isinstance(stored, str):
        return False
    try:
        scheme, iters, salt_hex, hash_hex = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 bytes.fromhex(salt_hex), int(iters), dklen=32)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# --------------------------------------------------------------------- users / sessions
def _user_public(u: dict | None) -> dict | None:
    if not u:
        return None
    return {"id": u["id"], "username": u["username"],
            "created_at": u.get("created_at")}


def create_user(username: str, password: str) -> int:
    from . import db
    username = (username or "").strip()
    if not _USERNAME_RE.match(username):
        raise ValueError("username must be 3-30 chars: letters, digits, . _ -")
    if len(password or "") < _MIN_PASSWORD:
        raise ValueError(f"password must be at least {_MIN_PASSWORD} characters")
    with db._LOCK:
        c = db._conn()
        low = username.lower()
        cur = c.execute(
            "INSERT INTO users (username, username_lower, password_hash, created_at) "
            "VALUES (?,?,?,?)",
            (username, low, hash_password(password), db.now_iso()))
        c.commit()
        return int(cur.lastrowid)


def get_user(user_id: int) -> dict | None:
    from . import db
    with db._LOCK:
        row = db._conn().execute(
            "SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def user_by_username(username: str) -> dict | None:
    from . import db
    with db._LOCK:
        row = db._conn().execute(
            "SELECT * FROM users WHERE username_lower=?",
            ((username or "").strip().lower(),)).fetchone()
    return dict(row) if row else None


def count_users() -> int:
    from . import db
    with db._LOCK:
        return db._conn().execute("SELECT COUNT(*) FROM users").fetchone()[0]


def user_by_session_token(token: str) -> dict | None:
    """Resolve a session cookie token to its user, refreshing its lifetime.
    Returns None for unknown/expired tokens (and prunes them)."""
    from . import db
    if not token:
        return None
    now = db.now_iso()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SESSION_DAYS)
              ).isoformat()
    with db._LOCK:
        c = db._conn()
        row = c.execute(
            "SELECT * FROM sessions WHERE token=?", (token,)).fetchone()
        if not row:
            return None
        if row["created_at"] < cutoff:
            c.execute("DELETE FROM sessions WHERE token=?", (token,))
            c.commit()
            return None
        c.execute("DELETE FROM sessions WHERE created_at < ?", (cutoff,))
        c.execute("UPDATE sessions SET created_at=? WHERE token=?", (now, token))
        c.commit()
        user = c.execute("SELECT * FROM users WHERE id=?",
                         (row["user_id"],)).fetchone()
    return dict(user) if user else None


def create_session(user_id: int) -> str:
    from . import db
    token = secrets.token_urlsafe(32)
    with db._LOCK:
        c = db._conn()
        c.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)",
                  (token, user_id, db.now_iso()))
        c.commit()
    return token


def delete_session(token: str) -> None:
    from . import db
    with db._LOCK:
        c = db._conn()
        c.execute("DELETE FROM sessions WHERE token=?", (token,))
        c.commit()


def first_user() -> dict | None:
    from . import db
    with db._LOCK:
        row = db._conn().execute(
            "SELECT * FROM users ORDER BY id LIMIT 1").fetchone()
    return dict(row) if row else None


def bootstrap_admin() -> bool:
    """First-boot helper: create the initial account when no user exists.

    Login comes from the ``ELT_INITIAL_LOGIN`` env var (default "tibo");
    password from ``ELT_INITIAL_PASSWORD``. Without a password the account is
    NOT created (create_user rejects it) — the operator instead creates the
    first account through the in-app "Create account" gate, which runs the
    same owner backfill. We never invent credentials silently.
    Returns True when a user was created here.
    """
    if count_users() > 0:
        return False
    username = os.environ.get("ELT_INITIAL_LOGIN", "tibo")
    password = os.environ.get("ELT_INITIAL_PASSWORD", "")
    try:
        create_user(username, password)
    except ValueError:
        return False
    return True


# --------------------------------------------------------------------- auth
PUBLIC_PATHS = {"/api/health", "/api/auth/login", "/api/auth/register",
                "/api/auth/me"}


def _is_public(request: Request) -> bool:
    path = request.url.path
    return (path in PUBLIC_PATHS or path == "/"
            or path.startswith("/static") or path.startswith("/docs-static"))


async def auth_dependency(request: Request) -> int | None:
    """Global FastAPI dependency (async → runs in the endpoint's task, so the
    owner_var set here is visible to the handler AND to its
    run_in_threadpool / to_thread db calls).

    * authenticated  → sets ``owner_var`` and returns the user
    * public route   → returns None (owner stays unset: system/unscoped)
    * anything else  → 401
    """
    from fastapi import HTTPException
    user = user_by_session_token(request.cookies.get(SESSION_COOKIE, ""))
    if user:
        owner_var.set(user["id"])
        return user["id"]
    if _is_public(request):
        return None
    raise HTTPException(status_code=401, detail="authentication required")


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=SESSION_DAYS * 86400,
        httponly=True, samesite="lax", path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
