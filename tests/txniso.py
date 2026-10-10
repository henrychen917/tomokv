#!/usr/bin/env python3
"""Serializable EXEC regression battery, including data-only PRE controls.

Run against a debug-enabled server with key/client balancing and automatic FLIP
disabled. --pre suppresses only assertions on newly introduced counters.
"""
import argparse
import concurrent.futures
import contextlib
import select
import subprocess
import sys
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

    def conn(self, timeout=10):
        c = _lib.Conn(self.args.host, self.args.port, timeout=timeout)
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
    finally:
        battery.close()
    return bool(battery.failures)


if __name__ == "__main__":
    sys.exit(main())
