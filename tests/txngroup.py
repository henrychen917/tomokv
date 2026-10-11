#!/usr/bin/env python3
"""Atomic group OCC: witnessed stale-image races and exact mover conservation."""
import argparse
import concurrent.futures
import select
import sys
import time

import _lib
from txniso import Battery, WindowMiss


class GroupBattery(Battery):
    def __init__(self, args):
        super().__init__(args)
        self.reload_checks = []

    def atomic(self):
        return int(self.admin.must("CONFIG", "GET", "atomic")[1])

    def held(self, command, writer_command, records):
        mover, writer = self.conn(), self.conn()
        atomic = self.atomic()
        self.wait(lambda: self.counter("atomic_pending_entries") == 0,
                  "prior groups did not drain", timeout=1)
        entries = self.counter("atomic_entries")
        dooms = self.counter("atomic_group_dooms")
        retries = self.counter("atomic_group_retries")
        self.hook("ATOMIC-COMMIT-HOLD", 1)
        try:
            mover.send(*command)
            if atomic:
                self.wait(lambda: self.counter("atomic_entries") >= entries + records and
                          self.counter("atomic_pending_entries") >= records,
                          "all required private images were not installed", timeout=1)
                if select.select([mover.sock], [], [], 0)[0]:
                    raise WindowMiss("held mover already replied")
            else:
                # The commit hook has no effect on the atomic-0 control. This
                # is the same completed-mover arm as the auditor's T03 control.
                result = mover.read()
            foreign = writer.must(*writer_command)
        except WindowMiss:
            self.hook("ATOMIC-COMMIT-HOLD", 0)
            mover.read()  # retire the missed arm before fresh state can witness it
            raise
        finally:
            self.hook("ATOMIC-COMMIT-HOLD", 0)
        if atomic:
            result = mover.read()
        return result, foreign, dooms, retries

    def directed(self, name):
        for arm in range(4):
            src, dst = self.pair()
            if name == "SMOVE":
                setup = [("SADD", src, "m"), ("SADD", dst, "a")]
                command, writer = ("SMOVE", src, dst, "m"), ("SADD", dst, "z")
                checks = [("SMEMBERS", src), ("SMEMBERS", dst)]
                valid = lambda r, v: r == 1 and v[0] == [] and sorted(v[1]) == [b"a", b"m", b"z"]
            elif name == "LMOVE":
                setup = [("RPUSH", src, "m"), ("RPUSH", dst, "a")]
                command = ("LMOVE", src, dst, "LEFT", "RIGHT")
                writer = ("RPUSH", dst, "z")
                checks = [("LRANGE", src, 0, -1), ("LRANGE", dst, 0, -1)]
                valid = lambda r, v: r == b"m" and v[0] == [] and sorted(v[1]) == [b"a", b"m", b"z"]
            elif name == "PFMERGE":
                setup = [("PFADD", src, "s1", "s2"), ("PFADD", dst, "a")]
                command, writer = ("PFMERGE", dst, src), ("PFADD", dst, "z1", "z2", "z3")
                checks = [("PFCOUNT", src), ("PFCOUNT", dst)]
                valid = lambda r, v: r == b"OK" and v == [2, 6]
            elif name == "RPOPLPUSH-source":
                setup = [("RPUSH", src, "m"), ("RPUSH", dst, "a")]
                command, writer = ("RPOPLPUSH", src, dst), ("RPUSH", src, "z")
                checks = [("LRANGE", src, 0, -1), ("LRANGE", dst, 0, -1)]
                valid = lambda r, v: (r, v) in (
                    (b"m", [[b"z"], [b"m", b"a"]]),
                    (b"z", [[b"m"], [b"z", b"a"]]))
            elif name == "RENAME-source":
                setup = [("SET", src, "old")]
                command, writer = ("RENAME", src, dst), ("SET", src, "new")
                checks = [("GET", src), ("GET", dst)]
                valid = lambda r, v: r == b"OK" and v in ([b"new", b"old"], [None, b"new"])
            else:
                setup = []
                command = ("MSETNX", src, "from-msetnx", dst, "from-msetnx")
                writer = ("SET", src, "from-set")
                checks = [("GET", src), ("GET", dst)]
                valid = lambda r, v: (r, v) in (
                    (0, [b"from-set", None]), (1, [b"from-set", b"from-msetnx"]))
            for command_setup in setup:
                self.admin.must(*command_setup)
            try:
                result, foreign, dooms, retries = self.held(
                    command, writer, 1 if name == "PFMERGE" else 2)
            except WindowMiss:
                if arm == 3:
                    raise
                continue
            values = [self.admin.must(*check) for check in checks]
            assert valid(result, values), (name, result, foreign, values)
            if self.atomic():
                self.advanced("atomic_group_dooms", dooms)
                self.advanced("atomic_group_retries", retries)
            self.reload_checks.append((checks, values))
            print("directed", name, "result", result, "state", values, flush=True)
            return

    def moves(self, kind, adders=False):
        src, dst = self.pair()
        count = 4000 if adders else 2000
        members = [f"m{i}".encode() for i in range(count)]
        for start in range(0, count, 500):
            self.admin.must("SADD" if kind == "smove" else "RPUSH", src,
                            *members[start:start + 500])
        deadline = time.monotonic() + 30

        def worker(index, add):
            c = self.conn(timeout=10)
            replies = []
            for i in range(index * (count // 4), (index + 1) * (count // 4)):
                assert time.monotonic() < deadline, "mover conservation deadline"
                if add:
                    reply = c.must("SADD", dst, f"z{i}")
                elif kind == "smove":
                    reply = c.must("SMOVE", src, dst, members[i])
                else:
                    reply = c.must("RPOPLPUSH", src, dst)
                valid = reply == 1 if add or kind == "smove" else isinstance(reply, bytes)
                assert valid, reply
                replies.append(reply)
            return replies

        with concurrent.futures.ThreadPoolExecutor(8 if adders else 4) as pool:
            moved = [pool.submit(worker, i, False) for i in range(4)]
            added = [pool.submit(worker, i, True) for i in range(4)] if adders else []
            deliveries = [value for future in moved for value in future.result(timeout=35)]
            for future in added:
                assert len(future.result(timeout=35)) == count // 4
        if kind == "smove":
            source = self.admin.must("SMEMBERS", src)
            destination = self.admin.must("SMEMBERS", dst)
        else:
            source = self.admin.must("LRANGE", src, 0, -1)
            destination = self.admin.must("LRANGE", dst, 0, -1)
            assert len(deliveries) == len(set(deliveries)) == count, "duplicate delivery"
        expected = set(members)
        if adders:
            expected.update(f"z{i}".encode() for i in range(count))
        assert not source and len(destination) == len(expected) and set(destination) == expected, (
            kind, len(source), len(destination), len(expected))
        print("conservation", kind, "atomic", self.atomic(), "members", len(expected), flush=True)

    def off_control(self):
        self.rest()
        before = {k: v for k, v in self.stats().items() if k.startswith("atomic_group_")}
        self.admin.must("CONFIG", "SET", "atomic", 0)
        try:
            for name in ("SMOVE", "LMOVE", "PFMERGE", "RPOPLPUSH-source", "RENAME-source"):
                self.directed(name)
            self.moves("smove", adders=True)
            self.moves("smove")
            self.moves("rpoplpush")
        finally:
            self.admin.must("CONFIG", "SET", "atomic", 1)
        after = {k: v for k, v in self.stats().items() if k.startswith("atomic_group_")}
        assert after == before, (before, after)

    def reload(self):
        assert self.admin.must("CONFIG", "GET", "appendonly")[1] == b"yes", "AOF boot required"
        self.directed("SMOVE")
        self.directed("MSETNX")
        self.admin.must("DEBUG", "LOADAOF")
        for checks, expected in self.reload_checks:
            assert [self.admin.must(*check) for check in checks] == expected, checks

    def exclusive(self):
        self.hook("TXN-OCC-LIMIT", 1)
        try:
            for name in ("SMOVE", "LMOVE", "PFMERGE", "RPOPLPUSH-source",
                         "RENAME-source", "MSETNX"):
                before = self.counter("atomic_group_exclusive")
                self.directed(name)
                self.advanced("atomic_group_exclusive", before)
                self.rest()
        finally:
            self.hook("TXN-OCC-LIMIT", 8)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--mode", choices=("1s", "2s"), default="2s")
    parser.add_argument("--pre", action="store_true")
    parser.add_argument("--only")
    args = parser.parse_args()
    battery = GroupBattery(args)
    try:
        assert _lib.thread_mode(battery.admin) == args.mode
        assert battery.atomic() == 1, "txngroup battery requires an atomic-1 boot"
        for knob in ("key-lb", "client-lb", "flip-auto"):
            assert battery.admin.must("CONFIG", "GET", knob)[1] == b"0", knob
        battery.script_intents_before = battery.counter("script_intents_live")
        for name in ("SMOVE", "LMOVE", "PFMERGE", "RPOPLPUSH-source", "RENAME-source"):
            battery.run("G1-" + name, lambda n=name: battery.directed(n))
        battery.run("G2", lambda: battery.directed("MSETNX"))
        battery.run("G3", lambda: battery.moves("smove", adders=True))
        battery.run("G4-smove", lambda: battery.moves("smove"))
        battery.run("G4-rpoplpush", lambda: battery.moves("rpoplpush"))
        battery.run("GX", battery.exclusive)
        battery.run("G5", battery.off_control)
        battery.run("G6", battery.rest)
        if args.only and "AOF" in args.only.split(","):
            battery.run("AOF", battery.reload)
    finally:
        battery.hook("ATOMIC-COMMIT-HOLD", 0)
        battery.close()
    return bool(battery.failures)


if __name__ == "__main__":
    sys.exit(main())
