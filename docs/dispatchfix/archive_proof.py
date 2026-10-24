#!/usr/bin/env python3
"""Archive completed gate evidence without retaining disposable database images."""
import argparse
import gzip
import hashlib
import json
import re
import tarfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logs', nargs='+', type=Path)
    args = parser.parse_args()
    destination = Path(__file__).resolve().parent / 'proof'
    destination.mkdir(exist_ok=True)
    index = destination / 'index.json'
    records = json.loads(index.read_text()) if index.exists() else {}
    suffixes = {'.log', '.txt', '.json', '.jsonl', '.tsv', '.csv', '.sh', '.manifest', '.acl', '.conf'}
    names = {'ledger', 'ledger.partial', 'done', 'timings', 'seed', 'seeds'}
    for log in args.logs:
        text = log.read_text(errors='replace')
        match = re.search(r'artifacts: (.+/build/gate-run\.[A-Za-z0-9]+)', text)
        assert match and 'GATE(PARTIAL):' in text, f'incomplete gate: {log}'
        root = Path(match[1])
        assert root.parent.resolve() == Path('build').resolve(), root
        archive = destination / (root.name + '.tar.gz')
        files = [p for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()
                 and (p.suffix in suffixes or p.name in names or p.name.startswith('gate-srv-'))]
        with archive.open('wb') as output, gzip.GzipFile(fileobj=output, mode='wb', mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode='w') as tar:
                for path in files:
                    info = tar.gettarinfo(str(path), arcname=str(path.relative_to(root)))
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ''
                    with path.open('rb') as data:
                        tar.addfile(info, data)
        jobs = {}
        for directory in sorted((root / 'jobs').iterdir()):
            if not directory.is_dir():
                continue
            ledger = directory / 'ledger'
            done = directory / 'done'
            assert done.exists(), f'job incomplete: {directory}'
            rows = []
            for line in ledger.read_text().splitlines() if ledger.exists() else []:
                status, elapsed, label = line.split('\t', 2)
                rows.append(dict(status=status, elapsed=elapsed, label=label))
            jobs[directory.name] = dict(done=done.read_text().strip(), rows=rows)
        records[root.name] = dict(log=str(log), archive=str(archive.relative_to(destination.parent)),
                                  sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                                  files=len(files), bytes=archive.stat().st_size, jobs=jobs,
                                  summary=[line for line in text.splitlines() if line.startswith('GATE(PARTIAL):')][-1])
        print(root.name, len(jobs), 'jobs;', len(files), 'files;', archive.stat().st_size, 'bytes')
    index.write_text(json.dumps(records, indent=2) + '\n')


if __name__ == '__main__':
    main()
