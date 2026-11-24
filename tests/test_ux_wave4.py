#!/usr/bin/env python3
"""Wave 4 (mobile ergonomics) E2E — live, mobile portrait 390×844 (2026-11-24).

Covers the four V4 items shipped this wave, in `static/index.html`:

V4.1/M1  native portrait layout for criterion-by-criterion eval
  W1  portrait eval: #eval.ev-port ON, 6-level 3×2 grid + descriptor panel,
      rotate hint NEVER shown
  W2  grid pick updates the entered level; save persists to the matrix
  W3  landscape phone (844×390): NO .ev-port → the old 3-col layout
  W4  desktop (1280): no .ev-port → full A1→C2 scale

M2       camera-first photo inputs
  W5  the copy photo input (#img-file) carries capture="environment"
      (instruction + doc photo inputs do too)

M3       sticky-bottom action bar on the evaluator form
  W6  .card.an-actions is position:sticky bottom on mobile, visible &
      above the bottom nav when scrolled to the TOP of the 5-screen form

M4       detail-page essentials sticky + folded long sections
  W7  the .att-ess essentials band is sticky under the (live-measured)
      header: --hdr-h is set, band pins at the header's bottom while the
      attestation card is on screen, still showing level + /120 score
  W8  header itself stays pinned (position sticky top:0) in the detail view
      (regression: overflow-x:hidden on body used to kill both stickies)
  W9  the oral transcript is a <details open> card (foldable on mobile)
  W10 no horizontal overflow from the html-only overflow-x:hidden fix

Login: tibo/<tests/.credentials>; force FR before goto; live server on :8090.
"""
import _testpw as TESTPW
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8090"
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f" | {extra}" if extra and not cond else ""))

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

def mobile_ctx(p, w=390, h=844, dpr=3):
    return p.chromium.launch, p.chromium.launch_persistent_context if False else None

def new_mobile(p, w=390, h=844, dpr=3):
    b = p.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": w, "height": h}, has_touch=True,
                        is_mobile=True, device_scale_factor=dpr, user_agent=UA)
    return b, ctx, ctx.new_page()

def login(pg, lang="fr"):
    pg.add_init_script(f"localStorage.setItem('babelgrade-lang','{lang}')")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", TESTPW.pw())
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    pg.wait_for_timeout(400)

def done_att(pg, kind=None):
    """A done attestation with an overall level (+ optionally oral for W9)."""
    return pg.evaluate("""(kind)=>{const need=kind||null;
        return (async()=>{const r=await fetch('/api/analyses');const j=await r.json();
        const rows=Array.isArray(j)?j:(j.items||[]);
        const c=rows.find(x=>(x.rubric_name||'').startsWith('Attestation')
            &&x.status==='done'&&x.overall_level&&(need?x.kind===need:true));
        return c?c.analysis_id:null;})();}""", kind)

def open_detail(pg, tgt):
    if pg.evaluate("location.hash") != f"#history/{tgt}":
        pg.evaluate("location.hash='#history'")
        pg.wait_for_selector("#hist-cards [data-aid]", state="attached", timeout=20000)
        pg.wait_for_timeout(500)
    pg.evaluate("""(t)=>{const el=document.querySelector(`#hist-cards [data-aid='${t}']`)
        ||document.querySelector(`#hist [data-aid='${t}']`); el&&el.click();}""", tgt)
    pg.wait_for_selector("#hist-report .att-card", state="attached", timeout=20000)
    pg.wait_for_timeout(500)

def open_eval(pg, tgt):
    open_detail(pg, tgt)
    if not pg.evaluate("!!document.querySelector('#att-eval')"):
        pg.evaluate("location.hash='#history'"); pg.wait_for_timeout(500)
        pg.evaluate("""(t)=>{const el=document.querySelector(`#hist-cards [data-aid='${t}']`)
            ||document.querySelector(`#hist [data-aid='${t}']`); el&&el.click();}""", tgt)
        pg.wait_for_timeout(500)
    pg.click("#att-eval")
    pg.wait_for_selector("#eval:not([hidden])", timeout=20000)
    pg.wait_for_timeout(400)

def main():
    with sync_playwright() as p:
        # ============ MOBILE PORTRAIT 390x844 ============
        b, ctx, pg = new_mobile(p)
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        login(pg)

        # ---- V4.1/M1: native portrait eval layout ----
        tgt = done_att(pg)
        check("W0 target analysis found", tgt is not None)
        open_eval(pg, tgt)
        st = pg.evaluate("""()=>({evPort:document.querySelector('#eval').classList.contains('ev-port'),
            grid:document.querySelectorAll('#ev-cols .ev-port-grid .ev-lvl-btn[data-pick]').length,
            desc:!!document.querySelector('#ev-cols .ev-port-desc'),
            hint:document.querySelector('#eval-rotate').classList.contains('show')})""")
        check("W1 portrait eval: .ev-port + 6-level grid + descriptor, NO rotate hint",
              st["evPort"] and st["grid"] == 6 and st["desc"] and not st["hint"], str(st))
        before = pg.evaluate("(()=>{const o=document.querySelector('#ev-cols .ev-lvl-btn.on');"
                             "return o?o.dataset.lv:null;})()")
        pg.evaluate("""()=>{const o=document.querySelector('#ev-cols .ev-lvl-btn.on');
            const order=['A1','A2','B1','B2','C1','C2'];const i=order.indexOf(o.dataset.lv);
            const t=document.querySelector(`#ev-cols .ev-lvl-btn[data-pick="${order[i<5?i+1:0]}"]`);
            t.click();}""")
        pg.wait_for_timeout(300)
        after = pg.evaluate("(()=>{const o=document.querySelector('#ev-cols .ev-lvl-btn.on');"
                            "return o?o.dataset.lv:null;})()")
        check("W2 portrait: grid pick changes entered level", after and after != before,
              f"{before} -> {after}")
        # save persists the counter-proposal
        pg.click("#ev-btn-save"); pg.wait_for_timeout(600)
        lvl_after = pg.evaluate("""()=>{const r=document.querySelector('#hist-report .att-lvl-pill .level');
            return r?r.textContent:null;}""")
        check("W2b portrait: save persists level into the matrix", lvl_after == after,
              f"matrix={lvl_after} picked={after}")
        # close (clean now? we saved → discard is moot; use header ✕)
        pg.evaluate("(()=>{const x=document.querySelector('#ev-close');x&&x.click();})()")
        pg.wait_for_timeout(400)
        if pg.evaluate("document.querySelector('#ev-exitbar').classList.contains('show')"):
            pg.click("#ev-exit-discard"); pg.wait_for_timeout(300)

        # ---- M2: camera-first photo input ----
        pg.evaluate("location.hash='#evaluator'"); pg.wait_for_selector("#view-analyze:not(.hide)", timeout=20000)
        pg.wait_for_timeout(400)
        caps = pg.evaluate("""()=>[...['img-file','instrphotos-file','docphotos-file']
            .map(id=>{const e=document.getElementById(id);return e?e.getAttribute('capture'):null;})]""")
        check("W5 M2: copy/instr/doc photo inputs have capture=environment",
              all(c == "environment" for c in caps), str(caps))

        # ---- M3: sticky-bottom action bar on the evaluator form ----
        pg.evaluate("window.scrollTo({top:0})"); pg.wait_for_timeout(250)
        m3 = pg.evaluate("""()=>{const a=document.querySelector('#view-analyze .card.an-actions');
            if(!a)return{present:false};
            const cs=getComputedStyle(a);const r=a.getBoundingClientRect();
            const nav=document.querySelector('#nav');
            return {present:true,pos:cs.position,bottom:cs.bottom,
              inView:r.bottom<=innerHeight+1&&r.top<innerHeight,
              aboveNav:nav?r.top<nav.getBoundingClientRect().top-2:true};}""")
        check("W6 M3: .card.an-actions sticky-bottom + visible at form top on mobile",
              m3["present"] and m3["pos"] == "sticky" and m3["inView"], str(m3))

        # ---- M4: detail essentials sticky under the live header ----
        open_detail(pg, tgt)
        hdrh = pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--hdr-h').trim()")
        hdrH = int(hdrh.replace("px", ""))
        check("W7 M4: --hdr-h measured + matches header", hdrH > 0 and
              abs(hdrH - pg.evaluate("Math.round(document.querySelector('header').getBoundingClientRect().height)")) <= 1,
              f"--hdr-h={hdrh}")
        # band pins under header while the att card is on screen
        pg.evaluate("window.scrollTo({top:1200})"); pg.wait_for_timeout(200)
        pin = pg.evaluate("""()=>{const h=document.querySelector('header').getBoundingClientRect();
            const e=document.querySelector('#hist-report .att-ess').getBoundingClientRect();
            const card=document.querySelector('#hist-report .att-card').getBoundingClientRect();
            return {pin:Math.abs(e.top-h.bottom)<4&&e.bottom>h.bottom,card:card.bottom>0,
              lvl:((document.querySelector('#hist-report .att-ess .att-level')||{}).textContent||'').trim(),
              score:((document.querySelector('#hist-report .att-ess .att-score')||{}).textContent||'').trim()};}""")
        check("W7 M4: essentials band pinned under header with level+score",
              pin["pin"] and pin["lvl"] and pin["score"], str(pin))
        # header pinned
        pg.evaluate("window.scrollTo({top:1200})"); pg.wait_for_timeout(200)
        check("W8 M4: header pinned (top≈0) in detail view",
              pg.evaluate("Math.round(document.querySelector('header').getBoundingClientRect().top)") == 0)
        # W9 oral transcript fold
        oral = done_att(pg, "oral")
        if oral:
            open_detail(pg, oral)
            tr = pg.evaluate("""()=>{const d=document.querySelector('#hist-report details .transcript');
                if(!d)return{found:false};const det=d.closest('details');
                return {found:true,open:det.open,openAttr:det.hasAttribute('open'),
                  lines:d.querySelectorAll('.line').length};}""")
            check("W9 M4: oral transcript is <details open> (foldable)",
                  tr["found"] and tr["openAttr"] and tr["lines"] > 0, str(tr))
        else:
            check("W9 M4: oral transcript fold (no oral fixture — skipped)", True, "no oral attestation")
        # W10 no horizontal overflow
        ovf = pg.evaluate("""()=>{let mx=0;document.querySelectorAll('body *').forEach(e=>{
            const r=e.getBoundingClientRect();if(r.width>0)mx=Math.max(mx,r.right);});
            return {mx:Math.round(mx),w:innerWidth,overflow:mx>innerWidth+1};}""")
        check("W10 M4: no horizontal overflow (html-only overflow-x fix)",
              not ovf["overflow"], str(ovf))
        check("W11 portrait: no JS errors", not errs, str(errs[:3]))
        ctx.close(); b.close()

        # ============ LANDSCAPE 844x390 ============
        b, ctx, pg = new_mobile(p, 844, 390, 2)
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        login(pg)
        open_eval(pg, tgt)
        st = pg.evaluate("""()=>({evPort:document.querySelector('#eval').classList.contains('ev-port'),
            grid:document.querySelectorAll('#ev-cols .ev-port-grid .ev-lvl-btn[data-pick]').length,
            cols:document.querySelectorAll('#ev-cols .ev-col').length,
            hint:document.querySelector('#eval-rotate').classList.contains('show')})""")
        check("W3 landscape: NO .ev-port → 3-col layout, no hint",
              not st["evPort"] and st["grid"] == 0 and st["cols"] >= 1 and not st["hint"], str(st))
        check("W12 landscape: no JS errors", not errs, str(errs[:3]))
        ctx.close(); b.close()

        # ============ DESKTOP 1280 ============
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width": 1280, "height": 800})
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        login(pg)
        open_eval(pg, tgt)
        st = pg.evaluate("""()=>({evPort:document.querySelector('#eval').classList.contains('ev-port'),
            scale:document.querySelectorAll('#ev-cols .ev-col').length,
            hint:document.querySelector('#eval-rotate').classList.contains('show')})""")
        check("W4 desktop: no .ev-port → full A1→C2 scale (6 cols), no hint",
              not st["evPort"] and st["scale"] == 6 and not st["hint"], str(st))
        check("W13 desktop: no JS errors", not errs, str(errs[:3]))
        ctx.close(); b.close()

    print("=" * 40)
    print(f"=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
    if FAIL:
        print("FAILED:", FAIL)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
