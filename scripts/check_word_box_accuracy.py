#!/usr/bin/env python3
"""Numeric accuracy check of the LLM's PER-WORD boxes (probe round 2).

No vision model involved: for every word box the script measures the ACTUAL
ink inside and around the box on the real photo:
  - ink coverage  : fraction of dark pixels strictly inside the box
  - ink in 2x box : fraction of dark pixels in a box expanded by 50%
                    (catches boxes that are too small / offset)
  - ink OUTSIDE   : fraction of dark pixels in the 2x box that lie OUTSIDE
                    the box (catches boxes that miss part of the word)
  - line y-band check: word y-center vs the ink band of its visual line
Groups words into visual lines by y-center clustering and checks
x-order inside each line.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

report = json.load(open(ROOT / "data/ocr_test/wordboxes_probe.json"))
final = json.load(open(ROOT / "data/ocr_test/final.json"))
page = final["pages"][0]
w, h = page["w"], page["h"]

img = Image.open(ROOT / "data/ocr_test/page1.jpg")
gray = np.array(img.convert("L"))
dark = gray < 140  # ink mask (handwritten blue ink on white)

# ---- group words into visual lines by y-center clustering ----
words = report["words"]
cent = []
for wd in words:
    b = wd["box"]
    cent.append(((b[1] + b[3]) / 2) * h / 1000)
order = sorted(range(len(words)), key=lambda i: cent[i])
lines = []
for i in order:
    if lines and cent[i] - cent[lines[-1][-1]] < h * 0.018:
        lines[-1].append(i)
    else:
        lines.append([i])

print(f"page {w}x{h}, {len(words)} words -> {len(lines)} visual lines")
print(f"known line boxes (final.json): {len(page['lines'])}")

row_report = []
all_inside = []
all_outside = []
for li, idxs in enumerate(lines):
    idxs = sorted(idxs)  # reading order
    ys = [cent[i] for i in idxs]
    y0, y1 = min(ys) - 0.12 * h, max(ys) + 0.12 * h
    y0i, y1i = int(max(0, y0)), int(min(h, y1))
    # x-order check
    xviol = 0
    viol_words = []
    for a, b in zip(idxs, idxs[1:]):
        pa = words[a]["box"]; pb = words[b]["box"]
        if pb[0] * w / 1000 < pa[2] * w / 1000 - 5:
            xviol += 1
            viol_words.append(words[a]["t"] + ">" + words[b]["t"])
    # per-word ink measurement
    ins = out = 0
    per_word = []
    for i in idxs:
        x0, y0b, x1, y1b = [v * w / 1000 if k % 2 == 0 else v * h / 1000
                            for k, v in enumerate(words[i]["box"])]
        x0, x1 = int(min(x0, x1)), int(max(x0, x1))
        y0b, y1b = int(min(y0b, y1b)), int(max(y0b, y1b))
        # expanded box: +50% each side
        ew = max(4, int((x1 - x0) * 0.5))
        eh = max(4, int((y1b - y0b) * 0.5))
        ex0, ey0 = max(0, x0 - ew), max(0, y0b - eh)
        ex1, ey1 = min(w, x1 + ew), min(h, y1b + eh)
        big = dark[ey0:ey1, ex0:ex1]
        ix0, iy0 = x0 - ex0, y0b - ey0
        small = big[iy0:iy0 + (y1b - y0b), ix0:ix0 + (x1 - x0)]
        tin = small.sum()
        tout = int(big.sum() - tin)
        inside = tin / max(1, tin + tout)
        per_word.append({
            "t": words[i]["t"],
            "box_px": [int(x0), int(y0b), int(x1), int(y1b)],
            "ink_in": int(tin), "ink_out": tout,
            "coverage": round(inside, 3),
        })
        all_inside.append(inside)
        all_outside.append(tout)
    avg = float(np.mean([p["coverage"] for p in per_word]))
    row_report.append({
        "line": li, "nwords": len(idxs), "xviol": xviol,
        "xviol_pairs": viol_words, "avg_coverage": round(avg, 3),
        "y": [int(ys[0]), int(ys[-1])],
        "words": per_word,
    })
    print(f"line{li:02d} n={len(idxs):2d} xviol={xviol} "
          f"avg_cov={avg:.2f}  '{words[idxs[0]]['t']}'..'{words[idxs[-1]]['t']}'"
          + (f"  violations:{viol_words[:4]}" if viol_words else ""))

import statistics
print("\nGLOBAL")
print(f"  avg word-box coverage (ink inside vs expanded-box ink): "
      f"{statistics.mean(all_inside):.2%}")
print(f"  words with <50% coverage: "
      f"{sum(1 for v in all_inside if v < 0.5)}/{len(all_inside)}")
low = [r for rr in row_report for r in rr["words"] if r["coverage"] < 0.5]
for r in low[:20]:
    print(f"    LOW {r['coverage']:.2f}  '{r['t']}' at {r['box_px']}")
tot_xv = sum(r["xviol"] for r in row_report)
print(f"  total x-order violations: {tot_xv} "
      f"({tot_xv * 100 // max(1, len(words) - len(lines))}%)")

# ---- line-band check vs the known LLM line boxes (final.json) ----
# group words' y-centers onto the known lines' y bands
klines = page["lines"]
mismatch = 0
for li, idxs in enumerate(lines):
    yc = sum(cent[i] for i in idxs) / len(idxs)
    best = None
    for k in klines:
        b = k.get("box")
        if not b:
            continue
        lo, hi = b[1] * h / 1000, b[3] * h / 1000
        if lo - 10 <= yc <= hi + 10:
            best = k["i"]
            break
    status = "ok" if best == li else f"MISMATCH(known={best})"
    if best != li:
        mismatch += 1
    if li < len(klines):
        print(f"line{li:02d} yc={yc:6.1f} -> known line {best} {status} "
              f"n={len(idxs)}")
print(f"\nline-band mismatches vs known line boxes: {mismatch}/{len(lines)}")

out = ROOT / "data/ocr_test/wordboxes_accuracy.json"
json.dump({"lines": row_report,
           "avg_coverage": round(statistics.mean(all_inside), 4),
           "low_coverage_words": low,
           "line_band_mismatches": mismatch},
          open(out, "w"), ensure_ascii=False, indent=1)
print(f"\nsaved -> {out}")
