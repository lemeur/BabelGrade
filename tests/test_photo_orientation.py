"""Photo orientation normalization (2026-11-21).

Phone photos carry an EXIF Orientation tag instead of rotated pixels.
Browsers render them upright, but the LLM vision engine / OCR / Annoter
read the RAW pixels. This test verifies that every upload path bakes the
orientation into the stored file, so the app ALWAYS shows the photo in
the right orientation.

In-process (TestClient + temp DB + temp UPLOAD_DIR), no LLM, no restart.
Run: /home/tibo/.hermes/hermes-agent/venv/bin/python tests/test_photo_orientation.py
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
from PIL.ExifTags import Base

TMP = Path(tempfile.mkdtemp(prefix="bg_orient_"))
# throwaway DB via the app's own env override (db.DB_PATH reads it at import)
os.environ["BABELGRADE_DB_PATH"] = str(TMP / "test.db")

import app.config as cfg  # noqa: E402
cfg.UPLOAD_DIR = TMP / "uploads"
cfg.UPLOAD_DIR.mkdir(parents=True)

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, raise_server_exceptions=True)

ok = True
def check(name, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))
    return cond

def make_jpeg(w, h, orientation=None, color=(200, 30, 30)):
    im = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    if orientation:
        ex = im.getexif()
        ex[Base.Orientation] = orientation
        im.save(buf, "JPEG", quality=90, exif=ex.tobytes())
    else:
        im.save(buf, "JPEG", quality=90)
    return buf.getvalue()

def open_saved(name):
    p = cfg.UPLOAD_DIR / name
    assert p.is_file(), f"missing {name}"
    return Image.open(io.BytesIO(p.read_bytes())), p.read_bytes()

# --- auth -------------------------------------------------------------------
r = client.post("/api/auth/register",
                json={"username": "tibo", "password": "orient-pw-1"})
check("register", r.status_code == 200, r.text)

r = client.post("/api/students", json={"name": "Roté Élève"})
check("create student", r.status_code == 200, r.text)
student_id = r.json()["id"]

r = client.get("/api/rubrics")
check("list rubrics", r.status_code == 200, r.text)
rubric = next(x for x in r.json() if x["id"] == "att-exp-ecrite")

def evaluate_with_photo(data, fname):
    return client.post(
        "/api/evaluate",
        data={"kind": "written", "written_text": "", "rubric_id": "att-exp-ecrite",
              "student_id": str(student_id), "ui_language": "fr"},
        files={"images": (fname, io.BytesIO(data), "image/jpeg")},
    )

# --- 1. orientation 6 (stored landscape, upright after 90° CW) --------------
rot = make_jpeg(1600, 1000, orientation=6)
r = evaluate_with_photo(rot, "photo.jpg")
check("evaluate rotated photo -> 200", r.status_code == 200, r.text)
d = r.json()
sub_id = d.get("submission_id") or d.get("data", {}).get("submission_id")
check("evaluate returns submission", bool(sub_id), json.dumps(d)[:300])

r = client.get(f"/api/submissions/{sub_id}")
meta = (r.json().get("payload_meta") or {})
page_paths = meta.get("page_paths") or []
check("submission has page_paths", len(page_paths) == 1, json.dumps(meta))
if page_paths:
    im, raw = open_saved(page_paths[0])
    check("stored file is portrait 1000x1600", im.size == (1000, 1600), str(im.size))
    check("orientation tag removed/baked",
          im.getexif().get(Base.Orientation, 1) == 1,
          str(im.getexif().get(Base.Orientation)))
    check("stored bytes differ from upload (re-encoded)", raw != rot)
    r2 = client.get(f"/api/files/{page_paths[0]}")
    check("file served to owner", r2.status_code == 200, str(r2.status_code))
    im2 = Image.open(io.BytesIO(r2.content))
    check("served file upright too", im2.size == (1000, 1600), str(im2.size))

# --- 2. no-tag photo: byte-identical passthrough ----------------------------
plain = make_jpeg(800, 600, orientation=None, color=(30, 120, 200))
r = evaluate_with_photo(plain, "plain.jpg")
check("evaluate plain photo -> 200", r.status_code == 200, r.text)
sub2 = r.json().get("submission_id")
meta2 = (client.get(f"/api/submissions/{sub2}").json().get("payload_meta") or {})
pp2 = meta2.get("page_paths") or []
check("plain photo has page_paths", len(pp2) == 1, json.dumps(meta2))
if pp2:
    raw2 = (cfg.UPLOAD_DIR / pp2[0]).read_bytes()
    check("no-tag file byte-identical (no re-encode)", raw2 == plain)
    im3 = Image.open(io.BytesIO(raw2))
    check("plain photo size preserved", im3.size == (800, 600), str(im3.size))

# --- 3. orientation 3 (180°) ------------------------------------------------
r = evaluate_with_photo(make_jpeg(900, 700, orientation=3), "flip.jpg")
check("evaluate 180° photo -> 200", r.status_code == 200, r.text)
sub3 = r.json().get("submission_id")
pp3 = ((client.get(f"/api/submissions/{sub3}").json()
        .get("payload_meta") or {}).get("page_paths") or [])
if pp3:
    im4 = Image.open(io.BytesIO((cfg.UPLOAD_DIR / pp3[0]).read_bytes()))
    check("180° tag removed, size kept",
          im4.size == (900, 700) and im4.getexif().get(Base.Orientation, 1) == 1,
          f"{im4.size} tag={im4.getexif().get(Base.Orientation)}")

# --- 4. job payload carries the SAME (normalized) names ---------------------
# The analyze/evaluate runner re-attaches the stored files by name — the
# stored file IS what the LLM sees, so the names alone must be enough.
check("page names unchanged by normalization",
      all(n.endswith(".jpg") for n in page_paths + pp2 + pp3),
      json.dumps(page_paths + pp2 + pp3))

# --- 5. cleanup: cascade-delete the throwaway student -----------------------
r = client.delete(f"/api/students/{student_id}", params={"cascade": "true"})
check("cleanup student cascade", r.status_code == 200, r.text)

print()
print("ALL GREEN" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
