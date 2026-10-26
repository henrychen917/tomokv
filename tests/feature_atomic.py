#!/usr/bin/env python3
"""Restore and verify the advertised atomic arm at every shared-battery boundary."""
import subprocess
import sys
from contextlib import closing
from _lib import Conn


def restore(conn, atomic):
    expected = str(atomic).encode()
    assert conn.must("CONFIG", "SET", "atomic", expected) == b"OK", "atomic restore rejected"
    actual = conn.must("CONFIG", "GET", "atomic")
    assert actual == [b"atomic", expected], f"atomic boundary mismatch: {actual!r}"


def boundary(host, port, atomic):
    with closing(Conn(host, port)) as conn:
        restore(conn, atomic)
        # The limits battery deliberately fills maxclients. Leave no wrapper
        # connection alive during its body, and witness the server's close.
        assert conn.must("QUIT") == b"OK", "atomic observer did not quit"
        assert conn.file.read(1) == b"", "atomic observer did not close"


def run(host, port, atomic, command):
    boundary(host, port, atomic)
    print(f"atomic boundary entry={atomic}", flush=True)
    try:
        return subprocess.run(command, check=False).returncode
    finally:
        boundary(host, port, atomic)
        print(f"atomic boundary restored={atomic}", flush=True)


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4:]))
