#!/usr/bin/env python3
"""Serverless negative controls for the raw-wire oracle (no listening sockets)."""
import socket
import unittest
from unittest.mock import patch

import respcompat as wire


class ScriptedSocket:
    def __init__(self, events):
        self.events = list(events)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def setsockopt(self, *_):
        pass

    def settimeout(self, *_):
        pass

    def sendall(self, _):
        pass

    def recv(self, length):
        if not self.events:
            raise socket.timeout("connection stayed open")
        event = self.events.pop(0)
        if isinstance(event, Exception):
            raise event
        if len(event) > length:
            self.events.insert(0, event[length:])
        return event[:length]


class WireOracleTests(unittest.TestCase):
    error = wire.PREFIX + b"invalid multibulk length\r\n"
    case = wire.Case("bad count", ((b"*01\r\n", error),), True)

    def run_script(self, events, case=None):
        with patch.object(wire.socket, "create_connection", return_value=ScriptedSocket(events)):
            wire.run_case(("unused", 0), case or self.case)

    def test_fragmented_exact_error_and_close_pass(self):
        self.run_script([self.error[:2], self.error[2:17], self.error[17:], b""])

    def test_wrong_text_fails(self):
        with self.assertRaises(AssertionError):
            self.run_script([self.error.replace(b"Protocol", b"protocol"), b""])

    def test_missing_close_fails(self):
        with self.assertRaises(socket.timeout):
            self.run_script([self.error])

    def test_early_close_fails(self):
        with self.assertRaises(AssertionError):
            self.run_script([self.error[:-1], b""])

    def test_reply_after_error_fails(self):
        with self.assertRaises(AssertionError):
            self.run_script([self.error + wire.PONG, b""])

    def test_empty_array_reply_or_close_fails(self):
        case = wire.Case("empty", ((b"*0\r\n", None), (wire.PING, wire.PONG)))
        for unwanted in (b"*0\r\n", b""):
            with self.subTest(unwanted=unwanted), self.assertRaises(AssertionError):
                self.run_script([unwanted, wire.PONG], case)

    def test_empty_array_then_live_ping_passes(self):
        case = wire.Case("empty", ((b"*0\r\n", None), (wire.PING, wire.PONG)))
        self.run_script([socket.timeout(), wire.PONG], case)


if __name__ == "__main__":
    unittest.main()
