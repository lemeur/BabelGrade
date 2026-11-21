"""Grid i18n (official LVA/LVB criterion translation) — live E2E.

Verifies, on the running app, that the official LVA/LVB grid criterion names /
level descriptors / gap chips are translated for display in the chosen UI
language, while the backend stays keyed on the canonical French strings.

Creates a FRESH teacher-skeleton analysis (via the real /api/evaluate endpoint)
against the att-exp-ecrite attestation rubric, runs the UI checks, then deletes
it — no pre-existing data is touched, so the test is safe to re-run.

Run (any venv with playwright + the project importable):
  /tmp/bg_venv/bin/python tests/test_grid_i18n.py
"""
import sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _testpw as T
from playwright.sync_api import sync_playwright

BASE = os.environ.get("BABELGRADE_TEST_BASE", "http://127.0.0.1:8090")
RUBRIC = "att-exp-ecrite"
CANON = ["Qualité du contenu", "Cohérence dans la construction du discours",
         "Correction de la langue écrite", "Richesse de la langue"]
EN = {"Qualité du contenu": "Content quality",
      "Cohérence dans la construction du discours": "Coherence in discourse construction",
      "Correction de la langue écrite": "Accuracy of the written language",
      "Richesse de la langue": "Language richness"}

FAILS = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{extra}]" if extra and not ok else ""))
    if not ok: FAILS.append(name)

def make(lang):
    pw = sync_playwright().start()
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width":1280,"height":860}, device_scale_factor=2, locale="en-US")
    ctx.add_init_script(f"localStorage.setItem('babelgrade-lang','{lang}');")
    pg = ctx.new_page(); errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    return pw, b, pg, errs

def login(pg):
    pg.goto(BASE, wait_until="networkidle")
    pg.fill("#auth-username", T.USERNAME); pg.fill("#auth-password", T.pw())
    pg.click("#auth-login-btn"); pg.wait_for_timeout(900)
    assert pg.evaluate("document.getElementById('auth-gate').classList.contains('hide')")

def levels(pg, aid):
    return pg.evaluate("""async (id)=>{ const r=await fetch('/api/analyses/'+id); const j=await r.json();
      return (j.matrix&&j.matrix.rubric_mapping||[]).map(m=>m.criterion+'='+m.suggested_level); }""", aid)

def wait_matrix(pg, aid, timeout_ms=15000):
    """Poll until the skeleton's rubric_mapping is populated (the evaluate job
    fills matrix_json asynchronously — render before that shows the
    unstructured fallback with 0 att rows)."""
    import time
    n = 0
    t0 = time.time()
    while (time.time() - t0) * 1000 < timeout_ms:
        n = pg.evaluate("""async(id)=>{ const j=await (await fetch('/api/analyses/'+id)).json();
          return ((j.matrix||{}).rubric_mapping||[]).length; }""", aid)
        if n >= 4: return n
        pg.wait_for_timeout(400)
    raise TimeoutError(f"skeleton matrix not ready within {timeout_ms}ms (last n={n})")

def render(pg, aid, target="#report"):
    """Fetch the analysis and hand renderReport the EXACT shape the history
    flow builds ({data: a.matrix, parsed: !!a.matrix, ...}) — NOT the raw body.
    Playwright Python passes the arg as ONE value, so destructure the [id,
    target] pair in JS (passing a bare 2-tuple makes `id` the whole array →
    a 422 URL like /api/analyses/646,#report)."""
    return pg.evaluate("""async ([id, target])=>{
      const a = await (await fetch('/api/analyses/'+id)).json();
      window.__last = window.__last || {d:null,P:null};
      const d = {id:id, data:a.matrix, ai_data:a.ai_matrix||null, aiMode:a.ai_mode||null,
        aiAt:a.ai_at||null, parsed:!!a.matrix, raw:a.raw_markdown, warnings:[],
        fluency:a.fluency||null, transcript:a.transcript||null, attestation:a.attestation||null,
        validated:!!a.validated, note20:a.note20||null, rubric_id:a.rubric_id||null};
      window.__last.d = d;
      renderReport(d, target);
      return document.querySelectorAll(target+' .att-table tbody tr.att-main-row').length;
    }""", [aid, target])

def rows(pg, target="#report"):
    return pg.evaluate("""(target)=>[...document.querySelectorAll(target+' .att-table tbody tr.att-main-row')]
      .map(tr=>({v: tr.cells[0]?tr.cells[0].textContent.trim():null,
                 c: tr.dataset.crit||null,
                 lvl: (tr.querySelector('.att-lvl')||{}).value}))""", target)

# --- create a fresh teacher skeleton against the attestation rubric --------
pw, b, pg, errs = make("en")
login(pg)
aid = pg.evaluate("""async (rubric)=>{
  const fd = new FormData();
  fd.append('written_text','This is a fresh test copy created by the grid-i18n E2E test.');
  fd.append('kind','written'); fd.append('rubric_id', rubric);
  fd.append('title','grid-i18n-e2e'); fd.append('language','en');
  const r = await fetch('/api/evaluate',{method:'POST', body:fd});
  const j = await r.json();
  return {status:r.status, analysis_id:(j.analysis_id||null), follow:(j.follow_url||null)};
}""", RUBRIC)
check("POST /api/evaluate created a skeleton", aid["status"]==200 and aid["analysis_id"],
      f"(status={aid['status']} id={aid['analysis_id']})")
AID = aid["analysis_id"]
if not AID:
    print("\nRESULT: ABORT (no analysis id) —", FAILS); b.close(); pw.stop(); sys.exit(1)

try:
    wait_matrix(pg, AID)
    print("\n== 1. EN: translated cells + canonical data-crit ==")
    n = render(pg, AID)
    check("att-table rendered 4 rows", n==4, f"(n={n})")
    for r in rows(pg):
        check(f"EN display '{r['v']}' <- canonical '{r['c']}'",
              r["c"] in CANON and r["v"]==EN.get(r["c"], r["c"]), f"(lvl={r['lvl']})")

    print("\n== 2. Counter-proposal save round-trip (EN UI, canonical keys) ==")
    before = levels(pg, AID)
    check("skeleton has empty levels", all("=" in x and x.endswith("=") for x in before), f"({before})")
    # set two levels exactly as the UI does: key on data-crit, change .att-lvl
    pg.evaluate("""() => {
      const set=(crit,lv)=>{ const tr=[...document.querySelectorAll('#report tr.att-main-row')]
        .find(x=>x.dataset.crit===crit);
        if(tr){ tr.querySelector('.att-lvl').value=lv;
          tr.querySelector('.att-lvl').dispatchEvent(new Event('change',{bubbles:true})); } };
      set('Qualité du contenu','C1');
      set('Correction de la langue écrite','A2');
    }""")
    pg.wait_for_timeout(300)
    clicked = pg.evaluate("""() => { const b=document.querySelector('#report #att-save');
      return b ? (b.click(),'clicked') : 'NO BUTTON'; }""")
    check("#att-save present + clicked", clicked=="clicked", f"(got {clicked})")
    pg.wait_for_timeout(2000)
    after = levels(pg, AID)
    expect = {"Qualité du contenu":"C1",
              "Cohérence dans la construction du discours":"",
              "Correction de la langue écrite":"A2",
              "Richesse de la langue":""}
    got = {k:lv for k,lv in (x.split("=",1) for x in after)}
    check("save matched the CANONICAL criteria (not the translated text)", got==expect, f"(got {got})")

    print("\n== 3. Language switch EN->FR: cells re-point, .att-lvl preserved ==")
    lvls_before = {r["c"]: r["lvl"] for r in rows(pg)}
    pg.evaluate("""() => { const btn=document.querySelector('#menu-lang .lang-opt[data-lang="fr"]')
      || [...document.querySelectorAll('[data-lang]')].find(x=>x.dataset.lang==='fr');
      if(btn){ btn.click(); return 'clicked'; } return 'NO LANG BTN'; }""")
    pg.wait_for_timeout(900)
    rf = rows(pg)
    for r in rf:
        check(f"FR display back to French '{r['v']}'", r["v"]==r["c"] and r["c"] in CANON, f"(lvl={r['lvl']})")
    lvls_after = {r["c"]: r["lvl"] for r in rf}
    check(".att-lvl values preserved across language switch", lvls_after==lvls_before,
          f"(prev {lvls_before} vs now {lvls_after})")

    print("\n== 4. Rubric list + detail use translated names (EN) ==")
    # switch back to EN, open rubrics view, verify the attestation grid shows EN name
    pg.evaluate("""() => { const btn=document.querySelector('#menu-lang .lang-opt[data-lang="en"]')
      || [...document.querySelectorAll('[data-lang]')].find(x=>x.dataset.lang==='en');
      if(btn) btn.click(); return 'ok'; }""")
    pg.wait_for_timeout(700)
    rubname = pg.evaluate("""async (rid)=>{ const r=await fetch('/api/rubrics/'+rid); const j=await r.json();
      return j.name||null; }""", RUBRIC)
    check("backend rubric.name stays canonical French", rubname=="Attestation LVA/LVB — Expression écrite",
          f"(got {rubname!r})")
finally:
    # --- cleanup: delete the throwaway analysis ----------------------------
    st = pg.evaluate("""async (id)=>{ const r=await fetch('/api/analyses/'+id,{method:'DELETE'});
      return r.status; }""", AID)
    check("cleanup: throwaway analysis deleted", st in (200,204), f"(status={st})")

jserr = [e for e in errs if "404" not in e]
check("no JS console errors", not jserr, f"({jserr[:3]})" if jserr else "")
b.close(); pw.stop()

print("\nRESULT:", "ALL GREEN ★" if not FAILS else f"{len(FAILS)} FAILURE(S): {FAILS}")
sys.exit(1 if FAILS else 0)
