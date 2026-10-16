"""Local audio transcription via faster-whisper (offline, cached model).

Loads the model once per process; transcribes to word/segment-level
timestamps. Falls back gracefully if the model cache is missing.
"""
import os
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HUGGINGFACE_HUB_OFFLINE", "1")

CACHE_DIR = "/home/tibo/.cache/huggingface/hub"
MODEL_NAME = "base"

_model = None
_model_error: str | None = None


def _load():
    global _model, _model_error
    if _model is not None:
        return _model
    from faster_whisper import WhisperModel
    _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8",
                          download_root=CACHE_DIR)
    return _model


def model_status() -> dict:
    global _model_error
    if _model is not None:
        return {"available": True, "model": MODEL_NAME, "device": "cpu",
                "loaded": True}
    if _model_error:
        return {"available": False, "model": MODEL_NAME, "error": _model_error}
    try:
        t0 = time.time()
        _load()
        return {"available": True, "model": MODEL_NAME, "device": "cpu",
                "loaded": True, "load_s": round(time.time() - t0, 1)}
    except Exception as e:
        _model_error = f"{type(e).__name__}: {e}"
        return {"available": False, "model": MODEL_NAME, "error": _model_error}


def transcribe(audio_path: str, language: str = "en") -> dict:
    """Transcribe an audio file.

    Returns {text, language, duration_s, words: [{w, start, end, prob}],
             segments: [{start, end, text}], wpm}.
    """
    t0 = time.time()
    m = _load()
    p = Path(audio_path)
    if not p.exists():
        raise FileNotFoundError(audio_path)

    segments, info = m.transcribe(
        str(p), language=language or None, vad_filter=True,
        word_timestamps=True,
    )
    words = []
    segs = []
    for s in segments:
        seg_text = s.text.strip()
        segs.append({"start": round(s.start, 2), "end": round(s.end, 2),
                     "text": seg_text})
        for w in (s.words or []):
            words.append({"w": w.word.strip(), "start": round(w.start, 2),
                          "end": round(w.end, 2), "prob": round(w.probability, 3)})

    full = " ".join(seg["text"] for seg in segs).strip()
    dur = round(info.duration, 2)
    word_count = len([w for w in words if w["w"]])
    wpm = round(word_count / (dur / 60.0), 1) if dur > 0 else 0

    return {
        "text": full,
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "duration_s": dur,
        "elapsed_s": round(time.time() - t0, 1),
        "word_count": word_count,
        "wpm": wpm,
        "words": words,
        "segments": segs,
    }
