#!/usr/bin/env python3
"""Build serverless CD witnesses or audit all production function bodies. Never boots a server.

Run under taskset -c 112-127. PRE/POST are build roots made with the normal Makefile.
The test-only coordinate oracle compiles the pinned Redis checkout without modifying it.
"""
import argparse
import hashlib
import inspect
import json
from pathlib import Path
import re
import subprocess
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lbstall_artifacts as audit


def run(argv):
    subprocess.run([str(arg) for arg in argv], cwd=ROOT, check=True)


def build(args):
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    oracle = args.oracle.resolve()
    for source in ("util", "geohash"):
        run(["cc", "-O2", "-ffunction-sections", "-fdata-sections",
             "-I" + str(oracle / "src"), "-I" + str(oracle / "deps/fpconv"),
             "-c", oracle / ("src/%s.c" % source), "-o", out / ("redis-%s.o" % source)])
    run(["cc", "-O2", "-I" + str(oracle / "src"), "-c", "tests/cdfix_oracle.c",
         "-o", out / "oracle.o"])
    flags = ["g++", "-std=c++20", "-O2", "-g", "-Wall", "-Wextra", "-march=native",
             "-pthread", "-DTOMO_JEMALLOC", "-I.", "-I" + str(oracle / "src")]
    # The same compiled test object links to PRE and POST. No inline copies of the fixed code.
    for namespace in ("multi", "db0"):
        variant = [] if namespace == "multi" else ["-DTOMO_SINGLE_DATABASE=1", "-Dtomo=tomo_db0"]
        unit = out / (namespace + ".o")
        run(flags + variant + ["-c", "tests/cdfix_unit.cc", "-o", unit])
        for arm, root in (("PRE", args.pre), ("POST", args.post)):
            objects = sorted(p for p in (root / "src").rglob("*.o") if p.name not in ("main.o", "version.o"))
            if namespace == "db0":
                objects = sorted(p for p in (root / "db0/src").rglob("*.o") if p.name not in ("main.o", "version.o")) + objects
            run(flags + [unit, out / "oracle.o", out / "redis-geohash.o", out / "redis-util.o"] + objects +
                ["-Wl,--gc-sections", "-ljemalloc", "-luring", "-lssl", "-lcrypto", "-lm",
                 "-o", out / (arm + "-" + namespace)])
    # Deliberately broken, test-only cursor: reverse physical slots instead of logical homes.
    # The growth/wraparound property must reject this even though it terminates.
    source = (ROOT / "src/cmd/t_set.cc").read_text()
    correct = "slot.state == Live && (static_cast<uint32_t>(mix64(slot.hash)) & mask) == home"
    assert source.count(correct) == 1
    broken = out / "physical-slot.cc"
    broken.write_text(source.replace(correct, "slot.state == Live && pos == home"))
    run(flags + ["-Isrc/cmd", "-c", broken, "-o", out / "physical-slot.o"])
    objects = sorted(p for p in (args.post / "src").rglob("*.o") if p.name not in ("main.o", "version.o", "t_set.o"))
    run(flags + [out / "multi.o", out / "physical-slot.o", out / "oracle.o",
                 out / "redis-geohash.o", out / "redis-util.o"] + objects +
        ["-Wl,--gc-sections", "-ljemalloc", "-luring", "-lssl", "-lcrypto", "-lm",
         "-o", out / "PHYSICAL-multi"])
    print("Built PRE/POST serverless witnesses in both database namespaces")


def compare(args):
    # Match the existing full-body audit's TLS relocation-width extension. Only addresses are
    # canonicalized; every opcode/register/immediate/branch and resolved target remains checked.
    source = textwrap.dedent(inspect.getsource(audit.Elf.canonical))
    assert source.count("24: 8,") == 1
    scope = vars(audit).copy()
    exec(source.replace("24: 8,", "23: 4, 24: 8,"), scope)
    canonical = scope["canonical"]

    def with_local_code_addresses(elf, symbol):
        body, targets = canonical(elf, symbol)
        body = bytearray(body)
        if not hasattr(elf, "local_code_addresses"):
            elf.local_code_addresses = {}
            section = None
            sections = {name: i for i, name in enumerate(elf.names)}
            disassembly = subprocess.check_output(["objdump", "-dw", str(elf.path)], text=True)
            for line in disassembly.splitlines():
                if line.startswith("Disassembly of section "):
                    section = sections[line[len("Disassembly of section "):-1]]
                    continue
                match = re.match(r"\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*lea\s+.*\(%rip\),.*#\s*([0-9a-f]+)\s+<", line)
                if not match:
                    continue
                raw = bytes.fromhex(match[2])
                at, destination = int(match[1], 16), int(match[3], 16)
                # GAS resolves LEA of local function pointers (notify wrappers/snapshot hooks)
                # without an ELF relocation. Recognize only this exact seven-byte instruction.
                if len(raw) != 7 or raw[0] not in (0x48, 0x4c) or raw[1] != 0x8d:
                    continue
                if any(rel[0] == at + 3 for rel in elf.relocs.get(section, [])):
                    continue
                assert destination == at + 7 + int.from_bytes(raw[3:], "little", signed=True)
                target = dict(sec=section, info=3, value=0, name="")
                resolved = elf.target(target, destination, 0)
                if resolved[0] in elf.functions():
                    elf.local_code_addresses.setdefault(section, []).append((at, destination, resolved))
        for at, destination, resolved in elf.local_code_addresses.get(symbol["sec"], []):
            offset = at - symbol["value"]
            if not 0 <= offset < len(body) or symbol["value"] <= destination < symbol["value"] + symbol["size"]:
                continue
            body[offset + 3:offset + 7] = bytes(4)
            targets.append((offset + 3, "local-code-address", resolved))
        return bytes(body), sorted(targets, key=lambda row: row[0])

    audit.Elf.canonical = with_local_code_addresses
    witness = audit.Elf(args.pre / "src/cmd/t_set.o")
    name = next(name for name in witness.functions() if "SetMemberTable6insert" in name)
    symbol = witness.functions()[name]
    original = witness.canonical(symbol)
    offset = witness.sections[symbol["sec"]][4] + symbol["value"]
    saved_data = witness.data
    mutated = bytearray(saved_data)
    mutated[offset] ^= 1
    witness.data = bytes(mutated)
    assert witness.canonical(symbol) != original, "audit accepted a changed opcode"
    witness.data = saved_data
    relocations = witness.relocs[symbol["sec"]]
    index = next(i for i, rel in enumerate(relocations)
                 if symbol["value"] <= rel[0] < symbol["value"] + symbol["size"])
    saved_relocation = relocations[index]
    at, kind, target, addend = saved_relocation
    relocations[index] = (at, kind, dict(target, sec=0, name="CDFIX_WRONG_TARGET"), addend)
    assert witness.canonical(symbol) != original, "audit accepted a changed resolved target"
    relocations[index] = saved_relocation
    print("Audit negative controls: opcode and resolved-target changes rejected")
    rows, objects = [], []
    for path in sorted(args.pre.rglob("*.o")):
        rel = path.relative_to(args.pre)
        if not (str(rel).startswith("src/") or str(rel).startswith("db0/src/")):
            continue
        if args.objects and path.name not in args.objects:
            continue
        a, b = audit.Elf(path), audit.Elf(args.post / rel)
        old, new = a.functions(), b.functions()
        names = sorted(old.keys() | new.keys())
        labels = subprocess.check_output(["c++filt"], input="\n".join(names) + "\n", text=True).splitlines()
        start = len(rows)
        for name, label in zip(names, labels):
            left, right = old.get(name), new.get(name)
            raw = bool(left and right and a.body(left) == b.body(right))
            same = bool(left and right and a.canonical(left) == b.canonical(right))
            rows.append(dict(object=str(rel), symbol=name, name=label,
                             pre_size=left["size"] if left else 0,
                             post_size=right["size"] if right else 0,
                             raw_equal=raw, bytes_and_targets_equal=same))
        subset = rows[start:]
        objects.append(dict(object=str(rel), functions=len(subset),
                            raw_equal=sum(row["raw_equal"] for row in subset),
                            bytes_and_targets_equal=sum(row["bytes_and_targets_equal"] for row in subset)))
    changed = [row for row in rows if not row["bytes_and_targets_equal"]]
    protected = [row for row in rows if any(name in row["name"] for name in
                 ("cmd_get<", "cmd_set<", "cmd_mget<", "cmd_mset<", "cmd_hset<", "cmd_sadd<",
                  "cmd_sismember<", "cmd_smembers<", "SetMemberTable::insert(",
                  "SetMemberTable::ensure_insert_capacity(", "SetMemberTable::rehash("))]
    allowed = {
        "geo.o": ("parse_search(", "reply_coordinate(", "cmd_geoadd<", "cmd_geo_xshard_local("),
        "t_set.o": ("cmd_sscan<", "SetMemberTable::scan("),
        "t_zset.o": ("zset_owner_replace(",),
    }
    def new_geo_lookup(row):
        return (Path(row["object"]).name == "geo.o" and row["pre_size"] == 0 and
                "::FlatStore::find_resident(" in row["name"])

    unexpected = [row for row in changed if not new_geo_lookup(row) and not any(
        token in row["name"] for token in allowed.get(Path(row["object"]).name, ()))]
    # A changed weak COMDAT copy is not executable if the linker discarded it in both arms.
    # Require affirmative map + ELF evidence, and the selected copy's own full byte proof.
    discarded = []
    if not args.objects and all((root / "tomokv.map").exists() for root in (args.pre, args.post)):
        maps = []
        binaries = []
        for root in (args.pre, args.post):
            records = {}
            pattern = r"^ \.text\.(\S+)\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+(\S+\.o)$"
            for symbol, address, size, path in re.findall(
                    pattern, (root / "tomokv.map").read_text(), re.M):
                if path.startswith(str(root) + "/"):
                    records.setdefault(symbol, []).append(
                        (int(address, 16), int(size, 16), str(Path(path).relative_to(root))))
            maps.append(records)
            binaries.append(audit.Elf(root / "tomokv").functions())
        indexed = {(row["object"], row["symbol"]): row for row in rows}
        for row in unexpected:
            origins = []
            for arm, (records, symbols) in enumerate(zip(maps, binaries)):
                candidates = records.get(row["symbol"], [])
                copy_size = row["pre_size"] if arm == 0 else row["post_size"]
                if copy_size and not any(at == 0 and path == row["object"]
                                         for at, size, path in candidates):
                    break
                if not copy_size and any(path == row["object"] for at, size, path in candidates):
                    break
                selected = [(at, size, path) for at, size, path in candidates if at]
                if len(selected) != 1 or row["symbol"] not in symbols:
                    break
                at, size, path = selected[0]
                symbol = symbols[row["symbol"]]
                if (symbol["value"], symbol["size"]) != (at, size):
                    break
                origins.append(path)
            if len(origins) == 2 and origins[0] == origins[1]:
                selected = indexed.get((origins[0], row["symbol"]))
                if selected and selected["bytes_and_targets_equal"]:
                    row["retained_equal_copy"] = origins[0]
                    discarded.append(row)
        unexpected = [row for row in unexpected if row not in discarded]
    result = dict(pre=str(args.pre), post=str(args.post), functions=len(rows),
                  negative_controls=["opcode rejected", "resolved target rejected"],
                  raw_equal=sum(row["raw_equal"] for row in rows),
                  bytes_and_targets_equal=sum(row["bytes_and_targets_equal"] for row in rows),
                  objects=objects, changed=changed, discarded=discarded,
                  unexpected=unexpected, protected=protected,
                  sha256={arm: hashlib.sha256((root / "tomokv").read_bytes()).hexdigest()
                          for arm, root in (("PRE", args.pre), ("POST", args.post))})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("Functions: %d; raw bytes equal: %d; bytes + resolved targets equal: %d" %
          (len(rows), result["raw_equal"], result["bytes_and_targets_equal"]))
    for row in changed:
        print("CHANGED", row["object"], row["pre_size"], row["post_size"], row["name"])
    print("Protected bodies: %d; equal: %d; unexpected changes: %d" %
          (len(protected), sum(row["bytes_and_targets_equal"] for row in protected), len(unexpected)))
    for row in discarded:
        print("DISCARDED", row["object"], row["name"], "retained equal copy:", row["retained_equal_copy"])
    assert protected and all(row["bytes_and_targets_equal"] for row in protected), "ordinary command changed"
    assert not unexpected, "unexpected changed body; see audit output"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "audit"))
    parser.add_argument("--pre", type=Path, default=Path("build/cdfix/PRE"))
    parser.add_argument("--post", type=Path, default=Path("build/cdfix/POST"))
    parser.add_argument("--oracle", type=Path, default=Path("/tmp/claude-1000/redis74"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--objects", nargs="*", help="optional object filenames for codegen diagnosis")
    args = parser.parse_args()
    (build if args.action == "build" else compare)(args)
