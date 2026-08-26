#!/usr/bin/env python3
"""Directed BITFIELD/BITFIELD_RO grammar, boundary, growth, and accounting battery."""

import socket
import sys


HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 6379


def encode(args):
    payload = b"*%d\r\n" % len(args)
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        else:
            arg = str(arg).encode() if isinstance(arg, int) else arg
        payload += b"$%d\r\n" % len(arg) + arg + b"\r\n"
    return payload


class Client:
    def __init__(self):
        self.socket = socket.create_connection((HOST, PORT), timeout=30)
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


def memory_bytes():
    raw = client.cmd("INFO", "memory")
    fields = {}
    for line in raw.splitlines():
        if b":" in line:
            key, value = line.split(b":", 1)
            fields[key] = value
    return int(fields[b"used_memory_dataset"])


expect(client.cmd("FLUSHALL"), b"+OK", "clean slate")
expect(client.cmd("BITFIELD", "bf:empty"), [], "empty operation list")
expect(client.cmd("BITFIELD", "bf:empty", "OVERFLOW", "SAT"), [], "overflow-only list")
expect(client.cmd("BITFIELD_RO", "bf:empty", "OVERFLOW", "FAIL"), [], "RO overflow-only list")

# Every legal width is accepted and round-trips its extreme representable value.
for bits in range(1, 64):
    maximum = (1 << bits) - 1
    expect(client.cmd("BITFIELD", "bf:u:%d" % bits,
                      "SET", "u%d" % bits, "0", maximum,
                      "GET", "u%d" % bits, "0"),
           [0, maximum], "unsigned width %d" % bits)
for bits in range(1, 65):
    minimum = -(1 << (bits - 1))
    expect(client.cmd("BITFIELD", "bf:i:%d" % bits,
                      "SET", "i%d" % bits, "0", minimum,
                      "GET", "i%d" % bits, "0"),
           [0, minimum], "signed width %d" % bits)

type_error = (b"-ERR Invalid bitfield type. Use something like i16 u8. "
              b"Note that u64 is not supported but i64 is.")
for bad_type in ("u0", "u64", "i0", "i65", "I8", "u01", "x8"):
    expect(client.cmd("BITFIELD", "bf:badtype", "GET", bad_type, "0"),
           type_error, "reject type %s" % bad_type)

offset_error = b"-ERR bit offset is not an integer or out of range"
for bad_offset in ("-1", "+1", "00", "#-1", "#1152921504606846976"):
    expect(client.cmd("BITFIELD", "bf:badoffset", "GET", "i8", bad_offset),
           offset_error, "reject offset %s" % bad_offset)
expect(client.cmd("BITFIELD", "bf:syntax", "NOPE"), b"-ERR syntax error", "bad subcommand")
expect(client.cmd("BITFIELD", "bf:syntax", "OVERFLOW", "NOPE"),
       b"-ERR Invalid OVERFLOW type specified", "bad overflow mode")

# #offsets are element indexes, and mixed operations observe earlier writes in the same command.
expect(client.cmd("BITFIELD", "bf:hash", "SET", "u4", "#2", "10",
                  "GET", "u4", "#2", "INCRBY", "u4", "#2", "1"),
       [0, 10, 11], "# element offsets")
expect(client.cmd("STRLEN", "bf:hash"), 2, "# offset byte growth")

expect(client.cmd("DEL", "bf:missing"), 0, "missing precondition")
expect(client.cmd("BITFIELD", "bf:missing", "GET", "u8", "0", "GET", "i16", "7"),
       [0, 0], "missing reads are zero")
expect(client.cmd("EXISTS", "bf:missing"), 0, "pure GET does not create")
expect(client.cmd("SET", "bf:short", b"\x80"), b"+OK", "short seed")
expect(client.cmd("BITFIELD", "bf:short", "GET", "u8", "8", "GET", "u16", "4"),
       [0, 0], "past-end and straddling reads")
expect(client.cmd("SET", "bf:int", "12345"), b"+OK", "integer seed")
expect(client.cmd("BITFIELD", "bf:int", "GET", "u8", "0"), [ord("1")], "integer encoding read")

# SET returns old; INCRBY returns new. Exercise both directions at signed/unsigned boundaries.
def boundary(key, type_name, initial, increment, mode, expected):
    client.cmd("DEL", key)
    client.cmd("BITFIELD", key, "SET", type_name, "0", initial)
    return client.cmd("BITFIELD", key, "OVERFLOW", mode,
                      "INCRBY", type_name, "0", increment,
                      "GET", type_name, "0")


for mode, result in (("WRAP", [0, 0]), ("SAT", [255, 255]), ("FAIL", [None, 255])):
    expect(boundary("bf:u8:up:" + mode, "u8", 255, 1, mode, result), result,
           "u8 overflow " + mode)
for mode, result in (("WRAP", [255, 255]), ("SAT", [0, 0]), ("FAIL", [None, 0])):
    expect(boundary("bf:u8:down:" + mode, "u8", 0, -1, mode, result), result,
           "u8 underflow " + mode)
for mode, result in (("WRAP", [-128, -128]), ("SAT", [127, 127]), ("FAIL", [None, 127])):
    expect(boundary("bf:i8:up:" + mode, "i8", 127, 1, mode, result), result,
           "i8 overflow " + mode)
for mode, result in (("WRAP", [127, 127]), ("SAT", [-128, -128]), ("FAIL", [None, -128])):
    expect(boundary("bf:i8:down:" + mode, "i8", -128, -1, mode, result), result,
           "i8 underflow " + mode)

expect(boundary("bf:u63", "u63", (1 << 63) - 1, 1, "WRAP", [0, 0]),
       [0, 0], "u63 exact maximum")
expect(boundary("bf:i64:max", "i64", (1 << 63) - 1, 1, "WRAP",
                [-(1 << 63), -(1 << 63)]),
       [-(1 << 63), -(1 << 63)], "i64 maximum wrap")
expect(boundary("bf:i64:min", "i64", -(1 << 63), -1, "WRAP",
                [(1 << 63) - 1, (1 << 63) - 1]),
       [(1 << 63) - 1, (1 << 63) - 1], "i64 minimum wrap")

expect(client.cmd("DEL", "bf:ordered"), 0, "ordered clean")
expect(client.cmd("BITFIELD", "bf:ordered", "SET", "u8", "0", "255",
                  "OVERFLOW", "SAT", "INCRBY", "u8", "0", "1",
                  "OVERFLOW", "WRAP", "INCRBY", "u8", "0", "1"),
       [0, 255, 0], "overflow applies only to following operations")

# Parse pass is mutation-free, and RO rejects writes only after parsing the complete list.
expect(client.cmd("SET", "bf:parse", b"\x00"), b"+OK", "parse seed")
expect(client.cmd("BITFIELD", "bf:parse", "SET", "u8", "0", "1", "GET", "u64", "0"),
       type_error, "late parse error")
expect(client.cmd("GET", "bf:parse"), b"\x00", "late parse error did not write")
expect(client.cmd("BITFIELD_RO", "bf:parse", "GET", "u8", "0"), [0], "RO GET")
expect(client.cmd("BITFIELD_RO", "bf:parse", "GET", "u8", "0", "SET", "u8", "0", "1"),
       b"-ERR BITFIELD_RO only supports the GET subcommand", "RO write refusal")
expect(client.cmd("GET", "bf:parse"), b"\x00", "RO refusal did not write")
expect(client.cmd("SADD", "bf:wrong", "x"), 1, "wrong-type seed")
expect(client.cmd("BITFIELD", "bf:wrong"),
       b"-WRONGTYPE Operation against a key holding the wrong kind of value",
       "empty list still type-checks")

# TTL survives bitmap materialization.
expect(client.cmd("SET", "bf:ttl", "1", "PX", "60000"), b"+OK", "TTL seed")
before_ttl = client.cmd("PTTL", "bf:ttl")
expect(client.cmd("BITFIELD", "bf:ttl", "SET", "u8", "#4", "9"), [0], "TTL write")
after_ttl = client.cmd("PTTL", "bf:ttl")
if not (0 < after_ttl <= before_ttl):
    raise AssertionError("BITFIELD did not preserve TTL: before=%r after=%r" % (before_ttl, after_ttl))
checks += 1

# Inline-16 operation storage spills without changing reply shape.
many = ["BITFIELD", "bf:many"]
for index in range(24):
    many += ["GET", "u1", str(index)]
expect(client.cmd(*many), [0] * 24, "operation-list heap spill")

# obj_bytes must move by the bitmap growth and fall after deletion.
expect(client.cmd("FLUSHALL"), b"+OK", "accounting clean")
before = memory_bytes()
expect(client.cmd("BITFIELD", "bf:account", "SET", "u8", "#100000", "1"), [0],
       "large # growth")
expect(client.cmd("STRLEN", "bf:account"), 100001, "large # exact length")
grown = memory_bytes()
if grown < before + 100000:
    raise AssertionError("obj_bytes did not account bitmap growth: %d -> %d" % (before, grown))
checks += 1
expect(client.cmd("DEL", "bf:account"), 1, "accounting delete")
shrunk = memory_bytes()
if shrunk >= grown or shrunk > before + 256:
    raise AssertionError("obj_bytes did not release bitmap growth: %d -> %d -> %d" %
                         (before, grown, shrunk))
checks += 1

# The replacement admission path must reject a single oversized growth under noeviction.
expect(client.cmd("CONFIG", "SET", "maxmemory-policy", "noeviction"), b"+OK", "noeviction")
expect(client.cmd("CONFIG", "SET", "maxmemory", "65536"), b"+OK", "small maxmemory")
try:
    expect(client.cmd("BITFIELD", "bf:oom", "SET", "u8", "#100000", "1"),
           b"-OOM command not allowed when used memory > 'maxmemory'.", "growth admission")
    expect(client.cmd("EXISTS", "bf:oom"), 0, "OOM growth did not create")
finally:
    expect(client.cmd("CONFIG", "SET", "maxmemory", "0"), b"+OK", "restore maxmemory")

expect(client.cmd("FLUSHALL"), b"+OK", "cleanup")
print("bitfield: PASS (%d checks; all widths, overflow, RO, #, accounting/admission fired)" % checks)
