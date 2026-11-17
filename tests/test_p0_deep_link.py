#!/usr/bin/env python3
"""P0.1 E2E: address-bar deep links (#history/<id>, #ststats/<id>, #evaluator, #view).
Scenarios: client-side typed hash from another view, fresh boot deep link,
back-button semantics, unknown-id fallback, in-app nav regression."""
import _testpw as TESTPW
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8090"
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

def login(pg):
    pg.add_init_script("localStorage.setItem('babelgrade-lang','fr')")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username", "tibo")
    pg.fill("#auth-password", TESTPW.pw())
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    pg.wait_for_timeout(1200)

def snap(pg):
    return pg.evaluate("""() => ({
      hash: location.hash,
      inApp: document.querySelector('#view-assignments') !== null,
      visible: [...document.querySelectorAll('.wrap > section')].filter(s => !s.classList.contains('hide')).map(s => s.id),
      att: (() => { const h=document.querySelector('#view-history');
        return h && !h.classList.contains('hide') && !!h.querySelector('.att-card'); })(),
      detailOpen: !!document.querySelector('#view-history') && document.querySelector('#view-history').classList.contains('detail-open'),
      stack: (typeof NAV_HISTORY !== 'undefined') ? NAV_HISTORY.map(e => e.view + (e.sub ? '/' + e.sub : '')) : null,
      ststats: !!document.querySelector('#view-ststats') && !document.querySelector('#view-ststats').classList.contains('hide')
    })""")

with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])

    # ---------------- S1: client-side typed deep link (desktop) ----------------
    print("== S1 client-side typed #history/553 from assignments ==")
    ctx = b.new_context(viewport={"width":1280,"height":800})
    pg = ctx.new_page()
    errs=[]
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg)
    pg.evaluate("() => { location.hash = '#history/553'; }")
    pg.wait_for_timeout(3500)
    s = snap(pg)
    check("S1 history view visible", "view-history" in s["visible"], s)
    check("S1 detail opened (att-card)", s["att"], s)
    check("S1 hash", s["hash"] == "#history/553", s["hash"])
    check("S1 no JS errors", not errs, errs[:2])
    # back button -> list (the typed entry replaced the top; back goes to the pre-typed state)
    pg.go_back()
    pg.wait_for_timeout(1500)
    s = snap(pg)
    check("S1 back -> no detail / back state", (not s["att"]) or ("view-history" in s["visible"] and not s["detailOpen"]), s)
    # back button -> list (the typed entry replaced the top; back goes to the
    # pre-typed state). 2026-10-27: boot default = #home where the tab bar is
    # HIDDEN — the in-app regression clicks the nav, so open it first.
    pg.evaluate("navGo('assignments')")
    pg.wait_for_timeout(300)
    pg.click('#nav button[data-view="history"]')
    pg.wait_for_timeout(2500)
    row = pg.query_selector("#hist [data-aid='553']") or pg.query_selector("#hist [data-aid]")
    row.click(); pg.wait_for_timeout(2000)
    check("S1 in-app row open att", snap(pg)["att"])
    pg.go_back(); pg.wait_for_timeout(1200)
    check("S1 in-app back closes detail", not snap(pg)["att"])
    pg.go_forward(); pg.wait_for_timeout(1500)
    check("S1 in-app forward reopens detail", snap(pg)["att"])
    ctx.close()

    # ---------------- S2: fresh boot deep link ----------------
    print("== S2 fresh boot with #history/553 in the URL ==")
    ctx = b.new_context(viewport={"width":1280,"height":800})
    pg = ctx.new_page()
    errs=[]
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.add_init_script("localStorage.setItem('babelgrade-lang','fr')")
    pg.goto(BASE + "#history/553", wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username", "tibo")
    pg.fill("#auth-password", TESTPW.pw())
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    pg.wait_for_timeout(3000)
    s = snap(pg)
    check("S2 history view visible", "view-history" in s["visible"], s)
    check("S2 detail opened (att-card)", s["att"], s)
    check("S2 no JS errors", not errs, errs[:2])
    # boot back button: with a single history entry, back leaves the app
    # (leaves #history/553 → back URL). That is acceptable; just ensure the
    # app did not crash while doing it.
    pg.go_back(); pg.wait_for_timeout(1200)
    ok = True
    try:
        s2 = snap(pg)
        ok = isinstance(s2, dict)
    except Exception:
        ok = pg.evaluate("() => location.href")  # page still alive
    check("S2 back safe (no crash)", bool(ok), "navigated away")
    ctx.close()

    # ---------------- S3: ststats typed deep link ----------------
    print("== S3 typed #ststats/<sid> ==")
    ctx = b.new_context(viewport={"width":1280,"height":800})
    pg = ctx.new_page()
    login(pg)
    sid = pg.evaluate("() => STUDENTS[0].id")
    pg.evaluate(f"() => {{ location.hash = '#ststats/{sid}'; }}")
    pg.wait_for_timeout(2500)
    s = snap(pg)
    check("S3 ststats visible", s["ststats"], s)
    ctx.close()

    # ---------------- S4: evaluator typed deep link ----------------
    print("== S4 typed #evaluator ==")
    ctx = b.new_context(viewport={"width":1280,"height":800})
    pg = ctx.new_page()
    login(pg)
    pg.evaluate("() => { location.hash = '#evaluator'; }")
    pg.wait_for_timeout(1500)
    s = snap(pg)
    check("S4 evaluator visible", "view-analyze" in s["visible"], s)
    ctx.close()

    # ---------------- S5: unknown id -> list, no crash ----------------
    print("== S5 typed #history/99999 (unknown) ==")
    ctx = b.new_context(viewport={"width":1280,"height":800})
    pg = ctx.new_page()
    errs=[]
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg)
    pg.evaluate("() => { location.hash = '#history/99999'; }")
    pg.wait_for_timeout(3000)
    s = snap(pg)
    check("S5 lands on history list", "view-history" in s["visible"], s)
    check("S5 no detail", not s["att"], s)
    check("S5 no JS errors", not errs, errs[:2])
    ctx.close()

    # ---------------- S6: mobile typed deep link ----------------
    print("== S6 mobile 390 typed #history/553 ==")
    ctx = b.new_context(viewport={"width":390,"height":844}, device_scale_factor=2,
                        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15")
    pg = ctx.new_page()
    login(pg)
    pg.evaluate("() => { location.hash = '#history/553'; }")
    pg.wait_for_timeout(3500)
    s = snap(pg)
    check("S6 history visible", "view-history" in s["visible"], s)
    check("S6 detail opened", s["att"], s)
    ctx.close()

    b.close()

print(f"\n=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
if FAIL:
    print("FAILED:", FAIL)
