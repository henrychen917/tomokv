#!/usr/bin/env python3
"""Run existing sweep-hit batteries that have no gate job; never replace a row."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'build/wave4/supplemental'
DOC=ROOT/'docs/wave4/supplemental'
sys.path.insert(0,str(ROOT/'tests'))
from compat2_support import Client


@contextmanager
def owned(name,binary,cores,port,extra):
    directory=OUT/name;directory.mkdir(parents=True,exist_ok=False)
    assert not subprocess.check_output(['ss','-ltnH',f'sport = :{port}']).strip()
    argv=['taskset','-c',cores,str(binary),'--bind','127.0.0.1','--port',str(port),
          '--dir',str(directory),'--save','','--appendonly','no','--protected-mode','no',
          '--enable-debug-command','yes',*extra]
    (directory/'command.json').write_text(json.dumps(argv,indent=2)+'\n')
    with (directory/'server.log').open('w') as log:
        process=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT)
        (directory/'server.pid').write_text(str(process.pid)+'\n')
        try:
            deadline=time.monotonic()+15
            while True:
                assert process.poll() is None,(name,process.returncode)
                try:
                    with Client(port) as c:
                        if c.cmd('PING')==b'PONG':break
                except (OSError,EOFError):pass
                assert time.monotonic()<deadline,'boot did not complete'
                time.sleep(.05)
            yield
        finally:
            identity=subprocess.run(['ps','-p',str(process.pid),'-o','pid=,ppid=,lstart=,args='],capture_output=True,text=True)
            (directory/'pre-stop-ps.txt').write_text(identity.stdout)
            if process.poll() is None:
                assert str(process.pid) in identity.stdout
                assert Path(f'/proc/{process.pid}/exe').resolve()==Path(binary).resolve()
                process.terminate()
                try:process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait();raise AssertionError('owned server did not drain')
            assert process.returncode==0,(name,process.returncode)


def main():
    OUT.mkdir(parents=True,exist_ok=True);DOC.mkdir(parents=True,exist_ok=True)
    binary=ROOT/'build/tomokv';records=[]
    with owned('redis74',Path('/home/user/Projects/redis74/src/redis-server'),'104',26861,[]):
        for mode in ('1s','2s'):
            for engine in ('epoll','uring'):
                for atomic in (0,1):
                    name=f'{mode}-{engine}-a{atomic}'
                    shape=['--shards','16','--thread-mode',mode,'--net-io',engine,
                           '--atomic',str(atomic),'--read-local','1' if mode=='1s' else '0',
                           '--key-lb','0','--client-lb','0','--flip-auto','0','--databases','1']
                    if mode=='2s':shape+=['--ratio','6:2']
                    with owned(name,binary,'96-103',26860,shape):
                        for test,args in [('cmdgap2',[]),('dumpttl',['127.0.0.1','26861'])]+(
                                [('respresume_flip',[])] if mode=='2s' else []):
                            argv=['taskset','-c','105-111','python3','tests/'+test+'.py','127.0.0.1','26860',*args]
                            with (DOC/(name+'-'+test+'.log')).open('w') as stream:
                                rc=subprocess.run(argv,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT).returncode
                            records.append(dict(name=name,test=test,argv=argv,returncode=rc))
                            print(name,test,rc,flush=True)
    result=dict(binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),rows=records)
    (DOC/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    raise SystemExit(any(r['returncode'] for r in records))


if __name__=='__main__':main()
