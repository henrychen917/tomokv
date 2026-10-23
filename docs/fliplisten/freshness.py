"""Build every production-unit prerequisite, then check real target freshness."""
import json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];DOC=ROOT/'docs/fliplisten'
gate=(ROOT/'tests/gate.sh').read_text().split('job_production_units(){',1)[1].split('\njob_multidb()',1)[0]
targets=sorted(set(re.findall(r'\bbuild/[-a-z0-9]+',gate)))
assert len(targets)>35,targets
argv=['taskset','-c','48-63','make','-j16','all',*targets,'mdbqsbr-live-arms']
with (DOC/'production-final-build.log').open('w') as f:
 rc=subprocess.run(argv,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT).returncode
assert rc==0,rc
rows=[]
for target in ['build/tomokv',*targets]:
 command=['make','-q',target]
 r=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
 rows.append(dict(target=target,argv=command,returncode=r.returncode,stdout=r.stdout,stderr=r.stderr))
# mdbqsbr-live-arms is a phony wrapper; query each underlying output with the
# same BUILD_ROOT instead of falsely treating the wrapper's -q status as stale.
for root in ('build/mdbqsbr2-park','build/mdbqsbr2-no-wake'):
 command=['make','-q','BUILD_ROOT='+root,root+'/tomokv']
 r=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
 rows.append(dict(target=root+'/tomokv',argv=command,returncode=r.returncode,stdout=r.stdout,stderr=r.stderr))
(DOC/'freshness.json').write_text(json.dumps(dict(build_argv=argv,targets=rows),indent=2)+'\n')
assert all(r['returncode']==0 for r in rows),rows
print(len(rows),'real build targets fresh')
