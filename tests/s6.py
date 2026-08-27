#!/usr/bin/env python3
"""S6 wrong-answer regression battery: exactly 215 oracle-derived comparisons.

Usage: tests/s6.py HOST PORT

The server must be purpose-booted without AOF. The A4 detector gives every one of 200 inserted
keys its own reachability comparison after 20,000 RANDOMKEY draws. Its unexpected-key and null
controls must both remain zero. A5 walks every TomoKV shard cursor rather than assuming one SCAN
call covers the database. A6 checks the pre-save boot-time seed. A7 covers the repaired negative
numreplicas validation and retains the AOF-off [0,0] control; the per-connection local-fsync count
is deliberately outside this lane's gate, as documented in NOTES-S6FIX.md and NOTES-SERVERTAIL.md.
"""

import collections
import re
import socket
import sys
import time


HOST, PORT = sys.argv[1], int(sys.argv[2])
failures = []
comparisons = 0


def encode(*args):
    out = [b"*%d\r\n" % len(args)]
    for arg in args:
        if not isinstance(arg, bytes):
            arg = str(arg).encode()
        out.append(b"$%d\r\n" % len(arg) + arg + b"\r\n")
    return b"".join(out)


class ErrorReply:
    def __init__(self, text):
        self.text = text

    def __repr__(self):
        return "ErrorReply(%r)" % self.text

    def __eq__(self, other):
        return isinstance(other, ErrorReply) and self.text == other.text


class Client:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=30)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def command(self, *args):
        self.sock.sendall(encode(*args))
        return self.read()

    def read(self):
        line = self.file.readline()
        if not line:
            raise EOFError("server closed the connection")
        kind, body = line[:1], line[1:-2]
        if kind == b"+":
            return body
        if kind == b"-":
            return ErrorReply(body)
        if kind == b":":
            return int(body)
        if kind in (b"$", b"="):
            length = int(body)
            if length == -1:
                return None
            return self.file.read(length + 2)[:-2]
        if kind in (b"*", b"~", b">"):
            length = int(body)
            return None if length == -1 else [self.read() for _ in range(length)]
        if kind == b"%":
            return [self.read() for _ in range(int(body) * 2)]
        if kind == b"_":
            return None
        raise AssertionError("unexpected RESP marker %r" % line[:16])


def check(label, got, want):
    global comparisons
    comparisons += 1
    ok = want(got) if callable(want) else got == want
    if not ok:
        failures.append("%s: got %r, want %r" % (label, got, want))


def scan_type(client, type_name):
    cursor = b"0"
    keys = []
    calls = 0
    while True:
        reply = client.command("SCAN", cursor, "COUNT", "10000", "TYPE", type_name)
        calls += 1
        if isinstance(reply, ErrorReply):
            return keys, calls, reply
        if not isinstance(reply, list) or len(reply) != 2:
            return keys, calls, ErrorReply(b"invalid SCAN reply shape")
        cursor, page = reply
        keys.extend(page)
        if cursor == b"0":
            return keys, calls, None
        if calls > 300:
            return keys, calls, ErrorReply(b"SCAN did not terminate")


def main():
    client = Client()
    if client.command("CONFIG", "GET", "appendonly") != [b"appendonly", b"no"]:
        raise AssertionError("s6 battery must be purpose-booted with appendonly no")

    # A4: 200 firing comparisons plus three zero/control comparisons.
    client.command("FLUSHALL")
    expected = {("s6:rk:%03d" % i).encode() for i in range(200)}
    for key in sorted(expected):
        if client.command("SET", key, "v") != b"OK":
            raise AssertionError("SET failed for %r" % key)
    draws = collections.Counter(client.command("RANDOMKEY") for _ in range(20000))
    missing = sorted(expected - set(draws))
    unexpected = sorted(set(draws) - expected - {None})
    nulls = draws.get(None, 0)
    for key in sorted(expected):
        check("A4 reachable %s" % key.decode(), draws[key], lambda count: count > 0)
    check("A4 DB cardinality control", client.command("DBSIZE"), 200)
    check("A4 unexpected-key control", len(unexpected), 0)
    check("A4 null-reply control", nulls, 0)

    # A5: STREAM is a real type; an unknown name is a valid filter that matches nothing.
    client.command("FLUSHALL")
    stream_id = client.command("XADD", "s6:stream", "*", "f", "v")
    client.command("SET", "s6:string", "v")
    stream_keys, stream_calls, stream_error = scan_type(client, "stream")
    unknown_keys, unknown_calls, unknown_error = scan_type(client, "not-a-real-type")
    check("A5 XADD fired", stream_id,
          lambda value: isinstance(value, bytes) and re.fullmatch(br"[0-9]+-[0-9]+", value))
    check("A5 TYPE stream completes", stream_error, None)
    check("A5 TYPE stream includes stream", stream_keys.count(b"s6:stream"), 1)
    check("A5 TYPE stream excludes string", stream_keys.count(b"s6:string"), 0)
    check("A5 unknown TYPE completes", unknown_error, None)
    check("A5 unknown TYPE matches nothing", len(unknown_keys), 0)

    # A6: no SAVE has run since this fresh purpose boot, so LASTSAVE must be near boot wall-clock.
    now = int(time.time())
    lastsave = client.command("LASTSAVE")
    check("A6 LASTSAVE reply type", lastsave, lambda value: isinstance(value, int))
    check("A6 LASTSAVE boot-time seed", lastsave,
          lambda value: isinstance(value, int) and 0 <= now - value <= 300)
    check("A6 future-time control", int(isinstance(lastsave, int) and lastsave > now + 1), 0)

    # A7: validation fixed here; local count stays the documented conservative shelf.
    wait_zero = client.command("WAITAOF", "0", "0", "0")
    negative_replicas = client.command("WAITAOF", "0", "-1", "0")
    negative_timeout = client.command("WAITAOF", "0", "0", "-1")
    check("A7 AOF-off zero control", wait_zero, [0, 0])
    check("A7 negative numreplicas", negative_replicas,
          ErrorReply(b"ERR value is out of range, must be positive"))
    check("A7 negative timeout control", negative_timeout,
          ErrorReply(b"ERR timeout is negative"))

    if comparisons != 215:
        failures.append("battery definition drift: %d comparisons, expected 215" % comparisons)

    print("A4 draws=20000 distinct=%d missing=%d unexpected=%d nulls=%d min=%d max=%d" %
          (len(set(draws) & expected), len(missing), len(unexpected), nulls,
           min(draws[key] for key in expected), max(draws[key] for key in expected)))
    print("A5 stream_calls=%d stream_keys=%r unknown_calls=%d unknown_keys=%d" %
          (stream_calls, sorted(stream_keys), unknown_calls, len(unknown_keys)))
    print("A6 lastsave=%r now=%d delta=%r future_control=%d" %
          (lastsave, now, None if not isinstance(lastsave, int) else now - lastsave,
           int(isinstance(lastsave, int) and lastsave > now + 1)))
    print("A7 zero=%r negative_replicas=%r negative_timeout=%r" %
          (wait_zero, negative_replicas, negative_timeout))
    print("s6: %d comparisons, %d failures -> %s" %
          (comparisons, len(failures), "PASS" if not failures else "FAIL"))
    for failure in failures[:40]:
        print("  " + failure)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
