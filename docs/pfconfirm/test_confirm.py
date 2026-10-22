#!/usr/bin/env python3
"""Serverless negative controls for confirmation validity, not a box benchmark."""
from collections import Counter
from contextlib import redirect_stderr
from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import confirm as c


def sample(arm="A", on=False, rate=100, p99=1, p999=2, maximum=None):
    return dict(arm=arm, trigger_on=on, complete=True, rate=rate, p99_ms=p99,
                p999_ms=p999, max_ms=p999 if maximum is None else maximum,
                witness=dict(verdict="PASS"))


def experiment(rate=94, p99=1, p999=2, maximum=None, plain_maximum=None):
    null = [sample(arm) for arm in c.ORDER]
    blocks = [[sample(arm, arm == "B", rate if arm == "B" else 100,
                      p99 if arm == "B" else 1, p999 if arm == "B" else 2,
                      maximum if arm == "B" else plain_maximum)
               for arm in c.ORDER] for _ in range(3)]
    return null, blocks


def evaluate(null, blocks, candidate="PFKEYSPA.1", cell=None):
    if cell is None:
        cell = next(x for x in c.read_cells(c.HERE / "cells.txt")
                    if x.id.startswith(c.SPECS[candidate][0]))
    return c.decide(null, blocks, cell=cell, candidate=candidate)


class VerdictControls(unittest.TestCase):
    def test_null_never_confirms_and_both_thresholds_work(self):
        for candidate in ("PFKEYSPA.1", "PFMESSAG.1"):
            for rate, tail, verdict in ((100, 1, False), (94, 1, True), (100, 2, True), (96, 1.99, False)):
                with self.subTest(candidate=candidate, rate=rate, tail=tail):
                    result = evaluate(*experiment(rate, tail), candidate)
                    self.assertEqual(result["verdict"] == "HIGH upside CONFIRMED", verdict)

    def test_null_tail_spread_cannot_be_ignored(self):
        null, blocks = experiment(100, 2)
        null[0]["p99_ms"] = 5
        self.assertEqual(evaluate(null, blocks)["verdict"], "NOT CONFIRMED (mark only)")

    def test_quiet_five_percent_null_passes_but_seven_percent_fails(self):
        for span in (5, 7):
            null, blocks = experiment()
            for row, rate in zip(null, (100 - span / 2, 100, 100, 100 + span / 2)):
                row["rate"] = rate
            with self.subTest(span=span):
                if span == 7:
                    with self.assertRaisesRegex(RuntimeError, "unstable OFF null.*>6%"):
                        evaluate(null, blocks)
                else:
                    result = evaluate(null, blocks)
                    self.assertEqual(result["null"]["rate"]["span_pct"], 5)
                    self.assertEqual(result["rate_span_cap_pct"], 6)
                    self.assertTrue(result["rate_confirmed"])

    def test_quiet_and_noisy_caps_apply_to_nulls_and_both_abba_arms(self):
        base = c.read_cells(c.HERE / "cells.txt")[0]
        for op, read_local, cap in (("GET", 0, 6), ("SET", 0, 6), ("GET", 1, 20),
                                   ("SET", 1, 20), ("MGET", 0, 20), ("MSET", 0, 20)):
            cell = replace(base, op=op, read_local=read_local)
            for which in ("null", "on", "off"):
                for span in (cap - 1, cap, cap + 1):
                    null, blocks = experiment(100)
                    rows = null if which == "null" else [r for r in blocks[1]
                        if r["arm"] == ("B" if which == "on" else "A")]
                    rows[0]["rate"], rows[-1]["rate"] = 100 - span / 2, 100 + span / 2
                    with self.subTest(op=op, rl=read_local, which=which, span=span):
                        if span > cap:
                            with self.assertRaisesRegex(RuntimeError, f"unstable.*>{cap}%"):
                                evaluate(null, blocks, cell=cell)
                        else:
                            self.assertEqual(evaluate(null, blocks, cell=cell)["rate_span_cap_pct"], cap)

    def test_rate_effect_must_exceed_measured_null_in_every_block(self):
        for weak_block in (False, True):
            null, blocks = experiment(94)
            for row, rate in zip(null, (97.5, 100, 100, 102.5)):
                row["rate"] = rate
            # Same null and median effect: one weak block must prevent confirmation.
            if weak_block:
                for row in blocks[2]:
                    if row["arm"] == "B":
                        row["rate"] = 97
            self.assertEqual(evaluate(null, blocks)["rate_confirmed"], not weak_block)
        null, blocks = experiment(93.75)  # Exact binary fraction: loss equals measured span.
        for row, rate in zip(null, (96.875, 100, 100, 103.125)):
            row["rate"] = rate
        self.assertFalse(evaluate(null, blocks, "PFMESSAG.1")["rate_confirmed"])

    def test_unstable_null_or_arm_fails_instead_of_widening_threshold(self):
        for which in ("null", "on", "off"):
            null, blocks = experiment()
            target = null[0] if which == "null" else blocks[1][1 if which == "on" else 0]
            target["rate"] *= 1.1
            with self.subTest(which=which), self.assertRaisesRegex(RuntimeError, "unstable"):
                evaluate(null, blocks)

    def test_no_best_block_selection_or_p999_only_confirmation(self):
        null, blocks = experiment(100, 1)
        for row in blocks[0]:
            if row["arm"] == "B":
                row["rate"] = 50
        for block in blocks:
            for row in block:
                if row["arm"] == "B":
                    row["p999_ms"] = 200
        for candidate in ("PFKEYSPA.1", "PFMESSAG.1"):
            self.assertEqual(evaluate(null, blocks, candidate)["verdict"], "NOT CONFIRMED (mark only)")

    def test_sparse_one_hz_stall_visible_only_at_p999_confirms_stall_candidates(self):
        # A 2 ms window each second affects 0.2% of requests, below p99's reach.
        plain = Counter({1000: 100000})
        stalled = Counter({1000: 99800, 3000: 200})
        null, blocks = experiment(100)
        for row in null + sum(blocks, []):
            hist = stalled if row["trigger_on"] else plain
            row.update(p99_ms=c.percentile(hist, 99), p999_ms=c.percentile(hist, 99.9),
                       max_ms=c.percentile(hist, 100))
        for candidate in c.SPECS:
            with self.subTest(candidate=candidate):
                result = evaluate(null, blocks, candidate)
                stall_candidate = candidate in ("PFKEYSPA.3", "PFKEYSPA.4", "PFDATATY.1")
                self.assertEqual(result["p999_confirmed"], stall_candidate)
                self.assertEqual(result["verdict"] == "HIGH upside CONFIRMED", stall_candidate)
                self.assertFalse(result["rate_confirmed"] or result["p99_confirmed"])
                self.assertEqual(result["p99_ratio"], 1)
                self.assertEqual(result["p999_ratio"], 3)

    def test_p999_needs_action_bar_and_all_three_blocks_beyond_its_null(self):
        for control in ("at_bar", "below_bar", "null_equals_effect", "weak_block"):
            null, blocks = experiment(100, 1, 4)
            if control == "below_bar":
                for block in blocks:
                    for row in block:
                        if row["arm"] == "B":
                            row["p999_ms"] = 3.99
            elif control == "null_equals_effect":
                null[0]["p999_ms"] = 4  # 100% measured span, ratio exactly 2 is insufficient.
            elif control == "weak_block":
                for row in blocks[2]:
                    if row["arm"] == "B":
                        row["p999_ms"] = 2
            with self.subTest(control=control):
                self.assertEqual(evaluate(null, blocks, "PFKEYSPA.3")["p999_confirmed"],
                                 control == "at_bar")

    def test_tls_encryption_cost_without_stall_never_confirms(self):
        result = evaluate(*experiment(50, 4, 8, maximum=9), "PFPERSIS.1")
        self.assertEqual(result["verdict"], "NOT CONFIRMED (mark only)")
        self.assertEqual(result["rate_loss_pct"], 50)
        self.assertEqual((result["p99_ratio"], result["p999_ratio"]), (4, 4))
        self.assertEqual(result["decisive_metrics"], ("max_ms",))
        self.assertFalse(any(result[m] for m in ("rate_confirmed", "p99_confirmed",
                                                 "p999_confirmed", "stall_confirmed")))

    def test_tls_stall_requires_each_block_and_strict_plain_maximum(self):
        for control in ("at_bar", "below_bar", "plain_at_limit", "one_missing_block", "plain_spike"):
            null, blocks = experiment(100, maximum=100, plain_maximum=9.999)
            if control == "below_bar":
                for block in blocks:
                    for row in block:
                        if row["arm"] == "B":
                            row["max_ms"] = 99.999
            elif control == "plain_at_limit":
                blocks[0][0]["max_ms"] = 10
            elif control == "one_missing_block":
                for row in blocks[2]:
                    if row["arm"] == "B":
                        row["max_ms"] = 9
            elif control == "plain_spike":
                blocks[2][3]["max_ms"] = 150
            with self.subTest(control=control):
                result = evaluate(null, blocks, "PFPERSIS.1")
                self.assertEqual(result["stall_confirmed"], control == "at_bar")
                self.assertEqual(result["verdict"] == "HIGH upside CONFIRMED", control == "at_bar")

    def test_tls_pools_maxima_without_averaging_or_null_tail_caps(self):
        null, blocks = experiment(100, maximum=150, plain_maximum=9)
        null[0].update(p99_ms=1000, p999_ms=1000, max_ms=1000)
        for block in blocks:
            block[1]["max_ms"] = 2  # max(2, 150) must stay 150, not fall to a mean of 76.
        result = evaluate(null, blocks, "PFPERSIS.1")
        self.assertTrue(result["stall_confirmed"])
        self.assertEqual(result["block_max_ms"], [dict(A=9, B=150)] * 3)

    def test_missing_or_nonfinite_maximum_fails(self):
        for value in (None, float("nan")):
            null, blocks = experiment()
            if value is None:
                del blocks[0][1]["max_ms"]
            else:
                blocks[0][1]["max_ms"] = value
            with self.assertRaises((KeyError, RuntimeError)):
                evaluate(null, blocks, "PFPERSIS.1")

    def test_missing_trigger_incomplete_or_mislabelled_arm_fails(self):
        for mutation in (lambda r: r["witness"].update(verdict="FAIL"),
                         lambda r: r.update(complete=False),
                         lambda r: r.update(trigger_on=False),
                         lambda r: r.update(arm="A")):
            null, blocks = experiment()
            mutation(blocks[0][1])
            with self.assertRaises(RuntimeError):
                evaluate(null, blocks)
        null, blocks = experiment()
        with self.assertRaises(RuntimeError):
            evaluate(null, blocks[:2])


class DriverControls(unittest.TestCase):
    def setUp(self):
        self.cell = c.read_cells(c.HERE / "cells.txt")[0]
        self.driver = object.__new__(c.Campaign)
        self.driver.args = SimpleNamespace(smoke=False)
        self.driver.memtier = "/usr/bin/memtier_benchmark"
        self.driver.seconds = 20
        self.driver.port = 25000
        self.driver.out = Path("/unused")
        self.place = dict(cpus=[32], threads=1, clients=1)

    def test_all_cell_files_parse_and_no_trigger_can_run_as_stock_cell(self):
        self.assertEqual(len(c.read_cells(c.HERE / "cells.txt")), 12)
        self.assertEqual(len(c.read_cells(c.HERE / "guards.txt")), 16)
        for ident, (prefix, _) in c.SPECS.items():
            self.assertTrue(any(x.id.startswith(prefix) for x in c.read_cells(c.HERE / "cells.txt")), ident)

    def test_scoring_and_all_dependent_guards_use_read_local_zero(self):
        cells = c.read_cells(c.HERE / "cells.txt")
        guards = c.read_cells(c.HERE / "guards.txt")
        self.assertTrue(all(cell.mode == "1s" and cell.read_local == cell.reorder == 0 for cell in cells))
        self.assertTrue(all(cell.read_local == cell.reorder == 0 for cell in guards))
        self.assertEqual({cell.mode for cell in guards}, {"1s", "2s"})

    def test_candidate_null_and_dry_guards_use_classified_rate_caps(self):
        for op, rl, cap in (("GET", 0, 6), ("MSET", 0, 20), ("GET", 1, 20)):
            cell = replace(self.cell, op=op, read_local=rl)
            for span in (cap - 1, cap + 1):
                for method in (self.driver.guards, lambda: self.driver.candidate("PFKEYSPA.1")):
                    null, blocks = experiment(100)
                    null[0]["rate"], null[-1]["rate"] = 100 - span / 2, 100 + span / 2
                    with self.subTest(op=op, rl=rl, span=span, method=method), redirect_stderr(StringIO()):
                        with patch.object(c, "read_cells", return_value=[cell]), patch.object(c, "save"), \
                             patch.object(self.driver, "sample", side_effect=null + sum(blocks, [])) as sample_mock:
                            if span > cap:
                                with self.assertRaisesRegex(RuntimeError, "unstable"):
                                    method()
                                self.assertEqual(sample_mock.call_count, 4)  # No ON data after a bad null.
                            else:
                                method()

    def test_wide_mset_has_exactly_1024_distinct_nonmatching_keys(self):
        cell = next(x for x in c.read_cells(c.HERE / "cells.txt") if x.id.startswith("tracking-"))
        argv, names = self.driver.load_argv(cell, "tracking", True, self.place, Path("/unused"), 0)
        command = next(a for a in argv if a.startswith("--command=")).split("=", 1)[1].split()
        self.assertEqual(command[0], "MSET")
        keys = command[1::2]
        self.assertEqual(len(keys), 1024)
        self.assertEqual(len(set(keys)), 1024)
        self.assertTrue(all(not k.startswith("never:") for k in keys))
        self.assertEqual(names, ["MSET"])

    def test_stream_feature_precedes_get_on_same_memtier_connection(self):
        cell = next(x for x in c.read_cells(c.HERE / "cells.txt") if x.id.startswith("stream-"))
        argv, names = self.driver.load_argv(cell, "stream", True, self.place, Path("/unused"), 0)
        commands = [a for a in argv if a.startswith("--command=")]
        self.assertEqual(commands, ["--command=XREADGROUP GROUP g c COUNT 1 STREAMS pf:stream >", "--command=GET __key__"])
        self.assertIn("--rate-limiting=4096", argv)
        self.assertEqual(cell.conns, 1)
        self.assertEqual(names, ["GET", "XREADGROUP"])

    def test_tls_arms_hold_work_constant_and_restrict_protocol(self):
        argv_a, _ = self.driver.load_argv(self.cell, "tls", False, self.place, Path("/unused"), 0)
        argv_b, _ = self.driver.load_argv(self.cell, "tls", True, self.place, Path("/unused"), 0)
        argv_a[argv_a.index("-p") + 1] = "25001"
        self.assertEqual(argv_b, argv_a + ["--tls", "--tls-protocols=TLSv1.3", "--tls-skip-verify"])

    def test_population_or_missing_field_ttl_cannot_pass(self):
        conn = Mock()
        conn.must.side_effect = lambda *a: 1025 if a[0] == "DBSIZE" else [-1]
        with patch.object(c, "keyspace", return_value={"db0": {"subexpiry": 0}}):
            with self.assertRaisesRegex(RuntimeError, "HEXPIRE"):
                self.driver.witness_state(self.cell, dict(kind="info", on=True), conn)

    def test_stream_empty_delivery_fails_even_when_command_counter_advanced(self):
        state = dict(kind="stream", on=True, resident=1025, stream_entries=100000,
                     before=dict(pending=0))
        with patch.object(self.driver, "witness_state", return_value=dict(resident=1025, pending=0)):
            with self.assertRaisesRegex(RuntimeError, "pending mismatch"):
                self.driver.finish_witness(self.cell, state, Mock(), None, {}, {},
                                           {"cmdstat_xreadgroup": "calls=10,usec=0"})

    def test_flush_no_fired_calls_or_outside_load_fails(self):
        state = dict(kind="flush", on=True, resident=1024, before={})
        periodic = SimpleNamespace(rows=[dict(start=0, finish=1)])
        with patch.object(self.driver, "witness_state", return_value=dict(resident=1024)):
            with self.assertRaisesRegex(RuntimeError, "too few calls"):
                self.driver.finish_witness(self.cell, state, Mock(), periodic,
                                           dict(common_runtime=[2, 22]), {}, {})

    def test_tracking_no_invalidations_fails(self):
        state = dict(kind="tracking", on=True, resident=1025,
                     before=dict(stats={"tracking_invalidations": "0"}))
        periodic = SimpleNamespace(rows=[dict(start=i + .1, finish=i + .2) for i in range(20)])
        with patch.object(self.driver, "witness_state", return_value=dict(resident=1025, stats={"tracking_invalidations": "0"})):
            with self.assertRaisesRegex(RuntimeError, "invalidations"):
                self.driver.finish_witness(self.cell, state, Mock(), periodic, dict(common_runtime=[0, 20]), {}, {})

    def test_tls_no_load_handshakes_fails(self):
        stats = dict(tls_handshakes_completed="0", tls_handshakes_failed="0", tls_plaintext_output_bytes="0")
        state = dict(kind="tls", on=True, resident=1024, before=dict(stats=stats))
        with patch.object(self.driver, "witness_state", return_value=dict(resident=1024, stats=stats)):
            with self.assertRaisesRegex(RuntimeError, "handshake"):
                self.driver.finish_witness(self.cell, state, Mock(), None, {}, {}, {})

    def test_ttl_no_volatile_keys_fails(self):
        conn = Mock()
        conn.must.side_effect = lambda *a: 2048 if a[0] == "DBSIZE" else -1
        with patch.object(c, "keyspace", return_value={"db0": {"expires": 0}}):
            with self.assertRaisesRegex(RuntimeError, "background TTL"):
                self.driver.witness_state(self.cell, dict(kind="ttl", on=True, background=1024), conn)


class HistogramControls(unittest.TestCase):
    def test_server_rejection_or_incomplete_work_cannot_be_fast_confirmation(self):
        for after in ({"cmdstat_get": "calls=100,rejected_calls=1"},
                      {"cmdstat_get": "calls=99,rejected_calls=0"}):
            with self.assertRaises(RuntimeError):
                c.check_command_counts({}, after, {"GET": 100})

    def test_merge_counts_instead_of_percentiles_and_score_get_only(self):
        cell = replace(c.read_cells(c.HERE / "cells.txt")[0], conns=2)
        documents = []
        for count in (10000, 50):
            documents.append({"configuration": dict(threads=1, clients=1, pipeline=cell.depth,
                data_size=cell.data_bytes, key_minimum=1, key_maximum=cell.key_count), "ALL STATS": {
                "Totals": {"Count": count + 1, "Connection Errors": 0, "Connection Errors/sec": 0},
                "Runtime": {"Interrupted": False, "Time unit": "MILLISECONDS", "Total duration": 20000,
                            "Start time": 0, "Finish time": 20000},
                "Gets": {"Count": count}, "XLEN": {"Count": 1}}})
        def histogram(document, command, **kwargs):
            count = document["ALL STATS"]["Gets"]["Count"]
            if command != "GET":
                return Counter({500000: 1})
            return Counter({100: count - 1, 200000: 1}) if count == 10000 else Counter({100000: count})
        with patch.object(c, "command_histogram", side_effect=histogram):
            result = c.metrics(documents, cell, [dict(threads=1, clients=1)] * 2, ["GET", "XLEN"])
        self.assertEqual(result["p99_ms"], .1)
        self.assertEqual(result["p999_ms"], 100)
        self.assertEqual(result["max_ms"], 200)  # Rarer than p99.9; XLEN's 500 ms must not score.
        self.assertEqual(result["rate"], 502.5)
        self.assertEqual(result["completed"], {"GET": 10050, "XLEN": 2})


if __name__ == "__main__":
    unittest.main(verbosity=2)
