"""Batch-augment all fixture submissions with REAL media for the Annoter test.

For every submission:
  - written (comp-ecrite, prod-ecrite):
      render a "copy" page photo (PIL) -> data/uploads/pg-*.jpg
      run the app's real ocr_page() -> submissions.ocr_json
      payload_path = OCR text, source_type = "image",
      payload_meta = {page_paths:[name], page_count:1}
  - oral (comp-orale, prod-orale):
      synthesize French speech (Piper) -> data/uploads/aud-*.wav
      run the app's real whisper.transcribe() -> analyses.transcript_json
      + analyses.fluency_json, submissions.duration_s
      payload_path = transcript text, source_type = "audio",
      payload_meta = {audio_name}

Uses the app's own code paths (ocr_page, whisper.transcribe,
fluency_metrics) so the stored shapes exactly match production.
"""
import sys, os, json, uuid, datetime, random
sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import sqlite3
from PIL import Image
from app.ocr import ocr_page
from app import whisper
from app.assess import fluency_metrics
from photo_gen import render_page
from media_content import pick_content

DB = "data/elt_assessor.db"
UP = "data/uploads"
os.makedirs(UP, exist_ok=True)

PIPER = "/tmp/piper_tts/venv/bin/piper"
VOICES = ["upmc", "siwis", "tom"]
import subprocess

SUBJ_KEY = {
    ("comprehension", "oral"): "comp-orale",
    ("comprehension", "written"): "comp-ecrite",
    ("expression", "oral"): "prod-orale",
    ("expression", "written"): "prod-ecrite",
}


def first_name(full: str) -> str:
    return full.split(" ")[0] if full else ""


def synth(text: str, student_id: int, name: str) -> tuple[str, float]:
    """Piper TTS -> wav in uploads. Returns (wav_name, duration_s)."""
    voice = VOICES[student_id % len(VOICES)]
    txt = text.replace("{name}", first_name(name))
    inp = f"/tmp/piper_tts/batch_{uuid.uuid4().hex}.txt"
    open(inp, "w").write(txt)
    wav_name = f"aud-{uuid.uuid4().hex}.wav"
    out = f"{UP}/{wav_name}"
    subprocess.run([PIPER, "-m", f"/tmp/piper_tts/voices/{voice}.onnx",
                    "-c", "3", "-i", inp, "--output_file", out],
                   check=True, capture_output=True, text=True)
    dur = float(subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", out], capture_output=True,
        text=True).stdout.strip())
    os.remove(inp)
    return wav_name, dur


def main():
    rng = random.Random(20261012)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("""
        SELECT sub.id subid, sub.student_id, sub.kind, sub.assignment_id,
               s.name, an.id aid, an.status, an.overall_level
        FROM submissions sub
        JOIN students s ON s.id=sub.student_id
        JOIN assignments a ON a.id=sub.assignment_id
        LEFT JOIN analyses an ON an.submission_id=sub.id
        ORDER BY sub.id""")]
    print(f"{len(rows)} submissions to process")

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    n_w = n_o = 0
    for r in rows:
        skill = con.execute("SELECT skill FROM assignments WHERE id=?",
                            (r["assignment_id"],)).fetchone()[0]
        key = SUBJ_KEY[(skill, r["kind"])]
        tier_level = r["overall_level"] or "B1"
        text = pick_content(key, tier_level, r["student_id"],
                            first_name(r["name"]))

        if r["kind"] == "written":
            img, meta = render_page(text, rng)
            pg_name = f"pg-{uuid.uuid4().hex}-1.jpg"
            img.save(f"{UP}/{pg_name}", "JPEG", quality=88)
            pg = ocr_page(f"{UP}/{pg_name}", "fr")
            pg["name"] = pg_name
            ocr_blob = {"generated_at": now, "engine": "tesseract",
                        "language": "fr", "pages": [pg]}
            ocr_text = " ".join(l["text"] for l in pg["lines"])
            con.execute("""UPDATE submissions SET payload_path=?, source_type=?,
                payload_meta_json=?, ocr_json=? WHERE id=?""",
                (ocr_text, "image",
                 json.dumps({"page_paths": [pg_name], "page_count": 1},
                            ensure_ascii=False),
                 json.dumps(ocr_blob, ensure_ascii=False), r["subid"]))
            n_w += 1
        else:  # oral
            wav_name, dur = synth(text, r["student_id"], r["name"])
            tr = whisper.transcribe(f"{UP}/{wav_name}", "fr")
            transcript_blob = {"text": tr["text"], "segments": tr["segments"],
                               "duration_s": tr["duration_s"],
                               "language": tr["language"]}
            flu = fluency_metrics(tr)
            con.execute("""UPDATE submissions SET payload_path=?, source_type=?,
                duration_s=?, language=?, payload_meta_json=? WHERE id=?""",
                (tr["text"], "audio", tr["duration_s"], "fr",
                 json.dumps({"audio_name": wav_name}, ensure_ascii=False),
                 r["subid"]))
            if r["aid"]:
                con.execute("""UPDATE analyses SET transcript_json=?,
                    fluency_json=? WHERE id=?""",
                    (json.dumps(transcript_blob, ensure_ascii=False),
                     json.dumps(flu, ensure_ascii=False), r["aid"]))
            n_o += 1
        if (n_w + n_o) % 10 == 0:
            con.commit()
            print(f"  ...{n_w+n_o} done (W:{n_w} O:{n_o})", flush=True)

    con.commit()
    con.close()
    print(f"DONE  written={n_w}  oral={n_o}")


if __name__ == "__main__":
    main()
