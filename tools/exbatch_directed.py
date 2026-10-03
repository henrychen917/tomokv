#!/usr/bin/env python3
"""Mainline-only EX1/EX3/EX6 directed measurements (never part of the gate).

The inventory is executable input, not a second transcription of the recipes.
--self-test opens no sockets and launches no programs. --dry-run only executes
memtier --help, as a required grammar check; all workload commands are printed.
Normal invocation owns/reaps its children, boots fresh state for EVERY sample,
and retains failed samples. See MEASURE-REQUEST-exbatch-bench.md for scopes.
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
MEMTIER = "/usr/bin/memtier_benchmark"
ARMS = ("PRE", "PAD-A", "POST", "EX1-OLD", "EX3-OLD", "EX6-OLD")
BASES = ("exbatch_watch_w32", "exbatch_hz32", "exbatch_object32",
         "exbatch_xgroup32", "exbatch_publish_poll32")
REGIMES = ("f0", "f1", "s0")
PARTIAL = dict(zip(BASES, ("EX3-OLD", "EX3-OLD", "EX6-OLD", "EX6-OLD", "EX1-OLD")))
WINDOW, WARMUP, TAIL = 20, 3, 5
CONNECTIONS, PIPELINE = 512, 32
BOUND = CONNECTIONS * PIPELINE
REQUIRED_OPTIONS = ("command", "command-ratio", "command-key-pattern", "transaction",
                    "rate-limiting", "json-out-file", "distinct-client-seed",
                    "pipeline", "test-time", "key-minimum", "key-maximum")

# Stock memtier counts arbitrary replies but does not export integer VALUES.
# Interpose only the XGROUP generators' receive calls, on their existing CPUs.
# Connections still go directly to the exact server/port; no proxy, extra client,
# MONITOR in the timed run, or changed command grammar. A missing hook fails the
# exact guard/HDR count reconciliation. Per-FD state avoids a shared hot counter.
# This is compiled by MAINLINE before measurement, never by --self-test/dry-run.
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
static int receipt = -1;
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
    const char *path = getenv("EXBATCH_ZERO_RECEIPT");
    if (!path) die("missing receipt path");
    receipt = open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (receipt < 0) die("cannot create receipt");
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
    char text[256];
    int n = snprintf(text, sizeof(text), "{\"connections\":%llu,\"bytes\":%llu,\"zero_replies\":%llu}\n",
                     clients, bytes, bytes / 4);
    if (write(receipt, text, (size_t)n) != n) die("receipt write failed");
    next_close(receipt);
}
'''


def guard_build_argv(folder):
    return ["taskset", "-c", "8-23", "cc", "-std=c11", "-O2", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
            "-o", str(folder / "zero-reply.so"), str(folder / "zero-reply.c"), "-ldl"]


def prepare_guard(folder):
    folder.mkdir()
    (folder / "zero-reply.c").write_text(ZERO_REPLY_GUARD)
    with (folder / "build.log").open("wb") as log:
        subprocess.run(guard_build_argv(folder), check=True, stdout=log, stderr=subprocess.STDOUT)
    return dict(path=str(folder / "zero-reply.so"), sha256=digest(folder / "zero-reply.so"),
                source_sha256=digest(folder / "zero-reply.c"), build_argv=guard_build_argv(folder))


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
                    "--atomic": "1", "--overlap": "1", "--reorder": "0", "--key-lb": "1",
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
    cpu = "111" if kind == "poll" else (cell["memtier_instances"][index]["argv"][2] if index is not None else "8")
    result = ["taskset", "-c", cpu, sys.executable, str(Path(__file__).resolve()),
              "--worker", kind, "--cell", cell["id"], "--output", str(folder)]
    return result + (["--instance", str(index)] if index is not None else [])


def perf_argv(folder):
    # IPC is instructions / cycles from this group, never a separately sampled metric.
    return ["taskset", "-c", "8", "perf", "stat", "-a", "-A", "-C", "0-7", "-x", ",",
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
        hits = stats["Per-Key Misses"]["GET"]
        require(hits["Total Misses"] == 0 and hits["Total Hits"] == completed["GET"], "GET missed warm keys")
    return result


def parse_perf(text):
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
    require(set(cpus) == set(range(8)), "perf lacks one or more server CPUs")
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


def prepare_arms(dry=False):
    manifest = json.loads(RECEIPTS.read_text())
    paths = arm_paths()
    expected = {r["arm"]: r["sha256"] for r in manifest["artifacts"]}
    identities = {}
    for arm in ("PRE", "POST", "PAD-A", "EX1-OLD", "EX3-OLD", "EX6-OLD"):
        path = paths[arm]
        if not path.is_file():
            if dry:
                if arm == "PRE":
                    print(f"# git archive {manifest['pre_commit']} | tar -x -C {path.parent.parent}")
                    print(shlex.join(["taskset", "-c", "0-15", "make", "-C", str(path.parent.parent), "-j16"]))
                elif arm == "POST":
                    print(shlex.join(["taskset", "-c", "0-15", "make", "-C", str(ROOT), "-j16"]))
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
                subprocess.run(["taskset", "-c", "0-15", "make", "-C", str(source), "-j16"], check=True)
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
        identities[arm] = dict(path=str(path), sha256=actual, expected_sha256=expected[arm],
                               kind="A: PRE behaviour at POST layout" if arm == "PAD-A" else
                                    "A: selected old item at POST layout" if arm.endswith("OLD") else "source build")
    return identities


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
    with contextlib.closing(Conn("127.0.0.1", 18179, timeout=60)) as conn:
        for low in range(item["key_min"], item["key_max"] + 1, 128):
            batch = []
            for n in range(low, min(low + 128, item["key_max"] + 1)):
                if not verify_only:
                    for template in templates:
                        argv = [s.replace("{n}", str(n)) for s in template]
                        expected = b"OK" if argv[0] == "SET" or argv[:2] == ["XGROUP", "CREATE"] else b"1-0" if argv[0] == "XADD" else 1
                        batch.append((argv, expected))
                        warmed += 1
                verify = verification_commands(base, n)
                batch += verify
                checked += len(verify)
            conn.raw(b"".join(encode(*argv) for argv, _ in batch))
            for argv, expected in batch:
                check_reply(conn.read(), expected, argv)
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


def poll_worker(folder):
    rows, missed = [], 0
    with contextlib.closing(Conn("127.0.0.1", 18179)) as conn:
        save(folder / "poll-ready.json", dict(pid=os.getpid(), cpu=111))
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
    def __init__(self, folder, children):
        self.folder, self.children = folder, children
        for name in ("perf.ctl", "perf.ack"):
            os.mkfifo(folder / name)
        self.ctl = os.open(folder / "perf.ctl", os.O_RDWR | os.O_NONBLOCK)
        self.ack = os.open(folder / "perf.ack", os.O_RDWR | os.O_NONBLOCK)
        self.process = children.start(perf_argv(folder), folder / "perf.log", folder)
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
        require(select.select([self.ack], [], [], 5)[0], "perf control ACK timeout")
        reply = os.read(self.ack, 1024)
        require(reply.strip() == b"ack" and self.process.poll() is None, "invalid perf control ACK")
        return dict(before=before, after=time.monotonic())

    def finish(self):
        self.children.stop(self.process, signal.SIGINT)
        return parse_perf((self.folder / "perf.csv").read_text())

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
    deadline = time.monotonic() + seconds
    while not path.exists():
        require(process.poll() is None, f"worker exited before {path}")
        require(time.monotonic() < deadline, f"timeout waiting for {path}")
        time.sleep(.01)


def command_counts(cell, before, after):
    names = {s.split()[0] for s in cell["workload"]["commands"]}
    result = {n: command_stat(after, n)[0] - command_stat(before, n)[0] for n in names}
    require(all(c > 0 for c in result.values()), "no progress on a workload command")
    return result


def role_cpus(snapshot, regime, boot):
    placement = {int(t): int(cpu) for t, cpu in (part.split(":") for part in boot["thread_cpus"].split(","))}
    require(set(placement) == set(snapshot.threads), "INFO/LBSIGNALS thread inventory differs")
    roles = {}
    for tid, row in snapshot.threads.items():
        # LBSIGNALS 'cpu' is CPU TIME, not a placement ID. Use INFO's map.
        roles.setdefault(row["role"], []).append(placement[tid])
    require(sorted(c for cpus in roles.values() for c in cpus) == list(range(8)), "server CPU geometry changed")
    expected = {"io": 6, "ex": 2} if regime == "s0" else {"fused": 8}
    require({r: len(v) for r, v in roles.items()} == expected, "server roles changed")
    return roles


def wire_probe(cell, folder, children, guard=None):
    with contextlib.closing(Conn("127.0.0.1", 18179, timeout=10)) as monitor:
        check_reply(monitor.must("MONITOR"), b"OK", "MONITOR")
        guarded = cell["id"].startswith(BASES[3])
        env = guard_environment(guard, folder, "wire-probe") if guarded else None
        proc = children.start(probe_argv(cell, folder), folder / "wire-probe.log", folder, env)
        frames = []
        for _ in range(2 * cell["workload"]["cycle_frames"]):
            raw = monitor.read()
            require(isinstance(raw, bytes), "missing MONITOR wire witness")
            # All recipe tokens are printable ASCII. Refuse unknown escaping.
            tokens = re.findall(r'"(?:[^"\\]|\\.)*"', raw.decode("ascii"))
            frames.append([json.loads(s) for s in tokens])
        require(proc.wait(timeout=10) == 0, "memtier wire probe failed")
    record = validate_wire(cell, frames)
    parsed = parse_memtier(folder / "wire-probe.json", cell, folder / "wire-probe.log")
    record["completed"] = parsed["completed"]
    if guarded:
        record["zero_reply_guard"] = check_zero_receipt(folder / "wire-probe-zero.json", parsed["completed"]["XGROUP"], 1)
    save(folder / "wire-witness.json", record)
    return record


def check_mix(cell, counts, bound):
    rotation = Counter(s.split()[0] for s in cell["workload"]["commands"])
    rounds = [counts[n] / number for n, number in rotation.items()]
    require(max(rounds) - min(rounds) <= bound, "command mix differs beyond finite pipeline boundary")
    return dict(rotation=dict(rotation), counts=counts, boundary_frames=bound)


def run_sample(cell, arm, identities, folder, q, guard=None):
    folder.mkdir(parents=True, exist_ok=False)
    record = dict(cell=cell["id"], arm=arm, arm_identity=identities[arm], complete=False,
                  matched=q if q is not None else "plateau", argv={}, artifacts=str(folder),
                  numerator_scope="perf stat system-wide on CPUs 0-7, grouped cycles+instructions; includes observer server work",
                  denominator_scope="central top-level workload frames; excludes MEMORY/INFO/DEBUG and counts queued SET once",
                  latency_scope="pooled completed-response HDR across all eight full 28-second runs, including warmup/tail",
                  startup_allowance_seconds=0, server_boot_timeout_seconds=30)
    children, monitor, conn, perf = Children(), None, None, None
    started = time.monotonic()
    try:
        quiet_file_guard()
        monitor = QuietMonitor(range(8), range(8, 112), ports=[18179],
                               sample_artifact=folder / "quiet-samples.jsonl").start()
        record["quiet"] = monitor.evidence()
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
                            "key_lb": "1", "client_lb": "1", "flip_auto": "0"}.items():
            require(boot[name] == value, f"effective boot {name} differs from recipe")
        require(conn.must("DBSIZE") == 0, "server did not boot with fresh empty state")
        if base == BASES[0]:
            watch_proof(folder)
        warmers = []
        for i in range(8):
            argv = worker_argv("warm", cell, folder, i)
            record["argv"].setdefault("warm", []).append(argv)
            warmers.append(children.start(argv, folder / f"warm-{i}.log", folder))
        for i, worker in enumerate(warmers):
            require(worker.wait(timeout=600) == 0, f"typed warm/verification failed for instance {i}")
        require(conn.must("DBSIZE") == cell["workload"]["physical_keys"], "warm physical key count differs")
        record["warm"] = [json.loads((folder / f"warm-{i}.json").read_text()) for i in range(8)]
        record["argv"]["wire_probe"] = probe_argv(cell, folder)
        if base == BASES[3]:
            require(guard is not None and digest(guard["path"]) == guard["sha256"], "XGROUP native guard changed")
            record["zero_reply_guard"] = guard
        record["wire_witness"] = wire_probe(cell, folder, children, guard)
        deadline = time.monotonic() + 10
        while int(info(conn, "clients")["connected_clients"]) != 1:
            require(time.monotonic() < deadline, "wire probe/monitor connections did not drain")
            time.sleep(.02)
        before_full = info(conn, "commandstats")
        record["whole_commandstats_before"] = before_full
        perf = PerfWindow(folder, children)
        record["argv"]["perf"] = perf_argv(folder)
        poller = None
        if base == BASES[-1]:
            argv = worker_argv("poll", cell, folder)
            record["argv"]["observer"] = argv
            poller = children.start(argv, folder / "poll.log", folder)
            wait_for(folder / "poll-ready.json", poller)
            save(folder / "poll-start.json", dict(start=time.monotonic() + .05))
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
        roles = role_cpus(lb0, regime, boot)
        enable = perf.command("enable")
        before_at = time.monotonic()
        before = info(conn, "commandstats")
        t0 = time.monotonic()
        # Normal gate uses no diagnostic +5s allowance: preserve --test-time=28.
        # The five-second tail absorbs sequential launch and counter endpoint work.
        require(t0 - launch < WARMUP + 1, "load startup/counter setup consumed >1s of the reserved tail")
        while time.monotonic() < t0 + WINDOW:
            time.sleep(min(1, max(0, t0 + WINDOW - time.monotonic())))
            quiet_file_guard()
            monitor.check()
            require(server.poll() is None and all(p.poll() is None for p in loads), "child exited inside central window")
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
        pmu = perf.finish()
        pmu["executable"] = perf.identity
        lb1raw = conn.must("DEBUG", "LBSIGNALS")
        (folder / "lb-after.txt").write_bytes(lb1raw)
        lb1 = parse_snapshot(lb1raw)
        require(role_cpus(lb1, regime, info(conn, "server")) == roles, "thread roles/CPU placement changed during sample")
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
            require(load.wait(timeout=30) == 0, f"memtier {i} failed")
        if poller:
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
                                       scope="one persistent connection, CPU111, 100Hz; workload denominator excludes MEMORY")
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
            verifiers = [children.start(worker_argv("verify", cell, folder, i), folder / f"verify-{i}.log", folder)
                         for i in range(8)]
            record["argv"]["verify"] = [worker_argv("verify", cell, folder, i) for i in range(8)]
            for process in verifiers:
                require(process.wait(timeout=180) == 0, "XGROUP existing-consumer/cardinality check failed")
            record["xgroup"] = dict(all_keys_verified_before_and_after=True, existing_consumer_reply=0,
                                     streams=65536, groups_per_stream=1, consumers_per_group=1,
                                     scored_zero_replies=completed["XGROUP"],
                                     observation="every scored wire reply checked as :0 CR LF by SHA-bound native receive guard; exact guard/HDR reconciliation")
        quiet_file_guard()
        monitor.check()
        require(digest(binary) == identities[arm]["sha256"], "arm changed during sample")
        record["complete"] = True
        return record
    except BaseException as error:
        record["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if perf:
            perf.close()
        if conn:
            conn.close()
        children.close()
        if monitor:
            record["quiet"] = monitor.close()
        record["elapsed_seconds"] = time.monotonic() - started
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


def endgame(cell, a, b, left, right, q):
    base, regime = cell["id"].rsplit("_", 1)
    delta = lambda key: 100 * (right[key] / left[key] - 1)
    return (f"EXBATCH-DIRECTED {base} {regime} {a}->{b} "
            f"rate={left['rate']:.2f}/{right['rate']:.2f} ({delta('rate'):+.2f}%) "
            f"p50={left['p50']:.3f}/{right['p50']:.3f} p99={left['p99']:.3f}/{right['p99']:.3f} "
            f"cyc/op={left['cycles_per_op']:.3f}/{right['cycles_per_op']:.3f} ({delta('cycles_per_op'):+.2f}%) "
            f"instr/op={left['instr_per_op']:.3f}/{right['instr_per_op']:.3f} "
            f"ipc={left['ipc']:.4f}/{right['ipc']:.4f} matched={q if q is not None else 'plateau'}")


def block_checks(samples, q):
    require(len(samples) == 4, "ABBA block incomplete")
    sides = ([samples[0], samples[3]], [samples[1], samples[2]])
    if q is not None:
        rate_check([s["rate"] for s in samples], q)
        receipt = rate_check([statistics.mean(s["rate"] for s in side) for side in sides], q)
        require(receipt["inter_arm_spread_pct"] <= .5, "matched arm means differ >0.5%; recollect common target")
    else:
        for side in sides:
            require(statistics.mean(s["saturation"]["score_pct"] for s in side) >= SATURATION_FLOOR and
                    min(s["saturation"]["score_pct"] for s in side) >= SATURATION_FLOOR - 5,
                    "unlimited-rate block lacks gate productive-role occupancy; not a sustainable plateau")
            require(max(s["rate"] for s in side) / min(s["rate"] for s in side) <= 1.02,
                    "same-arm plateau repeats differ >2%; recollect quiet block")
    if "observer" in samples[0]:
        require(max(s["observer"]["central_successful"] for s in samples) -
                min(s["observer"]["central_successful"] for s in samples) <= 2, "poll cadence differs across arms")


def dry_run(cells, identities, output, blocks):
    print("# DRY RUN: only memtier --help was executed. No server, load, perf, socket, build or output directory is created.")
    print("# arm SHA256 identities " + json.dumps(identities, sort_keys=True))
    print(shlex.join([MEMTIER, "--help"]) + " # already checked; SHA-bound grammar receipt")
    print("git rev-parse HEAD")
    guard = dict(path=str(output / "guard/zero-reply.so"))
    if any(c["id"].startswith(BASES[3]) for c in cells):
        print("# write embedded zero-reply C source; compile and SHA-bind before quiet preflight")
        print(shlex.join(guard_build_argv(output / "guard")))
    for arm, identity in identities.items():
        source = identity["path"]
        identity["path"] = str(output / "arms" / arm / "tomokv")
        print(f"# freeze copy {shlex.quote(source)} -> {shlex.quote(identity['path'])}; chmod 0555; verify SHA256")
    for cell in cells:
        base, _ = cell["id"].rsplit("_", 1)
        for phase, q in (("plateau", None), ("matched", "Q_" + cell["id"])):
            if q:
                print(f"# {q}=floor(0.8*min(mean PRE/PAD-A/POST primary plateau frames/s)/512)")
            pairs = [("PRE", "PRE")] + comparisons(cell)
            for pair_index, (a, b) in enumerate(pairs):
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
                        print(shlex.join(perf_argv(folder)))
                        if base == BASES[-1]:
                            print(shlex.join(worker_argv("poll", cell, folder)))
                        for i in range(8):
                            display_load(load_argv(cell, i, folder, q), f"load-{i}")
                        print("# warmup 3s; perf FIFO enable/ACK; INFO commandstats; central 20s; INFO commandstats; perf disable/ACK; drain 28s workload; reap owned perf")
                        if base == BASES[3]:
                            for i in range(8):
                                print(shlex.join(worker_argv("verify", cell, folder, i)))
                        print("# verify exact whole-run server/HDR counts, replies/mix/state, rate target, PMU coverage; terminate/reap owned server")


def run(cells, identities, output, blocks, memtier):
    require(not output.exists(), "output already exists; never overwrite/reuse prior samples")
    require(set(range(112)) <= os.sched_getaffinity(0), "mainline launch must permit CPUs 0-111")
    os.sched_setaffinity(0, {8})
    output.mkdir(parents=True)
    instrument_files = [Path(__file__).resolve(), INVENTORY, RECEIPTS,
                        *[ROOT / "tests" / n for n in ("_lib.py", "abba_workloads.py", "abba_saturation.py", "gate_quiet.py", "gateplan.py")]]
    report = dict(schema=1, complete=False, arms=identities, memtier=memtier,
                  instrument={str(p.relative_to(ROOT)): digest(p) for p in instrument_files},
                  git_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  regimes=sorted({c["id"].rsplit("_", 1)[1] for c in cells}), cells={}, rows=[],
                  bands="Same-binary nulls collected before each pass; no regression band inferred/widened by this tool. Mainline freezes bands and judges.",
                  capacity="Fixed requested 8-instance geometry. Productive occupancy and repeatability checked; higher-generator-capacity plateau proof remains mainline's calibration.")
    started = time.monotonic()
    try:
        guard = prepare_guard(output / "guard") if any(c["id"].startswith(BASES[3]) for c in cells) else None
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
            q = None
            for phase in ("plateau", "matched"):
                pass_entry = entry["passes"][phase] = dict(q=q, null=[], comparisons=[], blocks=[])
                for pair_index, (a, b) in enumerate([("PRE", "PRE")] + comparisons(cell)):
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
                        block_checks(samples, q)
                        block_record["accepted"] = True
                    left, right = map(aggregate, groups)
                    comparison = dict(A=a, B=b, left=left, right=right,
                                      samples=[[s["artifacts"] for s in g] for g in groups])
                    if pair_index == 0:
                        pass_entry["null"] = comparison
                        # Persist null evidence before any candidate in this pass.
                        save(output / "results.json", report)
                    else:
                        pass_entry["comparisons"].append(comparison)
                        row = endgame(cell, a, b, left, right, q)
                        report["rows"].append(row)
                        print(row, flush=True)
                    save(output / "results.json", report)
                if phase == "plateau":
                    rates = {a: [] for a in ("PRE", "PAD-A", "POST")}
                    for comp in pass_entry["comparisons"][:3]:
                        rates[comp["A"]].append(comp["left"]["rate"])
                        rates[comp["B"]].append(comp["right"]["rate"])
                    plateaus = {a: statistics.mean(v) for a, v in rates.items()}
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

    def synthetic(cell):
        counts = Counter(c.split()[0] for c in cell["workload"]["commands"])
        stats = {"Runtime": {"Interrupted": "false", "Time unit": "MILLISECONDS", "Total duration": 28000},
                 "Per-Key Misses": {}}
        for name, weight in counts.items():
            count = 10000 * weight
            stats[name.capitalize() + "s"] = dict(Count=count, **{
                "Time-Serie": {"0": {"Count": count, "Bytes RX": count * (9 if name == "EXEC" else 4)}},
                "Aborts/sec": 0,
                "Percentile Latencies": {"Histogram log format": {"Compressed Histogram": histogram(count)}}})
            if name in ("EXEC", "GET"):
                stats["Per-Key Misses"][name] = {"Total Hits": count, "Total Misses": 0}
        stats["Totals"] = {"Count": sum(counts.values()) * 10000, "Connection Errors": 0,
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
                            key_lb="1", client_lb="1", flip_auto="0", thread_cpus=",".join(f"{i}:{i}" for i in range(8)))

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

        def test_aggregate_pools_histograms_and_pmu_numerators(self):
            sample = dict(complete=True, frames=100, cycles=1000, instructions=1500, rate=5,
                          histogram={1000: 90, 9000: 10})
            result = aggregate([sample, sample])
            self.assertEqual((result["p50"], result["p99"], result["cycles_per_op"], result["ipc"]), (1., 9., 10., 1.5))
            row = endgame(self.cells[BASES[0] + "_f0"], "PRE", "POST", result, result, 17)
            self.assertTrue(row.startswith("EXBATCH-DIRECTED exbatch_watch_w32 f0 PRE->POST rate="))
            self.assertTrue(row.endswith("matched=17"))

    with mock.patch("subprocess.Popen", side_effect=AssertionError("self-test launched a process")), \
         mock.patch("subprocess.run", side_effect=AssertionError("self-test launched a process")), \
         mock.patch("socket.create_connection", side_effect=AssertionError("self-test opened a socket")):
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Controls)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--worker", choices=("warm", "verify", "poll"), help=argparse.SUPPRESS)
    parser.add_argument("--regime", choices=REGIMES, action="append", help="repeatable; default all three")
    parser.add_argument("--cell", action="append", help="base ID or full cell ID; default all directed cells")
    parser.add_argument("--blocks", type=int, default=1, help="ABBA blocks per comparison/pass (default 1), including same-binary null")
    parser.add_argument("--output", type=Path, help="fresh run directory; contains results.json, endgame.txt and raw samples")
    parser.add_argument("--instance", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    require(args.output is not None, "--output is required")
    require(args.blocks > 0, "--blocks must be positive")
    cells = inventory()
    output = args.output.resolve()
    require(output.is_relative_to(ROOT), "output must stay inside this worktree")
    if args.worker:
        require(args.cell and len(args.cell) == 1 and args.cell[0] in cells, "worker requires one full cell ID")
        cell = cells[args.cell[0]]
        if args.worker == "poll":
            poll_worker(output)
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
    memtier = memtier_identity()
    if not args.dry_run:
        quiet_file_guard()
    identities = prepare_arms(dry=args.dry_run)
    if args.dry_run:
        dry_run(selected, identities, output, args.blocks)
    else:
        run(selected, identities, output, args.blocks, memtier)
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
