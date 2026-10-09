#!/usr/bin/env python3
"""Serverless negative controls for confirmation validity, not a box benchmark."""
from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import confirm as c


def sample(arm="A", on=False, rate=100, p99=1, p999=2):
    return dict(arm=arm, trigger_on=on, complete=True, rate=rate, p99_ms=p99,
                p999_ms=p999, witness=dict(verdict="PASS"))


def experiment(rate=94, p99=1):
    null = [sample(arm) for arm in c.ORDER]
    blocks = [[sample(arm, arm == "B", rate if arm == "B" else 100,
                      p99 if arm == "B" else 1) for arm in c.ORDER] for _ in range(3)]
    return null, blocks


class VerdictControls(unittest.TestCase):
    def test_null_never_confirms_and_both_thresholds_work(self):
        for rate, tail, verdict in ((100, 1, False), (94, 1, True), (100, 2, True), (96, 1.99, False)):
            with self.subTest(rate=rate, tail=tail):
                result = c.decide(*experiment(rate, tail))
                self.assertEqual(result["verdict"] == "HIGH upside CONFIRMED", verdict)

    def test_null_tail_spread_cannot_be_ignored(self):
        null, blocks = experiment(100, 2)
        null[0]["p99_ms"] = 5
        self.assertEqual(c.decide(null, blocks)["verdict"], "NOT CONFIRMED (mark only)")

    def test_unstable_null_or_arm_fails_instead_of_widening_threshold(self):
        for which in ("null", "on", "off"):
            null, blocks = experiment()
            target = null[0] if which == "null" else blocks[1][1 if which == "on" else 0]
            target["rate"] *= 1.1
            with self.subTest(which=which), self.assertRaisesRegex(RuntimeError, "unstable"):
                c.decide(null, blocks)

    def test_no_best_block_selection_or_p999_only_confirmation(self):
        null, blocks = experiment(100, 1)
        for row in blocks[0]:
            if row["arm"] == "B":
                row["rate"] = 50
        for block in blocks:
            for row in block:
                if row["arm"] == "B":
                    row["p999_ms"] = 200
        self.assertEqual(c.decide(null, blocks)["verdict"], "NOT CONFIRMED (mark only)")

    def test_missing_trigger_incomplete_or_mislabelled_arm_fails(self):
        for mutation in (lambda r: r["witness"].update(verdict="FAIL"),
                         lambda r: r.update(complete=False),
                         lambda r: r.update(trigger_on=False),
                         lambda r: r.update(arm="A")):
            null, blocks = experiment()
            mutation(blocks[0][1])
            with self.assertRaises(RuntimeError):
                c.decide(null, blocks)
        null, blocks = experiment()
        with self.assertRaises(RuntimeError):
            c.decide(null, blocks[:2])


class DriverControls(unittest.TestCase):
    def setUp(self):
        self.cell = c.read_cells(c.HERE / "cells.txt")[0]
        self.driver = object.__new__(c.Campaign)
        self.driver.args = SimpleNamespace(smoke=False)
        self.driver.memtier = "/usr/bin/memtier_benchmark"
        self.driver.seconds = 20
        self.driver.port = 25000
        self.place = dict(cpus=[32], threads=1, clients=1)

    def test_all_cell_files_parse_and_no_trigger_can_run_as_stock_cell(self):
        self.assertEqual(len(c.read_cells(c.HERE / "cells.txt")), 12)
        self.assertEqual(len(c.read_cells(c.HERE / "guards.txt")), 16)
        for ident, (prefix, _) in c.SPECS.items():
            self.assertTrue(any(x.id.startswith(prefix) for x in c.read_cells(c.HERE / "cells.txt")), ident)

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
            return Counter({100 if count == 10000 else 100000: count}) if command == "GET" else Counter({500000: 1})
        with patch.object(c, "command_histogram", side_effect=histogram):
            result = c.metrics(documents, cell, [dict(threads=1, clients=1)] * 2, ["GET", "XLEN"])
        self.assertEqual(result["p99_ms"], .1)
        self.assertEqual(result["p999_ms"], 100)
        self.assertEqual(result["rate"], 502.5)
        self.assertEqual(result["completed"], {"GET": 10050, "XLEN": 2})


if __name__ == "__main__":
    unittest.main(verbosity=2)
