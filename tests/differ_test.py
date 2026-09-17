#!/usr/bin/env python3
"""Serverless controls for clock tolerance, including the real differential runners."""
import contextlib
import importlib.util
import io
from pathlib import Path
import random
import runpy
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SCALARS = ('EXPIRETIME', 'PEXPIRETIME', 'TTL', 'PTTL', 'OBJECT IDLETIME')
ARRAYS = ('HEXPIRETIME', 'HPEXPIRETIME', 'HTTL', 'HPTTL')


def integer(value):
    return b':%d\r\n' % value


def array(*values):
    return b'*%d\r\n' % len(values) + b''.join(integer(value) for value in values)


class ClockReplies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('differ_clock_controls', ROOT / 'tests/differ.py')
        cls.differ = importlib.util.module_from_spec(spec)
        with patch.object(sys, 'argv', ['differ.py', '--list-generators']), \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                spec.loader.exec_module(cls.differ)
            except SystemExit as stopped:
                if stopped.code != 0:
                    raise

    def setUp(self):
        self.enterContext(patch.object(self.differ, 'clock_tolerances', 0))
        self.enterContext(patch.object(self.differ.coverage, 'path', None))

    def compare(self, command, target, oracle):
        argv = command.split() + ['key']
        # Use the same normalizers as the main runner, so old TTL buckets cannot mask +/-2.
        target, oracle = [self.differ.normalize_introspection(argv[0], argv,
                          self.differ.normalize(argv[0], reply)) for reply in (target, oracle)]
        return self.differ.replies_equal(argv, target, oracle)

    def test_one_native_unit_in_both_directions_and_across_boundaries(self):
        for command in SCALARS + ARRAYS:
            for spelling in (command, command.lower()):
                encode = array if command in ARRAYS else integer
                for value in (1, 1000, 10000, 110460711, 1900000000000, (1 << 63) - 2):
                    for delta in (-2, -1, 0, 1, 2):
                        accepted = abs(delta) <= 1
                        if value == 1 and delta == -2:
                            accepted = False  # -1 is a persistent sentinel, not a time.
                        with self.subTest(command=spelling, value=value, delta=delta), \
                                contextlib.redirect_stdout(io.StringIO()) as log:
                            before = self.differ.clock_tolerances
                            self.assertEqual(self.compare(spelling, encode(value + delta), encode(value)),
                                             accepted)
                            used = accepted and delta != 0
                            self.assertEqual(self.differ.clock_tolerances - before, int(used))
                            self.assertEqual('CLOCK TOLERANCE' in log.getvalue(), used)

    def test_sentinels_stay_exact_in_scalars_and_arrays(self):
        for command in SCALARS + ARRAYS:
            encode = array if command in ARRAYS else integer
            for a, b in ((-2, -1), (-1, 0), (0, -1), (-1, -2), (-3, -2)):
                with self.subTest(command=command, values=(a, b)):
                    self.assertFalse(self.compare(command, encode(a), encode(b)))
            for sentinel in (-2, -1):
                self.assertTrue(self.compare(command, encode(sentinel), encode(sentinel)))
        self.assertEqual(self.differ.clock_tolerances, 0)

    def test_arrays_check_every_field_and_log_only_fully_tolerated_replies(self):
        with contextlib.redirect_stdout(io.StringIO()) as log:
            self.assertTrue(self.compare('HPTTL', array(101, -1, 199, -2), array(100, -1, 200, -2)))
            self.assertFalse(self.compare('HPTTL', array(101, -1, 202, -2), array(100, -1, 200, -2)))
            self.assertFalse(self.compare('HPTTL', array(101, -2), array(100, -1)))
            self.assertTrue(self.compare('TTL', integer(999), integer(1000)))
        self.assertEqual(self.differ.clock_tolerances, 2)
        self.assertEqual(log.getvalue().count('CLOCK TOLERANCE'), 2)
        self.assertIn('count=1 integers=2', log.getvalue())
        self.assertIn('count=2 integers=1', log.getvalue())
        self.assertIn(repr(array(101, -1, 199, -2)), log.getvalue())
        self.assertIn(repr(array(100, -1, 200, -2)), log.getvalue())

    def test_wire_types_lengths_errors_and_malformed_integers_stay_exact(self):
        pairs = [(integer(101), array(100)), (b'$4\r\n:101\r\n', integer(100)),
                 (b':+101\r\n', integer(100)), (b':0101\r\n', integer(100)),
                 (b':101\r\ntrailing', integer(100)), (b':101\n', integer(100)),
                 (integer(1 << 63), integer((1 << 63) - 1)),
                 (b'-ERR 101\r\n', b'-ERR 100\r\n'), (b'$-1\r\n', b'_\r\n'),
                 (array(101, 100), array(100)), (b'*2\r\n:101\r\n', array(100)),
                 (b'*01\r\n:101\r\n', array(100)), (b'~1\r\n:101\r\n', array(100)),
                 (b'*1\r\n$4\r\n:101\r\n', array(100)),
                 (b'*1\r\n*1\r\n:101\r\n', b'*1\r\n*1\r\n:100\r\n')]
        for command in SCALARS + ARRAYS:
            for a, b in pairs:
                with self.subTest(command=command, replies=(a, b)):
                    self.assertFalse(self.compare(command, a, b))
        self.assertEqual(self.differ.clock_tolerances, 0)

    def test_values_counts_lengths_and_expiry_status_codes_stay_exact(self):
        commands = ('GET', 'MGET', 'HGET', 'HGETALL', 'STRLEN', 'HSTRLEN', 'LLEN', 'HLEN',
                    'SCARD', 'ZCARD', 'DBSIZE', 'EXISTS', 'DEL', 'INCR', 'INCRBY',
                    'EXPIRE', 'PEXPIRE', 'HEXPIRE', 'HPEXPIRE', 'HEXPIREAT', 'HPEXPIREAT',
                    'PERSIST', 'HPERSIST', 'OBJECT REFCOUNT', 'OBJECT FREQ', 'XPENDING',
                    'EXEC', 'EVAL', 'FCALL')
        for command in commands:
            for encode in (integer, array, lambda n: b'$3\r\n%d\r\n' % n):
                for delta in (-1, 1):
                    with self.subTest(command=command, delta=delta):
                        self.assertFalse(self.compare(command, encode(100 + delta), encode(100)))
                        self.assertTrue(self.compare(command, encode(100), encode(100)))
        self.assertEqual(self.differ.clock_tolerances, 0)

    def connection(self, answer):
        # In-memory request/reply transport: exercise production routing without any listener.
        file = io.BytesIO()
        def send(payload):
            commands = io.BytesIO(payload)
            position = file.tell()
            file.seek(0, io.SEEK_END)
            while commands.tell() < len(payload):
                argv = self.differ.parse_reply(self.differ.read_reply(commands))
                file.write(answer(argv))
            file.seek(position)
        sock = Mock()
        sock.makefile.return_value = file
        sock.sendall.side_effect = send
        return sock, file

    def test_pipeline_uses_tolerance_and_preserves_failure_exit(self):
        for suite, verb, encode in (('string', b'TTL', integer), ('hexpire', b'HTTL', array),
                                    ('string', b'STRLEN', integer)):
            for delta in (-2, -1, 1, 2):
                def answer(argv, offset=0):
                    return encode(110460711 + offset) if argv[0].upper() == verb else b'+OK\r\n'
                target, _ = self.connection(lambda argv: answer(argv, delta))
                oracle, _ = self.connection(answer)
                with self.subTest(suite=suite, verb=verb, delta=delta), \
                        patch.object(sys, 'argv', ['differ.py', 'target', '1', 'oracle', '2', suite, '23']), \
                        patch('socket.create_connection', side_effect=[target, oracle]), \
                        contextlib.redirect_stdout(io.StringIO()) as log, self.assertRaises(SystemExit) as exit:
                    runpy.run_path(str(ROOT / 'tests/differ.py'), run_name='__main__')
                passed = verb != b'STRLEN' and abs(delta) == 1
                self.assertEqual(exit.exception.code, 0 if passed else 1)
                self.assertEqual('CLOCK TOLERANCE' in log.getvalue(), passed)
                self.assertIn('clock tolerances -> ' + ('PASS' if passed else 'FAIL'), log.getvalue())

    def test_wiredump_tolerates_only_expiry_and_never_hash_values(self):
        for delta, change_value in ((1, False), (-1, False), (2, False), (1, True)):
            def answer(argv, target=False):
                if argv[0] == b'HPEXPIRETIME':
                    return array(*([100 + (delta if target else 0)] * int(argv[3])))
                if argv[0] == b'PTTL':
                    return integer(100 + (delta if target else 0))
                if argv[0] == b'HGETALL':
                    return b'*2\r\n$1\r\nf\r\n$1\r\n' + (b'2' if target and change_value else b'1') + b'\r\n'
                if argv[0] == b'DUMP':
                    return b'$1\r\nx\r\n'
                return b'+OK\r\n'
            with self.subTest(delta=delta, change_value=change_value), \
                    patch.object(self.differ, 'conn', side_effect=[
                        self.connection(lambda argv: answer(argv, True)), self.connection(answer)]), \
                    contextlib.redirect_stdout(io.StringIO()) as log:
                diffs = self.differ.run_wiredump_suite(random.Random(23))
            passed = abs(delta) == 1 and not change_value
            self.assertEqual(diffs == 0, passed)
            self.assertEqual('CLOCK TOLERANCE' in log.getvalue(), abs(delta) == 1)
            self.assertIn('clock tolerances -> ' + ('PASS' if passed else 'FAIL'), log.getvalue())


if __name__ == '__main__':
    unittest.main()
