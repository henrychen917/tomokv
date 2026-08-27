#!/usr/bin/env python3
"""Defect (c): which preamble makes the 7-op shape lose the write?

Usage: c_var.py TARGET_PORT
"""
import socket
import sys

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


def fresh():
    s = socket.create_connection(("127.0.0.1", TP), timeout=30)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s, s.makefile("rb")


def trial(keya, keyb, preamble, label):
    s, f = fresh()

    def cmd(*argv):
        s.sendall(enc(list(argv)))
        return read_reply(f)

    for c in preamble:
        cmd(*c)
    cmd("MULTI"); cmd("RPUSH", keyb, "v"); cmd("RPUSH", keya, "v")
    e1 = cmd("EXEC")
    cmd("MULTI"); cmd("RPUSH", keya, "x")
    e2 = cmd("EXEC")
    got = cmd("LRANGE", keya, "0", "-1")
    sa = cmd("DEBUG", "SHARD", keya).strip().decode()
    sb = cmd("DEBUG", "SHARD", keyb).strip().decode()
    s.close()
    bad = b"$1\r\nx" not in got
    print("%-34s a=%-10s b=%-10s sh %s/%s exec1=%-16r exec2=%-10r %s" %
          (label, keya, keyb, sa, sb, e1[:24], e2[:12], "LOST" if bad else "ok"))
    return bad


F = [["FLUSHALL"]]
lost = 0
lost += trial("lz:A", "lz:B", F, "flushall")
lost += trial("lz:A", "lz:B", [["DEL", "lz:A"], ["DEL", "lz:B"]], "del-only")
lost += trial("lz:A", "lz:B", F + [["PING"]] * 5, "flushall + 5 ping")
lost += trial("lz:A", "lz:B", F + [["DEBUG", "SHARD", "q"]] * 5, "flushall + 5 debug-shard")
lost += trial("lz:A", "lz:B", F + [["SET", "z:%d" % i, "q"] for i in range(20)],
              "flushall + 20 SET")
lost += trial("lz:B", "lz:A", F, "flushall, keys swapped")
print("--- same shapes with sk: keys (shards 0/1) ---")
lost += trial("sk:000", "sk:002", F, "sk pair, flushall")
lost += trial("sk:000", "sk:002", [["DEL", "sk:000"], ["DEL", "sk:002"]], "sk pair, del-only")
print("\n%d cells lost" % lost)
