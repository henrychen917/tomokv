#!/usr/bin/env python3
"""Check every production-unit output via make -q, plus delivery identities."""
import hashlib,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 text=(ROOT/'tests/gate.sh').read_text()
 body=text.split('job_production_units(){',1)[1].split('\njob_multidb(){',1)[0]
 regular=body.split('make -k -j"$BUILD_JOBS"',1)[1].split('>"$TMPDIR/build.log"',1)[0]
 targets=list(dict.fromkeys(re.findall(r'build/[A-Za-z0-9_.-]+',regular)))
 commands=[['make','-q','all']]+[['make','-q',target] for target in targets]
 commands += [['make','-q','BUILD_ROOT=build/'+name,'all'] for name in ('mdbqsbr2-park','mdbqsbr2-no-wake')]
 commands += [['make','-f','Makefile','-f','tools/blockfix_cost.mk','-q','build/blockfix-cost','build/tomokv.blockfix-cost.sha256']]
 commands += [['make','-f','Makefile','-f','tools/blockfix2.mk','-q','build/'+target] for target in ('blockfix2-unit','blockfix2-db0-unit')]
 rows=[]
 for cmd in commands:
  result=subprocess.run(['taskset','-c','48-60']+cmd,cwd=ROOT,capture_output=True,text=True)
  rows.append(dict(command=cmd,rc=result.returncode,output=result.stdout+result.stderr))
 arms={name:sha(ROOT/'build/flipfix7'/name) for name in ('PRE','POST','PAD-A')}
 expected={Path(line.split()[1]).name:line.split()[0] for line in (ROOT/'docs/flipfix7/arms.sha256').read_text().splitlines()}
 result=dict(checks=rows,arms=arms,expected_arms=expected,arms_match=arms==expected,
             release_matches_post=sha(ROOT/'build/tomokv')==arms['POST'],
             expectations=re.findall(r'^EXPECT_(?:QUICK|FULL)=\d+',text,re.M))
 (ROOT/'docs/flipfix7/delivery-verification.json').write_text(json.dumps(result,indent=2)+'\n')
 print('freshness',len(rows),'failed',[r for r in rows if r['rc']],'identities',result['arms_match'],result['release_matches_post'])
 assert not any(r['rc'] for r in rows) and result['arms_match'] and result['release_matches_post']
 assert result['expectations']==['EXPECT_QUICK=1046','EXPECT_FULL=1063']
if __name__=='__main__':main()
