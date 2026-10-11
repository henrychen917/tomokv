#!/usr/bin/env python3
"""Run one client battery against one fresh server and record both exit codes.

Receipt generator for the rlresize lane. It starts the server binary with the given argv
(pinned by taskset), waits for its listener, runs the client command (pinned by taskset),
then stops a surviving server with SIGTERM. A server lost to a signal is recorded as a
negative exit code (SIGABRT = -6), exactly like the txnfix2 controls' runs.json.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time


def listening(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--server-cpus", required=True)
    parser.add_argument("--client-cpus", required=True)
    parser.add_argument("--cwd", required=True, help="directory the client command runs in")
    parser.add_argument("--out", required=True, help="receipt directory (created)")
    parser.add_argument("--server-arg", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--gdb", action="store_true",
                        help="run the server under gdb -batch and print the crashing stack")
    parser.add_argument("client", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    client = args.client[1:] if args.client[:1] == ["--"] else args.client
    if not client:
        raise SystemExit("missing client command")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    if listening(args.port):
        raise SystemExit("port %d is already in use" % args.port)
    binary = str(Path(args.binary).resolve())
    debugger = ["gdb", "-nx", "-batch", "-iex", "set auto-load off",
                "-ex", "set pagination off", "-ex", "handle SIGTERM nostop noprint pass",
                "-ex", "handle SIGPIPE nostop noprint pass", "-ex", "run", "-ex", "bt 12",
                "--args"] if args.gdb else []
    server_cmd = ["taskset", "-c", args.server_cpus] + debugger + [
        binary, "--bind", "127.0.0.1", "--port", str(args.port)] + args.server_arg
    client_cmd = ["taskset", "-c", args.client_cpus] + client
    started = time.monotonic()
    with open(out / "server.log", "wb") as server_log:
        server = subprocess.Popen(server_cmd, stdout=server_log, stderr=subprocess.STDOUT,
                                  cwd=str(out))
    deadline = time.monotonic() + 30
    while not listening(args.port):
        if server.poll() is not None or time.monotonic() > deadline:
            raise SystemExit("server did not start; see %s" % (out / "server.log"))
        time.sleep(0.05)
    with open(out / "test.log", "wb") as test_log:
        try:
            test = subprocess.run(client_cmd, stdout=test_log, stderr=subprocess.STDOUT,
                                  cwd=args.cwd, timeout=args.timeout)
            test_code = test.returncode
        except subprocess.TimeoutExpired:
            test_code = "timeout"
    seconds = time.monotonic() - started
    server_alive = server.poll() is None
    if server_alive:
        server.send_signal(signal.SIGTERM)
        try:
            server.wait(timeout=60)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
    receipt = dict(
        arm=args.label,
        server=server_cmd,
        command=client_cmd,
        cwd=args.cwd,
        sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
        exit_code=test_code,
        server_alive_after_test=server_alive,
        server_exit_code=server.returncode,
        stopped_by_runner=server_alive,
        seconds=round(seconds, 3),
    )
    (out / "run.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
