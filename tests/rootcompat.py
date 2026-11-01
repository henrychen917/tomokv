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


CASES = {'proc': proc, 'password': password, 'replication': replication,
         'sort-acl': sort_acl, 'redact': redact, 'errorstats': errorstats}


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
                    conf = None
                    if a.case == 'password':
                        conf = run.conf(label, 'user embedded on ">a\\x00b" ~* +@all\n'
                                        'user leading on ">\\x00tail" ~* +@all\n')
                    server = Server(run, label, mode, conf, extra)
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
