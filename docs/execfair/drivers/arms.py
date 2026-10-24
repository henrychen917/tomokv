#!/usr/bin/env python3
"""Build a kind-A PRE-behaviour padding arm.

Run after gate builds, on CPUs 64-79. Never starts a server or a measurement.
PAD matches cold object/allocation sizes and aggregate .text, not every address.
"""
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from lbstall_artifacts import Elf
OUT = ROOT / "docs/execfair/arms"
OUT.mkdir(exist_ok=True)
FLAGS = "-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread"


def change(path, before, after):
    text = path.read_text()
    assert text.count(before) == 1, (path, before)
    path.write_text(text.replace(before, after))


def run(command, log):
    with (OUT / log).open("w") as stream:
        subprocess.run(["taskset", "-c", "64-79", *command], cwd=ROOT,
                       stdout=stream, stderr=subprocess.STDOUT, check=True)


def text_size(path):
    elf = Elf(path)
    return elf.sections[elf.names.index(".text")][5]


def main():
    source = ROOT / "build/pad-source"
    assert not source.exists(), "do not silently overwrite an earlier PAD source"
    source.mkdir()
    for folder in ("src", "tests"):
        shutil.copytree(ROOT / "build/pre-source" / folder, source / folder)
    shutil.copy2(ROOT / "build/pre-source/Makefile", source / "Makefile")
    change(source / "src/core/ex_loop.h",
           "    [[no_unique_address]] ReadLocalExState<Fused> read_local_;",
           "    [[no_unique_address]] ReadLocalExState<Fused> read_local_;\n    uint32_t execfair_pad_count_ = 0;")
    change(source / "src/core/ex_loop.h", "sizeof(ExLoop) == 5848", "sizeof(ExLoop) == 5856")
    change(source / "src/core/ex_loop.h", "sizeof(FusedExLoop) == 5856", "sizeof(FusedExLoop) == 5864")
    # Nontrivial destructor preserves the same array cookie and 24-byte element
    # allocation as TxnPlaceBlocker, with no holder pointer or polling policy.
    change(source / "src/cmd/multi.h", "enum class TxnClaimMode",
           "struct ExecfairPadBlocker { void* unused[3]{}; ~ExecfairPadBlocker() {} };\n\nenum class TxnClaimMode")
    change(source / "src/cmd/multi.inc", "    std::shared_ptr<AofGroupDecision> aof_group;\n};",
           "    std::shared_ptr<AofGroupDecision> aof_group;\n    std::unique_ptr<ExecfairPadBlocker[]> execfair_pad_blockers;\n};")
    change(source / "src/cmd/multi.inc", "        state->watch_shard_done.assign(server.nshards(), 0);",
           "        state->watch_shard_done.assign(server.nshards(), 0);\n"
           "        if (kind == MultiStateKind::Execute)\n"
           "            state->execfair_pad_blockers = std::make_unique<ExecfairPadBlocker[]>(server.nshards());")
    change(source / "src/cmd/scatter_engine.inc", "    std::unique_ptr<ShardGroup[]> placement_groups;\n};",
           "    std::unique_ptr<ShardGroup[]> placement_groups;\n    std::unique_ptr<ExecfairPadBlocker[]> execfair_pad_blockers;\n};")
    change(source / "src/cmd/txn_group.inc", "        attempt->arrived.assign(server.nshards(), 0);",
           "        attempt->arrived.assign(server.nshards(), 0);\n"
           "        attempt->execfair_pad_blockers = std::make_unique<ExecfairPadBlocker[]>(server.nshards());")
    pad = ROOT / "build/pad-a"
    run(["make", "-C", str(source), "-j16", "BUILD_ROOT=" + str(pad), "all"], "pad-build.log")
    recipe = subprocess.check_output(["make", "-C", str(source), "BUILD_ROOT=" + str(pad),
                                     "-n", "-W", str(pad / "src/main.o"), "all"], text=True)
    link = shlex.split(next(line for line in recipe.splitlines() if " -o " + str(pad / "tomokv") + " " in line))
    post = ROOT / "build/tomokv"
    target = text_size(post)
    padding = target - text_size(pad / "tomokv")
    assert padding >= 0, (target, text_size(pad / "tomokv"))
    attempts = []
    link.insert(link.index("-o"), str(pad / "padding.o"))
    for number in range(4):
        (pad / "padding.S").write_text('.section .text,"ax",@progbits\n.fill ' + str(padding) +
                                       ',1,0x90\n.section .note.GNU-stack,"",@progbits\n')
        run(["gcc", "-c", str(pad / "padding.S"), "-o", str(pad / "padding.o")], "pad-assembly.log")
        run(link, f"pad-link-{number}.log")
        actual = text_size(pad / "tomokv")
        attempts.append(dict(padding=padding, text_size=actual))
        if actual == target:break
        padding += target - actual
        assert padding >= 0
    assert actual == target
    arms = {"PRE": ROOT / "build/pre/tomokv", "POST": post,
            "PAD-A": pad / "tomokv"}
    manifest = {"pad_kind": "A: PRE behaviour with candidate cold object/allocation and aggregate text sizes",
                "pad_limits": "Individual function addresses and other ELF sections are not matched.",
                "pad_attempts": attempts, "arms": {name: {"path": str(path.relative_to(ROOT)),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "text_bytes": text_size(path)}
                    for name, path in arms.items()}}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":main()
