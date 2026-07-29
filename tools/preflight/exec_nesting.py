#!/usr/bin/env python3
"""EXECUTION-NESTING CROSS-THREAD TEST — see exec_nesting.sh for why this exists.

Writes `name<TAB>PASS|FAIL<TAB>detail` rows to argv[1].
"""
import socket, sys, time, threading

OUT    = sys.argv[1]
PORT   = int(sys.argv[2])
NCMD   = int(sys.argv[3]) if len(sys.argv) > 3 else 50
SLP_MS = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0
ARM_S  = float(sys.argv[5]) if len(sys.argv) > 5 else 3.0
NCONN  = 8
EXPECT = NCMD * SLP_MS * 1000.0      # us of command duration the probe loop generates

res = []
def rec(name, ok, detail=""):
    res.append((name, "PASS" if ok else "FAIL", detail))


def enc(*a):
    o = ("*%d\r\n" % len(a)).encode()
    for x in a:
        b = x if isinstance(x, bytes) else str(x).encode()
        o += b"$%d\r\n%s\r\n" % (len(b), b)
    return o


class R:
    def __init__(self, s):
        self.s = s
        self.buf = b""

    def send(self, *a):
        self.s.sendall(enc(*a))

    def _line(self):
        while b"\r\n" not in self.buf:
            c = self.s.recv(1 << 20)
            if not c:
                raise EOFError
            self.buf += c
        i = self.buf.index(b"\r\n")
        ln, self.buf = self.buf[:i], self.buf[i + 2:]
        return ln

    def reply(self):
        ln = self._line()
        t, rest = ln[:1], ln[1:]
        if t in b"+-:":
            return rest
        if t == b"$":
            n = int(rest)
            if n < 0:
                return None
            while len(self.buf) < n + 2:
                self.buf += self.s.recv(1 << 20)
            v, self.buf = self.buf[:n], self.buf[n + 2:]
            return v
        if t == b"*":
            n = int(rest)
            if n < 0:
                return None
            return [self.reply() for _ in range(n)]
        raise ValueError(ln)

    def do(self, *a):
        self.send(*a)
        return self.reply()


def cmd_sum(rc):
    txt = rc.do("INFO", "stats")
    for ln in txt.decode(errors="replace").splitlines():
        if ln.startswith("eventloop_duration_cmd_sum:"):
            return int(ln.split(":", 1)[1])
    raise KeyError("eventloop_duration_cmd_sum")


def measure(P, S):
    """(delta_us, note). S=None for the unarmed control. delta_us None => rig failure."""
    sum0 = cmd_sum(P)
    ev = threading.Event()
    if S is not None:
        def arm():
            try:
                S.do("DEBUG", "SLEEP", ARM_S)
            finally:
                ev.set()
        threading.Thread(target=arm, daemon=True).start()
        time.sleep(0.3)
        if ev.is_set():
            return None, "sleeper returned before the probe started"
    t0 = time.time()
    for _ in range(NCMD):
        P.do("DEBUG", "SLEEP", SLP_MS / 1000.0)
    el = time.time() - t0
    if S is not None and ev.is_set():
        return None, "arm expired at %.2fs, before the probe loop finished" % el
    d = cmd_sum(P) - sum0
    if S is not None:
        if ev.is_set():
            return None, "arm expired before the INFO read"
        ev.wait(ARM_S + 10)
    return d, "loop=%.3fs" % el


def main():
    try:
        conns = []
        for _ in range(NCONN):
            s = socket.create_connection(("127.0.0.1", PORT))
            s.settimeout(120)
            conns.append(R(s))
        for c in conns:
            c.do("PING")
    except Exception as e:
        rec("boot", False, "%s: %s" % (type(e).__name__, e))
        open(OUT, "w").write("".join("%s\t%s\t%s\n" % r for r in res))
        return 2

    S = conns[0]
    # ORACLE: DEBUG SLEEP parks the OWNING io thread's whole event loop, so only a connection on a
    # different io thread can answer meanwhile. Measured, never assumed: with 1 io thread there is
    # no second thread to hold, and this test would be vacuous.
    ev = threading.Event()

    def hold():
        try:
            S.do("DEBUG", "SLEEP", 1.0)
        finally:
            ev.set()
    threading.Thread(target=hold, daemon=True).start()
    time.sleep(0.15)
    elsewhere = []
    for c in conns[1:]:
        c.s.settimeout(0.45)
        try:
            t0 = time.time()
            c.do("PING")
            if time.time() - t0 < 0.45 and not ev.is_set():
                elsewhere.append(c)
        except (socket.timeout, OSError):
            pass          # co-resident (or late): discard, never reuse this connection
        finally:
            c.s.settimeout(120)
    ev.wait(5)
    rec("io-thread-partition", bool(elsewhere), "%d/%d conns on another io thread" % (len(elsewhere), NCONN - 1))
    if not elsewhere:
        open(OUT, "w").write("".join("%s\t%s\t%s\n" % r for r in res))
        return 1
    P = elsewhere[0]
    nonce = b"sync-%d" % (int(time.time() * 1e6) % 1000000)
    P.send("ECHO", nonce)
    t0 = time.time()
    while P.reply() != nonce:
        if time.time() - t0 > 15:
            rec("resync", False, "probe connection never resynced")
            open(OUT, "w").write("".join("%s\t%s\t%s\n" % r for r in res))
            return 1

    armed, anote = measure(P, S)
    ctrl,  cnote = measure(P, None)
    rec("arm-overlap", armed is not None, anote)
    # The control is the anti-vacuity guard: it must move the sum on THIS build, or "the sum did
    # not move" under the arm proves nothing at all.
    rec("unarmed-control-records-samples", ctrl is not None and ctrl >= EXPECT * 0.5,
        "delta=%s expect>=%.0f (%s)" % (ctrl, EXPECT * 0.5, cnote))
    ok = (armed is not None and ctrl is not None
          and ctrl >= EXPECT * 0.5 and armed >= EXPECT * 0.5)
    rec("cross-thread-nesting-does-not-suppress-sampling", ok,
        "armed=%s control=%s expect~%.0f" % (armed, ctrl, EXPECT))
    open(OUT, "w").write("".join("%s\t%s\t%s\n" % r for r in res))
    print("".join("%s\t%s\t%s\n" % r for r in res), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
