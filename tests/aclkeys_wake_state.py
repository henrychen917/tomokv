#!/usr/bin/env python3
"""One SWAPDB must not lose an XADD wake. Takes a fresh, gate-owned db16 listener.

CLIENT LIST alone precedes owner registration. Require the parked counter too:
otherwise registration's eager reprobe could mask the broken publish namespace.
No listener, background traffic, DEBUG latch, or relaxed timeout is needed.
"""
import sys
import time
from _lib import Conn, info
from _differ_aclkeys import wait_blocked


def registered(admin):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        fields = info(admin)
        if int(fields["blocking_waiters"]) == 1 and int(fields["blocked_clients"]) == 1:
            return
        time.sleep(.001)
    raise AssertionError("XREAD owner registration never appeared")


def reproduce(admin, worker):
    assert admin.cmd("SWAPDB", 0, 1) == b"OK"
    assert admin.cmd("DEL", "block:aclkeys") == 0
    ident = worker.cmd("CLIENT", "ID")
    worker.send("XREAD", "BLOCK", 0, "STREAMS", "block:aclkeys", 0)
    wait_blocked(admin, (worker.sock, worker.file), ident,
                 lambda conn, args: conn.cmd(*args), lambda value: value,
                 lambda _file: worker.read(), timeout=2)
    registered(admin)
    started = time.monotonic()
    assert admin.cmd("XADD", "block:aclkeys", "1-0", "field", "value") == b"1-0"
    assert worker.read() == [[b"block:aclkeys", [[b"1-0", [b"field", b"value"]]]]]
    assert time.monotonic() - started < 2, "XREAD exceeded the wake deadline"


if __name__ == "__main__":
    host, port = sys.argv[1], int(sys.argv[2])
    admin = Conn(host, port, timeout=2, buffering=0)
    worker = Conn(host, port, timeout=2, buffering=0)
    try:
        reproduce(admin, worker)
        assert worker.cmd("PING") == b"PONG"
        print("aclkeys SWAPDB/XREAD wake PASS (registered, exact reply within 2 s)")
    finally:
        worker.close()
        admin.close()
