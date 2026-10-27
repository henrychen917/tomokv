#!/usr/bin/env python3
"""Quiet harness proof; landing counts/fixture edited only in a disposable copy."""
import argparse,hashlib,json,os,re,shutil,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
os.chdir(ROOT);os.sched_setaffinity(0,set(range(64,80)))
env=dict(os.environ,LANG='en_US.UTF-8',GATE_TEST_PORT='20098');env.pop('LC_ALL',None)
parser=argparse.ArgumentParser()
parser.add_argument('--tag',default='final',choices=('final','count-repair'))
parser.add_argument('--selftest-only',action='store_true')
args=parser.parse_args()
suffix='' if args.tag=='final' else '-'+args.tag
out=ROOT/'docs/wave8b'; copy=ROOT/('build/wave8b/selftest-'+args.tag)
assert not copy.exists()
for name in subprocess.check_output(['git','ls-files'],text=True).splitlines():
    if name in ('CODEX-OUT.md',): continue
    source=ROOT/name
    if not source.is_file(): continue
    target=copy/name;target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,target)
(copy/'build').mkdir(exist_ok=True)
gate=copy/'tests/gate.sh'; original=(ROOT/'tests/gate.sh').read_bytes()
text=gate.read_text()
for tier,before,after in [('QUICK',798,807),('FULL',815,824)]:
    text,replaced=re.subn(r'^EXPECT_'+tier+'='+str(before)+r'\b',
                         'EXPECT_'+tier+'='+str(after),text,count=1,flags=re.M)
    assert replaced==1,(tier,replaced)
counts={tier.lower():int(re.search(r'^EXPECT_'+tier+r'=(\d+)',text,re.M)[1]) for tier in ('QUICK','FULL')}
assert counts=={'quick':807,'full':824}
assert text!=original.decode();gate.write_text(text)
fixture=copy/'tests/fixtures/nullrefresh-ledger-labels.json'
labels=json.loads(fixture.read_text());assert len(labels['labels'])==823
labels['labels'].append('wave8b tracking-off EXEC scans and transitions')
labels['purpose']+='; disposable wave8b landing control only, +1/+1'
fixture.write_text(json.dumps(labels,indent=2)+'\n')
receipt=dict(root=str(copy),original_gate_sha256=hashlib.sha256(original).hexdigest(),
    copy_gate_sha256=hashlib.sha256(gate.read_bytes()).hexdigest(),counts=counts,fixture_rows=824)
(out/('selftest-copy'+suffix+'.json')).write_text(json.dumps(receipt,indent=2)+'\n')
command=['python3','tests/gates_test.py']
if args.selftest_only:
    prior=json.loads((out/'gates-test-final.json').read_text())
    assert prior['exit']==0 and prior['command']==command
    assert (ROOT/'tests/gates_test.py').read_bytes()==subprocess.check_output(
        ['git','show','83e0b809d:tests/gates_test.py'])
    gates_exit=0
else:
    start=time.time()
    with (out/'gates-test-final.log').open('w') as log:
        result=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT)
    gates_exit=result.returncode
    (out/'gates-test-final.json').write_text(json.dumps(dict(command=command,exit=gates_exit,
        seconds=time.time()-start,affinity=sorted(os.sched_getaffinity(0))),indent=2)+'\n')
    print('gates_test',gates_exit,flush=True)
abba=subprocess.run(['python3','docs/wave8b/run_jobs.py','final-abba-selftest'+suffix,'abba_selftest',
    '--single-slot','--root',str(copy)],env=env)
assert (ROOT/'tests/gate.sh').read_bytes()==original
raise SystemExit(0 if gates_exit==0 and abba.returncode==0 else 1)
