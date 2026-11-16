#!/usr/bin/env python3
"""Functional word-box validation on the REAL photo (page1.jpg).

The feature needs, per selection = first-word..last-word:
  (a) every word box sits inside its OCR line's y-band
  (b) word boxes within a line do not overlap horizontally (readable as
      separate words)
  (c) the first/last words' x-extents roughly bound the selection span so a
      crop with margin is sensible
No ink coverage (unreliable on this low-contrast blue-grid photo); pure
geometry against the trusted line boxes from final.json.
"""
import json
import statistics
from pathlib import Path

ROOT = Path("/home/tibo/babelgrade")
report = json.loads(open(ROOT / "data/ocr_test/wordboxes_probe.json").read())
final = json.loads(open(ROOT / "data/ocr_test/final.json").read())
page = final["pages"][0]
W, H = page["w"], page["h"]
words = report["words"]

# line boxes (trusted, resnapped) in 0..1000
lineboxes = {ln["i"]: ln["box"] for ln in page["lines"] if ln.get("box")}


def px(b):
    return [b[0] * W / 1000, b[1] * H / 1000,
            b[2] * W / 1000, b[3] * H / 1000]


# assign each word to the line whose y-band contains its center
def line_of(wb):
    cy = (wb[1] + wb[3]) / 2
    best, bestd = None, 1e9
    for i, lb in lineboxes.items():
        lo, hi = lb[1], lb[3]
        if lo - 6 <= cy <= hi + 6:
            return i
        bestd = min(bestd, min(abs(cy - lo), abs(cy - hi)))
        best = i
    return best


by_line = {}
for j, wd in enumerate(words):
    lb = ocr_line = line_of(wd["box"])
    by_line.setdefault(lb, []).append(j)

print(f"lines with words: {len(by_line)} / {len(lineboxes)}")
inside_frac = []
overlap_frac = []
span_ok = []
for i, idxs in sorted(by_line.items()):
    idxs.sort(key=lambda j: px(words[j]["box"])[0])  # left->right
    lb_px = px(lineboxes[i])
    ltop, lbot = lb_px[1], lb_px[3]
    ins = 0
    for j in idxs:
        wp = px(words[j]["box"])
        cy = (wp[1] + wp[3]) / 2
        if ltop - 12 <= cy <= lbot + 12:
            ins += 1
    inside_frac.append(ins / len(idxs))
    # horizontal overlap between consecutive words
    ov = 0
    for a, b in zip(idxs, idxs[1:]):
        pa, pb = px(words[a]["box"]), px(words[b]["box"])
        inter = min(pa[2], pb[2]) - max(pa[0], pb[0])
        width = min(pa[2] - pa[0], pb[2] - pb[0])
        if width > 0 and inter / width > 0.35:
            ov += 1
    n_pairs = len(idxs) - 1
    overlap_frac.append(ov / n_pairs if n_pairs else 0.0)
    # selection span: union x of the line's words vs the line box x
    x0 = min(px(words[j]["box"])[0] for j in idxs)
    x1 = max(px(words[j]["box"])[2] for j in idxs)
    lbox_x0, lbox_x1 = lb_px[0], lb_px[2]
    # union should cover a good fraction of the line's ink width
    union = x1 - x0
    line_w = lbox_x1 - lbox_x0
    span_ok.append(union / line_w if line_w else 0.0)

inside_frac = statistics.mean(inside_frac)
overlap_frac = statistics.mean(overlap_frac)
span_ok = statistics.mean(span_ok)
print(f"\n(a) word-center inside its line y-band : {inside_frac:.0%}")
print(f"(b) consecutive words overlap >35%      : {overlap_frac:.0%}  (want ~0)")
print(f"(c) union of word x vs line x-width     : {span_ok:.0%}  (want high)")

# a concrete selection example: line 5, words 2..6
i = 5
idxs = sorted(by_line[i], key=lambda j: px(words[j]["box"])[0])
sel = idxs[2:7]
wp0 = px(words[sel[0]]["box"]); wp1 = px(words[sel[-1]]["box"])
crop = [wp0[0] - 30, wp0[1] - 30, wp1[2] + 30, wp1[3] + 30]
print(f"\nexample selection line {i} words 3..7:")
for j in sel:
    print(f"   '{words[j]['t']}'  {px(words[j]['box'])}")
print(f"   crop-with-30px-margin (px): {crop}")
json.dump({"inside": inside_frac, "overlap": overlap_frac, "span": span_ok},
          open(ROOT / "data/ocr_test/wordboxes_functional.json", "w"))
print("\nsaved wordboxes_functional.json")
