#!/usr/bin/env python3
# READ-YOUR-OWN-WRITES gate. The contract: on ONE connection, a GET that follows a SET (in send
# order) observes that SET or a later one -- at any pipeline depth, across shard boundaries, with
# other connections hammering the same keys. The ROB's in-order retirement is what makes this true;
# this test exists because the fork once broke exactly this with reorder machinery (reorder-RYOW).
import socket, sys, threading, os

HOST, PORT = sys.argv[1], int(sys.argv[2])
FAIL = 0
def note(name, ok, extra=""):
    global FAIL
    print(("  ok   " if ok else "  FAIL ") + name + (" " + extra if extra else ""), flush=True)
    if not ok: FAIL += 1

def conn():
    s = socket.create_connection((HOST, PORT), timeout=30)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s
def cmd(*args):
    out = b"*%d\r\n" % len(args)
    for a in args:
        if isinstance(a, str): a = a.encode()
        out += b"$%d\r\n" % len(a) + a + b"\r\n"
    return out
def read_reply(f):
    line = f.readline()
    if not line: raise EOFError
    t = line[:1]
    if t in b"+-:": return line[1:-2]
    if t == b"$":
        n = int(line[1:-2])
        if n == -1: return None
        return f.read(n + 2)[:-2]
    raise ValueError(repr(line[:20]))

# ---- 1. deep-pipelined SET/GET alternation on one key ----
s = conn(); f = s.makefile("rb")
N = 5000
burst = b"".join(cmd("SET", "ryow", "v%d" % i) + cmd("GET", "ryow") for i in range(N))
s.sendall(burst)
ok = True
for i in range(N):
    if read_reply(f) != b"OK": ok = False; break
    if read_reply(f) != b"v%d" % i: ok = False; break
name = "pipelined SET/GET x%d one key" % N
note(name, ok)

# ---- 2. cross-shard interleave: many keys (spread over shards), strict per-key freshness ----
K = 64
burst = b""
for r in range(200):
    for k in range(K):
        burst += cmd("SET", "rk%d" % k, "r%d.%d" % (r, k)) + cmd("GET", "rk%d" % k)
s.sendall(burst)
ok = True
for r in range(200):
    for k in range(K):
        if read_reply(f) != b"OK": ok = False
        if read_reply(f) != b"r%d.%d" % (r, k): ok = False
note("cross-shard interleave 200 rounds x %d keys" % K, ok)

# ---- 3. Exact RYOW under independently acknowledged background write pressure ----
stop = threading.Event()
noise_errors = []
noise_ready = [threading.Event() for _ in range(4)]
noise_ops = [0] * 4
def hammer(wid):
    h = hf = None
    try:
        h = conn(); hf = h.makefile("rb")
        i = 0
        while not stop.is_set():
            h.sendall(cmd("SET", "rk%d" % (i % K), "noise%d" % i))
            assert read_reply(hf) == b"OK", "background SET did not acknowledge"
            i += 1
            noise_ops[wid] = i
            noise_ready[wid].set()
    except Exception as error:
        noise_errors.append(repr(error))
    finally:
        if hf is not None: hf.close()
        if h is not None: h.close()
threads = [threading.Thread(target=hammer, args=(wid,), daemon=True) for wid in range(4)]
for t in threads: t.start()
for ready in noise_ready:
    assert ready.wait(5), "background writer never acknowledged progress"
ok = True
for r in range(2000):
    k = "own%d" % (r % 8)
    v = b"mine%d" % r
    s.sendall(cmd("SET", k, v) + cmd("GET", k))
    if read_reply(f) != b"OK": ok = False
    if read_reply(f) != v: ok = False
note("RYOW under 4-writer pressure x2000", ok)
stop.set()
for t in threads: t.join(timeout=3)
note("all background writers acknowledged and stopped",
     all(noise_ops) and not noise_errors and not any(t.is_alive() for t in threads),
     "ops=%r errors=%r" % (noise_ops, noise_errors))

# Explicit SAME-KEY conflicts. A read may return this connection's acknowledged
# write or one of the four concurrent overwrites, never an unrelated/older value.
# Once all four writes acknowledge, the next unconflicted SET/GET must be exact.
peers = [conn() for _ in range(4)]
files = [peer.makefile("rb") for peer in peers]
conflicts_ok = True
conflict_epoch = os.urandom(8).hex()
try:
    for round_id in range(64):
        key = "ryow:conflict:%s:%d" % (conflict_epoch, round_id)
        mine = ("mine:%d" % round_id).encode()
        s.sendall(cmd("SET", key, mine))
        assert read_reply(f) == b"OK"
        noise = [("other:%d:%d" % (round_id, wid)).encode() for wid in range(4)]
        for peer, value in zip(peers, noise):
            peer.sendall(cmd("SET", key, value))
        s.sendall(cmd("GET", key))
        got = read_reply(f)
        conflicts_ok &= got in [mine] + noise
        for file in files:
            conflicts_ok &= read_reply(file) == b"OK"
        settled = ("settled:%d" % round_id).encode()
        s.sendall(cmd("SET", key, settled) + cmd("GET", key))
        conflicts_ok &= read_reply(f) == b"OK"
        conflicts_ok &= read_reply(f) == settled
    note("same-key overwrite replies + unconflicted RYOW x64", conflicts_ok)
finally:
    for file in files: file.close()
    for peer in peers: peer.close()

# ---- 4. DEL visibility: SET;DEL;GET pipelined must see nil; SET;GET;DEL;GET mixed ----
burst = b""
for i in range(1000):
    burst += cmd("SET", "dk", "x") + cmd("DEL", "dk") + cmd("GET", "dk") \
           + cmd("SET", "dk", "y%d" % i) + cmd("GET", "dk")
s.sendall(burst)
ok = True
for i in range(1000):
    if read_reply(f) != b"OK": ok = False
    if read_reply(f) != b"1": ok = False
    if read_reply(f) is not None: ok = False
    if read_reply(f) != b"OK": ok = False
    if read_reply(f) != b"y%d" % i: ok = False
note("DEL visibility x1000", ok)
s.close()

print("RYOW " + ("PASS" if FAIL == 0 else "FAIL %d" % FAIL), flush=True)
sys.exit(1 if FAIL else 0)
