#!/usr/bin/env python3
"""Replay the original complete split-0 seed plan, observing SAVE's actual result."""
import argparse, json, os, signal, subprocess, threading, time
from pathlib import Path
import exec1sd as d

def main():
    assert os.sched_getaffinity(0)<=set(range(64,96))
    p=argparse.ArgumentParser();p.add_argument('arm');a=p.parse_args()
    arm=next(r for r in json.loads((d.DOCS/'arms.json').read_text()) if r['arm']==a.arm)
    out=d.OUT/('save-full-traceable-'+a.arm);out.mkdir(exist_ok=False)
    observer=out/'observe.gdb'
    observer.write_text('''set pagination off
set confirm off
set print thread-events off
set debuginfod enabled off
handle SIGPIPE nostop noprint pass
handle SIGTERM nostop noprint pass
python
import gdb,json
class Result(gdb.FinishBreakpoint):
 def __init__(self):
  self.error=gdb.parse_and_eval('error').address
  super().__init__(gdb.newest_frame(),internal=True)
 def stop(self):
  try:
   value=int(self.return_value)
   message=self.error.dereference()['_M_dataplus']['_M_p'].string()
   print('SAVE_RESULT '+json.dumps(dict(result=value,error=message)),flush=True)
  except Exception as error:print('SAVE_OBSERVER_ERROR '+str(error),flush=True)
  return False
class Entry(gdb.Breakpoint):
 def stop(self):
  try:Result()
  except Exception as error:print('SAVE_OBSERVER_ERROR '+str(error),flush=True)
  return False
Entry('tomo::SnapshotManager::start',internal=True)
Entry('tomo_db0::SnapshotManager::start',internal=True)
end
continue
thread apply all bt
''')
    env=dict(os.environ,REDIS74_ROOT='/home/user/Projects/redis',GATE_DIFFER_OUT=str(out/'differ'),
        GATE_DIFFER_NET_IO='epoll',GATE_DIFFER_GEOMETRY='split',GATE_DIFFER_PART='split-0',
        GATE_DIFFER_PLAN=str(d.DOCS/'epoll-seed22-plan.json'),GATE_LOAD_CORES='80-95',
        GATE_DIFFER_ORACLE_CORES='72-79')
    # A sibling debugger needs process-local Yama consent. This exec shim keeps
    # the gate's owned PID and its listener checks intact; no system setting is
    # changed and the frozen server bytes are unmodified.
    launcher=out/'traceable-server';code=out/'traceable.c'
    code.write_text('#include <sys/prctl.h>\n#include <unistd.h>\nint main(int n,char**v){'
        'if(prctl(PR_SET_PTRACER,PR_SET_PTRACER_ANY,0,0,0))return 125;'
        'v[0]='+json.dumps(arm['binary'])+';execv(v[0],v);return 126;}\n')
    subprocess.run(['gcc','-O2',str(code),'-o',str(launcher)],check=True)
    cmd=['taskset','-c',d.CPUS,'tests/differ_gate.sh',str(launcher),'20000','20001','64-71','6:2']
    attached=[];finished=threading.Event()
    def attach():
        while not finished.wait(.02):
            for proc in Path('/proc').iterdir():
                if not proc.name.isdigit():continue
                try:args=(proc/'cmdline').read_bytes().split(b'\0')
                except (OSError,ProcessLookupError):continue
                if arm['binary'].encode() not in args or str(out/'differ/target-atomic-0').encode() not in args:continue
                with (out/'observer.log').open('w') as log:
                    attached.append(subprocess.Popen(['taskset','-c','80-95','gdb','-nx','-batch',
                        '-p',proc.name,'-x',str(observer)],stdout=log,stderr=subprocess.STDOUT))
                return
    thread=threading.Thread(target=attach);thread.start()
    try:
        with (out/'run.log').open('w') as f:result=subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT)
    finally:
        finished.set();thread.join()
        for process in attached:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.terminate();process.wait()
    logfile=out/'observer.log';log=logfile.read_text()
    rows=[json.loads(line[len('SAVE_RESULT '):]) for line in log.splitlines() if line.startswith('SAVE_RESULT ')]
    d.save(d.DOCS/('save-full-traceable-'+a.arm+'.json'),dict(arm=arm,command=cmd,returncode=result.returncode,
        plan_sha256=d.sha(d.DOCS/'epoll-seed22-plan.json'),observer_sha256=d.sha(observer),
        target_log=str(logfile),target_log_sha256=d.sha(logfile),results=rows,
        observer_errors=[line for line in log.splitlines() if line.startswith('SAVE_OBSERVER_ERROR ')]))
    print(a.arm,'full split-0 plan exit',result.returncode,rows,flush=True)

if __name__=='__main__':main()
