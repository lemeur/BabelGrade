"""SQLite persistence: rubrics, students, submissions (written/oral), analyses."""
import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "elt_assessor.db"
_LOCK = threading.RLock()
_local = threading.local()


def _conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- multi-user
_OWNED_TABLES = ("students", "assignments", "submissions", "analyses",
                 "annotations", "jobs")


def _owner() -> int | None:
    """The authenticated user id for the current request/job (contextvar set
    by main.py's auth middleware / the job worker). Every scoping helper
    reads it, so callers never pass the owner explicitly."""
    try:
        from . import auth
        return auth.current_owner()
    except Exception:
        return None


def _scoped(table: str, alias: str = "") -> tuple[str, list]:
    """SQL WHERE clause limiting one owned table to the current user's rows.

    `alias` is the SQL table alias to use in the clause (e.g. "sub" for the
    submissions table). Returns ("", []) when unauthenticated (system
    context — bootstrap, migrations) or when `table` is not an owned table.
    """
    if table not in _OWNED_TABLES:
        return "", []
    o = _owner()
    if o is None:
        return "", []
    return f"{alias or table}.owner_id=?", [o]


def _rubric_scoped(alias: str = "r") -> tuple[str, list]:
    """Rubrics are shared-or-owned: presets (owner_id IS NULL) are visible to
    everyone, custom rubrics only to their owner."""
    o = _owner()
    if o is None:
        return "", []
    return f"({alias}.owner_id IS NULL OR {alias}.owner_id=?)", [o]


def init_db() -> None:
    with _LOCK:
        c = _conn()
        # 2026-10-13 multi-user: users + sessions tables (created FIRST so
        # the owner backfill below can reference the initial account).
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                username_lower TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL
            );
            """)
        c.commit()
    _init_schema()          # pre-multi-user schema + forward migrations
    _ensure_owner_columns() # owner_id on every owned table (after they exist)
    _migrate_multiuser()    # attach legacy rows to the first account


def _ensure_owner_columns() -> None:
    """Add owner_id to every owned table if missing (fresh DBs create the
    tables WITHOUT owner_id via _init_schema; existing DBs already have it
    from a previous boot). Preset rubrics keep owner_id NULL = shared by
    everyone (official LVA/LVB grids)."""
    with _LOCK:
        c = _conn()
        for tbl in ("rubrics", "students", "assignments", "submissions",
                    "analyses", "annotations", "jobs"):
            cols = {r[1] for r in c.execute(f"PRAGMA table_info({tbl})")}
            if "owner_id" not in cols:
                c.execute(f"ALTER TABLE {tbl} ADD COLUMN owner_id INTEGER")
        c.commit()


def _migrate_multiuser() -> None:
    """One-shot owner backfill (2026-10-13): existing single-user data is
    attached to the initial account (the first user in the table). Idempotent
    — never touches rows that already carry an owner."""
    with _LOCK:
        c = _conn()
        owner = c.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        if not owner:
            return  # no account yet (fresh install) — nothing to migrate
        owner_id = owner[0]
        for tbl in ("students", "assignments", "submissions", "analyses",
                    "annotations", "jobs"):
            c.execute(f"UPDATE {tbl} SET owner_id=? WHERE owner_id IS NULL",
                      (owner_id,))
        # rubrics: backfill only the NON-preset ones (presets stay shared).
        c.execute("UPDATE rubrics SET owner_id=? "
                  "WHERE owner_id IS NULL AND is_preset=0", (owner_id,))
        c.commit()


def _init_schema() -> None:
    """Schema creation + forward migrations (the pre-multi-user init_db
    body, kept verbatim)."""
    with _LOCK:
        c = _conn()
        # 2026-10-05 rename: tasks -> assignments (UI concept "Sujets /
        # Assignments"). Runs BEFORE the fresh-DB CREATE TABLE: otherwise
        # `assignments` gets created empty and the rename below is skipped
        # because both tables already exist. Idempotent. SQLite >= 3.25
        # updates other schemas' references on RENAME.
        old_tables = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "tasks" in old_tables:
            if "assignments" in old_tables:
                # broken intermediate state from an earlier boot: carry the
                # data over by explicit column names (the live tasks table may
                # have a different column ORDER than the fresh DDL because
                # older versions added columns via ALTER TABLE), then drop it. The live submissions column already reads
                # `assignment_id REFERENCES tasks(id) ON DELETE SET NULL`, so
                # with foreign_keys ON the DROP would NULL out every linked
                # submission -> do the drop (and the submissions rebuild
                # below) with foreign keys OFF.
                c.execute("PRAGMA foreign_keys=OFF")
                task_cols = [r[1] for r in c.execute("PRAGMA table_info(tasks)")]
                asgn_cols = [r[1] for r in c.execute("PRAGMA table_info(assignments)")]
                common = [k for k in asgn_cols if k in task_cols]
                c.execute(f"INSERT INTO assignments ({', '.join(common)}) "
                          f"SELECT {', '.join(common)} FROM tasks")
                c.execute("DROP TABLE tasks")
                # dropping tasks leaves its sqlite_sequence row; dedup so the
                # assignments seq stays authoritative.
                c.execute("DELETE FROM sqlite_sequence WHERE name='tasks'")
            else:
                # clean path: RENAME carries the data AND (SQLite >= 3.25)
                # updates other schemas' FK references to the new name, so
                # linked submissions keep their ids.
                c.execute("ALTER TABLE tasks RENAME TO assignments")
        old_sub_cols = {r[1] for r in c.execute("PRAGMA table_info(submissions)")}
        if "task_id" in old_sub_cols and "assignment_id" not in old_sub_cols:
            c.execute("ALTER TABLE submissions RENAME COLUMN task_id TO assignment_id")
        # Follow-up of the rename: REname COLUMN does NOT update the FK's
        # referenced table name, so the live submissions schema can still read
        # `assignment_id INTEGER REFERENCES tasks(id)`. Rebuild the table with
        # the corrected FK (same column order, same constraints) when needed.
        # Fresh DBs: the table does not exist yet (created below) — skip.
        sub_sql = c.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='submissions'"
        ).fetchone()
        sub_sql = sub_sql[0] if sub_sql else None
        if sub_sql and "REFERENCES tasks(" in sub_sql:
            live_cols = [r[1] for r in c.execute("PRAGMA table_info(submissions)")]
            c.execute("CREATE TABLE submissions_new ("
                      "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                      "student_id INTEGER REFERENCES students(id) ON DELETE SET NULL,"
                      "kind TEXT NOT NULL CHECK (kind IN ('written','oral')),"
                      "title TEXT,"
                      "source_type TEXT NOT NULL,"
                      "payload_path TEXT,"
                      "language TEXT,"
                      "duration_s REAL,"
                      "target_level TEXT,"
                      "created_at TEXT NOT NULL,"
                      "payload_meta_json TEXT,"
                      "context_json TEXT,"
                      "eval_notes_json TEXT,"
                      "assignment_id INTEGER REFERENCES assignments(id) ON DELETE SET NULL,"
                      "accommodations TEXT)")
            c.execute(f"INSERT INTO submissions_new SELECT {', '.join(live_cols)} FROM submissions")
            c.execute("DROP TABLE submissions")
            c.execute("ALTER TABLE submissions_new RENAME TO submissions")
            # keep AUTOINCREMENT continuity: a DROP TABLE keeps the old
            # sqlite_sequence row, so delete-then-insert (dedup) the seq.
            c.execute("DELETE FROM sqlite_sequence WHERE name='submissions'")
            c.execute("INSERT INTO sqlite_sequence(name, seq) VALUES ('submissions', "
                      "(SELECT MAX(id) FROM submissions))")
        # the broken-state path above dropped tables with foreign keys OFF —
        # restore the session default so FK enforcement stays ON afterwards.
        c.execute("PRAGMA foreign_keys=ON")
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS rubrics (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                mode TEXT NOT NULL CHECK (mode IN ('written','oral')),
                criteria_json TEXT NOT NULL,
                meta_json TEXT,
                is_preset INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                classroom TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                target_level TEXT,
                skill TEXT,          -- comprehension | expression (type d'exercice)
                kind TEXT,           -- written | oral (canal : écrit ou oral)
                instruction TEXT,
                instruction_pdf_name TEXT,
                instruction_photo_names TEXT,
                document_text TEXT,
                document_pdf_name TEXT,
                document_pdf_page_names TEXT,
                document_photo_names TEXT,
                document_audio_name TEXT,
                eval_notes TEXT,
                eval_notes_pdf_name TEXT,
                eval_notes_pdf_page_names TEXT,
                eval_notes_photo_names TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER REFERENCES students(id) ON DELETE SET NULL,
                assignment_id INTEGER REFERENCES assignments(id) ON DELETE SET NULL,
                kind TEXT NOT NULL CHECK (kind IN ('written','oral')),
                title TEXT,
                source_type TEXT NOT NULL,   -- image | text | audio
                payload_path TEXT,           -- stored file (image/audio) or transcript text
                language TEXT,
                duration_s REAL,
                target_level TEXT,
                payload_meta_json TEXT,    -- e.g. {"page_paths": [...], "page_count": N}
                context_json TEXT,         -- assignment context: instruction + source document
                eval_notes_json TEXT,      -- teacher evaluation notes {text, pdf_name, page_count}
                accommodations TEXT,       -- per-student evaluation accommodations
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
                rubric_id TEXT REFERENCES rubrics(id),
                overall_level TEXT,
                raw_markdown TEXT DEFAULT '',
                matrix_json TEXT,
                feedback TEXT,
                fluency_json TEXT,
                transcript_json TEXT,
                status TEXT NOT NULL DEFAULT 'done',   -- done | error | processing
                error TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS trg_analyses_raw_default
            AFTER INSERT ON analyses
            WHEN NEW.raw_markdown IS NULL
            BEGIN UPDATE analyses SET raw_markdown = '' WHERE id = NEW.id; END;
            """
        )
        # schema migration: add new columns to pre-existing DBs
        for col in ("fluency_json TEXT", "transcript_json TEXT",
                    "note20_json TEXT", "validated_at TEXT",
                    "ai_matrix_json TEXT", "ai_mode TEXT", "ai_at TEXT",
                    "transcript_correction_json TEXT",
                    "transcript_mode TEXT"):
            existing = {r[1] for r in c.execute("PRAGMA table_info(analyses)")}
            if col.split()[0] not in existing:
                c.execute(f"ALTER TABLE analyses ADD COLUMN {col}")
        sub_cols = {r[1] for r in c.execute("PRAGMA table_info(submissions)")}
        if "target_level" not in sub_cols:
            c.execute("ALTER TABLE submissions ADD COLUMN target_level TEXT")
        if "payload_meta_json" not in sub_cols:
            c.execute("ALTER TABLE submissions ADD COLUMN payload_meta_json TEXT")
        if "context_json" not in sub_cols:
            c.execute("ALTER TABLE submissions ADD COLUMN context_json TEXT")
        if "eval_notes_json" not in sub_cols:
            c.execute("ALTER TABLE submissions ADD COLUMN eval_notes_json TEXT")
        if "ocr_json" not in sub_cols:
            c.execute("ALTER TABLE submissions ADD COLUMN ocr_json TEXT")
        if "assignment_id" not in sub_cols:
            c.execute("ALTER TABLE submissions ADD COLUMN assignment_id INTEGER "
                      "REFERENCES assignments(id) ON DELETE SET NULL")
        if "accommodations" not in sub_cols:
            c.execute("ALTER TABLE submissions ADD COLUMN accommodations TEXT")
        stu_cols = {r[1] for r in c.execute("PRAGMA table_info(students)")}
        if "classroom" not in stu_cols:
            c.execute("ALTER TABLE students ADD COLUMN classroom TEXT")
        asgn_cols = {r[1] for r in c.execute("PRAGMA table_info(assignments)")}
        for col in ("document_pdf_page_names TEXT", "eval_notes_pdf_page_names TEXT",
                    "skill TEXT", "kind TEXT", "eval_notes_photo_names TEXT"):
            if col.split()[0] not in asgn_cols:
                c.execute(f"ALTER TABLE assignments ADD COLUMN {col}")
        # one-shot backfill of the exercise type (2026-10-10): pre-existing
        # subjects carry the written/oral channel ONLY in their name
        # (convention "… (oral)" / "… (written)"). Seed the new `kind` column
        # from that convention so the UI can auto-pick the matching rubric;
        # anything without the convention stays NULL (= unknown). Idempotent:
        # only rows with a NULL kind are ever touched.
        _asgn_cols = {r[1] for r in c.execute("PRAGMA table_info(assignments)")}
        if "kind" in _asgn_cols:
            _rows = c.execute(
                "SELECT id, name FROM assignments WHERE kind IS NULL").fetchall()
            for _r in _rows:
                _s = (_r["name"] or "").lower()
                _k = None
                if "(oral" in _s or re.search(r"\boral\b", _s):
                    _k = "oral"
                elif "(written" in _s or re.search(r"\bwritten\b", _s):
                    _k = "written"
                if _k:
                    c.execute("UPDATE assignments SET kind=? WHERE id=? AND kind IS NULL",
                              (_k, _r["id"]))
        rub_cols = {r[1] for r in c.execute("PRAGMA table_info(rubrics)")}
        if "meta_json" not in rub_cols:
            c.execute("ALTER TABLE rubrics ADD COLUMN meta_json TEXT")
        # schema migration: relax raw_markdown NOT NULL on pre-existing DBs
        info = {r[1]: r for r in c.execute("PRAGMA table_info(analyses)")}
        if "raw_markdown" in info and info["raw_markdown"]["notnull"]:
            cols = [r[1] for r in c.execute("PRAGMA table_info(analyses)")]
            c.executescript(
                "ALTER TABLE analyses RENAME TO analyses_old;"
                "CREATE TABLE analyses ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "submission_id INTEGER NOT NULL,"
                "rubric_id TEXT,"
                "overall_level TEXT,"
                "raw_markdown TEXT DEFAULT '',"
                "matrix_json TEXT,"
                "feedback TEXT,"
                "fluency_json TEXT,"
                "transcript_json TEXT,"
                "status TEXT NOT NULL DEFAULT 'done',"
                "error TEXT,"
                "created_at TEXT NOT NULL"
                ");"
                f"INSERT INTO analyses SELECT {', '.join(cols)} FROM analyses_old;"
                "DROP TABLE analyses_old;"
            )
        # 2026-10-06: async job queue — long processing (Whisper transcription,
        # PDF extraction, LLM analysis, run-ai) runs in worker tasks off the
        # request thread; jobs are persisted so the queue survives a restart.
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,                    -- analyze | evaluate | run_ai
                status TEXT NOT NULL DEFAULT 'queued',-- queued|running|done|error|cancelled
                payload_json TEXT NOT NULL,
                submission_id INTEGER,
                analysis_id INTEGER,
                cancel_flag INTEGER NOT NULL DEFAULT 0,
                phase TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                elapsed_s REAL,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        job_cols = {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
        if "phase" not in job_cols:
            c.execute("ALTER TABLE jobs ADD COLUMN phase TEXT")
        # 2026-10-13: terminal payload of a job (the stats-ai "class insight"
        # JSON result) — persisted so the result survives the 15-min stream GC.
        if "result_json" not in job_cols:
            c.execute("ALTER TABLE jobs ADD COLUMN result_json TEXT")
        # 2026-10-08: teacher annotations — passages the teacher highlights on
        # the student's copy (written: text span over the OCR lines; oral: time
        # span over the transcript), each carrying an emoji sticker, an
        # estimated level, and an optional note. One row = one annotation; the
        # spans are stored in span_json.
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS annotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
                analysis_id INTEGER,
                kind TEXT NOT NULL CHECK (kind IN ('written','oral')),
                page_idx INTEGER,
                span_json TEXT NOT NULL,
                quote TEXT,
                sticker TEXT,
                level TEXT,
                note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS passage_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
                annotation_id INTEGER NOT NULL REFERENCES annotations(id) ON DELETE CASCADE,
                criterion TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        c.commit()


# ---------------------------------------------------------------- rubrics
def _rubric_meta(r: dict) -> dict:
    """Attestation-specific fields not covered by name/mode/criteria."""
    return {k: r[k] for k in ("attestation", "modalite", "point_scale", "modes") if k in r}


def upsert_rubric(r: dict) -> None:
    with _LOCK:
        c = _conn()
        # Presets keep owner_id NULL (shared); custom rubrics belong to the
        # caller (contextvar). Seeding a preset must never clobber an
        # existing CUSTOM rubric (owned by some user) — the DO UPDATE WHERE
        # clause only rewrites preset-owned / ownerless rows.
        c.execute(
            "INSERT INTO rubrics (id,name,mode,criteria_json,meta_json,is_preset,created_at,owner_id) "
            "VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, "
            "mode=excluded.mode, criteria_json=excluded.criteria_json, "
            "meta_json=excluded.meta_json, is_preset=excluded.is_preset, "
            "created_at=excluded.created_at, owner_id=excluded.owner_id "
            "WHERE rubrics.owner_id IS NULL OR rubrics.is_preset=1",
            (r["id"], r["name"], r["mode"],
             json.dumps(r["criteria"], ensure_ascii=False),
             json.dumps(_rubric_meta(r), ensure_ascii=False) if _rubric_meta(r) else None,
             int(bool(r.get("is_preset"))),
             now_iso(),
             None if r.get("is_preset") else _owner()),
        )
        c.commit()


def _attach_meta(d: dict) -> dict:
    if d.get("meta_json"):
        try:
            d.update(json.loads(d["meta_json"]))
        except Exception:
            pass
    d.pop("meta_json", None)
    return d


def get_rubric(rubric_id: str) -> dict | None:
    """One rubric, visible to the caller: shared presets (owner_id NULL) or
    the caller's own custom rubric. Unauthenticated (system) sees all."""
    o = _owner()
    where = "id=?"
    args: list = [rubric_id]
    if o is not None:
        where += " AND (owner_id IS NULL OR owner_id=?)"
        args.append(o)
    with _LOCK:
        row = _conn().execute(f"SELECT * FROM rubrics WHERE {where}", args).fetchone()
    if not row:
        return None
    d = dict(row)
    d["criteria"] = json.loads(d.pop("criteria_json"))
    d["is_preset"] = bool(d["is_preset"])
    return _attach_meta(d)


def rubric_matches_mode(r: dict, mode: str) -> bool:
    """A rubric fits a mode if its mode equals it or its modes list contains it."""
    if r.get("mode") == mode:
        return True
    return mode in (r.get("modes") or [])


def list_rubrics(mode: str | None = None) -> list[dict]:
    """Rubrics visible to the caller: ALL presets (owner_id NULL, shared) +
    the caller's own custom rubrics. System context (no owner) sees all."""
    o = _owner()
    q = "SELECT * FROM rubrics"
    args: list = []
    if o is not None:
        q += " WHERE owner_id IS NULL OR owner_id=?"
        args.append(o)
    with _LOCK:
        rows = _conn().execute(q, args).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        d["criteria"] = json.loads(d.pop("criteria_json"))
        d["is_preset"] = bool(d["is_preset"])
        d = _attach_meta(d)
        if mode and not rubric_matches_mode(d, mode):
            continue
        out.append(d)
    return sorted(out, key=lambda r: (not r["is_preset"], r["name"]))


def delete_rubric(rubric_id: str) -> bool:
    """Delete a rubric the caller may see (presets are delete-protected at the
    API layer; this also refuses to delete another user's custom rubric)."""
    o = _owner()
    where = "id=?"
    args: list = [rubric_id]
    if o is not None:
        where += " AND (owner_id IS NULL OR owner_id=?)"
        args.append(o)
    with _LOCK:
        n = _conn().execute(f"DELETE FROM rubrics WHERE {where}", args).rowcount
        _conn().commit()
    return n > 0


# ---------------------------------------------------------------- students
def create_student(name: str, classroom: str = "") -> int:
    with _LOCK:
        c = _conn()
        cur = c.execute(
            "INSERT INTO students (name, classroom, created_at, owner_id) VALUES (?,?,?,?)",
            (name, classroom or None, now_iso(), _owner()))
        c.commit()
        return cur.lastrowid


def update_student(student_id: int, *, name: str | None = None,
                   classroom: str | None = None) -> dict | None:
    where, args = _scoped("students")
    if where:
        where = f"id=? AND {where}"
        args = [student_id] + args
    else:
        where = "id=?"
        args = [student_id]
    with _LOCK:
        c = _conn()
        row = c.execute(f"SELECT * FROM students WHERE {where}", args).fetchone()
        if not row:
            return None
        # UPDATE re-uses the same owner clause (one extra ? when scoped)
        uargs = [
            (name or row["name"]).strip() or row["name"],
            classroom if classroom is not None else row["classroom"],
            student_id,
        ] + (args[1:] if where != "id=?" else [])
        c.execute(
            f"UPDATE students SET name=?, classroom=? WHERE {where}", uargs)
        c.commit()
    return get_student(student_id)


def list_students() -> list[dict]:
    where, args = _scoped("students", "s")
    # The owner clause is used TWICE in this query (subquery + outer WHERE),
    # so it needs two bound values — one per `?`.
    q = (
        "SELECT s.*, "
        "(SELECT COUNT(*) FROM submissions sub "
        + (f"WHERE sub.student_id=s.id AND {where}" if where
           else "WHERE sub.student_id=s.id")
        + ") AS submissions FROM students s"
    )
    if where:
        q += f" WHERE {where}"
    q += " ORDER BY COALESCE(s.classroom,'') COLLATE NOCASE, s.name COLLATE NOCASE"
    with _LOCK:
        rows = _conn().execute(q, args * (2 if where else 1)).fetchall()
    return [dict(r) for r in rows]


def get_student(student_id: int) -> dict | None:
    where, args = _scoped("students")
    q = "SELECT * FROM students WHERE id=?"
    a: list = [student_id]
    if where:
        q += f" AND {where}"
        a += args
    with _LOCK:
        row = _conn().execute(q, a).fetchone()
    return dict(row) if row else None


def delete_student(student_id: int, cascade: bool = False) -> dict:
    """Delete one student of the caller. With `cascade=True` their
    submissions (and the analyses attached to them, via the FK) are removed
    too; otherwise the submissions are kept but lose their student link
    (ON DELETE SET NULL)."""
    # ownership check first (another user's student = not found)
    if get_student(student_id) is None:
        return {"deleted": [], "submissions_deleted": 0,
                "submissions_unlinked": 0, "not_found": True}
    ids = [student_id]
    res = _delete_students(ids, cascade)
    res["deleted"] = [student_id]
    return res


def _delete_students(ids: list, cascade: bool) -> dict:
    ids = [i for i in ids if i is not None]
    if not ids:
        return {"deleted": [], "submissions_deleted": 0, "submissions_unlinked": 0}
    o = _owner()
    own_sub = " AND owner_id=?" if o is not None else ""
    own_stu = " AND owner_id=?" if o is not None else ""
    with _LOCK:
        c = _conn()
        marks = ",".join("?" * len(ids))
        sub_count = c.execute(
            f"SELECT COUNT(*) FROM submissions WHERE student_id IN ({marks}){own_sub}",
            ids + ([o] if o is not None else [])).fetchone()[0]
        sub_ids: list = []
        if cascade:
            sub_ids = [r["id"] for r in c.execute(
                f"SELECT id FROM submissions WHERE student_id IN ({marks}){own_sub}",
                ids + ([o] if o is not None else []))]
            # Capture the files each submission references BEFORE deleting it.
            own_files = {sid: _referenced_file_names("WHERE id=?", (sid,))
                         for sid in sub_ids}
            # Delete the submissions first (analyses are removed explicitly —
            # the live DB predates the FK ON DELETE CASCADE definition).
            for sid in sub_ids:
                c.execute("DELETE FROM analyses WHERE submission_id=?", (sid,))
                c.execute("DELETE FROM submissions WHERE id=?", (sid,))
        else:
            own_files = {}
        c.execute(f"DELETE FROM students WHERE id IN ({marks}){own_stu}",
                  ids + ([o] if o is not None else []))
        c.commit()
    if cascade:
        for sid in sub_ids:
            _remove_orphaned_files(own_files[sid], also_assignments=True)
        return {"deleted": ids, "submissions_deleted": len(sub_ids),
                "submissions_unlinked": 0}
    return {"deleted": ids, "submissions_deleted": 0,
            "submissions_unlinked": sub_count}


def count_students_classroom_prefix(prefix: str) -> list[dict]:
    """Students whose classroom starts with `prefix` (prefix match, e.g. '25/26').

    Returns the matching students with their submission counts, so the caller
    can preview a purge before doing it.
    """
    prefix = (prefix or "").strip()
    if not prefix:
        return []
    o = _owner()
    own = " AND s.owner_id=?" if o is not None else ""
    with _LOCK:
        rows = _conn().execute(
            "SELECT s.id, s.name, s.classroom, "
            "(SELECT COUNT(*) FROM submissions sub WHERE sub.student_id=s.id) AS submissions "
            f"FROM students s WHERE s.classroom LIKE ? ESCAPE '\\'{own} "
            "ORDER BY COALESCE(s.classroom,'') COLLATE NOCASE, s.name COLLATE NOCASE",
            (prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",)
            + ((o,) if o is not None else ()),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_students_classroom_prefix(prefix: str, cascade: bool = False) -> dict:
    """Delete all students whose classroom starts with `prefix` (prefix match,
    e.g. '25/26'), scoped to the caller. With `cascade=True` their submissions
    and analyses are removed too; otherwise submissions keep their analyses
    but lose the student link (ON DELETE SET NULL).

    Returns {"deleted": ids, "submissions_deleted": N, "submissions_unlinked": M}.
    """
    prefix = (prefix or "").strip()
    if not prefix:
        raise ValueError("classroom prefix required")
    esc = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    o = _owner()
    own = " AND owner_id=?" if o is not None else ""
    with _LOCK:
        c = _conn()
        ids = [r["id"] for r in c.execute(
            f"SELECT id FROM students WHERE classroom LIKE ? ESCAPE '\\'{own}",
            (esc,) + ((o,) if o is not None else ()))]
        if not ids:
            return {"deleted": [], "submissions_deleted": 0, "submissions_unlinked": 0}
    return _delete_students(ids, cascade)


def students_as_rows() -> list[dict]:
    """Flat rows for CSV export/import (scoped to the caller)."""
    o = _owner()
    own = " WHERE owner_id=?" if o is not None else ""
    with _LOCK:
        rows = _conn().execute(
            f"SELECT id, name, classroom, created_at FROM students{own} "
            "ORDER BY id", (o,) if o is not None else ()).fetchall()
    return [dict(r) for r in rows]


def upsert_student_csv(*, name: str, classroom: str,
                       student_id: int | None = None) -> int:
    """Import path: update the student with `student_id` if it exists (and
    belongs to the caller), else create it for the caller.
    `name` required; `classroom` optional."""
    name = (name or "").strip()
    classroom = (classroom or "").strip()
    if not name:
        raise ValueError("student name required")
    o = _owner()
    with _LOCK:
        c = _conn()
        if student_id:
            q = "SELECT id FROM students WHERE id=?"
            a = [student_id]
            if o is not None:
                q += " AND owner_id=?"
                a.append(o)
            row = c.execute(q, a).fetchone()
            if row:
                q2 = "UPDATE students SET name=?, classroom=? WHERE id=?"
                a2 = [name, classroom or None, student_id]
                if o is not None:
                    q2 += " AND owner_id=?"
                    a2.append(o)
                c.execute(q2, a2)
                c.commit()
                return int(student_id)
        cur = c.execute(
            "INSERT INTO students (name, classroom, created_at, owner_id) VALUES (?,?,?,?)",
            (name, classroom or None, now_iso(), o))
        c.commit()
        return cur.lastrowid


# ---------------------------------------------------------------- assignments
ASSIGNMENT_LIST_COLS = ("instruction_photo_names", "document_pdf_page_names",
                  "document_photo_names", "eval_notes_pdf_page_names",
                  "eval_notes_photo_names")


def _assignment_dict(row) -> dict:
    d = dict(row)
    for col in ASSIGNMENT_LIST_COLS:
        if d.get(col):
            try:
                d[col] = json.loads(d[col])
            except Exception:
                d[col] = []
    return d


def create_assignment(*, name: str, description: str = "",
                target_level: str | None = None,
                skill: str | None = None,
                kind: str | None = None,
                instruction: str = "",
                instruction_pdf_name: str | None = None,
                instruction_photo_names: list | None = None,
                document_text: str = "",
                document_pdf_name: str | None = None,
                document_pdf_page_names: list | None = None,
                document_photo_names: list | None = None,
                document_audio_name: str | None = None,
                eval_notes: str = "",
                eval_notes_pdf_name: str | None = None,
                eval_notes_pdf_page_names: list | None = None,
                eval_notes_photo_names: list | None = None,
                owner: int | None = None) -> int:
    with _LOCK:
        c = _conn()
        cur = c.execute(
            "INSERT INTO assignments (name, description, target_level, skill, kind, instruction, "
            "instruction_pdf_name, instruction_photo_names, document_text, "
            "document_pdf_name, document_pdf_page_names, document_photo_names, "
            "document_audio_name, eval_notes, eval_notes_pdf_name, "
            "eval_notes_pdf_page_names, eval_notes_photo_names, created_at, owner_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (name, description or None, target_level, skill, kind, instruction or None,
             instruction_pdf_name,
             json.dumps(instruction_photo_names) if instruction_photo_names else None,
             document_text or None, document_pdf_name,
             json.dumps(document_pdf_page_names) if document_pdf_page_names else None,
             json.dumps(document_photo_names) if document_photo_names else None,
             document_audio_name, eval_notes or None,
             eval_notes_pdf_name,
             json.dumps(eval_notes_pdf_page_names) if eval_notes_pdf_page_names else None,
             json.dumps(eval_notes_photo_names) if eval_notes_photo_names else None,
             now_iso(), owner if owner is not None else _owner()),
        )
        c.commit()
        _media_map_bump()
        return cur.lastrowid


def get_assignment(assignment_id: int) -> dict | None:
    where, args = _scoped("assignments")
    q = "SELECT * FROM assignments WHERE id=?"
    a: list = [assignment_id]
    if where:
        q += f" AND {where}"
        a += args
    with _LOCK:
        row = _conn().execute(q, a).fetchone()
    return _assignment_dict(row) if row else None


def list_assignments() -> list[dict]:
    where, args = _scoped("assignments", "t")
    q = ("SELECT t.*, (SELECT COUNT(*) FROM submissions sub "
         + (f"WHERE sub.assignment_id=t.id AND {where.replace('t.', 'sub.')}"
            if where else "WHERE sub.assignment_id=t.id")
         + ") AS submission_count FROM assignments t")
    if where:
        q += f" WHERE {where}"
    q += " ORDER BY t.id DESC"
    with _LOCK:
        rows = _conn().execute(q, args * (2 if where else 1)).fetchall()
    return [_assignment_dict(r) for r in rows]


def stats_for_assignment(assignment_id: int) -> dict | None:
    """Aggregate the evaluations made on one assignment.

    An "evaluation" is one analysis row linked (via its submission) to the
    assignment, with a usable result: a CEFR-levelable overall_level OR a
    filled attestation matrix. Skeletons (no levels anywhere) are counted in
    `evaluations_requested` but excluded from every statistic.

    Returns {assignment_id, evaluations, evaluations_requested,
             rubrics[{id,name}], levels{A1..C2:'' counts, global},
             by_class: [{classroom, students[], levels_counts{},
             overall{level counts + mean/median/sigma/min/max/n on the
             /120 point scale}, criterion{<name>: same shape per criterion}}]}
    or None when the assignment does not exist.
    """
    import statistics
    from .rubrics import CEFR_ORDER, LEVEL_POINTS, normalize_cefr, compute_attestation

    if not get_assignment(assignment_id):
        return None
    o = _owner()
    own = " AND s.owner_id=?" if o is not None else ""
    q = ("SELECT a.id, a.rubric_id, a.overall_level, a.matrix_json, a.feedback, "
         "a.ai_at, s.student_id, st.name AS student_name, st.classroom "
         "FROM analyses a "
         "JOIN submissions s ON s.id=a.submission_id "
         "LEFT JOIN students st ON st.id=s.student_id "
         f"WHERE s.assignment_id=?{own}")
    with _LOCK:
        rows = [dict(r) for r in _conn().execute(
            q, (assignment_id,) + ((o,) if o is not None else ())).fetchall()]

    requested = len(rows)
    rubrics_seen: dict[str, str] = {}
    usable = []
    for r in rows:
        r["levels"] = {}
        r["crit_levels"] = {}
        try:
            mapping = (json.loads(r["matrix_json"]) or {}).get("rubric_mapping", []) \
                if r.get("matrix_json") else []
        except Exception:
            mapping = []
        for m in mapping:
            name = (m or {}).get("criterion")
            if name:
                r["crit_levels"][name] = normalize_cefr(
                    (m or {}).get("suggested_level"))
        r["overall_norm"] = normalize_cefr(r.get("overall_level"))
        has_level = r["overall_norm"] is not None or any(r["crit_levels"].values())
        if has_level:
            usable.append(r)
            if r.get("rubric_id") and r["rubric_id"] not in rubrics_seen:
                rub = get_rubric(r["rubric_id"])
                rubrics_seen[r["rubric_id"]] = (rub or {}).get("name", r["rubric_id"])

    def moments(vals):
        out = {}
        if not vals:
            return out
        out["n"] = len(vals)
        out["mean"] = round(statistics.mean(vals), 2)
        out["median"] = statistics.median(vals)
        out["sigma"] = round(statistics.pstdev(vals), 2) if len(vals) > 1 else 0.0
        out["min"] = min(vals)
        out["max"] = max(vals)
        return out

    def level_counts(levels):
        c = {lv: 0 for lv in CEFR_ORDER}
        c[""] = 0
        for lv in levels:
            c[lv or ""] += 1
        return c

    classes: dict[str, dict] = {}
    rub_crits: dict[str, list] = {}
    for r in usable:
        if r.get("rubric_id"):
            rub = get_rubric(r["rubric_id"])
            if rub and r["rubric_id"] not in rub_crits:
                rub_crits[r["rubric_id"]] = [
                    c["name"] for c in rub.get("criteria", [])]
    for r in usable:
        classroom = (r.get("classroom") or "").strip() or "—"
        cl = classes.setdefault(classroom, {
            "classroom": classroom, "students": [], "levels": [],
            "criterion": {}, "overall": []})
        name = r.get("student_name") or "—"
        if name not in cl["students"]:
            cl["students"].append(name)
        # global: overall_level if set, else the recomputed attestation level
        overall = r["overall_norm"]
        rub = get_rubric(r["rubric_id"]) if r.get("rubric_id") else None
        if not overall and rub and rub.get("attestation"):
            att = compute_attestation(rub, [
                {"criterion": c, "suggested_level": lv}
                for c, lv in r["crit_levels"].items()])
            if att:
                overall = att.get("attestation")
        if overall:
            cl["overall"].append(overall)
            cl["levels"].append(LEVEL_POINTS.get(overall, 0))
        # per criterion: only criteria that exist on that rubric
        crits = rub_crits.get(r.get("rubric_id") or "", [])
        for cname in crits:
            lv = r["crit_levels"].get(cname)
            d = cl["criterion"].setdefault(cname, {"level": [], "score": []})
            d["level"].append(lv or "")
            if lv:
                d["score"].append(LEVEL_POINTS[lv])

    by_class = []
    for cl in sorted(classes.values(), key=lambda c: c["classroom"]):
        by_class.append({
            "classroom": cl["classroom"],
            "students": sorted(cl["students"]),
            "levels_counts": level_counts(cl["overall"]),
            "overall": dict(level_counts(cl["overall"]), **moments(cl["levels"])),
            "criterion": {
                name: dict(level_counts(d["level"]), **moments(d["score"]))
                for name, d in sorted(cl["criterion"].items())},
        })

    # Per-evaluation detail for the AI class insight (job kind "stats_ai"):
    # the per-criterion levels + the AI feedback summary of each evaluation.
    detail = []
    for r in usable:
        try:
            fb = json.loads(r.get("feedback") or "null")
        except Exception:
            fb = None
        detail.append({
            "student": (r.get("student_name") or "—"),
            "classroom": (r.get("classroom") or "").strip() or "—",
            "overall": r["overall_norm"],
            "criteria": r["crit_levels"],
            "feedback": fb if isinstance(fb, dict) else None,
            "ai_at": r.get("ai_at"),
        })

    return {
        "assignment_id": assignment_id,
        "evaluations": len(usable),
        "evaluations_requested": requested,
        "rubrics": [{"id": k, "name": v} for k, v in rubrics_seen.items()],
        "levels": level_counts([r["overall_norm"] for r in usable]),
        "by_class": by_class,
        "evaluations_detail": detail,
    }


def stats_for_student(student_id: int) -> dict | None:
    """Chronological level evolution of ONE student, for the per-student
    "Stats" time chart (2026-10-12).

    Every submission of the student (linked or not — a student deletion keeps
    submissions via FK ON DELETE SET NULL) with at least one usable level
    (CEFR-levelable overall_level OR a filled criterion in the matrix) is one
    point in time. The level is resolved exactly like in
    `stats_for_assignment`: stored overall_level first, else the recomputed
    attestation from the matrix.

    Returns {student: {id, name, classroom}, evaluations (usable),
             total_submissions,
             points: [{id, date, title, level, points}],
             by_type: {"comprehension": {"written": [points], "oral": …},
                        "expression": …, "untyped": …}}
    or None when the student does not exist.
    """
    from .rubrics import CEFR_ORDER, LEVEL_POINTS, normalize_cefr, compute_attestation

    st = get_student(student_id)
    if not st:
        return None
    o = _owner()
    own = " AND s.owner_id=?" if o is not None else ""
    q = ("SELECT s.id, s.kind, s.title, s.created_at, s.assignment_id, "
         "a.id AS analysis_id, a.rubric_id, a.overall_level, a.matrix_json "
         "FROM submissions s "
         "LEFT JOIN analyses a ON a.submission_id=s.id "
         f"WHERE s.student_id=?{own} ORDER BY s.created_at ASC, s.id ASC")
    with _LOCK:
        rows = [dict(r) for r in _conn().execute(
            q, (student_id,) + ((o,) if o is not None else ())).fetchall()]

    def resolve_level(r) -> str | None:
        lv = normalize_cefr(r.get("overall_level"))
        if lv:
            return lv
        mapping = []
        try:
            if r.get("matrix_json"):
                mapping = (json.loads(r["matrix_json"]) or {}).get("rubric_mapping", [])
        except Exception:
            mapping = []
        crit_levels = {}
        for m in mapping:
            name = (m or {}).get("criterion")
            if name:
                crit_levels[name] = normalize_cefr((m or {}).get("suggested_level"))
        if any(crit_levels.values()) and r.get("rubric_id"):
            rub = get_rubric(r["rubric_id"])
            if rub and rub.get("attestation"):
                att = compute_attestation(rub, [
                    {"criterion": c, "suggested_level": lv2}
                    for c, lv2 in crit_levels.items()])
                if att:
                    return att.get("attestation") or None
        return None

    def bucket_of(r) -> str:
        """comprehension | expression | untyped, from the linked assignment."""
        if r.get("assignment_id"):
            a = get_assignment(r["assignment_id"])
            if a and (a.get("skill") or "").strip():
                return (a.get("skill") or "").strip()
        return "untyped"

    def code_of(skill: str, kind: str) -> str:
        """Short type code shown next to each chart point: L = listening
        (comprehension oral), R = reading (comprehension written),
        S = speaking (expression oral), W = writing (expression written).
        Untyped assignments (no skill) -> ''."""
        if skill == "comprehension":
            return "L" if kind == "oral" else "R"
        if skill == "expression":
            return "S" if kind == "oral" else "W"
        return ""

    points = []
    by_type: dict[str, dict] = {}
    total = len(rows)
    for r in rows:
        lv = resolve_level(r)
        if not lv:
            continue
        b = bucket_of(r)
        kind = (r.get("kind") or "").strip() or "unknown"
        rec = {"id": r["id"], "date": r["created_at"], "title": r["title"] or "",
               "level": lv, "points": LEVEL_POINTS.get(lv, 0),
               "code": code_of(b, kind)}
        points.append(rec)
        by_type.setdefault(b, {}).setdefault(kind, []).append(rec)

    return {
        "student": {"id": st["id"], "name": st.get("name"),
                    "classroom": st.get("classroom") or ""},
        "total_submissions": total,
        "evaluations": len(points),
        "levels": {lv: 0 for lv in CEFR_ORDER} | {
            lv: sum(1 for p in points if p["level"] == lv) for lv in CEFR_ORDER},
        "points": points,
        "by_type": {k: {k2: v2 for k2, v2 in v.items()}
                    for k, v in by_type.items()},
    }


def update_assignment(assignment_id: int, **fields) -> int:
    """Update editable assignment fields: text columns (name, description,
    target_level, instruction, document_text, eval_notes) AND file columns
    (instruction_pdf_name, instruction_photo_names, document_pdf_name,
    document_pdf_page_names, document_photo_names, document_audio_name,
    eval_notes_pdf_name, eval_notes_pdf_page_names).

    Semantics: a key NOT in fields is left untouched; a key present with a
    value is written; a key present with None forces the column to NULL
    (i.e. "remove this file"). After the update, media files that the assignment
    no longer references are deleted UNLESS a surviving submission or assignment
    still references them (shared files survive). Returns the number of
    orphaned files removed.
    """
    text_allowed = {"name", "description", "target_level", "skill", "kind",
                    "instruction",
                    "document_text", "eval_notes"}
    file_allowed = {"instruction_pdf_name", "document_pdf_name",
                    "document_audio_name", "eval_notes_pdf_name"}
    list_allowed = set(ASSIGNMENT_LIST_COLS)
    allowed = text_allowed | file_allowed | list_allowed
    sets: list = []
    args: list = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if v is None:
            sets.append(f"{k}= NULL")
        elif k in list_allowed:
            sets.append(f"{k}= ?")
            args.append(json.dumps(v))
        else:
            sets.append(f"{k}= ?")
            args.append(v)
    if not sets:
        return 0
    old = get_assignment(assignment_id)
    old_files = _assignment_file_names(old) if old else set()
    where, wargs = _scoped("assignments")
    q = f"UPDATE assignments SET {', '.join(sets)} WHERE id=?"
    a2: list = list(args)
    a2.append(assignment_id)
    if where:
        q += f" AND {where}"
        a2 += wargs
    with _LOCK:
        c = _conn()
        c.execute(q, a2)
        c.commit()
        _media_map_bump()
    new = get_assignment(assignment_id)
    new_files = _assignment_file_names(new) if new else set()
    return _remove_orphaned_files(old_files - new_files, also_assignments=True)


def _assignment_file_names(assignment: dict) -> set:
    """Media filenames referenced by one assignment (list columns + single names)."""
    out: set = set()
    for col in ASSIGNMENT_LIST_COLS:
        v = assignment.get(col)
        if isinstance(v, list):
            out.update(x for x in v if isinstance(x, str))
    for col in ("instruction_pdf_name", "document_pdf_name",
                "document_audio_name", "eval_notes_pdf_name"):
        v = assignment.get(col)
        if isinstance(v, str) and v:
            out.add(v)
    return out


def delete_assignment(assignment_id: int) -> dict:
    """Delete one assignment of the caller. Linked submissions keep their
    context snapshot and lose the link (FK ON DELETE SET NULL); assignment
    media files are removed when no surviving submission or assignment still
    references them."""
    where, wargs = _scoped("assignments")
    q = "DELETE FROM assignments WHERE id=?"
    a2: list = [assignment_id]
    if where:
        q += f" AND {where}"
        a2 += wargs
    with _LOCK:
        c = _conn()
        linked = c.execute(
            "SELECT COUNT(*) FROM submissions WHERE assignment_id=?"
            + (f" AND {where.replace('assignments', 'submissions')}"
               if where else ""),
            ((assignment_id,) + tuple(wargs))).fetchone()[0]
        assignment = _assignment_dict(c.execute(
            "SELECT * FROM assignments WHERE id=?"
            + (f" AND {where}" if where else ""),
            ((assignment_id,) + tuple(wargs))).fetchone())
        c.execute(q, a2)
        c.commit()
        _media_map_bump()
    own = _assignment_file_names(assignment) if assignment else set()
    removed = _remove_orphaned_files(own)
    return {"deleted": assignment_id, "submissions_unlinked": linked,
            "files_removed": removed}


def assignments_referencing_file(filename: str) -> int:
    """Count assignments referencing a media filename (list columns or single-name
    columns). Used to avoid deleting a file an assignment still points at."""
    with _LOCK:
        c = _conn()
        rows = c.execute("SELECT * FROM assignments").fetchall()
    n = 0
    for row in rows:
        d = _assignment_dict(row)
        in_lists = any(filename in (d.get(col) or []) for col in ASSIGNMENT_LIST_COLS)
        in_names = any(d.get(col) == filename for col in (
            "instruction_pdf_name", "document_pdf_name",
            "document_audio_name", "eval_notes_pdf_name"))
        if in_lists or in_names:
            n += 1
    return n


# ---------------------------------------------------------------- submissions
def create_submission(*, kind: str, source_type: str, payload_path: str,
                      title: str = "", student_id: int | None = None,
                      assignment_id: int | None = None,
                      language: str = "", duration_s: float | None = None,
                      target_level: str | None = None,
                      payload_meta: dict | None = None,
                      context: dict | None = None,
                      eval_notes: dict | None = None,
                      accommodations: str | None = None) -> int:
    with _LOCK:
        c = _conn()
        cur = c.execute(
            "INSERT INTO submissions (student_id, assignment_id, kind, source_type, payload_path, title, "
            "language, duration_s, target_level, payload_meta_json, context_json, "
            "eval_notes_json, accommodations, created_at, owner_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (student_id, assignment_id, kind, source_type, payload_path, title, language,
             duration_s, target_level,
             json.dumps(payload_meta, ensure_ascii=False) if payload_meta else None,
             json.dumps(context, ensure_ascii=False) if context else None,
             json.dumps(eval_notes, ensure_ascii=False) if eval_notes else None,
             accommodations or None,
             now_iso(), _owner()),
        )
        c.commit()
        _media_map_bump()
        return cur.lastrowid


def get_submission(sub_id: int) -> dict | None:
    where, wargs = _scoped("submissions", "sub")
    q = ("SELECT sub.*, st.name AS student_name, t.name AS assignment_name "
         "FROM submissions sub "
         "LEFT JOIN students st ON st.id=sub.student_id "
         "LEFT JOIN assignments t ON t.id=sub.assignment_id WHERE sub.id=?")
    a: list = [sub_id]
    if where:
        q += f" AND {where}"
        a += wargs
    with _LOCK:
        row = _conn().execute(q, a).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("payload_meta_json"):
        try:
            d["payload_meta"] = json.loads(d["payload_meta_json"])
        except Exception:
            d["payload_meta"] = None
    d.pop("payload_meta_json", None)
    if d.get("context_json"):
        try:
            d["context"] = json.loads(d["context_json"])
        except Exception:
            d["context"] = None
    d.pop("context_json", None)
    if d.get("eval_notes_json"):
        try:
            d["eval_notes"] = json.loads(d["eval_notes_json"])
        except Exception:
            d["eval_notes"] = None
    d.pop("eval_notes_json", None)
    if d.get("ocr_json"):
        try:
            d["ocr"] = json.loads(d["ocr_json"])
        except Exception:
            d["ocr"] = None
    d.pop("ocr_json", None)
    return d


def list_submissions(student_id: int | None = None, limit: int = 200,
                     classroom_prefix: str = "", title: str = "",
                     assignment_id: int | None = None) -> list[dict]:
    q = ("SELECT sub.id, sub.kind, sub.source_type, sub.title, sub.language, sub.duration_s, "
         "sub.created_at, sub.target_level, st.name AS student_name, st.classroom, "
         "t.name AS assignment_name, "
         "a.id AS analysis_id, a.overall_level, a.status, r.name AS rubric_name, "
         "a.validated_at, a.note20_json, a.ai_mode, "
         "a.ai_matrix_json IS NOT NULL AS ai_has "
         "FROM submissions sub "
         "LEFT JOIN students st ON st.id=sub.student_id "
         "LEFT JOIN assignments t ON t.id=sub.assignment_id "
         "LEFT JOIN analyses a ON a.submission_id=sub.id "
         "LEFT JOIN rubrics r ON r.id=a.rubric_id ")
    where = []
    args: list = []
    ow, owargs = _scoped("submissions", "sub")
    if ow:
        where.append(ow)
        args += owargs
    if student_id is not None:
        where.append("sub.student_id=?")
        args.append(student_id)
    if assignment_id:
        where.append("sub.assignment_id=?")
        args.append(assignment_id)
    pfx = (classroom_prefix or "").strip()
    if pfx:
        where.append("st.classroom LIKE ? ESCAPE '\\'")
        args.append(pfx.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    tl = (title or "").strip()
    if tl:
        where.append("sub.title LIKE ? ESCAPE '\\'")
        args.append("%" + tl.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if where:
        q += "WHERE " + " AND ".join(where) + " "
    q += "ORDER BY sub.id DESC LIMIT ?"
    args.append(limit)
    with _LOCK:
        rows = _conn().execute(q, args).fetchall()
    return [dict(r) for r in rows]


def delete_submission(sub_id: int) -> None:
    """Delete one submission of the caller, its analyses, and — when no other
    surviving submission or assignment still references them — the stored
    media files."""
    o = _owner()
    own = " AND owner_id=?" if o is not None else ""
    args = (sub_id,) + ((o,) if o is not None else ())
    # capture the files BEFORE deleting (the rows go away below)
    own_files = _referenced_file_names("WHERE id=?" + own, args)
    with _LOCK:
        c = _conn()
        c.execute(f"DELETE FROM passage_links WHERE analysis_id IN "
                  f"(SELECT id FROM analyses WHERE submission_id=?{own})", args)
        c.execute(f"DELETE FROM analyses WHERE submission_id=?{own}", args)
        c.execute(f"DELETE FROM annotations WHERE submission_id=?{own}", args)
        c.execute(f"DELETE FROM submissions WHERE id=?{own}", args)
        c.commit()
        _media_map_bump()
    _remove_orphaned_files(own_files, also_assignments=True)


def set_submission_ocr(sub_id: int, ocr: dict) -> None:
    """Persist the hybrid OCR result (per-page line boxes + text) of a written
    submission's copy photos. ocr_json = {generated_at, engine, language,
    pages: [{name, w, h, lines: [{i, y0, y1, x0, x1, text}]}]}."""
    where, wargs = _scoped("submissions")
    q = "UPDATE submissions SET ocr_json=? WHERE id=?"
    a2: list = [json.dumps(ocr, ensure_ascii=False), sub_id]
    if where:
        q += f" AND {where}"
        a2 += wargs
    with _LOCK:
        c = _conn()
        c.execute(q, a2)
        c.commit()


# ---------------------------------------------------------------- media ownership
# (2026-10-14) /api/files serves student copies + assignment material from
# data/uploads/. Filenames are random uuid4s (unguessable), but ownership must
# still be ENFORCED, not just hidden: a leaked URL (browser cache, logs, a
# shared link) must not let another teacher fetch a student's work or another
# teacher's assignment. media_owner_map() maps filename -> owner_id for every
# file referenced by a submission or an assignment; /api/files 404s any file
# whose owner != the caller. The map is cached 30 s and invalidated on
# submission/assignment create/delete.
_MEDIA_MAP_TTL = 30.0
_media_map = None  # (built_at, {filename: owner_id})


def _media_map_bump() -> None:
    global _media_map
    _media_map = None


def media_owner_map() -> dict:
    """{filename: owner_id} for every media referenced by a submission
    (payload_meta/context json) or an assignment (list + name columns).
    owner_id is None for system/unscoped builds (jobs worker context)."""
    global _media_map
    import time as _time
    now = _time.monotonic()
    if _media_map and now - _media_map[0] < _MEDIA_MAP_TTL:
        return _media_map[1]
    import json as _json
    out: dict = {}
    for row in _conn().execute(
            "SELECT payload_meta_json, context_json, eval_notes_json, owner_id "
            "FROM submissions"):
        owner = row[3]
        for col in (row[0] or "", row[1] or "", row[2] or ""):
            col = (col or "").strip()
            if not col:
                continue
            try:
                d = _json.loads(col)
            except _json.JSONDecodeError:
                continue
            if not isinstance(d, dict):
                continue
            for v in d.values():
                if isinstance(v, str) and v:
                    out.setdefault(v, owner)
                elif isinstance(v, (list, tuple)):
                    for x in v:
                        if isinstance(x, str) and x:
                            out.setdefault(x, owner)
        # eval_notes may nest {pdf_name, photo_names} explicitly
        en = row[2] or ""
        try:
            en = _json.loads(en.strip()) if en.strip() else {}
        except _json.JSONDecodeError:
            en = {}
        if isinstance(en, dict):
            if isinstance(en.get("pdf_name"), str):
                out.setdefault(en["pdf_name"], owner)
            for x in (en.get("photo_names") or []):
                if isinstance(x, str) and x:
                    out.setdefault(x, owner)
    for row in _conn().execute("SELECT * FROM assignments"):
        d = _assignment_dict(row)
        owner = d.get("owner_id")
        for name in _assignment_file_names(d):
            out.setdefault(name, owner)
    _media_map = (now, out)
    return out


def _referenced_file_names(where_sql: str, args: tuple = ()) -> set:
    """Collect every string value (filename) found in the
    payload_meta_json / context_json of the matching submissions."""
    import json as _json
    out: set = set()
    with _LOCK:
        c = _conn()
        for row in c.execute(
                "SELECT payload_meta_json, context_json FROM submissions " + where_sql, args):
            for col in (row[0] or "", row[1] or ""):
                col = (col or "").strip()
                if not col:
                    continue
                try:
                    d = _json.loads(col)
                except _json.JSONDecodeError:
                    continue
                if not isinstance(d, dict):
                    continue
                for v in d.values():
                    if isinstance(v, str):
                        out.add(v)
                    elif isinstance(v, (list, tuple)):
                        out.update(x for x in v if isinstance(x, str))
    return out


def _remove_orphaned_files(own: set, also_assignments: bool = False) -> int:
    """Remove media files referenced by a deleted submission from
    data/uploads/ unless a surviving submission OR surviving assignment still
    references the same filename (shared context files survive). Audio
    files (aud-*) are not named in the JSON (their path is not persisted),
    so they are never touched by this cleanup — safe behaviour.
    """
    from pathlib import Path as _P
    upload_dir = _P(__file__).resolve().parent.parent / "data" / "uploads"
    if not upload_dir.is_dir() or not own:
        return 0
    used_by_others = _referenced_file_names("WHERE 1=1", ())  # every surviving submission
    removed = 0
    for name in own:
        if name in used_by_others:
            continue
        if also_assignments and assignments_referencing_file(name):
            continue
        f = upload_dir / name
        if f.is_file():
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    return removed


# ---------------------------------------------------------------- analyses
def create_analysis(submission_id: int, rubric_id: str | None, status: str = "processing",
                    owner: int | None = None) -> int:
    with _LOCK:
        c = _conn()
        cur = c.execute(
            "INSERT INTO analyses (submission_id, rubric_id, status, created_at, owner_id) "
            "VALUES (?,?,?,?,?)",
            (submission_id, rubric_id, status, now_iso(),
             owner if owner is not None else _owner()),
        )
        c.commit()
        return cur.lastrowid


# Sentinel passed to update_analysis() to force a column to NULL
_CLEAR = object()


def update_analysis(analysis_id: int, *, raw_markdown: str | None = None,
                    overall_level: str | None = None, matrix_json: str | None = None,
                    feedback: str | None = None, fluency_json: str | None = None,
                    transcript_json: str | None = None,
                    transcript_correction_json: str | None = None,
                    transcript_mode: str | None = None,
                    status: str | None = None,
                    error: str | None = None,
                    note20_json: str | None = None,
                    validated_at: str | None = None,
                    ai_matrix_json: str | None = None,
                    ai_mode: str | None = None,
                    ai_at: str | None = None) -> None:
    sets, args = [], []
    for col, val in [("raw_markdown", raw_markdown), ("overall_level", overall_level),
                     ("matrix_json", matrix_json), ("feedback", feedback),
                     ("fluency_json", fluency_json), ("transcript_json", transcript_json),
                     ("transcript_correction_json", transcript_correction_json),
                     ("transcript_mode", transcript_mode),
                     ("status", status), ("error", error),
                     ("note20_json", note20_json), ("validated_at", validated_at),
                     ("ai_matrix_json", ai_matrix_json),
                     ("ai_mode", ai_mode), ("ai_at", ai_at)]:
        if val is _CLEAR:
            sets.append(f"{col}= NULL")
        elif val is not None:
            sets.append(f"{col}= ?")
            args.append(val)
    if not sets:
        return
    where, wargs = _scoped("analyses")
    q = f"UPDATE analyses SET {', '.join(sets)} WHERE id=?"
    a2: list = list(args)
    a2.append(analysis_id)
    if where:
        q += f" AND {where}"
        a2 += wargs
    with _LOCK:
        c = _conn()
        c.execute(q, a2)
        c.commit()


def get_analysis(analysis_id: int) -> dict | None:
    where, wargs = _scoped("analyses", "a")
    q = ("SELECT a.*, sub.kind, sub.source_type, r.name AS rubric_name, "
         "st.name AS student_name, sub.id AS submission_id, sub.title "
         "FROM analyses a "
         "JOIN submissions sub ON sub.id=a.submission_id "
         "LEFT JOIN rubrics r ON r.id=a.rubric_id "
         "LEFT JOIN students st ON st.id=sub.student_id "
         "WHERE a.id=?")
    a: list = [analysis_id]
    if where:
        q += f" AND {where}"
        a += wargs
    with _LOCK:
        row = _conn().execute(q, a).fetchone()
    return dict(row) if row else None


def latest_analysis_for_submission(submission_id: int) -> dict | None:
    where, wargs = _scoped("analyses", "a")
    q = ("SELECT a.* FROM analyses a WHERE a.submission_id=?"
         + (f" AND {where}" if where else "")
         + " ORDER BY a.id DESC LIMIT 1")
    with _LOCK:
        row = _conn().execute(q, [submission_id] + wargs).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------- annotations
def _annotation_dict(row) -> dict:
    d = dict(row)
    if d.get("span_json"):
        try:
            d["span"] = json.loads(d["span_json"])
        except Exception:
            d["span"] = None
    d.pop("span_json", None)
    return d


def create_annotation(*, submission_id: int, kind: str, span: dict,
                      quote: str = "", sticker: str | None = None,
                      level: str | None = None, note: str | None = None,
                      page_idx: int | None = None,
                      analysis_id: int | None = None) -> int:
    """Insert one teacher annotation (a highlighted passage on the copy or the
    transcript). `span` is the machine-readable range:
      written: {"page": 0, "start_line": 3, "start_char": 10,
                     "end_line": 5, "end_char": 42}   (line idxs + char offsets
                                                         within that line's text)
      oral:    {"start_s": 12.4, "end_s": 18.9}
    Both are clamped/validated by the API layer before this call."""
    with _LOCK:
        c = _conn()
        cur = c.execute(
            "INSERT INTO annotations (submission_id, analysis_id, kind, page_idx, "
            "span_json, quote, sticker, level, note, created_at, owner_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (submission_id, analysis_id, kind, page_idx,
             json.dumps(span, ensure_ascii=False), quote or None,
             sticker or None, level or None, note or None, now_iso(),
             _owner()),
        )
        c.commit()
        return cur.lastrowid


def get_annotation(annotation_id: int) -> dict | None:
    where, wargs = _scoped("annotations", "a")
    q = ("SELECT a.*, sub.kind AS sub_kind FROM annotations a "
         "JOIN submissions sub ON sub.id=a.submission_id WHERE a.id=?")
    a2: list = [annotation_id]
    if where:
        q += f" AND {where}"
        a2 += wargs
    with _LOCK:
        row = _conn().execute(q, a2).fetchone()
    return _annotation_dict(row) if row else None


def list_annotations(submission_id: int, analysis_id: int | None = None) -> list[dict]:
    where, wargs = _scoped("annotations", "a")
    q = "SELECT a.*, sub.kind AS sub_kind FROM annotations a " \
        "JOIN submissions sub ON sub.id=a.submission_id WHERE a.submission_id=?"
    args: list = [submission_id]
    if where:
        q += f" AND {where}"
        args += wargs
    if analysis_id is not None:
        q += " AND (a.analysis_id IS ? OR a.analysis_id IS NULL)"
        args.append(analysis_id)
    q += " ORDER BY " \
         "CASE WHEN sub.kind='oral' " \
         "  THEN CAST(json_extract(a.span_json,'$.start_s') AS REAL) " \
         "  ELSE a.page_idx*10000 + json_extract(a.span_json,'$.start_line')*100 " \
         "     + json_extract(a.span_json,'$.start_char') END, a.id"
    with _LOCK:
        rows = _conn().execute(q, args).fetchall()
    return [_annotation_dict(r) for r in rows]


def update_annotation(annotation_id: int, *, quote: str | None = None,
                      sticker: str | None = None, level: str | None = None,
                      note: str | None = None,
                      span: dict | None = None,
                      page_idx: int | None = None) -> dict | None:
    row = get_annotation(annotation_id)
    if not row:
        return None
    new_quote = row["quote"] if quote is None else quote
    new_sticker = row["sticker"] if sticker is None else sticker
    new_level = row["level"] if level is None else level
    new_note = row["note"] if note is None else note
    new_span = row.get("span") or {}
    if span is not None:
        new_span = span
    new_page = row["page_idx"] if page_idx is None else page_idx
    with _LOCK:
        c = _conn()
        c.execute(
            "UPDATE annotations SET span_json=?, quote=?, sticker=?, level=?, note=?, "
            "page_idx=?, updated_at=? WHERE id=?",
            (json.dumps(new_span, ensure_ascii=False), new_quote or None,
             new_sticker or None, new_level or None, new_note or None,
             new_page, now_iso(), annotation_id))
        c.commit()
    return get_annotation(annotation_id)


def delete_annotation(annotation_id: int) -> bool:
    where, wargs = _scoped("annotations")
    q = "DELETE FROM annotations WHERE id=?"
    a2: list = [annotation_id]
    if where:
        q += f" AND {where}"
        a2 += wargs
    with _LOCK:
        c = _conn()
        c.execute("DELETE FROM passage_links WHERE annotation_id=?", (annotation_id,))
        n = c.execute(q, a2).rowcount
        c.commit()
    return n > 0


def link_passage(analysis_id: int, annotation_id: int, criterion: str) -> int:
    """Link an annotated passage to a rubric criterion (for the criterion-by-
    criterion evaluation). Idempotent."""
    with _LOCK:
        c = _conn()
        existing = c.execute(
            "SELECT id FROM passage_links WHERE analysis_id=? AND annotation_id=? "
            "AND criterion=?", (analysis_id, annotation_id, criterion)).fetchone()
        if existing:
            return existing["id"]
        cur = c.execute(
            "INSERT INTO passage_links (analysis_id, annotation_id, criterion, created_at) "
            "VALUES (?,?,?,?)", (analysis_id, annotation_id, criterion, now_iso()))
        c.commit()
        return cur.lastrowid


def unlink_passage(analysis_id: int, annotation_id: int, criterion: str) -> bool:
    with _LOCK:
        c = _conn()
        n = c.execute(
            "DELETE FROM passage_links WHERE analysis_id=? AND annotation_id=? "
            "AND criterion=?", (analysis_id, annotation_id, criterion)).rowcount
        c.commit()
    return n > 0


def passage_links(analysis_id: int) -> list[dict]:
    """All criterion<->passage links for one analysis, each hydrated with the
    annotation's quote/sticker/level/span."""
    with _LOCK:
        rows = _conn().execute(
            "SELECT pl.*, a.quote, a.sticker, a.level, a.span_json, a.page_idx, "
            "a.note, sub.kind AS sub_kind "
            "FROM passage_links pl "
            "JOIN annotations a ON a.id=pl.annotation_id "
            "JOIN submissions sub ON sub.id=a.submission_id "
            "WHERE pl.analysis_id=? "
            "ORDER BY sub.kind, a.page_idx, a.id", (analysis_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("span_json"):
            try:
                d["span"] = json.loads(d["span_json"])
            except Exception:
                d["span"] = None
        d.pop("span_json", None)
        out.append(d)
    return out


def annotations_for_prompt(submission_id: int) -> list[dict]:
    """Annotations shaped for the LLM prompt: written passages carry the quoted
    text + estimated level; oral passages carry [mm:ss] time ranges + text."""
    out = []
    for a in list_annotations(submission_id):
        out.append({
            "id": a["id"],
            "kind": a.get("sub_kind") or a["kind"],
            "page": a.get("page_idx"),
            "quote": a.get("quote") or "",
            "sticker": a.get("sticker"),
            "level": a.get("level"),
            "note": a.get("note"),
            "span": a.get("span") or {},
        })
    return out


# ---------------------------------------------------------------- settings
def get_setting(key: str, default: str | None = None) -> str | None:
    with _LOCK:
        row = _conn().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    with _LOCK:
        c = _conn()
        c.execute("INSERT INTO settings (key,value) VALUES (?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        c.commit()


# ---------------------------------------------------------------- jobs
def update_submission(sub_id: int, *, payload_path: str | None = None,
                      source_type: str | None = None,
                      language: str | None = None,
                      duration_s: float | None = None,
                      target_level: str | None = None,
                      payload_meta: dict | None = None,
                      context: dict | None = None,
                      eval_notes: dict | None = None,
                      accommodations: str | None = None) -> None:
    """Fill in a placeholder submission created at request time (the job
    worker completes it once the long processing has run)."""
    sets, args = [], []
    for col, val in (("payload_path", payload_path), ("source_type", source_type),
                     ("language", language), ("duration_s", duration_s),
                     ("target_level", target_level),
                     ("payload_meta_json", json.dumps(payload_meta, ensure_ascii=False)
                      if payload_meta else None),
                     ("context_json", json.dumps(context, ensure_ascii=False)
                      if context else None),
                     ("eval_notes_json", json.dumps(eval_notes, ensure_ascii=False)
                      if eval_notes else None),
                     ("accommodations", accommodations)):
        if val is not None:
            sets.append(f"{col}= ?")
            args.append(val)
    if not sets:
        return
    args.append(sub_id)
    with _LOCK:
        c = _conn()
        c.execute(f"UPDATE submissions SET {', '.join(sets)} WHERE id=?", args)
        c.commit()
    _media_map_bump()


# ---------------------------------------------------------------- jobs
def create_job(kind: str, payload: dict,
               submission_id: int | None = None,
               analysis_id: int | None = None,
               owner: int | None = None) -> int:
    with _LOCK:
        c = _conn()
        cur = c.execute(
            "INSERT INTO jobs (kind,status,payload_json,submission_id,analysis_id,created_at,owner_id) "
            "VALUES (?,'queued',?,?,?, ?,?)",
            (kind, json.dumps(payload, ensure_ascii=False), submission_id,
             analysis_id, now_iso(),
             owner if owner is not None else _owner()),
        )
        c.commit()
        return cur.lastrowid


def job_claim_next() -> dict | None:
    """Atomically take the next queued job (oldest first) and mark it running."""
    with _LOCK:
        c = _conn()
        row = c.execute(
            "SELECT id FROM jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not row:
            return None
        c.execute("UPDATE jobs SET status='running', started_at=? WHERE id=?",
                  (now_iso(), row[0]))
        c.commit()
        return job_get(row[0])


def job_update(job_id: int, *, status: str | None = None,
               submission_id: int | None = None,
               analysis_id: int | None = None,
               error: str | None = None,
               cancel_flag: int | None = None,
               elapsed_s: float | None = None,
               phase: str | None = None,
               result: dict | None = None,
               finished: bool = False) -> None:
    sets, args = [], []
    for col, val in (("status", status), ("submission_id", submission_id),
                     ("analysis_id", analysis_id), ("error", error),
                     ("cancel_flag", cancel_flag), ("elapsed_s", elapsed_s),
                     ("phase", phase)):
        if val is not None:
            sets.append(f"{col}= ?")
            args.append(val)
    if result is not None:
        sets.append("result_json=?")
        args.append(json.dumps(result, ensure_ascii=False))
    if finished:
        sets.append("finished_at=?")
        args.append(now_iso())
    if not sets:
        return
    args.append(job_id)
    with _LOCK:
        c = _conn()
        c.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", args)
        c.commit()


def job_get(job_id: int) -> dict | None:
    where, wargs = _scoped("jobs")
    q = "SELECT * FROM jobs WHERE id=?"
    a2: list = [job_id]
    if where:
        q += f" AND {where}"
        a2 += wargs
    with _LOCK:
        row = _conn().execute(q, a2).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("payload_json"):
        try:
            d["payload"] = json.loads(d["payload_json"])
        except Exception:
            d["payload"] = None
    return d


def job_list(status: str = "", limit: int = 100) -> list[dict]:
    q = ("SELECT j.*, sub.title AS submission_title, sub.kind AS submission_kind, "
         "r.name AS rubric_name, st.name AS student_name "
         "FROM jobs j "
         "LEFT JOIN submissions sub ON sub.id=j.submission_id "
         "LEFT JOIN analyses a ON a.id=j.analysis_id "
         "LEFT JOIN rubrics r ON r.id=a.rubric_id "
         "LEFT JOIN students st ON st.id=sub.student_id")
    args: list = []
    conds: list = []
    ow, owargs = _scoped("jobs", "j")
    if ow:
        conds.append(ow)
        args += owargs
    if status:
        conds.append("j.status=?")
        args.append(status)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY j.id DESC LIMIT ?"
    args.append(limit)
    with _LOCK:
        rows = _conn().execute(q, args).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        if d.get("payload_json"):
            try:
                d["payload"] = json.loads(d["payload_json"])
            except Exception:
                d["payload"] = None
        out.append(d)
    return out


def job_counts() -> dict:
    """Job status counts, scoped to the caller when an owner is set (the
    scheduler calls this in a system context = all jobs)."""
    o = _owner()
    where = " WHERE owner_id=?" if o is not None else ""
    args = (o,) if o is not None else ()
    with _LOCK:
        rows = _conn().execute(
            f"SELECT status, COUNT(*) FROM jobs{where} GROUP BY status", args).fetchall()
    counts = {"queued": 0, "running": 0, "done": 0, "error": 0, "cancelled": 0}
    for r in rows:
        counts[r[0]] = r[1]
    return counts


def job_active_for(analysis_id: int, kinds: tuple | None = None) -> int:
    """Count of jobs in queued|running state for a given analysis (scoped)."""
    o = _owner()
    where = " AND owner_id=?" if o is not None else ""
    q = (f"SELECT COUNT(*) FROM jobs WHERE analysis_id=?{where} "
         "AND status IN ('queued','running')")
    args: list = [analysis_id]
    if o is not None:
        args.append(o)
    if kinds:
        q += " AND kind IN (%s)" % ",".join("?" * len(kinds))
        args.extend(kinds)
    with _LOCK:
        row = _conn().execute(q, args).fetchone()
    return row[0] if row else 0


def job_cleanup(limit: int = 500) -> int:
    """Delete finished jobs older than the `limit` most recent finished ones."""
    with _LOCK:
        c = _conn()
        c.execute("DELETE FROM jobs WHERE status IN ('done','error','cancelled') "
                  "AND id NOT IN (SELECT id FROM jobs "
                  "WHERE status IN ('done','error','cancelled') ORDER BY id DESC LIMIT ?)",
                  (limit,))
        c.commit()
        return c.total_changes
