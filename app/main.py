"""BabelGrade - FastAPI application.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8090

The route handlers live in app/routes_*.py modules (2026-10-16 split from a
single 1700-line create_app). This module only wires the app together:
lifespan, auth gate, CORS, DB init + seed, router inclusion, static mounts.
Shared helpers: app/media.py (uploads/staging), app/config.py (paths+limits),
app/docs_catalog.py (in-app docs index).
"""
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import auth, db, jobs
from . import (routes_admin, routes_analyses, routes_analyze,
               routes_annotate, routes_assignments, routes_auth, routes_docs,
               routes_files, routes_health, routes_jobs, routes_rubrics,
               routes_roster, routes_students)
from .config import STATIC_DIR
from .docs_catalog import DOCS_DIR
from .media import _migrate_default_titles, seed_rubrics


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # First-boot: create the initial account when no user exists yet
        # (login from BABELGRADE_INITIAL_LOGIN env, password from
        # BABELGRADE_INITIAL_PASSWORD; without a password the account has none and
        # login stays 401 — the operator sets it via the in-app flow or by
        # re-running with the env var). The owner backfill in
        # db._migrate_multiuser already ran in init_db; it attaches legacy
        # rows to user #1, which is exactly this account.
        import logging
        if auth.bootstrap_admin():
            logging.getLogger("elt.auth").info(
                "first boot: created initial account (%s)",
                os.environ.get("BABELGRADE_INITIAL_LOGIN", "tibo"))
            # The owner backfill already ran once at init_db time — but on a
            # true first boot there was no account yet, so it was a no-op.
            # Re-run it now that the initial account exists: attach every
            # legacy row (students, assignments, submissions, analyses,
            # annotations, jobs, non-preset rubrics) to it. Idempotent.
            db._migrate_multiuser()
        jobs.start_workers()
        yield
        jobs.stop_workers()

    app = FastAPI(title="BabelGrade", version="1.0",
                 lifespan=lifespan,
                 # Global auth gate: every /api/* route (except PUBLIC_PATHS
                 # + static) requires the session cookie. Runs in the
                 # endpoint's task, so owner_var propagates to run_in_
                 # threadpool / to_thread db calls inside the handler.
                 dependencies=[Depends(auth.auth_dependency)])
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])
    db.init_db()
    seed_rubrics()
    _migrate_default_titles()   # point 8: smart titles for legacy rows

    app.include_router(routes_health.router)
    app.include_router(routes_auth.router)
    app.include_router(routes_rubrics.router)
    app.include_router(routes_roster.router)
    app.include_router(routes_students.router)
    app.include_router(routes_assignments.router)
    app.include_router(routes_admin.router)
    app.include_router(routes_analyze.router)
    # NOTE (2026-10-17): routes_annotate MUST be mounted before
    # routes_analyses — FastAPI matches in registration order, so
    # GET /api/submissions/{sub_id}.ocr has to be tried BEFORE
    # GET /api/submissions/{sub_id} can swallow the ".ocr" suffix and
    # 422 on the int parse (the Annoter view loads its OCR through that
    # dotted route).
    app.include_router(routes_annotate.router)
    app.include_router(routes_jobs.router)
    app.include_router(routes_analyses.router)
    app.include_router(routes_files.router)
    app.include_router(routes_docs.router)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    if DOCS_DIR.exists():
        app.mount("/docs-static", StaticFiles(directory=str(DOCS_DIR)), name="docs-static")
    return app


app = create_app()
