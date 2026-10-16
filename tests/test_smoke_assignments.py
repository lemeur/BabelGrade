#!/usr/bin/env python3
"""Smoke suite: Assignments (Sujets) + Evaluations core flows.

Re-creation of the pre-auth-gate /tmp/elt_asgn/smoke.py (stale since the
2026-10-13 login gate; /tmp is lost on reboot). Follows the repo test
conventions: login(tibo/****) helper, own teardown of seeded rows.

Covers (desktop 1280, FR):
- boot: no JS errors, default view = assignments, evaluator hidden until asked
- "+ New subject" modal: blank create state, save creates the row (UI->API),
  and the evaluator opens with the new subject selected
- edit prefill via the ✎ row button, cancel closes
- delete via ✕ (confirm auto-accepted) -> API row gone
- ad-hoc entry: "Évaluer sans sujet" opens the evaluator with no subject
- 390px: assignments table fits (no page-level horizontal overflow)
Teardown: any leftover 'Smoke probe' rows are deleted at the end."""
import sys
sys.path.insert(0, "/tmp/elt_dm/venv/lib/python3.11/site-packages")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8090"
PROBE = "Smoke probe 2026-10-16"
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

def login(pg, lang="fr"):
    pg.add_init_script(f"localStorage.setItem('elt-lang','{lang}')")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", "****")
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    pg.wait_for_timeout(800)

ROWS = """()=>[...document.querySelectorAll('#assignments tbody tr')]
  .filter(tr=>!tr.querySelector('td[colspan]')).length"""
PROBE_ROW = """n=>[...document.querySelectorAll('#assignments tbody tr')]
  .filter(tr=>!tr.querySelector('td[colspan]') && tr.textContent.includes(n)).length"""

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    login(pg)

    # clean leftovers from a crashed run, then capture the baseline
    pg.evaluate("""async n => {
      const list = await (await fetch('/api/assignments')).json();
      const ids = (Array.isArray(list)?list:list.items||[])
        .filter(a=>a.name===n).map(a=>a.id);
      await Promise.all(ids.map(id=>fetch('/api/assignments/'+id,{method:'DELETE'})));
    }""", PROBE)
    base_rows = pg.evaluate(ROWS)
    check(f"baseline: assignments rows >0 ({base_rows})", base_rows > 0)

    # --- boot state ---
    check("boot: assignments view active",
          pg.evaluate("!document.querySelector('#view-assignments').classList.contains('hide')"))
    check("boot: evaluator hidden until asked",
          pg.evaluate("document.querySelector('#view-analyze').classList.contains('hide')"))

    # --- create via the editor modal ---
    pg.click("#asg-new")
    pg.wait_for_selector("#assignment-edit-overlay:not(.hide)", timeout=5000)
    check("new: editor modal opens",
          not pg.evaluate("document.querySelector('#assignment-edit-overlay').classList.contains('hide')"))
    check("new: title = add",
          pg.evaluate("document.querySelector('#asg-edit-title').textContent") == "Nouveau sujet")
    check("new: name blank", pg.evaluate("document.querySelector('#asg-name').value") == "")
    check("new: add button label",
          pg.evaluate("document.querySelector('#asg-add').textContent") == "Enregistrer le sujet")

    pg.fill("#asg-name", PROBE)
    # target select is hidden inside the lvl carousel — set the value via JS
    pg.evaluate("document.querySelector('#asg-target').value='B1';"
                "document.querySelector('#asg-target').dispatchEvent(new Event('change',{bubbles:true}))")
    # skill/kind pills: click expression + written (data-pv holds the value)
    pg.evaluate("""() => {
      const s = document.querySelector('#asg-skill-pills [data-pv="expression"]');
      if (s) s.click();
      const k = document.querySelector('#asg-kind-pills [data-pv="written"]');
      if (k) k.click();
    }""")
    pg.click("#asg-add")
    pg.wait_for_timeout(1500)

    created = pg.evaluate("""async n => {
      const list = await (await fetch('/api/assignments')).json();
      const arr = Array.isArray(list)?list:list.items||[];
      const hit = arr.filter(a=>a.name===n);
      return hit.length ? hit[0] : null;
    }""", PROBE)
    check("create: API row exists", created is not None, str(created)[:120] if created else "")
    check("create: fields stored", created and created.get("target_level") == "B1"
          and created.get("skill") == "expression" and created.get("kind") == "written",
          {k: created.get(k) for k in ("target_level", "skill", "kind")} if created else "")

    check("create: table shows the new row",
          pg.evaluate(PROBE_ROW, PROBE) == 1)
    check("create: row count grew", pg.evaluate(ROWS) == base_rows + 1)
    check("create: evaluator opens with the subject selected",
          created is not None
          and not pg.evaluate("document.querySelector('#view-analyze').classList.contains('hide')")
          and pg.evaluate("document.querySelector('#assignment').value") == str(created["id"]))

    # --- edit prefill ---
    # back to the assignments view
    pg.evaluate("navGo('assignments')")
    pg.wait_for_timeout(500)
    if created:
        pg.evaluate(f"""() => {{
          const tr = [...document.querySelectorAll('#assignments tbody tr')]
            .find(t=>!t.querySelector('td[colspan]') && t.textContent.includes({PROBE!r}));
          tr.querySelector('[data-assignedit]').click();
        }}""")
        pg.wait_for_selector("#assignment-edit-overlay:not(.hide)", timeout=5000)
        check("edit: prefilled name",
              pg.evaluate("document.querySelector('#asg-name').value") == PROBE)
        check("edit: prefilled target",
              pg.evaluate("document.querySelector('#asg-target').value") == "B1")
        check("edit: note visible + edit button label",
              not pg.evaluate("document.querySelector('#asg-edit-note').classList.contains('hide')")
              and pg.evaluate("document.querySelector('#asg-add').textContent") == "Enregistrer les modifications")
        pg.click("#asg-cancel")
        pg.wait_for_timeout(300)
        check("edit: cancel closes the modal",
              pg.evaluate("document.querySelector('#assignment-edit-overlay').classList.contains('hide')"))

    # --- delete via the ✕ row button (confirm auto-accepted) ---
    if created:
        probe_id = str(created["id"])
        pg.evaluate("navGo('assignments')")
        pg.wait_for_timeout(500)
        pg.once("dialog", lambda d: d.accept())
        pg.evaluate(f"""() => {{
          const tr = [...document.querySelectorAll('#assignments tbody tr')]
            .find(t=>!t.querySelector('td[colspan]') && t.textContent.includes({PROBE!r}));
          tr.querySelector('[data-assigndel]').click();
        }}""")
        pg.wait_for_timeout(800)
        gone = pg.evaluate("""async id => {
          const r = await fetch('/api/assignments/'+id);
          return !r.ok;
        }""", probe_id)
        check("delete: API row gone", gone)
        check("delete: table row gone",
              pg.evaluate(PROBE_ROW, PROBE) == 0)
        check("delete: count back to baseline", pg.evaluate(ROWS) == base_rows)
        created = None  # no teardown needed for the probe row

    # --- ad-hoc entry ---
    pg.click("#asg-adhoc")
    pg.wait_for_timeout(300)
    check("adhoc: evaluator opens",
          not pg.evaluate("document.querySelector('#view-analyze').classList.contains('hide')"))
    check("adhoc: no subject selected",
          pg.evaluate("document.querySelector('#assignment').value") == "")

    # --- mobile 390: no page-level overflow on the assignments table ---
    mctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    m = mctx.new_page()
    merr = []
    m.on("pageerror", lambda e: merr.append(str(e)))
    login(m)
    m.evaluate("navGo('assignments')")
    m.wait_for_timeout(500)
    check("390: no horizontal page overflow",
          m.evaluate("document.documentElement.scrollWidth") <= 391,
          m.evaluate("document.documentElement.scrollWidth"))
    check("390: no JS errors", not merr, merr[:2])
    mctx.close()

    # --- teardown ---
    pg.evaluate("""async n => {
      const list = await (await fetch('/api/assignments')).json();
      const ids = (Array.isArray(list)?list:list.items||[])
        .filter(a=>a.name===n).map(a=>a.id);
      await Promise.all(ids.map(id=>fetch('/api/assignments/'+id,{method:'DELETE'})));
    }""", PROBE)
    check("teardown: probe rows deleted",
          pg.evaluate(PROBE_ROW, PROBE) == 0,
          pg.evaluate(ROWS))
    check("no JS page errors", not errors, errors[:3])

    b.close()

    print("=" * 40)
    print(f"=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
    if FAIL:
        sys.exit(1)
