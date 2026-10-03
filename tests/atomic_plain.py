#!/usr/bin/env python3
"""AT1/AT2 lost-update races, against an isolated debug-enabled server.

Usage: atomic_plain.py HOST PORT --atomic 0|1 [--case movers|blocking]
       atomic_plain.py --self-test  (serverless harness controls)
Boot with --atomic MODE --enable-debug-command yes --key-lb 0 --client-lb 0 --flip-auto 0.
These settings are verified with CONFIG GET; the battery never changes configuration.
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
import sys
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


def verify_boot(admin, atomic):
    for knob, value in (("atomic", atomic), ("key-lb", "0"),
                        ("client-lb", "0"), ("flip-auto", "0")):
        reply = admin.must("CONFIG", "GET", knob)
        require(isinstance(reply, list) and len(reply) == 2 and reply[0] == knob.encode(),
                "CONFIG GET " + knob)
        expect(reply[1], value.encode(), f"boot with --{knob} {value}")


def reset_hooks(admin):
    # Attempt every reset and close even if one fails. Preserve the data/arming failure
    # already in flight; cleanup must not replace it with a second exception.
    failed = sys.exc_info()[0] is not None
    errors = []
    for hook in ("ATOMIC-FANOUT-DEFER", "ATOMIC-OFF-HOP-DELAY", "ATOMIC-COMMIT-DELAY"):
        try:
            debug(admin, hook, 0)
        except Exception as error:
            errors.append(error)
    if errors:
        if not failed:
            raise errors[0]
        for error in errors:
            print(f"DEBUG cleanup failed: {error}", file=sys.stderr)


def witnessed(opened, label):
    if not opened:
        raise WindowMiss(label)


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
            witnessed(pending(holder), "EXEC completed before the competing operation")
            yield holder
        finally:
            reset_hooks(self.admin)
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
            expect(writer.must(add, dst, "kept"), 1 if is_set else 2, "racing destination write acknowledged")
            opened &= pending(mover) and pending(holder)
            expect(mover.read(), 1 if is_set else b"move", "mover reply")
            members = admin.must("SMEMBERS", dst) if is_set else admin.must("LRANGE", dst, 0, -1)
            require(sorted(members) == [b"base", b"kept", b"move"],
                    f"AT1: {verb} preserves the acknowledged destination write: {members!r}")
            stale_zero(admin)
            witnessed(opened, "destination write did not finish inside both held windows")

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
            witnessed(opened, "wake push did not land inside the reserved commit bracket")


def run_case(host, port, admin, atomic, method, verb):
    for attempt in range(1, 5):
        race = Race(host, port, admin)
        try:
            with race.stack:
                getattr(race, method)(verb)
            print(f"  PASS {verb} atomic={atomic} window opened attempt={attempt}", flush=True)
            return
        except WindowMiss as error:
            if attempt == 4:
                raise AssertionError(f"{verb}: window never opened after four fresh attempts: {error}") from error
            print(f"  re-arm {verb} on fresh state: {error}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", nargs="?")
    parser.add_argument("port", nargs="?", type=int)
    parser.add_argument("--atomic", choices=("0", "1"))
    parser.add_argument("--case", choices=("movers", "blocking"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        if any(value is not None for value in (args.host, args.port, args.atomic, args.case)):
            parser.error("--self-test takes no live-server arguments")
        return self_test()
    if args.host is None or args.port is None or args.atomic is None:
        parser.error("HOST PORT --atomic 0|1 are required for live checks")
    require(args.atomic == "0" or args.case != "movers", "AT1 non-atomic arm requires --atomic 0")
    admin = _lib.Conn(args.host, args.port, timeout=5)
    try:
        verify_boot(admin, args.atomic)
        reset_hooks(admin)
        stale_zero(admin)
        cases = []
        if args.atomic == "0" and args.case != "blocking":
            cases += [("mover", verb) for verb in ("SMOVE", "LMOVE", "RPOPLPUSH")]
        if args.case != "movers":
            cases += [("blocking", verb) for verb in
                      ("BLPOP", "BRPOP", "BLMPOP", "BZPOPMIN", "BZPOPMAX", "BZMPOP")]
        for method, verb in cases:
            run_case(args.host, args.port, admin, args.atomic, method, verb)
        stale_zero(admin)
        print(f"ATOMIC PLAIN PASS atomic={args.atomic}: {len(cases)} witnessed races", flush=True)
    finally:
        try:
            reset_hooks(admin)
        finally:
            admin.close()


def self_test():
    """Exercise the real setup/retry/witness paths with no sockets or workers."""
    import io
    import socket
    import unittest
    from unittest import mock

    module = sys.modules[__name__]

    class Admin:
        def __init__(self, atomic="0"):
            self.config = {"atomic": atomic, "key-lb": "0", "client-lb": "0", "flip-auto": "0"}
            self.calls = []
            self.closed = False
            self.reject_debug = False

        def must(self, *command):
            self.calls.append(command)
            if command[:2] == ("CONFIG", "GET"):
                return [command[2].encode(), self.config[command[2]].encode()]
            if command[:2] == ("CONFIG", "SET"):
                raise _lib.RespError("ERR parameter is immutable at runtime")
            if command == ("DEBUG", "ATOMIC-PLAIN-STALE-CUTS"):
                return 0
            if command[0] == "DEBUG" and not self.reject_debug:
                return b"OK"
            raise _lib.RespError("injected DEBUG cleanup failure")

        def close(self):
            self.closed = True

    class HarnessControls(unittest.TestCase):
        def setUp(self):
            self.output = io.StringIO()
            self.enterContext(contextlib.redirect_stdout(self.output))
            self.enterContext(mock.patch.object(socket, "create_connection",
                                               side_effect=AssertionError("self-test opened a socket")))

        def test_boot_only_setup_and_cleanup_both_modes(self):
            for atomic, count in (("0", 9), ("1", 6)):
                admin = Admin(atomic)
                with mock.patch.object(_lib, "Conn", return_value=admin), \
                        mock.patch.object(module, "run_case") as run:
                    main(["unused", "1", "--atomic", atomic])
                self.assertEqual(run.call_count, count)
                self.assertTrue(admin.closed)
                self.assertFalse(any(c[:2] == ("CONFIG", "SET") for c in admin.calls))
                self.assertIn(f"{count} witnessed races", self.output.getvalue())

        def test_wrong_boot_is_a_failure_before_any_race(self):
            for knob in ("atomic", "key-lb", "client-lb", "flip-auto"):
                admin = Admin()
                admin.config[knob] = "1"
                with self.subTest(knob=knob), mock.patch.object(_lib, "Conn", return_value=admin), \
                        mock.patch.object(module, "run_case") as run:
                    with self.assertRaisesRegex(AssertionError, "boot with --" + knob):
                        main(["unused", "1", "--atomic", "0"])
                    run.assert_not_called()
                    self.assertTrue(admin.closed)

        def test_cleanup_preserves_the_original_failure(self):
            admin = Admin()

            def fail(*args):
                admin.reject_debug = True
                raise AssertionError("named lost-write assertion")

            with mock.patch.object(_lib, "Conn", return_value=admin), \
                    mock.patch.object(module, "run_case", side_effect=fail), \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                with self.assertRaisesRegex(AssertionError, "named lost-write assertion"):
                    main(["unused", "1", "--atomic", "0"])
            self.assertTrue(admin.closed)
            self.assertEqual(errors.getvalue().count("DEBUG cleanup failed:"), 3)

        def test_missing_probe_never_arms(self):
            with mock.patch.object(time, "monotonic", side_effect=(0, 0, 1)), \
                    mock.patch.object(time, "sleep"):
                with self.assertRaisesRegex(WindowMiss, "counter never advanced"):
                    wait_for(lambda: False, True, "counter never advanced")

        def attempts(self, failures):
            instances = []

            class Attempt:
                def __init__(self, *args):
                    instances.append(self)
                    self.stack = contextlib.ExitStack()
                    self.closed = False
                    self.stack.callback(self.close)

                def close(self):
                    self.closed = True

                def mover(self, verb):
                    error = next(failures)
                    if error is not None:
                        raise error

            return Attempt, instances

        def test_unentered_window_fails_after_four_fresh_attempts(self):
            attempt, instances = self.attempts(iter([WindowMiss("unentered")] * 4))
            with mock.patch.object(module, "Race", attempt):
                with self.assertRaisesRegex(AssertionError, "window never opened after four fresh attempts"):
                    run_case("unused", 1, None, "0", "mover", "SMOVE")
            self.assertEqual(len(instances), 4)
            self.assertEqual(len({id(r) for r in instances}), 4)
            self.assertTrue(all(r.closed for r in instances))
            self.assertNotIn("PASS", self.output.getvalue())

        def test_rearm_requires_a_successful_fresh_window(self):
            attempt, instances = self.attempts(iter([WindowMiss("unentered")] * 3 + [None]))
            with mock.patch.object(module, "Race", attempt):
                run_case("unused", 1, None, "0", "mover", "SMOVE")
            self.assertEqual(len(instances), 4)
            self.assertTrue(all(r.closed for r in instances))
            self.assertEqual(self.output.getvalue().count("PASS"), 1)
            self.assertIn("attempt=4", self.output.getvalue())

        def test_data_reply_and_counter_failures_are_not_retried(self):
            for error in (AssertionError("lost data"), AssertionError("stale cut"),
                          TimeoutError("lost reply")):
                attempt, instances = self.attempts(iter([error]))
                with self.subTest(error=str(error)), mock.patch.object(module, "Race", attempt):
                    with self.assertRaises(type(error)) as caught:
                        run_case("unused", 1, None, "0", "mover", "SMOVE")
                    self.assertIs(caught.exception, error)
                self.assertEqual(len(instances), 1)
                self.assertTrue(instances[0].closed)

        def test_correct_data_without_each_window_witness_still_fails(self):
            # Drive the actual race bodies. Every data reply is correct; removing any
            # pending-reply/counter witness must still refuse the round.
            for method, verbs, missing in (
                    ("mover", ("SMOVE", "LMOVE", "RPOPLPUSH"), ("operation", "holder")),
                    ("blocking", ("BLPOP", "BRPOP", "BLMPOP", "BZPOPMIN", "BZPOPMAX", "BZMPOP"),
                     ("operation", "holder", "commit counter"))):
                for verb in verbs:
                    for absent in (None, *missing):
                        with self.subTest(verb=verb, absent=absent), contextlib.ExitStack() as stack:
                            race = Race.__new__(Race)
                            race.admin = mock.Mock()
                            race.a, race.b, race.owners = 0, 1, (6, 7)
                            race.key = mock.Mock(side_effect=("source", "target"))
                            waiter, writer, blocker, holder = (mock.Mock() for _ in range(4))
                            race.conn = mock.Mock(side_effect=(waiter, writer, blocker))

                            @contextlib.contextmanager
                            def held(keys):
                                yield holder

                            race.held_exec = held
                            writer.must.side_effect = [b"OK", b"QUEUED", [1]] + (
                                [b"seed", 2] if method == "blocking" else [1 if verb == "SMOVE" else 2])
                            blocker.must.side_effect = [b"OK", b"QUEUED"]
                            blocker.read.return_value = [b"OK"]
                            high = verb in ("BRPOP", "BZPOPMAX")
                            consumed, left, score = (b"kept", b"wake", b"2") if high else (
                                b"wake", b"kept", b"1")
                            waiter.read.return_value = (
                                1 if verb == "SMOVE" else b"move" if method == "mover" else
                                [b"source", [consumed]] if verb == "BLMPOP" else
                                [b"source", [[consumed, score]]] if verb == "BZMPOP" else
                                [b"source", consumed] if verb in ("BLPOP", "BRPOP") else
                                [b"source", consumed, score])

                            def answer(*command):
                                if command[0] == "DEBUG":
                                    return 0 if command[1] == "ATOMIC-PLAIN-STALE-CUTS" else b"OK"
                                if command[0] in ("SADD", "RPUSH"):
                                    return 1
                                if command[0] in ("SISMEMBER", "LLEN"):
                                    return 0
                                return [b"base", b"kept", b"move"] if method == "mover" else [left]

                            race.admin.must.side_effect = answer
                            stack.enter_context(mock.patch.object(_lib, "shards_of", return_value=[(0, 6), (1, 7)]))
                            operation = waiter if method == "mover" else blocker
                            stack.enter_context(mock.patch.object(module, "pending", side_effect=lambda conn:
                                not (absent == "operation" and conn is operation or
                                     absent == "holder" and conn is holder)))
                            stack.enter_context(mock.patch.object(module, "stat", side_effect=(
                                0, 1, 0, 0 if absent == "commit counter" else 1)))
                            stack.enter_context(mock.patch.object(time, "sleep"))
                            if absent is None:
                                getattr(race, method)(verb)
                            else:
                                with self.assertRaises(WindowMiss):
                                    getattr(race, method)(verb)

    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(HarnessControls))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
