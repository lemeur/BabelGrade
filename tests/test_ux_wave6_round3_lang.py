#!/usr/bin/env python3
"""Round-3 verify (2026-11-27 tibo): landscape FR/EN mix fix + portrait full phrases.

1. LANDSCAPE (844x390, EN): the side-card adds/lacks synthesis must be like-with-
   like — centre AND side translated. No canonical-French clause may appear in an
   EN card (the reported bug: '+' lines EN, '-' lines FR).
2. PORTRAIT (390x844, EN): the gain/loss card rows carry the FULL translated
   diff phrases (not the short gap words); labels remain gainUp/settleFor.
"""
import _testpw as TESTPW
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8090"
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f" | {extra}" if extra and not cond else ""))

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

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

def side_card_probe(pg):
    """EN side-card text: the entered (centre) level's neighbours in landscape."""
    return pg.evaluate("""()=>{
        const cols=[...document.querySelectorAll('#ev-cols .ev-col.side .ds-txt')];
        const centre=document.querySelector('#ev-cols .ev-col.center .desc');
        const on=document.querySelector('#ev-cols .ev-lvl-btn.on, #ev-cols .ev-col.center .lv');
        return {sideTxts:cols, centre:centre?centre.textContent:'', lv:on?on.textContent.trim():null};}""")

def main():
    with sync_playwright() as p:
        # ---------- LANDSCAPE EN: no French in side-card synthesis ----------
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width":844,"height":390},has_touch=True,
                            is_mobile=True,device_scale_factor=2,user_agent=UA)
        pg = ctx.new_page(); errs=[]
        pg.on("pageerror", lambda e: errs.append(str(e)))
        login(pg, "en"); tgt=find_target(pg)
        check("L0 target found", tgt is not None)
        open_eval(pg, tgt)
        s = side_card_probe(pg)
        # canonical-French tell-tale phrases that must NOT appear in EN cards
        fr_tells = ["comprend","produit","traite","construit","s'appuie","exploite",
                    "formule","organise","propose","détaille","réalise","établit",
                    "dégage","met en","permet","accorde","maîtrise","reconnaît"]
        joined = " ".join(s["sideTxts"]).lower()
        bad = [w for w in fr_tells if w in joined]
        check("L1 EN landscape: side-card adds/lacks have no canonical-French clause",
              not bad and len(s["sideTxts"])>0, f"lv={s['lv']} bad={bad} txts={s['sideTxts'][:2]}")
        check("L2 EN landscape: no JS errors", not errs, str(errs[:3]))
        b.close()

        # ---------- PORTRAIT EN: full translated phrases in the gain card ----------
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width":390,"height":844},has_touch=True,
                            is_mobile=True,device_scale_factor=3,user_agent=UA)
        pg = ctx.new_page(); errs=[]
        pg.on("pageerror", lambda e: errs.append(str(e)))
        login(pg, "en"); tgt=find_target(pg)
        open_eval(pg, tgt)
        pr = pg.evaluate("""()=>{
            const gain=document.querySelector('#ev-cols .ev-port-gain');
            const on=document.querySelector('#ev-cols .ev-lvl-btn.on');
            const rows=gain?[...gain.querySelectorAll('.pg-row')].map(r=>({
                cls:r.className, lv:r.querySelector('.pg-lv')?r.querySelector('.pg-lv').textContent:'',
                txt:r.querySelector('.pg-txt')?r.querySelector('.pg-txt').textContent:''})):[];
            return {lv:on?on.dataset.lv:null, rows};}""")
        fr_tells = ["comprend","produit","traite","construit","s'appuie","exploite",
                    "formule","organise","propose","détaille","réalise","établit",
                    "dégage","met en","permet","accorde","maîtrise","reconnaît",
                    "ateliers","s'appuie"]
        joined = " ".join(r["txt"] for r in pr["rows"]).lower()
        bad = [w for w in fr_tells if w in joined]
        check("P1 EN portrait: gain card rows present", len(pr["rows"])>0, str(pr))
        check("P2 EN portrait: gain rows are FULL phrases (longer than a 3-word gap)",
              all(len(r["txt"].split())>=5 for r in pr["rows"]), str(pr["rows"]))
        check("P3 EN portrait: no canonical-French clause in gain rows",
              not bad, f"bad={bad} rows={pr['rows']}")
        check("P4 EN portrait: labels = gainUp ('reach') / settleFor ('settle for')",
              all(("reach" in r["txt"] or "settle" in r["txt"]) for r in pr["rows"]), str(pr["rows"]))
        check("P5 EN portrait: no JS errors", not errs, str(errs[:3]))
        b.close()

    print("="*40)
    print(f"=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
    raise SystemExit(1 if FAIL else 0)

if __name__ == "__main__":
    main()
