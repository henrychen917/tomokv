#!/usr/bin/env python3
"""Directed runtime check for the generated Redis 7.4 ACL category table."""

import pathlib
import re
import socket
import sys


HOST, PORT = sys.argv[1], int(sys.argv[2])
ROOT = pathlib.Path(__file__).resolve().parents[1]
GENERATED = (ROOT / "src/cmd/acl_categories_generated.h").read_text()
METADATA = (ROOT / "src/cmd/cmdmeta_generated.inc").read_text()

# TWO tables carry ACL categories and each feeds a different path:
#
#   +@keyspace          -> command registry, masks from acl_categories_generated.h (top-level only)
#   ACL CAT keyspace    -> cold metadata, masks from cmdmeta_generated.inc (includes subcommands)
#
# ACL CAT enumerates the metadata table so that subcommands appear the way Redis reports them --
# real 7.4 lists object|encoding .. object|refcount under @keyspace, and the registry has no row for
# them because OBJECT is a single command there. So membership must be derived from the METADATA
# table; deriving it from the registry table under-reports by exactly the subcommands.
METADATA_ROWS = re.findall(
    r'\{"([a-z0-9|_-]+)",\s*(?:-?\d+),\s*0x[0-9a-fA-F]+ULL,\s*[^,]+,\s*[^,]+,\s*[^,]+,'
    r'\s*0x([0-9a-fA-F]+)ULL',
    METADATA[METADATA.index("kGeneratedMetadata[] = {"):])


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
command_rows = re.findall(r'\{"([A-Z0-9_-]+)", 0x([0-9a-f]{16})ULL\}', GENERATED)
if len(category_rows) != 21 or not command_rows:
    raise AssertionError("could not read generated category table")

sock = socket.create_connection((HOST, PORT), timeout=10)
bare = command(sock, "ACL", "CAT")
expected_names = [name.encode() for name, _ in category_rows]
if bare != expected_names:
    raise AssertionError(f"ACL CAT: got {bare!r}, wanted {expected_names!r}")

if not METADATA_ROWS:
    raise AssertionError("could not read generated metadata table")

# The two tables must agree wherever they overlap. They are separate sources of truth for the same
# fact, so drift between them would mean `+@cat` grants a different set than `ACL CAT cat` reports
# -- silently, and in the direction of granting more or less than the operator was shown.
registry_masks = {command_name.lower(): int(mask, 16) for command_name, mask in command_rows}
metadata_masks = {command_name: int(mask, 16) for command_name, mask in METADATA_ROWS}
top_level = {name: mask for name, mask in metadata_masks.items() if "|" not in name}
if set(top_level) != set(registry_masks):
    only_meta = sorted(set(top_level) - set(registry_masks))
    only_registry = sorted(set(registry_masks) - set(top_level))
    raise AssertionError(f"table membership differs: metadata-only {only_meta}, "
                         f"registry-only {only_registry}")
disagree = sorted(name for name, mask in top_level.items() if registry_masks[name] != mask)
if disagree:
    detail = ", ".join(f"{name}: metadata 0x{top_level[name]:016x} vs "
                       f"registry 0x{registry_masks[name]:016x}" for name in disagree[:6])
    raise AssertionError(f"{len(disagree)} command(s) carry different ACL categories in the two "
                         f"generated tables -- {detail}")

for name, bit_text in category_rows:
    bit = int(bit_text)
    expected = sorted(command_name.encode()
                      for command_name, mask in METADATA_ROWS
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
