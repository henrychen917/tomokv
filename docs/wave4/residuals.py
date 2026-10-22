#!/usr/bin/env python3
"""Retain strict instruction diffs and distinguish code from address/data identity."""
import difflib
import gzip
import json
from pathlib import Path
import identity

ROOT=identity.ROOT
OUT=ROOT/'build/wave4/residuals';OUT.mkdir(parents=True,exist_ok=True)
DOC=ROOT/'docs/wave4/identity'
before=identity.audit.Binary(identity.REFS['headline'],OUT,literal_pools=True)
after=identity.audit.Binary(ROOT/'build/tomokv',OUT,literal_pools=True)
rows=json.loads((DOC/'changed-bodies.json').read_text())
details=[]
for row in rows:
    if row['matches']: continue
    name=row['name']
    old=sorted(before.groups.get(name,[]),key=lambda b:b['addr'])
    new=sorted(after.groups.get(name,[]),key=lambda b:b['addr'])
    encoded_old=[b['encodings'] for b in old];encoded_new=[b['encodings'] for b in new]
    kind='symbol/clone emission' if len(old)!=len(new) else 'instruction bytes' if encoded_old!=encoded_new else 'resolved targets/literals only'
    row['difference_kind']=kind
    if kind=='resolved targets/literals only':
        row['reason']='Instruction encodings and clone multiplicity unchanged; strict resolved target/literal comparison differs. '+row['reason']
    a=[f'clone {i}: {line} | {code}' for i,b in enumerate(old) for line,code in zip(b['ins'],b['encodings'])]
    b=[f'clone {i}: {line} | {code}' for i,b in enumerate(new) for line,code in zip(b['ins'],b['encodings'])]
    details.append(dict(name=name,kind=kind,diff='\n'.join(difflib.unified_diff(a,b,fromfile='headline',tofile='merged'))))
with gzip.open(DOC/'residual-diffs.json.gz','wt') as stream:json.dump(details,stream,indent=2)
(DOC/'changed-bodies.json').write_text(json.dumps(rows,indent=2)+'\n')
(DOC/'changed-bodies.md').write_text('\n'.join([
    '# Linked body differences','',
    'Strict gate instruction/address normalization; local clone multiplicity retained. Identity is a proxy.','',
    '| Function | Headline sizes | Merged sizes | Reason |','|---|---|---|---|',
    *[f"| `{r['name']}` | {r['headline_sizes']} | {r['post_sizes']} | {r['reason']} |" for r in rows]])+'\n')
from collections import Counter
counts=dict(Counter(r['kind'] for r in details))
(DOC/'residual-kinds.json').write_text(json.dumps(counts,indent=2)+'\n')
print(counts)
for p in OUT.glob('*.objdump'):p.unlink()
