#!/usr/bin/env python3
"""Mainline-only EX1/EX3/EX6 directed measurements (never part of the gate).

The inventory is executable input, not a second transcription of the recipes.
--self-test opens no sockets; it builds a native preload fixture and, when perf
is available, checks a local busy loop on CPUs 112-127.
--dry-run only executes memtier --help, as a required grammar
check; all workload commands are printed.
Normal invocation owns/reaps its children, boots fresh state for EVERY sample,
and retains failed samples. See MEASURE-REQUEST-exbatch-bench.md for scopes.
--arms replaces the frozen table with a path+SHA256 receipt; PRE and POST are
required, while absent controls are reported as not available. See
MEASURE-REQUEST-exbatch-bench4.md for lane versus landed-mainline framing.
--score matched-only requires --matched-load (aggregate offered frames/s),
skips plateau passes, and checks PRE matched cyc/op repeatability instead.
"""
from __future__ import annotations

import argparse
from collections import Counter
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import signal
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from _lib import Conn, RespError, encode
from abba_workloads import decode_histogram, percentile, command_stat
from abba_saturation import parse_snapshot, bottleneck_saturation, SATURATION_FLOOR
from gate_quiet import QuietMonitor

INVENTORY = ROOT / "docs/exbatch/measurement-cells.json"
RECEIPTS = ROOT / "docs/exbatch/binaries.json"
MAINLINE_RECEIPT = ROOT / "docs/exbatch/mainline-arms.json"
MEMTIER = "/usr/bin/memtier_benchmark"
ARMS = ("PRE", "PAD-A", "POST", "EX1-OLD", "EX3-OLD", "EX6-OLD")
BASES = ("exbatch_watch_w32", "exbatch_hz32", "exbatch_object32",
         "exbatch_xgroup32", "exbatch_publish_poll32")
REGIMES = ("f0", "f1", "s0")
PARTIAL = dict(zip(BASES, ("EX3-OLD", "EX3-OLD", "EX6-OLD", "EX6-OLD", "EX1-OLD")))
WINDOW, WARMUP, TAIL = 20, 3, 5
CONNECTIONS, PIPELINE = 512, 32
BOUND = CONNECTIONS * PIPELINE
DEFAULT_CORES = ("0-7", "8-111")
REQUIRED_OPTIONS = ("command", "command-ratio", "command-key-pattern", "transaction",
                    "rate-limiting", "json-out-file", "distinct-client-seed",
                    "pipeline", "test-time", "key-minimum", "key-maximum")

# Stock memtier counts arbitrary replies but does not export integer VALUES.
# Interpose only the XGROUP generators' receive calls, on their existing CPUs.
# Connections still go directly to the exact server/port; no proxy, extra client,
# MONITOR in the timed run, or changed command grammar. A missing hook fails the
# exact guard/HDR count reconciliation. Per-FD state avoids a shared hot counter.
# MAINLINE compiles this before measurement; --self-test compiles a memory-only
# fixture on CPUs 112-127. --dry-run never compiles it.
ZERO_REPLY_GUARD = r'''
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <unistd.h>

#define FDS 65536
struct state { unsigned long long bytes; unsigned phase, active; char pad[48]; };
static struct state states[FDS];
static _Atomic unsigned long long closed_bytes, connections;
static const char *receipt_path;
static int (*next_connect)(int, const struct sockaddr *, socklen_t);
static int (*next_close)(int);
static ssize_t (*next_read)(int, void *, size_t);
static ssize_t (*next_readv)(int, const struct iovec *, int);
static ssize_t (*next_recv)(int, void *, size_t, int);
static ssize_t (*next_recvfrom)(int, void *, size_t, int, struct sockaddr *, socklen_t *);
static ssize_t (*next_recvmsg)(int, struct msghdr *, int);

static void die(const char *why) {
    static const char prefix[] = "EXBATCH ZERO-REPLY GUARD FAILED: ";
    (void)!write(2, prefix, sizeof(prefix)-1);
    (void)!write(2, why, strlen(why));
    (void)!write(2, "\n", 1);
    _exit(86);
}
static void *resolve(const char *name) {
    void *p = dlsym(RTLD_NEXT, name);
    if (!p) die("missing libc receive symbol");
    return p;
}
__attribute__((constructor)) static void init(void) {
    next_connect = resolve("connect"); next_close = resolve("close");
    next_read = resolve("read"); next_readv = resolve("readv");
    next_recv = resolve("recv"); next_recvfrom = resolve("recvfrom");
    next_recvmsg = resolve("recvmsg");
    receipt_path = getenv("EXBATCH_ZERO_RECEIPT");
    if (!receipt_path) die("missing receipt path");
    /* LD_PRELOAD also runs this constructor in taskset, before it execs
       memtier. Do not create the exclusive receipt until the receiving
       process finishes: a launcher must not reserve its child's path. */
}
static void retire(int fd) {
    if (fd < 0 || fd >= FDS || !states[fd].active) return;
    if (states[fd].phase) die("truncated integer reply at close");
    atomic_fetch_add_explicit(&closed_bytes, states[fd].bytes, memory_order_relaxed);
    states[fd].active = 0;
}
static void consume(int fd, const void *buffer, ssize_t length) {
    if (length <= 0 || fd < 0 || fd >= FDS || !states[fd].active) return;
    const unsigned char *p = buffer;
    size_t n = (size_t)length;
    static const unsigned char expected[4] = {':', '0', '\r', '\n'};
    struct state *s = &states[fd];
    s->bytes += n;
    while (n && s->phase) {
        if (*p++ != expected[s->phase]) die("XGROUP reply was not :0 CR LF");
        s->phase = (s->phase + 1) & 3; --n;
    }
    while (n >= 4) {
        if (memcmp(p, expected, 4)) die("XGROUP reply was not :0 CR LF");
        p += 4; n -= 4;
    }
    while (n--) {
        if (*p++ != expected[s->phase]) die("XGROUP reply was not :0 CR LF");
        s->phase = (s->phase + 1) & 3;
    }
}
int connect(int fd, const struct sockaddr *address, socklen_t length) {
    if (!next_connect) next_connect = resolve("connect");
    int target = address && ((address->sa_family == AF_INET && length >= sizeof(struct sockaddr_in) &&
        ntohs(((const struct sockaddr_in *)address)->sin_port) == 18179) ||
        (address->sa_family == AF_INET6 && length >= sizeof(struct sockaddr_in6) &&
        ntohs(((const struct sockaddr_in6 *)address)->sin6_port) == 18179));
    if (target) {
        if (fd < 0 || fd >= FDS || states[fd].active) die("unsupported/reused socket FD");
        states[fd].bytes = 0; states[fd].phase = 0; states[fd].active = 1;
        atomic_fetch_add_explicit(&connections, 1, memory_order_relaxed);
    }
    return next_connect(fd, address, length);
}
int close(int fd) {
    if (!next_close) next_close = resolve("close");
    retire(fd); return next_close(fd);
}
ssize_t read(int fd, void *buffer, size_t n) {
    if (!next_read) next_read = resolve("read");
    ssize_t result = next_read(fd, buffer, n); consume(fd, buffer, result); return result;
}
ssize_t recv(int fd, void *buffer, size_t n, int flags) {
    if (!next_recv) next_recv = resolve("recv");
    ssize_t result = next_recv(fd, buffer, n, flags);
    if (!(flags & MSG_PEEK)) consume(fd, buffer, result);
    return result;
}
ssize_t recvfrom(int fd, void *buffer, size_t n, int flags, struct sockaddr *a, socklen_t *length) {
    if (!next_recvfrom) next_recvfrom = resolve("recvfrom");
    ssize_t result = next_recvfrom(fd, buffer, n, flags, a, length);
    if (!(flags & MSG_PEEK)) consume(fd, buffer, result);
    return result;
}
static void consume_iov(int fd, const struct iovec *iov, size_t count, ssize_t total) {
    for (size_t i = 0; total > 0 && i < count; ++i) {
        ssize_t n = (size_t)total < iov[i].iov_len ? total : (ssize_t)iov[i].iov_len;
        consume(fd, iov[i].iov_base, n); total -= n;
    }
}
ssize_t readv(int fd, const struct iovec *iov, int count) {
    if (!next_readv) next_readv = resolve("readv");
    ssize_t result = next_readv(fd, iov, count); consume_iov(fd, iov, (size_t)count, result); return result;
}
ssize_t recvmsg(int fd, struct msghdr *msg, int flags) {
    if (!next_recvmsg) next_recvmsg = resolve("recvmsg");
    ssize_t result = next_recvmsg(fd, msg, flags);
    if (!(flags & MSG_PEEK)) consume_iov(fd, msg->msg_iov, msg->msg_iovlen, result);
    return result;
}
__attribute__((destructor)) static void finish(void) {
    for (int fd = 0; fd < FDS; ++fd) retire(fd);
    unsigned long long bytes = atomic_load(&closed_bytes), clients = atomic_load(&connections);
    if (!clients || !bytes || bytes % 4) die("no verified complete replies");
    int receipt = open(receipt_path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (receipt < 0) die("cannot create receipt");
    char text[256];
    int n = snprintf(text, sizeof(text), "{\"connections\":%llu,\"bytes\":%llu,\"zero_replies\":%llu}\n",
                     clients, bytes, bytes / 4);
    if (write(receipt, text, (size_t)n) != n) die("receipt write failed");
    next_close(receipt);
}
'''

ZERO_REPLY_UNIT = r'''
int guard_unit(const char *mode) {
    if (!strcmp(mode, "empty")) return 0;
    atomic_store(&connections, 1);
    states[64000].active = 1; /* memory-only parser fixture, no socket */
    if (!strcmp(mode, "bad")) consume(64000, ":1\r\n", 4);
    else if (!strcmp(mode, "error")) consume(64000, "-ERR\r\n", 6);
    else if (!strcmp(mode, "partial")) consume(64000, ":0\r", 3);
    else {
        const char good[] = ":0\r\n:0\r\n:0\r\n";
        for (int chunk = 1; chunk <= 12; ++chunk)
            for (int at = 0; at < 12; at += chunk)
                consume(64000, good + at, chunk < 12-at ? chunk : 12-at);
        char one[] = ":0", two[] = "\r\n:0\r\n";
        struct iovec vec[] = {{one, 2}, {two, 6}};
        consume_iov(64000, vec, 2, 8);
    }
    return 0;
}
int main(int argc, char **argv) {
    return argc == 2 ? guard_unit(argv[1]) : 2;
}
'''


def guard_build_argv(folder, unit=False, cores=DEFAULT_CORES):
    name = "guard-unit" if unit else "zero-reply"
    return ["taskset", "-c", "8-23" if cores == DEFAULT_CORES else cores[1], "cc", "-std=c11", "-O2", *([] if unit else ["-shared", "-fPIC"]),
            "-Wall", "-Wextra", "-Werror", "-o", str(folder / (name if unit else name + ".so")),
            str(folder / (name + ".c")), "-ldl"]


def prepare_guard(folder, cores=DEFAULT_CORES):
    folder.mkdir()
    (folder / "zero-reply.c").write_text(ZERO_REPLY_GUARD)
    (folder / "guard-unit.c").write_text(ZERO_REPLY_GUARD + ZERO_REPLY_UNIT)
    with (folder / "build.log").open("wb") as log:
        subprocess.run(guard_build_argv(folder, cores=cores), check=True, stdout=log, stderr=subprocess.STDOUT)
        subprocess.run(guard_build_argv(folder, unit=True, cores=cores), check=True, stdout=log, stderr=subprocess.STDOUT)
    controls = []
    for mode in ("good", "bad", "error", "partial", "empty"):
        receipt = folder / (mode + ".json")
        proc = subprocess.run(["taskset", "-c", str(cpu_ids(cores[1]).start), str(folder / "guard-unit"), mode],
                              env={**os.environ, "EXBATCH_ZERO_RECEIPT": str(receipt)},
                              capture_output=True, text=True, timeout=10)
        require(proc.returncode == (0 if mode == "good" else 86), "native guard positive/negative control failed: " + mode)
        if mode == "good":
            check_zero_receipt(receipt, 38, 1)
        else:
            require("EXBATCH ZERO-REPLY GUARD FAILED:" in proc.stderr, "native guard negative control did not fire")
        controls.append(dict(mode=mode, exit_status=proc.returncode, stderr=proc.stderr))
    save(folder / "unit-checks.json", controls)
    return dict(path=str(folder / "zero-reply.so"), sha256=digest(folder / "zero-reply.so"),
                source_sha256=digest(folder / "zero-reply.c"), build_argv=guard_build_argv(folder, cores=cores),
                unit_sha256=digest(folder / "guard-unit"), unit_checks=controls)


def guard_environment(guard, folder, label):
    require(guard is not None, "XGROUP scored replies require the native receive guard")
    return {"LD_PRELOAD": guard["path"], "EXBATCH_ZERO_RECEIPT": str(folder / f"{label}-zero.json")}


def check_zero_receipt(path, completed, connections):
    receipt = json.loads(Path(path).read_text())
    require(all(type(value) is int for value in receipt.values()), "non-integer XGROUP guard counter")
    require(receipt == dict(connections=connections, bytes=4 * completed, zero_replies=completed),
            "XGROUP zero-reply guard / completed HDR counts differ; missing hook or nonzero reply")
    return receipt


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def file_evidence(folder, names):
    """Bounded, failure-only reads; never collect extra traffic on the server."""
    result = {}
    for name in names:
        path = folder / name
        try:
            with path.open("rb") as stream:
                size = stream.seek(0, os.SEEK_END)
                stream.seek(max(0, size - 2048))
                result[name] = dict(bytes=size, tail=stream.read().decode("utf-8", "replace"))
        except OSError as error:
            result[name] = dict(unavailable=str(error))
    return result


class StepFailure(RuntimeError):
    pass


class Diagnostics:
    def __init__(self, folder, scope):
        self.folder, self.scope = folder, scope
        self.started = time.monotonic()
        self.steps = []
        self.step("starting")

    def step(self, name, **evidence):
        now = time.monotonic()
        if self.steps:
            self.steps[-1]["seconds"] = now - self.steps[-1]["started"]
        self.current = dict(step=name, started=now, evidence=evidence)
        self.steps.append(self.current)

    def failure(self, error, **evidence):
        now = time.monotonic()
        self.current["seconds"] = now - self.current["started"]
        detail = dict(scope=self.scope, step=self.current["step"],
                      elapsed_seconds=self.current["seconds"], total_seconds=now - self.started,
                      error=f"{type(error).__name__}: {error}", steps=self.steps,
                      evidence={**self.current["evidence"], **evidence})
        path = self.folder / f"{self.scope}-failure.json"
        save(path, detail)
        return StepFailure(f"{self.scope}/{detail['step']} failed after {detail['elapsed_seconds']:.3f}s "
                           f"(total {detail['total_seconds']:.3f}s): {detail['error']}; "
                           f"partial evidence={json.dumps(detail['evidence'], sort_keys=True)}; receipt={path}")


def cpu_ids(spec):
    low, high = map(int, spec.split("-"))
    return range(low, high + 1)


def parse_cores(value):
    if not re.fullmatch(r"\d+-\d+,\d+-\d+", value):
        raise argparse.ArgumentTypeError("--cores requires SERVER_RANGE,LOAD_RANGE (e.g. 112-119,120-127)")
    server, load = value.split(",")
    s0, s1 = map(int, server.split("-"))
    l0, l1 = map(int, load.split("-"))
    if s1 - s0 != 7 or l1 - l0 < 7 or max(s0, l0) <= min(s1, l1):
        raise argparse.ArgumentTypeError("--cores requires 8 server CPUs and at least 8 disjoint load CPUs")
    return (f"{s0}-{s1}", f"{l0}-{l1}")


def cell_cores(cell):
    return tuple(cell.get("cores", DEFAULT_CORES))


def configure_cores(cells, cores):
    if cores == DEFAULT_CORES:
        return  # Keep the frozen default recipes byte-for-byte.
    for cell in cells.values():
        cell["cores"] = cores
        cell["server_argv"][2] = cores[0]
        cpus = cpu_ids(cores[1])
        # Keep a dedicated poll CPU when possible; with eight load CPUs the
        # observer shares the final instance's CPU. Client/thread counts stay fixed.
        if cell["id"].startswith(BASES[-1]) and len(cpus) > 8:
            cpus = cpus[:-1]
        for i, item in enumerate(cell["memtier_instances"]):
            part = cpus[i * len(cpus) // 8:(i + 1) * len(cpus) // 8]
            item["argv"][2] = str(part[0]) if len(part) == 1 else f"{part[0]}-{part[-1]}"


def matched_q(load):
    q = math.floor(load / CONNECTIONS)
    require(q > 0, "matched load too low for a positive common q (at least 512 frames/s)")
    return q


def inventory():
    document = json.loads(INVENTORY.read_text())
    cells = {c["id"]: c for c in document["custom"]}
    require(set(cells) == {f"{b}_{r}" for b in BASES for r in REGIMES}, "directed inventory changed")
    require((document["central_window_seconds"], document["warmup_seconds"], document["tail_seconds"])
            == (WINDOW, WARMUP, TAIL), "gate timing changed")
    for cell in cells.values():
        base, regime = cell["id"].rsplit("_", 1)
        require(cell["connections"] == CONNECTIONS and cell["pipeline"] == PIPELINE and
                cell["instances"] == len(cell["memtier_instances"]) == 8, "geometry changed")
        srv = cell["server_argv"]
        require(srv[:4] == ["taskset", "-c", "0-7", "{ARM}"], "server placement changed")
        options = dict(zip(srv[4::2], srv[5::2]))
        expected = {"--bind": "127.0.0.1", "--port": "18179", "--net-io": "uring", "--shards": "16",
                    "--atomic": "1", "--reorder": "0", "--key-lb": "1",
                    "--client-lb": "1", "--flip-auto": "0", "--save": "", "--appendonly": "no",
                    "--enable-debug-command": "yes", "--databases": "1", "--dir": "{RUN_DIR}",
                    "--thread-mode": "2s" if regime == "s0" else "1s",
                    "--read-local": "1" if regime == "f1" else "0"}
        if regime == "s0":
            expected["--ratio"] = "6:2"
        require(options == expected and len(srv) == 4 + 2 * len(expected), "server argv changed")
        previous = 0
        for i, item in enumerate(cell["memtier_instances"]):
            argv = item["argv"]
            high_cpu = 110 if base == BASES[-1] and i == 7 else 20 + 13 * i
            require(argv[:4] == ["taskset", "-c", f"{8 + 13 * i}-{high_cpu}", MEMTIER], "load placement changed")
            require(item["instance"] == i and item["key_min"] == previous + 1, "key ranges overlap/gap")
            require(item["key_max"] - item["key_min"] + 1 == cell["workload"]["keyspace"] // 8,
                    "unequal key ranges")
            previous = item["key_max"]
            require(not any(a.startswith("--key-pattern") for a in argv), "native key-pattern on arbitrary commands")
            require(argv[argv.index("-t") + 1] == argv[argv.index("-c", 4) + 1] == "8", "load threads/clients changed")
            for option in ("--test-time=28", "--pipeline=32", f"--key-minimum={item['key_min']}",
                           f"--key-maximum={item['key_max']}"):
                require(option in argv, "missing recipe option " + option)
            commands = [a.split("=", 1)[1] for a in argv if a.startswith("--command=")]
            require(commands == cell["workload"]["commands"], "command rotation changed")
            for j, a in enumerate(argv):
                if a.startswith("--command="):
                    require(argv[j + 1:j + 3] == ["--command-ratio=1", "--command-key-pattern=P"],
                            "each arbitrary command needs ratio 1 and P")
            require(("--transaction" in argv) == cell["workload"]["transaction"], "transaction grammar changed")
        require(previous == cell["workload"]["keyspace"], "incomplete keyspace")
    return cells


def server_argv(cell, binary, folder):
    return [s.replace("{ARM}", str(binary)).replace("{RUN_DIR}", str(folder)) for s in cell["server_argv"]]


def load_argv(cell, index, folder, q=None):
    result = [s.replace("{RUN_DIR}", str(folder)) for s in cell["memtier_instances"][index]["argv"]]
    if q is not None:
        result += [f"--rate-limiting={q}"]
    return result


def probe_argv(cell, folder):
    # Unscored two-rotation wire witness, using the SAME command/affix grammar.
    argv = load_argv(cell, 0, folder)
    argv[argv.index("-t") + 1] = "1"
    argv[argv.index("-c", 4) + 1] = "1"
    return [f"--requests={2 * cell['workload']['cycle_frames']}" if x == "--test-time=28"
            else x.replace("load-0.json", "wire-probe.json") for x in argv]


def worker_argv(kind, cell, folder, index=None):
    cores = cell_cores(cell)
    cpu = str(cpu_ids(cores[1])[-1]) if kind == "poll" else (cell["memtier_instances"][index]["argv"][2] if index is not None else str(cpu_ids(cores[1])[0]))
    result = ["taskset", "-c", cpu, sys.executable, str(Path(__file__).resolve()),
              "--worker", kind, "--cell", cell["id"], "--output", str(folder)]
    return (result + (["--instance", str(index)] if index is not None else []) +
            (["--cores", ",".join(cores)] if cores != DEFAULT_CORES else []))


def perf_argv(folder, cores=DEFAULT_CORES):
    # IPC is instructions / cycles from this group, never a separately sampled metric.
    return ["taskset", "-c", str(cpu_ids(cores[1])[0]), "perf", "stat", "-a", "-A", "-C", cores[0], "-x", ",",
            "--no-big-num", "--no-scale", "-e", "{cycles,instructions}", "--delay=-1",
            f"--control=fifo:{folder / 'perf.ctl'},{folder / 'perf.ack'}",
            "--timeout", "40000", "-o", str(folder / "perf.csv")]


def check_help(text):
    missing = [x for x in REQUIRED_OPTIONS if not re.search(r"--" + re.escape(x) + r"(?:[=\s]|$)", text)]
    require(not missing, "MEMTIER GRAMMAR MISSING: " + ", ".join("--" + x for x in missing))
    require("individual connection" in text and "rotation" in text and "same key" in text,
            "memtier help does not document per-connection rate / same-key transaction rotation")


def memtier_identity():
    # --help exits 2 in this installed 2.5.1 build; inspect the grammar, not that status.
    before = digest(MEMTIER)
    proc = subprocess.run([MEMTIER, "--help"], capture_output=True, text=True, timeout=10)
    help_text = proc.stdout + proc.stderr
    check_help(help_text)
    expected = json.loads(INVENTORY.read_text())["memtier"]["sha256"]
    require(before == digest(MEMTIER) == expected, "memtier changed: re-audit grammar/schema and freeze inventory")
    return dict(path=MEMTIER, sha256=before, help_sha256=hashlib.sha256(help_text.encode()).hexdigest(),
                help_exit_status=proc.returncode, version="2.5.1, bound by inventory SHA256", help=help_text)


def rows_for(stats, name):
    found = [v for k, v in stats.items() if k.upper() in (name, name + "S")]
    require(len(found) == 1, f"expected one memtier row for {name}")
    return found[0]


def parse_memtier(path, cell, log):
    data = json.loads(Path(path).read_text())
    stats = data["ALL STATS"]
    require(stats["Runtime"]["Interrupted"] in (False, "false"), "interrupted memtier")
    require(stats["Runtime"]["Time unit"] == "MILLISECONDS", "unknown memtier runtime unit")
    total = stats["Totals"]
    require(total["Connection Errors"] == 0 and total["Connection Errors/sec"] == 0, "connection errors")
    require(not re.search(r"handle error response:|\berror:|\bfailed\b", Path(log).read_text(), re.I),
            "memtier error log is nonempty (server errors are not all exported in JSON)")
    for key in ("Errors", "Errors/sec", "Aborts/sec"):
        require(float(total.get(key, 0)) == 0, f"nonzero memtier {key}")
    rotation = Counter(c.split()[0] for c in cell["workload"]["commands"])
    counts, completed, hist, bytes_rx = {}, {}, Counter(), {}
    for name in rotation:
        row = rows_for(stats, name)
        count = row["Count"]
        require(type(count) is int and count > 0, f"empty/invalid {name} Count")
        h = decode_histogram(row["Percentile Latencies"]["Histogram log format"]["Compressed Histogram"])
        counts[name], completed[name] = count, sum(h.values())
        require(completed[name] > 0, "no completed responses")
        hist.update(h)
        series = row["Time-Serie"]
        require(sum(s["Count"] for s in series.values()) == count, "Time-Serie/Count mismatch")
        bytes_rx[name] = sum(s["Bytes RX"] for s in series.values())
    require(total["Count"] == sum(counts.values()), "Totals Count differs from command sum")
    # As in gate, the end-time snapshot may omit/duplicate the final outstanding
    # bucket. Fully drained HDR counts are exact; never permit a percent error.
    bound = 64 * PIPELINE
    error = sum(abs(counts[n] - completed[n]) for n in rotation)
    require(error <= bound, f"Count/HDR difference {error} > finite bound {bound}")
    for k, v in stats.items():
        if isinstance(v, dict) and "Count" in v and k != "Totals":
            require(k.upper() in set(rotation) | {n + "S" for n in rotation} or v["Count"] == 0,
                    "unexpected command in memtier JSON")
    result = dict(counts=counts, completed=completed, count_hdr_bound=bound, count_hdr_error=error,
                  runtime=stats["Runtime"], histogram=dict(hist), bytes_rx=bytes_rx)
    if cell["id"].startswith("exbatch_watch_"):
        buckets = stats["Per-Key Misses"]
        execs = [v for k, v in buckets.items() if k.split()[0].upper() == "EXEC"]
        require(len(execs) == 1, "missing exact EXEC hit/abort counters")
        hit, miss = execs[0]["Total Hits"], execs[0]["Total Misses"]
        require(type(hit) is int and type(miss) is int and miss == 0 and hit == completed["EXEC"],
                "WATCH aborted or exact EXEC counter does not match completed responses")
        require(rows_for(stats, "EXEC")["Aborts/sec"] == 0, "EXEC abort rate is nonzero")
        # Every successful EXEC contains exactly one +OK; QUEUED belongs to SET.
        require(bytes_rx["EXEC"] == counts["EXEC"] * len(b"*1\r\n+OK\r\n"), "EXEC payload is not [OK]")
        result.update(exec_aborts=miss, committed_transactions=hit)
    if cell["id"].startswith("exbatch_publish_"):
        get_buckets = [v for k, v in stats["Per-Key Misses"].items() if k.split()[0].upper() == "GET"]
        require(len(get_buckets) == 1, "missing exact GET hit/miss counters")
        hits = get_buckets[0]
        require(hits["Total Misses"] == 0 and hits["Total Hits"] == completed["GET"], "GET missed warm keys")
    return result


def parse_perf(text, server_cpus=range(8)):
    cpus = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = [s.strip() for s in line.split(",")]
        if not fields[0].startswith("CPU"):
            continue
        require(len(fields) >= 6, "short perf CSV row")
        cpu = int(fields[0][3:])
        event = fields[3].split(":")[0]
        if event not in ("cycles", "instructions"):
            continue
        require(re.fullmatch(r"\d+(?:\.\d+)?", fields[1]) is not None, "perf counter unavailable: " + line)
        count, runtime, percent = float(fields[1]), float(fields[4]), float(fields[5].rstrip("%"))
        require(all(math.isfinite(x) and x > 0 for x in (count, runtime, percent)), "invalid perf counter")
        require(percent == 100, "multiplexed perf counter (require 100% running): " + line)
        row = cpus.setdefault(cpu, {})
        require(event not in row, "duplicate perf event")
        row[event] = count
        row[event + "_runtime_ns"] = runtime
    require(set(cpus) == set(server_cpus), "perf lacks one or more server CPUs")
    for row in cpus.values():
        require("cycles" in row and "instructions" in row, "missing grouped perf event")
        require(row["cycles_runtime_ns"] == row["instructions_runtime_ns"], "PMU numerator scopes differ")
    cycles = sum(r["cycles"] for r in cpus.values())
    instructions = sum(r["instructions"] for r in cpus.values())
    return dict(cpus=cpus, cycles=cycles, instructions=instructions, ipc=instructions / cycles)


def rate_check(rates, q):
    require(type(q) is int and q > 0, "matched q must be a positive integer")
    target = CONNECTIONS * q
    require(rates and all(math.isfinite(r) and r > 0 for r in rates), "invalid achieved rate")
    deviations = [abs(r / target - 1) for r in rates]
    require(max(deviations) <= .02 + 1e-12, f"achieved rate outside 2% of offered {target}: {rates}")
    return dict(q=q, offered_frames_per_second=target, achieved=rates,
                maximum_target_error_pct=100 * max(deviations),
                inter_arm_spread_pct=100 * (max(rates) / min(rates) - 1))


def comparisons(cell):
    return [("PRE", "POST"), ("PRE", "PAD-A"), ("PAD-A", "POST"),
            (PARTIAL[cell["id"].rsplit("_", 1)[0]], "POST")]


def arm_paths():
    return {a: ROOT / ("build/tomokv" if a == "POST" else
                       "build/exbatch/PRE/build/tomokv" if a == "PRE" else f"build/exbatch/{a}/tomokv")
            for a in ARMS}


def bind_arms(receipt=None):
    """Bind a replacement table once; relative binaries are receipt-relative."""
    path = (receipt if receipt is not None else RECEIPTS).resolve()
    raw = path.read_bytes()
    identity = dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(),
                    source="--arms" if receipt is not None else "frozen lane receipts")
    if receipt is None:
        return None, identity

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"duplicate arm receipt field: {key}")
            result[key] = value
        return result

    data = json.loads(raw, object_pairs_hook=unique)
    require(isinstance(data, dict) and {"PRE", "POST"} <= set(data) <= set(ARMS),
            "arms receipt requires PRE and POST; optional arms: PAD-A, EX1-OLD, EX3-OLD, EX6-OLD")
    table = {}
    for arm, entry in data.items():
        require(isinstance(entry, dict) and set(entry) == {"path", "sha256"},
                f"{arm} receipt must contain exactly path and sha256")
        name, sha = entry["path"], entry["sha256"]
        require(isinstance(name, str) and name and isinstance(sha, str) and
                re.fullmatch(r"[0-9a-f]{64}", sha), f"invalid {arm} path/SHA256 receipt")
        table[arm] = dict(path=str((path.parent / name).resolve()), sha256=sha)
    return table, identity


def verify_receipt(receipt):
    require(digest(receipt["path"]) == receipt["sha256"], "arms receipt changed after binding")


def arm_kind(arm):
    return ("A: PRE behaviour at POST layout" if arm == "PAD-A" else
            "A: selected old item at POST layout" if arm.endswith("OLD") else "source build")


def prepare_arms(dry=False, table=None, cores=DEFAULT_CORES):
    if table is not None:
        identities = {}
        for arm, entry in table.items():
            path = Path(entry["path"])
            require(path.is_file() and os.access(path, os.X_OK),
                    f"{arm} binary missing/not executable in explicit arms receipt: {path}")
            actual = digest(path)
            require(actual == entry["sha256"], f"{arm} SHA differs from explicit arms receipt: {path}")
            identities[arm] = dict(path=str(path), sha256=actual, expected_sha256=entry["sha256"],
                                   kind=arm_kind(arm))
        return identities
    manifest = json.loads(RECEIPTS.read_text())
    paths = arm_paths()
    expected = {r["arm"]: r["sha256"] for r in manifest["artifacts"]}
    identities = {}
    build_cpus = "0-15" if cores == DEFAULT_CORES else cores[1]
    for arm in ("PRE", "POST", "PAD-A", "EX1-OLD", "EX3-OLD", "EX6-OLD"):
        path = paths[arm]
        if not path.is_file():
            if dry:
                if arm == "PRE":
                    print(f"# git archive {manifest['pre_commit']} | tar -x -C {path.parent.parent}")
                    print(shlex.join(["taskset", "-c", build_cpus, "make", "-C", str(path.parent.parent), "-j16"]))
                elif arm == "POST":
                    print(shlex.join(["taskset", "-c", build_cpus, "make", "-C", str(ROOT), "-j16"]))
                else:
                    print(f"# reconstruct {arm} from POST and docs/exbatch/{'pad-a' if arm == 'PAD-A' else arm.lower()}/planned-retargets.json; verify frozen SHA256")
            elif arm in ("PRE", "POST"):
                source = ROOT if arm == "POST" else path.parent.parent
                if arm == "PRE":
                    require(not source.exists() or not any(source.iterdir()), "missing PRE in a nonempty archive: do not mix builds")
                    source.mkdir(parents=True, exist_ok=True)
                    archive = ROOT / "build/exbatch/pre-source.tar"
                    subprocess.run(["git", "archive", "-o", str(archive), manifest["pre_commit"]], cwd=ROOT, check=True)
                    with tarfile.open(archive) as stream:
                        stream.extractall(source, filter="data")
                subprocess.run(["taskset", "-c", build_cpus, "make", "-C", str(source), "-j16"], check=True)
            else:
                receipt = ROOT / "docs/exbatch" / ("pad-a" if arm == "PAD-A" else arm.lower())
                plan = json.loads((receipt / "planned-retargets.json").read_text())
                require(digest(paths["POST"]) == plan["source_sha256"], "PAD receipt belongs to different POST")
                raw = bytearray(paths["POST"].read_bytes())
                for patch in plan["patches"]:
                    at = patch["offset"]
                    require(raw[at:at + 5].hex() == patch["before"], "PAD control NOP missing")
                    raw[at:at + 5] = bytes.fromhex(patch["after"])
                require(hashlib.sha256(raw).hexdigest() == expected[arm], "rebuilt PAD SHA mismatch")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                path.chmod(0o755)
        actual = digest(path) if path.is_file() else None
        # PRE rebuilt from archive can differ in debug/build metadata; require
        # the frozen .text hash as well as recording its NEW whole-file hash.
        if actual is not None and actual != expected[arm]:
            require(arm == "PRE", f"{arm} SHA differs from frozen receipt; regenerate controls before scoring")
            from lbstall_artifacts import Elf
            elf = Elf(path)
            text_sha = hashlib.sha256(elf.section_data(elf.names.index(".text"))).hexdigest()
            require(text_sha == "c44b7d6be8b1bdcb941002a569e7bf6f3cf9b0cce1f3c69064ee8d7f5771d9aa",
                    "rebuilt synchronized PRE text differs from report")
            import gzip
            functions = sorted((s['name'], s['value'], s['size'], elf.names[s['sec']])
                               for s in elf.symbols if s['info'] & 15 == 2 and 0 < s['sec'] < len(elf.sections))
            table = 'symbol\taddress\tsize\tsection\n' + ''.join(
                f'{n}\t{v:016x}\t{z}\t{s}\n' for n, v, z, s in functions)
            with gzip.open(ROOT / "docs/exbatch/pre-post-identity/REFERENCE-functions.tsv.gz", "rt") as stream:
                require(table == stream.read(), "rebuilt PRE function addresses/sizes differ from report")
        identities[arm] = dict(path=str(path), sha256=actual, expected_sha256=expected[arm], kind=arm_kind(arm))
    return identities


def measurement_framing(identities, receipt):
    headline = json.loads(MAINLINE_RECEIPT.read_text())
    if set(identities) == set(headline) and all(identities[a]["sha256"] == headline[a]["sha256"] for a in headline):
        return dict(name="mainline", description="headline 07023fd6e -> 1055409c2; includes every landing between them "
                    "(only exbatch); no PAD/EX-OLD controls")
    frozen = json.loads(RECEIPTS.read_text())
    expected = {r["arm"]: r["sha256"] for r in frozen["artifacts"] if r["arm"] in ARMS}
    if receipt["source"] == "frozen lane receipts" or (set(identities) == set(ARMS) and all(
            identities[a]["sha256"] == expected[a] for a in ARMS)):
        return dict(name="lane", description="original EX1/EX3/EX6 lane; PAD-A kind A is PRE behaviour at POST layout; "
                    "EX*-OLD are kind-A selected-item controls")
    return dict(name="explicit", description="supplied receipt binaries; attribution limited to the available controls")


def unavailable_comparison(a, b, identities):
    missing = [arm for arm in (a, b) if arm not in identities]
    if missing:
        return dict(A=a, B=b, status="not available", missing_arms=missing,
                    reason="arms absent from receipt: " + ", ".join(missing))
    return None


def primary_plateaus(comps, identities):
    rates = {a: [] for a in ("PRE", "PAD-A", "POST") if a in identities}
    for comp in comps:
        if comp.get("status") == "not available" or not {comp["A"], comp["B"]} <= rates.keys():
            continue
        rates[comp["A"]].append(comp["left"]["rate"])
        rates[comp["B"]].append(comp["right"]["rate"])
    require(all(rates.values()), "missing primary arm plateau")
    return {a: statistics.mean(v) for a, v in rates.items()}


def info(conn, section):
    raw = conn.must("INFO", section)
    return dict(line.split(":", 1) for line in raw.decode().splitlines() if line and not line.startswith("#") and ":" in line)


def check_reply(reply, expected, command):
    require(not isinstance(reply, RespError), f"{command}: {reply}")
    if expected == "encoding":
        require(isinstance(reply, bytes) and bool(reply), f"OBJECT ENCODING returned {reply!r}")
    elif expected == "score":
        require(isinstance(reply, bytes) and float(reply) == 1, "wrong sorted-set score")
    elif expected == "groups":
        require(isinstance(reply, list) and len(reply) == 1, "stream group cardinality changed")
        fields = dict(zip(reply[0][::2], reply[0][1::2]))
        require(fields[b"name"] == b"g" and fields[b"consumers"] == 1 and fields[b"pending"] == 0,
                "stream group state changed")
    elif expected == "consumers":
        require(isinstance(reply, list) and len(reply) == 1, "stream consumer cardinality changed")
        fields = dict(zip(reply[0][::2], reply[0][1::2]))
        require(fields[b"name"] == b"c" and fields[b"pending"] == 0, "stream consumer state changed")
    else:
        require(type(reply) is type(expected) and reply == expected, f"{command}: {reply!r} != {expected!r}")


def verification_commands(base, n):
    key = f"exbatch-{n}"
    value = b"x" * 64
    if base == BASES[0]:
        return [(["GET", "w:" + key], value), (["GET", "plain:" + key], value)]
    if base in (BASES[1], BASES[2]):
        rows = [(["HLEN", "h:" + key], 1), (["HGET", "h:" + key, "field"], value),
                (["OBJECT", "ENCODING", "h:" + key], "encoding")]
        if base == BASES[1]:
            rows += [(["ZCARD", "z:" + key], 1), (["ZSCORE", "z:" + key, "member"], "score")]
        return rows
    if base == BASES[3]:
        return [(["XLEN", "s:" + key], 1), (["XINFO", "GROUPS", "s:" + key], "groups"),
                (["XINFO", "CONSUMERS", "s:" + key, "g"], "consumers"),
                (["XGROUP", "CREATECONSUMER", "s:" + key, "g", "c"], 0)]
    return [(["GET", key], value)]


def warm_worker(cell, index, folder, verify_only=False):
    base = cell["id"].rsplit("_", 1)[0]
    item = cell["memtier_instances"][index]
    templates = [shlex.split(c) for c in cell["workload"]["warm_commands"]]
    warmed, checked = 0, 0
    started = time.monotonic()
    kind = "verify" if verify_only else "warm"
    diagnostic = Diagnostics(folder, f"{kind}-{index}")
    replies = 0
    try:
        diagnostic.step("connect", timeout_seconds=60, key_min=item["key_min"], key_max=item["key_max"])
        with contextlib.closing(Conn("127.0.0.1", 18179, timeout=60)) as conn:
            for low in range(item["key_min"], item["key_max"] + 1, 128):
                batch = []
                high = min(low + 128, item["key_max"] + 1)
                for n in range(low, high):
                    if not verify_only:
                        for template in templates:
                            argv = [s.replace("{n}", str(n)) for s in template]
                            expected = b"OK" if argv[0] == "SET" or argv[:2] == ["XGROUP", "CREATE"] else b"1-0" if argv[0] == "XADD" else 1
                            batch.append((argv, expected))
                            warmed += 1
                    verify = verification_commands(base, n)
                    batch += verify
                    checked += len(verify)
                diagnostic.step("batch send", key_min=low, key_max=high - 1,
                                batch_commands=len(batch), replies_checked=replies, timeout_seconds=60)
                conn.raw(b"".join(encode(*argv) for argv, _ in batch))
                diagnostic.step("batch replies", key_min=low, key_max=high - 1,
                                batch_commands=len(batch), timeout_seconds=60)
                for reply_index, (argv, expected) in enumerate(batch):
                    diagnostic.current["evidence"].update(reply_index=reply_index, command=argv,
                                                          replies_checked=replies)
                    check_reply(conn.read(), expected, argv)
                    replies += 1
    except Exception as error:
        raise diagnostic.failure(error, replies_checked=replies) from error
    save(folder / f"{'verify' if verify_only else 'warm'}-{index}.json",
         dict(key_min=item["key_min"], key_max=item["key_max"], warmed_commands=warmed,
              verified_commands=checked, seconds=time.monotonic() - started, complete=True))


def watch_proof(folder):
    # Both windows are deterministic: wait for WATCH and foreign SET ACKs.
    # Unique fresh state per attempt; no skipped witness or tolerance widening.
    witnesses = []
    with contextlib.closing(Conn("127.0.0.1", 18179)) as a, contextlib.closing(Conn("127.0.0.1", 18179)) as b:
        for attempt in range(2):
            w, p = f"proof:w:{time.monotonic_ns()}", f"proof:plain:{time.monotonic_ns()}"
            require(a.must("EXISTS", w, p) == 0, "WATCH proof did not start fresh")
            check_reply(a.must("SET", w, "before"), b"OK", "proof seed")
            check_reply(a.must("WATCH", w), b"OK", "WATCH")
            check_reply(b.must("SET", w, "foreign"), b"OK", "foreign SET")
            check_reply(a.must("MULTI"), b"OK", "MULTI")
            check_reply(a.must("SET", w, "must-not-commit"), b"QUEUED", "SET")
            require(a.must("EXEC") is None and b.must("GET", w) == b"foreign", "foreign SET failed to abort WATCH")
            rotation = [("WATCH", w), ("SET", p, "plain"), ("MULTI",), ("SET", w, "committed"), ("EXEC",), ("UNWATCH",)]
            a.raw(b"".join(encode(*c) for c in rotation))
            for c, expected in zip(rotation, (b"OK", b"OK", b"OK", b"QUEUED", [b"OK"], b"OK")):
                check_reply(a.read(), expected, c)
            require(b.must("GET", w) == b"committed", "nonconflicting rotation did not commit")
            require(a.must("DEL", w, p) == 2, "proof cleanup failed")
            witnesses.append(dict(fresh_key=w, foreign_set_abort=True, nonconflicting_commit=True))
    save(folder / "watch-proof.json", witnesses)


def validate_wire(cell, frames):
    templates = [s.split() for s in cell["workload"]["commands"]]
    require(len(frames) == 2 * len(templates), "wire probe did not emit exactly two rotations")
    rotations = []
    for start in range(0, len(frames), len(templates)):
        suffixes = []
        for template, actual in zip(templates, frames[start:start + len(templates)]):
            require(len(template) == len(actual), "wire probe arity changed")
            for want, got in zip(template, actual):
                if "__key__" in want:
                    prefix, suffix = want.split("__key__")
                    match = re.fullmatch(re.escape(prefix + "exbatch-") + r"(\d+)" + re.escape(suffix), got)
                    require(match is not None, "memtier did not preserve literal key affix")
                    n = int(match[1])
                    require(1 <= n <= cell["memtier_instances"][0]["key_max"], "probe key outside instance 0")
                    suffixes.append(n)
                elif want == "__data__":
                    require(len(got.encode()) == 64, "memtier value size changed")
                else:
                    require(want.upper() == got.upper(), "memtier command rotation changed")
        if cell["workload"]["transaction"]:
            require(len(set(suffixes)) == 1, "WATCH and SET resolve to different suffixes")
        rotations.append(suffixes)
    return dict(frames=frames, rotation_suffixes=rotations, complete=True)


def poll_worker(folder, cpu=111):
    rows, missed = [], 0
    with contextlib.closing(Conn("127.0.0.1", 18179)) as conn:
        save(folder / "poll-ready.json", dict(pid=os.getpid(), cpu=cpu))
        while not (folder / "poll-start.json").exists():
            time.sleep(.002)
        start = json.loads((folder / "poll-start.json").read_text())["start"]
        index = 0
        while not (folder / "poll-stop").exists():
            due = start + index / 100
            time.sleep(max(0, due - time.monotonic()))
            sent = time.monotonic()
            late = sent - due
            if late >= .01:
                skipped = int(late / .01)
                missed += skipped
                index += skipped
            reply = conn.must("MEMORY", "STATS")
            require(isinstance(reply, list) and len(reply) % 2 == 0 and b"keys.count" in reply,
                    "invalid MEMORY STATS observer reply")
            rows.append(dict(sent=sent, completed=time.monotonic(), scheduled=due, lateness=late))
            index += 1
    save(folder / "poll.json", dict(start=start, successful=len(rows), missed_deadlines=missed, samples=rows))


class Children:
    def __init__(self):
        self.processes = []

    def start(self, argv, log, cwd, extra_env=None):
        with Path(log).open("wb") as output:
            process = subprocess.Popen(argv, stdout=output, stderr=subprocess.STDOUT, cwd=cwd,
                                       start_new_session=True, env={**os.environ, "LC_ALL": "C", **(extra_env or {})})
        self.processes.append(process)
        return process

    def stop(self, process, sig=signal.SIGTERM):
        if process.poll() is None:
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)

    def close(self):
        for process in reversed(self.processes):
            self.stop(process)


class PerfWindow:
    ACK_TIMEOUT = 5.0

    def __init__(self, folder, children, cores=DEFAULT_CORES):
        self.folder, self.children = folder, children
        self.cores = cores
        for name in ("perf.ctl", "perf.ack"):
            os.mkfifo(folder / name)
        self.ctl = os.open(folder / "perf.ctl", os.O_RDWR | os.O_NONBLOCK)
        self.ack = os.open(folder / "perf.ack", os.O_RDWR | os.O_NONBLOCK)
        self.process = children.start(perf_argv(folder, cores), folder / "perf.log", folder)
        try:
            self.command("disable")  # ACK proves perf is listening before any timed work.
            self.identity = dict(path=os.readlink(f"/proc/{self.process.pid}/exe"),
                                 sha256=digest(f"/proc/{self.process.pid}/exe"))
        except BaseException:
            self.close()
            raise

    def command(self, text):
        before = time.monotonic()
        os.write(self.ctl, (text + "\n").encode())
        deadline = before + self.ACK_TIMEOUT
        pending, received, acknowledgements = b"", bytearray(), 0
        while True:
            status = self.process.poll()
            require(status is None, f"perf exited ({status}) awaiting {text!r} ACK; see {self.folder / 'perf.log'}")
            remaining = deadline - time.monotonic()
            require(remaining > 0, f"perf control ACK timeout for {text!r} after {time.monotonic() - before:.3f}s; "
                    f"received {bytes(received)!r}; pid={self.process.pid}; see {self.folder / 'perf.log'}")
            if not select.select([self.ack], [], [], min(.05, remaining))[0]:
                continue
            # FIFO reads are stream fragments, not replies. Drain every available
            # chunk, including coalesced replies, without adding a timed delay.
            while time.monotonic() < deadline:
                try:
                    chunk = os.read(self.ack, 4096)
                except BlockingIOError:
                    break
                if not chunk:
                    break
                received.extend(chunk)
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    # perf 7.0.12 writes b"ack\n\x00", including the NUL.
                    # Its terminator may arrive before the next line or alone.
                    if line.strip(b"\x00\r") == b"ack":
                        acknowledgements += 1
            if acknowledgements:
                require(self.process.poll() is None, f"perf exited after {text!r} ACK; see {self.folder / 'perf.log'}")
                # Only one command is outstanding. Surplus drained ACKs must not
                # satisfy the next command before perf has acted on that command.
                return dict(before=before, after=time.monotonic(),
                            ack_hex=received.hex(), ack_lines=acknowledgements)

    def finish(self):
        self.children.stop(self.process, signal.SIGINT)
        return parse_perf((self.folder / "perf.csv").read_text(), cpu_ids(self.cores[0]))

    def close(self):
        self.children.stop(self.process, signal.SIGINT)
        os.close(self.ctl)
        os.close(self.ack)


def quiet_file_guard():
    path = os.environ.get("GATE_QUIET_FILE")
    if path:
        require(Path(path).exists() and time.time() - Path(path).stat().st_mtime >
                60 * float(os.environ.get("GATE_QUIET_MINUTES", "3")), "GATE_QUIET_FILE absent/recent; recollect on quiet box")


def wait_for(path, process, seconds=10):
    started = time.monotonic()
    deadline = started + seconds
    while not path.exists():
        require(process.poll() is None, f"worker exited before {path}")
        require(time.monotonic() < deadline, f"timeout waiting for {path} after {time.monotonic() - started:.3f}s; "
                f"pid={process.pid}, exit_status={process.poll()}")
        time.sleep(.01)


def command_counts(cell, before, after):
    names = {s.split()[0] for s in cell["workload"]["commands"]}
    result = {n: command_stat(after, n)[0] - command_stat(before, n)[0] for n in names}
    require(all(c > 0 for c in result.values()), "no progress on a workload command")
    return result


def role_cpus(snapshot, regime, boot, server_cpus=range(8)):
    placement = {int(t): int(cpu) for t, cpu in (part.split(":") for part in boot["thread_cpus"].split(","))}
    require(set(placement) == set(snapshot.threads), "INFO/LBSIGNALS thread inventory differs")
    roles = {}
    for tid, row in snapshot.threads.items():
        # LBSIGNALS 'cpu' is CPU TIME, not a placement ID. Use INFO's map.
        roles.setdefault(row["role"], []).append(placement[tid])
    require(sorted(c for cpus in roles.values() for c in cpus) == list(server_cpus), "server CPU geometry changed")
    expected = {"io": 6, "ex": 2} if regime == "s0" else {"fused": 8}
    require({r: len(v) for r, v in roles.items()} == expected, "server roles changed")
    return roles


def wire_probe(cell, folder, children, guard=None):
    diagnostic = Diagnostics(folder, "wire-probe")
    frames, proc, raw = [], None, None
    expected_frames = 2 * cell["workload"]["cycle_frames"]
    try:
        diagnostic.step("MONITOR connect", timeout_seconds=10)
        with contextlib.closing(Conn("127.0.0.1", 18179, timeout=10)) as monitor:
            diagnostic.step("MONITOR acknowledgement", timeout_seconds=10)
            check_reply(monitor.must("MONITOR"), b"OK", "MONITOR")
            guarded = cell["id"].startswith(BASES[3])
            env = guard_environment(guard, folder, "wire-probe") if guarded else None
            diagnostic.step("memtier launch", argv=probe_argv(cell, folder), guard_env=env)
            proc = children.start(probe_argv(cell, folder), folder / "wire-probe.log", folder, env)
            # At most 12 short MONITOR lines fit comfortably in the socket buffer.
            # Reap the tiny probe first so an LD_PRELOAD/grammar failure is reported
            # immediately, instead of waiting for frames it will never send.
            diagnostic.step("memtier exit", timeout_seconds=10)
            status = proc.wait(timeout=10)
            require(status == 0, f"memtier wire probe exited {status}")
            diagnostic.step("MONITOR frames", timeout_seconds=10)
            for _ in range(expected_frames):
                raw = monitor.read()
                require(isinstance(raw, bytes), "missing MONITOR wire witness")
                # All recipe tokens are printable ASCII. Refuse unknown escaping.
                tokens = re.findall(r'"(?:[^"\\]|\\.)*"', raw.decode("ascii"))
                frames.append([json.loads(s) for s in tokens])
        diagnostic.step("wire/HDR/guard validation")
        record = validate_wire(cell, frames)
        parsed = parse_memtier(folder / "wire-probe.json", cell, folder / "wire-probe.log")
        record["completed"] = parsed["completed"]
        if guarded:
            record["zero_reply_guard"] = check_zero_receipt(folder / "wire-probe-zero.json", parsed["completed"]["XGROUP"], 1)
        save(folder / "wire-witness.json", record)
        return record
    except Exception as error:
        raise diagnostic.failure(error, expected_frames=expected_frames, frames=frames,
                                 received_frames=len(frames), last_raw=repr(raw),
                                 pid=proc.pid if proc else None, exit_status=proc.poll() if proc else None,
                                 artifacts=file_evidence(folder, ("wire-probe.log", "wire-probe.json",
                                                                   "wire-probe-zero.json"))) from error


def check_mix(cell, counts, bound):
    rotation = Counter(s.split()[0] for s in cell["workload"]["commands"])
    rounds = [counts[n] / number for n, number in rotation.items()]
    require(max(rounds) - min(rounds) <= bound, "command mix differs beyond finite pipeline boundary")
    return dict(rotation=dict(rotation), counts=counts, boundary_frames=bound)


def run_sample(cell, arm, identities, folder, q, guard=None):
    folder.mkdir(parents=True, exist_ok=False)
    cores = cell_cores(cell)
    server_cpus, load_cpus = map(cpu_ids, cores)
    record = dict(cell=cell["id"], arm=arm, arm_identity=identities[arm], complete=False,
                  matched=q if q is not None else "plateau", argv={}, artifacts=str(folder),
                  numerator_scope=f"perf stat system-wide on CPUs {cores[0]}, grouped cycles+instructions; includes observer server work",
                  denominator_scope="central top-level workload frames; excludes MEMORY/INFO/DEBUG and counts queued SET once",
                  latency_scope="pooled completed-response HDR across all eight full 28-second runs, including warmup/tail",
                  startup_allowance_seconds=0, server_boot_timeout_seconds=30)
    children, monitor, conn, perf = Children(), None, None, None
    started = time.monotonic()
    diagnostic = Diagnostics(folder, "sample")
    try:
        diagnostic.step("quiet preflight")
        quiet_file_guard()
        monitor = QuietMonitor(server_cpus, load_cpus, ports=[18179],
                               sample_artifact=folder / "quiet-samples.jsonl").start()
        record["quiet"] = monitor.evidence()
        diagnostic.step("server launch and boot", timeout_seconds=30)
        # Bind without REUSEPORT before launch; never adopt another process's listener.
        import socket
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", 18179))
        binary = identities[arm]["path"]
        require(digest(binary) == identities[arm]["sha256"], "arm changed before launch")
        require(digest(MEMTIER) == json.loads(INVENTORY.read_text())["memtier"]["sha256"], "memtier changed")
        argv = server_argv(cell, binary, folder)
        record["argv"]["server"] = argv
        server = children.start(argv, folder / "server.log", folder)
        deadline = time.monotonic() + 30  # Same startup allowance as normal gate Runner.
        while conn is None:
            require(server.poll() is None, "server exited during boot; see server.log")
            try:
                conn = Conn("127.0.0.1", 18179, timeout=10)
                boot = info(conn, "server")
                require(int(boot["process_id"]) == server.pid, "listener is not our child")
            except (OSError, EOFError):
                if conn:
                    conn.close()
                    conn = None
                require(time.monotonic() < deadline, "server boot exceeded gate's 30s allowance")
                time.sleep(.1)
        require(digest(f"/proc/{server.pid}/exe") == identities[arm]["sha256"], "running ELF differs from frozen arm")
        record["boot_info"] = boot
        base, regime = cell["id"].rsplit("_", 1)
        require(boot["read_local"] == ("1" if regime == "f1" else "0"), "effective read-local posture differs")
        for name, value in {"pin_threads": "1", "net_io": "uring", "atomic": "1",
                            "key_lb": "1", "client_lb": "1", "flip_auto": "0", "shards": "16",
                            "reorder": "0", "thread_mode": "2s" if regime == "s0" else "1s"}.items():
            require(boot[name] == value, f"effective boot {name} differs from recipe")
        require(conn.must("DBSIZE") == 0, "server did not boot with fresh empty state")
        if base == BASES[0]:
            diagnostic.step("WATCH proof")
            watch_proof(folder)
        diagnostic.step("warm worker launch")
        warmers = []
        for i in range(8):
            argv = worker_argv("warm", cell, folder, i)
            record["argv"].setdefault("warm", []).append(argv)
            warmers.append(children.start(argv, folder / f"warm-{i}.log", folder))
        for i, worker in enumerate(warmers):
            diagnostic.step("warm worker exit", instance=i, pid=worker.pid, timeout_seconds=600)
            require(worker.wait(timeout=600) == 0, f"typed warm/verification failed for instance {i}")
        diagnostic.step("warm state validation")
        require(conn.must("DBSIZE") == cell["workload"]["physical_keys"], "warm physical key count differs")
        record["warm"] = [json.loads((folder / f"warm-{i}.json").read_text()) for i in range(8)]
        record["argv"]["wire_probe"] = probe_argv(cell, folder)
        if base == BASES[3]:
            require(guard is not None and digest(guard["path"]) == guard["sha256"], "XGROUP native guard changed")
            record["zero_reply_guard"] = guard
        diagnostic.step("wire probe")
        record["wire_witness"] = wire_probe(cell, folder, children, guard)
        diagnostic.step("wire connection drain", timeout_seconds=10)
        deadline = time.monotonic() + 10
        while int(info(conn, "clients")["connected_clients"]) != 1:
            require(time.monotonic() < deadline, "wire probe/monitor connections did not drain")
            time.sleep(.02)
        before_full = info(conn, "commandstats")
        record["whole_commandstats_before"] = before_full
        diagnostic.step("perf startup/disable ACK")
        perf = PerfWindow(folder, children, cores)
        record["argv"]["perf"] = perf_argv(folder, cores)
        poller = None
        if base == BASES[-1]:
            diagnostic.step("observer ready", timeout_seconds=10)
            argv = worker_argv("poll", cell, folder)
            record["argv"]["observer"] = argv
            poller = children.start(argv, folder / "poll.log", folder)
            wait_for(folder / "poll-ready.json", poller)
            save(folder / "poll-start.json", dict(start=time.monotonic() + .05))
        diagnostic.step("load launch and warmup")
        launch = time.monotonic()
        loads = []
        for i in range(8):
            argv = load_argv(cell, i, folder, q)
            record["argv"].setdefault("load", []).append(argv)
            env = guard_environment(guard, folder, f"load-{i}") if base == BASES[3] else None
            if env:
                record.setdefault("load_env", []).append(env)
            loads.append(children.start(argv, folder / f"load-{i}.log", folder, env))
        last_launch = time.monotonic()
        time.sleep(WARMUP)
        require(all(p.poll() is None for p in loads), "generator exited before central window")
        require(int(info(conn, "clients")["connected_clients"]) == CONNECTIONS + 1 + bool(poller),
                "not all 512 workload connections are active")
        stats0 = info(conn, "stats")
        lb0raw = conn.must("DEBUG", "LBSIGNALS")
        (folder / "lb-before.txt").write_bytes(lb0raw)
        lb0 = parse_snapshot(lb0raw)
        roles = role_cpus(lb0, regime, boot, server_cpus)
        diagnostic.step("perf enable ACK / initial commandstats")
        enable = perf.command("enable")
        before_at = time.monotonic()
        before = info(conn, "commandstats")
        t0 = time.monotonic()
        # Normal gate uses no diagnostic +5s allowance: preserve --test-time=28.
        # The five-second tail absorbs sequential launch and counter endpoint work.
        require(t0 - launch < WARMUP + 1, "load startup/counter setup consumed >1s of the reserved tail")
        diagnostic.step("central perf window", window_seconds=WINDOW)
        while time.monotonic() < t0 + WINDOW:
            time.sleep(min(1, max(0, t0 + WINDOW - time.monotonic())))
            quiet_file_guard()
            monitor.check()
            require(server.poll() is None and all(p.poll() is None for p in loads), "child exited inside central window")
        diagnostic.step("final commandstats / perf disable ACK")
        after_at = time.monotonic()
        after = info(conn, "commandstats")
        t1 = time.monotonic()
        disable = perf.command("disable")
        record["window"] = dict(start=t0, end=t1, seconds=t1 - t0, first_launch=launch, last_launch=last_launch,
                                before_request=before_at, after_request=after_at, perf_enable=enable, perf_disable=disable,
                                pmu_prefix_seconds=t0 - enable["before"], pmu_suffix_seconds=disable["after"] - t1,
                                endpoint_limit_seconds=.05)
        require(t0 - enable["before"] <= .05 and disable["after"] - t1 <= .05 and t1 - t0 <= WINDOW + .05,
                "PMU/counter endpoint skew exceeds 50ms; reject window")
        record["commandstats_before"], record["commandstats_after"] = before, after
        diagnostic.step("perf finish and counter validation")
        pmu = perf.finish()
        pmu["executable"] = perf.identity
        lb1raw = conn.must("DEBUG", "LBSIGNALS")
        (folder / "lb-after.txt").write_bytes(lb1raw)
        lb1 = parse_snapshot(lb1raw)
        require(role_cpus(lb1, regime, info(conn, "server"), server_cpus) == roles, "thread roles/CPU placement changed during sample")
        stats1 = info(conn, "stats")
        require(int(stats1["keyspace_misses"]) == int(stats0["keyspace_misses"]), "scored workload missed warm state")
        require(all(p.poll() is None for p in loads), "generator ended inside central window")
        require(int(info(conn, "clients")["connected_clients"]) == CONNECTIONS + 1 + bool(poller), "connections disappeared")
        counts = command_counts(cell, before, after)
        record["mix"] = check_mix(cell, counts, 2 * BOUND)
        frames = sum(counts.values())
        record.update(frames=frames, rate=frames / (t1 - t0), window_seconds=t1 - t0,
                      instructions=pmu["instructions"], cycles=pmu["cycles"], ipc=pmu["ipc"],
                      instr_per_op=pmu["instructions"] / frames,
                      cycles_per_op=(pmu["instructions"] / frames) / pmu["ipc"],
                      stats_before=stats0, stats_after=stats1,
                      saturation=bottleneck_saturation(lb0, lb1, floor_pct=SATURATION_FLOOR))
        record["per_role_pmu"] = {}
        for role, cpus in roles.items():
            cycles = sum(pmu["cpus"][cpu]["cycles"] for cpu in cpus)
            instructions = sum(pmu["cpus"][cpu]["instructions"] for cpu in cpus)
            record["per_role_pmu"][role] = dict(cpus=cpus, cycles=cycles, instructions=instructions,
                                                ipc=instructions / cycles, cycles_per_frame=cycles / frames)
        record["pmu"] = pmu
        if q is not None:
            record["rate_match"] = rate_check([record["rate"]], q)
        for i, load in enumerate(loads):
            diagnostic.step("memtier load exit", instance=i, pid=load.pid, timeout_seconds=30)
            require(load.wait(timeout=30) == 0, f"memtier {i} failed")
        if poller:
            diagnostic.step("observer exit", pid=poller.pid, timeout_seconds=10)
            (folder / "poll-stop").touch()
            require(poller.wait(timeout=10) == 0, "observer failed")
            polls = json.loads((folder / "poll.json").read_text())
            central = [p for p in polls["samples"] if t0 <= p["completed"] < t1]
            memory_calls = command_stat(after, "MEMORY")[0] - command_stat(before, "MEMORY")[0]
            require(polls["missed_deadlines"] == 0 and abs(len(central) - 100 * (t1 - t0)) <= 2,
                    "observer missed 100Hz cadence; recollect block")
            require(abs(memory_calls - len(central)) <= 2, "observer/server MEMORY accounting differs")
            record["observer"] = dict(successful=polls["successful"], central_successful=len(central),
                                       central_memory_calls=memory_calls, missed_deadlines=0,
                                       scope=f"one persistent connection, CPU{load_cpus[-1]}, 100Hz; workload denominator excludes MEMORY")
        diagnostic.step("whole-run HDR/guard accounting")
        after_full = info(conn, "commandstats")
        record["whole_commandstats_after"] = after_full
        full_counts = command_counts(cell, before_full, after_full)
        documents = [parse_memtier(folder / f"load-{i}.json", cell, folder / f"load-{i}.log") for i in range(8)]
        completed = Counter()
        hist = Counter()
        for i, doc in enumerate(documents):
            if base == BASES[3]:
                doc["zero_reply_guard"] = check_zero_receipt(folder / f"load-{i}-zero.json", doc["completed"]["XGROUP"], 64)
            completed.update(doc["completed"])
            hist.update(doc.pop("histogram"))
        require(dict(completed) == full_counts, f"whole-run server/HDR accounting differs: {full_counts} / {dict(completed)}")
        record["whole_mix"] = check_mix(cell, completed, CONNECTIONS)
        record["memtier"], record["histogram"] = documents, dict(hist)
        record.update(p50=percentile(hist, 50), p99=percentile(hist, 99), p999=percentile(hist, 99.9),
                      completed_whole_run_frames=sum(completed.values()),
                      central_frame_boundary_bound=2 * BOUND)
        if base == BASES[0]:
            commits = sum(d["committed_transactions"] for d in documents)
            require(commits == completed["EXEC"], "committed transaction denominator mismatch")
            record["watch"] = dict(exec_aborts=0, committed_transactions_whole_run=commits,
                                   central_execs=counts["EXEC"], central_exec_boundary_bound=2 * BOUND,
                                   successful_sets_whole_run=completed["SET"],
                                   cycles_per_central_committed_transaction=pmu["cycles"] / counts["EXEC"],
                                   instructions_per_central_committed_transaction=pmu["instructions"] / counts["EXEC"],
                                   queued_replies_are_not_extra_writes=True)
        require(conn.must("DBSIZE") == cell["workload"]["physical_keys"], "workload grew/lost physical keys")
        if base == BASES[3]:
            diagnostic.step("verify worker launch")
            verifiers = [children.start(worker_argv("verify", cell, folder, i), folder / f"verify-{i}.log", folder)
                         for i in range(8)]
            record["argv"]["verify"] = [worker_argv("verify", cell, folder, i) for i in range(8)]
            for i, process in enumerate(verifiers):
                diagnostic.step("verify worker exit", instance=i, pid=process.pid, timeout_seconds=180)
                require(process.wait(timeout=180) == 0, "XGROUP existing-consumer/cardinality check failed")
            record["xgroup"] = dict(all_keys_verified_before_and_after=True, existing_consumer_reply=0,
                                     streams=65536, groups_per_stream=1, consumers_per_group=1,
                                     scored_zero_replies=completed["XGROUP"],
                                     observation="every scored wire reply checked as :0 CR LF by SHA-bound native receive guard; exact guard/HDR reconciliation")
        diagnostic.step("final quiet/identity checks")
        quiet_file_guard()
        monitor.check()
        require(digest(binary) == identities[arm]["sha256"], "arm changed during sample")
        record["complete"] = True
        return record
    except BaseException as error:
        failure = diagnostic.failure(error,
            children=[dict(pid=p.pid, exit_status=p.poll()) for p in children.processes],
            artifacts=file_evidence(folder, sorted({p.name for pattern in ("*.log", "*-failure.json", "*-zero.json")
                                                     for p in folder.glob(pattern)})))
        record["error"] = str(failure)
        if not isinstance(error, Exception):
            raise
        raise failure from error
    finally:
        diagnostic.step("cleanup")
        if perf:
            perf.close()
        if conn:
            conn.close()
        children.close()
        if monitor:
            record["quiet"] = monitor.close()
        record["elapsed_seconds"] = time.monotonic() - started
        diagnostic.step("finished")
        record["steps"] = diagnostic.steps
        save(folder / "sample.json", record)


def aggregate(samples):
    require(samples and all(s["complete"] for s in samples), "cannot aggregate incomplete samples")
    frames = sum(s["frames"] for s in samples)
    cycles = sum(s["cycles"] for s in samples)
    instructions = sum(s["instructions"] for s in samples)
    hist = Counter()
    for sample in samples:
        hist.update({int(k): v for k, v in sample["histogram"].items()})
    ipc = instructions / cycles
    return dict(rate=statistics.mean(s["rate"] for s in samples), p50=percentile(hist, 50),
                p99=percentile(hist, 99), p999=percentile(hist, 99.9), instr_per_op=instructions / frames,
                ipc=ipc, cycles_per_op=(instructions / frames) / ipc, samples=len(samples),
                repeat_spread_pct=100 * (max(s["rate"] for s in samples) / min(s["rate"] for s in samples) - 1))


def framing_suffix(framing):
    return f"; framing={framing['name']}: {framing['description']}" if framing else ""


def unavailable_row(cell, comparison, q, framing):
    base, regime = cell["id"].rsplit("_", 1)
    return (f"EXBATCH-DIRECTED {base} {regime} {comparison['A']}->{comparison['B']} "
            f"not available; {comparison['reason']}; matched={q if q is not None else 'plateau'}" +
            framing_suffix(framing))


def endgame(cell, a, b, left, right, q, framing=None):
    base, regime = cell["id"].rsplit("_", 1)
    delta = lambda key: 100 * (right[key] / left[key] - 1)
    return (f"EXBATCH-DIRECTED {base} {regime} {a}->{b} "
            f"rate={left['rate']:.2f}/{right['rate']:.2f} ({delta('rate'):+.2f}%) "
            f"p50={left['p50']:.3f}/{right['p50']:.3f} p99={left['p99']:.3f}/{right['p99']:.3f} "
            f"cyc/op={left['cycles_per_op']:.3f}/{right['cycles_per_op']:.3f} ({delta('cycles_per_op'):+.2f}%) "
            f"instr/op={left['instr_per_op']:.3f}/{right['instr_per_op']:.3f} "
            f"ipc={left['ipc']:.4f}/{right['ipc']:.4f} matched={q if q is not None else 'plateau'}" +
            framing_suffix(framing))


def block_checks(samples, q, matched_pre=False):
    require(len(samples) == 4, "ABBA block incomplete")
    sides = ([samples[0], samples[3]], [samples[1], samples[2]])
    if q is not None:
        rate_check([s["rate"] for s in samples], q)
        receipt = rate_check([statistics.mean(s["rate"] for s in side) for side in sides], q)
        require(receipt["inter_arm_spread_pct"] <= .5, "matched arm means differ >0.5%; recollect common target")
        if matched_pre:
            require(all(s["arm"] == "PRE" for s in samples), "matched precondition requires PRE null samples")
            costs = [s["cycles"] / s["frames"] for s in samples]
            require(all(math.isfinite(c) and c > 0 for c in costs), "invalid matched cyc/op")
            # All four samples are PRE. Check both repeats and both null sides,
            # so equal within-side costs cannot conceal a displaced null pair.
            low, high = min(costs), max(costs)
            ratio = high / low
            require(ratio <= 1.02,
                    f"same-arm matched repeats differ >2%; arm=PRE cyc/op={low:.6f}/{high:.6f} "
                    f"spread={100 * (ratio - 1):.6f}%; "
                    f"samples={[s.get('artifacts') for s in samples]}; recollect quiet block")
    else:
        for side in sides:
            require(statistics.mean(s["saturation"]["score_pct"] for s in side) >= SATURATION_FLOOR and
                    min(s["saturation"]["score_pct"] for s in side) >= SATURATION_FLOOR - 5,
                    "unlimited-rate block lacks gate productive-role occupancy; not a sustainable plateau")
            rates = [s["rate"] for s in side]
            ratio = max(rates) / min(rates)
            spread = ratio - 1
            require(ratio <= 1.02,
                    f"same-arm plateau repeats differ >2%; arm={side[0].get('arm', 'unknown')} "
                    f"rates={rates[0]:.6f}/{rates[1]:.6f} frames/s spread={100 * spread:.6f}%; "
                    f"samples={[s.get('artifacts') for s in side]}; recollect quiet block")
    if "observer" in samples[0]:
        require(max(s["observer"]["central_successful"] for s in samples) -
                min(s["observer"]["central_successful"] for s in samples) <= 2, "poll cadence differs across arms")


def validate_score(score, matched_load):
    require(score in ("plateau-then-matched", "matched-only"), "unknown score mode")
    if score == "matched-only":
        require(type(matched_load) is int, "--score matched-only requires --matched-load (aggregate offered frames/s)")
        return matched_q(matched_load)
    require(matched_load is None, "--matched-load requires --score matched-only")
    return None


def dry_run(cells, identities, output, blocks, receipt=None, framing=None,
            score="plateau-then-matched", matched_load=None):
    fixed_q = validate_score(score, matched_load)
    cores = cell_cores(cells[0])
    suffix = " plateau=skipped" if score == "matched-only" else ""
    identities = {a: dict(entry) for a, entry in identities.items()}
    print("# DRY RUN: only memtier --help was executed. No server, load, perf, socket, build or output directory is created.")
    print("# arm SHA256 identities " + json.dumps(identities, sort_keys=True))
    print("# arms receipt " + json.dumps(receipt, sort_keys=True))
    print("# measurement framing " + json.dumps(framing, sort_keys=True))
    if fixed_q is not None:
        print(f"# score=matched-only plateau=skipped; requested={matched_load} frames/s; "
              f"q=floor({matched_load}/512)={fixed_q}; offered={CONNECTIONS * fixed_q} frames/s; "
              "PRE matched cyc/op repeats must agree within 2% in every null ABBA block")
    print(shlex.join([MEMTIER, "--help"]) + " # already checked; SHA-bound grammar receipt")
    print("git rev-parse HEAD")
    guard = dict(path=str(output / "guard/zero-reply.so"))
    if any(c["id"].startswith(BASES[3]) for c in cells):
        print("# write embedded zero-reply C source; compile and SHA-bind before quiet preflight")
        print(shlex.join(guard_build_argv(output / "guard", cores=cores)))
        print(shlex.join(guard_build_argv(output / "guard", unit=True, cores=cores)))
        for mode in ("good", "bad", "error", "partial", "empty"):
            print(shlex.join(["env", f"EXBATCH_ZERO_RECEIPT={output / 'guard' / (mode + '.json')}",
                              "taskset", "-c", str(cpu_ids(cores[1])[0]), str(output / "guard/guard-unit"), mode]))
    for arm, identity in identities.items():
        source = identity["path"]
        identity["path"] = str(output / "arms" / arm / "tomokv")
        print(f"# freeze copy {shlex.quote(source)} -> {shlex.quote(identity['path'])}; chmod 0555; verify SHA256")
    for cell in cells:
        base, _ = cell["id"].rsplit("_", 1)
        phases = (("matched", fixed_q),) if fixed_q is not None else (("plateau", None), ("matched", "Q_" + cell["id"]))
        for phase, q in phases:
            if q and fixed_q is None:
                primary = "/".join(a for a in ("PRE", "PAD-A", "POST") if a in identities)
                print(f"# {q}=floor(0.8*min(mean {primary} primary plateau frames/s)/512)")
            pairs = [("PRE", "PRE")] + comparisons(cell)
            for pair_index, (a, b) in enumerate(pairs):
                unavailable = unavailable_comparison(a, b, identities)
                if unavailable:
                    print("# " + unavailable_row(cell, unavailable, q, framing) + suffix)
                    continue
                for block in range(blocks):
                    for index, arm in enumerate((a, b, b, a)):
                        folder = output / cell["id"] / phase / f"pair{pair_index}-block{block}-{index}-{arm}"
                        print(f"# {cell['id']} {phase} {a}->{b} ABBA[{index}], quiet guard 20s, boot allowance 30s, fresh warm state")
                        print(shlex.join(server_argv(cell, identities[arm]["path"], folder)))
                        if base == BASES[0]:
                            print("# RESP fresh WATCH key, foreign SET ACK, MULTI/SET/EXEC -> null; fresh nonconflicting six-frame commit -> [OK]; cleanup, repeat twice")
                        for i in range(8):
                            print(shlex.join(worker_argv("warm", cell, folder, i)))
                        for recipe in cell["workload"]["warm_commands"]:
                            print(f"# warm each n=1..{cell['workload']['keyspace']}: {recipe}; check creation reply and read back every key")
                        print("# RESP MONITOR then read/validate exactly two real memtier rotations; close before scoring")
                        def display_load(argv, label):
                            if base == BASES[3]:
                                env = guard_environment(guard, folder, label)
                                print(shlex.join(["env", *[f"{k}={v}" for k, v in env.items()], *argv]))
                            else:
                                print(shlex.join(argv))
                        display_load(probe_argv(cell, folder), "wire-probe")
                        print(shlex.join(perf_argv(folder, cores)))
                        if base == BASES[-1]:
                            print(shlex.join(worker_argv("poll", cell, folder)))
                        for i in range(8):
                            display_load(load_argv(cell, i, folder, q), f"load-{i}")
                        print("# warmup 3s; perf FIFO enable/ACK; INFO commandstats; central 20s; INFO commandstats; perf disable/ACK; drain 28s workload; reap owned perf")
                        if base == BASES[3]:
                            for i in range(8):
                                print(shlex.join(worker_argv("verify", cell, folder, i)))
                        print("# verify exact whole-run server/HDR counts, replies/mix/state, rate target, PMU coverage; terminate/reap owned server")


def run(cells, identities, output, blocks, memtier, receipt=None, framing=None,
        score="plateau-then-matched", matched_load=None):
    fixed_q = validate_score(score, matched_load)
    cores = cell_cores(cells[0])
    suffix = " plateau=skipped" if score == "matched-only" else ""
    require(not output.exists(), "output already exists; never overwrite/reuse prior samples")
    receipt = receipt or bind_arms()[1]
    verify_receipt(receipt)
    framing = framing or measurement_framing(identities, receipt)
    require(set(cpu_ids(cores[0])) | set(cpu_ids(cores[1])) <= os.sched_getaffinity(0),
            f"launch must permit server CPUs {cores[0]} and load CPUs {cores[1]}")
    os.sched_setaffinity(0, {cpu_ids(cores[1])[0]})
    output.mkdir(parents=True)
    instrument_files = [Path(__file__).resolve(), INVENTORY, RECEIPTS, MAINLINE_RECEIPT,
                        *[ROOT / "tests" / n for n in ("_lib.py", "abba_workloads.py", "abba_saturation.py", "gate_quiet.py", "gateplan.py")]]
    report = dict(schema=2, complete=False, arms=identities, arms_receipt=receipt, framing=framing,
                  unavailable_arms={a: "not available: absent from receipt" for a in ARMS if a not in identities},
                  memtier=memtier,
                  instrument={str(p.relative_to(ROOT)): digest(p) for p in instrument_files},
                  git_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  regimes=sorted({c["id"].rsplit("_", 1)[1] for c in cells}), cells={}, rows=[],
                  bands="Same-binary nulls collected before each pass; no regression band inferred/widened by this tool. Mainline freezes bands and judges.",
                  capacity="Fixed requested 8-instance geometry. Productive occupancy and repeatability checked; higher-generator-capacity plateau proof remains mainline's calibration.")
    if fixed_q is not None:
        report.update(score=score, plateau="skipped", matched_load=dict(source="--matched-load",
                      requested_frames_per_second=matched_load, q=fixed_q,
                      offered_frames_per_second=CONNECTIONS * fixed_q),
                      capacity="Plateau skipped. Matched PRE cyc/op repeatability and achieved-rate checks required; no capacity claim.")
    if cores != DEFAULT_CORES:
        report["cores"] = dict(server=cores[0], load=cores[1])
    started = time.monotonic()
    try:
        guard = prepare_guard(output / "guard", cores) if any(c["id"].startswith(BASES[3]) for c in cells) else None
        report["zero_reply_guard"] = guard
        # Frozen copies prevent a concurrent rebuild replacing a measured arm.
        for arm, identity in identities.items():
            target = output / "arms" / arm / "tomokv"
            target.parent.mkdir(parents=True)
            shutil.copyfile(identity["path"], target)
            require(digest(target) == identity["sha256"], "arm changed while freezing")
            target.chmod(0o555)
            identity["source_path"], identity["path"] = identity["path"], str(target)
        for cell in cells:
            entry = report["cells"][cell["id"]] = dict(recipe=cell, passes={})
            q = fixed_q
            if fixed_q is not None:
                entry.update(plateau="skipped", matched_q=q)
            for phase in (("matched",) if fixed_q is not None else ("plateau", "matched")):
                pass_entry = entry["passes"][phase] = dict(q=q, null=[], comparisons=[], blocks=[])
                for pair_index, (a, b) in enumerate([("PRE", "PRE")] + comparisons(cell)):
                    unavailable = unavailable_comparison(a, b, identities)
                    if unavailable:
                        pass_entry["comparisons"].append(unavailable)
                        row = unavailable_row(cell, unavailable, q, framing) + suffix
                        report["rows"].append(row)
                        print(row, flush=True)
                        save(output / "results.json", report)
                        continue
                    groups = [[], []]
                    for block in range(blocks):
                        samples = []
                        block_record = dict(A=a, B=b, index=block, samples=[], accepted=False)
                        pass_entry["blocks"].append(block_record)
                        for i, arm in enumerate((a, b, b, a)):
                            folder = output / cell["id"] / phase / f"pair{pair_index}-block{block}-{i}-{arm}"
                            block_record["samples"].append(str(folder))
                            save(output / "results.json", report)
                            print(f"MEASURING {cell['id']} {phase} {a}->{b} block={block + 1} ABBA={i + 1} arm={arm}", flush=True)
                            sample = run_sample(cell, arm, identities, folder, q, guard)
                            samples.append(sample)
                            groups[0 if i in (0, 3) else 1].append(sample)
                        block_checks(samples, q, matched_pre=fixed_q is not None and pair_index == 0)
                        block_record["accepted"] = True
                    left, right = map(aggregate, groups)
                    comparison = dict(A=a, B=b, status="measured", left=left, right=right,
                                      samples=[[s["artifacts"] for s in g] for g in groups])
                    if pair_index == 0:
                        pass_entry["null"] = comparison
                        # Persist null evidence before any candidate in this pass.
                        save(output / "results.json", report)
                    else:
                        pass_entry["comparisons"].append(comparison)
                        row = endgame(cell, a, b, left, right, q, framing) + suffix
                        report["rows"].append(row)
                        print(row, flush=True)
                    save(output / "results.json", report)
                if phase == "plateau":
                    plateaus = primary_plateaus(pass_entry["comparisons"], identities)
                    q = math.floor(.8 * min(plateaus.values()) / CONNECTIONS)
                    require(q > 0, "plateau too low for a positive common q")
                    entry["plateau_frames_per_second"], entry["matched_q"] = plateaus, q
        report["complete"] = True
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        save(output / "results.json", report)
        (output / "endgame.txt").write_text("\n".join(report["rows"]) + "\n")


def self_test():
    import base64
    import copy
    import struct
    import unittest
    from unittest import mock
    import zlib

    def histogram(count):
        payload = bytearray()
        for signed in (-1000, count):
            n = signed * 2 if signed >= 0 else -signed * 2 - 1
            while n >= 128:
                payload.append((n & 127) | 128)
                n >>= 7
            payload.append(n)
        body = struct.pack(">IIiiQQd", 0x1c849303, len(payload), 0, 3, 1, 1000000, 1.) + payload
        compressed = zlib.compress(body)
        return base64.b64encode(struct.pack(">II", 0x1c849304, len(compressed)) + compressed).decode()

    def synthetic(cell, rounds=10000):
        counts = Counter(c.split()[0] for c in cell["workload"]["commands"])
        stats = {"Runtime": {"Interrupted": "false", "Time unit": "MILLISECONDS", "Total duration": 28000},
                 "Per-Key Misses": {}}
        for name, weight in counts.items():
            count = rounds * weight
            stats[name.capitalize() + "s"] = dict(Count=count, **{
                "Time-Serie": {"0": {"Count": count, "Bytes RX": count * (9 if name == "EXEC" else 4)}},
                "Aborts/sec": 0,
                "Percentile Latencies": {"Histogram log format": {"Compressed Histogram": histogram(count)}}})
            if name in ("EXEC", "GET"):
                stats["Per-Key Misses"][name] = {"Total Hits": count, "Total Misses": 0}
        stats["Totals"] = {"Count": sum(counts.values()) * rounds, "Connection Errors": 0,
                           "Connection Errors/sec": 0, "Aborts/sec": 0}
        return {"ALL STATS": stats}

    class Controls(unittest.TestCase):
        def setUp(self):
            self.cells = inventory()
            self.directory = tempfile.TemporaryDirectory(dir=ROOT / "build", prefix="exbatch-selftest-")
            self.addCleanup(self.directory.cleanup)
            self.folder = Path(self.directory.name)
            self.log = self.folder / "load.log"
            self.log.write_text("normal synthetic output\n")

        def parsed(self, cell, document):
            path = self.folder / "load.json"
            save(path, document)
            return parse_memtier(path, cell, self.log)

        def test_all_15_cells_all_6_arms_and_matched_argv(self):
            for cell in self.cells.values():
                for arm in ARMS:
                    argv = server_argv(cell, "/frozen/" + arm, self.folder)
                    self.assertEqual(argv[3], "/frozen/" + arm)
                    self.assertNotIn("{RUN_DIR}", argv)
                    for i in range(8):
                        plain = load_argv(cell, i, self.folder)
                        self.assertEqual(load_argv(cell, i, self.folder, 31), plain + ["--rate-limiting=31"])
                        self.assertNotIn("--key-pattern=P:P", plain)
                        self.assertIn("--test-time=28", plain)
                    self.assertEqual(len(comparisons(cell)), 4)
                poll = cell["id"].startswith(BASES[-1])
                self.assertEqual(load_argv(cell, 7, self.folder)[2], "99-110" if poll else "99-111")
                if poll:
                    self.assertEqual(worker_argv("poll", cell, self.folder)[2], "111")

        def test_required_grammar_missing_options_fail(self):
            text = " ".join("--" + n + "=VALUE" for n in REQUIRED_OPTIONS) + " individual connection rotation same key"
            check_help(text)
            for name in REQUIRED_OPTIONS:
                with self.assertRaisesRegex(RuntimeError, "MISSING"):
                    check_help(text.replace("--" + name + "=VALUE", ""))

        def test_dry_help_probe_accepts_exit_2_but_never_missing_grammar(self):
            text = " ".join("--" + n + "=VALUE" for n in REQUIRED_OPTIONS) + " individual connection rotation same key"
            expected = json.loads(INVENTORY.read_text())["memtier"]["sha256"]
            proc = subprocess.CompletedProcess([MEMTIER, "--help"], 2, stdout=text, stderr="")
            with mock.patch("subprocess.run", return_value=proc) as invoked, mock.patch.dict(globals(), digest=lambda p: expected):
                self.assertEqual(memtier_identity()["help_exit_status"], 2)
                invoked.assert_called_once_with([MEMTIER, "--help"], capture_output=True, text=True, timeout=10)
                proc.stdout = text.replace("--transaction=VALUE", "")
                with self.assertRaisesRegex(RuntimeError, "MISSING"):
                    memtier_identity()

        def test_synthetic_memtier_files_for_every_cell(self):
            for cell in self.cells.values():
                parsed = self.parsed(cell, synthetic(cell))
                self.assertEqual(sum(parsed["completed"].values()), 10000 * cell["workload"]["cycle_frames"])
                self.assertEqual(percentile(parsed["histogram"], 99), 1.)

        def test_one_exec_abort_cannot_hide_in_rounded_zero_rate(self):
            cell = self.cells[BASES[0] + "_f0"]
            document = synthetic(cell)
            document["ALL STATS"]["Per-Key Misses"]["EXEC"]["Total Misses"] = 1
            with self.assertRaisesRegex(RuntimeError, "WATCH aborted"):
                self.parsed(cell, document)

        def test_missing_exec_detector_bad_payload_and_error_log_fail(self):
            cell = self.cells[BASES[0] + "_f0"]
            for kind in ("missing", "payload", "error", "connection"):
                document = synthetic(cell)
                self.log.write_text("")
                if kind == "missing":
                    del document["ALL STATS"]["Per-Key Misses"]["EXEC"]
                elif kind == "payload":
                    document["ALL STATS"]["Execs"]["Time-Serie"]["0"]["Bytes RX"] -= 4
                elif kind == "error":
                    self.log.write_text("server 127.0.0.1 handle error response: -ERR bad\n")
                else:
                    document["ALL STATS"]["Totals"]["Connection Errors"] = 1
                with self.assertRaises(RuntimeError):
                    self.parsed(cell, document)

        def test_count_hdr_bound_is_finite_in_both_directions(self):
            cell = self.cells[BASES[2] + "_f0"]
            for difference in (-2049, -2048, 2048, 2049):
                document = synthetic(cell)
                row = document["ALL STATS"]["Objects"]
                row["Count"] += difference
                row["Time-Serie"]["0"]["Count"] += difference
                document["ALL STATS"]["Totals"]["Count"] += difference
                if abs(difference) > 2048:
                    with self.assertRaisesRegex(RuntimeError, "finite bound"):
                        self.parsed(cell, document)
                else:
                    self.parsed(cell, document)

        def test_invalid_json_histogram_or_missed_get_fails(self):
            cell = self.cells[BASES[-1] + "_s0"]
            document = synthetic(cell)
            document["ALL STATS"]["Per-Key Misses"]["GET"]["Total Misses"] = 1
            with self.assertRaisesRegex(RuntimeError, "GET missed"):
                self.parsed(cell, document)
            document = synthetic(cell)
            document["ALL STATS"]["Gets"]["Percentile Latencies"]["Histogram log format"]["Compressed Histogram"] = "broken"
            with self.assertRaises(Exception):
                self.parsed(cell, document)

        def test_perf_csv_same_scope_ipc_and_negative_controls(self):
            raw = "# perf stat\n" + "".join(f"CPU{cpu},{count},,{name},20000000000,100.00,,\n"
                       for cpu in range(8) for name, count in (("cycles", 200000000), ("instructions", 300000000)))
            parsed = parse_perf(raw)
            self.assertEqual(parsed["ipc"], 1.5)
            self.assertEqual(parsed["cycles"], 1600000000)
            for broken in (raw.replace("100.00", "99.99", 1), raw.replace("200000000,", "<not counted>,", 1),
                           raw.replace("CPU7", "CPU6"), raw.replace("20000000000", "19999999999", 1), ""):
                with self.assertRaises(RuntimeError):
                    parse_perf(broken)

        def perf_pipe(self):
            window = PerfWindow.__new__(PerfWindow)
            window.folder, window.ACK_TIMEOUT = self.folder, .03
            window.process = mock.Mock()
            window.process.poll.return_value = None
            ctl_reader, window.ctl = os.pipe2(os.O_NONBLOCK)
            window.ack, ack_writer = os.pipe2(os.O_NONBLOCK)
            for fd in (ctl_reader, window.ctl, window.ack, ack_writer):
                self.addCleanup(os.close, fd)
            return window, ctl_reader, ack_writer

        def test_perf_ack_fragmented_nul_and_newline_framing(self):
            read = os.read
            for payload in (b"ack\n", b"ack\n\x00", b"\x00ack\r\n\x00", b"ignored\nack\n\x00"):
                for width in (1, 2, 4096):
                    with self.subTest(payload=payload, width=width):
                        window, ctl_reader, ack_writer = self.perf_pipe()
                        os.write(ack_writer, payload)
                        with mock.patch("os.read", side_effect=lambda fd, size: read(fd, min(size, width))):
                            result = window.command("disable")
                        self.assertEqual(result["ack_lines"], 1)
                        self.assertEqual(result["ack_hex"], payload.hex())
                        self.assertEqual(read(ctl_reader, 4096), b"disable\n")
                        with self.assertRaises(BlockingIOError):
                            read(window.ack, 4096)

        def test_perf_ack_coalesced_lines_drained_not_reused(self):
            window, ctl_reader, ack_writer = self.perf_pipe()
            os.write(ack_writer, b"ack\n\x00ack\n\x00")
            self.assertEqual(window.command("enable")["ack_lines"], 2)
            with self.assertRaisesRegex(RuntimeError, "ACK timeout.*disable"):
                window.command("disable")
            self.assertEqual(os.read(ctl_reader, 4096), b"enable\ndisable\n")

        def test_perf_ack_missing_or_incomplete_line_times_out(self):
            for payload in (b"", b"ack", b"nack\n\x00"):
                with self.subTest(payload=payload):
                    window, _, ack_writer = self.perf_pipe()
                    if payload:
                        os.write(ack_writer, payload)
                    with self.assertRaisesRegex(RuntimeError, "ACK timeout.*received"):
                        window.command("enable")

        def test_perf_exit_before_or_after_ack_fails(self):
            for statuses in ([7], [None, 7]):
                window, _, ack_writer = self.perf_pipe()
                window.process.poll.side_effect = statuses
                os.write(ack_writer, b"ack\n\x00")
                with self.assertRaisesRegex(RuntimeError, "perf exited"):
                    window.command("enable")

        def test_rate_match_2_percent_and_invalid_values(self):
            rate_check([51200 * .98, 51200 * 1.02], 100)
            for rates in ([51200 * .979], [51200 * 1.021], [float("nan")], [0], []):
                with self.assertRaises(RuntimeError):
                    rate_check(rates, 100)
            with self.assertRaises(RuntimeError):
                rate_check([51200], 0)

        def test_wire_same_key_and_literal_affixes(self):
            for cell in self.cells.values():
                frames = [s.replace("__key__", "exbatch-1").replace("__data__", "x" * 64).split()
                          for s in cell["workload"]["commands"]] * 2
                validate_wire(cell, frames)
            cell = self.cells[BASES[0] + "_f0"]
            frames = [s.replace("__key__", "exbatch-1").replace("__data__", "x" * 64).split()
                      for s in cell["workload"]["commands"]] * 2
            broken = copy.deepcopy(frames)
            broken[3][1] = "w:exbatch-2"
            with self.assertRaisesRegex(RuntimeError, "different suffixes"):
                validate_wire(cell, broken)
            with self.assertRaisesRegex(RuntimeError, "two rotations"):
                validate_wire(cell, frames[:-1])

        def test_wire_failure_names_step_elapsed_and_partial_evidence(self):
            cell = self.cells[BASES[3] + "_f0"]
            stages = ("MONITOR connect", "MONITOR acknowledgement", "memtier exit", "MONITOR frames")
            for index, stage in enumerate(stages):
                with self.subTest(stage=stage):
                    folder = self.folder / str(index)
                    folder.mkdir()
                    (folder / "wire-probe.log").write_text("partial memtier evidence\n")
                    now = [1000.]
                    def timed_out(*args, **kwargs):
                        now[0] += 10
                        if stage == "memtier exit":
                            raise subprocess.TimeoutExpired([MEMTIER], 10)
                        raise TimeoutError("timed out")
                    conn = mock.Mock()
                    conn.must.return_value = b"OK"
                    proc = mock.Mock(pid=321)
                    proc.wait.return_value = 0
                    proc.poll.return_value = None if stage == "memtier exit" else 0
                    owned = mock.Mock()
                    owned.start.return_value = proc
                    connect = mock.Mock(return_value=conn)
                    if stage == "MONITOR connect":
                        connect.side_effect = timed_out
                    elif stage == "MONITOR acknowledgement":
                        conn.must.side_effect = timed_out
                    elif stage == "memtier exit":
                        proc.wait.side_effect = timed_out
                    else:
                        replies = iter([b'1 [0 local] "XGROUP" "CREATECONSUMER" "s:exbatch-1" "g" "c"'])
                        conn.read.side_effect = lambda: next(replies, None) or timed_out()
                    with mock.patch.dict(globals(), Conn=connect), mock.patch("time.monotonic", lambda: now[0]):
                        with self.assertRaises(StepFailure) as caught:
                            wire_probe(cell, folder, owned, dict(path="/guard.so"))
                    self.assertIn(f"wire-probe/{stage} failed after 10.000s", str(caught.exception))
                    self.assertIn("partial memtier evidence", str(caught.exception))
                    detail = json.loads((folder / "wire-probe-failure.json").read_text())
                    self.assertEqual(detail["step"], stage)
                    self.assertEqual(detail["elapsed_seconds"], 10)
                    evidence = detail["evidence"]
                    self.assertEqual(evidence["expected_frames"], 2)
                    self.assertEqual(evidence["received_frames"], 1 if stage == "MONITOR frames" else 0)
                    self.assertIn("wire-probe-zero.json", evidence["artifacts"])
                    if stage == "MONITOR frames":
                        self.assertEqual(evidence["exit_status"], 0)
                        self.assertEqual(evidence["frames"][0][0], "XGROUP")

        def test_wire_success_reaps_then_keeps_guard_and_transaction_witnesses(self):
            for base in (BASES[0], BASES[3]):
                cell = self.cells[base + "_f0"]
                frames = [s.replace("__key__", "exbatch-1").replace("__data__", "x" * 64).split()
                          for s in cell["workload"]["commands"]] * 2
                raw = iter(('1 [0 local] ' + ' '.join(json.dumps(s) for s in frame)).encode() for frame in frames)
                save(self.folder / "wire-probe.json", synthetic(cell, rounds=2))
                (self.folder / "wire-probe.log").write_text("")
                if base == BASES[3]:
                    save(self.folder / "wire-probe-zero.json", dict(connections=1, bytes=8, zero_replies=2))
                exited = []
                conn, proc, owned = mock.Mock(), mock.Mock(pid=321), mock.Mock()
                conn.must.return_value = b"OK"
                def read():
                    self.assertTrue(exited, "MONITOR read masked an unchecked child exit")
                    return next(raw)
                conn.read.side_effect = read
                proc.wait.side_effect = lambda timeout: exited.append(True) or 0
                owned.start.return_value = proc
                with mock.patch.dict(globals(), Conn=lambda *a, **k: conn):
                    record = wire_probe(cell, self.folder, owned, dict(path="/guard.so"))
                self.assertTrue(record["complete"])
                self.assertEqual(record["frames"], frames)
                self.assertEqual(sum(record["completed"].values()), len(frames))
                if base == BASES[3]:
                    self.assertEqual(record["zero_reply_guard"]["zero_replies"], 2)
                self.assertTrue((self.folder / "wire-witness.json").exists())
                conn.close.assert_called_once()

        def test_wire_guard_exit_is_not_hidden_by_monitor_timeout(self):
            conn = mock.Mock()
            conn.must.return_value = b"OK"
            conn.read.side_effect = AssertionError("must notice child exit before reading MONITOR")
            proc = mock.Mock(pid=321)
            proc.wait.return_value = proc.poll.return_value = 86
            owned = mock.Mock()
            owned.start.return_value = proc
            (self.folder / "wire-probe.log").write_text("EXBATCH ZERO-REPLY GUARD FAILED: cannot create receipt\n")
            (self.folder / "wire-probe-zero.json").touch()
            with mock.patch.dict(globals(), Conn=lambda *a, **k: conn):
                with self.assertRaisesRegex(StepFailure, "memtier exit.*exited 86.*cannot create receipt"):
                    wire_probe(self.cells[BASES[3] + "_f0"], self.folder, owned, dict(path="/guard.so"))
            conn.read.assert_not_called()
            conn.close.assert_called_once()
            evidence = json.loads((self.folder / "wire-probe-failure.json").read_text())["evidence"]
            self.assertEqual(evidence["exit_status"], 86)
            self.assertEqual(evidence["artifacts"]["wire-probe-zero.json"]["bytes"], 0)

        def test_warm_and_verify_timeout_retains_key_command_and_reply_progress(self):
            cell = copy.deepcopy(self.cells[BASES[3] + "_s0"])
            cell["memtier_instances"][0]["key_max"] = 1
            for verify in (False, True):
                conn = mock.Mock()
                conn.read.side_effect = [1 if verify else b"1-0", TimeoutError("timed out")]
                kind = "verify" if verify else "warm"
                with mock.patch.dict(globals(), Conn=lambda *a, **k: conn):
                    with self.assertRaisesRegex(StepFailure, f"{kind}-0/batch replies failed after"):
                        warm_worker(cell, 0, self.folder, verify_only=verify)
                detail = json.loads((self.folder / f"{kind}-0-failure.json").read_text())
                evidence = detail["evidence"]
                self.assertEqual(evidence["key_min"], 1)
                self.assertEqual(evidence["replies_checked"], 1)
                self.assertEqual(evidence["command"][:2], ["XINFO", "GROUPS"] if verify else ["XGROUP", "CREATE"])
                self.assertFalse((self.folder / f"{kind}-0.json").exists())
                conn.close.assert_called_once()

        def test_xgroup_guard_rejects_new_consumer_or_cardinality(self):
            check_reply(0, 0, "XGROUP CREATECONSUMER")
            with self.assertRaises(RuntimeError):
                check_reply(1, 0, "XGROUP CREATECONSUMER")
            good = [[b"name", b"c", b"pending", 0]]
            check_reply(good, "consumers", "XINFO CONSUMERS")
            with self.assertRaises(RuntimeError):
                check_reply(good * 2, "consumers", "XINFO CONSUMERS")

        def test_xgroup_scored_wire_receipt_must_match_exact_hdr(self):
            path = self.folder / "guard.json"
            save(path, dict(connections=64, bytes=40000, zero_replies=10000))
            check_zero_receipt(path, 10000, 64)
            for field in ("connections", "bytes", "zero_replies"):
                data = dict(connections=64, bytes=40000, zero_replies=10000)
                data[field] -= 1
                save(path, data)
                with self.assertRaises(RuntimeError):
                    check_zero_receipt(path, 10000, 64)

        def test_missing_partial_arms_rebuild_from_sha_bound_receipts(self):
            root = self.folder
            pre, post = b"synthetic PRE", b"prefix" + bytes.fromhex("0f1f440000") + b"suffix"
            old = post[:6] + bytes.fromhex("e900000000") + post[11:]
            paths = {a: root / ("build/tomokv" if a == "POST" else
                               "build/exbatch/PRE/build/tomokv" if a == "PRE" else f"build/exbatch/{a}/tomokv") for a in ARMS}
            for arm, raw in (("PRE", pre), ("POST", post)):
                paths[arm].parent.mkdir(parents=True, exist_ok=True)
                paths[arm].write_bytes(raw)
            for arm in ("PAD-A", "EX1-OLD", "EX3-OLD", "EX6-OLD"):
                path = root / "docs/exbatch" / ("pad-a" if arm == "PAD-A" else arm.lower())
                path.mkdir(parents=True)
                save(path / "planned-retargets.json", dict(source_sha256=hashlib.sha256(post).hexdigest(),
                    patches=[dict(offset=6, before="0f1f440000", after="e900000000")]))
            receipt = root / "binaries.json"
            save(receipt, dict(pre_commit="unused", artifacts=[dict(arm=a, sha256=hashlib.sha256(
                pre if a == "PRE" else post if a == "POST" else old).hexdigest()) for a in ARMS]))
            with mock.patch.dict(globals(), ROOT=root, RECEIPTS=receipt):
                result = prepare_arms()
                self.assertTrue(all(result[a]["sha256"] == result[a]["expected_sha256"] for a in ARMS))
                self.assertEqual(paths["EX6-OLD"].read_bytes(), old)
                paths["EX1-OLD"].unlink()
                paths["POST"].write_bytes(b"changed")
                with self.assertRaisesRegex(RuntimeError, "POST SHA"):
                    prepare_arms()

        def arms_fixture(self, arms=("PRE", "POST")):
            entries = {}
            for arm in arms:
                binary = self.folder / arm
                binary.write_text("synthetic " + arm)
                binary.chmod(0o700)
                entries[arm] = dict(path=arm, sha256=digest(binary))
            receipt = self.folder / "arms.json"
            save(receipt, entries)
            return receipt, entries

        def test_explicit_receipt_binds_relative_paths_and_itself(self):
            receipt, entries = self.arms_fixture(("PRE", "POST", "EX6-OLD"))
            table, identity = bind_arms(receipt)
            self.assertEqual(identity, dict(path=str(receipt), sha256=digest(receipt), source="--arms"))
            self.assertEqual(set(table), set(entries))
            # A replacement must work even if the frozen binaries/receipts are gone.
            with mock.patch.dict(globals(), RECEIPTS=self.folder / "absent-frozen.json"), \
                 mock.patch.dict(globals(), arm_paths=mock.Mock(side_effect=AssertionError("frozen fallback"))):
                bound = prepare_arms(table=table)
            for arm in entries:
                self.assertEqual(bound[arm]["path"], str(self.folder / arm))
                self.assertEqual(bound[arm]["sha256"], entries[arm]["sha256"])
            self.assertNotIn("PAD-A", bound)
            verify_receipt(identity)
            receipt.write_text(receipt.read_text() + "\n")
            with self.assertRaisesRegex(RuntimeError, "receipt changed"):
                verify_receipt(identity)

        def test_explicit_sha_mismatch_refuses_real_and_dry_runs(self):
            receipt, _ = self.arms_fixture()
            table, _ = bind_arms(receipt)
            (self.folder / "POST").write_text("wrong binary")
            for dry in (False, True):
                with self.assertRaisesRegex(RuntimeError, "POST SHA differs from explicit"):
                    prepare_arms(dry=dry, table=table)

        def test_explicit_missing_or_nonexecutable_arm_never_falls_back(self):
            receipt, _ = self.arms_fixture()
            table, _ = bind_arms(receipt)
            (self.folder / "POST").chmod(0o600)
            with self.assertRaisesRegex(RuntimeError, "POST binary missing/not executable"):
                prepare_arms(table=table)
            (self.folder / "POST").unlink()
            with self.assertRaisesRegex(RuntimeError, "POST binary missing/not executable"):
                prepare_arms(dry=True, table=table)

        def test_explicit_receipt_rejects_bad_schema_and_duplicate_fields(self):
            receipt, entries = self.arms_fixture()
            bad = [[], {}, {"PRE": entries["PRE"]}, dict(entries, TYPO=entries["POST"]),
                   dict(entries, POST={"path": "POST", "sha256": "bad"}),
                   dict(entries, POST={"path": "", "sha256": entries["POST"]["sha256"]}),
                   dict(entries, POST=dict(entries["POST"], extra=1))]
            for document in bad:
                save(receipt, document)
                with self.assertRaises(RuntimeError):
                    bind_arms(receipt)
            for raw in ('{"PRE": {}, "PRE": {}}', '{"PRE": {"path": "x", "path": "y"}}'):
                receipt.write_text(raw)
                with self.assertRaisesRegex(RuntimeError, "duplicate"):
                    bind_arms(receipt)

        def test_explicit_dry_cli_skips_unavailable_controls_without_creating_output(self):
            import io
            receipt, _ = self.arms_fixture()
            output = self.folder / "dry-output"
            stream = io.StringIO()
            with mock.patch.dict(globals(), memtier_identity=mock.Mock(return_value={})), \
                 contextlib.redirect_stdout(stream):
                code = main(["--dry-run", "--arms", str(receipt), "--cell", BASES[3],
                             "--regime", "f0", "--output", str(output)])
            self.assertEqual(code, 0)
            self.assertFalse(output.exists())
            text = stream.getvalue()
            self.assertIn(digest(receipt), text)
            self.assertIn(str(receipt), text)
            self.assertEqual(text.count("# warmup 3s;"), 16)
            self.assertEqual(text.count("not available;"), 6)
            self.assertIn("mean PRE/POST primary plateau", text)
            self.assertNotIn(str(output / "arms/PAD-A"), text)
            self.assertNotIn(str(output / "arms/EX6-OLD"), text)

        def test_explicit_run_records_skips_and_uses_only_available_primary_plateaus(self):
            import io
            cell = self.cells[BASES[3] + "_s0"]
            for optional in ((), ("PAD-A",), ("EX6-OLD",), ("PAD-A", "EX1-OLD", "EX3-OLD", "EX6-OLD")):
                receipt_path, _ = self.arms_fixture(("PRE", "POST") + optional)
                table, receipt = bind_arms(receipt_path)
                identities = prepare_arms(table=table)
                output = self.folder / ("run-" + "-".join(optional))
                calls = []
                def sample(cell, arm, identities, folder, q, guard):
                    calls.append((arm, q))
                    self.assertEqual(digest(identities[arm]["path"]), table[arm]["sha256"])
                    # Partial controls cannot lower the common matched-load target.
                    rate = (1000 if arm.endswith("OLD") else 512000) if q is None else q * CONNECTIONS
                    return dict(arm=arm, complete=True, rate=rate, frames=100, cycles=400, instructions=800,
                                histogram={1: 100}, saturation=dict(score_pct=100), artifacts=str(folder))
                with mock.patch.dict(globals(), run_sample=sample, prepare_guard=mock.Mock(return_value=None)), \
                     mock.patch.object(os, "sched_getaffinity", return_value=set(range(112))), \
                     mock.patch.object(os, "sched_setaffinity"), \
                     mock.patch.object(subprocess, "check_output", return_value="synthetic-commit\n"), \
                     contextlib.redirect_stdout(io.StringIO()):
                    run([cell], identities, output, 1, {}, receipt)
                result = json.loads((output / "results.json").read_text())
                self.assertTrue(result["complete"])
                self.assertEqual(result["arms_receipt"], receipt)
                self.assertEqual(set(result["unavailable_arms"]), set(ARMS) - set(table))
                entry = result["cells"][cell["id"]]
                self.assertEqual(entry["matched_q"], 800)
                self.assertEqual(set(entry["plateau_frames_per_second"]), {"PRE", "POST"} | (set(optional) & {"PAD-A"}))
                skipped = 0
                for phase in entry["passes"].values():
                    self.assertEqual(len(phase["comparisons"]), 4)
                    for comp in phase["comparisons"]:
                        missing = {comp["A"], comp["B"]} - set(table)
                        if missing:
                            skipped += 1
                            self.assertEqual(comp["status"], "not available")
                            self.assertEqual(set(comp["missing_arms"]), missing)
                            self.assertNotIn("left", comp)
                        else:
                            self.assertEqual(comp["status"], "measured")
                self.assertEqual(len(calls), (10 - skipped) * 4)
                self.assertTrue(all(a in table for a, _ in calls))
                self.assertEqual(len(result["rows"]), 8)
                self.assertEqual(sum("not available;" in row for row in result["rows"]), skipped)
                self.assertEqual((output / "endgame.txt").read_text(), "\n".join(result["rows"]) + "\n")

        def test_matched_only_cli_validation_and_quantization(self):
            import io
            self.assertEqual(validate_score("plateau-then-matched", None), None)
            self.assertEqual(validate_score("matched-only", 433147), 845)
            self.assertEqual(validate_score("matched-only", 438272), 856)
            for score, load in (("matched-only", None), ("matched-only", 0), ("matched-only", -1),
                                ("matched-only", 511), ("plateau-then-matched", 438272)):
                with self.subTest(score=score, load=load), self.assertRaises(RuntimeError):
                    validate_score(score, load)
            for extra in (["--score", "wrong"], ["--matched-load", "nan"],
                          ["--matched-load", "1.5"], ["--cores", "112-127"]):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    main(["--dry-run", "--output", str(self.folder / "unused"), *extra])
                self.assertEqual(caught.exception.code, 2)
            for extra in (["--score", "matched-only"], ["--matched-load", "438272"],
                          ["--score", "matched-only", "--matched-load", "511"], ["--blocks", "0"]):
                with self.assertRaises(RuntimeError):
                    main(["--dry-run", "--output", str(self.folder / "unused"), *extra])
            self.assertFalse((self.folder / "unused").exists())

        def test_matched_only_dry_cli_has_only_matched_blocks_on_selected_cores(self):
            import io
            receipt, _ = self.arms_fixture()
            output = self.folder / "matched-dry"
            stream = io.StringIO()
            with mock.patch.dict(globals(), memtier_identity=mock.Mock(return_value={})), \
                 contextlib.redirect_stdout(stream):
                self.assertEqual(main(["--dry-run", "--score", "matched-only", "--matched-load", "433147",
                    "--cores", "112-119,120-127", "--arms", str(receipt), "--cell", BASES[3],
                    "--regime", "s0", "--blocks", "2", "--output", str(output)]), 0)
            text = stream.getvalue()
            self.assertEqual(text.count("# warmup 3s;"), 16)
            self.assertEqual(text.count("not available;"), 3)
            self.assertIn("offered=432640 frames/s", text)
            self.assertIn("--rate-limiting=845", text)
            self.assertIn("plateau=skipped", text)
            self.assertNotIn("/plateau/", text)
            self.assertNotIn("primary plateau", text)
            for line in text.splitlines():
                argv = shlex.split(line)
                if "taskset" in argv and not line.startswith("#"):
                    at = argv.index("taskset")
                    spec = argv[at + 2]
                    cpus = set(cpu_ids(spec)) if "-" in spec else {int(spec)}
                    self.assertLessEqual(cpus, set(range(112, 128)))
            self.assertFalse(output.exists())

        def test_matched_only_campaign_scores_agreeing_pre_and_refuses_disagreeing_pre(self):
            import io
            cases = (("agree", [100, 101, 100.5, 100], None),
                     ("boundary", [100, 102, 100, 100], None),
                     ("bad-repeat", [100, 100, 104, 100], 4),
                     ("bad-sides", [100, 104, 104, 100], 4),
                     ("bad-later-block", [100] * 4 + [100, 104, 100, 100], 8))
            for name, costs, refused_after in cases:
                receipt_path, _ = self.arms_fixture()
                output = self.folder / name
                calls = []
                def sample(cell, arm, identities, folder, q, guard):
                    self.assertEqual(q, 856, "matched-only launched an unlimited plateau")
                    calls.append((arm, q))
                    cost = costs[(len(calls) - 1) % len(costs)] if arm == "PRE" else 20
                    return dict(arm=arm, complete=True, rate=CONNECTIONS * q, frames=100,
                                cycles=100 * cost, instructions=200 * cost, histogram={1: 100},
                                artifacts=str(folder))  # No saturation witness: matched-only must not require one.
                with mock.patch.dict(globals(), run_sample=sample, prepare_guard=mock.Mock(return_value=None),
                                     memtier_identity=mock.Mock(return_value={}), quiet_file_guard=lambda: None), \
                     mock.patch.object(os, "sched_getaffinity", return_value=set(range(112, 128))), \
                     mock.patch.object(os, "sched_setaffinity") as affinity, \
                     mock.patch.object(subprocess, "check_output", return_value="synthetic-commit\n"), \
                     contextlib.redirect_stdout(io.StringIO()):
                    argv = ["--score", "matched-only", "--matched-load", "438272", "--cores", "112-119,120-127",
                            "--arms", str(receipt_path), "--cell", BASES[3], "--regime", "s0",
                            "--blocks", "2", "--output", str(output)]
                    if refused_after:
                        with self.assertRaisesRegex(RuntimeError,
                                r"same-arm matched repeats differ >2%; arm=PRE cyc/op=100.000000/104.000000"):
                            main(argv)
                    else:
                        self.assertEqual(main(argv), 0)
                    affinity.assert_called_once_with(0, {120})
                result = json.loads((output / "results.json").read_text())
                entry = result["cells"][BASES[3] + "_s0"]
                self.assertEqual(set(entry["passes"]), {"matched"})
                self.assertEqual(entry["plateau"], "skipped")
                self.assertEqual(entry["matched_q"], 856)
                self.assertEqual(result["matched_load"]["offered_frames_per_second"], 438272)
                if refused_after:
                    self.assertFalse(result["complete"])
                    self.assertEqual(len(calls), refused_after)
                    self.assertTrue(all(arm == "PRE" for arm, _ in calls))
                    self.assertEqual(result["rows"], [])
                    self.assertFalse(entry["passes"]["matched"]["blocks"][-1]["accepted"])
                else:
                    self.assertTrue(result["complete"])
                    self.assertEqual(len(calls), 16)  # two null blocks, two comparison blocks
                    self.assertEqual(len(entry["passes"]["matched"]["blocks"]), 4)
                    self.assertEqual(len(result["rows"]), 4)
                    self.assertEqual(sum("not available;" in row for row in result["rows"]), 3)
                    self.assertTrue(all(row.endswith(" plateau=skipped") for row in result["rows"]))
                    self.assertRegex(result["rows"][0], r"^EXBATCH-DIRECTED exbatch_xgroup32 s0 PRE->POST rate=.*cyc/op=.*instr/op=.*ipc=.*matched=856")
                self.assertEqual((output / "endgame.txt").read_text(), "\n".join(result["rows"]) + "\n")

        def test_core_override_routes_helpers_and_validates_pmu_and_roles(self):
            self.assertEqual(parse_cores("0-7,8-111"), DEFAULT_CORES)
            for bad in ("0-7,7-14", "0-6,8-15", "0-8,9-16", "112-119,120-126",
                        "119-112,120-127", "-1-6,8-15", "0-7,16-8", "0-7,8-9,10-11"):
                with self.assertRaises(argparse.ArgumentTypeError):
                    parse_cores(bad)
            original = copy.deepcopy(self.cells)
            configure_cores(self.cells, DEFAULT_CORES)
            self.assertEqual(original, self.cells)
            cores = parse_cores("112-119,120-127")
            configure_cores(self.cells, cores)
            for cell in self.cells.values():
                self.assertEqual(server_argv(cell, "/arm", self.folder)[2], "112-119")
                for i in range(8):
                    self.assertEqual(load_argv(cell, i, self.folder)[2], str(120 + i))
                    for kind in ("warm", "verify"):
                        argv = worker_argv(kind, cell, self.folder, i)
                        self.assertEqual(argv[2], str(120 + i))
                        self.assertEqual(argv[-2:], ["--cores", "112-119,120-127"])
                self.assertEqual(worker_argv("poll", cell, self.folder)[2], "127")
            self.assertEqual(guard_build_argv(self.folder, cores=cores)[2], "120-127")
            argv = perf_argv(self.folder, cores)
            self.assertEqual(argv[2], "120")
            self.assertEqual(argv[argv.index("-C") + 1], "112-119")
            raw = "".join(f"CPU{cpu},{count},,{name},20000000000,100.00,,\n"
                          for cpu in range(112, 120) for name, count in (("cycles", 200), ("instructions", 300)))
            self.assertEqual(parse_perf(raw, range(112, 120))["cycles"], 1600)
            with self.assertRaisesRegex(RuntimeError, "server CPUs"):
                parse_perf(raw)
            signals = b"lbver 1 stamp_ns 1000000000\n" + b"".join(
                f"thread {i} {'io' if i < 6 else 'ex'} 0 {1 if i < 6 else 0} 1 1 1000 1000 99999999\n".encode() for i in range(8))
            boot = {"thread_cpus": ",".join(f"{i}:{112 + i}" for i in range(8))}
            self.assertEqual(role_cpus(parse_snapshot(signals), "s0", boot, range(112, 120)),
                             {"io": list(range(112, 118)), "ex": [118, 119]})
            with self.assertRaisesRegex(RuntimeError, "geometry changed"):
                role_cpus(parse_snapshot(signals), "s0", boot)

        def test_mainline_framing_is_sha_bound_and_explains_landing_scope_in_rows(self):
            headline = json.loads(MAINLINE_RECEIPT.read_text())
            framing = measurement_framing(headline, dict(source="--arms"))
            self.assertEqual(framing["name"], "mainline")
            cell = self.cells[BASES[3] + "_f0"]
            side = dict(rate=1, p50=1, p99=1, cycles_per_op=1, instr_per_op=1, ipc=1)
            row = endgame(cell, "PRE", "POST", side, side, None, framing)
            self.assertIn("includes every landing between them (only exbatch)", row)
            skipped = unavailable_comparison("PRE", "PAD-A", headline)
            self.assertIn("framing=mainline", unavailable_row(cell, skipped, 1, framing))
            headline["POST"]["sha256"] = "0" * 64
            self.assertEqual(measurement_framing(headline, dict(source="--arms"))["name"], "explicit")

        def test_dry_plan_uses_frozen_paths_and_guard_without_launching(self):
            import io
            cell = self.cells[BASES[3] + "_s0"]
            identities = {a: dict(path="/source/" + a, sha256="synthetic") for a in ARMS}
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                dry_run([cell], identities, self.folder, 1)
            text = stream.getvalue()
            self.assertEqual(text.count("# warmup 3s;"), 40)
            self.assertIn("LD_PRELOAD=", text)
            self.assertIn(str(self.folder / "arms/EX6-OLD/tomokv"), text)
            self.assertIn("--rate-limiting=Q_" + cell["id"], text)
            self.assertNotIn("--key-pattern=P:P", text)

        def test_mocked_sample_lifecycle_and_failure_cleanup(self):
            # Run the real orchestration with in-memory children/counters/clock.
            # Any unmocked subprocess/socket call is trapped by self_test's outer guards.
            cell = self.cells[BASES[2] + "_f0"]
            for q in (None, 1000):
                folder = self.folder / ("success" if q is None else "rate-failure")
                now = [1000.]
                processes, dbsizes, endpoints, lb_calls = [], [0, 1000000, 1000000], [0, 0, 80000, 80000], []
                boot = dict(process_id="123", read_local="0", pin_threads="1", net_io="uring", atomic="1",
                            key_lb="1", client_lb="1", flip_auto="0", shards="16", reorder="0",
                            thread_mode="1s", thread_cpus=",".join(f"{i}:{i}" for i in range(8)))

                class Process:
                    pid = 123
                    def __init__(self, load=False):
                        self.load, self.done = load, False
                    def poll(self):
                        return 0 if self.done else None
                    def wait(self, timeout=None):
                        self.done = True
                        return 0

                class Owned:
                    def __init__(self):
                        self.processes = processes
                    def start(self, argv, log, cwd, extra_env=None):
                        load = Path(log).name.startswith("load-")
                        p = Process(load)
                        processes.append(p)
                        Path(log).write_text("")
                        if load:
                            save(Path(log).with_suffix(".json"), synthetic(cell))
                        if "--worker" in argv:
                            i = argv[argv.index("--instance") + 1]
                            save(folder / f"warm-{i}.json", dict(complete=True))
                        return p
                    def stop(self, p, sig=None):
                        p.done = True
                    def close(self):
                        for p in processes:
                            p.done = True

                class Client:
                    def must(self, *args):
                        if args[0] == "DBSIZE":
                            return dbsizes.pop(0)
                        if args == ("DEBUG", "LBSIGNALS"):
                            after = bool(lb_calls)
                            lb_calls.append(True)
                            stamp, cpu = (21000000000, 20000000000) if after else (1000000000, 0)
                            return f"lbver 1 stamp_ns {stamp}\n".encode() + b"".join(
                                f"thread {i} fused 0 64 1 {1000000 if after else 0} {cpu} 0 {cpu}\n".encode()
                                for i in range(8))
                        raise AssertionError(args)
                    def close(self):
                        pass

                def fake_info(conn, section):
                    if section == "server": return boot
                    if section == "clients": return {"connected_clients": 1 + 64 * sum(p.load and not p.done for p in processes)}
                    if section == "stats": return {"keyspace_misses": 0}
                    if section == "commandstats": return {"cmdstat_object": f"calls={endpoints.pop(0)}"}
                    raise AssertionError(section)

                class Quiet:
                    def __init__(self, *args, **kwargs): pass
                    def start(self): return self
                    def evidence(self): return dict(complete=True)
                    def check(self): pass
                    def close(self): return self.evidence()

                class Perf:
                    identity = dict(path="/fake/perf", sha256="bound")
                    def __init__(self, *args): pass
                    def command(self, command): return dict(before=now[0], after=now[0])
                    def finish(self):
                        return parse_perf("".join(f"CPU{i},{n},,{name},20000000000,100.00,,\n"
                            for i in range(8) for name, n in (("cycles", 200000000), ("instructions", 300000000))))
                    def close(self): pass

                def fake_digest(path):
                    return json.loads(INVENTORY.read_text())["memtier"]["sha256"] if str(path) == MEMTIER else "bound"

                class Socket:
                    def __enter__(self): return self
                    def __exit__(self, *args): pass
                    def setsockopt(self, *args): pass
                    def bind(self, *args): pass

                with mock.patch.dict(globals(), Children=Owned, QuietMonitor=Quiet, Conn=lambda *a, **k: Client(),
                                     PerfWindow=Perf, info=fake_info, digest=fake_digest, quiet_file_guard=lambda: None,
                                     wire_probe=lambda *a: dict(complete=True)), \
                     mock.patch("socket.socket", Socket), \
                     mock.patch("time.monotonic", lambda: now[0]), \
                     mock.patch("time.sleep", lambda delay: now.__setitem__(0, now[0] + delay)):
                    if q is None:
                        result = run_sample(cell, "PRE", {"PRE": dict(path="/fake/PRE", sha256="bound")}, folder, q)
                        self.assertEqual(result["frames"], 80000)
                        self.assertEqual(result["rate"], 4000)
                        self.assertEqual(len(result["argv"]["load"]), 8)
                        self.assertTrue(result["complete"])
                    else:
                        with self.assertRaisesRegex(RuntimeError, "2%"):
                            run_sample(cell, "PRE", {"PRE": dict(path="/fake/PRE", sha256="bound")}, folder, q)
                self.assertTrue(all(p.done for p in processes))
                self.assertEqual(json.loads((folder / "sample.json").read_text())["complete"], q is None)
                if q is not None:
                    failure = json.loads((folder / "sample-failure.json").read_text())
                    self.assertEqual(failure["step"], "perf finish and counter validation")
                    self.assertEqual(len(failure["evidence"]["children"]), len(processes))

        def test_role_cpu_map_does_not_confuse_cpu_time_with_placement(self):
            raw = b"lbver 1 stamp_ns 1000000000\n" + b"".join(
                f"thread {i} {'io' if i < 6 else 'ex'} 0 {1 if i < 6 else 0} 1 1 1000 1000 99999999\n".encode()
                for i in range(8))
            boot = {"thread_cpus": ",".join(f"{i}:{i}" for i in range(8))}
            self.assertEqual(role_cpus(parse_snapshot(raw), "s0", boot), {"io": list(range(6)), "ex": [6, 7]})

        def test_block_match_05_percent_and_plateau_rejection(self):
            samples = [dict(rate=51200, saturation={"score_pct": 99}) for _ in range(4)]
            block_checks(samples, 100)
            samples[1]["rate"] = samples[2]["rate"] = 51712
            with self.assertRaisesRegex(RuntimeError, "0.5%"):
                block_checks(samples, 100)
            samples[1]["saturation"]["score_pct"] = 80
            with self.assertRaisesRegex(RuntimeError, "occupancy"):
                block_checks(samples, None)

        def test_matched_precondition_preserves_rate_checks_and_default_mode(self):
            samples = [dict(arm="PRE", rate=51200, cycles=100, frames=1) for _ in range(4)]
            block_checks(samples, 100, matched_pre=True)
            samples[3]["cycles"] = 102.0001
            block_checks(samples, 100)  # Existing matched scoring keeps its old acceptance rules.
            with self.assertRaisesRegex(RuntimeError, "same-arm matched repeats differ >2%"):
                block_checks(samples, 100, matched_pre=True)
            samples[3]["cycles"] = 100
            for cost in (0, float("nan"), float("inf")):
                samples[0]["cycles"] = cost
                with self.assertRaisesRegex(RuntimeError, "invalid matched cyc/op"):
                    block_checks(samples, 100, matched_pre=True)
            samples[0]["cycles"] = 100
            samples[1]["rate"] = samples[2]["rate"] = 51712
            with self.assertRaisesRegex(RuntimeError, "matched arm means differ >0.5%"):
                block_checks(samples, 100, matched_pre=True)
            samples[1]["rate"] = samples[2]["rate"] = 53000
            with self.assertRaisesRegex(RuntimeError, "achieved rate outside 2%"):
                block_checks(samples, 100, matched_pre=True)

        def test_plateau_rejection_keeps_two_percent_limit_and_reports_both_repeats(self):
            samples = [dict(arm="PRE", rate=100, saturation={"score_pct": 99}, artifacts=f"sample-{i}")
                       for i in range(4)]
            samples[3]["rate"] = 102
            block_checks(samples, None)
            samples[3]["rate"] = 102.0001
            with self.assertRaisesRegex(RuntimeError, "arm=PRE rates=100.000000/102.000100.*spread=.*sample-0.*sample-3"):
                block_checks(samples, None)
            samples[3]["rate"] = 100
            samples[1]["rate"] = 103
            with self.assertRaisesRegex(RuntimeError, "rates=103.000000/100.000000.*sample-1.*sample-2"):
                block_checks(samples, None)

        def test_aggregate_pools_histograms_and_pmu_numerators(self):
            sample = dict(complete=True, frames=100, cycles=1000, instructions=1500, rate=5,
                          histogram={1000: 90, 9000: 10})
            result = aggregate([sample, sample])
            self.assertEqual((result["p50"], result["p99"], result["cycles_per_op"], result["ipc"]), (1., 9., 10., 1.5))
            row = endgame(self.cells[BASES[0] + "_f0"], "PRE", "POST", result, result, 17)
            self.assertEqual(row, "EXBATCH-DIRECTED exbatch_watch_w32 f0 PRE->POST rate=5.00/5.00 (+0.00%) "
                             "p50=1.000/1.000 p99=9.000/9.000 cyc/op=10.000/10.000 (+0.00%) "
                             "instr/op=15.000/15.000 ipc=1.5000/1.5000 matched=17")

    class NativeGuardControl(unittest.TestCase):
        def test_preload_survives_taskset_exec_and_still_rejects_bad_or_missing_replies(self):
            # The in-memory unit is exported ONLY by this test library. The tiny
            # driver calls it after taskset's real exec; neither opens a socket.
            with tempfile.TemporaryDirectory(dir=ROOT / "build", prefix="exbatch-guard-selftest-") as tmp:
                folder = Path(tmp)
                library, driver = folder / "guard.so", folder / "driver"
                (folder / "guard.c").write_text(ZERO_REPLY_GUARD + ZERO_REPLY_UNIT)
                (folder / "driver.c").write_text('''
#include <dlfcn.h>
int main(int argc, char **argv) {
    int (*unit)(const char *) = dlsym(RTLD_DEFAULT, "guard_unit");
    return argc == 2 && unit ? unit(argv[1]) : 2;
}
''')
                for name, flags in (("guard", ["-shared", "-fPIC"]), ("driver", [])):
                    subprocess.run(["taskset", "-c", "112-127", "cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                                    *flags, "-o", str(library if name == "guard" else driver),
                                    str(folder / (name + ".c")), "-ldl"], check=True, capture_output=True, timeout=30)
                for mode in ("good", "bad", "error", "partial", "empty", "good"):
                    receipt = folder / (mode + ".json")
                    existed = receipt.exists()
                    proc = subprocess.run(["taskset", "-c", "112", str(driver), mode],
                        env={**os.environ, "LD_PRELOAD": str(library), "EXBATCH_ZERO_RECEIPT": str(receipt)},
                        capture_output=True, text=True, timeout=5)
                    with self.subTest(mode=mode, existed=existed):
                        self.assertEqual(proc.returncode, 0 if mode == "good" and not existed else 86, proc.stderr)
                        if mode == "good":
                            check_zero_receipt(receipt, 38, 1)
                            if existed:
                                self.assertIn("cannot create receipt", proc.stderr)
                        else:
                            self.assertIn("EXBATCH ZERO-REPLY GUARD FAILED:", proc.stderr)
                            self.assertNotIn("cannot create receipt", proc.stderr)
                            self.assertFalse(receipt.exists())

    class RealPerfControl(unittest.TestCase):
        def test_busy_loop_counts_only_inside_enabled_window(self):
            # Availability is checked WITHOUT control FIFOs: a broken handshake
            # after a successful PMU probe must fail, never turn into a skip.
            if not shutil.which("perf") or not shutil.which("taskset"):
                self.skipTest("perf/taskset unavailable")
            if not hasattr(os, "sched_getaffinity") or not {112, 120} <= os.sched_getaffinity(0):
                self.skipTest("perf self-test requires allowed CPUs 112 and 120")
            probe = subprocess.run(["taskset", "-c", "120", "perf", "stat", "-a", "-A", "-C", "112",
                                    "-x", ",", "--no-big-num", "--no-scale", "-e", "{cycles,instructions}",
                                    "--", "sleep", ".05"], capture_output=True, text=True, timeout=10,
                                   env={**os.environ, "LC_ALL": "C"})
            if probe.returncode or "<not supported>" in probe.stderr:
                self.skipTest("perf grouped PMU unavailable: " + (probe.stderr + probe.stdout)[-1000:])

            directory = tempfile.TemporaryDirectory(dir=ROOT / "build", prefix="exbatch-perf-selftest-")
            self.addCleanup(directory.cleanup)
            folder = Path(directory.name)
            children = Children()
            self.addCleanup(children.close)
            ready = folder / "busy.ready"
            busy = children.start(["taskset", "-c", "112", sys.executable, "-c",
                                   "import pathlib, sys\npathlib.Path(sys.argv[1]).touch()\nwhile True: pass\n",
                                   str(ready)], folder / "busy.log", folder)
            wait_for(ready, busy, seconds=5)

            def busy_ticks():
                self.assertIsNone(busy.poll(), "known busy loop exited")
                fields = Path(f"/proc/{busy.pid}/stat").read_text().rsplit(")", 1)[1].split()
                return int(fields[11]) + int(fields[12])  # utime + stime

            production_argv = perf_argv

            def interval_argv(path, cores=DEFAULT_CORES):
                argv = production_argv(path, cores)
                argv[2], argv[argv.index("-C") + 1] = "120", "112"
                # perf disallows --timeout with -I. Owned-child cleanup bounds
                # this serverless test; the production argv remains unchanged.
                at = argv.index("--timeout")
                argv[at:at + 2] = ["-I", "100"]
                return argv

            launched = time.monotonic()
            with mock.patch.dict(globals(), perf_argv=interval_argv):
                window = PerfWindow(folder, children)
            self.addCleanup(window.close)
            listening = time.monotonic()
            ticks = [busy_ticks()]
            time.sleep(.55)
            ticks.append(busy_ticks())
            enabled = window.command("enable")
            time.sleep(.55)
            ticks.append(busy_ticks())
            disabled = window.command("disable")
            time.sleep(.55)
            ticks.append(busy_ticks())
            children.stop(window.process, signal.SIGINT)
            self.assertTrue(all(b > a for a, b in zip(ticks, ticks[1:])),
                            f"busy loop did not run in every phase: {ticks}")

            intervals = {}
            for line in (folder / "perf.csv").read_text().splitlines():
                if not line.strip() or line.startswith("#"):
                    continue
                fields = [s.strip() for s in line.split(",")]
                self.assertGreaterEqual(len(fields), 7)
                stamp, cpu, count, _, event, runtime, percent = fields[:7]
                self.assertEqual(cpu, "CPU112")
                event = event.split(":")[0]
                self.assertIn(event, ("cycles", "instructions"))
                runtime, percent = float(runtime), float(percent.rstrip("%"))
                if count == "<not counted>":
                    self.assertEqual(runtime, 0)
                    count = 0
                else:
                    count = float(count)
                    self.assertTrue(math.isfinite(count) and count >= 0)
                self.assertEqual(percent, 100, "multiplexed self-test PMU")
                row = intervals.setdefault(float(stamp), {})
                self.assertNotIn(event, row)
                row[event] = count
                row[event + "_runtime_ns"] = runtime

            phases = {name: dict(intervals=0, cycles=0, instructions=0)
                      for name in ("before", "enabled", "after")}
            previous = 0.
            for stamp, row in sorted(intervals.items()):
                self.assertEqual(set(row), {"cycles", "instructions", "cycles_runtime_ns", "instructions_runtime_ns"})
                self.assertEqual(row["cycles_runtime_ns"], row["instructions_runtime_ns"])
                # perf's epoch lies between launch and the constructor ACK.
                # Classify only intervals wholly inside a phase for EVERY epoch
                # in that bound; boundary-straddling intervals cannot prove it.
                phase = None
                if listening + stamp <= enabled["before"]:
                    phase = "before"
                elif launched + previous >= enabled["after"] and listening + stamp <= disabled["before"]:
                    phase = "enabled"
                elif launched + previous >= disabled["after"]:
                    phase = "after"
                if phase:
                    phases[phase]["intervals"] += 1
                    for event in ("cycles", "instructions"):
                        phases[phase][event] += row[event]
                        if phase == "enabled":
                            self.assertGreater(row[event], 0, "no counts inside enabled window")
                        else:
                            self.assertEqual(row[event], 0, f"counts outside enabled window: {phase}")
                previous = stamp
            for name, row in phases.items():
                self.assertGreaterEqual(row["intervals"], 2, f"missing complete {name} intervals: {phases}")
            ipc = phases["enabled"]["instructions"] / phases["enabled"]["cycles"]
            self.assertTrue(.1 < ipc < 6, f"implausible busy-loop IPC: {ipc}")
            log = (folder / "perf.log").read_text()
            self.assertEqual(log, "Events disabled\nEvents disabled\nEvents enabled\nEvents disabled\n")
            print("REAL-PERF SELF-TEST " + json.dumps(dict(phases=phases, ipc=ipc, busy_ticks=ticks,
                  enabled=enabled, disabled=disabled, perf=window.identity, log=log), sort_keys=True), flush=True)

    with mock.patch("subprocess.Popen", side_effect=AssertionError("self-test launched a process")), \
         mock.patch("subprocess.run", side_effect=AssertionError("self-test launched a process")), \
         mock.patch("socket.create_connection", side_effect=AssertionError("self-test opened a socket")):
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Controls)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    with mock.patch("socket.create_connection", side_effect=AssertionError("self-test opened a socket")):
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls)
                                   for cls in (NativeGuardControl, RealPerfControl))
        live = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() and live.wasSuccessful() else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--worker", choices=("warm", "verify", "poll"), help=argparse.SUPPRESS)
    parser.add_argument("--regime", choices=REGIMES, action="append", help="repeatable; default all three")
    parser.add_argument("--cell", action="append", help="base ID or full cell ID; default all directed cells")
    parser.add_argument("--blocks", type=int, default=1, help="ABBA blocks per comparison/pass (default 1), including same-binary null")
    parser.add_argument("--score", choices=("plateau-then-matched", "matched-only"), default="plateau-then-matched",
                        help="default plateau then matched; matched-only skips plateau and checks PRE matched cyc/op")
    parser.add_argument("--matched-load", type=int,
                        help="required for matched-only: aggregate offered frames/s; rounded down to 512 * integer per-connection q")
    parser.add_argument("--cores", type=parse_cores, default=DEFAULT_CORES, metavar="SERVER_RANGE,LOAD_RANGE",
                        help="8 server CPUs and >=8 disjoint load CPUs (default 0-7,8-111)")
    parser.add_argument("--output", type=Path, help="fresh run directory; contains results.json, endgame.txt and raw samples")
    parser.add_argument("--arms", type=Path, help="replace frozen arms with PRE/POST path+sha256 JSON; optional PAD-A/EX*-OLD")
    parser.add_argument("--instance", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    require(args.output is not None, "--output is required")
    require(args.blocks > 0, "--blocks must be positive")
    validate_score(args.score, args.matched_load)
    cells = inventory()
    configure_cores(cells, args.cores)
    output = args.output.resolve()
    require(output.is_relative_to(ROOT), "output must stay inside this worktree")
    if args.worker:
        require(args.cell and len(args.cell) == 1 and args.cell[0] in cells, "worker requires one full cell ID")
        cell = cells[args.cell[0]]
        if args.worker == "poll":
            poll_worker(output, cpu_ids(args.cores[1])[-1])
        else:
            require(args.instance is not None and 0 <= args.instance < 8, "worker instance missing")
            warm_worker(cell, args.instance, output, verify_only=args.worker == "verify")
        return 0
    if args.cell:
        require(set(args.cell) <= set(cells) | set(BASES), "unknown --cell")
    selected = [cell for cell in cells.values() if
                (not args.regime or cell["id"].rsplit("_", 1)[1] in args.regime) and
                (not args.cell or cell["id"] in args.cell or cell["id"].rsplit("_", 1)[0] in args.cell)]
    require(selected, "no directed cells selected")
    table, receipt = bind_arms(args.arms)
    verify_receipt(receipt)
    if not args.dry_run:
        quiet_file_guard()
    identities = prepare_arms(dry=args.dry_run, table=table, cores=args.cores)
    verify_receipt(receipt)
    framing = measurement_framing(identities, receipt)
    memtier = memtier_identity()
    if args.dry_run:
        dry_run(selected, identities, output, args.blocks, receipt, framing, args.score, args.matched_load)
    else:
        run(selected, identities, output, args.blocks, memtier, receipt, framing, args.score, args.matched_load)
    return 0


if __name__ == "__main__":
    try:
        def interrupted(signum, frame):
            raise InterruptedError(f"received signal {signum}; reaping owned children")
        signal.signal(signal.SIGTERM, interrupted)
        sys.exit(main())
    except (RuntimeError, KeyError, ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"EXBATCH-DIRECTED FAILED: {error}", file=sys.stderr)
        sys.exit(1)
