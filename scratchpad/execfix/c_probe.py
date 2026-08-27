#!/usr/bin/env python3
"""Explore the 9-op minimal defect-(c) shape: which ingredient is load-bearing?

Usage: c_probe.py TARGET_PORT ORACLE_PORT [--nopipe]
"""
import socket
import sys

TP, OP = int(sys.argv[1]), int(sys.argv[2])
PIPE = "--nopipe" not in sys.argv


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
    s = socket.create_connection(("127.0.0.1", port), timeout=30)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s, s.makefile("rb")


ts, tf = conn(TP)
os_, of = conn(OP)


def run(seq, probe_keys):
    res = []
    for s, f in ((ts, tf), (os_, of)):
        s.sendall(enc(["FLUSHALL"])); read_reply(f)
        replies = []
        if PIPE:
            s.sendall(b"".join(enc(o) for o in seq))
            replies = [read_reply(f) for _ in seq]
        else:
            for o in seq:
                s.sendall(enc(o)); replies.append(read_reply(f))
        s.sendall(b"".join(enc(["LRANGE", k, "0", "-1"]) for k in probe_keys))
        res.append((replies, [read_reply(f) for _ in probe_keys]))
    return res


A, B, C = "lz:A", "lz:B", "lz:C"

CASES = {
    "minimal-9":        [["MULTI"], ["EXEC"],
                         ["MULTI"], ["RPUSH", B, "v"], ["RPUSH", A, "v"], ["EXEC"],
                         ["MULTI"], ["RPUSH", A, "x"], ["EXEC"]],
    "no-empty-tx":      [["MULTI"], ["RPUSH", B, "v"], ["RPUSH", A, "v"], ["EXEC"],
                         ["MULTI"], ["RPUSH", A, "x"], ["EXEC"]],
    "single-key-tx1":   [["MULTI"], ["RPUSH", A, "v"], ["EXEC"],
                         ["MULTI"], ["RPUSH", A, "x"], ["EXEC"]],
    "bare-then-tx":     [["RPUSH", A, "v"],
                         ["MULTI"], ["RPUSH", A, "x"], ["EXEC"]],
    "tx1-then-bare":    [["MULTI"], ["RPUSH", B, "v"], ["RPUSH", A, "v"], ["EXEC"],
                         ["RPUSH", A, "x"]],
    "same-tx-2keys":    [["MULTI"], ["RPUSH", B, "v"], ["RPUSH", A, "v"], ["RPUSH", A, "x"],
                         ["EXEC"]],
    "3tx-chain":        [["MULTI"], ["RPUSH", B, "v"], ["RPUSH", A, "v"], ["EXEC"],
                         ["MULTI"], ["RPUSH", A, "x"], ["EXEC"],
                         ["MULTI"], ["RPUSH", A, "y"], ["EXEC"]],
    "order-swapped":    [["MULTI"], ["RPUSH", A, "v"], ["RPUSH", B, "v"], ["EXEC"],
                         ["MULTI"], ["RPUSH", A, "x"], ["EXEC"]],
    "strings-2keys":    [["MULTI"], ["SET", B, "v"], ["SET", A, "v"], ["EXEC"],
                         ["MULTI"], ["APPEND", A, "x"], ["EXEC"]],
    "sets-2keys":       [["MULTI"], ["SADD", B, "v"], ["SADD", A, "v"], ["EXEC"],
                         ["MULTI"], ["SADD", A, "x"], ["EXEC"]],
    "hash-2keys":       [["MULTI"], ["HSET", B, "f", "v"], ["HSET", A, "f", "v"], ["EXEC"],
                         ["MULTI"], ["HSET", A, "g", "x"], ["EXEC"]],
    "zset-2keys":       [["MULTI"], ["ZADD", B, "1", "v"], ["ZADD", A, "1", "v"], ["EXEC"],
                         ["MULTI"], ["ZADD", A, "2", "x"], ["EXEC"]],
}

PROBE = {"strings-2keys": ["GET"], "sets-2keys": ["SMEMBERS"], "hash-2keys": ["HGETALL"],
         "zset-2keys": ["ZRANGE"]}

fails = 0
for name, seq in CASES.items():
    kind = PROBE.get(name)
    keys = [A, B]
    if kind:
        # rewrite the probe to the right reader
        res = []
        for s, f in ((ts, tf), (os_, of)):
            s.sendall(enc(["FLUSHALL"])); read_reply(f)
            if PIPE:
                s.sendall(b"".join(enc(o) for o in seq))
                replies = [read_reply(f) for _ in seq]
            else:
                replies = []
                for o in seq:
                    s.sendall(enc(o)); replies.append(read_reply(f))
            probe = []
            for k in keys:
                if kind[0] == "ZRANGE":
                    s.sendall(enc(["ZRANGE", k, "0", "-1"]))
                elif kind[0] in ("SMEMBERS", "HGETALL", "GET"):
                    s.sendall(enc([kind[0], k]))
                probe.append(read_reply(f))
            res.append((replies, probe))
    else:
        res = run(seq, keys)
    (tr, tp), (orr, op_) = res
    bad = tr != orr or tp != op_
    fails += bool(bad)
    print("%-18s %s" % (name, "DIFF" if bad else "ok"))
    if bad:
        for i, k in enumerate(keys):
            if tp[i] != op_[i]:
                print("     key %s  target=%r" % (k, tp[i][:120]))
                print("     key %s  oracle=%r" % (k, op_[i][:120]))
        if tr != orr:
            for i in range(len(tr)):
                if tr[i] != orr[i]:
                    print("     reply %d %r  t=%r o=%r" % (i, seq[i][:3], tr[i][:80], orr[i][:80]))

print("\n%d/%d cases diverge (pipelined=%s)" % (fails, len(CASES), PIPE))
sys.exit(1 if fails else 0)
