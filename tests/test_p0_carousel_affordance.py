#!/usr/bin/env python3
"""P0.3 verify: scroll affordance on .lvl-carousel (NIVEAU CIBLE carousels).
Desktop: #lvl-plain-carousel overflows -> inset shadow present; scroll to end -> gone.
Mobile 390: same on the evaluator plain carousel; new-assignment carousel too."""
import os
import _testpw as TESTPW
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8090"
OUT = os.path.dirname(os.path.abspath(__file__))
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

def login(pg):
    pg.add_init_script("localStorage.setItem('babelgrade-lang','fr')")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", TESTPW.pw())
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    pg.wait_for_timeout(1200)

def afford(pg, sel):
    """(overflows, shadowSet, scrolledToEnd) for a selector."""
    return pg.evaluate("""(sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      return {
        overflow: el.scrollWidth > el.clientWidth + 1,
        shadow: el.style.boxShadow !== '',
        canScrollClass: el.classList.contains('can-scroll'),
        end: el.scrollLeft + el.clientWidth >= el.scrollWidth - 2,
        sw: el.scrollWidth, cw: el.clientWidth, sl: el.scrollLeft
      };
    }""", sel)

with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])

    # ---------- Desktop 1280 ----------
    print("== Desktop 1280 ==")
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg)
    # open the evaluator (ad-hoc) view so the plain level carousel is visible
    pg.evaluate("() => { location.hash = '#evaluator'; }")
    pg.wait_for_timeout(1500)
    st = afford(pg, "#lvl-plain-carousel")
    check("desktop plain carousel: shadow iff overflow (state consistency)",
          st and (st["shadow"] == st["overflow"]), st)
    check("desktop plain carousel: class iff overflow", st and (st["canScrollClass"] == st["overflow"]), st)
    pg.screenshot(path=os.path.join(OUT, "p03_desktop_carousel.png"))
    check("desktop no JS errors", not errs, errs[:2])
    ctx.close()

    # ---------- Mobile 390 ----------
    print("== Mobile 390 ==")
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15")
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg)
    pg.evaluate("() => { location.hash = '#evaluator'; }")
    pg.wait_for_timeout(1500)
    st = afford(pg, "#lvl-plain-carousel")
    check("mobile plain carousel overflows", st and st["overflow"], st)
    check("mobile plain carousel has affordance shadow", st and st["shadow"] and st["canScrollClass"], st)
    pg.screenshot(path=os.path.join(OUT, "p03_mobile_carousel.png"))
    # new-assignment editor carousel
    pg.evaluate("() => { openAssignmentEditor(null); }")
    pg.wait_for_timeout(800)
    st = afford(pg, "#asg-target-carousel")
    check("assignment carousel overflows on mobile", st and st["overflow"], st)
    check("assignment carousel has affordance shadow when overflowing",
          st and st["shadow"] and st["canScrollClass"], st)
    pg.evaluate("() => { const el=document.querySelector('#asg-target-carousel'); el.scrollLeft = el.scrollWidth; }")
    pg.wait_for_timeout(400)
    st = afford(pg, "#asg-target-carousel")
    check("affordance drops at end of scroll", st and not st["shadow"] and not st["canScrollClass"], st)
    check("mobile no JS errors", not errs, errs[:2])
    ctx.close()

    b.close()

print(f"\n=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
if FAIL: print("FAILED:", FAIL)
