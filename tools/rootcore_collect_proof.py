#!/usr/bin/env python3
"""Preserve completed gate phases, including failures and private job logs."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tarfile

root = Path(__file__).resolve().parents[1]
assert os.sched_getaffinity(0) <= set(range(16, 32))
source = root / 'build/rootcore/proof'
out = root / 'docs/rootcore/proof'
out.mkdir(parents=True, exist_ok=True)
summaries = []
for receipt in sorted(source.glob('*.json')):
    meta = json.loads(receipt.read_text())
    log = source / (receipt.stem + '.log')
    match = re.search(r'artifacts: (\S+)', log.read_text())
    assert match, log
    run = Path(match[1]).resolve()
    run.relative_to(root / 'build')
    ledger = run / 'ledger.partial'
    assert ledger.is_file(), ledger
    rows = [line.split('\t', 2) for line in ledger.read_text().splitlines() if line]
    assert all(len(row) == 3 for row in rows), ledger
    assert all(row[0] in ('PARTIAL', 'ok', 'FAIL') for row in rows), ledger
    jobs = {}
    differential = {}
    for directory in sorted((run / 'jobs').iterdir()):
        done = directory / 'done'
        jobs[directory.name] = dict(
            done=done.read_text().strip() if done.exists() else None,
            ledger=(directory / 'ledger').read_text() if (directory / 'ledger').exists() else '')
        if directory.name.startswith('differ-'):
            output = (directory / 'output.log').read_text(errors='replace')
            differential[directory.name] = [line for line in output.splitlines()
                if line.startswith(('DIFFER GATE:', 'DIFFER COMMAND COVERAGE:'))]
    selected = []
    for path in sorted(run.rglob('*')):
        if path.is_file() and (path.suffix in ('.log', '.txt', '.json', '.tsv', '.timings')
                or path.name in ('ledger', 'done', 'ledger.partial', 'plan.sh')):
            selected.append(path)
    archive = out / (receipt.stem + '.tar.gz')
    with tarfile.open(archive, 'w:gz') as tar:
        for path in selected:
            tar.add(path, arcname=str(path.relative_to(run)), recursive=False)
    with archive.open('rb') as f:
        archive_sha = hashlib.file_digest(f, 'sha256').hexdigest()
    summary = dict(meta, run_directory=str(run),
        passed_rows=sum(row[0] == 'ok' for row in rows),
        failed_rows=[row[2] for row in rows if row[0] == 'FAIL'],
        notices=[row[2] for row in rows if row[0] == 'PARTIAL'],
        missing_jobs=[name for name in meta['jobs'] if not jobs.get(name, {}).get('done')],
        differential=differential,
        differential_plan=json.loads((run / 'differ-plan.json').read_text())
            if (run / 'differ-plan.json').exists() else None,
        jobs=jobs, archive_sha256=archive_sha,
        archive_files=[str(path.relative_to(run)) for path in selected])
    # meta already contains the requested job list; preserve it separately.
    summary['requested_jobs'] = meta['jobs']
    shutil.copyfile(log, out / log.name)
    (out / (receipt.stem + '.json')).write_text(json.dumps(summary, indent=2) + '\n')
    summaries.append({key: value for key, value in summary.items()
                      if key not in ('jobs', 'archive_files', 'command', 'requested_jobs',
                                     'differential_plan')})
(out / 'summary.json').write_text(json.dumps(summaries, indent=2) + '\n')
print(json.dumps(summaries, indent=2))
