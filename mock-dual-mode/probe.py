from playwright.sync_api import sync_playwright
URL = "file:///home/tibo/elt-assessor/mock-dual-mode/mock.html"
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_context(viewport={"width": 1280, "height": 900}).new_page()
    pg.goto(URL + "?flow=teacher&eval=B1,B2,B1,B1")
    pg.wait_for_timeout(300)
    print("flow:", pg.evaluate("S.flow"))
    print("entered:", pg.evaluate("JSON.stringify(S.entered)"))
    print("lvl0:", repr(pg.input_value("#lvl-0")), "lvl1:", repr(pg.input_value("#lvl-1")))
    print("score:", pg.inner_text("#att-score"))
    print("view-report hidden?", pg.evaluate("document.getElementById('view-report').classList.contains('hide')"))
    # 390: which nth-child is the pts column?
    m = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True).new_page()
    m.goto(URL + "?flow=teacher&eval=B1,B2,B1,B1")
    m.wait_for_timeout(300)
    print("390 th4 hidden?", m.evaluate("getComputedStyle(document.querySelectorAll('#att-card .att-table th')[3]).display"))
    print("390 th3 hidden?", m.evaluate("getComputedStyle(document.querySelectorAll('#att-card .att-table th')[2]).display"))
    b.close()
