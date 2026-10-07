#!/usr/bin/env python3
"""Serverless mutation/fragmentation controls. Never imports a live battery's main body."""
import ast
from contextlib import closing, contextmanager
import io
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def definitions(file, names, **namespace):
    tree = ast.parse((ROOT / file).read_text())
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
             and node.name in names]
    assert {node.name for node in nodes} == set(names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), file, "exec"), namespace)
    return namespace


class Fragments(io.RawIOBase):
    def __init__(self, data):
        self.data = io.BytesIO(data)

    def readable(self):
        return True

    def readinto(self, buffer):
        piece = self.data.read(min(len(buffer), 1))
        buffer[:len(piece)] = piece
        return len(piece)


class WireControls(unittest.TestCase):
    def test_tracking_push_one_byte_fragments(self):
        cls = definitions("tests/tracking.py", ["Conn"])["Conn"]
        conn = object.__new__(cls)
        expected = b">2\r\n$10\r\ninvalidate\r\n*1\r\n$3\r\nkey\r\n"
        conn.file = Fragments(expected)
        self.assertEqual(conn.raw_reply(), expected)
        conn.file = Fragments(expected[:-1])
        with self.assertRaises(EOFError):
            conn.raw_reply()

    def test_acl_coded_reply_mutation_is_preserved_as_extra_frame(self):
        read = definitions("tests/aclreply.py", ["raw_reply"])["raw_reply"]
        denial = b"-NOPERM User u has no permissions to run the 'blpop' command\r\n"
        fence = b"$5\r\nfence\r\n"
        for coded in (b"*-1\r\n", b"_\r\n"):
            with io.BufferedReader(Fragments(coded + denial + fence)) as wire:
                got = b""
                while (frame := read(wire)) != fence:
                    got += frame
            self.assertEqual(got, coded + denial)
            self.assertNotEqual(got, denial)  # Original clear_reply mutation still loses.
        with io.BufferedReader(Fragments(b"$3\r\nab")) as wire:
            with self.assertRaises(AssertionError):
                read(wire)

    def test_ktls_fragmented_info_keeps_positive_gauge(self):
        source = (ROOT / "tests/gate.sh").read_text()
        block = source.split('with s.makefile("rb") as wire:\n', 1)[1].split('\nPYEOF', 1)[0]
        code = 'with s.makefile("rb") as wire:\n' + block
        for gauge in (1, 0):
            body = b"# Stats\r\ntls_ktls_active:%d\r\n" % gauge
            raw = b"$%d\r\n" % len(body) + body + b"\r\n"
            sock = SimpleNamespace(makefile=lambda mode: io.BufferedReader(Fragments(raw)),
                                   close=lambda: None)
            if gauge:
                exec(code, dict(s=sock))
            else:
                with self.assertRaisesRegex(AssertionError, "kTLS did not engage"):
                    exec(code, dict(s=sock))

    def test_armed_highwater_survives_reset_but_malformed_info_fails(self):
        source = (ROOT / "tests/gate.sh").read_text()
        fn = "sample_armed_lane(){" + source.split("sample_armed_lane(){", 1)[1].split("\n}", 1)[0] + "\n}"
        with tempfile.TemporaryDirectory() as temp:
            script = fn + r'''
redis-cli(){ printf '%s\n' "$MOCK_INFO"; }
AT=0; ARMED_HITS=0; ARMED_SAMPLE_FAILED=0
MOCK_INFO=$'read_local_keyspace_hits:7\nread_local_mget_local_hits:2'
sample_armed_lane before_reset || exit 1
MOCK_INFO=$'read_local_keyspace_hits:0\nread_local_mget_local_hits:0'
sample_armed_lane after_reset || exit 2
[ "$ARMED_HITS" = 9 ] || exit 3
MOCK_INFO='read_local_keyspace_hits:1'
if sample_armed_lane missing; then exit 4; fi
[ "$ARMED_SAMPLE_FAILED" = 1 ] || exit 5
MOCK_INFO=$'read_local_keyspace_hits:bad\nread_local_mget_local_hits:0'
if sample_armed_lane malformed; then exit 6; fi
'''
            subprocess.run(["bash", "-c", 'TMPDIR="$1"\n' + script, "control", temp], check=True)


class Clock:
    def __init__(self):
        self.now = 1.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class ExpiryControls(unittest.TestCase):
    def arm(self, *, late=0, broken=False):
        clock = Clock()
        class Fake:
            attempts = 0
            def cmd(self, *args):
                if args[0] == "DEL":
                    self.attempts += 1
                    return 1
                if args[0] == "HSET":
                    return 3
                if args[0] == "TIME":
                    return [int(clock.now), int(clock.now % 1 * 1000000)]
                if args[0] == "INFO":
                    return b"expired_hash_fields:0\r\nhash_field_expires:1\r\n"
                if args[0] == "HPEXPIRE":
                    self.expiry = int(clock.now * 1000) + int(args[2])
                    return "QUEUED"
                if args[0] == "HPEXPIRETIME":
                    return "QUEUED"
                if args[0] == "MULTI":
                    return "OK"
                if args[0] == "EXEC":
                    return [[0, 0] if broken else [1, 1], [self.expiry, self.expiry]]
                if args[0] == "HLEN":
                    if self.attempts <= late:
                        clock.now += 1
                    return 3
                raise AssertionError(args)
        fake = Fake()
        arm = definitions("tests/hexpire.py", ["server_ms", "arm_live_fields", "info_counter"],
                          time=clock)["arm_live_fields"]
        return arm, fake

    def test_missed_live_window_recreates_state(self):
        arm, fake = self.arm(late=1)
        self.assertEqual(arm(fake, "k", ("a", "1", "b", "2", "c", "3"),
                             ("a", "b"), 250)[:3], ([1, 1], 1, 3))
        self.assertEqual(fake.attempts, 2)

    def test_never_live_cannot_pass(self):
        arm, fake = self.arm(late=100)
        with self.assertRaisesRegex(AssertionError, "window never opened"):
            arm(fake, "k", ("a", "1", "b", "2", "c", "3"), ("a", "b"), 250)

    def test_wrong_arm_reply_is_not_retried(self):
        arm, fake = self.arm(broken=True)
        with self.assertRaisesRegex(AssertionError, "arm failed"):
            arm(fake, "k", ("a", "1", "b", "2", "c", "3"), ("a", "b"), 250)
        self.assertEqual(fake.attempts, 1)


class AtomicControls(unittest.TestCase):
    def observe(self, *, missing=False, private=False, escape=False):
        state = dict(held=False, predecessors=0, installed=0)
        clock = Clock()
        class Fake:
            sock = object()
            def __init__(self, *args):
                pass
            def close(self):
                pass
            def cmd(self, *args):
                if args[0] == "SET":
                    return b"QUEUED" if state["held"] else b"OK"
                if args[0] == "MULTI":
                    return b"OK"
                if args[0] == "MGET":
                    state["predecessors"] += len(args) - 1
                    return [b"held" if private or not state["held"] else b"0"] * (len(args) - 1)
                raise AssertionError(args)
            def send(self, *args):
                assert args == ("EXEC",)
                state["installed"] = 0 if missing else 8
            def read(self):
                assert not state["held"]
                return [b"OK"] * 8
        @contextmanager
        def armed(*args):
            state["held"] = True
            try:
                yield
            finally:
                state["held"] = False
        def info(*args):
            return dict(atomic_pending_entries=state["installed"],
                        atomic_predecessor_reads=state["predecessors"])
        fn = definitions("tests/multi_exec.py", ["held_exec_cut"], HOST="fake", PORT=0,
            closing=closing, time=clock,
            select=SimpleNamespace(select=lambda *args: ([Fake.sock] if escape else [], [], [])),
            _lib=SimpleNamespace(Conn=Fake, armed=armed, info=info))["held_exec_cut"]
        fn(list(range(8)))

    def test_held_cut_reads_old_then_new(self):
        self.observe()

    def test_missing_install_cannot_pass(self):
        with self.assertRaisesRegex(AssertionError, "never installed"):
            self.observe(missing=True)

    def test_private_values_fail(self):
        with self.assertRaisesRegex(AssertionError, "private values"):
            self.observe(private=True)

    def test_disabled_hold_fails(self):
        with self.assertRaisesRegex(AssertionError, "escaped commit hold"):
            self.observe(escape=True)


class DifferentialWaitControls(unittest.TestCase):
    def observe(self, *, late_first=False, never_parked=False, early_reply=False):
        clock = Clock()
        opened = []
        mismatches = []
        class Fake:
            def __init__(self, admin=False):
                self.admin = admin
                self.id = len(opened) + 1
                if not admin:
                    opened.append(self)
                self.args = None
            def sendall(self, args):
                self.args = args
            def close(self):
                pass
        admins = [Fake(True), Fake(True)]
        late = [late_first]
        def read(sock):
            if sock.args[:2] == ["CLIENT", "ID"]:
                return b":%d\r\n" % sock.id
            if sock.args[:2] == ["CLIENT", "LIST"]:
                if late[0]:
                    clock.now += .25
                    late[0] = False
                if never_parked:
                    clock.now += .05
                return b"id=%s flags=%s cmd=wait\n" % (
                    sock.args[-1].encode(), b"N" if never_parked else b"b")
            assert sock.args[0] == "WAIT"
            clock.now += .2
            return b":0\r\n"
        def compare(label, actual, wanted):
            if actual != wanted:
                mismatches.append((label, actual, wanted))
        tree = ast.parse((ROOT / "tests/differ.py").read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == "run_blocking_differ")
        block = next(n for n in function.body if isinstance(n, ast.For)
                     and isinstance(n.target, ast.Name) and n.target.id == "timeout")
        namespace = dict(time=clock, conn_mode=lambda *a: (lambda c: (c, c))(Fake()),
            TH="fake", TP=0, OH="fake", OP=0, RESP3=False,
            ts=admins[0], tf=admins[0], os_=admins[1], of=admins[1],
            enc=lambda args: args, read_reply=read, parse_reply=lambda raw: raw,
            logical_ops=0, property_check=compare, compare=compare,
            select=SimpleNamespace(select=lambda *a: ([a[0][0]] if early_reply else [], [], [])))
        with patch("builtins.print"):
            exec(compile(ast.Module(body=[block], type_ignores=[]), "WAIT arm", "exec"), namespace)
        return opened, mismatches

    def test_valid_parked_deadlines_pass(self):
        opened, wrong = self.observe()
        self.assertEqual(len(opened), 4)
        self.assertEqual(wrong, [])

    def test_missed_deadline_rearms_fresh_clients(self):
        opened, wrong = self.observe(late_first=True)
        self.assertEqual(len(opened), 6)
        self.assertEqual(wrong, [])

    def test_never_parked_cannot_pass(self):
        with self.assertRaisesRegex(AssertionError, "window never opened"):
            self.observe(never_parked=True)

    def test_early_reply_fails_without_rearming(self):
        opened, wrong = self.observe(early_reply=True)
        self.assertEqual(len(opened), 4)
        self.assertEqual(len(wrong), 4)  # Both peers, finite and timeout-zero arms.


if __name__ == "__main__":
    unittest.main(verbosity=2)
