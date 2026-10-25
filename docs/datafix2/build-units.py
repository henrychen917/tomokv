#!/usr/bin/env python3
import argparse, json, re, subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[2]
doc=root/'docs/datafix2'
p=argparse.ArgumentParser();p.add_argument('--source-root',type=Path);p.add_argument('--prefix',default='');options=p.parse_args()
build_root=options.source_root.resolve() if options.source_root else root
body=(root/'tests/gate.sh').read_text().split('job_production_units(){',1)[1].split('\n}',1)[0]
targets=re.findall(r'build/[\w-]+',body.split('>"$TMPDIR/build.log"',1)[0])
assert len(targets)==len(set(targets))
(doc/'unit-targets.json').write_text(json.dumps(targets,indent=2)+'\n')
with (build_root/'build/datafix2-units-build.log').open('w') as log:
    rc=subprocess.run(['taskset','-c','96-111','make','-k','-j16','all',*targets,'mdbqsbr-live-arms'],
        cwd=build_root,stdout=log,stderr=subprocess.STDOUT).returncode
checks=[]
for target in ['all',*targets]:
    checks.append(dict(target=target,returncode=subprocess.run(['make','-q',target],cwd=build_root).returncode))
for name, flags in [('park','-DTOMO_MDBQSBR_LIVE_PARK'),('no-wake','-DTOMO_MDBQSBR_LIVE_PARK -DTOMO_MDBQSBR_NO_WAKE')]:
    args=['make','-q','BUILD_ROOT=build/mdbqsbr2-'+name,
          'CXXFLAGS=-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread '+flags,'all']
    checks.append(dict(target='mdbqsbr2-'+name,returncode=subprocess.run(args,cwd=build_root).returncode))
(doc/(options.prefix+'unit-build.json')).write_text(json.dumps(dict(build_returncode=rc,checks=checks),indent=2)+'\n')
print('build',rc,'fresh',sum(r['returncode']==0 for r in checks),'of',len(checks),flush=True)
