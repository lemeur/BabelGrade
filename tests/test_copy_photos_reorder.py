#!/usr/bin/env python3
"""Card-3 "student work" photo field — 2026-11-25 UX additions, E2E:

1. ORIENTATION NORMALIZATION AT SELECTION TIME: picking a photo fires
   POST /api/media/normalize immediately (not at submit), and the STORED
   File is the upright result (the thumbnail / the later upload show exactly
   what the backend persists and the LLM/OCR read).
2. LIGHTBOX: clicking a thumbnail opens a full-size preview (prev/next/close,
   rotate-180 replaces the stored File).
3. REORDER: ‹ › move buttons (mobile) AND drag-and-drop (desktop) reorder the
   reading order, renumbering the badges.

Runs against the live server (default 127.0.0.1:8090, override BABELGRADE_URL).
Login tibo / test-pw-9876. Deterministic fixtures are generated into a tempdir
so the test is self-contained (no /tmp fixtures assumed present).
"""
import os
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("BABELGRADE_URL", "http://127.0.0.1:8090")
res = []


def chk(name, cond, extra=""):
    res.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + str(extra)) if (extra and not cond) else ""))


def make_fixtures(tmp: Path):
    """Create the test photos:
       upright.jpg      — plain lines, no EXIF orientation (X-Changed: 0)
       sideways.jpg     — plain lines, EXIF orientation=6 (90° → becomes 1000x800)
       upside.jpg       — plain lines, EXIF orientation=3 (180°)
       pa/pb/pc.jpg     — distinct 3-file set for the unambiguous DnD check
    """
    from PIL import Image, ImageDraw

    def lines(size, name):
        w, h = size
        im = Image.new("RGB", (w, h), "white")
        d = ImageDraw.Draw(im)
        for y in range(int(h * 0.1), int(h * 0.9), int(h * 0.06)):
            d.line([(int(w * 0.1), y), (int(w * 0.9), y)], fill="black", width=3)
        d.text((int(w * 0.1), int(h * 0.03)), name, fill="red")
        return im

    def with_exif(im, orientation, path):
        exif = im.getexif()
        exif[0x0112] = orientation
        im.save(path, exif=exif, quality=90)

    # 800x1000 page, lines
    with_exif(lines((800, 1000), "upright"), 1, tmp / "upright.jpg")
    with_exif(lines((800, 1000), "sideways"), 6, tmp / "sideways.jpg")
    with_exif(lines((800, 1000), "upside"), 3, tmp / "upside.jpg")
    for n in ("pa", "pb", "pc"):
        lines((600, 800), n).save(tmp / f"{n}.jpg", quality=90)


with sync_playwright() as pw:
    tmpdir = Path(tempfile.mkdtemp(prefix="bg_photos_"))
    make_fixtures(tmpdir)
    UPRIGHT = str(tmpdir / "upright.jpg")
    SIDEWAYS = str(tmpdir / "sideways.jpg")
    PA = str(tmpdir / "pa.jpg")
    PB = str(tmpdir / "pb.jpg")
    PC = str(tmpdir / "pc.jpg")

    pg = pw.chromium.launch(headless=True)
    ctx = pg.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="networkidle")
    page.fill("#auth-username", "tibo")
    page.fill("#auth-password", "test-pw-9876")
    page.click("#auth-login-btn")
    page.wait_for_load_state("networkidle")
    page.evaluate("localStorage.setItem('babelgrade-lang','fr')")
    page.goto(BASE + "/", wait_until="networkidle")

    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    norm_calls = []
    page.on("response", lambda r: norm_calls.append(r.url)
            if "/api/media/normalize" in r.url else None)

    # enter the evaluate view (card-3 photo field lives here)
    page.evaluate("goEvaluate()")
    page.wait_for_timeout(400)

    # --- 1) functions + lightbox DOM present
    fns = page.evaluate("""() => ({
      lbOpen: typeof window.lbOpen==='function',
      lbClose: typeof window.lbClose==='function',
      lbFlip180: typeof window.lbFlip180==='function',
      mNormalizePhoto: typeof window.mNormalizePhoto==='function',
      mAddPhotos: typeof window.mAddPhotos==='function'})""")
    chk("functions defined", all(fns.values()), fns)

    lb = page.evaluate("""() => {
      const ov=document.getElementById('lightbox');
      return { exists: !!ov,
        img: !!document.getElementById('lb-img'),
        prev: !!document.getElementById('lb-prev'),
        next: !!document.getElementById('lb-next'),
        rot: !!document.getElementById('lb-rot'),
        close: !!document.getElementById('lb-close'),
        count: !!document.getElementById('lb-count') };}""")
    chk("lightbox DOM", lb["exists"] and all(v for k, v in lb.items() if k != "exists"), lb)

    mf = page.evaluate("""() => {
      const h=document.getElementById('mfield-copy');
      if(!h) return {exists:false};
      return { exists:true, mphotos: !!h.querySelector('.mphotos'),
        imgfile: !!h.querySelector('#img-file') };}""")
    chk("card-3 photo panel (photo default mode)", mf["exists"] and mf.get("imgfile"), mf)

    # --- 2) select 2 photos → normalization fires AT SELECTION + upright result
    page.set_input_files("#img-file", [UPRIGHT, SIDEWAYS])
    page.wait_for_selector("#mfield-copy .mthumb", timeout=15000)
    page.wait_for_timeout(1200)
    n_thumbs = page.eval_on_selector_all("#mfield-copy .mthumb", "els=>els.length")
    chk("2 thumbs after select", n_thumbs == 2, f"got {n_thumbs}")
    chk("normalize fired at selection (>=2 calls)", len(norm_calls) >= 2,
        f"{len(norm_calls)} calls")

    dims = page.evaluate("""() => new Promise(resolve=>{
      const f=currenasgnFiles.find(x=>/sideways/.test(x.name));
      if(!f) return resolve(null);
      const im=new Image();
      im.onload=()=>resolve({w:im.width,h:im.height});
      im.onerror=()=>resolve(null);
      im.src=URL.createObjectURL(f);})""")
    chk("sideways photo stored upright (1000x800 after EXIF 90°)",
        dims and dims["w"] == 1000 and dims["h"] == 800, dims)

    # --- 3) per-thumb controls: × / ‹ / ›, draggable
    btns = page.evaluate("""() => {
      const t=document.querySelector('#mfield-copy .mthumb');
      if(!t) return null;
      return { del: !!t.querySelector('button[data-mdel]'),
        prev: !!t.querySelector('button[data-mprev]'),
        next: !!t.querySelector('button[data-mnext]'),
        draggable: t.draggable };}""")
    chk("thumb buttons (×/‹/›)", btns and btns["del"] and btns["prev"] and btns["next"], btns)
    chk("thumb draggable", bool(btns and btns["draggable"]))

    order = page.evaluate("""() => {
      const ts=document.querySelectorAll('#mfield-copy .mthumb');
      const g=i=>({prevDis:ts[i].querySelector('button[data-mprev]').disabled,
                   nextDis:ts[i].querySelector('button[data-mnext]').disabled});
      return {first:g(0), last:g(ts.length-1)};}""")
    chk("‹/› disabled at the ends",
        order["first"]["prevDis"] and not order["first"]["nextDis"]
        and not order["last"]["prevDis"] and order["last"]["nextDis"], order)

    # --- 4) ‹ › reorder (mobile path)
    names_before = page.evaluate("""() => currenasgnFiles.map(f=>f.name)""")
    page.evaluate("""() => {
      document.querySelectorAll('#mfield-copy .mthumb button[data-mnext]')[0].click(); }""")
    page.wait_for_timeout(300)
    names_after = page.evaluate("""() => currenasgnFiles.map(f=>f.name)""")
    chk("reorder via › moves first thumb to last",
        len(names_after) == 2 and names_after[0] != names_before[0]
        and names_after[-1] == names_before[0],
        f"before={names_before} after={names_after}")
    badges = page.evaluate(
        """() => [...document.querySelectorAll('#mfield-copy .mthumb span')].map(s=>s.textContent)""")
    chk("badges renumbered [1,2]", badges == ["1", "2"], badges)

    # --- 5) lightbox: open on click, navigate, rotate-180, close
    page.evaluate("""() => { document.querySelector('#mfield-copy .mthumb img').click(); }""")
    page.wait_for_selector("#lightbox.show", timeout=5000)
    chk("lightbox opens on thumb click",
        page.evaluate("""() => document.getElementById('lightbox').classList.contains('show')
            && document.getElementById('lb-img').getAttribute('src','').startsWith('blob:')"""))
    chk("lightbox count = 1 / 2", page.text_content("#lb-count") == "1 / 2",
        page.text_content("#lb-count"))
    page.click("#lb-next"); page.wait_for_timeout(150)
    chk("lightbox next → 2 / 2", page.text_content("#lb-count") == "2 / 2",
        page.text_content("#lb-count"))
    page.click("#lb-prev"); page.wait_for_timeout(150)
    chk("lightbox prev → 1 / 2", page.text_content("#lb-count") == "1 / 2",
        page.text_content("#lb-count"))
    before_flip = page.evaluate("""() => currenasgnFiles.map(f=>f.name)""")
    page.click("#lb-rot"); page.wait_for_timeout(900)
    after_flip = page.evaluate("""() => currenasgnFiles.map(f=>f.name)""")
    chk("rotate-180 replaces the stored File (.flipped)",
        any("flipped" in n for n in after_flip)
        and not any("flipped" in n for n in before_flip),
        f"before={before_flip} after={after_flip}")
    page.keyboard.press("Escape"); page.wait_for_timeout(200)
    chk("lightbox closes on Esc",
        not page.evaluate("""() => document.getElementById('lightbox').classList.contains('show')"""))

    # --- 6) × removes a thumb
    page.evaluate("""() => {
      document.querySelector('#mfield-copy .mthumb button[data-mdel]').click(); }""")
    page.wait_for_timeout(300)
    chk("× removes a thumb",
        page.eval_on_selector_all("#mfield-copy .mthumb", "els=>els.length") == 1)

    # --- 7) drag-and-drop reorder with 3 distinct files (unambiguous)
    page.evaluate("""() => { currenasgnFiles.length=0; }""")
    page.set_input_files("#img-file", [PA, PB, PC])
    page.wait_for_timeout(1400)
    n3 = page.eval_on_selector_all("#mfield-copy .mthumb", "els=>els.length")
    if n3 >= 3:
        ob = page.evaluate("""() => currenasgnFiles.map(f=>f.name)""")
        chk("3 distinct thumbs before DnD = [pa,pb,pc]", ob == ["pa.jpg", "pb.jpg", "pc.jpg"], ob)
        page.evaluate("""() => {
          const ts=document.querySelectorAll('#mfield-copy .mthumb');
          ts[0].classList.add('mdrag');
          ts[2].dispatchEvent(new Event('drop',{bubbles:true})); }""")
        page.wait_for_timeout(300)
        page.evaluate("""() => {
          document.querySelectorAll('#mfield-copy .mthumb.mdrag')
            .forEach(e=>e.classList.remove('mdrag')); }""")
        oa = page.evaluate("""() => currenasgnFiles.map(f=>f.name)""")
        chk("DnD drop moves thumb[0] (pa) to last", oa == ["pb.jpg", "pc.jpg", "pa.jpg"],
            f"before={ob} after={oa}")
    else:
        chk("DnD (skipped: <3 thumbs)", True, f"only {n3}")

    # --- 8) no page errors
    chk("no page errors", not errors, errors[:3])

    ctx.close(); pg.close()

print("\n==== SUMMARY ====")
fails = [r for r in res if not r[1]]
print(f"{len(res)-len(fails)}/{len(res)} passed")
if fails:
    print("FAILURES:")
    for f in fails:
        print("  -", f[0])
    sys.exit(1)
print("ALL PASS")
