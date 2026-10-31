#!/usr/bin/env python3
"""Maintainer-only Redis adapter for the unchanged shared T6 storm workload.

Only --self-test is run by this lane. Normal invocation runs a benchmark.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace


def install(harness, redis_io_threads):
    harness.em.REDIS_IO_THREADS = redis_io_threads
    original = harness.run_arm

    def run_arm(args, block, seq, arm, binary, out):
        redis = harness.em.is_redis(binary)
        pick, counters = harness.em.pick_hot, harness.info_counters
        if redis:
            # Redis owns both keys on one execution thread. No DEBUG SHARDS or
            # Tomo-only INFO counters exist in the reference server.
            harness.em.pick_hot = lambda conn: (["exechot:0", "exechot:1"], [])
            harness.info_counters = lambda conn: {}
        try:
            record = original(args, block, seq, arm, binary, out)
        finally:
            harness.em.pick_hot, harness.info_counters = pick, counters
        record["server_kind"] = "redis" if redis else "tomokv"
        record["tomo_counters_available"] = not redis
        if redis:
            record["counters"] = {}
            record["redis_io_threads"] = redis_io_threads
        (out / f"b{block}-{seq}-{arm}" / "record.json").write_text(
            json.dumps(record, indent=1) + "\n")
        return record

    harness.run_arm = run_arm
    if hasattr(harness, "summarize"):
        summarize = harness.summarize

        def summary(records):
            result = summarize(records)
            redis_arms = sorted({r["arm"] for r in records if r.get("server_kind") == "redis"})
            if redis_arms:
                result += " | Tomo-only counters UNAVAILABLE on Redis arms " + ",".join(redis_arms)
            return result

        harness.summarize = summary


def self_test():
    """Serverless: the Redis branch never calls the Tomo geometry/counter APIs."""
    def pick(conn):
        assert conn == "tomokv"
        return ["a", "b"], [[0, 6], [1, 7]]

    def counters(conn):
        assert conn == "tomokv"
        return {"atomic_txn_order_violations": 0}

    fake = SimpleNamespace(em=SimpleNamespace(is_redis=lambda binary: binary == "redis", pick_hot=pick), info_counters=counters)

    def run(args, block, seq, arm, binary, out):
        (out / f"b{block}-{seq}-{arm}").mkdir()
        keys, geometry = fake.em.pick_hot(binary)
        counts = fake.info_counters(binary)
        assert (keys, geometry, counts) == ((["exechot:0", "exechot:1"], [], {}) if binary == "redis" else (["a", "b"], [[0, 6], [1, 7]], {"atomic_txn_order_violations": 0}))
        return dict(valid=True, counters=counts)

    fake.run_arm = run
    install(fake, 4)
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "build") as directory:
        for seq, binary in enumerate(("redis", "tomokv", "tomokv", "redis"), 1):
            row = fake.run_arm(None, 1, seq, "A", binary, Path(directory))
            assert row["tomo_counters_available"] == (binary == "tomokv")
            assert fake.em.pick_hot is pick and fake.info_counters is counters
    assert fake.em.REDIS_IO_THREADS == 4
    print("PASS Redis storm adapter (serverless ABBA dispatch and restoration)")


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--redis-io-threads", type=int, default=4)
    parser.add_argument("--harness", type=Path, default=Path("/home/user/Projects/calib/script-storm-merit.py"))
    args, rest = parser.parse_known_args()
    if args.self_test:
        self_test()
        return 0
    assert args.redis_io_threads > 0
    spec = importlib.util.spec_from_file_location("execfifo2_storm_harness", args.harness)
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    install(harness, args.redis_io_threads)
    sys.argv = [str(args.harness), *rest]
    return harness.main()


if __name__ == "__main__":
    raise SystemExit(main())
