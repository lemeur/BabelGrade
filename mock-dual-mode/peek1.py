import json
d = json.load(open("data.json"))
rub = d["rubric"]
print("rubric keys:", list(rub.keys()))
for c in rub["criteria"][:1]:
    print("criterion keys:", list(c.keys()))
    print("desc head:", c["description"][:150])
an = d["analysis"]
print("analysis keys:", list(an.keys()))
m = an["matrix"]
print("matrix type:", type(m))
if isinstance(m, dict):
    print("matrix keys:", list(m.keys()))
    rm = m.get("rubric_mapping")
    print("rubric_mapping len:", len(rm) if rm else None)
    if rm:
        print("first:", json.dumps(rm[0])[:400])
        print("crits:", [x.get("criterion") for x in rm])
elif isinstance(m, list):
    print("first item:", json.dumps(m[0])[:400])
print("overall:", an["overall"], "feedback:", str(an["feedback"])[:200])
