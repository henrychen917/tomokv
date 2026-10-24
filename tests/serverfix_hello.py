#!/usr/bin/env python3
"""SV4.7: canonical signed HELLO protocol integers and exact Redis errors."""
from _serverfix import main, Server


def probe(run, mode, label, extra):
    with Server(run, label, mode, extra=extra) as server:
        for version in [b'02', b'03', b'+2', b'-0', b'00', b'', b' 2', b'2 ',
                        b'2\0x', b'9223372036854775808', b'-9223372036854775809',
                        b'0', b'1', b'4', b'-1', b'-9223372036854775808', b'9223372036854775807']:
            with server.client() as c:
                run.check(label + ' setup RESP3', dict(zip(*(iter(c.cmd('HELLO', 3)),) * 2))[b'proto'], 3)
                reply = c.cmd('HELLO', version, 'SETNAME', 'must-not-apply')
                key = repr(version)
                run.rows[key] = reply
                if not run.oracle:
                    run.check(label + ' oracle error ' + key, reply, run.reference[key])
                run.check(label + ' failed HELLO retained name', c.cmd('CLIENT', 'GETNAME'), None)
                hello = c.cmd('HELLO')
                run.check(label + ' failed HELLO retained protocol', dict(zip(hello[::2], hello[1::2]))[b'proto'], 3)
                run.check(label + ' usable connection', c.cmd('PING'), b'PONG')
        with server.client() as c:
            for version in [2, 3, 2]:
                hello = c.cmd('HELLO', version)
                run.check(label + ' canonical protocol ' + str(version),
                          dict(zip(hello[::2], hello[1::2]))[b'proto'], version)


if __name__ == '__main__':
    raise SystemExit(main(probe))
