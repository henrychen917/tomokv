#!/usr/bin/env python3
"""Serverless controls for the churn battery's movement witness."""
import contextlib
import io
import unittest
from unittest.mock import Mock, patch

import rlcache_churn as churn


class ChurnWindow(unittest.TestCase):
    def test_hot_keys_cover_distinct_shards_on_one_owner(self):
        keys = ['a', 'b', 'c', 'd', 'e']
        with patch.object(churn._lib, 'shards_of', return_value=[
                (0, 4), (0, 4), (1, 4), (2, 4), (3, 7)]):
            hot = [churn.arm_hot_keys(None, keys)]
        self.assertEqual(hot[0], ('a', 'c', 'd'))
        # Wall-clock rotation cannot discard the armed demand before a move.
        with patch.object(churn.time, 'time', side_effect=AssertionError('unobserved rotation')):
            self.assertEqual({churn.hot_key(keys, hot, 1, salt) for salt in range(12)},
                             {'a', 'c', 'd'})

    def test_one_indivisible_shard_cannot_arm(self):
        with patch.object(churn._lib, 'shards_of', return_value=[(0, 4), (0, 4)]):
            with self.assertRaisesRegex(AssertionError, 'multiple movable shards'):
                churn.arm_hot_keys(None, ['a', 'b'])

    def witness(self, moves):
        now = [0.0]
        conn = Mock()
        conn.read.return_value = b'OK'
        conn.must.return_value = b'OK'

        def info_int(_conn, _section, field):
            if field == 'read_local_active_threads':
                return 8
            if field == 'read_local_hits':
                return int(now[0] > 0)
            if field == 'tomokv_keylb_bucket_moves':
                return moves if now[0] > 0 else 0
            raise AssertionError(field)

        def info(_conn, section):
            if section == 'server':
                return {'read_local': '1'}
            return {'mem_block_cache': '128', 'tomokv_keylb_bucket_moves': str(moves)}

        def thread(*, target, args):
            args[6][args[2]] = 1  # both simulated workers finish useful traffic
            return Mock(is_alive=lambda: False)

        output = io.StringIO()
        with patch.object(churn.sys, 'argv', ['rlcache_churn.py', 'unused', '1', '.5', '2']), \
                patch.object(churn._lib, 'Conn', return_value=conn), \
                patch.object(churn._lib, 'thread_mode', return_value='1s'), \
                patch.object(churn._lib, 'info', side_effect=info), \
                patch.object(churn._lib, 'info_int', side_effect=info_int), \
                patch.object(churn._lib, 'call', return_value=b'PONG'), \
                patch.object(churn, 'arm_hot_keys', return_value=('ch:0', 'ch:1')) as arm, \
                patch.object(churn.threading, 'Thread', side_effect=thread), \
                patch.object(churn.time, 'time', side_effect=lambda: now[0]), \
                patch.object(churn.time, 'sleep', side_effect=lambda dt: now.__setitem__(0, now[0] + dt)), \
                contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as finished:
                churn.main()
            status = finished.exception.code
        return status, output.getvalue(), arm.call_count

    def test_never_moving_stays_red_despite_reads_and_cache_activity(self):
        status, output, arms = self.witness(0)
        self.assertEqual(status, 1)
        self.assertIn('tomokv_keylb_bucket_moves delta 0', output)
        self.assertEqual(arms, 1)

    def test_completed_move_rearms_from_current_placement(self):
        status, output, arms = self.witness(2)
        self.assertEqual(status, 0)
        self.assertIn('rearmed churn after shard moves: delta=2', output)
        self.assertEqual(arms, 2)


if __name__ == '__main__':
    unittest.main()
