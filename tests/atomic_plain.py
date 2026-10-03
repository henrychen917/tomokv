#!/usr/bin/env python3
"""AT1/AT2 lost-update races, against an isolated debug-enabled server.

Usage: atomic_plain.py HOST PORT --atomic 0|1 [--case movers|blocking]
The gate row also runs atomic-survivors-unit plain_0/plain_1: that serverless arm drives
every caller, including LMPOP/ZMPOP's single-owner phase two (which OFF-HOP cannot park).

Like multirace/execatomic, prove actual owners and hold an EXEC read cut with FANOUT-DEFER.
Like blockmulti, require registration before the waking push. OFF-HOP exposes a mover's
destination window; COMMIT-DELAY holds the safe watermark behind a blocking wake push.
Only a missed window is retried, on fresh keys/connections, at most four times. Wrong data,
a lost reply, or a nonzero stale-cut counter is always a failure, never an arming retry.
"""
import argparse
import contextlib
import select
import time

import _lib


class WindowMiss(Exception):
    pass


def require(condition, label):
    if not condition:
        raise AssertionError(label)


def expect(value, wanted, label):
    require(value == wanted, f"{label}: got {value!r}, wanted {wanted!r}")


def info(conn, section="STATS"):
    raw = conn.must("INFO", section)
    require(isinstance(raw, bytes), "INFO returns a bulk string")
    return dict(line.split(":", 1) for line in raw.decode().splitlines()
                if ":" in line)


def stat(conn, field, section="STATS"):
    rows = info(conn, section)
    require(field in rows, f"INFO {section} must expose {field}")
    return int(rows[field])


def debug(conn, name, value):
    expect(conn.must("DEBUG", name, value), b"OK", "DEBUG " + name)


def pending(conn):
    return not select.select([conn.sock], [], [], 0)[0]


def wait_for(probe, wanted, label, timeout=0.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe() == wanted:
            return
        time.sleep(0.002)
    raise WindowMiss(label)


def stale_zero(admin):
    expect(admin.must("DEBUG", "ATOMIC-PLAIN-STALE-CUTS"), 0,
           "plain write stale-cut counter is zero")


def queued(conn, commands):
    expect(conn.must("MULTI"), b"OK", "MULTI")
    for command in commands:
        expect(conn.must(*command), b"QUEUED", "queued " + command[0])


class Race:
    def __init__(self, host, port, admin):
        self.host, self.port, self.admin = host, port, admin
        self.stack = contextlib.ExitStack()
        topo = _lib.topology(admin)
        require(len(topo.owners) >= 2, "lost-update race needs two real shard owners")
        self.a = min(topo.shard_owner)
        self.b = next(s for s in sorted(topo.shard_owner)
                      if topo.shard_owner[s] != topo.shard_owner[self.a])
        self.owners = (topo.shard_owner[self.a], topo.shard_owner[self.b])
        self.prefix = "atomicplain:" + str(time.time_ns())
        self.serial = 0

    def conn(self):
        conn = _lib.Conn(self.host, self.port, timeout=5)
        self.stack.callback(conn.close)
        return conn

    def key(self, shard):
        for _ in range(5000):
            self.serial += 1
            key = f"{self.prefix}:{self.serial}"
            if _lib.shard_of(self.admin, key) == shard:
                return key
        raise AssertionError("fresh key search did not find the required shard")

    @contextlib.contextmanager
    def held_exec(self, keys):
        holder = self.conn()
        queued(holder, [("MGET", *keys)])
        before = stat(self.admin, "atomic_exec_read_cuts")
        debug(self.admin, "ATOMIC-FANOUT-DEFER", 1000000)
        holder.send("EXEC")
        try:
            wait_for(lambda: stat(self.admin, "atomic_exec_read_cuts") > before,
                     True, "EXEC did not register its read cut")
            # Already-published deadlines remain on the holder; new commands run normally.
            debug(self.admin, "ATOMIC-FANOUT-DEFER", 0)
            if not pending(holder):
                raise WindowMiss("EXEC completed before the competing operation")
            yield holder
        finally:
            debug(self.admin, "ATOMIC-FANOUT-DEFER", 0)
            debug(self.admin, "ATOMIC-OFF-HOP-DELAY", 0)
            reply = holder.read()
            require(isinstance(reply, list) and len(reply) == 1 and
                    isinstance(reply[0], list), f"held EXEC reply: {reply!r}")

    def mover(self, verb):
        admin = self.admin
        src, dst = self.key(self.a), self.key(self.b)
        require(_lib.shards_of(admin, [src, dst]) ==
                [(self.a, self.owners[0]), (self.b, self.owners[1])], "mover owner geometry")
        is_set = verb == "SMOVE"
        add = "SADD" if is_set else "RPUSH"
        expect(admin.must(add, src, "move"), 1, "seed mover source")
        mover, writer = self.conn(), self.conn()
        with self.held_exec([src, dst]) as holder:
            # Install an actual EXEC record after the held cut. It cannot be collapsed away.
            queued(writer, [(add, dst, "base")])
            expect(writer.must("EXEC"), [1], "destination EXEC committed")
            debug(admin, "ATOMIC-OFF-HOP-DELAY", 400000)
            command = ((verb, src, dst, "move") if is_set else
                       (verb, src, dst, "LEFT", "RIGHT") if verb == "LMOVE" else
                       (verb, src, dst))
            mover.send(*command)
            # The lowest-shard source is the lead. Its removal proves phase two started;
            # the destination owner is parked, but remains free to accept our plain write.
            probe = (lambda: admin.must("SISMEMBER", src, "move")) if is_set else (
                lambda: admin.must("LLEN", src))
            wait_for(probe, 0, "mover source did not publish inside the hop window", 0.25)
            opened = pending(mover) and pending(holder)
            expect(writer.must(add, dst, "kept"), 2, "racing destination write acknowledged")
            opened &= pending(mover) and pending(holder)
            expect(mover.read(), 1 if is_set else b"move", "mover reply")
            members = admin.must("SMEMBERS", dst) if is_set else admin.must("LRANGE", dst, 0, -1)
            require(sorted(members) == [b"base", b"kept", b"move"],
                    f"AT1: {verb} preserves the acknowledged destination write: {members!r}")
            stale_zero(admin)
            if not opened:
                raise WindowMiss("destination write did not finish inside both held windows")

    def blocking(self, verb):
        admin = self.admin
        key, other = self.key(self.a), self.key(self.b)
        require(_lib.shards_of(admin, [key, other]) ==
                [(self.a, self.owners[0]), (self.b, self.owners[1])], "blocking owner geometry")
        waiter, writer, blocker = self.conn(), self.conn(), self.conn()
        is_list = verb in ("BLPOP", "BRPOP", "BLMPOP")
        high = verb in ("BRPOP", "BZPOPMAX")
        with self.held_exec([key, other]) as holder:
            seed = ("RPUSH", key, "seed") if is_list else ("ZADD", key, 1, "seed")
            queued(writer, [seed])
            expect(writer.must("EXEC"), [1], "wake key EXEC record installed")
            # Leave an absent version behind the held read floor, as a waiting pop requires.
            writer.must("LPOP" if is_list else "ZPOPMIN", key)
            expect(stat(admin, "blocked_clients", "CLIENTS"), 0, "isolated blocking baseline")
            command = ((verb, 2, 1, key, "LEFT" if is_list else "MIN")
                       if verb in ("BLMPOP", "BZMPOP") else (verb, key, 2))
            waiter.send(*command)
            wait_for(lambda: stat(admin, "blocked_clients", "CLIENTS"), 1,
                     "waiter did not register")
            queued(blocker, [("SET", other, "unrelated")])
            before = stat(admin, "atomic_commit_windows")
            debug(admin, "ATOMIC-COMMIT-DELAY", 600000)
            blocker.send("EXEC")
            time.sleep(0.03)
            push = (("RPUSH", key, "wake", "kept") if is_list else
                    ("ZADD", key, 1, "wake", 2, "kept"))
            expect(writer.must(*push), 2, "wake push acknowledged")
            opened = (pending(blocker) and pending(holder) and
                      stat(admin, "atomic_commit_windows") > before)
            debug(admin, "ATOMIC-COMMIT-DELAY", 0)
            consumed, left, score = (b"kept", b"wake", b"2") if high else (b"wake", b"kept", b"1")
            wanted = ([key.encode(), [consumed]] if verb == "BLMPOP" else
                      [key.encode(), [[consumed, score]]] if verb == "BZMPOP" else
                      [key.encode(), consumed] if is_list else [key.encode(), consumed, score])
            expect(waiter.read(), wanted,
                   f"AT2: {verb} consumes the acknowledged wake push instead of re-parking")
            expect(blocker.read(), [b"OK"], "unrelated EXEC completed")
            expect(admin.must("LRANGE" if is_list else "ZRANGE", key, 0, -1), [left],
                   "AT2: unconsumed acknowledged element survives")
            stale_zero(admin)
            if not opened:
                raise WindowMiss("wake push did not land inside the reserved commit bracket")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--atomic", required=True, choices=("0", "1"))
    parser.add_argument("--case", choices=("movers", "blocking"))
    args = parser.parse_args()
    require(args.atomic == "0" or args.case != "movers", "AT1 non-atomic arm requires --atomic 0")
    admin = _lib.Conn(args.host, args.port, timeout=5)
    saved = {}
    try:
        # Stable actual owners, with all settings restored even on a failed assertion.
        for knob, value in (("atomic", args.atomic), ("key-lb", "0"),
                            ("client-lb", "0"), ("flip-auto", "0")):
            reply = admin.must("CONFIG", "GET", knob)
            require(isinstance(reply, list) and len(reply) == 2, "CONFIG GET " + knob)
            saved[knob] = reply[1]
            expect(admin.must("CONFIG", "SET", knob, value), b"OK", "CONFIG SET " + knob)
            expect(admin.must("CONFIG", "GET", knob)[1], value.encode(), "effective " + knob)
        stale_zero(admin)
        cases = []
        if args.atomic == "0" and args.case != "blocking":
            cases += [("mover", verb) for verb in ("SMOVE", "LMOVE", "RPOPLPUSH")]
        if args.case != "movers":
            cases += [("blocking", verb) for verb in
                      ("BLPOP", "BRPOP", "BLMPOP", "BZPOPMIN", "BZPOPMAX", "BZMPOP")]
        for method, verb in cases:
            for attempt in range(1, 5):
                race = Race(args.host, args.port, admin)
                try:
                    with race.stack:
                        getattr(race, method)(verb)
                    print(f"  PASS {verb} atomic={args.atomic} window opened attempt={attempt}", flush=True)
                    break
                except WindowMiss as error:
                    if attempt == 4:
                        raise AssertionError(f"{verb}: window never opened after four fresh attempts: {error}")
                    print(f"  re-arm {verb} on fresh state: {error}", flush=True)
        stale_zero(admin)
        print(f"ATOMIC PLAIN PASS atomic={args.atomic}: {len(cases)} witnessed races", flush=True)
    finally:
        for hook in ("ATOMIC-FANOUT-DEFER", "ATOMIC-OFF-HOP-DELAY"):
            debug(admin, hook, 0)
        for knob, value in reversed(list(saved.items())):
            expect(admin.must("CONFIG", "SET", knob, value), b"OK", "restore " + knob)
        admin.close()


if __name__ == "__main__":
    main()
