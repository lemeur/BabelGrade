#!/usr/bin/env python3
"""E2E: the student's work may be submitted as a PDF (2026-11-25, commit
ef2f4e9).

Two deterministic checks, no LLM, live server on :8090, login tibo/test-pw-9876:

  1. STRUCTURE (Playwright) — the block-3 copy field (#mfield-copy) exposes a
     📄 PDF mode alongside photo/text; PHOTO remains the default mode (the PDF
     option is NOT preselected — tibo's explicit requirement); uploading a PDF
     sets currentCopyPdf (the state the run CTAs send as written_pdf).
  2. SCAN PERSIST (stdlib HTTP, cookie auth) — POST /api/evaluate with a
     scanned (image-only) PDF: the worker renders its pages to JPEGs and the
     submission persists source_type=image + page_paths + copy_pdf_name, so
     Annoter auto-OCR + /api/files ownership follow from there.

The TEXT-LAYER branch was verified live in the session (analysis 676: the LLM
cited the PDF's text as verbatim evidence) but needs ~90 s + LLM — kept out of
the regression suite.
Run: /tmp/bg_venv/bin/python tests/test_copy_pdf_work.py
"""
import io
import json
import mimetypes
import os
import sqlite3
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
import http.cookiejar

BASE = os.environ.get("BABELGRADE_BASE", "http://127.0.0.1:8090")
DB = os.path.join(os.path.dirname(__file__), "..", "data", "babelgrade.db")


def make_scanned_pdf(path: str) -> None:
    """Single-page image-only PDF (no text layer) via PIL — the test venv has
    no pymupdf; the APP's worker (pymupdf) renders it, which is what we test."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (1200, 1600), "white")
    ImageDraw.Draw(img).text((80, 120), "scanned page, no text layer",
                             fill="black")
    img.save(path, "PDF", resolution=100.0)


def multipart(fields: dict, files: dict) -> tuple[str, bytes]:
    b = uuid.uuid4().hex
    body = io.BytesIO()
    for k, v in fields.items():
        body.write(
            (f'--{b}\r\nContent-Disposition: form-data; name="{k}"'
             f'\r\n\r\n{v}\r\n').encode())
    for name, (fname, data) in files.items():
        mime = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        body.write(
            (f'--{b}\r\nContent-Disposition: form-data; name="{name}"; '
             f'filename="{fname}"\r\nContent-Type: {mime}\r\n\r\n').encode())
        body.write(data)
        body.write(b"\r\n")
    body.write(f"--{b}--\r\n".encode())
    return f"multipart/form-data; boundary={b}", body.getvalue()


def backend_scan_persist(scan_pdf_path: str) -> dict:
    """Login (cookie) + POST /api/evaluate with the scanned PDF + poll the
    job to a terminal state; read back the persisted submission row."""
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj))
    login = json.dumps({"username": "tibo", "password": "test-pw-9876"}).encode()
    req = urllib.request.Request(
        BASE + "/api/auth/login", data=login,
        headers={"Content-Type": "application/json"})
    op.open(req)

    rubs = json.loads(op.open(BASE + "/api/rubrics").read())
    rid = next(r["id"] for r in rubs
               if r.get("mode") == "written" or "written" in (r.get("modes") or []))

    ct, body = multipart(
        {"kind": "written", "rubric_id": rid, "student_id": "0",
         "assignment_id": "0", "language": "en", "ui_language": "fr",
         "target_level": "B1", "title": "Copy PDF backend probe"},
        {"written_pdf": ("copy_scan.pdf", open(scan_pdf_path, "rb").read())})
    req = urllib.request.Request(BASE + "/api/evaluate", data=body,
                                 headers={"Content-Type": ct})
    handle = json.loads(op.open(req).read())
    sub_id = handle["submission_id"]

    # poll the job row until a terminal state (REST, no SSE byte parsing)
    deadline = time.time() + 60
    status = None
    while time.time() < deadline:
        j = json.loads(op.open(
            f"{BASE}/api/jobs/{handle['job_id']}").read())
        status = j.get("status")
        if status in ("done", "error", "cancelled", "failed"):
            break
        time.sleep(0.5)

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    sub = con.execute(
        "SELECT source_type, payload_meta_json FROM submissions WHERE id=?",
        (sub_id,)).fetchone()
    con.close()
    pm = json.loads(sub["payload_meta_json"] or "{}")
    return {"source_type": sub["source_type"], "meta": pm,
            "sub_id": sub_id}


async def structure_checks(scan_pdf_path: str) -> dict:
    from playwright.async_api import async_playwright
    out: dict = {}
    async with async_playwright() as pw:
        br = await pw.chromium.launch()
        pg = await br.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.add_init_script(
            "localStorage.setItem('babelgrade-lang','fr')")
        await pg.goto(BASE + "/", wait_until="networkidle")
        if await pg.locator("#auth-username").count():
            await pg.fill("#auth-username", "tibo")
            await pg.fill("#auth-password", "test-pw-9876")
            await pg.click("#auth-login-btn")
            await pg.wait_for_load_state("networkidle")
        await pg.evaluate("goEvaluate()")
        await pg.wait_for_selector("#mfield-copy", timeout=8000)

        out["buttons"] = await pg.eval_on_selector_all(
            "#mctrl-copy button[data-mmode]",
            "els=>els.map(e=>e.dataset.mmode)")
        out["default"] = await pg.eval_on_selector(
            "#mfield-copy", "el=>el.dataset.mactive")
        out["pdf_label"] = await pg.eval_on_selector(
            "#mctrl-copy button[data-mmode=pdf]", "e=>e.textContent.trim()")
        # switch to pdf mode, upload, confirm the run-CTA state is set
        await pg.evaluate("setMMode('copy','pdf')")
        await pg.wait_for_selector("#copypdf-file", state="attached",
                                   timeout=4000)
        await pg.set_input_files("#copypdf-file", scan_pdf_path)
        await pg.wait_for_timeout(300)
        out["currentCopyPdf"] = await pg.evaluate(
            "currentCopyPdf?currentCopyPdf.name:null")
        out["pageerrors"] = errs
        await br.close()
    return out


def main() -> int:
    import asyncio
    tmpdir = tempfile.mkdtemp(prefix="bg_copy_pdf_")
    scan_pdf = os.path.join(tmpdir, "copy_scan.pdf")
    make_scanned_pdf(scan_pdf)

    out = {}
    out.update(asyncio.run(structure_checks(scan_pdf)))
    out["persist"] = backend_scan_persist(scan_pdf)

    fails = []
    if out["buttons"] != ["photo", "pdf", "text"]:
        fails.append(f"copy field buttons {out['buttons']} != photo/pdf/text")
    if out["default"] != "photo":
        fails.append(f"default mode {out['default']!r} != photo (PDF must NOT "
                     "be preselected)")
    if not out.get("currentCopyPdf"):
        fails.append("currentCopyPdf not set after PDF upload")
    p = out["persist"]
    if not (p["meta"].get("copy_pdf_name") and p["meta"].get("page_paths")):
        fails.append(f"scanned PDF not persisted (copy_pdf_name + page_paths): "
                     f"{p}")
    if p["source_type"] != "image":
        fails.append(f"source_type {p['source_type']!r} != image")
    if out.get("pageerrors"):
        fails.append(f"page errors: {out['pageerrors'][:2]}")

    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("=" * 44)
    print(f"=== {'FAIL' if fails else 'PASS'} ({len(fails)} failure(s)) ===")
    for f in fails:
        print("  FAIL:", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
