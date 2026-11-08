#!/usr/bin/env python3
"""Inventory mainline PRE, merged aclkeys3, and POST without executing a server."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from ccfix_audit import audit
from aclkeys3_audit import layouts

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('pre',type=Path)
p.add_argument('base',type=Path)
p.add_argument('post',type=Path)
p.add_argument('output',type=Path)
a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=True)
roots=[a.pre,a.base,a.post]
legacy_path=Path(__file__).resolve().parents[1]/'docs/aclkeys/aclkeys3/final-body-audit/changed-bodies.json'
legacy={(r['object'],r['symbol']):r['reason'] for r in json.loads(legacy_path.read_text())}
rows=[]
for rel in sorted({f.relative_to(root) for root in roots for sub in ('src','db0/src')
                   for f in (root/sub).rglob('*.o')}):
    elves=[audit.Elf(root/rel) if (root/rel).exists() else None for root in roots]
    functions=[elf.functions() if elf else {} for elf in elves]
    symbols=sorted(set().union(*(x.keys() for x in functions)))
    names=subprocess.check_output(['c++filt'],input='\n'.join(symbols)+'\n',text=True).splitlines()
    for symbol,name in zip(symbols,names):
        bodies=[elf.canonical(table[symbol]) if elf and symbol in table else None
                for elf,table in zip(elves,functions)]
        equal=bodies[0] is not None and bodies[0]==bodies[2]
        incremental=bodies[1]==bodies[2]
        fixed=(str(rel)=='src/cmd/t_stream.o' and '::cmd_xadd<' in name or
               str(rel)=='src/cmd/t_list.o' and '::xshard_push_list_element_impl<' in name)
        if fixed and not incremental:
            reason=('Publish XADD using its captured physical database' if '::cmd_xadd<' in name else
                    'Publish both list-push outcomes using the destination key namespace')
            if '[clone .cold]' in name: reason+='; associated exception landing pad'
        elif not incremental:
            reason='UNEXPECTED aclkeys4 change outside namespace publication'
        elif not equal:
            reason='Inherited unchanged from merged aclkeys3: '+legacy.get((str(rel),symbol),
                'existing lane body; see the mainline/merged/POST canonical hashes')
        else:
            reason='Identical opcodes and resolved targets'
        rows.append(dict(object=str(rel),symbol=symbol,name=name,equal=equal,
                         aclkeys4_equal=incremental,aclkeys4_fixed_path=fixed,
                         pre_size=functions[0].get(symbol,{}).get('size',0),
                         base_size=functions[1].get(symbol,{}).get('size',0),
                         post_size=functions[2].get(symbol,{}).get('size',0),
                         canonical_sha256=[hashlib.sha256(repr(b).encode()).hexdigest() if b else None for b in bodies],
                         reason=reason))
    print(rel,len(symbols),flush=True)
changed=[r for r in rows if not r['equal']]
new=[r for r in rows if not r['aclkeys4_equal']]
unexpected=[r for r in new if not r['aclkeys4_fixed_path']]
hot=[r for r in rows if audit.HOT.search(r['name']) or re.search(r'ExLoopT<.*>::run\(',r['name'])]
handlers=[r for r in rows if re.search(r'::cmd_\w+(?:<|\()',r['name']) and
          '::cmd_debug' not in r['name'] and not r['aclkeys4_fixed_path']]
layout={name:layouts(root/'tomokv') for name,root in zip(('PRE','BASE','POST'),roots)}
arms={}
for name,root in zip(('PRE','BASE','POST'),roots):
    elf=audit.Elf(root/'tomokv')
    arms[name]=dict(sha256=hashlib.sha256(elf.data).hexdigest(),text_bytes=elf.sections[elf.names.index('.text')][5])
summary=dict(total=len(rows),equal=sum(r['equal'] for r in rows),changed=len(changed),
             aclkeys4_equal=sum(r['aclkeys4_equal'] for r in rows),aclkeys4_changed=len(new),
             unexpected=unexpected,hot=len(hot),hot_equal=sum(r['equal'] for r in hot),
             ordinary_handlers=len(handlers),ordinary_handlers_equal=sum(r['equal'] for r in handlers),
             layouts_equal=layout['PRE']==layout['BASE']==layout['POST'],arms=arms)
with gzip.open(a.output/'bodies.json.gz','wt') as f:json.dump(rows,f,indent=2)
for filename,value in [('summary.json',summary),('changed-bodies.json',changed),
                       ('aclkeys4-bodies.json',new),('layouts.json',layout)]:
    (a.output/filename).write_text(json.dumps(value,indent=2)+'\n')
text=['# Emitted body inventory','','PRE is the fresh mainline merge-base; BASE is the merged lane before aclkeys4.',
      'Opcodes, offsets and resolved targets are checked; no error-callee or opcode masking.','',
      '| Object | Body | PRE | BASE | POST | Reason |','|---|---|---:|---:|---:|---|']
for r in changed:
    text.append('| `%s` | `%s` | %d | %d | %d | %s |' %
                (r['object'],r['name'].replace('|','\\|'),r['pre_size'],r['base_size'],r['post_size'],r['reason']))
(a.output/'changed-bodies.md').write_text('\n'.join(text)+'\n')
print(json.dumps(summary,indent=2),flush=True)
assert not unexpected, 'aclkeys4 changed an unrelated emitted body'
assert len(new)==6, 'expected exactly two XADD bodies and two list helpers with their cold clones'
assert summary['layouts_equal'], 'layout drift'
assert summary['hot']==summary['hot_equal'], 'ordinary hot body drift'
assert summary['ordinary_handlers']==summary['ordinary_handlers_equal'], 'ordinary handler drift'
