#!/usr/bin/env python3
"""Hash-field TTL DUMP/RESTORE and Redis-wire interoperability battery.

Usage: tests/dumpttl.py TARGET_HOST TARGET_PORT [ORACLE_HOST ORACLE_PORT]

The optional oracle leg must point at vanilla Redis 7.4.  The target-only checks still cover the
codec, elapsed fields, whole-key TTLs, attention registration, and native snapshot reload.
"""

import socket
import sys
import time


TARGET_HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
TARGET_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 6379
ORACLE = (sys.argv[3], int(sys.argv[4])) if len(sys.argv) > 4 else None


def encode(args):
    wire = b"*%d\r\n" % len(args)
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        elif isinstance(arg, int):
            arg = str(arg).encode()
        wire += b"$%d\r\n" % len(arg) + arg + b"\r\n"
    return wire


class Client:
    def __init__(self, host, port):
        self.socket = socket.create_connection((host, port), timeout=60)
        self.file = self.socket.makefile("rb")

    def close(self):
        self.socket.close()

    def read(self):
        line = self.file.readline()
        if not line:
            raise RuntimeError("server closed the connection")
        kind = line[:1]
        if kind == b"+":
            return line[1:-2]
        if kind == b"-":
            return RuntimeError(line[1:-2].decode("utf-8", "replace"))
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


checks = 0


def expect(label, actual, wanted):
    global checks
    checks += 1
    if actual != wanted:
        raise AssertionError("%s: expected %r, got %r" % (label, wanted, actual))


def require(label, condition, detail):
    global checks
    checks += 1
    if not condition:
        raise AssertionError("%s: %s" % (label, detail))


def pairs(client, key):
    reply = client.cmd("HGETALL", key)
    return sorted((reply[i], reply[i + 1]) for i in range(0, len(reply), 2))


def field_times(client, key, *fields):
    return client.cmd("HPEXPIRETIME", key, "FIELDS", len(fields), *fields)


def info_counter(client, name):
    reply = client.cmd("INFO", "STATS")
    require("INFO STATS is a bulk reply", isinstance(reply, bytes), repr(reply))
    prefix = name.encode() + b":"
    for line in reply.split(b"\r\n"):
        if line.startswith(prefix):
            return int(line[len(prefix):])
    raise AssertionError("INFO STATS omitted %s" % name)


def dump(client, key, wanted_type=None):
    payload = client.cmd("DUMP", key)
    require("DUMP %s produced bytes" % key, isinstance(payload, bytes), repr(payload))
    require("DUMP %s has body and trailer" % key, len(payload) > 10, repr(payload))
    if wanted_type is not None:
        expect("DUMP %s RDB type" % key, payload[0], wanted_type)
    return payload


def seed_hash(client, key, fields, deadlines):
    args = ["HSET", key]
    for field, value in fields:
        args += [field, value]
    expect("HSET %s" % key, client.cmd(*args), len(fields))
    for deadline, names in deadlines:
        expect("HPEXPIREAT %s/%s" % (key, ",".join(names)),
               client.cmd("HPEXPIREAT", key, deadline, "FIELDS", len(names), *names),
               [1] * len(names))


def target_battery(target):
    now = int(time.time() * 1000)
    far = now + 24 * 60 * 60 * 1000
    farther = far + 70000

    expect("target FLUSHALL", target.cmd("FLUSHALL"), b"OK")
    expect("unarmed hash-field expiry control", info_counter(target, "hash_field_expires"), 0)

    # No field TTL: retain the ordinary canonical type and allocate/register nothing.
    seed_hash(target, "dt:none", [("a", "1"), ("b", "2")], [])
    plain = dump(target, "dt:none", 4)
    expect("RESTORE TTL-free hash", target.cmd("RESTORE", "dt:none:rest", 0, plain), b"OK")
    expect("TTL-free values", pairs(target, "dt:none:rest"), [(b"a", b"1"), (b"b", b"2")])
    expect("TTL-free deadlines", field_times(target, "dt:none:rest", "a", "b"), [-1, -1])
    expect("TTL-free negative registration control", info_counter(target, "hash_field_expires"), 0)

    # Some fields carry TTLs. Exact absolute times prove metadata, rather than just values, fired.
    seed_hash(target, "dt:some", [("a", "1"), ("b", "2"), ("c", "3")],
              [(far, ["a"]), (farther, ["c"])])
    before_restore = info_counter(target, "hash_field_expires")
    some = dump(target, "dt:some", 24)
    expect("RESTORE partial TTL hash", target.cmd("RESTORE", "dt:some:rest", 0, some), b"OK")
    expect("partial TTL values", pairs(target, "dt:some:rest"),
           [(b"a", b"1"), (b"b", b"2"), (b"c", b"3")])
    expect("partial TTL exact deadlines", field_times(target, "dt:some:rest", "a", "b", "c"),
           [far, -1, farther])
    expect("RESTORE re-armed field expiry attention",
           info_counter(target, "hash_field_expires"), before_restore + 1)

    # Every field carries a deadline, including equal minima.
    seed_hash(target, "dt:all", [("x", "10"), ("y", "20")], [(far, ["x", "y"])])
    all_payload = dump(target, "dt:all", 24)
    expect("RESTORE all-TTL hash", target.cmd("RESTORE", "dt:all:rest", 0, all_payload), b"OK")
    expect("all-TTL exact deadlines", field_times(target, "dt:all:rest", "x", "y"), [far, far])

    # Cache the DUMP while one deadline is live, then restore after it has elapsed. The codec load
    # must discard that field and retain both the persistent and later-expiring fields.
    soon = int(time.time() * 1000) + 350
    seed_hash(target, "dt:elapsed", [("gone", "1"), ("plain", "2"), ("later", "3")],
              [(soon, ["gone"]), (farther, ["later"])])
    elapsed_payload = dump(target, "dt:elapsed", 24)
    time.sleep(0.5)
    expect("RESTORE payload containing elapsed field",
           target.cmd("RESTORE", "dt:elapsed:rest", 0, elapsed_payload), b"OK")
    expect("elapsed field omitted on RESTORE", pairs(target, "dt:elapsed:rest"),
           [(b"later", b"3"), (b"plain", b"2")])
    expect("surviving field metadata after elapsed drop",
           field_times(target, "dt:elapsed:rest", "gone", "plain", "later"), [-2, -1, farther])

    # DUMP excludes the whole-key TTL. RESTORE's TTL argument controls it independently while the
    # field's absolute deadline remains part of the value payload.
    seed_hash(target, "dt:keyttl", [("f", "v"), ("p", "q")], [(farther, ["f"])])
    before_key_ttl = dump(target, "dt:keyttl", 24)
    key_deadline = int(time.time() * 1000) + 60000
    expect("whole-key PEXPIREAT", target.cmd("PEXPIREAT", "dt:keyttl", key_deadline), 1)
    after_key_ttl = dump(target, "dt:keyttl", 24)
    expect("DUMP excludes whole-key TTL", after_key_ttl, before_key_ttl)
    expect("RESTORE ABSTTL with field metadata",
           target.cmd("RESTORE", "dt:keyttl:rest", key_deadline, after_key_ttl, "ABSTTL"), b"OK")
    expect("RESTORE whole-key absolute deadline",
           target.cmd("PEXPIRETIME", "dt:keyttl:rest"), key_deadline)
    expect("RESTORE field and key TTLs are independent",
           field_times(target, "dt:keyttl:rest", "f", "p"), [farther, -1])

    # Native snapshot uses the same logical hash image. Reload a value that specifically arrived
    # through RESTORE, then require both exact deadlines and active-cycle registration.
    expect("DEBUG RELOAD snapshot round-trip", target.cmd("DEBUG", "RELOAD"), b"OK")
    expect("snapshot kept restored field deadlines",
           field_times(target, "dt:some:rest", "a", "b", "c"), [far, -1, farther])
    expect("snapshot kept restored values", pairs(target, "dt:some:rest"),
           [(b"a", b"1"), (b"b", b"2"), (b"c", b"3")])
    require("snapshot re-armed field expiry attention",
            info_counter(target, "hash_field_expires") > 0,
            "hash_field_expires stayed zero after reload")
    return far, farther


def cross_wire(target, oracle, far, farther):
    expect("oracle FLUSHALL", oracle.cmd("FLUSHALL"), b"OK")

    # Compact Redis hashes with TTLs use the observed listpackex RDB type (25).
    seed_hash(oracle, "dt:o:listpackex", [("a", "1"), ("b", "2"), ("c", "3")],
              [(far, ["a"]), (farther, ["c"])])
    oracle_packed = dump(oracle, "dt:o:listpackex", 25)
    expect("reference listpackex -> target RESTORE",
           target.cmd("RESTORE", "dt:o:listpackex:rest", 0, oracle_packed, "REPLACE"), b"OK")
    expect("reference listpackex values", pairs(target, "dt:o:listpackex:rest"),
           [(b"a", b"1"), (b"b", b"2"), (b"c", b"3")])
    expect("reference listpackex deadlines",
           field_times(target, "dt:o:listpackex:rest", "a", "b", "c"), [far, -1, farther])

    # A >64-byte value forces Redis's hashtable representation and metadata RDB type (24).
    long_value = b"0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!!!"
    seed_hash(oracle, "dt:o:metadata", [("a", "1"), ("b", "2"), ("long", long_value)],
              [(far, ["a"]), (farther, ["b"])])
    oracle_metadata = dump(oracle, "dt:o:metadata", 24)
    expect("reference metadata -> target RESTORE",
           target.cmd("RESTORE", "dt:o:metadata:rest", 0, oracle_metadata, "REPLACE"), b"OK")
    expect("reference metadata values", pairs(target, "dt:o:metadata:rest"),
           [(b"a", b"1"), (b"b", b"2"), (b"long", long_value)])
    expect("reference metadata deadlines",
           field_times(target, "dt:o:metadata:rest", "a", "b", "long"), [far, farther, -1])

    # TomoKV deliberately emits the simple metadata form. Redis must accept it in both partial and
    # all-field cases, proving the reverse wire direction rather than self-compatibility alone.
    for source, fields, wanted in (
            ("dt:some", ("a", "b", "c"), [far, -1, farther]),
            ("dt:all", ("x", "y"), [far, far])):
        payload = dump(target, source, 24)
        destination = source + ":on-oracle"
        expect("target -> reference RESTORE %s" % source,
               oracle.cmd("RESTORE", destination, 0, payload, "REPLACE"), b"OK")
        expect("target -> reference values %s" % source,
               pairs(oracle, destination), pairs(target, source))
        expect("target -> reference deadlines %s" % source,
               field_times(oracle, destination, *fields), wanted)


def main():
    target = Client(TARGET_HOST, TARGET_PORT)
    oracle = Client(*ORACLE) if ORACLE else None
    try:
        far, farther = target_battery(target)
        if oracle:
            cross_wire(target, oracle, far, farther)
        else:
            print("SKIP live Redis 7.4 cross-wire leg (no oracle host/port supplied)")
    finally:
        target.close()
        if oracle:
            oracle.close()
    print("PASS dumpttl: %d checks%s" % (checks, " with Redis 7.4 cross-wire" if ORACLE else ""))


if __name__ == "__main__":
    main()
