#!/usr/bin/env python3
"""Validate the complete finite instruction product and attribute every changed symbol."""
import csv
import itertools
import json
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DOC=ROOT/'docs/clientcompat'
I=DOC/'instructions'

def compare(session=False):
    prefix='-session' if session else ''
    before=json.loads((I/('PRE'+prefix+'-elf')/'counts.json').read_text())
    after=json.loads((I/('POST'+prefix+'-elf')/'counts.json').read_text())
    verbs=['EXEC-single','EXEC-cross','EXEC-reads-single','EXEC-reads-cross'] if session else ['GET','SET','INCR','MGET','MSET']
    commands=[p+c for p in ('','TRACK-') for c in verbs]
    expected=set(itertools.product(('normal','db0'),commands,('1s','2s'),(1,4) if session else (1,32),(0,1)))
    def key(r):return tuple(r[k] for k in ('namespace','command','mode','batch','atomic'))
    pre={key(r):r for r in before['rows']};post={key(r):r for r in after['rows']}
    assert len(pre)==len(before['rows']) and len(post)==len(after['rows'])
    assert set(pre)==set(post)==expected
    rows=[];sites=[]
    for k in sorted(expected):
        a,b=pre[k],post[k];base=dict(zip(('namespace','command','mode','batch','atomic'),k))
        rows.append(dict(**base,pre=a['total'],post=b['total'],delta=b['total']-a['total'],per_command_delta=(b['total']-a['total'])/k[3]))
        for name in sorted(a['functions'].keys()|b['functions'].keys()):
            x,y=a['functions'].get(name,0),b['functions'].get(name,0)
            if x!=y:sites.append(dict(**base,symbol=name,pre=x,post=y,delta=y-x))
    name='session' if session else 'command'
    for suffix,data in [('totals',rows),('sites',sites)]:
        with (DOC/(name+'-'+suffix+'.csv')).open('w') as f:
            w=csv.DictWriter(f,fieldnames=list(data[0]),lineterminator='\n');w.writeheader();w.writerows(data)
    result=dict(rows=len(rows),equal=sum(r['delta']==0 for r in rows),lower=sum(r['delta']<0 for r in rows),higher=sum(r['delta']>0 for r in rows),min_per_command_delta=min(r['per_command_delta'] for r in rows),max_per_command_delta=max(r['per_command_delta'] for r in rows),changed_symbol_rows=len(sites),pre_server_sha256=before['server_sha256'],post_server_sha256=after['server_sha256'])
    if not session:assert result['higher']==0,result
    return result

result=dict(domain='All executed functions in the linked executable, including out-of-line STL; fixture function bodies and shared libraries excluded. The identical PRE and POST scope markers bound one operation batch.',commands=compare(),sessions=compare(True))
(DOC/'instruction-summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
