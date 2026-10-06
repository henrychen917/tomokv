#!/usr/bin/env python3
"""Offline RESP lane byte/instruction evidence; never executes either server.

Use the existing ELF canonicalizer: executable bytes and resolved relocation
targets must both agree. TLS TPOFF32's width is the same four-byte extension used
by docs/gt13split/audit_bodies.py. No opcode, register or immediate is masked.
"""
import argparse
from collections import Counter
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

source = textwrap.dedent(inspect.getsource(audit.Elf.canonical))
assert source.count("24: 8,") == 1
scope = vars(audit).copy()
exec(source.replace("24: 8,", "23: 4, 24: 8,"), scope)
audit.Elf.canonical = scope["canonical"]
RESP = re.compile(r"resp_parse|parse_len_crlf|resp_length|resp_count|resp_bulk_prefix|"
                  r"resp_inline|resp_expected|reply_simple|reply_line_text|cmd_type\(")


def compare(pre, post, out):
    out.mkdir(parents=True, exist_ok=True)
    hot, changed, objects = [], [], []
    total = 0
    for before in sorted(pre.rglob("*.o")):
        relative = before.relative_to(pre)
        after = post / relative
        assert after.is_file(), after
        a, b = audit.Elf(before), audit.Elf(after)
        old, new = a.functions(), b.functions()
        names = sorted(old.keys() | new.keys())
        labels = subprocess.check_output(["c++filt"], input="\n".join(names) + "\n", text=True).splitlines()
        delta = 0
        for name, label in zip(names, labels):
            left, right = old.get(name), new.get(name)
            ca = a.canonical(left) if left else None
            cb = b.canonical(right) if right else None
            equal = bool(left and right) and ca == cb
            raw = bool(left and right) and a.body(left) == b.body(right)
            row = dict(object=str(relative), symbol=name, name=label,
                       pre_size=left["size"] if left else 0, post_size=right["size"] if right else 0,
                       raw_equal=raw, relocation_equal=equal)
            if audit.HOT.search(label) or RESP.search(label):
                hot.append(row)
            if not equal:
                def code_targets(canonical):
                    if canonical is None:
                        return Counter()
                    return Counter(str(target) for _, kind, target in canonical[1]
                                   if kind in (4, 'direct'))
                old_targets, new_targets = code_targets(ca), code_targets(cb)
                row['code_targets_removed'] = list((old_targets - new_targets).elements())
                row['code_targets_added'] = list((new_targets - old_targets).elements())
                changed.append(row)
                delta += 1
            total += 1
        objects.append(dict(object=str(relative), functions=len(names), changed=delta))
    assert hot and objects, "empty object/body inventory"
    for filename, data in (("hot-bodies.json", hot), ("changed-bodies.json", changed), ("objects.json", objects)):
        (out / filename).write_text(json.dumps(data, indent=2) + "\n")
    summary = dict(objects=len(objects), functions=total, changed=len(changed), hot=len(hot),
                   hot_equal=sum(row["relocation_equal"] for row in hot),
                   hot_raw_equal=sum(row["raw_equal"] for row in hot),
                   changed_objects={row["object"]: row["changed"] for row in objects if row["changed"]})
    for arm, binary in (("PRE", pre / "tomokv"), ("POST", post / "tomokv")):
        if binary.exists():
            elf = audit.Elf(binary)
            summary[arm] = dict(sha256=hashlib.sha256(elf.data).hexdigest(),
                                text_bytes=len(elf.section_data(elf.names.index(".text"))))
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pre", type=Path)
    parser.add_argument("post", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    compare(args.pre, args.post, args.out)


if __name__ == "__main__":
    main()
