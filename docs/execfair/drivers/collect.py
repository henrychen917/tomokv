#!/usr/bin/env python3
"""Archive completed gate job evidence without changing any result or test."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
ROOT=Path(__file__).resolve().parents[3]
ap=argparse.ArgumentParser();ap.add_argument('label');ap.add_argument('log');args=ap.parse_args()
log=ROOT/args.log
text=log.read_text()
run=Path(re.search(r'artifacts: (\S+)',text)[1])
out=ROOT/'docs/execfair/correctness'/args.label
out.mkdir(parents=True,exist_ok=True)
shutil.copy2(log,out/'gate.log')
for name in ('phases.tsv','differ-plan.json','plan.sh','row-timeouts.json'):
    if (run/name).exists():shutil.copy2(run/name,out/name)
rows=[]
for folder in sorted((run/'jobs').iterdir()):
    dest=out/folder.name;dest.mkdir(exist_ok=True)
    ledger=(folder/'ledger').read_text().splitlines() if (folder/'ledger').exists() else []
    entries=[dict(status=line.split('\t',2)[0],seconds=line.split('\t',2)[1],label=line.split('\t',2)[2]) for line in ledger]
    rows.append(dict(job=folder.name,rows=entries))
    for name in ('ledger','output.log','timings'):
        if (folder/name).exists():shutil.copy2(folder/name,dest/name)
    if (folder/'differ').is_dir():
        dd=dest/'differ';dd.mkdir(exist_ok=True)
        for name in ('complete.json','command-coverage.json'):
            if (folder/'differ'/name).exists():shutil.copy2(folder/'differ'/name,dd/name)
    if folder.name in ('txnorder2','txnorder_wake','execfair') or folder.name.startswith('txnorder-'):
        for source in folder.rglob('*'):
            if source.is_file() and source.suffix in ('.json','.log','.txt'):
                target=dest/source.relative_to(folder)
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source,target)
    # Keep every failing assertion's text, including failed differential legs.
    for source in folder.rglob('*'):
        if not source.is_file() or source.suffix not in ('.log','.txt'):continue
        raw=source.read_bytes()
        if b'Traceback (most recent call last)' in raw or b'AssertionError' in raw or b'FAIL ' in raw or b'failed assertion' in raw:
            target=dest/'failure-logs'/source.relative_to(folder)
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
summary=dict(source_run=str(run),gate_log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),jobs=rows,
             pass_rows=sum(r['status']=='ok' for j in rows for r in j['rows']),
             fail_rows=sum(r['status']!='ok' for j in rows for r in j['rows']))
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
for path in list(out.rglob('*')):
    if path.is_file() and path.stat().st_size>800000:
        raw=path.read_bytes();path.with_name(path.name+'.gz').write_bytes(gzip.compress(raw,mtime=0));path.unlink()
print(args.label,summary['pass_rows'],'pass',summary['fail_rows'],'fail',len(rows),'jobs')
