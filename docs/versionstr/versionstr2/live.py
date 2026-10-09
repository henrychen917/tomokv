#!/usr/bin/env python3
"""Focused versionstr2 correctness replay; run only with a quiet-box allocation.

Uses the unchanged infofix stream, both RESP modes, both database builds, both
thread geometries and both atomic settings. No throughput verdict is produced.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))
from _gate_process import fields, info, install_signals, server, stop_process
from _lib import wait_ready

ORACLE = Path("/home/user/Projects/redis74/src/redis-server")
BANNER = "TomoKV 1.0-cpp (Redis 7.4.10 compatible)"


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def quiet(out):
    # Initial attempt plus three retries, spanning ten minutes. A refusal is
    # retained as evidence and cannot be turned into a passed live cell.
    started = time.monotonic()
    for attempt in range(4):
        due = started + 200 * attempt
        while time.monotonic() < due:
            time.sleep(min(10, due - time.monotonic()))
        commands = [["bash", "tools/quietcheck.sh", "112-127", str(port)]
                    for port in (18460, 18461)]
        with (out / f"quiet-{attempt}.log").open("w") as log:
            log.write(time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()) + "\n")
            log.flush()
            results = [subprocess.run(command, cwd=ROOT, stdout=log,
                                      stderr=subprocess.STDOUT).returncode
                       for command in commands]
            subprocess.run(["ps", "-C", "cc1plus", "-o", "pid,ppid,psr,etime,comm"],
                           stdout=log, stderr=subprocess.STDOUT)
        print(f"quiet attempt {attempt}: {results}", flush=True)
        if results == [0, 0]:
            return
    raise RuntimeError("quiet preflight refused initial attempt and three retries over ten minutes")


@contextlib.contextmanager
def oracle(out):
    directory = out / "oracle"
    directory.mkdir()
    args = ["taskset", "-c", "127", str(ORACLE), "--port", "18461",
            "--bind", "127.0.0.1", "--dir", str(directory), "--save", "",
            "--appendonly", "no", "--enable-debug-command", "yes"]
    save(directory / "argv.json", args)
    with (directory / "server.log").open("w") as log:
        process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
        conn = None
        try:
            conn = wait_ready("127.0.0.1", 18461, process=process, timeout=20,
                              log_path=directory / "server.log")
            identity = fields(conn.must("INFO", "server"))
            assert int(identity["process_id"]) == process.pid
            assert identity["redis_version"] == "7.4.10", identity
            save(directory / "identity.json", identity)
            yield
        finally:
            if conn:
                conn.close()
            forced = stop_process(process)
            save(directory / "exit.json", dict(returncode=process.returncode, forced=forced))
        assert process.returncode == 0 and not forced


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    binary, out = args.binary.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    os.chdir(ROOT)
    os.sched_setaffinity(0, set(range(120, 127)))
    install_signals()
    save(out / "binaries.json", {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in (binary, ORACLE)})
    quiet(out)
    rows = []
    with oracle(out):
        for databases in (1, 16):
            for geometry in ("split", "fused"):
                for atomic in (0, 1):
                    name = f"db{databases}-{geometry}-a{atomic}"
                    directory = out / name
                    flags = ["--shards", "16", "--databases", str(databases),
                             "--atomic", str(atomic)]
                    flags += (["--ratio", "6:2", "--read-local", "0"] if geometry == "split"
                              else ["--thread-mode", "1s", "--read-local", "1"])
                    with server(binary, "112-119", 18460, directory, flags) as (conn, process):
                        identity = info(conn, "server")
                        assert int(identity["process_id"]) == process.pid
                        assert identity["redis_version"] == "7.4.10"
                        assert identity["tomokv_version"] == "1.0-cpp"
                        save(directory / "identity.json", identity)
                        boot = (directory / "server.log").read_text()
                        assert boot.splitlines().count(BANNER) == 1, boot
                        expected = ("8 threads (6 io + 2 ex)" if geometry == "split"
                                    else "8 unified threads")
                        assert expected in boot and "16 shard(s)" in boot, boot
                        for seed in (7, 19, 20, 23):
                            for protocol in (2, 3):
                                label = f"{name}-s{seed}-resp{protocol}"
                                command = ["taskset", "-c", "120-126", "python3", "tests/differ.py",
                                           "127.0.0.1", "18460", "127.0.0.1", "18461", "infofix", str(seed)]
                                if protocol == 3:
                                    command.append("-3")
                                started = time.monotonic()
                                with (out / f"{label}.log").open("w") as log:
                                    result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                                            timeout=180)
                                row = dict(cell=label, databases=databases, geometry=geometry, atomic=atomic,
                                           seed=seed, protocol=protocol, returncode=result.returncode,
                                           seconds=time.monotonic() - started, argv=command)
                                rows.append(row)
                                save(out / "results.json", rows)
                                print(f"{label}: rc={result.returncode}", flush=True)
                        if geometry == "fused":
                            assert conn.must("SET", "versionstr2:lane", "v") == b"OK"
                            for _ in range(32):
                                assert conn.must("GET", "versionstr2:lane") == b"v"
                            counters = info(conn, "stats")
                            assert int(counters["read_local_hits"]) > 0, counters
                            save(directory / "read-local.json", counters)
    assert len(rows) == 64 and all(row["returncode"] == 0 for row in rows), rows
    print("PASS: 64 infofix cells; eight boot banners; four armed read-local witnesses", flush=True)


if __name__ == "__main__":
    main()
