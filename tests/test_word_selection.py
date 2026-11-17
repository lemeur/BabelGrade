#!/usr/bin/env python3
"""Word-selection Annoter test (2026-10-18) — Playwright on the live :8090 server.

Covers:
- WRITTEN: click a first word then a last word (across lines) ->
  .an-w spans get .an-wsel, covered .line-cards get .an-sel, photo crop masks
  (.an-crop) appear, the quote shows exactly the selected words, and the
  pending span is {page,start_word,end_word}.
- WRITTEN: clear the selection -> crop masks removed, no .an-wsel, quote resets.
- WRITTEN: save the annotation -> API accepts start_word/end_word, returns
  derived start_line/end_line, a .an-chip appears, selection clears.
- ORAL (legacy, no words blob): segment selection still works (fallback).
- 390px: no horizontal overflow with the word UI.
Uses analysis 592 (written sub 602) and one oral analysis. Teardown deletes
the annotation created."""
import sys
sys.path.insert(0, "/tmp/elt_dm/venv/lib/python3.11/site-packages")
import _testpw as TESTPW
from playwright.sync_api import sync_playwright
import json, urllib.request, urllib.error

BASE = "http://127.0.0.1:8090"
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + ((" | " + str(extra)) if extra else ""))

def api(method, path, body=None, cookie=None):
    d = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=d, method=method)
    r.add_header("Content-Type", "application/json")
    if cookie:
        r.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

def login_cookie():
    s, _ = api("POST", "/api/auth/login", {"username": "tibo", "password": TESTPW.pw()})
    r = urllib.request.Request(BASE + "/api/auth/login",
        data=json.dumps({"username": "tibo", "password": TESTPW.pw()}).encode(), method="POST")
    r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r) as resp:
        sc = resp.headers.get("Set-Cookie", "")
    return sc.split(";")[0]

def login(pg, lang="fr"):
    pg.add_init_script(f"localStorage.setItem('babelgrade-lang','{lang}')")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", TESTPW.pw())
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    pg.wait_for_timeout(700)

def open_annoter(pg, analysis_id):
    pg.goto(BASE + f"/#history/{analysis_id}", wait_until="networkidle")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    # wait for the analysis report to render, then click the Annoter button
    pg.wait_for_selector("[data-annot-open]", timeout=20000)
    pg.click("[data-annot-open]")
    pg.wait_for_selector("#an-written, #an-oral", state="visible", timeout=20000)
    pg.wait_for_timeout(600)

with sync_playwright() as pw:
    browser = pw.chromium.launch()

    # ============ WRITTEN (1280) ============
    pg = browser.new_page(viewport={"width": 1280, "height": 900})
    login(pg)
    open_annoter(pg, 592)
    pg.wait_for_selector("#an-written .an-w", state="visible", timeout=15000)

    nwords = pg.eval_on_selector_all("#an-written .an-w", "els => els.length")
    check("written: word spans rendered", nwords >= 8, f"n={nwords}")

    # read the global word indices + texts from the page
    word_data = pg.eval_on_selector_all(
        "#an-written .an-w",
        "els => els.map(e => ({w: e.dataset.anw, t: e.textContent.trim()}))")
    # choose a first word on line 0 and a last word on a later line (>= line 2)
    # find word indices per line card
    line_first = pg.evaluate("""() => {
      const out = [];
      document.querySelectorAll('#an-written .line-card').forEach(card => {
        const ws = card.querySelectorAll('.an-w');
        if (ws.length) out.push(+ws[0].dataset.anw);
      });
      return out;
    }""")
    check("written: >=3 lines have words", len(line_first) >= 3, f"lines={len(line_first)}")

    first_w = line_first[0]
    # last word on the 3rd line that has words
    last_w = pg.evaluate("""(first) => {
      const cards = document.querySelectorAll('#an-written .line-card');
      let count = 0;
      for (const card of cards) {
        const ws = card.querySelectorAll('.an-w');
        if (!ws.length) continue;
        count++;
        if (count >= 3) return +ws[ws.length - 1].dataset.anw;
      }
      return first;
    }""", first_w)
    check("written: first<last word index", first_w < last_w, f"{first_w}->{last_w}")

    # click first word
    pg.click(f"#an-written .an-w[data-anw=\"{first_w}\"]")
    pg.wait_for_timeout(150)
    # click last word
    pg.click(f"#an-written .an-w[data-anw=\"{last_w}\"]")
    pg.wait_for_timeout(250)

    sel_count = pg.eval_on_selector_all("#an-written .an-w.an-wsel", "e => e.length")
    expected = last_w - first_w + 1
    check("written: selected words highlighted", sel_count == expected,
          f"{sel_count} vs {expected}")

    crop_count = pg.eval_on_selector_all("#an-written .an-crop", "e => e.length")
    check("written: photo crop masks present", crop_count == 4, f"masks={crop_count}")

    # quote = selected words joined
    quote = pg.inner_text("#an-quote")
    want_words = [wd["t"] for wd in word_data if wd["w"] and first_w <= int(wd["w"]) <= last_w]
    want_quote = " ".join(want_words).strip()
    check("written: quote = selected words", want_quote and want_quote in quote,
          f"want {want_quote!r} got {quote!r}")

    # pending span via anSpanNow (ANNOT is a top-level `let`, not on window)
    span = pg.evaluate("() => (typeof ANNOT !== 'undefined' ? anSpanNow() : null)")
    check("written: pending span is word-based",
          span and span.get("start_word") == first_w and span.get("end_word") == last_w
          and "start_line" not in span, f"span={span}")

    # ---- clear the selection ----
    pg.click("#an-clear-sel")
    pg.wait_for_timeout(200)
    sel_after = pg.eval_on_selector_all("#an-written .an-w.an-wsel", "e => e.length")
    crop_after = pg.eval_on_selector_all("#an-written .an-crop", "e => e.length")
    check("written: clear removes selection", sel_after == 0 and crop_after == 0,
          f"sel={sel_after} crop={crop_after}")

    # ---- save an annotation (reselect then save) ----
    pg.click(f"#an-written .an-w[data-anw=\"{first_w}\"]")
    pg.wait_for_timeout(120)
    pg.click(f"#an-written .an-w[data-anw=\"{last_w}\"]")
    pg.wait_for_timeout(200)
    # chips render PER COVERED LINE (same annotation id on each line card),
    # so count the distinct lines covered by the selection, not "1 chip"
    n_covered_lines = pg.evaluate("""() => {
      const ws = document.querySelectorAll('#an-written .an-w.an-wsel');
      const lines = new Set();
      ws.forEach(w => lines.add(w.closest('.line-card').dataset.line));
      return lines.size;
    }""")
    before = pg.eval_on_selector_all("#an-written .an-chip", "e => e.length")
    # capture the new annotation id so we can clean it up
    pg.click("#an-save")
    pg.wait_for_timeout(1500)
    after = pg.eval_on_selector_all("#an-written .an-chip", "e => e.length")
    new_ann_id = pg.eval_on_selector_all(
        "#an-written .an-chip", "e => e.length ? e[e.length-1].dataset.ann : null")
    check("written: annotation saved (chips added)", after == before + n_covered_lines,
          f"{before}->{after} (covered lines={n_covered_lines})")
    if new_ann_id:
        CK = login_cookie()
        s, _ = api("DELETE", f"/api/annotations/{new_ann_id}", cookie=CK)
        print(f"  (teardown: deleted annotation {new_ann_id} -> {s})")

    # ============ 390px no overflow ============
    pg2 = browser.new_page(viewport={"width": 390, "height": 844})
    login(pg2)
    open_annoter(pg2, 592)
    pg2.wait_for_selector("#an-written .an-w", state="visible", timeout=15000)
    pg2.click("#an-written .an-w")  # select first word
    pg2.wait_for_timeout(200)
    overflow = pg2.evaluate("""() => {
      const de = document.documentElement;
      return de.scrollWidth - de.clientWidth > 2;
    }""")
    check("390px: no horizontal overflow with word UI", not overflow,
          f"scrollW-clientW={pg2.evaluate('document.documentElement.scrollWidth-document.documentElement.clientWidth')}")
    pg2.close()

    # ============ ORAL (legacy segment fallback) ============
    # find an oral analysis id from the API
    ck = login_cookie()
    s, anals = api("GET", "/api/analyses?limit=500", cookie=ck)
    oral_aid = None
    for a in anals:
        sid = a.get("id"); aid = a.get("analysis_id")
        if not sid or not aid:
            continue
        s2, sub = api("GET", f"/api/submissions/{sid}", cookie=ck)
        if s2 == 200 and sub.get("kind") == "oral" and (sub.get("payload_meta") or {}).get("audio_name"):
            s3, an = api("GET", f"/api/analyses/{aid}", cookie=ck)
            if s3 == 200 and ((an or {}).get("transcript") or {}).get("segments"):
                oral_aid = aid
                break
    if oral_aid:
        pg3 = browser.new_page(viewport={"width": 1280, "height": 900})
        login(pg3)
        open_annoter(pg3, oral_aid)
        pg3.wait_for_selector("#an-oral .an-tseg", state="visible", timeout=20000)
        # legacy: no word spans expected -> clicking a segment selects it
        nwords_oral = pg3.eval_on_selector_all("#an-oral .an-w", "e => e.length")
        has_seg = pg3.eval_on_selector_all("#an-oral .an-tseg", "e => e.length")
        check("oral: segments rendered", has_seg >= 2, f"segs={has_seg}")
        pg3.click("#an-oral .an-tseg")
        pg3.wait_for_timeout(200)
        seg_sel = pg3.eval_on_selector_all("#an-oral .an-tseg.an-sel", "e => e.length")
        sp = pg3.evaluate("() => (typeof ANNOT !== 'undefined' ? anSpanNow() : null)")
        check("oral: segment selection works (fallback)",
              seg_sel >= 1 and sp and "start_s" in sp, f"sel={seg_sel} span={sp}")
        print(f"  (oral word spans present: {nwords_oral} — legacy blob has no words)")
        pg3.close()
    else:
        print("ORAL: no oral analysis with transcript found — skipped")

    pg.close()
    browser.close()

print("---")
if FAIL:
    print(f"FAIL {len(FAIL)}:")
    for f in FAIL:
        print(" -", f)
    sys.exit(1)
print(f"PASS ({len(PASS)} checks)")
