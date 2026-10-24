#!/usr/bin/env python3
"""CC4.26: lazy ACL log stores, retention, reset and disable semantics."""
import contextlib
import subprocess
import sys
from pathlib import Path
from _serverfix import main, Server, is_error
from _serverfix_alloc import Trace, untraced_rss


def probe(run, mode, label, extra):
    untraced_rss(run, mode, label, extra, 'acllog')
    with Trace(run, label) as trace, Server(run, label, mode, extra=extra +
            ['--slowlog-log-slower-than', '-1', '--latency-monitor-threshold', '0', '--acllog-max-len', '0']) as server:
        trace.snapshot('off-boot', server.process.pid)
        with contextlib.ExitStack() as stack:
            clients = [stack.enter_context(server.client()) for _ in range(24)]
            admin = clients[0]
            run.check(label + ' user', admin.cmd('ACL', 'SETUSER', 'lazy-denied', 'on', 'nopass', '+ping', '~*'), b'OK')
            for c in clients[1:]:
                run.check(label + ' auth', c.cmd('AUTH', 'lazy-denied', ''), b'OK')
                run.check(label + ' off denial', c.cmd('GET', 'denied'), lambda r: is_error(r, 'NOPERM'))
            run.check(label + ' disabled log empty', admin.cmd('ACL', 'LOG'), [])
            trace.snapshot('off-clients', server.process.pid)
            run.check(label + ' enable', admin.cmd('CONFIG', 'SET', 'acllog-max-len', 8), b'OK')
            for c in clients[1:]:
                run.check(label + ' enabled denial', c.cmd('GET', 'denied'), lambda r: is_error(r, 'NOPERM'))
            run.check(label + ' recorder fired', admin.cmd('ACL', 'LOG'), lambda rows: bool(rows))
            run.check(label + ' reset', admin.cmd('ACL', 'LOG', 'RESET'), b'OK')
            run.check(label + ' reset empty', admin.cmd('ACL', 'LOG'), [])
            run.check(label + ' disable', admin.cmd('CONFIG', 'SET', 'acllog-max-len', 0), b'OK')
            run.check(label + ' disabled denial', clients[1].cmd('GET', 'denied'), lambda r: is_error(r, 'NOPERM'))
            run.check(label + ' disable empty', admin.cmd('ACL', 'LOG'), [])
            trace.snapshot('enabled-then-disabled', server.process.pid)
    trace.verify('acllog')
    if not run.oracle:
        # Exercise the established full ACL battery on a fresh enabled server
        # in every declared mode/engine, alongside the allocation witness.
        aclfile = run.path / (label + '-users.acl')
        aclfile.write_text('')
        with Server(run, label + '-legacy', mode, extra=extra + ['--aclfile', str(aclfile)]) as server:
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('acl.py')),
                                     '127.0.0.1', str(run.args.port), str(aclfile)],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
            (run.path / (label + '-legacy.log')).write_text(result.stdout)
            run.check(label + ' full ACL battery', result.returncode, 0)


if __name__ == '__main__':
    raise SystemExit(main(probe))
