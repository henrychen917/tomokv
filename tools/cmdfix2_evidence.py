#!/usr/bin/env python3
"""Summarize original receipts; archive red controls as well as green runs."""
import argparse
from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import blockfix2_receipts as receipts

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/cmdfix2'
DOC = ROOT / 'docs/cmdfix2'


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def instruction_table():
    def read(arm):
        return json.loads((DOC / 'instructions' / arm / 'counts.json').read_text())['rows']
    def key(row):
        return tuple(row[k] for k in ('namespace', 'command', 'mode', 'batch', 'atomic'))
    pre = {key(r): r for r in read('PRE')}
    rows = []
    for post in read('POST'):
        before = pre[key(post)]['total']
        rows.append((*key(post), before, post['total'], post['total'] - before))
    assert len(rows) == 144 and len(pre) == 144
    main = [r for r in rows if r[1] in ('GET', 'SET', 'INCR', 'MGET', 'MSET')]
    assert len(main) == 80 and all(r[-1] == 0 for r in main)
    with (DOC / 'instructions/table.csv').open('w') as out:
        writer = csv.writer(out, lineterminator='\n')
        writer.writerow(('namespace', 'command', 'mode', 'batch', 'atomic', 'PRE', 'POST', 'delta'))
        writer.writerows(sorted(rows))


def gate_runs(archive):
    output = DOC / 'gate-receipts'; output.mkdir(exist_ok=True)
    index_path = output / 'index.json'
    previous = {r['label']: r for r in json.loads(index_path.read_text())} if index_path.exists() else {}
    overview = []
    for log in sorted(BUILD.glob('*.log')):
        contents = log.read_text(errors='replace')
        matches = re.findall(r'^  artifacts: (.+)$', contents, re.M)
        if not matches: continue
        assert len(matches) == 1, log
        root = Path(matches[0]); rows = []
        for ledger in sorted(root.glob('jobs/*/ledger')):
            for line in ledger.read_text().splitlines():
                status, seconds, label = line.split('\t', 2)
                rows.append(dict(job=ledger.parent.name, status=status, seconds=seconds, label=label))
        if not root.exists() and log.stem in previous:
            rows = [dict(job=job['job'], **row) for job in previous[log.stem]['jobs'] for row in job['rows']]
        complete = 'GATE(PARTIAL):' in contents
        record = dict(label=log.stem, source=str(root), complete=complete, archived_only=not root.exists(),
                      passed=sum(r['status'] == 'ok' for r in rows),
                      failed=sum(r['status'] != 'ok' for r in rows), rows=rows)
        overview.append(record)
        if archive and complete and log.stem not in previous:
            previous[log.stem] = receipts.collect(log.stem, root, output)
            shutil.copyfile(log, output / log.name)
            print('archived', log.stem, record['passed'], record['failed'], flush=True)
    save(DOC / 'gate-summary.json', overview)
    if archive: save(index_path, list(previous.values()))
    return {r['label']: r for r in overview}


def witnesses(runs):
    selected = {'geo': 'pre-unit-geo', 'channels': 'pre-channels-final'}
    result = []
    for case in ('geo', 'scores', 'hll', 'lcs', 'channels', 'xsetid'):
        item = dict(case=case)
        for arm, run in [('PRE', selected.get(case, 'pre-gate')), ('POST', 'post-v2-witness')]:
            path = Path(runs[run]['source']) / 'jobs' / ('cmdfix2-' + case) / 'proof/summary.json'
            rows = json.loads(path.read_text())
            assert len(rows) == len({r['leg'] for r in rows}) == 32
            item[arm] = dict(run=run, checks=sum(r['checks'] for r in rows),
                            failed_legs=sum(bool(r['failures']) for r in rows),
                            differences=sum(len(r['failures']) for r in rows),
                            legs=[dict(leg=r['leg'], checks=r['checks'], differences=len(r['failures']))
                                  for r in rows])
        assert item['PRE']['failed_legs'] == 32 and item['POST']['failed_legs'] == 0
        result.append(item)
    save(DOC / 'witnesses.json', result)


def differential_summary(runs, require_complete):
    result = []
    for name in ('post-v2-main-uring', 'post-v2-main-epoll'):
        root = Path(runs[name]['source'])
        paths = sorted(root.glob('jobs/differ-*/output.log'))
        if require_complete:
            assert {p.parent.name for p in paths} == {
                'differ-split-0', 'differ-split-1', 'differ-armed-0',
                'differ-armed-1', 'differ-equivalence'}
        for path in paths:
            lines = path.read_text(errors='replace').splitlines()
            verdict = [line for line in lines if line.startswith((
                'DIFFER GATE:', 'DIFFER COMMAND COVERAGE:', 'DIFFER matrix:'))]
            if require_complete:
                assert any(line.startswith('DIFFER GATE:') and ' fail=0 ' in line for line in verdict)
            result.append(dict(run=name, job=path.parent.name, verdict=verdict))
    save(DOC / 'differential.json', result)


def final_jobs(runs):
    """Require completed final-arm jobs and expose the unchanged baseline failure."""
    names = ['post-v2-witness', 'post-v2-main-uring', 'post-v2-main-epoll',
             'post-v2-related', 'post-v2-modes-epoll', 'post-v2-extra-uring']
    for engine in ('uring', 'epoll'):
        names += [f'post-v2-fused-{engine}', f'post-v2-tcl-receipted-{engine}']
        names += [f'post-v2-notify-{engine}-{mode}' for mode in ('1s', '2s')]
    assert len(names) == len(set(names)) == 14
    rows = []
    for name in names:
        run = runs[name]
        assert run['complete'] and run['rows'], name
        failures = [row for row in run['rows'] if row['status'] != 'ok']
        if name == 'post-v2-extra-uring':
            assert len(failures) == 1 and failures[0]['job'] == 'rootcompat-stringlimit', failures
        else:
            assert not failures, (name, failures)
        rows.append(dict(run=name, passed=run['passed'], failed=run['failed'],
                         jobs=sorted({row['job'] for row in run['rows']})))
    old_index = json.loads((DOC/'gate-receipts/index.json').read_text())
    old = next(row for row in old_index if row['label'] == 'pre-stringlimit')
    archive = Path(old['archive'])
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == old['archive_sha256']
    member = 'jobs/rootcompat-stringlimit/rootcompat.log'
    with tarfile.open(archive) as source:
        pre = source.extractfile(member).read().decode()
    post = (Path(runs['post-v2-extra-uring']['source'])/member).read_text()
    failures = lambda text: [line for line in text.splitlines() if line.startswith('FAIL ')]
    assert len(failures(pre)) == 24 and failures(pre) == failures(post)
    witness_rows = json.loads((DOC/'witnesses.json').read_text())
    pad_rows = []
    for name, expected in [('pad-a-v2-final', 6), ('pad-b-v2-gate', 0)]:
        assert runs[name]['complete'] and runs[name]['failed'] == expected
        if expected:
            assert {row['job'] for row in runs[name]['rows'] if row['status'] != 'ok'} == {
                'cmdfix2-'+case for case in ('geo', 'scores', 'hll', 'lcs', 'channels', 'xsetid')}
        for witness in witness_rows:
            path = Path(runs[name]['source'])/'jobs'/('cmdfix2-'+witness['case'])/'proof/summary.json'
            legs = json.loads(path.read_text())
            assert len(legs) == len({leg['leg'] for leg in legs}) == 32
            differences = sum(len(leg['failures']) for leg in legs)
            target = witness['PRE' if expected else 'POST']['differences']
            assert differences == target, (name, witness['case'], differences, target)
            pad_rows.append(dict(run=name, case=witness['case'], differences=differences))
    save(DOC/'final-jobs.json', dict(
        post_sha256=hashlib.sha256((BUILD/'POST').read_bytes()).hexdigest(),
        runs=rows, unchanged_stringlimit_failures=failures(post),
        pad_controls=pad_rows))


def tcl_summary(runs):
    manifest = json.loads((DOC/'tcl-manifest.json').read_text())['files']
    digest = hashlib.sha256((BUILD/'POST').read_bytes()).hexdigest()
    result = []
    for engine in ('uring', 'epoll'):
        run = 'post-v2-tcl-receipted-' + engine
        assert runs[run]['complete'] and runs[run]['failed'] == 0
        root = Path(runs[run]['source'])/'jobs/redis_tcl'
        for mode in ('1s', '2s'):
            path = root/('redis-tcl-'+mode)/'summary.json'
            summary = json.loads(path.read_text())
            assert summary['binary_sha256'] == digest and summary['mode'] == mode
            rows = summary['rows']
            assert all(row['complete'] and row['error'] is None for row in rows)
            assert all(row['server_argv'][row['server_argv'].index('--net-io')+1] == engine
                       for row in rows)
            files = []
            for name, expected in manifest.items():
                group = [row for row in rows if row['file'] == name]
                passed = [event['test'] for row in group for event in row['events']
                          if event['status'] == 'ok']
                assert Counter(passed) == Counter(expected['passed_tests']), (run, mode, name)
                errors = [error for row in group for error in row.get('setup_errors', [])]
                assert errors == expected.get('known_setup_errors', []), (run, mode, name, errors)
                files.append(dict(file=name, required_passes=len(passed), known_setup_errors=errors))
            assert sum(row['required_passes'] for row in files) == 311
            fences = sum(row.get('pubsub_fences', 0) for row in rows)
            assert fences == 1
            result.append(dict(engine=engine, mode=mode, files=files, pubsub_fences=fences,
                               summary_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    save(DOC/'tcl-summary.json', result)


def auditor_summary(archive):
    folder = BUILD / 'audit-post-v2'; rows = []
    def objects(path):
        return [json.loads(line) for line in path.read_text().splitlines() if line.startswith('{')]
    for path in sorted(folder.glob('*.jsonl')):
        for row in objects(path):
            if 'summary' in row:
                rows.append(dict(file=path.name, **row))
            elif 'lcs_reply' in row:
                rows.append(dict(file=path.name, **row))
    comparisons = []
    for label in ('T40', 'T47', 'T21', 'T21b'):
        def result(mode):
            return next(r['result'] for r in objects(folder / f'{label}-{mode}.jsonl') if r.get('test') == label)
        oracle = result('oracle')
        for mode in ('1s', '2s'):
            candidate = result(mode)
            assert candidate.keys() == oracle.keys()
            differences = {k: dict(oracle=oracle[k], candidate=candidate[k])
                           for k in oracle if oracle[k] != candidate[k]}
            comparisons.append(dict(test=label, mode=mode, fields=len(oracle), differences=differences))
    save(DOC / 'auditors.json', dict(data=rows, complex=comparisons))
    if archive:
        output = DOC / 'auditor-receipts'; output.mkdir(exist_ok=True)
        old = json.loads((output / 'index.json').read_text()) if (output / 'index.json').exists() else []
        labels = {row['label'] for row in old}
        for label in ('audit-pre-T40', 'audit-post', 'audit-post-v2'):
            if label not in labels: old.append(receipts.collect(label, BUILD / label, output))
        save(output / 'index.json', old)


def local_check_receipts():
    """Retain serverless checks and exact supplemental job invocations."""
    output = DOC / 'local-checks'; output.mkdir(exist_ok=True)
    selected = set()
    for pattern in ('gates-test*.log', 'gateplan-test.log', 'redis-tcl-test*.log',
                    'final-build-*.log', 'fresh-*.log', 'freshness-final.log',
                    '*jobs*.json', 'final-supplemental-v2.json', 'post-v2-main-*.json',
                    'pad-a-v2-final.json', 'pad-v2-final-build.log',
                    'whitespace-control/*.log'):
        selected.update(BUILD.glob(pattern))
    rows = []
    for source in sorted(selected):
        data = source.read_bytes()
        name = source.relative_to(BUILD).as_posix().replace('/', '-')
        (output / name).write_bytes(data)
        rows.append(dict(file=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
    save(output / 'index.json', rows)


def main():
    assert os.sched_getaffinity(0) <= set(range(100, 112))
    parser = argparse.ArgumentParser(); parser.add_argument('--archive', action='store_true')
    parser.add_argument('--final', action='store_true')
    args = parser.parse_args()
    original = receipts.selected
    receipts.selected = lambda path, root: original(path, root) or (
        path.suffix == '.jsonl' and not {'checkout', 'data', 'appendonlydir'} & set(path.relative_to(root).parts))
    instruction_table()
    runs = gate_runs(args.archive)
    witnesses(runs)
    differential_summary(runs, args.final)
    if args.final:
        final_jobs(runs)
        tcl_summary(runs)
    auditor_summary(args.archive)
    if args.archive: local_check_receipts()
    with (DOC / 'arms.sha256').open('w') as out:
        for arm in ('PRE', 'POST', 'PAD-A', 'PAD-B'):
            path = BUILD / arm
            out.write(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + str(path.relative_to(ROOT)) + '\n')


if __name__ == '__main__':
    main()
