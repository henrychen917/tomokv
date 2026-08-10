#!/usr/bin/env python3
"""ee451 (#B2) CONFIG RESETSTAT probe — the five assertions cmdstat_check.py cannot reach.

WHY THIS EXISTS. cmdstat_check.py ends with a RESETSTAT section, and on this fork that section is
UNREACHABLE: the server SEGFAULTS on `CONFIG RESETSTAT` once error replies have been recorded.
That crash is PRE-EXISTING (it reproduces identically on the pre-#B2 binary, see
docs/STABLE_PLAN.md section 4, `errorstats concurrent raxInsert`) — resetErrorTableStats frees
server.errors while every IO thread and worker is still doing raxFind/raxInsert on it, so
raxFreeWithCallback trips `rax.c:1280 'rax->numnodes == 0'` and a concurrent walker then reads
freed nodes. cmdstat_check.py drives 5000 deliberate WRONGTYPE errors before it gets there, so it
always dies at that point and its last five assertions never run.

Deleting those assertions would be the wrong repair — they are the ones that catch a RESETSTAT
that clears only the legacy scalars and leaves the per-thread shards reporting pre-reset totals.
So this probe checks the SAME property over a workload with NO error replies, which leaves
server.errors empty and makes the rax teardown a no-op. It is not a workaround for the crash; the
crash stays visible in cmdstat_check.py, which is where it belongs.

IT DISCRIMINATES. Assertion 3 (counting RESUMES after the reset) reads 0 on a pre-#B2 build, for
the same reason every other worker-route count did. Assertions 1 and 2 are POST-correctness only:
on a build with no shards there is nothing for a reset to fail to clear.

Exit 0 = every assertion held, 1 = at least one did not, 2 = precondition not met.
"""
import socket, sys, time

port = int(sys.argv[1])
label = sys.argv[2] if len(sys.argv) > 2 else "run"
N = 20000
fails = []


def cmd(*a):
    o = f"*{len(a)}\r\n".encode()
    for x in a:
        b = x if isinstance(x, bytes) else str(x).encode()
        o += b"$%d\r\n%s\r\n" % (len(b), b)
    return o


SENT = b"ZZ_RESET_PROBE_ZZ"


def read_bulk(s):
    buf = b""
    while True:
        c = s.recv(1 << 20)
        if not c:
            raise RuntimeError("connection closed mid-reply")
        buf += c
        if buf[0:1] != b"$":
            raise RuntimeError("unexpected reply %r" % buf[:64])
        hdr = buf.find(b"\r\n")
        if hdr < 0:
            continue
        n = int(buf[1:hdr])
        if n < 0:
            return b""
        if len(buf) >= hdr + 2 + n + 2:
            return buf[hdr + 2:hdr + 2 + n]


def info(s, section):
    s.sendall(cmd("INFO", section))
    return read_bulk(s).decode(errors="replace")


def calls_of(s, name):
    for line in info(s, "commandstats").splitlines():
        if line.startswith("cmdstat_%s:" % name):
            for kv in line.split(":", 1)[1].split(","):
                k, _, v = kv.partition("=")
                if k == "calls":
                    return int(v)
    return 0


def drain(s, payload):
    s.sendall(payload + cmd("ECHO", SENT))
    b = b""
    while SENT not in b:
        c = s.recv(1 << 20)
        if not c:
            raise RuntimeError("closed before sentinel")
        b = b[-64:] + c


def check(name, got, want):
    ok = got == want
    print("  %-46s got=%-10s want=%-10s %s" % (name, got, want, "OK" if ok else "*** WRONG ***"))
    if not ok:
        fails.append("%s: got %s want %s" % (name, got, want))


s = socket.create_connection(("127.0.0.1", port))
s.settimeout(180)
s.sendall(cmd("CONFIG", "SET", "latency-tracking", "yes"))
s.recv(1 << 16)

# PRECONDITION, asserted rather than assumed: this probe is only safe while server.errors is
# empty. If anything has recorded an error we would be walking into the pre-existing crash and any
# result would be worthless, so stop with a distinct status instead.
es = [l for l in info(s, "errorstats").splitlines() if l.startswith("errorstat_")]
if es:
    print("%s: PRECONDITION FAILED — errorstats is non-empty, RESETSTAT would hit the "
          "pre-existing errorstats rax crash: %s" % (label, es[:4]))
    sys.exit(2)

drain(s, b"".join(cmd("SET", "rk:%d" % i, "v") for i in range(N)))
drain(s, b"".join(cmd("GET", "rk:%d" % i) for i in range(N)))
time.sleep(0.5)

print("%s: baseline — the shards counted the worker-routed traffic" % label)
check("cmdstat_set:calls before reset", calls_of(s, "set"), N)
check("cmdstat_get:calls before reset", calls_of(s, "get"), N)

s.sendall(cmd("CONFIG", "RESETSTAT"))
s.recv(1 << 16)
time.sleep(0.2)

print("%s: 1/2 RESETSTAT must clear the per-thread COUNTER shards" % label)
check("cmdstat_set:calls after reset", calls_of(s, "set"), 0)
check("cmdstat_get:calls after reset", calls_of(s, "get"), 0)

print("%s: 2/2 RESETSTAT must clear the per-thread HISTOGRAM shards" % label)
gone = [l for l in info(s, "latencystats").splitlines()
        if l.startswith("latency_percentiles_usec_get")]
check("latency_percentiles_usec_get after reset", gone, [])

# THE DISCRIMINATING ONE: a reset that hdr_close()d the shards, or unpublished the block pointer,
# would leave counting permanently dead rather than merely zeroed — and a pre-#B2 build reads 0
# here for the original defect. Either way this assertion goes red.
drain(s, b"".join(cmd("GET", "rk:%d" % i) for i in range(N)))
time.sleep(0.5)
print("%s: 3/3 counting must RESUME after the reset" % label)
check("cmdstat_get:calls after reset + %d more" % N, calls_of(s, "get"), N)

print()
if fails:
    print("%s: FAILED (%d)" % (label, len(fails)))
    for f in fails:
        print("   - " + f)
    sys.exit(1)
print("%s: PASSED" % label)
sys.exit(0)
