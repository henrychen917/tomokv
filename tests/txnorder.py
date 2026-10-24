#!/usr/bin/env python3
"""Version-order regression rows a-d; connects only to an owner-managed boot.

Every POST window has a required witness. --pre runs the semantic checks that
the old binary can express; absence of new instrumentation is never evidence
that the old mechanism failed. A PRE pass invalidates that negative control.
"""
import argparse
import collections
import concurrent.futures
import json
import threading
import time

import _lib
from txniso import Battery


# AT4.12: known contention refusals, not arbitrary TRYAGAIN/BUSY errors.
SCRIPT_REFUSALS = {
    b"TRYAGAIN Cross-shard script conflicted, retry": "TRYAGAIN",
    b"BUSY Cross-shard script snapshot window is full": "BUSY",
}


class OrderBattery(Battery):
    def __init__(self, args):
        super().__init__(args)
        self.atomic = int(self.admin.must("CONFIG", "GET", "atomic")[1])

    def counter(self, name):
        value = self.stats().get(name)
        assert value is not None, "missing counter " + name
        return int(value)

    def snapshot(self):
        return {k: int(v) for k, v in self.stats().items()
                if k.startswith(("atomic_txn_", "atomic_group_"))}

    def delta(self, before, name):
        return self.counter(name) - before.get(name, 0)

    def clean(self, before):
        if not self.args.pre:
            assert self.delta(before, "atomic_txn_dooms") == 0, "plain writer cancelled EXEC"
            assert self.delta(before, "atomic_group_dooms") == 0, "plain writer cancelled group"
        for name in ("atomic_txn_order_violations", "atomic_exec_order_late", "atomic_gauge_underflows"):
            if self.args.pre and name == "atomic_txn_order_violations":
                continue  # PRE has no version-order instrumentation; exact data remains mandatory.
            assert self.counter(name) == 0, (name, self.counter(name))

    def report(self, label, before, **values):
        values.update(row=label, mode=self.args.mode, atomic=self.atomic,
                      counters={k: v - before.get(k, 0) for k, v in self.snapshot().items()})
        print(json.dumps(values, sort_keys=True), flush=True)

    def owner_keys(self, count, per_owner=1):
        names = [f"txnorder:{time.time_ns()}:{i}" for i in range(4096)]
        geometry = self.admin.must("DEBUG", "SHARDS", *names)
        by_owner = collections.defaultdict(list)
        for key, (shard, owner) in zip(names, geometry):
            by_owner[owner].append(key)
        assert len(by_owner) >= count, ("required executor owners", count, sorted(by_owner))
        keys = [key for owner in sorted(by_owner)[:count] for key in by_owner[owner][:per_owner]]
        actual = self.admin.must("DEBUG", "SHARDS", *keys)
        assert len({row[1] for row in actual}) == count, actual
        return keys

    def storm(self, clients, seconds=None, movers=False):
        a, b = self.pair()
        self.admin.must("MSET", a, 0, b, 0)
        before = self.snapshot()
        jobs = clients + 16 + (2 if movers else 0)
        start = threading.Barrier(jobs)
        deadline = [0.0]
        move_keys = []
        if movers:
            for kind in ("set", "list"):
                src, dst = self.pair()
                self.admin.must("SADD" if kind == "set" else "RPUSH", src, "token")
                move_keys.append((kind, src, dst))

        def run_exec(index):
            c = self.conn(timeout=5)
            start.wait(10)
            count = 0
            while (time.monotonic() < deadline[0]) if seconds else (count < 2000):
                reply = self.transaction(c, [("INCR", a), ("INCR", b), ("GET", a)])
                assert isinstance(reply, list) and len(reply) == 3 and reply[2] == str(reply[0]).encode(), reply
                count += 1
            return count

        def run_plain(index):
            c = self.conn(timeout=5)
            key = (a, b)[index // 8]
            start.wait(10)
            count = 0
            while (time.monotonic() < deadline[0]) if seconds else (count < 5000):
                for _ in range(4):
                    c.send("INCR", key)
                for _ in range(4):
                    assert isinstance(c.read(), int)
                    count += 1
            return count

        def run_mover(spec):
            kind, src, dst = spec
            c = self.conn(timeout=5)
            start.wait(10)
            count = 0
            while time.monotonic() < deadline[0]:
                if kind == "set":
                    assert c.must("SMOVE", src, dst, "token") == 1
                else:
                    assert c.must("RPOPLPUSH", src, dst) == b"token"
                src, dst = dst, src
                count += 1
            return count

        # Publish the common end before any worker can cross the barrier.
        deadline[0] = time.monotonic() + (seconds or 120)
        with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
            ex = [pool.submit(run_exec, i) for i in range(clients)]
            plain = [pool.submit(run_plain, i) for i in range(16)]
            moved = [pool.submit(run_mover, spec) for spec in move_keys]
            executions = sum(f.result(timeout=150) for f in ex)
            increments = [f.result(timeout=150) for f in plain]
            deliveries = [f.result(timeout=20) for f in moved]
        expected = [executions + sum(increments[:8]), executions + sum(increments[8:])]
        assert self.admin.must("MGET", a, b) == [str(v).encode() for v in expected], expected
        self.clean(before)
        if not self.args.pre:
            assert self.delta(before, "atomic_txn_executed") == executions
        if seconds is None and clients == 1 and not self.args.pre:
            assert self.delta(before, "atomic_txn_attempts") == 2000, "not every EXEC used one attempt"
            assert self.delta(before, "atomic_txn_retries") == 0, "plain writers re-executed EXEC"
        elif seconds is None and clients != 1:
            assert executions == 8000
            if not self.args.pre:
                assert self.delta(before, "atomic_txn_retries") == (
                    self.delta(before, "atomic_txn_wounds") + self.delta(before, "atomic_txn_blind_restarts"))
        if not self.atomic and not self.args.pre:
            assert self.delta(before, "atomic_txn_blind_restarts") == 0
        if not self.args.pre:
            assert self.delta(before, "atomic_txn_writer_waits") > 0, "storm never encountered a claim"
        for kind, src, dst in move_keys:
            values = [self.admin.must("SMEMBERS", k) if kind == "set" else
                      self.admin.must("LRANGE", k, 0, -1) for k in (src, dst)]
            assert values[0] + values[1] == [b"token"], values
        self.report("d" if seconds else f"a{1 if clients == 1 else 2}", before,
                    executions=executions, plain=increments, final=expected, deliveries=deliveries)

    def hot(self):
        self.storm(1)
        self.storm(4)

    def starvation(self):
        keys = self.owner_keys(self.args.owners, 2)
        quiet = [self.same_shard(keys[i]) for i in (0, 2)]
        self.admin.must("MSET", *[part for key in keys + quiet for part in (key, 0)])
        stop = threading.Event()
        ready = threading.Barrier(25)
        before = self.snapshot()
        counts = collections.Counter()
        lock = threading.Lock()
        latencies = []
        bystander_ready = threading.Event()
        min_bystander_samples = 20
        completed_execs = [0]

        def worker(index):
            c = self.conn(timeout=5)
            selected = [keys[index % len(keys)], keys[(index + 3) % len(keys)]]
            ready.wait(10)
            while not stop.is_set():
                if index < 8:
                    reply = self.transaction(c, [("INCR", key) for key in selected])
                    assert len(reply) == 2 and all(isinstance(v, int) for v in reply), reply
                    with lock:
                        counts.update(selected)
                        completed_execs[0] += 1
                else:
                    key = keys[index % len(keys)]
                    assert isinstance(c.must("INCR", key), int)
                    with lock:
                        counts[key] += 1

        def bystander():
            c = self.conn(timeout=5)
            ready.wait(10)
            while not stop.is_set():
                at = time.monotonic()
                reply = self.transaction(c, [("INCR", key) for key in quiet])
                elapsed = time.monotonic() - at
                assert len(reply) == 2 and all(isinstance(v, int) for v in reply), reply
                latencies.append(elapsed)
                if len(latencies) >= min_bystander_samples:
                    bystander_ready.set()

        with concurrent.futures.ThreadPoolExecutor(25) as pool:
            futures = [pool.submit(worker, i) for i in range(24)] + [pool.submit(bystander)]
            try:
                # A fast victim can finish before the bystander's first EXEC.
                # Require acknowledged progress from BOTH workers before timing it;
                # the server's EXEC total also includes the bystander and cannot
                # by itself prove that the younger-unit storm has started.
                self.wait(lambda: completed_execs[0] >= 16 and bystander_ready.is_set(),
                          "storm or bystander did not start (16 EXECs / 20 samples)", timeout=5)
                victim = self.conn(timeout=1)
                at = time.monotonic()
                reply = self.transaction(victim, [("INCR", key) for key in keys])
                elapsed = time.monotonic() - at
                assert len(reply) == len(keys) and elapsed < 1, (elapsed, reply)
                attempts = None if self.args.pre else victim.must("DEBUG", "TXN-LAST-ATTEMPTS")
                if not self.args.pre:
                    assert isinstance(attempts, int) and attempts >= 1, attempts
                with lock:
                    counts.update(keys)
            finally:
                stop.set()
                for f in futures:
                    f.result(timeout=6)
        assert len(latencies) >= min_bystander_samples and max(latencies) < .2, latencies[-10:]
        assert self.admin.must("MGET", *quiet) == [str(len(latencies)).encode()] * len(quiet)
        if not self.args.pre:
            assert self.delta(before, "atomic_txn_executed") == completed_execs[0] + len(latencies) + 1
        assert self.admin.must("MGET", *keys) == [str(counts[k]).encode() for k in keys], counts
        self.clean(before)
        after = self.snapshot()
        assert after.get("atomic_txn_exclusive", 0) - before.get("atomic_txn_exclusive", 0) == 0
        self.report("b1", before, victim_seconds=elapsed, victim_attempts=attempts,
                    bystander_max_seconds=max(latencies), bystander_samples=len(latencies),
                    storm_executions=completed_execs[0], owners=self.args.owners)
        self.writer_bound()

    def writer_bound(self):
        key, _ = self.pair()
        self.admin.must("SET", key, 0)
        before = self.snapshot()
        stop = threading.Event()
        ready = threading.Barrier(5)
        counts = [0] * 4
        def holder(index):
            c = self.conn(timeout=5)
            ready.wait(10)
            while not stop.is_set():
                reply = self.transaction(c, [("INCR", key), ("DEBUG", "SLEEP", ".002")])
                assert isinstance(reply, list) and len(reply) == 2 and isinstance(reply[0], int), reply
                counts[index] += 1
        latency = []
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            tasks = [pool.submit(holder, i) for i in range(4)]
            try:
                c = self.conn(timeout=5)
                ready.wait(10)
                for _ in range(500):
                    at = time.monotonic()
                    assert isinstance(c.must("INCR", key), int)
                    latency.append(time.monotonic() - at)
            finally:
                stop.set()
                for f in tasks:
                    f.result(timeout=6)
        assert max(latency) < .040, ("writer bound 40 ms", max(latency))
        assert self.admin.must("GET", key) == str(500 + sum(counts)).encode(), counts
        if not self.args.pre:
            assert self.delta(before, "atomic_txn_writer_waits") > 0, "writer-bound window never opened"
        self.clean(before)
        self.report("b2", before, writer_max_seconds=max(latency), executions=counts)

    def deadlock(self):
        keys = self.owner_keys(self.args.owners)
        churn = [self.same_shard(key) for key in keys]
        self.admin.must("MSET", *[part for key in keys for part in (key, 0)])
        before = self.snapshot()
        end = None  # The 30-second storm starts after the PING watcher is ready.
        stop = threading.Event()
        counts = collections.Counter()
        lock = threading.Lock()
        executions = [0]
        config_count = [0]
        script_refusals = dict.fromkeys(SCRIPT_REFUSALS.values(), 0)
        ping_latencies = []
        # WATCH and plain multi-key writers share the EXEC churn keys. Keeping
        # these on a separate keyspace would miss validation/placement cycles.
        watch_pairs = [churn[:2], churn[2:4]]
        for pair in watch_pairs:
            self.admin.must("MSET", pair[0], 0, pair[1], 0)
        source, destination = self.pair()
        stream = [f"item:{i}".encode() for i in range(20000)]
        sent, delivered = [], []
        mover_results = []
        plain_pairs = [(churn[i % len(churn)], self.same_shard(churn[i % len(churn)])
                        if i < 4 else churn[(i + 1) % len(churn)]) for i in range(8)]
        move_pairs = [(self.pair(), self.pair()) for _ in range(2)]
        nx_pair = self.pair()

        def record(changes=(), execution=False):
            with lock:
                counts.update(changes)
                executions[0] += execution

        def exec_worker(index):
            c = self.conn(timeout=5)
            order = list(range(len(keys)))
            if index >= 8:
                order.reverse()
            n = 0
            while time.monotonic() < end:
                commands = []
                for i in order:
                    commands.extend([("INCR", keys[i]), ("SET", churn[i], f"{index}:{n}"), ("GET", churn[i])])
                reply = self.transaction(c, commands)
                assert isinstance(reply, list) and len(reply) == 3 * len(keys), reply
                for i in range(len(keys)):
                    assert isinstance(reply[i * 3], int) and reply[i * 3 + 2] == f"{index}:{n}".encode(), reply
                record(keys, True)
                n += 1

        def watched(pair, reverse):
            c = self.conn(timeout=5)
            watched_key, written = pair[::-1] if reverse else pair
            counted = keys[churn.index(written)]
            while time.monotonic() < end:
                c.must("WATCH", watched_key)
                reply = self.transaction(c, [("INCR", counted), ("SET", written, "watch")])
                assert reply is None or (isinstance(reply, list) and len(reply) == 2 and
                                         isinstance(reply[0], int) and reply[1] == b"OK"), reply
                if reply is not None:
                    record([counted], True)

        def plain(index):
            c = self.conn(timeout=5)
            a, b = plain_pairs[index]
            while time.monotonic() < end:
                assert c.must("MSET", a, "plain", b, "plain") == b"OK"
                assert isinstance(c.must("DEL", a, b), int)

        def script():
            c = self.conn(timeout=5)
            code = "redis.call('INCR',KEYS[1]); return redis.call('INCR',KEYS[2])"
            pair = [keys[0], keys[len(keys) // 2]]
            while time.monotonic() < end:
                reply = c.cmd("EVAL", code, 2, *pair)
                if isinstance(reply, _lib.RespError):
                    assert reply.message in SCRIPT_REFUSALS, reply
                    with lock:
                        script_refusals[SCRIPT_REFUSALS[reply.message]] += 1
                else:
                    assert isinstance(reply, int), reply
                    record(pair)

        def producer():
            c = self.conn(timeout=5)
            for value in stream:
                if time.monotonic() >= end:
                    break
                reply = self.transaction(c, [("LPUSH", source, value)])
                assert isinstance(reply, list) and len(reply) == 1 and isinstance(reply[0], int), reply
                sent.append(value)
                record(execution=True)

        def consumer():
            c = self.conn(timeout=5)
            while time.monotonic() < end:
                reply = c.must("BLMOVE", source, destination, "RIGHT", "LEFT", .1)
                if reply is not None:
                    assert isinstance(reply, bytes), reply
                    delivered.append(reply)

        timeout = self.admin.must("CONFIG", "GET", "timeout")[1]
        def admin_unit():
            c = self.conn(timeout=5)
            while time.monotonic() < end:
                reply = self.transaction(c, [("CONFIG", "SET", "timeout", timeout), ("INCR", keys[0])])
                assert isinstance(reply, list) and len(reply) == 2 and reply[0] == b"OK" and isinstance(reply[1], int), reply
                config_count[0] += 1
                record([keys[0]], True)
                time.sleep(.1)

        def ping():
            c = self.conn(timeout=1)
            while not stop.is_set():
                at = time.monotonic()
                assert c.must("PING") == b"PONG"
                ping_latencies.append(time.monotonic() - at)
                stop.wait(.1)

        def move(index):
            c = self.conn(timeout=5)
            (a, b), (r, t) = move_pairs[index]
            c.must("SADD" if index == 0 else "RPUSH", a, "m")
            c.must("SET", r, "rename")
            while time.monotonic() < end:
                reply = c.must("SMOVE", a, b, "m") if index == 0 else c.must("RPOPLPUSH", a, b)
                assert reply == (1 if index == 0 else b"m"), reply
                a, b = b, a
                assert c.must("RENAME", r, t) == b"OK"
                r, t = t, r
            values = [c.must("SMEMBERS", k) if index == 0 else c.must("LRANGE", k, 0, -1) for k in (a, b)]
            assert values[0] + values[1] == [b"m"]
            assert c.must("MGET", r, t) == [b"rename", None]
            mover_results.append(index)

        def nx():
            c = self.conn(timeout=5)
            a, b = nx_pair
            while time.monotonic() < end:
                assert c.must("MSETNX", a, 1, b, 1) == 1
                assert c.must("DEL", a, b) == 2

        def databases():
            c = self.conn(timeout=5)
            d = self.conn(timeout=5)
            d.must("SELECT", 4)
            while time.monotonic() < end:
                assert c.must("SWAPDB", 2, 3) == b"OK"
                d.must("SET", "txnorder-db4", "1")
                assert d.must("FLUSHDB") == b"OK"
                time.sleep(.05)

        jobs = [(exec_worker, (i,)) for i in range(16)]
        jobs += [(watched, (pair, reverse)) for pair in watch_pairs for reverse in (False, True)]
        jobs += [(plain, (i,)) for i in range(8)]
        jobs += [(script, ()), (script, ()), (producer, ()), (consumer, ()), (admin_unit, ())]
        jobs += [(move, (0,)), (move, (1,))]  # atomic-0 mover fix is also an invariant
        if self.atomic:
            jobs.append((nx, ()))
        if int(self.admin.must("CONFIG", "GET", "databases")[1]) == 16:
            jobs.append((databases, ()))
        with concurrent.futures.ThreadPoolExecutor(len(jobs) + 1) as pool:
            watcher = pool.submit(ping)
            try:
                self.wait(lambda: len(ping_latencies) >= 20,
                          "PING watcher did not collect 20 samples", timeout=5)
                ping_samples_before = len(ping_latencies)
                end = time.monotonic() + 30
                futures = [pool.submit(fn, *args) for fn, args in jobs]
                for future in futures:
                    future.result(timeout=36)
                ping_samples_after = len(ping_latencies)
            finally:
                stop.set()
                watcher.result(timeout=2)
        # Only `keys` carry increments recorded in counts. The watched churn
        # keys deliberately receive SET markers and DEL; Redis returns those
        # strings/null, never this nonexistent count (oracle-sequencing receipt).
        # Their exact in-EXEC values were checked in every successful transaction.
        for key in keys:
            assert self.admin.must("GET", key) == str(counts[key]).encode(), (key, counts[key])
        remaining = self.admin.must("LRANGE", source, 0, -1)
        destination_values = self.admin.must("LRANGE", destination, 0, -1)
        assert collections.Counter(remaining + destination_values) == collections.Counter(sent)
        assert len(delivered) == len(set(delivered)) and collections.Counter(destination_values) == collections.Counter(delivered)
        assert sorted(mover_results) == [0, 1] and config_count[0] > 0
        if not self.args.pre:
            assert self.delta(before, "atomic_txn_executed") == executions[0], (executions, config_count)
        assert ping_samples_after > ping_samples_before, "PING watcher missed the storm"
        assert max(ping_latencies) < 1
        self.clean(before)
        self.report("c", before, executions=executions[0], config_executions=config_count[0],
                    ping_max_seconds=max(ping_latencies),
                    ping_samples=ping_samples_after - ping_samples_before,
                    produced=len(sent), delivered=len(delivered),
                    script_refusals=script_refusals)

    def armed_witness(self):
        if self.args.mode != "1s":
            return
        key, _ = self.pair()
        self.admin.must("SET", key, "lane")
        c = self.conn(timeout=5)
        before = self.counter("read_local_keyspace_hits")
        for _ in range(10000):
            assert c.must("GET", key) == b"lane"
        assert self.counter("read_local_keyspace_hits") > before, "armed lane served no clean GET"

    def aof(self):
        assert self.admin.must("CONFIG", "GET", "appendonly")[1] == b"yes", "row d needs an AOF boot"
        self.storm(4, seconds=10, movers=bool(self.atomic))
        self.wait(lambda: self.counter("atomic_pending_entries") == 0,
                  "AOF comparison started with pending candidates", timeout=5)
        keys = sorted(self.admin.must("KEYS", "*"))
        def capture():
            data = {}
            for key in keys:
                kind = self.admin.must("TYPE", key)
                if kind == b"string":
                    value = self.admin.must("GET", key)
                elif kind == b"set":
                    value = sorted(self.admin.must("SMEMBERS", key))
                elif kind == b"list":
                    value = self.admin.must("LRANGE", key, 0, -1)
                else:
                    raise AssertionError(("unexpected storm key type", key, kind))
                data[key] = (kind, value)
            return data
        before = capture()
        assert self.admin.must("DEBUG", "LOADAOF") == b"OK"
        assert sorted(self.admin.must("KEYS", "*")) == keys, "reload changed key inventory"
        assert capture() == before, "reload differs from acknowledged storm state"
        print(json.dumps(dict(row="d-reload", keys=len(keys), exact=True)), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--mode", choices=("1s", "2s"), required=True)
    parser.add_argument("--owners", type=int, default=4)
    parser.add_argument("--only")
    parser.add_argument("--pre", action="store_true")
    args = parser.parse_args()
    battery = OrderBattery(args)
    try:
        assert _lib.thread_mode(battery.admin) == args.mode
        for knob in ("key-lb", "client-lb", "flip-auto"):
            assert battery.admin.must("CONFIG", "GET", knob)[1] == b"0", knob
        if args.mode == "1s":
            assert battery.admin.must("CONFIG", "GET", "read-local")[1] == b"1"
        for name, function in (("a", battery.hot), ("b", battery.starvation), ("c", battery.deadlock)):
            battery.run(name, function)
        if args.only and "d" in args.only.split(","):
            battery.run("d", battery.aof)
        battery.run("armed", battery.armed_witness)
    finally:
        battery.close()
    return bool(battery.failures)


if __name__ == "__main__":
    raise SystemExit(main())
