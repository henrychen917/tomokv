#!/usr/bin/env python3
"""Encoding boundary stream, byte oracle replay, and per-key INFO accounting.

The unit endpoint calls real handlers without a TomoKV listener or workers. Live
dispatch/MVCC proof uses this same stream through differ.py on maintainer boots.
This module never starts a server; --oracle-port must name an existing oracle.
"""
import argparse
import ast
import gzip
import hashlib
import json
import random
from pathlib import Path
import subprocess

from _lib import Conn, encode

DEFAULTS = {
    "hash-max-listpack-entries": 512, "hash-max-listpack-value": 64,
    "list-max-listpack-size": -2, "set-max-intset-entries": 512,
    "set-max-listpack-entries": 128, "set-max-listpack-value": 64,
    "zset-max-listpack-entries": 128, "zset-max-listpack-value": 64,
}


def commands():
    rows = []
    def add(*args):
        rows.append(tuple(str(a) if not isinstance(a, bytes) else a for a in args))
    def mutation(key, command, *args):
        add(command, key, *args)
        add("OBJECT", "ENCODING", key)
    def setting(**values):
        add("CONFIG", "SET", *(a for pair in values.items() for a in pair))

    for name in DEFAULTS:
        add("CONFIG", "GET", name)
    for phase, h, si, sl, z, v in (("default", 512, 512, 128, 128, 64),
                                  ("custom", 4, 3, 5, 4, 8)):
        if phase == "custom":
            setting(**{"hash-max-listpack-entries": h, "hash-max-listpack-value": v,
                       "set-max-intset-entries": si, "set-max-listpack-entries": sl,
                       "set-max-listpack-value": v, "zset-max-listpack-entries": z,
                       "zset-max-listpack-value": v})
        for kind, count, create, remove in (("hash", h, "HSET", "HDEL"),
                                          ("intset", si, "SADD", "SREM"),
                                          ("set", sl, "SADD", "SREM"),
                                          ("zset", z, "ZADD", "ZREM")):
            key = f"efx:{phase}:{kind}"
            add("DEL", key)
            for i in range(count + 1):
                member = str(i) if kind == "intset" else f"m{i}"
                values = (member, "v") if kind == "hash" else (i, member) if kind == "zset" else (member,)
                mutation(key, create, *values)
            # Cross downward through the threshold, then all the way to deletion.
            for i in range(count, -1, -1):
                mutation(key, remove, str(i) if kind == "intset" else f"m{i}")
        for kind, create, remove in (("hash", "HSET", "HDEL"), ("set", "SADD", "SREM"),
                                     ("zset", "ZADD", "ZREM")):
            key = f"efx:{phase}:{kind}:value"
            add("DEL", key)
            for n in (v, v + 1):
                member = "x" * n
                values = (member, "v") if kind == "hash" else (n, member) if kind == "zset" else (member,)
                mutation(key, create, *values)
            mutation(key, remove, "x" * (v + 1))
            add("DEL", key)
        # Integer -> text conversion: include all existing integer text lengths.
        for members, text in ((("1", "2"), "x"), (("9223372036854775807",), "x"),
                              (("1",), "x" * (v + 1)), (("1",), "01")):
            key = f"efx:{phase}:mixed"
            add("DEL", key)
            mutation(key, "SADD", *members)
            mutation(key, "SADD", text)
            mutation(key, "SREM", text)
        for wide in ("9223372036854775807", "-9223372036854775808"):
            key = f"efx:{phase}:removed-wide"
            add("DEL", key)
            mutation(key, "SADD", wide, "1")
            mutation(key, "SREM", wide)
            mutation(key, "SADD", "x")

    # Fresh hints choose intset/listpack/HT; existing hints promote directly to HT,
    # even when every argument is a duplicate. These are different Redis rules.
    for key, seed, incoming in (("fresh", (), ("0", "1", "2", "3")),
                                ("hint", ("1",), ("1", "1", "1", "1")),
                                ("lp-hint", ("x",), ("x",) * 6)):
        key = "efx:" + key
        add("DEL", key)
        if seed: mutation(key, "SADD", *seed)
        mutation(key, "SADD", *incoming)
    add("DEL", "efx:lower")
    setting(**{"set-max-intset-entries": 5})
    mutation("efx:lower", "SADD", "1", "2", "3", "4")
    setting(**{"set-max-intset-entries": 2})
    add("OBJECT", "ENCODING", "efx:lower")
    mutation("efx:lower", "SADD", "1")  # duplicate does not rebuild
    mutation("efx:lower", "SADD", "5")
    for integer, pack in ((0, 5), (3, 0), (0, 0)):
        setting(**{"set-max-intset-entries": integer, "set-max-listpack-entries": pack})
        add("DEL", "efx:zero")
        mutation("efx:zero", "SADD", "1")
        mutation("efx:zero", "SADD", "x")

    name = "set-max-intset-entries"
    for value in ("0", "7", "512", "9223372036854775807"):
        add("CONFIG", "SET", name, value)
        add("CONFIG", "GET", name)
    for value in ("-1", "+1", "01", "-0", "1kb", "", "9223372036854775808", b"1\0x"):
        add("CONFIG", "SET", name, value)
        add("CONFIG", "GET", name)
    add("CONFIG", "SET", name, "2", name.upper(), "3")
    add("CONFIG", "GET", name)
    setting(**DEFAULTS)
    return rows


def read_wire(file):
    line = file.readline()
    if not line: raise EOFError("endpoint exited before replying")
    if line[:1] in (b"+", b"-", b":"): return line
    n = int(line[1:-2])
    if line[:1] == b"$": return line + (file.read(n + 2) if n >= 0 else b"")
    if line[:1] == b"*": return line + b"".join(read_wire(file) for _ in range(max(0, n)))
    raise AssertionError(line)


class Unit:
    def __init__(self, binary, atomic):
        self.p = subprocess.Popen([binary, "trace", str(atomic)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    def cmd(self, *args):
        self.p.stdin.write(encode(*args)); self.p.stdin.flush()
        return read_wire(self.p.stdout)
    def close(self):
        self.p.stdin.close()
        if self.p.wait(timeout=20): raise AssertionError("unit endpoint failed")


class Oracle:
    def __init__(self, port): self.conn = Conn("127.0.0.1", port)
    def cmd(self, *args):
        self.conn.send(*args)
        return read_wire(self.conn.file)
    def close(self): self.conn.close()


def memory(endpoint, n):
    def used():
        wire = endpoint.cmd("INFO", "MEMORY")
        return int(next(line.split(b":")[1] for line in wire.split(b"\r\n") if line.startswith(b"used_memory:")))
    out = []
    for shape, count, op in (("hash100", 100, "HSET"), ("hash300", 300, "HSET"),
                             ("intset300", 300, "SADD"), ("stringset64", 64, "SADD")):
        keys = [f"efm:{i:08d}" for i in range(n)]
        for key in keys: endpoint.cmd("DEL", key)
        used()  # first INFO allocation is outside the baseline
        before = used()
        for key in keys:
            members = [str(i) if shape == "intset300" else f"m{i:03d}" for i in range(count)]
            args = [x for member in members for x in (member, "v")] if op == "HSET" else members
            response = endpoint.cmd(op, key, *args)
            assert response == f":{count}\r\n".encode(), response
        after = used()
        out.append(dict(shape=shape, keys=n, used_before=before, used_after=after,
                        bytes_per_key=(after-before)/n,
                        encoding=endpoint.cmd("OBJECT", "ENCODING", keys[0]).decode()))
        for key in keys: endpoint.cmd("DEL", key)
    return out


def collection_suite(name, seed):
    # Load only the existing pure generators/normalizer, avoiding differ.py's live
    # socket driver at module scope. No generator or comparison rule is duplicated.
    path = Path(__file__).with_name("differ.py")
    tree = ast.parse(path.read_text())
    names = {"gen_" + name, "parse_reply", "sort_nested", "normalize"}
    nodes = [node for node in tree.body if
             isinstance(node, ast.FunctionDef) and node.name in names or
             isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
             t.id == "SORTED_SET_REPLIES" for t in node.targets)]
    scope = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), scope)
    return scope["gen_" + name](random.Random(seed)), scope["normalize"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("record", "compare", "memory", "collections"))
    parser.add_argument("--oracle-port", type=int)
    parser.add_argument("--unit")
    parser.add_argument("--atomic", type=int, choices=(0, 1), default=0)
    parser.add_argument("--oracle-json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--keys", type=int, default=256)
    parser.add_argument("--suite", choices=("hash", "set", "zset"))
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    endpoint = Unit(args.unit, args.atomic) if args.unit else Oracle(args.oracle_port)
    try:
        if args.action == "memory":
            result = memory(endpoint, args.keys)
        elif args.action == "collections":
            assert args.unit and args.oracle_port and args.suite
            oracle = Oracle(args.oracle_port)
            rows, normalize = collection_suite(args.suite, args.seed)
            differences = []
            try:
                assert oracle.cmd("FLUSHDB") == b"+OK\r\n"
                for i, row in enumerate(rows):
                    actual = normalize(row[0], endpoint.cmd(*row))
                    expected = normalize(row[0], oracle.cmd(*row))
                    if actual != expected:
                        differences.append(dict(index=i, command=row, expected=expected.hex(), actual=actual.hex()))
            finally:
                oracle.close()
            result = dict(suite=args.suite, seed=args.seed, atomic=args.atomic,
                          commands=len(rows), differences=differences)
            args.output.write_text(json.dumps(result, indent=2) + "\n")
            print(f"{args.suite} seed={args.seed} atomic={args.atomic}: {len(rows)} replies, {len(differences)} differences")
            assert not differences, differences[:5]
        else:
            rows = commands()
            replies = [endpoint.cmd(*row).hex() for row in rows]
            digest = hashlib.sha256(b"".join(encode(*row) for row in rows)).hexdigest()
            result = dict(stream_sha256=digest, commands=len(rows), atomic=args.atomic, replies=replies)
            if args.action == "compare":
                data = args.oracle_json.read_bytes()
                reference = json.loads(gzip.decompress(data) if args.oracle_json.suffix == ".gz" else data)
                assert reference["stream_sha256"] == digest, "oracle stream differs"
                assert len(reference["replies"]) == len(replies), "oracle reply count differs"
                differences = [dict(index=i, command=[str(x) for x in rows[i]],
                                    expected=bytes.fromhex(a).decode(errors="replace"),
                                    actual=bytes.fromhex(b).decode(errors="replace"))
                               for i, (a, b) in enumerate(zip(reference["replies"], replies)) if a != b]
                result["differences"] = differences
                print(f"encodingfix atomic={args.atomic}: {len(rows)} replies, {len(differences)} differences")
                args.output.write_text(json.dumps(result, indent=2) + "\n")
                assert not differences, differences[:5]
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    finally:
        endpoint.close()


if __name__ == "__main__": main()
