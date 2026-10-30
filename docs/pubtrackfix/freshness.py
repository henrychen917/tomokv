#!/usr/bin/env python3
"""Query every production_units target's prerequisites, including submake leaves."""
import argparse,hashlib,json,os,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
 assert os.sched_getaffinity(0)<=set(range(32,48))
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args()
 gate=(ROOT/'tests/gate.sh').read_text();body=gate.split('job_production_units(){',1)[1].split('\njob_multidb(){',1)[0]
 first=body.split('make -k -j"$BUILD_JOBS"',1)[1].split('>"$TMPDIR/build.log"',1)[0]
 targets=re.findall(r'build/[A-Za-z0-9_-]+',first)
 checks=[(['make','-q','all'],'all')]+[(['make','-q',t],t) for t in targets]
 for arm in ('park','no-wake'):
  flags='-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_MDBQSBR_LIVE_PARK'
  if arm=='no-wake':flags+=' -DTOMO_MDBQSBR_NO_WAKE'
  checks.append((['make','BUILD_ROOT=build/mdbqsbr2-'+arm,'CXXFLAGS='+flags,'-q','all'],'mdbqsbr-live-arms/'+arm))
 for target in ('build/blockfix-cost','build/tomokv.blockfix-cost.sha256'):
  checks.append((['make','-f','Makefile','-f','tools/blockfix_cost.mk','-q',target],target))
 for target in ('build/blockfix2-unit','build/blockfix2-db0-unit'):
  checks.append((['make','-f','Makefile','-f','tools/blockfix2.mk','-q',target],target))
 rows=[]
 for command,label in checks:
  r=subprocess.run(command,cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  rows.append(dict(target=label,command=command,returncode=r.returncode,output=r.stdout))
 result=dict(run=str(a.run),production_units_done=(a.run/'jobs/production_units/done').read_text(),
  ready_markers=sorted(p.name for p in (a.run/'unit-ready').iterdir()),queries=rows,
  post_sha256=hashlib.sha256((ROOT/'build/tomokv').read_bytes()).hexdigest())
 (ROOT/'docs/pubtrackfix/freshness.json').write_text(json.dumps(result,indent=2)+'\n')
 failed=[r for r in rows if r['returncode']]
 print(json.dumps({'queries':len(rows),'failures':failed},indent=2));return bool(failed)
if __name__=='__main__':raise SystemExit(main())
