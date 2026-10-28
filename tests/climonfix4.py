#!/usr/bin/env python3
"""CLIENT/PAUSE/MONITOR compatibility receipts, using the unchanged harness5 repros."""
import argparse
import contextlib
import json
import re
import select
import subprocess
import time
from pathlib import Path

from _lib import Conn, RespError
from redis_tcl import sha, stop

ROOT = Path(__file__).resolve().parents[1]
ROOTS = ("PAUSE-BLOCKED-COUNT", "PAUSE-CLIENT-EXEMPT", "PAUSE-MAY-REPLICATE",
         "PAUSE-SCRIPT-FLAGS", "MONITOR-SCRIPT-CMDS", "RESET-CLEARS-LIBNAME",
         "RESET-MONITOR-ECHO", "CLIENT-LIST-CMD-NAME", "CONNECTED-CLIENTS-LAG")


def wire(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "backslashreplace")
    if isinstance(value, RespError):
        return {"error": str(value)}
    if isinstance(value, list):
        return [wire(v) for v in value]
    return value


def read(c, timeout=2):
    # Do not poison Python's file object by timing out inside read(). The
    # unbuffered RESP reader consumes exactly one frame, including MONITOR lines.
    if not select.select([c.sock], [], [], timeout)[0]:
        return {"timeout": True}
    c.sock.settimeout(2)
    return wire(c.read())


@contextlib.contextmanager
def server(args, binary, mode, folder, databases=16):
    folder.mkdir(parents=True, exist_ok=True)
    argv = ["taskset", "-c", args.cores, str(binary), "--port", str(args.port),
            "--bind", "127.0.0.1", "--save", "", "--appendonly", "no", "--dir", str(folder),
            "--enable-debug-command", "yes"]
    if mode != "redis":
        argv += ["--thread-mode", mode, "--shards", "16", "--databases", str(databases),
                 "--net-io", args.engine]
        if mode == "2s":
            argv += ["--ratio", args.ratio]
    clients = {}
    def conn(name):
        if name not in clients:
            clients[name] = Conn("127.0.0.1", args.port, timeout=3, buffering=0)
        return clients[name]
    with (folder / "server.log").open("w") as log:
        process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            for _ in range(200):
                if process.poll() is not None:
                    raise RuntimeError(f"server exited: {folder / 'server.log'}")
                try:
                    probe = Conn("127.0.0.1", args.port, timeout=1, buffering=0)
                    assert probe.cmd("PING") == b"PONG"
                    probe.close()
                    break
                except OSError:
                    time.sleep(.025)
            else:
                raise RuntimeError("boot deadline")
            yield conn, argv
        finally:
            for c in clients.values():
                c.close()
            stop(process)


def repro(args, binary, mode, root, case):
    transcript = []
    with server(args, binary, mode, args.output / root / mode) as (conn, argv):
        for step in case["steps"]:
            row = dict(step)
            if "sleep" in step:
                time.sleep(step["sleep"])
            else:
                c = conn(step["c"])
                if "send" in step:
                    c.send(*step["send"])
                if "raw" in step:
                    c.raw(step["raw"].encode())
                if step.get("read", 1):
                    value = read(c, step.get("timeout", 2))
                    row["raw_reply"] = value
                    if isinstance(value, str):
                        for pattern, replacement in step.get("normalize", []):
                            value = re.sub(pattern, replacement, value)
                        # MONITOR has a volatile timestamp/address, but its DB,
                        # source (lua/client), command bytes and order are exact.
                        value = re.sub(r"^\d+\.\d+ \[(\d+) 127\.0\.0\.1:\d+\]", r"<time> [\1 <client>]", value)
                        value = re.sub(r"^\d+\.\d+ \[(\d+) lua\]", r"<time> [\1 lua]", value)
                    row["reply"] = value
            transcript.append(row)
    return {"argv": argv, "binary_sha256": sha(binary), "transcript": transcript}


def projection(result):
    return [x["reply"] for x in result["transcript"] if "reply" in x and x.get("compare", True)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--oracle", type=Path, default=Path("/home/user/Projects/redis74/src/redis-server"))
    p.add_argument("--cores", default="16-23")
    p.add_argument("--port", type=int, default=20200)
    p.add_argument("--ratio", default="6:2")
    p.add_argument("--engine", choices=("uring", "epoll"), default="uring")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--root", action="append", choices=ROOTS)
    args = p.parse_args()
    args.binary = args.binary.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    source = json.loads((ROOT / "docs/harness5/redis-tcl-repros.json").read_text())["cases"]
    results = {}
    for root in args.root or ROOTS:
        results[root] = {}
        for mode in ("redis", "2s", "1s"):
            result = repro(args, args.oracle if mode == "redis" else args.binary, mode, root, source[root])
            results[root][mode] = result
            if mode != "redis":
                result["verdict"] = "MATCH" if projection(result) == projection(results[root]["redis"]) else "DIFFERENT"
                print(root, mode, result["verdict"], flush=True)
            (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
