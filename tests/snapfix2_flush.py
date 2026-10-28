#!/usr/bin/env python3
"""Minimal FLUSHALL visibility witness: one serial EXEC/FLUSHALL client and one MGET reader.

No BGSAVE, scripts, unrelated writers, DEBUG scheduling, core dumps or debugger. At any Redis
command boundary the pair is either [1,1] or [nil,nil]. A mixed pair is an atomicity violation.
Use snapfix.py's normal boot/leg/oracle CLI with --case flush-pair --seconds 5.
"""
import contextlib
import json
import time

import snapfix as s
from _lib import Conn, encode


def case_flush_pair(args, directory, mode, engine, atomic, oracle):
    with s.Boot(args, directory, mode, engine, atomic, oracle) as b:
        pair, owners = s.keys_for(b.c, 'snapfix2:flush', oracle, 2)
        counts = {'cycles': 0, 'observations': 0, 'torn': 0}
        examples = []

        def mutate(stop):
            with contextlib.closing(Conn('127.0.0.1', b.port, timeout=args.stall)) as c:
                while not stop.is_set():
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


if __name__ == '__main__':
    s.CASES = {'flush-pair': case_flush_pair}
    raise SystemExit(s.main())
