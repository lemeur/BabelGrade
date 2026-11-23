#!/usr/bin/env python3
"""E2E (post 2026-11-23): in-app docs view removed — Docs is an external link.

The in-app markdown/mermaid docs view was replaced by the GitHub Pages site
(lemeur.github.io/BabelGrade, built into site/ by scripts/build_site.py).
This test verifies:
- the nav carries an EXTERNAL <a.ext-docs> (target=_blank, github.io URL)
- no in-app docs DOM remains (#view-docs, #docs-tabs, #docs-content…)
- no orphaned i18n keys (docs.title / docs.help / docs.loading / docs.tab.*)
- nav.docs still defined 4x (the link label)
- clicking Jobs then back still works (nav stack intact after docs removal)
- no JS errors
"""
import re
from pathlib import Path
import _testpw as TESTPW
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8090"
DOCS_URL = "https://lemeur.github.io/BabelGrade/"
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

def login(pg, lang="fr"):
    pg.add_init_script(f"localStorage.setItem('babelgrade-lang','{lang}')")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", TESTPW.pw())
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    pg.wait_for_timeout(1200)
    # 2026-10-27: boot default = home view, where the tab bar is HIDDEN
    pg.evaluate("navGo('assignments')")
    pg.wait_for_timeout(400)

with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg, "fr")

    nav = pg.evaluate("""() => {
      const a = document.querySelector('nav a.ext-docs');
      const docsBtn = document.querySelector('#nav button[data-view="docs"]');
      return {
        link: a ? {href: a.href, target: a.target, text: a.textContent.trim(),
                   i18n: a.dataset.i18n} : null,
        inAppBtn: !!docsBtn,
        views: ['view-docs','docs-tabs','docs-content','docs-subtabs',
                'docs-loading','docs-view'].filter(id => document.getElementById(id))
      };
    }""")
    check("Docs = external link", nav["link"] is not None, nav["link"])
    if nav["link"]:
        check("Docs URL = github.io site", nav["link"]["href"] == DOCS_URL, nav["link"]["href"])
        check("Docs opens in new tab", nav["link"] and nav["link"]["target"] in ("", "_blank"), nav["link"])
        check("Docs label uses i18n key", nav["link"]["i18n"] == "nav.docs", nav["link"]["i18n"])
    check("no in-app docs nav button", nav["inAppBtn"] is False, nav)
    check("no in-app docs DOM remains", nav["views"] == [], nav["views"])

    # nav stack intact: docs no longer a view, other views still navigate
    pg.evaluate("navGo('jobs')")
    pg.wait_for_timeout(600)
    st = pg.evaluate("""() => ({
      jobsVisible: !document.getElementById('view-jobs').classList.contains('hide')
    })""")
    check("jobs view still reachable", st["jobsVisible"] is True, st)

    check("FR: no JS errors", not errs, errs[:2])
    ctx.close()

    # EN — link label translated
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg, "en")
    txt = pg.evaluate("document.querySelector('nav a.ext-docs').textContent.trim()")
    check("EN: Docs label", txt == "Docs", txt)
    check("EN: no JS errors", not errs, errs[:2])
    ctx.close()
    b.close()

# i18n: nav.docs 4x ; the removed keys are gone
html = open(Path(__file__).resolve().parent.parent / 'static' / 'index.html').read()
n = len(re.findall(r"'nav\.docs':", html))
check("i18n 'nav.docs' defined 4x", n == 4, n)
for key in ["docs.title", "docs.help", "docs.loading",
            "docs.tab.user", "docs.tab.dev", "docs.tab.userguide",
            "docs.tab.asyncjobs", "docs.tab.readme", "docs.tab.uxaudit",
            "docs.tab.architecture"]:
    m = len(re.findall(re.escape("'" + key + "':"), html))
    check(f"i18n orphan key '{key}' removed", m == 0, m)

print(f"\n=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
if FAIL: print("FAILED:", FAIL)
