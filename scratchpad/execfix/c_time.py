#!/usr/bin/env python3
"""Defect (c): when does the element disappear, and does shard placement matter?

Usage: c_time.py TARGET_PORT
"""
import socket
import sys
import time

TP = int(sys.argv[1])


def enc(argv):
    out = bytearray(b"*%d\r\n" % len(argv))
    for a in argv:
        if isinstance(a, str):
            a = a.encode()
        out += b"$%d\r\n" % len(a) + a + b"\r\n"
    return bytes(out)


def read_reply(f):
    line = f.readline()
    if not line:
        raise EOFError
    k = line[:1]
    if k in (b"+", b"-", b":"):
        return line
    if k == b"$":
        n = int(line[1:-2])
        return line if n == -1 else line + f.read(n + 2)
    if k == b"*":
        n = int(line[1:-2])
        return line if n == -1 else line + b"".join(read_reply(f) for _ in range(n))
    raise ValueError(line)


s = socket.create_connection(("127.0.0.1", TP), timeout=30)
s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
f = s.makefile("rb")


def cmd(*argv):
    s.sendall(enc(list(argv)))
    return read_reply(f)


def shard_of(k):
    return int(cmd("DEBUG", "SHARD", k)[1:-2])


cmd("FLUSHALL")
# Build a key pool with known shards
pool = {}
for i in range(400):
    k = "sk:%03d" % i
    pool.setdefault(shard_of(k), []).append(k)
shards = sorted([sh for sh, v in pool.items() if len(v) >= 2])
print("shards seen: %s" % shards[:8])

SAME = (pool[shards[0]][0], pool[shards[0]][1])
DIFF = (pool[shards[0]][0], pool[shards[1]][0])


FLUSH = "--flush" in sys.argv


def trial(a, b, label, peek=False):
    if FLUSH:
        cmd("FLUSHALL")
    cmd("DEL", a); cmd("DEL", b)
    cmd("MULTI"); cmd("RPUSH", b, "v"); cmd("RPUSH", a, "v"); r1 = cmd("EXEC")
    imm_a0 = cmd("LRANGE", a, "0", "-1") if peek else b"(skipped)"
    cmd("MULTI"); cmd("RPUSH", a, "x"); r2 = cmd("EXEC")
    imm = cmd("LRANGE", a, "0", "-1")
    time.sleep(0.25)
    late = cmd("LRANGE", a, "0", "-1")
    for _ in range(50):
        cmd("PING")
    settled = cmd("LRANGE", a, "0", "-1")
    bad = b"$1\r\nx" not in settled
    print("%-24s sh(a)=%-2d sh(b)=%-2d peek=%-5s exec1=%-18r exec2=%-12r %s" %
          (label, shard_of(a), shard_of(b), peek, r1[:40], r2[:20], "LOST" if bad else "ok"))
    if bad or peek:
        print("     after-tx1=%r" % (imm_a0,))
        print("     immediate=%r  after-250ms=%r  after-pings=%r" % (imm, late, settled))
    return bad


trial(SAME[0], SAME[1], "same-shard, peek", peek=True)
trial(SAME[0], SAME[1], "same-shard, no peek")
trial(DIFF[0], DIFF[1], "diff-shard, peek", peek=True)
trial(DIFF[0], DIFF[1], "diff-shard, no peek")
print("--- shard sweep, no peek ---")
lost = 0
for sh in shards[1:]:
    lost += trial(pool[shards[0]][0], pool[sh][0], "a@%d b@%d" % (shards[0], sh))
for sh in shards[1:]:
    lost += trial(pool[shards[0]][2], pool[shards[0]][3], "a@%d b@%d (same)" % (shards[0], shards[0]))
    break
print("lost cells: %d" % lost)
