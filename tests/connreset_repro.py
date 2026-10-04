#!/usr/bin/env python3
"""Connection-churn correctness reproducer (never a throughput benchmark).

Owns and stops only its own server. Every child inherits CPUs 112-127. The default
matrix is 30 variants x 10 fresh boots: two modes, three transition shapes, five
LB/load profiles. JSON retains failed/incomplete trials; these never count as a
clean non-reproduction. --dry-run starts nothing. --live-port uses a gate-owned
server and performs one witnessed transition without starting/stopping it.
"""
import argparse
import asyncio
from collections import Counter
import errno
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time

from _lib import Conn, encode

ROOT = Path(__file__).resolve().parents[1]
CPUS = set(range(112, 128))
PROFILES = {
    "default": (1, 1, 128, 500),
    "client-off": (0, 1, 128, 500),
    "key-off": (1, 0, 128, 500),
    "both-off": (0, 0, 128, 500),
    "storm1000": (1, 1, 64, 1000),
}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def parse_info(raw):
    return dict(line.split(":", 1) for line in raw.decode().splitlines()
                if line and not line.startswith("#") and ":" in line)


def classify(error):
    if isinstance(error, ConnectionResetError) or getattr(error, "errno", None) == errno.ECONNRESET:
        return "ECONNRESET"
    if isinstance(error, (EOFError, asyncio.IncompleteReadError)) or "connection closed" in str(error):
        return "EOF"
    if isinstance(error, (TimeoutError, socket.timeout)):
        return "TIMEOUT"
    if isinstance(error, BrokenPipeError):
        return "EPIPE"
    return type(error).__name__


def evidence(conn):
    result = {"info": parse_info(conn.must("INFO", "ALL")),
              "clients": parse_info(conn.must("INFO", "CLIENTS"))}
    conn.send("DEBUG", "CLOSE-STATS")
    trace = conn.read()
    result["close_stats"] = trace.decode() if isinstance(trace, bytes) else str(trace)
    return result


class Monitor:
    """ONE retained socket, never reconnected or replaced after an error."""
    def __init__(self, port, path, signals=True):
        self.port, self.path, self.signals = port, path, signals
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.samples, self.failure = [], None
        self.conn = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        try:
            self.conn = Conn("127.0.0.1", self.port, timeout=2)
            self.client_id = self.conn.must("CLIENT", "ID")
            self.owner = self.conn.must("DEBUG", "IO-THREAD")
            self.before = evidence(self.conn)
            self.ready.set()
            with self.path.open("w") as out:
                deadline = time.monotonic()
                while not self.stop.is_set():
                    row = {"t": time.monotonic(), "info": parse_info(self.conn.must("INFO"))}
                    if self.signals:
                        row["signals"] = self.conn.must("DEBUG", "LBSIGNALS").decode()
                    self.samples.append(row)
                    out.write(json.dumps(row) + "\n")
                    out.flush()
                    deadline += .1
                    self.stop.wait(max(0, deadline - time.monotonic()))
            self.after = evidence(self.conn)
        except Exception as error:
            self.failure = {"kind": classify(error), "error": str(error), "t": time.monotonic()}
            self.ready.set()
        finally:
            if self.conn:
                self.conn.close()

    def start(self):
        self.thread.start()
        require(self.ready.wait(5), "monitor did not connect")
        require(self.failure is None, "monitor failed before load: " + str(self.failure))

    def finish(self):
        self.stop.set()
        self.thread.join(5)
        require(not self.thread.is_alive(), "monitor failed to stop")
        return {"client_id": getattr(self, "client_id", None), "owner": getattr(self, "owner", None),
                "samples": len(self.samples), "failure": self.failure,
                "before": getattr(self, "before", None), "after": getattr(self, "after", None),
                "max_sample_gap": max((b["t"] - a["t"] for a, b in
                                       zip(self.samples, self.samples[1:])), default=0)}


class Cohort:
    def __init__(self, port, count, pipeline):
        self.port, self.count, self.pipeline = port, count, pipeline
        self.streams, self.tasks, self.errors = [], [], []
        self.batches = [0] * count
        self.stopping = False

    async def start(self):
        opened = await asyncio.gather(*(
            asyncio.open_connection("127.0.0.1", self.port) for _ in range(self.count)),
            return_exceptions=True)
        self.streams = [pair for pair in opened if not isinstance(pair, BaseException)]
        require(len(self.streams) == self.count, "not all persistent clients connected: " +
                str([str(pair) for pair in opened if isinstance(pair, BaseException)]))
        self.tasks = [asyncio.create_task(self.run(i, *pair)) for i, pair in enumerate(self.streams)]
        deadline = time.monotonic() + 10
        while not all(self.batches):
            require(not self.errors, "load failed during arming: " + str(self.errors))
            require(time.monotonic() < deadline, "not every persistent client completed a pipeline")
            await asyncio.sleep(.01)

    async def run(self, index, reader, writer):
        value = ("%064d" % index).encode()
        key = "connreset:%d" % index
        packet = (encode("SET", key, value) + encode("GET", key)) * (self.pipeline // 2)
        expected = (b"+OK\r\n$64\r\n" + value + b"\r\n") * (self.pipeline // 2)
        try:
            while not self.stopping:
                writer.write(packet)
                await writer.drain()
                reply = await asyncio.wait_for(reader.readexactly(len(expected)), 10)
                require(reply == expected, "load returned incorrect SET/GET data")
                self.batches[index] += 1
        except asyncio.CancelledError:
            pass
        except Exception as error:
            if not self.stopping:
                self.errors.append({"client": index, "kind": classify(error), "error": str(error)})

    def close_now(self):
        self.stopping = True
        begin = time.monotonic()
        for _, writer in self.streams:
            writer.transport.abort()  # immediate fd close; do not drain in-flight replies
        for task in self.tasks:
            task.cancel()
        return {"count": len(self.streams), "begin": begin, "end": time.monotonic()}

    async def finish(self):
        if not self.stopping:
            self.close_now()
        await asyncio.gather(*self.tasks, return_exceptions=True)


async def storm(port, count, concurrency):
    owners, errors = Counter(), []
    first, last = None, None
    async def worker(number):
        nonlocal first, last
        for _ in range(number, count, concurrency):
            writer = None
            try:
                if first is None:
                    first = time.monotonic()
                reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 3)
                writer.write(encode("DEBUG", "IO-THREAD"))
                await writer.drain()
                reply = await asyncio.wait_for(reader.readline(), 3)
                require(reply.startswith(b":") and reply.endswith(b"\r\n"),
                        "storm owner reply: " + repr(reply))
                owners[int(reply[1:-2])] += 1
                last = time.monotonic()
            except Exception as error:
                errors.append({"kind": classify(error), "error": str(error)})
            finally:
                if writer:
                    writer.transport.abort()
    await asyncio.gather(*(worker(i) for i in range(concurrency)))
    return {"requested": count, "completed": sum(owners.values()), "owners": dict(owners),
            "errors": errors, "begin": first, "end": last}


async def transition(args, variant, directory):
    mode, event, profile = variant
    client_lb, key_lb, count, storm_count = PROFILES[profile]
    monitor = Monitor(args.port, directory / "monitor.jsonl", not args.info_only)
    cohort = Cohort(args.port, count, args.pipeline)
    result = {}
    try:
        monitor.start()
        observed = monitor.before["info"]
        require(observed["thread_mode"] == mode, "observed thread mode differs from requested mode")
        if not args.live_port:
            require((int(observed["io_threads"]), int(observed["ex_threads"])) ==
                    ((8, 8) if mode == "2s" else (16, 0)), "observed IO/EX counts differ")
            require(int(observed["shards"]) == (args.shards or (64 if mode == "2s" else 128)),
                    "observed shard count differs")
        await cohort.start()
        await asyncio.sleep(args.warmup)
        require(monitor.failure is None, "monitor failed before transition: " + str(monitor.failure))
        result["before_transition"] = monitor.samples[-1] if monitor.samples else None
        require(result["before_transition"] is not None, "monitor never completed a sample")
        require(int(result["before_transition"]["info"]["connected_clients"]) == count + 1,
                "before-transition sample did not witness all persistent clients plus monitor")
        result["pipelines_before"] = list(cohort.batches)
        result["transition_t"] = time.monotonic()
        if event in ("both", "close"):
            result["close"] = cohort.close_now()
        if event in ("both", "storm"):
            result["storm"] = await storm(args.port, storm_count, args.storm_concurrency)
        await asyncio.sleep(args.observe)
        result["after_transition"] = monitor.samples[-1] if monitor.samples else None
        if monitor.failure is None:
            require(result["after_transition"]["t"] >
                    (result.get("storm", {}).get("end") or result["transition_t"]),
                    "monitor never completed a sample after the transition")
        require(not cohort.errors, "persistent load error: " + str(cohort.errors))
        if "storm" in result:
            require(result["storm"]["completed"] == storm_count and not result["storm"]["errors"],
                    "storm did not complete every DEBUG reply")
    except Exception as error:
        result["trial_error"] = {"kind": classify(error), "error": str(error)}
    finally:
        await cohort.finish()
        result["monitor"] = monitor.finish()
        result["pipelines_completed"] = list(cohort.batches)
        result["load_errors"] = cohort.errors
        # A new telemetry socket AFTER the retained monitor stops is explicitly separate.
        try:
            recovery = Conn("127.0.0.1", args.port, timeout=2)
            try:
                result["recovery"] = evidence(recovery)
            finally:
                recovery.close()
        except Exception as error:
            result["recovery_error"] = {"kind": classify(error), "error": str(error)}
    return result


def command(args, variant, directory):
    mode, _, profile = variant
    client_lb, key_lb, _, _ = PROFILES[profile]
    argv = ["taskset", "-c", "112-127", str(args.binary.resolve()), "--bind", "127.0.0.1",
            "--port", str(args.port), "--thread-mode", mode, "--client-lb", str(client_lb),
            "--key-lb", str(key_lb), "--flip-auto", "0", "--enable-debug-command", "yes",
            "--save", "", "--appendonly", "no", "--dir", str(directory.resolve())]
    if args.shards is not None:
        argv += ["--shards", str(args.shards)]
    return argv


def boot(args, variant, directory):
    # Refuse to share an occupied port, including another SO_REUSEPORT server.
    with socket.socket() as check:
        check.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        check.bind(("127.0.0.1", args.port))
    argv = command(args, variant, directory)
    with (directory / "server.log").open("wb") as out:
        proc = subprocess.Popen(argv, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT,
                                start_new_session=True)
    try:
        deadline = time.monotonic() + 15
        while True:
            require(proc.poll() is None, "server exited: " + (directory / "server.log").read_text()[-3000:])
            try:
                conn = Conn("127.0.0.1", args.port, timeout=.5)
                try:
                    require(conn.must("PING") == b"PONG", "server readiness PING")
                finally:
                    conn.close()
                break
            except (OSError, EOFError):
                require(time.monotonic() < deadline, "server startup timeout")
                time.sleep(.05)
        affinity = {}
        for task in Path(f"/proc/{proc.pid}/task").iterdir():
            try:
                allowed = os.sched_getaffinity(int(task.name))
            except ProcessLookupError:
                continue
            require(allowed <= CPUS, "server thread escaped CPUs 112-127")
            affinity[task.name] = sorted(allowed)
        return proc, {"argv": argv, "pid": proc.pid, "affinity": affinity}
    except BaseException:
        stop_server(proc)
        raise


def stop_server(proc):
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
    return proc.returncode


def report(rows, args):
    lines = ["| Variant | resets/trials | EOF/trials | other monitor failures | incomplete trials |",
             "|---|---:|---:|---:|---:|"]
    for name in dict.fromkeys(row["variant"] for row in rows):
        group = [r for r in rows if r["variant"] == name]
        kinds = Counter((r.get("monitor", {}).get("failure") or {}).get("kind") for r in group)
        incomplete = sum(bool(r.get("trial_error")) for r in group)
        lines.append(f"| {name} | {kinds['ECONNRESET']}/{len(group)} | {kinds['EOF']}/{len(group)} | "
                     f"{sum(v for k, v in kinds.items() if k not in (None, 'ECONNRESET', 'EOF'))} | {incomplete} |")
    (args.output / "table.md").write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "build/tomokv")
    parser.add_argument("--output", type=Path, default=ROOT / "build/connreset/repro")
    parser.add_argument("--port", type=int, default=19079)
    parser.add_argument("--modes", nargs="+", choices=("2s", "1s"), default=["2s", "1s"])
    parser.add_argument("--events", nargs="+", choices=("both", "close", "storm"), default=["both", "close", "storm"])
    parser.add_argument("--profiles", nargs="+", choices=PROFILES, default=list(PROFILES))
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--warmup", type=float, default=3)
    parser.add_argument("--observe", type=float, default=2)
    parser.add_argument("--pipeline", type=int, default=128)
    parser.add_argument("--storm-concurrency", type=int, default=32)
    parser.add_argument("--shards", type=int)
    parser.add_argument("--info-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live-port", type=int)
    parser.add_argument("--expect-clean", action="store_true", help="nonzero exit on a retained monitor failure")
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    require(args.repeats > 0 and args.pipeline > 0 and args.pipeline % 2 == 0,
            "positive repeats and positive even pipeline required")
    require(args.warmup >= .1 and args.observe >= .1 and args.storm_concurrency > 0,
            "positive observation windows and storm concurrency required")
    variants = [(mode, event, profile) for mode in args.modes for profile in args.profiles for event in args.events]
    if args.dry_run:
        print(json.dumps({"variants": variants, "repeats": args.repeats, "cpus": sorted(CPUS),
                          "argv": command(args, variants[0], args.output)}, indent=2))
        return 0
    if not args.live_port:
        require(CPUS <= os.sched_getaffinity(0), "all CPUs 112-127 must be available")
        os.sched_setaffinity(0, CPUS)
    else:
        args.port = args.live_port
        require(len(variants) == 1 and args.repeats == 1, "live mode requires exactly one variant/trial")
    args.output.mkdir(parents=True, exist_ok=False)
    metadata = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}
    metadata["binary_sha256"] = hashlib.sha256(args.binary.read_bytes()).hexdigest() if not args.live_port else None
    (args.output / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    rows = []
    try:
        for variant in variants:
            name = "-".join(variant)
            for repeat in range(1, args.repeats + 1):
                directory = args.output / f"{name}-r{repeat:02d}"
                directory.mkdir()
                row = {"variant": name, "repeat": repeat}
                proc = None
                try:
                    if not args.live_port:
                        proc, row["server"] = boot(args, variant, directory)
                    row.update(asyncio.run(transition(args, variant, directory)))
                except Exception as error:
                    row["trial_error"] = {"kind": classify(error), "error": str(error)}
                finally:
                    if proc:
                        row["server_returncode"] = stop_server(proc)
                        if proc.returncode != 0:
                            row["trial_error"] = {"kind": "ServerExit", "error": str(proc.returncode)}
                rows.append(row)
                (directory / "result.json").write_text(json.dumps(row, indent=2) + "\n")
                with (args.output / "results.jsonl").open("a") as out:
                    out.write(json.dumps(row) + "\n")
                report(rows, args)
                print(name, repeat, "monitor=", row.get("monitor", {}).get("failure"),
                      "trial_error=", row.get("trial_error"), flush=True)
    finally:
        report(rows, args)
    return int(any(r.get("trial_error") or (args.expect_clean and r.get("monitor", {}).get("failure")) for r in rows))


if __name__ == "__main__":
    sys.exit(main())
