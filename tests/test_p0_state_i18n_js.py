#!/usr/bin/env python3
"""P0.6 state-check: i18n 4x4 balance + node --check on extracted inline JS."""
import re, subprocess, sys, os

html = open('/home/tibo/babelgrade/static/index.html').read()

# --- i18n balance: keys in the I18N{...} slice must appear exactly 4x in definitions
i18n_start = html.index('I18N={')
i18n_end = html.index('let LANG', i18n_start)
i18n_slice = html[i18n_start:i18n_end]
keys = re.findall(r"'((?:[a-zA-Z0-9_]+\.)?(?:[a-zA-Z0-9_]+))':", i18n_slice)
bad = {}
for k in keys:
    n = len(re.findall(r"'" + re.escape(k) + r"':", html))
    if n != 4:
        bad[k] = n
print(f"i18n keys scanned: {len(set(keys))} distinct / {len(keys)} total")
if bad:
    print("MISMATCH:", bad)
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
