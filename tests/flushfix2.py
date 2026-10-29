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
from _lib import Conn, encode


def falsify(b, args):
    """Pin a pre-flush script cut, then read/write under the committed range.

    Counter acknowledgements, not sleep, establish each edge. Fresh scripts and
    keys bound rearming; a window that never opened is always a failure.
    """
    c = b.c
    c.must('SELECT', 7 if args.command == 'FLUSHDB' and args.databases > 1 else 0)
    history = []
    for attempt in range(4):
        pair, _ = s.keys_for(c, f'flushfix2:armed:{attempt}', False, 2)
        for key in pair:
            c.must('SET', key, 5)
        before = s.stats(c)
        with contextlib.closing(Conn('127.0.0.1', b.port, timeout=args.stall)) as script, \
             contextlib.closing(Conn('127.0.0.1', b.port, timeout=args.stall)) as flush:
            db = 7 if args.command == 'FLUSHDB' and args.databases > 1 else 0
            script.must('SELECT', db)
            flush.must('SELECT', db)
            c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 500000)
            c.must('DEBUG', 'SCRIPT-STAGE-WATCH', script.must('CLIENT', 'ID'))
            script.raw(encode('EVAL', s.WRITE, 2, *pair))
            s.wait(lambda: s.stats(c)['script_stage_watch_tasks'] > 0, 'script never gathered', args.stall)
            flush.raw(encode(args.command, args.flush_mode))
            s.wait(lambda: s.stats(c).get('atomic_flush_units', 0) > before.get('atomic_flush_units', 0),
                   'flush never decided', args.stall)
            # These commands run after T while the old script still protects its
            # cut. A separate key avoids legitimately aborting the script here.
            key = f'flushfix2:post:{attempt}'
            assert c.must('GET', key) is None
            assert c.must('SET', key, 'post') == b'OK'
            c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 0)
            reply = script.read()
            assert reply in ([1, 1], [6, 6]), reply
            assert flush.read() == b'OK'
            after = s.stats(c)
            delta = {k: after.get(k, 0) - before.get(k, 0) for k in (
                'atomic_flush_units', 'atomic_flush_range_reads', 'atomic_flush_post_versions',
                'atomic_flush_script_conflicts', 'atomic_flush_slow_collapses')}
            history.append(dict(delta, script_reply=reply))
            if all(delta[k] > 0 for k in delta):
                assert reply == [1, 1], 'OCC retry used the pre-flush script image'
                assert c.must('GET', key) == b'post', 'collapse discarded a post-flush write'
                return history
    raise AssertionError(('flush window did not fire on fresh attempts', history))


class VerifiedBoot(s.Boot):
    def __init__(self, args, *a, **kw):
        self.args = args
        super().__init__(args, *a, **kw)

    def __exit__(self, kind, value, tb):
        try:
            if kind is None and not self.oracle and self.args.require_counters:
                result = falsify(self, self.args)
                (self.directory / 'falsifiers.json').write_text(json.dumps(result, indent=2) + '\n')
        finally:
            super().__exit__(kind, value, tb)


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
                    finally:
                        done.set()

        def control(stop):
            with contextlib.closing(Conn('127.0.0.1', b.port, timeout=args.stall)) as c:
                c.must('SELECT', control_db)
                while not stop.is_set():
                    assert c.must('MGET', *pair) == [b'control', b'control']
                    counts['controls'] += 1

        errors = s.run_storm(args.seconds, [mutate, observe] + ([control] if db else []), args.stall)
        control_final = True
        if db:
            b.c.must('SELECT', control_db)
            control_final = b.c.must('MGET', *pair) == [b'control', b'control']
            b.c.must('SELECT', db)
        result = dict(**counts, pair=pair, owners=owners, db=db,
                      control_db=control_db if db else None, examples=examples,
                      control_final=control_final,
                      errors=errors, counters={} if oracle else s.stats(b.c))
        (directory / 'observations.json').write_text(json.dumps(result, indent=2) + '\n')
        assert not errors and counts['cycles'] > 0 and counts['observations'] > 0, result
        assert not db or counts['controls'] > 0, result
        assert control_final, result
        assert counts['torn'] == 0, result
        return result


CASES = {'flush-pair': original.case_flush_pair,
         'flush-script': lambda *a: original.case_flush_pair(*a, script=True),
         'flush-only': original.case_flush_only, 'namespace': namespace_only}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case', choices=sorted(CASES), required=True)
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
    p.add_argument('--require-counters', type=int, choices=[0, 1], default=0)
    p.add_argument('--fresh-attempts', type=int, default=1,
                   help='bounded fresh boots after a clean observation (PRE reproduction only)')
    args = p.parse_args()
    assert 20100 <= args.port < 20199
    assert 1 <= args.fresh_attempts <= 8
    assert args.fresh_attempts == 1 or not args.require_counters
    os.environ['LC_ALL'] = 'C'
    s.Boot = VerifiedBoot
    legs = ([] if args.no_oracle else [('redis', 'redis', 0, True)]) + [
        (m, e, a, False) for m in args.modes for e in args.engines for a in args.atomics]
    results = []
    args.output.mkdir(parents=True, exist_ok=True)
    for mode, engine, atomic, oracle in legs:
        label = f'{mode}-{engine}-{atomic}'
        row = dict(case=args.case, leg=label, databases=args.databases,
                   command=args.command, flush_mode=args.flush_mode)
        began = time.monotonic()
        attempts = []
        for attempt in range(1 if oracle else args.fresh_attempts):
            directory = args.output / label
            if args.fresh_attempts > 1:
                directory /= f'attempt-{attempt}'
            try:
                value = CASES[args.case](args, directory, mode, engine, atomic, oracle)
                attempts.append(dict(value=value, passed=True))
                row.update(value=value, **{'pass': True})
            except Exception:
                error = traceback.format_exc()
                attempts.append(dict(passed=False, error=error))
                row.update(error=error, **{'pass': False})
                break
        row['attempts'] = attempts
        row['seconds'] = round(time.monotonic() - began, 3)
        results.append(row)
        print(json.dumps(row), flush=True)
        (args.output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    return int(any(not r.get('pass') for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
