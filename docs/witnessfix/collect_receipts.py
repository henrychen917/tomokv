"""Archive small gate receipts, excluding binaries, database images and traces."""
import hashlib
import json
from pathlib import Path
import re
import tarfile

root = Path.cwd()
output = root / 'docs/witnessfix/gates'
output.mkdir(parents=True, exist_ok=True)
rows = []
for log in sorted((root / 'build/witnessfix').glob('*.log')):
    text = log.read_text(errors='replace')
    match = re.search(r'artifacts: (\S+gate-run\.\w+)', text)
    if not match:
        continue
    run = Path(match.group(1))
    ledger = run / 'ledger.partial'
    if not ledger.exists() or not re.search(r'^GATE\(PARTIAL\):', text, re.M):
        rows.append(dict(log=log.name, run=str(run), complete=False))
        continue
    entries = [line.split('\t', 2) for line in ledger.read_text().splitlines()]
    archive = output / (log.stem + '.tar.gz')
    files = [log, ledger]
    for job in (run / 'jobs').iterdir():
        if not job.is_dir() or job.name == 'production_units':
            continue
        for path in job.rglob('*'):
            if not path.is_file() or path.is_symlink():
                continue
            if path.name in ('ledger', 'timings') or path.suffix in ('.json', '.jsonl', '.txt', '.log'):
                # Full Tcl summaries contain the assertion inventory and raw
                # events for 39 files; preserve those as well as per-file logs.
                limit = 5_000_000 if path.suffix == '.json' else 1_000_000
                if path.stat().st_size <= limit:
                    files.append(path)
    with tarfile.open(archive, 'w:gz') as tar:
        for path in files:
            tar.add(path, arcname=str(path.relative_to(root)), recursive=False)
    counts = {kind: sum(entry[0] == kind for entry in entries) for kind in ('ok', 'FAIL')}
    jobs = {}
    for path in (run/'jobs').glob('*/ledger'):
        lines = [line.split('\t', 2) for line in path.read_text().splitlines()]
        jobs[path.parent.name] = {kind: sum(row[0] == kind for row in lines) for kind in ('ok','FAIL')}
    rows.append(dict(log=log.name, run=str(run), complete=True, counts=counts,
                     jobs=jobs, archive=str(archive.relative_to(root)),
                     archive_sha256=hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest()))
(root/'docs/witnessfix/gate-runs.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps([{k:r[k] for k in ('log','complete','counts') if k in r} for r in rows],indent=2))
