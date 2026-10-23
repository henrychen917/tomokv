"""Archive completed owned gate jobs, excluding binaries, databases and private keys."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('label')
parser.add_argument('log', type=Path)
args = parser.parse_args()
text = args.log.read_text()
assert 'GATE(PARTIAL):' in text, 'gate has not finished'
run = Path(re.search(r'artifacts: (.+)', text)[1])
dest = ROOT / 'docs/fliplisten/gate-receipts'
dest.mkdir(exist_ok=True)
archive = dest / (args.label + '.tar.gz')
included, omitted = [], []
with tarfile.open(archive, 'w:gz') as tar:
    for path in sorted(run.rglob('*')):
        if not path.is_file() or path.is_symlink(): continue
        name = str(path.relative_to(run))
        # Only text receipts; no executable/build artifact is committed.
        if (path.suffix not in ('.txt', '.log', '.json', '.gdb', '.tsv', '.sh', '.py', '')
                or path.stat().st_size > 20_000_000):
            omitted.append(name)
            continue
        with path.open('rb') as stream: prefix = stream.read(512)
        if b'\0' in prefix or prefix.startswith(b'\x7fELF'):
            omitted.append(name)
            continue
        tar.add(path, arcname=name, recursive=False)
        included.append(name)
jobs = []
for path in sorted((run / 'jobs').iterdir()):
    done = path / 'done'
    assert done.exists(), path
    jobs.append(dict(job=path.name, done=done.read_text().strip()))
legs = []
for path in sorted(run.glob('jobs/fliplisten/fliplisten-*/*/result.json')):
    legs.append(json.loads(path.read_text()))
receipt = dict(label=args.label, run=str(run),
               summaries=[line for line in text.splitlines() if line.startswith('GATE(PARTIAL):')],
               jobs=jobs, legs=legs, included=included, omitted=omitted,
               archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
(dest / (args.label + '.json')).write_text(json.dumps(receipt, indent=2) + '\n')
print(args.label, len(jobs), 'jobs', len(legs), 'arrival legs', receipt['summaries'])
