#!/usr/bin/env python3
"""Smoke test for the radial v3 mockup (file://, no server needed).

Model under test: concentric crowns. L0 = 3 verbs (innermost); each
additional submenu level = an OUTER crown that appears dynamically as
the user navigates: crown i+1 shows the children of the SELECTED sector
in crown i. The wheel/arrow keys cycle the OUTERMOST crown; Enter (or a
click on a leaf sector) executes + closes; a click on an inner sector
selects it and rebuilds the outer crowns; Esc / center / backdrop close.

Demo tree:  L0 Préparer/Évaluer/Analyser
            L1 (Préparer) Classe/élèves · Sujet ; (Analyser) Progression/Résultats/Historique
            L2 (Classe/élèves, DÉMO) Cours · Devoirs   ← 3rd level, removed at integration
"""
import sys
sys.path.insert(0, "/tmp/elt_dm/venv/lib/python3.11/site-packages")
from playwright.sync_api import sync_playwright

URL = "file:///home/tibo/elt-assessor/mockups/radial_v3.html"
PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f" | {extra}" if extra else ""))

def click_sector(pg, selector):
    """Click at the label center of a <g class=sector> (its bbox center can
    fall outside the wedge path, so Playwright's click would hit the <svg>)."""
    x, y = pg.evaluate(f"""() => {{
        const el = document.querySelector({selector!r});
        const r = el.querySelector('text').getBoundingClientRect();
        return [r.left + r.width / 2, r.top + r.height / 2];
    }}""")
    pg.mouse.click(x, y)

def rings_js():
    return """() => [...document.querySelectorAll('#pie-stage g[id^="rg-"]:not(.g-exit)')]
      .map(g => ({lv: +g.id.slice(3),
        sectors: [...g.querySelectorAll('.sector')].map(s => s.getAttribute('aria-label')),
        sel: g.querySelector('.sector.selected, .sector.sel-inner')?.getAttribute('aria-label') || null}))
      .sort((a,b) => a.lv - b.lv)"""

def log_js():
    return "document.querySelector('#log-lines').textContent"

def open_state_js():
    return "document.querySelector('#pie-wrap').classList.contains('open')"

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(URL, wait_until="load")
    pg.wait_for_timeout(300)
    check("no JS errors at boot", not errors, errors)

    # ---- open Prepare: L2 demo crown already grown (Classe has children) ----
    pg.click("#home-prepare")
    pg.wait_for_timeout(500)
    rings = pg.evaluate(rings_js())
    check("Prepare: 3 crowns (L2 demo grows under 'Classe')",
          [r["lv"] for r in rings] == [0, 1, 2], rings)
    check("L0: 3 verbs, Préparer selected",
          rings[0]["sectors"] == ["Préparer", "Évaluer", "Analyser"] and rings[0]["sel"] == "Préparer", rings[0])
    check("L1: Classe/Sujet, Classe selected",
          rings[1]["sectors"] == ["Classe / élèves", "Sujet"] and rings[1]["sel"] == "Classe / élèves", rings[1])
    check("L2: demo courses/homework, first selected",
          rings[2]["sectors"] == ["Cours (dém.)", "Devoirs (dém.)"] and rings[2]["sel"] == "Cours (dém.)", rings[2])
    check("center shows verb emoji",
          pg.evaluate("document.querySelector('#pie-center text')?.textContent") == "📚")
    vp = pg.evaluate("""() => {
        const r = document.querySelector('#pie-stage .menu').getBoundingClientRect();
        const crowns = [...document.querySelectorAll('#pie-stage g[id^="rg-"]')];
        const allIn = crowns.every(g => [...g.querySelectorAll('.sector')].every(s => {
            const ir = s.getBoundingClientRect();
            return ir.left >= 0 && ir.right <= innerWidth + 1 && ir.top >= 0 && ir.bottom <= innerHeight + 1;
        }));
        return {svgIn: r.left >= 0 && r.right <= innerWidth + 1 && r.top >= 0 && r.bottom <= innerHeight + 1, allIn};
    }""")
    check("desktop 1280: svg + all sectors of 3 crowns inside viewport", vp["svgIn"] and vp["allIn"], vp)
    # ANGULAR LIMITATION: every L1 sector must sit inside the 120° span of the
    # selected L0 sector (Préparer = [-150°, -30°]), every L2 sector inside the
    # selected L1 sector (Classe = [-150°, -90°]).
    geo = pg.evaluate("""() => {
        const deg = p => Math.atan2(p[1], p[0]) * 180 / Math.PI;
        const inSpan = (a, s0, s1) => { let x = (a - s0) % 360; if (x < 0) x += 360; return x <= s1 - s0 + 1; };
        /* path: M P0(outer,a0) A P1(outer,a1) L P2(inner,a1) A P3 Z */
        const angles = g => [...g.querySelectorAll('path')].map(p => {
            const d = p.getAttribute('d');
            const m0 = d.match(/^M\s*([-\d.]+)\s+([-\d.]+)/);
            const m1 = d.match(/L\s*([-\d.]+)\s+([-\d.]+)/);
            const a0 = deg([+m0[1], +m0[2]]), a1 = deg([+m1[1], +m1[2]]);
            return [Math.min(a0, a1), Math.max(a0, a1)];
        });
        const l0 = angles(document.querySelector('#rg-0'));
        const l1 = angles(document.querySelector('#rg-1'));
        const l2 = angles(document.querySelector('#rg-2'));
        return {l0, l1, l2,
                l1inL0: l1.every(([a,b]) => inSpan(a, l0[0][0], l0[0][1]) && inSpan(b, l0[0][0], l0[0][1])),
                l2inL1: l2.every(([a,b]) => inSpan(a, l1[0][0], l1[0][1]) && inSpan(b, l1[0][0], l1[0][1])),
                l0Sel: l0[0]};
    }""")
    check("geometry: L1 limited to selected L0 sector (Préparer ≈ [-150°,-30°])",
          abs(geo["l0Sel"][0] - -150) < 4 and abs(geo["l0Sel"][1] - -30) < 4 and geo["l1inL0"], geo["l0Sel"])
    check("geometry: L2 limited to selected L1 sector (Classe ≈ [-150°,-90°], 3° gap)",
          abs(geo["l1"][0][0] - -150) < 5 and abs(geo["l1"][0][1] - -90) < 5 and geo["l2inL1"],
          [geo["l1"][0], [a for a in geo["l2"]]])
    pg.screenshot(path="/home/tibo/elt-assessor/mockups/v3_prepare.png")

    # ---- wheel cycles the OUTERMOST crown (L2 demo) ----
    pg.mouse.move(640, 450)
    pg.mouse.wheel(0, 120)
    pg.wait_for_timeout(300)
    check("wheel L2: -> Devoirs", pg.evaluate(rings_js())[-1]["sel"] == "Devoirs (dém.)")
    pg.keyboard.press("Enter"); pg.wait_for_timeout(350)
    check("Enter on L2 leaf: closed + logged",
          not pg.evaluate(open_state_js())
          and "navGo(\"students/homework\") [démo]" in pg.evaluate(log_js()),
          pg.evaluate(log_js())[:80])
    pg.screenshot(path="/home/tibo/elt-assessor/mockups/v3_three_levels.png")

    # ---- click an INNER leaf sector: executes + closes ----
    pg.click("#home-prepare"); pg.wait_for_timeout(450)
    click_sector(pg, "#pie-stage #rg-1 .sector[data-idx='1']")   # 'Sujet' = leaf
    pg.wait_for_timeout(400)
    check("click leaf 'Sujet' (inner): executed + closed",
          not pg.evaluate(open_state_js())
          and "navGo(\"assignments\")" in pg.evaluate(log_js()),
          pg.evaluate(log_js())[:60])

    # ---- outer-crown dynamics: L2 collapses when the verb changes, regrows back ----
    pg.click("#home-prepare"); pg.wait_for_timeout(450)
    click_sector(pg, "#pie-stage #rg-0 .sector[data-idx='2']")   # L0 -> Analyser
    pg.wait_for_timeout(450)
    rings = pg.evaluate(rings_js())
    check("L0 -> Analyser: L2 collapsed, L1 rebuilt (3 items)",
          rings[0]["sel"] == "Analyser"
          and rings[1]["sectors"] == ["Progression d’un élève", "Résultats sur un sujet", "Historique"]
          and [r["lv"] for r in rings] == [0, 1], rings)
    pg.screenshot(path="/home/tibo/elt-assessor/mockups/v3_analyze.png")
    click_sector(pg, "#pie-stage #rg-0 .sector[data-idx='0']")   # L0 -> back to Préparer
    pg.wait_for_timeout(450)
    rings = pg.evaluate(rings_js())
    check("L0 -> Préparer again: L2 regrows dynamically",
          [r["lv"] for r in rings] == [0, 1, 2]
          and rings[1]["sectors"] == ["Classe / élèves", "Sujet"]
          and rings[2]["sectors"] == ["Cours (dém.)", "Devoirs (dém.)"], rings)

    # Esc closes
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    check("Esc: closed", not pg.evaluate(open_state_js()))

    # center-click closes
    pg.click("#home-evaluate"); pg.wait_for_timeout(400)
    pg.click("#pie-center"); pg.wait_for_timeout(300)
    check("center click: closed", not pg.evaluate(open_state_js()))

    # ---- EN switch re-renders labels while open ----
    pg.click("#lang-en"); pg.wait_for_timeout(200)
    pg.click("#home-prepare"); pg.wait_for_timeout(450)
    rings = pg.evaluate(rings_js())
    check("EN: labels translated in crowns",
          rings[0]["sectors"] == ["Prepare", "Evaluate", "Analyze"]
          and rings[1]["sectors"] == ["Class / students", "Subject"], rings)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    pg.click("#lang-fr"); pg.wait_for_timeout(300)

    # ---- mobile 390 ----
    ctx2 = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    pg2 = ctx2.new_page()
    pg2.goto(URL, wait_until="load"); pg2.wait_for_timeout(300)
    pg2.click("#home-analyze"); pg2.wait_for_timeout(500)
    state = pg2.evaluate("""() => {
        const svg = document.querySelector('#pie-stage .menu');
        const r = svg.getBoundingClientRect();
        const crowns = [...document.querySelectorAll('#pie-stage g[id^="rg-"]')];
        const allIn = crowns.every(g => [...g.querySelectorAll('.sector')].every(s => {
            const ir = s.getBoundingClientRect();
            return ir.left >= 0 && ir.right <= innerWidth + 1 && ir.top >= 0 && ir.bottom <= innerHeight + 1;
        }));
        return {svgIn: r.left >= 0 && r.right <= innerWidth + 1 && r.top >= 0 && r.bottom <= innerHeight + 1,
                nCrowns: crowns.length, allIn};
    }""")
    check("390px: 2 crowns, svg + all sectors inside viewport",
          state["svgIn"] and state["nCrowns"] == 2 and state["allIn"], state)
    pg2.screenshot(path="/home/tibo/elt-assessor/mockups/v3_390.png")
    pg2.keyboard.press("Escape"); pg2.wait_for_timeout(300)
    pg2.click("#home-prepare"); pg2.wait_for_timeout(500)
    state = pg2.evaluate("""() => {
        const svg = document.querySelector('#pie-stage .menu');
        const r = svg.getBoundingClientRect();
        return {nCrowns: document.querySelectorAll('#pie-stage g[id^="rg-"]').length,
                svgIn: r.left >= 0 && r.right <= innerWidth + 1 && r.top >= 0 && r.bottom <= innerHeight + 1};
    }""")
    check("390px: 3 crowns (demo) still fit", state["nCrowns"] == 3 and state["svgIn"], state)
    pg2.screenshot(path="/home/tibo/elt-assessor/mockups/v3_390_three.png")

    b.close()

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
