#!/usr/bin/env python3
"""SV4.14: allocation-free disabled logging and enable-after-connect identity."""
import contextlib
import time
from _serverfix import main, Server
from _serverfix_alloc import Trace, untraced_rss


def probe(run, mode, label, extra):
    untraced_rss(run, mode, label, extra, 'slowlog')
    with Trace(run, label) as trace, Server(run, label, mode, extra=extra +
            ['--slowlog-log-slower-than', '-1', '--latency-monitor-threshold', '0', '--acllog-max-len', '0']) as server:
        trace.snapshot('off-boot', server.process.pid)
        with contextlib.ExitStack() as stack:
            clients = [stack.enter_context(server.client()) for _ in range(24)]
            for i, c in enumerate(clients):
                run.check(label + ' disabled name ' + str(i), c.cmd('CLIENT', 'SETNAME', 'before-' + str(i)), b'OK')
            c = clients[0]
            run.check(label + ' empty disabled log', c.cmd('SLOWLOG', 'GET', -1), [])
            trace.snapshot('off-clients', server.process.pid)
            # A high armed threshold exercises completion without allocating a recorder.
            # This is independent of the cold-disabled leg and the subsequent zero-threshold
            # witness. The command-scope debugger checks the default fast-path instructions.
            run.check(label + ' arm high threshold', c.cmd('CONFIG', 'SET',
                      'slowlog-log-slower-than', 1000000000), b'OK')
            for command, args, expected in [('SET', ('threshold-key', '0'), b'OK'),
                                            ('GET', ('threshold-key',), b'0'),
                                            ('INCR', ('threshold-key',), 1)]:
                run.check(label + ' below threshold ' + command, c.cmd(command, *args), expected)
            run.check(label + ' below threshold log empty', c.cmd('SLOWLOG', 'GET', -1), [])
            trace.snapshot('armed-below-threshold', server.process.pid)
            run.check(label + ' enable', c.cmd('CONFIG', 'SET', 'slowlog-log-slower-than', 0), b'OK')
            found = []
            for attempt in range(4):
                run.check(label + ' reset', c.cmd('SLOWLOG', 'RESET'), b'OK')
                run.check(label + ' marker', c.cmd('SET', 'lazy-slowlog-marker', 'value'), b'OK')
                end = time.monotonic() + .2
                while time.monotonic() < end:
                    found = [e for e in c.cmd('SLOWLOG', 'GET', -1)
                             if e[3][:2] == [b'SET', b'lazy-slowlog-marker']]
                    if found:
                        break
                    time.sleep(.005)
                if found:
                    break
            run.check(label + ' enabled recorder fired', bool(found), True)
            run.check(label + ' pre-enable connection name retained', [e[5] for e in found],
                      lambda rows: bool(rows) and all(x == b'before-0' for x in rows))
            run.check(label + ' real client address', [e[4] for e in found],
                      lambda rows: bool(rows) and all(x.startswith(b'127.0.0.1:') for x in rows))
            run.check(label + ' rename', c.cmd('CLIENT', 'SETNAME', 'after'), b'OK')
            run.check(label + ' disable', c.cmd('CONFIG', 'SET', 'slowlog-log-slower-than', -1), b'OK')
            trace.snapshot('enabled-then-disabled', server.process.pid)
        with server.client() as admin:
            old = [e for e in admin.cmd('SLOWLOG', 'GET', -1) if e[3][:2] == [b'SET', b'lazy-slowlog-marker']]
            run.check(label + ' disconnect preserved historical identity', old, found)
    trace.verify('slowlog')


if __name__ == '__main__':
    raise SystemExit(main(probe))
