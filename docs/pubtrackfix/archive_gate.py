#!/usr/bin/env python3
"""Compact receipts for a completed gate job run, retaining failures and argv."""
import argparse,gzip,json,re,shutil,tarfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('log',type=Path);p.add_argument('name');a=p.parse_args()
root=Path(__file__).resolve().parents[2];out=root/'docs/pubtrackfix/proof'/a.name;out.mkdir(parents=True,exist_ok=True)
s=a.log.read_text();match=re.search(r'artifacts: (.*)',s);assert match,'missing gate run'
run=Path(match.group(1));summary={'run':str(run),'log':str(a.log),'jobs':{},'summary':[line for line in s.splitlines() if line.startswith('GATE(PARTIAL)')]}
for rel in ('plan.sh','phases.tsv','ledger.partial'):
 if (run/rel).exists():shutil.copy2(run/rel,out/rel)
with gzip.open(out/'gate.log.gz','wb') as f:f.write(a.log.read_bytes())
with tarfile.open(out/'receipts.tar.gz','w:gz') as archive:
 for job in sorted((run/'jobs').iterdir()):
  if not job.is_dir():continue
  entry={'done':(job/'done').read_text() if (job/'done').exists() else None}
  for path in job.rglob('*'):
   if not path.is_file() or 'checkout' in path.parts or path.stat().st_size>30_000_000:continue
   if path.suffix not in ('.json','.log','.tsv') and path.name not in ('ledger','done'):continue
   archive.add(path,arcname=str(path.relative_to(run/'jobs')),recursive=False)
  summary['jobs'][job.name]=entry
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({'name':a.name,'summary':summary['summary'],'jobs':len(summary['jobs'])}))
