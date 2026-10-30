#!/usr/bin/env python3
"""Replay the seven original, type-preserving harness5 scripts on fresh servers."""
import argparse, hashlib, importlib.util, json, sys
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('h5repro',ROOT/'docs/harness5/repro_tcl.py')
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
ROOTS=['TRACK-BCAST-BATCH','TRACK-INVALIDATE-BEFORE-REPLY','TRACK-MAXKEYS-IMMUTABLE','PUBSUB-SUBSCRIBE-NO-DENYOOM','PUBSUB-REPLY-OFF-PUSH','PUBSUB-IMPLICIT-CONSUMER-EVENT','PUBSUB-EVICT-ON-MAXMEMORY']
def main():
 p=argparse.ArgumentParser();p.add_argument('--binary',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 oracle=Path('/home/user/Projects/redis74/src/redis-server')
 cases=json.loads((ROOT/'docs/harness5/redis-tcl-repros.json').read_text())['cases']
 options=SimpleNamespace(port=20300,cores='32-39',ratio='6:2')
 out={'binary_sha256':hashlib.sha256(a.binary.read_bytes()).hexdigest(),'oracle_sha256':hashlib.sha256(oracle.read_bytes()).hexdigest(),'cases':{}}
 for root in ROOTS:
  c=cases[root];results={}
  for mode,engine in [('redis','oracle'),('2s','uring'),('1s','uring'),('2s','epoll'),('1s','epoll')]:
   name=mode+'-'+engine
   case=dict(c,server_args=c.get('server_args',[])+([] if mode=='redis' else ['--net-io',engine]))
   results[name]=h.play(case,mode,oracle if mode=='redis' else a.binary.resolve(),options,ROOT/'build/pubtrackfix/repro'/a.output.stem/root/name)
  def values(r):return [x.get('reply') for x in r['transcript'] if x.get('compare',True) and ('send' in x or 'read' in x or 'raw' in x)]
  verdict={k:'SAME' if values(v)==values(results['redis-oracle']) else 'DIFFERENT' for k,v in results.items() if k!='redis-oracle'}
  out['cases'][root]={'results':results,'verdict':verdict}
  a.output.write_text(json.dumps(out,indent=2)+'\n');print(root,verdict,flush=True)
if __name__=='__main__':main()
