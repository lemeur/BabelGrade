#!/usr/bin/env python3
"""Eval-mode level cards follow the UI language (2026-11-23).

Before this fix the Mode Évaluation overlay cards showed the CANONICAL FRENCH
per-level descriptors (crit.levels from the rubric) even when the UI language
was EN/ES/DE — only the gap chips and criterion names were translated.

Checks (Playwright, live server on :8090, login tibo):
  E1  overlay opens in EN, full 6-card scale (wide desktop)
  E2  centre card descriptor == the EN translated per-level segment (exact)
  E3  every side card contains the translated segment words + diff <mark>s
  E4  gap chips carry the translated word (title), not the canonical French one
  E5  language switch EN→FR live: cards re-render, centre desc == canonical FR
  E6  language switch FR→DE live: centre desc == DE translation
  E7  no JS console errors

Uses a pre-existing populated att-exp-ecrite analysis (read-only — nothing is
mutated or deleted, so the test is safe to re-run).
Run:  /tmp/bg_venv/bin/python tests/test_eval_cards_i18n.py
"""
import sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _testpw as T
from playwright.sync_api import sync_playwright

BASE = os.environ.get("BABELGRADE_TEST_BASE", "http://127.0.0.1:8090")

FAILS = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{extra}]" if extra and not ok else ""))
    if not ok: FAILS.append(name)

pw = sync_playwright().start()
b = pw.chromium.launch(headless=True)
ctx = b.new_context(viewport={"width":1280,"height":860}, device_scale_factor=2, locale="en-US")
ctx.add_init_script("localStorage.setItem('babelgrade-lang','en');")
pg = ctx.new_page(); errs = []
pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
pg.goto(BASE, wait_until="networkidle")
pg.fill("#auth-username", T.USERNAME); pg.fill("#auth-password", T.pw())
pg.click("#auth-login-btn"); pg.wait_for_timeout(900)

# --- pick a populated written att-exp-ecrite analysis -------------------------
# (the list endpoint omits rubric_id → match on the canonical French name)
aid = pg.evaluate("""async()=>{const r=await fetch('/api/analyses');const j=await r.json();
  const rows=Array.isArray(j)?j:(j.items||[]);
  const c=rows.filter(x=>(x.rubric_name||'').startsWith('Attestation')&&x.kind==='written');
  return c.length?c[0].analysis_id:null;}""")
check("found a written att-exp-ecrite analysis", aid, f"(aid={aid})")
if not aid:
    print("\nRESULT: ABORT (no analysis) —", FAILS); b.close(); pw.stop(); sys.exit(1)

# --- render the report into #report and open the eval overlay -----------------
n = pg.evaluate("""async (id)=>{
  const a = await (await fetch('/api/analyses/'+id)).json();
  window.__last = window.__last || {d:null,P:null};
  window.__last.d = {id:id, data:a.matrix, ai_data:a.ai_matrix||null, aiMode:a.ai_mode||null,
    aiAt:a.ai_at||null, parsed:!!a.matrix, raw:a.raw_markdown, warnings:[],
    fluency:a.fluency||null, transcript:a.transcript||null, attestation:a.attestation||null,
    validated:!!a.validated, note20:a.note20||null, rubric_id:a.rubric_id||null};
  renderReport(window.__last.d, '#report');
  return document.querySelectorAll('#report .att-table tbody tr.att-main-row').length;
}""", aid)
check("att-table rendered", n==4, f"(n={n})")

opened = pg.evaluate("""async()=>{
  const btn=document.querySelector('#report #att-eval');
  if(!btn)return 'NO BTN';
  await openEval(btn);
  return document.getElementById('eval').hidden?'HIDDEN':'OPEN';
}""")
check("eval overlay opens", opened=="OPEN", f"(got {opened})")
pg.wait_for_timeout(400)

# --- E1: full 6-card scale on wide desktop ------------------------------------
cards = pg.evaluate("() => document.querySelectorAll('#ev-cols .ev-col[data-lv]').length")
check("E1 six level cards (wide scale)", cards==6, f"(n={cards})")

# --- E2/E3/E4: descriptors + diff marks + gap chips in EN ---------------------
res = pg.evaluate("""()=>{
  const rubricId=window.__last.d.rubric_id;
  const rub=document.createElement('div');
  // rubric is fetched async by openEval into EVAL.crits — read from there instead
  const cur=EVAL.rows[EVAL.cur].name;
  const crit=EVAL.crits[cur];
  if(!crit||!crit.levels)return {err:'no crits loaded'};
  const L=EVAL.chosen[EVAL.cur];
  const gi=window.BG_GRID_I18N.en;
  const fr=(lv)=>crit.levels[lv]||'';
  const en=(lv)=>gi.lvdescs[fr(lv)]!=null?gi.lvdescs[fr(lv)]:fr(lv);
  const centre=document.querySelector(`#ev-cols .ev-col[data-lv="${L}"] .desc`);
  const out={centreText:centre?centre.textContent.trim():null, centreExpected:en(L),
             sideOk:0, sideBad:[], chipOk:0, chipBad:[], marks:0};
  document.querySelectorAll('#ev-cols .ev-col[data-lv]').forEach(col=>{
    const lv=col.dataset.lv;
    if(lv===L)return;
    const d=col.querySelector('.desc');
    const txt=d?d.textContent.trim():'';
    const exp=en(lv);
    const firstWords=exp.split(/\\s+/).slice(0,4).join(' ');
    if(!txt.includes(firstWords))out.sideBad.push(lv+' :: '+txt.slice(0,60)+' !~ '+exp.slice(0,60));
    else out.sideOk++;
    out.marks+=(d?d.querySelectorAll('mark').length:0);
  });
  document.querySelectorAll('#ev-cols .ev-col .gap-chip[title]').forEach(ch=>{
    const col=ch.closest('.ev-col[data-lv]');
    const lv=col.dataset.lv;
    const word=(col.dataset.pos==='right'?(crit.gaps[L]||{}).up:(crit.gaps[L]||{}).down)||'';
    const expected=gi.gaps[word]!=null?gi.gaps[word]:word;   // what gGap() returns in EN
    if(ch.getAttribute('title')!==expected)out.chipBad.push(col.dataset.pos+' '+lv+': '+ch.getAttribute('title')+' !~ '+expected);
    else out.chipOk++;
  });
  return out;
}""")
if res.get("err"):
    check("E2/E3/E4 crits loaded", False, res["err"])
else:
    check("E2 centre card descriptor is the EN translation (exact)",
          res["centreText"]==res["centreExpected"],
          f"(got {res['centreText']!r} want {res['centreExpected']!r})")
    check("E3 side cards carry translated text", res["sideOk"]==5 and not res["sideBad"],
          f"(ok={res['sideOk']} bad={res['sideBad']})")
    check("E3 inline diff marks present on side cards", res["marks"]>=5, f"(marks={res['marks']})")
    check("E4 gap chips translated (EN, not canonical FR)", res["chipOk"]>=4 and not res["chipBad"],
          f"(ok={res['chipOk']} bad={res['chipBad']})")

# --- E5: live language switch EN→FR re-renders the cards ----------------------
pg.evaluate("""()=>{const btn=[...document.querySelectorAll('[data-lang]')].find(x=>x.dataset.lang==='fr');
  if(btn){btn.click();return 'clicked';}return 'NO LANG BTN';}""")
pg.wait_for_timeout(700)
fr_res = pg.evaluate("""()=>{
  const cur=EVAL.rows[EVAL.cur].name;
  const crit=EVAL.crits[cur];
  const L=EVAL.chosen[EVAL.cur];
  const centre=document.querySelector(`#ev-cols .ev-col[data-lv="${L}"] .desc`);
  const gi=window.BG_GRID_I18N.fr||null;
  // FR: gLevelDesc must return the canonical segment (no fr lvdescs pack)
  return {lang:LANG, centreText:centre?centre.textContent.trim():null,
          expected:crit.levels[L]||'', hasFrPack:!!gi};
}""")
check("E5 language switch to FR live", fr_res["lang"]=="fr", f"(lang={fr_res['lang']})")
check("E5 centre card back to canonical French", fr_res["centreText"]==fr_res["expected"],
      f"(got {fr_res['centreText']!r} want {fr_res['expected']!r})")
fr_marks = pg.evaluate("() => document.querySelectorAll('#ev-cols .desc mark').length")
check("E5 side cards still diff-marked in FR", fr_marks>=5, f"(marks={fr_marks})")

# --- E6: FR→DE live ------------------------------------------------------------
pg.evaluate("""()=>{const btn=[...document.querySelectorAll('[data-lang]')].find(x=>x.dataset.lang==='de');
  if(btn){btn.click();return 'clicked';}return 'NO LANG BTN';}""")
pg.wait_for_timeout(700)
de_res = pg.evaluate("""()=>{
  const cur=EVAL.rows[EVAL.cur].name;
  const crit=EVAL.crits[cur];
  const L=EVAL.chosen[EVAL.cur];
  const centre=document.querySelector(`#ev-cols .ev-col[data-lv="${L}"] .desc`);
  const de=window.BG_GRID_I18N.de.lvdescs[crit.levels[L]||'']||crit.levels[L];
  return {lang:LANG, centreText:centre?centre.textContent.trim():null, expected:de};
}""")
check("E6 language switch to DE live", de_res["lang"]=="de", f"(lang={de_res['lang']})")
check("E6 centre card shows the DE translation", de_res["centreText"]==de_res["expected"],
      f"(got {de_res['centreText']!r} want {de_res['expected']!r})")

jserr = [e for e in errs if "404" not in e]
check("E7 no JS console errors", not jserr, f"({jserr[:3]})")
b.close(); pw.stop()
print("\nRESULT:", "ALL GREEN ★" if not FAILS else f"{len(FAILS)} FAILURE(S): {FAILS}")
sys.exit(1 if FAILS else 0)
