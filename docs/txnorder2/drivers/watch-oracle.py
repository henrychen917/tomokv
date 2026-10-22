#!/usr/bin/env python3
import importlib.util
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('runtime',Path(__file__).with_name('runtime.py'))
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
r.POST=ROOT/'build/tomokv'
out=ROOT/'docs/txnorder2/watch-oracle-final';out.mkdir(parents=True,exist_ok=True)
rows=[]
arms=[('redis74',Path('/home/user/Projects/redis74/src/redis-server'),'oracle',16,'epoll')]
arms += [(arm,binary,mode,db,engine) for arm,binary in [('pre',r.PRE),('post',r.POST)]
         for mode in ['1s','2s'] for db in [1,16] for engine in ['uring','epoll']]
for arm,binary,mode,db,engine in arms:
    label=f'{arm}-{mode}-db{db}-{engine}';directory=ROOT/'build/txnorder2/watch-oracle'/label
    directory.mkdir(parents=True,exist_ok=True);oracle=arm=='redis74';port=27893 if oracle else 27892
    argv=['taskset','-c','84' if oracle else '72-79',str(binary),'--bind','127.0.0.1',
          '--port',str(port),'--save','','--appendonly','no','--dir',str(directory),'--databases',str(db)]
    if not oracle:argv+=['--thread-mode',mode,'--net-io',engine,'--shards','16','--ratio','6:2',
                        '--key-lb','0','--client-lb','0','--flip-auto','0','--read-local','1' if mode=='1s' else '0']
    if mode=='1s':
        i=argv.index('--ratio');del argv[i:i+2]
    row=dict(label=label,server=argv,sha256=r.digest(binary));server=None
    try:
        with open(out/(label+'-server.log'),'w') as log:
            server=subprocess.Popen(argv,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            r.ready(port,server)
            row['cases']={}
            for case in ['flush','serve']:
                cmd=['taskset','-c','85-95','python3','tests/txnorder_watch.py','127.0.0.1',str(port),
                     '--databases',str(db),'--only',case]
                with open(out/(label+'-'+case+'.log'),'w') as f:
                    rc=subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=90).returncode
                row['cases'][case]={'command':cmd,'exit_code':rc}
    except Exception as exc:row['error']=repr(exc)
    finally:r.stop(server)
    rows.append(row);(out/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(label,row.get('cases',row.get('error')),flush=True)
