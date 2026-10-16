"""Rubric CRUD + official /20 conversion-table routes.

Extracted from main.py (2026-10-16 split).
"""
from fastapi import APIRouter, HTTPException

from . import db
from .rubrics import note_bands
from .rubrics import NOTE_THRESHOLDS, NOTE_VISE
import uuid

router = APIRouter()


@router.get("/api/rubrics")
def list_rubrics(mode: str = ""):
    return db.list_rubrics(mode or None)

@router.get("/api/rubrics/{rubric_id}")
def get_rubric(rubric_id: str):
    r = db.get_rubric(rubric_id)
    if not r:
        raise HTTPException(404, "Rubric not found")
    return r

@router.post("/api/rubrics")
def create_rubric(payload: dict):
    pid = payload.get("id") or f"custom-{uuid.uuid4().hex[:8]}"
    payload["id"] = pid
    payload["name"] = payload.get("name") or "Untitled rubric"
    payload["mode"] = payload.get("mode") or "written"
    if payload["mode"] not in ("written", "oral"):
        raise HTTPException(422, "mode must be 'written' or 'oral'")
    payload["criteria"] = payload.get("criteria") or []
    if not payload["criteria"]:
        raise HTTPException(422, "at least one criterion required")
    db.upsert_rubric(payload)
    return db.get_rubric(pid)

@router.delete("/api/rubrics/{rubric_id}")
def delete_rubric(rubric_id: str):
    r = db.get_rubric(rubric_id)
    if not r:
        raise HTTPException(404, "Rubric not found")
    if r.get("is_preset"):
        raise HTTPException(400, "Preset rubrics cannot be deleted")
    db.delete_rubric(rubric_id)
    return {"deleted": rubric_id}

@router.get("/api/note-bands")
def get_note_bands(modalite: str = "", classe: str = "", track: str = ""):
    """Official conversion-table reference (note sur 20 -> attestation).

    Bands are in "points score" units (comprehension /90, expression /120),
    each mapping to a CEFR level; the tables also print a "Note sur 20"
    reference row. The app does NOT grade off these — they are a teacher
    reference to cross-check against the official document. `verified`
    marks bands whose level label is explicitly printed in the document.
    """
    if not (modalite and classe and track):
        raise HTTPException(422, "modalite, classe and track are required")
    bands = note_bands(modalite, classe, track)
    return {"modalite": modalite, "classe": classe, "track": track,
            "bands": bands,
            "vise": NOTE_VISE.get((modalite, classe, track), ""),
            "thresholds": NOTE_THRESHOLDS.get(modalite, ""),
            "verified": all(b.get("verified", False) for b in bands) if bands else False,
            "note": "Référence issue des tableaux de conversion officiels "
                    "(note sur 20 / points score). L'attestation de l'app est "
                    "calculée sur le score /120, pas sur ces bandes."}

