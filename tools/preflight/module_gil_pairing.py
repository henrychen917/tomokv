#!/usr/bin/env python3
"""Driver for module_gil_pairing.sh -- see that file for the defect.

THE ORACLE IS THE HUNG-CONNECTION FRACTION.

The previous version of this probe watched INFO server's uptime_in_seconds, on the theory that
server.unixtime is refreshed only by main. That is FALSE in this fork and the probe was therefore
vacuous -- it passed on binaries whose main thread was provably dead in afterSleep. afterSleepIO()
calls updateCachedTime(1) (src/server.c:2962) and is registered on EVERY IO thread's event loop
(src/server.c:17796 and 17851), so the clock keeps advancing perfectly while main is deadlocked.

What actually stops when an event-loop thread wedges is that thread's share of the connections.
Each IO thread has its own listener, so the kernel keeps handing new connections to the dead one
and they are never answered: the hang rate settles at roughly 1/io_threads. Established
connections on the surviving threads keep working, which is exactly why PING, SET, GET and INFO
all "prove" the server healthy. Only fresh connections expose it.

Discrimination is checked in module_gil_pairing.sh's header; briefly, against a binary with a
known-deadlocked main this reports 25% at io=4 and 100% at io=1, versus 0% healthy.
"""
import argparse, socket, sys, time


def enc(*parts):
    out = bytearray(b"*%d\r\n" % len(parts))
    for p in parts:
        if isinstance(p, str):
            p = p.encode()
        out += b"$%d\r\n%s\r\n" % (len(p), p)
    return bytes(out)


class C:
    def __init__(self, port, t=10.0):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=t)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""

    def cmd(self, *parts, budget=10.0):
        self.s.settimeout(budget); self.s.sendall(enc(*parts))
        end = time.time() + budget
        while time.time() < end:
            if b"\r\n" in self.buf:
                h = self.buf[:1]
                i = self.buf.find(b"\r\n")
                if h in (b"+", b"-", b":"):
                    line, self.buf = self.buf[:i], self.buf[i + 2:]
                    return line.decode(errors="replace")
                if h == b"$":
                    n = int(self.buf[1:i])
                    if n == -1:
                        self.buf = self.buf[i + 2:]; return None
                    if len(self.buf) >= i + 2 + n + 2:
                        b = self.buf[i + 2:i + 2 + n]; self.buf = self.buf[i + 2 + n + 2:]
                        return b.decode(errors="replace")
            d = self.s.recv(1 << 20)
            if not d:
                raise ConnectionError("closed")
            self.buf += d
        raise TimeoutError("no reply in %.1fs" % budget)

    def close(self):
        try: self.s.close()
        except Exception: pass


def fresh_conn_sweep(port, n, budget=3.0):
    """Open n brand-new connections and round-trip one command on each. Returns hangs."""
    hung = 0
    for i in range(n):
        c = None
        try:
            c = C(port, t=budget)
            c.cmd("SET", "gil:sweep:%d" % i, "1", budget=budget)
        except Exception:
            hung += 1
        finally:
            if c: c.close()
    return hung


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--reloads", type=int, default=60)
    ap.add_argument("--keys", type=int, default=120000)
    ap.add_argument("--sweep", type=int, default=16, help="fresh conns per liveness sweep")
    ap.add_argument("--io-threads", type=int, default=4, help="only used to report the expected rate")
    a = ap.parse_args()

    val = b"x" * 64
    # Several connections so DEBUG RELOAD lands on IO threads other than 0 -- the race needs the
    # reload's processEventsWhileBlocked() to run OFF main. Which thread owns a connection is not
    # selectable from outside, so we spread the reloads and rely on coverage.
    fleet = [C(a.port) for _ in range(8)]
    load = C(a.port)

    # A keyspace worth reloading: the load-progress callback that calls processEventsWhileBlocked()
    # only fires periodically during the RDB load, so an empty db reproduces nothing.
    pipe = bytearray()
    for i in range(a.keys):
        pipe += enc(b"SET", b"gil:%d" % i, val)
    load.s.sendall(pipe)
    got = 0
    load.s.settimeout(60.0)
    while got < a.keys:
        d = load.s.recv(1 << 20)
        if not d:
            print("FAIL\tserver closed the load connection while populating"); return 1
        got += d.count(b"\r\n")

    base = fresh_conn_sweep(a.port, a.sweep)
    if base:
        print("FAIL\tbaseline sweep already hung %d/%d fresh connections before any reload"
              % (base, a.sweep))
        return 1

    t0 = time.time()
    for r in range(1, a.reloads + 1):
        c = fleet[r % len(fleet)]
        try:
            c.cmd("DEBUG", "RELOAD", budget=60.0)
        except Exception as e:
            # A reload that never returns is itself the wedge (its own IO thread is stuck).
            print("FAIL\treload %d did not return: %s" % (r, type(e).__name__)); return 1

        hung = fresh_conn_sweep(a.port, a.sweep)
        if hung:
            # Confirm it persists rather than being one scheduling blip.
            time.sleep(1.0)
            again = fresh_conn_sweep(a.port, a.sweep)
            if again:
                print("FAIL\treload %d: %d/%d then %d/%d fresh connections got NO reply after "
                      "%.0fs. Established connections still work, so this is a wedged event-loop "
                      "thread; ~1/%d is main dead in afterSleep on the module GIL."
                      % (r, hung, a.sweep, again, a.sweep, time.time() - t0, a.io_threads))
                return 1

    print("PASS\t%d reloads, %d fresh-connection sweeps of %d, 0 hung -- every event loop alive"
          % (a.reloads, a.reloads + 1, a.sweep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
