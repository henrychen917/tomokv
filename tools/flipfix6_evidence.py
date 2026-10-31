#!/usr/bin/env python3
"""Archive the lane's owned correctness evidence and classify every diagnostic refusal."""
import collections
import gzip
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/flipfix6'
OUT = ROOT / 'docs/flipfix6'
OUT.mkdir(parents=True, exist_ok=True)
DRAIN_BITS = dict(enumerate((
    'pending_serve_', 'pending_releases_', 'pending_handoffs_', 'deferred_timers_',
    'client_migrations_', 'epoll_closes_', 'dead_next_', 'dead_ready_',
    'multi_deferred_', 'pending_multi_cleanups_', 'pubsub_notification_chains_',
    'io_inbound_quiesced', 'pubsub_inflight', 'pubsub_pending', 'accepts_quiesced',
    'flip_io_drain_ordered', 'closing client before removal')))
DRAIN_BITS.update(dict(enumerate((
    'ROB not quiesced', 'send_inflight', 'serve_pending', 'retire_queued',
    'barrier_owners', 'atomic_groups_io', 'blocked', 'output pending',
    'WB migration not ready', 'coordinator ROB/reply/WB busy'), start=20)))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n')


def classify(directory, label):
    rows = []
    for path in sorted(directory.rglob('server.log')):
        text = path.read_text(errors='replace')
        planned = collections.defaultdict(list)
        drains = collections.defaultdict(list)
        failures = []
        for line in text.splitlines():
            if line.startswith('FLIPFIX6 planned '):
                fields = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', line)}
                planned[fields['epoch']].append(fields)
            elif line.startswith('FLIPFIX6 failure '):
                fields = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', line)}
                fields['error'] = line.split(' error=', 1)[1]
                failures.append(fields)
            elif line.startswith('FLIPFIX6 drain '):
                fields = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', line)}
                fields['clauses'] = [name for bit, name in DRAIN_BITS.items() if fields['mask'] & (1 << bit)]
                drains[fields['epoch']].append(fields)
        for failure in failures:
            db1 = re.search(r'-db1(?:/|-)', str(path)) is not None
            names = ['Idle'] + ([] if db1 else ['DatabaseIoDrain', 'DatabaseExDrain', 'DatabaseRun'])
            names += ['Planning', 'IoDrain', 'IoPrepare', 'ExDrain', 'ClientPrepare',
                      'ClientCommit', 'ClientInstall', 'RoleReady', 'ShardCommit', 'ExInstall', 'Rollback']
            failure['stage_name'] = names[failure['stage']]
            failure['drains'] = drains[failure['epoch']]
            failure['planned'] = planned[failure['epoch']]
            failure['clauses'] = []
            for entry in failure['planned']:
                if entry['migration']:
                    continue
                clauses = []
                if not entry['drain']:
                    clauses.append('a flip_drain_idle clause')
                if entry['session']:
                    clauses.append('multi_session_ == nullptr')
                if entry['watched_refs']:
                    clauses.append('watched_refs_ == 0')
                failure['clauses'].append(dict(io=entry['io'], id=entry['id'], clauses=clauses))
            assert failure['deadline'] == 1, failure
            if failure['stage_name'] == 'ClientPrepare':
                assert any(c['clauses'] for c in failure['clauses']), failure
            elif not failure['drains']:
                failure['limitation'] = 'Drain clauses not captured by diagnostic v1; see v2 rerun.'
        all_planned = [entry for group in planned.values() for entry in group]
        row = dict(path=str(path.relative_to(directory)), failures=failures,
                   planned=len(all_planned), sessions=sum(p['session'] for p in all_planned),
                   s2=sum(p['pending'] for p in all_planned),
                   log_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        rows.append(row)
        dest = OUT / label / path.relative_to(directory).with_suffix('.log.gz')
        dest.parent.mkdir(parents=True, exist_ok=True)
        with gzip.GzipFile(filename=str(dest), mode='wb', mtime=0) as stream:
            stream.write(path.read_bytes())
        for name in ('server.argv.json', 'server.exit.json', 'witness.json'):
            source = path.with_name(name)
            if source.exists():
                dest.with_name(name).write_bytes(source.read_bytes())
    result = dict(rows=rows, refusals=sum(len(r['failures']) for r in rows),
                  planned=sum(r['planned'] for r in rows),
                  sessions=sum(r['sessions'] for r in rows), s2=sum(r['s2'] for r in rows))
    save(OUT / f'{label}-diagnosis.json', result)
    return {k: v for k, v in result.items() if k != 'rows'}


summary = {}
for name in ('diagnosis', 'legacy-diagnostic', 'legacy-diagnostic-v2', 'legacy-pre', 'pre-smoke'):
    directory = BUILD / name
    if not (directory / 'results.json').exists():
        continue
    (OUT / f'{name}-results.json').write_bytes((directory / 'results.json').read_bytes())
    if name in ('diagnosis', 'legacy-diagnostic', 'legacy-diagnostic-v2'):
        summary[name] = classify(directory, name)
for name in ('pre-build.log', 'diag-build.log', 'gates-test.log', 'gates-test-contended.log'):
    source = BUILD / name
    if source.exists():
        with gzip.GzipFile(filename=str(OUT / (name + '.gz')), mode='wb', mtime=0) as stream:
            stream.write(source.read_bytes())
save(OUT / 'summary.json', summary)
print(json.dumps(summary, indent=2))
