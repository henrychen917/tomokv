#!/usr/bin/env python3
"""Keep correctness ports out of automatic client-port allocation between boots.

The guard binds but never listens, accepts, or sends. SO_REUSEADDR permits the
Redis oracle to bind/listen; SO_REUSEPORT also permits TomoKV's per-IO listeners.
No system-wide ephemeral-port setting or server option is changed.
"""
import argparse
import json
import socket
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ports', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    first, last = map(int, args.ports.split('-'))
    assert 48800 <= first <= last <= 48899, 'outside iofix3 port allocation'
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    assert command, 'missing command'
    guards = []
    try:
        for port in range(first, last + 1):
            # Refuse live sockets before enabling shared binds. TIME-WAIT from
            # a completed gate has no owner; bind itself decides whether its
            # SO_REUSEADDR state permits reuse. Never join a live listener.
            sockets = subprocess.check_output(['ss', '-H', '-tan', f'sport = :{port}'])
            live = [row for row in sockets.splitlines() if row.split()[0] != b'TIME-WAIT']
            assert not live, f'port {port} already has live TCP state: {live!r}'
            guard = socket.socket()
            guards.append(guard)
            guard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            guard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            guard.bind(('127.0.0.1', port))
        print(json.dumps(dict(bound_only_ports=list(range(first,last+1)), command=command)), flush=True)
        return subprocess.run(command).returncode
    finally:
        for guard in guards:
            guard.close()


if __name__ == '__main__':
    sys.exit(main())
