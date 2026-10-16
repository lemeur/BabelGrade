#!/usr/bin/env python3
"""Extract real data from the live API for the dual-mode mock."""
import json, urllib.request

BASE = "http://127.0.0.1:8090"

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as r:
        return json.loads(r.read())

rub = get("/api/rubrics/att-exp-ecrite")
an = get("/api/analyses/17")

out = {
    "rubric": rub,
    "analysis": {
        "id": an.get("id"),
        "status": an.get("status"),
        "matrix": an.get("matrix"),
        "overall": an.get("overall_level"),
        "feedback": an.get("feedback"),
        "attestation": an.get("attestation"),
        "raw_markdown_head": (an.get("raw_markdown") or "")[:400],
    },
    "submission": an.get("submission"),
}
with open("data.json", "w") as f:
    json.dump(out, f, indent=1)
print("rubric criteria:", len(rub.get("criteria", [])))
print("analysis 17 overall:", out["analysis"]["overall"], "| matrix crits:", len(out["analysis"]["matrix"] or []))
print("submission title:", (out["submission"] or {}).get("title"), "| kind:", (out["submission"] or {}).get("kind"))
print("attestation:", json.dumps(out["analysis"]["attestation"])[:300])
