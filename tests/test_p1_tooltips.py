#!/usr/bin/env python3
"""P1.3 verify: jargon tooltips.
- 9 tip.* i18n keys defined 4x (EN/FR/ES/DE) and every t('tip.x') reference resolves
- history detail attestation card carries native-lang title tooltips:
  * attestation h2  -> tip.att
  * overall-level pill -> tip.result
  * criterion header  -> tip.critGrid
  * /120 score span   -> tip.points
- no JS errors"""
import os, re, time
import _testpw as TESTPW
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8090"
OUT = os.path.dirname(os.path.abspath(__file__))
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

def login(pg, lang="fr"):
    pg.add_init_script(f"localStorage.setItem('babelgrade-lang','{lang}')")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", TESTPW.pw())
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    pg.wait_for_timeout(600)

def api(pg, path, method="GET", body=None):
    return pg.evaluate("""async ({path, method, body}) => {
      const opt = {method};
      let bd = null;
      if (body) { opt.headers = {'Content-Type':'application/json'}; bd = JSON.stringify(body); }
      const r = await fetch(path, {method, headers: opt.headers||{}, body: bd});
      return {status: r.status, data: await r.json().catch(()=>null)};
    }""", {"path": path, "method": method, "body": body})

# native-language marker for tip.att / tip.result / tip.critGrid / tip.points
EXPECT = {
  "en": ("Attests a CEFR level", "Overall level computed", "six official sub-scores", "Points out of 120"),
  "fr": ("Atteste un niveau CECRL", "Niveau global calculé", "six sous-critères officiels", "Points sur 120"),
  "es": ("Certifica un nivel MCER", "Nivel global calculado", "seis subcriterios oficiales", "Puntos sobre 120"),
  "de": ("Attestiert ein GER-Niveau", "Gesamtstufe, berechnet", "sechs offiziellen Teilpunkte", "Punkte von 120"),
}

with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg, "fr")

    # ---- seed a teacher-first attestation analysis (no AI opinion) ----
    st = api(pg, "/api/students", "POST", {"name": "P1TipTest"}).get("data")
    sid = st["id"]
    pg.evaluate(f"window.__sid={sid}")
    ev = pg.evaluate("""async () => {
      const fd = new FormData();
      fd.append('kind','written');
      fd.append('rubric_id','att-exp-ecrite');
      fd.append('student_id', String(window.__sid));
      fd.append('assignment_id','0');
      fd.append('title','P1 tooltips essay');
      fd.append('language','en');
      fd.append('target_level','B2');
      fd.append('written_text','It was a dark stormy night and the wind howled through the broken window. The old man lit a lamp and began to write his last letter, his hand trembling as he shaped each careful word on the yellowed paper.');
      const r = await fetch('/api/evaluate', {method:'POST', body: fd});
      return await r.json();
    }""")
    jid = ev.get("id") or ev.get("job_id")
    done = None
    for _ in range(60):
        j = api(pg, f"/api/jobs/{jid}").get("data") or {}
        if j.get("status") in ("done", "error", "cancelled"):
            done = j; break
        time.sleep(2)
    check("seed: job finished", done and done["status"] == "done", done and done.get("status"))
    aid = done.get("analysis_id")
    check("seed: analysis id", bool(aid), aid)
    pg.close(); ctx.close()

    # ---- per-language: open deep link, check native title tooltips ----
    for lang, (att_m, res_m, crit_m, pts_m) in EXPECT.items():
        ctx = b.new_context(viewport={"width": 1280, "height": 800})
        pg = ctx.new_page()
        errs2 = []
        pg.on("pageerror", lambda e, _errs=errs2: _errs.append(str(e)))
        login(pg, lang)
        pg.evaluate(f"() => {{ location.hash = '#history/{aid}'; }}")
        pg.wait_for_selector("#hist-report .att-card", timeout=30000)
        st2 = pg.evaluate("""() => {
          const card = document.querySelector('#hist-report .att-card');
          const titles = [...card.querySelectorAll('[title]')].map(e => e.getAttribute('title'));
          return {
            attTitle: card.querySelector('.att-ess h2') ? card.querySelector('.att-ess h2').getAttribute('title') : null,
            lvlTitle: card.querySelector('.att-ess .att-level') ? card.querySelector('.att-ess .att-level').getAttribute('title') : null,
            critTitle: card.querySelector('.att-table thead th') ? card.querySelector('.att-table thead th').getAttribute('title') : null,
            ptsTitle: titles.find(t => t && t.length > 15) || null,
            allTitles: titles
          };
        }""")
        check(f"{lang}: tip.att on attestation title", att_m in (st2["attTitle"] or ""), st2["attTitle"])
        check(f"{lang}: tip.result on overall pill", res_m in (st2["lvlTitle"] or ""), st2["lvlTitle"])
        check(f"{lang}: tip.critGrid on criterion th", crit_m in (st2["critTitle"] or ""), st2["critTitle"])
        check(f"{lang}: tip.points on /120 span", any(pts_m in (x or "") for x in st2["allTitles"]), st2["allTitles"])
        check(f"{lang}: no page errors", not errs2, errs2)
        pg.close(); ctx.close()

    # ---- static: i18n balance 4x + references resolve ----
    html = open(os.path.join(OUT, "..", "static", "index.html"), encoding="utf-8").read()
    keys = ["tip.att","tip.modalite","tip.note20","tip.vsTarget","tip.aiCol","tip.just","tip.points","tip.result","tip.critGrid"]
    counts = {k: len(re.findall(r"'\s*" + re.escape(k) + r"\s*'\s*:", html)) for k in keys}
    check("i18n: 9 tip.* keys defined 4x", all(v == 4 for v in counts.values()), counts)
    refs = set(re.findall(r"\bt\('tip\.([A-Za-z]+)'\)", html))
    defined = set(re.findall(r"'tip\.([A-Za-z]+)'\s*:", html))
    check("i18n: every tip.* reference is defined", not (refs - defined), sorted(refs - defined))
    check("no page errors (main page)", not errs, errs)

    b.close()

print(f"\n{len(PASS)}/{len(PASS)+len(FAIL)} checks passed")
if FAIL:
    print("FAILED:", FAIL)
    raise SystemExit(1)
print("ALL OK")
