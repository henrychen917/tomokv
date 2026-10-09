"""Serverless negative controls for the ACL differential's parking witness."""
import unittest
from unittest.mock import patch

import _differ_aclkeys as suite


class Clock:
    now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, delay):
        self.now += delay


class WitnessTests(unittest.TestCase):
    def observe(self, replies, early=False, late=False):
        clock = Clock()
        calls = []

        def issue(_pair, args):
            calls.append(args)
            if late:
                clock.now = 1.0
            result = replies[min(len(calls) - 1, len(replies) - 1)]
            return result

        with patch.object(suite, "time", clock), patch.object(suite.select, "select",
                return_value=(["blocked"] if early else [], [], [])):
            suite.wait_blocked("admin", ("blocked", "file"), 7, issue,
                               lambda value: value, lambda _file: suite.DENIED, timeout=.02)
        return calls

    def test_requires_exact_client_then_blocked_flag(self):
        calls = self.observe([b"id=7 flags=N\n", b"id=7 flags=b\n"])
        self.assertEqual(calls, [["CLIENT", "LIST", "ID", "7"]] * 2)

    def test_early_denial_fails_before_revocation(self):
        with self.assertRaisesRegex(AssertionError, "replied before parking"):
            self.observe([b"id=7 flags=N\n"], early=True)

    def test_never_parked_fails(self):
        with self.assertRaisesRegex(AssertionError, "never parked"):
            self.observe([b"id=7 flags=N\n"])

    def test_malformed_and_wrong_client_fail(self):
        for reply in (b"", b"id=8 flags=b\n", b"id=7\n", b"id=7 flags=b\nid=8 flags=b\n"):
            with self.subTest(reply=reply), self.assertRaises(AssertionError):
                self.observe([reply])

    def test_late_witness_fails(self):
        with self.assertRaisesRegex(AssertionError, "never parked"):
            self.observe([b"id=7 flags=b\n"], late=True)

    def test_requested_command_timeout_matrix(self):
        for timeout in ("0", "1"):
            rows = suite.cases(timeout, "block:test")
            self.assertEqual([row[0][0] for row in rows],
                             ["BLPOP", "BRPOP", "BLMPOP", "BZPOPMIN", "XREAD"])
            self.assertEqual(rows[0][0], ["BLPOP", "block:test", timeout])
            self.assertEqual(rows[2][0], ["BLMPOP", timeout, "1", "block:test", "LEFT"])
            self.assertEqual(rows[4][0], ["XREAD", "BLOCK", timeout, "STREAMS", "block:test", "0"])


if __name__ == "__main__":
    unittest.main()
