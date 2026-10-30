#!/usr/bin/env python3
"""Repeat the unchanged seed-22 psfix leg and observe native SAVE refusal branches."""
import argparse, json, os, signal, socket, subprocess, time
from pathlib import Path
import exec1sd as d

def ready(port, proc):
    until=time.monotonic()+30
    while time.monotonic()<until:
        assert proc.poll() is None, ('boot exited',proc.returncode)
        try:
            with socket.create_connection(('127.0.0.1',port),.2) as s:
                s.sendall(b'*1\r\n$4\r\nPING\r\n')
                if s.recv(128)==b'+PONG\r\n':return
        except OSError:pass
        time.sleep(.05)
    raise RuntimeError('boot timed out')

def stop(proc):
    if proc.poll() is None:
        os.killpg(proc.pid,signal.SIGTERM)
        try:proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL);proc.wait()

def main():
    assert os.sched_getaffinity(0)<=set(range(64,96))
    p=argparse.ArgumentParser();p.add_argument('arm',choices=['C-PRE','MERGE','POST']);p.add_argument('--repeats',type=int,default=64);a=p.parse_args()
    arms=json.loads((d.DOCS/'arms.json').read_text());arm=next(r for r in arms if r['arm']==a.arm)
    out=d.OUT/('save-observed-'+a.arm);out.mkdir(exist_ok=False)
    (out/'target').mkdir();(out/'oracle').mkdir()
    binary=Path(arm['binary']);assert d.sha(binary)==arm['sha256']
    source=subprocess.check_output(['git','show',arm['source_commit']+':src/snapshot/snapshot.cc'],text=True)
    points=[]
    for line,text in enumerate(source.splitlines(),1):
        for label in ('placement transition is in progress','Background save already in progress','previous shutdown snapshot is still draining'):
            if 'error = "'+label+'"' in text:points.append((line,label))
    script=out/'observe.gdb'
    script.write_text('set pagination off\nset confirm off\nset print thread-events off\nset breakpoint pending on\n'
        'handle SIGPIPE nostop noprint pass\npython\nimport gdb,json\n'
        'class Refusal(gdb.Breakpoint):\n'
        ' def __init__(self,line,label):\n'
        '  super().__init__("snapshot.cc:"+str(line));self.label=label\n'
        ' def stop(self):\n'
        '  fields={"reason":self.label}\n'
        '  for name in ("server.lb_stage_", "server.flip_stage_", "phase_"):\n'
        '   try:fields[name]=str(gdb.parse_and_eval(name))\n'
        '   except gdb.error:pass\n'
        '  print("SAVE_ADMISSION "+json.dumps(fields),flush=True);return False\n'
        f'for line,label in {points!r}:Refusal(line,label)\nend\nrun\n')
    target=['taskset','-c','64-71','gdb','-nx','-batch','-x',str(script),'--args',str(binary),
        '--port','20000','--bind','127.0.0.1','--shards','16','--ratio','6:2','--net-io','epoll',
        '--databases','16','--atomic','0','--save','','--dir',str(out/'target'),'--enable-debug-command','yes']
    oracle=['taskset','-c','72-79','/home/user/Projects/redis/src/redis-server','--port','20001',
        '--bind','127.0.0.1','--save','','--appendonly','no','--dir',str(out/'oracle')]
    results=[];processes=[]
    try:
        for label,cmd,port in (('oracle',oracle,20001),('target',target,20000)):
            with (out/(label+'.log')).open('w') as log:
                proc=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            processes.append(proc);ready(port,proc)
        for i in range(a.repeats):
            path=out/(f'psfix-a0-s22-repeat-{i:03}.log')
            with path.open('w') as log:
                result=subprocess.run(['taskset','-c','80-95','python3','tests/differ.py',
                    '127.0.0.1','20000','127.0.0.1','20001','psfix','22'],stdout=log,stderr=subprocess.STDOUT,timeout=180)
            results.append(dict(repeat=i,returncode=result.returncode,log=str(path),sha256=d.sha(path)))
            print(a.arm,i,result.returncode,flush=True)
            if result.returncode:break
    finally:
        for proc in reversed(processes):stop(proc)
        log=(out/'target.log').read_text()
        d.save(d.DOCS/('save-observed-'+a.arm+'.json'),dict(arm=arm,commands=[target,oracle],
            seed=22,suite='psfix',mode='2s',engine='epoll',atomic=0,results=results,
            admissions=[line for line in log.splitlines() if line.startswith('SAVE_ADMISSION ')],
            observer_sha256=d.sha(script),server_log_sha256=d.sha(out/'target.log')))

if __name__=='__main__':main()
