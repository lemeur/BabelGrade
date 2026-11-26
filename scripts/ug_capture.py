#!/usr/bin/env python3
"""Userguide screenshots: capture + annotate live BabelGrade UI states.

Output: docs/assets/ug-<name>.png (raw) and docs/assets/ug-<name>-annot.png
Viewport 1280x900 CSS (dsf=2) except the mobile shot. Server on :8090.
Run: /tmp/bg_venv/bin/python scripts/ug_capture.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _testpw as TESTPW
from PIL import Image, ImageDraw, ImageFont

ASSETS = os.path.join(ROOT, "docs", "assets")
os.makedirs(ASSETS, exist_ok=True)
BASE = "http://127.0.0.1:8090"
DSF = 2  # device scale factor


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


def annotate(name, shots, boxes, corner=False):
    """shots: list of (path, css_w, css_h); boxes: {n: (label, [x,y,w,h] CSS px)}
    Draws small numbered badges (no label chips) on the LAST shot; the legend
    lives in the userguide markdown below the figure.
    corner=False  -> badge in the page margin, connector to the box corner
    corner=True   -> badge pinned at the box' top-left corner, short connector
                     (for full-width panels where the margin is outside the panel)
    """
    last = shots[-1]
    path, cw, ch = last
    im = Image.open(path)
    dr = ImageDraw.Draw(im, "RGBA")
    for n in sorted(boxes):
        label, (x, y, w, h) = boxes[n]
        px = lambda v: int(v * DSF)
        r = int(14 * DSF * 0.72)
        if corner:
            cx, cy = px(x) + r + 10 * DSF, px(y) + r + 10 * DSF
            tx, ty = px(x + w * 0.35), px(y + h * 0.15)
        else:
            # default: badge in the left margin, just above the box's top-left corner
            cx, cy = px(x) - 40 * DSF, px(y) - 20 * DSF
            if cx < r + 2:  # no left margin -> right side of the box
                cx, cy = px(x + w) + 24 * DSF, px(y) - 20 * DSF
            if cy < r + 4:  # too close to the top -> below the top edge
                cy = px(y) + 20 * DSF
            cx = max(r, min(im.width - r, cx))
            cy = max(r, min(im.height - r, cy))
            # connector to the box corner
            tx = px(x) if cx < px(x) else px(x + w)
            ty = px(y)
        dr.line([(cx, cy), (tx, ty)], fill=(37, 99, 235, 215), width=max(2, r // 5))
        # badge circle (white ring for contrast)
        dr.ellipse([cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4],
                   fill=(255, 255, 255, 235))
        dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(37, 99, 235))
        fnt = ImageFont.truetype(FONT, int(r * 1.15)) if FONT else ImageFont.load_default()
        txt = str(n)
        bb = dr.textbbox((0, 0), txt, font=fnt)
        dr.text((cx - (bb[2] - bb[0]) / 2, cy - (bb[3] - bb[1]) / 2 - bb[1]),
                txt, fill="white", font=fnt)
    out = path.replace(".png", "-annot.png")
    im.save(out, optimize=True)
    return out


def shoot(pg, name, w, h, scroll=0, full=False):
    """screenshot the viewport (or full page); returns (path, css_w, css_h, shot_boxes_json)"""
    if scroll:
        pg.evaluate(f"window.scrollTo(0, {scroll})")
        pg.wait_for_timeout(180)
    path = os.path.join(ASSETS, f"ug-{name}.png")
    if full:
        pg.screenshot(path=path, full_page=True)
    else:
        pg.screenshot(path=path)
    return path, w, h


def get_boxes(pg, exprs):
    """exprs: list of js expressions each returning a rect (DOMRect object or
    [x,y,w,h] list) or null. Normalised to [x, y, w, h] lists."""
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
            # DOMRect flattened to more values: x,y,w,h are first four
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
            # Évaluer sector (top)
            "(document.getElementById('rg-0') && document.getElementById('rg-0').querySelector('.sector[data-idx=\"0\"]'))?.getBoundingClientRect()",
            # Préparer sector (bottom-left)
            "(document.getElementById('rg-0') && document.getElementById('rg-0').querySelector('.sector[data-idx=\"2\"]'))?.getBoundingClientRect()",
            "(()=>{const r=document.getElementById('home-advanced').getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()",
            "(()=>{const r=document.getElementById('lang-tgl').getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()",
        ])
        labels = {1: "Évaluer", 2: "Préparer", 3: "Mode avancé", 4: "Langue / compte"}
        annotate("home-radial", [(path, w, h)],
                 {k: (labels[k], v) for k, v in enumerate(boxes, 1) if v})
        shots_log.append(("home-radial", "menu radial home"))

        # ---- 2. home radial: Évaluer selected + L1
        pg.evaluate("rPick(0,0)")
        pg.wait_for_timeout(1000)
        path, w, h = shoot(pg, "home-radial-eval", 1280, 900)
        boxes = get_boxes(pg, [
            "(document.getElementById('rg-0') && document.getElementById('rg-0').querySelector('.sector[data-idx=\"0\"]'))?.getBoundingClientRect()",
            "(document.getElementById('rg-1') && document.getElementById('rg-1').querySelector('.sector[data-idx=\"0\"]'))?.getBoundingClientRect()",
            "(document.getElementById('rg-1') && document.getElementById('rg-1').querySelector('.sector[data-idx=\"1\"]'))?.getBoundingClientRect()",
        ])
        labels = {1: "Verbe sélectionné", 2: "Sur un sujet", 3: "Évaluation directe"}
        annotate("home-radial-eval", [(path, w, h)],
                 {k: (labels[k], v) for k, v in enumerate(boxes, 1) if v})
        shots_log.append(("home-radial-eval", "sous-couronne Évaluer"))
        pg.evaluate("pieClose()")
        pg.wait_for_timeout(500)

        # ---- 3. evaluator, subject mode (top)
        pg.evaluate("goEvaluateSub('subject')")
        pg.wait_for_timeout(900)
        # pick the CommonWealth Games assignment (B1) so inherited level shows
        pg.evaluate("(()=>{const s=document.getElementById('assignment');"
                    "[...s.options].forEach(o=>{if(o.textContent.includes('CommonWealth'))s.value=o.value});"
                    "s.dispatchEvent(new Event('change'))})()")
        pg.wait_for_timeout(700)
        path, w, h = shoot(pg, "evaluator-top", 1280, 900)
        boxes = get_boxes(pg, [
            "(()=>{const e=document.querySelector('#view-analyze .stepper, #view-analyze .wiz-steps'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const r=document.getElementById('assignment').getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()",
            "(()=>{const e=document.getElementById('lvl-inherit-lab'); if(!e)return null; const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()",
            "(()=>{const e=document.getElementById('who-opts'); if(!e)return null; const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()",
            "(()=>{const r=document.getElementById('student').getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()",
        ])
        labels = {1: "Assistant (étapes remplies)", 2: "Sujet",
                  3: "Niveau cible (hérité du sujet)", 4: "Aménagements / niveau spécifique",
                  5: "Élève"}
        annotate("evaluator-top", [(path, w, h)],
                 {k: (labels[k], v) for k, v in enumerate(boxes, 1) if v})
        shots_log.append(("evaluator-top", "Évaluateur blocs 1-2"))

        # ---- 4. evaluator, work + rubric + CTAs (scrolled)
        pg.evaluate("document.querySelector('#view-analyze .card.an-actions')?.scrollIntoView({block:'end'})")
        pg.wait_for_timeout(300)
        path, w, h = shoot(pg, "evaluator-work", 1280, 900)
        boxes = get_boxes(pg, [
            "(()=>{const e=document.querySelector('#mfield-copy'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const r=document.getElementById('rubric').getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()",
            "(()=>{const r=document.getElementById('run').getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()",
            "(()=>{const r=document.getElementById('run-eval').getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()",
        ])
        labels = {1: "Travail de l'élève (photo / PDF / texte)", 2: "Grille d'évaluation",
                  3: "IA d'abord", 4: "Évaluer d'abord"}
        annotate("evaluator-work", [(path, w, h)],
                 {k: (labels[k], v) for k, v in enumerate(boxes, 1) if v})
        shots_log.append(("evaluator-work", "Évaluateur blocs 3-4 + CTA"))

        # ---- 5. AI report top (analysis 660: done, B2, attestation)
        pg.goto(BASE + "/#history/660", wait_until="networkidle")
        pg.wait_for_timeout(1600)
        path, w, h = shoot(pg, "report-ai", 1280, 900)
        boxes = get_boxes(pg, [
            "(()=>{const e=document.querySelector('#hist-report .att-ess, #report .att-ess'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('#hist-report .att-table, #report .att-table'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('#hist-report .note20-fold, #report .note20-fold'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('#hist-report .ai-banner-card, #report .ai-banner-card'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
        ])
        labels = {1: "Attestation : niveau, score /120, note /20",
                  2: "Niveau par critère (modifiable) + points",
                  3: "Note /20 (classe + voie LVA/LVB)",
                  4: "Bannière IA (avis en aveugle / au courant)"}
        annotate("report-ai", [(path, w, h)],
                 {k: (labels[k], v) for k, v in enumerate(boxes, 1) if v})
        shots_log.append(("report-ai", "Rapport IA (haut)"))

        # ---- 6. AI report: feedback + copy transcription (scrolled)
        pg.evaluate("document.querySelector('#hist-report .feedback, #report .feedback')?.scrollIntoView({block:'center'})")
        pg.wait_for_timeout(300)
        pg.evaluate("window.scrollBy(0, -120)")
        pg.wait_for_timeout(250)
        path, w, h = shoot(pg, "report-ai-feedback", 1280, 900)
        boxes = get_boxes(pg, [
            "(()=>{const e=document.querySelector('#hist-report .feedback, #report .feedback'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('#hist-report .copytext-card, #report .copytext-card'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('#hist-report .actions-card, #report .actions-card'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
        ])
        labels = {1: "Feedback pour l'élève (succès + axes)", 2: "Transcription de la copie (OCR automatique)",
                  3: "Annoter · Copier · Imprimer · Télécharger"}
        annotate("report-ai-feedback", [(path, w, h)],
                 {k: (labels[k], v) for k, v in enumerate(boxes, 1) if v})
        shots_log.append(("report-ai-feedback", "Rapport IA (feedback + actions)"))

        # ---- 7. teacher report with AI column (analysis 672)
        pg.goto(BASE + "/#history/672", wait_until="networkidle")
        pg.wait_for_timeout(1600)
        path, w, h = shoot(pg, "report-teacher-ai", 1280, 900)
        boxes = get_boxes(pg, [
            "(()=>{const e=document.querySelector('#att-eval'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('[class*=ai-banner], .ai-card, #ai-banner'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('th[title*=IA], th:has(+td)'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
        ])
        labels = {1: "Mode Évaluation (critère par critère)",
                  2: "Bannière IA (avis + re-lancer)",
                  3: "Colonne IA ✓/≠"}
        annotate("report-teacher-ai", [(path, w, h)],
                 {k: (labels[k], v) for k, v in enumerate(boxes, 1) if v})
        shots_log.append(("report-teacher-ai", "Évaluation enseignant + avis IA"))

        # ---- 8. criterion-by-criterion mode (desktop) on 672
        pg.evaluate("(()=>{const b=document.getElementById('att-eval'); if(b) b.click()})()")
        pg.wait_for_timeout(1400)
        path, w, h = shoot(pg, "eval-criterion", 1280, 900)
        boxes = get_boxes(pg, [
            "(()=>{const e=document.querySelector('#ev-crit-name'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('#ev-cols'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('#ev-cols .ev-col.center .desc'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.getElementById('ev-score-hdr'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
        ])
        labels = {1: "Critère courant + score /120", 2: "Échelle des niveaux (carte par niveau)",
                  3: "Descripteur du niveau saisi", 4: "Score en direct"}
        annotate("eval-criterion", [(path, w, h)],
                 {k: (labels[k], v) for k, v in enumerate(boxes, 1) if v})
        shots_log.append(("eval-criterion", "Mode Évaluation (critère par critère)"))
        pg.evaluate("evRequestExit()")
        pg.wait_for_timeout(400)
        pg.evaluate("(()=>{const b=document.querySelector('#ev-exit-discard'); if(b) b.click()})()")
        pg.wait_for_timeout(500)

        # ---- 9. jobs view
        pg.goto(BASE + "/#jobs", wait_until="networkidle")
        pg.wait_for_timeout(900)
        path, w, h = shoot(pg, "jobs", 1280, 900)
        boxes = get_boxes(pg, [
            "(()=>{const e=document.querySelector('#view-jobs .pill-row, #view-jobs .filterbar, #view-jobs .job-head'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('#view-jobs tbody tr'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('#view-jobs tbody tr button'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
        ])
        labels = {1: "Filtres + compteurs en direct", 2: "Phase + durée", 3: "Suivre en direct"}
        annotate("jobs", [(path, w, h)],
                 {k: (labels[k], v) for k, v in enumerate(boxes, 1) if v})
        shots_log.append(("jobs", "Tâches (file de traitement)"))

        # ---- 10. assignments view
        pg.goto(BASE + "/#assignments", wait_until="networkidle")
        pg.wait_for_timeout(900)
        path, w, h = shoot(pg, "assignments", 1280, 900)
        boxes = get_boxes(pg, [
            "(()=>{const e=document.getElementById('asg-new'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('#view-assignments tbody tr .badge, #view-assignments tbody tr td:nth-child(2)'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('#view-assignments tbody tr td:nth-child(4)'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('#view-assignments tbody tr button'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
        ])
        labels = {1: "Créer un sujet", 2: "Type (comp/expr × écrit/oral)",
                  3: "Ressources jointes", 4: "Actions (stats / détails / évaluer / modifier)"}
        annotate("assignments", [(path, w, h)],
                 {k: (labels[k], v) for k, v in enumerate(boxes, 1) if v})
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
            "(()=>{const e=document.getElementById('s-import-photos'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('#view-students tbody tr td:nth-child(2)'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('#view-students tbody tr button'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
        ])
        labels = {1: "Importer la classe (photo de la liste)", 2: "Code de classe",
                  3: "Modifier / copie / stats / retirer"}
        annotate("students", [(path, w, h)],
                 {k: (labels[k], v) for k, v in enumerate(boxes, 1) if v})
        shots_log.append(("students", "Élèves"))

        # ---- 12. student stats (Hugo Bonnet, id 123)
        pg.goto(BASE + "/#ststats/123", wait_until="networkidle")
        pg.wait_for_timeout(1200)
        path, w, h = shoot(pg, "student-stats", 1280, 900)
        boxes = get_boxes(pg, [
            "(()=>{const e=document.querySelector('#view-ststats svg'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('#view-ststats .stat-table, #view-ststats table'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
        ])
        labels = {1: "Évolution des niveaux (écrit/oral × comp/expr)", 2: "Détail par évaluation"}
        annotate("student-stats", [(path, w, h)],
                 {k: (labels[k], v) for k, v in enumerate(boxes, 1) if v})
        shots_log.append(("student-stats", "Stats élève"))

        # ---- 13. assignment stats (assignment 48)
        pg.goto(BASE + "/#assignments", wait_until="networkidle")
        pg.wait_for_timeout(900)
        pg.evaluate("(()=>{const tr=[...document.querySelectorAll('#view-assignments tbody tr')]"
                    ".find(r=>r.textContent.includes('Writing — argumentative essay'));"
                    "const b=tr&&tr.querySelector('button[aria-label*=Stats], button[title*=Stats]');"
                    "(b||tr&&tr.querySelectorAll('button')[0])&&b.click()})()")
        pg.wait_for_timeout(2500)
        # the stats section renders inside the detail modal, below the tall
        # "Avis IA" card → scroll it into view before shooting
        pg.evaluate("(()=>{const s=document.querySelector('#asgd-stats .stat-class'); if(s) s.scrollIntoView({block:'center'})})()")
        pg.wait_for_timeout(500)
        path, w, h = shoot(pg, "assignment-stats", 1280, 900)
        boxes = get_boxes(pg, [
            "(()=>{const e=document.querySelector('#asgd-stats .stat-class'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
        ])
        labels = {1: "Distribution des niveaux par classe (histogrammes + μ / médiane / σ)"}
        annotate("assignment-stats", [(path, w, h)],
                 {k: (labels[k], v) for k, v in enumerate(boxes, 1) if v}, corner=True)
        shots_log.append(("assignment-stats", "Stats d'un sujet"))
        # close the detail modal so it does not leak over the next deep-linked views
        pg.evaluate("closeAssignmentDetail()")
        pg.wait_for_timeout(400)

        # ---- 14. oral report (analysis 552, B1, transcription)
        pg.goto(BASE + "/#history/552", wait_until="networkidle")
        pg.wait_for_timeout(1600)
        path, w, h = shoot(pg, "report-oral", 1280, 900)
        boxes = get_boxes(pg, [
            "(()=>{const e=document.querySelector('#hist-report .kv, #report .kv'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('#hist-report .transcript, #report .transcript'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('#hist-report .feedback, #report .feedback'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
        ])
        labels = {1: "Fluence mesurée (WPM, pauses, hésitations)", 2: "Transcription horodatée (corrigible via Annoter)",
                  3: "Feedback pour l'élève"}
        annotate("report-oral", [(path, w, h)],
                 {k: (labels[k], v) for k, v in enumerate(boxes, 1) if v})
        shots_log.append(("report-oral", "Rapport oral"))

        # ---- 15. annoter dual pane (from 660)
        pg.goto(BASE + "/#history/660", wait_until="networkidle")
        pg.wait_for_timeout(1600)
        pg.evaluate("(()=>{const b=document.querySelector('[data-annot-open]'); if(b) b.click()})()")
        pg.wait_for_timeout(1500)
        path, w, h = shoot(pg, "annotate", 1280, 900)
        boxes = get_boxes(pg, [
            "(()=>{const e=document.querySelector('#an-written .ph-box, #an-written img, #an-written'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('.an-panel, #an-panel'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.getElementById('an-save'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
        ])
        labels = {1: "Photo de la copie (lignes OCR sur sélection)", 2: "Panneau d'annotation (niveau + note)",
                  3: "Enregistrer"}
        annotate("annotate", [(path, w, h)],
                 {k: (labels[k], v) for k, v in enumerate(boxes, 1) if v})
        shots_log.append(("annotate", "Annoter (double panneau)"))

        # ---- 16. mobile criterion picker (390 portrait, evaluator 672 context)
        mctx = b.new_context(viewport={"width": 390, "height": 844},
                             device_scale_factor=2, locale="en-US", is_mobile=True,
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
        mpg.evaluate("(()=>{const b=document.getElementById('att-eval'); if(b) b.click()})()")
        mpg.wait_for_timeout(1400)
        path = os.path.join(ASSETS, "ug-eval-mobile.png")
        mpg.screenshot(path=path)
        boxes = get_boxes(mpg, [
            "(()=>{const e=document.querySelector('#eval.ev-port .ev-port-grid, .ev-port-grid'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
            "(()=>{const e=document.querySelector('.ev-port-desc'); const r=e?e.getBoundingClientRect():null; return r?[r.x,r.y,r.width,r.height]:null})()",
        ])
        labels = {1: "Grille des niveaux (1 critère à la fois)", 2: "Descripteur du niveau choisi"}
        annotate("eval-mobile", [(path, 390, 844)],
                 {k: (labels[k], v) for k, v in enumerate(boxes, 1) if v})
        shots_log.append(("eval-mobile", "Mode critique mobile (portrait)"))
        mctx.close()

        b.close()

    print("ERRORS:", errs[:5] if errs else "none")
    for n, desc in shots_log:
        print(f"OK ug-{n}.png — {desc}")


if __name__ == "__main__":
    main()
