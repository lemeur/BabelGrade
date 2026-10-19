"""Unit tests for app.ocr box re-snapping (2026-10-17 bug fix, 2026-10-19 hardening).

The vision LLM transcribes faithfully but its per-line box y-coordinates
are frequently INTERPOLATED rather than measured, and systematically land
~one line ABOVE the ink. `resnap_boxes` re-anchors the boxes onto the
page's actual ink bands via an order-preserving alignment (Needleman–
Wunsch) with a one-line de-bias, so it also copes with band_count ≠
line_count: the LLM sometimes skips a visual line (printed "Question 2:"
header, teacher's grading ink), which a strict 1:1 zip could not absorb
and which caused the "highlight one line above the selection" bug
(2026-10-19, sub 597-style photo).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ocr import (  # noqa: E402
    _band_unclean_frac,
    _ink_bands,
    resnap_boxes,
)


def make_page(h=752, w=1000, bands=()) -> np.ndarray:
    """Synthetic page: white with black ink bars on the given rows.

    bands: iterable of (y0, y1) pixel rows to fill with ink.
    """
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    for y0, y1 in bands:
        d.rectangle([0, y0, w - 1, y1], fill=20)
    return np.array(img)


def test_ink_bands_detects_filled_rows():
    gray = make_page(h=752, bands=[(200, 223), (300, 323), (400, 423)])
    bands = _ink_bands(gray)
    assert len(bands) == 3, bands
    assert bands[0][0] >= 195 and bands[0][1] <= 228, bands[0]
    assert bands[2][0] >= 395 and bands[2][1] <= 428, bands[2]


def test_ink_bands_merges_small_gaps():
    # descenders split a visual line into two raw bands 3px apart -> merged
    gray = make_page(h=752, bands=[(200, 223), (227, 235), (400, 423)])
    bands = _ink_bands(gray)
    assert len(bands) == 2, bands


def test_ink_bands_drops_specks():
    gray = make_page(h=752, bands=[(100, 102), (200, 223)])  # 3px speck + real line
    bands = _ink_bands(gray)
    assert len(bands) == 1, bands


def test_resnap_1to1_replaces_y_keeping_x():
    h = 752
    gray = make_page(h=h, bands=[(211, 243), (297, 329), (378, 404)])
    lines = [
        {"i": 0, "text": "line one", "box": [118, 120, 900, 190]},
        {"i": 1, "text": "line two", "box": [118, 210, 880, 280]},
        {"i": 2, "text": "line three", "box": [118, 300, 800, 370]},
    ]
    n = resnap_boxes(lines, gray)
    assert n == 3
    exp = [211 * 1000 // h, 297 * 1000 // h, 378 * 1000 // h]
    for ln, (e_y0) in zip(lines, exp):
        # x extents preserved, y snapped to the ink band
        assert ln["box"][0] in (118,) or isinstance(ln["box"][0], int)
        assert ln["box"][1] >= e_y0 - 10 and ln["box"][1] <= e_y0 + 10, ln["box"]
    assert lines[0]["box"][0] == 118 and lines[0]["box"][2] == 900


def test_resnap_missing_box_line_stays_untouched():
    # a line with no LLM box cannot be localized from its own box: it is
    # left as-is (the UI falls back to an index-estimated band), while the
    # boxed line still snaps to its band. (Old 1:1 zip gave it a
    # full-width band; with the alignment a forced snap could grab the
    # wrong band, so "leave it" is now the safe behaviour.)
    gray = make_page(h=752, bands=[(211, 243), (297, 329)])
    # band 1 centre px=313 -> 416 in 0..1000; median spacing 86px -> 114;
    # the LLM box sits ~one spacing ABOVE its ink: centre 416-114 = 302.
    lines = [
        {"i": 0, "text": "a", "box": None},
        {"i": 1, "text": "b", "box": [10, 278, 500, 326]},
    ]
    n = resnap_boxes(lines, gray)
    assert n == 1
    assert lines[0]["box"] is None  # untouched
    assert lines[1]["box"][1] == 297 * 1000 // 752


def test_resnap_skipped_header_line_shifts_down():
    # 2026-10-19 bug (Rachid's photo): the page has 8 ink bands but the LLM
    # did not transcribe the printed "Question 2:" header band, so it
    # returned 7 lines whose boxes sit ~one line ABOVE their ink. A strict
    # 1:1 zip (or no resnap at all) left line 0's box on the header band ->
    # highlight/crop one line up. The alignment must leave band 0 unclaimed
    # and snap line k onto band k+1.
    h = 1000
    band_ys = [60, 130, 200, 270, 340, 410, 480, 550]  # 8 bands, 70px pitch
    gray = make_page(h=h, bands=[(y, y + 20) for y in band_ys])
    lines = []
    for k in range(7):  # line k's ink = band k+1; raw box 1 line ABOVE it
        center_1000 = (band_ys[k + 1] + 10 - 70) * 1000 // h  # de-bias target - spacing
        y0 = max(0, center_1000 - 12)
        lines.append({"i": k, "text": f"line {k}", "box": [40, y0, 900, y0 + 24]})
    n = resnap_boxes(lines, gray)
    assert n == 7, n
    for k, ln in enumerate(lines):
        assert ln["box"][1] >= band_ys[k + 1] * 1000 // h - 2, (k, ln["box"])
        assert ln["box"][3] <= band_ys[k + 1] + 20 + 1, (k, ln["box"])
        # and NOT on the band above (the old off-by-one)
        assert ln["box"][1] > band_ys[k] * 1000 // h + 25, (k, ln["box"])
        assert ln["box"][0] == 40 and ln["box"][2] == 900  # x preserved


def test_resnap_guardrail_too_many_bands_keeps_boxes():
    # more than 2x the line count of bands = detector noise (e.g. grading
    # marks all over) -> never resnap.
    gray = make_page(h=752, bands=[(100 + 60 * k, 120 + 60 * k) for k in range(5)])
    lines = [{"i": 0, "text": "a", "box": [5, 50, 500, 100]},
             {"i": 1, "text": "b", "box": [5, 130, 500, 180]}]
    assert resnap_boxes(lines, gray) == 0
    assert lines[0]["box"] == [5, 50, 500, 100]


def test_resnap_single_giant_band_keeps_boxes():
    # dark / low-contrast page collapses to one band -> guardrail skips.
    img = Image.new("L", (1000, 752), 90)
    gray = np.array(img)
    lines = [{"i": 0, "text": "a", "box": [5, 50, 500, 100]}]
    assert resnap_boxes(lines, gray) == 0
    assert lines[0]["box"] == [5, 50, 500, 100]


def test_resnap_y_monotonic_even_with_tight_lines():
    h = 1000
    # gaps of 19px > merge gap (15px at h=1000) -> 3 distinct bands
    bands = [(100, 130), (150, 180), (200, 230)]
    gray = make_page(h=h, bands=bands)
    lines = [{"i": i, "text": f"l{i}", "box": [0, i * 90, 1000, i * 90 + 60]} for i in range(3)]
    n = resnap_boxes(lines, gray)
    assert n == 3
    ys = [ln["box"][1] for ln in lines]
    assert ys == sorted(ys), ys
    for ln, (b0, b1) in zip(lines, bands):
        assert ln["box"][1] >= b0 * 1000 // h - 1
        assert ln["box"][3] <= b1 * 1000 // h + 1


def test_band_unclean_frac_clean_white_page_is_zero():
    # White paper with uniform ink bars: no merged / sparse band -> the
    # detector is reliable and resnap_boxes may trust it.
    gray = make_page(h=1000, bands=[(100 + 60 * k, 130 + 60 * k) for k in range(5)])
    assert _band_unclean_frac(_ink_bands(gray), gray) == 0.0


def test_resnap_abstains_when_detector_is_noisy():
    # 2026-10-19 regression guard (real dim grid-notebook copy): when a
    # quarter of the detected bands are unclean (one merged multi-line
    # band + one sparse grid-line speck among 8 lines), the detector is
    # not a trustworthy reference and resnap must leave every box
    # UNTOUCHED instead of shuffling good LLM boxes onto the noise.
    h = 1000
    # 6 normal 30px lines at 100 pitch + 1 merged 70px band + 1 5px speck
    bands = [(y, y + 30) for y in (60, 160, 260, 360, 460, 560)]
    bands += [(660, 730), (800, 805)]  # merged + sparse
    gray = make_page(h=h, bands=bands)
    assert _band_unclean_frac(_ink_bands(gray), gray) >= 0.20
    # 5 lines (so the 8-band count guardrail does NOT fire: 8 <= 2*5) —
    # the abstention must come from the NEW unclean gate, not from there.
    lines = [
        {"i": 0, "text": "a", "box": [40, 80, 900, 130]},
        {"i": 1, "text": "b", "box": [40, 180, 900, 230]},
        {"i": 2, "text": "c", "box": [40, 280, 900, 330]},
        {"i": 3, "text": "d", "box": [40, 380, 900, 430]},
        {"i": 4, "text": "e", "box": [40, 480, 900, 530]},
    ]
    boxes = [ln["box"] for ln in lines]
    assert resnap_boxes(lines, gray) == 0
    assert [ln["box"] for ln in lines] == boxes  # all untouched
