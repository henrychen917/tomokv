#!/usr/bin/env python3
"""flakeaudit2b: retain reproduction and serial six-job/full gate evidence."""
import argparse
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

import proof

ROOT = proof.ROOT
sys.path.insert(0, str(ROOT / "tests"))
import _lib

JOBS = "feature-split-0 feature-split-1 feature-armed-0 feature-armed-1 fused-0 fused-1"
GATE = ["taskset", "-c", "112-127", "tests/gate.sh", "iteration",
        "--server-cores", "112-119", "--load-cores", "120-127",
        "--server-smt", "", "--load-smt", "", "--ports", "18340-18342"]


def probe(out):
    """Contrast EXEC's direct commit with the scatter queue on the same two owners."""
    admin, writer = _lib.Conn("127.0.0.1", 18340), _lib.Conn("127.0.0.1", 18340)
    try:
        buckets = _lib.owner_buckets(admin, "flakeaudit2b:probe", per_owner=4)
        groups = [(owner, keys[:4]) for owner, keys in buckets.items() if len(keys) >= 4][:2]
        keys = [key for _, group in groups for key in group]
        result = dict(owners=groups, exec={}, scatter={})
        assert len(groups) == 2 and len(keys) == 8
        for key in keys:
            assert admin.cmd("SET", key, "old") == b"OK"
        with _lib.armed(admin, "ATOMIC-COMMIT-HOLD", 1):
            assert writer.cmd("MULTI") == b"OK"
            for key in keys:
                assert writer.cmd("SET", key, "new") == b"QUEUED"
            writer.send("EXEC")
            assert select.select([writer.sock], [], [], 10)[0], "EXEC unexpectedly held"
            reply = writer.read()
            values = admin.cmd("MGET", *keys)
            assert reply == [b"OK"] * 8 and values == [b"new"] * 8
            stats = _lib.info(admin, "stats")
            result["exec"] = dict(reply=repr(reply), values=repr(values),
                completed_while_hold_armed=True, pending_entries=stats["atomic_pending_entries"])
        assert admin.cmd("CONFIG", "SET", "atomic", "1") == b"OK"
        scatter_keys = [group[0] for _, group in groups]
        with _lib.armed(admin, "ATOMIC-COMMIT-HOLD", 1):
            writer.send("MSET", *[arg for key in scatter_keys for arg in (key, "scatter")])
            deadline = time.monotonic() + 10
            while int(_lib.info(admin, "stats")["atomic_pending_entries"]) < 2:
                assert time.monotonic() < deadline, "scatter queue never held installed entries"
                time.sleep(.005)
            assert not select.select([writer.sock], [], [], 0)[0]
            assert admin.cmd("MGET", *scatter_keys) == [b"new"] * 2
            result["scatter"] = dict(pending_entries=_lib.info(admin, "stats")["atomic_pending_entries"],
                                      reply_blocked_until_release=True)
        assert writer.read() == b"OK"
        assert admin.cmd("MGET", *scatter_keys) == [b"scatter"] * 2
        proof.write(out / "hook-probe.json", result)
    finally:
        writer.close()
        admin.close()


def reproduce(base):
    build = base / "build"
    build.mkdir()
    rc = proof.run(build, ["taskset", "-c", "112-127", "make", "-j16"])
    if rc:
        return rc
    results = []
    for mode, read_local in (("2s", 0), ("1s", 0), ("1s", 1)):
        for atomic in (0, 1):
            out = base / ("%s-rl%d-a%d" % (mode, read_local, atomic))
            out.mkdir()
            data = ROOT / "build" / ("flakeaudit2b-" + out.name)
            data.mkdir(exist_ok=True)
            command = ["taskset", "-c", "112-119", "build/tomokv", "--port", "18340",
                       "--bind", "127.0.0.1", "--shards", "16", "--ratio", "6:2",
                       "--thread-mode", mode, "--read-local", str(read_local), "--atomic", str(atomic),
                       "--enable-debug-command", "yes", "--save", "", "--dir", str(data)]
            with (out / "server.log").open("w") as log:
                server = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            row = dict(server_command=command)
            try:
                deadline = time.monotonic() + 30
                while True:
                    assert server.poll() is None, "server exited during boot"
                    try:
                        conn = _lib.Conn("127.0.0.1", 18340)
                        conn.close()
                        break
                    except OSError:
                        assert time.monotonic() < deadline, "server boot timeout"
                        time.sleep(.1)
                env = os.environ.copy()
                env["TOMO_GATE_STRICT"] = "1"
                env["PYTHONPATH"] = str(ROOT / "tests")
                rc = proof.run(out, ["taskset", "-c", "120-127", "python3", str(base.parent / "rejected-multi_exec.py"),
                                     "127.0.0.1", "18340"], env)
                row["battery_rc"] = rc
                row["expected_failure"] = rc != 0 and "AssertionError: EXEC never installed held records" in (out / "run.log").read_text()
                assert row["expected_failure"], row
                probe(out)
            finally:
                server.send_signal(signal.SIGTERM)
                row["server_rc"] = server.wait(timeout=30)
                results.append(row)
                proof.write(base / "summary.json", results)
            assert row["server_rc"] == 0, row
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("reproduce", "selected", "full"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--prior-screen", type=Path)
    args = parser.parse_args()
    os.chdir(ROOT)
    base = args.output.resolve()
    # Never turn a refused/failed campaign into a pass by overwriting its files.
    base.mkdir(parents=True, exist_ok=args.prior_screen is not None)
    proof.write(base / "request.json", dict(stage=args.stage,
        jobs=JOBS if args.stage == "selected" else None,
        command=GATE, repetitions=6 if args.stage == "selected" else 1,
        revision=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        origin=subprocess.check_output(["git", "rev-parse", "origin/cpp"], text=True).strip()))
    if not proof.quiet(base, args.prior_screen):
        return 3
    if args.stage == "reproduce":
        return reproduce(base)
    # Merge may have changed source while an older release binary still exists.
    # Establish the candidate before the before/after SHA check on every gate run.
    build = base / "build"
    build.mkdir()
    rc = proof.run(build, ["taskset", "-c", "112-127", "make", "-j16"])
    if rc:
        return rc
    for index in range(1, 7 if args.stage == "selected" else 2):
        out = base / ("run-%d" % index)
        out.mkdir()
        env = os.environ.copy()
        env.pop("GATE_ONLY_JOBS", None)
        env["GATE_LEDGER"] = str(out / "ledger")
        if args.stage == "selected":
            env["GATE_ONLY_JOBS"] = JOBS
        rc = proof.run(out, GATE, env, gate=True)
        if rc:
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
