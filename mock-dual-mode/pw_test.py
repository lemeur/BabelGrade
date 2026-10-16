#!/usr/bin/env python3
"""Playwright checks for the dual-mode mock (teacher-first / ai-first, re-run AI)."""
import sys
from playwright.sync_api import sync_playwright

URL = "file:///home/tibo/elt-assessor/mock-dual-mode/mock.html"
PASS, FAIL = 0, []

def ok(name, cond, extra=""):
    global PASS
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL.append(name)
        print(f" FAIL {name} {extra}")

MOCK = "/home/tibo/elt-assessor/mock-dual-mode/shots"
import os
os.makedirs(MOCK, exist_ok=True)

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: print("  PAGEERROR:", e))

    # ---------- 1. entry view ----------
    pg.goto(URL)
    ok("entry: two cards", pg.locator("#btn-ai-first").count() == 1 and pg.locator("#btn-teacher-first").count() == 1)
    ok("entry: report hidden", pg.locator("#view-report").evaluate("el=>el.classList.contains('hide')"))
    ok("entry: label « Évaluer d'abord »", "Évaluer d'abord" in pg.inner_text("#view-entry"))
    pg.screenshot(path=f"{MOCK}/01-entry.png")

    # ---------- 2. teacher-first, blank start ----------
    pg.click("#btn-teacher-first")
    ok("tf: report visible", not pg.locator("#view-report").evaluate("el=>el.classList.contains('hide')"))
    ok("tf: 4 criteria rows", pg.locator("#att-rows tr").count() == 4)
    ok("tf: starts blank (score 0)", pg.inner_text("#att-score") == "0")
    ok("tf: level dash", pg.inner_text("#att-level") == "—")
    ok("tf: unmapped warning", "non notés" in pg.inner_text("#att-unmapped"))
    ok("tf: AI banner + 2 mode options", pg.locator('input[name=aimode]').count() == 2 and "Lancer l'analyse IA" in pg.inner_text("#ai-banner"))
    ok("tf: no feedback card yet", pg.locator("#ai-feedback-card").evaluate("el=>el.classList.contains('hide')"))
    ok("tf: AI cells empty", pg.locator("#ai-0").inner_text().strip() == "—")

    # set teacher levels B1, B2, B1, B1
    pg.select_option("#lvl-0", "B1"); pg.select_option("#lvl-1", "B2")
    pg.select_option("#lvl-2", "B1"); pg.select_option("#lvl-3", "B1")
    ok("tf: score 25 after B1,B2,B1,B1", pg.inner_text("#att-score") == "25")
    ok("tf: attestation level B1 (>=20)", pg.inner_text("#att-level") == "B1")
    ok("tf: unmapped warning gone", pg.locator("#att-unmapped").evaluate("el=>el.classList.contains('hide')"))
    pg.screenshot(path=f"{MOCK}/02-teacher-blank-filled.png")

    # ---------- 3. run AI in aware mode ----------
    pg.click('label:has(input[value=aware])')
    pg.click("#btn-run-ai")
    ok("tf: running state", "Analyse IA en cours" in pg.inner_text("#ai-banner"))
    pg.wait_for_selector("#ai-run .ln:nth-child(4)", timeout=15000)
    ok("tf: stream lines appear", pg.locator("#ai-run .ln").count() >= 4)
    pg.screenshot(path=f"{MOCK}/03-running.png")
    pg.wait_for_function("document.getElementById('btn-rerun')", timeout=20000)
    ok("tf: AI done → rerun button (old one gone)", pg.locator("#btn-rerun").count() == 1 and pg.locator("#btn-run-ai").count() == 0)
    ok("tf: recap 2 confirmed 2 diverged", "2 confirmé" in pg.inner_text("#recap") and "2 divergence" in pg.inner_text("#recap"))
    ok("tf: aware pill on banner", "avec vos niveaux" in pg.inner_text("#ai-banner"))
    ok("tf: ai cells show badges", "B2" in pg.locator("#ai-2").inner_text() and "≠" in pg.locator("#ai-2").inner_text())
    ok("tf: matching cell has ✓", "✓" in pg.locator("#ai-1").inner_text())
    ok("tf: feedback card visible (aware text)", "je confirme" in pg.inner_text("#ai-feedback-card").lower())
    pg.screenshot(path=f"{MOCK}/04-ai-after-aware.png")

    # ---------- 4. re-run in blind mode (last one wins) ----------
    pg.click("#btn-rerun")
    ok("rerun: mode selector re-shown", pg.locator('input[name=aimode]').count() == 2 and pg.locator("#btn-run-ai").count() == 1)
    ok("rerun: 'replace' wording", "remplacé" in pg.inner_text("#ai-banner"))
    pg.click('label:has(input[value=blind])')
    pg.click("#btn-run-ai")
    ok("rerun: running state", "Analyse IA en cours" in pg.inner_text("#ai-banner"))
    pg.wait_for_function("document.getElementById('btn-rerun') && document.querySelector('input[name=aimode]')===null", timeout=20000)
    ok("rerun: finished → banner back to 'avis IA' state", "Avis IA" in pg.inner_text("#ai-banner"))
    ok("rerun: mode flipped to blind", "en aveugle" in pg.inner_text("#ai-banner"))
    ok("rerun: blind feedback replaced", "Excellent letter" in pg.inner_text("#ai-feedback-card"))
    pg.screenshot(path=f"{MOCK}/05-rerun-blind.png")

    # ---------- 5. save ----------
    pg.click("#btn-save")
    pg.wait_for_timeout(100)
    ok("tf: validated pill", "validée" in pg.inner_text("#pill-validated") and not pg.locator("#pill-validated").evaluate("el=>el.classList.contains('hide')"))
    ok("tf: save button disabled", pg.locator("#btn-save").is_disabled())
    pg.screenshot(path=f"{MOCK}/06-saved.png")

    # ---------- 6. ai-first flow ----------
    pg.goto(URL + "?flow=ai")
    ok("af: pre-filled AI levels", [pg.input_value("#lvl-" + str(i)) for i in range(4)] == ["B1", "B2", "B2", "B2"])
    ok("af: score 35", pg.inner_text("#att-score") == "35")
    ok("af: attestation level B1 (35<40)", pg.inner_text("#att-level") == "B1")
    ok("af: all 4 confirmed", "4 confirmé" in pg.inner_text("#recap"))
    ok("af: rerun offered", pg.locator("#btn-rerun").count() == 1)
    ok("af: blind feedback", "Excellent letter" in pg.inner_text("#ai-feedback-card"))
    pg.screenshot(path=f"{MOCK}/07-ai-first.png")

    # ---------- 7. deep-link with prefilled teacher levels ----------
    pg.goto(URL + "?flow=teacher&eval=B1,B2,B1,B1")
    ok("dl: prefilled levels", [pg.input_value("#lvl-" + str(i)) for i in range(4)] == ["B1", "B2", "B1", "B1"])
    ok("dl: score 25", pg.inner_text("#att-score") == "25")

    # ---------- 8. mobile 390 ----------
    m = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                      user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)")
    pm = m.new_page()
    pm.on("pageerror", lambda e: print("  M-PAGEERROR:", e))
    pm.goto(URL + "?flow=teacher&eval=B1,B2,B1,B1")
    pm.wait_for_timeout(200)
    sw = pm.evaluate("document.documentElement.scrollWidth")
    ok("390: no page overflow", sw <= 390, f"scrollWidth={sw}")
    ok("390: all 4 columns kept on mobile", pm.locator("#att-card .att-table th").nth(3).is_visible())
    pm.screenshot(path=f"{MOCK}/08-mobile-390.png")
    pm.click('label:has(input[value=aware])')
    pm.click("#btn-run-ai")
    pm.wait_for_function("document.getElementById('btn-rerun')", timeout=20000)
    sw2 = pm.evaluate("document.documentElement.scrollWidth")
    ok("390: after AI run no overflow", sw2 <= 390, f"scrollWidth={sw2}")
    pm.screenshot(path=f"{MOCK}/09-mobile-390-after-ai.png", full_page=True)

    # ---------- 9. landscape 844 ----------
    l = b.new_context(viewport={"width": 844, "height": 390}, device_scale_factor=2, is_mobile=True, has_touch=True)
    pl = l.new_page()
    pl.goto(URL + "?flow=teacher")
    pl.wait_for_timeout(200)
    iw = pl.evaluate("window.innerWidth")
    ok("844: innerWidth stays 844", iw == 844, f"innerWidth={iw}")
    pl.screenshot(path=f"{MOCK}/10-landscape-844.png")

    b.close()

print(f"\n{PASS} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
