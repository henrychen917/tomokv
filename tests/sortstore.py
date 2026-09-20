#!/usr/bin/env python3
"""SORT key metadata and selected-DB regression; connects to mainline-owned servers only."""
import argparse
import csv
from pathlib import Path

from _lib import Conn, RespError, encode, topology


def cases():
    rows = []
    with Path(__file__).with_name("sortstore_cases.tsv").open() as source:
        for row in csv.reader(source, delimiter="\t"):
            if not row or row[0].startswith("#"):
                continue
            name, indexes, *argv = row
            keys = [int(index) for index in indexes.split(",")]
            assert len(argv) >= 2 and keys[0] == 1 and max(keys) < len(argv), name
            rows.append((name, keys, argv))
    assert rows and len({row[0] for row in rows}) == len(rows), "empty/duplicate SORT corpus"
    return rows


def key_commands():
    """The ordinary SORT differ gates exactly the same argv as the parser unit."""
    return [["COMMAND", verb, *argv]
            for _, _, argv in cases() for verb in ("GETKEYS", "GETKEYSANDFLAGS")]


def expect(got, wanted, label):
    if got != wanted:
        raise AssertionError(f"sortstore {label}: got {got!r}, expected {wanted!r}")


def check_keys(target, oracle):
    info = oracle.must("INFO", "SERVER")
    assert any(line.startswith(b"redis_version:7.4.") for line in info.splitlines()), info
    rows = cases()
    for name, indexes, argv in rows:
        wanted = [argv[index].encode() for index in indexes]
        flags = [[key, [b"RO", b"access"] if i == 0 else [b"OW", b"update"]]
                 for i, key in enumerate(wanted)]
        for verb, expected in (("GETKEYS", wanted), ("GETKEYSANDFLAGS", flags)):
            reference = oracle.cmd("COMMAND", verb, *argv)
            expect(reference, expected, f"{name} Redis {verb}")
            expect(target.cmd("COMMAND", verb, *argv), reference, f"{name} target {verb}")
    print(f"PASS sortstore Redis 7.4 key metadata: {len(rows)} cases")


def check_namespace(c):
    """Also called by the existing multidb gate battery, before its concurrent writers."""
    expect(c.cmd("CONFIG", "GET", "databases"), [b"databases", b"16"], "database count")
    source, destination = "sortstore:src", "sortstore:dst"
    weights = [f"sortstore:weight:{i}" for i in (1, 2, 3)]
    # Each shape starts with an absent destination in both namespaces; a prior
    # passing STORE cannot conceal a subsequent misplaced write.
    shapes = [
        ("oracle", ["STORE", destination, "BY", "STORE", "LIMIT", "0", "2"], [b"3", b"1"]),
        ("get-store-word", ["STORE", destination, "GET", "STORE", "LIMIT", "0", "2"], [b"", b""]),
        ("by-pattern", ["STORE", destination, "BY", "sortstore:weight:*"], [b"1", b"2", b"3"]),
    ]
    try:
        for name, options, expected in shapes:
            for db in (0, 1):
                expect(c.cmd("SELECT", db), b"OK", f"{name} cleanup SELECT {db}")
                c.must("DEL", source, destination, *weights)
            # One connection, one pipeline: SELECT/populate/SORT/immediate read.
            # BY STORE is globless and suppresses sorting, so the oracle retains
            # the source's first two elements. The real BY pattern sorts by weight.
            commands = [
                ["SELECT", "1"], ["RPUSH", source, "3", "1", "2"],
                ["MSET", weights[0], "10", weights[1], "20", weights[2], "30"],
                ["SORT", source, *options], ["LRANGE", destination, "0", "-1"],
                ["TYPE", destination], ["GET", destination],
                ["SELECT", "0"], ["EXISTS", destination], ["LRANGE", destination, "0", "-1"],
            ]
            replies = [b"OK", 3, b"OK", len(expected), expected, b"list",
                       RespError("WRONGTYPE Operation against a key holding the wrong kind of value"),
                       b"OK", 0, []]
            c.raw(b"".join(encode(*command) for command in commands))
            actual = [c.read() for _ in commands]  # drain even on a failed assertion
            for command, got, wanted in zip(commands, actual, replies):
                expect(got, wanted, f"{name} selected-DB RYOW {command!r}")
    finally:
        for db in (0, 1):
            c.must("SELECT", db)
            c.must("DEL", source, destination, *weights)
        c.must("SELECT", 0)
    print("PASS sortstore selected-DB STORE/read pipeline and DB 0 isolation")


def geometry(c, mode):
    topo = topology(c)
    expect(topo.mode, mode, "thread mode")
    expect(len(topo.roles), 8, "eight threads")
    expect(len(topo.shard_owner), 16, "sixteen shards")
    if mode == "2s":
        expect(list(topo.roles.values()).count("io"), 6, "six IO threads")
        expect(list(topo.roles.values()).count("ex"), 2, "two executor threads")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--check", choices=("keys", "live", "all"), default="all")
    parser.add_argument("--oracle-host", default="127.0.0.1")
    parser.add_argument("--oracle-port", type=int)
    parser.add_argument("--thread-mode", choices=("1s", "2s"), default="2s")
    args = parser.parse_args()
    if args.check != "live" and args.oracle_port is None:
        parser.error("--oracle-port is required for keys/all")
    target = Conn(args.host, args.port)
    try:
        if args.check != "live":
            oracle = Conn(args.oracle_host, args.oracle_port)
            try:
                check_keys(target, oracle)
            finally:
                oracle.close()
        if args.check != "keys":
            geometry(target, args.thread_mode)
            check_namespace(target)
    finally:
        target.close()


if __name__ == "__main__":
    main()
