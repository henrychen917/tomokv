#!/usr/bin/env python3
"""Mainline-only LB convergence episodes; --self-test and --dry-run start nothing.

Frozen PRE balanced windows determine ONE envelope per mode before any scored
arms run. Missing stimulus, motion, telemetry or a complete hold is a failure.
See MEASURE-REQUEST-lbplanner-bench.md for geometry and interpretation limits.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from _lib import Conn  # noqa: E402
from abba_workloads import (command_histogram, memtier_workload_counts, percentile,
                            require_workload_accounting)  # noqa: E402

PREFIX = "tomokv_keylb_"
TICKS, STAGE = PREFIX + "ticks", PREFIX + "stage"
KEY, CLIENT, GATHERS = (PREFIX + n for n in ("bucket_moves", "client_moves", "bucket_gathers"))
SPREADS = tuple(PREFIX + n + "_spread_current" for n in
                ("bucket_weight", "bucket_bytes", "client_weight"))
REFUSALS = tuple(PREFIX + n for n in (
    "no_candidate", "hysteresis_refused", "cooldown_refused", "transition_refused",
    "capacity_refused", "client_refused", "hot_bucket_refused"))
COUNTERS = (TICKS, KEY, CLIENT, GATHERS, PREFIX + "bucket_cross_domain_moves",
            PREFIX + "client_cross_domain_moves", *REFUSALS)
FIELDS = (STAGE, *COUNTERS, *SPREADS,
          *(n.replace("current", edge) for n in SPREADS for edge in ("before", "after")))
ARMS = {
    "PRE": ("build/lbplanner-pre/tomokv", "33f07418205817e93d5d759d4cab78480f77c5aa9fa51618dc89aa3e3828f8a2"),
    "PAD-A": ("build/tomokv-lbplanner-pad", "bdda99b8c96438cfa60637279c886827cc1a6d78370a5c9a5053e73a79d634c8"),
    "POST": ("build/tomokv", "571fa4ab3e81f1d231941be82f22950644e0ed437a85d50d6111e5545354e0f1"),
}
INTERVAL = .1
DECISION_TICKS, DECISION_SECONDS = 3, 3.0  # frozen arms' LbAutotune, not a fitted threshold
KEYS, CONNECTIONS, PIPELINE, DATA_SIZE = 500000, 128, 128, 64
SERVER_CORES, LOAD_CORES = "0-15", "64-95"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def parse_info(raw, mandatory=True):
    require(isinstance(raw, bytes), "INFO must return a bulk string")
    result = {}
    for line in raw.decode().splitlines():
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        require(sep and key not in result, "malformed/duplicate INFO field: " + line)
        result[key] = value
    if mandatory:
        require(all(k in result for k in FIELDS), "INFO LB missing mandatory fields")
        require(result.get(PREFIX + "enabled") == result.get("tomokv_clientlb_enabled") == "1",
                "both balancers must be enabled")
        for key in FIELDS:
            value = float(result[key]) if "spread" in key else int(result[key])
            require(math.isfinite(value) and value >= 0, "invalid INFO value: " + key)
            result[key] = value
    return result


def parse_signals(raw):
    require(isinstance(raw, bytes), "LBSIGNALS must return a bulk string")
    result = {"threads": {}, "shards": {}, "raw": raw.decode()}
    for line in raw.decode().splitlines():
        v = line.split()
        if not v:
            continue
        if v[0] == "lbver":
            require(len(v) == 4 and v[:3] == ["lbver", "1", "stamp_ns"], "bad LB schema")
            result["stamp_ns"] = int(v[3])
        elif v[0] == "thread":
            require(len(v) >= 23 and v[2] in ("fused", "io", "ex"), "bad LB thread row")
            tid = int(v[1])
            require(tid not in result["threads"], "duplicate LB thread")
            row = dict(zip(("domain", "clients", "iterations", "ops", "busy_ns", "idle_ns",
                            "cpu_ns"), map(int, v[3:10])))
            require(all(n >= 0 for n in row.values()), "negative LB thread counter")
            result["threads"][tid] = dict(row, role=v[2])
        elif v[0] == "shard":
            require(len(v) == 9, "bad LB shard row")
            sid = int(v[1])
            require(sid not in result["shards"], "duplicate LB shard")
            result["shards"][sid] = dict(zip(
                ("owner", "domain", "ops", "foreign_ops", "migrations", "size", "obj_bytes"),
                map(int, v[2:])))
        elif v[0] == "derived":
            require(len(v) % 2 == 1, "bad LB derived row")
            result["derived"] = dict(zip(v[1::2], v[2::2]))
    require(result.get("stamp_ns", 0) > 0 and result["threads"] and result["shards"]
            and "derived" in result, "incomplete LBSIGNALS")
    require(all(r["owner"] in result["threads"] for r in result["shards"].values()),
            "shard references absent owner")
    return result


def geometry(sample, mode):
    snap = sample["signals"]
    require(snap["derived"]["thread_mode"] == mode, "wrong thread mode")
    roles = Counter(r["role"] for r in snap["threads"].values())
    require(roles == ({"fused": 16} if mode == "1s" else {"io": 12, "ex": 4}),
            "expected 16 fused or 12 IO + 4 EX on cores 0-15 (ratio 6:2)")
    require(set(snap["shards"]) == set(range(16)), "expected exactly 16 shards")
    return sorted(tid for tid, row in snap["threads"].items() if row["role"] in ("io", "fused"))


def delta(before, after):
    result = {key: after["info"][key] - before["info"][key] for key in COUNTERS}
    require(all(n >= 0 for n in result.values()), "LB counter reset")
    result["total_moves"] = result[KEY] + result[CLIENT]
    return result


def beats(samples):
    """Last observation of each *closed* beat avoids treating 10 polls as 10 decisions."""
    result, previous = [], None
    for sample in samples:
        if previous:
            change = sample["info"][TICKS] - previous["info"][TICKS]
            require(change in (0, 1), "missed controller beat or reset")
            delta(previous, sample)
            require(0 < sample["t"] - previous["t"] <= .5, "telemetry gap exceeds 500 ms")
            if change:
                result.append(previous)
        previous = sample
    return result


def envelope(samples):
    rows = beats(samples)
    require(len(rows) >= 3 * DECISION_TICKS, "PRE baseline needs three complete decision windows")
    require(rows[-1]["t"] - rows[0]["t"] >= 3 * DECISION_SECONDS,
            "PRE baseline duration too short")
    require(delta(rows[0], rows[-1])["total_moves"] == 0,
            "PRE balanced baseline still moving; no envelope may be fitted")
    require(all(s["info"][STAGE] == 0 for s in rows), "PRE baseline has an active plan")
    require(all(rows[-1]["signals"]["threads"][tid]["ops"] > old["ops"]
                for tid, old in rows[0]["signals"]["threads"].items()),
            "PRE baseline has an inactive owner")
    return {"upper": {key: max(s["info"][key] for s in rows) for key in SPREADS},
            "lower": {key: 0 for key in SPREADS}, "beats": len(rows),
            "first_tick": rows[0]["info"][TICKS], "last_tick": rows[-1]["info"][TICKS],
            "sustain_seconds": DECISION_SECONDS, "sustain_ticks": DECISION_TICKS,
            "source": "PRE balanced baseline; observed maxima; never widened using an arm"}


def inside(sample, criterion):
    return (sample["info"][STAGE] == 0 and
            all(sample["info"][k] <= limit for k, limit in criterion["upper"].items()))


def convergence(samples, stimulus, end, criterion, episode, max_seconds, suffix_seconds):
    rows = beats(samples)
    before = [s for s in samples if s["t"] <= stimulus]
    after = [s for s in samples if stimulus < s["t"] <= end]
    require(before and after, "episode has no bracketing samples")
    anchor, final = before[-1], after[-1]
    rows = [s for s in rows if stimulus < s["t"] <= final["t"]]
    primary = SPREADS[0] if episode == "key-skew" else SPREADS[2]
    move = KEY if episode == "key-skew" else CLIENT
    excursion = next((s for s in rows if s["info"][primary] > criterion["upper"][primary]), None)
    total = delta(anchor, final)
    result = {"status": "FAIL", "t_converge": None, "deltas": total,
              "key_moves": total[KEY], "client_moves": total[CLIENT],
              "total_moves": total["total_moves"], "gathers": total[GATHERS],
              "suffix_moves": None, "suffix_deltas": None,
              "anchor_t": anchor["t"], "end_t": final["t"],
              "excursion_t": excursion["t"] if excursion else None}
    if excursion is None:
        return dict(result, reason="required spread never left the PRE envelope; stimulus unarmed")
    if total[move] == 0 or (episode == "key-skew" and total[GATHERS] == 0):
        return dict(result, reason="no required controller move/admission; cannot prove convergence")
    # Use the FINAL uninterrupted return: a later excursion invalidates an earlier apparent
    # convergence. All moves from stimulus through the full fixed observation remain charged.
    streak = None
    for row in rows:
        if row["t"] <= excursion["t"] or not inside(row, criterion):
            streak = None
        elif streak is None and delta(anchor, row)[move] > 0:
            streak = row
    if streak is None:
        return dict(result, reason="did not return to the fixed PRE envelope")
    confirmed = next((row for row in rows if row["t"] - streak["t"] >= DECISION_SECONDS and
                      row["info"][TICKS] - streak["info"][TICKS] >= DECISION_TICKS), None)
    if (confirmed is None or streak["t"] - stimulus > max_seconds or
            final["t"] - confirmed["t"] < suffix_seconds or
            final["info"][TICKS] - confirmed["info"][TICKS] < DECISION_TICKS):
        return dict(result, reason="return lacks sustained decision window or complete stationary suffix")
    suffix = delta(confirmed, final)
    return dict(result, status="PASS" if suffix["total_moves"] == 0 else "FAIL",
                reason="complete" if suffix["total_moves"] == 0 else "moves during stationary suffix",
                t_converge=streak["t"] - stimulus, confirmed_t=confirmed["t"],
                suffix_seconds=final["t"] - confirmed["t"], suffix_deltas=suffix,
                suffix_moves=suffix["total_moves"])


def occupancy(samples, start, end, coordinator):
    rows = [s for s in samples if start <= s["t"] <= end]
    require(len(rows) >= 2, "missing occupancy window")
    first, last = rows[0]["signals"], rows[-1]["signals"]
    result = {}
    for tid, old in first["threads"].items():
        new = last["threads"][tid]
        counters = {key: new[key] - old[key] for key in ("busy_ns", "idle_ns", "cpu_ns", "ops")}
        require(all(n >= 0 for n in counters.values()), "thread counters reset")
        denom = counters["busy_ns"] + counters["idle_ns"]
        require(denom > 0, "thread occupancy not observed")
        result[tid] = dict(counters, busy_pct=100 * counters["busy_ns"] / denom, role=new["role"])
    return {"threads": result, "coordinator": coordinator, "coord_busy": result[coordinator]["busy_pct"]}


def metrics(documents, before, after, expected_seconds):
    hist, rate, per_loader, accounting = Counter(), 0, [], []
    cell = SimpleNamespace(op="SET", depth=PIPELINE, conns=CONNECTIONS)
    for document in documents:
        stats = document["ALL STATS"]
        total = stats["Totals"]
        require("Connection Errors" in total, "memtier lacks connection-error evidence")
        require(all(float(total.get(k, 0)) == 0 for k in
                    ("Errors", "Errors/sec", "Connection Errors", "Connection Errors/sec")),
                "memtier reports errors")
        require(str(stats["Runtime"].get("Interrupted", "false")).lower() == "false",
                "memtier interrupted")
        value = float(total["Ops/sec"])
        require(math.isfinite(value) and value > 0, "invalid memtier rate")
        runtime = stats["Runtime"]
        require(runtime["Time unit"] == "MILLISECONDS" and
                float(runtime["Total duration"]) >= (expected_seconds - 1) * 1000,
                "memtier ended before the requested fixed episode duration")
        # The gate's audited finite Count/HDR bound is 64 connections * 128 outstanding
        # replies. It is legal ONLY alongside exact server SET calls == drained HDR counts.
        evidence = memtier_workload_counts(cell, document, CONNECTIONS // 2)
        bins = command_histogram(document, "SET", count_bound=evidence["outstanding_bound"])
        accounting.append(evidence)
        hist.update(bins)
        rate += value
        per_loader.append({"rate": value, "p99": percentile(bins, 99), "count": sum(bins.values()),
                           "runtime": runtime})
    return {"rate": rate, "p99": percentile(hist, 99), "loaders": per_loader,
            "accounting": require_workload_accounting(cell, before, after, accounting),
            "p99_method": "merged SET HDR counts; microseconds converted to milliseconds"}


# Connect-only LD_PRELOAD helper: select real TCP sockets with the read-only owner hook.
# No send/recv interposition, forwarding process, server mutation or steady-path work.
# A new socket replaces a rejected one on the SAME descriptor before memtier uses it.
SELECTOR_C = r'''
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/tcp.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>
static _Atomic unsigned sequence;
static void fail(const char *why) { dprintf(2, "lb-owner-selector: %s\n", why); _exit(91); }
int connect(int fd, const struct sockaddr *address, socklen_t length) {
    int (*real_connect)(int, const struct sockaddr *, socklen_t) = dlsym(RTLD_NEXT, "connect");
    const char *port = getenv("LB_EPISODE_PORT"), *owners = getenv("LB_EPISODE_OWNERS");
    if (!real_connect) fail("dlsym connect");
    if (!port || !owners || address->sa_family != AF_INET ||
        ntohs(((const struct sockaddr_in *)address)->sin_port) != atoi(port))
        return real_connect(fd, address, length);
    unsigned ids[128], n = 0;
    char *copy = strdup(owners), *save = NULL;
    if (!copy) fail("strdup");
    for (char *p = strtok_r(copy, ",", &save); p; p = strtok_r(NULL, ",", &save)) {
        if (n == 128) fail("too many owners");
        ids[n++] = strtoul(p, NULL, 10);
    }
    free(copy);
    if (!n) fail("empty owner list");
    unsigned index = atomic_fetch_add(&sequence, 1), wanted = ids[index % n];
    int flags = fcntl(fd, F_GETFL), descriptor_flags = fcntl(fd, F_GETFD);
    if (flags < 0 || descriptor_flags < 0) fail("fcntl");
    for (unsigned attempt = 0; attempt < 512; ++attempt) {
        if (attempt) {
            int replacement = socket(AF_INET, SOCK_STREAM, 0);
            if (replacement < 0 || dup2(replacement, fd) < 0) fail("replace socket");
            close(replacement);
        }
        struct timeval timeout = {.tv_sec = 2};
        int yes = 1;
        if (fcntl(fd, F_SETFL, flags & ~O_NONBLOCK) < 0 ||
            setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) ||
            setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) ||
            setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &yes, sizeof(yes))) fail("socket setup");
        if (real_connect(fd, address, length)) fail("connect");
        const char request[] = "*2\r\n$5\r\nDEBUG\r\n$9\r\nIO-THREAD\r\n";
        size_t sent = 0;
        while (sent < sizeof(request)-1) {
            ssize_t count = send(fd, request+sent, sizeof(request)-1-sent, MSG_NOSIGNAL);
            if (count <= 0) fail("owner query send");
            sent += (size_t)count;
        }
        char reply[64]; size_t used = 0;
        while (used < sizeof(reply)-1) {
            if (recv(fd, reply+used, 1, 0) != 1) fail("owner query receive");
            if (reply[used++] == '\n') break;
        }
        reply[used] = 0;
        unsigned owner; char extra;
        if (sscanf(reply, ":%u\r\n%c", &owner, &extra) != 1 || used < 4 ||
            reply[used-2] != '\r' || reply[used-1] != '\n') fail("bad owner reply");
        if (owner != wanted) continue;
        timeout.tv_sec = 0;
        if (setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) ||
            setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) ||
            fcntl(fd, F_SETFL, flags) < 0 || fcntl(fd, F_SETFD, descriptor_flags) < 0)
            fail("restore socket");
        const char *path = getenv("LB_EPISODE_LOG");
        int logfd = path ? open(path, O_WRONLY|O_APPEND|O_CREAT|O_CLOEXEC, 0600) : -1;
        if (logfd < 0) fail("owner log open");
        struct timespec stamp; clock_gettime(CLOCK_MONOTONIC, &stamp);
        char line[256]; int size = snprintf(line, sizeof(line),
            "{\"index\":%u,\"owner\":%u,\"attempts\":%u,\"t\":%ld.%09ld}\n",
            index, owner, attempt+1, stamp.tv_sec, stamp.tv_nsec);
        if (write(logfd, line, (size_t)size) != size) fail("owner log write");
        close(logfd);
        return 0;
    }
    fail("owner never armed after 512 fresh connections");
    return -1;
}
'''


class Children:
    def __init__(self):
        self.processes = []

    def start(self, argv, log, cwd, env=None):
        print("COMMAND " + shlex.join(argv), flush=True)
        with log.open("wb") as stream:
            proc = subprocess.Popen(argv, stdout=stream, stderr=subprocess.STDOUT,
                                    cwd=cwd, env=env, start_new_session=True)
        self.processes.append(proc)
        return proc

    def close(self):
        for proc in reversed(self.processes):
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=10)


def cpu_ticks(path):
    # /proc comm may contain spaces or parentheses; field 3 follows the LAST ')'.
    fields = path.read_text().rsplit(")", 1)[1].split()
    return int(fields[11]) + int(fields[12])  # fields 14 + 15


class Sampler:
    def __init__(self, port, path, pid):
        self.port, self.path, self.pid = port, path, pid
        self.samples, self.error = [], None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        conn = None
        try:
            conn = Conn("127.0.0.1", self.port, timeout=2)
            with self.path.open("w") as stream:
                deadline = time.monotonic()
                while not self.stop.is_set():
                    started = time.monotonic()
                    row = {"t": started, "info": parse_info(conn.must("INFO", "LB")),
                           "signals": parse_signals(conn.must("DEBUG", "LBSIGNALS"))}
                    row["process_cpu_ticks"] = cpu_ticks(Path(f"/proc/{self.pid}/stat"))
                    row["monitor_cpu_ticks"] = cpu_ticks(Path(f"/proc/{self.pid}/task/{self.pid}/stat"))
                    row["capture_seconds"] = time.monotonic() - started
                    self.samples.append(row)
                    stream.write(json.dumps(row, allow_nan=False) + "\n")
                    stream.flush()
                    deadline += INTERVAL
                    self.stop.wait(max(0, deadline - time.monotonic()))
        except Exception as error:
            self.error = str(error)
        finally:
            if conn:
                conn.close()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)
        require(not self.thread.is_alive(), "sampler did not stop")
        require(self.error is None, "sampler failed: " + str(self.error))


def server_command(args, arm, mode, directory):
    argv = ["taskset", "-c", SERVER_CORES, str(ROOT / ARMS[arm][0]),
            "--bind", "127.0.0.1", "--port", str(args.port), "--thread-mode", mode,
            "--shards", "16", "--key-lb", "1", "--client-lb", "1", "--flip-auto", "0",
            "--enable-debug-command", "yes", "--save", "", "--appendonly", "no",
            "--dir", str(directory), "--dbfilename", "seed.tomo"]
    if mode == "2s":
        argv += ["--ratio", "6:2"]
    return argv


def load_command(args, directory, label, low, high, duration=None, populate=False, owners=None):
    argv = ["taskset", "-c", LOAD_CORES, args.memtier, "-s", "127.0.0.1", "-p", str(args.port),
            "--protocol=redis", "-t", "8" if populate else "4", "-c", "4" if populate else "16",
            "--ratio=1:0", "--key-pattern=" + ("P:P" if populate else "R:R"),
            f"--key-minimum={low}", f"--key-maximum={high}", "--key-prefix=memtier-",
            "-d", str(DATA_SIZE), "--hide-histogram",
            "--json-out-file=" + str(directory / (label + ".json"))]
    if populate:
        argv += ["-n", str(KEYS // 32)]
    else:
        argv += [f"--pipeline={PIPELINE}", "--test-time=" + str(duration)]
        if args.rate_per_client:
            argv += [f"--rate-limiting={args.rate_per_client}"]
    if owners is not None:
        argv = ["env", "LD_PRELOAD=" + str(args.output / "owner-select.so"),
                "LB_EPISODE_PORT=" + str(args.port),
                "LB_EPISODE_OWNERS=" + ",".join(map(str, owners)),
                "LB_EPISODE_LOG=" + str(directory / (label + ".owners.jsonl")), *argv]
    return argv


@contextmanager
def boot(args, arm, mode, directory, seed=None):
    directory.mkdir(parents=True, exist_ok=False)
    if seed:
        shutil.copyfile(seed, directory / "seed.tomo")
        require(digest(directory / "seed.tomo") == digest(seed), "snapshot copy mismatch")
    # Bind without SO_REUSEPORT: never share with or kill another measurement's listener.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", args.port))
    children, conn = Children(), None
    try:
        proc = children.start(server_command(args, arm, mode, directory), directory / "server.log", directory)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            require(proc.poll() is None, "server exited during boot")
            try:
                conn = Conn("127.0.0.1", args.port, timeout=2)
                identity = parse_info(conn.must("INFO", "SERVER"), False)
                require(int(identity["process_id"]) == proc.pid, "server PID does not match owned child")
                break
            except (OSError, EOFError):
                if conn:
                    conn.close()
                    conn = None
                time.sleep(.1)
        require(conn is not None, "server boot timeout")
        sample = {"signals": parse_signals(conn.must("DEBUG", "LBSIGNALS"))}
        owners = geometry(sample, mode)
        parse_info(conn.must("INFO", "LB"))
        yield conn, children, owners, identity
    finally:
        if conn:
            conn.close()
        children.close()


def wait_loads(processes, sampler=None, timeout=600):
    deadline = time.monotonic() + timeout
    while any(p.poll() is None for p in processes):
        require(time.monotonic() < deadline, "load timeout")
        require(all(p.poll() in (None, 0) for p in processes), "memtier failed; inspect loader log")
        if sampler:
            require(sampler.error is None, "telemetry failed: " + str(sampler.error))
        time.sleep(.05)
    require(all(p.returncode == 0 for p in processes), "memtier failed; inspect loader log")
    return time.monotonic()


def key_mapping(conn, hotmax):
    result = []
    for start in range(1, hotmax + 1, 128):
        keys = ["memtier-" + str(i) for i in range(start, min(hotmax + 1, start + 128))]
        rows = conn.must("DEBUG", "SHARDS", *keys)
        require(isinstance(rows, list) and len(rows) == len(keys), "bad physical key map")
        result.extend([key, int(row[0])] for key, row in zip(keys, rows))
    return result


def prepare_seed(args):
    directory = args.output / "seed"
    with boot(args, "PRE", "1s", directory) as (conn, children, owners, identity):
        argv = load_command(args, directory, "populate", 1, KEYS, populate=True)
        proc = children.start(argv, directory / "populate.log", directory)
        wait_loads([proc])
        require(conn.must("DBSIZE") == KEYS, "population did not produce exactly 500000 keys")
        mapping = key_mapping(conn, args.hotmax)
        require(conn.must("SAVE") == b"OK", "seed SAVE failed")
    path = directory / "seed.tomo"
    record = {"sha256": digest(path), "path": str(path), "hot_keys": mapping,
              "population_command": argv, "identity": identity}
    save_json(directory / "manifest.json", record)
    return path, record


def owner_evidence(directory, labels, expected):
    result = {}
    for label, targets in zip(labels, expected):
        rows = [json.loads(line) for line in (directory / (label + ".owners.jsonl")).read_text().splitlines()]
        require(len(rows) == 64 and {r["index"] for r in rows} == set(range(64)),
                "loader did not arm exactly 64 selected connections (or reconnected)")
        require(all(r["owner"] == targets[r["index"] % len(targets)] for r in rows),
                "connection selector did not produce requested owners")
        result[label] = rows
    return result


def run_episode(args, arm, mode, episode, round_no, seed, seed_record, criterion=None):
    calibration = episode == "balanced"
    name = f"{episode}-{mode}-{arm}-r{round_no}"
    directory = args.output / name
    result = {"name": name, "arm": arm, "mode": mode, "episode": episode, "round": round_no,
              "binary": str(ROOT / ARMS[arm][0]), "sha256": ARMS[arm][1],
              "seed_sha256": seed_record["sha256"], "criterion": criterion,
              "status": "FAIL", "sampling_interval": INTERVAL, "commands": []}
    sampler = None
    try:
        with boot(args, arm, mode, directory, seed) as (conn, children, owners, identity):
            result["identity"] = identity
            require(key_mapping(conn, args.hotmax) == seed_record["hot_keys"], "physical key map changed")
            sampler = Sampler(args.port, directory / "telemetry.jsonl", int(identity["process_id"]))
            sampler.thread.start()
            baseline_start = time.monotonic()
            processes = []
            for label in ("baseline-a", "baseline-b"):
                argv = load_command(args, directory, label, 1, KEYS,
                                    args.warm + args.baseline + 3, owners=owners)
                result["commands"].append(argv)
                processes.append(children.start(argv, directory / (label + ".log"), directory))
            baseline_end = wait_loads(processes, sampler, args.warm + args.baseline + 63)
            result["baseline"] = {"start": baseline_start, "end": baseline_end,
                                  "owners": owner_evidence(directory, ("baseline-a", "baseline-b"), [owners, owners])}
            # Trim both connection setup and generator teardown. The last three seconds are
            # guard time, not calibration evidence. No candidate run refits these limits.
            balanced = [s for s in sampler.samples if
                        baseline_start + args.warm <= s["t"] <= baseline_start + args.warm + args.baseline]
            if calibration:
                result["criterion"] = envelope(balanced)
                result["criterion"]["shard_owners"] = {
                    str(sid): row["owner"] for sid, row in balanced[-1]["signals"]["shards"].items()}
                result["status"] = "PASS"
            else:
                baseline_beats = beats(balanced)
                require(len(baseline_beats) >= 3 * DECISION_TICKS, "run baseline lacks beats")
                result["baseline_in_envelope_fraction"] = sum(inside(s, criterion) for s in balanced) / len(balanced)
                require(all(inside(s, criterion) for s in baseline_beats[-(DECISION_TICKS + 1):]) and
                        delta(baseline_beats[0], baseline_beats[-1])["total_moves"] == 0,
                        "pre-stimulus baseline not stationary inside the PRE envelope")
                require({str(sid): row["owner"] for sid, row in balanced[-1]["signals"]["shards"].items()}
                        == criterion["shard_owners"], "pre-stimulus shard placement differs from PRE")
                command_before = parse_info(conn.must("INFO", "COMMANDSTATS"), False)
                stimulus = time.monotonic()
                result["stimulus_t"] = stimulus
                result["baseline_to_stimulus_gap"] = stimulus - baseline_end
                processes = []
                post_owners = [owners, owners[:2] if episode == "client-skew" else owners]
                ranges = [(args.hotmax + 1, KEYS), (1, args.hotmax)] if episode == "key-skew" else [(1, KEYS)] * 2
                duration = args.max_converge + DECISION_SECONDS + args.suffix + 3
                for label, targets, (low, high) in zip(("cold", "hot"), post_owners, ranges):
                    argv = load_command(args, directory, label, low, high, int(duration), owners=targets)
                    result["commands"].append(argv)
                    processes.append(children.start(argv, directory / (label + ".log"), directory))
                finish = wait_loads(processes, sampler, duration + 60)
                command_after = parse_info(conn.must("INFO", "COMMANDSTATS"), False)
                # Fixed common window, ending before either load's requested test-time.
                end = stimulus + duration - 3
                result["loads_finished_t"] = finish
                result["owners"] = owner_evidence(directory, ("cold", "hot"), post_owners)
                result["stimulus_ready_t"] = max(r["t"] for rows in result["owners"].values() for r in rows)
                require(result["stimulus_ready_t"] - stimulus < DECISION_SECONDS,
                        "connection burst took a full decision window; stimulus is not a step")
                result.update(convergence(sampler.samples, stimulus, end, criterion, episode,
                                          args.max_converge, args.suffix))
                result.update(metrics([json.loads((directory / (label + ".json")).read_text())
                                       for label in ("cold", "hot")], command_before, command_after, duration))
                result["occupancy"] = occupancy(sampler.samples, stimulus, end, owners[0])
                result["coord_busy"] = result["occupancy"]["coord_busy"]
                result["coordinator_latency"] = None
                result["coordinator_latency_reason"] = "memtier aggregate histograms do not identify connection owners after migration"
                cpu_rows = [s for s in sampler.samples if stimulus <= s["t"] <= end]
                result["cpu"] = {key + "_delta": cpu_rows[-1][key] - cpu_rows[0][key]
                                 for key in ("process_cpu_ticks", "monitor_cpu_ticks")}
                result["cpu"]["clock_ticks_per_second"] = os.sysconf("SC_CLK_TCK")
            sampler.close()  # observer must close BEFORE boot() reaps the server
    except Exception as error:
        result.update(status="FAIL", reason=str(error))
    finally:
        if sampler:
            try:
                sampler.close()
            except Exception as error:
                result.update(status="FAIL", reason=str(error))
        directory.mkdir(parents=True, exist_ok=True)
        save_json(directory / "run.json", result)
    if not calibration:
        def fmt(key):
            value = result.get(key)
            return "NA" if value is None else f"{value:.6f}" if isinstance(value, float) else str(value)
        row = f"LBPLANNER-EPISODE {episode} {mode} {arm} r{round_no} " + " ".join(
            f"{key}={fmt(key)}" for key in ("t_converge", "key_moves", "client_moves", "gathers",
                                          "suffix_moves", "rate", "p99", "coord_busy"))
        print(row, flush=True)
        print(f"{name}: {result['status']} {result.get('reason', '')}", flush=True)
        with (args.output / "rows.txt").open("a") as stream:
            stream.write(row + "\n")
    return result


def schedule():
    for episode in ("key-skew", "client-skew"):
        for mode in ("1s", "2s"):
            for number in range(1, 4):
                order = ("PRE", "PAD-A", "POST") if number % 2 else ("POST", "PAD-A", "PRE")
                for arm in order:
                    yield arm, mode, episode, number


def assess(results):
    checks = []
    for post in (r for r in results if r["arm"] == "POST"):
        pre = next(r for r in results if r["arm"] == "PRE" and
                   all(r[k] == post[k] for k in ("episode", "mode", "round")))
        reasons = []
        if pre["status"] != "PASS" or post["status"] != "PASS":
            reasons.append("PRE or POST episode did not establish convergence and a stationary suffix")
        else:
            for key in ("t_converge", "key_moves", "client_moves", "total_moves", "suffix_moves", "p99"):
                if post[key] > pre[key]:
                    reasons.append(f"POST {key} exceeds PRE")
            if post["rate"] < pre["rate"]:
                reasons.append("POST rate below PRE")
        checks.append({"episode": post["episode"], "mode": post["mode"], "round": post["round"],
                       "status": "FAIL" if reasons else "PASS", "reasons": reasons})
    return {"status": "PASS" if len(checks) == 12 and all(c["status"] == "PASS" for c in checks)
            and all(r["status"] == "PASS" for r in results) else "FAIL", "checks": checks,
            "rule": "POST converges no slower than PRE, makes no more key/client/total moves, and loses no rate or p99; every paired round must pass",
            "pad_kind": "A: PRE behaviour with candidate text size/layout; diagnostic control, no placement claim without mainline null",
            "rate_tail_tolerance": "none; no arm-dependent or invented noise allowance"}


def dry_run(args):
    def command(argv):
        print(shlex.join(argv))
    print("# DRY RUN: no processes, sockets or output files are created")
    for arm, (path, sha) in ARMS.items():
        print(f"# SHA256 REQUIRED {arm} {sha} {ROOT / path}")
    command(["cc", "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror", "-o",
             str(args.output / "owner-select.so"), str(args.output / "owner-select.c"), "-ldl"])
    seed = args.output / "seed"
    command(server_command(args, "PRE", "1s", seed))
    command(load_command(args, seed, "populate", 1, KEYS, populate=True))
    print(f"# RESP 127.0.0.1:{args.port}: INFO SERVER, INFO LB, DEBUG LBSIGNALS, DBSIZE;")
    print(f"# DEBUG SHARDS memtier-1 ... memtier-{args.hotmax} in batches of 128; SAVE")
    jobs = [("PRE", mode, "balanced", attempt) for mode in ("1s", "2s") for attempt in range(1, 4)] + list(schedule())
    for arm, mode, episode, number in jobs:
        directory = args.output / f"{episode}-{mode}-{arm}-r{number}"
        owners = list(range(16 if mode == "1s" else 12))
        if episode == "balanced" and number > 1:
            print("# CONDITIONAL: only if preceding calibration failed to arm; fresh snapshot/server, bounded to 3")
        print(f"# {directory.name}: copy shared seed; verify hash/key map/actual owner IDs")
        command(server_command(args, arm, mode, directory))
        print("# RESP: INFO SERVER (owned PID); DEBUG SHARDS; INFO LB + DEBUG LBSIGNALS every 100 ms")
        print("# Selector RESP per connection attempt: DEBUG IO-THREAD (<=512 fresh sockets); actual IO IDs come from boot")
        for label in ("baseline-a", "baseline-b"):
            command(load_command(args, directory, label, 1, KEYS, args.warm + args.baseline + 3, owners=owners))
        if episode != "balanced":
            print("# RESP: INFO COMMANDSTATS before/after both complete post-stimulus generators")
            ranges = [(args.hotmax + 1, KEYS), (1, args.hotmax)] if episode == "key-skew" else [(1, KEYS)] * 2
            for label, (low, high) in zip(("cold", "hot"), ranges):
                targets = owners[:2] if episode == "client-skew" and label == "hot" else owners
                command(load_command(args, directory, label, low, high,
                                     int(args.max_converge + DECISION_SECONDS + args.suffix + 3), owners=targets))
        print("# stop sampler; SIGTERM owned server process group; wait (SIGKILL only on timeout)")
    print(f"# nominal load time {wall_seconds(args) / 60:.1f} minutes + population/boot/SAVE/connection setup")


def wall_seconds(args):
    return 38 * (args.warm + args.baseline + 3) + 36 * (args.max_converge + DECISION_SECONDS + args.suffix + 3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--self-test", action="store_true")
    action.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "build/lbplanner-episodes")
    parser.add_argument("--memtier", default="memtier_benchmark")
    parser.add_argument("--port", type=int, default=7931)
    parser.add_argument("--hotmax", type=int, default=int(os.environ.get("HOTMAX", "2000")))
    parser.add_argument("--warm", type=int, default=30)
    parser.add_argument("--baseline", type=int, default=12)
    parser.add_argument("--max-converge", type=int, default=180)
    parser.add_argument("--suffix", type=int, default=30)
    parser.add_argument("--rate-per-client", type=int, default=0,
                        help="0: stationary driver's closed loop; positive: same fixed memtier cap for every arm")
    args = parser.parse_args()
    if args.self_test:
        return 0 if unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SelfTest)).wasSuccessful() else 1
    args.output = args.output.resolve()
    require(args.warm >= 30 and args.baseline >= 12, "keep warm >=30 s and baseline >=12 s")
    require(args.max_converge >= DECISION_SECONDS and args.suffix >= DECISION_SECONDS,
            "convergence and suffix must each cover a decision window")
    require(1 <= args.hotmax < KEYS and 0 < args.port < 65536 and args.rate_per_client >= 0, "invalid workload argument")
    if args.dry_run:
        dry_run(args)
        return 0
    require(not args.output.exists(), "output must be new; never overwrite or cherry-pick prior trials")
    require("LD_PRELOAD" not in os.environ, "unset inherited LD_PRELOAD before a matched measurement")
    for arm, (relative, expected) in ARMS.items():
        path = ROOT / relative
        require(path.is_file() and os.access(path, os.X_OK) and digest(path) == expected,
                f"{arm} binary differs from frozen lbplanner receipt; do not silently rebind SHA")
    memtier = shutil.which(args.memtier)
    require(memtier is not None, "memtier executable missing")
    args.memtier = str(Path(memtier).resolve())
    require(set(range(0, 16)) | set(range(64, 96)) <= os.sched_getaffinity(0), "required server/load CPUs unavailable")
    os.sched_setaffinity(0, range(64, 96))
    args.output.mkdir(parents=True)
    (args.output / "owner-select.c").write_text(SELECTOR_C)
    compile_argv = ["cc", "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror", "-o",
                    str(args.output / "owner-select.so"), str(args.output / "owner-select.c"), "-ldl"]
    subprocess.run(compile_argv, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    manifest = {"arms": ARMS, "pad_kind": "A: PRE behaviour with POST text size/layout",
                "config": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                "schedule": list(schedule()), "memtier_sha256": digest(args.memtier),
                "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in
                                  (Path(__file__), ROOT / "tests/_lib.py", ROOT / "tests/abba_workloads.py")},
                "selector_sha256": digest(args.output / "owner-select.so"),
                "expected_load_seconds": wall_seconds(args), "started_unix": time.time()}
    save_json(args.output / "manifest.json", manifest)
    seed, seed_record = prepare_seed(args)
    criteria = {}
    for mode in ("1s", "2s"):
        for attempt in range(1, 4):
            calibration = run_episode(args, "PRE", mode, "balanced", attempt, seed, seed_record)
            if calibration["status"] == "PASS":
                break
            print(f"PRE balanced {mode} fresh-state attempt {attempt}/3: {calibration.get('reason')}", flush=True)
        require(calibration["status"] == "PASS", f"PRE balanced {mode} never armed after 3 fresh-state attempts: {calibration.get('reason')}")
        criteria[mode] = calibration["criterion"]
    save_json(args.output / "criteria.json", criteria)
    results = []
    for arm, mode, episode, number in schedule():
        # Revalidate bytes before EVERY boot; paths alone are not an identity claim.
        require(digest(ROOT / ARMS[arm][0]) == ARMS[arm][1], "binary changed during campaign")
        results.append(run_episode(args, arm, mode, episode, number, seed, seed_record, criteria[mode]))
        save_json(args.output / "results.json", results)
    report = assess(results)
    save_json(args.output / "report.json", report)
    print("LBPLANNER-VERDICT " + report["status"] + ": " + report["rule"])
    return 0 if report["status"] == "PASS" else 1


class SelfTest(unittest.TestCase):
    @staticmethod
    def sample(t, spread=1, key=0, client=0, gathers=0):
        info = {name: 0 for name in FIELDS}
        info.update({TICKS: int(t), KEY: key, CLIENT: client, GATHERS: gathers,
                     **{k: spread for k in SPREADS}})
        return {"t": t, "info": info, "signals": {"threads": {0: {
            "role": "fused", "busy_ns": int(t * 800), "idle_ns": int(t * 200),
            "cpu_ns": int(t * 900), "ops": int(t * 100)}}}}

    def trace(self, end=40, moving=True, excursion=True):
        return [self.sample(i / 10, 10 if excursion and 150 <= i < 200 else 1,
                            int(moving and i >= 180), int(moving and i >= 180),
                            int(moving and i >= 170)) for i in range(end * 10 + 1)]

    def criterion(self):
        return envelope(self.trace()[:130])

    def test_converges_and_counts_separately(self):
        for episode in ("key-skew", "client-skew"):
            result = convergence(self.trace(), 14, 40, self.criterion(), episode, 20, 3)
            self.assertEqual(result["status"], "PASS")
            self.assertAlmostEqual(result["t_converge"], 6.9)
            self.assertEqual((result["key_moves"], result["client_moves"], result["total_moves"]), (1, 1, 2))
            self.assertEqual(result["suffix_moves"], 0)

    def test_unarmed_and_no_move_fail(self):
        for kwargs in ({"moving": False}, {"excursion": False}):
            result = convergence(self.trace(**kwargs), 14, 40, self.criterion(), "key-skew", 20, 3)
            self.assertEqual(result["status"], "FAIL")
            self.assertIsNone(result["t_converge"])

    def test_suffix_move_and_truncation_fail(self):
        trace = self.trace()
        for s in trace:
            if s["t"] >= 30:
                s["info"][CLIENT] += 1
        self.assertEqual(convergence(trace, 14, 40, self.criterion(), "key-skew", 20, 3)["suffix_moves"], 1)
        self.assertEqual(convergence(trace, 14, 24, self.criterion(), "key-skew", 20, 3)["status"], "FAIL")

    def test_duplicate_ticks_and_reset(self):
        trace = self.trace()
        self.assertEqual(len(beats(trace)), 40)
        trace[22]["info"][TICKS] = 0
        with self.assertRaises(ValueError):
            beats(trace)
        with self.assertRaises(ValueError):
            envelope(self.trace()[:30])
        with self.assertRaises(ValueError):
            beats(self.trace()[::20])

    def test_envelope_frozen_and_baseline_motion_refused(self):
        criterion = self.criterion()
        trace = self.trace()
        for s in trace:
            if s["t"] >= 20:
                s["info"][SPREADS[0]] = 2
        self.assertEqual(convergence(trace, 14, 40, criterion, "key-skew", 20, 3)["status"], "FAIL")
        self.assertEqual(criterion["upper"][SPREADS[0]], 1)
        with self.assertRaises(ValueError):
            envelope(self.trace()[150:300])

    def test_info_parsing(self):
        raw = b"# LB\r\ntomokv_keylb_enabled:1\r\ntomokv_clientlb_enabled:1\r\n" + b"".join(
            f"{k}:1\r\n".encode() for k in FIELDS)
        self.assertEqual(parse_info(raw)[KEY], 1)
        for broken in (raw.replace((KEY + ":1\r\n").encode(), b""), raw + b"tomokv_keylb_ticks:1\r\n",
                       raw.replace((SPREADS[0] + ":1").encode(), (SPREADS[0] + ":nan").encode())):
            with self.assertRaises(ValueError):
                parse_info(broken)

    def test_signals_parsing_and_coordinator(self):
        raw = ("lbver 1 stamp_ns 42\nthread 0 fused " + " ".join(["0"] * 20) +
               "\nshard 0 0 0 100 0 0 4 256\nderived thread_mode 1s client_threads 1\n").encode()
        self.assertEqual(parse_signals(raw)["shards"][0]["ops"], 100)
        with self.assertRaises(ValueError):
            parse_signals(raw.replace(b"lbver 1", b"lbver 2"))
        self.assertEqual(occupancy(self.trace(), 1, 10, 0)["coord_busy"], 80)

    def test_orders_and_sha_pins(self):
        jobs = list(schedule())
        self.assertEqual(len(jobs), 36)
        self.assertEqual([j[0] for j in jobs[:9]], ["PRE", "PAD-A", "POST", "POST", "PAD-A", "PRE", "PRE", "PAD-A", "POST"])
        self.assertTrue(all(len(sha) == 64 for _, sha in ARMS.values()))

    def test_comparison_cannot_hide_one_bad_metric(self):
        results = [dict(arm=a, mode=m, episode=e, round=r, status="PASS", t_converge=4,
                        key_moves=2, client_moves=3, total_moves=5, suffix_moves=0, rate=100, p99=1)
                   for a, m, e, r in schedule()]
        self.assertEqual(assess(results)["status"], "PASS")
        results[2]["client_moves"] += 1
        results[2]["key_moves"] -= 1
        self.assertEqual(assess(results)["status"], "FAIL")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print("LBPLANNER-ERROR " + str(error), file=sys.stderr)
        sys.exit(1)
