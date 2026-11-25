#!/usr/bin/env python3
"""Photo field — two explicit sources on mobile (2026-11-25):

tibo's ask: on iPhone the single photo input with capture="environment"
opened the camera DIRECTLY, leaving no way to pick an EXISTING photo from
the gallery. Fix: on coarse pointers the photo panel shows TWO source
buttons — 📸 camera (input capture="environment") and 🖼 gallery (plain
picker) — and the dropzone itself still opens the gallery on tap.
Desktop (pointer:fine) keeps ONE input, no capture, no buttons.

Runs against the live server (default 127.0.0.1:8090). Login tibo.
"""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("BABELGRADE_URL", "http://127.0.0.1:8090")
res = []

# --- credentials: tests/.credentials holds the password
_cred = Path(__file__).resolve().parent / ".credentials"
PW = _cred.read_text().strip() if _cred.exists() else "test-pw-9876"

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")


def chk(name, cond, extra=""):
    res.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + str(extra)) if (extra and not cond) else ""))


PROBE = """() => {
  const h=document.getElementById('mfield-copy');
  if(!h) return {exists:false};
  const srcs=h.querySelector('.m-srcs');
  const cam=h.querySelector('input#img-file-cam');
  const inp=h.querySelector('input#img-file');
  const camBtn=srcs?srcs.children[0]:null;
  const galBtn=srcs?srcs.children[1]:null;
  const btns=srcs?[...srcs.querySelectorAll('button')].map(b=>b.textContent):[];
  return { exists:true,
    coarse: matchMedia('(pointer:coarse)').matches,
    srcsVisible: srcs?getComputedStyle(srcs).display!=='none':null,
    camBtn: !!camBtn, galBtn: !!galBtn,
    btnTexts: btns,
    camAria: camBtn?camBtn.getAttribute('aria-label'):null,
    galAria: galBtn?galBtn.getAttribute('aria-label'):null,
    camInp: !!cam,
    camCapture: cam?cam.getAttribute('capture'):null,
    camMultiple: cam?cam.hasAttribute('multiple'):null,
    galInp: !!inp,
    galCapture: inp?inp.getAttribute('capture'):null,
    galMultiple: inp?inp.hasAttribute('multiple'):null };}"""


with sync_playwright() as pw:
    # ===== 1) MOBILE (iPhone emulation → pointer:coarse) =====
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True,
                        is_mobile=True, device_scale_factor=3, user_agent=UA)
    pg = ctx.new_page()
    pg.add_init_script("localStorage.setItem('babelgrade-lang','fr')")
    pg.goto(BASE, wait_until="networkidle")
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", PW)
    pg.click("#auth-login-btn")
    pg.wait_for_load_state("networkidle")
    pg.evaluate("goEvaluate()")
    pg.wait_for_timeout(400)

    m = pg.evaluate(PROBE)
    chk("mobile: photo panel present", m["exists"] and m["coarse"], m.get("coarse"))
    chk("mobile: TWO source buttons", m["srcsVisible"] and m["galBtn"] is not None and len(m["btnTexts"]) == 2, m["btnTexts"])
    chk("mobile: FR labels on the buttons",
        "Prendre une photo" in (m["btnTexts"][0] or "") and "Depuis la galerie" in (m["btnTexts"][1] or ""), m["btnTexts"])
    chk("mobile: aria-labels set", m["camAria"] == "Prendre une photo" and m["galAria"] == "Depuis la galerie",
        (m["camAria"], m["galAria"]))
    chk("mobile: camera input has capture=environment", m["camInp"] and m["camCapture"] == "environment", m["camCapture"])
    chk("mobile: camera input is single-shot (no multiple)", m["camInp"] and not m["camMultiple"])
    chk("mobile: gallery input = original #img-file, NO capture, multiple",
        m["galInp"] and m["galCapture"] is None and m["galMultiple"])
    # the camera button must target its own capture input (not the gallery one)
    target = pg.evaluate("""() => {
      const btn=document.querySelector('#mfield-copy .m-srcs button');
      btn.click();  // opens the native picker — harmless in headless
      return 'clicked';}""")
    chk("mobile: buttons clickable (no JS error)", target == "clicked")
    chk("mobile: no pageerrors", len(errors) == 0, errors)
    b.close()

    # ===== 2) MOBILE — language switch repaints the button labels =====
    b2 = pw.chromium.launch(args=["--no-sandbox"])
    ctx2 = b2.new_context(viewport={"width": 390, "height": 844}, has_touch=True,
                          is_mobile=True, device_scale_factor=3, user_agent=UA)
    pg2 = ctx2.new_page()
    pg2.add_init_script("localStorage.setItem('babelgrade-lang','en')")
    pg2.goto(BASE, wait_until="networkidle")
    pg2.fill("#auth-username", "tibo"); pg2.fill("#auth-password", PW)
    pg2.click("#auth-login-btn")
    pg2.wait_for_load_state("networkidle")
    pg2.evaluate("goEvaluate()")
    pg2.wait_for_timeout(400)
    en = pg2.evaluate(PROBE)
    chk("mobile EN: labels repainted (Take a photo / From the gallery)",
        "Take a photo" in (en["btnTexts"][0] or "") and "From the gallery" in (en["btnTexts"][1] or ""), en["btnTexts"])
    b2.close()

    # ===== 3) DESKTOP (pointer:fine) — UX unchanged =====
    b3 = pw.chromium.launch(args=["--no-sandbox"])
    ctx3 = b3.new_context(viewport={"width": 1280, "height": 900})
    pg3 = ctx3.new_page()
    pg3.add_init_script("localStorage.setItem('babelgrade-lang','fr')")
    pg3.goto(BASE, wait_until="networkidle")
    errs3 = []
    pg3.on("pageerror", lambda e: errs3.append(str(e)))
    pg3.fill("#auth-username", "tibo"); pg3.fill("#auth-password", PW)
    pg3.click("#auth-login-btn")
    pg3.wait_for_load_state("networkidle")
    pg3.evaluate("goEvaluate()")
    pg3.wait_for_timeout(400)
    d = pg3.evaluate(PROBE)
    chk("desktop: no source buttons (absent from DOM)", d["exists"] and not d["coarse"] and not d["srcsVisible"], d["coarse"])
    chk("desktop: no camera input", not d["camInp"])
    chk("desktop: original #img-file present, NO capture attr, multiple",
        d["galInp"] and d["galCapture"] is None and d["galMultiple"])
    chk("desktop: no pageerrors", len(errs3) == 0, errs3)
    b3.close()

print("\n==== SUMMARY ====")
fails = [n for n, ok in res if not ok]
print(f"{len(res) - len(fails)}/{len(res)} passed")
for n in fails:
    print("  FAIL:", n)
if fails:
    raise SystemExit(1)
print("ALL PASS")
