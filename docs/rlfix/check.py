#!/usr/bin/env python3
"""Focused correctness runner. Owns exact child PIDs; CPUs 48-63, ports 25610/11 only."""
import argparse
import contextlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import _lib


@contextlib.contextmanager
def server(binary, output, mode=None, atomic=1):
    oracle = mode is None
    port, cores = (25611, "56") if oracle else (25610, "48-55")
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", port)) != 0, f"port {port} occupied"
    command = ["taskset", "-c", cores, str(binary.resolve()), "--port", str(port),
               "--bind", "127.0.0.1", "--save", "", "--appendonly", "no",
               "--dir", str(output.resolve()), "--enable-debug-command", "yes"]
    if oracle:
        command += ["--daemonize", "no"]
    else:
        command += ["--shards", "16", "--thread-mode", mode, "--read-local", "1",
                    "--atomic", str(atomic)]
        if mode == "2s":
            command += ["--ratio", "6:2"]
    label = "oracle" if oracle else f"{mode}-a{atomic}"
    (output / (label + ".command.json")).write_text(json.dumps(command) + "\n")
    with (output / (label + ".server.log")).open("w") as log:
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 20
            while True:
                assert proc.poll() is None, f"server exited: {label}"
                try:
                    c = _lib.Conn("127.0.0.1", port, timeout=1)
                    assert c.cmd("PING") == b"PONG"
                    c.close()
                    break
                except OSError:
                    assert time.monotonic() < deadline, "server boot deadline"
                    time.sleep(0.05)
            yield port
        finally:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise AssertionError(f"server TERM deadline: {label}")
            # io_uring can defer its last socket reference past process reap.
            # Require closure before reusing the port, with a bounded wait.
            close_deadline = time.monotonic() + 2
            while True:
                with socket.socket() as probe:
                    probe.settimeout(0.1)
                    if probe.connect_ex(("127.0.0.1", port)) != 0:
                        break
                assert time.monotonic() < close_deadline, f"port {port} still open"
                time.sleep(0.02)
            assert proc.returncode == 0, f"server exit {proc.returncode}: {label}"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("binary", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--cases", nargs="+", default=["miss"])
    p.add_argument("--atomics", nargs="+", type=int, default=[1])
    p.add_argument("--negative", action="store_true")
    p.add_argument("--batteries", action="store_true")
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    rows = []
    with server(Path("/home/user/Projects/redis74/src/redis-server"), a.output) as oracle:
        for mode in ("1s", "2s"):
            for atomic in a.atomics:
                with server(a.binary, a.output, mode, atomic) as port:
                    jobs = [(case, ["tests/rlfix.py", "127.0.0.1", str(port), "--case", case] +
                             (["--oracle-port", str(oracle)] if case == "miss" else []))
                            for case in a.cases]
                    if a.batteries:
                        jobs += [(name, [f"tests/{name}.py", "127.0.0.1", str(port)] + flags)
                                 for name, flags in (("ryow", []), ("atomic_ryow", ["--no-rate-assertions"]),
                                                     ("bplus", []), ("read_local_lane", []),
                                                     ("read_local_lane", ["--mget-fence"]))]
                    for i, (name, args) in enumerate(jobs):
                        command = ["taskset", "-c", "57-63", sys.executable] + args
                        label = f"{mode}-a{atomic}-{i}-{name}"
                        with (a.output / (label + ".log")).open("w") as log:
                            r = subprocess.run(command, cwd=ROOT, stdout=log,
                                               stderr=subprocess.STDOUT, timeout=300)
                        rows.append(dict(label=label, command=command, exit_code=r.returncode))
                        print(label, r.returncode, flush=True)
    (a.output / "receipt.json").write_text(json.dumps(rows, indent=2) + "\n")
    return any((row["exit_code"] == 0) if a.negative else (row["exit_code"] != 0) for row in rows)


if __name__ == "__main__":
    raise SystemExit(main())
