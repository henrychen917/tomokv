"""CC11/CC12/CC13/CC18 wire differentials, called by differ.py on owned listeners."""
from pathlib import Path
import select
import time
import _lib

FLAGS = ("", "AKE", "AKEn", "gnK", "gKn", "Em", "KEA", "$lshzxe",
         "g$lshzxetdnKEm", "n", "nKmE", "AEmn")
EXPECTED_FLAGS = dict(zip(FLAGS, ("", "AKE", "AKE", "gnK", "gnK", "Em", "AKE",
                                "$lshzxe", "AKEm", "n", "nKEm", "AEm")))
COUNTERS = (b"calls", b"rejected_calls")


def commandstats(payload, target=False):
    if not isinstance(payload, bytes):
        raise AssertionError("INFO commandstats is not a bulk/verbatim reply")
    result = {}
    for line in payload.split(b"\r\n"):
        if not line.startswith(b"cmdstat_"):
            continue
        name, values = line.split(b":", 1)
        fields = [part.split(b"=", 1) for part in values.split(b",")]
        if target and tuple(k for k, _ in fields) != COUNTERS:
            raise AssertionError("unexpected target commandstats fields: %r" % line)
        members = dict(fields)
        if not all(k in members for k in COUNTERS):
            raise AssertionError("missing commandstats counters: %r" % line)
        result[name] = tuple(int(members[k]) for k in COUNTERS)
    return result


def run(api):
    conn_mode, enc = api["conn_mode"], api["enc"]
    read_reply, parse = api["read_reply"], api["parse_reply"]
    endpoints = ((api["TH"], api["TP"]), (api["OH"], api["OP"]))
    opened = []
    checks = 0

    def connect(endpoint):
        pair = conn_mode(*endpoint, False, buffering=0)
        opened.append(pair)
        return pair

    def issue(pair, args):
        pair[0].sendall(enc(args))
        return read_reply(pair[1])

    admins = [connect(endpoint) for endpoint in endpoints]

    def equal(args, expected=None, pairs=None):
        nonlocal checks
        replies = [issue(pair, args) for pair in (pairs or admins)]
        assert replies[0] == replies[1], (args, replies)
        if expected is not None:
            assert replies[0] == expected, (args, replies, expected)
        api["coverage"].note(args)
        checks += 1
        return replies[0]

    def stats(expected, others=None):
        nonlocal checks
        replies = [issue(pair, ["INFO", "commandstats"]) for pair in admins]
        rows = [commandstats(parse(reply), target=(i == 0)) for i, reply in enumerate(replies)]
        values = [row.get(b"cmdstat_get", (0, 0)) for row in rows]
        assert values[0] == values[1] == expected, ("CC18 GET", values, expected, replies)
        for name, wanted in (others or {}).items():
            key = b"cmdstat_" + name.encode()
            actual = [row.get(key, (0, 0)) for row in rows]
            assert actual[0] == actual[1] == wanted, ("CC18", name, actual, wanted, replies)
        api["coverage"].note(["INFO", "commandstats"], "commandstats counters")
        checks += 1

    def failed_deviation(label, command):
        nonlocal checks
        replies = [parse(issue(pair, ["INFO", "commandstats"])) for pair in admins]
        prefix = b"cmdstat_" + command.encode() + b":"
        lines = [next(line for line in reply.split(b"\r\n") if line.startswith(prefix))
                 for reply in replies]
        fields = [dict(member.split(b"=", 1) for member in line.split(b":", 1)[1].split(b","))
                  for line in lines]
        assert tuple(fields[0]) == COUNTERS, (label, lines)
        assert b"failed_calls" not in fields[0], (label, lines)
        assert int(fields[1][b"failed_calls"]) > 0, (label, lines)
        checks += 1
        print("  EXPECTED-DEVIATION CC18 %s: failed_calls omitted; Redis reports %s" %
              (label, fields[1][b"failed_calls"].decode()))

    try:
        # CC12: compare complete RESP frames AND Redis's canonical spellings.
        for flags in FLAGS:
            equal(["CONFIG", "SET", "notify-keyspace-events", flags], b"+OK\r\n")
            reply = equal(["CONFIG", "GET", "notify-keyspace-events"])
            assert parse(reply) == [b"notify-keyspace-events", EXPECTED_FLAGS[flags].encode()]
        equal(["CONFIG", "SET", "notify-keyspace-events", ""], b"+OK\r\n")

        # CC13: the harness boots both with the SAME filename so the complete error is comparable.
        paths = [parse(issue(pair, ["CONFIG", "GET", "aclfile"])) for pair in admins]
        assert paths[0] == paths[1] and paths[0][0] == b"aclfile" and paths[0][1], paths
        path = Path(paths[0][1].decode())
        original = path.read_bytes()
        try:
            path.write_bytes(b"user ccfix_broken bogusrule\n")
            expected = (b"-ERR " + str(path).encode() + b":1: Syntax error. WARNING: ACL errors "
                        b"detected, no change to the previously active ACL rules was performed\r\n")
            equal(["ACL", "LOAD"], expected)
            # Failed LOAD must preserve the previously working default user's permissions.
            equal(["PING"], b"+PONG\r\n")
        finally:
            path.write_bytes(original)

        # CC11: deterministic same-shard and different-shard sources. A marker on the same
        # channel fences each batch; an absent keymiss is a zero count, never a timeout skip.
        equal(["FLUSHALL"], b"+OK\r\n")
        by_shard = {}
        for candidate in range(1024):
            key = "ccfix:%04d" % candidate
            reply = issue(admins[0], ["DEBUG", "SHARD", key])
            assert reply.startswith(b":"), reply
            shard = int(reply[1:-2])
            by_shard.setdefault(shard, []).append(key)
            if len(by_shard.get(0, [])) >= 4 and len(by_shard.get(1, [])) >= 2:
                break
        assert len(by_shard.get(0, [])) >= 4 and len(by_shard.get(1, [])) >= 2, by_shard
        channel = "__keyevent@0__:keymiss"
        subscribers = [connect(endpoint) for endpoint in endpoints]
        equal(["CONFIG", "SET", "notify-keyspace-events", "Em"], b"+OK\r\n")
        equal(["SUBSCRIBE", channel], pairs=subscribers)
        serial = 0

        def misses(args, expected_keys, target_result=None, pending_deviation=False):
            nonlocal serial, checks
            if target_result is None:
                equal(args)
            else:
                oracle_result = issue(admins[1], args)
                assert target_result == oracle_result, (args, target_result, oracle_result)
                api["coverage"].note(args)
                checks += 1
            marker = ("ccfix:barrier:%d" % serial).encode()
            serial += 1
            equal(["PUBLISH", channel, marker], b":1\r\n")
            observed = []
            for sub in subscribers:
                messages = []
                while True:
                    message = parse(read_reply(sub[1]))
                    assert isinstance(message, list) and len(message) == 3, message
                    assert message[:2] == [b"message", channel.encode()], message
                    if message[2] == marker:
                        break
                    messages.append(message[2])
                    assert len(messages) <= len(expected_keys) + 8, (args, messages)
                observed.append(sorted(messages))
            expected = sorted(k.encode() for k in expected_keys)
            assert observed[1] == expected, ("CC11 oracle", args, observed, expected)
            target_expected = [] if pending_deviation else expected
            assert observed[0] == target_expected, ("CC11 target", args, observed, target_expected)
            api["coverage"].note(args, "keymiss frames")
            checks += 1

        local = by_shard[0]
        for label, sources in (("local", local[1:3]), ("cross", [local[1], by_shard[1][0]])):
            dest = local[0] if label == "local" else by_shard[1][1]
            a, b = sources
            misses(["COPY", a, dest], [a])
            misses(["COPY", a, a], [])
            for cmd in ("SINTERSTORE", "SUNIONSTORE", "SDIFFSTORE"):
                misses([cmd, dest, a, b], [a, b])
                # Destination and source have equal bytes, but only the source lookup is a read.
                misses([cmd, a, a, b], [a, b])
            for operation in ("AND", "OR", "XOR"):
                misses(["BITOP", operation, dest, a, b], [a, b])
                misses(["BITOP", operation, a, a, b], [a, b])
            misses(["BITOP", "NOT", dest, a], [a])
            misses(["GET", a], [a])
            misses(["DEL", a, b, dest], [])
            misses(["SET", a, "v"], [])
            misses(["COPY", a, dest], [])
            misses(["DEL", a, dest], [])
            equal(["SADD", a, "v"], b":1\r\n")
            equal(["SADD", b, "w"], b":1\r\n")
            for cmd in ("SINTERSTORE", "SUNIONSTORE", "SDIFFSTORE"):
                misses([cmd, dest, a, b], [])
            misses(["DEL", a, b, dest], [])
            print("  CC11 %s source/destination lookups: exact" % label)

        # The same persistent commit latch and owner geometry helpers used by the
        # atomics tests. No probabilistic delay: leave the writer undecided until
        # the real reader has resolved each pending source to its predecessor.
        probe = _lib.Conn(*endpoints[0], timeout=10)
        try:
            atomic = int(_lib.info(probe, "server")["atomic"])
            assert atomic in (0, 1)
            if atomic:
                for verb in ("COPY", "SINTERSTORE", "BITOP"):
                    equal(["FLUSHALL"], b"+OK\r\n")
                    deadline = time.monotonic() + 5
                    while int(_lib.info(probe, "stats")["atomic_pending_entries"]):
                        assert time.monotonic() < deadline, "old atomic records did not drain"
                        time.sleep(.005)
                    buckets = _lib.owner_buckets(probe, "ccfix2:%s:%d:" % (verb, time.time_ns()),
                                                per_owner=2)
                    owners = [keys for keys in buckets.values() if len(keys) >= 2][:2]
                    a, b, dest = owners[0][0], owners[1][0], owners[1][1]
                    args = ([verb, a, dest] if verb == "COPY" else
                            [verb, "OR", dest, a, b] if verb == "BITOP" else
                            [verb, dest, a, b])
                    wanted = [a] if verb == "COPY" else [a, b]
                    writer, reader = connect(endpoints[0]), connect(endpoints[0])
                    before = _lib.info(probe, "stats")
                    with _lib.armed(probe, "ATOMIC-COMMIT-HOLD", 1):
                        writer[0].sendall(enc(["MSET", a, "private", b, "private"]))
                        deadline = time.monotonic() + 5
                        while True:
                            held = _lib.info(probe, "stats")
                            if int(held["atomic_pending_entries"]) >= 2:
                                break
                            assert time.monotonic() < deadline, "pending-source window never opened"
                            time.sleep(.005)
                        assert not select.select([writer[0]], [], [], 0)[0], "writer escaped hold"
                        predecessor = int(held["atomic_predecessor_reads"])
                        reader[0].sendall(enc(args))
                        deadline = time.monotonic() + 5
                        while True:
                            observed = _lib.info(probe, "stats")
                            if int(observed["atomic_predecessor_reads"]) - predecessor >= len(wanted):
                                break
                            assert time.monotonic() < deadline, "reader never visited pending sources"
                            time.sleep(.005)
                        assert int(observed["atomic_pending_entries"]) >= 2
                        assert int(observed["atomic_localfast"]) == int(before["atomic_localfast"]), \
                            "pending witness took localfast instead of scatter"
                        assert not select.select([writer[0]], [], [], 0)[0], "writer committed early"
                    assert read_reply(writer[1]) == b"+OK\r\n"
                    misses(args, wanted, read_reply(reader[1]), pending_deviation=True)
                    print("  EXPECTED-DEVIATION CC11 pending %s: no keymiss; "
                          "source records and predecessor reads witnessed, Redis emits %d" %
                          (verb, len(wanted)))
        finally:
            probe.close()
        equal(["CONFIG", "SET", "notify-keyspace-events", ""], b"+OK\r\n")

        # CC18: a denied command is rejected, an executed WRONGTYPE is a failed call.
        equal(["ACL", "SETUSER", "ccfix_denied", "reset", "on", ">ccfix-password",
               "~*", "+@all", "-get"], b"+OK\r\n")
        denied = [connect(endpoint) for endpoint in endpoints]
        equal(["AUTH", "ccfix_denied", "ccfix-password"], b"+OK\r\n", denied)
        equal(["CONFIG", "RESETSTAT"], b"+OK\r\n")
        equal(["GET", "ccfix:wrongtype"],
              b"-NOPERM User ccfix_denied has no permissions to run the 'get' command\r\n", denied)
        stats((0, 1))
        equal(["RPUSH", "ccfix:wrongtype", "v"], b":1\r\n")
        equal(["GET", "ccfix:wrongtype"],
              b"-WRONGTYPE Operation against a key holding the wrong kind of value\r\n")
        stats((1, 1))
        failed_deviation("executed WRONGTYPE", "get")
        equal(["GET", "ccfix:absent"], b"$-1\r\n")
        stats((2, 1))
        equal(["MULTI"], b"+OK\r\n")
        equal(["GET", "ccfix:wrongtype"], b"+QUEUED\r\n")
        equal(["EXEC"], b"*1\r\n-WRONGTYPE Operation against a key holding the wrong kind of value\r\n")
        stats((3, 1), {"multi": (1, 0), "exec": (1, 0)})
        equal(["EXEC"], b"-ERR EXEC without MULTI\r\n")
        stats((3, 1), {"exec": (2, 0)})
        failed_deviation("MULTI member", "get")
        failed_deviation("EXEC own error", "exec")
        equal(["EVAL", "return {{err='ERR one'},{err='ERR two'}}", "0"],
              b"*2\r\n-ERR one\r\n-ERR two\r\n")
        failed_deviation("Lua error array", "eval")
        equal(["EVAL", "return redis.pcall('GET',KEYS[1])", "1", "ccfix:wrongtype"],
              b"-WRONGTYPE Operation against a key holding the wrong kind of value\r\n")
        failed_deviation("Lua forwarded error", "eval")
        equal(["CONFIG", "RESETSTAT"], b"+OK\r\n")
        equal(["CONFIG", "SET", "requirepass", "ccfix-password"], b"+OK\r\n")
        try:
            noauth = [connect(endpoint) for endpoint in endpoints]
            equal(["GET", "ccfix:absent"], b"-NOAUTH Authentication required.\r\n", noauth)
            stats((0, 1))
        finally:
            equal(["CONFIG", "SET", "requirepass", ""], b"+OK\r\n")
        equal(["CONFIG", "RESETSTAT"], b"+OK\r\n")
        stats((0, 0))
        equal(["ACL", "DELUSER", "ccfix_denied"], b":1\r\n")
        print("DIFFER ccfix: %d exact comparisons -> PASS" % checks)
        return 0
    finally:
        # Preserve later suites even when a PRE arm fails one of these assertions.
        for pair in admins:
            for command in (["CONFIG", "SET", "notify-keyspace-events", ""],
                            ["CONFIG", "SET", "requirepass", ""],
                            ["ACL", "DELUSER", "ccfix_denied"]):
                try:
                    issue(pair, command)
                except (OSError, EOFError):
                    pass
        for sock, file in opened:
            file.close()
            sock.close()
