"""Screenshot: oral annotation (audio player + timestamped transcript).

Uses analysis 551 (Hugo Diallo, 7 segments, B1).
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
    pg.goto(BASE + "/#history/551", wait_until="networkidle")
    pg.wait_for_timeout(2500)
    pg.evaluate("document.querySelector('#hist-report [data-annot-open]')?.click()")
    pg.wait_for_timeout(3000)
    state = pg.evaluate("""() => {
        const an = document.getElementById('annot');
        const oral = document.getElementById('an-oral');
        return {
            open: an && !an.hidden,
            oralShown: oral && !oral.hidden,
            segs: oral.querySelectorAll('.an-tseg').length,
            hasAudio: !!oral.querySelector('audio[src]'),
            panelTitle: (document.getElementById('an-panel-title')||{}).textContent,
        };
    }""")
    print("state:", state)
    if not state.get("open") or state.get("segs", 0) < 3:
        print("ABORT — oral annoter did not render", state)
        b.close(); pw.stop()
        return
    # Select segments 2..4 (click segment anchor, then extend)
    pg.evaluate("""() => {
        const segs = document.querySelectorAll('#an-oral .an-tseg');
        segs[1]?.dispatchEvent(new MouseEvent('click', {bubbles: true}));
        segs[3]?.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    }""")
    pg.wait_for_timeout(600)
    # Enrich the marker: sticker 👍 + level B1 + note
    pg.evaluate("""() => {
        const stickers = document.querySelectorAll('#an-stickers button');
        stickers[0]?.click();
        const lvl = document.getElementById('an-level');
        if (lvl) { lvl.value = 'B1'; lvl.dispatchEvent(new Event('change', {bubbles:true})); }
        const note = document.getElementById('an-note');
        if (note) { note.value = 'Argumentation structurée, débit fluide'; }
    }""")
    pg.wait_for_timeout(500)
    pg.evaluate("document.getElementById('annot').scrollIntoView()")
    pg.wait_for_timeout(400)
    pg.screenshot(path=os.path.join(OUT, "oral-annotation.png"), full_page=False)
    print("saved oral-annotation.png")
    if errs:
        print("JS ERRORS:", errs[:5])
    b.close(); pw.stop()


if __name__ == "__main__":
    main()
