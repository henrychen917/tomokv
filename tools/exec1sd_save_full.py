#!/usr/bin/env python3
"""Replay the original complete split-0 seed plan, observing SAVE's actual result."""
import argparse, fcntl, json, os, re, signal, subprocess, threading, time
from pathlib import Path
import exec1sd as d

def main():
    assert os.sched_getaffinity(0)<=set(range(64,96))
    p=argparse.ArgumentParser();p.add_argument('arm');p.add_argument('--native',action='store_true');p.add_argument('--busy-only',action='store_true');p.add_argument('--label',default='');a=p.parse_args()
    assert not (a.native and a.busy_only)
    port_lock=(d.OUT/'save-native-ports.lock').open('w')
    fcntl.flock(port_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    arm=next(r for r in json.loads((d.DOCS/'arms.json').read_text()) if r['arm']==a.arm)
    assert d.sha(arm['binary'])==arm['sha256']
    label=('save-full-native-' if a.native else 'save-full-busy-only-' if a.busy_only else 'save-full-traceable-')+a.arm+a.label
    out=d.OUT/label;out.mkdir(exist_ok=False)
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
    busy_sites=[]
    if a.busy_only:
        # Stop only after SnapshotManager already returned Busy. No accepted
        # admission executes a breakpoint; this avoids the entry/finish
        # observer's delays before the placement-admission decision.
        source=subprocess.check_output(['git','show',arm['source_commit']+':src/cmd/t_server.cc'],text=True)
        lines=source.splitlines()
        busy_line=next(i+2 for i,line in enumerate(lines)
            if 'if (result == SnapshotManager::StartResult::Busy)' in line)
        assert 'Background save already in progress' in lines[busy_line-1]
        # GCC assigns the source line to the non-Busy fallthrough. Resolve
        # the taken Busy branch from each frozen symbol instead of setting a
        # misleading line breakpoint that would stop on successful admissions.
        for namespace in ('4tomo','8tomo_db0'):
            symbol='_ZN'+namespace+'12_GLOBAL__N_116snapshot_commandERNS_2OpEb'
            assembly=subprocess.check_output(['objdump','-d','--disassemble='+symbol,arm['binary']],text=True)
            (out/(namespace+'-snapshot-command.asm')).write_text(assembly)
            start=int(re.search(r'^([0-9a-f]+) <'+re.escape(symbol)+r'>:',assembly,re.M)[1],16)
            ins=[]
            for line in assembly.splitlines():
                parts=line.split('\t')
                if len(parts)>=3 and re.fullmatch(r'[0-9a-f]+:',parts[0].strip()):
                    ins.append((int(parts[0].strip()[:-1],16),parts[-1].strip()))
            index=next(i for i,(_,text) in enumerate(ins) if re.fullmatch(r'cmp\s+\$0x1,%al',text))
            assert 'SnapshotManager5start' in ins[index-2][1]
            destination=int(re.match(r'je\s+([0-9a-f]+)',ins[index+1][1])[1],16)
            busy_sites.append(dict(symbol=symbol,offset=destination-start,elf_address=destination,
                assembly_sha256=d.sha(out/(namespace+'-snapshot-command.asm'))))
        observer.write_text("""set pagination off
set confirm off
set print thread-events off
set debuginfod enabled off
handle SIGPIPE nostop noprint pass
handle SIGTERM nostop noprint pass
python
import gdb,json
class Busy(gdb.Breakpoint):
 def stop(self):
  frame=gdb.newest_frame();errors=[];message=None
  while frame:
   try:
    value=frame.read_var('error')
    message=value['_M_dataplus']['_M_p'].string()
    break
   except Exception as error:errors.append(str(error));frame=frame.older()
  print('SAVE_BUSY_RESULT '+json.dumps(dict(error=message,
    variable_errors=errors if message is None else [],
    backtrace=gdb.execute('bt 8',to_string=True))),flush=True)
  return False
sites="""+repr(busy_sites)+"""
points=[Busy('*'+hex(int(gdb.parse_and_eval('&'+site['symbol']))+site['offset']),internal=True) for site in sites]
print('SAVE_BUSY_OBSERVER_ARMED '+json.dumps(dict(locations=sum(len(point.locations) for point in points))),flush=True)
end
continue
thread apply all bt
""")
    env=dict(os.environ,REDIS74_ROOT='/home/user/Projects/redis',GATE_DIFFER_OUT=str(out/'differ'),
        GATE_DIFFER_NET_IO='epoll',GATE_DIFFER_GEOMETRY='split',GATE_DIFFER_PART='split-0',
        GATE_DIFFER_PLAN=str(d.DOCS/'epoll-seed22-plan.json'),GATE_LOAD_CORES='80-95',
        GATE_DIFFER_ORACLE_CORES='72-79')
    if a.native:
        cmd=['taskset','-c',d.CPUS,'tests/differ_gate.sh',arm['binary'],'20000','20001','64-71','6:2']
        with (out/'run.log').open('w') as stream:
            result=subprocess.run(cmd,env=env,stdout=stream,stderr=subprocess.STDOUT)
        d.save(d.DOCS/(label+'.json'),dict(arm=arm,command=cmd,returncode=result.returncode,
            plan_sha256=d.sha(d.DOCS/'epoll-seed22-plan.json'),log=str(out/'run.log'),
            log_sha256=d.sha(out/'run.log'),observer=False))
        print(a.arm,'native full split-0 plan exit',result.returncode,flush=True)
        return
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
    busy_rows=[json.loads(line[len('SAVE_BUSY_RESULT '):]) for line in log.splitlines()
               if line.startswith('SAVE_BUSY_RESULT ')]
    armed=[json.loads(line[len('SAVE_BUSY_OBSERVER_ARMED '):]) for line in log.splitlines()
           if line.startswith('SAVE_BUSY_OBSERVER_ARMED ')]
    assert not a.busy_only or (len(armed)==1 and armed[0]['locations']>0), log
    assert d.sha(arm['binary'])==arm['sha256']
    d.save(d.DOCS/(label+'.json'),dict(arm=arm,command=cmd,returncode=result.returncode,
        observer_kind='Busy reply only' if a.busy_only else 'Every admission entry and return',
        busy_results=busy_rows,armed=armed,busy_sites=busy_sites,
        plan_sha256=d.sha(d.DOCS/'epoll-seed22-plan.json'),observer_sha256=d.sha(observer),
        target_log=str(logfile),target_log_sha256=d.sha(logfile),results=rows,
        observer_errors=[line for line in log.splitlines() if line.startswith('SAVE_OBSERVER_ERROR ')]))
    print(a.arm,'full split-0 plan exit',result.returncode,rows,flush=True)

if __name__=='__main__':main()
