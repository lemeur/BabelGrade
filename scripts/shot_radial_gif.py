"""Animated GIF: home radial menu — slow tour of EVERY menu item.

Timeline (~6.5 s, deliberately slow so each label can be read):
  - boot on #home, menu auto-opens (L0: Évaluer / Analyser / Préparer)
  - hold L0
  - pick Évaluer -> its L1 sub-crown fans in (Sur sujet / Directe / Historique)
  - cycle the 3 leaves one by one, slow hold on each
  - pick Analyser -> old sub-crown folds away, new one fans in
    (Élèves / Sujets / Grilles) — cycle its 3 leaves
  - pick Préparer -> (Classe / élèves, Importer la classe, Sujets)
    — cycle its 3 leaves
  - close the menu back on the home hero

Regenerate with:
  /tmp/bg_venv/bin/python scripts/shot_radial_gif.py
(Server must be running on http://127.0.0.1:8090)
"""
import os
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shot_common import make_page, login, OUT

FRAMES_DIR = tempfile.mkdtemp(prefix="bg_radial_")
frames = []       # file paths, in order
durations = []    # ms per frame, parallel list


def shoot(pg, name, pre_ms=0, dur_ms=110):
    """Wait pre_ms, capture one viewport frame, remember its display duration."""
    if pre_ms:
        pg.wait_for_timeout(pre_ms)
    p = os.path.join(FRAMES_DIR, f"{name}.png")
    pg.screenshot(path=p, full_page=False)
    frames.append(p)
    durations.append(dur_ms)
    return p


def hold(pg, n, dur_ms=130, pre_ms=0, prefix="hold"):
    for i in range(n):
        shoot(pg, f"{prefix}{i:02d}", pre_ms if i == 0 else 0, dur_ms)


def main():
    pw, b, ctx, pg = make_page(lang="en", width=390, height=844)
    errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    login(pg)
    # Boot lands on #home and the menu auto-opens via rAF (L0 entry:
    # stagger 60+i*190ms + .5s -> settles ~0.95 s)
    pg.wait_for_function("""() => {
        const c = document.querySelector('#pie-stage .crown[data-lv="0"]');
        return !!(c && c.querySelectorAll('.sector').length >= 3);
    }""", timeout=15000)
    pg.wait_for_timeout(1400)  # let the entry animation settle
    st = pg.evaluate("""() => ({
        open: RST.open,
        crowns: [...document.querySelectorAll('#pie-stage .crown')].map(g => g.dataset.lv),
        selected: RST.sel
    })""")
    print("L0 state:", st)
    if not st.get("open"):
        print("ABORT — menu not open")
        b.close(); pw.stop()
        return

    # hold L0
    hold(pg, 4, 110, 0, "l0")

    # Tour each verb: pick it (its L1 fans in), hold, then cycle the 3
    # leaves slowly one by one.
    verbs = [0, 1, 2]
    for v in verbs:
        # Pick the verb at L0 -> its sub-crown enters (stagger 60+i*190ms
        # + .5s, so ~0.95 s; the previous verb's L1 folds out in parallel).
        pg.evaluate(f"rPick(0, {v})")
        # sample the fan-in (~10 frames cover the 0.95 s entry)
        for i in range(10):
            shoot(pg, f"fan{v}_{i:02d}", 30 if i == 0 else 0, 95)
        # hold the open sub-crown
        hold(pg, 2, 140, 0, f"open{v}")
        # cycle its 3 leaves, slow hold on each (L1 starts unselected:
        # first rCycle(1) selects item 0)
        for leaf in range(3):
            pg.evaluate("rCycle(1)")
            st = pg.evaluate("""() => ({
                sel: RST.sel,
                l1: [...document.querySelectorAll('#pie-stage g.crown[data-lv="1"]:not([data-exit]) .sector')]
                     .map(s => ({idx: s.dataset.idx, sel: s.classList.contains('selected')}))
            })""")
            print(f"verb {v} leaf {leaf}:", st)
            hold(pg, 3, 120, 150, f"leaf{v}_{leaf}")

    # end: close the menu back on the home hero
    pg.evaluate("pieClose()")
    hold(pg, 3, 160, 0, "end")

    if errs:
        print("JS ERRORS:", errs[:5])
    b.close(); pw.stop()

    # Assemble the GIF with PIL
    from PIL import Image
    imgs = []
    for f in frames:
        imgs.append(Image.open(f).convert("RGB"))
    # downscale to 320w to keep the GIF light (390 -> 320)
    w = 320
    rs = getattr(Image, "Resampling", Image)
    imgs = [im.resize((w, round(im.height * w / im.width)), rs.LANCZOS) for im in imgs]
    q = [im.quantize(colors=128, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
         for im in imgs]
    # Merge frames pixel-identical to the previous one by extending its
    # duration: keeps every captured step visible at its intended pace
    # (no optimize=True, which would silently half the sampled animations)
    # while keeping the file small (static holds become single frames).
    fq, dur = [q[0]], [durations[0]]
    for im, d in zip(q[1:], durations[1:]):
        if im.tobytes() == fq[-1].tobytes():
            dur[-1] += d
        else:
            fq.append(im)
            dur.append(d)
    out = os.path.join(OUT, "radial-menu.gif")
    fq[0].save(
        out,
        save_all=True,
        append_images=fq[1:],
        duration=dur,
        loop=0,
    )
    total_ms = sum(durations)
    print(f"saved radial-menu.gif with {len(frames)} frames, {total_ms} ms, "
          f"{os.path.getsize(out) // 1024} KB")


if __name__ == "__main__":
    main()
