"""Boundary grid: drives every encoding/size threshold in this tree against the vanilla
oracle and byte-compares every reply.  Lane t-edgeenc.

usage: boundary_grid.py TARGET_PORT ORACLE_PORT [block ...]
       ZCMIN=<n> in the environment moves the zero-copy block to a different cutover.

Diffs are split into SEMANTIC (a real answer differs) and OBJECT-ENCODING-NAME (only the
encoding label differs -- three of those are documented deviations, see NOTES-EDGEENC.md).
HGETALL and the unordered set replies are normalized before comparison; ordering there is
not contractual on either server.
"""
import os, sys, socket

HOST = "127.0.0.1"
TP, OP = int(sys.argv[1]), int(sys.argv[2])
ONLY = set(sys.argv[3:])


def enc(args):
    out = [b"*%d\r\n" % len(args)]
    for a in args:
        if isinstance(a, str):
            a = a.encode()
        elif isinstance(a, int):
            a = str(a).encode()
        out.append(b"$%d\r\n%s\r\n" % (len(a), a))
    return b"".join(out)


def read_reply(f):
    line = f.readline()
    if not line:
        raise EOFError
    k = line[:1]
    if k in b"+-:,#(_":
        return line
    if k in b"$=!":
        n = int(line[1:])
        return line if n == -1 else line + f.read(n + 2)
    if k in b"*~>":
        n = int(line[1:])
        if n == -1:
            return line
        return line + b"".join(read_reply(f) for _ in range(n))
    if k == b"%":
        n = int(line[1:])
        return line + b"".join(read_reply(f) for _ in range(2 * n))
    raise RuntimeError("bad reply %r" % line)


def connect(p):
    s = socket.create_connection((HOST, p), timeout=30)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s, s.makefile("rb")


ts, tf = connect(TP)
os_, of = connect(OP)

ALIGN = {
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

for side, (s, f) in enumerate(((ts, tf), (os_, of))):
    s.sendall(enc(["FLUSHALL"]))
    read_reply(f)
    for c in ALIGN[side]:
        s.sendall(enc(c))
        r = read_reply(f)
        if r[:1] != b"+":
            raise RuntimeError("align failed %r -> %r" % (c, r))

DIFFS = []
ENCDIFFS = []
NOPS = 0

UNORDERED = {"HGETALL", "SMEMBERS", "HRANDFIELD", "SRANDMEMBER", "HKEYS", "HVALS", "KEYS"}


def parse(r):
    """Reply -> python structure, for normalization."""
    import io
    f = io.BytesIO(r)

    def rd():
        line = f.readline()
        k, body = line[:1], line[1:-2]
        if k in b"+-:,#(_":
            return (k, body)
        if k in b"$=!":
            n = int(body)
            return None if n == -1 else f.read(n + 2)[:-2]
        if k in b"*~>":
            n = int(body)
            return None if n == -1 else [rd() for _ in range(n)]
        if k == b"%":
            return [rd() for _ in range(2 * int(body))]
        raise RuntimeError("parse %r" % line)
    return rd()


def norm(cmd, r):
    c = cmd.upper()
    if c == "HGETALL":
        v = parse(r)
        if isinstance(v, list) and len(v) % 2 == 0:
            return repr(sorted((v[i], v[i + 1]) for i in range(0, len(v), 2))).encode()
    if c in UNORDERED:
        v = parse(r)
        if isinstance(v, list):
            return repr(sorted(map(repr, v))).encode()
    return r


def run(ops, label):
    """Send the op list to both, diff every reply."""
    global NOPS
    B = 32
    for i in range(0, len(ops), B):
        chunk = ops[i:i + B]
        p = b"".join(enc(o) for o in chunk)
        ts.sendall(p)
        os_.sendall(p)
        for j, o in enumerate(chunk):
            a, b = read_reply(tf), read_reply(of)
            NOPS += 1
            a, b = norm(o[0], a), norm(o[0], b)
            if a != b:
                if o[0].upper() == "OBJECT":
                    ENCDIFFS.append((label, i + j, o, a, b))
                else:
                    DIFFS.append((label, i + j, o, a, b))


def report(rows=None, title="SEMANTIC"):
    rows = DIFFS if rows is None else rows
    print("%s: ops=%d diffs=%d" % (title, NOPS, len(rows)))
    seen = {}
    for label, idx, o, a, b in rows:
        seen.setdefault(label, []).append((idx, o, a, b))
    for label, rows in seen.items():
        print("  %-34s %d diffs; first:" % (label, len(rows)))
        for idx, o, a, b in rows[:4]:
            oo = [x if isinstance(x, str) and len(x) < 40 else (
                  ("<%dB>" % len(x)) if isinstance(x, (str, bytes)) else x) for x in o]
            print("      op#%d %r\n        target=%r\n        oracle=%r" % (idx, oo, a[:160], b[:160]))


V = lambda n, c="x": (c * n)[:n] if n else ""


# ---------------------------------------------------------------- H1 compact transitions
def block_promote_demote():
    ops = []
    for entries in (1, 2, 15, 16, 17, 63, 64, 127, 128, 129, 200):
        for vlen in (1, 8, 63, 64, 65, 96, 191, 192, 193):
            k = "h:%d:%d" % (entries, vlen)
            ops.append(["DEL", k])
            for i in range(entries):
                ops.append(["HSET", k, "f%d" % i, V(vlen)])
                if i in (0, entries - 1):
                    ops.append(["OBJECT", "ENCODING", k])
            ops += [["HLEN", k], ["OBJECT", "ENCODING", k], ["HRANDFIELD", k, "0"]]
            # demote back down
            for i in range(entries):
                ops.append(["HDEL", k, "f%d" % i])
            ops += [["HLEN", k], ["EXISTS", k]]
    return ops


def block_promote_demote_set():
    ops = []
    for entries in (1, 15, 16, 17, 127, 128, 129):
        for vlen in (1, 63, 64, 65, 96, 192, 193):
            k = "s:%d:%d" % (entries, vlen)
            ops.append(["DEL", k])
            for i in range(entries):
                ops.append(["SADD", k, "m%d%s" % (i, V(max(0, vlen - 6)))])
            ops += [["SCARD", k], ["OBJECT", "ENCODING", k], ["SORT", k, "ALPHA"]]
            for i in range(entries):
                ops.append(["SREM", k, "m%d%s" % (i, V(max(0, vlen - 6)))])
            ops += [["SCARD", k], ["EXISTS", k]]
        # integer set crossing to generic and back
        k = "si:%d" % entries
        ops.append(["DEL", k])
        for i in range(entries):
            ops.append(["SADD", k, str(i * 1000)])
        ops += [["OBJECT", "ENCODING", k], ["SADD", k, "notanint"], ["OBJECT", "ENCODING", k],
                ["SREM", k, "notanint"], ["OBJECT", "ENCODING", k], ["SCARD", k],
                ["SORT", k, "ALPHA"]]
    return ops


def block_promote_demote_zset():
    ops = []
    for entries in (1, 15, 16, 17, 127, 128, 129):
        for vlen in (1, 63, 64, 65, 96, 192, 193):
            k = "z:%d:%d" % (entries, vlen)
            ops.append(["DEL", k])
            for i in range(entries):
                ops.append(["ZADD", k, str(i), "m%d%s" % (i, V(max(0, vlen - 6)))])
            ops += [["ZCARD", k], ["OBJECT", "ENCODING", k], ["ZRANGE", k, "0", "-1"],
                    ["ZRANGEBYSCORE", k, "-inf", "+inf"], ["ZRANK", k, "m0" + V(max(0, vlen - 6))]]
            ops.append(["ZREMRANGEBYRANK", k, "0", "-1"])
            ops += [["ZCARD", k], ["EXISTS", k]]
    return ops


def block_promote_demote_list():
    ops = []
    for entries in (1, 2, 15, 16, 17, 127, 128, 129):
        for vlen in (1, 8, 63, 64, 65, 95, 96, 97, 128, 191, 192, 193):
            k = "l:%d:%d" % (entries, vlen)
            ops.append(["DEL", k])
            for i in range(entries):
                ops.append(["RPUSH", k, V(vlen)])
            ops += [["LLEN", k], ["OBJECT", "ENCODING", k], ["LRANGE", k, "0", "-1"],
                    ["LINDEX", k, "0"], ["LINDEX", k, "-1"]]
            for i in range(entries):
                ops.append(["LPOP", k])
            ops += [["LLEN", k], ["EXISTS", k]]
            # rebuild and pop from the other end
            for i in range(entries):
                ops.append(["LPUSH", k, V(vlen)])
            ops += [["LLEN", k], ["OBJECT", "ENCODING", k]]
            for i in range(entries):
                ops.append(["RPOP", k])
            ops += [["LLEN", k], ["EXISTS", k]]
    return ops


# ---------------------------------------------------------------- H2 value size classes
def block_string_sizes():
    ops = []
    for n in list(range(0, 300)) + [511, 512, 513, 1023, 1024, 1025, 4095, 4096, 4097]:
        k = "vs%d" % n
        ops += [["SET", k, V(n)], ["GET", k], ["STRLEN", k], ["OBJECT", "ENCODING", k],
                ["APPEND", k, "Z"], ["GET", k], ["STRLEN", k], ["OBJECT", "ENCODING", k],
                ["GETRANGE", k, "0", "-1"], ["SETRANGE", k, str(max(0, n - 1)), "QQ"],
                ["GET", k], ["OBJECT", "ENCODING", k]]
    return ops


def block_list_element_sizes():
    ops = []
    for n in range(0, 300):
        k = "le%d" % (n % 8)
        ops += [["DEL", k], ["RPUSH", k, V(n, "a")], ["RPUSH", k, V(n, "b")],
                ["LRANGE", k, "0", "-1"], ["OBJECT", "ENCODING", k],
                ["LSET", k, "0", V(n + 1, "c")], ["LRANGE", k, "0", "-1"],
                ["LINSERT", k, "BEFORE", V(n, "b"), V(n, "d")], ["LRANGE", k, "0", "-1"],
                ["LREM", k, "0", V(n, "d")], ["LLEN", k], ["OBJECT", "ENCODING", k]]
    return ops


def block_hash_field_sizes():
    ops = []
    for n in range(0, 200):
        k = "hf%d" % (n % 8)
        ops += [["DEL", k], ["HSET", k, V(n, "f") or "e", V(n, "v")],
                ["HGET", k, V(n, "f") or "e"], ["HSTRLEN", k, V(n, "f") or "e"],
                ["OBJECT", "ENCODING", k],
                ["HSET", k, V(n, "f") or "e", V(n + 1, "w")],
                ["HGET", k, V(n, "f") or "e"], ["HLEN", k],
                ["HSET", k, "g", V(n, "u")], ["HGETALL", k], ["OBJECT", "ENCODING", k]]
    return ops


# ---------------------------------------------------------------- H3 zero-copy threshold
def block_zc_threshold():
    ops = []
    for n in (16000, 16256, 16352, 16383, 16384, 16385, 16400, 20000, 32768, 65536):
        k = "zc%d" % n
        ops += [["SET", k, V(n)], ["STRLEN", k], ["GETRANGE", k, "0", "15"],
                ["GETRANGE", k, str(n - 16), "-1"], ["OBJECT", "ENCODING", k]]
        ops.append(["GET", k])
        # grow across the threshold rather than writing it large in one shot
        g = "zg%d" % n
        ops += [["DEL", g], ["SET", g, V(16380)], ["GET", g], ["STRLEN", g]]
        ops += [["APPEND", g, V(n - 16380 if n > 16380 else 1)], ["STRLEN", g], ["GET", g]]
        ops += [["SETRANGE", g, str(n), "TAIL"], ["STRLEN", g], ["GET", g]]
    return ops


def block_segmented_send():
    """Small replies AFTER a large one on the same connection."""
    ops = []
    ops += [["SET", "seg:big", V(200000)], ["SET", "seg:small", "s"]]
    for i in range(20):
        ops += [["GET", "seg:big"], ["GET", "seg:small"], ["PING"], ["STRLEN", "seg:big"],
                ["ECHO", "after-big"], ["INCR", "seg:ctr"], ["GET", "seg:small"]]
    ops += [["RPUSH", "seg:list"] + [V(400) for _ in range(200)],
            ["LRANGE", "seg:list", "0", "-1"], ["PING"], ["GET", "seg:small"], ["LLEN", "seg:list"]]
    return ops


# ---------------------------------------------------------------- H6 integer encodings
def block_int_encoding():
    ops = []
    cands = ["0", "-0", "+0", "00", "007", "-007", "1", "-1", "+1", " 1", "1 ", "1.0", "1e3",
             "9223372036854775807", "9223372036854775806", "-9223372036854775808",
             "-9223372036854775807", "9223372036854775808", "-9223372036854775809",
             "18446744073709551615", "0x10", "0b1", "  ", "", "-", "+",
             "4294967295", "4294967296", "2147483647", "2147483648", "-2147483648",
             "65535", "65536", "127", "128", "255", "256", "32767", "32768",
             "99999999999999999999999999", "1" * 20, "-" + "1" * 20]
    for i, c in enumerate(cands):
        k = "iv%d" % i
        ops += [["SET", k, c], ["GET", k], ["OBJECT", "ENCODING", k], ["STRLEN", k],
                ["INCR", k], ["GET", k], ["OBJECT", "ENCODING", k],
                ["DECRBY", k, "3"], ["GET", k],
                ["INCRBYFLOAT", k, "1.5"], ["GET", k], ["OBJECT", "ENCODING", k],
                ["SET", k, c], ["APPEND", k, "9"], ["GET", k], ["OBJECT", "ENCODING", k],
                ["SET", k, c], ["SETRANGE", k, "0", "5"], ["GET", k], ["OBJECT", "ENCODING", k],
                ["SET", k, c], ["GETRANGE", k, "0", "0"], ["GETRANGE", k, "-1", "-1"],
                ["SET", k, c], ["SETRANGE", k, "20", "T"], ["GET", k], ["STRLEN", k],
                ["SET", k, c], ["GETDEL", k], ["EXISTS", k]]
        # integer members inside collections
        for t, add, dump in (("iset", ["SADD"], ["SORT", "ALPHA"]),
                             ("izset", ["ZADD", "1"], None)):
            kk = "%s%d" % (t, i)
            ops.append(["DEL", kk])
            if t == "iset":
                ops += [["SADD", kk, c], ["SCARD", kk], ["OBJECT", "ENCODING", kk],
                        ["SISMEMBER", kk, c], ["SORT", kk, "ALPHA"],
                        ["SADD", kk, "42"], ["OBJECT", "ENCODING", kk], ["SORT", kk, "ALPHA"]]
            else:
                ops += [["ZADD", kk, "1", c], ["ZSCORE", kk, c], ["OBJECT", "ENCODING", kk],
                        ["ZRANGE", kk, "0", "-1"]]
        kl = "ilist%d" % i
        ops += [["DEL", kl], ["RPUSH", kl, c], ["LRANGE", kl, "0", "-1"],
                ["OBJECT", "ENCODING", kl], ["LPOS", kl, c]]
        kh = "ihash%d" % i
        ops += [["DEL", kh], ["HSET", kh, c, c], ["HGET", kh, c], ["HGETALL", kh],
                ["HINCRBY", kh, c, "1"], ["HGET", kh, c], ["OBJECT", "ENCODING", kh]]
    return ops


# ---------------------------------------------------------------- H5 embedded->heap strings
def block_embed_transitions():
    ops = []
    for n in (0, 1, 44, 45, 63, 64, 95, 96, 127, 128, 190, 191, 192, 193, 194, 200, 255, 256):
        k = "em%d" % n
        ops += [["SET", k, V(n)], ["OBJECT", "ENCODING", k], ["STRLEN", k], ["GET", k],
                ["APPEND", k, "A"], ["OBJECT", "ENCODING", k], ["GET", k],
                ["SETRANGE", k, "0", "B"], ["GET", k],
                ["SET", k, V(n), "KEEPTTL"], ["GET", k],
                ["SET", k, V(n), "EX", "100"], ["GET", k], ["PERSIST", k],
                ["OBJECT", "ENCODING", k], ["GET", k],
                ["SETRANGE", k, str(n), V(1)], ["STRLEN", k], ["GET", k],
                ["GETSET", k, V(n + 1)], ["GET", k], ["OBJECT", "ENCODING", k],
                ["COPY", k, k + "c"], ["GET", k + "c"], ["OBJECT", "ENCODING", k + "c"]]
        # key length crossing the 255-byte KeyExt boundary
        for klen in (250, 254, 255, 256, 260):
            kk = ("K" * klen)[:klen] + str(n)
            ops += [["SET", kk, V(n)], ["GET", kk], ["STRLEN", kk],
                    ["APPEND", kk, "Z"], ["GET", kk], ["DEL", kk]]
    return ops


ZC = int(os.environ.get("ZCMIN", "16384"))


def block_zc_boundary():
    ops = []
    lo, hi = max(0, ZC - 8), ZC + 8
    for n in list(range(lo, hi)) + [ZC // 2, 2 * ZC, 1020, 1023, 1024, 1025, 1028]:
        k = "zk%d" % n
        ops += [["SET", k, V(n, "q")], ["GET", k], ["STRLEN", k],
                ["GETRANGE", k, "0", "-1"], ["GETRANGE", k, "1", "-2"],
                ["GETDEL", k], ["EXISTS", k],
                ["SET", k, V(n, "q")], ["GET", k],
                ["MGET", k, k, "nope"], ["MGET", k],
                ["COPY", k, k + "c"], ["GET", k + "c"], ["STRLEN", k + "c"],
                ["RENAME", k + "c", k + "r"], ["GET", k + "r"],
                ["SETRANGE", k, "0", "AB"], ["GET", k],
                ["APPEND", k, "TAIL"], ["GET", k], ["STRLEN", k],
                ["DEL", k, k + "r"]]
    # grow ACROSS the cutover instead of writing it large in one shot
    for start in (ZC - 4, ZC - 1, ZC, ZC + 1):
        k = "zg%d" % start
        ops += [["DEL", k], ["SET", k, V(start, "g")], ["GET", k]]
        for add in (1, 1, 1, 1, 1, 1, 1, 1):
            ops += [["APPEND", k, "Z" * add], ["GET", k], ["STRLEN", k]]
        ops += [["SETRANGE", k, str(start + 20), "TAIL"], ["GET", k], ["STRLEN", k]]
    # multi-key gather: the min(zc-min, 1024) cutover
    for n in (1000, 1023, 1024, 1025, 1100, 2048):
        keys = ["gk%d_%d" % (n, i) for i in range(6)]
        for i, k in enumerate(keys):
            ops.append(["SET", k, V(n, chr(97 + i))])
        ops += [["MGET"] + keys, ["MGET"] + keys[:1], ["MGET"] + keys + ["absent"],
                ["EXISTS"] + keys, ["TOUCH"] + keys,
                ["DEL"] + keys]
    return ops


def block_copy_move():
    ops = []
    sizes = (1, 63, 64, 65, 95, 96, 97, 191, 192, 193, 1024, 16383, 16384, 16385)
    for n in sizes:
        s, d = "cp%d" % n, "cp%d_d" % n
        ops += [["DEL", s, d], ["SET", s, V(n, "s")], ["COPY", s, d], ["GET", d],
                ["STRLEN", d], ["COPY", s, d], ["COPY", s, d, "REPLACE"], ["GET", d],
                ["RENAME", s, d], ["GET", d], ["EXISTS", s],
                ["SET", s, V(n, "t")], ["RENAMENX", s, d], ["GET", d],
                ["DEL", s, d]]
        # collection value-moving commands at the same sizes
        la, lb = "lm%d_a" % n, "lm%d_b" % n
        ops += [["DEL", la, lb], ["RPUSH", la, V(n, "1"), V(n, "2"), V(n, "3")],
                ["LMOVE", la, lb, "LEFT", "RIGHT"], ["LRANGE", la, "0", "-1"],
                ["LRANGE", lb, "0", "-1"],
                ["RPOPLPUSH", la, lb], ["LRANGE", lb, "0", "-1"],
                ["LMOVE", lb, lb, "LEFT", "RIGHT"], ["LRANGE", lb, "0", "-1"],
                ["DEL", la, lb]]
        sa, sb = "sm%d_a" % n, "sm%d_b" % n
        ops += [["DEL", sa, sb], ["SADD", sa, V(n, "m"), V(n, "n")],
                ["SMOVE", sa, sb, V(n, "m")], ["SMEMBERS", sa], ["SMEMBERS", sb],
                ["SINTERSTORE", sa + "i", sa, sa], ["SMEMBERS", sa + "i"],
                ["SUNIONSTORE", sa + "u", sa, sb], ["SMEMBERS", sa + "u"],
                ["SDIFFSTORE", sa + "d", sa, sb], ["SMEMBERS", sa + "d"],
                ["DEL", sa, sb, sa + "i", sa + "u", sa + "d"]]
        za, zb = "zm%d_a" % n, "zm%d_b" % n
        ops += [["DEL", za, zb], ["ZADD", za, "1", V(n, "p"), "2", V(n, "q")],
                ["ZRANGESTORE", zb, za, "0", "-1"], ["ZRANGE", zb, "0", "-1", "WITHSCORES"],
                ["ZUNIONSTORE", zb + "u", "2", za, zb], ["ZRANGE", zb + "u", "0", "-1"],
                ["ZDIFFSTORE", zb + "d", "2", za, zb], ["ZRANGE", zb + "d", "0", "-1"],
                ["DEL", za, zb, zb + "u", zb + "d"]]
        ha, hb = "hm%d_a" % n, "hm%d_b" % n
        ops += [["DEL", ha, hb], ["HSET", ha, "f", V(n, "h")], ["COPY", ha, hb],
                ["HGET", hb, "f"], ["HLEN", hb], ["DEL", ha, hb]]
    return ops


def block_sparse_setrange():
    ops = []
    for base in (0, 40, 44, 63, 64, 95, 96, 191, 192, 193, 1000, 16380):
        for off in (0, 1, base, base + 1, base + 100, 16380, 16384):
            k = "sr%d_%d" % (base, off)
            ops += [["DEL", k], ["SET", k, V(base, "b")] if base else ["SETRANGE", k, "0", ""],
                    ["SETRANGE", k, str(off), "PAD"], ["STRLEN", k], ["GET", k],
                    ["GETRANGE", k, "0", "-1"], ["SETRANGE", k, str(off), ""], ["STRLEN", k],
                    ["APPEND", k, "E"], ["STRLEN", k], ["GET", k], ["DEL", k]]
    return ops


def block_keylen_slack():
    """Embedded capacity depends on good_size() slack, which depends on KEY length.
    Same collection contents under many key lengths must behave identically."""
    ops = []
    for klen in list(range(1, 72)) + [100, 128, 200, 250, 253, 254, 255, 256, 257, 300, 511, 512]:
        k = ("K" * klen)[:klen]
        for vlen in (1, 8, 16, 32, 48, 60, 63, 64):
            ops += [["DEL", k]]
            for i in range(6):
                ops.append(["RPUSH", k, ("%d" % i) + V(vlen, "v")])
            ops += [["LRANGE", k, "0", "-1"], ["LLEN", k],
                    ["LSET", k, "0", V(vlen + 40, "w")], ["LRANGE", k, "0", "-1"],
                    ["LINSERT", k, "AFTER", V(vlen + 40, "w"), V(vlen + 40, "y")],
                    ["LRANGE", k, "0", "-1"], ["LLEN", k],
                    ["LREM", k, "0", V(vlen + 40, "y")], ["LRANGE", k, "0", "-1"],
                    ["LTRIM", k, "1", "3"], ["LRANGE", k, "0", "-1"], ["DEL", k]]
            ops += [["DEL", k]]
            for i in range(6):
                ops.append(["HSET", k, "f%d" % i, V(vlen, "v")])
            ops += [["HGETALL", k], ["HSET", k, "f0", V(vlen + 40, "w")], ["HGETALL", k],
                    ["HDEL", k, "f1"], ["HGETALL", k], ["HLEN", k], ["DEL", k]]
            ops += [["DEL", k]]
            for i in range(6):
                ops.append(["ZADD", k, str(i), "m%d%s" % (i, V(vlen, "v"))])
            ops += [["ZRANGE", k, "0", "-1", "WITHSCORES"],
                    ["ZADD", k, "9", "m0" + V(vlen, "v")],
                    ["ZRANGE", k, "0", "-1", "WITHSCORES"],
                    ["ZINCRBY", k, "3", "m1" + V(vlen, "v")],
                    ["ZRANGE", k, "0", "-1", "WITHSCORES"],
                    ["ZREMRANGEBYRANK", k, "0", "1"], ["ZRANGE", k, "0", "-1"], ["DEL", k]]
            ops += [["DEL", k]]
            for i in range(6):
                ops.append(["SADD", k, "m%d%s" % (i, V(vlen, "v"))])
            ops += [["SMEMBERS", k], ["SREM", k, "m0" + V(vlen, "v")], ["SMEMBERS", k],
                    ["SADD", k, V(vlen + 60, "z")], ["SMEMBERS", k], ["SCARD", k], ["DEL", k]]
    return ops




def block_stream_nodes():
    ops = []
    for vlen in (1, 8, 40, 64, 96, 190, 192, 194, 400, 1000, 2048, 4090, 4096, 4100):
        k = "xs%d" % vlen
        ops.append(["DEL", k])
        for i in range(1, 12):
            ops.append(["XADD", k, "%d-1" % i, "f", V(vlen, "v")])
            if i in (1, 2, 11):
                ops += [["XLEN", k], ["OBJECT", "ENCODING", k]]
        ops += [["XRANGE", k, "-", "+"], ["XREVRANGE", k, "+", "-"],
                ["XRANGE", k, "3-1", "7-1"], ["XLEN", k],
                ["XDEL", k, "1-1"], ["XRANGE", k, "-", "+"], ["XLEN", k],
                ["XDEL", k, "11-1"], ["XRANGE", k, "-", "+"],
                ["XTRIM", k, "MAXLEN", "3"], ["XRANGE", k, "-", "+"], ["XLEN", k],
                ["XINFO", "STREAM", k], ["DEL", k]]
    # entries-per-node and bytes-per-node rollover
    for count in (98, 99, 100, 101, 102, 250):
        k = "xn%d" % count
        ops.append(["DEL", k])
        for i in range(1, count + 1):
            ops.append(["XADD", k, "%d-1" % i, "f", "v"])
        ops += [["XLEN", k], ["XRANGE", k, "-", "+"], ["XREVRANGE", k, "+", "-"],
                ["XRANGE", k, "50-1", "60-1"],
                ["XDEL", k, "1-1"], ["XDEL", k, "%d-1" % count], ["XLEN", k],
                ["XTRIM", k, "MAXLEN", "10"], ["XRANGE", k, "-", "+"], ["DEL", k]]
    return ops


def block_intset_widths():
    ops = []
    groups = [
        ("i16", ["1", "-1", "32766", "32767", "-32768", "-32767"]),
        ("i32", ["32768", "-32769", "2147483646", "2147483647", "-2147483648"]),
        ("i64", ["2147483648", "-2147483649", "9223372036854775807", "-9223372036854775808"]),
    ]
    for name, members in groups:
        k = "is_" + name
        ops.append(["DEL", k])
        for m in members:
            ops += [["SADD", k, m], ["OBJECT", "ENCODING", k], ["SCARD", k], ["SISMEMBER", k, m]]
        ops += [["SMEMBERS", k], ["SORT", k], ["SPOP", k, "0"], ["SRANDMEMBER", k, "0"]]
        for m in members:
            ops += [["SREM", k, m], ["SCARD", k], ["OBJECT", "ENCODING", k]]
        ops.append(["EXISTS", k])
    # width promotion in one step, then mixing a non-integer in and out
    k = "is_mix"
    ops += [["DEL", k], ["SADD", k, "1", "2", "3"], ["OBJECT", "ENCODING", k],
            ["SADD", k, "100000"], ["OBJECT", "ENCODING", k], ["SMEMBERS", k],
            ["SADD", k, "10000000000"], ["OBJECT", "ENCODING", k], ["SMEMBERS", k],
            ["SADD", k, "notint"], ["OBJECT", "ENCODING", k], ["SMEMBERS", k],
            ["SREM", k, "notint"], ["OBJECT", "ENCODING", k], ["SMEMBERS", k],
            ["SADD", k, "0007"], ["SMEMBERS", k], ["OBJECT", "ENCODING", k],
            ["SADD", k, "+7"], ["SMEMBERS", k], ["SADD", k, "-0"], ["SMEMBERS", k],
            ["SCARD", k], ["DEL", k]]
    # exceed the intset entry limit
    k = "is_big"
    ops.append(["DEL", k])
    for i in range(140):
        ops.append(["SADD", k, str(i)])
        if i in (126, 127, 128, 129):
            ops.append(["OBJECT", "ENCODING", k])
    ops += [["SCARD", k], ["SORT", k], ["DEL", k]]
    return ops


def block_ttl_embed():
    ops = []
    for n in (0, 1, 44, 63, 64, 95, 96, 127, 128, 183, 184, 190, 191, 192, 193, 200, 256):
        k = "te%d" % n
        ops += [["DEL", k], ["SET", k, V(n, "t"), "EX", "1000"], ["GET", k], ["TTL", k],
                ["APPEND", k, "A"], ["GET", k], ["TTL", k], ["STRLEN", k],
                ["SETRANGE", k, str(n + 5), "PAD"], ["GET", k], ["TTL", k],
                ["PERSIST", k], ["TTL", k], ["GET", k],
                ["EXPIRE", k, "500"], ["TTL", k], ["GET", k],
                ["GETEX", k, "PERSIST"], ["TTL", k], ["GET", k],
                ["SET", k, V(n, "u"), "KEEPTTL"], ["GET", k],
                ["DEL", k]]
        # collections with a TTL across the embedded/external line
        lk = "tl%d" % n
        ops += [["DEL", lk], ["RPUSH", lk, V(n, "l")], ["EXPIRE", lk, "1000"], ["TTL", lk],
                ["RPUSH", lk, V(n, "m")], ["TTL", lk], ["LRANGE", lk, "0", "-1"],
                ["RPUSH", lk, V(n, "n")], ["TTL", lk], ["LRANGE", lk, "0", "-1"],
                ["PERSIST", lk], ["TTL", lk], ["LRANGE", lk, "0", "-1"], ["DEL", lk]]
        hk = "th%d" % n
        ops += [["DEL", hk], ["HSET", hk, "f", V(n, "h")], ["EXPIRE", hk, "1000"],
                ["HSET", hk, "g", V(n, "i")], ["TTL", hk], ["HGETALL", hk],
                ["HSET", hk, "j", V(n, "k")], ["TTL", hk], ["HGETALL", hk],
                ["HDEL", hk, "f"], ["HGETALL", hk], ["TTL", hk], ["DEL", hk]]
    return ops


def block_hexpire_embed():
    ops = []
    for n in (1, 32, 64, 96, 190, 192, 200):
        k = "he%d" % n
        ops += [["DEL", k]]
        for i in range(4):
            ops.append(["HSET", k, "f%d" % i, V(n, "v")])
        ops += [["OBJECT", "ENCODING", k],
                ["HEXPIRE", k, "1000", "FIELDS", "1", "f0"], ["HTTL", k, "FIELDS", "1", "f0"],
                ["OBJECT", "ENCODING", k], ["HGETALL", k],
                ["HPERSIST", k, "FIELDS", "1", "f0"], ["HTTL", k, "FIELDS", "1", "f0"],
                ["HGETALL", k],
                ["HEXPIRE", k, "1000", "FIELDS", "2", "f1", "f2"], ["HGETALL", k],
                ["HDEL", k, "f1"], ["HGETALL", k], ["HLEN", k],
                ["HEXPIRE", k, "0", "FIELDS", "1", "f2"], ["HGETALL", k], ["HLEN", k],
                ["DEL", k]]
    return ops


def block_xshard_sizes():
    ops = []
    for n in (1, 63, 64, 95, 96, 97, 191, 192, 193, 1023, 1024, 1025, 16383, 16384, 16385):
        keys = ["xk%d_%d" % (n, i) for i in range(5)]
        pairs = []
        for i, k in enumerate(keys):
            pairs += [k, V(n, chr(97 + i))]
        ops += [["DEL"] + keys, ["MSET"] + pairs, ["MGET"] + keys,
                ["MSETNX"] + pairs, ["MGET"] + keys,
                ["EXISTS"] + keys, ["TOUCH"] + keys,
                ["UNLINK"] + keys[:2], ["MGET"] + keys,
                ["MSETNX"] + pairs, ["MGET"] + keys,
                ["DEL"] + keys]
        # multi-key writes inside MULTI at the same sizes
        ops += [["MULTI"], ["MSET"] + pairs, ["MGET"] + keys, ["EXEC"], ["MGET"] + keys]
        ops += [["MULTI"], ["RPUSH", keys[0] + "L", V(n, "p")],
                ["RPUSH", keys[0] + "L", V(n, "q")], ["LRANGE", keys[0] + "L", "0", "-1"],
                ["EXEC"], ["LRANGE", keys[0] + "L", "0", "-1"], ["DEL", keys[0] + "L"]]
        ops.append(["DEL"] + keys)
    return ops


BLOCKS = {
    "hash": block_promote_demote,
    "set": block_promote_demote_set,
    "zset": block_promote_demote_zset,
    "list": block_promote_demote_list,
    "strsize": block_string_sizes,
    "listelem": block_list_element_sizes,
    "hashfield": block_hash_field_sizes,
    "zc": block_zc_threshold,
    "segsend": block_segmented_send,
    "intenc": block_int_encoding,
    "embed": block_embed_transitions,
    "zcbound": block_zc_boundary,
    "copymove": block_copy_move,
    "sparse": block_sparse_setrange,
    "keylen": block_keylen_slack,
    "streamnodes": block_stream_nodes,
    "intset": block_intset_widths,
    "ttlembed": block_ttl_embed,
    "hexpire": block_hexpire_embed,
    "xshard": block_xshard_sizes,
}

ONLY = set(sys.argv[3:])
for name, fn in BLOCKS.items():
    if ONLY and name not in ONLY:
        continue
    before, ebefore = len(DIFFS), len(ENCDIFFS)
    ops = fn()
    run(ops, name)
    print("block %-12s ops=%6d semantic=%d encoding-name=%d"
          % (name, len(ops), len(DIFFS) - before, len(ENCDIFFS) - ebefore), flush=True)

print()
report(DIFFS, "SEMANTIC")
print()
report(ENCDIFFS, "OBJECT-ENCODING-NAME")
sys.exit(1 if DIFFS else 0)
