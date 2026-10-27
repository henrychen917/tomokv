#!/usr/bin/env python3
"""Wait for offline proof, freeze arms, then run only selected correctness jobs."""
import hashlib,json,os,shutil,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];os.chdir(ROOT)
os.sched_setaffinity(0,set(range(64,80)))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
digest=sha('build/tomokv');deadline=time.monotonic()+3600
while True:
    receipt=json.loads(Path('docs/wave8b/build/receipt.json').read_text())
    ready=(receipt['after_sha256']==digest and all(x['exit']==0 for x in receipt['builds']+receipt['freshness'])
           and Path('build/wave8b/final-counts-ready').exists())
    if ready:break
    assert time.monotonic()<deadline,'offline verification did not finish'
    time.sleep(10)
assert sha('build/tomokv')==digest
assert len(json.loads(Path('docs/wave8b/controls/receipts.json').read_text()))==4
shutil.copy2('build/tomokv','build/tomokv-wave8b-POST')
shutil.copy2('build/tomokv.asserts.tsv','build/tomokv-wave8b-POST.asserts.tsv')
subprocess.run(['python3','docs/wave8b/pad_identity.py'],check=True)
arms={name:dict(path=str((ROOT/path).resolve()),sha256=sha(path))for name,path in
 [('PRE','build/tomokv-wave8b-PRE'),('POST','build/tomokv-wave8b-POST'),('PAD-A','build/tomokv-wave8b-PAD-A'),
 ('headline','/home/user/Projects/bench-bins/tomokv-headline-3700b51d7'),('execindex','/home/user/Projects/bins/execindex-post-aee04885')]}
Path('docs/wave8b/arms.json').write_text(json.dumps(arms,indent=2)+'\n')
print('FROZEN',digest,flush=True)
subprocess.run(['python3','docs/wave8b/run_final.py'],check=True)
subprocess.run(['python3','docs/wave8b/sync_comment.py'],check=True)
subprocess.run(['python3','docs/wave8b/run_jobs.py','final-source-repair',
    'source_identity','reorder_sync','splitlocal_units','wbland_units','wave8b_off',
    '--single-slot'],check=True)
subprocess.run(['python3','docs/wave8b/identity.py'],check=True)
subprocess.run(['python3','docs/wave8b/pad_a.py'],check=True)
subprocess.run(['python3','docs/wave8b/pad_identity.py'],check=True)
shutil.copy2('build/tomokv','build/tomokv-wave8b-POST')
shutil.copy2('build/tomokv.asserts.tsv','build/tomokv-wave8b-POST.asserts.tsv')
for arm in arms.values():arm['sha256']=sha(arm['path'])
Path('docs/wave8b/arms.json').write_text(json.dumps(arms,indent=2)+'\n')
digest=sha('build/tomokv')
subprocess.run(['python3','docs/wave8b/quiet_checks.py'],check=True)
subprocess.run(['python3','docs/wave8b/scope_identity.py'],check=True)
assert sha('build/tomokv')==digest
