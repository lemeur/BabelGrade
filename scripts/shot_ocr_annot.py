"""Screenshot: OCR annotation dual-pane (written copy photo + OCR lines).

Uses analysis 590 / submission 600 (Giulia Romano, llm-direct OCR, 8 lines).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shot_common import make_page, login, OUT, BASE


def main():
    pw, b, ctx, pg = make_page(lang="fr", width=1440, height=900)
    errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    login(pg)
    pg.goto(BASE + "/#history/590", wait_until="networkidle")
    pg.wait_for_timeout(2500)
    # Click the "Annoter la copie" button in the report action row
    pg.evaluate("""() => {
        document.querySelector('#hist-report [data-annot-open]')?.click();
    }""")
    pg.wait_for_timeout(3000)  # OCR fetch + render
    state = pg.evaluate("""() => {
        const an = document.getElementById('annot');
        const written = document.getElementById('an-written');
        return {
            open: an && !an.hidden,
            dual: written.querySelectorAll('.an-dual').length,
            lines: written.querySelectorAll('.lc, .an-line, [class*=line]').length,
            boxes: written.querySelectorAll('.ph-box, .an-box').length,
            img: written.querySelectorAll('img').length,
            panelTitle: (document.getElementById('an-panel-title')||{}).textContent,
            hintText: (document.getElementById('an-hint')||{}).textContent,
            bodyH: document.body.scrollHeight
        };
    }""")
    print("state:", state)
    if not state.get("open") or not state.get("boxes"):
        print("ABORT — annoter did not render", state)
        b.close(); pw.stop()
        return
    # Select a real multi-line word range: first word of line 2 -> last word of line 4
    pg.evaluate("""() => {
        const words = document.querySelectorAll('#an-written .an-w');
        // group word spans by their line card
        const byLine = {};
        words.forEach(w => {
            const card = w.closest('.line-card');
            const li = card ? +card.dataset.line : -1;
            if (li >= 0) (byLine[li] = byLine[li] || []).push(w);
        });
        const lines = Object.keys(byLine).map(Number).sort((a,b)=>a-b);
        const start = byLine[lines[1]]?.[0];
        const endLine = byLine[lines[3]] || byLine[lines[lines.length-1]];
        const end = endLine?.[endLine.length-1];
        start?.click();
        end?.click();
        return {lines, clicked: !!(start && end)};
    }""")
    pg.wait_for_timeout(900)
    # Enrich the marker: sticker 👍 + level B1 + a teacher note
    pg.evaluate("""() => {
        const stickers = document.querySelectorAll('#an-stickers button');
        stickers[0]?.click();   // 👍 (ANNOT_STICKERS[0])
        const lvl = document.getElementById('an-level');
        if (lvl) { lvl.value = 'B1'; lvl.dispatchEvent(new Event('change', {bubbles:true})); }
        const note = document.getElementById('an-note');
        if (note) { note.value = 'Belle argumentation, connecteurs bien utilisés'; }
    }""")
    pg.wait_for_timeout(500)
    pg.evaluate("document.getElementById('annot').scrollIntoView()")
    pg.wait_for_timeout(400)
    pg.screenshot(path=os.path.join(OUT, "ocr-annotation.png"), full_page=False)
    print("saved ocr-annotation.png")
    if errs:
        print("JS ERRORS:", errs[:5])
    b.close(); pw.stop()


if __name__ == "__main__":
    main()
