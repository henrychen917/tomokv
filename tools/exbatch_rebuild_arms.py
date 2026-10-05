#!/usr/bin/env python3
"""Rebuild the frozen lane arms without starting a server or load generator.

Archive the recorded source revisions into a NEW directory in this worktree.
The archived Makefiles retain all per-object compiler flags. Debug prefix maps
restore the original compilation directories without writing outside the lane.
A mismatched POST never produces controls or a usable arms.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time

from exbatch_directed import ROOT, RECEIPTS, ARMS, digest, require, save


def rebuild_control(post, plan, expected, target):
    raw = bytearray(post.read_bytes())
    require(hashlib.sha256(raw).hexdigest() == plan["source_sha256"],
            "control receipt belongs to a different POST")
    for patch in plan["patches"]:
        at = patch["offset"]
        before, after = bytes.fromhex(patch["before"]), bytes.fromhex(patch["after"])
        require(len(before) == len(after) == 5 and raw[at:at + 5] == before,
                "control patch does not match frozen POST")
        raw[at:at + 5] = after
    require(hashlib.sha256(raw).hexdigest() == expected, "rebuilt control SHA mismatch")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    target.chmod(0o555)


def build_arm(arm, manifest, output, report):
    config = manifest["build"]
    commit = manifest[arm.lower() + "_commit"]
    source = output / arm / "source"
    source.mkdir(parents=True)
    archive = output / (arm + "-source.tar")
    subprocess.run(["git", "archive", "-o", str(archive), commit], cwd=ROOT, check=True)
    with tarfile.open(archive) as stream:
        stream.extractall(source, filter="data")
    archive.unlink()
    original = config[arm.lower() + "_directory"]
    flags = config["cxxflags"] + f" -fdebug-prefix-map={source}={original}"
    argv = ["taskset", "-c", config["cpus"], "make", f"-j{config['jobs']}",
            "CXX=g++", "CXXFLAGS=" + flags, f"JE={config['je']}", "BUILD_ROOT=build", "all"]
    env = dict(os.environ)
    for key in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES", "LDLIBS", "LDFLAGS",
                "CPPFLAGS", "JEFLAGS", "JELIBS", "SOURCE_DATE_EPOCH", "LD_PRELOAD"):
        env.pop(key, None)
    env["LC_ALL"] = "C"
    log = output / (arm + "-build.log")
    record = report["builds"][arm] = dict(commit=commit, cwd=str(source), argv=argv,
                                           log=str(log), original_directory=original)
    save(output / "rebuild.json", report)
    print(f"Building {arm} from {commit}; log: {log}", flush=True)
    with log.open("wb") as stream:
        subprocess.run(argv, cwd=source, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)
    binary = source / "build/tomokv"
    record["sha256"] = digest(binary)
    record["expected_sha256"] = next(r["sha256"] for r in manifest["artifacts"] if r["arm"] == arm)
    record["sha256_reproduced"] = record["sha256"] == record["expected_sha256"]
    save(output / "rebuild.json", report)
    require(record["sha256_reproduced"],
            f"{arm} SHA mismatch: got {record['sha256']}, expected {record['expected_sha256']}; "
            "no arms receipt issued (see rebuild.json)")
    return binary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/exbatch-rebuilt",
                        help="new build directory inside this worktree")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    require(output.is_relative_to(ROOT / "build"), "rebuild output must be inside this worktree's build/")
    require(not output.exists(), "rebuild output must be new; do not mix builds")
    os.sched_setaffinity(0, set(range(112, 128)))
    manifest = json.loads(RECEIPTS.read_text())
    compiler = subprocess.check_output(["g++", "--version"], text=True).splitlines()[0]
    require(compiler == manifest["build"]["compiler"], "compiler differs from frozen build receipt")
    output.mkdir(parents=True)
    started = time.monotonic()
    report = dict(complete=False, compiler=compiler, cpus=sorted(os.sched_getaffinity(0)),
                  receipt=dict(path=str(RECEIPTS), sha256=digest(RECEIPTS)), builds={}, controls={})
    try:
        # POST is the strict prerequisite for applying any frozen retargets.
        post = build_arm("POST", manifest, output, report)
        paths = {"POST": post}
        for arm in ARMS:
            if arm in ("PRE", "POST"):
                continue
            directory = ROOT / "docs/exbatch" / ("pad-a" if arm == "PAD-A" else arm.lower())
            plan_path = directory / "planned-retargets.json"
            plan = json.loads(plan_path.read_text())
            expected = next(r["sha256"] for r in manifest["artifacts"] if r["arm"] == arm)
            target = output / arm / "tomokv"
            rebuild_control(post, plan, expected, target)
            paths[arm] = target
            report["controls"][arm] = dict(sha256=expected, plan_sha256=digest(plan_path),
                                           kind="A: PRE behaviour for selected items at POST layout")
        paths["PRE"] = build_arm("PRE", manifest, output, report)
        receipt = {arm: dict(path=str(paths[arm].relative_to(output)), sha256=digest(paths[arm])) for arm in ARMS}
        save(output / "arms.json", receipt)
        report["complete"] = True
        report["arms_receipt"] = dict(path=str(output / "arms.json"), sha256=digest(output / "arms.json"))
        print(f"All six frozen SHA256 values reproduced; receipt: {output / 'arms.json'}", flush=True)
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        save(output / "rebuild.json", report)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"EXBATCH REBUILD FAILED: {error}", file=sys.stderr)
        sys.exit(1)
