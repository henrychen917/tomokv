#!/usr/bin/env python3
"""Defect (c): isolate the exact 7-op losing shape on a fresh connection.

Usage: c_iso.py TARGET_PORT [KEYA KEYB]
"""
import socket
import sys

TP = int(sys.argv[1])
A = sys.argv[2] if len(sys.argv) > 2 else "lz:A"
B = sys.argv[3] if len(sys.argv) > 3 else "lz:B"


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


def fresh():
    s = socket.create_connection(("127.0.0.1", TP), timeout=30)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s, s.makefile("rb")


s, f = fresh()


def cmd(*argv):
    s.sendall(enc(list(argv)))
    return read_reply(f)


SEQ = [["FLUSHALL"],
       ["MULTI"], ["RPUSH", B, "v"], ["RPUSH", A, "v"], ["EXEC"],
       ["MULTI"], ["RPUSH", A, "x"], ["EXEC"],
       ["LRANGE", A, "0", "-1"], ["LRANGE", B, "0", "-1"]]

print("shard(%s)=%s shard(%s)=%s" % (A, cmd("DEBUG", "SHARD", A).strip(),
                                     B, cmd("DEBUG", "SHARD", B).strip()))
for c in SEQ:
    r = cmd(*c)
    print("  %-40s -> %r" % (" ".join(c)[:40], r[:120]))
