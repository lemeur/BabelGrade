#!/usr/bin/env python3
"""Round-4 verify (2026-11-27 tibo): eval-mode portrait always-render + landscape labels + AI badge colour.

1. PORTRAIT BUG: when the synthesized diff is empty (near-identical B1<->B2
   descriptors, e.g. the "Correction de la langue écrite" criterion), the
   gain/loss rows used to VANISH. Now they ALWAYS render: empty diff falls back
   to "exactly the same requirements as L". Verify entering B1 on that criterion
   yields BOTH an up row (reach B2) AND a down row (drop to A2).
2. LANDSCAPE: the side cards now carry ONE directional label each, mirroring the
   portrait: the card to the RIGHT of the entered level = "What it takes to
   reach {Lv}" (gainUp), the card to the LEFT = "What you drop to fall back to
   {Lv}" (gainDown).
3. AI BADGE COLOUR: the landscape .badge-ai is now the solid amber
   (--warn #d97706) + white text like the portrait .pd-ai (was pale cream
   #fef3c7 + amber text).
"""
import sys, json
sys.path.insert(0, "/home/tibo/babelgrade")
sys.path.insert(0, "/home/tibo/babelgrade/tests")
import _testpw as TESTPW
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8090"
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f" | {extra}" if extra and not cond else ""))

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

def login(pg, lang):
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

PORT_PROBE = """(lv)=>{
    window.eval('evPick('+JSON.stringify(lv)+')');
    const gain=document.querySelector('#ev-cols .ev-port-gain');
    const rows=gain?[...gain.querySelectorAll('.pg-row')].map(r=>({
        cls:r.className,
        lv:r.querySelector('.pg-lv')?r.querySelector('.pg-lv').textContent:'',
        lab:r.querySelector('.pg-txt b')?r.querySelector('.pg-txt b').textContent:'',
        body:(r.querySelector('.pg-txt')?r.querySelector('.pg-txt').textContent:'').slice(0,60)})):null;
    return {lv, rows};}"""

def main():
    with sync_playwright() as p:
        # ---------- PORTRAIT 390x844 : the always-render bug ----------
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width":390,"height":844},has_touch=True,
                            is_mobile=True,device_scale_factor=3,user_agent=UA)
        pg = ctx.new_page(); errs=[]
        pg.on("pageerror", lambda e: errs.append(str(e)))
        login(pg, "fr"); tgt=find_target(pg)
        open_eval(pg, tgt)
        # find the "Correction de la langue écrite" criterion index (near-identical B1/B2)
        crit_idx = pg.evaluate("""()=>{
            const names=EVAL.rows.map(r=>r.name);
            return names.findIndex(n=>/Correction de la langue|Accuracy/i.test(n));}""")
        check("P0 target + crit index found", tgt is not None and crit_idx>=0,
              f"tgt={tgt} idx={crit_idx}")
        pg.evaluate(f"evSetCrit({crit_idx})")
        pg.wait_for_timeout(150)
        r1 = pg.evaluate(PORT_PROBE, "B1")
        # The BUG: B1 must now show BOTH an up row (reach B2) AND a down row (drop to A2).
        up = [r for r in r1["rows"] if r["cls"].endswith("up")]
        down = [r for r in r1["rows"] if r["cls"].endswith("down")]
        check("P1 portrait: B1 shows an UP row (reach B2)",
              any(r["lv"]=="B2" for r in up), str(r1["rows"]))
        check("P2 portrait: B1 shows a DOWN row (drop to A2)",
              any(r["lv"]=="A2" for r in down), str(r1["rows"]))
        # B2 on the same criterion: up row (reach C1) + down row (drop to B1) both present.
        r2 = pg.evaluate(PORT_PROBE, "B2")
        up2 = [r for r in r2["rows"] if r["cls"].endswith("up")]
        down2 = [r for r in r2["rows"] if r["cls"].endswith("down")]
        check("P3 portrait: B2 shows BOTH rows (no missing transition)",
              any(r["lv"]=="C1" for r in up2) and any(r["lv"]=="B1" for r in down2),
              str(r2["rows"]))
        # FR labels still carry gainUp/gainDown wording.
        all_fr = [r["lab"] for r in r1["rows"]]+[r["lab"] for r in r2["rows"]]
        check("P4 portrait: FR labels = 'atteindre'/'redescendre'",
              any("atteindre" in l for l in all_fr) and any("redescendre" in l for l in all_fr),
              str(all_fr))
        check("P5 portrait: no JS errors", not errs, str(errs[:3]))
        b.close()

        # ---------- LANDSCAPE 844x390 : directional labels + AI badge colour ----------
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width":844,"height":390},has_touch=True,
                            is_mobile=True,device_scale_factor=2,user_agent=UA)
        pg = ctx.new_page(); errs=[]
        pg.on("pageerror", lambda e: errs.append(str(e)))
        login(pg, "en"); open_eval(pg, find_target(pg))
        land = pg.evaluate("""()=>{
            const cols=[...document.querySelectorAll('#ev-cols .ev-col.side')].map(c=>({
                pos:c.dataset.pos, lv:c.dataset.lv,
                lab:c.querySelector('.ds-lab')?c.querySelector('.ds-lab').textContent.trim():'',
                lines:c.querySelectorAll('.ds-line').length}));
            const ai=document.querySelector('#ev-cols .ev-col .badge-ai');
            const aiStyle=ai?{bg:getComputedStyle(ai).backgroundColor,
                              color:getComputedStyle(ai).color}:null;
            return {cols, aiStyle};}""")
        right = [c for c in land["cols"] if c["pos"]=="right"]
        left  = [c for c in land["cols"] if c["pos"]=="left"]
        check("L1 landscape: right side card label = gainUp ('reach')",
              right and all("reach" in c["lab"].lower() for c in right), str(right))
        check("L2 landscape: left side card label = gainDown ('fall back')",
              left and all("fall back" in c["lab"].lower() for c in left), str(left))
        check("L3 landscape: each side card has exactly one directional line",
              all(c["lines"]==1 for c in land["cols"]), str(land["cols"]))
        # AI badge: solid amber background (rgb(217,119,6) = #d97706) + white text.
        check("L4 landscape: AI badge solid amber + white text (matches portrait)",
              land["aiStyle"] and land["aiStyle"]["bg"]=="rgb(217, 119, 6)"
              and land["aiStyle"]["color"]=="rgb(255, 255, 255)", str(land["aiStyle"]))
        check("L5 landscape: no JS errors", not errs, str(errs[:3]))
        b.close()

    print("="*40)
    print(f"=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
    if FAIL:
        print("FAILED:", FAIL)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
