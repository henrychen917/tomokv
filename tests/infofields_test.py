#!/usr/bin/env python3
"""Serverless falsification of the differential's field, rate and MONITOR checks."""
import contextlib
import copy
import importlib.util
import io
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("infofields_differ", ROOT / "tests/differ.py")
differ = importlib.util.module_from_spec(spec)
with patch.object(sys, "argv", ["differ.py", "--list-generators"]), contextlib.redirect_stdout(io.StringIO()):
    try:
        spec.loader.exec_module(differ)
    except SystemExit as stopped:
        assert stopped.code == 0


class InfoFieldsControls(unittest.TestCase):
    def test_names_and_placement(self):
        fields = {section: {name: b"0" for name in names}
                  for section, names in differ.INFOFIELDS_REQUIRED.items()}
        differ.infofields_names(fields, fields)
        for section, required in differ.INFOFIELDS_REQUIRED.items():
            for name in required:
                with self.subTest(section=section, name=name):
                    missing = copy.deepcopy(fields)
                    del missing[section][name]
                    with self.assertRaises(AssertionError):
                        differ.infofields_names(missing, fields)
        misplaced = copy.deepcopy(fields)
        misplaced[b"Server"][b"role"] = misplaced[b"Replication"].pop(b"role")
        with self.assertRaises(AssertionError):
            differ.infofields_names(misplaced, fields)
        duplicate = copy.deepcopy(fields)
        duplicate[b"Server"][b"cluster_enabled"] = b"0"
        with self.assertRaises(AssertionError):
            differ.infofields_names(duplicate, fields)

    def test_sections_framing(self):
        body = b"# Server\r\nrun_id:a\r\n\r\n# Cluster\r\ncluster_enabled:0\r\n"
        raw = b"$%d\r\n" % len(body) + body + b"\r\n"
        self.assertEqual(set(differ.infofields_sections(raw)), {b"Server", b"Cluster"})
        for bad in (b"# Server\r\na:1\r\na:2\r\n", b"# Server\r\n# Server\r\n", b"a:1\r\n"):
            raw = b"$%d\r\n" % len(bad) + bad + b"\r\n"
            with self.assertRaises(AssertionError):
                differ.infofields_sections(raw)

    def test_rate_bounds(self):
        for rate in (1700, 2000, 2300):
            differ.infofields_rate_check(rate, 2000)
        for rate in (-1, 0, 1699, 2301, 10000):
            with self.assertRaises(AssertionError):
                differ.infofields_rate_check(rate, 2000)

    def test_monitor_bytes(self):
        quote = differ.monitor_quote(b'\x00\x07\x08\t\n\r"\\\x7f\xff')
        self.assertEqual(quote, b'"\\x00\\a\\b\\t\\n\\r\\"\\\\\\x7f\\xff"')
        line = b'+123.123456 [0 127.0.0.1:1234] "SET" "k" ' + quote + b"\r\n"
        payload = differ.monitor_payload(line, b"127.0.0.1:1234")
        self.assertEqual(payload, b'"SET" "k" ' + quote)
        for bad in (line.replace(b".123456", b".123"), line.replace(b"[0 ", b"[1 "),
                    line[:-1], line.replace(b"+123", b"$123")):
            with self.assertRaises(AssertionError):
                differ.monitor_payload(bad, b"127.0.0.1:1234")
        with self.assertRaises(AssertionError):
            differ.monitor_payload(line, b"127.0.0.1:9999")

    def test_monitor_inclusion_controls(self):
        expected = [b'"SET" "k" "v"', b'"PING" "done"']
        differ.monitor_check_streams(expected, expected, expected)
        for broken in ([], expected[1:], expected + [b'"CONFIG" "GET" "maxmemory"'],
                       expected + [b'"SET" "denied" "v"'],
                       [b'"SET" "k" "wrong-quote"', expected[-1]]):
            with self.assertRaises(AssertionError):
                differ.monitor_check_streams(broken, expected, expected)
        with self.assertRaises(AssertionError):
            differ.monitor_check_streams([], [], [])

    def test_monitor_generator_cannot_omit_denials(self):
        for seed in (7, 91):
            commands = differ.gen_monitor(random.Random(seed))
            self.assertTrue(any(args[:2] == ["CONFIG", "GET"] and not visible
                                for args, _, visible in commands))
            self.assertTrue(any(args[0] == "EVAL" and not visible for args, _, visible in commands))
            for error in (b"-NOPERM", b"-NOAUTH"):
                self.assertTrue(any(reply == error and not visible for _, reply, visible in commands))
            self.assertEqual(sum(visible for _, _, visible in commands), 8)


if __name__ == "__main__":
    unittest.main()
