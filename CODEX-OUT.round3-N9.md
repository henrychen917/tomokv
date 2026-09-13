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
session id: 01a09903-f1e3-73e3-aadb-333a70a9eab8
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

CORRECTION-N9 (mainline 12:40) -- my earlier N9 instruction was WRONG; verified against Redis 7.4
source: timeout.c:39-45 exempts any client with CLIENT_PUBSUB from the idle timeout and has NO RESP
test; markClientAsPubSub (pubsub.c:222, callers 535/570) is unconditional, so RESP3 subscribers carry
the flag too. Redis exempts ALL subscribers. Our ORIGINAL io_loop.h:6063 (`!c->subscriber_mode()`,
no RESP test) already matched Redis. Owner decision = match Redis. Therefore, ONE commit on top of
4f6449e12 that: (a) restores the original condition at io_loop.h:6063 exactly (no RESP test);
(b) fixes tomokv.conf:52 to state the TRUE behaviour: "Blocked clients and pub/sub clients (RESP2 and
RESP3, as in Redis) are exempt; an idle MULTI transaction is not exempt."; (c) INVERTS your new
netcmd_unit test so it asserts a RESP3 subscriber is NOT closed by the timeout while a plain idle
RESP3 client IS -- this is the Redis-parity test and must FAIL against 4f6449e12's code. Do not
squash or rewrite 4f6449e12; a fresh commit on top. Compile + the same units on 112-127. Commit, stop.
codex
I’ll read the audit verdict, apply the N9 correction on top of `4f6449e12`, and invert the timeout test. Then I’ll compile and run the same units on cores 112–127, commit, and stop.
exec
/bin/bash -lc 'git status --short --branch && git log -9 --oneline' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
## cx-deadconf-fix-items
?? CODEX-OUT.round1.md
?? CODEX-OUT.round2-N9-wrong.md
4f6449e12 limit subscriber idle-timeout exemption to RESP2
528cb0b15 reject ACL selectors and correct ownership and list-limit comments
f1b61114a correct AOF, ROB and tracking configuration comments
9ab54c4e1 sample tracking eviction victims across buckets and collisions
36f7c17dc honor zero-copy off and inclusive GET/MGET cutovers
8c73d5d46 reject overflowing uint32 configuration limits
831b5499e preserve measurement metadata from worktree recovery
a363c2c5e gate: the ABBA row honours an explicit plan budget, overriding only a history-derived one
b9ed48b29 gate: the ABBA row never takes a history-derived timeout

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

## 2026-09-13 12:40 -- N9 REFUTED (mainline, from Redis 7.4 source)
The audit claimed "Redis exempts RESP2 only" from the idle timeout. False: `timeout.c:39-45` exempts
`CLIENT_PUBSUB` with no RESP test, and `markClientAsPubSub` (pubsub.c:222; callers :535, :570) sets the
flag for RESP3 subscribers too. Redis exempts ALL subscribers. The audit conflated this with the
RESP2-only *command* restriction (server.c:4106 `CLIENT_PUBSUB && c->resp == 2`). Our original
io_loop.h:6063 already matched Redis; the only defect was the tomokv.conf:52 comment. Lane commit
4f6449e12 (RESP2-only exemption) implemented mainline's wrong brief and is being superseded by a
restoring commit + corrected conf comment + inverted (RESP3-exempt) parity test.

exec
/bin/bash -lc "pwd && rg --files -g AGENTS.md -g '"'!build*'"' -g '"'!vendor'"' /home/user/Projects 2>/dev/null" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
/home/user/Projects/cx-deadconf-fix
/home/user/Projects/dragonfly/helio/AGENTS.md
/home/user/Projects/dragonfly/AGENTS.md
/home/user/Projects/valkey/AGENTS.md

exec
/bin/bash -lc "rg --files -g '*netcmd*' -g 'CMakeLists.txt' -g 'Makefile*' -g 'CODEX-OUT*' -g 'CMakeCache.txt' -g 'CTestTestfile.cmake' -g 'build.ninja' -g 'AGENTS.md' -g '"'!vendor'"' -g '"'!third_party'"' -g '"'!deps'"' && cat CODEX-OUT.round2-N9-wrong.md" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
xtern size_t netcmd_fail_size;
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

exec
/bin/bash -lc 'git show --stat 4f6449e12 && git show --format=fuller 4f6449e12 -- src/net/io_loop.h tomokv.conf tests/netcmd_unit.cc' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
commit 4f6449e12cd986d27fc0d1f3a79a3b96148f3357
Author: Codex <codex@openai.com>
Date:   Sun Sep 13 12:18:28 2026 +0800

    limit subscriber idle-timeout exemption to RESP2

 src/core/io_loop.h   |  4 ++--
 tests/netcmd_unit.cc | 53 ++++++++++++++++++++++++++++++++++++++++++++++++++++
 tomokv.conf          |  3 ++-
 3 files changed, 57 insertions(+), 3 deletions(-)
commit 4f6449e12cd986d27fc0d1f3a79a3b96148f3357
Author:     Codex <codex@openai.com>
AuthorDate: Sun Sep 13 12:18:28 2026 +0800
Commit:     Codex <codex@openai.com>
CommitDate: Sun Sep 13 12:18:28 2026 +0800

    limit subscriber idle-timeout exemption to RESP2

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

exec
/bin/bash -lc 'for path in /AGENTS.md /home/AGENTS.md /home/user/AGENTS.md /home/user/Projects/AGENTS.md; do if [ -f "$path" ]; then cat "$path"; fi; done' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
exec
/bin/bash -lc "sed -n '1,260p' Makefile && sed -n '1,295p' tests/netcmd_unit.cc && sed -n '1,180p' tests/netcmd_unit.h" in /home/user/Projects/cx-deadconf-fix
exec
/bin/bash -lc "ls -ld build && rg --files --hidden --no-ignore build -g '*netcmd*' -g '*tomokv*' -g '*n9*' -g '*N9*' -g 'Makefile' -g '*build*.log' -g 'AGENTS.md' && git status --porcelain=v1 --untracked-files=all" in /home/user/Projects/cx-deadconf-fix
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
        pubsub_timeout();
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

 succeeded in 0ms:
drwxrwxr-x 7 user user 4096 Sep 13 12:17 build
build/deadconf-item2-build.log
build/tomokv-deadconf-post
build/netcmd-tracking-old
build/deadconf-item1-build.log
build/netcmd-acl-old
build/tomokv-tracking-post
build/tomokv-zc-post
build/netcmd-zc-old
build/deadconf-n9-old-test.log
build/deadconf-item5-build.log
build/deadconf-item3-build.log
build/deadconf-item2-final-build.log
build/deadconf-old-unit-build.log
build/netcmd-unit
build/deadconf-n9-old-build.log
build/netcmd-config-old
build/netcmd-n9-old
build/deadconf-item5-final-build.log
build/deadconf-zc-old-build.log
build/tomokv-deadconf-pre
build/deadconf-pre-build.log
build/netcmd-zc-sanitized
build/tomokv-zc-pre
build/deadconf-zc-sanitized-build.log
build/tomokv
build/deadconf-n9-post-build.log
build/deadconf-item1-final-build.log
build/tests/netcmd_config_unit.o
build/tests/netcmd_zset_unit.o
build/tests/netcmd_unit.o
build/tests/netcmd_stream_unit.o
?? CODEX-OUT.round1.md
?? CODEX-OUT.round2-N9-wrong.md

exec
/bin/bash -lc "sed -n '6025,6095p' src/core/io_loop.h && rg -n 'void close_client|close_client\\(' src/core/io_loop.h | tail -12 && sed -n '44,62p' tomokv.conf && rg -n -m 18 'taskset -c 112-127|make .*netcmd|build/netcmd' CODEX-OUT.round2-N9-wrong.md" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
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
            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
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
5074:                            close_client(client,
5150:                        close_client(c, tls->output_pending() || c->send_inflight());
5420:                    close_client(c);
5462:                    if (tls->failed()) close_client(c, tls->output_pending() || c->send_inflight());
5488:                    if (tls->failed()) close_client(c, tls->output_pending() || c->send_inflight());
5529:                    if (tls->failed()) close_client(c, tls->output_pending() || c->send_inflight());
5689:                // through mark_closing() rather than close_client() (the reply has to go out
5787:                else { c->set_in_active(false); active_.erase_at(idx); close_client(c); }
5857:                    if (tls->failed()) close_client(c, tls->output_pending() || c->send_inflight());
6034:        close_client(c);
6065:                close_client(c);
6114:    void close_client(Client* c, bool drain_tls_output = false) {
###################### CONNECTION LIMITS ###################

# Maximum accepted clients [live], default 10000. Admission is checked before Client allocation.
# With independent SO_REUSEPORT acceptors, a simultaneous burst may overshoot by at most the
# number of IO threads; this is a safety valve rather than an exact reservation boundary.
# maxclients 10000

# Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
# transactions remain subject to this timeout.
# timeout 0

# TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive
# setsockopt calls. Linux KEEPINTVL is interval/3 (minimum 1) and KEEPCNT is 3.
# tcp-keepalive 300

# listen(2) backlog for TCP and unix sockets [boot-only]. Linux may cap it at somaxconn; boot logs
# Redis's advisory warning when that happens.
# tcp-backlog 511
532:build/netcmd-unit: $(NETCMD_TEST_OBJ) $(NETCMD_LIB_OBJ)
1553:168:build/netcmd-unit: $(NETCMD_TEST_OBJ) $(NETCMD_LIB_OBJ)
1810:        char directory[] = "build/netcmd-config-XXXXXX";
2116:build/netcmd-unit: $(NETCMD_TEST_OBJ) $(NETCMD_LIB_OBJ)
2163:  taskset -c "$CORES" ./build/netcmd-unit "$NETCMD_CASE" >$TMPDIR/gate-netcmd-$NETCMD_CASE.txt 2>&1 \
2238:1328:  taskset -c "$CORES" ./build/netcmd-unit "$NETCMD_CASE" >$TMPDIR/gate-netcmd-$NETCMD_CASE.txt 2>&1 \
2241:2548:      build/core-concurrency-unit build/atomic-survivors-unit build/netcmd-unit \
3895:/bin/bash -lc 'taskset -c 112-127 make -j8 build/netcmd-unit > build/deadconf-n9-old-build.log 2>&1' in /home/user/Projects/cx-deadconf-fix
4283:g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread build/tests/netcmd_unit.o build/tests/netcmd_stream_unit.o build/tests/netcmd_zset_unit.o build/tests/netcmd_config_unit.o build/src/net/tls.o build/src/cmd/commands.o build/src/cmd/glob.o build/src/cmd/acl.o build/src/cmd/hll.o build/src/cmd/t_server.o build/src/cmd/t_string.o build/src/cmd/t_string_notify.o build/src/cmd/t_hash.o build/src/cmd/t_hash_ttl.o build/src/cmd/t_list.o build/src/cmd/t_set.o build/src/cmd/t_zset_ops.o build/src/cmd/geo.o build/src/cmd/t_stream.o build/src/cmd/scripting.o build/src/cmd/functions.o build/src/cmd/serialize.o build/src/snapshot/snapshot.o build/src/persist/aof.o build/src/cmd/climon.o build/src/cmd/tracking.o build/src/cmd/slowlog.o build/src/cmd/lcs.o build/src/cmd/info_stats.o build/src/cmd/lbsignals.o build/src/core/flipctl.o build/src/core/genthread.o build/src/core/rl2s.o build/src/cmd/cmdgap.o build/src/cmd/pfdebug.o build/src/cmd/cmdmeta.o build/src/cmd/t_sort.o -o build/netcmd-unit -ljemalloc -luring -pthread -lssl -lcrypto -lm -Wl,--wrap=mkstemp -Wl,--wrap=fopen
4365:/bin/bash -lc 'taskset -c 112-127 ./build/netcmd-unit pubsub-timeout > build/deadconf-n9-old-test.log 2>&1' in /home/user/Projects/cx-deadconf-fix
4455:/bin/bash -lc 'cp build/netcmd-unit build/netcmd-n9-old' in /home/user/Projects/cx-deadconf-fix
4570:/bin/bash -lc 'taskset -c 112-127 make -j8 all build/netcmd-unit > build/deadconf-n9-post-build.log 2>&1' in /home/user/Projects/cx-deadconf-fix
5246:/bin/bash -lc 'taskset -c 112-127 ./build/netcmd-unit pubsub-timeout' in /home/user/Projects/cx-deadconf-fix
5251:/bin/bash -lc 'taskset -c 112-127 ./build/netcmd-unit output' in /home/user/Projects/cx-deadconf-fix
5257:/bin/bash -lc 'taskset -c 112-127 ./build/netcmd-unit pubsub' in /home/user/Projects/cx-deadconf-fix

codex
The branch is at `4f6449e12`, and the previous units were `pubsub-timeout`, `pubsub`, and `output`. I’ll first run the revised test against that commit’s timeout condition to confirm it fails, then restore the condition and rerun those units.
exec
/bin/bash -lc "sed -n '6105,6245p' src/core/io_loop.h && rg -n 'try_finalize_close|maybe_finalize_close|finalize_close|retire_client\\(' src/core/io_loop.h && sed -n '545,595p' tests/netcmd_unit.cc" in /home/user/Projects/cx-deadconf-fix
 exited 1 in 0ms:
        if (srv_->read_local_enabled()) {
            fused_executor_->set_read_local_point_writes_precise(
                snapshot.maxmemory == 0 || snapshot.policy == MaxmemoryPolicy::NoEviction);
            fused_executor_->set_read_local_keymiss_notify(
                (snapshot.notify_events & NOTIFY_KEY_MISS) != 0);
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

exec
/bin/bash -lc "git ls-files src tests tomokv.conf Makefile ':*AGENTS.md' && taskset -pc "'$$ && git check-ignore build CODEX-OUT.md' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
Makefile
src/README.md
src/base/README.md
src/base/alloc.h
src/base/numeric.h
src/base/slice.h
src/base/topology.h
src/cmd/README.md
src/cmd/acl.cc
src/cmd/acl.h
src/cmd/acl.inc
src/cmd/acl_categories_generated.h
src/cmd/atomics_glue.inc
src/cmd/auth.h
src/cmd/auth.inc
src/cmd/bitfield.inc
src/cmd/blocking.h
src/cmd/blocking.inc
src/cmd/climon.cc
src/cmd/climon.inc
src/cmd/cmdgap.cc
src/cmd/cmdmeta.cc
src/cmd/cmdmeta.h
src/cmd/cmdmeta_generated.inc
src/cmd/command.h
src/cmd/commands.cc
src/cmd/debug.h
src/cmd/debug_sleep.h
src/cmd/functions.cc
src/cmd/geo.cc
src/cmd/geo.h
src/cmd/glob.cc
src/cmd/hll.cc
src/cmd/hll.h
src/cmd/info_stats.cc
src/cmd/info_stats.h
src/cmd/lbsignals.cc
src/cmd/lcs.cc
src/cmd/lcs.h
src/cmd/multi.h
src/cmd/multi.inc
src/cmd/notify.h
src/cmd/notify.inc
src/cmd/pfdebug.cc
src/cmd/scatter_engine.inc
src/cmd/scripting.cc
src/cmd/scripting.h
src/cmd/serialize.cc
src/cmd/serialize.h
src/cmd/server_tail.cc
src/cmd/server_tail.h
src/cmd/slowlog.cc
src/cmd/slowlog.h
src/cmd/t_hash.cc
src/cmd/t_hash_ttl.cc
src/cmd/t_hash_ttl.h
src/cmd/t_list.cc
src/cmd/t_server.cc
src/cmd/t_set.cc
src/cmd/t_sort.cc
src/cmd/t_sort.h
src/cmd/t_stream.cc
src/cmd/t_stream.h
src/cmd/t_stream_groups.cc
src/cmd/t_string.cc
src/cmd/t_string_notify.cc
src/cmd/t_zset.cc
src/cmd/t_zset.h
src/cmd/t_zset_ops.cc
src/cmd/tracking.cc
src/cmd/xshard.cc
src/cmd/xshard.h
src/cmd/xshard_commands.inc
src/core/README.md
src/core/atomic_admission.h
src/core/atomic_tripwire.h
src/core/config.h
src/core/ex_loop.h
src/core/flip_policy.h
src/core/flipctl.cc
src/core/flipctl.h
src/core/fused_boot_gate.h
src/core/genthread.cc
src/core/genthread.h
src/core/genthread_pipeline.h
src/core/io_loop.h
src/core/iopipe_pipeline.h
src/core/lbsignals.h
src/core/live_config.h
src/core/orthog.h
src/core/placement.h
src/core/pubsub.inc
src/core/pubsub_event.h
src/core/read_local.h
src/core/reorder.h
src/core/rl2s.cc
src/core/server.h
src/core/shard.h
src/core/shutdown_report.h
src/core/signal.h
src/core/signal_doorbell.h
src/core/thread.h
src/core/weighted_lb.h
src/exec/README.md
src/exec/exqueue.h
src/exec/masked_queue.h
src/exec/op.h
src/main.cc
src/net/README.md
src/net/conn.h
src/net/epoll.h
src/net/resp.h
src/net/resp3.h
src/net/rob.h
src/net/tls.cc
src/net/tls.h
src/net/unix_listener.h
src/net/uring.h
src/net/wb.h
src/persist/README.md
src/persist/aof.cc
src/persist/aof.h
src/persist/aof_stream_owner.h
src/snapshot/README.md
src/snapshot/format.h
src/snapshot/snapshot.cc
src/snapshot/snapshot.h
src/store/README.md
src/store/atomic_mvcc.h
src/store/eviction.h
src/store/flatstore.h
src/store/flatstore_atomic.inc
src/store/foreign_read_safety.h
src/store/kv_block_cache.h
src/store/kvobj.h
src/store/read_local_reclaim.h
src/store/read_local_settax.h
src/store/resize_retirement.h
src/store/store_ttl.h
src/store/typeval.h
tests/README.md
tests/_abba_test_fixtures.py
tests/_differ_history.py
tests/_gate_process.py
tests/_lib.py
tests/abba_aslr.py
tests/abba_calibration.py
tests/abba_evidence.py
tests/abba_experiments.py
tests/abba_instrument.py
tests/abba_profile.py
tests/abba_saturation.py
tests/abba_saturation_controls.py
tests/abba_simple.py
tests/abba_worker_affinity.py
tests/abba_workloads.py
tests/abbagate.py
tests/acl.py
tests/acl_categories.py
tests/aclreply.py
tests/aclsel.py
tests/aof.py
tests/aof_frame_order.py
tests/aof_frames.py
tests/aof_fsync.py
tests/aof_rewrite.py
tests/aof_rewrite_matrix.sh
tests/aof_rewrite_trigger_matrix.sh
tests/aof_rewrite_triggers.py
tests/aof_torn_group.py
tests/arity.py
tests/atomfix.py
tests/atomic_hazards.py
tests/atomic_ryow.py
tests/atomic_survivors_unit.cc
tests/atomic_torn.py
tests/atomicwindow.py
tests/auth.py
tests/background_environment_test.py
tests/barrier.py
tests/benchfeat.py
tests/bitfield.py
tests/blocking.py
tests/blockmulti.py
tests/borrow_registry.py
tests/bplus.py
tests/broaden_bench.cc
tests/climon.py
tests/climon2.py
tests/cmdgap.py
tests/cmdgap2.py
tests/cmdlookup_unit.cc
tests/cmdmeta.py
tests/cmdmeta_coverage.py
tests/concur.py
tests/config_parser_test.cc
tests/contarity.py
tests/core_concurrency_unit.cc
tests/debug.py
tests/differ.py
tests/differ_fanout.py
tests/differ_fanout_test.py
tests/differ_gate.sh
tests/differ_seeds.txt
tests/doubles.py
tests/dumprestore.py
tests/dumpttl.py
tests/edgeenc.py
tests/edgeproto.py
tests/edgetime.py
tests/edgetime_persist.sh
tests/evict_battery.py
tests/execatomic.py
tests/execfix.py
tests/execiso.py
tests/expireindex.py
tests/expwide.py
tests/feature_gate.py
tests/flatstore_alloc_fail.py
tests/flip.py
tests/flip_cost_gate.py
tests/flip_multikey_hold.py
tests/flip_ttl.py
tests/flip_under_load.py
tests/flipctl.py
tests/flipctl_unit.cc
tests/flush_capture.py
tests/foreign_read_safety_test.cc
tests/gate.sh
tests/gate_history.py
tests/gate_measurements.json
tests/gate_measurements.py
tests/gate_perf_evidence.json
tests/gate_perf_refs.json
tests/gate_process_test.py
tests/gate_quiet.py
tests/gate_receipt.py
tests/gate_refs.txt
tests/gateplan.py
tests/gates_test.py
tests/geo.py
tests/globcase.py
tests/headline_cells.txt
tests/hexpire.py
tests/hexpire_persist.sh
tests/infofix.py
tests/knobs.py
tests/ktls_keyupdate.cc
tests/lbsignals.py
tests/lcs.py
tests/legacy_reorder_witness.py
tests/limits.py
tests/load_calibration.py
tests/lru_slow.sh
tests/lua_scripting.py
tests/maskflood.py
tests/matrix.sh
tests/mode_equivalence.py
tests/multi_exec.py
tests/multirace.py
tests/multires.py
tests/mutants.py
tests/mutants.registry
tests/mutants.sh
tests/netcmd.py
tests/netcmd_config_unit.cc
tests/netcmd_stream_unit.cc
tests/netcmd_unit.cc
tests/netcmd_unit.h
tests/netcmd_zset_unit.cc
tests/netio.py
tests/niclib.sh
tests/notify.py
tests/orthog.py
tests/overlap.py
tests/parbuild.sh
tests/perf_gate.py
tests/pipeorder.py
tests/pubsub.py
tests/push_tear_repro.py
tests/pushtear.py
tests/read_local_lane.py
tests/read_local_ring_unit.cc
tests/read_local_write_ring_unit.cc
tests/rehash_readonly.py
tests/rehash_waits_unit.cc
tests/reorder_unit.cc
tests/replyoff_xshard.py
tests/replyschema.py
tests/resizefix.py
tests/resp3.py
tests/rl2s.py
tests/rlcache_churn.py
tests/ryow.py
tests/ryow_sort_repro.py
tests/s6.py
tests/scriptatomic.py
tests/scriptsurf.py
tests/servertail.py
tests/session_monotonic.py
tests/shutdown_report.py
tests/slowlog.py
tests/snap_cut_battery.py
tests/snap_typed_race.py
tests/snap_typed_roundtrip.py
tests/sort.py
tests/spinprobe.py
tests/spscmask_flip.py
tests/store_regression.cc
tests/storeorder.py
tests/stream.py
tests/streamgroups.py
tests/tls.py
tests/torn_mset.py
tests/torture.py
tests/tracking.py
tests/waits_unit.cc
tests/watchlive.py
tests/watchlive_gate.sh
tests/wiredump.py
tests/writer_atomic.py
tests/writer_atomic_campaign.py
tests/xacct.py
tests/xmove.py
tests/xscript.py
tests/xshard_dispatch_scale.py
tests/xshard_dispatch_scale.sh
tests/zc.py
tests/zsetops.py
tomokv.conf
pid 1763013's current affinity list: 112-127
build
CODEX-OUT.md

exec
/bin/bash -lc "rg -n '~IoLoop|release_wb_slot|client_released\\(|safe_to_release\\(|~ThreadCtx|~Client|pubsub_disconnect_ready|Client\\(int|recv_armed_' src/core/io_loop.h src/core/thread.h src/core/server.h src/net/conn.h src/core/pubsub.inc && sed -n '1,95p' src/core/io_loop.h && sed -n '930,995p' src/core/pubsub.inc && sed -n '545,600p' tests/netcmd_unit.cc" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
src/core/pubsub.inc:1395:    bool pubsub_disconnect_ready(Client* client) {
src/net/conn.h:291:    explicit Client(int fd) : fd_(fd) {
src/net/conn.h:295:    ~Client() { multi_session_destroy(multi_session_); std::free(rbuf_); }
src/net/conn.h:355:    bool recv_armed() const { return recv_armed_; }
src/net/conn.h:356:    void set_recv_armed(bool v) { recv_armed_ = v; }
src/net/conn.h:712:    bool safe_to_release() {
src/net/conn.h:714:               !recv_armed_ && !send_inflight_ &&        // the KERNEL holds no pointer into us
src/net/conn.h:792:    bool      recv_armed_    = false;
src/core/io_loop.h:142:    ~IoLoop() {
src/core/io_loop.h:149:            srv_->client_released();
src/core/io_loop.h:1003:    // that "arms" a uring recv performs the recv itself, and recv_armed_ changes meaning to
src/core/io_loop.h:1028:    // Draining fully is the edge-triggered obligation; stopping early WITHOUT setting recv_armed_
src/core/io_loop.h:1105:    // the whole operation, and the edge that satisfies it is already on its way. recv_armed_ is
src/core/io_loop.h:1768:        self_->release_wb_slot(client->wb_slot());
src/core/io_loop.h:4786:            } else if (c->closing() && !tls_output && c->safe_to_release()) {
src/core/io_loop.h:4787:                if (pubsub_disconnect_ready(c)) {
src/core/io_loop.h:5416:            } else if (c->closing() && !tls_output && c->safe_to_release()) {
src/core/io_loop.h:5417:                if (pubsub_disconnect_ready(c)) {
src/core/io_loop.h:5671:            // harmful: recv_armed_ means "an edge is owed", not "the kernel holds a pointer into
src/core/io_loop.h:5682:                // refuses to re-arm a closing connection, so recv_armed_ falls to false as soon as
src/core/io_loop.h:5683:                // the outstanding recv completes and safe_to_release() opens. Under epoll nothing
src/core/io_loop.h:5685:                // that is simply false. Leaving it set makes safe_to_release() refuse forever, and
src/core/io_loop.h:5782:            else if (c->closing() && !tls_output && c->safe_to_release()) {
src/core/io_loop.h:5786:                if (!pubsub_disconnect_ready(c)) { idx++; }
src/core/io_loop.h:6138:            // Under epoll recv_armed_ records an owed EDGE, not a kernel-held buffer pointer, and
src/core/io_loop.h:6139:            // a torn-down socket owes nothing. Leaving it set would make safe_to_release() refuse
src/core/io_loop.h:6160:        if (!pubsub_disconnect_ready(c)) { mark_active(c); return; }
src/core/io_loop.h:6168:        if (!c->safe_to_release() || !client_executor_quiesced(c) ||
src/core/io_loop.h:6169:            !c->safe_to_release()) { mark_active(c); return; }
src/core/io_loop.h:6173:        self_->release_wb_slot(c->wb_slot());
src/core/io_loop.h:6177:        srv_->client_released();
src/core/io_loop.h:6406:        ~ClientRoutingMigration() {
src/core/server.h:148:        ~ClientWorkScope() {
src/core/server.h:2197:    void client_released() {
src/core/thread.h:1083:    void release_wb_slot(uint32_t s) {
// io_loop.h — accepts, receives, parses, routes, publishes, retires, and sends for its clients.
// In fused mode the same physical thread also executes its owned shards; split mode hands tasks
// to executor threads. Reply retirement and sending stay with the connection's IO owner.
//
//   out  task_in of the shard's owner        a parsed op to execute
//   in   ready mask / client_in             completed ops to retire and send
#pragma once
#include <array>
#include <deque>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>
#include <cstdio>
#include <cstdlib>
#include <new>
#include <memory>
#include <string>
#include <type_traits>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include "server.h"
#include "iopipe_pipeline.h"
#include "signal.h"
#include "ex_loop.h"
#include "genthread_pipeline.h"
#include "../net/conn.h"
#include "../net/resp.h"
#include "../net/uring.h"
#include "../net/epoll.h"
#include "../net/wb.h"
#include "../net/tls.h"
#include "../cmd/command.h"
#include "../cmd/debug_sleep.h"
#include "../cmd/slowlog.h"
#include "../cmd/blocking.h"
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
    // that batching window is what a pipelined publisher's coalescing is made of. Out-of-line and
    // cold, so a server with no subscribers pays one bool test per pass and nothing else.
    __attribute__((noinline)) uint32_t pubsub_pass_flush() {
        uint32_t work = 0;
        for (int guard = 0; guard < 8; guard++) {
            if (!pubsub_local_events_.empty()) work += pubsub_drain_events();
            if (pubsub_outbox_dirty_.empty()) break;
            work += pubsub_flush_outboxes();
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
            event->shard = shard;
            event->rebind = true;
            events.push_back(event);
            return event;
        };
        auto exact = [&](const auto& values, bool shard) {
            std::unordered_map<uint32_t, PubSubEvent*> homes;
            for (const std::string& value : values) {
                const uint32_t home = pubsub_home_for(value);
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
    else if (mode == "pubsub-timeout") R::pubsub_timeout();
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

exec
/bin/bash -lc "sed -n '135,169p' src/core/io_loop.h && sed -n '1390,1435p' src/core/pubsub.inc && sed -n '1077,1090p' src/core/thread.h && sed -n '2190,2205p' src/core/server.h && sed -n '705,725p' src/net/conn.h" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
        wb_.set_cold_send_classification(
            srv_->cfg().thread_mode == ThreadMode::Fused &&
            srv_->cfg().overlap != 0);
        initialized_ = true;
        return dormant || activate();
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
        setsockopt(fd, SOL_SOCKET, SO_REUSEPORT, &one, sizeof(one));
        if (defer_accept) setsockopt(fd, IPPROTO_TCP, TCP_DEFER_ACCEPT, &one, sizeof(one));
        sockaddr_in sa{};
        sa.sin_family = AF_INET;
        sa.sin_port   = htons(port);
        if (::inet_pton(AF_INET, addr, &sa.sin_addr) != 1) { ::close(fd); return -1; }
        if (::bind(fd, reinterpret_cast<sockaddr*>(&sa), sizeof(sa)) != 0) { ::close(fd); return -1; }
        if (::listen(fd, static_cast<int>(backlog)) != 0) { ::close(fd); return -1; }
        return fd;
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
            free_slots_.reserve(ReadyMask::kSlots);
            return true;
        } catch (...) {
            return false;
        }
    }
    void release_wb_slot(uint32_t s) {
        if (s == kNoWbSlot || s >= slots_.size()) return;
        ready_.clear(s);
        slots_[s] = nullptr;
        free_slots_.push_back(s);
    }
    Client* wb_slot_client(uint32_t s) { return s < slots_.size() ? slots_[s] : nullptr; }


    uint32_t maxclients() const { return live_maxclients_.load(std::memory_order_relaxed); }
    void set_maxclients(uint32_t value) {
        live_maxclients_.store(value, std::memory_order_relaxed);
    }
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

apply patch
patch: completed
/home/user/Projects/cx-deadconf-fix/tests/netcmd_unit.cc
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 

exec
/bin/bash -lc 'taskset -c 112-127 make -j8 build/netcmd-unit > build/deadconf-n9-correction-old-build.log 2>&1' in /home/user/Projects/cx-deadconf-fix
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 

apply patch
patch: completed
/home/user/Projects/cx-deadconf-fix/tomokv.conf
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8..7c52a3d60efeb4c859baa2e95bbe2566d7e76c9c
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

exec
/bin/bash -lc 'tail -6 build/deadconf-n9-correction-old-build.log' in /home/user/Projects/cx-deadconf-fix
exec
/bin/bash -lc 'git diff --check && git diff --stat && git diff -- tests/netcmd_unit.cc tomokv.conf' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -Wno-mismatched-new-delete -I. -c tests/netcmd_unit.cc -o build/tests/netcmd_unit.o

 succeeded in 0ms:
 tests/netcmd_unit.cc | 16 ++++++++++++++--
 tomokv.conf          |  4 ++--
 2 files changed, 16 insertions(+), 4 deletions(-)
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bf..c9c15c48d 100644
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@ struct NetcmdRegression {
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0c..7c52a3d60 100644
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8..7c52a3d60efeb4c859baa2e95bbe2566d7e76c9c
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8..7c52a3d60efeb4c859baa2e95bbe2566d7e76c9c
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

 succeeded in 38786ms:
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8..7c52a3d60efeb4c859baa2e95bbe2566d7e76c9c
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

exec
/bin/bash -lc 'taskset -c 112-127 ./build/netcmd-unit pubsub-timeout > build/deadconf-n9-correction-old-test.log 2>&1' in /home/user/Projects/cx-deadconf-fix
 exited 1 in 0ms:
exec
/bin/bash -lc 'cat build/deadconf-n9-correction-old-test.log && git diff --exit-code 4f6449e12 -- src/core/io_loop.h' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
FAIL: idle RESP3 SUBSCRIBE client must remain exempt from timeout

diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8..7c52a3d60efeb4c859baa2e95bbe2566d7e76c9c
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

codex
The revised test fails against `4f6449e12` with “idle RESP3 SUBSCRIBE client must remain exempt from timeout.” It also checks that a plain idle client closes. I’m now restoring the original condition and rebuilding.
exec
/bin/bash -lc 'cp build/netcmd-unit build/netcmd-n9-correction-old' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
apply patch
patch: completed
/home/user/Projects/cx-deadconf-fix/src/core/io_loop.h
diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index e6fe5a7167a073d2164527ab89510e090970c9a0..30f6fa514632ac41a2ee60e2e07ec936c0dfcd09
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
-                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
+                cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8..7c52a3d60efeb4c859baa2e95bbe2566d7e76c9c
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

exec
/bin/bash -lc 'taskset -c 112-127 make -j8 all build/netcmd-unit > build/deadconf-n9-correction-post-build.log 2>&1' in /home/user/Projects/cx-deadconf-fix
diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index e6fe5a7167a073d2164527ab89510e090970c9a0..30f6fa514632ac41a2ee60e2e07ec936c0dfcd09
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
-                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
+                cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8..7c52a3d60efeb4c859baa2e95bbe2566d7e76c9c
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

exec
/bin/bash -lc 'tail -5 build/deadconf-n9-correction-post-build.log' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -I. -c src/cmd/tracking.cc -o build/src/cmd/tracking.o
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -I. -c src/cmd/server_tail.cc -o build/src/cmd/server_tail.o
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -I. -c src/cmd/slowlog.cc -o build/src/cmd/slowlog.o
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -I. -c src/cmd/lcs.cc -o build/src/cmd/lcs.o
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -I. -c src/cmd/info_stats.cc -o build/src/cmd/info_stats.o

exec
/bin/bash -lc 'git diff --check && git diff --exit-code 4f6449e12''^ -- src/core/io_loop.h && git diff --stat && git diff -- src/core/io_loop.h tests/netcmd_unit.cc tomokv.conf' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
 src/core/io_loop.h | 4 ++--
 1 file changed, 2 insertions(+), 2 deletions(-)
diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index e6fe5a716..30f6fa514 100644
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@ ordinary_shard_ready:
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
-                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
+                cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {

diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index e6fe5a7167a073d2164527ab89510e090970c9a0..30f6fa514632ac41a2ee60e2e07ec936c0dfcd09
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
-                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
+                cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8..7c52a3d60efeb4c859baa2e95bbe2566d7e76c9c
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

exec
/bin/bash -lc 'git status --short --branch && git diff --cached --stat && git log -3 --oneline' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
## cx-deadconf-fix-items
 M src/core/io_loop.h
cae99a51a autosave: cx-deadconf-fix 12:28 (2 files)
4f6449e12 limit subscriber idle-timeout exemption to RESP2
528cb0b15 reject ACL selectors and correct ownership and list-limit comments

diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index e6fe5a7167a073d2164527ab89510e090970c9a0..30f6fa514632ac41a2ee60e2e07ec936c0dfcd09
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
-                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
+                cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8..7c52a3d60efeb4c859baa2e95bbe2566d7e76c9c
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

exec
/bin/bash -lc 'tail -4 build/deadconf-n9-correction-post-build.log' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -Wno-mismatched-new-delete -I. -c tests/netcmd_unit.cc -o build/tests/netcmd_unit.o
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -Wno-mismatched-new-delete -I. -c tests/netcmd_stream_unit.cc -o build/tests/netcmd_stream_unit.o
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -Wno-mismatched-new-delete -I. -c tests/netcmd_zset_unit.cc -o build/tests/netcmd_zset_unit.o
g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -Wno-mismatched-new-delete -I. -c tests/netcmd_config_unit.cc -o build/tests/netcmd_config_unit.o

exec
/bin/bash -lc 'git show --format=fuller --stat HEAD && git diff 4f6449e12 --stat && git diff 4f6449e12 -- tests/netcmd_unit.cc tomokv.conf && git status --porcelain=v1 --untracked-files=all' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
commit cae99a51a71f943badfc7c609c6946b4735e2859
Author:     autosave <autosave@localhost>
AuthorDate: Sun Sep 13 12:28:59 2026 +0800
Commit:     autosave <autosave@localhost>
CommitDate: Sun Sep 13 12:28:59 2026 +0800

    autosave: cx-deadconf-fix 12:28 (2 files)

 CODEX-OUT.round1.md          | 54211 +++++++++++++++++++++++++++++++++++++++++
 CODEX-OUT.round2-N9-wrong.md |  5976 +++++
 tests/netcmd_unit.cc         |    16 +-
 tomokv.conf                  |     4 +-
 4 files changed, 60203 insertions(+), 4 deletions(-)
 CODEX-OUT.round1.md          | 54211 +++++++++++++++++++++++++++++++++++++++++
 CODEX-OUT.round2-N9-wrong.md |  5976 +++++
 src/core/io_loop.h           |     4 +-
 tests/netcmd_unit.cc         |    16 +-
 tomokv.conf                  |     4 +-
 5 files changed, 60205 insertions(+), 6 deletions(-)
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bf..c9c15c48d 100644
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@ struct NetcmdRegression {
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0c..7c52a3d60 100644
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive
 M src/core/io_loop.h

diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index e6fe5a7167a073d2164527ab89510e090970c9a0..30f6fa514632ac41a2ee60e2e07ec936c0dfcd09
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
-                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
+                cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8..7c52a3d60efeb4c859baa2e95bbe2566d7e76c9c
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

 succeeded in 74906ms:
codex
The restored `io_loop.h` matches its pre-`4f6449e12` contents exactly, and the rebuild is still running. An autosave also captured the edits and two existing transcript files; I’ll preserve the transcripts on disk and keep the final correction to the three requested files.
diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index e6fe5a7167a073d2164527ab89510e090970c9a0..30f6fa514632ac41a2ee60e2e07ec936c0dfcd09
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
-                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
+                cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8..7c52a3d60efeb4c859baa2e95bbe2566d7e76c9c
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

exec
/bin/bash -lc "rg -n 'warning:|error:' build/deadconf-n9-correction-old-build.log build/deadconf-n9-correction-post-build.log" in /home/user/Projects/cx-deadconf-fix
 exited 1 in 0ms:
exec
/bin/bash -lc 'taskset -c 112-127 ./build/netcmd-unit pubsub-timeout' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
ok: netcmd pubsub-timeout

exec
/bin/bash -lc 'taskset -c 112-127 ./build/netcmd-unit pubsub' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
ok: netcmd pubsub

exec
/bin/bash -lc 'taskset -c 112-127 ./build/netcmd-unit output' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
Client id=1 closed for overcoming of output buffer limits.
ok: netcmd output

diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index e6fe5a7167a073d2164527ab89510e090970c9a0..30f6fa514632ac41a2ee60e2e07ec936c0dfcd09
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
-                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
+                cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8..7c52a3d60efeb4c859baa2e95bbe2566d7e76c9c
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

codex
The build and all three units passed on cores 112–127. The timeout test keeps RESP2 and RESP3 subscribers open while closing plain idle clients; its old-code run failed as required. I’m committing the correction now.
exec
/bin/bash -lc 'git status --short --branch && git log -2 --oneline && git diff 4f6449e12 --check' in /home/user/Projects/cx-deadconf-fix
 exited 2 in 0ms:
## cx-deadconf-fix-items
 M src/core/io_loop.h
cae99a51a autosave: cx-deadconf-fix 12:28 (2 files)
4f6449e12 limit subscriber idle-timeout exemption to RESP2
CODEX-OUT.round1.md:1489: trailing whitespace.
+web search: 
CODEX-OUT.round1.md:5598: trailing whitespace.
+web search: 
CODEX-OUT.round1.md:8357: trailing whitespace.
+rg -n 'friend.*Netcmd|climon_conn_find|struct ClimonConn' src/core/io_loop.h src/core/server.h src/cmd/climon* 
CODEX-OUT.round1.md:8684: trailing whitespace.
+ 
CODEX-OUT.round1.md:8710: trailing whitespace.
+ 
CODEX-OUT.round1.md:8753: trailing whitespace.
+ 
CODEX-OUT.round1.md:8786: trailing whitespace.
+ 
CODEX-OUT.round1.md:8812: trailing whitespace.
+ 
CODEX-OUT.round1.md:8855: trailing whitespace.
+ 
CODEX-OUT.round1.md:9066: trailing whitespace.
+ 
CODEX-OUT.round1.md:9092: trailing whitespace.
+ 
CODEX-OUT.round1.md:9135: trailing whitespace.
+ 
CODEX-OUT.round1.md:9199: trailing whitespace.
+ 
CODEX-OUT.round1.md:9225: trailing whitespace.
+ 
CODEX-OUT.round1.md:9268: trailing whitespace.
+ 
CODEX-OUT.round1.md:9312: trailing whitespace.
+ 
CODEX-OUT.round1.md:9338: trailing whitespace.
+ 
CODEX-OUT.round1.md:9381: trailing whitespace.
+ 
CODEX-OUT.round1.md:9538: trailing whitespace.
+ 
CODEX-OUT.round1.md:9564: trailing whitespace.
+ 
CODEX-OUT.round1.md:9607: trailing whitespace.
+ 
CODEX-OUT.round1.md:9705: trailing whitespace.
+ 
CODEX-OUT.round1.md:9731: trailing whitespace.
+ 
CODEX-OUT.round1.md:9774: trailing whitespace.
+ 
CODEX-OUT.round1.md:9843: trailing whitespace.
+ 
CODEX-OUT.round1.md:9869: trailing whitespace.
+ 
CODEX-OUT.round1.md:9912: trailing whitespace.
+ 
CODEX-OUT.round1.md:9954: trailing whitespace.
+ 
CODEX-OUT.round1.md:9980: trailing whitespace.
+ 
CODEX-OUT.round1.md:10023: trailing whitespace.
+ 
CODEX-OUT.round1.md:10061: trailing whitespace.
+ 
CODEX-OUT.round1.md:10087: trailing whitespace.
+ 
CODEX-OUT.round1.md:10130: trailing whitespace.
+ 
CODEX-OUT.round1.md:10195: trailing whitespace.
+ 
CODEX-OUT.round1.md:10242: trailing whitespace.
+ 
CODEX-OUT.round1.md:10322: trailing whitespace.
+ 
CODEX-OUT.round1.md:10348: trailing whitespace.
+ 
CODEX-OUT.round1.md:10391: trailing whitespace.
+ 
CODEX-OUT.round1.md:10454: trailing whitespace.
+ 
CODEX-OUT.round1.md:10501: trailing whitespace.
+ 
CODEX-OUT.round1.md:10581: trailing whitespace.
+ 
CODEX-OUT.round1.md:10607: trailing whitespace.
+ 
CODEX-OUT.round1.md:10650: trailing whitespace.
+ 
CODEX-OUT.round1.md:10993: trailing whitespace.
+ 
CODEX-OUT.round1.md:11040: trailing whitespace.
+ 
CODEX-OUT.round1.md:11120: trailing whitespace.
+ 
CODEX-OUT.round1.md:11146: trailing whitespace.
+ 
CODEX-OUT.round1.md:11189: trailing whitespace.
+ 
CODEX-OUT.round1.md:11254: trailing whitespace.
+ 
CODEX-OUT.round1.md:11301: trailing whitespace.
+ 
CODEX-OUT.round1.md:11381: trailing whitespace.
+ 
CODEX-OUT.round1.md:11407: trailing whitespace.
+ 
CODEX-OUT.round1.md:11450: trailing whitespace.
+ 
CODEX-OUT.round1.md:11780: trailing whitespace.
+ 
CODEX-OUT.round1.md:11827: trailing whitespace.
+ 
CODEX-OUT.round1.md:11907: trailing whitespace.
+ 
CODEX-OUT.round1.md:11933: trailing whitespace.
+ 
CODEX-OUT.round1.md:11976: trailing whitespace.
+ 
CODEX-OUT.round1.md:12125: trailing whitespace.
+ 
CODEX-OUT.round1.md:12172: trailing whitespace.
+ 
CODEX-OUT.round1.md:12252: trailing whitespace.
+ 
CODEX-OUT.round1.md:12278: trailing whitespace.
+ 
CODEX-OUT.round1.md:12321: trailing whitespace.
+ 
CODEX-OUT.round1.md:12511: trailing whitespace.
+ 
CODEX-OUT.round1.md:12558: trailing whitespace.
+ 
CODEX-OUT.round1.md:12638: trailing whitespace.
+ 
CODEX-OUT.round1.md:12664: trailing whitespace.
+ 
CODEX-OUT.round1.md:12707: trailing whitespace.
+ 
CODEX-OUT.round1.md:12777: trailing whitespace.
+ 
CODEX-OUT.round1.md:12824: trailing whitespace.
+ 
CODEX-OUT.round1.md:12904: trailing whitespace.
+ 
CODEX-OUT.round1.md:12930: trailing whitespace.
+ 
CODEX-OUT.round1.md:12973: trailing whitespace.
+ 
CODEX-OUT.round1.md:13050: trailing whitespace.
+ 
CODEX-OUT.round1.md:13097: trailing whitespace.
+ 
CODEX-OUT.round1.md:13177: trailing whitespace.
+ 
CODEX-OUT.round1.md:13203: trailing whitespace.
+ 
CODEX-OUT.round1.md:13246: trailing whitespace.
+ 
CODEX-OUT.round1.md:13337: trailing whitespace.
+ 
CODEX-OUT.round1.md:13384: trailing whitespace.
+ 
CODEX-OUT.round1.md:13464: trailing whitespace.
+ 
CODEX-OUT.round1.md:13490: trailing whitespace.
+ 
CODEX-OUT.round1.md:13533: trailing whitespace.
+ 
CODEX-OUT.round1.md:13600: trailing whitespace.
+ 
CODEX-OUT.round1.md:13647: trailing whitespace.
+ 
CODEX-OUT.round1.md:13727: trailing whitespace.
+ 
CODEX-OUT.round1.md:13753: trailing whitespace.
+ 
CODEX-OUT.round1.md:13798: trailing whitespace.
+ 
CODEX-OUT.round1.md:13806: trailing whitespace.
+ 
CODEX-OUT.round1.md:13875: trailing whitespace.
+ 
CODEX-OUT.round1.md:13922: trailing whitespace.
+ 
CODEX-OUT.round1.md:14002: trailing whitespace.
+ 
CODEX-OUT.round1.md:14028: trailing whitespace.
+ 
CODEX-OUT.round1.md:14073: trailing whitespace.
+ 
CODEX-OUT.round1.md:14081: trailing whitespace.
+ 
CODEX-OUT.round1.md:14155: trailing whitespace.
+ 
CODEX-OUT.round1.md:14202: trailing whitespace.
+ 
CODEX-OUT.round1.md:14282: trailing whitespace.
+ 
CODEX-OUT.round1.md:14308: trailing whitespace.
+ 
CODEX-OUT.round1.md:14353: trailing whitespace.
+ 
CODEX-OUT.round1.md:14361: trailing whitespace.
+ 
CODEX-OUT.round1.md:14441: trailing whitespace.
+ 
CODEX-OUT.round1.md:14488: trailing whitespace.
+ 
CODEX-OUT.round1.md:14568: trailing whitespace.
+ 
CODEX-OUT.round1.md:14594: trailing whitespace.
+ 
CODEX-OUT.round1.md:14639: trailing whitespace.
+ 
CODEX-OUT.round1.md:14647: trailing whitespace.
+ 
CODEX-OUT.round1.md:14725: trailing whitespace.
+ 
CODEX-OUT.round1.md:14772: trailing whitespace.
+ 
CODEX-OUT.round1.md:14852: trailing whitespace.
+ 
CODEX-OUT.round1.md:14878: trailing whitespace.
+ 
CODEX-OUT.round1.md:14923: trailing whitespace.
+ 
CODEX-OUT.round1.md:14931: trailing whitespace.
+ 
CODEX-OUT.round1.md:15163: trailing whitespace.
+ 
CODEX-OUT.round1.md:15210: trailing whitespace.
+ 
CODEX-OUT.round1.md:15290: trailing whitespace.
+ 
CODEX-OUT.round1.md:15316: trailing whitespace.
+ 
CODEX-OUT.round1.md:15361: trailing whitespace.
+ 
CODEX-OUT.round1.md:15369: trailing whitespace.
+ 
CODEX-OUT.round1.md:15558: trailing whitespace.
+ 
CODEX-OUT.round1.md:15605: trailing whitespace.
+ 
CODEX-OUT.round1.md:15685: trailing whitespace.
+ 
CODEX-OUT.round1.md:15711: trailing whitespace.
+ 
CODEX-OUT.round1.md:15756: trailing whitespace.
+ 
CODEX-OUT.round1.md:15764: trailing whitespace.
+ 
CODEX-OUT.round1.md:15832: trailing whitespace.
+ 
CODEX-OUT.round1.md:15879: trailing whitespace.
+ 
CODEX-OUT.round1.md:15959: trailing whitespace.
+ 
CODEX-OUT.round1.md:15985: trailing whitespace.
+ 
CODEX-OUT.round1.md:16030: trailing whitespace.
+ 
CODEX-OUT.round1.md:16139: trailing whitespace.
+ 
CODEX-OUT.round1.md:16205: trailing whitespace.
+ 
CODEX-OUT.round1.md:16252: trailing whitespace.
+ 
CODEX-OUT.round1.md:16332: trailing whitespace.
+ 
CODEX-OUT.round1.md:16358: trailing whitespace.
+ 
CODEX-OUT.round1.md:16403: trailing whitespace.
+ 
CODEX-OUT.round1.md:16512: trailing whitespace.
+ 
CODEX-OUT.round1.md:16586: trailing whitespace.
+ 
CODEX-OUT.round1.md:16633: trailing whitespace.
+ 
CODEX-OUT.round1.md:16713: trailing whitespace.
+ 
CODEX-OUT.round1.md:16739: trailing whitespace.
+ 
CODEX-OUT.round1.md:16784: trailing whitespace.
+ 
CODEX-OUT.round1.md:16893: trailing whitespace.
+ 
CODEX-OUT.round1.md:16960: trailing whitespace.
+ 
CODEX-OUT.round1.md:17007: trailing whitespace.
+ 
CODEX-OUT.round1.md:17087: trailing whitespace.
+ 
CODEX-OUT.round1.md:17113: trailing whitespace.
+ 
CODEX-OUT.round1.md:17158: trailing whitespace.
+ 
CODEX-OUT.round1.md:17267: trailing whitespace.
+ 
CODEX-OUT.round1.md:17356: trailing whitespace.
+ 
CODEX-OUT.round1.md:17403: trailing whitespace.
+ 
CODEX-OUT.round1.md:17483: trailing whitespace.
+ 
CODEX-OUT.round1.md:17509: trailing whitespace.
+ 
CODEX-OUT.round1.md:17554: trailing whitespace.
+ 
CODEX-OUT.round1.md:17663: trailing whitespace.
+ 
CODEX-OUT.round1.md:17730: trailing whitespace.
+ 
CODEX-OUT.round1.md:17777: trailing whitespace.
+ 
CODEX-OUT.round1.md:17857: trailing whitespace.
+ 
CODEX-OUT.round1.md:17883: trailing whitespace.
+ 
CODEX-OUT.round1.md:17928: trailing whitespace.
+ 
CODEX-OUT.round1.md:18037: trailing whitespace.
+ 
CODEX-OUT.round1.md:18103: trailing whitespace.
+ 
CODEX-OUT.round1.md:18150: trailing whitespace.
+ 
CODEX-OUT.round1.md:18230: trailing whitespace.
+ 
CODEX-OUT.round1.md:18256: trailing whitespace.
+ 
CODEX-OUT.round1.md:18301: trailing whitespace.
+ 
CODEX-OUT.round1.md:18410: trailing whitespace.
+ 
CODEX-OUT.round1.md:18639: trailing whitespace.
+ 
CODEX-OUT.round1.md:18686: trailing whitespace.
+ 
CODEX-OUT.round1.md:18766: trailing whitespace.
+ 
CODEX-OUT.round1.md:18792: trailing whitespace.
+ 
CODEX-OUT.round1.md:18837: trailing whitespace.
+ 
CODEX-OUT.round1.md:18946: trailing whitespace.
+ 
CODEX-OUT.round1.md:19206: trailing whitespace.
+ 
CODEX-OUT.round1.md:19253: trailing whitespace.
+ 
CODEX-OUT.round1.md:19333: trailing whitespace.
+ 
CODEX-OUT.round1.md:19359: trailing whitespace.
+ 
CODEX-OUT.round1.md:19404: trailing whitespace.
+ 
CODEX-OUT.round1.md:19513: trailing whitespace.
+ 
CODEX-OUT.round1.md:19586: trailing whitespace.
+ 
CODEX-OUT.round1.md:19633: trailing whitespace.
+ 
CODEX-OUT.round1.md:19713: trailing whitespace.
+ 
CODEX-OUT.round1.md:19739: trailing whitespace.
+ 
CODEX-OUT.round1.md:19784: trailing whitespace.
+ 
CODEX-OUT.round1.md:19893: trailing whitespace.
+ 
CODEX-OUT.round1.md:19935: trailing whitespace.
+ 
CODEX-OUT.round1.md:19954: trailing whitespace.
+ 
CODEX-OUT.round1.md:19957: trailing whitespace.
+ 
CODEX-OUT.round1.md:20040: trailing whitespace.
+ 
CODEX-OUT.round1.md:20110: trailing whitespace.
+ 
CODEX-OUT.round1.md:20212: trailing whitespace.
+ 
CODEX-OUT.round1.md:20238: trailing whitespace.
+ 
CODEX-OUT.round1.md:20283: trailing whitespace.
+ 
CODEX-OUT.round1.md:20392: trailing whitespace.
+ 
CODEX-OUT.round1.md:20431: trailing whitespace.
+ 
CODEX-OUT.round1.md:20450: trailing whitespace.
+ 
CODEX-OUT.round1.md:20453: trailing whitespace.
+ 
CODEX-OUT.round1.md:20536: trailing whitespace.
+ 
CODEX-OUT.round1.md:20606: trailing whitespace.
+ 
CODEX-OUT.round1.md:20708: trailing whitespace.
+ 
CODEX-OUT.round1.md:20734: trailing whitespace.
+ 
CODEX-OUT.round1.md:20779: trailing whitespace.
+ 
CODEX-OUT.round1.md:20888: trailing whitespace.
+ 
CODEX-OUT.round1.md:20960: trailing whitespace.
+ 
CODEX-OUT.round1.md:20979: trailing whitespace.
+ 
CODEX-OUT.round1.md:20982: trailing whitespace.
+ 
CODEX-OUT.round1.md:21065: trailing whitespace.
+ 
CODEX-OUT.round1.md:21135: trailing whitespace.
+ 
CODEX-OUT.round1.md:21237: trailing whitespace.
+ 
CODEX-OUT.round1.md:21263: trailing whitespace.
+ 
CODEX-OUT.round1.md:21308: trailing whitespace.
+ 
CODEX-OUT.round1.md:21417: trailing whitespace.
+ 
CODEX-OUT.round1.md:21499: trailing whitespace.
+ 
CODEX-OUT.round1.md:21518: trailing whitespace.
+ 
CODEX-OUT.round1.md:21521: trailing whitespace.
+ 
CODEX-OUT.round1.md:21604: trailing whitespace.
+ 
CODEX-OUT.round1.md:21674: trailing whitespace.
+ 
CODEX-OUT.round1.md:21776: trailing whitespace.
+ 
CODEX-OUT.round1.md:21802: trailing whitespace.
+ 
CODEX-OUT.round1.md:21847: trailing whitespace.
+ 
CODEX-OUT.round1.md:21956: trailing whitespace.
+ 
CODEX-OUT.round1.md:22134: trailing whitespace.
+ 
CODEX-OUT.round1.md:22153: trailing whitespace.
+ 
CODEX-OUT.round1.md:22156: trailing whitespace.
+ 
CODEX-OUT.round1.md:22239: trailing whitespace.
+ 
CODEX-OUT.round1.md:22309: trailing whitespace.
+ 
CODEX-OUT.round1.md:22411: trailing whitespace.
+ 
CODEX-OUT.round1.md:22437: trailing whitespace.
+ 
CODEX-OUT.round1.md:22482: trailing whitespace.
+ 
CODEX-OUT.round1.md:22591: trailing whitespace.
+ 
CODEX-OUT.round1.md:22722: trailing whitespace.
+ 
CODEX-OUT.round1.md:22741: trailing whitespace.
+ 
CODEX-OUT.round1.md:22744: trailing whitespace.
+ 
CODEX-OUT.round1.md:22827: trailing whitespace.
+ 
CODEX-OUT.round1.md:22897: trailing whitespace.
+ 
CODEX-OUT.round1.md:22999: trailing whitespace.
+ 
CODEX-OUT.round1.md:23025: trailing whitespace.
+ 
CODEX-OUT.round1.md:23070: trailing whitespace.
+ 
CODEX-OUT.round1.md:23179: trailing whitespace.
+ 
CODEX-OUT.round1.md:23310: trailing whitespace.
+ 
CODEX-OUT.round1.md:23329: trailing whitespace.
+ 
CODEX-OUT.round1.md:23332: trailing whitespace.
+ 
CODEX-OUT.round1.md:23415: trailing whitespace.
+ 
CODEX-OUT.round1.md:23485: trailing whitespace.
+ 
CODEX-OUT.round1.md:23587: trailing whitespace.
+ 
CODEX-OUT.round1.md:23613: trailing whitespace.
+ 
CODEX-OUT.round1.md:23658: trailing whitespace.
+ 
CODEX-OUT.round1.md:23767: trailing whitespace.
+ 
CODEX-OUT.round1.md:23911: trailing whitespace.
+ 
CODEX-OUT.round1.md:23930: trailing whitespace.
+ 
CODEX-OUT.round1.md:23933: trailing whitespace.
+ 
CODEX-OUT.round1.md:24016: trailing whitespace.
+ 
CODEX-OUT.round1.md:24086: trailing whitespace.
+ 
CODEX-OUT.round1.md:24188: trailing whitespace.
+ 
CODEX-OUT.round1.md:24214: trailing whitespace.
+ 
CODEX-OUT.round1.md:24259: trailing whitespace.
+ 
CODEX-OUT.round1.md:24368: trailing whitespace.
+ 
CODEX-OUT.round1.md:24498: trailing whitespace.
+ 
CODEX-OUT.round1.md:24517: trailing whitespace.
+ 
CODEX-OUT.round1.md:24520: trailing whitespace.
+ 
CODEX-OUT.round1.md:24603: trailing whitespace.
+ 
CODEX-OUT.round1.md:24673: trailing whitespace.
+ 
CODEX-OUT.round1.md:24775: trailing whitespace.
+ 
CODEX-OUT.round1.md:24801: trailing whitespace.
+ 
CODEX-OUT.round1.md:24846: trailing whitespace.
+ 
CODEX-OUT.round1.md:24982: trailing whitespace.
+ 
CODEX-OUT.round1.md:25111: trailing whitespace.
+ 
CODEX-OUT.round1.md:25130: trailing whitespace.
+ 
CODEX-OUT.round1.md:25133: trailing whitespace.
+ 
CODEX-OUT.round1.md:25216: trailing whitespace.
+ 
CODEX-OUT.round1.md:25286: trailing whitespace.
+ 
CODEX-OUT.round1.md:25388: trailing whitespace.
+ 
CODEX-OUT.round1.md:25414: trailing whitespace.
+ 
CODEX-OUT.round1.md:25459: trailing whitespace.
+ 
CODEX-OUT.round1.md:25595: trailing whitespace.
+ 
CODEX-OUT.round1.md:25724: trailing whitespace.
+ 
CODEX-OUT.round1.md:25743: trailing whitespace.
+ 
CODEX-OUT.round1.md:25746: trailing whitespace.
+ 
CODEX-OUT.round1.md:25829: trailing whitespace.
+ 
CODEX-OUT.round1.md:25899: trailing whitespace.
+ 
CODEX-OUT.round1.md:26001: trailing whitespace.
+ 
CODEX-OUT.round1.md:26027: trailing whitespace.
+ 
CODEX-OUT.round1.md:26072: trailing whitespace.
+ 
CODEX-OUT.round1.md:26208: trailing whitespace.
+ 
CODEX-OUT.round1.md:26367: trailing whitespace.
+ 
CODEX-OUT.round1.md:26386: trailing whitespace.
+ 
CODEX-OUT.round1.md:26389: trailing whitespace.
+ 
CODEX-OUT.round1.md:26472: trailing whitespace.
+ 
CODEX-OUT.round1.md:26542: trailing whitespace.
+ 
CODEX-OUT.round1.md:26644: trailing whitespace.
+ 
CODEX-OUT.round1.md:26670: trailing whitespace.
+ 
CODEX-OUT.round1.md:26715: trailing whitespace.
+ 
CODEX-OUT.round1.md:26851: trailing whitespace.
+ 
CODEX-OUT.round1.md:26986: trailing whitespace.
+ 
CODEX-OUT.round1.md:27005: trailing whitespace.
+ 
CODEX-OUT.round1.md:27008: trailing whitespace.
+ 
CODEX-OUT.round1.md:27091: trailing whitespace.
+ 
CODEX-OUT.round1.md:27161: trailing whitespace.
+ 
CODEX-OUT.round1.md:27263: trailing whitespace.
+ 
CODEX-OUT.round1.md:27289: trailing whitespace.
+ 
CODEX-OUT.round1.md:27334: trailing whitespace.
+ 
CODEX-OUT.round1.md:27470: trailing whitespace.
+ 
CODEX-OUT.round1.md:27662: trailing whitespace.
+ 
CODEX-OUT.round1.md:27681: trailing whitespace.
+ 
CODEX-OUT.round1.md:27684: trailing whitespace.
+ 
CODEX-OUT.round1.md:27767: trailing whitespace.
+ 
CODEX-OUT.round1.md:27837: trailing whitespace.
+ 
CODEX-OUT.round1.md:27939: trailing whitespace.
+ 
CODEX-OUT.round1.md:27965: trailing whitespace.
+ 
CODEX-OUT.round1.md:28010: trailing whitespace.
+ 
CODEX-OUT.round1.md:28146: trailing whitespace.
+ 
CODEX-OUT.round1.md:28312: trailing whitespace.
+ 
CODEX-OUT.round1.md:28331: trailing whitespace.
+ 
CODEX-OUT.round1.md:28334: trailing whitespace.
+ 
CODEX-OUT.round1.md:28417: trailing whitespace.
+ 
CODEX-OUT.round1.md:28487: trailing whitespace.
+ 
CODEX-OUT.round1.md:28589: trailing whitespace.
+ 
CODEX-OUT.round1.md:28615: trailing whitespace.
+ 
CODEX-OUT.round1.md:28660: trailing whitespace.
+ 
CODEX-OUT.round1.md:28796: trailing whitespace.
+ 
CODEX-OUT.round1.md:28926: trailing whitespace.
+ 
CODEX-OUT.round1.md:28945: trailing whitespace.
+ 
CODEX-OUT.round1.md:28948: trailing whitespace.
+ 
CODEX-OUT.round1.md:29031: trailing whitespace.
+ 
CODEX-OUT.round1.md:29101: trailing whitespace.
+ 
CODEX-OUT.round1.md:29203: trailing whitespace.
+ 
CODEX-OUT.round1.md:29229: trailing whitespace.
+ 
CODEX-OUT.round1.md:29274: trailing whitespace.
+ 
CODEX-OUT.round1.md:29411: trailing whitespace.
+ 
CODEX-OUT.round1.md:29540: trailing whitespace.
+ 
CODEX-OUT.round1.md:29559: trailing whitespace.
+ 
CODEX-OUT.round1.md:29562: trailing whitespace.
+ 
CODEX-OUT.round1.md:29645: trailing whitespace.
+ 
CODEX-OUT.round1.md:29715: trailing whitespace.
+ 
CODEX-OUT.round1.md:29817: trailing whitespace.
+ 
CODEX-OUT.round1.md:29843: trailing whitespace.
+ 
CODEX-OUT.round1.md:29888: trailing whitespace.
+ 
CODEX-OUT.round1.md:30025: trailing whitespace.
+ 
CODEX-OUT.round1.md:30167: trailing whitespace.
+ 
CODEX-OUT.round1.md:30186: trailing whitespace.
+ 
CODEX-OUT.round1.md:30189: trailing whitespace.
+ 
CODEX-OUT.round1.md:30272: trailing whitespace.
+ 
CODEX-OUT.round1.md:30342: trailing whitespace.
+ 
CODEX-OUT.round1.md:30444: trailing whitespace.
+ 
CODEX-OUT.round1.md:30470: trailing whitespace.
+ 
CODEX-OUT.round1.md:30515: trailing whitespace.
+ 
CODEX-OUT.round1.md:30652: trailing whitespace.
+ 
CODEX-OUT.round1.md:30797: trailing whitespace.
+ 
CODEX-OUT.round1.md:30816: trailing whitespace.
+ 
CODEX-OUT.round1.md:30819: trailing whitespace.
+ 
CODEX-OUT.round1.md:30902: trailing whitespace.
+ 
CODEX-OUT.round1.md:30972: trailing whitespace.
+ 
CODEX-OUT.round1.md:31074: trailing whitespace.
+ 
CODEX-OUT.round1.md:31100: trailing whitespace.
+ 
CODEX-OUT.round1.md:31145: trailing whitespace.
+ 
CODEX-OUT.round1.md:31282: trailing whitespace.
+ 
CODEX-OUT.round1.md:31428: trailing whitespace.
+ 
CODEX-OUT.round1.md:31447: trailing whitespace.
+ 
CODEX-OUT.round1.md:31450: trailing whitespace.
+ 
CODEX-OUT.round1.md:31533: trailing whitespace.
+ 
CODEX-OUT.round1.md:31603: trailing whitespace.
+ 
CODEX-OUT.round1.md:31705: trailing whitespace.
+ 
CODEX-OUT.round1.md:31731: trailing whitespace.
+ 
CODEX-OUT.round1.md:31776: trailing whitespace.
+ 
CODEX-OUT.round1.md:31913: trailing whitespace.
+ 
CODEX-OUT.round1.md:32057: trailing whitespace.
+ 
CODEX-OUT.round1.md:32076: trailing whitespace.
+ 
CODEX-OUT.round1.md:32079: trailing whitespace.
+ 
CODEX-OUT.round1.md:32162: trailing whitespace.
+ 
CODEX-OUT.round1.md:32232: trailing whitespace.
+ 
CODEX-OUT.round1.md:32334: trailing whitespace.
+ 
CODEX-OUT.round1.md:32360: trailing whitespace.
+ 
CODEX-OUT.round1.md:32405: trailing whitespace.
+ 
CODEX-OUT.round1.md:32542: trailing whitespace.
+ 
CODEX-OUT.round1.md:32691: trailing whitespace.
+ 
CODEX-OUT.round1.md:32710: trailing whitespace.
+ 
CODEX-OUT.round1.md:32713: trailing whitespace.
+ 
CODEX-OUT.round1.md:32796: trailing whitespace.
+ 
CODEX-OUT.round1.md:32866: trailing whitespace.
+ 
CODEX-OUT.round1.md:32968: trailing whitespace.
+ 
CODEX-OUT.round1.md:32994: trailing whitespace.
+ 
CODEX-OUT.round1.md:33039: trailing whitespace.
+ 
CODEX-OUT.round1.md:33176: trailing whitespace.
+ 
CODEX-OUT.round1.md:33327: trailing whitespace.
+ 
CODEX-OUT.round1.md:33346: trailing whitespace.
+ 
CODEX-OUT.round1.md:33349: trailing whitespace.
+ 
CODEX-OUT.round1.md:33432: trailing whitespace.
+ 
CODEX-OUT.round1.md:33522: trailing whitespace.
+ 
CODEX-OUT.round1.md:33624: trailing whitespace.
+ 
CODEX-OUT.round1.md:33650: trailing whitespace.
+ 
CODEX-OUT.round1.md:33695: trailing whitespace.
+ 
CODEX-OUT.round1.md:33832: trailing whitespace.
+ 
CODEX-OUT.round1.md:33970: trailing whitespace.
+ 
CODEX-OUT.round1.md:33989: trailing whitespace.
+ 
CODEX-OUT.round1.md:33992: trailing whitespace.
+ 
CODEX-OUT.round1.md:34075: trailing whitespace.
+ 
CODEX-OUT.round1.md:34165: trailing whitespace.
+ 
CODEX-OUT.round1.md:34267: trailing whitespace.
+ 
CODEX-OUT.round1.md:34293: trailing whitespace.
+ 
CODEX-OUT.round1.md:34338: trailing whitespace.
+ 
CODEX-OUT.round1.md:34475: trailing whitespace.
+ 
CODEX-OUT.round1.md:34687: trailing whitespace.
+ 
CODEX-OUT.round1.md:34706: trailing whitespace.
+ 
CODEX-OUT.round1.md:34709: trailing whitespace.
+ 
CODEX-OUT.round1.md:34792: trailing whitespace.
+ 
CODEX-OUT.round1.md:34882: trailing whitespace.
+ 
CODEX-OUT.round1.md:34984: trailing whitespace.
+ 
CODEX-OUT.round1.md:35010: trailing whitespace.
+ 
CODEX-OUT.round1.md:35055: trailing whitespace.
+ 
CODEX-OUT.round1.md:35192: trailing whitespace.
+ 
CODEX-OUT.round1.md:35406: trailing whitespace.
+ 
CODEX-OUT.round1.md:35425: trailing whitespace.
+ 
CODEX-OUT.round1.md:35428: trailing whitespace.
+ 
CODEX-OUT.round1.md:35511: trailing whitespace.
+ 
CODEX-OUT.round1.md:35601: trailing whitespace.
+ 
CODEX-OUT.round1.md:35703: trailing whitespace.
+ 
CODEX-OUT.round1.md:35729: trailing whitespace.
+ 
CODEX-OUT.round1.md:35774: trailing whitespace.
+ 
CODEX-OUT.round1.md:35911: trailing whitespace.
+ 
CODEX-OUT.round1.md:36141: trailing whitespace.
+ 
CODEX-OUT.round1.md:36160: trailing whitespace.
+ 
CODEX-OUT.round1.md:36163: trailing whitespace.
+ 
CODEX-OUT.round1.md:36246: trailing whitespace.
+ 
CODEX-OUT.round1.md:36336: trailing whitespace.
+ 
CODEX-OUT.round1.md:36438: trailing whitespace.
+ 
CODEX-OUT.round1.md:36464: trailing whitespace.
+ 
CODEX-OUT.round1.md:36509: trailing whitespace.
+ 
CODEX-OUT.round1.md:36646: trailing whitespace.
+ 
CODEX-OUT.round1.md:36885: trailing whitespace.
+ 
CODEX-OUT.round1.md:36904: trailing whitespace.
+ 
CODEX-OUT.round1.md:36907: trailing whitespace.
+ 
CODEX-OUT.round1.md:36990: trailing whitespace.
+ 
CODEX-OUT.round1.md:37080: trailing whitespace.
+ 
CODEX-OUT.round1.md:37182: trailing whitespace.
+ 
CODEX-OUT.round1.md:37208: trailing whitespace.
+ 
CODEX-OUT.round1.md:37253: trailing whitespace.
+ 
CODEX-OUT.round1.md:37390: trailing whitespace.
+ 
CODEX-OUT.round1.md:37601: trailing whitespace.
+ 
CODEX-OUT.round1.md:37620: trailing whitespace.
+ 
CODEX-OUT.round1.md:37623: trailing whitespace.
+ 
CODEX-OUT.round1.md:37706: trailing whitespace.
+ 
CODEX-OUT.round1.md:37796: trailing whitespace.
+ 
CODEX-OUT.round1.md:37898: trailing whitespace.
+ 
CODEX-OUT.round1.md:37924: trailing whitespace.
+ 
CODEX-OUT.round1.md:37969: trailing whitespace.
+ 
CODEX-OUT.round1.md:38106: trailing whitespace.
+ 
CODEX-OUT.round1.md:38143: trailing whitespace.
+ 
CODEX-OUT.round1.md:38147: trailing whitespace.
+ 
CODEX-OUT.round1.md:38156: trailing whitespace.
+ 
CODEX-OUT.round1.md:38162: trailing whitespace.
+ 
CODEX-OUT.round1.md:38377: trailing whitespace.
+ 
CODEX-OUT.round1.md:38396: trailing whitespace.
+ 
CODEX-OUT.round1.md:38399: trailing whitespace.
+ 
CODEX-OUT.round1.md:38482: trailing whitespace.
+ 
CODEX-OUT.round1.md:38572: trailing whitespace.
+ 
CODEX-OUT.round1.md:38674: trailing whitespace.
+ 
CODEX-OUT.round1.md:38700: trailing whitespace.
+ 
CODEX-OUT.round1.md:38745: trailing whitespace.
+ 
CODEX-OUT.round1.md:38882: trailing whitespace.
+ 
CODEX-OUT.round1.md:38919: trailing whitespace.
+ 
CODEX-OUT.round1.md:38923: trailing whitespace.
+ 
CODEX-OUT.round1.md:38932: trailing whitespace.
+ 
CODEX-OUT.round1.md:38938: trailing whitespace.
+ 
CODEX-OUT.round1.md:39146: trailing whitespace.
+ 
CODEX-OUT.round1.md:39165: trailing whitespace.
+ 
CODEX-OUT.round1.md:39168: trailing whitespace.
+ 
CODEX-OUT.round1.md:39251: trailing whitespace.
+ 
CODEX-OUT.round1.md:39341: trailing whitespace.
+ 
CODEX-OUT.round1.md:39444: trailing whitespace.
+ 
CODEX-OUT.round1.md:39448: trailing whitespace.
+ 
CODEX-OUT.round1.md:39486: trailing whitespace.
+ 
CODEX-OUT.round1.md:39512: trailing whitespace.
+ 
CODEX-OUT.round1.md:39557: trailing whitespace.
+ 
CODEX-OUT.round1.md:39694: trailing whitespace.
+ 
CODEX-OUT.round1.md:39731: trailing whitespace.
+ 
CODEX-OUT.round1.md:39735: trailing whitespace.
+ 
CODEX-OUT.round1.md:39753: trailing whitespace.
+ 
CODEX-OUT.round1.md:39759: trailing whitespace.
+ 
CODEX-OUT.round1.md:39773: trailing whitespace.
+ 
CODEX-OUT.round1.md:39781: trailing whitespace.
+ 
CODEX-OUT.round1.md:39967: trailing whitespace.
+ 
CODEX-OUT.round1.md:39986: trailing whitespace.
+ 
CODEX-OUT.round1.md:39989: trailing whitespace.
+ 
CODEX-OUT.round1.md:40072: trailing whitespace.
+ 
CODEX-OUT.round1.md:40162: trailing whitespace.
+ 
CODEX-OUT.round1.md:40265: trailing whitespace.
+ 
CODEX-OUT.round1.md:40269: trailing whitespace.
+ 
CODEX-OUT.round1.md:40307: trailing whitespace.
+ 
CODEX-OUT.round1.md:40333: trailing whitespace.
+ 
CODEX-OUT.round1.md:40378: trailing whitespace.
+ 
CODEX-OUT.round1.md:40515: trailing whitespace.
+ 
CODEX-OUT.round1.md:40552: trailing whitespace.
+ 
CODEX-OUT.round1.md:40556: trailing whitespace.
+ 
CODEX-OUT.round1.md:40574: trailing whitespace.
+ 
CODEX-OUT.round1.md:40580: trailing whitespace.
+ 
CODEX-OUT.round1.md:40594: trailing whitespace.
+ 
CODEX-OUT.round1.md:40602: trailing whitespace.
+ 
CODEX-OUT.round1.md:40804: trailing whitespace.
+ 
CODEX-OUT.round1.md:40823: trailing whitespace.
+ 
CODEX-OUT.round1.md:40826: trailing whitespace.
+ 
CODEX-OUT.round1.md:40909: trailing whitespace.
+ 
CODEX-OUT.round1.md:40999: trailing whitespace.
+ 
CODEX-OUT.round1.md:41102: trailing whitespace.
+ 
CODEX-OUT.round1.md:41106: trailing whitespace.
+ 
CODEX-OUT.round1.md:41144: trailing whitespace.
+ 
CODEX-OUT.round1.md:41170: trailing whitespace.
+ 
CODEX-OUT.round1.md:41215: trailing whitespace.
+ 
CODEX-OUT.round1.md:41352: trailing whitespace.
+ 
CODEX-OUT.round1.md:41389: trailing whitespace.
+ 
CODEX-OUT.round1.md:41393: trailing whitespace.
+ 
CODEX-OUT.round1.md:41411: trailing whitespace.
+ 
CODEX-OUT.round1.md:41417: trailing whitespace.
+ 
CODEX-OUT.round1.md:41431: trailing whitespace.
+ 
CODEX-OUT.round1.md:41439: trailing whitespace.
+ 
CODEX-OUT.round1.md:41739: trailing whitespace.
+ 
CODEX-OUT.round1.md:41758: trailing whitespace.
+ 
CODEX-OUT.round1.md:41761: trailing whitespace.
+ 
CODEX-OUT.round1.md:41844: trailing whitespace.
+ 
CODEX-OUT.round1.md:41934: trailing whitespace.
+ 
CODEX-OUT.round1.md:42037: trailing whitespace.
+ 
CODEX-OUT.round1.md:42041: trailing whitespace.
+ 
CODEX-OUT.round1.md:42079: trailing whitespace.
+ 
CODEX-OUT.round1.md:42105: trailing whitespace.
+ 
CODEX-OUT.round1.md:42150: trailing whitespace.
+ 
CODEX-OUT.round1.md:42287: trailing whitespace.
+ 
CODEX-OUT.round1.md:42324: trailing whitespace.
+ 
CODEX-OUT.round1.md:42328: trailing whitespace.
+ 
CODEX-OUT.round1.md:42346: trailing whitespace.
+ 
CODEX-OUT.round1.md:42352: trailing whitespace.
+ 
CODEX-OUT.round1.md:42366: trailing whitespace.
+ 
CODEX-OUT.round1.md:42374: trailing whitespace.
+ 
CODEX-OUT.round1.md:42831: trailing whitespace.
+ 
CODEX-OUT.round1.md:42850: trailing whitespace.
+ 
CODEX-OUT.round1.md:42853: trailing whitespace.
+ 
CODEX-OUT.round1.md:42936: trailing whitespace.
+ 
CODEX-OUT.round1.md:43026: trailing whitespace.
+ 
CODEX-OUT.round1.md:43129: trailing whitespace.
+ 
CODEX-OUT.round1.md:43133: trailing whitespace.
+ 
CODEX-OUT.round1.md:43171: trailing whitespace.
+ 
CODEX-OUT.round1.md:43197: trailing whitespace.
+ 
CODEX-OUT.round1.md:43242: trailing whitespace.
+ 
CODEX-OUT.round1.md:43379: trailing whitespace.
+ 
CODEX-OUT.round1.md:43416: trailing whitespace.
+ 
CODEX-OUT.round1.md:43420: trailing whitespace.
+ 
CODEX-OUT.round1.md:43438: trailing whitespace.
+ 
CODEX-OUT.round1.md:43444: trailing whitespace.
+ 
CODEX-OUT.round1.md:43458: trailing whitespace.
+ 
CODEX-OUT.round1.md:43466: trailing whitespace.
+ 
CODEX-OUT.round1.md:43675: trailing whitespace.
+ 
CODEX-OUT.round1.md:43694: trailing whitespace.
+ 
CODEX-OUT.round1.md:43697: trailing whitespace.
+ 
CODEX-OUT.round1.md:43780: trailing whitespace.
+ 
CODEX-OUT.round1.md:43870: trailing whitespace.
+ 
CODEX-OUT.round1.md:43973: trailing whitespace.
+ 
CODEX-OUT.round1.md:43977: trailing whitespace.
+ 
CODEX-OUT.round1.md:44015: trailing whitespace.
+ 
CODEX-OUT.round1.md:44041: trailing whitespace.
+ 
CODEX-OUT.round1.md:44086: trailing whitespace.
+ 
CODEX-OUT.round1.md:44223: trailing whitespace.
+ 
CODEX-OUT.round1.md:44260: trailing whitespace.
+ 
CODEX-OUT.round1.md:44264: trailing whitespace.
+ 
CODEX-OUT.round1.md:44282: trailing whitespace.
+ 
CODEX-OUT.round1.md:44288: trailing whitespace.
+ 
CODEX-OUT.round1.md:44302: trailing whitespace.
+ 
CODEX-OUT.round1.md:44310: trailing whitespace.
+ 
CODEX-OUT.round1.md:44516: trailing whitespace.
+ 
CODEX-OUT.round1.md:44535: trailing whitespace.
+ 
CODEX-OUT.round1.md:44538: trailing whitespace.
+ 
CODEX-OUT.round1.md:44621: trailing whitespace.
+ 
CODEX-OUT.round1.md:44711: trailing whitespace.
+ 
CODEX-OUT.round1.md:44814: trailing whitespace.
+ 
CODEX-OUT.round1.md:44818: trailing whitespace.
+ 
CODEX-OUT.round1.md:44856: trailing whitespace.
+ 
CODEX-OUT.round1.md:44882: trailing whitespace.
+ 
CODEX-OUT.round1.md:44927: trailing whitespace.
+ 
CODEX-OUT.round1.md:45064: trailing whitespace.
+ 
CODEX-OUT.round1.md:45101: trailing whitespace.
+ 
CODEX-OUT.round1.md:45105: trailing whitespace.
+ 
CODEX-OUT.round1.md:45123: trailing whitespace.
+ 
CODEX-OUT.round1.md:45129: trailing whitespace.
+ 
CODEX-OUT.round1.md:45143: trailing whitespace.
+ 
CODEX-OUT.round1.md:45151: trailing whitespace.
+ 
CODEX-OUT.round1.md:45428: trailing whitespace.
+ 
CODEX-OUT.round1.md:45447: trailing whitespace.
+ 
CODEX-OUT.round1.md:45450: trailing whitespace.
+ 
CODEX-OUT.round1.md:45533: trailing whitespace.
+ 
CODEX-OUT.round1.md:45623: trailing whitespace.
+ 
CODEX-OUT.round1.md:45726: trailing whitespace.
+ 
CODEX-OUT.round1.md:45730: trailing whitespace.
+ 
CODEX-OUT.round1.md:45768: trailing whitespace.
+ 
CODEX-OUT.round1.md:45794: trailing whitespace.
+ 
CODEX-OUT.round1.md:45839: trailing whitespace.
+ 
CODEX-OUT.round1.md:45976: trailing whitespace.
+ 
CODEX-OUT.round1.md:46013: trailing whitespace.
+ 
CODEX-OUT.round1.md:46017: trailing whitespace.
+ 
CODEX-OUT.round1.md:46035: trailing whitespace.
+ 
CODEX-OUT.round1.md:46041: trailing whitespace.
+ 
CODEX-OUT.round1.md:46055: trailing whitespace.
+ 
CODEX-OUT.round1.md:46063: trailing whitespace.
+ 
CODEX-OUT.round1.md:46335: trailing whitespace.
+ 
CODEX-OUT.round1.md:46354: trailing whitespace.
+ 
CODEX-OUT.round1.md:46357: trailing whitespace.
+ 
CODEX-OUT.round1.md:46440: trailing whitespace.
+ 
CODEX-OUT.round1.md:46530: trailing whitespace.
+ 
CODEX-OUT.round1.md:46633: trailing whitespace.
+ 
CODEX-OUT.round1.md:46637: trailing whitespace.
+ 
CODEX-OUT.round1.md:46675: trailing whitespace.
+ 
CODEX-OUT.round1.md:46701: trailing whitespace.
+ 
CODEX-OUT.round1.md:46746: trailing whitespace.
+ 
CODEX-OUT.round1.md:46883: trailing whitespace.
+ 
CODEX-OUT.round1.md:46920: trailing whitespace.
+ 
CODEX-OUT.round1.md:46924: trailing whitespace.
+ 
CODEX-OUT.round1.md:46942: trailing whitespace.
+ 
CODEX-OUT.round1.md:46948: trailing whitespace.
+ 
CODEX-OUT.round1.md:46962: trailing whitespace.
+ 
CODEX-OUT.round1.md:46970: trailing whitespace.
+ 
CODEX-OUT.round1.md:47158: trailing whitespace.
+ 
CODEX-OUT.round1.md:47177: trailing whitespace.
+ 
CODEX-OUT.round1.md:47180: trailing whitespace.
+ 
CODEX-OUT.round1.md:47263: trailing whitespace.
+ 
CODEX-OUT.round1.md:47353: trailing whitespace.
+ 
CODEX-OUT.round1.md:47453: trailing whitespace.
+ 
CODEX-OUT.round1.md:47454: trailing whitespace.
+ 
CODEX-OUT.round1.md:47462: trailing whitespace.
+ 
CODEX-OUT.round1.md:47486: trailing whitespace.
+ 
CODEX-OUT.round1.md:47506: trailing whitespace.
+ 
CODEX-OUT.round1.md:47510: trailing whitespace.
+ 
CODEX-OUT.round1.md:47548: trailing whitespace.
+ 
CODEX-OUT.round1.md:47574: trailing whitespace.
+ 
CODEX-OUT.round1.md:47619: trailing whitespace.
+ 
CODEX-OUT.round1.md:47879: trailing whitespace.
+ 
CODEX-OUT.round1.md:47918: trailing whitespace.
+ 
CODEX-OUT.round1.md:47922: trailing whitespace.
+ 
CODEX-OUT.round1.md:47940: trailing whitespace.
+ 
CODEX-OUT.round1.md:47946: trailing whitespace.
+ 
CODEX-OUT.round1.md:47960: trailing whitespace.
+ 
CODEX-OUT.round1.md:47968: trailing whitespace.
+ 
CODEX-OUT.round1.md:48154: trailing whitespace.
+ 
CODEX-OUT.round1.md:48173: trailing whitespace.
+ 
CODEX-OUT.round1.md:48176: trailing whitespace.
+ 
CODEX-OUT.round1.md:48259: trailing whitespace.
+ 
CODEX-OUT.round1.md:48349: trailing whitespace.
+ 
CODEX-OUT.round1.md:48449: trailing whitespace.
+ 
CODEX-OUT.round1.md:48450: trailing whitespace.
+ 
CODEX-OUT.round1.md:48458: trailing whitespace.
+ 
CODEX-OUT.round1.md:48482: trailing whitespace.
+ 
CODEX-OUT.round1.md:48502: trailing whitespace.
+ 
CODEX-OUT.round1.md:48506: trailing whitespace.
+ 
CODEX-OUT.round1.md:48544: trailing whitespace.
+ 
CODEX-OUT.round1.md:48570: trailing whitespace.
+ 
CODEX-OUT.round1.md:48615: trailing whitespace.
+ 
CODEX-OUT.round1.md:48875: trailing whitespace.
+ 
CODEX-OUT.round1.md:48914: trailing whitespace.
+ 
CODEX-OUT.round1.md:48918: trailing whitespace.
+ 
CODEX-OUT.round1.md:48936: trailing whitespace.
+ 
CODEX-OUT.round1.md:48942: trailing whitespace.
+ 
CODEX-OUT.round1.md:48956: trailing whitespace.
+ 
CODEX-OUT.round1.md:48964: trailing whitespace.
+ 
CODEX-OUT.round1.md:49259: trailing whitespace.
+ 
CODEX-OUT.round1.md:49278: trailing whitespace.
+ 
CODEX-OUT.round1.md:49281: trailing whitespace.
+ 
CODEX-OUT.round1.md:49364: trailing whitespace.
+ 
CODEX-OUT.round1.md:49454: trailing whitespace.
+ 
CODEX-OUT.round1.md:49554: trailing whitespace.
+ 
CODEX-OUT.round1.md:49555: trailing whitespace.
+ 
CODEX-OUT.round1.md:49563: trailing whitespace.
+ 
CODEX-OUT.round1.md:49587: trailing whitespace.
+ 
CODEX-OUT.round1.md:49607: trailing whitespace.
+ 
CODEX-OUT.round1.md:49611: trailing whitespace.
+ 
CODEX-OUT.round1.md:49649: trailing whitespace.
+ 
CODEX-OUT.round1.md:49675: trailing whitespace.
+ 
CODEX-OUT.round1.md:49720: trailing whitespace.
+ 
CODEX-OUT.round1.md:49980: trailing whitespace.
+ 
CODEX-OUT.round1.md:50019: trailing whitespace.
+ 
CODEX-OUT.round1.md:50023: trailing whitespace.
+ 
CODEX-OUT.round1.md:50041: trailing whitespace.
+ 
CODEX-OUT.round1.md:50047: trailing whitespace.
+ 
CODEX-OUT.round1.md:50061: trailing whitespace.
+ 
CODEX-OUT.round1.md:50069: trailing whitespace.
+ 
CODEX-OUT.round1.md:50278: trailing whitespace.
+ 
CODEX-OUT.round1.md:50297: trailing whitespace.
+ 
CODEX-OUT.round1.md:50300: trailing whitespace.
+ 
CODEX-OUT.round1.md:50383: trailing whitespace.
+ 
CODEX-OUT.round1.md:50473: trailing whitespace.
+ 
CODEX-OUT.round1.md:50573: trailing whitespace.
+ 
CODEX-OUT.round1.md:50574: trailing whitespace.
+ 
CODEX-OUT.round1.md:50582: trailing whitespace.
+ 
CODEX-OUT.round1.md:50606: trailing whitespace.
+ 
CODEX-OUT.round1.md:50626: trailing whitespace.
+ 
CODEX-OUT.round1.md:50630: trailing whitespace.
+ 
CODEX-OUT.round1.md:50668: trailing whitespace.
+ 
CODEX-OUT.round1.md:50694: trailing whitespace.
+ 
CODEX-OUT.round1.md:50739: trailing whitespace.
+ 
CODEX-OUT.round1.md:50999: trailing whitespace.
+ 
CODEX-OUT.round1.md:51038: trailing whitespace.
+ 
CODEX-OUT.round1.md:51042: trailing whitespace.
+ 
CODEX-OUT.round1.md:51060: trailing whitespace.
+ 
CODEX-OUT.round1.md:51066: trailing whitespace.
+ 
CODEX-OUT.round1.md:51080: trailing whitespace.
+ 
CODEX-OUT.round1.md:51088: trailing whitespace.
+ 
CODEX-OUT.round1.md:51336: trailing whitespace.
+ 
CODEX-OUT.round1.md:51355: trailing whitespace.
+ 
CODEX-OUT.round1.md:51358: trailing whitespace.
+ 
CODEX-OUT.round1.md:51441: trailing whitespace.
+ 
CODEX-OUT.round1.md:51531: trailing whitespace.
+ 
CODEX-OUT.round1.md:51631: trailing whitespace.
+ 
CODEX-OUT.round1.md:51632: trailing whitespace.
+ 
CODEX-OUT.round1.md:51640: trailing whitespace.
+ 
CODEX-OUT.round1.md:51664: trailing whitespace.
+ 
CODEX-OUT.round1.md:51684: trailing whitespace.
+ 
CODEX-OUT.round1.md:51688: trailing whitespace.
+ 
CODEX-OUT.round1.md:51726: trailing whitespace.
+ 
CODEX-OUT.round1.md:51752: trailing whitespace.
+ 
CODEX-OUT.round1.md:51797: trailing whitespace.
+ 
CODEX-OUT.round1.md:52057: trailing whitespace.
+ 
CODEX-OUT.round1.md:52096: trailing whitespace.
+ 
CODEX-OUT.round1.md:52100: trailing whitespace.
+ 
CODEX-OUT.round1.md:52118: trailing whitespace.
+ 
CODEX-OUT.round1.md:52124: trailing whitespace.
+ 
CODEX-OUT.round1.md:52138: trailing whitespace.
+ 
CODEX-OUT.round1.md:52146: trailing whitespace.
+ 
CODEX-OUT.round1.md:52372: trailing whitespace.
+ 
CODEX-OUT.round1.md:52391: trailing whitespace.
+ 
CODEX-OUT.round1.md:52394: trailing whitespace.
+ 
CODEX-OUT.round1.md:52477: trailing whitespace.
+ 
CODEX-OUT.round1.md:52567: trailing whitespace.
+ 
CODEX-OUT.round1.md:52667: trailing whitespace.
+ 
CODEX-OUT.round1.md:52668: trailing whitespace.
+ 
CODEX-OUT.round1.md:52676: trailing whitespace.
+ 
CODEX-OUT.round1.md:52700: trailing whitespace.
+ 
CODEX-OUT.round1.md:52720: trailing whitespace.
+ 
CODEX-OUT.round1.md:52724: trailing whitespace.
+ 
CODEX-OUT.round1.md:52762: trailing whitespace.
+ 
CODEX-OUT.round1.md:52788: trailing whitespace.
+ 
CODEX-OUT.round1.md:52833: trailing whitespace.
+ 
CODEX-OUT.round1.md:53093: trailing whitespace.
+ 
CODEX-OUT.round1.md:53132: trailing whitespace.
+ 
CODEX-OUT.round1.md:53136: trailing whitespace.
+ 
CODEX-OUT.round1.md:53154: trailing whitespace.
+ 
CODEX-OUT.round1.md:53160: trailing whitespace.
+ 
CODEX-OUT.round1.md:53174: trailing whitespace.
+ 
CODEX-OUT.round1.md:53182: trailing whitespace.
+ 
CODEX-OUT.round1.md:53382: trailing whitespace.
+ 
CODEX-OUT.round1.md:53401: trailing whitespace.
+ 
CODEX-OUT.round1.md:53404: trailing whitespace.
+ 
CODEX-OUT.round1.md:53487: trailing whitespace.
+ 
CODEX-OUT.round1.md:53577: trailing whitespace.
+ 
CODEX-OUT.round1.md:53677: trailing whitespace.
+ 
CODEX-OUT.round1.md:53678: trailing whitespace.
+ 
CODEX-OUT.round1.md:53686: trailing whitespace.
+ 
CODEX-OUT.round1.md:53710: trailing whitespace.
+ 
CODEX-OUT.round1.md:53730: trailing whitespace.
+ 
CODEX-OUT.round1.md:53734: trailing whitespace.
+ 
CODEX-OUT.round1.md:53772: trailing whitespace.
+ 
CODEX-OUT.round1.md:53798: trailing whitespace.
+ 
CODEX-OUT.round1.md:53843: trailing whitespace.
+ 
CODEX-OUT.round1.md:54103: trailing whitespace.
+ 
CODEX-OUT.round1.md:54142: trailing whitespace.
+ 
CODEX-OUT.round1.md:54146: trailing whitespace.
+ 
CODEX-OUT.round1.md:54164: trailing whitespace.
+ 
CODEX-OUT.round1.md:54170: trailing whitespace.
+ 
CODEX-OUT.round1.md:54184: trailing whitespace.
+ 
CODEX-OUT.round1.md:54192: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:3821: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:3830: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:3902: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:3911: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4126: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4135: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4205: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4214: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4291: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4300: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4378: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4387: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4482: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4491: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4560: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4566: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4592: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4601: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4670: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4676: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4711: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4720: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4789: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4795: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4823: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4832: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4901: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4907: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4931: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:4940: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5009: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5015: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5046: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5055: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5124: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5130: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5158: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5167: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5236: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5242: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5285: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5294: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5363: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5369: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5405: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5414: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5483: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5489: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5534: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5543: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5612: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5618: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5649: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5658: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5727: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5733: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5765: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5774: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5843: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5849: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5881: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5890: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5959: trailing whitespace.
+ 
CODEX-OUT.round2-N9-wrong.md:5965: trailing whitespace.
+ 

diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index e6fe5a7167a073d2164527ab89510e090970c9a0..30f6fa514632ac41a2ee60e2e07ec936c0dfcd09
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
-                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
+                cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8..7c52a3d60efeb4c859baa2e95bbe2566d7e76c9c
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

exec
/bin/bash -lc 'test "$(git rev-parse HEAD)" = cae99a51a71f943badfc7c609c6946b4735e2859 && git rm --cached -- CODEX-OUT.round1.md CODEX-OUT.round2-N9-wrong.md && git add -A '"':"'!CODEX-OUT.md'"' ':"'!CODEX-OUT.round1.md'"' ':"'!CODEX-OUT.round2-N9-wrong.md'"' && git diff --cached 4f6449e12 --check && git diff --cached 4f6449e12 --stat" in /home/user/Projects/cx-deadconf-fix
 exited 1 in 0ms:
rm 'CODEX-OUT.round1.md'
rm 'CODEX-OUT.round2-N9-wrong.md'
The following paths are ignored by one of your .gitignore files:
CODEX-OUT.md
hint: Use -f if you really want to add them.
hint: Turn this message off by running
hint: "git config advice.addIgnoredFile false"

diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index e6fe5a7167a073d2164527ab89510e090970c9a0..30f6fa514632ac41a2ee60e2e07ec936c0dfcd09
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
-                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
+                cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8..7c52a3d60efeb4c859baa2e95bbe2566d7e76c9c
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

exec
/bin/bash -lc 'git add -- src/core/io_loop.h tests/netcmd_unit.cc tomokv.conf && git diff --cached 4f6449e12 --check && git diff --cached 4f6449e12 --stat && git diff --cached --exit-code 4f6449e12''^ -- src/core/io_loop.h && git log -2 --oneline' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
 src/core/io_loop.h   |  4 ++--
 tests/netcmd_unit.cc | 16 ++++++++++++++--
 tomokv.conf          |  4 ++--
 3 files changed, 18 insertions(+), 6 deletions(-)
cae99a51a autosave: cx-deadconf-fix 12:28 (2 files)
4f6449e12 limit subscriber idle-timeout exemption to RESP2

diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index e6fe5a7167a073d2164527ab89510e090970c9a0..30f6fa514632ac41a2ee60e2e07ec936c0dfcd09
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
-                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
+                cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8..7c52a3d60efeb4c859baa2e95bbe2566d7e76c9c
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

exec
/bin/bash -lc 'test "$(git rev-parse HEAD)" = cae99a51a71f943badfc7c609c6946b4735e2859 && git -c user.name=Codex -c user.email=codex@openai.com commit --amend --reset-author -m '"'restore Redis idle-timeout exemption for all subscribers' && git log -2 --oneline && git show --stat --oneline HEAD && git status --short && git rev-list --count 4f6449e12..HEAD" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
[cx-deadconf-fix-items 3fed576c8] restore Redis idle-timeout exemption for all subscribers
 3 files changed, 18 insertions(+), 6 deletions(-)
3fed576c8 restore Redis idle-timeout exemption for all subscribers
4f6449e12 limit subscriber idle-timeout exemption to RESP2
3fed576c8 restore Redis idle-timeout exemption for all subscribers
 src/core/io_loop.h   |  4 ++--
 tests/netcmd_unit.cc | 16 ++++++++++++++--
 tomokv.conf          |  4 ++--
 3 files changed, 18 insertions(+), 6 deletions(-)
?? CODEX-OUT.round1.md
?? CODEX-OUT.round2-N9-wrong.md
1

diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index e6fe5a7167a073d2164527ab89510e090970c9a0..30f6fa514632ac41a2ee60e2e07ec936c0dfcd09
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
-                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
+                cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8..7c52a3d60efeb4c859baa2e95bbe2566d7e76c9c
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

codex
Restored the idle-timeout exemption for all subscribers in one commit atop unchanged `4f6449e12`.

| Item | Files | Test that fails on old code | Commit |
|---|---|---|---|
| N9 Redis parity | [io_loop.h](/home/user/Projects/cx-deadconf-fix/src/core/io_loop.h:6063), [tomokv.conf](/home/user/Projects/cx-deadconf-fix/tomokv.conf:52), [netcmd_unit.cc](/home/user/Projects/cx-deadconf-fix/tests/netcmd_unit.cc:196) | `pubsub-timeout`: confirmed failure against `4f6449e12`; corrected code exempts both protocols while closing plain idle RESP3 clients | `3fed576c8` |

Build and `pubsub-timeout`, `pubsub`, and `output` units passed on cores 112–127. No server, benchmark, or gate run.
diff --git a/src/core/io_loop.h b/src/core/io_loop.h
index e6fe5a7167a073d2164527ab89510e090970c9a0..30f6fa514632ac41a2ee60e2e07ec936c0dfcd09
--- a/src/core/io_loop.h
+++ b/src/core/io_loop.h
@@ -6060,8 +6060,8 @@
             Client* c = clients[client_cron_cursor_];
             const size_t before = clients.size();
             bool closed = false;
-            if (timeout && !c->blocked() && (!c->subscriber_mode() || c->resp3()) &&
-                !c->closing() && cached_now_s_ - c->last_interaction_s() > timeout) {
+            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
+                cached_now_s_ - c->last_interaction_s() > timeout) {
                 close_client(c);
                 closed = true;
             } else if (client_obuf_check(c, false)) {
diff --git a/tests/netcmd_unit.cc b/tests/netcmd_unit.cc
index dba9b59bfe828b3b56b69bd31d13101894773dac..c9c15c48d3c7f44aca353e5f8349849452989d90
--- a/tests/netcmd_unit.cc
+++ b/tests/netcmd_unit.cc
@@ -238,9 +238,21 @@
             check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
             client.set_blocked(false);
             check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
-            check(client.closing() == resp3,
-                  resp3 ? "idle RESP3 SUBSCRIBE client must be closed after timeout"
+            check(!client.closing(),
+                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                         : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");
+
+            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
+            idle.set_last_interaction_s(100);
+            // Model an outstanding receive to keep this stack-owned control alive after close.
+            // No receive is submitted; the control has no subscription or blocking command.
+            idle.set_recv_armed(true);
+            self.add_client(&idle);
+            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
+            check(!client.closing(), "subscriber stays open alongside the plain idle control");
+            check(idle.closing(),
+                  resp3 ? "plain idle RESP3 client must be closed after timeout"
+                        : "plain idle RESP2 client must be closed after timeout");
         }
     }
 
diff --git a/tomokv.conf b/tomokv.conf
index 8dc4b8c0cf882ebd740e323ed3b3745b2192c8a8..7c52a3d60efeb4c859baa2e95bbe2566d7e76c9c
--- a/tomokv.conf
+++ b/tomokv.conf
@@ -49,8 +49,8 @@
 # maxclients 10000
 
 # Close idle normal clients after strictly more than this many whole seconds [live]. 0 disables.
-# Blocked clients and RESP2 pub/sub clients are exempt. RESP3 pub/sub clients and idle MULTI
-# transactions remain subject to this timeout.
+# Blocked clients and pub/sub clients (RESP2 and RESP3, as in Redis) are exempt; an idle MULTI
+# transaction is not exempt.
 # timeout 0
 
 # TCP keepalive interval in seconds [live for newly accepted connections]. 0 makes no keepalive

tokens used
66,723
Restored the idle-timeout exemption for all subscribers in one commit atop unchanged `4f6449e12`.

| Item | Files | Test that fails on old code | Commit |
|---|---|---|---|
| N9 Redis parity | [io_loop.h](/home/user/Projects/cx-deadconf-fix/src/core/io_loop.h:6063), [tomokv.conf](/home/user/Projects/cx-deadconf-fix/tomokv.conf:52), [netcmd_unit.cc](/home/user/Projects/cx-deadconf-fix/tests/netcmd_unit.cc:196) | `pubsub-timeout`: confirmed failure against `4f6449e12`; corrected code exempts both protocols while closing plain idle RESP3 clients | `3fed576c8` |

Build and `pubsub-timeout`, `pubsub`, and `output` units passed on cores 112–127. No server, benchmark, or gate run.
