"""Analysis routes: list/get/delete, teacher matrix update, transcript
correction, passage links, submission get/delete.

Extracted from main.py (2026-10-16 split).
"""
import json

from fastapi import APIRouter, HTTPException

from . import db
from .rubrics import compute_attestation
from .config import _SET_NULL

router = APIRouter()


@router.get("/api/analyses")
def list_analyses(student_id: int = 0, limit: int = 200,
                 classroom_prefix: str = "", title: str = "",
                 assignment_id: int = 0):
    return [db.enrich_analysis(a) for a in
            db.list_submissions(student_id=student_id or None, limit=limit,
                                 classroom_prefix=classroom_prefix,
                                 title=title,
                                 assignment_id=assignment_id or None)]

@router.get("/api/analyses/{analysis_id}")
def get_analysis(analysis_id: int):
    a = db.get_analysis(analysis_id)
    if not a:
        raise HTTPException(404, "analysis not found")
    return db.enrich_analysis(a)

@router.delete("/api/analyses/{analysis_id}")
def delete_analysis(analysis_id: int):
    # (2026-10-14) owner-scoped: get_analysis() already 404s a foreign
    # analysis for the caller, so only delete rows the caller owns.
    a = db.get_analysis(analysis_id)
    if not a:
        raise HTTPException(404, "analysis not found")
    with db._LOCK:
        db._conn().execute("DELETE FROM analyses WHERE id=?", (analysis_id,))
        db._conn().commit()
    return {"deleted": analysis_id}

@router.put("/api/analyses/{analysis_id}")
def update_analysis_teacher(analysis_id: int, body: dict):
    """Teacher's counter-proposal: save edited per-criterion levels, the
    hand-set /20 note, and mark the attestation as validated.

    body: {
      "levels": {criterion_name: "A1".."C2"|"", ...}  optional,
      "note20": {"modalite","classe","track","note"} | null   optional,
      "validate": true | "revert"   optional
    }
    `validate` writes `validated_at` (and snapshots the original AI matrix
    into ai_matrix_json on the FIRST validation only, so "revert" can go
    back to the AI's proposal); "revert" restores the AI matrix and clears
    the validation. Levels are stored INTO matrix_json (rubric_mapping
    suggested_level) so every read path recomputes the attestation from
    the teacher's levels. The /120 score stays the single source of truth
    — the /20 note is reference-only (never graded from).
    """
    a = db.get_analysis(analysis_id)
    if not a:
        raise HTTPException(404, "analysis not found")
    body = body or {}
    sets: dict = {}
    levels = body.get("levels")
    if isinstance(levels, dict):
        m = a.get("matrix_json")
        data = json.loads(m) if m else None
        if not isinstance(data, dict) or not isinstance(data.get("rubric_mapping"), list):
            raise HTTPException(400, "analysis has no editable rubric mapping")
        allowed = set()
        r = db.get_rubric(a.get("rubric_id") or "")
        if r:
            allowed = {c["name"] for c in r.get("criteria", [])}
        for entry in data["rubric_mapping"]:
            name = entry.get("criterion")
            if name in levels and (not allowed or name in allowed):
                lvl = str(levels.get(name) or "").strip().upper()
                if lvl and lvl not in ("A1", "A2", "B1", "B2", "C1", "C2"):
                    raise HTTPException(422, f"invalid level for criterion {name!r}")
                entry["suggested_level"] = lvl
        sets["matrix_json"] = json.dumps(data, ensure_ascii=False)
        # For attestation rubrics, the stored overall level is the
        # attestation level derived from the TEACHER's levels (this is
        # what the history list/detail shows). Non-attestation rubrics
        # keep the AI's overall_level.
        if r and r.get("attestation"):
            att = compute_attestation(r, data.get("rubric_mapping", []))
            if att:
                sets["overall_level"] = att["attestation"]
    # note20: key ABSENT = no change; null = clear; dict = save.
    if "note20" in body:
        note20 = body.get("note20")
        if note20 is None:
            sets["note20_json"] = _SET_NULL
        else:
            if not isinstance(note20, dict):
                raise HTTPException(422, "note20 must be an object or null")
            try:
                note = float(note20.get("note"))
            except (TypeError, ValueError):
                raise HTTPException(422, "note20.note must be a number")
            if not (0 <= note <= 45):
                raise HTTPException(422, "note20.note out of range 0–45")
            sets["note20_json"] = json.dumps({
                "modalite": note20.get("modalite") or "",
                "classe": note20.get("classe") or "",
                "track": note20.get("track") or "",
                "note": note,
            }, ensure_ascii=False)
    val = body.get("validate")
    if val in (True, "yes", "true"):
        sets["validated_at"] = db.now_iso()
        if not a.get("ai_matrix_json"):
            # first validation: keep the AI's original matrix for "revert"
            sets["ai_matrix_json"] = a.get("matrix_json")
    elif val in ("revert", False):
        if not a.get("ai_matrix_json"):
            raise HTTPException(409, "no AI snapshot to revert to yet")
        sets["matrix_json"] = a["ai_matrix_json"]
        sets["validated_at"] = _SET_NULL  # type: ignore[assignment]
    if not sets:
        return db.enrich_analysis(a)
    with db._LOCK:
        c = db._conn()
        col_exprs = []
        args = []
        for k, v in sets.items():
            if v is _SET_NULL:
                col_exprs.append(f"{k}=NULL")
            else:
                col_exprs.append(f"{k}=?")
                args.append(v)
        c.execute("UPDATE analyses SET " + ", ".join(col_exprs)
                  + " WHERE id=?", args + [analysis_id])
        c.commit()
    return db.enrich_analysis(db.get_analysis(analysis_id))

@router.post("/api/analyses/{analysis_id}/transcript-correction")
def save_transcript_correction(analysis_id: int, body: dict):
    """Save the teacher's corrected transcript (the ASR misheard some words).

    body: {
      "segments": [{"start": 0.0, "end": 3.2, "text": "…"}, ...],  // REQUIRED
      "mode": "original" | "corrected"   // which version the evaluator's
                                          // AI should use next (default:
                                          // "corrected" when saving)
    }
    Both versions are kept: the original stays in transcript_json, the
    correction in transcript_correction_json. `mode` switches which one the
    run-ai prompt receives (and which one the UI shows as active). The
    original Whisper timestamps/fluency metrics are kept (they are the
    audio's ground truth); only the text is replaced in the prompt.
    """
    a = db.get_analysis(analysis_id)
    if not a:
        raise HTTPException(404, "analysis not found")
    sub = db.get_submission(a["submission_id"])
    if not sub or sub.get("kind") != "oral":
        raise HTTPException(422, "transcript correction requires an oral analysis")
    body = body or {}
    segs = body.get("segments")
    if not isinstance(segs, list) or not segs:
        raise HTTPException(422, "segments list required")
    clean = []
    for s in segs:
        try:
            clean.append({"start": round(float(s.get("start", 0)), 2),
                          "end": round(float(s.get("end", 0)), 2),
                          "text": str(s.get("text", "")).strip()})
        except (TypeError, ValueError):
            raise HTTPException(422, "bad segment")
    mode = str(body.get("mode") or "corrected").strip().lower()
    if mode not in ("original", "corrected"):
        raise HTTPException(422, "mode must be original|corrected")
    db.update_analysis(
        analysis_id,
        transcript_correction_json=json.dumps(
            {"segments": clean, "updated_at": db.now_iso()},
            ensure_ascii=False),
        transcript_mode=mode,
    )
    return {"analysis_id": analysis_id, "transcript_mode": mode,
            "segments": clean}

@router.delete("/api/analyses/{analysis_id}/transcript-correction")
def clear_transcript_correction(analysis_id: int):
    """Remove the teacher's correction (the original ASR transcript becomes
    the sole source again)."""
    a = db.get_analysis(analysis_id)
    if not a:
        raise HTTPException(404, "analysis not found")
    db.update_analysis(
        analysis_id,
        transcript_correction_json=db._CLEAR,
        transcript_mode="original",
    )
    return {"analysis_id": analysis_id, "cleared": True}

@router.get("/api/analyses/{analysis_id}/passage-links")
def list_passage_links(analysis_id: int):
    a = db.get_analysis(analysis_id)
    if not a:
        raise HTTPException(404, "analysis not found")
    return {"links": db.passage_links(analysis_id)}

@router.post("/api/analyses/{analysis_id}/passage-links")
def add_passage_link(analysis_id: int, body: dict):
    """Link an annotated passage to a criterion: body {annotation_id, criterion}."""
    a = db.get_analysis(analysis_id)
    if not a:
        raise HTTPException(404, "analysis not found")
    body = body or {}
    ann_id = body.get("annotation_id")
    criterion = str(body.get("criterion") or "").strip()
    if not isinstance(ann_id, int) or not criterion:
        raise HTTPException(422, "annotation_id and criterion required")
    ann = db.get_annotation(ann_id)
    if not ann or ann["submission_id"] != a["submission_id"]:
        raise HTTPException(422, "annotation not found for this analysis")
    # criterion must belong to the analysis's rubric
    rubric = db.get_rubric(a.get("rubric_id") or "")
    names = {c["name"] for c in rubric["criteria"]} if rubric else set()
    if names and criterion not in names:
        raise HTTPException(422, f"unknown criterion '{criterion}'")
    link_id = db.link_passage(analysis_id, ann_id, criterion)
    return {"link_id": link_id, "linked": True}

@router.delete("/api/analyses/{analysis_id}/passage-links")
def remove_passage_link(analysis_id: int, annotation_id: int,
                        criterion: str = ""):
    a = db.get_analysis(analysis_id)
    if not a:
        raise HTTPException(404, "analysis not found")
    ok = db.unlink_passage(analysis_id, annotation_id, criterion)
    return {"deleted": ok}

@router.get("/api/submissions/{sub_id}")
def get_submission(sub_id: int):
    s = db.get_submission(sub_id)
    if not s:
        raise HTTPException(404, "submission not found")
    return s

@router.delete("/api/submissions/{sub_id}")
def delete_submission(sub_id: int):
    db.delete_submission(sub_id)
    return {"deleted": sub_id}

