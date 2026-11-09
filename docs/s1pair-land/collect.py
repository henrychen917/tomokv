#!/usr/bin/env python3
"""Collect completed selected-job evidence; never starts a server or a gate."""
import hashlib
import itertools
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'build/s1pair-land'
OUT = Path(__file__).resolve().parent
TAGS = ('pre-s1pair', 'post-s1pair', 'post-existing', 'post-differ')


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def differential_receipts(run):
    plan = json.loads((run / 'differ-plan.json').read_text())
    receipt = dict(plan=plan, folds={}, parts={})
    for group in ('split', 'armed'):
        receipt['folds'][group] = json.loads((run / ('differ-' + group + '-fold.json')).read_text())
    for part in ('split-0', 'split-1', 'armed-0', 'armed-1', 'equivalence'):
        directory = run / 'jobs' / ('differ-' + part) / 'differ'
        record = dict(completion=json.loads((directory / 'complete.json').read_text()))
        if part == 'equivalence':
            record['streams'] = []
            for seed in plan['equivalence_seeds']:
                folder = directory / ('mode-equivalence-' + str(seed))
                record['streams'].append(dict(
                    manifest=json.loads((folder / 'stream.json').read_text()),
                    results=json.loads((folder / 'results.json').read_text())))
        else:
            record['legs'] = []
            record['commands'] = {}
            for line in (directory / 'legs.tsv').read_text().splitlines():
                suite, atomic, seed, repeat, code, filename = line.split('\t')
                coverage = json.loads((directory / (filename + '.coverage.json')).read_text())
                counts = coverage['commands']
                record['legs'].append(dict(suite=suite, atomic=int(atomic), seed=int(seed),
                                           repeat=int(repeat), returncode=int(code),
                                           comparisons=sum(counts.values())))
                for command, count in counts.items():
                    record['commands'][command] = record['commands'].get(command, 0) + count
            if part.startswith('armed-'):
                record['read_local_samples'] = (directory / ('read-local-a' + part[-1] + '.tsv')).read_text()
        receipt['parts'][part] = record
    payload = json.dumps(receipt, indent=2) + '\n'
    assert len(payload.encode()) <= 1_000_000
    (OUT / 'differ-results.json').write_text(payload)


def main():
    result = {'scope': 'selected correctness jobs only; no full gate or rate measurements',
              'batches': {}, 'arms': {}}
    existing = re.search(r'JOBS="(.*?)"', (OUT / 'run_existing.sh').read_text(), re.S)[1].split()
    expected = {
        'pre-s1pair': {'release', 's1pair'},
        'post-s1pair': {'release', 's1pair'},
        'post-existing': set(existing) | {'release', 'production_units'},
        'post-differ': {'release', 'differ-split-0', 'differ-split-1',
                        'differ-armed-0', 'differ-armed-1', 'differ-equivalence'},
    }
    for tag in TAGS:
        rc = int((BUILD / (tag + '.rc')).read_text())
        log = (BUILD / (tag + '.log')).read_text()
        run = Path(re.search(r'  artifacts: (.*)', log)[1])
        names = re.search(r'^PARTIAL jobs \(including prerequisites\): (.*)$', log, re.M)[1].split()
        assert len(names) == len(set(names)) and set(names) == expected[tag], (tag, names)
        jobs = []
        for name in names:
            directory = run / 'jobs' / name
            code, passed, failed = map(int, (directory / 'done').read_text().split())
            ledger = directory / 'ledger'
            rows = []
            if ledger.exists():
                for line in ledger.read_text().splitlines():
                    verdict, seconds, label = line.split('\t', 2)
                    rows.append(dict(verdict=verdict, seconds=float(seconds), label=label))
            assert sum(r['verdict'] == 'ok' for r in rows) == passed, (tag, name)
            assert sum(r['verdict'] == 'FAIL' for r in rows) == failed, (tag, name)
            jobs.append(dict(job=name, returncode=code, passed=passed, failed=failed, rows=rows,
                             artifacts=str(directory.relative_to(ROOT))))
        result['batches'][tag] = dict(returncode=rc, run=str(run.relative_to(ROOT)), jobs=jobs,
                                     passed=sum(j['passed'] for j in jobs),
                                     failed=sum(j['failed'] for j in jobs))
        public_rows = []
        for line in (BUILD / (tag + '.ledger.partial')).read_text().splitlines():
            verdict, seconds, label = line.split('\t', 2)
            if verdict == 'PARTIAL':
                continue
            assert verdict in ('ok', 'FAIL'), (tag, line)
            public_rows.append(dict(verdict=verdict, seconds=float(seconds), label=label))
        result['batches'][tag]['public_rows'] = public_rows
        for suffix in ('.log', '.ledger.partial', '.ledger.partial.timings'):
            source = BUILD / (tag + suffix)
            assert source.stat().st_size <= 1_000_000, source
            shutil.copy2(source, OUT / source.name)
    for arm in ('pre', 'post'):
        record = json.loads((BUILD / (arm + '-arm.json')).read_text())
        assert sha256(Path(record['path'])) == record['sha256'], arm
        result['arms'][arm] = record
    production = Path(result['batches']['post-existing']['run']) / 'unit-ready'
    result['fresh_unit_markers'] = sorted(p.name for p in (ROOT / production).iterdir())
    live_cases = [f'T{i}' for i in range(1, 17) if i != 11] + ['T11a', 'T11b']
    result['at412'] = []
    for case in live_cases:
        run = ROOT / result['batches']['post-existing']['run'] / 'jobs' / ('at412-' + case)
        source = run / ('at412-' + case) / 'results.json'
        records = json.loads(source.read_text())
        modes = ['2s'] if case in ('T3', 'T10', 'T11a') else ['1s', '2s']
        expected_legs = {f'redis-redis-0-{cmd}' for cmd in ('EVAL', 'EVALSHA', 'FCALL')}
        expected_legs.update('-'.join(map(str, leg)) for leg in itertools.product(
            modes, ['uring', 'epoll'], [0, 1], ['EVAL', 'EVALSHA', 'FCALL']))
        observed = [r['leg'] for r in records]
        assert len(observed) == len(set(observed)), (case, observed)
        result['at412'].append(dict(
            case=case, expected_legs=len(expected_legs), observed_legs=len(observed),
            missing=sorted(expected_legs - set(observed)), extra=sorted(set(observed) - expected_legs),
            passed=sum(bool(r.get('pass')) for r in records),
            failed=[r for r in records if not r.get('pass')],
            unarmed_attempts=[leg for r in records for leg in r.get('unarmed_attempts', [])],
            deviations=[dict(leg=r['leg'], deviation=r['deviation']) for r in records if 'deviation' in r],
            artifacts=str(source.relative_to(ROOT))))
    payload = json.dumps(result, indent=2) + '\n'
    assert len(payload.encode()) <= 1_000_000
    (OUT / 'job-results.json').write_text(payload)
    differential_receipts(ROOT / result['batches']['post-differ']['run'])
    for tag, batch in result['batches'].items():
        print(tag, len(batch['jobs']), 'jobs;', batch['passed'], 'ok;', batch['failed'], 'FAIL;',
              'rc', batch['returncode'], '; public rows',
              sum(r['verdict'] == 'ok' for r in batch['public_rows']), 'ok /',
              sum(r['verdict'] == 'FAIL' for r in batch['public_rows']), 'FAIL')


if __name__ == '__main__':
    main()
