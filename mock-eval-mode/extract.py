import json, re

r = json.load(open('/tmp/elt_mock/rubric_full.json'))

def parse(desc):
    out = {}
    for m in re.finditer(r'(C2|C1|B2|B1|A2|A1)\s*:\s*', desc):
        key = m.group(1)
        start = m.end()
        nxt = re.search(r'\b(?:C2|C1|B2|B1|A2|A1)\s*:', desc[start:])
        end = start + (nxt.start() if nxt else len(desc) - start)
        out[key] = desc[start:end].strip().rstrip('.').strip()
    return out

data = []
for c in r['criteria']:
    data.append({'name': c['name'], 'levels': parse(c['description'])})

a = json.load(open('/tmp/elt_mock/analysis17_full.json'))
raw = json.loads(a['raw_markdown'])
ai = {m['criterion']: m for m in raw['rubric_mapping']}
att = a['attestation']
for c in data:
    b = next(x for x in att['breakdown'] if x['criterion'] == c['name'])
    c['ai'] = ai[c['name']]['suggested_level']
    c['teacher'] = b['level_norm']
    c['justif'] = ai[c['name']]['justification']
    c['evidence'] = ai[c['name']]['evidence']
    for L, txt in c['levels'].items():
        print(c['name'][:20], '|', L, '|', len(txt))

json.dump(data, open('/tmp/mock_data.json', 'w'), ensure_ascii=False, indent=1)
print('OK saved /tmp/mock_data.json')
