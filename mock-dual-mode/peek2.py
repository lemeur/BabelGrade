import json
d = json.load(open("data.json"))
for m in d["analysis"]["matrix"]["rubric_mapping"]:
    print(m["criterion"], "->", m["suggested_level"])
print()
print("strong:", d["analysis"]["matrix"].get("strong_points"))
print("feedback:", d["analysis"]["matrix"].get("student_feedback"))
