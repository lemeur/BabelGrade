"""Image enhancement for OCR of student copy photos.

Two tiers, deliberately separated by how much they may change the image's
coordinate frame:

* **`enhance_for_ocr(img)` — SLICE 1, geometry-preserving.** Only in-place
  pixel transforms that keep the EXACT same width/height: median-filter
  denoise + grid local-contrast equalisation. Because the output has the
  same dimensions, Tesseract's line boxes stay in the ORIGINAL photo's
  coordinate space, so the annotation UI's band crops (which cut from the
  raw upload using the stored x0/y0/x1/y1) stay aligned, and the
  `truncated_right` flag (ink reaches the photo's right edge) keeps its
  meaning. Never raises — on any error it returns the input unchanged.

* **`preprocess_page(path)` — SLICE 3, geometry-changing (NOT wired yet).**
  Ink-crop + global deskew + upscale. These change w/h, so they CANNOT be
  fed to Tesseract unless the preprocessed image is also persisted and the
  page's `w/h`/`name` repointed at it (and `truncated_right` re-derived
  from the original photo). Deferred until validated on real handwritten
  photos — an unvalidated deskew that mis-rotates a real page would be
  worse than no deskew.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

MIN_LINE_HEIGHT = 70   # (Slice 3) below this, upscale x2
UPSCALE_FACTOR = 2
DESKREW_RANGES = (-8.0, 8.0)   # degrees, both bounds inclusive
DESKREW_STEP = 0.5


# ---------------------------------------------------------------------------
# SLICE 1 — geometry-preserving enhancement (in-place, same w/h)
# ---------------------------------------------------------------------------

def enhance_for_ocr(img: Image.Image) -> Image.Image:
    """Enhance a page photo for Tesseract WITHOUT changing its size.

    Returns a new grayscale image the SAME dimensions as the input. On any
    failure returns the input converted to grayscale (never raises).

    What it does / doesn't do (measured on a noisy handwritten fixture,
    2026-10-09): the default is a grid local-contrast stretch only. A 3x3
    MEDIAN filter was tested and FOUND TO HARM thin handwritten strokes —
    it dropped tesseract's word recovery from 19/19 to 17-18/19 (it
    erodes the thin ink that IS the text). Contrast-only stayed at 19/19
    and can still rescue low-contrast / uneven-lamp photos. So the median
    is deliberately NOT in the default path; it remains available as
    `median3` if a future noisy-photo case proves it worth the risk.
    """
    g = img.convert("L")
    try:
        arr = np.asarray(g, dtype=np.uint8)
        enh = _grid_contrast(arr)
        return Image.fromarray(enh, mode="L")
    except Exception:  # noqa: BLE001 — enhancement must never break OCR
        return g


def median3(img: Image.Image) -> Image.Image:
    """3x3 median filter, same-size. NOT used in the default path — see
    enhance_for_ocr's note: it degrades thin handwriting. Kept for the off
    chance a very noisy photo case needs it and the teacher accepts the
    trade-off."""
    return img.convert("L").filter(ImageFilter.MedianFilter(3))


def _grid_contrast(gray: np.ndarray, grid: int = 8,
                   lo_pct: int = 2, hi_pct: int = 98) -> np.ndarray:
    """Per-cell linear stretch to [0,255] using robust percentiles, then a
    light blur to hide cell seams. Keeps flat white margins white (cells
    where lo~hi get left untouched)."""
    h, w = gray.shape
    gh, gw = max(1, h // grid), max(1, w // grid)
    out = np.empty_like(gray)
    for i in range(grid):
        i0, i1 = i * gh, min(h, (i + 1) * gh)
        for j in range(grid):
            j0, j1 = j * gw, min(w, (j + 1) * gw)
            cell = gray[i0:i1, j0:j1]
            lo, hi = np.percentile(cell, lo_pct), np.percentile(cell, hi_pct)
            if hi - lo < 12:  # near-uniform (paper) — leave as-is
                out[i0:i1, j0:j1] = cell
                continue
            norm = np.clip((cell.astype(np.float32) - lo) / (hi - lo), 0, 1)
            out[i0:i1, j0:j1] = (norm * 255).astype(np.uint8)
    return np.asarray(Image.fromarray(out).filter(ImageFilter.GaussianBlur(1)))


# ---------------------------------------------------------------------------
# SLICE 3 — geometry-changing pipeline (crop / deskew / upscale), NOT wired
# ---------------------------------------------------------------------------

def _gray(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"))


def _ink_crop(gray: np.ndarray):
    mask = gray < 200
    if not mask.any():
        return None
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    return (int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1)


def deskew_angle(gray: np.ndarray) -> float:
    """Global page tilt in degrees via dark-row histogram peak. 0 if none
    beats horizontal. (Slice 3 helper — not used until the page image is
    persisted as the preprocessed version.)"""
    mask = (gray < 160).astype(np.uint8)
    w = gray.shape[1]
    scale = min(1.0, 1000.0 / w)
    if scale < 1.0:
        small = Image.fromarray(mask * 255).resize(
            (int(w * scale), int(gray.shape[0] * scale)), Image.BILINEAR)
        mask = (np.asarray(small) > 100).astype(np.uint8)

    def score(angle: float) -> float:
        if angle:
            m = Image.fromarray(mask * 255).rotate(angle, resample=Image.BILINEAR,
                                                  expand=True, fillcolor=0)
            m = (np.asarray(m) > 100).astype(np.uint8)
        else:
            m = mask
        rows = m.sum(axis=1)
        return float(rows.max()) / rows.sum() if rows.sum() else 0.0

    best, best_a = score(0.0), 0.0
    a = DESKREW_RANGES[0]
    while a <= DESKREW_RANGES[1] + 1e-9:
        if a:
            s = score(a)
            if s > best:
                best, best_a = s, a
        a += DESKREW_STEP
    return best_a


def preprocess_page(path: str | Path) -> tuple[Image.Image, dict]:
    """SLICE 3: crop-to-ink + deskew + denoise + equalise + upscale.

    Returns (image, meta). Changes the coordinate frame — caller MUST
    persist this image and repoint the page's w/h/name at it, and re-derive
    `truncated_right` from the original photo. NOT wired into ocr.py yet.
    """
    p = Path(path)
    meta: dict = {"ok": True, "steps": {}}
    try:
        img = Image.open(p).convert("L")
        meta["orig_size"] = img.size
        gray = _gray(img)
        box = _ink_crop(gray)
        if box:
            l, t, r, b = box
            if (r - l) > 8 and (b - t) > 8:
                pad = 4
                img = img.crop((max(0, l - pad), max(0, t - pad),
                                min(img.width, r + pad), min(img.height, b + pad)))
                gray = _gray(img)
                meta["steps"]["crop"] = list(box)
        try:
            angle = deskew_angle(gray)
            if abs(angle) >= DESKREW_STEP:
                img = img.rotate(angle, resample=Image.BICUBIC,
                                 expand=True, fillcolor=255)
            meta["steps"]["deskew"] = angle
        except Exception as e:  # noqa: BLE001
            meta["steps"]["deskew"] = f"error:{e}"
        img = enhance_for_ocr(img)
        meta["steps"]["enhance"] = "ok"
        h = img.height
        if h < MIN_LINE_HEIGHT * 3:
            img = img.resize((img.width * UPSCALE_FACTOR, h * UPSCALE_FACTOR),
                             Image.LANCZOS)
            meta["steps"]["upscale"] = UPSCALE_FACTOR
        else:
            meta["steps"]["upscale"] = 1
        return img, meta
    except Exception as e:  # noqa: BLE001
        meta["ok"] = False
        meta["error"] = str(e)
        try:
            return Image.open(p).convert("L"), meta
        except Exception:
            return Image.new("L", (10, 10), 255), meta
