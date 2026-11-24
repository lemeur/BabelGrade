"""V5-C3 live E2E: queue position rendered in the Jobs view + follow card.

Plan:
 1. POST /api/jobs/settings max_workers=1 (legit endpoint)
 2. enqueue job A (analyze, short text) -> running
 3. enqueue job B (analyze, short text) -> queued, queue_pos 1
 4. Playwright (FR): Jobs view -> row B pill shows 'n°1'; open B follow card
    -> meta shows 'En file n°1'
 5. cancel job B; let job A finish
 6. POST /api/jobs/settings max_workers=3
"""
import _testpw as TESTPW
import time
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8090"
PASS, FAIL = [], []

def check(n, c, x=""):
    (PASS if c else FAIL).append(n)
    print(("PASS " if c else "FAIL ") + n + (f" | {x}" if x and not c else ""))

TEXT = ("In my opinion, online learning has many advantages. First, students "
        "can study at their own pace and choose flexible schedules. Second, "
        "they can access many resources such as videos and documents. However, "
        "it can be difficult to stay motivated without a teacher nearby.")

def login(pg, lang="fr"):
    pg.add_init_script(f"localStorage.setItem('babelgrade-lang','{lang}')")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", TESTPW.pw())
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)

def set_workers(pg, n):
    # data= sends a JSON body — matches set_job_settings(payload: dict).
    r = pg.request.post(BASE + "/api/jobs/settings", data={"max_workers": n})
    assert r.ok, r.text()
    return r.json()

def enqueue(pg, title):
    # form= (NOT data=): data= sends a JSON body, FastAPI Form params need urlencoded.
    fd = pg.request.post(BASE + "/api/analyze", form={
        "written_text": TEXT, "rubric_id": "att-exp-ecrite",
        "title": title, "ui_language": "fr"})
    assert fd.ok, fd.text()
    return fd.json()

with sync_playwright() as pw:
    ctx = pw.chromium.launch(headless=True).new_context(
        viewport={"width": 1280, "height": 800}, locale="fr-FR")
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
    login(pg)

    # 1. workers = 1
    j = set_workers(pg, 1)
    check("max_workers set to 1", j.get("max_workers") == 1, str(j))

    # 2. job A -> running
    a = enqueue(pg, "v5-c3 A")
    check("job A enqueued", a.get("job_id"), str(a))
    pg.wait_for_timeout(1500)  # let the scheduler claim it

    # 3. job B -> queued
    b = enqueue(pg, "v5-c3 B")
    check("job B enqueued", b.get("job_id"), str(b))
    pg.wait_for_timeout(800)

    # 4a. Jobs view: row B shows 'n°1'
    pg.evaluate("navGo('jobs')")
    pg.wait_for_timeout(1200)
    rows = pg.evaluate("""(bid)=>{
      const trs=[...document.querySelectorAll('#jobs tbody tr')];
      const out={};
      for(const tr of trs){
        const id=tr.cells[0].textContent.trim();
        out[id]={status:tr.cells[2].textContent.trim(),
                pillHtml:tr.cells[2].innerHTML.slice(0,200)};
      }
      return out[bid]||null;}""", b["job_id"])
    check("jobs row B pill shows n°1", rows and "n°1" in (rows.get("pillHtml") or ""),
          str(rows))
    # job A is running (no position)
    rowA = pg.evaluate("""(aid)=>{const tr=[...document.querySelectorAll('#jobs tbody tr')]
      .find(t=>t.cells[0].textContent.trim()==aid);
      return tr?{status:tr.cells[2].textContent.trim(),pill:tr.cells[2].innerHTML.slice(0,120)}:null;}""",
      str(a["job_id"]))
    check("jobs row A running has no n°", rowA and "n°" not in (rowA.get("pill") or ""),
          str(rowA))

    # 4b. follow card for B: meta shows 'En file n°1'
    pg.evaluate("""(bid)=>{const b=document.querySelector(`[data-jfollow="${bid}"]`);if(b)b.click();}""",
      b["job_id"])
    pg.wait_for_selector("#job-follow:not(.hide)", state="visible", timeout=8000)
    pg.wait_for_timeout(1000)
    meta = pg.evaluate("document.querySelector('#job-follow-meta').textContent")
    check("follow card B shows 'En file n°1'", "En file n°1" in meta, meta[:160])

    # 5. cancel B, let A run to done
    pg.evaluate("""(bid)=>{const b=document.querySelector(`[data-jcancel="${bid}"]`);if(b)b.click();}""",
      b["job_id"])
    pg.wait_for_timeout(500)
    stB = pg.evaluate("""(bid)=>{const tr=[...document.querySelectorAll('#jobs tbody tr')]
      .find(t=>t.cells[0].textContent.trim()==bid);
      return tr?tr.cells[2].textContent.trim():null;}""", b["job_id"])
    check("job B cancelled", "Annul" in stB, stB)

    # wait for A to finish (short text -> 60-130 s). Poll the API, NOT the DOM:
    # the Jobs table re-renders only on refresh/filter, and the follow card is
    # open, so a DOM `wait_for_function` could hang even after the job is done.
    deadline = time.time() + 240
    stA = None
    while time.time() < deadline:
        jA = pg.request.get(f"{BASE}/api/jobs/{a['job_id']}").json()
        stA = jA.get("status")
        if stA in ("done", "error", "cancelled"):
            break
        pg.wait_for_timeout(1500)
    check("job A reached done", stA == "done", str(stA))

    # 6. workers back to 3
    j = set_workers(pg, 3)
    check("max_workers restored to 3", j.get("max_workers") == 3, str(j))

    check("0 page errors", len(errors) == 0, str(errors))
    ctx.close()

print("\n===== V5 C3 UI E2E =====")
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FAILURES:", FAIL)
    raise SystemExit(1)
