#!/usr/bin/env python3
"""Archive completed gate jobs and summarize their actual ledgers; no inference of passes."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import tarfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logs',nargs='+',type=Path)
    parser.add_argument('--output',type=Path,default=Path('docs/atomfix5'))
    args=parser.parse_args()
    runs=[]
    for log in args.logs:
        text=log.read_text()
        found=re.findall(r'^  artifacts: (.+)$',text,re.M)
        assert len(found)==1,(log,found)
        root=Path(found[0])
        phases=(root/'phases.tsv').read_text()
        assert re.search(r'^end\s',phases,re.M),(root,'unfinished gate run')
        name=log.stem.removeprefix('atomfix5-')
        totals=re.findall(r'^GATE\(PARTIAL\): (\d+) ok, (\d+) FAIL;',text,re.M)
        assert len(totals)==1,(log,'missing final partial tally')
        total_passed,total_failed=map(int,totals[0])
        jobs=[]
        for directory in sorted((root/'jobs').iterdir()):
            if not directory.is_dir():continue
            done=directory/'done'
            assert done.exists(),(directory,'missing completion')
            rc,passed,failed=map(int,done.read_text().strip().split())
            rows=[line.split('\t',2) for line in (directory/'ledger').read_text().splitlines()]
            output=(directory/'output.log').read_text()
            jobs.append(dict(job=directory.name,returncode=rc,passed=passed,failed=failed,
                             ledger_passed=sum(r[0].lower()=='ok' for r in rows),
                             ledger_failed=sum(r[0].lower()=='fail' for r in rows),
                             differential_passes=len(re.findall(r'  differ .*? ok ',output)),
                             differential_failures=len(re.findall(r'  differ .*? FAIL ',output)),
                             skips=[line.strip() for line in output.splitlines() if 'SKIP (' in line],
                             rows=[dict(status=r[0],seconds=r[1],label=r[2]) for r in rows]))
        archive=args.output/(name+'-artifacts.tar.gz')
        # Keep logs, receipts and replay inputs. Generated database images stay
        # in build/ and are inventoried instead of bloating the committed proof.
        omitted=[]
        with archive.open('wb') as raw,gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as zipped:
            with tarfile.open(fileobj=zipped,mode='w') as tar:
                tar.add(root,arcname=root.name,recursive=False)
                for path in sorted(root.rglob('*')):
                    if (path.is_file() and not path.is_symlink() and
                            path.suffix in ('.tomo','.rdb','.aof')):
                        omitted.append(dict(path=str(path.relative_to(root)),bytes=path.stat().st_size,
                                            sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
                        continue
                    tar.add(path,arcname=str(Path(root.name)/path.relative_to(root)),recursive=False)
        log_archive=args.output/(name+'-gate.log.gz')
        log_archive.write_bytes(gzip.compress(log.read_bytes(),mtime=0))
        runs.append(dict(name=name,artifact_root=str(root),
                         passed=total_passed,failed=total_failed,
                         jobs=jobs,archive=str(archive),omitted_database_images=omitted,
                         differential_plan=json.loads((root/'differ-plan.json').read_text())
                             if (root/'differ-plan.json').exists() else None,
                         sha256=hashlib.sha256(archive.read_bytes()).hexdigest()))
    (args.output/'proof-runs.json').write_text(json.dumps(runs,indent=2)+'\n')
    for run in runs:
        print(run['name'],run['passed'],run['failed'],len(run['jobs']))


if __name__=='__main__':main()
