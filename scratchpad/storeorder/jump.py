#!/usr/bin/env python3
"""jump.py -- directed reproducer for the queue-jump.

Claim: a two-hop store's PHASE 2 task is posted to the destination's owner by the EX thread that
finished phase 1, while the connection's ordinary ops reach that same owner through the IO
thread's queue.  Those are different inboxes, so the owner has no order between them and a
YOUNGER install can overtake OLDER same-connection ops on the destination.

The shape below makes the older ops wait: between the read under test and the next store we put a
long run of plain ops that all land on the DESTINATION's owner, so the read is still deep in that
owner's IO-side queue when phase 2 arrives from the EX side.

  ZADD  src 1 m1
  ZRANGESTORE dst src 0 -1      -> :1      (barriered; fully retires)
  ZCARD dst                     -> must be :1        <-- the read under test
  EXISTS dst  x BACKLOG                               <-- keeps the owner busy, IO-side
  ZADD  src 2 m2                                      (src's owner, elsewhere)
  ZRANGESTORE dst src 0 -1      -> :2                 (phase 2 posted EX-side)

usage: jump.py <host> <port> [rounds] [backlog] [pairs]
"""
import socket, sys, threading, time

HOST, PORT = sys.argv[1], int(sys.argv[2])
ROUNDS = int(sys.argv[3]) if len(sys.argv) > 3 else 20
BACKLOG = int(sys.argv[4]) if len(sys.argv) > 4 else 60
PAIRS = int(sys.argv[5]) if len(sys.argv) > 5 else 40


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


def conn():
    s = socket.create_connection((HOST, PORT), timeout=60)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s, s.makefile("rb")


def shard(s, f, k):
    s.sendall(enc(["DEBUG", "SHARD", k])); r = read_reply(f)
    return int(r[1:-2]) if r[:1] == b":" else None


s, f = conn()
s.sendall(enc(["FLUSHALL"])); read_reply(f)
# choose a src/dst pair that lives on DIFFERENT shards on this boot
cand = ["j%d" % i for i in range(200)]
place = {}
for k in cand:
    place[k] = shard(s, f, k)
by = {}
for k, v in place.items(): by.setdefault(v, []).append(k)
order = sorted(by)
if len(order) < 2: raise SystemExit("single shard boot")

# LOAD: keep the destination's owner busy so the connection's older plain tasks are still sitting
# in the IO producer's channel when phase 2 lands in the EX producer's channel.
STOP = threading.Event()


def loader():
    try:
        ls, lf = conn()
        keys = ["ld%d" % i for i in range(4000)]
        i = 0
        while not STOP.is_set():
            chunk = [["SET", keys[(i + j) % len(keys)], "v"] for j in range(256)]
            ls.sendall(b"".join(enc(c) for c in chunk))
            for _ in chunk: read_reply(lf)
            i += 256
    except Exception:
        pass


LOADERS = int(sys.argv[6]) if len(sys.argv) > 6 else 0
threads = [threading.Thread(target=loader, daemon=True) for _ in range(LOADERS)]
for t in threads: t.start()
if LOADERS: time.sleep(0.3)

bad = 0
total = 0
examples = []
for r in range(ROUNDS):
    # THREE distinct owners: two phase-1 source fragments and a destination.  Every violation seen
    # in the wild was a TWO-SOURCE store, which is the shape whose phase 1 finishes on whichever
    # source owner is last and posts phase 2 from THERE.
    dst = by[order[r % len(order)]][0]
    src = by[order[(r + 1) % len(order)]][0]
    src2 = by[order[(r + 2) % len(order)]][0]
    stream = []
    for k in (dst, src, src2):
        s.sendall(enc(["DEL", k])); read_reply(f)
    for n in range(1, PAIRS + 1):
        stream.append((["ZADD", src, str(n), "m%d" % n], "pre"))
        stream.append((["ZDIFFSTORE", dst, "2", src, src2], "store"))
        stream.append((["ZCARD", dst], "read"))
        stream.append((["ZRANGE", dst, "0", "-1"], "noise"))
        stream.append((["OBJECT", "ENCODING", dst], "noise"))
        for _ in range(BACKLOG):
            stream.append((["EXISTS", dst], "noise"))
    s.sendall(b"".join(enc(a) for a, _ in stream))
    replies = [read_reply(f) for _ in stream]
    last = None
    for i, (argv, role) in enumerate(stream):
        if role == "store": last = replies[i]
        elif role == "read":
            total += 1
            if replies[i] != last:
                bad += 1
                if len(examples) < 6:
                    examples.append("  round %d op %d store=%r read=%r" %
                                    (r, i, last.strip(), replies[i].strip()))
STOP.set()
for e in examples: print(e)
print("JUMP port=%d rounds=%d backlog=%d pairs=%d loaders=%d -> %d/%d reads saw a YOUNGER store "
      "(%.2f%%)" % (PORT, ROUNDS, BACKLOG, PAIRS, LOADERS, bad, total,
                    100.0 * bad / max(total, 1)))
sys.exit(1 if bad else 0)
