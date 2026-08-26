#!/usr/bin/env python3
# DIFFERENTIAL battery: run one deterministic command stream against the TARGET (tomokv-cpp) and
# the ORACLE (the optimized Redis fork -- byte-exact redis semantics) and diff every reply.
#   python3 tests/differ.py <target_host> <target_port> <oracle_host> <oracle_port> <suite> [seed] [-3]
# Exit 0 iff zero diffs. Suites: string (more added per type lane).
import socket, sys, random, re, time, hashlib

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

gens = {"string": gen_string, "list": gen_list, "set": gen_set, "zset": gen_zset,
        "hash": gen_hash, "xshard": gen_xshard, "bitmap": gen_bitmap, "hll": gen_hll,
        "bitfield": gen_bitfield, "cgaps": gen_cgaps, "stream": gen_stream,
        "script": gen_script,
        "streamgrp": gen_streamgrp}
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
        if a != b:
            diffs += 1
            if diffs <= 12:
                shown_a = a if o[0].upper() == "KEYS" else a[:256]
                shown_b = b if o[0].upper() == "KEYS" else b[:256]
                print("  DIFF op %d %r\n    target: %r\n    oracle: %r" %
                      (i + j, o[:4], shown_a, shown_b))

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
ts.close(); os_.close()
print("DIFFER %s: %d ops, %d diffs -> %s" % (SUITE, len(ops), diffs, "PASS" if diffs == 0 else "FAIL"))
sys.exit(1 if diffs else 0)
