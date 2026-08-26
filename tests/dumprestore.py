#!/usr/bin/env python3
"""Directed self-format DUMP/RESTORE codec, grammar, TTL, and restart battery."""

import socket
import sys
import time


HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 6379
MODE = sys.argv[3] if len(sys.argv) > 3 else "live"


def encode(args):
    payload = b"*%d\r\n" % len(args)
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        elif isinstance(arg, int):
            arg = str(arg).encode()
        payload += b"$%d\r\n" % len(arg) + arg + b"\r\n"
    return payload


class Client:
    def __init__(self):
        self.socket = socket.create_connection((HOST, PORT), timeout=60)
        self.file = self.socket.makefile("rb")

    def read(self):
        line = self.file.readline()
        if not line:
            raise RuntimeError("server closed the connection")
        kind = line[:1]
        if kind in (b"+", b"-"):
            return line.rstrip(b"\r\n")
        if kind == b":":
            return int(line[1:-2])
        if kind == b"$":
            length = int(line[1:-2])
            return None if length == -1 else self.file.read(length + 2)[:-2]
        if kind == b"*":
            length = int(line[1:-2])
            return None if length == -1 else [self.read() for _ in range(length)]
        raise RuntimeError("unknown RESP reply %r" % line)

    def cmd(self, *args):
        self.socket.sendall(encode(args))
        return self.read()


client = Client()
checks = 0


def expect(actual, expected, label):
    global checks
    checks += 1
    if actual != expected:
        raise AssertionError("%s: expected %r, got %r" % (label, expected, actual))


def case_defs(prefix):
    return [
        (prefix + ":string:int", "string"),
        (prefix + ":string:raw", "string"),
        (prefix + ":string:extern", "string"),
        (prefix + ":bitmap", "string"),
        (prefix + ":hll:sparse", "string"),
        (prefix + ":hll:dense", "string"),
        (prefix + ":hash:compact", "hash"),
        (prefix + ":hash:expanded", "hash"),
        (prefix + ":list:compact", "list"),
        (prefix + ":list:expanded", "list"),
        (prefix + ":set:intcompact", "set"),
        (prefix + ":set:genericcompact", "set"),
        (prefix + ":set:expanded", "set"),
        (prefix + ":zset:compact", "zset"),
        (prefix + ":zset:expanded", "zset"),
        (prefix + ":stream:compact", "stream"),
        (prefix + ":stream:expanded", "stream"),
    ]


def build_cases(prefix):
    expect(client.cmd("SET", prefix + ":string:int", "12345"), b"+OK", "int string")
    expect(client.cmd("SET", prefix + ":string:raw", b"raw\x00value\xff"), b"+OK", "raw string")
    expect(client.cmd("SET", prefix + ":string:extern", b"E" * 50000), b"+OK", "extern string")
    expect(client.cmd("BITFIELD", prefix + ":bitmap", "SET", "u8", "#1000", "165",
                      "SET", "i16", "7", "-1234"), [0, 0], "bitmap")
    expect(client.cmd("PFADD", prefix + ":hll:sparse", "a", "b", "c", "a"), 1, "sparse HLL")
    dense = prefix + ":hll:dense"
    for base in range(0, 5000, 50):
        args = ["PFADD", dense] + ["dense:%05d" % index for index in range(base, base + 50)]
        reply = client.cmd(*args)
        if reply not in (0, 1):
            raise AssertionError("dense HLL PFADD: %r" % reply)

    compact_hash = prefix + ":hash:compact"
    expect(client.cmd("HSET", compact_hash, "a", "1", "b", "2", b"c\x00", b"v\xff"),
           3, "compact hash")
    expanded_hash = prefix + ":hash:expanded"
    args = ["HSET", expanded_hash]
    for index in range(600):
        args += ["f%04d" % index, "v%04d" % index]
    expect(client.cmd(*args), 600, "expanded hash")

    expect(client.cmd("RPUSH", prefix + ":list:compact", "a", "b", "c", "d"),
           4, "compact list")
    args = ["RPUSH", prefix + ":list:expanded"] + [
        ("entry:%04d:" % index) + "L" * 80 for index in range(180)
    ]
    expect(client.cmd(*args), 180, "expanded list")

    expect(client.cmd(*(["SADD", prefix + ":set:intcompact"] + [str(i) for i in range(50)])),
           50, "integer compact set")
    expect(client.cmd(*(["SADD", prefix + ":set:genericcompact"] +
                        ["member:%d" % i for i in range(8)])),
           8, "generic compact set")
    expect(client.cmd(*(["SADD", prefix + ":set:expanded"] +
                        ["table:%04d" % i for i in range(220)])),
           220, "expanded set")

    compact_zset = prefix + ":zset:compact"
    expect(client.cmd("ZADD", compact_zset, "-inf", "down", "-1.25", "a",
                      "0", "zero", "inf", "up"), 4, "compact zset")
    expanded_zset = prefix + ":zset:expanded"
    args = ["ZADD", expanded_zset]
    for index in range(220):
        args += [str(index * 0.25 - 20), "member:%04d" % index]
    expect(client.cmd(*args), 220, "expanded zset")

    compact_stream = prefix + ":stream:compact"
    expect(client.cmd("XADD", compact_stream, "10-0", "f", "v0"), b"10-0", "compact stream 0")
    expect(client.cmd("XADD", compact_stream, "10-1", "f", "v1"), b"10-1", "compact stream 1")
    expect(client.cmd("XDEL", compact_stream, "10-1"), 1, "compact stream tombstone")
    expanded_stream = prefix + ":stream:expanded"
    for index in range(180):
        expect(client.cmd("XADD", expanded_stream, "%d-0" % (index + 1),
                          "field", ("value:%03d:" % index) + "S" * 160),
               ("%d-0" % (index + 1)).encode(), "expanded stream %d" % index)
    expect(client.cmd("XDEL", expanded_stream, "90-0"), 1, "expanded stream tombstone")
    expect(client.cmd("XTRIM", expanded_stream, "MINID", "=", "21-0"), 20,
           "expanded stream trim")
    return case_defs(prefix)


def observation(key, kind):
    common = (client.cmd("TYPE", key), client.cmd("OBJECT", "ENCODING", key))
    if kind == "string":
        value = client.cmd("GET", key)
    elif kind == "hash":
        reply = client.cmd("HGETALL", key)
        value = sorted((reply[index], reply[index + 1]) for index in range(0, len(reply), 2))
    elif kind == "list":
        value = client.cmd("LRANGE", key, "0", "-1")
    elif kind == "set":
        value = sorted(client.cmd("SMEMBERS", key))
    elif kind == "zset":
        value = client.cmd("ZRANGE", key, "0", "-1", "WITHSCORES")
    elif kind == "stream":
        value = client.cmd("XRANGE", key, "-", "+")
    else:
        raise AssertionError("unknown case kind %s" % kind)
    return common + (value,)


def validate_envelope(payload, label):
    global checks
    if not isinstance(payload, bytes) or len(payload) < 20:
        raise AssertionError("%s: short/non-bulk envelope %r" % (label, payload))
    if payload[:8] != b"TOMODMP\x00" or payload[8:10] != b"\x01\x80":
        raise AssertionError("%s: bad magic/version %r" % (label, payload[:12]))
    checks += 1


def roundtrip_cases(cases, destination_prefix):
    for index, (source, kind) in enumerate(cases):
        payload = client.cmd("DUMP", source)
        validate_envelope(payload, source)
        destination = "%s:%02d" % (destination_prefix, index)
        expect(client.cmd("RESTORE", destination, "0", payload), b"+OK", "restore " + source)
        expect(observation(destination, kind), observation(source, kind), "round-trip " + source)


def live_battery():
    expect(client.cmd("FLUSHALL"), b"+OK", "clean slate")
    cases = build_cases("dr:live")
    roundtrip_cases(cases, "dr:copy")
    expect(client.cmd("DUMP", "dr:missing"), None, "DUMP missing")

    source = "dr:live:string:raw"
    payload = client.cmd("DUMP", source)
    validate_envelope(payload, "grammar payload")
    expect(client.cmd("SET", "dr:busy", "old"), b"+OK", "BUSYKEY seed")
    expect(client.cmd("RESTORE", "dr:busy", "0", payload),
           b"-BUSYKEY Target key name already exists.", "BUSYKEY exact")
    expect(client.cmd("RESTORE", "dr:busy", "-1", payload),
           b"-BUSYKEY Target key name already exists.", "BUSYKEY precedes TTL parse")
    expect(client.cmd("RESTORE", "dr:busy", "0", payload, "REPLACE"), b"+OK", "REPLACE")
    expect(client.cmd("GET", "dr:busy"), b"raw\x00value\xff", "REPLACE value")

    expect(client.cmd("RESTORE", "dr:badttl", "-1", payload),
           b"-ERR Invalid TTL value, must be >= 0", "negative TTL")
    expect(client.cmd("RESTORE", "dr:badttl", "00", payload),
           b"-ERR value is not an integer or out of range", "TTL integer grammar")
    expect(client.cmd("RESTORE", "dr:idle", "0", payload, "IDLETIME", "12"), b"+OK",
           "IDLETIME accepted/ignored")
    expect(client.cmd("RESTORE", "dr:freq", "0", payload, "FREQ", "255"), b"+OK",
           "FREQ accepted/ignored")
    expect(client.cmd("RESTORE", "dr:idlebad", "0", payload, "IDLETIME", "-1"),
           b"-ERR Invalid IDLETIME value, must be >= 0", "IDLETIME range")
    expect(client.cmd("RESTORE", "dr:freqbad", "0", payload, "FREQ", "256"),
           b"-ERR Invalid FREQ value, must be >= 0 and <= 255", "FREQ range")
    expect(client.cmd("RESTORE", "dr:mixmeta", "0", payload,
                      "IDLETIME", "1", "FREQ", "1"),
           b"-ERR syntax error", "IDLETIME/FREQ exclusivity")
    expect(client.cmd("RESTORE", "dr:option", "0", payload, "NOPE"),
           b"-ERR syntax error", "unknown option")

    # DUMP carries value bytes only. The RESTORE TTL argument is the explicit expiry contract.
    expect(client.cmd("SET", "dr:ttl:source", "ttl-value", "PX", "60000"), b"+OK", "TTL source")
    ttl_payload = client.cmd("DUMP", "dr:ttl:source")
    remaining = client.cmd("PTTL", "dr:ttl:source")
    expect(client.cmd("RESTORE", "dr:ttl:preserved", remaining, ttl_payload), b"+OK",
           "relative TTL restore")
    restored_ttl = client.cmd("PTTL", "dr:ttl:preserved")
    if not (0 < restored_ttl <= remaining):
        raise AssertionError("relative TTL mismatch: %r -> %r" % (remaining, restored_ttl))
    global checks
    checks += 1
    expect(client.cmd("RESTORE", "dr:ttl:cleared", "0", ttl_payload), b"+OK", "zero TTL restore")
    expect(client.cmd("PTTL", "dr:ttl:cleared"), -1, "DUMP does not retain source TTL")
    future = int(time.time() * 1000) + 60000
    expect(client.cmd("RESTORE", "dr:ttl:absolute", future, ttl_payload, "ABSTTL"), b"+OK",
           "absolute TTL restore")
    absolute_ttl = client.cmd("PTTL", "dr:ttl:absolute")
    if not (0 < absolute_ttl <= 60000):
        raise AssertionError("ABSTTL mismatch: %r" % absolute_ttl)
    checks += 1
    expect(client.cmd("SET", "dr:ttl:past", "old"), b"+OK", "past REPLACE seed")
    expect(client.cmd("RESTORE", "dr:ttl:past", int(time.time() * 1000) - 1,
                      ttl_payload, "ABSTTL", "REPLACE"), b"+OK", "expired ABSTTL")
    expect(client.cmd("EXISTS", "dr:ttl:past"), 0, "expired ABSTTL removed replacement")
    expect(client.cmd("RESTORE", "dr:ttl:wrap", (1 << 63) - 1, ttl_payload), b"+OK",
           "relative TTL signed wrap")
    expect(client.cmd("EXISTS", "dr:ttl:wrap"), 0, "wrapped TTL already expired")

    corrupt_error = b"-ERR DUMP payload version or checksum are wrong"
    variants = [
        (b"", "empty"),
        (payload[:19], "short"),
        (payload[:-1], "truncated checksum"),
        (bytes([payload[0] ^ 1]) + payload[1:], "magic bit flip"),
        (payload[:8] + bytes([payload[8] ^ 1]) + payload[9:], "version bit flip"),
        (payload[:10] + bytes([255]) + payload[11:], "type corruption"),
        (payload[:12] + bytes([payload[12] ^ 1]) + payload[13:], "payload bit flip"),
        (payload[:-1] + bytes([payload[-1] ^ 1]), "checksum bit flip"),
    ]
    for index, (bad, label) in enumerate(variants):
        key = "dr:corrupt:%d" % index
        expect(client.cmd("RESTORE", key, "0", bad), corrupt_error, label)
        expect(client.cmd("EXISTS", key), 0, label + " no mutation")

    # A valid envelope whose per-type encoding byte is impossible reaches the hook and fails cleanly.
    bad_encoding = payload[:11] + b"\xff" + payload[12:]
    expect(client.cmd("RESTORE", "dr:badencoding", "0", bad_encoding),
           b"-ERR Bad data format", "snapshot hook rejects encoding")
    expect(client.cmd("EXISTS", "dr:badencoding"), 0, "bad encoding no mutation")
    expect(client.cmd("FLUSHALL"), b"+OK", "cleanup")


def prepare_restart():
    expect(client.cmd("FLUSHALL"), b"+OK", "restart clean")
    cases = build_cases("dr:restart")
    for index, (source, kind) in enumerate(cases):
        payload = client.cmd("DUMP", source)
        validate_envelope(payload, "restart " + source)
        expect(client.cmd("SET", "dr:restart:blob:%02d" % index, payload), b"+OK", "store envelope")
        destination = "dr:restart:pre:%02d" % index
        expect(client.cmd("RESTORE", destination, "0", payload), b"+OK", "pre-restart restore")
        expect(observation(destination, kind), observation(source, kind), "pre-restart compare")
    expect(client.cmd("SAVE"), b"+OK", "snapshot SAVE")


def verify_restart():
    cases = case_defs("dr:restart")
    for index, (source, kind) in enumerate(cases):
        pre = "dr:restart:pre:%02d" % index
        expect(observation(pre, kind), observation(source, kind), "loaded pre-copy")
        payload = client.cmd("GET", "dr:restart:blob:%02d" % index)
        validate_envelope(payload, "loaded envelope")
        post = "dr:restart:post:%02d" % index
        expect(client.cmd("RESTORE", post, "0", payload), b"+OK", "post-restart restore")
        expect(observation(post, kind), observation(source, kind), "post-restart compare")
    expect(client.cmd("FLUSHALL"), b"+OK", "restart cleanup")


if MODE == "live":
    live_battery()
elif MODE == "prepare_restart":
    prepare_restart()
elif MODE == "verify_restart":
    verify_restart()
else:
    raise SystemExit("unknown mode %s" % MODE)

print("dumprestore: PASS (%d checks, mode=%s; snapshot hooks/envelope/TTL fired)" % (checks, MODE))
