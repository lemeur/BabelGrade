"""Copy-text card + auto-OCR UI — live E2E (read-only).

Regression test for the 2026-11-21 fix: after an AI analysis of a written
photo copy, the Annoter used to say "no OCR yet" even though the teacher just
analyzed the copy. The backend now auto-enqueues the OCR job after every AI
pass (analyze + run-ai), the Annoter follows the in-flight OCR live, and every
report shows a collapsed "Copy transcription" card with the text the AI
actually read.

Checks (read-only on existing OCR'd submissions — nothing is mutated):
 1. report: the copy-text card renders with the OCR pill + transcribed text
    (both the structured-report path AND the "unstructured" bail path —
    the card is submission-level data, shown even when the LLM produced no
    matrix)
 2. Annoter: opens the dual pane (photo + transcript) on an OCR'd copy
 3. Annoter "OCR in progress" state (mocked .ocr endpoint) shows the running
    banner instead of the re-launch button
 4. Annoter "no OCR" state (mocked) still offers the manual re-launch button

Run (live server on :8090 required; needs a written photo submission WITH
ocr_json in the DB — the test discovers one, else fails clearly):
  /tmp/bg_venv/bin/python tests/test_copy_text_card.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import _testpw as T
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8090"

FAILS = []
TOTAL = 0
def check(name, ok, extra=""):
    global TOTAL
    TOTAL += 1
    print(("PASS " if ok else "FAIL ") + name + (f"  [{extra}]" if extra and not ok else ""))
    if not ok:
        FAILS.append(name)

def login(pg):
    pg.goto(BASE, wait_until="networkidle")
    pg.fill("#auth-username", T.USERNAME); pg.fill("#auth-password", T.pw())
    pg.click("#auth-login-btn"); pg.wait_for_timeout(900)
    assert pg.evaluate("document.getElementById('auth-gate').classList.contains('hide')")

def open_hist_detail(pg, aid, timeout=25000):
    """Deep-link the history detail exactly like a row click does. The detail
    head (`.detail-head`) is the reliable "done" marker — the first `.card`
    in #hist-report is the LOADING card, so never wait on that."""
    pg.evaluate("(aid)=>{ navGo('history', aid, {reload:true}); }", str(aid))
    for _ in range(80):
        if pg.evaluate("!!document.querySelector('#hist-report .detail-head')"):
            break
        pg.wait_for_timeout(300)
    else:
        raise AssertionError("#hist-report .detail-head never appeared")
    pg.wait_for_timeout(400)

def find_ocr_submission(pg):
    """Find a written submission with page photos + ocr_json, and its analysis.
    NOTE: /api/analyses list rows are SUBMISSION rows — `id` is the
    submission_id and `analysis_id` the related analysis (may be null)."""
    return pg.evaluate("""async ()=>{
      const an = await (await fetch('/api/analyses?limit=200')).json();
      for (const a of an) {
        const sid = a.id;                 // submission id (list row is a submission)
        const aid = a.analysis_id;        // related analysis id
        if (sid == null) continue;
        const s = await (await fetch('/api/submissions/'+sid)).json();
        if (!s || s.kind !== 'written') continue;
        if (!(s.payload_meta && s.payload_meta.page_paths && s.payload_meta.page_paths.length)) continue;
        const o = await (await fetch('/api/submissions/'+sid+'.ocr')).json();
        if (o.ocr && o.ocr.pages && o.ocr.pages.length)
          return {aid: aid, sid: sid, lines: o.ocr.pages[0].lines.length,
                  hasMatrix: await (async()=>{ try{ const aa=await (await fetch('/api/analyses/'+aid)).json(); return !!aa.matrix; }catch(e){ return null; } })()};
      }
      return null;
    }""")

def open_annot(pg):
    pg.evaluate("""()=>{
      const b=[...document.querySelectorAll('#hist-report [data-annot-open]')].find(x=>x);
      if (b) b.click();
    }""")
    for _ in range(40):
        if pg.evaluate("!document.getElementById('annot').hidden && (ANNOT&&ANNOT.sub)"):
            break
        pg.wait_for_timeout(300)
    pg.wait_for_timeout(400)

def main():
    pw = sync_playwright().start()
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width":1280,"height":900}, locale="en-US")
    pg = ctx.new_page(); errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errs.append("PAGEERROR: " + str(e)))
    try:
        login(pg)
        target = find_ocr_submission(pg)
        check("found an OCR'd written photo submission", target is not None,
              "need a written photo copy with ocr_json in the DB")
        if not target:
            return
        aid, sid = target["aid"], str(target["sid"])
        print(f"    -> submission {sid} (analysis {aid}, {target['lines']} OCR lines, matrix={target['hasMatrix']})")

        # ---- 1) report: copy-text card with OCR text ----
        open_hist_detail(pg, aid)
        card = pg.evaluate("""(sid)=>{
          const c = document.querySelector('#hist-report .copytext-card[data-cts="'+sid+'"]');
          if (!c) return null;
          const pill = c.querySelector('summary .pill');
          const box = c.querySelector('.copytext-box');
          return { present:true, pillOcr: pill?pill.textContent:'', textLen: box?box.textContent.length:0 };
        }""", sid)
        check("report: copy-text card present", bool(card and card["present"]),
              "no .copytext-card[data-cts] in #hist-report")
        if card:
            check("report: card shows the OCR source pill", "OCR" in card["pillOcr"],
                  f"pill={card['pillOcr']!r}")
            check("report: card contains the transcribed text", card["textLen"] > 30,
                  f"textLen={card['textLen']}")
            pg.evaluate("""(sid)=>{ const c=document.querySelector('.copytext-card[data-cts="'+sid+'"]');
              const d=c.querySelector('details'); if(d && !d.open){ d.open=true; d.dispatchEvent(new Event('toggle')); } }""", sid)
            pg.wait_for_timeout(150)
            vis = pg.evaluate("""(sid)=>{ const b=document.querySelector('.copytext-card[data-cts="'+sid+'"] .copytext-box');
              return b && getComputedStyle(b).display !== 'none' ? b.textContent.trim().length : 0; }""", sid)
            check("report: OCR text visible when expanded", vis > 30, f"visibleLen={vis}")
        js_errs_mid = [e for e in errs if "favicon" not in e.lower()]
        check("report: no JS console errors", not js_errs_mid, str(js_errs_mid[:3]))

        # ---- 2) Annoter opens the dual pane on an OCR'd copy ----
        open_annot(pg)
        st = pg.evaluate("""()=>({ hidden: document.getElementById('annot').hidden,
          ocrPages: ANNOT && ANNOT.ocr ? ANNOT.ocr.pages.length : 0,
          dual: !!document.querySelector('#an-written .an-dual'),
          running: ANNOT ? ANNOT.ocrRunning : null })""")
        check("annoter: overlay open", st["hidden"] is False, str(st))
        check("annoter: has OCR pages", st["ocrPages"] >= 1, str(st))
        check("annoter: dual pane rendered", st["dual"] is True, str(st))
        check("annoter: not in running state (OCR done)", st["running"] is False, str(st))
        pg.evaluate("anClose()"); pg.wait_for_timeout(300)

        # ---- 3) Annoter "OCR in progress" state (mocked .ocr endpoint) ----
        # The app fetches `/api/submissions/{id}.ocr` — note the DOT, not /ocr.
        mock_url = BASE + f"/api/submissions/{sid}.ocr"

        def run_handler(r):
            return r.fulfill(
                status=200, content_type="application/json",
                body='{"submission_id":1,"ocr":null,"running":true,"job_id":99999}')
        pg.route(mock_url, run_handler)
        try:
            open_hist_detail(pg, aid)
            open_annot(pg)
            running = pg.evaluate("""()=>({ running: ANNOT ? ANNOT.ocrRunning : null,
              bodyText: document.getElementById('an-written').textContent,
              hasRelaunchBtn: !!document.querySelector('#an-written [data-annocr]') })""")
            check("annoter (mocked running): ocrRunning flag", running["running"] is True, str(running))
            bt = running["bodyText"].lower()
            check("annoter (mocked running): shows in-progress text",
                  ("in progress" in bt or "en cours" in bt or "running" in bt),
                  f"body={running['bodyText'][:80]!r}")
            check("annoter (mocked running): NO re-launch button (would 409)",
                  running["hasRelaunchBtn"] is False, str(running["hasRelaunchBtn"]))
            pg.evaluate("anClose()"); pg.wait_for_timeout(300)
        finally:
            pg.unroute(mock_url, run_handler)

        # ---- 4) Annoter "no OCR, not running" state (mocked) keeps the button ----
        def none_handler(r):
            return r.fulfill(
                status=200, content_type="application/json",
                body='{"submission_id":1,"ocr":null,"running":false,"job_id":null}')
        pg.route(mock_url, none_handler)
        try:
            open_hist_detail(pg, aid)
            open_annot(pg)
            noocr = pg.evaluate("""()=>({ hasRelaunchBtn: !!document.querySelector('#an-written [data-annocr]'),
              bodyText: document.getElementById('an-written').textContent })""")
            check("annoter (mocked no-OCR): re-launch button present",
                  noocr["hasRelaunchBtn"] is True, str(noocr))
            pg.evaluate("anClose()"); pg.wait_for_timeout(300)
        finally:
            pg.unroute(mock_url, none_handler)

        js_errs = [e for e in errs if "favicon" not in e.lower()]
        check("no JS console errors (final)", not js_errs, str(js_errs[:3]))

    finally:
        pg.close(); b.close(); pw.stop()

    print("\n%d/%d checks passed" % (TOTAL - len(FAILS), TOTAL))
    print("FAILED:", FAILS if FAILS else "none")
    sys.exit(1 if FAILS else 0)

if __name__ == "__main__":
    main()
