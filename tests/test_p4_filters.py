#!/usr/bin/env python3
"""P4 verify: filter rows collapsed by default + 🔍 toggle (2026-10-15, tibo ask).

Sujets + Évaluations only (tibo scope decision — Rubriques/Élèves untouched).

Checks (1280px + 390px unless noted):
- filter row hidden at boot, toggle button visible with the localized label
  and NO count badge (class .off)
- toggle opens the row; toggle again closes it
- typing into a filter field shows the count badge (1), button loses .off
- a 2nd active filter bumps the badge to 2
- Reset / chip clear brings the badge back to 0 and .off
- filter still works while the row is CLOSED (deep-link assignment chip)
- language switch FR keeps the label translated ("Filtres" / "Filters")
- 390px: no horizontal overflow with the row open

Seeding: one assignment named 'P4 toggle check' via FormData POST
/api/assignments (the real Form contract). Teardown: DELETE it at the end."""
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
    pg.wait_for_timeout(800)

def state(pg, row, btn, n):
    return pg.evaluate("""({row,btn,n}) => ({
      rowHidden: document.querySelector(row).classList.contains('hide'),
      btnOff: document.querySelector(btn).classList.contains('off'),
      badgeHidden: document.querySelector(n).classList.contains('hide'),
      badge: document.querySelector(n).textContent,
      label: document.querySelector(btn + ' span[data-i18n]').textContent,
      expanded: document.querySelector(btn).getAttribute('aria-expanded')
    })""", {"row": row, "btn": btn, "n": n})

def ensure_app(pg):
    """After a reload: session cookie may survive (app boots straight in) or
    not (login gate). Wait for whichever, and log in if needed."""
    try:
        pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=15000)
    except Exception:
        pg.wait_for_selector("#auth-username", state="visible", timeout=15000)
        pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", "****")
        pg.click("#auth-login-btn")
        pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))

    login(pg)

    # seed a known assignment
    seeded = pg.evaluate("""async () => {
      const fd = new FormData();
      fd.append('name','P4 toggle check');
      fd.append('target_level','B2');
      const r = await fetch('/api/assignments',{method:'POST',body:fd});
      return await r.json();
    }""")
    asg_id = str(seeded.get("id"))

    # refresh the cached ASSIGNMENTS (boot cache predates the seeded row)
    pg.evaluate("(async () => { await loadAssignments(); })()")

    A = {"row": "#asg-filters", "btn": "#asg-filter-tgl", "n": "#asg-ftl-n"}
    H = {"row": "#hist-filters", "btn": "#hist-filter-tgl", "n": "#hist-ftl-n"}

    # ---- Sujets ----
    s = state(pg, **A)
    check("asg: filter row hidden at boot", s["rowHidden"], s)
    check("asg: toggle visible, off state, no badge",
          s["btnOff"] and s["badgeHidden"] and s["expanded"] == "false", s)
    check("asg: FR label 'Filtres'", s["label"] == "Filtres", s["label"])

    pg.click("#asg-filter-tgl")
    s = state(pg, **A)
    check("asg: click opens the row", not s["rowHidden"] and s["expanded"] == "true", s)

    pg.fill("#asg-filter-name", "P4 toggle")
    pg.wait_for_timeout(500)
    s = state(pg, **A)
    check("asg: name filter -> badge 1, active style",
          s["badge"] == "1" and not s["badgeHidden"] and not s["btnOff"], s)
    rows = pg.evaluate(
        "document.querySelectorAll('#assignments tbody tr:not(:has(td[colspan]))').length")
    check("asg: filter still applies while row is being used", rows >= 1, rows)

    pg.select_option("#asg-filter-level", "B2")
    pg.wait_for_timeout(300)
    s = state(pg, **A)
    check("asg: second filter -> badge 2", s["badge"] == "2", s)

    pg.click("#asg-filter-clear")
    pg.wait_for_timeout(300)
    s = state(pg, **A)
    check("asg: reset -> badge hidden, off style",
          s["badgeHidden"] and s["btnOff"], s)

    pg.click("#asg-filter-tgl")
    s = state(pg, **A)
    check("asg: second click closes the row", s["rowHidden"] and s["expanded"] == "false", s)

    # ---- Évaluations ----
    pg.click('#nav button[data-view="history"]')
    pg.wait_for_selector("#hist tbody tr, .hcard")
    pg.wait_for_timeout(600)
    s = state(pg, **H)
    check("hist: filter row hidden at boot", s["rowHidden"], s)
    check("hist: toggle off, no badge", s["btnOff"] and s["badgeHidden"], s)

    pg.click("#hist-filter-tgl")
    s = state(pg, **H)
    check("hist: click opens the row", not s["rowHidden"], s)

    pg.fill("#hist-title", "P4-toggle")
    pg.wait_for_timeout(900)
    s = state(pg, **H)
    check("hist: title filter -> badge 1", s["badge"] == "1" and not s["btnOff"], s)

    # a deep-link assignment chip also counts as an active filter
    pg.select_option("#hist-assignment", asg_id)
    pg.wait_for_timeout(900)
    s = state(pg, **H)
    check("hist: title + assignment -> badge 2", s["badge"] == "2", s)
    chip = pg.evaluate("!document.querySelector('#hist-assignment-chip').classList.contains('hide')")
    check("hist: assignment chip visible (synced)", chip)

    pg.click("#hist-clear")
    pg.wait_for_timeout(900)
    s = state(pg, **H)
    check("hist: reset -> badge hidden, off style", s["badgeHidden"] and s["btnOff"], s)

    # label follows the language (in-app switch via the flag menu — the real
    # user path: setLang() rewrites every data-i18n label live, no reload)
    pg.evaluate("setLang('en')")
    pg.wait_for_timeout(200)
    s = state(pg, **A)
    check("asg: EN label 'Filters' after in-app switch", s["label"] == "Filters", s["label"])
    s = state(pg, **H)
    check("hist: EN label 'Filters' after in-app switch", s["label"] == "Filters", s["label"])
    pg.evaluate("setLang('fr')")

    # ---- 390px mobile (fresh context: mobile UA viewport + EN) ----
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    m = ctx.new_page()
    m.on("pageerror", lambda e: errors.append("390:" + str(e)))
    m.add_init_script("localStorage.setItem('elt-lang','fr')")
    m.goto(BASE, wait_until="networkidle")
    ensure_app(m)
    m.wait_for_load_state("networkidle")
    m.wait_for_timeout(400)
    s = state(m, **A)
    check("390: asg row hidden at boot", s["rowHidden"], s)
    m.click("#asg-filter-tgl")
    overflow = m.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth")
    check("390: no horizontal overflow with row open", overflow <= 0, overflow)
    m.click('#nav button[data-view="history"]')
    m.wait_for_selector("#hist-cards .hcard")   # mobile: the table is hidden, cards are the list
    m.wait_for_load_state("networkidle")
    m.click("#hist-filter-tgl")
    overflow = m.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth")
    check("390: hist no overflow with row open", overflow <= 0, overflow)
    ctx.close()

    check("no JS page errors", not errors, errors[:3])

    # teardown
    pg.evaluate("""async (id) => { await fetch('/api/assignments/'+id,{method:'DELETE'}) }""", asg_id)
    b.close()

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", FAIL)
    raise SystemExit(1)
