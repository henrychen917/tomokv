#!/usr/bin/env python3
"""Bounded replay of the harness5 source reproductions; no performance work."""
import argparse
import json
import socket
import subprocess
import time
from pathlib import Path
from _lib import Conn, RespError
from redis_tcl import stop, sha

ROOT = Path(__file__).resolve().parents[1]
ROOTS = ("BLOCK-WAKE-RENAME-SORTSTORE", "BLOCK-STREAM-REMOVED-NO-UNBLOCK",
         "BLOCK-MOVE-WRONGTYPE-STRANDS", "BLOCK-WAKE-ORDER-MULTI", "BLOCK-CHAIN-ASYNC",
         "MULTI-XREADGROUP-BLOCK-HANG", "INFO-TOTAL-BLOCKING-KEYS", "SLOWLOG-BLOCKED-NOT-LOGGED")


def wire(x):
    if isinstance(x, bytes): return x.decode("utf-8", "backslashreplace")
    if isinstance(x, RespError): return {"error": str(x)}
    if isinstance(x, list): return [wire(v) for v in x]
    return x


def replay(args, binary, mode, name, case):
    folder = args.output / name / mode
    folder.mkdir(parents=True, exist_ok=True)
    argv = ["taskset", "-c", args.cores, str(binary), "--port", str(args.port),
            "--bind", "127.0.0.1", "--save", "", "--appendonly", "no", "--dir", str(folder),
            "--enable-debug-command", "yes"]
    if mode != "redis":
        argv += ["--thread-mode", mode, "--shards", "16", "--databases", "16", "--net-io", args.engine]
        if mode == "2s": argv += ["--ratio", "6:2"]
    clients = {}
    transcript = []
    with (folder / "server.log").open("w") as log:
        proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            for _ in range(200):
                if proc.poll() is not None: raise RuntimeError("server exited")
                try:
                    c = Conn("127.0.0.1", args.port, timeout=1, buffering=0)
                    assert c.cmd("PING") == b"PONG"
                    c.close()
                    break
                except OSError: time.sleep(.025)
            else: raise RuntimeError("boot deadline")
            for step in case["steps"]:
                row = dict(step)
                if "sleep" in step:
                    time.sleep(step["sleep"])
                else:
                    ident = step["c"]
                    if ident not in clients:
                        clients[ident] = Conn("127.0.0.1", args.port, timeout=2, buffering=0)
                    c = clients[ident]
                    if "send" in step: c.send(*step["send"])
                    if "raw" in step: c.raw(step["raw"].encode())
                    if step.get("read", 1):
                        c.sock.settimeout(step.get("timeout", 2))
                        try: row["reply"] = wire(c.read())
                        except (TimeoutError, socket.timeout): row["reply"] = {"timeout": True}
                transcript.append(row)
        finally:
            for c in clients.values(): c.close()
            stop(proc)
    return dict(argv=argv, sha256=sha(binary), transcript=transcript)


def projection(root, result):
    replies = [x["reply"] for x in result["transcript"] if "reply" in x and x.get("compare", True)]
    if root == "INFO-TOTAL-BLOCKING-KEYS":
        fields = dict(line.split(":", 1) for line in replies[-1].splitlines() if ":" in line)
        return {k: fields.get(k) for k in ("total_blocking_keys", "total_blocking_keys_on_nokey")}
    return replies


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--oracle", type=Path, default=Path("/home/user/Projects/redis74/src/redis-server"))
    p.add_argument("--cores", default="16-23")
    p.add_argument("--port", type=int, default=20400)
    p.add_argument("--engine", choices=("uring", "epoll"), default="uring")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--root", action="append", choices=ROOTS)
    args = p.parse_args()
    args.binary = args.binary.resolve(); args.output = args.output.resolve()
    source = json.loads((ROOT / "docs/harness5/redis-tcl-repro-cases.json").read_text())
    results = {}
    for root in args.root or ROOTS:
        name = next(k for k in source if k.endswith(root))
        results[root] = {}
        for mode in ("redis", "2s", "1s"):
            results[root][mode] = replay(args, args.oracle if mode == "redis" else args.binary,
                                         mode, root, source[name])
            if mode != "redis":
                different = projection(root, results[root][mode]) != projection(root, results[root]["redis"])
                print(root, mode, "DIFFERENT" if different else "MATCH", flush=True)
        (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__": main()
