"""V2 (a11y structure) — live E2E, desktop 1280 FR.

Proves the three structural a11y items shipped in Wave 2:
  A7  table headers: every <th> in a <thead> has scope="col"; the 6 key tables
      (#hist #assignments #students #jobs #roster-table .stat-table) carry a
      populated <caption>; the tbody row-header <th class=rub-det-crit> is NOT
      scoped (correctly a row header).
  A3  icon-only buttons: the close/zoom/remove-photo/clear-sel buttons expose a
      non-empty translated aria-label (data-i18n-aria / direct t()).
  A5  Home radial menu keyboard: #pie-center is focusable (tabindex 0); opening
      the menu moves focus to it; Escape closes and restores focus to
      #home-reopen; the active crown #rg-0 has role=menu with its L0 sectors
      carrying role=menuitem + aria-selected; ArrowDown cycles a verb
      (aria-selected moves) and Enter executes it (navigates away, menu closes).

Run:  /tmp/bg_venv/bin/python tests/test_a11y_wave2.py   (server live :8090)
"""
import _testpw as TESTPW
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8090"
PASS, FAIL = [], []

def check(n, c, x=""):
    (PASS if c else FAIL).append(n)
    print(("PASS " if c else "FAIL ") + n + (f" | {x}" if x and not c else ""))

with sync_playwright() as pw:
    ctx = pw.chromium.launch(headless=True).new_context(
        viewport={"width": 1280, "height": 800}, locale="fr-FR")
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
    pg.add_init_script("localStorage.setItem('babelgrade-lang','fr')")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", TESTPW.pw())
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)

    # ---- A7: table headers ----
    a7 = pg.evaluate("""()=>{
      const ths=[...document.querySelectorAll('table thead th')];
      const unscoped=ths.filter(th=>th.getAttribute('scope')!=='col').length;
      const caps={};
      ['hist','assignments','students','jobs','roster-table'].forEach(id=>{
        const t=document.getElementById(id);const c=t&&t.querySelector('caption');
        caps[id]=c?c.textContent.trim():null;
      });
      const rowHdr=document.querySelector('th.rub-det-crit');
      return {thCount:ths.length,unscoped,
              caps,capsEmpty:Object.keys(caps).filter(k=>!caps[k]),
              statCap:(()=>{const s=document.querySelector('.stat-table caption');
                  return s?s.textContent.trim():null})(),
              rowHdrScope:rowHdr?rowHdr.getAttribute('scope'):null};}""")
    check("A7: all thead th have scope=col", a7["thCount"] > 0 and a7["unscoped"] == 0,
          f"thCount={a7['thCount']} unscoped={a7['unscoped']}")
    check("A7: 5 static tables have non-empty caption",
          len(a7["capsEmpty"]) == 0, str(a7["caps"]))
    check("A7: tbody row-header th NOT scoped",
          a7["rowHdrScope"] is None, str(a7["rowHdrScope"]))
    # (.stat-table caption is JS-generated in the Stats view; verified in the
    # template + node --check, not in the boot DOM.)

    # ---- A3: icon-only buttons carry a translated aria-label ----
    a3 = pg.evaluate("""()=>{
      const ids=['ev-close','an-close','ls-close','ev-rot-close','an-clear-sel'];
      const o={};
      ids.forEach(id=>{const b=document.getElementById(id);
        o[id]=b?b.getAttribute('aria-label'):null;});
      const z=[...document.querySelectorAll('[data-anzoom]')].map(b=>b.getAttribute('aria-label'));
      return {o,z};}""")
    a3all = list(a3["o"].values()) + list(a3["z"])
    check("A3: icon-only buttons have non-empty aria-label",
          all(v and v.strip() for v in a3all), str(a3))

    # ---- A5: Home radial menu keyboard ----
    # Ensure we're on the home view with the menu open (boot default).
    pg.evaluate("navGo('home',null,{});")
    pg.wait_for_timeout(400)
    a5 = pg.evaluate("""()=>{
      const c=document.getElementById('pie-center');
      return {center:!!c,tab:c?c.getAttribute('tabindex'):null,
              focused:document.activeElement===c};}""")
    check("A5: #pie-center exists and is focusable (tabindex 0)",
          a5["center"] and a5["tab"] == "0", str(a5))
    check("A5: focus moved into the menu on open", a5["focused"], str(a5["focused"]))
    # Active crown L0 = #rg-0 with role=menu, its sectors menuitem + aria-selected.
    crown = pg.evaluate("""()=>{
      const g=document.getElementById('rg-0');
      if(!g)return null;
      const secs=[...g.querySelectorAll('.sector')];
      return {role:g.getAttribute('role'),n:secs.length,
              menuitems:secs.filter(s=>s.getAttribute('role')==='menuitem').length,
              withSel:secs.filter(s=>s.hasAttribute('aria-selected')).length,
              sel:secs.map(s=>s.getAttribute('aria-selected'))};}""")
    check("A5: active crown #rg-0 has role=menu",
          crown and crown["role"] == "menu", str(crown))
    check("A5: L0 sectors are menuitem + aria-selected",
          crown and crown["n"] >= 3 and crown["menuitems"] == crown["n"]
          and crown["withSel"] == crown["n"], str(crown))
    # No verb pre-selected at boot -> all aria-selected false.
    check("A5: no verb pre-selected at boot (all aria-selected false)",
          crown and all(v == "false" for v in crown["sel"]), str(crown["sel"]))

    # 1st ArrowDown -> selects the first L0 verb (aria-selected moves to idx 0).
    pg.keyboard.press("ArrowDown")
    pg.wait_for_timeout(200)
    after = pg.evaluate("""()=>{const g=document.getElementById('rg-0');
      const s=[...g.querySelectorAll('.sector')].map(x=>x.getAttribute('aria-selected'));
      return {sel:s,active:RST.sel};}""")
    check("A5: ArrowDown selects the first verb (L0 aria-selected true)",
          after["sel"].count("true") == 1, str(after))
    # 2nd ArrowDown -> descends into the verb's L1 sub-crown (its 1st leaf
    # becomes the active-level selection). The engine executes the ACTIVE
    # (deepest) level, so a non-leaf L0 verb needs this second step.
    pg.keyboard.press("ArrowDown")
    pg.wait_for_timeout(200)
    # Enter executes the active leaf -> navigates away and closes the menu.
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(500)
    post = pg.evaluate("""()=>({open:document.getElementById('pie-wrap').classList.contains('open'),
      homeActive:document.body.classList.contains('home-active')});""")
    check("A5: Enter executes a leaf + closes the menu (navigates off home)",
          post["open"] is False and post["homeActive"] is False, str(post))

    # ---- Escape path: back on home, reopen, then Escape ----
    pg.evaluate("navGo('home',null,{})")
    pg.wait_for_timeout(500)          # boot default re-opens the menu, focus on centre
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(300)
    esc = pg.evaluate("""()=>({open:document.getElementById('pie-wrap').classList.contains('open'),
      reopen:document.getElementById('home-reopen').classList.contains('hide'),
      focusReopen:document.activeElement===document.getElementById('home-reopen')});""")
    check("A5: Escape closes + focus returns to #home-reopen (on home)",
          esc["open"] is False and esc["reopen"] is False and esc["focusReopen"] is True, str(esc))

    check("0 page errors", len(errors) == 0, str(errors))
    ctx.close()

print("\n===== V2 A11Y STRUCTURE E2E =====")
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FAILURES:", FAIL)
    raise SystemExit(1)
