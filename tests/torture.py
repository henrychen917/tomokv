#!/usr/bin/env python3
# Perfected-checkpoint torture battery: size walls, depth walls, slot overflow, fuzz, churn.
import socket, sys, time, os, random

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
def read_reply(s, f):
    line = f.readline()
    if not line: raise EOFError("closed")
    t = line[:1]
    if t in b"+-:": return line[1:-2]
    if t == b"$":
        n = int(line[1:-2])
        if n == -1: return None
        d = f.read(n + 2)
        return d[:-2]
    raise ValueError("unexpected " + repr(line[:20]))

# ---- 1. value-size ladder (the 1MB-wall fix) ----
s = conn(); f = s.makefile("rb")
for sz in [64, 4096, 65536, 512*1024, 1024*1024, 2*1024*1024, 8*1024*1024, 64*1024*1024]:
    val = os.urandom(sz)
    t0 = time.time()
    s.sendall(cmd("SET", "bigv", val)); r1 = read_reply(s, f)
    s.sendall(cmd("GET", "bigv"));      r2 = read_reply(s, f)
    s.sendall(cmd("DEL", "bigv"));      r3 = read_reply(s, f)
    s.sendall(cmd("GET", "bigv"));      r4 = read_reply(s, f)
    note("value %dKB roundtrip" % (sz//1024), r1 == b"OK" and r2 == val and r3 == b"1" and r4 is None,
         "%.2fs" % (time.time()-t0))
# ---- 2. key-size ladder ----
for ksz in [16, 1024, 16*1024, 512*1024]:
    key = b"k" * ksz
    s.sendall(cmd("SET", key, b"v1")); r1 = read_reply(s, f)
    s.sendall(cmd("GET", key));        r2 = read_reply(s, f)
    s.sendall(cmd("DEL", key));        r3 = read_reply(s, f)
    note("key %dB roundtrip" % ksz, r1 == b"OK" and r2 == b"v1" and r3 == b"1")
s.close()

# ---- 3. pipe depth > ROB window (64): 300-deep pipelined burst, in-order replies ----
s = conn(); f = s.makefile("rb")
N = 300
burst = b"".join(cmd("SET", "p%d" % i, "val%d" % i) for i in range(N))
s.sendall(burst)
ok = all(read_reply(s, f) == b"OK" for _ in range(N))
burst = b"".join(cmd("GET", "p%d" % i) for i in range(N))
s.sendall(burst)
ok = ok and all(read_reply(s, f) == b"val%d" % i for i in range(N))
burst = b"".join(cmd("DEL", "p%d" % i) for i in range(N))
s.sendall(burst)
ok = ok and all(read_reply(s, f) == b"1" for i in range(N))
note("pipe depth 300 (window=64) in order", ok)
s.close()

# ---- 4. split-frame torture: one SET delivered byte-by-byte, interleaved timing ----
s = conn(); f = s.makefile("rb")
payload = cmd("SET", "split", "splitval")
for i in range(0, len(payload), 3):
    s.sendall(payload[i:i+3]); time.sleep(0.001)
note("split-frame SET", read_reply(s, f) == b"OK")
s.sendall(cmd("GET", "split")); note("split-frame GET", read_reply(s, f) == b"splitval")
s.close()

# ---- 5. fuzz-lite: garbage must not kill the SERVER (conns may die) ----
random.seed(7)
frames = [b"\x00\xff\xfe garbage\r\n", b"*99999999999999\r\n", b"*2\r\n$-5\r\nX\r\n",
          b"*1\r\n$999999999999999\r\n", b"$5\r\nhello\r\n", b"*3\r\n$3\r\nSET\r\n",
          b"PING\r\n", b"\r\n\r\n\r\n", b"*2\r\n$3\r\nGET\r\n$0\r\n\r\n",
          bytes(random.getrandbits(8) for _ in range(4096))]
for i, fr in enumerate(frames):
    try:
        x = conn(); x.sendall(fr)
        x.settimeout(2)
        try: x.recv(4096)
        except Exception: pass
        x.close()
    except Exception: pass
try:
    s = conn(); f = s.makefile("rb")
    s.sendall(cmd("PING"))
    note("server alive after fuzz", read_reply(s, f) == b"PONG")
    s.close()
except Exception as e:
    note("server alive after fuzz", False, str(e))

# ---- 6. churn: 300 abrupt disconnects mid-command ----
for i in range(300):
    try:
        x = conn()
        x.sendall(cmd("SET", "churn%d" % i, "x" * 100))
        if i % 3 == 0: x.sendall(b"*3\r\n$3\r\nSET\r\n$4\r\nhalf")   # die mid-frame
        x.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")  # RST
        x.close()
    except Exception: pass
time.sleep(1)
try:
    s = conn(); f = s.makefile("rb")
    s.sendall(cmd("PING")); note("server alive after churn", read_reply(s, f) == b"PONG")
    landed = 0
    for i in range(300):
        s.sendall(cmd("GET", "churn%d" % i))
        landed += read_reply(s, f) == b"x" * 100
    note("churn writes landed", landed > 0, "(%d/300)" % landed)
    s.close()
except Exception as e:
    note("server alive after churn", False, str(e))

print("TORTURE " + ("PASS" if FAIL == 0 else "FAIL %d" % FAIL), flush=True)
sys.exit(1 if FAIL else 0)
