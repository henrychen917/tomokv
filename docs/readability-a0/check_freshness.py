from pathlib import Path
import json,re,subprocess
root=Path(__file__).resolve().parents[2]
body=(root/'tests/gate.sh').read_text().split('job_production_units(){',1)[1].split('\njob_multidb(){',1)[0]
first=body.split('make -k -j"$BUILD_JOBS"',1)[1].split('>"$TMPDIR/build.log"',1)[0]
targets=list(dict.fromkeys(re.findall(r'\bbuild/[\w.-]+',first)))
rows=[]
def query(label,args,required=True):
 result=subprocess.run(['make',*args],cwd=root,text=True,capture_output=True)
 rows.append(dict(target=label,argv=['make',*args],returncode=result.returncode,required=required,
                  output=result.stdout+result.stderr))
query('all',['-q','all'])
for target in targets:query(target,['-q',target])
query('build/tomo-assert-fail',['-q','build/tomo-assert-fail'])
query('mdbqsbr-live-arms',['-q','mdbqsbr-live-arms'])
flags='-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread'
for variant,extra in [('park','-DTOMO_MDBQSBR_LIVE_PARK'),('no-wake','-DTOMO_MDBQSBR_LIVE_PARK -DTOMO_MDBQSBR_NO_WAKE')]:
 query('mdbqsbr2-'+variant+' all',['-q','BUILD_ROOT=build/mdbqsbr2-'+variant,'CXXFLAGS='+flags+' '+extra,'all'])
query('blockfix-cost and binding',['-f','Makefile','-f','tools/blockfix_cost.mk','-q','build/blockfix-cost','build/tomokv.blockfix-cost.sha256'])
result=dict(production_targets=targets,queries=rows,all_fresh=all(row['returncode']==0 for row in rows))
(root/'build/readability-a0/freshness.json').write_text(json.dumps(result,indent=2)+'\n')
print('Production target count:',len(targets),'queries:',len(rows),'all fresh:',result['all_fresh'])
for row in rows:
 if row['returncode']:print(row['target'],row['returncode'],row['output'])
raise SystemExit(0 if result['all_fresh'] else 1)
