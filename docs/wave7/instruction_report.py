#!/usr/bin/env python3
"""Summarize exact linked production instruction traces; no elapsed-time claims."""
from collections import Counter
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'docs/wave7/instructions'
pre=json.load(open(OUT/'results-pre.json'));post=json.load(open(OUT/'results-post.json'))
keys=('namespace','command','mode','batch','atomic','threshold')
index={tuple(r[k] for k in keys):r for r in pre};rows=[]
for r in post:
 before=index[tuple(r[k] for k in keys)]
 old,new=Counter(before['functions']),Counter(r['functions'])
 delta={n:new[n]-old[n] for n in new.keys()|old.keys() if new[n]!=old[n]}
 oldlibs,newlibs=Counter(before['excluded']),Counter(r['excluded'])
 def external(c):return Counter({n:v for n,v in c.items() if 'CoreConcurrencyTest::' not in n})
 assert external(oldlibs)==external(newlibs), ('external library call footprint changed',r)
 rows.append({k:r[k] for k in keys}|dict(pre=before['total'],post=r['total'],delta=r['total']-before['total'],
  pre_per_command=before['total']/r['batch'],post_per_command=r['total']/r['batch'],
  function_delta=delta,library_call_delta={n:newlibs[n]-oldlibs[n] for n in newlibs.keys()|oldlibs.keys() if newlibs[n]!=oldlibs[n]},
  post_watch_functions={n:c for n,c in new.items() if 'watch' in n.lower()},
  external_library_call_counts_equal=True))
assert len(rows)==80 and sum(r['command'] in ('GET','SET','INCR') for r in rows)==48
assert all(r['delta']<=0 for r in rows if r['command'] in ('GET','SET','INCR'))
(OUT/'comparison.json').write_text(json.dumps(rows,indent=2)+'\n')
lines=['# Serverless command-scope instruction counts','','Exact named TomoKV instructions per batch; setup, verification and external library bodies excluded. Divide by batch for per-command counts (also stored in comparison.json). Every cell verifies its exact reply and resulting data. Read-local, FLIP, balancing and maxmemory are off. Plain commands use the production executor entry; multi-key commands use the production eight-shard scatter chain with group completion and retirement. The eight-command scatter batch repeats completed groups, not an overlapped parser pipeline. Clock reads return deterministic timestamps to keep debugger pauses out of slowlog selection. These counts do not measure throughput, cycles, IPC, parsing, network or queueing.','','Each cell is PRE → POST (difference). Runtime normal uses 16 databases; db0 uses the single-database compile.','','| Command | Batch | Slowlog µs | normal 1s | normal 2s | db0 1s | db0 2s |','|---|---:|---:|---:|---:|---:|---:|']
def cell(cmd,batch,atomic,threshold,ns,mode):
 r=next(r for r in rows if tuple(r[k] for k in keys)==(ns,cmd,mode,batch,atomic,threshold))
 return f"{r['pre']} → {r['post']} ({r['delta']:+})"
for cmd in ('GET','SET','INCR'):
 for batch in (1,32):
  for slow in (-1,10000):
   lines.append('| '+ ' | '.join([cmd,str(batch),str(slow),*[cell(cmd,batch,1,slow,ns,mode) for ns in ('normal','db0') for mode in ('1s','2s')]])+' |')
lines+=['','All 48 plain cells add zero instructions. The unarmed SET body is identical to headline and no WATCH callback or key lookup executes on these no-watcher paths.','','| Command, 8 keys | Batch | Atomic | normal 1s | normal 2s | db0 1s | db0 2s |','|---|---:|---:|---:|---:|---:|---:|']
for cmd in ('MGET','MSET'):
 for batch in (1,8):
  for atomic in (0,1):
   lines.append('| '+' | '.join([cmd,str(batch),str(atomic),*[cell(cmd,batch,atomic,-1,ns,mode) for ns in ('normal','db0') for mode in ('1s','2s')]])+' |')
lines+=['','Per-function and excluded library-call changes are retained in comparison.json. External library call counts match in all 80 cells; the retained raw excluded-target differences are only the fixture callback's PRE/POST path names. There is no assertion that equal named instruction totals imply equal cycles or rate.']
(OUT/'table.md').write_text('\n'.join(lines)+'\n')
for r in rows:
 if r['command']=='MSET' and r['batch']==1:print(r['namespace'],r['mode'],r['atomic'],r['delta'],r['function_delta'])
