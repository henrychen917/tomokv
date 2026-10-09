import json, os, signal, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path('tests').resolve()))
from _lib import Conn, wait_ready
from _differ_aclkeys import wait_blocked
root=Path('build/aclkeys4/debug-state'); root.mkdir(exist_ok=True)
for label,arming in [('alone',[]),('swap',[['SWAPDB',0,1]])]:
    d=root/label; d.mkdir(exist_ok=True)
    log=(d/'gdb.log').open('w')
    argv=['taskset','-c','112-119','gdb','-q','-batch','-x','build/aclkeys4/state.gdb','--args',str(Path('build/aclkeys4/aclkeys3-original').resolve()),'--port','18340','--bind','127.0.0.1','--shards','16','--ratio','6:2','--databases','16','--atomic','0','--save','','--dir',str(d.resolve()),'--enable-debug-command','yes']
    child=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT)
    pid=None; a=w=None
    try:
        a=wait_ready('127.0.0.1',18340,timeout=20)
        info=a.cmd('INFO','SERVER'); pid=int(next(x.split(b':')[1] for x in info.splitlines() if x.startswith(b'process_id:')))
        row={'pid':pid,'boot_shards':a.cmd('DEBUG','SHARDS','block:aclkeys'),'boot_topology':a.cmd('DEBUG','LBSIGNALS').decode()}
        for cmd in arming: assert a.cmd(*cmd)==b'OK'
        w=Conn('127.0.0.1',18340,timeout=2,buffering=0)
        row['config']={x:repr(a.cmd('CONFIG','GET',x)) for x in ('notify-keyspace-events','timeout','maxmemory')}
        row['before_shards']=a.cmd('DEBUG','SHARDS','block:aclkeys')
        a.cmd('DEL','block:aclkeys'); ident=w.cmd('CLIENT','ID'); w.send('XREAD','BLOCK',0,'STREAMS','block:aclkeys',0)
        wait_blocked(a,(w.sock,w.file),ident,lambda c,args:c.cmd(*args),lambda v:v,lambda f:w.read(),timeout=2)
        deadline=time.monotonic()+2
        while b'blocking_waiters:1\r\n' not in a.cmd('INFO'):
            assert time.monotonic()<deadline
        row['before_clients']=a.cmd('CLIENT','LIST').decode()
        row['xadd']=repr(a.cmd('XADD','block:aclkeys','1-0','field','value'))
        try: row['wake']=repr(w.read())
        except TimeoutError: row['wake']='TIMEOUT'
        row['after_clients']=a.cmd('CLIENT','LIST').decode()
        row['after_topology']=a.cmd('DEBUG','LBSIGNALS').decode()
        row['after_info']=a.cmd('INFO').decode()
        (d/'state.json').write_text(json.dumps(row,indent=2)+'\n')
        print(label,row['wake'],flush=True)
    finally:
        if w:w.close()
        if a:a.close()
        if pid:os.kill(pid,signal.SIGTERM)
        else:child.terminate()
        child.wait(timeout=20);log.close()
