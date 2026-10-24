#!/usr/bin/env python3
"""Reserve lane ports against ephemeral clients while running the real gate job.

Linux permits the server's SO_REUSEADDR listener beside a bound, non-listening
SO_REUSEADDR socket. The latter excludes automatic ephemeral-port allocation
between boots without changing any host sysctl, readiness check or test assertion.
"""
import argparse
from contextlib import ExitStack
import socket
import subprocess

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("ports", help="inclusive lane range, e.g. 37813-37815")
ap.add_argument("command", nargs=argparse.REMAINDER)
args = ap.parse_args()
first, last = map(int, args.ports.split("-"))
assert 37800 <= first <= last <= 37899
command = args.command[1:] if args.command[:1] == ["--"] else args.command
assert command
with ExitStack() as stack:
    for port in range(first, last + 1):
        reservation = stack.enter_context(socket.socket())
        reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        reservation.bind(("127.0.0.1", port))
    print("Non-listening ephemeral-port reservations:", args.ports, flush=True)
    raise SystemExit(subprocess.run(command).returncode)
