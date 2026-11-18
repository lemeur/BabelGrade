"""Screenshot: AI analysis report (history detail, desktop 1280px)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shot_common import make_page, login, OUT


def main():
    pw, b, ctx, pg = make_page(lang="en", width=1280, height=900)
    errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    login(pg)
    # Deep-link to history detail of analysis 590 (rich AI report, FR)
    pg.goto("http://127.0.0.1:8090/#history/590", wait_until="networkidle")
    pg.wait_for_timeout(2500)
    # Expand every criterion row so justifications + verbatim evidence are visible
    pg.evaluate("""() => {
        document.querySelectorAll('#hist-report .att-main-row').forEach(r => r.classList.add('open'));
        // closed fixed bottom sheet would render as a stray band in full-page shots
        const sh = document.getElementById('eval-ai');
        if (sh) sh.style.display = 'none';
        const ls = document.getElementById('lvl-sheet');
        if (ls) ls.style.display = 'none';
    }""")
    # Verify the detail header + attestation card are present
    ok = pg.evaluate("""() => {
        const det = document.querySelector('#hist-report');
        return {
            hasDetail: !!(det && det.innerHTML.length > 500),
            att: !!document.querySelector('.att-card'),
            aiBanner: !!document.querySelector('.ai-banner-card'),
            openRows: document.querySelectorAll('#hist-report .att-main-row.open').length,
            detailText: (det||{textContent:''}).textContent.slice(0,120)
        };
    }""")
    print("state:", ok)
    pg.wait_for_timeout(500)
    pg.evaluate("window.scrollTo(0,0)")
    pg.wait_for_timeout(300)
    pg.screenshot(path=os.path.join(OUT, "ai-analysis-report.png"), full_page=False)
    print("saved ai-analysis-report.png")
    if errs:
        print("JS ERRORS:", errs[:5])
    pg.screenshot(path=os.path.join(OUT, "ai-analysis-report-full.png"), full_page=True)
    print("saved ai-analysis-report-full.png")
    b.close(); pw.stop()


if __name__ == "__main__":
    main()
