#!/usr/bin/env python3
# DIFFERENTIAL battery: run one deterministic command stream against the TARGET (tomokv-cpp) and
# the ORACLE (vanilla Redis 7.4.2 -- byte-exact redis semantics) and diff every reply.
#   python3 tests/differ.py <target_host> <target_port> <oracle_host> <oracle_port> <suite> [seed] [-3]
#   python3 tests/differ.py --list-generators
# Exit 0 iff zero diffs. Suites include the ordinary byte-comparison generators plus property
# suites (e.g. s6fix, scan) for commands whose successful replies are intentionally
# nondeterministic and must be compared as sets rather than byte streams.
import socket, sys, random, re, time, hashlib

LIST_GENERATORS = sys.argv[1:] == ["--list-generators"]
if LIST_GENERATORS:
    TH = OH = ""
    TP = OP = 0
    SUITE = ""
    EXTRA = []
else:
    TH, TP, OH, OP = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
    SUITE = sys.argv[5]
    EXTRA = sys.argv[6:]
RESP3 = "-3" in EXTRA
SEED = int(next((arg for arg in EXTRA if arg != "-3"), "7"))

def conn(h, p):
    s = socket.create_connection((h, p), timeout=30)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    f = s.makefile("rb")
    if RESP3:
        s.sendall(enc(["HELLO", "3"]))
        hello = read_reply(f)
        if not hello.startswith(b"%7\r\n"):
            raise RuntimeError("HELLO 3 failed for %s:%d: %r" % (h, p, hello[:96]))
    return s, f
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
    if t in b"+-:,_#(": return line
    if t in (b"$", b"=", b"!"):
        n = int(line[1:-2])
        if n == -1: return line
        return line + f.read(n + 2)
    if t in (b"*", b"~", b">"):
        n = int(line[1:-2])
        if n == -1: return line
        return line + b"".join(read_reply(f) for _ in range(n))
    if t in (b"%", b"|"):
        n = int(line[1:-2])
        return line + b"".join(read_reply(f) for _ in range(n * 2))
    raise ValueError(repr(line[:24]))

def parse_reply(r):
    # Decode serialized RESP2/RESP3 into a Python structure for unordered normalization.
    def one(pos):
        marker = r[pos:pos + 1]
        end = r.index(b"\r\n", pos)
        line = r[pos + 1:end]
        next_pos = end + 2
        if marker in b"+-:, #(".replace(b" ", b""):
            return marker + line, next_pos
        if marker == b"_": return None, next_pos
        if marker in (b"$", b"=", b"!"):
            length = int(line)
            if length == -1: return None, next_pos
            value = r[next_pos:next_pos + length]
            return value, next_pos + length + 2
        if marker in (b"*", b"~", b">"):
            count = int(line)
            if count == -1: return None, next_pos
            values = []
            for _ in range(count):
                value, next_pos = one(next_pos)
                values.append(value)
            return values, next_pos
        if marker in (b"%", b"|"):
            values = []
            for _ in range(int(line) * 2):
                value, next_pos = one(next_pos)
                values.append(value)
            return values, next_pos
        raise ValueError("unsupported RESP marker %r" % marker)
    try:
        value, consumed = one(0)
        return value if consumed == len(r) else None
    except (ValueError, IndexError):
        return None

SORTED_SET_REPLIES = {"SMEMBERS", "SPOPSHAPE", "HKEYS", "HVALS",
                      "KEYS", "SINTER", "SUNION", "SDIFF"}

def sort_nested(value):
    # FUNCTION LIST enumerates libraries and their functions in hash order on Redis and in name
    # order here; both are unordered by contract. Canonicalize any list whose elements are all
    # lists (the library list, the function list) and leave flat key/value rows alone.
    if not isinstance(value, list):
        return value
    out = [sort_nested(item) for item in value]
    if out and all(isinstance(item, list) for item in out):
        out.sort(key=repr)
    return out
def normalize_introspection(cmdname, argv, r):
    """MEMORY USAGE and COMMAND INFO are compared for MEANING, not bytes.

    MEMORY USAGE: the number is our accounting, not redis's, so only hit-vs-miss is comparable.
    COMMAND INFO: the flag names, ACL category list and key-spec map are redis-internal; the name,
    arity and legacy key range are the parts the router and every client actually consume.
    """
    if cmdname == "MEMORY" and len(argv) > 1 and argv[1].upper() == "USAGE":
        return b"USAGE:nil" if r.startswith((b"$-1", b"_")) else b"USAGE:present"
    if cmdname == "COMMAND" and len(argv) > 1 and argv[1].upper() == "INFO":
        rows = parse_reply(r)
        if not isinstance(rows, list):
            return r
        out = []
        for row in rows:
            if row is None:
                out.append(b"<nil>")
            elif isinstance(row, list) and len(row) >= 6:
                out.append(b"%s/%s/%s/%s/%s" % (row[0], row[1], row[3], row[4], row[5]))
            else:
                out.append(b"<shape?>")
        return b"CMDINFO:" + b";".join(out)
    return r

def normalize(cmdname, r):
    if cmdname == "FUNCTION" and r[:1] in (b"*", b"%"):
        parsed = parse_reply(r)
        if parsed is not None:
            return b"FNSORTED:" + repr(sort_nested(parsed)).encode()
    if cmdname == "HGETALL" and r[:1] in (b"*", b"%") and not r.startswith(b"*-1"):
        it = parse_reply(r)
        if it is not None and len(it) % 2 == 0:
            pairs = sorted((it[i], it[i+1]) for i in range(0, len(it), 2))
            return b"HSORTED:" + b";".join(b"%s=%s" % p for p in pairs)
    if cmdname in SORTED_SET_REPLIES:
        it = parse_reply(r)
        if isinstance(it, list):
            return b"SORTED:" + b",".join(sorted(x if x is not None else b"<nil>" for x in it))
    # HTTL/HPTTL are remaining-time answers computed from each server's own clock, so a
    # far-future deadline lands a few ms apart. Bucket to 10 s; the ABSOLUTE forms
    # (HEXPIRETIME/HPEXPIRETIME) stay byte-exact and are what actually pins the deadline.
    if cmdname in ("HTTL", "HPTTL") and r[:1] == b"*":
        it = parse_reply(r)
        if isinstance(it, list):
            out = []
            for x in it:
                v = int(x[1:]) if isinstance(x, bytes) and x[:1] == b":" else None
                if v is None: out.append(b"?")
                elif v < 0: out.append(b"%d" % v)
                else:
                    ms = v * 1000 if cmdname == "HTTL" else v
                    out.append(b"~%d" % (ms // 10000))
            return b"HTTLB:" + b",".join(out)
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

def gen_list(rng):
    keys = ["l%d" % i for i in range(10)]
    vals = ["a", "bb", "ccc", "x" * 80, "v-%d" % 0] + ["item%d" % i for i in range(12)]
    ops = []
    def K(): return rng.choice(keys)
    def V(): return rng.choice(vals)
    for _ in range(3500):
        c = rng.randrange(16)
        if   c in (0,1): ops.append(["LPUSH", K()] + [V() for _ in range(rng.randrange(1,4))])
        elif c in (2,3): ops.append(["RPUSH", K()] + [V() for _ in range(rng.randrange(1,4))])
        elif c == 4: ops.append(["LPUSHX", K(), V()])
        elif c == 5: ops.append(["RPUSHX", K(), V()])
        elif c == 6: ops.append(["LPOP", K()] if rng.randrange(2) else ["LPOP", K(), str(rng.randrange(0,4))])
        elif c == 7: ops.append(["RPOP", K()] if rng.randrange(2) else ["RPOP", K(), str(rng.randrange(0,4))])
        elif c == 8: ops.append(["LLEN", K()])
        elif c == 9: ops.append(["LRANGE", K(), str(rng.randrange(-8,8)), str(rng.randrange(-8,8))])
        elif c == 10: ops.append(["LINDEX", K(), str(rng.randrange(-10,10))])
        elif c == 11: ops.append(["LSET", K(), str(rng.randrange(-6,6)), V()])
        elif c == 12: ops.append(["LINSERT", K(), rng.choice(["BEFORE","AFTER"]), V(), V()])
        elif c == 13: ops.append(["LREM", K(), str(rng.randrange(-3,4)), V()])
        elif c == 14: ops.append(["LTRIM", K(), str(rng.randrange(-6,6)), str(rng.randrange(-6,6))])
        elif c == 15: ops.append(["LPOS", K(), V()] + (["RANK", str(rng.choice([-2,-1,1,2])), "COUNT", str(rng.randrange(0,3))] if rng.randrange(2) else []))
    ops += [
        ["DEL","dl"], ["RPUSH","dl","a","b","c"], ["LTRIM","dl","1","0"], ["EXISTS","dl"],
        ["RPUSH","dl2","a"], ["LINSERT","dl2","BEFORE","missing","x"], ["LLEN","dl2"],
        ["LPOS","dl2","a","RANK","-1"], ["LPOS","missinglist","a"],
        ["RPUSH","big"] + ["e%d" % i for i in range(300)], ["LLEN","big"], ["LRANGE","big","250","260"],
        ["LPOP","big","5"], ["RPOP","big","5"], ["LREM","big","0","e100"], ["LLEN","big"],
        ["SET","strk","v"], ["LPUSH","strk","x"], ["LLEN","strk"],
        ["LSET","missinglist","0","v"], ["LPOP","missinglist","2"],
    ]
    return ops

def gen_stream(rng):
    """Explicit-ID primary arm. Approximate trim and wall-clock IDs are property-tested elsewhere."""
    keys = ["xs%d" % i for i in range(12)]
    next_id = {key: 0 for key in keys}
    known = {key: [] for key in keys}
    ops = []

    def add(key):
        next_id[key] += 1
        ident = "%d-%d" % (next_id[key] // 7 + 1, next_id[key] % 7)
        known[key].append(ident)
        fields = ["f", "v%d" % next_id[key]]
        if rng.randrange(3) == 0:
            fields += ["g", "x%d" % rng.randrange(100)]
        ops.append(["XADD", key, ident] + fields)

    for key in keys:
        add(key)
    for _ in range(4000):
        key = rng.choice(keys)
        choice = rng.randrange(12)
        if choice < 4:
            add(key)
        elif choice == 4:
            ops.append(["XLEN", key])
        elif choice == 5:
            start = rng.choice(["-", "0-0", "(" + (rng.choice(known[key]) if known[key] else "0-0"),
                                str(rng.randrange(0, 20))])
            end = rng.choice(["+", "%d-%d" % (rng.randrange(1, 30), rng.randrange(0, 8))])
            op = ["XRANGE", key, start, end]
            if rng.randrange(2): op += ["COUNT", str(rng.randrange(0, 6))]
            ops.append(op)
        elif choice == 6:
            end = rng.choice(["+", "%d-%d" % (rng.randrange(1, 30), rng.randrange(0, 8))])
            start = rng.choice(["-", "(" + (rng.choice(known[key]) if known[key] else "0-0")])
            op = ["XREVRANGE", key, end, start]
            if rng.randrange(2): op += ["COUNT", str(rng.randrange(0, 6))]
            ops.append(op)
        elif choice == 7:
            ids = [rng.choice(known[key]) if known[key] and rng.randrange(3) else
                   "%d-%d" % (rng.randrange(1, 30), rng.randrange(0, 8))
                   for _ in range(rng.randrange(1, 4))]
            ops.append(["XDEL", key] + ids)
        elif choice == 8:
            ops.append(["XTRIM", key, "MAXLEN", "=", str(rng.randrange(0, 12))])
        elif choice == 9:
            ops.append(["XTRIM", key, "MINID", "=",
                        "%d-%d" % (rng.randrange(1, 30), rng.randrange(0, 8))])
        elif choice == 10:
            cursor = rng.choice(known[key]) if known[key] and rng.randrange(2) else "0-0"
            ops.append(["XREAD", "COUNT", str(rng.randrange(1, 5)), "STREAMS", key, cursor])
        else:
            second = rng.choice(keys)
            c1 = rng.choice(known[key]) if known[key] and rng.randrange(2) else "0-0"
            c2 = rng.choice(known[second]) if known[second] and rng.randrange(2) else "0-0"
            ops.append(["XREAD", "COUNT", "2", "STREAMS", key, second, c1, c2])
    ops += [
        ["XADD", "edge", "0-0", "f", "v"], ["EXISTS", "edge"],
        ["XADD", "edge", "1-0", "f", "v"], ["XADD", "edge", "1-0", "f", "dup"],
        ["XADD", "edge", "1-*", "f", "auto-seq"], ["XADD", "edge", "1-*", "f", "auto-seq2"],
        ["XRANGE", "edge", "1", "1"], ["XRANGE", "edge", "(1-0", "+"],
        ["XRANGE", "edge", "-", "+", "COUNT", "0"],
        ["XDEL", "edge", "1-0", "bad-id"], ["XLEN", "edge"],
        ["XTRIM", "edge", "MAXLEN", "=", "0"], ["XLEN", "edge"],
        ["XADD", "nomake", "NOMKSTREAM", "*", "f", "v"], ["EXISTS", "nomake"],
        ["XADD", "edge", "MAXLEN", "=", "1", "LIMIT", "1", "2-0", "f", "v"],
        ["SET", "stream-wrong", "v"], ["XLEN", "stream-wrong"],
        ["XREAD", "STREAMS", "edge", "stream-wrong", "0-0", "0-0"],
    ]
    return ops

def gen_streamgrp(rng):
    """Consumer-group mix with explicit stream IDs and no wall-clock-valued replies."""
    keys = ["xg%d" % i for i in range(8)]
    consumers = ["a", "b", "c", "d"]
    next_id = {key: 5 for key in keys}
    known = {key: ["%d-0" % i for i in range(1, 6)] for key in keys}
    ops = []
    for key in keys:
        for ident in known[key]:
            ops.append(["XADD", key, ident, "f", "v" + ident])
        ops.append(["XGROUP", "CREATE", key, "g", "0-0", "ENTRIESREAD", "0"])

    for _ in range(4000):
        key = rng.choice(keys)
        consumer = rng.choice(consumers)
        choice = rng.randrange(16)
        if choice in (0, 1, 2):
            next_id[key] += 1
            ident = "%d-0" % next_id[key]
            known[key].append(ident)
            ops.append(["XADD", key, ident, "f", "v" + ident])
        elif choice == 3:
            ops.append(["XREADGROUP", "GROUP", "g", consumer, "COUNT",
                        str(rng.randrange(1, 5)), "STREAMS", key, ">"])
        elif choice == 4:
            cursor = rng.choice(["0-0"] + known[key])
            ops.append(["XREADGROUP", "GROUP", "g", consumer, "COUNT", "3",
                        "STREAMS", key, cursor])
        elif choice == 5:
            ids = [rng.choice(known[key]) for _ in range(rng.randrange(1, 4))]
            ops.append(["XACK", key, "g"] + ids)
        elif choice == 6:
            ops.append(["XPENDING", key, "g"])
        elif choice == 7:
            ids = [rng.choice(known[key]) for _ in range(rng.randrange(1, 4))]
            ops.append(["XCLAIM", key, "g", consumer, "0"] + ids + ["JUSTID"])
        elif choice == 8:
            ident = rng.choice(known[key])
            ops.append(["XCLAIM", key, "g", consumer, "0", ident, "FORCE", "JUSTID"])
        elif choice == 9:
            start = rng.choice(["0-0"] + known[key])
            ops.append(["XAUTOCLAIM", key, "g", consumer, "0", start,
                        "COUNT", str(rng.randrange(1, 4)), "JUSTID"])
        elif choice == 10:
            ids = [rng.choice(known[key]) for _ in range(rng.randrange(1, 3))]
            ops.append(["XDEL", key] + ids)
        elif choice == 11:
            ops.append(["XTRIM", key, "MAXLEN", "=", str(rng.randrange(2, 12))])
        elif choice == 12:
            ident = rng.choice(known[key])
            read = int(ident.split("-", 1)[0])
            ops.append(["XGROUP", "SETID", key, "g", ident,
                        "ENTRIESREAD", str(read)])
        elif choice == 13:
            ops.append(["XGROUP", "CREATECONSUMER", key, "g", consumer])
        elif choice == 14:
            ops.append(["XGROUP", "DELCONSUMER", key, "g", consumer])
        else:
            ops.append(["XPENDING", key, "g"])
    ops += [
        ["XGROUP", "CREATE", keys[0], "g", "0-0"],
        ["XACK", keys[0], "missing", "1-0"],
        ["XPENDING", keys[0], "missing"],
        ["XSETID", keys[0], "%d-0" % next_id[keys[0]]],
    ]
    return ops

def gen_zset(rng):
    keys = ["z%d" % i for i in range(8)]
    mems = ["m%d" % i for i in range(20)] + ["alpha", "beta", "x" * 70]
    scores = ["1", "2.5", "-3", "0", "1e3", "-1.5e-2", "inf", "-inf", "3.0000000000000004", "9007199254740993"]
    ops = []
    def K(): return rng.choice(keys)
    def M(): return rng.choice(mems)
    def S(): return rng.choice(scores)
    for _ in range(3500):
        c = rng.randrange(20)
        if   c in (0,1,2): ops.append(["ZADD", K()] + sum([[S(), M()] for _ in range(rng.randrange(1,4))], []))
        elif c == 3: ops.append(["ZADD", K(), rng.choice(["NX","XX","GT","LT"]), S(), M()])
        elif c == 4: ops.append(["ZADD", K(), "XX", "CH", S(), M()])
        elif c == 5: ops.append(["ZADD", K(), "INCR", S(), M()])
        elif c == 6: ops.append(["ZSCORE", K(), M()])
        elif c == 7: ops.append(["ZMSCORE", K(), M(), M()])
        elif c == 8: ops.append(["ZINCRBY", K(), S(), M()])
        elif c == 9: ops.append(["ZCARD", K()])
        elif c == 10: ops.append(["ZCOUNT", K(), rng.choice(["-inf","0","(1"]), rng.choice(["+inf","10","(5"])])
        elif c == 11: ops.append(["ZRANGE", K(), str(rng.randrange(-5,5)), str(rng.randrange(-5,5))] + (["WITHSCORES"] if rng.randrange(2) else []))
        elif c == 12: ops.append(["ZRANGE", K(), rng.choice(["-inf","(0","2"]), rng.choice(["+inf","8","(9"]), "BYSCORE"] + (["WITHSCORES"] if rng.randrange(2) else []))
        elif c == 13: ops.append(["ZRANGEBYSCORE", K(), "-inf", "+inf", "LIMIT", str(rng.randrange(0,3)), str(rng.randrange(-1,4))])
        elif c == 14: ops.append(["ZRANK", K(), M()] + (["WITHSCORE"] if rng.randrange(2) else []))
        elif c == 15: ops.append(["ZREVRANK", K(), M()])
        elif c == 16: ops.append(["ZREM", K(), M(), M()])
        elif c == 17: ops.append(["ZPOPMIN", K()] if rng.randrange(2) else ["ZPOPMAX", K(), str(rng.randrange(0,3))])
        elif c == 18: ops.append(["ZREMRANGEBYRANK", K(), str(rng.randrange(-4,3)), str(rng.randrange(-3,4))])
        elif c == 19: ops.append(["ZREMRANGEBYSCORE", K(), rng.choice(["-inf","(0"]), rng.choice(["+inf","5"])])
    ops += [
        ["DEL","lex"], ["ZADD","lex","0","a","0","b","0","c","0","d"],
        ["ZRANGEBYLEX","lex","-","+"], ["ZRANGEBYLEX","lex","[b","(d"], ["ZRANGEBYLEX","lex","(a","[c"],
        ["ZREVRANGEBYLEX","lex","+","-"], ["ZLEXCOUNT","lex","-","+"], ["ZLEXCOUNT","lex","[b","+"],
        ["ZRANGE","lex","(a","[c","BYLEX"], ["ZRANGE","lex","+","-","BYLEX","REV"],
        ["ZREMRANGEBYLEX","lex","[b","[c"], ["ZRANGE","lex","-","+","BYLEX"],
        ["ZADD","cf","NX","GT","1","m"], ["ZADD","cf","GT","LT","1","m"],
        ["ZADD","nan1","INCR","inf","m"], ["ZADD","nan1","INCR","-inf","m"],
        ["ZINCRBY","nan2","inf","m"], ["ZINCRBY","nan2","-inf","m"],
        ["ZADD","big"] + sum([["%d" % i, "bm%d" % i] for i in range(200)], []),
        ["ZCARD","big"], ["ZRANGE","big","95","105","WITHSCORES"], ["ZRANK","big","bm150"],
        ["ZPOPMIN","big","3"], ["ZPOPMAX","big","3"], ["ZCOUNT","big","(10","(20"],
        ["SET","strz","v"], ["ZADD","strz","1","m"], ["ZSCORE","strz","m"],
        ["ZPOPMIN","missing"], ["ZPOPMIN","missing","5"], ["ZRANK","missing","x","WITHSCORE"],
    ]
    return ops

def gen_zsetops(rng):
    zkeys = ["zo:z%d" % i for i in range(18)]
    skeys = ["zo:s%d" % i for i in range(8)]
    destinations = ["zo:d%d" % i for i in range(10)]
    members = ["m%d" % i for i in range(20)] + ["shared", "tie"]
    ops = []
    for _ in range(4200):
        c = rng.randrange(13)
        if c <= 2:
            key = rng.choice(zkeys)
            pairs = []
            for _ in range(rng.randrange(1, 4)):
                pairs += [str(rng.randrange(-30, 31)), rng.choice(members)]
            ops.append(["ZADD", key] + pairs)
        elif c == 3:
            ops.append(["SADD", rng.choice(skeys)] +
                       [rng.choice(members) for _ in range(rng.randrange(1, 5))])
        elif c == 4:
            ops.append(["DEL", rng.choice(zkeys + skeys)])
        elif c in (5, 6):
            command = "ZUNION" if c == 5 else "ZINTER"
            count = rng.randrange(1, 6)
            keys = [rng.choice(zkeys + skeys) for _ in range(count)]
            tail = []
            if rng.randrange(2):
                tail += ["WEIGHTS"] + [str(rng.randrange(-3, 4)) for _ in range(count)]
            if rng.randrange(2): tail += ["AGGREGATE", rng.choice(["SUM", "MIN", "MAX"])]
            if rng.randrange(2): tail += ["WITHSCORES"]
            ops.append([command, str(count)] + keys + tail)
        elif c == 7:
            count = rng.randrange(1, 6)
            ops.append(["ZDIFF", str(count)] +
                       [rng.choice(zkeys + skeys) for _ in range(count)] +
                       (["WITHSCORES"] if rng.randrange(2) else []))
        elif c == 8:
            count = rng.randrange(1, 6)
            tail = [] if rng.randrange(2) else ["LIMIT", str(rng.randrange(0, 8))]
            ops.append(["ZINTERCARD", str(count)] +
                       [rng.choice(zkeys + skeys) for _ in range(count)] + tail)
        elif c in (9, 10):
            command = "ZUNIONSTORE" if c == 9 else "ZINTERSTORE"
            count = rng.randrange(1, 6)
            keys = [rng.choice(zkeys + skeys) for _ in range(count)]
            tail = []
            if rng.randrange(2):
                tail += ["WEIGHTS"] + [str(rng.randrange(-3, 4)) for _ in range(count)]
            if rng.randrange(2): tail += ["AGGREGATE", rng.choice(["SUM", "MIN", "MAX"])]
            ops.append([command, rng.choice(destinations), str(count)] + keys + tail)
        elif c == 11:
            count = rng.randrange(1, 6)
            ops.append(["ZDIFFSTORE", rng.choice(destinations), str(count)] +
                       [rng.choice(zkeys + skeys) for _ in range(count)])
        else:
            ops.append(["ZRANGE", rng.choice(destinations), "0", "-1", "WITHSCORES"])
    return ops

def gen_geo(rng):
    keys = ["geo:g%d" % i for i in range(10)]
    destinations = ["geo:d%d" % i for i in range(10)]
    points = [
        ("13.361389", "38.115556", "palermo"),
        ("15.087269", "37.502669", "catania"),
        ("-73.985700", "40.748400", "nyc"),
        ("139.691700", "35.689500", "tokyo"),
        ("2.294500", "48.858400", "paris"),
        ("151.209300", "-33.868800", "sydney"),
    ]
    units = ["m", "km", "ft", "mi"]
    ops = []
    for _ in range(4200):
        c = rng.randrange(19)
        key = rng.choice(keys)
        lon, lat, member = rng.choice(points)
        if c <= 3:
            option = rng.choice([[], ["NX"], ["XX"], ["CH"], ["NX", "CH"], ["XX", "CH"]])
            ops.append(["GEOADD", key] + option + [lon, lat, member])
        elif c == 4:
            ops.append(["GEOPOS", key, member, rng.choice(points)[2], "missing"])
        elif c == 5:
            ops.append(["GEOHASH", key, member, rng.choice(points)[2]])
        elif c == 6:
            ops.append(["GEODIST", key, member, rng.choice(points)[2], rng.choice(units)])
        elif c in (7, 8):
            center = rng.choice(points)
            source = ["FROMMEMBER", center[2]] if c == 7 else ["FROMLONLAT", center[0], center[1]]
            shape = ["BYRADIUS", str(rng.choice([1, 30, 200, 20000])), rng.choice(units)]
            tail = rng.choice([["ASC"], ["DESC"], ["ASC", "WITHDIST"],
                               ["ASC", "WITHHASH"], ["ASC", "WITHCOORD"],
                               ["ASC", "WITHDIST", "WITHHASH", "WITHCOORD"],
                               ["ASC", "COUNT", "2"], ["ASC", "COUNT", "1"]])
            ops.append(["GEOSEARCH", key] + source + shape + tail)
        elif c == 9:
            center = rng.choice(points)
            ops.append(["GEOSEARCH", key, "FROMLONLAT", center[0], center[1],
                        "BYBOX", str(rng.choice([10, 500, 40000])),
                        str(rng.choice([10, 500, 40000])), "km",
                        rng.choice(["ASC", "DESC"])])
        elif c in (10, 11):
            center = rng.choice(points)
            tail = ["STOREDIST"] if c == 11 else []
            ops.append(["GEOSEARCHSTORE", rng.choice(destinations), key,
                        "FROMMEMBER", center[2], "BYRADIUS",
                        str(rng.choice([30, 200, 20000])), "km"] + tail)
        elif c == 12:
            center = rng.choice(points)
            ops.append(["GEORADIUS", key, center[0], center[1],
                        str(rng.choice([30, 200, 20000])), "km",
                        rng.choice(["ASC", "DESC"]), "COUNT", "3"])
        elif c == 13:
            center = rng.choice(points)
            ops.append(["GEORADIUS", key, center[0], center[1],
                        str(rng.choice([30, 200, 20000])), "km", "STORE",
                        rng.choice(destinations)])
        elif c == 14:
            center = rng.choice(points)
            ops.append(["GEORADIUSBYMEMBER", key, center[2],
                        str(rng.choice([30, 200, 20000])), "km",
                        rng.choice(["ASC", "DESC"])])
        elif c == 15:
            center = rng.choice(points)
            ops.append(["GEORADIUSBYMEMBER", key, center[2],
                        str(rng.choice([30, 200, 20000])), "km",
                        rng.choice(["STORE", "STOREDIST"]), rng.choice(destinations)])
        elif c == 16:
            center = rng.choice(points)
            ops.append(["GEORADIUS_RO", key, center[0], center[1],
                        str(rng.choice([30, 200, 20000])), "km",
                        rng.choice(["ASC", "DESC"])])
        elif c == 17:
            center = rng.choice(points)
            ops.append(["GEORADIUSBYMEMBER_RO", key, center[2],
                        str(rng.choice([30, 200, 20000])), "km",
                        rng.choice(["ASC", "DESC"])])
        else:
            ops.append(["ZCARD", rng.choice(destinations)])
    return ops


def gen_hash(rng):
    keys = ["h%d" % i for i in range(12)]
    fields = ["f%d" % i for i in range(20)] + ["", "bin\x00fld", "F" * 80]
    vals = ["", "x", "hello world", "12345", "-7", "9223372036854775807", "1e100",
            "v" * 120, "\x00\x01\xff"]
    nums = ["1", "-3", "100", "9223372036854775807", "-9223372036854775808", "notanum"]
    floats = ["0.1", "-3.5e2", "1e100", "nan", "abc", "5.0e3", "10.5"]
    ops = []
    def K(): return rng.choice(keys)
    def F(): return rng.choice(fields)
    for _ in range(3500):
        c = rng.randrange(16)
        if   c in (0, 1, 2):
            pairs = []
            for _ in range(rng.randrange(1, 4)): pairs += [F(), rng.choice(vals)]
            ops.append(["HSET", K()] + pairs)
        elif c == 3: ops.append(["HGET", K(), F()])
        elif c == 4: ops.append(["HDEL", K()] + [F() for _ in range(rng.randrange(1, 3))])
        elif c == 5: ops.append(["HMGET", K()] + [F() for _ in range(rng.randrange(1, 4))])
        elif c == 6: ops.append(["HSETNX", K(), F(), rng.choice(vals)])
        elif c == 7: ops.append(["HLEN", K()])
        elif c == 8: ops.append(["HEXISTS", K(), F()])
        elif c == 9: ops.append(["HSTRLEN", K(), F()])
        elif c == 10: ops.append(["HINCRBY", K(), rng.choice(fields[:6]), rng.choice(nums)])
        elif c == 11: ops.append(["HINCRBYFLOAT", K(), rng.choice(fields[:6]), rng.choice(floats)])
        elif c == 12: ops.append([rng.choice(["HGETALL", "HKEYS", "HVALS"]), K()])
        elif c == 13: ops.append(["DEL", K()])
        elif c == 14: ops.append([rng.choice(["TYPE", "EXISTS", "HLEN"]), K()])
        elif c == 15: ops.append(["HSET", "hgrow"] + ["g%d" % rng.randrange(300), rng.choice(vals)])
    # directed: promotion, big values, binary, WRONGTYPE, deterministic HRANDFIELD forms
    ops += [
        ["DEL", "hp"], ["HSET", "hp"] + sum((["p%d" % i, "v%d" % i] for i in range(200)), []),
        ["HLEN", "hp"], ["HGET", "hp", "p150"], ["HGETALL", "hp"],
        ["DEL", "hbig"], ["HSET", "hbig", "f", "Y" * 100], ["HSTRLEN", "hbig", "f"],
        ["HSET", "hnul", "a\x00b", "c\x00d"], ["HGET", "hnul", "a\x00b"], ["HGETALL", "hnul"],
        ["HSET", "hemp", "", ""], ["HGET", "hemp", ""], ["HSTRLEN", "hemp", ""], ["HLEN", "hemp"],
        ["SET", "hstr", "v"], ["HSET", "hstr", "f", "v"], ["HGET", "hstr", "f"],
        ["HSET", "h0", "wt", "x"], ["GET", "h0"], ["APPEND", "h0", "y"],
        ["HRANDFIELD", "missingh"], ["HRANDFIELD", "missingh", "3"],
        ["HRANDFIELD", "missingh", "-3"], ["HRANDFIELD", "missingh", "3", "WITHVALUES"],
        ["DEL", "hone"], ["HSET", "hone", "solo", "sv"],
        ["HRANDFIELD", "hone"], ["HRANDFIELD", "hone", "5"], ["HRANDFIELD", "hone", "-4"],
        ["HRANDFIELD", "hone", "5", "WITHVALUES"], ["HRANDFIELD", "hone", "0"],
        ["HSET", "hdelall", "a", "1", "b", "2"], ["HDEL", "hdelall", "a", "b"],
        ["EXISTS", "hdelall"], ["TYPE", "hdelall"],
        ["HSETNX", "hnx", "f", "first"], ["HSETNX", "hnx", "f", "second"], ["HGET", "hnx", "f"],
        ["HINCRBY", "hof", "f", "9223372036854775807"], ["HINCRBY", "hof", "f", "1"],
        ["HSET", "hif", "f", "5"], ["HINCRBYFLOAT", "hif", "f", "0.1"], ["HGET", "hif", "f"],
        ["HMGET", "missingh2", "a", "b", "c"],
    ]
    return ops

def gen_hexpire(rng):
    # Hash-field TTLs.  Every deadline is ABSOLUTE and either far in the future or definitively in
    # the past, so the whole stream is deterministic on both servers: no sleep, no clock race, and
    # the "already past" deadlines exercise the immediate-delete return code (2) reproducibly.
    keys = ["hx%d" % i for i in range(10)]
    fields = ["f%d" % i for i in range(14)] + ["", "bin\x00fld", "L" * 70]
    vals = ["", "v", "hello world", "12345", "-7", "w" * 130, "\x00\x01\xff"]
    base = 1900000000000                      # ~2030, comfortably inside the 46-bit ceiling
    future_ms = [base, base + 1, base + 7777, base + 3600000, base + 86400000]
    past_ms = [1, 2, 1000, 1500000000000 - 1000000000]
    conds = [[], ["NX"], ["XX"], ["GT"], ["LT"]]
    setters = ["HEXPIREAT", "HPEXPIREAT"]
    readers = ["HTTL", "HPTTL", "HEXPIRETIME", "HPEXPIRETIME"]
    ops = []
    def K(): return rng.choice(keys)
    def F(): return rng.choice(fields)
    def flist(n): return [F() for _ in range(n)]

    # seed every key so the interesting branches are reachable from op 0
    for k in keys:
        pairs = []
        for i in range(6):
            pairs += ["f%d" % i, "v%d" % i]
        ops.append(["HSET", k] + pairs)

    for _ in range(4200):
        c = rng.randrange(22)
        if c in (0, 1, 2, 3, 4):
            cmd = rng.choice(setters)
            at = rng.choice(future_ms if rng.randrange(5) else past_ms)
            if cmd == "HEXPIREAT":
                at //= 1000
            n = rng.randrange(1, 4)
            fs = flist(n)
            ops.append([cmd, K(), str(at)] + rng.choice(conds) + ["FIELDS", str(n)] + fs)
        elif c in (5, 6, 7):
            n = rng.randrange(1, 4)
            ops.append([rng.choice(readers), K(), "FIELDS", str(n)] + flist(n))
        elif c == 8:
            n = rng.randrange(1, 3)
            ops.append(["HPERSIST", K(), "FIELDS", str(n)] + flist(n))
        elif c in (9, 10):
            pairs = []
            for _ in range(rng.randrange(1, 3)):
                pairs += [F(), rng.choice(vals)]
            ops.append(["HSET", K()] + pairs)
        elif c == 11:
            ops.append(["HDEL", K()] + flist(rng.randrange(1, 3)))
        elif c == 12:
            ops.append(["HGET", K(), F()])
        elif c == 13:
            ops.append(["HMGET", K()] + flist(rng.randrange(1, 4)))
        elif c == 14:
            ops.append(["HGETALL", K()])
        elif c == 15:
            ops.append([rng.choice(["HLEN", "EXISTS", "TYPE"]), K()])
        elif c == 16:
            ops.append(["HEXISTS", K(), F()])
        elif c == 17:
            ops.append(["HSTRLEN", K(), F()])
        elif c == 18:
            ops.append(["HSETNX", K(), F(), rng.choice(vals)])
        elif c == 19:
            ops.append(["HINCRBY", K(), rng.choice(fields[:4]), rng.choice(["1", "-2"])])
        elif c == 20:
            ops.append(["DEL", K()])
        else:
            ops.append(["HSET", K(), F(), rng.choice(vals)])

    # directed tail: the error surface, the ceiling, and the representation transitions
    far = str(base + 500)
    ops += [
        ["DEL", "hxe"], ["SET", "hxstr", "v"],
        ["HEXPIRE", "hxstr", "100", "FIELDS", "1", "a"],
        ["HTTL", "hxstr", "FIELDS", "1", "a"],
        ["HPERSIST", "hxstr", "FIELDS", "1", "a"],
        ["HEXPIREAT", "hxmissing", "99999999", "FIELDS", "2", "a", "b"],
        ["HTTL", "hxmissing", "FIELDS", "3", "a", "b", "c"],
        ["HPEXPIREAT", "hxe", "abc", "FIELDS", "1", "a"],
        ["HPEXPIREAT", "hxe", "-1", "FIELDS", "1", "a"],
        ["HPEXPIREAT", "hxe", "70368744177664", "FIELDS", "1", "a"],
        ["HEXPIREAT", "hxe", "70368744178", "FIELDS", "1", "a"],
        ["HEXPIRE", "hxe", "1000000000000", "FIELDS", "1", "a"],
        ["HPEXPIRE", "hxe", "70368744177664", "FIELDS", "1", "a"],
        ["HEXPIREAT", "hxe", "100", "FIELDS", "2", "a"],
        ["HEXPIREAT", "hxe", "100", "FIELDS", "1", "a", "b"],
        ["HEXPIREAT", "hxe", "100", "FIELDS", "0", "a"],
        ["HEXPIREAT", "hxe", "100", "FIELDS", "-3", "a"],
        ["HEXPIREAT", "hxe", "100", "FIELDS", "zz", "a"],
        ["HTTL", "hxe", "FIELDS", "zz", "a"], ["HTTL", "hxe", "FIELDS", "0", "a"],
        ["HEXPIREAT", "hxe", "100", "NX", "XX", "FIELDS", "1", "a"],
        ["HEXPIREAT", "hxe", "100", "GT", "LT", "FIELDS", "1", "a"],
        ["HEXPIREAT", "hxe", "100", "NOPE", "1", "a"],
        ["HPERSIST", "hxe", "NOPE", "1", "a"],
        # one-field hash: the first deadline changes its internal representation
        ["DEL", "hxsmall"], ["HSET", "hxsmall", "solo", "sv"],
        ["HPEXPIREAT", "hxsmall", far, "FIELDS", "1", "solo"],
        ["HGET", "hxsmall", "solo"], ["HPEXPIRETIME", "hxsmall", "FIELDS", "1", "solo"],
        ["HPERSIST", "hxsmall", "FIELDS", "1", "solo"],
        ["HPEXPIRETIME", "hxsmall", "FIELDS", "1", "solo"],
        # last field expires immediately -> the key must disappear
        ["DEL", "hxlast"], ["HSET", "hxlast", "a", "1", "b", "2"],
        ["HEXPIREAT", "hxlast", "1", "FIELDS", "1", "a"],
        ["HLEN", "hxlast"], ["EXISTS", "hxlast"],
        ["HEXPIREAT", "hxlast", "1", "FIELDS", "1", "b"],
        ["HLEN", "hxlast"], ["EXISTS", "hxlast"], ["TYPE", "hxlast"],
        # value writes clear the deadline, counter writes keep it
        ["DEL", "hxw"], ["HSET", "hxw", "a", "1", "n", "5"],
        ["HPEXPIREAT", "hxw", far, "FIELDS", "2", "a", "n"],
        ["HSET", "hxw", "a", "2"], ["HPEXPIRETIME", "hxw", "FIELDS", "2", "a", "n"],
        ["HINCRBY", "hxw", "n", "1"], ["HPEXPIRETIME", "hxw", "FIELDS", "1", "n"],
        ["HSETNX", "hxw", "n", "9"], ["HPEXPIRETIME", "hxw", "FIELDS", "1", "n"],
        ["HDEL", "hxw", "n"], ["HSET", "hxw", "n", "5"],
        ["HPEXPIRETIME", "hxw", "FIELDS", "1", "n"],
        # deadlines travel with the value
        ["DEL", "hxc"], ["DEL", "hxc2"], ["HSET", "hxc", "a", "1", "b", "2"],
        ["HPEXPIREAT", "hxc", far, "FIELDS", "1", "a"],
        ["COPY", "hxc", "hxc2"], ["HPEXPIRETIME", "hxc2", "FIELDS", "2", "a", "b"],
        ["HPERSIST", "hxc2", "FIELDS", "1", "a"],
        ["HPEXPIRETIME", "hxc", "FIELDS", "1", "a"],
        ["RENAME", "hxc", "hxc3"], ["HPEXPIRETIME", "hxc3", "FIELDS", "2", "a", "b"],
        # a promoted hash carrying deadlines on a subset
        ["DEL", "hxbig"],
        ["HSET", "hxbig"] + sum(([("g%d" % i), ("gv%d" % i)] for i in range(200)), []),
        ["HPEXPIREAT", "hxbig", far, "FIELDS", "3", "g0", "g100", "g199"],
        ["HPEXPIRETIME", "hxbig", "FIELDS", "4", "g0", "g100", "g199", "g5"],
        ["HLEN", "hxbig"], ["HGET", "hxbig", "g100"],
        ["HEXPIREAT", "hxbig", "1", "FIELDS", "2", "g0", "g5"],
        ["HLEN", "hxbig"], ["HGET", "hxbig", "g0"],
        # binary and empty field names
        ["DEL", "hxbin"], ["HSET", "hxbin", "a\x00b", "1", "", "2"],
        ["HPEXPIREAT", "hxbin", far, "FIELDS", "2", "a\x00b", ""],
        ["HPEXPIRETIME", "hxbin", "FIELDS", "2", "a\x00b", ""],
        ["HGETALL", "hxbin"],
        # case-insensitive tokens
        ["hpexpireat", "hxbin", far, "nx", "fields", "1", "a\x00b"],
        ["httl", "hxbin", "fields", "1", "a\x00b"],
    ]
    return ops

def gen_xshard(rng):
    # Long, unrelated names spread across the full router instead of clustering in a small prefix.
    keys = ["xs:%02d:%s" % (i, "".join(rng.choice("abcdef0123456789") for _ in range(38)))
            for i in range(48)]
    setkeys = keys[:16]
    listkeys = keys[16:28]
    strkeys = keys[28:]
    members = ["m%d" % i for i in range(18)] + ["long-member-" + "x" * 60]
    values = ["", "v", "hello", "42", "value-" + "y" * 90]
    ops = []

    def ks(n, pool=keys): return [rng.choice(pool) for _ in range(n)]
    def pairs(n):
        out = []
        for key in ks(n): out += [key, rng.choice(values)]
        return out

    # Establish all three value families, then continually collide and delete them below.
    for key in strkeys: ops.append(["SET", key, rng.choice(values)])
    for key in setkeys: ops.append(["SADD", key] + rng.sample(members, rng.randrange(1, 6)))
    for key in listkeys: ops.append(["RPUSH", key] + rng.sample(members, rng.randrange(1, 6)))

    for _ in range(4200):
        c = rng.randrange(28)
        if c == 0: ops.append(["MGET"] + ks(rng.randrange(2, 8)))
        elif c == 1: ops.append(["MSET"] + pairs(rng.randrange(2, 7)))
        elif c == 2: ops.append(["DEL"] + ks(rng.randrange(2, 7)))
        elif c == 3: ops.append(["UNLINK"] + ks(rng.randrange(2, 7)))
        elif c == 4: ops.append(["EXISTS"] + ks(rng.randrange(2, 8)))
        elif c == 5: ops.append(["TOUCH"] + ks(rng.randrange(2, 8)))
        elif c == 6: ops.append(["MSETNX"] + pairs(rng.randrange(2, 6)))
        elif c == 7: ops.append(["RENAME", rng.choice(keys), rng.choice(keys)])
        elif c == 8: ops.append(["RENAMENX", rng.choice(keys), rng.choice(keys)])
        elif c == 9:
            ops.append(["COPY", rng.choice(keys), rng.choice(keys)] +
                       (["REPLACE"] if rng.randrange(2) else []))
        elif c == 10: ops.append(["SMOVE", rng.choice(setkeys), rng.choice(setkeys), rng.choice(members)])
        elif c == 11:
            ops.append(["LMOVE", rng.choice(listkeys), rng.choice(listkeys),
                        rng.choice(["LEFT", "RIGHT"]), rng.choice(["LEFT", "RIGHT"])])
        elif c == 12: ops.append(["RPOPLPUSH", rng.choice(listkeys), rng.choice(listkeys)])
        elif c == 13: ops.append(["SINTER"] + ks(rng.randrange(2, 6), setkeys))
        elif c == 14: ops.append(["SUNION"] + ks(rng.randrange(2, 6), setkeys))
        elif c == 15: ops.append(["SDIFF"] + ks(rng.randrange(2, 6), setkeys))
        elif c == 16: ops.append(["SINTERSTORE", rng.choice(keys)] + ks(rng.randrange(2, 5), setkeys))
        elif c == 17: ops.append(["SUNIONSTORE", rng.choice(keys)] + ks(rng.randrange(2, 5), setkeys))
        elif c == 18: ops.append(["SDIFFSTORE", rng.choice(keys)] + ks(rng.randrange(2, 5), setkeys))
        elif c == 19:
            src = ks(rng.randrange(1, 5), setkeys)
            ops.append(["SINTERCARD", str(len(src))] + src +
                       (["LIMIT", str(rng.randrange(0, 5))] if rng.randrange(2) else []))
        elif c == 20: ops.append(["SET", rng.choice(keys), rng.choice(values)])
        elif c == 21: ops.append(["SADD", rng.choice(keys), rng.choice(members), rng.choice(members)])
        elif c == 22: ops.append(["RPUSH", rng.choice(keys), rng.choice(members)])
        elif c == 23: ops.append(["KEYS", rng.choice(["xs:*", "xs:0?:*", "*member*", "no-match-*"])])
        elif c == 24: ops.append(["GET", rng.choice(keys)])
        elif c == 25: ops.append(["SMEMBERS", rng.choice(setkeys)])
        elif c == 26: ops.append(["LRANGE", rng.choice(listkeys), "0", "-1"])
        else: ops.append(["TYPE", rng.choice(keys)])

    # Directed edge semantics. These names are also long enough to avoid accidentally sharing one
    # shard in small deployments; the implementation still handles same-owner coalescing.
    a, b, c, d = keys[0], keys[17], keys[31], keys[45]
    ops += [
        ["DEL", a, b, c, d],
        ["RENAME", a, a],                                      # missing self -> no such key
        ["SET", a, "self"], ["RENAME", a, a], ["GET", a],
        ["RENAMENX", a, a],
        ["SET", b, "old"], ["COPY", a, b], ["GET", b],
        ["COPY", a, b, "REPLACE"], ["GET", b],
        ["SET", c, "hit"], ["DEL", d],
        ["MSETNX", b, "would-change", c, "blocked", d, "would-create"],
        ["MGET", b, c, d],
        ["DEL", a, b, c, d], ["SADD", a, "x", "y", "z"], ["SADD", b, "y", "z", "q"],
        ["SET", c, "wrong-destination"],
        ["SINTERSTORE", c, a, b], ["SMEMBERS", c],
        ["SUNIONSTORE", c, a, b], ["SMEMBERS", c],
        ["SDIFFSTORE", c, a, b], ["SMEMBERS", c],
        ["KEYS", "xs:*"], ["KEYS", "xs:0?:*"], ["KEYS", "does-not-match-*"],
    ]
    return ops

def gen_scan(rng):
    """SCAN family. The diffed stream is the OPTION SURFACE plus the mutations that shape the
    tables; the completeness property itself cannot be byte-compared (cursor values and emission
    order are implementation-defined) and is checked in the `scan` property block below, which
    walks each cursor to completion on both servers and compares the resulting SETS.

    `SCAN 0 TYPE <unknown>` is deliberately absent: TomoKV rejects an unknown type name and Redis
    accepts it and returns an empty batch. That divergence is real but it belongs to the compat
    surface, not to cursor completeness, and folding it in here would only hide this suite's
    verdict behind an unrelated failure.
    """
    ops = []
    for i in range(400):
        ops.append(["SET", "s:str:%03d" % i, "v%d" % i])
    for i in range(60):
        ops.append(["HSET", "s:hash", "f%03d" % i, "v"])
        ops.append(["SADD", "s:set", "m%03d" % i])
        ops.append(["ZADD", "s:zset", str(i), "m%03d" % i])
        ops.append(["LPUSH", "s:list", "e%03d" % i])
    # Enough members to force every collection past its compact encoding into a real table, which
    # is the only encoding a cursor exists in.
    for i in range(400):
        ops.append(["HSET", "s:hbig", "f%04d" % i, "v" * (i % 70)])
        ops.append(["SADD", "s:sbig", "m%04d" % i])
        ops.append(["ZADD", "s:zbig", str(i * 1.5), "m%04d" % i])
    # Random churn so the two servers see identical tables with identical tombstone histories.
    for _ in range(2200):
        c = rng.randrange(10)
        n = rng.randrange(400)
        if   c < 3: ops.append(["SET", "s:str:%03d" % n, "r%d" % rng.randrange(1000)])
        elif c == 3: ops.append(["DEL", "s:str:%03d" % n])
        elif c == 4: ops.append(["HSET", "s:hbig", "f%04d" % n, "r"])
        elif c == 5: ops.append(["HDEL", "s:hbig", "f%04d" % n])
        elif c == 6: ops.append(["SADD", "s:sbig", "m%04d" % n])
        elif c == 7: ops.append(["SREM", "s:sbig", "m%04d" % n])
        elif c == 8: ops.append(["ZADD", "s:zbig", str(n), "m%04d" % n])
        else: ops.append(["ZREM", "s:zbig", "m%04d" % n])
    # Option surface: every reply here IS byte-comparable.
    ops += [
        ["SCAN", "abc"], ["SCAN", "-1"], ["SCAN", "0", "COUNT", "0"], ["SCAN", "0", "COUNT", "-1"],
        ["SCAN", "0", "COUNT", "abc"], ["SCAN", "0", "BADOPT"], ["SCAN", "0", "MATCH"],
        ["SCAN", "0", "COUNT"], ["SCAN", "0", "TYPE"],
        ["HSCAN", "s:hbig", "abc"], ["HSCAN", "s:hbig", "0", "COUNT", "0"],
        ["HSCAN", "s:hbig", "0", "BADOPT"], ["HSCAN", "s:missing", "0"],
        ["HSCAN", "s:missing", "0", "NOVALUES"], ["HSCAN", "s:hbig", "0", "NOVALUES", "BADOPT"],
        ["SSCAN", "s:sbig", "abc"], ["SSCAN", "s:sbig", "0", "COUNT", "0"],
        ["SSCAN", "s:missing", "0"], ["SSCAN", "s:sbig", "0", "MATCH"],
        ["ZSCAN", "s:zbig", "abc"], ["ZSCAN", "s:zbig", "0", "COUNT", "0"],
        ["ZSCAN", "s:missing", "0"], ["ZSCAN", "s:zbig", "0", "BADOPT"],
        # WRONGTYPE is a reply shape, and it must not depend on which encoding the key holds.
        ["HSCAN", "s:sbig", "0"], ["SSCAN", "s:zbig", "0"], ["ZSCAN", "s:hbig", "0"],
        ["SSCAN", "s:list", "0"], ["HSCAN", "s:str:001", "0"],
        # A small collection answers in one call with cursor 0 on both servers.
        ["DEL", "s:tiny"], ["SADD", "s:tiny", "a", "b", "c"], ["SSCAN", "s:tiny", "0"],
        ["SSCAN", "s:tiny", "0", "COUNT", "1"], ["SSCAN", "s:tiny", "0", "MATCH", "a*"],
        ["DEL", "s:htiny"], ["HSET", "s:htiny", "a", "1", "b", "2"], ["HSCAN", "s:htiny", "0"],
        ["HSCAN", "s:htiny", "0", "NOVALUES"],
        ["DEL", "s:ztiny"], ["ZADD", "s:ztiny", "1", "a", "2", "b"], ["ZSCAN", "s:ztiny", "0"],
        ["ZSCAN", "s:ztiny", "0", "MATCH", "b"],
    ]
    return ops


def gen_multi(rng):
    # MULTI/EXEC against vanilla, over a key set spread across the whole router.  The bodies mix
    # MULTI-OWNER reads (MGET/EXISTS/TOUCH over many keys) with blind writes, because that is the
    # pair the in-EXEC read-cut lane (t-execiso) changed: a read inside EXEC now resolves at the
    # transaction's cut instead of at each fragment's own moment, and the transaction's own writes
    # must stay visible through the origin-conn overlay.  DISCARD, EXECABORT and empty-transaction
    # shapes are generated too.  Everything here has a deterministically ORDERED reply -- an EXEC
    # reply is compared byte-for-byte and normalize() cannot reach inside it to sort a set reply.
    #
    # RUN THIS AT --atomic 0.  At --atomic 1 the suite is red on UNFIXED HEAD as well as on any
    # later tree, for a pre-existing defect in the MVCC resolver that is not what this suite is
    # for: a transaction's own still-private candidate carries epoch 0, and the winner comparison
    # in atomic_resolve_internal ranks by epoch, so that candidate loses to any older COMMITTED
    # version of the same key.  A read after an EXEC write on the same key then answers from
    # before the transaction.  Root cause, evidence and reproducers: NOTES-EXECISO.md.
    #
    # Three families are deliberately NOT generated, each because of a separate pre-existing
    # divergence that is present on unfixed HEAD and is outside the lane that wrote this suite.
    # Each is listed with the scratchpad/execiso/narrow.py line that re-opens it:
    #   lists       RPUSH of a large element inside MULTI is lost   (dropped: lists absent below)
    #   string RMW  INCRBY/APPEND clone from a stale base           narrow.py P T S incrby,append
    #   same key twice in one transaction / one command             the `used` set + rng.sample
    keys = ["mx:%02d:%s" % (i, "".join(rng.choice("abcdef0123456789") for _ in range(38)))
            for i in range(24)]
    strkeys = keys
    values = ["", "v", "hello", "42", "-7", "value-" + "y" * 90]
    ops = []

    # Distinct keys within one command: a duplicated key inside a single DEL/MSET/MGET is its own
    # (pre-existing, mode-independent) divergence family in this tree and is not what a MULTI suite
    # is for -- tests/differ.py's `xshard` suite already generates duplicate-bearing forms for the
    # bare lane. See NOTES-EXECISO.md.
    def ks(n, pool=None): return rng.sample(pool or strkeys, min(n, len(pool or strkeys)))

    def pairs(n):
        out = []
        for key in ks(n): out += [key, rng.choice(values)]
        return out

    for key in strkeys: ops.append(["SET", key, rng.choice(values)])

    def make():
        c = rng.randrange(14)
        if c == 0: return ["MGET"] + ks(rng.randrange(2, 8))
        if c == 1: return ["MSET"] + pairs(rng.randrange(2, 6))
        if c == 2: return ["EXISTS"] + ks(rng.randrange(2, 8))
        if c == 3: return ["TOUCH"] + ks(rng.randrange(2, 8))
        if c == 4: return ["DEL"] + ks(rng.randrange(2, 6))
        if c == 5: return ["SET", rng.choice(strkeys), rng.choice(values)]
        if c == 6: return ["GET", rng.choice(strkeys)]
        if c == 7: return ["GETDEL", rng.choice(strkeys)]
        if c == 8: return ["SETNX", rng.choice(strkeys), rng.choice(values)]
        if c == 9: return ["STRLEN", rng.choice(strkeys)]
        if c == 10: return ["MSETNX"] + pairs(rng.randrange(2, 5))
        if c == 11: return ["GETSET", rng.choice(strkeys), rng.choice(values)]
        if c == 12: return ["TYPE", rng.choice(strkeys)]
        return ["GETRANGE", rng.choice(strkeys), "0", str(rng.randrange(0, 5))]

    def named(op):
        # Every generated form here is first_key=1 with step 1, except the MSET family (step 2)
        # and the option-free tails of GETRANGE/INCRBY/APPEND/LRANGE, which name exactly one key.
        head = op[0]
        if head in ("MSET", "MSETNX"): return set(op[1::2])
        if head in ("MGET", "EXISTS", "TOUCH", "DEL"): return set(op[1:])
        return {op[1]}

    def body(n, used):
        # NO KEY IS TOUCHED TWICE INSIDE ONE TRANSACTION.  Not a stylistic choice: a pre-existing
        # --atomic 1 defect in the MVCC resolver makes a transaction's own still-private candidate
        # (epoch 0) lose the winner comparison to any older COMMITTED version of the same key, so a
        # second touch of one key inside one EXEC answers from before the first.  It is present on
        # unfixed HEAD, it is in write-visibility code this lane deliberately does not change, and
        # it is written up with reproducers in NOTES-EXECISO.md.  Generating the overlap here would
        # make this suite permanently red for a defect that is not the one it exists to cover.
        # tests/execiso.py still locks read-your-own-in-transaction-write directly, on keys with no
        # prior MVCC entry, which is the arm this restriction would otherwise drop.
        out = []
        while len(out) < n:
            op = make()
            keys_named = named(op)
            if keys_named & used: continue
            used |= keys_named
            out.append(op)
        return out

    for _ in range(700):
        mode = rng.randrange(10)
        used = set()
        if mode == 0:
            # DISCARD must drop the queue and leave the keyspace untouched.
            ops.append(["MULTI"]); ops += body(rng.randrange(1, 5), used); ops.append(["DISCARD"])
        elif mode == 1:
            # A queue-time rejection must turn EXEC into EXECABORT on both servers.
            ops.append(["MULTI"]); ops += body(rng.randrange(0, 3), used)
            ops.append(["GET"])                       # wrong arity: rejected while queueing
            ops += body(rng.randrange(0, 3), used); ops.append(["EXEC"])
        elif mode == 2:
            ops.append(["MULTI"]); ops.append(["EXEC"])            # empty transaction
        else:
            ops.append(["MULTI"]); ops += body(rng.randrange(1, 7), used); ops.append(["EXEC"])
        # Bare traffic between transactions: read-after-write ACROSS transactions is covered here,
        # where the earlier write is committed and the resolver defect above cannot bite.
        ops += body(1, set())
    return ops


def gen_xmove(rng):
    """Element-mover-heavy stream: cross-key, same-key, empty, and WRONGTYPE transitions."""
    listkeys = ["xm:list:%02d:%s" % (i, "l" * (31 + i % 5)) for i in range(14)]
    setkeys = ["xm:set:%02d:%s" % (i, "s" * (33 + i % 7)) for i in range(14)]
    wrongkeys = ["xm:wrong:%02d:%s" % (i, "w" * 37) for i in range(6)]
    values = ["", "a", "bb", "value-7", "nul\x00value", "x" * 90]
    members = ["m%d" % i for i in range(24)] + ["", "nul\x00member", "y" * 85]
    ops = []

    for key in listkeys:
        ops.append(["RPUSH", key] + [rng.choice(values) for _ in range(rng.randrange(1, 7))])
    for key in setkeys:
        ops.append(["SADD", key] + rng.sample(members, rng.randrange(1, 7)))
    for key in wrongkeys:
        ops.append(["SET", key, rng.choice(values)])

    for _ in range(4200):
        choice = rng.randrange(24)
        if choice < 6:
            source = rng.choice(listkeys)
            destination = source if rng.randrange(8) == 0 else rng.choice(listkeys)
            ops.append(["LMOVE", source, destination, rng.choice(["LEFT", "RIGHT"]),
                        rng.choice(["LEFT", "RIGHT"])])
        elif choice < 9:
            source = rng.choice(listkeys)
            destination = source if rng.randrange(8) == 0 else rng.choice(listkeys)
            ops.append(["RPOPLPUSH", source, destination])
        elif choice == 9:
            ops.append([rng.choice(["LPUSH", "RPUSH"]), rng.choice(listkeys),
                        rng.choice(values)])
        elif choice == 10:
            ops.append([rng.choice(["LPOP", "RPOP"]), rng.choice(listkeys)])
        elif choice == 11:
            ops.append(["LRANGE", rng.choice(listkeys), "0", "-1"])
        elif choice < 17:
            source = rng.choice(setkeys)
            destination = source if rng.randrange(8) == 0 else rng.choice(setkeys)
            ops.append(["SMOVE", source, destination, rng.choice(members)])
        elif choice == 17:
            ops.append(["SADD", rng.choice(setkeys), rng.choice(members)])
        elif choice == 18:
            ops.append(["SREM", rng.choice(setkeys), rng.choice(members)])
        elif choice == 19:
            ops.append(["SMEMBERS", rng.choice(setkeys)])
        elif choice == 20:
            ops.append(["DEL", rng.choice(listkeys + setkeys)])
        elif choice == 21:
            ops.append(["LMOVE", rng.choice(listkeys), rng.choice(wrongkeys),
                        rng.choice(["LEFT", "RIGHT"]), rng.choice(["LEFT", "RIGHT"])])
        elif choice == 22:
            ops.append(["SMOVE", rng.choice(setkeys), rng.choice(wrongkeys),
                        rng.choice(members)])
        else:
            ops.append([rng.choice(["LLEN", "SCARD", "TYPE"]),
                        rng.choice(listkeys + setkeys)])

    same_list, same_set = listkeys[0], setkeys[0]
    source_list, destination_list = listkeys[1], listkeys[-1]
    source_set, destination_set = setkeys[1], setkeys[-1]
    ops += [
        ["DEL", same_list], ["RPUSH", same_list, "a", "b", "c"],
        ["LMOVE", same_list, same_list, "LEFT", "RIGHT"],
        ["RPOPLPUSH", same_list, same_list], ["LRANGE", same_list, "0", "-1"],
        ["DEL", same_set], ["SADD", same_set, "member"],
        ["SMOVE", same_set, same_set, "member"],
        ["SMOVE", same_set, same_set, "missing"], ["SMEMBERS", same_set],
        ["DEL", source_list, destination_list],
        ["LMOVE", source_list, destination_list, "LEFT", "RIGHT"],
        ["RPUSH", source_list, "only"],
        ["RPOPLPUSH", source_list, destination_list],
        ["EXISTS", source_list], ["LRANGE", destination_list, "0", "-1"],
        ["DEL", source_set, destination_set],
        ["SMOVE", source_set, destination_set, "member"],
        ["SADD", source_set, "member"], ["SMOVE", source_set, destination_set, "member"],
        ["EXISTS", source_set], ["SMEMBERS", destination_set],
        ["SET", wrongkeys[0], "wrong"],
        ["RPUSH", source_list, "kept"],
        ["LMOVE", source_list, wrongkeys[0], "LEFT", "RIGHT"],
        ["LRANGE", source_list, "0", "-1"],
        ["SADD", source_set, "kept"],
        ["SMOVE", source_set, wrongkeys[0], "kept"], ["SMEMBERS", source_set],
    ]
    return ops


def gen_servertail(rng):
    """LCS-heavy, plus the introspection replies that are genuinely byte-comparable.

    Threshold alignment is done in the suite preamble below, NOT here: the two servers spell their
    encoding knobs differently, so the same intent needs two different CONFIG SET commands and they
    cannot travel in the diffed op stream.

    Deliberately EXCLUDED, with reasons:
      - OBJECT ENCODING on strings of 45..192 bytes. Our embstr/raw boundary is kEmbedThreshold
        (192); redis's is 44. The names mean the same thing at different sizes.
      - OBJECT REFCOUNT. Redis reports INT_MAX for its shared small integers; we have no shared
        object table and always report 1.
      - MEMORY USAGE values, and COMMAND INFO flag/acl/key-spec arrays. Normalized in normalize().
    """
    alphabet = "abcdef"
    ops = []

    def rand_string(lo, hi):
        return "".join(rng.choice(alphabet) for _ in range(rng.randrange(lo, hi)))

    # Long, unrelated key names so the pair lands on different shards most of the time; the
    # repeated-key form exercises the same-shard local fast path.
    pairs = []
    for i in range(24):
        pairs.append(("st:a:%02d:%s" % (i, "q" * 34), "st:b:%02d:%s" % (i, "w" * 34)))
    for key_a, key_b in pairs:
        ops.append(["SET", key_a, rand_string(0, 40)])
        ops.append(["SET", key_b, rand_string(0, 40)])

    for _ in range(3600):
        c = rng.randrange(10)
        key_a, key_b = rng.choice(pairs)
        if c == 0:
            ops.append(["SET", key_a, rand_string(0, 45)])
        elif c == 1:
            ops.append(["SET", key_b, rand_string(0, 45)])
        elif c == 2:
            ops.append(["LCS", key_a, key_b])
        elif c == 3:
            ops.append(["LCS", key_a, key_b, "LEN"])
        elif c == 4:
            ops.append(["LCS", key_a, key_b, "IDX"])
        elif c == 5:
            ops.append(["LCS", key_a, key_b, "IDX", "WITHMATCHLEN"])
        elif c == 6:
            ops.append(["LCS", key_a, key_b, "IDX", "MINMATCHLEN",
                        str(rng.randrange(-2, 6)), "WITHMATCHLEN"])
        elif c == 7:
            ops.append(["LCS", key_a, key_a])           # same-shard local path
        elif c == 8:
            ops.append(rng.choice([["LCS", key_a, key_b, "LEN", "IDX"],
                                   ["LCS", key_a, key_b, "BOGUS"],
                                   ["LCS", key_a, key_b, "MINMATCHLEN"],
                                   ["LCS", key_a, key_b, "MINMATCHLEN", "abc"],
                                   ["LCS", key_a, "st:absent:%d" % rng.randrange(9)]]))
        else:
            ops.append(["SUBSTR", key_a, str(rng.randrange(-8, 8)), str(rng.randrange(-8, 8))])

    # OBJECT ENCODING across type mutations, restricted to shapes both servers agree on.
    ops.append(["SET", "st:enc:int", "42"])
    ops.append(["SET", "st:enc:short", "a" * 20])
    ops.append(["SET", "st:enc:long", "a" * 300])
    for name in ("st:enc:int", "st:enc:short", "st:enc:long"):
        ops.append(["OBJECT", "ENCODING", name])
    # APPEND leaves redis in `raw` regardless of the resulting length, because redis over-allocates
    # an appended string for future growth. We have no such growth reservation, so a 3-byte result
    # stays embstr. The TYPE is still comparable; the encoding is not, for the same embstr/raw
    # reason listed in the docstring.
    ops.append(["APPEND", "st:enc:int", "x"])
    ops.append(["TYPE", "st:enc:int"])
    ops.append(["OBJECT", "ENCODING", "st:enc:absent"])
    ops.append(["OBJECT", "HELP"])

    for key, add, small, big in (("st:enc:hash", "HSET", 3, 700),
                                 ("st:enc:set", "SADD", 3, 300),
                                 ("st:enc:zset", "ZADD", 3, 300),
                                 ("st:enc:list", "RPUSH", 3, 300)):
        ops.append(["DEL", key])
        for i in range(small):
            if add == "HSET": ops.append([add, key, "f%d" % i, "v%d" % i])
            elif add == "ZADD": ops.append([add, key, str(i), "m%d" % i])
            else: ops.append([add, key, "m%d" % i])
        ops.append(["OBJECT", "ENCODING", key])
        for i in range(small, big):
            if add == "HSET": ops.append([add, key, "f%d" % i, "v%d" % i])
            elif add == "ZADD": ops.append([add, key, str(i), "m%d" % i])
            else: ops.append([add, key, "m%d" % i])
        ops.append(["OBJECT", "ENCODING", key])
        ops.append(["TYPE", key])

    ops.append(["DEL", "st:enc:intset"])
    for i in range(20):
        ops.append(["SADD", "st:enc:intset", str(i)])
    ops.append(["OBJECT", "ENCODING", "st:enc:intset"])
    ops.append(["SADD", "st:enc:intset", "notanint"])
    ops.append(["OBJECT", "ENCODING", "st:enc:intset"])

    ops.append(["XADD", "st:enc:stream", "1-1", "f", "v"])
    ops.append(["OBJECT", "ENCODING", "st:enc:stream"])

    # Presence, not value (normalized): MEMORY USAGE must agree on hit vs miss.
    for name in ("st:enc:short", "st:enc:absent", "st:enc:hash", "st:enc:stream"):
        ops.append(["MEMORY", "USAGE", name])

    # COMMAND INFO shapes for a fixed list (normalized to name/arity/key-range).
    # `object` and `memory` are deliberately absent: redis reports a 0/0/0 key range on the
    # container and hangs the real key spec off its subcommands, while our registry row carries the
    # truthful argv[2] range because ACL, MULTI and the router all consume it. Ours is the more
    # informative answer and it is not going to be made wrong to match a byte.
    for name in ("get", "set", "mset", "del", "lcs", "substr", "ping", "subscribe",
                 "sort_ro", "getrange", "zadd", "hset", "sinterstore", "xadd"):
        ops.append(["COMMAND", "INFO", name])
    ops.append(["COMMAND", "GETKEYS", "MSET", "a", "1", "b", "2"])
    ops.append(["COMMAND", "GETKEYS", "GET", "k"])
    ops.append(["COMMAND", "GETKEYS", "LCS", "k1", "k2"])
    ops.append(["COMMAND", "GETKEYS", "PING"])
    ops.append(["COMMAND", "GETKEYS", "NOSUCHCOMMAND", "k"])

    # Scope A parity replies that are byte-identical by construction.
    ops.append(["ROLE"])
    ops.append(["WAIT", "0", "0"])
    ops.append(["WAIT", "0", "-1"])
    ops.append(["FAILOVER", "ABORT"])
    ops.append(["PFSELFTEST"])
    ops.append(["DEL", "st:sort"])
    for value in ("3", "1", "2", "10"):
        ops.append(["RPUSH", "st:sort", value])
    ops.append(["SORT_RO", "st:sort"])
    ops.append(["SORT_RO", "st:sort", "DESC"])
    ops.append(["SORT_RO", "st:sort", "LIMIT", "1", "2"])
    ops.append(["SORT_RO", "st:sort", "ALPHA"])
    ops.append(["SORT_RO", "st:sort", "STORE", "st:sortdst"])
    ops.append(["SORT_RO", "st:absent:sort"])
    return ops


def gen_bitmap(rng):
    # Long, unrelated key names make random BITOPs exercise both localfast and cross-shard paths.
    keys = ["bm:%02d:%s" % (i, "".join(rng.choice("abcdef0123456789") for _ in range(30)))
            for i in range(24)]
    ops = []
    values = [b"", b"\x00", b"\xff", b"\x80\x01", b"hello", b"12345",
              bytes(range(16)), b"\x00\xff\x55\xaa" * 8]
    def K(): return rng.choice(keys)
    def R(): return str(rng.randrange(-80, 96))

    for _ in range(4200):
        c = rng.randrange(16)
        if c in (0, 1, 2):
            ops.append(["SETBIT", K(), str(rng.randrange(0, 1024)), str(rng.randrange(2))])
        elif c in (3, 4):
            ops.append(["GETBIT", K(), str(rng.randrange(0, 1536))])
        elif c == 5:
            ops.append(["BITCOUNT", K()])
        elif c == 6:
            ops.append(["BITCOUNT", K(), R(), R()])
        elif c == 7:
            ops.append(["BITCOUNT", K(), R(), R(), rng.choice(["BYTE", "BIT"])])
        elif c == 8:
            ops.append(["BITPOS", K(), str(rng.randrange(2))])
        elif c == 9:
            ops.append(["BITPOS", K(), str(rng.randrange(2)), R()])
        elif c == 10:
            ops.append(["BITPOS", K(), str(rng.randrange(2)), R(), R()])
        elif c == 11:
            ops.append(["BITPOS", K(), str(rng.randrange(2)), R(), R(),
                        rng.choice(["BYTE", "BIT"])])
        elif c == 12:
            operation = rng.choice(["AND", "OR", "XOR"])
            ops.append(["BITOP", operation, K()] + [K() for _ in range(rng.randrange(1, 5))])
        elif c == 13:
            ops.append(["BITOP", "NOT", K(), K()])
        elif c == 14:
            ops.append([rng.choice(["SET", "APPEND"]), K(), rng.choice(values)])
        else:
            ops.append([rng.choice(["GET", "STRLEN", "DEL"]), K()])

    a, b, c, d, e = keys[:5]
    ops += [
        # MSB-first indexing, zero-filled growth, reads beyond the physical string.
        ["DEL", a], ["SETBIT", a, "0", "1"], ["SETBIT", a, "7", "1"],
        ["SETBIT", a, "15", "1"], ["SETBIT", a, "79", "1"],
        ["GETBIT", a, "0"], ["GETBIT", a, "1"], ["GETBIT", a, "79"],
        ["GETBIT", a, "80"], ["STRLEN", a], ["GET", a],

        # Negative clamping and BYTE versus BIT ranges, including partial edge bytes.
        ["SET", b, b"\xf0\x0f\x81"],
        ["BITCOUNT", b], ["BITCOUNT", b, "-2", "-1"],
        ["BITCOUNT", b, "-100", "100", "BYTE"],
        ["BITCOUNT", b, "3", "18", "BIT"],
        ["BITCOUNT", b, "-17", "-2", "BIT"],
        ["BITCOUNT", b, "-1", "-2", "BIT"],
        ["BITPOS", b, "1"], ["BITPOS", b, "0", "1"],
        ["BITPOS", b, "1", "4", "18", "BIT"],
        ["BITPOS", b, "0", "4", "18", "BIT"],
        ["BITPOS", b, "0", "0", "0", "BYTE"],
        ["BITPOS", b, "0", "99"],

        # Missing sources are empty, shorter inputs zero-extend, and an empty result deletes dest.
        ["SET", a, b"\xff\x0f\xaa"], ["SET", b, b"\x0f\xf0"], ["DEL", c, d, e],
        ["BITOP", "AND", c, a, b], ["GET", c], ["STRLEN", c],
        ["BITOP", "OR", d, a, b, e], ["GET", d],
        ["BITOP", "XOR", e, a, b], ["GET", e],
        ["BITOP", "NOT", c, b], ["GET", c],
        ["BITOP", "AND", d, "bitmap-missing-1", "bitmap-missing-2"],
        ["EXISTS", d], ["STRLEN", d],

        # Destination/source aliasing and ordinary string-command interoperability.
        ["SET", a, "hello"], ["APPEND", a, b"\x00\xff"], ["SETBIT", a, "9", "1"],
        ["GETRANGE", a, "0", "-1"], ["STRLEN", a], ["BITCOUNT", a],
        ["BITOP", "XOR", a, a, b], ["GET", a], ["GETBIT", a, "9"],
        ["SET", e, "12345"], ["SETBIT", e, "3", "0"], ["GET", e],
        ["APPEND", e, "tail"], ["BITPOS", e, "1"], ["GETRANGE", e, "0", "-1"],

        # Exact parser/type failures must not mutate the destination.
        ["BITOP", "NOT", c, a, b], ["BITOP", "NOPE", c, a],
        ["SETBIT", a, "-1", "1"], ["SETBIT", a, "1", "2"],
        ["SADD", "bitmap-wrongtype", "x"], ["SET", c, "keep"],
        ["BITOP", "OR", c, a, "bitmap-wrongtype"], ["GET", c],
    ]
    return ops

def gen_bitfield(rng):
    keys = ["bf:%02d:%s" % (i, "".join(rng.choice("abcdef0123456789") for _ in range(24)))
            for i in range(20)]
    types = ["u1", "u2", "u7", "u8", "u16", "u31", "u32", "u63",
             "i1", "i2", "i7", "i8", "i16", "i31", "i32", "i63", "i64"]
    values = ["-9223372036854775808", "-65537", "-257", "-129", "-1", "0", "1",
              "127", "255", "256", "65535", "9223372036854775807"]
    ops = []
    def K(): return rng.choice(keys)
    def T(): return rng.choice(types)
    def O(t):
        bits = int(t[1:])
        return ("#%d" % rng.randrange(0, 48)) if rng.randrange(3) == 0 \
            else str(rng.randrange(0, 48 * bits + 24))

    for _ in range(3200):
        choice = rng.randrange(18)
        key = K()
        type_name = T()
        offset = O(type_name)
        if choice < 4:
            ops.append(["BITFIELD", key, "GET", type_name, offset])
        elif choice < 8:
            ops.append(["BITFIELD", key, "SET", type_name, offset, rng.choice(values)])
        elif choice < 12:
            ops.append(["BITFIELD", key, "OVERFLOW", rng.choice(["WRAP", "SAT", "FAIL"]),
                        "INCRBY", type_name, offset, rng.choice(values)])
        elif choice == 12:
            second = T()
            ops.append(["BITFIELD", key,
                        "GET", type_name, offset,
                        "OVERFLOW", rng.choice(["WRAP", "SAT", "FAIL"]),
                        "INCRBY", second, O(second), rng.choice(values),
                        "GET", second, O(second)])
        elif choice == 13:
            ops.append(["BITFIELD_RO", key, "GET", type_name, offset])
        elif choice == 14:
            ops.append(["SETBIT", key, str(rng.randrange(0, 512)), str(rng.randrange(2))])
        elif choice == 15:
            ops.append(["GETBIT", key, str(rng.randrange(0, 768))])
        elif choice == 16:
            ops.append([rng.choice(["SET", "APPEND"]), key,
                        rng.choice([b"", b"12345", b"hello", b"\x00\xff\x80"])])
        else:
            ops.append([rng.choice(["GET", "STRLEN", "DEL"]), key])

    a, b, c, d = keys[:4]
    ops += [
        ["DEL", a, b, c, d],
        ["BITFIELD", a], ["BITFIELD", a, "OVERFLOW", "SAT"],
        ["BITFIELD", a, "GET", "u8", "0"], ["EXISTS", a],
        ["BITFIELD", a, "SET", "u8", "0", "255", "GET", "u8", "0",
         "INCRBY", "u8", "0", "1", "GET", "u8", "0"],
        ["BITFIELD", a, "OVERFLOW", "SAT", "INCRBY", "u8", "0", "-1",
         "OVERFLOW", "WRAP", "INCRBY", "u8", "0", "-999"],
        ["BITFIELD", b, "SET", "i8", "0", "127", "OVERFLOW", "WRAP",
         "INCRBY", "i8", "0", "1", "OVERFLOW", "SAT", "INCRBY", "i8", "0", "-1"],
        ["BITFIELD", b, "OVERFLOW", "FAIL", "SET", "i8", "0", "999",
         "GET", "i8", "0"],
        ["BITFIELD", c, "SET", "u4", "#2", "10", "GET", "u4", "#2"],
        ["STRLEN", c], ["GET", c],
        ["SET", d, "12345"], ["BITFIELD", d, "GET", "u8", "0"],
        ["SET", d, "v", "PX", "600000"], ["BITFIELD", d, "SET", "u8", "#4", "9"],
        ["PTTL", d],
        ["BITFIELD_RO", a, "GET", "u8", "0"],
        ["BITFIELD_RO", a, "GET", "u8", "0", "SET", "u8", "0", "1"],
        ["BITFIELD", a, "GET", "u64", "0"], ["BITFIELD", a, "GET", "i65", "0"],
        ["BITFIELD", a, "GET", "i8", "#1152921504606846976"],
        ["BITFIELD", a, "OVERFLOW", "NOPE"], ["BITFIELD", a, "GET", "u8"],
        ["SADD", "bf:wrongtype", "x"], ["BITFIELD", "bf:wrongtype"],
    ]
    return ops

def gen_hll(rng):
    keys = ["hll:%02d:%s" % (i, "".join(rng.choice("abcdef0123456789") for _ in range(30)))
            for i in range(18)]
    elements = ["e:%04d" % i for i in range(700)] + ["", "nul\x00byte", "\xff\x00binary"]
    ops = []

    # Random PFADD streams deliberately repeat both elements within one call and across calls.
    # GET/STRLEN make the HYLL bytes themselves part of the differential contract, not just counts.
    for _ in range(1800):
        key = rng.choice(keys)
        chosen = [rng.choice(elements) for _ in range(rng.randrange(1, 6))]
        if rng.randrange(4) == 0: chosen.append(chosen[0])
        ops.append(["PFADD", key] + chosen)
        action = rng.randrange(10)
        if action < 3: ops.append(["PFCOUNT", key])
        elif action == 3: ops.append(["PFCOUNT"] + [rng.choice(keys) for _ in range(rng.randrange(2, 6))])
        elif action == 4: ops.append(["STRLEN", key])
        elif action == 5: ops.append(["GET", key])

    sparse, dense = "hll:sparse", "hll:dense"
    ops += [
        ["DEL", sparse, dense],
        ["PFADD", sparse, "a", "b", "a", "c"], ["PFCOUNT", sparse],
        ["GET", sparse], ["STRLEN", sparse],
        ["PFADD", sparse, "a", "b", "c"], ["PFCOUNT", sparse], ["GET", sparse],
    ]

    # Cross the default 3000-byte sparse ceiling, then compare the fixed 12304-byte dense image.
    for base in range(0, 5000, 64):
        ops.append(["PFADD", dense] + ["dense:%05d" % i for i in range(base, min(base + 64, 5000))])
    ops += [["PFCOUNT", dense], ["STRLEN", dense], ["GET", dense]]

    # Overlapping sources include a pre-existing destination because Redis merges argv[1] too.
    dst, left, right = "hll:merge:dst", "hll:merge:left", "hll:merge:right"
    for base in range(0, 1000, 50):
        ops.append(["PFADD", left] + ["overlap:%04d" % i for i in range(base, base + 50)])
    for base in range(500, 1500, 50):
        ops.append(["PFADD", right] + ["overlap:%04d" % i for i in range(base, base + 50)])
    for base in range(1200, 1700, 50):
        ops.append(["PFADD", dst] + ["overlap:%04d" % i for i in range(base, base + 50)])
    ops += [
        ["PFCOUNT", left, right, dst], ["PFMERGE", dst, left, right],
        ["STRLEN", dst], ["GET", dst], ["PFCOUNT", dst],
        ["PFCOUNT", left, right, dst], ["STRLEN", dst], ["GET", dst],
        ["PFADD", "hll:small-left", "a", "b", "c"],
        ["PFADD", "hll:small-right", "b", "c", "d"],
        ["PFADD", "hll:small-dst", "d", "e"],
        ["PFMERGE", "hll:small-dst", "hll:small-left", "hll:small-right"],
        ["STRLEN", "hll:small-dst"], ["GET", "hll:small-dst"],
        ["PFCOUNT", "hll:small-dst"], ["GET", "hll:small-dst"],
        ["PFMERGE", "hll:empty-dst", "hll:missing-a", "hll:missing-b"],
        ["PFCOUNT", "hll:empty-dst"], ["GET", "hll:empty-dst"],
        ["PFMERGE", "hll:empty-dst"], ["GET", "hll:empty-dst"],
    ]

    # Distinguish a non-string WRONGTYPE, a string with a bad HLL header, and a valid header whose
    # sparse stream is corrupt. The invalid cache bit forces PFCOUNT to decode the corrupt stream.
    corrupt = b"HYLL\x01\x00\x00\x00" + b"\x00" * 7 + b"\x80" + b"\x00"
    ops += [
        ["SADD", "hll:set-type", "x"], ["PFCOUNT", "hll:set-type"],
        ["PFADD", "hll:set-type", "x"], ["PFMERGE", "hll:merge-type", "hll:set-type"],
        ["SET", "hll:bad", "not-a-hyperloglog"], ["PFCOUNT", "hll:bad"],
        ["PFADD", "hll:bad", "x"], ["PFMERGE", "hll:merge-bad", "hll:bad"],
        ["SET", "hll:int-bad", "42"], ["PFCOUNT", "hll:int-bad"],
        ["PFADD", "hll:int-bad", "x"], ["PFMERGE", "hll:merge-int-bad", "hll:int-bad"],
        ["SET", "hll:corrupt", corrupt], ["PFCOUNT", "hll:corrupt"],
        ["PFADD", "hll:corrupt", "x"], ["PFMERGE", "hll:merge-corrupt", "hll:corrupt"],
    ]
    return ops

def gen_cgaps(rng):
    # Container-gap commands deliberately use long unrelated names so their numkeys/STORE forms
    # exercise both scatter-v2 and same-owner coalescing across ordinary shard counts.
    keys = ["cg:%02d:%s" % (i, "".join(rng.choice("abcdef0123456789") for _ in range(34)))
            for i in range(48)]
    lists = keys[:14]
    zsets = keys[14:28]
    numeric = keys[28:38]
    alpha = keys[38:44]
    dests = keys[44:]
    nums = ["-10", "-2", "0", "1", "2", "10", "3.5", "1e2", "+4", "001"]
    words = ["a", "aa", "b", "z", "10", "2", "item-3", "item-20"]
    ops = []

    for key in lists:
        ops.append(["RPUSH", key] + [rng.choice(words) for _ in range(rng.randrange(1, 6))])
    for key in zsets:
        pairs = []
        for n in range(rng.randrange(1, 6)):
            pairs += [str(rng.randrange(-8, 9)), "zm-%d-%d" % (keys.index(key), n)]
        ops.append(["ZADD", key] + pairs)
    for key in numeric:
        ops.append([rng.choice(["RPUSH", "SADD"]), key] +
                   [rng.choice(nums) for _ in range(rng.randrange(1, 7))])
    for key in alpha:
        ops.append([rng.choice(["RPUSH", "SADD"]), key] +
                   [rng.choice(words) for _ in range(rng.randrange(1, 7))])

    for _ in range(3200):
        c = rng.randrange(18)
        if c == 0:
            ops.append(["LPOS", rng.choice(lists), rng.choice(words), "RANK",
                        str(rng.choice([-4, -2, -1, 1, 2, 4]))])
        elif c == 1:
            ops.append(["LPOS", rng.choice(lists), rng.choice(words), "RANK",
                        str(rng.choice([-3, -1, 1, 3])), "COUNT", str(rng.randrange(0, 5)),
                        "MAXLEN", str(rng.randrange(0, 8))])
        elif c == 2:
            chosen = [rng.choice(lists) for _ in range(rng.randrange(1, 6))]
            ops.append(["LMPOP", str(len(chosen))] + chosen +
                       [rng.choice(["LEFT", "RIGHT"]), "COUNT", str(rng.randrange(1, 7))])
        elif c == 3:
            chosen = [rng.choice(zsets) for _ in range(rng.randrange(1, 6))]
            ops.append(["ZMPOP", str(len(chosen))] + chosen +
                       [rng.choice(["MIN", "MAX"]), "COUNT", str(rng.randrange(1, 7))])
        elif c == 4:
            ops.append(["RPUSH", rng.choice(lists)] + [rng.choice(words) for _ in range(rng.randrange(1, 4))])
        elif c == 5:
            ops.append(["ZADD", rng.choice(zsets), str(rng.randrange(-20, 21)), rng.choice(words)])
        elif c == 6:
            ops.append(["ZRANGESTORE", rng.choice(dests), rng.choice(zsets),
                        str(rng.randrange(-6, 3)), str(rng.randrange(-2, 7))] +
                       (["REV"] if rng.randrange(2) else []))
        elif c == 7:
            ops.append(["ZRANGESTORE", rng.choice(dests), rng.choice(zsets),
                        rng.choice(["-inf", "(0", "2"]), rng.choice(["+inf", "10", "(8"]),
                        "BYSCORE"] + (["LIMIT", str(rng.randrange(-1, 4)),
                                       str(rng.randrange(-1, 5))] if rng.randrange(2) else []) +
                       (["REV"] if rng.randrange(2) else []))
        elif c == 8:
            ops.append(["SORT", rng.choice(numeric)] +
                       (["DESC"] if rng.randrange(2) else ["ASC"]) +
                       (["LIMIT", str(rng.randrange(-2, 5)), str(rng.randrange(-2, 6))]
                        if rng.randrange(2) else []))
        elif c == 9:
            ops.append(["SORT", rng.choice(alpha), "ALPHA", rng.choice(["ASC", "DESC"])])
        elif c == 10:
            ops.append(["SORT", rng.choice(numeric), "LIMIT", str(rng.randrange(-2, 5)),
                        str(rng.randrange(-2, 6)), "STORE", rng.choice(dests)])
        elif c == 11:
            ops.append(["SORT", rng.choice(alpha + zsets), "ALPHA", "STORE", rng.choice(dests),
                        rng.choice(["ASC", "DESC"])])
        elif c == 12: ops.append(["DEL", rng.choice(lists)])
        elif c == 13: ops.append(["DEL", rng.choice(zsets)])
        elif c == 14: ops.append(["LRANGE", rng.choice(dests), "0", "-1"])
        elif c == 15: ops.append(["ZRANGE", rng.choice(dests), "0", "-1", "WITHSCORES"])
        elif c == 16: ops.append(["TYPE", rng.choice(dests)])
        else: ops.append(["EXISTS", rng.choice(keys)])

    # Directed byte-exact edges requested by the container-gap mission.
    l0, l1, l2, lbig = lists[:4]
    z0, z1, z2, zbig = zsets[:4]
    d0, d1 = dests[:2]
    n0, a0 = numeric[0], alpha[0]
    ops += [
        ["DEL", l0, l1, l2], ["RPUSH", l0, "a", "x", "a", "y", "a"],
        ["LPOS", l0, "a", "RANK", "-1"],
        ["LPOS", l0, "a", "RANK", "-2", "COUNT", "0", "MAXLEN", "0"],
        ["LPOS", l0, "a", "RANK", "-2", "COUNT", "5", "MAXLEN", "2"],
        ["RPUSH", l1, "first", "second", "third"],
        ["LMPOP", "3", l2, l1, l0, "LEFT", "COUNT", "99"],
        ["LRANGE", l0, "0", "-1"], ["LRANGE", l1, "0", "-1"],
        ["DEL", l0, l1, l2], ["LMPOP", "3", l0, l1, l2, "RIGHT", "COUNT", "2"],
        ["LMPOP", "0", l0, "LEFT"], ["LMPOP", "1", l0, "LEFT", "COUNT", "0"],
        ["SET", l0, "wrong"], ["RPUSH", l1, "winner"],
        ["LMPOP", "2", l0, l1, "LEFT"], ["LMPOP", "2", l1, l0, "LEFT"],
        ["DEL", z0, z1, z2], ["ZADD", z1, "1", "one", "2", "two", "3", "three"],
        ["ZMPOP", "3", z0, z1, z2, "MAX", "COUNT", "99"],
        ["ZRANGE", z1, "0", "-1", "WITHSCORES"],
        ["DEL", z0, z1, z2], ["ZMPOP", "3", z0, z1, z2, "MIN", "COUNT", "2"],
        ["ZMPOP", "0", z0, "MIN"], ["ZMPOP", "1", z0, "MAX", "COUNT", "0"],
        ["SET", z0, "wrong"], ["ZADD", z1, "1", "winner"],
        ["ZMPOP", "2", z0, z1, "MIN"], ["ZMPOP", "2", z1, z0, "MIN"],
        ["DEL", lbig], ["RPUSH", lbig] +
            [("L%03d-" % i) + "x" * 72 for i in range(115)],
        ["LMPOP", "1", lbig, "RIGHT", "COUNT", "112"], ["LLEN", lbig],
        ["DEL", zbig], ["ZADD", zbig] +
            sum(([str(i), "Z%03d" % i] for i in range(200)), []),
        ["ZMPOP", "1", zbig, "MIN", "COUNT", "197"], ["ZCARD", zbig],

        ["DEL", z0, d0], ["ZADD", z0, "0", "a", "1", "b", "2", "c", "3", "d"],
        ["ZRANGESTORE", d0, z0, "1", "-2"], ["ZRANGE", d0, "0", "-1", "WITHSCORES"],
        ["ZRANGESTORE", d0, z0, "+inf", "-inf", "BYSCORE", "REV", "LIMIT", "0", "2"],
        ["ZRANGE", d0, "0", "-1", "WITHSCORES"],
        ["ZRANGESTORE", d0, z0, "9", "0"], ["EXISTS", d0],
        ["ZADD", z0, "0", "aa", "0", "ab", "0", "ba"],
        ["ZRANGESTORE", d0, z0, "+", "[aa", "BYLEX", "REV", "LIMIT", "0", "2"],
        ["ZRANGE", d0, "0", "-1", "WITHSCORES"],

        ["DEL", n0, a0, d0, d1], ["RPUSH", n0, "10", "2", "-1", "3.5"],
        ["SORT", n0], ["SORT", n0, "DESC", "LIMIT", "1", "2"],
        ["RPUSH", a0, "10", "2", "apple"], ["SORT", a0], ["SORT", a0, "ALPHA"],
        ["SET", d0, "wrong-type-destination"], ["SORT", a0, "ALPHA", "STORE", d0],
        ["TYPE", d0], ["LRANGE", d0, "0", "-1"],
        ["DEL", z2], ["ZADD", z2, "8", "10", "1", "2", "3", "-1"],
        ["SORT", z2], ["SORT", z2, "ALPHA", "DESC"],
        ["SET", d1, "preserve-on-error"], ["SORT", a0, "STORE", d1], ["GET", d1],
    ]
    return ops

def gen_script(rng):
    # Scripting surface: EVAL / EVALSHA / EVAL_RO / EVALSHA_RO / SCRIPT LOAD|EXISTS|FLUSH and the
    # FUNCTION library (FCALL / FCALL_RO / LIST / STATS).
    #
    # TWO STRUCTURAL LIMITS, both properties of TomoKV rather than of the suite:
    #   * numkeys is 0 or 1. A script declaring two keys is routed to ONE owner here, so a pair
    #     landing on different shards is a CROSSSLOT that vanilla Redis does not produce. The
    #     single-owner law is the design, not a gap the differ should paper over.
    #   * every redis.call names KEYS[i]. TomoKV enforces the declared range (Redis 7 only warns),
    #     because routing happened before execution.
    # Everything else — reply conversion, the error text including the " script: <sha>, on
    # @user_script:<line>." tail, the read-only gate, the function metadata — is byte-compared.
    keys = ["sc:%d" % i for i in range(24)]
    values = ["1", "2", "-3", "abc", "", "10", "3.5", "hello world"]

    def K():
        return rng.choice(keys)

    scripts = [
        "return 1",
        "return 'plain'",
        "return {1,2,3,'x'}",
        "return {ok='fine'}",
        "return {err='handmade'}",
        "return #KEYS",
        "return ARGV[1]",
        "return tostring(ARGV[1]) .. ':' .. tostring(#ARGV)",
        "return redis.call('GET', KEYS[1])",
        "return redis.call('SET', KEYS[1], ARGV[1])",
        "return redis.call('INCR', KEYS[1])",
        "return redis.call('APPEND', KEYS[1], ARGV[1])",
        "return redis.call('STRLEN', KEYS[1])",
        "return redis.call('EXISTS', KEYS[1])",
        "return redis.call('TYPE', KEYS[1])",
        "return redis.call('DEL', KEYS[1])",
        "return {redis.call('SET', KEYS[1], ARGV[1]), redis.call('GET', KEYS[1])}",
        "local v = redis.call('GET', KEYS[1]) if v then return v .. '!' else return false end",
        "local r = redis.pcall('INCR', KEYS[1]) if r.err then return r.err end return r",
        "return redis.call('LPUSH', KEYS[1], ARGV[1])",
        "return redis.call('LRANGE', KEYS[1], 0, -1)",
        "return redis.call('HSET', KEYS[1], 'f', ARGV[1])",
        "return redis.call('HGETALL', KEYS[1])",
        "return redis.call('ZADD', KEYS[1], 1, ARGV[1])",
        "return redis.call('ZSCORE', KEYS[1], ARGV[1])",
        "return redis.call('SADD', KEYS[1], ARGV[1])",
        "return redis.call('SCARD', KEYS[1])",
        "local a = 0 for i = 1, 20 do a = a + i end return a",
    ]
    keyless = ["return 1", "return 'plain'", "return {1,2,3,'x'}", "return {ok='fine'}",
               "return {err='handmade'}", "return ARGV[1]", "return #KEYS",
               "local a = 0 for i = 1, 20 do a = a + i end return a"]
    # Deterministic error paths. Their replies carry the sha and the source line, so a divergence
    # in either the message or the tail shows up as a diff.
    broken = ["return (", "return redis.call('NOSUCHCOMMAND')", "error('kaput')",
              "error({err='raised table'})", "return zzz_undefined",
              "local x = nil\nreturn x.field"]
    ro_writes = ["return redis.call('SET', KEYS[1], 'ro')",
                 "return redis.call('INCR', KEYS[1])",
                 "return redis.call('DEL', KEYS[1])",
                 "return redis.call('LPUSH', KEYS[1], 'ro')"]

    library = ("#!lua name=difflib\n"
               "redis.register_function('dget', function(keys, args)\n"
               "  return {redis.call('GET', keys[1]), #keys, #args}\n"
               "end)\n"
               "redis.register_function{function_name='dset',\n"
               "  callback=function(keys, args) return redis.call('SET', keys[1], args[1]) end,\n"
               "  description='diff writer'}\n"
               "redis.register_function{function_name='dro',\n"
               "  callback=function(keys, args) return redis.call('GET', keys[1]) end,\n"
               "  flags={'no-writes'}, description='diff reader'}\n"
               "redis.register_function{function_name='dcount',\n"
               "  callback=function(keys, args) return #args end, flags={'no-writes'}}\n")
    library2 = ("#!lua name=difflib2\n"
                "redis.register_function('decho', function(keys, args) return args[1] end)\n")
    functions = ["dget", "dset", "dro", "dcount"]

    def sha(text):
        return hashlib.sha1(text.encode()).hexdigest()

    ops = [["SCRIPT", "FLUSH"], ["FUNCTION", "FLUSH"],
           ["FUNCTION", "LOAD", library], ["FUNCTION", "LOAD", library2],
           ["FUNCTION", "LOAD", library], ["FUNCTION", "LOAD", "REPLACE", library],
           ["FUNCTION", "STATS"]]
    for key in keys:
        ops.append(["SET", key, rng.choice(values)])

    loaded = []
    for _ in range(4200):
        pick = rng.randrange(100)
        if pick < 20:
            src = rng.choice(scripts)
            ops.append(["EVAL", src, "1", K(), rng.choice(values)])
        elif pick < 26:
            src = rng.choice(keyless)
            ops.append(["EVAL", src, "0", rng.choice(values)])
        elif pick < 34:
            src = rng.choice(scripts)
            loaded.append(src)
            ops.append(["SCRIPT", "LOAD", src])
        elif pick < 44:
            src = rng.choice(loaded) if loaded else scripts[0]
            ops.append(["EVALSHA", sha(src), "1", K(), rng.choice(values)])
        elif pick < 50:
            wanted = [sha(rng.choice(scripts)) for _ in range(rng.randrange(1, 4))]
            ops.append(["SCRIPT", "EXISTS"] + wanted)
        elif pick < 58:
            ops.append(["EVAL_RO", rng.choice(scripts), "1", K(), rng.choice(values)])
        elif pick < 62:
            ops.append(["EVAL_RO", rng.choice(ro_writes), "1", K()])
        elif pick < 66:
            src = rng.choice(loaded) if loaded else scripts[0]
            ops.append(["EVALSHA_RO", sha(src), "1", K(), rng.choice(values)])
        elif pick < 72:
            ops.append(["EVAL", rng.choice(broken), "1", K()])
        elif pick < 82:
            name = rng.choice(functions)
            ops.append(["FCALL", name, "1", K(), rng.choice(values)])
        elif pick < 88:
            name = rng.choice(functions)
            ops.append(["FCALL_RO", name, "1", K(), rng.choice(values)])
        elif pick < 90:
            ops.append(["FCALL", "not_a_function", "1", K()])
        elif pick < 92:
            ops.append(["FUNCTION", "LIST"])
        elif pick < 94:
            ops.append(["FUNCTION", "LIST", "LIBRARYNAME", rng.choice(["difflib", "difflib2",
                                                                       "absent"])])
        elif pick < 95:
            ops.append(["FUNCTION", "LIST", "WITHCODE"])
        elif pick < 96:
            ops.append(["FUNCTION", "STATS"])
        elif pick < 97:
            loaded = []
            ops.append(["SCRIPT", "FLUSH", rng.choice(["SYNC", "ASYNC"])])
        else:
            key = K()
            ops.append(rng.choice([["GET", key], ["SET", key, rng.choice(values)],
                                   ["DEL", key], ["TYPE", key], ["STRLEN", key]]))
    # PHASE 2 -- SCRIPTS AGAINST A LIVE CROSS-SHARD ENGINE.
    #
    # Phase 1 above is entirely single-key, so on TomoKV it ran with `atomic_groups:0`: the epoch
    # MVCC engine never engaged and the leg proved nothing about scripts meeting it. The multi-key
    # commands below DO form real cross-shard groups over the very keys the scripts declare, and
    # they sit next to those scripts in the same pipeline chunk, so an activation's effects have to
    # survive alongside an in-flight group and be visible to the multi-key read that follows.
    # Appended rather than woven into the loop above on purpose: the phase-1 stream (and therefore
    # every recorded per-seed diff count) stays exactly what it was.
    #
    # Every command here is ordinary Redis, byte-comparable against the oracle; the sharding is the
    # target's private business.
    write_fail = ["redis.call('INCR', KEYS[1]) error('boom')",
                  "redis.call('SET', KEYS[1], 'made') error('boom')",
                  "redis.call('APPEND', KEYS[1], 'XY') return nosuchglobal",
                  "redis.call('DEL', KEYS[1]) error('boom')",
                  "redis.call('INCR', KEYS[1]) return redis.call('LPUSH', KEYS[1], 'x')",
                  "redis.call('SET', KEYS[1], ARGV[1]) return redis.call('GET', KEYS[1])"]
    for _ in range(700):
        a, b, c = K(), K(), K()
        pick = rng.randrange(6)
        if pick == 0:
            ops.append(["MSET", a, rng.choice(values), b, rng.choice(values)])
        elif pick == 1:
            ops.append(["EVAL", rng.choice(write_fail), "1", a, rng.choice(values)])
        elif pick == 2:
            ops.append(["MGET", a, b, c])
        elif pick == 3:
            ops.append(rng.choice([["DEL", a, b], ["UNLINK", a, c],
                                   ["EXISTS", a, b, c], ["TOUCH", a, b]]))
        elif pick == 4:
            ops.append(["FCALL", rng.choice(["dset", "dget"]), "1", a, rng.choice(values)])
        else:
            ops.append(rng.choice([["GET", a], ["STRLEN", a], ["TYPE", a],
                                   ["SET", a, rng.choice(values)]]))

    ops.append(["FUNCTION", "DELETE", "difflib2"])
    ops.append(["FUNCTION", "LIST"])
    ops.append(["FUNCTION", "FLUSH"])
    ops.append(["FUNCTION", "LIST"])
    ops.append(["SCRIPT", "FLUSH"])
    return ops

# Sharded pub/sub is stateful and has spontaneous delivery frames, so it cannot use the ordinary
# one-request/one-reply pipeline below. Keep its whole differential driver in one mergeable block.
def run_spubsub_differ(rng):
    import select

    tp, tpf = conn(TH, TP)
    op, opf = conn(OH, OP)
    tl, tlf = conn(TH, TP)
    ol, olf = conn(OH, OP)
    diffs = 0
    checks = 0

    def compare(label, target, oracle, unordered=False):
        nonlocal diffs, checks
        checks += 1
        if unordered:
            target = normalize("SMEMBERS", target)
            oracle = normalize("SMEMBERS", oracle)
        if target != oracle:
            diffs += 1
            if diffs <= 12:
                print("  DIFF %s\n    target: %r\n    oracle: %r" %
                      (label, target[:160], oracle[:160]))

    channels = ["spubsub:differ:%02d" % i for i in range(12)]
    subscribed = set(channels[:5])
    initial = ["SSUBSCRIBE"] + sorted(subscribed)
    tl.sendall(enc(initial)); ol.sendall(enc(initial))
    for index in range(len(subscribed)):
        compare("initial SSUBSCRIBE %d" % index, read_reply(tlf), read_reply(olf))

    # Randomized subscription changes, local receiver counts, deliveries, and introspection.
    for sequence in range(600):
        choice = rng.randrange(20)
        channel = rng.choice(channels)
        if choice < 12:
            message = "payload:%d:%d" % (sequence, rng.randrange(1000000))
            command = ["SPUBLISH", channel, message]
            tp.sendall(enc(command)); op.sendall(enc(command))
            target = read_reply(tpf); oracle = read_reply(opf)
            compare("SPUBLISH %d" % sequence, target, oracle)
            if channel in subscribed:
                compare("smessage %d" % sequence, read_reply(tlf), read_reply(olf))
        elif choice < 15:
            command = ["SSUBSCRIBE", channel]
            tl.sendall(enc(command)); ol.sendall(enc(command))
            compare("SSUBSCRIBE %d" % sequence, read_reply(tlf), read_reply(olf))
            subscribed.add(channel)
        elif choice < 18:
            command = ["SUNSUBSCRIBE", channel]
            tl.sendall(enc(command)); ol.sendall(enc(command))
            compare("SUNSUBSCRIBE %d" % sequence, read_reply(tlf), read_reply(olf))
            subscribed.discard(channel)
        elif choice == 18:
            names = [rng.choice(channels) for _ in range(3)]
            command = ["PUBSUB", "SHARDNUMSUB"] + names
            tp.sendall(enc(command)); op.sendall(enc(command))
            compare("SHARDNUMSUB %d" % sequence, read_reply(tpf), read_reply(opf))
        else:
            command = ["PUBSUB", "SHARDCHANNELS", "spubsub:differ:*"]
            tp.sendall(enc(command)); op.sendall(enc(command))
            compare("SHARDCHANNELS %d" % sequence, read_reply(tpf), read_reply(opf), True)

    # Same bytes in regular/shard/pattern namespaces must not cross in either direction.
    cross = channels[0]
    if cross not in subscribed:
        tl.sendall(enc(["SSUBSCRIBE", cross])); ol.sendall(enc(["SSUBSCRIBE", cross]))
        compare("cross SSUBSCRIBE", read_reply(tlf), read_reply(olf))
        subscribed.add(cross)
    tr, trf = conn(TH, TP); ore, oref = conn(OH, OP)
    tr.sendall(enc(["SUBSCRIBE", cross])); ore.sendall(enc(["SUBSCRIBE", cross]))
    compare("cross SUBSCRIBE", read_reply(trf), read_reply(oref))
    tp.sendall(enc(["SPUBLISH", cross, "shard-only"]))
    op.sendall(enc(["SPUBLISH", cross, "shard-only"]))
    compare("cross SPUBLISH", read_reply(tpf), read_reply(opf))
    compare("cross smessage", read_reply(tlf), read_reply(olf))
    target_ready = bool(select.select([tr], [], [], 0.15)[0])
    oracle_ready = bool(select.select([ore], [], [], 0.15)[0])
    compare("SPUBLISH regular silence", b":" + str(target_ready).encode(),
            b":" + str(oracle_ready).encode())
    if target_ready or oracle_ready:
        diffs += 1

    tp.sendall(enc(["PUBLISH", cross, "regular-only"]))
    op.sendall(enc(["PUBLISH", cross, "regular-only"]))
    compare("cross PUBLISH", read_reply(tpf), read_reply(opf))
    compare("cross message", read_reply(trf), read_reply(oref))
    target_ready = bool(select.select([tl], [], [], 0.15)[0])
    oracle_ready = bool(select.select([ol], [], [], 0.15)[0])
    compare("PUBLISH shard silence", b":" + str(target_ready).encode(),
            b":" + str(oracle_ready).encode())
    if target_ready or oracle_ready:
        diffs += 1

    pattern = "spubsub:differ:*"
    tpat, tpatf = conn(TH, TP); opat, opatf = conn(OH, OP)
    tpat.sendall(enc(["PSUBSCRIBE", pattern])); opat.sendall(enc(["PSUBSCRIBE", pattern]))
    compare("cross PSUBSCRIBE", read_reply(tpatf), read_reply(opatf))
    tp.sendall(enc(["SPUBLISH", cross, "no-pattern"]))
    op.sendall(enc(["SPUBLISH", cross, "no-pattern"]))
    compare("pattern SPUBLISH", read_reply(tpf), read_reply(opf))
    compare("pattern smessage", read_reply(tlf), read_reply(olf))
    target_ready = bool(select.select([tpat], [], [], 0.15)[0])
    oracle_ready = bool(select.select([opat], [], [], 0.15)[0])
    compare("SPUBLISH pattern silence", b":" + str(target_ready).encode(),
            b":" + str(oracle_ready).encode())
    if target_ready or oracle_ready:
        diffs += 1

    # No-argument unsubscribe order is dictionary-dependent; compare the frame multiset.
    tl.sendall(enc(["SUNSUBSCRIBE"])); ol.sendall(enc(["SUNSUBSCRIBE"]))
    frame_count = len(subscribed) if subscribed else 1
    target_frames = [parse_reply(read_reply(tlf)) for _ in range(frame_count)]
    oracle_frames = [parse_reply(read_reply(olf)) for _ in range(frame_count)]
    def normalize_unsubscribe_all(frames):
        labels = sorted(frame[0] for frame in frames)
        channels_seen = sorted(frame[1] if frame[1] is not None else b"<nil>" for frame in frames)
        counts = sorted(frame[2] for frame in frames)
        return repr((labels, channels_seen, counts)).encode()
    compare("SUNSUBSCRIBE all", normalize_unsubscribe_all(target_frames),
            normalize_unsubscribe_all(oracle_frames))

    for sock in (tp, op, tl, ol, tr, ore, tpat, opat): sock.close()
    print("DIFFER spubsub: %d checks, %d diffs -> %s" %
          (checks, diffs, "PASS" if diffs == 0 else "FAIL"))
    return 1 if diffs else 0

def run_fanout_differ(rng):
    # FANOUT differential: every delivered frame is byte-compared against Redis, in order, for a
    # mixed population of RESP2/RESP3, exact/pattern/shard subscribers.  This is the suite that
    # covers the encode-once blob (one encoding serving '*' and '>' headers), the `pmessage` tail
    # reuse, the per-owner delivery batch, and the two ordering contracts the design promises:
    #   (1) a pipelined burst on ONE channel arrives in publish order (its single home orders it);
    #   (2) one-at-a-time publishes across MANY channels arrive in publish order (a home queues its
    #       deliveries before it releases the reply, so the next publish cannot overtake them).
    # Frame counts come from a Python-side model, not from select(): a lost, extra or reordered
    # frame therefore misaligns the byte comparison immediately instead of being timed out.
    diffs = 0
    checks = 0

    def compare(label, target, oracle):
        nonlocal diffs, checks
        checks += 1
        if target != oracle:
            diffs += 1
            if diffs <= 12:
                print("  DIFF %s\n    target: %r\n    oracle: %r" %
                      (label, target[:200], oracle[:200]))

    def open_pair(resp3):
        pair = []
        for host, port in ((TH, TP), (OH, OP)):
            s = socket.create_connection((host, port), timeout=20)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            f = s.makefile("rb")
            if resp3:
                s.sendall(enc(["HELLO", "3"]))
                hello = read_reply(f)
                if not hello.startswith(b"%7\r\n"):
                    raise RuntimeError("HELLO 3 failed on %s:%d" % (host, port))
            pair.append((s, f))
        return pair

    CHANNELS = ["fan:d:%02d" % i for i in range(8)]
    SHARDS = ["fan:s:%02d" % i for i in range(4)]
    # Disjoint by construction: no channel matches two patterns, because the relative order of two
    # pmessage frames for one publish is dictionary order on both servers and is not a contract.
    PREFIXES = ["fan:d:0", "fan:d:1"]
    PATTERNS = [p + "*" for p in PREFIXES]

    publisher = open_pair(False)
    subs = []
    NSUB = 9
    for index in range(NSUB):
        (ts, tf), (os_, of) = open_pair(index % 3 == 2)
        state = {"t": ts, "tf": tf, "o": os_, "of": of, "resp3": index % 3 == 2,
                 "exact": set(), "patterns": set(), "shard": set()}
        exact = rng.sample(CHANNELS, rng.randrange(1, 4))
        for channel in exact:
            for sock in (ts, os_): sock.sendall(enc(["SUBSCRIBE", channel]))
            compare("SUBSCRIBE ack %d" % index, read_reply(tf), read_reply(of))
            state["exact"].add(channel)
        if index % 2 == 0:
            pattern = rng.choice(PATTERNS)
            for sock in (ts, os_): sock.sendall(enc(["PSUBSCRIBE", pattern]))
            compare("PSUBSCRIBE ack %d" % index, read_reply(tf), read_reply(of))
            state["patterns"].add(pattern)
        if index % 3 != 1:
            shard = rng.choice(SHARDS)
            for sock in (ts, os_): sock.sendall(enc(["SSUBSCRIBE", shard]))
            compare("SSUBSCRIBE ack %d" % index, read_reply(tf), read_reply(of))
            state["shard"].add(shard)
        subs.append(state)

    def frames_for(state, channel, shard):
        # Redis walks the exact index first and the pattern list second, and so do we.
        n = 0
        if shard:
            return 1 if channel in state["shard"] else 0
        if channel in state["exact"]: n += 1
        for pattern in state["patterns"]:
            if channel.startswith(pattern[:-1]): n += 1
        return n

    def drain(published):
        # `published` is the publish order: [(channel, shard), ...].
        for index, state in enumerate(subs):
            expected = sum(frames_for(state, channel, shard) for channel, shard in published)
            for frame in range(expected):
                compare("sub%d frame %d" % (index, frame),
                        read_reply(state["tf"]), read_reply(state["of"]))

    ROUNDS = 220
    for round_index in range(ROUNDS):
        mode = rng.randrange(10)
        published = []
        if mode < 5:
            # (1) pipelined burst on ONE channel -- ordering owned by that channel's single home.
            shard = rng.randrange(4) == 0
            channel = rng.choice(SHARDS if shard else CHANNELS)
            verb = "SPUBLISH" if shard else "PUBLISH"
            burst = rng.randrange(3, 26)
            payload = [enc([verb, channel, "r%d:%d" % (round_index, i)]) for i in range(burst)]
            blob = b"".join(payload)
            publisher[0][0].sendall(blob); publisher[1][0].sendall(blob)
            for i in range(burst):
                compare("%s burst %d/%d" % (verb, round_index, i),
                        read_reply(publisher[0][1]), read_reply(publisher[1][1]))
                published.append((channel, shard))
        elif mode < 9:
            # (2) one at a time across MANY channels -- ordering owned by the delivery fence.
            for step in range(rng.randrange(2, 8)):
                shard = rng.randrange(4) == 0
                channel = rng.choice(SHARDS if shard else CHANNELS)
                verb = "SPUBLISH" if shard else "PUBLISH"
                command = enc([verb, channel, "s%d:%d" % (round_index, step)])
                publisher[0][0].sendall(command); publisher[1][0].sendall(command)
                compare("%s seq %d/%d" % (verb, round_index, step),
                        read_reply(publisher[0][1]), read_reply(publisher[1][1]))
                published.append((channel, shard))
        else:
            # Subscription churn plus the full introspection surface.
            state = subs[rng.randrange(NSUB)]
            channel = rng.choice(CHANNELS)
            if channel in state["exact"]:
                for sock in (state["t"], state["o"]): sock.sendall(enc(["UNSUBSCRIBE", channel]))
                compare("UNSUBSCRIBE churn %d" % round_index,
                        read_reply(state["tf"]), read_reply(state["of"]))
                state["exact"].discard(channel)
            else:
                for sock in (state["t"], state["o"]): sock.sendall(enc(["SUBSCRIBE", channel]))
                compare("SUBSCRIBE churn %d" % round_index,
                        read_reply(state["tf"]), read_reply(state["of"]))
                state["exact"].add(channel)
            for command, unordered in (
                    (["PUBSUB", "NUMSUB"] + rng.sample(CHANNELS, 3), False),
                    (["PUBSUB", "NUMPAT"], False),
                    (["PUBSUB", "SHARDNUMSUB"] + rng.sample(SHARDS, 2), False),
                    (["PUBSUB", "CHANNELS", "fan:d:*"], True),
                    (["PUBSUB", "SHARDCHANNELS", "fan:s:*"], True)):
                publisher[0][0].sendall(enc(command)); publisher[1][0].sendall(enc(command))
                target = read_reply(publisher[0][1]); oracle = read_reply(publisher[1][1])
                if unordered:
                    target = normalize("SMEMBERS", target)
                    oracle = normalize("SMEMBERS", oracle)
                compare(" ".join(command[:3]), target, oracle)
        drain(published)

    # Sentinel sweep: every subscriber's NEXT frame must be this publish. Any frame either server
    # leaked earlier and we did not account for would sit ahead of it and show up right here.
    sentinel = CHANNELS[0]
    command = enc(["PUBLISH", sentinel, "sentinel-final"])
    publisher[0][0].sendall(command); publisher[1][0].sendall(command)
    compare("sentinel PUBLISH", read_reply(publisher[0][1]), read_reply(publisher[1][1]))
    for index, state in enumerate(subs):
        for frame in range(frames_for(state, sentinel, False)):
            target = read_reply(state["tf"]); oracle = read_reply(state["of"])
            compare("sentinel sub%d frame %d" % (index, frame), target, oracle)
            if b"sentinel-final" not in target:
                diffs += 1
                print("  DIFF sentinel sub%d saw a stale frame: %r" % (index, target[:120]))

    for state in subs:
        state["t"].close(); state["o"].close()
    publisher[0][0].close(); publisher[1][0].close()
    print("DIFFER fanout: %d checks, %d diffs -> %s" %
          (checks, diffs, "PASS" if diffs == 0 else "FAIL"))
    return 1 if diffs else 0


if SUITE == "fanout":
    sys.exit(run_fanout_differ(rng))
if SUITE == "spubsub":
    sys.exit(run_spubsub_differ(rng))
# Notification differential is structurally different from command/reply suites: each side needs
# a driver plus a pattern subscriber, and streams are compared at every known owner-side fire
# point. The oracle for this suite must be vanilla Redis (see SPEC-WAVEA §0.2).
def run_notify_suite(rng):
    tds, tdf = conn(TH, TP); ods, odf = conn(OH, OP)
    tls, tlf = conn(TH, TP); ols, olf = conn(OH, OP)
    for sock, file in ((tds, tdf), (ods, odf)):
        sock.sendall(enc(["CONFIG", "SET", "notify-keyspace-events", ""]))
        if read_reply(file)[:1] != b"+": raise RuntimeError("notification disable failed")
        sock.sendall(enc(["FLUSHALL"])); read_reply(file)
        sock.sendall(enc(["CONFIG", "SET", "notify-keyspace-events", "EA"]))
        if read_reply(file)[:1] != b"+": raise RuntimeError("notification enable failed")
    for sock, file in ((tls, tlf), (ols, olf)):
        sock.sendall(enc(["PSUBSCRIBE", "__keyevent@0__:*"]))
        read_reply(file)

    stream = []
    for i in range(160):
        stem = "nd:%d" % i
        choice = rng.randrange(10)
        if choice == 0:
            stream += [(["SET", stem, str(rng.randrange(1000))], 1)]
        elif choice == 1:
            stream += [(["RPUSH", stem, "a", "b"], 1), (["LPOP", stem, "2"], 2)]
        elif choice == 2:
            stream += [(["SADD", stem, "a"], 1), (["SREM", stem, "a"], 2)]
        elif choice == 3:
            stream += [(["HSET", stem, "f", "v"], 1), (["HDEL", stem, "f"], 2)]
        elif choice == 4:
            stream += [(["ZADD", stem, "1", "m"], 1), (["ZREM", stem, "m"], 2)]
        elif choice == 5:
            stream += [(["MSET", stem + ":a", "1", stem + ":z", "2"], 2),
                       (["DEL", stem + ":a", stem + ":z"], 2)]
        elif choice == 6:
            stream += [(["SET", stem, "v", "EX", "1000"], 2),
                       (["PERSIST", stem], 1)]
        elif choice == 7:
            stream += [(["SET", stem + ":a", "v"], 1),
                       (["RENAME", stem + ":a", stem + ":z"], 2)]
        elif choice == 8:
            # Redis 7.4 only publishes the empty-result del when an old destination existed;
            # pre-seed it so this differential arm has one event on both sides. The directed
            # battery separately enforces this spec's stronger nonexistent-destination arm.
            stream += [(["SET", stem, "old"], 1),
                       (["SINTERSTORE", stem, stem + ":none-a", stem + ":none-z"], 1)]
        else:
            stream += [(["XADD", stem, "1-0", "f", "v"], 1),
                       (["XADD", stem, "2-0", "f", "w"], 1),
                       (["XDEL", stem, "1-0"], 1),
                       (["XTRIM", stem, "MAXLEN", "=", "0"], 1)]

    diffs = 0
    events = 0
    for i, (op, count) in enumerate(stream):
        payload = enc(op)
        tds.sendall(payload); ods.sendall(payload)
        target_reply = read_reply(tdf); oracle_reply = read_reply(odf)
        if target_reply != oracle_reply:
            diffs += 1
            if diffs <= 12:
                print("  REPLY DIFF op %d %r\n    target: %r\n    oracle: %r" %
                      (i, op[:5], target_reply[:96], oracle_reply[:96]))
        for _ in range(count):
            try:
                target = parse_reply(read_reply(tlf))
            except TimeoutError:
                print("  TARGET TIMEOUT op %d %r expected_events=%d" % (i, op[:5], count))
                return diffs + 1
            try:
                oracle = parse_reply(read_reply(olf))
            except TimeoutError:
                print("  ORACLE TIMEOUT op %d %r expected_events=%d" % (i, op[:5], count))
                return diffs + 1
            target_event = target[2:4] if target and len(target) == 4 else target
            oracle_event = oracle[2:4] if oracle and len(oracle) == 4 else oracle
            events += 1
            if target_event != oracle_event:
                diffs += 1
                if diffs <= 12:
                    print("  EVENT DIFF op %d %r\n    target: %r\n    oracle: %r" %
                          (i, op[:5], target_event, oracle_event))
    for sock in (tds, ods):
        sock.sendall(enc(["CONFIG", "SET", "notify-keyspace-events", ""]))
    read_reply(tdf); read_reply(odf)
    for sock in (tds, ods, tls, ols): sock.close()
    print("DIFFER notify: %d ops, %d events, %d diffs -> %s" %
          (len(stream), events, diffs, "PASS" if diffs == 0 else "FAIL"))
    return diffs

if SUITE == "notify":
    sys.exit(1 if run_notify_suite(rng) else 0)

# DUMP payloads have multiple equally valid encodings (TomoKV intentionally emits the simple
# canonical RDB types), so byte-comparing the bulk strings would reject interoperability. This
# suite cross-RESTOREs each side's payload into the other side and then byte-compares full reads.
def run_wiredump_suite(rng):
    ts, tf = conn(TH, TP); os_, of = conn(OH, OP)

    def command(sock, file, args):
        sock.sendall(enc(args))
        return read_reply(file)

    def payload(reply):
        value = parse_reply(reply)
        return value if isinstance(value, bytes) else None

    def full_read(sock, file, kind, key):
        if kind == "string": op = ["GET", key]
        elif kind == "list": op = ["LRANGE", key, "0", "-1"]
        elif kind == "hash": op = ["HGETALL", key]
        elif kind == "set": op = ["SMEMBERS", key]
        else: op = ["ZRANGE", key, "0", "-1", "WITHSCORES"]
        return normalize(op[0], command(sock, file, op))

    definitions = [
        ("wd:string", "string", [["SET", "wd:string", "wire\x00value"]]),
        ("wd:string-lzf", "string", [["SET", "wd:string-lzf", "repeat-" * 800]]),
        ("wd:list", "list", [["RPUSH", "wd:list", "a", "2", "x" * 500]]),
        ("wd:list-large", "list", [["RPUSH", "wd:list-large", "q" * 10000]]),
        ("wd:hash", "hash", [["HSET", "wd:hash", "a", "1", "b", "value"]]),
        ("wd:hash-large", "hash", [["HSET", "wd:hash-large", "field", "x" * 1000]]),
        ("wd:set-int", "set", [["SADD", "wd:set-int", "-2", "1", "70000"]]),
        ("wd:set", "set", [["SADD", "wd:set", "a", "bb", "m" * 100]]),
        ("wd:zset", "zset", [["ZADD", "wd:zset", "-2", "lo", "1.5", "mid"]]),
        ("wd:zset-large", "zset", [["ZADD", "wd:zset-large", "3.25", "z" * 100]]),
    ]
    pairs = ((ts, tf), (os_, of))
    for sock, file in pairs:
        if command(sock, file, ["FLUSHALL"])[:1] != b"+":
            raise RuntimeError("wiredump FLUSHALL failed")
    diffs = 0
    checks = 0

    for _, _, setup in definitions:
        for operation in setup:
            replies = [command(sock, file, operation) for sock, file in pairs]
            if replies[0] != replies[1]:
                diffs += 1

    cached = []
    for key, kind, _ in definitions:
        target_dump = payload(command(ts, tf, ["DUMP", key]))
        oracle_dump = payload(command(os_, of, ["DUMP", key]))
        if target_dump is None or oracle_dump is None:
            raise RuntimeError("wiredump seed DUMP failed for %s" % key)
        cached.append((key, kind, target_dump, oracle_dump))

    for iteration in range(4200):
        key, kind, target_seed, oracle_seed = rng.choice(cached)
        action = rng.randrange(5)
        if action == 0:
            # Cross the freshly produced payloads. The restored values have the same TTL and full
            # content even though their legal wire representations differ.
            target_dump = payload(command(ts, tf, ["DUMP", key]))
            oracle_dump = payload(command(os_, of, ["DUMP", key]))
            if target_dump is None or oracle_dump is None:
                diffs += 1
                continue
            target_reply = command(ts, tf, ["RESTORE", "wd:cross", "600000",
                                             oracle_dump, "REPLACE"])
            oracle_reply = command(os_, of, ["RESTORE", "wd:cross", "600000",
                                              target_dump, "REPLACE"])
            if target_reply != oracle_reply or full_read(ts, tf, kind, "wd:cross") != \
                    full_read(os_, of, kind, "wd:cross"):
                diffs += 1
        elif action == 1:
            # Feed exactly the same randomly selected producer payload to both RESTORE parsers.
            wire = target_seed if rng.randrange(2) else oracle_seed
            options = ["REPLACE"]
            ttl = "600000"
            if rng.randrange(4) == 0:
                ttl = str(int(time.time() * 1000) + 600000)
                options.append("ABSTTL")
            target_reply = command(ts, tf, ["RESTORE", "wd:restore", ttl, wire] + options)
            oracle_reply = command(os_, of, ["RESTORE", "wd:restore", ttl, wire] + options)
            if target_reply != oracle_reply or full_read(ts, tf, kind, "wd:restore") != \
                    full_read(os_, of, kind, "wd:restore"):
                diffs += 1
        elif action == 2:
            target_reply = command(ts, tf, ["EXISTS", key])
            oracle_reply = command(os_, of, ["EXISTS", key])
            if target_reply != oracle_reply:
                diffs += 1
        elif action == 3:
            if full_read(ts, tf, kind, key) != full_read(os_, of, kind, key):
                diffs += 1
        else:
            # This arm is a negative control until the first restore and a live-TTL check after it.
            target_reply = normalize("PTTL", command(ts, tf, ["PTTL", "wd:restore"]))
            oracle_reply = normalize("PTTL", command(os_, of, ["PTTL", "wd:restore"]))
            if target_reply != oracle_reply:
                diffs += 1
        checks += 1
        if diffs and diffs <= 12:
            print("  WIREDUMP DIFF op %d action=%d key=%s" % (iteration, action, key))

    ts.close(); os_.close()
    print("DIFFER wiredump: %d ops, %d diffs -> %s" %
          (checks, diffs, "PASS" if diffs == 0 else "FAIL"))
    return diffs

if SUITE == "wiredump":
    sys.exit(1 if run_wiredump_suite(rng) else 0)

# ---- Lane F: CLIENT connection-control + TRACKING differential ---------------------------------
# Structurally different from the command/reply suites: replies depend on connection identity, and
# invalidation arrives as an out-of-band push. So the suite drives a fixed pair of connections per
# side, byte-compares every reply of an identity-independent grammar stream, and then compares the
# invalidation frames a tracking connection receives for an identical write script.
def run_climon_suite(rng):
    import select as _select
    diffs = 0
    checks = 0
    ts, tf = conn(TH, TP); os_, of = conn(OH, OP)
    for cs, cf in ((ts, tf), (os_, of)):
        cs.sendall(enc(["FLUSHALL"])); read_reply(cf)

    def both(args, label=None):
        nonlocal diffs, checks
        payload = enc(args)
        ts.sendall(payload); os_.sendall(payload)
        a = read_reply(tf); b = read_reply(of)
        checks += 1
        if a != b:
            diffs += 1
            if diffs <= 15:
                print("  DIFF %s %r\n    target: %r\n    oracle: %r" %
                      (label or "", args[:14], a[:160], b[:160]))
        return a

    # ---- grammar stream. Every command below has an identity-independent reply. --------------
    on_off = ["ON", "OFF", "on", "off", "garbage", ""]
    modes = ["WRITE", "ALL", "write", "GARBAGE"]
    prefixes = ["a", "ab", "abc", "b", "user:", "user:1", ""]
    grammar = []
    for _ in range(4200):
        c = rng.randrange(16)
        if c == 0:   grammar.append(["CLIENT", "NO-TOUCH", rng.choice(on_off)])
        elif c == 1: grammar.append(["CLIENT", "NO-EVICT", rng.choice(on_off)])
        elif c == 2: grammar.append(["CLIENT", "GETREDIR"])
        elif c == 3: grammar.append(["CLIENT", "TRACKINGINFO"])
        elif c == 4: grammar.append(["CLIENT", "TRACKING", rng.choice(["on", "off", "garbage"])])
        elif c == 5:
            args = ["CLIENT", "TRACKING", rng.choice(["on", "off"])]
            if rng.randrange(2): args.append("BCAST")
            for _ in range(rng.randrange(3)):
                args += ["PREFIX", rng.choice(prefixes)]
            if rng.randrange(3) == 0: args.append(rng.choice(["OPTIN", "OPTOUT", "NOLOOP"]))
            grammar.append(args)
        elif c == 6: grammar.append(["CLIENT", "CACHING", rng.choice(["yes", "no", "maybe"])])
        elif c == 7:
            grammar.append(["CLIENT", "TRACKING", "on", "REDIRECT",
                            rng.choice(["999999", "0", "abc", "-1"])])
        elif c == 8: grammar.append(["CLIENT", "UNBLOCK", rng.choice(["999999", "0", "notanint", "-5"])])
        elif c == 9:
            grammar.append(["CLIENT", "UNBLOCK", "999999",
                            rng.choice(["TIMEOUT", "ERROR", "GARBAGE"])])
        elif c == 10: grammar.append(["CLIENT", "PAUSE", rng.choice(["0", "abc", "-1", "99999999999999999999"])])
        elif c == 11: grammar.append(["CLIENT", "PAUSE", "0", rng.choice(modes)])
        elif c == 12: grammar.append(["CLIENT", "UNPAUSE"])
        elif c == 13: grammar.append(["CLIENT", "REPLY", rng.choice(["ON", "on", "garbage"])])
        elif c == 14:
            # arity errors: the per-subcommand wrong-number-of-arguments strings
            grammar.append(rng.choice([
                ["CLIENT", "NO-TOUCH"], ["CLIENT", "REPLY"], ["CLIENT", "UNPAUSE", "X"],
                ["CLIENT", "PAUSE"], ["CLIENT", "UNBLOCK"], ["CLIENT", "CACHING"],
                ["CLIENT", "GETREDIR", "X"], ["CLIENT", "TRACKINGINFO", "X"],
                ["CLIENT", "TRACKING"], ["CLIENT", "NO-EVICT"],
            ]))
        else: grammar.append(["CLIENT", "TRACKING", "off"])
    grammar.append(["CLIENT", "TRACKING", "off"])
    grammar.append(["CLIENT", "UNPAUSE"])
    for op in grammar:
        both(op, "grammar")

    # ---- invalidation stream. RESP3 tracking client + a writer, per side. --------------------
    tt, ttf = conn(TH, TP); ot, otf = conn(OH, OP)
    for cs, cf in ((tt, ttf), (ot, otf)):
        cs.sendall(enc(["HELLO", "3"])); read_reply(cf)
    tw, twf = conn(TH, TP); ow, owf = conn(OH, OP)

    # Out-of-band pushes can arrive interleaved with a command reply, and the two servers place
    # them at different points relative to it (redis emits the reply first; this server can emit
    # the push first when the connection was idle). So a reply read PARKS any push it runs into
    # and the round-level comparison consumes the parked frames -- the assertion is on the set of
    # invalidations produced by a round, which is the actual contract.
    parked = {"t": b"", "o": b""}

    def read_command_reply(file, side):
        while True:
            frame = read_reply(file)
            if frame[:1] == b">":
                parked[side] += frame
                continue
            return frame

    def track(args, label):
        nonlocal diffs, checks
        payload = enc(args)
        tt.sendall(payload); ot.sendall(payload)
        a = read_command_reply(ttf, "t"); b = read_command_reply(otf, "o")
        checks += 1
        if a != b:
            diffs += 1
            print("  DIFF track %s %r\n    target: %r\n    oracle: %r" % (label, args[:5], a, b))

    def write_both(args):
        payload = enc(args)
        tw.sendall(payload); ow.sendall(payload)
        read_reply(twf); read_reply(owf)

    def compare_pushes(label, wait=1.2):
        nonlocal diffs, checks
        checks += 1
        def collect(sock):
            deadline = time.time() + wait
            out = b""
            while True:
                left = deadline - time.time()
                if left <= 0: break
                if not _select.select([sock], [], [], left)[0]: break
                chunk = sock.recv(65536)
                if not chunk: break
                out += chunk
                deadline = time.time() + 0.2
            return out
        a = parked["t"] + collect(tt); b = parked["o"] + collect(ot)
        parked["t"] = parked["o"] = b""
        if a != b:
            diffs += 1
            print("  DIFF invalidation %s\n    target: %r\n    oracle: %r" % (label, a, b))

    track(["CLIENT", "TRACKING", "on"], "on")
    keys = ["ck:%d" % i for i in range(12)]
    for round_ in range(40):
        k = rng.choice(keys)
        mode = rng.randrange(5)
        if mode == 0:
            write_both(["SET", k, "v%d" % round_])
            track(["GET", k], "read")
            write_both(["SET", k, "w%d" % round_])
        elif mode == 1:
            write_both(["SET", k, "v"])
            track(["GET", k], "read")
            write_both(["DEL", k])
        elif mode == 2:
            track(["GET", k], "read-miss")
            write_both(["SET", k, "created"])
        elif mode == 3:
            track(["GET", k], "read")
            write_both(["GET", k])            # a read must never invalidate
        else:
            track(["GET", k], "read")
            write_both(["APPEND", k, "z"])
        compare_pushes("round %d mode %d" % (round_, mode))
    track(["CLIENT", "TRACKING", "off"], "off")

    # NOLOOP + BCAST behaviours, byte-compared
    track(["CLIENT", "TRACKING", "on", "NOLOOP"], "noloop on")
    track(["SET", "ck:loop", "1"], "self set")
    track(["GET", "ck:loop"], "self read")
    track(["SET", "ck:loop", "2"], "self set again")
    compare_pushes("noloop self-write")
    track(["GET", "ck:loop"], "self read 2")
    write_both(["SET", "ck:loop", "3"])
    compare_pushes("noloop other-write")
    track(["CLIENT", "TRACKING", "off"], "noloop off")

    track(["CLIENT", "TRACKING", "on", "BCAST", "PREFIX", "bx:"], "bcast on")
    for i in range(12):
        write_both(["SET", "bx:%d" % i, "v"])
        compare_pushes("bcast hit %d" % i)
        write_both(["SET", "zz:%d" % i, "v"])
        compare_pushes("bcast miss %d" % i)
    track(["CLIENT", "TRACKING", "off"], "bcast off")

    for sock in (ts, os_, tt, ot, tw, ow): sock.close()
    print("DIFFER climon: %d ops, %d diffs -> %s" %
          (checks, diffs, "PASS" if diffs == 0 else "FAIL"))
    return diffs

if SUITE == "climon":
    sys.exit(1 if run_climon_suite(rng) else 0)


# ---- Lane t-compatintro: routing/introspection/ACL/notification differential -----------------
# Identity-bearing CLIENT rows and asynchronous notification frames make this a custom driver.
# Deterministic replies are byte-compared; COMMAND inventory/metadata and CLIENT counters are
# compared at their documented semantic boundary, with the raw known differences recorded in
# NOTES-COMPATINTRO.md.
def run_compatintro_suite(rng):
    import select as _select

    diffs = 0
    checks = 0
    fired = {"getkeys": 0, "config_multi": 0, "client_rows": 0,
             "acl_mutations": 0, "notify_events": 0, "silence_controls": 0}
    ts, tf = conn(TH, TP); os_, of = conn(OH, OP)

    def mismatch(label, target, oracle):
        nonlocal diffs
        diffs += 1
        if diffs <= 18:
            print("  DIFF %s\n    target: %r\n    oracle: %r" %
                  (label, target[:280] if isinstance(target, bytes) else target,
                   oracle[:280] if isinstance(oracle, bytes) else oracle))

    def raw_command(sock, file, argv):
        sock.sendall(enc(argv))
        return read_reply(file)

    def both(argv, label=None):
        nonlocal checks
        target = raw_command(ts, tf, argv)
        oracle = raw_command(os_, of, argv)
        checks += 1
        if target != oracle:
            mismatch(label or " ".join(argv[:3]), target, oracle)
        return target, oracle

    def semantic(label, target, oracle):
        nonlocal checks
        checks += 1
        if target != oracle: mismatch(label, target, oracle)

    # Clean only state this suite owns. The servers may be long-lived across seeds.
    for sock, file in ((ts, tf), (os_, of)):
        raw_command(sock, file, ["CONFIG", "SET", "notify-keyspace-events", ""])
        raw_command(sock, file, ["FLUSHALL"])
        raw_command(sock, file, ["ACL", "DELUSER", "ci:diff", "ci:bad"])

    # COMMAND: randomized exact GETKEYS coverage, especially movable-key forms. ----------------
    def keys(n): return ["ci:k:%d" % rng.randrange(64) for _ in range(n)]

    def getkeys_case():
        choice = rng.randrange(25)
        n = rng.randrange(1, 5)
        ks = keys(n)
        if choice == 0: cmd = ["GET", ks[0]]
        elif choice == 1: cmd = ["MGET"] + ks
        elif choice == 2: cmd = ["ZADD", ks[0], "NX", "1", "m1", "2", "m2"]
        elif choice == 3: cmd = ["EVAL", "return 1", str(n)] + ks + ["arg"]
        elif choice == 4: cmd = ["EVALSHA", "0" * 40, str(n)] + ks + ["arg"]
        elif choice == 5: cmd = ["FCALL", "ci_fn", str(n)] + ks + ["arg"]
        elif choice == 6: cmd = ["XREAD", "COUNT", "2", "STREAMS"] + ks + ["0"] * n
        elif choice == 7:
            cmd = ["XREADGROUP", "GROUP", "g", "c", "COUNT", "2", "STREAMS"] + ks + [">"] * n
        elif choice == 8: cmd = ["LMPOP", str(n)] + ks + ["LEFT", "COUNT", "2"]
        elif choice == 9: cmd = ["BLMPOP", "0", str(n)] + ks + ["RIGHT", "COUNT", "2"]
        elif choice == 10: cmd = ["ZMPOP", str(n)] + ks + ["MIN", "COUNT", "2"]
        elif choice == 11: cmd = ["BZMPOP", "0", str(n)] + ks + ["MAX", "COUNT", "2"]
        elif choice == 12: cmd = ["SINTERCARD", str(n)] + ks + ["LIMIT", "1"]
        elif choice == 13: cmd = ["ZINTERCARD", str(n)] + ks + ["LIMIT", "1"]
        elif choice in (14, 15, 16):
            cmd = [rng.choice(["ZUNION", "ZINTER", "ZDIFF"]), str(n)] + ks
            if cmd[0] != "ZDIFF": cmd += ["WEIGHTS"] + ["1"] * n
        elif choice == 17:
            cmd = [rng.choice(["ZUNIONSTORE", "ZINTERSTORE", "ZDIFFSTORE"]),
                   "ci:dest", str(n)] + ks
        elif choice == 18:
            cmd = ["GEORADIUS", ks[0], "0", "0", "1", "km", "STORE", "ci:dest"]
        elif choice == 19:
            cmd = ["GEORADIUSBYMEMBER", ks[0], "m", "1", "km", "STOREDIST", "ci:dest"]
        elif choice == 20:
            cmd = ["SORT", ks[0], "BY", "weight:*", "GET", "object:*", "STORE", "ci:dest"]
        elif choice == 21: cmd = ["MEMORY", "USAGE", ks[0], "SAMPLES", "3"]
        elif choice == 22: cmd = ["BITOP", "AND", "ci:dest"] + ks
        elif choice == 23:
            cmd = ["MSET"] + sum(([key, "v"] for key in ks), [])
        else: cmd = ["RENAME", ks[0], "ci:dest"]
        return ["COMMAND", "GETKEYS"] + cmd

    for iteration in range(1550):
        argv = getkeys_case()
        both(argv, "GETKEYS randomized %d %s" % (iteration, argv[2]))
        fired["getkeys"] += 1

    directed_getkeys = [
        ["COMMAND", "GETKEYS", "EVAL", "return 1", "0", "not-a-key"],
        ["COMMAND", "GETKEYS", "EVAL", "return 1", "-1"],
        ["COMMAND", "GETKEYS", "LMPOP", "0", "k", "LEFT"],
        ["COMMAND", "GETKEYS", "ZMPOP", "garbage", "k", "MIN"],
        ["COMMAND", "GETKEYS", "GET"],
        ["COMMAND", "GETKEYS", "PING"],
    ]
    for iteration in range(150):
        both(rng.choice(directed_getkeys), "GETKEYS validation %d" % iteration)
    for iteration in range(180):
        ks = keys(rng.randrange(1, 5))
        both(["COMMAND", "GETKEYSANDFLAGS", "MGET"] + ks,
             "GETKEYSANDFLAGS readonly %d" % iteration)

    # Inventory order is dictionary/registry order. Compare the returned set and prove it fired.
    for args, label in ((["COMMAND", "LIST", "FILTERBY", "PATTERN", "*POP"], "LIST PATTERN"),
                        (["COMMAND", "LIST", "FILTERBY", "ACLCAT", "STRING"], "LIST ACLCAT")):
        target = parse_reply(raw_command(ts, tf, args))
        oracle = parse_reply(raw_command(os_, of, args))
        target_set = sorted(target) if isinstance(target, list) else target
        oracle_set = sorted(oracle) if isinstance(oracle, list) else oracle
        if not target_set or not oracle_set:
            mismatch(label + " non-vacuity", repr(target_set).encode(), repr(oracle_set).encode())
        semantic(label + " members", repr(target_set).encode(), repr(oracle_set).encode())
    both(["COMMAND", "LIST", "FILTERBY", "MODULE", "no-such-module"], "LIST MODULE empty")

    # COMMAND INFO's name/arity/legacy key range is the declared compatibility boundary.
    info = ["COMMAND", "INFO", "GET", "MGET", "ZADD", "not-a-command"]
    target = normalize_introspection("COMMAND", info, raw_command(ts, tf, info))
    oracle = normalize_introspection("COMMAND", info, raw_command(os_, of, info))
    semantic("COMMAND INFO routing fields", target, oracle)
    for sock, file, side in ((ts, tf, "target"), (os_, of, "oracle")):
        count = parse_reply(raw_command(sock, file, ["COMMAND", "COUNT"]))
        value = int(count[1:]) if isinstance(count, bytes) and count[:1] == b":" else 0
        if value < 200: mismatch("COMMAND COUNT %s positive" % side, str(value).encode(), b">=200")
    checks += 1

    # CONFIG: maps are order-independent, but every name and rendered value remains byte-exact. --
    config_names = ["save", "appendonly", "appendfsync", "maxmemory", "maxmemory-policy",
                    "maxmemory-samples", "maxclients", "timeout", "tcp-keepalive",
                    "client-output-buffer-limit", "notify-keyspace-events"]

    def normalized_config(reply):
        value = parse_reply(reply)
        if not isinstance(value, list) or len(value) % 2: return reply
        pairs = sorted((value[i], value[i + 1]) for i in range(0, len(value), 2))
        return repr(pairs).encode()

    def config_get(patterns, label):
        argv = ["CONFIG", "GET"] + patterns
        target = normalized_config(raw_command(ts, tf, argv))
        oracle = normalized_config(raw_command(os_, of, argv))
        semantic(label, target, oracle)
        if len(patterns) > 1: fired["config_multi"] += 1

    for iteration in range(1050):
        choice = rng.randrange(10)
        if choice < 6:
            count = rng.randrange(1, 4)
            names = rng.sample(config_names, count)
            config_get(names, "CONFIG GET %d" % iteration)
        elif choice < 8:
            timeout = str(rng.choice([0, 30, 60, 300]))
            keepalive = str(rng.choice([0, 60, 300]))
            both(["CONFIG", "SET", "timeout", timeout, "tcp-keepalive", keepalive],
                 "CONFIG SET multi %d" % iteration)
            config_get(["timeout", "tcp-keepalive"], "CONFIG SET verify %d" % iteration)
        elif choice == 8:
            # Negative control for all-or-nothing validation: the valid first pair must not apply.
            config_get(["timeout"], "CONFIG invalid before %d" % iteration)
            both(["CONFIG", "SET", "timeout", "17", "ci-no-such-knob", "x"],
                 "CONFIG invalid multi %d" % iteration)
            config_get(["timeout"], "CONFIG invalid after %d" % iteration)
        else:
            both(["CONFIG", "RESETSTAT"], "CONFIG RESETSTAT %d" % iteration)
    both(["CONFIG", "SET", "timeout", "0", "tcp-keepalive", "300"], "CONFIG restore")
    config_get(["no-such-config-*", "still-no-such-*"], "CONFIG unknown multi")

    # CLIENT: exact grammar plus normalized INFO/LIST field names and stable state values. --------
    client_fields_seen = None
    expected_name = ""
    no_evict = no_touch = False
    lib_name = lib_ver = ""

    def client_info_fields(raw):
        body = parse_reply(raw)
        if not isinstance(body, bytes): return [], {}
        if body.startswith(b"txt:"): body = body[4:]
        words = body.strip().split()
        pairs = [(word.split(b"=", 1)[0], word.split(b"=", 1)[1])
                 for word in words if b"=" in word]
        return [key for key, _ in pairs], dict(pairs)

    def verify_client_info(label):
        nonlocal client_fields_seen
        target_raw = raw_command(ts, tf, ["CLIENT", "INFO"])
        oracle_raw = raw_command(os_, of, ["CLIENT", "INFO"])
        tnames, tmap = client_info_fields(target_raw)
        onames, omap = client_info_fields(oracle_raw)
        semantic(label + " field order", repr(tnames).encode(), repr(onames).encode())
        stable = (b"name", b"flags", b"db", b"sub", b"psub", b"ssub", b"multi", b"watch",
                  b"events", b"user", b"redir", b"resp", b"lib-name", b"lib-ver")
        semantic(label + " stable values", repr([(key, tmap.get(key)) for key in stable]).encode(),
                 repr([(key, omap.get(key)) for key in stable]).encode())
        if len(tnames) < 31: mismatch(label + " non-vacuity", repr(tnames).encode(), b">=31 fields")
        client_fields_seen = tnames
        fired["client_rows"] += 1

    for iteration in range(950):
        choice = rng.randrange(12)
        if choice == 0:
            expected_name = "ci_%d" % rng.randrange(100000)
            both(["CLIENT", "SETNAME", expected_name], "CLIENT SETNAME %d" % iteration)
        elif choice == 1:
            target, oracle = both(["CLIENT", "GETNAME"], "CLIENT GETNAME %d" % iteration)
            wanted = b"$-1\r\n" if not expected_name else \
                     b"$%d\r\n%s\r\n" % (len(expected_name), expected_name.encode())
            if target != wanted or oracle != wanted: mismatch("CLIENT GETNAME model", target, wanted)
        elif choice == 2:
            no_evict = bool(rng.randrange(2))
            both(["CLIENT", "NO-EVICT", "ON" if no_evict else "OFF"],
                 "CLIENT NO-EVICT %d" % iteration)
        elif choice == 3:
            no_touch = bool(rng.randrange(2))
            both(["CLIENT", "NO-TOUCH", "ON" if no_touch else "OFF"],
                 "CLIENT NO-TOUCH %d" % iteration)
        elif choice == 4:
            both(["CLIENT", "UNPAUSE"], "CLIENT UNPAUSE %d" % iteration)
        elif choice == 5:
            if rng.randrange(5) == 0:
                # Redis strings are binary-safe: NUL is accepted even though line/control
                # delimiters are rejected. This row caught TomoKV's former ch <= ' ' check.
                expected_name = "bad\x00name"
                both(["CLIENT", "SETNAME", expected_name], "CLIENT binary name %d" % iteration)
            else:
                bad = rng.choice(["bad name", "bad\nname", "bad\rname", "bad\tname", "bad\x7fname"])
                both(["CLIENT", "SETNAME", bad], "CLIENT invalid name %d" % iteration)
        elif choice == 6:
            lib_name = "lib%d" % rng.randrange(100)
            both(["CLIENT", "SETINFO", "LIB-NAME", lib_name], "CLIENT SETINFO name")
        elif choice == 7:
            lib_ver = "%d.%d" % (rng.randrange(10), rng.randrange(10))
            both(["CLIENT", "SETINFO", "LIB-VER", lib_ver], "CLIENT SETINFO version")
        elif choice in (8, 9):
            verify_client_info("CLIENT INFO %d" % iteration)
        elif choice == 10:
            tids = parse_reply(raw_command(ts, tf, ["CLIENT", "ID"]))
            oids = parse_reply(raw_command(os_, of, ["CLIENT", "ID"]))
            tid = int(tids[1:]) if isinstance(tids, bytes) and tids[:1] == b":" else 0
            oid = int(oids[1:]) if isinstance(oids, bytes) and oids[:1] == b":" else 0
            checks += 1
            if tid <= 0 or oid <= 0: mismatch("CLIENT ID positive", str(tid).encode(), str(oid).encode())
        else:
            # LIST is issued with each side's own id; compare one-row schema and stable state.
            tid_raw = parse_reply(raw_command(ts, tf, ["CLIENT", "ID"]))
            oid_raw = parse_reply(raw_command(os_, of, ["CLIENT", "ID"]))
            tid, oid = int(tid_raw[1:]), int(oid_raw[1:])
            traw = raw_command(ts, tf, ["CLIENT", "LIST", "ID", str(tid)])
            oraw = raw_command(os_, of, ["CLIENT", "LIST", "ID", str(oid)])
            tnames, tmap = client_info_fields(traw)
            onames, omap = client_info_fields(oraw)
            semantic("CLIENT LIST field order", repr(tnames).encode(), repr(onames).encode())
            stable = (b"name", b"flags", b"db", b"sub", b"psub", b"ssub", b"multi",
                      b"watch", b"user", b"redir", b"resp", b"lib-name", b"lib-ver")
            semantic("CLIENT LIST stable values",
                     repr([(key, tmap.get(key)) for key in stable]).encode(),
                     repr([(key, omap.get(key)) for key in stable]).encode())
            fired["client_rows"] += 1
    verify_client_info("CLIENT INFO final")
    if not client_fields_seen: mismatch("CLIENT INFO fired", b"none", b"fields")

    # ACL: exact user serialization, patterns, categories, and malformed-rule errors. ------------
    rules = [
        ["reset", "on", "nopass", "~ci:*", "&chan:*", "+get", "+set"],
        ["reset", "off", ">secret", "~*", "&*", "+@all"],
        ["reset", "on", "nopass", "resetkeys", "~a:*", "~b:*", "resetchannels",
         "&c:*", "+get", "+subscribe"],
    ]
    malformed = [["+nosuchcommand"], [">"], ["&"], ["~"], ["reset", "+@nosuchcategory"]]
    both(["ACL", "CAT"], "ACL CAT")
    both(["ACL", "WHOAMI"], "ACL WHOAMI")
    for iteration in range(1000):
        choice = rng.randrange(10)
        if choice < 3:
            both(["ACL", "SETUSER", "ci:diff"] + rng.choice(rules),
                 "ACL SETUSER %d" % iteration)
            fired["acl_mutations"] += 1
        elif choice == 3: both(["ACL", "GETUSER", "ci:diff"], "ACL GETUSER %d" % iteration)
        elif choice == 4: both(["ACL", "LIST"], "ACL LIST %d" % iteration)
        elif choice == 5: both(["ACL", "USERS"], "ACL USERS %d" % iteration)
        elif choice == 6:
            category = rng.choice(["string", "list", "set", "sortedset", "hash", "bitmap", "geo"])
            target = parse_reply(raw_command(ts, tf, ["ACL", "CAT", category]))
            oracle = parse_reply(raw_command(os_, of, ["ACL", "CAT", category]))
            semantic("ACL CAT %s" % category, repr(sorted(target)).encode(),
                     repr(sorted(oracle)).encode())
        elif choice == 7:
            both(["ACL", "SETUSER", "ci:bad"] + rng.choice(malformed),
                 "ACL malformed %d" % iteration)
        elif choice == 8:
            both(["ACL", "DELUSER", "ci:diff"], "ACL DELUSER %d" % iteration)
            fired["acl_mutations"] += 1
        else: both(["ACL", "GETUSER", "no-such-user"], "ACL missing user %d" % iteration)
    both(["ACL", "DELUSER", "ci:diff", "ci:bad"], "ACL cleanup")

    # Notification flags, routes, event names/order, and no-change controls. --------------------
    tks, tksf = conn(TH, TP); oks, oksf = conn(OH, OP)
    tke, tkef = conn(TH, TP); oke, okef = conn(OH, OP)
    subscribers = ((tks, tksf, "__keyspace@0__:ci:n:*"),
                   (oks, oksf, "__keyspace@0__:ci:n:*"),
                   (tke, tkef, "__keyevent@0__:*"),
                   (oke, okef, "__keyevent@0__:*"))
    for sock, file, pattern in subscribers:
        raw_command(sock, file, ["PSUBSCRIBE", pattern])

    def set_notify(flags):
        both(["CONFIG", "SET", "notify-keyspace-events", flags], "notify flags " + flags)

    def quiet(sock): return not _select.select([sock], [], [], 0.08)[0]

    def assert_silence(label, target_sock, oracle_sock):
        target_quiet = quiet(target_sock)
        oracle_quiet = quiet(oracle_sock)
        semantic(label, str(target_quiet).encode(), str(oracle_quiet).encode())
        if not target_quiet or not oracle_quiet:
            mismatch(label + " expected zero", str(target_quiet).encode(), b"True/True")
        fired["silence_controls"] += 1

    def notify_op(argv, keyspace_events, keyevent_events, label):
        both(argv, label + " reply")
        for index in range(keyspace_events):
            target = read_reply(tksf); oracle = read_reply(oksf)
            semantic(label + " keyspace event %d" % index, target, oracle)
            fired["notify_events"] += 1
        for index in range(keyevent_events):
            target = read_reply(tkef); oracle = read_reply(okef)
            semantic(label + " keyevent event %d" % index, target, oracle)
            fired["notify_events"] += 1

    set_notify("K$"); notify_op(["SET", "ci:n:string-k", "v"], 1, 0, "K string")
    assert_silence("K string keyevent silence", tke, oke)
    set_notify("E$"); notify_op(["SET", "ci:n:string-e", "v"], 0, 1, "E string")
    assert_silence("E string keyspace silence", tks, oks)
    set_notify("Eh"); notify_op(["HSET", "ci:n:hash", "f", "v"], 0, 1, "hash class")
    set_notify("El"); notify_op(["LPUSH", "ci:n:list", "v"], 0, 1, "list class")
    set_notify(""); notify_op(["SET", "ci:n:generic", "v"], 0, 0, "generic setup")
    set_notify("Eg"); notify_op(["DEL", "ci:n:generic"], 0, 1, "generic class")
    set_notify("Es"); notify_op(["SADD", "ci:n:set", "m"], 0, 1, "set class")
    notify_op(["SADD", "ci:n:set", "m"], 0, 0, "set no change")
    assert_silence("set no-change keyevent silence", tke, oke)
    set_notify("Ez"); notify_op(["ZADD", "ci:n:zset", "1", "m"], 0, 1, "zset class")
    set_notify("Et"); notify_op(["XADD", "ci:n:stream", "1-0", "f", "v"], 0, 1, "stream class")
    set_notify("Ex"); notify_op(["SET", "ci:n:expired", "v", "PX", "1"], 0, 0, "expired setup")
    time.sleep(0.02)
    notify_op(["GET", "ci:n:expired"], 0, 1, "expired class")
    set_notify("Em"); notify_op(["GET", "ci:n:missing"], 0, 1, "keymiss class")
    set_notify("En"); notify_op(["SET", "ci:n:new", "v"], 0, 1, "new class")
    set_notify("KEA")
    notify_op(["SET", "ci:n:ordered", "v", "EX", "1000"], 2, 2, "set-expire ordering")
    set_notify(""); notify_op(["SET", "ci:n:disabled", "v"], 0, 0, "disabled control")
    assert_silence("disabled keyspace silence", tks, oks)
    assert_silence("disabled keyevent silence", tke, oke)

    for sock in (tks, oks, tke, oke): sock.close()
    for sock in (ts, os_): sock.close()

    minimums = {"getkeys": 1500, "config_multi": 100, "client_rows": 50,
                "acl_mutations": 100, "notify_events": 10, "silence_controls": 5}
    for name, minimum in minimums.items():
        if fired[name] < minimum:
            mismatch("non-vacuity " + name, str(fired[name]).encode(), str(minimum).encode())
    print("DIFFER compatintro: %d checks, %d diffs -> %s (%s)" %
          (checks, diffs, "PASS" if diffs == 0 else "FAIL",
           ", ".join("%s=%d" % item for item in fired.items())))
    return diffs


if SUITE == "compatintro":
    sys.exit(1 if run_compatintro_suite(rng) else 0)


def run_s6fix_suite(rng):
    """A4-A7 differential properties plus 4,000 byte-compared mixed operations.

    RANDOMKEY values and LASTSAVE seconds cannot be compared pairwise, and TomoKV's outer SCAN
    cursor deliberately carries a shard id. Compare their observable properties instead; retain
    byte comparison for every deterministic validation reply and for the randomized command mix.
    Both servers must be purpose-booted with appendonly disabled so WAITAOF's [0,0] control is
    meaningful.
    """
    ts, tf = conn(TH, TP)
    os_, of = conn(OH, OP)
    diffs = 0
    logical_ops = 0

    def command(sock, file, argv):
        nonlocal logical_ops
        sock.sendall(enc(argv))
        logical_ops += 1
        return read_reply(file)

    def mismatch(label, target, oracle):
        nonlocal diffs
        diffs += 1
        if diffs <= 12:
            print("  DIFF %s\n    target: %r\n    oracle: %r" % (label, target, oracle))

    def compare(argv, label=None):
        target = command(ts, tf, argv)
        oracle = command(os_, of, argv)
        if target != oracle:
            mismatch(label or " ".join(argv[:4]), target, oracle)
        return target, oracle

    for sock, file in ((ts, tf), (os_, of)):
        if command(sock, file, ["FLUSHALL"])[:1] != b"+":
            raise RuntimeError("FLUSHALL failed on s6fix clean-slate")
        configured = parse_reply(command(sock, file, ["CONFIG", "GET", "appendonly"]))
        if configured != [b"appendonly", b"no"]:
            raise RuntimeError("s6fix differ must be purpose-booted with appendonly no")

    # A4: values are random, so compare reachability and the zero-valued controls on each side.
    expected = {("s6d:rk:%03d" % i).encode() for i in range(200)}
    for key in sorted(expected):
        compare(["SET", key.decode(), "v"], "A4 setup %s" % key.decode())
    counts = []
    for sock, file in ((ts, tf), (os_, of)):
        seen = {}
        for base in range(0, 20000, 64):
            width = min(64, 20000 - base)
            sock.sendall(enc(["RANDOMKEY"]) * width)
            logical_ops += width
            for _ in range(width):
                value = parse_reply(read_reply(file))
                seen[value] = seen.get(value, 0) + 1
        counts.append(seen)
    for side, seen in zip(("target", "oracle"), counts):
        missing = sorted(expected - set(seen))
        unexpected = sorted(set(seen) - expected - {None}, key=repr)
        nulls = seen.get(None, 0)
        if missing:
            mismatch("A4 %s missing" % side, missing, [])
        if unexpected:
            mismatch("A4 %s unexpected-key control" % side, unexpected, [])
        if nulls:
            mismatch("A4 %s null control" % side, nulls, 0)
        print("  A4 %s distinct=%d missing=%d unexpected=%d nulls=%d" %
              (side, len(set(seen) & expected), len(missing), len(unexpected), nulls))

    # A5: independently exhaust each server's cursor, then compare the complete key sets.
    for sock, file in ((ts, tf), (os_, of)):
        command(sock, file, ["FLUSHALL"])
        command(sock, file, ["XADD", "s6d:stream", "1-0", "f", "v"])
        command(sock, file, ["SET", "s6d:string", "v"])

    def scan_type(sock, file, type_name):
        cursor = b"0"
        keys = []
        calls = 0
        while True:
            raw = command(sock, file,
                          ["SCAN", cursor.decode(), "COUNT", "10000", "TYPE", type_name])
            calls += 1
            if raw[:1] == b"-":
                return raw, keys, calls
            parsed = parse_reply(raw)
            if not isinstance(parsed, list) or len(parsed) != 2:
                return b"invalid reply shape", keys, calls
            cursor, page = parsed
            keys.extend(page)
            if cursor == b"0":
                return None, keys, calls
            if calls > 300:
                return b"cursor did not terminate", keys, calls

    stream_results = [scan_type(sock, file, "stream") for sock, file in ((ts, tf), (os_, of))]
    unknown_results = [scan_type(sock, file, "not-a-real-type")
                       for sock, file in ((ts, tf), (os_, of))]
    for label, results, want in (("A5 stream", stream_results, [b"s6d:stream"]),
                                 ("A5 unknown control", unknown_results, [])):
        for side, (error, keys, calls) in zip(("target", "oracle"), results):
            if error is not None:
                mismatch("%s %s error" % (label, side), error, None)
            if sorted(keys) != want:
                mismatch("%s %s keys" % (label, side), sorted(keys), want)
            print("  %s %s calls=%d keys=%r" % (label, side, calls, sorted(keys)))

    # A6: exact seconds differ because the processes start separately; positivity and no-future
    # are the oracle properties, and LASTSAVE=0 on the old target fails them.
    now = int(time.time())
    for side, sock, file in (("target", ts, tf), ("oracle", os_, of)):
        raw = command(sock, file, ["LASTSAVE"])
        try:
            value = int(raw[1:-2]) if raw[:1] == b":" else -1
        except ValueError:
            value = -1
        if value <= 0:
            mismatch("A6 %s positive" % side, value, "> 0")
        future_control = int(value > now + 1)
        if future_control:
            mismatch("A6 %s future control" % side, future_control, 0)
        print("  A6 %s lastsave=%d future_control=%d" % (side, value, future_control))

    # A7 and the two cheap SCAN cosmetic errors are byte-comparable.
    compare(["WAITAOF", "0", "0", "0"], "A7 AOF-off zero control")
    compare(["WAITAOF", "0", "-1", "0"], "A7 negative numreplicas")
    compare(["WAITAOF", "0", "0", "-1"], "A7 negative-timeout control")
    compare(["SCAN", "0", "COUNT", "abc"], "SCAN COUNT abc")
    compare(["SCAN", "0", "NOVALUES"], "SCAN NOVALUES")

    # Stable randomized byte comparisons keep this a real >=4k differ, not a handful of directed
    # probes wearing a suite name. Validation rows recur throughout the mix.
    keys = ["s6d:mix:%02d" % i for i in range(32)]
    for iteration in range(4000):
        key = rng.choice(keys)
        choice = rng.randrange(8)
        if choice == 0:
            argv = ["SET", key, "v%d" % rng.randrange(1000)]
        elif choice == 1:
            argv = ["GET", key]
        elif choice == 2:
            argv = ["DEL", key]
        elif choice == 3:
            argv = ["EXISTS", key]
        elif choice == 4:
            argv = ["TYPE", key]
        elif choice == 5:
            argv = ["WAITAOF", "0", "-1", str(rng.randrange(3))]
        elif choice == 6:
            argv = ["SCAN", "0", "COUNT", "abc"]
        else:
            argv = ["SCAN", "0", "NOVALUES"]
        compare(argv, "mixed op %d %s" % (iteration, argv[0]))

    ts.close()
    os_.close()
    print("DIFFER s6fix: %d logical ops, %d diffs -> %s" %
          (logical_ops, diffs, "PASS" if diffs == 0 else "FAIL"))
    return diffs


if SUITE == "s6fix":
    sys.exit(1 if run_s6fix_suite(rng) else 0)

gens = {"string": gen_string, "list": gen_list, "set": gen_set, "zset": gen_zset,
        "hash": gen_hash, "hexpire": gen_hexpire, "xshard": gen_xshard,
        "xmove": gen_xmove, "bitmap": gen_bitmap,
        "hll": gen_hll, "bitfield": gen_bitfield, "cgaps": gen_cgaps, "stream": gen_stream,
        "script": gen_script,
        "streamgrp": gen_streamgrp,
        "zsetops": gen_zsetops, "geo": gen_geo,
        "scan": gen_scan, "multi": gen_multi,
        "servertail": gen_servertail}
if LIST_GENERATORS:
    print("\n".join(list(gens) + ["fanout", "spubsub", "notify", "wiredump", "climon",
                                   "compatintro", "s6fix"]))
    sys.exit(0)
ops = gens[SUITE](rng)

ts, tf = conn(TH, TP)
os_, of = conn(OH, OP)
# clean slates on BOTH sides: the oracle is long-lived across runs; residue there while the
# target boots fresh makes every op diff from op 0 (bit us on zset 2026-08-24). FLUSHALL (the
# target grew one with i-compat) rather than a DEL preamble: DEL-by-harvested-arg-1 missed any
# key a command names elsewhere (RENAME/STORE destinations live in arg 2+), which would re-open
# the residue trap for cross-shard suites. Replies are drained, NOT diffed.
for cs, cf in ((ts, tf), (os_, of)):
    cs.sendall(enc(["FLUSHALL"]))
    if read_reply(cf)[:1] != b"+": raise RuntimeError("FLUSHALL failed on clean-slate")
# OBJECT ENCODING is only comparable once both servers promote at the same sizes, and the two
# spell those knobs differently, so the alignment cannot ride in the diffed op stream. Replies are
# drained, NOT diffed -- the knob NAMES differ by design.
if SUITE == "servertail":
    alignment = {
        0: [["CONFIG", "SET", "hash-max-compact-entries", "128"],
            ["CONFIG", "SET", "hash-max-compact-value", "64"],
            ["CONFIG", "SET", "set-max-compact-entries", "128"],
            ["CONFIG", "SET", "set-max-compact-value", "64"],
            ["CONFIG", "SET", "zset-max-compact-entries", "128"],
            ["CONFIG", "SET", "zset-max-compact-value", "64"],
            ["CONFIG", "SET", "list-max-compact-entries", "128"],
            ["CONFIG", "SET", "list-max-compact-value", "64"]],
        1: [["CONFIG", "SET", "hash-max-listpack-entries", "128"],
            ["CONFIG", "SET", "hash-max-listpack-value", "64"],
            ["CONFIG", "SET", "set-max-listpack-entries", "128"],
            ["CONFIG", "SET", "set-max-listpack-value", "64"],
            ["CONFIG", "SET", "set-max-intset-entries", "128"],
            ["CONFIG", "SET", "zset-max-listpack-entries", "128"],
            ["CONFIG", "SET", "zset-max-listpack-value", "64"],
            ["CONFIG", "SET", "list-max-listpack-size", "128"]],
    }
    for side, (cs, cf) in enumerate(((ts, tf), (os_, of))):
        for command in alignment[side]:
            cs.sendall(enc(command))
            if read_reply(cf)[:1] != b"+":
                raise RuntimeError("encoding alignment failed: %r" % command)
diffs = 0
# HLL's directed promotion stream uses many-argument PFADDs and byte-sized GET oracles, and the
# cgaps suite carries wide numkeys forms; keep their pipeline chunks below the target's fixed
# read-buffer rollover so the suites test semantics, not an unrelated transport boundary.
BATCH = 16 if SUITE in ("hll", "cgaps") else 64
for i in range(0, len(ops), BATCH):
    chunk = ops[i:i + BATCH]
    payload = b"".join(enc(o) for o in chunk)
    ts.sendall(payload); os_.sendall(payload)
    for j, o in enumerate(chunk):
        try:
            a = normalize(o[0], read_reply(tf))
        except TimeoutError:
            print("  TIMEOUT target op %d: %r" % (i + j, o[:8]), flush=True)
            raise
        try:
            b = normalize(o[0], read_reply(of))
        except TimeoutError:
            print("  TIMEOUT oracle op %d: %r" % (i + j, o[:8]), flush=True)
            raise
        a = normalize_introspection(o[0].upper(), o, a)
        b = normalize_introspection(o[0].upper(), o, b)
        if a != b:
            diffs += 1
            if diffs <= 12:
                shown_a = a if o[0].upper() == "KEYS" else a[:256]
                shown_b = b if o[0].upper() == "KEYS" else b[:256]
                print("  DIFF op %d %r\n    target: %r\n    oracle: %r" %
                      (i + j, o[:4], shown_a, shown_b))
                # Scan-vs-point discriminator: when a KEYS listing disagrees, immediately probe
                # every disputed key with EXISTS and re-run KEYS on the target. A key that EXISTS
                # but was absent from the listing is a scan-visibility race; EXISTS==0 is loss;
                # a clean second KEYS marks the divergence transient.
                if o[0].upper() == "KEYS" and b":" in a and b":" in b:
                    seta = set(a.split(b"SORTED:")[-1].split(b","))
                    setb = set(b.split(b"SORTED:")[-1].split(b","))
                    # FRESH-connection probes only: probing on the differ's own pipelined
                    # connection desynchronizes the reply stream and self-inflicts a cascade
                    # (learned the hard way). A fresh conn also discriminates the mechanism:
                    # same-client RYOW-gate miss vs global publish-ordering gap.
                    try:
                        ps, pf = conn(TH, TP)
                        for miss in sorted((seta ^ setb))[:4]:
                            side = "target-missing" if miss in setb else "oracle-missing"
                            ps.sendall(enc(["EXISTS", miss.decode()]))
                            print("    PROBE(freshconn) %s %s EXISTS=%r" %
                                  (side, miss.decode()[:24], read_reply(pf)), flush=True)
                        ps.sendall(enc(["KEYS", "xs:*"]))
                        rekeys = normalize("KEYS", read_reply(pf))
                        print("    PROBE(freshconn) re-KEYS match-oracle=%r" % (rekeys == b),
                              flush=True)
                        ps.sendall(enc(["INFO", "STATS"]))
                        stats = read_reply(pf)
                        for want in (b"atomic_entries", b"atomic_pending_entries",
                                     b"atomic_promotions"):
                            row = [l for l in stats.split(b"\r\n") if l.startswith(want)]
                            if row:
                                print("    PROBE stat %s" % row[0].decode(), flush=True)
                        ps.close()
                    except Exception as probe_err:
                        print("    PROBE error: %r" % (probe_err,), flush=True)

if SUITE == "stream":
    # Auto IDs are clock-derived, and TomoKV intentionally refreshes its owner clock more
    # coarsely. Validate each server structurally and monotonically instead of hiding the entire
    # downstream command stream behind normalization.
    prior = [None, None]
    now_ms = int(time.time() * 1000)
    for iteration in range(8):
        for side, (sock, file) in enumerate(((ts, tf), (os_, of))):
            sock.sendall(enc(["XADD", "stream:auto", "*", "f", str(iteration)]))
            reply = read_reply(file)
            match = re.fullmatch(br"\$([0-9]+)\r\n([0-9]+)-([0-9]+)\r\n", reply)
            ok = match is not None
            if ok:
                ident = (int(match.group(2)), int(match.group(3)))
                ok = abs(ident[0] - now_ms) < 10000 and (prior[side] is None or ident > prior[side])
                prior[side] = ident
            if not ok:
                diffs += 1
                print("  AUTO-ID PROPERTY FAIL side=%s iteration=%d reply=%r" %
                      ("target" if side == 0 else "oracle", iteration, reply))

    # '~' is deliberately exact on TomoKV and node-approximate on Redis. The compatibility
    # contract is the property, not byte equality.
    for sock, file in ((ts, tf), (os_, of)):
        sock.sendall(enc(["DEL", "stream:approx"])); read_reply(file)
        for ident in range(1, 251):
            sock.sendall(enc(["XADD", "stream:approx", "%d-0" % ident, "f", "v"]))
            read_reply(file)
        sock.sendall(enc(["XTRIM", "stream:approx", "MAXLEN", "~", "25"]))
        read_reply(file)
        sock.sendall(enc(["XLEN", "stream:approx"]))
        length_reply = read_reply(file)
        try: length = int(length_reply[1:-2]) if length_reply[:1] == b":" else -1
        except ValueError: length = -1
        if length < 25:
            diffs += 1
            print("  APPROX-TRIM PROPERTY FAIL reply=%r" % length_reply)
if SUITE == "scan":
    # Cursor VALUES and emission ORDER are implementation-defined, so the walk cannot be byte
    # diffed. What is contractual, and what this checks, is the SET a completed walk yields: with
    # identical keyspaces on both servers it must be identical, at every COUNT. A COUNT small
    # enough to force many calls is the interesting one -- it is the number of resumptions, not
    # the number of keys, that exposes a cursor that cannot survive its own table.
    def read_value(file):
        line = file.readline()
        if not line: raise EOFError
        kind, body = line[:1], line[1:-2]
        if kind in b"+-:,#(_": return body
        if kind in b"$=!":
            n = int(body)
            return None if n == -1 else file.read(n + 2)[:-2]
        if kind in b"*~>":
            n = int(body)
            return None if n == -1 else [read_value(file) for _ in range(n)]
        if kind == b"%":
            return [read_value(file) for _ in range(int(body) * 2)]
        raise RuntimeError("scan property: unexpected reply %r" % line)

    def walk_to_end(sock, file, args, count, step):
        cursor, out, calls = b"0", [], 0
        while True:
            sock.sendall(enc(args + [cursor, "COUNT", str(count)]))
            reply = read_value(file)
            calls += 1
            cursor, batch = reply[0], reply[1]
            out.extend(batch[i] for i in range(0, len(batch), step))
            if cursor == b"0": break
            if calls > 200000:
                raise RuntimeError("%s cursor never returned to 0" % args[0])
        return sorted(set(out)), calls, len(out)

    for label, args, step in (("SCAN", ["SCAN"], 1),
                              ("HSCAN", ["HSCAN", "s:hbig"], 2),
                              ("SSCAN", ["SSCAN", "s:sbig"], 1),
                              ("ZSCAN", ["ZSCAN", "s:zbig"], 2)):
        for count in (7, 50, 400):
            tset, tcalls, temitted = walk_to_end(ts, tf, args, count, step)
            oset, ocalls, oemitted = walk_to_end(os_, of, args, count, step)
            if tset != oset:
                diffs += 1
                missing = [x for x in oset if x not in set(tset)]
                extra = [x for x in tset if x not in set(oset)]
                print("  SCAN-COMPLETENESS FAIL %s COUNT=%d: target %d unique in %d calls "
                      "(%d emitted), oracle %d unique in %d calls; MISSING from target %r; "
                      "EXTRA %r" % (label, count, len(tset), tcalls, temitted, len(oset), ocalls,
                                    missing[:6], extra[:6]))
            elif not tset:
                diffs += 1
                print("  SCAN-COMPLETENESS FAIL %s COUNT=%d: both sides empty, the check is "
                      "vacuous" % (label, count))

ts.close(); os_.close()
print("DIFFER %s: %d ops, %d diffs -> %s" % (SUITE, len(ops), diffs, "PASS" if diffs == 0 else "FAIL"))
sys.exit(1 if diffs else 0)
