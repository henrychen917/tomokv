#!/usr/bin/env python3
"""Run gate's complete EXEC job while four owned CPU burners share its slot."""
import json,os,signal,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
os.chdir(ROOT);os.sched_setaffinity(0,set(range(64,96)))
source=ROOT/'build/wave9/correctness-load.c';binary=source.with_suffix('')
source.write_text('#include <signal.h>\n#include <stdint.h>\nstatic volatile sig_atomic_t stop; static void done(int s){(void)s;stop=1;}\nint main(void){signal(SIGTERM,done);volatile uint64_t x=1;while(!stop)x=x*6364136223846793005ULL+1;return 0;}\n')
subprocess.run(['cc','-O2',str(source),'-o',str(binary)],check=True)
children=[];start=time.monotonic();ticks=os.sysconf('SC_CLK_TCK');receipt=dict(server_cores='88-95',load='four finite owned CPU burners, no traffic or rate measurement',processes=[])
try:
 for _ in range(4):children.append(subprocess.Popen(['taskset','-c','88-95',str(binary)]))
 result=subprocess.run(['python3','docs/wave9/run_jobs.py','execfair-loaded','execfair','--single-slot','--server-start','88','--port','20080'])
 receipt['gate_exit']=result.returncode
finally:
 for child in children:
  fields=Path(f'/proc/{child.pid}/stat').read_text().rsplit(')',1)[1].split()
  receipt['processes'].append(dict(pid=child.pid,cpu_seconds=(int(fields[11])+int(fields[12]))/ticks,affinity=sorted(os.sched_getaffinity(child.pid))))
  child.terminate()
 for child in children:child.wait(timeout=10)
 receipt['seconds']=time.monotonic()-start
 Path('docs/wave9/loaded-execfair.json').write_text(json.dumps(receipt,indent=2)+'\n')
assert receipt['gate_exit']==0,receipt
assert all(p['cpu_seconds']>1 for p in receipt['processes']),receipt
