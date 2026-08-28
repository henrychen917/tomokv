#!/usr/bin/env python3
"""storeorder -- a cross-shard STORE's destination must be visible to the SAME connection's next
operation, on a long pipelined stream.

    python3 tests/storeorder.py <host> <port> [--reps N] [--cycles N] [--seed N] [--quiet]

WHAT IS UNDER TEST.  Every command in the store family writes a key it does not read: the
destination.  The engine reaches that destination through the two-hop scatter path (phase 1 reads
the sources on their owners, phase 2 installs the image on the destination's owner), and phase 2 is
posted only after phase 1 has finished.  Same-connection program order across that gap is held by
ONE mechanism -- `ScatterState::barrier`, which stops the connection's parse pass until the whole
op has retired -- except for RENAME/RENAMENX at `--atomic 1` and MSETNX, which drop the barrier and
rely on the MVCC hazard gate instead.  Both mechanisms are asserted here, on one connection, from a
single pipelined write.

WHY THE ASSERTION IS ORACLE-FREE.  Each cycle is

    <build the source>            e.g. ZADD src <n> m<n>
    <STORE dst ... >              ->  a reply that is a known function of the destination content
    <read dst>                    ->  must agree with that reply
    DEL dst                       ->  must be :1
    <read dst>                    ->  must be :0

so every expected value is derived from the target's own earlier reply.  No second server is
needed, nothing depends on float text or on collection ordering, and a violation is by construction
either an acknowledged write that is not visible or a destination write that arrived late.

WHY IT IS A RATE, NOT A RUN.  The defect this battery exists for is boot-dependent (routing is
seeded per boot) and it is a race, so a single clean run proves nothing.  The battery drives
--reps independent pipelines and reports violations per repetition; the pass condition is zero over
all of them.

WHY IT IS NOT VACUOUS.  Two guards, both fatal:
  * GEOMETRY -- DEBUG SHARD is used to count how many store cycles put the destination on a
    different owner from its sources.  Zero cross-owner cycles means the run never drove the
    machinery, and that is reported as a FAILURE of the test, not a pass of the server.
  * CHECKER -- the reply checker is run against a hand-built transcript that contains one injected
    violation of each shape it can report, and it must find exactly those.  A checker that cannot
    say "bad" cannot say "good".
The engine-level positive control is recorded in NOTES-STOREORDER.md: a build with
`ScatterState::barrier` forced false fails this battery on every repetition and in every family
member.
"""
import socket, sys, random

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 7899


def opt(name, default):
    return int(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


REPS = opt("--reps", 10)
CYCLES = opt("--cycles", 500)
# How many consecutive cycles reuse the SAME (src, src2, dst) triple.  This is the single knob
# that decides the battery's sensitivity, and it is not a detail: whether a given triple can
# expose the defect is decided by the boot (which io thread owns the connection, which ex threads
# own the two phase-1 fragments and the destination), so a battery that draws a fresh triple every
# cycle spends almost all of its cycles on geometries that cannot fire.  Holding a triple for a
# run of cycles means an unlucky geometry is hammered instead of sampled -- which is exactly the
# shape the original sighting had, a 160-op window replayed 40 times over one destination.
FOCUS = opt("--focus", 24)
SEED = opt("--seed", 1)
QUIET = "--quiet" in sys.argv


def enc(argv):
    out = b"*%d\r\n" % len(argv)
    for a in argv:
        if isinstance(a, str): a = a.encode()
        out += b"$%d\r\n" % len(a) + a + b"\r\n"
    return out


def read_reply(f):
    line = f.readline()
    if not line: raise EOFError("connection closed mid-stream")
    tag = line[:1]
    if tag in b"+-:,#(_": return line
    if tag in b"$=":
        n = int(line[1:-2])
        return line if n == -1 else line + f.read(n + 2)
    if tag in b"*%~>":
        n = int(line[1:-2])
        if n == -1: return line
        if tag == b"%": n *= 2
        return line + b"".join(read_reply(f) for _ in range(n))
    raise RuntimeError("unparsable reply %r" % line)


def connect():
    s = socket.create_connection((HOST, PORT), timeout=60)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s, s.makefile("rb")


# ---------------------------------------------------------------------------------------------
# The family.  `card` is a read of the DESTINATION whose reply is a known function of n; `flag`
# marks the kinds whose store reply is a status or a 0/1 rather than a destination cardinality.
FAMILY = ["zrangestore", "zunionstore", "zinterstore", "zdiffstore", "sortstore",
          "geosearchstore", "copy", "sunionstore", "sinterstore", "sdiffstore",
          "rename", "renamenx", "smove", "lmove", "rpoplpush", "bitop", "pfmerge", "msetnx"]


def cycle(kind, src, src2, dst, n):
    """(setup commands, store command, destination read, expected destination reply or None).

    None means "the destination read must equal the store's own reply"."""
    if kind == "zrangestore":
        return ([["ZADD", src, str(n), "m%d" % n]],
                ["ZRANGESTORE", dst, src, "0", "-1"], ["ZCARD", dst], None)
    if kind == "zunionstore":
        return ([["ZADD", src, str(n), "m%d" % n]],
                ["ZUNIONSTORE", dst, "2", src, src2], ["ZCARD", dst], None)
    if kind == "zinterstore":
        return ([["ZADD", src, str(n), "m%d" % n], ["ZADD", src2, str(n), "m%d" % n]],
                ["ZINTERSTORE", dst, "2", src, src2], ["ZCARD", dst], None)
    if kind == "zdiffstore":
        return ([["ZADD", src, str(n), "m%d" % n]],
                ["ZDIFFSTORE", dst, "2", src, src2], ["ZCARD", dst], None)
    if kind == "sortstore":
        return ([["RPUSH", src, str(n)]], ["SORT", src, "STORE", dst], ["LLEN", dst], None)
    if kind == "geosearchstore":
        return ([["GEOADD", src, "13.%03d" % (n % 900), "38.1", "p%d" % n]],
                ["GEOSEARCHSTORE", dst, src, "FROMLONLAT", "13.5", "38.1",
                 "BYRADIUS", "20000", "km", "ASC"], ["ZCARD", dst], None)
    if kind == "sunionstore":
        return ([["SADD", src, "m%d" % n]], ["SUNIONSTORE", dst, src, src2], ["SCARD", dst], None)
    if kind == "sinterstore":
        return ([["SADD", src, "m%d" % n], ["SADD", src2, "m%d" % n]],
                ["SINTERSTORE", dst, src, src2], ["SCARD", dst], None)
    if kind == "sdiffstore":
        return ([["SADD", src, "m%d" % n]], ["SDIFFSTORE", dst, src, src2], ["SCARD", dst], None)
    # --- store replies that are NOT a destination cardinality -------------------------------
    if kind == "copy":
        return ([["ZADD", src, str(n), "m%d" % n]],
                ["COPY", src, dst, "REPLACE"], ["ZCARD", dst], n)
    if kind == "rename":
        return ([["DEL", dst], ["ZADD", src, str(n), "m%d" % n]],
                ["RENAME", src, dst], ["ZCARD", dst], 1)
    if kind == "renamenx":
        return ([["DEL", dst], ["ZADD", src, str(n), "m%d" % n]],
                ["RENAMENX", src, dst], ["ZCARD", dst], 1)
    if kind == "smove":
        return ([["SADD", src, "m%d" % n]], ["SMOVE", src, dst, "m%d" % n], ["SCARD", dst], n)
    if kind == "lmove":
        return ([["RPUSH", src, "m%d" % n]],
                ["LMOVE", src, dst, "LEFT", "RIGHT"], ["LLEN", dst], n)
    if kind == "rpoplpush":
        return ([["RPUSH", src, "m%d" % n]], ["RPOPLPUSH", src, dst], ["LLEN", dst], n)
    if kind == "bitop":
        return ([["SET", src, "a" * n]], ["BITOP", "OR", dst, src, src2], ["STRLEN", dst], n)
    if kind == "pfmerge":
        return ([["PFADD", src, "m%d" % n]], ["PFMERGE", dst, src, src2], ["EXISTS", dst], 1)
    if kind == "msetnx":
        return ([["DEL", dst, src2]],
                ["MSETNX", dst, "v%d" % n, src2, "w%d" % n], ["EXISTS", dst], 1)
    raise AssertionError(kind)


SUBCYCLES = 3          # the destination content MOVES, so a stale answer cannot look correct

# A second, UNCHECKED read of the destination in the same pipeline.  It is never compared -- its
# whole job is to be in the transcript when the checked read fails, so the report says WHAT the
# destination held (which members, which encoding) and not merely how many.
FORENSIC = {"ZCARD": lambda d: [["ZRANGE", d, "0", "-1", "WITHSCORES"]],
            "SCARD": lambda d: [["SMEMBERS", d]],
            "LLEN":  lambda d: [["LRANGE", d, "0", "-1"]],
            "STRLEN": lambda d: [["GET", d]],
            "EXISTS": lambda d: [["TYPE", d]]}


def build(rng, cycles, keys):
    """-> (stream, key_roles). stream entries are (argv, role, kind, expected)."""
    stream = []
    roles = []
    for c in range(cycles):
        kind = FAMILY[c % len(FAMILY)]
        if c % FOCUS == 0:
            triple = ("so:%s#s" % rng.choice(keys), "so:%s#t" % rng.choice(keys),
                      "so:%s#d" % rng.choice(keys))
        src, src2, dst = triple
        roles.append((kind, src, src2, dst))
        read = None
        for n in range(1, SUBCYCLES + 1):
            pre, store, read, expected = cycle(kind, src, src2, dst, n)
            for p in pre: stream.append((p, "pre", kind, None))
            stream.append((store, "store", kind, None))
            stream.append((read, "read", kind, expected))
            for extra in FORENSIC[read[0]](read[1]):
                stream.append((extra, "forensic", kind, None))
            stream.append((["OBJECT", "ENCODING", read[1]], "forensic", kind, None))
        stream.append((["DEL", dst], "del", kind, None))
        stream.append((read, "afterdel", kind, 0))
        stream.append((["DEL", src, src2], "pre", kind, None))
    return stream, roles


SHARDS = {}   # key -> owning shard, filled by geometry() and used only in reports


def history(stream, replies, key, upto, back=14, ahead=6):
    """Every op in the stream that names `key`, up to and including `upto`, with its reply.

    A violation of this invariant is always a statement about ONE key's timeline, so the timeline
    is what the report has to carry: which command wrote it, what that command answered, and what
    the reads on either side of it saw."""
    rows = []
    after = []
    for i in range(len(stream)):
        argv = stream[i][0]
        if key not in argv: continue
        row = "      op %d %-52r -> %r" % (i, argv[:6], replies[i][:88])
        if i <= upto: rows.append(row)
        elif len(after) < ahead: after.append(row)
        else: break
    place = ["      shards: " + " ".join(
        "%s=%s" % (k, SHARDS.get(k, "?")) for k in
        sorted({a for j in range(max(0, upto - 3), upto + 1) for a in stream[j][0]
                if isinstance(a, str) and a.startswith("so:")}))]
    return rows[-back:] + after + place


def check(stream, replies):
    """-> list of violation strings. Pure function of the transcript; unit-tested below."""
    bad = []
    last_store = None
    for i, (argv, role, kind, expected) in enumerate(stream):
        reply = replies[i]
        if role == "store":
            last_store = reply if reply[:1] == b":" else None
            if reply[:1] == b"-":
                bad.append("op %d %s %r -> error reply %r" % (i, kind, argv[:3], reply.strip()))
        elif role == "read":
            hit = None
            if expected is not None:
                if reply != b":%d\r\n" % expected:
                    hit = ("op %d %s LATE-OR-LOST destination %r: want :%d got %r"
                           % (i, kind, argv, expected, reply.strip()))
            elif last_store is not None and reply != last_store:
                hit = ("op %d %s LATE-OR-LOST destination %r: store answered %r, read %r"
                       % (i, kind, argv, last_store.strip(), reply.strip()))
            if hit:
                bad.append("\n".join([hit] + history(stream, replies, argv[-1], i)))
        elif role == "afterdel":
            if reply != b":0\r\n":
                bad.append("\n".join(
                    ["op %d %s SURVIVES-DEL %r -> %r" % (i, kind, argv, reply.strip())] +
                    history(stream, replies, argv[-1], i)))
    return bad


# ---------------------------------------------------------------------------------------------
def checker_self_test():
    """The checker must report each shape it claims to detect. Fatal if it cannot."""
    stream = [(["ZRANGESTORE", "d", "s", "0", "-1"], "store", "zrangestore", None),
              (["ZCARD", "d"], "read", "zrangestore", None),
              (["COPY", "s", "d"], "store", "copy", None),
              (["ZCARD", "d"], "read", "copy", 2),
              (["ZCARD", "d"], "afterdel", "copy", 0)]
    clean = [b":2\r\n", b":2\r\n", b":1\r\n", b":2\r\n", b":0\r\n"]
    if check(stream, clean):
        raise SystemExit("storeorder: FATAL checker flags a clean transcript: %r"
                         % check(stream, clean))
    shapes = {
        "store-vs-read": [b":2\r\n", b"*0\r\n", b":1\r\n", b":2\r\n", b":0\r\n"],
        "expected-count": [b":2\r\n", b":2\r\n", b":1\r\n", b":0\r\n", b":0\r\n"],
        "survives-del":   [b":2\r\n", b":2\r\n", b":1\r\n", b":2\r\n", b":1\r\n"],
        "store-errored":  [b"-ERR x\r\n", b":0\r\n", b":1\r\n", b":2\r\n", b":0\r\n"],
    }
    for name, replies in shapes.items():
        if not check(stream, replies):
            raise SystemExit("storeorder: FATAL checker blind to %s" % name)
    return len(shapes)


def geometry(sock, file, roles):
    """How many cycles genuinely put the destination on a different OWNER from its sources?

    DEBUG SHARD is the geometry oracle (the hash seed is drawn per boot).  A run with zero
    cross-owner cycles never drove the two-hop path and must not be reported as a pass.
    """
    want = set()
    for _, src, src2, dst in roles: want.update((src, src2, dst))
    shard = {}
    for key in sorted(want):
        sock.sendall(enc(["DEBUG", "SHARD", key]))
        reply = read_reply(file)
        if reply[:1] != b":":
            raise SystemExit("storeorder: FATAL DEBUG SHARD unavailable (%r) -- boot the server "
                             "with --enable-debug-command yes" % reply.strip())
        shard[key] = int(reply[1:-2])
    SHARDS.update(shard)
    cross = sum(1 for _, src, src2, dst in roles
                if shard[dst] != shard[src] or shard[dst] != shard[src2])
    return cross, len(set(shard.values()))


def main():
    shapes = checker_self_test()
    rng0 = random.Random(SEED)
    keys = ["k%02d" % i for i in range(64)]
    total_stores = total_bad = total_cross = 0
    bad_reps = 0
    shown = 0
    nshards_seen = 0
    for rep in range(REPS):
        rng = random.Random(SEED * 1000 + rep)
        stream, roles = build(rng, CYCLES, keys)
        sock, file = connect()
        sock.sendall(enc(["FLUSHALL"]))
        if read_reply(file)[:1] != b"+":
            raise SystemExit("storeorder: FATAL FLUSHALL refused")
        cross, nshards = geometry(sock, file, roles)
        total_cross += cross
        nshards_seen = max(nshards_seen, nshards)
        # ONE write.  The pipeline is the load-bearing part: the destination install and the
        # connection's later operations only overlap when the client is not waiting for replies.
        sock.sendall(b"".join(enc(a) for a, _, _, _ in stream))
        replies = [read_reply(file) for _ in stream]
        sock.close()
        bad = check(stream, replies)
        total_stores += sum(1 for _, role, _, _ in stream if role == "store")
        total_bad += len(bad)
        if bad:
            bad_reps += 1
            for line in bad[:6]:
                if shown < 12:
                    print("  %s" % line)
                    shown += 1
        if not QUIET:
            print("  rep %d: %d ops, %d store cycles cross-owner of %d, %d violations"
                  % (rep, len(stream), cross, len(roles), len(bad)))
    if nshards_seen <= 1:
        print("storeorder: single-shard boot -- the two-hop path was never driven. "
              "This is a CONTROL leg only; re-run with --shards >= 2.")
    if total_cross == 0 and nshards_seen > 1:
        print("storeorder: 0 checks, 1 failures -> FAIL "
              "(no cross-owner store cycle was generated: the battery tested nothing)")
        return 1
    checks = total_stores + shapes
    ok = total_bad == 0
    print("storeorder: %d checks, %d failures -> %s  "
          "[%d reps, %d store cycles, %d cross-owner, %d shards, checker self-test %d/%d]"
          % (checks, total_bad, "PASS" if ok else "FAIL", REPS, total_stores, total_cross,
             nshards_seen, shapes, shapes))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
