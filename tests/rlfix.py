#!/usr/bin/env python3
"""RL4.3/RL4.4 live regressions; connects to an already booted armed server.

Usage: rlfix.py HOST PORT --case miss [--oracle-port PORT]
       rlfix.py HOST PORT --case delete
Boot with --read-local 1 --enable-debug-command yes, in either thread mode.
Every measured arm requires a preceding lane-served GET on a fresh connection.
"""
import argparse
import json
import select
import time

import _lib


def snapshot(c):
    stats = _lib.info(c, "stats")
    return {k: int(v) for k, v in stats.items()
            if (k.startswith("read_local_") or k in
                ("keyspace_hits", "keyspace_misses", "expired_keys")) and v.isdigit()}


def delta(before, after):
    return {k: after[k] - before[k] for k in before if after[k] != before[k]}


def expect(actual, expected, label):
    assert actual == expected, f"{label}: got {actual!r}, wanted {expected!r}"


def counted(d, expected):
    for key, value in expected.items():
        expect(d.get(key, 0), value, key)


def armed_connection(host, port, ctl, resp=2, oracle=False):
    for attempt in range(3):
        c = _lib.Conn(host, port)
        c.must("HELLO", resp)
        before = snapshot(ctl)
        expect(c.cmd("GET", "rlfix:arm"), b"armed", "arming GET")
        d = delta(before, snapshot(ctl))
        if oracle or d.get("read_local_hits", 0) == 1:
            return c
        c.close()
    raise AssertionError("lane failed to arm on three fresh connections")


def events(listener, count):
    out = []
    deadline = time.monotonic() + 3
    while len(out) < count:
        left = deadline - time.monotonic()
        assert left > 0 and select.select([listener.sock], [], [], left)[0], (
            f"keymiss notification window never opened: {out!r}, expected {count}")
        out.append(listener.read())
    # An unbuffered RESP reader makes readiness include every extra frame.
    while select.select([listener.sock], [], [], 0.05)[0]:
        out.append(listener.read())
    return out


def write_window(host, port, ctl, setup, frames, expected, inflight):
    for attempt in range(3):
        for command in setup:
            ctl.must(*command)
        c = armed_connection(host, port, ctl)
        try:
            before = snapshot(ctl)
            c.sock.sendall(b"".join(_lib.encode(*frame) for frame in frames))
            replies = [c.read() for _ in frames]
            d = delta(before, snapshot(ctl))
            expect(replies, expected, "same-connection replies/RYOW")
            held = d.get("read_local_fallback_inflight_write", 0)
            if held >= inflight or d.get("read_local_fallbacks", 0) != held:
                return d, replies
            # The owner can finish before the parser reaches a younger GET.
            # Reinsert the deleted values and re-arm a fresh ROB; never accept
            # such a run as a witness or relax its exact counter assertions.
            print(json.dumps(dict(rearm=attempt + 1, counters=d)), flush=True)
        finally:
            c.close()
    raise AssertionError("write window never opened on three fresh connections")


def misses(host, port, oracle=False):
    ctl = _lib.Conn(host, port)
    saved_notify = ctl.must("CONFIG", "GET", "notify-keyspace-events")[1]
    results = []
    try:
        if not oracle:
            expect(_lib.info(ctl, "server")["read_local"], "1", "armed server")
        ctl.must("DEBUG", "SET-ACTIVE-EXPIRE", 0)
        ctl.must("CONFIG", "SET", "notify-keyspace-events", "")
        ctl.must("SET", "rlfix:arm", "armed")
        ctl.must("SET", "rlfix:s", "value")
        ctl.must("DEL", "rlfix:l", "rlfix:missing")
        ctl.must("RPUSH", "rlfix:l", "list")
        for resp in (2, 3):
            for notify in (False, True):
                ctl.must("CONFIG", "SET", "notify-keyspace-events", "Em" if notify else "")
                listener = _lib.Conn(host, port, buffering=0)
                listener.must("SUBSCRIBE", "__keyevent@0__:keymiss")
                c = armed_connection(host, port, ctl, resp, oracle)
                try:
                    cases = (
                        ("get-missing", ("GET", "rlfix:missing"), None, 0, 1, 0, None),
                        ("mget-missing", ("MGET", "rlfix:s", "rlfix:missing", "rlfix:missing"),
                         [b"value", None, None], 1, 2, 0, None),
                        ("get-wrongtype", ("GET", "rlfix:l"),
                         _lib.RespError("WRONGTYPE Operation against a key holding the wrong kind of value"),
                         1, 0, 0, "typed"),
                        ("mget-wrongtype", ("MGET", "rlfix:l", "rlfix:s"),
                         [None, b"value"], 2, 0, 0, "typed"),
                        ("get-expired", ("GET", "rlfix:e"), None, 0, 1, 1, "expired"),
                        ("mget-expired", ("MGET", "rlfix:s", "rlfix:e"),
                         [b"value", None], 1, 1, 1, "expired"),
                    )
                    for label, command, reply, hits, miss, expired, reason in cases:
                        if expired:
                            ctl.must("SET", "rlfix:e", "expired", "PX", 20)
                            time.sleep(0.08)
                        before = snapshot(ctl)
                        got = c.cmd(*command)
                        d = delta(before, snapshot(ctl))
                        expect(got, reply, label)
                        counted(d, {"keyspace_hits": hits, "keyspace_misses": miss,
                                    "expired_keys": expired})
                        expected_events = [[b"message", b"__keyevent@0__:keymiss",
                                            command[-1].encode()]] * (miss if notify else 0)
                        observed_events = events(listener, len(expected_events))
                        expect(observed_events, expected_events, label + " notifications")
                        if not oracle:
                            mget = command[0] == "MGET"
                            local = reason is None and not notify
                            counted(d, {
                                "read_local_mget_local_hits" if mget else "read_local_hits": int(local),
                                "read_local_mget_fallbacks" if mget else "read_local_fallbacks": int(not local),
                                "read_local_keyspace_hits": hits if local else 0,
                                "read_local_keyspace_misses": miss if local else 0,
                                "read_local_fallback_missing": 0,
                            })
                            if not local:
                                fallback = ("context_keymiss_notify" if notify and
                                            (mget or reason is None) else reason)
                                prefix = "read_local_mget_fallback_" if mget else "read_local_fallback_"
                                counted(d, {prefix + fallback: 1})
                        row = dict(resp=resp, notify=notify, case=label, reply=repr(got),
                                   counters=d, events=repr(observed_events))
                        results.append(row)
                        print(json.dumps(row), flush=True)
                finally:
                    c.close()
                    listener.close()
        return results
    finally:
        ctl.must("CONFIG", "SET", "notify-keyspace-events", saved_notify)
        ctl.must("DEBUG", "SET-ACTIVE-EXPIRE", 1)
        ctl.close()


def deletes(host, port):
    ctl = _lib.Conn(host, port)
    saved_notify = ctl.must("CONFIG", "GET", "notify-keyspace-events")[1]
    try:
        expect(_lib.info(ctl, "server")["read_local"], "1", "armed server")
        ctl.must("CONFIG", "SET", "notify-keyspace-events", "")
        ctl.must("SET", "rlfix:arm", "armed")
        # Read keys must avoid the write shards: a concurrent owner deletion can
        # legitimately invalidate a probe of a different key in the same table.
        # Prove this geometry on this boot instead of accepting fewer local reads.
        shards = {}
        for key, shard, owner in _lib.probe_keys(ctl, "rlfix:delete", _lib.topology(ctl)):
            shards.setdefault(shard, key)
            if len(shards) == 6:
                break
        assert len(shards) == 6, "delete precision witness needs six distinct shards"
        a, b, *keys = shards.values()
        for key in keys:
            ctl.must("SET", key, key)
        for command in ("DEL", "UNLINK", "dEl", "uNlInK"):
            for broad in (False, True):
                write = (command, a, b) if broad else (command, a)
                frames = [("GET", key) for key in keys[:3]]
                frames += [write, ("GET", keys[3]), ("GET", a)]
                expected = [key.encode() for key in keys[:3]]
                expected += [2 if broad else 1, keys[3].encode(), None]
                d, replies = write_window(host, port, ctl,
                    [("SET", a, "old-a"), ("SET", b, "old-b")], frames, expected,
                    5 if broad else 1)
                # The final GET is an exact same-connection RYOW witness, not
                # an independent connection's eventual view of the deletion.
                counted(d, {"read_local_hits": 0 if broad else 4,
                            "read_local_keyspace_hits": 0 if broad else 4,
                            "read_local_keyspace_misses": 0,
                            "read_local_fallbacks": 5 if broad else 1,
                            "read_local_fallback_inflight_write": 5 if broad else 1,
                            "read_local_write_ring_records": 0 if broad else 1,
                            "keyspace_hits": 4, "keyspace_misses": 1})
                print(json.dumps(dict(command=command, broad=broad, counters=d,
                                      replies=repr(replies))), flush=True)
            # An older read of the deleted key must execute before the delete.
            frames = [("GET", a), (command, a), ("GET", a)]
            d, _ = write_window(host, port, ctl, [("SET", a, "old-a")], frames,
                                [b"old-a", 1, None], 2)
            counted(d, {"read_local_hits": 0, "read_local_fallback_inflight_write": 2})
    finally:
        ctl.must("CONFIG", "SET", "notify-keyspace-events", saved_notify)
        ctl.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--case", choices=("miss", "delete"), required=True)
    parser.add_argument("--oracle-port", type=int)
    args = parser.parse_args()
    if args.case == "delete":
        deletes(args.host, args.port)
        print("rlfix delete: PASS")
        return
    rows = misses(args.host, args.port)
    if args.oracle_port:
        oracle = misses(args.host, args.oracle_port, oracle=True)
        for actual, reference in zip(rows, oracle):
            for row in (actual, reference):
                row["counters"] = {k: v for k, v in row["counters"].items()
                                   if not k.startswith("read_local_")}
            expect(actual, reference, "Redis 7.4 differential")
    print("rlfix miss: PASS")


if __name__ == "__main__":
    main()
