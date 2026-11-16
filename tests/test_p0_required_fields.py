#!/usr/bin/env python3
"""P0.5 verify: required-field markers + flash UX on the evaluator form.
- '*' next to Rubric label and on the "student's work" card title (all langs)
- reqNote line present under the action buttons
- clicking #run with empty rubric -> settings card flashes + i18n toast
- clicking #run-eval with written + no text/photo -> work card flashes + i18n toast
- no JS errors; i18n keys balanced (every key 4x)"""
import os, re
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
    pg.wait_for_timeout(1500)

def toast_text(pg):
    return pg.evaluate("() => { const el=document.querySelector('.toast'); return el?{text:el.textContent, show:el.classList.contains('show')}:null; }")

with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])

    # ---------- FR desktop ----------
    print("== FR desktop: markers + guards ==")
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg, "fr")
    pg.evaluate("() => { location.hash = '#evaluator'; }")
    pg.wait_for_timeout(1500)

    # markers
    m = pg.evaluate("""() => {
      const rubricLabel = document.querySelector('label[data-i18n="an.rubric"]');
      const workTitle = document.querySelector('#work-panel h2');
      const note = document.querySelector('[data-i18n="an.reqNote"]');
      return {
        rubricStar: rubricLabel ? rubricLabel.querySelector('.req') !== null : null,
        workStar: workTitle ? workTitle.querySelector('.req') !== null : null,
        noteText: note ? note.textContent.trim() : null,
      };
    }""")
    check("FR: '*' on Rubric label", m["rubricStar"] is True, m)
    check("FR: '*' on work card title", m["workStar"] is True, m)
    check("FR: reqNote visible under action buttons", bool(m["noteText"]), m["noteText"])
    pg.screenshot(path=os.path.join(OUT, "p05_evaluator_fr.png"))

    # guard 1: empty rubric -> settings panel flash
    pg.evaluate("() => { document.querySelector('#rubric').value=''; }")
    pg.click('#run')
    pg.wait_for_timeout(700)
    st = pg.evaluate("""() => {
      const c=document.querySelector('#settings-panel');
      return {flash:c.classList.contains('req-flash')};
    }""")
    tt = toast_text(pg)
    check("FR: empty rubric -> settings flash", st["flash"], st)
    check("FR: empty rubric -> i18n toast (choose rubric)", tt and "grille" in tt["text"].lower(), tt)

    # guard 2: written + no text -> work panel flash
    pg.evaluate("() => { const s=document.querySelector('#rubric'); if(s.options.length>1)s.selectedIndex=1; else s.value=s.options[0]?s.options[0].value:''; }")
    pg.evaluate("() => { KIND='written'; document.querySelector('#written-text').value=''; currenasgnFiles=[]; }")
    pg.click('#run-eval')
    pg.wait_for_timeout(700)
    st = pg.evaluate("() => ({flash:document.querySelector('#work-panel').classList.contains('req-flash')})")
    tt = toast_text(pg)
    check("FR: written no text -> work flash", st["flash"], st)
    check("FR: written no text -> i18n toast", tt and "travail écrit" in tt["text"].lower() or (tt and "écrit" in tt["text"].lower()), tt)
    check("FR: no JS errors", not errs, errs[:2])
    ctx.close()

    # ---------- EN desktop: markers survive applyI18n ----------
    print("== EN desktop: markers after applyI18n ==")
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg, "en")
    pg.evaluate("() => { location.hash = '#evaluator'; }")
    pg.wait_for_timeout(1500)
    m = pg.evaluate("""() => {
      const rubricLabel = document.querySelector('label[data-i18n="an.rubric"]');
      const workTitle = document.querySelector('#work-panel h2');
      return {
        rubricText: rubricLabel ? rubricLabel.textContent.trim() : null,
        rubricStar: rubricLabel ? rubricLabel.querySelector('.req') !== null : null,
        workStar: workTitle ? workTitle.querySelector('.req') !== null : null,
      };
    }""")
    check("EN: Rubric label text kept + star after applyI18n", m["rubricText"] == "Rubric*" or m["rubricText"].startswith("Rubric "), m)
    check("EN: '*' on Rubric label", m["rubricStar"] is True, m)
    check("EN: '*' on work card title", m["workStar"] is True, m)
    check("EN: no JS errors", not errs, errs[:2])
    ctx.close()

    b.close()

# ---------- i18n balance: new keys appear 4x each ----------
html = open('/home/tibo/babelgrade/static/index.html').read()
for key in ["an.reqNote", "an.missingWorkWritten", "an.missingAudio"]:
    n = len(re.findall(re.escape(key) + "':'", html))
    check(f"i18n key '{key}' defined 4x", n == 4, n)

print(f"\n=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
if FAIL: print("FAILED:", FAIL)
