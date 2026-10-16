"""Re-derive note->attestation bands by ROW (y), not x. LVA/LVB are separate rows."""
import pymupdf, re

PDF = "/home/tibo/.hermes/cache/documents/doc_ddc7cdc6cc88_grilles-lva-et-lvb-avec-premierepdf-97680.pdf"
doc = pymupdf.open(PDF)

LEVELS = {"A1", "A2", "A2+", "B1", "B1+", "B2", "B2-", "B2(-)", "C1", "C2"}

def parse_band(t):
    t = t.strip()
    if t in LEVELS:
        return None
    if t == "0":
        return (0, 0)
    m = re.match(r"^(\d+)\s*-\s*(\d+)\s*$", t)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    m = re.match(r"^(\d+)\s*\+$", t)
    if m:
        return (int(m.group(1)), None)
    return None

def row_spans(pno, y_min, y_max):
    page = doc[pno]
    d = page.get_text("dict")
    spans = []
    for b in d["blocks"]:
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                t = s["text"].strip()
                y = s["bbox"][1]
                if t and y_min <= y <= y_max:
                    spans.append((round(s["bbox"][0], 1), round(y, 1), t))
    return spans

# For each table, locate the LVA label and LVB label y, then take a +-14px row window
tables = {
    ("comprehension", "premiere"): (1, 150, 230),
    ("comprehension", "terminale"): (1, 340, 400),
    ("expression", "premiere"): (4, 190, 265),
    ("expression", "terminale"): (4, 395, 475),
}

for (mod, classe), (pno, ym, ymax) in tables.items():
    spans = row_spans(pno, ym, ymax)
    lva_y = [y for (x, y, t) in spans if t == "LVA"]
    lvb_y = [y for (x, y, t) in spans if t == "LVB"]
    print(f"===== {mod} {classe} =====")
    for track, ty in (("LVA", lva_y[0]), ("LVB", lvb_y[0])):
        # row window around the track label y
        row = [(x, t) for (x, y, t) in spans if abs(y - ty) <= 14 and t not in ("LVA", "LVB")]
        lvl = sorted([(x, t) for (x, t) in row if t in LEVELS])
        bands = []
        for (x, t) in row:
            b = parse_band(t)
            if b:
                bands.append((x, b, t))
        bands.sort()
        out = []
        prev = None
        for (x, b, txt) in bands:
            lv = None
            for (lx, lt) in lvl:
                if abs(lx - x) <= 5:
                    lv = lt
            if lv is None:
                lv = prev
            if lv:
                prev = lv
            out.append(f"{txt}={lv}")
        print(f"  [{track}] levels: {lvl}")
        print(f"  [{track}] bands:  {' '.join(out)}")
        print()
