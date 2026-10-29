#!/usr/bin/env python3
"""FLUSH publication witnesses. Each leg owns its server and records observations.

The original snapfix witnesses are imported unchanged. Namespace witnesses rearm
only while the observer is parked; FLUSH is the sole mutation in its window.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import queue
import threading
import time
import traceback

import snapfix as s
import snapfix2_flush as original
from _lib import Conn


def namespace_only(args, directory, mode, engine, atomic, oracle):
    db = 7 if args.databases > 1 and args.command == 'FLUSHDB' else 0
    control_db = 11
    with s.Boot(args, directory, mode, engine, atomic, oracle) as b:
        b.c.must('SELECT', db)
        pair, owners = s.keys_for(b.c, 'flushfix2:pair', oracle, 2)
        work = queue.Queue()
        counts = dict(cycles=0, observations=0, torn=0, controls=0)
        examples = []
        if db:
            b.c.must('SELECT', control_db)
            b.c.must('MSET', pair[0], 'control', pair[1], 'control')
            b.c.must('SELECT', db)

        def mutate(stop):
            try:
                with contextlib.closing(Conn('127.0.0.1', b.port, timeout=args.stall)) as c:
                    c.must('SELECT', db)
                    while not stop.is_set():
                        for key in pair:
                            assert c.must('SET', key, 1) == b'OK'
                        active, ready, done = (threading.Event() for _ in range(3))
                        active.set()
                        work.put((active, ready, done))
                        assert ready.wait(args.stall), 'observer never armed'
                        try:
                            assert c.must(args.command, args.flush_mode) == b'OK'
                        finally:
                            active.clear()
                        assert done.wait(args.stall), 'observer never parked'
                        counts['cycles'] += 1
            finally:
                work.put(None)

        def observe(stop):
            with contextlib.closing(Conn('127.0.0.1', b.port, timeout=args.stall)) as c:
                c.must('SELECT', db)
                while True:
                    request = work.get(timeout=args.stall)
                    if request is None:
                        break
                    active, ready, done = request
                    try:
                        while active.is_set():
                            values = c.must('MGET', *pair)
                            counts['observations'] += 1
                            ready.set()
                            if values not in ([None, None], [b'1', b'1']):
                                counts['torn'] += 1
                                if len(examples) < 20:
                                    examples.append([None if v is None else int(v) for v in values])
                            if db:
                                c.must('SELECT', control_db)
                                assert c.must('MGET', *pair) == [b'control', b'control']
                                counts['controls'] += 1
                                c.must('SELECT', db)
                    finally:
                        done.set()

        errors = s.run_storm(args.seconds, [mutate, observe], args.stall)
        result = dict(**counts, pair=pair, owners=owners, db=db,
                      control_db=control_db if db else None, examples=examples,
                      errors=errors, counters={} if oracle else s.stats(b.c))
        (directory / 'observations.json').write_text(json.dumps(result, indent=2) + '\n')
        assert not errors and counts['cycles'] > 0 and counts['observations'] > 0, result
        assert not db or counts['controls'] > 0, result
        assert counts['torn'] == 0, result
        return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case', choices=['flush-pair', 'flush-script', 'flush-only', 'namespace'], required=True)
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', required=True)
    p.add_argument('--cores', default='0-7')
    p.add_argument('--port', type=int, default=20100)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--modes', nargs='+', default=['1s', '2s'])
    p.add_argument('--engines', nargs='+', default=['uring', 'epoll'])
    p.add_argument('--atomics', nargs='+', type=int, default=[0, 1])
    p.add_argument('--databases', type=int, choices=[1, 16], default=16)
    p.add_argument('--command', choices=['FLUSHALL', 'FLUSHDB'], default='FLUSHALL')
    p.add_argument('--flush-mode', choices=['SYNC', 'ASYNC'], default='SYNC')
    p.add_argument('--seconds', type=float, default=6)
    p.add_argument('--stall', type=float, default=10)
    p.add_argument('--no-oracle', action='store_true')
    args = p.parse_args()
    assert 20100 <= args.port < 20199
    os.environ['LC_ALL'] = 'C'
    cases = {'flush-pair': original.case_flush_pair,
             'flush-script': lambda *a: original.case_flush_pair(*a, script=True),
             'flush-only': original.case_flush_only, 'namespace': namespace_only}
    legs = ([] if args.no_oracle else [('redis', 'redis', 0, True)]) + [
        (m, e, a, False) for m in args.modes for e in args.engines for a in args.atomics]
    results = []
    args.output.mkdir(parents=True, exist_ok=True)
    for mode, engine, atomic, oracle in legs:
        label = f'{mode}-{engine}-{atomic}'
        row = dict(case=args.case, leg=label, databases=args.databases,
                   command=args.command, flush_mode=args.flush_mode)
        began = time.monotonic()
        try:
            row['value'] = cases[args.case](args, args.output / label, mode, engine, atomic, oracle)
            row['pass'] = True
        except Exception:
            row.update(pass_=False, error=traceback.format_exc())
        row['seconds'] = round(time.monotonic() - began, 3)
        results.append(row)
        print(json.dumps(row), flush=True)
        (args.output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    return int(any(not r.get('pass') for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
