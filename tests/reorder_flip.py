#!/usr/bin/env python3
"""Fresh-server R7/overlap integration checks on the owner's assigned cores.

Reuses coadapt's flip_fix_acceptance.py protocol; tests/flipctl.py remains the
workload and acceptance oracle. Explicitly record both switches: the original
reproduction defaults to overlap=0/reorder=0 and cannot exercise the R7 drain.
Run only when scheduled, with taskset -c 120-127. All attempts are retained and
any failed attempt makes this runner fail. Only child PIDs are stopped.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests/flipctl.py"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def stop(child):
    if child is None:
        return None
    if child.poll() is None:
        child.terminate()
        try:
            return child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
    return child.wait()


def interrupted(signum, frame):
    raise KeyboardInterrupt(f"signal {signum}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--binary", type=Path, default=ROOT / "build/tomokv")
    parser.add_argument("--port", type=int, default=10750)
    parser.add_argument("--repetitions", type=int, default=6)
    parser.add_argument("--observe", action="store_true")
    parser.add_argument("--reorder", choices=("0", "1"))
    parser.add_argument("--overlap", choices=("0", "1"))
    parser.add_argument("--sample-driver", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--driver-args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.sample_driver:
        observe(args.driver_args)
        return
    binary, port = args.binary.resolve(), args.port
    assert args.repetitions > 0
    assert set(os.sched_getaffinity(0)) <= set(range(120, 128)), "pin runner to 120-127"
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location("flipctl", DRIVER)
    flipctl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(flipctl)
    binary_sha, driver_sha = sha(binary), sha(DRIVER)
    results = []
    signal.signal(signal.SIGTERM, interrupted)
    for repetition in range(1, args.repetitions + 1):
        run = out / f"run-{repetition}"
        data = run / "data"
        data.mkdir(parents=True)
        # A foreign listener is a scheduling conflict, never a process to kill.
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
        assert sha(binary) == binary_sha and sha(DRIVER) == driver_sha
        server_argv = ["taskset", "-c", "112-119", str(binary),
                       "--port", str(port), "--shards", "16", "--ratio", "6:2",
                       "--atomic", "0", "--enable-debug-command", "yes", "--flip-auto", "1"]
        if args.reorder is not None:
            server_argv += ["--reorder", args.reorder]
        if args.overlap is not None:
            server_argv += ["--overlap", args.overlap]
        driver_argv = ["taskset", "-c", "120-127", "python3"]
        if args.observe:
            driver_argv += [str(Path(__file__).resolve()), str(run), "--sample-driver", "--driver-args"]
        else:
            driver_argv += [str(DRIVER)]
        driver_argv += ["--host", "127.0.0.1", "--port", str(port), "--stable-seconds", "30"]
        record = dict(repetition=repetition, binary_sha256=binary_sha,
                      driver_sha256=driver_sha, server_argv=server_argv,
                      driver_argv=driver_argv, server_cwd=str(data), driver_cwd=str(ROOT),
                      observer=args.observe, functional_acceptance=False)
        server = driver = None
        started = time.monotonic()
        print(f"run {repetition}/{args.repetitions}: starting {binary}, {binary_sha}", flush=True)
        try:
            with (run / "server.log").open("w") as server_log, \
                    (run / "driver.log").open("w") as driver_log:
                server = subprocess.Popen(server_argv, cwd=data, stdout=server_log,
                                          stderr=subprocess.STDOUT)
                record["server_pid"] = server.pid
                write_json(run / "result.json", record)
                deadline = time.monotonic() + 20
                while True:
                    if server.poll() is not None:
                        raise RuntimeError(f"server exited before readiness: {server.returncode}")
                    try:
                        control = flipctl.Resp("127.0.0.1", port)
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise RuntimeError("server did not listen within 20 seconds")
                        time.sleep(0.1)
                        continue
                    try:
                        assert control.command("PING") == b"PONG"
                        record["initial_server"] = flipctl.info(control, "SERVER")
                        record["initial_flipctl"] = flipctl.info(control)
                        settings = record["initial_server"]
                        expected = {"thread_mode": "2s", "shards": "16", "atomic": "0",
                                    "flip_auto": "1", "reorder": args.reorder or "0",
                                    "overlap": args.overlap or "0"}
                        for name, value in expected.items():
                            assert settings[name] == value, (name, settings[name], value)
                        assert settings["process_id"] == str(server.pid)
                        assert settings["thread_cpus"] == ",".join(f"{i}:{112+i}" for i in range(8))
                    finally:
                        control.close()
                    break
                driver = subprocess.Popen(driver_argv, cwd=ROOT, stdout=driver_log,
                                          stderr=subprocess.STDOUT,
                                          env=os.environ | {"PYTHONUNBUFFERED": "1",
                                              "R7_FLIP_TRACE": str(run / "trace.jsonl")})
                record["driver_pid"] = driver.pid
                write_json(run / "result.json", record)
                record["driver_exit"] = driver.wait(timeout=600)
                control = flipctl.Resp("127.0.0.1", port)
                try:
                    record["final_server"] = flipctl.info(control, "SERVER")
                    record["final_flipctl"] = flipctl.info(control)
                finally:
                    control.close()
                log = (run / "driver.log").read_text()
                record["functional_acceptance"] = (record["driver_exit"] == 0 and
                    "ok: flipctl functional acceptance" in log)
        except Exception as error:
            record["error"] = repr(error)
        finally:
            record["driver_exit_after_cleanup"] = stop(driver)
            record["server_exit_after_cleanup"] = stop(server)
            record["functional_acceptance"] &= record["server_exit_after_cleanup"] == 0
            record["elapsed_seconds"] = time.monotonic() - started
            write_json(run / "result.json", record)
            results.append(record)
            passed = sum(row["functional_acceptance"] for row in results)
            write_json(out / "summary.json", dict(
                binary_sha256=binary_sha, driver_sha256=driver_sha,
                required=args.repetitions, attempted=len(results), passed=passed,
                all_passed=(len(results) == passed == args.repetitions), runs=results))
            print(f"run {repetition}/{args.repetitions}: acceptance={record['functional_acceptance']}, "
                  f"elapsed={record['elapsed_seconds']:.1f}s, total={passed}/{len(results)}",
                  flush=True)
    raise SystemExit(0 if passed == args.repetitions else 1)


def observe(arguments):
    # Two DEBUG dumps on the unchanged driver's existing INFO connection; no
    # extra client, altered pacing, relaxed assertion or manufactured witness.
    import sys
    spec = importlib.util.spec_from_file_location("flipctl", DRIVER)
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    original_info = driver.info
    started, last = time.monotonic(), -1.0
    with open(os.environ["R7_FLIP_TRACE"], "x", buffering=1) as trace:
        def observed_info(control, section="FLIPCTL"):
            nonlocal last
            row = original_info(control, section)
            now = time.monotonic()
            if section == "FLIPCTL" and now - last >= 1:
                last = now
                trace.write(json.dumps(dict(seconds=now-started, info=row,
                    signals=control.command("DEBUG", "LBSIGNALS").decode(),
                    controller=control.command("DEBUG", "FLIPCTL").decode())) + "\n")
            return row
        driver.info = observed_info
        sys.argv = [str(DRIVER)] + arguments
        driver.main()


if __name__ == "__main__":
    main()
