#!/usr/bin/env python3
"""Archive gate job ledgers and raw textual correctness evidence, never build objects."""
import argparse,hashlib,json,re,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('name');p.add_argument('log',type=Path);args=p.parse_args()
 match=re.search(r'artifacts: (.+)',args.log.read_text());assert match,args.log
 run=Path(match[1]);assert run.is_relative_to(ROOT/'build')
 doc=ROOT/'docs/flipfix7';archive=doc/(args.name+'-evidence.tar.gz');jobs={};kept=[]
 for f in (run/'jobs').glob('*/done'):
  rc,passed,failed=map(int,f.read_text().split());jobs[f.parent.name]=dict(exit=rc,passed=passed,failed=failed)
 with tarfile.open(archive,'w:gz') as tar:
  for f in sorted(run.rglob('*')):
   if f.is_file() and (f.suffix in ('.json','.jsonl','.log','.txt','.tsv') or f.name in ('done','ledger','plan.sh','timings','boot-argv','output.log')):
    tar.add(f,arcname=str(f.relative_to(run)));kept.append(str(f.relative_to(run)))
 ledger=run/'ledger.partial';(doc/(args.name+'.ledger')).write_bytes(ledger.read_bytes())
 result=dict(run=str(run),jobs=jobs,archive=str(archive.relative_to(ROOT)),archive_sha256=sha(archive),files=kept,runner_log_sha256=sha(args.log),post_sha256=sha(ROOT/'build/flipfix7/POST'))
 (doc/(args.name+'-archive.json')).write_text(json.dumps(result,indent=2)+'\n')
 print(args.name,{name:r for name,r in jobs.items() if r['exit'] or r['failed']},flush=True)
if __name__=='__main__':main()
