#!/usr/bin/env python3
"""Discriminating probe for xshard lookup accounting. See xshard_lookup_accounting.sh header.

Reads each key's LFU counter out of the RDB (RDB_OPCODE_FREQ, 0xF9) because OBJECT FREQ answers
nil for sharded keys. With --lfu-log-factor 0 / --lfu-decay-time 0 the counter is an EXACT
per-lookup access count, so "one logical read == one counter increment" is an integer assertion.
"""
import socket, sys, time

out_path, port, rdb_path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
res = []
def rec(name, ok, detail=""):
    res.append((name, "PASS" if ok else "FAIL", detail))

s = socket.create_connection(("127.0.0.1", port)); s.settimeout(30)
buf = b""

def enc(*a):
    o = ("*%d\r\n" % len(a)).encode()
    for x in a:
        b = x if isinstance(x, bytes) else str(x).encode()
        o += b"$%d\r\n%s\r\n" % (len(b), b)
    return o

def readreply():
    """Minimal RESP reader (one reply)."""
    global buf
    def need(n):
        global buf
        while len(buf) < n:
            c = s.recv(1 << 20)
            if not c: raise RuntimeError("eof")
            buf += c
    def line():
        global buf
        while b"\r\n" not in buf:
            c = s.recv(1 << 20)
            if not c: raise RuntimeError("eof")
            buf += c
        i = buf.index(b"\r\n"); ln = buf[:i]; buf = buf[i+2:]
        return ln
    ln = line(); t = ln[:1]
    if t in b"+-:": return ln[1:]
    if t == b"$":
        n = int(ln[1:])
        if n == -1: return None
        need(n+2); v = buf[:n]; buf = buf[n+2:]; return v
    if t == b"*":
        n = int(ln[1:])
        if n == -1: return None
        return [readreply() for _ in range(n)]
    raise RuntimeError("bad reply %r" % ln)

def cmd(*a):
    s.sendall(enc(*a)); return readreply()

def info_int(field):
    d = cmd("INFO", "stats")
    for ln in d.split(b"\r\n"):
        if ln.startswith(field.encode() + b":"):
            return int(ln.split(b":")[1])
    return None

def lfu_of(keys):
    """SAVE, then read RDB_OPCODE_FREQ for each key. Layout per key:
       0xF9 <freq:1> <type:1> <keylen:1> <keybytes>  (keylen < 64 => 1 byte, 6-bit len)."""
    cmd("SAVE")
    raw = open(rdb_path, "rb").read()
    got = {}
    for k in keys:
        kb = k.encode()
        pat = bytes([len(kb)]) + kb
        i = raw.find(pat)
        while i > 3:
            if raw[i-3] == 0xF9:
                got[k] = raw[i-2]; break
            i = raw.find(pat, i+1)
        else:
            got[k] = None
    return got

# ---------------------------------------------------------------- set up a CROSS-SHARD key set
# The routing oracle is tomokv_xshard_multikey_split: dispatchGather bumps it exactly when a
# read-only multi-key command's keys span MORE THAN ONE owner worker (i.e. it could not take the
# single-owner localfast arm). A key set that does not raise it is same-shard and would test the
# WRONG route, so search until the counter proves the split.
K = 4
cross_keys = None
for attempt in range(60):
    keys = ["xs%d:%d" % (attempt, i) for i in range(K)]
    for k in keys:
        cmd("DEL", k)
        cmd("SADD", k, "common", "u_" + k)
    before = info_int("tomokv_xshard_multikey_split")
    r = cmd("SINTER", *keys)
    after = info_int("tomokv_xshard_multikey_split")
    if after > before and r == [b"common"]:
        cross_keys = keys; break
    for k in keys: cmd("DEL", k)
rec("cross-shard-key-set-found", cross_keys is not None,
    "keys=%s" % (cross_keys,))
if cross_keys is None:
    open(out_path, "w").write("".join("%s\t%s\t%s\n" % r for r in res)); raise SystemExit(1)

# Same-shard control set (localfast route: multikey_split must NOT rise). With 16 owners, a random
# four-key set lands together with probability 1/16^3 = 1/4096; the old 200-quartet search therefore
# succeeded only ~4.8% of the time. Hold one anchor and admit candidates whose two-key SINTER proves
# the same owner. Each draw now succeeds with probability 1/16, while the route oracle remains the
# authority (no duplicated hash/owner implementation in the harness).
anchor = "ss:anchor"
cmd("DEL", anchor)
cmd("SADD", anchor, "common", "u_" + anchor)
same_keys = [anchor]
for attempt in range(400):
    candidate = "ss:candidate:%d" % attempt
    cmd("DEL", candidate)
    cmd("SADD", candidate, "common", "u_" + candidate)
    before = info_int("tomokv_xshard_multikey_split")
    r = cmd("SINTER", anchor, candidate)
    after = info_int("tomokv_xshard_multikey_split")
    if after == before and r == [b"common"]:
        same_keys.append(candidate)
        if len(same_keys) == K:
            break
    else:
        cmd("DEL", candidate)
if len(same_keys) != K:
    for k in same_keys:
        cmd("DEL", k)
    same_keys = None
rec("same-shard-control-key-set-found", same_keys is not None, "keys=%s" % (same_keys,))

M = 20

def run_arm(keys, label):
    base = lfu_of(keys)
    if any(v is None for v in base.values()):
        return None, "no RDB freq byte for %s" % [k for k, v in base.items() if v is None]
    h0 = info_int("keyspace_hits")
    split0 = info_int("tomokv_xshard_multikey_split")
    for _ in range(M):
        r = cmd("SINTER", *keys)
        if r != [b"common"]:
            return None, "wrong SINTER result %r" % (r,)
    h1 = info_int("keyspace_hits")
    split1 = info_int("tomokv_xshard_multikey_split")
    end = lfu_of(keys)
    delta = {k: end[k] - base[k] for k in keys}
    return (delta, h1 - h0, split1 - split0), ""

# ------------------------------------------------------------------------------ CONTROL: SCARD
# Single-key reads: one lookup per command, no pipeline. Calibrates the probe itself — if this
# arm is not exactly 1/command the counter is not an access counter and nothing else means anything.
ck = cross_keys[0]
b0 = lfu_of([ck])[ck]
for _ in range(M): cmd("SCARD", ck)
b1 = lfu_of([ck])[ck]
rec("control-single-key-scard-1-touch-per-cmd", (b1 - b0) == M, "delta=%d expected=%d" % (b1 - b0, M))

# ---------------------------------------------------------------- CONTROL: same-shard localfast
if same_keys:
    r, err = run_arm(same_keys, "localfast")
    if r is None:
        rec("control-localfast-sinter-1-touch-per-key-per-cmd", False, err)
    else:
        delta, dh, dsplit = r
        ok = all(v == M for v in delta.values())
        rec("control-localfast-sinter-1-touch-per-key-per-cmd", ok,
            "delta=%s expected=%d each; keyspace_hits=%d expected=%d" % (delta, M, dh, M * K))

# ------------------------------------------------------------- THE TEST: cross-shard pipeline
r, err = run_arm(cross_keys, "pipeline")
if r is None:
    rec("pipeline-sinter-1-touch-per-key-per-cmd", False, err)
    rec("pipeline-sinter-keyspace-hits-once-per-key", False, err)
    rec("pipeline-route-was-exercised", False, err)
else:
    delta, dh, dsplit = r
    rec("pipeline-route-was-exercised", dsplit == M,
        "multikey_split delta=%d expected=%d" % (dsplit, M))
    ok = all(v == M for v in delta.values())
    rec("pipeline-sinter-1-touch-per-key-per-cmd", ok,
        "LFU delta=%s expected=%d each" % (delta, M))
    rec("pipeline-sinter-keyspace-hits-once-per-key", dh == M * K,
        "keyspace_hits delta=%d expected=%d" % (dh, M * K))

open(out_path, "w").write("".join("%s\t%s\t%s\n" % r for r in res))
sys.exit(0 if all(x[1] == "PASS" for x in res) else 1)
