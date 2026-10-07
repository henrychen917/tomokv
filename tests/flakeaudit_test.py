#!/usr/bin/env python3
"""Serverless controls: absent, wrong and late client witnesses must stay red."""
from collections import deque
import unittest
from unittest.mock import patch

import _client_wait


class Clock:
    now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, delay):
        self.now += delay


class Observer:
    def __init__(self, replies):
        self.replies = deque(replies)
        self.commands = []
        self.sock = self
        self.timeout = 30.0

    def gettimeout(self):
        return self.timeout

    def settimeout(self, value):
        self.timeout = value

    def cmd(self, *args):
        self.commands.append(args)
        reply = self.replies[0]
        if len(self.replies) > 1:
            self.replies.popleft()
        return reply() if callable(reply) else reply


class ClientWitnessTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        patcher = patch.object(_client_wait, "time", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_blocked_requires_this_clients_flag(self):
        observer = Observer([b"id=7 flags=N\n", b"id=7 flags=b\n"])
        _client_wait.wait_client_state(observer, 7, "blocked")
        self.assertEqual(observer.commands, [("CLIENT", "LIST", "ID", "7")] * 2)
        self.assertEqual(observer.timeout, 30.0)

    def test_gone_requires_empty_client_list(self):
        observer = Observer([b"id=7 flags=N\n", b""])
        _client_wait.wait_client_state(observer, 7, "gone")
        self.assertEqual(len(observer.commands), 2)
        self.assertEqual(observer.timeout, 30.0)

    def test_missing_window_never_passes(self):
        for state, reply in (("blocked", b""), ("blocked", b"id=7 flags=N\n"),
                             ("gone", b"id=7 flags=N\n")):
            with self.subTest(state=state, reply=reply):
                observer = Observer([reply])
                with self.assertRaisesRegex(AssertionError, "never became"):
                    _client_wait.wait_client_state(observer, 7, state, timeout=.02)
                self.assertEqual(observer.timeout, 30.0)

    def test_malformed_wrong_client_and_errors_fail_immediately(self):
        for reply in (b"id=8 flags=b\n", b"id=7\n", b"flags=b\n", RuntimeError("ERR"),
                      b"id=7 flags=b\nid=8 flags=b\n", b"garbage"):
            with self.subTest(reply=reply):
                observer = Observer([reply])
                with self.assertRaises((AssertionError, ValueError)):
                    _client_wait.wait_client_state(observer, 7, "blocked")
                self.assertEqual(len(observer.commands), 1)
                self.assertEqual(observer.timeout, 30.0)

    def test_late_success_is_not_a_witness(self):
        def late():
            self.clock.sleep(6)
            return b"id=7 flags=b\n"
        observer = Observer([late])
        with self.assertRaisesRegex(AssertionError, "exceeded deadline"):
            _client_wait.wait_client_state(observer, 7, "blocked")
        self.assertEqual(observer.timeout, 30.0)

    def test_transport_failure_is_not_retried(self):
        def closed():
            raise EOFError("closed")
        observer = Observer([closed])
        with self.assertRaises(EOFError):
            _client_wait.wait_client_state(observer, 7, "gone")
        self.assertEqual(len(observer.commands), 1)
        self.assertEqual(observer.timeout, 30.0)


if __name__ == "__main__":
    unittest.main()
