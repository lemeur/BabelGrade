"""One-shot real-photo OCR test (2026-10-17, tibo's student copies).

Runs the EXACT production pipeline (ocr.ocr_submission, LLM-direct) on
data/ocr_test/pageN.jpg and writes data/ocr_test/final.json. Used to
evaluate fidelity on genuine handwritten French-ESL copies.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import ocr  # noqa: E402

TEST = Path(__file__).resolve().parent.parent / "data" / "ocr_test"

names = sorted(TEST.glob("page*.jpg"))
assert names, f"no page*.jpg in {TEST}"
# ocr_submission takes (image_names, upload_dir); the test photos live in
# data/ocr_test itself, so use that directory as the "upload dir".
result = ocr.ocr_submission([p.name for p in names], TEST, language="en")
(TEST / "final.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
for pg in result["pages"]:
    print(f"{pg['name']}: {len(pg['lines'])} lignes, engine={pg.get('engine')}")
print("WROTE", TEST / "final.json")
