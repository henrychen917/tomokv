#!/usr/bin/env python3
"""Freeze R1's decomposed build inputs; never boot a server or run a measurement.

The variants are source substitutions, not shipped feature switches. Refuse a
different production baseline or changed extraction anchors rather than silently
mixing an unrelated change into the experiment. Build each generated Makefile's
all target; manifest.json records the exact inputs, not a performance verdict.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

import reorder_scope as scope


ROOT = scope.ROOT
WRAPPER = "// A single connection has no legal promotion, regardless of command classes, hazards, gaps,"
END = "}  // namespace tomo\n"


def digest_tree(path):
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_file():
            digest.update(str(item.relative_to(path)).encode() + b"\0" + item.read_bytes())
    return digest.hexdigest()


def headers(pre, post):
    if post.count(WRAPPER) != 1 or not post.endswith(END):
        raise ValueError("R1 wrapper extraction anchor changed")
    body, wrapper = post.split(WRAPPER)
    wrapper = WRAPPER + wrapper
    signature = "ReorderResult ex_schedule_batch(Task (&tasks)[BatchOps], uint32_t n)"
    candidates = signature.replace("ex_schedule_batch", "ex_schedule_candidates")
    single = scope.replace_once(pre, signature, candidates)
    single = scope.replace_once(single, END, wrapper)
    metadata = scope.replace_once(body + END, candidates, signature)
    fifo = scope.replace_once(post, "    return ex_schedule_candidates(tasks, n);",
                              "    return {}; // Throwaway negative control: promotion removed.")
    return {"pre": pre, "single-client": single, "metadata-pass": metadata,
            "post": post, "fifo-mutant": fifo}


def prepare(path, revision):
    path = scope.destination_path(path)
    if path.exists():
        raise ValueError(f"destination already exists: {path}")
    revision = subprocess.check_output(
        ["git", "rev-parse", "--verify", revision + "^{commit}"], cwd=ROOT, text=True).strip()
    archive = subprocess.check_output(
        ["git", "archive", revision, "src", "third_party", "Makefile", "tests/reorder_unit.cc"],
        cwd=ROOT)
    path.mkdir(parents=True)
    pre = path / "pre"
    with tarfile.open(fileobj=io.BytesIO(archive)) as entries:
        entries.extractall(pre, filter="data")
    # Only reorder.h may differ in release build inputs. Test extensions are
    # independent of the executable; generation cannot smuggle in another lane.
    for name in ("src", "third_party"):
        old = {p.relative_to(pre) for p in (pre / name).rglob("*") if p.is_file()}
        new = {p.relative_to(ROOT) for p in (ROOT / name).rglob("*") if p.is_file()}
        if old != new:
            raise ValueError(f"baseline file inventory differs in {name}")
        for relative in sorted(old - {Path("src/core/reorder.h")}):
            if (pre / relative).read_bytes() != (ROOT / relative).read_bytes():
                raise ValueError(f"unrelated production change: {relative}")
    if (pre / "Makefile").read_bytes() != (ROOT / "Makefile").read_bytes():
        raise ValueError("baseline Makefile differs")
    variants = headers((pre / "src/core/reorder.h").read_text(),
                       (ROOT / "src/core/reorder.h").read_text())
    manifest = {"base": revision, "measured": False, "variants": {}}
    for name, header in variants.items():
        target = path / name
        if name != "pre":
            shutil.copytree(pre, target)
            (target / "src/core/reorder.h").write_text(header)
        # The unmaterialized-ROB tripwire specifically proves D1. PRE and D2
        # use the original policy oracle; POST/D1/mutant include that tripwire.
        if name in ("single-client", "post", "fifo-mutant"):
            shutil.copy2(ROOT / "tests/reorder_unit.cc", target / "tests/reorder_unit.cc")
        manifest["variants"][name] = {
            "directory": str(target), "source_sha256": digest_tree(target),
            "header_sha256": hashlib.sha256(header.encode()).hexdigest(),
            "scored": name != "fifo-mutant",
            "build": ["make", "-C", str(target), "all", "build/reorder-unit"],
        }
    # Both copies use the SAME observer, in both modes and on either reorder arm.
    manifest["scope"] = {
        "pre": scope.prepare(path / "scope-pre", revision),
        "post": scope.prepare(path / "scope-post"),
    }
    (path / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="commit supplying the unchanged R1 policy")
    parser.add_argument("--directory", type=Path, default=ROOT / "build/reorder-R1/artifacts")
    args = parser.parse_args()
    print(json.dumps(prepare(args.directory, args.base), indent=2))
