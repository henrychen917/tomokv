#!/usr/bin/env python3
"""CD13b full-body byte audit. Only verified address fields are normalized."""
import argparse
import hashlib
import inspect
import json
from pathlib import Path
import re
import subprocess
import sys
import textwrap
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import lbstall_artifacts as audit

def install_normalizer():
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


def annotate(result, args):
    """Count decoded instructions and retain exact raw-byte hashes for every changed body."""
    cache = {}
    def emitted(root, relative, name):
        path = root / relative
        if not path.exists():
            return 0, None
        if path not in cache:
            elf = audit.Elf(path)
            decoded, section = {}, None
            for line in subprocess.check_output(["objdump", "-dw", str(path)], text=True).splitlines():
                if line.startswith("Disassembly of section "):
                    section = line[len("Disassembly of section "):-1]
                match = re.match(r"\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*", line)
                if match:
                    decoded.setdefault(section, []).append((int(match[1], 16), bytes.fromhex(match[2])))
            cache[path] = elf, decoded
        elf, decoded = cache[path]
        symbol = elf.functions().get(name)
        if not symbol:
            return 0, None
        instructions = [raw for at, raw in decoded[elf.names[symbol["sec"]]]
                        if symbol["value"] <= at < symbol["value"] + symbol["size"]]
        raw = elf.body(symbol)
        assert b"".join(instructions) == raw, (path, name, "instruction coverage")
        return len(instructions), hashlib.sha256(raw).hexdigest()

    for row in result["changed"]:
        for arm, root in (("pre", args.pre), ("post", args.post)):
            row[arm + "_instructions"], row[arm + "_raw_sha256"] = emitted(root, row["object"], row["symbol"])
        name = row["name"]
        if "retained_equal_copy" in row:
            reason = "Discarded COMDAT; selected byte-identical copy: " + row["retained_equal_copy"]
        elif "_GLOBAL__sub_I__" in name:
            reason = "New cold translation unit's guarded header-static initialization"
        elif "geo_store_preserve_metadata(" in name:
            reason = "New owner-side resident/expiry lookup and cdfix metadata-copy adapter"
        elif "apply_image<" in name or "execute_atomic_apply(" in name:
            reason = "Owner-side policy check and metadata copy immediately before installation"
        elif "finish_phase1(" in name:
            reason = "Mark the fresh GEO STORE image for owner-side metadata preservation"
        elif any(token in name for token in ("ObjectImage", "compute_pfmerge(", "script_clear_attempt(",
                                            "publish_pop_retry<", "xshard_prepare(", "prepare_commands(")):
            reason = "Initialize/copy the image policy flag in former padding; existing field offsets unchanged"
        elif any(token in name for token in ("normalize_multi_blocking_pop(", "classify_keys(")):
            reason = "Unchanged cold scatter parser: GCC inlining changed after the added install calls"
        elif any(token in name for token in ("server_tail_command_subcommand(", "basic_string<std::allocator<char> >")):
            reason = "Unknown ACL category no longer constructs an error; zero mask filters all names"
        elif any(token in name for token in ("reply_help(", "reply_map_pair_int(", "server_tail_config_subcommand(")):
            reason = "Unchanged cold administrative formatter: GCC inlining changed after error removal"
        else:
            raise AssertionError((name, "missing reviewed reason"))
        row["reason"] = reason
    result["text_bytes"] = {}
    for arm, root in (("PRE", args.pre), ("POST", args.post)):
        elf = audit.Elf(root / "tomokv")
        result["text_bytes"][arm] = elf.sections[elf.names.index(".text")][5]


def compare(args):
    install_normalizer()
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
    relocations[index] = (at, kind, dict(target, sec=0, name="CD13B_WRONG_TARGET"), addend)
    assert witness.canonical(symbol) != original, "audit accepted a changed resolved target"
    relocations[index] = saved_relocation
    print("Audit negative controls: opcode and resolved-target changes rejected")
    rows, objects = [], []
    for rel in sorted({p.relative_to(root) for root in (args.pre, args.post) for p in root.rglob("*.o")}):
        path = args.pre / rel
        if not (str(rel).startswith("src/") or str(rel).startswith("db0/src/")):
            continue
        if args.objects and path.name not in args.objects:
            continue
        a = audit.Elf(path) if path.exists() else None
        b = audit.Elf(args.post / rel) if (args.post / rel).exists() else None
        old, new = a.functions() if a else {}, b.functions() if b else {}
        names = sorted(old.keys() | new.keys())
        labels = subprocess.check_output(["c++filt"], input="\n".join(names) + "\n", text=True).splitlines()
        start = len(rows)
        for name, label in zip(names, labels):
            left, right = old.get(name), new.get(name)
            raw = bool(left and right and a.body(left) == b.body(right))
            ca = a.canonical(left) if left else None
            cb = b.canonical(right) if right else None
            same = bool(left and right and ca == cb)
            rows.append(dict(object=str(rel), symbol=name, name=label,
                             pre_size=left["size"] if left else 0,
                             post_size=right["size"] if right else 0,
                             pre_section=a.names[left["sec"]] if left else None,
                             post_section=b.names[right["sec"]] if right else None,
                             pre_canonical_sha256=hashlib.sha256(repr(ca).encode()).hexdigest() if ca else None,
                             post_canonical_sha256=hashlib.sha256(repr(cb).encode()).hexdigest() if cb else None,
                             raw_equal=raw, bytes_and_targets_equal=same))
        subset = rows[start:]
        objects.append(dict(object=str(rel), functions=len(subset),
                            raw_equal=sum(row["raw_equal"] for row in subset),
                            bytes_and_targets_equal=sum(row["bytes_and_targets_equal"] for row in subset)))
    changed = [row for row in rows if not row["bytes_and_targets_equal"]]
    protected = [row for row in rows if re.search(r"\d+cmd_", row["symbol"]) or any(
        word in row["name"] for word in ("notify_flat_emit(", "bitfield_generic(", "xshard_plain_prepare("))]
    hot = [row for row in rows if audit.HOT.search(row["name"])]
    allowed = {
        "server_tail.o": ("reply_help(", "reply_map_pair_int(", "server_tail_config_subcommand(",
                          "server_tail_command_subcommand(", "basic_string<std::allocator<char> >"),
        "xshard.o": ("ObjectImage", "apply_image<", "finish_phase1(", "compute_pfmerge(",
                     "execute_atomic_apply(", "script_clear_attempt(", "publish_pop_retry<",
                     "xshard_prepare(", "normalize_multi_blocking_pop(", "classify_keys("),
        "geo_store.o": ("geo_store_preserve_metadata(", "_GLOBAL__sub_I__"),
    }
    unexpected = [row for row in changed if not any(
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
                if Path(path).resolve().is_relative_to(root.resolve()):
                    records.setdefault(symbol, []).append(
                        (int(address, 16), int(size, 16), str(Path(path).resolve().relative_to(root.resolve()))))
            maps.append(records)
            binaries.append(audit.Elf(root / "tomokv").functions())
        indexed = {(row["object"], row["symbol"]): row for row in rows}
        for row in changed:
            origins = []
            for arm, (records, symbols) in enumerate(zip(maps, binaries)):
                section = row["pre_section"] if arm == 0 else row["post_section"]
                # C++ destructor aliases D1/D2 share the COMDAT section named for D2.
                # Use the actual input section, then verify the alias's linked address/size.
                section = section or row["post_section"] or row["pre_section"]
                key = section[len(".text."):] if section.startswith(".text.") else row["symbol"]
                candidates = records.get(key, [])
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
                  objects=objects, changed=changed, discarded=discarded, hot=hot,
                  unexpected=unexpected, protected=protected,
                  hot_unexpected=[row for row in hot if not row["bytes_and_targets_equal"] and row not in discarded],
                  sha256={arm: hashlib.sha256((root / "tomokv").read_bytes()).hexdigest()
                          for arm, root in (("PRE", args.pre), ("POST", args.post))})
    if not args.objects:
        annotate(result, args)
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
    assert not result["hot_unexpected"], "hot body changed"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre", type=Path, default=Path("build/cd13b/PRE"))
    parser.add_argument("--post", type=Path, default=Path("build/cd13b/POST"))
    parser.add_argument("--output", type=Path, default=Path("docs/cd13b/audit.json"))
    parser.add_argument("--objects", nargs="*")
    compare(parser.parse_args())
