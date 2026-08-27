#!/usr/bin/env python3
"""Directed RESP3/HELLO protocol and shape battery."""
import socket
import sys

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 6379
checks = 0


class Frame:
    def __init__(self, kind, value):
        self.kind = kind
        self.value = value

    def __repr__(self):
        return "Frame(%r, %r)" % (self.kind, self.value)


def encode(args):
    out = b"*%d\r\n" % len(args)
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        out += b"$%d\r\n%s\r\n" % (len(arg), arg)
    return out


def read_frame(file):
    line = file.readline()
    if not line:
        raise EOFError("connection closed")
    if not line.endswith(b"\r\n"):
        raise AssertionError("truncated frame header %r" % line)
    kind = line[:1]
    payload = line[1:-2]
    if kind in (b"+", b"-", b":", b",", b"#", b"("):
        return Frame(kind, payload)
    if kind == b"_":
        return Frame(kind, None)
    if kind in (b"$", b"=", b"!"):
        length = int(payload)
        if length == -1:
            return Frame(kind, None)
        body = file.read(length + 2)
        if len(body) != length + 2 or body[-2:] != b"\r\n":
            raise AssertionError("truncated length frame")
        return Frame(kind, body[:-2])
    if kind in (b"*", b"~", b">"):
        count = int(payload)
        if count == -1:
            return Frame(kind, None)
        return Frame(kind, [read_frame(file) for _ in range(count)])
    if kind in (b"%", b"|"):
        return Frame(kind, [(read_frame(file), read_frame(file)) for _ in range(int(payload))])
    raise AssertionError("unknown RESP marker %r" % kind)


class Client:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=10)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def command(self, *args):
        self.sock.sendall(encode(args))
        return read_frame(self.file)

    def close(self):
        self.sock.close()


def expect(condition, label, detail=None):
    global checks
    checks += 1
    if not condition:
        raise AssertionError("%s%s" % (label, ": %r" % detail if detail is not None else ""))


def bulk(frame):
    expect(frame.kind == b"$", "bulk frame", frame)
    return frame.value


def map_values(frame):
    expect(frame.kind == b"%", "map frame", frame)
    result = {}
    for key, value in frame.value:
        expect(key.kind == b"$", "map bulk key", key)
        result[key.value] = value
    return result


def hello_matrix():
    client = Client()
    bare = client.command("HELLO")
    expect(bare.kind == b"*" and len(bare.value) == 14, "bare HELLO stays RESP2", bare)
    client.close()

    client = Client()
    hello = client.command("HELLO", "3")
    values = map_values(hello)
    expect(set(values) == {b"server", b"version", b"proto", b"id", b"mode", b"role", b"modules"},
           "HELLO full seven-field map", values)
    expect(values[b"proto"].kind == b":" and values[b"proto"].value == b"3",
           "HELLO reports negotiated proto", values[b"proto"])
    expect(values[b"modules"].kind == b"*", "HELLO modules array", values[b"modules"])
    expect(client.command("HELLO").kind == b"%", "bare HELLO preserves RESP3")
    named = client.command("HELLO", "3", "SETNAME", "resp3-directed")
    expect(named.kind == b"%", "HELLO SETNAME")
    expect(client.command("CLIENT", "GETNAME").value == b"resp3-directed", "HELLO name applied")
    downgraded = client.command("HELLO", "2")
    expect(downgraded.kind == b"*" and downgraded.value[5].value == b"2",
           "HELLO 2 replies in new protocol", downgraded)
    client.close()

    for version in ("1", "4"):
        client = Client()
        frame = client.command("HELLO", version)
        expect(frame.kind == b"-" and frame.value == b"NOPROTO unsupported protocol version",
               "HELLO unsupported version %s" % version, frame)
        client.close()
    client = Client()
    frame = client.command("HELLO", "abc")
    expect(frame.kind == b"-" and frame.value == b"ERR Protocol version is not an integer or out of range",
           "HELLO noninteger", frame)
    frame = client.command("HELLO", "3", "BOGUS")
    expect(frame.kind == b"-" and frame.value == b"ERR Syntax error in HELLO option 'BOGUS'",
           "HELLO option syntax", frame)
    client.close()


def shape_matrix():
    client = Client()
    map_values(client.command("HELLO", "3"))
    expect(client.command("FLUSHALL").kind == b"+", "FLUSHALL")

    expect(client.command("GET", "resp3:missing").kind == b"_", "null bulk unification")
    expect(client.command("ZMPOP", "1", "resp3:missing-z", "MIN").kind == b"_",
           "null array unification")

    client.command("HSET", "resp3:h", "a", "1", "b", "2")
    expect(client.command("HGETALL", "resp3:h").kind == b"%", "HGETALL map")
    random_hash = client.command("HRANDFIELD", "resp3:h", "2", "WITHVALUES")
    expect(random_hash.kind == b"*" and all(item.kind == b"*" and len(item.value) == 2
                                             for item in random_hash.value),
           "HRANDFIELD WITHVALUES pairs", random_hash)
    expect(client.command("CONFIG", "GET", "maxmemory").kind == b"%", "CONFIG GET map")
    docs = client.command("COMMAND", "DOCS", "GET")
    docs_values = map_values(docs)
    expect(docs_values[b"get"].kind == b"%", "COMMAND DOCS nested map", docs_values)
    info = client.command("CLIENT", "INFO")
    expect(info.kind == b"=" and info.value.startswith(b"txt:"), "CLIENT INFO verbatim", info)
    client_list = client.command("CLIENT", "LIST")
    expect(client_list.kind == b"=" and client_list.value.startswith(b"txt:"),
           "CLIENT LIST verbatim", client_list)
    server_info = client.command("INFO", "SERVER")
    expect(server_info.kind == b"=" and server_info.value.startswith(b"txt:"),
           "INFO verbatim", server_info)

    client.command("SADD", "resp3:s1", "a", "b", "c")
    client.command("SADD", "resp3:s2", "b", "c", "d")
    expect(client.command("SMEMBERS", "resp3:s1").kind == b"~", "SMEMBERS set")
    expect(client.command("SINTER", "resp3:s1", "resp3:s2").kind == b"~", "SINTER set")
    expect(client.command("SUNION", "resp3:s1", "resp3:s2").kind == b"~", "SUNION set")
    expect(client.command("SDIFF", "resp3:s1", "resp3:s2").kind == b"~", "SDIFF set")
    client.command("SADD", "resp3:spop", "only")
    expect(client.command("SPOP", "resp3:spop", "1").kind == b"~", "SPOP count set")
    expect(client.command("SISMEMBER", "resp3:s1", "a").kind == b":", "SISMEMBER stays integer")
    expect(client.command("EXISTS", "resp3:s1").kind == b":", "EXISTS stays integer")

    # resp3:z is small, so it is a COMPACT (listpack) zset -- and a score entering compact storage
    # loses the sign of a zero, exactly as the oracle's listpack does. This row read b"-0" until
    # the zsetfix lane probed redis 7.4.2: `ZADD k -0 m; ZSCORE k m` answers "0" on a listpack and
    # "-0" on a skiplist, so the old expectation pinned a divergence. The skiplist arm is asserted
    # right below so this stays a two-sided test of the rule rather than a one-armed constant.
    score_cases = [("zero", "0", b"0"), ("negzero", "-0", b"0"),
                   ("small", "0.015", b"0.015"), ("negsmall", "-0.015", b"-0.015"),
                   ("huge", "1e308", b"1e+308"), ("posinf", "inf", b"inf"),
                   ("neginf", "-inf", b"-inf")]
    for member, score, expected in score_cases:
        client.command("ZADD", "resp3:z", score, member)
        actual = client.command("ZSCORE", "resp3:z", member)
        expect(actual.kind == b"," and actual.value == expected,
               "ZSCORE shortest double %s" % member, actual)
    encoding = client.command("OBJECT", "ENCODING", "resp3:z")
    expect(encoding.value == b"listpack", "score cases really ran on a compact zset", encoding)
    client.command("DEL", "resp3:zbig")
    client.command("ZADD", "resp3:zbig",
                   *[part for i in range(200) for part in (str(10000 + i), "pad%d" % i)])
    client.command("ZADD", "resp3:zbig", "-0", "negzero")
    encoding = client.command("OBJECT", "ENCODING", "resp3:zbig")
    expect(encoding.value == b"skiplist", "expanded arm really is expanded", encoding)
    actual = client.command("ZSCORE", "resp3:zbig", "negzero")
    expect(actual.kind == b"," and actual.value == b"-0",
           "ZSCORE keeps -0 on an expanded zset", actual)
    zmscore = client.command("ZMSCORE", "resp3:z", "small", "absent")
    expect([item.kind for item in zmscore.value] == [b",", b"_"], "ZMSCORE types", zmscore)
    expect(client.command("ZINCRBY", "resp3:z", "1", "small").kind == b",", "ZINCRBY double")
    expect(client.command("ZADD", "resp3:z", "INCR", "1", "small").kind == b",",
           "ZADD INCR double")
    rank = client.command("ZRANK", "resp3:z", "small", "WITHSCORE")
    expect(rank.kind == b"*" and rank.value[1].kind == b",", "ZRANK WITHSCORE", rank)
    reverse_rank = client.command("ZREVRANK", "resp3:z", "small", "WITHSCORE")
    expect(reverse_rank.kind == b"*" and reverse_rank.value[1].kind == b",",
           "ZREVRANK WITHSCORE", reverse_rank)
    scored_ranges = [
        ("ZRANGE WITHSCORES", client.command("ZRANGE", "resp3:z", "0", "2", "WITHSCORES")),
        ("ZREVRANGE WITHSCORES", client.command("ZREVRANGE", "resp3:z", "0", "2", "WITHSCORES")),
        ("ZRANGEBYSCORE WITHSCORES",
         client.command("ZRANGEBYSCORE", "resp3:z", "-inf", "+inf", "WITHSCORES")),
        ("ZREVRANGEBYSCORE WITHSCORES",
         client.command("ZREVRANGEBYSCORE", "resp3:z", "+inf", "-inf", "WITHSCORES")),
    ]
    for label, scored in scored_ranges:
        expect(scored.kind == b"*" and
               all(pair.kind == b"*" and pair.value[1].kind == b"," for pair in scored.value),
               "%s pairs" % label, scored)
    random_z = client.command("ZRANDMEMBER", "resp3:z", "2", "WITHSCORES")
    expect(all(pair.kind == b"*" and pair.value[1].kind == b"," for pair in random_z.value),
           "ZRANDMEMBER WITHSCORES pairs", random_z)

    client.command("DEL", "resp3:zpop")
    client.command("ZADD", "resp3:zpop", "1", "a", "2", "b", "3", "c")
    flat = client.command("ZPOPMIN", "resp3:zpop")
    expect(flat.kind == b"*" and len(flat.value) == 2 and flat.value[1].kind == b",",
           "ZPOPMIN no-count stays flat", flat)
    nested = client.command("ZPOPMIN", "resp3:zpop", "2")
    expect(nested.kind == b"*" and all(pair.kind == b"*" and pair.value[1].kind == b"," for pair in nested.value),
           "ZPOPMIN count nests", nested)
    client.command("ZADD", "resp3:zpop", "1", "a", "2", "b", "3", "c")
    flat = client.command("ZPOPMAX", "resp3:zpop")
    expect(flat.kind == b"*" and len(flat.value) == 2 and flat.value[1].kind == b",",
           "ZPOPMAX no-count stays flat", flat)
    nested = client.command("ZPOPMAX", "resp3:zpop", "2")
    expect(nested.kind == b"*" and all(pair.kind == b"*" and pair.value[1].kind == b"," for pair in nested.value),
           "ZPOPMAX count nests", nested)

    client.command("XADD", "resp3:x", "1-0", "f", "v")
    xread = client.command("XREAD", "STREAMS", "resp3:x", "0-0")
    expect(xread.kind == b"%" and len(xread.value) == 1, "XREAD outer map", xread)

    client.command("SET", "resp3:f", "1")
    expect(client.command("INCRBYFLOAT", "resp3:f", "0.5").kind == b"$",
           "INCRBYFLOAT stays bulk")
    zscan = client.command("ZSCAN", "resp3:z", "0")
    expect(zscan.kind == b"*" and all(item.kind == b"$" for item in zscan.value[1].value),
           "ZSCAN scores stay bulk", zscan)

    # XPENDING and GEO are not registered in this tree. Their audited RESP3 invariance is recorded
    # in NOTES-COMPAT.md; there is no implemented shape to exercise here.
    client.close()


def multi_and_lua():
    client = Client()
    map_values(client.command("HELLO", "3"))
    client.command("HSET", "resp3:mh", "f", "v")
    client.command("ZADD", "resp3:mz", "0.015", "m")
    client.command("SADD", "resp3:ms", "a", "b")
    expect(client.command("MULTI").kind == b"+", "MULTI starts")
    for command in (("HGETALL", "resp3:mh"), ("ZSCORE", "resp3:mz", "m"),
                    ("SMEMBERS", "resp3:ms")):
        expect(client.command(*command).value == b"QUEUED", "MULTI queues", command)
    executed = client.command("EXEC")
    expect(executed.kind == b"*" and [item.kind for item in executed.value] == [b"%", b",", b"~"],
           "EXEC preserves RESP3 child shapes", executed)

    watcher = Client()
    map_values(watcher.command("HELLO", "3"))
    watcher.command("WATCH", "resp3:watched")
    watcher.command("MULTI")
    watcher.command("GET", "resp3:watched")
    client.command("SET", "resp3:watched", "changed")
    expect(watcher.command("EXEC").kind == b"_", "EXEC watch abort null")
    watcher.close()

    scripts = [
        ("return false", b"_"),
        ("return true", b":"),
        ("return {map={a=1}}", b"%"),
        ("return {set={a=true,b=true}}", b"~"),
        ("return {double=1.5}", b","),
        ("return {big_number='123456789012345678901'}", b"("),
        ("return {verbatim_string={format='txt',string='hi'}}", b"="),
        ("redis.setresp(3); return false", b"#"),
    ]
    for source, kind in scripts:
        result = client.command("EVAL", source, "0")
        expect(result.kind == kind, "Lua RESP3 conversion", (source, result))
    default_nested = client.command("EVAL", "return redis.call('ZSCORE',KEYS[1],'m')", "1", "resp3:mz")
    expect(default_nested.kind == b"$", "Lua nested default RESP2", default_nested)
    resp3_nested = client.command(
        "EVAL", "redis.setresp(3); return redis.call('ZSCORE',KEYS[1],'m')", "1", "resp3:mz")
    expect(resp3_nested.kind == b",", "Lua nested RESP3", resp3_nested)
    client.close()


def pubsub_and_notify():
    resp2 = Client()
    resp3 = Client()
    map_values(resp3.command("HELLO", "3"))
    ack2 = resp2.command("SUBSCRIBE", "resp3:channel")
    ack3 = resp3.command("SUBSCRIBE", "resp3:channel")
    expect(ack2.kind == b"*" and ack3.kind == b">", "mixed protocol subscribe acks", (ack2, ack3))
    ordinary = resp3.command("GET", "resp3:ordinary-missing")
    expect(ordinary.kind == b"_", "RESP3 subscriber ordinary command", ordinary)
    restricted = resp2.command("GET", "resp3:ordinary-missing")
    expect(restricted.kind == b"-", "RESP2 subscriber restriction", restricted)

    publisher = Client()
    publisher.command("PUBLISH", "resp3:channel", "payload")
    message2 = read_frame(resp2.file)
    message3 = read_frame(resp3.file)
    expect(message2.kind == b"*" and message3.kind == b">", "mixed delivery framing", (message2, message3))

    shard = Client()
    map_values(shard.command("HELLO", "3"))
    expect(shard.command("SSUBSCRIBE", "resp3:shard-channel").kind == b">", "sharded subscribe push")
    publisher.command("SPUBLISH", "resp3:shard-channel", "shard-payload")
    smessage = read_frame(shard.file)
    expect(smessage.kind == b">" and bulk(smessage.value[0]) == b"smessage",
           "sharded message push", smessage)

    notify = Client()
    map_values(notify.command("HELLO", "3"))
    publisher.command("CONFIG", "SET", "notify-keyspace-events", "KEA")
    ack = notify.command("PSUBSCRIBE", "__keyevent@0__:*")
    expect(ack.kind == b">", "notification subscribe push", ack)
    publisher.command("SET", "resp3:notify-key", "value")
    event = read_frame(notify.file)
    expect(event.kind == b">" and bulk(event.value[0]) == b"pmessage",
           "keyspace notification push", event)
    publisher.command("CONFIG", "SET", "notify-keyspace-events", "")

    # RESET clears subscriptions and downgrades the protocol before subsequent replies.
    reset = resp3.command("RESET")
    expect(reset.kind == b"+" and reset.value == b"RESET", "RESET while subscribed")
    expect(resp3.command("GET", "resp3:after-reset-missing").kind == b"$", "RESET RESP2 downgrade")
    expect(resp3.command("HELLO").kind == b"*", "RESET HELLO introspection")

    for client in (resp2, resp3, shard, notify, publisher):
        client.close()


hello_matrix()
shape_matrix()
multi_and_lua()
pubsub_and_notify()
print("RESP3 directed: %d checks -> PASS" % checks)
