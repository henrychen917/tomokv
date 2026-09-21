#!/usr/bin/env python3
"""Logical databases, including mid-pipeline RYOW. Connects only to a gate-owned server."""
import argparse
import threading
import time
from _lib import Conn, RespError, encode, topology
from sortstore import check_namespace as check_sortstore_namespace


def expect(got, wanted, label):
    if got != wanted:
        raise AssertionError(f"{label}: got {got!r}, expected {wanted!r}")


def pipeline(c, commands, replies, label):
    assert len(commands) == len(replies)
    c.raw(b"".join(encode(*cmd) for cmd in commands))
    for index, wanted in enumerate(replies):
        try:
            got = c.read()
        except (EOFError, OSError) as error:
            raise AssertionError(f"{label} #{index} {commands[index]!r}: {error}") from error
        expect(got, wanted, f"{label} #{index} {commands[index]!r}")


def fields(c, section):
    return dict(line.split(b":", 1) for line in c.must("INFO", section).splitlines()
                if b":" in line and not line.startswith(b"#"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--read-local", type=int, choices=(0, 1), required=True)
    parser.add_argument("--persistence", action="store_true")
    args = parser.parse_args()
    opened = []

    def connection(db=0):
        c = Conn(args.host, args.port, timeout=30)
        opened.append(c)
        expect(c.cmd("SELECT", db), b"OK", "SELECT connection")
        return c

    admin = connection()
    try:
        expect(admin.cmd("CONFIG", "GET", "databases"), [b"databases", b"16"], "configured count")
        for index in (-1, 16, 256):
            expect(admin.cmd("SELECT", index), RespError("ERR DB index is out of range"), "SELECT range")
        for index in ("no", "+1", "01", "-0", "9223372036854775808"):
            expect(admin.cmd("SELECT", index), RespError("ERR invalid DB index"), "SELECT grammar")
        expect(admin.cmd("SWAPDB", "bad", 0), RespError("ERR invalid first DB index"), "SWAP first index")
        expect(admin.cmd("SWAPDB", 0, "bad"), RespError("ERR invalid second DB index"), "SWAP second index")
        expect(admin.cmd("FLUSHALL"), b"OK", "clean dataset")
        check_sortstore_namespace(admin)
        c = connection()
        one = connection(1)
        expect(one.cmd("SET", "md:ryow", "other-db"), b"OK", "db1 sentinel")
        stop = threading.Event()
        started = [threading.Event() for _ in range(4)]
        counts = [0] * 4
        failures = []

        def writer(i):
            w = None
            try:
                w = Conn(args.host, args.port)
                expect(w.cmd("SELECT", 2 + i % 2), b"OK", "writer namespace")
                while not stop.is_set():
                    # Same raw key in another DB is NOT an explicit key conflict.
                    expect(w.cmd("SET", "md:ryow", f"noise:{i}:{counts[i]}"), b"OK", "writer SET")
                    counts[i] += 1
                    started[i].set()
            except BaseException as error:
                failures.append(repr(error))
                started[i].set()
            finally:
                if w:
                    w.close()

        threads = [threading.Thread(target=writer, args=(i,), daemon=True) for i in range(4)]
        for thread in threads:
            thread.start()
        try:
            for witness in started:
                assert witness.wait(10), "concurrent writer never started"
            before = counts[:]
            for burst in range(16):
                commands, replies = [], []
                for i in range(128):
                    value = f"own:{burst}:{i}".encode()
                    commands += [("SET", "md:ryow", value), ("SELECT", 1), ("GET", "md:ryow"),
                                 ("SELECT", 0), ("GET", "md:ryow")]
                    replies += [b"OK", b"OK", b"other-db", b"OK", value]
                pipeline(c, commands, replies, "mid-pipe RYOW")
            assert all(after > prior for after, prior in zip(counts, before)), "writers did not overlap RYOW"
        finally:
            stop.set()
            for thread in threads:
                thread.join(10)
            assert not any(thread.is_alive() for thread in threads), "writer did not stop"
        assert not failures, failures
        if args.read_local:
            hits = int(fields(admin, "stats").get(b"read_local_hits", b"-1"))
            pipeline(c, [("GET", "md:ryow")] * 256, [b"own:15:127"] * 256, "clean local reads")
            assert int(fields(admin, "stats").get(b"read_local_hits", b"-1")) > hits >= 0, "local lane never fired"
        print(f"multidb RYOW: 2048 SELECT round trips; concurrent writes={counts}", flush=True)

        expect(admin.cmd("FLUSHALL"), b"OK", "scoped setup")
        for db in range(4):
            expect(c.cmd("SELECT", db), b"OK", "populate DB")
            expect(c.cmd("SET", b"md:\0key", f"db{db}"), b"OK", "binary key")
            expect(c.cmd("HSET", "md:hash", "field", f"db{db}"), 1, "hash namespace")
            expect(c.cmd("RPUSH", "md:list", f"db{db}"), 1, "list namespace")
            expect(c.cmd("SADD", "md:set", f"db{db}"), 1, "set namespace")
            expect(c.cmd("ZADD", "md:zset", db, f"db{db}"), 1, "zset namespace")
            expect(c.cmd("SET", "md:ttl", f"db{db}", "PX", 600000), b"OK", "TTL namespace")
            expect(c.cmd("DBSIZE"), 6, "DBSIZE")
            keys = {b"md:\0key", b"md:hash", b"md:list", b"md:set", b"md:zset", b"md:ttl"}
            expect(set(c.must("KEYS", "*")), keys, "KEYS")
            assert c.must("RANDOMKEY") in keys, "RANDOMKEY escaped namespace"
            cursor, scanned = b"0", set()
            for _ in range(10000):
                cursor, found = c.must("SCAN", cursor, "COUNT", 3)
                scanned.update(found)
                if cursor == b"0":
                    break
            else:
                raise AssertionError("SCAN did not finish")
            expect(scanned, keys, "SCAN")
        info = fields(admin, "keyspace")
        for db in range(4):
            parts = dict(item.split(b"=", 1) for item in info[f"db{db}".encode()].split(b","))
            expect(int(parts[b"keys"]), 6, "INFO keys")
            expect(int(parts[b"expires"]), 1, "INFO expires")
            assert 0 < int(parts[b"avg_ttl"]) <= 600000, "INFO avg_ttl"
        assert b"db=3" in c.must("CLIENT", "INFO"), "CLIENT database"
        expect(c.cmd("FLUSHDB"), b"OK", "FLUSHDB")
        expect(c.cmd("DBSIZE"), 0, "empty DB")
        expect(c.cmd("RANDOMKEY"), None, "empty RANDOMKEY")
        expect(one.cmd("GET", b"md:\0key"), b"db1", "FLUSHDB preserves another DB")
        expect(one.cmd("MOVE", b"md:\0key", 3), 1, "MOVE")
        expect(one.cmd("GET", b"md:\0key"), None, "MOVE source removed")
        expect(c.cmd("GET", b"md:\0key"), b"db1", "MOVE destination")
        expect(c.cmd("COPY", b"md:\0key", b"md:\0key", "DB", 1), 1, "COPY DB")

        expect(c.cmd("SELECT", 0), b"OK", "transaction base")
        pipeline(c, [("MULTI",), ("SELECT", 1), ("GET", b"md:\0key"),
                     ("SELECT", 0), ("GET", b"md:\0key"), ("EXEC",)],
                 [b"OK", b"QUEUED", b"QUEUED", b"QUEUED", b"QUEUED",
                  [b"OK", b"db1", b"OK", b"db0"]], "MULTI SELECT")
        pipeline(c, [("MULTI",), ("SELECT", 16), ("GET", b"md:\0key"), ("EXEC",)],
                 [b"OK", b"QUEUED", b"QUEUED", [RespError("ERR DB index is out of range"), b"db0"]],
                 "invalid queued SELECT leaves DB")
        pipeline(c, [("WATCH", b"md:\0key"), ("SELECT", 1), ("WATCH", b"md:\0key")],
                 [b"OK"] * 3, "WATCH across DBs")
        other = connection(2)
        expect(other.cmd("SET", b"md:\0key", "elsewhere"), b"OK", "unwatched DB write")
        pipeline(c, [("MULTI",), ("GET", b"md:\0key"), ("EXEC",)],
                 [b"OK", b"QUEUED", [b"db1"]], "WATCH isolation")
        expect(c.cmd("WATCH", b"md:\0key"), b"OK", "WATCH before swap")
        expect(admin.cmd("SWAPDB", 0, 1), b"OK", "swap")
        expect(admin.cmd("SWAPDB", 0, 1), b"OK", "swap back")
        pipeline(c, [("MULTI",), ("SELECT", 0), ("GET", b"md:\0key"), ("EXEC",)],
                 [b"OK", b"QUEUED", b"QUEUED", None], "WATCH swap-back abort")
        assert b"db=1" in c.must("CLIENT", "INFO"), "aborted EXEC applied SELECT"
        expect(c.cmd("WATCH", "md:missing"), b"OK", "WATCH absent in both DBs")
        expect(admin.cmd("SWAPDB", 0, 1), b"OK", "swap absent key")
        pipeline(c, [("MULTI",), ("GET", "md:missing"), ("EXEC",)],
                 [b"OK", b"QUEUED", [None]], "absent WATCH survives swap")
        expect(c.cmd("WATCH", "md:missing"), b"OK", "WATCH follows DB")
        expect(admin.cmd("SWAPDB", 0, 1), b"OK", "restore map with absent WATCH")
        expect(one.cmd("SET", "md:missing", "after-swap"), b"OK", "write through new WATCH alias")
        pipeline(c, [("MULTI",), ("GET", "md:missing"), ("EXEC",)],
                 [b"OK", b"QUEUED", None], "WATCH sees write after swap")
        expect(one.cmd("DEL", "md:missing"), 1, "WATCH alias cleanup")

        # Two equal keys per DB make a cross-namespace/torn pair detectable under SWAPDB.
        # Prove owner fan-out in BOTH physical namespaces; two distinct shard IDs
        # alone are insufficient at the gate's sixteen-shard/two-executor geometry.
        shard_owner = topology(admin).shard_owner
        pair = None
        first = None
        for probe in range(10000):
            key = f"md:pair:{probe}"
            owners = []
            for db in (0, 1):
                expect(c.cmd("SELECT", db), b"OK", "pair geometry DB")
                owners.append(shard_owner[c.must("DEBUG", "SHARD", key)])
            if first is None:
                first = (key, owners)
            elif all(a != b for a, b in zip(first[1], owners)):
                pair = (first[0], key)
                break
        assert pair, "multi-owner SWAPDB pair never armed in both databases"
        for db in (0, 1):
            expect(c.cmd("SELECT", db), b"OK", "swap population DB")
            expect(c.cmd("MSET", pair[0], f"db{db}", pair[1], f"db{db}"), b"OK", "swap population")
        commands, replies = [], []
        for i in range(128):
            commands += [("SWAPDB", 0, 1), ("SELECT", 0), ("MGET", *pair),
                         ("SELECT", 1), ("MGET", *pair)]
            left = b"db1" if i % 2 == 0 else b"db0"
            right = b"db0" if i % 2 == 0 else b"db1"
            replies += [b"OK", b"OK", [left, left], b"OK", [right, right]]
        pipeline(c, commands, replies, "SWAPDB pipeline")
        pipeline(c, [("SELECT", 0), ("SET", "md:midpipe", "before"), ("SWAPDB", 0, 1),
                     ("SELECT", 1), ("GET", "md:midpipe"), ("SET", "md:midpipe", "after"),
                     ("SELECT", 0), ("GET", "md:midpipe"), ("SWAPDB", 0, 1),
                     ("GET", "md:midpipe"), ("DEL", "md:midpipe")],
                 [b"OK", b"OK", b"OK", b"OK", b"before", b"OK", b"OK", None,
                  b"OK", b"after", 1], "mid-pipe SELECT+SWAPDB RYOW")

        swap_start = threading.Event()
        swap_counts = [0, 0]
        swap_errors = []
        def swapper(i):
            s = None
            try:
                s = Conn(args.host, args.port)
                assert swap_start.wait(5), "swap start barrier"
                for _ in range(64):
                    pipeline(s, [("SWAPDB", 0, 1), ("SWAPDB", 0, 1)], [b"OK", b"OK"], "concurrent swaps")
                    swap_counts[i] += 2
            except BaseException as error:
                swap_errors.append(repr(error))
            finally:
                if s:
                    s.close()
        swappers = [threading.Thread(target=swapper, args=(i,), daemon=True) for i in range(2)]
        for thread in swappers:
            thread.start()
        swap_start.set()
        read_batches = 0
        while any(thread.is_alive() for thread in swappers):
            c.raw(encode("MGET", *pair) * 32)
            for _ in range(32):
                assert c.read() in ([b"db0", b"db0"], [b"db1", b"db1"]), "SWAPDB tore a pipelined read"
            read_batches += 1
        for thread in swappers:
            thread.join(5)
        assert not swap_errors, swap_errors
        assert swap_counts == [128, 128] and read_batches > 0, "concurrent SWAP/read window never opened"
        print(f"multidb SWAPDB: two swappers={swap_counts}, read batches={read_batches}", flush=True)

        # A parked logical-DB waiter must follow its DB through a namespace-map swap.
        waiter = connection(4)
        populated = connection(5)
        expect(populated.cmd("RPUSH", "md:wake", "swapped-value"), 1, "blocking swap source")
        baseline = int(fields(admin, "clients")[b"blocked_clients"])
        waiter.send("BLPOP", "md:wake", 5)
        deadline = time.monotonic() + 3
        while int(fields(admin, "clients")[b"blocked_clients"]) <= baseline:
            assert time.monotonic() < deadline, "BLPOP never parked"
            time.sleep(.01)
        expect(admin.cmd("SWAPDB", 4, 5), b"OK", "swap wakes logical DB waiter")
        expect(waiter.read(), [b"md:wake", b"swapped-value"], "blocking SWAPDB")

        expect(admin.cmd("CONFIG", "SET", "notify-keyspace-events", "Eg$"), b"OK", "notification config")
        subscriber = connection()
        expect(subscriber.cmd("PSUBSCRIBE", "__keyevent@*__:*")[0], b"psubscribe", "subscribe")
        expect(one.cmd("SET", "md:event", "one"), b"OK", "db1 notification write")
        expect(subscriber.read(), [b"pmessage", b"__keyevent@*__:*", b"__keyevent@1__:set", b"md:event"], "notification DB")
        expect(one.cmd("MOVE", "md:event", 6), 1, "notification MOVE")
        events = [subscriber.read(), subscriber.read()]
        expect([(event[2], event[3]) for event in events],
               [(b"__keyevent@1__:move_from", b"md:event"), (b"__keyevent@6__:move_to", b"md:event")], "MOVE events")
        subscriber.close()
        expect(admin.cmd("CONFIG", "SET", "notify-keyspace-events", ""), b"OK", "notification reset")

        if args.persistence:
            # DEBUG RELOAD invokes the native snapshot save/load path. LOADAOF replays the
            # independently journalled stream. Both are owned by this gate boot, never this client.
            expect(admin.cmd("SELECT", 0), b"OK", "history DB0")
            expect(admin.cmd("SET", "md:persist-history", "zero"), b"OK", "history zero")
            expect(one.cmd("SET", "md:persist-history", "one"), b"OK", "history one")
            expect(admin.cmd("SWAPDB", 0, 2), b"OK", "persist standalone swap")
            pipeline(admin, [("MULTI",), ("SWAPDB", 0, 1), ("SELECT", 0),
                             ("GET", "md:persist-history"), ("SET", "md:persist-after", "after"),
                             ("SELECT", 2), ("GET", "md:persist-history"), ("EXEC",)],
                     [b"OK"] + [b"QUEUED"] * 6 +
                     [[b"OK", b"OK", b"one", b"OK", b"OK", b"zero"]],
                     "persist transactional swap history")
            def dataset():
                rows = []
                for db in range(7):
                    expect(c.cmd("SELECT", db), b"OK", "persist SELECT")
                    row = []
                    for key in sorted(c.must("KEYS", "*")):
                        row.append((key, c.must("DUMP", key)))
                        ttl = c.must("PTTL", key)
                        assert ttl == -1 or 0 < ttl <= 600000, "TTL lost on replay"
                    rows.append(row)
                return rows
            before = dataset()
            assert sum(map(len, before)) > 20, "persistence dataset never populated"
            expect(admin.cmd("DEBUG", "RELOAD"), b"OK", "snapshot reload")
            expect(dataset(), before, "multi-DB snapshot round trip")
            expect(admin.cmd("DEBUG", "LOADAOF"), b"OK", "AOF replay")
            expect(dataset(), before, "multi-DB AOF round trip")
        print("multidb PASS: namespace commands, transactions, WATCH, SWAPDB, blocking, notifications and persistence", flush=True)
    finally:
        for c in opened:
            c.close()


if __name__ == "__main__":
    main()
