#!/usr/bin/env python3
"""Home (simplified mode) suite — radial menu v3 (2026-10-27).

Boot default is the simplified start screen (#view-home, hash #home).
the 3 rectangular verb buttons are GONE: the RADIAL menu (concentric SVG
crowns, innermost = the 3 verbs) OPENS BY DEFAULT; the rectangular
"Mode avancé" back-door button stays below the menu, ACTIVE even while the
menu is open (z-71 > backdrop z-70), and the hero title is NOT dimmed.
centred on #home-anchor. Each submenu level = an outer crown confined to
the selected parent's angular sector. Wheel/arrows move a SINGLE LINEAR
CURSOR through the leaves (tibo 2026-11-24): rien → S(v) → S(v,0) → … →
S(v,dernier) → S(v+1,0) → …, rétrograde symétrique ; Enter executes,
Esc closes (a ghost re-open pill appears).

Covers (desktop 1280, FR; then 390px mobile):
- boot: #home hash, home view visible, menu OPEN with L0 only (3 verbs FR:
  Évaluer top / Analyser right / Préparer left; NO pre-selected verb since
  2026-10-29 → no L1 sub-crown at boot, empty centre icon), hero title not
  dimmed, no JS errors, no rectangular .home-btn left, no #pie-path
  description pill (removed 2026-10-28: redundant, covered the "Mode avancé"
  button)
- crowns geometry: L0 Évaluer ≈ [-150°,-30°] (top sector); Analyse L1 inside
  its L0 sector
- navigation: wheel cycles L1 (Classe/Importer classe/Sujet), Enter executes
  → view + hash, menu closed; click Analyse inner sector → its 3-item crown
  (progression/results/Grilles — Historique moved under Évaluer 2026-10-29);
  click Grilles → rubrics; re-open via #home-reopen pill
- "Mode avancé" rectangular button (ACTIVE while menu open) → assignments
  view; "◂ Simplified" header → back to home (menu re-opens)
- Évaluateur verb → its sub-crown (Sur sujet / Directe): "Sur sujet"
  pre-selects the most recent assignment (inherited card up, ad-hoc boxes
  hidden), "Directe" is ad-hoc (context boxes visible) — 2026-10-28
- back button: home → assignments (push) → back lands on home + menu open
- typed #home from another view
- 390px: menu opens, crowns in viewport, leaf click navigates

Follows the repo test conventions: login(tibo/<tests/.credentials>), lang forced via
add_init_script, own checks + exit(1) on failure. No API writes → no
teardown needed."""
import sys
sys.path.insert(0, "/tmp/elt_dm/venv/lib/python3.11/site-packages")
import _testpw as TESTPW
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8090"
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

def login(pg, lang="fr"):
    pg.add_init_script(f"localStorage.setItem('babelgrade-lang','{lang}')")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", TESTPW.pw())
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)

JS_CROWNS = """() => {
  const out = {};
  out.open = document.querySelector('#pie-wrap').classList.contains('open');
  out.rectBtns = document.querySelectorAll('.home-btn').length;
  out.svgIn = (() => {
    const s = document.querySelector('#pie-stage svg.rsvg');
    if (!s) return false;
    const r = s.getBoundingClientRect();
    return r.left >= -1 && r.right <= window.innerWidth + 1
        && r.top >= 0 && r.bottom <= window.innerHeight + 1;
  })();
  out.hasPathPill = !!document.querySelector('#pie-path');
  out.sectors = [...document.querySelectorAll('#pie-stage g[id^="rg-"]')]
    .filter(g => !g.classList.contains('g-exit'))
    .map(g => ({
      id: g.id,
      items: [...g.querySelectorAll('.sector')]
        .sort((a, b) => (+a.dataset.idx) - (+b.dataset.idx))
        .map(s => ({
          t: (s.getAttribute('aria-label') || '').trim(),
          sel: s.classList.contains('selected') || s.classList.contains('sel-inner'),
          inVp: (() => { const r = s.getBoundingClientRect();
            return r.left >= -1 && r.right <= window.innerWidth + 1
                && r.top >= -1 && r.bottom <= window.innerHeight + 1; })()
        }))
    }));
  out.center = document.querySelector('#pie-center text')
    ? document.querySelector('#pie-center text').textContent : '';
  out.reopenHidden = document.querySelector('#home-reopen').classList.contains('hide');
  return out;
}"""

def angles(pg):
    """Sample each sector path's outline (getPointAtLength, in path order)
    and return [min, max] of the UNWRAPPED angles (deg, 0°=right, CW
    positive in screen coords) relative to the anchor centre. Unwrapping
    (±360° continuity) makes sectors crossing the ±180° line report their
    true [a0, a0+sweep] span (e.g. Analyse L0 = [90°, 210°]) instead of a
    meaningless min/max across the discontinuity."""
    return pg.evaluate("""() => {
      const out = {};
      for (const g of document.querySelectorAll('#pie-stage g[id^="rg-"]:not(.g-exit)')) {
        /* DOM = ordre de peinture inversé (idx 0 en dernier) → on trie par
           data-idx pour retrouver l'ordre logique des items. */
        out[g.id] = [...g.querySelectorAll('.sector')]
          .sort((a, b) => (+a.dataset.idx) - (+b.dataset.idx)).map(s => {
          const p = s.querySelector('path');
          const L = p.getTotalLength();
          const raw = [];
          for (let i = 0; i <= 40; i++) {
            /* SVG local coords: the viewBox origin (0,0) sits on the anchor */
            const pt = p.getPointAtLength(L * i / 40);
            raw.push(Math.atan2(pt.y, pt.x) * 180 / Math.PI);
          }
          /* unwrap: each sample within ±180° of the previous one */
          const un = [raw[0]];
          for (let i = 1; i < raw.length; i++) {
            let a = raw[i];
            while (a - un[i - 1] < -180) a += 360;
            while (a - un[i - 1] > 180) a -= 360;
            un.push(a);
          }
          let mn = Infinity, mx = -Infinity;
          for (const a of un) { mn = Math.min(mn, a); mx = Math.max(mx, a); }
          return [mn, mx];
        });
      }
      return out;
    }""")

def click_sector(pg, selector):
    x, y = pg.evaluate("""sel => {
      const s = document.querySelector(sel);
      const t = s.querySelector('.lbl') || s.querySelector('.em');
      const r = t.getBoundingClientRect();
      return [r.left + r.width / 2, r.top + r.height / 2];
    }""", selector)
    pg.mouse.click(x, y)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    login(pg)
    pg.wait_for_timeout(1300)   # laisse finir le fan-out L0 (+L1 retardé)

    # --- boot state: menu open by default, NO pre-selected verb
    #     (2026-10-29): L0 only, empty centre icon, sub-crown appears when a
    #     verb is picked (click or wheel) ---
    s = pg.evaluate(JS_CROWNS)
    check("boot: hash #home", pg.evaluate("location.hash") == "#home")
    check("boot: home view visible",
          not pg.evaluate("document.querySelector('#view-home').classList.contains('hide')"))
    check("boot: no JS errors", not errors, errors[:3])
    check("boot: no rectangular .home-btn left", s["rectBtns"] == 0, s["rectBtns"])
    check("boot: radial menu OPEN by default", s["open"], s["open"])
    check("boot: re-open pill hidden while open", s["reopenHidden"], s)
    check("boot: L0 = 3 verbs FR: Évaluer top / Analyser right / Préparer left",
          [i["t"] for i in s["sectors"][0]["items"]] ==
          ["Évaluer", "Analyser", "Préparer"], s["sectors"])
    check("boot: no L1 sub-crown at boot (no pre-selected verb, 2026-10-29)",
          len(s["sectors"]) == 1, s["sectors"])
    check("boot: all sectors in viewport, svg in viewport",
          all(i["inVp"] for c in s["sectors"] for i in c["items"]) and s["svgIn"], s)
    check("boot: hero title not dimmed (z-71, above the menu backdrop)",
          pg.evaluate("getComputedStyle(document.querySelector('#view-home .home-hero')).zIndex") == "71")
    check("boot: centre empty at boot (no pre-selected verb, 2026-10-29)", s["center"] == "", s["center"])
    check("boot: header trimmed on home — 'Évaluer' button + Data menu hidden",
          pg.evaluate("getComputedStyle(document.querySelector('#hdr-evaluate')).display") == "none"
          and pg.evaluate("getComputedStyle(document.querySelector('#menu-data-wrap')).display") == "none")
    check("boot: header ACTIVE on home (user chip + language flag reachable, above the backdrop)",
          pg.evaluate("getComputedStyle(document.querySelector('header')).zIndex") == "74"
          and pg.evaluate("!!document.querySelector('#user-chip-wrap') && "
                         "!document.querySelector('#user-chip-wrap').classList.contains('hide')")
          and pg.evaluate("getComputedStyle(document.querySelector('#lang-tgl')).display") == "flex")
    check("boot: no #pie-path description pill (removed 2026-10-28)",
          not s["hasPathPill"], s["hasPathPill"])
    pg.screenshot(path="tests/home_radial_boot.png")

    # --- geometry: L0 sector placement (span [-150°,210°]: idx0 top, idx1
    #     bottom-right, idx2 bottom-left) ---
    ang = angles(pg)
    l0e = ang.get("rg-0", [None])[0]
    check("geometry: L0 Évaluer ≈ [-150°,-30°] (top sector)",
          l0e and l0e[0] <= -148 and l0e[1] >= -32 and l0e[1] <= -28, l0e)

    # --- resize: the menu must RE-CENTRE on #home-anchor (2026-11-25, tibo) ---
    #     #home-center's height is vh-based, so resizing moves the anchor; the
    #     crowns used to stay stuck on the centre captured at openMenu().
    def centres():
        return pg.evaluate("""() => {
          const s = document.querySelector('#pie-stage svg.rsvg');
          const a = document.getElementById('home-anchor');
          const r1 = s.getBoundingClientRect(), r2 = a.getBoundingClientRect();
          return [r1.left + r1.width/2, r1.top + r1.height/2,
                  r2.left + r2.width/2, r2.top + r2.height/2];
        }""")
    c0 = centres()
    check("resize: boot svg centred on anchor (1280x900)",
          abs(c0[0] - c0[2]) < 2 and abs(c0[1] - c0[3]) < 2, c0)
    pg.set_viewport_size({"width": 900, "height": 1300})
    pg.wait_for_timeout(500)   # > the 150 ms debounce
    c1 = centres()
    check("resize 900x1300: svg re-centred on anchor",
          abs(c1[0] - c1[2]) < 2 and abs(c1[1] - c1[3]) < 2, c1)
    pg.set_viewport_size({"width": 1400, "height": 520})
    pg.wait_for_timeout(500)
    c2 = centres()
    check("resize 1400x520: svg re-centred on anchor",
          abs(c2[0] - c2[2]) < 2 and abs(c2[1] - c2[3]) < 2, c2)
    pg.set_viewport_size({"width": 1280, "height": 900})
    pg.wait_for_timeout(500)
    c3 = centres()
    check("resize back 1280x900: svg re-centred on anchor",
          abs(c3[0] - c3[2]) < 2 and abs(c3[1] - c3[3]) < 2, c3)
    # the resize re-render replays the fan-in (stagger up to ~940 ms after the
    # 150 ms debounce) — let it settle before the click-based checks below.
    pg.wait_for_timeout(1200)

    # --- click Préparer → its L1 crown (Classe/Sujet); NO item pre-selected ---
    click_sector(pg, "#rg-0 .sector[data-idx='2']")   # Préparer (bottom-left)
    pg.wait_for_timeout(1500)
    s = pg.evaluate(JS_CROWNS)
    check("Préparer selected: L1 = 3 items (Classe / Importer classe / Sujet), none pre-selected",
          [i["t"] for i in s["sectors"][1]["items"]] ==
          ["Classe / élèves", "Importer une classe (photos)", "Sujet"]
          and not any(i["sel"] for i in s["sectors"][1]["items"]),
          s["sectors"])
    check("centre shows 📚 when Préparer selected", s["center"] == "📚", s["center"])
    ang = angles(pg)
    l0p = ang.get("rg-0", [None])[2]
    l1 = ang.get("rg-1", [])
    check("geometry: L0 Préparer ≈ [90°,210°] (bottom-left sector)",
          l0p and l0p[0] >= 88 and l0p[1] <= 212, l0p)
    check("geometry: L1 inside the selected L0 sector (±GAP)",
          all(a[0] >= l0p[0] - 4 and a[1] <= l0p[1] + 4 for a in l1),
          {"l0": l0p, "l1": l1})

    # --- wheel: first press SELECTS the first item (was unselected); ---
    # --- next presses cycle 'Importer une classe (photos)' then 'Sujet';
    # --- Enter executes the 'Sujet' leaf ---
    pg.mouse.move(640, 450)
    pg.mouse.wheel(0, 120)
    pg.wait_for_timeout(250)
    s = pg.evaluate(JS_CROWNS)
    check("wheel: L1 selection moves to 'Classe / élèves' (from unselected)",
          s["sectors"][1]["items"][0]["sel"]
          and not s["sectors"][1]["items"][1]["sel"]
          and not s["sectors"][1]["items"][2]["sel"], s["sectors"])
    pg.mouse.wheel(0, 120)
    pg.wait_for_timeout(250)
    s = pg.evaluate(JS_CROWNS)
    check("wheel: L1 selection cycles to 'Importer une classe (photos)'",
          s["sectors"][1]["items"][1]["sel"], s["sectors"])
    pg.mouse.wheel(0, 120)
    pg.wait_for_timeout(250)
    s = pg.evaluate(JS_CROWNS)
    check("wheel: L1 selection cycles to 'Sujet'",
          s["sectors"][1]["items"][2]["sel"], s["sectors"])
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(500)
    check("Enter on 'Sujet': assignments view + hash",
          pg.evaluate("location.hash") == "#assignments"
          and not pg.evaluate("document.querySelector('#view-assignments').classList.contains('hide')"))
    check("menu closed after navigation",
          not pg.evaluate("document.querySelector('#pie-wrap').classList.contains('open')"))
    check("re-open pill visible after close",
          not pg.evaluate("document.querySelector('#home-reopen').classList.contains('hide')"))

    # --- back to home: menu re-opens; Analyse branch ---
    pg.evaluate("navGo('home')")
    pg.wait_for_timeout(400)
    s = pg.evaluate(JS_CROWNS)
    check("return home: menu re-opened by default", s["open"], s)
    click_sector(pg, "#rg-0 .sector[data-idx='1']")   # Analyser (bottom-right)
    pg.wait_for_timeout(1500)
    s = pg.evaluate(JS_CROWNS)
    check("Analyse selected: L1 = 3 items (progression/results/grilles)",
          [i["t"] for i in s["sectors"][1]["items"]] ==
          ["Progression d’un élève", "Résultats sur un sujet", "Grilles"],
          s["sectors"][1]["items"])
    check("centre shows 📊 when Analyse selected", s["center"] == "📊", s["center"])
    pg.screenshot(path="tests/home_radial_analyze.png")
    # geometry: Analyse's L1 must sit inside its L0 sector (≈ [-30°,90°] with
    # 3 sectors of 120°)
    ang = angles(pg)
    l0a = ang.get("rg-0", [None])[1]
    l1a = ang.get("rg-1", [])
    check("geometry: L0 Analyse ≈ [-30°,90°] (bottom-right sector)",
          l0a and l0a[0] >= -32 and l0a[1] <= 92, l0a)
    check("geometry: Analyse L1 inside its L0 sector (±GAP)",
          l0a and all(a[0] >= l0a[0] - 4 and a[1] <= l0a[1] + 4 for a in l1a),
          {"l0": l0a, "l1": l1a})
    click_sector(pg, "#rg-1 .sector[data-idx='2']")   # Grilles (leaf; Historique
                                                      # moved under Évaluer 2026-10-29)
    pg.wait_for_timeout(600)
    check("'Grilles' → rubrics view + hash",
          pg.evaluate("location.hash") == "#rubrics"
          and not pg.evaluate("document.querySelector('#view-rubrics').classList.contains('hide')"))

    # --- re-open pill → menu opens ---
    pg.evaluate("navGo('home')")
    pg.wait_for_timeout(300)
    pg.evaluate("pieClose()")
    pg.wait_for_timeout(300)
    pg.click("#home-reopen")
    pg.wait_for_timeout(300)
    s = pg.evaluate(JS_CROWNS)
    check("re-open pill: clicking re-opens the menu at L0 (nothing pre-selected)",
          s["open"] and len(s["sectors"]) == 1
          and not any(i["sel"] for i in s["sectors"][0]["items"]), s)

    # --- Esc closes ---
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(300)
    s = pg.evaluate(JS_CROWNS)
    check("Esc closes the menu", not s["open"], s["open"])

    # --- wheel at boot (nothing pre-selected, 2026-10-29): first press
    #     SELECTS the L0 verb 'Évaluer' (which opens its sub-crown); further
    #     presses cycle the L1 crown 'Sur sujet' → 'Directe' → 'Historique';
    #     Enter runs the selected leaf ---
    pg.click("#home-reopen"); pg.wait_for_timeout(250)
    pg.mouse.move(640, 450)
    pg.mouse.wheel(0, 120)
    pg.wait_for_timeout(250)
    s = pg.evaluate(JS_CROWNS)
    check("wheel: 1st press selects L0 'Évaluer' + opens its L1 crown",
          s["sectors"][0]["items"][0]["sel"]
          and not any(i["sel"] for i in s["sectors"][1]["items"])
          and [i["t"] for i in s["sectors"][1]["items"]] ==
              ["Sur sujet", "Directe", "Historique"],
          s["sectors"])
    pg.mouse.wheel(0, 120)
    pg.wait_for_timeout(250)
    s = pg.evaluate(JS_CROWNS)
    check("wheel: L1 selection moves to 'Sur sujet' (from unselected)",
          s["sectors"][1]["items"][0]["sel"]
          and not s["sectors"][1]["items"][1]["sel"],
          [i["t"] for i in s["sectors"][1]["items"]])
    pg.mouse.wheel(0, 120)
    pg.wait_for_timeout(250)
    s = pg.evaluate(JS_CROWNS)
    check("wheel: L1 selection moves to 'Directe'",
          s["sectors"][1]["items"][1]["sel"] and s["center"] == "✍️",
          [i["t"] for i in s["sectors"][1]["items"]])
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(500)
    check("Enter on 'Directe': evaluator form + ad-hoc context boxes visible",
          pg.evaluate("location.hash") == "#evaluator"
          and not pg.evaluate("document.querySelector('#view-analyze').classList.contains('hide')")
          and pg.evaluate("document.querySelector('#assignment-edit-row').classList.contains('hide')"
                          " && document.querySelector('#context-panel').style.display!=='none'"))
    check("menu closed after Enter",
          not pg.evaluate("document.querySelector('#pie-wrap').classList.contains('open')"))

    # --- "Mode avancé" rectangular button: ACTIVE even while the menu is
    #     open (z-71 above the backdrop) → full interface; header back → home
    #     (menu re-opens on home) ---
    pg.evaluate("navGo('home')"); pg.wait_for_timeout(400)
    s = pg.evaluate(JS_CROWNS)
    check("'Mode avancé' button present while menu open", s["open"]
          and pg.evaluate("!!document.querySelector('#home-advanced')"), s["open"])
    pg.click("#home-advanced")
    pg.wait_for_timeout(400)
    check("'Mode avancé': assignments view + tab bar + menu closed",
          pg.evaluate("location.hash") == "#assignments"
          and not pg.evaluate("document.querySelector('#nav').classList.contains('hide')")
          and not pg.evaluate("document.querySelector('#pie-wrap').classList.contains('open')"))
    check("'Mode avancé': header restored — 'Évaluer' + Data menu back on the advanced screen",
          pg.evaluate("getComputedStyle(document.querySelector('#hdr-evaluate')).display") != "none"
          and pg.evaluate("getComputedStyle(document.querySelector('#menu-data-wrap')).display") != "none")
    pg.click("#hdr-home")
    pg.wait_for_timeout(400)
    s = pg.evaluate(JS_CROWNS)
    check("'◂ Simplified': back to home + menu open",
          pg.evaluate("location.hash") == "#home" and s["open"], s["open"])

    # --- Evaluate verb → its sub-crown (Sur sujet / Directe); each leaf goes
    #     to the evaluator in its own state: "Sur sujet" pre-selects the most
    #     recent assignment (inherited card up, ad-hoc boxes hidden), "Directe"
    #     is ad-hoc (context boxes visible) ---
    pg.evaluate("navGo('home')"); pg.wait_for_timeout(350)
    click_sector(pg, "#rg-0 .sector[data-idx='0']")          # Évaluer (top, verb)
    pg.wait_for_timeout(400)
    s = pg.evaluate(JS_CROWNS)
    check("Évaluateur sub-crown open: L1 = Sur sujet / Directe / Historique",
          len(s["sectors"]) == 2
          and [i["t"] for i in s["sectors"][1]["items"]] ==
              ["Sur sujet", "Directe", "Historique"],
          s["sectors"])
    click_sector(pg, "#rg-1 .sector[data-idx='0']")          # Sur sujet (leaf)
    pg.wait_for_timeout(400)
    check("'Sur sujet' → evaluator + most recent assignment pre-selected",
          pg.evaluate("location.hash") == "#evaluator"
          and not pg.evaluate("document.querySelector('#view-analyze').classList.contains('hide')")
          and pg.evaluate("document.querySelector('#assignment').value!==''")
          and pg.evaluate("!document.querySelector('#assignment-edit-row').classList.contains('hide')"))
    check("menu closed after 'Sur sujet'",
          not pg.evaluate("document.querySelector('#pie-wrap').classList.contains('open')"))
    # back to home, then the Directe branch
    pg.evaluate("navGo('home')"); pg.wait_for_timeout(350)
    click_sector(pg, "#rg-0 .sector[data-idx='0']")          # Évaluer
    pg.wait_for_timeout(300)
    click_sector(pg, "#rg-1 .sector[data-idx='1']")          # Directe (leaf)
    pg.wait_for_timeout(400)
    check("'Directe' → evaluator + ad-hoc context boxes visible (no subject)",
          pg.evaluate("location.hash") == "#evaluator"
          and not pg.evaluate("document.querySelector('#view-analyze').classList.contains('hide')")
          and pg.evaluate("document.querySelector('#assignment').selectedIndex === 0")
          and pg.evaluate("document.querySelector('#context-panel').style.display !== 'none'"))

    # --- browser back/forward through home (menu must re-open on home) ---
    pg.evaluate("navGo('home')"); pg.wait_for_timeout(350)   # pop-back to the root entry
    pg.evaluate("navGo('assignments')"); pg.wait_for_timeout(300)  # push
    pg.go_back(); pg.wait_for_timeout(400)
    s = pg.evaluate(JS_CROWNS)
    check("back: assignments → home + menu open",
          pg.evaluate("location.hash") == "#home" and s["open"], s["open"])
    pg.go_forward(); pg.wait_for_timeout(400)
    check("forward: home → assignments",
          pg.evaluate("location.hash") == "#assignments"
          and not pg.evaluate("document.querySelector('#view-assignments').classList.contains('hide')"))
    check("forward: menu closed on assignments",
          not pg.evaluate("document.querySelector('#pie-wrap').classList.contains('open')"))

    # --- typed #home from another view ---
    pg.evaluate("() => { location.hash = '#home'; }")
    pg.wait_for_timeout(400)
    s = pg.evaluate(JS_CROWNS)
    check("typed #home: home view shown + menu open",
          not pg.evaluate("document.querySelector('#view-home').classList.contains('hide')")
          and s["open"], s["open"])

    check("no JS errors (desktop)", not errors, errors[:3])

    # --- mobile 390 ---
    mctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                         user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15")
    m = mctx.new_page()
    merr = []
    m.on("pageerror", lambda e: merr.append(str(e)))
    login(m)
    m.wait_for_timeout(1900)   # laisse finir le fan-out L0 + L1 retardé
    s = m.evaluate(JS_CROWNS)
    check("390: menu open at boot, L0 = 3 verbs, no L1 (no pre-selected verb)",
          s["open"] and len(s["sectors"][0]["items"]) == 3 and len(s["sectors"]) == 1,
          {k: s[k] for k in ("open", "sectors")})
    check("390: no page-level overflow",
          m.evaluate("document.documentElement.scrollWidth") <= 391,
          m.evaluate("document.documentElement.scrollWidth"))
    check("390: svg + sectors in viewport",
          s["svgIn"] and all(i["inVp"] for c in s["sectors"] for i in c["items"]), s)
    # mobile resize: same re-centring invariant (vh-based anchor, 2026-11-25)
    m.set_viewport_size({"width": 390, "height": 700})
    m.wait_for_timeout(500)
    cm = m.evaluate("""() => {
      const sv = document.querySelector('#pie-stage svg.rsvg');
      const a = document.getElementById('home-anchor');
      const r1 = sv.getBoundingClientRect(), r2 = a.getBoundingClientRect();
      return [r1.left + r1.width/2, r1.top + r1.height/2,
              r2.left + r2.width/2, r2.top + r2.height/2];
    }""")
    check("390: resize to 700h → svg re-centred on anchor",
          abs(cm[0] - cm[2]) < 2 and abs(cm[1] - cm[3]) < 2, cm)
    m.screenshot(path="tests/home_390.png")
    click_sector(m, "#rg-0 .sector[data-idx='1']")   # Analyser
    m.wait_for_timeout(1800)
    s = m.evaluate(JS_CROWNS)
    check("390: Analyse crown 3 items in viewport",
          len(s["sectors"][1]["items"]) == 3
          and all(i["inVp"] for i in s["sectors"][1]["items"]), s["sectors"][1])
    m.screenshot(path="tests/home_390_pie.png")
    click_sector(m, "#rg-1 .sector[data-idx='2']")   # Grilles (Historique moved
                                                     # under Évaluer 2026-10-29)
    m.wait_for_timeout(600)
    check("390: 'Grilles' → rubrics view",
          m.evaluate("location.hash") == "#rubrics")
    check("390: no JS errors", not merr, merr[:3])
    mctx.close()
    ctx.close()
    b.close()

print("=" * 40)
print(f"=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
