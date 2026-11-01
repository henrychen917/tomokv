#!/usr/bin/env python3
"""Index complete gate witnesses for the added integration subchecks."""
import hashlib
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/wave13'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    post = sha(ROOT / 'build/wave13/tomokv-POST')
    receipts = []
    for path in (DOC / 'jobs').glob('landing-*.json'):
        record = json.loads(path.read_text())
        if (record.get('binary_sha256') == post and record.get('binary_unchanged') and
                record.get('source_tree_unchanged') and record.get('tests_tools_unchanged') and
                record.get('env', {}).get('LC_ALL') == 'C' and 'artifacts' in record):
            receipts.append((record['started'], path, record))

    used = {}

    def job(name):
        for _, path, record in sorted(receipts, reverse=True):
            folder = Path(record['artifacts']) / 'jobs' / name
            if (folder / 'done').exists():
                done = list(map(int, (folder / 'done').read_text().split()))
                if done[0] == done[2] == 0:
                    used[name] = dict(receipt=str(path.relative_to(ROOT)),
                                      receipt_sha256=sha(path), artifact=str(folder))
                    return folder
        raise AssertionError('No passing whole-job receipt for ' + name)

    unit = job('flipfix6_units')
    units = []
    for name in ('flipfix6.txt', 'tsan-core-concurrency-tsan-flipfix6.log'):
        lines = (unit / name).read_text().splitlines()
        old = [line for line in lines if line.startswith('ARMED flipfix6 ')]
        added = [line for line in lines if line.startswith('ARMED wave13 ')]
        assert len(old) == 54 and len(added) == 12, (name, old, added)
        units.append(dict(log=name, original_cases=len(old), integration_cases=added,
                          sha256=sha(unit / name)))

    live = job('flipfix6')
    storms, semantics = [], []
    for directory, cases, workers in (
            ('flipfix6', ('exec', 'p1', 'p2', 'p3', 'watch', 'semantics', 'exec-close'), 6),
            ('flipfix6-scale', ('exec', 'exec-close'), 48)):
        path = live / directory / 'results.json'
        results = json.loads(path.read_text())
        results_sha256 = sha(path)
        expected = {f'2s-{engine}-{atomic}-db{db}-{case}'
                    for db, engine, atomic, case in itertools.product((1, 16), ('uring', 'epoll'), (0, 1), cases)}
        assert len(results) == len(expected) and {r['leg'] for r in results} == expected
        assert all(r['pass'] for r in results)
        for row in results:
            result = row['result']
            if row['leg'].endswith('-semantics'):
                assert {r['case'] for r in result} == {
                    'watch-clean', 'watch-dirty', 'watch-flushall', 'watch-flushdb',
                    'watch-config', 'queue', 'queue-error', 'discard', 'reset'}
                assert all(r['session_moves'] == 1 and r['flip_seconds'] < 1 for r in result)
                semantics.append(dict(leg=row['leg'], cases=result))
                continue
            assert result['pings'] > 0 and result['ping_max'] < 1 and result['errors'] == []
            assert len(result['workers']) == workers and result['sessions_moved'] > 0
            assert all(r['max_gap'] < 1 and r['ops'] > 0 for r in result['workers'])
            storms.append(dict(group=directory, leg=row['leg'], workers=workers,
                               pings=result['pings'], ping_max_seconds=result['ping_max'],
                               max_flip_seconds=max(r['seconds'] for r in result['flips']),
                               flips=len(result['flips']), sessions_moved=result['sessions_moved'],
                               s2_refusals=result['flip_refused_s2'], close_refusals=result['flip_refused_close'],
                               results_sha256=results_sha256))

    siblings = []
    for db in (1, 16):
        path = live / f'flush-live-flip-db{db}/results.json'
        rows = json.loads(path.read_text())
        expected = {'redis-redis-0', '2s-uring-0', '2s-uring-1', '2s-epoll-0', '2s-epoll-1'}
        assert len(rows) == len(expected) and {r['leg'] for r in rows} == expected
        assert all(r['pass'] and r['case'] == 'live-flip' for r in rows)
        siblings.append(dict(databases=db, legs=rows, results_sha256=sha(path)))

    persistence = job('persistfmt')
    boundaries, failures = [], []
    for mode, engine in itertools.product(('1s', '2s'), ('epoll', 'uring')):
        for case in ('save', 'bgsave', 'shutdown', 'reload', 'aof-yes'):
            path = persistence / f'persistfmt-{case}-{mode}-{engine}/events.jsonl'
            events = [json.loads(line) for line in path.read_text().splitlines()]
            boundary = [r for r in events if r['event'] == 'wave13_flush_function_boundary']
            assert len(boundary) == 2 and {r['oracle'] for r in boundary} == {True, False}
            assert all(r['case'] == case and not r['function_flush_invalidates'] for r in boundary)
            assert sum(r['event'] == 'functions_after_restart' for r in events) == 2
            boundaries.append(dict(mode=mode, engine=engine, case=case, checks=boundary,
                                   events_sha256=sha(path)))
        path = persistence / f'persistfmt-aof-failure-{mode}-{engine}/events.jsonl'
        events = [json.loads(line) for line in path.read_text().splitlines()]
        commands = [r['command'] for r in events if r['event'] == 'aof_failure_command']
        windows = [r for r in events if r['event'] == 'failure_window_armed']
        limits = [r for r in events if r['event'] == 'wave13_flush_aof_limit']
        assert commands == ['SET', 'FLUSHALL', 'FLUSHDB']
        assert len(windows) == 3 and all(r['threads'] for r in windows)
        assert [r['command'] for r in limits] == ['FLUSHALL', 'FLUSHDB']
        assert all(r['bytes'] > 80 for r in limits)
        failures.append(dict(mode=mode, engine=engine, commands=commands,
                             windows=windows, limits=limits, events_sha256=sha(path)))
    job('persistfmt_aof_error')
    job('trackorder')
    job('maxmemrace')
    admission_controls = []
    for case, modes in (('T6', ('1s', '2s')), ('T10', ('2s',))):
        folder = job('at412-' + case)
        path = folder / ('at412-' + case) / 'results.json'
        rows = json.loads(path.read_text())
        expected = {f'redis-redis-0-{command}' for command in ('EVAL', 'EVALSHA', 'FCALL')} | {
            f'{mode}-{engine}-{atomic}-{command}' for mode, engine, atomic, command in
            itertools.product(modes, ('uring', 'epoll'), (0, 1), ('EVAL', 'EVALSHA', 'FCALL'))}
        assert len(rows) == len(expected) and {r['leg'] for r in rows} == expected
        assert all(r.get('pass') for r in rows)
        admission_controls.append(dict(case=case, passing_legs=sorted(expected),
                                        results_sha256=sha(path),
                                        mix='scripts, EXEC, WATCH/EXEC, plain writers' if case == 'T6'
                                            else 'original T10 scripts/plain writers with FLIP; session storm is covered separately'))
    output = dict(binary_sha256=post, gate_jobs=used, sanitizer_units=units,
                  ping_probed_storm_legs=storms, moved_session_semantics=semantics,
                  flush_live_flip=siblings, function_flush_restart_boundaries=boundaries,
                  aof_failure_windows=failures,
                  headline_admission_controls=admission_controls,
                  scheduled_aof_twin=dict(path='build/persistfmt/scheduled/tomokv',
                      sha256=sha(ROOT / 'build/persistfmt/scheduled/tomokv'),
                      production_aof_source_sha256=sha(ROOT / 'src/persist/aof.cc'),
                      schedule_generator_sha256=sha(ROOT / 'tools/persistfmt_schedule.py'),
                      note='Gate-owned scheduling twin: merged production objects, with AOF-only timing latches compiled from the merged AOF source.'),
                  note='Gap values verify the original one-second correctness bound. No rate, throughput, cycles or IPC claim.', passed=True)
    (DOC / 'interaction-receipts.json').write_text(json.dumps(output, indent=2) + '\n')
    print(len(storms), 'PING-probed storm legs;', len(semantics), 'session matrices;',
          2 * len(boundaries), 'oracle/target persistence boundaries; 12 armed AOF failure windows')


if __name__ == '__main__':
    main()
