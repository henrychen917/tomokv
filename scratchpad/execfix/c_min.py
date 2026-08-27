#!/usr/bin/env python3
"""Defect (c) narrowing: which shape actually loses the RPUSH?

Usage: c_min.py TARGET_PORT ORACLE_PORT
"""
import socket
import sys

TP, OP = int(sys.argv[1]), int(sys.argv[2])
BIG = "value-" + "y" * 90


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


PIPELINE = "--pipeline" in sys.argv


def run(port, seq):
    s = socket.create_connection(("127.0.0.1", port), timeout=20)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    f = s.makefile("rb")
    out = []
    if PIPELINE:
        s.sendall(b"".join(enc(c) for c in seq))
        for _ in seq:
            out.append(read_reply(f))
    else:
        for cmd in seq:
            s.sendall(enc(cmd))
            out.append(read_reply(f))
    s.close()
    return out


CASES = {
    # name: (setup, body-inside-MULTI)
    "1push-clean":        ([], [["RPUSH", "K", "a"]]),
    "1push-seeded":       ([["RPUSH", "K", "seed"]], [["RPUSH", "K", "a"]]),
    "2push-same-key":     ([["RPUSH", "K", "seed"]], [["RPUSH", "K", "a"], ["RPUSH", "K", "b"]]),
    "2push-clean":        ([], [["RPUSH", "K", "a"], ["RPUSH", "K", "b"]]),
    "3push-same-key":     ([["RPUSH", "K", "seed"]],
                           [["RPUSH", "K", "a"], ["RPUSH", "K", "b"], ["RPUSH", "K", "c"]]),
    "2push-big":          ([["RPUSH", "K", "seed"]], [["RPUSH", "K", BIG], ["RPUSH", "K", "b"]]),
    "push+lrange":        ([["RPUSH", "K", "seed"]], [["RPUSH", "K", "a"], ["LRANGE", "K", "0", "-1"]]),
    "lrange+push":        ([["RPUSH", "K", "seed"]], [["LRANGE", "K", "0", "-1"], ["RPUSH", "K", "a"]]),
    "lrange+push+lrange": ([["RPUSH", "K", "seed"]],
                           [["LRANGE", "K", "0", "-1"], ["RPUSH", "K", "a"],
                            ["LRANGE", "K", "0", "-1"]]),
    "push-then-bare":     ([["RPUSH", "K", "seed"]], [["RPUSH", "K", "a"]]),
    "2set-same-key":      ([["SET", "S", "seed"]], [["SET", "S", "a"], ["APPEND", "S", "b"]]),
}

fails = 0
for i, (name, (setup, body)) in enumerate(CASES.items()):
    key = "ck:%02d:%s" % (i, name)
    sub = lambda c: [key if a == "K" else (key if a == "S" else a) for a in c]
    seq = [["DEL", key]] + [sub(c) for c in setup] + [["MULTI"]] + [sub(c) for c in body] + \
          [["EXEC"], ["LRANGE", key, "0", "-1"], ["LLEN", key], ["GET", key], ["OBJECT", "ENCODING", key]]
    t = run(TP, seq)
    o = run(OP, seq)
    n = len(seq)
    # compare only the EXEC reply and the trailing observations
    tail_t = t[n - 5:]
    tail_o = o[n - 5:]
    bad = tail_t[:3] != tail_o[:3]
    fails += bool(bad)
    print("%-22s %s" % (name, "DIFF" if bad else "ok"))
    if bad:
        print("    exec   t=%r" % (tail_t[0][:160],))
        print("    exec   o=%r" % (tail_o[0][:160],))
        print("    lrange t=%r" % (tail_t[1][:200],))
        print("    lrange o=%r" % (tail_o[1][:200],))
        print("    llen   t=%r o=%r" % (tail_t[2], tail_o[2]))
    print("    enc    t=%r o=%r" % (tail_t[4], tail_o[4]))

print("\n%d/%d cases diverge" % (fails, len(CASES)))
sys.exit(1 if fails else 0)
