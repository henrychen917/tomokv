#!/usr/bin/env python3
"""Directed container-subcommand arity battery. Usage: tests/arity.py HOST PORT"""

import socket
import sys


HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 6379


def encode(argv):
    out = b"*%d\r\n" % len(argv)
    for arg in argv:
        value = arg.encode() if isinstance(arg, str) else arg
        out += b"$%d\r\n%s\r\n" % (len(value), value)
    return out


def read_reply(stream):
    line = stream.readline()
    if not line:
        raise EOFError("server closed the connection")
    marker = line[:1]
    if marker in b"+-:,_#(":
        return line
    if marker in (b"$", b"=", b"!"):
        length = int(line[1:-2])
        return line if length < 0 else line + stream.read(length + 2)
    if marker in (b"*", b"~", b">"):
        count = int(line[1:-2])
        return line if count < 0 else line + b"".join(read_reply(stream) for _ in range(count))
    if marker in (b"%", b"|"):
        count = int(line[1:-2])
        return line + b"".join(read_reply(stream) for _ in range(count * 2))
    raise ValueError("unsupported RESP marker %r" % marker)


def wrong(name):
    return b"-ERR wrong number of arguments for '%s' command\r\n" % name.encode()


def unknown(subcommand, container):
    return b"-ERR unknown subcommand '%s'. Try %s HELP.\r\n" % (
        subcommand.encode(), container.encode())


def unknown_or_wrong(subcommand, container):
    return b"-ERR unknown subcommand or wrong number of arguments for '%s'. Try %s HELP.\r\n" % (
        subcommand.encode(), container.encode())


# Every row below was byte-different from Redis 7.4 before this lane. Keep the odd-looking
# generic errors for ACL CAT/GENPASS/LOG and SLOWLOG GET: those subcommands have variadic command
# metadata in Redis and reject their upper bound inside the container handler.
CASES = [
    ("ACL CAT above", ["ACL", "CAT", "keyspace", "x"], unknown_or_wrong("CAT", "ACL")),
    ("ACL DELUSER below", ["ACL", "DELUSER"], wrong("acl|deluser")),
    ("ACL GENPASS above", ["ACL", "GENPASS", "8", "x"], unknown_or_wrong("GENPASS", "ACL")),
    ("ACL GETUSER below", ["ACL", "GETUSER"], wrong("acl|getuser")),
    ("ACL GETUSER above", ["ACL", "GETUSER", "default", "x"], wrong("acl|getuser")),
    ("ACL LIST above", ["ACL", "LIST", "x"], wrong("acl|list")),
    ("ACL LOAD above", ["ACL", "LOAD", "x"], wrong("acl|load")),
    ("ACL SAVE above", ["ACL", "SAVE", "x"], wrong("acl|save")),
    ("ACL LOG above", ["ACL", "LOG", "1", "x"], unknown_or_wrong("LOG", "ACL")),
    ("ACL SETUSER below", ["ACL", "SETUSER"], wrong("acl|setuser")),
    ("ACL USERS above", ["ACL", "USERS", "x"], wrong("acl|users")),
    ("ACL WHOAMI above", ["ACL", "WHOAMI", "x"], wrong("acl|whoami")),
    ("ACL HELP above", ["ACL", "HELP", "x"], wrong("acl|help")),
    ("ACL unknown", ["ACL", "BOGUS"], unknown("BOGUS", "ACL")),

    ("CONFIG GET below", ["CONFIG", "GET"], wrong("config|get")),
    ("CONFIG SET below", ["CONFIG", "SET", "maxmemory"], wrong("config|set")),
    ("CONFIG REWRITE above", ["CONFIG", "REWRITE", "x"], wrong("config|rewrite")),
    ("CONFIG RESETSTAT above", ["CONFIG", "RESETSTAT", "x"], wrong("config|resetstat")),
    ("CONFIG HELP above", ["CONFIG", "HELP", "x"], wrong("config|help")),
    ("CONFIG unknown", ["CONFIG", "BOGUS"], unknown("BOGUS", "CONFIG")),

    ("OBJECT ENCODING above", ["OBJECT", "ENCODING", "k", "x"], wrong("object|encoding")),
    ("OBJECT REFCOUNT above", ["OBJECT", "REFCOUNT", "k", "x"], wrong("object|refcount")),
    ("OBJECT IDLETIME above", ["OBJECT", "IDLETIME", "k", "x"], wrong("object|idletime")),
    ("OBJECT FREQ above", ["OBJECT", "FREQ", "k", "x"], wrong("object|freq")),
    ("OBJECT HELP above", ["OBJECT", "HELP", "x"], wrong("object|help")),

    ("MEMORY USAGE above", ["MEMORY", "USAGE", "k", "SAMPLES", "1", "x"],
     b"-ERR syntax error\r\n"),
    ("MEMORY STATS above", ["MEMORY", "STATS", "x"], wrong("memory|stats")),
    ("MEMORY DOCTOR above", ["MEMORY", "DOCTOR", "x"], wrong("memory|doctor")),
    ("MEMORY PURGE above", ["MEMORY", "PURGE", "x"], wrong("memory|purge")),
    ("MEMORY MALLOC-STATS above", ["MEMORY", "MALLOC-STATS", "x"],
     wrong("memory|malloc-stats")),
    ("MEMORY HELP above", ["MEMORY", "HELP", "x"], wrong("memory|help")),

    ("LATENCY HISTORY below", ["LATENCY", "HISTORY"], wrong("latency|history")),
    ("LATENCY HISTORY above", ["LATENCY", "HISTORY", "command", "x"],
     wrong("latency|history")),
    ("LATENCY GRAPH below", ["LATENCY", "GRAPH"], wrong("latency|graph")),
    ("LATENCY GRAPH above", ["LATENCY", "GRAPH", "command", "x"], wrong("latency|graph")),
    ("LATENCY DOCTOR above", ["LATENCY", "DOCTOR", "x"], wrong("latency|doctor")),
    ("LATENCY LATEST above", ["LATENCY", "LATEST", "x"], wrong("latency|latest")),
    ("LATENCY HELP above", ["LATENCY", "HELP", "x"], wrong("latency|help")),

    ("SLOWLOG GET above", ["SLOWLOG", "GET", "1", "x"], unknown_or_wrong("GET", "SLOWLOG")),
    ("SLOWLOG LEN above", ["SLOWLOG", "LEN", "x"], wrong("slowlog|len")),
    ("SLOWLOG RESET above", ["SLOWLOG", "RESET", "x"], wrong("slowlog|reset")),
    ("SLOWLOG HELP above", ["SLOWLOG", "HELP", "x"], wrong("slowlog|help")),
]


# Controls prove the outer container arity gate was not disturbed. These six rows were already
# byte-exact before the lane and must remain so.
OUTER_CONTROLS = [
    (name, [name], wrong(name.lower()))
    for name in ("ACL", "CONFIG", "OBJECT", "MEMORY", "LATENCY", "SLOWLOG")
]


# These rows complete the one-below/one-above/unknown matrix. They were already byte-exact before
# the lane, so they are controls rather than regression cases.
COMPAT_CONTROLS = [
    ("OBJECT ENCODING below", ["OBJECT", "ENCODING"], wrong("object|encoding")),
    ("OBJECT REFCOUNT below", ["OBJECT", "REFCOUNT"], wrong("object|refcount")),
    ("OBJECT IDLETIME below", ["OBJECT", "IDLETIME"], wrong("object|idletime")),
    ("OBJECT FREQ below", ["OBJECT", "FREQ"], wrong("object|freq")),
    ("OBJECT unknown", ["OBJECT", "BOGUS"], unknown("BOGUS", "OBJECT")),
    ("MEMORY USAGE below", ["MEMORY", "USAGE"], wrong("memory|usage")),
    ("MEMORY unknown", ["MEMORY", "BOGUS"], unknown("BOGUS", "MEMORY")),
    ("LATENCY unknown", ["LATENCY", "BOGUS"], unknown("BOGUS", "LATENCY")),
    ("SLOWLOG unknown", ["SLOWLOG", "BOGUS"], unknown("BOGUS", "SLOWLOG")),
]


# A second negative control exercises a valid form of every container. The detector must report
# zero errors, otherwise matching error strings in CASES would not prove correct classification.
VALID_CONTROLS = [
    ("ACL", ["ACL", "WHOAMI"]),
    ("CONFIG", ["CONFIG", "GET", "__arity_no_match__"]),
    ("OBJECT", ["OBJECT", "ENCODING", "__arity_missing__"]),
    ("MEMORY", ["MEMORY", "USAGE", "__arity_missing__"]),
    ("LATENCY", ["LATENCY", "RESET"]),
    ("SLOWLOG", ["SLOWLOG", "RESET"]),
]


sock = socket.create_connection((HOST, PORT), timeout=10)
stream = sock.makefile("rb")
failures = []
fired = {"wrong": 0, "unknown_or_wrong": 0, "unknown": 0, "syntax": 0}

for label, argv, expected in CASES:
    sock.sendall(encode(argv))
    got = read_reply(stream)
    if got != expected:
        failures.append("%s: got %r, want %r" % (label, got, expected))
    if got.startswith(b"-ERR wrong number"):
        fired["wrong"] += 1
    elif got.startswith(b"-ERR unknown subcommand or wrong number"):
        fired["unknown_or_wrong"] += 1
    elif got.startswith(b"-ERR unknown subcommand '"):
        fired["unknown"] += 1
    elif got == b"-ERR syntax error\r\n":
        fired["syntax"] += 1

for label, argv, expected in OUTER_CONTROLS + COMPAT_CONTROLS:
    sock.sendall(encode(argv))
    got = read_reply(stream)
    if got != expected:
        failures.append("%s control: got %r, want %r" % (label, got, expected))

valid_control_errors = 0
for label, argv in VALID_CONTROLS:
    sock.sendall(encode(argv))
    got = read_reply(stream)
    if got.startswith(b"-"):
        valid_control_errors += 1
        failures.append("valid %s control returned an error: %r" % (label, got))

sock.close()

expected_fired = {"wrong": 35, "unknown_or_wrong": 4, "unknown": 2, "syntax": 1}
if fired != expected_fired:
    failures.append("mechanism counts got %r, want %r" % (fired, expected_fired))
if valid_control_errors != 0:
    failures.append("valid-control detector must report zero, got %d" % valid_control_errors)

print("arity mechanism: cases=%d fired=%r outer_controls=%d compat_controls=%d "
      "valid_control_errors=%d" %
      (len(CASES), fired, len(OUTER_CONTROLS), len(COMPAT_CONTROLS), valid_control_errors))
if failures:
    for failure in failures[:20]:
        print("FAIL", failure)
    print("ARITY: %d checks, %d failures -> FAIL" %
          (len(CASES) + len(OUTER_CONTROLS) + len(COMPAT_CONTROLS) + len(VALID_CONTROLS),
           len(failures)))
    sys.exit(1)
print("ARITY: %d checks, 0 failures -> PASS" %
      (len(CASES) + len(OUTER_CONTROLS) + len(COMPAT_CONTROLS) + len(VALID_CONTROLS)))
