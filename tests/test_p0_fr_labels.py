#!/usr/bin/env python3
"""P0.4 verify: written/oral labels localized (FR: écrit/oral) in
history table, mobile hcard meta, rubrics list pill, and #r-mode select options.
Also: language switch EN->FR re-renders without raw 'written'."""
import os
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
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", "****")
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    pg.wait_for_timeout(1500)
    # 2026-10-27: boot default = home view, where the tab bar is HIDDEN —
    # these tests click nav buttons right after login, so open assignments.
    pg.evaluate("navGo('assignments')")
    pg.wait_for_timeout(400)

def history_kind_texts(pg):
    return pg.evaluate("""() => {
      const rows = [...document.querySelectorAll('#hist tbody tr')].map(tr =>
        [...tr.cells].map(td => td.textContent.trim()));
      const cards = [...document.querySelectorAll('#hist-cards .hcard-meta')]
        .map(m => m.textContent.trim());
      return {rows, cards, anyWrittenRaw:
        rows.join('\\n').includes('written') || cards.join('\\n').includes('written')};
    }""")

with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])

    # ---------- FR desktop: history + rubrics ----------
    print("== FR desktop ==")
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg, "fr")
    pg.click('#nav button[data-view="history"]'); pg.wait_for_timeout(2000)
    h = history_kind_texts(pg)
    check("FR history: no raw 'written' anywhere", not h["anyWrittenRaw"],
          [r for r in h["rows"][:3]])
    check("FR history: at least one 'Écrit' cell", any("Écrit" in r[4] for r in h["rows"] if len(r) > 4),
          [r[4] for r in h["rows"][:5]])
    pg.screenshot(path=os.path.join(OUT, "p04_hist_fr.png"))

    # rubrics list
    pg.click('#nav button[data-view="rubrics"]'); pg.wait_for_timeout(1500)
    pills = pg.evaluate("""() => [...document.querySelectorAll('#rubric-list .rub-row .pill')]
      .map(p => p.textContent.trim())""")
    check("FR rubrics: pills use Écrit/Oral (no raw 'written')",
          any(p == "Écrit" for p in pills) and not any(p == "written" for p in pills), pills[:8])
    pg.screenshot(path=os.path.join(OUT, "p04_rubrics_fr.png"))

    # #r-mode select options localized
    opts = pg.evaluate("""() => {
      const sel = document.querySelector('#rubric-edit-overlay select#r-mode') || document.getElementById('r-mode');
      return sel ? [...sel.options].map(o => o.textContent.trim()) : null;
    }""")
    check("FR #r-mode options localized", opts and "Écrit" in opts and "Oral" in opts, opts)
    check("FR no JS errors", not errs, errs[:2])
    ctx.close()

    # ---------- FR mobile: hcard meta ----------
    print("== FR mobile 390 ==")
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15")
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg, "fr")
    pg.click('#nav button[data-view="history"]'); pg.wait_for_timeout(2000)
    h = history_kind_texts(pg)
    check("FR mobile hcard meta: no raw 'written'", not h["anyWrittenRaw"], h["cards"][:3])
    check("FR mobile hcard meta: 'Écrit' present", any("Écrit" in c for c in h["cards"]), h["cards"][:3])
    check("FR mobile no JS errors", not errs, errs[:2])
    ctx.close()

    # ---------- EN -> FR switch: history re-rendered ----------
    print("== EN->FR switch ==")
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg, "en")
    pg.click('#nav button[data-view="history"]'); pg.wait_for_timeout(2000)
    # switch language in place (lang menu)
    pg.evaluate("() => { setLang && setLang('fr'); }")
    pg.wait_for_timeout(1500)
    h = history_kind_texts(pg)
    check("after switch FR: no raw 'written'", not h["anyWrittenRaw"], h["rows"][:2])
    check("after switch FR: 'Écrit' present", any("Écrit" in r[4] for r in h["rows"] if len(r) > 4),
          [r[4] for r in h["rows"][:5]])
    check("switch no JS errors", not errs, errs[:2])
    ctx.close()

    b.close()

print(f"\n=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
if FAIL: print("FAILED:", FAIL)
