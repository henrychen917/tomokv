#!/usr/bin/env python3
"""Summarize named gate witnesses without converting a failed run into a pass."""
import argparse,json,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/pubtrackfix'
PROMOTED=json.loads((DOC/'tcl-promotions.json').read_text())['removed_from_known_failures']
ROOTS=('TRACK-BCAST-BATCH','PUBSUB-REPLY-OFF-PUSH','PUBSUB-IMPLICIT-CONSUMER-EVENT','PUBSUB-EVICT-ON-MAXMEMORY')
WITNESS={'bcast':('unit/tracking','The connection gets invalidation messages about all the keys'),
 'reply-off':('unit/pubsub','PubSub messages with CLIENT REPLY OFF'),
 'consumer':('unit/pubsub','Keyspace notifications: stream events test'),
 'eviction':('unit/pubsub','Keyspace notifications: evicted events')}
def main():
 p=argparse.ArgumentParser();p.add_argument('--partial',action='store_true');a=p.parse_args()
 names=['post-affected-final','differ-uring','differ-epoll','pre-directed','pad-directed']+['plant-'+x for x in WITNESS]
 out={};missing=[]
 for name in names:
  directory=DOC/'proof'/name
  if not (directory/'summary.json').exists():missing.append(name);continue
  saved=json.loads((directory/'summary.json').read_text())
  entry={'gate_summary':saved['summary'],'jobs':saved['jobs']}
  with tarfile.open(directory/'receipts.tar.gz','r:gz') as t:
   inventory=set(t.getnames())
   def read(path):return json.load(t.extractfile(path))
   if name.startswith('differ-'):
    parts={part:read(f'differ-{part}/differ/complete.json') for part in
     ('split-0','split-1','armed-0','armed-1','equivalence')}
    entry['differential']={'comparisons':sum(v['comparisons'] for v in parts.values()),
     'complete':all(v['complete'] for v in parts.values()),'parts':parts,
     'plan':json.loads((directory/'differ-plan.json').read_text())}
   if name.endswith('-directed') or name=='post-affected-final':
    rows={}
    for root in ROOTS:
     for arm in ('oracle','candidate'):
      path=f'pubtrackfix/{root}/{arm}/results.json'
      if path not in inventory:continue
      d=read(path);rows[root+' '+arm]={'sha256':d['sha256'],'legs':len(d['checks']),
       'passed':sum(c['passed'] for c in d['checks']),
       'failed_labels':[c['label'] for c in d['checks'] if not c['passed']]}
    entry['directed']=rows
    if name.endswith('-directed'):
     witnesses={}
     for root in ROOTS:
      d=read(f'pubtrackfix/{root}/candidate/results.json');verified=[]
      for c in d['checks']:
       w=read(f"pubtrackfix/{root}/candidate/{c['label']}-wire.json")
       if root=='TRACK-BCAST-BATCH':
        got=bytes.fromhex(w[-1].get('reply_hex',''));want=bytes.fromhex(w[-1].get('expected_hex',''))
        ok=got.startswith(b'>2\r\n$10\r\ninvalidate\r\n*1\r\n') and b'*3\r\n' in want
       elif root=='PUBSUB-REPLY-OFF-PUSH':
        ok=w==[{'send':[repr(x) for x in ('CLIENT','REPLY','OFF')]},
               {'send':[repr(x) for x in ('SUBSCRIBE','ch')]}]
       elif root=='PUBSUB-IMPLICIT-CONSUMER-EVENT':
        ok=w[-2].get('send')==[repr(x) for x in ('XREADGROUP','GROUP','g','Alice','STREAMS','s','>')] and bytes.fromhex(w[-1].get('reply_hex','')).startswith(b'*1\r\n*2\r\n$1\r\ns\r\n')
       else:
        ok=w[-2].get('send')==[repr(x) for x in ('CONFIG','SET','maxmemory',1)] and w[-1].get('reply_hex')==b'+OK\r\n'.hex()
       verified.append(ok and not c['passed'])
      log=t.extractfile(f'pubtrackfix/{root}.log').read().decode()
      bcast=root=='TRACK-BCAST-BATCH'
      witnesses[root]={'legs':len(verified),'wire_witnesses':sum(verified),
       'expected_exception':'AssertionError' if bcast else 'TimeoutError',
       'expected_exceptions':log.count('AssertionError:' if bcast else 'TimeoutError: timed out')}
     entry['negative_failure_witnesses']=witnesses
   if name=='post-affected-final' or name.startswith('plant-'):
    modes={}
    for mode in ('1s','2s'):
     path=f'redis_tcl/redis-tcl-{mode}/summary.json'
     if path not in inventory:continue
     d=read(path);rows={r['file']:r for r in d['rows']};passed=set()
     for r in d['rows']:
      passed.update((r['file'],e['data']) for e in r['events'] if e['status']=='ok')
     m={'sha256':d['binary_sha256'],'files':len(rows),'file_runs':len(d['rows']),
        'passed_assertions':sum(r['passed'] for r in d['rows']),
        'promoted_passed':sum(tuple(v) in passed for v in PROMOTED),
        'promoted_missing':[v for v in PROMOTED if tuple(v) not in passed]}
     if name.startswith('plant-'):
      unit,test=WITNESS[name.removeprefix('plant-')];r=rows[unit]
      started=any(e['status']=='testing' and e['data']==test for e in r['events'])
      last='';failures=[]
      for e in r['events']:
       if e['status']=='testing':last=e['data']
       if e['status'] in ('err','exception') and last==test:failures.append(e['data'])
      m['root_witness']={'file':unit,'test':test,'started':started,'passed':(unit,test) in passed,
       'file_complete':r['complete'],'file_error':r['error'],'failure_events':failures,
       'detected':started and (unit,test) not in passed and (bool(failures) or not r['complete'] or bool(r['error']))}
     modes[mode]=m
    entry['tcl']=modes
  out[name]=entry
 result={'runs':out,'missing_runs':missing}
 (DOC/'proof-summary.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({k:{'summary':v['gate_summary'],'promoted':{m:r['promoted_passed'] for m,r in v.get('tcl',{}).items()},
  'plants':{m:r.get('root_witness',{}).get('detected') for m,r in v.get('tcl',{}).items()}} for k,v in out.items()},indent=2))
 if missing and not a.partial:raise SystemExit('missing: '+', '.join(missing))
if __name__=='__main__':main()
