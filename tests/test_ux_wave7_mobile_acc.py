#!/usr/bin/env python3
"""2026-11-28 round-2 mobile accordion behavior (390×844, portrait, touch).

Covers the round-2 mobile feedback lot on the evaluator accordion:
- M5 chevron TOGGLE: clicking an OPEN step's header CLOSES it (n=0); clicking
  a closed step's header opens it. (The old code force-reopened the persisted
  step on every scroll/resize — the chevron bug.)
- M1 Previous buttons: steps 2-4 carry a .wz-prev (data-wz-prev) that goes back
  unconditionally; step 1 has none.
- M2 CTA band gating: the #run/#run-eval band is hidden (.cta-waiting) while
  any accordion step is unfilled, and becomes visible (sticky on mobile) once
  all 4 are filled.
- M6 done badge: a filled step shows the ✓ via .wz-num::after while the step
  NUMBER stays visible (the old ::before replaced the digit).
- M7 ad-hoc title (Direct mode): typing a subject title fills step 1 even with
  no subject selected.
- no JS errors.
Run: /tmp/bg_venv/bin/python tests/test_ux_wave7_mobile_acc.py
Live server on :8090 required; login tibo/<tests/.credentials>; lang forced FR.
"""
import os
import _testpw as TESTPW
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8090"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + ((" | " + str(extra) if extra else "")))


def login(pg):
    pg.add_init_script("localStorage.setItem('babelgrade-lang','fr')")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", TESTPW.pw())
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)


def open_step(pg):
    return pg.evaluate("() => { const o=document.querySelector('#wz-steps .acc-item.open'); return o?+o.dataset.step:null; }")


def cta(pg):
    return pg.evaluate("""() => {
      const c=document.querySelector('.card.an-actions');
      return {waiting:c.classList.contains('cta-waiting'), disp:getComputedStyle(c).display,
              filled:wizFilled()};
    }""")


with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 390, "height": 844}, locale="fr-FR",
                        has_touch=True, is_mobile=True)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg)
    pg.evaluate("() => { location.hash = '#evaluator'; }")
    pg.wait_for_timeout(1200)

    # ---- M2: CTA band hidden at boot (3 of 4 steps unfilled) ----
    c0 = cta(pg)
    check("M2: CTA band hidden at boot (mobile, .cta-waiting + display:none)",
          c0["waiting"] and c0["disp"] == "none", c0)

    # ---- M1: Previous buttons on steps 2-4, none on step 1 ----
    prevs = pg.evaluate("""() => {
      return [...document.querySelectorAll('.wz-prev')].map(x=>+x.dataset.wzPrev);
    }""")
    check("M1: Previous buttons present on steps -> back to 1,2,3 (data-wz-prev)",
          sorted(prevs) == [1, 2, 3], prevs)
    step1prev = pg.evaluate("() => !!(document.querySelector('#what-panel .wz-prev'))")
    check("M1: step 1 has NO Previous button", not step1prev, step1prev)

    # ---- M5: chevron TOGGLE — open step 2, then re-click closes it (n=0) ----
    pg.click('.acc-hd[data-wz-hd="2"]')
    pg.wait_for_timeout(400)
    check("M5: clicking step-2 header opens it", open_step(pg) == 2, open_step(pg))
    pg.click('.acc-hd[data-wz-hd="2"]')
    pg.wait_for_timeout(400)
    check("M5: re-clicking the open step-2 header CLOSES it (n=0)",
          open_step(pg) is None, open_step(pg))

    # re-open step 2 for the Previous-button behaviour
    pg.click('.acc-hd[data-wz-hd="3"]')
    pg.wait_for_timeout(400)
    check("M5: clicking a closed step (3) opens it", open_step(pg) == 3, open_step(pg))

    # ---- M1: Previous button goes back unconditionally ----
    pg.click('#work-panel .wz-prev')          # step 3 -> back to step 2
    pg.wait_for_timeout(400)
    check("M1: Previous on step 3 returns to step 2", open_step(pg) == 2, open_step(pg))

    # ---- M6 + M7 + M2: fill all 4 steps, watch .done badge + CTA reveal ----
    # step 1: ad-hoc title in Direct mode (M7) — no subject selected
    pg.click('.acc-hd[data-wz-hd="1"]')
    pg.wait_for_timeout(300)
    pg.fill("#direct-subject-title", "Bac blanc — rédaction argumentée")
    pg.wait_for_timeout(400)
    s1 = pg.evaluate("""() => ({
      filled1: wizFilled()[0],
      done: document.querySelector('.acc-item[data-step="1"]').classList.contains('done'),
      before: getComputedStyle(document.querySelector('.acc-item[data-step="1"] .wz-num'),'::before').content,
      after: getComputedStyle(document.querySelector('.acc-item[data-step="1"] .wz-num'),'::after').content,
      num: document.querySelector('.acc-item[data-step="1"] .wz-num span').textContent.trim()
    })""")
    check("M7: ad-hoc title fills step 1 (Direct mode)", s1["filled1"] is True, s1)
    check("M6: step 1 .done badge via ::after (✓)", '✓' in s1["after"] or '2713' in s1["after"], s1["after"])
    check("M6: step 1 NUMBER still visible (digit not replaced)", s1["num"] == "1", s1["num"])

    # steps 2,3,4
    pg.evaluate("""() => {
      const s2=document.getElementById('student'); if(s2.options.length>1)s2.selectedIndex=1; s2.dispatchEvent(new Event('change',{bubbles:true}));
      const t=document.getElementById('written-text'); t.value='Il a fait beau et nous sommes allés au parc.'; t.dispatchEvent(new Event('input',{bubbles:true}));
      const s4=document.getElementById('rubric'); if(s4.options.length>1)s4.selectedIndex=1; s4.dispatchEvent(new Event('change',{bubbles:true}));
    }""")
    pg.wait_for_timeout(600)
    c1 = cta(pg)
    check("M2: CTA band visible when all 4 steps filled (mobile)",
          (not c1["waiting"]) and c1["disp"] != "none", c1)

    # sticky on mobile: the visible band is a sticky bottom bar
    stick = pg.evaluate("() => getComputedStyle(document.querySelector('.card.an-actions')).position")
    check("M2: CTA band is sticky-bottom on mobile (≤760px)", stick == "sticky", stick)

    check("no JS errors", not errs, errs[:2])
    ctx.close(); b.close()

print(f"\n=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
if FAIL:
    print("FAILED:", FAIL)
    raise SystemExit(1)
