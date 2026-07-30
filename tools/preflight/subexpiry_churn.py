#!/usr/bin/env python3
"""SUBEXPIRY CHURN — hammer hash-field TTLs while the worker active-expire cycle reclaims them.

WHY. The worker half of the hash-field cycle (exActiveSubexpiresCycle) runs from exSlice and takes
ALL of the node's worker locks, ascending — the same lock set an HFE command takes, but acquired
from a thread that is itself on the request path. The traffic-free probe cannot exercise that at
all: it proves reclaim happens, not that reclaim is safe next to concurrent HFE traffic.

So this drives the two against each other: many clients doing HSET/HPEXPIRE/HGETALL/HDEL/HRANDFIELD
against short TTLs, while the background cycle is actively deleting the same hashes out from under
them. What it is looking for is a crash, a hang, or a wedged connection — not a throughput number.

Correctness oracle beyond "still alive": every field this script writes with a LONG ttl must still
be readable at the end (the cycle must not reclaim un-due fields), and the server must answer PING
within the timeout the whole time.

Usage: subexpiry_churn.py <port> <seconds> [threads] [keyspace]
Exit 0 = survived with the oracle intact.
"""
import socket, sys, threading, time, random

PORT = int(sys.argv[1])
SECS = int(sys.argv[2])
THREADS = int(sys.argv[3]) if len(sys.argv) > 3 else 8
KEYSPACE = int(sys.argv[4]) if len(sys.argv) > 4 else 20000

stop = threading.Event()
errors = []


def enc(*args):
    out = [b"*%d\r\n" % len(args)]
    for a in args:
        if isinstance(a, str):
            a = a.encode()
        out.append(b"$%d\r\n%s\r\n" % (len(a), a))
    return b"".join(out)


class Conn:
    def __init__(self):
        self.s = socket.create_connection(("127.0.0.1", PORT), timeout=15)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""

    def cmd(self, *a):
        self.s.sendall(enc(*a))
        return self.read_reply()

    def _fill(self):
        d = self.s.recv(65536)
        if not d:
            raise IOError("server closed the connection")
        self.buf += d

    def _line(self):
        while b"\r\n" not in self.buf:
            self._fill()
        i = self.buf.index(b"\r\n")
        ln, self.buf = self.buf[:i], self.buf[i + 2:]
        return ln

    def read_reply(self):
        ln = self._line()
        t, rest = ln[:1], ln[1:]
        if t in b"+:,#":
            return rest
        if t == b"-":
            raise IOError("server error: " + rest.decode(errors="replace"))
        if t == b"$":
            n = int(rest)
            if n == -1:
                return None
            while len(self.buf) < n + 2:
                self._fill()
            v, self.buf = self.buf[:n], self.buf[n + 2:]
            return v
        if t in b"*~%":
            n = int(rest)
            if n == -1:
                return None
            if t == b"%":
                n *= 2
            return [self.read_reply() for _ in range(n)]
        raise IOError("unparsed reply type %r (%r)" % (t, ln[:64]))


def worker(idx):
    try:
        c = Conn()
        rnd = random.Random(idx * 7919 + 13)
        while not stop.is_set():
            k = "chx:%d" % rnd.randrange(KEYSPACE)
            f = "f%d" % rnd.randrange(4)
            op = rnd.randrange(6)
            if op == 0:
                c.cmd("HSET", k, f, "v" * rnd.randrange(1, 40))
                # Short TTL: this field is meant to be reclaimed by the background cycle.
                c.cmd("HPEXPIRE", k, str(rnd.randrange(50, 900)), "FIELDS", "1", f)
            elif op == 1:
                c.cmd("HGETALL", k)
            elif op == 2:
                c.cmd("HDEL", k, f)
            elif op == 3:
                c.cmd("HRANDFIELD", k, "2")
            elif op == 4:
                c.cmd("HTTL", k, "FIELDS", "1", f)
            else:
                c.cmd("HLEN", k)
    except Exception as e:  # noqa: BLE001 - any failure is a finding
        errors.append("thread %d: %r" % (idx, e))
        stop.set()


ctl = Conn()
# ORACLE SETUP: long-TTL fields that must survive the whole run. If the cycle ever reclaims by
# anything other than the deadline, these vanish and the run fails loudly.
SURVIVORS = 200
for i in range(SURVIVORS):
    ctl.cmd("HSET", "chx:keep:%d" % i, "f", "survivor")
    ctl.cmd("HPEXPIRE", "chx:keep:%d" % i, "3600000", "FIELDS", "1", "f")

ts = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(THREADS)]
for t in ts:
    t.start()

t0 = time.time()
pings = 0
while time.time() - t0 < SECS and not stop.is_set():
    time.sleep(0.5)
    try:
        if ctl.cmd("PING") != b"PONG":
            errors.append("PING did not answer PONG")
            break
        pings += 1
    except Exception as e:  # noqa: BLE001
        errors.append("control connection died: %r" % e)
        break
stop.set()
for t in ts:
    t.join(timeout=10)
alive = [t for t in ts if t.is_alive()]
if alive:
    errors.append("%d churn thread(s) HUNG (did not exit in 10s)" % len(alive))

# ORACLE CHECK
lost = 0
try:
    c2 = Conn()
    for i in range(SURVIVORS):
        v = c2.cmd("HGET", "chx:keep:%d" % i, "f")
        if v != b"survivor":
            lost += 1
    stats = c2.cmd("INFO", "stats").decode(errors="replace")
    act = [l for l in stats.splitlines() if l.startswith("expired_subkeys_active:")]
except Exception as e:  # noqa: BLE001
    errors.append("post-run verification failed: %r" % e)
    act = []
    lost = -1

print("churn: %ds x %d threads, %d pings, survivors_lost=%d, %s"
      % (SECS, THREADS, pings, lost, act[0] if act else "no stats"))
if lost > 0:
    errors.append("%d/%d long-TTL survivor fields were reclaimed early" % (lost, SURVIVORS))
if errors:
    for e in errors:
        print("  CHURN FAILURE: " + e)
    sys.exit(1)
print("churn: PASS (no crash, no hang, no early reclaim)")
sys.exit(0)
