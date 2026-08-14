# Server transfer — pulls, installs, setup, and what to re-measure

Target: multi-CCD Threadripper/EPYC box replacing the 8-core Zen 4 desktop (7700X-class).
Everything in this `transfer/` directory rode along on this branch: the 2026-08-13 d32 results, and the distilled
Claude project memory (`claude-memory/` → copy to the new box's
`.claude/projects/<project>/memory/` for assistant continuity).

## 1. System packages (apt names; adjust for distro)

- Toolchain: `build-essential` (gcc/g++, make), `pkg-config`, `git`, `cmake`
- **`liburing-dev` — REQUIRED.** `make USE_URING=yes` without it produces a silent
  first-connection hang in 3-stage mode (documented failure, not a build error).
- `libssl-dev`, `tcl` (Redis build + tests), `libjemalloc-dev` optional (TomoKV vendors jemalloc
  in `deps/`; build with `MALLOC=jemalloc`, the +30–54% lever)
- memtier build deps: `autoconf automake libtool libevent-dev libpcre2-dev zlib1g-dev`
- Measurement: `linux-tools-common linux-tools-$(uname -r)` (perf), `numactl`, `hwloc` (topology),
  `util-linux` (flock), `psmisc` (fuser/pkill), `jq`, `python3` (3.10+, stdlib only)
- YCSB: `openjdk-21-jdk maven`
- Garnet (optional baseline): dotnet SDK 8+
- Dragonfly (if building from source): `ninja-build` + their deps — or just pull the release binary

## 2. Pulls

| What | From | Notes |
|---|---|---|
| TomoKV | `git@github.com:henrychen917/tomokv.git` | **light clone**: `git clone -b stable --single-branch`, then `git fetch origin transfer-context:transfer-context` once and harvest `transfer/` (claude-memory -> .claude memory path). All other branches (threadcap128-dev, cx102-writetax-shelved, 2s-atomic-*, audits) stay on gh as archive — fetch on demand only. |
| memtier_benchmark | github RedisLabs/memtier_benchmark | benches will be REWRITTEN for the new server; stock memtier suffices to start |
| Redis (baseline) | github redis/redis, unstable | build `make MALLOC=jemalloc`; the sweep used a v255.255.255 unstable build |
| Dragonfly v1.39 | github dragonflydb release binary x86_64 | pin the same version for comparability (torn result is version-specific) |
| YCSB | github brianfrankcooper/YCSB release tarball | needs the `redis` binding dir; gate jar builds via `bench_suite/make_ycsb_gate.sh` |
| Traces | owner-provided (meta / twitter cache traces + replayer) | `META_TRACE_FILE` / `TWITTER_TRACE_FILE` env for the suite |

## 3. Build order on the new box

```sh
cd tomokv && make -j MALLOC=jemalloc USE_URING=yes    # liburing installed first!
```

Bench harnesses will be rewritten for the new server's topology; the old suite's box-fix lessons
live in `claude-memory/thredis-bench-suite-comparison.md`. Priority workstreams on arrival:
**multi-CCD / high-core-count validation** (per-node flip divergence, threadcap 128/128, CCD-aware
pinning) and the **big-DB sustained-SET fix** (see claude-memory task notes).

## 4. Box setup (before ANY benchmark)

- `kernel.perf_event_paranoid = -1` (sysctl) — perf counters without sudo
- cpufreq governor `performance` on all cores; note boost behavior
- Re-derive the pinning plan: on 24-core, server cores = one full CCD (or two), load generator on a
  DIFFERENT CCD, never share L3 between server and memtier. Old box: server 0-7, loadgen 8-15.
- `numactl --hardware` → record nodes/CCDs; set `tomokv-nodes` to match the topology under test
- Exclusive box discipline: one server + one bench (flock a boxlock file; run `harness/watchdog.sh`)
- Noise floor: establish it FIRST (same A/A cell 4×) before believing any A/B delta

## 5. What to RE-MEASURE / REBUILD on the new box (box-gated verdicts)

Priority order:
1. **The remaining sweep sections**: d128 io/ex curve, d1024 cross-system, zipf, ycsb, traces —
   the d32 protocol transfers unchanged (results/2026-08-13-d32/ is the reference).
2. **"2 6 6 2" per-node flip divergence** — EPYC-gated on the old box (2:1 oversubscription capped
   it): `IOB=4 EXB=4` two-node sim with real per-node IO confinement.
3. **SET p32 sustained-write tax + landing choice** (open issue): 300 s static-io4 SET first
   (separates the +31% landing-choice recovery from the reclamation-backlog tax), then the fix
   ladder (jemalloc `dirty_decay_ms:0` discriminator → bounded-backlog drain → embed threshold).
4. **DRAM-regime verdicts** marked topology-dependent: zero-copy KEEP (wins on 16–64 KB values),
   storage prefetch L3 gate (self-selecting — verify on big-L3 parts), thread-config scaling
   (3-stage WB scaling on large values; i4w2-vs-i4w4).
5. **Dragonfly torn re-verify** with stricter transaction modes before citing externally.
6. Noise floor + quiet-box ceiling re-derivation (guard values are box-specific).
