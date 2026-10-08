#!/usr/bin/env python3
"""Network-IO product around the unchanged, fingerprinted ABBA instrument.

The historical headline file is a frozen 181-cell inventory, not a 32-cell
inventory. Its h01-h32 p32 product gains 32 epoll twins in a second gate pass.
No instrument module imports this coordinator: it only supplies cell DATA to
the original executable. Runtime source hashes still bind that data separately.

--dry-run prints all 64 cells and their actual current-grammar argv, without
starting a server, generator, capability probe, or quiet monitor. --smoke is an
explicit, two-boot diagnostic on server 112-119 / load 120-127, never a verdict.
"""
import argparse
from contextlib import redirect_stdout
from dataclasses import asdict, replace
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import abbagate as abba
from gate_measurements import shape
from gate_quiet import QuietMonitor, QuietViolation

ROOT = Path(__file__).resolve().parents[1]
HEADLINE = ROOT / "tests/headline_cells.txt"
EPOLL = ROOT / "tests/netio_cells.txt"
IDS = tuple(f"h{i:02}" for i in range(1, 33))
# Filled from the original data lines, including LF; not the comments or a reserialization.
FROZEN_SHA256 = "244c3941036d8b4535df60eb7a6304bd1f022e046a4c40fdada9501114bc5abc"


def data_lines(path):
    rows = {}
    for line in path.read_bytes().splitlines(keepends=True):
        if not line.strip() or line.lstrip().startswith(b"#"):
            continue
        ident = line.split(b" |", 1)[0].decode()
        if ident in rows:
            raise ValueError(f"duplicate cell data: {ident}")
        rows[ident] = line
    return rows


def check_matrix():
    originals, additions = data_lines(HEADLINE), data_lines(EPOLL)
    frozen = b"".join(originals[ident] for ident in IDS)
    if hashlib.sha256(frozen).hexdigest() != FROZEN_SHA256:
        raise ValueError("frozen h01-h32 cell bytes changed")
    expected = {ident + "-epoll": originals[ident].replace(b" |", b"-epoll |", 1).rstrip(b"\n")
                + b" | srv=--net-io epoll\n" for ident in IDS}
    if additions != expected or list(additions) != list(expected):
        raise ValueError("epoll product differs from the exact ordered h01-h32 twins")
    return dict(uring=32, epoll=32, product=64, headline=len(originals),
                gate_full=len(originals) + len(additions), frozen_sha256=FROZEN_SHA256)


def parse_abba(argv):
    saved = sys.argv
    try:
        sys.argv = [str(ROOT / "tests/abbagate.py"), *argv]
        return abba.parse_args()
    finally:
        sys.argv = saved


def knobs(cell):
    return {"thread-mode": cell.mode, "read-local": cell.read_local,
            "overlap": cell.overlap, "reorder": cell.reorder}


def server_argv(runner, cell, arm, folder):
    # Mirror only argv assembly. The serverless control below intercepts the
    # original Runner.measure at its first spawn and compares the COMPLETE argv.
    command = ["taskset", "-c", abba.cpu_string(runner.server_cpus), str(runner.binaries[arm]),
               "--port", str(runner.args.port), "--bind", "127.0.0.1", "--atomic", str(cell.atomic),
               "--enable-debug-command", "yes", "--save", "", "--appendonly", "no", "--dir", str(folder)]
    ex = 0
    if cell.mode == "2s":
        ratio = abba.measured_ratio("abba", len(runner.server_cpus))
        ex = int(ratio.split(":")[1])
        command += ["--ratio", ratio, "--flip-auto", "0"]
    command += ["--shards", str(min(8 * (ex if cell.mode == "2s" else len(runner.server_cpus)), 256))]
    for name, value in knobs(cell).items():
        command += [f"--{name}", str(value)]
    return command + abba.server_arguments(cell.server_flags)


def duration(count):
    run = abba.WARMUP + abba.WINDOW + abba.TAIL
    return dict(warmup_seconds=abba.WARMUP, window_seconds=abba.WINDOW, tail_seconds=abba.TAIL,
                generator_seconds_per_run=run, runs_per_abba=len(abba.ORDER),
                seconds_per_cell_block=run * len(abba.ORDER),
                seconds_per_product_block=count * run * len(abba.ORDER),
                excludes="boot, population, probes, teardown, quiet preflight, load search and null repeats")


def dry_run(args):
    counts = check_matrix()
    if args.cells.resolve() != HEADLINE or args.only or args.subset != "full":
        raise ValueError("dry-run prints the full network-IO product; omit --cells, --only and --subset smoke")
    abba.resolve_geometry(args)
    server, load = abba.cpus(args.server_cores), abba.cpus(args.load_cores)
    ssmt, lsmt = abba.cpus(args.server_smt), abba.cpus(args.load_smt)
    abba.check_placement(server, load, ssmt, lsmt)
    args.port, _ = abba.select_port(args.ports, args.port)
    placement = dict(server_physical=server, server_smt=ssmt, load_physical=load, load_smt=lsmt,
                     split_ratio=abba.measured_ratio("abba", len(server + ssmt)))
    cells = [cell for cell in abba.read_cells(HEADLINE, placement=placement) if cell.id in IDS]
    cells += abba.read_cells(EPOLL, placement=placement)
    out = (args.output or ROOT / "build/gateprod-dry-run").resolve()
    binaries = {"A": args.reference_binary or Path("<reference-binary>"), "B": args.candidate}
    runner = abba.Runner(args, out, binaries, None)
    rows = []
    for cell in cells:
        instances = cell.instances or 1
        layout = abba.load_layout(runner.load_cpus, instances, cell.conns, cell.dbs)
        arms = {}
        for sequence, arm in ((1, "A"), (2, "B")):
            folder = out / cell.id / f"n{instances}-{sequence}-{arm}"
            arms[arm] = dict(server_argv=server_argv(runner, cell, arm, folder),
                memtier_argv=[runner.memtier(part, cell=cell) + abba.workload_arguments(cell) +
                    [f"--pipeline={cell.depth}", f"--test-time={abba.WARMUP + abba.WINDOW + abba.TAIL}",
                     f"--json-out-file={folder / f'load-{index}.json'}"]
                    for index, part in enumerate(layout)])
        rows.append(dict(cell=asdict(cell), transport="epoll" if cell.server_flags else "uring",
            initial_instances=instances, pinned=bool(cell.instances),
            search_ladder=[] if cell.instances and not args.escalate else
                [n for n in abba.LADDER if n <= args.max_instances], arms=arms))
    return dict(kind="dry-run; no processes started", counts=counts, placement=placement,
                argv_scope="initial or pinned rung, current knob grammar; unpinned cells search the unchanged ladder",
                duration=duration(len(rows)), cells=rows)


def epoll_arguments(argv):
    """Select twins only for the standard headline; preserve private diagnostic inputs."""
    args = parse_abba(argv)
    if args.cells.resolve() != HEADLINE:
        return None
    extra = ["--cells", str(EPOLL)]
    if args.only:
        selected = [ident + "-epoll" for ident in IDS if ident in args.only.split(",")]
        if not selected:
            return None
        extra += ["--only", ",".join(selected)]
    if args.output:
        extra += ["--output", str(args.output.with_name(args.output.name + "-epoll"))]
    # A uring standing null is not evidence for epoll. The same unmodified
    # matcher rejects an absent or mismatched control; no threshold is waived.
    extra += ["--null-result", os.getenv("GATE_ABBA_EPOLL_NULL",
                str(ROOT / ".gate-history/receipts/baselines/epoll-null.json"))]
    return [*argv, *extra]


def run_gate(argv):
    check_matrix()
    epoll = epoll_arguments(argv)
    commands = [("headline", argv)] + ([("epoll", epoll)] if epoll is not None else [])
    active = None

    def interrupted(signum, _frame):
        raise InterruptedError(f"gate product interrupted by signal {signum}")

    old = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)}
    statuses = []
    try:
        for name, arguments in commands:
            print(f"GATE measurement pass: {name}", flush=True)
            # One forwarded termination lets ABBA reap its own children. A
            # private session avoids an extra terminal SIGINT during cleanup.
            active = subprocess.Popen([sys.executable, str(ROOT / "tests/abbagate.py"), *arguments],
                                      cwd=ROOT, start_new_session=True)
            rc = active.wait()
            statuses.append(dict(pass_name=name, exit_code=rc))
            active = None
        print("GATE measurement passes: " + json.dumps(statuses), flush=True)
        return 1 if any(row["exit_code"] not in (0, 3) for row in statuses) else (
            3 if any(row["exit_code"] == 3 for row in statuses) else 0)
    finally:
        if active is not None and active.poll() is None:
            active.terminate()
            try:
                active.wait(timeout=30)
            except subprocess.TimeoutExpired:
                active.kill()
                active.wait()
        for sig, handler in old.items():
            signal.signal(sig, handler)


def smoke(args):
    check_matrix()
    if (args.server_cores, args.load_cores, args.server_smt, args.load_smt) != (
            "112-119", "120-127", "", ""):
        raise ValueError("smoke requires explicit --server-cores 112-119 --load-cores 120-127 --server-smt '' --load-smt ''")
    abba.check_placement(abba.cpus(args.server_cores), abba.cpus(args.load_cores), [], [])
    args.port, _ = abba.select_port(args.ports, args.port)
    args.memtier = str(Path(abba.shutil.which(args.memtier)).resolve())
    out = (args.output or ROOT / "build/gateprod-smoke").resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = dict(kind="boot-smoke", measurement_valid=False, comparison_trusted=False,
                  candidate_sha256=abba.sha256(args.candidate), attempts=[], cells=[])
    # Initial preflight plus three retries, scheduled across ten minutes. The
    # guard and its 0.15% budget are unchanged, and a refusal starts no workload.
    started = time.monotonic()
    quiet = None
    children = abba.Children()
    try:
        for attempt in range(4):
            target = started + attempt * 200
            while time.monotonic() < target:
                time.sleep(max(0, min(30, target - time.monotonic())))
            quiet = QuietMonitor(abba.cpus(args.server_cores), abba.cpus(args.load_cores),
                ports=(args.port,), window_seconds=abba.WINDOW,
                sample_artifact=out / f"quiet-{attempt + 1}.jsonl")
            try:
                quiet.start()
                print(f"SMOKE quiet preflight {attempt + 1}: admitted", flush=True)
                break
            except QuietViolation as error:
                record = quiet.close()
                report["attempts"].append(record)
                (out / f"quiet-{attempt + 1}.json").write_text(json.dumps(record, indent=2) + "\n")
                print(f"SMOKE quiet preflight {attempt + 1}: {error}", flush=True)
                quiet = None
        if quiet is None:
            report.update(status="REFUSED", reason="initial quiet preflight and all three retries refused")
            return 3

        class SmokeRunner(abba.Runner):
            def populate(self, cell, arm, conn, folder):
                engine = "epoll" if cell.server_flags else "uring"
                actual = conn.must("CONFIG", "GET", "net-io")
                if actual != [b"net-io", engine.encode()]:
                    raise RuntimeError(f"wrong transport: {actual!r}, expected {engine}")
                report["cells"].append(dict(id=cell.id, config_net_io=engine))
                return super().populate(cell, arm, conn, folder)

        runner = SmokeRunner(args, out, {"A": args.candidate, "B": args.candidate}, children)
        # The authorized eight-core smoke uses fused h01; split ABBA has only a
        # reviewed 32-core ratio. Do not invent an eight-core measurement ratio.
        cells = [next(cell for cell in abba.read_cells(path) if cell.id == ident)
                 for path, ident in ((HEADLINE, "h01"), (EPOLL, "h01-epoll"))]
        for cell in cells:
            calibration = {}
            try:
                result = runner.measure(cell, "B", 1, 1, knobs(cell),
                                        _calibration=calibration, _window=10)
                report["cells"][-1].update(server_argv=result["server_argv"], complete=result["complete"])
            finally:
                if calibration:
                    calibration["conn"].close()
                children.close()
            log = out / cell.id / "n1-1-B/server.log"
            found = subprocess.run(["grep", "-E", r"^tomokv-cpp:.*(io_uring|epoll)", str(log)],
                                   check=True, text=True, capture_output=True).stdout.strip()
            expected = "epoll" if cell.server_flags else "io_uring"
            if expected not in found:
                raise RuntimeError(f"boot line lacks {expected}: {found}")
            report["cells"][-1]["boot_line"] = found
            print(found, flush=True)
        report["status"] = "PASS"
        return 0
    except BaseException as error:
        report.update(status="FAIL", reason=f"{type(error).__name__}: {error}")
        raise
    finally:
        children.close()
        if quiet is not None:
            report["attempts"].append(quiet.close())
        report["elapsed_seconds"] = time.monotonic() - started
        (out / "smoke.json").write_text(json.dumps(report, indent=2) + "\n")


def self_test():
    import tempfile
    import unittest
    from unittest import mock

    class Controls(unittest.TestCase):
        def test_frozen_bytes_and_full_product(self):
            from itertools import product
            from gate_measurements import apply_floor
            self.assertEqual(check_matrix()["product"], 64)
            original = [c for c in abba.read_cells(HEADLINE, measurements={"load_floors": {}}) if c.id in IDS]
            epoll = abba.read_cells(EPOLL, measurements={"load_floors": {}})
            self.assertEqual({(c.mode, c.read_local, c.overlap, c.reorder, c.op,
                               "epoll" if c.server_flags else "uring") for c in original + epoll},
                set(product(("1s", "2s"), (0, 1), (0, 1), (0, 1), ("GET", "SET"), ("uring", "epoll"))))
            for before, after in zip(original, epoll):
                self.assertEqual(replace(after, id=before.id, server_flags=""), before)
                self.assertNotEqual(shape(before), shape(after))
                self.assertEqual(after.instances, 0)
                copied = dict(instances=8, shape=shape(before), geometry={},
                              status="calibrated", instrument_sha256="fixture")
                self.assertEqual(apply_floor(after, {"load_floors": {after.id: copied}},
                    instrument_sha256="fixture").instances, 0)

        def test_instrument_scope_stays_frozen_but_uring_null_cannot_cover_epoll(self):
            from abba_instrument import instrument_fingerprint, validate_fingerprint
            from abba_evidence import match_null_identity
            fingerprint = instrument_fingerprint(ROOT)
            self.assertEqual(validate_fingerprint(fingerprint), fingerprint["sha256"])
            paths = {entry["path"] for entry in fingerprint["entries"]}
            for name in ("tests/gateprod.py", "tests/netio_cells.txt", "tests/headline_cells.txt", "tests/gate.sh"):
                self.assertNotIn(name, paths)
            def identity(path):
                return dict(instrument_fingerprint=fingerprint, cell_source=dict(
                    sha256=abba.sha256(path), total_cells=len(abba.read_cells(path))))
            uring, epoll = identity(HEADLINE), identity(EPOLL)
            match_null_identity(uring, uring)
            match_null_identity(epoll, epoll)
            with self.assertRaisesRegex(ValueError, "null inventory differs"):
                match_null_identity(epoll, uring)

        def test_dry_run_matches_real_boot_argv_for_every_cell_and_both_arms(self):
            import ast
            import inspect
            import textwrap
            syntax = ast.parse(textwrap.dedent(inspect.getsource(abba.Runner.measure)))
            # Evaluate the actual instrument's load argv expression, without
            # executing its surrounding boot/measurement body.
            expressions = [node.value for node in ast.walk(syntax) if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "argv" for target in node.targets)]
            self.assertEqual(len(expressions), 1)
            load_expression = compile(ast.Expression(expressions[0]), "Runner.measure/load-argv", "eval")
            with tempfile.TemporaryDirectory(dir=ROOT / "build") as directory:
                args = parse_abba(["--server-cores", "0-31", "--server-smt", "", "--load-cores", "32-127",
                    "--load-smt", "160-255", "--output", directory])
                plan = dry_run(args)
                self.assertEqual(len(plan["cells"]), 64)
                children = mock.Mock()
                children.start.side_effect = RuntimeError("intercepted before boot")
                runner = abba.Runner(args, Path(directory), {"A": Path("<reference-binary>"), "B": args.candidate}, children)
                for row in plan["cells"]:
                    cell = abba.Cell(**row["cell"])
                    for sequence, arm in ((1, "A"), (2, "B")):
                        with mock.patch.object(abba, "require_unbound_port"), redirect_stdout(io.StringIO()), \
                                self.assertRaisesRegex(RuntimeError, "intercepted before boot"):
                            runner.measure(cell, arm, sequence, row["initial_instances"], knobs(cell))
                        actual = list(map(str, children.start.call_args.args[0]))
                        self.assertEqual(actual, row["arms"][arm]["server_argv"])
                        if row["transport"] == "epoll":
                            self.assertEqual(actual[-2:], ["--net-io", "epoll"])
                        else:
                            self.assertNotIn("--net-io", actual)
                        folder = Path(directory) / cell.id / f"n{row['initial_instances']}-{sequence}-{arm}"
                        layout = abba.load_layout(runner.load_cpus, row["initial_instances"], cell.conns, cell.dbs)
                        for index, part in enumerate(layout):
                            actual_load = eval(load_expression, vars(abba), dict(self=runner, cell=cell,
                                placement=part, i=index, folder=folder,
                                load_lifetime=abba.WARMUP + abba.WINDOW + abba.TAIL))
                            self.assertEqual(actual_load, row["arms"][arm]["memtier_argv"][index])

        def test_absent_or_wrong_transport_and_missing_cell_cannot_pass(self):
            rows = data_lines(EPOLL)
            for mutation in (lambda r: r.pop("h01-epoll"),
                             lambda r: r.update({"h01-epoll": r["h01-epoll"].replace(b"epoll\n", b"uring\n")}),
                             lambda r: r.update({"h01-epoll": r["h01-epoll"].replace(b" | srv=--net-io epoll", b"")})):
                changed = rows.copy()
                mutation(changed)
                original_reader = data_lines
                with mock.patch(__name__ + ".data_lines", side_effect=lambda p:
                        changed if p == EPOLL else original_reader(p)), self.assertRaises(ValueError):
                    check_matrix()

        def test_selection_and_null_are_transport_specific(self):
            args = epoll_arguments(["--only", "h01,h17", "--output", "build/result", "--subset", "full"])
            parsed = parse_abba(args)
            self.assertEqual(parsed.only, "h01-epoll,h17-epoll")
            self.assertEqual(parsed.cells, EPOLL)
            self.assertEqual(parsed.output, Path("build/result-epoll"))
            self.assertIsNone(epoll_arguments(["--only", "m01"]))
            self.assertIsNone(epoll_arguments(["--cells", "tests/mkprobe_cells.txt"]))
            self.assertEqual(len(abba.selected_cells(abba.read_cells(EPOLL), "smoke")), 8)

        def test_real_coordinator_dispatches_both_passes_and_cannot_hide_epoll_failure(self):
            for statuses, expected in (((0, 0), 0), ((0, 3), 3), ((3, 0), 3), ((0, 1), 1), ((1, 0), 1)):
                processes = [mock.Mock(wait=mock.Mock(return_value=code)) for code in statuses]
                with mock.patch.object(subprocess, "Popen", side_effect=processes) as start, \
                        redirect_stdout(io.StringIO()):
                    self.assertEqual(run_gate(["--output", "build/result"]), expected)
                self.assertEqual(start.call_count, 2)
                first, second = [call.args[0] for call in start.call_args_list]
                self.assertEqual(first, [sys.executable, str(ROOT / "tests/abbagate.py"),
                                         "--output", "build/result"])
                parsed = parse_abba(second[2:])
                self.assertEqual(parsed.cells, EPOLL)
                self.assertEqual(parsed.output, Path("build/result-epoll"))

        def test_coordinator_interrupt_terminates_the_active_driver_once(self):
            process = mock.Mock()
            process.poll.return_value = None
            process.wait.side_effect = [InterruptedError("control"), 0]
            with mock.patch.object(subprocess, "Popen", return_value=process), \
                    redirect_stdout(io.StringIO()), self.assertRaises(InterruptedError):
                run_gate([])
            process.terminate.assert_called_once()
            process.kill.assert_not_called()

    (ROOT / "build").mkdir(exist_ok=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Controls))
    return 0 if result.wasSuccessful() else 1


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "perf":
        argv = argv[1:]
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--run", action="store_true")
    group.add_argument("--smoke", action="store_true")
    options, rest = parser.parse_known_args(argv)
    if options.self_test:
        return self_test()
    if options.run:
        return run_gate(rest)
    args = parse_abba(rest)
    if options.smoke:
        return smoke(args)
    print(json.dumps(dry_run(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
