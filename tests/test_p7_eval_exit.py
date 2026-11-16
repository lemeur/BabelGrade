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

Checks (Playwright, live server on :8090, login tibo/****):
PORT 390x844 coarse+touch (iPhone UA):
  P1 rotate hint shown in portrait while eval open
  P2 hint ✕ topmost at its center (elementFromPoint)
  P3 after a pick, hint ✕ still hit-testable
  P4 dirty + hint ✕ → exit bar shown, overlay still open
  P5 discard → overlay + hint closed
  P6 discard restored the pre-open levels
  P7 clean + hint ✕ → closes directly
  P8 back-swipe (dirty) → overlay stays open, exit bar shown, hash unchanged
  P9 no JS errors
LAND 844x390 coarse+touch:
  L1 no rotate hint, header X hit-testable
  L2 dirty + X → exit bar (unchanged desktop behaviour)
  L3 discard closes cleanly
  L4 back-swipe (dirty) → stays open + exit bar, hash unchanged
  L5 no JS errors
DESK 1280:
  D1 no rotate hint, X hit-testable
  D2 dirty + Esc → exit bar (unchanged)
  D3 no JS errors
"""
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
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", "****")
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    pg.wait_for_timeout(400)

def find_target(pg):
    return pg.evaluate("""async()=>{const r=await fetch('/api/analyses');const j=await r.json();
        const rows=Array.isArray(j)?j:(j.items||[]);
        const c=rows.find(x=>(x.rubric_name||'').startsWith('Attestation'));
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

def pick(pg):
    return pg.evaluate("""()=>{const s=document.querySelector('#ev-cols .ev-col[data-pos="right"]')
        ||document.querySelector('#ev-cols .ev-col[data-pos="left"]');
        if(!s)return null; s.click(); return s.dataset.lv;}""")

def st(pg):
    return pg.evaluate("""()=>{
        const b=document.querySelector('#ev-close');const r=b.getBoundingClientRect();
        const el=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
        const rb=document.querySelector('#ev-rot-close').getBoundingClientRect();
        const elb=document.elementFromPoint(rb.x+rb.width/2,rb.y+rb.height/2);
        return {evalHidden:document.querySelector('#eval').hidden,
            rotShow:document.querySelector('#eval-rotate').classList.contains('show'),
            exitBar:document.querySelector('#ev-exitbar').classList.contains('show'),
            xHit:el?(el.id||el.tagName):'none',
            rotXHit:elb?(elb.id||elb.tagName):'none',
            innerW:innerWidth,portrait:innerHeight>innerWidth};}""")

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
        check("P1 portrait: rotate hint shown", s["rotShow"], str(s))
        check("P2 portrait: hint ✕ topmost at its center", s["rotXHit"] == "ev-rot-close", str(s))
        pick(pg); pg.wait_for_timeout(300)
        s = st(pg)
        check("P3 portrait: after pick, hint ✕ still hit", s["rotXHit"] == "ev-rot-close")
        pg.click("#ev-rot-close")
        pg.wait_for_timeout(300)
        s = st(pg)
        check("P4 portrait: dirty + hint ✕ → exit bar, overlay still open",
              s["exitBar"] and not s["evalHidden"], str(s))
        lvls_dirty = pg.evaluate("[...document.querySelectorAll('.att-lvl')].map(s=>s.value)")
        pg.click("#ev-exit-discard")
        pg.wait_for_timeout(400)
        s = st(pg)
        lvls_after = pg.evaluate("[...document.querySelectorAll('.att-lvl')].map(s=>s.value)")
        check("P5 portrait: discard closes overlay + hint", s["evalHidden"] and not s["rotShow"], str(s))
        check("P6 portrait: discard restored levels", lvls_after != lvls_dirty,
              f"{lvls_dirty} vs {lvls_after}")
        open_eval(pg, tgt)
        pg.click("#ev-rot-close")
        pg.wait_for_timeout(300)
        s = st(pg)
        check("P7 portrait: clean + hint ✕ → closes directly",
              s["evalHidden"] and not s["exitBar"], str(s))
        open_eval(pg, tgt)
        pick(pg); pg.wait_for_timeout(300)
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
        check("L1 landscape: no rotate hint, X hit-testable",
              (not s["rotShow"]) and s["xHit"] == "ev-close", str(s))
        pick(pg); pg.wait_for_timeout(300)
        pg.click("#ev-close"); pg.wait_for_timeout(300)
        s = st(pg)
        check("L2 landscape: dirty + X → exit bar (unchanged)",
              s["exitBar"] and not s["evalHidden"], str(s))
        pg.click("#ev-exit-discard"); pg.wait_for_timeout(300)
        s = st(pg)
        check("L3 landscape: discard closes cleanly", s["evalHidden"], str(s))
        open_eval(pg, tgt); pick(pg); pg.wait_for_timeout(300)
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
        check("D1 desktop: no rotate hint, X hit-testable",
              (not s["rotShow"]) and s["xHit"] == "ev-close", str(s))
        pick(pg); pg.wait_for_timeout(300)
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
