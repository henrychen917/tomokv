#!/usr/bin/env python3
"""Build every production-unit prerequisite, then query each actual output."""
import hashlib,json,os,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
assert os.sched_getaffinity(0)<=set(range(64,112))
gate=(ROOT/'tests/gate.sh').read_text()
body=gate[gate.index('job_production_units(){'):]
first=body[:body.index('  # -q verifies')]
targets=re.findall(r'\bbuild/[a-z][a-z0-9-]*',first)
assert len(targets)==len(set(targets))==42
command=['make','-j32','all',*targets,'mdbqsbr-live-arms']
log=ROOT/'build/wave5b/freshness-build.log'
with log.open('w') as f:
    built=subprocess.run(command,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT).returncode
checks=[]
commands=[['make','-q',target] for target in ['all',*targets]]
flags='-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_MDBQSBR_LIVE_PARK'
commands += [['make','-q','BUILD_ROOT=build/mdbqsbr2-'+arm,
              'CXXFLAGS='+flags+(' -DTOMO_MDBQSBR_NO_WAKE' if arm=='no-wake' else ''),'all']
             for arm in ('park','no-wake')]
for cmd in commands:
    r=subprocess.run(cmd,cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    checks.append(dict(command=cmd,returncode=r.returncode,output=r.stdout))
row=dict(build_command=command,build_returncode=built,checks=checks,
         sha256=hashlib.sha256((ROOT/'build/tomokv').read_bytes()).hexdigest(),
         phony_note='mdbqsbr-live-arms is queried using its two actual outputs with matching build flags')
(ROOT/'docs/wave5b/freshness.json').write_text(json.dumps(row,indent=2)+'\n')
print(json.dumps(dict(build_returncode=built,checks=len(checks),failed=[r for r in checks if r['returncode']]),indent=2))
raise SystemExit(bool(built or any(r['returncode'] for r in checks)))
