#!/usr/bin/env python3
"""Archive completed selected-job evidence without disposable checkouts or data."""
import argparse, hashlib, json, os, tarfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
assert os.sched_getaffinity(0) <= set(range(32, 48))
p = argparse.ArgumentParser()
p.add_argument('names', nargs='*')
a = p.parse_args()
receipts = ROOT / 'docs/scriptfix3/jobs'
output = ROOT / 'docs/scriptfix3/job-archives'
output.mkdir(exist_ok=True)
names = a.names or [f.stem for f in sorted(receipts.glob('*.json'))]
index = []
for name in names:
    receipt = json.loads((receipts / (name + '.json')).read_text())
    run = Path(receipt['artifacts'])
    assert run.is_relative_to(ROOT / 'build')
    archive = output / (name + '.tar.gz')
    inventory = output / (name + '.json')
    if not inventory.exists():
        assert not archive.exists(), 'incomplete archive must be examined first'
        rows = []
        with tarfile.open(archive, 'w:gz', compresslevel=6) as tar:
            for source in sorted(run.rglob('*')):
                relative = source.relative_to(run)
                if not source.is_file() or source.is_symlink():
                    continue
                if any(part in ('checkout', 'data', '__pycache__') for part in relative.parts):
                    continue
                data = source.read_bytes()
                assert not data.startswith(b'\x7fELF'), str(source)
                tar.add(source, arcname=str(relative), recursive=False)
                rows.append(dict(path=str(relative), bytes=len(data),
                                 sha256=hashlib.sha256(data).hexdigest()))
        inventory.write_text(json.dumps(dict(run=str(run), files=rows,
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest()), indent=2) + '\n')
    saved = json.loads(inventory.read_text())
    assert saved['archive_sha256'] == hashlib.sha256(archive.read_bytes()).hexdigest()
    index.append(dict(name=name, exit=receipt['exit'], summary=receipt['summary'],
        binary_sha256=receipt['binary_sha256'], binary_unchanged=receipt['binary_unchanged'],
        archive=str(archive.relative_to(ROOT)), sha256=saved['archive_sha256'],
        files=len(saved['files'])))
(ROOT / 'docs/scriptfix3/proof-archives.json').write_text(json.dumps(index, indent=2) + '\n')
print(json.dumps(index, indent=2))
