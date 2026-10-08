#!/usr/bin/env python3
"""Offline type-A twin: PRE key policy on POST's exact text size/layout.

Returns zero at the cold configured-level boundary in each namespace. No ELF is
executed. Function/section tables and every other byte must remain identical.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

from lbstall_artifacts import Elf
from lbplanner_pad import body, normalized
from rlfence_artifacts import tables, moved_symbol

ROOT = Path(__file__).resolve().parents[1]
BASE = "db86e5b4a051929c68108d33b1dc358428c59bca"

def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def source_proof():
    def old(path):
        return subprocess.check_output(["git", "show", BASE + ":" + path], cwd=ROOT, text=True)
    planner = (ROOT / "src/core/lbplanner.cc").read_text()
    candidate = body(planner, "lb_controller_tick")
    level = "    const int32_t damping = lbosc3_level(cfg_.key_lb_damping);\n"
    assert candidate.count(level) == 1
    candidate = candidate.replace(level, "")
    begin = candidate.index("            // LBOSC3 BEGIN admission:")
    end = candidate.index("            if (key_admitted) {", begin) + len("            if (key_admitted) {")
    candidate = candidate[:begin] + """            if (update_streak(std::max(weight_ratio, byte_ratio), lb_policy_->key_jitter,
                              lb_bucket_hot_streak_, executors.size())) {""" + candidate[end:]
    band = """                const double band = damping && lb_policy_->key_damping
                    ? lb_policy_->key_damping->fire_band.load(std::memory_order_relaxed)
                    : lb_policy_->key_jitter.band(executors.size());"""
    assert candidate.count(band) == 1
    candidate = candidate.replace(band, "                const double band = lb_policy_->key_jitter.band(executors.size());")
    found = """                        const bool found = damping
                            ? lbosc3_best_incremental_move(shard_items, executors,
                                  demand_hot, memory_hot, choice, band)
                            : weighted_lb_best_incremental_move(shard_items, executors,
                                  demand_hot, memory_hot, choice);
                        if (!found) {"""
    assert candidate.count(found) == 1
    candidate = candidate.replace(found, """                        if (!weighted_lb_best_incremental_move(
                                shard_items, executors, demand_hot, memory_hot, choice)) {""")
    original = body(old("src/core/lbplanner.cc"), "lb_controller_tick")
    assert normalized(candidate) == normalized(original), "zero policy does not restore PRE controller"
    weighted = (ROOT / "src/core/weighted_lb.h").read_text()
    assert normalized(body(weighted, "weighted_lb_best_incremental_move")) == normalized(
        body(old("src/core/weighted_lb.h"), "weighted_lb_best_incremental_move")), "PRE search changed"
    for name in ("lb_consume_plan", "monitor_controllers", "lb_controller_tick_pad"):
        assert normalized(body(planner, name)) == normalized(body(old("src/core/lbplanner.cc"), name)), name
    assert normalized(body(planner, "lbosc3_level")) == "{ return configured; }"
    return {"base": BASE, "zero_policy_equals_pre": True,
            "pre_planner_sha256": hashlib.sha256(normalized(original).encode()).hexdigest()}


def plan(source):
    elf = Elf(source)
    assert elf.kind != 1, "PAD requires a linked executable"
    functions = [s for s in elf.functions().values()
                 if s["name"].startswith("_ZN") and "12lbosc3_level" in s["name"]]
    assert len(functions) in (1, 2), "PAD missing or cloned policy boundary"
    if source.name == "tomokv" or source.name.startswith("tomokv-"):
        assert len(functions) == 2, "PAD must cover both production namespaces"
    patches = []
    for symbol in functions:
        assert symbol["name"].startswith(("_ZN4tomo12lbosc3_level", "_ZN8tomo_db012lbosc3_level")), "PAD unknown namespace"
        raw = elf.body(symbol)
        skip = 4 if raw.startswith(b"\xf3\x0f\x1e\xfa") else 0
        replacement = bytes.fromhex("31 c0 c3")  # xor eax,eax; ret (policy zero)
        assert len(raw) >= skip + len(replacement), "PAD policy bypass too short"
        section = elf.sections[symbol["sec"]]
        offset = section[4] + symbol["value"] - section[3] + skip
        patches.append({"symbol": symbol["name"], "address": symbol["value"] + skip,
                        "offset": offset, "before": raw[skip:skip + len(replacement)].hex(),
                        "after": replacement.hex()})
    return {"kind": "A: PRE placement behaviour with POST text size/layout",
            "source_sha256": hashlib.sha256(elf.data).hexdigest(),
            "source_proof": source_proof(), "patches": sorted(patches, key=lambda p: p["address"])}


def verify(source, output, expected, independent=True):
    if independent:
        assert expected == plan(source), "PAD inventory changed"
    before, after = Elf(source), Elf(output)
    assert before.sections == after.sections, "PAD section table moved"
    assert before.symbols == after.symbols, "PAD symbol table moved"
    restored = bytearray(after.data)
    for patch in expected["patches"]:
        at = patch["offset"]
        old, new = bytes.fromhex(patch["before"]), bytes.fromhex(patch["after"])
        assert restored[at:at + len(new)] == new, "PAD policy bypass missing"
        restored[at:at + len(old)] = old
    assert bytes(restored) == before.data, "PAD unplanned byte change"


def make_pad(source, output, receipt):
    assert source.resolve() != output.resolve(), "PAD must be a separate copy"
    receipt.mkdir(parents=True, exist_ok=True)
    expected = plan(source)
    save(receipt / "planned-patches.json", expected)
    before = Elf(source)
    changed = bytearray(before.data)
    for patch in expected["patches"]:
        at = patch["offset"]
        new = bytes.fromhex(patch["after"])
        changed[at:at + len(new)] = new
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(changed)
    output.chmod(0o755)
    verify(source, output, expected)
    a, b = tables(before, receipt, "POST"), tables(Elf(output), receipt, "PAD-A")
    assert a["function_table_sha256"] == b["function_table_sha256"]
    assert a["section_table_sha256"] == b["section_table_sha256"]
    controls = []
    for patch in expected["patches"]:
        broken = bytearray(changed)
        at, old = patch["offset"], bytes.fromhex(patch["before"])
        broken[at:at + len(old)] = old
        controls.append(("missing-" + patch["symbol"], broken, "PAD policy bypass missing"))
    controls.append(("moved-symbol", moved_symbol(changed, before, expected["patches"][0]["symbol"]),
                     "PAD symbol table moved"))
    broken = bytearray(changed)
    broken[before.sections[before.names.index(".text")][4]] ^= 1
    controls.append(("unrelated-byte", broken, "PAD unplanned byte change"))
    outcomes = {}
    broken_path = output.with_name(output.name + ".NEVER-RUN")
    try:
        for name, broken, message in controls:
            broken_path.write_bytes(broken)
            broken_path.chmod(0o600)
            try:
                verify(source, broken_path, expected, independent=False)
            except AssertionError as error:
                assert str(error) == message, (name, str(error))
                outcomes[name] = {"rejected": True, "assertion": message}
            else:
                raise AssertionError(("PAD accepted negative", name))
    finally:
        broken_path.unlink(missing_ok=True)
    save(receipt / "proof.json", {"kind": expected["kind"], "post": a, "pad": b,
         "exact_function_and_section_tables": True, "all_other_bytes_identical": True,
         "changed_bytes": sum(x != y for x, y in zip(before.data, changed)), "controls": outcomes})
    for path in receipt.glob("*.tsv"):
        with gzip.GzipFile(filename=str(path) + ".gz", mode="wb", mtime=0) as stream:
            stream.write(path.read_bytes())
        path.unlink()
    print("PASS LBOSC3 PAD-A: exact function/section tables, PRE source closure,",
          len(expected["patches"]), "policy bypasses,", len(outcomes), "negative controls")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    make_pad(args.source, args.output, args.receipt)
