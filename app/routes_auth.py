"""Auth routes: session login / registration / password management.

Extracted from main.py (2026-10-16 split).
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from . import auth
from . import db

router = APIRouter()


@router.get("/api/auth/me")
def auth_me(request: Request):
    """Who am I? {user, has_password, has_account}.

    has_account = at least one account exists on this deployment.
    has_password = whether MY account has a login password set.
    The login screen uses these to decide between "log in" /
    "first account, create one" / "account creation closed".
    """
    o = auth.current_owner()
    u = auth.get_user(o) if o is not None else None
    return {
        "user": auth._user_public(u),
        "has_password": bool(u and u.get("password_hash")),
        "has_account": auth.count_users() > 0,
    }

@router.post("/api/auth/register")
def auth_register(payload: dict, request: Request, response: Response):
    """Create an account — open only while NO account exists yet
    (first-boot flow); 403 once the first account exists, so nobody can
    squat a login on a running deployment."""
    if auth.count_users() > 0:
        raise HTTPException(403, "account creation is closed — the first "
                                 "account already exists")
    try:
        uid = auth.create_user(payload.get("username", ""),
                               payload.get("password", ""))
    except ValueError as e:
        raise HTTPException(422, str(e))
    # First account on this deployment: the gate just attached the
    # operator's identity to the whole legacy dataset (students,
    # assignments, submissions, analyses, non-preset rubrics, jobs) —
    # the owner backfill targets user #1, which is this very account.
    # Idempotent (only NULL-owner rows are ever touched).
    db._migrate_multiuser()
    tok = auth.create_session(uid)
    auth.set_session_cookie(response, tok)
    return {"id": uid, "username": auth.get_user(uid)["username"]}

@router.post("/api/auth/login")
def auth_login(payload: dict, response: Response):
    user = auth.user_by_username(payload.get("username", ""))
    if not user or not auth.verify_password(
            payload.get("password", ""), user.get("password_hash")):
        raise HTTPException(401, "invalid credentials")
    tok = auth.create_session(user["id"])
    auth.set_session_cookie(response, tok)
    return auth._user_public(user)

@router.post("/api/auth/set-password")
def auth_set_password(payload: dict):
    """Change the caller's password (current one required — it's a change,
    not a takeover)."""
    o = auth.current_owner()
    if o is None:
        raise HTTPException(401, "authentication required")
    u = auth.get_user(o)
    if not u or not u.get("password_hash"):
        raise HTTPException(401, "authentication required")
    pw = (payload.get("password") or "").strip()
    if len(pw) < 8:
        raise HTTPException(422, "password must be at least 8 characters")
    cur = (payload.get("current") or "").strip()
    if not auth.verify_password(cur, u["password_hash"]):
        raise HTTPException(401, "current password is incorrect")
    with db._LOCK:
        db._conn().execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (auth.hash_password(pw), o))
        db._conn().commit()
    return {"password_set": True}

@router.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    tok = request.cookies.get(auth.SESSION_COOKIE, "")
    if tok:
        auth.delete_session(tok)
    auth.clear_session_cookie(response)
    return {"logged_out": True}

