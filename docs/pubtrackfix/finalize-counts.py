#!/usr/bin/env python3
"""Bind refreshed POST counts to retained PRE receipts and production inputs."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/pubtrackfix';PC=DOC/'instructions-pc'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,indent=2)+'\n')
pairs=[]
for kind in ('commands','local'):
 pre=json.loads((PC/(kind+'-results-pre.json')).read_text())
 post=json.loads((PC/(kind+'-results-post.json')).read_text())
 for arm, records in (('pre',pre),('post',post)):
  for row in records:
   build=json.loads((DOC/'instructions'/(arm+'-'+row['namespace']+'-build.json')).read_text())
   assert row['probe_sha256']==build['sha256'], (arm,row['namespace'],'stale probe counts')
 keys=('namespace','command','mode','batch','atomic','threshold')
 rows=[]
 for new in post:
  old=next(r for r in pre if all(r[k]==new[k] for k in keys))
  rows.append({k:new[k] for k in keys}|dict(pre=old['total'],post=new['total'],delta=new['total']-old['total'],functions_equal=old['functions']==new['functions']))
 save(PC/(kind+'-results-pre,post.json'),pre+post)
 save(PC/(kind+'-comparison.json'),rows);pairs+=rows
assert len(pairs)==52 and all(r['delta']==0 and r['functions_equal'] for r in pairs),pairs
path=DOC/'instructions-production-binding.json';binding=json.loads(path.read_text())
binding['post_sha256']=sha(ROOT/'build/tomokv')
for ns in ('normal','db0'):
 build=json.loads((DOC/'instructions'/('post-'+ns+'-build.json')).read_text())
 binding['probes'][ns]={'probe_sha256':build['sha256'],'inputs':[{'path':p,'sha256':sha(p)} for p in build['link'] if p.endswith('.o')]}
save(path,binding)
print('52 zero-delta comparisons bound to',binding['post_sha256'])
