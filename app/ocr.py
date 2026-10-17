"""LLM-direct OCR for handwritten student copies (2026-10-17 rewrite).

Old pipeline (pre-2026-10-17): Tesseract produced rough line boxes + text,
and the LLM "polished" it. On real handwritten photos the polish silently
failed (model over-thought the "correct this garbage, keep line count"
prompt → empty content → the Tesseract junk was stored as if it were the
final text). See `references/ocr-findings-real-copies.md` in the
`elt-assessor-app` skill for the benchmark.

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
from PIL import Image

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


def _ink_bands(gray: np.ndarray) -> list[tuple[int, int]]:
    """Detect horizontal ink bands (text lines) in a grayscale page.

    Returns pixel [y0, y1] pairs, top to bottom. Bands closer together
    than a small gap are merged (descenders / dotted underlines split a
    visual line); bands thinner than a minimum height (specks, stray
    marks) are dropped.
    """
    h = int(gray.shape[0])
    dark_frac = (gray < 120).mean(axis=1)
    thresh = 0.004
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
    gap = int(h * 0.015)
    for b in raw:
        if merged and b[0] - merged[-1][1] - 1 <= gap:
            merged[-1][1] = b[1]
        else:
            merged.append(b)
    return [(b[0], b[1]) for b in merged]


def resnap_boxes(lines: list[dict], gray: np.ndarray) -> int:
    """Re-snap the LLM's per-line boxes onto the page's ACTUAL ink bands.

    The vision model transcribes faithfully but its box coordinates are
    frequently INTERPOLATED instead of measured: on real handwritten
    photos (2026-10-17, verified on 3 live submissions) line N's box
    lands in the blank margin above line N-1's ink, so the Annoter
    highlights the wrong band when a transcript line is selected.

    When the detector finds exactly as many ink bands as there are
    lines, each line's box y-extent is replaced by its band's pixel
    range (converted back to 0..1000). The x-extents are kept as-is
    (they were plausible). Lines without a box get a full-width band.
    When the counts do not match (teacher's grading ink adds a band,
    blank lines, partial pages, …) the LLM's boxes are kept untouched —
    never resnap a misaligned 1:1. Returns the number of boxes changed.
    """
    h = int(gray.shape[0])
    bands = _ink_bands(gray)
    n = len(lines)
    if not bands or len(bands) != n:
        return 0
    changed = 0
    for ln, (by0, by1) in zip(lines, bands):
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
