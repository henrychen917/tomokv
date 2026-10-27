#!/usr/bin/env python3
"""Unchanged upstream SMOVE/WATCH reproduction on bounded fresh armed boots."""
import hashlib,json,os,sys
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'))
from redis_tcl import prepare,run_file
os.sched_setaffinity(0,set(range(32,48)))
case='SMOVE only notify dstset when the addition is successful'
rows=[]
for mode,binary in [('1s',ROOT/'build/multifix/tomokv-pre'),('2s',ROOT/'build/multifix/tomokv-pre'),
                    ('redis',Path('/home/user/Projects/redis74/src/redis-server'))]:
    folder=ROOT/'build/multifix/pre-watch-upstream'/mode
    assert not folder.exists(),'preserve previous attempts'
    args=SimpleNamespace(output=folder,port=20500,cores='32-39',binary=binary,mode=mode,
                         baseport=20502,idle_timeout=60,file_timeout=240,arm_smove=True,ratio='6:2')
    tree=folder/'checkout'
    prepare(Path('/home/user/Projects/redis'),tree,controller_port=20501)
    row=run_file(args,tree,'unit/type/set',only=[case])
    matching=[e for e in row['events'] if e['status'] in ('ok','err') and e['test'].split(' in tests/')[0]==case]
    assert len(matching)==1 and matching[0]['status']==('ok' if mode=='redis' else 'err'),(mode,matching)
    row['binary_sha256']=hashlib.sha256(binary.read_bytes()).hexdigest()
    rows.append(row)
    print(mode,matching[0]['status'],'boots',len(row['smove_layout_attempts']),flush=True)
(ROOT/'docs/multifix/pre-watch-upstream.json').write_text(json.dumps(rows,indent=2)+'\n')
