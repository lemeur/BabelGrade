"""Annoter routes: OCR line boxes + per-line annotations (2026-10-08).

Extracted from main.py (2026-10-16 split).
"""
from fastapi import APIRouter, HTTPException

from . import db
import json

router = APIRouter()


@router.post("/api/submissions/{sub_id}/ocr")
def start_ocr(sub_id: int):
    """Enqueue the LLM-direct OCR job (the vision engine transcribes each
    page photo directly, with per-line bounding boxes) for a written
    submission's page photos. Returns the job handle; follow it at
    `follow_url` (SSE). The result is persisted on submissions.ocr_json and
    served by GET /api/submissions/{id}.ocr."""
    sub = db.get_submission(sub_id)
    if not sub:
        raise HTTPException(404, "submission not found")
    if sub.get("kind") != "written":
        raise HTTPException(422, "OCR is only available for written submissions")
    meta = sub.get("payload_meta") or {}
    if not meta.get("page_paths"):
        raise HTTPException(422, "this submission has no page photos")
    with db._LOCK:
        c = db._conn()
        n = c.execute(
            "SELECT COUNT(*) FROM jobs WHERE submission_id=? AND kind='ocr' "
            "AND status IN ('queued','running')", (sub_id,)).fetchone()[0]
    if n:
        raise HTTPException(409, "an OCR job for this submission is already in the queue")
    job_id = db.create_job("ocr", {"submission_id": sub_id},
                           submission_id=sub_id, analysis_id=None)
    job = db.job_get(job_id)
    return {"job_id": job_id, "job_status": job.get("status"),
            "job_kind": "ocr", "submission_id": sub_id,
            "enqueued": True, "follow_url": f"/api/jobs/{job_id}/events"}

@router.get("/api/submissions/{sub_id}.ocr")
def get_ocr(sub_id: int):
    sub = db.get_submission(sub_id)
    if not sub:
        raise HTTPException(404, "submission not found")
    ocr_data = sub.get("ocr")
    with db._LOCK:
        c = db._conn()
        job = c.execute(
            "SELECT * FROM jobs WHERE submission_id=? AND kind='ocr' "
            "ORDER BY id DESC LIMIT 1", (sub_id,)).fetchone()
    running = bool(job and job["status"] in ("queued", "running"))
    return {"submission_id": sub_id, "ocr": ocr_data, "running": running,
            "job_id": job["id"] if job else None}

# ------------------------------------------------------------- annotations
def _page_words(lines: list) -> tuple[list, list]:
    """Global word list of a page + each word's owning line index.

    A "word" is one element of `line.text.split(" ")` (markers like
    `[X:word]`/`[TAPE]`/`[FR]`/`[?]` stay their own token, so a rature is
    selectable as a word). Must stay BYTE-IDENTICAL to the UI tokenization
    (frontend `anPageWords()`), else word indices desync.
    """
    words: list[str] = []
    line_of_word: list[int] = []
    for li, ln in enumerate(lines):
        text = ln.get("text") or ""
        for tok in text.split(" "):
            words.append(tok)
            line_of_word.append(li)
    return words, line_of_word


def _validate_annotation_span(body: dict, sub: dict, span: dict):
    """Validate/clamp an annotation span against the submission's content.

    Returns (clean_span, page_idx, quote). Raises ValueError on bad input.

    Two written formats are accepted (2026-10-18 word-selection feature):
      - word-based:  {page, start_word, end_word}   (global page word idx)
      - legacy:      {page, start_line, start_char, end_line, end_char}
    Oral is unchanged: {start_s, end_s}.
    """
    kind = sub["kind"]
    if kind == "written":
        ocr_data = sub.get("ocr") or {}
        pages = ocr_data.get("pages") or []
        if not pages:
            raise ValueError("no OCR lines available for this copy yet")
        page = int(span.get("page", 0))
        if not (0 <= page < len(pages)):
            raise ValueError("page out of range")
        lines = pages[page].get("lines") or []

        # WORD-based span (2026-10-18). start_word/end_word are global
        # indices into the page's word list; the covered-line range is
        # derived so the existing UI `.an-hl` (which reads start_line/
        # end_line) keeps working unchanged.
        if "start_word" in span or "end_word" in span:
            sw = int(span.get("start_word", 0))
            ew = int(span.get("end_word", sw))
            if ew < sw:
                raise ValueError("annotation range is inverted or empty")
            words, line_of_word = _page_words(lines)
            if sw < 0 or ew >= len(words):
                raise ValueError("word index out of range")
            sl_line, el_line = line_of_word[sw], line_of_word[ew]
            quote = " ".join(words[sw:ew + 1]).strip()
            clean = {"page": page, "start_word": sw, "end_word": ew,
                     "start_line": sl_line, "end_line": el_line}
            return clean, page, quote

        def clamp(li: int, ch: int) -> int:
            if not (0 <= li < len(lines)):
                raise ValueError("line out of range")
            ln = lines[li]
            L = len(ln.get("text") or "")
            return max(0, min(int(ch), L))

        raw_sl = int(span.get("start_line", 0))
        raw_el = int(span.get("end_line", raw_sl))
        # reject inverted RAW ranges before clamping can mask them
        if raw_el < raw_sl or (raw_el == raw_sl
                and int(span.get("end_char", 0)) < int(span.get("start_char", 0))):
            raise ValueError("annotation range is inverted or empty")
        # NOTE: clamp(li, ch) validates the LINE `li` (raises if out of range)
        # but RETURNS the clamped CHARACTER offset, not the line. So the line
        # index must come from the raw values, and clamp is only used for the
        # char offsets (2026-10-10 bug: `sl_line = clamp(raw_sl, 0)` always
        # returned 0, pinning every annotation to line 0).
        sl_line = raw_sl
        el_line = raw_el
        sc = clamp(sl_line, int(span.get("start_char", 0)))
        ec = clamp(el_line, int(span.get("end_char", 0)))
        if (el_line, ec) < (sl_line, sc):
            raise ValueError("annotation range is inverted or empty")
        # quoted passage, possibly spanning several lines
        parts = []
        for li in range(sl_line, el_line + 1):
            ln_text = lines[li].get("text") or ""
            a = 0 if li > sl_line else sc
            b = len(ln_text) if li < el_line else ec
            seg = ln_text[a:b].strip()
            if seg:
                parts.append(seg)
        quote = " ".join(parts)
        clean = {"page": page, "start_line": sl_line, "start_char": sc,
                 "end_line": el_line, "end_char": ec}
        return clean, page, quote
    # oral
    tr = None
    analysis = db.latest_analysis_for_submission(sub["id"])
    if analysis and analysis.get("transcript_json"):
        try:
            tr = json.loads(analysis["transcript_json"])
        except Exception:
            tr = None
    dur = (tr or {}).get("duration_s") or sub.get("duration_s") or 0
    s = float(span.get("start_s", 0))
    e = float(span.get("end_s", 0))
    if dur:
        s, e = max(0.0, s), min(e, dur)
    if e - s < 0.2:
        raise ValueError("time range too short (min 0.2 s)")
    # quoted text = the transcript WORDS overlapping the range (word-level,
    # 2026-10-18); falls back to the coarser segment texts for legacy
    # analyses whose transcript_json predates the persisted words blob.
    quote = ""
    if tr:
        words = tr.get("words") or []
        if words:
            quote = " ".join(w.get("w", "").strip() for w in words
                             if w.get("end", 0) > s and w.get("start", 0) < e
                             and (w.get("w") or "").strip())
        if not quote:
            segs = []
            for seg in tr.get("segments") or []:
                if seg.get("end", 0) <= s or seg.get("start", 0) >= e:
                    continue
                segs.append(seg.get("text", "").strip())
            quote = " ".join(t for t in segs if t)
    return {"start_s": round(s, 2), "end_s": round(e, 2)}, None, quote

@router.get("/api/submissions/{sub_id}/annotations")
def list_annotations(sub_id: int):
    sub = db.get_submission(sub_id)
    if not sub:
        raise HTTPException(404, "submission not found")
    return {"annotations": db.list_annotations(sub_id)}

@router.post("/api/submissions/{sub_id}/annotations")
def create_annotation(sub_id: int, body: dict):
    """Create one annotation. body: {kind?, span, sticker?, level?, note?}.
    For written copies the quote is derived server-side from the OCR lines
    (never trusted from the client); for oral recordings from the segments."""
    sub = db.get_submission(sub_id)
    if not sub:
        raise HTTPException(404, "submission not found")
    body = body or {}
    span = body.get("span") or {}
    if not isinstance(span, dict):
        raise HTTPException(422, "span object required")
    level = (body.get("level") or "").strip().upper()
    if level and level not in ("A1", "A2", "B1", "B2", "C1", "C2"):
        raise HTTPException(422, "level must be A1..C2 or empty")
    sticker = (body.get("sticker") or "").strip() or None
    note = (body.get("note") or "").strip() or None
    try:
        clean_span, page_idx, quote = _validate_annotation_span(body, sub, span)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e))
    a_id = db.create_annotation(
        submission_id=sub_id, kind=sub["kind"], span=clean_span,
        quote=quote, sticker=sticker, level=level or None, note=note,
        page_idx=page_idx,
        analysis_id=(body.get("analysis_id") if isinstance(body.get("analysis_id"), int) else None))
    return db.get_annotation(a_id)

@router.put("/api/annotations/{annotation_id}")
def update_annotation_endpoint(annotation_id: int, body: dict):
    a = db.get_annotation(annotation_id)
    if not a:
        raise HTTPException(404, "annotation not found")
    body = body or {}
    level = body.get("level")
    if level is not None:
        level = (level or "").strip().upper()
        if level and level not in ("A1", "A2", "B1", "B2", "C1", "C2"):
            raise HTTPException(422, "level must be A1..C2 or empty")
    sticker = body.get("sticker")
    if sticker is not None:
        sticker = (sticker or "").strip() or None
    note = body.get("note")
    if note is not None:
        note = (note or "").strip() or None
    span = body.get("span")
    quote = None  # None = keep the stored quote
    page_idx = None
    if span is not None:
        if not isinstance(span, dict):
            raise HTTPException(422, "span object required")
        sub = db.get_submission(a["submission_id"])
        try:
            span, page_idx, quote = _validate_annotation_span(body, sub, span)
        except (ValueError, TypeError) as e:
            raise HTTPException(422, str(e))
    out = db.update_annotation(
        annotation_id, quote=quote, sticker=sticker,
        level=None if level is None else (level or None),
        note=None if note is None else note,
        span=span,
        page_idx=page_idx)
    if not out:
        raise HTTPException(404, "annotation not found")
    return out

@router.delete("/api/annotations/{annotation_id}")
def delete_annotation_endpoint(annotation_id: int):
    if not db.get_annotation(annotation_id):
        raise HTTPException(404, "annotation not found")
    db.delete_annotation(annotation_id)
    return {"deleted": annotation_id}

