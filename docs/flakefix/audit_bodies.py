#!/usr/bin/env python3
"""Serverless whole-object/function audit; only the DEBUG handler may change."""
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import lbstall_artifacts as audit

# The existing full-body audit's TLS relocation extension. No opcode is masked.
source = textwrap.dedent(inspect.getsource(audit.Elf.canonical))
assert source.count("24: 8,") == 1
scope = vars(audit).copy()
exec(source.replace("24: 8,", "23: 4, 24: 8,"), scope)
audit.Elf.canonical = scope["canonical"]

pre = ROOT / "build/flakefix/PRE"
post = ROOT / "build/flakefix/POST"
objects, changed, unexpected = [], [], []
for path in sorted(pre.rglob("*.o")):
    rel = path.relative_to(pre)
    other = post / rel
    before = audit.Elf(path)
    old = before.functions()
    raw_file_equal = path.read_bytes() == other.read_bytes()
    row = dict(object=str(rel), file_equal=raw_file_equal, functions=len(old),
               pre_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
               post_sha256=hashlib.sha256(other.read_bytes()).hexdigest(),
               raw_body_equal=len(old), bytes_and_targets_equal=len(old))
    objects.append(row)
    if raw_file_equal:
        continue
    after = audit.Elf(other)
    new = after.functions()
    names = sorted(old.keys() | new.keys())
    labels = subprocess.check_output(["c++filt"], input="\n".join(names) + "\n", text=True).splitlines()
    row.update(functions=len(names), raw_body_equal=0, bytes_and_targets_equal=0)
    for name, label in zip(names, labels):
        left, right = old.get(name), new.get(name)
        raw = bool(left and right and before.body(left) == after.body(right))
        same = bool(left and right and before.canonical(left) == after.canonical(right))
        row["raw_body_equal"] += int(raw)
        row["bytes_and_targets_equal"] += int(same)
        if not raw or not same:
            item = dict(object=str(rel), name=label, symbol=name, raw_equal=raw,
                        bytes_and_targets_equal=same,
                        pre_size=left["size"] if left else 0, post_size=right["size"] if right else 0)
            changed.append(item)
            if not same and not any(token in label for token in (
                    "(anonymous namespace)::cmd_debug_impl(",
                    "(anonymous namespace)::debug_aof_frame_state(")):
                unexpected.append(item)

summary = dict(objects=objects, changed=changed, unexpected=unexpected,
               function_bodies=sum(row["functions"] for row in objects),
               raw_body_equal=sum(row["raw_body_equal"] for row in objects),
               bytes_and_targets_equal=sum(row["bytes_and_targets_equal"] for row in objects))
(ROOT / "docs/flakefix/body-audit.json").write_text(json.dumps(summary, indent=2) + "\n")
print("Objects:", len(objects), "identical:", sum(row["file_equal"] for row in objects))
print("Bodies:", summary["function_bodies"], "raw equal:", summary["raw_body_equal"],
      "bytes and resolved targets equal:", summary["bytes_and_targets_equal"])
for row in changed:
    print(json.dumps(row))
assert not unexpected, "ordinary production bodies changed"
