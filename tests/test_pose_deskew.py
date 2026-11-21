"""Deterministic deskew / missing-EXIF orientation (2026-11-21).

Phone photos frequently arrive with NO EXIF Orientation tag (flat-sheet
scans, apps that strip metadata) so the PIXELS are rotated.  ``app.pose``
estimates the corrective rotation from the pixels alone (mod-180 line
alignment + 0°/180° hampes/majuscules baseline asymmetry);
``app.media._normalize_orientation`` applies it at upload when confidence
is high enough, and returns the ORIGINAL BYTES when nothing needed
correcting (no re-encode, no quality loss).

Unit-level: no DB, no server, no LLM.  Run:
    /home/tibo/.hermes/hermes-agent/venv/bin/python tests/test_pose_deskew.py
"""
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# throwaway DB path so any import-time db access is harmless
import os
_tmp = Path(tempfile.mkdtemp(prefix="bg_pose_"))
os.environ.setdefault("BABELGRADE_DB_PATH", str(_tmp / "test.db"))

from PIL import Image, ImageDraw, ImageFont

from app.pose import estimate_orientation
from app.media import _normalize_orientation

ok = True
def check(name, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))
    return cond


def make_clean(size=1400):
    """A realistic upright 'French composition' page (text + ruled lines)."""
    words = ["de l'ete passe au bord de la mer", "ou nous jouions pendant des heures",
             "entieres sous le ciel bleu et doux.", "La vague roulait sous nos pieds,",
             "froide et douce, le sable etait chaud", "et s'etendait jusqu'a l'horizon bleu.",
             "Nous courions le long du rivage", "en riant fort, les cheveux pleins",
             "de sable et de sel, l'ete etait", "magnifique et je n'oublierai jamais."]
    img = Image.new("RGB", (size, size), (252, 251, 248))
    d = ImageDraw.Draw(img)
    f_big = ImageFont.truetype("/usr/share/fonts/truetype/dejaVu/DejaVuSerif-Bold.ttf", 44)
    f_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejaVu/DejaVuSerif.ttf", 34)
    d.text((size // 2 - 360, size // 2 - 470), "French composition", font=f_big, fill=(20, 20, 90))
    y = size // 2 - 350
    for ln in words:
        d.line([(size // 2 - 430, y - 9), (size // 2 + 430, y - 9)], fill=(218, 226, 236), width=2)
        d.text((size // 2 - 420, y), ln, font=f_sm, fill=(12, 12, 12))
        y += 106
    return img


def norm(a):
    a = a % 360
    return a - 360 if a > 180 else a


def to_jpeg(im, q=90):
    b = io.BytesIO()
    im.save(b, "JPEG", quality=q)
    return b.getvalue()


up = make_clean()

# --- 1. estimator: all common phone angles exact (angle error < 0.5°) --------
print("--- estimator on pixel-rotated photos (no EXIF tag) ---")
for tilt in [0, 90, 180, -90, 270]:
    P = up.rotate(tilt, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255)) \
        if tilt else up
    r = estimate_orientation(to_jpeg(P))
    err = abs(norm(r["angle_ccw"]) - norm(-tilt))
    err = min(err, 360 - err)
    check(f"tilt {tilt:+4}: angle within 0.5°", err < 0.5,
          f"est={r['angle_ccw']:.2f} err={err:.2f} conf={r['confidence']:.2f}")

# --- 2. small deskews (handheld tilt 8° / -12°) -----------------------------
for tilt in [8, -12]:
    P = up.rotate(tilt, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))
    r = estimate_orientation(to_jpeg(P))
    err = abs(norm(r["angle_ccw"]) - norm(-tilt))
    err = min(err, 360 - err)
    check(f"tilt {tilt:+4}: angle within 0.5°", err < 0.5,
          f"est={r['angle_ccw']:.2f} err={err:.2f} conf={r['confidence']:.2f}")

# --- 3. _normalize_orientation end-to-end ------------------------------------
print("--- _normalize_orientation ---")
# 3a. upright photo, no tag -> byte-identical (no re-encode)
data_up = to_jpeg(up)
check("upright no-tag: byte-identical passthrough",
      _normalize_orientation(data_up, "jpg") == data_up)

# 3b. 180°-rotated pixels, no tag -> corrected + re-encoded
P180 = up.rotate(180, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))
data180 = to_jpeg(P180)
out180 = _normalize_orientation(data180, "jpg")
check("180° pixels: bytes changed (corrected + re-encoded)", out180 != data180)
im180 = Image.open(io.BytesIO(out180))
check("180° pixels: size unchanged", im180.size == P180.size, str(im180.size))
# the re-encoded file must read as upright again -> re-estimating gives ~0°
r180 = estimate_orientation(out180)
check("180° pixels: result reads upright (~0°)", abs(r180["angle_ccw"]) < 0.5,
      f"angle={r180['angle_ccw']:.2f}")

# 3c. 90° CW-rotated pixels, no tag -> corrected; portrait restored
P90 = up.rotate(-90, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))
out90 = _normalize_orientation(to_jpeg(P90), "jpg")
im90 = Image.open(io.BytesIO(out90))
check("90° CW pixels: corrected (bytes differ)", out90 != to_jpeg(P90))
check("90° CW pixels: back to near-square upright size",
      abs(im90.size[0] - P90.size[1]) <= 4 and abs(im90.size[1] - P90.size[0]) <= 4,
      f"{im90.size} vs {P90.size}")

# 3d. blank page (no ink) -> byte-identical, never rotated
blank = to_jpeg(Image.new("RGB", (800, 1000), (250, 250, 250)))
check("blank page: byte-identical", _normalize_orientation(blank, "jpg") == blank)

# 3e. PNG round-trip: 180°-rotated PNG corrected, format preserved
P180p = up.rotate(180, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))
b = io.BytesIO(); P180p.save(b, "PNG")
data_png = b.getvalue()
out_png = _normalize_orientation(data_png, "png")
check("PNG 180°: corrected", out_png != data_png)
im_png = Image.open(io.BytesIO(out_png))
check("PNG 180°: still PNG", im_png.format == "PNG", str(im_png.format))

# 3f. garbage / non-image -> no raise, original bytes back
check("garbage bytes: no raise, original returned",
      _normalize_orientation(b"not an image at all", "jpg") == b"not an image at all")

print()
print("ALL GREEN" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
