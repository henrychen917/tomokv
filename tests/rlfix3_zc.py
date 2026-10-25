#!/usr/bin/env python3
"""RL4.11: the reported lane borrow capability must describe actual replies.

Boots belong to gate.sh. This battery runs in both modes/engines with read-local
0 and 1. All threshold/venue checks run before checking the new capability, so
PRE records the original behaviour and then fails on the missing CONFIG field.
No timings or throughput estimates are collected.
"""
import sys

from _lib import Conn, RespError, info


def main():
    host, port = sys.argv[1], int(sys.argv[2])
    c, observer = Conn(host, port), Conn(host, port)
    try:
        armed = int(info(observer, "server")["read_local"])
        original = c.cmd("CONFIG", "GET", "zc-min")[1]
        try:
            for size in (1024, 16384, 262144):
                value = bytes(range(256)) * (size // 256)
                assert c.cmd("SET", "rlfix3:zc", value) == b"OK"
                # Complete the initial arming transient before taking counters.
                assert c.cmd("GET", "rlfix3:zc") == value
                for threshold in (0, size, size + 1):
                    assert c.cmd("CONFIG", "SET", "zc-min", threshold) == b"OK"
                    assert c.cmd("CONFIG", "GET", "zc-min") == [b"zc-min", str(threshold).encode()]
                    before = info(observer, "stats")
                    for _ in range(4):
                        assert c.cmd("GET", "rlfix3:zc") == value
                    after = info(observer, "stats")
                    hits = int(after["read_local_hits"]) - int(before["read_local_hits"])
                    sends = int(after["zc_sends"]) - int(before["zc_sends"])
                    assert hits == (4 if armed else 0), (size, threshold, hits)
                    assert (sends > 0) == (not armed and threshold == size), (size, threshold, sends)
                    print(f"read_local={armed} bytes={size} zc_min={threshold} lane_hits={hits} zc_sends={sends}", flush=True)
            # Owner fallback still honours the live threshold while the lane is armed.
            assert c.cmd("CONFIG", "SET", "zc-min", 1024) == b"OK"
            assert c.cmd("WATCH", "rlfix3:zc") == b"OK"
            before = info(observer, "stats")
            assert c.cmd("GET", "rlfix3:zc") == value
            after = info(observer, "stats")
            assert int(after["zc_sends"]) > int(before["zc_sends"]), "WATCH owner fallback must borrow"
            assert c.cmd("UNWATCH") == b"OK"
            print("WATCH owner fallback borrowed", flush=True)
            # Collect every capability observation on PRE too: a missing GET
            # field must not prevent the wildcard and immutable-state legs.
            failures = []
            def check(name, condition, observed):
                print(f"capability {name}: {'PASS' if condition else 'FAIL'} {observed!r}", flush=True)
                if not condition: failures.append((name, observed))
            expected = [b"zc-min-read-local", b"0"]
            result = c.cmd("CONFIG", "GET", "zc-min-read-local")
            check("GET", result == expected, result)
            wildcard = c.cmd("CONFIG", "GET", "zc-min*")
            check("wildcard", dict(zip(wildcard[::2], wildcard[1::2])) ==
                  {b"zc-min": b"1024", b"zc-min-read-local": b"0"}, wildcard)
            result = c.cmd("CONFIG", "SET", "zc-min-read-local", 1)
            check("immutable error", isinstance(result, RespError) and b"immutable" in result.message, result)
            result = c.cmd("CONFIG", "GET", "zc-min-read-local")
            check("unchanged after SET", result == expected, result)
            assert not failures, failures
            print("RL4.11 PASS: exact threshold, lane venue, owner fallback and read-only capability")
        finally:
            assert c.cmd("CONFIG", "SET", "zc-min", original) == b"OK"
            c.cmd("UNWATCH")
    finally:
        c.close()
        observer.close()


if __name__ == "__main__":
    main()
