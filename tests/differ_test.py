#!/usr/bin/env python3
"""Serverless deadline controls, including the real differential comparison loops."""
import ast
import contextlib
import importlib.util
import io
import itertools
from pathlib import Path
import random
import runpy
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
MS = 1000000


def integer(value):
    return b':%d\r\n' % value


def array(*values):
    return b'*%d\r\n' % len(values) + b''.join(integer(value) for value in values)


class DeadlineReplies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('differ_controls', ROOT / 'tests/differ.py')
        cls.differ = importlib.util.module_from_spec(spec)
        with patch.object(sys, 'argv', ['differ.py', '--list-generators']), \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                spec.loader.exec_module(cls.differ)
            except SystemExit as stopped:
                if stopped.code != 0:
                    raise

    def setUp(self):
        self.enterContext(patch.object(self.differ, 'deadline_bounded_ttl_checks', 0))
        self.enterContext(patch.object(self.differ.coverage, 'path', None))
        self.log = self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def window(self, start=1000, elapsed=10):
        return self.differ.ReplyWindow(start, int(elapsed * MS))

    def states(self, fields=False):
        states = (self.differ.TtlDeadlines(), self.differ.TtlDeadlines())
        argv = ['HPEXPIREAT', 'key', '100000', 'FIELDS', '2', 'a', 'b'] if fields else \
               ['PEXPIREAT', 'key', '100000']
        for state in states:
            state.observe(argv, array(1, 1) if fields else integer(1), self.window())
        return states

    def compare(self, name, a, b, states=None, windows=None):
        argv = [name, 'key']
        if name.upper() in ('HTTL', 'HPTTL'):
            argv += ['FIELDS', '2', 'a', 'b']
        return self.differ.replies_equal(argv, a, b, states, windows)

    def test_independent_seven_ms_cuts_and_equal_positive_replies(self):
        states = self.states()
        windows = (self.window(1000, 10), self.window(1000, 1))
        self.assertTrue(self.compare('PTTL', integer(98992), integer(98999), states, windows))
        self.assertTrue(self.compare('pttl', integer(98999), integer(98999), states, windows))
        self.assertEqual(self.differ.deadline_bounded_ttl_checks, 2)

    def test_boundaries_and_negative_control_reject_identical_wrong_ttls(self):
        states = self.states()
        windows = (self.window(1000, 2),) * 2  # cut offset must be in [0, 3] ms
        for cut, accepted in ((999, False), (1000, True), (1003, True), (1004, False)):
            with self.subTest(cut=cut):
                reply = integer(100000 - cut)
                self.assertEqual(self.compare('PTTL', reply, reply, states, windows), accepted)
        self.assertIn('TTL DEADLINE FAIL', self.log.getvalue())
        # No rounding up elapsed latency: 3 ms is outside a 2.25 ms bound.
        self.assertFalse(self.compare('PTTL', integer(98997), integer(98997), states,
                                      (self.window(1000, 1.25),) * 2))

    def test_each_server_needs_its_own_bound(self):
        states = self.states()
        windows = (self.window(1000, 10), self.window(1000, 1))
        self.assertFalse(self.compare('PTTL', integer(98999), integer(98992), states, windows))
        self.assertIn('side=oracle', self.log.getvalue())

    def test_missing_deadline_or_timing_is_a_failure_even_for_equal_replies(self):
        reply = integer(98999)
        self.assertFalse(self.compare('PTTL', reply, reply))
        self.assertFalse(self.compare('PTTL', reply, reply, self.states()))
        empty = (self.differ.TtlDeadlines(), self.differ.TtlDeadlines())
        self.assertFalse(self.compare('PTTL', reply, reply, empty, (self.window(),) * 2))

    def test_seconds_rounding_is_inverted_not_tolerated(self):
        # Redis TTL rounds nearest, HTTL rounds up. Each boundary is checked on
        # both sides with a zero-elapsed request (only the specified 1 ms slack).
        for name, durations in (('TTL', (499, 500, 501, 1499, 1500, 1501)),
                                ('HTTL', (1, 999, 1000, 1001, 1999, 2000))):
            for remaining in durations:
                deadline = ((1000 + remaining) * MS,) * 2
                value = (remaining + (500 if name == 'TTL' else 999)) // 1000
                with self.subTest(name=name, remaining=remaining):
                    self.assertTrue(self.differ.ttl_within_deadline(name, value, deadline,
                                                                   self.window(1000, 0)))
                    self.assertFalse(self.differ.ttl_within_deadline(name, value + 2, deadline,
                                                                    self.window(1000, 0)))
        # A one-second difference is not automatically accepted.
        deadline = (100000 * MS,) * 2
        self.assertFalse(self.differ.ttl_within_deadline('TTL', 98, deadline, self.window(1000, 0)))
        self.assertFalse(self.differ.ttl_within_deadline('HTTL', 100, deadline, self.window(1000, 0)))

    def test_sentinels_zero_and_arrays(self):
        states = self.states(True)
        windows = (self.window(),) * 2
        self.assertTrue(self.compare('HPTTL', array(98999, -1), array(98992, -1), states, windows))
        self.assertFalse(self.compare('HPTTL', array(98999, 98000), array(98999, 98000), states, windows))
        for name in ('PTTL', 'TTL', 'HPTTL', 'HTTL'):
            encode = (lambda n: array(n, n)) if name.startswith('H') else integer
            for a, b in ((-2, -1), (-1, 0), (0, -2), (-3, -3)):
                self.assertFalse(self.compare(name, encode(a), encode(b)))
            for sentinel in (-1, -2):
                self.assertTrue(self.compare(name, encode(sentinel), encode(sentinel)))
        # Zero is a live result, including a sub-second TTL rounded to zero.
        zero = (1000 * MS,) * 2
        self.assertTrue(self.differ.ttl_within_deadline('PTTL', 0, zero, self.window(1000, 0)))

    def test_wire_types_and_lengths_do_not_receive_deadline_relaxation(self):
        for malformed in (b'+OK\r\n', b':+1\r\n', b':01\r\n', b':1\n',
                          b':1\r\ntrailing', b'$2\r\n:1\r\n', integer(1 << 63)):
            self.assertFalse(self.compare('PTTL', malformed, malformed))
        for malformed in (array(1), b'*2\r\n:1\r\n', b'*02\r\n:1\r\n:1\r\n',
                          b'~2\r\n:1\r\n:1\r\n', b'*2\r\n$2\r\n:1\r\n:1\r\n'):
            self.assertFalse(self.compare('HPTTL', malformed, malformed))
        self.assertTrue(self.compare('HTTL', b'-WRONGTYPE test\r\n', b'-WRONGTYPE test\r\n'))
        self.assertFalse(self.compare('HTTL', b'-ERR a\r\n', b'-ERR b\r\n'))
        self.assertEqual(self.differ.deadline_bounded_ttl_checks, 0)

    def test_absolute_probes_and_all_non_ttl_replies_stay_exact(self):
        commands = ('EXPIRETIME', 'PEXPIRETIME', 'HEXPIRETIME', 'HPEXPIRETIME',
                    'OBJECT IDLETIME', 'GET', 'HGETALL', 'DBSIZE', 'EXISTS', 'EXPIRE',
                    'HEXPIRE', 'HPERSIST', 'EXEC', 'EVAL', 'FCALL')
        for command in commands:
            for encode in (integer, array):
                args = command.split() + ['key']
                self.assertTrue(self.differ.replies_equal(args, encode(100), encode(100)))
                self.assertFalse(self.differ.replies_equal(args, encode(101), encode(100)))
        self.assertEqual(self.differ.deadline_bounded_ttl_checks, 0)

    def test_all_setter_forms_record_generator_intent(self):
        cases = [(['EXPIRE', 'key', '20'], 21000, 21011),
                 (['PEXPIRE', 'key', '20'], 1020, 1031),
                 (['EXPIREAT', 'key', '20'], 20000, 20000),
                 (['PEXPIREAT', 'key', '20'], 20, 20),
                 (['SETEX', 'key', '20', 'v'], 21000, 21011),
                 (['PSETEX', 'key', '20', 'v'], 1020, 1031)]
        for option, low, high in (('EX', 21000, 21011), ('PX', 1020, 1031),
                                  ('EXAT', 20000, 20000), ('PXAT', 20, 20)):
            cases += [(['SET', 'key', 'v', option, '20'], low, high),
                      (['GETEX', 'key', option, '20'], low, high)]
        for argv, low, high in cases:
            with self.subTest(argv=argv):
                state = self.differ.TtlDeadlines()
                reply = integer(1) if argv[0].startswith(('EXPIRE', 'PEXPIRE')) else b'+OK\r\n'
                state.observe(argv, reply, self.window())
                self.assertEqual(state.expected(['PTTL', 'key']), [(low * MS, high * MS)])
        for name, low, high in (('HEXPIRE', 21000, 21011), ('HPEXPIRE', 1020, 1031),
                                ('HEXPIREAT', 20000, 20000), ('HPEXPIREAT', 20, 20)):
            state = self.differ.TtlDeadlines()
            state.observe([name, 'key', '20', 'FIELDS', '2', 'a', 'b'], array(1, -2), self.window())
            self.assertEqual(state.expected(['HPTTL', 'key', 'FIELDS', '2', 'a', 'b']),
                             [(low * MS, high * MS), None])

    def test_relative_setter_uncertainty_is_measured_separately(self):
        states = (self.differ.TtlDeadlines(), self.differ.TtlDeadlines())
        states[0].observe(['SET', 'key', 'v', 'PX', '100000'], b'+OK\r\n', self.window(1000, 8))
        states[1].observe(['SET', 'key', 'v', 'PX', '100000'], b'+OK\r\n', self.window(1000, 1))
        windows = (self.window(2000, 1),) * 2
        self.assertTrue(self.compare('PTTL', integer(99007), integer(99000), states, windows))
        self.assertFalse(self.compare('PTTL', integer(99007), integer(99007), states, windows))
        self.assertFalse(self.compare('PTTL', integer(98990), integer(98990), states, windows))

    def test_conditional_writes_persistence_renames_copies_and_resets(self):
        state = self.states()[0]
        def observe(argv, reply=b'+OK\r\n'):
            state.observe(argv, reply, self.window())
        def expected(key='key'):
            return state.expected(['PTTL', key])[0]
        deadline = expected()
        for argv, reply in ((['PEXPIREAT', 'key', '120000', 'NX'], integer(0)),
                            (['SET', 'key', 'v', 'NX'], b'$-1\r\n'),
                            (['SET', 'key', 'v', 'NX', 'GET'], b'$1\r\nv\r\n'),
                            (['PEXPIREAT', 'key', 'bad'], b'-ERR bad\r\n'),
                            (['SET', 'key', 'v', 'KEEPTTL'], b'+OK\r\n')):
            observe(argv, reply)
            self.assertEqual(expected(), deadline)
        observe(['COPY', 'key', 'copy'], integer(1))
        observe(['PERSIST', 'copy'], integer(1))
        self.assertIsNone(expected('copy'))
        self.assertEqual(expected(), deadline)
        observe(['RENAME', 'key', 'renamed'])
        self.assertEqual(expected('renamed'), deadline)
        self.assertIsNone(expected())
        observe(['SET', 'renamed', 'v'])
        self.assertIsNone(expected('renamed'))
        observe(['SET', 'key', 'v', 'PXAT', '120000', 'GET'], b'$-1\r\n')
        self.assertEqual(expected(), (120000 * MS,) * 2)
        observe(['MSET', 'key', 'v', 'other', 'v'])
        self.assertIsNone(expected())

    def test_hash_deadline_mutations_keep_field_identity_and_order(self):
        state = self.states(True)[0]
        query = ['HPTTL', 'key', 'FIELDS', '3', 'b', 'a', 'b']
        deadline = (100000 * MS,) * 2
        self.assertEqual(state.expected(query), [deadline] * 3)
        state.observe(['HINCRBY', 'key', 'a', '1'], integer(1), self.window())
        state.observe(['HSETNX', 'key', 'a', '2'], integer(0), self.window())
        self.assertEqual(state.expected(query), [deadline] * 3)
        state.observe(['COPY', 'key', 'copy'], integer(1), self.window())
        state.observe(['HSET', 'key', 'a', '2'], integer(0), self.window())
        self.assertEqual(state.expected(query), [deadline, None, deadline])
        state.observe(['HPERSIST', 'key', 'FIELDS', '1', 'b'], array(1), self.window())
        self.assertEqual(state.expected(query), [None] * 3)
        query[1] = 'copy'
        self.assertEqual(state.expected(query), [deadline] * 3)
        state.observe(['HPEXPIREAT', 'copy', '1', 'FIELDS', '2', 'b', 'a'], array(2, 0), self.window())
        self.assertEqual(state.expected(query), [None, deadline, None])

    def test_request_timing_starts_before_send_and_ends_after_each_read(self):
        sock = Mock()
        with patch.object(self.differ.time, 'monotonic_ns', side_effect=[0, 2 * MS, 9 * MS]), \
                patch.object(self.differ.time, 'time_ns', return_value=1000 * MS + 999999):
            sent = self.differ.timed_send(sock, b'pipeline')
            _, first = self.differ.timed_read(io.BytesIO(integer(1)), sent)
            _, second = self.differ.timed_read(io.BytesIO(integer(2)), sent)
        sock.sendall.assert_called_once_with(b'pipeline')
        self.assertEqual((first.start, first.end), (1000 * MS, 1003 * MS))
        self.assertEqual((second.start, second.end), (1000 * MS, 1010 * MS))

    def connection(self, answer):
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

    def test_psfix_waits_for_both_peers_in_the_same_poll(self):
        peers = [(Mock(), None), (Mock(), None)]
        for sock, _ in peers:
            sock.gettimeout.return_value = 30
        # The initially idle target becomes busy as the oracle completes.
        states = iter((b'0', b'1', b'1', b'0', b'0', b'0'))
        observed = []
        def persistence(peer):
            observed.append(peers.index(peer))
            return {b'rdb_bgsave_in_progress': next(states)}
        with patch.object(self.differ.time, 'sleep') as sleep:
            result = self.differ.psfix_wait_idle(peers, persistence, 'before SAVE')
        self.assertEqual(observed, [0, 1, 0, 1, 0, 1])
        self.assertEqual(result, [{b'rdb_bgsave_in_progress': b'0'}] * 2)
        self.assertEqual(sleep.call_args_list, [unittest.mock.call(.001)] * 2)
        for sock, _ in peers:
            sock.settimeout.assert_called_with(30)

    def test_psfix_stuck_peer_has_one_ten_second_deadline(self):
        peers = [(Mock(), None), (Mock(), None)]
        now = [0.0]
        def sleep(seconds):
            self.assertLessEqual(seconds, .001)
            now[0] += seconds
        for busy in (0, 1):
            now[0] = 0
            def persistence(peer):
                return {b'rdb_bgsave_in_progress': b'1' if peer is peers[busy] else b'0'}
            with self.subTest(busy=busy), \
                    patch.object(self.differ.time, 'monotonic', side_effect=lambda: now[0]), \
                    patch.object(self.differ.time, 'sleep', side_effect=sleep), \
                    self.assertRaisesRegex(AssertionError, 'PSFIX harness error.*within 10 s'):
                self.differ.psfix_wait_idle(peers, persistence, 'before BGSAVE')
            self.assertEqual(now[0], 10)

    def test_psfix_missing_or_invalid_busy_field_never_means_idle(self):
        peers = [(Mock(), None), (Mock(), None)]
        for state in (None, b'', b'2', b'no'):
            with self.subTest(state=state), self.assertRaisesRegex(AssertionError, 'harness error'):
                self.differ.psfix_wait_idle(peers, lambda peer: {b'rdb_bgsave_in_progress': state},
                                           'before SAVE')

    def test_psfix_slow_info_is_bounded_and_restores_socket_timeout(self):
        peers = [(Mock(), None), (Mock(), None)]
        with self.assertRaisesRegex(AssertionError, 'PSFIX harness error.*within 10 s'):
            self.differ.psfix_wait_idle(peers, Mock(side_effect=TimeoutError), 'before SAVE')
        for sock, _ in peers:
            sock.settimeout.assert_called_with(sock.gettimeout.return_value)
        self.assertLessEqual(peers[0][0].settimeout.call_args_list[0].args[0], 10)

    def test_psfix_background_save_collision_is_a_harness_error_on_either_peer(self):
        for label in ('target', 'oracle'):
            for command in ('SAVE', 'BGSAVE'):
                with self.subTest(label=label, command=command), \
                        self.assertRaisesRegex(AssertionError, 'PSFIX harness error: ' + label):
                    self.differ.psfix_check_save_reply(
                        label, command, b'-ERR Background save already in progress\r\n')
        self.differ.psfix_check_save_reply('target', 'SAVE', b'+OK\r\n')
        self.differ.psfix_check_save_reply('oracle', 'BGSAVE', b'+Background saving started\r\n')
        with self.assertRaises(AssertionError):
            self.differ.psfix_check_save_reply('target', 'SAVE', b'+Background saving started\r\n')

    def test_real_pipeline_checks_equal_wrong_replies_and_preserves_failure_exit(self):
        source = ROOT / 'tests/differ.py'
        tree = ast.parse(source.read_text())
        cut = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'ops' for t in node.targets))
        for wrong in (False, True):
            def answer(argv, target=False):
                if argv[0] == b'PTTL':
                    return integer(98000 if wrong else 98992 if target else 98999)
                return b'+OK\r\n'
            with patch.object(sys, 'argv', ['differ.py', 'target', '1', 'oracle', '2', 'string', '7']), \
                    patch('socket.create_connection', side_effect=[
                        self.connection(lambda argv: answer(argv, True))[0], self.connection(answer)[0]]), \
                    contextlib.redirect_stdout(io.StringIO()) as log, self.assertRaises(SystemExit) as stopped:
                scope = dict(__name__='__main__', __file__=str(source))
                exec(compile(ast.Module(body=tree.body[:cut], type_ignores=[]), str(source), 'exec'), scope)
                scope['gens']['string'] = lambda rng: ([['SET', 'key', 'v', 'PXAT', '100000']] +
                    [['GET', 'key']] * 63 + [['PTTL', 'key'], ['PTTL', 'key']])
                actual_read = scope['timed_read']
                scope['timed_read'] = lambda file, sent: (actual_read(file, sent)[0], self.window())
                exec(compile(ast.Module(body=tree.body[cut:], type_ignores=[]), str(source), 'exec'), scope)
            self.assertEqual(stopped.exception.code, int(wrong))
            self.assertIn('2 deadline-bounded TTL checks -> ' + ('FAIL' if wrong else 'PASS'), log.getvalue())
            self.assertEqual('TTL DEADLINE FAIL' in log.getvalue(), wrong)

    def test_multidb_exact_positions_and_publication_fail_independently(self):
        expected = sum(o == ['DBSIZE', 'NOW'] for o in self.differ.gen_multidb(random.Random(7)))
        self.assertGreater(expected, 0)
        for wrong_exact, stuck in ((False, False), (True, False), (False, True)):
            sent = [[], []]
            polls = 0
            def answer(argv, target=False):
                nonlocal polls
                sent[int(target)].append(argv)
                if argv[0] != b'DBSIZE': return b'+OK\r\n'
                if not target:
                    self.assertEqual(argv, [b'DBSIZE'])
                    return integer(1)
                if argv == [b'DBSIZE', b'NOW']:
                    first = sum(command == argv for command in sent[1]) == 1
                    return integer(2 if wrong_exact and first else 1)
                polls += 1
                return integer(0 if stuck or polls < 3 else 1)
            with patch.object(sys, 'argv', ['differ.py', 'target', '1', 'oracle', '2', 'multidb', '7']), \
                    patch('socket.create_connection', side_effect=[
                        self.connection(lambda argv: answer(argv, True))[0], self.connection(answer)[0]]), \
                    contextlib.redirect_stdout(io.StringIO()) as log, self.assertRaises(SystemExit) as stopped:
                runpy.run_path(str(ROOT / 'tests/differ.py'), run_name='__main__')
            self.assertEqual(stopped.exception.code, int(wrong_exact or stuck))
            self.assertIn('exact_positions=%d' % expected, log.getvalue())
            self.assertEqual(sum(argv == [b'DBSIZE', b'NOW'] for argv in sent[1]), expected + 1)
            self.assertEqual('DBSIZE EXACT PROPERTY FAIL' in log.getvalue(), wrong_exact)
            self.assertEqual('DBSIZE PUBLICATION PROPERTY FAIL' in log.getvalue(), stuck)
            self.assertGreaterEqual(polls, 3)

    def test_dbsize_rejects_equal_noninteger_replies(self):
        for reply in (b'+OK\r\n', b'-ERR broken\r\n', b':-1\r\n', b':01\r\n', b'$1\r\n1\r\n'):
            with self.subTest(reply=reply), self.assertRaises(ValueError):
                self.differ.dbsize_integer(reply)

    def test_wiredump_tracks_relative_restore_and_keeps_absolute_probes_exact(self):
        for delta, absolute_delta, change_value in ((7, 0, False), (200, 0, False),
                                                  (0, 1, False), (0, 0, True)):
            restored = [None, None]
            def answer(argv, target=False):
                side = int(target)
                if argv[0] == b'RESTORE' and argv[1] == b'wd:restore':
                    restored[side] = int(argv[2]) + (0 if b'ABSTTL' in argv else 1000)
                if argv[0] == b'HPEXPIRETIME':
                    return array(*([100 + (absolute_delta if target else 0)] * int(argv[3])))
                if argv[0] == b'PTTL':
                    return integer(-2 if restored[side] is None else restored[side] - 1000 -
                                   (delta if target else 0))
                if argv[0] == b'HGETALL':
                    return b'*2\r\n$1\r\nf\r\n$1\r\n' + (b'2' if target and change_value else b'1') + b'\r\n'
                if argv[0] == b'DUMP': return b'$1\r\nx\r\n'
                return b'+OK\r\n'
            with patch.object(self.differ, 'conn', side_effect=[
                        self.connection(lambda argv: answer(argv, True)), self.connection(answer)]), \
                    patch.object(self.differ.time, 'time', return_value=1.0), \
                    patch.object(self.differ.time, 'time_ns', return_value=1000 * MS), \
                    patch.object(self.differ.time, 'monotonic_ns', side_effect=itertools.count(0, 10 * MS)), \
                    contextlib.redirect_stdout(io.StringIO()) as log:
                diffs = self.differ.run_wiredump_suite(random.Random(23))
            passed = delta == 7 and absolute_delta == 0 and not change_value
            self.assertEqual(diffs == 0, passed, log.getvalue()[:2000])
            self.assertIn('deadline-bounded TTL checks -> ' + ('PASS' if passed else 'FAIL'), log.getvalue())


if __name__ == '__main__':
    unittest.main()
