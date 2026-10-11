#!/usr/bin/env python3
"""Negative controls: remove/move the risky moment, and the hit must disappear."""
import tempfile
from pathlib import Path
import unittest

from lottery_evidence import Event as E, observed, reduce_events, trace


class EvidenceTests(unittest.TestCase):
    def test_exec_installed_requires_foreign_reader_in_exact_window(self):
        prefix = [E('write_new', 100), E('exec_key', 100, 9, 11),
                  E('exec_installed', 100, 2, 1, 11)]
        read = E('foreign_undecided', 100, 9, 17, 22, 11)
        close = E('exec_decision', 100, 18)
        self.assertEqual(reduce_events(prefix + [read, close])['W16'], 1)
        for events in (prefix + [close, read], [read] + prefix,
                       prefix + [E('foreign_undecided', 101, 9, 17, 22, 11)],
                       prefix + [E('foreign_undecided', 100, 8, 17, 22, 11)],
                       prefix + [E('foreign_undecided', 100, 9, 17, 11, 11)]):
            self.assertEqual(reduce_events(events)['W16'], 0)

    def fanout(self):
        return [E('read_new', 1, 2, 10, 3), E('read_begin', 1, 0),
                E('read_key', 1, 80, 0), E('read_end', 1, 0),
                E('write_new', 2), E('exec_key', 2, 80, 4), E('exec_key', 2, 90, 4),
                E('exec_decision', 2, 11), E('commit', 0, 11, 1),
                E('read_begin', 1, 1), E('read_key', 1, 90, 1), E('read_end', 1, 1)]

    def test_fanout_straddle_and_wrong_order_controls(self):
        events = self.fanout()
        self.assertEqual(reduce_events(events)['W2.fanout'], 1)
        self.assertEqual(reduce_events(events[4:9] + events[:4] + events[9:])['W2.fanout'], 0)
        self.assertEqual(reduce_events(events[:8] + events[9:] + events[8:9])['W2.fanout'], 0)
        self.assertEqual(reduce_events([e for e in events if e.kind != 'read_end'])['W2.fanout'], 0)

    def test_wrong_key_or_unpinned_read_is_not_fanout_hit(self):
        for i, replacement in [(6, E('exec_key', 2, 99, 4)),
                               (0, E('read_new', 1, 2, (1 << 64)-1, 3))]:
            events = self.fanout()
            events[i] = replacement
            self.assertEqual(reduce_events(events)['W2.fanout'], 0)

    def test_snapshot_requires_partial_installs_not_just_pending_group(self):
        group = E('apply_group', 4, 2)
        one, two = E('apply_key', 4, 80), E('apply_key', 4, 90)
        cut = E('snapshot_drain', 0, 1)
        self.assertEqual(reduce_events([group, one, cut, two])['W9'], 1)
        for events in ([group, cut], [group, one, two, cut],
                       [group, one, E('exec_decision', 4, 9), cut]):
            self.assertEqual(reduce_events(events)['W9'], 0)

    def test_move_requires_same_source_same_edge_between_selection_and_removal(self):
        selected = E('move_selected', 1, 50, 1)
        pushed = E('push_end', 50, 1)
        remove = E('move_remove', 1)
        self.assertEqual(reduce_events([selected, pushed, remove])['W6.left'], 1)
        for events in ([pushed, selected, remove], [selected, remove, pushed],
                       [selected, E('push_end', 51, 1), remove],
                       [selected, E('push_end', 50, 0), remove]):
            self.assertEqual(reduce_events(events)['W6.left'], 0)

    def test_expiry_requires_every_family_and_actual_deadline_crossing(self):
        events = []
        for name in ('fanout', 'exec', 'script'):
            events += [E('expiry_section_' + name), E('expiry_lookup', 9, 100, 110, ms=111)]
        self.assertEqual(reduce_events(events)['W4'], 1)
        self.assertEqual(reduce_events(events[:-1])['W4'], 0)
        self.assertEqual(reduce_events([E('expiry_section_exec'),
                                        E('expiry_lookup', 9, 100, 110, ms=109)])['W4'], 0)

    def test_config_requires_all_owners_and_every_checked_epoch(self):
        events = [E('config_io', 0, 4), E('config_ex', 1, 4), E('config_check', 0, 4, 2)]
        self.assertEqual(reduce_events(events)['W1'], 1)
        self.assertEqual(reduce_events(events[1:])['W1'], 0)
        self.assertEqual(reduce_events(events + [E('config_check', 0, 6, 2)])['W1'], 0)

    def test_tracking_pending_event_makes_fence_a_miss(self):
        post, done, check = E('tracking_post', 9, 3), E('tracking_end', 9, 3), E('tracking_compare_begin')
        self.assertEqual(reduce_events([post, done, check])['W13'], 1)
        self.assertEqual(reduce_events([post, check, done])['W13'], 0)
        self.assertEqual(reduce_events([post, check])['W13'], 0)

    def test_trace_missing_footer_and_sequence_gap_are_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'trace'
            path.write_text('LOTTERY1 42 2\n1 x 0 0 0 0 0 1 1\nEND 1 1\n')
            self.assertEqual(len(list(trace(path, 42))), 1)
            for content in ('LOTTERY1 42 2\n', 'LOTTERY1 42 2\nEND 0 0\n',
                            'LOTTERY1 42 2\n2 x 0 0 0 0 0 1 1\nEND 1 1\n'):
                path.write_text(content)
                with self.assertRaises(ValueError):
                    list(trace(path, 42))

    def test_empty_or_unrelated_trace_cannot_hit(self):
        from lottery_runner import registry
        for row in registry():
            counts = observed(row, [], '', {'snapshot_preimages': '0'}, {'snapshot_preimages': '0'})
            self.assertFalse(any(counts.values()), row['id'])


if __name__ == '__main__':
    unittest.main()
