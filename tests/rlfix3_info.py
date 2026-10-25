#!/usr/bin/env python3
"""RL4.15 section-union wire battery plus a real-handler no-cell-read witness.

The gate owns all boots. The native fixture initializes stores but starts no
workers/listeners. It protects filter pages, so PRE deterministically faults;
no latency threshold is involved. --unit may name the frozen PRE-linked unit.
"""
import argparse
import resource
import subprocess

from _lib import Conn, info
from wave7 import selected_fields


SECTIONS = ("server", "clients", "memory", "persistence", "stats", "replication",
            "commandstats", "cluster", "keyspace", "writeback", "lb", "flipctl")
DEFAULT = set(SECTIONS) - {"commandstats", "lb"}


def headings(body):
    assert isinstance(body, bytes), body
    if body.startswith(b"txt:"): body = body[4:]
    names = [line[2:].decode().lower() for line in body.split(b"\r\n") if line.startswith(b"# ")]
    assert len(names) == len(set(names)), names
    return set(names)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("host"); p.add_argument("port", type=int)
    p.add_argument("--unit", required=True, action="append")
    args = p.parse_args()
    c = Conn(args.host, args.port)
    try:
        server = info(c, "server")
        mode = server["thread_mode"]
        for resp in (2, 3):
            assert isinstance(c.cmd("HELLO", resp), list)
            # No section alias creates duplicate headings, including repeated
            # names and overlapping DEFAULT/ALL/EVERYTHING unions.
            for names in ((), ("default",), ("all",), ("everything",),
                          ("SERVER", "clients", "server"), ("unknown",),
                          ("default", "commandstats"), ("everything", "unknown", "all"),
                          *((section,) for section in SECTIONS)):
                selected = DEFAULT if not names else set()
                for name in names:
                    name = name.lower()
                    if name in ("all", "everything"): selected |= set(SECTIONS)
                    elif name == "default": selected |= DEFAULT
                    elif name in SECTIONS: selected.add(name)
                got = headings(c.cmd("INFO", *names))
                assert got == selected, (resp, names, got, selected)
        selected_fields(c)
        print(f"RL4.15 wire unions PASS: {mode}, read-local {server['read_local']}", flush=True)
    finally:
        c.close()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    failures = []
    # Run all legs even when PRE faults. Both 16- and 256-shard paths must prove
    # they execute with their pages accessible before the protected call.
    for unit in args.unit:
        print(f"Native image: {unit}", flush=True)
        r = subprocess.run([unit, "rewrite", mode, "16"], capture_output=True)
        print(f"RL4.11 CONFIG REWRITE rc={r.returncode}", flush=True)
        if r.returncode: failures.append((unit, "rewrite", r.returncode, r.stderr.decode(errors="replace")))
        for shards in (16, 256):
            for names in (("server",), ("clients",), ("server", "clients"), ("unknown",)):
                r = subprocess.run([unit, "metadata", mode, str(shards), *names], capture_output=True)
                print(f"RL4.15 metadata {mode} shards={shards} sections={names} rc={r.returncode}", flush=True)
                if r.returncode: failures.append((unit, "metadata", shards, names, r.returncode))
            for names in (("server",), ("all",), ("everything",), ("server", "clients")):
                for arm in ("snapshot", "guard"):
                    r = subprocess.run([unit, arm, mode, str(shards), *names], capture_output=True)
                    print(f"RL4.15 unit {mode} shards={shards} sections={names} {arm} rc={r.returncode}", flush=True)
                    if r.returncode:
                        failures.append((unit, shards, names, arm, r.returncode, r.stderr.decode(errors="replace")))
        r = subprocess.run([unit, "counts"], capture_output=True)
        print(f"RL4.15 counter transitions rc={r.returncode}", flush=True)
        if r.returncode: failures.append((unit, "counts", r.returncode, r.stderr.decode(errors="replace")))
    assert not failures, failures


if __name__ == "__main__":
    main()
