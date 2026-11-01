#!/usr/bin/env python3
"""Query the complete gate production-unit inventory without rebuilding it."""
import hashlib,json,os,re,shlex,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    assert os.sched_getaffinity(0)<=set(range(96,112))
    source=(ROOT/'tests/gate.sh').read_text()
    body=source.split('job_production_units(){',1)[1].split('# -q verifies',1)[0]
    targets=re.findall(r'build/[A-Za-z0-9_-]+',body)
    assert len(targets)==len(set(targets)) and len(targets)>40
    commands=[['make','-q','all']]+[['make','-q',target] for target in targets]
    recipe=subprocess.check_output(['make','-n','mdbqsbr-live-arms'],cwd=ROOT,text=True)
    recursive=[shlex.split(line) for line in recipe.splitlines() if line.startswith('make BUILD_ROOT=build/mdbqsbr2-')]
    assert len(recursive)==2
    commands += [[*cmd[:-1],'-q','all'] for cmd in recursive]
    commands += [['make','-f','Makefile','-f','tools/blockfix_cost.mk','-q','build/blockfix-cost','build/tomokv.blockfix-cost.sha256'],
                 ['make','-f','Makefile','-f','tools/blockfix2.mk','-q','build/blockfix2-unit','build/blockfix2-db0-unit']]
    rows=[]
    for command in commands:
        result=subprocess.run(command,cwd=ROOT,text=True,capture_output=True)
        rows.append(dict(command=command,returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
    digest=hashlib.sha256((ROOT/'build/tomokv').read_bytes()).hexdigest()
    assert digest==hashlib.sha256((ROOT/'build/execfifo3/POST').read_bytes()).hexdigest()
    identities={str(path):hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in map(Path,('Makefile','tests/gate.sh','tests/txnorder_fifo.cc','tests/txnorder_chain.cc','build/txnorder-fifo-unit','build/txnorder-fifo-db0-unit'))}
    record=dict(recorded_ns=time.time_ns(),production_sha256=digest,unit_targets=targets,queries=rows,identities=identities,
                phony='mdbqsbr-live-arms was built by job_production_units; both recursive all targets queried with identical flags',
                passed=all(row['returncode']==0 for row in rows))
    (ROOT/'docs/execfifo3/freshness.json').write_text(json.dumps(record,indent=2)+'\n')
    print(len(rows),'make -q checks; pass',record['passed']);assert record['passed']
if __name__=='__main__':main()
