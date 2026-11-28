#!/usr/bin/env python3
"""P1.1 verify: evaluator accordion (replaces the old 4-chip stepper, 2026-11-28).
- the 4 steps ARE the form: 4 .acc-item headers, step 1 open by default,
  the others collapsed (grid 0fr, height 0) but still in the DOM
- .wz-steps is sticky under the header
- clicking a step header opens it; a collapsed panel gets height 0
- 'advanced options' <details> panels exist in step 2 (accommodations) and
  step 4 (evaluation notes) and are collapsed by default
- P0.5 regression: '*' markers still on Rubric + work title; empty rubric #run
  still flashes #settings-panel with the i18n toast (guards untouched)
- no JS errors; wz.next/wz.of + wiz.* keys defined 4x each
"""
import os, re
import _testpw as TESTPW
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
    pg.wait_for_selector("#auth-gate", state="attached", timeout=20000)
    pg.wait_for_timeout(400)
    if pg.evaluate("() => { const g=document.getElementById('auth-gate'); return g && !g.classList.contains('hide'); }"):
        pg.wait_for_selector("#auth-username", state="visible")
        pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", TESTPW.pw())
        pg.click("#auth-login-btn")
        pg.wait_for_function("() => document.getElementById('auth-gate').classList.contains('hide')", timeout=20000)
    pg.wait_for_timeout(600)

def goto_eval(pg):
    pg.evaluate("() => { location.hash = '#evaluator'; }")
    pg.wait_for_timeout(1000)
    pg.wait_for_selector("#view-analyze:not(.hide)", timeout=20000)

def toast_text(pg):
    return pg.evaluate("() => { const el=document.querySelector('#toast'); return el?{text:el.textContent, show:el.classList.contains('show')}:null; }")

with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])

    # ---------- EN desktop ----------
    print("== EN desktop ==")
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg, "en")
    goto_eval(pg)

    st = pg.evaluate("""() => {
      const items=[...document.querySelectorAll('#wz-steps .acc-item')];
      const open=document.querySelector('#wz-steps .acc-item.open');
      const s1=document.querySelector('.acc-item[data-step="1"] .acc-body');
      const s2=document.querySelector('.acc-item[data-step="2"] .acc-body');
      return {
        n: items.length,
        labels: items.map(it=>it.querySelector('.wz-lab').textContent.trim()),
        sticky: getComputedStyle(document.querySelector('#wz-steps')).position,
        openStep: open?+open.dataset.step:null,
        s1h: s1.offsetHeight, s2h: s2.offsetHeight,
        details: document.querySelectorAll('#view-analyze details.opts-panel').length,
        detailsOpen: [...document.querySelectorAll('#view-analyze details.opts-panel')].filter(d=>d.open).length,
        accInDetails: !!document.querySelector('#view-analyze details #accommodations'),
        evalInDetails: !!document.querySelector('#view-analyze details #mfield-eval'),
        panelsInDom: ['#what-panel','#who-panel','#work-panel','#settings-panel']
          .every(sel=>{const el=document.querySelector(sel); return el && !el.classList.contains('hide');})
      };
    }""")
    check("accordion: 4 step items", st["n"] == 4, st["labels"])
    check("accordion: EN labels", st["labels"][0] == "Assignment" and "Student" in st["labels"][1]
          and "work" in st["labels"][2] and st["labels"][3] == "Rubric", st["labels"])
    check("accordion: .wz-steps sticky under header", st["sticky"] == "sticky", st["sticky"])
    check("accordion: step 1 open on entry", st["openStep"] == 1, st["openStep"])
    check("accordion: step 1 open (height>0), step 2 collapsed (height 0)",
          st["s1h"] > 0 and st["s2h"] == 0, (st["s1h"], st["s2h"]))
    check("all 4 step panels stay in DOM, none .hide (P0.5 guard)", st["panelsInDom"], st["panelsInDom"])
    check("advanced options: 2 <details> (accommodations + eval notes)", st["details"] == 2, st["details"])
    check("advanced options: collapsed by default", st["detailsOpen"] == 0, st["detailsOpen"])
    check("accommodations lives inside a <details>", st["accInDetails"], st["accInDetails"])
    check("eval notes live inside a <details>", st["evalInDetails"], st["evalInDetails"])

    # jump: click header 3 -> work panel opens
    pg.click('.acc-hd[data-wz-hd="3"]')
    pg.wait_for_timeout(400)
    top3 = pg.evaluate("() => { const o=document.querySelector('#wz-steps .acc-item.open'); return o?+o.dataset.step:null; }")
    wh3 = pg.evaluate("() => document.querySelector('.acc-item[data-step=\"3\"] .acc-body').offsetHeight")
    check("header click opens step 3", top3 == 3, top3)
    check("step 3 open after click (height>0)", wh3 > 0, wh3)

    # P0.5 regression: markers + guard untouched
    m = pg.evaluate("""() => {
      const rubricLabel = document.querySelector('label[data-i18n="an.rubric"]');
      const workTitle = document.querySelector('#work-panel h2');
      return {
        rubricStar: rubricLabel ? rubricLabel.querySelector('.req') !== null : null,
        workStar: workTitle ? workTitle.querySelector('.req') !== null : null
      };
    }""")
    check("P0.5 regression: '*' on Rubric label", m["rubricStar"] is True, m)
    check("P0.5 regression: '*' on work card title", m["workStar"] is True, m)
    pg.evaluate("() => { document.querySelector('#rubric').value=''; }")
    pg.click('#run')
    pg.wait_for_timeout(700)
    st2 = pg.evaluate("() => ({flash:document.querySelector('#settings-panel').classList.contains('req-flash'),"
                      "open:document.querySelector('.acc-item.open')?.dataset.step})")
    tt = toast_text(pg)
    check("P0.5 regression: empty rubric -> settings flash", st2["flash"], st2)
    check("P0.5 regression: guard re-opened step 4 (settings)", str(st2["open"]) == "4", st2["open"])
    check("P0.5 regression: empty rubric -> EN toast", tt and "rubric" in tt["text"].lower(), tt)
    check("EN: no page errors", not errs, errs[:2])
    pg.screenshot(path=os.path.join(OUT, "p11_evaluator_en.png"))
    pg.close(); ctx.close()

    # ---------- FR desktop: labels + toast language ----------
    print("== FR desktop ==")
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg, "fr")
    goto_eval(pg)
    st = pg.evaluate("""() => ({labels:[...document.querySelectorAll('#wz-steps .wz-lab')].map(c=>c.textContent.trim()),
      next: document.querySelector('#what-panel .wz-next span[data-i18n]').textContent.trim(),
      adv: [...document.querySelectorAll('#view-analyze details.opts-panel summary')].map(s=>s.textContent.trim())})""")
    check("FR: step labels translated", st["labels"][0] == "Sujet" and "Élève" in st["labels"][1]
          and st["labels"][3] == "Grille", st["labels"])
    check("FR: Next button translated (Étape suivante)", st["next"] == "Étape suivante", st["next"])
    check("FR: advanced options labels translated", "Niveau spécifique et aménagements" in st["adv"][0]
          and "Consignes" in st["adv"][1], st["adv"])
    pg.evaluate("() => { document.querySelector('#rubric').value=''; }")
    pg.click('#run')
    pg.wait_for_timeout(700)
    tt = toast_text(pg)
    check("FR: empty rubric -> FR toast (grille)", tt and "grille" in tt["text"].lower(), tt)
    check("FR: no page errors", not errs, errs[:2])
    pg.screenshot(path=os.path.join(OUT, "p11_evaluator_fr.png"))
    pg.close(); ctx.close()

    # ---------- static: i18n balance ----------
    html = open(os.path.join(OUT, "..", "static", "index.html"), encoding="utf-8").read()
    keys = ["wiz.s1","wiz.s2","wiz.s3","wiz.s4","wiz.specificOpts","wiz.evalNotes","wz.next","wz.of"]
    counts = {k: len(re.findall(r"'\s*" + re.escape(k) + r"\s*':", html)) for k in keys}
    check("i18n: 8 accordion/wizard keys defined 4x each", all(v == 4 for v in counts.values()), counts)

    b.close()

print(f"\n{len(PASS)}/{len(PASS)+len(FAIL)} checks passed")
if FAIL:
    print("FAILED:", FAIL)
    raise SystemExit(1)
print("ALL OK")
