#!/usr/bin/env python3
"""Retain and validate the complete wave12 lane witnesses, including every leg."""
import argparse
import gzip
import hashlib
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/wave12'
OUT = DOC / 'lane-proofs'


def read(path):
    return json.loads(path.read_text())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def archive(path, relative, index):
    data = path.read_bytes()
    dest = OUT / (str(relative) + '.gz')
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(gzip.compress(data, mtime=0))
    index.append(dict(source=str(path.relative_to(ROOT)), source_sha256=sha(data),
                      archive=str(dest.relative_to(ROOT)), archive_sha256=sha(dest.read_bytes())))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--primary-only', action='store_true')
    args = parser.parse_args()
    post = sha((ROOT / 'build/wave12/tomokv-POST').read_bytes())
    receipt = read(DOC / 'jobs/landing-main-2s-uring.json')
    assert receipt['binary_sha256'] == post and receipt['binary_unchanged']
    jobs = Path(receipt['artifacts']) / 'jobs'
    index, findings = [], {}
    for job in ('flushfix2', 'flushfix2_units', 'flushfix3_units', 'trackorder', 'maxmemrace'):
        done = list(map(int, (jobs / job / 'done').read_text().split()))
        assert done[0] == done[2] == 0, (job, done)

    flush = jobs / 'flushfix2'
    target_legs = {f'{mode}-{engine}-{atomic}' for mode, engine, atomic in
                   itertools.product(('1s', '2s'), ('uring', 'epoll'), (0, 1))}
    result_files = sorted(flush.glob('*/results.json'))
    assert len(result_files) == 14
    for path in result_files:
        rows = read(path)
        assert len(rows) == 9 and all(r['pass'] for r in rows), path
        assert {r['leg'] for r in rows} == target_legs | {'redis-redis-0'}, path
    falsifiers = sorted(flush.rglob('falsifiers.json'))
    assert len(falsifiers) == 112
    counters = ('atomic_flush_units', 'atomic_flush_range_reads', 'atomic_flush_post_versions',
                'atomic_flush_script_conflicts', 'atomic_flush_slow_collapses', 'script_chunk_cache_hits')
    for path in falsifiers:
        attempts = read(path)
        assert 1 <= len(attempts) <= 4
        assert all(attempts[-1][k] > 0 for k in counters), path
        assert attempts[-1]['script_reply'] == [1, 1], path
    findings['flushfix2'] = dict(rows=14, target_legs=112, oracle_legs=14,
                                warm_sha_config_range_witnesses=len(falsifiers),
                                counters=list(counters), all_legs_passed=True)

    track = jobs / 'trackorder/proof'
    oracle = read(track / 'oracle.json')
    assert len(oracle) == 864
    track_summary = read(track / 'summary.json')
    expected = {f'db{db}-{mode}-{engine}-a{atomic}-rl{rl}'
                for db, mode, engine, atomic in
                itertools.product((1, 16), ('1s', '2s'), ('epoll', 'uring'), (0, 1))
                for rl in ((0, 1) if mode == '1s' else (0,))}
    assert len(track_summary) == 24 and {r['leg'] for r in track_summary} == expected
    for row in track_summary:
        assert row['passed'] == 864 and row['failed'] == 0
        frames = read(track / row['leg'] / 'frames.json')
        assert len(frames) == 864
        for actual, baseline in zip(frames, oracle):
            assert actual['case'] == baseline['case'] and actual['pass']
            assert actual['streams'] == baseline['streams']
    bindings = read(track / 'binaries.json')
    assert bindings['target'] == post
    findings['trackorder'] = dict(geometries=24, cases_per_geometry=864,
                                 target_cases=24 * 864, oracle_cases=864,
                                 bindings=bindings, all_streams_equal_oracle=True)

    memory = read(jobs / 'maxmemrace/maxmemrace/summary.json')
    assert len(memory['results']) == 49 and memory['trials'] == 3
    targets = [r for r in memory['results'] if not r['oracle']]
    assert len(targets) == 48 and len({r['label'] for r in targets}) == 48
    for row in memory['results']:
        assert row['complete'] and row['assertions_passed'] and row['passed']
        assert not row['failed_trials']
        if not row['oracle']:
            assert row['window_open'], row['label']
    findings['maxmemrace'] = dict(target_geometries=48, oracle_geometries=1,
                                  trials=3, cases=memory['cases'],
                                  every_target_window_open=True, all_assertions_passed=True)

    for name in ('flushfix2', 'flushfix2_units', 'flushfix3_units', 'trackorder', 'maxmemrace'):
        for path in sorted((jobs / name).rglob('*.json')):
            archive(path, Path(name) / path.relative_to(jobs / name), index)

    if args.primary_only:
        output = dict(binary_sha256=post, findings=findings, archives=index, passed=True,
                      scope='Primary lane jobs only; final idle and live-FLIP checks are separate.')
        (DOC / 'primary-semantic-runtime-proof.json').write_text(json.dumps(output, indent=2) + '\n')
        print(json.dumps(findings, indent=2))
        return

    idle_receipt = read(DOC / 'jobs/landing-flush-idle.json')
    assert idle_receipt['exit'] == 0 and idle_receipt['binary_sha256'] == post
    idle = Path(idle_receipt['artifacts']) / 'jobs/flushfix3'
    idle_files = sorted(idle.glob('*/results.json'))
    assert len(idle_files) == 2
    idle_rows = []
    for path in idle_files:
        rows = read(path)
        assert len(rows) == 8 and {r['leg'] for r in rows} == target_legs
        for row in rows:
            assert row['passed'] and len(row['samples']) == 4
            for sample in row['samples']:
                assert sample['misses'] == 0 and len(sample['ns']) == sample['required_calls']
        idle_rows += rows
        archive(path, Path('flushfix3-idle') / path.relative_to(idle), index)
    assert {r['databases'] for r in idle_rows} == {1, 16}
    findings['flushfix3_idle'] = dict(legs=len(idle_rows), all_deadlines_passed=True,
                                     calls=sum(len(s['ns']) for r in idle_rows for s in r['samples']))

    flip = ROOT / 'build/flushfix2/siblings/wave12-final-flip'
    runs = read(flip / 'runs.json')
    assert len(runs) == 2 and all(r['status'] == 0 for r in runs)
    results = {str(db): read(flip / f'live-flip-{db}/results.json') for db in (1, 16)}
    flip_legs = {f'2s-{engine}-{atomic}' for engine, atomic in itertools.product(('uring', 'epoll'), (0, 1))}
    for db, rows in results.items():
        assert len(rows) == 5 and {r['leg'] for r in rows} == flip_legs | {'redis-redis-0'}
        for row in rows:
            assert row['pass'] and row['value']['flushes'] > 0
            assert row['value']['flip_refusals'] == 0
            if not row['leg'].startswith('redis-'):
                assert row['value']['flips'] > 0
    final_flip = dict(binary_sha256=post, runs=runs, results=results,
                      status='PASS: all eight target legs and both oracle legs; positive FLUSH/FLIP witnesses')
    (DOC / 'final-flip.json').write_text(json.dumps(final_flip, indent=2) + '\n')
    findings['live_flip'] = dict(target_legs=8, oracle_legs=2, all_passed=True, refusals=0)
    output = dict(binary_sha256=post, findings=findings, archives=index, passed=True)
    (DOC / 'semantic-runtime-proof.json').write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps(findings, indent=2))


if __name__ == '__main__':
    main()
