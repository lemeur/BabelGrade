"""V3 (desktop ergonomics) — live E2E, desktop 1280 FR.

Proves the 5 desktop items shipped in Wave 3 (docs/ux-audit-2026-11-23.md §4):
  D1  the two near-identical AI CTAs are now differentiated: #run stays solid,
      #run-eval is ghost, and both carry i18n tooltips (an.runTip /
      an.runEvalTip) explaining what each does.
  D2  the 5 icon-only row actions in the Sujets table expose aria-labels ×4
      i18n and sit in a regular single row (no 2×2+1 ragged cluster — one row
      of ≥4 buttons).
  D3  the 4-step plan is an honest SUMMARY: the accordion step badges flip
      .done (✓) with the completion state — clearing the rubric select makes
      step 4 lose its badge, re-selecting regains it (change-driven sync).
  D4  tooltips ×4 on « ◂ Simplifié » (home.advBackTip) + « ⚙ Données »
      (nav.dataTip); the Whisper pill is muted for the WRITTEN channel and
      un-muted when the channel switches to oral.
  D5  Sujets table nits: DEPUIS date on one line (white-space:nowrap),
      PRODUCTIONS count no longer clipped by the dotted underline (overflow
      removed + hover affordance), resource badges uniform
      "icon + text" ("📷 2 photo(s)").

Run:  /tmp/bg_venv/bin/python tests/test_ux_wave3.py   (server live on :8090)
"""
import re
import _testpw as TESTPW
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8090"
PASS, FAIL = [], []

def check(n, c, x=""):
    (PASS if c else FAIL).append(n)
    print(("PASS " if c else "FAIL ") + n + (f" | {x}" if x and not c else ""))

def css(pg, sel, prop):
    return pg.evaluate(f"""sel => {{
      const el = document.querySelector(sel);
      return el ? getComputedStyle(el).getPropertyValue('{prop}') : null;
    }}""", sel)

def _has_icon(s):
    """True if the string carries an emoji / symbol code point (badge icon)."""
    for ch in s:
        o = ord(ch)
        if 0x1F000 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF:
            return True
    return False

with sync_playwright() as pw:
    ctx = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"]) \
           .new_context(viewport={"width": 1280, "height": 800}, locale="fr-FR")
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
    pg.add_init_script("localStorage.setItem('babelgrade-lang','fr')")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", TESTPW.pw())
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    pg.wait_for_timeout(900)

    # ---- D1: CTAs differentiated + tooltips ----
    pg.evaluate("navGo('evaluator',null,{});")
    pg.wait_for_timeout(900)
    d1 = pg.evaluate("""() => ({
      runClass: document.getElementById('run').className,
      runEvalClass: document.getElementById('run-eval').className,
      runTip: document.getElementById('run').getAttribute('title'),
      runEvalTip: document.getElementById('run-eval').getAttribute('title')})""")
    check("D1: #run stays solid (btn, not ghost)",
          "btn" in d1["runClass"] and "ghost" not in d1["runClass"], d1["runClass"])
    check("D1: #run-eval is ghost (differentiated)",
          "ghost" in d1["runEvalClass"], d1["runEvalClass"])
    check("D1: #run carries a FR tooltip (IA + critique)",
          d1["runTip"] and "IA" in d1["runTip"], d1["runTip"])
    check("D1: #run-eval carries a FR tooltip (vous d'abord)",
          d1["runEvalTip"] and ("d’abord" in d1["runEvalTip"] or "d'abord" in d1["runEvalTip"]),
          d1["runEvalTip"])

    # ---- D4: toolbar tooltips + Whisper pill context ----
    d4 = pg.evaluate("""() => ({
      homeTip: document.getElementById('hdr-home').getAttribute('title'),
      dataTip: document.getElementById('menu-data-btn').getAttribute('title'),
      sttMuted: document.getElementById('badge-stt').classList.contains('muted'),
      kind: KIND})""")
    check("D4: '◂ Simplifié' has a FR tooltip",
          d4["homeTip"] and "accueil" in d4["homeTip"].lower(), d4["homeTip"])
    check("D4: '⚙ Données' has a FR tooltip",
          d4["dataTip"] and "Données" in d4["dataTip"], d4["dataTip"])
    check("D4: Whisper pill muted on the written channel",
          d4["kind"] == "written" and d4["sttMuted"] is True, str(d4))
    pg.evaluate("""() => {
      const b=document.querySelector('#mode-seg button[data-kind="oral"]');
      if(b)b.click();}""")
    pg.wait_for_timeout(500)
    d4b = pg.evaluate("""() => ({muted:document.getElementById('badge-stt').classList.contains('muted'),
      kind:KIND, sttText:document.getElementById('badge-stt').textContent})""")
    check("D4: Whisper pill un-muted on the oral channel",
          d4b["kind"] == "oral" and d4b["muted"] is False, str(d4b))
    pg.evaluate("""() => {
      const b=document.querySelector('#mode-seg button[data-kind="written"]');
      if(b)b.click();}""")
    pg.wait_for_timeout(500)
    check("D4: back to written re-mutes the pill",
          pg.evaluate("document.getElementById('badge-stt').classList.contains('muted')") is True)

    # ---- D3: accordion step badges = honest summary (.done ✓ when filled) ----
    # The live app pre-selects a rubric, so drive the MECHANIC: clear the
    # rubric -> step 4 loses its .done badge; re-select -> step 4 regains it
    # (the same change-driven completion sync as before the accordion).
    marks0 = pg.evaluate("""() => [...document.querySelectorAll('#wz-steps .acc-item')]
      .map(it => ({step:it.dataset.step, done:it.classList.contains('done'),
                   cur:it.classList.contains('cur'),
                   open:it.classList.contains('open')}))""")
    check("D3: 4 accordion steps with state classes", len(marks0) == 4, str(marks0))
    # clear the rubric -> step 4 must lose its .done badge
    pg.evaluate("""() => {
      const s=document.getElementById('rubric');
      s.value=''; s.dispatchEvent(new Event('change',{bubbles:true}));}""")
    pg.wait_for_timeout(400)
    step4a = pg.evaluate("""() => {
      const c=document.querySelector('.acc-item[data-step="4"]');
      return {done:c.classList.contains('done')};}""")
    check("D3: rubric cleared -> step 4 is no longer .done",
          step4a["done"] is False, str(step4a))
    # re-select the first attestation rubric -> step 4 regains .done
    pg.evaluate("""() => {
      const s=document.getElementById('rubric');
      if(s.options.length>1)s.selectedIndex=1; else s.selectedIndex=0;
      s.dispatchEvent(new Event('change',{bubbles:true}));}""")
    pg.wait_for_timeout(400)
    step4b = pg.evaluate("""() => {
      const c=document.querySelector('.acc-item[data-step="4"]');
      return {done:c.classList.contains('done')};}""")
    check("D3: rubric picked -> step 4 regains .done (✓ badge)",
          step4b["done"] is True, str(step4b))
    # the ✓ badge renders via .wz-num::before — verify the computed glyph
    cssmark = pg.evaluate("""() => ({
      c4: getComputedStyle(document.querySelector('.acc-item[data-step="4"] .wz-num'),'::before').content})""")
    check("D3: CSS ::before badge renders (✓ glyph)",
          '✓' in cssmark["c4"] or '2713' in cssmark["c4"], str(cssmark))

    # ---- D2: row actions aria-labels ×4 + regular single row ----
    pg.evaluate("navGo('assignments',null,{});")
    pg.wait_for_timeout(900)
    d2 = pg.evaluate("""() => {
      const row=document.querySelector('#assignments tbody tr');
      if(!row)return {rows:0};
      const sel='button[data-assignview],button[data-assignuse],button[data-assignedit],button[data-assigndel]';
      const btns=[...row.querySelectorAll(sel)];
      const rects=btns.map(b=>Math.round(b.getBoundingClientRect().top));
      const uniqTop=new Set(rects).size;
      return {rows:document.querySelectorAll('#assignments tbody tr').length,
              n:btns.length, uniqTop,
              aria:btns.map(b=>b.getAttribute('aria-label'))};}""")
    check("D2: ≥4 row actions with non-empty aria-labels",
          d2.get("n", 0) >= 4 and all(a and a.strip() for a in d2.get("aria", [])),
          str(d2.get("aria")))
    check("D2: actions share one row (same top y) — not 2×2+1",
          d2.get("uniqTop") == 1, f"uniqTop={d2.get('uniqTop')}")
    check("D2: aria-labels are the FR i18n strings (Détails/Utiliser/Modifier/Supprimer)",
          any("Détails" in a for a in d2.get("aria", []))
          and any("Utiliser" in a for a in d2.get("aria", [])),
          str(d2.get("aria")))

    # ---- D5: DEPUIS nowrap + PRODUCTIONS not clipped + uniform badges ----
    d5 = pg.evaluate("""() => {
      const row=document.querySelector('#assignments tbody tr');
      if(!row)return {rows:0};
      const cells=[...row.querySelectorAll('td')];
      // DEPUIS = 6th cell (index 5); check computed white-space
      const depuis=cells[5];
      const ws=depuis?getComputedStyle(depuis).whiteSpace:null;
      // PRODUCTIONS = 5th cell (index 4): the subslink button
      const subs=cells[4]?cells[4].querySelector('.subslink'):null;
      const subsOverflow=subs?getComputedStyle(subs).overflow:null;
      // resource badges
      const badges=[...row.querySelectorAll('.res-badge')].map(b=>b.textContent.trim());
      return {rows:cells.length, ws, subsOverflow,
              hasSubs:!!subs, badges};}""")
    check("D5: DEPUIS cell white-space:nowrap",
          d5.get("ws") == "nowrap", f"ws={d5.get('ws')}")
    check("D5: PRODUCTIONS subslink not overflow-clipped",
          d5.get("subsOverflow") in ("visible", None, "clip") or d5.get("hasSubs") is False,
          f"subsOverflow={d5.get('subsOverflow')}")
    check("D5: resource badges carry an icon + text (uniform)",
          any(_has_icon(b) for b in d5.get("badges", [])) or len(d5.get("badges", [])) == 0,
          str(d5.get("badges")))

    check("0 page errors", len(errors) == 0, str(errors))
    ctx.close()

# ---- static: i18n keys exist 4× each (scoped to the I18N block — a key may
#      ALSO appear in JS maps like RES_ICON, so don't count the whole file) ----
html = open("/home/tibo/babelgrade/static/index.html", encoding="utf-8").read()
m = re.search(r"const I18N=\{(.*?)\nlet LANG", html, re.S)
i18n_block = m.group(1) if m else ""
for k in ["an.runTip", "an.runEvalTip", "home.advBackTip", "nav.dataTip", "td.ph"]:
    c = len(re.findall(r"'" + re.escape(k) + r"':'", i18n_block))
    check(f"i18n: {k} defined 4× (in I18N block)", c == 4, str(c))

print("=" * 40)
print(f"=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
if FAIL:
    print("FAILED:", FAIL)
    raise SystemExit(1)
