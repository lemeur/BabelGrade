#!/usr/bin/env python3
"""P3 verify: teacher ergonomics — 3 points (2026-10-15).

P3.1 Sujets resource badges:
- i18n keys td.pdf/td.ph/td.pages/td.audio defined 4x each
- Sujets table renders localized .res-badge pills (Consigne / Document source /
  Consignes d'évaluation …) with title tooltips — NO raw EN abbreviations
  (instr / doc / eval / 'instr PDF' …)
- bare subject row shows the td.noMedia muted label
- language switch FR→EN re-localizes the badges (applyI18n → renderAssignmentsTable)
P3.2 Students toolbar mobile labels:
- .st-lbl hidden on desktop, visible on phones; texts = short i18n keys
  (Ajouter / Purger / Exporter / Importer in FR), re-pointed on lang switch
P3.3 #lvl-sheet polish:
- grab handle ::before content !== 'none', ✕ close rect >= 44x44

Seeding: two assignments via FormData POST /api/assignments
(app/main.py create_assignment — POST is Form/FormData, NOT JSON) +
teacher-first attestation via POST /api/evaluate (P2 recipe) for the sheet.
Teardown: DELETE both assignments + the analysis at the end."""
import os, time
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8090"
OUT = os.path.dirname(os.path.abspath(__file__))
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

def login(pg, lang="fr"):
    pg.add_init_script(f"localStorage.setItem('elt-lang','{lang}')")
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

def seed_assignments(pg):
    """FormData POST — the real contract of POST /api/assignments."""
    return pg.evaluate("""async () => {
      const fd1 = new FormData();
      fd1.append('name','P3 res subject');
      fd1.append('instruction','Read the text and answer the questions.');
      fd1.append('eval_notes','Check coherence and language accuracy.');
      fd1.append('target_level','B2');
      const r1 = await fetch('/api/assignments',{method:'POST',body:fd1});
      const a1 = await r1.json();
      const fd2 = new FormData();
      fd2.append('name','P3 bare subject');
      fd2.append('target_level','A2');
      const r2 = await fetch('/api/assignments',{method:'POST',body:fd2});
      const a2 = await r2.json();
      return {a1: a1.id, a2: a2.id, s1: r1.status, s2: r2.status};
    }""")

def seed_analysis(pg):
    st = api(pg, "/api/students", "POST", {"name": "P3ErgoTest"}).get("data")
    sid = st["id"]
    pg.evaluate(f"window.__sid={sid}")
    ev = pg.evaluate("""async () => {
      const fd = new FormData();
      fd.append('kind','written');
      fd.append('rubric_id','att-exp-ecrite');
      fd.append('student_id', String(window.__sid));
      fd.append('assignment_id','0');
      fd.append('title','P3 ergo essay');
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
            return j.get("analysis_id"), j.get("status"), sid
        time.sleep(2)
    return None, None, sid

with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])

    # ============ 1280px desktop (FR) ============
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg, "fr")
    s = seed_assignments(pg)
    check("seed: two assignments created", s["s1"] == 200 and s["s2"] == 200, s)
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector("#assignments tbody tr", timeout=20000)
    pg.wait_for_timeout(500)
    st = pg.evaluate("""() => {
      const rows = [...document.querySelectorAll('#assignments tbody tr')];
      const resRow = rows.find(r => r.textContent.includes('P3 res subject'));
      const bareRow = rows.find(r => r.textContent.includes('P3 bare subject'));
      const badges = resRow ? [...resRow.querySelectorAll('.res-badge')] : [];
      const rawEn = [...document.querySelectorAll('#assignments .res-badge')]
        .filter(x => /^(instr|doc|eval|instr PDF|doc PDF)$/.test(x.textContent.trim()));
      return {
        nRows: rows.length,
        resLabels: badges.map(x => x.textContent.trim()),
        resTitles: badges.map(x => x.title),
        rawEnTexts: rawEn.map(x => x.textContent.trim()),
        bareMuted: bareRow ? bareRow.querySelector('td:nth-child(4)').textContent.trim() : null
      };
    }""")
    check("desktop: res subject row has badges", st and st["nRows"] >= 2 and len(st["resLabels"]) == 2, st)
    check("desktop: FR labels localized (Consigne + Consignes d’évaluation)",
          st and "Consigne" in st["resLabels"] and any(lb.startswith("Consignes d’évaluation") for lb in st["resLabels"]), st["resLabels"])
    check("desktop: no raw EN abbreviations", st and len(st["rawEnTexts"]) == 0, st["rawEnTexts"])
    check("desktop: badge title == label (tooltip)", st and all(tl == lb for tl, lb in zip(st["resTitles"], st["resLabels"])), st)
    check("desktop: bare row shows td.noMedia", st and st["bareMuted"] == "texte uniquement / rien", st["bareMuted"])

    # P3.2 desktop: labels hidden, tooltips intact
    st = pg.evaluate("""() => {
      const add = document.querySelector('#s-add-tgl');
      const lbl = add.querySelector('.st-lbl');
      return {lblDisplay: getComputedStyle(lbl).display, addTitle: add.title};
    }""")
    check("P3.2 desktop: .st-lbl hidden", st and st["lblDisplay"] == "none", st)
    check("P3.2 desktop: tooltip stays the long sentence", st and st["addTitle"] == "Ajouter un élève", st)

    # detail modal badges (asgd-res)
    pg.evaluate("""() => {
      const row = [...document.querySelectorAll('#assignments tbody tr')].find(r => r.textContent.includes('P3 res subject'));
      row.querySelector('button[data-assignview]').click();
    }""")
    ok = pg.wait_for_selector("#assignment-detail-overlay:not(.hide)", timeout=5000)
    if ok:
        st = pg.evaluate("""() => {
          const c = document.querySelector('#asgd-res');
          return {labels: [...c.querySelectorAll('.res-badge')].map(x => x.textContent.trim())};
        }""")
        check("detail modal: res badges rendered (FR)", st and "Consigne" in st["labels"], st["labels"])
        pg.screenshot(path=os.path.join(OUT, "p31_detail_fr.png"))
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
    else:
        check("detail modal: res badges rendered (FR)", False, "modal did not open")

    # language switch FR→EN re-localizes the table badges (applyI18n path) —
    # go through the IN-APP flag menu (real user path; a reload would re-apply
    # the add_init_script and force FR back, defeating the test)
    pg.evaluate("document.querySelector('#lang-tgl').click()")
    pg.wait_for_selector("#menu-lang:not(.hide)", timeout=5000)
    pg.evaluate("document.querySelector('#menu-lang [data-lang=\"en\"]').click()")
    pg.wait_for_selector("#assignments tbody tr", timeout=20000)
    pg.wait_for_timeout(500)
    st = pg.evaluate("""() => {
      const row = [...document.querySelectorAll('#assignments tbody tr')].find(r => r.textContent.includes('P3 res subject'));
      const bareRow = [...document.querySelectorAll('#assignments tbody tr')].find(r => r.textContent.includes('P3 bare subject'));
      return {labels: row ? [...row.querySelectorAll('.res-badge')].map(x => x.textContent.trim()) : [],
              bareMuted: bareRow ? bareRow.querySelector('td:nth-child(4)').textContent.trim() : null};
    }""")
    check("lang switch: badges re-localized to EN (Instruction + Evaluation instructions)",
          st and "Instruction" in st["labels"] and "Evaluation instructions" in st["labels"], st["labels"])
    check("lang switch: bare row EN label", st and st["bareMuted"] == "text only / none", st["bareMuted"])
    check("desktop: no JS page errors", not errs, errs[:3])
    ctx.close()

    # ============ 390px mobile (FR) ============
    ctx = b.new_context(viewport={"width": 390, "height": 844},
                        device_scale_factor=2, is_mobile=True, has_touch=True,
                        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
    pg = ctx.new_page()
    merrs = []
    pg.on("pageerror", lambda e: merrs.append(str(e)))
    login(pg, "fr")

    # P3.2 mobile: visible labels
    pg.evaluate("document.querySelector('#nav button[data-view=\"students\"]').click()")
    pg.wait_for_timeout(500)
    st = pg.evaluate("""() => {
      const out = {};
      for (const id of ['s-add-tgl','s-purge-tgl','s-export','s-import']) {
        const b = document.querySelector('#' + id);
        const l = b.querySelector('.st-lbl');
        out[id] = {display: getComputedStyle(l).display, text: l.textContent.trim(), title: b.title};
      }
      return out;
    }""")
    check("P3.2 mobile: all 4 labels visible", st and all(v["display"] == "inline" for v in st.values()), st)
    check("P3.2 mobile: FR short labels",
          st and st["s-add-tgl"]["text"] == "Ajouter" and st["s-purge-tgl"]["text"] == "Purger"
          and st["s-export"]["text"] == "Exporter" and st["s-import"]["text"] == "Importer", st)
    check("P3.2 mobile: tooltips stay long sentences",
          st and st["s-purge-tgl"]["title"] == "Purger par préfixe de classe", st["s-purge-tgl"]["title"])
    pg.screenshot(path=os.path.join(OUT, "p32_toolbar_mobile.png"))

    # P3.3: open the sheet on the seeded analysis
    aid, status, sid = seed_analysis(pg)
    check("seed: analysis created", bool(aid), {"aid": aid, "status": status})
    if aid:
        pg.goto(BASE + f"#history/{aid}", wait_until="networkidle")
        pg.wait_for_selector("#hist-report .att-card", timeout=30000)
        pg.wait_for_timeout(800)
        pg.evaluate("""() => {
          document.querySelector('#hist-report .att-main-row .att-lvl-pill').click();
        }""")
        pg.wait_for_selector("#lvl-sheet.show", timeout=10000)
        pg.wait_for_timeout(300)
        st = pg.evaluate("""() => {
          const sheet = document.querySelector('#lvl-sheet');
          const before = getComputedStyle(sheet, '::before');
          const close = document.querySelector('#lvl-sheet .ls-close');
          const r = close.getBoundingClientRect();
          return {beforeContent: before.content, beforeW: before.width,
                  closeW: Math.round(r.width), closeH: Math.round(r.height),
                  bodyScrollW: document.body.scrollWidth, vw: window.innerWidth};
        }""")
        check("P3.3: grab handle present (::before content)", st and st["beforeContent"] not in ("none", ""), st)
        check("P3.3: handle width 36px", st and st["beforeW"] in ("36px", "35px", "37px"), st["beforeW"])
        check("P3.3: close button >= 44x44", st and st["closeW"] >= 44 and st["closeH"] >= 44, st)
        check("mobile: page not wider than viewport (sheet open)", st and st["bodyScrollW"] <= st["vw"] + 1, st)
        pg.screenshot(path=os.path.join(OUT, "p33_sheet_handle.png"))
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)

        # P3.1 on mobile: Sujets table badges wrap, no overflow
        pg.evaluate("document.querySelector('#nav button[data-view=\"assignments\"]').click()")
        pg.wait_for_selector("#assignments tbody tr", timeout=20000)
        pg.wait_for_timeout(500)
        st = pg.evaluate("""() => {
          const row = [...document.querySelectorAll('#assignments tbody tr')].find(r => r.textContent.includes('P3 res subject'));
          const tbl = document.querySelector('#view-assignments .tbl-wrap');
          return {nBadges: row ? row.querySelectorAll('.res-badge').length : 0,
                  bodyScrollW: document.body.scrollWidth, vw: window.innerWidth};
        }""")
        check("mobile: res badges present in table", st and st["nBadges"] == 2, st)
        check("mobile: Sujets table fits 390px (no body overflow)", st and st["bodyScrollW"] <= st["vw"] + 1, st)
        pg.screenshot(path=os.path.join(OUT, "p31_sujets_mobile.png"))
        check("mobile: no JS page errors", not merrs, merrs[:3])
    ctx.close()

    # ============ teardown: delete seeded rows ============
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    login(pg, "fr")
    if aid:
        api(pg, f"/api/analyses/{aid}", "DELETE")
    for key in ("a1", "a2"):
        r = api(pg, f"/api/assignments/{s[key]}", "DELETE")
        check(f"teardown: delete {key}", r["status"] in (200, 204), r)
    ctx.close()
    b.close()

print(f"\n=== {len(PASS)} passed, {len(FAIL)} failed ===")
if FAIL:
    print("FAILED:", FAIL)
    raise SystemExit(1)
