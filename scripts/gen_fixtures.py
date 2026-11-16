#!/usr/bin/env python3
"""Seed realistic test fixtures for the BabelGrade stats view.

- 40 fictional students in 2 classes
- 4 subjects (compréhension orale/écrite, production orale/écrite)
- 160 evaluations (40 students x 4 subjects): 38 filled + 2 skeletons/subject
Levels are generated so that overall_level == compute_attestation() of the
per-criterion matrix, i.e. fully consistent with the app's own math.
"""
import os
import json
import sqlite3
import random
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "data", "babelgrade.db")

# ---- verbatim from app/rubrics.py (keep in sync) ----
LEVEL_POINTS = {"A1": 1, "A2": 3, "B1": 5, "B2": 10, "C1": 20, "C2": 30}
SCORE_MAX = 120
CEFR_ORDER = ("A1", "A2", "B1", "B2", "C1", "C2")
SCORE_THRESHOLDS = {
    "comprehension": {"A1": 3, "A2": 9, "B1": 15, "B2": 30, "C1": 60, "C2": 90},
    "expression":    {"A1": 4, "A2": 12, "B1": 20, "B2": 40, "C1": 80, "C2": 120},
}
PTS_TO_LVL = {v: k for k, v in LEVEL_POINTS.items()}


def attestation_from_score(score: int, modalite: str) -> str:
    th = SCORE_THRESHOLDS[modalite]
    for lvl in reversed(CEFR_ORDER):
        if score >= th[lvl]:
            return lvl
    return "—"


def lvl_from_points(points: float) -> str:
    """Nearest discrete level to a raw point value (clipped to scale)."""
    p = max(1, min(30, points))
    best = min(LEVEL_POINTS, key=lambda k: abs(LEVEL_POINTS[k] - p))
    return best


# ---- rubrics (ids -> modalite + criterion names) ----
RUBRICS = {
    "att-comp": {
        "modalite": "comprehension",
        "kind": "written",  # modes=[written, oral]
        "criteria": [
            "Identification du contexte / situation d'énonciation",
            "Identification des réseaux de sens",
            "Identification des stratégies de communication",
        ],
    },
    "att-exp-ecrite": {
        "modalite": "expression",
        "kind": "written",
        "criteria": [
            "Qualité du contenu",
            "Cohérence dans la construction du discours",
            "Correction de la langue écrite",
            "Richesse de la langue",
        ],
    },
    "att-exp-orale": {
        "modalite": "expression",
        "kind": "oral",
        "criteria": [
            "Expression orale en continu",
            "Interaction orale",
            "Correction de la langue orale",
            "Richesse de la langue",
        ],
    },
}

# 4 subjects: (name, description, skill, kind, target, rubric_id, doc)
# English ELT class -> English names/instructions (student work is in English).
SUBJECTS = [
    ("Listening Comprehension — dictation & questioning",
     "Listening to a documentary podcast followed by a questioning.", "comprehension", "oral",
     "B1", "att-comp",
     "Listening exercises: 20 open-answer questions, one global comprehension question "
     "and 2 detailed-comprehension questions."),
    ("Reading Comprehension — study of a text",
     "Reading a press article followed by a questionnaire.", "comprehension", "written",
     "B1", "att-comp",
     "Reading a 650-word press article + 15 questions + a text-analysis questionnaire "
     "(semantic networks, registers, author's intention)."),
    ("Speaking — argumentative presentation",
     "A 5-minute oral presentation on a topic of the learner's choice.", "expression", "oral",
     "B1", "att-exp-orale",
     "A 5-minute argumentative talk on a topic in society, followed by a 3-minute "
     "assessment interview."),
    ("Writing — argumentative essay",
     "Writing an argumentative essay (~250 words).", "expression", "written",
     "B1", "att-exp-ecrite",
     'Argumentative essay: "Should social networks be banned in high schools?" '
     "(minimum 250 words, structured argumentation, open ending)."),
]

# ---- two classes: A = tighter/higher, B = wider/lower ----
CLASS_A = "26/27-LMY-2G1"   # tighter, higher (mean ~B1, low sd)
CLASS_B = "26/27-LMY-4A"    # wider, lower (mean ~A2, high sd)

NAMES_A = [
    "Léa Moreau", "Théo Lefèvre", "Chloé Martin", "Enzo Bernard", "Lucas Petit",
    "Emma Roux", "Nathan Fournier", "Manon Girard", "Hugo Bonnet", "Camille Blanc",
    "Jules Garnier", "Inès Dupont", "Louis Lambert", "Alice Mercier", "Gabriel Bonfils",
    "Jade Chevalier", "Maël Faure", "Zoé Gauthier", "Arthur Renard", "Lina Costa",
]
NAMES_B = [
    "Yanis Kaddour", "Sarah Benali", "Mehdi Haddad", "Lina Ziani", "Karim Bouaziz",
    "Nadia Cherif", "Adil Merabet", "Rania Saidi", "Hugo Diallo", "Awa Ndiaye",
    "Mickaël Traoré", "Fatou Sarr", "Ismaël Kone", "Awa Bello", "Rachid Amrani",
    "Sofia Rossi", "Marco Bianchi", "Giulia Romano", "Yannick Mbemba", "Chloé Ngoma",
]


def ability(rng, cls):
    """Latent 0-30 criterion-points ability per student, per class profile.

    NOTE: this is on the official point scale (A1=1, A2=3, B1=5, B2=10, C1=20,
    C2=30), where the low end is compressed — so a realistic class mean sits
    near 4-8, not 15. 2G1 (tight, higher, ~B1/B2) vs 4A (wide, lower, ~A2/B1).
    """
    if cls == CLASS_A:
        return rng.gauss(7.5, 1.8)
    return rng.gauss(3.8, 2.8)


def main():
    rng = random.Random(20261011)
    now = datetime(2026, 10, 11, 9, 0, 0)

    # clean any prior fixture rows (idempotent re-runs)
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("DELETE FROM passage_links")
    cur.execute("DELETE FROM analyses")
    cur.execute("DELETE FROM annotations")
    cur.execute("DELETE FROM submissions")
    cur.execute("DELETE FROM students")
    cur.execute("DELETE FROM assignments")
    con.commit()

    # ---- students ----
    students = {}     # name -> id
    cls_of_name = {}  # name -> classroom
    for cls, names in ((CLASS_A, NAMES_A), (CLASS_B, NAMES_B)):
        for nm in names:
            cur.execute(
                "INSERT INTO students (name, classroom, created_at) VALUES (?,?,?)",
                (nm, cls, now.isoformat(sep=" ")))
            students[nm] = cur.lastrowid
            cls_of_name[nm] = cls
    all_students = list(students.items())

    # ---- assignments ----
    assign_ids = []  # parallel to SUBJECTS (by index)
    for (name, desc, skill, kind, target, _rub, instruction) in SUBJECTS:
        cur.execute(
            "INSERT INTO assignments (name, description, target_level, skill, kind,"
            " instruction, created_at) VALUES (?,?,?,?,?,?,?)",
            (name, desc, target, skill, kind, instruction, now.isoformat(sep=" ")))
        assign_ids.append(cur.lastrowid)

    # ---- evaluations ----
    t0 = now
    filled = skeletons = 0
    level_counts = {k: 0 for k in CEFR_ORDER}
    for sidx, subj in enumerate(SUBJECTS):
        sname, desc, skill, kind, target, rid, instruction = subj
        rub = RUBRICS[rid]
        modalite = rub["modalite"]
        crit_names = rub["criteria"]
        aid = assign_ids[sidx]
        shift = 1.5 if skill == "comprehension" else 0.0  # comprehension a touch higher
        # two students leave a skeleton (started but not finished)
        skeleton_names = set(rng.sample([nm for (nm, _sid) in all_students], 2))
        for nm, sid in all_students:
            t = t0 + timedelta(seconds=rng.randint(0, 240))
            cur.execute(
                "INSERT INTO submissions (student_id, kind, source_type, language,"
                " target_level, assignment_id, created_at, title) VALUES (?,?,?,?,?,?,?,?)",
                (sid, kind, "text" if kind == "written" else "audio", "fr",
                 target, aid, t.isoformat(sep=" "), nm + " — " + sname))
            subid = cur.lastrowid
            is_skel = nm in skeleton_names
            if is_skel:
                cur.execute(
                    "INSERT INTO analyses (submission_id, rubric_id, status, created_at)"
                    " VALUES (?,?,?,?)", (subid, rid, "teacher",
                                          t.isoformat(sep=" ")))
                skeletons += 1
                continue
            # latent ability + per-subject + per-criterion noise
            base = ability(rng, cls_of_name[nm]) + shift
            levels = []
            for _ in crit_names:
                lvl = lvl_from_points(base + rng.gauss(0, 2.5))
                levels.append(lvl)
            score = sum(LEVEL_POINTS[lv] for lv in levels)
            overall = attestation_from_score(score, modalite)
            mapping = {"rubric_mapping": [
                {"criterion": c, "suggested_level": lvl}
                for c, lvl in zip(crit_names, levels)]}
            cur.execute(
                "INSERT INTO analyses (submission_id, rubric_id, overall_level,"
                " matrix_json, status, created_at) VALUES (?,?,?,?,?,?)",
                (subid, rid, overall, json.dumps(mapping, ensure_ascii=False),
                 "done", t.isoformat(sep=" ")))
            filled += 1
            level_counts[overall] = level_counts.get(overall, 0) + 1
    con.commit()

    # ---- report ----
    print("=== fixtures seeded ===")
    print(f"students: 40 ({len(NAMES_A)} in {CLASS_A}, {len(NAMES_B)} in {CLASS_B})")
    print("assignments:", len(assign_ids))
    print("submissions:", cur.execute("SELECT COUNT(*) FROM submissions").fetchone()[0])
    print("analyses:", cur.execute("SELECT COUNT(*) FROM analyses").fetchone()[0],
          f"(filled={filled}, skeleton={skeletons})")
    print("overall level spread:", {k: v for k, v in level_counts.items() if v})
    con.close()


if __name__ == "__main__":
    main()
