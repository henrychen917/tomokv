#!/usr/bin/env python3
"""WB4.7/14: mixed reply paths and witnessed nondefault small-pipe hold/release."""
import argparse
from contextlib import closing
import select
import time
import _lib
from _client_wait import wait_client_state
from wb_policy import check_replies


def run(args):
    with closing(_lib.Conn("127.0.0.1", args.port, timeout=5)) as admin:
        settings = {"wb-policy": args.policy, "wb-small-pipe": args.small,
                    "wb-complete-visits": args.visits}
        info = _lib.info(admin, "WRITEBACK")
        for knob, value in settings.items():
            check_replies(admin.must("CONFIG", "GET", knob), [knob.encode(), str(value).encode()], knob)
            assert info[knob.replace("-", "_")] == str(value), knob
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
        # A blocked second ROB slot establishes the incomplete pipeline. D=0/S>=2
        # must retain its tiny head; S=0 or a bounded D must eventually send it.
        admin.must("SET", key, "tiny")
        admin.must("DEL", blocked)
        with closing(_lib.Conn("127.0.0.1", args.port, timeout=5)) as conn:
            ident = conn.must("CLIENT", "ID")
            conn.raw(_lib.encode("GET", key) + _lib.encode("BLPOP", blocked, "0"))
            try:
                wait_client_state(admin, ident, "blocked")
                held = args.policy == 1 and args.small >= 2 and args.visits == 0
                if held:
                    assert not select.select([conn.sock], [], [], .03)[0], "small complete pipe did not hold"
                else:
                    check_replies(conn.read(), b"tiny", "bounded/half head must progress")
            finally:
                assert admin.must("LPUSH", blocked, "release") == 1
            if held:
                check_replies(conn.read(), b"tiny", "unbounded head resumes")
            check_replies(conn.read(), [blocked.encode(), b"release"], "blocked tail resumes")
        print(f"PASS WB mixed policy={args.policy} S={args.small} D={args.visits}; borrowed sends, SKIP and hold/resume")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--policy", type=int, required=True)
    parser.add_argument("--small", type=int, required=True)
    parser.add_argument("--visits", type=int, required=True)
    run(parser.parse_args())
