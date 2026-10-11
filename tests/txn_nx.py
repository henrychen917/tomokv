#!/usr/bin/env python3
"""Repeated RENAMENX winner/source conservation at the boot's atomic setting.

EXEC is isolated at both settings. Bare groups are isolated at atomic=1;
--bare also permits the existing atomic=0 negative control, without changing
the boot's setting or treating its anomalies as a successful result.
"""
import argparse
import json
import threading
import time

import _lib


def geometry(admin):
    names = [f"txn-nx:{time.time_ns()}:{i}" for i in range(256)]
    rows = admin.must("DEBUG", "SHARDS", *names)
    for i, (shard, owner) in enumerate(rows):
        same = next((j for j in range(i + 1, len(rows)) if rows[j][0] == shard), None)
        other = next((j for j, row in enumerate(rows) if row[1] != owner), None)
        if same is not None and other is not None:
            keys = [names[i], names[same], names[other]]
            proof = admin.must("DEBUG", "SHARDS", *keys)
            assert proof == [rows[i], rows[same], rows[other]]
            return keys, proof
    raise AssertionError("need two source keys on one shard and a destination on another owner")


def race(args, admin, transactional):
    keys, proof = geometry(admin)
    start = threading.Barrier(3, timeout=10)
    finish = threading.Barrier(3, timeout=10)
    replies = [None, None]
    errors = []
    failures = []
    completed = 0

    def abort():
        start.abort()
        finish.abort()

    def contender(index):
        client = None
        try:
            client = _lib.Conn(args.host, args.port, timeout=10)
            frame = _lib.encode("RENAMENX", keys[index], keys[2])
            if transactional:
                frame = _lib.encode("MULTI") + frame + _lib.encode("EXEC")
            for _ in range(args.rounds):
                start.wait()
                client.raw(frame)
                if transactional:
                    assert client.read() == b"OK"
                    assert client.read() == b"QUEUED"
                    value = client.read()
                    assert isinstance(value, list) and len(value) == 1, value
                    replies[index] = value[0]
                else:
                    replies[index] = client.read()
                finish.wait()
        except Exception as exc:
            errors.append(f"contender {index}: {exc!r}")
            abort()
        finally:
            if client:
                client.close()

    threads = [threading.Thread(target=contender, args=(i,), daemon=True) for i in range(2)]
    for thread in threads:
        thread.start()
    try:
        for iteration in range(args.rounds):
            assert admin.must("MSET", keys[0], "winner-a", keys[1], "winner-b") == b"OK"
            admin.must("DEL", keys[2])
            start.wait()
            finish.wait()
            values = admin.must("MGET", *keys)
            valid = ((replies == [1, 0] and values == [None, b"winner-b", b"winner-a"]) or
                     (replies == [0, 1] and values == [b"winner-a", None, b"winner-b"]))
            completed += 1
            if not valid:
                failure = dict(iteration=iteration, replies=list(replies), values=values)
                failures.append(failure)
                if len(failures) <= 8:
                    print("FAIL", failure, flush=True)
    except Exception as exc:
        errors.append(f"controller: {exc!r}")
        abort()
    finally:
        for thread in threads:
            thread.join(timeout=10)
    result = dict(transactional=transactional, geometry=proof, rounds=args.rounds,
                  completed=completed, failures=len(failures), examples=failures[:8],
                  errors=errors, threads_alive=any(t.is_alive() for t in threads))
    print(json.dumps(result, default=repr), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--rounds", type=int, default=8192)
    parser.add_argument("--bare", action="store_true")
    args = parser.parse_args()
    assert args.rounds > 0
    admin = _lib.Conn(args.host, args.port, timeout=10)
    try:
        atomic = int(admin.must("CONFIG", "GET", "atomic")[1])
        print(f"atomic={atomic}", flush=True)
        kinds = [False] if args.bare else ([True, False] if atomic else [True])
        results = [race(args, admin, kind) for kind in kinds]
        return int(any(r["failures"] or r["errors"] or r["threads_alive"] or
                       r["completed"] != r["rounds"] for r in results))
    finally:
        admin.close()


if __name__ == "__main__":
    raise SystemExit(main())
