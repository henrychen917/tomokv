#!/usr/bin/env python3
"""Round-robin campaign driver for tests/writer_atomic.py.

The production matrix uses >=60-second cells.  --include-soak appends the same
>=600-second contention-amplified soak to all four arms.  --validation permits
short cells solely for harness and sanitizer checks.

Servers are started one at a time.  Before and after every boot, listener PIDs
are resolved with ss.  The driver terminates only the exact process it started
and refuses to touch an unexpected listener.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SERVER_CPUS = "32-47"
LOAD_CPUS = "96-119"
SPINNER_CPUS = list(range(32, 48))


@dataclasses.dataclass(frozen=True)
class Arm:
    name: str
    port: int
    kind: str
    atomic: int | None = None


@dataclasses.dataclass(frozen=True)
class Cell:
    name: str
    command: str
    pattern: str
    writers: int
    keys: int
    spinners: int = 0
    soak: bool = False


ARMS = (
    Arm("tomokv-atomic0", 7040, "tomokv", 0),
    Arm("tomokv-atomic1", 7041, "tomokv", 1),
    Arm("dragonfly", 7042, "dragonfly"),
    Arm("redis74", 7043, "redis"),
)


# This is a coverage matrix, not an accidental Cartesian explosion.  Across the portable arms it
# covers all requested overlap patterns, 2/4/8/16/32 writers, 2/8/32/128 keys, all command families,
# a high-volume disjoint zero control, and a scheduling-gap amplifier.
CELLS = (
    Cell("control-disjoint-w32-k128", "mset", "disjoint", 32, 128),
    Cell("mset-full-w2-k2", "mset", "full", 2, 2),
    Cell("mset-partial-w4-k8", "mset", "partial", 4, 8),
    Cell("mset-rotating-w8-k32", "mset", "rotating", 8, 32),
    Cell("mset-full-w16-k128", "mset", "full", 16, 128),
    Cell("multi-mset-partial-w32-k32", "multi-mset", "partial", 32, 32),
    Cell("del-mset-full-w16-k8", "del-mset", "full", 16, 8),
    Cell("rename-full-w32-k2", "rename", "full", 32, 2),
    Cell("sunionstore-full-w8-k32", "sunionstore", "full", 8, 32),
    Cell("zunionstore-full-w4-k8", "zunionstore", "full", 4, 8),
    Cell("incrby-full-w32", "incrby", "full", 32, 1),
    Cell("oversubscribed-mset-rotating-w32-k128", "mset", "rotating", 32, 128,
         spinners=16),
)

SOAK = Cell("soak-oversubscribed-mset-rotating-w32-k128", "mset", "rotating", 32, 128,
            spinners=16, soak=True)


def listener_pids(port: int) -> set[int]:
    output = subprocess.run(["ss", "-lntp"], check=True, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout
    pids: set[int] = set()
    marker = re.compile(rf":{port}\b")
    for line in output.splitlines():
        if not marker.search(line):
            continue
        pids.update(int(value) for value in re.findall(r"pid=(\d+)", line))
    return pids


def ping(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0) as sock:
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            return sock.recv(64) == b"+PONG\r\n"
    except OSError:
        return False


class ServerProcess:
    def __init__(self, arm: Arm, args: argparse.Namespace, run_dir: Path):
        self.arm = arm
        self.args = args
        self.run_dir = run_dir
        self.data_dir = Path(tempfile.mkdtemp(prefix=f"writer-atomic-{arm.name}-"))
        self.log_file = open(run_dir / "server.log", "wb")
        self.process: subprocess.Popen[bytes] | None = None

    def command(self) -> list[str]:
        prefix = ["taskset", "-c", SERVER_CPUS]
        if self.arm.kind == "tomokv":
            binary = Path(self.args.tomokv_binary).resolve()
            return prefix + [str(binary), "--bind", "127.0.0.1", "--port", str(self.arm.port),
                             "--ratio", "8:8", "--shards", "64", "--atomic",
                             str(self.arm.atomic), "--dir", str(self.data_dir),
                             "--dbfilename", "writer-atomic.rdb"]
        if self.arm.kind == "dragonfly":
            binary = Path(self.args.dragonfly_binary).resolve()
            return prefix + [str(binary), f"--bind=127.0.0.1", f"--port={self.arm.port}",
                             "--proactor_threads=16", f"--dir={self.data_dir}"]
        binary = Path(self.args.redis_binary).resolve()
        return ["taskset", "-c", "32", str(binary), "--bind", "127.0.0.1",
                "--port", str(self.arm.port), "--save", "", "--appendonly", "no",
                "--dir", str(self.data_dir), "--dbfilename", "writer-atomic.rdb"]

    def start(self) -> None:
        existing = listener_pids(self.arm.port)
        if existing:
            raise RuntimeError(f"port {self.arm.port} already has listener PIDs {sorted(existing)}")
        command = self.command()
        (self.run_dir / "server-command.json").write_text(
            json.dumps(command, indent=2) + "\n", encoding="utf-8")
        self.process = subprocess.Popen(command, cwd=ROOT, stdout=self.log_file,
                                        stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"{self.arm.name} exited during boot with {self.process.returncode}")
            pids = listener_pids(self.arm.port)
            if pids:
                if pids != {self.process.pid}:
                    raise RuntimeError(
                        f"listener ownership mismatch: started {self.process.pid}, found {sorted(pids)}")
                if ping(self.arm.port):
                    return
            time.sleep(0.05)
        raise RuntimeError(f"{self.arm.name} did not listen on {self.arm.port}")

    def stop(self) -> None:
        try:
            if self.process is None:
                return
            pids = listener_pids(self.arm.port)
            unexpected = pids - {self.process.pid}
            if unexpected:
                raise RuntimeError(
                    f"refusing to terminate unexpected listener PIDs {sorted(unexpected)}")
            if self.process.poll() is None:
                os.kill(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.kill(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=10)
            deadline = time.monotonic() + 5
            while listener_pids(self.arm.port) and time.monotonic() < deadline:
                time.sleep(0.05)
            survivors = listener_pids(self.arm.port)
            if survivors:
                raise RuntimeError(f"listener survived termination: PIDs {sorted(survivors)}")
        finally:
            self.log_file.close()
            shutil.rmtree(self.data_dir, ignore_errors=True)


def start_spinners(count: int) -> list[subprocess.Popen[bytes]]:
    spinners = []
    for index in range(count):
        cpu = SPINNER_CPUS[index % len(SPINNER_CPUS)]
        process = subprocess.Popen(
            ["taskset", "-c", str(cpu), sys.executable, "-c", "while True: pass"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        spinners.append(process)
    return spinners


def stop_spinners(spinners: list[subprocess.Popen[bytes]]) -> None:
    for process in spinners:
        if process.poll() is None:
            os.kill(process.pid, signal.SIGTERM)
    for process in spinners:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.kill(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def run_cell(arm: Arm, cell: Cell, repetition: int, args: argparse.Namespace,
             output_root: Path) -> dict[str, Any]:
    duration = args.soak_seconds if cell.soak else args.seconds
    run_name = f"rep{repetition:02d}-{cell.name}-{arm.name}"
    run_dir = output_root / run_name
    run_dir.mkdir(parents=True)
    server = ServerProcess(arm, args, run_dir)
    spinners: list[subprocess.Popen[bytes]] = []
    started = time.monotonic()
    try:
        server.start()
        spinners = start_spinners(cell.spinners)
        json_path = run_dir / "result.json"
        command = [
            "taskset", "-c", LOAD_CPUS, sys.executable, str(ROOT / "tests/writer_atomic.py"),
            "127.0.0.1", str(arm.port), "--command", cell.command, "--pattern", cell.pattern,
            "--writers", str(cell.writers), "--keys", str(cell.keys), "--seconds", str(duration),
            "--active-ms", str(args.active_ms), "--settle-ms", str(args.settle_ms),
            "--prefix", f"wstress:{repetition}:{cell.name}:{arm.name}",
            "--json-out", str(json_path),
        ]
        if args.validation:
            command.append("--allow-short")
        if arm.atomic is not None:
            command.extend(("--tomokv-mode", str(arm.atomic)))
        (run_dir / "harness-command.json").write_text(
            json.dumps(command, indent=2) + "\n", encoding="utf-8")
        with open(run_dir / "harness.log", "wb") as log:
            completed = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        if not json_path.exists():
            raise RuntimeError(
                f"harness rc={completed.returncode} produced no result; see {run_dir / 'harness.log'}")
        result = json.loads(json_path.read_text(encoding="utf-8"))
        result.update({
            "arm": arm.name,
            "cell": cell.name,
            "repetition": repetition,
            "spinners": cell.spinners,
            "harness_returncode": completed.returncode,
            "wall_seconds": time.monotonic() - started,
        })
        if completed.returncode not in (0, 1):
            raise RuntimeError(f"harness error rc={completed.returncode}: {result.get('errors')}")
        return result
    finally:
        stop_spinners(spinners)
        server.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=None)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--soak-seconds", type=float, default=600.0)
    parser.add_argument("--active-ms", type=float, default=100.0)
    parser.add_argument("--settle-ms", type=float, default=10.0)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--include-soak", action="store_true")
    parser.add_argument("--validation", action="store_true",
                        help="allow short smoke/ASAN cells; never label these campaign evidence")
    parser.add_argument("--only", action="append", default=[], help="cell name (repeatable)")
    parser.add_argument("--arms", nargs="+", choices=[arm.name for arm in ARMS],
                        default=[arm.name for arm in ARMS])
    parser.add_argument("--tomokv-binary", default=str(ROOT / "build/tomokv"))
    parser.add_argument(
        "--dragonfly-binary",
        default=("/tmp/claude-1000/-home-user-Projects/"
                 "ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/dragonfly-x86_64"))
    parser.add_argument("--redis-binary",
                        default="/tmp/claude-1000/redis74/src/redis-server")
    args = parser.parse_args()
    if not args.validation and args.seconds < 60:
        parser.error("production cells require --seconds >=60")
    if not args.validation and args.include_soak and args.soak_seconds < 600:
        parser.error("production soak requires --soak-seconds >=600")
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    return args


def main() -> int:
    args = parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = Path(args.output or f"/tmp/writer-atomic-campaign-{stamp}").resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    selected = list(CELLS)
    if args.include_soak:
        selected.append(SOAK)
    if args.only:
        wanted = set(args.only)
        selected = [cell for cell in selected if cell.name in wanted]
        missing = wanted - {cell.name for cell in selected}
        if missing:
            raise SystemExit(f"unknown/unselected cell(s): {sorted(missing)}")
    arms = [arm for arm in ARMS if arm.name in args.arms]
    manifest = {
        "started_utc": stamp,
        "root": str(ROOT),
        "server_cpus": SERVER_CPUS,
        "load_cpus": LOAD_CPUS,
        "seconds": args.seconds,
        "soak_seconds": args.soak_seconds,
        "repetitions": args.repetitions,
        "validation": args.validation,
        "cells": [dataclasses.asdict(cell) for cell in selected],
        "arms": [dataclasses.asdict(arm) for arm in arms],
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    combined = output_root / "results.jsonl"
    failures = 0
    total = args.repetitions * len(selected) * len(arms)
    completed_count = 0
    for repetition in range(1, args.repetitions + 1):
        for cell_index, cell in enumerate(selected):
            # Rotate the first arm so background variation does not always privilege one server.
            offset = (repetition - 1 + cell_index) % len(arms)
            ordered_arms = arms[offset:] + arms[:offset]
            for arm in ordered_arms:
                completed_count += 1
                print(f"[{completed_count}/{total}] START {cell.name} {arm.name}", flush=True)
                try:
                    result = run_cell(arm, cell, repetition, args, output_root)
                    with open(combined, "a", encoding="utf-8") as output:
                        output.write(json.dumps(result, sort_keys=True) + "\n")
                    print(
                        f"[{completed_count}/{total}] DONE  {cell.name} {arm.name} "
                        f"status={result['status']} writes={result['writes_total']} "
                        f"probes={result['quiescent_probes']}+{result['final_drain_probes']} "
                        f"violations={result['violations']} wall={result['wall_seconds']:.1f}s",
                        flush=True,
                    )
                    if result["errors"]:
                        failures += 1
                except Exception as exc:
                    failures += 1
                    error = {"arm": arm.name, "cell": cell.name, "repetition": repetition,
                             "driver_error": f"{type(exc).__name__}: {exc}"}
                    with open(combined, "a", encoding="utf-8") as output:
                        output.write(json.dumps(error, sort_keys=True) + "\n")
                    print(f"[{completed_count}/{total}] ERROR {cell.name} {arm.name}: {exc}",
                          flush=True)
    print(f"CAMPAIGN_DONE output={output_root} runs={total} driver_failures={failures}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
