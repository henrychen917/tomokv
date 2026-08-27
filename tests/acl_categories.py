#!/usr/bin/env python3
"""Directed runtime check for the generated Redis 7.4 ACL category table."""

import pathlib
import re
import socket
import sys


HOST, PORT = sys.argv[1], int(sys.argv[2])
ROOT = pathlib.Path(__file__).resolve().parents[1]
GENERATED = (ROOT / "src/cmd/acl_categories_generated.h").read_text()


class RespError(Exception):
    pass


def command(sock, *args):
    encoded = [arg.encode() if isinstance(arg, str) else arg for arg in args]
    sock.sendall(
        b"*%d\r\n" % len(encoded) +
        b"".join(b"$%d\r\n" % len(arg) + arg + b"\r\n" for arg in encoded)
    )
    file = sock.makefile("rb")

    def read():
        prefix = file.read(1)
        line = file.readline()
        if not prefix or not line.endswith(b"\r\n"):
            raise AssertionError("truncated RESP reply")
        value = line[:-2]
        if prefix == b"+":
            return value
        if prefix == b"-":
            return RespError(value.decode())
        if prefix == b":":
            return int(value)
        if prefix == b"$":
            length = int(value)
            if length == -1:
                return None
            payload = file.read(length)
            if file.read(2) != b"\r\n":
                raise AssertionError("bad bulk terminator")
            return payload
        if prefix == b"*":
            return [read() for _ in range(int(value))]
        raise AssertionError(f"unknown RESP prefix {prefix!r}")

    return read()


category_rows = re.findall(r'\{"([a-z]+)", uint64_t\{1\} << (\d+)\}', GENERATED)
command_rows = re.findall(r'\{"([A-Z0-9_]+)", 0x([0-9a-f]{16})ULL\}', GENERATED)
if len(category_rows) != 21 or not command_rows:
    raise AssertionError("could not read generated category table")

sock = socket.create_connection((HOST, PORT), timeout=10)
bare = command(sock, "ACL", "CAT")
expected_names = [name.encode() for name, _ in category_rows]
if bare != expected_names:
    raise AssertionError(f"ACL CAT: got {bare!r}, wanted {expected_names!r}")

for name, bit_text in category_rows:
    bit = int(bit_text)
    expected = sorted(command_name.lower().encode()
                      for command_name, mask in command_rows
                      if int(mask, 16) & (1 << bit))
    # The server replies in registry order, which shifts whenever a family table is added or the
    # merge order changes; the MEMBERSHIP is the contract, so compare sorted.
    actual = sorted(command(sock, "ACL", "CAT", name.upper()))
    if actual != expected:
        raise AssertionError(f"ACL CAT {name}: got {actual!r}, wanted {expected!r}")

unknown = command(sock, "ACL", "CAT", "not-a-category")
if not isinstance(unknown, RespError) or str(unknown) != "ERR Unknown category 'not-a-category'":
    raise AssertionError(f"bad unknown-category error: {unknown!r}")

sock.close()
