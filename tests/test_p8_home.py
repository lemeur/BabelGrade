#!/usr/bin/env python3
"""Home (simplified mode) suite — radial menu v3 (2026-10-27).

Boot default is the simplified start screen (#view-home, hash #home).
the 3 rectangular verb buttons are GONE: the RADIAL menu (concentric SVG
crowns, innermost = the 3 verbs) OPENS BY DEFAULT; the rectangular
"Mode avancé" back-door button stays below the menu, ACTIVE even while the
menu is open (z-71 > backdrop z-70), and the hero title is NOT dimmed.
centred on #home-anchor. Each submenu level = an outer crown confined to
the selected parent's angular sector. Wheel/arrows cycle the outermost
level, Enter executes, Esc closes (a ghost re-open pill appears).

Covers (desktop 1280, FR; then 390px mobile):
- boot: #home hash, home view visible, menu OPEN with L0 (3 verbs FR) +
  L1 (Préparer's 2 items), hero title not dimmed, no JS errors, no
  rectangular .home-btn left
- crowns geometry: L1 angles inside the selected L0 sector (Préparer ≈
  [-150°,-30°] → L1 inside it), all sectors in the viewport
- navigation: wheel cycles L1 (Classe/Sujet), Enter executes → view + hash,
  menu closed; click Analyse inner sector → its 3-item crown; click
  Historique → history; re-open via #home-reopen pill
- "Mode avancé" rectangular button (ACTIVE while menu open) → assignments
  view; "◂ Simplified" header → back to home (menu re-opens)
- Evaluate leaf → evaluator form
- back button: home → assignments (push) → back lands on home + menu open
- typed #home from another view
- 390px: menu opens, crowns in viewport, leaf click navigates

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
  out.path = document.querySelector('#pie-path').textContent.trim().replace(/\\s+/g,' ');
  out.sectors = [...document.querySelectorAll('#pie-stage g[id^="rg-"]')]
    .filter(g => !g.classList.contains('g-exit'))
    .map(g => ({
      id: g.id,
      items: [...g.querySelectorAll('.sector')].map(s => ({
        t: (s.getAttribute('aria-label') || '').trim(),
        sel: s.classList.contains('selected') || s.classList.contains('sel-inner'),
        inVp: (() => { const r = s.getBoundingClientRect();
          return r.left >= -1 && r.right <= window.innerWidth + 1
              && r.top >= 0 && r.bottom <= window.innerHeight + 1; })()
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
        out[g.id] = [...g.querySelectorAll('.sector')].map(s => {
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
    pg.wait_for_timeout(700)

    # --- boot state: menu open by default ---
    s = pg.evaluate(JS_CROWNS)
    check("boot: hash #home", pg.evaluate("location.hash") == "#home")
    check("boot: home view visible",
          not pg.evaluate("document.querySelector('#view-home').classList.contains('hide')"))
    check("boot: no JS errors", not errors, errors[:3])
    check("boot: no rectangular .home-btn left", s["rectBtns"] == 0, s["rectBtns"])
    check("boot: radial menu OPEN by default", s["open"], s["open"])
    check("boot: re-open pill hidden while open", s["reopenHidden"], s)
    check("boot: L0 = 3 verbs (FR) + L1 = 2 items (Préparer)",
          [i["t"] for i in s["sectors"][0]["items"]] ==
          ["Préparer", "Évaluer", "Analyser"]
          and [i["t"] for i in s["sectors"][1]["items"]] ==
          ["Classe / élèves", "Sujet"], s["sectors"])
    check("boot: all sectors in viewport, svg in viewport",
          all(i["inVp"] for c in s["sectors"] for i in c["items"]) and s["svgIn"], s)
    check("boot: hero title not dimmed (z-71, above the menu backdrop)",
          pg.evaluate("getComputedStyle(document.querySelector('#view-home .home-hero')).zIndex") == "71")
    check("boot: centre shows the selected verb emoji (📚)", s["center"] == "📚", s["center"])
    check("boot: path pill = 📚 Préparer › 🏫 Classe / élèves",
          "Préparer" in s["path"] and "Classe / élèves" in s["path"], s["path"])
    pg.screenshot(path="tests/home_radial_boot.png")

    # --- geometry: L1 confined to the selected L0 sector ---
    ang = angles(pg)
    l0p = ang.get("rg-0", [None])[0]
    l1 = ang.get("rg-1", [])
    check("geometry: L0 Préparer ≈ [-150°,-30°] (360°/3 sectors)",
          l0p and l0p[0] <= -148 and l0p[1] >= -32 and l0p[1] <= -28, l0p)
    check("geometry: L1 inside the selected L0 sector (±GAP)",
          all(a[0] >= l0p[0] - 4 and a[1] <= l0p[1] + 4 for a in l1),
          {"l0": l0p, "l1": l1})

    # --- wheel cycles the outer crown; Enter executes ---
    pg.mouse.move(640, 450)
    pg.mouse.wheel(0, 120)
    pg.wait_for_timeout(250)
    s = pg.evaluate(JS_CROWNS)
    check("wheel: L1 selection moves to 'Sujet'",
          s["sectors"][1]["items"][1]["sel"] and "Sujet" in s["path"], s["path"])
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
    click_sector(pg, "#rg-0 .sector[data-idx='2']")   # Analyser
    pg.wait_for_timeout(300)
    s = pg.evaluate(JS_CROWNS)
    check("Analyse selected: L1 = 3 items (progression/results/history)",
          [i["t"] for i in s["sectors"][1]["items"]] ==
          ["Progression d’un élève", "Résultats sur un sujet", "Historique"],
          s["sectors"][1]["items"])
    check("centre shows 📊 when Analyse selected", s["center"] == "📊", s["center"])
    pg.screenshot(path="tests/home_radial_analyze.png")
    # geometry: Analyse's L1 must sit inside its L0 sector (≈ [90°,210°] with
    # 3 sectors of 120°)
    ang = angles(pg)
    l0a = ang.get("rg-0", [None])[2]
    l1a = ang.get("rg-1", [])
    check("geometry: L0 Analyse ≈ [90°,210°] (360°/3 sectors)",
          l0a and l0a[0] >= 88 and l0a[1] <= 212, l0a)
    check("geometry: Analyse L1 inside its L0 sector (±GAP)",
          l0a and all(a[0] >= l0a[0] - 4 and a[1] <= l0a[1] + 4 for a in l1a),
          {"l0": l0a, "l1": l1a})
    click_sector(pg, "#rg-1 .sector[data-idx='2']")   # Historique (leaf)
    pg.wait_for_timeout(600)
    check("'Historique' → history view + hash",
          pg.evaluate("location.hash") == "#history"
          and not pg.evaluate("document.querySelector('#view-history').classList.contains('hide')"))

    # --- re-open pill → menu opens ---
    pg.evaluate("navGo('home')")
    pg.wait_for_timeout(300)
    pg.evaluate("pieClose()")
    pg.wait_for_timeout(300)
    pg.click("#home-reopen")
    pg.wait_for_timeout(300)
    s = pg.evaluate(JS_CROWNS)
    check("re-open pill: clicking re-opens the menu at L0",
          s["open"] and s["sectors"][0]["items"][0]["sel"], s)

    # --- Esc closes ---
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(300)
    s = pg.evaluate(JS_CROWNS)
    check("Esc closes the menu", not s["open"], s["open"])

    # --- wheel cycles the OPEN outer crown even from L0 verbs (design: the
    #     wheel always drives the deepest open crown; L0 verbs are reached
    #     by clicking) ---
    pg.click("#home-reopen"); pg.wait_for_timeout(250)
    s = pg.evaluate(JS_CROWNS)
    l1_before = [i["sel"] for i in s["sectors"][1]["items"]]
    pg.mouse.move(640, 450)
    pg.mouse.wheel(0, 120)
    pg.wait_for_timeout(250)
    s = pg.evaluate(JS_CROWNS)
    l1_after = [i["sel"] for i in s["sectors"][1]["items"]]
    check("wheel from L0 verbs cycles the open L1 crown (Préparer → Sujet)",
          l1_before == [True, False] and l1_after == [False, True],
          {"before": l1_before, "after": l1_after})

    # --- "Mode avancé" rectangular button: ACTIVE even while the menu is
    #     open (z-71 above the backdrop) → full interface; header back → home
    #     (the menu is already open from the wheel-L0 check above)
    s = pg.evaluate(JS_CROWNS)
    check("'Mode avancé' button present while menu open", s["open"]
          and pg.evaluate("!!document.querySelector('#home-advanced')"), s["open"])
    pg.click("#home-advanced")
    pg.wait_for_timeout(400)
    check("'Mode avancé': assignments view + tab bar + menu closed",
          pg.evaluate("location.hash") == "#assignments"
          and not pg.evaluate("document.querySelector('#nav').classList.contains('hide')")
          and not pg.evaluate("document.querySelector('#pie-wrap').classList.contains('open')"))
    pg.click("#hdr-home")
    pg.wait_for_timeout(400)
    s = pg.evaluate(JS_CROWNS)
    check("'◂ Simplified': back to home + menu open",
          pg.evaluate("location.hash") == "#home" and s["open"], s["open"])

    # --- Evaluate leaf → evaluator form ---
    pg.evaluate("navGo('home')"); pg.wait_for_timeout(350)
    click_sector(pg, "#rg-0 .sector[data-idx='1']")          # Évaluer (leaf)
    pg.wait_for_timeout(400)
    check("Evaluate: evaluator form visible + hash",
          pg.evaluate("location.hash") == "#evaluator"
          and not pg.evaluate("document.querySelector('#view-analyze').classList.contains('hide')"))
    check("Evaluate: menu closed",
          not pg.evaluate("document.querySelector('#pie-wrap').classList.contains('open')"))

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
    m.wait_for_timeout(600)
    s = m.evaluate(JS_CROWNS)
    check("390: menu open at boot, L0 3 + L1 2",
          s["open"] and len(s["sectors"][0]["items"]) == 3 and len(s["sectors"][1]["items"]) == 2,
          {k: s[k] for k in ("open", "sectors")})
    check("390: no page-level overflow",
          m.evaluate("document.documentElement.scrollWidth") <= 391,
          m.evaluate("document.documentElement.scrollWidth"))
    check("390: svg + sectors in viewport",
          s["svgIn"] and all(i["inVp"] for c in s["sectors"] for i in c["items"]), s)
    m.screenshot(path="tests/home_390.png")
    click_sector(m, "#rg-0 .sector[data-idx='2']")   # Analyser
    m.wait_for_timeout(300)
    s = m.evaluate(JS_CROWNS)
    check("390: Analyse crown 3 items in viewport",
          len(s["sectors"][1]["items"]) == 3
          and all(i["inVp"] for i in s["sectors"][1]["items"]), s["sectors"][1])
    m.screenshot(path="tests/home_390_pie.png")
    click_sector(m, "#rg-1 .sector[data-idx='2']")   # Historique
    m.wait_for_timeout(600)
    check("390: 'Historique' → history view",
          m.evaluate("location.hash") == "#history")
    check("390: no JS errors", not merr, merr[:3])
    mctx.close()
    ctx.close()
    b.close()

print("=" * 40)
print(f"=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
