#!/usr/bin/env python3
"""Standing RO1/RO2 bounds, real parser witnesses and old-algorithm controls."""
import subprocess


def run(binary, args=(), failure=None):
    result = subprocess.run([binary, *args], text=True, capture_output=True, timeout=60)
    print(result.stdout, end="")
    print(result.stderr, end="")
    if failure:
        assert result.returncode == 1 and failure in result.stderr, (binary, result)
        print(f"CONTROL FAIL {binary}: {failure}")
    else:
        assert result.returncode == 0, (binary, result)


for suffix in ("", "-db0"):
    run(f"build/reorderscan{suffix}-unit")
    run(f"build/reorderscan{suffix}-quadratic", failure="prefix only once")
    run(f"build/reorderscan{suffix}-eager", failure="non-dispatch passes did shadow work")
    run(f"build/reorderscan{suffix}-paths", ["post"])
