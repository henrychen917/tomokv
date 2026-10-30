#!/usr/bin/env python3
"""Retain completed gate evidence without copying executables, dumps or source arms."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/climonfix5/job-evidence'
OUT.mkdir(exist_ok=True)
SUFFIXES = {'.log', '.txt', '.json', '.tsv', '.csv', '.out', '.err', '.stdout', '.stderr'}
NAMES = {'ledger', 'done', 'timings', 'counts', 'completion-order', 'fixture-affinity'}
SKIP_DIRS = {'src', 'third_party', 'objects', '__pycache__', '.git'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


index_path = ROOT / 'docs/climonfix5/job-evidence-index.json'
previous = {x['name']: x for x in json.loads(index_path.read_text())} if index_path.exists() else {}
index = []
for receipt_path in sorted((ROOT / 'docs/climonfix5/jobs').glob('*.json')):
    receipt = json.loads(receipt_path.read_text())
    row = dict(name=receipt_path.stem, receipt=str(receipt_path.relative_to(ROOT)),
               exit=receipt['exit'], binary_sha256=receipt['binary_sha256'])
    old = previous.get(receipt_path.stem, {})
    if 'archive' in old:
        assert digest((ROOT / old['archive']).read_bytes()) == old['archive_sha256']
        assert (old['exit'], old['binary_sha256']) == (row['exit'], row['binary_sha256'])
        # Completed campaigns are immutable. Source checkouts may have been
        # pruned after their original archive/hash was recorded.
        index.append(old)
        continue
    directory = Path(receipt.get('artifacts', '/does-not-exist'))
    if not directory.is_dir():
        row['note'] = 'Setup failed before a gate artifact directory was created.'
        index.append(row)
        continue
    archive = OUT / (receipt_path.stem + '.tar.gz')
    manifest = []
    with archive.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode='w|') as tar:
            for path in sorted(directory.rglob('*')):
                relative = path.relative_to(directory)
                if not path.is_file() or path.is_symlink() or SKIP_DIRS.intersection(relative.parts[:-1]):
                    continue
                if not (path.suffix in SUFFIXES or path.name in NAMES or path.name.startswith('gate-srv-')):
                    continue
                data = path.read_bytes()
                if b'\0' in data[:8192]:
                    continue
                info = tarfile.TarInfo(str(relative))
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
                manifest.append(dict(path=str(relative), bytes=len(data), sha256=digest(data)))
            data = (json.dumps(manifest, indent=2) + '\n').encode()
            info = tarfile.TarInfo('climonfix5-archive-manifest.json')
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    row.update(archive=str(archive.relative_to(ROOT)), archive_sha256=digest(archive.read_bytes()),
               files=len(manifest), uncompressed_bytes=sum(x['bytes'] for x in manifest))
    row['jobs'] = []
    for path in sorted((directory / 'jobs').iterdir()):
        if not path.is_dir():
            continue
        done = path / 'done'
        ledger = path / 'ledger'
        lines = ledger.read_text().splitlines() if ledger.exists() else []
        row['jobs'].append(dict(name=path.name, done=done.read_text().strip() if done.exists() else None,
                               rows=[dict(zip(('verdict', 'seconds', 'label'), line.split('\t', 2)))
                                     for line in lines]))
    index.append(row)
index_path.write_text(json.dumps(index, indent=2) + '\n')
print(json.dumps(dict(campaigns=len(index), archives=sum('archive' in x for x in index),
                     files=sum(x.get('files', 0) for x in index),
                     uncompressed_bytes=sum(x.get('uncompressed_bytes', 0) for x in index))))
