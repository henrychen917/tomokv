#!/usr/bin/env python3
"""Masked-monolith directed test: pipelined flood spanning ALL owners while flipping between
extreme splits. Asserts no loss, no per-connection reorder, correct values after each phase.
usage: maskflood.py HOST PORT"""
import socket, sys, time

HOST, PORT = sys.argv[1], int(sys.argv[2])

def conn():
    s = socket.create_connection((HOST, PORT)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s, s.makefile("rb")

def enc(*argv):
    out = b"*%d\r\n" % len(argv)
    for a in argv:
        a = a.encode() if isinstance(a, str) else a
        out += b"$%d\r\n%s\r\n" % (len(a), a)
    return out

def read(f):
    ln = f.readline(); t = ln[:1]
    if t in b"+-:": return ln[:-2]
    if t == b"$":
        n = int(ln[1:]); return None if n < 0 else f.read(n + 2)[:-2]
    if t == b"*":
        n = int(ln[1:]); return None if n < 0 else [read(f) for _ in range(n)]
    raise AssertionError(ln)

ctl, ctlf = conn()
ctl.sendall(enc("FLIP")); rep = read(ctlf)
total = None
if isinstance(rep, list):
    kv = dict(zip(rep[::2], rep[1::2]))
    total = int(kv.get(b"live_io", b"0").lstrip(b":")) + int(kv.get(b"live_ex", b"0").lstrip(b":"))
assert total and total >= 4, "need a flip-capable boot, got %r" % rep

NKEYS, ROUNDS, PIPE = 4096, 6, 64
splits = [(total - 1, 1), (1, total - 1), (total // 2, total - total // 2)]
s, f = conn()
for rnd in range(ROUNDS):
    io_n, ex_n = splits[rnd % len(splits)]
    ctl.sendall(enc("FLIP", str(io_n), str(ex_n)))
    assert read(ctlf) in (b"OK", b"+OK"), "flip refused"
    # pipelined SET flood over keys spanning every owner, value tagged by round
    for base in range(0, NKEYS, PIPE):
        batch = b"".join(enc("SET", "mf:%d" % k, "r%d-%d" % (rnd, k)) for k in range(base, base + PIPE))
        s.sendall(batch)
        for _ in range(PIPE): assert read(f) == b"+OK", "SET lost/reordered"
    # verify a stride of reads sees THIS round's values (RYOW across the flip)
    for base in range(0, NKEYS, PIPE):
        batch = b"".join(enc("GET", "mf:%d" % k) for k in range(base, base + PIPE))
        s.sendall(batch)
        for i in range(PIPE):
            v = read(f); k = base + i
            assert v == b"r%d-%d" % (rnd, k), "wrong value for mf:%d after flip io%d: %r" % (k, io_n, v)
print("maskflood: %d rounds x %d keys across splits %s: PASS" % (ROUNDS, NKEYS, splits))
