#!/usr/bin/env python3
"""Run ntfix3 correctness only, on the lane's reserved CPUs and ports."""
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/ntfix/ntfix3"
PRE = Path("/home/user/Projects/bins/ntfix-pre-5c8ca908")


def main():
    assert hashlib.sha256(PRE.read_bytes()).hexdigest() == (
        "5c8ca908bc4babe1a2ef6dcae4d3d3a60900aa8de6ecc78019a02c8c7c30b8c5")
    post = ROOT / "build/tomokv"
    digest = hashlib.sha256(post.read_bytes()).hexdigest()
    driver = ["python3", "tools/ntfix_proof.py"]
    jobs = [
        ("pre/rows", "89-95", [*driver, "--binary", str(PRE), "--out",
                               str(OUT / "pre/rows"), "--rows-only"]),
        ("post/rows", "89-95", [*driver, "--binary", str(post), "--out",
                                str(OUT / "post/rows"), "--rows-only", "--expect-equal"]),
        ("post/limits", "89-95", [*driver, "--binary", str(post), "--out",
                                  str(OUT / "post/limits"), "--expect-equal"]),
        ("post/fragments", "89-95", [*driver, "--binary", str(post), "--out",
                                     str(OUT / "post/fragments"), "--fragments", "--expect-equal"]),
        ("post/batteries", "89-95", [*driver, "--binary", str(post), "--out",
                                     str(OUT / "post/batteries"), "--batteries", "--expect-equal"]),
        ("post/netcap-unit", "89-95", ["build/netcap-unit"]),
        ("post/frontier-unit", "89-95", ["build/netcap-unit", "frontier"]),
        ("post/respresume-unit", "89-95", ["build/respresume-unit"]),
        # This in-process migration fixture requires eight allowed CPUs.
        ("post/respresume-migration", "80-95", ["build/respresume-migration"]),
        ("post/gates-test", "89-95", ["env", "GATE_TEST_PORT=22899",
                                      "python3", "tests/gates_test.py"]),
    ]
    rows = []
    for name, cores, command in jobs:
        assert hashlib.sha256(post.read_bytes()).hexdigest() == digest, "POST changed during proof"
        log = OUT / (name + ".log")
        log.parent.mkdir(parents=True, exist_ok=True)
        command = ["taskset", "-c", cores, *command]
        start = time.monotonic()
        with log.open("w") as stream:
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        row = dict(name=name, command=command, returncode=result.returncode,
                   elapsed_seconds=round(time.monotonic() - start, 3))
        rows.append(row)
        (OUT / "runtime.json").write_text(json.dumps(
            dict(post_sha256=digest, jobs=rows), indent=2) + "\n")
        print(json.dumps(row), flush=True)
    # The PRE driver records expected row failures without making those failures
    # its own exit code. Require all eight N3/N4 failures explicitly.
    pre_rows = (OUT / "pre/rows.log").read_text().splitlines()
    expected = {f"{mode}-{engine} N{n}: rc=1" for mode in ("1s", "2s")
                for engine in ("uring", "epoll") for n in (3, 4)}
    assert expected <= set(pre_rows), pre_rows
    assert all(not r["returncode"] for r in rows), rows


if __name__ == "__main__":
    main()
