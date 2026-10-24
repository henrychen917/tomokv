#!/usr/bin/env python3
"""Blocking/stream structure witnesses, run by the gate's complete oracle matrix."""
from compat3_lib import equal, run
from _lib import Conn, info
import time


def parked(c, n):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if int(info(c, "clients")["blocked_clients"]) == n:
            return
        time.sleep(.002)
    equal(int(info(c, "clients")["blocked_clients"]), n, "all requested waiters actually parked")


def registry(c):
    clients = []
    outputs = []
    try:
        for command, push, wanted in (
            (("BLPOP", b"q\x00x", b"q\x00x", 0), ("RPUSH", b"q\x00x", "a", "b", "c"),
             [[b"q\x00x", x] for x in (b"a", b"b", b"c")]),
            (("BZPOPMIN", b"q\x00z", b"q\x00z", 0), ("ZADD", b"q\x00z", 1, "a", 2, "b", 3, "c"),
             [[b"q\x00z", x, str(i+1).encode()] for i, x in enumerate((b"a", b"b", b"c"))])):
            active = []
            for i in range(3):
                waiter = Conn(c.host, c.port, timeout=5, buffering=0)
                clients.append(waiter); active.append(waiter)
                waiter.send(*command); parked(c, i+1)
            c.cmd(*push)
            got = [w.read() for w in active]
            equal(got, wanted, "FIFO with duplicate binary key aliases")
            outputs.append(got); parked(c, 0)
        # A short-lived middle waiter must disappear without moving its neighbours.
        active = []
        for timeout in (0, .05, 0):
            w = Conn(c.host, c.port, timeout=5, buffering=0)
            clients.append(w); active.append(w); w.send("BLPOP", "timeouts", timeout)
            parked(c, len(active))
        equal(active[1].read(), None, "middle deadline")
        parked(c, 2)
        c.cmd("RPUSH", "timeouts", "first", "last")
        got = [active[i].read() for i in (0, 2)]
        equal(got, [[b"timeouts", b"first"], [b"timeouts", b"last"]], "FIFO after middle removal")
        outputs.append(got); parked(c, 0)
        # XREAD waiters on one key have independent cursors, unlike pop FIFO.
        active = []
        for cursor in ("5-0", "0-0"):
            w = Conn(c.host, c.port, timeout=5, buffering=0)
            clients.append(w); active.append(w)
            w.send("XREAD", "BLOCK", 0, "STREAMS", "wake", cursor); parked(c, len(active))
        c.cmd("XADD", "wake", "1-0", "f", "v")
        equal(active[1].read(), [[b"wake", [[b"1-0", [b"f", b"v"]]]]], "later eligible stream waiter")
        parked(c, 1)
        c.cmd("XADD", "wake", "6-0", "f", "v")
        equal(active[0].read(), [[b"wake", [[b"6-0", [b"f", b"v"]]]]], "older cursor waiter")
        parked(c, 0)
        # A disconnected alias is reaped, and the same logical key can register anew.
        w = Conn(c.host, c.port, timeout=5, buffering=0); clients.append(w)
        w.send("BLPOP", "reuse", 0); parked(c, 1); w.close(); parked(c, 0)
        w = Conn(c.host, c.port, timeout=5, buffering=0); clients.append(w)
        w.send("BLPOP", "reuse", 0); parked(c, 1); c.cmd("LPUSH", "reuse", "v")
        equal(w.read(), [b"reuse", b"v"], "queue removal and recreation")
        parked(c, 0)
        return outputs
    finally:
        for w in clients:
            w.close()



def probe(c, case):
    return registry(c)


if __name__ == "__main__":
    run(probe, ("registry",))
