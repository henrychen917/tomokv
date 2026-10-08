#!/usr/bin/env python3
"""Directed multi-key diagnostics. Mainline only; NEVER a gate row.

One MKPROBE_ROW JSON object per cell/sample/arm. Failed attempts are retained.
All scored boots restore a fresh snapshot, so shutdown WB totals exclude wire
population. Core counters, memory counters and symbol samples use separate boots.
--dry-run checks memtier grammar, proves the unset override and prints argv.
--self-test starts no server or load generator. See MEASURE-REQUEST-mkprobe.md.
"""
from __future__ import annotations

import argparse
from collections import Counter
import contextlib
from dataclasses import asdict, replace
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import re
import shlex
import shutil
import signal
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from _lib import Conn
from abbagate import (Runner, read_cells, load_layout, info, require_unbound_port,
                      generator_cpu_endpoint, generator_cpu_between, memtier_totals)
from abba_workloads import command_stat
from abba_profile import EVENTS
from abba_saturation import parse_snapshot, bottleneck_saturation
from gate_quiet import QuietMonitor, QuietViolation
from gate_measurements import ratio as measured_ratio
from gateplan import parse_cpu_range, cpu_string, read_topology
from exbatch_directed import Children, PerfWindow as AckWindow, digest, quiet_file_guard

SCHEMA = 1
CELLS = ROOT / "tests/mkprobe_cells.txt"
FROZEN_REV = "65a9d0a22"
HEADLINE_SHA = "d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350"
WORKLOAD_SHA = "0060d75451b97c4274600eefcd8c950e0683359b31df910233d5e60765e15ce9"
MULTI_IDS = "m02 m03 m05 m06 m26 m27 m50 m51 m53 m54 m74 m75".split()
NULL_IDS = MULTI_IDS + ["h05", "h06"]  # 14, recipes defined in headline_cells.txt.
PAIR_IDS = "m02 m03 m05 m06 p8g p8s h05 h06".split()
SWEEP_IDS = "m02 m03 m05 m06".split()
KEYS = (2, 3, 4, 7, 8, 9, 16)
NA = "not available"
FLIPCTL_DISARMED = NA + ": flipctl disarmed (flip-auto 0)"
NULL_K = 3
MEDIAN_NORMAL_FACTOR = math.sqrt(math.pi / 2)
# Instability guards, NOT acceptance/resolution bands. Owner's outward caps on
# calib/refnull-spread.py's observed maxima: quiet 5.30%, noisy 8.84% (n=30),
# with multi-key same-arm ranges reaching 16.64% (n=6). Full source table and
# scope distinction: MEASURE-REQUEST-mkprobe3.md. Never clamp a measured band.
STABILITY_CAPS = {"quiet": .06, "noisy/multi-key": .20}
BATCH_RANGE = (.9, 1.1)  # Predeclared operational meaning of the note's '~1.0'.
WARMUP, WINDOW, TAIL = 3, 20, 5
CORE_EVENTS = tuple("ref-cycles" if name == "ref_cycles" else name for name, _ in EVENTS)
MEMORY_EVENTS = (
    "ls_any_fills_from_sys.all", "ls_dmnd_fills_from_sys.all",
    "de_dis_dispatch_token_stalls1.store_queue_rsrc_stall",
    "ls_l1_d_tlb_miss.all", "ls_l1_d_tlb_miss.all_l2_miss")
MEMORY_NAMES = ("any_fills", "demand_fills", "store_buffer_stall_cycles", "dtlb_misses", "table_walk_requests")
SYMBOLS = {
    "allocator": r"\b(?:(?:__GI_)?(?:__libc_)?(?:malloc|free|realloc)|je_\w+)\b",
    "malloc": r"\b(?:__GI_)?(?:__libc_)?malloc\b",
    "free": r"\b(?:__GI_)?(?:__libc_)?free\b",
    "realloc": r"\b(?:__GI_)?(?:__libc_)?realloc\b",
    "je_*": r"\bje_\w+\b",
    "SmallBuf::grow": r"SmallBuf.*::grow\(",
    "refresh_snapshot_floor": r"ScatterArenaPool::refresh_snapshot_floor\(",
    "active_snapshot_floor": r"active_snapshot_floor\(",
    "build_initial_groups": r"build_initial_groups\(",
    "xshard_prepare": r"xshard_prepare\(",
    "xshard_execute": r"xshard_execute\(",
    "assemble_mget": r"assemble_mget\(",
}
SIGNAL_SUFFIXES = ("masked_lane_high_water", "masked_lane_full_events",
                   "queue_delay_ewma_us", "oldest_age_max_us")


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def save(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def number(value, label, *, positive=False):
    n = float(value)
    require(math.isfinite(n) and (n > 0 if positive else n >= 0), f"invalid {label}: {value!r}")
    return n


def cores_arg(text):
    try:
        server, load = text.split(",")
        a, b = parse_cpu_range(server), parse_cpu_range(load)
        require(len(a) >= 2 and len(b) >= 8 and not set(a) & set(b), "need disjoint server and >=8 load CPUs")
        return server, load
    except (ValueError, RuntimeError) as error:
        raise argparse.ArgumentTypeError("--cores SERVER_RANGE,LOAD_RANGE: " + str(error))


def cells():
    require(digest(ROOT / "tests/headline_cells.txt") == HEADLINE_SHA, "frozen headline changed; re-audit recipes")
    result = read_cells(CELLS, measurements={"load_floors": {}})
    sources = {}
    for path in (ROOT / "tests/headline_cells.txt", ROOT / "tests/wb_rule_cells.txt"):
        sources.update({c.id: c for c in read_cells(path, measurements={"load_floors": {}})})
    for cell in result:
        if cell.id not in ("mk128g", "mk128s"):
            require(cell == sources[cell.id], f"{cell.id} drifted from its canonical definition")
    require(len(result) == 19, "mkprobe inventory must contain 19 cells")
    return {c.id: c for c in result}


def workload_args(cell, key_count):
    # Exercise the actual import-time environment override, without altering the
    # imported gate module or allowing ambient TOMO_MULTI_KEYS to leak between jobs.
    with contextlib.ExitStack() as stack:
        previous = os.environ.get("TOMO_MULTI_KEYS")
        def restore():
            if previous is None:
                os.environ.pop("TOMO_MULTI_KEYS", None)
            else:
                os.environ["TOMO_MULTI_KEYS"] = previous
        stack.callback(restore)
        if key_count is None:
            os.environ.pop("TOMO_MULTI_KEYS", None)
        else:
            os.environ["TOMO_MULTI_KEYS"] = str(key_count)
        spec = importlib.util.spec_from_file_location("mkprobe_workloads", ROOT / "tests/abba_workloads.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.workload_arguments(cell)


def load_commands(args, cell, folder, keys):
    runner = object.__new__(Runner)
    runner.args = args
    layout = load_layout(parse_cpu_range(args.cores[1]), cell.instances or args.instances, cell.conns)
    commands = [runner.memtier(place, cell=cell) + workload_args(cell, keys) +
                [f"--pipeline={cell.depth}", f"--test-time={WARMUP + args.window + TAIL}",
                 f"--json-out-file={folder / f'load-{i}.json'}"] for i, place in enumerate(layout)]
    return layout, commands


def argv_proof(args):
    old = subprocess.check_output(["git", "show", f"{FROZEN_REV}:tests/abba_workloads.py"], cwd=ROOT)
    require(sha(old) == WORKLOAD_SHA, "frozen workload source changed")
    namespace = {"__name__": "mkprobe_frozen_workloads"}
    exec(compile(old, "frozen-abba_workloads.py", "exec"), namespace)
    payload = []
    headline = read_cells(ROOT / "tests/headline_cells.txt", measurements={"load_floors": {}})
    proof_args = argparse.Namespace(**vars(args))
    # All 181 headline recipes include sixteen-generator tails. Generating their
    # mainline vectors is serverless and does not schedule work on these CPUs.
    proof_args.cores = ("0-31", "32-111")
    for cell in headline + list(cells().values()):
        # Runner.memtier is shared unchanged. Compare the complete execve vector,
        # encoded as NUL-terminated UTF-8 arguments, not a shell-quoted rendering.
        _, commands = load_commands(proof_args, cell, Path("RUN"), None)
        for cmd in commands:
            new_work = workload_args(cell, None)
            old_work = namespace["workload_arguments"](cell)
            offset = len(cmd) - len(new_work) - 3
            before = cmd[:offset] + old_work + cmd[offset + len(new_work):]
            left, right = (b"\0".join(s.encode() for s in x) + b"\0" for x in (before, cmd))
            require(left == right, f"default argv changed: {cell.id}")
            payload.append(left)
    checks = []
    for count in KEYS:
        for ident in ("m02", "m05"):
            argv = workload_args(cells()[ident], count)
            command = next(x.split("=", 1)[1] for x in argv if x.startswith("--command="))
            require(command.split().count("__key__") == count, "override did not change every generated key")
            require(command.split().count("__data__") == (count if ident == "m05" else 0), "MSET value/key arity differs")
            checks.append(dict(cell=ident, keys=count, command=command))
    require(workload_args(cells()["m02"], None) == namespace["workload_arguments"](cells()["m02"]),
            "override leaked after restoring unset environment")
    return dict(status="PASS", headline_sha256=HEADLINE_SHA, frozen_revision=FROZEN_REV,
                frozen_workloads_sha256=WORKLOAD_SHA, complete_argv_vectors=len(payload),
                nul_argv_sha256=sha(b"".join(payload)), encoding="execve UTF-8 arguments separated/terminated by NUL",
                override_round_trip=checks, unset_after_sweep="PASS")


def grammar(args):
    before = digest(args.memtier)
    p = subprocess.run([args.memtier, "--help"], capture_output=True, text=True, timeout=10)
    text = p.stdout + p.stderr
    for name in ("command", "command-ratio", "command-key-pattern", "pipeline", "test-time",
                 "json-out-file", "distinct-client-seed", "key-minimum", "key-maximum"):
        require(re.search(r"--" + name + r"(?:[=\s]|$)", text), f"memtier grammar missing --{name}")
    require(before == digest(args.memtier), "memtier changed during grammar check")
    return dict(path=args.memtier, sha256=before, help_sha256=sha(text.encode()), help_exit_status=p.returncode)


def selected(args, inventory):
    default = {"null": NULL_IDS, "wb-pair": PAIR_IDS, "keys": SWEEP_IDS,
               "smoke": ["m02", "p8g"]}.get(args.mode, list(inventory))
    names = args.cells.split(",") if args.cells else default
    require(names and len(set(names)) == len(names) and all(x in inventory for x in names), "unknown/duplicate cell")
    if args.mode == "null":
        require(names == NULL_IDS, "null must cover the frozen 14 saturation cells in order")
    if args.mode in ("wb-pair", "keys"):
        require(set(names) == set(default), f"{args.mode} requires its complete command/depth matrix")
    return [replace(inventory[n], atomic=args.atomic) if args.atomic is not None else inventory[n] for n in names]


def jobs(args, chosen):
    result = []
    samples = 1 if args.mode == "smoke" else args.samples
    if args.mode in ("null", "wb-pair"):
        require(samples % 2 == 0, "ABBA requires an even number of samples per arm")
    for block in range(samples // 2 if args.mode in ("null", "wb-pair") else samples):
        for cell in chosen:
            if args.mode in ("null", "wb-pair"):
                arms = ("A", "B", "B", "A")
                for position, arm in enumerate(arms):
                    sample = block * 2 + (0 if position < 2 else 1)
                    policy = (0 if arm == "A" else 1) if args.mode == "wb-pair" else 1
                    result.append(dict(cell=cell.id, keys=8, sample=sample, arm=arm, wb_policy=policy))
            else:
                counts = KEYS if args.mode == "keys" else (8,)
                # Alternate ascending/descending sweeps; never finish all samples
                # of a single key count before beginning its adjacent control.
                for key_count in (counts if block % 2 == 0 else tuple(reversed(counts))):
                    result.append(dict(cell=cell.id, keys=key_count, sample=block, arm="base", wb_policy=1))
    for job in result:
        job["id"] = f"{job['cell']}-k{job['keys']}-{job['arm']}-s{job['sample']:02d}"
    return result


def server_command(args, cell, folder, policy):
    n = len(parse_cpu_range(args.cores[0]))
    command = ["taskset", "-c", args.cores[0], str(args.binary), "--port", str(args.port),
               "--bind", "127.0.0.1", "--dir", str(folder), "--save", "", "--appendonly", "no",
               "--enable-debug-command", "yes", "--thread-mode", cell.mode,
               "--read-local", str(cell.read_local), "--overlap", str(cell.overlap),
               "--reorder", str(cell.reorder), "--atomic", str(cell.atomic), "--wb-policy", str(policy),
               "--key-lb", "1", "--client-lb", "1", "--flip-auto", "0"]
    ex = n
    if cell.mode == "2s":
        ratio = args.ratio or measured_ratio("correctness" if n == 8 else "abba", n)
        io, ex = map(int, ratio.split(":"))
        require(io > 0 and ex > 0 and io + ex == n, "split ratio must cover selected server CPUs")
        command += ["--ratio", ratio]
    # Use the shipped default, not the gate's --shards 16 geometry.
    command += ["--shards", str(256 if ex >= 32 else 8 * ex)]
    return command


def perf_command(args, folder, kind, server_pid=None):
    control = f"--control=fifo:{folder / 'perf.ctl'},{folder / 'perf.ack'}"
    common = ["taskset", "-c", str(parse_cpu_range(args.cores[1])[0]), "perf"]
    if kind == "symbols":
        return common + ["record", "-p", str(server_pid) if server_pid is not None else "{SERVER_PID}",
                         "-C", args.cores[0], "-e", "cycles", "-F", "199",
                         "--call-graph", "dwarf,8192", "--delay=-1", control,
                         "-o", str(folder / "perf.data")]
    events = CORE_EVENTS if kind == "core" else MEMORY_EVENTS
    return common + ["stat", "-a", "-A", "-C", args.cores[0], "-x", ",", "--no-big-num", "--no-scale",
                     "-e", "{" + ",".join(events) + "}:Duk", "--delay=-1", control,
                     "-o", str(folder / "perf.csv")]


class PerfWindow(AckWindow):
    def __init__(self, args, folder, children, kind, server_pid=None):
        self.folder, self.children, self.kind = folder, children, kind
        self.cores = args.cores
        self.ctl = self.ack = None
        self.process = None
        try:
            for name in ("perf.ctl", "perf.ack"):
                os.mkfifo(folder / name)
            self.ctl = os.open(folder / "perf.ctl", os.O_RDWR | os.O_NONBLOCK)
            self.ack = os.open(folder / "perf.ack", os.O_RDWR | os.O_NONBLOCK)
            self.process = children.start(perf_command(args, folder, kind, server_pid), folder / "perf.log", folder)
            self.command("disable")
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.process is not None:
            self.children.stop(self.process, signal.SIGINT)
        for name in ("ctl", "ack"):
            fd = getattr(self, name)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)


def parse_perf(text, expected_cpus, events):
    rows = {}
    for line in text.splitlines():
        if not line.startswith("CPU"):
            continue
        fields = [x.strip() for x in line.split(",")]
        require(len(fields) >= 6, "truncated perf CSV")
        cpu = int(fields[0][3:])
        name = fields[3].split(":")[0]
        require(name in events, f"unexpected perf event {name}")
        value = number(fields[1], name)
        runtime = number(fields[4], "event runtime", positive=True)
        running = number(fields[5].rstrip("%"), "running percent", positive=True)
        require(running == 100, f"multiplexed/unavailable event: {line}")
        row = rows.setdefault(cpu, {})
        require(name not in row, "duplicate perf CPU/event")
        row[name] = dict(value=value, runtime_ns=runtime)
    require(set(rows) == set(expected_cpus), "perf did not cover exactly the server CPUs")
    for row in rows.values():
        require(set(row) == set(events), "missing perf group event")
        require(len({v['runtime_ns'] for v in row.values()}) == 1, "group members have different windows")
    return dict(cpus=rows, totals={event: sum(r[event]["value"] for r in rows.values()) for event in events})


def core_metrics(totals, commands, keys, seconds, cores):
    require(commands > 0 and keys > 0 and seconds > 0 and cores > 0, "invalid core-counter denominator")
    cyc, ins, ref = (number(totals[n], n, positive=True) for n in CORE_EVENTS)
    result = dict(instr_per_op=ins / commands, ipc=ins / cyc, cyc_per_op=cyc / commands,
                  cycles_per_reference_cycle=cyc / ref, cycles_per_key=cyc / commands / keys)
    require(.01 < result["ipc"] < 10 and 1 < result["instr_per_op"] < 1e8 and 1 < result["cyc_per_op"] < 1e9,
            "implausible IPC/instructions/cycles per op")
    require(cyc / seconds / cores < 8e9, "cycles exceed 8GHz/core physical bound")
    return result


def symbol_shares(text):
    require(re.search(r"Total Lost Samples:\s+0(?:\s|$)", text), "lost/unknown perf record samples")
    sample_match = re.search(r"# Samples:\s+([\d,]+)\s+of event 'cycles'", text)
    require(sample_match, "missing cycles sample count")
    total = 0
    weights = Counter()
    found = Counter()
    for line in text.splitlines():
        if not re.match(r"\s*\d+(?:\.\d+)?%\s*;", line):
            continue
        fields = [s.strip() for s in line.split(";")]
        require(len(fields) >= 3 and fields[1].isdigit(), "unsupported perf report period/symbol grammar")
        weight = int(fields[1])
        symbol = re.sub(r"^\[[.kguH]\]\s*", "", fields[2])
        total += weight
        for name, pattern in SYMBOLS.items():
            if re.search(pattern, symbol):
                weights[name] += weight
                found[name] += 1
    require(total > 0, "empty symbol profile")
    event_count = re.search(r"# Event count \(approx\.\):\s+(\d+)", text)
    if event_count:
        require(total == int(event_count[1]), "symbol periods do not reconcile to the captured cycles period")
    return dict(total_period=total, samples=int(sample_match[1].replace(",", "")),
                shares_pct={name: 100 * weights[name] / total for name in SYMBOLS},
                observed_symbols=dict(found), scope="exclusive leaf/inline symbol, period weighted; unobserved is not proof of absence")


def parse_shutdown(text):
    reports = [json.loads(line.split("shutdown_report ", 1)[1]) for line in text.splitlines()
               if line.startswith("shutdown_report ")]
    require(len(reports) == 1 and reports[0].get("schema") == 1, "missing/duplicate/unknown shutdown-report JSON")
    row = reports[0]
    wb = row["wb"]
    for key in ("retired", "sends_submitted", "serves", "serves_empty", "sends_completed",
                "send_errors", "peer_aborts", "short_writes"):
        require(key in wb, f"shutdown counter missing: {key}; production counter work belongs to code lane")
        number(wb[key], key)
    require(wb["retired"] > 0 and wb["sends_submitted"] > 0 and wb["serves"] > 0, "no WB progress")
    require(wb["serves_empty"] <= wb["serves"], "empty serves exceed serves")
    require(wb["sends_completed"] == wb["sends_submitted"], "shutdown left incomplete sends")
    require(wb["send_errors"] == wb["peer_aborts"] == 0, "workload send error/peer abort")
    return row


def telemetry(cell, observations, before, after):
    result = {}
    flip_armed = False
    if cell.mode == "2s":
        # INFO's flip_auto reports flipctl_enabled(), not merely the requested
        # mode/configuration. Missing or changing state cannot excuse a zero.
        flags = [row.get("flip_auto") for row in observations]
        require(flags and all(flag in ("0", "1") for flag in flags), "missing/invalid INFO flip_auto")
        require(len(set(flags)) == 1, "INFO flip_auto changed during central window")
        result["flip_auto"] = int(flags[0])
        flip_armed = flags[0] == "1"
    for name in ("atomic_fanout_cuts", "atomic_read_cuts_held"):
        require(all(name in row for row in observations), f"INFO counter missing: {name}; stop for code lane")
        vals = [number(row[name], name) for row in observations]
        result[name] = max(vals) if name.endswith("held") else vals[-1] - vals[0]
        require(result[name] >= 0, f"reset {name}")
    result["atomic_read_cuts_held_scope"] = "maximum observed gauge during central window, not cumulative cuts"
    result["atomic_fanout_cuts_scope"] = "central endpoint delta; atomic=1 may legitimately be zero"
    for command in ("mget", "mset"):
        result["cmdstat_" + command + "_calls"] = command_stat(after, command)[0] - command_stat(before, command)[0]
        require(result["cmdstat_" + command + "_calls"] >= 0, "commandstats reset")
    calls = result["cmdstat_mget_calls"]
    result["fanout_cuts_per_mget"] = result["atomic_fanout_cuts"] / calls if calls else NA
    result["atomic_cut_witness"] = (
        "fanout cuts are not an engagement witness at atomic=1; use held-cut gauge" if cell.atomic else
        "PASS" if calls and .9 <= result["fanout_cuts_per_mget"] <= 1.1 else
        "not applicable" if not calls else "FAIL")
    for role in ("fused", "io", "ex"):
        for suffix in SIGNAL_SUFFIXES:
            key = f"lb_{role}_{suffix}"
            if (cell.mode == "1s" and (role != "fused" or suffix in SIGNAL_SUFFIXES[2:])) or (cell.mode == "2s" and role == "fused"):
                result[key] = NA
                continue
            if cell.mode == "2s" and not flip_armed and suffix in SIGNAL_SUFFIXES[2:]:
                result[key] = FLIPCTL_DISARMED
                continue
            require(all(key in row for row in observations), f"INFO counter missing: {key}; stop for code lane")
            vals = [number(row[key], key) for row in observations]
            result[key] = max(vals)
    if cell.mode == "2s":
        for suffix in ("queue_delay_samples", "oldest_age_samples"):
            key = "lb_ex_" + suffix
            if not flip_armed:
                result[key] = FLIPCTL_DISARMED
                continue
            require(all(key in row for row in observations), f"split sampler counter missing: {key}")
            values = [number(row[key], key) for row in observations]
            require(values[-1] > values[0], f"split sampler did not progress in central window: {key}")
            result[key] = values[-1] - values[0]
    if flip_armed:
        for suffix in SIGNAL_SUFFIXES[2:]:
            require(result["lb_ex_" + suffix] > 0, f"split {suffix} stayed zero; sample is invalid")
            require(result["lb_ex_" + suffix] <= 60_000_000, f"split {suffix} exceeds the existing lbsignals test's 60s sanity bound")
    result["queue_signal_scope"] = "central observed maxima; native role names; full-events are cumulative high-water observations"
    return result


def boot(args, cell, folder, policy, children, binary_sha):
    require_unbound_port(args.port)
    require(digest(args.binary) == binary_sha, "binary changed before launch")
    command = server_command(args, cell, folder, policy)
    server = children.start(command, folder / "server.log", folder)
    conn = None
    deadline = time.monotonic() + 30
    while conn is None:
        require(server.poll() is None, f"server exited before boot: {folder / 'server.log'}")
        try:
            conn = Conn("127.0.0.1", args.port, timeout=10)
            identity = info(conn, "all")
            require(int(identity["process_id"]) == server.pid, "listener is not owned child")
        except (OSError, EOFError):
            if conn:
                conn.close()
                conn = None
            require(time.monotonic() < deadline, "server boot timeout")
            time.sleep(.1)
    require(digest(f"/proc/{server.pid}/exe") == binary_sha, "running binary differs from receipt")
    for field, expected in dict(thread_mode=cell.mode, read_local=str(cell.read_local), atomic=str(cell.atomic),
                                wb_policy=str(policy), flip_auto="0", key_lb="1", client_lb="1",
                                overlap=str(cell.overlap), reorder=str(cell.reorder), net_io="uring", pin_threads="1",
                                shards=command[command.index("--shards") + 1]).items():
        require(identity.get(field) == expected, f"boot {field}={identity.get(field)!r}, expected {expected}")
    placement = {int(t): int(c) for t, c in (p.split(":") for p in identity["thread_cpus"].split(","))}
    require(set(placement.values()) == set(parse_cpu_range(args.cores[0])), "server escaped requested CPU geometry")
    return server, conn, identity, command


def prepare_snapshot(args, cell, folder, children, binary_sha):
    folder.mkdir()
    server, conn, identity, command = boot(args, cell, folder, 1, children, binary_sha)
    try:
        require(conn.must("DBSIZE") == 0, "setup boot was not fresh")
        runner = object.__new__(Runner)
        runner.args, runner.children = args, children
        runner.load_cpus = parse_cpu_range(args.cores[1])
        runner.populate(cell, "setup", conn, folder)
        require(conn.must("SAVE") == b"OK", "snapshot SAVE failed")
        filename = conn.must("CONFIG", "GET", "dbfilename")[1].decode()
        require(filename == "dump.tomo", "unexpected snapshot filename")
    finally:
        conn.close()
        children.stop(server)
    require(server.returncode == 0, "setup shutdown failed")
    path = folder / "dump.tomo"
    return dict(path=str(path), sha256=digest(path), boot=identity, argv=command,
                scope="unscored wire population; measured boots restore this image with fresh WB counters")


def snapshot_fixture(args, cell, children, binary_sha):
    cache = args.snapshot_cache or args.output / "snapshots"
    cache.mkdir(parents=True, exist_ok=True)
    argv = server_command(args, cell, Path("SNAPSHOT"), 1)
    key = sha(canonical(dict(binary=binary_sha, keys=cell.key_count, size=cell.data_bytes,
                             shards=argv[argv.index("--shards") + 1])))[:24]
    folder = cache / key
    folder.mkdir(exist_ok=True)
    receipt = folder / "snapshot.json"
    with (folder / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if receipt.exists():
            record = json.loads(receipt.read_text())
            require(digest(record["path"]) == record["sha256"], "cached snapshot changed")
            return record
        attempt = folder / f"setup-{len(list(folder.glob('setup-*'))) + 1:03d}"
        record = prepare_snapshot(args, cell, attempt, children, binary_sha)
        save(receipt, record)
        return record


def wait_until(deadline, processes, monitor):
    while time.monotonic() < deadline:
        require(all(p.poll() is None for p in processes), "owned workload exited during central window")
        monitor.check()
        time.sleep(min(.1, max(0, deadline - time.monotonic())))


def box_inventory(owned=()):
    """Conservative read-only box-share screen; never signals foreign processes.

    The historical boxguard.sh is not installed in this worktree. Record actual
    known competing servers/generators/compilers, in addition to gate_quiet's
    selected-CPU activity budget. Affinity alone is not evidence of activity.
    This is not a claim to recognize every possible source of interference.
    """
    owned = {os.getpid(), *(p.pid for p in owned)}
    competitors = []
    for path in Path("/proc").iterdir():
        if not path.name.isdigit() or int(path.name) in owned:
            continue
        try:
            name = (path / "comm").read_text().strip()
            if not name.startswith(("tomokv", "memtier", "redis-server", "valkey-server", "dragonfly", "keydb-server", "memcached", "cc1", "clang", "lto1", "rustc")):
                continue
            status = (path / "status").read_text()
            state = re.search(r"^State:\s+(\S+)", status, re.M)
            if state and state[1] == "Z":
                continue
            affinity = re.search(r"^Cpus_allowed_list:\s+(.*)", status, re.M)
            stat = (path / "stat").read_text().rsplit(")", 1)[1].split()
            competitors.append(dict(pid=int(path.name), name=name, cpus=affinity[1] if affinity else "unknown",
                                    start=int(stat[19]), ticks=int(stat[11]) + int(stat[12])))
        except (FileNotFoundError, ProcessLookupError):
            continue
    return competitors


def box_progress(before, after, budget_seconds):
    old = {(r["pid"], r["start"]): r["ticks"] for r in before}
    progress = [{**r, "cpu_seconds": max(0, r["ticks"] - old.get((r["pid"], r["start"]), 0)) / os.sysconf("SC_CLK_TCK")}
                for r in after]
    total = sum(r["cpu_seconds"] for r in progress)
    return dict(processes=progress, cpu_seconds=total, budget_seconds=budget_seconds, passed=total <= budget_seconds)


def run_pass(args, cell, job, folder, kind, snapshot, children, monitor, receipt):
    folder.mkdir()
    reserve = 5 * 1024**3
    estimate = Path(snapshot["path"]).stat().st_size
    if kind == "symbols":
        estimate += (args.window + 2) * len(parse_cpu_range(args.cores[0])) * 199 * 10000
    require(shutil.disk_usage(folder).free > reserve + estimate, "insufficient free disk for retained evidence plus 5GiB reserve")
    # Clone an immutable setup image; never adopt the setup process or its counters.
    shutil.copyfile(snapshot["path"], folder / "dump.tomo")
    require(digest(folder / "dump.tomo") == snapshot["sha256"], "snapshot copy changed")
    server = conn = perf = None
    result = dict(kind=kind, complete=False, artifacts=str(folder), argv={})
    try:
        server, conn, identity, command = boot(args, cell, folder, job["wb_policy"], children, receipt["binary_sha256"])
        result.update(boot_info=identity, pid=server.pid)
        result["argv"]["server"] = command
        require(conn.must("DBSIZE") == cell.key_count, "restored population count differs")
        require(all(conn.must("STRLEN", f"memtier-{k}") == cell.data_bytes for k in (1, cell.key_count)), "restored value sizes differ")
        before_full = info(conn, "commandstats")
        perf = PerfWindow(args, folder, children, kind, server.pid)
        result["argv"]["perf"] = perf_command(args, folder, kind, server.pid)
        layout, commands = load_commands(args, cell, folder, job["keys"])
        result["argv"]["load"] = commands
        result["layout"] = layout
        loads = [children.start(cmd, folder / f"load-{i}.log", folder) for i, cmd in enumerate(commands)]
        wait_until(time.monotonic() + WARMUP, [server, *loads], monitor)
        require(int(info(conn, "clients")["connected_clients"]) == cell.conns + 1, "not all requested load clients connected")
        first_lb = conn.must("DEBUG", "LBSIGNALS")
        (folder / "lb-before.txt").write_bytes(first_lb)
        cpu_before = [generator_cpu_endpoint(p) for p in loads]
        enabled = perf.command("enable")
        first = info(conn, "all")
        t0 = time.monotonic()
        observations = [first]
        deadline = t0 + args.window
        next_poll = t0 + 1
        foreign = box_inventory(children.processes)
        foreign_at = time.monotonic()
        result["box_runtime"] = []
        while time.monotonic() < deadline:
            wait_until(min(next_poll, deadline), [server, *loads], monitor)
            if time.monotonic() < deadline:
                current = box_inventory(children.processes)
                now = time.monotonic()
                share = box_progress(foreign, current, monitor.cpu_budget_seconds * (now - foreign_at) / monitor.window_seconds)
                result["box_runtime"].append(share)
                require(share["passed"], "competing benchmark/compiler consumed the box-share CPU budget during central window")
                foreign, foreign_at = current, now
                observations.append(info(conn, "all"))
                next_poll += 1
        last = info(conn, "all")
        t1 = time.monotonic()
        disabled = perf.command("disable")
        cpu_after = [generator_cpu_endpoint(p) for p in loads]
        observations.append(last)
        final_lb = conn.must("DEBUG", "LBSIGNALS")
        (folder / "lb-after.txt").write_bytes(final_lb)
        save(folder / "info.json", observations)
        require(t1 - t0 <= args.window * 1.02, "central interval overran by >2%")
        require(t0 - enabled["before"] + disabled["after"] - t1 <= args.window * .01, "perf/command window overhang >1%")
        count = command_stat(last, cell.op)[0] - command_stat(first, cell.op)[0]
        require(count > 0, f"{cell.op} made no central progress")
        result.update(commands=count, seconds=t1 - t0, rate=count / (t1 - t0),
                      perf_window=dict(enable=enabled, disable=disabled, central_start=t0, central_end=t1))
        result["telemetry"] = telemetry(cell, observations, first, last)
        result["saturation"] = bottleneck_saturation(parse_snapshot(first_lb), parse_snapshot(final_lb), floor_pct=95)
        result["generator_cpu"] = [generator_cpu_between(b, a, place["threads"], t0, t1)
                                   for b, a, place in zip(cpu_before, cpu_after, layout)]
        require(all(r["cpu_pct_per_configured_worker"] < 98 for r in result["generator_cpu"]), "load generator has no CPU headroom")
        # Counters are disabled before drain; no unrelated numerator from teardown.
        perf.close()
        perf = None
        if kind == "symbols":
            argv = ["taskset", "-c", args.cores[1], "perf", "report", "-i", str(folder / "perf.data"),
                    "--stdio", "--stdio-color", "never", "--no-children", "--inline", "--show-total-period",
                    "--percent-limit", "0", "--sort", "symbol", "-t", ";"]
            result["argv"]["perf_report"] = argv
        else:
            events = CORE_EVENTS if kind == "core" else MEMORY_EVENTS
            result["perf"] = parse_perf((folder / "perf.csv").read_text(), parse_cpu_range(args.cores[0]), events)
            totals = result["perf"]["totals"]
            if kind == "core":
                result.update(core_metrics(totals, count, job["keys"] if cell.op.startswith("M") else 1,
                                           t1 - t0, len(parse_cpu_range(args.cores[0]))))
            else:
                counts = dict(zip(MEMORY_NAMES, (totals[e] for e in MEMORY_EVENTS)))
                require(counts["any_fills"] >= counts["demand_fills"], "negative any-demand fills residual")
                require(counts["table_walk_requests"] <= counts["dtlb_misses"], "table walks exceed all dTLB misses")
                counts["coherence_residual"] = counts["any_fills"] - counts["demand_fills"]
                result["memory_per_op"] = {k: v / count for k, v in counts.items()}
        for process in loads:
            require(process.wait(timeout=TAIL + 15) == 0, "memtier failed; see retained log")
        after_full = info(conn, "commandstats")
        whole = command_stat(after_full, cell.op)[0] - command_stat(before_full, cell.op)[0]
        documents = []
        for i, place in enumerate(layout):
            path = folder / f"load-{i}.json"
            documents.append(memtier_totals(path, cell, place["clients"] * place["threads"]))
            log = (folder / f"load-{i}.log").read_text()
            require(not re.search(r"handle error response:|\berror:|\bfailed\b", log, re.I), "memtier logged protocol/connection error")
        completed = sum(d["completed_hdr_counts"][cell.op] for d in documents)
        require(completed == whole, f"server/HDR completed command mismatch {whole}/{completed}")
        require(whole >= count and whole > 0, "whole-run count smaller than central interval")
        result["completion"] = dict(server_calls=whole, completed_hdr=completed, generators=documents)
        require(conn.must("DBSIZE") == cell.key_count, "workload changed key count")
        conn.close()
        conn = None
        children.stop(server)
        require(server.returncode == 0, "measured server did not shut down cleanly")
        shutdown = parse_shutdown((folder / "server.log").read_text())
        result["shutdown"] = shutdown
        wb = shutdown["wb"]
        result["retired_per_send"] = wb["retired"] / wb["sends_submitted"]
        result["empty_serve_fraction"] = wb["serves_empty"] / wb["serves"]
        require(result["retired_per_send"] <= cell.depth * cell.conns + 100, "implausible reply batching")
        result["wb_scope"] = "measured boot lifetime: warmup + central + tail + bounded observers; excludes population"
        result["observer_call_bound"] = len(observations) + 20
        require(result["observer_call_bound"] / whole < .001, "observer commands exceed 0.1% of workload")
        require(digest(args.binary) == receipt["binary_sha256"] and digest(args.memtier) == receipt["memtier"]["sha256"], "executable changed during sample")
        if kind == "symbols":
            # Post-process only after load generators and server have exited.
            p = subprocess.run(result["argv"]["perf_report"], capture_output=True, text=True, timeout=120)
            (folder / "symbols.txt").write_text(p.stdout + p.stderr)
            require(p.returncode == 0, "perf report failed")
            result["symbols"] = symbol_shares(p.stdout)
        result["complete"] = True
        # The SHA-bound cache retains the exact input. Successful private copies
        # would otherwise consume hundreds of GB over a night; failed copies stay.
        (folder / "dump.tomo").unlink()
        return result
    except BaseException as error:
        result["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if perf:
            perf.close()
        if conn:
            conn.close()
        if server:
            children.stop(server)
        save(folder / "pass.json", result)


def run_sample(args, cell, job, folder, receipt):
    folder.mkdir(parents=True, exist_ok=False)
    started = time.time()
    row = dict(schema=SCHEMA, mode=args.mode, **job, status="FAILED", started=started,
               geometry=args.cores, binary_sha256=receipt["binary_sha256"], receipt_sha256=sha(canonical(receipt)),
               artifact=str(folder), rate=NA, instr_per_op=NA, ipc=NA, cyc_per_op=NA, cycles_per_key=NA,
               retired_per_send=NA, empty_serve_fraction=NA, passes=[])
    # Keep the full recipe separately from the short cell ID in every row.
    row["recipe"] = asdict(cell)
    row["keys_per_command"] = job["keys"] if cell.op in ("MGET", "MSET") else 1
    row.update({name: NA for name in ("atomic_fanout_cuts", "atomic_read_cuts_held", "cmdstat_mget_calls", "cmdstat_mset_calls")})
    row.update({f"lb_{role}_{suffix}": NA for role in ("fused", "io", "ex") for suffix in SIGNAL_SUFFIXES})
    children, monitor = Children(), None
    try:
        quiet_file_guard()
        row["box_preflight"] = box_inventory()
        monitor = QuietMonitor(parse_cpu_range(args.cores[0]), parse_cpu_range(args.cores[1]), ports=[args.port],
                               sample_artifact=folder / "quiet.jsonl")
        monitor.start()
        row["box_share"] = box_progress(row["box_preflight"], box_inventory(), monitor.cpu_budget_seconds)
        if not row["box_share"]["passed"]:
            raise QuietViolation("named benchmark/compiler exceeded box-share preflight budget: " + json.dumps(row["box_share"]))
        snapshot = snapshot_fixture(args, cell, children, receipt["binary_sha256"])
        row["snapshot"] = snapshot
        for kind in (["core", "memory", "symbols"] if args.mode == "probes" else
                     ["core", "memory"] if args.mode == "coherence" else
                     ["core", "symbols"] if args.mode == "symbols" else ["core"]):
            piece = run_pass(args, cell, job, folder / kind, kind, snapshot, children, monitor, receipt)
            row["passes"].append(piece)
        core = row["passes"][0]
        for key in ("rate", "instr_per_op", "ipc", "cyc_per_op", "cycles_per_key", "retired_per_send", "empty_serve_fraction"):
            row[key] = core[key]
        row.update({k: core["shutdown"]["wb"][k] for k in ("retired", "sends_submitted", "serves_empty", "serves")})
        row.update(commands=core["commands"], seconds=core["seconds"])
        row.update(core["telemetry"])
        row["saturation_pct"] = min(piece["saturation"]["score_pct"] for piece in row["passes"])
        by_kind = {piece["kind"]: piece for piece in row["passes"]}
        if "memory" in by_kind:
            row["memory_per_op"] = by_kind["memory"]["memory_per_op"]
            row["memory_pass_rate"] = by_kind["memory"]["rate"]
            row["memory_pass_scope"] = "separate fresh boot, its own central command denominator"
        if "symbols" in by_kind:
            row["symbols"] = by_kind["symbols"]["symbols"]
        quiet_file_guard()
        monitor.check()
        row["status"] = "COMPLETE"
    except BaseException as error:
        row["error"] = f"{type(error).__name__}: {error}"
        row["quiet_refusal"] = isinstance(error, QuietViolation)
        if not isinstance(error, Exception):
            raise
    finally:
        children.close()
        row["children"] = [dict(pid=p.pid, exit_status=p.poll()) for p in children.processes]
        if monitor:
            row["quiet"] = monitor.close()
        row["finished"] = time.time()
        row["elapsed_seconds"] = row["finished"] - started
        save(folder / "row.json", row)
    return row


def complete_rows(paths):
    rows, receipts = [], []
    for directory in paths:
        directory = Path(directory)
        receipt = json.loads((directory / "receipt.json").read_text())
        receipts.append(receipt)
        for path in sorted((directory / "rows").glob("*.json")):
            row = json.loads(path.read_text())
            require(row["receipt_sha256"] == sha(canonical(receipt)), f"unbound result row: {path}")
            if row["status"] == "COMPLETE":
                require(row["quiet"]["complete"] and all(p["exit_status"] is not None for p in row["children"]), "incomplete quiet/reaping evidence")
                require(row["binary_sha256"] == receipt["binary_sha256"] and row["geometry"] == receipt["geometry"], "row binary/geometry differs from receipt")
                for name in ("rate", "instr_per_op", "ipc", "cyc_per_op", "cycles_per_key", "retired_per_send", "empty_serve_fraction"):
                    number(row[name], name, positive=name != "empty_serve_fraction")
                    require(row[name] == row["passes"][0][name], "row does not match its recorded core pass: " + name)
                require(math.isclose(row["ipc"], row["instr_per_op"] / row["cyc_per_op"], rel_tol=1e-12), "IPC != instr/op divided by cyc/op")
            rows.append(row)
    return rows, receipts


def observations(rows, mode, cell, *, keys=8, arm="base", atomic=1, metric="cyc_per_op"):
    chosen = [r for r in rows if r["status"] == "COMPLETE" and (r["mode"] == mode or
              (r["mode"] == "probes" and mode in ("counters", "coherence", "symbols"))) and r["cell"] == cell
              and r["keys"] == keys and r["arm"] == arm and r["recipe"]["atomic"] == atomic]
    require(len({r["sample"] for r in chosen}) == len(chosen), f"duplicate samples: {mode}/{cell}/{keys}/{arm}")
    require(len(chosen) >= 6, f"{mode}/{cell}/k{keys}/{arm}/atomic{atomic}: n={len(chosen)} < 6")
    require(statistics.median(r["saturation_pct"] for r in chosen) >= 95, f"{mode}/{cell}: productive-role median below 95%")
    values = []
    for row in sorted(chosen, key=lambda r: r["sample"]):
        value = row
        for part in metric.split("/"):
            value = value[part]
        values.append(number(value, metric))
    require(all(v > 0 for v in values) or metric.startswith("symbols/") or metric.startswith("memory_per_op/"), f"no progress: {metric}")
    return values


def interval(values):
    # Deterministic percentile bootstrap, used only as a diagnostic uncertainty
    # interval; n>=6 and null/quality prerequisites still apply separately.
    require(len(values) >= 6, "bootstrap requires at least six observations")
    rng = random.Random(0x4D4B)
    medians = sorted(statistics.median(rng.choices(values, k=len(values))) for _ in range(2000))
    return dict(median=statistics.median(values), low=medians[49], high=medians[1949], n=len(values))


def paired_change(left, right):
    require(len(left) == len(right), "unequal paired sample counts")
    return interval([a / b - 1 for a, b in zip(left, right)])


def median_agreement(a, b):
    # Normal-reference SE of the difference of two independent sample medians,
    # relative to median(B). Pool within-arm sample variances (ddof=1), never
    # between-arm drift. sqrt(1/nA+1/nB) accounts for BOTH estimated medians.
    na, nb = len(a), len(b)
    pooled_sd = math.sqrt(((na - 1) * statistics.variance(a) +
                           (nb - 1) * statistics.variance(b)) / (na + nb - 2))
    scale = MEDIAN_NORMAL_FACTOR * pooled_sd / statistics.median(b)
    se = scale * math.sqrt(1 / na + 1 / nb)
    spread = max(max(v) / min(v) - 1 for v in (a, b))
    # Planning estimate for equal-sized ABBA arms, rounded up to an even n.
    # Raw max/min ranges do NOT contract as 1/sqrt(n); median SE does under the
    # stationary independent-sample model. This estimate cannot waive the band.
    target_n = max(6, 2 * math.ceil((2 * (NULL_K * scale / .03) ** 2) / 2))
    return dict(relative_delta=statistics.median(a) / statistics.median(b) - 1,
                relative_se_median=se, agreement_band=NULL_K * se,
                max_same_arm_spread=spread, measured_null_band=spread,
                pooled_sd=pooled_sd, n_per_arm=dict(A=na, B=nb),
                required_n_per_arm_for_3pct=target_n)


def null_verdict(rows):
    table = []
    for cell in NULL_IDS:
        category = "noisy/multi-key" if cell in MULTI_IDS else "quiet"
        item = dict(cell=cell, status="PASS", stability_class=category,
                    stability_cap=STABILITY_CAPS[category])
        for metric in ("rate", "cyc_per_op"):
            try:
                a = observations(rows, "null", cell, arm="A", metric=metric)
                b = observations(rows, "null", cell, arm="B", metric=metric)
                value = median_agreement(a, b)
                value["status"] = ("UNSTABLE" if value["measured_null_band"] > item["stability_cap"] else
                                   "PASS" if abs(value["relative_delta"]) <= value["agreement_band"] else "FAIL")
            except (RuntimeError, KeyError) as error:
                value = dict(status="UNRESOLVED", reason=str(error))
            item[metric] = value
        item["status"] = next((s for s in ("UNSTABLE", "UNRESOLVED", "FAIL")
                               if any(item[m]["status"] == s for m in ("rate", "cyc_per_op"))), "PASS")
        table.append(item)
    status = next((s for s in ("UNSTABLE", "UNRESOLVED", "FAIL") if any(r["status"] == s for r in table)), "PASS")
    return dict(status=status, rows=table, k=NULL_K,
                estimator="SE = sqrt(pi/2) * pooled within-arm sample sd * sqrt(1/nA + 1/nB) / median(B); ddof=1",
                band_contract="Each cell/metric's max(max(arm)/min(arm)-1) is its measured null resolution; no clipping or fixed floor",
                stability_source="calib/refnull-spread.py; observed maxima table in MEASURE-REQUEST-mkprobe3.md",
                reason=("all 14 cells: rate and cyc/op medians agree within k x SE; no unstable cell" if status == "PASS" else
                        "; ".join(f"{r['cell']} {r['status']}" for r in table if r["status"] != "PASS")))


def calibrated_band(calibration, cell, metric):
    item = next((r for r in calibration["rows"] if r["cell"] == cell), None)
    require(item is not None and metric in item and item[metric]["status"] == "PASS",
            f"no measured same-binary band for {cell}/{metric}")
    return item[metric]["measured_null_band"]


def baseline_band(rows, calibration, cell, metric, mode, arm="base"):
    # Frozen null has fourteen cells and no symbol passes. Do not borrow another
    # cell's noise. For unrepresented controls use only their repeated unchanged
    # baseline (WB1/B for the policy pair), never the intervention arm's spread.
    if any(r["cell"] == cell for r in calibration["rows"]):
        return dict(value=calibrated_band(calibration, cell, metric), source="earlier same-binary null", cell=cell, metric=metric)
    values = observations(rows, mode, cell, arm=arm, metric=metric)
    band = max(values) / min(values) - 1
    category = "noisy/multi-key" if cell.startswith("m") else "quiet"
    require(band <= STABILITY_CAPS[category], f"UNSTABLE baseline: {mode}/{cell}/{arm}/{metric}")
    return dict(value=band, source=f"same-cell repeated baseline: {mode}/{arm}; not in frozen 14-cell null",
                cell=cell, metric=metric, n=len(values))


def effect_verdict(evidence, band, prediction="positive"):
    # Directional claims need a whole interval beyond the measured band. The
    # opposite direction beyond that band refutes; an in-band effect is unresolved.
    # Equivalence is asymmetric: an interval contained in the band confirms the
    # null prediction, an interval outside refutes, and overlap is unresolved.
    if prediction == "null":
        return ("CONFIRMED" if -band <= evidence["low"] <= evidence["high"] <= band else
                "REFUTED" if evidence["low"] > band or evidence["high"] < -band else "UNRESOLVED")
    if prediction == "no_positive_step":
        return ("CONFIRMED" if evidence["high"] <= band else
                "REFUTED" if evidence["low"] > band else "UNRESOLVED")
    return ("CONFIRMED" if evidence["low"] > band else
            "REFUTED" if evidence["high"] < -band else "UNRESOLVED")


def conjunction(states):
    return "REFUTED" if "REFUTED" in states else "UNRESOLVED" if "UNRESOLVED" in states else "CONFIRMED"


def null_table(calibration):
    lines = ["| Cell | Metric | n A/B | A/B delta | SE median | k x SE (k=3) | Same-arm spread / measured band | Sanity cap | Verdict |",
             "|---|---|---|---|---|---|---|---|---|"]
    for cell in calibration["rows"]:
        for metric in ("rate", "cyc_per_op"):
            v = cell[metric]
            if "relative_delta" not in v:
                lines.append(f"| {cell['cell']} | {metric} | — | — | — | — | — | {cell['stability_cap']:.0%} | {v['status']}: {v['reason']} |")
                continue
            n = v["n_per_arm"]
            lines.append(f"| {cell['cell']} | {metric} | {n['A']}/{n['B']} | {v['relative_delta']:+.3%} | "
                         f"{v['relative_se_median']:.3%} | {v['agreement_band']:.3%} | {v['measured_null_band']:.3%} | "
                         f"{cell['stability_cap']:.0%} | {v['status']} |")
    return lines


def resolution_statement(calibration):
    chosen = [r for r in calibration["rows"] if r["cell"] in ("m03", "m51")]
    if len(chosen) != 2 or any("measured_null_band" not in r[m] for r in chosen for m in ("rate", "cyc_per_op")):
        return "Multi-key p32 resolution unavailable: missing m03/m51 null samples."
    spreads = [r["rate"]["measured_null_band"] for r in chosen]
    ns = sorted({v for r in chosen for v in r["rate"]["n_per_arm"].values()})
    sample_text = str(ns[0]) if len(ns) == 1 else "/".join(map(str, ns))
    details = "; ".join(f"{r['cell']}: {r['rate']['measured_null_band']:.2%} rate spread, "
                        f"n={r['rate']['required_n_per_arm_for_3pct']} for rate / "
                        f"{r['cyc_per_op']['required_n_per_arm_for_3pct']} for cycles/op" for r in chosen)
    return (f"The multi-key p32 cells have a same-arm spread of {math.floor(min(spreads) * 100)}-"
            f"{math.ceil(max(spreads) * 100)}% at n={sample_text} on this box (rl0 MGET m03/m51); "
            "any multi-key claim below that needs more samples. " + details + ". "
            "These are equal per-arm n estimates for a 3% median-difference resolution (3 x SE <= 3%), "
            "rounded up for ABBA: n = 2 * ceil(max(6, 2*(3*sqrt(pi/2)*pooled_sd/(median(B)*0.03))^2)/2). "
            "This assumes independent stationary samples, not a power guarantee. Raw max/min spreads do not shrink "
            "as 1/sqrt(n); more samples must re-establish resolution and do not automatically waive the recorded band.")


def verdicts(rows, calibration):
    result = []
    def resolve(mechanism, function):
        if calibration["status"] != "PASS":
            result.append(dict(mechanism=mechanism, verdict="UNRESOLVED", reason="14-cell same-binary null has not passed: " + calibration["reason"]))
            return
        try:
            value = function()
            result.append(dict(mechanism=mechanism, **value))
        except (RuntimeError, KeyError) as error:
            result.append(dict(mechanism=mechanism, verdict="UNRESOLVED", reason=str(error)))

    def m1():
        checks, states = [], []
        for cell in ("m02", "m03", "m05", "m06", "m50", "m51", "m53", "m54", "mk128g", "mk128s"):
            v = interval(observations(rows, "counters", cell, metric="retired_per_send"))
            passed = BATCH_RANGE[0] <= v["low"] <= v["high"] <= BATCH_RANGE[1]
            state = ("CONFIRMED" if passed else "REFUTED" if v["low"] > BATCH_RANGE[1] or v["high"] < BATCH_RANGE[0] else "UNRESOLVED")
            states.append(state)
            checks.append(dict(cell=cell, prediction="0.9 <= retired/sends_submitted <= 1.1", result="PASS" if passed else "FAIL", verdict=state, evidence=v))
        for cell in PAIR_IDS:
            rate = paired_change(observations(rows, "wb-pair", cell, arm="A", metric="rate"),
                                 observations(rows, "wb-pair", cell, arm="B", metric="rate"))
            cycles = paired_change(observations(rows, "wb-pair", cell, arm="A"), observations(rows, "wb-pair", cell, arm="B"))
            multi = cell.startswith("m")
            rate_band = baseline_band(rows, calibration, cell, "rate", "wb-pair", "B")
            cycle_band = baseline_band(rows, calibration, cell, "cyc_per_op", "wb-pair", "B")
            loss = dict(low=-rate["high"], high=-rate["low"])
            state = conjunction([effect_verdict(rate if multi else loss, rate_band["value"], "null" if multi else "positive"),
                                 effect_verdict(cycles, cycle_band["value"], "null" if multi else "positive")])
            states.append(state)
            checks.append(dict(cell=cell, prediction="wb0/wb1 multi-key null" if multi else "wb0 loses rate and costs cycles versus wb1",
                               result="PASS" if state == "CONFIRMED" else "FAIL", verdict=state,
                               rate=rate, cycles=cycles, rate_band=rate_band, cycle_band=cycle_band))
        passed = all(c["result"] == "PASS" for c in checks)
        return dict(verdict=conjunction(states), arithmetic="PASS" if passed else "FAIL", checks=checks,
                    reason="Conjunction of reply batching arithmetic and same-binary policy effects; read-local MGET controls excluded from scatter prediction")

    def m3():
        details, states = [], []
        for cell in SWEEP_IDS:
            for key_count in KEYS:
                observations(rows, "keys", cell, keys=key_count, metric="cycles_per_key")
        def step_evidence(cell, small, large):
            a = observations(rows, "keys", cell, keys=small, metric="cycles_per_key")
            b = observations(rows, "keys", cell, keys=large, metric="cycles_per_key")
            require(len(a) == len(b), "unequal key-sweep sample counts")
            fraction = calibrated_band(calibration, cell, "cyc_per_op")
            # At each k: uncertainty(cycles/op)/k = band * cycles/key.
            # Add absolute endpoint uncertainties before taking a difference;
            # neither a key division nor a depth comparison cancels uncertainty.
            endpoint_bands = [fraction * statistics.median(v) for v in (a, b)]
            return [y - x for x, y in zip(a, b)], dict(
                cell=cell, boundary=f"{small}->{large}",
                cycles_per_key_step=interval([y - x for x, y in zip(a, b)]),
                relative=paired_change(b, a), null_band=fraction,
                endpoint_bands_cycles_per_key=endpoint_bands,
                propagated_band_cycles_per_key=sum(endpoint_bands),
                propagated_relative_band=sum(endpoint_bands) / statistics.median(a))
        for small, large, p8, p32 in ((7, 8, "m02", "m03"), (3, 4, "m05", "m06")):
            jumps, bands = [], []
            for cell in (p8, p32):
                jump, detail = step_evidence(cell, small, large)
                band = detail["propagated_band_cycles_per_key"]
                detail["verdict"] = effect_verdict(detail["cycles_per_key_step"], band)
                states.append(detail["verdict"])
                jumps.append(jump)
                bands.append(band)
                details.append(detail)
            require(len(jumps[0]) == len(jumps[1]), "unequal key-sweep depth sample counts")
            growth = interval([b - a for a, b in zip(*jumps)])
            state = effect_verdict(growth, sum(bands))
            states.append(state)
            details.append(dict(boundary=f"{small}->{large}", p32_minus_p8_step=growth,
                                propagated_band_cycles_per_key=sum(bands), verdict=state))
        # Beyond MGET's spill cliff, more keys must not introduce another positive
        # per-key jump larger than the propagated identical-arm resolution.
        for cell in ("m02", "m03"):
            _, detail = step_evidence(cell, 9, 16)
            detail["verdict"] = effect_verdict(detail["cycles_per_key_step"], detail["propagated_band_cycles_per_key"], "no_positive_step")
            states.append(detail["verdict"])
            details.append(detail)
        return dict(verdict=conjunction(states), checks=details,
                    reason="Predeclared cycles/key cliffs at MGET 7->8 and MSET 3->4, both larger at p32; MGET 9->16 has no further positive jump")

    def m5():
        values, bands = [], []
        for cell in ("m02", "m03", "mk128g"):
            refresh = observations(rows, "symbols", cell, metric="symbols/shares_pct/refresh_snapshot_floor")
            active = observations(rows, "symbols", cell, metric="symbols/shares_pct/active_snapshot_floor")
            # Exclusive symbol buckets do not double count call chains.
            values.append([a + b for a, b in zip(refresh, active)])
            bands.append(baseline_band(rows, calibration, cell, "cyc_per_op", "symbols"))
        evidence = [interval(v) for v in values]
        enough = all(r["symbols"]["samples"] >= 1000 for r in rows if r["status"] == "COMPLETE" and r["mode"] in ("symbols", "probes") and r["cell"] in ("m02", "m03", "mk128g"))
        require(enough, "M5 requires >=1000 cycles samples per symbol pass")
        # No inlining guess: an entirely unobserved function is unavailable, not a
        # proven zero. perf report --inline must actually resolve it in the set.
        require(any(v > 0 for v in values[1]), "p32 floor symbols unobserved; cannot treat missing attribution as 0%")
        # Shares are percent of total cycles: a relative cycles/op null band is
        # 100*band percentage points. Two endpoints contribute to each contrast.
        importance_band = 2 * 100 * bands[1]["value"]
        growth = []
        for i in (0, 1):
            require(len(values[i]) == len(values[i + 1]), "unequal symbol-pass sample counts")
            step = interval([b - a for a, b in zip(values[i], values[i + 1])])
            band = 100 * (bands[i]["value"] + bands[i + 1]["value"])
            growth.append(dict(evidence=step, band_percentage_points=band, verdict=effect_verdict(step, band)))
        if evidence[1]["high"] < importance_band:
            state, reason = "REFUTED", "p32 floor-share upper bound excludes importance above its measured cycles/op resolution; not proof of zero cost"
        elif evidence[1]["low"] > importance_band and all(g["verdict"] == "CONFIRMED" for g in growth):
            state, reason = "CONFIRMED", "floor-sweep share exceeds measured resolution and grows beyond propagated bands p8->p32->p128"
        elif any(g["verdict"] == "REFUTED" for g in growth):
            state, reason = "REFUTED", "depth growth reverses beyond the propagated measured band"
        else:
            state, reason = "UNRESOLVED", "importance or depth growth overlaps the measured resolution band"
        return dict(verdict=state, reason=reason, shares_pct=dict(zip(("p8", "p32", "p128"), evidence)),
                    cycle_bands=bands, importance_band_percentage_points=importance_band, growth=growth)

    def m2():
        evidence = {}
        for name in ("coherence_residual", "demand_fills", "table_walk_requests"):
            evidence[name] = {c: interval(observations(rows, "coherence", c, metric="memory_per_op/" + name)) for c in ("m02", "m03", "mk128g", "h05", "m05", "m06", "mk128s", "h06")}
        for c in ("m02", "m03", "mk128g", "m05", "m06", "mk128s"):
            observations(rows, "symbols", c, metric="symbols/shares_pct/xshard_execute")
        return dict(verdict="UNRESOLVED", reason="Cold-fragment signature measured, but aggregate fills/walks and xshard_execute share cannot isolate 6-10 remote lines per fragment from allocator/floor/gather traffic. No existing fragment-coldness counter or intervention; do not infer causality.", evidence=evidence)

    def m4():
        evidence = {name: {c: interval(observations(rows, "coherence", c, metric="memory_per_op/" + name)) for c in ("m02", "m03", "h05")}
                    for name in ("demand_fills", "store_buffer_stall_cycles", "dtlb_misses", "table_walk_requests")}
        return dict(verdict="UNRESOLVED", reason="Server-core coherence/TLB pass supplies the predicted stall discriminator, but does not localize a stall to the table probe or measure absent prefetch's causal cost. Aggregate dTLB/fill events cannot confirm/refute probe-side attribution; code lane must supply a controlled prefetch intervention or a localized load-latency profile.", evidence=evidence)

    for mechanism, function in (("M1", m1), ("M2", m2), ("M3", m3), ("M4", m4), ("M5", m5)):
        resolve(mechanism, function)
    return result


def campaign_commands(binary, destination):
    root = Path(destination)
    common = ["python3", str(ROOT / "tools/mkprobe_probe.py"), "--binary", str(binary),
              "--cores", "0-31,32-111", "--samples", "6", "--snapshot-cache", str(root / "snapshots")]
    specs = [("null", []), ("probes", []),
             ("counters-atomic0", ["--atomic", "0", "--cells", "m02,m03,mk128g"]),
             ("wb-pair", []), ("keys", [])]
    result = []
    for name, extra in specs:
        mode = "counters" if name == "counters-atomic0" else name
        command = common + ["--mode", mode, "--output", str(root / name)] + extra
        if mode != "null":
            command += ["--null", str(root / "null")]
        result.append(shlex.join(command))
    result.append(shlex.join(["python3", str(ROOT / "tools/mkprobe_probe.py"), "--mode", "report", "--inputs", *[str(root / name) for name, _ in specs],
                             "--output", str(root / "report")]))
    return result


def report(rows, receipts, destination, binary):
    identities = {(r["binary_sha256"], tuple(r["geometry"]),
                   sha(canonical({k: r.get(k) for k in ("memtier", "perf", "environment", "placement")}))) for r in receipts}
    require(len(identities) <= 1, "report mixes binary, geometry or instrument identities")
    require(all(compatible_instruments(receipts[0], r) for r in receipts), "report mixes collection instruments")
    calibration = null_verdict(rows)
    # Null must have completed before every non-smoke measured row began.
    null_rows = [r for r in rows if r["mode"] == "null" and r["status"] == "COMPLETE"]
    measured = [r for r in rows if r["mode"] not in ("null", "smoke") and r["status"] == "COMPLETE"]
    if calibration["status"] == "PASS" and measured and max(r["finished"] for r in null_rows) > min(r["started"] for r in measured):
        calibration = dict(calibration, status="FAIL", reason="null did not finish FIRST")
    answers = verdicts(rows, calibration)
    commands = campaign_commands(binary, ROOT / "build/mkprobe-mainline")
    result = dict(schema=SCHEMA, null=calibration, verdicts=answers, sample_rows=len(rows), mainline_commands=commands,
                  status_counts=dict(Counter(r["status"] for r in rows)), performance_claim=False,
                  resolution_statement=resolution_statement(calibration),
                  verdict_contract=("Directional effects confirm only when the whole bootstrap interval exceeds the measured band; "
                      "an opposite effect beyond the band refutes; effects inside/overlapping the band are UNRESOLVED. "
                      "Equivalence is asymmetric: an interval contained within the band confirms a null prediction, "
                      "an interval entirely outside refutes, and boundary overlap is UNRESOLVED. "
                      "M3 adds endpoint uncertainties after dividing cycles/op by key count and adds both depths' step bands. "
                      "M5 importance is a separate minimum-effect prediction: its p32 share interval must exceed twice "
                      "the measured cycles/op band (in percentage points); a whole interval below that threshold refutes "
                      "resolvable importance, not nonzero cost; overlap is UNRESOLVED. Depth growth uses directional bands. "
                      "Unrepresented p8/p128 controls use their own repeated unchanged baseline's spread, "
                      "with source and n recorded; no cell borrows another cell's band. "
                      "The retired/send [0.9,1.1] prediction describes batching semantics, not instrument resolution."),
                  age_delay_contract=("Age/delay columns are diagnostic; M1-M5 do not use them. "
                      f"2s INFO flip_auto=0 prints '{FLIPCTL_DISARMED}' and does not invalidate the sample. "
                      "Only INFO flip_auto=1 requires executor sample counts to advance inside the central interval "
                      "and measured values to be positive. Missing, invalid or changing flip_auto fails the sample."))
    save(destination / "report.json", result)
    lines = ["# mkprobe diagnostic report", "", "No performance claim. Verdicts describe the predeclared mechanism signatures only.", "",
             f"Same-binary null: **{calibration['status']}** — {calibration['reason']}", "",
             f"Declared estimator (k={calibration['k']}): {calibration['estimator']}. " + calibration["band_contract"] + ".",
             "", "Sanity caps only: quiet 6%, noisy/multi-key 20%; exceeded caps mark UNSTABLE, never enlarge or clip a band. "
             + calibration["stability_source"] + ".", "", *null_table(calibration),
             "", result["resolution_statement"], "", result["verdict_contract"], "",
             "| Mechanism | Verdict | Arithmetic | Reason |", "|---|---|---|---|"]
    for answer in answers:
        lines.append(f"| {answer['mechanism']} | {answer['verdict']} | {answer.get('arithmetic', NA)} | {answer['reason']} |")
    m1 = next(a for a in answers if a["mechanism"] == "M1")
    if m1.get("checks"):
        lines += ["", "| M1 cell | Prediction | Arithmetic | Observation |", "|---|---|---|---|"]
        for check in m1["checks"]:
            observed = check.get("evidence", {k: check[k] for k in ("rate", "cycles", "rate_band", "cycle_band") if k in check})
            lines.append(f"| {check['cell']} | {check['prediction']} | {check['result']} / {check['verdict']} | `{json.dumps(observed, sort_keys=True)}` |")
    m3 = next(a for a in answers if a["mechanism"] == "M3")
    if m3.get("checks"):
        lines += ["", "| M3 cell / contrast | Keys | Step interval (cycles/key) | Propagated band (cycles/key) | Verdict |",
                  "|---|---|---|---|---|"]
        for check in m3["checks"]:
            v = check.get("cycles_per_key_step", check.get("p32_minus_p8_step"))
            lines.append(f"| {check.get('cell', 'p32 minus p8')} | {check['boundary']} | {v['low']:.6g} to {v['high']:.6g} | "
                         f"{check['propagated_band_cycles_per_key']:.6g} | {check['verdict']} |")
    m5 = next(a for a in answers if a["mechanism"] == "M5")
    if "cycle_bands" in m5:
        lines += ["", f"M5 p32 importance threshold: {m5['importance_band_percentage_points']:.6g} percentage points.",
                  "", "| M5 depth | Share interval (%) | Measured cycles/op band | Source |", "|---|---|---|---|"]
        for (depth, v), band in zip(m5["shares_pct"].items(), m5["cycle_bands"]):
            lines.append(f"| {depth} | {v['low']:.6g} to {v['high']:.6g} | {band['value']:.3%} | {band['source']} |")
        for contrast, growth in zip(("p8->p32", "p32->p128"), m5["growth"]):
            v = growth["evidence"]
            lines += ["", f"M5 {contrast}: interval {v['low']:.6g} to {v['high']:.6g} percentage points; "
                      f"propagated band {growth['band_percentage_points']:.6g}; {growth['verdict']}."]
    lines += ["", "Rows retain individual observations and arithmetic in report.json and rows.jsonl. n>=6 is required for every contributing cell/variant.",
              "", "The 1s age/delay columns are **not available**: flipctl sampling is Split-only. Split telemetry retains lb_ex_* and lb_io_* names; lb_fused_* is not synthesized for 2s.",
              "", result["age_delay_contract"],
              "", "Perf core events are the abba_profile EVENTS group (cycles, instructions, ref-cycles), measured on server CPUs only. IPC=instructions/cycles; cyc/op=cycles/central calls; instr/op=instructions/central calls. Windows encompass INFO endpoints and are approximate. The memory pass and symbol pass each use a separate boot and denominator.",
              "", "WB ratios cover the whole restored boot, including warmup/tail and the recorded small observer bound. They exclude population. INFO held cuts is a sampled maximum gauge; fanout cuts is a central delta and can be zero at atomic=1.",
              "", "Memory events: any fills minus demand fills is the requested coherence residual, not a unique RFO count. The store event counts dispatch cycles blocked on store-queue tokens. L2 dTLB misses count table-walk requests, not walker duration. PMU availability/multiplexing failures invalidate the sample.",
              "", "Symbol shares are exclusive, cycle-period weighted, with inline attribution enabled. An unobserved function is not a proven zero. M2/M4 cannot receive causal confirmation from these aggregate counters alone.",
              "", "## Ordered mainline campaign", "", "Run serially on the idle box. Fresh directories; --resume only with the identical receipt.", "", "```sh", *commands, "```", ""]
    (destination / "report.md").write_text("\n".join(lines))
    return result


def collection_source(source):
    # Preserve every collection node, constant, import and entry point. Exclude
    # analysis/report code only. The one run() assertion that compares instrument
    # identities is normalized explicitly; acquisition itself must match exactly.
    import ast
    analysis_names = set("BOX_BAND REPEAT_BAND NULL_K MEDIAN_NORMAL_FACTOR STABILITY_CAPS "
                         "median_agreement null_verdict calibrated_band baseline_band effect_verdict conjunction "
                         "null_table resolution_statement verdicts report self_test collection_source compatible_instruments".split())
    tree = ast.parse(source)
    tree.body = [n for n in tree.body if not (
        isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in analysis_names or
        isinstance(n, ast.Assign) and all(isinstance(t, ast.Name) and t.id in analysis_names for t in n.targets))]
    class IdentityAssertion(ast.NodeTransformer):
        def visit_Call(self, node):
            if (isinstance(node.func, ast.Name) and node.func.id == "require" and len(node.args) == 2
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value == "null identity/geometry/instrument/PMU/environment does not match"):
                node.args[0] = ast.Constant(value="analysis-only compatibility assertion")
            return self.generic_visit(node)
    return sha(ast.dump(IdentityAssertion().visit(tree), include_attributes=False).encode())


def compatible_instruments(left, right):
    for receipt in (left, right):
        require(sha(canonical(receipt["sources"])) == receipt["instrument_sha256"], "unbound instrument source hashes")
    if left["sources"] == right["sources"]:
        return True
    tool = "tools/mkprobe_probe.py"
    if {k:v for k,v in left["sources"].items() if k != tool} != {k:v for k,v in right["sources"].items() if k != tool}:
        return False
    # Existing mkprobe2 nulls keep their ORIGINAL full source/receipt digests.
    # Prove compatibility against the actual landed source, not an unchecked
    # allowlist of instrument hashes. Unknown revisions are refused.
    current = Path(__file__).read_bytes()
    legacy = subprocess.check_output(["git", "show", "2c78708f8:tools/mkprobe_probe.py"], cwd=ROOT)
    sources = {sha(s): s for s in (current, legacy)}
    a, b = (sources.get(r["sources"].get(tool)) for r in (left, right))
    return a is not None and b is not None and collection_source(a) == collection_source(b)


def instrument_identity():
    paths = [Path(__file__).resolve(), CELLS, *[ROOT / "tests" / n for n in
             ("abba_workloads.py", "abba_profile.py", "abbagate.py", "abba_saturation.py", "gate_quiet.py", "gateplan.py", "gate_measurements.py", "_lib.py")],
             ROOT / "tools/exbatch_directed.py"]
    return {str(p.relative_to(ROOT)): digest(p) for p in paths}


def perf_identity():
    executable = Path(shutil.which("perf") or "").resolve()
    require(executable.is_file(), "perf executable missing")
    version = subprocess.check_output([str(executable), "--version"], text=True).strip()
    available = subprocess.check_output([str(executable), "list", "--raw-dump"], text=True).split()
    require(all(e in available for e in MEMORY_EVENTS), "host does not expose the required Bergamo memory events")
    descriptions = subprocess.check_output([str(executable), "list", *MEMORY_EVENTS], text=True)
    cpu = Path("/proc/cpuinfo").read_text().split("\n\n", 1)[0]
    model = {k.strip(): v.strip() for line in cpu.splitlines() if ":" in line for k,v in [line.split(":",1)]
             if k.strip() in ("vendor_id", "cpu family", "model", "model name", "stepping", "microcode")}
    return dict(path=str(executable), sha256=digest(executable), version=version, memory_event_descriptions=descriptions,
                core_events=[list(e) for e in EVENTS], memory_events=list(MEMORY_EVENTS), cpu=model, kernel=os.uname().release,
                boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip())


def dry_run(args, chosen):
    proof = argv_proof(args)
    identity = grammar(args)
    plan = jobs(args, chosen)
    print("# memtier grammar PASS " + json.dumps(identity, sort_keys=True))
    print("# unset TOMO_MULTI_KEYS byte-identity PASS " + json.dumps(proof, sort_keys=True))
    print(f"# {len(plan)} result rows; fresh restored boot for each instrument pass; 20s quiet preflight per sample")
    seen = set()
    for job in plan:
        signature = (job["cell"], job["keys"], job["wb_policy"])
        if signature in seen:
            continue
        seen.add(signature)
        cell = next(c for c in chosen if c.id == job["cell"])
        folder = args.output / job["id"]
        print(f"# {job['cell']} keys={job['keys']} wb={job['wb_policy']} samples_per_arm={args.samples}; TOMO_MULTI_KEYS={job['keys']}")
        print(shlex.join(server_command(args, cell, folder, job["wb_policy"])))
        for command in load_commands(args, cell, folder, job["keys"])[1]:
            print(shlex.join(command))
        for kind in (["core", "memory", "symbols"] if args.mode == "probes" else
                     ["core", "memory"] if args.mode == "coherence" else ["core", "symbols"] if args.mode == "symbols" else ["core"]):
            print(shlex.join(perf_command(args, folder / kind, kind)))
    print("# row grammar: MKPROBE_ROW <one JSON object: schema, cell, sample, arm, recipe, keys, status, rate, instr_per_op, ipc, cyc_per_op, cycles_per_key, retired_per_send, empty_serve_fraction, atomic_*, cmdstat_*, lb_*, passes, quiet, children>")
    return proof


def self_test(args):
    from unittest import mock
    import tempfile
    checks = []
    def passed(name):
        checks.append(name)
    def rejects(function):
        try:
            function()
        except (RuntimeError, ValueError, KeyError):
            return
        raise AssertionError("negative control was accepted")
    inventory = cells()
    require(len(inventory) == 19 and len(NULL_IDS) == 14, "inventory cardinality")
    passed("canonical recipes and 14-cell null")
    argv_proof(args)
    passed("all headline/mkprobe complete argv byte-identity plus 14 override round trips")
    rejects(lambda: workload_args(inventory["m02"], 0))
    rejects(lambda: workload_args(inventory["m02"], -1))
    passed("invalid key counts fail")
    text = "\n".join(f"CPU112,1000,,{event}:D,1000000000,100.00," for event in CORE_EVENTS)
    require(parse_perf(text, [112], CORE_EVENTS)["totals"]["cycles"] == 1000, "counter parser")
    for broken in (text.replace("100.00", "99.99", 1), text.replace("1000", "<not counted>", 1), text.splitlines()[0], text + "\n" + text.splitlines()[0]):
        rejects(lambda: parse_perf(broken, [112], CORE_EVENTS))
    rejects(lambda: parse_perf(text, [112, 113], CORE_EVENTS))
    passed("PMU partial, multiplexed, missing, duplicate and unavailable negative controls")
    metrics = core_metrics(dict(zip(CORE_EVENTS, (100000, 80000, 50000))), 100, 8, 1, 8)
    require(metrics["cyc_per_op"] == 1000 and metrics["instr_per_op"] == 800 and metrics["ipc"] == .8
            and metrics["cycles_per_key"] == 125, "command/key denominator or IPC arithmetic differs")
    rejects(lambda: core_metrics(dict(zip(CORE_EVENTS, (100000, 80000, 50000))), 0, 8, 1, 8))
    passed("cycles/op, instructions/op, IPC and cycles/key independent arithmetic")
    wb = dict(retired=1000, sends_submitted=1000, serves=1100, serves_empty=100,
              sends_completed=1000, send_errors=0, peer_aborts=0, short_writes=0)
    wire = "shutdown_report " + json.dumps(dict(schema=1, wb=wb))
    parse_shutdown(wire)
    rejects(lambda: parse_shutdown(wire + "\n" + wire))
    rejects(lambda: parse_shutdown("shutdown_report " + json.dumps(dict(schema=1, wb={**wb, "serves_empty":1101}))))
    passed("shutdown accounting and duplicate report negatives")
    base = dict(atomic_fanout_cuts="0", atomic_read_cuts_held="0", cmdstat_mget="calls=10,usec=0", flip_auto="1")
    for role in ("fused", "io", "ex"):
        base.update({f"lb_{role}_{s}": "1" for s in (*SIGNAL_SUFFIXES, "queue_delay_samples", "oldest_age_samples")})
    result = telemetry(inventory["m02"], [base, base], base, base)
    require(result["lb_fused_queue_delay_ewma_us"] == NA, "1s silent zero")
    advancing = {**base, "lb_ex_queue_delay_samples": "2", "lb_ex_oldest_age_samples": "2"}
    result = telemetry(inventory["m50"], [base, advancing], base, advancing)
    require(result["flip_auto"] == 1 and result["lb_ex_queue_delay_samples"] == 1
            and result["lb_ex_oldest_age_samples"] == 1, "armed sampler lost central deltas")
    rejects(lambda: telemetry(inventory["m50"], [base, base], base, base))
    for suffix in ("queue_delay_samples", "oldest_age_samples"):
        key = "lb_ex_" + suffix
        for value in ("0", "1"):
            before, after = {**base, key: value}, {**advancing, key: value}
            rejects(lambda: telemetry(inventory["m50"], [before, after], before, after))
    for suffix in SIGNAL_SUFFIXES[2:]:
        key = "lb_ex_" + suffix
        before, after = {**base, key: "0"}, {**advancing, key: "0"}
        rejects(lambda: telemetry(inventory["m50"], [before, after], before, after))
    passed("armed INFO flip_auto=1: advancing positive samples pass; zero/stale counts and zero values fail")
    disarmed = {**base, "flip_auto": "0"}
    diagnostic_keys = [f"lb_{role}_{s}" for role in ("io", "ex") for s in SIGNAL_SUFFIXES[2:]]
    diagnostic_keys += ["lb_ex_queue_delay_samples", "lb_ex_oldest_age_samples"]
    disarmed.update({key: "0" for key in diagnostic_keys})
    for disabled in (disarmed, {**base, "flip_auto": "0"}):
        result = telemetry(inventory["m50"], [disabled, disabled], disabled, disabled)
        require(result["flip_auto"] == 0 and all(result[key] == FLIPCTL_DISARMED for key in diagnostic_keys),
                "disarmed age/delay must be NA with reason, including stale warmup values")
        require(result["lb_ex_masked_lane_high_water"] == 1 and result["lb_fused_queue_delay_ewma_us"] == NA,
                "disarmed controller changed non-age telemetry or native role names")
    for flag in (None, "", "-1", "2", "unavailable"):
        bad = {**base, "flip_auto": flag}
        rejects(lambda: telemetry(inventory["m50"], [bad, bad], bad, bad))
    rejects(lambda: telemetry(inventory["m50"], [disarmed, base, disarmed], disarmed, disarmed))
    passed("disarmed INFO flip_auto=0: NA with reason; missing/invalid/changing state fails")
    bad = {k:v for k,v in base.items() if k != "atomic_fanout_cuts"}
    rejects(lambda: telemetry(inventory["m02"], [bad, bad], bad, bad))
    passed("1s unavailable and missing-counter negatives")
    symbols = "# Total Lost Samples: 0\n# Samples: 1200 of event 'cycles'\n 50.00%;500;[.] tomo::ScatterArenaPool::refresh_snapshot_floor();\n 50.00%;500;[.] je_malloc;\n"
    require(symbol_shares(symbols)["shares_pct"]["allocator"] == 50, "symbol attribution")
    rejects(lambda: symbol_shares(symbols.replace("Samples: 0", "Samples: 1")))
    passed("weighted symbol shares and lost-sample negative")
    for mode, count in (("null", 168), ("wb-pair", 96), ("keys", 168), ("counters", 114), ("coherence", 114), ("symbols", 114), ("probes", 114), ("smoke", 2)):
        local = argparse.Namespace(**vars(args))
        local.mode, local.cells, local.samples = mode, "", 6
        plan = jobs(local, selected(local, inventory))
        require(len(plan) == count and len({j["id"] for j in plan}) == count, "plan/ABBA sample identities")
    passed("all eight collection-mode matrices and ABBA per-arm n=6")
    unresolved = verdicts([], null_verdict([]))
    require(all(r["verdict"] == "UNRESOLVED" for r in unresolved), "empty data produced verdict")
    synthetic = []
    variation = [1 + i / 1000 for i in (-2, -1, 0, 0, 1, 2)]
    for cell in NULL_IDS:
        for arm in ("A", "B"):
            for sample, scale in enumerate(variation):
                synthetic.append(dict(status="COMPLETE", mode="null", cell=cell, keys=8, arm=arm, sample=sample,
                                      recipe=dict(atomic=1), saturation_pct=99, rate=1e6 * scale, cyc_per_op=1000 * scale))
    passed_null = null_verdict(synthetic)
    require(passed_null["status"] == "PASS", "identical-median null with nonzero spread failed")
    measured = passed_null["rows"][0]["rate"]
    require(math.isclose(measured["measured_null_band"], max(variation) / min(variation) - 1), "band did not come from samples")
    # At exactly k*SE the declared <= rule passes; just beyond it must fail.
    shift = (NULL_K + .01) * measured["relative_se_median"] * 1e6
    shifted = [dict(r, rate=r["rate"] + (shift if r["arm"] == "A" else 0)) for r in synthetic]
    require(null_verdict(shifted)["status"] == "FAIL", "shift beyond 3 x SE passed")
    boundary = dict(measured, relative_delta=measured["agreement_band"])
    with mock.patch(__name__ + ".median_agreement", return_value=boundary):
        require(null_verdict(synthetic)["status"] == "PASS", "exact k x SE boundary must be inclusive")
    shifted_cycles = [dict(r, cyc_per_op=r["cyc_per_op"] + (shift / 1000 if r["arm"] == "A" else 0)) for r in synthetic]
    require(null_verdict(shifted_cycles)["status"] == "FAIL", "cycles-only disagreement passed")
    unstable = [dict(r, rate=1e6 * (1.3 if r["sample"] == 5 else 1)) if r["cell"] == "m03" else r for r in synthetic]
    unstable_null = null_verdict(unstable)
    require(unstable_null["status"] == "UNSTABLE" and len(unstable_null["rows"]) == 14
            and next(r for r in unstable_null["rows"] if r["cell"] == "m03")["status"] == "UNSTABLE",
            "unstable cell lost its distinct status/table")
    quiet_unstable = [dict(r, rate=1e6 * (1.07 if r["sample"] == 5 else 1)) if r["cell"] == "h05" else r for r in synthetic]
    require(null_verdict(quiet_unstable)["status"] == "UNSTABLE", "quiet sanity cap ignored")
    require(null_verdict(synthetic[:-1])["status"] == "UNRESOLVED", "n=5 null passed")
    require(all(r["verdict"] == "UNRESOLVED" for r in verdicts([], unstable_null)), "unstable null enabled a verdict")
    require(math.isclose(measured["relative_se_median"], MEDIAN_NORMAL_FACTOR * statistics.stdev(variation) * math.sqrt(2 / 6)),
            "SE does not include both arms at their n")
    scaled = median_agreement([v * 17 for v in variation], [v * 17 for v in variation])
    require(math.isclose(scaled["relative_se_median"], measured["relative_se_median"]), "relative SE depends on units")
    require(median_agreement([1.] * 6, [1.] * 6)["measured_null_band"] == 0, "zero spread gained a literal floor")
    passed("measured null: identical medians with known spread PASS; >3 x SE rate/cycle shifts FAIL; quiet/multi-key UNSTABLE; n=5/empty UNRESOLVED")
    def fixture(mode, cell, *, keys=8, arm="base", **metrics):
        return [dict(status="COMPLETE", mode=mode, cell=cell, keys=keys, arm=arm, sample=i,
                     recipe=dict(atomic=1), saturation_pct=99,
                     **{k: v * variation[i] if isinstance(v, (int, float)) else v for k,v in metrics.items()}) for i in range(6)]
    evidence = []
    for cell in ("m02", "m03", "m05", "m06", "m50", "m51", "m53", "m54", "mk128g", "mk128s"):
        evidence += fixture("counters", cell, retired_per_send=1.)
    for cell in PAIR_IDS:
        evidence += fixture("wb-pair", cell, arm="B", rate=1e6, cyc_per_op=1000.)
        evidence += fixture("wb-pair", cell, arm="A", rate=1e6 if cell.startswith("m") else 9e5,
                            cyc_per_op=1000. if cell.startswith("m") else 1100.)
    for cell in SWEEP_IDS:
        for key_count in KEYS:
            spill = key_count >= (8 if cell in ("m02", "m03") else 4)
            evidence += fixture("keys", cell, keys=key_count,
                                cycles_per_key=1000. + (200. if cell in ("m03", "m06") else 100.) * spill)
    for cell, share in (("m02", 1.), ("m03", 2.), ("mk128g", 3.)):
        evidence += fixture("symbols", cell, cyc_per_op=1000., symbols=dict(samples=2000, shares_pct=dict(refresh_snapshot_floor=share, active_snapshot_floor=0.)))
    answers = {r["mechanism"]:r for r in verdicts(evidence, passed_null)}
    require(all(answers[m]["verdict"] == "CONFIRMED" for m in ("M1", "M3", "M5")), "positive mechanism fixtures did not confirm")
    require(math.isclose(next(c for c in answers["M1"]["checks"] if c["cell"] == "m02" and "rate_band" in c)["rate_band"]["value"],
                         measured["measured_null_band"]), "M1 ignored fixture's measured band")
    first_step = answers["M3"]["checks"][0]
    require(math.isclose(first_step["propagated_band_cycles_per_key"], calibrated_band(passed_null, "m02", "cyc_per_op") * (1000 + 1100)),
            "M3 failed to propagate cycles/op band through per-key division")
    require(math.isclose(answers["M5"]["importance_band_percentage_points"], 200 * calibrated_band(passed_null, "m03", "cyc_per_op")),
            "M5 used a fixed importance band")
    # Alter only calibration spread, retaining identical medians and effect data.
    # A hard-coded judge would keep confirming both of these marginal effects.
    wide = [dict(r, rate=1e6 * (1 + (variation[r["sample"]] - 1) * 10),
                 cyc_per_op=1000 * (1 + (variation[r["sample"]] - 1) * 10)) for r in synthetic]
    wider_null = null_verdict(wide)
    require(wider_null["status"] == "PASS", "wider known-spread null failed")
    marginal = [dict(r, rate=.98e6 * variation[r["sample"]], cyc_per_op=1020. * variation[r["sample"]])
                if r["mode"] == "wb-pair" and r["arm"] == "A" and not r["cell"].startswith("m") else r for r in evidence]
    require(verdicts(marginal, passed_null)[0]["verdict"] == "CONFIRMED"
            and verdicts(marginal, wider_null)[0]["verdict"] == "UNRESOLVED", "M1 ignored increased measured spread")
    require(verdicts(evidence, wider_null)[2]["verdict"] == "UNRESOLVED", "M3 ignored increased measured spread")
    require(verdicts(evidence, wider_null)[4]["verdict"] == "REFUTED", "M5 ignored increased measured resolution threshold")
    combined = {}
    for row in evidence:
        key = ("probes" if row["mode"] in ("counters", "symbols") else row["mode"], row["cell"], row["sample"], row["keys"], row["arm"])
        combined[key] = {**combined.get(key, {}), **row, "mode": key[0]}
    require(all(r["verdict"] == "CONFIRMED" for r in verdicts(list(combined.values()), passed_null) if r["mechanism"] in ("M1", "M3", "M5")),
            "combined three-pass rows changed mechanism verdicts")
    broken = [dict(r, retired_per_send=2.) if r["mode"] == "counters" and r["cell"] == "m03" else r for r in evidence]
    answer = verdicts(broken, passed_null)[0]
    require(answer["verdict"] == "REFUTED" and answer["arithmetic"] == "FAIL", "broken M1 batching passed")
    flat = [dict(r, cycles_per_key=1000.) if r["mode"] == "keys" else r for r in evidence]
    require(verdicts(flat, passed_null)[2]["verdict"] == "UNRESOLVED", "in-band flat cliff became a directional conclusion")
    broken = [dict(r, cycles_per_key=2000. - r["cycles_per_key"]) if r["mode"] == "keys" else r for r in evidence]
    require(verdicts(broken, passed_null)[2]["verdict"] == "REFUTED", "reversed spill cliff passed M3")
    small = [dict(r, rate=1e6 * variation[r["sample"]], cyc_per_op=1000. * variation[r["sample"]])
             if r["mode"] == "wb-pair" and not r["cell"].startswith("m") else r for r in evidence]
    require(verdicts(small, passed_null)[0]["verdict"] == "UNRESOLVED", "in-band GET/SET effect became a conclusion")
    reversed_pair = [dict(r, rate=1.1e6 * variation[r["sample"]], cyc_per_op=900. * variation[r["sample"]])
                     if r["mode"] == "wb-pair" and r["arm"] == "A" and r["cell"] == "p8g" else r for r in evidence]
    require(verdicts(reversed_pair, passed_null)[0]["verdict"] == "REFUTED", "reversed GET policy effect passed M1")
    incomplete = [r for r in evidence if not (r["mode"] == "keys" and r["cell"] == "m02" and r["keys"] == 2 and r["sample"] == 5)]
    require(verdicts(incomplete, passed_null)[2]["verdict"] == "UNRESOLVED", "n=5 key variant passed M3")
    unequal = evidence + [dict(r, sample=6) for r in evidence if r["mode"] == "keys" and r["cell"] == "m02" and r["sample"] == 0]
    require(verdicts(unequal, passed_null)[2]["verdict"] == "UNRESOLVED", "unequal depths silently discarded samples")
    broken = [dict(r, symbols=dict(samples=2000, shares_pct=dict(refresh_snapshot_floor=.1, active_snapshot_floor=0.)))
              if r["mode"] == "symbols" else r for r in evidence]
    require(verdicts(broken, passed_null)[4]["verdict"] == "REFUTED", "floor share below measured importance passed M5")
    broken = [dict(r, symbols=dict(samples=2000, shares_pct=dict(refresh_snapshot_floor=0., active_snapshot_floor=0.)))
              if r["mode"] == "symbols" else r for r in evidence]
    require(verdicts(broken, passed_null)[4]["verdict"] == "UNRESOLVED", "missing symbol attribution became zero-cost evidence")
    threshold = answers["M5"]["importance_band_percentage_points"]
    overlap = [dict(r, symbols=dict(samples=2000, shares_pct=dict(refresh_snapshot_floor=threshold, active_snapshot_floor=0.)))
               if r["mode"] == "symbols" and r["cell"] == "m03" else r for r in evidence]
    require(verdicts(overlap, passed_null)[4]["verdict"] == "UNRESOLVED", "M5 importance boundary overlap produced a conclusion")
    passed("M1/M3/M5 CONFIRMED/REFUTED from fixture-owned spread; flat directional effects UNRESOLVED; key-division propagation; missing variants/attribution")
    current_source = Path(__file__).read_bytes()
    old_source = subprocess.check_output(["git", "show", "2c78708f8:tools/mkprobe_probe.py"], cwd=ROOT)
    require(collection_source(old_source) == collection_source(current_source), "analysis update changed collection code")
    require(collection_source(current_source.replace(b"WARMUP, WINDOW, TAIL = 3, 20, 5", b"WARMUP, WINDOW, TAIL = 4, 20, 5"))
            != collection_source(old_source), "collection compatibility ignored window mutation")
    source_map = instrument_identity()
    old_map = dict(source_map, **{"tools/mkprobe_probe.py": sha(old_source)})
    current_receipt = dict(sources=source_map, instrument_sha256=sha(canonical(source_map)))
    old_receipt = dict(sources=old_map, instrument_sha256=sha(canonical(old_map)))
    require(compatible_instruments(old_receipt, current_receipt), "mkprobe2 source-bound null reuse rejected")
    changed_map = dict(old_map, **{"tests/abba_workloads.py": "changed"})
    require(not compatible_instruments(dict(sources=changed_map, instrument_sha256=sha(canonical(changed_map))), current_receipt),
            "changed workload passed compatibility")
    rejects(lambda: compatible_instruments(dict(old_receipt, instrument_sha256="unbound"), current_receipt))
    passed("mkprobe2 null reuse proves identical collection AST; changed windows/workloads and unbound digests rejected")
    with tempfile.TemporaryDirectory(dir=ROOT / "build") as temp:
        folder = Path(temp)
        receipt = dict(geometry=list(args.cores), arguments=dict(cores=args.cores), events=EVENTS)
        save(folder / "receipt.json", receipt)
        require(json.loads(canonical(receipt)) == json.loads((folder / "receipt.json").read_text()), "resume tuple/list normalization failed")
        saved = (folder / "receipt.json").read_bytes()
        changed = json.loads(saved)
        changed["geometry"] = ["0-31", "32-111"]
        require(changed != json.loads(canonical(receipt)), "changed geometry accepted as identical receipt")
        passed("resume serialization identity and changed-geometry negative control")
        mechanism_report = folder / "mechanisms"
        mechanism_report.mkdir()
        report([dict(r, started=0., finished=1.) for r in synthetic] +
               [dict(r, started=2., finished=3.) for r in evidence], [], mechanism_report, args.binary)
        rendered = (mechanism_report / "report.md").read_text()
        require(all(text in rendered for text in ("SE median", "Propagated band", "importance threshold", "same-cell repeated baseline")),
                "Markdown omitted measured bands or their provenance")
        passed("Markdown/JSON report includes per-metric null table, M1/M3/M5 bands and baseline provenance")
        children = Children()
        try:
            process = children.start(["taskset", "-c", "112", sys.executable, "-c", "import time; time.sleep(30)"], folder / "child.log", folder)
        finally:
            children.close()
        require(process.poll() is not None, "owned child not reaped")
        passed("owned child process-group stop and reap (CPU112, no listener)")
        # A quiet refusal must still create a durable failed row and no server.
        fake = argparse.Namespace(**vars(args))
        fake.mode = "smoke"
        with mock.patch(__name__ + ".QuietMonitor.start", side_effect=QuietViolation("fixture contention")):
            row = run_sample(fake, inventory["m02"], dict(id="fixture", cell="m02", sample=0, keys=8, arm="base", wb_policy=1), folder / "failed", {"binary_sha256":"fixture"})
        require(row["status"] == "FAILED" and row["quiet_refusal"] and not row["children"] and (folder / "failed/row.json").exists(), "failed sample was lost")
        passed("quiet refusal retained without starting a server")
        # Exercise the real row-completion and report paths, replacing only the
        # external collection. The disarmed fixture must not become a failed row.
        monitor = mock.Mock(cpu_budget_seconds=.48)
        monitor.close.return_value = dict(complete=True)
        def fixture_pass(*unused):
            return dict(metrics, kind="core", rate=100., retired_per_send=1., empty_serve_fraction=0.,
                        shutdown=dict(wb=wb), commands=100, seconds=1., saturation=dict(score_pct=99),
                        telemetry=telemetry(inventory["m50"], [disarmed, disarmed], disarmed, disarmed))
        with mock.patch.multiple(__name__, quiet_file_guard=mock.Mock(), box_inventory=mock.Mock(return_value=[]),
                                 QuietMonitor=mock.Mock(return_value=monitor), snapshot_fixture=mock.Mock(return_value={}),
                                 run_pass=mock.Mock(side_effect=fixture_pass)):
            row = run_sample(fake, inventory["m50"], dict(id="fixture", cell="m50", sample=0, keys=8, arm="base", wb_policy=1),
                             folder / "disarmed", {"binary_sha256": "fixture"})
        require(row["status"] == "COMPLETE" and all(row[key] == FLIPCTL_DISARMED for key in diagnostic_keys),
                "disarmed sample did not complete with explained NA: " + str(row.get("error")))
        require(json.loads((folder / "disarmed/row.json").read_text()) == json.loads(canonical(row)), "disarmed row not retained")
        destination = folder / "report"
        destination.mkdir()
        report([row], [], destination, args.binary)
        require(FLIPCTL_DISARMED in (destination / "report.md").read_text()
                and FLIPCTL_DISARMED in json.loads((destination / "report.json").read_text())["age_delay_contract"],
                "report lost disarmed diagnostic reason")
        passed("disarmed 2s fixture: COMPLETE row and Markdown/JSON reports retain NA reason (no server)")
    print(json.dumps(dict(status="PASS", checks=checks, server_started=False), indent=2))
    return checks


def arguments(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("null", "probes", "counters", "coherence", "wb-pair", "keys", "symbols", "smoke", "report"), default="counters")
    p.add_argument("--binary", type=Path, default=ROOT / "build/tomokv")
    p.add_argument("--memtier", default="/usr/bin/memtier_benchmark")
    p.add_argument("--cores", type=cores_arg, default=("112-119", "120-127"))
    p.add_argument("--ratio", help="explicit split io:ex; otherwise gate_measurements.json's ABBA ratio")
    p.add_argument("--instances", type=int, default=8, help="loader count only for unpinned cells")
    p.add_argument("--port", type=int, default=18189)
    p.add_argument("--samples", type=int, default=6, help="samples per cell/key-count/arm; null/pair use ABBA")
    p.add_argument("--window", type=int, default=WINDOW)
    p.add_argument("--cells", default="", help="comma-separated canonical cell IDs")
    p.add_argument("--atomic", type=int, choices=(0, 1), help="explicit diagnostic override, retained in each recipe")
    p.add_argument("--output", type=Path, default=ROOT / "build/mkprobe-run")
    p.add_argument("--snapshot-cache", type=Path)
    p.add_argument("--null", type=Path, help="completed earlier 14-cell same-binary null output")
    p.add_argument("--inputs", nargs="*", type=Path, default=[])
    p.add_argument("--resume", action="store_true")
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--quiet-retries", type=int, default=3, help="smoke only, retain all refused attempts")
    p.add_argument("--retry-seconds", type=int, default=300, help="smoke retries at 0,5,10 minutes")
    args = p.parse_args(argv)
    require(1 <= args.samples <= 100 and args.window >= 1 and 1 <= args.port <= 65535, "invalid sample/window/port")
    require(args.instances >= 1 and 1 <= args.quiet_retries <= 3 and args.retry_seconds >= 0, "invalid loader/retry count")
    if args.mode not in ("smoke", "report") and not args.self_test:
        require(args.samples >= 6 and args.window == WINDOW, "campaign requires n>=6 and the frozen 20s window")
    require(args.atomic is None or args.mode in ("counters", "smoke"), "atomic override is a separate counter diagnostic only")
    args.output, args.binary = args.output.resolve(), args.binary.resolve()
    if args.snapshot_cache:
        args.snapshot_cache = args.snapshot_cache.resolve()
    return args


def run(args):
    inventory = cells()
    chosen = selected(args, inventory)
    if args.dry_run:
        dry_run(args, chosen)
        return 0
    memtier = grammar(args)
    sources = instrument_identity()
    receipt = dict(schema=SCHEMA, binary_path=str(args.binary), binary_sha256=digest(args.binary), memtier=memtier,
                   geometry=list(args.cores), sources=sources, instrument_sha256=sha(canonical(sources)),
                   arguments={k: str(v) if isinstance(v, Path) else v for k,v in vars(args).items()
                              if k not in ("resume", "quiet_retries", "retry_seconds")}, argv_proof=argv_proof(args), perf=perf_identity(),
                   environment={k: os.environ.get(k, "") for k in ("MALLOC_CONF", "LD_PRELOAD", "LD_LIBRARY_PATH", "LC_ALL")},
                   placement=dict(ratio=args.ratio, instances=args.instances, port=args.port, window=args.window))
    # JSON arrays and Python tuples must compare identically on --resume.
    receipt = json.loads(canonical(receipt))
    null_rows = []
    if args.mode not in ("null", "smoke"):
        require(args.null is not None, "run the 14-cell same-binary null FIRST; supply --null OUTPUT")
        null_rows, controls = complete_rows([args.null])
        require(null_verdict(null_rows)["status"] == "PASS", "earlier same-binary null has not passed")
        control = controls[0]
        require(all(control[k] == receipt[k] for k in ("binary_sha256", "geometry", "memtier", "perf", "environment", "placement"))
                and compatible_instruments(control, receipt), "null identity/geometry/instrument/PMU/environment does not match")
        receipt["null_receipt_sha256"] = sha(canonical(control))
    if args.output.exists():
        require(args.resume, "output exists; use a fresh --output or --resume")
        require(json.loads((args.output / "receipt.json").read_text()) == receipt, "resume receipt changed; use a fresh output")
    else:
        require(not args.resume, "--resume requires an existing output directory")
        args.output.mkdir(parents=True)
        save(args.output / "receipt.json", receipt)
    with (args.output / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        (args.output / "rows").mkdir(exist_ok=True)
        failed = False
        for job in jobs(args, chosen):
            path = args.output / "rows" / (job["id"] + ".json")
            if path.exists() and json.loads(path.read_text())["status"] == "COMPLETE":
                continue
            cell = next(c for c in chosen if c.id == job["cell"])
            parent = args.output / "samples" / job["id"]
            parent.mkdir(parents=True, exist_ok=True)
            attempts = args.quiet_retries if args.mode == "smoke" else 1
            for attempt in range(attempts):
                number_ = 1 + len(list(parent.glob("attempt-*")))
                row = run_sample(args, cell, job, parent / f"attempt-{number_:03d}", receipt)
                row["attempt_history"] = []
                for old_path in sorted(parent.glob("attempt-*/row.json")):
                    previous = json.loads(old_path.read_text())
                    row["attempt_history"].append(dict(artifact=str(old_path), status=previous["status"],
                                                       error=previous.get("error"), started=previous["started"], finished=previous["finished"]))
                save(path, row)
                if row["status"] == "COMPLETE" or not row.get("quiet_refusal") or attempt + 1 == attempts:
                    break
                print(f"# quiet refusal retained at {row['artifact']}; retry {attempt+2}/{attempts} in {args.retry_seconds}s", flush=True)
                time.sleep(args.retry_seconds)
            summary_row = {k:v for k,v in row.items() if k not in ("passes", "quiet", "snapshot", "box_preflight", "box_share")}
            print("MKPROBE_ROW " + json.dumps(summary_row, sort_keys=True, allow_nan=False), flush=True)
            if row["status"] != "COMPLETE":
                failed = True
                # Smoke still attempts the other requested cell; campaigns stop on
                # the first invalid sample and preserve all earlier observations.
                if args.mode != "smoke":
                    break
        rows, receipts = complete_rows([args.output])
        (args.output / "rows.jsonl").write_text("".join(json.dumps(r, sort_keys=True, allow_nan=False) + "\n" for r in rows))
        summary = report(rows + null_rows, receipts, args.output, args.binary)
        return 1 if failed or (args.mode == "null" and summary["null"]["status"] != "PASS") else 0


def main(argv=None):
    args = arguments(argv)
    os.environ["LC_ALL"] = "C"
    topology = read_topology(parse_cpu_range(args.cores[0]) + parse_cpu_range(args.cores[1]))
    require(not ({topology[c] for c in parse_cpu_range(args.cores[0])} & {topology[c] for c in parse_cpu_range(args.cores[1])}),
            "server and generator axes share physical cores via SMT")
    # The Python observer and post-processing run on load CPUs. Dry runs and
    # self-tests always stay on the development allocation, even for a mainline plan.
    allowed = set(range(112, 128)) if args.self_test or args.dry_run or args.mode == "report" else set(parse_cpu_range(args.cores[1]))
    os.sched_setaffinity(0, allowed)
    if args.self_test:
        (ROOT / "build").mkdir(exist_ok=True)
        self_test(args)
        return 0
    if args.mode == "report":
        require(args.inputs, "report requires --inputs campaign output directories")
        if args.dry_run:
            print("# report reads receipts and rows only; starts no server/load/perf")
            print("\n".join(campaign_commands(args.binary, ROOT / "build/mkprobe-mainline")))
            return 0
        args.output.mkdir(parents=True, exist_ok=False)
        rows, receipts = complete_rows(args.inputs)
        result = report(rows, receipts, args.output, receipts[0]["binary_path"])
        print(json.dumps(result, indent=2))
        return 0
    return run(args)


if __name__ == "__main__":
    def interrupt(signum, frame):
        raise KeyboardInterrupt(f"signal {signum}")
    signal.signal(signal.SIGTERM, interrupt)
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"mkprobe: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
