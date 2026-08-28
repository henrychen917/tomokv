#!/usr/bin/env python3
"""liveness.py -- the new dispatch hold must never wedge a connection.

The fix makes a barriered scatter wait for the ROB head. A hold that is never released is the
failure mode to rule out, so this drives the shapes that can create one: deep pipelines that mix
plain ops with two-hop stores, multi-key groups, MULTI/EXEC, blocking pops and whole-owner
commands (KEYS/FLUSHALL are barriered too), across many connections at once, and it checks both
that every connection finished and that a FRESH connection is still served afterwards.

usage: liveness.py <host> <port> <conns> [rounds] [--watch]
"""
import socket, sys, threading, time, random

HOST, PORT = sys.argv[1], int(sys.argv[2])
CONNS = int(sys.argv[3]) if len(sys.argv) > 3 else 8
ROUNDS = int(sys.argv[4]) if len(sys.argv) > 4 else 6
WATCH = "--watch" in sys.argv


def enc(a):
    o = b"*%d\r\n" % len(a)
    for x in a:
        if isinstance(x, str): x = x.encode()
        o += b"$%d\r\n" % len(x) + x + b"\r\n"
    return o


def read_reply(f):
    line = f.readline()
    if not line: raise EOFError
    t = line[:1]
    if t in b"+-:,#(_": return line
    if t in b"$=":
        n = int(line[1:-2]); return line if n == -1 else line + f.read(n + 2)
    if t in b"*%~>":
        n = int(line[1:-2])
        if n == -1: return line
        if t == b"%": n *= 2
        return line + b"".join(read_reply(f) for _ in range(n))
    raise RuntimeError(line)


done = [0] * CONNS
errs = []


def worker(idx):
    rng = random.Random(idx * 7 + 1)
    try:
        s = socket.create_connection((HOST, PORT), timeout=45)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        f = s.makefile("rb")
        keys = ["lv:%d:%d" % (idx, i) for i in range(24)]
        for r in range(ROUNDS):
            ops = []
            for k in keys[:8]:
                ops.append(["ZADD", k, "1", "a", "2", "b"])
                ops.append(["SADD", k + ":s", "a", "b"])
                ops.append(["RPUSH", k + ":l", "1", "2"])
                ops.append(["SET", k + ":v", "xy"])
            for _ in range(120):
                c = rng.randrange(12)
                d = rng.choice(keys) + ":d"
                if c == 0: ops.append(["GET", rng.choice(keys) + ":v"])
                elif c == 1: ops.append(["ZRANGESTORE", d, rng.choice(keys[:8]), "0", "-1"])
                elif c == 2: ops.append(["ZUNIONSTORE", d, "2", keys[0], keys[1]])
                elif c == 3: ops.append(["SUNIONSTORE", d, keys[2] + ":s", keys[3] + ":s"])
                elif c == 4: ops.append(["SORT", keys[4] + ":l", "STORE", d])
                elif c == 5: ops.append(["DEL", d, rng.choice(keys) + ":gone"])
                elif c == 6: ops += [["MULTI"], ["SET", rng.choice(keys) + ":v", "z"],
                                     ["DEL", keys[5], keys[6]], ["EXEC"]]
                elif c == 7: ops.append(["MGET", keys[0] + ":v", keys[1] + ":v"])
                elif c == 8: ops.append(["COPY", keys[0], d, "REPLACE"])
                elif c == 9: ops += [["RPUSH", keys[7] + ":bl", "v"],
                                     ["BLPOP", keys[7] + ":bl", "0.05"]]
                elif c == 10 and WATCH: ops += [["WATCH", keys[0]], ["MULTI"],
                                               ["SET", keys[0] + ":v", "w"], ["EXEC"]]
                else: ops.append(["EXISTS", d])
            ops.append(["PING"])
            s.sendall(b"".join(enc(o) for o in ops))
            for _ in ops: read_reply(f)
            done[idx] += 1
        s.close()
    except Exception as e:
        errs.append("conn %d: %r" % (idx, e))


t0 = time.time()
threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(CONNS)]
for t in threads: t.start()
for t in threads: t.join(timeout=180)
elapsed = time.time() - t0
alive = sum(1 for t in threads if t.is_alive())
# A fresh connection must still be served: a wedged executor shows up here even when the
# pipelined connections are merely slow.
fresh = "unreachable"
try:
    s = socket.create_connection((HOST, PORT), timeout=10)
    f = s.makefile("rb")
    s.sendall(enc(["PING"])); fresh = read_reply(f).strip().decode()
    s.sendall(enc(["ZRANGESTORE", "lv:fresh:d", "lv:0:0", "0", "-1"]))
    fresh += " " + read_reply(f).strip().decode()
    s.close()
except Exception as e:
    fresh = repr(e)
ok = alive == 0 and not errs and sum(done) == CONNS * ROUNDS and fresh.startswith("+PONG")
print("LIVENESS conns=%d rounds=%d watch=%s -> %s  (%d/%d rounds done, %d stuck, %.1fs, "
      "fresh=%s)%s" % (CONNS, ROUNDS, WATCH, "PASS" if ok else "FAIL", sum(done),
                       CONNS * ROUNDS, alive, elapsed, fresh,
                       "" if not errs else " errs=" + "; ".join(errs[:3])))
sys.exit(0 if ok else 1)
