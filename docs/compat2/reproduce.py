#!/usr/bin/env python3
"""Initial PRE anchor verification; each listener and connection is owned here."""
import argparse
from pathlib import Path
import select
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
import aoffix2 as h
import hexpread as hx
import tls


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--artifacts', type=Path, required=True)
    p.add_argument('--mode', default='2s')
    p.add_argument('--engine', default='uring')
    p.add_argument('--case', choices=('auth', 'notify', 'tls'), required=True)
    p.add_argument('--oracle', action='store_true')
    a = p.parse_args()
    a.binary, a.artifacts = a.binary.resolve(), a.artifacts.resolve()
    a.artifacts.mkdir(parents=True, exist_ok=False)
    a.cores, a.ratio, a.port = ('72' if a.oracle else '64-71'), '6:2', 26800
    h.ARGS = a
    cert = ROOT / 'build/compat2/certs'
    extra = [] if a.oracle else ['--atomic', '1', '--databases', '16']
    if a.case == 'tls':
        extra += ['--tls-port', '26801', '--tls-cert-file', str(cert / 'server.crt'),
                  '--tls-key-file', str(cert / 'server.key'), '--tls-ca-cert-file',
                  str(cert / 'ca.crt'), '--tls-auth-clients', 'no']
    with h.Server(extra) as s:
        c = s.client(timeout=5)
        if a.case == 'auth':
            c.cmd('CONFIG', 'SET', 'requirepass', 'compat2-secret')
            for auth in (False, True):
                r = s.client()
                if auth:
                    r.cmd('AUTH', 'compat2-secret')
                for cmd in [('PING', *range(9)), ('GET',), ('NOTACOMMAND',)]:
                    try:
                        result = r.cmd(*cmd)
                    except RuntimeError as err:
                        result = '-' + str(err)
                    h.emit('auth', authenticated=auth, command=cmd, result=result)
        elif a.case == 'notify':
            c.cmd('CONFIG', 'SET', 'notify-keyspace-events', 'Exm')
            c.cmd('DEBUG', 'SET-ACTIVE-EXPIRE', '0')
            sub = s.client()
            sub.send('SUBSCRIBE', '__keyevent@0__:expired', '__keyevent@0__:keymiss')
            sub.read(); sub.read()
            ka, kb, _ = hx.keys(c)
            for kind in ('MSET', 'RENAME', 'EXEC'):
                c.cmd('FLUSHDB')
                c.cmd('SET', ka, 'old')
                c.cmd('SET', kb, 'candidate')
                deadline = time.time_ns() // 1000000 + 700
                c.cmd('PEXPIREAT', kb, deadline)
                group = s.client()
                c.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', 1)
                try:
                    if kind == 'EXEC':
                        group.cmd('MULTI')
                        group.cmd('MSET', ka, 'new', kb, 'new')
                        group.cmd('PEXPIREAT', ka, deadline)
                        group.send('EXEC')
                    elif kind == 'RENAME':
                        group.send('RENAME', kb, ka)
                    else:
                        group.send('MSET', ka, 'new', kb, 'new')
                    try:
                        installed = hx.wait_for(lambda: (x if (x := hx.stats(c))[
                            'atomic_pending_entries'] >= 2 else None), 'not installed', 2)
                    except AssertionError:
                        installed = hx.stats(c)
                    held = not select.select([group.s], [], [], 0)[0]
                    h.emit('notify_arm', kind=kind, installed=installed, held=held)
                    hx.deadline_passed(deadline)
                    value = c.cmd('GET', ka)
                    time.sleep(.05)
                    h.emit('notify_read', kind=kind, value=value, events=hx.events(sub))
                finally:
                    c.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', 0)
                h.emit('notify_commit', kind=kind, reply=group.read())
        else:
            def snapshot(label):
                stats = hx.stats(c)
                h.emit('tls_stats', label=label,
                       stats={k: v for k, v in stats.items() if k.startswith('tls_')},
                       clients=c.cmd('CLIENT', 'LIST'))
            snapshot('baseline')
            for version in ('tls12', 'tls13'):
                probe = tls.Conn('127.0.0.1', 26801, tls.context(str(cert), **{version: True}))
                assert probe.command('PING') == b'PONG'
                snapshot(version + '-live')
                probe.close(graceful=True)
                for delay in (.05, .2, 1):
                    time.sleep(delay)
                    snapshot(version + '-closed-' + str(delay))


if __name__ == '__main__':
    main()
