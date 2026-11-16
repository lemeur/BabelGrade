"""LLM-direct OCR for handwritten student copies (2026-10-17 rewrite).

Old pipeline (pre-2026-10-17): Tesseract produced rough line boxes + text,
and the LLM "polished" it. On real handwritten photos the polish silently
failed (model over-thought the "correct this garbage, keep line count"
prompt → empty content → the Tesseract junk was stored as if it were the
final text). See `references/ocr-findings-real-copies.md` in the
`babelgrade` skill for the benchmark.

New pipeline (this file): the LLM vision engine reads the page photo
DIRECTLY and returns:
  - the transcription, line by line, in reading order, preserving the
    student's own spelling / grammar / word choices verbatim
  - a per-line bounding box in NORMALIZED 0..1000 coordinates (used by the
    Annoter view to highlight the matching band of the photo when the
    teacher selects a line of the transcript)
  - markers for ratures, tape, French words and illegible words:
      [X:word]  crossed-out by the student (same ink colour as the text;
                red ink is usually the teacher's grading, not a rature)
      [TAPE]    word covered by correction tape, illegible
      [FR]      word in French (the student is a French ESL learner)
      [?]      truly illegible word

If the model returns an empty `content` but a non-empty
`reasoning_content` (it over-thought and hit the token cap), the call is
retried ONCE with a smaller thinking budget; if it still comes back empty
we RAISE, so the job fails loudly instead of silently storing nothing.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from . import llm_client

MAX_PAGES = 20  # same cap as the photo uploader

# thinking_budget: cap on the model's reasoning tokens. 1500 was measured
# enough for a faithful page transcription on the 5-page real-copy test
# (2026-10-17), and low enough to avoid the "over-think → empty content"
# failure mode that the old polish prompt triggered with 3000.
_THINKING_BUDGET = 1500
_MAX_TOKENS = 10000

TRANSCRIBE_PROMPT = (
    "You are an OCR engine for a STUDENT'S handwritten school copy "
    "(blue grid paper, blue ink, English with occasional French words — "
    "the student is a French learner of English). The photo of ONE page "
    "is attached. Transcribe it faithfully, line by line, in reading "
    "order, using the ACTUAL visual lines in the photo (do NOT rely on "
    "any external line count). For EACH line also give the bounding box "
    "of that whole line's ink in the photo, in NORMALIZED coordinates "
    "where (0,0) is the top-left corner of the photo and (1000,1000) is "
    "the bottom-right corner of the photo: \"box\": [x0, y0, x1, y1] "
    "with x0<x1, y0<y1, integers 0..1000. The box should cover the ink "
    "of that line with a small margin. "
    "RULES: "
    "(1) Preserve the student's own spelling, grammar and word choices "
    "EXACTLY as written — do NOT correct, improve or normalize in ANY "
    "way. "
    "(2) CROSSED-OUT words struck through by the student (a straight "
    "line through the word, usually in the SAME INK COLOR as the rest of "
    "the text): represent as [X:word]. If the student wrote a "
    "replacement word nearby, include the replacement as normal text and "
    "STILL mark the crossed-out word as [X:word]. Red ink marks are "
    "usually the TEACHER'S grading, not the student's deletions — do NOT "
    "treat red ink as a rature unless the student's own ink is clearly "
    "struck through. "
    "(3) Words covered by correction tape that are illegible: [TAPE]. "
    "(4) Words in French (the student sometimes mixes in French): keep "
    "them, add [FR] after them. "
    "(5) If a word is truly illegible, use [?]. "
    "Output ONLY a JSON object, no markdown, no commentary: "
    "{\"lines\": [{\"text\": \"line text\", \"box\": [x0,y0,x1,y1]}, "
    "...], \"notes\": \"one-line summary of ratures / tape / French "
    "words if any\"}"
)


def available() -> dict:
    """Status of the OCR engine (for /api/health-style probes). The OCR
    engine is the LLM vision endpoint; there is no local Tesseract step
    anymore (2026-10-17)."""
    return {"engine": "llm-direct", "model": llm_client.MODEL,
            "base_url": llm_client.BASE_URL}


def _transcribe_once(image_data_url: str) -> tuple[dict | None, str]:
    """One LLM call. Returns (parsed_json_or_None, raw_content)."""
    res = llm_client.chat(
        [{"role": "user", "content": [
            {"type": "text", "text": TRANSCRIBE_PROMPT},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]}],
        temperature=0.0, max_tokens=_MAX_TOKENS,
        thinking_budget=_THINKING_BUDGET)
    return llm_client.extract_json(res["content"]), res["content"]


def transcribe_page(image_path: str, language: str | None = None) -> dict:
    """Run the LLM-direct OCR on ONE page photo.

    Returns {w, h, lines: [{i, text, box:[x0,y0,x1,y1 in 0..1000]}],
             notes, engine}. Raises RuntimeError if the LLM returns an
    empty content after a retry (the silent-fallback bug of the old
    polish pipeline is no longer allowed: better a loud job failure than
    stored garbage).
    """
    p = Path(image_path)
    if not p.exists():
        raise FileNotFoundError(f"page photo not found: {p}")
    img = Image.open(p)
    w, h = img.size
    b64 = base64.b64encode(p.read_bytes()).decode()
    mime = p.suffix.lstrip(".").lower() or "jpeg"
    mime = "jpeg" if mime == "jpg" else mime
    data_url = f"data:image/{mime};base64,{b64}"

    parsed, raw = _transcribe_once(data_url)
    lines = (parsed.get("lines") if isinstance(parsed, dict) else None)
    if not isinstance(lines, list) or not lines:
        # empty content / unparseable / over-thought: retry ONCE with a
        # tighter thinking budget so the model has to commit to an answer
        res2 = llm_client.chat(
            [{"role": "user", "content": [
                {"type": "text", "text": TRANSCRIBE_PROMPT +
                 " Be decisive: do not over-analyze, just transcribe."},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]}],
            temperature=0.0, max_tokens=_MAX_TOKENS,
            thinking_budget=500)
        parsed = llm_client.extract_json(res2["content"])
        lines = (parsed.get("lines") if isinstance(parsed, dict) else None)
        raw = res2["content"]
        if not isinstance(lines, list) or not lines:
            raise RuntimeError(
                "LLM OCR returned no lines "
                f"(raw_len={len(raw or '')}); page={p.name}")

    out_lines: list[dict] = []
    for i, ln in enumerate(lines):
        if isinstance(ln, dict):
            text = (ln.get("text") or "").strip()
            box = _sanitize_box(ln.get("box"))
        else:
            text, box = str(ln).strip(), None
        out_lines.append({"i": i, "text": text, "box": box})
    # The model's box y-coordinates are frequently interpolated, not
    # measured (verified on real copies 2026-10-17: every line's box
    # sat in the blank margin above its ink). Re-snap them onto the
    # page's actual ink bands — only when the band count matches the
    # line count 1:1 (see resnap_boxes).
    resnap_boxes(out_lines, np.array(img.convert("L")))
    notes = ""
    if isinstance(parsed, dict):
        notes = str(parsed.get("notes") or "")[:500]
    return {"w": w, "h": h, "lines": out_lines, "notes": notes,
            "engine": "llm-direct"}


def _sanitize_box(box) -> list[int] | None:
    """Clamp/validate the model's 0..1000 box. Returns [x0,y0,x1,y1] or
    None when the model didn't give a usable box (the UI then falls back
    to a full-width band estimated from the line index)."""
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        x0, y0, x1, y1 = (int(round(float(v))) for v in box)
    except (TypeError, ValueError):
        return None
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    x0, x1 = max(0, min(1000, x0)), max(0, min(1000, x1))
    y0, y1 = max(0, min(1000, y0)), max(0, min(1000, y1))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return [x0, y0, x1, y1]


def _normalize_illumination(gray: np.ndarray, radius: int = 64) -> np.ndarray:
    """Subtract the large-scale illumination field of a page.

    Phone photos of student copies frequently have a DARK paper (grid
    notebook photographed through a glass / dim light: background median
    ~116-150 instead of ~250), sometimes with a vignette. A fixed
    `gray < 120` ink threshold then treats the paper itself as ink and
    the band detector collapses to one giant band. The local background
    is estimated with a wide Gaussian blur (larger than any text line,
    smaller than the page) and subtracted, re-centered at 128 so that
    "darker than the local paper" ends up < 128 in the equalized image.
    Verified on 6 real copies (2026-10-19): grid-paper darkness splits
    into per-line ink bands with this normalization.
    """
    im = Image.fromarray(gray)
    bg = np.array(im.filter(ImageFilter.GaussianBlur(radius)), dtype=np.int16)
    out = np.clip(gray.astype(np.int16) - bg + 128, 0, 255)
    return out.astype(np.uint8)


def _ink_bands(gray: np.ndarray) -> list[tuple[int, int]]:
    """Detect horizontal ink bands (text lines) in a grayscale page.

    Returns pixel [y0, y1] pairs, top to bottom. Bands closer together
    than a small gap are merged (descenders / dotted underlines split a
    visual line); bands thinner than a minimum height (specks, stray
    marks) are dropped.

    Dark pages (p90 < 200: dim grid notebook, low-light photo, vignette)
    are illumination-normalized first and probed with a stricter ink
    threshold (pix < 100, dark_frac > 0.05) so the grid lines and the
    paper itself stop masquerading as ink (2026-10-19: every real copy
    shot so far landed on the dark path and collapsed to 1 band under
    the old fixed threshold). White-paper pages keep the historical
    thresholds.
    """
    h = int(gray.shape[0])
    if np.percentile(gray, 90) < 200:
        # Dark paper: equalize the illumination first, then probe the
        # equalized image with a strict ink threshold (the paper and its
        # grid would otherwise be counted as ink).
        probe = _normalize_illumination(gray)
        dark_frac = (probe < 100).mean(axis=1)
        thresh = 0.05
    else:
        dark_frac = (gray < 120).mean(axis=1)
        thresh = 0.004
    # After equalization the inter-line gutters of a grid notebook can
    # still carry stray dark grid pixels: merge only a small gap so two
    # separate lines are not fused by one noisy gutter row.
    gap = int(h * (0.008 if thresh > 0.01 else 0.015))
    min_h = max(4, int(h * 0.006))
    raw: list[list[int]] = []
    start: int | None = None
    for y, d in enumerate(dark_frac):
        if d > thresh and start is None:
            start = y
        elif d <= thresh and start is not None:
            if y - start >= min_h:
                raw.append([start, y - 1])
            start = None
    if start is not None and h - start >= min_h:
        raw.append([start, h - 1])
    merged: list[list[int]] = []
    for b in raw:
        if merged and b[0] - merged[-1][1] - 1 <= gap:
            merged[-1][1] = b[1]
        else:
            merged.append(b)
    return [(b[0], b[1]) for b in merged]


def _band_unclean_frac(bands: list[tuple[int, int]], gray: np.ndarray) -> float:
    """Fraction of detected bands that look UNRELIABLE.

    A band is "unclean" if it is a merged multi-line band (taller than
    1.5× the median band height) or a sparse grid-line / speck band
    (short, and/or carrying far less ink than a typical line). The ink
    measure is taken on the same illumination-equalized image that
    `_ink_bands` probes when the paper is dark, so it is consistent with
    the threshold that produced the bands.

    Used as a detector-reliability gate in `resnap_boxes`: when the page
    is clean, the bands are the ground truth and re-snapping is safe;
    when the detector is noisy (as it is on dim grid notebook paper),
    re-snapping would move already-good LLM boxes onto merged / phantom
    bands, so the resnap must abstain (2026-10-19, real copy: 25 % of
    bands unclean -> the off-by-one fix must NOT be applied there).
    """
    if len(bands) < 2:
        return 1.0
    heights = [b - a for a, b in bands]
    med_h = float(np.median(heights))
    if np.percentile(gray, 90) < 200:
        probe = _normalize_illumination(gray)
        ink = probe < 100
    else:
        ink = gray < 120
    ink_counts = [float(ink[a:b + 1].sum()) for a, b in bands]
    med_ink = float(np.median(ink_counts))
    if med_ink <= 0:
        return 1.0
    unclean = 0
    for (a, b), ic in zip(bands, ink_counts):
        h = b - a
        merged = h > 1.5 * med_h
        sparse = h < 0.35 * med_h or ic < 0.30 * med_ink
        if merged or sparse:
            unclean += 1
    return unclean / len(bands)


def resnap_boxes(lines: list[dict], gray: np.ndarray) -> int:
    """Re-snap the LLM's per-line boxes onto the page's ACTUAL ink bands.

    The vision model transcribes faithfully but its box coordinates are
    frequently INTERPOLATED instead of measured, and — verified on 3 real
    photos 2026-10-17 — systematically land ~ONE LINE ABOVE the ink. So
    the Annoter highlights the wrong band when a transcript line is
    selected (2026-10-19 off-by-one bug, sub 597-style photo where the LLM
    also skipped the printed "Question 2:" header line).

    Matching is an ORDER-PRESERVING alignment (Needleman–Wunsch) between
    transcript lines and detected ink bands, run TWICE — with the raw box
    centres and with the centres shifted down by one median line-spacing
    (the "de-bias") — and the candidate with the LOWER total match cost
    wins. This makes the choice data-driven instead of assuming the LLM's
    bias is present:

      * skipped top line + boxes 1 line high  -> shifted candidate costs
        ~0, raw costs ~n·spacing -> shifted wins, band 0 stays unclaimed;
      * counts equal / boxes already near their ink -> raw candidate wins
        (shifted is penalised by the ~1-spacing offset); a global de-bias
        would have shifted every box down one line here;
      * skipped bottom line, boxes on ink     -> raw wins, last band
        unclaimed.

    A band may be left UNCLAIMED (the LLM sometimes does not transcribe a
    visual line: printed headers, the teacher's red grading ink). The
    x-extents are kept as-is (they were plausible); only the y-extent is
    re-anchored to the matched band.

    Guardrails: never resnap when the detector is clearly broken (< 2
    bands — dark/low-contrast page collapses to one giant band — or more
    than 2× the line count of bands). Lines with no LLM box (centre
    unknown) and lines whose box is far from every band (beyond the cap)
    are left untouched.

    Detector-reliability gate (2026-10-19, verified on a real copy):
    before trusting the bands, `resnap_boxes` measures what fraction of
    them is unclean (`_band_unclean_frac`: merged multi-line bands or
    sparse grid-line / speck bands). If ≥ 20 % of the bands are
    unclean, the detector is NOT a reliable reference and the resnap
    abstains entirely. This is the exact regime of dim grid-notebook
    photos (real copy: 25 % unclean) where the LLM's own boxes were
    already well-centred (0.8 px mean ink offset) and re-snapping onto
    the noisy bands would have REGRESSED 24/24 boxes onto merged or
    phantom bands. On clean pages (white paper, 0 % unclean — all the
    synthetic off-by-one fixtures) the resnap still fires, which is
    the only regime where it is proven to help.

    Returns the number of boxes changed.
    """
    h = int(gray.shape[0])
    n = len(lines)
    if not n:
        return 0
    bands = _ink_bands(gray)
    if len(bands) < 2 or len(bands) > 2 * n:
        return 0
    # Detector-reliability gate: on noisy pages (merged lines, phantom
    # grid-line bands) the bands are NOT a trustworthy reference, and
    # re-snapping good LLM boxes onto them regresses the result.
    if _band_unclean_frac(bands, gray) >= 0.20:
        return 0
    bcenter = [float(b[0] + b[1]) / 2 for b in bands]
    gaps = [bcenter[i + 1] - bcenter[i] for i in range(len(bcenter) - 1)]
    med_gap = float(np.median(gaps)) if gaps else float(h / n)
    cap = 1.6 * med_gap  # a match beyond this is "far" -> leave box as-is
    m = len(bands)

    def box_center_px(ln):
        box = ln.get("box")
        if not (isinstance(box, list) and len(box) == 4):
            return None
        return ((box[1] + box[3]) / 2.0) * h / 1000.0

    # LINE_GAP > BAND_GAP keeps the alignment "match as much as possible";
    # the cap bounds a single bad match so a gap stays attractive when the
    # extra band/line really has no counterpart.
    lg, bg = 3.0 * med_gap, 2.0 * med_gap
    INF = float("inf")
    centers = [box_center_px(ln) for ln in lines]

    def run(shift):
        cs = [None if c is None else c + shift for c in centers]
        dp = [[0.0] * (m + 1) for _ in range(n + 1)]
        for i in range(1, n + 1):
            dp[i][0] = i * lg
        for j in range(1, m + 1):
            dp[0][j] = j * bg
        for i in range(1, n + 1):
            c = cs[i - 1]
            for j in range(1, m + 1):
                if c is None:
                    cost = min(dp[i - 1][j] + lg, dp[i][j - 1] + bg)
                else:
                    match = dp[i - 1][j - 1] + min(abs(c - bcenter[j - 1]), cap)
                    cost = min(match, dp[i - 1][j] + lg, dp[i][j - 1] + bg)
                dp[i][j] = cost
        # backtrack (line idx -> band idx, or None for an unpaired line).
        # Ties prefer a match, then a band gap — deterministic, and keeps
        # counts-equal runs collapsing to the line k -> band k zip.
        i, j, mapping = n, m, [None] * n
        while i > 0 and j > 0:
            c = cs[i - 1]
            match_c = INF if c is None else dp[i - 1][j - 1] + min(abs(c - bcenter[j - 1]), cap)
            if match_c <= dp[i][j] + 1e-9:
                mapping[i - 1] = j - 1
                i -= 1
                j -= 1
            elif dp[i][j - 1] + bg <= dp[i][j] + 1e-9:
                j -= 1  # band j-1 unclaimed (skipped line / grading ink)
            else:
                i -= 1  # line i-1 unpaired
        return dp[n][m], mapping

    raw_cost, raw_map = run(0.0)
    shifted_cost, shifted_map = run(med_gap)
    # `<=` tie-break toward the shifted mapping: when the boxes are one line
    # high AND one band is unclaimed (the LLM skipped a top line — the
    # 2026-10-19 "Question 2:" header case), both hypotheses fit perfectly
    # and tie in cost; the documented LLM bias (3 real copies, 2026-10-17)
    # is boxes-above-ink, so the unclaimed band is the top one -> shifted
    # wins the tie. When boxes are already on their ink, shifted is
    # strictly more expensive, so raw wins and the result is idempotent.
    # (In the m==n equal-count case both mappings are the line k -> band k
    # zip and the cost tie is irrelevant to the output.)
    cost, mapping = (shifted_cost, shifted_map) if shifted_cost <= raw_cost else (raw_cost, raw_map)

    changed = 0
    for li, ln in enumerate(lines):
        if centers[li] is None:
            continue  # no LLM box -> nothing to verify, leave as-is
        bj = mapping[li]
        if bj is None:
            continue  # line far from any band -> keep the LLM box
        by0, by1 = bands[bj]
        y0 = by0 * 1000 // h
        y1 = max(y0 + 2, by1 * 1000 // h)
        box = ln.get("box")
        if isinstance(box, list) and len(box) == 4:
            ln["box"] = [box[0], y0, box[2], y1]
        else:
            ln["box"] = [0, y0, 1000, y1]
        changed += 1
    return changed


def ocr_submission(image_names: list[str], upload_dir: Path,
                   language: str | None = None,
                   progress=None, check_cancel=None) -> dict:
    """OCR all pages of a written submission (LLM-direct, no Tesseract).

    progress(phase: str) and check_cancel() -> bool are optional callables.
    Returns the ocr_json blob persisted on the submission. Raises
    RuntimeError on any page that yields no lines (the job then fails
    loudly instead of storing a silently-broken result).
    """
    pages = []
    for pi, name in enumerate(image_names[:MAX_PAGES]):
        if check_cancel and check_cancel():
            raise InterruptedError("cancelled")
        if progress:
            progress(f"ocr-page-{pi + 1}")
        p = upload_dir / name
        if not p.exists():
            raise FileNotFoundError(f"page photo not found: {p}")
        pg = transcribe_page(str(p), language=language)
        pg["name"] = name
        pages.append(pg)
        if check_cancel and check_cancel():
            raise InterruptedError("cancelled")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "llm-direct",
        "language": language or "",
        "pages": pages,
    }
