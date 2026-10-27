#!/usr/bin/env python3
"""Quiet harness proof; landing counts/fixture edited only in a disposable copy."""
import hashlib,json,os,shutil,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
os.chdir(ROOT);os.sched_setaffinity(0,set(range(64,80)))
env=dict(os.environ,LANG='en_US.UTF-8',GATE_TEST_PORT='20098');env.pop('LC_ALL',None)
out=ROOT/'docs/wave8b'; copy=ROOT/'build/wave8b/selftest-final'
assert not copy.exists()
for name in subprocess.check_output(['git','ls-files'],text=True).splitlines():
    if name.startswith(('docs/','calib/')) or name in ('CODEX-OUT.md',): continue
    source=ROOT/name
    if not source.is_file(): continue
    target=copy/name;target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,target)
(copy/'build').symlink_to(ROOT/'build',target_is_directory=True)
gate=copy/'tests/gate.sh'; original=(ROOT/'tests/gate.sh').read_bytes()
text=gate.read_text().replace('EXPECT_QUICK=798\n','EXPECT_QUICK=807\n').replace('EXPECT_FULL=815\n','EXPECT_FULL=824\n')
assert text!=original.decode();gate.write_text(text)
fixture=copy/'tests/fixtures/nullrefresh-ledger-labels.json'
labels=json.loads(fixture.read_text());assert len(labels['labels'])==823
labels['labels'].append('wave8b tracking-off EXEC scans and transitions')
labels['purpose']+='; disposable wave8b landing control only, +1/+1'
fixture.write_text(json.dumps(labels,indent=2)+'\n')
receipt=dict(root=str(copy),original_gate_sha256=hashlib.sha256(original).hexdigest(),
    copy_gate_sha256=hashlib.sha256(gate.read_bytes()).hexdigest(),counts={'quick':807,'full':824},fixture_rows=824)
(out/'selftest-copy.json').write_text(json.dumps(receipt,indent=2)+'\n')
command=['python3','tests/gates_test.py'];start=time.time()
with (out/'gates-test-final.log').open('w') as log:
    result=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT)
(out/'gates-test-final.json').write_text(json.dumps(dict(command=command,exit=result.returncode,
    seconds=time.time()-start,affinity=sorted(os.sched_getaffinity(0))),indent=2)+'\n')
print('gates_test',result.returncode,flush=True)
abba=subprocess.run(['python3','docs/wave8b/run_jobs.py','final-abba-selftest','abba_selftest',
    '--single-slot','--root',str(copy)],env=env)
assert (ROOT/'tests/gate.sh').read_bytes()==original
raise SystemExit(0 if result.returncode==0 and abba.returncode==0 else 1)
