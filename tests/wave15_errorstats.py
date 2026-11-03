#!/usr/bin/env python3
"""Redis 7.4 afterErrorReply oracle: ordinary, EXEC and Lua errors plus reset/cap."""
import argparse
import json
import os
from pathlib import Path
import traceback

from authfix import Run, Server
from infofix_compat import fields


def observe(c):
    stats = fields(c, 'STATS')
    assert b'total_error_replies' in stats, 'missing INFO total_error_replies'
    errors = fields(c, 'ERRORSTATS')
    return [int(stats[b'total_error_replies']),
            {k.decode(): v.decode() for k, v in errors.items()}]


def witness(c, observer, run, label):
    c.cmd('FLUSHALL')
    assert c.cmd('LPUSH', 'wrong', 'x') == 1
    assert c.cmd('SET', 'number', 'x') == b'OK'
    assert c.cmd('CONFIG', 'RESETSTAT') == b'OK'
    commands = [
        ('UNKNOWN-WAVE15',), ('SET',), ('GET', 'wrong'), ('INCR', 'number'),
        ('XREADGROUP', 'GROUP', 'absent', 'c', 'STREAMS', 'absent', '>'),
        ('MULTI',), ('GET', 'wrong'), ('INCR', 'number'), ('EXEC',),
        ('MULTI',), ('UNKNOWN-WAVE15',), ('EXEC',),
    ]
    scripts = [
        "return redis.error_reply('CUSTOM message')",
        "return redis.error_reply('')",
        "return redis.error_reply('NOSPACE')",
        "return redis.error_reply('a:b#c message')",
        "return redis.error_reply(string.rep('x',30)..' message')",
        "return redis.error_reply(string.rep('x',31)..' message')",
        "return redis.pcall('GET',KEYS[1])",
        "return redis.call('GET',KEYS[1])",
        "local e=redis.pcall('GET',KEYS[1]); return 'caught'",
        "local ok,e=pcall(redis.call,'GET',KEYS[1]); return 'caught'",
        "return {redis.pcall('GET',KEYS[1]),redis.pcall('GET',KEYS[1])}",
        "return redis.pcall('UNKNOWN-WAVE15')",
        "local e=redis.pcall('UNKNOWN-WAVE15'); return 'caught'",
        "return redis.pcall('SET')",
        "local e=redis.pcall('SET'); return 'caught'",
        "local e=redis.pcall({}); return 'caught'",
        "return redis.pcall({})",
        "return {err='CUSTOM ignored',ignore_error_stats_update=true}",
        "error('plain Lua error')",
    ]
    commands += [('EVAL', script, 1, 'wrong') for script in scripts]
    sha = c.cmd('SCRIPT', 'LOAD', "return redis.pcall('GET',KEYS[1])")
    commands += [('EVALSHA', sha, 1, 'wrong')] * 2
    for i, command in enumerate(commands):
        c.cmd(*command)
        actual = observe(observer)
        key = f'mixed-{i}'
        if run.oracle:
            run.reference[key] = actual
        run.check(f'{label} {key} {command[0]}', actual, run.reference[key])
    assert c.cmd('CONFIG', 'RESETSTAT') == b'OK'
    run.check(label + ' reset', observe(observer), [0, {}])
    # The 129th distinct prefix disables only the prefix table; total continues.
    for i in range(130):
        c.cmd('EVAL', f"return redis.error_reply('E{i} cap')", 0)
    actual = observe(observer)
    if run.oracle:
        run.reference['cap'] = actual
    run.check(label + ' prefix cap', actual, run.reference['cap'])
    c.cmd('CONFIG', 'RESETSTAT')
    c.cmd('GET', 'wrong')
    run.check(label + ' reset re-enables', observe(observer),
              [1, {'errorstat_WRONGTYPE': 'count=1'}])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('binary', 'oracle', 'cores'):
        p.add_argument('--' + key, required=True)
    p.add_argument('--port', required=True, type=int)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    os.environ['LC_ALL'] = 'C'
    a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=False)
    failures, reference = 0, {}
    for binary, oracle in ((a.oracle, True), (a.binary, False)):
        run = Run(a, binary, oracle)
        run.reference = reference
        for mode in run.modes():
            for engine in (['redis'] if oracle else ['uring', 'epoll']):
                for db in ([16] if oracle else [1, 16]):
                    for atomic in ([0] if oracle else [0, 1]):
                        label = f'{mode}-{engine}-d{db}-a{atomic}'
                        extra = ['--databases', str(db)]
                        if not oracle:
                            extra += ['--net-io', engine, '--atomic', str(atomic)]
                        run.server = Server(run, label, mode, None, extra)
                        try:
                            with run.server, run.server.client() as c, run.server.client() as observer:
                                witness(c, observer, run, label)
                        except Exception:
                            traceback.print_exc()
                            run.check(label + ' completed', False, True)
        failures += run.finish()
        reference = run.reference
    (a.output / 'oracle.json').write_text(json.dumps(reference, indent=2) + '\n')
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
