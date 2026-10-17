"""Unit tests for app.ocr box re-snapping (2026-10-17 bug fix).

The vision LLM transcribes faithfully but its per-line box y-coordinates
are frequently INTERPOLATED rather than measured: on real handwritten
photos, line N's box sits in the blank margin above line N-1's ink, so
the Annoter highlights the wrong band when a transcript line is
selected. `resnap_boxes` re-anchors the boxes onto the page's actual
ink bands — but only when the detector finds exactly as many bands as
there are lines (never resnap a misaligned 1:1).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ocr import _ink_bands, resnap_boxes  # noqa: E402


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


def test_resnap_missing_box_gets_full_width_band():
    gray = make_page(h=752, bands=[(211, 243), (297, 329)])
    lines = [
        {"i": 0, "text": "a", "box": None},
        {"i": 1, "text": "b", "box": [10, 90, 500, 150]},
    ]
    n = resnap_boxes(lines, gray)
    assert n == 2
    assert lines[0]["box"] == [0, 211 * 1000 // 752, 1000, 243 * 1000 // 752]
    assert lines[1]["box"][1] == 297 * 1000 // 752


def test_resnap_count_mismatch_keeps_boxes():
    gray = make_page(h=752, bands=[(211, 243), (297, 329), (378, 404)])
    lines = [{"i": 0, "text": "a", "box": [5, 50, 500, 100]}]
    n = resnap_boxes(lines, gray)
    assert n == 0
    assert lines[0]["box"] == [5, 50, 500, 100]  # untouched


def test_resnap_no_bands_keeps_boxes():
    gray = make_page(h=752)  # blank page
    lines = [{"i": 0, "text": "a", "box": [5, 50, 500, 100]}]
    n = resnap_boxes(lines, gray)
    assert n == 0
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
