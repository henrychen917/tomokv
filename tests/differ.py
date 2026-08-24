#!/usr/bin/env python3
# DIFFERENTIAL battery: run one deterministic command stream against the TARGET (tomokv-cpp) and
# the ORACLE (the optimized Redis fork -- byte-exact redis semantics) and diff every reply.
#   python3 tests/differ.py <target_host> <target_port> <oracle_host> <oracle_port> <suite> [seed]
# Exit 0 iff zero diffs. Suites: string (more added per type lane).
import socket, sys, random

TH, TP, OH, OP = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
SUITE = sys.argv[5]
SEED = int(sys.argv[6]) if len(sys.argv) > 6 else 7

def conn(h, p):
    s = socket.create_connection((h, p), timeout=30)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s, s.makefile("rb")
def enc(args):
    o = b"*%d\r\n" % len(args)
    for a in args:
        if isinstance(a, str): a = a.encode()
        o += b"$%d\r\n" % len(a) + a + b"\r\n"
    return o
def read_reply(f):
    line = f.readline()
    if not line: raise EOFError
    t = line[:1]
    if t in b"+-:": return line
    if t == b"$":
        n = int(line[1:-2])
        if n == -1: return line
        return line + f.read(n + 2)
    if t == b"*":
        n = int(line[1:-2])
        if n == -1: return line
        return line + b"".join(read_reply(f) for _ in range(n))
    raise ValueError(repr(line[:24]))

def parse_reply(r):
    # decode one serialized reply into a python structure for normalization
    if r[:1] == b"*" and not r.startswith(b"*-1"):
        # split header + elements (only flat arrays of bulks/ints needed here)
        items = []
        rest = r[r.index(b"\r\n")+2:]
        while rest:
            if rest[:1] == b"$":
                if rest.startswith(b"$-1"):
                    items.append(None); rest = rest[rest.index(b"\r\n")+2:]
                else:
                    n = int(rest[1:rest.index(b"\r\n")])
                    body_at = rest.index(b"\r\n")+2
                    items.append(rest[body_at:body_at+n]); rest = rest[body_at+n+2:]
            elif rest[:1] in b":+-":
                items.append(rest[:rest.index(b"\r\n")]); rest = rest[rest.index(b"\r\n")+2:]
            else: return None
        return items
    return None

SORTED_SET_REPLIES = {"SMEMBERS", "SPOPSHAPE", "HKEYS", "HVALS"}

def normalize(cmdname, r):
    if cmdname in SORTED_SET_REPLIES:
        it = parse_reply(r)
        if it is not None:
            return b"SORTED:" + b",".join(sorted(x if x is not None else b"<nil>" for x in it))
    # TTL/PTTL race by wall time between servers: bucket to second granularity.
    if cmdname in ("TTL", "PTTL", "EXPIRETIME", "PEXPIRETIME") and r[:1] == b":":
        try:
            v = int(r[1:-2])
            if v > 0:
                if cmdname in ("PTTL",): v = (v + 999) // 1000
                if cmdname in ("PEXPIRETIME",): v //= 1000
                return b":~%d\r\n" % v
        except ValueError: pass
    return r

def gen_string(rng):
    keys = ["s%d" % i for i in range(24)]
    ops = []
    def K(): return rng.choice(keys)
    vals = ["", "x", "hello world", "12345", "-7", "+1", "007", "-0",
            "9223372036854775807", "-9223372036854775808", "9223372036854775808",
            "3.0e3", "10.5", "a" * 300, "\x00\x01bin\xff"]
    for _ in range(4000):
        c = rng.randrange(20)
        if   c == 0: ops.append(["SET", K(), rng.choice(vals)])
        elif c == 1: ops.append(["GET", K()])
        elif c == 2: ops.append(["APPEND", K(), rng.choice(vals)])
        elif c == 3: ops.append(["STRLEN", K()])
        elif c == 4: ops.append(["GETRANGE", K(), str(rng.randrange(-20, 20)), str(rng.randrange(-20, 20))])
        elif c == 5: ops.append(["SETRANGE", K(), str(rng.randrange(0, 24)), rng.choice(vals[:8])])
        elif c == 6: ops.append(["GETSET", K(), rng.choice(vals)])
        elif c == 7: ops.append(["SETNX", K(), rng.choice(vals)])
        elif c == 8: ops.append(["INCR", K()])
        elif c == 9: ops.append(["DECR", K()])
        elif c == 10: ops.append(["INCRBY", K(), rng.choice(["1", "-3", "100", "9223372036854775807", "notanum"])])
        elif c == 11: ops.append(["DECRBY", K(), rng.choice(["2", "-5", "9223372036854775807", "-9223372036854775808"])])
        elif c == 12: ops.append(["INCRBYFLOAT", K(), rng.choice(["0.1", "-3.5e2", "1e100", "nan", "abc", "5.0e3"])])
        elif c == 13: ops.append(["DEL", K()])
        elif c == 14: ops.append(["EXISTS", K()])
        elif c == 15:
            form = rng.randrange(6)
            if form == 0: ops.append(["SET", K(), rng.choice(vals), "NX"])
            elif form == 1: ops.append(["SET", K(), rng.choice(vals), "XX"])
            elif form == 2: ops.append(["SET", K(), rng.choice(vals), "XX", "GET"])
            elif form == 3: ops.append(["SET", K(), rng.choice(vals), "NX", "GET"])
            elif form == 4: ops.append(["SET", K(), rng.choice(vals), "KEEPTTL"])
            else:          ops.append(["SET", K(), rng.choice(vals), "EX", "1000", "GET"])
        elif c == 16: ops.append(["EXPIRE", K(), rng.choice(["1000", "0", "-5"])])
        elif c == 17: ops.append(["TTL", K()])
        elif c == 18: ops.append(["PERSIST", K()])
        elif c == 19: ops.append(["GETDEL", K()])
    # directed adversarial tail (from NOTES-STRING.md)
    ops += [
        ["SET", "adv", "42"], ["APPEND", "adv", ""], ["OBJECTENCODINGSKIP"],
        ["APPEND", "adv", "9"], ["GET", "adv"],
        ["SET", "adv2", "10"], ["SETRANGE", "adv2", "5", "zz"], ["GET", "adv2"],
        ["SETRANGE", "advnew", "3", "abc"], ["GET", "advnew"], ["STRLEN", "advnew"],
        ["SET", "adv3", "5"], ["INCRBYFLOAT", "adv3", "0.1"], ["GET", "adv3"],
        ["INCRBYFLOAT", "adv3", "-5.1"], ["GET", "adv3"],
        ["SET", "ttlk", "v", "EX", "1000"], ["TTL", "ttlk"], ["APPEND", "ttlk", "w"], ["TTL", "ttlk"],
        ["GETSET", "ttlk", "z"], ["TTL", "ttlk"],
        ["SET", "c", "v", "NX", "XX"],
        ["SET", "c", "v", "EX", "10", "PX", "10000"],
        ["SET", "c", "v", "EX", "10", "KEEPTTL"],
        ["SET", "c", "v", "EX", "0"], ["SET", "c", "v", "EX", "-1"],
        ["SETEX", "se", "0", "v"], ["PSETEX", "se", "-1", "v"],
        ["GETRANGE", "missing", "0", "-1"], ["SETRANGE", "adv2", "0", ""],
        ["DECRBY", "of", "-9223372036854775808"],
        ["SET", "of2", "9223372036854775807"], ["INCR", "of2"],
    ]
    return [o for o in ops if o[0] != "OBJECTENCODINGSKIP"]

rng = random.Random(SEED)
def gen_set(rng):
    keys = ["set%d" % i for i in range(12)]
    ints = [str(rng.randrange(-100, 100)) for _ in range(40)] + ["9223372036854775807", "-9223372036854775808", "0", "-0", "007"]
    strs = ["a", "bb", "hello", "x" * 70, "binm"] + ["member-%d" % i for i in range(8)]
    ops = []
    def K(): return rng.choice(keys)
    def members(pool, k):
        return [rng.choice(pool) for _ in range(k)]
    for _ in range(3500):
        c = rng.randrange(14)
        pool = ints if rng.randrange(3) else (ints + strs)
        if   c in (0,1,2): ops.append(["SADD", K()] + members(pool, rng.randrange(1, 6)))
        elif c == 3: ops.append(["SREM", K()] + members(pool, rng.randrange(1, 4)))
        elif c == 4: ops.append(["SISMEMBER", K(), rng.choice(pool)])
        elif c == 5: ops.append(["SMISMEMBER", K()] + members(pool, rng.randrange(1, 4)))
        elif c == 6: ops.append(["SCARD", K()])
        elif c == 7: ops.append(["SMEMBERS", K()])
        elif c == 8: ops.append(["DEL", K()])
        elif c == 9: ops.append(["EXISTS", K()])
        elif c == 10: ops.append(["TYPE", K()])
        elif c == 11: ops.append(["SADD", K()] + members(strs, rng.randrange(1, 4)))
        elif c == 12: ops.append(["GET", K()])                    # WRONGTYPE path
        elif c == 13: ops.append(["SADD", "grow"] + ["g%d" % rng.randrange(400) for _ in range(5)])
    # directed: conversions + WRONGTYPE + edge counts (deterministic only)
    ops += [
        ["DEL", "iv"], ["SADD", "iv"] + [str(i) for i in range(200)], ["SCARD", "iv"],   # int compact -> table
        ["SADD", "iv", "notint"], ["SCARD", "iv"], ["SMEMBERS", "iv"],
        ["DEL", "big"], ["SADD", "big", "y" * 100], ["SCARD", "big"],                    # value > 64 forces table
        ["SET", "str", "v"], ["SADD", "str", "m"], ["SCARD", "str"],
        ["SADD", "one", "solo"], ["SPOP", "one"], ["EXISTS", "one"],                      # SPOP deterministic on 1-elem
        ["SADD", "one2", "solo2"], ["SRANDMEMBER", "one2"], ["SPOP", "one2", "1"],
        ["SPOP", "missingset"], ["SPOP", "missingset", "3"], ["SRANDMEMBER", "missingset"],
        ["SRANDMEMBER", "missingset", "5"], ["SRANDMEMBER", "missingset", "-5"],
        ["SMISMEMBER", "missingset", "a", "b"],
    ]
    return ops

gens = {"string": gen_string, "set": gen_set}
ops = gens[SUITE](rng)

ts, tf = conn(TH, TP)
os_, of = conn(OH, OP)
# clean slates
for s, f in ((ts, tf), (os_, of)):
    s.sendall(enc(["FLUSHALL"])) if SUITE == "never" else None
diffs = 0
BATCH = 64
for i in range(0, len(ops), BATCH):
    chunk = ops[i:i + BATCH]
    payload = b"".join(enc(o) for o in chunk)
    ts.sendall(payload); os_.sendall(payload)
    for o in chunk:
        a = normalize(o[0], read_reply(tf))
        b = normalize(o[0], read_reply(of))
        if a != b:
            diffs += 1
            if diffs <= 12:
                print("  DIFF %r\n    target: %r\n    oracle: %r" % (o[:4], a[:96], b[:96]))
ts.close(); os_.close()
print("DIFFER %s: %d ops, %d diffs -> %s" % (SUITE, len(ops), diffs, "PASS" if diffs == 0 else "FAIL"))
sys.exit(1 if diffs else 0)
