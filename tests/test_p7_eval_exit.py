#!/usr/bin/env python3
"""P7 verify: eval-mode exit on phones (2026-10-15 tibo bug).

Root causes fixed here:
- the portrait rotate hint (#eval-rotate, z-index 90) covered #eval (z-80)
  and intercepted the header ✕ — on a phone the X looked dead / "went back".
  The hint now carries its own ✕ (#ev-rot-close) wired to evRequestExit().
- the hint now hides while the exit bar is up (z-order), and evExitBar()
  refreshes it on toggle.
- a browser back-swipe (popstate) while the overlay is open no longer
  navigates the app underneath: clean session → overlay closes (it was the
  top step); dirty session → exit bar shown.

V4.1 (2026-11-24) change: on a coarse-pointer device held in PORTRAIT the
eval mode now renders the NATIVE PORTRAIT layout instead of the forced
landscape — the rotate hint no longer shows (evPort() true → suppressed),
the 6 levels are a 3×2 grid of big tappable buttons (#ev-cols
.ev-port-grid .ev-lvl-btn[data-pick]) and the entered level's descriptor
sits in the panel below (.ev-port-desc). P1–P4 were therefore rewritten:
portrait now asserts hint-off + native grid + grid-pick works. Landscape
(844×390, <900px wide) keeps the 3-col layout and never showed the hint;
desktop (≥900px) keeps the full A1→C2 scale. Exit-bar/discard/back-swipe
semantics are unchanged everywhere.

Checks (Playwright, live server on :8090, login tibo/<tests/.credentials>):
PORT 390x844 coarse+touch (iPhone UA):
  P1 rotate hint NOT shown + native portrait layout on (.ev-port, grid, desc)
  P2 grid has 6 level buttons, entered level marked .on, descriptor shown
  P3 grid pick (data-pick click) updates entered level + descriptor
  P4 dirty + header ✕ → exit bar shown, overlay still open
  P5 discard → overlay closed
  P6 discard restored the pre-open levels
  P7 clean + header ✕ → closes directly
  P8 back-swipe (dirty) → overlay stays open, exit bar shown, hash unchanged
  P9 no JS errors
LAND 844x390 coarse+touch:
  L1 no rotate hint, no .ev-port (3-col layout), header X hit-testable
  L2 dirty + X → exit bar (unchanged desktop behaviour)
  L3 discard closes cleanly
  L4 back-swipe (dirty) → stays open + exit bar, hash unchanged
  L5 no JS errors
DESK 1280:
  D1 no rotate hint, no .ev-port, X hit-testable
  D2 dirty + Esc → exit bar (unchanged)
  D3 no JS errors
"""
import _testpw as TESTPW
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8090"
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f" | {extra}" if extra and not cond else ""))

def login(pg, lang="fr"):
    pg.add_init_script(f"localStorage.setItem('babelgrade-lang','{lang}')")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", TESTPW.pw())
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    pg.wait_for_timeout(400)

def find_target(pg):
    """A DONE attestation analysis WITH an overall level — the report renders
       its .att-card (the eval button) only for such rows. The raw list is
       newest-first, so an in-flight 'queued' attestation (no level yet) can
       sit at the top and has no .att-card → the old 'startsWith only' find
       picked it and open_eval() timed out on the missing card. """
    return pg.evaluate("""async()=>{const r=await fetch('/api/analyses');const j=await r.json();
        const rows=Array.isArray(j)?j:(j.items||[]);
        const c=rows.find(x=>(x.rubric_name||'').startsWith('Attestation')
            &&x.status==='done'&&x.overall_level);
        return c?c.analysis_id:null;}""")

def open_eval(pg, tgt):
    if pg.evaluate("location.hash") != f"#history/{tgt}":
        pg.evaluate("location.hash='#history'")
        pg.wait_for_selector("#hist-body [data-aid]", state="attached", timeout=20000)
        pg.wait_for_timeout(600)
    if not pg.evaluate("!!document.querySelector('#hist-report .att-card')"):
        pg.evaluate("""(t)=>{const el=document.querySelector(`#hist-cards [data-aid='${t}']`)
            ||document.querySelector(`#hist [data-aid='${t}']`); el&&el.click();}""", tgt)
        pg.wait_for_timeout(400)
    pg.wait_for_selector(".att-card", timeout=20000)
    pg.wait_for_timeout(300)
    pg.click("#att-eval")
    pg.wait_for_timeout(500)

def st(pg):
    return pg.evaluate("""()=>{
        const b=document.querySelector('#ev-close');const r=b.getBoundingClientRect();
        const el=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
        return {evalHidden:document.querySelector('#eval').hidden,
            rotShow:document.querySelector('#eval-rotate').classList.contains('show'),
            exitBar:document.querySelector('#ev-exitbar').classList.contains('show'),
            evPort:document.querySelector('#eval').classList.contains('ev-port'),
            grid:!!document.querySelector('#ev-cols .ev-port-grid'),
            gridBtns:document.querySelectorAll('#ev-cols .ev-port-grid .ev-lvl-btn[data-pick]').length,
            desc:!!document.querySelector('#ev-cols .ev-port-desc'),
            xHit:el?(el.id||el.tagName):'none',
            innerW:innerWidth,portrait:innerHeight>innerWidth};}""")

def entered_level(pg):
    """The level currently entered in eval mode, via the .on marker which both
       the 3-col/wide layout (.ev-col.center) and the native-portrait grid
       (.ev-lvl-btn.on) use. """
    return pg.evaluate("""()=>{
        const c=document.querySelector('#ev-cols .ev-col.center, #ev-cols .ev-lvl-btn.on');
        return c?c.dataset.lv:null;}""")

def pick(pg, mode="port"):
    """Pick a NEIGHBOUR of the entered level: native-portrait grid → the
       B1-or-A2 button next to the entered one (data-pick); 3-col/wide →
       the left/right .ev-col. Returns the level that was picked. """
    return pg.evaluate("""(mode)=>{
        if(mode==='port'){
            const on=document.querySelector('#ev-cols .ev-lvl-btn.on');
            const lv=on?on.dataset.lv:null;
            const order=['A1','A2','B1','B2','C1','C2'];
            const i=lv?order.indexOf(lv):-1;
            const target=(i<5?order[i+1]:order[0]);
            const btn=document.querySelector(`#ev-cols .ev-lvl-btn[data-pick="${target}"]`);
            if(!btn)return null; btn.click(); return target;}
        const s=document.querySelector('#ev-cols .ev-col[data-pos="right"]')
            ||document.querySelector('#ev-cols .ev-col[data-pos="left"]');
        if(!s)return null; s.click(); return s.dataset.lv;}""", mode)

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

def main():
    with sync_playwright() as p:
        # ---------------- PORTRAIT 390x844 ----------------
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True,
                            is_mobile=True, device_scale_factor=3, user_agent=UA)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        login(pg)
        tgt = find_target(pg)
        check("P0 target analysis found", tgt is not None)
        open_eval(pg, tgt)
        s = st(pg)
        check("P1 portrait: rotate hint NOT shown + native layout on",
              s["portrait"] and not s["rotShow"] and s["evPort"] and s["grid"], str(s))
        check("P2 portrait: grid = 6 level buttons + descriptor panel",
              s["gridBtns"] == 6 and s["desc"], str(s))
        before = entered_level(pg)
        picked = pick(pg, "port"); pg.wait_for_timeout(300)
        after = entered_level(pg)
        check("P3 portrait: grid pick updates entered level",
              picked is not None and after == picked and after != before,
              f"before={before} picked={picked} after={after}")
        pg.click("#ev-close"); pg.wait_for_timeout(300)
        s = st(pg)
        check("P4 portrait: dirty + header ✕ → exit bar, overlay still open",
              s["exitBar"] and not s["evalHidden"], str(s))
        lvls_dirty = pg.evaluate("[...document.querySelectorAll('.att-lvl')].map(s=>s.value)")
        pg.click("#ev-exit-discard")
        pg.wait_for_timeout(400)
        s = st(pg)
        lvls_after = pg.evaluate("[...document.querySelectorAll('.att-lvl')].map(s=>s.value)")
        check("P5 portrait: discard closes overlay + hint off", s["evalHidden"] and not s["rotShow"], str(s))
        check("P6 portrait: discard restored levels", lvls_after != lvls_dirty,
              f"{lvls_dirty} vs {lvls_after}")
        open_eval(pg, tgt)
        pg.click("#ev-close"); pg.wait_for_timeout(300)
        s = st(pg)
        check("P7 portrait: clean + header ✕ → closes directly",
              s["evalHidden"] and not s["exitBar"], str(s))
        open_eval(pg, tgt)
        pick(pg, "port"); pg.wait_for_timeout(300)
        pg.go_back(); pg.wait_for_timeout(600)
        s = st(pg)
        check("P8 portrait: back-swipe (dirty) → stays open + exit bar + hash unchanged",
              not s["evalHidden"] and s["exitBar"]
              and pg.evaluate("location.hash") == f"#history/{tgt}", str(s))
        pg.click("#ev-exit-discard"); pg.wait_for_timeout(300)
        check("P9 portrait: no JS errors", not errs, str(errs[:3]))
        b.close()

        # ---------------- LANDSCAPE 844x390 ----------------
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 844, "height": 390}, has_touch=True,
                            is_mobile=True, device_scale_factor=2, user_agent=UA)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        login(pg)
        tgt = find_target(pg)
        open_eval(pg, tgt)
        s = st(pg)
        check("L1 landscape: no rotate hint, no native layout (3-col), X hit-testable",
              (not s["rotShow"]) and not s["evPort"] and not s["grid"] and s["xHit"] == "ev-close", str(s))
        pick(pg, "cols"); pg.wait_for_timeout(300)
        pg.click("#ev-close"); pg.wait_for_timeout(300)
        s = st(pg)
        check("L2 landscape: dirty + X → exit bar (unchanged)",
              s["exitBar"] and not s["evalHidden"], str(s))
        pg.click("#ev-exit-discard"); pg.wait_for_timeout(300)
        s = st(pg)
        check("L3 landscape: discard closes cleanly", s["evalHidden"], str(s))
        open_eval(pg, tgt); pick(pg, "cols"); pg.wait_for_timeout(300)
        pg.go_back(); pg.wait_for_timeout(600)
        s = st(pg)
        check("L4 landscape: back-swipe (dirty) → stays open + exit bar + hash unchanged",
              not s["evalHidden"] and s["exitBar"]
              and pg.evaluate("location.hash") == f"#history/{tgt}", str(s))
        pg.click("#ev-exit-discard"); pg.wait_for_timeout(300)
        check("L5 landscape: no JS errors", not errs, str(errs[:3]))
        b.close()

        # ---------------- DESKTOP 1280 ----------------
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 800})
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        login(pg)
        tgt = find_target(pg)
        open_eval(pg, tgt)
        s = st(pg)
        check("D1 desktop: no rotate hint, no native layout, X hit-testable",
              (not s["rotShow"]) and not s["evPort"] and s["xHit"] == "ev-close", str(s))
        pick(pg, "cols"); pg.wait_for_timeout(300)
        pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
        s = st(pg)
        check("D2 desktop: dirty + Esc → exit bar (unchanged)",
              s["exitBar"] and not s["evalHidden"], str(s))
        pg.click("#ev-exit-discard"); pg.wait_for_timeout(300)
        check("D3 desktop: no JS errors", not errs, str(errs[:3]))
        b.close()

    print("=" * 40)
    print(f"=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
    if FAIL:
        print("FAILED:", FAIL)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
