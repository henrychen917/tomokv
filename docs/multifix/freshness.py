#!/usr/bin/env python3
"""Check every production_units build target without treating file existence as freshness."""
import argparse,hashlib,json,os,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
os.sched_setaffinity(0,set(range(32,48)))
p=argparse.ArgumentParser();p.add_argument('--build',action='store_true');a=p.parse_args()
gate=(ROOT/'tests/gate.sh').read_text()
body=gate.split('job_production_units(){',1)[1].split('  # -q verifies',1)[0]
targets=list(dict.fromkeys(re.findall(r'build/[\w-]+',body)))
assert targets and all((ROOT/t).parent==ROOT/'build' for t in targets)
# The live-arm target is a recursive/phony build; check each namespace's all
# target with the same compile flags, rather than asking whether phony is fresh.
make=(ROOT/'Makefile').read_text()
flags=re.search(r'^CXXFLAGS\s*[:?]?=\s*(.*)$',make,re.M)[1]
commands=[(['make'],['all',*targets]),
          (['make','BUILD_ROOT=build/mdbqsbr2-park','CXXFLAGS='+flags+' -DTOMO_MDBQSBR_LIVE_PARK'],['all']),
          (['make','BUILD_ROOT=build/mdbqsbr2-no-wake','CXXFLAGS='+flags+' -DTOMO_MDBQSBR_LIVE_PARK -DTOMO_MDBQSBR_NO_WAKE'],['all']),
          (['make','-f','Makefile','-f','tools/blockfix_cost.mk'],
           ['build/blockfix-cost','build/tomokv.blockfix-cost.sha256'])]
if a.build:
 with (ROOT/'build/multifix/required-build.log').open('w') as out:
  for prefix,items in commands:
   subprocess.run([*prefix,'-j16',*items],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
rows=[]
for prefix,items in commands:
 for target in items:
  result=subprocess.run([*prefix,'-q',target],cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  root=next((arg.split('=',1)[1] for arg in prefix if arg.startswith('BUILD_ROOT=')),'build')
  f=ROOT/(root+'/tomokv' if target=='all' else target)
  rows.append(dict(target=target,argv=[*prefix,'-q',target],exit=result.returncode,diagnostic=result.stdout,
                   sha256=hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else None))
report=dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            production_unit_targets=len(targets),rows=rows,all_fresh=all(r['exit']==0 for r in rows))
(ROOT/'docs/multifix/freshness.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(dict(production_unit_targets=len(targets),checked=len(rows),all_fresh=report['all_fresh'],
                     stale=[r['target'] for r in rows if r['exit']]),indent=2))
raise SystemExit(0 if report['all_fresh'] else 1)
