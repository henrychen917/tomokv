#!/usr/bin/env python3
"""Exact Redis replies behind CD4.15's changed historical assertions."""
import json, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'))
from _lib import Conn
from compat3_lib import wire
port=33890
with (ROOT/'build/datafix2-edgeenc-oracle.log').open('w') as log:
    server=subprocess.Popen(['taskset','-c','104','/home/user/Projects/redis74/src/redis-server',
        '--port',str(port),'--bind','127.0.0.1','--save','','--appendonly','no'],stdout=log,stderr=log)
    try:
        for _ in range(100):
            try: c=Conn('127.0.0.1',port,buffering=0);break
            except OSError: time.sleep(.03)
        else: raise AssertionError('oracle did not listen')
        for start in (190,191,192):
            for command in [('APPEND','k','AB'),('SETRANGE','k',start,'CD')]:
                c.cmd('SET','k','g'*start)
                reply=c.cmd(*command);encoding=c.cmd('OBJECT','ENCODING','k')
                assert encoding==b'raw',(start,command,encoding)
                print(json.dumps(dict(seed_length=start,command=command,reply=wire(reply),encoding=wire(encoding))))
        for command in [('APPEND','k','45'),('APPEND','k',''),('SETRANGE','k',1,'X')]:
            c.cmd('SET','k','123')
            reply=c.cmd(*command);encoding=c.cmd('OBJECT','ENCODING','k')
            assert encoding==b'raw',(command,encoding)
            print(json.dumps(dict(seed='123',command=command,reply=wire(reply),encoding=wire(encoding))))
        c.close()
    finally:
        server.terminate();server.wait(timeout=10)
