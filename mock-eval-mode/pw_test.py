#!/usr/bin/env python3
"""Playwright test of the eval-mode mock: landscape phone, swipe, AI panel, end-of-scale, desktop."""
import json, pathlib, sys
from playwright.sync_api import sync_playwright

OUT = pathlib.Path('/tmp/elt_mock/shots'); OUT.mkdir(exist_ok=True)
URL = 'file:///tmp/elt_mock/mock.html'
results = []
def check(label, got, exp=None):
    ok = (got == exp) if exp is not None else (got is not None)
    results.append((label, got, exp, ok))
    print(f'{"OK  " if ok else "FAIL"} {label}: got={got!r}' + (f' exp={exp!r}' if exp is not None else ''))

def swipe_touch(page, direction):
    """Touch-event swipe via CDP Input.dispatchTouchEvent (page context)."""
    box = page.evaluate("""() => { const c = document.getElementById('cols').getBoundingClientRect();
                 return {x: c.x, y: c.y, w: c.width, h: c.height} }""")
    y = int(box['y'] + box['h'] / 2)
    if direction < 0:
        x0, x1 = int(box['x'] + box['w'] - 30), int(box['x'] + 30)
    else:
        x0, x1 = int(box['x'] + 30), int(box['x'] + box['w'] - 30)
    cdp = page.context.new_cdp_session(page)
    cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': x0, 'y': y}]})
    cdp.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [{'x': (x0+x1)//2, 'y': y}]})
    cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
    cdp.detach()

with sync_playwright() as p:
    b = p.chromium.launch(args=['--no-sandbox'])
    # ---- landscape phone 844x390 ----
    ph = b.new_context(viewport={'width': 844, 'height': 390}, device_scale_factor=2,
                       is_mobile=True, has_touch=True,
                       user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)')
    pg = ph.new_page()
    pg.goto(URL); pg.wait_for_timeout(300)

    # Open eval mode first, then check rotate overlay by orientation
    pg.click('#btn-eval'); pg.wait_for_timeout(300)
    # portrait (844x390 swapped to 390x844)
    pg.set_viewport_size({'width': 390, 'height': 844}); pg.wait_for_timeout(400)
    check('rotate-overlay(portrait+eval) shown', pg.evaluate("document.getElementById('rotate').classList.contains('show')"), True)
    # landscape
    pg.set_viewport_size({'width': 844, 'height': 390}); pg.wait_for_timeout(400)
    check('rotate-overlay(landscape+eval) hidden', pg.evaluate("document.getElementById('rotate').classList.contains('show')"), False)
    pg.screenshot(path=str(OUT/'01_report.png'))

    # back to report view for the base screenshot
    pg.click('#btn-close'); pg.wait_for_timeout(200)

    # open eval mode
    pg.click('#btn-eval'); pg.wait_for_timeout(300)
    check('eval opens on c1', pg.evaluate("JSON.stringify({hidden:document.getElementById('eval').hidden,"
        "crit:document.getElementById('crit-name').textContent.slice(0,15),"
        "pill:document.getElementById('pill-lvl').textContent,"
        "cols:[...document.querySelectorAll('#cols .col')].map(c=>c.dataset.lv||null),"
        "aiBadge:!!document.querySelector('#cols .badge-ai'),"
        "aiDiff:!!document.querySelector('#cols .ai-diff')})"))
    pg.screenshot(path=str(OUT/'02_eval_c1.png'))

    # swipe right (dx>0) -> pick left level B1 -> A2
    swipe_touch(pg, 1); pg.wait_for_timeout(300)
    check('swipe right picks A2', pg.evaluate("JSON.stringify({pill:document.getElementById('pill-lvl').textContent,"
        "score:document.getElementById('score-hdr').textContent})"))
    pg.screenshot(path=str(OUT/'03_swiped_A2.png'))

    # swipe left (dx<0) -> back to B1
    swipe_touch(pg, -1); pg.wait_for_timeout(300)
    check('swipe left back to B1', pg.evaluate("document.getElementById('pill-lvl').textContent"), 'B1')

    # criterion 2 via chip + AI panel
    pg.click('.chip[data-crit="1"]'); pg.wait_for_timeout(200)
    pg.click('#btn-ai'); pg.wait_for_timeout(400)
    check('AI panel opens', pg.evaluate("JSON.stringify({open:document.getElementById('ai-panel').classList.contains('open'),"
        "title:document.getElementById('ai-title').textContent,"
        "evCount:document.querySelectorAll('#ai-ev li').length})"))
    pg.screenshot(path=str(OUT/'04_c2_ai.png'))

    # end of scale: c1, swipe left 3x -> C2, right col empty
    pg.click('#close-ai'); pg.wait_for_timeout(300)   # dismiss AI panel (covers chips)
    pg.click('.chip[data-crit="0"]'); pg.wait_for_timeout(150)
    for _ in range(3):
        swipe_touch(pg, -1); pg.wait_for_timeout(250)
    check('at C2 (end of scale)', pg.evaluate("JSON.stringify({pill:document.getElementById('pill-lvl').textContent,"
        "rightEmpty:!!document.querySelector('#cols .col.empty[data-pos=right]')})"))
    pg.screenshot(path=str(OUT/'05_c2_end.png'))

    # save button toast
    pg.click('#btn-save'); pg.wait_for_timeout(250)
    check('save toast', pg.evaluate("document.getElementById('toast').textContent"))

    # close -> back to report
    pg.click('#btn-close'); pg.wait_for_timeout(250)
    check('close returns to report', pg.evaluate("document.getElementById('eval').hidden"), True)
    ph.close()

    # ---- desktop 1280x800: no rotate overlay, kbd hint shown ----
    dk = b.new_context(viewport={'width': 1280, 'height': 800})
    pd = dk.new_page()
    pd.goto(URL); pd.wait_for_timeout(300)
    check('desktop: no rotate overlay', pd.evaluate("document.getElementById('rotate').classList.contains('show')"), False)
    pd.click('#btn-eval'); pd.wait_for_timeout(300)
    check('desktop: kbd hint visible', pd.evaluate("document.getElementById('kbd-hint').offsetParent!==null"), True)
    # keyboard: ArrowRight picks the upper level (B1 -> B2), key '2' jumps to criterion 2
    pd.keyboard.press('ArrowRight'); pd.wait_for_timeout(250)
    check('desktop: ArrowRight -> B2', pd.evaluate("document.getElementById('pill-lvl').textContent"), 'B2')
    pd.keyboard.press('2'); pd.wait_for_timeout(250)
    check('desktop: key 2 -> criterion 2', pd.evaluate("document.getElementById('crit-name').textContent.slice(0,12)"))
    pd.screenshot(path=str(OUT/'06_desktop.png'))
    b.close()

fails = [r for r in results if not r[3]]
print('\n==== SUMMARY:', 'ALL OK' if not fails else f'{len(fails)} FAILURES')
for f in fails: print('  FAIL:', f[0], '| got:', f[1], '| expected:', f[2])
sys.exit(1 if fails else 0)
