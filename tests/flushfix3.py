#!/usr/bin/env python3
"""Bounded idle FLUSH completion witness; no throughput measurement.

Each fresh server receives only one outstanding FLUSH at a time. The complete
sample is retained, and a single deadline miss fails (no percentile tolerance).
"""
import argparse
import json
import os
from pathlib import Path
import time
import traceback

from snapfix import Boot


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', required=True)
    p.add_argument('--cores', default='0-7')
    p.add_argument('--port', type=int, default=20100)
    p.add_argument('--databases', type=int, choices=[1, 16], default=16)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--calls', type=int, default=1000)
    p.add_argument('--deadline-ms', type=float, default=5)
    p.add_argument('--modes', nargs='+', default=['1s', '2s'])
    p.add_argument('--engines', nargs='+', default=['uring', 'epoll'])
    p.add_argument('--atomics', nargs='+', type=int, default=[0, 1])
    a = p.parse_args()
    assert 1024 <= a.port < 32768 and a.calls > 0 and a.deadline_ms > 0
    a.stall = 5
    os.environ['LC_ALL'] = 'C'
    a.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for mode in a.modes:
        for engine in a.engines:
            for atomic in a.atomics:
                leg = f'{mode}-{engine}-{atomic}'
                row = dict(leg=leg, databases=a.databases, passed=False, samples=[])
                try:
                    with Boot(a, a.output / leg, mode, engine, atomic, False) as b:
                        b.c.must('SELECT', 7 if a.databases > 1 else 0)
                        for command in ('FLUSHALL', 'FLUSHDB'):
                            for option in ('SYNC', 'ASYNC'):
                                samples = []
                                for i in range(a.calls):
                                    # Leave no producer to wake a stranded continuation;
                                    # vary the idle phase relative to the 50 ms cron tick.
                                    time.sleep(0.001 + (i % 7) * 0.0001)
                                    begin = time.monotonic_ns()
                                    reply = b.c.must(command, option)
                                    samples.append(time.monotonic_ns() - begin)
                                    assert reply == b'OK', reply
                                    if samples[-1] > a.deadline_ms * 1e6:
                                        break  # A failed deadline needs no further traffic.
                                row['samples'].append(dict(command=command, option=option,
                                    ns=samples, maximum_ns=max(samples),
                                    required_calls=a.calls,
                                    misses=sum(n > a.deadline_ms * 1e6 for n in samples)))
                    row['passed'] = all(s['misses'] == 0 and len(s['ns']) == a.calls
                                        for s in row['samples'])
                except Exception:
                    row['error'] = traceback.format_exc()
                rows.append(row)
                (a.output / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
                print(leg, 'PASS' if row['passed'] else 'FAIL',
                      [(s['command'], s['option'], s['maximum_ns'], s['misses'])
                       for s in row['samples']], flush=True)
    return int(not all(r['passed'] for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
