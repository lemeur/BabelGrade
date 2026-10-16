"""Security test: media ownership on /api/files (2026-10-14).

Verifies that student copies (photos/audio) and assignment material
(instruction PDFs/photos, document PDFs/audio, eval notes) are only served
to their owner; foreign, unknown and untracked files all 404 identically.
In-process TestClient against a throwaway DB.
"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, "/home/tibo/elt-assessor")
from pathlib import Path as P
import app.db as db

TMP = P(tempfile.mkdtemp(prefix="elt_sec_test_"))
db.DB_PATH = TMP / "test.db"
db._CONN = None

# isolate uploads too: point UPLOAD_DIR at the temp dir via app.main patch
import app.main as m
m.UPLOAD_DIR = TMP / "uploads"
m.UPLOAD_DIR.mkdir(parents=True)

from fastapi.testclient import TestClient
from app import auth

app = m.create_app()
client = TestClient(app, raise_server_exceptions=True)
c1 = TestClient(app, raise_server_exceptions=True)

ok = True
def check(name, cond, extra=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))
    ok &= cond

# --- two users -------------------------------------------------------------
c1.post("/api/auth/register", json={"username": "tibo", "password": "tibo-pw-1"})
uid2 = auth.create_user("marie", "marie-pw-1")
c2 = TestClient(app, raise_server_exceptions=True)
c2.post("/api/auth/login", json={"username": "marie", "password": "marie-pw-1"})

def put(name, b=b"fakebytes"):
    (m.UPLOAD_DIR / name).write_bytes(b)

# --- tibo's data ------------------------------------------------------------
# 1) written submission with a page photo -> payload_meta page_paths
put("pg-aaa111-1.png")
before = {f.name for f in m.UPLOAD_DIR.iterdir() if f.name.startswith("pg-")}
r = c1.post("/api/analyze", files={"image": ("pg.png", b"\x89PNG fake", "image/png")},
            data={"kind": "written", "written_text": "bonjour", "rubric_id": "att-exp-ecrite"})
check("analyze written accepted", r.status_code == 200, r.text[:200])
sub1 = r.json()["submission_id"]
after = {f.name for f in m.UPLOAD_DIR.iterdir() if f.name.startswith("pg-")}
new = after - before
check("exactly one new photo for tibo", len(new) == 1, str(new))
tibo_photo = next(iter(new))

# sine tone wav (whisper gets real audio -> non-empty transcript -> doc audio
# gets persisted on the assignment). Generated once, reused.
import io as _io, wave as _wave, math as _math, struct as _struct
_wav_io = _io.BytesIO()
_w = _wave.open(_wav_io, "wb")
_w.setnchannels(1); _w.setsampwidth(2); _w.setframerate(16000)
_frames = b"".join(_struct.pack("<h", int(_math.sin(2 * _math.pi * 440 * i / 16000) * 12000))
                   for i in range(16000))  # 1 s of 440 Hz
_w.writeframes(_frames * 2)
_w.close()
_wav_bytes_sil = _wav_io.getvalue()

# 2) oral submission with audio
r = c1.post("/api/analyze", files={"audio": ("a.wav", _wav_bytes_sil, "audio/wav")},
            data={"kind": "oral", "rubric_id": "att-exp-orale"})
check("analyze oral accepted", r.status_code == 200, r.text[:200])
audios = [f.name for f in m.UPLOAD_DIR.iterdir() if f.name.startswith("aud-")]
check("tibo audio created", len(audios) >= 1, str(audios))
tibo_audio = audios[-1]

# 3) assignment with instruction PDF + source-document audio + eval notes
#    (field is `doc_audio` — `document_audio` is NOT a form field, it is
#     ignored by FastAPI; the earlier FAIL was a test bug, not an app bug)
try:
    import pymupdf as _pdf
    _buf = _pdf.new()
    _page = _buf.new_page()
    _page.insert_text((72, 72), "Consignes secretes B1")
    _pdf_bytes = _buf.tobytes()
except Exception:
    _pdf_bytes = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
r = c1.post("/api/assignments", files=[
    ("instruction_pdf", ("i.pdf", _pdf_bytes, "application/pdf")),
    ("doc_audio", ("d.wav", _wav_bytes_sil, "audio/wav")),
], data={"name": "Diss secret", "target_level": "B1", "skill": "expression",
         "kind": "written", "instruction": "Ecris un texte"})
check("assignment created", r.status_code == 200, r.text[:300])
asg = r.json()["id"]
r = c1.get(f"/api/assignments/{asg}")
a = r.json()
check("assignment exposes its files",
      bool(a.get("instruction_pdf_name") and a.get("document_audio_name")),
      str({k: a.get(k) for k in ("instruction_pdf_name", "document_audio_name")}))
asg_pdf = a["instruction_pdf_name"]
asg_audio = a["document_audio_name"]

# --- the map ------------------------------------------------------------
mmap = db.media_owner_map()
check("map owns tibo photo", mmap.get(tibo_photo) == 1, str(mmap.get(tibo_photo)))
check("map owns tibo audio", mmap.get(tibo_audio) == 1, str(mmap.get(tibo_audio)))
check("map owns assignment pdf", mmap.get(asg_pdf) == 1, str(mmap.get(asg_pdf)))
check("map owns assignment audio", mmap.get(asg_audio) == 1, str(mmap.get(asg_audio)))

# --- /api/files enforcement -------------------------------------------------
r = c1.get(f"/api/files/{tibo_photo}")
check("OWNER serves own photo", r.status_code == 200, str(r.status_code))
r = c2.get(f"/api/files/{tibo_photo}")
check("FOREIGN 404s on tibo's photo", r.status_code == 404, str(r.status_code))
r = c2.get(f"/api/files/{tibo_audio}")
check("FOREIGN 404s on tibo's audio", r.status_code == 404, str(r.status_code))
r = c1.get(f"/api/files/{tibo_audio}")
check("OWNER serves own audio", r.status_code == 200, str(r.status_code))
r = c2.get(f"/api/files/{asg_pdf}")
check("FOREIGN 404s on tibo's instruction PDF", r.status_code == 404, str(r.status_code))
r = c1.get(f"/api/files/{asg_pdf}")
check("OWNER serves own instruction PDF", r.status_code == 200, str(r.status_code))
r = c2.get(f"/api/files/{asg_audio}")
check("FOREIGN 404s on tibo's document audio", r.status_code == 404, str(r.status_code))
r = c1.get(f"/api/files/{asg_audio}")
check("OWNER serves own document audio", r.status_code == 200, str(r.status_code))
r = c2.get("/api/files/no-such-file-xyz.png")
check("UNKNOWN file 404 for marie", r.status_code == 404, str(r.status_code))
r = c1.get("/api/files/no-such-file-xyz.png")
check("UNKNOWN file 404 for tibo too", r.status_code == 404, str(r.status_code))
# untracked file (exists on disk, referenced by NO data row) -> 404 for both
put("pg-orphan999-1.png")
r = c1.get("/api/files/pg-orphan999-1.png")
check("UNTRACKED file 404 even for its 'uploader' (no data row)", r.status_code == 404, str(r.status_code))
r = c2.get("/api/files/pg-orphan999-1.png")
check("UNTRACKED file 404 for foreigner", r.status_code == 404, str(r.status_code))
# traversal guard still intact
r = c2.get("/api/files/..%2F..%2Fetc%2Fpasswd")
check("path traversal blocked", r.status_code in (404, 405), str(r.status_code))

# --- marie's own files stay reachable by marie -----------------------------
before = {f.name for f in m.UPLOAD_DIR.iterdir() if f.name.startswith("aud-")}
r = c2.post("/api/analyze", files={"audio": ("b.wav", _wav_bytes_sil, "audio/wav")},
            data={"kind": "oral", "rubric_id": "att-exp-orale"})
check("marie analyze accepted", r.status_code == 200, r.text[:200])
if r.status_code == 200:
    after = {f.name for f in m.UPLOAD_DIR.iterdir() if f.name.startswith("aud-")}
    new = after - before
    check("exactly one new audio for marie", len(new) == 1, str(new))
    marie_audio = next(iter(new))
    r = c2.get(f"/api/files/{marie_audio}")
    check("MARIE serves her own audio", r.status_code == 200, str(r.status_code))
    r = c1.get(f"/api/files/{marie_audio}")
    check("TIBO 404s on marie's audio", r.status_code == 404, str(r.status_code))

# --- scoping of the raw-SQL endpoints --------------------------------------
# marie cannot read tibo's analysis (get_analysis scoped) -> so cannot
# delete or counter-propose it either.
subs = c1.get("/api/analyses").json()
check("tibo has >=2 analyses", len(subs) >= 2, str(len(subs)))
aid = subs[0]["analysis_id"]
check("tibo reads own analysis", c1.get(f"/api/analyses/{aid}").status_code == 200)
check("marie 404s on tibo's analysis", c2.get(f"/api/analyses/{aid}").status_code == 404)
check("marie DELETE tibo's analysis -> 404", c2.delete(f"/api/analyses/{aid}").status_code == 404)
check("marie PUT tibo's analysis -> 404", c2.put(f"/api/analyses/{aid}", json={"note20": None}).status_code == 404)
check("tibo's analysis survived marie", c1.get(f"/api/analyses/{aid}").status_code == 200)
# stats-ai scoping: tibo's assignment insight invisible to marie
check("marie GET tibo's stats-ai -> 404", c2.get(f"/api/assignments/{asg}/stats-ai").status_code == 404)
check("marie DELETE tibo's stats-ai -> 0 deleted", c2.delete(f"/api/assignments/{asg}/stats-ai").json().get("deleted") == 0)

print()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
