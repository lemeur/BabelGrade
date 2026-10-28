"""Verify the FR UI sends ui_language on all THREE AI entry points:
   - /api/analyze/stream   (AI-first, #run — direct SSE)
   - /api/evaluate         (teacher-first, #run-eval — JSON job handle)
   - /api/analyses/{id}/run-ai  (re-run AI, banner — JSON job handle)

Run: /tmp/elt_dm/venv/bin/python3 /tmp/elt_uilang/ui_lang_send_test.py
Live server on :8090 required; login tibo/****; lang forced FR.
"""
import json
import re
import sys
import urllib.request
from http.cookiejar import CookieJar

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8090"
FAILED = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        FAILED.append(label)


def main():
    # parse a multipart/form-data body into {field_name: value}.
    # A plain text field looks like: ...name="X"\r\n\r\nvalue\r\n
    def mpart_fields(body):
        out = {}
        for m in re.finditer(r'name="([^"]+)"\r?\n\r?\n([^\r\n]*)', body):
            out[m.group(1)] = m.group(2).strip()
        return out

    # real rubric (for a faithful report payload the UI can render)
    cj = CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.open(urllib.request.Request(
        "http://127.0.0.1:8090/api/auth/login",
        data=json.dumps({"username": "tibo", "password": "****"}).encode(),
        headers={"Content-Type": "application/json"}))
    rub = json.load(op.open("http://127.0.0.1:8090/api/rubrics/att-exp-ecrite"))
    mapping = [{"criterion": c["name"], "suggested_level": "B1",
                "justification": "x", "evidence": ["y"]}
               for c in rub.get("criteria", [])]

    def report_payload(aid):
        return json.dumps({
            "id": aid, "submission_id": 1, "data": {
                "executive_summary": "", "overall_level": "B1",
                "versus_target": "meets", "confidence": "high",
                "strong_points": [], "areas_for_improvement": [],
                "rubric_mapping": mapping,
                "student_feedback": {"key_success": "a", "target_area": "b",
                                     "comment": "c"}},
            "ai_data": None, "aiMode": None, "aiAt": None,
            "parsed": True, "raw": "", "warnings": [], "fluency": None,
            "transcript": None, "transcript_correction": None,
            "transcript_mode": None, "annotations": [],
            "attestation": {"score": 30, "score_max": 120,
                            "modalite": "expression", "attestation": "B1",
                            "breakdown": [], "unmapped": []},
            "validated": False, "note20": None,
            "rubric_id": "att-exp-ecrite", "rubric_name": rub.get("name"),
        })

    def job_handle(kind, aid, jid):
        return json.dumps({
            "job_id": jid, "job_status": "queued", "job_kind": kind,
            "analysis_id": aid, "submission_id": 1, "created_at": "",
            "enqueued": True, "follow_url": f"/api/jobs/{jid}/events",
            "analysis": None})

    def events_sse(aid):
        return ("event: meta\ndata: {}\n\n"
                "event: result\ndata: " + report_payload(aid) + "\n\n"
                "event: done\ndata: {\"status\": \"done\"}\n\n")

    stream_bodies, eval_bodies, runai_bodies = [], [], []

    # AI-first #run -> POST /api/analyze/stream (multipart, direct SSE)
    def r_stream(route):
        if route.request.method != "POST":
            return route.continue_()
        stream_bodies.append(route.request.post_data)
        route.fulfill(status=200, content_type="text/event-stream",
                      body=events_sse(901))

    # teacher-first #run-eval -> POST /api/evaluate (JSON handle, then SSE)
    def r_eval(route):
        if route.request.method != "POST":
            return route.continue_()
        eval_bodies.append(route.request.post_data)
        route.fulfill(status=200, content_type="application/json",
                      body=job_handle("evaluate", 902, 92))

    # banner re-run -> POST /api/analyses/{id}/run-ai (JSON handle, then SSE)
    def r_runai(route):
        if route.request.method != "POST":
            return route.continue_()
        runai_bodies.append(route.request.post_data)
        route.fulfill(status=200, content_type="application/json",
                      body=job_handle("run_ai", 902, 93))

    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_init_script("localStorage.setItem('elt-lang','fr')")
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))

        pg.route("**/api/analyze/stream", r_stream)
        pg.route("**/api/evaluate", r_eval)
        pg.route("**/api/analyses/**/run-ai", r_runai)
        pg.route("**/api/jobs/**/events",
                 lambda r: r.fulfill(status=200,
                                     content_type="text/event-stream",
                                     body=events_sse(902)))

        pg.goto(BASE + "/", wait_until="networkidle")
        pg.wait_for_timeout(400)
        if pg.evaluate(
                "document.querySelector('#auth-login-form') && "
                "!document.querySelector('#auth-login-form').classList.contains('hide')"):
            pg.fill("#auth-username", "tibo")
            pg.fill("#auth-password", "****")
            pg.click("#auth-login-btn")
            pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
        pg.wait_for_timeout(800)
        pg.evaluate("pieClose()")   # 2026-10-27: home radial menu opens by default —
                                    # close it so the header buttons are clickable
        check(pg.evaluate("localStorage.getItem('elt-lang')") == "fr",
              "boot in FR")

        # 1) AI-first #run
        pg.click("#hdr-evaluate")
        pg.fill("#written-text", "It was a nice day and we went to the park.")
        pg.select_option("#rubric", "att-exp-ecrite")
        pg.click("#run")
        pg.wait_for_timeout(2000)
        check(len(stream_bodies) >= 1, "POST /api/analyze/stream fired")
        if stream_bodies:
            sf = mpart_fields(stream_bodies[0])
            check(sf.get("ui_language") == "fr",
                  f"analyze/stream form carries ui_language=fr (got {sf.get('ui_language')!r})")
            check(sf.get("language") == "en",
                  "student-language field unchanged (language=en)")

        # 2) teacher-first #run-eval
        pg.click("#run-eval")
        pg.wait_for_timeout(2000)
        check(eval_bodies and mpart_fields(eval_bodies[-1]).get("ui_language") == "fr",
              "evaluate form carries ui_language=fr")

        # 3) banner re-run -> run-ai
        pg.wait_for_selector("#report .ai-banner-card", timeout=10000)
        pg.click("#report .ai-banner-card #ai-run")
        pg.wait_for_timeout(2500)
        check(len(runai_bodies) >= 1, "POST run-ai fired")
        if runai_bodies:
            try:
                body = json.loads(runai_bodies[0])
                check(body.get("ui_language") == "fr",
                      "run-ai body carries ui_language=fr")
            except Exception as e:
                check(False, f"run-ai body parse ({e})")

        print("\nJS errors:", errs or "none")
        b.close()

    print()
    if FAILED:
        print("FAILED:", FAILED)
        sys.exit(1)
    print("All frontend send-side checks passed")


if __name__ == "__main__":
    main()
