#!/usr/bin/env python3
"""Archive all selected-job attempts, their legs, digests and explicit failures."""
import hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/execfifo3/validation'
records=[]
for ordinal,row in enumerate(json.loads((OUT/'runs.json').read_text())):
    run=Path(row['run_directory']); dest=OUT/f"{ordinal:02d}-{row['group']}";dest.mkdir(parents=True,exist_ok=True)
    shutil.copy2(row['log'],dest/'output.log')
    for name in ['ledger.partial','ledger.partial.timings','plan.sh','differ-plan.json','differ-split-fold.json','differ-armed-fold.json']:
        if (run/name).exists():shutil.copy2(run/name,dest/name)
    jobs=[]
    for job in sorted((run/'jobs').iterdir()):
        if not (job/'done').exists():continue
        rc,passed,failed=map(int,(job/'done').read_text().split())
        evidence=dest/job.name;evidence.mkdir(exist_ok=True)
        digests=[]
        for file in sorted(job.rglob('*')):
            if not file.is_file():continue
            relative=file.relative_to(job)
            # Exclude datasets, binaries, pid files and temporary timeout markers.
            if file.suffix not in ('.txt','.log','.json','.tsv') and file.name not in ('done','ledger','timings') and not file.name.startswith('gate-srv-'):continue
            data=file.read_bytes()
            digests.append(dict(path=str(relative),bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
            # Large build/server traces remain digest-bound on disk; preserve
            # every result, coverage and failure log used to judge a leg.
            if len(data)<=2_000_000 or failed:
                target=evidence/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        (evidence/'file-digests.json').write_text(json.dumps(digests,indent=2)+'\n')
        jobs.append(dict(name=job.name,returncode=rc,passed=passed,failed=failed,path=str(job),evidence=str(evidence.relative_to(ROOT))))
    records.append(dict(row,jobs_evidence=jobs))
(OUT/'evidence.json').write_text(json.dumps(records,indent=2)+'\n')
print('archived',len(records),'selected-job attempts; failures',sum(r['exit_code']!=0 for r in records))
