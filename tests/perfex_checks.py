#!/usr/bin/env python3
"""EX4.2/12/13 regressions, adapted from round4 T2/T13/T26/T28.

The binary rows never boot. The sampler row accepts a prebooted gate endpoint,
or --binary/--port/--cores for an isolated reproduction. No historical binary,
port, or CPU assignment is hidden in the driver.
"""
import argparse
from contextlib import closing, contextmanager
import json
import os
import mmap
import struct
from pathlib import Path
import re
import subprocess
import tempfile
import time

from _lib import Conn, encode, info, shards_of, topology, wait_ready


def require(ok, why):
    if not ok:
        raise AssertionError(why)


def symbols(binary, pattern):
    rows = []
    text = subprocess.check_output(["nm", "-S", "-C", "--defined-only", str(binary)], text=True)
    for line in text.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and re.fullmatch(pattern, parts[3]):
            rows.append((int(parts[0], 16), int(parts[1], 16), parts[3]))
    return rows


def instructions(binary, symbol):
    addr, size, _ = symbol
    text = subprocess.check_output([
        "objdump", "-dC", "--no-show-raw-insn", f"--start-address={addr}",
        f"--stop-address={addr + size}", str(binary)], text=True)
    return [(int(m[1], 16), m[2], m[3].strip()) for line in text.splitlines()
            if (m := re.match(r"\s*([0-9a-f]+):\s+(\S+)\s*(.*)", line))]


def batch_check(binary):
    rows = symbols(binary, r"unsigned int tomo(?:_db0)?::ExLoopT<(?:true|false)>::"
                   r"(?:drain_tasks<32u, false>\(bool\)|"
                   r"drain_tasks_read_local_interleaved<false>\(bool, bool&\))")
    require(len(rows) == 6, f"expected all six ordinary drain bodies, found {len(rows)}")
    failed = []
    for row in rows:
        code = instructions(binary, row)
        calls = [f"{addr:x}: {op} {args}" for addr, op, args in code
                 if (op.startswith("call") and "memset" in args)
                 or (op == "rep" and "stos" in args)]
        print(json.dumps(dict(body=row[2], zero_fill=calls)), flush=True)
        if calls:
            failed.append(row[2])
    require(not failed, f"EX4.13: {len(failed)} drain bodies zero their batch before receiving a Task")


def clock_check(binary):
    """Follow the sample_depth(false) edge until the next signal beat.

    A CLOCK_THREAD_CPUTIME_ID call must be reachable from the true edge and
    unreachable from the false edge. Unknown control flow fails closed. This
    checks linked code in both namespaces and both executor capabilities.
    """
    rows = symbols(binary, r"tomo(?:_db0)?::ExLoopT<(?:true|false)>::run\(\)")
    require(len(rows) == 4, f"expected four executor run bodies, found {len(rows)}")
    failed = []
    for row in rows:
        code = instructions(binary, row)
        index = {line[0]: i for i, line in enumerate(code)}
        beats = [i for i, (_, op, args) in enumerate(code)
                 if op.startswith("call") and "::ThreadCtx::sample_depth(" in args]
        require(len(beats) == 1, f"{row[2]}: signal beat missing/ambiguous")
        clocks = set()
        for i, (_, op, args) in enumerate(code):
            if not op.startswith("call") or "clock_gettime" not in args:
                continue
            for _, prev_op, prev_args in reversed(code[max(0, i - 16):i]):
                if prev_op.startswith("call"):
                    raise AssertionError(f"{row[2]}: clock ID not visible before call")
                if prev_args.endswith(",%edi"):
                    if prev_op == "mov" and prev_args == "$0x3,%edi":
                        clocks.add(i)
                    break
            else:
                raise AssertionError(f"{row[2]}: unknown clock ID")
        require(clocks, f"{row[2]}: CPU-time diagnostic was removed")
        beat = beats[0]
        require(code[beat + 1][1:] == ("test", "%al,%al"), "unknown signal-beat result test")
        branch = beat + 2
        require(code[branch][1] in ("je", "jne"), "unknown signal-beat branch")

        def target(i):
            arg = code[i][2].split()[0]
            require(re.fullmatch(r"[0-9a-f]+", arg), f"indirect control flow at {code[i]}")
            return index.get(int(arg, 16))

        def reachable(start):
            pending, seen = [start], set()
            while pending:
                i = pending.pop()
                if i is None or i in seen or i == beat or i >= len(code):
                    continue
                seen.add(i)
                _, op, args = code[i]
                if op in ("ret", "retq", "ud2"):
                    continue
                if op.startswith("j"):
                    pending.append(target(i))
                    if op == "jmp":
                        continue
                pending.append(i + 1)
            return seen

        fall, taken = branch + 1, target(branch)
        false, true = (taken, fall) if code[branch][1] == "je" else (fall, taken)
        false_clocks = reachable(false) & clocks
        require(reachable(true) & clocks, f"{row[2]}: beat does not sample CPU time")
        print(json.dumps(dict(body=row[2], cpu_clock_sites=len(clocks),
                              clocks_reachable_without_beat=len(false_clocks))), flush=True)
        if false_clocks:
            failed.append(row[2])
    require(not failed, f"EX4.12: CPU clock reachable without signal beat in {len(failed)} bodies")


def keyspace(c):
    row = info(c, "keyspace").get("db0")
    require(row is not None, "INFO keyspace db0 missing")
    return {k: int(v) for k, v in (field.split("=") for field in row.split(","))}


def pipeline(c, commands, expected):
    c.raw(b"".join(encode(*cmd) for cmd in commands))
    for _ in commands:
        require(c.read() == expected, "pipeline reply differs")


# Only these regression children load this shim. Production objects/binaries
# have no test hook, counter, shared atomic, clock branch or added configuration.
CLOCK_SOURCE = r"""
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>
static int64_t *frozen;
static int (*real_clock)(clockid_t, struct timespec *);
__attribute__((constructor)) static void init_clock(void) {
    real_clock = dlsym(RTLD_NEXT, "clock_gettime");
    const char *path = getenv("TOMO_PERFEX_CLOCK");
    if (!path) _exit(91);
    int fd = open(path, O_RDONLY);
    if (fd < 0) _exit(92);
    void *p = mmap(0, 8, PROT_READ, MAP_SHARED, fd, 0);
    close(fd);
    if (p == MAP_FAILED) _exit(93);
    frozen = p;
}
int clock_gettime(clockid_t id, struct timespec *ts) {
    int64_t ms = frozen ? __atomic_load_n(frozen, __ATOMIC_RELAXED) : 0;
    if (id == CLOCK_REALTIME && ms) {
        ts->tv_sec = ms / 1000;
        ts->tv_nsec = (ms % 1000) * 1000000;
        return 0;
    }
    return real_clock ? real_clock(id, ts) : syscall(SYS_clock_gettime, id, ts);
}
"""


def prepare_clock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(8))
    library = Path(str(path) + ".so")
    subprocess.run(["cc", "-x", "c", "-", "-O2", "-fPIC", "-shared", "-o", str(library), "-ldl"],
                   input=CLOCK_SOURCE, text=True, check=True)
    return library.resolve()


def sampler_check(host, port, clock_file):
    require(clock_file is not None, "sampler needs the isolated realtime clock fixture")
    with clock_file.open("r+b") as file, mmap.mmap(file.fileno(), 8) as clock, closing(Conn(host, port)) as c:
        origin = time.time_ns() // 1_000_000
        def freeze(ms):
            clock[:] = struct.pack("q", ms)
            # The PTTL boundary witness below detects a shim that never
            # freezes time. No window is silently skipped.
            time.sleep(.06)  # exceeds the existing 50 ms idle wait, not a precision window
        freeze(origin)
        topo = topology(c)
        require(len(topo.shard_owner) == 16, "sampler proof needs the gate's 16 shards")
        target = next(iter(topo.shard_owner))
        other = next(s for s, owner in topo.shard_owner.items()
                     if s != target and owner == topo.shard_owner[target])
        keys, plain = [], None
        for base in range(0, 32768, 512):
            candidates = [f"perfex:{i}" for i in range(base, base + 512)]
            for key, (sid, _) in zip(candidates, shards_of(c, candidates)):
                if sid == target and len(keys) < 512:
                    keys.append(key)
                if sid == other:
                    plain = key
            if len(keys) == 512 and plain:
                break
        require(len(keys) == 512 and plain, "could not arm unrelated-shard geometry")
        require(c.must("DEBUG", "SET-ACTIVE-EXPIRE", 0) == b"OK", "disable active expiry")
        try:
            require(c.must("FLUSHALL") == b"OK", "fresh sampler fixture")
            require(c.must("SET", plain, "plain") == b"OK", "plain fixture")
            deadlines = [origin + 1_000_000 + 997_000 * i for i in range(len(keys))]
            pipeline(c, [("SET", key, "v", "PXAT", at)
                         for key, at in zip(keys, deadlines)], b"OK")
            # Give every owner/shard an explicit beat; then hold time fixed.
            for tick in range(1, 10):
                freeze(origin + tick)
            now = origin + 9
            initial = keyspace(c)
            require(initial["keys"] == 513 and initial["expires"] == 512,
                    f"published counts differ: {initial}")
            require(initial["avg_ttl"] > 0, "no monitoring sample after explicit owner beats")
            # PTTL reads the cached owner clock. A missing/broken shim must fail
            # before the absence-of-change assertion, never produce a false PASS.
            pttl = c.must("PTTL", keys[0])
            require(pttl == deadlines[0] - now, f"frozen realtime window did not open: {pttl}")
            values = [keyspace(c)["avg_ttl"]]
            for _ in range(16):
                require(c.must("GET", plain) == b"plain", "unrelated GET result")
                values.append(keyspace(c)["avg_ttl"])
            changes = sum(a != b for a, b in zip(values, values[1:]))
            print(json.dumps(dict(frozen_time_ms=now, unrelated_batches=16,
                                  sample_changes=changes, averages=values)), flush=True)
            require(changes == 0, "EX4.2: unrelated batches drive the TTL sampler without a beat")
            estimates = []
            for tick in range(10, 138):
                freeze(origin + tick)
                estimates.append(keyspace(c)["avg_ttl"] + tick)
            exact = sum(deadlines) / len(deadlines) - origin
            estimated = sum(estimates) / len(estimates)
            error = abs(estimated - exact) / exact
            require(len(set(estimates)) >= 8, "cursor did not advance with active expiry disabled")
            print(json.dumps(dict(estimated_ttl_ms=estimated, exact_ttl_ms=exact,
                                  relative_error=error, tolerance=.10)), flush=True)
            require(error <= .10, "avg_ttl does not track the exact average within 10%")
            # Every volatile shard must receive a turn. Equal deadlines make
            # this check exact and reject a cursor stuck on one shard.
            require(c.must("FLUSHALL") == b"OK", "fairness fixture reset")
            uniform = origin + 1_000_000
            pipeline(c, [("SET", f"all:{i}", "v", "PXAT", uniform) for i in range(4096)], b"OK")
            for tick in range(138, 150):
                freeze(origin + tick)
            row = keyspace(c)
            require(row["keys"] == row["expires"] == 4096, "all-shard counts differ")
            require(row["avg_ttl"] == uniform - origin - 149,
                    f"rotating sampler did not refresh every volatile shard: {row}")
            require(c.must("DBSIZE") == 4096, "DBSIZE publication differs")
            pipeline(c, [("PERSIST", f"all:{i}") for i in range(4096)], 1)
            row = keyspace(c)
            require(row["keys"] == 4096 and row["expires"] == row["avg_ttl"] == 0,
                    "zero-expiry publication differs")
        finally:
            c.must("DEBUG", "SET-ACTIVE-EXPIRE", 1)
            clock[:] = bytes(8)
    print("PASS EX4.2: bounded beat sampling, avg_ttl, exact counts and DBSIZE", flush=True)


@contextmanager
def server(binary, port, cores, mode="2s", read_local=0, clock_file=None, balancing=False):
    """Only the explicit --binary live invocation starts this isolated child."""
    root = Path(__file__).resolve().parents[1] / "build/perfex/runs"
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as directory:
        log = Path(directory) / "server.log"
        argv = ["taskset", "-c", cores, str(Path(binary).resolve()), "--port", str(port),
                "--bind", "127.0.0.1", "--thread-mode", mode,
                "--shards", "16", "--read-local", str(read_local), "--databases", "1",
                "--key-lb", str(int(balancing)), "--client-lb", str(int(balancing)), "--flip-auto", "0",
                "--enable-debug-command", "yes", "--save", "", "--appendonly", "no"]
        if mode == "2s":
            argv += ["--ratio", "6:2"]
        with log.open("w") as stream:
            env = dict(os.environ)
            if clock_file:
                env.update(LD_PRELOAD=str(Path(str(clock_file) + ".so").resolve()),
                           TOMO_PERFEX_CLOCK=str(clock_file.resolve()))
            proc = subprocess.Popen(argv, cwd=directory, stdout=stream, stderr=subprocess.STDOUT, env=env)
            try:
                ready = wait_ready("127.0.0.1", port, process=proc, log_path=log, timeout=15)
                ready.close()
                yield proc
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                if proc.returncode not in (0, -15):
                    print(log.read_text(), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("check", choices=("batch", "clock", "sampler", "prepare"))
    p.add_argument("--binary", type=Path)
    p.add_argument("--clock-file", type=Path)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=25100)
    p.add_argument("--cores", default="112-119")
    p.add_argument("--mode", choices=("1s", "2s"), default="2s")
    p.add_argument("--read-local", type=int, choices=(0, 1), default=0)
    a = p.parse_args()
    if a.check == "prepare":
        require(a.clock_file is not None, "prepare needs --clock-file")
        prepare_clock(a.clock_file)
    elif a.check == "sampler":
        if a.binary:
            if a.clock_file is None:
                a.clock_file = Path("build/perfex/sampler-clock")
            prepare_clock(a.clock_file)
            with server(a.binary, a.port, a.cores, a.mode, a.read_local, a.clock_file):
                sampler_check(a.host, a.port, a.clock_file)
        else:
            sampler_check(a.host, a.port, a.clock_file)
    else:
        require(a.binary is not None, "binary row requires --binary")
        (batch_check if a.check == "batch" else clock_check)(a.binary)
        print(f"PASS EX4.{13 if a.check == 'batch' else 12}")


if __name__ == "__main__":
    main()
