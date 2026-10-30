#!/usr/bin/env python3
"""Scripting compatibility across real optimistic retries and escalation.

The execfair gate job supplies all mode/engine/atomic legs and owns the server.
Reuse at412's witnessed nine-conflict schedule; no absent window can pass.
"""
import contextlib
import json
import sys
from _lib import Conn
from at412 import conflicts, invocation, pair, settle


def main(port):
    results = []
    with contextlib.closing(Conn('127.0.0.1', port, timeout=5)) as admin:
        # Numeric command arguments stay rooted through the complete child call.
        # Registration happens under the restricted initialization environment;
        # the retained callback gains its runtime redis API before invocation.
        body = "return {redis.call('INCRBY',KEYS[1],1),redis.call('INCRBY',KEYS[2],1)}"
        for shape in ('header', 'sha-case', 'function-case'):
            keys = pair(admin, 'wave10:' + shape, False)
            if shape == 'header':
                call = ('EVAL', '#!lua flags=allow-oom\n' + body, 2, *keys)
            elif shape == 'sha-case':
                call = list(invocation(admin, 'EVALSHA', keys, body))
                call[1] = call[1].upper()
            else:
                admin.must('FUNCTION', 'LOAD', 'REPLACE',
                    '#!lua name=wave10\nredis.register_function{' +
                    "function_name='Wave10Case',callback=function(KEYS,ARGV) " + body + ' end}')
                call = ('FCALL', 'WAVE10CASE', 2, *keys)
            results.append(dict(shape=shape, result=conflicts(admin, port, keys, call, False)))
            settle(admin)
    print(json.dumps(dict(passed=True, witnesses=results)), flush=True)


if __name__ == '__main__':
    main(int(sys.argv[1]))
