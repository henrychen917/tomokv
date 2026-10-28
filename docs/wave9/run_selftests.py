#!/usr/bin/env python3
import hashlib,json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];os.chdir(ROOT)
while not all(Path('docs/wave9/jobs/'+n+'.json').exists() for n in ('atomic-recheck2','final-persistence-1s')):time.sleep(10)
os.sched_setaffinity(0,set(range(88,96)))
with open('docs/wave9/gates-test-final.log','w') as f:
 r=subprocess.run(['python3','tests/gates_test.py'],env=dict(os.environ,GATE_TEST_PORT='20098'),stdout=f,stderr=subprocess.STDOUT)
Path('docs/wave9/gates-test-final.json').write_text(json.dumps(dict(argv=['taskset','-c','88-95','python3','tests/gates_test.py'],exit=r.returncode,source_sha256=hashlib.sha256(Path('tests/gates_test.py').read_bytes()).hexdigest()),indent=2)+'\n')
r=subprocess.run(['python3','docs/wave9/run_jobs.py','final-selftest','abba_selftest','--root','build/wave9/selftest-source','--single-slot','--server-start','88','--port','20080','--load-cores','64-71'])
raise SystemExit(r.returncode)
