#!/usr/bin/env python3
"""Userguide screenshots: capture + annotate live BabelGrade UI states.

Output: docs/assets/ug-<name>.png (raw) and docs/assets/ug-<name>-annot.png
Viewport 1280x900 CSS (dsf=2) except the mobile shot. Server on :8090.
Badges: MAGENTA #db2777 (NOT the app's accent blue #2563eb) + white ring +
thin black outline, so they stay readable over any UI component.
Badge modes: 'left' (left margin), 'right' (right margin), 'top' (top margin,
connector down to box top-centre). 'top' is preferred for tall targets
(columns/panes) and narrow full-width strips, where a left-margin connector
would cross the content.
Run: /tmp/bg_venv/bin/python scripts/ug_capture.py
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _testpw as TESTPW
from PIL import Image, ImageDraw, ImageFont

ASSETS = os.path.join(ROOT, "docs", "assets")
os.makedirs(ASSETS, exist_ok=True)
BASE = "http://127.0.0.1:8090"
DSF = 2  # device scale factor

# badge palette: magenta, chosen to be outside the app palette
MAGENTA = (219, 39, 119)
RING_DARK = (20, 20, 25, 230)
RING_WHITE = (255, 255, 255, 255)


def find_font():
    cands = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    return None


FONT = find_font()


def seed_annotate_demo(ctx, sub_id: int) -> int:
    """Idempotently create the 2 demo annotations shown in the userguide §7
    shot (analysis 482 / submission 492 = synthetic fixture copy).

    The docs must NOT ship a real student's handwritten photo, so the §7
    screenshot uses the synthetic fixture copy. That shot only looks right
    when 2 repères are already saved (highlighted lines + a non-empty
    "Annotations (2)" list). This seeds them via the app's own API so the
    capture stays reproducible after a DB reset. No-op when >=2 annotations
    already exist on the submission.

    Spans are word-index based (global index into the page's word list, same
    order as the frontend tokenization); the quote is derived server-side.
    Returns the annotation count afterwards.
    """
    api = ctx.request
    r = api.get(f"{BASE}/api/submissions/{sub_id}/annotations")
    if r.status != 200:
        return 0
    cur = len(r.json().get("annotations", []))
    if cur >= 2:
        return cur
    demo = [
        {"span": {"page": 0, "start_word": 21, "end_word": 28}, "sticker": "thumbs-up",
         "level": "B1", "note": "Très belle nuance : « balanced tone » est bien repéré et nuancé."},
        {"span": {"page": 0, "start_word": 52, "end_word": 60}, "sticker": "star",
         "level": "B2", "note": "Belle analyse de la structure : le connecteur « yet » est identifié et justifié."},
    ]
    for d in demo:
        body = dict(d)
        body["kind"] = "written"
        api.post(f"{BASE}/api/submissions/{sub_id}/annotations", json=body)
    r = api.get(f"{BASE}/api/submissions/{sub_id}/annotations")
    return len(r.json().get("annotations", [])) if r.status == 200 else 0


def annotate(name, shots, boxes):
    """shots: list of (path, css_w, css_h); boxes: {n: (label, [x,y,w,h], mode)}
    Draws small numbered badges (no label chips) on the LAST shot; the legend
    lives in the userguide markdown below the figure.

    mode = 'left':     badge in the left  margin, connector to (x + w*0.5, y + h*0.35)
    mode = 'far-left': as 'left' but pushed into the far-left margin (for targets
                       that start near the middle of the screen, e.g. header pills)
    mode = 'right':    badge in the right margin, connector to (x + w, y + h*0.35)
    mode = 'top':      badge in the top   margin, connector to (x + w*0.5, y)
    mode = 'on':       badge centered ON the element (no connector) — for small
                       header pills where there is no free margin
    mode = 'below':    badge BELOW the element, connector up to (x + w*0.5, y + h)
    mode = 'edge':     badge on the element's RIGHT EDGE (no connector) — for wide
                       buttons whose label is centred, so the badge sits on the
                       button's empty right portion instead of covering the label
    """
    last = shots[-1]
    path, cw, ch = last
    im = Image.open(path)
    dr = ImageDraw.Draw(im, "RGBA")

    def px(v):
        return int(v * DSF)

    r = int(14 * DSF * 0.72)
    for n in sorted(boxes):
        label, (x, y, w, h), mode = boxes[n]
        ty = px(y + h * 0.35)
        if mode == "on":
            cx = int(px(x + w * 0.5))
            cy = int(px(y + h * 0.5))
            cx = max(r + 4, min(im.width - r - 4, cx))
            cy = max(r + 4, min(im.height - r - 4, cy))
            dr.ellipse([cx - r - 7, cy - r - 7, cx + r + 7, cy + r + 7], fill=RING_DARK)
            dr.ellipse([cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3], fill=RING_WHITE)
            dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=MAGENTA + (255,))
            fnt = ImageFont.truetype(FONT, int(r * 1.15)) if FONT else ImageFont.load_default()
            bb = dr.textbbox((0, 0), str(n), font=fnt)
            dr.text((cx - (bb[2] - bb[0]) / 2, cy - (bb[3] - bb[1]) / 2 - bb[1]),
                    str(n), fill="white", font=fnt)
            continue
        if mode == "edge":
            # no connector; badge at the element's right edge, vertically centred
            cx = int(px(x + w) - 10 * DSF)
            cy = int(px(y + h * 0.5))
            cx = max(r + 4, min(im.width - r - 4, cx))
            cy = max(r + 4, min(im.height - r - 4, cy))
            dr.ellipse([cx - r - 7, cy - r - 7, cx + r + 7, cy + r + 7], fill=RING_DARK)
            dr.ellipse([cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3], fill=RING_WHITE)
            dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=MAGENTA + (255,))
            fnt = ImageFont.truetype(FONT, int(r * 1.15)) if FONT else ImageFont.load_default()
            bb = dr.textbbox((0, 0), str(n), font=fnt)
            dr.text((cx - (bb[2] - bb[0]) / 2, cy - (bb[3] - bb[1]) / 2 - bb[1]),
                    str(n), fill="white", font=fnt)
            continue
        if mode == "below":
            tx = px(x + w * 0.5)
            cx = max(r + 4, min(im.width - r - 4, tx))
            cy = px(y + h) + 36 * DSF
            cy = max(r + 4, min(im.height - r - 4, cy))
            ty = px(y + h)
            dr.line([(cx, cy), (tx, ty)], fill=MAGENTA + (255,), width=max(2, r // 5))
            dr.ellipse([cx - r - 7, cy - r - 7, cx + r + 7, cy + r + 7], fill=RING_DARK)
            dr.ellipse([cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3], fill=RING_WHITE)
            dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=MAGENTA + (255,))
            fnt = ImageFont.truetype(FONT, int(r * 1.15)) if FONT else ImageFont.load_default()
            bb = dr.textbbox((0, 0), str(n), font=fnt)
            dr.text((cx - (bb[2] - bb[0]) / 2, cy - (bb[3] - bb[1]) / 2 - bb[1]),
                    str(n), fill="white", font=fnt)
            continue
        cy = ty  # default: aligned with the connector target
        # connector target: for wide elements (cards, full-width strips) point
        # at the INNER EDGE (24 px in) so the connector stays short instead of
        # crossing the whole card; narrow elements are targeted at their centre.
        if mode == "right":
            tx = px(x + w - 24) if w >= 90 else px(x + w)
            cx = px(x + w) + 44 * DSF
            cx = min(cx, im.width - r - 4)
            cx = max(cx, px(x + w) + 10 * DSF)
        elif mode == "top":
            tx = px(x + w * 0.5)
            cx = tx
            cx = max(px(x + w * 0.05), min(px(x + w * 0.95), cx))
            cy = px(y) - 36 * DSF
            cy = max(r + 4, min(cy, px(y) - 18 * DSF))
            cx = max(r + 4, min(im.width - r - 4, cx))
        else:  # 'left'
            tx = px(x + 24) if w >= 90 else px(x + w * 0.5)
            cx = px(x) - 44 * DSF
            cx = max(r + 4, min(cx, px(x) - 10 * DSF))
        cy = max(r + 4, min(im.height - r - 4, cy))
        dr.line([(cx, cy), (tx, ty)], fill=MAGENTA + (255,), width=max(2, r // 5))
        dr.ellipse([cx - r - 7, cy - r - 7, cx + r + 7, cy + r + 7], fill=RING_DARK)
        dr.ellipse([cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3], fill=RING_WHITE)
        dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=MAGENTA + (255,))
        fnt = ImageFont.truetype(FONT, int(r * 1.15)) if FONT else ImageFont.load_default()
        txt = str(n)
        bb = dr.textbbox((0, 0), txt, font=fnt)
        dr.text((cx - (bb[2] - bb[0]) / 2, cy - (bb[3] - bb[1]) / 2 - bb[1]),
                txt, fill="white", font=fnt)
    out = path.replace(".png", "-annot.png")
    im.save(out, optimize=True)
    return out


def shoot(pg, name, w, h, scroll=0):
    """screenshot the viewport; returns (path, css_w, css_h).
    ALWAYS applies window.scrollTo(0, scroll) first — deep-link hash
    navigations do NOT reset the scroll position, so a view shot right after
    a scrolled one would otherwise inherit the old scrollY. Pass the desired
    scroll for scrolled report shots (report-ai=800, report-ai-feedback=1300,
    report-oral=700)."""
    pg.evaluate(f"window.scrollTo(0, {scroll})")
    pg.wait_for_timeout(300)
    path = os.path.join(ASSETS, f"ug-{name}.png")
    pg.screenshot(path=path)
    return path, w, h


def get_boxes(pg, exprs):
    """exprs: list of js expressions each returning a rect [x,y,w,h] list or
    None. Normalised to [x, y, w, h] float lists or None."""
    def norm(r):
        if not r:
            return None
        if isinstance(r, dict):
            try:
                return [r["x"], r["y"], r["width"], r["height"]]
            except (KeyError, TypeError):
                return None
        if isinstance(r, (list, tuple)):
            if len(r) == 4:
                return [float(v) for v in r]
            try:
                return [float(r[0]), float(r[1]), float(r[2]), float(r[3])]
            except (TypeError, IndexError, ValueError):
                return None
        return None
    out = []
    for e in exprs:
        out.append(norm(pg.evaluate(e)))
    return out


def main():
    from playwright.sync_api import sync_playwright
    shots_log = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width": 1280, "height": 900},
                            device_scale_factor=DSF, locale="en-US")
        ctx.add_init_script("localStorage.setItem('babelgrade-lang','fr');")
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))

        # ---- login
        pg.goto(BASE, wait_until="networkidle")
        pg.fill("#auth-username", "tibo")
        pg.fill("#auth-password", TESTPW.pw())
        pg.click("#auth-login-btn")
        pg.wait_for_timeout(1500)
        assert pg.evaluate("document.getElementById('auth-gate').classList.contains('hide')")

        # ---- 1. home radial (open, no selection)
        pg.evaluate("pieClose()")
        pg.wait_for_timeout(400)
        pg.evaluate("openMenu()")
        pg.wait_for_timeout(1100)
        path, w, h = shoot(pg, "home-radial", 1280, 900)
        boxes = get_boxes(pg, [
            # Évaluer sector (top, sector idx 0)
            "(() => { const t = document.querySelector('#rg-0 .sector[data-idx=\"0\"]'); const r = t.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; })()",
            # Préparer sector (bottom-left, sector idx 2)
            "(() => { const t = document.querySelector('#rg-0 .sector[data-idx=\"2\"]'); const r = t.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; })()",
            # Mode avancé button
            "(() => { const r = document.getElementById('home-advanced').getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()",
            # language pill (top-left)
            "(() => { const r = document.getElementById('lang-tgl').getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()",
        ])
        labels = {1: "Évaluer", 2: "Préparer", 3: "Mode avancé", 4: "Langue / compte"}
        annotate("home-radial", [(path, w, h)],
                 {1: (labels[1], boxes[0], "left"),
                  2: (labels[2], boxes[1], "left"),
                  3: (labels[3], boxes[2], "top"),
                  4: (labels[4], boxes[3], "on")})
        shots_log.append(("home-radial", "menu radial home"))

        # ---- 2. home radial: Évaluer selected + L1
        pg.evaluate("rPick(0,0)")
        pg.wait_for_timeout(1000)
        path, w, h = shoot(pg, "home-radial-eval", 1280, 900)
        boxes = get_boxes(pg, [
            "(() => { const s = document.querySelector('#rg-0 .sector[data-idx=\"0\"]'); const r = s.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; })()",
            "(() => { const s = document.querySelector('#rg-1 .sector[data-idx=\"0\"]'); const r = s.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; })()",
            "(() => { const s = document.querySelector('#rg-1 .sector[data-idx=\"1\"]'); const r = s.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; })()",
        ])
        labels = {1: "Évaluer (sélectionné)", 2: "Sur un sujet", 3: "Évaluation directe"}
        annotate("home-radial-eval", [(path, w, h)],
                 {1: (labels[1], boxes[0], "left"),
                  2: (labels[2], boxes[1], "left"),
                  3: (labels[3], boxes[2], "right")})
        shots_log.append(("home-radial-eval", "sous-couronne Évaluer"))
        pg.evaluate("pieClose()")
        pg.wait_for_timeout(500)

        # ---- 3. evaluator, subject mode (top)
        pg.evaluate("goEvaluateSub('subject')")
        pg.wait_for_timeout(900)
        pg.evaluate("(() => { const s = document.getElementById('assignment'); "
                    "[...s.options].forEach(o => { if (o.textContent.includes('CommonWealth')) s.value = o.value; }); "
                    "s.dispatchEvent(new Event('change')); })()")
        pg.wait_for_timeout(700)
        path, w, h = shoot(pg, "evaluator-top", 1280, 900)
        boxes = get_boxes(pg, [
            "(() => { const e = document.querySelector('#view-analyze .wiz-chips'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const r = document.getElementById('assignment').getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()",
            "(() => { const e = document.getElementById('lvl-inherit-lab'); if (!e) return null; const r = e.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; })()",
            "(() => { const e = document.getElementById('who-opts'); if (!e) return null; const r = e.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; })()",
            "(() => { const r = document.getElementById('student').getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()",
        ])
        labels = {1: "Assistant (étapes remplies)", 2: "Sujet",
                  3: "Niveau cible (hérité du sujet)",
                  4: "Niveau spécifique et aménagements", 5: "Élève"}
        annotate("evaluator-top", [(path, w, h)],
                 {k: (labels[k], boxes[k - 1], "left") for k in range(1, 6) if boxes[k - 1]})
        shots_log.append(("evaluator-top", "Évaluateur blocs 1-2"))

        # ---- 4. evaluator, work + rubric + CTAs (scrolled)
        pg.evaluate("document.querySelector('#view-analyze .card.an-actions')?.scrollIntoView({block:'end'})")
        pg.wait_for_timeout(300)
        path, w, h = shoot(pg, "evaluator-work", 1280, 900)
        boxes = get_boxes(pg, [
            "(() => { const e = document.querySelector('#mfield-copy'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const r = document.getElementById('rubric').getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()",
            "(() => { const r = document.getElementById('run').getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()",
            "(() => { const r = document.getElementById('run-eval').getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()",
        ])
        labels = {1: "Travail de l'élève (photo / PDF / texte)", 2: "Grille d'évaluation",
                  3: "Lancer l'analyse IA", 4: "Évaluer d'abord"}
        annotate("evaluator-work", [(path, w, h)],
                 {1: (labels[1], boxes[0], "left"),
                  2: (labels[2], boxes[1], "left"),
                  3: (labels[3], boxes[2], "left"),
                  4: (labels[4], boxes[3], "right")})
        shots_log.append(("evaluator-work", "Évaluateur blocs 3-4 + CTA"))

        # ---- 5. AI report (660) — attestation + note /20
        pg.goto(BASE + "/#history/660", wait_until="networkidle")
        pg.wait_for_timeout(1600)
        path, w, h = shoot(pg, "report-ai", 1280, 900, scroll=800)
        boxes = get_boxes(pg, [
            "(() => { const e = document.querySelector('#hist-report .att-ess, #report .att-ess'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('#hist-report .att-table, #report .att-table'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('#hist-report .note20-card, #report .note20-card'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
        ])
        labels = {1: "Synthèse : niveau, score /120, cible", 2: "Un niveau par critère (modifiable)",
                  3: "Note /20 (classe + voie)"}
        annotate("report-ai", [(path, w, h)],
                 {1: (labels[1], boxes[0], "left"),
                  2: (labels[2], boxes[1], "top"),
                  3: (labels[3], boxes[2], "right")})
        shots_log.append(("report-ai", "Rapport IA (attestation)"))

        # ---- 6. AI report: banner + feedback + copy transcription (scrolled)
        path, w, h = shoot(pg, "report-ai-feedback", 1280, 900, scroll=1300)
        boxes = get_boxes(pg, [
            "(() => { const e = document.querySelector('#hist-report .ai-banner-card, #report .ai-banner-card'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('#hist-report .feedback, #report .feedback'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('#hist-report .copytext-card, #report .copytext-card'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
        ])
        labels = {1: "Bannière IA (avis + relancer)", 2: "Feedback pour l'élève (succès + axes)",
                  3: "Transcription de la copie (OCR automatique)"}
        annotate("report-ai-feedback", [(path, w, h)],
                 {1: (labels[1], boxes[0], "left"),
                  2: (labels[2], boxes[1], "left"),
                  3: (labels[3], boxes[2], "left")})
        shots_log.append(("report-ai-feedback", "Rapport IA (feedback + actions)"))

        # ---- 7. teacher report with AI column (analysis 672)
        pg.goto(BASE + "/#history/672", wait_until="networkidle")
        pg.wait_for_timeout(1600)
        path, w, h = shoot(pg, "report-teacher-ai", 1280, 900, scroll=430)
        boxes = get_boxes(pg, [
            "(() => { const e = document.querySelector('#att-eval'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('#hist-report th:nth-child(2), #report th:nth-child(2)'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('#hist-report th:nth-child(3), #report th:nth-child(3)'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('.ai-banner-card'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
        ])
        labels = {1: "Vos niveaux saisis (modifiable)", 2: "Revoir critère par critère",
                  3: "Avis IA : confirmer ou diverger (✓ / ≠)", 4: "Relancer l'avis IA"}
        annotate("report-teacher-ai", [(path, w, h)],
                 {1: (labels[1], boxes[1], "top"),
                  2: (labels[2], boxes[0], "left"),
                  3: (labels[3], boxes[2], "right"),
                  4: (labels[4], boxes[3], "left")})
        shots_log.append(("report-teacher-ai", "Évaluation enseignant + avis IA"))

        # ---- 8. criterion-by-criterion mode (desktop) on 672
        pg.evaluate("(() => { const b = document.getElementById('att-eval'); if (b) b.click(); })()")
        pg.wait_for_timeout(1400)
        path, w, h = shoot(pg, "eval-criterion", 1280, 900)
        boxes = get_boxes(pg, [
            "(() => { const e = document.querySelector('#ev-crit-name'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('#ev-cols .ev-col.center'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('#ev-cols .ev-col.center .desc'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('.ev-chips'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
        ])
        labels = {1: "Critère courant + score /120", 2: "Les 6 niveaux en cartes",
                  3: "Descripteur du niveau choisi", 4: "Les autres critères"}
        annotate("eval-criterion", [(path, w, h)],
                 {1: (labels[1], boxes[0], "left"),
                  2: (labels[2], boxes[1], "top"),
                  3: (labels[3], boxes[2], "left"),
                  4: (labels[4], boxes[3], "top")})
        shots_log.append(("eval-criterion", "Mode Évaluation (critère par critère)"))
        pg.evaluate("evRequestExit()")
        pg.wait_for_timeout(400)
        pg.evaluate("(() => { const b = document.querySelector('#ev-exit-discard'); if (b) b.click(); })()")
        pg.wait_for_timeout(500)

        # ---- 9. jobs view
        pg.goto(BASE + "/#jobs", wait_until="networkidle")
        pg.wait_for_timeout(900)
        path, w, h = shoot(pg, "jobs", 1280, 900)
        boxes = get_boxes(pg, [
            "(() => { const e = document.querySelector('#view-jobs [data-jfilter]'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('#jobs-counts'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('#view-jobs tbody tr td:nth-child(3)'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('#view-jobs tbody tr td:last-child button'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
        ])
        labels = {1: "Filtres (En attente / En cours / Toutes)", 2: "Compteurs en direct",
                  3: "Phase + durée de chaque tâche", 4: "Suivre une tâche en direct"}
        annotate("jobs", [(path, w, h)],
                 {1: (labels[1], boxes[0], "top"),
                  2: (labels[2], boxes[1], "left"),
                  3: (labels[3], boxes[2], "left"),
                  4: (labels[4], boxes[3], "right")})
        shots_log.append(("jobs", "Tâches (file de traitement)"))

        # ---- 10. assignments view
        pg.goto(BASE + "/#assignments", wait_until="networkidle")
        pg.wait_for_timeout(900)
        path, w, h = shoot(pg, "assignments", 1280, 900)
        boxes = get_boxes(pg, [
            "(() => { const e = document.getElementById('asg-new'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('#view-assignments tbody tr td:nth-child(3)'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('#view-assignments tbody tr td:nth-child(4)'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('#view-assignments tbody tr td:last-child'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
        ])
        labels = {1: "Nouveau sujet", 2: "Type d'exercice (compréhension/expression × écrit/oral)",
                  3: "Ressources jointes", 4: "Actions (stats · détails · évaluer · modifier · supprimer)"}
        annotate("assignments", [(path, w, h)],
                 {k: (labels[k], boxes[k - 1], "left") for k in range(1, 5) if boxes[k - 1]})
        shots_log.append(("assignments", "Sujets"))

        # ---- 11. students view
        pg.goto(BASE + "/#students", wait_until="networkidle")
        pg.wait_for_timeout(900)
        # cosmetic DOM trim for the doc screenshot: hide dev-test leftovers
        # (students without a classroom — residue of Playwright test suites).
        # Does NOT touch the database.
        pg.evaluate("""(() => {
          [...document.querySelectorAll('#students tbody tr')].forEach(tr => {
            const c = tr.querySelector('[data-class]');
            if (c && c.getAttribute('data-class') === '') tr.remove();
          });
        })()""")
        pg.wait_for_timeout(300)
        path, w, h = shoot(pg, "students", 1280, 900)
        boxes = get_boxes(pg, [
            "(() => { const e = document.getElementById('s-import-photos'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('#view-students tbody tr td:nth-child(2)'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('#view-students tbody tr td:last-child'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
        ])
        labels = {1: "Importer la classe (photo de la liste)", 2: "Code de classe",
                  3: "Actions par élève : historique · stats · retirer"}
        annotate("students", [(path, w, h)],
                 {k: (labels[k], boxes[k - 1], "left") for k in range(1, 4) if boxes[k - 1]})
        shots_log.append(("students", "Élèves"))

        # ---- 12. student stats (Hugo Bonnet, id 123)
        pg.goto(BASE + "/#ststats/123", wait_until="networkidle")
        pg.wait_for_timeout(1200)
        path, w, h = shoot(pg, "student-stats", 1280, 900)
        boxes = get_boxes(pg, [
            "(() => { const e = document.querySelector('#view-ststats svg'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const h3s = document.querySelectorAll('#view-ststats h3'); const e = h3s[h3s.length - 1]; const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
        ])
        labels = {1: "Évolution des niveaux dans le temps (écrit/oral × comp/expr)",
                  2: "Détail par type d'évaluation"}
        annotate("student-stats", [(path, w, h)],
                 {k: (labels[k], boxes[k - 1], "left") for k in range(1, 3) if boxes[k - 1]})
        shots_log.append(("student-stats", "Stats élève"))

        # ---- 13. assignment stats (detail modal)
        pg.goto(BASE + "/#assignments", wait_until="networkidle")
        pg.wait_for_timeout(900)
        pg.evaluate("""(() => {
          const tr = [...document.querySelectorAll('#view-assignments tbody tr')]
            .find(r => r.textContent.includes('Writing — argumentative essay'));
          const b = tr && tr.querySelector('button[aria-label*=Stats], button[title*=Stats]');
          (b || (tr && tr.querySelectorAll('button')[0])) && b.click();
        })()""")
        pg.wait_for_timeout(2500)
        pg.evaluate("(() => { const s = document.querySelector('#asgd-stats .stat-class'); if (s) s.scrollIntoView({block:'center'}); })()")
        pg.wait_for_timeout(500)
        path, w, h = shoot(pg, "assignment-stats", 1280, 900)
        boxes = get_boxes(pg, [
            "(() => { const e = document.querySelector('#asgd-stats .stat-class'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
        ])
        labels = {1: "Distribution des niveaux par classe (histogrammes + μ / médiane / σ)"}
        annotate("assignment-stats", [(path, w, h)],
                 {1: (labels[1], boxes[0], "right")})
        shots_log.append(("assignment-stats", "Stats d'un sujet"))
        pg.evaluate("closeAssignmentDetail()")
        pg.wait_for_timeout(400)

        # ---- 14. oral report (analysis 552)
        pg.goto(BASE + "/#history/552", wait_until="networkidle")
        pg.wait_for_timeout(1600)
        path, w, h = shoot(pg, "report-oral", 1280, 900, scroll=700)
        boxes = get_boxes(pg, [
            "(() => { const e = document.querySelector('#hist-report .kv, #report .kv'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('.ai-banner-card'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('#hist-report .transcript, #report .transcript'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
        ])
        labels = {1: "Analyse IA (optionnelle)", 2: "Fluence mesurée (WPM, pauses, hésitations)",
                  3: "Transcription horodatée (corrigible via Annoter)"}
        annotate("report-oral", [(path, w, h)],
                 {1: (labels[1], boxes[1], "left"),
                  2: (labels[2], boxes[0], "left"),
                  3: (labels[3], boxes[2], "left")})
        shots_log.append(("report-oral", "Rapport oral"))

        # ---- 15. annoter dual pane (482 = Camille Blanc, SYNTHETIC fixture
        #         copy + 2 pre-seeded annotations — docs must NOT ship a real
        #         student's handwritten photo; 660 was a real copy)
        n_ann = seed_annotate_demo(ctx, 492)
        print(f"seeded/checked demo annotations on sub 492: {n_ann}")
        pg.goto(BASE + "/#history/482", wait_until="networkidle")
        pg.wait_for_timeout(1600)
        pg.evaluate("(() => { const b = document.querySelector('[data-annot-open]'); if (b) b.click(); })()")
        pg.wait_for_timeout(1500)
        path, w, h = shoot(pg, "annotate", 1280, 900)
        boxes = get_boxes(pg, [
            "(() => { const e = document.querySelector('#an-written .ph-box, #an-written img, #an-written'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.getElementById('an-note'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.getElementById('an-save'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
        ])
        labels = {1: "Photo de la copie (lignes OCR cliquables)", 2: "Panneau d'annotation (niveau + note)",
                  3: "Enregistrer le repère"}
        annotate("annotate", [(path, w, h)],
                 {1: (labels[1], boxes[0], "left"),
                  2: (labels[2], boxes[1], "left"),
                  3: (labels[3], boxes[2], "edge")})
        shots_log.append(("annotate", "Annoter (double panneau)"))

        # ---- 16. mobile criterion picker (390 portrait, 672 context)
        mctx = b.new_context(viewport={"width": 390, "height": 844},
                             device_scale_factor=DSF, locale="en-US", is_mobile=True,
                             has_touch=True)
        mctx.add_init_script("localStorage.setItem('babelgrade-lang','fr');")
        mpg = mctx.new_page()
        mpg.goto(BASE, wait_until="networkidle")
        mpg.fill("#auth-username", "tibo")
        mpg.fill("#auth-password", TESTPW.pw())
        mpg.click("#auth-login-btn")
        mpg.wait_for_timeout(1500)
        mpg.goto(BASE + "/#history/672", wait_until="networkidle")
        mpg.wait_for_timeout(1600)
        mpg.evaluate("(() => { const b = document.getElementById('att-eval'); if (b) b.click(); })()")
        mpg.wait_for_timeout(1400)
        path = os.path.join(ASSETS, "ug-eval-mobile.png")
        mpg.screenshot(path=path)
        boxes = get_boxes(mpg, [
            "(() => { const e = document.querySelector('#eval.ev-port .ev-port-grid, .ev-port-grid'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
            "(() => { const e = document.querySelector('.ev-port-desc'); const r = e ? e.getBoundingClientRect() : null; return r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null; })()",
        ])
        labels = {1: "Grille des niveaux (1 critère à la fois)", 2: "Descripteur du niveau choisi"}
        annotate("eval-mobile", [(path, 390, 844)],
                 {k: (labels[k], boxes[k - 1], "left") for k in range(1, 3) if boxes[k - 1]})
        shots_log.append(("eval-mobile", "Mode critique mobile (portrait)"))
        mctx.close()

        b.close()

    print("ERRORS:", errs[:5] if errs else "none")
    for n, desc in shots_log:
        print(f"OK ug-{n}.png — {desc}")


if __name__ == "__main__":
    main()
