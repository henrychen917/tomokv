#!/usr/bin/env python3
"""Defect (c)/(a) amplifier: run the losing shape N times and count silently lost writes.

Shape (one connection, one round):
    MULTI / RPUSH B v / RPUSH A v / EXEC        <- two owners, so a group ticket is drawn
    MULTI / RPUSH A x / EXEC                    <- reply says the element landed
    LRANGE A 0 -1                               <- ... and it is not there

Also reports the delta of atomic_predecessor_reads, which is the resolver telling us it answered
a read from a version older than the physical one.

Usage: c_loop.py PORT [ROUNDS]
"""
import socket
import sys

TP = int(sys.argv[1])
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 200


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


def info_stat(name):
    txt = cmd("INFO", "stats")
    for line in txt.split(b"\r\n"):
        if line.startswith(name.encode() + b":"):
            return int(line.split(b":")[1])
    return -1


cmd("FLUSHALL")
pre = info_stat("atomic_predecessor_reads")
lost = 0
badreply = 0
for i in range(ROUNDS):
    a, b = "lp:a:%04d" % i, "lp:b:%04d" % i
    cmd("MULTI"); cmd("RPUSH", b, "v"); cmd("RPUSH", a, "v"); cmd("EXEC")
    cmd("MULTI"); cmd("RPUSH", a, "x")
    e2 = cmd("EXEC")
    got = cmd("LRANGE", a, "0", "-1")
    if e2 != b"*1\r\n:2\r\n":
        badreply += 1
    if b"$1\r\nx" not in got:
        lost += 1
post = info_stat("atomic_predecessor_reads")
print("rounds=%d  silently_lost=%d (%.1f%%)  wrong_reply=%d  predecessor_reads_delta=%d"
      % (ROUNDS, lost, 100.0 * lost / ROUNDS, badreply, post - pre))
sys.exit(1 if lost else 0)
