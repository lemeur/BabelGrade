"""Job-queue routes: counts, list, get, cancel, settings, SSE events.

Extracted from main.py (2026-10-16 split). The live SSE generator is imported
from routes_analyze (the module that owns the shared _job_events helper).
"""
from fastapi import APIRouter, HTTPException

from . import db, jobs
from .routes_analyze import _job_events

router = APIRouter()


@router.get("/api/jobs/counts")
def job_counts():
    return {"counts": db.job_counts(), "max_workers": jobs.max_workers()}

@router.get("/api/jobs")
def list_jobs(status: str = "", limit: int = 100):
    """Job queue + history. status: queued|running|done|error|cancelled|''."""
    return {"jobs": db.job_list(status=status, limit=min(max(limit, 1), 500)),
            "counts": db.job_counts(),
            "max_workers": jobs.max_workers()}

@router.get("/api/jobs/{job_id}")
def get_job(job_id: int):
    j = db.job_get(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    out = {k: j.get(k) for k in ("id", "kind", "status", "phase",
                                 "submission_id", "analysis_id",
                                 "created_at", "started_at", "finished_at",
                                 "elapsed_s", "error", "cancel_flag")}
    out["job_id"] = j["id"]
    out["payload"] = j.get("payload")
    # V5-C3: queue position (queued jobs only)
    out["queue_pos"] = (db.job_queue_positions().get(job_id)
                        if j.get("status") == "queued" else None)
    return out

@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    """Cancel a queued job, or signal a running job to stop after its
    current step."""
    j = db.job_get(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    if j["status"] not in ("queued", "running"):
        raise HTTPException(409, f"job is {j['status']}, not cancellable")
    db.job_update(job_id, cancel_flag=1)
    if j["status"] == "queued":
        db.job_update(job_id, status="cancelled", finished=True)
    return {"job_id": job_id, "cancelled": True}

@router.post("/api/jobs/settings")
def set_job_settings(payload: dict):
    """Set the number of simultaneous workers (1-4, persisted)."""
    try:
        v = int((payload or {}).get("max_workers"))
    except (TypeError, ValueError):
        raise HTTPException(422, "max_workers must be an integer")
    if not (1 <= v <= jobs.MAX_WORKERS_CAP):
        raise HTTPException(422, f"max_workers must be 1-{jobs.MAX_WORKERS_CAP}")
    db.set_setting("max_workers", str(v))
    return {"max_workers": jobs.max_workers()}

@router.get("/api/jobs/{job_id}/events")
async def job_events(job_id: int):
    return await _job_events(job_id)


