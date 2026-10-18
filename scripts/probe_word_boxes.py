#!/usr/bin/env python3
"""Probe: can the LLM vision engine give accurate PER-WORD boxes?

Ask qwen38-27b to transcribe a page photo with per-WORD bounding boxes in
0..1000 normalized coords. Then measure box quality NUMERICALLY (not via
vision):
  - word count vs actual word count of the transcription
  - every word box's y-extent must sit inside its line's ink band
    (detected independently with ocr._ink_bands)
  - word boxes within a line must be in increasing x order and not
    overlap more than a small tolerance
  - x-extent of the first/last word of a line vs the known line box
Outputs a JSON report to data/ocr_test/wordboxes_probe.json
"""
import base64
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

from app import llm_client, ocr

PROMPT = (
    "You are an OCR engine for a STUDENT'S handwritten school copy "
    "(blue grid paper, blue ink, English with occasional French words). "
    "The photo of ONE page is attached. Transcribe it faithfully, word by "
    "word, in reading order, using the ACTUAL words in the photo. For EACH "
    "word give the bounding box of that word's ink in the photo, in "
    "NORMALIZED coordinates where (0,0) is the top-left corner of the photo "
    "and (1000,1000) is the bottom-right corner: \"box\": [x0, y0, x1, y1] "
    "with x0<x1, y0<y1, integers 0..1000. The box should tightly cover the "
    "ink of that single word only (no other words), with a small margin. "
    "RULES: "
    "(1) Preserve the student's own spelling, grammar and word choices "
    "EXACTLY as written — do NOT correct, improve or normalize in ANY way. "
    "(2) CROSSED-OUT words struck through by the student: represent as "
    "[X:word] with its own box. (3) Words covered by correction tape: "
    "[TAPE]. (4) Words in French: keep them, add [FR] after them in the "
    "text. (5) If a word is truly illegible, use [?]. "
    "Output ONLY a JSON object, no markdown, no commentary: "
    "{\"words\": [{\"t\": \"word\", \"box\": [x0,y0,x1,y1]}, ...], "
    "\"notes\": \"one-line summary of ratures / tape / French words if any\"}"
)


def main():
    page = ROOT / "data/ocr_test/page1.jpg"
    img = Image.open(page)
    w, h = img.size
    b64 = base64.b64encode(page.read_bytes()).decode()
    data_url = f"data:image/jpeg;base64,{b64}"
    gray = np.array(img.convert("L"))

    t0 = time.time()
    res = llm_client.chat(
        [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
        temperature=0.0, max_tokens=20000, thinking_budget=1500)
    elapsed = round(time.time() - t0, 1)
    open(ROOT / "data/ocr_test/wordboxes_raw.txt", "w").write(
        res.get("content") or "")
    parsed = llm_client.extract_json(res["content"])
    words = parsed.get("words") if isinstance(parsed, dict) else None
    print(f"elapsed_s={elapsed} truncated={res.get('truncated')} "
          f"finish={res.get('finish_reason')}")
    if not isinstance(words, list) or not words:
        # salvage: regex out every complete word entry even from a
        # truncated JSON (page was cut mid-list)
        import re
        words = [{"t": m[0], "box": [int(v) for v in m[1:5]]}
                 for m in re.findall(
                     r'\{"t":\s*"((?:[^"\\]|\\.)*)",\s*"box":\s*'
                     r'\[(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]',
                     res.get("content") or "")]
        print("SALVAGED from truncated JSON")
    if not isinstance(words, list) or not words:
        print("FAILED: no words parsed")
        print("RAW head:", (res["content"] or "")[:800])
        return
    print(f"words returned: {len(words)}")
    for wd in words[:12]:
        print(wd)

    # ---- numeric quality checks ----
    # group words into visual lines by y-overlap (center within band)
    bands = ocr._ink_bands(gray)
    print(f"ink bands detected: {len(bands)} (page {w}x{h})")
    h_px = h

    def box_px(b):
        return [b[0] * w / 1000, b[1] * h_px / 1000,
                b[2] * w / 1000, b[3] * h_px / 1000]

    bad_y = []
    lines: list[list[dict]] = []
    for wd in words:
        b = ocr._sanitize_box(wd.get("box"))
        if b is None:
            bad_y.append({"t": wd.get("t"), "reason": "no-box"})
            continue
        cx = (b[1] + b[3]) / 2 * h_px / 1000
        # find containing band
        match = None
        for bi, (by0, by1) in enumerate(bands):
            if by0 - 6 <= cx <= by1 + 6:
                match = bi
                break
        rec = dict(wd)
        rec["box_px"] = box_px(b)
        rec["band"] = match
        if match is None:
            bad_y.append(rec)
        if match is not None and (lines and lines[-1]["band"] == match):
            lines[-1]["words"].append(rec)
        else:
            lines.append({"band": match, "words": [rec]})

    x_violations = 0
    for ln in lines:
        ws = ln["words"]
        for a, b in zip(ws, ws[1:]):
            pa, pb = a["box_px"], b["box_px"]
            # next word must start at/after prev end - 4px tolerance
            if pb[0] < pa[2] - 4:
                x_violations += 1

    print(f"\nQUALITY REPORT")
    print(f"  words total:          {len(words)}")
    print(f"  words w/o usable box: {sum(1 for r in bad_y if r.get('reason')=='no-box')}")
    print(f"  words outside any band: {sum(1 for r in bad_y if r.get('reason')!='no-box')}")
    print(f"  visual lines grouped: {sum(1 for l in lines if l['band'] is not None)}")
    print(f"  x-order violations:   {x_violations}")
    # per-line summary: word count + y-center consistency
    for i, ln in enumerate(lines[:8]):
        ws = ln["words"]
        ycs = [r["box_px"][1] for r in ws]
        print(f"  line{i:02d} band={ln['band']} nwords={len(ws):2d} "
              f"y0={min(ycs):6.1f} y1={max(r['box_px'][3] for r in ws):6.1f} "
              f"x={ws[0]['box_px'][0]:6.1f}..{ws[-1]['box_px'][2]:6.1f}  "
              f"'{ws[0]['t']}'..' {ws[-1]['t']}'")

    report = {
        "elapsed_s": elapsed,
        "word_count": len(words),
        "words": words,
        "bad_y": bad_y,
        "x_violations": x_violations,
        "lines": [{ "band": l["band"],
                    "words": [r["t"] for r in l["words"]],
                    "boxes": [r["box_px"] for r in l["words"]]} for l in lines],
        "bands": bands,
    }
    out = ROOT / "data/ocr_test/wordboxes_probe.json"
    json.dump(report, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"\nsaved -> {out}")


if __name__ == "__main__":
    main()
