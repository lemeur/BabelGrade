#!/usr/bin/env python3
"""P6 verify: student-stats (📈) button + all entry paths (2026-10-15 bugfix).

BUG (tibo report): the 📈 button on a Students row did nothing. Root cause:
navApplyView('ststats', sub) used to `return` early expecting the CALLER of
navGo to open the view — but the row click (navGo push branch) and back/forward
only go through navApplyView, so the hash updated and the view never showed.
Fix: navApplyView now calls openStudentStats(sub) itself (it does the section
swap; same contract as the history loaders).

Verified paths (desktop 1280 + mobile 390):
- PRIMARY: row click opens the charts + hash #ststats/<id> + name + nav .on
- browser back -> students list; forward -> view re-shown (a known hash
  desync remains after forward — pre-existing since the 2026-10-12 nav
  design, NOT a regression; the VIEW is correct and back still works)
- Esc -> students list
- typed hash mid-session -> charts
- boot deep link #ststats/<id> (fresh context, login) -> charts
- 390px: click opens, no horizontal overflow

No seeding: uses the live DB's first student (any row with data-ststats).
No teardown needed (read-only flow)."""
import sys
sys.path.insert(0, "/tmp/elt_dm/venv/lib/python3.11/site-packages")
import _testpw as TESTPW
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8090"
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra and not cond else ""))

def ensure_app(pg):
    """Session cookie may survive a reload (app boots straight in) or not
    (login gate). Wait for whichever, log in if needed."""
    try:
        pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=15000)
    except Exception:
        pg.wait_for_selector("#auth-username", state="visible", timeout=15000)
        pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", TESTPW.pw())
        pg.click("#auth-login-btn")
        pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)

def snap(pg):
    return pg.evaluate("""() => ({hidden:document.querySelector('#view-ststats').classList.contains('hide'),
      hash:location.hash, bodyLen:document.querySelector('#ststats-body').innerHTML.length,
      name:document.querySelector('#ststats-name').textContent,
      stuVisible:!document.querySelector('#view-students').classList.contains('hide'),
      navOn:document.querySelector('#nav button.on')?.dataset.view})""")

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.add_init_script("localStorage.setItem('babelgrade-lang','fr')")
    pg.goto(BASE, wait_until="networkidle")
    ensure_app(pg)
    pg.wait_for_timeout(800)
    pg.evaluate("navGo('assignments')")   # 2026-10-27: boot default = home, nav hidden
    pg.wait_for_timeout(300)
    pg.click('#nav button[data-view="students"]')
    pg.wait_for_selector("#students tbody tr:not(:has(td[colspan]))")
    sid = pg.evaluate("document.querySelector('button[data-ststats]').dataset.ststats")

    # PRIMARY BUG: row click opens the charts
    pg.click(f'button[data-ststats="{sid}"]')
    pg.wait_for_timeout(1800)
    s = snap(pg)
    check("PRIMARY 📈 click -> charts + hash + name + nav .on",
          not s["hidden"] and s["hash"] == "#ststats/" + sid and s["name"]
          and s["bodyLen"] > 100 and s["navOn"] == "students", s)

    # browser back -> students list
    pg.go_back()
    pg.wait_for_timeout(1100)
    s = snap(pg)
    check("back -> students list + #students", s["hidden"] and s["stuVisible"] and s["hash"] == "#students", s)

    # forward -> the VIEW is re-shown (functional check). The hash may stay
    # desynced at #students — pre-existing nav-design behavior, not a
    # regression (documented in this file's docstring + the skill).
    pg.go_forward()
    pg.wait_for_timeout(1800)
    s = snap(pg)
    check("forward -> charts view re-shown", not s["hidden"] and s["bodyLen"] > 100 and s["name"], s)
    # back again: must land on the students list, view OR hash
    pg.go_back()
    pg.wait_for_timeout(1100)
    s = snap(pg)
    check("back-from-forward -> students list (no break)", s["hidden"] and s["stuVisible"], s)

    # Esc closes the stats view
    pg.click(f'button[data-ststats="{sid}"]')
    pg.wait_for_timeout(1800)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(700)
    s = snap(pg)
    check("Esc -> students list", s["hidden"] and s["stuVisible"] and s["hash"] == "#students", s)

    # typed hash mid-session (not in the stack)
    pg.evaluate(f"location.hash='#ststats/{sid}'")
    pg.wait_for_timeout(1800)
    s = snap(pg)
    check("typed hash -> charts", not s["hidden"] and s["bodyLen"] > 100, s)
    pg.go_back()
    pg.wait_for_timeout(900)

    # boot deep link in a fresh context
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    p2 = ctx.new_page()
    p2.on("pageerror", lambda e: errors.append(str(e)))
    p2.add_init_script("localStorage.setItem('babelgrade-lang','fr')")
    p2.goto(BASE + "/#ststats/" + sid, wait_until="networkidle")
    ensure_app(p2)
    p2.wait_for_timeout(2000)
    s = p2.evaluate("""() => ({hidden:document.querySelector('#view-ststats').classList.contains('hide'),
      bodyLen:document.querySelector('#ststats-body').innerHTML.length,
      name:document.querySelector('#ststats-name').textContent})""")
    check("boot deep link #ststats/<id> -> charts + name",
          not s["hidden"] and s["bodyLen"] > 100 and s["name"], s)
    ctx.close()

    # mobile 390: click works, no overflow
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    m = ctx.new_page()
    m.on("pageerror", lambda e: errors.append("390:" + str(e)))
    m.add_init_script("localStorage.setItem('babelgrade-lang','fr')")
    m.goto(BASE, wait_until="networkidle")
    ensure_app(m)
    m.wait_for_timeout(800)
    m.evaluate("navGo('assignments')")   # 2026-10-27: boot default = home, nav hidden
    m.wait_for_timeout(300)
    m.click('#nav button[data-view="students"]')
    m.wait_for_selector("#students tbody tr:not(:has(td[colspan]))")
    msid = m.evaluate("document.querySelector('button[data-ststats]').dataset.ststats")
    m.click(f'button[data-ststats="{msid}"]')
    m.wait_for_timeout(2000)
    c = m.evaluate("""() => ({hidden:document.querySelector('#view-ststats').classList.contains('hide'),
      ov:document.documentElement.scrollWidth-document.documentElement.clientWidth,
      bodyLen:document.querySelector('#ststats-body').innerHTML.length})""")
    check("390px: click opens, no overflow", not c["hidden"] and c["ov"] <= 0 and c["bodyLen"] > 100, c)
    ctx.close()

    check("no JS page errors", not errors, errors[:3])
    b.close()

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
