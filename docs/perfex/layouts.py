#!/usr/bin/env python3
"""DWARF-only layout proof; never starts either server."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

LOCKS = dict(Op=336, Client=1984, ThreadCtx=1408, Shard=1440,
             FlatStore=944, AtomicEntry=144, Config=624)
LOCKS["Rob<64>"] = 192
TYPES = [*LOCKS, "ExLoopT<true>", "ExLoopT<false>"]


def inspect(binary):
    program = "import gdb,json\nout={}\n"
    program += 'for namespace in ("tomo", "tomo_db0"):\n'
    program += f" for name in {TYPES!r}:\n"
    program += "  ty=gdb.lookup_type(namespace+'::'+name)\n"
    program += "  out[namespace+'::'+name]={'size':ty.sizeof,'fields':{f.name:f.bitpos for f in ty.fields() if f.name and hasattr(f,'bitpos')}}\n"
    program += "print(json.dumps(out,sort_keys=True))\n"
    raw = subprocess.check_output(["gdb", "-nx", "-batch", str(binary),
                                   "-ex", "python exec(" + repr(program) + ")"], text=True)
    return json.loads(raw)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pre", type=Path, default=Path("build/perfex/pre/tomokv"))
    p.add_argument("--post", type=Path, default=Path("build/tomokv"))
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    before, after = inspect(args.pre), inspect(args.post)
    for name, old in before.items():
        new = after[name]
        assert old["size"] == new["size"], (name, "size")
        bare = name.split("::", 1)[1]
        if bare in LOCKS:
            assert new["size"] == LOCKS[bare], (name, "locked size")
        for field, offset in old["fields"].items():
            assert new["fields"][field] == offset, (name, field, "moved")
        added = set(new["fields"]) - set(old["fields"])
        assert added == ({"keyspace_shard_cursor_"} if bare.startswith("ExLoopT<") else set()), (name, added)
        if added:
            cursor = new["fields"]["keyspace_shard_cursor_"]
            assert cursor >= old["fields"]["snapshot_was_cancelled_"] + 8
            assert cursor + 32 <= old["fields"]["snapshot_prepare_cursor_"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = dict(pre=before, post=after, existing_sizes_and_offsets_equal=True,
                  cursor_occupies_existing_padding=True,
                  sha256={"PRE": hashlib.sha256(args.pre.read_bytes()).hexdigest(),
                          "POST": hashlib.sha256(args.post.read_bytes()).hexdigest()})
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("LAYOUT PASS: eight locked types and both ExLoop variants, both namespaces")


if __name__ == "__main__":
    main()
