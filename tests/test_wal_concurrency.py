"""V5-C1 — prove SQLite WAL fixes the concurrent read/write contention.

The 2026-11-23 UX audit found the DB in `delete` journal mode: a writer locks
the WHOLE db file, so with 3 mobile sessions saving while a desktop reads
stats/lists, readers get "database is locked" / stall behind writes.

This test reproduces that exact pattern on a THROWAWAY DB (never touches
data/babelgrade.db): 4 readers (SELECT) + 3 writers (heavy txn commits) for
a few seconds, in both `delete` and `wal` modes. The differentiating signal:
  * READER lock errors  -> present in delete, ~0 in WAL
  * reader throughput   -> ~4-5x higher in WAL under the same writer load

Run:  /tmp/bg_venv/bin/python tests/test_wal_concurrency.py
      (any python3 works; no app deps, no live server needed.)
"""
import os, sqlite3, tempfile, threading, time

N_READERS = 4
N_WRITERS = 3
DUR = 5.0
ROWS_PER_TXN = 400      # heavy commit -> commit holds the write lock a while
PASS, FAIL = [], []


def check(n, c, x=""):
    (PASS if c else FAIL).append(n)
    print(("PASS " if c else "FAIL ") + n + (f" | {x}" if x and not c else ""))


def make_db(path, mode):
    c = sqlite3.connect(path)
    c.execute(f"PRAGMA journal_mode={mode}")
    c.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
    c.commit()
    c.close()


def run(path, label):
    stop = time.time() + DUR
    locked = {"w": 0, "r": 0}
    ok_w = {"n": 0}; ok_r = {"n": 0}
    rconns = [sqlite3.connect(path, check_same_thread=False, timeout=0.3)
              for _ in range(N_READERS)]
    wconns = [sqlite3.connect(path, check_same_thread=False, timeout=5.0)
              for _ in range(N_WRITERS)]
    for c in rconns: c.execute("PRAGMA busy_timeout=300")
    for c in wconns: c.execute("PRAGMA busy_timeout=5000")

    def reader(ci):
        c = rconns[ci]
        while time.time() < stop:
            try:
                c.execute("SELECT count(*) FROM t").fetchone()
                ok_r["n"] += 1
            except sqlite3.OperationalError as e:
                if "locked" in str(e): locked["r"] += 1
                else: raise
            time.sleep(0.001)

    def writer(ci):
        c = wconns[ci]
        while time.time() < stop:
            try:
                c.execute("BEGIN")
                c.executemany("INSERT INTO t(v) VALUES (?)",
                              [(bytes(64),)] * ROWS_PER_TXN)
                c.execute("COMMIT")
                ok_w["n"] += 1
                time.sleep(0.01)
            except sqlite3.OperationalError as e:
                if "locked" in str(e):
                    locked["w"] += 1
                    time.sleep(0.05)
                else: raise

    ts = [threading.Thread(target=reader, args=(i,)) for i in range(N_READERS)]
    ts += [threading.Thread(target=writer, args=(i,)) for i in range(N_WRITERS)]
    for t in ts: t.start()
    for t in ts: t.join()
    for c in rconns + wconns: c.close()
    jm = sqlite3.connect(path).execute("PRAGMA journal_mode").fetchone()[0]
    print(f"  {label:8s} journal_mode={jm:8s}  READER_locked={locked['r']:5d}  "
          f"writer_locked={locked['w']:4d}  reads={ok_r['n']}  heavy_writes={ok_w['n']}")
    return locked, ok_r["n"], jm


if __name__ == "__main__":
    tmp = tempfile.mkdtemp()
    print(f"Pattern: {N_READERS} readers + {N_WRITERS} writers "
          f"({ROWS_PER_TXN}-row txns), {DUR}s each.\n")
    del_ = del_reads = wal_ = wal_reads = None
    for mode, label in [("delete", "DELETE"), ("wal", "WAL")]:
        db = os.path.join(tmp, f"bg_{mode}.db")
        make_db(db, mode)
        locked, reads, jm = run(db, label)
        if mode == "delete":
            del_, del_reads = locked, reads
            check("delete journal mode is 'delete'", jm == "delete", jm)
        else:
            wal_, wal_reads = locked, reads
            check("wal journal mode is 'wal'", jm == "wal", jm)

    print("\n--- verdict ---")
    ratio = (wal_reads / del_reads) if del_reads else float("inf")
    check("WAL eliminates reader lock errors (delete had some)",
          del_["r"] > 0 and wal_["r"] == 0,
          f"delete={del_['r']} wal={wal_['r']}")
    check("WAL read throughput >= delete under 3 concurrent writers",
          wal_reads >= del_reads, f"delete={del_reads} wal={wal_reads}")
    print(f"\nWAL readers do {ratio:.1f}x the work of delete readers under "
          f"{N_WRITERS} concurrent writers.")
    print("\n===== WAL CONCURRENCY VERIFICATION =====")
    print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
    if FAIL:
        print("FAILURES:", FAIL)
        raise SystemExit(1)
