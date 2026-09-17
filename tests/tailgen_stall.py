#!/usr/bin/env python3
"""Open-loop client-migration stall row. The gate owns the already-running server."""
import argparse
import json
import math
from pathlib import Path
import subprocess

from _lib import Conn, info
from abba_workloads import LONG_KEYS, prepare_long_keys

SHORT_KEYS = 2_000_000
ROW = "tailgen client-lb outstanding bound"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def check_report(report):
    def number(name):
        value = report.get(name)
        require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
                f"missing or invalid tailgen {name}: {value!r}")
        return value

    maximum = number("outstanding_max")
    fraction = number("over_max_outstanding_fraction")
    require(maximum <= 64, f"outstanding_max {maximum} exceeds 64")
    require(fraction == 0, f"over_max_outstanding_fraction {fraction} exceeds 0")
    require(number("window_seconds") == 20, "tailgen did not observe the full 20-second window")
    short, long = number("short_count"), number("long_count")
    require(short > 0 and long > 0 and maximum > 0, "tailgen did not exercise both workload commands")
    require(math.isclose(number("rate"), (short + long) / 20, rel_tol=1e-9),
            "tailgen rate/count/window accounting differs")


def run(args):
    args.output.mkdir(parents=True, exist_ok=True)
    conn = Conn(args.host, args.port, timeout=30)
    try:
        require(info(conn, "server").get("shards") == "256", "tailgen needs the 256-shard tail boot")
        for name, value in (("thread-mode", "1s"), ("atomic", "1"), ("overlap", "1"),
                            ("read-local", "0"), ("key-lb", "1"), ("client-lb", "1")):
            require(conn.must("CONFIG", "GET", name) == [name.encode(), value.encode()],
                    f"tailgen boot did not retain {name}={value}")
        require(conn.must("DBSIZE") == 0, "tailgen needs a fresh empty boot")
        population = ["taskset", "-c", args.cores, args.memtier,
                      "-s", args.host, "-p", str(args.port), "--protocol=redis",
                      "-t", "8", "-c", "8", "--key-minimum=1", f"--key-maximum={SHORT_KEYS}",
                      "-d", "64", "--distinct-client-seed", "--hide-histogram",
                      "--key-pattern=P:P", "--pipeline=32", "--ratio=1:0", "-n", "allkeys"]
        with (args.output / "populate.log").open("w") as log:
            subprocess.run(population, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=45)
        require(conn.must("DBSIZE") == SHORT_KEYS, "incomplete short-key population")
        for number in (1, SHORT_KEYS):
            require(conn.must("STRLEN", f"memtier-{number}") == 64, "short value size differs")
        extra = prepare_long_keys(conn)
        require(conn.must("DBSIZE") == SHORT_KEYS + LONG_KEYS, "incomplete heavy-key population")
        (args.output / "population.json").write_text(json.dumps(extra, indent=2) + "\n")
        argv = ["taskset", "-c", args.cores, str(args.binary),
                "--host", args.host, "--port", str(args.port),
                "--rate", "717000", "--threads", "16", "--conns", "32", "--cores", args.cores,
                "--mix", "GET:8,BITCOUNT:2", "--spacing", "poisson",
                "--short-keys", str(SHORT_KEYS), "--long-keys", str(LONG_KEYS),
                "--warmup", "3", "--duration", "20", "--max-outstanding", "64"]
        (args.output / "argv.json").write_text(json.dumps(argv) + "\n")
        with (args.output / "tailgen.json").open("w") as out, (args.output / "tailgen.log").open("w") as log:
            subprocess.run(argv, stdout=out, stderr=log, check=True, timeout=40)
        report = json.loads((args.output / "tailgen.json").read_text())
        check_report(report)
        print(f"PASS {ROW}: outstanding_max={report['outstanding_max']} over_fraction=0")
    finally:
        conn.close()


def self_test():
    import unittest
    from unittest import mock

    class Stall(unittest.TestCase):
        def test_boundaries_and_nonvacuity(self):
            clean = dict(outstanding_max=64, over_max_outstanding_fraction=0, window_seconds=20,
                         short_count=11_472_000, long_count=2_868_000, rate=717_000)
            check_report(clean)
            for field, values in {
                "outstanding_max": (65, 0, -1, True, float("nan")),
                "over_max_outstanding_fraction": (1e-12, 1, -1, None, float("nan")),
                "window_seconds": (0, 19, 21), "short_count": (0,), "long_count": (0,),
                "rate": (0, 1),
            }.items():
                for value in values:
                    with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                        check_report({**clean, field: value})
            for field in clean:
                with self.subTest(missing=field), self.assertRaises(RuntimeError):
                    check_report({key: value for key, value in clean.items() if key != field})

        def test_population_and_argv_use_the_valid_instrument(self):
            import tempfile
            with tempfile.TemporaryDirectory() as folder:
                args = argparse.Namespace(host="127.0.0.1", port=9999, cores="32-63",
                    binary=Path("build/tailgen"), memtier="memtier_benchmark", output=Path(folder))
                conn = mock.Mock()
                sizes = iter((0, SHORT_KEYS, SHORT_KEYS + LONG_KEYS))
                def reply(command, *values):
                    if command == "CONFIG":
                        return [values[1].encode(), b"1s" if values[1] == "thread-mode" else
                                b"0" if values[1] == "read-local" else b"1"]
                    if command == "DBSIZE": return next(sizes)
                    if command == "STRLEN": return 64
                    raise AssertionError(command)
                conn.must.side_effect = reply
                def child(argv, **kwargs):
                    if "--spacing" in argv:
                        kwargs["stdout"].write(json.dumps(dict(outstanding_max=6,
                            over_max_outstanding_fraction=0, window_seconds=20,
                            short_count=80, long_count=20, rate=5)))
                with mock.patch(__name__ + ".Conn", return_value=conn), \
                     mock.patch(__name__ + ".info", return_value={"shards": "256"}), \
                     mock.patch(__name__ + ".prepare_long_keys", return_value={}) as populate, \
                     mock.patch.object(subprocess, "run", side_effect=child) as execute:
                    run(args)
                populate.assert_called_once_with(conn)
                argv = execute.call_args_list[-1].args[0]
                for flag, value in (("--rate", "717000"), ("--threads", "16"), ("--conns", "32"),
                                    ("--cores", "32-63"), ("--long-keys", "65536"),
                                    ("--max-outstanding", "64"), ("--duration", "20")):
                    self.assertEqual(argv[argv.index(flag) + 1], value)
                conn.close.assert_called_once()

        def test_gate_row_fails_closed_and_stops_its_server(self):
            import os
            import tempfile
            gate = Path(__file__).with_name("gate.sh").read_text()
            begin = gate.index('# One correctness row, before the quick exit.')
            end = gate.index('if [ "$TIER" = quick ]; then', begin)
            row = gate[begin:end]
            stub = r'''set -u
PERF_SERVER_CORES=0-31; PERF_LOAD_CORES=32-63
PORT=9999; CANDIDATE_BINARY=unused
join_workers(){ echo JOIN; }
taskset(){ :; }
row_begin(){ echo ROW; }
boot_fused(){
  [ "$*" = 'unused --shards 256 --atomic 1 --overlap 1' ] || exit 99
  return "$BOOT_RC"
}
py(){
  [ "$*" = "tests/tailgen_stall.py --port 9999 --cores 32-63 --output $TMPDIR/tailgen-stall" ] || exit 99
  return "$LOAD_RC"
}
ok(){ echo PASS; }
bad(){ echo FAIL; }
stop(){ echo STOP; }
set_slot(){ echo RESTORE; }
'''
            with tempfile.TemporaryDirectory() as folder:
                ready = Path(folder) / "unit-ready"
                ready.mkdir()
                for built, boot, load in ((True, 0, 0), (True, 1, 0), (True, 0, 1), (False, 0, 0)):
                    (ready / "tailgen").unlink(missing_ok=True)
                    if built:
                        (ready / "tailgen").touch()
                    result = subprocess.run(["bash", "-c", stub + row], text=True, capture_output=True,
                        env={**os.environ, "RUN_DIR": folder, "TMPDIR": folder,
                             "BOOT_RC": str(boot), "LOAD_RC": str(load)}, check=True)
                    verdict = "PASS" if built and not boot and not load else "FAIL"
                    self.assertEqual(result.stdout.splitlines(), ["JOIN", "ROW", verdict, "STOP", "RESTORE"])

    return 0 if unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(Stall)).wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6379)
    parser.add_argument("--cores")
    parser.add_argument("--binary", type=Path, default=Path("build/tailgen"))
    parser.add_argument("--memtier", default="memtier_benchmark")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.cores or args.output is None:
        parser.error("--cores and --output are required")
    try:
        run(args)
        return 0
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"FAIL {ROW}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
