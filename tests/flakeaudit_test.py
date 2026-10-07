#!/usr/bin/env python3
"""Serverless controls: absent, wrong and late client witnesses must stay red."""
from collections import deque
import ast
from pathlib import Path
import unittest
from unittest.mock import patch

import _client_wait


def definitions(filename, names, namespace):
    """Load only real helpers; the batteries' module bodies open live sockets."""
    tree = ast.parse((Path(__file__).parent / filename).read_text())
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in tree.body} == set(names)
    exec(compile(tree, filename, "exec"), namespace)
    return namespace


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


class PersistenceWitnessTests(unittest.TestCase):
    def test_idle_sync_waits_for_counter_and_preserves_policy_age(self):
        clock = Clock()
        def info(_):
            return {"aof_fsyncs": 4 if clock.now < 1.8 else 5}
        ns = definitions("aof_fsync.py", ["wait_idle_sync"], dict(time=clock, info=info))
        self.assertEqual(ns["wait_idle_sync"](None, {"aof_fsyncs": 4}), {"aof_fsyncs": 5})
        self.assertGreaterEqual(clock.now, 1.8)
        clock.now = 0
        ns["info"] = lambda _: {"aof_fsyncs": 5}
        ns["wait_idle_sync"](None, {"aof_fsyncs": 4})
        self.assertGreaterEqual(clock.now, 1.25)

    def test_absent_sync_fails(self):
        clock = Clock()
        ns = definitions("aof_fsync.py", ["wait_idle_sync"],
                         dict(time=clock, info=lambda _: {"aof_fsyncs": 4}))
        with self.assertRaisesRegex(AssertionError, "not witnessed"):
            ns["wait_idle_sync"](None, {"aof_fsyncs": 4}, timeout=2)

    def test_save_must_finish_and_publish_valid_state(self):
        clock = Clock()
        values = deque([b"1", b"1", b"0"])
        ns = definitions("snap_cut_battery.py", ["wait_save_idle"],
                         dict(time=clock, info_field=lambda _: values.popleft()))
        ns["wait_save_idle"]()
        self.assertFalse(values)
        for value in (None, b"bad", b"1"):
            ns["info_field"] = lambda _, v=value: v
            with self.assertRaises(AssertionError):
                ns["wait_save_idle"](timeout=1)

    def test_raw_load_keeps_exact_success_and_corruption_oracles(self):
        refusal = b"-ERR loading is not allowed while FLIP is in progress\r\n"
        corrupt = b"-ERR Error trying to load the AOF, check server logs.\r\n"
        for expected in (b"+OK\r\n", corrupt):
            with self.subTest(expected=expected):
                client = Observer([refusal, expected])
                client.command = client.cmd
                waits = []
                ns = definitions("aof.py", ["bulk_payload", "expect_loadaof"],
                                 dict(c=client, time=Clock(), wait_flip_idle=lambda *args: waits.append(args)))
                self.assertEqual(ns["expect_loadaof"](expected), expected)
                self.assertEqual(len(waits), 2)
                self.assertEqual(client.commands, [("DEBUG", "LOADAOF")] * 2)
                self.assertIs(waits[0][0].sock, client.sock)
                # INFO stays on the same connection and is decoded for the existing barrier.
                client.replies = deque([b"$3\r\nx:y\r\n"])
                self.assertEqual(waits[0][0].command("INFO", "SERVER", "LB"), b"x:y")

    def test_raw_load_never_retries_data_errors_or_accepts_two_refusals(self):
        refusal = b"-ERR loading is not allowed while FLIP is in progress\r\n"
        for reply, calls in ((b"-ERR corruption\r\n", 1), (refusal, 2), (b"+OK\n", 1)):
            client = Observer([reply])
            client.command = client.cmd
            ns = definitions("aof.py", ["expect_loadaof"],
                             dict(c=client, time=Clock(), wait_flip_idle=lambda *args: None))
            with self.assertRaises(AssertionError):
                ns["expect_loadaof"](b"+OK\r\n")
            self.assertEqual(len(client.commands), calls)


if __name__ == "__main__":
    unittest.main()
