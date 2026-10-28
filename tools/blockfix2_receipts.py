#!/usr/bin/env python3
"""Archive lane-owned gate receipts, excluding binaries and server data.

Each --run is a human label and a gate artifact directory, separated by '='.
The archive includes the original red receipts as well as passing ones; the
index summarizes ledger rows without reclassifying failures as successes.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def selected(path, root):
    parts = path.relative_to(root).parts
    if any(part in ('checkout', 'data', 'appendonlydir') or
           part.startswith('gate-data-') for part in parts):
        return False
    return path.name in ('ledger', 'done', 'timings') or \
        path.suffix in ('.log', '.txt', '.json', '.tsv', '.sh') or \
        path.name.startswith('gate-srv-') or 'unit-ready' in parts


def collect(label, root, output):
    files = []
    archive = output / (label + '.tar.gz')
    with archive.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as gz, \
            tarfile.open(fileobj=gz, mode='w|') as tar:
        for path in sorted(root.rglob('*')):
            if not path.is_file() or path.is_symlink() or not selected(path, root):
                continue
            data = path.read_bytes()
            name = str(path.relative_to(root))
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.mode = 0o644
            tar.addfile(member, io.BytesIO(data))
            files.append(dict(path=name, size=len(data), sha256=sha(data)))
    jobs = []
    for path in sorted(root.glob('jobs/*/ledger')):
        rows = []
        for line in path.read_text().splitlines():
            status, seconds, name = line.split('\t', 2)
            rows.append(dict(status=status, seconds=seconds, label=name))
        done = path.with_name('done')
        jobs.append(dict(job=path.parent.name, done=done.read_text().strip() if done.exists() else None,
                         passed=sum(r['status'] == 'ok' for r in rows),
                         failed=sum(r['status'] != 'ok' for r in rows), rows=rows))
    return dict(label=label, source=str(root.resolve()), archive=str(archive),
                archive_sha256=sha(archive.read_bytes()), files=files, jobs=jobs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='append', required=True)
    parser.add_argument('--output', type=Path, default=Path('docs/blockfix2/gate-receipts'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    index = args.output / 'index.json'
    previous = {item['label']: item for item in json.loads(index.read_text())} if index.exists() else {}
    for spec in args.run:
        label, folder = spec.split('=', 1)
        assert label and '/' not in label
        previous[label] = collect(label, Path(folder), args.output)
        row = previous[label]
        print(label, sum(j['passed'] for j in row['jobs']),
              sum(j['failed'] for j in row['jobs']), row['archive_sha256'])
    index.write_text(json.dumps(list(previous.values()), indent=2) + '\n')


if __name__ == '__main__':
    main()
