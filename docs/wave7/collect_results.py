#!/usr/bin/env python3
"""Archive completed gate evidence and summarize exact candidate/job bindings.

This reads gate verdicts; it does not recreate them or turn a failed selection
into a passing one. Historical failed invocations stay in the summary/archive.
"""
import gzip
import hashlib
import io
import json
import os
import tarfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 96)))
OUT = ROOT / 'docs/wave7/correctness'
POST = hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest()
TEXT = {'.json', '.jsonl', '.log', '.txt', '.tsv', '.sh', '.diff', '.out', '.trace'}
NAMES = {'ledger', 'done', 'timings', 'stdout', 'stderr', 'output'}
selections, pending, jobs = [], [], defaultdict(list)
for receipt in sorted(OUT.glob('*/receipt.json')):
    value = json.loads(receipt.read_text())
    if not isinstance(value, dict) or 'command' not in value:
        continue
    if 'exit' not in value:
        pending.append(receipt.parent.name)
        continue
    record = dict(name=receipt.parent.name, exit=value['exit'],
                  current_post=value['binary_sha256'] == POST,
                  unchanged_binary=value['binary_sha256'] == value['binary_sha256_after'],
                  environment=value['environment'], jobs=value.get('jobs', {}))
    selections.append(record)
    for name, job in record['jobs'].items():
        verdicts = Counter(row.split('\t', 1)[0] for row in job['rows'])
        jobs[name].append(dict(selection=record['name'], current_post=record['current_post'],
                              exit=job['done'].split('\t')[0] if job['done'] else None,
                              rows=dict(verdicts), labels=[row.split('\t', 2)[-1] for row in job['rows']],
                              engine=value['environment']['GATE_DIFFER_NET_IO'],
                              fused=value['environment']['GATE_TXN_FUSED']))
    run = Path(value['run_dir']) if value.get('run_dir') else None
    archive = receipt.parent / 'gate-evidence.tar.gz'
    manifest = receipt.parent / 'archive.json'
    if not run or archive.exists():
        continue
    included, excluded = [], []
    with archive.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, filename='') as gz:
        with tarfile.open(fileobj=gz, mode='w|', format=tarfile.PAX_FORMAT) as tar:
            for path in sorted(run.rglob('*')):
                if not path.is_file() or path.is_symlink():
                    continue
                relative = str(path.relative_to(run))
                item = dict(path=relative, bytes=path.stat().st_size)
                if path.suffix not in TEXT and path.name not in NAMES:
                    excluded.append(item)
                    continue
                data = path.read_bytes()
                item['sha256'] = hashlib.sha256(data).hexdigest()
                included.append(item)
                info = tarfile.TarInfo(relative)
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
    manifest.write_text(json.dumps(dict(run_dir=str(run),
        archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        included=included, excluded_runtime_data=excluded), indent=2) + '\n')

summary = dict(post_sha256=POST, pending=pending, selections=selections, jobs=dict(jobs))
(OUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
passed = [name for name, entries in jobs.items() if any(
    e['current_post'] and e['exit'] == '0' and not e['rows'].get('bad', 0) for e in entries)]
failed = [(r['name'], r['exit']) for r in selections if r['exit']]
print('completed selections', len(selections), 'current POST jobs passing', len(passed),
      'historical failed selections', failed, 'pending', pending)
