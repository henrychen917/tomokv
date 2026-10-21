#!/usr/bin/env python3
"""NT-new-4: hold an owner's sampled clock until newer requests are queued.

Like perfex_checks.py, only the gate child loads the mmap/LD_PRELOAD clock.
There is no production hook. The gate owns boot/stop, CPU placement and ports.
All four observations and the post-release control are reported even on PRE.
"""
import argparse
from contextlib import ExitStack, closing
import json
import mmap
from pathlib import Path
import re
import struct
import subprocess
import time

from _lib import Conn, encode, lbsignals, shards_of, topology


CLOCK_SOURCE = r"""
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <sched.h>
#include <stdint.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>
struct control {
    int64_t frozen_ms;
    uint64_t arm_gen, release_gen, stalled, timeouts;
    uint64_t cpus[16];
};
static struct control *page;
static __thread uint64_t consumed;
static int (*real_clock)(clockid_t, struct timespec *);
__attribute__((constructor)) static void init_clock(void) {
    real_clock = dlsym(RTLD_NEXT, "clock_gettime");
    const char *path = getenv("TOMO_NTNEW4_CLOCK");
    if (!path) _exit(91);
    int fd = open(path, O_RDWR);
    if (fd < 0) _exit(92);
    void *p = mmap(0, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (p == MAP_FAILED) _exit(93);
    page = p;
}
static int real_time(clockid_t id, struct timespec *ts) {
    return real_clock ? real_clock(id, ts) : syscall(SYS_clock_gettime, id, ts);
}
int clock_gettime(clockid_t id, struct timespec *ts) {
    if (id != CLOCK_REALTIME || !page) return real_time(id, ts);
    // Sample FIRST: the release returns this old value, exactly as if the
    // executor were preempted immediately after a successful vDSO read.
    int64_t ms = __atomic_load_n(&page->frozen_ms, __ATOMIC_ACQUIRE);
    uint64_t gen = __atomic_load_n(&page->arm_gen, __ATOMIC_ACQUIRE);
    int cpu = sched_getcpu();
    if (gen > consumed && cpu >= 0 && cpu < 1024 &&
        (__atomic_load_n(&page->cpus[cpu / 64], __ATOMIC_RELAXED) & (1ULL << (cpu % 64)))) {
        consumed = gen;
        struct timespec start, now, pause = {0, 50000};
        real_time(CLOCK_MONOTONIC, &start);
        __atomic_fetch_add(&page->stalled, 1, __ATOMIC_RELEASE);
        while (__atomic_load_n(&page->release_gen, __ATOMIC_ACQUIRE) < gen) {
            real_time(CLOCK_MONOTONIC, &now);
            if ((now.tv_sec - start.tv_sec) * 1000000000LL + now.tv_nsec - start.tv_nsec >= 2000000000LL) {
                __atomic_fetch_add(&page->timeouts, 1, __ATOMIC_RELEASE);
                break;
            }
            nanosleep(&pause, 0);
        }
    }
    if (!ms) return real_time(id, ts);
    ts->tv_sec = ms / 1000;
    ts->tv_nsec = (ms % 1000) * 1000000;
    return 0;
}
"""


def require(ok, why):
    if not ok:
        raise AssertionError(why)


def prepare(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(4096))
    subprocess.run(["cc", "-x", "c", "-", "-O2", "-Wall", "-Wextra", "-fPIC", "-shared",
                    "-o", str(path) + ".so", "-ldl"],
                   input=CLOCK_SOURCE, text=True, check=True)


def observe(check, actual, expected):
    ok = actual == expected
    print(json.dumps(dict(check=check, actual=actual, expected=expected, ok=ok),
                     default=lambda value: value.decode() if isinstance(value, bytes) else repr(value)),
          flush=True)
    return ok


def clock_check(args):
    with ExitStack() as stack:
        file = stack.enter_context(args.clock_file.open("r+b"))
        clock = stack.enter_context(mmap.mmap(file.fileno(), 4096))
        admin = stack.enter_context(closing(Conn(args.host, args.port, timeout=5)))

        def put(offset, value):
            struct.pack_into("Q", clock, offset, value)

        def get(offset):
            return struct.unpack_from("Q", clock, offset)[0]

        origin = time.time_ns() // 1_000_000
        put(0, origin)
        time.sleep(.06)  # exceeds the 50 ms park; exact PTTL below proves the freeze
        require(admin.must("DEBUG", "SET-ACTIVE-EXPIRE", 0) == b"OK", "disable active expiry")
        require(admin.must("FLUSHALL") == b"OK", "fresh clock fixture")
        topo = topology(admin)
        require(topo.mode == args.mode, f"wrong thread mode: {topo.mode}")
        require(len(topo.shard_owner) == 16, "clock proof requires the gate's 16 shards")
        boot = {int(tid): (role, int(cpu)) for tid, role, cpu in re.findall(
            r"thread t(\d+): role=(\w+) cpu=(\d+)", args.server_log.read_text())}
        require(set(topo.roles) <= boot.keys(), "boot log missing thread CPU map")

        # Resolve the probe connection's IO thread by the +1 client count. All
        # connections stay open until teardown, and placement controls are off.
        # No same-thread fused request is allowed to masquerade as inbox work.
        before = {t.tid: t.clients for t in lbsignals(admin).threads}
        probe = stack.enter_context(closing(Conn(args.host, args.port, timeout=5)))
        require(probe.must("PING") == b"PONG", "probe connection ready")
        after = {t.tid: t.clients for t in lbsignals(admin).threads}
        io = [tid for tid in before if after[tid] == before[tid] + 1]
        require(len(io) == 1 and sum(after.values()) == sum(before.values()) + 1,
                f"ambiguous connection thread: {before} -> {after}")
        owner = next(tid for tid in topo.owners if tid != io[0])
        target_shard = next(sid for sid, tid in topo.shard_owner.items() if tid == owner)
        keys = []
        for base in range(0, 8192, 256):
            candidates = [f"ntnew4:{i}" for i in range(base, base + 256)]
            keys += [key for key, (sid, _) in zip(candidates, shards_of(admin, candidates))
                     if sid == target_shard]
            if len(keys) >= 3:
                break
        require(len(keys) >= 3, "could not find three keys on the selected owner")
        a, b, h = keys[:3]
        require(admin.must("SET", a, "v", "PXAT", origin + 1_000_000) == b"OK", "long TTL")
        require(admin.must("SET", b, "v", "PXAT", origin + 20) == b"OK", "short TTL")
        require(admin.must("HSET", h, "f", "v") == 1, "hash fixture")
        require(observe("frozen clock non-vacuity", probe.must("PTTL", a), 1_000_000),
                "frozen realtime window did not open")
        # Let any preceding command batch finish before arming an idle pass.
        time.sleep(.06)
        targets = [boot[tid][1] for tid in topo.owners] if args.mode == "2s" else [boot[owner][1]]
        require(boot[io[0]][1] not in targets, "probe IO thread would be held")
        for cpu in targets:
            require(0 <= cpu < 1024, "CPU outside shim mask")
            offset = 40 + (cpu // 64) * 8
            put(offset, get(offset) | (1 << (cpu % 64)))
        print(json.dumps(dict(mode=args.mode, owner=owner, shard=target_shard,
                              probe_thread=io[0], targets=targets, t0=origin, t1=origin + 50)), flush=True)
        put(8, 1)
        try:
            deadline = time.monotonic() + 1
            while get(24) != len(targets) and time.monotonic() < deadline:
                time.sleep(.001)
            require(observe("stall non-vacuity", get(24), len(targets)), "window did not open")
            put(0, origin + 50)
            probe.raw(b"".join(encode(*cmd) for cmd in [
                ("PTTL", a), ("GET", b), ("EXISTS", b),
                ("HPEXPIREAT", h, origin + 30, "FIELDS", 1, "f")]))
            time.sleep(.2)  # IO parses/posts while the owning executor is held
            require(get(32) == 0, "shim stall timed out before release")
        finally:
            put(16, 1)
        answers = [probe.read() for _ in range(4)]
        results = [observe(name, actual, expected) for name, actual, expected in zip(
            ("PTTL", "GET expired key", "EXISTS expired key", "HPEXPIREAT past deadline"),
            answers, (999_950, None, 0, [2]))]
        # Require a later pass on PRE too, then check the same current frozen
        # time. Report this even when one or all of the four defect probes fail.
        time.sleep(.06)
        control = observe("post-release control PTTL", probe.must("PTTL", a), 999_950)
        require(get(32) == 0, "shim stall hit its safety timeout")
        require(control and all(results), f"NT-new-4: {results.count(False)}/4 stale-clock replies")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "check"))
    parser.add_argument("--clock-file", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--mode", choices=("1s", "2s"))
    parser.add_argument("--server-log", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.clock_file)
    else:
        require(args.port and args.mode and args.server_log, "check needs port, mode and server log")
        clock_check(args)


if __name__ == "__main__":
    main()
