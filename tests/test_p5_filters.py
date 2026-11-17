#!/usr/bin/env python3
"""P5 regression: the classic filter_test.py suite (2026-10-06), re-ported for
the two P4 changes (2026-10-15):
- filter rows are COLLAPSED by default on every viewport -> the test opens
  each row via its 🔍 toggle before using the fields
- multi-user login gate (2026-10-13) -> login first

Covers (desktop 1280):
- Assignments: name / type / level filters, AND combos, reset; counts checked
  against the API (relative, no fixture names assumed)
- Evaluations: title filter matches the API count; reset restores all
- Rubrics: name filter + no-match placeholder + reset (untouched view)
- Students: name filter + no-match placeholder + reset (untouched view)
- Deep link: reload on #history lands on the list with the (closed-by-default)
  filter row; opening it keeps the list usable
- 390px: filter rows open/close without horizontal overflow
Teardown: the seeded assignment is deleted at the end."""
import sys
sys.path.insert(0, "/tmp/elt_dm/venv/lib/python3.11/site-packages")
import _testpw as TESTPW
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8090"
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
    pg.wait_for_timeout(800)

def kind(x):
    """Channel of an assignment row: stored column, name convention as legacy
    fallback — mirrors asgnKindOf() in the UI."""
    if x.get("kind"):
        return x["kind"]
    s = (x.get("name") or "").lower()
    if "(oral" in s:
        return "oral"
    if "(written" in s:
        return "written"
    return None

def ensure_app(pg):
    """After a reload: session cookie may survive (app boots straight in) or
    not (login gate). Wait for whichever, and log in if needed."""
    try:
        pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=15000)
    except Exception:
        pg.wait_for_selector("#auth-username", state="visible", timeout=15000)
        pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", TESTPW.pw())
        pg.click("#auth-login-btn")
        pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)

DATA_ASGN = """()=>[...document.querySelectorAll('#assignments tbody tr')]
  .filter(tr=>!tr.querySelector('td[colspan]')).length"""
DATA_STU = """()=>[...document.querySelectorAll('#students tbody tr')]
  .filter(tr=>!tr.querySelector('td[colspan]')).length"""
HIST_ROWS = "()=>document.querySelectorAll('#hist tbody tr').length"

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    login(pg)

    # clean any leftovers from a previously crashed run, then seed one known
    # assignment for the name-filter checks
    pg.evaluate("""async () => {
      const list = await (await fetch('/api/assignments')).json();
      const ids = (Array.isArray(list)?list:list.items||[])
        .filter(a=>a.name==='P5 filter probe').map(a=>a.id);
      await Promise.all(ids.map(id=>fetch('/api/assignments/'+id,{method:'DELETE'})));
    }""")
    seeded = pg.evaluate("""async () => {
      const fd = new FormData();
      fd.append('name','P5 filter probe');
      fd.append('target_level','B2');
      const r = await fetch('/api/assignments',{method:'POST',body:fd});
      return await r.json();
    }""")
    seeded_id = str(seeded.get("id"))
    pg.evaluate("navGo('assignments')")   # 2026-10-27: boot default = home
    pg.evaluate("(async () => { await loadAssignments(); })()")
    pg.wait_for_timeout(300)

    # --- ASSIGNMENTS: open the collapsed filter row first ---
    rows_all = pg.evaluate(DATA_ASGN)
    check(f"assignments data rows baseline >0 ({rows_all})", rows_all > 0)
    check("asg: filter row closed at boot",
          pg.evaluate("document.querySelector('#asg-filters').classList.contains('hide')"))
    pg.click("#asg-filter-tgl")
    pg.wait_for_timeout(150)

    pg.fill("#asg-filter-name", "P5 filter probe")
    pg.wait_for_timeout(600)
    r = pg.evaluate(DATA_ASGN)
    check(f"name filter 'P5 filter probe' -> 1 row (got {r})", r == 1)
    pg.fill("#asg-filter-name", "")
    pg.wait_for_timeout(400)

    tps = pg.eval_on_selector_all("#asg-filter-type option", "els=>els.map(e=>e.value)")
    check(f"type filter options built (got {tps})", tps[0] == "" and len(tps) > 1)
    pg.select_option("#asg-filter-type", "oral")
    pg.wait_for_timeout(300)
    via_oral = len([x for x in pg.evaluate("ASSIGNMENTS") if kind(x) == "oral"])
    r_oral = pg.evaluate(DATA_ASGN)
    check(f"type filter oral -> {r_oral} rows (live cache says {via_oral})",
          r_oral == via_oral)
    pg.select_option("#asg-filter-type", "written")
    pg.wait_for_timeout(300)
    via_written = len([x for x in pg.evaluate("ASSIGNMENTS") if kind(x) == "written"])
    r_written = pg.evaluate(DATA_ASGN)
    check(f"type filter written -> {r_written} rows (live cache says {via_written})",
          r_written == via_written)
    # combinable name+type (AND)
    pg.select_option("#asg-filter-type", "oral")
    pg.fill("#asg-filter-name", "P5 filter probe")
    pg.wait_for_timeout(600)
    r_combo = pg.evaluate(DATA_ASGN)
    check("combinable name+type AND: seeded subject is not oral -> 0", r_combo == 0)
    pg.select_option("#asg-filter-type", "")
    pg.fill("#asg-filter-name", "")
    pg.wait_for_timeout(400)

    lvls = pg.eval_on_selector_all("#asg-filter-level option", "els=>els.map(e=>e.value)")
    check(f"level filter options built (got {lvls})", lvls[0] == "" and "B2" in lvls)
    pg.select_option("#asg-filter-level", "B2")
    pg.wait_for_timeout(300)
    via_b2 = len([x for x in pg.evaluate("ASSIGNMENTS") if x.get("target_level") == "B2"])
    r2 = pg.evaluate(DATA_ASGN)
    check(f"level B2 -> {r2} rows (live cache says {via_b2})", r2 == via_b2)

    pg.select_option("#asg-filter-level", "")
    pg.select_option("#asg-filter-type", "")
    pg.click("#asg-filter-clear")
    pg.wait_for_timeout(400)
    check("assignments reset restores all", pg.evaluate(DATA_ASGN) == rows_all)
    check("asg: reset -> badge hidden",
          pg.evaluate("document.querySelector('#asg-ftl-n').classList.contains('hide')"))

    # --- EVALUATIONS ---
    pg.click('#nav button[data-view="history"]')
    pg.wait_for_selector("#hist tbody tr")
    pg.wait_for_timeout(600)
    h_all = pg.evaluate(HIST_ROWS)
    check(f"history data rows baseline >0 ({h_all})", h_all > 0)
    check("hist: filter row closed at boot",
          pg.evaluate("document.querySelector('#hist-filters').classList.contains('hide')"))
    pg.click("#hist-filter-tgl")
    pg.wait_for_timeout(150)
    pg.fill("#hist-title", "Speaking")
    pg.wait_for_timeout(1200)
    h2 = pg.evaluate(HIST_ROWS)
    api_spk = pg.evaluate("""async () => {
      const r = await fetch('/api/analyses?limit=200&title=Speaking');
      return (await r.json()).length;
    }""")
    check(f"history title filter 'Speaking' -> {h2} rows (api {api_spk})", h2 == api_spk)
    pg.click("#hist-clear")
    pg.wait_for_timeout(1000)
    check("history reset restores all", pg.evaluate(HIST_ROWS) == h_all)

    # --- RUBRICS (untouched by P4) ---
    pg.click('#nav button[data-view="rubrics"]')
    pg.wait_for_timeout(400)
    rub_all = pg.eval_on_selector_all(".rub-row", "els=>els.length")
    check(f"rubrics rows baseline >0 ({rub_all})", rub_all > 0)
    pg.fill("#rub-filter-name", "orale")
    pg.wait_for_timeout(600)
    rub2 = pg.eval_on_selector_all(".rub-row", "els=>els.length")
    check(f"rubrics name filter 'orale' -> fewer rows ({rub2}<{rub_all})", 0 < rub2 < rub_all)
    pg.fill("#rub-filter-name", "zzz_no_such_rubric")
    pg.wait_for_timeout(600)
    check("rubrics no-match shows empty message",
          pg.eval_on_selector_all(".rub-row", "els=>els.length") == 0)
    pg.click("#rub-filter-clear")
    pg.wait_for_timeout(400)
    check("rubrics reset restores all",
          pg.eval_on_selector_all(".rub-row", "els=>els.length") == rub_all)

    # --- STUDENTS (untouched by P4) ---
    pg.click('#nav button[data-view="students"]')
    pg.wait_for_timeout(400)
    st_all = pg.evaluate(DATA_STU)
    check(f"students data rows baseline >0 ({st_all})", st_all > 0)
    # pick a name from the live cache and expect exactly that many rows
    st_names = pg.evaluate("STUDENTS.map(s=>s.name)")
    probe_name = st_names[0]
    expected = sum(1 for n in st_names if probe_name.lower() in n.lower())
    pg.fill("#st-filter-name", probe_name)
    pg.wait_for_timeout(600)
    st2 = pg.evaluate(DATA_STU)
    check(f"students name filter '{probe_name[:20]}…' -> {expected} rows (got {st2})",
          st2 == expected and st2 >= 1)
    pg.fill("#st-filter-name", "zzz_no_such_student")
    pg.wait_for_timeout(600)
    check("students no-match -> placeholder message",
          pg.evaluate(DATA_STU) == 0 and
          "filtre" in pg.inner_text("#students tbody"))
    pg.click("#st-filter-clear")
    pg.wait_for_timeout(400)
    check("students reset restores all", pg.evaluate(DATA_STU) == st_all)

    check("no page JS errors", not errors, errors[:3])

    # --- deep link #history: fresh load lands on the list, filter row closed,
    #     opens cleanly (the earlier section left the row open in-page; a hash-
    #     only goto would NOT reload the document, so force a real reload) ---
    pg.goto(BASE + "/#history", wait_until="networkidle")
    pg.reload(wait_until="networkidle")
    ensure_app(pg)
    pg.wait_for_selector("#hist tbody tr")
    pg.wait_for_timeout(800)
    check("deep link #history: on the list",
          not pg.evaluate("document.querySelector('#view-history').classList.contains('hide')")
          and pg.evaluate("document.querySelectorAll('#hist tbody tr').length") > 0)
    check("deep link #history: filter row still closed by default",
          pg.evaluate("document.querySelector('#hist-filters').classList.contains('hide')"))
    pg.click("#hist-filter-tgl")
    check("deep link #history: toggle opens the row",
          not pg.evaluate("document.querySelector('#hist-filters').classList.contains('hide')"))

    # --- 390px: open/close both rows, no overflow ---
    ctx2 = b.new_context(viewport={"width": 390, "height": 844})
    m = ctx2.new_page()
    m.on("pageerror", lambda e: errors.append("390:" + str(e)))
    m.add_init_script("localStorage.setItem('babelgrade-lang','fr')")
    m.goto(BASE, wait_until="networkidle")
    try:
        m.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=15000)
    except Exception:
        m.wait_for_selector("#auth-username", state="visible")
        m.fill("#auth-username", "tibo"); m.fill("#auth-password", TESTPW.pw())
        m.click("#auth-login-btn")
        m.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    m.wait_for_timeout(500)
    m.evaluate("navGo('assignments')")   # 2026-10-27: boot default = home
    m.click("#asg-filter-tgl")
    ov = m.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    check("390: asg row open, no overflow", ov <= 0, ov)
    m.click('#nav button[data-view="history"]')
    m.wait_for_selector("#hist-cards .hcard")
    m.click("#hist-filter-tgl")
    ov = m.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    check("390: hist row open, no overflow", ov <= 0, ov)
    ctx2.close()

    # teardown
    pg.evaluate("async (id)=>{ await fetch('/api/assignments/'+id,{method:'DELETE'}) }", seeded_id)
    b.close()

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
