#!/usr/bin/env python3
"""P1.1 verify: 4-step wizard on the evaluator path.
- stepper card visible with 4 chips (EN + FR), labelled via i18n
- chips jump to their step panel (scrollIntoView -> panel top near viewport top)
- scroll-spy: active chip follows the panel scrolled into view
- 'advanced options' <details> panels exist in step 2 (accommodations) and step 4
  (evaluation notes) and are collapsed by default
- P0.5 regression: '*' markers still on Rubric + work title; empty rubric #run
  still flashes #settings-panel with the i18n toast (guards untouched)
- no JS errors; wiz.* keys defined 4x"""
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
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", TESTPW.pw())
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    pg.wait_for_timeout(800)

def toast_text(pg):
    return pg.evaluate("() => { const el=document.querySelector('.toast'); return el?{text:el.textContent, show:el.classList.contains('show')}:null; }")

with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])

    # ---------- EN desktop ----------
    print("== EN desktop ==")
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg, "en")
    pg.evaluate("() => { location.hash = '#evaluator'; }")
    pg.wait_for_timeout(1200)

    st = pg.evaluate("""() => {
      const chips=[...document.querySelectorAll('.wiz-chip[data-wiz-go]')];
      return {
        n: chips.length,
        labels: chips.map(c=>c.textContent.trim()),
        sticky: getComputedStyle(document.querySelector('#view-analyze .wiz-card')).position,
        onIdx: chips.findIndex(c=>c.classList.contains('on')),
        details: document.querySelectorAll('#view-analyze details.opts-panel').length,
        detailsOpen: [...document.querySelectorAll('#view-analyze details.opts-panel')].filter(d=>d.open).length,
        accInDetails: !!document.querySelector('#view-analyze details #accommodations'),
        evalInDetails: !!document.querySelector('#view-analyze details #mfield-eval'),
        panelsVisible: ['#what-panel','#who-panel','#work-panel','#settings-panel']
          .every(sel=>{const el=document.querySelector(sel); return el && !el.classList.contains('hide');})
      };
    }""")
    check("stepper: 4 chips", st["n"] == 4, st["labels"])
    check("stepper: EN labels", st["labels"][0] == "Assignment" and "Student" in st["labels"][1]
          and "work" in st["labels"][2] and st["labels"][3] == "Rubric", st["labels"])
    check("stepper: sticky under header", st["sticky"] == "sticky", st["sticky"])
    check("stepper: step 1 active on entry", st["onIdx"] == 0, st["onIdx"])
    check("all 4 step panels stay visible (P0.5 guard)", st["panelsVisible"], st["panelsVisible"])
    check("advanced options: 2 <details> (accommodations + eval notes)", st["details"] == 2, st["details"])
    check("advanced options: collapsed by default", st["detailsOpen"] == 0, st["detailsOpen"])
    check("accommodations lives inside a <details>", st["accInDetails"], st["accInDetails"])
    check("eval notes live inside a <details>", st["evalInDetails"], st["evalInDetails"])

    # jump: click chip 3 -> work panel near viewport top
    pg.click(".wiz-chip[data-wiz-go='3']")
    pg.wait_for_timeout(900)
    top3 = pg.evaluate("() => document.getElementById('work-panel').getBoundingClientRect().top")
    check("chip 3 jumps to work panel", 40 <= top3 <= 300, top3)
    on3 = pg.evaluate("() => [...document.querySelectorAll('.wiz-chip[data-wiz-go]')].findIndex(c=>c.classList.contains('on'))")
    check("scroll-spy: chip 3 active after jump", on3 == 2, on3)

    # back to top -> chip 1
    pg.evaluate("() => window.scrollTo({top:0})")
    pg.wait_for_timeout(500)
    on1 = pg.evaluate("() => [...document.querySelectorAll('.wiz-chip[data-wiz-go]')].findIndex(c=>c.classList.contains('on'))")
    check("scroll-spy: chip 1 active at top", on1 == 0, on1)

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
    st2 = pg.evaluate("() => ({flash:document.querySelector('#settings-panel').classList.contains('req-flash')})")
    tt = toast_text(pg)
    check("P0.5 regression: empty rubric -> settings flash", st2["flash"], st2)
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
    pg.evaluate("() => { location.hash = '#evaluator'; }")
    pg.wait_for_timeout(1200)
    st = pg.evaluate("""() => ({labels:[...document.querySelectorAll('.wiz-chip[data-wiz-go]')].map(c=>c.textContent.trim()),
      adv: [...document.querySelectorAll('#view-analyze details.opts-panel summary')].map(s=>s.textContent.trim())})""")
    check("FR: chip labels translated", st["labels"][0] == "Sujet" and "Élève" in st["labels"][1]
          and st["labels"][3] == "Grille", st["labels"])
    check("FR: advanced options labels translated", "Options avancées" in st["adv"][0]
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
    keys = ["wiz.title","wiz.s1","wiz.s2","wiz.s3","wiz.s4","wiz.advOpts","wiz.evalNotes"]
    counts = {k: len(re.findall(r"'\s*" + re.escape(k) + r"\s*'\s*:", html)) for k in keys}
    check("i18n: 7 wiz.* keys defined 4x", all(v == 4 for v in counts.values()), counts)

    b.close()

print(f"\n{len(PASS)}/{len(PASS)+len(FAIL)} checks passed")
if FAIL:
    print("FAILED:", FAIL)
    raise SystemExit(1)
print("ALL OK")
