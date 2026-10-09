#!/usr/bin/env python3
"""Serverless FLIP/key-LB reload witnesses. No sockets, server processes, or real sleeps.

Run: python3 tests/debug_load_test.py -v
The scripted fake refuses the first load after an idle observation, then accepts the single
retry. Its command trace requires an idle wait on BOTH attempts; ignoring any error or waiting
on the controller's learning phase cannot pass these controls.
"""

from collections import deque
import sys
import unittest
from unittest.mock import patch

import _lib

with patch.object(sys, "argv", ["hexpire.py", "unused", "0"]):
    import hexpire


FLIP_ERROR = "ERR loading is not allowed while FLIP is in progress"
INFO = ("INFO", "SERVER", "LB")
RELOAD = ("DEBUG", "RELOAD")


def status(flip="0", lb="0", fused=False):
    topology = ("thread_mode:1s\r\nflip_available:0\r\n" if fused else
                "thread_mode:2s\r\nflip_in_progress:%s\r\n" % flip)
    # flip-auto=0 does not rule out a placement transition. The controller's phase likewise
    # says nothing about the actual FlipStage/LbStage sampled by loading_begin().
    return (topology + "flip_auto:0\r\nflipctl_phase:measuring\r\n"
            "tomokv_keylb_stage:%s\r\n" % lb).encode()


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def time(self):
        return 1700000000.0 + self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeServer:
    """A connection-shaped fake; every scripted command must be consumed in order."""

    def __init__(self, steps=(), repeated_info=None):
        self.steps = deque(steps)
        self.repeated_info = repeated_info
        self.commands = []
        self.sock = self
        self.timeout = 60.0  # edgeenc's socket deadline exceeds the helper's wait budget.
        self.timeouts = []

    def gettimeout(self):
        return self.timeout

    def settimeout(self, value):
        self.timeout = value
        self.timeouts.append(value)

    def cmd(self, *args):
        self.commands.append(args)
        if self.steps:
            command, reply = self.steps.popleft()
            if args != command:
                raise AssertionError("fake expected %r, got %r" % (command, args))
        else:
            if args != INFO or self.repeated_info is None:
                raise AssertionError("unexpected fake command: %r" % (args,))
            reply = self.repeated_info
        return reply() if callable(reply) else reply


class SnapshotServer(FakeServer):
    def __init__(self, clock, delays, replies=()):
        super().__init__()
        self.clock = clock
        self.delays = deque(delays)
        self.replies = deque(replies)

    def cmd(self, *args):
        self.commands.append(args)
        if args == INFO:
            return status()
        if args == RELOAD:
            self.clock.sleep(self.delays.popleft())
            return self.replies.popleft() if self.replies else "OK"
        if args[0] in ("FLUSHALL", "HSET", "HPEXPIREAT"):
            return "OK"
        raise AssertionError("unexpected snapshot command: %r" % (args,))


class DebugLoadTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        for module in (_lib, hexpire):
            patcher = patch.object(module, "time", self.clock)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_refusal_once_then_accepts_after_both_idle_waits(self):
        for error in (RuntimeError(FLIP_ERROR), _lib.RespError(FLIP_ERROR), Exception(FLIP_ERROR)):
            with self.subTest(error=type(error).__name__):
                server = FakeServer([
                    (INFO, status(flip="1")), (INFO, status()), (RELOAD, error),
                    (INFO, status(lb="3")), (INFO, status()), (RELOAD, "OK"),
                ])
                self.assertEqual(_lib.debug_load(server), "OK")
                self.assertFalse(server.steps)
                self.assertEqual(server.commands, [INFO, INFO, RELOAD, INFO, INFO, RELOAD])
                self.assertEqual(server.timeout, 60.0)

    def test_idle_success_loads_once_for_both_commands_and_ok_types(self):
        for subcommand in ("RELOAD", "LOADAOF"):
            for ok in ("OK", b"OK"):
                with self.subTest(subcommand=subcommand, ok=ok):
                    command = ("DEBUG", subcommand)
                    server = FakeServer([(INFO, status()), (command, ok)])
                    self.assertEqual(_lib.debug_load(server, subcommand), ok)
                    self.assertEqual(server.commands, [INFO, command])

    def test_second_exact_refusal_fails_without_a_third_load(self):
        error = RuntimeError(FLIP_ERROR)
        server = FakeServer([(INFO, status()), (RELOAD, error)] * 2)
        with self.assertRaisesRegex(AssertionError, FLIP_ERROR):
            _lib.debug_load(server)
        self.assertEqual(server.commands, [INFO, RELOAD, INFO, RELOAD])

    def test_other_errors_and_non_ok_replies_fail_without_retry(self):
        for reply in (RuntimeError("ERR Background save already in progress"),
                      RuntimeError("ERR DEBUG command not allowed"),
                      RuntimeError("ERR snapshot I/O failed"),
                      RuntimeError(FLIP_ERROR + "!"), RuntimeError(FLIP_ERROR + "\n"),
                      RuntimeError(FLIP_ERROR.removeprefix("ERR ")),
                      FLIP_ERROR, FLIP_ERROR.encode(), b"QUEUED", None, 1):
            with self.subTest(reply=reply):
                server = FakeServer([(INFO, status()), (RELOAD, reply)])
                with self.assertRaisesRegex(AssertionError, "DEBUG RELOAD required"):
                    _lib.debug_load(server)
                self.assertEqual(server.commands, [INFO, RELOAD])

    def test_permanent_flip_or_lb_times_out_without_loading(self):
        for body in (status(flip="1"), status(lb="1"), status(lb="4", fused=True)):
            with self.subTest(body=body):
                self.clock.now = 0.0
                server = FakeServer(repeated_info=body)
                with self.assertRaisesRegex(AssertionError, "did not become idle"):
                    _lib.debug_load(server)
                self.assertAlmostEqual(self.clock.now, 30.0)
                self.assertTrue(server.commands)
                self.assertTrue(all(command == INFO for command in server.commands))
                self.assertEqual(server.timeout, 60.0)
                self.assertLessEqual(max(server.timeouts[:-1]), 30.0)

    def test_retry_shares_the_original_wait_deadline(self):
        def late_idle():
            self.clock.sleep(20.0)
            return status()

        server = FakeServer([(INFO, late_idle), (RELOAD, RuntimeError(FLIP_ERROR))],
                            repeated_info=status(flip="1"))
        with self.assertRaisesRegex(AssertionError, "did not become idle"):
            _lib.debug_load(server)
        self.assertAlmostEqual(self.clock.now, 30.0)
        self.assertEqual(server.commands.count(RELOAD), 1)

    def test_slow_idle_reply_cannot_escape_wait_deadline(self):
        def late_idle():
            self.clock.sleep(30.1)
            return status()

        server = FakeServer([(INFO, late_idle)])
        with self.assertRaisesRegex(AssertionError, "did not become idle"):
            _lib.debug_load(server)
        self.assertEqual(server.commands, [INFO])
        self.assertEqual(server.timeout, 60.0)

    def test_fused_still_waits_for_key_lb(self):
        server = FakeServer([(INFO, status(lb="2", fused=True)),
                             (INFO, status(fused=True)), (RELOAD, b"OK")])
        self.assertEqual(_lib.debug_load(server), b"OK")
        self.assertEqual(server.commands, [INFO, INFO, RELOAD])

    def test_missing_or_malformed_witness_is_never_idle(self):
        for body in (b"", b"redis_version:7.4.10\r\n", status(flip="idle"), status(lb="idle"),
                     status().replace(b"flip_in_progress:0\r\n", b""),
                     status().replace(b"tomokv_keylb_stage:0\r\n", b""),
                     status(fused=True).replace(b"flip_available:0", b"flip_available:1"),
                     status().replace(b"thread_mode:2s", b"thread_mode:unknown"),
                     RuntimeError("ERR INFO failed")):
            with self.subTest(body=body):
                server = FakeServer([(INFO, body)])
                with self.assertRaises(AssertionError):
                    _lib.debug_load(server)
                self.assertEqual(server.commands, [INFO])
                self.assertEqual(server.timeout, 60.0)

    def test_connection_failure_is_not_retried(self):
        def disconnected():
            raise EOFError("server closed the connection")

        server = FakeServer([(INFO, status()), (RELOAD, disconnected)])
        with self.assertRaises(EOFError):
            _lib.debug_load(server)
        self.assertEqual(server.commands, [INFO, RELOAD])

    def test_expired_setup_rearms_fresh_state_without_inflating_checks(self):
        server = SnapshotServer(self.clock, [0.6, 0.1])
        checks = hexpire.CHECKS[0]
        hexpire.arm_snapshot_expiry(server)
        self.assertEqual(server.commands.count(("FLUSHALL",)), 2)
        self.assertEqual(server.commands.count(RELOAD), 2)
        deadlines = [int(args[2]) for args in server.commands if args[:2] == ("HPEXPIREAT", "mix")]
        self.assertEqual(len(set(deadlines)), 2)
        self.assertLess(int(self.clock.time() * 1000), deadlines[-1])
        self.assertEqual(hexpire.CHECKS[0], checks)
        self.assertEqual(hexpire.EXPECT_DEFAULT, 206)

    def test_window_never_opens_fails_after_three_fresh_attempts(self):
        server = SnapshotServer(self.clock, [0.6] * 3)
        with self.assertRaisesRegex(AssertionError, "window never armed in 3 fresh attempts"):
            hexpire.arm_snapshot_expiry(server)
        self.assertEqual(server.commands.count(("FLUSHALL",)), 3)
        self.assertEqual(server.commands.count(RELOAD), 3)

    def test_rearming_does_not_hide_a_failed_reload(self):
        server = SnapshotServer(self.clock, [0.6], [RuntimeError("ERR disk failure")])
        with self.assertRaisesRegex(AssertionError, "ERR disk failure"):
            hexpire.arm_snapshot_expiry(server)
        self.assertEqual(server.commands.count(("FLUSHALL",)), 1)
        self.assertEqual(server.commands.count(RELOAD), 1)


if __name__ == "__main__":
    unittest.main()
