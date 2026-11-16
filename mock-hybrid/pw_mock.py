#!/usr/bin/env python3
"""Playwright verification of the hybrid-annoter mock (written + oral)."""
import http.server
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

MOCK = Path("/home/tibo/babelgrade/mock-hybrid")
PORT = 8077


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(MOCK), **kw)

    def log_message(self, *a):
        pass


def serve():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H)
    httpd.serve_forever()


checks = []


def chk(name, cond):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


def run(vp_w, vp_h):
    tag = f"{vp_w}x{vp_h}"
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": vp_w, "height": vp_h})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"http://127.0.0.1:{PORT}/mock.html")
        pg.wait_for_timeout(500)
        chk(f"[{tag}] no JS errors at boot", not errs)

        # written: transcript has word spans; count = 257
        nwords = pg.locator("#trans-w .w").count()
        chk(f"[{tag}] written words rendered (257)", nwords == 257)
        nlines = pg.locator("#trans-w .ln").count()
        chk(f"[{tag}] 23 lines", nlines == 23)
        chk(f"[{tag}] photo shown, crop hidden",
            pg.locator("#phfull").is_visible() and not pg.locator("#phcrop").is_visible())

        # select word 5 -> word 30 (spans lines 0..2: ~11 words/line)
        pg.locator("#trans-w .w[data-w='5']").click()
        chk(f"[{tag}] single-word selection -> 1 line hl",
            pg.locator("#trans-w .ln.hl").count() == 1)
        pg.locator("#trans-w .w[data-w='30']").click()
        hl = pg.locator("#trans-w .ln.hl").count()
        chk(f"[{tag}] range 6..31 -> multi-line consecutive highlight (got {hl})", hl >= 3)
        hls = pg.eval_on_selector_all("#trans-w .ln.hl", "els=>els.map(e=>+e.dataset.ln)")
        contig = all(b - a == 1 for a, b in zip(hls, hls[1:]))
        chk(f"[{tag}] highlighted lines contiguous {hls}", contig and len(hls) > 1)
        # photo crop now visible
        chk(f"[{tag}] crop visible on selection",
            not pg.locator("#phfull").is_visible() and pg.locator("#phcrop").is_visible())
        crop_hl = pg.locator("#crop-boxes .phbox.hl").count()
        chk(f"[{tag}] crop has {hl} highlighted boxes", crop_hl == hl)
        # quote + span json
        q = pg.locator("#quote").inner_text()
        chk(f"[{tag}] quote non-empty", len(q.strip("« »")) > 10)
        sj = pg.locator("#spanjson").inner_text()
        chk(f"[{tag}] span json has start_word/end_word",
            "start_word" in sj and "end_word" in sj and "quote" in sj)
        # re-click the anchor word 5 -> collapse to that single word
        pg.locator("#trans-w .w[data-w='5']").click()
        nsel = pg.locator("#trans-w .w.sel").count()
        chk(f"[{tag}] re-click anchor collapses to 1 word (got {nsel} selected)", nsel == 1)
        pg.locator("#trans-w .w[data-w='5']").click()  # toggle off
        chk(f"[{tag}] toggle-off deselects", pg.locator("#trans-w .w.sel").count() == 0)
        # re-select for the clear test
        pg.locator("#trans-w .w[data-w='5']").click()
        pg.locator("#trans-w .w[data-w='30']").click()
        # clear
        pg.locator("#clear").click()
        chk(f"[{tag}] clear -> back to full photo, no hl",
            pg.locator("#phfull").is_visible()
            and pg.locator("#trans-w .ln.hl").count() == 0
            and pg.locator("#spanjson").inner_text().startswith("//"))

        # oral
        pg.locator("#tab-o").click()
        pg.wait_for_timeout(300)
        nwo = pg.locator("#trans-o .w").count()
        chk(f"[{tag}] oral words rendered ({nwo})", nwo > 80)
        chk(f"[{tag}] audio element present", pg.locator("#au").count() == 1)
        pg.locator("#trans-o .w[data-w='5']").click()
        pg.locator("#trans-o .w[data-w='15']").click()
        sj = pg.locator("#spanjson-o").inner_text()
        chk(f"[{tag}] oral span json start_s/end_s",
            "start_s" in sj and "end_s" in sj and "quote" in sj)
        s0 = pg.eval_on_selector("#au", "a=>a.currentTime")
        chk(f"[{tag}] player seeked to selection start", s0 > 0.5 and s0 < 20)
        hl_o = pg.locator("#trans-o .orln.hl").count()
        chk(f"[{tag}] oral lines highlighted (got {hl_o})", hl_o >= 1)
        chk(f"[{tag}] no JS errors at end", not errs)
        b.close()


if __name__ == "__main__":
    t = threading.Thread(target=serve, daemon=True)
    t.start()
    run(1280, 900)
    run(390, 844)
    passed = sum(1 for _, c in checks if c)
    print(f"\n{passed}/{len(checks)} checks passed")
    if passed != len(checks):
        raise SystemExit(1)
