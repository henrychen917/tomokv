#!/usr/bin/env python3
"""Redis evidence for the script_apply unit's unchanged RESP/value assertions."""
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from _lib import Conn
from compat3_lib import equal, wire

work = ROOT / "build/datafix2/script-apply-oracle"
work.mkdir(exist_ok=True)
for port in range(33800, 33890):
    reserve = socket.socket()
    reserve.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        reserve.bind(("0.0.0.0", port))
        break
    except OSError as error:
        reserve.close()
        if error.errno != 98:
            raise
else:
    raise RuntimeError("no free assigned oracle port")
argv = ["taskset", "-c", "104", "/home/user/Projects/redis74/src/redis-server",
        "--port", str(port), "--bind", "127.0.0.1", "--save", "", "--appendonly", "no",
        "--dir", str(work)]
c = None
with (ROOT / "docs/datafix2/script-apply-oracle.log").open("w") as log:
    process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
    try:
        until = time.monotonic() + 5
        while time.monotonic() < until:
            assert process.poll() is None, "oracle failed to boot"
            try:
                c = Conn("127.0.0.1", port, buffering=0)
                equal(c.cmd("PING"), b"PONG", "oracle ready")
                break
            except OSError:
                if c:
                    c.close()
                c = None
                time.sleep(.02)
        assert c is not None, "oracle listener did not become ready"
        equal(c.cmd("SET", "apply-x", "B"), b"OK", "seed")
        script = "redis.call('GET',KEYS[2]); return redis.call('APPEND',KEYS[1],'S')"
        reply = c.cmd("EVAL", script, 2, "apply-x", "apply-y")
        value = c.cmd("GET", "apply-x")
        equal(reply, 2, "unchanged RESP integer :2")
        equal(value, b"BS", "unchanged read-modify-write image")
        result = dict(argv=argv, command=["EVAL", script, 2, "apply-x", "apply-y"],
                      reply=wire(reply), value=wire(value), passed=True,
                      internal_assertion="POST requires read|staged-write|modified (11); PRE requires read|staged-write (3). No wire expectation changed.")
        (ROOT / "docs/datafix2/script-apply-oracle.json").write_text(json.dumps(result, indent=2) + "\n")
    finally:
        if c:
            c.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        reserve.close()
print("PASS script_apply oracle: RESP :2 and value BS")
