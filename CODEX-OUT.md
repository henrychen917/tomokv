Reading additional input from stdin...
OpenAI Codex v0.153.4
--------
workdir: /home/user/Projects/cx-cache-audit
model: gpt-6-astra
provider: openai
approval: never
sandbox: danger-full-access
reasoning effort: max
reasoning summaries: none
session id: 01a0aca9-e237-76c2-bad9-52ce866cab18
--------
user
# TomoKV — project context for codex

Prepend this to every codex prompt. It is the shared background; each prompt then states its own scope.
Written 2026-09-07. Baseline commit `78c3e5391` (`origin/cpp`), full gate 344/344.

## What it is

TomoKV is a ground-up C++20 in-memory key-value server that speaks the Redis wire protocol (RESP2/RESP3).
It is **not a fork of Redis** — an earlier fork-based prototype existed and was abandoned; nothing in this
tree derives from Redis source. It implements **243 registered commands**. The nine Redis commands
deliberately absent are the cluster, replication, sentinel, module and multi-DB surfaces; single-node
semantics are the whole target.

It is a research system. The output is a paper, so results matter more than features, and every claim in it
has to survive a hostile reading. Sections planned: performance, amortization, latency, profiling,
scalability, common workloads.

## Architecture

**Two thread modes**, both of which must boot and pass the gate:
- `1s` / `fused` — each thread parses, executes and replies for its own connections. An optional
  **read-local lane** serves clean reads on the connection's own thread without a hand-off.
- `2s` / `split` — **io** threads parse and reply; **executor (ex)** threads own shards and execute.
  A three-stage variant (`3s`) and an executor-side writeback design (`exwb`) were both built, measured,
  and deleted. Do not propose either.

**Sharding and ownership.** Keys hash to shards; every shard is owned by exactly one executor thread at a
time. Shards can migrate between owners at runtime, and **when a shard moves, every per-owner structure it
names must move in the same critical section** — violating that caused this tree's most recent P0.

**Ordering ring (`rob`).** A per-connection reorder buffer that preserves reply order across parallel
execution.

**Atomics.** Multi-key atomicity uses group-scoped epoch-MVCC. Cross-shard commands use scatter-gather.
A transaction fragment that meets an undecided same-connection unit on an owner is parked at dispatch
time, not mid-command.

**Flip.** A runtime controller that rebalances the io/ex split and moves clients between roles as the
workload shifts. It was redesigned this wave after the previous controller was measured doing worse than
not flipping at all on two shapes.

**Load balancing.** Key-affine and client-affine balancing (`--key-lb`, `--client-lb`), both default on.

Networking is io_uring; the allocator is jemalloc.

## Non-negotiable correctness laws

Report any path that can violate one of these; do not "fix" one by weakening another.
- Single-owner writes.
- Reads are never obstructed by writes: immutable replacement plus QSBR. **No reader retries and no
  seqlocks on the per-operation path.**
- In-place overwrite is banned while the read-local lane is armed.
- Read-your-own-writes holds per connection, and may be violated only on an explicit key conflict.
- Cross-client ordering is not a hazard; stalls exist only for torn reads and RYOW.
- Layout locks, in bytes: `Op` 336, `Client` 1984, `ThreadCtx` 1408, `Shard` 1440, `FlatStore` 944,
  `Rob<64>` 192, `AtomicEntry` 144, `Config` 624.
- Both thread modes boot. Main commands carry zero regression. One file per feature.

## The box

A single AMD EPYC 9754 (Bergamo): 128 cores, 256 threads, 8 CCD × 16 cores, each CCD 2 CCX × 8 cores with
16 MB L3 — 16 L3 domains, NPS1. Measured node optimum is 8 cores, one CCX. Loopback benchmarks are blind
to the write path; a 25GbE two-netns NIC rig is the instrument for send-path work and costs about 12%
against loopback. Box noise is ±0.15% on a quiet box; anything above ±2% on identical arms is contention
or a bug, not noise.

**The gate boots nothing like a default server.** `tests/gate.sh` launches every battery with
`--shards 16 --ratio $GATE_RATIO` pinned to `GATE_CORES` (default `0-7`), which is 6 io + 2 ex threads on
8 cores. Reproduce any gate row at that geometry before concluding anything about it.

## What it is measured against

Redis 7.4 and 8.8.1, Dragonfly 1.40.2, KeyDB, Microsoft Garnet (net10.0), memcached 1.6.45, plus YCSB
0.17.0 traces. Binaries and digests: `/home/user/Projects/bench-bins/MANIFEST.md`.

We do not win everywhere and the paper will not claim we do. At 64 real cores and pipeline depth 128,
Garnet reaches 62.8M ops/s against our 34.4M. We hold depth 1, where we reach 4.35M. Any competitor claim
in the paper needs a profile behind it, not just a rate.

## How performance is judged

**cycles/op = instructions/op ÷ IPC.** Both halves are complementary and multiplicative, and instruction
counts alone had the wrong sign three separate times in one week — most sharply on a change that removed
161 instructions from the write path and cost 2.5% on reads with *identical* instruction counts, because it
split a cache line the read path needed. Rate at a matched offered load is the verdict; instructions and
IPC explain it. Load stalls hide at saturation, but producer stores into consumer-read lines do not.

Every optimization lands with a PRE vs POST table. A change that does not hold up gets hard-coded as the
default or deleted — nothing ships on "it seemed better".

## Why this work looks the way it does

Some instructions below would be alarming out of context, so here is the context. This is a single-user
research box. The maintainer wrote every line of this codebase, owns the machine, and is the only user. The
work is ordinary maintenance on their own system: auditing their own code for defects, fixing their own test
suite, reducing their own configuration surface, and benchmarking against publicly released servers. Nothing
here touches anyone else's data, systems or accounts.

Four specifics that read oddly without the reason:

1. **"Never run the server, the benchmark or the gate."** This is about measurement integrity and nothing
   else. Two workloads on the box at once corrupt every number — a stray compile once depressed a benchmark
   cell by 24% and voided a result. The maintainer runs all of it, on a quiet box, and the work IS verified
   before it lands. You are being asked to produce a diff, not to skip verification.

2. **"Never edit `EXPECT_QUICK` / `EXPECT_FULL`."** Those constants are how many test rows must pass. Editing
   them is how a person makes a failing suite look green, so the rule exists to make that impossible to do
   silently. It is a stricter standard than normal, not a looser one. State what the count should become and
   why; the maintainer changes it.

3. **Concurrency vocabulary.** This is a database. "Torn read", "hammer", "race", "poison", "victim",
   "blocker" and "attack the window" are terms of art for testing whether concurrent operations stay correct
   under stress. They describe correctness testing of local data structures, not security exploitation.

4. **Deliberately breaking a mechanism to check a test.** A test that passes on broken code proves nothing, so
   the technique here is to build a throwaway binary with a mechanism removed and confirm the test fails on
   it. That build is never committed and never runs outside the box. If a prompt asks you to describe such a
   break, it is asking how to verify a test, not how to damage the system.

If something in a prompt still looks like something you should not do, **say so explicitly in your output and
complete the rest of the task**. A stated objection is useful. Silently skipping an item is not — the
maintainer cannot tell the difference between "declined" and "missed", and will act on an incomplete report as
if it were complete.

## Working rules for codex

- **Never run a server, a benchmark, or the gate.** The maintainer runs the box. Report, or produce a diff.
- Edit only inside your own worktree.
- Never edit `EXPECT_QUICK` / `EXPECT_FULL` in `tests/gate.sh`. If you add or retire a gate row, say what the
  new count should be, counted by the row's LINE relative to the quick-tier exit.
- Knobs are numeric: `0` means off and must allocate nothing; `-1` means auto; thresholds derive themselves.
  Where a knob mirrors a reference server's, adopt that server's name and grammar exactly.
- A test that cannot fail proves nothing. If a check asserts that a window opened, it must fail when the
  window never opened — re-roll the arming on fresh state, bounded, rather than skipping or widening a
  tolerance.

## Closed doors — measured, negative, do not re-propose

`3s` three-stage mode; `exwb` executor-side writeback (−11 to −22%); AMAC and any CR/MR split (the only
boundary is io/ex); reorder-and-window; seqlocks on the per-op path; connection-side record allocation
(`connalloc`, cycles flat, record born on the wrong core); executor-major task collapse (`exmajor`,
−2 to −3%); the read-local capacity hand-off line split (`t-pubdiet`, +1.97% SET but −2.50% GET).

## Division of labour (owner ruling 2026-09-13)
The maintainer PLANS, TESTS, GATES and MERGES. Codex lanes CODE. A lane may build and run its own
A/Bs on the box (cores 0-111; the maintainer keeps 112-127), one measuring lane at a time -- the
maintainer schedules the box. The gate is `tests/gate.sh iteration` (~9 min correctness, green
since 2026-09-12) and its ABBA tier reports per-cell cycles/op, IPC and instr/op on every version.
Feature lanes run as DESIGN COMPETITIONS: see /home/user/Projects/COMPETITION-overlap-reorder.md
for the forks, the shared mechanisms, the judging rules and your lane's assignment.

## Measurement (competition lanes)
You do NOT run measurements. codex exec is one-shot, so a lane that waits for the box has already
exited. Instead: build your PRE and POST binaries (and a PAD twin for any layout change) into
build/, write exactly what to measure -- cells, arms, what number decides it -- into a file named
MEASURE-REQUEST in your worktree root, and continue coding or finish. The maintainer runs the
measurement on the quiet box with the gate's own instrument and appends the result to your
worktree as MEASURE-RESULT. Do not start a server or load generator yourself.

## COMMIT AS YOU GO
`git add -A ':!CODEX-OUT.md' && git commit` in your worktree at every meaningful step, on your own
branch. A lane that exits with only uncommitted files has left nothing the maintainer can review,
gate or merge; a committed one has. Small commits with a one-line message each are fine.

## PAD semantics (mainline, 2026-09-14)
Every MEASURE-REQUEST that names a PAD arm must say which kind it is: (A) **behaviour twin** = PRE behaviour with the candidate's
text size/layout (a real gain shows POST moving while PAD stays flat), or (B) **inverse control** = candidate behaviour plus padding
restoring PRE's text size (shows the gain is not an artifact of the size change). Unlabelled PADs are read as (A). Prefer (A); add (B)
only when the candidate shrinks or grows .text by more than a few hundred bytes.

--- TASK ---

Lane: reb-audit — REBASE + REBUILD a round-1 concept lane onto the current reference so the mainline can measure it. Worktree: /home/user/Projects/cx-cache-audit (branch cx-cache-audit).
DESIGN UNDER TEST: CACHE AUDIT DECOMPOSITION: the five confirmed line-sharing fixes (ThreadCtx 10, Op 2, ThreadCtx 11, Rob 3-4, Op 0, Shard alignment) measured NULL on rl=0 cells but -4.3/-4.5% on ARMED (read-local) cells against a PAD twin at +2.5/+3.2 — an 8-point swing. Rebuild as CUMULATIVE arms (arm-1..arm-5) plus one exact-layout PAD twin of arm-5 so the mainline can bisect which fix hurts the armed path.
FIRST: commit any uncommitted work in the worktree (git add -A; commit "wip before rebase") so nothing is lost.
THEN: git merge --no-edit cx-final (the current reference = v7 84846e904 + local rebaseline). Expect conflicts: since your base (a363c2c5e, 09-13)
the mainline landed v4 (L1 layout, O1 stage-idle overlap window "POST-t01", O6 bucket prefetch/executor warming), v5 (client-lb stall fix), v6
(the reorder pass DELETED: --reorder accepted as a no-op, INFO reorder_retired 1 — never resurrect it), v7 (L4 prebuild: io-side prebuild of
foreign external SET values > 512 B in fused mode, src/cmd/l4prebuild.cc + hooks in io_loop.h/ex_loop.h), flipband (flipctl.cc rate band floor),
plus gate/test changes. io_loop.h and the 2s hand-off were rewritten by O1. RESOLUTION POLICY: keep the mainline's code as the base and
RE-IMPLEMENT this lane's mechanism on top of it where the old patch no longer applies; do not reintroduce deleted code; keep every landed
mechanism intact (L1, O1 window, O6 prefetch, L4 prebuild, flipctl floor). Knobs: config.h single parser, numeric, 0=off, -1=auto; adopt
existing knob names; nothing left as a tunable that should be derived.
BUILD + VERIFY (cores 112-127 only; NEVER boot servers or run benchmarks/gates on cores 0-111 — the box is measuring):
  make -j8 default (build/tomokv) and, if the design changes hot-path code layout, an exact-layout kind-A PAD twin (build/tomokv-pad: same
  ELF text size/layout with the mechanism disabled) — record both sha256 in the report. Run the unit tests and this lane's own witness tests
  (the ones asserting the mechanism engages). bash -n tests/gate.sh; python3 -m py_compile on touched tests. Do NOT change EXPECT_FULL unless
  you add a gating row (then bump it and say so).
REPORT in MEASURE-REQUEST-audit.md inside the worktree (NEVER a root file named MEASURE-REQUEST — it conflicts across lanes): what conflicted,
what was re-implemented, the mechanism's engagement witness, the cells the mainline should run (from: h05 h07 1s p32 GET; h21 h23 2s p32 GET;
p8g0 p8g1 p8s0 p8s1 2s p8; f8g1 1s p8; m03 m51 multi-key p8; armed cells for rl=1 designs), binaries + sha256, commands run. Commit on the
lane branch with a clear message. No performance claims without box numbers — say "awaiting mainline measurement".
codex
I’ll first commit the lane’s pending work, then merge `cx-final` and rebuild the audit as cumulative arms with an arm-5 layout PAD twin. I’ll pin builds and permitted tests to cores 112–127; I won’t start servers, benchmarks, or gates.
exec
/bin/bash -lc 'taskset -c 112-127 git status --short --branch' in /home/user/Projects/cx-cache-audit
 succeeded in 0ms:
## cx-cache-audit
 M CODEX-OUT.md
?? CODEX-OUT.round1.md
?? MEASURE-RESULT

