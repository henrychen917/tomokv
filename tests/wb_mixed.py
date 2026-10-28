#!/usr/bin/env python3
"""WB4.7/14: mixed reply paths and witnessed nondefault small-pipe hold/release."""
import argparse
from contextlib import closing
import select
import time
import _lib
from wb_policy import check_replies


def check_settings(admin, settings):
    info = _lib.info(admin, "WRITEBACK")
    for knob, value in settings.items():
        check_replies(admin.must("CONFIG", "GET", knob), [knob.encode(), str(value).encode()], knob)
        assert info[knob.replace("-", "_")] == str(value), knob


def retained_head(ready):
    assert not ready, "small complete pipe did not hold"


def self_test():
    from types import SimpleNamespace
    from unittest.mock import patch
    controls = [("leaked SKIP reply", lambda: check_replies([b"value", b"leak", b"end"],
                                                          [b"value", b"end"], "SKIP")),
                ("corrupted borrowed bytes", lambda: check_replies([b"bad", b"end"],
                                                                  [b"value", b"end"], "borrow")),
                ("ignored complete-pipe hold", lambda: retained_head(True))]
    for name, control in controls:
        try: control()
        except AssertionError as exc: print(f"CONTROL FAIL WB: {name}: {exc}")
        else: raise AssertionError(f"negative control passed: {name}")
    admin = SimpleNamespace(must=lambda *args: [args[2].encode(), b"16"])
    with patch.object(_lib, "info", return_value={"wb_small_pipe": "16"}):
        try: check_settings(admin, {"wb-small-pipe": 2})
        except AssertionError as exc: print(f"CONTROL FAIL WB: ignored boot knob: {exc}")
        else: raise AssertionError("ignored boot knob passed")


def run(args):
    with closing(_lib.Conn("127.0.0.1", args.port, timeout=5)) as admin:
        settings = {"wb-policy": args.policy, "wb-small-pipe": args.small,
                    "wb-complete-visits": args.visits}
        check_settings(admin, settings)
        key, blocked = "wb-mixed:value", "wb-mixed:block"
        old, new = b"old:" + bytes(range(256)) * 32, b"new:" + bytes(range(256)) * 32
        admin.must("SET", key, old)
        before = int(_lib.info(admin, "stats")["zc_sends"])
        with closing(_lib.Conn("127.0.0.1", args.port, timeout=5)) as conn:
            commands = [("GET", key), ("CLIENT", "REPLY", "SKIP"), ("GET", key),
                        ("MULTI",), ("GET", key), ("SET", key, new), ("GET", key), ("EXEC",),
                        ("CLIENT", "REPLY", "OFF"), ("GET", key), ("CLIENT", "REPLY", "ON"),
                        ("GET", key), ("DEBUG", "SLEEP", ".002"), ("ECHO", "mixed-end")]
            expected = [old, b"OK", b"QUEUED", b"QUEUED", b"QUEUED", [old, b"OK", new],
                        b"OK", new, b"OK", b"mixed-end"]
            conn.raw(b"".join(_lib.encode(*command) for command in commands))
            check_replies([conn.read() for _ in expected], expected, "borrow/MULTI/REPLY/SLEEP")
        assert int(_lib.info(admin, "stats")["zc_sends"]) > before, "borrowed sends never fired"
        targets = [("PING",), ("GET", key), ("WAIT", "0", "0"),
                   ("SCRIPT", "EXISTS", "a" * 40), ("FUNCTION", "LIST"),
                   ("BLPOP", blocked, ".005"),
                   ("XREAD", "BLOCK", "5", "STREAMS", "wb-mixed:stream", "$")]
        for target in targets:
            with closing(_lib.Conn("127.0.0.1", args.port, timeout=5)) as conn:
                commands = [("GET", key), ("CLIENT", "REPLY", "SKIP"), target, ("ECHO", "skip-end")]
                conn.raw(b"".join(_lib.encode(*command) for command in commands))
                check_replies([conn.read(), conn.read()], [new, b"skip-end"], f"SKIP {target[0]}")
        # Hold an actual second ROB operation at atomic publication. Blocking
        # commands are parser barriers and cannot establish a two-slot WB window.
        admin.must("SET", key, "tiny")
        admin.must("CONFIG", "SET", "atomic", "1")
        left, right, _, _ = _lib.cross_owner_pair(admin, "wb-mixed:hold")
        with closing(_lib.Conn("127.0.0.1", args.port, timeout=5)) as conn:
            assert admin.must("DEBUG", "ATOMIC-COMMIT-HOLD", "1") == b"OK"
            held = args.policy == 1 and args.small >= 2 and args.visits == 0
            try:
                conn.raw(_lib.encode("GET", key) + _lib.encode("MSET", left, "a", right, "b"))
                deadline = time.monotonic() + 5
                while int(_lib.info(admin, "stats")["atomic_inflight"]) == 0:
                    assert time.monotonic() < deadline, "held group never admitted"
                    time.sleep(.001)
                if held:
                    retained_head(bool(select.select([conn.sock], [], [], .03)[0]))
                else:
                    check_replies(conn.read(), b"tiny", "bounded/half head must progress")
            finally:
                assert admin.must("DEBUG", "ATOMIC-COMMIT-HOLD", "0") == b"OK"
            if held:
                check_replies(conn.read(), b"tiny", "unbounded head resumes")
            check_replies(conn.read(), b"OK", "held atomic tail resumes")
        print(f"PASS WB mixed policy={args.policy} S={args.small} D={args.visits}; borrowed sends, SKIP and hold/resume")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--policy", type=int)
    parser.add_argument("--small", type=int)
    parser.add_argument("--visits", type=int)
    args = parser.parse_args()
    self_test() if args.self_test else run(args)
