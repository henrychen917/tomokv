#!/usr/bin/env python3
"""O7 engagement/reply-order witness against an externally started server; never boots one.

overlap_reply.py HOST PORT engaged|off
Use engaged for POST 2s/overlap=1; off for PAD, overlap=0, or 1s. Requires DEBUG enabled,
key/client LB disabled and flip-auto=0, as in the correctness gate's fixed 16-shard geometry.
Each failed arming attempt creates fresh connections and keys. Missing engagement is a FAIL.
"""
import argparse
import concurrent.futures
import threading
import time

import _lib


NAMES = ("overlap_reply_early_posts", "overlap_reply_early_submits")


def counters(conn):
    info = _lib.info(conn, "server")
    if info["overlap"] == "1":
        for name in NAMES:
            if name not in info:
                raise AssertionError("missing O7 witness: " + name)
    return {name: int(info.get(name, 0)) for name in NAMES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("expect", choices=("engaged", "off"))
    args = parser.parse_args()
    ctl = _lib.Conn(args.host, args.port, timeout=15)
    try:
        info = _lib.info(ctl, "server")
        for name in ("key_lb", "client_lb", "flip_auto"):
            if int(info[name]) != 0:
                raise AssertionError("fixed witness topology requires " + name + "=0")
        if args.expect == "engaged" and (info["thread_mode"], info["overlap"]) != ("2s", "1"):
            raise AssertionError("engagement requires 2s/overlap=1")
        if info.get("reorder_retired") != "1":
            raise AssertionError("retired reorder must stay retired")

        baseline = counters(ctl)
        final = baseline
        for attempt in range(4):
            # INCR always visits the owner even with read-local armed. Alternate GET verifies
            # RYOW and reply order across more than two ROB wraps on every fresh connection.
            prefix = "o7:%d:%d:" % (time.time_ns(), attempt)
            keys = [prefix + str(index) for index in range(16)]
            start = threading.Barrier(len(keys))

            def worker(key):
                conn = _lib.Conn(args.host, args.port, timeout=15)
                try:
                    if conn.must("SET", key, "0") != b"OK":
                        raise AssertionError("seed failed")
                    start.wait(timeout=15)
                    for turn in range(24):
                        commands, expected = [], []
                        for offset in range(4):
                            value = turn * 4 + offset + 1
                            commands += [("INCR", key), ("GET", key)]
                            expected += [value, str(value).encode()]
                        conn.raw(b"".join(_lib.encode(*command) for command in commands))
                        actual = [conn.read() for _ in expected]
                        if actual != expected:
                            raise AssertionError("ordered INCR/GET replies differ: %r" % actual)
                finally:
                    conn.close()

            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(keys)) as pool:
                    list(pool.map(worker, keys))
                final = counters(ctl)
            finally:
                ctl.must("DEL", *keys)
            delta = {name: final[name] - baseline[name] for name in NAMES}
            if args.expect == "engaged" and any(delta.values()):
                break
            if args.expect == "off" and any(delta.values()):
                raise AssertionError("disabled O7 engaged: %r" % delta)
        if args.expect == "engaged" and not any(delta.values()):
            raise AssertionError("O7 window never opened on four fresh attempts: %r" % delta)
        print("PASS overlap reply %s: %r" % (args.expect, delta))
    finally:
        ctl.close()


if __name__ == "__main__":
    main()
