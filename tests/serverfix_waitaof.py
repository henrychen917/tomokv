#!/usr/bin/env python3
"""SV4.5: standalone WAITAOF deadlines, forever waits and connection cleanup."""
import select
import time
from _serverfix import main, Server


def send(c, *args):
    parts = [str(a).encode() for a in args]
    c.sock.sendall(b'*%d\r\n' % len(parts) + b''.join(b'$%d\r\n' % len(a) + a + b'\r\n' for a in parts))


def client_row(admin, ident):
    return next((dict(p.split(b'=', 1) for p in row.split() if b'=' in p)
                 for row in admin.cmd('CLIENT', 'LIST').splitlines()
                 if row.startswith(b'id=' + str(ident).encode() + b' ')), {})


def parked(admin, ident, timeout=.3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        row = client_row(admin, ident)
        if b'b' in row.get(b'flags', b''):
            return True
        time.sleep(.005)
    return False


def probe(run, mode, label, extra):
    with Server(run, label, mode, extra=extra) as server, server.client() as admin:
        run.check(label + ' immediate', admin.cmd('WAITAOF', 0, 0, 0), [0, 0])
        for i, args in enumerate([(0, -1, 0), (0, 1, -1), (0, 1, '01'),
                                   ('00', 0, 1), (0, 1, 9223372036854775807), (1, 0, 0)]):
            reply = admin.cmd('WAITAOF', *args)
            run.rows[str(i)] = reply
            if not run.oracle:
                run.check(label + ' grammar ' + str(i), reply, run.reference[str(i)])
        # Every observation must occur inside the finite window. Re-arm on a new
        # connection if this process was descheduled; exhausted attempts fail.
        observed = False
        for attempt in range(3):
            with server.client() as c:
                ident = c.cmd('CLIENT', 'ID')
                started = time.monotonic()
                send(c, 'WAITAOF', 0, 1, 1000)
                blocked = parked(admin, ident)
                ready = bool(select.select([c.sock], [], [], .05)[0])
                if time.monotonic() - started >= .7:
                    continue
                observed = True
                run.check(label + ' finite blocked witness', blocked, True)
                run.check(label + ' no premature reply', ready, False)
                run.check(label + ' deadline reply', c.read(), [0, 0])
                run.check(label + ' finite next command', c.cmd('PING'), b'PONG')
                break
        run.check(label + ' finite observation window opened', observed, True)
        for flavor in ['TIMEOUT', 'ERROR']:
            with server.client() as c:
                ident = c.cmd('CLIENT', 'ID')
                send(c, 'WAITAOF', 0, 1, 0)
                run.check(label + ' forever parked ' + flavor, parked(admin, ident), True)
                run.check(label + ' forever has no reply ' + flavor,
                          bool(select.select([c.sock], [], [], .1)[0]), False)
                unblocked = admin.cmd('CLIENT', 'UNBLOCK', ident, flavor)
                run.check(label + ' unblock ' + flavor, unblocked, 1)
                run.check(label + ' unblock reply ' + flavor, c.read(), [0, 0] if flavor == 'TIMEOUT' else
                          {'error': 'UNBLOCKED client unblocked via CLIENT UNBLOCK'})
                run.check(label + ' resumed ' + flavor, c.cmd('PING'), b'PONG')
                run.check(label + ' no lingering waiter', admin.cmd('CLIENT', 'UNBLOCK', ident), 0)
        with server.client() as c:
            ident = c.cmd('CLIENT', 'ID')
            send(c, 'WAITAOF', 0, 1, 0)
            run.check(label + ' disconnect parked', parked(admin, ident), True)
        end = time.monotonic() + 2
        while client_row(admin, ident) and time.monotonic() < end:
            time.sleep(.01)
        run.check(label + ' disconnected waiter removed', client_row(admin, ident), {})
        run.check(label + ' disconnected cannot unblock', admin.cmd('CLIENT', 'UNBLOCK', ident), 0)
        run.check(label + ' MULTI', admin.cmd('MULTI'), b'OK')
        run.check(label + ' queued WAITAOF', admin.cmd('WAITAOF', 0, 1, 0), b'QUEUED')
        run.check(label + ' EXEC never parks', admin.cmd('EXEC'), [[0, 0]])


if __name__ == '__main__':
    raise SystemExit(main(probe))
