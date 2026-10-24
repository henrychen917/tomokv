#!/usr/bin/env python3
"""Apply the gate's unchanged linked-instruction normalizer to this lane."""
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'))
import reorder_noop as audit
out=ROOT/'build/atomfix5-linked'
out.mkdir(exist_ok=True)
audit.self_test()
pre=audit.Binary(ROOT/'build/tomokv-pre',out,literal_pools=True)
post=audit.Binary(ROOT/'build/tomokv',out,literal_pools=True)
rows=audit.compare(pre,post,out)
selected=re.compile(r'::cmd_(?:get|set|mget|mset)(?:\(|<)|prepare_captured_local_mget|xshard_.*mset')
hot=[]
changed=[]
for name in sorted(set(pre.groups)|set(post.groups)):
    a=sorted(pre.groups.get(name,[]),key=lambda b:b['addr'])
    b=sorted(post.groups.get(name,[]),key=lambda b:b['addr'])
    equal=[(v['ins'],v['encodings']) for v in a]==[(v['ins'],v['encodings']) for v in b]
    aliases=[alias for body in a+b for alias in body['aliases']]
    row=dict(name=name,equal=equal,pre_sizes=[v['size'] for v in a],post_sizes=[v['size'] for v in b])
    if selected.search(name) or any(selected.search(alias) for alias in aliases):hot.append(row)
    if not equal:changed.append(row)
result=dict(pre_sha256=pre.sha256,post_sha256=post.sha256,gate_selection=rows,
            hot=hot,changed=changed,hot_identical=all(row['equal'] for row in hot))
(ROOT/'docs/atomfix5/linked-identity.json').write_text(json.dumps(result,indent=2)+'\n')
for path in out.glob('*.objdump'):path.unlink()
print(json.dumps(dict(hot=len(hot),hot_identical=result['hot_identical'],changed=len(changed),
                      selected=len(rows),selected_changed=sum(not row['equal'] for row in rows))))
