#!/usr/bin/env python3
"""Redis 7.4 INFO/introspection roots, through one gate job per root.

Each row owns fresh Redis and both TomoKV mode/engine/database-runtime legs.
No rate or timing threshold is used as a correctness verdict.
"""
import argparse
import json
from pathlib import Path
import re
import time
import traceback

from authfix import Run, Server, clean


def fields(c, section):
    raw = c.cmd('INFO', section)
    assert isinstance(raw, bytes), raw
    if raw.startswith(b'txt:'):
        raw = raw[4:]
    return dict(line.split(b':', 1) for line in raw.split(b'\r\n') if b':' in line)


def document(value):
    pairs = dict(zip(value[::2], value[1::2]))
    if b'arguments' in pairs:
        pairs[b'arguments'] = [document(arg) for arg in pairs[b'arguments']]
    if b'subcommands' in pairs:
        children = pairs[b'subcommands']
        pairs[b'subcommands'] = {name: document(row) for name, row in zip(children[::2], children[1::2])}
    return pairs


def missing(c, run, label):
    for protocol in (2, 3):
        c.cmd('HELLO', protocol)
        cpu = fields(c, 'CPU')
        expected = {b'used_cpu_' + x for x in (
            b'sys', b'user', b'sys_children', b'user_children', b'sys_main_thread', b'user_main_thread')}
        run.check(label + ' CPU fields', sorted(cpu), sorted(expected))
        run.check(label + ' CPU values', list(cpu.values()),
                  lambda rows: len(rows) == 6 and all(re.fullmatch(rb'\d+\.\d{6}', x) for x in rows))
        server = fields(c, 'SERVER')
        for name in (b'redis_git_sha1', b'redis_git_dirty', b'redis_build_id'):
            run.check(label + ' build ' + name.decode(), server.get(name),
                      lambda x: isinstance(x, bytes) and re.fullmatch(rb'[0-9a-f]+', x) is not None)
        for selection in ('DEFAULT', 'ALL', 'EVERYTHING'):
            run.check(label + ' ' + selection + ' CPU', b'used_cpu_user' in fields(c, selection), True)
    c.cmd('CONFIG', 'RESETSTAT')
    after = fields(c, 'CPU')
    run.check(label + ' CPU survives RESETSTAT', all(float(after[k]) >= float(v) for k, v in cpu.items()), True)


def docs(c, run, label):
    for protocol in (2, 3):
        c.cmd('HELLO', protocol)
        # Query every name advertised by TomoKV, including metadata children.
        # Oracle responses are compared as maps; Redis randomizes map order.
        names = c.cmd('COMMAND', 'LIST')
        if run.oracle:
            names = [name for name in names if name != b'flip']
        for name in names:
            if name == b'flip':
                continue
            reply = c.cmd('COMMAND', 'DOCS', name)
            assert len(reply) == 2 and reply[0] == name, (name, reply)
            row = document(reply[1])
            key = f'{protocol}-' + name.decode()
            if run.oracle:
                run.rows[key] = row
            else:
                run.check(label + ' DOCS ' + key, row, run.reference[key])
        run.check(label + ' unknown docs', c.cmd('COMMAND', 'DOCS', '__infofix_missing'), [])
        get = document(c.cmd('COMMAND', 'DOCS', 'GET')[1])
        run.check(label + ' GET argument witness', get.get(b'arguments'),
                  [{b'name': b'key', b'type': b'key', b'display_text': b'key', b'key_spec_index': 0}])


def slowlog(c, run, label):
    c.cmd('CONFIG', 'SET', 'slowlog-log-slower-than', 0)
    c.cmd('CONFIG', 'SET', 'slowlog-max-len', 3)
    c.cmd('SLOWLOG', 'RESET')
    for args in [('SET', 'key', 'test'), ('SADD', 'set', 'a', 'b', 'c'),
                 ('INCR', 'num'), ('LPUSH', 'list', 'a')]:
        c.cmd(*args)
    run.check(label + ' global LEN', c.cmd('SLOWLOG', 'LEN'), 3)
    entries = c.cmd('SLOWLOG', 'GET', -1)
    run.check(label + ' global GET all', len(entries), 3)
    run.check(label + ' newest first', [x[3] for x in entries],
              [[b'SLOWLOG', b'LEN'], [b'LPUSH', b'list', b'a'], [b'INCR', b'num']])
    run.check(label + ' IDs descend', [x[0] for x in entries], lambda ids: ids == sorted(set(ids), reverse=True))
    c.cmd('CONFIG', 'SET', 'slowlog-log-slower-than', -1)
    c.cmd('CONFIG', 'SET', 'slowlog-max-len', 1)
    run.check(label + ' disabled logger retains history', c.cmd('SLOWLOG', 'LEN'), 3)
    c.cmd('CONFIG', 'SET', 'slowlog-log-slower-than', 0)
    c.cmd('PING')
    c.cmd('CONFIG', 'SET', 'slowlog-log-slower-than', -1)
    c.cmd('CONFIG', 'SET', 'slowlog-max-len', 100)
    run.check(label + ' discarded history stays discarded', c.cmd('SLOWLOG', 'LEN'), 1)
    for count in (0, 1, 2, -1):
        run.check(label + f' GET limit {count}', len(c.cmd('SLOWLOG', 'GET', count)), 0 if count == 0 else 1)
    c.cmd('CONFIG', 'SET', 'slowlog-max-len', 0)
    run.check(label + ' zero disables retention changes', c.cmd('SLOWLOG', 'LEN'), 1)
    c.cmd('SLOWLOG', 'RESET')
    run.check(label + ' reset clears', c.cmd('SLOWLOG', 'GET', -1), [])


def loadaof(c, run, label):
    c.cmd('SET', 'without-aof', 'discard-me')
    run.check(label + ' absent AOF', c.cmd('DEBUG', 'LOADAOF'),
              {'error': 'ERR Error trying to load the AOF files, check server logs.'})
    run.check(label + ' failed load flushes', c.cmd('GET', 'without-aof'), None)
    c.cmd('SET', 'x', 10, 'PX', 60000)
    run.check(label + ' offline rewrite', c.cmd('BGREWRITEAOF'), b'Background append only file rewriting started')
    deadline = time.monotonic() + 10
    while fields(c, 'PERSISTENCE').get(b'aof_rewrite_in_progress') == b'1':
        assert time.monotonic() < deadline, 'rewrite completion deadline'
        time.sleep(.01)
    c.cmd('SET', 'x', 'after-rewrite')
    c.cmd('SET', 'new-key', 'discard-me')
    run.check(label + ' offline LOADAOF', c.cmd('DEBUG', 'LOADAOF'), b'OK')
    run.check(label + ' loaded value', c.cmd('GET', 'x'), b'10')
    run.check(label + ' restored TTL', c.cmd('PTTL', 'x'), lambda ttl: 0 < ttl <= 60000)
    run.check(label + ' flushed new key', c.cmd('GET', 'new-key'), None)
    run.check(label + ' stays appendonly no', c.cmd('CONFIG', 'GET', 'appendonly'), [b'appendonly', b'no'])


CASES = {'missing': missing, 'docs': docs, 'slowlog': slowlog, 'loadaof': loadaof}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case', required=True, choices=CASES)
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', required=True)
    p.add_argument('--port', required=True, type=int)
    p.add_argument('--cores', required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=False)
    failures, reference = 0, {}
    for binary, oracle in [(a.oracle, True), (a.binary, False)]:
        run = Run(a, binary, oracle)
        run.reference = reference
        for mode in run.modes():
            for engine in (['redis'] if oracle else ['uring', 'epoll']):
                for databases in ([16] if oracle else [1, 16]):
                    label = f'{mode}-{engine}-db{databases}'
                    extra = ['--databases', str(databases), '--enable-debug-command', 'yes']
                    if not oracle:
                        extra += ['--net-io', engine]
                    try:
                        with Server(run, label, mode, extra=extra) as server, server.client() as c:
                            CASES[a.case](c, run, label)
                    except Exception:
                        traceback.print_exc()
                        run.check(label + ' completed every assertion', False, True)
        failures += run.finish()
        if oracle:
            reference = run.rows
    print(f'infofix {a.case}: {failures} failed checks; evidence {a.output}', flush=True)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
