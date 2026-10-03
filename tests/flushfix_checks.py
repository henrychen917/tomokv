#!/usr/bin/env python3
"""ST1/ST10 serverless proofs and throwaway controls; live mode is mainline-only."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = "e279aeb4cf08ae2c39f26be679388b872fed4667"
SITES = dict(raw="kvobj_init_raw_string", int="kvobj_init_int", string="kvobj_new_string",
             typeval="kvobj_new_typeval", embedded="kvobj_new_embedded_typeval",
             reheader="kvobj_reheader")


def overlay(output, directory, replacements):
    target = output / "src" / directory
    target.mkdir(parents=True, exist_ok=True)
    for path in (ROOT / "src").iterdir():
        dest = output / "src" / path.name
        if path.name != directory and not dest.exists():
            dest.symlink_to(path)
    for path in (ROOT / "src" / directory).iterdir():
        dest = target / path.name
        if dest.is_symlink() or dest.exists():
            dest.unlink()
        if path.name in replacements:
            dest.write_text(replacements[path.name])
        else:
            dest.symlink_to(path)


def emit_header(site, output):
    source = (ROOT / "src/store/kvobj.h").read_text()
    begin = source.index(f"inline KvObj* {SITES[site]}(")
    end = source.find("\ninline ", begin + 1)
    if end < 0:
        end = len(source)
    body = source[begin:end]
    assert body.count("key.identity() >= 255") == 3, (site, "header predicate moved")
    body = body.replace("key.identity() >= 255", "key.n >= 255")
    overlay(output, "store", {"kvobj.h": source[:begin] + body + source[end:]})


def emit_pre(output):
    # Use the actual launch sources, never a production tree with edits reverted.
    originals = {name: subprocess.check_output(
        ["git", "show", f"{BASE}:src/cmd/{name}"], cwd=ROOT, text=True)
        for name in ("t_server.cc", "multidb.cc")}
    overlay(output, "cmd", originals)
    (output / ".emitted").write_text(BASE + "\n")


def check(group, pre):
    rows = []

    def run(binary, case, marker, expected=0):
        result = subprocess.run([str(binary), case], capture_output=True, text=True, timeout=120)
        passed = result.returncode == expected and marker in result.stdout + result.stderr
        rows.append(dict(binary=str(binary.relative_to(ROOT)), case=case,
                         sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                         expected_exit=expected, exit=result.returncode, required=marker,
                         passed=passed, stdout=result.stdout, stderr=result.stderr))
        print(result.stdout + result.stderr, end="", flush=True)
        print(f"{'PASS' if passed else 'FAIL'} receipt {binary.name} {case} exit={result.returncode}", flush=True)

    build = ROOT / "build"
    if group == "headers":
        for variant in ("", "db0-"):
            run(build / f"kvobj-header-{variant}unit", "all", "PASS header all:")
        for site in SITES:
            run(build / "flushfix-header-controls" / site / "unit", site,
                f"FAIL header {site}: 8-byte header equals kvobj_init_header", 1)
    else:
        for case in ("semantics", "memory-db0", "memory-multi", "memory-all"):
            run(build / "flushfix-unit", case, "PASS flushfix")
        if pre:
            for case in ("memory-db0", "memory-multi"):
                run(pre, case, "FAIL flushfix: FLUSHDB completes under RLIMIT_AS (uncaught allocation failure)", 1)
            run(pre, "memory-all", "PASS flushfix memory:")
    receipt = build / f"flushfix-{group}-proofs.json"
    receipt.write_text(json.dumps(rows, indent=2) + "\n")
    if not all(row["passed"] for row in rows):
        raise SystemExit(1)
    print(f"PASS flushfix {group}: {len(rows)}/{len(rows)} strict outcomes")


def live(args):
    # This mode is intentionally never called by the serverless checks. Mainline
    # owns scheduling and starts only this test's isolated, disposable server.
    import os
    import resource
    import signal
    import tempfile
    import time
    from _lib import Conn, encode
    from _gate_process import cpus, fields, stop_process
    from gate_measurements import ratio

    assert not set(cpus(args.server_cores)) & set(cpus(args.load_cores)), "CPU sets overlap"
    assert len(cpus(args.server_cores)) == 8, "use the gate's eight-core geometry"
    os.sched_setaffinity(0, cpus(args.load_cores))
    with tempfile.TemporaryDirectory(prefix="flushfix-live-", dir=ROOT / "build") as directory:
        path = Path(directory)
        command = ["taskset", "-c", args.server_cores, str(args.binary.resolve()),
                   "--port", str(args.port), "--shards", "16", "--ratio", ratio("correctness", 8),
                   "--thread-mode", args.mode, "--databases", str(args.databases),
                   "--save", "", "--appendonly", "no", "--maxmemory", "0", "--dir", str(path)]
        with (path / "server.log").open("wb") as log:
            process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log)
            connection = None
            try:
                for _ in range(1000):
                    assert process.poll() is None, "server exited before readiness"
                    try:
                        connection = Conn("127.0.0.1", args.port, timeout=60)
                        assert connection.must("PING") == b"PONG"
                        break
                    except OSError:
                        time.sleep(.02)
                assert connection is not None, "server never became ready"
                info = fields(connection.must("INFO", "SERVER"))
                assert int(info["process_id"]) == process.pid, "connected to an unrelated server"
                resource.prlimit(process.pid, resource.RLIMIT_CORE, (0, 0))
                db = 0 if args.databases == 1 else 15
                if db:
                    assert connection.must("SET", "sentinel", "other-db") == b"OK"
                    assert connection.must("SELECT", db) == b"OK"
                for first in range(0, args.keys, 64):
                    commands = [("SET", i.to_bytes(8, "little") + b"k" * (args.key_bytes - 8), "v")
                                for i in range(first, min(first + 64, args.keys))]
                    connection.raw(b"".join(encode(*command) for command in commands))
                    for _ in commands:
                        assert connection.read() == b"OK", "populate failed"
                assert connection.must("DBSIZE") == args.keys, "full keyspace never armed"
                pages = int(Path(f"/proc/{process.pid}/statm").read_text().split()[0])
                previous = resource.prlimit(process.pid, resource.RLIMIT_AS)
                cap = pages * os.sysconf("SC_PAGE_SIZE") + 2 * 1024 * 1024
                resource.prlimit(process.pid, resource.RLIMIT_AS, (cap, previous[1]))
                print(f"ARMED live: pid={process.pid} keys={args.keys} key_bytes={args.key_bytes} cap={cap}", flush=True)
                try:
                    reply = connection.must("FLUSHDB")
                except (EOFError, OSError):
                    if not args.expect_terminate:
                        raise AssertionError("FLUSHDB did not complete under RLIMIT_AS")
                    assert process.wait(timeout=10) == -signal.SIGABRT, "PRE did not abort in terminate"
                    assert "std::bad_alloc" in (path / "server.log").read_text(errors="replace"), \
                        "PRE aborted for a different reason"
                    print("PASS live negative control: armed FLUSHDB terminates with std::bad_alloc")
                    return
                assert not args.expect_terminate, "PRE survived: the live memory window did not discriminate"
                assert reply == b"OK", "FLUSHDB did not complete under RLIMIT_AS"
                assert connection.must("PING") == b"PONG" and connection.must("DBSIZE") == 0, \
                    "server died or FLUSHDB left keys under RLIMIT_AS"
                resource.prlimit(process.pid, resource.RLIMIT_AS, previous)
                if db:
                    assert connection.must("SELECT", 0) == b"OK"
                    assert connection.must("GET", "sentinel") == b"other-db", "other DB changed"
                print("PASS live flushfix: FLUSHDB completes under RLIMIT_AS")
            finally:
                if connection:
                    connection.close()
                stop_process(process)
                print((path / "server.log").read_text(errors="replace")[-4000:])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    emit = sub.add_parser("emit-header")
    emit.add_argument("site", choices=SITES)
    emit.add_argument("output", type=Path)
    old = sub.add_parser("emit-pre")
    old.add_argument("output", type=Path)
    checks = sub.add_parser("check")
    checks.add_argument("group", choices=("flush", "headers"))
    checks.add_argument("--pre", type=Path)
    live_parser = sub.add_parser("live", help="MAINLINE ONLY: boots an isolated server")
    live_parser.add_argument("--binary", type=Path, default=ROOT / "build/tomokv")
    live_parser.add_argument("--server-cores", default="112-119")
    live_parser.add_argument("--load-cores", default="120-127")
    live_parser.add_argument("--port", type=int, default=17953)
    live_parser.add_argument("--mode", choices=("1s", "2s"), required=True)
    live_parser.add_argument("--databases", type=int, choices=(1, 16), required=True)
    live_parser.add_argument("--keys", type=int, default=262144)
    live_parser.add_argument("--key-bytes", type=int, default=4096)
    live_parser.add_argument("--expect-terminate", action="store_true",
                             help="PRE only: require the armed flush to abort with std::bad_alloc")
    args = parser.parse_args()
    if args.action == "emit-header":
        emit_header(args.site, args.output)
    elif args.action == "emit-pre":
        emit_pre(args.output)
    elif args.action == "check":
        check(args.group, args.pre.resolve() if args.pre else None)
    else:
        assert args.keys > 0 and args.key_bytes >= 8
        live(args)
