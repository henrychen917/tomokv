#!/usr/bin/env python3
"""Non-gated MONITOR witnesses against two already-running peers.

Usage: tools/infofields_monitor_strict.py TARGET_HOST TARGET_PORT ORACLE_HOST ORACLE_PORT [--scripts]
The default witnesses refused-command visibility. --scripts additionally checks
nested Lua feeds; neither mode is a discovered differential suite or gate row.
"""
import argparse
import contextlib
import importlib.util
import io
from pathlib import Path
import random
import sys


def load_differ():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "tests"))
    spec = importlib.util.spec_from_file_location("infofields_witness", root / "tests/differ.py")
    module = importlib.util.module_from_spec(spec)
    saved = sys.argv
    try:
        sys.argv = ["differ.py", "--list-generators"]
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                spec.loader.exec_module(module)
            except SystemExit as stopped:
                assert stopped.code == 0
    finally:
        sys.argv = saved
    return module


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("target_host")
    p.add_argument("target_port", type=int)
    p.add_argument("oracle_host")
    p.add_argument("oracle_port", type=int)
    p.add_argument("--scripts", action="store_true")
    p.add_argument("--seed", type=int, default=7)
    a = p.parse_args()
    d = load_differ()
    d.TH, d.TP, d.OH, d.OP = a.target_host, a.target_port, a.oracle_host, a.oracle_port
    if a.scripts:
        d.MONITOR_SCRIPT = "return redis.call('get', KEYS[1])"
        d.MONITOR_SHA = d.hashlib.sha1(d.MONITOR_SCRIPT.encode()).hexdigest()
        d.MONITOR_LIBRARY = d.MONITOR_LIBRARY.replace("return 7", "return redis.call('get',keys[1])")
    d.run_monitor_suite(random.Random(a.seed), strict=True, nested=a.scripts)
