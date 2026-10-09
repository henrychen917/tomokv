#!/usr/bin/env python3
"""Serverless TTL cell controls, included in abbagate's existing self-test row."""
import contextlib
import copy
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


def suite(abba):
    from abba_evidence import validate_workload_evidence
    from abba_workloads import (require_workload_witness, require_workload_accounting,
                               memtier_workload_counts)
    from gate_measurements import shape, apply_floor
    from _abba_test_fixtures import saturation_record

    class TTLCell(unittest.TestCase):
        def setUp(self):
            self.cells = abba.read_cells(abba.ROOT / "tests/ttl_cells.txt")
            self.cell = self.cells[0]

        def test_option_text_argv_receipt_and_shape(self):
            template = (abba.ROOT / "tests/ttl_cells.txt").read_text().splitlines()[-2].split(" | cli=")[0]
            with tempfile.TemporaryDirectory(dir=abba.ROOT / "build") as directory:
                path = Path(directory) / "cells.txt"
                path.write_text(template + "\n")
                plain = abba.read_cells(path)[0]
                self.assertNotIn("client_flags", abba.cell_receipt(plain))
                self.assertNotIn("client_flags", abba.coverage([plain]))
                self.assertNotIn("client_flags", shape(plain))
                for flags, argv in (("--expiry-range=1-30", ["--expiry-range=1-30"]),
                                    ('--expiry-range "1-30"', ["--expiry-range", "1-30"])):
                    path.write_text(template + " | srv=--databases 16 | cli=" + flags + "\n")
                    cell = abba.read_cells(path)[0]
                    self.assertEqual(cell.client_flags, flags)
                    self.assertEqual(abba.client_arguments(flags), argv)
                    self.assertEqual(abba.cell_receipt(cell)["client_flags"], flags)
                    self.assertEqual(abba.coverage([cell])["client_flags"], {cell.id: flags})
                    self.assertEqual(shape(cell)["client_flags"], flags)
                    self.assertNotEqual(shape(cell), shape(plain))
                    self.assertEqual(abba.Cell(**abba.cell_receipt(cell)), cell)
                    self.assertEqual(abba.Cell(**abba.cell_receipt(plain)), plain)
                    ledger = dict(load_floors={plain.id: dict(status="calibrated", instances=8,
                        shape=shape(plain), geometry={}, instrument_sha256="same")})
                    self.assertEqual(apply_floor(plain, ledger, instrument_sha256="same").instances, 8)
                    self.assertEqual(apply_floor(replace(cell, server_flags=""), ledger,
                                                instrument_sha256="same").instances, 0)

        def test_unknown_duplicate_unsafe_and_vacuous_options_rejected(self):
            for option in ("cli=", "CLI=--expiry-range=1-30", "client=--expiry-range=1-30",
                    "cli=--expiry=1-30", "cli=-e 1-30", "cli=--expiry_range=1-30",
                    "cli=--expiry-range=1-30 --expiry-range=1-30", "cli=--expiry-range",
                    "cli=--expiry-range=0-30", "cli=--expiry-range=30-1", "cli=--expiry-range=1-0",
                    "cli=--expiry-range=1-2147483648", "cli=--expiry-range=1-x",
                    "cli=--expiry-range='1-30", "cli=--expiry-range=1-30; touch nope",
                    "cli=--expiry-range=$(touch nope)", "cli=--expiry-range=1-30\n",
                    "cli=--ratio=1:0", "cli=--pipeline=64", "cli=--test-time=1",
                    "cli=--server=elsewhere", "cli=-p 6379", "cli=--key-pattern=R:R",
                    "cli=--key-maximum=1", "cli=--select-db=1", "cli=--command=GET",
                    "cli=--json-out-file=elsewhere", "cli=--threads=1", "cli=--clients=1"):
                with self.subTest(option=option), self.assertRaises(ValueError):
                    abba.cell_options([option])
            with self.assertRaisesRegex(ValueError, "duplicate"):
                abba.cell_options(["cli=--expiry-range=1-30"] * 2)
            for changes in (dict(op="GET"), dict(op="MSET"), dict(op="REORDER"), dict(dbs=16)):
                with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "db0 SET or MIX"):
                    replace(self.cell, **changes)

        def test_null_cannot_cover_a_plain_twin_even_with_same_id_and_source_digest(self):
            from abba_evidence import _match_null
            plain = replace(self.cell, client_flags="")
            control = dict(instrument_fingerprint={"fixture": "same code"}, window_seconds=20,
                cell_source=dict(sha256="same-source-for-negative-control", total_cells=1),
                cells=[dict(cell=abba.cell_receipt(plain), rounds=[dict(instances=8)])],
                elapsed_seconds=1, candidate={"sha256": "same-binary"})
            comparison = dict(copy.deepcopy(control), run_kind="comparison", coverage=dict(ids=[plain.id]))
            with mock.patch("abba_evidence.validate_measurements", return_value=(20, {})), \
                    mock.patch("abba_evidence.validate_null", return_value=(1, {})):
                self.assertEqual(_match_null(comparison, control, now=30)["status"], "MATCHED")
                comparison["cells"][0]["cell"] = abba.cell_receipt(self.cell)
                with self.assertRaisesRegex(ValueError, "null does not cover this exact cell"):
                    _match_null(comparison, control, now=30)

        def test_inventory_geometry_and_pin(self):
            self.assertEqual([cell.id for cell in self.cells], ["ttls", "ttlm"])
            self.assertEqual([(cell.op, cell.mix) for cell in self.cells], [("SET", "-"), ("MIX", "1:1")])
            h05 = next(cell for cell in abba.read_cells(abba.ROOT / "tests/wb_rule_cells.txt") if cell.id == "h05")
            for cell in self.cells:
                self.assertEqual((cell.mode, cell.read_local, cell.overlap, cell.reorder,
                    cell.conns, cell.data_bytes, cell.depth, cell.atomic, cell.score, cell.instances),
                    ("1s", 0, 0, 0, 512, 64, 32, 1, "rate", h05.instances))
                self.assertEqual(cell.key_count, 20_000_000)
                self.assertEqual(abba.client_arguments(cell.client_flags), ["--expiry-range=1-30"])
            args = SimpleNamespace(cells=abba.ROOT / "tests/ttl_cells.txt", subset="full", only="")
            self.assertEqual(abba.selected_split_ratio(args, 32), "16:16")
            layout = abba.load_layout(list(range(32, 112)), 8, 512)
            self.assertEqual(sum(row["threads"] * row["clients"] for row in layout), 512)
            self.assertEqual(sum(row["threads"] for row in layout), 64)

        def test_witness_zero_missing_bad_and_reset_fail_for_either_arm(self):
            for arm in ("A", "B"):
                for after in ({"expired_keys": "100"}, {"expired_keys": "99"}, {},
                              {"expired_keys": "-1"}, {"expired_keys": "1.5"}, {"expired_keys": 101}):
                    with self.subTest(arm=arm, after=after), self.assertRaisesRegex(
                            RuntimeError, f"EXPIRY-FIRED: arm {arm}"):
                        abba.expiry_witness(self.cell, {"expired_keys": "100"}, after, arm)
                with self.assertRaisesRegex(RuntimeError, "before expired_keys"):
                    abba.expiry_witness(self.cell, {}, {"expired_keys": "101"}, arm)
            proof = abba.expiry_witness(self.cell, {"expired_keys": "100"}, {"expired_keys": "101"}, "A")
            self.assertEqual(proof, dict(name="EXPIRY-FIRED", field="expired_keys", before=100,
                                         after=101, delta=1, verdict="PASS"))
            self.assertIsNone(abba.expiry_witness(replace(self.cell, client_flags=""), {}, {}, "A"))

        def evidence(self, cell, arm="A"):
            layout = abba.load_layout(list(range(32, 112)), 8, 512)
            before, after = {"expired_keys": "100"}, {"expired_keys": "101"}
            return dict(arm=arm, instances=8, complete=True, rate=100., latency_ms=1., busy_pct=99.9,
                window_seconds=20., midpoint_monotonic=11., saturation=saturation_record(), load_layout=layout,
                load_argv=[["memtier", "--expiry-range=1-30"] for _ in layout],
                info_before=before, info_after=after,
                expiry_witness=abba.expiry_witness(cell, before, after, arm))

        def test_raw_endpoint_replay_and_arm_specific_named_fail(self):
            runs = [self.evidence(self.cell, arm) for arm in abba.ORDER]
            block = dict(instances=8, runs=runs)
            assessment = abba.assess(self.cell, [block])
            self.assertEqual(assessment["verdict"], "PASS", assessment["reasons"])
            for index, arm in enumerate(abba.ORDER):
                broken = copy.deepcopy(block)
                broken["runs"][index]["info_after"]["expired_keys"] = "100"
                # The cached PASS witness deliberately remains intact: replay must catch it.
                assessment = abba.assess(self.cell, [broken])
                self.assertEqual(assessment["verdict"], "FAIL")
                self.assertIn(f"EXPIRY-FIRED: arm {arm} expired_keys delta=0", " ".join(assessment["reasons"]))
            for mutate in (lambda run: run.pop("expiry_witness"),
                           lambda run: run["expiry_witness"].update(delta=2),
                           lambda run: run["load_argv"][0].pop(),
                           lambda run: run["load_argv"][0].insert(1, "--expiry-range=1-30"),
                           lambda run: run["load_argv"][0].insert(2, "--hide-histogram")):
                run = self.evidence(self.cell)
                mutate(run)
                with self.assertRaises(RuntimeError):
                    abba.require_cell_options_evidence(self.cell, run)

        def test_setex_server_counters_match_logical_memtier_sets_exactly(self):
            for cell in self.cells:
                before = dict(cmdstat_set="calls=100000", cmdstat_setex="calls=100", cmdstat_get="calls=100")
                after = dict(cmdstat_set="calls=100000", cmdstat_setex="calls=200", cmdstat_get="calls=200")
                witness = require_workload_witness(cell, before, after, {}, {})
                self.assertEqual(witness["SET"], dict(calls=100, server_command="SETEX"))
                names = abba.workload_command_names(cell)
                stats = {name + "s": dict(Count=100, **{"Percentile Latencies": {
                    "Histogram log format": {"Compressed Histogram": "fixture"}}}) for name in names}
                stats.update(Totals=dict(Count=100 * len(names)), Runtime=dict(Interrupted=False))
                with mock.patch("abba_workloads.decode_histogram", return_value={1: 100}):
                    producer = memtier_workload_counts(cell, {"ALL STATS": stats}, cell.conns)
                accounting = require_workload_accounting(cell, before, after, [producer])
                self.assertEqual(accounting["commands"]["SET"]["server_command"], "SETEX")
                run = dict(self.evidence(cell), data_bytes=64,
                    workload_raw=dict(before=before, after=after, mode_before={}, mode_after={}),
                    workload_witness=witness, whole_run_commandstats_before=before,
                    whole_run_commandstats_after=after, memtier=[producer], whole_run_accounting=accounting)
                validate_workload_evidence(cell, run)
                run["info_after"]["expired_keys"] = "100"
                with self.assertRaisesRegex(ValueError, "EXPIRY-FIRED"):
                    validate_workload_evidence(cell, run)
                after["cmdstat_setex"] = "calls=199"
                with self.assertRaisesRegex(RuntimeError, "SETEX whole-run accounting mismatch"):
                    require_workload_accounting(cell, before, after, [producer])
                after["cmdstat_setex"] = "calls=100"
                after["cmdstat_set"] = "calls=100100"
                with self.assertRaisesRegex(RuntimeError, "SETEX did not execute"):
                    require_workload_witness(cell, before, after, {}, {})

        def test_population_never_gets_client_flags(self):
            children = mock.Mock()
            children.start.return_value.wait.return_value = 0
            args = SimpleNamespace(server_cores="112-119", server_smt="", load_cores="120-127",
                                   load_smt="", port=9090, memtier="never-executed-memtier")
            runner = abba.Runner(args, Path("/unused"), {}, children)
            conn = mock.Mock()
            conn.must.return_value = self.cell.key_count
            for arm in ("A", "B"):
                runner.populate(self.cell, arm, conn, Path("/unused"))
                argv = children.start.call_args.args[0]
                self.assertIn("--key-maximum=20000000", argv)
                self.assertFalse(any(arg.startswith("--expiry") for arg in argv))

        def test_measured_window_wiring_both_arms_and_failed_artifact(self):
            # Intercept every child and socket; exercise the actual measurement path
            # through its central snapshots, argv construction and cleanup.
            positions = []
            for cell in self.cells:
                for arm in ("A", "B"):
                    for expires in (True, False):
                        with self.subTest(cell=cell.id, arm=arm, expires=expires), \
                                tempfile.TemporaryDirectory(dir=abba.ROOT / "build") as directory:
                            directory = Path(directory)
                            cell = replace(cell, conns=4, instances=2)
                            phase, launches, stopped = [0], [], []
                            server = SimpleNamespace(pid=123, poll=lambda: None)
                            def start(argv, log, folder):
                                launches.append(argv)
                                return server if len(launches) == 1 else SimpleNamespace(
                                    pid=123 + len(launches), poll=lambda: None, wait=lambda timeout: 0)
                            children = SimpleNamespace(start=start, stop=lambda child: stopped.append(child.pid))
                            conn = mock.Mock()
                            conn.must.return_value = [b"atomic", b"1"]
                            def snapshot(_conn, section):
                                if section == "server":
                                    return dict(process_id="123", read_local="0")
                                if section == "clients":
                                    return dict(connected_clients="5")
                                if section == "commandstats":
                                    value = str(100 if phase[0] < 2 else 2100)
                                    return dict(cmdstat_setex="calls=" + value, cmdstat_get="calls=" + value)
                                self.assertEqual(section, "stats")
                                return dict(total_commands_processed="100" if phase[0] < 2 else "4101",
                                    keyspace_misses="0" if phase[0] < 2 else "10",
                                    expired_keys="7" if phase[0] < 2 or not expires else "17")
                            args = SimpleNamespace(server_cores="112-113", server_smt="", load_cores="120-121",
                                load_smt="", port=9090, memtier="never-executed-memtier")
                            runner = abba.Runner(args, directory, {arm: Path("never-executed-server")}, children)
                            lb = SimpleNamespace(threads={i: dict(role="fused", busy=10, idle=0) for i in (0, 1)})
                            totals = dict(rate=100., latency_ms=1., connections=2,
                                reported_counts={name: 1000 for name in abba.workload_command_names(cell)},
                                completed_hdr_counts={name: 1000 for name in abba.workload_command_names(cell)},
                                outstanding_bound=64)
                            def sleep(seconds):
                                self.assertIn(seconds, (abba.WARMUP, abba.WINDOW))
                                phase[0] += 1
                            with mock.patch.multiple(abba, require_unbound_port=mock.Mock(),
                                    Conn=mock.Mock(return_value=conn), info=mock.Mock(side_effect=snapshot),
                                    lb_snapshot=mock.Mock(return_value=lb), cpu_seconds=mock.Mock(return_value=0),
                                    generator_cpu_endpoint=mock.Mock(return_value={}),
                                    generator_cpu_between=mock.Mock(return_value={}),
                                    busy_between=mock.Mock(return_value=(99.9, {})), busy_deltas=mock.Mock(return_value={}),
                                    bottleneck_saturation=mock.Mock(return_value=saturation_record(threads=2)),
                                    productive_saturation=mock.Mock(return_value={}),
                                    require_saturation_window=mock.Mock(return_value={"score_pct": 99.9}),
                                    memtier_totals=mock.Mock(return_value=totals)), \
                                    mock.patch.object(runner, "populate", return_value=None), \
                                    mock.patch.object(abba.time, "sleep", side_effect=sleep), \
                                    contextlib.redirect_stdout(io.StringIO()):
                                if expires:
                                    result = runner.measure(cell, arm, 1, 2, {})
                                    self.assertTrue(result["complete"])
                                    self.assertEqual(result["expiry_witness"]["delta"], 10)
                                else:
                                    with self.assertRaisesRegex(RuntimeError, f"EXPIRY-FIRED: arm {arm}.*delta=0"):
                                        runner.measure(cell, arm, 1, 2, {})
                            for argv in launches[1:]:
                                self.assertEqual(argv[-1], "--expiry-range=1-30")
                                positions.append(argv.index("--expiry-range=1-30"))
                            artifact = json.loads((directory / cell.id / f"n2-1-{arm}/measurement.json").read_text())
                            self.assertEqual(artifact["complete"], expires)
                            self.assertEqual(artifact["info_before"]["expired_keys"], "7")
                            self.assertEqual(artifact["info_after"]["expired_keys"], "17" if expires else "7")
                            if not expires:
                                self.assertIn("EXPIRY-FIRED", artifact["error"])
                            self.assertEqual(len(stopped), 3)
                            conn.close.assert_called_once()
            self.assertEqual(len(set(positions)), 1)

    return unittest.defaultTestLoader.loadTestsFromTestCase(TTLCell)


if __name__ == "__main__":
    import abbagate
    (abbagate.ROOT / "build").mkdir(exist_ok=True)
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite(abbagate)).wasSuccessful())
