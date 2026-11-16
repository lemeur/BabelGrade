"""P2.9 — E2E test of the async job queue with a MOCK LLM (no real model).

Points ``BABELGRADE_LLM_BASE`` at an in-process OpenAI-compatible mock
(``tests/mock_llm_server.py``) and drives the three long endpoints that the
real qwen38-27b would serve (~100-130 s each, manual-only before this):

    POST /api/analyze            (enqueue -> claim -> run -> finalize -> done)
    POST /api/evaluate           (teacher-first: skeleton, no LLM)
    POST /api/analyses/{id}/run-ai  (aware mode: teacher matrix untouched,
                                     AI matrix filled, last-AI-wins)
    POST /api/analyze/stream     (SSE: meta -> phase* -> token* -> result -> done)

plus the job plumbing (counts / list / get / cancel / 404). Runs in-process
against a throwaway sqlite file, so it is fast, deterministic and safe to put
in CI. No Whisper, no real LLM, no network beyond 127.0.0.1.

Run:  python3 tests/test_p2_mock_llm_e2e.py
"""
import json
import os
import sys
import tempfile
import time

PROJ = "/home/tibo/babelgrade"
sys.path.insert(0, PROJ)
sys.path.insert(0, PROJ + "/tests")

from pathlib import Path
import mock_llm_server as mms

# ---------------------------------------------------------------------------
# Point the LLM client at the mock BEFORE the app imports it (llm_client reads
# BABELGRADE_LLM_BASE/MODEL at import time). Start the mock, grab its real port.
mock = mms.MockLLMServer().start()
# Hold each streamed LLM reply open a beat longer than the scheduler's claim
# window, so the SSE subscriber deterministically attaches to the LIVE job
# stream (catching the token events) instead of falling back to the
# late-subscriber DB-rebuild path. Mirrors production where the real LLM keeps
# the stream open for ~100 s.
mms.STREAM_PRE_DELAY = 1.0
os.environ["BABELGRADE_LLM_BASE"] = mock.base_url
os.environ["BABELGRADE_LLM_MODEL"] = "mock-llm"

TMP = Path(tempfile.mkdtemp(prefix="elt_p2_mock_"))
import app.db as db
db.DB_PATH = TMP / "test.db"          # temp DB, BEFORE app.main boots it

import app.main as app_main           # create_app() runs init_db on the temp DB
from fastapi.testclient import TestClient

app = app_main.app

RESULTS = []
def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name
          + (f"  [{extra}]" if extra and not cond else ""))


def poll_job(client, job_id, timeout=60.0):
    """GET /api/jobs/{id} until terminal (done/error/cancelled) or timeout."""
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        r = client.get(f"/api/jobs/{job_id}")
        last = r.json()
        if last.get("status") in ("done", "error", "cancelled"):
            return last
        time.sleep(0.2)
    return last


def sse_events(resp_lines):
    """Parse SSE text lines into a list of (event, data_json)."""
    events, ev, data = [], None, []
    for ln in resp_lines:
        ln = ln.rstrip("\n")
        if ln.startswith("event:"):
            ev = ln[len("event:"):].strip()
        elif ln.startswith("data:"):
            data.append(ln[len("data:"):].strip())
        elif ln == "" and ev is not None:
            payload = "\n".join(data)
            try:
                parsed = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                parsed = {"_raw": payload}
            events.append((ev, parsed))
            ev, data = None, []
    return events


with TestClient(app, raise_server_exceptions=True) as client:
    # the `with` runs the lifespan -> jobs.start_workers() (the scheduler)

    # --- auth (fresh temp DB: first-user registration) ---------------------
    r = client.post("/api/auth/register",
                    json={"username": "tibo", "password": "tibo-test-pw-1"})
    check("register first user", r.status_code == 200, r.text)
    r = client.get("/api/auth/me")
    check("logged in as tibo", r.status_code == 200
          and r.json()["user"]["username"] == "tibo", r.text)

    # --- a custom attestation rubric with known criteria -------------------
    crits = [
        {"name": "Qualité du contenu", "description": "mock description 1"},
        {"name": "Cohérence du discours", "description": "mock description 2"},
        {"name": "Correction morphosyntaxique", "description": "mock description 3"},
        {"name": "Richesse lexicale", "description": "mock description 4"},
    ]
    r = client.post("/api/rubrics", json={
        "name": "Mock Written", "mode": "written", "criteria": crits,
        "attestation": True, "modalite": "expression"})
    check("create custom rubric", r.status_code == 200, r.text)
    rubric = r.json()
    check("rubric marked attestation", rubric.get("attestation") is True,
          json.dumps(rubric.get("attestation")))
    rid = rubric["id"]

    # Deterministic per-criterion levels the mock returns for every analyze
    # call (A2 + A2 + B1 + B2 = 3 + 3 + 5 + 10 = 21 points -> B1 / expression).
    mms.DEFAULT_LEVELS = {
        crits[0]["name"]: "A2",
        crits[1]["name"]: "A2",
        crits[2]["name"]: "B1",
        crits[3]["name"]: "B2",
    }

    # =======================================================================
    # A. /api/analyze  (full enqueue -> claim -> run -> done)
    # =======================================================================
    r = client.post("/api/analyze", data={
        "kind": "written", "rubric_id": rid, "student_id": 0,
        "written_text": "The weather in Paris has been surprisingly mild this "
                        "autumn, which the residents have welcomed with open arms.",
        "title": "Mock Essay A", "target_level": "B1", "ui_language": "fr"})
    check("analyze enqueues a job", r.status_code == 200
          and r.json().get("enqueued") is True, r.text[:200])
    handle = r.json()
    a1 = handle["analysis"]["id"]
    j1 = handle["job_id"]
    check("handle exposes follow_url + ids",
          handle.get("follow_url", "").endswith(f"/api/jobs/{j1}/events")
          and handle["submission_id"], json.dumps(handle)[:200])

    job1 = poll_job(client, j1)
    check("analyze job reached done", job1 and job1.get("status") == "done",
          json.dumps(job1)[:300])

    r = client.get(f"/api/analyses/{a1}")
    a1row = r.json()
    mat = a1row.get("matrix") or {}
    check("analyze persisted the AI matrix",
          isinstance(mat, dict) and mat.get("overall_level") == "B1",
          json.dumps(mat.get("overall_level")))
    names = [m.get("criterion") for m in mat.get("rubric_mapping", [])]
    check("rubric_mapping has one entry per criterion, in order",
          names == [c["name"] for c in crits], json.dumps(names))
    check("every mapping carries evidence",
          all(m.get("evidence") for m in mat.get("rubric_mapping", [])))
    check("analyze: no matrix warnings",
          a1row.get("status") == "done", json.dumps(a1row.get("status")))
    check("analyze raw_markdown stored (verbatim evidence quote)",
          (a1row.get("raw_markdown") or "").find("demonstrates") >= 0
          or (a1row.get("raw_markdown") or "").find("Mock") >= 0,
          (a1row.get("raw_markdown") or "")[:120])
    att = a1row.get("attestation") or {}
    check("analyze: attestation computed deterministically (score 21 -> B1)",
          att.get("score") == 21 and att.get("attestation") == "B1",
          json.dumps({k: att.get(k) for k in ("score", "attestation", "modalite")}))
    # the finished job row carries its result report (UI-ready report dict),
    # stored as result_json (job_get does not hydrate it, so parse it here)
    j1row = db.job_get(j1) or {}
    try:
        j1result = json.loads(j1row["result_json"]) if j1row.get("result_json") else None
    except (json.JSONDecodeError, TypeError):
        j1result = None
    check("analyze: job result report persisted on the job row",
          j1row.get("status") == "done"
          and isinstance(j1result, dict)
          and j1result.get("data", {}).get("overall_level") == "B1",
          json.dumps({k: j1row.get(k) for k in ("status", "finished_at", "elapsed_s")}))

    # job list shows it done with an elapsed time
    r = client.get("/api/jobs")
    jobs_list = r.json()["jobs"]
    check("job list shows the analyze job done with elapsed_s",
          any(j["id"] == j1 and j["status"] == "done" and j.get("elapsed_s") is not None
              for j in jobs_list),
          json.dumps([j["status"] for j in jobs_list]))

    # =======================================================================
    # B. /api/evaluate  (teacher-first: empty skeleton, NO LLM call)
    # =======================================================================
    r = client.post("/api/evaluate", data={
        "kind": "written", "rubric_id": rid, "student_id": 0,
        "written_text": "Another mock essay for the teacher-first flow.",
        "title": "Mock Eval B"})
    check("evaluate enqueues a job", r.status_code == 200
          and r.json().get("enqueued") is True, r.text[:200])
    b1 = r.json()["analysis"]["id"]
    jb = r.json()["job_id"]
    jobb = poll_job(client, jb)
    check("evaluate job reached done", jobb and jobb.get("status") == "done",
          json.dumps(jobb)[:300])
    r = client.get(f"/api/analyses/{b1}")
    b1row = r.json()
    bmat = b1row.get("matrix") or {}
    check("evaluate built an empty skeleton (levels blank)",
          isinstance(bmat, dict)
          and [m.get("criterion") for m in bmat.get("rubric_mapping", [])]
          == [c["name"] for c in crits]
          and all((m.get("suggested_level") or "") == ""
                  for m in bmat.get("rubric_mapping", [])),
          json.dumps([m.get("suggested_level") for m in bmat.get("rubric_mapping", [])]))
    check("evaluate: no AI opinion yet (has_ai_snapshot False)",
          b1row.get("has_ai_snapshot") is False, json.dumps(b1row.get("has_ai_snapshot")))

    # B.2. run-ai (aware) on that evaluation: teacher matrix must survive,
    #       AI matrix must be filled, last-AI-wins.
    # Seed a teacher level so "aware" mode has something to review.
    r = client.put(f"/api/analyses/{b1}", json={
        "levels": {crits[0]["name"]: "B2"}})
    check("teacher set a level before run-ai",
          r.status_code == 200
          and [m.get("suggested_level") for m in
               (r.json().get("matrix") or {}).get("rubric_mapping", [])]
          and r.json()["matrix"]["rubric_mapping"][0]["suggested_level"] == "B2",
          json.dumps(r.json().get("matrix", {}).get("rubric_mapping", [None]))[:200])

    r = client.post(f"/api/analyses/{b1}/run-ai", json={"mode": "aware"})
    check("run-ai enqueues a job", r.status_code == 200
          and r.json().get("enqueued") is True, r.text[:200])
    jr = r.json()["job_id"]
    jobr = poll_job(client, jr)
    check("run-ai job reached done", jobr and jobr.get("status") == "done",
          json.dumps(jobr)[:300])
    r = client.get(f"/api/analyses/{b1}")
    brow = r.json()
    tm = (brow.get("matrix") or {}).get("rubric_mapping", [])
    am = (brow.get("ai_matrix") or {}).get("rubric_mapping", [])
    check("run-ai: teacher matrix UNTOUCHED (first level still B2)",
          tm and tm[0].get("suggested_level") == "B2",
          json.dumps([m.get("suggested_level") for m in tm]))
    check("run-ai: AI matrix FILLED (last-AI-wins snapshot present)",
          am and any(m.get("suggested_level") for m in am)
          and brow.get("has_ai_snapshot") is True,
          json.dumps([m.get("suggested_level") for m in am]))
    check("run-ai: ai_mode recorded as 'aware'",
          brow.get("ai_mode") == "aware", json.dumps(brow.get("ai_mode")))
    check("run-ai: CONFIRMED-B1 marker flowed through the aware prompt",
          (brow.get("raw_markdown") or "").find("CONFIRMED-B1") >= 0,
          (brow.get("raw_markdown") or "")[:120])

    # =======================================================================
    # C. /api/analyze/stream  (SSE event ordering)
    # =======================================================================
    with client.stream("POST", "/api/analyze/stream", data={
            "kind": "written", "rubric_id": rid, "student_id": 0,
            "written_text": "Streaming mock essay for the SSE path.",
            "title": "Mock Essay C", "ui_language": "fr"}) as resp:
        lines = list(resp.iter_lines())
    ev = sse_events(lines)
    kinds = [e for e, _ in ev]
    check("SSE: got a meta event", "meta" in kinds, json.dumps(kinds))
    check("SSE: phase events observed", "phase" in kinds, json.dumps(kinds))
    check("SSE: at least one token event streamed", "token" in kinds,
          json.dumps(kinds))
    check("SSE: result event carries the parsed matrix",
          any(e == "result" and isinstance(d, dict)
              and isinstance(d.get("data"), dict) and d["data"].get("overall_level")
              for e, d in ev),
          json.dumps([e for e, _ in ev]))
    check("SSE: terminal 'done' event", "done" in kinds, json.dumps(kinds))
    order = [kinds.index(x) for x in ("meta", "result", "done") if x in kinds]
    check("SSE: order meta < result < done",
          len(order) == 3 and order == sorted(order), json.dumps(kinds))

    # =======================================================================
    # D. job plumbing: counts / get payload / cancel / 404
    # =======================================================================
    r = client.get("/api/jobs/counts")
    check("job counts: at least 3 jobs, max_workers 1",
          r.status_code == 200 and r.json()["counts"].get("done", 0) >= 3
          and r.json()["max_workers"] == 1,
          json.dumps(r.json()))
    r = client.get(f"/api/jobs/{j1}")
    check("get_job returns the stored payload (rubric_id round-trip)",
          r.status_code == 200 and r.json().get("payload", {}).get("rubric_id") == rid,
          json.dumps(r.json().get("payload", {}))[:200])
    # cancel a terminal job -> 409
    r = client.post(f"/api/jobs/{j1}/cancel")
    check("cancel a done job -> 409", r.status_code == 409, str(r.status_code))
    # cancel an unknown job -> 404
    r = client.post("/api/jobs/99999/cancel")
    check("cancel unknown job -> 404", r.status_code == 404, str(r.status_code))
    # unknown job get -> 404
    r = client.get("/api/jobs/99999")
    check("get unknown job -> 404", r.status_code == 404, str(r.status_code))

# exiting the `with` stops the lifespan -> jobs.stop_workers()
mock.stop()

passed = sum(1 for _, ok in RESULTS if ok)
print()
print(f"{passed}/{len(RESULTS)} checks passed")
print("ALL PASS" if passed == len(RESULTS) else "SOME FAILED")
sys.exit(0 if passed == len(RESULTS) else 1)
