#!/usr/bin/env python3
"""P1.2 verify: dedup in the report + history detail.
- attestation card WITHOUT AI opinion: no "IA" column header, no .ai-cell,
  no "Note /20 : —" placeholder
- after saving levels + /20 note: "Note /20 : 14" appears in the essentials
  band AND the detail header shows a labelled "Résultat B1" pill next to
  the "Cible : B2" pill (no bare unlabeled level pill)
- no JS errors; i18n keys rep.levelLbl + ai.noOpHint defined 4x"""
import re, time
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8090"
OUT = __file__.replace('\\','/')
import os
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

def api(pg, path, method="GET", body=None, form=False):
    return pg.evaluate("""async ({path, method, body, form}) => {
      const opt = {method, headers:{}};
      let bd = null;
      if (body) { if (form) { bd = body; } else { opt.headers['Content-Type']='application/json'; bd = JSON.stringify(body); } }
      const r = await fetch(path, {method, headers:opt.headers, body: bd});
      return {status: r.status, data: await r.json().catch(()=>null)};
    }""", {"path": path, "method": method, "body": body, "form": form})

with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg, "fr")

    # ---- seed a real teacher-first evaluation (no LLM, no AI opinion) ----
    st = api(pg, "/api/students", "POST", {"name": "P1DedupTest"}).get("data")
    sid = st["id"]
    pg.evaluate(f"window.__sid={sid}")
    ev = pg.evaluate("""async () => {
      const fd = new FormData();
      fd.append('kind','written');
      fd.append('rubric_id','att-exp-ecrite');
      fd.append('student_id', String(window.__sid));
      fd.append('assignment_id','0');
      fd.append('title','P1 dedup essay');
      fd.append('language','en');
      fd.append('target_level','B2');
      fd.append('written_text','It was a dark stormy night and the wind howled through the broken window. The old man lit a lamp and began to write his last letter, his hand trembling as he shaped each careful word on the yellowed paper.');
      const r = await fetch('/api/evaluate', {method:'POST', body: fd});
      return await r.json();
    }""")
    check("seed: /api/evaluate returns job", isinstance(ev, dict) and ("id" in ev or "job_id" in ev), ev)
    jid = ev.get("id") or ev.get("job_id")
    done = None
    for _ in range(60):
        j = api(pg, f"/api/jobs/{jid}").get("data") or {}
        if j.get("status") in ("done", "error", "cancelled"):
            done = j; break
        time.sleep(2)
    check("seed: job finished", done and done["status"] == "done", done and done.get("status"))
    aid = done.get("analysis_id")
    check("seed: analysis id", bool(aid), aid)
    rep = api(pg, f"/api/analyses/{aid}").get("data")
    check("seed: report has attestation + NO ai_data",
          rep and rep.get("attestation") and not rep.get("ai_matrix"),
          {"att": bool(rep and rep.get("attestation")), "ai": bool(rep and rep.get("ai_matrix"))})

    # ---- 1) open history detail from scratch: no IA column, no /20 mini ----
    pg.evaluate("() => { location.hash = '#history'; }")
    pg.wait_for_selector(f"#hist [data-aid='{aid}'], #hist-cards [data-aid='{aid}']", timeout=30000)
    pg.evaluate(f"""() => {{
      const row = document.querySelector('#hist [data-aid="{aid}"], #hist-cards [data-aid="{aid}"]');
      row.click();
    }}""")
    pg.wait_for_selector("#hist-report .att-card", timeout=30000)
    pg.wait_for_timeout(800)
    st = pg.evaluate("""() => {
      const rep = document.querySelector('#hist-report .att-card');
      if (!rep) return null;
      const head = [...rep.querySelectorAll('thead th')].map(x => x.textContent.trim());
      const aiCell = rep.querySelector('.att-main-row .ai-cell');
      const mini = rep.querySelector('.n20mini');
      const pills = [...document.querySelectorAll('#hist-report .detail-head .pill')].map(p => p.textContent.trim());
      return {head, hasAiCell: !!aiCell, hasMini: !!mini, pills,
              resultPill: pills.find(p => p.startsWith('Résultat')) || null,
              targetPill: pills.find(p => p.startsWith('Cible')) || null};
    }""")
    check("FR: attestation header has NO 'IA' column", st and 'IA' not in st["head"], st and st["head"])
    check("FR: no .ai-cell in rows", st and st["hasAiCell"] is False, st)
    check("FR: no 'Note /20 : —' placeholder (no note stored)", st and st["hasMini"] is False, st)
    check("FR: target pill present (Cible : B2)", st and st["targetPill"], st and st["targetPill"])
    check("FR: no bare 'Résultat' pill yet (no levels saved)", st and st["resultPill"] is None, st)
    pg.screenshot(path=os.path.join(OUT, "p12_report_no_ai.png"))

    # ---- 2) save levels + /20 note → essentials band + labelled result pill ----
    pg.evaluate("""() => {
      const card = document.querySelector('#hist-report .att-card');
      card.querySelectorAll('select.att-lvl').forEach((s, i) => { s.value = i % 3 === 0 ? 'B1' : 'B2'; });
      const inp = document.querySelector('#hist-report .n20-in');
      inp.value = '14'; inp.dispatchEvent(new Event('input'));
    }""")
    pg.click('#att-save')
    pg.wait_for_selector("#hist-report .att-card", timeout=30000)
    pg.wait_for_timeout(2000)
    st = pg.evaluate("""() => {
      const rep = document.querySelector('#hist-report .att-card');
      const mini = rep.querySelector('.n20mini');
      const miniNote = rep.querySelector('.n20mini-note');
      const head = [...rep.querySelectorAll('thead th')].map(x => x.textContent.trim());
      return {miniText: mini ? mini.textContent.trim() : null, miniNote: miniNote ? miniNote.textContent.trim() : null,
              head};
    }""")
    check("FR: after save, 'Note /20 : 14' in essentials band", st and st["miniText"] and "14" in st["miniText"], st and st["miniText"])
    # NOTE: first save with validate=true makes the backend snapshot the
    # teacher's matrix into ai_matrix_json (revert feature) — so the IA column
    # MAY legitimately reappear showing the snapshot levels (not "–").
    if 'IA' in st["head"]:
        cells = pg.evaluate("""() => [...document.querySelectorAll('#hist-report .att-main-row .ai-cell')].map(c => c.textContent.trim())""")
        check("FR: IA column (snapshot) cells are NOT bare '–'",
              cells and any(c and c != '–' for c in cells), cells)
    else:
        check("FR: still no IA column (no AI ran)", True)
    # close + reopen the detail so the header re-reads the FRESH list row
    # (overall_level was persisted by the save above)
    pg.click('#hist-close')
    pg.wait_for_timeout(800)
    pg.wait_for_selector(f"#hist [data-aid='{aid}'], #hist-cards [data-aid='{aid}']", timeout=30000)
    pg.evaluate(f"""() => {{
      const row = document.querySelector('#hist [data-aid="{aid}"], #hist-cards [data-aid="{aid}"]');
      row.click();
    }}""")
    pg.wait_for_selector("#hist-report .att-card", timeout=30000)
    pg.wait_for_timeout(800)
    st = pg.evaluate("""() => {
      const pills = [...document.querySelectorAll('#hist-report .detail-head .pill')].map(p => p.textContent.trim());
      const resultPill = pills.find(p => p.startsWith('Résultat'));
      return {resultPill, targetPill: pills.find(p => p.startsWith('Cible')) || null,
              detailHeadLevelPills: document.querySelectorAll('#hist-report .detail-head .level').length};
    }""")
    check("FR: reopen: 'Résultat B1' labelled pill in detail head", st and st["resultPill"] and "B1" in st["resultPill"], st and st["resultPill"])
    check("FR: 'Cible : B2' pill still present (labelled, not bare)", st and st["targetPill"], st and st["targetPill"])
    check("FR: detail head has exactly two level pills (Cible + Résultat, no bare dup)",
          st and st["detailHeadLevelPills"] == 2, st and st["detailHeadLevelPills"])
    check("FR: no JS errors", not errs, errs[:3])
    pg.screenshot(path=os.path.join(OUT, "p12_report_after_save.png"))
    ctx.close()
    b.close()

# i18n balance
html = open(os.path.join(OUT, '..', 'static', 'index.html')).read()
for key in ["rep.levelLbl", "ai.noOpHint"]:
    n = len(re.findall(re.escape(key) + "':'", html))
    check(f"i18n key '{key}' defined 4x", n == 4, n)

print(f"\n=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
if FAIL: print("FAILED:", FAIL)
