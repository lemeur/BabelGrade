#!/usr/bin/env python3
"""V6 verify: eval-mode round-2 UX (2026-11-27 tibo).

Three changes on top of the round-1 (buttons in header):
1. PORTRAIT: the entered level's descriptor card is kept COMPACT (capped
   height, scrollable inside, .ev-port-desc) and a SECOND card below it
   (.ev-port-gain) shows the gain/loss arrows: green → up-row (what this level
   GAINS to reach the level above) + red ← down-row (what it DROPS to fall back
   a level). The gap is NO LONGER inside the grid cell.
2. LANDSCAPE/desktop: the level pill was removed from the header and replaced
   by an inline swipe/keyboard hint (#ev-hint-inline); the two bottom hint lines
   (#ev-hint-swipe / #ev-hint-kbd) are gone entirely.
3. ALL modes: the AI-report button (#ev-btn-ai) is greyed + disabled when the
   analysis has no prior AI run (EVAL.hasAi false), with a "no AI analysis yet"
   tooltip. Simulated live by toggling EVAL.hasAi + evRender().

Checks (Playwright, live server on :8090, login tibo/<tests/.credentials>):
PORT 390x844, LAND 844x390, DESK 1280 — layout + AI-button grey.
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

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

def layout_probe(pg):
    return pg.evaluate("""()=>({
        hdrBtns:!!document.querySelector('#eval .ev-hdr .ev-hdr-btns'),
        ai:!!document.querySelector('#ev-btn-ai'),
        save:!!document.querySelector('#ev-btn-save'),
        oldFooterBtns:document.querySelectorAll('#eval .ev-ftr .ev-btns').length,
        pill:!!document.querySelector('#ev-pill-lvl'),
        hintInline:!!document.querySelector('#ev-hint-inline'),
        hintInlineTxt:document.querySelector('#ev-hint-inline')?document.querySelector('#ev-hint-inline').textContent:'',
        bottomHints:document.querySelectorAll('#eval .ev-hint').length,
        evPort:document.querySelector('#eval').classList.contains('ev-port')})""")

def ai_btn_state(pg):
    return pg.evaluate("""()=>{const b=document.querySelector('#ev-btn-ai');
        return b?{disabled:b.disabled, title:b.title, txt:b.textContent}:null;}""")

def set_hasai_and_render(pg, val):
    """Toggle EVAL.hasAi and re-render to exercise the greyed-button path live.
    EVAL is a top-level `let` (resolvable as a global in page-eval scope)."""
    return pg.evaluate("""(v)=>{if(!EVAL)return 'noEVAL';
        EVAL.hasAi=v; evRender();
        const b=document.querySelector('#ev-btn-ai');
        return b?{disabled:b.disabled, title:b.title, txt:b.textContent}:null;}""", val)

def main():
    with sync_playwright() as p:
        # ---------- PORTRAIT 390x844 ----------
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width":390,"height":844},has_touch=True,
                            is_mobile=True,device_scale_factor=3,user_agent=UA)
        pg = ctx.new_page(); errs=[]
        pg.on("pageerror", lambda e: errs.append(str(e)))
        login(pg); tgt=find_target(pg)
        check("P0 target found", tgt is not None)
        open_eval(pg, tgt)
        s = layout_probe(pg)
        check("P1 portrait: header AI+Save, no pill, inline hint, no bottom hints",
              s["evPort"] and s["hdrBtns"] and s["ai"] and s["save"]
              and not s["pill"] and s["hintInline"] and s["bottomHints"]==0, str(s))
        check("P2 portrait: swipe hint text in header (touch)", "glissez" in s["hintInlineTxt"], str(s["hintInlineTxt"]))
        # portrait compact desc + gain card
        pc = pg.evaluate("""()=>{
            const on=document.querySelector('#ev-cols .ev-lvl-btn.on');
            const lv=on?on.dataset.lv:null, order=['A1','A2','B1','B2','C1','C2'];
            const i=lv?order.indexOf(lv):-1;
            const inCell=on?on.querySelector('.ev-port-gap'):null;   // round-1 location (must be GONE)
            const gain=document.querySelector('#ev-cols .ev-port-gain');
            const desc=document.querySelector('#ev-cols .ev-port-desc');
            const up=gain?gain.querySelector('.pg-row.up'):null,
                  down=gain?gain.querySelector('.pg-row.down'):null;
            return {lv, inCellGone: inCell===null,
                gainCard:!!gain, desc:!!desc,
                upLv: up?up.querySelector('.pg-lv').textContent:null,
                downLv: down?down.querySelector('.pg-lv').textContent:null,
                upTxt: up?up.querySelector('.pg-txt').textContent:null,
                downTxt: down?down.querySelector('.pg-txt').textContent:null,
                expUp: i>=0&&i<5?order[i+1]:null, expDown: i>0?order[i-1]:null};}""")
        check("P3 portrait: gap no longer in grid cell (moved out)", pc["inCellGone"], str(pc))
        check("P4 portrait: dedicated gain card below compact descriptor", pc["gainCard"] and pc["desc"], str(pc))
        check("P5 portrait: up row = next level", pc["upLv"]==pc["expUp"], str(pc))
        check("P6 portrait: down row = prev level", pc["downLv"]==pc["expDown"], str(pc))
        # rows are only expected where a neighbour exists (scale ends have none).
        up_ok = (pc["expUp"] is None) or ("atteindre" in pc["upTxt"])
        down_ok = (pc["expDown"] is None) or ("redescendre" in pc["downTxt"])
        present = pc["upLv"] is not None or pc["downLv"] is not None
        check("P7 portrait: gain rows carry the right FR label (gainUp/gainDown)",
              up_ok and down_ok and present, str(pc))
        check("P8 portrait: no JS errors", not errs, str(errs[:3]))
        b.close()

        # ---------- LANDSCAPE 844x390 ----------
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width":844,"height":390},has_touch=True,
                            is_mobile=True,device_scale_factor=2,user_agent=UA)
        pg = ctx.new_page(); errs=[]
        pg.on("pageerror", lambda e: errs.append(str(e)))
        login(pg); tgt=find_target(pg)
        open_eval(pg, tgt)
        s = layout_probe(pg)
        check("L1 landscape: header AI+Save, no pill, inline hint, no bottom hints",
              (not s["evPort"]) and s["hdrBtns"] and s["ai"] and s["save"]
              and not s["pill"] and s["hintInline"] and s["bottomHints"]==0, str(s))
        check("L2 landscape: swipe hint text in header (touch)", "glissez" in s["hintInlineTxt"], str(s["hintInlineTxt"]))
        check("L3 landscape: footer .ev-btns gone", s["oldFooterBtns"]==0, str(s))
        check("L4 landscape: no JS errors", not errs, str(errs[:3]))
        b.close()

        # ---------- DESKTOP 1280 (AI-button grey simulation) ----------
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width":1280,"height":800})
        pg = ctx.new_page(); errs=[]
        pg.on("pageerror", lambda e: errs.append(str(e)))
        login(pg); tgt=find_target(pg)
        open_eval(pg, tgt)
        s = layout_probe(pg)
        check("D1 desktop: header AI+Save, no pill, inline hint, no bottom hints",
              (not s["evPort"]) and s["hdrBtns"] and s["ai"] and s["save"]
              and not s["pill"] and s["hintInline"] and s["bottomHints"]==0, str(s))
        check("D2 desktop: keyboard hint text in header (fine pointer)",
              "1-4" in s["hintInlineTxt"] or "Échap" in s["hintInlineTxt"], str(s["hintInlineTxt"]))
        st = ai_btn_state(pg)
        # simulate "no prior AI analysis" → button greys
        st0 = set_hasai_and_render(pg, False)
        check("D3 desktop: no prior AI → button disabled + tooltip",
              st0 and st0["disabled"] and "IA" in st0["title"] and "analyse" in st0["title"].lower(), str(st0))
        # simulate "AI analysis exists" → button enabled again
        st1 = set_hasai_and_render(pg, True)
        check("D4 desktop: prior AI present → button enabled, no tooltip",
              st1 and not st1["disabled"] and st1["title"]=="", str(st1))
        check("D5 desktop: no JS errors", not errs, str(errs[:3]))
        b.close()

    print("="*40)
    print(f"=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
    if FAIL:
        print("FAILED:", FAIL)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
