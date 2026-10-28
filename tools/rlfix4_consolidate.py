#!/usr/bin/env python3
"""Fail-closed final census: use current hash-bound cases, never stale aggregates."""
import csv,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];DOC=ROOT/'docs/rlfix4';INS=DOC/'instructions'
FIELDS=('arm','namespace','command','mode','batch','atomic','threshold','route')
load=lambda p:json.loads(p.read_text())
save=lambda p,v:p.write_text(json.dumps(v,indent=2)+'\n')
cases=[]
for a in ('anchor','wave6','wave7'):
 cases+=load(INS/f'results-{a}-local.json')
cases += [r for r in load(INS/'results-anchor,wave6,wave7,preparse,post,pad-a,post-layout-parser.json') if r['arm'] in ('anchor','wave6','wave7','preparse')]
cases += [r for r in load(INS/'results-pre,post,pad-a,post-layout-all.json') if r['arm']=='pre']
for suite in ('all','parser'):
 cases+=load(INS/f'results-post-{suite}.json')+load(INS/f'results-pad-a,post-layout-{suite}.json')
cases += [r for r in load(INS/'results-admission-pre,post.json') if r['arm']=='admission-pre']
cases += load(INS/'results-admission-post.json')+load(INS/'results-admission-pad-a,post-layout.json')
rows=[]
for case in cases:
 arm=case['arm'];name='-'.join(str(case[f]) for f in FIELDS)
 trace=load(INS/(name+'.json'));build=load(INS/f'{arm}-{case["namespace"]}-build.json')
 assert trace['binary_sha256']==build['sha256'],name
 assert trace['total']==sum(trace['functions'].values())==sum(trace['bodies'].values()),name
 row={f:case[f] for f in FIELDS};row.update(trace,trace_file='instructions/'+name+'.json')
 if row['arm']=='preparse':row['arm']='pre'
 rows.append(row)
key=lambda r:tuple(r[f] for f in FIELDS[1:])
by={a:{key(r):r for r in rows if r['arm']==a} for a in {r['arm'] for r in rows}}
assert len(by['post'])==132 and len(by['admission-post'])==96
deltas=[];twins=[];transitions=[]
for family in ('','admission-'):
 for k,post in by[family+'post'].items():
  pre=by[family+'pre'][k];delta=post['total']-pre['total'];assert delta<=0,(family,k,delta)
  deltas.append(dict(family=family or 'execution/parser',case=k,pre=pre['total'],post=post['total'],delta=delta))
 for left,right in [('pre','pad-a'),('post','post-layout')]:
  for k,reference in by[family+left].items():
   actual=by[family+right][k]
   assert reference['total']==actual['total'] and reference['functions']==actual['functions'],(family,left,right,k)
   twins.append(dict(family=family or 'execution/parser',reference=left,arm=right,case=k,total=actual['total'],equal_function_counts=True))
for left,right in [('anchor','wave6'),('wave6','wave7'),('wave7','pre'),('pre','post')]:
 for k in sorted(by[left].keys()&by[right].keys()):
  a,b=by[left][k],by[right][k]
  fs={f:b['functions'].get(f,0)-a['functions'].get(f,0) for f in a['functions'].keys()|b['functions'].keys()};fs={f:v for f,v in fs.items() if v}
  assert sum(fs.values())==b['total']-a['total']
  transitions.append(dict(before=left,after=right,case=k,delta=sum(fs.values()),functions=fs))
save(DOC/'final-counts.json',rows);save(DOC/'final-deltas.json',deltas);save(DOC/'function-deltas.json',transitions);save(DOC/'layout/counts.json',twins)
with (DOC/'final-counts.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=list(FIELDS)+['total','binary_sha256','trace_file'],extrasaction='ignore');w.writeheader();w.writerows(rows)
arms={a:dict(path='build/tomokv-rlfix4-'+a,sha256=hashlib.sha256((ROOT/('build/tomokv-rlfix4-'+a)).read_bytes()).hexdigest(),bytes=(ROOT/('build/tomokv-rlfix4-'+a)).stat().st_size) for a in ('pre','post','pad-a','post-layout')}
save(DOC/'final-arms.json',arms)
print(len(rows),'hash-bound traces;',len(deltas),'nonincreasing PRE/POST cases;',len(twins),'exact twin cases')
