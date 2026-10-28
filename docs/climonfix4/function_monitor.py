#!/usr/bin/env python3
"""Declared-key FCALL MONITOR comparison on final POST and the Redis oracle."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from climonfix4 import read, server, sha
from _lib import encode

out = ROOT / 'build/climonfix4/function-monitor-final'
out.mkdir(exist_ok=True)
results = []
for engine in ('uring', 'epoll'):
    for mode in ('redis', '1s', '2s'):
        binary = (Path('/home/user/Projects/redis74/src/redis-server') if mode == 'redis'
                  else ROOT / 'build/climonfix4/tomokv-POST')
        args = argparse.Namespace(cores='16-23', port=20290, ratio='6:2', engine=engine)
        folder = out / engine / mode
        with server(args, binary, mode, folder) as (connect, argv):
            a, m = connect('a'), connect('m')
            source = ("#!lua name=cm4mon\nredis.register_function('cm4mon',function(keys,args) "
                      "redis.call('set',keys[1],args[1]); return redis.call('get',keys[1]) end)")
            assert a.cmd('FUNCTION', 'LOAD', source) == b'cm4mon'
            assert m.cmd('MONITOR') == b'OK'
            a.raw(encode('FCALL', 'cm4mon', 1, 'cm4:mon', 'value') + encode('PING'))
            assert a.read() == b'value' and a.read() == b'PONG'
            lines = [read(m, 1) for _ in range(4)]
            expected = ['] "FCALL"', '[0 lua] "set" "cm4:mon" "value"',
                        '[0 lua] "get" "cm4:mon"', '] "PING"']
            assert all(isinstance(line, str) and part in line for line, part in zip(lines, expected)), lines
            results.append(dict(engine=engine, mode=mode, binary_sha256=sha(binary),
                                argv=argv, lines=lines, expected=expected, passed=True))
(ROOT / 'docs/climonfix4/function-monitor-results.json').write_text(json.dumps(results, indent=2) + '\n')
print('Declared-key FCALL nested records and pipelined order match Redis in both modes/engines')
