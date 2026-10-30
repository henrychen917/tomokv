#!/usr/bin/env python3
"""Reconcile the planned job geometries with complete, hash-bound POST attempts."""
import json
from pathlib import Path
from collect_jobs import collect

DOC = Path(__file__).resolve().parent
POSTS = {
    'ed88bd649b62eeec920e23aa21f360470e67df968f02f8e351340b8aad2a2173',
    '844cf188071bae335a80e8ae15c2acaec2d1f583f235edf4bf4496421299660e',
}


def main():
    matrix = json.loads((DOC / 'correctness-matrix.json').read_text())
    runs = collect()['runs']
    seen = []
    for run in runs:
        if run['binary_sha256'] not in POSTS or 'TOMO_SCRIPTFIX2_BREAK' in run['env']:
            continue
        for job in run['jobs']:
            if job['complete']:
                seen.append(dict(name=job['name'], run=run['name'], artifact=job['artifact'],
                                 engine=run['env']['GATE_NET_IO'],
                                 fused=run['env']['GATE_TXN_FUSED'],
                                 atomic=run['env'].get('GATE_TXN_ATOMIC', '1'),
                                 passed=job['exit'] == 0 and job['failed'] == 0))
    wanted = []

    def add(names, engines=(None,), modes=(None,), atomic=None):
        for name in names:
            for engine in engines:
                for fused in modes:
                    wanted.append(dict(name=name, engine=engine, fused=fused, atomic=atomic))

    add(matrix['once'] + matrix['new_lanes_once'])
    add(matrix['each_mode'], modes=('0', '1'))
    add(matrix['each_engine'], engines=('uring', 'epoll'))
    add(matrix['each_mode_engine'], engines=('uring', 'epoll'), modes=('0', '1'))
    add(matrix['script_bounds_atomic0_each_mode_engine'], engines=('uring', 'epoll'),
        modes=('0', '1'), atomic='0')
    add(['compat2', 'redis_tcl', 'abba_selftest'])
    rows = []
    for requirement in wanted:
        matches = [v for v in seen if all(value is None or v[key] == value
                                          for key, value in requirement.items())]
        rows.append(dict(**requirement, complete=bool(matches),
                         passed=any(v['passed'] for v in matches), attempts=matches))
    result = dict(note='Coverage of planned whole-job geometries, not a full-gate receipt. '
                       'The two accepted POST hashes have identical executable bytes; their '
                       'strict section bridge is source-labels-identity.json. Differential '
                       'coverage is separately recorded in differential-final.json. '
                       'A later pass does not erase an earlier failed attempt.', requirements=rows)
    (DOC / 'correctness-coverage.json').write_text(json.dumps(result, indent=2) + '\n')
    for row in rows:
        if not row['passed']:
            print('MISSING' if not row['complete'] else 'FAILED',
                  row['name'], row['engine'], row['fused'], row['atomic'])
    print('requirements', len(rows), 'complete', sum(v['complete'] for v in rows),
          'passing attempt', sum(v['passed'] for v in rows))


if __name__ == '__main__':
    main()
