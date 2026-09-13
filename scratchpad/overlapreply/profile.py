#!/usr/bin/env python3
"""Read an existing gate cpu-profile.json offline; never attach to a process.

O7 needs to distinguish a reply crossing from storage work before implementation.
The gate's PMCs and schedstat can explain IPC and scheduled time, but cannot
attribute stalls to either source path. Keep that limit in every output. Reuse
the gate's raw-record decoders, including its no-multiplexing rule, instead of
turning a cached summary or a partial capture into measurement evidence.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import abba_profile as gate


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def interval(first, last, description):
    gate.require(finite(first) and finite(last) and first < last,
                 f"invalid {description} interval")
    return last - first


def raw_counts(group):
    gate.require(group["status"] == "COMPLETE", "incomplete PMC group")
    events = group["events"]
    ids = {event["id"]: event["name"] for event in events}
    gate.require(len(ids) == len(events) == len(gate.EVENTS) and
                 {(e["name"], e["config"]) for e in events} == set(gate.EVENTS),
                 "missing, duplicate or unexpected PMC event")
    readings = []
    for endpoint in ("before", "after"):
        saved = group[endpoint]
        decoded = gate.decode_group(bytes.fromhex(saved["raw_hex"]), ids)
        gate.require(decoded == saved, f"PMC {endpoint} disagrees with its raw bytes")
        readings.append(decoded)
    delta = gate.perf_delta(*readings)
    gate.require(delta == group["delta"], "saved PMC delta disagrees with raw endpoints")
    return delta["counts"]


def ratios(counts, commands):
    # Ratio of sums, never the mean of per-thread IPCs. A dormant executor has
    # undefined IPC, while its zero counts still belong in the server totals.
    return dict(ipc=counts["instructions"] / counts["cycles"] if counts["cycles"] else None,
                approx_instructions_per_command=counts["instructions"] / commands,
                approx_cycles_per_command=counts["cycles"] / commands)


def summarize(document):
    profile = document.get("cpu_profile", document)
    gate.require(profile["schema"] == 1 and profile["kind"] == "owned-cpu-profile",
                 "unsupported profile format")
    gate.require(profile["status"] == "COMPLETE", "profile is not complete")
    gate.require(profile["normal_gate_eligible"] is False and profile["decision_input"] is False,
                 "diagnostic capture was relabelled as verdict evidence")
    start, end = profile["central_start_monotonic"], profile["central_end_monotonic"]
    duration = interval(start, end, "central command")
    commands = profile["central_commands"]
    gate.require(type(commands) is int and commands > 0, "missing central commands")
    gate.require(profile["sched_schedstats"] in ("0", "1"), "unknown schedstats setting")
    wait_available = profile["sched_schedstats"] == "1"
    servers = [p for p in profile["processes"] if p["kind"] == "server"]
    gate.require(len(servers) == 1, "profile must contain exactly one server")
    server = servers[0]
    before, after = server["before"], server["after"]
    changes = gate.task_deltas(before, after, wait_available=wait_available)
    gate.require(changes == server["deltas"], "saved scheduler deltas disagree with endpoints")
    groups = profile["server_groups"]
    tids = [str(group["tid"]) for group in groups]
    gate.require(len(tids) == len(set(tids)) and set(tids) == set(changes),
                 "PMC coverage differs from the full server thread set")
    totals = {name: 0 for name, _ in gate.EVENTS}
    threads = []
    for group, tid in zip(groups, tids):
        first, last = before["threads"][tid], after["threads"][tid]
        gate.require(all(finite(t) for t in (first["before_monotonic"], first["after_monotonic"],
                                            last["before_monotonic"], last["after_monotonic"])) and
                     first["before_monotonic"] <= first["after_monotonic"] <= start < end <=
                     last["before_monotonic"] <= last["after_monotonic"],
                     f"TID {tid} scheduler endpoints do not encompass the command interval")
        earliest = group["enable_before_monotonic"]
        enabled = group["enable_after_monotonic"]
        disabled = group["disable_before_monotonic"]
        latest = group["disable_after_monotonic"]
        gate.require(all(finite(t) for t in (earliest, enabled, disabled, latest)) and
                     earliest <= enabled <= start < end <= disabled <= latest,
                     f"TID {tid} PMC interval does not encompass the command interval")
        counts = raw_counts(group)
        for name in totals:
            totals[name] += counts[name]
        change = changes[tid]
        threads.append(dict(tid=int(tid), comm=first["stat"]["comm"],
            cpus_allowed=change["cpus_allowed"], role="unattributed",
            counts=counts, **ratios(counts, commands),
            runtime_ns=change["runtime_ns"], runqueue_wait_ns=change["runqueue_wait_ns"],
            timeslices=change["timeslices"],
            pmc_start_offset_seconds=enabled - start, pmc_end_offset_seconds=disabled - end,
            pmc_max_overhang_seconds=(start - earliest) + (latest - end),
            schedstat_max_span_seconds=last["after_monotonic"] - first["before_monotonic"]))
    gate.require(all(n > 0 for n in totals.values()), "no aggregate PMC progress")
    runtime = sum(t["runtime_ns"] for t in threads)
    gate.require(runtime > 0, "server schedstat runtime did not advance")
    # Do not infer IO/EX roles from TID order or a shared comm string. Retain CPU
    # affinities for the maintainer's captured worker-role map. Likewise, kernel
    # CPU time and runqueue delay are different things; neither is a memory stall.
    return dict(schema=1, kind="o7-cpu-profile-summary", normal_gate_eligible=False,
        decision_input=False, source_attribution="UNAVAILABLE: this artifact has no sampled instruction addresses",
        prerequisite="UNRESOLVED: source-attributed reply/crossing/storage evidence is still required",
        scope=profile["scope"], alignment=profile["alignment"],
        operation_unit="central server commands; never multiply MGET/MSET by key count",
        commands=commands, central_seconds=duration, rate_commands_per_second=commands / duration,
        server_pid=before["pid"], executable=before["executable"],
        executable_digest_status="UNVERIFIED: proc executable metadata is not a capture-time SHA-256",
        counts=totals, **ratios(totals, commands), runtime_ns=runtime,
        runqueue_wait_ns=sum(t["runqueue_wait_ns"] for t in threads) if wait_available else None,
        runqueue_wait_status="AVAILABLE" if wait_available else "UNAVAILABLE: kernel schedstats disabled",
        threads=sorted(threads, key=lambda t: t["tid"]))


def markdown(report):
    def number(value):
        return "unavailable" if value is None else f"{value:,.3f}"

    lines = ["CPU diagnostics only. Per-command PMCs encompass the command interval; they are approximate.",
             "", report["prerequisite"], "",
             "| Rate commands/s | IPC | Approx. instructions/command | Approx. cycles/command |",
             "| ---: | ---: | ---: | ---: |",
             "| " + " | ".join(number(report[key]) for key in
                 ("rate_commands_per_second", "ipc", "approx_instructions_per_command",
                  "approx_cycles_per_command")) + " |", "",
             "Thread IPC uses each thread's own counters. Per-command contributions use all server commands.",
             "Roles require the captured worker map; TID order does not identify IO or EX.", "",
             "| TID | CPU affinity | IPC | Approx. instr/cmd | Approx. cycles/cmd | Runtime ms | Runqueue ms | Max PMC overhang ms |",
             "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in report["threads"]:
        wait = row["runqueue_wait_ns"]
        values = [row["ipc"], row["approx_instructions_per_command"], row["approx_cycles_per_command"],
                  row["runtime_ns"] / 1e6, None if wait is None else wait / 1e6,
                  row["pmc_max_overhang_seconds"] * 1000]
        lines.append(f"| {row['tid']} | {','.join(map(str, row['cpus_allowed']))} | " +
                     " | ".join(map(number, values)) + " |")
    return "\n".join(lines) + "\n"


def self_test():
    # Synthetic raw counters only: no perf_event_open, /proc, server or load.
    # Corrupt the evidence, not just the expected summary, so a partial capture
    # cannot turn into apparent zero fixed cost or a favorable IPC comparison.
    import copy
    import struct
    import unittest

    class ReaderTest(unittest.TestCase):
        def fixture(self, wait="1"):
            def snapshot(advance):
                threads = {}
                for tid in (101, 102, 103):
                    threads[str(tid)] = dict(before_monotonic=9 + 22 * advance,
                        after_monotonic=9.1 + 22 * advance,
                        stat=dict(start_ticks=7, comm="tomokv", user_ticks=advance,
                                  system_ticks=advance, last_cpu=tid - 101),
                        uids=[1000] * 4, cpus_allowed=[tid - 101], scheduler={},
                        schedstat=dict(runtime_ns=advance * 1_000_000_000,
                                       runqueue_wait_ns=advance * 1000, timeslices=advance))
                return dict(pid=101, stat=dict(start_ticks=7), executable=dict(path="synthetic-PRE"),
                            threads=threads)

            before, after = snapshot(0), snapshot(1)
            server = dict(kind="server", before=before, after=after,
                          deltas=gate.task_deltas(before, after, wait_available=wait == "1"))
            groups = []
            for tid, counts in ((101, (1000, 2000, 500)), (102, (3000, 3000, 1500)), (103, (0, 0, 0))):
                ids = {i + 1: name for i, (name, _) in enumerate(gate.EVENTS)}
                endpoints = []
                for advance in (0, 1):
                    elapsed = advance * (100 if any(counts) else 0)
                    values = [3, elapsed, elapsed]
                    for ident, count in zip(ids, counts):
                        values.extend((advance * count, ident))
                    endpoints.append(gate.decode_group(struct.pack("=" + "Q" * len(values), *values), ids))
                groups.append(dict(tid=tid, status="COMPLETE", before=endpoints[0], after=endpoints[1],
                    events=[dict(id=i + 1, name=name, config=config) for i, (name, config) in enumerate(gate.EVENTS)],
                    delta=gate.perf_delta(*endpoints), enable_before_monotonic=9.4,
                    enable_after_monotonic=9.5, disable_before_monotonic=30.5, disable_after_monotonic=30.6))
            return dict(schema=1, kind="owned-cpu-profile", status="COMPLETE", normal_gate_eligible=False,
                decision_input=False, central_start_monotonic=10., central_end_monotonic=30.,
                central_commands=100, sched_schedstats=wait, processes=[server], server_groups=groups,
                scope="synthetic", alignment="encompassing intervals")

        def test_ratio_of_sums_and_idle_thread(self):
            result = summarize({"cpu_profile": self.fixture()})
            self.assertEqual((result["rate_commands_per_second"], result["ipc"],
                              result["approx_instructions_per_command"], result["approx_cycles_per_command"]),
                             (5, 1.25, 50, 40))
            self.assertEqual(len(result["threads"]), 3)
            self.assertIsNone(result["threads"][2]["ipc"])
            self.assertFalse(result["decision_input"])
            self.assertIn("UNRESOLVED", markdown(result))

        def test_disabled_schedstats_never_becomes_zero_wait(self):
            result = summarize(self.fixture(wait="0"))
            self.assertIsNone(result["runqueue_wait_ns"])
            self.assertTrue(all(t["runqueue_wait_ns"] is None for t in result["threads"]))

        def test_corrupt_evidence_cannot_pass(self):
            mutations = [
                lambda p: p.update(status="INVALID"),
                lambda p: p.update(decision_input=True),
                lambda p: p.update(central_commands=0),
                lambda p: p.update(central_end_monotonic=float("nan")),
                lambda p: p["server_groups"].pop(),
                lambda p: p["server_groups"].append(copy.deepcopy(p["server_groups"][0])),
                lambda p: p["server_groups"][0].update(enable_after_monotonic=11),
                lambda p: p["server_groups"][0]["delta"]["counts"].update(instructions=9999),
                lambda p: p["server_groups"][0]["after"].update(time_running_ns=50),
                lambda p: p["processes"][0]["after"]["threads"]["101"]["stat"].update(start_ticks=8),
                lambda p: p["processes"][0]["after"]["threads"]["101"].update(cpus_allowed=[99]),
                lambda p: p["processes"][0]["after"]["threads"]["101"].update(before_monotonic=29),
            ]
            for mutation in mutations:
                with self.subTest(mutation=mutations.index(mutation)):
                    profile = self.fixture()
                    mutation(profile)
                    with self.assertRaises(gate.ProfileError):
                        summarize(profile)

        def test_multiplexed_raw_counters_are_rejected(self):
            profile = self.fixture()
            group = profile["server_groups"][0]
            raw = bytearray.fromhex(group["after"]["raw_hex"])
            struct.pack_into("=Q", raw, 16, 50)
            ids = {e["id"]: e["name"] for e in group["events"]}
            group["after"] = gate.decode_group(raw, ids)
            with self.assertRaisesRegex(gate.ProfileError, "multiplexed"):
                summarize(profile)

    return unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReaderTest)).wasSuccessful()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, help="saved cpu-profile.json or gate run JSON containing cpu_profile")
    parser.add_argument("--output", type=Path, help="new JSON artifact inside this worktree; Markdown goes to stdout")
    parser.add_argument("--self-test", action="store_true", help="exercise synthetic records offline")
    args = parser.parse_args()
    if args.self_test:
        parser.exit(0 if self_test() else 1)
    if args.input is None:
        parser.error("a saved profile is required")
    try:
        raw = args.input.read_bytes()
        report = summarize(json.loads(raw))
        report["input"] = dict(path=str(args.input.resolve()), sha256=hashlib.sha256(raw).hexdigest())
        if args.output is not None:
            output = args.output.resolve()
            gate.require(output.is_relative_to(ROOT), "output must stay in this worktree")
            with output.open("x") as stream:
                json.dump(report, stream, indent=2, allow_nan=False)
                stream.write("\n")
        print(markdown(report), end="")
    except (OSError, ValueError, KeyError, TypeError, gate.ProfileError) as error:
        parser.exit(2, f"unavailable: {error}\n")


if __name__ == "__main__":
    main()
