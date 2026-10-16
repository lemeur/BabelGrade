"""Stats aggregation views (2026-10-16 split out of app/db.py — P2.7).

Two read-side aggregation functions:
- `stats_for_assignment` (assignment 📊 stats view, per-class gaussian bars
  + criterion rows, plus the per-evaluation `evaluations_detail` consumed
  by the "Avis IA" class-insight job kind "stats_ai")
- `stats_for_student` (per-student 📈 level-evolution time chart, L/R/S/W
  type codes)

They only READ (owner-scoped, via db._owner) and reuse db helpers
(get_assignment / get_student / get_rubric / _LOCK / _conn); db.py
re-exports both names so every existing `db.stats_*` call site keeps
working (single source of truth stays here).
"""
import statistics

from . import db
from .rubrics import CEFR_ORDER, LEVEL_POINTS, compute_attestation, normalize_cefr

import json as _json


def stats_for_assignment(assignment_id: int) -> dict | None:
    """Aggregate the evaluations made on one assignment.

    An "evaluation" is one analysis row linked (via its submission) to the
    assignment, with a usable result: a CEFR-levelable overall_level OR a
    filled attestation matrix. Skeletons (no levels anywhere) are counted in
    `evaluations_requested` but excluded from every statistic.

    Returns {assignment_id, evaluations, evaluations_requested,
             rubrics[{id,name}], levels{A1..C2:'' counts, global},
             by_class: [{classroom, students[], levels_counts{},
             overall{level counts + mean/median/sigma/min/max/n on the
             /120 point scale}, criterion{<name>: same shape per criterion}}]
             + evaluations_detail (per-evaluation feed for stats-ai)}
    or None when the assignment does not exist.
    """
    if not db.get_assignment(assignment_id):
        return None
    o = db._owner()
    own = " AND s.owner_id=?" if o is not None else ""
    q = ("SELECT a.id, a.rubric_id, a.overall_level, a.matrix_json, a.feedback, "
         "a.ai_at, s.student_id, st.name AS student_name, st.classroom "
         "FROM analyses a "
         "JOIN submissions s ON s.id=a.submission_id "
         "LEFT JOIN students st ON st.id=s.student_id "
         f"WHERE s.assignment_id=?{own}")
    with db._LOCK:
        rows = [dict(r) for r in db._conn().execute(
            q, (assignment_id,) + ((o,) if o is not None else ())).fetchall()]

    requested = len(rows)
    rubrics_seen: dict[str, str] = {}
    usable = []
    for r in rows:
        r["levels"] = {}
        r["crit_levels"] = {}
        try:
            mapping = (_json.loads(r["matrix_json"]) or {}).get("rubric_mapping", []) \
                if r.get("matrix_json") else []
        except Exception:
            mapping = []
        for m in mapping:
            name = (m or {}).get("criterion")
            if name:
                r["crit_levels"][name] = normalize_cefr(
                    (m or {}).get("suggested_level"))
        r["overall_norm"] = normalize_cefr(r.get("overall_level"))
        has_level = r["overall_norm"] is not None or any(r["crit_levels"].values())
        if has_level:
            usable.append(r)
            if r.get("rubric_id") and r["rubric_id"] not in rubrics_seen:
                rub = db.get_rubric(r["rubric_id"])
                rubrics_seen[r["rubric_id"]] = (rub or {}).get("name", r["rubric_id"])

    def moments(vals):
        out = {}
        if not vals:
            return out
        out["n"] = len(vals)
        out["mean"] = round(statistics.mean(vals), 2)
        out["median"] = statistics.median(vals)
        out["sigma"] = round(statistics.pstdev(vals), 2) if len(vals) > 1 else 0.0
        out["min"] = min(vals)
        out["max"] = max(vals)
        return out

    def level_counts(levels):
        c = {lv: 0 for lv in CEFR_ORDER}
        c[""] = 0
        for lv in levels:
            c[lv or ""] += 1
        return c

    classes: dict[str, dict] = {}
    rub_crits: dict[str, list] = {}
    for r in usable:
        if r.get("rubric_id"):
            rub = db.get_rubric(r["rubric_id"])
            if rub and r["rubric_id"] not in rub_crits:
                rub_crits[r["rubric_id"]] = [
                    c["name"] for c in rub.get("criteria", [])]
    for r in usable:
        classroom = (r.get("classroom") or "").strip() or "—"
        cl = classes.setdefault(classroom, {
            "classroom": classroom, "students": [], "levels": [],
            "criterion": {}, "overall": []})
        name = r.get("student_name") or "—"
        if name not in cl["students"]:
            cl["students"].append(name)
        # global: overall_level if set, else the recomputed attestation level
        overall = r["overall_norm"]
        rub = db.get_rubric(r["rubric_id"]) if r.get("rubric_id") else None
        if not overall and rub and rub.get("attestation"):
            att = compute_attestation(rub, [
                {"criterion": c, "suggested_level": lv}
                for c, lv in r["crit_levels"].items()])
            if att:
                overall = att.get("attestation")
        if overall:
            cl["overall"].append(overall)
            cl["levels"].append(LEVEL_POINTS.get(overall, 0))
        # per criterion: only criteria that exist on that rubric
        crits = rub_crits.get(r.get("rubric_id") or "", [])
        for cname in crits:
            lv = r["crit_levels"].get(cname)
            d = cl["criterion"].setdefault(cname, {"level": [], "score": []})
            d["level"].append(lv or "")
            if lv:
                d["score"].append(LEVEL_POINTS[lv])

    by_class = []
    for cl in sorted(classes.values(), key=lambda c: c["classroom"]):
        by_class.append({
            "classroom": cl["classroom"],
            "students": sorted(cl["students"]),
            "levels_counts": level_counts(cl["overall"]),
            "overall": dict(level_counts(cl["overall"]), **moments(cl["levels"])),
            "criterion": {
                name: dict(level_counts(d["level"]), **moments(d["score"]))
                for name, d in sorted(cl["criterion"].items())},
        })

    # Per-evaluation detail for the AI class insight (job kind "stats_ai"):
    # the per-criterion levels + the AI feedback summary of each evaluation.
    detail = []
    for r in usable:
        try:
            fb = _json.loads(r.get("feedback") or "null")
        except Exception:
            fb = None
        detail.append({
            "student": (r.get("student_name") or "—"),
            "classroom": (r.get("classroom") or "").strip() or "—",
            "overall": r["overall_norm"],
            "criteria": r["crit_levels"],
            "feedback": fb if isinstance(fb, dict) else None,
            "ai_at": r.get("ai_at"),
        })

    return {
        "assignment_id": assignment_id,
        "evaluations": len(usable),
        "evaluations_requested": requested,
        "rubrics": [{"id": k, "name": v} for k, v in rubrics_seen.items()],
        "levels": level_counts([r["overall_norm"] for r in usable]),
        "by_class": by_class,
        "evaluations_detail": detail,
    }


def stats_for_student(student_id: int) -> dict | None:
    """Chronological level evolution of ONE student, for the per-student
    "Stats" time chart (2026-10-12).

    Every submission of the student (linked or not — a student deletion keeps
    submissions via FK ON DELETE SET NULL) with at least one usable level
    (CEFR-levelable overall_level OR a filled criterion in the matrix) is one
    point in time. The level is resolved exactly like in
    `stats_for_assignment`: stored overall_level first, else the recomputed
    attestation from the matrix.

    Returns {student: {id, name, classroom}, evaluations (usable),
             total_submissions,
             points: [{id, date, title, level, points, code}],
             by_type: {"comprehension": {"written": [points], "oral": …},
                        "expression": …, "untyped": …}}
    or None when the student does not exist.
    """
    st = db.get_student(student_id)
    if not st:
        return None
    o = db._owner()
    own = " AND s.owner_id=?" if o is not None else ""
    q = ("SELECT s.id, s.kind, s.title, s.created_at, s.assignment_id, "
         "a.id AS analysis_id, a.rubric_id, a.overall_level, a.matrix_json "
         "FROM submissions s "
         "LEFT JOIN analyses a ON a.submission_id=s.id "
         f"WHERE s.student_id=?{own} ORDER BY s.created_at ASC, s.id ASC")
    with db._LOCK:
        rows = [dict(r) for r in db._conn().execute(
            q, (student_id,) + ((o,) if o is not None else ())).fetchall()]

    def resolve_level(r) -> str | None:
        lv = normalize_cefr(r.get("overall_level"))
        if lv:
            return lv
        mapping = []
        try:
            if r.get("matrix_json"):
                mapping = (_json.loads(r["matrix_json"]) or {}).get("rubric_mapping", [])
        except Exception:
            mapping = []
        crit_levels = {}
        for m in mapping:
            name = (m or {}).get("criterion")
            if name:
                crit_levels[name] = normalize_cefr((m or {}).get("suggested_level"))
        if any(crit_levels.values()) and r.get("rubric_id"):
            rub = db.get_rubric(r["rubric_id"])
            if rub and rub.get("attestation"):
                att = compute_attestation(rub, [
                    {"criterion": c, "suggested_level": lv2}
                    for c, lv2 in crit_levels.items()])
                if att:
                    return att.get("attestation") or None
        return None

    def bucket_of(r) -> str:
        """comprehension | expression | untyped, from the linked assignment."""
        if r.get("assignment_id"):
            a = db.get_assignment(r["assignment_id"])
            if a and (a.get("skill") or "").strip():
                return (a.get("skill") or "").strip()
        return "untyped"

    def code_of(skill: str, kind: str) -> str:
        """Short type code shown next to each chart point: L = listening
        (comprehension oral), R = reading (comprehension written),
        S = speaking (expression oral), W = writing (expression written).
        Untyped assignments (no skill) -> ''."""
        if skill == "comprehension":
            return "L" if kind == "oral" else "R"
        if skill == "expression":
            return "S" if kind == "oral" else "W"
        return ""

    points = []
    by_type: dict[str, dict] = {}
    total = len(rows)
    for r in rows:
        lv = resolve_level(r)
        if not lv:
            continue
        b = bucket_of(r)
        kind = (r.get("kind") or "").strip() or "unknown"
        rec = {"id": r["id"], "date": r["created_at"], "title": r["title"] or "",
               "level": lv, "points": LEVEL_POINTS.get(lv, 0),
               "code": code_of(b, kind)}
        points.append(rec)
        by_type.setdefault(b, {}).setdefault(kind, []).append(rec)

    return {
        "student": {"id": st["id"], "name": st.get("name"),
                    "classroom": st.get("classroom") or ""},
        "total_submissions": total,
        "evaluations": len(points),
        "levels": {lv: 0 for lv in CEFR_ORDER} | {
            lv: sum(1 for p in points if p["level"] == lv) for lv in CEFR_ORDER},
        "points": points,
        "by_type": {k: {k2: v2 for k2, v2 in v.items()}
                    for k, v in by_type.items()},
    }
