#!/usr/bin/env python3
"""Stateful, same-executable OFF/ON confirmations. See MEASURE-REQUEST-pfconfirm.md.

No shell commands, process-name cleanup, standing-null substitution, or retries.
Only --smoke is authorized for the coding lane; the maintainer runs the default.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
from dataclasses import asdict, replace
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import ssl
import statistics
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tests"))
from _lib import Conn, RespError, encode, topology
from abbagate import (read_cells, load_layout, cpu_string, info, server_arguments,
                      measured_ratio, workload_arguments)
from abba_workloads import command_histogram, command_stat, percentile
from gate_quiet import QuietMonitor, QuietViolation
from gateplan import read_topology

HEADLINE = "/home/user/Projects/bench-bins/tomokv-headline-165d268be"
DIGEST = "fa9c128af17a32a68b1eece3c5ad68f00ce5f3477b65eb1b4f44c8141e5b8434"
SPECS = {
    "PFKEYSPA.1": ("ttl-", 40),
    "PFKEYSPA.3": ("flush-", 10),
    "PFKEYSPA.4": ("info-", 10),
    "PFMESSAG.1": ("tracking-", 10),
    "PFPERSIS.1": ("tls-", 35),
    "PFDATATY.1": ("stream-", 10),
}
METRICS = ("rate", "p99_ms", "p999_ms")
ORDER = "ABBA"


class CampaignAbort(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def summary(values):
    require(values and all(math.isfinite(x) and x > 0 for x in values), "invalid metric samples")
    middle = statistics.median(values)
    return dict(median=middle, minimum=min(values), maximum=max(values),
                span_pct=100 * (max(values) - min(values)) / middle)


def decide(null, blocks):
    """Pure, replayable preregistered verdict; never discards a bad block."""
    require(len(null) == 4 and len(blocks) == 3 and all(len(b) == 4 for b in blocks),
            "need one four-sample null and three complete ABBA blocks")
    require(all(r["witness"]["verdict"] == "PASS" for r in null + sum(blocks, [])),
            "TRIGGER-FIRED witness failed")
    require(all(r["complete"] for r in null + sum(blocks, [])), "incomplete sample")
    require(not any(r["trigger_on"] for r in null), "null contains an ON trigger")
    null_stats = {m: summary([r[m] for r in null]) for m in METRICS}
    require(null_stats["rate"]["span_pct"] <= 2, "unstable OFF null (>2% rate span)")
    pairs = []
    for block in blocks:
        require("".join(r["arm"] for r in block) == ORDER, "invalid ABBA order")
        require(all(r["trigger_on"] == (r["arm"] == "B") for r in block), "OFF/ON arm mismatch")
        arms = {a: {m: summary([r[m] for r in block if r["arm"] == a])
                    for m in METRICS} for a in "AB"}
        require(all(arms[a]["rate"]["span_pct"] <= 2 for a in "AB"),
                "unstable within-arm ABBA rate span (>2%)")
        pairs.append(dict(arms=arms,
            rate_loss_pct=100 * (1 - arms["B"]["rate"]["median"] / arms["A"]["rate"]["median"]),
            p99_ratio=arms["B"]["p99_ms"]["median"] / arms["A"]["p99_ms"]["median"],
            p999_ratio=arms["B"]["p999_ms"]["median"] / arms["A"]["p999_ms"]["median"]))
    losses = [p["rate_loss_pct"] for p in pairs]
    tails = [p["p99_ratio"] for p in pairs]
    rate_hit = statistics.median(losses) >= 5 and min(losses) > null_stats["rate"]["span_pct"]
    tail_hit = statistics.median(tails) >= 2 and min(tails) > 1 + null_stats["p99_ms"]["span_pct"] / 100
    return dict(verdict="HIGH upside CONFIRMED" if rate_hit or tail_hit else "NOT CONFIRMED (mark only)",
                rate_loss_pct=statistics.median(losses), p99_ratio=statistics.median(tails),
                p999_ratio=statistics.median(p["p999_ratio"] for p in pairs),
                rate_confirmed=rate_hit, p99_confirmed=tail_hit, null=null_stats, blocks=pairs,
                arms={a: {m: summary([r[m] for b in blocks for r in b if r["arm"] == a])
                          for m in METRICS} for a in "AB"})


class Children:
    """Reap only this run's child process groups, including on interrupt/watchdog."""
    def __init__(self):
        self.processes = []

    def start(self, argv, log, cwd):
        with Path(log).open("wb") as output:
            process = subprocess.Popen(list(map(str, argv)), cwd=cwd, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        self.processes.append(process)
        return process

    def wait(self, processes, timeout):
        deadline = time.monotonic() + timeout
        while any(p.poll() is None for p in processes):
            require(time.monotonic() < deadline, "child workload watchdog expired")
            time.sleep(.05)
        require(all(p.returncode == 0 for p in processes), "child failed; inspect retained logs")

    def close(self):
        for process in reversed(self.processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in reversed(self.processes):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)


class Periodic:
    """One trigger per second, with actual send/completion timestamps, never catch up."""
    def __init__(self, callback):
        self.callback = callback
        self.stop = threading.Event()
        self.rows = []
        self.error = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        target = time.monotonic() + .25
        try:
            while not self.stop.wait(max(0, target - time.monotonic())):
                require(time.monotonic() - target < 1, "trigger missed an entire 1 Hz period")
                started = time.time()
                reply = self.callback()
                self.rows.append(dict(start=started, finish=time.time(), reply=reply))
                target += 1
        except Exception as error:
            self.error = str(error)

    def close(self):
        self.stop.set()
        if self.thread.ident:
            self.thread.join(timeout=12)
            require(not self.thread.is_alive(), "trigger did not drain")
        require(self.error is None, f"trigger failed: {self.error}")


def keyspace(conn):
    data = info(conn, "keyspace")
    return {db: {k: int(v) for k, v in (item.split("=", 1) for item in row.split(","))}
            for db, row in data.items() if db.startswith("db")}


def checked_reply(conn, command, expected):
    result = conn.must(*command)
    require(result == expected, f"{command[0]} reply {result!r}, expected {expected!r}")
    return result


def pipeline(conn, commands):
    conn.raw(b"".join(encode(*command) for command in commands))
    replies = [conn.read() for _ in commands]
    require(not any(isinstance(r, RespError) for r in replies), "pipeline returned a RESP error")
    return replies


def metrics(documents, cell, layout, names):
    hist = Counter()
    counts = Counter()
    rate = 0
    times = []
    for document, place in zip(documents, layout, strict=True):
        stats = document["ALL STATS"]
        total, runtime = stats["Totals"], stats["Runtime"]
        require(runtime["Interrupted"] in (False, "false"), "interrupted memtier run")
        require(runtime["Time unit"] == "MILLISECONDS" and runtime["Total duration"] > 0,
                "unknown memtier runtime units")
        require({"Connection Errors", "Connection Errors/sec"} <= total.keys(),
                "missing memtier connection-error evidence")
        require(all(float(total.get(k, 0)) == 0 for k in
                    ("Errors", "Errors/sec", "Connection Errors", "Connection Errors/sec", "Misses/sec")),
                "memtier errors or missing main keys")
        bound = place["threads"] * place["clients"] * cell.depth
        count_error = 0
        reported_total = 0
        for name in names:
            rows = [v for k, v in stats.items() if k.upper() in (name, name + "S")]
            require(len(rows) == 1, f"missing {name} command statistics")
            row = rows[0]
            observed = command_histogram(document, name, count_bound=bound)
            done = sum(observed.values())
            counts[name] += done
            reported_total += row["Count"]
            count_error += abs(done - row["Count"])
            if name == cell.op:
                hist.update(observed)
                rate += done / (runtime["Total duration"] / 1000)
        require(count_error <= bound and reported_total == total["Count"],
                "command Count/HDR accounting failed")
        times.append((runtime["Start time"] / 1000, runtime["Finish time"] / 1000))
    require(rate > 0 and hist, "no main-command completions")
    return dict(rate=rate, p99_ms=percentile(hist, 99), p999_ms=percentile(hist, 99.9),
                completed=dict(counts), main_histogram=dict(hist),
                common_runtime=[max(t[0] for t in times), min(t[1] for t in times)], runtimes=times)


class Campaign:
    def __init__(self, args):
        self.args = args
        self.out = args.output.resolve()
        self.server = list(range(112, 120)) if args.smoke else list(range(32))
        self.load = list(range(120, 128)) if args.smoke else list(range(32, 112))
        self.seconds = 2 if args.smoke else 20
        self.port = 25000
        self.binary = self.out / "headline"
        self.cert = self.out / "cert.pem"
        self.key = self.out / "key.pem"
        self.memtier = shutil.which(args.memtier)
        require(self.memtier, "memtier_benchmark unavailable")

    def prepare(self):
        require(set(self.server + self.load) <= os.sched_getaffinity(0),
                "requested physical CPU geometry is unavailable in current affinity")
        topo = read_topology(self.server + self.load)
        require(len(set(topo.values())) == len(topo), "SMT siblings are not permitted")
        # All orchestration, TLS setup and trigger threads stay on the granted load CPUs.
        os.sched_setaffinity(0, self.load)
        require(sha(self.args.binary) == self.args.sha256, "headline digest differs from explicit pin")
        shutil.copy2(self.args.binary, self.binary)
        require(sha(self.binary) == self.args.sha256, "staged headline digest differs")
        self.memtier_sha = sha(self.memtier)
        save(self.out / "manifest.json", dict(binary_source=str(self.args.binary),
             binary_sha256=self.args.sha256, memtier=self.memtier, memtier_sha256=self.memtier_sha,
             smoke=self.args.smoke, server_cpus=self.server, load_cpus=self.load,
             ports=[self.port, self.port + 1], seconds=self.seconds,
             preregistration_sha256=sha(ROOT / "MEASURE-REQUEST-pfconfirm.md"),
             cells_sha256=sha(HERE / "cells.txt"), guards_sha256=sha(HERE / "guards.txt"),
             driver_sha256=sha(Path(__file__)),
             order=ORDER, repeats=3, null_blocks=1, guard_blocks=1))
        # Quiet screening has already passed before any executable/openssl subprocess.
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
                        "-nodes", "-subj", "/CN=localhost", "-days", "2", "-keyout", str(self.key),
                        "-out", str(self.cert)], check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=15)

    def population(self, children, folder, count, prefix, size, ttl=False):
        argv = ["taskset", "-c", cpu_string(self.load), self.memtier, "-s", "127.0.0.1",
                "-p", str(self.port), "-t", "8", "-c", "1", "--ratio=1:0", "--pipeline=64",
                "--key-minimum=1", f"--key-maximum={count}", f"--key-prefix={prefix}",
                "--key-pattern=P:P", f"--data-size={size}", "--requests=allkeys", "--hide-histogram"]
        if ttl:
            argv += ["--expiry-range=3600-3600"]
        log = folder / ("populate-" + prefix.replace(":", "-") + ".log")
        save(log.with_suffix(".argv.json"), argv)
        children.wait([children.start(argv, log, folder)], 100)

    def boot(self, cell, kind, children, folder, stack):
        ex = len(self.server) if cell.mode == "1s" else len(self.server) // 2
        shards = min(8 * ex, 256)
        argv = ["taskset", "-c", cpu_string(self.server), str(self.binary),
                "--port", str(self.port), "--bind", "127.0.0.1", "--save", "", "--appendonly", "no",
                "--dir", str(folder), "--thread-mode", cell.mode, "--shards", str(shards),
                "--read-local", str(cell.read_local), "--overlap", str(cell.overlap), "--reorder", "0",
                "--atomic", str(cell.atomic), "--key-lb", "1", "--client-lb", "1", "--flip-auto", "0",
                "--enable-debug-command", "yes"]
        if cell.mode == "2s":
            argv += ["--ratio", measured_ratio("abba", len(self.server))]
        argv += server_arguments(cell.server_flags)
        if kind == "tls":
            argv += ["--tls-port", str(self.port + 1), "--tls-auth-clients", "no", "--tls-protocols", "TLSv1.3",
                     "--tls-cert-file", str(self.cert), "--tls-key-file", str(self.key)]
        save(folder / "server-argv.json", argv)
        require(sha(self.binary) == self.args.sha256, "binary changed before boot")
        process = children.start(argv, folder / "server.log", folder)
        deadline = time.monotonic() + 15
        while True:
            require(process.poll() is None, "server exited before ready")
            try:
                conn = Conn("127.0.0.1", self.port, timeout=.5)
                checked_reply(conn, ("PING",), b"PONG")
                conn.sock.settimeout(10)
                stack.callback(conn.close)
                break
            except (OSError, EOFError):
                if "conn" in locals():
                    conn.close()
                require(time.monotonic() < deadline, "server readiness timeout")
                time.sleep(.05)
        placement = topology(conn)
        require(placement.mode == cell.mode and len(placement.roles) == len(self.server)
                and len(placement.shard_owner) == shards and len(placement.owners) == ex,
                "observed executor/shard geometry differs from registered geometry")
        save(folder / "topology.json", placement._asdict())
        return conn

    def setup(self, cell, kind, on, children, folder, conn, stack):
        state = dict(kind=kind, on=on)
        count = cell.key_count
        self.population(children, folder, count, "memtier-", cell.data_bytes)
        require(conn.must("DBSIZE") == count, "main population count mismatch")
        for key in ("memtier-1", f"memtier-{count}"):
            require(conn.must("STRLEN", key) == cell.data_bytes and conn.must("PTTL", key) == -1,
                    "main population value/TTL mismatch")
        if kind == "ttl":
            state["background"] = 4096 if self.args.smoke else 1_000_000
            self.population(children, folder, state["background"], "pf:bg:", 64, ttl=on)
        elif kind == "flush":
            state["admin"] = Conn("127.0.0.1", self.port, timeout=10)
            stack.callback(state["admin"].close)
            checked_reply(state["admin"], ("SELECT", 1), b"OK")
        elif kind == "info":
            checked_reply(conn, ("HSET", "pf:hash", "f", "v"), 1)
            if on:
                checked_reply(conn, ("HEXPIRE", "pf:hash", 3600, "FIELDS", 1, "f"), [1])
            state["admin"] = Conn("127.0.0.1", self.port, timeout=10)
            stack.callback(state["admin"].close)
        elif kind == "tracking":
            checked_reply(conn, ("SET", "never:witness", "v"), b"OK")
            tracker = state["tracker"] = Conn("127.0.0.1", self.port, timeout=5)
            stack.callback(tracker.close)
            tracker.must("HELLO", 3)
            command = ("CLIENT", "TRACKING", "ON", "BCAST", "PREFIX", "never:") if on else ("CLIENT", "TRACKING", "OFF")
            checked_reply(tracker, command, b"OK")
            state["admin"] = Conn("127.0.0.1", self.port, timeout=5)
            stack.callback(state["admin"].close)
        elif kind == "tls":
            probe = Conn("127.0.0.1", self.port + int(on), timeout=10)
            stack.callback(probe.close)
            if on:
                probe.file.close()
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
                probe.sock = context.wrap_socket(probe.sock, server_hostname="localhost")
                probe.file = probe.sock.makefile("rb")
                state["protocol"] = probe.sock.version()
                require(state["protocol"] == "TLSv1.3", "TLSv1.3 was not negotiated")
            try:
                expected = conn.must("GET", "memtier-1")
                replies = pipeline(probe, [("GET", "memtier-1")] * cell.depth)
                require(replies == [expected] * cell.depth and len(expected) == cell.data_bytes,
                        "TLS/plain pipeline payload corruption")
                state["exact_reply_bytes"] = len(expected) * len(replies)
            finally:
                probe.close()
        elif kind == "stream":
            n = state["stream_entries"] = 1000 if self.args.smoke else 100_000
            for first in range(1, n + 1, 512):
                ids = [f"{i}-0" for i in range(first, min(first + 512, n + 1))]
                replies = pipeline(conn, [("XADD", "pf:stream", ident, "f", "v") for ident in ids])
                require(replies == [i.encode() for i in ids], "XADD population reply mismatch")
            checked_reply(conn, ("XGROUP", "CREATE", "pf:stream", "g", "0"), b"OK")
            require(conn.must("XLEN", "pf:stream") == n, "stream population mismatch")
        state["resident"] = conn.must("DBSIZE")
        state["before"] = self.witness_state(cell, state, conn)
        return state

    def witness_state(self, cell, state, conn):
        kind, on = state["kind"], state["on"]
        data = dict(resident=conn.must("DBSIZE"))
        if kind == "ttl":
            keys = ("pf:bg:1", f"pf:bg:{state['background'] // 2}", f"pf:bg:{state['background']}")
            data.update(pttl=[conn.must("PTTL", k) for k in keys], keyspace=keyspace(conn),
                        main_pttl=conn.must("PTTL", "memtier-1"))
            require(all(t > 0 if on else t == -1 for t in data["pttl"]), "TRIGGER-FIRED: background TTL absent/wrong")
            require(data["keyspace"]["db0"]["expires"] == (state["background"] if on else 0)
                    and data["resident"] == cell.key_count + state["background"] and data["main_pttl"] == -1,
                    "TRIGGER-FIRED: volatile population/main TTL mismatch")
        elif kind == "flush":
            data["db1_keys"] = state["admin"].must("DBSIZE")
            require(data["db1_keys"] == 0 and data["resident"] == cell.key_count,
                    "TRIGGER-FIRED: FLUSHDB target not empty or DB0 changed")
        elif kind == "info":
            data["httl"] = conn.must("HTTL", "pf:hash", "FIELDS", 1, "f")
            data["keyspace"] = keyspace(conn)
            require(len(data["httl"]) == 1 and (data["httl"][0] > 0 if on else data["httl"][0] == -1),
                    "TRIGGER-FIRED: HEXPIRE field not present")
            require(data["keyspace"]["db0"]["subexpiry"] == int(on), "TRIGGER-FIRED: INFO subexpiry mismatch")
        elif kind == "tracking":
            data["clients"] = info(conn, "clients")
            data["stats"] = info(conn, "stats")
            require(int(data["clients"]["tracking_clients"]) == int(on), "TRIGGER-FIRED: tracking client absent")
        elif kind == "stream":
            data["pending"] = conn.must("XPENDING", "pf:stream", "g")[0]
            data["length"] = conn.must("XLEN", "pf:stream")
            require(data["length"] == state["stream_entries"], "stream length changed")
        elif kind == "tls":
            data["stats"] = info(conn, "stats")
        return data

    def trigger(self, state):
        kind, on = state["kind"], state["on"]
        admin = state.get("admin")
        if kind == "flush":
            def call():
                command = ("FLUSHDB", "SYNC") if on else ("PING",)
                return checked_reply(admin, command, b"OK" if on else b"PONG").decode()
        elif kind == "info":
            def call():
                data = admin.must("INFO")
                require(b"# Keyspace\r\n" in data and f"subexpiry={int(on)}".encode() in data,
                        "TRIGGER-FIRED: bare INFO reply lost its field TTL witness")
                return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        elif kind == "tracking":
            def call():
                checked_reply(admin, ("SET", "never:witness", "v"), b"OK")
                if not on:
                    return dict(invalidated=[])
                reply = state["tracker"].read()
                require(reply == [b"invalidate", [b"never:witness"]],
                        "TRIGGER-FIRED: missing/wrong invalidation (main prefix must not match)")
                return dict(invalidated=["never:witness"])
        else:
            return None
        return Periodic(call)

    def load_argv(self, cell, kind, on, place, folder, index):
        argv = ["taskset", "-c", cpu_string(place["cpus"]), self.memtier, "-s", "127.0.0.1",
                "-p", str(self.port + int(kind == "tls" and on)), "--protocol=redis",
                "-t", str(place["threads"]), "-c", str(place["clients"]),
                "--key-minimum=1", f"--key-maximum={cell.key_count}", f"--data-size={cell.data_bytes}",
                "--distinct-client-seed", "--hide-histogram", f"--pipeline={cell.depth}",
                f"--test-time={self.seconds}", f"--json-out-file={folder / f'load-{index}.json'}"]
        names = [cell.op]
        if kind == "tracking":
            argv += ["--command=MSET " + " ".join(f"memtier-{i} __data__" for i in range(1, 1025)),
                     "--command-ratio=1", "--command-key-pattern=P"]
        elif kind == "stream":
            feature = "XREADGROUP GROUP g c COUNT 1 STREAMS pf:stream >" if on else "XLEN pf:stream"
            argv += [f"--command={feature}", "--command-ratio=1", "--command-key-pattern=P",
                     "--command=GET __key__", "--command-ratio=127", "--command-key-pattern=P",
                     "--rate-limiting=4096"]
            names.append("XREADGROUP" if on else "XLEN")
        else:
            argv += workload_arguments(cell)
            if cell.op in ("GET", "SET"):
                argv += ["--key-pattern=P:P"]
        if kind == "tls" and on:
            argv += ["--tls", "--tls-protocols=TLSv1.3", "--tls-skip-verify"]
        return argv, names

    def finish_witness(self, cell, state, conn, periodic, result, before, after):
        kind, on = state["kind"], state["on"]
        witness = dict(verdict="PASS", trigger_on=on, before=state["before"],
                       after=self.witness_state(cell, state, conn))
        require(witness["after"]["resident"] == state["resident"], "resident population changed")
        if periodic:
            lo, hi = result["common_runtime"]
            rows = [r for r in periodic.rows if lo <= r["start"] and r["finish"] <= hi]
            require(len(rows) >= (1 if self.args.smoke else 18), "TRIGGER-FIRED: too few calls inside common load window")
            witness.update(timed_calls=len(rows), polls=periodic.rows)
        if kind == "flush":
            delta = command_stat(after, "FLUSHDB")[0] - command_stat(before, "FLUSHDB")[0]
            require(delta == (len(periodic.rows) if on else 0), "TRIGGER-FIRED: FLUSHDB calls mismatch")
            witness["flush_calls"] = delta
        elif kind == "tracking":
            delta = int(witness["after"]["stats"]["tracking_invalidations"]) - int(witness["before"]["stats"]["tracking_invalidations"])
            require(delta >= len(periodic.rows) > 0 if on else delta == 0,
                    "TRIGGER-FIRED: invalidations did not advance")
            # PING must be the next reply: no unmatched main-key pushes are hidden in the socket.
            checked_reply(state["tracker"], ("PING",), b"PONG")
            witness["invalidations"] = delta
        elif kind == "tls":
            pre, post = witness["before"]["stats"], witness["after"]["stats"]
            deltas = {k: int(post[k]) - int(pre[k]) for k in
                      ("tls_handshakes_completed", "tls_handshakes_failed", "tls_plaintext_output_bytes")}
            require(deltas["tls_handshakes_completed"] == (cell.conns if on else 0)
                    and deltas["tls_handshakes_failed"] == 0, "TRIGGER-FIRED: load TLS handshake mismatch")
            require(deltas["tls_plaintext_output_bytes"] > 0 if on else deltas["tls_plaintext_output_bytes"] == 0,
                    "TRIGGER-FIRED: missing TLS output")
            witness.update(protocol=state.get("protocol", "plain"), exact_reply_bytes=state["exact_reply_bytes"], deltas=deltas)
        elif kind == "stream":
            calls = command_stat(after, "XREADGROUP")[0] - command_stat(before, "XREADGROUP")[0]
            pending = witness["after"]["pending"]
            require(witness["before"]["pending"] == 0, "fresh group was not empty")
            require((0 < calls <= 1000 and pending == calls < state["stream_entries"]) if on else calls == pending == 0,
                    "TRIGGER-FIRED: empty/exhausted XREADGROUP or pending mismatch")
            witness["xreadgroup_calls"] = calls
        return witness

    def sample(self, original, kind, on, arm, folder):
        folder.mkdir(parents=True)
        cell = original
        if self.args.smoke:
            cell = replace(cell, conns=min(cell.conns, 8), instances=1,
                           keys=min(cell.key_count, 4096))
        result = dict(cell=asdict(cell), kind=kind, arm=arm, trigger_on=on, complete=False,
                      binary_sha256=self.args.sha256)
        children = Children()
        try:
            with ExitStack() as stack:
                stack.callback(children.close)
                conn = self.boot(cell, kind, children, folder, stack)
                state = self.setup(cell, kind, on, children, folder, conn, stack)
                layout = load_layout(self.load, cell.instances, cell.conns)
                result["layout"] = layout
                before = info(conn, "commandstats")
                periodic = self.trigger(state)
                if periodic:
                    stack.callback(periodic.close)
                loads = []
                for index, place in enumerate(layout):
                    argv, names = self.load_argv(cell, kind, on, place, folder, index)
                    save(folder / f"load-{index}-argv.json", argv)
                    loads.append(children.start(argv, folder / f"load-{index}.log", folder))
                if periodic:
                    periodic.thread.start()
                children.wait(loads, self.seconds + 45)
                if periodic:
                    periodic.close()
                after = info(conn, "commandstats")
                documents = [json.loads((folder / f"load-{i}.json").read_text()) for i in range(len(loads))]
                result.update(metrics(documents, cell, layout, names))
                require(result["common_runtime"][1] - result["common_runtime"][0] >= self.seconds - .5,
                        "load generators did not share the registered window")
                for name, done in result["completed"].items():
                    calls = command_stat(after, name)[0] - command_stat(before, name)[0]
                    require(calls == done > 0, f"{name} whole-run server/HDR mismatch: {calls} != {done}")
                save(folder / "commandstats.json", dict(before=before, after=after))
                result["witness"] = self.finish_witness(cell, state, conn, periodic, result, before, after)
                result["complete"] = True
        except Exception as error:
            result.update(error=f"{type(error).__name__}: {error}", witness=dict(verdict="FAIL"))
            raise
        finally:
            save(folder / "sample.json", result)
        return result

    def guards(self):
        results = {}
        for cell in read_cells(HERE / "guards.txt"):
            print(f"dry M0/B0 guard {cell.id}", file=sys.stderr, flush=True)
            rows = [self.sample(cell, "guard", False, arm, self.out / "guards" / cell.id / str(i))
                    for i, arm in enumerate(ORDER)]
            stats = {m: summary([r[m] for r in rows]) for m in METRICS}
            results[cell.id] = stats
            save(self.out / "guards.json", results)
            require(stats["rate"]["span_pct"] <= 2, f"unstable dry guard {cell.id}")

    def candidate(self, ident):
        prefix, estimate = SPECS[ident]
        kind = prefix[:-1]
        print(f"{ident}: budget {estimate} min; {'SHORT SMOKE only' if self.args.smoke else 'OFF null + 3 ABBA'}",
              file=sys.stderr, flush=True)
        cells = [c for c in read_cells(HERE / "cells.txt") if c.id.startswith(prefix)]
        # One representative A/B per trigger in smoke; all declared cells run at bench.
        if self.args.smoke:
            cells = cells[:1]
        results = {}
        for cell in cells:
            base = self.out / ident / cell.id
            if self.args.smoke:
                rows = [self.sample(cell, kind, arm == "B", arm, base / arm) for arm in "AB"]
                results[cell.id] = dict(verdict="SMOKE_OK (no performance verdict)",
                                       witnesses=[r["witness"] for r in rows])
                continue
            null = [self.sample(cell, kind, False, arm, base / f"null-{i}-{arm}")
                    for i, arm in enumerate(ORDER)]
            require(summary([r["rate"] for r in null])["span_pct"] <= 2, "unstable candidate null")
            blocks = [[self.sample(cell, kind, arm == "B", arm, base / f"block-{block}-{i}-{arm}")
                       for i, arm in enumerate(ORDER)] for block in range(3)]
            results[cell.id] = decide(null, blocks)
            save(base / "verdict.json", results[cell.id])
        verdict = "SMOKE_OK (no performance verdict)" if self.args.smoke else (
            "HIGH upside CONFIRMED" if any(c["verdict"] == "HIGH upside CONFIRMED" for c in results.values())
            else "NOT CONFIRMED (mark only)")
        result = dict(candidate=ident, verdict=verdict, cells=results)
        save(self.out / ident / "result.json", result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="short functional proof, CPUs 112-127 only")
    parser.add_argument("--only", choices=tuple(SPECS))
    parser.add_argument("--output", type=Path, required=True, help="new directory inside this worktree")
    parser.add_argument("--binary", type=Path, default=Path(HEADLINE))
    parser.add_argument("--sha256", default=DIGEST)
    parser.add_argument("--memtier", default="memtier_benchmark")
    args = parser.parse_args()
    require(args.output.resolve().is_relative_to(ROOT), "output must stay inside this worktree")
    args.output.mkdir(parents=True, exist_ok=False)
    candidates = [args.only] if args.only else list(SPECS)
    results, monitor, campaign = [], None, None

    def emit(result):
        results.append(result)

    def publish(result):
        line = {k: v for k, v in result.items() if k != "cells"}
        if "cells" in result:
            line["cells"] = {name: {k: v for k, v in row.items() if k in
                ("verdict", "rate_loss_pct", "p99_ratio", "p999_ratio", "arms", "null")}
                for name, row in result["cells"].items()}
        with (args.output / "results.jsonl").open("a") as stream:
            stream.write(json.dumps(line, sort_keys=True) + "\n")
        print(json.dumps(line, sort_keys=True), flush=True)

    def abort(signum, frame):
        raise CampaignAbort(f"campaign interrupted/watchdog: signal {signum}")

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(sig, abort)
    signal.alarm(300 if args.smoke else 170 * 60)
    try:
        campaign = Campaign(args)
        # No boot/probe/load/build before the repository's strict, latched quiet screen.
        monitor = QuietMonitor(campaign.server, campaign.load, window_seconds=20,
                               ports=(25000, 25001), sample_artifact=args.output / "quiet-samples.jsonl")
        monitor.start()
        campaign.prepare()
        if not args.smoke:
            campaign.guards()
        for ident in candidates:
            monitor.check()
            try:
                emit(campaign.candidate(ident))
            except CampaignAbort:
                raise
            except Exception as error:
                emit(dict(candidate=ident, verdict="FAIL", reason=f"{type(error).__name__}: {error}"))
        require(sha(campaign.binary) == args.sha256 and sha(campaign.memtier) == campaign.memtier_sha,
                "binary or generator changed during campaign")
        monitor.close()
        monitor.check()
    except Exception as error:
        verdict = "REFUSED" if isinstance(error, QuietViolation) else "FAIL"
        # A late identity/quiet/watchdog failure invalidates earlier provisional results too.
        for result in results:
            if result["verdict"] != "FAIL":
                result.update(verdict="FAIL", reason=f"campaign invalid: {type(error).__name__}: {error}")
        for ident in candidates:
            if ident not in {r["candidate"] for r in results}:
                emit(dict(candidate=ident, verdict=verdict, reason=f"{type(error).__name__}: {error}"))
        save(args.output / "campaign-error.json", dict(verdict=verdict, error=str(error)))
    finally:
        signal.alarm(0)
        if monitor:
            save(args.output / "quiet.json", monitor.close())
        save(args.output / "results.json", results)
        for result in results:
            publish(result)
    if (args.output / "campaign-error.json").exists() or any(r["verdict"] in ("FAIL", "REFUSED") for r in results):
        return 3 if results and all(r["verdict"] == "REFUSED" for r in results) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
