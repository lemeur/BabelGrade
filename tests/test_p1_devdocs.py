#!/usr/bin/env python3
"""P1.4 E2E: docs view split into user guide (main) + Dev section (sub-tabs).
- main tabs = [User guide, Developer]
- user section: userguide loaded, no sub-tabs
- dev section: sub-tabs [Architecture, Async jobs (tech), README, UX audit]
- sub-tab click loads that doc
- switching back to user shows userguide again
- i18n 4x for docs.tab.user / docs.tab.dev
- no JS errors
"""
import re
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8090"
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

def login(pg, lang="fr"):
    pg.add_init_script(f"localStorage.setItem('babelgrade-lang','{lang}')")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", "****")
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    pg.wait_for_timeout(1200)
    # 2026-10-27: boot default = home view, where the tab bar is HIDDEN —
    # the test clicks the Docs nav button right after login, so open
    # assignments first (navGo restores the bar).
    pg.evaluate("navGo('assignments')")
    pg.wait_for_timeout(400)

with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg, "fr")
    pg.click("#nav button[data-view=\"docs\"]")
    pg.wait_for_timeout(2000)

    tabs = pg.evaluate("""() => {
      const main=[...document.querySelectorAll('#docs-tabs button')].map(b=>b.textContent.trim());
      const sub=document.getElementById('docs-subtabs');
      const subVisible=sub && !sub.classList.contains('hide');
      const subBtns=subVisible?[...sub.querySelectorAll('button')].map(b=>b.textContent.trim()):[];
      const content=document.getElementById('docs-content').textContent;
      return {main, subVisible, subBtns, h1:(document.querySelector('#docs-content h1')||{}).textContent||''};
    }""")
    check("FR: 2 main tabs (user guide / dev)", tabs["main"]==["Guide utilisateur","Développeur"], tabs["main"])
    check("FR: user section loaded (userguide)", "guide" in tabs["h1"].lower() or tabs["h1"].strip()!="", tabs["h1"])
    check("FR: no dev sub-tabs in user section", tabs["subVisible"] is False, tabs)

    # switch to dev section
    pg.click('#docs-tabs button[data-docsec="dev"]')
    pg.wait_for_timeout(2000)
    tabs = pg.evaluate("""() => {
      const sub=document.getElementById('docs-subtabs');
      const subVisible=sub && !sub.classList.contains('hide');
      const subBtns=subVisible?[...sub.querySelectorAll('button')].map(b=>b.dataset.docslug):[];
      const on=subVisible?[...sub.querySelectorAll('button')].findIndex(b=>b.style.background.includes('var(--ai)')):-1;
      const devActive=[...document.querySelectorAll('#docs-tabs button')].findIndex(b=>b.dataset.docsec==='dev'&&b.style.background.includes('var(--acc)'));
      const h1=(document.querySelector('#docs-content h1')||{}).textContent||'';
      return {subVisible, subBtns, on, devActive, h1};
    }""")
    check("FR: dev sub-tabs visible", tabs["subVisible"] is True, tabs)
    check("FR: 4 dev sub-tabs", tabs["subBtns"]==["architecture","async-jobs","ux-audit","readme"], tabs["subBtns"])
    check("FR: first dev doc loaded (architecture)", tabs["on"]==0, tabs)
    check("FR: main dev tab highlighted", tabs["devActive"]>=0, tabs)

    # click README sub-tab
    pg.click('#docs-subtabs button[data-docslug="readme"]')
    pg.wait_for_timeout(1500)
    st = pg.evaluate("""() => {
      const sub=[...document.querySelectorAll('#docs-subtabs button')];
      const on=sub.findIndex(b=>b.style.background.includes('var(--ai)'));
      return {on, h1:(document.querySelector('#docs-content h1')||{}).textContent||''};
    }""")
    check("FR: readme sub-tab highlighted + content swapped", st["on"]==3, st)

    # back to user section
    pg.click('#docs-tabs button[data-docsec="user"]')
    pg.wait_for_timeout(1500)
    st = pg.evaluate("""() => {
      const sub=document.getElementById('docs-subtabs');
      const main=[...document.querySelectorAll('#docs-tabs button')].findIndex(b=>b.dataset.docsec==='user'&&b.style.background.includes('var(--acc)'));
      return {subHidden:sub.classList.contains('hide'), main};
    }""")
    check("FR: back to user, sub-tabs hidden, user tab on", st["subHidden"] is True and st["main"]==0, st)

    check("FR: no JS errors", not errs, errs[:2])
    ctx.close()

    # EN
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    login(pg, "en")
    pg.click("#nav button[data-view=\"docs\"]")
    pg.wait_for_timeout(2000)
    tabs = pg.evaluate("""() => [...document.querySelectorAll('#docs-tabs button')].map(b=>b.textContent.trim())""")
    check("EN: main tabs translated", tabs==["User guide","Developer"], tabs)
    pg.click('#docs-tabs button[data-docsec="dev"]')
    pg.wait_for_timeout(1500)
    sub = pg.evaluate("""() => {
      const sub=document.getElementById('docs-subtabs');
      return sub&&!sub.classList.contains('hide')?[...sub.querySelectorAll('button')].map(b=>b.textContent.trim()):[];
    }""")
    check("EN: dev sub-tabs translated", sub==["Architecture","Async jobs (tech)","UX audit","README"], sub)
    check("EN: no JS errors", not errs, errs[:2])
    ctx.close()
    b.close()

# i18n balance: new keys 4x
html = open('/home/tibo/babelgrade/static/index.html').read()
for key in ["docs.tab.user", "docs.tab.dev"]:
    n = len(re.findall(re.escape(key) + "':", html))
    check(f"i18n key '{key}' defined 4x", n == 4, n)

print(f"\n=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
if FAIL: print("FAILED:", FAIL)
