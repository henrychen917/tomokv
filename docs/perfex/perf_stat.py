#!/usr/bin/env python3
"""Short, matched-offer executor diagnostic; never a main-command merit verdict.

CPUs 112-119: split 6:2 / 16 shards / databases 1, default balancing.
CPUs 120-127: eight memtier threads, four clients each, 2,000 ops/s/client.
The unchanged quiet-screen policy must pass before any server/load starts.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from _lib import Conn, info
from gate_quiet import QuietMonitor
from perfex_checks import require, server


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def command_count(conn, op):
    row = info(conn, "commandstats").get("cmdstat_" + op.lower())
    require(row is not None, "workload command counter missing")
    return int(dict(item.split("=") for item in row.split(","))["calls"])


def stat_window(conn, tids, seconds, folder, op=None):
    ctl, ack = folder / "control", folder / "ack"
    os.mkfifo(ctl)
    os.mkfifo(ack)
    ctl_fd, ack_fd = os.open(ctl, os.O_RDWR), os.open(ack, os.O_RDWR)
    argv = ["taskset", "-c", "120-127", "perf", "stat", "-x,", "-e", "cycles,instructions",
            "-t", ",".join(map(str, tids)), "-D", "-1", f"--control=fifo:{ctl},{ack}",
            "-o", str(folder / "perf.csv")]
    save(folder / "perf-argv.json", argv)
    def control(text):
        os.write(ctl_fd, (text + "\n").encode())
        require(select.select([ack_fd], [], [], 5)[0], "perf control acknowledgement timed out")
        require(os.read(ack_fd, 256).strip() == b"ack", "invalid perf control acknowledgement")
    with (folder / "perf.log").open("w") as log:
        perf = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
        try:
            control("enable")
            enabled = time.monotonic()
            before = command_count(conn, op) if op else 0
            t0 = time.monotonic()
            time.sleep(seconds)
            t1 = time.monotonic()
            after = command_count(conn, op) if op else 0
            control("disable")
            disabled = time.monotonic()
        finally:
            perf.send_signal(signal.SIGINT)
            try:
                perf.wait(timeout=5)
            except subprocess.TimeoutExpired:
                perf.kill()
                perf.wait()
            os.close(ctl_fd)
            os.close(ack_fd)
            ctl.unlink()
            ack.unlink()
    events = {}
    for line in (folder / "perf.csv").read_text().splitlines():
        fields = line.split(",")
        if len(fields) < 5 or fields[2] not in ("cycles", "instructions"):
            continue
        require(fields[0].strip().isdigit(), f"perf event unavailable: {line}")
        if len(fields) > 4 and fields[4].strip():
            require(float(fields[4]) >= 99.9, f"multiplexed perf group: {line}")
        events[fields[2]] = int(fields[0])
    require(events.keys() == {"cycles", "instructions"}, "missing executor PMU events")
    count = after - before
    row = dict(events=events, executor_tids=tids, completed=count, window_s=t1 - t0,
               pmu_envelope_s=disabled - enabled,
               endpoint_envelope_ms=1000 * ((t0 - enabled) + (disabled - t1)))
    if op:
        require(count > 0, "no workload completions")
        row.update(rate=count / (t1 - t0), offered_ops_s=64000,
                   cycles_per_op=events["cycles"] / count,
                   instructions_per_op=events["instructions"] / count,
                   ipc=events["instructions"] / events["cycles"])
        require(abs(row["rate"] / 64000 - 1) <= .02, f"offered rate was not held: {row['rate']}")
    else:
        row["idle_executor_cycles_s"] = events["cycles"] / (disabled - enabled)
    save(folder / "result.json", row)
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--sha256", required=True)
    p.add_argument("--port", type=int, default=25110)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    require(set(range(112, 128)) <= os.sched_getaffinity(0), "CPUs 112-127 must be available")
    require(25100 <= a.port <= 25124, "proof port outside authorized range")
    require(a.output.resolve().is_relative_to(ROOT), "output must stay in this worktree")
    require(hashlib.sha256(a.binary.read_bytes()).hexdigest() == a.sha256, "binary digest differs")
    a.output.mkdir(parents=True, exist_ok=False)
    os.sched_setaffinity(0, set(range(120, 128)))
    monitor = QuietMonitor(list(range(112, 120)), list(range(120, 128)), ports=(a.port,),
                           sample_artifact=a.output / "quiet-samples.jsonl")
    result = dict(binary=str(a.binary.resolve()), sha256=a.sha256, samples={}, status="INCOMPLETE")
    try:
        monitor.start()
        memtier = shutil.which("memtier_benchmark")
        require(memtier is not None, "memtier_benchmark missing")
        for op, depth in [(None, 0), ("GET", 8), ("SET", 8), ("GET", 32), ("SET", 32)]:
            name = "idle" if op is None else f"{op.lower()}{depth}"
            folder = (a.output / name).resolve()
            folder.mkdir()
            with server(a.binary, a.port, "112-119", balancing=True) as proc, closing(Conn("127.0.0.1", a.port)) as conn:
                tids = [int(t.name) for t in Path(f"/proc/{proc.pid}/task").iterdir()
                        if os.sched_getaffinity(int(t.name)) in ({118}, {119})]
                require(len(tids) == 2, f"expected two pinned executor threads, found {tids}")
                common = ["taskset", "-c", "120-127", memtier, "-s", "127.0.0.1", "-p", str(a.port),
                          "--key-minimum=1", "--key-maximum=100000", "--data-size=64", "--hide-histogram"]
                if op:
                    population = common + ["-t", "8", "-c", "1", "--ratio=1:0", "--key-pattern=P:P",
                                           "--requests=allkeys", "--pipeline=32"]
                    with (folder / "population.log").open("w") as log:
                        subprocess.run(population, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=60)
                    argv = common + ["-t", "8", "-c", "4", "--ratio=" + ("0:1" if op == "GET" else "1:0"),
                                     f"--pipeline={depth}", "--rate-limiting=2000", "--test-time=9"]
                    save(folder / "load-argv.json", argv)
                    with (folder / "load.log").open("w") as log:
                        load = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
                        try:
                            time.sleep(2)
                            require(load.poll() is None, "load exited before central window")
                            row = stat_window(conn, tids, 3, folder, op)
                            load.wait(timeout=15)
                            require(load.returncode == 0, "load failed")
                        finally:
                            if load.poll() is None:
                                load.terminate()
                                load.wait(timeout=5)
                else:
                    time.sleep(.2)
                    row = stat_window(conn, tids, 1, folder)
                result["samples"][name] = row
        monitor.check()
        result["status"] = "COMPLETE"
    except Exception as error:
        result.update(status="REFUSED_OR_FAILED", reason=f"{type(error).__name__}: {error}")
    finally:
        save(a.output / "quiet.json", monitor.close())
        save(a.output / "result.json", result)
    print(json.dumps(result), flush=True)
    return result["status"] != "COMPLETE"


if __name__ == "__main__":
    raise SystemExit(main())
