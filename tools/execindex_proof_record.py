#!/usr/bin/env python3
"""Archive selected-job ledgers and explicit failures, never infer a full gate pass."""
import hashlib,json,re,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/execindex/proof';OUT.mkdir(parents=True,exist_ok=True)
records=[]
for group in ['proof','proof-extra']:
    source=ROOT/'build/execindex'/group
    if not (source/'runs.json').exists():continue
    for row in json.loads((source/'runs.json').read_text()):
        log=(source/(row['name']+'.log')).read_text()
        path=re.search(r'  artifacts: (.*)',log)
        assert path,row
        run=Path(path[1]);dest=OUT/row['name'];dest.mkdir(exist_ok=True)
        (dest/'output.log').write_text(log)
        for name in ['ledger.partial','plan.sh','differ-plan.json','differ-split-fold.json','differ-armed-fold.json']:
            if (run/name).exists():shutil.copy2(run/name,dest/name)
        jobs=[]
        for job in sorted((run/'jobs').iterdir()):
            if not (job/'done').exists():continue
            rc,passed,failed=map(int,(job/'done').read_text().split())
            jobs.append(dict(name=job.name,returncode=rc,passed=passed,failed=failed,path=str(job)))
            if (job/'ledger').exists() and (job/'ledger').stat().st_size:
                shutil.copy2(job/'ledger',dest/(job.name+'.ledger'))
            if failed or job.name.startswith(('txnorder','execfair')):
                d=dest/(job.name+('-failed' if failed else '-evidence'));d.mkdir(exist_ok=True)
                for file in job.iterdir():
                    if file.is_file() and file.suffix in ['.txt','.log','.json']:
                        shutil.copy2(file,d/file.name)
            if job.name.startswith('differ-'):
                # Retain the actual seed/leg inventory and every exact mode
                # comparison, without committing the generated Redis datasets.
                for file in job.rglob('*'):
                    if file.is_file() and (file.name in {
                            'seeds.json','legs.tsv','complete.json','stream.json',
                            'results.json','result.json','output.log'} or
                            file.name.endswith('.coverage.json')):
                        target=dest/job.name/file.relative_to(job)
                        target.parent.mkdir(parents=True,exist_ok=True)
                        shutil.copy2(file,target)
                if (job/'differ').exists():
                    logs=[]
                    for file in sorted((job/'differ').rglob('*.log')):
                        logs.append(dict(path=str(file.relative_to(job)),bytes=file.stat().st_size,
                                         sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
                    (dest/(job.name+'-log-digests.json')).write_text(json.dumps(logs,indent=2)+'\n')
        records.append(dict(row,run_directory=str(run),jobs_evidence=jobs,proof_no_rates=group=='proof-extra'))
(OUT/'runs.json').write_text(json.dumps(records,indent=2)+'\n')
print('archived',len(records),'selected-job runs; failing attempts',sum(r['exit_code']!=0 for r in records))
