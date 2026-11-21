"""Deterministic 2-step orientation estimation for handwritten page photos.

Pipeline (no LLM, no scipy, no cv2 — numpy + Pillow only):

  1. Preprocessing:
       - EXIF orientation tag is IGNORED (per spec, unreliable on flat sheets).
       - Resize to width <= target_w (default 700 px), grayscale.
       - Morphological black-hat (dilate - original) to isolate ink from
         shadow / illumination.
       - Filter full-width ruled lines (rows where >70% of the columns have
         ink on that exact row are not letters, they are grid lines).

  2. Step 1 — modulo 180°:
       - Coarse horizontal-projection scan over [-90°, +90°] step 2°.
       - Refine ±2° step 0.25°, then ±0.25° step 0.1°.
       - Maximise the variance of the 1-D projection profile of the ink
         points.  The optimum c2 ≈ -α (mod 180) where α is the visual CCW
         rotation of the text, so the first correction is +c2 deg.

  3. Step 2 — 0° vs 180° (up/down):
       - After applying the mod-180 correction, split the ink mask into
         per-line bands (peaks of the detrended row-ink profile).
       - Within each band, the row with maximum column-coverage is the
         letter baseline.  Its normalised position (0=top, 1=bottom of the
         band) is measured.  In an UPRIGHT page the baseline sits near the
         BOTTOM of each band (ascenders / capitals reach up); in a FLIPPED
         page it sits near the TOP.  The mean position is the signal.

  4. Output: corrective rotation in TRIGONOMETRIC (CCW, y-up) degrees,
     normalised to [-180, +180], plus a confidence score in [0, 1].

The helper is never allowed to raise: any decode/encode failure returns
angle 0 / confidence 0 so the caller can fall back to the original file.
"""
from __future__ import annotations

import io
import time

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from PIL import Image

# ---------------------------------------------------------------------------
#  Preprocessing
# ---------------------------------------------------------------------------

def _dilate_sep(a: np.ndarray, k: int, axis: int) -> np.ndarray:
    """Separable dilation (max-filter) along one axis only."""
    return sliding_window_view(a, k, axis=axis).max(axis=-1)


def ink_mask(gray: np.ndarray, k: int = 9) -> np.ndarray:
    """Isolate ink from background via morphological black-hat.

    Returns an int64 mask of the same shape as ``gray`` with the border
    ``k//2`` rows/cols set to 0 (where the dilation is not defined).
    Full-width ruled lines (>70% of columns inked on a single row) are
    zeroed out so they cannot act as fake baselines.
    """
    g = gray.astype(np.float32)
    d0 = _dilate_sep(_dilate_sep(g, k, 0), k, 1)
    p = k // 2
    bh = d0 - g[p:-p, p:-p]
    th = max(12.0, 0.12 * bh.max()) if bh.size else 0.0
    m = (bh > th).astype(np.uint8).astype(np.int64)
    H, W = m.shape
    if H > 0 and W > 0:
        rowcov = m.sum(axis=1)
        m[rowcov > 0.7 * W, :] = 0
    return m


# ---------------------------------------------------------------------------
#  Step 1 — modulo 180 (coarse + refine + micro)
# ---------------------------------------------------------------------------

def _profile_var(ys: np.ndarray, xs: np.ndarray, phi_rad: float,
                 off: int = 600) -> float:
    c, s = np.cos(phi_rad), np.sin(phi_rad)
    yp = np.round(ys * c - xs * s).astype(np.int32) + off
    prof = np.bincount(yp, minlength=2 * off + 1).astype(np.float64)
    return float(prof.var())


def mod180_estimate(ys: np.ndarray, xs: np.ndarray) -> float:
    """Return the optimal projection angle in [-90, +90] (mod 180)."""
    best, bv = 0.0, -1.0
    for i in range(91):
        phi = -90.0 + 2.0 * i
        v = _profile_var(ys, xs, np.deg2rad(phi))
        if v > bv:
            bv, best = v, float(phi)
    for phi in np.arange(best - 2.0, best + 2.0 + 1e-9, 0.25):
        v = _profile_var(ys, xs, np.deg2rad(float(phi)))
        if v > bv:
            bv, best = v, float(phi)
    for phi in np.arange(best - 0.25, best + 0.25 + 1e-9, 0.1):
        v = _profile_var(ys, xs, np.deg2rad(float(phi)))
        if v > bv:
            bv, best = v, float(phi)
    return best


# ---------------------------------------------------------------------------
#  Step 2 — 0° vs 180° (per-band baseline position)
# ---------------------------------------------------------------------------

def _per_band_baseline(ink: np.ndarray) -> tuple[float, int]:
    """Mean normalised baseline position across line bands.

    0.0 = baseline at the TOP of the band (page flipped),
    1.0 = baseline at the BOTTOM of the band (page upright).
    Returns (mean_position, n_bands).
    """
    H, W = ink.shape
    prof = ink.sum(axis=1).astype(np.float64)
    if H < 10 or W < 10 or prof.max() == 0:
        return 0.5, 0
    k = max(3, len(prof) // 50 | 1)
    k = k if k % 2 else k + 1
    sm = np.convolve(prof, np.ones(k) / k, mode="same")
    thr = 0.3 * sm.max()
    peaks: list[int] = []
    for i in range(1, len(sm) - 1):
        if sm[i] > thr and sm[i] >= sm[i - 1] and sm[i] >= sm[i + 1]:
            if not peaks or i - peaks[-1] > 6:
                peaks.append(i)
    if not peaks:
        return 0.5, 0
    band_half = max(8, H // 35)
    positions: list[float] = []
    for pk in peaks:
        lo, hi = max(0, pk - band_half), min(H, pk + band_half)
        band = ink[lo:hi, :]
        bh = hi - lo
        if bh < 8 or band.sum() < 40:
            continue
        rowcov = band.sum(axis=1)
        base_in_band = int(np.argmax(rowcov))
        positions.append(base_in_band / (bh - 1))
    if not positions:
        return 0.5, 0
    return float(np.mean(positions)), len(positions)


# ---------------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------------

def _estimate_from_image(im: Image.Image, target_w: int) -> dict:
    """Core estimator on a PIL image.  See estimate_orientation() for the
    returned dict shape.  EXIF is NOT consulted here — the caller passes
    the pixels it actually wants to analyse."""
    t0 = time.perf_counter()
    neutral = {"angle_ccw": 0.0, "confidence": 0.0, "ms": 0.0,
               "baseline_pos": 0.5, "ink_pixels": 0}
    try:
        im = im.convert("RGB")
    except Exception:
        neutral["ms"] = (time.perf_counter() - t0) * 1000.0
        return neutral

    w, h = im.size
    if w > target_w:
        nh = max(1, int(target_w * h / w))
        im = im.resize((target_w, nh), Image.BILINEAR)
    gray = np.asarray(im.convert("L"), dtype=np.float32)
    ink = ink_mask(gray)
    ink_n = int(ink.sum())
    if ink_n < 400:
        neutral["ms"] = (time.perf_counter() - t0) * 1000.0
        neutral["ink_pixels"] = ink_n
        return neutral

    ys, xs = np.nonzero(ink)
    xs = xs.astype(np.float32) - (ink.shape[1] - 1) / 2.0
    ys = ys.astype(np.float32) - (ink.shape[0] - 1) / 2.0
    N = 6000
    if len(ys) > N:
        idx = np.random.default_rng(0).choice(len(ys), N, replace=False)
        xs, ys = xs[idx], ys[idx]

    c2 = mod180_estimate(ys, xs)

    im2 = im.rotate(c2, resample=Image.BICUBIC, expand=True,
                    fillcolor=(255, 255, 255))
    ink2 = ink_mask(np.asarray(im2.convert("L"), dtype=np.float32))
    baseline_pos, n_bands = _per_band_baseline(ink2)

    # Upright: baseline near bottom of band (pos > 0.5).  Flipped: pos < 0.5.
    angle = c2 + (180.0 if baseline_pos < 0.5 else 0.0)
    angle = ((angle + 180.0) % 360.0) - 180.0
    ms = (time.perf_counter() - t0) * 1000.0

    # Confidence: how clearly the baseline signal separates from 0.5,
    # scaled by how much ink we have.
    margin = abs(baseline_pos - 0.5)  # 0.5 = no opinion, 0.0..1.0 = strong
    conf = min(1.0, ink_n / 3000.0) * min(1.0, margin * 4.0 + 0.1)
    conf = 0.0 if n_bands < 3 else conf  # need enough bands to be sure

    # The flip 0°/180° is most reliable when the stored lines are nearly
    # horizontal (|c2| ≈ 0°) or nearly vertical (|c2| ≈ 90°).  At the
    # diagonals (|c2| ≈ 45°/135°) the intermediate rotation smears the ink
    # and the hampes/majuscules signal degrades, so we cap the confidence
    # with |sin(2·c2)| (0 on the axes, 1 on the diagonals).  This is a
    # safety net: it is ~0 for the common phone orientations (0/90/180/270 +
    # small deskew) and only bites on rare diagonal orientations, where the
    # caller's confidence threshold then skips the rotation rather than risk
    # an 180° flip on a noisy signal.
    diag = abs(np.sin(2.0 * np.deg2rad(c2)))
    conf *= (1.0 - 0.6 * diag)

    return {"angle_ccw": float(angle), "confidence": float(conf),
            "ms": float(ms), "baseline_pos": float(baseline_pos),
            "ink_pixels": ink_n}


def estimate_orientation(data: bytes, target_w: int = 700) -> dict:
    """Estimate the corrective rotation (visual CCW, trig sense) of a page.

    Parameters
    ----------
    data:
        Raw image bytes (JPEG / PNG / WebP / …).
    target_w:
        Maximum width for the analysis miniature (default 700 px).

    Returns
    -------
    dict with keys:
        angle_ccw:  corrective rotation in degrees, [-180, +180].
                    0.0 means "already upright, keep as-is".
        confidence: float in [0, 1].  0 means "no opinion / could not
                    estimate" (caller should keep the original orientation).
        ms:         wall-clock time in milliseconds.
        baseline_pos: the raw per-band baseline signal (0.5 = neutral).
        ink_pixels:  number of ink pixels in the miniature (diagnostic).
    """
    t0 = time.perf_counter()
    neutral = {"angle_ccw": 0.0, "confidence": 0.0, "ms": 0.0,
               "baseline_pos": 0.5, "ink_pixels": 0}
    try:
        im = Image.open(io.BytesIO(data))
    except Exception:
        neutral["ms"] = (time.perf_counter() - t0) * 1000.0
        return neutral
    res = _estimate_from_image(im, target_w)
    res["ms"] = (time.perf_counter() - t0) * 1000.0
    return res


def rotate_ccw(im: Image.Image, deg: float) -> Image.Image:
    """Rotate ``im`` by ``deg`` degrees in the visual CCW (trig, y-up) sense.

    Uses PIL's ``rotate`` which is visually CCW in the standard image
    coordinate system.  ``expand=True`` keeps the whole image; the empty
    corners are filled with white.
    """
    return im.rotate(deg, resample=Image.BICUBIC, expand=True,
                     fillcolor=(255, 255, 255))
