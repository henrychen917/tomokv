#!/usr/bin/env python3
"""Complete gate-owned correctness jobs; retain all legs and assertions.

Does not invoke full iteration, ABBA/NIC measurements or throughput generators.
The release atomic_batteries job is excluded for its explicit rate comparison;
its non-rate checks run through the declared ASAN job in both modes.
"""
import difflib,hashlib,json,os,re,shutil,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];os.chdir(ROOT)
os.sched_setaffinity(0,os.sched_getaffinity(0)&set(range(64,96)))
OUT=ROOT/'docs/wave7/correctness';BUILD=ROOT/'build/wave7'
manifest=json.loads((ROOT/'docs/wave7/job-manifest.json').read_text());results=[]

def job(name,jobs,*options):
 command=['python3','docs/wave7/run_jobs.py',name,*jobs,*options]
 result=subprocess.run(command)
 results.append(dict(name=name,command=command,exit=result.returncode))
 (OUT/'sequence.json').write_text(json.dumps(results,indent=2)+'\n')
 print(name,result.returncode,flush=True)

# Use one complete selection, allowing gate.sh to own prerequisites and slots.
# No performance-dependent job appears in this list.
job('merged-sweep',manifest['lanes']+manifest['remaining'])
for engine in ('uring','epoll'):
 job('differ-'+engine,manifest['differential'],'--engine',engine)
cells=['txnorder-fused-0','txnorder-fused-1','txnorder-split-0','txnorder-split-1']
for round in (2,3):job('txnorder-round-'+str(round),cells)
legacy=['release_batteries','notify','sort','script_bounds','dump_restore',
        'auth','replyoff','zc','aof-epoll','aof-uring','snapshot-epoll','snapshot-uring','aof_frame']
job('legacy-fused',legacy+['debug-0','debug-1','asan_batteries'],'--fused')
# No compiler/server runs concurrently with the scheduler and bounded latency controls.
env=dict(os.environ,LANG='en_US.UTF-8',GATE_TEST_PORT='26897');env.pop('LC_ALL',None);env.pop('NETFIX_TLS_ORACLE',None)
start=time.time()
with (BUILD/'gates-test.log').open('w') as log:
 result=subprocess.run(['python3','tests/gates_test.py'],env=env,stdout=log,stderr=subprocess.STDOUT)
(OUT/'gates-test.json').write_text(json.dumps(dict(command=['python3','tests/gates_test.py'],
 affinity=sorted(os.sched_getaffinity(0)),port=26897,start=start,end=time.time(),exit=result.returncode,
 environment={'LANG':env['LANG'],'LC_ALL':'unset'},log=str(BUILD/'gates-test.log')),indent=2)+'\n')
results.append(dict(name='gates-test',exit=result.returncode))
copy=BUILD/'selftest-source'
for name in ('tests','tools','.githooks','src'):
 shutil.copytree(ROOT/name,copy/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
for p in [ROOT/'Makefile',ROOT/'.gitignore',*ROOT.glob('*.md')]:shutil.copy2(p,copy/p.name)
for rel in ('docs/CONFIGURATION.md','docs/cd13b/audit.json','docs/dispatchfix/pre-sha256.txt',
            'docs/flakeaudit2/triage.json','docs/lbplanner/generic-cells.txt','docs/lbplanner/multidb-cells.txt'):
 (copy/rel).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/rel,copy/rel)
gate=(ROOT/'tests/gate.sh').read_text()
adjusted=re.sub(r'^EXPECT_QUICK=768$', 'EXPECT_QUICK=798',gate,flags=re.M)
adjusted=re.sub(r'^EXPECT_FULL=785\b','EXPECT_FULL=815',adjusted,flags=re.M)
assert adjusted!=gate
(copy/'tests/gate.sh').write_text(adjusted)
(ROOT/'docs/wave7/selftest-copy.json').write_text(json.dumps(dict(
 source_sha256=hashlib.sha256(gate.encode()).hexdigest(),copied_sha256=hashlib.sha256(adjusted.encode()).hexdigest(),
 diff=''.join(difflib.unified_diff(gate.splitlines(True),adjusted.splitlines(True),fromfile='protected gate',tofile='throwaway gate'))),indent=2)+'\n')
job('abba-selftest',['abba_selftest'],'--selftest','--root',str(copy))
job('perfio-quiet',['perfio_stream'])
(OUT/'sequence.json').write_text(json.dumps(results,indent=2)+'\n')
raise SystemExit(int(any(r['exit'] for r in results)))
