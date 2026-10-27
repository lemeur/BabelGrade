#!/usr/bin/env python3
"""Home (simplified mode) suite — 2026-10-27.

Boot default is now the simplified start screen (#view-home, hash #home):
three big verbs (Prepare / Evaluate / Analyze) + a small "Advanced mode"
button. Prepare and Analyze open a RADIAL (pie) menu around the pressed
button; Evaluate goes straight to the evaluator form. The full interface
(still reachable via the pie items, "Advanced mode", or the header
"◂ Simplified" button) is unchanged.

Covers (desktop 1280, FR; then 390px mobile):
- boot: #home hash, home view visible, 3 verbs + advanced button, tab bar
  hidden, no JS errors
- pie menu: opens on Prepare (2 FR items), on Analyze (3 FR items), items
  inside the viewport, click navigates (class/subject/progression/results/
  history), re-open after leaving, closes on backdrop / Esc
- Evaluate verb → evaluator form visible
- Advanced mode → assignments view + tab bar back; "◂ Simplified" in the
  header → back to home
- back button: home → assignments (push) → back lands on home
- typed #home from another view
- 390px: home fits (no page overflow), pie opens with all items in viewport

Follows the repo test conventions: login(tibo/****), lang forced via
add_init_script, own checks + exit(1) on failure. No API writes → no
teardown needed."""
import sys
sys.path.insert(0, "/tmp/elt_dm/venv/lib/python3.11/site-packages")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8090"
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

def home_state(pg):
    return pg.evaluate("""() => ({
      hash: location.hash,
      homeVisible: !document.querySelector('#view-home').classList.contains('hide'),
      othersHidden: [...document.querySelectorAll('.wrap > section')].filter(s => s.id !== 'view-home' && !s.classList.contains('hide')).length === 0,
      navHidden: document.querySelector('#nav').classList.contains('hide'),
      hdrHomeHidden: document.querySelector('#hdr-home').classList.contains('hide'),
      verbs: [...document.querySelectorAll('.home-btn')].map(b => b.textContent.trim()),
      adv: document.querySelector('#home-advanced').textContent.trim(),
      pieOpen: document.querySelector('#pie-wrap').classList.contains('open'),
      pieItems: [...document.querySelectorAll('.pie-item')].map(b => {
        const r = b.getBoundingClientRect();
        return {t: b.textContent.trim(), inVp: r.left >= 0 && r.right <= window.innerWidth + 1 && r.top >= 0 && r.bottom <= window.innerHeight + 1, h: r.height};
      })
    })""")

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    login(pg)
    pg.wait_for_timeout(600)

    # --- boot state ---
    s = home_state(pg)
    check("boot: hash #home", s["hash"] == "#home", s["hash"])
    check("boot: home view visible + all others hidden", s["homeVisible"] and s["othersHidden"], s)
    check("boot: 3 verbs (FR)", [v.replace(" ", "").strip() for v in s["verbs"]] ==
          ["📚Préparer", "✍️Évaluer", "📊Analyser"], s["verbs"])
    check("boot: advanced button FR", s["adv"] == "Mode avancé ▸", s["adv"])
    check("boot: tab bar hidden on home", s["navHidden"], s)
    check("boot: '◂ Simplified' header button hidden on home", s["hdrHomeHidden"], s)
    check("boot: pie closed", not s["pieOpen"], s)

    # --- pie: Prepare ---
    pg.click("#home-prepare")
    pg.wait_for_timeout(300)
    s = home_state(pg)
    check("pie(Prepare): open", s["pieOpen"], s)
    check("pie(Prepare): 2 items (class + subject)", [i["t"] for i in s["pieItems"]] ==
          ["🏫 Classe / élèves", "📚 Sujet"], s["pieItems"])
    check("pie(Prepare): items in viewport, tappable",
          all(i["inVp"] and i["h"] >= 40 for i in s["pieItems"]), s["pieItems"])
    pg.screenshot(path="tests/home_pie_prepare.png")
    # click "Sujet" → assignments
    pg.click(".pie-item[data-pie-idx='1']")
    pg.wait_for_timeout(400)
    check("pie(Prepare): 'Sujet' → assignments view + hash",
          pg.evaluate("location.hash") == "#assignments"
          and not pg.evaluate("document.querySelector('#view-assignments').classList.contains('hide')"))
    check("pie(Prepare): closed after navigation", not pg.evaluate("document.querySelector('#pie-wrap').classList.contains('open')"))

    # --- pie: Analyze ---
    pg.evaluate("navGo('home')")
    pg.wait_for_timeout(300)
    pg.click("#home-analyze")
    pg.wait_for_timeout(300)
    s = home_state(pg)
    check("pie(Analyze): open, 3 items (progression/results/history)",
          [i["t"] for i in s["pieItems"]] ==
          ["📈 Progression d’un élève", "📊 Résultats sur un sujet", "🗂️ Historique"],
          s["pieItems"])
    pg.screenshot(path="tests/home_pie_analyze.png")
    # click "Historique" → history
    pg.click(".pie-item[data-pie-idx='2']")
    pg.wait_for_timeout(600)
    check("pie(Analyze): 'Historique' → history view + hash",
          pg.evaluate("location.hash") == "#history"
          and not pg.evaluate("document.querySelector('#view-history').classList.contains('hide')"))
    # item 1 → students (progression)
    pg.evaluate("navGo('home')"); pg.wait_for_timeout(200)
    pg.click("#home-analyze"); pg.wait_for_timeout(250)
    pg.click(".pie-item[data-pie-idx='0']")
    pg.wait_for_timeout(400)
    check("pie(Analyze): 'Progression' → students view",
          pg.evaluate("location.hash") == "#students")

    # --- close on backdrop + Esc ---
    pg.evaluate("navGo('home')"); pg.wait_for_timeout(200)
    pg.click("#home-prepare"); pg.wait_for_timeout(200)
    pg.click("#pie-backdrop")
    pg.wait_for_timeout(200)
    check("pie: backdrop click closes", not pg.evaluate("document.querySelector('#pie-wrap').classList.contains('open')"))
    pg.click("#home-prepare"); pg.wait_for_timeout(200)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)
    check("pie: Esc closes", not pg.evaluate("document.querySelector('#pie-wrap').classList.contains('open')"))

    # --- Evaluate verb → straight to the form ---
    pg.click("#home-evaluate")
    pg.wait_for_timeout(400)
    check("Evaluate: evaluator form visible + hash",
          pg.evaluate("location.hash") == "#evaluator"
          and not pg.evaluate("document.querySelector('#view-analyze').classList.contains('hide')"))
    check("Evaluate: tab bar restored", not pg.evaluate("document.querySelector('#nav').classList.contains('hide')"))
    check("Evaluate: '◂ Simplified' header button visible",
          not pg.evaluate("document.querySelector('#hdr-home').classList.contains('hide')"))

    # --- Advanced mode → full interface; header back-button → home ---
    pg.evaluate("navGo('home')"); pg.wait_for_timeout(200)
    pg.click("#home-advanced")
    pg.wait_for_timeout(400)
    check("Advanced: assignments view + tab bar",
          pg.evaluate("location.hash") == "#assignments"
          and not pg.evaluate("document.querySelector('#nav').classList.contains('hide')"))
    pg.click("#hdr-home")
    pg.wait_for_timeout(300)
    check("'◂ Simplified': back to home",
          pg.evaluate("location.hash") == "#home"
          and not pg.evaluate("document.querySelector('#view-home').classList.contains('hide')"))

    # --- browser back/forward through home ---
    pg.evaluate("navGo('assignments')"); pg.wait_for_timeout(300)
    pg.go_back(); pg.wait_for_timeout(300)
    check("back: assignments → home",
          pg.evaluate("location.hash") == "#home"
          and not pg.evaluate("document.querySelector('#view-home').classList.contains('hide')"))
    pg.go_forward(); pg.wait_for_timeout(300)
    check("forward: home → assignments",
          pg.evaluate("location.hash") == "#assignments"
          and not pg.evaluate("document.querySelector('#view-assignments').classList.contains('hide')"))

    # --- typed #home from another view ---
    pg.evaluate("() => { location.hash = '#home'; }")
    pg.wait_for_timeout(300)
    check("typed #home: home view shown",
          not pg.evaluate("document.querySelector('#view-home').classList.contains('hide')"))

    check("no JS errors (desktop)", not errors, errors[:3])

    # --- mobile 390 ---
    mctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                         user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15")
    m = mctx.new_page()
    merr = []
    m.on("pageerror", lambda e: merr.append(str(e)))
    login(m)
    m.wait_for_timeout(500)
    check("390: home visible at boot", not m.evaluate("document.querySelector('#view-home').classList.contains('hide')"))
    check("390: no page-level overflow",
          m.evaluate("document.documentElement.scrollWidth") <= 391,
          m.evaluate("document.documentElement.scrollWidth"))
    m.screenshot(path="tests/home_390.png")
    m.click("#home-analyze")
    m.wait_for_timeout(300)
    st = m.evaluate("""() => [...document.querySelectorAll('.pie-item')].map(b => {
      const r = b.getBoundingClientRect();
      return {t: b.textContent.trim(), inVp: r.left >= -1 && r.right <= 391 && r.top >= 0 && r.bottom <= 845};
    })""")
    check("390: pie(Analyze) 3 items all in viewport",
          len(st) == 3 and all(i["inVp"] for i in st), st)
    m.screenshot(path="tests/home_390_pie.png")
    m.click(".pie-item[data-pie-idx='2']")
    m.wait_for_timeout(500)
    check("390: pie 'Historique' → history cards",
          m.evaluate("location.hash") == "#history"
          and (m.evaluate("document.querySelectorAll('#hist-cards .hcard').length") > 0
               or m.evaluate("document.querySelectorAll('#hist tbody tr').length") > 0))
    check("390: no JS errors", not merr, merr[:3])
    mctx.close()
    ctx.close()
    b.close()

print("=" * 40)
print(f"=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
