"""Batch-augment all fixture submissions with REAL ENGLISH media (Annoter test).

Same as gen_media.py but for an English ELT class:
  - written: copy photo (PIL) + ocr_page(lang='en' -> tesseract 'eng')
  - oral: English Piper voices + whisper.transcribe(lang='en')
  - submissions.language / analyses transcript language = 'en'
First removes the previously-generated (French) media files so uploads/ stays
clean, then regenerates all 160.
"""
import sys, os, json, uuid, datetime, random, glob
sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import sqlite3
from PIL import Image
from app.ocr import ocr_page
from app import whisper
from app.assess import fluency_metrics
from photo_gen import render_page
from media_content_en import pick_content

DB = "data/elt_assessor.db"
UP = "data/uploads"
os.makedirs(UP, exist_ok=True)

PIPER = "/tmp/piper_tts/venv/bin/piper"
VOICES = [
    ("en_amy",  "en_US"),
    ("en_ryan", "en_US"),
    ("en_jenny","en_GB"),
]
import subprocess

SUBJ_KEY = {
    ("comprehension", "oral"):    "comp-orale",
    ("comprehension", "written"): "comp-ecrite",
    ("expression",    "oral"):    "prod-orale",
    ("expression",    "written"): "prod-ecrite",
}


def first_name(full: str) -> str:
    return full.split(" ")[0] if full else ""


def synth(text: str, student_id: int, name: str) -> tuple[str, float]:
    voice, _ = VOICES[student_id % len(VOICES)]
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


def clear_old_media(con):
    """Delete the currently-referenced media files + rows' media columns."""
    names = set()
    for (pm,) in con.execute("SELECT payload_meta_json FROM submissions "
                             "WHERE payload_meta_json IS NOT NULL"):
        m = json.loads(pm)
        names.update(m.get("page_paths") or [])
        if m.get("audio_name"):
            names.add(m["audio_name"])
    removed = 0
    for f in names:
        p = os.path.join(UP, f)
        if os.path.exists(p):
            os.remove(p); removed += 1
    con.execute("UPDATE submissions SET payload_path='', source_type='pending', "
                "payload_meta_json=NULL, ocr_json=NULL, duration_s=NULL")
    con.execute("UPDATE analyses SET transcript_json=NULL, fluency_json=NULL")
    con.commit()
    print(f"cleared {removed} old media files + reset media columns")


def main():
    rng = random.Random(20261013)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    clear_old_media(con)
    rows = [dict(r) for r in con.execute("""
        SELECT sub.id subid, sub.student_id, sub.kind, sub.assignment_id,
               s.name, a.skill, an.id aid
        FROM submissions sub
        JOIN students s ON s.id=sub.student_id
        JOIN assignments a ON a.id=sub.assignment_id
        LEFT JOIN analyses an ON an.submission_id=sub.id
        ORDER BY sub.id""")]
    print(f"{len(rows)} submissions to process (ENGLISH)")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    n_w = n_o = 0
    for r in rows:
        key = SUBJ_KEY[(r["skill"], r["kind"])]
        # overall level from analysis (or default B1)
        ol = con.execute("SELECT overall_level FROM analyses WHERE id=?",
                         (r["aid"],)).fetchone()
        level = (ol[0] if ol and ol[0] else "B1")
        text = pick_content(key, level, r["student_id"], first_name(r["name"]))

        if r["kind"] == "written":
            img, meta = render_page(text, rng)
            pg_name = f"pg-{uuid.uuid4().hex}-1.jpg"
            img.save(f"{UP}/{pg_name}", "JPEG", quality=88)
            pg = ocr_page(f"{UP}/{pg_name}", "en")
            pg["name"] = pg_name
            ocr_blob = {"generated_at": now, "engine": "tesseract",
                        "language": "en", "pages": [pg]}
            ocr_text = " ".join(l["text"] for l in pg["lines"])
            con.execute("""UPDATE submissions SET payload_path=?, source_type=?,
                language=?, payload_meta_json=?, ocr_json=? WHERE id=?""",
                (ocr_text, "image", "en",
                 json.dumps({"page_paths": [pg_name], "page_count": 1},
                            ensure_ascii=False),
                 json.dumps(ocr_blob, ensure_ascii=False), r["subid"]))
            n_w += 1
        else:
            wav_name, dur = synth(text, r["student_id"], r["name"])
            tr = whisper.transcribe(f"{UP}/{wav_name}", "en")
            transcript_blob = {"text": tr["text"], "segments": tr["segments"],
                               "duration_s": tr["duration_s"],
                               "language": tr["language"]}
            flu = fluency_metrics(tr)
            con.execute("""UPDATE submissions SET payload_path=?, source_type=?,
                duration_s=?, language=?, payload_meta_json=? WHERE id=?""",
                (tr["text"], "audio", tr["duration_s"], "en",
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
