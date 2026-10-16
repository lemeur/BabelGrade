"""Hybrid OCR for handwritten written copies.

Pipeline (2026-10-08, "Annoter" feature):
1. **Tesseract** (local, offline, via pytesseract) produces the LINE BOXES of
   the handwritten text on each page photo — deterministic pixel geometry
   (y0/y1/x0/x1) used by the UI to interleave the AI's reading between the
   handwritten lines.
2. The **LLM (vision)** then POLISHES the rough tesseract text: it sees the
   page image + the tesseract lines and returns corrected line texts, keeping
   the exact line count and order. Crucially it must NOT "fix" the student's
   own spelling/grammar mistakes — only OCR misreads (l vs 1, o vs 0, …).

If tesseract is missing, `ocr_page` degrades to an empty-lines result (the UI
still shows the photo, without the interleaved OCR lines). If the LLM polish
fails, the tesseract text is kept as-is.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import llm_client

MAX_PAGES = 20  # same cap as the photo uploader

_TESS_LANGS = ("fra", "eng")


def _detect_language_hint(language: str | None) -> tuple[str, str]:
    """Map the submission's language code to (tesseract lang, hint label)."""
    lang = (language or "").lower()
    if lang.startswith("fr"):
        return "fra", "français"
    return "eng", "English"


def available() -> dict:
    """Status of the local OCR engine (for /api/health-style probes)."""
    try:
        out = subprocess.run(["tesseract", "--version"], capture_output=True,
                             text=True, timeout=10)
        first = (out.stdout or out.stderr or "").splitlines()[:1]
        return {"tesseract": out.returncode == 0,
                "version": (first[0] if first else "").strip(),
                "langs": _TESS_LANGS}
    except Exception as e:
        return {"tesseract": False, "error": str(e)}


def _lang_available(lang: str) -> bool:
    try:
        out = subprocess.run(["tesseract", "--list-langs"],
                             capture_output=True, text=True, timeout=10)
        return lang in (out.stdout or "")
    except Exception:
        return False


def _red_strike_spans(img: Image.Image) -> list[tuple[int, int, int, int]]:
    """Detect red strike-through marks (crossed-out words) in a page photo.

    A strike is a near-horizontal run of distinctly red pixels (R well
    above G/B) spanning >= 25 px — thin enough in height to be a LINE, not
    red-inked text. Returns a list of (x0, y0, x1, y1) boxes, padded.

    Conservative on purpose: false positives only cause a wrongly crossed
    word to be dropped, but the polish LLM still sees the original photo
    and will re-add it if it's actually there; false negatives just fall
    back to the LLM-only cross-out handling. Never raises — returns [] on
    any failure.
    """
    import numpy as np
    try:
        a = np.asarray(img.convert("RGB")).astype(np.int16)
        r, g, b = a[..., 0], a[..., 1], a[..., 2]
        red = (r - np.maximum(g, b) > 40) & (r > 70)
        spans: list[tuple[int, int, int, int]] = []
        for y in range(red.shape[0]):
            row = red[y]
            x = 0
            while x < row.shape[0]:
                if not row[x]:
                    x += 1
                    continue
                x0 = x
                while x < row.shape[0] and row[x]:
                    x += 1
                if x - x0 >= 25:
                    # merge with any span of the same stroke run (the
                    # stroke is 2-4 px thick: consecutive rows overlap)
                    merged = False
                    for k in range(len(spans) - 1, -1, -1):
                        px0, py0, px1, py1 = spans[k]
                        if y - py1 <= 3 and x0 - 6 <= px1 and px0 <= x + 6:
                            spans[k] = (min(px0, x0), py0,
                                        max(px1, x), max(py1, y + 1))
                            merged = True
                            break
                    if not merged:
                        spans.append((x0, y, x, y + 1))
        # pad + drop degenerate boxes
        out = [(max(0, x0 - 6), max(0, y0 - 6), x1 + 6, y1 + 6)
               for x0, y0, x1, y1 in spans
               if (x1 - x0) >= 25]
        return out
    except Exception:  # noqa: BLE001 — detection must never break OCR
        return []


def _is_crossed(word_box: tuple, spans: list[tuple]) -> bool:
    """True when a word's box sits ON a strike-through span: the word's
    vertical center is within the span's y band and >= 60% of the word's
    width overlaps the span's x range (the line goes through the word)."""
    wx0, wy0, wx1, wy1 = word_box
    wy_mid = (wy0 + wy1) / 2
    ww = wx1 - wx0
    if ww <= 0:
        return False
    for sx0, sy0, sx1, sy1 in spans:
        if sy0 <= wy_mid <= sy1:
            overlap = min(wx1, sx1) - max(wx0, sx0)
            if overlap >= 0.6 * ww:
                return True
    return False


def ocr_page(image_path: str, language: str | None = None) -> dict:
    """Run tesseract on ONE page photo.

    Returns {name, w, h, lines: [{i, y0, y1, x0, x1, text}],
             tesseract: bool}. Lines are merged from tesseract's word boxes
    into reading-order lines (grouped by y-overlap, sorted by x).

    Handwritten-copy note (2026-10-09, Slice 1 experiments): the image is
    fed to tesseract as a plain grayscale conversion — NO enhancement
    pipeline. Both a grid local-contrast stretch and a median denoise were
    measured on a noisy handwritten fixture and BOTH were measured to HURT
    on photos that are already decent: contrast created phantom inks at
    cell borders / noise that tesseract merged into lines ("My Favourite
    Movie" fused with line 1, 8 lines → 10, hallucinated junk lines) and the
    median eroded thin strokes (word recovery 19/19 → 17/19). The real
    robustness lever for poor photos is image quality itself (Slice 2:
    photo-quality warning + re-shoot hint), not an in-pipeline filter that
    can regress good photos. `imaging.py` keeps the helpers for future use.
    """
    import pytesseract
    from PIL import Image
    p = Path(image_path)
    img = Image.open(p)
    w, h = img.size
    tess_lang, _ = _detect_language_hint(language)
    if not _lang_available(tess_lang):
        tess_lang = "eng"
    tess_img = img.convert("L")
    data = pytesseract.image_to_data(
        tess_img, lang=tess_lang, config="--psm 6",
        output_type=pytesseract.Output.DICT)
    crossed_x = _red_strike_spans(img)
    lines: list[dict] = []
    n = len(data.get("text", []))
    words: list[tuple] = []  # (y0, y1, x0, x1, text)
    for i in range(n):
        txt = (data["text"][i] or "").strip()
        conf = data.get("conf", [None] * n)[i]
        if not txt:
            continue
        try:
            if float(conf) < 0:
                continue
        except (TypeError, ValueError):
            pass
        x0, y0 = int(data["left"][i]), int(data["top"][i])
        x1, y1 = x0 + int(data["width"][i]), y0 + int(data["height"][i])
        # crossed-out words (red strike-through) are DELETED by the student:
        # drop them from the rough OCR so neither the polish LLM nor the
        # stored line text carries a word the student rejected.
        if crossed_x and _is_crossed((x0, y0, x1, y1), crossed_x):
            continue
        words.append((y0, y1, x0, x1, txt))
    # group words into lines: a word belongs to the open line with the most
    # vertical overlap; otherwise it opens a new line.
    lines_raw: list[list] = []
    for (y0, y1, x0, x1, txt) in sorted(words, key=lambda t: (t[0], t[2])):
        placed = False
        for line in lines_raw:
            ly0, ly1 = line[0], line[1]
            overlap = min(ly1, y1) - max(ly0, y0)
            if overlap > 0.4 * min(ly1 - ly0, y1 - y0) and overlap > 0:
                line[2].append((x0, x1, txt))
                line[0] = min(ly0, y0)
                line[1] = max(ly1, y1)
                placed = True
                break
        if not placed:
            lines_raw.append([y0, y1, [(x0, x1, txt)]])
    for idx, (y0, y1, ws) in enumerate(sorted(lines_raw, key=lambda l: l[0])):
        ws.sort(key=lambda t: t[0])
        x1 = min(w, int(max(x1 for _, x1, _ in ws)))
        lines.append({
            "i": idx,
            "y0": max(0, int(y0)),
            "y1": min(h, int(y1)),
            "x0": max(0, int(min(x0 for x0, _, _ in ws))),
            "x1": x1,
            "text": " ".join(t for _, _, t in ws),
            # True when the line's ink reaches the right edge of the photo —
            # the line is CROPPED by the image, the last word may be cut
            # mid-character. Flagged so the polish LLM does NOT invent the
            # missing letters and the UI can warn the teacher to re-shoot.
            "truncated_right": x1 >= w - 3,
        })
    return {"w": w, "h": h, "lines": lines, "tesseract": True,
            "tess_lang": tess_lang}


def polish_page(image_data_url: str, lines: list[dict],
                language_hint: str = "") -> list[dict]:
    """LLM vision polish of the tesseract lines.

    Returns a NEW list of lines (same count, same order, same boxes) whose
    `text` has been corrected by the model for OCR misreads only. On any
    failure, the input lines are returned unchanged.
    """
    if not lines:
        return lines
    rough = "\n".join(
        f"L{i + 1}: {ln['text']}" + (" [CUT OFF AT RIGHT EDGE]"
        if ln.get("truncated_right") else "")
        for i, ln in enumerate(lines))
    prompt = (
        "Below is a rough OCR (Tesseract) reading of a student's handwritten "
        "copy, one line per L-number, in reading order. The photo of the page "
        "is attached. Correct the OCR misreads ONLY (letters the engine "
        "confused, split/joined words, stray characters, punctuation). "
        "IMPORTANT: this is a STUDENT'S work — you must NOT correct, improve, "
        "or normalize the student's own spelling, grammar, vocabulary or word "
        "choice: preserve every error the student actually wrote, verbatim. "
        "CROSSED-OUT TEXT: students cross out words they want to delete "
        "(usually with a straight line through the word). NEVER include a "
        "crossed-out word in the output — it does not exist in the student's "
        "final text. If the student wrote a replacement word above, below or "
        "next to the crossed-out word, keep that replacement in place of the "
        "crossed-out one. "
        "Lines marked [CUT OFF AT RIGHT EDGE] reach the physical edge of the "
        "photo: their last word may be cut mid-letter. NEVER invent or "
        "complete the missing letters of such a word — reproduce EXACTLY what "
        "is visible, cut off the same way, and append '…' at the end of that "
        "line. "
        f"Language: {language_hint or 'unknown'}. Keep the EXACT same number "
        "of lines and the same order. If a line is illegible in the photo, "
        "keep the rough text and prefix it with '? '.\n\n"
        f"ROUGH OCR:\n{rough}\n\n"
        "Respond with ONLY a JSON object: {\"lines\": [\"line 1 text\", ...]}"
    )
    try:
        res = llm_client.chat(
            [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ]}],
            temperature=0.0, max_tokens=6000, thinking_budget=3000)
        parsed = llm_client.extract_json(res["content"])
        texts = parsed.get("lines") if isinstance(parsed, dict) else None
        if not isinstance(texts, list) or len(texts) != len(lines):
            return lines
        for ln, txt in zip(lines, texts):
            if isinstance(txt, str) and txt.strip():
                ln["text"] = txt.strip()
        return lines
    except Exception:
        return lines


def ocr_submission(image_names: list[str], upload_dir: Path,
                   language: str | None = None,
                   progress=None, check_cancel=None) -> dict:
    """OCR all pages of a written submission (tesseract + LLM polish).

    progress(phase: str) and check_cancel() -> bool are optional callables.
    Returns the ocr_json blob persisted on the submission.
    """
    import base64
    _, hint = _detect_language_hint(language)
    pages = []
    for pi, name in enumerate(image_names[:MAX_PAGES]):
        if check_cancel and check_cancel():
            raise InterruptedError("cancelled")
        p = upload_dir / name
        if not p.exists():
            raise FileNotFoundError(f"page photo not found: {name}")
        if progress:
            progress(f"ocr-page-{pi + 1}")
        pg = ocr_page(str(p), language=language)
        if progress:
            progress(f"polish-page-{pi + 1}")
        data_url = "data:image/" + (p.suffix.lstrip(".").replace("jpeg", "jpeg")) \
            + f";base64,{base64.b64encode(p.read_bytes()).decode()}"
        pg["lines"] = polish_page(data_url, pg["lines"], language_hint=hint)
        pg["name"] = name
        pages.append(pg)
        if check_cancel and check_cancel():
            raise InterruptedError("cancelled")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "tesseract+llm",
        "language": language or "",
        "pages": pages,
    }
