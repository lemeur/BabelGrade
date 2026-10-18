#!/usr/bin/env python3
"""Generate mock data: oral word timings (Whisper) + written photo/OCR.
Oral: transcribe test_oral.ogg -> words[{w,start,end,prob}] + segments.
Written: page1.jpg + final.json OCR lines (already in data/ocr_test/).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import whisper

out = ROOT / "mock-hybrid"
out.mkdir(exist_ok=True)

# ---- oral ----
tr = whisper.transcribe(str(ROOT / "test_oral.ogg"), language="en")
oral = {
    "text": tr["text"],
    "duration_s": tr["duration_s"],
    "segments": tr["segments"],
    "words": tr["words"],
}
json.dump(oral, open(out / "oral.json", "w"), ensure_ascii=False, indent=1)
print(f"oral: {len(oral['words'])} words, {len(oral['segments'])} segments, "
      f"{oral['duration_s']}s, wpm {tr['wpm']}")

# ---- written: copy photo + OCR ----
import shutil
shutil.copy(ROOT / "data/ocr_test/page1.jpg", out / "page1.jpg")
final = json.load(open(ROOT / "data/ocr_test/final.json"))
written = {"page": final["pages"][0]}
json.dump(written, open(out / "written.json", "w"), ensure_ascii=False, indent=1)
lines = written["page"]["lines"]
print(f"written: {written['page']['w']}x{written['page']['h']}, "
      f"{len(lines)} lines, "
      f"{sum(len(l['text'].split()) for l in lines)} words")
print("data ->", out)
