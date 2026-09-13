Reading additional input from stdin...
OpenAI Codex v0.153.4
--------
workdir: /home/user/Projects/cx-deadconf-fix
model: gpt-6-astra
provider: openai
approval: never
sandbox: danger-full-access
reasoning effort: max
reasoning summaries: none
session id: 01a098f6-bd7d-73d1-a8fa-a9bb9f89a830
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

--- TASK ---

You are fixing configuration defects confirmed by a code audit. You CODE; the maintainer tests, gates
and merges. Build and unit-test on cores 112-127 only. Never `pkill -f`/`pgrep -f`. COMMIT AS YOU
GO on your branch (git add -A ':!CODEX-OUT.md' && git commit) -- small commits, one per item below.

Read /home/user/Projects/AUDIT-deadconf-verdict.md first: every item there is CONFIRMED against the
code with file:line evidence. Do not re-audit; fix.

ITEMS, each its own commit, each with a TEST THAT FAILS ON THE OLD CODE:
 1. FIVE uint32_t TRUNCATIONS -- latency-monitor-threshold, stream-node-max-entries,
    stream-node-max-bytes, --script-crossshard-cut-slots, --script-crossshard-conflict-retries.
    Today 4294967296 is accepted, echoed back, and consumed as 0 (feature silently off). Do what
    Redis does: reject an out-of-range value at parse with an error (CONFIG SET returns
    "ERR ... argument must be between ..."; a boot flag refuses to boot). Match Redis's exact
    bounds and message grammar for the three Redis-named knobs. Reproducer per knob: set
    4294967296, expect an error, not a silent zero.
 2. ZERO-COPY (N1+N7, ONE commit): tomokv.conf says zc 0 "disables entirely" but 0 is not mapped;
    map 0 -> UINT32_MAX at both install sites. AND the two consumers disagree by one: GET borrows
    at value.n >= zc_min (t_string.cc:400,412), MGET gather at > (scatter_engine.inc:2943). Align
    the gather to >=. Test: a value of exactly the cutover is treated identically by GET and MGET.
 3. TRACKING-TABLE EVICTION (N8): tracking.cc:138 evicts unordered_map::begin() -- deterministic
    and biased -- while its own comment and tomokv.conf claim a RANDOM victim. Make it random
    (sample; a full table must not re-evict the same subset forever). Standalone commit.
 4. DOC-ONLY (N10-N12, one commit touching only tomokv.conf): aof rewrite fires at ">" not "at
    least"; kRobWindow lives in net/rob.h not net/conn.h; tracking-table-max-keys is boot-only and
    per-IO-owner, so drop the bare "redis semantics" phrase.
 5. THE 3 INHERITED CONTRADICTIONS: ACL selectors (conf says rejected, acl.inc:329-383 stores
    them) -- REJECT them at parse until enforcement exists, do not silently store; connection
    "for life" claim vs climon.cc:292-294 tracking extraction on move -- fix the CONF, the code is
    right (connections move under client-lb); list-max-compact-entries caps lists (conf says no
    cap) -- fix the conf to describe the cap.
DO NOT touch N9 (RESP3 pub/sub exemption): it needs an owner decision first.
DO NOT touch the SORT globless-BY item: unverified.
Knob rules: numeric, 0 = off allocates nothing, -1 = auto; Redis-named knobs match Redis exactly.
Write MEASURE-REQUEST only if a change could plausibly move performance (item 2 can: say which
cells). Report: a table [item | files | test that fails on old code | commit].

N9 DECIDED BY THE OWNER: MATCH REDIS. Exempt only RESP2 subscribers from the client-eviction budget,
as Redis does (Redis sets CLIENT_PUBSUB for RESP2 only). io_loop.h:6063 exempts on
!c->subscriber_mode() with no RESP test, and pubsub.inc:737 sets that flag regardless of protocol.
Add the RESP2 test; a RESP3 subscriber is no longer exempt. Test: a RESP3 SUBSCRIBE client is
counted against the budget; a RESP2 one is not. Own commit. Update tomokv.conf:52 to say RESP2.

CONTINUATION-N9 (mainline 12:12): your six commits are received and will be gated. ONE item remains,
decided by the owner after you finished: N9 -- MATCH REDIS. Exempt only RESP2 subscribers from the
client-eviction budget (io_loop.h:6063 has no RESP test; pubsub.inc:737 sets subscriber_mode
regardless of protocol). Add the RESP2 test; update tomokv.conf:52 to say RESP2. Test: a RESP3
SUBSCRIBE client counts against the budget, a RESP2 one does not; the test must FAIL on the old
code. One commit. Nothing else. Compile on 112-127. Commit and stop.
codex
I’ll make only the N9 change, add a regression test that fails on the old code, then build and unit-test on cores 112–127. I’ll commit it without running a server, benchmark, or gate.

exec
/bin/bash -lc 'cat /home/user/Projects/AUDIT-deadconf-verdict.md' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
# deadconf audit — Opus agent verdict 2026-09-13 (mainline record; not in git)
Agent scope: config.h / tomokv.conf / main.cc and their consumers. Read-only.

## The 8 inherited claims (from the content-filtered rep-deadconf lane)
5 uint32_t truncations (4294967296 accepted, echoed, consumed as 0 = feature silently OFF):
  latency-monitor-threshold, stream-node-max-entries, stream-node-max-bytes,
  --script-crossshard-cut-slots, --script-crossshard-conflict-retries      -> CONFIRMED
3 conf/code contradictions: ACL selectors parsed+stored (conf says rejected); tracking state
  extracted on IO move (conf says "for life"); list-max-compact-entries caps (conf says no cap) -> CONFIRMED
## New findings from the sweep (7 verified by the agent, 1 unverified)
N1/N7 zero-copy: conf:163 "0 disables" is false (0 is not mapped); AND the two consumers of the same
     knob disagree by one: GET borrows at >= zc_min, MGET gather at > (scatter_engine.inc:2943).
     One commit: map 0 -> UINT32_MAX at both install sites AND align the gather to >=.
N8   tracking-table eviction: conf + code comment say "random victim"; tracking.cc:138 evicts
     unordered_map::begin() -- deterministic, biased. REAL CODE DEFECT, small, standalone commit.
N9   RESP3 subscribers are exempted like RESP2 (io_loop.h:6063 has no RESP test); Redis exempts
     RESP2 only. Needs a DECISION, then code or conf.
N10-N12 doc-only (aof rewrite ">" vs "at least"; kRobWindow pointer wrong file; tracking-table
     claims redis semantics but is boot-only per-owner). One tomokv.conf commit.
N?   SORT globless BY with STORE (t_sort.cc:89-93) -- UNVERIFIED, command semantics, spot-check.
~60 other conf claims checked and CORRECT.

## Disposition (mainline)
* Coding lane "deadconf-fix" (codex): the 5 truncations -> reject out-of-range at parse like Redis
  does (CONFIG SET returns an error); N1+N7 as one commit; N8 as one commit; N10-N12 as one conf
  commit. Every fix ships with a test that FAILS on the old code (the 4294967296 -> 0 case is a
  one-line reproducer each).
* Decision for the owner: N9 (RESP3 pub/sub exemption) -- match Redis (RESP2 only) or keep ours?
* Confirm-or-refute of the fix = mainline (me), via the gate + the reproducers.

exec
/bin/bash -lc "pwd && rg --files -g AGENTS.md -g '"'!build*'"' -g '"'!vendor'"' -g '"'!third_party'"' /home/user/Projects 2>/dev/null" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
/home/user/Projects/cx-deadconf-fix
/home/user/Projects/valkey/AGENTS.md
/home/user/Projects/dragonfly/helio/AGENTS.md
/home/user/Projects/dragonfly/AGENTS.md

exec
/bin/bash -lc 'git status --short && git branch --show-current && git log -9 --oneline' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
?? CODEX-OUT.round1.md
cx-deadconf-fix-items
528cb0b15 reject ACL selectors and correct ownership and list-limit comments
f1b61114a correct AOF, ROB and tracking configuration comments
9ab54c4e1 sample tracking eviction victims across buckets and collisions
36f7c17dc honor zero-copy off and inclusive GET/MGET cutovers
8c73d5d46 reject overflowing uint32 configuration limits
831b5499e preserve measurement metadata from worktree recovery
a363c2c5e gate: the ABBA row honours an explicit plan budget, overriding only a history-derived one
b9ed48b29 gate: the ABBA row never takes a history-derived timeout
0adfaac27 gate: correctness gates merges; ABBA reports every version and does not decide

exec
/bin/bash -lc 'for p in /AGENTS.md /home/AGENTS.md /home/user/AGENTS.md /home/user/Projects/AGENTS.md /home/user/Projects/cx-deadconf-fix/AGENTS.md; do if [ -f "$p" ]; then cat "$p"; fi; done' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
exec
/bin/bash -lc "rg -n 'subscriber_mode\\(|maxmemory.clients|client.eviction|client.evict|evict.*client' src tests CMakeLists.txt tomokv.conf && rg --files -g '*test*' -g '*CMake*' -g '*Makefile*' -g 'AGENTS.md' -g '"'!build*'"' -g '"'!third_party'"' -g '"'!vendor'"'" in /home/user/Projects/cx-deadconf-fix
 exited 2 in 0ms:
rg: CMakeLists.txt: No such file or directory (os error 2)
tomokv.conf:197:# random entry is evicted AND its owner is sent an invalidation for that key, so a client can
src/core/io_loop.h:3474:                            } else if (c->blocked() || c->subscriber_mode()) {
src/core/io_loop.h:3675:            const bool subscriber_mode = __builtin_expect(c->subscriber_mode(), false);
src/core/io_loop.h:6008:        const ClientBufferLimit& limit = c->subscriber_mode() ? limits.pubsub : limits.normal;
src/core/io_loop.h:6063:            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
src/core/pubsub.inc:706:        if (local.client) local.client->set_subscriber_mode(false);
src/core/pubsub.inc:737:                client->set_subscriber_mode(pubsub_total_subscription_count(local) != 0);
tests/cmdmeta.py:16:client|help client|id client|info client|kill client|list client|no-evict client|no-touch
tests/differ.py:5072:client|help client|id client|info client|kill client|list client|no-evict client|no-touch
src/cmd/tracking.cc:263:    if (!resp3_push && (!redirected || !target->subscriber_mode())) return;
src/net/conn.h:635:    bool subscriber_mode() const { return subscriber_mode_; }
src/net/conn.h:636:    void set_subscriber_mode(bool v) { subscriber_mode_ = v; }
src/cmd/command.h:356:void command_client_set_no_evict(Client* client, bool enabled);
src/cmd/t_server.cc:221:    if (client.subscriber_mode()) *flag++ = 'P';
src/cmd/t_server.cc:1264:        // maxmemory-clients output-buffer eviction. TomoKV has neither maxmemory-clients nor a
src/cmd/t_server.cc:1267:        command_client_set_no_evict(g_client, eq_icase(op.arg(2), "ON"));
src/cmd/t_server.cc:3219:        const bool pubsub = client.subscriber_mode();
src/cmd/t_server.cc:3253:void command_client_set_no_evict(Client* client, bool enabled) {

exec
/bin/bash -lc "git worktree list && rg --files -g '*MEASURE*' -g 'CODEX*' -g 'CMakeCache.txt' -g 'CTestTestfile.cmake' -g 'build.ninja' -g 'Makefile' -g '"'!third_party'"' -g '"'!vendor'"' -g '"'!deps'"' -g '"'!bench*'"' && ls -ld build*" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
/home/user/Projects/tomokv-cpp                                  a363c2c5e [cpp]
/home/user/Projects/cx-cache-L1                                 69ddf87a1 [cx-cache-L1]
/home/user/Projects/cx-cache-L1/build/cache-L1/candidate02-src  8263c67c8 [cx-cache-L1-c2]
/home/user/Projects/cx-cache-L2                                 695b3c8c3 [cx-cache-L2]
/home/user/Projects/cx-cache-L3                                 9d5684bd3 [cx-cache-L3]
/home/user/Projects/cx-cache-L4                                 2248c38bf [cx-cache-L4]
/home/user/Projects/cx-cache-L5                                 97bbe689f [cx-cache-L5]
/home/user/Projects/cx-deadconf-fix                             528cb0b15 [cx-deadconf-fix-items]
/home/user/Projects/cx-delvar                                   5f64b1734 [cx-delvar]
/home/user/Projects/cx-final                                    3adaaae06 [cx-final]
/home/user/Projects/cx-gaterigor-integration                    25cf9ffd3 [cx-gaterigor-integration]
/home/user/Projects/cx-nowaitb                                  a055beb85 [cx-nowaitb]
/home/user/Projects/cx-overlap-O1                               b3c1fba75 [cx-overlap-O1]
/home/user/Projects/cx-overlap-O10                              586eb7ae6 [cx-overlap-O10]
/home/user/Projects/cx-overlap-O11                              e2fc6873e [cx-overlap-O11]
/home/user/Projects/cx-overlap-O2                               ec20893f7 [cx-overlap-O2]
/home/user/Projects/cx-overlap-O5                               783fbecb5 [cx-overlap-O5]
/home/user/Projects/cx-overlap-O6                               3682294fb [cx-overlap-O6]
/home/user/Projects/cx-overlap-O7                               30418dbb1 [cx-overlap-O7]
/home/user/Projects/cx-overlap-O8                               3c75ed673 [cx-overlap-O8]
/home/user/Projects/cx-overlap-O9                               95ea5941f [cx-overlap-O9]
/home/user/Projects/cx-readlocal-obs                            5c943ace9 [cx-readlocal-obs]
/home/user/Projects/cx-redisgap                                 0939cecc5 [cx-redisgap]
/home/user/Projects/cx-reorder-R1                               d97779ecb [cx-reorder-R1]
/home/user/Projects/cx-reorder-R2                               9bf786455 [cx-reorder-R2]
/home/user/Projects/cx-reorder-R4                               81d4d1cb6 [cx-reorder-R4]
/home/user/Projects/cx-reorder-R5                               1809ef4e2 [cx-reorder-R5]
/home/user/Projects/cx-reorder-R6                               30d8d90cb [cx-reorder-R6]
/home/user/Projects/cx-reorder-R7                               c862246cd [cx-reorder-R7]
/home/user/Projects/cx-reorder-R8                               a363c2c5e [cx-reorder-R8]
/home/user/Projects/tomokv-cpp-perthread                        e821f56f2 [t-merge14-recovered]
/home/user/Projects/tomokv-cpp-stable                           c7618cda0 [stable-recovered]
CODEX-OUT.round1.md
CODEX-OUT.md
Makefile
MEASURE-REQUEST
drwxrwxr-x 7 user user 4096 Sep 13 11:56 build

exec
/bin/bash -lc "rg --files -g '*test*' -g '*CMake*' -g '*Makefile*' -g 'AGENTS.md' -g '"'!build*'"' -g '"'!third_party'"' -g '"'!vendor'"' && sed -n '1,250p' Makefile && cat CODEX-OUT.md && cat .gitignore" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
Makefile
tests/_abba_test_fixtures.py
tests/gate_process_test.py
tests/config_parser_test.cc
tests/background_environment_test.py
tests/gates_test.py
tests/differ_fanout_test.py
tests/foreign_read_safety_test.cc
CXX      ?= g++
JEDIR    ?= /home/user/Projects/refs/jemalloc/_install
# jemalloc is optional: without it the tree still builds and runs, using the deterministic portable
# size-class table in alloc.h. Set JE=0 to force that path (useful for A/B-ing the allocator).
JE       ?= 1
ifeq ($(JE),1)
  # Prefer the system package; fall back to the copy built from refs/.
  ifneq ($(wildcard /usr/include/jemalloc/jemalloc.h),)
    JEFLAGS := -DTOMO_JEMALLOC
    JELIBS  := -ljemalloc
  else
    JEFLAGS := -DTOMO_JEMALLOC -I$(JEDIR)/include
    JELIBS  := $(JEDIR)/lib/libjemalloc.a -ldl
  endif
else
  JEFLAGS :=
  JELIBS  :=
endif
CXXFLAGS ?= -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread
LDLIBS   ?= -luring -pthread
SRC      := src/main.cc src/net/tls.cc src/cmd/commands.cc src/cmd/glob.cc src/cmd/xshard.cc src/cmd/acl.cc src/cmd/hll.cc src/cmd/t_server.cc src/cmd/t_string.cc src/cmd/t_string_notify.cc src/cmd/t_hash.cc src/cmd/t_hash_ttl.cc \
            src/cmd/t_list.cc src/cmd/t_set.cc src/cmd/t_zset.cc src/cmd/t_zset_ops.cc src/cmd/geo.cc src/cmd/t_stream.cc src/cmd/t_stream_groups.cc src/cmd/scripting.cc src/cmd/functions.cc src/cmd/serialize.cc src/snapshot/snapshot.cc src/persist/aof.cc
SRC      += src/cmd/climon.cc src/cmd/tracking.cc
SRC      += src/cmd/server_tail.cc src/cmd/slowlog.cc src/cmd/lcs.cc src/cmd/info_stats.cc
SRC      += src/cmd/lbsignals.cc
SRC      += src/core/flipctl.cc
SRC      += src/core/genthread.cc
SRC      += src/core/rl2s.cc
SRC      += src/cmd/cmdgap.cc
SRC      += src/cmd/pfdebug.cc
SRC      += src/cmd/cmdmeta.cc
SRC      += src/cmd/t_sort.cc
LDLIBS   += -lssl -lcrypto
BIN      := build/tomokv
OBJ      := $(SRC:%.cc=build/%.o)

all: $(BIN)

$(BIN): $(OBJ)
	$(CXX) $(CXXFLAGS) $(OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

# The clean string family intentionally excludes the armed instantiations, but its parsed template
# bodies still move GCC just past the default large-unit threshold. 10600 restores the same inlining
# decisions as the base-420b4d492 translation unit; the objdump gate locks cmd_get/cmd_set to base.
build/src/cmd/t_string.o: CXXFLAGS += --param large-unit-insns=10600

build/%.o: %.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) $(wildcard third_party/lua/*) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. -c $< -o $@

asan: CXXFLAGS += -fsanitize=address,undefined -fno-omit-frame-pointer -O1
asan:
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. $(SRC) -o build/tomokv-asan $(LDLIBS) -lm

tsan:
	@mkdir -p build
	$(CXX) -std=c++20 -O1 -g -Wall -Wextra -pthread -fsanitize=thread \
	  -I. $(SRC) -o build/tomokv-tsan $(LDLIBS) -lm

# The armed-write block cache's ownership laws as assertions: the cache and the QSBR retire ring
# are owner-private (one thread, no lock), each cached block is resident exactly once, each class
# list matches its counter, and every shard's retire sink names its CURRENT owner. Debug-only: the
# residency set and the sampled list walk cost far more than the path they guard. DESIGN-P0REPLY.md.
rlcachedbg:
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_RL_CACHE_DEBUG -I. $(SRC) \
	  -o build/tomokv-rlcachedbg $(JELIBS) $(LDLIBS) -lm

# NEGATIVE-CONTROL BUILD for the row above: the same assertions with the ownership-edge rebind
# removed, i.e. the pre-fix behaviour. tests/rlcache_churn.py MUST fail against this binary; a
# detector that cannot report failure proves nothing about the runs that pass.
rlcache-nofix:
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_RL_CACHE_DEBUG -DTOMO_RL_CACHE_NO_EAGER_ADOPT -I. $(SRC) \
	  -o build/tomokv-rlcache-nofix $(JELIBS) $(LDLIBS) -lm

# NEGATIVE-CONTROL BUILD for the cross-owner script reservation sub-wave. Identical to the release
# build except that ScriptPhase::Pin arms nothing, so tests/xscript.py counterexample MUST fail
# against it. A detector that cannot report failure proves nothing about the runs that pass.
noreserve:
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_XSCRIPT_NO_RESERVE -I. $(SRC) \
	  -o build/tomokv-noreserve $(JELIBS) $(LDLIBS) -lm

# Server-less unit binaries: the config parser and the flip controller. `make unit` builds and
# runs both (neither boots a server). tests/gate.sh's parser row is the same program.
build/config-parser-test: tests/config_parser_test.cc $(wildcard src/*/*.h) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/config_parser_test.cc -o $@
build/flipctl-unit: tests/flipctl_unit.cc src/core/flipctl.cc $(wildcard src/*/*.h) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/flipctl_unit.cc src/core/flipctl.cc -o $@
# The fused owner's deferred-reclaim ring (QSBR batches) against a per-entry reference model.
build/read-local-ring-unit: tests/read_local_ring_unit.cc $(wildcard src/*/*.h) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/read_local_ring_unit.cc -o $@
build/read-local-write-ring-unit: tests/read_local_write_ring_unit.cc $(wildcard src/*/*.h) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/read_local_write_ring_unit.cc -o $@
# The production cross-connection scheduler, with real ROB tasks at both executor capacities.
build/reorder-unit: tests/reorder_unit.cc $(wildcard src/*/*.h) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/reorder_unit.cc -o $@
STORE_REGRESSION_SRC := tests/store_regression.cc src/cmd/t_hash.cc src/cmd/t_hash_ttl.cc
build/store-regression: $(STORE_REGRESSION_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -ffunction-sections -fdata-sections -DTOMO_STORE_REGRESSION_TEST -I. \
	  $(STORE_REGRESSION_SRC) -Wl,--gc-sections -o $@
build/store-regression-sidecar: $(STORE_REGRESSION_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -ffunction-sections -fdata-sections -DTOMO_STORE_REGRESSION_TEST \
	  -DTOMO_TTL_DEADLINE_SIDECAR=1 -I. $(STORE_REGRESSION_SRC) -Wl,--gc-sections -o $@
build/store-regression-tsan: $(STORE_REGRESSION_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -O1 -fsanitize=thread -fno-omit-frame-pointer -no-pie \
	  -ffunction-sections -fdata-sections -DTOMO_STORE_REGRESSION_TEST -I. \
	  $(STORE_REGRESSION_SRC) -Wl,--gc-sections -o $@
build/waits-unit: tests/waits_unit.cc $(wildcard src/*/*.h) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/waits_unit.cc -o $@
unit: build/config-parser-test build/flipctl-unit build/read-local-ring-unit build/read-local-write-ring-unit build/reorder-unit build/waits-unit
	./build/config-parser-test
	./build/flipctl-unit
	./build/read-local-ring-unit
	./build/read-local-write-ring-unit
	./build/reorder-unit
	./build/waits-unit

# Deterministic core regressions: the test TU instantiates the real executor/IO methods
# with ASAN/UBSAN and test-only interleaving hooks. No server or ring is started.
CORE_TEST_OBJ := $(filter-out build/src/main.o build/src/core/genthread.o,$(OBJ))
build/rehash-waits-unit: tests/rehash_waits_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

build/core-concurrency-unit: tests/core_concurrency_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -O1 -fsanitize=address,undefined -fno-omit-frame-pointer \
	  -DTOMO_CORE_CONCURRENCY_TEST -I. $< $(CORE_TEST_OBJ) -o $@ \
	  $(JELIBS) $(LDLIBS) -lm

# Directed owner-phase tests. The test includes xshard.cc to drive the real private phases
# without starting worker threads or opening a listener; all other code is the release objects.
build/atomic-survivors-unit: tests/atomic_survivors_unit.cc src/cmd/xshard.cc $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. tests/atomic_survivors_unit.cc \
	  $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm

# Load drivers: not part of `all`, kept compiling here so they cannot rot unnoticed.
build/benchtxn: tools/benchtxn.cc Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tools/benchtxn.cc -o $@
build/broaden-bench: tests/broaden_bench.cc Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/broaden_bench.cc -o $@
tools: build/benchtxn build/broaden-bench

clean:
	rm -rf build
.PHONY: all asan tsan noreserve clean unit tools

# Deterministic networking/command regressions. These TUs include the real private implementations;
# omit their production objects from this serverless binary. No server threads or gate are started.
NETCMD_TEST_SRC := tests/netcmd_unit.cc tests/netcmd_stream_unit.cc tests/netcmd_zset_unit.cc tests/netcmd_config_unit.cc
NETCMD_TEST_OBJ := $(NETCMD_TEST_SRC:tests/%.cc=build/tests/%.o)
NETCMD_LIB_OBJ := $(filter-out build/src/main.o build/src/cmd/xshard.o build/src/cmd/t_stream_groups.o build/src/cmd/t_zset.o build/src/cmd/server_tail.o,$(OBJ))
build/tests/%.o: tests/%.cc tests/netcmd_unit.h $(wildcard src/*/*.h) $(wildcard src/*/*.cc) $(wildcard src/*/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Wno-mismatched-new-delete -I. -c $< -o $@
build/netcmd-unit: $(NETCMD_TEST_OBJ) $(NETCMD_LIB_OBJ)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=mkstemp -Wl,--wrap=fopen
Reading additional input from stdin...
OpenAI Codex v0.153.4
--------
workdir: /home/user/Projects/cx-deadconf-fix
model: gpt-6-astra
provider: openai
approval: never
sandbox: danger-full-access
reasoning effort: max
reasoning summaries: none
session id: 01a098f6-bd7d-73d1-a8fa-a9bb9f89a830
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

--- TASK ---

You are fixing configuration defects confirmed by a code audit. You CODE; the maintainer tests, gates
and merges. Build and unit-test on cores 112-127 only. Never `pkill -f`/`pgrep -f`. COMMIT AS YOU
GO on your branch (git add -A ':!CODEX-OUT.md' && git commit) -- small commits, one per item below.

Read /home/user/Projects/AUDIT-deadconf-verdict.md first: every item there is CONFIRMED against the
code with file:line evidence. Do not re-audit; fix.

ITEMS, each its own commit, each with a TEST THAT FAILS ON THE OLD CODE:
 1. FIVE uint32_t TRUNCATIONS -- latency-monitor-threshold, stream-node-max-entries,
    stream-node-max-bytes, --script-crossshard-cut-slots, --script-crossshard-conflict-retries.
    Today 4294967296 is accepted, echoed back, and consumed as 0 (feature silently off). Do what
    Redis does: reject an out-of-range value at parse with an error (CONFIG SET returns
    "ERR ... argument must be between ..."; a boot flag refuses to boot). Match Redis's exact
    bounds and message grammar for the three Redis-named knobs. Reproducer per knob: set
    4294967296, expect an error, not a silent zero.
 2. ZERO-COPY (N1+N7, ONE commit): tomokv.conf says zc 0 "disables entirely" but 0 is not mapped;
    map 0 -> UINT32_MAX at both install sites. AND the two consumers disagree by one: GET borrows
    at value.n >= zc_min (t_string.cc:400,412), MGET gather at > (scatter_engine.inc:2943). Align
    the gather to >=. Test: a value of exactly the cutover is treated identically by GET and MGET.
 3. TRACKING-TABLE EVICTION (N8): tracking.cc:138 evicts unordered_map::begin() -- deterministic
    and biased -- while its own comment and tomokv.conf claim a RANDOM victim. Make it random
    (sample; a full table must not re-evict the same subset forever). Standalone commit.
 4. DOC-ONLY (N10-N12, one commit touching only tomokv.conf): aof rewrite fires at ">" not "at
    least"; kRobWindow lives in net/rob.h not net/conn.h; tracking-table-max-keys is boot-only and
    per-IO-owner, so drop the bare "redis semantics" phrase.
 5. THE 3 INHERITED CONTRADICTIONS: ACL selectors (conf says rejected, acl.inc:329-383 stores
    them) -- REJECT them at parse until enforcement exists, do not silently store; connection
    "for life" claim vs climon.cc:292-294 tracking extraction on move -- fix the CONF, the code is
    right (connections move under client-lb); list-max-compact-entries caps lists (conf says no
    cap) -- fix the conf to describe the cap.
DO NOT touch N9 (RESP3 pub/sub exemption): it needs an owner decision first.
DO NOT touch the SORT globless-BY item: unverified.
Knob rules: numeric, 0 = off allocates nothing, -1 = auto; Redis-named knobs match Redis exactly.
Write MEASURE-REQUEST only if a change could plausibly move performance (item 2 can: say which
cells). Report: a table [item | files | test that fails on old code | commit].

N9 DECIDED BY THE OWNER: MATCH REDIS. Exempt only RESP2 subscribers from the client-eviction budget,
as Redis does (Redis sets CLIENT_PUBSUB for RESP2 only). io_loop.h:6063 exempts on
!c->subscriber_mode() with no RESP test, and pubsub.inc:737 sets that flag regardless of protocol.
Add the RESP2 test; a RESP3 subscriber is no longer exempt. Test: a RESP3 SUBSCRIBE client is
counted against the budget; a RESP2 one is not. Own commit. Update tomokv.conf:52 to say RESP2.

CONTINUATION-N9 (mainline 12:12): your six commits are received and will be gated. ONE item remains,
decided by the owner after you finished: N9 -- MATCH REDIS. Exempt only RESP2 subscribers from the
client-eviction budget (io_loop.h:6063 has no RESP test; pubsub.inc:737 sets subscriber_mode
regardless of protocol). Add the RESP2 test; update tomokv.conf:52 to say RESP2. Test: a RESP3
SUBSCRIBE client counts against the budget, a RESP2 one does not; the test must FAIL on the old
code. One commit. Nothing else. Compile on 112-127. Commit and stop.
codex
I’ll make only the N9 change, add a regression test that fails on the old code, then build and unit-test on cores 112–127. I’ll commit it without running a server, benchmark, or gate.

exec
/bin/bash -lc 'cat /home/user/Projects/AUDIT-deadconf-verdict.md' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
# deadconf audit — Opus agent verdict 2026-09-13 (mainline record; not in git)
Agent scope: config.h / tomokv.conf / main.cc and their consumers. Read-only.

## The 8 inherited claims (from the content-filtered rep-deadconf lane)
5 uint32_t truncations (4294967296 accepted, echoed, consumed as 0 = feature silently OFF):
  latency-monitor-threshold, stream-node-max-entries, stream-node-max-bytes,
  --script-crossshard-cut-slots, --script-crossshard-conflict-retries      -> CONFIRMED
3 conf/code contradictions: ACL selectors parsed+stored (conf says rejected); tracking state
  extracted on IO move (conf says "for life"); list-max-compact-entries caps (conf says no cap) -> CONFIRMED
## New findings from the sweep (7 verified by the agent, 1 unverified)
N1/N7 zero-copy: conf:163 "0 disables" is false (0 is not mapped); AND the two consumers of the same
     knob disagree by one: GET borrows at >= zc_min, MGET gather at > (scatter_engine.inc:2943).
     One commit: map 0 -> UINT32_MAX at both install sites AND align the gather to >=.
N8   tracking-table eviction: conf + code comment say "random victim"; tracking.cc:138 evicts
     unordered_map::begin() -- deterministic, biased. REAL CODE DEFECT, small, standalone commit.
N9   RESP3 subscribers are exempted like RESP2 (io_loop.h:6063 has no RESP test); Redis exempts
     RESP2 only. Needs a DECISION, then code or conf.
N10-N12 doc-only (aof rewrite ">" vs "at least"; kRobWindow pointer wrong file; tracking-table
     claims redis semantics but is boot-only per-owner). One tomokv.conf commit.
N?   SORT globless BY with STORE (t_sort.cc:89-93) -- UNVERIFIED, command semantics, spot-check.
~60 other conf claims checked and CORRECT.

## Disposition (mainline)
* Coding lane "deadconf-fix" (codex): the 5 truncations -> reject out-of-range at parse like Redis
  does (CONFIG SET returns an error); N1+N7 as one commit; N8 as one commit; N10-N12 as one conf
  commit. Every fix ships with a test that FAILS on the old code (the 4294967296 -> 0 case is a
  one-line reproducer each).
* Decision for the owner: N9 (RESP3 pub/sub exemption) -- match Redis (RESP2 only) or keep ours?
* Confirm-or-refute of the fix = mainline (me), via the gate + the reproducers.

exec
/bin/bash -lc "pwd && rg --files -g AGENTS.md -g '"'!build*'"' -g '"'!vendor'"' -g '"'!third_party'"' /home/user/Projects 2>/dev/null" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
/home/user/Projects/cx-deadconf-fix
/home/user/Projects/valkey/AGENTS.md
/home/user/Projects/dragonfly/helio/AGENTS.md
/home/user/Projects/dragonfly/AGENTS.md

exec
/bin/bash -lc 'git status --short && git branch --show-current && git log -9 --oneline' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
?? CODEX-OUT.round1.md
cx-deadconf-fix-items
528cb0b15 reject ACL selectors and correct ownership and list-limit comments
f1b61114a correct AOF, ROB and tracking configuration comments
9ab54c4e1 sample tracking eviction victims across buckets and collisions
36f7c17dc honor zero-copy off and inclusive GET/MGET cutovers
8c73d5d46 reject overflowing uint32 configuration limits
831b5499e preserve measurement metadata from worktree recovery
a363c2c5e gate: the ABBA row honours an explicit plan budget, overriding only a history-derived one
b9ed48b29 gate: the ABBA row never takes a history-derived timeout
0adfaac27 gate: correctness gates merges; ABBA reports every version and does not decide

exec
/bin/bash -lc 'for p in /AGENTS.md /home/AGENTS.md /home/user/AGENTS.md /home/user/Projects/AGENTS.md /home/user/Projects/cx-deadconf-fix/AGENTS.md; do if [ -f "$p" ]; then cat "$p"; fi; done' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
exec
/bin/bash -lc "rg -n 'subscriber_mode\\(|maxmemory.clients|client.eviction|client.evict|evict.*client' src tests CMakeLists.txt tomokv.conf && rg --files -g '*test*' -g '*CMake*' -g '*Makefile*' -g 'AGENTS.md' -g '"'!build*'"' -g '"'!third_party'"' -g '"'!vendor'"'" in /home/user/Projects/cx-deadconf-fix
 exited 2 in 0ms:
rg: CMakeLists.txt: No such file or directory (os error 2)
tomokv.conf:197:# random entry is evicted AND its owner is sent an invalidation for that key, so a client can
src/core/io_loop.h:3474:                            } else if (c->blocked() || c->subscriber_mode()) {
src/core/io_loop.h:3675:            const bool subscriber_mode = __builtin_expect(c->subscriber_mode(), false);
src/core/io_loop.h:6008:        const ClientBufferLimit& limit = c->subscriber_mode() ? limits.pubsub : limits.normal;
src/core/io_loop.h:6063:            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
src/core/pubsub.inc:706:        if (local.client) local.client->set_subscriber_mode(false);
src/core/pubsub.inc:737:                client->set_subscriber_mode(pubsub_total_subscription_count(local) != 0);
tests/cmdmeta.py:16:client|help client|id client|info client|kill client|list client|no-evict client|no-touch
tests/differ.py:5072:client|help client|id client|info client|kill client|list client|no-evict client|no-touch
src/cmd/tracking.cc:263:    if (!resp3_push && (!redirected || !target->subscriber_mode())) return;
src/net/conn.h:635:    bool subscriber_mode() const { return subscriber_mode_; }
src/net/conn.h:636:    void set_subscriber_mode(bool v) { subscriber_mode_ = v; }
src/cmd/command.h:356:void command_client_set_no_evict(Client* client, bool enabled);
src/cmd/t_server.cc:221:    if (client.subscriber_mode()) *flag++ = 'P';
src/cmd/t_server.cc:1264:        // maxmemory-clients output-buffer eviction. TomoKV has neither maxmemory-clients nor a
src/cmd/t_server.cc:1267:        command_client_set_no_evict(g_client, eq_icase(op.arg(2), "ON"));
src/cmd/t_server.cc:3219:        const bool pubsub = client.subscriber_mode();
src/cmd/t_server.cc:3253:void command_client_set_no_evict(Client* client, bool enabled) {

exec
/bin/bash -lc "git worktree list && rg --files -g '*MEASURE*' -g 'CODEX*' -g 'CMakeCache.txt' -g 'CTestTestfile.cmake' -g 'build.ninja' -g 'Makefile' -g '"'!third_party'"' -g '"'!vendor'"' -g '"'!deps'"' -g '"'!bench*'"' && ls -ld build*" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
/home/user/Projects/tomokv-cpp                                  a363c2c5e [cpp]
/home/user/Projects/cx-cache-L1                                 69ddf87a1 [cx-cache-L1]
/home/user/Projects/cx-cache-L1/build/cache-L1/candidate02-src  8263c67c8 [cx-cache-L1-c2]
/home/user/Projects/cx-cache-L2                                 695b3c8c3 [cx-cache-L2]
/home/user/Projects/cx-cache-L3                                 9d5684bd3 [cx-cache-L3]
/home/user/Projects/cx-cache-L4                                 2248c38bf [cx-cache-L4]
/home/user/Projects/cx-cache-L5                                 97bbe689f [cx-cache-L5]
/home/user/Projects/cx-deadconf-fix                             528cb0b15 [cx-deadconf-fix-items]
/home/user/Projects/cx-delvar                                   5f64b1734 [cx-delvar]
/home/user/Projects/cx-final                                    3adaaae06 [cx-final]
/home/user/Projects/cx-gaterigor-integration                    25cf9ffd3 [cx-gaterigor-integration]
/home/user/Projects/cx-nowaitb                                  a055beb85 [cx-nowaitb]
/home/user/Projects/cx-overlap-O1                               b3c1fba75 [cx-overlap-O1]
/home/user/Projects/cx-overlap-O10                              586eb7ae6 [cx-overlap-O10]
/home/user/Projects/cx-overlap-O11                              e2fc6873e [cx-overlap-O11]
/home/user/Projects/cx-overlap-O2                               ec20893f7 [cx-overlap-O2]
/home/user/Projects/cx-overlap-O5                               783fbecb5 [cx-overlap-O5]
/home/user/Projects/cx-overlap-O6                               3682294fb [cx-overlap-O6]
/home/user/Projects/cx-overlap-O7                               30418dbb1 [cx-overlap-O7]
/home/user/Projects/cx-overlap-O8                               3c75ed673 [cx-overlap-O8]
/home/user/Projects/cx-overlap-O9                               95ea5941f [cx-overlap-O9]
/home/user/Projects/cx-readlocal-obs                            5c943ace9 [cx-readlocal-obs]
/home/user/Projects/cx-redisgap                                 0939cecc5 [cx-redisgap]
/home/user/Projects/cx-reorder-R1                               d97779ecb [cx-reorder-R1]
/home/user/Projects/cx-reorder-R2                               9bf786455 [cx-reorder-R2]
/home/user/Projects/cx-reorder-R4                               81d4d1cb6 [cx-reorder-R4]
/home/user/Projects/cx-reorder-R5                               1809ef4e2 [cx-reorder-R5]
/home/user/Projects/cx-reorder-R6                               30d8d90cb [cx-reorder-R6]
/home/user/Projects/cx-reorder-R7                               c862246cd [cx-reorder-R7]
/home/user/Projects/cx-reorder-R8                               a363c2c5e [cx-reorder-R8]
/home/user/Projects/tomokv-cpp-perthread                        e821f56f2 [t-merge14-recovered]
/home/user/Projects/tomokv-cpp-stable                           c7618cda0 [stable-recovered]
CODEX-OUT.round1.md
CODEX-OUT.md
Makefile
MEASURE-REQUEST
drwxrwxr-x 7 user user 4096 Sep 13 11:56 build

build/
*.o
compile_commands.json
servertail-testdata/

# compiled test/bench drivers (sources are tracked, binaries are not)
tools/benchtxn

# stray comparison-run snapshot artifacts (dragonfly writes these into cwd)
dump-*.dfs
dump-*.rdb
dump-*.tomo
dump.tomo

# python bytecode from the in-tree test helpers (tests/aof_frame_order.py imports aof_frames)
__pycache__/

# agent lane artifacts -- never commit these
codex*.log
BRIEF*.md
LANE_RULES.md
# The interactive agent transcript changes during validation and is not project source.
/CODEX-OUT.md

# replycode lane: measurement drivers are tracked as sources, their binaries are not
scratchpad/replycode/replay
scratchpad/replycode/layout
scratchpad/replycode/*.so

# Exact gate timing and seed history survive make clean.
.gate-history/

exec
/bin/bash -lc "sed -n '5960,6110p' src/core/io_loop.h && sed -n '660,760p' src/core/pubsub.inc && sed -n '20,70p' tomokv.conf && sed -n '580,690p' src/net/conn.h" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
                    ::clock_gettime(CLOCK_REALTIME, &wall);
                    slowlog_record(self_->id(), client->id(), op,
                                   now_ns() - timer.slow_started_ns,
                                   static_cast<int64_t>(wall.tv_sec) * 1000 +
                                       wall.tv_nsec / 1000000,
                                   timer.slowlog_arm, true);
                }
            }
            op.state.store(OpState::Done, std::memory_order_release);
            client->set_blocked(false);
            client->set_last_interaction_s(cached_now_s_);
            srv_->blocking_client_unparked();
            deferred_timers_[i] = deferred_timers_.back();
            deferred_timers_.pop_back();
            enqueue_serve(client);
            mark_active(client);
            completed++;
        }
        return completed;
    }

    bool deferred_timer_cancel(Client* client) {
        bool cancelled = false;
        for (size_t i = 0; i < deferred_timers_.size();) {
            const DeferredTimer timer = deferred_timers_[i];
            if (timer.client != client) {
                i++;
                continue;
            }
            Op& op = client->rob().at(timer.op_id);
            op.state.store(OpState::Done, std::memory_order_release);
            srv_->blocking_client_unparked();
            deferred_timers_[i] = deferred_timers_.back();
            deferred_timers_.pop_back();
            cancelled = true;
        }
        if (cancelled) client->set_blocked(false);
        return cancelled;
    }

    bool client_obuf_check(Client* c, bool async) {
        if (c->closing() || c->dead()) return false;
        if (!srv_->client_obuf_armed()) {
            c->stop_obuf_tracking();
            return false;
        }
        c->start_obuf_tracking();
        const ClientLimitsConfigSnapshot limits = srv_->client_limits_snapshot(self_->id());
        const ClientBufferLimit& limit = c->subscriber_mode() ? limits.pubsub : limits.normal;
        if (!limit.hard_bytes && !limit.soft_bytes) {
            c->set_obuf_soft_since_s(0);
            return false;
        }
        uint64_t used = c->obuf_bytes() + wb_.deferred_output_bytes(*c);
        const auto pending = pubsub_pending_.find(c->id());
        if (pending != pubsub_pending_.end()) used += pending->second.deferred.size();
        bool over = limit.hard_bytes && used >= limit.hard_bytes;
        if (!over && limit.soft_bytes && used >= limit.soft_bytes) {
            if (!c->obuf_soft_since_s()) c->set_obuf_soft_since_s(cached_now_s_);
            else if (cached_now_s_ - c->obuf_soft_since_s() > limit.soft_seconds) over = true;
        } else if (!over) {
            c->set_obuf_soft_since_s(0);
        }
        if (!over) return false;

        srv_->note_client_output_buffer_limit_disconnect();
        if (async)
            std::fprintf(stderr,
                "Client id=%llu scheduled to be closed ASAP for overcoming of output buffer limits.\n",
                static_cast<unsigned long long>(c->id()));
        else
            std::fprintf(stderr,
                "Client id=%llu closed for overcoming of output buffer limits.\n",
                static_cast<unsigned long long>(c->id()));
        close_client(c);
        // Unified W1 has already retired/staged this client but must not let W2 submit the bytes
        // which crossed the hard limit. Its batch already has a nullable-client guard, so encode
        // this rare refusal there and keep the ordinary prepare path free of a parallel bool.
        // close_client runs first while the active context still fences the Client lifetime.
        if (active_wb_context_)
            for (uint32_t i = 0; i < active_wb_context_->count; i++)
                if (active_wb_context_->clients[i] == c) {
                    active_wb_context_->clients[i] = nullptr;
                    break;
                }
        return true;
    }

    uint32_t client_cron_pass() {
        auto& clients = self_->clients();
        const size_t initial = clients.size();
        if (!initial) { client_cron_cursor_ = 0; return 0; }
        size_t visits = initial / kClientCronBeatsPerSecond;
        if (visits < kClientCronMinVisits)
            visits = std::min(initial, static_cast<size_t>(kClientCronMinVisits));

        const uint32_t timeout = srv_->timeout();
        uint32_t work = 0;
        for (size_t visited = 0; visited < visits && !clients.empty(); visited++) {
            if (client_cron_cursor_ >= clients.size()) client_cron_cursor_ = 0;
            Client* c = clients[client_cron_cursor_];
            const size_t before = clients.size();
            bool closed = false;
            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
                cached_now_s_ - c->last_interaction_s() > timeout) {
                close_client(c);
                closed = true;
            } else if (client_obuf_check(c, false)) {
                closed = true;
            }
            work++;
            // close_client removes by swap-with-back. Revisit this index so the swapped-in client
            // is not skipped; if teardown is still pending, advance past the unchanged entry.
            if (!closed || clients.size() == before) client_cron_cursor_++;
        }
        return work;
    }

    uint32_t lb_client_signal_pass() {
        lb_client_observations_.clear();
        if (lb_client_observations_.capacity() < self_->clients().size())
            lb_client_observations_.reserve(self_->clients().size());
        for (Client* client : self_->clients()) {
            if (client->dead()) continue;
            lb_client_observations_.push_back({client->id(), client->rob().dispatch_id(),
                                               client->rob().in_flight()});
        }
        srv_->lb_publish_client_observations(self_->id(), lb_client_observations_);
        return static_cast<uint32_t>(lb_client_observations_.size());
    }

    void refresh_notify_config() {
        LiveConfigSnapshot snapshot;
        if (!srv_->live_config_snapshot_if_changed(
                self_->id(), notify_config_version_, snapshot)) return;
        notify_config_armed_ = snapshot.notify_events != 0;
        save_config_armed_ = snapshot.save_armed;
        notify_armed_ = notify_config_armed_ || save_config_armed_ ||
                        climon_armed_cached_ != 0;
        proto_max_bulk_len_ = snapshot.proto_max_bulk_len;
        // Connection-local commands never reach an executor, so the IO thread owns their timing.
        // Same snapshot, same pass, no extra load.
        slowlog_arm_.slowlog_us = snapshot.slowlog_log_slower_than;
        slowlog_arm_.latency_ms = snapshot.latency_monitor_threshold;
        slowlog_armed_ = slowlog_arm_.armed();
        if (srv_->read_local_enabled()) {
            fused_executor_->set_read_local_point_writes_precise(
                snapshot.maxmemory == 0 || snapshot.policy == MaxmemoryPolicy::NoEviction);
            fused_executor_->set_read_local_keymiss_notify(
                (snapshot.notify_events & NOTIFY_KEY_MISS) != 0);
        }

    static uint64_t pubsub_subscription_count(const PubSubLocalConn& local) {
        return local.channels.size() + local.patterns.size();
    }

    static uint64_t pubsub_shard_subscription_count(const PubSubLocalConn& local) {
        return local.shard_channels.size();
    }

    static uint64_t pubsub_total_subscription_count(const PubSubLocalConn& local) {
        return pubsub_subscription_count(local) + pubsub_shard_subscription_count(local);
    }

    void pubsub_append_ack(Op::Sink& sink, bool pattern, bool shard, bool subscribe,
                           const std::string* value, uint64_t count, bool resp3) {
        const char* label = nullptr;
        uint32_t label_len = 0;
        if (shard) {
            label = subscribe ? "ssubscribe" : "sunsubscribe";
            label_len = subscribe ? 10 : 12;
        } else if (pattern) {
            label = subscribe ? "psubscribe" : "punsubscribe";
            label_len = subscribe ? 10 : 12;
        } else {
            label = subscribe ? "subscribe" : "unsubscribe";
            label_len = subscribe ? 9 : 11;
        }
        if (resp3) reply_push_header(sink, 3);
        else reply_array_header(sink, 3);
        reply_bulk(sink, Slice(label, label_len));
        if (value) reply_bulk(sink, Slice(value->data(), value->size()));
        else reply_null(sink, resp3);
        reply_int(sink, static_cast<long long>(count));
    }

    void pubsub_clear_local_subscriptions(PubSubLocalConn& local) {
        for (size_t i = 0; i < local.channels.size(); i++)
            srv_->pubsub_subscription_removed(false);
        for (size_t i = 0; i < local.patterns.size(); i++)
            srv_->pubsub_subscription_removed(true);
        for (size_t i = 0; i < local.shard_channels.size(); i++)
            srv_->pubsub_subscription_removed(false, true);
        local.channels.clear();
        local.patterns.clear();
        local.shard_channels.clear();
        if (local.client) command_client_set_subscriptions(local.client, 0, 0, 0);
        if (local.client) local.client->set_subscriber_mode(false);
    }

    void pubsub_finish_pending(uint64_t conn_id) {
        auto pending_it = pubsub_pending_.find(conn_id);
        auto local_it = pubsub_local_.find(conn_id);
        if (pending_it == pubsub_pending_.end() || local_it == pubsub_local_.end()) return;
        PubSubPending& pending = pending_it->second;
        PubSubLocalConn& local = local_it->second;
        Client* client = local.client;
        Op& op = client->rob().at(pending.op_id);
        auto sink = op.sink();

        // Publications are independent frames. Suppression may discard only the command reply.
        if (op.reply_skip() && !pending.deferred.empty()) {
            wb_.defer_oob(*client, pending.deferred.data(), pending.deferred.size());
            pending.deferred.clear();
        }
        switch (pending.kind) {
            case PubSubPendingKind::Modify:
                if (!pending.subscribe && !pending.deferred.empty())
                    sink.append(pending.deferred.data(), pending.deferred.size());
                for (const std::string& item : pending.items) {
                    pubsub_account_local_change(
                        local, pending.pattern, pending.shard, pending.subscribe, item);
                    pubsub_append_ack(sink, pending.pattern, pending.shard, pending.subscribe, &item,
                        pending.shard ? pubsub_shard_subscription_count(local)
                                      : pubsub_subscription_count(local), op.resp3());
                }
                if (pending.subscribe && !pending.deferred.empty())
                    sink.append(pending.deferred.data(), pending.deferred.size());
                client->set_subscriber_mode(pubsub_total_subscription_count(local) != 0);
                break;
            case PubSubPendingKind::Publish:
                reply_int(sink, static_cast<long long>(pending.count));
                break;
            case PubSubPendingKind::Channels:
                std::sort(pending.channels.begin(), pending.channels.end());
                pending.channels.erase(
                    std::unique(pending.channels.begin(), pending.channels.end()),
                    pending.channels.end());
                reply_array_header(sink, pending.channels.size());
                for (const std::string& channel : pending.channels)
                    reply_bulk(sink, Slice(channel.data(), channel.size()));
                break;
            case PubSubPendingKind::Numsub:
                reply_array_header(sink, pending.items.size() * 2);
                for (size_t i = 0; i < pending.items.size(); i++) {
                    reply_bulk(sink, Slice(pending.items[i].data(), pending.items[i].size()));
                    reply_int(sink, static_cast<long long>(pending.counts[i]));
                }
                break;
            case PubSubPendingKind::Numpat:
                reply_int(sink, static_cast<long long>(pending.count));
                break;
# Independent TLS listener; tls-port 0 disables TLS and allocates no TLS state. Plain `port` and
# `tls-port` may coexist; `port 0` + a non-zero tls-port makes the service TLS-only. TLS requires a
# PEM certificate chain and private key. Client authentication defaults to yes (a trusted client
# certificate is mandatory); optional requests and verifies a certificate when supplied; no does
# not request one. A CA file or c_rehash-prepared CA directory is required for yes/optional.
# tls-port 0
# tls-cert-file /etc/tomokv/server.crt
# tls-key-file /etc/tomokv/server.key
# tls-ca-cert-file /etc/tomokv/ca.crt
# tls-ca-cert-dir /etc/tomokv/ca
# tls-auth-clients yes

# Space-separated, case-insensitive protocol names: TLSv1 TLSv1.1 TLSv1.2 TLSv1.3. Empty selects
# TLSv1.2 + TLSv1.3. tls-ciphers controls TLS <=1.2; tls-ciphersuites controls TLS 1.3. The
# defaults below are the AES-128-GCM-first lists src/net/tls.cc installs when the knob is empty
# (kernel/AES-NI-fast, kTLS-eligible); an explicit value replaces the default list exactly.
# tls-protocols "TLSv1.2 TLSv1.3"
# tls-ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256
# tls-ciphersuites TLS_AES_128_GCM_SHA256
# tls-prefer-server-ciphers no

# Also listen on a unix domain socket (unset = off).
# unixsocket /tmp/tomokv.sock

###################### CONNECTION LIMITS ###################

# Maximum accepted clients [live], default 10000. Admission is checked before Client allocation.
# With independent SO_REUSEPORT acceptors, a simultaneous burst may overshoot by at most the
# number of IO threads; this is a safety valve rather than an exact reservation boundary.
# maxclients 10000

# Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
# Blocked and RESP2 pub/sub clients are exempt; an idle MULTI transaction is not exempt.
# timeout 0

# TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive
# setsockopt calls. Linux KEEPINTVL is interval/3 (minimum 1) and KEEPCNT is 3.
# tcp-keepalive 300

# listen(2) backlog for TCP and unix sockets [boot-only]. Linux may cap it at somaxconn; boot logs
# Redis's advisory warning when that happens.
# tcp-backlog 511

# Network event engine for the io threads [boot-only].
#   uring  the native path and the default. One io_uring per io thread with SINGLE_ISSUER +
#          DEFER_TASKRUN; accept/recv/send are submitted and complete asynchronously.
#   epoll  a portable alternative for kernels and environments where io_uring is unavailable or
#          unwanted. The io thread waits in epoll_wait and issues recv/send/accept itself. The
#          2-stage split, routing, shard ownership and the reply path are identical; only the
#          waiting and completion change.
# Selecting epoll changes two other things, and the boot log says so:
    // Torn down but not yet freed: still legal to READ while outstanding CQEs retire (it sits on
    // the io thread's deferred-free list), but no longer part of any working set.
    bool dead() const { return dead_; }
    void mark_dead() { dead_ = true; }
    bool closing() const { return closing_; }
    void mark_closing() { closing_ = true; }

    // Membership in its io thread's active set, as a FLAG rather than a search; and whether this
    // conn's ready bit fired since io last served it. Plain bools — one thread.
    bool serve_pending() const { return serve_pending_; }
    void set_serve_pending(bool v) { serve_pending_ = v; }
    // An in-flight all-shards scatter (FLUSHALL/FLUSHDB/CONFIG SET fan-out) is a parse barrier:
    // commands behind it on this conn must observe post-scatter state (ConnLocal readers like
    // DBSIZE/INFO execute at parse time, so without the barrier they snapshot early and a
    // pipelined FLUSHALL;DBSIZE answers the PRE-flush count). Set only on successful publish;
    // cleared at ROB quiescence — the scatter is necessarily the newest op, since nothing parses
    // behind it. Same-client read-your-own-writes hazard: a sanctioned stall.
    //
    // The gate the parse loop asks is unchanged and stays one byte test against zero: the owner
    // set is a MASK in the byte the bool already occupied (see BarrierOwner), not a new field.
    bool scatter_barrier() const { return barrier_owners_ != 0; }
    bool barrier_held_by(BarrierOwner who) const {
        return (barrier_owners_ & static_cast<uint8_t>(who)) != 0;
    }
    void barrier_acquire(BarrierOwner who) {
        barrier_owners_ = static_cast<uint8_t>(barrier_owners_ | static_cast<uint8_t>(who));
    }
    // Drops one owner's claim. Returns TRUE when this release was the last one — i.e. when the
    // connection is actually released. A false return is the event the old unconditional clear got
    // wrong; its callers count it, which is what makes a validation run able to fail.
    bool barrier_release(BarrierOwner who) {
        barrier_owners_ = static_cast<uint8_t>(barrier_owners_ & ~static_cast<uint8_t>(who));
        return barrier_owners_ == 0;
    }
    // The backstop, at ROB quiescence: with nothing in flight every PRODUCTION owner has completed
    // by definition, so quiescence releases them all in one store. Only the injected test owner is
    // exempt, and only because holding past quiescence is the whole point of it.
    void barrier_release_quiesced() {
        barrier_owners_ =
            static_cast<uint8_t>(barrier_owners_ & static_cast<uint8_t>(BarrierOwner::Debug));
    }
    // Parse backpressure is deliberately distinct from the semantic scatter barrier. Each owner
    // parks this connection's unconsumed head frame without publishing a ROB slot, and clears only
    // its own reason. The byte is a mask because atomic admission and FLIP can overlap.
    bool parse_backpressure() const { return parse_backpressure_ != 0; }
    bool atomic_backpressure() const { return parse_backpressure_ & kAtomicBackpressure; }
    void set_atomic_backpressure(bool v) {
        if (v) parse_backpressure_ |= kAtomicBackpressure;
        else parse_backpressure_ &= static_cast<uint8_t>(~kAtomicBackpressure);
    }
    bool flip_backpressure() const { return parse_backpressure_ & kFlipBackpressure; }
    void set_flip_backpressure(bool v) {
        if (v) parse_backpressure_ |= kFlipBackpressure;
        else parse_backpressure_ &= static_cast<uint8_t>(~kFlipBackpressure);
    }
    bool subscriber_mode() const { return subscriber_mode_; }
    void set_subscriber_mode(bool v) { subscriber_mode_ = v; }
    bool blocked() const { return connection_flags_ & kBlocked; }
    void set_blocked(bool value) {
        if (value) connection_flags_ |= kBlocked;
        else connection_flags_ &= static_cast<uint8_t>(~kBlocked);
    }
    bool resp3() const { return connection_flags_ & kResp3; }
    void set_resp3(bool value) {
        if (value) connection_flags_ |= kResp3;
        else connection_flags_ &= static_cast<uint8_t>(~kResp3);
    }
    // CLIENT NO-TOUCH. Bit 4 was free in this byte AND is ignored by Op::route_flags_, so the
    // connection's answer reaches every operation through the store op_route_flags() already
    // makes -- no new field, no new load, no growth of the footprint-locked Client.
    bool no_touch() const { return connection_flags_ & kNoTouch; }
    void set_no_touch(bool value) {
        if (value) connection_flags_ |= kNoTouch;
        else connection_flags_ &= static_cast<uint8_t>(~kNoTouch);
    }
    // Bit 2 deliberately matches Op::route_flags_'s Resp3 assignment. Passing the byte through
    // Op::reset folds protocol capture into the ROB's existing flags store: RESP2 pays one load,
    // no mask and no branch. The armed coarse parser masks kBlocked before reusing its bit for a
    // hash-precise write stamp; ordinary acquisitions continue to ignore that high bit.
    uint8_t op_route_flags() const { return connection_flags_; }
    static constexpr size_t connection_flags_offset();
    // The owning IO thread captures this into each Op before dispatch. Executors never read Client
    // atomic bookkeeping: doing so pulled this tail cache line across cores for every shard task
    // and regressed the pure-MGET cell even when no atomic group existed.
    bool has_atomic_group_io() const { return atomic_groups_io_ != 0; }
    void atomic_group_started() { ++atomic_groups_io_; }
    void atomic_group_finished() {
        if (!atomic_groups_io_) std::abort();
        --atomic_groups_io_;
    }
    bool in_active() const { return in_active_; }
    void set_in_active(bool v) { in_active_ = v; }
    // IOFUSED IFID readiness is owner-local and shares the connection flag byte instead of
    // growing the footprint-locked hot scalar run. Ordinary Op consumers ignore bit 6; the
    // overlap-0 read-local parser masks it before reusing that bit for a classified slot.
    bool ifid_pending() const { return connection_flags_ & kIfidPending; }
    void set_ifid_pending(bool value) {
        if (value) connection_flags_ |= kIfidPending;
        else connection_flags_ &= static_cast<uint8_t>(~kIfidPending);
    }

    // MULTI/WATCH state is cold and allocated only on first use.  These fields consume padding in
    // the executor-facing tail; the signed 1984-byte Client footprint remains unchanged.
    MultiSession* multi_session() const { return multi_session_; }
    void set_multi_session(MultiSession* state) { multi_session_ = state; }
    uint64_t watch_generation() const {
        return watch_generation_.load(std::memory_order_acquire);
    }
    uint64_t next_watch_generation() {
        return watch_generation_.fetch_add(1, std::memory_order_acq_rel) + 1;
    }

exec
/bin/bash -lc "rg -n 'timeout|subscriber|SUBSCRIBE|maintenance|sweep|evict' tests/*unit* tests/*test* tests/gate.sh && ls build && rg -n 'test|unit|deadconf' Makefile" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
tests/gate.sh:158:ROW_PLAN="$RUN_DIR/row-timeouts.json"
tests/gate.sh:207:# 313 -> 321 quick, 326 -> 334 full: eviction accounting rows. tests/evict_battery.py had no gate
tests/gate.sh:209:# the LFU/LRU metadata (hot keys were evicted FIRST). lfu and the new lruclock section, each on its
tests/gate.sh:211:# Merged: 245 base + 1 lane-admission row + 76 fused+armed and eviction rows = 322 quick;
tests/gate.sh:228:# 258 -> 260 full: reply codes make a blocking timeout's "*-1"/"_" a CODE rather than bytes, so the
tests/gate.sh:265:# unreached through the existing completion/count checks. No timeout becomes a skip.
tests/gate.sh:379:    # A published timeout owns its five-second kill escalation. Let it finish so a
tests/gate.sh:415:  # An EXPLICIT plan entry (basis != own-row-history) is honoured -- that is how the timeout
tests/gate.sh:421:  ROW_MARKER="$TMPDIR/row-timeout-$BASHPID.json"
tests/gate.sh:425:  trap row_timeout USR1
tests/gate.sh:429:row_timeout(){
tests/gate.sh:499:  # timeouts. A previous failure is evidence to investigate, never an anecdote
tests/gate.sh:720:    if ! timeout --kill-after=1 30 tail --sleep-interval=.1 --pid="$SRV" -f /dev/null; then
tests/gate.sh:812:    evict-*) local kind section mode atomic
tests/gate.sh:815:      echo "eviction $section battery ($mode, atomic $atomic)";;
tests/gate.sh:843:    evict-*)
tests/gate.sh:847:        boot "$CANDIDATE_BINARY" --atomic "$atomic" || bad "eviction $section boot (split, atomic $atomic)"
tests/gate.sh:850:            || bad "eviction $section boot (fused+armed, atomic $atomic)"
tests/gate.sh:853:      py tests/evict_battery.py "$PORT" "$section" >"$TMPDIR/battery.log" 2>&1 \
tests/gate.sh:908:  # EXIT is the publication point even for row_timeout's exit124. Preserve every partial
tests/gate.sh:966:    for atomic in 0 1; do for mode in split armed; do JOB_NAMES+=("evict-$section-$mode-$atomic"); done; done
tests/gate.sh:1121:  timeout --kill-after=5 10 taskset -c "$CORES" "$CANDIDATE_BINARY" "${conf[@]}" \
tests/gate.sh:1262:# store-boundary spies make held epochs, capture cursors, eviction and allocation failures exact.
tests/gate.sh:1271:for STORE_CASE in unlinked randomkey rehash rollback snapshot-eviction flags aof-eviction intents imported-hash field-index-failure hash-bytes; do
tests/gate.sh:1536:# timeout answers "*-1" / "_", which are ReplyCode-carried, so a discard that clears only the byte
tests/gate.sh:1540:# op.reply.clear() the four timeout rows fail and the rest pass.
tests/gate.sh:2259:s = ctx.wrap_socket(socket.create_connection(("127.0.0.1", port), timeout=5))
tests/gate.sh:2535:  TSAN_OPTIONS=halt_on_error=1:exitcode=66 timeout --foreground 60 \
tests/gate.sh:2595:for tool in g++ make python3 redis-cli memtier_benchmark ss taskset timeout awk setarch flock; do
tests/gate.sh:2673:# ---- eviction accounting on both read paths: owner-served (split) and lane-served (fused+armed) --
tests/gate.sh:2674:# tests/evict_battery.py needs one FRESH boot per section (it sets maxmemory itself and has no
tests/gate.sh:2680:# evicted FIRST, which is the inverse of the policy the boot asked for.
tests/gate.sh:2683:    collect_job "evict-$EVSEC-split-$AT"
tests/gate.sh:2684:    collect_job "evict-$EVSEC-armed-$AT"
tests/gate.sh:2823:#   * its own per-row timeout is derived from the row's history, and that history is dominated by
tests/gate.sh:2825:#     at 30s. Three overnight rounds, three identical timeouts.
tests/gate.sh:2828:#     searches every ladder from scratch, which no timeout budget survives.
tests/gate_process_test.py:31:        self.timeout = 5
tests/gate_process_test.py:34:    def gettimeout(self):
tests/gate_process_test.py:35:        return self.timeout
tests/gate_process_test.py:37:    def settimeout(self, timeout):
tests/gate_process_test.py:38:        self.timeout = timeout
tests/gate_process_test.py:87:    def wait(self, timeout):
tests/gate_process_test.py:107:        self.assertEqual(conn.timeout, 5)
tests/gate_process_test.py:112:            gate.quiesce_connections(conn, Process(conn), timeout=.025)
tests/gate_process_test.py:136:        conn = Connection(counts=(1,), eof=socket.timeout('peer never closed'))
tests/gate_process_test.py:137:        with self.clock(), self.assertRaisesRegex(socket.timeout, 'peer never closed'):
tests/gate_process_test.py:139:        self.assertEqual(conn.timeout, 5)
tests/gates_test.py:290:                           text=True, capture_output=True, check=True, timeout=10)
tests/gates_test.py:365:                                  cwd=root, env=env, text=True, capture_output=True, timeout=5)
tests/gates_test.py:409:                stdout, stderr = process.communicate(timeout=5)
tests/gates_test.py:415:            foreign.wait(timeout=5)
tests/gates_test.py:440:                owned.wait(timeout=5)
tests/gates_test.py:441:                stdout, stderr = process.communicate(timeout=5)
tests/gates_test.py:450:                    child.wait(timeout=5)
tests/gates_test.py:516:                    stdout, stderr = process.communicate(timeout=1)
tests/gates_test.py:522:                stdout, stderr = process.communicate(timeout=5)
tests/gates_test.py:548:                process.communicate(timeout=5)
tests/gates_test.py:550:                foreign.wait(timeout=5)
tests/gates_test.py:601:                                    text=True, capture_output=True, timeout=5)
tests/gates_test.py:685:                              text=True, capture_output=True, timeout=5), cpu
tests/gates_test.py:758:            # invoking timeout teardown while otherwise healthy rows were still completing.
tests/gates_test.py:839:    # on one CPU (retained controls reached 92--94 families before timeout).
tests/gates_test.py:930:                result = subprocess.run(['timeout', '--kill-after=2', '45', 'taskset', '-c', cpu_list,
tests/gates_test.py:932:                                        text=True, capture_output=True, timeout=50)
tests/gates_test.py:1161:taskset(){ timeout "$@"; }
tests/gates_test.py:1165:timeout(){
tests/gates_test.py:1193:                capture_output=True, text=True, timeout=5)
tests/gates_test.py:1244:                    text=True, capture_output=True, timeout=5)
tests/gates_test.py:1321:                        cwd=root, env=env, text=True, capture_output=True, timeout=5)
tests/gates_test.py:1352:                                cwd=root, env=env, text=True, capture_output=True, timeout=5)
tests/gates_test.py:1379:                                    text=True, capture_output=True, timeout=5)
tests/gates_test.py:1421:                                        cwd=root, text=True, capture_output=True, timeout=5)
tests/differ_fanout_test.py:129:taskset(){ shift 2; if [ "$1" = timeout ]; then shift 2; fi; "$@"; }
tests/differ_fanout_test.py:147:                                cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
tests/differ_fanout_test.py:246:        write_json(self.directory / 'timeouts.json',
tests/differ_fanout_test.py:258:                '--row-plan', str(self.directory / 'timeouts.json'),
tests/differ_fanout_test.py:317:    def test_success_and_timeout_history_match_emitted_six_decimal_duration(self):
tests/differ_fanout_test.py:350:                                      FOLD_RC=str(rc), FOLD_OUTPUT=output), capture_output=True, text=True, timeout=5)
tests/atomic_survivors_unit.cc:171:            "failed admission installed no evictable candidate");
tests/read_local_write_ring_unit.cc:29:// write that never refines: a wide multi-key write, or a point write under an evicting maxmemory
tests/read_local_write_ring_unit.cc:40://   M2  sweep stops after the first live group-> cases 10, 12 and both precise soaks, the soaks
tests/read_local_write_ring_unit.cc:107:    // and its ordinary point write under an evicting maxmemory policy. It takes no ring slot and no
tests/read_local_write_ring_unit.cc:195:        // sits at every distance from the ring head across the sweep.
tests/read_local_write_ring_unit.cc:310:// evicting maxmemory policy -- is one. Run four ring capacities of them, with precise writes and
tests/rehash_waits_unit.cc:217:static void maintenance_child(bool expiry) {
tests/rehash_waits_unit.cc:246:            require(f.store.active_expire(64) != 0, "capacity-blocked maintenance remains work");
tests/rehash_waits_unit.cc:253:                "maintenance did not release the stale participant");
tests/rehash_waits_unit.cc:292:    std::printf("PASS maintenance %s\n", expiry ? "expiry effects" : "four pinned-ring resizes");
tests/rehash_waits_unit.cc:350:    std::puts("PASS maintenance hash expiry under pinned capacity");
tests/rehash_waits_unit.cc:373:    std::puts("PASS maintenance snapshot table retirement");
tests/rehash_waits_unit.cc:400:            "an unvisited resize prevents parking, even before its first maintenance visit");
tests/rehash_waits_unit.cc:404:    require(!store.rehashing(), "idle maintenance reaches every owned shard within its visit bound");
tests/rehash_waits_unit.cc:407:    std::puts("PASS maintenance idle owner with more shards than the visit budget");
tests/rehash_waits_unit.cc:410:static int maintenance_checks() {
tests/rehash_waits_unit.cc:414:        require(pid >= 0, "maintenance fork");
tests/rehash_waits_unit.cc:416:            if (which < 2) maintenance_child(which == 1);
tests/rehash_waits_unit.cc:427:                "maintenance must return without a quiescence deadline");
tests/rehash_waits_unit.cc:435:    if (selection == "maintenance") return maintenance_checks();
tests/netcmd_unit.cc:244:        tracking_eviction();
tests/netcmd_unit.cc:326:    static void tracking_eviction() {
tests/netcmd_unit.cc:352:                      "tracking eviction preserves exact key and owner counts");
tests/netcmd_unit.cc:355:                    check(a.fill_buf().empty() && b.fill_buf().empty(), "no eviction before the table is full");
tests/netcmd_unit.cc:365:                              "each evicted key invalidates every tracking owner exactly once");
tests/netcmd_unit.cc:367:                    check(removed == 1, "one actual eviction per full-table insertion");
tests/netcmd_unit.cc:371:            check(server.climon_invalidations() == 8192, "4096 evictions fired for both owners");
tests/netcmd_unit.cc:374:                      "random eviction reaches the whole table, including a single collision bucket");
tests/netcmd_unit.cc:523:    else if (mode == "tracking-eviction") R::tracking_eviction();
config-parser-test
deadconf-acl-JFRQn2
deadconf-acl-NNhJT4
deadconf-acl-method.txt
deadconf-acl-old.log
deadconf-arm-sha256.txt
deadconf-differ-aclsel.txt
deadconf-doc4-commit.txt
deadconf-doc4-old.log
deadconf-doc5-old.log
deadconf-final-config.log
deadconf-item1-build.log
deadconf-item1-final-build.log
deadconf-item1-parser.log
deadconf-item1-unit.log
deadconf-item2-build.log
deadconf-item2-config.log
deadconf-item2-final-build.log
deadconf-item2-unit.log
deadconf-item3-build.log
deadconf-item3-unit.log
deadconf-item5-build.log
deadconf-item5-commit.txt
deadconf-item5-final-build.log
deadconf-item5-unit.log
deadconf-old
deadconf-old-config.log
deadconf-old-latency-monitor-threshold.log
deadconf-old-parser.log
deadconf-old-stream-node-max-bytes.log
deadconf-old-stream-node-max-entries.log
deadconf-old-unit-build.log
deadconf-old-zc-boundary.log
deadconf-old-zc-install.log
deadconf-old-zc-live.log
deadconf-old-zc-off.log
deadconf-pre-build.log
deadconf-tracking-method.txt
deadconf-tracking-old.log
deadconf-unit-suite.log
deadconf-zc-debug.log
deadconf-zc-old-build.log
deadconf-zc-sanitized-build.log
deadconf-zc-sanitized.log
deadconf-zc-sanitized.o
deadconf_conf_check.py
flipctl-unit
netcmd-acl-old
netcmd-config-old
netcmd-tracking-old
netcmd-unit
netcmd-zc-old
netcmd-zc-sanitized
read-local-ring-unit
read-local-write-ring-unit
reorder-unit
src
tests
tomokv
tomokv-deadconf-post
tomokv-deadconf-pre
tomokv-tracking-post
tomokv-zc-post
tomokv-zc-pre
waits-unit
43:# bodies still move GCC just past the default large-unit threshold. 10600 restores the same inlining
44:# decisions as the base-420b4d492 translation unit; the objdump gate locks cmd_get/cmd_set to base.
45:build/src/cmd/t_string.o: CXXFLAGS += --param large-unit-insns=10600
71:# removed, i.e. the pre-fix behaviour. tests/rlcache_churn.py MUST fail against this binary; a
79:# build except that ScriptPhase::Pin arms nothing, so tests/xscript.py counterexample MUST fail
86:# Server-less unit binaries: the config parser and the flip controller. `make unit` builds and
87:# runs both (neither boots a server). tests/gate.sh's parser row is the same program.
88:build/config-parser-test: tests/config_parser_test.cc $(wildcard src/*/*.h) Makefile
90:	$(CXX) $(CXXFLAGS) -I. tests/config_parser_test.cc -o $@
91:build/flipctl-unit: tests/flipctl_unit.cc src/core/flipctl.cc $(wildcard src/*/*.h) Makefile
93:	$(CXX) $(CXXFLAGS) -I. tests/flipctl_unit.cc src/core/flipctl.cc -o $@
95:build/read-local-ring-unit: tests/read_local_ring_unit.cc $(wildcard src/*/*.h) Makefile
97:	$(CXX) $(CXXFLAGS) -I. tests/read_local_ring_unit.cc -o $@
98:build/read-local-write-ring-unit: tests/read_local_write_ring_unit.cc $(wildcard src/*/*.h) Makefile
100:	$(CXX) $(CXXFLAGS) -I. tests/read_local_write_ring_unit.cc -o $@
102:build/reorder-unit: tests/reorder_unit.cc $(wildcard src/*/*.h) Makefile
104:	$(CXX) $(CXXFLAGS) -I. tests/reorder_unit.cc -o $@
105:STORE_REGRESSION_SRC := tests/store_regression.cc src/cmd/t_hash.cc src/cmd/t_hash_ttl.cc
119:build/waits-unit: tests/waits_unit.cc $(wildcard src/*/*.h) Makefile
121:	$(CXX) $(CXXFLAGS) -I. tests/waits_unit.cc -o $@
122:unit: build/config-parser-test build/flipctl-unit build/read-local-ring-unit build/read-local-write-ring-unit build/reorder-unit build/waits-unit
123:	./build/config-parser-test
124:	./build/flipctl-unit
125:	./build/read-local-ring-unit
126:	./build/read-local-write-ring-unit
127:	./build/reorder-unit
128:	./build/waits-unit
130:# Deterministic core regressions: the test TU instantiates the real executor/IO methods
131:# with ASAN/UBSAN and test-only interleaving hooks. No server or ring is started.
133:build/rehash-waits-unit: tests/rehash_waits_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) Makefile
136:build/core-concurrency-unit: tests/core_concurrency_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h)
141:# Directed owner-phase tests. The test includes xshard.cc to drive the real private phases
143:build/atomic-survivors-unit: tests/atomic_survivors_unit.cc src/cmd/xshard.cc $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) Makefile
144:	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. tests/atomic_survivors_unit.cc \
151:build/broaden-bench: tests/broaden_bench.cc Makefile
153:	$(CXX) $(CXXFLAGS) -I. tests/broaden_bench.cc -o $@
158:.PHONY: all asan tsan noreserve clean unit tools
162:NETCMD_TEST_SRC := tests/netcmd_unit.cc tests/netcmd_stream_unit.cc tests/netcmd_zset_unit.cc tests/netcmd_config_unit.cc
163:NETCMD_TEST_OBJ := $(NETCMD_TEST_SRC:tests/%.cc=build/tests/%.o)
165:build/tests/%.o: tests/%.cc tests/netcmd_unit.h $(wildcard src/*/*.h) $(wildcard src/*/*.cc) $(wildcard src/*/*.inc) Makefile
168:build/netcmd-unit: $(NETCMD_TEST_OBJ) $(NETCMD_LIB_OBJ)

codex
The cited check enforces the idle timeout. I’ll add the RESP2 condition there and test both protocols through the existing serverless command harness. The config comment already says RESP2; I’ll make RESP3’s inclusion explicit.

exec
/bin/bash -lc "sed -n '1,330p' tests/netcmd_unit.cc && sed -n '475,550p' tests/netcmd_unit.cc && rg -n 'friend|NetCmd|Core.*Test|client_cron|pubsub_local_|pubsub_pending_' src/core/io_loop.h src/core/thread.h src/core/server.h tests/core_concurrency_unit.cc" in /home/user/Projects/cx-deadconf-fix
exec
/bin/bash -lc "sed -n '1,58p' Makefile && sed -n '130,190p' Makefile && sed -n '1,240p' tests/netcmd_unit.h" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
#include "netcmd_unit.h"
// Include the actual cold command implementation to exercise its anonymous notification helpers.
// The unit link omits the corresponding production object.
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wsubobject-linkage"
#include "src/cmd/xshard.cc"
#pragma GCC diagnostic pop
#include <filesystem>

long netcmd_fail_after = -1;
size_t netcmd_fail_size = 0;
unsigned netcmd_allocations = 0, netcmd_failures = 0;
void* operator new(size_t size) {
    if (netcmd_fail_after >= 0 && (!netcmd_fail_size || netcmd_fail_size == size)) {
        ++netcmd_allocations;
        if (netcmd_fail_after-- == 0) { ++netcmd_failures; throw std::bad_alloc(); }
    }
    if (void* ptr = std::malloc(size ? size : 1)) return ptr;
    throw std::bad_alloc();
}
void operator delete(void* ptr) noexcept { std::free(ptr); }
void operator delete(void* ptr, size_t) noexcept { std::free(ptr); }
void* operator new[](size_t size) { return ::operator new(size); }
void operator delete[](void* ptr) noexcept { std::free(ptr); }
void operator delete[](void* ptr, size_t) noexcept { std::free(ptr); }

namespace tomo {
struct NetcmdRegression {
    // Preparation-only fixtures still satisfy the production sender's complete bind contract.
    // The Ring stays unopened; these cases must never submit or acquire a borrowed value.
    struct Sender {
        Ring ring;
        std::atomic<bool> limits{false};
        uint32_t now_s = 0;
        LoopSignals signals;
        void bind(WbEngine& wb) {
            wb.bind(&ring, nullptr,
                [](void*, int32_t, const char*) { check(false, "unexpected fixture borrow release"); },
                nullptr, [](void*, Client&, Op&) { check(false, "unexpected fixture special retire"); },
                &limits, nullptr, [](void*, Client&) { return false; }, &now_s, &signals);
        }
    };
    static void notify_oom() {
        Server server;
        auto chain = std::make_unique<PubSubNotificationChain>();
        chain->items.push_back(PubSubNotificationItem{"channel", "message"});
        fault(0);
        bool threw = false;
        try { (void)notify_reserve_chain(server, std::move(chain)); }
        catch (const std::bad_alloc&) { threw = true; }
        const auto failed = netcmd_failures; fault(-1);
        check(threw && failed == 1, "shared_ptr control block allocation failed");
        check(server.pubsub_inflight() == 0, "reservation released exactly once on failure");
        auto good = std::make_unique<PubSubNotificationChain>();
        good->items.push_back(PubSubNotificationItem{"channel", "message"});
        auto reserved = notify_reserve_chain(server, std::move(good));
        check(reserved && server.pubsub_inflight() == 1, "successful chain owns reservation");
        reserved.reset(); check(server.pubsub_inflight() == 0, "successful chain releases reservation");
    }

    static void notify_retry() {
        Server server;
        // The gate runs this serverless row without taskset. Automatic SMT placement requires
        // whole sibling pairs for BOTH roles; only one IO is a tracking destination below.
        Config cfg; cfg.even_ifid = 2; cfg.even_ex = 2; cfg.shards = 16;
        check(server.prepare_boot(cfg), "notification topology");
        server.threads_.resize(server.placement().total_threads());
        for (uint32_t i = 0; i < server.threads_.size(); ++i) {
            server.threads_[i] = std::make_unique<ThreadCtx>();
            server.threads_[i]->init(i, Role::Ifid, server.threads_.size(), 0, 0);
        }
        const uint32_t io = server.placement().ifid_threads().front();
        ThreadCtx& thread = server.thread(io);
        server.climon_tracking_io_mask_.store(uint64_t{1} << io);
        Ring ring; LoopSignals signals;
        uint32_t queued = 0;
        while (thread.post_client(0, nullptr, ring, signals)) ++queued;
        check(queued > 0, "producer marker lane filled");
        Shard shard; shard.init_private(&server, 0, TypeLimits{}, StreamLimits{});
        shard.notify_state_slot() = std::make_unique<NotifyShardState>();
        NotifyOut out; out.routes = NOTIFY_TRACKING; out.key = "expired";
        shard.notify_state_slot()->keyless.push_back(std::move(out));
        check(notify_ex_pass_entry(server, shard, 0, thread, ring, signals) == 0,
              "failed marker post is incomplete work");
        check(shard.notify_state_slot()->keyless.size() == 1, "keyless invalidation retained");
        std::deque<PubSubEvent*> events; thread.take_pubsub_events(events);
        check(events.empty(), "failed post enqueued no payload");
        check(thread.drain_clients([](Client*) {}) == queued, "producer lane drained");
        check(notify_ex_pass_entry(server, shard, 0, thread, ring, signals) == 1, "retry completes record");
        thread.take_pubsub_events(events);
        check(events.size() == 1 && events.front()->kind == PubSubEventKind::TrackingInvalidate &&
              events.front()->items.size() == 1 && events.front()->items.front().value == "expired",
              "exact invalidation delivered after retry");
        server.pubsub_event_retired(); delete events.front();
        thread.drain_clients([](Client*) {});
    }

    static void flush() {
        // Two IOs still prove the foreign delivery; an even EX count also admits SMT placement.
        Server server; Config cfg; cfg.even_ifid = 2; cfg.even_ex = 2; cfg.shards = 16;
        check(server.prepare_boot(cfg), "flush topology");
        const auto& ios = server.placement().ifid_threads();
        check(ios.size() == 2, "foreign tracking IO exists");
        server.threads_.resize(server.placement().total_threads());
        for (uint32_t i = 0; i < server.threads_.size(); ++i) {
            server.threads_[i] = std::make_unique<ThreadCtx>();
            server.threads_[i]->init(i, Role::Ifid, server.threads_.size(), 0, 0);
        }
        IoLoop loop; loop.srv_ = &server; loop.self_ = &server.thread(ios[0]);
        loop.climon_armed_cached_ = Server::kClimonTracking;
        server.climon_tracking_io_mask_.store(uint64_t{1} << ios[1]);
        Client writer(-1); writer.set_id(9); Op op; args(op, {"FLUSHALL"});
        check(!loop.climon_armed_gate(&writer, op), "FLUSH passed dispatch gate");
        std::deque<PubSubEvent*> events;
        server.thread(ios[1]).take_pubsub_events(events);
        check(events.empty(), "no flush invalidation before owner work was published");
        op.state.store(OpState::Done);
        loop.climon_flush_completed(op);
        server.thread(ios[1]).take_pubsub_events(events);
        check(events.size() == 1 && events.front()->kind == PubSubEventKind::TrackingFlush,
              "completed flush invalidates foreign tracking IO");
        delete events.front(); server.pubsub_event_retired();
        server.thread(ios[1]).drain_clients([](Client*) {});
    }

    static void output() {
        Sender sender;
        Client client(-1); WbEngine wb;
        sender.bind(wb);
        client.start_obuf_tracking();
        check(client.obuf_bytes() == 0, "tracked balance drained before disable");
        Op* op = client.rob().acquire(); check(op, "reply slot");
        op->reply.append("+PONG\r\n", 7); op->state.store(OpState::Done); client.rob().publish();
        bool allowed; wb.prepare(client, allowed);
        check(allowed && client.fill_buf().size() == 7, "disabled specialization staged reply");
        client.swap_buffers(); client.commit_write(7);
        check(client.write_drained(), "uncounted reply send completion did not underflow");

        Server server; ThreadCtx self; IoLoop loop;
        loop.srv_ = &server; loop.self_ = &self;
        sender.bind(loop.wb_);
        // Mirror Server::init's mailbox initialization without starting workers or opening rings.
        // cx-waits made raw live-field stores writer-only; IO reads the published snapshot.
        server.live_config_committed_ = server.capture_live_config(server.live_config_version_.load());
        server.live_config_mailboxes_ = std::make_unique<LiveConfigMailbox[]>(server.nthreads() + 1);
        server.live_config_mailboxes_[self.id()].init(server.live_config_committed_);
        ClientOutputBufferLimits limits{}; limits.normal.hard_bytes = 8;
        server.set_client_output_buffer_limits(limits);
        check(server.client_obuf_armed() &&
              server.client_limits_snapshot(self.id()).normal.hard_bytes == 8,
              "hard limit published to the IO config mailbox");
        Client held(-1); held.set_id(1);
        check(held.rob().acquire(), "held ordinary operation"); held.rob().publish();
        check(!held.blocked(), "ordinary operation, not blocking exception");
        check(loop.wb_.defer_oob(held, "012345678", 9), "push entered deferred queue");
        check(held.buffered_output_bytes() == 0 && loop.wb_.deferred_output_bytes(held) == 9,
              "limit bytes exist only in deferred storage");
        check(loop.client_obuf_check(&held, false), "hard limit fired before Done");
        check(held.closing(), "deferred output scheduled connection close");
        loop.wb_.teardown(held);
    }

    static void pubsub() {
        for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                          IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
            for (bool suppressed : {false, true}) {
                Sender sender;
                Server server; ThreadCtx self; IoLoop loop; Client client(-1); client.set_id(42);
                loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
                Op* op = client.rob().acquire(); check(op, "pending pubsub operation");
                if (suppressed) op->mark_reply_skip();
                client.rob().publish();
                auto& local = loop.pubsub_local_[client.id()]; local.client = &client;
                local.channels.insert("old"); local.pending = 1;
                auto& pending = loop.pubsub_pending_[client.id()];
                pending.kind = kind; pending.op_id = client.rob().flush_id(); pending.subscribe = true;
                if (kind == IoLoop::PubSubPendingKind::Modify) pending.items.push_back("new");
                server.pubsub_pending_started();
                const std::string message = "*3\r\n$7\r\nmessage\r\n$3\r\nold\r\n$4\r\ndata\r\n";
                loop.pubsub_emit(&client, message.data(), message.size(), true);
                check(!pending.deferred.empty(), "publication arrived while control was pending");
                loop.pubsub_finish_pending(client.id());
                check(loop.pubsub_pending_.empty(), "pending control completed");
                bool allowed;
                if (suppressed) loop.wb_.prepare_suppressing(client, allowed);
                else loop.wb_.prepare(client, allowed);
                const std::string reply(client.fill_buf().data(), client.fill_buf().size());
                std::string push = message; push[0] = '>';
                check(reply.find(push) != std::string::npos, "independent publication survives retirement");
                if (suppressed) check(reply == push, "only command reply was suppressed");
            }
        }
    }

    static void receive_segments() {
        SegmentQueue<4, 8> segments;
        segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
        check(segments.size() == 3 && segments.byte_size() == 19, "two-piece aggregate split into representable segments");
        iovec iov[4]; bool borrow = false; uint32_t bytes = 0;
        const auto n = segments.build_iov(iov, 4, 64, borrow, bytes);
        std::string actual;
        for (uint32_t i = 0; i < n; ++i) {
            check(iov[i].iov_len <= 8, "segment length cap honored");
            actual.append(static_cast<const char*>(iov[i].iov_base), iov[i].iov_len);
        }
        check(bytes == 19 && actual == "abcdefghijklmnopqrs", "aggregate contents preserved");
        Client input(-1); size_t avail = 0;
        check(input.read_space(2 * 1024 * 1024, avail, true, 1024 * 1024) && avail >= 2 * 1024 * 1024,
              "whole command can exceed individual bulk limit");
        const auto before = input.rcap();
        input.commit_read(before - 1);
        check(!input.read_space(4096, avail, false, 1024 * 1024) && input.rcap() == before,
              "receive growth remains forbidden with outstanding argv slices");
        // Allocation reserves virtual space; no 600 MiB payload or benchmark is needed.
        Client large(-1);
        check(large.read_space(600ull * 1024 * 1024, avail, true) &&
              avail >= 600ull * 1024 * 1024, "default receive allowance has no one-bulk ceiling");
        check(large.read_space(600ull * 1024 * 1024, avail, true, 1024ull * 1024 * 1024) &&
              avail >= 600ull * 1024 * 1024, "raised bulk limit fits epoll receive geometry");
    }

    // Diagnostic for the still-open cross-family partial-mutation finding; deliberately absent
    // from the passing gate rows until a failure-atomic collection update is implemented.
    static void collection_oom() {
        Shard shard; TypeLimits limits; limits.hash.max_entries = 1;
        shard.init_private(nullptr, 0, limits, StreamLimits{}); shard.set_cached_now_ms(1000);
        check(execute(shard, {"HSET", "h", "a", "old-a", "b", "old-b"}) == ":2\r\n", "expanded hash seeded");
        auto* object = shard.store().find(FlatStore::hash_key(Slice("h", 1)), Slice("h", 1));
        check(CollectionRef(object).encoding() == CollectionEncoding::Hashtable, "expanded hash arm entered");
        check(execute(shard, {"HPEXPIRE", "h", "60000", "FIELDS", "1", "a"}) == "*1\r\n:1\r\n", "field TTL armed");
        const std::string replacement(256, 'x'); Op op;
        args(op, {"HSET", "h", "a", replacement.c_str(), "b", replacement.c_str()});
        fault(1, replacement.size() + 1); op.spec->handler(shard, op);
        const unsigned failures = netcmd_failures; fault(-1);
        check(failures == 1, "second replacement allocation failed");
        check(std::string(op.reply.data(), op.reply.size()).starts_with("-ERR"), "HSET reported allocation failure");
        check(execute(shard, {"HGET", "h", "a"}) == "$5\r\nold-a\r\n",
              "OPEN F05: failed multi-field HSET retained a changed prefix (and its old TTL)");
    }

    static void config() {
        test_config_bounds();
        acl_selectors();
        tracking_eviction();
        zero_copy("zc-all");
        Server server;
        const std::string password = "pass with spaces\n\r\t\"'\\tail";
        char directory[] = "build/netcmd-config-XXXXXX";
        check(::mkdtemp(directory), "private config directory");
        const std::string path = std::string(directory) + "/tomo.conf";
        server.cfg_.conf_path = path.c_str(); server.cfg_.requirepass = password.c_str();
        command_bind_server(&server);
        test_config_rewrite();
        command_bind_server(nullptr);
        std::filesystem::remove_all(directory);
    }

    static void acl_selectors() {
        const std::vector<std::vector<std::string>> selectors = {
            {"()"}, {"(+get ~safe:*)"}, {"(", "+get", "~safe:*", ")"}, {"("}, {"(+@all (~*))"}
        };
        char directory[] = "build/deadconf-acl-XXXXXX";
        check(::mkdtemp(directory), "private ACL fixture directory");
        const std::string path = std::string(directory) + "/users.acl";
        auto write_file = [&](const std::vector<std::string>& rules) {
            std::FILE* file = std::fopen(path.c_str(), "w"); check(file, "open ACL fixture");
            std::fputs("user default on nopass ~* &* +@all\nuser acl-file on nopass ~safe:* +get", file);
            for (const auto& rule : rules) std::fprintf(file, " %s", rule.c_str());
            check(std::fputs("\n", file) >= 0 && std::fclose(file) == 0, "write ACL fixture");
        };
        write_file({});
        Server server; Config cfg; cfg.aclfile = path.c_str();
        ThreadCtx self; self.init(0, Role::Ifid, 1, 0, 0);
        IoLoop loop; loop.srv_ = &server; loop.self_ = &self;
        Client admin(-1); admin.set_id(808);
        std::string error;
        acl_shutdown();
        check(acl_initialize(server, cfg, error), "valid root ACL file accepted");
        auto request = [&](std::vector<std::string> values) {
            Op op;
            for (const auto& value : values)
                check(op.push_arg(Slice(value.data(), value.size())), "ACL fixture argument");
            op.spec = command_lookup(op.cmd_name());
            acl_command_entry(loop, admin, op);
            return std::string(op.reply.data(), op.reply.size());
        };
        check(request({"ACL", "SETUSER", "acl-root", "on", "nopass", "~safe:*", "+get"}) == "+OK\r\n",
              "root ACL rules remain accepted");
        const auto before = request({"ACL", "GETUSER", "acl-root"});
        for (const auto& rules : selectors) {
            for (const char* name : {"acl-root", "acl-new"}) {
                std::vector<std::string> values = {"ACL", "SETUSER", name, "reset", "on", "nopass"};
                values.insert(values.end(), rules.begin(), rules.end());
                const auto reply = request(values);
                check(reply.starts_with("-ERR ") && reply.find("ACL selectors are not supported") != std::string::npos,
                      "ACL SETUSER rejects packed, split, empty and malformed selectors");
                check(request({"ACL", "GETUSER", "acl-root"}) == before, "failed selector leaves existing ACL intact");
                check(request({"ACL", "GETUSER", "acl-new"}) == "$-1\r\n", "failed selector creates no user");
            }
            write_file(rules);
            const auto reply = request({"ACL", "LOAD"});
            check(reply.starts_with("-") && reply.find("ACL selectors are not supported") != std::string::npos &&
                  reply.ends_with("no change to the previously active ACL rules was performed\r\n"),
                  "ACL LOAD rejects selectors");
            check(request({"ACL", "GETUSER", "acl-root"}) == before, "rejected ACL LOAD leaves live users intact");
        }
        acl_shutdown();
        for (const auto& rules : selectors) {
            Config boot;
            boot.acl_users = {{"acl-boot", "on", "nopass"}};
            boot.acl_users.front().insert(boot.acl_users.front().end(), rules.begin(), rules.end());
            error.clear();
            check(!acl_initialize(server, boot, error) && error.find("ACL selectors are not supported") != std::string::npos,
                  "inline boot ACL rejects selectors before startup");
            acl_shutdown();
            write_file(rules);
            error.clear();
            check(!acl_initialize(server, cfg, error) && error.find("ACL selectors are not supported") != std::string::npos,
                  "boot ACL file rejects selectors before startup");
            acl_shutdown();
        }
        std::filesystem::remove_all(directory);
    }


    static void tracking_eviction() {
        for (bool collide : {false, true}) {
            Server server; server.cfg_.tracking_table_max_keys = 32;
            ThreadCtx self; self.init(0, Role::Ifid, 1, 0, 0);
            IoLoop loop; loop.srv_ = &server; loop.self_ = &self;
                    server.shard(sid).set_zc_min(UINT32_MAX);
                    check(execute(server.shard(sid), {"SET", keys[sid].c_str(), value.c_str()}) == "+OK\r\n",
                          "seed gather allocation-failure case");
                }
                Client client(-1); client.set_id(778);
                Op op; args(op, {"MGET", keys[0].c_str(), keys[1].c_str()});
                ScatterArenaPool pool; ScatterDispatch dispatch;
                check(xshard_prepare(server, op, pool, 0, client.id(), dispatch) == ScatterPrepare::Ready,
                      "prepare allocation-failure gather");
                auto& state = *dispatch.state;
                fault(1, value.size()); // the second large reply copy, after the first owner finished
                for (uint32_t i = 0; i < state.nsub; ++i) {
                    const int sid = state.groups[i].shard;
                    check(xshard_execute(Task{&client, 0, sid, &state}, server.shard(sid), op,
                                         server.worker_of_shard(sid)) == ScatterTaskResult::Complete,
                          "copy allocation failure terminates the owner task");
                }
                const auto failures = netcmd_failures; fault(-1);
                WorkError error = WorkError::None;
                check(failures == 1 && first_error(state, error) && error == WorkError::Oom,
                      "second owned-copy allocation really failed and reported OOM");
                xshard_destroy(&state, pool, 0); pool.reap_deferred();
                for (int sid = 0; sid < 2; ++sid)
                    check(server.shard(sid).store().outstanding_borrows() == 0, "OOM used no borrow fallback");
            }
        }
    }
};
}

int main(int argc, char** argv) {
    check(argc == 2 || (argc == 3 && std::string(argv[1]) == "config-bounds"),
          "one regression section (and optional config-bound name) required");
    check(tomo::command_registry_init(false), "command registry initialized");
    const std::string mode = argv[1];
    using R = tomo::NetcmdRegression;
    if (mode == "streams") test_stream_faults();
    else if (mode == "zpop") test_zpop_faults();
    else if (mode == "notify-oom") R::notify_oom();
    else if (mode == "notify-retry") R::notify_retry();
    else if (mode == "flush") R::flush();
    else if (mode == "output") R::output();
    else if (mode == "pubsub") R::pubsub();
    else if (mode == "receive") R::receive_segments();
    else if (mode == "collection-oom") R::collection_oom();
    else if (mode == "config") R::config();
    else if (mode == "config-bounds") test_config_bounds(argc == 3 ? argv[2] : nullptr);
    else if (mode == "acl-selectors") R::acl_selectors();
    else if (mode == "tracking-eviction") R::tracking_eviction();
    else if (mode.starts_with("zc-")) R::zero_copy(mode);
    else check(false, "unknown regression section");
    std::printf("ok: netcmd %s\n", argv[1]);
}
tests/core_concurrency_unit.cc:21:struct CoreConcurrencyTest {
tests/core_concurrency_unit.cc:417:    using T = tomo::CoreConcurrencyTest;
src/core/io_loop.h:59:    friend struct CoreConcurrencyTest;
src/core/io_loop.h:130:                    loop->client_cron_beat_ms_ = 0;
src/core/io_loop.h:322:            pubsub_local_.reserve(pubsub_local_.size() + incoming);
src/core/io_loop.h:445:    friend struct NetcmdRegression;
src/core/io_loop.h:482:    friend bool multi_dispatch_entry(IoLoop&, Client&, Op&, uint32_t);
src/core/io_loop.h:483:    friend bool multi_dispatch_entry_iofused(IoLoop&, Client&, Op&, uint32_t);
src/core/io_loop.h:485:    friend bool multi_dispatch_entry_impl(IoLoop&, Client&, Op&, uint32_t);
src/core/io_loop.h:486:    friend bool auth_dispatch_entry(IoLoop&, Client&, Op&, uint32_t);
src/core/io_loop.h:487:    friend bool acl_dispatch_entry(IoLoop&, Client&, Op&, uint32_t, uint8_t);
src/core/io_loop.h:488:    friend bool acl_finish_dispatch_denial(IoLoop&, Client&, Op&, uint32_t,
src/core/io_loop.h:490:    friend void acl_command_entry(IoLoop&, Client&, Op&);
src/core/io_loop.h:491:    friend void acl_broadcast_user_change(IoLoop&, uint32_t, const AclPerm*, bool);
src/core/io_loop.h:492:    friend void multi_retire_entry(IoLoop&, Client&, Op&);
src/core/io_loop.h:493:    friend uint32_t multi_owner_pass_entry(IoLoop&);
src/core/io_loop.h:494:    friend uint32_t multi_owner_pass_entry_iofused(IoLoop&);
src/core/io_loop.h:496:    friend uint32_t multi_owner_pass_entry_impl(IoLoop&);
src/core/io_loop.h:497:    friend uint32_t multi_owner_reap_entry(IoLoop&);
src/core/io_loop.h:498:    friend void multi_close_entry(IoLoop&, Client&);
src/core/io_loop.h:499:    friend void multi_shutdown_entry(IoLoop&);
src/core/io_loop.h:500:    friend void notify_retire_batch_entry(IoLoop&, NotifyBatch*, uint64_t);
src/core/io_loop.h:538:            const bool client_cron_armed = !srv_->flip_dispatch_paused() &&
src/core/io_loop.h:539:                                           srv_->client_cron_armed();
src/core/io_loop.h:546:            const bool client_cron_newly_armed = client_cron_armed && !client_cron_was_armed_;
src/core/io_loop.h:547:            if (!client_cron_armed && __builtin_expect(client_cron_was_armed_, false)) {
src/core/io_loop.h:552:            client_cron_was_armed_ = client_cron_armed;
src/core/io_loop.h:568:                bool pass_time_cached = pause_armed || client_cron_armed || save_cron_armed ||
src/core/io_loop.h:578:                if (client_cron_newly_armed) {
src/core/io_loop.h:580:                    client_cron_beat_ms_ = cached_now_ms_;
src/core/io_loop.h:658:                if (__builtin_expect(client_cron_armed &&
src/core/io_loop.h:659:                                     cached_now_ms_ >= client_cron_beat_ms_, false)) {
src/core/io_loop.h:660:                    did += client_cron_pass();
src/core/io_loop.h:661:                    client_cron_beat_ms_ = cached_now_ms_ + 100;
src/core/io_loop.h:796:            const bool client_cron_armed = !srv_->flip_dispatch_paused() &&
src/core/io_loop.h:797:                                           srv_->client_cron_armed();
src/core/io_loop.h:802:            const bool client_cron_newly_armed =
src/core/io_loop.h:803:                client_cron_armed && !client_cron_was_armed_;
src/core/io_loop.h:804:            if (!client_cron_armed && __builtin_expect(client_cron_was_armed_, false))
src/core/io_loop.h:806:            client_cron_was_armed_ = client_cron_armed;
src/core/io_loop.h:814:                bool pass_time_cached = pause_armed || client_cron_armed || save_cron_armed ||
src/core/io_loop.h:824:                if (client_cron_newly_armed) {
src/core/io_loop.h:827:                    client_cron_beat_ms_ = cached_now_ms_;
src/core/io_loop.h:891:                if (__builtin_expect(client_cron_armed &&
src/core/io_loop.h:892:                                     cached_now_ms_ >= client_cron_beat_ms_, false)) {
src/core/io_loop.h:893:                    did += client_cron_pass();
src/core/io_loop.h:894:                    client_cron_beat_ms_ = cached_now_ms_ + 100;
src/core/io_loop.h:6014:        const auto pending = pubsub_pending_.find(c->id());
src/core/io_loop.h:6015:        if (pending != pubsub_pending_.end()) used += pending->second.deferred.size();
src/core/io_loop.h:6048:    uint32_t client_cron_pass() {
src/core/io_loop.h:6051:        if (!initial) { client_cron_cursor_ = 0; return 0; }
src/core/io_loop.h:6059:            if (client_cron_cursor_ >= clients.size()) client_cron_cursor_ = 0;
src/core/io_loop.h:6060:            Client* c = clients[client_cron_cursor_];
src/core/io_loop.h:6073:            if (!closed || clients.size() == before) client_cron_cursor_++;
src/core/io_loop.h:6275:    uint64_t client_cron_beat_ms_ = 0;
src/core/io_loop.h:6279:    size_t   client_cron_cursor_ = 0;
src/core/io_loop.h:6282:    bool     client_cron_was_armed_ = false;
src/core/server.h:132:    friend struct CoreConcurrencyTest;
src/core/server.h:164:    friend struct NetcmdRegression;
src/core/server.h:243:        refresh_client_cron_armed();
src/core/server.h:2210:    bool client_cron_armed() const {
src/core/server.h:2211:        return client_cron_armed_.load(std::memory_order_relaxed);
src/core/server.h:2222:        refresh_client_cron_armed();
src/core/server.h:2232:        refresh_client_cron_armed();
src/core/server.h:3159:    void pubsub_pending_started() { pubsub_pending_.fetch_add(1, std::memory_order_relaxed); }
src/core/server.h:3160:    void pubsub_pending_finished() {
src/core/server.h:3161:        if (pubsub_pending_.fetch_sub(1, std::memory_order_relaxed) == 0) std::abort();
src/core/server.h:3186:    uint64_t pubsub_pending() const { return pubsub_pending_.load(std::memory_order_relaxed); }
src/core/server.h:3272:    void refresh_client_cron_armed() {
src/core/server.h:3278:        client_cron_armed_.store(live_timeout_.load(std::memory_order_relaxed) != 0 ||
src/core/server.h:3460:    std::atomic<bool> client_cron_armed_{true};
src/core/server.h:3554:    std::atomic<uint64_t> pubsub_pending_{0};

 succeeded in 0ms:
CXX      ?= g++
JEDIR    ?= /home/user/Projects/refs/jemalloc/_install
# jemalloc is optional: without it the tree still builds and runs, using the deterministic portable
# size-class table in alloc.h. Set JE=0 to force that path (useful for A/B-ing the allocator).
JE       ?= 1
ifeq ($(JE),1)
  # Prefer the system package; fall back to the copy built from refs/.
  ifneq ($(wildcard /usr/include/jemalloc/jemalloc.h),)
    JEFLAGS := -DTOMO_JEMALLOC
    JELIBS  := -ljemalloc
  else
    JEFLAGS := -DTOMO_JEMALLOC -I$(JEDIR)/include
    JELIBS  := $(JEDIR)/lib/libjemalloc.a -ldl
  endif
else
  JEFLAGS :=
  JELIBS  :=
endif
CXXFLAGS ?= -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread
LDLIBS   ?= -luring -pthread
SRC      := src/main.cc src/net/tls.cc src/cmd/commands.cc src/cmd/glob.cc src/cmd/xshard.cc src/cmd/acl.cc src/cmd/hll.cc src/cmd/t_server.cc src/cmd/t_string.cc src/cmd/t_string_notify.cc src/cmd/t_hash.cc src/cmd/t_hash_ttl.cc \
            src/cmd/t_list.cc src/cmd/t_set.cc src/cmd/t_zset.cc src/cmd/t_zset_ops.cc src/cmd/geo.cc src/cmd/t_stream.cc src/cmd/t_stream_groups.cc src/cmd/scripting.cc src/cmd/functions.cc src/cmd/serialize.cc src/snapshot/snapshot.cc src/persist/aof.cc
SRC      += src/cmd/climon.cc src/cmd/tracking.cc
SRC      += src/cmd/server_tail.cc src/cmd/slowlog.cc src/cmd/lcs.cc src/cmd/info_stats.cc
SRC      += src/cmd/lbsignals.cc
SRC      += src/core/flipctl.cc
SRC      += src/core/genthread.cc
SRC      += src/core/rl2s.cc
SRC      += src/cmd/cmdgap.cc
SRC      += src/cmd/pfdebug.cc
SRC      += src/cmd/cmdmeta.cc
SRC      += src/cmd/t_sort.cc
LDLIBS   += -lssl -lcrypto
BIN      := build/tomokv
OBJ      := $(SRC:%.cc=build/%.o)

all: $(BIN)

$(BIN): $(OBJ)
	$(CXX) $(CXXFLAGS) $(OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

# The clean string family intentionally excludes the armed instantiations, but its parsed template
# bodies still move GCC just past the default large-unit threshold. 10600 restores the same inlining
# decisions as the base-420b4d492 translation unit; the objdump gate locks cmd_get/cmd_set to base.
build/src/cmd/t_string.o: CXXFLAGS += --param large-unit-insns=10600

build/%.o: %.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) $(wildcard third_party/lua/*) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. -c $< -o $@

asan: CXXFLAGS += -fsanitize=address,undefined -fno-omit-frame-pointer -O1
asan:
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. $(SRC) -o build/tomokv-asan $(LDLIBS) -lm

tsan:
	@mkdir -p build
	$(CXX) -std=c++20 -O1 -g -Wall -Wextra -pthread -fsanitize=thread \
# Deterministic core regressions: the test TU instantiates the real executor/IO methods
# with ASAN/UBSAN and test-only interleaving hooks. No server or ring is started.
CORE_TEST_OBJ := $(filter-out build/src/main.o build/src/core/genthread.o,$(OBJ))
build/rehash-waits-unit: tests/rehash_waits_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

build/core-concurrency-unit: tests/core_concurrency_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -O1 -fsanitize=address,undefined -fno-omit-frame-pointer \
	  -DTOMO_CORE_CONCURRENCY_TEST -I. $< $(CORE_TEST_OBJ) -o $@ \
	  $(JELIBS) $(LDLIBS) -lm

# Directed owner-phase tests. The test includes xshard.cc to drive the real private phases
# without starting worker threads or opening a listener; all other code is the release objects.
build/atomic-survivors-unit: tests/atomic_survivors_unit.cc src/cmd/xshard.cc $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. tests/atomic_survivors_unit.cc \
	  $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm

# Load drivers: not part of `all`, kept compiling here so they cannot rot unnoticed.
build/benchtxn: tools/benchtxn.cc Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tools/benchtxn.cc -o $@
build/broaden-bench: tests/broaden_bench.cc Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/broaden_bench.cc -o $@
tools: build/benchtxn build/broaden-bench

clean:
	rm -rf build
.PHONY: all asan tsan noreserve clean unit tools

# Deterministic networking/command regressions. These TUs include the real private implementations;
# omit their production objects from this serverless binary. No server threads or gate are started.
NETCMD_TEST_SRC := tests/netcmd_unit.cc tests/netcmd_stream_unit.cc tests/netcmd_zset_unit.cc tests/netcmd_config_unit.cc
NETCMD_TEST_OBJ := $(NETCMD_TEST_SRC:tests/%.cc=build/tests/%.o)
NETCMD_LIB_OBJ := $(filter-out build/src/main.o build/src/cmd/xshard.o build/src/cmd/t_stream_groups.o build/src/cmd/t_zset.o build/src/cmd/server_tail.o,$(OBJ))
build/tests/%.o: tests/%.cc tests/netcmd_unit.h $(wildcard src/*/*.h) $(wildcard src/*/*.cc) $(wildcard src/*/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Wno-mismatched-new-delete -I. -c $< -o $@
build/netcmd-unit: $(NETCMD_TEST_OBJ) $(NETCMD_LIB_OBJ)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=mkstemp -Wl,--wrap=fopen
#pragma once
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <new>
#include <string>
#include "src/cmd/command.h"
#include "src/core/shard.h"
#include "src/exec/op.h"

extern long netcmd_fail_after;
extern size_t netcmd_fail_size;
extern unsigned netcmd_allocations, netcmd_failures;
inline void check(bool value, const char* message) {
    if (!value) { std::fprintf(stderr, "FAIL: %s\n", message); std::exit(1); }
}
inline void fault(long after, size_t size = 0) {
    netcmd_fail_after = after; netcmd_fail_size = size;
    netcmd_allocations = netcmd_failures = 0;
}
inline void args(tomo::Op& op, std::initializer_list<const char*> values) {
    for (const char* value : values)
        check(op.push_arg(tomo::Slice(value, std::strlen(value))), "argument allocation");
    op.spec = tomo::command_lookup(op.cmd_name());
    check(op.spec != nullptr, "registered command");
    const int first = op.spec->first_key;
    if (first > 0) op.hash = tomo::FlatStore::hash_key(op.arg(first));
    op.shard = 0;
}
inline std::string execute(tomo::Shard& shard, std::initializer_list<const char*> values) {
    tomo::Op op; args(op, values); op.spec->handler(shard, op);
    return std::string(op.reply.data(), op.reply.size());
}
void test_stream_faults();
void test_zpop_faults();
void test_config_rewrite();
void test_config_bounds(const char* only = nullptr);

exec
/bin/bash -lc "sed -n '1325,1395p' tests/gate.sh && rg -n 'netcmd' tests/gate.sh && sed -n '1,145p' src/core/pubsub.inc && rg -n 'client_index|active_idx|refcount|refs_|in_flight|last_interaction_s' src/net/conn.h && sed -n '40,95p' src/core/io_loop.h" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
    && ok "netcmd regression build" || bad "netcmd regression build" "see $RUN_DIR/jobs/production_units/build.log"
for NETCMD_CASE in streams zpop notify-oom notify-retry flush output pubsub receive config; do
  row_begin "netcmd $NETCMD_CASE regression"
  taskset -c "$CORES" ./build/netcmd-unit "$NETCMD_CASE" >$TMPDIR/gate-netcmd-$NETCMD_CASE.txt 2>&1 \
      && ok "netcmd $NETCMD_CASE regression" \
      || bad "netcmd $NETCMD_CASE regression" "see $TMPDIR/gate-netcmd-$NETCMD_CASE.txt"
done
}

job_acl_metadata(){
if [ "$ORACLE_OK" = 1 ]; then
  row_begin "generated Redis 7.4 ACL categories"
  python3 tools/gen_acl_categories.py --redis-root "$REDIS74_ROOT" \
      --check src/cmd/acl_categories_generated.h \
      && ok "generated Redis 7.4 ACL categories" || bad "generated Redis 7.4 ACL categories"
else
  bad "generated Redis 7.4 ACL categories" "oracle source tree missing at $REDIS74_ROOT"
fi
}

job_boot_grammar(){
row_begin "reject --mode (flag deleted)"
reject_boot --mode 3s      2>&1 | grep -q "unknown" && ok "reject --mode (flag deleted)" || bad "reject --mode (flag deleted)"
row_begin "reject --spread"
reject_boot --spread 4:4   2>&1 | grep -q "unknown"  && ok "reject --spread"    || bad "reject --spread"
row_begin "reject --nodes"
reject_boot --nodes 2      2>&1 | grep -q "unknown"  && ok "reject --nodes"     || bad "reject --nodes"
row_begin "reject 3-part ratio"
reject_boot --ratio 4:4:2  2>&1 | grep -q "deleted"  && ok "reject 3-part ratio"|| bad "reject 3-part ratio"
row_begin "reject missing conf"
reject_boot /nonexistent-conf 2>&1 | grep -q "cannot open" && ok "reject missing conf" || bad "reject missing conf"
printf 'florb 1\n' > $TMPDIR/gate-bad.conf
row_begin "reject bad conf key"
reject_boot $TMPDIR/gate-bad.conf 2>&1 | grep -q "unknown argument" && ok "reject bad conf key" || bad "reject bad conf key"
printf 'aclfile %s\nuser alice on nopass ~* &* +@all\n' "$TMPDIR/gate-users.acl" > $TMPDIR/gate-acl-mixed.conf
row_begin "reject aclfile + conf user lines"
reject_boot $TMPDIR/gate-acl-mixed.conf 2>&1 | grep -q \
    "Configuring Redis with users defined in redis.conf and at the same setting an ACL file path is invalid" \
    && ok "reject aclfile + conf user lines" || bad "reject aclfile + conf user lines"
}

job_cmd_metadata(){
# A registered command with no generated metadata row makes command_metadata_init fail, and the
# server then refuses to boot at all -- every row below goes red at once with no indication which
# command is at fault. Static, so it fires before any server starts.
row_begin "cmdmeta covers every registered command"
py tests/cmdmeta_coverage.py >$TMPDIR/gate-cmdmeta-coverage.txt 2>&1 \
    && ok "cmdmeta covers every registered command" \
    || bad "cmdmeta covers every registered command" "see $TMPDIR/gate-cmdmeta-coverage.txt"
}

job_wait_units(){
# MERGEWAITS.md: six rows, all BEFORE the quick-tier exit. Build/boot failure belongs to its
# dependent row, so it cannot change the count. The retirement row intentionally includes lazy
# expiry: cx-waits alone still fails that broader no-quiescence-wait law. Never skip/xfail it.
row_begin "waits config publication + admission unit"
unit_ready waits-unit \
    && taskset -c "$CORES" ./build/waits-unit >>$TMPDIR/gate-waits-unit.txt 2>&1 \
    && tsan_unit "$WAITS_TSAN" waits-unit-tsan "waits unit: PASS" \
    && ok "waits config publication + admission unit" \
    || bad "waits config publication + admission unit" "see $TMPDIR/gate-waits-unit.txt, $TMPDIR/tsan-waits-unit-tsan.log, and $RUN_DIR/jobs/waits_tsan_build/build.log"
row_begin "reads never wait for retirement quiescence"
unit_ready rehash-waits-unit \
    && taskset -c "$CORES" ./build/rehash-waits-unit retirement \
        >>$TMPDIR/gate-rehash-waits-unit.txt 2>&1 \
    && ok "reads never wait for retirement quiescence" \
    || bad "reads never wait for retirement quiescence" "see $TMPDIR/gate-rehash-waits-unit.txt"
}

job_readonly(){
for WAIT_MODE in split fused; do
743:FEATURE_BATTERIES="s6 multi_exec blocking blockmulti stream streamgroups pubsub lua_scripting scriptsurf limits resp3 bitfield dumprestore zsetops geo climon climon2 tracking hexpire servertail lcs concur edgeproto edgeenc edgetime arity contarity cmdgap aclsel expwide infofix pushtear netcmd"
971:              core_units atomic_units netcmd_units boot_grammar wait_units readonly
1319:job_netcmd_units(){
1323:row_begin "netcmd regression build"
1324:unit_ready netcmd-unit \
1325:    && ok "netcmd regression build" || bad "netcmd regression build" "see $RUN_DIR/jobs/production_units/build.log"
1327:  row_begin "netcmd $NETCMD_CASE regression"
1328:  taskset -c "$CORES" ./build/netcmd-unit "$NETCMD_CASE" >$TMPDIR/gate-netcmd-$NETCMD_CASE.txt 2>&1 \
1329:      && ok "netcmd $NETCMD_CASE regression" \
1330:      || bad "netcmd $NETCMD_CASE regression" "see $TMPDIR/gate-netcmd-$NETCMD_CASE.txt"
2548:      build/core-concurrency-unit build/atomic-survivors-unit build/netcmd-unit \
2552:  for target in core-concurrency-unit atomic-survivors-unit netcmd-unit waits-unit rehash-waits-unit; do
2578:    atomic_units|netcmd_units) echo production_units;;
2647:collect_job netcmd_units
// pubsub.inc -- IO-owned Redis pub/sub implementation.
//
// This file is intentionally included inside IoLoop's private section.  Pub/sub needs the loop's
// ring, active-set and send engine, but is not a new translation unit and exposes no path from an
// executor to connection state.  Channel indexes below are touched only by their home IO thread.

    enum class PubSubPendingKind : uint8_t { Modify, Publish, Channels, Numsub, Numpat, Reset };
    enum class PubSubStartResult : uint8_t { Async, Sync };

    // Per destination IO thread, everything this home resolved during ONE pass.  Filled by
    // pubsub_home_publish, emptied once per pass by pubsub_pass_flush.  Coalescing here is what
    // turns a 64-deep pipelined publisher from 64 posts (and 64 sends per subscriber) into one.
    struct PubSubOutbox {
        std::vector<PubSubDelivery> deliveries;
        std::vector<PubSubResult> results;
    };

    struct PubSubRef {
        uint32_t io = 0;
        uint64_t conn = 0;
        bool operator==(const PubSubRef& other) const {
            return io == other.io && conn == other.conn;
        }
    };

    struct PubSubPatternRef {
        std::string pattern;
        PubSubRef ref;
    };

    struct PubSubLocalConn {
        Client* client = nullptr;
        std::unordered_set<std::string> channels;
        std::unordered_set<std::string> patterns;
        std::unordered_set<std::string> shard_channels;
        uint32_t pending = 0;
        uint32_t cleanup_remaining = 0;
        bool cleanup_started = false;
        bool cleanup_done = false;
    };

    struct PubSubPending {
        PubSubPendingKind kind = PubSubPendingKind::Modify;
        uint64_t op_id = 0;
        uint32_t remaining = 0;
        bool pattern = false;
        bool shard = false;
        bool subscribe = false;
        std::vector<std::string> items;
        std::vector<int8_t> changes;
        std::vector<uint64_t> counts;
        std::vector<std::string> channels;
        uint64_t count = 0;
        std::string deferred;
    };

    static std::string pubsub_string(Slice value) {
        return std::string(value.p, value.n);
    }

    PubSubEvent* pubsub_new_event(PubSubEventKind kind) {
        PubSubEvent* event = new PubSubEvent;
        event->kind = kind;
        srv_->pubsub_event_created();
        return event;
    }

    void pubsub_delete_event(PubSubEvent* event) {
        // A batch that never reached its destination (shutdown) still owns one blob reference per
        // undelivered item.  Releasing here is what keeps the blob gauge honest on every path.
        for (PubSubDelivery& item : event->deliveries) pubsub_blob_unref(item.blob);
        delete event;
        srv_->pubsub_event_retired();
    }

    // ---- encode-once delivery blobs --------------------------------------------------------------
    PubSubBlob* pubsub_blob_new(const std::string& channel, const std::string& message, bool shard) {
        PubSubBlob* blob = new PubSubBlob;
        blob->refs.store(1, std::memory_order_relaxed);   // the builder's own reference
        blob->shard = shard;
        SmallBuf<256> frame;
        reply_array_header(frame, 3);
        if (shard) reply_bulk(frame, Slice("smessage", 8));
        else reply_bulk(frame, Slice("message", 7));
        blob->body_off = static_cast<uint32_t>(frame.size());
        reply_bulk(frame, Slice(channel.data(), channel.size()));
        reply_bulk(frame, Slice(message.data(), message.size()));
        blob->frame.assign(frame.data(), frame.size());
        srv_->pubsub_blob_created();
        return blob;
    }

    void pubsub_blob_unref(PubSubBlob* blob) {
        if (blob->refs.fetch_sub(1, std::memory_order_acq_rel) != 1) return;
        delete blob;
        srv_->pubsub_blob_retired();
    }

    void pubsub_post(uint32_t target_io, PubSubEvent* event) {
        if (target_io == self_->id()) {
            pubsub_local_events_.push_back(event);
            pubsub_pass_pending_ = true;
            return;
        }
        ThreadCtx& target = srv_->thread(target_io);
        if (!target.post_pubsub_event(event)) return;

        // One nullptr marker wakes one whole inbox burst. This uses the established IO-to-IO
        // client channel, including its notify-mask/park protocol. The producer channel is an IO
        // channel, so ordinary executor completion traffic cannot fill this SPSC lane.
        while (!target.post_client(self_->id(), nullptr, ring_, self_->sig()))
            __builtin_ia32_pause();
    }

    uint32_t pubsub_home_for(Slice channel) const {
        const auto& ios = srv_->placement().ifid_threads();
        const uint64_t hash = FlatStore::hash_key(channel);
        return ios[hash % ios.size()];
    }

    uint32_t pubsub_home_for(const std::string& channel) const {
        return pubsub_home_for(Slice(channel.data(), channel.size()));
    }

    static bool pubsub_has_ref(const std::vector<PubSubRef>& refs, const PubSubRef& wanted) {
        return std::find(refs.begin(), refs.end(), wanted) != refs.end();
    }

    bool pubsub_home_add_channel(const std::string& channel, const PubSubRef& ref, bool shard) {
        auto& index = shard ? pubsub_shard_channels_ : pubsub_channels_;
        auto [it, inserted] = index.try_emplace(channel);
        std::vector<PubSubRef>& refs = it->second;
        if (pubsub_has_ref(refs, ref)) return false;
        if (inserted || refs.empty()) srv_->pubsub_active_channel_added(shard);
        refs.push_back(ref);
        srv_->pubsub_home_entry_added();
        return true;
    }

    bool pubsub_home_remove_channel(const std::string& channel, const PubSubRef& ref, bool shard) {
        auto& index = shard ? pubsub_shard_channels_ : pubsub_channels_;
        auto it = index.find(channel);
        if (it == index.end()) return false;
        std::vector<PubSubRef>& refs = it->second;
        auto found = std::find(refs.begin(), refs.end(), ref);
349:    uint32_t last_interaction_s() const { return last_interaction_s_; }
350:    void set_last_interaction_s(uint32_t value) { last_interaction_s_ = value; }
699:    void watch_ref() { watched_refs_.fetch_add(1, std::memory_order_relaxed); }
701:        if (watched_refs_.fetch_sub(1, std::memory_order_acq_rel) == 0) std::abort();
716:               watched_refs_.load(std::memory_order_acquire) == 0;
723:               watched_refs_.load(std::memory_order_acquire) == 0 &&
781:    uint32_t  last_interaction_s_ = 0; // monotonic whole seconds; occupies the rbuf_ alignment hole
854:    std::atomic<uint32_t> watched_refs_{0};                    // 1952
#include "../cmd/auth.h"
#include "../cmd/acl.h"
#include "../cmd/multi.h"
#include "../cmd/notify.h"
#include "../cmd/server_tail.h"
#include "../cmd/xshard.h"
#include "../snapshot/snapshot.h"
#include "../persist/aof.h"

namespace tomo {

inline constexpr uint32_t kRecvChunk = 16 * 1024;

// IO and EX responsibilities compose on one physical thread in fused mode:
//
//   io    IoLoop    recv+parse+retire+send; owns the whole client
//   ex    ExLoop    execute+notify; never sends

class IoLoop {
    friend struct CoreConcurrencyTest;
public:
    WbEngine& engine() { return wb_; }
    uint32_t reap_atomic_deferred() {
        return scatter_pool_.reap_deferred() + multi_owner_reap_entry(*this);
    }

    // ONE LISTENING SOCKET PER IO THREAD, via SO_REUSEPORT.
    //
    // Sharing a single listen fd across io threads does NOT distribute connections: every thread
    // arms a multishot accept on it and the kernel satisfies them all from one ring. Measured
    // consequence with 6 io threads and 577 connections — t5 took every single one and t0..t4 sat
    // idle for the entire run, so the server was really running on one io thread. It looked like a
    // latency problem (uniform ~3.5 ms at p1) and was actually a distribution problem.
    //
    // With SO_REUSEPORT the kernel hashes each incoming connection to one of the listening sockets,
    // which spreads them across threads without any userspace handoff. Note this is safe WITHIN one
    // process; two SERVER PROCESSES sharing a port is the failure mode that once faked data loss,
    // so a boot must still verify nothing else holds the port.
    bool init(Server* srv, ThreadCtx* self, const char* addr, uint16_t port,
              int unix_listen_fd = -1, const TlsContext* tls_context = nullptr,
              bool dormant = false) {
        srv_ = srv; self_ = self;
        (void)addr;
        configured_port_ = port;
        tls_context_ = tls_context;
        unix_listen_fd_ = unix_listen_fd;
        epoll_ = srv_->cfg().net_io == NetIoEngine::Epoll;
        targeted_ifid_ = srv_->cfg().thread_mode == ThreadMode::Fused &&
                         srv_->cfg().overlap != 0;
        age_sample_rate_cached_ = srv_->effective_age_sample_rate();
        age_signals_armed_ = age_sample_rate_cached_ != 0;
        client_lb_signal_armed_ = srv_->client_lb_signals_enabled();
        lb_controller_armed_ = srv_->lb_controller_enabled();
        if (!ring_.init(4096)) return false;
        if (epoll_ && !init_epoll()) return false;
        wb_.bind(&ring_, this, [](void* ctx, int32_t shard, const char* ptr) {

exec
/bin/bash -lc "rg -n 'void close_client|close_client\\(|pubsub_account_local_change|pubsub_dispatch|pubsub_begin|void enqueue_serve|void mark_active' src/core/io_loop.h src/core/pubsub.inc && sed -n '755,825p' src/core/pubsub.inc && sed -n '2195,2237p' src/core/server.h && rg -n 'add_client|remove_client|clients\\(' src/core/thread.h" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
src/core/pubsub.inc:271:    void pubsub_begin_rehome_epoch(uint64_t epoch) {
src/core/pubsub.inc:530:                    if (event.op_id) pubsub_begin_rehome_epoch(event.op_id);
src/core/pubsub.inc:646:    void pubsub_account_local_change(PubSubLocalConn& local, bool pattern, bool shard,
src/core/pubsub.inc:729:                    pubsub_account_local_change(
src/core/pubsub.inc:880:        for (Client* client : targets) close_client(client);
src/core/pubsub.inc:1014:        pubsub_begin_rehome_epoch(epoch);
src/core/pubsub.inc:1057:    __attribute__((noinline)) PubSubStartResult pubsub_begin_pending(
src/core/pubsub.inc:1145:        return pubsub_begin_pending(client, std::move(pending), events);
src/core/pubsub.inc:1222:        return pubsub_begin_pending(client, std::move(pending), events);
src/core/pubsub.inc:1248:        return pubsub_begin_pending(client, std::move(pending), events);
src/core/pubsub.inc:1262:        return pubsub_begin_pending(client, std::move(pending), events);
src/core/pubsub.inc:1275:        return pubsub_begin_pending(client, std::move(pending), events);
src/core/io_loop.h:1229:            close_client(c);
src/core/io_loop.h:1240:        if (!tls) { close_client(c); return; }
src/core/io_loop.h:1246:                *c, *tls, cqe->res)) close_client(c);
src/core/io_loop.h:2292:                close_client(c);
src/core/io_loop.h:2368:                close_client(c);
src/core/io_loop.h:2376:        if (res <= 0) { close_client(c); return; }
src/core/io_loop.h:2418:                close_client(c);
src/core/io_loop.h:2453:                close_client(c, tls->output_pending() || c->send_inflight());
src/core/io_loop.h:2490:                close_client(c, tls->output_pending() || c->send_inflight());
src/core/io_loop.h:2498:                close_client(c, tls->output_pending() || c->send_inflight());
src/core/io_loop.h:2513:        if (!tls) { close_client(c); return; }
src/core/io_loop.h:2517:        if (c->closing() || res < 0) { close_client(c); return; }
src/core/io_loop.h:2527:        if (!tls) { close_client(c); return; }
src/core/io_loop.h:2531:            close_client(c);
src/core/io_loop.h:2537:            close_client(c);
src/core/io_loop.h:4482:        close_client(c, drain_tls_output);
src/core/io_loop.h:4486:    void mark_active(Client* c) {
src/core/io_loop.h:4495:    void mark_active_known(Client* c) {
src/core/io_loop.h:4790:                    close_client(c);
src/core/io_loop.h:4911:                        close_client(client,
src/core/io_loop.h:5074:                            close_client(client,
src/core/io_loop.h:5150:                        close_client(c, tls->output_pending() || c->send_inflight());
src/core/io_loop.h:5420:                    close_client(c);
src/core/io_loop.h:5462:                    if (tls->failed()) close_client(c, tls->output_pending() || c->send_inflight());
src/core/io_loop.h:5488:                    if (tls->failed()) close_client(c, tls->output_pending() || c->send_inflight());
src/core/io_loop.h:5529:                    if (tls->failed()) close_client(c, tls->output_pending() || c->send_inflight());
src/core/io_loop.h:5689:                // through mark_closing() rather than close_client() (the reply has to go out
src/core/io_loop.h:5787:                else { c->set_in_active(false); active_.erase_at(idx); close_client(c); }
src/core/io_loop.h:5857:                    if (tls->failed()) close_client(c, tls->output_pending() || c->send_inflight());
src/core/io_loop.h:5875:    void enqueue_serve(Client* c) {
src/core/io_loop.h:6034:        close_client(c);
src/core/io_loop.h:6065:                close_client(c);
src/core/io_loop.h:6114:    void close_client(Client* c, bool drain_tls_output = false) {
                    reply_int(sink, static_cast<long long>(pending.counts[i]));
                }
                break;
            case PubSubPendingKind::Numpat:
                reply_int(sink, static_cast<long long>(pending.count));
                break;
            case PubSubPendingKind::Reset:
                if (!pending.deferred.empty())
                    sink.append(pending.deferred.data(), pending.deferred.size());
                pubsub_clear_local_subscriptions(local);
                command_set_local_context(client, self_);
                op.spec->handler(srv_->shard(0), op);
                command_set_local_context(nullptr, nullptr);
                break;
        }

        if (pending.kind != PubSubPendingKind::Modify && pending.kind != PubSubPendingKind::Reset &&
            !pending.deferred.empty())
            sink.append(pending.deferred.data(), pending.deferred.size());
        op.state.store(OpState::Done, std::memory_order_release);
        enqueue_serve(client);
        mark_active(client);
        if (!local.pending) std::abort();
        local.pending--;
        srv_->pubsub_pending_finished();
        pubsub_pending_.erase(pending_it);
        if (!client->closing() && !local.pending && local.channels.empty() &&
            local.patterns.empty() && local.shard_channels.empty() && !local.cleanup_started)
            pubsub_local_.erase(local_it);
    }

    void pubsub_finish_publish(const PubSubResult& result) {
        auto local_it = pubsub_local_.find(result.conn_id);
        if (local_it == pubsub_local_.end()) return;
        PubSubLocalConn& local = local_it->second;
        Client* client = local.client;
        if (!client || !local.pending) return;

        Op& op = client->rob().at(result.op_id);
        reply_int(op.sink(), static_cast<long long>(result.count));
        op.state.store(OpState::Done, std::memory_order_release);
        enqueue_serve(client);
        mark_active(client);
        local.pending--;
        srv_->pubsub_pending_finished();
        if (!client->closing() && !local.pending && local.channels.empty() &&
            local.patterns.empty() && local.shard_channels.empty() && !local.cleanup_started)
            pubsub_local_.erase(local_it);
    }

    void pubsub_handle_result(PubSubEvent& event) {
        auto pending_it = pubsub_pending_.find(event.conn_id);
        if (pending_it == pubsub_pending_.end() || pending_it->second.op_id != event.op_id) return;
        PubSubPending& pending = pending_it->second;
        switch (event.kind) {
            case PubSubEventKind::ModifyResult:
                for (const PubSubEventItem& item : event.items)
                    if (item.index < pending.changes.size() && pending.changes[item.index] < 0)
                        pending.changes[item.index] = item.changed ? 1 : 0;
                break;
            case PubSubEventKind::ChannelsResult:
                for (const PubSubEventItem& item : event.items)
                    pending.channels.push_back(item.value);
                break;
            case PubSubEventKind::NumsubResult:
                for (const PubSubEventItem& item : event.items)
                    if (item.index < pending.counts.size()) pending.counts[item.index] = item.count;
                break;
            case PubSubEventKind::NumpatResult:
                pending.count = event.count;
                break;
    uint64_t live_clients() const { return live_clients_.load(std::memory_order_relaxed); }
    void client_accepted() { live_clients_.fetch_add(1, std::memory_order_relaxed); }
    void client_released() {
        if (live_clients_.fetch_sub(1, std::memory_order_relaxed) == 0) std::abort();
    }
    void note_rejected_conn() { rejected_conns_.fetch_add(1, std::memory_order_relaxed); }
    uint64_t rejected_conns() const { return rejected_conns_.load(std::memory_order_relaxed); }

    uint32_t tcp_keepalive() const {
        return live_tcp_keepalive_.load(std::memory_order_relaxed);
    }
    void set_tcp_keepalive(uint32_t value) {
        live_tcp_keepalive_.store(value, std::memory_order_relaxed);
    }
    uint32_t timeout() const { return live_timeout_.load(std::memory_order_relaxed); }
    bool client_cron_armed() const {
        return client_cron_armed_.load(std::memory_order_relaxed);
    }
    const std::atomic<bool>* client_obuf_armed_ptr() const {
        return &client_obuf_armed_;
    }
    bool client_obuf_armed() const {
        return client_obuf_armed_.load(std::memory_order_relaxed);
    }
    void set_timeout(uint32_t value) {
        const uint64_t version = begin_live_config_update();
        live_timeout_.store(value, std::memory_order_relaxed);
        refresh_client_cron_armed();
        end_live_config_update(version);
    }

    ClientLimitsConfigSnapshot client_limits_snapshot(uint32_t reader_tid) const {
        return live_config_mailboxes_[reader_tid].read(live_config_version_).clients;
    }
    void set_client_output_buffer_limits(const ClientOutputBufferLimits& limits) {
        const uint64_t version = begin_live_config_update();
        store_client_output_buffer_limits(limits);
        refresh_client_cron_armed();
        end_live_config_update(version);
    }
    // ---- Lane F: the single CLIENT/MONITOR/TRACKING armed word ---------------------------------
    // Every feature this lane adds is OFF by default and must cost nothing while off.  Instead of
    // giving each one its own hot-path test, they share ONE word that the IO loop caches per
766:    uint32_t drain_clients(Fn&& fn) {
827:    std::vector<Client*>& clients() { return clients_; }   // Ifid role
829:    void add_client(Client* client) {
833:    bool remove_client(Client* client) {

exec
/bin/bash -lc "sed -n '850,955p' src/core/pubsub.inc && sed -n '1050,1155p' src/core/pubsub.inc && sed -n '3150,3198p' src/core/server.h && sed -n '3270,3286p' src/core/server.h && sed -n '704,728p' src/net/conn.h && rg -n 'mark_resp3|set_resp3|resp3\\(' src/exec/op.h" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
        const bool kill_all = event.kind == PubSubEventKind::AclUserDeleted;
        std::vector<Client*> targets;
        for (Client* client : self_->clients()) {
            if (!client || client->dead() || client->closing() ||
                client->acl_user_idx() != event.acl_user_index) continue;
            bool subscribed = false;
            bool violating = kill_all;
            auto found = pubsub_local_.find(client->id());
            if (found != pubsub_local_.end()) {
                const PubSubLocalConn& local = found->second;
                subscribed = pubsub_total_subscription_count(local) != 0;
                if (!kill_all && permissions) {
                    for (const std::string& pattern : local.patterns) {
                        const Slice value(pattern.data(), static_cast<uint32_t>(pattern.size()));
                        violating |= !acl_channel_allowed_any(*permissions, value, true);
                    }
                    for (const std::string& channel : local.channels) {
                        const Slice value(channel.data(), static_cast<uint32_t>(channel.size()));
                        violating |= !acl_channel_allowed_any(*permissions, value, false);
                    }
                    for (const std::string& channel : local.shard_channels) {
                        const Slice value(channel.data(), static_cast<uint32_t>(channel.size()));
                        violating |= !acl_channel_allowed_any(*permissions, value, false);
                    }
                }
            }
            if (!violating) continue;
            targets.push_back(client);
            if (subscribed) srv_->acl_pubsub_client_killed();
        }
        for (Client* client : targets) close_client(client);
        if (kill_all) srv_->acl_kill_broadcast_finished();
    }

    void acl_broadcast_user_change(uint32_t user_index, const AclPerm* permissions,
                                   bool deleted) {
        if (deleted)
            srv_->acl_kill_broadcast_started(srv_->placement().ifid_threads().size());
        for (uint32_t io : srv_->placement().ifid_threads()) {
            PubSubEvent* event = pubsub_new_event(
                deleted ? PubSubEventKind::AclUserDeleted
                        : PubSubEventKind::AclPermissionsChanged);
            event->acl_user_index = user_index;
            event->acl_permissions = permissions;
            pubsub_post(io, event);
        }
        // Remote IOs are woken through their client-in channel. The local event has no wake
        // marker, so consume it before returning or a same-IO client can retain revoked access.
        pubsub_drain_events();
    }

    void pubsub_handle_event(PubSubEvent& event) {
        if (climon_handle_event(event)) return;
        switch (event.kind) {
            case PubSubEventKind::NotificationEnqueue:
                pubsub_notification_enqueue(std::move(event.notification));
                break;
            case PubSubEventKind::NotificationContinue:
                pubsub_notification_continue(event);
                break;
            case PubSubEventKind::ModifyRequest:
            case PubSubEventKind::PublishRequest:
            case PubSubEventKind::NotificationRequest:
            case PubSubEventKind::ChannelsRequest:
            case PubSubEventKind::NumsubRequest:
            case PubSubEventKind::NumpatRequest:
            case PubSubEventKind::ResetRequest:
            case PubSubEventKind::CleanupRequest:
                pubsub_handle_home_request(event);
                break;
            case PubSubEventKind::AclPermissionsChanged:
            case PubSubEventKind::AclUserDeleted:
                pubsub_handle_acl_event(event);
                break;
            case PubSubEventKind::DeliveryBatch:
                pubsub_handle_delivery_batch(event);
                break;
            case PubSubEventKind::CleanupResult:
                pubsub_handle_cleanup_result(event);
                break;
            default:
                pubsub_handle_result(event);
                break;
        }
    }

    uint32_t pubsub_drain_events() {
        std::deque<PubSubEvent*> events;
        self_->take_pubsub_events(events);
        uint32_t count = 0;
        for (;;) {
            while (!events.empty()) {
                PubSubEvent* event = events.front();
                events.pop_front();
                pubsub_handle_event(*event);
                pubsub_delete_event(event);
                count++;
            }
            if (pubsub_local_events_.empty()) break;
            events.swap(pubsub_local_events_);
        }
        return count;
    }

    // THE pass boundary for pub/sub, called once per IO loop pass from flush_ready behind a single
    // predicted branch. Everything a pass parsed, resolved and owes is settled here in one go:
                        event->items.push_back(PubSubEventItem{0, false, 0, pattern});
                    pubsub_post(io, event);
                }
            }
        }
    }

    __attribute__((noinline)) PubSubStartResult pubsub_begin_pending(
            Client* client, PubSubPending&& pending, std::vector<PubSubEvent*>& events) {
        if (events.empty()) std::abort();
        const uint64_t conn_id = client->id();
        PubSubLocalConn& local = pubsub_track(client);
        local.pending++;
        pending.remaining = events.size();
        const uint64_t op_id = pending.op_id;
        if (!pubsub_pending_.emplace(conn_id, std::move(pending)).second) std::abort();
        srv_->pubsub_pending_started();

        // Publish the ROB slot before any home can answer it. The response event may race all the
        // way back to this IO, but it can never complete an operation absent from dispatch_.
        client->rob().publish();
        // Released by the quiescence backstop in flush_ready: the transition's parked lifetime is
        // its ROB slot, which retires only once every channel home has answered.
        barrier_arm(client, BarrierOwner::PubSub);
        for (PubSubEvent* event : events) {
            event->origin_io = self_->id();
            event->conn_id = conn_id;
            event->op_id = op_id;
        }
        for (PubSubEvent* event : events)
            pubsub_post(event->target_io, event);
        pubsub_drain_events();
        return PubSubStartResult::Async;
    }

    PubSubStartResult pubsub_start_modify(Client* client, Op& op, bool pattern,
                                          bool subscribe, bool shard = false) {
        PubSubPending pending;
        pending.kind = PubSubPendingKind::Modify;
        pending.op_id = client->rob().dispatch_id();
        pending.pattern = pattern;
        pending.shard = shard;
        pending.subscribe = subscribe;

        if (subscribe || op.argc() > 1) {
            pending.items.reserve(op.argc() - 1);
            for (uint32_t i = 1; i < op.argc(); i++) pending.items.push_back(pubsub_string(op.arg(i)));
        } else {
            auto local_it = pubsub_local_.find(client->id());
            if (local_it != pubsub_local_.end()) {
                const auto& values = shard ? local_it->second.shard_channels
                                           : (pattern ? local_it->second.patterns
                                                      : local_it->second.channels);
                pending.items.assign(values.begin(), values.end());
            }
            if (pending.items.empty()) {
                auto sink = op.sink();
                pubsub_append_ack(sink, pattern, shard, false, nullptr,
                    local_it == pubsub_local_.end()
                        ? 0 : (shard ? pubsub_shard_subscription_count(local_it->second)
                                     : pubsub_subscription_count(local_it->second)), op.resp3());
                return PubSubStartResult::Sync;
            }
        }
        pending.changes.assign(pending.items.size(), -1);

        const auto& ios = srv_->placement().ifid_threads();
        std::vector<PubSubEvent*> events;
        if (pattern) {
            events.reserve(ios.size());
            for (uint32_t io : ios) {
                PubSubEvent* event = pubsub_new_event(PubSubEventKind::ModifyRequest);
                event->pattern = true;
                event->shard = false;
                event->subscribe = subscribe;
                event->target_io = io;
                for (uint32_t i = 0; i < pending.items.size(); i++)
                    event->items.push_back(PubSubEventItem{i, false, 0, pending.items[i]});
                events.push_back(event);
            }
        } else {
            std::unordered_map<uint32_t, PubSubEvent*> homes;
            for (uint32_t i = 0; i < pending.items.size(); i++) {
                const uint32_t home = pubsub_home_for(pending.items[i]);
                PubSubEvent*& event = homes[home];
                if (!event) {
                    event = pubsub_new_event(PubSubEventKind::ModifyRequest);
                    event->shard = shard;
                    event->subscribe = subscribe;
                    event->target_io = home;
                    events.push_back(event);
                }
                event->items.push_back(PubSubEventItem{i, false, 0, pending.items[i]});
            }
        }
        return pubsub_begin_pending(client, std::move(pending), events);
    }

    PubSubStartResult pubsub_start_publish(Client* client, Op& op, bool shard = false) {
        const bool subscribers = shard ? srv_->pubsub_any_shard_subscribers()
                                       : srv_->pubsub_any_subscribers();
        if (!subscribers) {
            reply_int(op.sink(), 0);
            return PubSubStartResult::Sync;
        }
        std::string channel = pubsub_string(op.arg(1));
                    current, current + count, std::memory_order_relaxed,
                    std::memory_order_relaxed)) return true;
        }
        return false;
    }
    void pubsub_notification_retire(uint64_t count) {
        const uint64_t previous = pubsub_inflight_.fetch_sub(count, std::memory_order_relaxed);
        if (previous < count) std::abort();
    }
    void pubsub_pending_started() { pubsub_pending_.fetch_add(1, std::memory_order_relaxed); }
    void pubsub_pending_finished() {
        if (pubsub_pending_.fetch_sub(1, std::memory_order_relaxed) == 0) std::abort();
    }
    void pubsub_home_entry_added() { pubsub_home_entries_.fetch_add(1, std::memory_order_relaxed); }
    void pubsub_home_entry_removed() {
        if (pubsub_home_entries_.fetch_sub(1, std::memory_order_relaxed) == 0) std::abort();
    }
    void pubsub_active_channel_added(bool shard = false) {
        (shard ? pubsub_shard_channels_ : pubsub_active_channels_)
            .fetch_add(1, std::memory_order_relaxed);
    }
    void pubsub_active_channel_removed(bool shard = false) {
        auto& value = shard ? pubsub_shard_channels_ : pubsub_active_channels_;
        if (value.fetch_sub(1, std::memory_order_relaxed) == 0) std::abort();
    }
    void pubsub_subscription_added(bool pattern, bool shard = false) {
        (shard ? pubsub_shard_subscriptions_
               : (pattern ? pubsub_pattern_subscriptions_ : pubsub_subscriptions_))
            .fetch_add(1, std::memory_order_relaxed);
    }
    void pubsub_subscription_removed(bool pattern, bool shard = false) {
        auto& value = shard ? pubsub_shard_subscriptions_
                            : (pattern ? pubsub_pattern_subscriptions_ : pubsub_subscriptions_);
        if (value.fetch_sub(1, std::memory_order_relaxed) == 0) std::abort();
    }
    uint64_t pubsub_inflight() const { return pubsub_inflight_.load(std::memory_order_relaxed); }
    uint64_t pubsub_pending() const { return pubsub_pending_.load(std::memory_order_relaxed); }
    uint64_t pubsub_home_entries() const {
        return pubsub_home_entries_.load(std::memory_order_relaxed);
    }
    uint64_t pubsub_active_channels() const {
        return pubsub_active_channels_.load(std::memory_order_relaxed);
    }
    uint64_t pubsub_subscriptions() const {
        return pubsub_subscriptions_.load(std::memory_order_relaxed);
    }
    uint64_t pubsub_pattern_subscriptions() const {
        return pubsub_pattern_subscriptions_.load(std::memory_order_relaxed);
    }
    }

    void refresh_client_cron_armed() {
        const bool normal = live_obuf_normal_hard_.load(std::memory_order_relaxed) != 0 ||
                            live_obuf_normal_soft_.load(std::memory_order_relaxed) != 0;
        const bool pubsub = live_obuf_pubsub_hard_.load(std::memory_order_relaxed) != 0 ||
                            live_obuf_pubsub_soft_.load(std::memory_order_relaxed) != 0;
        client_obuf_armed_.store(normal || pubsub, std::memory_order_release);
        client_cron_armed_.store(live_timeout_.load(std::memory_order_relaxed) != 0 ||
                                 normal || pubsub, std::memory_order_release);
    }

    // Only boot or the serialized CONFIG writer reads these mutable fields as a group. Readers
    // consume immutable, committed mailbox copies and never collect/revalidate these atomics.
    LiveConfigValues capture_live_config(uint64_t version) const {
        LiveConfigValues values;
        auto& snapshot = values.live;
    // A connection may be freed only when (a) nothing is in flight through its ROB AND (b) no
    // Client* naming it can still surface from a notification channel. (b) is what the ASAN
    // use-after-free proved: a worker posts the client for retirement, io serves it through
    // flush_ready instead, the ROB quiesces, the peer disconnects, close frees the client -- and
    // io then drains its channel into freed memory. The claim flag covers every CLAIMED post: it is
    // set before posting and cleared only when the consumer takes the entry, and after quiescence
    // no new claim can ever be made (no op will complete again), so requiring it false here is
    // race-free.
    bool safe_to_release() {
        return rob_.quiesced() &&
               !recv_armed_ && !send_inflight_ &&        // the KERNEL holds no pointer into us
               !retire_queued_.load(std::memory_order_acquire) &&
               watched_refs_.load(std::memory_order_acquire) == 0;
    }
    bool migration_protocol_idle() const {
        // Ordinary unread input and admission/FLIP backpressure move with the Client.
        return rob_.quiesced() &&
               !send_inflight_ && !serve_pending_ &&
               !retire_queued_.load(std::memory_order_acquire) &&
               watched_refs_.load(std::memory_order_acquire) == 0 &&
               barrier_owners_ == 0 && atomic_groups_io_ == 0 && !blocked() &&
               multi_session_ == nullptr && nothing_to_write();
    }
    bool flip_drain_idle() const {
        // Global dispatch is paused, but connections which remain on this IO may retain durable
187:    void mark_resp3() { route_flags_ |= kResp3; }
188:    bool resp3() const { return route_flags_ & kResp3; }

exec
/bin/bash -lc "sed -n '6110,6250p' src/core/io_loop.h && sed -n '4480,4515p' src/core/io_loop.h && sed -n '5868,5898p' src/core/io_loop.h && sed -n '820,850p' src/core/thread.h && sed -n '640,662p' src/core/pubsub.inc && rg -n 'void pubsub_close|bool pubsub_close|close_client_finish|finish_close|~IoLoop|~ThreadCtx|~Server' src/core/io_loop.h src/core/pubsub.inc src/core/server.h src/core/thread.h" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
        }
        notify_config_version_ = snapshot.version;
    }

    void close_client(Client* c, bool drain_tls_output = false) {
        // IDEMPOTENT, and that is load-bearing: an abrupt disconnect can close a conn twice --
        // once when the recv fails and again when the in-flight reply's send CQE comes back
        // failed. The second call found the client already parked on the deferred-free list and
        // parked it AGAIN: a double delete, one reap later. Caught by the torture battery's RST
        // churn under ASAN; latent since the first teardown path was written.
        if (c->dead()) return;
        if (!c->closing()) {
            c->mark_closing();
            if (deferred_timer_cancel(c)) enqueue_serve(c);
            if (c->blocked() && blocking_cancel_client(*srv_, *self_, ring_, *c))
                enqueue_serve(c);
            TlsConn* slot_tls = tls_slot_conn(c);
            if (slot_tls && slot_tls->ktls() && !c->send_inflight() &&
                !slot_tls->shutdown_started()) {
                // recv(EIO) is how kTLS reports peer close_notify. The first SSL_shutdown call
                // emits our close_notify through TLS_TX without entering the application path.
                (void)slot_tls->shutdown();
            }
            TlsConn* tls = tls_engine(c);
            if (tls && tls->memory_userspace() && !tls->shutdown_started()) {
                (void)tls->shutdown();
                (void)wb_.pump_tls_any(*c, *tls);
            }
            // Under epoll recv_armed_ records an owed EDGE, not a kernel-held buffer pointer, and
            // a torn-down socket owes nothing. Leaving it set would make safe_to_release() refuse
            // forever and leak the whole Client -- the same ~137KB-per-disconnect shape the retry
            // note below describes, reached by a different route.
            if (epoll_) { c->set_recv_armed(false); c->set_send_inflight(false); }
            (void)wb_.take_send_failure();
            // Break any in-flight recv/send NOW: safe_to_release refuses to free while the kernel
            // holds a buffer pointer (recv_armed / send_inflight), and those only clear when their
            // CQEs come back -- which a half-open peer might never trigger on its own.
            const bool pending_tls_output = tls && (tls->output_pending() || c->send_inflight());
            if (!(drain_tls_output && pending_tls_output)) ::shutdown(c->fd(), SHUT_RDWR);
        }
        multi_close_entry(*this, *c);
        if (TlsConn* tls = tls_engine(c)) {
            if (drain_tls_output && (tls->output_pending() || c->send_inflight())) {
                mark_active(c);
                return;
            }
        }
        // Release only at the quiescence fence: a worker may still hold a Task that resolves through
        // this ROB. Anything else is a use-after-free under pipelining. (The retryable wait paths,
        // with their mark_active leak guard, are below.)
        if (!pubsub_disconnect_ready(c)) { mark_active(c); return; }
        c->set_in_active(false);
        active_.erase(c);
        (void)self_->remove_client(c);
        // THE RETRY IS THE LOAD-BEARING PART of this wait: the client left the active set when it
        // went quiet, so nothing revisits it unless mark_active puts it back -- returning without
        // doing so leaked the entire client (~137KB) per disconnect once. Only a quiesced,
        // claim-free conn may release its slot and die.
        if (!c->safe_to_release() || !client_executor_quiesced(c) ||
            !c->safe_to_release()) { mark_active(c); return; }
        client_work_fences_.erase(c);
        climon_untrack_client(c);
        command_client_disconnected(c);
        self_->release_wb_slot(c->wb_slot());
        c->set_wb_slot(Client::kNoWbSlot);
        wb_.teardown(*c);
        ::close(c->fd());
        srv_->client_released();
        srv_->lb_forget_client(c->id());
        // NOT delete. An ex-side claimed post may still sit un-consumed in our inbound channels
        // naming this client. Every such entry was pushed BEFORE this point, and channels are FIFO
        // with their mask bits set -- so ONE full
        // collect_retire_work pass consumes all of them. Park the corpse for one loop iteration and
        // free it at the top of the one after; the drain lambda skips dead clients.
        c->mark_dead();
        dead_next_.push_back(c);
    }

    // Called only after the connection is ROB-quiescent and no longer dispatching. The
    // acquire on Done precedes this snapshot, so every executor that could still hold
    // this Client published its odd scope before we sample. Wait for EACH such scope
    // to end, without requiring all executors to be idle at the same instant.
    bool client_executor_quiesced(Client* client) const {
        try {
            auto [it, inserted] = client_work_fences_.try_emplace(client);
            ClientWorkFence& fence = it->second;
            const uint64_t dispatch = client->rob().dispatch_id();
            if (inserted || fence.dispatch != dispatch) {
                fence.dispatch = dispatch;
                for (uint32_t tid = 0; tid < srv_->nthreads(); tid++)
                    fence.epochs[tid] = srv_->client_work_epoch(tid);
            }
            bool ready = true;
            for (uint32_t tid = 0; tid < srv_->nthreads(); tid++) {
                // This IO's synchronous fused stack cannot run concurrently with teardown;
                // its existing pipeline/serve fences cover retained local handles.
                if (tid == self_->id() || !(fence.epochs[tid] & 1)) continue;
                if (srv_->client_work_epoch(tid) == fence.epochs[tid]) ready = false;
                else fence.epochs[tid] = 0;
            }
            return ready;
        } catch (const std::bad_alloc&) {
            return false; // Keep the Client and retry; allocation failure cannot waive lifetime.
        }
    }

    // Free everything that has been dead for a full iteration. Called once per loop pass, BEFORE
    // this pass's drains, so a corpse parked in pass N is freed in pass N+2's prologue -- after the
    // whole of pass N+1 (including its channel drains) ran with the corpse still readable.
    void reap_dead() {
        // Hold a corpse while ANY outside reference can still surface: a pending_serve_ FIFO
        // entry (the budget serves 16/pass, so an entry can outlive two prologues -- audit
        // finding), or a kernel CQE not yet reaped (a send pins msghdr/iovecs/BORROWs; a recv
        // pins the buffer and the Client* in its user_data). Two prologues are the minimum grace;
        // these fences extend it exactly as long as a reference exists. teardown() before delete
        // returns any BORROW the close path could not (idempotent: release_all empties the queue).
        size_t keep = 0;
        for (Client* c : dead_ready_) {
            if (c->serve_pending() || c->send_inflight() || c->recv_armed() ||
                client_pipeline_referenced(c)) {
                dead_ready_[keep++] = c;
                continue;
            }
            wb_.teardown(*c);
            release_tls(c);
            delete c;
        }
        dead_ready_.resize(keep);
        dead_ready_.insert(dead_ready_.end(), dead_next_.begin(), dead_next_.end());
        dead_next_.clear();
    }

    Server*    srv_  = nullptr;
    struct ClientWorkFence {
        uint64_t dispatch = 0;
        uint64_t epochs[kMaxThreads] = {};
    };
    ThreadCtx* self_ = nullptr;
    IfidBatch ifid_batch_{};
    WbBatch wb_batch_{};
    IoPipeDepthGate iopipe_depth_gate_{};
    // it empty.
    void epoll_close_now(Client* c, bool drain_tls_output = false) {
        close_client(c, drain_tls_output);
        (void)wb_.take_send_failure();
    }

    void mark_active(Client* c) {
        if (c->dead()) return;               // a corpse from the deferred-free list: entry consumed, nothing to do
        if (targeted_ifid_) enqueue_ifid(c);
        if (c->in_active()) return;          // one load, not a scan of the whole set
        c->set_in_active(true);
        active_.insert(c);
    }

    template <bool TargetedIfid>
    void mark_active_known(Client* c) {
        if (c->dead()) return;
        if constexpr (TargetedIfid)
            if (!c->ifid_pending()) {
                c->set_ifid_pending(true);
                pending_ifid_.push_back(c);
            }
        if (c->in_active()) return;
        c->set_in_active(true);
        active_.insert(c);
    }

    void enqueue_ifid(Client* c) {
        if (!c || c->dead() || c->ifid_pending()) return;
        c->set_ifid_pending(true);
        pending_ifid_.push_back(c);
    }

    void discard_ifid(Client* c) {
        if (!c || !c->ifid_pending()) return;
        for (auto it = pending_ifid_.begin(); it != pending_ifid_.end(); ++it) {
            // per served connection is deliberate: a bit left set would close the NEXT one.
            if constexpr (kEp) if (wb_.take_send_failure()) epoll_close_now(c);
        }
        work += served;
        return work;
    }

    void enqueue_serve(Client* c) {
        if (c->serve_pending()) return;                 // already queued
        c->set_serve_pending(true);
        pending_serve_.push_back(c);
    }

    // IO owns both ROB frontiers, so this 100us signal beat can maintain head_since without a
    // Client field or a per-operation hook. The active set bounds the walk to connections already
    // carrying work. Entries not seen in this beat are erased, which also makes client teardown and
    // pointer reuse harmless without touching either lifecycle hot path.
    void sample_rob_head_age(uint64_t now_us) {
        LoopSignals& sig = self_->sig();
        if (++rob_age_generation_ == 0) {
            rob_head_ages_.clear();
            rob_age_generation_ = 1;
        }
        uint64_t oldest_us = 0;
        bool observed = false;
        for (size_t i = 0; i < active_.size(); i++) {
            Client* client = active_.at(i);
            if (!client || client->dead()) continue;
            const uint64_t head = client->rob().flush_id();
            if (head == client->rob().dispatch_id()) continue;
            auto [it, inserted] = rob_head_ages_.try_emplace(client);
    // The current role-tenure ring peers poke to wake this physical thread. A role edge publishes
    // its already-provisioned opposite ring before that new loop acknowledges ready.
    void  set_ring(Ring* r) { ring_.store(r, std::memory_order_release); }
    Ring* ring() const      { return ring_.load(std::memory_order_acquire); }

    std::vector<Shard*>&  shards()  { return shards_; }    // Ex role
    const std::vector<Shard*>& shards() const { return shards_; }
    std::vector<Client*>& clients() { return clients_; }   // Ifid role
    uint32_t client_count() const { return client_count_.load(std::memory_order_acquire); }
    void add_client(Client* client) {
        clients_.push_back(client);
        client_count_.fetch_add(1, std::memory_order_release);
    }
    bool remove_client(Client* client) {
        auto found = std::find(clients_.begin(), clients_.end(), client);
        if (found == clients_.end()) return false;
        *found = clients_.back();
        clients_.pop_back();
        if (client_count_.fetch_sub(1, std::memory_order_release) == 0) std::abort();
        return true;
    }

    // The single reporting surface. Every loop fills the same fields in the same units, so a
    // controller compares like with like — the failure mode behind every balancer defect in the
    // fork was comparing two quantities that were not the same kind of thing.
    LoopSignals& sig() { return sig_; }

    // IO-only INFO surface. Published for each IO tenure when IoLoop binds its send engine; INFO then
    // sums the engine's single-writer counters with the same exceptional cross-thread read shape
    // used for sig(). Executor threads leave this null because they do not send.
    void set_wb_engine(WbEngine* engine) {
            }
            default:
                std::abort();
        }
    }

    void pubsub_account_local_change(PubSubLocalConn& local, bool pattern, bool shard,
                                     bool subscribe, const std::string& value) {
        auto& values = shard ? local.shard_channels : (pattern ? local.patterns : local.channels);
        if (subscribe) {
            if (values.insert(value).second) srv_->pubsub_subscription_added(pattern, shard);
        } else {
            if (values.erase(value)) srv_->pubsub_subscription_removed(pattern, shard);
        }
        if (local.client)
            command_client_set_subscriptions(
                local.client, static_cast<uint32_t>(local.channels.size()),
                static_cast<uint32_t>(local.patterns.size()),
                static_cast<uint32_t>(local.shard_channels.size()));
    }

    static uint64_t pubsub_subscription_count(const PubSubLocalConn& local) {
        return local.channels.size() + local.patterns.size();
src/core/io_loop.h:142:    ~IoLoop() {

exec
/bin/bash -lc "rg -n 'void barrier_arm|void multi_close_entry|pubsub_track\\(' src/core/io_loop.h src/core/multi* src/core/pubsub.inc && sed -n '3345,3385p' src/core/server.h && sed -n '1,30p' src/cmd/xshard.cc && sed -n '350,366p' src/net/conn.h" in /home/user/Projects/cx-deadconf-fix
 exited 2 in 0ms:
rg: src/core/multi*: No such file or directory (os error 2)
src/core/pubsub.inc:970:    PubSubLocalConn& pubsub_track(Client* client) {
src/core/pubsub.inc:1061:        PubSubLocalConn& local = pubsub_track(client);
src/core/pubsub.inc:1168:        PubSubLocalConn& local = pubsub_track(client);
src/core/io_loop.h:498:    friend void multi_close_entry(IoLoop&, Client&);
src/core/io_loop.h:4440:    void barrier_arm(Client* c, BarrierOwner who) {

exec
/bin/bash -lc "rg -n 'pubsub_disconnect_ready|pubsub_start_cleanup|pubsub_handle_cleanup_result|PubSubLocalConn& pubsub_track' src/core/pubsub.inc && sed -n '1340,1445p' src/core/pubsub.inc && sed -n '140,160p' src/core/io_loop.h && sed -n '275,345p' src/core/pubsub.inc && sed -n '80,100p' src/cmd/xshard.cc" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
835:    void pubsub_handle_cleanup_result(PubSubEvent& event) {
928:                pubsub_handle_cleanup_result(event);
970:    PubSubLocalConn& pubsub_track(Client* client) {
1395:    bool pubsub_disconnect_ready(Client* client) {
        if (op.arg(1).eq_icase("help")) {
            if (op.argc() != 2) {
                pubsub_reply_bad_arity(op, "help");
                return PubSubStartResult::Sync;
            }
            return pubsub_start_help(op);
        }
        if (op.arg(1).eq_icase("channels")) return pubsub_start_channels(client, op);
        if (op.arg(1).eq_icase("numsub")) return pubsub_start_numsub(client, op);
        if (op.arg(1).eq_icase("numpat")) return pubsub_start_numpat(client, op);
        if (op.arg(1).eq_icase("shardchannels")) return pubsub_start_channels(client, op, true);
        if (op.arg(1).eq_icase("shardnumsub")) return pubsub_start_numsub(client, op, true);
        pubsub_reply_bad_subcommand(op, true);
        return PubSubStartResult::Sync;
    }

    void pubsub_reply_ping(Op& op) {
        auto sink = op.sink();
        reply_array_header(sink, 2);
        reply_bulk(sink, Slice("pong", 4));
        if (op.argc() == 2) reply_bulk(sink, op.arg(1));
        else reply_bulk(sink, Slice("", 0));
    }

    void pubsub_reply_restricted(Op& op) {
        std::string command(op.cmd_name().p, op.cmd_name().n);
        for (char& ch : command)
            if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch + ('a' - 'A'));
        if (op.cmd_name().eq_icase("pubsub")) {
            const bool known = op.arg(1).eq_icase("help") || op.arg(1).eq_icase("channels") ||
                               op.arg(1).eq_icase("numsub") || op.arg(1).eq_icase("numpat") ||
                               op.arg(1).eq_icase("shardchannels") ||
                               op.arg(1).eq_icase("shardnumsub");
            if (!known) {
                pubsub_reply_bad_subcommand(op, true);
                return;
            }
            if ((op.arg(1).eq_icase("help") || op.arg(1).eq_icase("numpat")) &&
                op.argc() != 2) {
                pubsub_reply_bad_arity(op, op.arg(1).eq_icase("help") ? "help" : "numpat");
                return;
            }
            command += '|';
            const size_t subcommand = command.size();
            command.append(op.arg(1).p, op.arg(1).n);
            for (size_t index = subcommand; index < command.size(); index++)
                if (command[index] >= 'A' && command[index] <= 'Z')
                    command[index] = static_cast<char>(command[index] + ('a' - 'A'));
        }
        std::string message = "ERR Can't execute '";
        message += command;
        message += "': only (P|S)SUBSCRIBE / (P|S)UNSUBSCRIBE / PING / QUIT / RESET are allowed in this context";
        reply_err(op.sink(), message.c_str());
    }

    bool pubsub_disconnect_ready(Client* client) {
        auto it = pubsub_local_.find(client->id());
        if (it == pubsub_local_.end()) return true;
        PubSubLocalConn& local = it->second;
        if (!local.cleanup_started) {
            if (!local.pending && local.channels.empty() && local.patterns.empty() &&
                local.shard_channels.empty()) {
                pubsub_local_.erase(it);
                return true;
            }
            local.cleanup_started = true;
            local.cleanup_remaining = srv_->placement().ifid_threads().size();
            for (uint32_t io : srv_->placement().ifid_threads()) {
                PubSubEvent* event = pubsub_new_event(PubSubEventKind::CleanupRequest);
                event->origin_io = self_->id();
                event->conn_id = client->id();
                pubsub_post(io, event);
            }
            pubsub_drain_events();
            return false;
        }
        if (!local.cleanup_done) return false;
        pubsub_local_.erase(it);
        return true;
    }

    void pubsub_shutdown_events() {
        std::deque<PubSubEvent*> events;
        self_->take_pubsub_events(events);
        events.insert(events.end(), pubsub_local_events_.begin(), pubsub_local_events_.end());
        pubsub_local_events_.clear();
        for (PubSubEvent* event : events) pubsub_delete_event(event);
        // Un-flushed outbox items still hold one blob reference each; the gauge must reach zero.
        for (uint32_t io : pubsub_outbox_dirty_) {
            PubSubOutbox& box = pubsub_outbox_[io];
            for (PubSubDelivery& item : box.deliveries) pubsub_blob_unref(item.blob);
            box.deliveries.clear();
            box.results.clear();
        }
        pubsub_outbox_dirty_.clear();
        pubsub_pass_pending_ = false;
        pubsub_notification_chains_.clear();
    }

    std::unordered_map<std::string, std::vector<PubSubRef>> pubsub_channels_;
    std::unordered_map<std::string, std::vector<PubSubRef>> pubsub_shard_channels_;
    std::vector<PubSubPatternRef> pubsub_patterns_;
    std::unordered_map<uint64_t, PubSubLocalConn> pubsub_local_;
    std::unordered_map<uint64_t, PubSubPending> pubsub_pending_;
    std::deque<PubSubEvent*> pubsub_local_events_;
    std::vector<PubSubOutbox> pubsub_outbox_;      // sized on first pub/sub use, never before
    }

    ~IoLoop() {
        if (self_) pubsub_shutdown_events();
        if (listen_fd_ >= 0) ::close(listen_fd_);
        if (tls_listen_fd_ >= 0) ::close(tls_listen_fd_);
        if (unix_listen_fd_ >= 0) ::close(unix_listen_fd_);
        for (Client* c : pending_handoffs_) {
            ::close(c->fd());
            srv_->client_released();
            delete c;
        }
        multi_shutdown_entry(*this);
    }

    static int make_reuseport_listener(const char* addr, uint16_t port, uint32_t backlog = 511,
                                       bool defer_accept = false) {
        int fd = ::socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0) return -1;
        int one = 1;
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    }

    void pubsub_home_cleanup_channels(
            std::unordered_map<std::string, std::vector<PubSubRef>>& index,
            const PubSubRef& ref, bool shard) {
        for (auto it = index.begin(); it != index.end();) {
            std::vector<PubSubRef>& refs = it->second;
            size_t out = 0;
            for (size_t i = 0; i < refs.size(); i++) {
                if (refs[i] == ref) srv_->pubsub_home_entry_removed();
                else refs[out++] = refs[i];
            }
            refs.resize(out);
            if (refs.empty()) {
                it = index.erase(it);
                srv_->pubsub_active_channel_removed(shard);
            } else {
                ++it;
            }
        }
    }

    void pubsub_home_cleanup(const PubSubRef& ref) {
        pubsub_home_cleanup_channels(pubsub_channels_, ref, false);
        pubsub_home_cleanup_channels(pubsub_shard_channels_, ref, true);
        size_t out = 0;
        for (size_t i = 0; i < pubsub_patterns_.size(); i++) {
            if (pubsub_patterns_[i].ref == ref) srv_->pubsub_home_entry_removed();
            else pubsub_patterns_[out++] = std::move(pubsub_patterns_[i]);
        }
        pubsub_patterns_.resize(out);
    }

    // Appends one already-encoded frame to a subscriber.  RESP3 subscribers get the same bytes
    // with the leading array byte swapped for the push byte, appended as two pieces so the payload
    // is never copied a second time.
    void pubsub_emit(Client* client, const char* p, size_t n, bool resp3) {
        static constexpr char kPush = '>';
        auto pending_it = pubsub_pending_.empty() ? pubsub_pending_.end()
                                                  : pubsub_pending_.find(client->id());
        if (pending_it != pubsub_pending_.end()) {
            // A subscription control is mid-flight on this connection: park the push behind it so
            // the acknowledgement it is waiting for still lands in the Redis-mandated order.
            std::string& deferred = pending_it->second.deferred;
            if (resp3) { deferred.push_back(kPush); deferred.append(p + 1, n - 1); }
            else deferred.append(p, n);
            return;
        }
        // A WHOLE FRAME, ON A FRAME BOUNDARY. This used to park the push on the newest live Op's
        // `reply`, which is the reply's tail when it is copied and its HEAD when it is borrowed --
        // so a push landed between a bulk header and its zero-copy body. Client::append_oob picks
        // the output channel that can neither reorder the frame nor overwrite a live direct-reply
        // region. The send engine also parks a frame behind the dispatch frontier it observes, so
        // a delivery cannot overtake an earlier-issued reply such as its own SSUBSCRIBE ack. A
        // genuinely parked blocking head is the latency-bounded exception.
        const bool deferred = resp3 ? wb_.defer_oob(*client, &kPush, 1, p + 1, n - 1)
                                    : wb_.defer_oob(*client, p, n);
        if (__builtin_expect(deferred, false)) {
            srv_->note_oob_frame_deferred();
        } else {
            const bool segmented = resp3 ? client->append_oob(&kPush, 1, p + 1, n - 1)
                                         : client->append_oob(p, n);
            if (__builtin_expect(segmented, false)) srv_->note_oob_frame_segmented();
        }
        enqueue_serve(client);
        mark_active(client);
    }

    void pubsub_deliver_one(const PubSubDelivery& item) {
        auto local_it = pubsub_local_.find(item.conn);
        if (local_it == pubsub_local_.end()) return;

exec
/bin/bash -lc "rg -n 'begin_live_config_update|end_live_config_update|store_client_output_buffer_limits' src/core/server.h && sed -n '3360,3435p' src/core/server.h && sed -n '4434,4458p' src/core/io_loop.h && sed -n '964,986p' src/core/pubsub.inc && sed -n '830,850p' src/core/pubsub.inc" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
242:        store_client_output_buffer_limits(cfg.client_output_buffer_limits);
1922:        const uint64_t version = begin_live_config_update();
1924:        end_live_config_update(version);
1927:        const uint64_t version = begin_live_config_update();
1929:        end_live_config_update(version);
2220:        const uint64_t version = begin_live_config_update();
2223:        end_live_config_update(version);
2230:        const uint64_t version = begin_live_config_update();
2231:        store_client_output_buffer_limits(limits);
2233:        end_live_config_update(version);
2260:        const uint64_t version = begin_live_config_update();
2263:        end_live_config_update(version);
2266:        const uint64_t version = begin_live_config_update();
2269:        end_live_config_update(version);
2448:        const uint64_t write_version = begin_live_config_update();
2453:        end_live_config_update(write_version);
2458:        const uint64_t write_version = begin_live_config_update();
2463:        end_live_config_update(write_version);
2890:        const uint64_t version = begin_live_config_update();
2892:        end_live_config_update(version);
3059:        const uint64_t write_version = begin_live_config_update();
3064:        end_live_config_update(write_version);
3067:        const uint64_t write_version = begin_live_config_update();
3069:        end_live_config_update(write_version);
3072:        const uint64_t write_version = begin_live_config_update();
3075:        end_live_config_update(write_version);
3254:    void store_client_output_buffer_limits(const ClientOutputBufferLimits& limits) {
3312:    uint64_t begin_live_config_update() {
3324:    void end_live_config_update(uint64_t write_version) {
    uint32_t flip_surviving_io_count_ = 0;
    std::vector<Client*> flip_client_plan_[kMaxThreads];
    std::vector<uint32_t> flip_client_destinations_[kMaxThreads];
    uint32_t flip_client_quota_[kMaxThreads] = {};
    uint32_t flip_bucket_quota_[kMaxThreads] = {};
    uint32_t flip_shard_destination_[256] = {};
    std::atomic<uint32_t> flip_incoming_clients_[kMaxThreads] = {};
    std::atomic<uint32_t> flip_source_clients_[kMaxThreads] = {};
    uint32_t flip_planned_client_transfers_ = 0;
    uint32_t flip_planned_shard_transfers_ = 0;
    uint32_t flip_coordinator_ = UINT32_MAX;
    uint32_t unix_owner_tid_ = UINT32_MAX;
    std::atomic<bool> flip_failed_{false};
    mutable std::mutex flip_error_mu_;
    std::string flip_error_;
    std::atomic<uint64_t> flip_completed_{0};
    std::atomic<uint64_t> flip_refused_{0};
    std::atomic<uint64_t> flip_clients_transferred_{0};
    std::atomic<uint64_t> flip_active_transfers_{0};
    std::atomic<uint64_t> flip_last_transfers_{0};
    std::atomic<uint64_t> flip_bucket_weight_spread_before_{0}; // fixed point, /1024
    std::atomic<uint64_t> flip_bucket_weight_spread_after_{0};
    std::atomic<uint64_t> flip_client_weight_spread_before_{0};
    std::atomic<uint64_t> flip_client_weight_spread_after_{0};
    std::atomic<uint64_t> flip_bucket_bytes_spread_before_{0};
    std::atomic<uint64_t> flip_bucket_bytes_spread_after_{0};
    std::atomic<uint64_t> flip_conservation_checks_{0};
    std::atomic<uint64_t> flip_conservation_violations_{0};

    // The continuous controller has one cron writer and publishes only these two cold stages.
    // EX movement reuses FLIP's quiescence fence; client movement pauses one selected connection
    // until the existing asynchronous transfer primitive takes ownership.
    std::atomic<LbStage> lb_stage_{LbStage::Idle};
    std::atomic<uint64_t> lb_epoch_{0};
    std::atomic<uint64_t> lb_deadline_ns_{0};
    std::atomic<uint64_t> lb_ack_[kMaxThreads] = {};
    uint32_t lb_coordinator_ = UINT32_MAX;
    std::vector<LbShardMove> lb_shard_moves_;
    LbClientMove lb_client_move_;
    std::atomic<uint64_t> lb_client_inflight_id_{0};
    uint32_t lb_bucket_hot_streak_ = 0;
    uint32_t lb_client_hot_streak_ = 0;
    bool lb_prefer_client_ = false;
    std::atomic<uint64_t> lb_ticks_{0};
    std::atomic<uint64_t> lb_bucket_moves_{0};
    std::atomic<uint64_t> lb_client_moves_{0};
    std::atomic<uint64_t> lb_bucket_cross_domain_moves_{0};
    std::atomic<uint64_t> lb_client_cross_domain_moves_{0};
    std::atomic<uint64_t> lb_no_candidate_{0};
    std::atomic<uint64_t> lb_hysteresis_refused_{0};
    std::atomic<uint64_t> lb_cooldown_refused_{0};
    std::atomic<uint64_t> lb_transition_refused_{0};
    std::atomic<uint64_t> lb_capacity_refused_{0};
    std::atomic<uint64_t> lb_client_refused_{0};
    std::atomic<uint64_t> lb_hot_bucket_refused_{0};
    std::atomic<uint64_t> lb_bucket_weight_spread_current_{0};
    std::atomic<uint64_t> lb_bucket_weight_spread_before_{0};
    std::atomic<uint64_t> lb_bucket_weight_spread_after_{0};
    std::atomic<uint64_t> lb_client_weight_spread_current_{0};
    std::atomic<uint64_t> lb_client_weight_spread_before_{0};
    std::atomic<uint64_t> lb_client_weight_spread_after_{0};
    std::atomic<uint64_t> lb_bucket_bytes_spread_current_{0};
    std::atomic<uint64_t> lb_bucket_bytes_spread_before_{0};
    std::atomic<uint64_t> lb_bucket_bytes_spread_after_{0};

    // Weighted-placement state is absent when both key-lb and client-lb are 0. Bucket arrays
    // are indexed by the immutable routing id; client state is keyed by the immutable connection id. The mutex is a
    // once-per-controller-beat/read-side lock and is never acquired on an operation path.
    std::unique_ptr<LbAutotune> lb_policy_;
    mutable std::mutex lb_signal_mu_;
    std::vector<uint32_t> lb_bucket_last_samples_;
    std::vector<double> lb_bucket_weight_;
    std::vector<uint64_t> lb_bucket_last_move_ms_;
    std::vector<uint64_t> lb_thread_last_busy_;
    std::vector<uint64_t> lb_thread_last_idle_;
    std::vector<double> lb_thread_occupancy_;
    // barrier stops younger frames; a resumed move reuses that slot and inherits its owner bit.
    // No external production path adds another owner while it is parked.
    // barrier_owner_overlaps is that argument's live assertion, and a validation run that
    // wants the two-owner geometry gates on it rather than trusting the prose. Cold by
    // construction: the seven owners are EXEC, a subscribe, a blocking command, a deferred WAIT,
    // a deferred DEBUG SLEEP, a barriered scatter and a CLIENT fan-out. GET and SET never reach it.
    void barrier_arm(Client* c, BarrierOwner who) {
        if (__builtin_expect(c->scatter_barrier(), false)) srv_->note_barrier_overlap();
        c->barrier_acquire(who);
    }

    void finish_locally(Client* c, Op& op, const char* err) {
        reply_err(op.reply, err);
        finish_prebuilt(c, op);
    }

    void finish_prebuilt(Client* c, Op& op) {
        // Unknown-command and arity errors precede the ordinary armed gate.
        if (!op.spec && (climon_armed_cached_ & Server::kClimonReply)) climon_mark_reply(c, op);
        op.state.store(OpState::Done, std::memory_order_release);
        c->rob().publish();
        enqueue_serve(c);
        mark_active(c);
    }

            if (pubsub_local_events_.empty()) break;
        }
        pubsub_pass_pending_ = !pubsub_local_events_.empty() || !pubsub_outbox_dirty_.empty();
        return work;
    }

    PubSubLocalConn& pubsub_track(Client* client) {
        auto [it, inserted] = pubsub_local_.try_emplace(client->id());
        if (inserted) it->second.client = client;
        return it->second;
    }

    bool pubsub_prepare_rebind_events(const PubSubLocalConn& local, uint64_t client_id,
                                      uint32_t destination,
                                      std::vector<PubSubEvent*>& events) {
        auto make = [&](uint32_t target, bool pattern, bool shard) -> PubSubEvent* {
            auto* event = new (std::nothrow) PubSubEvent;
            if (!event) return nullptr;
            event->kind = PubSubEventKind::ModifyRequest;
            event->target_io = target;
            event->origin_io = destination;
            event->conn_id = client_id;
            event->pattern = pattern;
        }
        if (!pending.remaining) std::abort();
        if (--pending.remaining == 0) pubsub_finish_pending(event.conn_id);
    }

    void pubsub_handle_cleanup_result(PubSubEvent& event) {
        auto it = pubsub_local_.find(event.conn_id);
        if (it == pubsub_local_.end() || !it->second.cleanup_started ||
            !it->second.cleanup_remaining)
            return;
        PubSubLocalConn& local = it->second;
        if (--local.cleanup_remaining == 0) {
            pubsub_clear_local_subscriptions(local);
            local.cleanup_done = true;
            if (local.client && !local.client->dead()) mark_active(local.client);
        }
    }

    void pubsub_handle_acl_event(PubSubEvent& event) {
        const auto* permissions = static_cast<const AclPerm*>(event.acl_permissions);
        const bool kill_all = event.kind == PubSubEventKind::AclUserDeleted;

exec
/bin/bash -lc "rg -n 'ThreadCtx\\(|~ThreadCtx|ThreadCtx\\&|void init\\(' src/core/thread.h && rg -n 'max_threads|set_even|even_ifid|ifid_threads\\(\\)' src/core/placement.h | head -35 && sed -n '1,34p' src/cmd/xshard.cc" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
318:    ThreadCtx() = default;
319:    ThreadCtx(const ThreadCtx&) = delete;
320:    ThreadCtx& operator=(const ThreadCtx&) = delete;
325:    void init(uint32_t id, Role r, uint32_t nthreads, uint32_t age_sample_rate,
34:    // intentionally contain the same tids: existing connection fanout consumes ifid_threads(),
233:    const std::vector<uint32_t>& ifid_threads() const { return ifid_; }
// xshard.cc -- arena-backed, owner-only cross-shard execution.
#include "xshard.h"
#include "lcs.h"
#include "t_sort.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <cctype>
#include <charconv>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <fcntl.h>
#include <limits>
#include <memory>
#include <mutex>
#include <new>
#include <queue>
#include <string>
#include <sys/random.h>
#include <sys/stat.h>
#include <unistd.h>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "command.h"
#include "acl.h"
#include "auth.h"
#include "blocking.h"

exec
/bin/bash -lc "sed -n '3304,3348p' src/core/server.h && sed -n '3250,3274p' src/core/server.h && sed -n '34,65p' src/core/placement.h && sed -n '319,339p' src/core/thread.h" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
        clients.normal.soft_bytes = live_obuf_normal_soft_.load(std::memory_order_relaxed);
        clients.normal.soft_seconds = live_obuf_normal_seconds_.load(std::memory_order_relaxed);
        clients.pubsub.hard_bytes = live_obuf_pubsub_hard_.load(std::memory_order_relaxed);
        clients.pubsub.soft_bytes = live_obuf_pubsub_soft_.load(std::memory_order_relaxed);
        clients.pubsub.soft_seconds = live_obuf_pubsub_seconds_.load(std::memory_order_relaxed);
        return values;
    }

    uint64_t begin_live_config_update() {
        uint64_t version = live_config_version_.load(std::memory_order_acquire);
        for (;;) {
            if (version & 1) {
                version = live_config_version_.load(std::memory_order_acquire);
                continue;
            }
            if (live_config_version_.compare_exchange_weak(
                    version, version + 1, std::memory_order_acq_rel, std::memory_order_acquire))
                return version + 1;
        }
    }
    void end_live_config_update(uint64_t write_version) {
        const LiveConfigValues next = capture_live_config(write_version + 1);
        if (live_config_mailboxes_)
            for (uint32_t tid = 0; tid <= nthreads(); tid++)
                live_config_mailboxes_[tid].publish(live_config_committed_, next);
        live_config_committed_ = next;
        live_config_version_.store(write_version + 1, std::memory_order_release);
    }

    Config    cfg_;
    Topology  topo_;
    Placement placement_;
    Router    router_;
    std::vector<std::unique_ptr<Shard>>     shards_;
    std::vector<std::unique_ptr<ThreadCtx>> threads_;
    AofManager aof_;
    // Declared after AOF so its destructor runs first and can detach an active rewrite callback.
    SnapshotManager snapshot_;
    FlipController flipctl_;

    // Router is authoritative at bucket granularity. This commit-only derivative exists solely so
    // shard-granularity dispatch remains one flat-array load.
    std::atomic<uint32_t> shard_owner_[256] = {};

    // FLIP is a cold, manually driven control-plane transaction.  The stage store is the global
                "/proc/sys/net/core/somaxconn is set to the lower value of %d.\n",
                cfg_.tcp_backlog, somaxconn);
    }

    void store_client_output_buffer_limits(const ClientOutputBufferLimits& limits) {
        live_obuf_normal_hard_.store(limits.normal.hard_bytes, std::memory_order_relaxed);
        live_obuf_normal_soft_.store(limits.normal.soft_bytes, std::memory_order_relaxed);
        live_obuf_normal_seconds_.store(limits.normal.soft_seconds, std::memory_order_relaxed);
        live_obuf_pubsub_hard_.store(limits.pubsub.hard_bytes, std::memory_order_relaxed);
        live_obuf_pubsub_soft_.store(limits.pubsub.soft_bytes, std::memory_order_relaxed);
        live_obuf_pubsub_seconds_.store(limits.pubsub.soft_seconds, std::memory_order_relaxed);
    }

    void refresh_climon_armed() {
        uint32_t armed = 0;
        if (climon_monitors_.load(std::memory_order_relaxed)) armed |= kClimonMonitor;
        if (climon_tracking_.load(std::memory_order_relaxed)) armed |= kClimonTracking;
        if (climon_pause_end_ms_.load(std::memory_order_relaxed)) armed |= kClimonPause;
        if (climon_reply_.load(std::memory_order_relaxed)) armed |= kClimonReply;
        climon_armed_.store(armed, std::memory_order_release);
    }

    void refresh_client_cron_armed() {
        const bool normal = live_obuf_normal_hard_.load(std::memory_order_relaxed) != 0 ||
                            live_obuf_normal_soft_.load(std::memory_order_relaxed) != 0;
    // intentionally contain the same tids: existing connection fanout consumes ifid_threads(),
    // while shard/snapshot fanout consumes ex_threads(). Explicit role labels remain accepted as
    // CPU selectors, but have no runtime meaning in this mode.
    bool build_fused(const Topology& topo, const char* spec) {
        clear();
        if (spec) {
            if (!build_explicit(topo, spec)) return false;
        } else {
            for (uint32_t domain = 0; domain < topo.ndomains(); domain++)
                for (int cpu : topo.cpus_in(domain)) append(Role::Ifid, cpu, domain);
        }
        if (threads_.empty()) {
            std::fprintf(stderr, "1s placement needs at least one thread\n");
            return false;
        }
        if (threads_.size() > kMaxThreads) {
            std::fprintf(stderr,
                         "1s placement has %zu threads, exceeding the %u-thread channel limit\n",
                         threads_.size(), kMaxThreads);
            return false;
        }
        ifid_.clear();
        ex_.clear();
        for (uint32_t tid = 0; tid < threads_.size(); tid++) {
            threads_[tid].role = Role::Ifid;
            ifid_.push_back(tid);
            ex_.push_back(tid);
        }
        return true;
    }

    // EVEN GLOBAL PLACEMENT. Counts are whole-server, so shapes no per-node grammar can express
    ThreadCtx(const ThreadCtx&) = delete;
    ThreadCtx& operator=(const ThreadCtx&) = delete;

    // `nthreads` is the TOTAL thread count, not the io count: any thread can become a producer
    // through a role change. The task slot allocation is deferred until this physical thread has
    // pinned itself; init_task_inbox_local() then first-touches it from the consumer's local CPU.
    void init(uint32_t id, Role r, uint32_t nthreads, uint32_t age_sample_rate,
              uint32_t flip_work_window) {
        id_ = id;
        role_.store(r, std::memory_order_relaxed);
        nchan_     = nthreads;
        client_in_ = std::make_unique<ClientChan[]>(nthreads);
        release_in_ = std::make_unique<ReleaseChan[]>(nthreads);
        transfer_in_ = std::make_unique<TransferChan[]>(nthreads);
        sig_.configure_age_sampling(age_sample_rate);
        flip_fingerprint_.configure(flip_work_window);
    }

    bool init_task_inbox_local(const std::vector<uint32_t>& io,
                               const std::vector<uint32_t>& ex) {
        std::unique_ptr<TaskInbox> inbox(new (std::nothrow) TaskInbox);

exec
/bin/bash -lc "rg -n -A22 '"'^struct ClientBufferLimit|''^struct ClientOutputBufferLimits'"' src/core/config.h && rg -n 'tls_slot_conn\\(' src/core/io_loop.h | head -12 && rg -n 'multi_close_entry\\(' src/cmd/multi.inc src/cmd/xshard.cc" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
43:struct ClientBufferLimit {
44-    uint64_t hard_bytes = 0;
45-    uint64_t soft_bytes = 0;
46-    uint32_t soft_seconds = 0;
47-};
48-
49:struct ClientOutputBufferLimits {
50-    ClientBufferLimit normal{};
51-    ClientBufferLimit replica{256ull * 1024 * 1024, 64ull * 1024 * 1024, 60};
52-    ClientBufferLimit pubsub{32ull * 1024 * 1024, 8ull * 1024 * 1024, 60};
53-};
54-
55-inline bool cfg_eq_icase(const char* a, const char* b) {
56-    if (!a || !b) return false;
57-    while (*a && *b) {
58-        unsigned char ac = static_cast<unsigned char>(*a++);
59-        unsigned char bc = static_cast<unsigned char>(*b++);
60-        if (ac >= 'A' && ac <= 'Z') ac = static_cast<unsigned char>(ac + ('a' - 'A'));
61-        if (bc >= 'A' && bc <= 'Z') bc = static_cast<unsigned char>(bc + ('a' - 'A'));
62-        if (ac != bc) return false;
63-    }
64-    return *a == *b;
65-}
66-
67-// Redis memtoull grammar: bare bytes (or B), decimal K/M/G, binary KB/MB/GB.  Both boot
68-// parsing and CONFIG SET call this length-aware implementation, so a RESP bulk does not need a
69-// temporary NUL-terminated copy and the two surfaces cannot drift again.
70-inline bool cfg_memory_suffix(const char* input, size_t length, const char* expected) {
71-    const size_t expected_length = std::strlen(expected);
1203:                        if (TlsConn* tls = tls_slot_conn(c)) {
1533:    TlsConn* tls_slot_conn(const Client* c) {
1539:        TlsConn* tls = tls_slot_conn(c);
2326:            TlsConn* tls = tls_slot_conn(c);
2396:        TlsConn* tls = tls_slot_conn(c);
2512:        TlsConn* tls = tls_slot_conn(c);
4893:                else if (TlsConn* slot = tls_slot_conn(client); slot && slot->ktls())
4913:                } else if (TlsConn* slot = tls_slot_conn(client); slot && slot->ktls()) {
5056:                    else if (TlsConn* slot = tls_slot_conn(client); slot && slot->ktls())
5076:                    } else if (TlsConn* slot = tls_slot_conn(client); slot && slot->ktls()) {
5151:                } else if (TlsConn* slot = tls_slot_conn(c); slot && slot->ktls()) {
5463:                } else if (TlsConn* slot = tls_slot_conn(c); slot && slot->ktls()) {
src/cmd/multi.inc:1798:void multi_close_entry(IoLoop& loop, Client& client) {

codex
I’ll put the regression in the existing pub/sub unit row, so the gate count stays unchanged. It will check SUBSCRIBE completion for both protocols, timeout disabled, the exact timeout boundary, the blocked-client exemption, and RESP3 expiry.

apply patch
patch: completed
/home/user/Projects/cx-deadconf-fix/tests/netcmd_unit.cc
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d8af667802044e2097656c75b64e1eda..dba9b59bfe828b3b56b69bd31d13101894773dac
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();

exec
/bin/bash -lc 'taskset -c 112-127 make -j8 build/netcmd-unit > build/deadconf-n9-old-build.log 2>&1' in /home/user/Projects/cx-deadconf-fix
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d8af667802044e2097656c75b64e1eda..dba9b59bfe828b3b56b69bd31d13101894773dac
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();

exec
/bin/bash -lc "sed -n '1530,1544p' src/core/io_loop.h && sed -n '1798,1823p' src/cmd/multi.inc && sed -n '185,277p' tests/netcmd_unit.cc" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
        return (ntohl(peer.sin_addr.s_addr) & 0xff000000u) == 0x7f000000u;
    }

    TlsConn* tls_slot_conn(const Client* c) {
        if (!c || !c->is_tls() || c->tls_slot() >= tls_slots_.size()) return nullptr;
        return tls_slots_[c->tls_slot()].get();
    }

    TlsConn* tls_engine(const Client* c) {
        TlsConn* tls = tls_slot_conn(c);
        return tls && !tls->ktls() ? tls : nullptr;
    }

    bool attach_tls(Client* c) {
        try {
void multi_close_entry(IoLoop& loop, Client& client) {
    if (MultiExecState* cleanup = multi_prepare_close(*loop.srv_, client, loop.self_->id()))
        loop.pending_multi_cleanups_.push_back(cleanup);
}

void multi_shutdown_entry(IoLoop& loop) {
    for (MultiExecState* state : loop.pending_multi_cleanups_)
        multi_abandon_unpublished(state);
    loop.pending_multi_cleanups_.clear();
}

uint32_t multi_dispatch_count(const MultiExecState* state) {
    return state ? static_cast<uint32_t>(state->shards.size()) : 0;
}

int32_t multi_dispatch_shard(const MultiExecState* state, uint32_t index) {
    return state && index < state->shards.size() ? state->shards[index] : -1;
}

void multi_dispatch_started(Client& client, MultiExecState* state) {
    if (!state) return;
    state->published = true;
    MultiSession* session = client.multi_session();
    if (session && session->pending == state) session->pending = nullptr;
}

                bool allowed;
                if (suppressed) loop.wb_.prepare_suppressing(client, allowed);
                else loop.wb_.prepare(client, allowed);
                const std::string reply(client.fill_buf().data(), client.fill_buf().size());
                std::string push = message; push[0] = '>';
                check(reply.find(push) != std::string::npos, "independent publication survives retirement");
                if (suppressed) check(reply == push, "only command reply was suppressed");
            }
        }
    }

    static void pubsub_timeout() {
        for (bool resp3 : {false, true}) {
            Sender sender;
            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
            client.set_id(42); client.set_resp3(resp3);
            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
            ClientOutputBufferLimits limits; limits.pubsub = {};
            server.set_client_output_buffer_limits(limits);
            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
            self.add_client(&client);

            // Drive the real SUBSCRIBE completion, including its protocol-independent
            // subscriber flag. No listener, ring or worker is started by this fixture.
            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
            args(*op, {"SUBSCRIBE", "idle"});
            if (resp3) op->mark_resp3();
            client.rob().publish();
            auto& local = loop.pubsub_local_[client.id()];
            local.client = &client; local.pending = 1;
            auto& pending = loop.pubsub_pending_[client.id()];
            pending.kind = IoLoop::PubSubPendingKind::Modify;
            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
            pending.items.push_back("idle");
            server.pubsub_pending_started();
            loop.pubsub_finish_pending(client.id());
            const std::string ack = std::string(resp3 ? ">" : "*") +
                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
            check(op->state.load() == OpState::Done &&
                  std::string(op->reply.data(), op->reply.size()) == ack &&
                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
                  "SUBSCRIBE completed and armed the subscriber exemption candidate");

            client.set_last_interaction_s(100);
            loop.cached_now_s_ = 106;
            server.set_timeout(0);
            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
            server.set_timeout(5);
            loop.cached_now_s_ = 105;
            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
            loop.cached_now_s_ = 106;
            client.set_blocked(true);
            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
            client.set_blocked(false);
            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
            check(client.closing() == resp3,
                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
        }
    }

    static void receive_segments() {
        SegmentQueue<4, 8> segments;
        segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
        check(segments.size() == 3 && segments.byte_size() == 19, "two-piece aggregate split into representable segments");
        iovec iov[4]; bool borrow = false; uint32_t bytes = 0;
        const auto n = segments.build_iov(iov, 4, 64, borrow, bytes);
        std::string actual;
        for (uint32_t i = 0; i < n; ++i) {
            check(iov[i].iov_len <= 8, "segment length cap honored");
            actual.append(static_cast<const char*>(iov[i].iov_base), iov[i].iov_len);
        }
        check(bytes == 19 && actual == "abcdefghijklmnopqrs", "aggregate contents preserved");
        Client input(-1); size_t avail = 0;
        check(input.read_space(2 * 1024 * 1024, avail, true, 1024 * 1024) && avail >= 2 * 1024 * 1024,
              "whole command can exceed individual bulk limit");
        const auto before = input.rcap();
        input.commit_read(before - 1);
        check(!input.read_space(4096, avail, false, 1024 * 1024) && input.rcap() == before,
              "receive growth remains forbidden with outstanding argv slices");
        // Allocation reserves virtual space; no 600 MiB payload or benchmark is needed.
        Client large(-1);
        check(large.read_space(600ull * 1024 * 1024, avail, true) &&
              avail >= 600ull * 1024 * 1024, "default receive allowance has no one-bulk ceiling");
        check(large.read_space(600ull * 1024 * 1024, avail, true, 1024ull * 1024 * 1024) &&
              avail >= 600ull * 1024 * 1024, "raised bulk limit fits epoll receive geometry");
    }

    // Diagnostic for the still-open cross-family partial-mutation finding; deliberately absent
    // from the passing gate rows until a failure-atomic collection update is implemented.
    static void collection_oom() {
        Shard shard; TypeLimits limits; limits.hash.max_entries = 1;

exec
/bin/bash -lc 'git diff --check && git diff --stat && tail -n 5 build/deadconf-n9-old-build.log' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
 tests/netcmd_unit.cc | 53 ++++++++++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 53 insertions(+)
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -Wno-mismatched-new-delete -I. -c tests/netcmd_unit.cc -o build/tests/netcmd_unit.o

diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d8af667802044e2097656c75b64e1eda..dba9b59bfe828b3b56b69bd31d13101894773dac
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();

diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d8af667802044e2097656c75b64e1eda..dba9b59bfe828b3b56b69bd31d13101894773dac
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();

 succeeded in 37213ms:
exec
/bin/bash -lc 'tail -n 4 build/deadconf-n9-old-build.log' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -Wno-mismatched-new-delete -I. -c tests/netcmd_unit.cc -o build/tests/netcmd_unit.o
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread build/tests/netcmd_unit.o build/tests/netcmd_stream_unit.o build/tests/netcmd_zset_unit.o build/tests/netcmd_config_unit.o build/src/net/tls.o build/src/cmd/commands.o build/src/cmd/glob.o build/src/cmd/acl.o build/src/cmd/hll.o build/src/cmd/t_server.o build/src/cmd/t_string.o build/src/cmd/t_string_notify.o build/src/cmd/t_hash.o build/src/cmd/t_hash_ttl.o build/src/cmd/t_list.o build/src/cmd/t_set.o build/src/cmd/t_zset_ops.o build/src/cmd/geo.o build/src/cmd/t_stream.o build/src/cmd/scripting.o build/src/cmd/functions.o build/src/cmd/serialize.o build/src/snapshot/snapshot.o build/src/persist/aof.o build/src/cmd/climon.o build/src/cmd/tracking.o build/src/cmd/slowlog.o build/src/cmd/lcs.o build/src/cmd/info_stats.o build/src/cmd/lbsignals.o build/src/core/flipctl.o build/src/core/genthread.o build/src/core/rl2s.o build/src/cmd/cmdgap.o build/src/cmd/pfdebug.o build/src/cmd/cmdmeta.o build/src/cmd/t_sort.o -o build/netcmd-unit -ljemalloc -luring -pthread -lssl -lcrypto -lm -Wl,--wrap=mkstemp -Wl,--wrap=fopen

diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d8af667802044e2097656c75b64e1eda..dba9b59bfe828b3b56b69bd31d13101894773dac
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();

exec
/bin/bash -lc 'taskset -c 112-127 ./build/netcmd-unit pubsub-timeout > build/deadconf-n9-old-test.log 2>&1' in /home/user/Projects/cx-deadconf-fix
 exited 1 in 0ms:
exec
/bin/bash -lc 'cat build/deadconf-n9-old-test.log' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
FAIL: idle RESP3 SUBSCRIBE client must be closed after timeout

diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d8af667802044e2097656c75b64e1eda..dba9b59bfe828b3b56b69bd31d13101894773dac
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();

codex
The regression failed on the old code at the intended assertion: “idle RESP3 SUBSCRIBE client must be closed after timeout.” I’ll now add the RESP2 condition and rebuild the server and unit binary on cores 112–127.

exec
/bin/bash -lc 'cp build/netcmd-unit build/netcmd-n9-old' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
apply patch
patch: completed
/home/user/Projects/cx-deadconf-fix/src/core/io_loop.h
/home/user/Projects/cx-deadconf-fix/tomokv.conf
diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index 30f6fa514632ac41a2ee60e2e07ec936c0dfcd09..e6fe5a7167a073d2164527ab89510e090970c9a0
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
-                cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
+                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d8af667802044e2097656c75b64e1eda..dba9b59bfe828b3b56b69bd31d13101894773dac
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();
diff --git a/tomokv.conf b/tomokv.conf
index 3b8d7aab968006f45df301bfcf2efffdcddf8fda..8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,7 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked and RESP2 pub/sub clients are exempt; an idle MULTI transaction is not exempt.
+# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
+# transactions remain subject to this timeout.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

exec
/bin/bash -lc 'taskset -c 112-127 make -j8 all build/netcmd-unit > build/deadconf-n9-post-build.log 2>&1' in /home/user/Projects/cx-deadconf-fix
diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index 30f6fa514632ac41a2ee60e2e07ec936c0dfcd09..e6fe5a7167a073d2164527ab89510e090970c9a0
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
-                cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
+                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d8af667802044e2097656c75b64e1eda..dba9b59bfe828b3b56b69bd31d13101894773dac
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();
diff --git a/tomokv.conf b/tomokv.conf
index 3b8d7aab968006f45df301bfcf2efffdcddf8fda..8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,7 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked and RESP2 pub/sub clients are exempt; an idle MULTI transaction is not exempt.
+# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
+# transactions remain subject to this timeout.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

exec
/bin/bash -lc 'tail -n 4 build/deadconf-n9-post-build.log' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -I. -c src/cmd/info_stats.cc -o build/src/cmd/info_stats.o
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -I. -c src/cmd/lbsignals.cc -o build/src/cmd/lbsignals.o
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -I. -c src/core/flipctl.cc -o build/src/core/flipctl.o
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -I. -c src/core/genthread.cc -o build/src/core/genthread.o

exec
/bin/bash -lc 'git diff --check && git diff -- src/core/io_loop.h tomokv.conf tests/netcmd_unit.cc && git status --short' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index 30f6fa514..e6fe5a716 100644
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@ ordinary_shard_ready:
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
-                cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
+                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d..dba9b59bf 100644
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@ struct NetcmdRegression {
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@ struct NetcmdRegression {
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@ int main(int argc, char** argv) {
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();
diff --git a/tomokv.conf b/tomokv.conf
index 3b8d7aab9..8dc4b8c0c 100644
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,7 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked and RESP2 pub/sub clients are exempt; an idle MULTI transaction is not exempt.
+# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
+# transactions remain subject to this timeout.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive
 M src/core/io_loop.h
 M tests/netcmd_unit.cc
 M tomokv.conf
?? CODEX-OUT.round1.md

diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index 30f6fa514632ac41a2ee60e2e07ec936c0dfcd09..e6fe5a7167a073d2164527ab89510e090970c9a0
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
-                cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
+                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d8af667802044e2097656c75b64e1eda..dba9b59bfe828b3b56b69bd31d13101894773dac
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();
diff --git a/tomokv.conf b/tomokv.conf
index 3b8d7aab968006f45df301bfcf2efffdcddf8fda..8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,7 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked and RESP2 pub/sub clients are exempt; an idle MULTI transaction is not exempt.
+# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
+# transactions remain subject to this timeout.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index 30f6fa514632ac41a2ee60e2e07ec936c0dfcd09..e6fe5a7167a073d2164527ab89510e090970c9a0
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
-                cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
+                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d8af667802044e2097656c75b64e1eda..dba9b59bfe828b3b56b69bd31d13101894773dac
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();
diff --git a/tomokv.conf b/tomokv.conf
index 3b8d7aab968006f45df301bfcf2efffdcddf8fda..8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,7 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked and RESP2 pub/sub clients are exempt; an idle MULTI transaction is not exempt.
+# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
+# transactions remain subject to this timeout.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

exec
/bin/bash -lc 'tail -n 3 build/deadconf-n9-post-build.log' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -Wno-mismatched-new-delete -I. -c tests/netcmd_stream_unit.cc -o build/tests/netcmd_stream_unit.o
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -Wno-mismatched-new-delete -I. -c tests/netcmd_zset_unit.cc -o build/tests/netcmd_zset_unit.o
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -Wno-mismatched-new-delete -I. -c tests/netcmd_config_unit.cc -o build/tests/netcmd_config_unit.o

diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index 30f6fa514632ac41a2ee60e2e07ec936c0dfcd09..e6fe5a7167a073d2164527ab89510e090970c9a0
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
-                cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
+                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d8af667802044e2097656c75b64e1eda..dba9b59bfe828b3b56b69bd31d13101894773dac
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();
diff --git a/tomokv.conf b/tomokv.conf
index 3b8d7aab968006f45df301bfcf2efffdcddf8fda..8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,7 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked and RESP2 pub/sub clients are exempt; an idle MULTI transaction is not exempt.
+# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
+# transactions remain subject to this timeout.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

codex
The fix and config update are ready. The build is still running; afterward I’ll run the timeout, pub/sub, and output-buffer unit cases before committing.

 succeeded in 69142ms:
diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index 30f6fa514632ac41a2ee60e2e07ec936c0dfcd09..e6fe5a7167a073d2164527ab89510e090970c9a0
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
-                cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
+                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d8af667802044e2097656c75b64e1eda..dba9b59bfe828b3b56b69bd31d13101894773dac
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();
diff --git a/tomokv.conf b/tomokv.conf
index 3b8d7aab968006f45df301bfcf2efffdcddf8fda..8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,7 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked and RESP2 pub/sub clients are exempt; an idle MULTI transaction is not exempt.
+# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
+# transactions remain subject to this timeout.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

exec
/bin/bash -lc 'taskset -c 112-127 ./build/netcmd-unit pubsub-timeout' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
ok: netcmd pubsub-timeout

exec
/bin/bash -lc 'taskset -c 112-127 ./build/netcmd-unit output' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
Client id=1 closed for overcoming of output buffer limits.
ok: netcmd output

exec
/bin/bash -lc 'taskset -c 112-127 ./build/netcmd-unit pubsub' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
ok: netcmd pubsub

exec
/bin/bash -lc "git diff --check && rg -n 'warning:|error:' build/deadconf-n9-post-build.log" in /home/user/Projects/cx-deadconf-fix
 exited 1 in 0ms:
diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index 30f6fa514632ac41a2ee60e2e07ec936c0dfcd09..e6fe5a7167a073d2164527ab89510e090970c9a0
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
-                cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
+                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d8af667802044e2097656c75b64e1eda..dba9b59bfe828b3b56b69bd31d13101894773dac
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();
diff --git a/tomokv.conf b/tomokv.conf
index 3b8d7aab968006f45df301bfcf2efffdcddf8fda..8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,7 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked and RESP2 pub/sub clients are exempt; an idle MULTI transaction is not exempt.
+# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
+# transactions remain subject to this timeout.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

codex
The build and all three unit cases passed on cores 112–127. The new test closes the idle RESP3 subscriber and keeps the RESP2 subscriber exempt; it failed on the old code as required. I’ll commit the three-file change now.

exec
/bin/bash -lc "git add -A ':"'!CODEX-OUT.md'"' ':"'!CODEX-OUT.round1.md'"' && git diff --cached --check && git diff --cached --stat && git commit -m 'limit subscriber idle-timeout exemption to RESP2' && git status --short && git log -1 --format='%h %s'" in /home/user/Projects/cx-deadconf-fix
 exited 1 in 0ms:
The following paths are ignored by one of your .gitignore files:
CODEX-OUT.md
hint: Use -f if you really want to add them.
hint: Turn this message off by running
hint: "git config advice.addIgnoredFile false"

diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index 30f6fa514632ac41a2ee60e2e07ec936c0dfcd09..e6fe5a7167a073d2164527ab89510e090970c9a0
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
-                cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
+                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d8af667802044e2097656c75b64e1eda..dba9b59bfe828b3b56b69bd31d13101894773dac
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();
diff --git a/tomokv.conf b/tomokv.conf
index 3b8d7aab968006f45df301bfcf2efffdcddf8fda..8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,7 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked and RESP2 pub/sub clients are exempt; an idle MULTI transaction is not exempt.
+# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
+# transactions remain subject to this timeout.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

exec
/bin/bash -lc "git add -- src/core/io_loop.h tests/netcmd_unit.cc tomokv.conf && git diff --cached --check && git diff --cached --stat && git commit -m 'limit subscriber idle-timeout exemption to RESP2' && git status --short && git log -1 --format='%h %s'" in /home/user/Projects/cx-deadconf-fix
 exited 128 in 0ms:
 src/core/io_loop.h   |  4 ++--
 tests/netcmd_unit.cc | 53 ++++++++++++++++++++++++++++++++++++++++++++++++++++
 tomokv.conf          |  3 ++-
 3 files changed, 57 insertions(+), 3 deletions(-)
Author identity unknown

*** Please tell me who you are.

Run

  git config --global user.email "you@example.com"
  git config --global user.name "Your Name"

to set your account's default identity.
Omit --global to set the identity only in this repository.

fatal: unable to auto-detect email address (got 'user@user-PowerEdge-R6615.(none)')

diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index 30f6fa514632ac41a2ee60e2e07ec936c0dfcd09..e6fe5a7167a073d2164527ab89510e090970c9a0
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
-                cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
+                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d8af667802044e2097656c75b64e1eda..dba9b59bfe828b3b56b69bd31d13101894773dac
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();
diff --git a/tomokv.conf b/tomokv.conf
index 3b8d7aab968006f45df301bfcf2efffdcddf8fda..8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,7 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked and RESP2 pub/sub clients are exempt; an idle MULTI transaction is not exempt.
+# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
+# transactions remain subject to this timeout.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

exec
/bin/bash -lc "git log -3 --format='%h %an <%ae> | %cn <%ce>' && git config --show-origin --get-regexp 'user\\.(name|email)|core\\.hooksPath'" in /home/user/Projects/cx-deadconf-fix
 exited 1 in 0ms:
528cb0b15 Codex <codex@openai.com> | Codex <codex@openai.com>
f1b61114a Codex <codex@openai.com> | Codex <codex@openai.com>
9ab54c4e1 Codex <codex@openai.com> | Codex <codex@openai.com>

diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index 30f6fa514632ac41a2ee60e2e07ec936c0dfcd09..e6fe5a7167a073d2164527ab89510e090970c9a0
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
-                cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
+                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d8af667802044e2097656c75b64e1eda..dba9b59bfe828b3b56b69bd31d13101894773dac
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();
diff --git a/tomokv.conf b/tomokv.conf
index 3b8d7aab968006f45df301bfcf2efffdcddf8fda..8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,7 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked and RESP2 pub/sub clients are exempt; an idle MULTI transaction is not exempt.
+# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
+# transactions remain subject to this timeout.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

exec
/bin/bash -lc "git -c user.name=Codex -c user.email=codex@openai.com commit -m 'limit subscriber idle-timeout exemption to RESP2' && git status --short && git log -1 --format='%h %s'" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
[cx-deadconf-fix-items 4f6449e12] limit subscriber idle-timeout exemption to RESP2
 3 files changed, 57 insertions(+), 3 deletions(-)
?? CODEX-OUT.round1.md
4f6449e12 limit subscriber idle-timeout exemption to RESP2

diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index 30f6fa514632ac41a2ee60e2e07ec936c0dfcd09..e6fe5a7167a073d2164527ab89510e090970c9a0
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
-                cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
+                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d8af667802044e2097656c75b64e1eda..dba9b59bfe828b3b56b69bd31d13101894773dac
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();
diff --git a/tomokv.conf b/tomokv.conf
index 3b8d7aab968006f45df301bfcf2efffdcddf8fda..8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,7 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked and RESP2 pub/sub clients are exempt; an idle MULTI transaction is not exempt.
+# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
+# transactions remain subject to this timeout.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

codex
Committed N9 only.

| Item | Files | Test that fails on old code | Commit |
|---|---|---|---|
| RESP2-only idle-timeout exemption | [io_loop.h](/home/user/Projects/cx-deadconf-fix/src/core/io_loop.h:6063), [tomokv.conf](/home/user/Projects/cx-deadconf-fix/tomokv.conf:52), [netcmd_unit.cc](/home/user/Projects/cx-deadconf-fix/tests/netcmd_unit.cc:196) | `pubsub-timeout`: confirmed old-code failure; fixed code closes RESP3 subscribers while preserving RESP2 exemption | `4f6449e12` |

Build and `pubsub-timeout`, `pubsub`, and `output` units passed on cores 112–127. Gate counts unchanged. No server, benchmark, or gate run.
diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index 30f6fa514632ac41a2ee60e2e07ec936c0dfcd09..e6fe5a7167a073d2164527ab89510e090970c9a0
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
-                cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
+                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index cb78ca09d8af667802044e2097656c75b64e1eda..dba9b59bfe828b3b56b69bd31d13101894773dac
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -161,6 +161,7 @@
     }
 
     static void pubsub() {
+        pubsub_timeout();
         for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                           IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
             for (bool suppressed : {false, true}) {
@@ -192,6 +193,57 @@
         }
     }
 
+    static void pubsub_timeout() {
+        for (bool resp3 : {false, true}) {
+            Sender sender;
+            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
+            client.set_id(42); client.set_resp3(resp3);
+            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
+            ClientOutputBufferLimits limits; limits.pubsub = {};
+            server.set_client_output_buffer_limits(limits);
+            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
+            self.add_client(&client);
+
+            // Drive the real SUBSCRIBE completion, including its protocol-independent
+            // subscriber flag. No listener, ring or worker is started by this fixture.
+            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
+            args(*op, {"SUBSCRIBE", "idle"});
+            if (resp3) op->mark_resp3();
+            client.rob().publish();
+            auto& local = loop.pubsub_local_[client.id()];
+            local.client = &client; local.pending = 1;
+            auto& pending = loop.pubsub_pending_[client.id()];
+            pending.kind = IoLoop::PubSubPendingKind::Modify;
+            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
+            pending.items.push_back("idle");
+            server.pubsub_pending_started();
+            loop.pubsub_finish_pending(client.id());
+            const std::string ack = std::string(resp3 ? ">" : "*") +
+                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
+            check(op->state.load() == OpState::Done &&
+                  std::string(op->reply.data(), op->reply.size()) == ack &&
+                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
+                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
+                  "SUBSCRIBE completed and armed the subscriber exemption candidate");
+
+            client.set_last_interaction_s(100);
+            loop.cached_now_s_ = 106;
+            server.set_timeout(0);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
+            server.set_timeout(5);
+            loop.cached_now_s_ = 105;
+            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
+            loop.cached_now_s_ = 106;
+            client.set_blocked(true);
+            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
+            client.set_blocked(false);
+            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
+            check(client.closing() == resp3,
+                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+        }
+    }
+
     static void receive_segments() {
         SegmentQueue<4, 8> segments;
         segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
@@ -515,6 +567,7 @@
     else if (mode == "flush") R::flush();
     else if (mode == "output") R::output();
     else if (mode == "pubsub") R::pubsub();
+    else if (mode == "pubsub-timeout") R::pubsub_timeout();
     else if (mode == "receive") R::receive_segments();
     else if (mode == "collection-oom") R::collection_oom();
     else if (mode == "config") R::config();
diff --git a/tomokv.conf b/tomokv.conf
index 3b8d7aab968006f45df301bfcf2efffdcddf8fda..8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,7 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked and RESP2 pub/sub clients are exempt; an idle MULTI transaction is not exempt.
+# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
+# transactions remain subject to this timeout.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

tokens used
105,152
Committed N9 only.

| Item | Files | Test that fails on old code | Commit |
|---|---|---|---|
| RESP2-only idle-timeout exemption | [io_loop.h](/home/user/Projects/cx-deadconf-fix/src/core/io_loop.h:6063), [tomokv.conf](/home/user/Projects/cx-deadconf-fix/tomokv.conf:52), [netcmd_unit.cc](/home/user/Projects/cx-deadconf-fix/tests/netcmd_unit.cc:196) | `pubsub-timeout`: confirmed old-code failure; fixed code closes RESP3 subscribers while preserving RESP2 exemption | `4f6449e12` |

Build and `pubsub-timeout`, `pubsub`, and `output` units passed on cores 112–127. Gate counts unchanged. No server, benchmark, or gate run.
