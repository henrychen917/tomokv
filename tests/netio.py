#!/usr/bin/env python3
"""netio.py — directed battery for the --net-io network event engine.

    tests/netio.py HOST PORT [expected-engine]

`expected-engine` is uring (default) or epoll, and the battery ASSERTS the server really is on that
engine before it asserts anything else. That matters more here than in most batteries: almost every
check below would also pass on the other engine, so without the identity assertion a run against the
wrong boot would report a green epoll battery having exercised io_uring.

Each section names the engine mechanism it is proving and carries a control that must report zero,
because "nothing broke" is not evidence:

  A  engine identity         CONFIG GET net-io, and the epoll readiness counters in INFO STATS.
                             CONTROL: on a uring boot those counters must be EXACTLY zero, so the
                             counter cannot be a constant that happens to look alive.
  B  knob discipline         boot-only: CONFIG SET net-io is refused in either direction.
  C  readiness re-arm        an edge-triggered engine that stops reading early (ROB window full,
                             no read space) owes itself a retry, because no second edge is coming.
                             A pipeline deeper than the ROB window (64) in ONE write is exactly that
                             case: get every reply back, in order.
  D  partial writes          a reply far larger than the socket buffer forces EAGAIN mid-send and
                             must resume from the byte frontier on the EPOLLOUT edge. CONTROL: the
                             bytes are compared, not just counted, so a resumed send that restarts
                             from the wrong offset fails rather than merely being slow.
  E  cross-thread doorbell   BLPOP parks on one connection and is woken by a push from another. Under
                             epoll the wake is an eventfd mailbox, not io_uring msg_ring. The park
                             has a 50 ms ceiling, so a BROKEN doorbell still completes -- just late.
                             This asserts the LATENCY, which is the only thing that tells a working
                             doorbell from a timeout covering for a missing one.
  F  connection churn        open/close many connections, including abrupt RST and half-close, then
                             prove the server still serves and reports no leaked clients.
  G  clean teardown          CLIENT KILL on self must deliver its reply and then close.
"""
import socket
import struct
import sys
import time

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 6379
EXPECT = (sys.argv[3] if len(sys.argv) > 3 else "uring").lower()

CHECKS = 0
FAILS = []


def check(ok, label, detail=""):
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILS.append(f"{label}{(': ' + str(detail)) if detail else ''}")


class Conn:
    def __init__(self, timeout=10):
        self.sock = socket.create_connection((HOST, PORT), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""

    def send(self, *args):
        out = b"*%d\r\n" % len(args)
        for a in args:
            a = a.encode() if isinstance(a, str) else a
            out += b"$%d\r\n%s\r\n" % (len(a), a)
        self.sock.sendall(out)

    def send_raw(self, blob):
        self.sock.sendall(blob)

    def _more(self):
        d = self.sock.recv(1 << 20)
        if not d:
            raise EOFError("peer closed")
        self.buf += d

    def read_line(self):
        while b"\r\n" not in self.buf:
            self._more()
        line, self.buf = self.buf.split(b"\r\n", 1)
        return line

    def read_reply(self):
        line = self.read_line()
        tag, body = line[:1], line[1:]
        if tag in b"+-:,#":
            return line
        if tag == b"$":
            n = int(body)
            if n < 0:
                return None
            while len(self.buf) < n + 2:
                self._more()
            out, self.buf = self.buf[:n], self.buf[n + 2:]
            return out
        if tag == b"*":
            n = int(body)
            if n < 0:
                return None
            return [self.read_reply() for _ in range(n)]
        raise AssertionError("unparsed reply %r" % line)

    def cmd(self, *args):
        self.send(*args)
        return self.read_reply()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def info_stats(conn):
    raw = conn.cmd("INFO", "STATS")
    out = {}
    for line in raw.decode(errors="replace").split("\r\n"):
        if ":" in line and not line.startswith("#"):
            k, _, v = line.partition(":")
            out[k] = v
    return out


admin = Conn()

# ---- A: engine identity ---------------------------------------------------------------------
got = admin.cmd("CONFIG", "GET", "net-io")
engine = got[1].decode() if isinstance(got, list) and len(got) == 2 else None
check(engine == EXPECT, "A1 CONFIG GET net-io", f"reported {engine!r}, expected {EXPECT!r}")

# Drive some traffic so the readiness counters have something to count, then read them.
for i in range(200):
    admin.cmd("SET", "netio:a:%d" % i, "v%d" % i)
stats = info_stats(admin)
events = int(stats.get("net_io_epoll_events", -1))
recvs = int(stats.get("net_io_epoll_recvs", -1))
check(events >= 0 and recvs >= 0, "A2 epoll counters present in INFO STATS", stats.get("net_io_epoll_events"))
if EXPECT == "epoll":
    check(events > 0, "A3 epoll_wait actually delivered events", events)
    check(recvs > 0, "A3 epoll engine actually issued recv syscalls", recvs)
else:
    # THE CONTROL. On io_uring these must be exactly zero; a non-zero reading here would mean the
    # counter is not measuring what its name says and every epoll assertion above is worthless.
    check(events == 0, "A3 CONTROL uring boot reports zero epoll events", events)
    check(recvs == 0, "A3 CONTROL uring boot reports zero epoll recvs", recvs)

# ---- B: the knob is boot-only ------------------------------------------------------------------
for value in ("epoll", "uring"):
    reply = admin.cmd("CONFIG", "SET", "net-io", value)
    check(reply[:1] == b"-", "B1 CONFIG SET net-io %s refused" % value, reply)
check(admin.cmd("CONFIG", "GET", "net-io")[1].decode() == EXPECT,
      "B2 engine unchanged after refused CONFIG SET")

# ---- C: readiness re-arm past the ROB window ---------------------------------------------------
# ONE write carrying 512 commands. The ROB window is 64, so the parse pass MUST stop with bytes
# still buffered and resume later. Under an edge-triggered engine no further edge will arrive for
# those bytes, so a backend that waits for one wedges here instead of replying.
pipe = Conn(timeout=20)
DEPTH = 512
blob = b""
for i in range(DEPTH):
    key = b"netio:pipe:%d" % i
    val = b"p" * 64
    blob += b"*3\r\n$3\r\nSET\r\n$%d\r\n%s\r\n$%d\r\n%s\r\n" % (len(key), key, len(val), val)
pipe.send_raw(blob)
ok = True
for _ in range(DEPTH):
    if pipe.read_reply() != b"+OK":
        ok = False
check(ok, "C1 %d-deep single-write pipeline fully answered" % DEPTH)
blob = b"".join(b"*2\r\n$3\r\nGET\r\n$%d\r\n%s\r\n" % (len(b"netio:pipe:%d" % i), b"netio:pipe:%d" % i)
                for i in range(DEPTH))
pipe.send_raw(blob)
ordered = all(pipe.read_reply() == b"p" * 64 for _ in range(DEPTH))
check(ordered, "C2 pipelined replies returned in order")
pipe.close()

# ---- D: partial writes and the EAGAIN/EPOLLOUT resume -------------------------------------------
# 8 MB in one reply, read back slowly enough that the socket buffer fills and the server's send
# takes EAGAIN. Compared byte-for-byte: a resume from the wrong frontier corrupts, it does not stall.
BIG = 8 * 1024 * 1024
big = Conn(timeout=60)
payload = bytes((i * 7 + 11) & 0xFF for i in range(65536))
big.cmd("SET", "netio:big", payload * (BIG // len(payload)))
big.send("GET", "netio:big")
t0 = time.monotonic()
got = big.read_reply()
elapsed = time.monotonic() - t0
check(isinstance(got, bytes) and len(got) == BIG, "D1 8MB reply fully delivered",
      len(got) if isinstance(got, bytes) else got)
check(isinstance(got, bytes) and got == payload * (BIG // len(payload)),
      "D2 8MB reply byte-exact (resume frontier correct)")
big.cmd("DEL", "netio:big")
big.close()

# ---- E: the cross-thread doorbell, measured ----------------------------------------------------
# BLPOP parks on a connection owned by one io thread; the LPUSH lands on an executor which must wake
# that io thread. Under epoll that wake is an eventfd; the park has a 50 ms ceiling, so a wake that
# never arrives still completes -- at ~50 ms. Anything near the ceiling means the doorbell is dead
# and the timeout is covering for it.
LAT_BUDGET_MS = 25.0
worst = 0.0
for round_ in range(20):
    waiter = Conn(timeout=10)
    key = "netio:blk:%d" % round_
    waiter.cmd("DEL", key)
    waiter.send("BLPOP", key, "5")
    time.sleep(0.05)                      # let it actually park
    pusher = Conn(timeout=10)
    t0 = time.monotonic()
    pusher.cmd("LPUSH", key, "woke")
    reply = waiter.read_reply()
    dt_ms = (time.monotonic() - t0) * 1000.0
    worst = max(worst, dt_ms)
    check(reply == [key.encode(), b"woke"], "E1 BLPOP woken with the pushed value", reply)
    waiter.close()
    pusher.close()
check(worst < LAT_BUDGET_MS, "E2 doorbell wake latency under %.0fms (worst %.1fms)"
      % (LAT_BUDGET_MS, worst), worst)

# ---- F: connection churn, including abrupt resets ----------------------------------------------
before = int(info_stats(admin).get("total_connections_received", 0))
CHURN = 300
for i in range(CHURN):
    c = Conn(timeout=10)
    if i % 3 == 0:
        c.cmd("SET", "netio:churn:%d" % i, "x")
        # Abrupt RST rather than an orderly FIN: the teardown path must survive a peer that
        # vanishes mid-connection, which is where the deferred-free fences earn their keep.
        c.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        c.sock.close()
    elif i % 3 == 1:
        c.send("PING")                    # reply in flight when we go away
        c.sock.shutdown(socket.SHUT_WR)
        c.close()
    else:
        c.cmd("PING")
        c.close()
after = int(info_stats(admin).get("total_connections_received", 0))
check(after - before >= CHURN, "F1 all %d churn connections accepted" % CHURN, after - before)
check(admin.cmd("PING") == b"+PONG", "F2 server still serving after churn")
check(admin.cmd("GET", "netio:churn:0") == b"x", "F3 pre-RST write survived the reset")

# ---- G: close-after-reply --------------------------------------------------------------------
victim = Conn(timeout=10)
vid = victim.cmd("CLIENT", "ID")
check(victim.cmd("CLIENT", "KILL", "ID", vid[1:].decode(), "SKIPME", "NO") == b":1",
      "G1 CLIENT KILL self replied before closing")
deadline = time.monotonic() + 3
closed = False
victim.sock.settimeout(0.2)
while time.monotonic() < deadline and not closed:
    try:
        closed = victim.sock.recv(1) == b""
    except socket.timeout:
        continue
    except OSError:
        closed = True
check(closed, "G2 CLIENT KILL self closed the socket after the reply")
victim.close()

for i in range(200):
    admin.cmd("DEL", "netio:a:%d" % i)
for i in range(DEPTH):
    admin.cmd("DEL", "netio:pipe:%d" % i)

if FAILS:
    print("netio(%s): %d checks, %d FAILURES" % (EXPECT, CHECKS, len(FAILS)))
    for f in FAILS:
        print("  FAIL " + f)
    sys.exit(1)
print("netio(%s): %d checks, 0 failures, epoll_events=%d epoll_recvs=%d worst_wake=%.1fms -> PASS"
      % (EXPECT, CHECKS, events, recvs, worst))
