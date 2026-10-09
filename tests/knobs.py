#!/usr/bin/env python3
"""Configuration grammar, live encoding controls and actual gate geometry."""
import sys

import _lib


host, port, engine, atomic = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
retired = (
    "read-local-prefetch-capture", "read-local-atomic-filter", "read-local-interleave",
    "flip-auto-band", "l3-domains", "smt-mode", "genthread-schedule",
    "atomic-window", "persist-io", "lru-clock-shift", "script-crossshard-max-bytes",
    "script-crossshard-workbench-bytes", "script-crossshard-conflict-retries",
    "script-crossshard-cut-slots", "tls-ktls", "lb", "flip-work-window",
    "script-instruction-limit",
    "load", "conf",
    "list-max-compact-entries", "list-max-compact-value", "set-max-compact-entries",
    "set-max-compact-value",
    "lb-sample-rate", "lb-age-sample-rate", "lb-tick-ms", "lb-imbalance-pct",
    "lb-move-cap", "lb-cooldown-ms", "ex-sched", "x-ex-sched", "x-overlap", "thread-pipeline",
)
conn = _lib.Conn(host, port)
try:
    config = conn.must("CONFIG", "GET", "*")
    values = dict(zip(config[::2], config[1::2]))
    for name in retired:
        if name.encode() in values or conn.must("CONFIG", "GET", name) != []:
            raise AssertionError("retired CONFIG name is visible: " + name)
        if not isinstance(conn.cmd("CONFIG", "SET", name, "0"), _lib.RespError):
            raise AssertionError("retired CONFIG name remains writable: " + name)
    # Redis 7.4 has a fixed PROTO_INLINE_MAX_SIZE, not a proto-max-inline knob.
    if conn.must("CONFIG", "GET", "proto-max-inline") != []:
        raise AssertionError("invented proto-max-inline CONFIG surface")
    if conn.cmd("CONFIG", "SET", "proto-max-inline", "65536") != _lib.RespError(
            b"ERR Unknown option or number of arguments for CONFIG SET - 'proto-max-inline'"):
        raise AssertionError("proto-max-inline SET differs from Redis 7.4")
    query_name = "client-query-buffer-limit"
    if values.get(query_name.encode()) != b"1073741824":
        raise AssertionError("query-buffer limit default differs from Redis's 1gb")
    try:
        for spelling, expected in (("1mb", "1048576"), ("2m", "2000000"),
                                   ("1GB", "1073741824"), ("001048576B", "1048576"),
                                   ("9223372036854775807", "9223372036854775807")):
            conn.must("CONFIG", "SET", query_name, spelling)
            if conn.must("CONFIG", "GET", query_name) != [query_name.encode(), expected.encode()]:
                raise AssertionError("query-buffer memory grammar round trip: " + spelling)
        before = conn.must("CONFIG", "GET", query_name)
        prefix = "ERR CONFIG SET failed (possibly related to argument '%s') - " % query_name
        for spelling, reason in [
                (s, "argument must be between 1048576 and 9223372036854775807 inclusive")
                for s in ("0", "1048575", "1m", "9223372036854775808", "", "mb")] + [
                (s, "argument must be a memory value")
                for s in ("-1", "+1048576", "1.5mb", "1MiB", " 1mb")]:
            if conn.cmd("CONFIG", "SET", query_name, spelling) != _lib.RespError(prefix + reason):
                raise AssertionError("query-buffer error grammar: " + repr(spelling))
            if conn.must("CONFIG", "GET", query_name) != before:
                raise AssertionError("rejected query-buffer SET changed the limit")
        if conn.cmd("CONFIG", "SET", query_name, "1mb", query_name, "2mb") != _lib.RespError(
                b"ERR duplicate configuration parameter"):
            raise AssertionError("duplicate query-buffer SET accepted")
        if conn.must("CONFIG", "GET", query_name) != before:
            raise AssertionError("duplicate query-buffer SET changed the limit")
    finally:
        conn.must("CONFIG", "SET", query_name, values[query_name.encode()])
    for name, expected in (("thread-mode", "2s"), ("net-io", engine), ("read-local", "0"),
                           ("atomic", atomic), ("key-lb", "1"), ("client-lb", "1"),
                           ("flip-auto", "0"), ("overlap", "0"), ("reorder", "0"),
                           ("wb-policy", "1"), ("wb-small-pipe", "16"),
                           ("wb-complete-visits", "3"), ("key-lb-damping", "-1")):
        if values.get(name.encode()) != expected.encode():
            raise AssertionError("CONFIG %s differs: %r" % (name, values.get(name.encode())))
    for name in ("read-local", "key-lb", "client-lb", "key-lb-damping", "flip-auto", "net-io", "overlap", "reorder", "wb-policy",
                 "wb-small-pipe", "wb-complete-visits",
                 "hll-sparse-max-bytes", "unixsocketperm", "port", "bind", "unixsocket"):
        result = conn.cmd("CONFIG", "SET", name, values[name.encode()])
        if not isinstance(result, _lib.RespError) or "immutable" not in str(result):
            raise AssertionError("boot-only knob was mutable: " + name)
        if conn.must("CONFIG", "GET", name) != [name.encode(), values[name.encode()]]:
            raise AssertionError("rejected boot-only SET changed its GET value: " + name)
    for policy in ("no", "yes"):
        conn.must("CONFIG", "SET", "aof-load-truncated", policy)
        if conn.must("CONFIG", "GET", "aof-load-truncated") != [b"aof-load-truncated", policy.encode()]:
            raise AssertionError("AOF recovery policy did not change at runtime")
    conn.must("CONFIG", "SET", "aof-load-truncated", values[b"aof-load-truncated"])
    writeback = _lib.info(conn, "WRITEBACK")
    for name, expected in (("wb_policy", "1"), ("wb_small_pipe", "16"), ("wb_complete_visits", "3")):
        if writeback.get(name) != expected:
            raise AssertionError("INFO WRITEBACK %s differs: %r" % (name, writeback))
    server = _lib.info(conn, "server")
    for name, expected in (("thread_mode", "2s"), ("shards", "16"),
                           ("read_local", "0"), ("atomic", atomic), ("overlap", "0"), ("reorder", "0"),
                           ("key_lb", "1"), ("client_lb", "1"), ("flip_auto", "0"),
                           ("flip_fingerprint_window", "0"), ("net_io", engine), ("hash", "mix64"),
                           ("zc_min", values[b"zc-min"].decode()),
                           ("multiplexing_api", "epoll" if engine == "epoll" else "io_uring")):
        if server.get(name) != expected:
            raise AssertionError("INFO server %s differs: %r" % (name, server.get(name)))
    snapshot = _lib.lbsignals(conn)
    if len(snapshot.shards) != int(server["shards"]):
        raise AssertionError("INFO shards differs from the actual shard inventory")
    for field in ("shard_home", "shard_owners"):
        entries = [tuple(map(int, pair.split(":"))) for pair in server[field].split(",")]
        mapping = dict(entries)
        if len(entries) != len(mapping) or set(mapping) != set(range(int(server["shards"]))):
            raise AssertionError("INFO %s is not a complete shard map" % field)
        if any(owner not in {t.tid for t in snapshot.threads if t.role == "ex"}
               for owner in mapping.values()):
            raise AssertionError("INFO %s names a non-executor" % field)
    lb = _lib.info(conn, "lb")
    if (lb.get("tomokv_keylb_enabled") != "1" or
            lb.get("tomokv_clientlb_enabled") != "1" or "tomokv_lb_enabled" in lb):
        raise AssertionError("INFO LB does not report the independent switches")
    if (sum(t.role == "io" for t in snapshot.threads) != int(server["io_threads"]) or
            sum(t.role == "ex" for t in snapshot.threads) != int(server["ex_threads"])):
        raise AssertionError("INFO role counts differ from actual thread inventory")
    # A boot-only echo would pass the initial comparison. Prove INFO follows a completed live
    # update too, including zero-copy's zero/off arm, and restore the caller's setting.
    original_zc = values[b"zc-min"].decode()
    try:
        for threshold in ("0", "1" if original_zc == "0" else original_zc):
            conn.must("CONFIG", "SET", "zc-min", threshold)
            if _lib.info(conn, "server").get("zc_min") != threshold:
                raise AssertionError("INFO zc_min echoed the boot request after CONFIG SET")
    finally:
        conn.must("CONFIG", "SET", "zc-min", original_zc)
    # Fresh keys on EVERY shard prove CONFIG's fan-out, not just the global GET echo.
    by_shard = {}
    for n in range(8192):
        key = "knob:encoding:%d" % n
        by_shard.setdefault(_lib.shard_of(conn, key), key)
        if len(by_shard) == int(server["shards"]):
            break
    if len(by_shard) != int(server["shards"]):
        raise AssertionError("could not cover the complete shard inventory")
    encoding_names = ["%s-max-listpack-%s" % (kind, axis)
                      for kind in ("hash", "set", "zset") for axis in ("entries", "value")]
    encoding_names.append("list-max-listpack-size")
    encoding_names.append("set-max-intset-entries")
    original = {name: values[name.encode()] for name in encoding_names}
    created = set(by_shard.values())

    def encoding(key, expected):
        actual = conn.must("OBJECT", "ENCODING", key)
        if actual != expected:
            raise AssertionError("%s encoding %r, expected %r" % (key, actual, expected))

    def add(kind, key, n, member):
        if kind == "hash":
            return conn.must("HSET", key, "f%d" % n, member)
        if kind == "set":
            return conn.must("SADD", key, member)
        return conn.must("ZADD", key, n, member)

    try:
        for kind, expanded in (("hash", b"hashtable"), ("set", b"hashtable"),
                                ("zset", b"skiplist")):
            entries, size = (kind + "-max-listpack-" + axis for axis in ("entries", "value"))
            conn.must("CONFIG", "SET", entries, 4, size, 64)
            for key in by_shard.values():
                conn.must("DEL", key)
                for n in range(4):
                    add(kind, key, n, "m%d" % n)
                encoding(key, b"listpack")
                add(kind, key, 4, "m4")
                encoding(key, expanded)
                # RESTORE must use the destination's live limits too.
                dump = conn.must("DUMP", key)
                conn.must("CONFIG", "SET", entries, 8)
                conn.must("RESTORE", key, 0, dump, "REPLACE")
                encoding(key, b"listpack")
                conn.must("CONFIG", "SET", entries, 4)
            conn.must("CONFIG", "SET", entries, 8, size, 4)
            for key in by_shard.values():
                conn.must("DEL", key)
                add(kind, key, 0, "xxxx")
                encoding(key, b"listpack")
                add(kind, key, 1, "xxxxx")
                encoding(key, expanded)
            conn.must("CONFIG", "SET", entries, 0)
            key = next(iter(by_shard.values()))
            conn.must("DEL", key)
            add(kind, key, 0, "x")
            encoding(key, expanded)
            conn.must("CONFIG", "SET", entries, original[entries], size, original[size])

        # Integer and listpack limits are independent, and CONFIG must reach every owner.
        conn.must("CONFIG", "SET", "set-max-listpack-entries", 0, "set-max-listpack-value", 0,
                  "set-max-intset-entries", 9)
        for key in by_shard.values():
            conn.must("DEL", key)
            conn.must("SADD", key, *range(9))
            encoding(key, b"intset")
            conn.must("SADD", key, 9)
            encoding(key, b"hashtable")
        conn.must("CONFIG", "SET", "set-max-intset-entries", original["set-max-intset-entries"])
        key = next(iter(by_shard.values()))
        conn.must("DEL", key)
        count = int(original["set-max-intset-entries"])
        conn.must("SADD", key, *range(count))
        encoding(key, b"intset")
        conn.must("SADD", key, count)
        encoding(key, b"hashtable")

        for fill, count in ((0, 1), (4, 4)):
            conn.must("CONFIG", "SET", "list-max-listpack-size", fill)
            for key in by_shard.values():
                conn.must("DEL", key)
                conn.must("RPUSH", key, *(["x"] * count))
                encoding(key, b"listpack")
                conn.must("RPUSH", key, "y")
                encoding(key, b"quicklist")
                if conn.must("LRANGE", key, 0, -1) != [b"x"] * count + [b"y"]:
                    raise AssertionError("list promotion lost content")

        # Both lists exceed either compact budget: different memory use witnesses that the
        # expanded node builder also consumes the knob. A promotion-only repair fails here.
        memory = []
        for fill in (-1, -3):
            conn.must("CONFIG", "SET", "list-max-listpack-size", fill)
            key = "knob:node:%d" % fill
            created.add(key)
            conn.must("DEL", key)
            conn.must("RPUSH", key, *(["x" * 128] * 512))
            encoding(key, b"quicklist")
            memory.append(conn.must("MEMORY", "USAGE", key))
        if memory[0] <= memory[1]:
            raise AssertionError("list node budgets had no observable effect: %r" % memory)

        for canonical, alias in (("hash-max-listpack-entries", "hash-max-ziplist-entries"),
                                 ("hash-max-listpack-value", "hash-max-ziplist-value"),
                                 ("zset-max-listpack-entries", "zset-max-ziplist-entries"),
                                 ("zset-max-listpack-value", "zset-max-ziplist-value"),
                                 ("list-max-listpack-size", "list-max-ziplist-size"),
                                 ("hash-max-listpack-entries", "hash-max-compact-entries"),
                                 ("hash-max-listpack-value", "hash-max-compact-value"),
                                 ("zset-max-listpack-entries", "zset-max-compact-entries"),
                                 ("zset-max-listpack-value", "zset-max-compact-value")):
            conn.must("CONFIG", "SET", alias, 7)
            for spelling in (canonical, alias):
                if conn.must("CONFIG", "GET", spelling) != [spelling.encode(), b"7"]:
                    raise AssertionError("encoding alias is not one shared value: " + spelling)
            conn.must("CONFIG", "SET", canonical, 8, alias, 9)
            for spelling in (canonical, alias):
                if conn.must("CONFIG", "GET", spelling) != [spelling.encode(), b"9"]:
                    raise AssertionError("last alias value did not win: " + spelling)
            if not isinstance(conn.cmd("CONFIG", "SET", canonical, 8, canonical, 10), _lib.RespError):
                raise AssertionError("repeated Redis spelling accepted in one CONFIG SET")
            if conn.must("CONFIG", "GET", canonical) != [canonical.encode(), b"9"]:
                raise AssertionError("rejected duplicate changed the setting")
        for name, value, expected in (("hash-max-listpack-value", "1kb", b"1024"),
                                      ("zset-max-listpack-value", "2k", b"2000"),
                                      ("hash-max-listpack-entries", "9223372036854775807",
                                       b"9223372036854775807"),
                                      ("list-max-listpack-size", "-2147483648", b"-2147483648")):
            conn.must("CONFIG", "SET", name, value)
            if conn.must("CONFIG", "GET", name)[1] != expected:
                raise AssertionError("reference grammar did not round-trip: " + name)
        for name, bad in (("set-max-listpack-value", "1kb"),
                          ("set-max-listpack-entries", "01"),
                          ("hash-max-listpack-entries", "9223372036854775808"),
                          ("list-max-listpack-size", "2147483648")):
            before = conn.must("CONFIG", "GET", name)
            if not isinstance(conn.cmd("CONFIG", "SET", name, bad), _lib.RespError):
                raise AssertionError("invalid reference grammar accepted: " + name)
            if conn.must("CONFIG", "GET", name) != before:
                raise AssertionError("invalid encoding update changed state")
    finally:
        conn.must("CONFIG", "SET", *(item for pair in original.items() for item in pair))
        conn.must("DEL", *sorted(created))
    print("configuration grammar, live encoding controls and actual geometry verified")
finally:
    conn.close()
