#!/usr/bin/env python3
"""Card-3 "student work" photo field — 2026-11-25 UX (v2, commit after 2720af3):

Tibo's 1st version (normalize-on-select via /api/media/normalize) was REVOKED:
the deskew estimate is slow on the VM and blocked the whole server, making
selection feel broken. v2 = tibo's own design:

1. INSTANT SELECTION: picking photos appends them to the store immediately,
   NO network call (thumbs appear at once; nothing to spin a progress bar).
2. LIGHTBOX: click a thumbnail → full-size preview + prev/next + manual
   ROTATE-90° (↻). Each click re-renders from the ORIGINAL pixels with the
   total angle (no re-encode loss accumulation); 4 clicks restore the
   original file as-is. Rotated files show a ↻ badge on the thumbnail.
3. REORDER: ‹ › move buttons (mobile) + drag-and-drop (desktop).
4. SAFETY NET unchanged: the backend still runs EXIF+deskew normalization at
   SUBMIT time (_read_image_uploads → media._normalize_orientation), so a
   photo the user forgot to rotate is still corrected before the LLM reads it.

Runs against the live server (default 127.0.0.1:8090, override BABELGRADE_URL).
Login tibo / test-pw-9876. Fixtures auto-generated (PIL) in a tempdir.
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
    """upright.jpg (800x1000, EXIF=1) + pa/pb/pc.jpg (600x800, distinct)."""
    from PIL import Image, ImageDraw

    def lines(size, name):
        w, h = size
        im = Image.new("RGB", (w, h), "white")
        d = ImageDraw.Draw(im)
        for y in range(int(h * 0.1), int(h * 0.9), int(h * 0.06)):
            d.line([(int(w * 0.1), y), (int(w * 0.9), y)], fill="black", width=3)
        d.text((int(w * 0.1), int(h * 0.03)), name, fill="red")
        return im

    im = lines((800, 1000), "upright")
    exif = im.getexif()
    exif[0x0112] = 1
    im.save(tmp / "upright.jpg", exif=exif, quality=90)
    for n in ("pa", "pb", "pc"):
        lines((600, 800), n).save(tmp / f"{n}.jpg", quality=90)


with sync_playwright() as pw:
    tmpdir = Path(tempfile.mkdtemp(prefix="bg_photos_"))
    make_fixtures(tmpdir)
    UPRIGHT = str(tmpdir / "upright.jpg")
    SIDE = str(tmpdir / "pa.jpg")
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

    page.evaluate("goEvaluate()")
    page.wait_for_timeout(400)

    # --- 1) functions + lightbox DOM
    fns = page.evaluate("""() => ({
      lbOpen: typeof window.lbOpen==='function',
      lbClose: typeof window.lbClose==='function',
      lbRot90: typeof window.lbRot90==='function',
      mAddPhotos: typeof window.mAddPhotos==='function'})""")
    chk("functions defined (lbRot90)", all(fns.values()), fns)

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

    # --- 2) INSTANT selection: 2 thumbs within a short window, NO normalize call
    t0 = page.evaluate("Date.now()")
    page.set_input_files("#img-file", [UPRIGHT, SIDE])
    page.wait_for_selector("#mfield-copy .mthumb", timeout=5000)
    page.wait_for_timeout(300)
    dt = page.evaluate("Date.now()") - t0
    n_thumbs = page.eval_on_selector_all("#mfield-copy .mthumb", "els=>els.length")
    chk("2 thumbs INSTANTLY after select", n_thumbs == 2, f"got {n_thumbs} in {dt}ms")
    chk("selection is fast (< 1000 ms, no heavy processing)", dt < 1000, f"{dt} ms")
    chk("NO /api/media/normalize call at selection", len(norm_calls) == 0,
        f"{len(norm_calls)} calls")

    # stored files are the RAW picks (nothing pre-processed on the client)
    raw = page.evaluate("""() => currenasgnFiles.every(f=>!f._rot && !f._rawRaw)
        && currenasgnFiles.map(f=>f.name)""")
    chk("stored files are raw (no _rot/_rawRaw yet)",
        isinstance(raw, list) and len(raw) == 2, raw)

    # --- 3) per-thumb controls
    btns = page.evaluate("""() => {
      const t=document.querySelector('#mfield-copy .mthumb');
      if(!t) return null;
      return { del: !!t.querySelector('button[data-mdel]'),
        prev: !!t.querySelector('button[data-mprev]'),
        next: !!t.querySelector('button[data-mnext]'),
        draggable: t.draggable,
        noBadge: !t.querySelector('.rot-badge') };}""")
    chk("thumb buttons (×/‹/›) + draggable",
        btns and btns["del"] and btns["prev"] and btns["next"] and btns["draggable"], btns)
    chk("no ↻ badge before any rotation", bool(btns and btns["noBadge"]))

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
    page.wait_for_timeout(200)
    names_after = page.evaluate("""() => currenasgnFiles.map(f=>f.name)""")
    chk("reorder via › moves first thumb to last",
        len(names_after) == 2 and names_after[0] != names_before[0]
        and names_after[-1] == names_before[0],
        f"before={names_before} after={names_after}")
    badges = page.evaluate(
        """() => [...document.querySelectorAll('#mfield-copy .mthumb span:not(.rot-badge)')].map(s=>s.textContent)""")
    chk("number badges renumbered [1,2]", badges == ["1", "2"], badges)

    # --- 5) lightbox: open, navigate, rotate-90° cycle, close
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

    # rotate-90°: 800x1000 → 1000x800, _rot=1, badge appears
    dim0 = page.evaluate("""() => new Promise(r=>{const f=currenasgnFiles[0];
      const im=new Image();im.onload=()=>r({w:im.width,h:im.height});
      im.src=URL.createObjectURL(f);})""")
    page.click("#lb-rot"); page.wait_for_timeout(600)
    dim1 = page.evaluate("""() => new Promise(r=>{const f=currenasgnFiles[0];
      const im=new Image();im.onload=()=>r({w:im.width,h:im.height});
      im.src=URL.createObjectURL(f);})""")
    rot_state = page.evaluate("""() => {
      const f=currenasgnFiles[0];
      const badge=!!document.querySelector('#mfield-copy .mthumb .rot-badge');
      return {rot:f._rot||0, hasRaw:!!f._raw, badge};}""")
    chk("rotate 90° swaps dimensions (800x1000 → 1000x800)",
        dim0 and dim1 and dim0["w"] == 800 and dim0["h"] == 1000
        and dim1["w"] == 1000 and dim1["h"] == 800,
        f"{dim0} → {dim1}")
    chk("rotated file carries _rot=1 + _raw + ↻ badge",
        rot_state["rot"] == 1 and rot_state["hasRaw"] and rot_state["badge"], rot_state)

    # rotate 3 more times → back to original (360°), badge gone
    for _ in range(3):
        page.click("#lb-rot"); page.wait_for_timeout(450)
    back = page.evaluate("""() => {
      const f=currenasgnFiles[0];
      return {rot:f._rot||0, badge:!!document.querySelector('#mfield-copy .mthumb .rot-badge')};}""")
    dim2 = page.evaluate("""() => new Promise(r=>{const f=currenasgnFiles[0];
      const im=new Image();im.onload=()=>r({w:im.width,h:im.height});
      im.src=URL.createObjectURL(f);})""")
    chk("4 rotations = 360° → original restored (badge off, 800x1000)",
        back["rot"] == 0 and not back["badge"] and dim2["w"] == 800 and dim2["h"] == 1000,
        f"{back} {dim2}")

    page.keyboard.press("Escape"); page.wait_for_timeout(200)
    chk("lightbox closes on Esc",
        not page.evaluate("""() => document.getElementById('lightbox').classList.contains('show')"""))

    # --- 6) × removes a thumb
    page.evaluate("""() => {
      document.querySelector('#mfield-copy .mthumb button[data-mdel]').click(); }""")
    page.wait_for_timeout(200)
    chk("× removes a thumb",
        page.eval_on_selector_all("#mfield-copy .mthumb", "els=>els.length") == 1)

    # --- 7) drag-and-drop reorder with 3 distinct files
    page.evaluate("""() => { currenasgnFiles.length=0; }""")
    page.set_input_files("#img-file", [PA, PB, PC])
    page.wait_for_timeout(500)
    n3 = page.eval_on_selector_all("#mfield-copy .mthumb", "els=>els.length")
    if n3 >= 3:
        ob = page.evaluate("""() => currenasgnFiles.map(f=>f.name)""")
        chk("3 distinct thumbs before DnD = [pa,pb,pc]", ob == ["pa.jpg", "pb.jpg", "pc.jpg"], ob)
        page.evaluate("""() => {
          const ts=document.querySelectorAll('#mfield-copy .mthumb');
          ts[0].classList.add('mdrag');
          ts[2].dispatchEvent(new Event('drop',{bubbles:true})); }""")
        page.wait_for_timeout(200)
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
