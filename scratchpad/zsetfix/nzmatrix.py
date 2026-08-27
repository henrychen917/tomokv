#!/usr/bin/env python3
"""Negative-zero probe matrix: TomoKV (7021) vs vanilla redis 7.4 (7022), byte-exact."""
import socket, sys

def conn(port):
    s = socket.create_connection(("127.0.0.1", port), timeout=30)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s, s.makefile("rb")

def enc(args):
    o = b"*%d\r\n" % len(args)
    for a in args:
        if isinstance(a, str): a = a.encode()
        o += b"$%d\r\n" % len(a) + a + b"\r\n"
    return o

def rd(f):
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
        return line + b"".join(rd(f) for _ in range(n))
    if t == b"%":
        n = int(line[1:-2])
        return line + b"".join(rd(f) for _ in range(2 * n))
    raise RuntimeError("bad reply %r" % line)

T = conn(7021); O = conn(7022)
SIDES = (("tomo", T), ("redis", O))

def run(side, cmd):
    s, f = side
    s.sendall(enc(cmd)); return rd(f)

def both(cmd):
    return tuple(run(sd, cmd) for _, sd in SIDES)

def scores(reply):
    """extract the score bulk strings from a flat WITHSCORES array reply"""
    out, i = [], 0
    parts = reply.split(b"\r\n")
    return reply

def setup(side, big):
    """build the standard source keys; big=True forces skiplist encoding"""
    run(side, ["FLUSHALL"])
    pad = []
    for i in range(200): pad += [str(1000 + i), "pad%d" % i]
    def mk(key, pairs):
        if big:
            run(side, ["ZADD", key] + pad)
        run(side, ["ZADD", key] + pairs)
        if big:
            run(side, ["ZREMRANGEBYSCORE", key, "1000", "+inf"])
    mk("zp", ["0", "m"])       # stored +0
    mk("zn", ["-0", "m"])      # stored -0
    mk("z1", ["1", "m"])       # stored +1
    mk("zm1", ["-1", "m"])     # stored -1
    run(side, ["SADD", "st", "m"])          # set member -> implicit 1.0
    run(side, ["ZADD", "zother", "5", "other"])

def cell(cmd):
    a, b = both(cmd)
    return a, b, (a == b)

rows = []
def add(label, cmd):
    a, b, same = cell(cmd)
    rows.append((label, cmd, a, b, same))

def show(title, encoding):
    print("\n" + "=" * 108)
    print("%s   [source encoding: %s]" % (title, encoding))
    print("=" * 108)
    print("%-56s | %-16s | %-16s | %s" % ("probe", "tomokv", "redis 7.4", "="))
    print("-" * 108)
    for label, cmd, a, b, same in rows:
        def fmt(r):
            # last bulk string in the reply is the score we care about for most probes
            return r.replace(b"\r\n", b" ").decode(errors="replace").strip()[:16]
        print("%-56s | %-16s | %-16s | %s" % (label[:56], fmt(a), fmt(b), "" if same else "DIFF"))
    rows.clear()

for big, encname in ((False, "listpack/Compact"), (True, "skiplist/Btree")):
    for _, sd in SIDES: setup(sd, big)
    for _, sd in SIDES:
        pass
    print("\n### encodings: tomo=%r redis=%r" % (run(T, ["OBJECT", "ENCODING", "zp"]),
                                                run(O, ["OBJECT", "ENCODING", "zp"])))

    # --- A. storage round-trip -------------------------------------------------------------
    add("ZSCORE zp m            (stored +0)", ["ZSCORE", "zp", "m"])
    add("ZSCORE zn m            (stored -0)", ["ZSCORE", "zn", "m"])
    add("ZRANGE zn 0 -1 WITHSCORES", ["ZRANGE", "zn", "0", "-1", "WITHSCORES"])
    for lit in ("-0", "-0.0", "-0e0", "0", "+0"):
        run(T, ["ZADD", "rt", lit, "m"]); run(O, ["ZADD", "rt", lit, "m"])
        add("ZADD rt %-5s m  -> ZSCORE" % lit, ["ZSCORE", "rt", "m"])
        run(T, ["DEL", "rt"]); run(O, ["DEL", "rt"])
    show("A. STORAGE ROUND-TRIP of a negative zero", encname)

    # --- B. INCR family --------------------------------------------------------------------
    for _, sd in SIDES: setup(sd, big)
    add("ZINCRBY zp -0 m   (+0 + -0)", ["ZINCRBY", "zp", "-0", "m"])
    add("ZINCRBY zn -0 m   (-0 + -0)", ["ZINCRBY", "zn", "-0", "m"])
    add("ZINCRBY zn 0 m    (-0 +  0)", ["ZINCRBY", "zn", "0", "m"])
    for _, sd in SIDES: setup(sd, big)
    add("ZADD zp INCR -0 m", ["ZADD", "zp", "INCR", "-0", "m"])
    add("ZADD zn INCR -0 m", ["ZADD", "zn", "INCR", "-0", "m"])
    for _, sd in SIDES: setup(sd, big)
    add("ZINCRBY fresh -0 m  (new key)", ["ZINCRBY", "fresh", "-0", "m"])
    add("ZINCRBY z1 -1 m     (1 + -1)", ["ZINCRBY", "z1", "-1", "m"])
    add("ZINCRBY zm1 1 m     (-1 + 1)", ["ZINCRBY", "zm1", "1", "m"])
    show("B. INCR family", encname)

    # --- C. single-source ZUNION with WEIGHTS ----------------------------------------------
    for _, sd in SIDES: setup(sd, big)
    for srckey, desc in (("zp", "+0"), ("zn", "-0"), ("st", "set(1.0)"), ("z1", "+1")):
        for w in ("1", "-1", "0", "-0"):
            add("ZUNION 1 %-3s WEIGHTS %-3s  src=%-9s" % (srckey, w, desc),
                ["ZUNION", "1", srckey, "WEIGHTS", w, "WITHSCORES"])
    show("C. single source x WEIGHTS (aggregate default SUM)", encname)

    # --- D. two-source SUM/MIN/MAX ---------------------------------------------------------
    for _, sd in SIDES: setup(sd, big)
    for agg in ("SUM", "MIN", "MAX"):
        for a_key, b_key in (("zp", "zn"), ("zn", "zp"), ("zn", "zn"), ("zp", "zp")):
            add("ZUNION 2 %s %s AGGREGATE %s" % (a_key, b_key, agg),
                ["ZUNION", "2", a_key, b_key, "AGGREGATE", agg, "WITHSCORES"])
    show("D. two-source aggregation over stored +0/-0", encname)

    # --- E. WEIGHTS x aggregate (the differ's shape) ----------------------------------------
    for _, sd in SIDES: setup(sd, big)
    for agg in ("SUM", "MIN", "MAX"):
        for w1, w2 in (("-1", "0"), ("0", "-1"), ("-1", "-1"), ("0", "0"), ("1", "-1"), ("-0", "1")):
            add("ZUNION 2 zp zn WEIGHTS %s %s AGG %s" % (w1, w2, agg),
                ["ZUNION", "2", "zp", "zn", "WEIGHTS", w1, w2, "AGGREGATE", agg, "WITHSCORES"])
    show("E. WEIGHTS x AGGREGATE on (+0, -0)", encname)

    # --- F. set member (implicit 1.0) mixed in ----------------------------------------------
    for _, sd in SIDES: setup(sd, big)
    for agg in ("SUM", "MIN", "MAX"):
        for w1, w2 in (("0", "1"), ("-0", "1"), ("0", "-1"), ("-1", "0")):
            add("ZUNION 2 st zp WEIGHTS %s %s AGG %s" % (w1, w2, agg),
                ["ZUNION", "2", "st", "zp", "WEIGHTS", w1, w2, "AGGREGATE", agg, "WITHSCORES"])
    for w in ("0", "-0", "-1"):
        add("ZUNION 1 st WEIGHTS %s" % w, ["ZUNION", "1", "st", "WEIGHTS", w, "WITHSCORES"])
    show("F. set members (implicit 1.0)", encname)

    # --- G. ZINTER / ZDIFF -------------------------------------------------------------------
    for _, sd in SIDES: setup(sd, big)
    for agg in ("SUM", "MIN", "MAX"):
        add("ZINTER 2 zp zn AGG %s" % agg, ["ZINTER", "2", "zp", "zn", "AGGREGATE", agg, "WITHSCORES"])
        add("ZINTER 2 zp zn W -1 0 AGG %s" % agg,
            ["ZINTER", "2", "zp", "zn", "WEIGHTS", "-1", "0", "AGGREGATE", agg, "WITHSCORES"])
    add("ZDIFF 2 zn zother", ["ZDIFF", "2", "zn", "zother", "WITHSCORES"])
    add("ZDIFF 2 zp zother", ["ZDIFF", "2", "zp", "zother", "WITHSCORES"])
    show("G. ZINTER / ZDIFF", encname)

    # --- H. STORE variants: does the stored score keep the sign? ------------------------------
    for _, sd in SIDES: setup(sd, big)
    both(["ZUNIONSTORE", "d1", "2", "zp", "zn", "WEIGHTS", "-1", "0"])
    add("ZUNIONSTORE d1 2 zp zn W -1 0 -> ZSCORE", ["ZSCORE", "d1", "m"])
    both(["ZUNIONSTORE", "d2", "1", "zp", "WEIGHTS", "-1"])
    add("ZUNIONSTORE d2 1 zp W -1      -> ZSCORE", ["ZSCORE", "d2", "m"])
    both(["ZINTERSTORE", "d3", "2", "zp", "zn", "AGGREGATE", "MIN"])
    add("ZINTERSTORE d3 2 zp zn AGG MIN-> ZSCORE", ["ZSCORE", "d3", "m"])
    both(["ZDIFFSTORE", "d4", "2", "zn", "zother"])
    add("ZDIFFSTORE d4 2 zn zother     -> ZSCORE", ["ZSCORE", "d4", "m"])
    both(["ZRANGESTORE", "d5", "zn", "0", "-1"])
    add("ZRANGESTORE d5 zn 0 -1        -> ZSCORE", ["ZSCORE", "d5", "m"])
    show("H. *STORE destinations", encname)
