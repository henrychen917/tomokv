#!/usr/bin/env python3
"""Build every job_production_units target and check actual prerequisite freshness."""
import hashlib,json,os,re,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];os.chdir(ROOT)
os.sched_setaffinity(0,os.sched_getaffinity(0)&set(range(64,96)))
env=dict(os.environ,LANG='en_US.UTF-8');env.pop('LC_ALL',None)
body=(ROOT/'tests/gate.sh').read_text().split('job_production_units(){',1)[1].split('\njob_multidb(){',1)[0]
first=body.split('# -q verifies',1)[0]
targets=list(dict.fromkeys(re.findall(r'\bbuild/[a-z0-9-]+',first)))
assert len(targets)>=40,targets
out=ROOT/'docs/wave7b/build-proof';out.mkdir(exist_ok=True)
receipt=dict(start=time.time(),affinity=sorted(os.sched_getaffinity(0)),environment={'LANG':env['LANG'],'LC_ALL':'unset'},targets=targets,
 before_sha256=hashlib.sha256((ROOT/'build/tomokv').read_bytes()).hexdigest(),builds=[],freshness=[])
for tag,command in [('production',['make','-k','-j32','all',*targets,'mdbqsbr-live-arms']),
                    ('blockfix',['make','-f','Makefile','-f','tools/blockfix_cost.mk','-j32','build/blockfix-cost','build/tomokv.blockfix-cost.sha256'])]:
 with (out/(tag+'.log')).open('w') as log:r=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT)
 receipt['builds'].append(dict(command=command,exit=r.returncode));print(tag,r.returncode,flush=True)
for target in ['all',*targets]:
 command=['make','-q',target];r=subprocess.run(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 receipt['freshness'].append(dict(command=command,exit=r.returncode,output=r.stdout))
# The live-arms entry is intentionally phony. Check each concrete binary under
# exactly its production compile flags, rather than treating PHONY as stale.
for root,extra in [('build/mdbqsbr2-park','-DTOMO_MDBQSBR_LIVE_PARK'),('build/mdbqsbr2-no-wake','-DTOMO_MDBQSBR_LIVE_PARK -DTOMO_MDBQSBR_NO_WAKE')]:
 command=['make','-q','BUILD_ROOT='+root,'CXXFLAGS=-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread '+extra,'all']
 r=subprocess.run(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 receipt['freshness'].append(dict(command=command,exit=r.returncode,output=r.stdout))
command=['make','-f','Makefile','-f','tools/blockfix_cost.mk','-q','build/blockfix-cost','build/tomokv.blockfix-cost.sha256']
r=subprocess.run(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
receipt['freshness'].append(dict(command=command,exit=r.returncode,output=r.stdout))
receipt.update(end=time.time(),after_sha256=hashlib.sha256((ROOT/'build/tomokv').read_bytes()).hexdigest())
(out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
# A build may intentionally change the candidate; both hashes are retained.
assert all(r['exit']==0 for r in receipt['builds']+receipt['freshness']),receipt
print('production build/freshness complete',len(receipt['freshness']),flush=True)
