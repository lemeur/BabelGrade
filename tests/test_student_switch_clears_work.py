"""Student switch must clear the previous student's work — live E2E.

Regression test for the bug (2026-11-21): after evaluating student A (written,
copy photos), starting a new evaluation for student B kept student A's copy
photos "selected by default" for B — currenasgnFiles / #written-text /
currentAudio are module-level state that nothing reset on a #student change.

Flow (no LLM involved, no data kept):
 1. log in, open the evaluator
 2. make sure ≥2 students exist (create two throwaway ones, else reuse)
 3. pick student A + attach a synthetic PNG photo + paste text
 4. switch to student B → the photo thumbnails, pasted text and (oral) audio
    must all be cleared, while the task-level context (card 1) is untouched
 5. clean up the throwaway students

Run (live server on :8090 required):
  /tmp/bg_venv/bin/python tests/test_student_switch_clears_work.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _testpw as T
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8090"
# 1x1 red PNG
PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNg"
       "YmKGCWQaj0CsAwBxfwJvQ6nQAAAABklEQVR4nGMAAQAABQAA"
       "hQdP2AAAAABJRU5ErkJggg==")
import base64
PNG_BYTES = base64.b64decode(PNG)

FAILS = []
TOTAL = 0
def check(name, ok, extra=""):
    global TOTAL
    TOTAL += 1
    print(("PASS " if ok else "FAIL ") + name + (f"  [{extra}]" if extra and not ok else ""))
    if not ok: FAILS.append(name)

def login(pg):
    pg.goto(BASE, wait_until="networkidle")
    pg.fill("#auth-username", T.USERNAME); pg.fill("#auth-password", T.pw())
    pg.click("#auth-login-btn"); pg.wait_for_timeout(900)
    assert pg.evaluate("document.getElementById('auth-gate').classList.contains('hide')")

def set_student(pg, name):
    """Pick the student named `name` in the evaluator's #student select."""
    pg.evaluate("""(n)=>{ const sel=document.getElementById('student');
      const o=[...sel.options].find(o=>o.textContent.includes(n));
      if(!o)throw new Error('student not in select: '+n);
      sel.value=o.value;
      sel.dispatchEvent(new Event('change',{bubbles:true})); }""", name)

def ensure_students(pg, a, b):
    """Create the two throwaway students if they don't exist yet."""
    for n in (a, b):
        pg.evaluate("""async(n)=>{ const list=await (await fetch('/api/students')).json();
          if(!list.some(s=>s.name===n)){
            await fetch('/api/students',{method:'POST',headers:{'Content-Type':'application/json'},
              body:JSON.stringify({name:n,classroom:'29/99-ZIA-T'})}); } }""", n)
    pg.evaluate("async()=>{ /* rebuild the evaluator's select from the API */ "
                "return loadStudents(); }")
    pg.wait_for_timeout(200)

def main():
    pw = sync_playwright().start()
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width":1280,"height":860}, locale="en-US")
    pg = ctx.new_page(); errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    A, B = "ZiaTest Alice", "ZiaTest Bob"
    try:
        login(pg)
        # open the evaluator view (boot view is #home where the header is hidden)
        pg.evaluate("goEvaluate()"); pg.wait_for_timeout(400)
        check("evaluator visible",
              not pg.evaluate("document.getElementById('view-analyze').classList.contains('hide')"))

        ensure_students(pg, A, B)

        # --- student A: attach a photo + paste text (written mode) ---
        # the copy field is a mode-field engine panel; photo is its default mode
        check("copy field defaults to photo mode",
              pg.evaluate("document.getElementById('mctrl-copy') && "
                          "document.querySelector('#mctrl-copy button.on').dataset.mmode") == 'photo')
        set_student(pg, A)
        a_id = pg.evaluate("$('#student').value")
        check("student A selected", bool(a_id))
        # drive the real engine path: the hidden #img-file input inside the
        # photo panel; its onchange (mAddPhotos + renderThumbs) does the rest
        png_path = ROOT / "tests" / "_zia_copy_p1.png"
        png_path.write_bytes(PNG_BYTES)
        pg.set_input_files("#img-file", str(png_path))
        pg.wait_for_timeout(150)
        # switch to text mode (photo is the default) so fill can reach the
        # engine-created #written-text textarea
        pg.evaluate("setMMode('copy','text')")
        pg.fill("#written-text", "ALICE_WORK_TEXT")
        n_thumbs = pg.evaluate("document.querySelectorAll('#mpanel-copy-photo .mthumbs .mthumb img').length")
        check("student A: photo attached (1 thumb)", n_thumbs == 1, "thumbs=" + str(n_thumbs))
        check("student A: currenasgnFiles has 1 file",
              pg.evaluate("currenasgnFiles.length") == 1)

        # --- switch to student B ---
        set_student(pg, B)
        b_id = pg.evaluate("$('#student').value")
        check("student B selected (value != A's)", bool(b_id) and b_id != a_id,
              f"a={a_id} b={b_id}")
        n_thumbs = pg.evaluate("document.querySelectorAll('#mpanel-copy-photo .mthumbs .mthumb img').length")
        check("student B: photo CLEARED (0 thumbs)", n_thumbs == 0, "thumbs=" + str(n_thumbs))
        check("student B: currenasgnFiles EMPTY", pg.evaluate("currenasgnFiles.length") == 0)
        check("student B: pasted text CLEARED",
              pg.evaluate("document.getElementById('written-text').value") == "")
        check("student B: #img-file input value cleared",
              pg.evaluate("document.getElementById('img-file').value") in ("", None))
        check("student B: no audio state", pg.evaluate("currentAudio") is None)

        # --- task-level context must be PRESERVED on student switch ---
        # (card-1 textareas are mode-field-engine hidden panels → set via JS)
        pg.evaluate("""()=>{ document.getElementById('instruction').value='KEEP_THIS_INSTRUCTION';
          document.getElementById('doc-text').value='KEEP_THIS_DOC'; }""")
        set_student(pg, A)  # switch back and forth
        check("instruction preserved on switch",
              pg.evaluate("document.getElementById('instruction').value") == "KEEP_THIS_INSTRUCTION")
        check("doc text preserved on switch",
              pg.evaluate("document.getElementById('doc-text').value") == "KEEP_THIS_DOC")
        check("rubric preserved on switch",
              pg.evaluate("document.getElementById('rubric').value") != "")

        # --- switching to 'none' must also clear the work ---
        pg.evaluate("""()=>{ const sel=document.getElementById('student');
          sel.value=''; sel.dispatchEvent(new Event('change',{bubbles:true})); }""")
        check("none: work cleared too",
              pg.evaluate("currenasgnFiles.length") == 0 and
              pg.evaluate("document.getElementById('written-text').value") == "")

        js_errs = [e for e in errs if "favicon" not in e.lower()]
        check("no JS console errors", not js_errs, str(js_errs[:3]))

    finally:
        # cleanup: temp photo fixture + throwaway students (no cascade needed)
        try:
            (ROOT / "tests" / "_zia_copy_p1.png").unlink(missing_ok=True)
        except Exception:
            pass
        for n in (A, B):
            try:
                pg.evaluate("""async(n)=>{ const list=await (await fetch('/api/students')).json();
                  const s=list.find(x=>x.name===n);
                  if(s)await fetch('/api/students/'+s.id,{method:'DELETE'}); }""", n)
            except Exception:
                pass
        pg.close(); b.close(); pw.stop()

    print("\n%d/%d checks passed" % (TOTAL - len(FAILS), TOTAL))
    print("FAILED:", FAILS if FAILS else "none")
    sys.exit(1 if FAILS else 0)

if __name__ == "__main__":
    main()
