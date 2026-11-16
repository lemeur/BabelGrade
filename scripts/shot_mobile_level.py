"""Screenshot: mobile criterion-by-criterion grading (390px, bottom-sheet level picker).

Analysis 590 (Giulia Romano, att-exp-ecrite, B1, AI opinion blind).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shot_common import make_page, login, OUT, BASE


def main():
    pw, b, ctx, pg = make_page(lang="fr", width=390, height=844)
    errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    login(pg)
    pg.goto(BASE + "/#history/590", wait_until="networkidle")
    pg.wait_for_timeout(2500)
    # Find the attestation table + open the bottom sheet on criterion #1
    st = pg.evaluate("""() => {
        const att = document.querySelector('#hist-report .att-card');
        const pill = document.querySelector('#hist-report .att-lvl-pill');
        if (!att) return {att: false};
        if (pill) pill.click();
        att.scrollIntoView({block: 'start'});
        window.scrollBy(0, -70);   // keep the detail header visible a bit
        return {
            att: true,
            pills: document.querySelectorAll('#hist-report .att-lvl-pill').length,
            sheet: document.getElementById('lvl-sheet').classList.contains('show'),
            sheetTitle: (document.getElementById('ls-title')||{}).textContent,
            sheetBtns: document.querySelectorAll('#ls-grid .lvl-sheet-btn').length,
            cur: (document.querySelector('#hist-report .att-lvl')||{}).value
        };
    }""")
    print("state:", st)
    pg.wait_for_timeout(600)
    # Hide the closed #eval-ai bottom sheet (fixed, would render as a stray band)
    pg.evaluate("""() => {
        const sh = document.getElementById('eval-ai');
        if (sh && !sh.classList.contains('show')) sh.style.display = 'none';
    }""")
    pg.wait_for_timeout(300)
    pg.screenshot(path=os.path.join(OUT, "mobile-level-picker.png"), full_page=False)
    print("saved mobile-level-picker.png")
    if errs:
        print("JS ERRORS:", errs[:5])
    b.close(); pw.stop()


if __name__ == "__main__":
    main()
