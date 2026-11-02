#!/usr/bin/env python3
"""Compare final production-bound instruction scopes without aggregating away a cell."""
import json
from pathlib import Path
from wave14_summary import key

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT/'docs/eoffix'
rows = []
for kind, pre_tag, expected in [('ordinary','',80),('parser','-final',52),('receive','',12)]:
    before = json.loads((DOC/'instructions'/('pre-'+kind+pre_tag)/'counts.json').read_text())
    after = json.loads((DOC/'instructions'/('post-'+kind+'-release')/'counts.json').read_text())
    pre = {key(r):r for r in before['rows']}
    post = {key(r):r for r in after['rows']}
    assert pre.keys()==post.keys() and len(pre)==expected
    for cell in pre:
        rows.append(dict(kind=kind,cell=cell,pre=pre[cell]['total'],post=post[cell]['total'],
                         added=post[cell]['total']-pre[cell]['total'],
                         pre_sha256=before['server_sha256'],post_sha256=after['server_sha256']))
out = dict(rows=rows,command_parser_nonzero=[r for r in rows if r['kind']!='receive' and r['added']],
           receive_deltas=sorted({r['added'] for r in rows if r['kind']=='receive'}))
(DOC/'instruction-comparison-final.json').write_text(json.dumps(out,indent=2)+'\n')
lines=['| Scope | Namespace | Command | Mode | Batch | Atomic | Read-local | PRE | POST | Added |',
       '|---|---|---|---|---:|---:|---:|---:|---:|---:|']
for row in rows:
    lines.append('| '+' | '.join(map(str,(row['kind'],*row['cell'],row['pre'],row['post'],row['added'])))+' |')
(DOC/'instruction-comparison-final.md').write_text('\n'.join(lines)+'\n')
print('cells',len(rows),'command/parser nonzero',len(out['command_parser_nonzero']),
      'receive deltas',out['receive_deltas'])
