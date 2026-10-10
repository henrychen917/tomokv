#!/usr/bin/env python3
"""Verify the lane's source boundary without running a server."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def original(commit, name):
    return subprocess.check_output(["git", "show", f"{commit}:{name}"], cwd=ROOT)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pre", default="5146b78ee")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    changed = subprocess.check_output(["git", "diff", "--name-only", args.pre, "--", "src"],
                                      cwd=ROOT, text=True).splitlines()
    assert set(changed) == {"src/core/ex_loop.h", "src/cmd/storesize.cc"}, changed
    untouched = {}
    for name in ("src/core/thread.h", "src/core/signal.h", "src/cmd/scatter_engine.inc"):
        before, after = original(args.pre, name), (ROOT / name).read_bytes()
        assert before == after, name
        untouched[name] = hashlib.sha256(after).hexdigest()
    before = original(args.pre, "src/core/ex_loop.h").decode().splitlines(keepends=True)
    after = (ROOT / "src/core/ex_loop.h").read_text()
    protected = {}
    for label, first, last in (("capture/shutdown admission", 1864, 2110),
                               ("AOF init hook", 172, 172),
                               ("AOF owner hooks", 1688, 1705),
                               ("AOF execute hooks", 2367, 2379)):
        fragment = "".join(before[first - 1:last])
        assert fragment in after, (label, "protected source changed")
        protected[label] = dict(pre_lines=[first, last], unchanged=True)
    before_gate = original(args.pre, "tests/gate.sh").decode()
    after_gate = (ROOT / "tests/gate.sh").read_text()
    counts = {}
    for name in ("EXPECT_QUICK", "EXPECT_FULL"):
        old = re.search(rf"^{name}=(\d+)", before_gate, re.M)[1]
        new = re.search(rf"^{name}=(\d+)", after_gate, re.M)[1]
        assert old == new, name
        counts[name] = dict(unchanged=int(new), delta=4, required=int(new) + 4)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(changed_production_sources=changed,
        untouched_sha256=untouched, protected_regions=protected, owner_counts=counts), indent=2) + "\n")
    print("SOURCE PASS: only owned production sources changed; shared regions/count constants intact")


if __name__ == "__main__":
    main()
