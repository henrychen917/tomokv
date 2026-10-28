#!/usr/bin/env python3
"""Check completeness and arm identity of the four implemented roots' receipts."""
import hashlib,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/pubtrackfix'
ARMS={
 'PRE':('build/pubtrackfix/pre/tomokv','0cac9819e46cfdcb7836fd04d5ab55ef9a49e92403b13212d9d3edea8427d16f'),
 'POST':('build/tomokv','faef9b9099cf0777685dd914571fda687ecc0f5c356191d11c02af6841f45b84'),
 'PAD-A':('build/pubtrackfix/pad-a/tomokv','f44826532e0afe1ddbc315ac1d8d7cd721e67983ac53ca119e76d91e6ad592f9')}
ORACLE='ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b'
ROOTS={'TRACK-BCAST-BATCH':32,'PUBSUB-REPLY-OFF-PUSH':32,
 'PUBSUB-IMPLICIT-CONSUMER-EVENT':32,'PUBSUB-EVICT-ON-MAXMEMORY':64}
def main():
 assert os.sched_getaffinity(0)<=set(range(32,48))
 checks=[];inputs={}
 def check(label,value):checks.append({'check':label,'passed':bool(value)})
 def read(path):
  data=(DOC/path).read_bytes();inputs[path]=hashlib.sha256(data).hexdigest()
  return json.loads(data)
 summary=read('proof-summary.json');runs=summary['runs']
 check('all nine proof runs present',not summary['missing_runs'] and len(runs)==9)
 driver=read('proof-driver-affected-differ-controls-gates-test.json')
 check('driver completed all nine cases',len(driver)==9)
 for row in driver:
  negative=row['name'].endswith('-directed') or row['name'].startswith('plant-')
  check(row['name']+' expected gate exit',(row['returncode']!=0)==negative)
 for arm,(path,digest) in ARMS.items():
  check(arm+' current binary SHA-256',hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest)
 for name,arm,positive in [('post-affected-final','POST',True),('pre-directed','PRE',False),('pad-directed','PAD-A',False)]:
  d=runs[name]['directed']
  for root,legs in ROOTS.items():
   candidate=d[root+' candidate'];oracle=d[root+' oracle']
   check(name+' '+root+' complete matrix',candidate['legs']==legs)
   check(name+' '+root+' expected verdict',candidate['passed']==(legs if positive else 0))
   check(name+' '+root+' binary binding',candidate['sha256']==ARMS[arm][1])
   oracle_legs=2 if legs==64 else 1
   check(name+' '+root+' oracle',oracle['legs']==oracle_legs and oracle['passed']==oracle_legs and oracle['sha256']==ORACLE)
 for name in ('pre-directed','pad-directed'):
  for root,legs in ROOTS.items():
   w=runs[name]['negative_failure_witnesses'][root]
   check(name+' '+root+' intended failure in every leg',w['legs']==legs and w['wire_witnesses']==legs and w['expected_exceptions']==legs)
 affected=runs['post-affected-final']
 done=[list(map(int,r['done'].split())) for r in affected['jobs'].values()]
 check('affected 36 jobs and 245 passing rows',len(done)==36 and sum(r[1] for r in done)==245)
 check('affected jobs all successful',all(r[0]==0 and r[2]==0 for r in done))
 check('Tcl has both modes',set(affected['tcl'])=={'1s','2s'})
 for mode,r in affected['tcl'].items():
  check('Tcl '+mode+' complete selected files',r['files']==35 and r['file_runs']==36)
  check('Tcl '+mode+' all 31 promoted names',r['promoted_passed']==31 and not r['promoted_missing'])
  check('Tcl '+mode+' POST binding',r['sha256']==ARMS['POST'][1])
 for engine in ('uring','epoll'):
  r=runs['differ-'+engine];d=r['differential']
  check(engine+' all 954 differential comparisons',d['complete'] and d['comparisons']==954)
  check(engine+' standard permanent seeds',d['plan']['manifest']['permanent']==[7,19,20,23])
  check(engine+' five differential parts',set(d['parts'])=={'split-0','split-1','armed-0','armed-1','equivalence'})
  check(engine+' gate jobs pass',all(v['done'].split()[0]=='0' and v['done'].split()[2]=='0' for v in r['jobs'].values()))
 plants=read('plants.json')
 check('plants built from POST',plants['post_sha256']==ARMS['POST'][1])
 check('four root-specific plants',set(plants['plants'])=={'bcast','reply-off','consumer','eviction'})
 for plant,details in plants['plants'].items():
  check(plant+' Tcl has both modes',set(runs['plant-'+plant]['tcl'])=={'1s','2s'})
  for mode,r in runs['plant-'+plant]['tcl'].items():
   check(plant+' '+mode+' exact promoted witness fails',r['root_witness']['detected'])
   check(plant+' '+mode+' planted binary binding',r['sha256']==details['sha256'])
 commands=read('instructions-pc/commands-comparison.json')
 local=read('instructions-pc/local-comparison.json')
 check('52 zero-instruction comparisons',len(commands)==48 and len(local)==4 and
  all(r['delta']==0 and r['functions_equal'] for r in commands+local))
 fresh=read('freshness.json')
 check('all 56 make-q queries pass',len(fresh['queries'])==56 and all(r['returncode']==0 for r in fresh['queries']))
 check('freshness POST binding',fresh['post_sha256']==ARMS['POST'][1])
 gates=read('gates-test-final.json')
 check('isolated gates_test passes',gates['returncode']==0 and gates['successful'])
 result={'scope':'Four implemented roots only; three owner-decision roots remain stopped.',
  'passed':all(c['passed'] for c in checks),'checks':checks,'input_sha256':inputs}
 (DOC/'proof-verification.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({'passed':result['passed'],'checks':len(checks),
  'failures':[c['check'] for c in checks if not c['passed']]},indent=2))
 return not result['passed']
if __name__=='__main__':raise SystemExit(main())
