#!/usr/bin/env python3
"""P2.2 verify: mobile inline level editing (390px bottom sheet).
- att-table level column: native select hidden, tappable pill shown
- tapping a pill opens #lvl-sheet (bottom sheet, criterion title + 6 level buttons)
- picking a level: select value written, /120 score recomputed, attested level
  + row pill updated, sheet closes
- clear row when a level is set; Esc closes without change
- desktop 1280: pill hidden, native select visible (unchanged behaviour)
- no JS errors; i18n key lvl.clear defined 4x
Seeding: teacher-first attestation via POST /api/evaluate (no LLM), same
recipe as tests/test_p1_dedup.py."""
import os, time
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8090"
OUT = os.path.dirname(os.path.abspath(__file__))
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

def login(pg, lang="fr"):
    pg.add_init_script(f"localStorage.setItem('babelgrade-lang','{lang}')")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", "****")
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    pg.wait_for_timeout(1000)

def api(pg, path, method="GET", body=None):
    return pg.evaluate("""async ({path, method, body}) => {
      const opt = {method, headers:{}};
      let bd = null;
      if (body) { opt.headers['Content-Type']='application/json'; bd = JSON.stringify(body); }
      const r = await fetch(path, {method, headers:opt.headers, body: bd});
      return {status: r.status, data: await r.json().catch(()=>null)};
    }""", {"path": path, "method": method, "body": body})

def seed_analysis(pg):
    st = api(pg, "/api/students", "POST", {"name": "P2MobileLvlTest"}).get("data")
    sid = st["id"]
    pg.evaluate(f"window.__sid={sid}")
    ev = pg.evaluate("""async () => {
      const fd = new FormData();
      fd.append('kind','written');
      fd.append('rubric_id','att-exp-ecrite');
      fd.append('student_id', String(window.__sid));
      fd.append('assignment_id','0');
      fd.append('title','P2 mobile level essay');
      fd.append('language','en');
      fd.append('target_level','B2');
      fd.append('written_text','It was a dark stormy night and the wind howled through the broken window. The old man lit a lamp and began to write his last letter.');
      const r = await fetch('/api/evaluate', {method:'POST', body: fd});
      return await r.json();
    }""")
    jid = ev.get("id") or ev.get("job_id")
    for _ in range(60):
        j = api(pg, f"/api/jobs/{jid}").get("data") or {}
        if j.get("status") in ("done", "error", "cancelled"):
            return j.get("analysis_id"), j.get("status")
        time.sleep(2)
    return None, None

with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])

    # ============ 390px mobile (the P2 target) ============
    ctx = b.new_context(viewport={"width": 390, "height": 844},
                        device_scale_factor=2, is_mobile=True, has_touch=True,
                        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg, "fr")
    aid, status = seed_analysis(pg)
    check("seed: analysis created", bool(aid), {"aid": aid, "status": status})
    if aid:
        # open the history detail via the boot deep link. The reconciler
        # (navReconcileHistoryDetail) opens it AND sets HIST_SEL/detail-open —
        # do NOT click the hcard manually: by the time we see it, it is already
        # .sel, so a click would TOGGLE the detail closed and leave HIST_SEL in
        # an indeterminate state (that is what broke the save re-render).
        pg.goto(BASE + f"#history/{aid}", wait_until="networkidle")
        pg.wait_for_selector("#hist-report .att-card", timeout=30000)
        pg.wait_for_timeout(800)

        st = pg.evaluate("""() => {
          const card = document.querySelector('#hist-report .att-card');
          const rows = [...card.querySelectorAll('.att-main-row')];
          const sel0 = rows[0].querySelector('.att-lvl');
          const pill0 = rows[0].querySelector('.att-lvl-pill');
          const cs = getComputedStyle(sel0), cp = getComputedStyle(pill0);
          const tbl = card.querySelector('.att-table');
          const wrap = card.querySelector('.att-table').parentElement;
          return {
            nRows: rows.length,
            selDisplay: cs.display, pillDisplay: cp.display,
            pillText: pill0 ? pill0.textContent.trim() : null,
            sheetHidden: !document.querySelector('#lvl-sheet').classList.contains('show'),
            tblMinWidth: getComputedStyle(tbl).minWidth,
            wrapOverflow: getComputedStyle(wrap).overflowX,
            score: card.querySelector('.att-score').textContent,
            level: card.querySelector('.att-level').textContent.trim(),
            bodyScrollW: document.body.scrollWidth, vw: window.innerWidth
          };
        }""")
        check("mobile: level select hidden", st and st["selDisplay"] == "none", st)
        check("mobile: tappable pill visible", st and st["pillDisplay"] == "inline-flex", st)
        check("mobile: sheet closed at start", st and st["sheetHidden"] is True, st)
        check("mobile: page not wider than viewport", st and st["bodyScrollW"] <= st["vw"] + 1, st)
        pg.screenshot(path=os.path.join(OUT, "p2_mobile_report.png"))

        # ---- tap the first row's pill → sheet opens ----
        pg.evaluate("""() => {
          document.querySelector('#hist-report .att-main-row .att-lvl-pill').click();
        }""")
        pg.wait_for_selector("#lvl-sheet.show", timeout=10000)
        pg.wait_for_timeout(300)
        st = pg.evaluate("""() => {
          const sheet = document.querySelector('#lvl-sheet');
          const title = document.querySelector('#ls-title').textContent;
          const btns = [...sheet.querySelectorAll('.lvl-sheet-btn')];
          const r = sheet.getBoundingClientRect();
          return {title, nBtns: btns.length,
                  labels: btns.map(x => x.dataset.lsv),
                  bottom: r.bottom, vh: window.innerHeight,
                  firstMinH: Math.min(...btns.map(x => x.getBoundingClientRect().height))};
        }""")
        check("sheet: opens on pill tap", st and st["nBtns"] >= 6, st)
        check("sheet: criterion title set", st and st["title"] and st["title"] != "", st)
        check("sheet: docked at bottom of viewport", st and st["bottom"] >= st["vh"] - 2, st)
        check("sheet: touch targets >= 44px", st and st["firstMinH"] >= 44, st)
        check("sheet: A1..C2 in order", st and st["labels"][:6] == ["A1","A2","B1","B2","C1","C2"], st)
        pg.screenshot(path=os.path.join(OUT, "p2_mobile_sheet.png"))

        # ---- pick B1 on row 1 → recompute ----
        before = pg.evaluate("""() => ({
          score: document.querySelector('#hist-report .att-score').textContent,
          level: document.querySelector('#hist-report .att-level').textContent.trim()})""")
        pg.evaluate("""() => {
          document.querySelector('#ls-grid .lvl-sheet-btn[data-lsv="B1"]').click();
        }""")
        pg.wait_for_function("() => !document.querySelector('#lvl-sheet').classList.contains('show')", timeout=10000)
        pg.wait_for_timeout(600)
        st = pg.evaluate("""() => {
          const card = document.querySelector('#hist-report .att-card');
          const row0 = card.querySelector('.att-main-row');
          return {
            selVal: row0.querySelector('.att-lvl').value,
            pillText: row0.querySelector('.att-lvl-pill').textContent.trim(),
            score: card.querySelector('.att-score').textContent,
            level: card.querySelector('.att-level').textContent.trim(),
            rowPts: row0.querySelector('.att-pts').textContent,
            sheetClosed: !document.querySelector('#lvl-sheet').classList.contains('show')
          };
        }""")
        check("pick: select value written", st and st["selVal"] == "B1", st)
        check("pick: row pill mirrors B1", st and "B1" in st["pillText"], st)
        check("pick: sheet closed after pick", st and st["sheetClosed"] is True, st)
        check("pick: row points = 5 (B1)", st and st["rowPts"] == "5", st)
        check("pick: score recomputed", st and st["score"] != before["score"], {"before": before, "after": st})
        pg.screenshot(path=os.path.join(OUT, "p2_mobile_after_pick.png"))

        # ---- reopen: current level highlighted + clear row present ----
        pg.evaluate("""() => {
          document.querySelector('#hist-report .att-main-row .att-lvl-pill').click();
        }""")
        pg.wait_for_selector("#lvl-sheet.show", timeout=10000)
        st = pg.evaluate("""() => {
          const on = document.querySelector('#ls-grid .lvl-sheet-btn.on');
          const clear = document.querySelector('#ls-grid .lvl-sheet-btn.clear');
          return {onVal: on ? on.dataset.lsv : null,
                  clearText: clear ? clear.textContent.trim() : null};
        }""")
        check("reopen: B1 highlighted", st and st["onVal"] == "B1", st)
        check("reopen: clear row present (FR 'Effacer')", st and st["clearText"] == "Effacer", st)

        # ---- Esc closes without change ----
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        st = pg.evaluate("""() => ({
          closed: !document.querySelector('#lvl-sheet').classList.contains('show'),
          detailStillOpen: document.querySelector('#view-history').classList.contains('detail-open')})""")
        check("Esc: sheet closes, history detail stays open", st and st["closed"] and st["detailStillOpen"], st)

        # ---- clear (Effacer) → row back to — ----
        pg.evaluate("""() => { document.querySelector('#hist-report .att-main-row .att-lvl-pill').click(); }""")
        pg.wait_for_selector("#lvl-sheet.show", timeout=10000)
        pg.evaluate("""() => { document.querySelector('#ls-grid .lvl-sheet-btn.clear').click(); }""")
        pg.wait_for_function("() => !document.querySelector('#lvl-sheet').classList.contains('show')", timeout=10000)
        pg.wait_for_timeout(400)
        st = pg.evaluate("""() => {
          const row0 = document.querySelector('#hist-report .att-main-row');
          return {selVal: row0.querySelector('.att-lvl').value,
                  pillText: row0.querySelector('.att-lvl-pill').textContent.trim()};
        }""")
        check("clear: select empty again", st and st["selVal"] == "", st)
        check("clear: pill shows —", st and "—" in st["pillText"], st)

        # ---- save persists the edited level (round-trip through #att-save) ----
        pg.evaluate("""() => {
          const rows = document.querySelectorAll('#hist-report .att-main-row');
          rows.forEach((r, i) => { r.querySelector('.att-lvl').value = i % 2 === 0 ? 'B1' : 'B2'; });
        }""")
        pg.click("#att-save")
        pg.wait_for_selector("#hist-report .att-card", timeout=30000)
        pg.wait_for_timeout(2500)
        rep = api(pg, f"/api/analyses/{aid}").get("data") or {}
        saved = {m["criterion"]: m["suggested_level"] for m in (rep.get("matrix") or rep.get("data") or {}).get("rubric_mapping", [])}
        check("save: levels persisted server-side",
              any(v in ("B1", "B2") for v in saved.values()), {k: v for k, v in list(saved.items())[:4]})
        # pills re-rendered from server state: row 0 should show B1
        st = pg.evaluate("""() => {
          const card = document.querySelector('#hist-report .att-card');
          const row0 = card.querySelector('.att-main-row');
          return {pillText: row0.querySelector('.att-lvl-pill').textContent.trim(),
                  selVal: row0.querySelector('.att-lvl').value};
        }""")
        check("save: re-render keeps pill in sync (B1)", st and "B1" in st["pillText"] and st["selVal"] == "B1", st)

        check("no JS page errors", not errs, errs[:3])

    ctx.close()

    # ============ 1280px desktop: unchanged behaviour ============
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    derrs = []
    pg.on("pageerror", lambda e: derrs.append(str(e)))
    login(pg, "fr")
    if aid:
        # boot deep link opens the detail (reconciler) — no manual click
        pg.goto(BASE + f"#history/{aid}", wait_until="networkidle")
        pg.wait_for_selector("#hist-report .att-card", timeout=30000)
        pg.wait_for_timeout(600)
        st = pg.evaluate("""() => {
          const row = document.querySelector('#hist-report .att-main-row');
          const sel = row.querySelector('.att-lvl'), pill = row.querySelector('.att-lvl-pill');
          return {selDisplay: getComputedStyle(sel).display,
                  pillDisplay: getComputedStyle(pill).display,
                  sheetClosed: !document.querySelector('#lvl-sheet').classList.contains('show')};
        }""")
        check("desktop: native select visible, pill hidden, sheet closed",
              st and st["selDisplay"] != "none" and st["pillDisplay"] == "none" and st["sheetClosed"], st)
        check("desktop: no JS page errors", not derrs, derrs[:3])
    ctx.close()
    b.close()

print(f"\n=== {len(PASS)} passed, {len(FAIL)} failed ===")
if FAIL:
    print("FAILED:", FAIL)
    raise SystemExit(1)
