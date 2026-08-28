#!/usr/bin/env python3
"""Directed cold command-metadata battery. Usage: tests/cmdmeta.py HOST PORT"""

import socket
import sys


HOST = sys.argv[1]
PORT = int(sys.argv[2])
checks = 0
failures = []

PIPE_NAMES = set("""
acl|cat acl|deluser acl|dryrun acl|genpass acl|getuser acl|help acl|list acl|load acl|log
acl|save acl|setuser acl|users acl|whoami client|caching client|getname client|getredir
client|help client|id client|info client|kill client|list client|no-evict client|no-touch
client|pause client|reply client|setinfo client|setname client|tracking client|trackinginfo
client|unblock client|unpause cluster|addslots cluster|addslotsrange cluster|bumpepoch
cluster|count-failure-reports cluster|countkeysinslot cluster|delslots cluster|delslotsrange
cluster|failover cluster|flushslots cluster|forget cluster|getkeysinslot cluster|help cluster|info
cluster|keyslot cluster|links cluster|meet cluster|myid cluster|myshardid cluster|nodes
cluster|replicas cluster|replicate cluster|reset cluster|saveconfig cluster|set-config-epoch
cluster|setslot cluster|shards cluster|slaves cluster|slots command|count command|docs
command|getkeys command|getkeysandflags command|help command|info command|list config|get
config|help config|resetstat config|rewrite config|set function|delete function|dump
function|flush function|help function|kill function|list function|load function|restore
function|stats latency|doctor latency|graph latency|help latency|histogram latency|history
latency|latest latency|reset memory|doctor memory|help memory|malloc-stats memory|purge
memory|stats memory|usage module|help module|list module|load module|loadex module|unload
object|encoding object|freq object|help object|idletime object|refcount pubsub|channels
pubsub|help pubsub|numpat pubsub|numsub pubsub|shardchannels pubsub|shardnumsub script|debug
script|exists script|flush script|help script|kill script|load slowlog|get slowlog|help
slowlog|len slowlog|reset xgroup|create xgroup|createconsumer xgroup|delconsumer
xgroup|destroy xgroup|help xgroup|setid xinfo|consumers xinfo|groups xinfo|help xinfo|stream
""".split())


def frame(*arguments):
    result = b"*%d\r\n" % len(arguments)
    for argument in arguments:
        value = argument if isinstance(argument, bytes) else str(argument).encode()
        result += b"$%d\r\n" % len(value) + value + b"\r\n"
    return result


class RespError(Exception):
    def __init__(self, message):
        self.message = message

    def __eq__(self, other):
        return isinstance(other, RespError) and self.message == other.message

    def __repr__(self):
        return "RespError(%r)" % self.message


class Connection:
    def __init__(self, resp3=False):
        self.socket = socket.create_connection((HOST, PORT), timeout=10)
        self.file = self.socket.makefile("rb")
        if resp3:
            self.socket.sendall(frame("HELLO", "3"))
            self.read()

    def read(self):
        line = self.file.readline()
        if not line:
            raise EOFError
        marker, payload = line[:1], line[1:-2]
        if marker in (b"+", b"$"):
            if marker == b"+":
                return payload
            length = int(payload)
            return None if length < 0 else self.file.read(length + 2)[:-2]
        if marker == b":":
            return int(payload)
        if marker == b"-":
            return RespError(payload)
        if marker == b"_":
            return None
        if marker in (b"*", b"~"):
            count = int(payload)
            return None if count < 0 else [self.read() for _ in range(count)]
        if marker == b"%":
            return [self.read() for _ in range(int(payload) * 2)]
        raise AssertionError("unsupported RESP marker %r" % marker)

    def cmd(self, *arguments):
        self.socket.sendall(frame(*arguments))
        return self.read()

    def close(self):
        self.socket.close()


def expect(label, got, want):
    global checks
    checks += 1
    try:
        passed = want(got) if callable(want) else got == want
    except (IndexError, KeyError, TypeError):
        passed = False
    if not passed:
        failures.append("%s: got %r, want %r" % (label, got, want))


def flagged(connection, argv, expected):
    expect("intent " + " ".join(argv),
           connection.cmd("COMMAND", "GETKEYSANDFLAGS", *argv),
           [[key.encode(), [flag.encode() for flag in flags]] for key, flags in expected])


def run():
    connection = Connection()
    listing = connection.cmd("COMMAND", "LIST")
    names = {name.decode() for name in listing}
    pipes = {name for name in names if "|" in name}
    top = names - pipes
    count = connection.cmd("COMMAND", "COUNT")
    expect("all 129 pipe-qualified names", pipes, PIPE_NAMES)
    expect("pipe-qualified count fired", len(pipes), 129)
    expect("COUNT remains top-level count", count, len(top))
    expect("LIST contains top plus subcommands", len(names), count + 129)
    expect("all metadata names lowercase", names, lambda value: all(x == x.lower() for x in value))

    config_get = connection.cmd("COMMAND", "INFO", "config|get")
    expect("config|get exact rich row", config_get, [[
        b"config|get", -3, [b"admin", b"noscript", b"loading", b"stale"], 0, 0, 0,
        [b"@admin", b"@slow", b"@dangerous"], [], [], [],
    ]])
    object_reply = connection.cmd("COMMAND", "INFO", "object|encoding")
    object_encoding = (object_reply[0] if isinstance(object_reply, list) and object_reply and
                       isinstance(object_reply[0], list) else [])
    expect("object|encoding arity/range", object_encoding[:6],
           [b"object|encoding", 3, [b"readonly"], 2, 2, 1])
    expect("object|encoding categories", object_encoding[6] if len(object_encoding) > 6 else None,
           [b"@keyspace", b"@read", b"@slow"])
    expect("object|encoding tip fired", object_encoding[7] if len(object_encoding) > 7 else None,
           [b"nondeterministic_output"])
    expect("object|encoding key spec fired", object_encoding[8] if len(object_encoding) > 8 else None,
           lambda value:
           len(value) == 1 and value[0][0:2] == [b"flags", [b"RO"]] and
           b"begin_search" in value[0] and b"find_keys" in value[0])
    config_reply = connection.cmd("COMMAND", "INFO", "config")
    config = (config_reply[0] if isinstance(config_reply, list) and config_reply and
              isinstance(config_reply[0], list) else [])
    children = config[9] if len(config) == 10 and isinstance(config[9], list) else []
    expect("container exposes five child rows", {row[0] for row in children},
           {b"config|get", b"config|help", b"config|resetstat", b"config|rewrite", b"config|set"})
    expect("unknown qualified name control", connection.cmd("COMMAND", "INFO", "nope|nope"),
           [None])

    # Every row below was byte-different before this lane except the explicitly labelled controls.
    flagged(connection, ["ZADD", "z", "1", "m"], [("z", ["RW", "update"])])
    flagged(connection, ["DEL", "a", "b"],
            [("a", ["RM", "delete"]), ("b", ["RM", "delete"])])
    flagged(connection, ["EXISTS", "a", "b"], [("a", ["RO"]), ("b", ["RO"])])
    flagged(connection, ["RENAME", "a", "b"],
            [("a", ["RW", "access", "delete"]), ("b", ["OW", "update"])])
    flagged(connection, ["MSET", "a", "1", "b", "2"],
            [("a", ["OW", "update"]), ("b", ["OW", "update"])])
    flagged(connection, ["COPY", "a", "b"],
            [("a", ["RO", "access"]), ("b", ["OW", "update"])])
    flagged(connection, ["SMOVE", "a", "b", "m"],
            [("a", ["RW", "access", "delete"]), ("b", ["RW", "insert"])])
    flagged(connection, ["BITOP", "AND", "d", "a", "b"],
            [("d", ["OW", "update"]), ("a", ["RO", "access"]),
             ("b", ["RO", "access"])])
    flagged(connection, ["ZUNIONSTORE", "d", "2", "a", "b"],
            [("d", ["OW", "update"]), ("a", ["RO", "access"]),
             ("b", ["RO", "access"])])
    flagged(connection, ["GEORADIUS", "g", "0", "0", "1", "km", "STORE", "d"],
            [("g", ["RO", "access"]), ("d", ["OW", "update"])])
    flagged(connection, ["OBJECT", "ENCODING", "k"], [("k", ["RO"])])
    flagged(connection, ["XGROUP", "CREATE", "x", "g", "$"], [("x", ["RW", "insert"])])
    flagged(connection, ["SET", "k", "v"], [("k", ["OW", "update"])])
    flagged(connection, ["BITFIELD", "k", "GET", "u8", "0"],
            [("k", ["RO", "access"])])
    flagged(connection, ["SORT", "s", "STORE", "d"],
            [("s", ["RO", "access"]), ("d", ["OW", "update"])])
    flagged(connection, ["PFMERGE", "d", "a", "b"],
            [("d", ["RW", "access", "insert"]), ("a", ["RO", "access"]),
             ("b", ["RO", "access"])])
    flagged(connection, ["ZUNION", "+1", "a", "b"], [("a", [])])
    flagged(connection, ["LMPOP", "01", "a", "b", "LEFT"], [("a", [])])
    flagged(connection, ["SORT", "s", "STORE", "d", "STORE", "e"],
            [("s", ["RO", "access"]), ("e", ["OW", "update"])])
    expect("unknown container arm is invalid command",
           connection.cmd("COMMAND", "GETKEYSANDFLAGS", "OBJECT", "BOGUS", "k"),
           RespError(b"ERR Invalid command specified"))
    # Controls that already matched prove contextual rewriting did not flatten every intent.
    flagged(connection, ["GET", "k"], [("k", ["RO", "access"])])
    flagged(connection, ["SET", "k", "v", "GET"],
            [("k", ["RW", "access", "update"])])
    flagged(connection, ["BITFIELD", "k", "SET", "u8", "0", "1"],
            [("k", ["RW", "access", "update"])])

    stream = {name.decode() for name in connection.cmd("ACL", "CAT", "stream") if b"|" in name}
    pubsub = {name.decode() for name in connection.cmd("ACL", "CAT", "pubsub") if b"|" in name}
    expect("stream subcommand categories", len(stream), 10)
    expect("pubsub subcommand categories", len(pubsub), 5)

    # Deliberate DOCS boundary: subcommands are discoverable, but prose remains the compact TomoKV
    # fallback rather than embedding Redis's large human-authored documentation corpus.
    docs = connection.cmd("COMMAND", "DOCS", "config|get")
    expect("subcommand DOCS remains minimal and explicit", docs, lambda value:
           value[0] == b"config|get" and b"tomokv compatible config|get command" in value[1])
    connection.close()

    resp3 = Connection(resp3=True)
    resp3_object = resp3.cmd("COMMAND", "INFO", "object|encoding")
    resp3_row = (resp3_object[0] if isinstance(resp3_object, list) and resp3_object and
                 isinstance(resp3_object[0], list) else [])
    expect("RESP3 INFO rich row", resp3_row[:8], object_encoding[:8] if object_encoding else [b"required"])
    expect("RESP3 key flags", resp3.cmd("COMMAND", "GETKEYSANDFLAGS", "RENAME", "a", "b"),
           [[b"a", [b"RW", b"access", b"delete"]], [b"b", [b"OW", b"update"]]])
    resp3.close()


run()
if failures:
    for failure in failures[:20]:
        print("FAIL", failure)
print("CMDMETA %s: %d checks; pipes=%d rich_rows=2 intent_rows=22 edge_rows=1 controls=3" %
      ("PASS" if not failures else "FAIL", checks, len(PIPE_NAMES)))
raise SystemExit(1 if failures else 0)
