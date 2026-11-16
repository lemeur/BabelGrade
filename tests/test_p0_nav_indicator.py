#!/usr/bin/env python3
"""P0.2b verify: mobile bottom nav — active indicator not clipped at screen edge,
top separator visible, no JS errors. Then screenshot for vision check."""
import os
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
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", "****")
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    pg.wait_for_timeout(1200)

with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15")
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg)
    H = 844
    # 2026-10-27: boot default is the home view, where the tab bar is HIDDEN
    # (display:none → zero rect + Playwright click refuses) — navGo() it first.
    pg.evaluate("navGo('assignments')")
    pg.wait_for_timeout(500)

    nb = pg.evaluate("() => { const n=document.getElementById('nav'); const r=n.getBoundingClientRect(); return {top:r.top,bottom:r.bottom,height:r.height,pos:getComputedStyle(n).position}; }")
    check("nav fixed bottom", nb["pos"] == "fixed" and abs(nb["bottom"] - H) < 3, nb)

    # active button (assignments) geometry: indicator must NOT be flush at screen edge
    info = pg.evaluate("""() => {
      const btn = document.querySelector('#nav button.on');
      const r = btn.getBoundingClientRect();
      const cs = getComputedStyle(btn);
      return {bottom: r.bottom, height: r.height,
              borderBottom: cs.borderBottomWidth, borderBottomColor: cs.borderBottomColor,
              background: cs.backgroundColor};
    }""")
    check("active indicator not flush at edge (button bottom < screen bottom - 3px)",
          info["bottom"] <= H - 4, info)

    # top separator present
    sep = pg.evaluate("() => getComputedStyle(document.getElementById('nav')).borderTopWidth")
    check("nav top border present", float(sep.rstrip('px')) >= 1, sep)

    pg.screenshot(path=os.path.join(OUT, "p02b_history_after.png"))
    pg.click('#nav button[data-view="students"]'); pg.wait_for_timeout(900)
    pg.screenshot(path=os.path.join(OUT, "p02b_students_after.png"))
    check("no JS errors", not errs, errs[:2])
    b.close()

print(f"\n=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
if FAIL: print("FAILED:", FAIL)
