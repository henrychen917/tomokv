#!/usr/bin/env python3
"""Retain gate ledgers, directed frames and differential logs after all jobs finish."""
import hashlib
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/notifyorder'
OUT = DOC / 'proof'
OUT.mkdir(exist_ok=True)
logs = [*(f'gate-verified-{arm}.log' for arm in ('post', 'pre', 'pad-a', 'no-salvage')),
        *(f'gate-broad-{arm}.log' for arm in ('post', 'pre')),
        *(f'differ-{arm}-{engine}.log' for arm in ('post', 'pre') for engine in ('uring', 'epoll')),
        *(f'gate-unit-{arm}.log' for arm in ('post', 'pre', 'pre-new-assertions', 'no-salvage-final')),
        'gate-serverless-post.log', 'gate-callback-before.log', 'gate-callback-pre.log',
        'gate-atomic-correctness-post.log',
        'gate-abba-fenced.log', 'gate-unit-post-early.log', 'gate-held-overwrite-before.log', 'gate-held-overwrite-after.log', 'gate-metadata-before.log', 'gate-lfu-before.log']
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--only', nargs='+', choices=logs)
args = parser.parse_args()
if args.only:
    logs = args.only
inventory = []
historical = {'gate-held-overwrite-before.log', 'gate-held-overwrite-after.log',
              'gate-metadata-before.log', 'gate-lfu-before.log'}
for name in logs:
    log = DOC / name
    assert log.is_file(), name
    matches = re.findall(r'  artifacts: (\S+)', log.read_text())
    assert len(matches) == 1, (name, matches)
    run = Path(matches[0])
    assert run.is_dir() and run.parent == ROOT / 'build', run
    rows = []
    for ledger in sorted(run.glob('jobs/*/ledger')):
        for line in ledger.read_text().splitlines():
            status, seconds, label = line.split('\t', 2)
            rows.append(dict(job=ledger.parent.name, status=status, seconds=seconds, label=label))
    public_rows = []
    for line in (run / 'ledger.partial').read_text().splitlines():
        status, seconds, label = line.split('\t', 2)
        if status != 'PARTIAL':
            public_rows.append(dict(status=status, seconds=seconds, label=label))
    completions = [dict(job=p.parent.name, record=p.read_text().strip())
                   for p in sorted(run.glob('jobs/*/done'))]
    legs = []
    for job in ('notify_order', 'notify_aof'):
        for path in sorted((run / 'jobs' / job).glob('order-*.log')):
            text = path.read_text()
            score = re.search(r'notifyorder: (\d+) cases passed; (\d+) failures', text)
            legs.append(dict(job=job, leg=path.name,
                             geometry=re.findall(r'^GEOMETRY .+$', text, re.M),
                             score=list(map(int, score.groups())) if score else None,
                             failures=re.findall(r'^FAIL .+$', text, re.M),
                             c2_failures=len(re.findall(r'^FAIL C2/', text, re.M)),
                             c7_failures=len(re.findall(r'^FAIL C7/', text, re.M)),
                             aof_pass='PASS local script notifications + grouped AOF + reload vs Redis' in text))
    differential = None
    plan = run / 'differ-plan.json'
    if plan.exists():
        differential = dict(plan=json.loads(plan.read_text()), parts=[])
        for job in sorted((run / 'jobs').glob('differ-*')):
            directory = job / 'differ'
            complete = directory / 'complete.json'
            leg_file = directory / 'legs.tsv'
            comparisons = [line.split('\t') for line in leg_file.read_text().splitlines()] if leg_file.exists() else []
            assert all(len(leg) == 6 for leg in comparisons), job
            equivalence = []
            for result_file in sorted(directory.glob('mode-equivalence-*/results.json')):
                results = json.loads(result_file.read_text())
                stream = json.loads((result_file.parent / 'stream.json').read_text())
                equivalence.append(dict(seed=stream['seed'], declared_cells=stream['cells'],
                                        completed_cells=len(results),
                                        verdicts=dict(Counter(row['verdict'] for row in results)),
                                        failed_cells=[row for row in results if row['verdict'] != 'ok']))
            differential['parts'].append(dict(
                job=job.name,
                complete=json.loads(complete.read_text()) if complete.exists() else None,
                comparisons=len(comparisons),
                suites=dict(sorted(Counter(leg[0] for leg in comparisons).items())),
                seeds=sorted({int(leg[2]) for leg in comparisons}),
                repeated_multi=sum(int(leg[3]) > 0 for leg in comparisons),
                equivalence=equivalence,
                failed_comparisons=[leg for leg in comparisons if leg[4] != '0']))
    files = []
    for path in sorted(run.rglob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix in ('.log', '.txt', '.json', '.tsv') or path.name in ('plan.sh', 'ledger', 'ledger.partial', 'timings', 'done'):
            # Test data directories may contain large data snapshots or TLS private
            # material; neither is needed to retain these execution receipts.
            if any(part.startswith(('gate-data-', 'notifyorder-oracle.', 'notifyaof-oracle.'))
                   for part in path.relative_to(run).parts):
                continue
            files.append(path)
    archive = OUT / (name.removesuffix('.log') + '.tar.gz')
    with tarfile.open(archive, 'w:gz') as bundle:
        bundle.add(log, arcname=name)
        for path in files:
            bundle.add(path, arcname=str(Path(run.name) / path.relative_to(run)))
    inventory.append(dict(log=name, run=str(run.relative_to(ROOT)), rows=rows, legs=legs,
                          public_rows=public_rows, completions=completions,
                          stage='superseded implementation regression receipt' if name in historical else 'final proof or explicit control',
                          differential=differential,
                          archive=str(archive.relative_to(ROOT)),
                          archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                          archived_files=len(files)))
(OUT / 'inventory.json').write_text(json.dumps(inventory, indent=2)+'\n')
for row in inventory:
    bad = [r for r in row['rows'] if r['status'] != 'ok']
    print(row['log'], len(row['rows']), 'rows;', len(bad), 'non-green;', len(row['legs']), 'directed legs')
