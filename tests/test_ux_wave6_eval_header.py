#!/usr/bin/env python3
"""V6 verify: eval-mode header actions + portrait gap arrows (2026-11-27 tibo).

Two changes:
1. The bottom-bar "AI report" + "Save" buttons moved UP into the title bar
   (#eval .ev-hdr .ev-hdr-btns) so the landscape mobile layout frees a bottom
   line. The bottom .ev-btns is gone; the footer now holds only the criterion
   chips. Verified in all three viewports (portrait / landscape / desktop).
2. In the NATIVE PORTRAIT layout, the ENTERED level's grid cell (.ev-lvl-btn.on)
   now carries a gap block (.ev-port-gap): a green up row (→ next level + the
   up-gap word = what to ADD to reach the level above) and a red down row (←
   prev level + the down-gap word = what to DROP to fall back a level). Absent
   at the ends of the scale (A1 has no down row, C2 has no up row).

Checks (Playwright, live server on :8090, login tibo/<tests/.credentials>):
PORT 390x844:  header carries .ev-hdr-btns (ai+save), footer has NO .ev-btns,
               entered cell has .ev-port-gap with the right up/down rows.
LAND 844x390:  header carries .ev-hdr-btns on ONE row, footer has NO .ev-btns.
DESK 1280:     header carries .ev-hdr-btns, footer has NO .ev-btns.
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

# Header/footer button placement — identical assertions across all viewports.
def layout_probe(pg):
    return pg.evaluate("""()=>{
        const hdr=document.querySelector('#eval .ev-hdr .ev-hdr-btns');
        const ai=hdr?hdr.querySelector('#ev-btn-ai'):null;
        const save=hdr?hdr.querySelector('#ev-btn-save'):null;
        const oldBtns=document.querySelectorAll('#eval .ev-ftr .ev-btns').length;
        const oldIds=[...document.querySelectorAll('#ev-btn-ai,#ev-btn-save')]
            .map(b=>b.closest('.ev-hdr-btns')? 'hdr':'OTHER');
        const chips=document.querySelectorAll('#eval .ev-ftr .ev-chips .ev-chip').length;
        return {
            hdrBtns:!!hdr, ai:!!ai, save:!!save,
            oldBtnsGone: oldBtns===0,
            ids:oldIds, chips:chips,
            evPort:document.querySelector('#eval').classList.contains('ev-port')};}""")

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

def main():
    with sync_playwright() as p:
        # ---------- PORTRAIT 390x844 (native portrait layout) ----------
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width":390,"height":844},has_touch=True,
                            is_mobile=True,device_scale_factor=3,user_agent=UA)
        pg = ctx.new_page(); errs=[]
        pg.on("pageerror", lambda e: errs.append(str(e)))
        login(pg)
        tgt = find_target(pg)
        check("P0 target analysis found", tgt is not None)
        open_eval(pg, tgt)
        s = layout_probe(pg)
        check("P1 portrait: header carries AI+Save in .ev-hdr-btns",
              s["evPort"] and s["hdrBtns"] and s["ai"] and s["save"], str(s))
        check("P2 portrait: old footer .ev-btns gone, both ids in header",
              s["oldBtnsGone"] and s["ids"]==["hdr","hdr"], str(s))
        check("P3 portrait: footer still has criterion chips", s["chips"]>=1, str(s))
        # gap block on the entered level
        gap = pg.evaluate("""()=>{
            const on=document.querySelector('#ev-cols .ev-lvl-btn.on');
            if(!on)return {on:null};
            const lv=on.dataset.lv, order=['A1','A2','B1','B2','C1','C2'];
            const i=order.indexOf(lv);
            const block=on.querySelector('.ev-port-gap');
            const up=on.querySelector('.pg-row.up');
            const down=on.querySelector('.pg-row.down');
            return {lv, hasGap:!!block,
                upLv: up?up.querySelector('.pg-lv').textContent:null,
                downLv: down?down.querySelector('.pg-lv').textContent:null,
                upTxt: up?up.querySelector('.pg-txt').textContent:null,
                downTxt: down?down.querySelector('.pg-txt').textContent:null,
                expUp: i<5?order[i+1]:null, expDown: i>0?order[i-1]:null};}""")
        # B2 is a typical entered level (mid-scale) → expect BOTH rows
        check("P4 portrait: entered cell has a gap block", gap.get("hasGap"), str(gap))
        check("P5 portrait: up row → correct next level",
              gap.get("upLv")==gap.get("expUp"), str(gap))
        check("P6 portrait: down row → correct prev level",
              gap.get("downLv")==gap.get("expDown"), str(gap))
        # arrows are present and labelled
        arrows = pg.evaluate("""()=>{
            const on=document.querySelector('#ev-cols .ev-lvl-btn.on');
            const up=on.querySelector('.pg-row.up .pg-arr'),
                  down=on.querySelector('.pg-row.down .pg-arr');
            return {up:up?up.textContent:null, down:down?down.textContent:null};}""")
        check("P7 portrait: up arrow green row '→' + down row '←'",
              arrows.get("up")=="→" and arrows.get("down")=="←", str(arrows))
        check("P8 portrait: no JS errors", not errs, str(errs[:3]))
        b.close()

        # ---------- LANDSCAPE 844x390 (3-col) ----------
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width":844,"height":390},has_touch=True,
                            is_mobile=True,device_scale_factor=2,user_agent=UA)
        pg = ctx.new_page(); errs=[]
        pg.on("pageerror", lambda e: errs.append(str(e)))
        login(pg); tgt=find_target(pg)
        open_eval(pg, tgt)
        s = layout_probe(pg)
        check("L1 landscape: header carries AI+Save, no .ev-port",
              (not s["evPort"]) and s["hdrBtns"] and s["ai"] and s["save"], str(s))
        check("L2 landscape: footer .ev-btns gone", s["oldBtnsGone"] and s["chips"]>=1, str(s))
        check("L3 landscape: no JS errors", not errs, str(errs[:3]))
        b.close()

        # ---------- DESKTOP 1280 (6-wide scale) ----------
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width":1280,"height":800})
        pg = ctx.new_page(); errs=[]
        pg.on("pageerror", lambda e: errs.append(str(e)))
        login(pg); tgt=find_target(pg)
        open_eval(pg, tgt)
        s = layout_probe(pg)
        check("D1 desktop: header carries AI+Save, no .ev-port",
              (not s["evPort"]) and s["hdrBtns"] and s["ai"] and s["save"], str(s))
        check("D2 desktop: footer .ev-btns gone", s["oldBtnsGone"] and s["chips"]>=1, str(s))
        check("D3 desktop: no JS errors", not errs, str(errs[:3]))
        b.close()

    print("="*40)
    print(f"=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
    if FAIL:
        print("FAILED:", FAIL)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
