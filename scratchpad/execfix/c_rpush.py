#!/usr/bin/env python3
"""Defect (c) minimal probe: RPUSH of a large element inside MULTI.

Usage: c_rpush.py TARGET_PORT [ORACLE_PORT]
Runs a matrix of (seeded?, element size) x (bare | in-MULTI) and prints, for each cell, the
RPUSH reply, the LLEN and the LRANGE the server answers afterwards.  With an oracle port the
same script is run against vanilla redis and the two are compared field by field.
"""
import socket
import sys

TP = int(sys.argv[1])
OP = int(sys.argv[2]) if len(sys.argv) > 2 else None


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


def conn(port):
    s = socket.create_connection(("127.0.0.1", port), timeout=20)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s, s.makefile("rb")


def run(port, seq):
    s, f = conn(port)
    out = []
    for cmd in seq:
        s.sendall(enc(cmd))
        out.append(read_reply(f))
    s.close()
    return out


def cell(seeded, size, in_multi, tag):
    key = "lk:%s" % tag
    val = "value-" + "y" * (size - 6)
    seq = [["DEL", key]]
    if seeded:
        seq.append(["RPUSH", key, "seed"])
    if in_multi:
        seq += [["MULTI"], ["RPUSH", key, val], ["EXEC"]]
    else:
        seq.append(["RPUSH", key, val])
    seq += [["LLEN", key], ["LRANGE", key, "0", "-1"]]
    return seq


rows = []
for seeded in (True, False):
    for size in (8, 32, 63, 64, 65, 96, 200):
        for in_multi in (False, True):
            tag = "%s-%d-%s" % ("s" if seeded else "e", size, "m" if in_multi else "b")
            rows.append((seeded, size, in_multi, tag))

fails = 0
print("%-8s %-6s %-5s %-6s | %-8s %-8s | %-8s %-8s" %
      ("seeded", "size", "multi", "want", "t.llen", "t.nelem", "o.llen", "o.nelem"))
for seeded, size, in_multi, tag in rows:
    seq = cell(seeded, size, in_multi, tag)
    tr = run(TP, seq)
    tllen = tr[-2].strip().decode()
    tn = tr[-1].split(b"\r\n")[0].decode()
    if OP:
        orr = run(OP, seq)
        ollen = orr[-2].strip().decode()
        on = orr[-1].split(b"\r\n")[0].decode()
        bad = (tr[-1] != orr[-1]) or (tr[-2] != orr[-2])
    else:
        ollen, on = "-", "-"
        bad = False
    want = (1 if seeded else 0) + 1
    if str(want) != tllen.lstrip(":"):
        bad = True
    fails += bool(bad)
    print("%-8s %-6d %-5s %-6d | %-8s %-8s | %-8s %-8s %s" %
          (seeded, size, in_multi, want, tllen, tn, ollen, on, "  <== DIFF" if bad else ""))

print("\n%d/%d cells wrong" % (fails, len(rows)))
sys.exit(1 if fails else 0)
