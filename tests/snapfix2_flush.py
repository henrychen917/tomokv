#!/usr/bin/env python3
"""Minimal FLUSHALL visibility witnesses with one MGET reader.

The mutator serially alternates an EXEC or script pair with FLUSHALL, or rearms
with SET while the observer is parked. No BGSAVE, unrelated writers, DEBUG
scheduling, core dumps or debugger. Each complete mutation leaves [1,1] or
[nil,nil]; a mixed observation is invalid. Use snapfix.py's boot/leg/oracle CLI.
"""
import contextlib
import json
import queue
import threading
import time

import snapfix as s
from _lib import Conn, encode


def case_flush_pair(args, directory, mode, engine, atomic, oracle, script=False):
    with s.Boot(args, directory, mode, engine, atomic, oracle) as b:
        pair, owners = s.keys_for(b.c, 'snapfix2:flush', oracle, 2)
        counts = {'cycles': 0, 'observations': 0, 'torn': 0}
        examples = []

        def mutate(stop):
            with contextlib.closing(Conn('127.0.0.1', b.port, timeout=args.stall)) as c:
                while not stop.is_set():
                    if script:
                        c.raw(encode('EVAL', "redis.call('SET',KEYS[1],1);"
                                     "redis.call('SET',KEYS[2],1);return 1", 2, *pair) +
                              encode('FLUSHALL'))
                        assert [c.read(), c.read()] == [1, b'OK']
                    else:
                        c.raw(encode('MULTI') + encode('SET', pair[0], 1) + encode('SET', pair[1], 1) +
                              encode('EXEC') + encode('FLUSHALL'))
                        assert [c.read() for _ in range(5)] == [b'OK', b'QUEUED', b'QUEUED',
                                                              [b'OK', b'OK'], b'OK']
                    counts['cycles'] += 1

        def observe(stop):
            with contextlib.closing(Conn('127.0.0.1', b.port, timeout=args.stall)) as c:
                while not stop.is_set():
                    values = c.must('MGET', *pair)
                    counts['observations'] += 1
                    if values not in ([None, None], [b'1', b'1']):
                        counts['torn'] += 1
                        if len(examples) < 20:
                            examples.append(dict(observation=counts['observations'],
                                                 values=[None if v is None else int(v) for v in values]))

        errors = s.run_storm(args.seconds, [mutate, observe], args.stall)
        result = dict(**counts, pair=pair, owners=owners, examples=examples, errors=errors)
        (directory / 'observations.json').write_text(json.dumps(result, indent=2) + '\n')
        assert not errors and counts['cycles'] > 0 and counts['observations'] > 0, result
        assert counts['torn'] == 0, result
        return result


def case_flush_only(args, directory, mode, engine, atomic, oracle):
    """Rearm with acknowledged SETs while the reader is parked. Only FLUSHALL
    mutates during each observation window, so no EXEC/script is required."""
    with s.Boot(args, directory, mode, engine, atomic, oracle) as b:
        pair, owners = s.keys_for(b.c, 'snapfix2:flush', oracle, 2)
        work = queue.Queue()
        counts = {'cycles': 0, 'observations': 0, 'torn': 0}
        examples = []

        def mutate(stop):
            try:
                with contextlib.closing(Conn('127.0.0.1', b.port, timeout=args.stall)) as c:
                    while not stop.is_set():
                        for key in pair:
                            assert c.must('SET', key, 1) == b'OK'
                        active, ready, done = (threading.Event() for _ in range(3))
                        active.set()
                        work.put((active, ready, done))
                        assert ready.wait(args.stall), 'observer never armed'
                        try:
                            assert c.must('FLUSHALL') == b'OK'
                        finally:
                            active.clear()
                        assert done.wait(args.stall), 'observer never parked'
                        counts['cycles'] += 1
            finally:
                work.put(None)

        def observe(stop):
            with contextlib.closing(Conn('127.0.0.1', b.port, timeout=args.stall)) as c:
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

        errors = s.run_storm(args.seconds, [mutate, observe], args.stall)
        result = dict(**counts, pair=pair, owners=owners, examples=examples, errors=errors)
        (directory / 'observations.json').write_text(json.dumps(result, indent=2) + '\n')
        assert not errors and counts['cycles'] > 0 and counts['observations'] > 0, result
        assert counts['torn'] == 0, result
        return result


if __name__ == '__main__':
    s.CASES = {'flush-pair': case_flush_pair, 'flush-only': case_flush_only,
               'flush-script': lambda *args: case_flush_pair(*args, script=True)}
    raise SystemExit(s.main())
