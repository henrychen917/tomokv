#!/usr/bin/env python3
"""Redis 7.4 blocking compatibility, with actual parking and exact oracle replies."""
from _lib import Conn, RespError, encode, info
from compat3_lib import equal, run
from compat3_blockfix import parked


def waiter(c, clients, *args):
    w = Conn(c.host, c.port, timeout=3, buffering=0)
    clients.append(w)
    before = int(info(c, "clients")["blocked_clients"])
    w.send(*args)
    parked(c, before + 1)
    return w


def rename_sort(c, clients):
    out = []
    for command in ("BLPOP", "BLMPOP"):
        for source, target in (("src{t}", "dst{t}"), ("source", "destination")):
            for trigger in ("RENAME", "SORT"):
                c.cmd("DEL", source, target)
                args = (command, target, 0) if command == "BLPOP" else (command, 0, 1, target, "LEFT")
                w = waiter(c, clients, *args)
                equal(c.cmd("RPUSH", source, "c", "a", "b"), 3, "seed source")
                result = c.cmd("RENAME", source, target) if trigger == "RENAME" else c.cmd("SORT", source, "ALPHA", "STORE", target)
                equal(result, b"OK" if trigger == "RENAME" else 3, "creator reply")
                value = b"c" if trigger == "RENAME" else b"a"
                expected = [target.encode(), value if command == "BLPOP" else [value]]
                equal(w.read(), expected, "destination wakes exact waiter")
                out.append([result, expected, c.cmd("LRANGE", target, 0, -1)])
                parked(c, 0)
    for with_group in (False, True):
        c.cmd("DEL", "stream{t}", "other{t}")
        c.cmd("XGROUP", "CREATE", "stream{t}", "g", "$", "MKSTREAM")
        w = waiter(c, clients, "XREADGROUP", "GROUP", "g", "c", "BLOCK", 0, "STREAMS", "stream{t}", ">")
        if with_group: c.cmd("XGROUP", "CREATE", "other{t}", "g", "$", "MKSTREAM")
        c.cmd("XADD", "other{t}", "1-0", "f", "v")
        equal(c.cmd("RENAME", "other{t}", "stream{t}"), b"OK", "stream replacement")
        got = w.read()
        if with_group: equal(got, [[b"stream{t}", [[b"1-0", [b"f", b"v"]]]]], "renamed group data")
        else: assert isinstance(got, RespError) and str(got).startswith("NOGROUP"), repr(got)
        out.append(got); parked(c, 0)
    return out


def removed(c, clients):
    out = []
    actions = [("DEL", "stream"), ("UNLINK", "stream"), ("SET", "stream", "v"),
               ("MSET", "stream", "v", "other", "v"), ("FLUSHALL",), ("FLUSHDB",),
               ("XGROUP", "DESTROY", "stream", "g"), ("transaction",)]
    for action in actions:
        c.cmd("DEL", "stream")
        c.cmd("XGROUP", "CREATE", "stream", "g", "$", "MKSTREAM")
        w = waiter(c, clients, "XREADGROUP", "GROUP", "g", "c", "BLOCK", 0, "STREAMS", "stream", ">")
        if action[0] == "transaction":
            c.cmd("MULTI"); c.cmd("DEL", "stream"); c.cmd("SADD", "stream", "v")
            result = c.cmd("EXEC")
            equal(result, [1, 1], "transaction reply")
        else: result = c.cmd(*action)
        try: got = w.read()
        except TimeoutError as exc: raise AssertionError(f"{action} never woke its group reader") from exc
        prefix = "WRONGTYPE" if action[0] in ("SET", "MSET", "transaction") else "NOGROUP"
        assert isinstance(got, RespError) and str(got).startswith(prefix), (action, got)
        out.append([result, got, c.cmd("TYPE", "stream")]); parked(c, 0)
    # A list waiter must not hide a group waiter on the same key.
    c.cmd("DEL", "mixed")
    a = waiter(c, clients, "BLPOP", "mixed", 0)
    c.cmd("XGROUP", "CREATE", "mixed", "g", "$", "MKSTREAM")
    b = waiter(c, clients, "XREADGROUP", "GROUP", "g", "c", "BLOCK", 0, "STREAMS", "mixed", ">")
    c.cmd("DEL", "mixed")
    got = b.read(); assert isinstance(got, RespError) and str(got).startswith("NOGROUP"), repr(got)
    parked(c, 1); c.cmd("RPUSH", "mixed", "x")
    equal(a.read(), [b"mixed", b"x"], "list waiter survives stream removal")
    parked(c, 0); out.append(got)
    # Fresh registrations also cover owner cleanup racing the next dispatch.
    # Every attempt must observe the deletion boundary, with no skipped window.
    for delete in (("DEL", "boundary"), ("UNLINK", "boundary"),
                   ("DEL", "boundary", "other-owner")) * 8:
        c.cmd("DEL", "boundary", "other-owner")
        c.cmd("XGROUP", "CREATE", "boundary", "g", "$", "MKSTREAM")
        w = waiter(c, clients, "XREADGROUP", "GROUP", "g", "c", "BLOCK", 0,
                   "STREAMS", "boundary", ">")
        c.raw(b"".join(encode(*command) for command in (
            delete,
            ("XGROUP", "CREATE", "boundary", "g", "$", "MKSTREAM"),
            ("XADD", "boundary", "1-0", "f", "v"))))
        equal([c.read(), c.read(), c.read()], [1, b"OK", b"1-0"], "pipeline replies")
        got = w.read()
        assert isinstance(got, RespError) and str(got).startswith("NOGROUP"), (
            "deleted group's waiter must not consume recreated stream", delete, got)
        parked(c, 0); out.append(got)
        equal(c.cmd("XPENDING", "boundary", "g"), [0, None, None, None],
              "recreated group has no inherited delivery")
        equal(c.cmd("XINFO", "CONSUMERS", "boundary", "g"), [],
              "recreated group has no inherited consumer")
        equal(c.cmd("XREADGROUP", "GROUP", "g", "new", "STREAMS", "boundary", ">"),
              [[b"boundary", [[b"1-0", [b"f", b"v"]]]]], "new consumer owns new entry")
    # RENAME recreates a group without running XGROUP CREATE on the target.
    # It must preserve the same deletion boundary, including atomic cleanup.
    for delete in (("DEL", "boundary"), ("DEL", "boundary", "other-owner")) * 8:
        c.cmd("DEL", "boundary", "other-owner")
        c.cmd("XGROUP", "CREATE", "boundary", "g", "$", "MKSTREAM")
        w = waiter(c, clients, "XREADGROUP", "GROUP", "g", "c", "BLOCK", 0,
                   "STREAMS", "boundary", ">")
        c.cmd("XGROUP", "CREATE", "replacement", "g", "$", "MKSTREAM")
        c.raw(b"".join(encode(*command) for command in (
            delete, ("RENAME", "replacement", "boundary"),
            ("XADD", "boundary", "1-0", "f", "v"))))
        equal([c.read(), c.read(), c.read()], [1, b"OK", b"1-0"], "RENAME pipeline replies")
        got = w.read()
        assert isinstance(got, RespError) and str(got).startswith("NOGROUP"), (
            "deleted group's waiter must not consume recreated stream", delete, "RENAME", got)
        parked(c, 0); out.append(got)
        equal(c.cmd("XPENDING", "boundary", "g"), [0, None, None, None],
              "renamed group has no inherited delivery")
        equal(c.cmd("XINFO", "CONSUMERS", "boundary", "g"), [],
              "renamed group has no inherited consumer")
    # EXEC's command boundary is the whole transaction: recreation inside it
    # retains the waiter and delivers the replacement group's committed data.
    c.cmd("DEL", "boundary")
    c.cmd("XGROUP", "CREATE", "boundary", "g", "$", "MKSTREAM")
    w = waiter(c, clients, "XREADGROUP", "GROUP", "g", "c", "BLOCK", 0,
               "STREAMS", "boundary", ">")
    c.cmd("MULTI")
    c.cmd("DEL", "boundary")
    c.cmd("XGROUP", "CREATE", "boundary", "g", "$", "MKSTREAM")
    c.cmd("XADD", "boundary", "1-0", "f", "v")
    equal(c.cmd("EXEC"), [1, b"OK", b"1-0"], "EXEC replies")
    got = w.read()
    equal(got, [[b"boundary", [[b"1-0", [b"f", b"v"]]]]], "EXEC publication boundary")
    parked(c, 0); out.append(got)
    # Accounting belongs to each failed command, not its producer or key. A
    # surviving group on the same stream must neither fail nor be charged.
    c.cmd("CONFIG", "RESETSTAT")
    c.cmd("XGROUP", "CREATE", "accounting", "gone", "$", "MKSTREAM")
    c.cmd("XGROUP", "CREATE", "accounting", "live", "$")
    failed = [waiter(c, clients, "XREADGROUP", "GROUP", "gone", who, "BLOCK", 0,
                     "STREAMS", "accounting", ">") for who in ("one", "two")]
    live = waiter(c, clients, "XREADGROUP", "GROUP", "live", "three", "BLOCK", 0,
                  "STREAMS", "accounting", ">")
    equal(c.cmd("XGROUP", "DESTROY", "accounting", "gone"), 1, "destroy one group")
    for w in failed:
        got = w.read()
        assert isinstance(got, RespError) and str(got).startswith("NOGROUP"), got
    parked(c, 1)
    c.cmd("XADD", "accounting", "1-0", "f", "v")
    equal(live.read(), [[b"accounting", [[b"1-0", [b"f", b"v"]]]]], "other group survives")
    parked(c, 0)
    equal(info(c, "errorstats").get("errorstat_NOGROUP"), "count=2", "NOGROUP replies counted once")
    equal(info(c, "default").get("errorstat_NOGROUP"), "count=2", "default INFO includes Errorstats")
    equal(info(c).get("errorstat_NOGROUP"), "count=2", "bare INFO includes Errorstats")
    equal(info(c, "stats").get("total_error_replies"), "2", "total NOGROUP errors")
    stats = dict(field.split("=", 1) for field in info(c, "commandstats")["cmdstat_xreadgroup"].split(","))
    equal([stats.get(k) for k in ("calls", "rejected_calls", "failed_calls")], ["3", "0", "2"],
          "failed blocked commands counted once")
    c.cmd("CONFIG", "RESETSTAT")
    equal(info(c, "errorstats").get("errorstat_NOGROUP"), None, "RESETSTAT clears NOGROUP")
    equal(info(c, "stats").get("total_error_replies"), "0", "RESETSTAT clears total errors")
    equal(info(c, "commandstats").get("cmdstat_xreadgroup"), None, "RESETSTAT clears command failures")
    out.append(["NOGROUP", 2, "xreadgroup", 3, 0, 2])
    return out


def wrongtype(c, clients):
    out = []
    for command in ("BRPOPLPUSH", "BLMOVE"):
        for source, bad, good in (("q{t}", "bad{t}", "ok{t}"), ("queue", "bad", "good")):
            c.cmd("DEL", source, bad, good); c.cmd("SET", bad, "string")
            args = lambda dest: (command, source, dest, 0) if command == "BRPOPLPUSH" else (command, source, dest, "RIGHT", "LEFT", 0)
            a = waiter(c, clients, *args(bad)); b = waiter(c, clients, *args(good))
            equal(c.cmd("LPUSH", source, "value"), 1, "producer reply")
            error = a.read(); equal(error, RespError("WRONGTYPE Operation against a key holding the wrong kind of value"), "wrong destination")
            equal(b.read(), b"value", "next move gets retained element")
            equal(c.cmd("LRANGE", source, 0, -1), [], "source drained")
            equal(c.cmd("LRANGE", good, 0, -1), [b"value"], "destination owns element")
            out.append([error, c.cmd("GET", bad)]); parked(c, 0)
    return out


def multi(c, clients):
    # EXEC must finish immediately; a broken BLOCK 0 must hit a bounded deadline.
    c.sock.settimeout(3)
    c.cmd("XGROUP", "CREATE", "stream", "g", "$", "MKSTREAM")
    out = []
    for timeout in (0, 50000):
        c.cmd("MULTI")
        c.cmd("XREADGROUP", "GROUP", "g", "c", "BLOCK", timeout, "STREAMS", "stream", ">")
        c.cmd("PING")
        equal(c.cmd("EXEC"), [None, b"PONG"], "EXEC ignores blocking timeout")
        parked(c, 0)
    c.cmd("XADD", "stream", "1-0", "f", "v")
    c.cmd("MULTI"); c.cmd("XREADGROUP", "GROUP", "g", "c", "BLOCK", 0, "STREAMS", "stream", ">")
    got = c.cmd("EXEC"); equal(got, [[[b"stream", [[b"1-0", [b"f", b"v"]]]]]], "EXEC delivers available entries")
    out.append(got)
    return out


def counts(c, clients):
    out = []
    def check(keys, missing):
        values = info(c, "clients")
        got = [int(values["total_blocking_keys"]), int(values["total_blocking_keys_on_nokey"])]
        equal(got, [keys, missing], "distinct blocking keys, including nokey listeners")
        out.append(got)
    check(0, 0)
    a = waiter(c, clients, "BLPOP", "a", "b", "a", 0); check(2, 0)
    b = waiter(c, clients, "BLPOP", "a", 0); check(2, 0)
    c.cmd("XGROUP", "CREATE", "s", "g", "$", "MKSTREAM")
    s = waiter(c, clients, "XREADGROUP", "GROUP", "g", "c", "BLOCK", 0, "STREAMS", "s", ">")
    check(3, 1)
    c.cmd("LPUSH", "b", "x"); equal(a.read(), [b"b", b"x"], "first multikey waiter"); check(2, 1)
    c.cmd("LPUSH", "a", "y"); equal(b.read(), [b"a", b"y"], "remaining alias"); check(1, 1)
    c.cmd("XADD", "s", "1-0", "f", "v"); s.read(); parked(c, 0); check(0, 0)
    return out


def slowlog(c, clients):
    out = []
    c.cmd("CONFIG", "SET", "slowlog-log-slower-than", -1)
    w = waiter(c, clients, "BLPOP", "list", 0)
    c.cmd("SLOWLOG", "RESET")
    c.cmd("CONFIG", "SET", "slowlog-log-slower-than", 0)
    c.cmd("LPUSH", "list", "value")
    equal(w.read(), [b"list", b"value"], "served BLPOP")
    parked(c, 0)
    entries = c.cmd("SLOWLOG", "GET", -1)
    matches = [e for e in entries if e[3] == [b"BLPOP", b"list", b"0"]]
    equal(len(matches), 1, "served blocked command logged once under original arguments")
    out.append(matches[0][3])
    c.cmd("CONFIG", "SET", "slowlog-log-slower-than", -1)
    return out


def probe(c, case):
    clients = []
    try: return dict(rename=rename_sort, removed=removed, wrongtype=wrongtype,
                     multi=multi, counts=counts, slowlog=slowlog)[case](c, clients)
    finally:
        for w in clients: w.close()


if __name__ == "__main__":
    run(probe, ("rename", "removed", "wrongtype", "multi", "counts", "slowlog"))
