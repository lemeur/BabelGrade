#!/usr/bin/env python3
"""P0.2 verify: bottom nav bar on mobile — present on every view, full 6 tabs fit, content not covered."""
import os
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8090"
OUT = os.path.dirname(os.path.abspath(__file__))
PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name); print(("PASS " if cond else "FAIL ")+name+(" | "+str(extra) if extra else ""))

def login(pg):
    pg.add_init_script("localStorage.setItem('elt-lang','fr')")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username","tibo"); pg.fill("#auth-password","****")
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    pg.wait_for_timeout(1200)

def navbox(pg):
    return pg.evaluate("() => { const n=document.getElementById('nav'); const r=n.getBoundingClientRect(); return {top:r.top,bottom:r.bottom,height:r.height, left:r.left, right:r.right, pos:getComputedStyle(n).position}; }")

with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width":390,"height":844}, device_scale_factor=2,
                        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15")
    pg = ctx.new_page()
    errs=[]
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg)
    H = 844
    # 2026-10-27: boot default is the home view, where the tab bar is hidden —
    # open assignments first (the loop skips the first view's click).
    pg.evaluate("navGo('assignments')")
    pg.wait_for_timeout(800)
    for view in ["assignments","history","rubrics","students","jobs","docs"]:
        if view!="assignments":
            pg.click(f'#nav button[data-view="{view}"]'); pg.wait_for_timeout(1200)
        nb = navbox(pg)
        check(f"nav[{view}] fixed at bottom", nb["pos"]=="fixed" and abs(nb["bottom"]-H)<3, nb)
        check(f"nav[{view}] full width", nb["left"]<=2 and nb["right"]>=388, nb)
        # all 6 buttons visible & tappable (>=40px wide, in viewport)
        boxes = pg.evaluate("""() => [...document.querySelectorAll('#nav button')].map(b=>{const r=b.getBoundingClientRect();return {t:b.textContent.trim(),w:r.width,h:r.height,r:r.right,l:r.left};})""")
        ok = len(boxes)==6 and all(x["l"]>=0 and x["r"]<=391 and x["h"]>=40 for x in boxes)
        check(f"nav[{view}] 6 tabs fit+tappable", ok, [ (x["t"],round(x["r"])) for x in boxes])
        # content not covered: main's bottom padding accounts for nav height
        pad = pg.evaluate("() => getComputedStyle(document.querySelector('main')).paddingBottom")
        check(f"nav[{view}] main bottom pad >= nav height", int(pad.rstrip('px')) >= nb["height"]-2, pad)
        pg.screenshot(path=os.path.join(OUT, f"p02_{view}.png"))
    pg.screenshot(path=os.path.join(OUT,"p02_assignments.png"), full_page=False)
    # no JS errors
    check("no JS errors", not errs, errs[:2])
    b.close()

print(f"\n=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
if FAIL: print("FAILED:", FAIL)
