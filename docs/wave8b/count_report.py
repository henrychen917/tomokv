#!/usr/bin/env python3
"""Exact accounting for the bounded named-command scope, with attribution limits."""
import collections,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; OUT=ROOT/'docs/wave8b'; DATA=OUT/'instructions'
def read(arm,tag): return json.loads((DATA/(arm+'-'+tag+'.json')).read_text())
def attribution(name):
    if 'LatencyTrackingPart::' in name:
        return 'latencyfix f57bc32ad parent/RAII; 3577500ef child scopes (shared callee)'
    if 'latency_tracking_forget(' in name or 'destroy_multi_state(' in name:
        return 'latencyfix f57bc32ad child cleanup; 83fcbf636 adds script-map cleanup when stores exist'
    if 'latency_tracking_retire(' in name:
        return 'latencyfix 3577500ef introduced child retire; integration 4161f1b0c moved it to IO; 83fcbf636 adds script children'
    if 'multi_retire(' in name:
        return 'integration 4161f1b0c logical-child retirement loop; wave8b guards it'
    if 'multi_execute_task(' in name:
        return 'latencyfix f57bc32ad/3577500ef timing scope call plumbing; wave8b body specialization and compiler propagation'
    return 'shared unchanged helper: wave8b caller/inlining propagation; no isolated source-commit causal attribution'
rows=[]; ledger=[]
for ns in ('normal','db0'):
 for shape in ('single','cross'):
  for mode in ('1s','2s'):
   for n in (1,2,4):
    for atomic in (0,1):
     tag=f'{ns}-EXEC-{shape}-{mode}-{n}-{atomic}--1'
     arms={a:read(a,tag) for a in ('headline','execindex','pre','post')}
     base=arms['execindex']['functions']
     record=dict(namespace=ns,shape=shape,mode=mode,children=n,atomic=atomic,
         **{a:r['total'] for a,r in arms.items()})
     record.update(delta_before=record['pre']-record['execindex'],delta_after=record['post']-record['execindex'])
     changes=[]
     for name in sorted(set(base)|set(arms['pre']['functions'])|set(arms['post']['functions'])):
      before=arms['pre']['functions'].get(name,0)-base.get(name,0)
      after=arms['post']['functions'].get(name,0)-base.get(name,0)
      if before or after: changes.append(dict(function=name,before=before,after=after,basis=attribution(name)))
     assert sum(r['before'] for r in changes)==record['delta_before']
     assert sum(r['after'] for r in changes)==record['delta_after']
     assert not any('LatencyTracking' in k or 'latency_tracking_' in k for k in arms['post']['functions'])
     rows.append(record);ledger.append(dict(case=record,functions=changes))
(OUT/'exec-comparison.json').write_text(json.dumps(rows,indent=2)+'\n')
(OUT/'exec-attribution.json').write_text(json.dumps(ledger,indent=2)+'\n')
lines=['# Command-scope EXEC instruction counts','','All numbers are named production instructions, not throughput. See the root report for scope and provenance.','',
 '| Namespace | Shape | Mode | Children | Atomic | Headline | Execindex | PRE | POST | PRE−EI | POST−EI |',
 '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
for r in rows:lines.append('| '+' | '.join(str(r[k]) for k in ('namespace','shape','mode','children','atomic','headline','execindex','pre','post','delta_before','delta_after'))+' |')
(OUT/'exec-comparison.md').write_text('\n'.join(lines)+'\n')
main=[]
for post in json.loads((DATA/'results-post.json').read_text()):
 tag='-'.join(str(post[k]) for k in ('namespace','command','mode','batch','atomic','threshold'))
 head=read('headline',tag)
 main.append({k:post[k] for k in ('namespace','command','mode','batch','atomic','threshold')}|
     dict(headline=head['total'],post=post['total'],delta=post['total']-head['total']))
(OUT/'main-comparison.json').write_text(json.dumps(main,indent=2)+'\n')
lines=['# Main command instruction counts','',
 '| Namespace | Command | Mode | Batch | Atomic | Slowlog µs | Headline | POST | Delta |',
 '|---|---|---|---:|---:|---:|---:|---:|---:|']
for r in main: lines.append('| '+' | '.join(str(r[k]) for k in ('namespace','command','mode','batch','atomic','threshold','headline','post','delta'))+' |')
(OUT/'main-comparison.md').write_text('\n'.join(lines)+'\n')
print('EXEC delta range',min(r['delta_after'] for r in rows),max(r['delta_after'] for r in rows))
for cmd in ('GET','SET','INCR','MGET','MSET'):
 d=[r['delta'] for r in main if r['command']==cmd];print(cmd,len(d),min(d),max(d))
