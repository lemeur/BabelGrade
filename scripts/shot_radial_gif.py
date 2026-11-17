"""Animated GIF: home radial menu — L0 verbs, fan-out of the L1 sub-crown,
then a leaf pick (Historique) that closes the menu.

Timeline (~3.5 s):
  - boot on #home, menu auto-opens (L0: Évaluer / Analyser / Préparer)
  - hold L0
  - rCycle(1) -> Évaluateur selected at L0, L1 sub-crown fans in (staggered)
  - sample the fan-out animation
  - hold L1 stable
  - rPick(1,2) -> "Historique" leaf -> menu closes, history view loads
"""
import os
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shot_common import make_page, login, OUT

FRAMES_DIR = tempfile.mkdtemp(prefix="bg_radial_")


def shoot(pg, name, hold_ms=0):
    pg.wait_for_timeout(hold_ms)
    p = os.path.join(FRAMES_DIR, f"{name}.png")
    pg.screenshot(path=p, full_page=False)
    return p


def main():
    pw, b, ctx, pg = make_page(lang="fr", width=390, height=844)
    errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    login(pg)
    # Boot lands on #home and the menu auto-opens via rAF
    frames = []
    # wait for the L0 crown to exist and finish entering
    pg.wait_for_function("""() => {
        const c = document.querySelector('#pie-stage .crown[data-lv="0"]');
        return !!(c && c.querySelectorAll('.sector').length >= 3);
    }""", timeout=15000)
    pg.wait_for_timeout(1400)  # let the entry animation settle
    st = pg.evaluate("""() => ({
        open: RST.open,
        crowns: [...document.querySelectorAll('#pie-stage .crown')].map(g => g.dataset.lv),
        selected: RST.sel,
        center: (document.getElementById('pie-center')||{}).textContent
    })""")
    print("L0 state:", st)
    if not st.get("open"):
        print("ABORT — menu not open")
        b.close(); pw.stop()
        return

    # hold L0 (3 frames)
    for i in range(3):
        frames.append(shoot(pg, f"f{i:02d}", 110))

    # select Évaluer at L0 -> L1 sub-crown fans in
    pg.evaluate("rCycle(1)")
    # sample the fan-out (stagger ~190ms per card, ~330ms duration)
    for i in range(8):
        frames.append(shoot(pg, f"fan{i:02d}", 95))

    # hold L1 stable (3 frames)
    st2 = pg.evaluate("""() => ({
        crowns: [...document.querySelectorAll('#pie-stage .crown')].map(g => g.dataset.lv),
        sel: RST.sel,
        l1selected: [...document.querySelectorAll('#pie-stage .crown[data-lv="1"] .sector')].map(s => s.classList.contains('selected'))
    })""")
    print("L1 state:", st2)
    for i in range(3):
        frames.append(shoot(pg, f"hold{i:02d}", 110))

    # pick the leaf "Évaluer directement" (L1 index 1) -> menu closes, evaluator form
    pg.evaluate("rPick(1, 1)")
    frames.append(shoot(pg, "close0", 120))
    frames.append(shoot(pg, "close1", 150))
    frames.append(shoot(pg, "eval", 900))   # evaluator form settled
    frames.append(shoot(pg, "eval2", 200))

    if errs:
        print("JS ERRORS:", errs[:5])
    b.close(); pw.stop()

    # Assemble the GIF with PIL
    from PIL import Image
    imgs = []
    for f in frames:
        im = Image.open(f).convert("RGB")
        imgs.append(im)
    # downscale to 320w to keep the GIF light (390 -> 320)
    w = 320
    rs = getattr(Image, "Resampling", Image)
    imgs = [im.resize((w, round(im.height * w / im.width)), rs.LANCZOS) for im in imgs]
    q = [im.quantize(colors=128, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE) for im in imgs]
    q[0].save(
        os.path.join(OUT, "radial-menu.gif"),
        save_all=True,
        append_images=q[1:],
        duration=[110] * 3 + [95] * 8 + [110] * 3 + [120, 150, 900, 200],
        loop=0,
        optimize=True,
    )
    print("saved radial-menu.gif with", len(frames), "frames")


if __name__ == "__main__":
    main()
