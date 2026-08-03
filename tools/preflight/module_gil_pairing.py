#!/usr/bin/env python3
"""Driver for module_gil_pairing.sh -- see that file for the defect and the detector.

Fires DEBUG RELOAD from connections that are NOT on IO thread 0, under concurrent load, and watches
INFO server's uptime_in_seconds. main refreshes server.unixtime from afterSleep/serverCron (both
main-only), so a frozen uptime while the server still answers commands means MAIN IS DEAD -- which
is the only externally visible signature of this bug.
"""
import argparse, socket, sys, time


def conn(port, t=10.0):
    s = socket.create_connection(("127.0.0.1", port), timeout=t)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s


def enc(*parts):
    out = bytearray(b"*%d\r\n" % len(parts))
    for p in parts:
        if isinstance(p, str):
            p = p.encode()
        out += b"$%d\r\n%s\r\n" % (len(p), p)
    return bytes(out)


class C:
    def __init__(self, port, t=10.0):
        self.s = conn(port, t); self.buf = b""

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

    def uptime(self, budget=10.0):
        t = self.cmd("INFO", "server", budget=budget) or ""
        for ln in t.splitlines():
            if ln.startswith("uptime_in_seconds:"):
                return int(ln.split(":", 1)[1])
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--reloads", type=int, default=60)
    ap.add_argument("--keys", type=int, default=120000)
    a = ap.parse_args()

    val = b"x" * 64
    # Several connections so DEBUG RELOAD lands on IO threads other than 0. Which thread owns a
    # connection is not selectable from outside, so we spread the reloads across many and rely on
    # coverage rather than on picking.
    fleet = [C(a.port) for _ in range(8)]
    load = C(a.port)
    mon = C(a.port)

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
            print("FAIL	server closed the load connection while populating"); return 1
        got += d.count(b"\r\n")

    base_up, base_wall = mon.uptime(), time.time()
    if base_up is None:
        print("FAIL	uptime_in_seconds missing from INFO server"); return 1

    for r in range(1, a.reloads + 1):
        c = fleet[r % len(fleet)]
        try:
            c.cmd("DEBUG", "RELOAD", budget=60.0)
        except Exception as e:
            # A reload that never returns is itself the wedge (its own IO thread is stuck).
            print("FAIL	reload %d did not return: %s" % (r, type(e).__name__)); return 1
        # keep other threads busy so main has beforeSleep work to race against
        try:
            c.cmd("SET", "gil:probe", "1", budget=15.0)
        except Exception:
            pass

        wall = time.time() - base_wall
        try:
            up = mon.uptime(budget=15.0)
        except Exception:
            up = None
            try:
                mon2 = C(a.port); up = mon2.uptime(budget=15.0)
            except Exception:
                pass
        if up is None:
            print("FAIL	reload %d: INFO unanswerable after %.0fs of wall clock" % (r, wall)); return 1
        drift = wall - (up - base_up)
        # uptime is integer seconds, so allow a couple of seconds of quantisation + scheduling.
        if wall > 20 and drift > 12:
            alive = "yes"
            try:
                C(a.port).cmd("SET", "gil:alive", "1", budget=5.0)
            except Exception:
                alive = "no"
            print("FAIL	reload %d: main's clock is FROZEN -- %.0fs of wall clock but uptime "
                  "advanced only %ds (drift %.0fs). Server still serving commands: %s. That is "
                  "main dead in afterSleep while the IO threads carry on."
                  % (r, wall, up - base_up, drift, alive))
            return 1

    wall = time.time() - base_wall
    up = mon.uptime()
    print("PASS	%d reloads, %.0fs wall, uptime advanced %ds (drift %.0fs) -- main stayed alive"
          % (a.reloads, wall, up - base_up, wall - (up - base_up)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
