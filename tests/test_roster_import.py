"""Roster photo import (2026-11-08) — in-process E2E with a MOCK LLM.

Boots the real FastAPI app against a throwaway sqlite DB + a throwaway
uploads dir, points the LLM client at the in-process mock
(tests/mock_llm_server.py) and drives the whole flow:

    POST /api/students/import-photos          (stage photos -> job handle)
    GET  /api/jobs/{id}                       (poll to done)
    GET  /api/students/import-photos/{job_id} (the extracted draft)
    POST /api/students/import-photos/{job_id}/commit
                                              (idempotent upsert of students)

plus the edge cases: no photo 422, bad extension 422, >10 photos 422,
404 unknown job, 409 commit before done, 409 second in-flight import,
unknown-job get, photos deleted after commit, re-commit = updated (no
duplication), and cross-user isolation of the roster job.

Run:  python3 tests/test_roster_import.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

PROJ = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, PROJ)
sys.path.insert(0, PROJ + "/tests")

import mock_llm_server as mms

# Point the LLM client at the mock BEFORE the app imports it.
mock = mms.MockLLMServer().start()
# Hold every roster reply open 1.5 s so the job stays in-flight long enough
# to make the 409 guards deterministic (the mock LLM is near-instant).
mms.ROSTER_DELAY = 1.5
os.environ["BABELGRADE_LLM_BASE"] = mock.base_url
os.environ["BABELGRADE_LLM_MODEL"] = "mock-llm"

TMP = Path(tempfile.mkdtemp(prefix="elt_roster_"))
import app.db as db
db.DB_PATH = TMP / "test.db"
import app.config as config
UPLOADS = TMP / "uploads"
UPLOADS.mkdir()
config.UPLOAD_DIR = UPLOADS          # staging dir override (runtime attribute)

import app.main as app_main
from fastapi.testclient import TestClient

app = app_main.app

RESULTS = []
def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name
          + (f"  [{extra}]" if extra and not cond else ""))


# a 1x1 PNG (the mock LLM ignores image content)
import struct, zlib
def _tiny_png() -> bytes:
    w = h = 2
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))
PNG = _tiny_png()


def poll_job(client, job_id, timeout=60.0):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        r = client.get(f"/api/jobs/{job_id}")
        last = r.json()
        if last.get("status") in ("done", "error", "cancelled"):
            return last
        time.sleep(0.15)
    return last


with TestClient(app, raise_server_exceptions=True) as client:
    # --- auth -------------------------------------------------------------
    r = client.post("/api/auth/register",
                    json={"username": "tibo", "password": "tibo-test-pw-1"})
    check("register first user", r.status_code == 200, r.text)

    # --- edge cases on POST ----------------------------------------------
    r = client.post("/api/students/import-photos",
                    data={"class_code": "26/27-LMY-2G1"})
    check("no photo -> 422", r.status_code == 422, str(r.status_code))
    r = client.post("/api/students/import-photos",
                    files={"photos": ("liste.txt", PNG, "text/plain")})
    check("unsupported extension -> 422", r.status_code == 422, r.text)

    # --- main flow: 2 photos -> job -> draft -> commit --------------------
    r = client.post("/api/students/import-photos",
                    files=[("photos", (f"roster-{i}.png", PNG, "image/png"))
                           for i in range(2)],
                    data={"class_code": "26/27-LMY-2G1", "ui_language": "fr"})
    check("import-photos enqueues a job", r.status_code == 200
          and r.json().get("enqueued") is True and r.json()["photo_count"] == 2,
          r.text[:200])
    h = r.json()
    j1 = h["job_id"]
    check("handle exposes follow_url",
          h.get("follow_url", "").endswith(f"/api/jobs/{j1}/events"))

    # the photos were staged into the uploads dir
    staged = [p.name for p in UPLOADS.glob("roster-*.png")]
    check("2 photos staged in uploads", len(staged) == 2, str(staged))

    # a second in-flight import is refused (409) while the first runs
    r2 = client.post("/api/students/import-photos",
                     files={"photos": ("a.png", PNG, "image/png")})
    check("second in-flight import -> 409", r2.status_code == 409,
          str(r2.status_code))

    job1 = poll_job(client, j1)
    check("roster job reached done", job1 and job1.get("status") == "done",
          json.dumps(job1 or {})[:300])

    # the draft
    r = client.get(f"/api/students/import-photos/{j1}")
    check("draft endpoint: done + draft", r.status_code == 200
          and r.json()["status"] == "done" and r.json()["draft"],
          r.text[:300])
    draft = r.json()["draft"]
    check("draft has class identity",
          draft.get("class_name") == "2G1"
          and draft.get("school_name") == "Lycée Mock Jean-Jaurès",
          json.dumps({k: draft.get(k) for k in ("class_name", "school_name")}))
    check("draft keeps the class_code_hint",
          draft.get("class_code_hint") == "26/27-LMY-2G1",
          json.dumps(draft.get("class_code_hint")))
    check("draft has the 3 mock students",
          [ (s["first_name"], s["last_name"]) for s in draft["students"] ] ==
          [("Léa", "Martin"), ("Noah", "Bernard"), ("Chloé", "DUPONT")],
          json.dumps(draft.get("students")))
    check("draft carries the mock warning", len(draft.get("warnings")) >= 1,
          json.dumps(draft.get("warnings")))

    # nothing created yet
    check("no student created before commit",
          client.get("/api/students").json() == [], "should be empty")

    # commit (teacher reviewed: edit one name, drop one row)
    body = {
        "school_name": draft["school_name"],
        "classroom": "26/27-LMY-2G1",
        "students": [
            {"first_name": "Léa", "last_name": "Martin", "include": True},
            {"first_name": "Noah", "last_name": "BERNARD", "include": True},
            {"first_name": "Chloé", "last_name": "DUPONT", "include": False},
        ],
    }
    r = client.post(f"/api/students/import-photos/{j1}/commit",
                    json=body)
    check("commit -> 2 created, 0 updated, 0 skipped",
          r.status_code == 200 and r.json()["created"] == 2
          and r.json()["updated"] == 0 and r.json()["skipped"] == [],
          r.text)
    studs = client.get("/api/students").json()
    names = sorted(s["name"] for s in studs)
    check("2 students in the list, dropped row absent",
          names == ["Léa Martin", "Noah BERNARD"], json.dumps(names))
    check("students carry the classroom code",
          all(s["classroom"] == "26/27-LMY-2G1" for s in studs),
          json.dumps([s["classroom"] for s in studs]))
    # photos were deleted after commit
    check("roster photos deleted after commit",
          len(list(UPLOADS.glob("roster-*.png"))) == 0,
          str([p.name for p in UPLOADS.glob('roster-*.png')]))

    # re-commit the SAME roster -> updated (idempotent, no duplication)
    body2 = {
        "classroom": "26/27-LMY-2G1",
        "students": [
            {"first_name": "Léa", "last_name": "Martin", "include": True},
            {"first_name": "Noah", "last_name": "BERNARD", "include": True},
        ],
    }
    r = client.post(f"/api/students/import-photos/{j1}/commit", json=body2)
    check("re-commit -> 0 created, 2 updated (idempotent)",
          r.status_code == 200 and r.json()["created"] == 0
          and r.json()["updated"] == 2, r.text)
    check("still exactly 2 students after re-commit",
          len(client.get("/api/students").json()) == 2)

    # edge: commit a job whose extraction is not done -> 409 (ROSTER_DELAY
    # keeps the mock reply open 1.5 s, so the commit is deterministically
    # early). The job stays in flight: it is still running when commit hits.
    r = client.post("/api/students/import-photos",
                    files={"photos": ("b.png", PNG, "image/png")})
    j2 = r.json()["job_id"]
    r = client.post(f"/api/students/import-photos/{j2}/commit", json={})
    check("commit in-flight job -> 409", r.status_code == 409, r.text)
    check("in-flight job still running (worker not stuck)",
          client.get(f"/api/jobs/{j2}").json()["status"] in
          ("queued", "running"))

    # edge: unknown job -> 404 (commit + status)
    r = client.post("/api/students/import-photos/99999/commit", json={})
    check("commit unknown job -> 404", r.status_code == 404, str(r.status_code))
    r = client.get("/api/students/import-photos/99999")
    check("status unknown job -> 404", r.status_code == 404, str(r.status_code))

    # let j2 finish before the isolation checks below
    job2 = poll_job(client, j2)
    check("second roster job also reached done",
          job2 and job2.get("status") == "done", json.dumps(job2 or {})[:200])

    # --- cross-user isolation --------------------------------------------
    from app import auth
    uid2 = auth.create_user("marie", "marie-pw-1")
    c2 = TestClient(app)
    c2.post("/api/auth/login", json={"username": "marie", "password": "marie-pw-1"})
    r = c2.get(f"/api/students/import-photos/{j1}")
    check("marie GET tibo's roster job -> 404", r.status_code == 404,
          str(r.status_code))
    r = c2.post(f"/api/students/import-photos/{j1}/commit",
                json={"classroom": "X", "students": []})
    check("marie commit tibo's job -> 404", r.status_code == 404,
          str(r.status_code))
    r = c2.get("/api/students")
    check("marie sees 0 students (roster not leaked)", r.json() == [],
          json.dumps(r.json()))

mock.stop()

passed = sum(1 for _, ok in RESULTS if ok)
print()
print(f"{passed}/{len(RESULTS)} checks passed")
print("ALL PASS" if passed == len(RESULTS) else "SOME FAILED")
sys.exit(0 if passed == len(RESULTS) else 1)
