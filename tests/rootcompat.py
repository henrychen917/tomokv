#!/usr/bin/env python3
"""Directed rootcompat oracle witnesses; invoked only by gate.sh jobs.

Every candidate case runs both modes, engines and database runtimes. Replies
are checked against a fresh Redis 7.4 oracle, with no rate assertions.
"""
import argparse
import json
import os
from pathlib import Path
import re
import select
import time
import traceback

from authfix import Run, Server, clean
from infofix_compat import fields


def proc(c, run, label):
    for section in ('CPU', 'DEFAULT'):
        result = fields(c, section)
        for name, value in result.items():
            if name.startswith(b'used_cpu_'):
                assert re.fullmatch(rb'\d+\.\d{6}', value), (name, value)
        run.check(label + ' alive after INFO ' + section, c.cmd('PING'), b'PONG')


def password(c, run, label):
    for user, password in ((b'embedded', b'a\0b'), (b'leading', b'\0tail')):
        run.check(label + ' full binary AUTH ' + user.decode(), c.cmd('AUTH', user, password), b'OK')
        run.check(label + ' full authenticated PING', c.cmd('PING'), b'PONG')
        c.cmd('RESET')
        reply = c.cmd('AUTH', user, password.split(b'\0')[0])
        run.check(label + ' truncated AUTH refused ' + user.decode(), reply,
                  lambda r: isinstance(r, dict) and r['error'].startswith('WRONGPASS'))


def replication(c, run, label):
    actual = fields(c, 'REPLICATION')
    if run.oracle:
        run.reference = actual
    expected = run.reference
    run.check(label + ' replication field set', sorted(actual), sorted(expected))
    for name, value in actual.items():
        if name in (b'master_replid', b'master_replid2'):
            run.check(label + ' ' + name.decode(), value,
                      lambda v: re.fullmatch(rb'[0-9a-f]{40}', v) is not None)
            if name == b'master_replid2':
                run.check(label + ' unused replid2', value, b'0' * 40)
        elif name in expected:
            run.check(label + ' ' + name.decode(), value, expected[name])


def sort_acl(c, run, label):
    assert c.cmd('ACL', 'SETUSER', 'restricted', 'on', 'nopass', '~source', '+@all') == b'OK'
    assert c.cmd('RPUSH', 'source', 2, 1) == 2
    assert c.cmd('AUTH', 'restricted', '') == b'OK'
    for command in ('SORT', 'SORT_RO'):
        for option, pattern in (('BY', 'weight:*'), ('GET', 'data:*'), ('GET', '#')):
            assert c.cmd('MULTI') == b'OK'
            run.check(label + ' queued ' + command + option,
                      c.cmd(command, 'source', option, pattern), b'QUEUED')
            run.check(label + ' EXEC ' + command + option, c.cmd('EXEC'),
                      [{'error': f'ERR {option} option of SORT denied due to insufficient ACL permissions.'}])
    assert c.cmd('AUTH', 'default', '') == b'OK'


def redact(c, run, label):
    assert c.cmd('CONFIG', 'SET', 'slowlog-log-slower-than', 0) == b'OK'
    for command in [('ACL', 'GETUSER', 'secret-user'),
                    ('ACL', 'DELUSER', 'secret-user', 'second-secret')]:
        c.cmd(*command)
        row = c.cmd('SLOWLOG', 'GET', 1)[0][3]
        run.check(label + ' ' + command[1], row,
                  [b'ACL', command[1].encode()] + [b'(redacted)'] * (len(command) - 2))


def errorstats(c, run, label):
    assert c.cmd('CONFIG', 'RESETSTAT') == b'OK'
    commands = [('UNKNOWN-ROOTCOMPAT',), ('SET',), ('LPUSH', 'wrongtype', 'x'),
                ('GET', 'wrongtype'), ('INCR', 'notint'),
                ('XREADGROUP', 'GROUP', 'missing', 'c', 'STREAMS', 'missing', '>')]
    assert c.cmd('SET', 'notint', 'x') == b'OK'
    errors = {}
    for command in commands:
        reply = c.cmd(*command)
        if isinstance(reply, dict):
            prefix = reply['error'].split(' ', 1)[0]
            errors[prefix] = errors.get(prefix, 0) + 1
    run.check(label + ' directed errors fired', sum(errors.values()), 5)
    run.check(label + ' total errors', fields(c, 'STATS').get(b'total_error_replies'), b'5')
    actual = fields(c, 'ERRORSTATS')
    run.check(label + ' all prefixes', actual,
              {('errorstat_' + k).encode(): f'count={v}'.encode() for k, v in errors.items()})
    assert c.cmd('CONFIG', 'RESETSTAT') == b'OK'
    run.check(label + ' reset total', fields(c, 'STATS').get(b'total_error_replies'), b'0')
    run.check(label + ' reset prefixes', fields(c, 'ERRORSTATS'), {})


def hscan(c, run, label):
    assert c.cmd('CONFIG', 'SET', 'hash-max-listpack-entries', 8) == b'OK'
    a, b = 'scan:target', 'scan:source'
    if not run.oracle:
        names = [f'scan:{i}' for i in range(256)]
        owners = c.cmd('DEBUG', 'SHARDS', *names)
        a = names[0]
        b = next(k for k, geo in zip(names, owners) if geo[1] != owners[0][1])
        run.check(label + ' cross-owner rename', c.cmd('DEBUG', 'SHARDS', a, b),
                  lambda rows: rows[0][1] != rows[1][1])
    required = {f'f{i}'.encode() for i in range(8)}
    for key, count in ((a, 8), (b, 64)):
        args = [x for i in range(count) for x in (f'f{i}', str(i))]
        assert c.cmd('HSET', key, *args) == count
    assert c.cmd('OBJECT', 'ENCODING', a) == b'listpack'
    assert c.cmd('OBJECT', 'ENCODING', b) == b'hashtable'
    with run.server.client() as group:
        held = False
        try:
            if not run.oracle:
                assert c.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', 1) == b'OK'
                held = True
                from rootcompat_tracking.resp import encode
                group.sock.sendall(encode('RENAME', b, a))
                deadline = time.monotonic() + 5
                while int(fields(c, 'STATS')[b'atomic_pending_entries']) < 2:
                    assert time.monotonic() < deadline, 'rename never installed both entries'
                    time.sleep(.005)
                assert not select.select([group.sock], [], [], 0)[0], 'held rename already replied'
            cursor, page = c.cmd('HSCAN', a, 0, 'COUNT', 1)
            seen = set(page[::2])
            run.check(label + ' compact predecessor returns all fields', sorted(seen), sorted(required))
            if held:
                assert c.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', 0) == b'OK'
                held = False
                assert group.read() == b'OK'
            else:
                assert c.cmd('RENAME', b, a) == b'OK'
            assert c.cmd('OBJECT', 'ENCODING', a) == b'hashtable'
            pages = 1
            while int(cursor):
                cursor, page = c.cmd('HSCAN', a, cursor, 'COUNT', 1)
                seen.update(page[::2])
                pages += 1
                assert pages <= 1024, 'scan never terminated'
            run.check(label + ' promotion preserves SCAN guarantee', sorted(required - seen), [])
        finally:
            if held:
                c.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', 0)
                group.read()


def setpast(c, run, label):
    from rootcompat_tracking.resp import Conn
    assert c.cmd('DEBUG', 'SET-ACTIVE-EXPIRE', 0) == b'OK'
    sub = Conn(run.args.port)
    try:
        sub.send('PSUBSCRIBE', '__keyevent@0__:*')
        assert sub.read()[0] == b'psubscribe'
        # Every shard is visited: in fused mode this necessarily includes keys
        # foreign to the connection's owner, where L4 prebuild is selected.
        keys = ['past:0'] if run.oracle else []
        if not run.oracle:
            names = [f'past:{i}' for i in range(512)]
            shards = c.cmd('DEBUG', 'SHARDS', *names)
            chosen = {}
            for key, (shard, _) in zip(names, shards):
                chosen.setdefault(shard, key)
            assert len(chosen) == 16, chosen
            keys = list(chosen.values())
        for key in keys:
            for option in ('EXAT', 'PXAT'):
                assert c.cmd('CONFIG', 'SET', 'notify-keyspace-events', '') == b'OK'
                assert c.cmd('SET', key, 'old') == b'OK'
                sub.poll_pushes(.01)
                assert c.cmd('CONFIG', 'SET', 'notify-keyspace-events', 'E$gx') == b'OK'
                run.check(label + ' elapsed large SET', c.cmd('SET', key, 'v' * 1024, option, 1), b'OK')
                run.check(label + ' elapsed value absent', c.cmd('GET', key), None)
                events = sub.read_frames_until_quiet(.04, 2)
                actual = [(row[2], row[3]) for row in events]
                run.check(label + f' {key} {option} ordered events', actual,
                          [(b'__keyevent@0__:set', key.encode()),
                           (b'__keyevent@0__:expire', key.encode()),
                           (b'__keyevent@0__:expired', key.encode())])
    finally:
        sub.close()


CASES = {'proc': proc, 'password': password, 'replication': replication,
         'sort-acl': sort_acl, 'redact': redact, 'errorstats': errorstats,
         'hscan': hscan, 'setpast': setpast}


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
    os.environ['LC_ALL'] = 'C'
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
                        if a.case == 'hscan':
                            extra += ['--atomic', '1', '--key-lb', '0', '--client-lb', '0']
                    conf = None
                    if a.case == 'password':
                        conf = run.conf(label, 'user embedded on ">a\\x00b" ~* +@all\n'
                                        'user leading on ">\\x00tail" ~* +@all\n')
                    server = Server(run, label, mode, conf, extra)
                    run.server = server
                    if a.case == 'proc':
                        server.args[3:3] = ['env', 'LD_PRELOAD=' + str(Path('build/rootcompat/proc-fault.so').resolve())]
                    try:
                        with server, server.client() as c:
                            CASES[a.case](c, run, label)
                        if a.case == 'proc' and not oracle:
                            run.check(label + ' fault fired',
                                      'rootcompat: denied proc stat' in (server.path / 'server.log').read_text(), True)
                    except Exception:
                        traceback.print_exc()
                        run.check(label + ' completed every assertion', False, True)
        failures += run.finish()
        reference = run.reference
    print(f'rootcompat {a.case}: {failures} failed checks; evidence {a.output}', flush=True)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
