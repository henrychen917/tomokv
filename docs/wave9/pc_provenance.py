#!/usr/bin/env python3
"""Bound every executed EXEC PC to debug source; verify repeated totals exactly."""
import gzip,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'docs/wave9/instructions-pc'
rows=json.loads((OUT/'exec-results-pre,post.json').read_text())
checks=[]
for row in rows:
 label='-'.join(str(row[k]) for k in ('arm','namespace','command','mode','batch','atomic','threshold'))
 old=json.loads((ROOT/'docs/wave9/instructions'/(label+'.json')).read_text())
 assert all(row[k]==old[k] for k in ('total','functions','probe_sha256','steps','clock_calls','excluded_calls')),label
 checks.append(dict(case=label,exact_repeat=True,pc_total=sum(n for _,n in row['pc_counts']),total=row['total']))
 assert checks[-1]['pc_total']==row['total']
for arm in ('pre','post'):
 for ns in ('normal','db0'):
  selected=[r for r in rows if r['arm']==arm and r['namespace']==ns]
  addresses=sorted({pc for r in selected for pc,n in r['pc_counts']},key=lambda s:int(s,16))
  binary=ROOT/'build/wave9/commands'/(arm+'-'+ns)/'probe'
  result=subprocess.check_output(['addr2line','-a','-f','-C','-i','-e',str(binary)],input='\n'.join(addresses)+'\n',text=True)
  sources={};pc=None
  for line in result.splitlines():
   if line.startswith('0x') and len(line)==18:
    pc=format(int(line,16),'x');sources[pc]=[]
   else:sources[pc].append(line.replace(str(ROOT)+'/', ''))
  assert set(sources)==set(addresses)
  with gzip.open(OUT/(arm+'-'+ns+'-source.json.gz'),'wt') as f:json.dump(sources,f)
with gzip.open(OUT/'executed-pcs.json.gz','wt') as f:json.dump(rows,f)
(OUT/'exact-repeat.json').write_text(json.dumps(checks,indent=2)+'\n')
# Keep compressed evidence; duplicate full per-cell step outputs are superseded.
for p in OUT.glob('*.json'):
 if p.name not in ('exact-repeat.json','exec-comparison.json'):p.unlink()
for p in OUT.glob('*.log'):p.unlink()
print(len(checks),'PC traces exactly reproduce frozen totals')
