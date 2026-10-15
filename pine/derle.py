import json, sys
d = open('/tmp/o').read()
try:
    j = json.loads(d)
    r = j.get('result', {}) or {}
    err = r.get('errors2') or r.get('errors') or j.get('reason') or []
    print('success:', j.get('success'), '| errors:', json.dumps(err, ensure_ascii=False)[:1500],
          '| warnings:', len(r.get('warnings2') or r.get('warnings') or []))
except Exception:
    print('ham:', d[:600])
