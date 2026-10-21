#!/usr/bin/env python3
"""Supplement the actual gate runs with the unchanged N3/N4 corpus on Redis 7.4."""
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "oracle"
BINARY = Path("/home/user/Projects/redis74/src/redis-server")
sys.path.insert(0, str(ROOT / "tests"))
from respcompat import limits_row, verify_oracle


def main():
    OUT.mkdir(exist_ok=True)
    endpoint = ("127.0.0.1", 22802)
    with socket.socket() as guard:
        guard.bind(endpoint)
    with tempfile.TemporaryDirectory(dir=ROOT / "build/ntfix5", prefix="oracle-") as directory:
        command = ["taskset", "-c", "80-87", str(BINARY), "--bind", endpoint[0],
                   "--port", str(endpoint[1]), "--save", "", "--appendonly", "no",
                   "--protected-mode", "no", "--dir", directory]
        with (OUT / "server.log").open("w") as log:
            server = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 10
                while True:
                    assert server.poll() is None, "oracle exited during startup"
                    try:
                        with socket.create_connection(endpoint, timeout=.2):
                            break
                    except OSError:
                        assert time.monotonic() < deadline, "oracle boot deadline"
                        time.sleep(.05)
                verify_oracle(endpoint)
                limits_row(endpoint, "preauth")
                limits_row(endpoint, "frontier")
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
            assert server.returncode == 0, server.returncode
        (OUT / "result.json").write_text(json.dumps(dict(
            command=command, binary_sha256=hashlib.sha256(BINARY.read_bytes()).hexdigest(),
            returncode=server.returncode, transport="TCP", preauth_exact_cases=23,
            frontier_exact_cases=4), indent=2) + "\n")


if __name__ == "__main__":
    main()
