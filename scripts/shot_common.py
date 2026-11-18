"""Shared Playwright helpers for BabelGrade README screenshots.

Run with: /tmp/bg_venv/bin/python  (chromium headless)
Server must be running on http://127.0.0.1:8090
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests"))
import _testpw as TESTPW

BASE = "http://127.0.0.1:8090"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "readme")
os.makedirs(OUT, exist_ok=True)


def make_page(lang="fr", width=1280, height=860):
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=2,
        locale="en-US",
    )
    ctx.add_init_script(
        f"localStorage.setItem('babelgrade-lang', '{lang}');"
    )
    pg = ctx.new_page()
    return pw, b, ctx, pg


def login(pg):
    pg.goto(BASE, wait_until="networkidle")
    pg.fill("#auth-username", "tibo")
    pg.fill("#auth-password", TESTPW.pw())
    pg.click("#auth-login-btn")
    pg.wait_for_timeout(1200)
    # Confirm we are in
    assert pg.evaluate("document.getElementById('auth-gate').classList.contains('hide')"), \
        "login did not hide the auth gate"


def wait_no_js_errors(pg):
    """Collect console errors during the next wait."""
    errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    return errs
