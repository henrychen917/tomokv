#!/usr/bin/env python3
"""Negative controls: remove/move the risky moment, and the hit must disappear."""
import tempfile
from pathlib import Path
import unittest

from lottery_evidence import Event as E, observed, reduce_events, trace


class EvidenceTests(unittest.TestCase):
    def test_exec_installed_requires_foreign_reader_in_exact_window(self):
        # Reader stamp (b) precedes its load; the installed record's own stamp
        # follows the last owner's join. Events are processed in stamp order.
        prefix = [E('exec_open', 100, seq=1), E('write_new', 100, seq=2),
                  E('exec_key', 100, 9, 11, seq=3), E('exec_installed', 100, 2, 1, 11, seq=4)]
        read = E('foreign_undecided', 100, 9, 5, 22, 11, seq=6)
        close = E('exec_decision', 100, 18, seq=7)
        self.assertEqual(reduce_events(prefix + [read, close])['W16'], 1)
        # A record written after the decision for an in-window load still counts.
        late = E('foreign_undecided', 100, 9, 5, 22, 11, seq=8)
        self.assertEqual(reduce_events(prefix + [close, late])['W16'], 1)
        # Load started before the last owner joined: a near miss, not a hit.
        early = E('foreign_undecided', 100, 9, 3, 22, 11, seq=6)
        counts = reduce_events(prefix + [early, close])
        self.assertEqual((counts['W16'], counts['W16.installing']), (0, 1))
        for events in (prefix + [E('foreign_undecided', 101, 9, 5, 22, 11, seq=6)],
                       prefix + [E('foreign_undecided', 100, 8, 5, 22, 11, seq=6)],
                       prefix + [E('foreign_undecided', 100, 9, 5, 11, 11, seq=6)],
                       prefix + [E('foreign_undecided', 100, 9, 5, 22, 12, seq=6)]):
            self.assertEqual(reduce_events(events)['W16'], 0)
        # Single-owner transactions never open the window.
        single = prefix[:3] + [E('exec_installed', 100, 1, 1, 11, seq=4), read]
        self.assertEqual(reduce_events(single)['W16'], 0)

    def test_reused_epoch_address_is_a_new_incarnation(self):
        first = [E('exec_open', 100, seq=1), E('write_new', 100, seq=2),
                 E('exec_key', 100, 9, 11, seq=3), E('exec_installed', 100, 2, 1, 11, seq=4),
                 E('exec_decision', 100, 18, seq=5)]
        # The address re-opens for a new EXEC still installing: the old
        # installed stamp must not turn its undecided entries into hits.
        again = [E('exec_open', 100, seq=6),
                 E('foreign_undecided', 100, 9, 7, 22, 11, seq=8)]
        counts = reduce_events(first + again)
        self.assertEqual((counts['W16'], counts['W16.installing']), (0, 1))
        # A non-EXEC scatter group reusing a child address is not a transaction.
        child = [E('exec_open', 100, seq=1), E('exec_child', 555, 100, seq=2),
                 E('write_new', 100, seq=3), E('exec_key', 100, 9, 11, seq=4),
                 E('exec_installed', 100, 3, 1, 11, seq=5)]
        hit = E('foreign_undecided', 555, 9, 6, 22, 11, seq=7)
        self.assertEqual(reduce_events(child + [hit])['W16'], 1)
        self.assertEqual(reduce_events(child + [E('group_open', 555, seq=6), hit])['W16'], 0)

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

    def test_pinned_flush_must_land_between_fragments(self):
        start = [E('read_new', 1, 2, 10, 3), E('read_begin', 1, 0), E('read_end', 1, 0)]
        self.assertEqual(reduce_events(start + [E('flush', 0)])['W2.pin_flush'], 1)
        # Second fragment already began, read is unpinned, or nothing finished yet.
        self.assertEqual(reduce_events(start + [E('read_begin', 1, 1), E('flush', 0)])
                         ['W2.pin_flush'], 0)
        unpinned = [E('read_new', 1, 2, (1 << 64) - 1, 3)] + start[1:]
        self.assertEqual(reduce_events(unpinned + [E('flush', 0)])['W2.pin_flush'], 0)
        self.assertEqual(reduce_events(start[:2] + [E('flush', 0)])['W2.pin_flush'], 0)
        self.assertEqual(reduce_events(start + [E('read_drop', 1), E('flush', 0)])
                         ['W2.pin_flush'], 0)

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
        emitted = [post, done, E('tracking_emit', 7), check]
        self.assertEqual(reduce_events(emitted + [E('tracking_compare_zero')])['W13'], 0)
        self.assertEqual(reduce_events(emitted + [E('tracking_compare_data')])['W13'], 1)
        self.assertEqual(reduce_events([post, done, check, E('tracking_compare_zero')])['W13'], 1)

    def flip(self, flip, begin, end):
        events = [E('flip_work', flip, t, epoch) for t, epoch in begin.items()]
        events.append(E('flip_begin', flip))
        events += [E('flip_work_end', flip, t, epoch) for t, epoch in end.items()]
        return events + [E('flip_end', flip)]

    def test_flip_requires_inflight_work_at_request_and_progress_inside_window(self):
        loaded = self.flip(0, {2: 7, 3: 10}, {2: 15, 3: 12})
        self.assertEqual(reduce_events(loaded)['W11'], 1)
        # Idle at the request (all epochs even), or no scope closed in the window.
        self.assertEqual(reduce_events(self.flip(0, {2: 8, 3: 10}, {2: 20, 3: 12}))['W11'], 0)
        self.assertEqual(reduce_events(self.flip(0, {2: 7, 3: 10}, {2: 7, 3: 10}))['W11'], 0)
        self.assertEqual(reduce_events(self.flip(0, {2: 7, 3: 10}, {2: 8, 3: 10}))['W11'], 0)
        # Every applied FLIP must be loaded; a refused one (no end) is not counted.
        idle = self.flip(1, {2: 16, 3: 12}, {2: 16, 3: 12})
        self.assertEqual(reduce_events(loaded + idle)['W11'], 0)
        refused = [E('flip_work', 1, 2, 16), E('flip_begin', 1)]
        self.assertEqual(reduce_events(loaded + refused)['W11'], 1)
        self.assertEqual(reduce_events(refused)['W11'], 0)

    def test_completed_partial_frame_cannot_witness_a_later_window(self):
        partial = E('parser_partial', 7, 2, 0, 10)
        sample = E('lbsignals')
        complete = E('parser_complete', 7)
        self.assertGreater(reduce_events([partial, sample, sample, complete])['W10'], 0)
        self.assertEqual(reduce_events([partial, complete, sample, sample])['W10'], 0)

    def test_stream_clock_witness_and_carry(self):
        ok = E('stream_clock', 3, 1000, 990, 1000, 0)
        carry = E('stream_clock', 3, 900, 990, 991, 0)
        same_ms = E('stream_clock', 3, 990, 990, 990, 5)
        self.assertEqual(reduce_events([ok, carry, same_ms])['W15'], 3)
        bad = E('stream_clock', 3, 1000, 990, 1003, 0)
        counts = reduce_events([ok, bad])
        self.assertEqual((counts['W15'], counts['W15.mismatch']), (0, 1))

    def test_trace_missing_footer_and_sequence_gap_are_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'trace'
            # Mutex order 1,2 but call-site stamps 9,4: returned in stamp order.
            path.write_text('LOTTERY2 42 2\n1 x 0 0 0 0 0 1 1 9\n2 y 0 0 0 0 0 2 1 4\nEND 2 1\n')
            self.assertEqual([e.kind for e in trace(path, 42)], ['y', 'x'])
            for content in ('LOTTERY2 42 2\n', 'LOTTERY2 42 2\nEND 0 0\n',
                            'LOTTERY1 42 2\n1 x 0 0 0 0 0 1 1 9\nEND 1 1\n',
                            'LOTTERY2 43 2\n1 x 0 0 0 0 0 1 1 9\nEND 1 1\n',
                            'LOTTERY2 42 2\n2 x 0 0 0 0 0 1 1 9\nEND 1 1\n',
                            'LOTTERY2 42 2\n1 x 0 0 0 0 0 1 1\nEND 1 1\n',
                            'LOTTERY2 42 2\n1 x 0 0 0 0 0 1 1 0\nEND 1 1\n',
                            'LOTTERY2 42 2\n1 x 0 0 0 0 0 1 1 9\n2 y 0 0 0 0 0 2 1 9\nEND 2 1\n',
                            'LOTTERY2 42 2\n1 x 0 0 0 0 0 5 1 9\n2 y 0 0 0 0 0 2 1 4\nEND 2 1\n',
                            'LOTTERY2 42 2\n1 x 0 0 0 0 0 1 1 9\nEND 1 1\nextra\n'):
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
