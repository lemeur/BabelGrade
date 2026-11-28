#!/usr/bin/env python3
"""P0.5 verify: required-field markers + flash UX + CTA band gating on the
evaluator form.
- '*' next to Rubric label and on the "student's work" card title (all langs)
- CTA band (#run/#run-eval) is HIDDEN while the 4 accordion steps are not all
  filled (.cta-waiting) and becomes VISIBLE once they are (M2, 2026-11-28 r3)
- clicking #run with empty rubric -> settings card flashes + i18n toast
- clicking #run-eval with written + no text/photo -> work card flashes + i18n
  toast (band forced visible to reach the guard, since it's hidden when a step
  is unfilled)
- no JS errors; i18n keys balanced (every key 4x in the I18N slice)"""
import os, re
from pathlib import Path
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
    pg.wait_for_timeout(1500)

def toast_text(pg):
    return pg.evaluate("() => { const el=document.querySelector('.toast'); return el?{text:el.textContent, show:el.classList.contains('show')}:null; }")

def cta_state(pg):
    """Computed display + .cta-waiting of the CTA band (M2 gate)."""
    return pg.evaluate("""() => {
      const c=document.querySelector('.card.an-actions');
      return {waiting:c.classList.contains('cta-waiting'),
              disp:getComputedStyle(c).display,
              filled:(typeof wizFilled==='function')?wizFilled():null};
    }""")

def force_cta_visible(pg):
    """M2 hides the band while a step is unfilled; tests that reach the #run /
    #run-eval guards force it visible so Playwright can click the buttons.
    An INLINE display:flex beats .cta-waiting{display:none} AND survives the
    rAF-debounced wizSync() that would otherwise re-add .cta-waiting after the
    guard-test state changes. (The run guards stay authoritative either way —
    this only un-hides the buttons.)"""
    pg.evaluate("() => { const c=document.querySelector('.card.an-actions'); c.classList.remove('cta-waiting'); c.style.display='flex'; }")

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
    pg.evaluate("typeof pieClose==='function'&&pieClose()")  # close radial menu (default boot view)
    pg.wait_for_timeout(1500)

    # markers
    m = pg.evaluate("""() => {
      const rubricLabel = document.querySelector('label[data-i18n="an.rubric"]');
      const workTitle = document.querySelector('#work-panel h2');
      return {
        rubricStar: rubricLabel ? rubricLabel.querySelector('.req') !== null : null,
        workStar: workTitle ? workTitle.querySelector('.req') !== null : null,
      };
    }""")
    check("FR: '*' on Rubric label", m["rubricStar"] is True, m)
    check("FR: '*' on work card title", m["workStar"] is True, m)

    # M2: CTA band is HIDDEN while the 4 accordion steps are not all filled
    # (boot: subject / student / work are empty -> 3 of 4 unfilled).
    c0 = cta_state(pg)
    check("FR: CTA band hidden at boot (.cta-waiting, display:none)",
          c0["waiting"] and c0["disp"] == "none", c0)
    pg.screenshot(path=os.path.join(OUT, "p05_evaluator_fr.png"))

    # M2: filling ALL 4 steps makes the band visible.
    pg.evaluate("""() => {
      const s1=document.getElementById('assignment'); s1.value='48'; s1.dispatchEvent(new Event('change',{bubbles:true}));
      const s2=document.getElementById('student'); if(s2.options.length>1)s2.selectedIndex=1; s2.dispatchEvent(new Event('change',{bubbles:true}));
      const t=document.getElementById('written-text'); t.value='It was a nice day and we went to the park.'; t.dispatchEvent(new Event('input',{bubbles:true}));
      const s4=document.getElementById('rubric'); if(s4.options.length>1)s4.selectedIndex=1; s4.dispatchEvent(new Event('change',{bubbles:true}));
    }""")
    pg.wait_for_timeout(500)
    c1 = cta_state(pg)
    check("FR: CTA band visible when all 4 steps filled",
          (not c1["waiting"]) and c1["disp"] != "none", c1)

    # guard 1: empty rubric -> settings panel flash. Clearing the rubric hides
    # the band again (step 4 unfilled) -> force it visible to reach the guard.
    pg.evaluate("() => { const r=document.querySelector('#rubric'); r.value=''; r.dispatchEvent(new Event('change',{bubbles:true})); }")
    force_cta_visible(pg)
    pg.click('#run')
    pg.wait_for_timeout(700)
    st = pg.evaluate("""() => {
      const c=document.querySelector('#settings-panel');
      return {flash:c.classList.contains('req-flash')};
    }""")
    tt = toast_text(pg)
    check("FR: empty rubric -> settings flash", st["flash"], st)
    check("FR: empty rubric -> i18n toast (choose rubric)", tt and "grille" in tt["text"].lower(), tt)

    # guard 2: written + no text -> work panel flash. Re-pick a rubric, clear
    # the work, force the band visible, then click #run-eval.
    pg.evaluate("() => { const s=document.querySelector('#rubric'); if(s.options.length>1)s.selectedIndex=1; else s.value=s.options[0]?s.options[0].value:''; s.dispatchEvent(new Event('change',{bubbles:true})); }")
    pg.evaluate("() => { KIND='written'; document.querySelector('#written-text').value=''; document.querySelector('#written-text').dispatchEvent(new Event('input',{bubbles:true})); currenasgnFiles=[]; }")
    force_cta_visible(pg)
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

# ---------- i18n balance: keys appear 4x each IN THE I18N SLICE ----------
# Count only definitions inside the I18N object (I18N={ ... let LANG), the way
# test_p0_state_i18n_js.py does — a whole-file count over-counts CONSUMER
# usages (e.g. the wizard ternary 'an.missingAudio').
html = open(Path(__file__).resolve().parent.parent / 'static' / 'index.html').read()
i18n_slice = html[html.index('I18N={'): html.index('let LANG')]
for key in ["an.missingWorkWritten", "an.missingAudio", "wz.prev"]:
    n = len(re.findall(re.escape(key) + "':'", i18n_slice))
    check(f"i18n key '{key}' defined 4x (in I18N slice)", n == 4, n)

print(f"\n=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
if FAIL: print("FAILED:", FAIL)
