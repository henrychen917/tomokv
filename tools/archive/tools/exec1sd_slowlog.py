#!/usr/bin/env python3
"""Replay the unchanged isolated upstream assertion on frozen PRE and POST.

This is a bounded correctness diagnosis, not a replacement gate verdict.
Every failed attempt remains in the receipt; no retry turns a failure green.
"""
import argparse
import json
import os
import sys

import exec1sd as d

sys.path.insert(0, str(d.ROOT / 'tests'))
import redis_tcl as tcl


def main():
    assert os.sched_getaffinity(0) <= set(range(64, 96))
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', default='slowlog-replay')
    parser.add_argument('--attempts', type=int, default=8)
    parser.add_argument('--arms', default='PRE,POST')
    parser.add_argument('--modes', default='1s,2s')
    opts = parser.parse_args()
    assert 1 <= opts.attempts <= 64
    assert '/' not in opts.label and opts.label.startswith('slowlog-')
    assert set(opts.arms.split(',')) <= {'PRE', 'POST'}
    assert set(opts.modes.split(',')) <= {'1s', '2s'}
    out = d.OUT / opts.label
    assert not out.exists(), 'keep previous failure receipts'
    tree = out / 'checkout'
    redis = d.ROOT.parent / 'redis'
    tcl.prepare(redis, tree, controller_port=20001)
    name = 'SLOWLOG - Rewritten commands are logged as their original command'
    expected = name + ' in tests/unit/slowlog.tcl'
    rows = []
    arms = {row['arm']: row for row in json.loads((d.DOCS / 'arms.json').read_text())}
    for mode in opts.modes.split(','):
        for attempt in range(opts.attempts):
            for arm in opts.arms.split(','):
                binary = d.OUT / arm
                assert d.sha(binary) == arms[arm]['sha256']
                args = argparse.Namespace(output=out / f'{mode}-{arm}-{attempt}',
                    binary=binary, mode=mode, cores='64-71', port=20000,
                    baseport=20002, idle_timeout=60, file_timeout=240,
                    ratio='6:2', arm_smove=False)
                row = tcl.run_file(args, tree, 'unit/slowlog', only=[name])
                try:
                    tcl.validate_passing(row, [expected])
                    passed = True
                except ValueError:
                    passed = False
                rows.append(dict(arm=arm, mode=mode, attempt=attempt,
                    binary_sha256=d.sha(binary), passed=passed,
                    result=str(args.output / 'unit/slowlog/result.json'),
                    failures=[e for e in row['events'] if e['status'] == 'err'],
                    error=row['error'], complete=row['complete']))
                d.save(d.DOCS / (opts.label + '.json'), dict(
                    upstream_sha256=d.sha(redis / 'tests/unit/slowlog.tcl'),
                    driver_sha256=d.sha(d.ROOT / 'tests/redis_tcl.py'),
                    test=expected, rows=rows))
                print(arm, mode, attempt, 'PASS' if passed else 'FAIL', flush=True)


if __name__ == '__main__':
    main()
