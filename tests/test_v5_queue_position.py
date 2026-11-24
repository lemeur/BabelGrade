"""V5-C3 — queue position (job n°X) + max_workers ladder.

Hermetic: uses a throwaway DB via BABELGRADE_DB_PATH, no live server needed.
Proves:
  * db.job_queue_positions() -> {job_id: 1-based position, oldest first}
  * job_list() annotates queued jobs with queue_pos, None otherwise, and
    positions COMPACT when a job is claimed (1,2,3 -> running,1,2)
  * the /api/jobs/{id} route's queue_pos rule (queued -> position, else None)
  * max_workers ladder: BABELGRADE_MAX_WORKERS env > DB setting > new default
    (3), clamped to 1..4, garbage env falls back.

Run:  /home/tibo/.hermes/hermes-agent/venv/bin/python tests/test_v5_queue_position.py
      (any env with the app importable; the hermes-agent venv has fastapi.)
"""
import os, sys, tempfile

tmp = tempfile.mkdtemp()
os.environ["BABELGRADE_DB_PATH"] = os.path.join(tmp, "test.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import db, jobs  # noqa: E402

PASS, FAIL = [], []


def check(n, c, x=""):
    (PASS if c else FAIL).append(n)
    print(("PASS " if c else "FAIL ") + n + (f" | {x}" if x and not c else ""))


db.init_db()

# 3 queued jobs, oldest first = id order
db._conn().execute(
    "INSERT INTO users (username, username_lower, password_hash, created_at) "
    "VALUES ('u1','u1','x',?)", (db.now_iso(),))
db._conn().commit()
owner = 1
for _ in range(3):
    db._conn().execute(
        "INSERT INTO jobs (kind, status, payload_json, owner_id, created_at) "
        "VALUES ('analyze','queued','{}',?,?)", (owner, db.now_iso()))
db._conn().commit()
ids = [r[0] for r in db._conn().execute("SELECT id FROM jobs ORDER BY id")]

pos = db.job_queue_positions()
check("job_queue_positions: oldest=1..3", pos == {ids[0]: 1, ids[1]: 2, ids[2]: 3},
      str(pos))

rows = db.job_list(status="queued")
got = {r["id"]: r.get("queue_pos") for r in rows}
check("job_list annotates queue_pos", got == {ids[0]: 1, ids[1]: 2, ids[2]: 3},
      str(got))

# claim the first -> running (no position), the rest compact
db.job_update(ids[0], status="running")
got = {r["id"]: r.get("queue_pos") for r in db.job_list()}
check("positions compact after a claim", got[ids[0]] is None
      and got[ids[1]] == 1 and got[ids[2]] == 2, str(got))

# /api/jobs/{id} route rule: queued -> position, else None
j = db.job_get(ids[1])
route_qpos = db.job_queue_positions().get(j["id"]) if j["status"] == "queued" else None
check("route rule: queued job -> position", route_qpos == 1, str(route_qpos))
j0 = db.job_get(ids[0])
route_qpos0 = db.job_queue_positions().get(j0["id"]) if j0["status"] == "queued" else None
check("route rule: running job -> None", route_qpos0 is None, str(route_qpos0))

# ---- max_workers ladder (V5-C2) ----
os.environ.pop("BABELGRADE_MAX_WORKERS", None)
check("default max_workers is now 3", jobs.max_workers() == 3,
      str(jobs.max_workers()))
os.environ["BABELGRADE_MAX_WORKERS"] = "1"
check("env override wins", jobs.max_workers() == 1, str(jobs.max_workers()))
os.environ["BABELGRADE_MAX_WORKERS"] = "99"
check("env clamps to cap 4", jobs.max_workers() == 4, str(jobs.max_workers()))
os.environ["BABELGRADE_MAX_WORKERS"] = "garbage"
check("garbage env -> default 3", jobs.max_workers() == 3, str(jobs.max_workers()))
del os.environ["BABELGRADE_MAX_WORKERS"]
db.set_setting("max_workers", "2")
check("DB setting beats default", jobs.max_workers() == 2, str(jobs.max_workers()))

print("\n===== V5 QUEUE-POSITION VERIFICATION =====")
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FAILURES:", FAIL)
    raise SystemExit(1)
