#!/usr/bin/env python3
"""Isolate each admitted wake, using the differential's actual RESP codec/witness."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from _differ_aclkeys import cases, wait_blocked
from gate_quiet import QuietMonitor, QuietViolation
from psfix import boot


def now():
    return datetime.now(timezone.utc).isoformat()


def codec():
    # Import only these definitions: differ.py is a command-line program.
    tree = ast.parse((ROOT / "tests/differ.py").read_text())
    names = {"conn_mode", "enc", "read_exact", "read_reply", "parse_reply"}
    tree.body = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in names]
    api = dict(socket=socket)
    exec(compile(tree, "tests/differ.py", "exec"), api)
    return api


def quiet(out, ports):
    first = time.monotonic()
    for attempt in range(4):
        while time.monotonic() < first + 200 * attempt:
            time.sleep(min(10, first + 200 * attempt - time.monotonic()))
        monitor = QuietMonitor(range(112, 120), range(120, 128), ports=ports,
            sample_artifact=out / ("quiet-%d-samples.jsonl" % attempt))
        passed = False
        try:
            monitor.preflight()
            passed = True
        except QuietViolation as error:
            print(now(), error, flush=True)
        finally:
            (out / ("quiet-%d.json" % attempt)).write_text(
                json.dumps(monitor.close(), indent=2) + "\n")
        if passed:
            print(now(), "quiet preflight PASS", flush=True)
            return True
    return False


def reproduce(binary, out):
    oracle = Path("/home/user/Projects/redis74/src/redis-server")
    (out / "reproduction-identity.json").write_text(json.dumps(dict(start=now(),
        binary=str(binary), sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        oracle=str(oracle), oracle_sha256=hashlib.sha256(oracle.read_bytes()).hexdigest(),
        geometry="split 6:2, 16 shards, 16 databases", server_cpus="112-119",
        oracle_client_cpus="120-127", socket_timeout_seconds=5), indent=2) + "\n")
    api = codec()
    enc, read, parse = (api[name] for name in ("enc", "read_reply", "parse_reply"))
    results = []
    for atomic in (0, 1):
        for label, cores, port in (("TomoKV", "112-119", 18540),
                                   ("Redis", "120-127", 18541)):
            name = "%s-a%d" % (label, atomic)
            directory = ROOT / "build/aclkeys2" / out.name / name
            directory.mkdir(parents=True, exist_ok=False)
            argv = [str(binary if label == "TomoKV" else oracle),
                    "--bind", "127.0.0.1", "--port", str(port),
                    "--dir", str(directory), "--save", ""]
            argv += (["--shards", "16", "--ratio", "6:2", "--databases", "16",
                      "--atomic", str(atomic)] if label == "TomoKV" else
                     ["--appendonly", "no"])
            with boot(argv, cores, port, out / (name + "-server.txt")):
                def connect():
                    pair = api["conn_mode"]("127.0.0.1", port, False, buffering=0)
                    pair[0].settimeout(5)
                    return pair

                def issue(pair, args):
                    pair[0].sendall(enc(args))
                    return read(pair[1])

                admin = connect()
                try:
                    if label == "Redis":
                        assert b"redis_version:7.4.10\r\n" in parse(issue(admin, ["INFO", "SERVER"]))
                    assert issue(admin, ["ACL", "SETUSER", "aclkeys-repro", "reset", "on",
                                         "nopass", "~block:*", "+@all"]) == b"+OK\r\n"
                    for args, keys, wake in cases("0", "block:aclkeys"):
                        worker = connect()
                        row = dict(atomic=atomic, server=label, command=args, wake=wake)
                        try:
                            assert issue(worker, ["AUTH", "aclkeys-repro", "unused"]) == b"+OK\r\n"
                            issue(admin, ["DEL", *keys])
                            client_id = int(parse(issue(worker, ["CLIENT", "ID"]))[1:])
                            worker[0].sendall(enc(args))
                            wait_blocked(admin, worker, client_id, issue, parse, read)
                            row["parked"] = True
                            start = time.monotonic()
                            row["wake_reply"] = repr(issue(admin, wake))
                            reply = read(worker[1])
                            row.update(verdict="WOKE", milliseconds=1000 * (time.monotonic() - start),
                                       reply=repr(reply))
                            assert b"value" in reply, reply
                            assert issue(worker, ["PING"]) == b"+PONG\r\n"
                        except TimeoutError:
                            row["verdict"] = "TIMEOUT"
                        finally:
                            worker[1].close()
                            worker[0].close()
                        results.append(row)
                        print(json.dumps(row), flush=True)
                        (out / "reproduction.json").write_text(json.dumps(results, indent=2) + "\n")
                finally:
                    admin[1].close()
                    admin[0].close()
    for atomic in (0, 1):
        print("atomic=%d\n| Command | TomoKV | Redis 7.4.10 |\n|---|---|---|" % atomic)
        for args, _, _ in cases("0", "block:aclkeys"):
            cells = []
            for label in ("TomoKV", "Redis"):
                row = next(row for row in results if row["atomic"] == atomic and
                           row["server"] == label and row["command"] == args)
                cells.append(("WOKE %.3f ms / `%s`" % (row["milliseconds"], row["reply"]))
                             if row["verdict"] == "WOKE" else row["verdict"])
            print("| %s | %s | %s |" % (args[0], *cells), flush=True)


def differential(binary, out):
    from _differ_history import permanent_seeds
    seeds = permanent_seeds()
    (out / "seeds.txt").write_text("".join("%d\n" % seed for seed in seeds))
    (out / "suites.txt").write_text("aclkeys\n")
    results = []
    for geometry in ("split", "armed-fused"):
        directory = out / geometry
        env = dict(os.environ, GATE_LOAD_CORES="120-127", GATE_DIFFER_ORACLE_CORES="120-127",
                   REDIS74_ROOT="/home/user/Projects/redis74", GATE_DIFFER_GEOMETRY=geometry,
                   GATE_DIFFER_OUT=str(directory), GATE_DIFFER_PROOF_SUITES=str(out / "suites.txt"),
                   GATE_DIFFER_PROOF_SEEDS=str(out / "seeds.txt"))
        argv = ["taskset", "-c", "120-127", "bash", "tests/differ_gate.sh",
                str(binary), "18540", "18541", "112-119", "6:2"]
        with (out / (geometry + ".txt")).open("w") as log:
            proc = subprocess.run(argv, cwd=ROOT, env=env, stdout=log,
                                  stderr=subprocess.STDOUT, timeout=180)
        print((out / (geometry + ".txt")).read_text(), flush=True)
        legs = []
        for atomic in (0, 1):
            for seed in seeds:
                path = directory / ("aclkeys-a%d-s%d.txt" % (atomic, seed))
                content = path.read_text() if path.exists() else ""
                legs.append(dict(atomic=atomic, seed=seed, path=str(path),
                                 passed="DIFFER aclkeys: PASS" in content))
        results.append(dict(geometry=geometry, exit=proc.returncode, legs=legs))
        (out / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    return int(any(row["exit"] or not all(leg["passed"] for leg in row["legs"]) for row in results))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--differ", action="store_true")
    parser.add_argument("--reproduce-binary", type=Path,
                        help="reproduce the saved failing binary before the final differential")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "identity.json").write_text(json.dumps(dict(start=now(),
        binary=str(args.binary.resolve()), sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        affinity=sorted(os.sched_getaffinity(0))), indent=2) + "\n")
    if not quiet(args.output, (18540, 18541)):
        (args.output / "REFUSED").write_text("All four quiet preflight attempts refused.\n")
        sys.exit(2)
    if args.differ:
        if args.reproduce_binary:
            reproduce(args.reproduce_binary.resolve(), args.output)
        sys.exit(differential(args.binary.resolve(), args.output.resolve()))
    reproduce(args.binary.resolve(), args.output)
