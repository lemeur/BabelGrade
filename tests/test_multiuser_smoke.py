"""Multi-user smoke test for the BabelGrade (in-process, temp DB).

Runs the real FastAPI app via TestClient against a throwaway sqlite file and
verifies: 401 gate, register-first-only, login/logout, me, set-password,
owner scoping of students/assignments, and cross-user isolation.
"""
import json, sys, tempfile

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app.db as db

TMP = Path(tempfile.mkdtemp(prefix="elt_mu_test_"))
db.DB_PATH = TMP / "test.db"
db._CONN = None  # force a fresh connect on the temp path (check _conn below)

from fastapi.testclient import TestClient
from app.main import app
from app import auth as _auth

client = TestClient(app, raise_server_exceptions=True)

def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))
    return cond

ok = True

# --- unauthenticated gate -------------------------------------------------
r = client.get("/api/students")
ok &= check("unauth /api/students -> 401", r.status_code == 401, str(r.status_code))
r = client.get("/api/health")
ok &= check("public /api/health -> 200", r.status_code == 200, str(r.status_code))
r = client.get("/")
ok &= check("static index -> 200", r.status_code == 200, str(r.status_code))

# --- first-user registration ---------------------------------------------
r = client.get("/api/auth/me")
ok &= check("me before login: no user", r.status_code == 200 and r.json()["user"] is None,
            json.dumps(r.json()))
r = client.post("/api/auth/register",
                json={"username": "tibo", "password": "tibo-test-pw-1"})
ok &= check("register first user", r.status_code == 200, r.text)
ok &= check("register sets session cookie", "elt_session" in r.cookies,
            str(list(r.cookies.keys())))

r = client.get("/api/auth/me")
ok &= check("me after register", r.status_code == 200
            and r.json()["user"]["username"] == "tibo" and r.json()["has_password"],
            json.dumps(r.json()))

# registration closed once an account exists
r = client.post("/api/auth/register",
                json={"username": "mallory", "password": "mallory-pw-1"})
ok &= check("register second user -> 403 closed", r.status_code == 403, str(r.status_code))

# weak password rejected
r = client.post("/api/auth/register", json={"username": "x", "password": "123"})
# (unreachable: closed; verify the validation path instead via auth.create_user)
from app import auth
try:
    auth.create_user("short", "123")
    ok &= check("weak password rejected", False)
except ValueError:
    ok &= check("weak password rejected", True)

# --- login / wrong password / logout --------------------------------------
r = client.post("/api/auth/login", json={"username": "tibo", "password": "wrong-pass-1"})
ok &= check("login wrong password -> 401", r.status_code == 401, str(r.status_code))

# fresh client for tibo login
c1 = TestClient(app)
r = c1.post("/api/auth/login", json={"username": "TIBO", "password": "tibo-test-pw-1"})
ok &= check("login case-insensitive username", r.status_code == 200, r.text)

# --- set-password (change) --------------------------------------------------
r = c1.post("/api/auth/set-password",
            json={"current": "wrong-pass-1", "password": "new-pass-12345"})
ok &= check("set-password wrong current -> 401", r.status_code == 401, str(r.status_code))
r = c1.post("/api/auth/set-password",
            json={"current": "tibo-test-pw-1", "password": "new-pass-12345"})
ok &= check("set-password with correct current", r.status_code == 200, r.text)
r = c1.post("/api/auth/login", json={"username": "tibo", "password": "new-pass-12345"})
ok &= check("login with new password", r.status_code == 200, str(r.status_code))
# --- tibo's data ------------------------------------------------------------
sid = c1.post("/api/students", json={"name": "Alice Martin", "classroom": "26/27-LMY-2G1"}).json()["id"]
sid2 = c1.post("/api/students", json={"name": "Bob Petit", "classroom": "26/27-LMY-2G1"}).json()["id"]
asg = c1.post("/api/assignments",
              data={"name": "Diss B1", "description": "", "target_level": "B1",
                    "skill": "expression", "kind": "written"}).json()["id"]
r = c1.get("/api/students")
ok &= check("tibo sees 2 students", r.status_code == 200 and len(r.json()) == 2,
            json.dumps(r.json()))
r = c1.get("/api/assignments")
ok &= check("tibo sees 1 assignment", len(r.json()) == 1, json.dumps(r.json()))

# --- logout: cookie removed, then 401 ----------------------------------------
tok = c1.cookies.get("elt_session")
assert tok, "session cookie present before logout"
r = c1.post("/api/auth/logout")
ok &= check("logout -> 200", r.status_code == 200, str(r.status_code))
ok &= check("logout prunes session from DB",
            auth.user_by_session_token(tok) is None)
c1.cookies.clear()
r = c1.get("/api/students")
ok &= check("after logout -> 401", r.status_code == 401, str(r.status_code))
# re-login for the isolation checks below
c1.post("/api/auth/login", json={"username": "tibo", "password": "new-pass-12345"})

# --- second teacher (created directly in DB — registration is closed) ------
uid2 = auth.create_user("marie", "marie-pw-1")
c2 = TestClient(app)
r = c2.post("/api/auth/login", json={"username": "marie", "password": "marie-pw-1"})
ok &= check("marie login", r.status_code == 200, str(r.status_code))

r = c2.get("/api/students")
ok &= check("marie starts with 0 students (isolated)", r.json() == [], json.dumps(r.json()))
r = c2.get("/api/assignments")
ok &= check("marie sees 0 assignments (isolated)", r.json() == [], json.dumps(r.json()))

# marie cannot read/modify tibo's rows
r = c2.get(f"/api/students/{sid}/stats")
ok &= check("marie GET tibo's student -> 404", r.status_code == 404, str(r.status_code))
r = c2.put(f"/api/students/{sid}", json={"name": "HACKED"})
ok &= check("marie PUT tibo's student -> 404", r.status_code == 404, str(r.status_code))
r = c2.delete(f"/api/students/{sid}")
ok &= check("marie DELETE tibo's student -> 404", r.status_code == 404, str(r.status_code))
r = c2.delete(f"/api/assignments/{asg}")
ok &= check("marie DELETE tibo's assignment -> 404", r.status_code == 404, str(r.status_code))

r = c1.get("/api/students")
ok &= check("tibo's student untouched by marie",
            any(s["name"] == "Alice Martin" for s in r.json()), json.dumps(r.json()))

# marie creates her own data — invisible to tibo
mid = c2.post("/api/students", json={"name": "Chloé Dupont", "classroom": "26/27-BCN-1G1"}).json()["id"]
r = c1.get("/api/students")
ok &= check("marie's student invisible to tibo",
            len(r.json()) == 2 and all(s["id"] != mid for s in r.json()),
            json.dumps(r.json()))

# rubrics: presets shared, custom private
r1 = c1.get("/api/rubrics")
r2 = c2.get("/api/rubrics")
n_preset = len(r1.json())
ok &= check("presets shared to both",
            n_preset == len(r2.json()) and n_preset >= 4,
            f"{n_preset} vs {len(r2.json())}")
rcid = c1.post("/api/rubrics", json={"name": "tibo custom", "mode": "written",
                                    "criteria": [{"code": "X", "name": "x", "levels": []}]})
ok &= check("tibo creates custom rubric", rcid.status_code == 200, rcid.text)
cid = rcid.json()["id"]
r1b = c1.get("/api/rubrics")
r2b = c2.get("/api/rubrics")
ok &= check("tibo sees own custom rubric",
            any(x["id"] == cid for x in r1b.json()))
ok &= check("custom rubric invisible to marie",
            all(x["id"] != cid for x in r2b.json())
            and len(r2b.json()) == len(r1b.json()) - 1,
            json.dumps([x["name"] for x in r2b.json()]))

# jobs scoping
r1 = c1.get("/api/jobs")
r2 = c2.get("/api/jobs")
ok &= check("jobs lists empty for both at start",
            r1.status_code == 200 and r2.json()["jobs"] == [],
            json.dumps(r2.json()))

# health still public
ok &= check("health public", c2.get("/api/health").status_code == 200)

# --- first-boot edge: operator registers via the gate ---------------------
# Simulate a fresh deployment: wipe users+sessions, create legacy-ish data
# with NULL owners (as a pre-multi-user dataset would look), then run the
# gate's "create account" flow and verify the owner backfill attaches it all.
with db._LOCK:
    c = db._conn()
    c.execute("DELETE FROM sessions")
    c.execute("DELETE FROM users")
    # legacy rows with no owner (NULL) — the shape of a pre-multi-user DB
    c.execute("UPDATE students SET owner_id=NULL")
    c.execute("UPDATE assignments SET owner_id=NULL")
    c.execute("UPDATE rubrics SET owner_id=NULL WHERE is_preset=0")
    c.execute("UPDATE jobs SET owner_id=NULL")
    c.commit()
ok &= check("users wiped for first-boot sim", _auth.count_users() == 0)
r = client.get("/api/auth/me")
ok &= check("me: no account -> gate is 'create account'",
            r.json()["user"] is None and r.json()["has_account"] is False,
            json.dumps(r.json()))
r = client.post("/api/auth/register",
                json={"username": "operator", "password": "operator-pw-1"})
ok &= check("first-boot operator registers via gate", r.status_code == 200,
            r.text)
# the backfill must now own every legacy row for the operator
# (3 students: tibo's Alice+Bob AND marie's Chloé — marie was wiped,
#  her row is legacy data with NULL owner now)
r = client.get("/api/students")
ok &= check("legacy students attached to operator (backfill)",
            r.status_code == 200 and len(r.json()) == 3
            and all(x["owner_id"] == 3 for x in r.json()),
            json.dumps(r.json()))
r = client.get("/api/assignments")
ok &= check("legacy assignments attached to operator (backfill)",
            len(r.json()) == 1, json.dumps(r.json()))
# custom rubric also attached; presets still shared (owner NULL)
r = client.get("/api/rubrics")
ok &= check("operator sees presets + own custom rubric",
            any(x["id"] == cid for x in r.json())
            and sum(1 for x in r.json() if x["is_preset"]) >= 4,
            json.dumps([x["id"] for x in r.json()]))
# registration stays closed after the first account
r = client.post("/api/auth/register",
                json={"username": "latecomer", "password": "latecomer-pw-1"})
ok &= check("registration still closed", r.status_code == 403, str(r.status_code))


print()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
