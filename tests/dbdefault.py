#!/usr/bin/env python3
"""Bounded default-image wire row and serverless ABBA database controls."""
import argparse
import json
from pathlib import Path
import subprocess
import time

from _lib import RespError, wait_ready
from _gate_process import info, install_signals, require


def check(conn, expected):
    configured = conn.must("CONFIG", "GET", "databases")
    require(configured == [b"databases", str(expected).encode()],
            f"CONFIG GET databases: expected {expected}, got {configured!r}")
    require(conn.must("SELECT", expected - 1) == b"OK", "last database was not selectable")
    rejected = conn.cmd("SELECT", expected)
    require(rejected == RespError("ERR DB index is out of range"),
            f"SELECT {expected}: {rejected!r}")
    require(conn.must("SELECT", 0) == b"OK", "SELECT 0 failed")
    return dict(configured_databases=expected, last_select="OK", invalid_select=str(rejected),
                server=info(conn, "server"), keyspace=info(conn, "keyspace"))


def boot(args, mode):
    folder = args.output.resolve() / mode
    folder.mkdir(parents=True, exist_ok=False)
    data = folder / "data"
    data.mkdir()
    argv = ["taskset", "-c", args.cores, str(args.binary.resolve())]
    if args.config:
        argv.append(str(args.config.resolve()))
    argv += ["--port", str(args.port), "--bind", "127.0.0.1", "--thread-mode", mode,
             "--shards", "16", "--dir", str(data), "--save", "", "--appendonly", "no"]
    if mode == "2s":
        argv += ["--ratio", args.ratio]
    if args.databases is not None:
        argv += ["--databases", str(args.databases)]
    result = dict(argv=argv, expected=args.expect, mode=mode)
    process = conn = None
    try:
        listeners = subprocess.check_output(["ss", "-H", "-ltnp", f"sport = :{args.port}"], text=True)
        require(not listeners.strip(), f"port {args.port} occupied: {listeners}")
        with (folder / "server.log").open("w") as log:
            process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
        conn = wait_ready("127.0.0.1", args.port, timeout=10, process=process,
                          log_path=folder / "server.log")
        conn.sock.settimeout(3)
        result.update(check(conn, args.expect))
        require(result["server"]["process_id"] == str(process.pid), "listener is not owned child")
        require(result["server"]["thread_mode"] == mode, "wrong thread mode")
        result["verdict"] = "PASS"
    except Exception as error:
        result.update(verdict="FAIL", error=str(error))
    finally:
        if conn:
            conn.close()
        if process:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                result.update(verdict="FAIL", error="owned server did not stop in 5 seconds")
            result["exit_code"] = process.returncode
        (folder / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def suite(abba):
    import unittest
    from dataclasses import replace
    from unittest import mock

    class DatabaseDefaults(unittest.TestCase):
        def test_database_plan_preserves_explicit_and_legacy_reference(self):
            cell = abba.Cell("dbdefault", "1s", 0, 0, 0, "GET", 32, 512)
            for arm in ("A", "B"):
                self.assertEqual(abba.database_arguments(cell, arm, True), ["--databases", "1"])
                self.assertEqual(abba.database_arguments(replace(cell, server_flags="--databases 16"),
                                                         arm, True), [])
            self.assertEqual(abba.database_arguments(cell, "A", False), [])
            for arm, explicit in (("B", ""), ("A", "--databases 16"), ("A", "--databases 1")):
                with self.assertRaises(abba.KnobNotAccepted):
                    abba.database_arguments(replace(cell, server_flags=explicit), arm, False)

        def test_modern_config_must_match_exactly(self):
            conn = mock.Mock()
            conn.must.return_value = [b"databases", b"1"]
            abba.verify_databases(conn, 1)
            for actual in ([], [b"databases", b"16"], [b"databases", b"01"], [b"wrong", b"1"]):
                conn.must.return_value = actual
                with self.assertRaises(RuntimeError):
                    abba.verify_databases(conn, 1)

        def test_legacy_requires_single_database_wire_witness(self):
            conn = mock.Mock()
            conn.must.side_effect = [[], b"OK"]
            conn.cmd.return_value = RespError("ERR DB index is out of range")
            abba.verify_databases(conn, 1, True)
            conn.must.side_effect = None
            for actual, select in (([], b"OK"), ([b"databases", b"16"], RespError("ERR"))):
                conn.must.return_value = actual
                conn.cmd.return_value = select
                with self.assertRaises(RuntimeError):
                    abba.verify_databases(conn, 1, True)

        def test_default_wire_control_fails_on_pre(self):
            conn = mock.Mock()
            conn.must.return_value = [b"databases", b"1"]
            with self.assertRaisesRegex(AssertionError, "expected 16"):
                check(conn, 16)

    return unittest.defaultTestLoader.loadTestsFromTestCase(DatabaseDefaults)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--cores", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--ratio", default="6:2")
    parser.add_argument("--mode", choices=("1s", "2s", "both"), default="both")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--databases", type=int)
    parser.add_argument("--expect", type=int, default=16)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    install_signals()
    started = time.monotonic()
    results = [boot(args, mode) for mode in (("1s", "2s") if args.mode == "both" else (args.mode,))]
    report = dict(results=results, seconds=time.monotonic() - started)
    (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if all(row["verdict"] == "PASS" for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
