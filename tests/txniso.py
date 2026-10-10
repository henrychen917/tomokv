#!/usr/bin/env python3
"""Serializable EXEC regression battery, including data-only PRE controls.

Run against a debug-enabled server with key/client balancing and automatic FLIP
disabled. --pre suppresses only assertions on newly introduced counters.
"""
import argparse
import collections
import concurrent.futures
import contextlib
import select
import subprocess
import sys
import threading
import time
from pathlib import Path

import _lib


class WindowMiss(Exception):
    pass


class Battery:
    def __init__(self, args):
        self.args = args
        self.connections = []
        self.admin = self.conn()
        self.serial = 0
        self.failures = []

    def conn(self, timeout=10, buffering=1 << 20):
        c = _lib.Conn(self.args.host, self.args.port, timeout=timeout, buffering=buffering)
        self.connections.append(c)
        return c

    def stats(self):
        return _lib.info(self.admin, "stats")

    def counter(self, name):
        stats = self.stats()
        if name not in stats and self.args.pre:
            return None
        assert name in stats, "missing counter " + name
        return int(stats[name])

    def advanced(self, name, before):
        if before is not None:
            assert self.counter(name) > before, name + " did not advance"

    def hook(self, name, value):
        assert self.admin.must("DEBUG", name, value) == b"OK"

    def pair(self):
        self.serial += 1
        names = [f"txniso:{time.time_ns()}:{self.serial}:{i}" for i in range(256)]
        geometry = self.admin.must("DEBUG", "SHARDS", *names)
        other = next((i for i in range(1, len(names))
                      if geometry[i][1] != geometry[0][1]), None)
        assert other is not None, "DEBUG SHARDS did not prove two owners"
        keys = [names[0], names[other]]
        assert self.admin.must("DEBUG", "SHARDS", *keys) == [geometry[0], geometry[other]]
        return keys

    @staticmethod
    def queue(c, commands):
        assert c.must("MULTI") == b"OK"
        for command in commands:
            assert c.must(*command) == b"QUEUED", command

    def transaction(self, c, commands):
        self.queue(c, commands)
        return c.must("EXEC")

    @staticmethod
    def wait(predicate, label, timeout=.25):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return
            time.sleep(.001)
        raise WindowMiss(label)

    @contextlib.contextmanager
    def parked(self, commands, writes=False, watch=None):
        holder = self.conn()
        if watch:
            assert holder.must("WATCH", watch) == b"OK"
        self.queue(holder, commands)
        cuts = self.counter("atomic_exec_read_cuts")
        entries = self.counter("atomic_entries")
        intents = self.counter("atomic_txn_intents")
        self.hook("ATOMIC-FANOUT-DEFER", 400000)
        holder.send("EXEC")
        try:
            self.wait(lambda: self.counter("atomic_exec_read_cuts") > cuts,
                      "EXEC did not register its cut")
            self.hook("ATOMIC-FANOUT-DEFER", 0)
            if writes:
                self.wait(lambda: self.counter("atomic_entries") > entries,
                          "lead did not install before the competing operation")
            elif intents is not None:
                self.wait(lambda: self.counter("atomic_txn_intents") > intents,
                          "lead did not read before the competing operation")
            if select.select([holder.sock], [], [], 0)[0]:
                raise WindowMiss("holder already replied")
            yield holder
        except WindowMiss:
            # Retire the missed attempt before arming a fresh one, so its late
            # counter movement cannot witness the replacement window.
            holder.read()
            raise
        finally:
            self.hook("ATOMIC-FANOUT-DEFER", 0)
            holder.close()

    def directed(self, kind):
        # Re-arm only an unobserved window, on fresh state. Data errors are never
        # retried: a single acknowledged loss is a failure.
        for attempt in range(4):
            a, b = self.pair()
            self.admin.must("MSET", a, 0, b, 0)
            dooms = self.counter("atomic_txn_dooms")
            retries = self.counter("atomic_txn_retries")
            waits = self.counter("atomic_txn_waits")
            commands = [("INCR", a), ("MGET", a, b), ("INCR", b)]
            if kind == "D3":
                shard = self.admin.must("DEBUG", "SHARD", a)
                marker = next(a + ":marker:" + str(i) for i in range(4096)
                              if self.admin.must("DEBUG", "SHARD", a + ":marker:" + str(i)) == shard)
                # The cut counter witnesses dispatch, not the lead read. A write
                # to a distinct key in that same owner turn proves the lead ran
                # before the foreign writer, including on PRE without intents.
                commands = [("INCR", marker), ("MGET", a, b), ("GET", a)]
            watched = a + ":watch" if kind.startswith("D4") else None
            try:
                with self.parked(commands, True, watched) as holder:
                    writer = self.conn()
                    if kind == "D2":
                        self.queue(writer, [("INCR", a)])
                        writer.send("EXEC")
                        result = holder.read()
                        foreign = writer.read()[0]
                    else:
                        foreign = writer.must("SET", a, "new") if kind == "D3" else writer.must("INCR", a)
                        if select.select([holder.sock], [], [], 0)[0]:
                            raise WindowMiss("foreign write did not precede holder reply")
                        if kind == "D4b":
                            writer.must("SET", watched, "changed")
                        result = holder.read()
                    if kind == "D3":
                        assert result[1][0] == result[2], ("read changed inside EXEC", result)
                    elif kind == "D4b":
                        assert result is None, ("changed WATCH must yield null", result)
                        assert self.admin.must("MGET", a, b) == [b"1", b"0"]
                    else:
                        assert isinstance(result, list) and len(result) == 3, result
                        assert self.admin.must("MGET", a, b) == [b"2", b"1"], (kind, result, foreign)
                        assert sorted([result[0], foreign]) == [1, 2], (result, foreign)
                        assert result[1] == [str(result[0]).encode(), b"0"], result
                if kind == "D2":
                    self.advanced("atomic_txn_waits", waits)
                else:
                    self.advanced("atomic_txn_dooms", dooms)
                    self.advanced("atomic_txn_retries", retries)
                return
            except WindowMiss:
                if attempt == 3:
                    raise

    def commit_window(self, child=False):
        a, b = self.pair()
        if child:
            self.admin.must("SADD", a, "m")
            commands = [("SMOVE", a, b, "m")]
            writers = [("SADD", a, "y"), ("SADD", b, "z")]
        else:
            self.admin.must("MSET", a, 0, b, 0)
            commands = [("INCR", a), ("INCR", b)]
            writers = [("INCR", a), ("INCR", b)]
        holder, one, two = self.conn(), self.conn(), self.conn()
        retries = self.counter("atomic_txn_retries")
        self.queue(holder, commands)
        self.hook("ATOMIC-COMMIT-DELAY", 200000)
        try:
            holder.send("EXEC")
            time.sleep(.04)
            def write(c, command):
                begin = time.monotonic()
                result = c.must(*command)
                return result, time.monotonic() - begin
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                first = pool.submit(write, one, writers[0])
                second = pool.submit(write, two, writers[1])
                r1, r2 = first.result(), second.result()
            self.hook("ATOMIC-COMMIT-DELAY", 0)
            result = holder.read()
            assert min(r1[1], r2[1]) < .1, ("no unstalled writer window", r1, r2)
            if child:
                assert result == [1], result
                assert set(self.admin.must("SMEMBERS", a)) == {b"y"}
                assert set(self.admin.must("SMEMBERS", b)) == {b"m", b"z"}
            else:
                assert self.admin.must("MGET", a, b) == [b"2", b"2"], (result, r1, r2)
                assert sorted([result[0], r1[0]]) == [1, 2]
                assert sorted([result[1], r2[0]]) == [1, 2]
            self.advanced("atomic_txn_retries", retries)
        finally:
            self.hook("ATOMIC-COMMIT-DELAY", 0)

    def audit(self, script, *workload, extra=()):
        path = Path(__file__).with_name("txnfix_audit") / script
        command = [sys.executable, str(path), "--attach", "--host", self.args.host,
                   "--port", str(self.args.port), *extra, *map(str, workload)]
        result = subprocess.run(command, timeout=30, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        print(result.stdout, end="", flush=True)
        assert result.returncode == 0, (script, result.returncode)

    def watch_before(self):
        a, b = self.pair()
        c = self.conn()
        c.must("WATCH", a)
        self.admin.must("SET", a, 1)
        assert self.transaction(c, [("SET", b, 1)]) is None
        assert self.admin.must("GET", b) is None

    def same_shard(self, key):
        names = [key + ":local:" + str(i) for i in range(1024)]
        shard = self.admin.must("DEBUG", "SHARD", key)
        routes = self.admin.must("DEBUG", "SHARDS", *names)
        return next(name for name, route in zip(names, routes) if route[0] == shard)

    def read_skew(self):
        a, b = self.pair()
        self.admin.must("MSET", a, 0, b, 0)
        start = threading.Barrier(8)
        def worker(index):
            c = self.conn()
            torn = 0
            start.wait(timeout=5)
            for i in range(300):
                if index < 4:
                    value = index * 300 + i
                    result = self.transaction(c, [("SET", a, value), ("SET", b, value)])
                    assert result == [b"OK", b"OK"], result
                else:
                    result = self.transaction(c, [("GET", a), ("GET", b)])
                    assert isinstance(result, list) and len(result) == 2, result
                    torn += result[0] != result[1]
            return torn
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            torn = sum(pool.map(worker, range(8)))
        print("read skew torn", torn, flush=True)
        assert torn == 0, torn

    def crossed_watch(self):
        a, b = self.pair()
        self.admin.must("MSET", a, 0, b, 0)
        turn = threading.Barrier(2)
        end = time.monotonic() + 20
        def worker(watch, write):
            c = self.conn(timeout=5)
            try:
                for i in range(500):
                    assert time.monotonic() < end, "crossed WATCH deadline"
                    c.must("WATCH", watch)
                    turn.wait(timeout=5)
                    result = self.transaction(c, [("DEBUG", "SLEEP", ".001"), ("SET", write, i)])
                    assert result is None or result == [b"OK", b"OK"], result
                    turn.wait(timeout=5)
            except BaseException:
                turn.abort()
                raise
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(worker, a, b), pool.submit(worker, b, a)]
            for future in futures:
                future.result(timeout=20)

    def invisible(self, kind):
        a, b = self.pair()
        self.admin.must("MSET", a, 0, b, 0)
        commands = [("INCR", a), ("MGET", a, b), ("INCR", b)]
        listener = None
        previous_notify = None
        if kind == "V1":
            previous_notify = self.admin.must("CONFIG", "GET", "notify-keyspace-events")[1]
            self.admin.must("CONFIG", "SET", "notify-keyspace-events", "KEA")
            listener = self.conn(buffering=0)
            listener.send("SUBSCRIBE", "__keyspace@0__:" + a, "__keyspace@0__:" + b)
            assert listener.read()[0] == listener.read()[0] == b"subscribe"
        elif kind == "V2":
            listener = self.conn(buffering=0)
            assert listener.must("SUBSCRIBE", a)[0] == b"subscribe"
            commands.append(("PUBLISH", a, "one"))
        elif kind == "V3":
            members = {str(i).encode() for i in range(16)}
            collection = self.same_shard(a)
            self.admin.must("SADD", collection, *members)
            commands.insert(1, ("SPOP", collection))
        retries = self.counter("atomic_txn_retries")
        try:
            with self.parked(commands, writes=True) as holder:
                assert self.admin.must("INCR", a) == 1
                result = holder.read()
            assert result is not None and result[0] == 2, result
            self.advanced("atomic_txn_retries", retries)
            if kind == "V1":
                events = [listener.read() for _ in range(3)]
                counts = collections.Counter((event[1], event[2]) for event in events)
                assert counts == collections.Counter({
                    (("__keyspace@0__:" + a).encode(), b"incrby"): 2,
                    (("__keyspace@0__:" + b).encode(), b"incrby"): 1}), events
            elif kind == "V2":
                assert result[-1] == 1, result
                assert listener.read() == [b"message", a.encode(), b"one"]
            elif kind == "V3":
                remaining = set(self.admin.must("SMEMBERS", collection))
                assert members - remaining == {result[1]} and len(remaining) == 15, (result, remaining)
            if listener:
                assert not select.select([listener.sock], [], [], .1)[0], "duplicate published effect"
        finally:
            if previous_notify is not None:
                self.admin.must("CONFIG", "SET", "notify-keyspace-events", previous_notify)

    def aof_replay(self):
        assert self.admin.must("CONFIG", "GET", "appendonly")[1] == b"yes", "V4 needs its own AOF boot"
        expected = {}
        for _ in range(3):
            a, b = self.pair()
            self.admin.must("MSET", a, 0, b, 0)
            retries = self.counter("atomic_txn_retries")
            with self.parked([("INCR", a), ("MGET", a, b), ("INCR", b)], writes=True) as holder:
                self.admin.must("INCR", a)
                assert holder.read() == [2, [b"2", b"0"], 1]
            self.advanced("atomic_txn_retries", retries)
            expected.update({a: b"2", b: b"1"})
        assert self.admin.must("DEBUG", "LOADAOF") == b"OK"
        assert self.admin.must("MGET", *expected) == list(expected.values()), "discarded attempt in AOF"

    def fallback(self):
        a, b = self.pair()
        self.admin.must("MSET", a, 0, b, 0)
        exclusive = self.counter("atomic_txn_exclusive")
        self.hook("TXN-OCC-LIMIT", 1)
        stop = threading.Event()
        counts = [0] * 4
        def hammer(index):
            c = self.conn(timeout=5)
            while not stop.is_set():
                assert isinstance(c.must("INCR", a), int)
                counts[index] += 1
        try:
            with concurrent.futures.ThreadPoolExecutor(4) as pool:
                writers = [pool.submit(hammer, i) for i in range(4)]
                try:
                    c = self.conn(timeout=5)
                    end = time.monotonic() + 15
                    for _ in range(200):
                        result = self.transaction(c, [("INCR", a), ("INCR", b)])
                        assert isinstance(result, list) and len(result) == 2, result
                        assert time.monotonic() < end, "fallback deadline"
                finally:
                    stop.set()
                    for writer in writers:
                        writer.result(timeout=5)
            assert self.admin.must("MGET", a, b) == [str(200 + sum(counts)).encode(), b"200"], counts
            self.advanced("atomic_txn_exclusive", exclusive)
            for name in ("atomic_txn_exclusive_violations", "atomic_txn_exclusive_drain_timeouts"):
                assert self.counter(name) in (0, None), name
        finally:
            self.hook("TXN-OCC-LIMIT", 8)

    def exclusive_admin(self):
        a, b = self.pair()
        self.admin.must("MSET", a, 0, b, 0)
        timeout = self.admin.must("CONFIG", "GET", "timeout")[1]
        before = self.counter("atomic_txn_exclusive")
        # Put the all-owner CONFIG barrier after the witnessed park. Classification
        # must still select exclusive before the first command of attempt one.
        commands = [("INCR", a), ("MGET", a, b), ("CONFIG", "SET", "timeout", timeout), ("INCR", b)]
        with self.parked(commands, writes=True) as holder:
            writer = self.conn()
            writer.send("INCR", a)
            assert holder.read() == [1, [b"1", b"0"], b"OK", 1]
            assert writer.read() == 2
        assert self.admin.must("MGET", a, b) == [b"2", b"1"]
        if before is not None:
            assert self.counter("atomic_txn_exclusive") == before + 1

    def rest(self):
        self.wait(lambda: self.counter("atomic_pending_entries") == 0,
                  "pending entries did not drain", timeout=1)
        for name in ("atomic_txn_intents_live", "atomic_exec_order_late", "atomic_gauge_underflows",
                     "atomic_txn_exclusive_violations", "atomic_txn_exclusive_drain_timeouts"):
            assert self.counter(name) in (0, None), (name, self.counter(name))
        assert self.counter("script_intents_live") == self.script_intents_before

    def plain_rest(self):
        a, b = self.pair()
        before = {k: v for k, v in self.stats().items() if k.startswith("atomic_txn_")}
        end = time.monotonic() + 1
        while time.monotonic() < end:
            self.admin.must("SET", a, 1)
            assert self.admin.must("GET", a) == b"1"
            self.admin.must("MSET", a, 2, b, 2)
            assert self.admin.must("MGET", a, b) == [b"2", b"2"]
        after = {k: v for k, v in self.stats().items() if k.startswith("atomic_txn_")}
        assert after == before, (before, after)

    def run(self, name, function):
        if self.args.only and name not in self.args.only.split(","):
            return
        try:
            function()
            print("PASS", name, flush=True)
        except Exception as error:
            self.failures.append(name)
            print("FAIL", name, repr(error), flush=True)

    def close(self):
        for c in self.connections:
            c.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--mode", choices=("1s", "2s"), default="2s")
    parser.add_argument("--pre", action="store_true")
    parser.add_argument("--only")
    args = parser.parse_args()
    battery = Battery(args)
    try:
        battery.script_intents_before = battery.counter("script_intents_live")
        assert _lib.thread_mode(battery.admin) == args.mode
        print("geometry", args.mode, "atomic", battery.admin.must("CONFIG", "GET", "atomic")[1],
              "databases", battery.admin.must("CONFIG", "GET", "databases")[1], flush=True)
        for knob in ("key-lb", "client-lb", "flip-auto"):
            assert battery.admin.must("CONFIG", "GET", knob)[1] == b"0", knob
        for name in ("D1", "D2", "D3", "D4a", "D4b"):
            battery.run(name, lambda n=name: battery.directed(n))
        if args.mode == "2s":
            battery.run("D1b", battery.commit_window)
            battery.run("D5", lambda: battery.commit_window(child=True))
        battery.run("S1", lambda: battery.audit("t15_exec_only_stress.py", "tomo", args.mode, 16, 500, 4))
        battery.run("S2", lambda: battery.audit("t01_exec_counter.py", "tomo", 0, args.mode, 500))
        battery.run("S3", lambda: battery.audit("t14_exec_window.py", 0, extra=("--clients", "200")))
        battery.run("S4", lambda: battery.audit("t17_queue_exec.py", "tomo", args.mode, extra=("--operations", "500")))
        battery.run("W1", lambda: battery.audit("t18_watch_cas.py", "tomo", args.mode, 4, 100))
        battery.run("W2", battery.watch_before)
        battery.run("S5", battery.read_skew)
        battery.run("W3", battery.crossed_watch)
        for name in ("V1", "V2", "V3"):
            battery.run(name, lambda n=name: battery.invisible(n))
        # The gate appends this companion check from a separate appendonly boot.
        if args.only and "V4" in args.only.split(","):
            battery.run("V4", battery.aof_replay)
        battery.run("X1", battery.fallback)
        battery.run("X2", battery.exclusive_admin)
        battery.run("Z1", battery.rest)
        battery.run("Z2", battery.plain_rest)
    finally:
        battery.close()
    return bool(battery.failures)


if __name__ == "__main__":
    sys.exit(main())
