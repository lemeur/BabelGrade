#!/usr/bin/env python3
"""P0.6 state-check: i18n 4x4 balance + node --check on extracted inline JS."""
import re, subprocess, sys, os
from pathlib import Path

html = open(Path(__file__).resolve().parent.parent / 'static' / 'index.html').read()

# --- i18n balance: keys in the I18N{...} slice must be defined exactly 4x
#     (one per language pack EN/FR/ES/DE). Count WITHIN the slice only — the
#     whole-file count would over-count legitimate CONSUMER usages (e.g. the
#     V3 RES_ICON map reuses td.* keys as object keys), which is not a
#     language definition. (Invariant tightened 2026-11-24 after V3 shipped
#     the resource-icon map.)
i18n_start = html.index('I18N={')
i18n_end = html.index('let LANG', i18n_start)
i18n_slice = html[i18n_start:i18n_end]
keys = re.findall(r"'((?:[a-zA-Z0-9_]+\.)?(?:[a-zA-Z0-9_]+))':", i18n_slice)
from collections import Counter
c = Counter(keys)
bad = {k: n for k, n in c.items() if n != 4}
print(f"i18n keys scanned: {len(set(keys))} distinct / {len(keys)} total")
if bad:
    print("MISMATCH (defined != 4x in the 4 language packs):", bad)
    sys.exit(1)
print("i18n 4x4 balanced, 0 mismatch")

# --- node --check on each inline script block
scripts = re.findall(r'<script(?![^>]*src)[^>]*>(.*?)</script>', html, re.S)
os.makedirs('/tmp/elt_p0/js', exist_ok=True)
for i, s in enumerate(scripts):
    p = f'/tmp/elt_p0/js/block_{i}.js'
    open(p, 'w').write(s)
    r = subprocess.run(['node', '--check', p], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"SYNTAX FAIL block {i}: {r.stderr[:500]}")
        sys.exit(1)
print(f"node --check: {len(scripts)} inline script blocks OK")
