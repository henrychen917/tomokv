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
session id: 01a099f2-e1ab-72f3-aee9-07d0ecf8a833
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

GATE FAILURE (mainline 16:50): tests/gate.sh iteration on cb8140efa: 434/436 rows PASS; both "ACL battery" rows FAIL in your own
tests/acl.py:192 — the server (your 528cb0b15) answers ACL SETUSER bad-selector "(on +get)" with
  "ERR Error in ACL SETUSER modifier '(on +get)': ACL selectors are not supported"
while the test wanted %r" % (label, actual, wanted))
Make the server message and the test agree and match Redis 7.4's error grammar for an ACL SETUSER modifier error (check
/tmp/claude-1000/redis74/src/acl.c: ACLSetUserStringError / "Error in ACL SETUSER modifier"); keep the honest rejection of
selectors. Then RUN the battery yourself before committing: taskset -c 112-127 python3 tests/acl.py --help for its interface,
boot a server on port 10390 with --shards 16 --ratio 6:2 --enable-debug-command yes on cores 112-127, run acl.py against it in
both atomic modes, kill the server by PID. One commit. End with CX-deadconf-fix-DONE.
codex
I’ll check Redis 7.4’s modifier-error grammar, make the selector rejection and test agree, then run the ACL battery in both atomic modes on cores 112–127 before committing.
exec
/bin/bash -lc 'pwd && git status --short && git branch --show-current && git log -10 --oneline' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
/home/user/Projects/cx-deadconf-fix
 M gate-iteration-1621.log
?? CODEX-OUT.round3-N9.md
cx-deadconf-fix-items
1e1eb2f09 autosave: cx-deadconf-fix 16:39 (1 files)
b1a0b2b64 autosave: cx-deadconf-fix 16:29 (1 files)
cb8140efa Merge cx-final (rebaseline 3adaaae06) into cx-deadconf-fix for gating
3fed576c8 restore Redis idle-timeout exemption for all subscribers
4f6449e12 limit subscriber idle-timeout exemption to RESP2
528cb0b15 reject ACL selectors and correct ownership and list-limit comments
f1b61114a correct AOF, ROB and tracking configuration comments
9ab54c4e1 sample tracking eviction victims across buckets and collisions
36f7c17dc honor zero-copy off and inclusive GET/MGET cutovers
3adaaae06 gate: reference tracks the push

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
/bin/bash -lc "rg -n -C 8 'ACLSetUserStringError|Error in ACL SETUSER modifier' /tmp/claude-1000/redis74/src/acl.c" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
1368-            return C_ERR;
1369-        }
1370-    }
1371-    return C_OK;
1372-}
1373-
1374-/* Return a description of the error that occurred in ACLSetUser() according to
1375- * the errno value set by the function on error. */
1376:const char *ACLSetUserStringError(void) {
1377-    const char *errmsg = "Wrong format";
1378-    if (errno == ENOENT)
1379-        errmsg = "Unknown command or category name in ACL";
1380-    else if (errno == EINVAL)
1381-        errmsg = "Syntax error";
1382-    else if (errno == EEXIST)
1383-        errmsg = "Adding a pattern after the * pattern (or the "
1384-                 "'allkeys' flag) is not valid and does not have any "
--
2096-     * If there are any errors then none of the changes will be applied. */
2097-    user *tempu = ACLCreateUnlinkedUser();
2098-    if (u) {
2099-        ACLCopyUser(tempu, u);
2100-    }
2101-
2102-    for (int j = 0; j < merged_argc; j++) {
2103-        if (ACLSetUser(tempu,acl_args[j],(ssize_t) sdslen(acl_args[j])) != C_OK) {
2104:            const char *errmsg = ACLSetUserStringError();
2105-            error = sdscatfmt(sdsempty(),
2106:                              "Error in ACL SETUSER modifier '%s': %s",
2107-                              (char*)acl_args[j], errmsg);
2108-            goto cleanup;
2109-        }
2110-    }
2111-
2112-    /* Existing pub/sub clients authenticated with the user may need to be
2113-     * disconnected if (some of) their channel permissions were revoked. */
2114-    if (u) {
--
2221-            serverAssert(!strcmp(username, "default"));
2222-            u = ACLGetUserByName("default",7);
2223-            ACLSetUser(u,"reset",-1);
2224-        }
2225-
2226-        /* Load every rule defined for this user. */
2227-        for (int j = 1; aclrules[j]; j++) {
2228-            if (ACLSetUser(u,aclrules[j],sdslen(aclrules[j])) != C_OK) {
2229:                const char *errmsg = ACLSetUserStringError();
2230-                serverLog(LL_WARNING,"Error loading ACL rule '%s' for "
2231-                                     "the user named '%s': %s",
2232-                          aclrules[j],aclrules[0],errmsg);
2233-                return C_ERR;
2234-            }
2235-        }
2236-
2237-        /* Having a disabled user in the configuration may be an error,
--
2364-                    "%s:%d: Unmatched parenthesis in selector definition.",
2365-                    server.acl_filename, linenum);
2366-        }
2367-
2368-        int syntax_error = 0;
2369-        for (int j = 0; j < merged_argc; j++) {
2370-            acl_args[j] = sdstrim(acl_args[j],"\t\r\n");
2371-            if (ACLSetUser(u,acl_args[j],sdslen(acl_args[j])) != C_OK) {
2372:                const char *errmsg = ACLSetUserStringError();
2373-                if (errno == ENOENT) {
2374-                    /* For missing commands, we print out more information since
2375-                     * it shouldn't contain any sensitive information. */
2376-                    errors = sdscatprintf(errors,
2377-                            "%s:%d: Error in applying operation '%s': %s. ",
2378-                            server.acl_filename, linenum, acl_args[j], errmsg);
2379-                } else if (syntax_error == 0) {
2380-                    /* For all other errors, only print out the first error encountered

exec
/bin/bash -lc "rg --files -g AGENTS.md -g '*acl*' -g '*atomic*' -g 'CMakeLists.txt' -g 'Makefile' -g 'meson.build' -g 'MEASURE*' -g '"'!third_party/**'"' -g '"'!vendor/**'"' . /home/user/Projects 2>/dev/null" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
./tools/gen_acl_categories.py
./Makefile
./src/core/atomic_admission.h
./src/core/atomic_tripwire.h
/home/user/Projects/cx-reorder-R4/tools/gen_acl_categories.py
/home/user/Projects/cx-reorder-R4/Makefile
./src/cmd/acl.inc
./src/cmd/acl.cc
./src/cmd/acl_categories_generated.h
./src/cmd/atomics_glue.inc
./src/cmd/acl.h
./src/store/flatstore_atomic.inc
./src/store/atomic_mvcc.h
/home/user/Projects/cx-reorder-R4/src/core/atomic_admission.h
/home/user/Projects/cx-reorder-R4/src/core/atomic_tripwire.h
./MEASURE-REQUEST
/home/user/Projects/tomokv-cpp-perthread/tools/gen_acl_categories.py
/home/user/Projects/cx-reorder-R4/src/cmd/acl.inc
/home/user/Projects/cx-reorder-R4/src/cmd/acl.cc
/home/user/Projects/cx-reorder-R4/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-reorder-R4/src/cmd/atomics_glue.inc
/home/user/Projects/cx-reorder-R4/src/cmd/acl.h
/home/user/Projects/cx-overlap-O9/tools/gen_acl_categories.py
/home/user/Projects/cx-reorder-R4/src/store/flatstore_atomic.inc
/home/user/Projects/cx-reorder-R4/src/store/atomic_mvcc.h
/home/user/Projects/cx-cache-L2/tools/gen_acl_categories.py
/home/user/Projects/cx-cache-L2/MEASURE-RESULT
/home/user/Projects/cx-overlap-O9/Makefile
/home/user/Projects/cx-reorder-R4/MEASURE-REQUEST
/home/user/Projects/tomokv-cpp-perthread/Makefile
/home/user/Projects/cx-overlap-O9/src/core/atomic_admission.h
/home/user/Projects/cx-overlap-O9/src/core/atomic_tripwire.h
/home/user/Projects/cx-cache-L2/Makefile
/home/user/Projects/tomokv-cpp-perthread/src/core/atomic_tripwire.h
./tests/aclsel.py
/home/user/Projects/cx-overlap-O9/src/cmd/acl.inc
/home/user/Projects/cx-cache-L2/src/core/atomic_admission.h
./tests/aclreply.py
./tests/writer_atomic.py
./tests/writer_atomic_campaign.py
./tests/scriptatomic.py
./tests/atomicwindow.py
./tests/atomic_hazards.py
./tests/acl_categories.py
./tests/atomic_ryow.py
./tests/atomic_torn.py
./tests/execatomic.py
./tests/acl.py
./tests/atomic_survivors_unit.cc
/home/user/Projects/tomokv-cpp-perthread/src/cmd/acl.inc
/home/user/Projects/tomokv-cpp-perthread/src/cmd/acl.cc
/home/user/Projects/tomokv-cpp-perthread/src/cmd/acl_categories_generated.h
/home/user/Projects/tomokv-cpp-perthread/src/cmd/atomics_glue.inc
/home/user/Projects/tomokv-cpp-perthread/src/cmd/acl.h
/home/user/Projects/tomokv-cpp-perthread/src/store/flatstore_atomic.inc
/home/user/Projects/tomokv-cpp-perthread/src/store/atomic_mvcc.h
/home/user/Projects/cx-reorder-R4/tests/aclsel.py
/home/user/Projects/cx-reorder-R4/tests/aclreply.py
/home/user/Projects/cx-reorder-R4/tests/writer_atomic.py
/home/user/Projects/cx-reorder-R4/tests/writer_atomic_campaign.py
/home/user/Projects/cx-reorder-R4/tests/scriptatomic.py
/home/user/Projects/cx-reorder-R4/tests/atomicwindow.py
/home/user/Projects/cx-reorder-R4/tests/atomic_hazards.py
/home/user/Projects/cx-reorder-R4/tests/acl_categories.py
/home/user/Projects/cx-reorder-R4/tests/atomic_ryow.py
/home/user/Projects/cx-reorder-R4/tests/atomic_torn.py
/home/user/Projects/cx-reorder-R4/tests/execatomic.py
/home/user/Projects/cx-reorder-R4/tests/acl.py
/home/user/Projects/cx-reorder-R4/tests/atomic_survivors_unit.cc
/home/user/Projects/cx-overlap-O9/MEASURE-REQUEST
/home/user/Projects/cx-overlap-O9/tests/aclsel.py
/home/user/Projects/cx-overlap-O9/tests/aclreply.py
/home/user/Projects/cx-overlap-O9/tests/writer_atomic.py
/home/user/Projects/cx-overlap-O9/tests/writer_atomic_campaign.py
/home/user/Projects/cx-overlap-O9/tests/scriptatomic.py
/home/user/Projects/cx-overlap-O9/tests/atomicwindow.py
/home/user/Projects/cx-overlap-O9/tests/atomic_hazards.py
/home/user/Projects/cx-overlap-O9/tests/acl_categories.py
/home/user/Projects/cx-overlap-O9/tests/atomic_ryow.py
/home/user/Projects/cx-overlap-O9/tests/atomic_torn.py
/home/user/Projects/cx-overlap-O9/tests/execatomic.py
/home/user/Projects/cx-overlap-O9/tests/acl.py
/home/user/Projects/cx-overlap-O9/tests/atomic_survivors_unit.cc
/home/user/Projects/cx-overlap-O9/src/cmd/acl.h
/home/user/Projects/cx-overlap-O9/src/store/flatstore_atomic.inc
/home/user/Projects/cx-overlap-O9/src/store/atomic_mvcc.h
/home/user/Projects/cx-overlap-O9/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-overlap-O9/src/cmd/atomics_glue.inc
/home/user/Projects/cx-overlap-O9/src/cmd/acl.cc
/home/user/Projects/cx-cache-L2/MEASURE-REQUEST
/home/user/Projects/cx-cache-L2/src/cmd/acl.inc
/home/user/Projects/cx-cache-L2/src/cmd/acl.cc
/home/user/Projects/cx-cache-L2/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-cache-L2/src/cmd/atomics_glue.inc
/home/user/Projects/cx-cache-L2/src/cmd/acl.h
/home/user/Projects/cx-cache-L2/tests/aclsel.py
/home/user/Projects/cx-cache-L2/tests/aclreply.py
/home/user/Projects/cx-cache-L2/tests/writer_atomic.py
/home/user/Projects/cx-cache-L2/tests/writer_atomic_campaign.py
/home/user/Projects/cx-cache-L2/tests/scriptatomic.py
/home/user/Projects/cx-cache-L2/tests/atomicwindow.py
/home/user/Projects/cx-cache-L2/tests/atomic_hazards.py
/home/user/Projects/cx-cache-L2/tests/acl_categories.py
/home/user/Projects/cx-cache-L2/tests/atomic_ryow.py
/home/user/Projects/cx-cache-L2/tests/atomic_torn.py
/home/user/Projects/cx-cache-L2/tests/execatomic.py
/home/user/Projects/cx-cache-L2/tests/acl.py
/home/user/Projects/cx-cache-L2/tests/atomic_survivors_unit.cc
/home/user/Projects/cx-cache-L2/src/store/flatstore_atomic.inc
/home/user/Projects/cx-cache-L2/src/store/atomic_mvcc.h
/home/user/Projects/cx-cache-L2/src/core/atomic_tripwire.h
/home/user/Projects/tomokv-cpp-perthread/tests/aclsel.py
/home/user/Projects/tomokv-cpp-perthread/tests/aclreply.py
/home/user/Projects/tomokv-cpp-perthread/tests/writer_atomic.py
/home/user/Projects/tomokv-cpp-perthread/tests/writer_atomic_campaign.py
/home/user/Projects/tomokv-cpp-perthread/tests/scriptatomic.py
/home/user/Projects/tomokv-cpp-perthread/tests/atomicwindow.py
/home/user/Projects/tomokv-cpp-perthread/tests/atomic_hazards.py
/home/user/Projects/tomokv-cpp-perthread/tests/acl_categories.py
/home/user/Projects/tomokv-cpp-perthread/tests/atomic_ryow.py
/home/user/Projects/tomokv-cpp-perthread/tests/atomic_torn.py
/home/user/Projects/tomokv-cpp-perthread/tests/execatomic.py
/home/user/Projects/tomokv-cpp-perthread/tests/acl.py
/home/user/Projects/cx-cache-L4/tools/gen_acl_categories.py
/home/user/Projects/cx-cache-L4/MEASURE-RESULT
/home/user/Projects/cx-cand1/tools/gen_acl_categories.py
/home/user/Projects/cx-cache-L4/Makefile
/home/user/Projects/cx-cand1/Makefile
/home/user/Projects/cx-cache-L4/src/core/atomic_admission.h
/home/user/Projects/cx-cache-L4/src/core/atomic_tripwire.h
/home/user/Projects/cx-cand1/src/core/atomic_admission.h
/home/user/Projects/cx-cand1/src/core/atomic_tripwire.h
/home/user/Projects/cx-cache-L4/src/cmd/acl.inc
/home/user/Projects/cx-cache-L4/src/cmd/acl.cc
/home/user/Projects/cx-cache-L4/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-cache-L4/src/cmd/atomics_glue.inc
/home/user/Projects/cx-cache-L4/src/cmd/acl.h
/home/user/Projects/cx-cache-L4/src/store/flatstore_atomic.inc
/home/user/Projects/cx-cache-L4/src/store/atomic_mvcc.h
/home/user/Projects/cx-cand1/src/cmd/acl.inc
/home/user/Projects/cx-cand1/src/cmd/acl.cc
/home/user/Projects/cx-cand1/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-cand1/src/cmd/atomics_glue.inc
/home/user/Projects/cx-cand1/src/cmd/acl.h
/home/user/Projects/cx-cand1/src/store/flatstore_atomic.inc
/home/user/Projects/cx-cand1/src/store/atomic_mvcc.h
/home/user/Projects/cx-cache-L4/MEASURE-REQUEST
/home/user/Projects/cx-cache-L4/tests/aclsel.py
/home/user/Projects/cx-cache-L4/tests/aclreply.py
/home/user/Projects/cx-cache-L4/tests/writer_atomic.py
/home/user/Projects/cx-cache-L4/tests/writer_atomic_campaign.py
/home/user/Projects/cx-cache-L4/tests/scriptatomic.py
/home/user/Projects/cx-cache-L4/tests/atomicwindow.py
/home/user/Projects/cx-cache-L4/tests/atomic_hazards.py
/home/user/Projects/cx-cache-L4/tests/acl_categories.py
/home/user/Projects/cx-cache-L4/tests/atomic_ryow.py
/home/user/Projects/cx-cache-L4/tests/atomic_torn.py
/home/user/Projects/cx-cache-L4/tests/execatomic.py
/home/user/Projects/cx-cache-L4/tests/acl.py
/home/user/Projects/cx-cache-L4/tests/atomic_survivors_unit.cc
/home/user/Projects/cx-cand1/tests/aclsel.py
/home/user/Projects/cx-cand1/tests/aclreply.py
/home/user/Projects/cx-cand1/tests/writer_atomic.py
/home/user/Projects/cx-cand1/tests/writer_atomic_campaign.py
/home/user/Projects/cx-cand1/tests/scriptatomic.py
/home/user/Projects/cx-cand1/tests/atomicwindow.py
/home/user/Projects/cx-cand1/tests/atomic_hazards.py
/home/user/Projects/cx-cand1/tests/acl_categories.py
/home/user/Projects/cx-cand1/tests/atomic_ryow.py
/home/user/Projects/cx-cand1/tests/atomic_torn.py
/home/user/Projects/cx-cand1/tests/execatomic.py
/home/user/Projects/cx-cand1/tests/acl.py
/home/user/Projects/cx-cand1/tests/atomic_survivors_unit.cc
/home/user/Projects/redis8/deps/hdr_histogram/Makefile
/home/user/Projects/redis8/deps/hdr_histogram/hdr_atomic.h
/home/user/Projects/redis8/deps/xxhash/Makefile
/home/user/Projects/redis8/deps/linenoise/Makefile
/home/user/Projects/cx-overlap-O11/tools/gen_acl_categories.py
/home/user/Projects/redis8/deps/tre/Makefile
/home/user/Projects/redis8/deps/Makefile
/home/user/Projects/cx-overlap-O11/Makefile
/home/user/Projects/cx-overlap-O11/src/core/atomic_admission.h
/home/user/Projects/cx-overlap-O11/src/core/atomic_tripwire.h
/home/user/Projects/cx-overlap-O11/src/cmd/acl.inc
/home/user/Projects/cx-overlap-O11/src/cmd/acl.cc
/home/user/Projects/cx-overlap-O11/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-overlap-O11/src/cmd/atomics_glue.inc
/home/user/Projects/cx-overlap-O11/src/cmd/acl.h
/home/user/Projects/cx-overlap-O11/src/store/flatstore_atomic.inc
/home/user/Projects/cx-overlap-O11/src/store/atomic_mvcc.h
/home/user/Projects/redis8/deps/hiredis/examples/CMakeLists.txt
/home/user/Projects/redis8/deps/hiredis/CMakeLists.txt
/home/user/Projects/redis8/deps/hiredis/Makefile
/home/user/Projects/redis8/deps/fpconv/Makefile
/home/user/Projects/redis8/deps/lua/Makefile
/home/user/Projects/redis8/deps/lua/src/Makefile
/home/user/Projects/redis8/deps/lua/etc/Makefile
/home/user/Projects/cx-redisgap/tools/gen_acl_categories.py
/home/user/Projects/cx-redisgap/Makefile
/home/user/Projects/cx-redisgap/src/core/atomic_admission.h
/home/user/Projects/cx-redisgap/src/core/atomic_tripwire.h
/home/user/Projects/cx-redisgap/src/cmd/acl.inc
/home/user/Projects/cx-redisgap/src/cmd/acl.cc
/home/user/Projects/cx-redisgap/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-redisgap/src/cmd/atomics_glue.inc
/home/user/Projects/cx-redisgap/src/cmd/acl.h
/home/user/Projects/cx-overlap-O6/tools/gen_acl_categories.py
/home/user/Projects/cx-redisgap/src/store/flatstore_atomic.inc
/home/user/Projects/cx-redisgap/src/store/atomic_mvcc.h
/home/user/Projects/cx-overlap-O6/Makefile
/home/user/Projects/cx-overlap-O6/src/core/atomic_admission.h
/home/user/Projects/cx-overlap-O6/src/core/atomic_tripwire.h
/home/user/Projects/tomokv-cpp-stable/tools/gen_acl_categories.py
/home/user/Projects/cx-overlap-O6/src/cmd/acl.inc
/home/user/Projects/cx-overlap-O6/src/cmd/acl.cc
/home/user/Projects/cx-overlap-O6/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-overlap-O6/src/cmd/atomics_glue.inc
/home/user/Projects/cx-overlap-O6/src/cmd/acl.h
/home/user/Projects/cx-overlap-O6/src/store/flatstore_atomic.inc
/home/user/Projects/cx-overlap-O6/src/store/atomic_mvcc.h
/home/user/Projects/tomokv-cpp-stable/Makefile
/home/user/Projects/cx-overlap-O6/MEASURE-REQUEST
/home/user/Projects/cx-redisgap/tests/aclsel.py
/home/user/Projects/cx-redisgap/tests/aclreply.py
/home/user/Projects/cx-redisgap/tests/redisgap_atomic.py
/home/user/Projects/cx-redisgap/tests/writer_atomic.py
/home/user/Projects/cx-redisgap/tests/writer_atomic_campaign.py
/home/user/Projects/cx-redisgap/tests/scriptatomic.py
/home/user/Projects/cx-redisgap/tests/atomicwindow.py
/home/user/Projects/cx-redisgap/tests/atomic_hazards.py
/home/user/Projects/cx-redisgap/tests/acl_categories.py
/home/user/Projects/cx-redisgap/tests/atomic_ryow.py
/home/user/Projects/cx-redisgap/tests/atomic_torn.py
/home/user/Projects/cx-redisgap/tests/execatomic.py
/home/user/Projects/cx-redisgap/tests/acl.py
/home/user/Projects/cx-redisgap/tests/atomic_survivors_unit.cc
/home/user/Projects/cx-reorder-R1/tools/gen_acl_categories.py
/home/user/Projects/tomokv-cpp-stable/src/cmd/acl.inc
/home/user/Projects/tomokv-cpp-stable/src/cmd/acl.cc
/home/user/Projects/tomokv-cpp-stable/src/cmd/acl_categories_generated.h
/home/user/Projects/tomokv-cpp-stable/src/cmd/atomics_glue.inc
/home/user/Projects/tomokv-cpp-stable/src/cmd/acl.h
/home/user/Projects/tomokv-cpp-stable/src/store/flatstore_atomic.inc
/home/user/Projects/tomokv-cpp-stable/src/store/atomic_mvcc.h
/home/user/Projects/cx-reorder-R1/Makefile
/home/user/Projects/cx-reorder-R1/src/core/atomic_admission.h
/home/user/Projects/cx-reorder-R1/src/core/atomic_tripwire.h
/home/user/Projects/cx-overlap-O6/tests/aclsel.py
/home/user/Projects/cx-overlap-O6/tests/aclreply.py
/home/user/Projects/cx-overlap-O6/tests/writer_atomic.py
/home/user/Projects/cx-overlap-O6/tests/writer_atomic_campaign.py
/home/user/Projects/cx-overlap-O6/tests/scriptatomic.py
/home/user/Projects/cx-overlap-O6/tests/atomicwindow.py
/home/user/Projects/cx-overlap-O6/tests/atomic_hazards.py
/home/user/Projects/cx-overlap-O6/tests/acl_categories.py
/home/user/Projects/cx-overlap-O6/tests/atomic_ryow.py
/home/user/Projects/cx-overlap-O6/tests/atomic_torn.py
/home/user/Projects/cx-overlap-O6/tests/execatomic.py
/home/user/Projects/cx-overlap-O6/tests/acl.py
/home/user/Projects/cx-overlap-O6/tests/atomic_survivors_unit.cc
/home/user/Projects/tomokv-cpp-stable/tests/aclsel.py
/home/user/Projects/tomokv-cpp-stable/tests/writer_atomic.py
/home/user/Projects/tomokv-cpp-stable/tests/writer_atomic_campaign.py
/home/user/Projects/tomokv-cpp-stable/tests/scriptatomic.py
/home/user/Projects/tomokv-cpp-stable/tests/acl_categories.py
/home/user/Projects/tomokv-cpp-stable/tests/atomic_ryow.py
/home/user/Projects/tomokv-cpp-stable/tests/atomic_torn.py
/home/user/Projects/tomokv-cpp-stable/tests/execatomic.py
/home/user/Projects/tomokv-cpp-stable/tests/acl.py
/home/user/Projects/cx-reorder-R1/src/cmd/acl.inc
/home/user/Projects/cx-reorder-R1/src/cmd/acl.cc
/home/user/Projects/cx-reorder-R1/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-reorder-R1/src/cmd/atomics_glue.inc
/home/user/Projects/cx-reorder-R1/src/cmd/acl.h
/home/user/Projects/cx-reorder-R1/src/store/flatstore_atomic.inc
/home/user/Projects/cx-reorder-R1/src/store/atomic_mvcc.h
/home/user/Projects/cx-reorder-R1/MEASURE-REQUEST
/home/user/Projects/cand1c/abba-POST-140245/reference-source/build/src/cmd/acl.o
/home/user/Projects/cand1c/abba-POST-140245/reference-source/tools/gen_acl_categories.py
/home/user/Projects/cx-reorder-R1/tests/aclsel.py
/home/user/Projects/cx-reorder-R1/tests/aclreply.py
/home/user/Projects/cx-reorder-R1/tests/writer_atomic.py
/home/user/Projects/cx-reorder-R1/tests/writer_atomic_campaign.py
/home/user/Projects/cx-reorder-R1/tests/scriptatomic.py
/home/user/Projects/cx-reorder-R1/tests/atomicwindow.py
/home/user/Projects/cx-reorder-R1/tests/atomic_hazards.py
/home/user/Projects/cx-reorder-R1/tests/acl_categories.py
/home/user/Projects/cx-reorder-R1/tests/atomic_ryow.py
/home/user/Projects/cx-reorder-R1/tests/atomic_torn.py
/home/user/Projects/cx-reorder-R1/tests/execatomic.py
/home/user/Projects/cx-reorder-R1/tests/acl.py
/home/user/Projects/cx-reorder-R1/tests/atomic_survivors_unit.cc
/home/user/Projects/redis/deps/hdr_histogram/Makefile
/home/user/Projects/redis/deps/hdr_histogram/hdr_atomic.h
/home/user/Projects/cand1c/abba-POST-140245/reference-source/Makefile
/home/user/Projects/session-archive-20260904/srv-atomics-xscript-a0.log
/home/user/Projects/session-archive-20260904/ideas-atomics.md
/home/user/Projects/redis/deps/linenoise/Makefile
/home/user/Projects/cand1c/abba-POST-140245/reference-source/src/core/atomic_admission.h
/home/user/Projects/cand1c/abba-POST-140245/reference-source/src/core/atomic_tripwire.h
/home/user/Projects/redis/deps/Makefile
/home/user/Projects/cand1c/abba-POST-140245/reference-source/src/cmd/acl.inc
/home/user/Projects/cand1c/abba-POST-140245/reference-source/src/cmd/acl.cc
/home/user/Projects/cand1c/abba-POST-140245/reference-source/src/cmd/acl_categories_generated.h
/home/user/Projects/cand1c/abba-POST-140245/reference-source/src/cmd/atomics_glue.inc
/home/user/Projects/cand1c/abba-POST-140245/reference-source/src/cmd/acl.h
/home/user/Projects/cand1c/abba-POST-140245/reference-source/src/store/flatstore_atomic.inc
/home/user/Projects/cand1c/abba-POST-140245/reference-source/src/store/atomic_mvcc.h
/home/user/Projects/redis/Makefile
/home/user/Projects/redis8/deps/jemalloc/test/unit/atomic.c
/home/user/Projects/redis/deps/hiredis/examples/CMakeLists.txt
/home/user/Projects/redis/deps/hiredis/CMakeLists.txt
/home/user/Projects/redis/deps/hiredis/Makefile
/home/user/Projects/redis/deps/fpconv/Makefile
/home/user/Projects/redis/deps/lua/Makefile
/home/user/Projects/cand1c/abba-POST-140245/reference-source/tests/aclsel.py
/home/user/Projects/cand1c/abba-POST-140245/reference-source/tests/aclreply.py
/home/user/Projects/cand1c/abba-POST-140245/reference-source/tests/writer_atomic.py
/home/user/Projects/cand1c/abba-POST-140245/reference-source/tests/writer_atomic_campaign.py
/home/user/Projects/cand1c/abba-POST-140245/reference-source/tests/scriptatomic.py
/home/user/Projects/cand1c/abba-POST-140245/reference-source/tests/atomicwindow.py
/home/user/Projects/cand1c/abba-POST-140245/reference-source/tests/atomic_hazards.py
/home/user/Projects/cand1c/abba-POST-140245/reference-source/tests/acl_categories.py
/home/user/Projects/cand1c/abba-POST-140245/reference-source/tests/atomic_ryow.py
/home/user/Projects/cand1c/abba-POST-140245/reference-source/tests/atomic_torn.py
/home/user/Projects/cand1c/abba-POST-140245/reference-source/tests/execatomic.py
/home/user/Projects/cand1c/abba-POST-140245/reference-source/tests/acl.py
/home/user/Projects/cand1c/abba-POST-140245/reference-source/tests/atomic_survivors_unit.cc
/home/user/Projects/redis/deps/lua/src/Makefile
/home/user/Projects/redis8/deps/jemalloc/include/jemalloc/internal/atomic_gcc_sync.h
/home/user/Projects/redis8/deps/jemalloc/include/jemalloc/internal/atomic_c11.h
/home/user/Projects/redis8/deps/jemalloc/include/jemalloc/internal/atomic_msvc.h
/home/user/Projects/redis8/deps/jemalloc/include/jemalloc/internal/atomic.h
/home/user/Projects/redis8/deps/jemalloc/include/jemalloc/internal/atomic_gcc_atomic.h
/home/user/Projects/redis/deps/lua/etc/Makefile
/home/user/Projects/cx-reorder-R2/tools/gen_acl_categories.py
/home/user/Projects/redis/src/acl.c
/home/user/Projects/redis/src/Makefile
/home/user/Projects/redis/src/atomicvar.h
/home/user/Projects/cx-reorder-R2/Makefile
/home/user/Projects/redis/src/modules/helloacl.c
/home/user/Projects/redis/src/modules/Makefile
/home/user/Projects/cx-reorder-R2/src/core/atomic_admission.h
/home/user/Projects/cx-reorder-R2/src/core/atomic_tripwire.h
/home/user/Projects/cx-reorder-R2/src/cmd/acl.inc
/home/user/Projects/cx-reorder-R2/src/cmd/acl.cc
/home/user/Projects/cx-reorder-R2/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-reorder-R2/src/cmd/atomics_glue.inc
/home/user/Projects/cx-reorder-R2/src/cmd/acl.h
/home/user/Projects/tomokv-cpp/tools/gen_acl_categories.py
/home/user/Projects/cx-reorder-R2/src/store/flatstore_atomic.inc
/home/user/Projects/cx-reorder-R2/src/store/atomic_mvcc.h
/home/user/Projects/cx-reorder-R2/MEASURE-REQUEST
/home/user/Projects/garnet/test/standalone/Garnet.test.acl/Garnet.test.acl.csproj
/home/user/Projects/redis/tests/assets/nodefaultuser.acl
/home/user/Projects/redis/tests/assets/userwithselectors.acl
/home/user/Projects/redis/tests/assets/user.acl
/home/user/Projects/redis/src/commands/acl-users.json
/home/user/Projects/redis/src/commands/acl-help.json
/home/user/Projects/redis/src/commands/acl-list.json
/home/user/Projects/redis/src/commands/acl-getuser.json
/home/user/Projects/redis/src/commands/acl-load.json
/home/user/Projects/redis/src/commands/acl-genpass.json
/home/user/Projects/redis/src/commands/acl-setuser.json
/home/user/Projects/redis/src/commands/acl.json
/home/user/Projects/redis/src/commands/acl-cat.json
/home/user/Projects/redis/src/commands/acl-dryrun.json
/home/user/Projects/redis/src/commands/acl-whoami.json
/home/user/Projects/redis/src/commands/acl-deluser.json
/home/user/Projects/redis/src/commands/acl-log.json
/home/user/Projects/redis/src/commands/acl-save.json
/home/user/Projects/redis/src/acl.o
/home/user/Projects/redis/src/acl.d
/home/user/Projects/cx-reorder-R2/tests/atomic_survivors_unit.cc
/home/user/Projects/cx-reorder-R2/tests/aclsel.py
/home/user/Projects/cx-reorder-R2/tests/aclreply.py
/home/user/Projects/cx-reorder-R2/tests/writer_atomic.py
/home/user/Projects/cx-reorder-R2/tests/writer_atomic_campaign.py
/home/user/Projects/cx-reorder-R2/tests/scriptatomic.py
/home/user/Projects/cx-reorder-R2/tests/atomicwindow.py
/home/user/Projects/cx-reorder-R2/tests/atomic_hazards.py
/home/user/Projects/cx-reorder-R2/tests/acl_categories.py
/home/user/Projects/cx-reorder-R2/tests/atomic_ryow.py
/home/user/Projects/cx-reorder-R2/tests/atomic_torn.py
/home/user/Projects/cx-reorder-R2/tests/execatomic.py
/home/user/Projects/cx-reorder-R2/tests/acl.py
/home/user/Projects/redis/tests/unit/acl.tcl
/home/user/Projects/redis/tests/unit/acl-v2.tcl
/home/user/Projects/redis/tests/unit/moduleapi/aclcheck.tcl
/home/user/Projects/redis/tests/modules/atomicslotmigration.so
/home/user/Projects/redis/tests/modules/Makefile
/home/user/Projects/redis/tests/modules/aclcheck.c
/home/user/Projects/cx-deadconf-fix/tools/gen_acl_categories.py
/home/user/Projects/cx-deadconf-fix/Makefile
/home/user/Projects/redis/tests/sentinel/tests/09-acl-support.tcl
/home/user/Projects/cx-deadconf-fix/src/core/atomic_admission.h
/home/user/Projects/cx-deadconf-fix/src/core/atomic_tripwire.h
/home/user/Projects/cx-deadconf-fix/src/cmd/acl.inc
/home/user/Projects/cx-deadconf-fix/src/cmd/acl.cc
/home/user/Projects/cx-deadconf-fix/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-deadconf-fix/src/cmd/atomics_glue.inc
/home/user/Projects/cx-deadconf-fix/src/cmd/acl.h
/home/user/Projects/cx-deadconf-fix/src/store/flatstore_atomic.inc
/home/user/Projects/cx-deadconf-fix/src/store/atomic_mvcc.h
/home/user/Projects/cx-deadconf-fix/MEASURE-REQUEST
/home/user/Projects/redis/deps/jemalloc/Makefile
/home/user/Projects/cx-overlap-O11/MEASURE-REQUEST
/home/user/Projects/cx-deadconf-fix/tests/aclsel.py
/home/user/Projects/cx-deadconf-fix/tests/aclreply.py
/home/user/Projects/cx-deadconf-fix/tests/writer_atomic.py
/home/user/Projects/cx-deadconf-fix/tests/writer_atomic_campaign.py
/home/user/Projects/cx-deadconf-fix/tests/scriptatomic.py
/home/user/Projects/cx-deadconf-fix/tests/atomicwindow.py
/home/user/Projects/cx-deadconf-fix/tests/atomic_hazards.py
/home/user/Projects/cx-deadconf-fix/tests/acl_categories.py
/home/user/Projects/cx-deadconf-fix/tests/atomic_ryow.py
/home/user/Projects/cx-deadconf-fix/tests/atomic_torn.py
/home/user/Projects/cx-deadconf-fix/tests/execatomic.py
/home/user/Projects/cx-deadconf-fix/tests/acl.py
/home/user/Projects/cx-deadconf-fix/tests/atomic_survivors_unit.cc
/home/user/Projects/cx-cache-L3/tools/gen_acl_categories.py
/home/user/Projects/cx-cache-L3/MEASURE-RESULT
/home/user/Projects/cx-cache-L3/Makefile
/home/user/Projects/garnet/website/docs/commands/acl.md
/home/user/Projects/cx-cache-L3/src/core/atomic_admission.h
/home/user/Projects/cx-cache-L3/src/core/atomic_tripwire.h
/home/user/Projects/cx-overlap-O11/tests/aclsel.py
/home/user/Projects/cx-overlap-O11/tests/aclreply.py
/home/user/Projects/cx-overlap-O11/tests/writer_atomic.py
/home/user/Projects/cx-overlap-O11/tests/writer_atomic_campaign.py
/home/user/Projects/cx-overlap-O11/tests/scriptatomic.py
/home/user/Projects/cx-overlap-O11/tests/atomicwindow.py
/home/user/Projects/cx-overlap-O11/tests/atomic_hazards.py
/home/user/Projects/cx-overlap-O11/tests/acl_categories.py
/home/user/Projects/cx-overlap-O11/tests/atomic_ryow.py
/home/user/Projects/cx-overlap-O11/tests/atomic_torn.py
/home/user/Projects/cx-overlap-O11/tests/execatomic.py
/home/user/Projects/cx-overlap-O11/tests/acl.py
/home/user/Projects/cx-overlap-O11/tests/atomic_survivors_unit.cc
/home/user/Projects/cx-cache-L3/src/cmd/acl.inc
/home/user/Projects/cx-cache-L3/src/cmd/acl.cc
/home/user/Projects/cx-cache-L3/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-cache-L3/src/cmd/atomics_glue.inc
/home/user/Projects/cx-cache-L3/src/cmd/acl.h
/home/user/Projects/cx-cache-L3/src/store/flatstore_atomic.inc
/home/user/Projects/cx-cache-L3/src/store/atomic_mvcc.h
/home/user/Projects/cx-cache-L3/MEASURE-REQUEST
/home/user/Projects/redis/deps/jemalloc/include/jemalloc/internal/atomic_gcc_sync.h
/home/user/Projects/redis/deps/jemalloc/include/jemalloc/internal/atomic_c11.h
/home/user/Projects/redis/deps/jemalloc/include/jemalloc/internal/atomic_msvc.h
/home/user/Projects/redis/deps/jemalloc/include/jemalloc/internal/atomic.h
/home/user/Projects/redis/deps/jemalloc/include/jemalloc/internal/atomic_gcc_atomic.h
/home/user/Projects/redis/deps/jemalloc/test/unit/atomic.c
/home/user/Projects/cx-cache-L3/tests/aclsel.py
/home/user/Projects/cx-cache-L3/tests/aclreply.py
/home/user/Projects/cx-cache-L3/tests/writer_atomic.py
/home/user/Projects/cx-cache-L3/tests/writer_atomic_campaign.py
/home/user/Projects/cx-cache-L3/tests/scriptatomic.py
/home/user/Projects/cx-cache-L3/tests/atomicwindow.py
/home/user/Projects/cx-cache-L3/tests/atomic_hazards.py
/home/user/Projects/cx-cache-L3/tests/acl_categories.py
/home/user/Projects/cx-cache-L3/tests/atomic_ryow.py
/home/user/Projects/cx-cache-L3/tests/atomic_torn.py
/home/user/Projects/cx-cache-L3/tests/execatomic.py
/home/user/Projects/cx-cache-L3/tests/acl.py
/home/user/Projects/cx-cache-L3/tests/atomic_survivors_unit.cc
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/build/src/cmd/acl.o
/home/user/Projects/redis-8.8.1/deps/hdr_histogram/Makefile
/home/user/Projects/redis-8.8.1/deps/hdr_histogram/hdr_atomic.h
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/tools/gen_acl_categories.py
/home/user/Projects/cx-nowaitb/tools/gen_acl_categories.py
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/Makefile
/home/user/Projects/cx-nowaitb/Makefile
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/src/core/atomic_admission.h
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/src/core/atomic_tripwire.h
/home/user/Projects/cx-nowaitb/src/core/atomic_tripwire.h
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/src/cmd/acl.inc
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/src/cmd/acl.cc
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/src/cmd/acl_categories_generated.h
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/src/cmd/atomics_glue.inc
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/src/cmd/acl.h
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/src/store/flatstore_atomic.inc
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/src/store/atomic_mvcc.h
/home/user/Projects/cx-nowaitb/src/cmd/acl.inc
/home/user/Projects/cx-nowaitb/src/cmd/acl.cc
/home/user/Projects/cx-nowaitb/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-nowaitb/src/cmd/atomics_glue.inc
/home/user/Projects/cx-nowaitb/src/cmd/acl.h
/home/user/Projects/redis-8.8.1/deps/xxhash/Makefile
/home/user/Projects/cx-nowaitb/src/store/flatstore_atomic.inc
/home/user/Projects/cx-nowaitb/src/store/atomic_mvcc.h
/home/user/Projects/cx-overlap-O5/tools/gen_acl_categories.py
/home/user/Projects/cx-overlap-O5/Makefile
/home/user/Projects/cx-overlap-O5/src/core/atomic_admission.h
/home/user/Projects/cx-overlap-O5/src/core/atomic_tripwire.h
/home/user/Projects/cx-overlap-O5/src/cmd/acl.inc
/home/user/Projects/cx-overlap-O5/src/cmd/acl.cc
/home/user/Projects/cx-overlap-O5/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-overlap-O5/src/cmd/atomics_glue.inc
/home/user/Projects/cx-overlap-O5/src/cmd/acl.h
/home/user/Projects/cx-nowaitb/tests/aclsel.py
/home/user/Projects/cx-nowaitb/tests/aclreply.py
/home/user/Projects/cx-nowaitb/tests/writer_atomic.py
/home/user/Projects/cx-nowaitb/tests/writer_atomic_campaign.py
/home/user/Projects/cx-nowaitb/tests/scriptatomic.py
/home/user/Projects/cx-nowaitb/tests/atomicwindow.py
/home/user/Projects/cx-nowaitb/tests/atomic_hazards.py
/home/user/Projects/cx-nowaitb/tests/acl_categories.py
/home/user/Projects/cx-nowaitb/tests/atomic_ryow.py
/home/user/Projects/cx-nowaitb/tests/atomic_torn.py
/home/user/Projects/cx-nowaitb/tests/execatomic.py
/home/user/Projects/cx-nowaitb/tests/acl.py
/home/user/Projects/cx-overlap-O5/src/store/flatstore_atomic.inc
/home/user/Projects/cx-overlap-O5/src/store/atomic_mvcc.h
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/tests/aclsel.py
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/tests/aclreply.py
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/tests/writer_atomic.py
/home/user/Projects/cx-overlap-O5/MEASURE-REQUEST
/home/user/Projects/redis-8.8.1/deps/linenoise/Makefile
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/tests/writer_atomic_campaign.py
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/tests/scriptatomic.py
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/tests/atomicwindow.py
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/tests/atomic_hazards.py
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/tests/acl_categories.py
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/tests/atomic_ryow.py
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/tests/atomic_torn.py
/home/user/Projects/redis-8.8.1/deps/tre/Makefile
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/tests/execatomic.py
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/tests/acl.py
/home/user/Projects/cand1c/abba-PAD-143717/reference-source/tests/atomic_survivors_unit.cc
/home/user/Projects/redis-8.8.1/deps/Makefile
/home/user/Projects/dragonfly/helio/examples/CMakeLists.txt
/home/user/Projects/dragonfly/helio/examples/pingserver/CMakeLists.txt
/home/user/Projects/dragonfly/helio/examples/redis_dict/CMakeLists.txt
/home/user/Projects/dragonfly/helio/CMakeLists.txt
/home/user/Projects/dragonfly/helio/util/http/CMakeLists.txt
/home/user/Projects/dragonfly/helio/util/cloud/CMakeLists.txt
/home/user/Projects/dragonfly/helio/util/cloud/azure/CMakeLists.txt
/home/user/Projects/dragonfly/helio/util/cloud/aws/CMakeLists.txt
/home/user/Projects/dragonfly/helio/util/cloud/gcp/CMakeLists.txt
/home/user/Projects/dragonfly/helio/util/tls/CMakeLists.txt
/home/user/Projects/dragonfly/helio/util/CMakeLists.txt
/home/user/Projects/dragonfly/helio/util/html/CMakeLists.txt
/home/user/Projects/dragonfly/helio/base/pmr/CMakeLists.txt
/home/user/Projects/dragonfly/helio/base/CMakeLists.txt
/home/user/Projects/dragonfly/helio/util/metrics/CMakeLists.txt
/home/user/Projects/dragonfly/helio/util/aws/CMakeLists.txt
/home/user/Projects/dragonfly/helio/io/CMakeLists.txt
/home/user/Projects/redis-8.8.1/deps/hiredis/examples/CMakeLists.txt
/home/user/Projects/redis-8.8.1/deps/hiredis/CMakeLists.txt
/home/user/Projects/redis-8.8.1/deps/hiredis/Makefile
/home/user/Projects/dragonfly/CMakeLists.txt
/home/user/Projects/dragonfly/Makefile
/home/user/Projects/redis-8.8.1/deps/fpconv/Makefile
/home/user/Projects/dragonfly/helio/util/fibers/CMakeLists.txt
/home/user/Projects/redis-8.8.1/deps/lua/Makefile
/home/user/Projects/dragonfly/helio/AGENTS.md
/home/user/Projects/dragonfly/helio/strings/CMakeLists.txt
/home/user/Projects/redis-8.8.1/deps/lua/src/Makefile
/home/user/Projects/redis-8.8.1/deps/lua/etc/Makefile
/home/user/Projects/dragonfly/fuzz/seeds/resp/acl_ops.resp
/home/user/Projects/dragonfly/fuzz/seeds/resp/acl_ops2.resp
/home/user/Projects/dragonfly/fuzz/seeds/resp/acl.resp
/home/user/Projects/cx-overlap-O5/tests/aclsel.py
/home/user/Projects/cx-overlap-O5/tests/aclreply.py
/home/user/Projects/cx-overlap-O5/tests/writer_atomic.py
/home/user/Projects/cx-overlap-O5/tests/writer_atomic_campaign.py
/home/user/Projects/cx-overlap-O5/tests/scriptatomic.py
/home/user/Projects/cx-overlap-O5/tests/atomicwindow.py
/home/user/Projects/cx-overlap-O5/tests/atomic_hazards.py
/home/user/Projects/cx-overlap-O5/tests/acl_categories.py
/home/user/Projects/cx-overlap-O5/tests/atomic_ryow.py
/home/user/Projects/cx-overlap-O5/tests/atomic_torn.py
/home/user/Projects/cx-overlap-O5/tests/execatomic.py
/home/user/Projects/cx-overlap-O5/tests/acl.py
/home/user/Projects/cx-overlap-O5/tests/atomic_survivors_unit.cc
/home/user/Projects/dragonfly/src/core/json/CMakeLists.txt
/home/user/Projects/dragonfly/src/core/page_usage/CMakeLists.txt
/home/user/Projects/dragonfly/src/core/CMakeLists.txt
/home/user/Projects/dragonfly/src/core/search/CMakeLists.txt
/home/user/Projects/tomokv-cpp/Makefile
/home/user/Projects/redis-8.8.1/modules/redisearch/Makefile
/home/user/Projects/redis-8.8.1/modules/Makefile
/home/user/Projects/redis-8.8.1/modules/redisbloom/Makefile
/home/user/Projects/tomokv-cpp/src/core/atomic_admission.h
/home/user/Projects/tomokv-cpp/src/core/atomic_tripwire.h
/home/user/Projects/dragonfly/src/server/tiering/CMakeLists.txt
/home/user/Projects/dragonfly/src/server/journal/CMakeLists.txt
/home/user/Projects/dragonfly/src/server/CMakeLists.txt
/home/user/Projects/redis-8.8.1/modules/vector-sets/Makefile
/home/user/Projects/dragonfly/src/server/search/CMakeLists.txt
/home/user/Projects/dragonfly/src/server/acl/acl_family.cc
/home/user/Projects/dragonfly/src/server/acl/acl_log.cc
/home/user/Projects/dragonfly/src/server/acl/acl_commands_def.h
/home/user/Projects/dragonfly/src/server/acl/acl_log.h
/home/user/Projects/dragonfly/src/server/acl/acl_family_test.cc
/home/user/Projects/dragonfly/src/server/acl/acl_family.h
/home/user/Projects/redis-8.8.1/modules/redistimeseries/Makefile
/home/user/Projects/redis-8.8.1/modules/redisjson/Makefile
/home/user/Projects/dragonfly/src/server/cluster/CMakeLists.txt
/home/user/Projects/tomokv-cpp/src/cmd/acl.inc
/home/user/Projects/tomokv-cpp/src/cmd/acl.cc
/home/user/Projects/tomokv-cpp/src/cmd/acl_categories_generated.h
/home/user/Projects/tomokv-cpp/src/cmd/atomics_glue.inc
/home/user/Projects/tomokv-cpp/src/cmd/acl.h
/home/user/Projects/tomokv-cpp/src/store/flatstore_atomic.inc
/home/user/Projects/tomokv-cpp/src/store/atomic_mvcc.h
/home/user/Projects/redis-8.8.1/tests/assets/nodefaultuser.acl
/home/user/Projects/redis-8.8.1/tests/assets/userwithselectors.acl
/home/user/Projects/redis-8.8.1/tests/assets/user.acl
/home/user/Projects/cx-overlap-O2/tools/gen_acl_categories.py
/home/user/Projects/dragonfly/src/redis/CMakeLists.txt
/home/user/Projects/dragonfly/src/redis/lua/CMakeLists.txt
/home/user/Projects/dragonfly/src/CMakeLists.txt
/home/user/Projects/redis-8.8.1/tests/unit/acl.tcl
/home/user/Projects/cx-overlap-O2/Makefile
/home/user/Projects/redis-8.8.1/tests/unit/acl-v2.tcl
/home/user/Projects/dragonfly/src/facade/CMakeLists.txt
/home/user/Projects/dragonfly/AGENTS.md
/home/user/Projects/cx-overlap-O2/src/core/atomic_admission.h
/home/user/Projects/cx-overlap-O2/src/core/atomic_tripwire.h
/home/user/Projects/dragonfly/tests/dragonfly/acl_family_test.py
/home/user/Projects/cx-overlap-O2/src/cmd/acl.inc
/home/user/Projects/cx-overlap-O2/src/cmd/acl.cc
/home/user/Projects/cx-overlap-O2/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-overlap-O2/src/cmd/atomics_glue.inc
/home/user/Projects/cx-overlap-O2/src/cmd/acl.h
/home/user/Projects/cx-overlap-O2/src/store/flatstore_atomic.inc
/home/user/Projects/cx-overlap-O2/src/store/atomic_mvcc.h
/home/user/Projects/cx-overlap-O7/tools/gen_acl_categories.py
/home/user/Projects/redis8/Makefile
/home/user/Projects/cx-overlap-O2/MEASURE-REQUEST
/home/user/Projects/cx-overlap-O7/Makefile
/home/user/Projects/cx-overlap-O7/src/core/atomic_admission.h
/home/user/Projects/cx-overlap-O7/src/core/atomic_tripwire.h
/home/user/Projects/cx-overlap-O7/src/cmd/acl.inc
/home/user/Projects/cx-overlap-O7/src/cmd/acl.cc
/home/user/Projects/cx-overlap-O7/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-overlap-O7/src/cmd/atomics_glue.inc
/home/user/Projects/cx-overlap-O7/src/cmd/acl.h
/home/user/Projects/redis-8.8.1/tests/sentinel/tests/09-acl-support.tcl
/home/user/Projects/cx-overlap-O7/src/store/flatstore_atomic.inc
/home/user/Projects/cx-overlap-O7/src/store/atomic_mvcc.h
/home/user/Projects/redis8/src/acl.c
/home/user/Projects/redis8/src/Makefile
/home/user/Projects/redis8/src/atomicvar.h
/home/user/Projects/tomokv-cpp/tests/aclsel.py
/home/user/Projects/tomokv-cpp/tests/aclreply.py
/home/user/Projects/tomokv-cpp/tests/writer_atomic.py
/home/user/Projects/tomokv-cpp/tests/writer_atomic_campaign.py
/home/user/Projects/tomokv-cpp/tests/scriptatomic.py
/home/user/Projects/tomokv-cpp/tests/atomicwindow.py
/home/user/Projects/tomokv-cpp/tests/atomic_hazards.py
/home/user/Projects/tomokv-cpp/tests/acl_categories.py
/home/user/Projects/tomokv-cpp/tests/atomic_ryow.py
/home/user/Projects/tomokv-cpp/tests/atomic_torn.py
/home/user/Projects/tomokv-cpp/tests/execatomic.py
/home/user/Projects/tomokv-cpp/tests/acl.py
/home/user/Projects/tomokv-cpp/tests/atomic_survivors_unit.cc
/home/user/Projects/redis8/src/modules/helloacl.c
/home/user/Projects/redis8/src/modules/Makefile
/home/user/Projects/cx-overlap-O7/MEASURE-REQUEST
/home/user/Projects/cx-overlap-O2/tests/aclsel.py
/home/user/Projects/cx-overlap-O2/tests/aclreply.py
/home/user/Projects/cx-overlap-O2/tests/writer_atomic.py
/home/user/Projects/cx-overlap-O2/tests/writer_atomic_campaign.py
/home/user/Projects/cx-overlap-O2/tests/scriptatomic.py
/home/user/Projects/cx-overlap-O2/tests/atomicwindow.py
/home/user/Projects/cx-overlap-O2/tests/atomic_hazards.py
/home/user/Projects/cx-overlap-O2/tests/acl_categories.py
/home/user/Projects/cx-overlap-O2/tests/atomic_ryow.py
/home/user/Projects/cx-overlap-O2/tests/atomic_torn.py
/home/user/Projects/cx-overlap-O2/tests/execatomic.py
/home/user/Projects/cx-overlap-O2/tests/acl.py
/home/user/Projects/cx-overlap-O2/tests/atomic_survivors_unit.cc
/home/user/Projects/cx-overlap-O7/tests/aclsel.py
/home/user/Projects/cx-overlap-O7/tests/aclreply.py
/home/user/Projects/cx-overlap-O7/tests/writer_atomic.py
/home/user/Projects/cx-overlap-O7/tests/writer_atomic_campaign.py
/home/user/Projects/cx-overlap-O7/tests/scriptatomic.py
/home/user/Projects/cx-overlap-O7/tests/atomicwindow.py
/home/user/Projects/cx-overlap-O7/tests/atomic_hazards.py
/home/user/Projects/cx-overlap-O7/tests/acl_categories.py
/home/user/Projects/cx-overlap-O7/tests/atomic_ryow.py
/home/user/Projects/cx-overlap-O7/tests/atomic_torn.py
/home/user/Projects/cx-overlap-O7/tests/execatomic.py
/home/user/Projects/cx-overlap-O7/tests/acl.py
/home/user/Projects/cx-overlap-O7/tests/atomic_survivors_unit.cc
/home/user/Projects/session-archive-20260902/pf_srv_pf_p16get_atomic.log
/home/user/Projects/session-archive-20260902/codex_atomic6.log
/home/user/Projects/session-archive-20260902/atomictest.sh
/home/user/Projects/session-archive-20260902/b_atomic_ret.md
/home/user/Projects/session-archive-20260902/brief_atomic_b.md
/home/user/Projects/session-archive-20260902/acl.log
/home/user/Projects/session-archive-20260902/dflyatomic.sh
/home/user/Projects/session-archive-20260902/d2-oracle-7525.log
/home/user/Projects/session-archive-20260902/brief_atomic2.md
/home/user/Projects/session-archive-20260902/codex_atomic2.log
/home/user/Projects/session-archive-20260902/pf_pf_p16get_atomic.log
/home/user/Projects/session-archive-20260902/matomic.sh
/home/user/Projects/session-archive-20260902/oracle7265.log
/home/user/Projects/session-archive-20260902/dflyatomic.log
/home/user/Projects/session-archive-20260902/ratio_oracle.sh
/home/user/Projects/session-archive-20260902/atomictest_b.sh
/home/user/Projects/session-archive-20260902/mk_atomic_pin.log
/home/user/Projects/redis-8.8.1/tests/modules/atomicslotmigration.so
/home/user/Projects/redis-8.8.1/tests/modules/Makefile
/home/user/Projects/redis-8.8.1/tests/modules/atomicslotmigration.c
/home/user/Projects/redis-8.8.1/tests/modules/aclcheck.c
/home/user/Projects/redis-8.8.1/tests/modules/aclcheck.so
/home/user/Projects/redis-8.8.1/tests/unit/cluster/atomic-slot-migration.tcl
/home/user/Projects/redis8/src/commands/acl-users.json
/home/user/Projects/redis8/src/commands/acl-help.json
/home/user/Projects/redis8/src/commands/acl-list.json
/home/user/Projects/redis8/src/commands/acl-getuser.json
/home/user/Projects/redis8/src/commands/acl-load.json
/home/user/Projects/redis8/src/commands/acl-genpass.json
/home/user/Projects/redis8/src/commands/acl-setuser.json
/home/user/Projects/redis8/src/commands/acl.json
/home/user/Projects/redis8/src/commands/acl-cat.json
/home/user/Projects/redis8/src/commands/acl-dryrun.json
/home/user/Projects/redis8/src/commands/acl-whoami.json
/home/user/Projects/redis8/src/commands/acl-deluser.json
/home/user/Projects/redis8/src/commands/acl-log.json
/home/user/Projects/redis8/src/commands/acl-save.json
/home/user/Projects/redis-8.8.1/tests/unit/moduleapi/aclcheck.tcl
/home/user/Projects/redis8/modules/Makefile
/home/user/Projects/redis8/modules/vector-sets/Makefile
/home/user/Projects/redis8/tests/assets/nodefaultuser.acl
/home/user/Projects/redis8/tests/assets/userwithselectors.acl
/home/user/Projects/redis8/tests/assets/user.acl
/home/user/Projects/cx-reorder-R5/tools/gen_acl_categories.py
/home/user/Projects/redis8/tests/unit/acl.tcl
/home/user/Projects/redis8/tests/unit/acl-v2.tcl
/home/user/Projects/cx-reorder-R5/Makefile
/home/user/Projects/redis8/tests/unit/moduleapi/aclcheck.tcl
/home/user/Projects/cx-reorder-R5/src/core/atomic_admission.h
/home/user/Projects/cx-reorder-R5/src/core/atomic_tripwire.h
/home/user/Projects/redis8/tests/unit/cluster/atomic-slot-migration.tcl
/home/user/Projects/tomokv/tools/preflight/atomic_correctness.sh
/home/user/Projects/tomokv/tools/preflight/atomicity_test.py
/home/user/Projects/redis-8.8.1/src/acl.c
/home/user/Projects/redis-8.8.1/src/Makefile
/home/user/Projects/redis-8.8.1/src/atomicvar.h
/home/user/Projects/tomokv/deps/hdr_histogram/Makefile
/home/user/Projects/tomokv/deps/hdr_histogram/hdr_atomic.h
/home/user/Projects/redis8/tests/modules/Makefile
/home/user/Projects/redis8/tests/modules/atomicslotmigration.c
/home/user/Projects/redis8/tests/modules/aclcheck.c
/home/user/Projects/cx-reorder-R5/src/cmd/acl.inc
/home/user/Projects/cx-reorder-R5/src/cmd/acl.cc
/home/user/Projects/cx-reorder-R5/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-reorder-R5/src/cmd/atomics_glue.inc
/home/user/Projects/cx-reorder-R5/src/cmd/acl.h
/home/user/Projects/redis-8.8.1/src/modules/helloacl.c
/home/user/Projects/redis-8.8.1/src/modules/Makefile
/home/user/Projects/cx-reorder-R5/src/store/flatstore_atomic.inc
/home/user/Projects/cx-reorder-R5/src/store/atomic_mvcc.h
/home/user/Projects/tomokv/deps/xxhash/Makefile
/home/user/Projects/cx-reorder-R5/MEASURE-REQUEST
/home/user/Projects/tomokv/deps/linenoise/Makefile
/home/user/Projects/tomokv/deps/Makefile
/home/user/Projects/redis8/tests/sentinel/tests/09-acl-support.tcl
/home/user/Projects/cx-overlap-O8/tools/gen_acl_categories.py
/home/user/Projects/cx-reorder-R5/tests/aclsel.py
/home/user/Projects/cx-reorder-R5/tests/aclreply.py
/home/user/Projects/cx-reorder-R5/tests/writer_atomic.py
/home/user/Projects/cx-reorder-R5/tests/writer_atomic_campaign.py
/home/user/Projects/cx-reorder-R5/tests/scriptatomic.py
/home/user/Projects/cx-reorder-R5/tests/atomicwindow.py
/home/user/Projects/cx-reorder-R5/tests/atomic_hazards.py
/home/user/Projects/cx-reorder-R5/tests/acl_categories.py
/home/user/Projects/cx-reorder-R5/tests/atomic_ryow.py
/home/user/Projects/cx-reorder-R5/tests/atomic_torn.py
/home/user/Projects/cx-reorder-R5/tests/execatomic.py
/home/user/Projects/cx-reorder-R5/tests/acl.py
/home/user/Projects/cx-reorder-R5/tests/atomic_survivors_unit.cc
/home/user/Projects/cx-overlap-O8/Makefile
/home/user/Projects/cx-overlap-O8/src/core/atomic_admission.h
/home/user/Projects/cx-overlap-O8/src/core/atomic_tripwire.h
/home/user/Projects/redis-8.8.1/src/commands/acl-users.json
/home/user/Projects/redis-8.8.1/src/commands/acl-help.json
/home/user/Projects/redis-8.8.1/src/commands/acl-list.json
/home/user/Projects/redis-8.8.1/src/commands/acl-getuser.json
/home/user/Projects/redis-8.8.1/src/commands/acl-load.json
/home/user/Projects/redis-8.8.1/src/commands/acl-genpass.json
/home/user/Projects/redis-8.8.1/src/commands/acl-setuser.json
/home/user/Projects/redis-8.8.1/src/commands/acl.json
/home/user/Projects/redis-8.8.1/src/commands/acl-cat.json
/home/user/Projects/redis-8.8.1/src/commands/acl-dryrun.json
/home/user/Projects/redis-8.8.1/src/commands/acl-whoami.json
/home/user/Projects/redis-8.8.1/src/commands/acl-deluser.json
/home/user/Projects/redis-8.8.1/src/commands/acl-log.json
/home/user/Projects/redis-8.8.1/src/commands/acl-save.json
/home/user/Projects/redis-8.8.1/src/acl.o
/home/user/Projects/redis-8.8.1/src/acl.d
/home/user/Projects/redis-8.8.1/Makefile
/home/user/Projects/cx-overlap-O8/MEASURE-REQUEST
/home/user/Projects/tomokv/deps/hiredis/examples/CMakeLists.txt
/home/user/Projects/tomokv/deps/hiredis/CMakeLists.txt
/home/user/Projects/tomokv/deps/hiredis/Makefile
/home/user/Projects/cx-overlap-O8/src/cmd/acl.inc
/home/user/Projects/cx-overlap-O8/src/cmd/acl.cc
/home/user/Projects/cx-overlap-O8/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-overlap-O8/src/cmd/atomics_glue.inc
/home/user/Projects/cx-overlap-O8/src/cmd/acl.h
/home/user/Projects/tomokv/deps/fpconv/Makefile
/home/user/Projects/cx-overlap-O8/src/store/flatstore_atomic.inc
/home/user/Projects/cx-overlap-O8/src/store/atomic_mvcc.h
/home/user/Projects/tomokv/deps/fast_float/Makefile
/home/user/Projects/tomokv/deps/lua/Makefile
/home/user/Projects/cx-overlap-O8/tests/atomic_survivors_unit.cc
/home/user/Projects/tomokv/deps/lua/src/Makefile
/home/user/Projects/tomokv/deps/lua/etc/Makefile
/home/user/Projects/cx-readlocal-obs/tools/gen_acl_categories.py
/home/user/Projects/redis-8.8.1/deps/jemalloc/Makefile
/home/user/Projects/cx-readlocal-obs/MEASURE-RESULT
/home/user/Projects/cx-cache-L1/tools/gen_acl_categories.py
/home/user/Projects/cx-cache-L1/MEASURE-RESULT
/home/user/Projects/cx-readlocal-obs/Makefile
/home/user/Projects/cx-cache-L5/tools/gen_acl_categories.py
/home/user/Projects/cx-cache-L5/MEASURE-RESULT
/home/user/Projects/cx-cache-L1/Makefile
/home/user/Projects/cx-readlocal-obs/src/core/atomic_admission.h
/home/user/Projects/cx-readlocal-obs/src/core/atomic_tripwire.h
/home/user/Projects/cx-cache-L5/Makefile
/home/user/Projects/cx-cache-L1/src/core/atomic_admission.h
/home/user/Projects/cx-cache-L1/src/core/atomic_tripwire.h
/home/user/Projects/cx-readlocal-obs/src/cmd/acl.inc
/home/user/Projects/cx-readlocal-obs/src/cmd/acl.cc
/home/user/Projects/cx-readlocal-obs/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-readlocal-obs/src/cmd/atomics_glue.inc
/home/user/Projects/cx-cache-L5/src/core/atomic_admission.h
/home/user/Projects/cx-cache-L5/src/core/atomic_tripwire.h
/home/user/Projects/cx-readlocal-obs/src/cmd/acl.h
/home/user/Projects/cx-readlocal-obs/src/store/flatstore_atomic.inc
/home/user/Projects/cx-readlocal-obs/src/store/atomic_mvcc.h
/home/user/Projects/cx-cache-L1/src/cmd/acl.inc
/home/user/Projects/cx-cache-L1/src/cmd/acl.cc
/home/user/Projects/cx-cache-L1/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-cache-L1/src/cmd/atomics_glue.inc
/home/user/Projects/cx-cache-L1/src/cmd/acl.h
/home/user/Projects/cx-cache-L1/src/store/flatstore_atomic.inc
/home/user/Projects/cx-cache-L1/src/store/atomic_mvcc.h
/home/user/Projects/cx-cache-L5/src/cmd/acl.inc
/home/user/Projects/cx-cache-L5/src/cmd/acl.cc
/home/user/Projects/cx-cache-L5/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-cache-L5/src/cmd/atomics_glue.inc
/home/user/Projects/cx-cache-L5/src/cmd/acl.h
/home/user/Projects/cx-cache-L5/src/store/flatstore_atomic.inc
/home/user/Projects/cx-cache-L5/src/store/atomic_mvcc.h
/home/user/Projects/cx-readlocal-obs/MEASURE-REQUEST
/home/user/Projects/cx-cache-L1/MEASURE-REQUEST
/home/user/Projects/valkey/deps/libvalkey/examples/CMakeLists.txt
/home/user/Projects/valkey/deps/libvalkey/examples/Makefile
/home/user/Projects/valkey/deps/libvalkey/CMakeLists.txt
/home/user/Projects/valkey/deps/libvalkey/Makefile
/home/user/Projects/cx-cache-L5/MEASURE-REQUEST
/home/user/Projects/valkey/deps/libvalkey/tests/CMakeLists.txt
/home/user/Projects/valkey/deps/hdr_histogram/CMakeLists.txt
/home/user/Projects/valkey/deps/hdr_histogram/Makefile
/home/user/Projects/valkey/deps/hdr_histogram/hdr_atomic.h
/home/user/Projects/cx-readlocal-obs/tests/aclsel.py
/home/user/Projects/cx-readlocal-obs/tests/aclreply.py
/home/user/Projects/cx-readlocal-obs/tests/writer_atomic.py
/home/user/Projects/cx-readlocal-obs/tests/writer_atomic_campaign.py
/home/user/Projects/cx-readlocal-obs/tests/scriptatomic.py
/home/user/Projects/valkey/deps/linenoise/CMakeLists.txt
/home/user/Projects/valkey/deps/linenoise/Makefile
/home/user/Projects/valkey/deps/CMakeLists.txt
/home/user/Projects/cx-readlocal-obs/tests/atomicwindow.py
/home/user/Projects/cx-readlocal-obs/tests/atomic_hazards.py
/home/user/Projects/cx-readlocal-obs/tests/acl_categories.py
/home/user/Projects/cx-readlocal-obs/tests/atomic_ryow.py
/home/user/Projects/cx-readlocal-obs/tests/atomic_torn.py
/home/user/Projects/cx-readlocal-obs/tests/execatomic.py
/home/user/Projects/cx-readlocal-obs/tests/acl.py
/home/user/Projects/cx-readlocal-obs/tests/atomic_survivors_unit.cc
/home/user/Projects/cx-cache-L1/tests/aclsel.py
/home/user/Projects/cx-cache-L1/tests/aclreply.py
/home/user/Projects/cx-cache-L1/tests/writer_atomic.py
/home/user/Projects/cx-cache-L1/tests/writer_atomic_campaign.py
/home/user/Projects/cx-cache-L1/tests/scriptatomic.py
/home/user/Projects/cx-cache-L1/tests/atomicwindow.py
/home/user/Projects/cx-cache-L1/tests/atomic_hazards.py
/home/user/Projects/cx-cache-L1/tests/acl_categories.py
/home/user/Projects/cx-cache-L1/tests/atomic_ryow.py
/home/user/Projects/cx-cache-L1/tests/atomic_torn.py
/home/user/Projects/cx-cache-L1/tests/execatomic.py
/home/user/Projects/cx-cache-L1/tests/acl.py
/home/user/Projects/cx-cache-L1/tests/atomic_survivors_unit.cc
/home/user/Projects/redis-8.8.1/deps/jemalloc/test/unit/atomic.c
/home/user/Projects/valkey/deps/Makefile
/home/user/Projects/valkey/deps/fpconv/CMakeLists.txt
/home/user/Projects/valkey/deps/fpconv/Makefile
/home/user/Projects/valkey/deps/fast_float/CMakeLists.txt
/home/user/Projects/valkey/deps/lua/CMakeLists.txt
/home/user/Projects/valkey/deps/lua/Makefile
/home/user/Projects/cx-cache-L5/tests/aclsel.py
/home/user/Projects/cx-cache-L5/tests/aclreply.py
/home/user/Projects/cx-cache-L5/tests/writer_atomic.py
/home/user/Projects/cx-cache-L5/tests/writer_atomic_campaign.py
/home/user/Projects/cx-cache-L5/tests/scriptatomic.py
/home/user/Projects/cx-cache-L5/tests/atomicwindow.py
/home/user/Projects/cx-cache-L5/tests/atomic_hazards.py
/home/user/Projects/cx-cache-L5/tests/acl_categories.py
/home/user/Projects/cx-cache-L5/tests/atomic_ryow.py
/home/user/Projects/cx-cache-L5/tests/atomic_torn.py
/home/user/Projects/cx-cache-L5/tests/execatomic.py
/home/user/Projects/cx-cache-L5/tests/acl.py
/home/user/Projects/cx-cache-L5/tests/atomic_survivors_unit.cc
/home/user/Projects/valkey/deps/lua/src/Makefile
/home/user/Projects/valkey/deps/lua/etc/Makefile
/home/user/Projects/redis-8.8.1/deps/jemalloc/include/jemalloc/internal/atomic_gcc_sync.h
/home/user/Projects/redis-8.8.1/deps/jemalloc/include/jemalloc/internal/atomic_c11.h
/home/user/Projects/redis-8.8.1/deps/jemalloc/include/jemalloc/internal/atomic_msvc.h
/home/user/Projects/redis-8.8.1/deps/jemalloc/include/jemalloc/internal/atomic.h
/home/user/Projects/redis-8.8.1/deps/jemalloc/include/jemalloc/internal/atomic_gcc_atomic.h
/home/user/Projects/tomokv/deps/jemalloc/Makefile
/home/user/Projects/memcached-1.6.45/aclocal.m4
/home/user/Projects/memcached-1.6.45/Makefile
/home/user/Projects/memcached-1.6.45/vendor/Makefile
/home/user/Projects/memcached-1.6.45/vendor/mcmc/Makefile
/home/user/Projects/memcached-1.6.45/vendor/lua/Makefile
/home/user/Projects/memcached-1.6.45/vendor/lua/src/Makefile
/home/user/Projects/memcached-1.6.45/doc/Makefile
/home/user/Projects/tomokv/deps/jemalloc/test/unit/atomic.c
/home/user/Projects/cx-overlap-O1/tools/gen_acl_categories.py
/home/user/Projects/cx-overlap-O1/Makefile
/home/user/Projects/cx-overlap-O1/src/core/atomic_admission.h
/home/user/Projects/cx-overlap-O1/src/core/atomic_tripwire.h
/home/user/Projects/valkey/design-docs/atomic-slot-migration.md
/home/user/Projects/tomokv/deps/jemalloc/include/jemalloc/internal/atomic_gcc_sync.h
/home/user/Projects/cx-overlap-O8/tests/aclsel.py
/home/user/Projects/tomokv/deps/jemalloc/include/jemalloc/internal/atomic_c11.h
/home/user/Projects/tomokv/deps/jemalloc/include/jemalloc/internal/atomic_msvc.h
/home/user/Projects/tomokv/deps/jemalloc/include/jemalloc/internal/atomic.h
/home/user/Projects/tomokv/deps/jemalloc/include/jemalloc/internal/atomic_gcc_atomic.h
/home/user/Projects/cx-overlap-O8/tests/aclreply.py
/home/user/Projects/cx-overlap-O8/tests/writer_atomic.py
/home/user/Projects/cx-overlap-O8/tests/writer_atomic_campaign.py
/home/user/Projects/cx-overlap-O8/tests/scriptatomic.py
/home/user/Projects/cx-overlap-O8/tests/atomicwindow.py
/home/user/Projects/cx-overlap-O8/tests/atomic_hazards.py
/home/user/Projects/cx-overlap-O8/tests/acl_categories.py
/home/user/Projects/cx-overlap-O8/tests/atomic_ryow.py
/home/user/Projects/cx-overlap-O8/tests/atomic_torn.py
/home/user/Projects/cx-overlap-O8/tests/execatomic.py
/home/user/Projects/cx-overlap-O8/tests/acl.py
/home/user/Projects/valkey/tests/assets/nodefaultuser.acl
/home/user/Projects/valkey/tests/assets/userwithselectors.acl
/home/user/Projects/valkey/tests/assets/user.acl
/home/user/Projects/cx-delvar/tools/gen_acl_categories.py
/home/user/Projects/valkey/tests/CMakeLists.txt
/home/user/Projects/cx-delvar/Makefile
/home/user/Projects/valkey/tests/unit/acl.tcl
/home/user/Projects/valkey/tests/unit/acl-v2.tcl
/home/user/Projects/cx-delvar/src/core/atomic_tripwire.h
/home/user/Projects/codex-prompts/repro2-atomics.txt
/home/user/Projects/codex-prompts/fixfind-atomics.txt
/home/user/Projects/codex-prompts/aud-atomics.txt
/home/user/Projects/codex-prompts/diffaudit-cx-fix-atomics.txt
/home/user/Projects/codex-prompts/aud2-atomics.txt
/home/user/Projects/codex-prompts/repro-atomics.txt
/home/user/Projects/cx-delvar/src/cmd/acl.inc
/home/user/Projects/valkey/tests/unit/moduleapi/aclcheck.tcl
/home/user/Projects/cx-delvar/src/cmd/acl.cc
/home/user/Projects/cx-delvar/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-delvar/src/cmd/atomics_glue.inc
/home/user/Projects/cx-delvar/src/cmd/acl.h
/home/user/Projects/cx-delvar/src/store/flatstore_atomic.inc
/home/user/Projects/cx-delvar/src/store/atomic_mvcc.h
/home/user/Projects/tomokv/Makefile
/home/user/Projects/valkey/tests/sentinel/tests/09-acl-support.tcl
/home/user/Projects/valkey/tests/unit/cluster/acl.tcl
/home/user/Projects/valkey/tests/rdma/CMakeLists.txt
/home/user/Projects/valkey/tests/rdma/Makefile
/home/user/Projects/valkey/tests/modules/CMakeLists.txt
/home/user/Projects/valkey/tests/modules/Makefile
/home/user/Projects/valkey/tests/modules/aclcheck.c
/home/user/Projects/valkey/deps/jemalloc/CMakeLists.txt
/home/user/Projects/valkey/deps/jemalloc/Makefile
/home/user/Projects/cx-delvar/tests/aclsel.py
/home/user/Projects/cx-delvar/tests/aclreply.py
/home/user/Projects/cx-delvar/tests/writer_atomic.py
/home/user/Projects/cx-delvar/tests/writer_atomic_campaign.py
/home/user/Projects/cx-delvar/tests/scriptatomic.py
/home/user/Projects/cx-delvar/tests/atomicwindow.py
/home/user/Projects/cx-delvar/tests/atomic_hazards.py
/home/user/Projects/cx-delvar/tests/acl_categories.py
/home/user/Projects/cx-delvar/tests/atomic_ryow.py
/home/user/Projects/cx-delvar/tests/atomic_torn.py
/home/user/Projects/cx-delvar/tests/execatomic.py
/home/user/Projects/cx-delvar/tests/acl.py
/home/user/Projects/valkey/CMakeLists.txt
/home/user/Projects/valkey/Makefile
/home/user/Projects/valkey/AGENTS.md
/home/user/Projects/tomokv/src/acl.c
/home/user/Projects/tomokv/src/Makefile
/home/user/Projects/tomokv/src/atomicvar.h
/home/user/Projects/tomokv/src/modules/helloacl.c
/home/user/Projects/tomokv/src/modules/Makefile
/home/user/Projects/tomokv/docs/atomics-mvcc.md
/home/user/Projects/valkey/deps/jemalloc/include/jemalloc/internal/atomic_gcc_sync.h
/home/user/Projects/valkey/deps/jemalloc/include/jemalloc/internal/atomic_c11.h
/home/user/Projects/valkey/deps/jemalloc/include/jemalloc/internal/atomic_msvc.h
/home/user/Projects/valkey/deps/jemalloc/include/jemalloc/internal/atomic.h
/home/user/Projects/valkey/deps/jemalloc/include/jemalloc/internal/atomic_gcc_atomic.h
/home/user/Projects/tomokv/docs/mechanisms/algorithms/atomic-window.md
/home/user/Projects/tomokv/docs/bench/atomicity-torn.md
/home/user/Projects/cx-reorder-R7/tools/gen_acl_categories.py
/home/user/Projects/cx-reorder-R7/MEASURE-RESULT
/home/user/Projects/valkey/src/acl.d
/home/user/Projects/valkey/src/acl.o
/home/user/Projects/tomokv/tests/assets/nodefaultuser.acl
/home/user/Projects/tomokv/tests/assets/userwithselectors.acl
/home/user/Projects/tomokv/tests/assets/user.acl
/home/user/Projects/valkey/deps/jemalloc/test/unit/atomic.c
/home/user/Projects/cx-reorder-R7/Makefile
/home/user/Projects/cx-reorder-R7/src/core/atomic_admission.h
/home/user/Projects/cx-reorder-R7/src/core/atomic_tripwire.h
/home/user/Projects/tomokv/tests/unit/acl.tcl
/home/user/Projects/tomokv/tests/unit/acl-v2.tcl
/home/user/Projects/cx-reorder-R7/src/cmd/acl.inc
/home/user/Projects/cx-reorder-R7/src/cmd/acl.cc
/home/user/Projects/cx-reorder-R7/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-reorder-R7/src/cmd/atomics_glue.inc
/home/user/Projects/cx-reorder-R7/src/cmd/acl.h
/home/user/Projects/cx-reorder-R7/src/store/flatstore_atomic.inc
/home/user/Projects/cx-reorder-R7/src/store/atomic_mvcc.h
/home/user/Projects/valkey/src/acl.c
/home/user/Projects/valkey/src/CMakeLists.txt
/home/user/Projects/valkey/src/Makefile
/home/user/Projects/tomokv/tests/tmp/selectors.acl.322471.3/userwithselectors.acl
/home/user/Projects/tomokv/tests/tmp/resetchannels.acl.322472.9/nodefaultuser.acl
/home/user/Projects/tomokv/tests/tmp/duplicate.acl.322472.16/user.acl
/home/user/Projects/cx-reorder-R7/MEASURE-REQUEST
/home/user/Projects/tomokv/tests/tmp/resetchannels.acl.322472.6/nodefaultuser.acl
/home/user/Projects/valkey/src/unit/CMakeLists.txt
/home/user/Projects/tomokv/tests/tmp/resetchannels.acl.152425.6/nodefaultuser.acl
/home/user/Projects/valkey/src/unit/Makefile
/home/user/Projects/tomokv/tests/tmp/duplicate.acl.152425.16/user.acl
/home/user/Projects/tomokv/tests/tmp/resetchannels.acl.152425.9/nodefaultuser.acl
/home/user/Projects/valkey/src/modules/CMakeLists.txt
/home/user/Projects/tomokv/tests/tmp/selectors.acl.152424.3/userwithselectors.acl
/home/user/Projects/valkey/src/modules/helloacl.c
/home/user/Projects/valkey/src/modules/Makefile
/home/user/Projects/tomokv/src/commands/acl-users.json
/home/user/Projects/valkey/src/modules/lua/CMakeLists.txt
/home/user/Projects/valkey/src/modules/lua/Makefile
/home/user/Projects/tomokv/src/commands/acl-help.json
/home/user/Projects/tomokv/src/commands/acl-list.json
/home/user/Projects/tomokv/src/commands/acl-getuser.json
/home/user/Projects/tomokv/src/commands/acl-load.json
/home/user/Projects/tomokv/src/commands/acl-genpass.json
/home/user/Projects/tomokv/src/commands/acl-setuser.json
/home/user/Projects/tomokv/src/commands/acl.json
/home/user/Projects/tomokv/src/commands/acl-cat.json
/home/user/Projects/tomokv/src/commands/acl-dryrun.json
/home/user/Projects/tomokv/tests/sentinel/tests/09-acl-support.tcl
/home/user/Projects/tomokv/src/commands/acl-whoami.json
/home/user/Projects/tomokv/src/commands/acl-deluser.json
/home/user/Projects/tomokv/src/commands/acl-log.json
/home/user/Projects/tomokv/src/commands/acl-save.json
/home/user/Projects/tomokv/src/acl.o
/home/user/Projects/tomokv/src/acl.d
/home/user/Projects/valkey/src/commands/acl-users.json
/home/user/Projects/valkey/src/commands/acl-help.json
/home/user/Projects/valkey/src/commands/acl-list.json
/home/user/Projects/valkey/src/commands/acl-getuser.json
/home/user/Projects/valkey/src/commands/acl-load.json
/home/user/Projects/valkey/src/commands/acl-genpass.json
/home/user/Projects/valkey/src/commands/acl-setuser.json
/home/user/Projects/valkey/src/commands/acl.json
/home/user/Projects/valkey/src/commands/acl-cat.json
/home/user/Projects/valkey/src/commands/acl-dryrun.json
/home/user/Projects/valkey/src/commands/acl-whoami.json
/home/user/Projects/valkey/src/commands/acl-deluser.json
/home/user/Projects/valkey/src/commands/acl-log.json
/home/user/Projects/valkey/src/commands/acl-save.json
/home/user/Projects/tomokv/harness/setop_oracle.sh
/home/user/Projects/cx-overlap-O1/src/cmd/acl.inc
/home/user/Projects/tomokv/harness/correctness_oracle.sh
/home/user/Projects/cx-overlap-O1/src/cmd/acl.cc
/home/user/Projects/cx-overlap-O1/src/cmd/acl_categories_generated.h
/home/user/Projects/tomokv/harness/oracle_full.sh
/home/user/Projects/cx-overlap-O1/src/cmd/atomics_glue.inc
/home/user/Projects/cx-overlap-O1/src/cmd/acl.h
/home/user/Projects/cx-overlap-O10/tools/gen_acl_categories.py
/home/user/Projects/tomokv/harness/validation/mkey_oracle.c
/home/user/Projects/tomokv/harness/validation/mkey_oracle_v7.c
/home/user/Projects/cx-overlap-O1/src/store/flatstore_atomic.inc
/home/user/Projects/cx-overlap-O1/src/store/atomic_mvcc.h
/home/user/Projects/cx-reorder-R7/tests/aclsel.py
/home/user/Projects/cx-reorder-R7/tests/aclreply.py
/home/user/Projects/cx-reorder-R7/tests/writer_atomic.py
/home/user/Projects/cx-reorder-R7/tests/writer_atomic_campaign.py
/home/user/Projects/cx-reorder-R7/tests/scriptatomic.py
/home/user/Projects/cx-reorder-R7/tests/atomicwindow.py
/home/user/Projects/cx-reorder-R7/tests/atomic_hazards.py
/home/user/Projects/cx-reorder-R7/tests/acl_categories.py
/home/user/Projects/cx-reorder-R7/tests/atomic_ryow.py
/home/user/Projects/cx-reorder-R7/tests/atomic_torn.py
/home/user/Projects/cx-reorder-R7/tests/execatomic.py
/home/user/Projects/cx-reorder-R7/tests/acl.py
/home/user/Projects/cx-reorder-R7/tests/atomic_survivors_unit.cc
/home/user/Projects/cx-overlap-O10/Makefile
/home/user/Projects/cx-overlap-O1/MEASURE-REQUEST
/home/user/Projects/cx-overlap-O10/src/core/atomic_admission.h
/home/user/Projects/cx-overlap-O10/src/core/atomic_tripwire.h
/home/user/Projects/tomokv/transfer/claude-memory/thredis-atomic-session-2026-08-08.md
/home/user/Projects/tomokv/transfer/claude-memory/thredis-mset-atomicity-bakeoff.md
/home/user/Projects/cx-overlap-O10/src/cmd/acl.inc
/home/user/Projects/tomokv/transfer/claude-memory/thredis-atomic-window.md
/home/user/Projects/cx-overlap-O10/src/cmd/acl.cc
/home/user/Projects/cx-overlap-O10/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-overlap-O10/src/cmd/atomics_glue.inc
/home/user/Projects/cx-overlap-O10/src/cmd/acl.h
/home/user/Projects/cx-overlap-O10/src/store/flatstore_atomic.inc
/home/user/Projects/cx-overlap-O10/src/store/atomic_mvcc.h
/home/user/Projects/tomokv/modules/redisearch/Makefile
/home/user/Projects/tomokv/modules/Makefile
/home/user/Projects/tomokv/modules/redisbloom/Makefile
/home/user/Projects/cx-overlap-O10/MEASURE-REQUEST
/home/user/Projects/cx-overlap-O1/tests/aclsel.py
/home/user/Projects/cx-overlap-O1/tests/aclreply.py
/home/user/Projects/cx-overlap-O1/tests/writer_atomic.py
/home/user/Projects/cx-overlap-O1/tests/writer_atomic_campaign.py
/home/user/Projects/cx-overlap-O1/tests/scriptatomic.py
/home/user/Projects/cx-overlap-O1/tests/atomicwindow.py
/home/user/Projects/cx-overlap-O1/tests/atomic_hazards.py
/home/user/Projects/cx-overlap-O1/tests/acl_categories.py
/home/user/Projects/cx-overlap-O1/tests/atomic_ryow.py
/home/user/Projects/cx-overlap-O1/tests/atomic_torn.py
/home/user/Projects/cx-overlap-O1/tests/execatomic.py
/home/user/Projects/cx-overlap-O1/tests/acl.py
/home/user/Projects/cx-overlap-O1/tests/atomic_survivors_unit.cc
/home/user/Projects/tomokv/modules/vector-sets/Makefile
/home/user/Projects/tomokv/modules/redistimeseries/Makefile
/home/user/Projects/tomokv/modules/redisjson/Makefile
/home/user/Projects/cx-overlap-O10/tests/aclsel.py
/home/user/Projects/cx-overlap-O10/tests/aclreply.py
/home/user/Projects/cx-overlap-O10/tests/writer_atomic.py
/home/user/Projects/cx-overlap-O10/tests/writer_atomic_campaign.py
/home/user/Projects/cx-overlap-O10/tests/scriptatomic.py
/home/user/Projects/cx-overlap-O10/tests/atomicwindow.py
/home/user/Projects/cx-overlap-O10/tests/atomic_hazards.py
/home/user/Projects/cx-overlap-O10/tests/acl_categories.py
/home/user/Projects/cx-overlap-O10/tests/atomic_ryow.py
/home/user/Projects/cx-overlap-O10/tests/atomic_torn.py
/home/user/Projects/cx-overlap-O10/tests/execatomic.py
/home/user/Projects/cx-overlap-O10/tests/acl.py
/home/user/Projects/cx-overlap-O10/tests/atomic_survivors_unit.cc
/home/user/Projects/session-archive-20260902/oracle-7525.log
/home/user/Projects/session-archive-20260902/brief_atomic.md
/home/user/Projects/session-archive-20260902/cherry_atomic_pin.log
/home/user/Projects/session-archive-20260902/atomic_async.sh
/home/user/Projects/session-archive-20260902/at_oracle.log
/home/user/Projects/session-archive-20260902/codex_atomic3.log
/home/user/Projects/session-archive-20260902/pf_srv_pf_mset8_atomic.log
/home/user/Projects/session-archive-20260902/codex_atomic_b.log
/home/user/Projects/session-archive-20260902/brief_atomic5.md
/home/user/Projects/session-archive-20260902/brief_atomic_async.md
/home/user/Projects/session-archive-20260902/oracle.log
/home/user/Projects/session-archive-20260902/codex_atomic.log
/home/user/Projects/session-archive-20260902/brief_atomic6.md
/home/user/Projects/session-archive-20260902/codex_atomicret.log
/home/user/Projects/session-archive-20260902/codex_atomic_async.log
/home/user/Projects/session-archive-20260902/pf_pf_mset8_atomic.log
/home/user/Projects/session-archive-20260902/mergebat_oracle.log
/home/user/Projects/session-archive-20260902/brief_atomic3.md
/home/user/Projects/session-archive-20260902/codex_atomic4.log
/home/user/Projects/session-archive-20260902/codex_atomic5.log
/home/user/Projects/session-archive-20260902/brief_atomic4.md
/home/user/Projects/cand1/MEASURE-RESULT
/home/user/Projects/cx-reorder-R6/tools/gen_acl_categories.py
/home/user/Projects/garnet/libs/storage/Tsavorite/cc/CMakeLists.txt
/home/user/Projects/garnet/libs/storage/Tsavorite/cc/src/CMakeLists.txt
/home/user/Projects/cx-delvar2/tools/gen_acl_categories.py
/home/user/Projects/cx-delvar2/Makefile
/home/user/Projects/cx-delvar2/src/core/atomic_admission.h
/home/user/Projects/cx-delvar2/src/core/atomic_tripwire.h
/home/user/Projects/cx-reorder-R6/MEASURE-REQUEST
/home/user/Projects/cx-delvar2/src/cmd/acl.inc
/home/user/Projects/cx-delvar2/src/cmd/acl.cc
/home/user/Projects/cx-delvar2/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-delvar2/src/cmd/atomics_glue.inc
/home/user/Projects/cx-delvar2/src/cmd/acl.h
/home/user/Projects/cx-delvar2/src/store/flatstore_atomic.inc
/home/user/Projects/cx-delvar2/src/store/atomic_mvcc.h
/home/user/Projects/cx-delvar2/MEASURE-REQUEST
/home/user/Projects/cx-reorder-R6/tests/acl_categories.py
/home/user/Projects/cx-reorder-R6/tests/atomic_ryow.py
/home/user/Projects/cx-reorder-R6/tests/atomic_torn.py
/home/user/Projects/cx-reorder-R6/tests/execatomic.py
/home/user/Projects/cx-reorder-R6/tests/acl.py
/home/user/Projects/cx-reorder-R6/tests/atomic_survivors_unit.cc
/home/user/Projects/cx-reorder-R6/tests/scriptatomic.py
/home/user/Projects/cx-reorder-R6/tests/atomicwindow.py
/home/user/Projects/cx-reorder-R6/tests/atomic_hazards.py
/home/user/Projects/cx-reorder-R6/tests/writer_atomic.py
/home/user/Projects/cx-reorder-R6/tests/writer_atomic_campaign.py
/home/user/Projects/cx-reorder-R6/tests/aclreply.py
/home/user/Projects/cx-reorder-R6/tests/aclsel.py
/home/user/Projects/cx-reorder-R6/Makefile
/home/user/Projects/cx-reorder-R6/src/core/atomic_admission.h
/home/user/Projects/cx-reorder-R6/src/core/atomic_tripwire.h
/home/user/Projects/cx-delvar2/tests/atomic_torn.py
/home/user/Projects/cx-delvar2/tests/execatomic.py
/home/user/Projects/cx-delvar2/tests/acl.py
/home/user/Projects/cx-delvar2/tests/atomic_survivors_unit.cc
/home/user/Projects/cx-reorder-R6/src/cmd/atomics_glue.inc
/home/user/Projects/cx-reorder-R6/src/cmd/acl.h
/home/user/Projects/cx-reorder-R6/src/cmd/acl.inc
/home/user/Projects/cx-reorder-R6/src/cmd/acl.cc
/home/user/Projects/cx-reorder-R6/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-delvar2/tests/aclsel.py
/home/user/Projects/cx-delvar2/tests/aclreply.py
/home/user/Projects/cx-delvar2/tests/writer_atomic.py
/home/user/Projects/cx-delvar2/tests/writer_atomic_campaign.py
/home/user/Projects/cx-delvar2/tests/scriptatomic.py
/home/user/Projects/cx-delvar2/tests/atomicwindow.py
/home/user/Projects/cx-delvar2/tests/atomic_hazards.py
/home/user/Projects/cx-delvar2/tests/acl_categories.py
/home/user/Projects/cx-delvar2/tests/atomic_ryow.py
/home/user/Projects/cx-reorder-R6/src/store/flatstore_atomic.inc
/home/user/Projects/cx-reorder-R6/src/store/atomic_mvcc.h
/home/user/Projects/cand1/MEASURE-RESULT.draft
/home/user/Projects/cx-reorder-R8/MEASURE-REQUEST
/home/user/Projects/cx-reorder-R8/tools/gen_acl_categories.py
/home/user/Projects/r7/abba-POST-151347/reference-source/build/src/cmd/acl.o
/home/user/Projects/ycsb-0.17.0/nosqldb-binding/lib/oracle-nosql-client-3.0.5.jar
/home/user/Projects/r7/abba-POST-151347/reference-source/tools/gen_acl_categories.py
/home/user/Projects/cx-reorder-R8/Makefile
/home/user/Projects/cx-reorder-R8/src/core/atomic_admission.h
/home/user/Projects/cx-reorder-R8/src/core/atomic_tripwire.h
/home/user/Projects/r7/abba-POST-151347/reference-source/Makefile
/home/user/Projects/cx-reorder-R8/src/cmd/acl.inc
/home/user/Projects/cx-reorder-R8/src/cmd/acl.cc
/home/user/Projects/cx-reorder-R8/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-reorder-R8/src/cmd/atomics_glue.inc
/home/user/Projects/cx-reorder-R8/src/cmd/acl.h
/home/user/Projects/r7/abba-POST-151347/reference-source/src/core/atomic_admission.h
/home/user/Projects/r7/abba-POST-151347/reference-source/src/core/atomic_tripwire.h
/home/user/Projects/cx-reorder-R8/tests/aclsel.py
/home/user/Projects/cx-reorder-R8/tests/aclreply.py
/home/user/Projects/cx-reorder-R8/tests/writer_atomic.py
/home/user/Projects/cx-reorder-R8/tests/writer_atomic_campaign.py
/home/user/Projects/cx-reorder-R8/tests/scriptatomic.py
/home/user/Projects/cx-reorder-R8/tests/atomicwindow.py
/home/user/Projects/cx-reorder-R8/tests/atomic_hazards.py
/home/user/Projects/cx-reorder-R8/tests/acl_categories.py
/home/user/Projects/cx-reorder-R8/tests/atomic_ryow.py
/home/user/Projects/cx-reorder-R8/tests/atomic_torn.py
/home/user/Projects/cx-reorder-R8/tests/execatomic.py
/home/user/Projects/cx-reorder-R8/tests/acl.py
/home/user/Projects/cx-reorder-R8/tests/atomic_survivors_unit.cc
/home/user/Projects/r7/abba-POST-151347/reference-source/tests/atomic_survivors_unit.cc
/home/user/Projects/cx-reorder-R8/src/store/flatstore_atomic.inc
/home/user/Projects/cx-reorder-R8/src/store/atomic_mvcc.h
/home/user/Projects/r7/abba-POST-151347/reference-source/src/cmd/acl.inc
/home/user/Projects/r7/abba-POST-151347/reference-source/src/cmd/acl.cc
/home/user/Projects/r7/abba-POST-151347/reference-source/src/cmd/acl_categories_generated.h
/home/user/Projects/r7/abba-POST-151347/reference-source/src/cmd/atomics_glue.inc
/home/user/Projects/r7/abba-POST-151347/reference-source/src/cmd/acl.h
/home/user/Projects/r7/abba-POST-151347/reference-source/tests/aclsel.py
/home/user/Projects/r7/abba-POST-151347/reference-source/tests/aclreply.py
/home/user/Projects/r7/abba-POST-151347/reference-source/tests/writer_atomic.py
/home/user/Projects/r7/abba-POST-151347/reference-source/tests/writer_atomic_campaign.py
/home/user/Projects/r7/abba-POST-151347/reference-source/tests/scriptatomic.py
/home/user/Projects/r7/abba-POST-151347/reference-source/tests/atomicwindow.py
/home/user/Projects/r7/abba-POST-151347/reference-source/tests/atomic_hazards.py
/home/user/Projects/r7/abba-POST-151347/reference-source/tests/acl_categories.py
/home/user/Projects/r7/abba-POST-151347/reference-source/tests/atomic_ryow.py
/home/user/Projects/r7/abba-POST-151347/reference-source/tests/atomic_torn.py
/home/user/Projects/r7/abba-POST-151347/reference-source/tests/execatomic.py
/home/user/Projects/r7/abba-POST-151347/reference-source/tests/acl.py
/home/user/Projects/r7/abba-POST-151347/reference-source/src/store/flatstore_atomic.inc
/home/user/Projects/r7/abba-POST-151347/reference-source/src/store/atomic_mvcc.h
/home/user/Projects/go-ycsb/Makefile
/home/user/Projects/cx-final/tools/gen_acl_categories.py
/home/user/Projects/cx-gaterigor-integration/tools/gen_acl_categories.py
/home/user/Projects/cx-final/Makefile
/home/user/Projects/cx-gaterigor-integration/Makefile
/home/user/Projects/cx-final/src/core/atomic_admission.h
/home/user/Projects/cx-final/src/core/atomic_tripwire.h
/home/user/Projects/cx-gaterigor-integration/src/core/atomic_admission.h
/home/user/Projects/cx-gaterigor-integration/src/core/atomic_tripwire.h
/home/user/Projects/cx-final/src/cmd/acl.inc
/home/user/Projects/cx-final/src/cmd/acl.cc
/home/user/Projects/cx-final/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-final/src/cmd/atomics_glue.inc
/home/user/Projects/cx-final/src/cmd/acl.h
/home/user/Projects/cx-final/src/store/flatstore_atomic.inc
/home/user/Projects/cx-final/src/store/atomic_mvcc.h
/home/user/Projects/cx-gaterigor-integration/src/cmd/acl.inc
/home/user/Projects/cx-gaterigor-integration/src/cmd/acl.cc
/home/user/Projects/cx-gaterigor-integration/src/cmd/acl_categories_generated.h
/home/user/Projects/cx-gaterigor-integration/src/cmd/atomics_glue.inc
/home/user/Projects/cx-gaterigor-integration/src/cmd/acl.h
/home/user/Projects/cx-gaterigor-integration/src/store/flatstore_atomic.inc
/home/user/Projects/cx-gaterigor-integration/src/store/atomic_mvcc.h
/home/user/Projects/cx-final/tests/atomic_torn.py
/home/user/Projects/cx-final/tests/execatomic.py
/home/user/Projects/cx-final/tests/acl.py
/home/user/Projects/cx-final/tests/atomic_survivors_unit.cc
/home/user/Projects/cx-final/tests/acl_categories.py
/home/user/Projects/cx-final/tests/atomic_ryow.py
/home/user/Projects/cx-final/tests/atomic_hazards.py
/home/user/Projects/cx-final/tests/atomicwindow.py
/home/user/Projects/cx-final/tests/aclsel.py
/home/user/Projects/cx-final/tests/aclreply.py
/home/user/Projects/cx-final/tests/writer_atomic.py
/home/user/Projects/cx-final/tests/writer_atomic_campaign.py
/home/user/Projects/cx-final/tests/scriptatomic.py
/home/user/Projects/cx-gaterigor-integration/tests/aclsel.py
/home/user/Projects/cx-gaterigor-integration/tests/atomic_hazards.py
/home/user/Projects/cx-gaterigor-integration/tests/writer_atomic_campaign.py
/home/user/Projects/cx-gaterigor-integration/tests/acl_categories.py
/home/user/Projects/cx-gaterigor-integration/tests/scriptatomic.py
/home/user/Projects/cx-gaterigor-integration/tests/atomic_ryow.py
/home/user/Projects/cx-gaterigor-integration/tests/aclreply.py
/home/user/Projects/cx-gaterigor-integration/tests/atomicwindow.py
/home/user/Projects/cx-gaterigor-integration/tests/atomic_torn.py
/home/user/Projects/cx-gaterigor-integration/tests/writer_atomic.py
/home/user/Projects/cx-gaterigor-integration/tests/execatomic.py
/home/user/Projects/cx-gaterigor-integration/tests/atomic_survivors_unit.cc
/home/user/Projects/cx-gaterigor-integration/tests/acl.py

exec
/bin/bash -lc 'for directory in / /home /home/user /home/user/Projects /home/user/Projects/cx-deadconf-fix; do if test -f "$directory/AGENTS.md"; then printf '"'%s\\n' \""'$directory/AGENTS.md"; cat "$directory/AGENTS.md"; fi; done
rg --files --hidden -g AGENTS.md -g '"'"'!.git'"' -g '"'!build/**'"' ." in /home/user/Projects/cx-deadconf-fix
 exited 1 in 0ms:
exec
/bin/bash -lc "sed -n '1,280p' tests/acl.py
sed -n '1,260p' src/cmd/acl.cc
sed -n '200,440p' src/cmd/acl.inc" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
#!/usr/bin/env python3
"""Directed Redis 7.4 ACL grammar, enforcement, closure, and persistence gate.

Usage: tests/acl.py HOST PORT ACLFILE
"""

import glob
import os
import select
import socket
import sys
import threading
import time


HOST, PORT, ACLFILE = sys.argv[1], int(sys.argv[2]), sys.argv[3]


def assert_notification_delivery_not_acl_checked():
    """Keyspace notifications share pubsub_deliver and must bypass & rules."""
    source_path = os.path.join(os.path.dirname(__file__), "..", "src", "core", "pubsub.inc")
    with open(source_path, "r", encoding="utf-8") as source_file:
        source = source_file.read()
    # The fanout redesign split delivery into deliver_one/deliver_batch; the span still ends at
    # home_publish, so the whole delivery path stays inside the checked region.
    start = source.index("    void pubsub_deliver_one(")
    end = source.index("\n    void pubsub_home_publish(", start)
    if "acl_" in source[start:end]:
        raise AssertionError("pubsub delivery must not apply ACL channel rules")


assert_notification_delivery_not_acl_checked()


class RespError(Exception):
    pass


def frame(*args):
    values = [arg if isinstance(arg, bytes) else str(arg).encode() for arg in args]
    return (b"*%d\r\n" % len(values) +
            b"".join(b"$%d\r\n" % len(value) + value + b"\r\n" for value in values))


class Conn:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=10)
        self.file = self.sock.makefile("rb")

    def send(self, *args):
        self.sock.sendall(frame(*args))

    def command(self, *args):
        self.send(*args)
        return self.read()

    def read(self):
        kind = self.file.read(1)
        if not kind:
            raise EOFError("server closed")
        line = self.file.readline()
        if not line.endswith(b"\r\n"):
            raise EOFError("truncated reply")
        value = line[:-2]
        if kind == b"+":
            return value
        if kind == b"-":
            return RespError(value.decode("utf-8", "replace"))
        if kind == b":":
            return int(value)
        if kind == b"$":
            size = int(value)
            if size == -1:
                return None
            data = self.file.read(size)
            assert self.file.read(2) == b"\r\n"
            return data
        if kind == b"*":
            count = int(value)
            return None if count == -1 else [self.read() for _ in range(count)]
        raise AssertionError("unknown RESP prefix %r" % kind)

    def close(self):
        try:
            self.file.close()
        finally:
            self.sock.close()


def expect(actual, wanted, label):
    if isinstance(wanted, str) and isinstance(actual, RespError):
        actual = str(actual)
    if actual != wanted:
        raise AssertionError("%s: got %r, wanted %r" % (label, actual, wanted))


def fields(reply):
    assert isinstance(reply, list) and len(reply) == 12, reply
    return {reply[i]: reply[i + 1] for i in range(0, len(reply), 2)}


def map_fields(reply):
    assert isinstance(reply, list) and len(reply) == 20, reply
    return {reply[i]: reply[i + 1] for i in range(0, len(reply), 2)}


def stats(conn):
    body = conn.command("INFO", "STATS")
    result = {}
    for line in body.split(b"\r\n"):
        if b":" in line:
            key, value = line.split(b":", 1)
            if value.isdigit():
                result[key] = int(value)
    return result


def wait_closed(conn, timeout=6):
    deadline = time.time() + timeout
    while time.time() < deadline:
        readable, _, _ = select.select([conn.sock], [], [], 0.2)
        if not readable:
            continue
        try:
            if conn.sock.recv(1, socket.MSG_PEEK) == b"":
                return
        except (ConnectionError, OSError):
            return
    raise AssertionError("connection was not closed by ACL revocation")


admin = Conn()
is_tomokv = b"tomokv_version:" in admin.command("INFO", "SERVER")
if ACLFILE == "-":
    nofile = ("ERR This Redis instance is not configured to use an ACL file. You may want to "
              "specify users via the ACL SETUSER command and then issue a CONFIG REWRITE "
              "(assuming you have a Redis configuration file set) in order to store users in "
              "the Redis configuration.")
    expect(admin.command("ACL", "LOAD"), nofile, "ACL LOAD without aclfile")
    expect(admin.command("ACL", "SAVE"), nofile, "ACL SAVE without aclfile")
    admin.close()
    print("acl: PASS (no-aclfile errors)")
    raise SystemExit(0)

expect(admin.command("ACL", "WHOAMI"), b"default", "default WHOAMI")
for username in admin.command("ACL", "USERS"):
    if username != b"default":
        admin.command("ACL", "DELUSER", username)

expect(admin.command("CONFIG", "GET", "acl-pubsub-default"),
       [b"acl-pubsub-default", b"resetchannels"], "pubsub ACL default")
expect(admin.command("ACL", "SETUSER", "channel-default"), b"OK", "new default-channel user")
expect(fields(admin.command("ACL", "GETUSER", "channel-default"))[b"channels"], b"",
       "new user resetchannels")
expect(admin.command("CONFIG", "SET", "acl-pubsub-default", "allchannels"), b"OK",
       "live pubsub ACL default")
expect(admin.command("ACL", "SETUSER", "channel-all"), b"OK", "new allchannels user")
expect(fields(admin.command("ACL", "GETUSER", "channel-all"))[b"channels"], b"&*",
       "new user allchannels")
expect(admin.command("ACL", "DELUSER", "channel-default", "channel-all"), 2,
       "delete channel-default probes")
expect(admin.command("CONFIG", "SET", "acl-pubsub-default", "resetchannels"), b"OK",
       "restore pubsub ACL default")

password = b"s3cr\x00et"
rules = [
    "on", b">" + password, "resetkeys", "~*", "resetchannels", "&news.*",
    "-@all", "+get", "+set", "+mget", "+mset", "+multi", "+exec",
    "+blpop", "+lpush", "+subscribe", "+unsubscribe", "+psubscribe",
    "+punsubscribe", "+ssubscribe", "+sunsubscribe", "+publish", "+spublish",
    "+eval", "+evalsha",
]
expect(admin.command("ACL", "SETUSER", "alice", *rules), b"OK", "SETUSER grammar")

alice_info = fields(admin.command("ACL", "GETUSER", "alice"))
if alice_info[b"flags"] != [b"on", b"sanitize-payload"]:
    raise AssertionError("flags/order: %r" % alice_info[b"flags"])
if len(alice_info[b"passwords"]) != 1 or len(alice_info[b"passwords"][0]) != 64:
    raise AssertionError("password hash shape: %r" % alice_info[b"passwords"])
expect(alice_info[b"keys"], b"~*", "GETUSER keys")
expect(alice_info[b"channels"], b"&news.*", "GETUSER channels")
expect(alice_info[b"selectors"], [], "GETUSER selectors")

listed = admin.command("ACL", "LIST")
if listed != sorted(listed) or not listed[0].startswith(b"user alice "):
    raise AssertionError("ACL LIST ordering/shape: %r" % listed)
expect(admin.command("ACL", "USERS"), [b"alice", b"default"], "USERS ordering")

expect(admin.command("ACL", "SETUSER", "bad-rw", "%R~cache:*"),
       "ERR Error in ACL SETUSER modifier '%R~cache:*': Read/write key patterns are not supported until command key specifications are available",
       "%R rule rejected")
expect(admin.command("ACL", "SETUSER", "bad-selector", "(on +get)"),
       "ERR Error in ACL SETUSER modifier '(on +get)': Syntax error",
       "invalid selector rejected")
expect(admin.command("ACL", "SETUSER", "bad-firstarg", "+select|0"),
       "ERR Error in ACL SETUSER modifier '+select|0': Allowing first-arg of a subcommand is not supported",
       "first-arg rule rejected")

alice = Conn()
expect(alice.command("AUTH", "alice", password), b"OK", "multi-user AUTH")
expect(alice.command("ACL", "WHOAMI"),
       "NOPERM User alice has no permissions to run the 'acl' command", "ACL command bit")
expect(alice.command("AUTH", "default", "anything"), b"OK", "AUTH identity switch")
expect(alice.command("ACL", "WHOAMI"), b"default", "WHOAMI after default switch")
expect(alice.command("HELLO", "2", "AUTH", "alice", password)[:2],
       [b"server", b"redis"], "HELLO AUTH multi-user")

expect(admin.command("SET", "a:1", "A"), b"OK", "seed a")
expect(admin.command("SET", "b:1", "B"), b"OK", "seed b")
expect(admin.command("ACL", "SETUSER", "alice", "resetkeys", "~a:*"), b"OK",
       "restrict keys")
expect(alice.command("GET", "a:1"), b"A", "allowed GET")
expect(alice.command("GET", "b:1"), "NOPERM No permissions to access a key", "denied GET")
expect(alice.command("MGET", "a:1", "b:1"),
       "NOPERM No permissions to access a key", "denied key inside MGET")
expect(alice.command("MSET", "a:2", "x", "b:2", "y"),
       "NOPERM No permissions to access a key", "denied key inside MSET")
expect(admin.command("GET", "a:2"), None, "denied MSET is atomic at admission")
expect(alice.command("EVAL", "return redis.call('GET',KEYS[1])", 1, "a:1"),
       "NOPERM User alice has no permissions to run the 'eval' command", "Lua v1 deny")

# Queue-time denial dirties EXEC; a later permission change is instead a per-element EXEC error.
expect(alice.command("MULTI"), b"OK", "MULTI queue-time")
expect(alice.command("GET", "b:1"), "NOPERM No permissions to access a key",
       "queue-time ACL denial")
expect(alice.command("EXEC"),
       "EXECABORT Transaction discarded because of previous errors.", "queue-time EXECABORT")

expect(admin.command("ACL", "SETUSER", "alice", "resetkeys", "~*"), b"OK",
       "open keys before EXEC")
expect(alice.command("MULTI"), b"OK", "MULTI recheck")
expect(alice.command("GET", "a:1"), b"QUEUED", "queue allowed a")
expect(alice.command("GET", "b:1"), b"QUEUED", "queue allowed b")
expect(admin.command("ACL", "SETUSER", "alice", "resetkeys", "~a:*"), b"OK",
       "revoke between MULTI and EXEC")
exec_reply = alice.command("EXEC")
expect(exec_reply[0], b"A", "EXEC partial allowed element")
expect(exec_reply[1],
       "NOPERM ACLs rules changed between the moment the transaction was accumulated and the EXEC call. This command is no longer allowed for the following reason: no permission to touch the specified keys",
       "EXEC per-element ACL recheck")

# Blocking completion must consult the current immutable permission blob, not its admission copy.
expect(admin.command("ACL", "SETUSER", "alice", "resetkeys", "~block:*"), b"OK",
       "allow blocking key")
blocked = Conn()
expect(blocked.command("AUTH", "alice", password), b"OK", "blocking AUTH")
blocking_reply = []
thread = threading.Thread(target=lambda: blocking_reply.append(
    blocked.command("BLPOP", "block:k", 0)))
thread.start()
time.sleep(0.25)
expect(admin.command("ACL", "SETUSER", "alice", "resetkeys", "~other:*"), b"OK",
       "revoke blocked key")
expect(admin.command("LPUSH", "block:k", "value"), 1, "wake blocked command")
thread.join(5)
expect(blocking_reply[0], "NOPERM No permissions to access a key", "blocking recheck")

# Three subscription namespaces and both publish forms share one channel-pattern namespace.
expect(admin.command("ACL", "SETUSER", "alice", "resetchannels", "&news.*"), b"OK",
       "restore channels")
expect(alice.command("PUBLISH", "other", "x"),
       "NOPERM No permissions to access a channel", "PUBLISH channel check")
expect(alice.command("SPUBLISH", "other", "x"),
       "NOPERM No permissions to access a channel", "SPUBLISH channel check")

sub = Conn(); expect(sub.command("AUTH", "alice", password), b"OK", "SUBSCRIBE AUTH")
expect(sub.command("SUBSCRIBE", "news.a"), [b"subscribe", b"news.a", 1], "SUBSCRIBE allow")
sub.send("UNSUBSCRIBE", "other")
unsub = sub.read()
if unsub[:2] != [b"unsubscribe", b"other"]:
    raise AssertionError("UNSUBSCRIBE channel exemption: %r" % (unsub,))
sub.close()

psub = Conn(); expect(psub.command("AUTH", "alice", password), b"OK", "PSUBSCRIBE AUTH")
expect(psub.command("PSUBSCRIBE", "news.*"), [b"psubscribe", b"news.*", 1],
       "PSUBSCRIBE literal allow")
psub.close()
psub_bad = Conn(); expect(psub_bad.command("AUTH", "alice", password), b"OK", "PSUB bad AUTH")
expect(psub_bad.command("PSUBSCRIBE", "news.a*"),
       "NOPERM No permissions to access a channel", "PSUBSCRIBE literal deny")
// acl.cc -- the sole stitch point for the Redis ACL machinery.

#include <algorithm>
#include <array>
#include <atomic>
#include <cctype>
#include <cerrno>
#include <climits>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <fcntl.h>
#include <mutex>
#include <string>
#include <sys/random.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "acl.h"
#include "acl_categories_generated.h"
#include "auth.h"
#include "command.h"
#include "cmdmeta.h"
#include "multi.h"
#include "../core/config.h"
#include "../core/io_loop.h"
#include "../core/server.h"
#include "../core/thread.h"
#include "../exec/op.h"
#include "../net/conn.h"
#include "../net/resp.h"

#include "acl.inc"
        if (old.size() == value.n && !std::memcmp(old.data(), value.p, value.n)) return;
    patterns.emplace_back(value.p, value.n);
}

bool acl_valid_username(Slice name) {
    if (!name.n) return false;
    for (uint32_t i = 0; i < name.n; i++)
        if (name.p[i] == '\0' || name.p[i] == ' ' || name.p[i] == '\t' ||
            name.p[i] == '\r' || name.p[i] == '\n') return false;
    return true;
}

AclUserImage acl_new_image(const std::string& name) {
    AclUserImage image;
    image.name = name;
    image.flags = AclUserDisabled | AclUserSanitize;
    if (g_acl_pubsub_default_all) image.perm.flags |= AclAllChannels;
    return image;
}

bool acl_apply_permission_rule(AclSelector& perm, Slice rule, std::string& error) {
    if (acl_equal_icase(rule, "allkeys") || acl_equal_icase(rule, "~*")) {
        perm.flags |= AclAllKeys;
        perm.key_patterns.clear();
    } else if (acl_equal_icase(rule, "resetkeys")) {
        perm.flags &= ~AclAllKeys;
        perm.key_patterns.clear();
    } else if (acl_equal_icase(rule, "allchannels") || acl_equal_icase(rule, "&*")) {
        perm.flags |= AclAllChannels;
        perm.channel_patterns.clear();
    } else if (acl_equal_icase(rule, "resetchannels")) {
        perm.flags &= ~AclAllChannels;
        perm.channel_patterns.clear();
    } else if (acl_equal_icase(rule, "allcommands")) {
        acl_reset_commands(perm, true);
    } else if (acl_equal_icase(rule, "nocommands")) {
        acl_reset_commands(perm, false);
    } else if (rule.p[0] == '%') {
        error = "Read/write key patterns are not supported until command key specifications are available";
        return false;
    } else if (rule.p[0] == '~') {
        if (perm.flags & AclAllKeys) {
            error = "Adding a pattern after the * pattern (or the 'allkeys' flag) is not valid and does not have any effect. Try 'resetkeys' to start with an empty list of patterns";
            return false;
        }
        acl_add_unique(perm.key_patterns, Slice(rule.p + 1, rule.n - 1));
    } else if (rule.p[0] == '&') {
        if (perm.flags & AclAllChannels) {
            error = "Adding a pattern after the * pattern (or the 'allchannels' flag) is not valid and does not have any effect. Try 'resetchannels' to start with an empty list of channels";
            return false;
        }
        acl_add_unique(perm.channel_patterns, Slice(rule.p + 1, rule.n - 1));
    } else if (!acl_apply_command_rule(perm, rule, error)) {
        return false;
    }
    return true;
}

AclUserImage acl_image(const AclUser& user) {
    AclUserImage image;
    image.name = user.name;
    image.flags = user.flags;
    image.passwords = user.passwords;
    const AclPerm* perm = user.perm.load(std::memory_order_acquire);
    if (perm) image.perm = *perm;
    return image;
}

bool acl_apply_rule(AclUserImage& image, Slice rule, std::string& error) {
    if (!rule.n) return true;
    if (acl_equal_icase(rule, "on")) {
        image.flags |= AclUserEnabled;
        image.flags &= ~AclUserDisabled;
    } else if (acl_equal_icase(rule, "off")) {
        image.flags |= AclUserDisabled;
        image.flags &= ~AclUserEnabled;
    } else if (acl_equal_icase(rule, "sanitize-payload")) {
        image.flags |= AclUserSanitize;
        image.flags &= ~AclUserSkipSanitize;
    } else if (acl_equal_icase(rule, "skip-sanitize-payload")) {
        image.flags |= AclUserSkipSanitize;
        image.flags &= ~AclUserSanitize;
    } else if (acl_equal_icase(rule, "nopass")) {
        image.flags |= AclUserNoPass;
        image.passwords.clear();
    } else if (acl_equal_icase(rule, "resetpass")) {
        image.flags &= ~AclUserNoPass;
        image.passwords.clear();
    } else if (acl_equal_icase(rule, "reset")) {
        image.passwords.clear();
        image.flags = AclUserDisabled | AclUserSanitize;
        image.perm = AclPerm{};
        if (g_acl_pubsub_default_all) image.perm.flags |= AclAllChannels;
    } else if (acl_equal_icase(rule, "clearselectors")) {
        image.perm.selectors.clear();
    } else if (rule.p[0] == '>' || rule.p[0] == '#') {
        std::array<uint64_t, 4> digest;
        if (rule.p[0] == '>') digest = auth_password_digest(Slice(rule.p + 1, rule.n - 1));
        else if (!acl_parse_hash(Slice(rule.p + 1, rule.n - 1), digest)) {
            error = "The password hash must be exactly 64 characters and contain only lowercase hexadecimal characters";
            return false;
        }
        bool duplicate = false;
        for (const auto& password : image.passwords) duplicate |= acl_digest_equal(password, digest);
        if (!duplicate) image.passwords.push_back(digest);
        image.flags &= ~AclUserNoPass;
    } else if (rule.p[0] == '<' || rule.p[0] == '!') {
        std::array<uint64_t, 4> digest;
        if (rule.p[0] == '<') digest = auth_password_digest(Slice(rule.p + 1, rule.n - 1));
        else if (!acl_parse_hash(Slice(rule.p + 1, rule.n - 1), digest)) {
            error = "The password hash must be exactly 64 characters and contain only lowercase hexadecimal characters";
            return false;
        }
        auto found = std::find_if(image.passwords.begin(), image.passwords.end(),
            [&](const auto& password) { return acl_digest_equal(password, digest); });
        if (found == image.passwords.end()) {
            error = "The password you are trying to remove from the user does not exist";
            return false;
        }
        image.passwords.erase(found);
    } else if (rule.p[0] == '(' || rule.p[rule.n - 1] == ')') {
        error = "Syntax error";
        return false;
    } else if (!acl_apply_permission_rule(image.perm, rule, error)) {
        return false;
    }
    return true;
}

bool acl_apply_rules(AclUserImage& image, const std::vector<std::string>& rules,
                     size_t begin, std::string& error, std::string* failed = nullptr) {
    for (size_t i = begin; i < rules.size(); i++) {
        if (!rules[i].empty() && rules[i][0] == '(') {
            error = "ACL selectors are not supported";
            if (failed) *failed = rules[i];
            return false;
        }
        const Slice rule(rules[i].data(), static_cast<uint32_t>(rules[i].size()));
        if (!acl_apply_rule(image, rule, error)) {
            if (failed) *failed = rules[i];
            return false;
        }
    }
    return true;
}

void acl_verify_command_description(const AclSelector& perm) {
    AclSelector predicted;
    acl_reset_commands(predicted, acl_future_commands(perm));
    for (const std::string& rule : perm.command_rules) {
        std::string error;
        if (!acl_apply_command_rule(predicted,
                Slice(rule.data(), static_cast<uint32_t>(rule.size())), error, false)) std::abort();
    }
    if (std::memcmp(predicted.allowed_commands, perm.allowed_commands,
                    sizeof(perm.allowed_commands))) std::abort();
}

std::string acl_describe_commands(const AclSelector& perm) {
    acl_verify_command_description(perm);
    std::string result = acl_future_commands(perm) ? "+@all" : "-@all";
    for (const std::string& rule : perm.command_rules) {
        result.push_back(' ');
        result += rule;
    }
    return result;
}

std::string acl_join_patterns(const AclSelector& perm, bool channel) {
    std::string result;
    if (channel) {
        if (perm.flags & AclAllChannels) return "&*";
        result = "resetchannels";
        for (const std::string& pattern : perm.channel_patterns) {
            result += " &";
            result += pattern;
        }
    } else {
        if (perm.flags & AclAllKeys) return "~*";
        for (const std::string& pattern : perm.key_patterns) {
            if (!result.empty()) result.push_back(' ');
            result.push_back('~');
            result += pattern;
        }
    }
    return result;
}

std::string acl_getuser_channels(const AclSelector& perm) {
    if (perm.flags & AclAllChannels) return "&*";
    std::string result;
    for (const std::string& pattern : perm.channel_patterns) {
        if (!result.empty()) result.push_back(' ');
        result.push_back('&');
        result += pattern;
    }
    return result;
}

std::string acl_describe_image(const AclUserImage& image) {
    std::string result;
    auto flag = [&](const char* text) {
        if (!result.empty()) result.push_back(' ');
        result += text;
    };
    if (image.flags & AclUserEnabled) flag("on");
    if (image.flags & AclUserDisabled) flag("off");
    if (image.flags & AclUserNoPass) flag("nopass");
    if (image.flags & AclUserSkipSanitize) flag("skip-sanitize-payload");
    if (image.flags & AclUserSanitize) flag("sanitize-payload");
    for (const auto& password : image.passwords) flag(("#" + acl_hex_hash(password)).c_str());
    const std::string keys = acl_join_patterns(image.perm, false);
    if (!keys.empty()) flag(keys.c_str());
    flag(acl_join_patterns(image.perm, true).c_str());
    flag(acl_describe_commands(image.perm).c_str());
    for (const AclSelector& selector : image.perm.selectors) {
        std::string description = "(";
        const std::string keys = acl_join_patterns(selector, false);
        if (!keys.empty()) description += keys + " ";
        description += acl_join_patterns(selector, true);
        description.push_back(' ');
        description += acl_describe_commands(selector);
        description.push_back(')');
        flag(description.c_str());
    }
    return result;
}

AclUser* acl_slot(uint32_t index) {
    if (index >= kAclMaxUsers) return nullptr;
    return g_acl_slots[index].load(std::memory_order_acquire);
}

bool acl_default_permission_unrestricted_locked() {
    AclUser* user = acl_slot(kAclDefaultUser);
    if (!user || !(user->flags & AclUserEnabled)) return false;
    const AclPerm* perm = user->perm.load(std::memory_order_acquire);
    return perm && (perm->flags & (AclAllKeys | AclAllCommands | AclAllChannels)) ==
                       (AclAllKeys | AclAllCommands | AclAllChannels);
}


exec
/bin/bash -lc "sed -n '1,220p' Makefile
rg -n -C 5 'ACL battery|tests/acl.py|enable-atomics|--atomics|--cores|--ratio|"'^start'"' tests/gate.sh src/main.cc" in /home/user/Projects/cx-deadconf-fix
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
tests/gate.sh-709-                 # "see $SRVLOG" and the log was rotated by the next row's mktemp before anyone
tests/gate.sh-710-                 # opened it.
tests/gate.sh-711-  printf 'GATE: boot (%s) %s -- last 25 lines of %s:\n' "$1" "$2" "$SRVLOG" >&2
tests/gate.sh-712-  tail -n 25 "$SRVLOG" 2>/dev/null | sed 's/^/GATE|   /' >&2
tests/gate.sh-713-}
tests/gate.sh:714:boot(){ local bin=$1; shift; launch main "$bin" --ratio $GATE_RATIO "$@"; }
tests/gate.sh:715:boot_fused(){ # deliberately omits --ratio, which fused mode rejects
tests/gate.sh-716-  local bin=$1; shift; launch fused "$bin" --thread-mode fused "$@"; }
tests/gate.sh-717-stop(){
tests/gate.sh-718-  if [ "$SRV" -gt 0 ]; then
tests/gate.sh-719-    kill -TERM "$SRV" 2>/dev/null
tests/gate.sh-720-    if ! timeout --kill-after=1 30 tail --sleep-interval=.1 --pid="$SRV" -f /dev/null; then
--
tests/gate.sh-852-      row_begin "$label"
tests/gate.sh-853-      py tests/evict_battery.py "$PORT" "$section" >"$TMPDIR/battery.log" 2>&1 \
tests/gate.sh-854-          && ok "$label" || bad "$label" "see $TMPDIR/battery.log"
tests/gate.sh-855-      stop;;
tests/gate.sh-856-    flipctl)
tests/gate.sh:857:      boot "$CANDIDATE_BINARY" --ratio 6:2 --atomic 0 --enable-debug-command yes --flip-auto 1 \
tests/gate.sh-858-          || bad 'flipctl boot'
tests/gate.sh-859-      # Retain the original bounded stationary-hold re-rolls and every directed assertion.
tests/gate.sh-860-      row_begin "$label"
tests/gate.sh-861-      python3 tests/flipctl.py --host 127.0.0.1 --port "$PORT" --stable-seconds 30 \
tests/gate.sh-862-          >"$TMPDIR/battery.log" 2>&1 && ok "$label" || bad "$label" "see $TMPDIR/battery.log"
--
tests/gate.sh-933-  started=$(date +%s.%N); ROW_T=$started
tests/gate.sh-934-  job_body "$name" >"$TMPDIR/output.log" 2>&1
tests/gate.sh-935-  rc=$?
tests/gate.sh-936-  exit "$rc"
tests/gate.sh-937-); }
tests/gate.sh:938:start_workers(){
tests/gate.sh-939-  phase parallel-begin
tests/gate.sh-940-  # Serialization is limited to binary publication, shared release-object writes, one job per
tests/gate.sh-941-  # CPU/three-port slot, and the operations inside a shared boot/recovery chain. All files written
tests/gate.sh-942-  # by independent batteries are private TMPDIR/mktemp paths; the coordinator alone owns ledgers.
tests/gate.sh-943-  # TLS uses PORT+1, nested servertail uses PORT+2, and oracle boots use these same reserved ports.
--
tests/gate.sh-1117-  # A broken rejection may accidentally start a server. Its affinity, bind, data directory and
tests/gate.sh-1118-  # lifetime must still obey this slot. Config-file paths remain first, as the parser requires.
tests/gate.sh-1119-  if [[ "$1" != --* ]]; then conf=("$1"); shift; fi
tests/gate.sh-1120-  directory=$(mktemp -d "$TMPDIR/reject-boot.XXXXXX") || return 1
tests/gate.sh-1121-  timeout --kill-after=5 10 taskset -c "$CORES" "$CANDIDATE_BINARY" "${conf[@]}" \
tests/gate.sh:1122:      --port "$PORT" --bind 127.0.0.1 --shards 16 --ratio "$GATE_RATIO" --dir "$directory" "$@"
tests/gate.sh-1123-}
tests/gate.sh-1124-
tests/gate.sh-1125-store_build(){
tests/gate.sh-1126-  local variant=${1:-} flags=${CXXFLAGS-'-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread'}
tests/gate.sh-1127-  # Match the three Makefile recipes, including the later -O1 override for TSan. Their former
--
tests/gate.sh-1348-row_begin "reject --spread"
tests/gate.sh-1349-reject_boot --spread 4:4   2>&1 | grep -q "unknown"  && ok "reject --spread"    || bad "reject --spread"
tests/gate.sh-1350-row_begin "reject --nodes"
tests/gate.sh-1351-reject_boot --nodes 2      2>&1 | grep -q "unknown"  && ok "reject --nodes"     || bad "reject --nodes"
tests/gate.sh-1352-row_begin "reject 3-part ratio"
tests/gate.sh:1353:reject_boot --ratio 4:4:2  2>&1 | grep -q "deleted"  && ok "reject 3-part ratio"|| bad "reject 3-part ratio"
tests/gate.sh-1354-row_begin "reject missing conf"
tests/gate.sh-1355-reject_boot /nonexistent-conf 2>&1 | grep -q "cannot open" && ok "reject missing conf" || bad "reject missing conf"
tests/gate.sh-1356-printf 'florb 1\n' > $TMPDIR/gate-bad.conf
tests/gate.sh-1357-row_begin "reject bad conf key"
tests/gate.sh-1358-reject_boot $TMPDIR/gate-bad.conf 2>&1 | grep -q "unknown argument" && ok "reject bad conf key" || bad "reject bad conf key"
--
tests/gate.sh-1428-    && ok "RYOW battery" || bad "RYOW battery" "see $TMPDIR/gate-ryow.txt"
tests/gate.sh-1429-row_begin "ACL category runtime table"
tests/gate.sh-1430-py tests/acl_categories.py 127.0.0.1 $PORT >$TMPDIR/gate-acl-categories.txt 2>&1 \
tests/gate.sh-1431-    && ok "ACL category runtime table" || bad "ACL category runtime table" "see $TMPDIR/gate-acl-categories.txt"
tests/gate.sh-1432-row_begin "ACL LOAD/SAVE no-file errors"
tests/gate.sh:1433:py tests/acl.py 127.0.0.1 $PORT - >$TMPDIR/gate-acl-nofile.txt 2>&1 \
tests/gate.sh-1434-    && ok "ACL LOAD/SAVE no-file errors" || bad "ACL LOAD/SAVE no-file errors" "see $TMPDIR/gate-acl-nofile.txt"
tests/gate.sh-1435-# Idle-loop ceiling: owner-written counters remove scheduler/jiffy noise and name a spinning
tests/gate.sh-1436-# thread. The helper requires two fresh LBSIGNALS captures and a sampling iteration, so a missing
tests/gate.sh-1437-# DEBUG surface or cached/empty dump cannot turn this row green.
tests/gate.sh-1438-row_begin "idle loop ceiling (LBSIGNALS, 1s)"
--
tests/gate.sh-1556-# ---- SORT's dynamic keys: exact production gate geometry, both atomic modes -------------------
tests/gate.sh-1557-# tests/sort.py rejects any boot other than 16 shards at 6:2, buckets candidate names with
tests/gate.sh-1558-# DEBUG SHARD, and requires concrete BY and GET keys plus STORE destination on the executor slot
tests/gate.sh-1559-# opposite the source. No same-owner or one-executor run can satisfy this row.
tests/gate.sh-1560-for AT in 0 1; do
tests/gate.sh:1561:  boot "$CANDIDATE_BINARY" --ratio 6:2 --atomic "$AT" --enable-debug-command yes \
tests/gate.sh-1562-      || bad "cross-owner SORT boot (atomic $AT)"
tests/gate.sh-1563-  row_begin "cross-owner SORT battery (atomic $AT)"
tests/gate.sh-1564-  py tests/sort.py 127.0.0.1 "$PORT" >$TMPDIR/gate-sort-$AT.txt 2>&1 \
tests/gate.sh-1565-      && ok "cross-owner SORT battery (atomic $AT)" \
tests/gate.sh-1566-      || bad "cross-owner SORT battery (atomic $AT)" "see $TMPDIR/gate-sort-$AT.txt"
--
tests/gate.sh-1698-stop
tests/gate.sh-1699-ACL_DIR=$(mktemp -d $TMPDIR/gate-acl.XXXXXX)
tests/gate.sh-1700-ACL_FILE="$ACL_DIR/users.acl"
tests/gate.sh-1701-: > "$ACL_FILE"
tests/gate.sh-1702-boot "$CANDIDATE_BINARY" --aclfile "$ACL_FILE" || bad "ACL purpose boot"
tests/gate.sh:1703:row_begin "ACL battery (atomic off)"
tests/gate.sh:1704:py tests/acl.py 127.0.0.1 $PORT "$ACL_FILE" >$TMPDIR/gate-acl.txt 2>&1 \
tests/gate.sh:1705:    && ok "ACL battery (atomic off)" || bad "ACL battery (atomic off)" "see $TMPDIR/gate-acl.txt"
tests/gate.sh-1706-stop
tests/gate.sh-1707-ACL_ATOMIC_FILE="$ACL_DIR/users-atomic.acl"
tests/gate.sh-1708-: > "$ACL_ATOMIC_FILE"
tests/gate.sh-1709-boot "$CANDIDATE_BINARY" --aclfile "$ACL_ATOMIC_FILE" --atomic 1 || bad "ACL atomic purpose boot"
tests/gate.sh:1710:row_begin "ACL battery (atomic on)"
tests/gate.sh:1711:py tests/acl.py 127.0.0.1 $PORT "$ACL_ATOMIC_FILE" >$TMPDIR/gate-acl-atomic.txt 2>&1 \
tests/gate.sh:1712:    && ok "ACL battery (atomic on)" || bad "ACL battery (atomic on)" "see $TMPDIR/gate-acl-atomic.txt"
tests/gate.sh-1713-stop
tests/gate.sh-1714-DEBUG_DIR=$(mktemp -d $TMPDIR/gate-debug.XXXXXX)
tests/gate.sh-1715-boot "$CANDIDATE_BINARY" --enable-debug-command local --dir "$DEBUG_DIR" --dbfilename reload.tomo \
tests/gate.sh-1716-    || bad "DEBUG purpose boot"
tests/gate.sh-1717-row_begin "DEBUG toggle/reload battery"
--
tests/gate.sh-1888-boot "$CANDIDATE_BINARY" --enable-debug-command yes || bad "flip battery reboot"
tests/gate.sh-1889-quiet_wait
tests/gate.sh-1890-row_begin "FLIP applies under saturated load"
tests/gate.sh-1891-(
tests/gate.sh-1892-  taskset -c "$LOAD_CORES" memtier_benchmark -s 127.0.0.1 -p $PORT --protocol=redis -t 8 -c 32 \
tests/gate.sh:1893:    --pipeline=16 --ratio=1:1 --key-pattern=R:R --key-minimum=1 --key-maximum=200000 -d 64 \
tests/gate.sh-1894-    --test-time=25 --distinct-client-seed --hide-histogram >/dev/null 2>&1 &
tests/gate.sh-1895-  MTPID=$!
tests/gate.sh-1896-  sleep 3
tests/gate.sh-1897-  SATOK=1
tests/gate.sh-1898-  TOTAL=$(redis-cli -p $PORT flip 2>/dev/null | paste - - | awk '/live_io/{a=$2} /live_ex/{b=$2} END{print a+b}')
--
tests/gate.sh-2213-  SRV=0; SRVLOG=/dev/null
tests/gate.sh-2214-  guard_port "$PORT"
tests/gate.sh-2215-  guard_port "$TLS_PORT"
tests/gate.sh-2216-  SRVLOG=$(mktemp $TMPDIR/gate-tls-srv.XXXXXX)
tests/gate.sh-2217-  taskset -c $CORES "$CANDIDATE_BINARY" --port "$PORT" --tls-port "$TLS_PORT" \
tests/gate.sh:2218:      --bind 127.0.0.1 --shards 16 --ratio "$GATE_RATIO" --protected-mode no --dir "$TLS_DIR" \
tests/gate.sh-2219-      --tls-cert-file "$TLS_DIR/server.crt" --tls-key-file "$TLS_DIR/server.key" \
tests/gate.sh-2220-      --tls-ca-cert-file "$TLS_DIR/ca.crt" --tls-auth-clients "$auth" "$@" \
tests/gate.sh-2221-      >"$SRVLOG" 2>&1 &
tests/gate.sh-2222-  SRV=$!
tests/gate.sh-2223-  for _ in $(seq 50); do
--
tests/gate.sh-2300-
tests/gate.sh-2301-job_feature_cell(){
tests/gate.sh-2302-  local FEATURE_CELL=${1#feature-cell-}
tests/gate.sh-2303-  row_begin "feature $FEATURE_CELL"
tests/gate.sh-2304-  py tests/feature_gate.py --cell "$FEATURE_CELL" --binary "$CANDIDATE_BINARY" \
tests/gate.sh:2305:        --server-cpus "$CORES" --load-cpus "${GATE_LOAD_CORES:-96-127}" --ratio "$GATE_RATIO" \
tests/gate.sh-2306-        --port "$PORT" --output "$FEATURE_OUTPUT" \
tests/gate.sh-2307-        >"$FEATURE_OUTPUT/$FEATURE_CELL.log" 2>&1 \
tests/gate.sh-2308-        && ok "feature $FEATURE_CELL" \
tests/gate.sh-2309-        || bad "feature $FEATURE_CELL" "see $FEATURE_OUTPUT/$FEATURE_CELL.log"
tests/gate.sh-2310-}
--
tests/gate.sh-2390-      echo "boot preflight: cores/port not quiet: $(tail -1 $TMPDIR/gate-quiet.err)"; return 1; }
tests/gate.sh-2391-  }
tests/gate.sh-2392-  SRV=0; SRVLOG=/dev/null
tests/gate.sh-2393-  guard_port "$PORT"
tests/gate.sh-2394-  SRVLOG=$(mktemp $TMPDIR/gate-srv-zc.XXXXXX)
tests/gate.sh:2395:  taskset -c $CORES "$1" --port $PORT --bind 127.0.0.1 --shards 16 --ratio $GATE_RATIO \
tests/gate.sh-2396-      --dir "$(mktemp -d "$TMPDIR/zc-data.XXXXXX")" --zc-min 16384 > "$SRVLOG" 2>&1 &
tests/gate.sh-2397-  SRV=$!
tests/gate.sh-2398-  for _ in $(seq 50); do
tests/gate.sh-2399-    if ! kill -0 "$SRV" 2>/dev/null; then wait "$SRV" 2>/dev/null; return 1; fi
tests/gate.sh-2400-    (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && return 0; sleep 0.2; done
--
tests/gate.sh-2622-for reserved_port in "${SLOT_PORTS[@]}"; do
tests/gate.sh-2623-  for reserved_offset in 0 1 2; do guard_port "$((reserved_port+reserved_offset))"; done
tests/gate.sh-2624-done
tests/gate.sh-2625-
tests/gate.sh-2626-# ---- 1. builds (the static_asserts on sizeof(Op)/sizeof(Client) gate here) -------------------
tests/gate.sh:2627:start_workers
tests/gate.sh-2628-collect_job release
tests/gate.sh-2629-
tests/gate.sh-2630-collect_job asan
tests/gate.sh-2631-collect_job config_unit
tests/gate.sh-2632-
--
tests/gate.sh-2720-
tests/gate.sh-2721-# ---- A. mandatory feature matrix (35 rows, BEFORE the quick-tier exit) -----------------------
tests/gate.sh-2722-# No inherited feature defaults: feature_gate.py sets --thread-mode {1s,2s}, --read-local {0,1},
tests/gate.sh-2723-# --overlap {0,1}, --reorder {0,1}, --flip-auto {0,1} in the full 32-way product, and explicitly
tests/gate.sh-2724-# sets both values of --atomic, --key-lb, --client-lb across it. The last three rows exercise
tests/gate.sh:2725:# --shards {-1,1,16,256}, --ratio, --place, --shard-home (including empty owners), and --no-pin.
tests/gate.sh-2726-# The eight fused + flip-auto=1 cells must refuse the exact documented unsupported combination;
tests/gate.sh-2727-# all other cells must boot and fire their mechanisms. These existing refusal checks remain
tests/gate.sh-2728-# mandatory: accepting the combination or refusing for another reason is a failure. The Python
tests/gate.sh-2729-# inventory assertion refuses a missing value/product entry. See GATES.md.
tests/gate.sh-2730-for FM in 1s 2s; do
--
tests/gate.sh-2915-    CPP="$CANDIDATE_BINARY"; KMAX=2000000
tests/gate.sh-2916-    run_cell(){ # name cores ratio shards pipe lg t conns ratio_rw
tests/gate.sh-2917-      nic_kill_srv $NIC_PORT || return 1
tests/gate.sh-2918-      # --protected-mode no: protected mode (vanilla-compat: no bind check) denies non-local
tests/gate.sh-2919-      # peers when no password is set — which is every NIC cell.
tests/gate.sh:2920:      NIC_SRV_CORES=$2 nic_boot "gate_$1" "$CPP" --port $NIC_PORT --bind $NIC_SRV_IP --ratio $3 --shards $4 --protected-mode no || return 1
tests/gate.sh:2921:      NIC_TO=1200 NIC_LG_CORES=$6 nic_memtier -t 16 -c 4 --pipeline=32 --ratio=1:0 --key-pattern=P:P \
tests/gate.sh-2922-          --key-minimum=1 --key-maximum=$KMAX -n allkeys -d 64 >/dev/null 2>&1
tests/gate.sh-2923-      local f=$BL_LOGDIR/g_$1.log
tests/gate.sh:2924:      NIC_TO=90 NIC_LG_CORES=$6 nic_memtier -t $7 -c $(( $8 / $7 )) --pipeline=$5 --ratio=$9 \
tests/gate.sh-2925-          --key-pattern=R:R --key-minimum=1 --key-maximum=$KMAX --test-time=15 -d 64 \
tests/gate.sh-2926-          --distinct-client-seed > "$f" 2>&1
tests/gate.sh-2927-      tr '\r' '\n' < "$f" | grep -E '^Totals' | tail -1 | awk '{print $2}'
tests/gate.sh-2928-    }
tests/gate.sh-2929-    RC=0

exec
/bin/bash -lc "sed -n '1140,1175p' /tmp/claude-1000/redis74/src/acl.c
sed -n '1300,1440p' /tmp/claude-1000/redis74/src/acl.c
sed -n '2010,2160p' /tmp/claude-1000/redis74/src/acl.c
taskset -c 112-127 python3 tests/acl.py --help" in /home/user/Projects/cx-deadconf-fix
 exited 1 in 0ms:
                return C_ERR;
            }

            /* We do not support allowing first-arg of a subcommand */
            if (cmd->parent) {
                zfree(copy);
                errno = ECHILD;
                return C_ERR;
            }

            /* The subcommand cannot be empty, so things like DEBUG|
             * are syntax errors of course. */
            if (strlen(sub) == 0) {
                zfree(copy);
                errno = EINVAL;
                return C_ERR;
            }

            if (cmd->subcommands_dict) {
                /* If user is trying to allow a valid subcommand we can just add its unique ID */
                cmd = ACLLookupCommand(op+1);
                if (cmd == NULL) {
                    zfree(copy);
                    errno = ENOENT;
                    return C_ERR;
                }
                ACLChangeSelectorPerm(selector,cmd,1);
            } else {
                /* If user is trying to use the ACL mech to block SELECT except SELECT 0 or
                 * block DEBUG except DEBUG OBJECT (DEBUG subcommands are not considered
                 * subcommands for now) we use the allowed_firstargs mechanism. */

                /* Add the first-arg to the list of valid ones. */
                serverLog(LL_WARNING, "Deprecation warning: Allowing a first arg of an otherwise "
                                      "blocked command is a misuse of ACL and may get disabled "
                                      "in the future (offender: +%s)", op+1);
        sds newpass;
        if (op[0] == '>') {
            newpass = ACLHashPassword((unsigned char*)op+1,oplen-1);
        } else {
            if (ACLCheckPasswordHash((unsigned char*)op+1,oplen-1) == C_ERR) {
                errno = EBADMSG;
                return C_ERR;
            }
            newpass = sdsnewlen(op+1,oplen-1);
        }

        listNode *ln = listSearchKey(u->passwords,newpass);
        /* Avoid re-adding the same password multiple times. */
        if (ln == NULL)
            listAddNodeTail(u->passwords,newpass);
        else
            sdsfree(newpass);
        u->flags &= ~USER_FLAG_NOPASS;
    } else if (op[0] == '<' || op[0] == '!') {
        sds delpass;
        if (op[0] == '<') {
            delpass = ACLHashPassword((unsigned char*)op+1,oplen-1);
        } else {
            if (ACLCheckPasswordHash((unsigned char*)op+1,oplen-1) == C_ERR) {
                errno = EBADMSG;
                return C_ERR;
            }
            delpass = sdsnewlen(op+1,oplen-1);
        }
        listNode *ln = listSearchKey(u->passwords,delpass);
        sdsfree(delpass);
        if (ln) {
            listDelNode(u->passwords,ln);
        } else {
            errno = ENODEV;
            return C_ERR;
        }
    } else if (op[0] == '(' && op[oplen - 1] == ')') {
        aclSelector *selector = aclCreateSelectorFromOpSet(op, oplen);
        if (!selector) {
            /* No errorno set, propagate it from interior error. */
            return C_ERR;
        }
        listAddNodeTail(u->selectors, selector);
        return C_OK;
    } else if (!strcasecmp(op,"clearselectors")) {
        listIter li;
        listNode *ln;
        listRewind(u->selectors,&li);
        /* There has to be a root selector */
        serverAssert(listNext(&li));
        while((ln = listNext(&li))) {
            listDelNode(u->selectors, ln);
        }
        return C_OK;
    } else if (!strcasecmp(op,"reset")) {
        serverAssert(ACLSetUser(u,"resetpass",-1) == C_OK);
        serverAssert(ACLSetUser(u,"resetkeys",-1) == C_OK);
        serverAssert(ACLSetUser(u,"resetchannels",-1) == C_OK);
        if (server.acl_pubsub_default & SELECTOR_FLAG_ALLCHANNELS)
            serverAssert(ACLSetUser(u,"allchannels",-1) == C_OK);
        serverAssert(ACLSetUser(u,"off",-1) == C_OK);
        serverAssert(ACLSetUser(u,"sanitize-payload",-1) == C_OK);
        serverAssert(ACLSetUser(u,"clearselectors",-1) == C_OK);
        serverAssert(ACLSetUser(u,"-@all",-1) == C_OK);
    } else {
        aclSelector *selector = ACLUserGetRootSelector(u);
        if (ACLSetSelector(selector, op, oplen) == C_ERR) {
            return C_ERR;
        }
    }
    return C_OK;
}

/* Return a description of the error that occurred in ACLSetUser() according to
 * the errno value set by the function on error. */
const char *ACLSetUserStringError(void) {
    const char *errmsg = "Wrong format";
    if (errno == ENOENT)
        errmsg = "Unknown command or category name in ACL";
    else if (errno == EINVAL)
        errmsg = "Syntax error";
    else if (errno == EEXIST)
        errmsg = "Adding a pattern after the * pattern (or the "
                 "'allkeys' flag) is not valid and does not have any "
                 "effect. Try 'resetkeys' to start with an empty "
                 "list of patterns";
    else if (errno == EISDIR)
        errmsg = "Adding a pattern after the * pattern (or the "
                 "'allchannels' flag) is not valid and does not have any "
                 "effect. Try 'resetchannels' to start with an empty "
                 "list of channels";
    else if (errno == ENODEV)
        errmsg = "The password you are trying to remove from the user does "
                 "not exist";
    else if (errno == EBADMSG)
        errmsg = "The password hash must be exactly 64 characters and contain "
                 "only lowercase hexadecimal characters";
    else if (errno == EALREADY)
        errmsg = "Duplicate user found. A user can only be defined once in "
                 "config files";
    else if (errno == ECHILD)
        errmsg = "Allowing first-arg of a subcommand is not supported";
    return errmsg;
}

/* Create the default user, this has special permissions. */
user *ACLCreateDefaultUser(void) {
    user *new = ACLCreateUser("default",7);
    ACLSetUser(new,"+@all",-1);
    ACLSetUser(new,"~*",-1);
    ACLSetUser(new,"&*",-1);
    ACLSetUser(new,"on",-1);
    ACLSetUser(new,"nopass",-1);
    return new;
}

/* Initialization of the ACL subsystem. */
void ACLInit(void) {
    Users = raxNew();
    UsersToLoad = listCreate();
    ACLInitCommandCategories();
    listSetMatchMethod(UsersToLoad, ACLListMatchLoadedUser);
    ACLLog = listCreate();
    DefaultUser = ACLCreateDefaultUser();
}

/* Check the username and password pair and return C_OK if they are valid,
 * otherwise C_ERR is returned and errno is set to:
 *
 *  EINVAL: if the username-password do not match.
 *  ENOENT: if the specified user does not exist at all.
 */
int ACLCheckUserCredentials(robj *username, robj *password) {
    user *u = ACLGetUserByName(username->ptr,sdslen(username->ptr));
    if (u == NULL) {
        errno = ENOENT;
        return C_ERR;
    }

    /* Disabled users can't login. */
            deauthenticateAndCloseClient(c);
    }

    listRelease(channels);
}

/* =============================================================================
 * ACL loading / saving functions
 * ==========================================================================*/


/* Selector definitions should be sent as a single argument, however
 * we will be lenient and try to find selector definitions spread 
 * across multiple arguments since it makes for a simpler user experience
 * for ACL SETUSER as well as when loading from conf files. 
 * 
 * This function takes in an array of ACL operators, excluding the username,
 * and merges selector operations that are spread across multiple arguments. The return
 * value is a new SDS array, with length set to the passed in merged_argc. Arguments 
 * that are untouched are still duplicated. If there is an unmatched parenthesis, NULL 
 * is returned and invalid_idx is set to the argument with the start of the opening
 * parenthesis. */
sds *ACLMergeSelectorArguments(sds *argv, int argc, int *merged_argc, int *invalid_idx) {
    *merged_argc = 0;
    int open_bracket_start = -1;

    sds *acl_args = (sds *) zmalloc(sizeof(sds) * argc);

    sds selector = NULL;
    for (int j = 0; j < argc; j++) {
        char *op = argv[j];

        if (open_bracket_start == -1 &&
            (op[0] == '(' && op[sdslen(op) - 1] != ')')) {
            selector = sdsdup(argv[j]);
            open_bracket_start = j;
            continue;
        }

        if (open_bracket_start != -1) {
            selector = sdscatfmt(selector, " %s", op);
            if (op[sdslen(op) - 1] == ')') {
                open_bracket_start = -1;
                acl_args[*merged_argc] = selector;                        
                (*merged_argc)++;
            }
            continue;
        }

        acl_args[*merged_argc] = sdsdup(argv[j]);
        (*merged_argc)++;
    }

    if (open_bracket_start != -1) {
        for (int i = 0; i < *merged_argc; i++) sdsfree(acl_args[i]);
        zfree(acl_args);
        sdsfree(selector);
        if (invalid_idx) *invalid_idx = open_bracket_start;
        return NULL;
    }

    return acl_args;
}

/* takes an acl string already split on spaces and adds it to the given user
 * if the user object is NULL, will create a user with the given username
 *
 * Returns an error as an sds string if the ACL string is not parsable
 */
sds ACLStringSetUser(user *u, sds username, sds *argv, int argc) {
    serverAssert(u != NULL || username != NULL);

    sds error = NULL;

    int merged_argc = 0, invalid_idx = 0;
    sds *acl_args = ACLMergeSelectorArguments(argv, argc, &merged_argc, &invalid_idx);

    if (!acl_args) {
        return sdscatfmt(sdsempty(),
                         "Unmatched parenthesis in acl selector starting "
                         "at '%s'.", (char *) argv[invalid_idx]);
    }

    /* Create a temporary user to validate and stage all changes against
     * before applying to an existing user or creating a new user. If all
     * arguments are valid the user parameters will all be applied together.
     * If there are any errors then none of the changes will be applied. */
    user *tempu = ACLCreateUnlinkedUser();
    if (u) {
        ACLCopyUser(tempu, u);
    }

    for (int j = 0; j < merged_argc; j++) {
        if (ACLSetUser(tempu,acl_args[j],(ssize_t) sdslen(acl_args[j])) != C_OK) {
            const char *errmsg = ACLSetUserStringError();
            error = sdscatfmt(sdsempty(),
                              "Error in ACL SETUSER modifier '%s': %s",
                              (char*)acl_args[j], errmsg);
            goto cleanup;
        }
    }

    /* Existing pub/sub clients authenticated with the user may need to be
     * disconnected if (some of) their channel permissions were revoked. */
    if (u) {
        ACLKillPubsubClientsIfNeeded(tempu, u);
    }

    /* Overwrite the user with the temporary user we modified above. */
    if (!u) {
        u = ACLCreateUser(username,sdslen(username));
    }
    serverAssert(u != NULL);

    ACLCopyUser(u, tempu);

cleanup:
    ACLFreeUser(tempu);
    for (int i = 0; i < merged_argc; i++) {
        sdsfree(acl_args[i]);
    }
    zfree(acl_args);

    return error;
}

/* Given an argument vector describing a user in the form:
 *
 *      user <username> ... ACL rules and flags ...
 *
 * this function validates, and if the syntax is valid, appends
 * the user definition to a list for later loading.
 *
 * The rules are tested for validity and if there obvious syntax errors
 * the function returns C_ERR and does nothing, otherwise C_OK is returned
 * and the user is appended to the list.
 *
 * Note that this function cannot stop in case of commands that are not found
 * and, in that case, the error will be emitted later, because certain
 * commands may be defined later once modules are loaded.
 *
 * When an error is detected and C_ERR is returned, the function populates
 * by reference (if not set to NULL) the argc_err argument with the index
 * of the argv vector that caused the error. */
int ACLAppendUserForLoading(sds *argv, int argc, int *argc_err) {
    if (argc < 2 || strcasecmp(argv[0],"user")) {
        if (argc_err) *argc_err = 0;
        return C_ERR;
    }

    if (listSearchKey(UsersToLoad, argv[1])) {
Traceback (most recent call last):
  File "/home/user/Projects/cx-deadconf-fix/tests/acl.py", line 16, in <module>
    HOST, PORT, ACLFILE = sys.argv[1], int(sys.argv[2]), sys.argv[3]
                                           ~~~~~~~~^^^
IndexError: list index out of range

exec
/bin/bash -lc "sed -n '322,397p' src/cmd/acl.inc
rg -n -C 3 'selector|Syntax error' tests/aclsel.py
rg -n -C 3 'selectors|selector' tests/netcmd_unit.cc
sed -n '1,150p' Makefile" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
        return false;
    } else if (!acl_apply_permission_rule(image.perm, rule, error)) {
        return false;
    }
    return true;
}

bool acl_apply_rules(AclUserImage& image, const std::vector<std::string>& rules,
                     size_t begin, std::string& error, std::string* failed = nullptr) {
    for (size_t i = begin; i < rules.size(); i++) {
        if (!rules[i].empty() && rules[i][0] == '(') {
            error = "ACL selectors are not supported";
            if (failed) *failed = rules[i];
            return false;
        }
        const Slice rule(rules[i].data(), static_cast<uint32_t>(rules[i].size()));
        if (!acl_apply_rule(image, rule, error)) {
            if (failed) *failed = rules[i];
            return false;
        }
    }
    return true;
}

void acl_verify_command_description(const AclSelector& perm) {
    AclSelector predicted;
    acl_reset_commands(predicted, acl_future_commands(perm));
    for (const std::string& rule : perm.command_rules) {
        std::string error;
        if (!acl_apply_command_rule(predicted,
                Slice(rule.data(), static_cast<uint32_t>(rule.size())), error, false)) std::abort();
    }
    if (std::memcmp(predicted.allowed_commands, perm.allowed_commands,
                    sizeof(perm.allowed_commands))) std::abort();
}

std::string acl_describe_commands(const AclSelector& perm) {
    acl_verify_command_description(perm);
    std::string result = acl_future_commands(perm) ? "+@all" : "-@all";
    for (const std::string& rule : perm.command_rules) {
        result.push_back(' ');
        result += rule;
    }
    return result;
}

std::string acl_join_patterns(const AclSelector& perm, bool channel) {
    std::string result;
    if (channel) {
        if (perm.flags & AclAllChannels) return "&*";
        result = "resetchannels";
        for (const std::string& pattern : perm.channel_patterns) {
            result += " &";
            result += pattern;
        }
    } else {
        if (perm.flags & AclAllKeys) return "~*";
        for (const std::string& pattern : perm.key_patterns) {
            if (!result.empty()) result.push_back(' ');
            result.push_back('~');
            result += pattern;
        }
    }
    return result;
}

std::string acl_getuser_channels(const AclSelector& perm) {
    if (perm.flags & AclAllChannels) return "&*";
    std::string result;
    for (const std::string& pattern : perm.channel_patterns) {
        if (!result.empty()) result.push_back(' ');
        result.push_back('&');
        result += pattern;
    }
    return result;
}
1-#!/usr/bin/env python3
2:"""TomoKV selector rejection and Redis 7.4 selector enforcement battery.
3-
4-Usage: tests/aclsel.py HOST PORT
5-"""
--
85-    return {reply[index]: reply[index + 1] for index in range(0, len(reply), 2)}
86-
87-
88:def selector_fields(reply):
89-    result = []
90:    for selector in reply:
91:        if not isinstance(selector, list) or len(selector) != 6:
92:            raise AssertionError("selector shape: %r" % (selector,))
93:        result.append({selector[index]: selector[index + 1]
94:                       for index in range(0, len(selector), 2)})
95-    return result
96-
97-
--
118-                return
119-        except (ConnectionError, OSError):
120-            return
121:    raise AssertionError("selector channel revocation did not close subscriber")
122-
123-
124-admin = Conn()
--
136-                      ("(",), ("(+@all (~*))",)):
137-            for name in ("aclsel", "aclsel-bad"):
138-                reply = admin.command("ACL", "SETUSER", name, "reset", "on", "nopass", *rules)
139:                if not isinstance(reply, RespError) or "ACL selectors are not supported" not in str(reply):
140:                    raise AssertionError("selector was not explicitly rejected: %r -> %r" % (rules, reply))
141-                expect(admin.command("ACL", "GETUSER", "aclsel"), original,
142:                       "rejected selector preserves root permissions")
143-                expect(admin.command("ACL", "GETUSER", "aclsel-bad"), None,
144:                       "rejected selector creates no user")
145:        expect(fields(original)[b"selectors"], [], "root user has no stored selectors")
146-    finally:
147-        admin.command("ACL", "DELUSER", *names)
148-        admin.close()
149:    print("aclsel: PASS (%d checks; selector rejection and unchanged root permissions)" % CHECKS)
150-    sys.exit(0)
151-for username in ("aclsel", "aclsel-bad", "aclsel-default"):
152-    admin.command("ACL", "DELUSER", username)
153-before = stats(admin)
154-
155-expect(admin.command("CONFIG", "SET", "acl-pubsub-default", "allchannels"), b"OK",
156:       "arm selector channel default")
157-expect(admin.command("ACL", "SETUSER", "aclsel-default", "reset", "on", "nopass", "()"),
158:       b"OK", "empty selector with allchannels default")
159:default_selector = selector_fields(
160:    fields(admin.command("ACL", "GETUSER", "aclsel-default"))[b"selectors"])
161:expect(default_selector[0][b"channels"], b"&*", "selector inherits allchannels default")
162-expect(admin.command("ACL", "DELUSER", "aclsel-default"), 1,
163:       "remove selector-default probe")
164-expect(admin.command("CONFIG", "SET", "acl-pubsub-default", "resetchannels"), b"OK",
165:       "restore selector channel default")
166-
167-for key, value in (("sel:a:1", "A"), ("sel:b:1", "B"), ("sel:root:1", "R"),
168-                   ("sel:cat:1", "CAT")):
169-    expect(admin.command("SET", key, value), b"OK", "seed " + key)
170-
171:# One packed selector and one fragmented across RESP arguments prove both parser paths fired.
172-rules = (
173-    "reset", "on", "nopass", "-@all", "resetkeys", "resetchannels",
174-    "(~sel:a:* +get +strlen +mget)",
--
176-    "(&sel:news:* +publish)",
177-    "(&sel:sub:* +subscribe +unsubscribe)",
178-)
179:expect(admin.command("ACL", "SETUSER", "aclsel", *rules), b"OK", "selector grammar")
180-
181-info = fields(admin.command("ACL", "GETUSER", "aclsel"))
182:selectors = selector_fields(info[b"selectors"])
183:expect(selectors, [
184-    {b"commands": b"-@all +get +strlen +mget", b"keys": b"~sel:a:*", b"channels": b""},
185-    {b"commands": b"-@all +set", b"keys": b"~sel:b:*", b"channels": b""},
186-    {b"commands": b"-@all +publish", b"keys": b"", b"channels": b"&sel:news:*"},
187-    {b"commands": b"-@all +subscribe +unsubscribe", b"keys": b"",
188-     b"channels": b"&sel:sub:*"},
189:], "GETUSER selector rows")
190-expected_list = (
191-    b"user aclsel on nopass sanitize-payload resetchannels -@all "
192-    b"(~sel:a:* resetchannels -@all +get +strlen +mget) "
--
195-    b"(resetchannels &sel:sub:* -@all +subscribe +unsubscribe)"
196-)
197-listed = next(row for row in admin.command("ACL", "LIST") if row.startswith(b"user aclsel "))
198:expect(listed, expected_list, "ACL LIST selector serialization")
199-
200-expect(admin.command("ACL", "SETUSER", "aclsel-bad", "reset", "(on +get)"),
201:       "ERR Error in ACL SETUSER modifier '(on +get)': Syntax error",
202:       "selector rejects user flags")
203-expect(admin.command("ACL", "GETUSER", "aclsel-bad"), None,
204:       "invalid selector is all-or-nothing")
205-expect(admin.command("ACL", "SETUSER", "aclsel-bad", "reset", "(~x:*", "+get"),
206:       "ERR Unmatched parenthesis in acl selector starting at '(~x:*'.",
207:       "unmatched selector error")
208-expect(admin.command("ACL", "SETUSER", "aclsel-bad", "reset", "(~x:* +eval)"),
209:       ("ERR Error in ACL SETUSER modifier '(~x:* +eval)': Script commands in ACL selectors "
210-        "require allcommands") if is_tomokv else b"OK",
211:       "unsafe script selector fail-closed policy")
212-
213-user = Conn()
214:expect(user.command("AUTH", "aclsel", "unused"), b"OK", "selector user AUTH")
215-
216-# Selector grants, negative controls, and denial-reason precedence.
217:expect(user.command("GET", "sel:a:1"), b"A", "selector GET grant")
218:expect(user.command("SET", "sel:b:2", "B2"), b"OK", "selector SET grant")
219-expect(user.command("GET", "sel:b:1"), "NOPERM No permissions to access a key",
220-       "GET command exists but no complete set matches key")
221-expect(user.command("SET", "sel:a:2", "A2"), "NOPERM No permissions to access a key",
222-       "SET command exists but no complete set matches key")
223-expect(user.command("DEL", "sel:a:1"),
224-       "NOPERM User aclsel has no permissions to run the 'del' command",
225:       "selector command denial")
226:expect(user.command("MGET", "sel:a:1"), [b"A"], "selector MGET grant")
227-expect(user.command("MGET", "sel:a:1", "sel:b:1"),
228:       "NOPERM No permissions to access a key", "selector MGET key denial")
229:expect(user.command("PUBLISH", "sel:news:x", "payload"), 0, "selector channel grant")
230-expect(user.command("PUBLISH", "sel:other", "payload"),
231:       "NOPERM No permissions to access a channel", "selector channel denial")
232-
233:# Root and selectors are alternatives, never bags of independently composable permissions.
234-expect(admin.command("ACL", "SETUSER", "aclsel", "~sel:root:*", "+get", "allchannels"),
235-       b"OK", "add root permission set")
236-expect(user.command("GET", "sel:root:1"), b"R", "root permission grant")
237:expect(user.command("GET", "sel:a:1"), b"A", "selector remains an alternative")
238-expect(user.command("PUBLISH", "sel:other", "payload"),
239:       "NOPERM No permissions to access a channel", "root channel cannot mix with selector command")
240-expect(admin.command("ACL", "SETUSER", "aclsel", "(~sel:b:* +mget)"), b"OK",
241:       "add second MGET selector")
242:expect(user.command("MGET", "sel:b:1"), [b"B"], "second selector MGET grant")
243-expect(user.command("MGET", "sel:a:1", "sel:b:1"),
244:       "NOPERM No permissions to access a key", "multi-key request cannot mix selectors")
245-
246:# Command categories and exclusions apply inside a selector exactly as in the root set.
247:expect(admin.command("ACL", "SETUSER", "aclsel", "clearselectors",
248:                     "(~sel:cat:* +@string -set)"), b"OK", "selector command category")
249:expect(user.command("GET", "sel:cat:1"), b"CAT", "selector category GET")
250:expect(user.command("STRLEN", "sel:cat:1"), 3, "selector category STRLEN")
251-expect(user.command("SET", "sel:cat:2", "x"),
252-       "NOPERM User aclsel has no permissions to run the 'set' command",
253:       "selector category exclusion")
254-expect(user.command("GET", "sel:a:1"), "NOPERM No permissions to access a key",
255:       "root command and selector key cannot mix")
256-
257:# EXEC rechecks the current immutable selector image, rather than the queued image.
258-expect(admin.command("ACL", "SETUSER", "aclsel", "reset", "on", "nopass", "~*",
259-                     "resetchannels", "-@all", "+multi", "+exec",
260:                     "(~sel:a:* +get)"), b"OK", "transaction selector setup")
261:expect(user.command("MULTI"), b"OK", "selector transaction MULTI")
262:expect(user.command("GET", "sel:a:1"), b"QUEUED", "selector transaction queue")
263:expect(admin.command("ACL", "SETUSER", "aclsel", "clearselectors"), b"OK",
264:       "revoke queued selector")
265-exec_reply = user.command("EXEC")
266-if not isinstance(exec_reply, list) or len(exec_reply) != 1:
267:    raise AssertionError("selector EXEC reply shape: %r" % (exec_reply,))
268-expect(exec_reply[0],
269-       "NOPERM ACLs rules changed between the moment the transaction was accumulated and the EXEC "
270-       "call. This command is no longer allowed for the following reason: no permission to execute "
271-       "the command or subcommand",
272:       "selector EXEC recheck")
273-
274:# Blocking completion also rechecks selectors after wakeup.
275-expect(admin.command("ACL", "SETUSER", "aclsel", "reset", "on", "nopass", "~*",
276-                     "resetchannels", "-@all", "(~sel:block:* +blpop)"), b"OK",
277:       "blocking selector setup")
278-admin.command("DEL", "sel:block:k")
279-expect(admin.command("EXISTS", "sel:block:k"), 0, "blocking key clean slate")
280-blocked = Conn()
281:expect(blocked.command("AUTH", "aclsel", "unused"), b"OK", "blocking selector AUTH")
282-blocking_reply = []
283-thread = threading.Thread(target=lambda: blocking_reply.append(
284-    blocked.command("BLPOP", "sel:block:k", 0)))
285-thread.start()
286-time.sleep(0.25)
287:expect(admin.command("ACL", "SETUSER", "aclsel", "clearselectors",
288:                     "(~sel:other:* +blpop)"), b"OK", "revoke blocking selector key")
289:expect(admin.command("LPUSH", "sel:block:k", "value"), 1, "wake selector BLPOP")
290-thread.join(5)
291-if not blocking_reply:
292:    raise AssertionError("selector BLPOP did not finish")
293:expect(blocking_reply[0], "NOPERM No permissions to access a key", "selector blocking recheck")
294-
295:# A selector-backed subscription survives unrelated root edits, then closes on selector removal.
296-expect(admin.command("ACL", "SETUSER", "aclsel", "reset", "on", "nopass",
297-                     "resetkeys", "-@all", "resetchannels",
298-                     "(&sel:sub:* +subscribe +unsubscribe)"), b"OK",
299:       "subscription selector setup")
300-subscriber = Conn()
301:expect(subscriber.command("AUTH", "aclsel", "unused"), b"OK", "subscriber selector AUTH")
302-expect(subscriber.command("SUBSCRIBE", "sel:sub:x"),
303:       [b"subscribe", b"sel:sub:x", 1], "selector SUBSCRIBE grant")
304-ordinary = Conn()
305-expect(ordinary.command("AUTH", "aclsel", "unused"), b"OK", "ordinary control AUTH")
306-killed_before = stats(admin).get(b"acl_pubsub_clients_killed")
307-expect(admin.command("ACL", "SETUSER", "aclsel", "~sel:root:*", "+get"), b"OK",
308:       "unrelated root update preserves selector")
309-expect(admin.command("PUBLISH", "sel:sub:x", "still-open"), 1,
310-       "preserved subscriber receiver count")
311-expect(subscriber.read(), [b"message", b"sel:sub:x", b"still-open"],
312:       "preserved selector subscriber delivery")
313-if is_tomokv:
314-    expect(stats(admin)[b"acl_pubsub_clients_killed"], killed_before,
315-           "preservation control kills zero subscribers")
316:expect(admin.command("ACL", "SETUSER", "aclsel", "clearselectors"), b"OK",
317:       "clear subscription selector")
318-wait_closed(subscriber)
319-if is_tomokv:
320-    expect(stats(admin)[b"acl_pubsub_clients_killed"], killed_before + 1,
321:           "selector revocation kills exactly one subscriber")
322-expect(ordinary.command("GET", "sel:root:1"), b"R",
323:       "selector revocation leaves ordinary connection open")
324-
325:# RESET and CLEARSELECTORS affect selectors without leaking into the root permission set.
326-expect(admin.command("ACL", "SETUSER", "aclsel", "(~sel:a:* +get)"), b"OK",
327:       "re-add selector before reset")
328-expect(admin.command("ACL", "SETUSER", "aclsel", "reset"), b"OK", "reset user")
329:expect(fields(admin.command("ACL", "GETUSER", "aclsel"))[b"selectors"], [],
330:       "reset clears selectors")
331-
332-after = stats(admin)
333-minimum_deltas = {
--
340-for counter, minimum in minimum_deltas.items():
341-    delta = after.get(counter, 0) - before.get(counter, 0)
342-    if delta < minimum:
343:        raise AssertionError("selector mechanism did not fire: %s delta=%d wanted>=%d" %
344-                             (counter.decode(), delta, minimum))
345-
346-admin.command("ACL", "DELUSER", "aclsel", "aclsel-bad", "aclsel-default")
347-for connection in (blocked, ordinary, user, admin):
348-    connection.close()
349:print("aclsel: PASS (%d checks; parsing/reporting/root+selector/key/channel/command/EXEC/BLPOP/revocation fired)" % CHECKS)
304-
305-    static void config() {
306-        test_config_bounds();
307:        acl_selectors();
308-        tracking_eviction();
309-        zero_copy("zc-all");
310-        Server server;
--
319-        std::filesystem::remove_all(directory);
320-    }
321-
322:    static void acl_selectors() {
323:        const std::vector<std::vector<std::string>> selectors = {
324-            {"()"}, {"(+get ~safe:*)"}, {"(", "+get", "~safe:*", ")"}, {"("}, {"(+@all (~*))"}
325-        };
326-        char directory[] = "build/deadconf-acl-XXXXXX";
--
351-        check(request({"ACL", "SETUSER", "acl-root", "on", "nopass", "~safe:*", "+get"}) == "+OK\r\n",
352-              "root ACL rules remain accepted");
353-        const auto before = request({"ACL", "GETUSER", "acl-root"});
354:        for (const auto& rules : selectors) {
355-            for (const char* name : {"acl-root", "acl-new"}) {
356-                std::vector<std::string> values = {"ACL", "SETUSER", name, "reset", "on", "nopass"};
357-                values.insert(values.end(), rules.begin(), rules.end());
358-                const auto reply = request(values);
359:                check(reply.starts_with("-ERR ") && reply.find("ACL selectors are not supported") != std::string::npos,
360:                      "ACL SETUSER rejects packed, split, empty and malformed selectors");
361:                check(request({"ACL", "GETUSER", "acl-root"}) == before, "failed selector leaves existing ACL intact");
362:                check(request({"ACL", "GETUSER", "acl-new"}) == "$-1\r\n", "failed selector creates no user");
363-            }
364-            write_file(rules);
365-            const auto reply = request({"ACL", "LOAD"});
366:            check(reply.starts_with("-") && reply.find("ACL selectors are not supported") != std::string::npos &&
367-                  reply.ends_with("no change to the previously active ACL rules was performed\r\n"),
368:                  "ACL LOAD rejects selectors");
369-            check(request({"ACL", "GETUSER", "acl-root"}) == before, "rejected ACL LOAD leaves live users intact");
370-        }
371-        acl_shutdown();
372:        for (const auto& rules : selectors) {
373-            Config boot;
374-            boot.acl_users = {{"acl-boot", "on", "nopass"}};
375-            boot.acl_users.front().insert(boot.acl_users.front().end(), rules.begin(), rules.end());
376-            error.clear();
377:            check(!acl_initialize(server, boot, error) && error.find("ACL selectors are not supported") != std::string::npos,
378:                  "inline boot ACL rejects selectors before startup");
379-            acl_shutdown();
380-            write_file(rules);
381-            error.clear();
382:            check(!acl_initialize(server, cfg, error) && error.find("ACL selectors are not supported") != std::string::npos,
383:                  "boot ACL file rejects selectors before startup");
384-            acl_shutdown();
385-        }
386-        std::filesystem::remove_all(directory);
--
584-    else if (mode == "collection-oom") R::collection_oom();
585-    else if (mode == "config") R::config();
586-    else if (mode == "config-bounds") test_config_bounds(argc == 3 ? argv[2] : nullptr);
587:    else if (mode == "acl-selectors") R::acl_selectors();
588-    else if (mode == "tracking-eviction") R::tracking_eviction();
589-    else if (mode.starts_with("zc-")) R::zero_copy(mode);
590-    else check(false, "unknown regression section");
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

exec
/bin/bash -lc "sed -n '300,375p' tests/gate.sh
sed -n '1680,1716p' tests/gate.sh
sed -n '280,620p' tests/acl.py
rg -n 'thread-mode|ratio|pin|affinity|atomic|aclfile' src/main.cc | head -70
rg -n '"'^release|''^all:|''^build/|LTO|''^CXX|''^LD|''^BIN|''^OBJ|acl.inc'"' Makefile
ls -l build/tomokv* build/*netcmd* 2>/dev/null
git diff --stat && git status --short" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
  if { read -r state < "/proc/$ROW_WATCHDOG/stat"; } 2>/dev/null; then
    state=${state##*) }; read -ra fields <<< "$state"
    if [ "${fields[1]}" != "${ROW_WATCH_PARENT:-0}" ] ||
        [ "${fields[19]}" != "${ROW_WATCHDOG_START:-0}" ] ||
        [ "$BASHPID" != "${ROW_WATCH_PARENT:-0}" ]; then
      ROW_WATCH_STATE=mismatch
    else ROW_WATCH_STATE=${fields[0]}
    fi
  fi
}
row_watch_clock(){
  local uptime idle whole fraction
  read -r uptime idle < /proc/uptime || return 1
  whole=${uptime%.*}; fraction=${uptime#*.}00
  ROW_WATCH_CLOCK=$((10#$whole*100+10#${fraction:0:2}))
}
row_watch_receipt(){
  local line expected lines=()
  [ -f "${ROW_WATCH_RECEIPT:-}" ] || return 1
  mapfile -t lines < "$ROW_WATCH_RECEIPT"
  [ "${#lines[@]}" = 1 ] || return 1
  IFS= read -r line < "$ROW_WATCH_RECEIPT" || return 1
  printf -v expected 'CANCELLED\t%s\t%s\t%s\t%s\t%s' "$ROW_WATCH_PARENT" "$ROW_WATCH_PARENT_START" \
      "$ROW_WATCHDOG" "$ROW_WATCHDOG_START" "$ROW_WATCH_GENERATION"
  [ "$line" = "$expected" ]
}
row_unwatch(){
  local watcher_rc=0 until expired=0 forced=0 can_wait=1
  if [ "$ROW_WATCHDOG" -gt 0 ]; then
    # Captured 2026-09-10: TERM in Bash's fork/exec transition was lost, leaving three
    # Python watchers sleeping for 900s while their parents waited forever. An EXIT-owner
    # guard prevents false publication but cannot make that first signal reliable.
    # Publish a generation-specific request before TERM; a child that starts afterwards
    # acknowledges it. Pause/rearm generations never share cancellation evidence.
    row_watch_probe
    if [ "$ROW_WATCH_STATE" != gone ] && [ "$ROW_WATCH_STATE" != Z ] &&
        [ "$ROW_WATCH_STATE" != mismatch ] && [ ! -f "$ROW_MARKER" ]; then
      if ! { printf 'CANCEL\t%s\t%s\t%s\t%s\t%s\n' "$ROW_WATCH_PARENT" "$ROW_WATCH_PARENT_START" \
          "$ROW_WATCHDOG" "$ROW_WATCHDOG_START" "$ROW_WATCH_GENERATION" > "$ROW_WATCH_CANCEL.tmp" &&
          mv "$ROW_WATCH_CANCEL.tmp" "$ROW_WATCH_CANCEL"; }; then ROW_MONITOR_FAILED=1; fi
      kill -TERM "$ROW_WATCHDOG" 2>/dev/null || :
    fi
    row_watch_clock || { ROW_MONITOR_FAILED=1; return 1; }
    until=$((ROW_WATCH_CLOCK+500)) # Match watch()'s existing five-second cleanup grace.
    while :; do
      row_watch_probe
      case "$ROW_WATCH_STATE" in
        gone|Z) break;;
        mismatch)
          ROW_MONITOR_FAILED=1; can_wait=0
          say "$ROW_ID" 'FAIL (row watchdog PID/start or direct-parent identity changed)'
          break;;
      esac
      row_watch_clock || { ROW_MONITOR_FAILED=1; can_wait=0; break; }
      if [ -f "$ROW_MARKER" ] && [ "$expired" = 0 ]; then
        # Expiry owns descendant reclamation. Allow its full five seconds plus one
        # second for marker publication/scheduling; never TERM/KILL it immediately.
        expired=1; until=$((ROW_WATCH_CLOCK+600))
      fi
      if [ "$ROW_WATCH_CLOCK" -ge "$until" ]; then
        forced=1; ROW_MONITOR_FAILED=1
        say "$ROW_ID" 'FAIL (row watchdog cancellation/expiry cleanup exceeded its bounded grace)'
        # This exceptional path pays for a pidfd helper so PID reuse across inspection
        # and SIGKILL cannot touch another process. Forced cleanup can never turn green.
        python3 tests/gate_history.py signal-child --pid "$ROW_WATCHDOG" --start "$ROW_WATCHDOG_START" \
            --parent "$ROW_WATCH_PARENT" --parent-start "$ROW_WATCH_PARENT_START" || :
        row_watch_clock || { can_wait=0; break; }
        until=$((ROW_WATCH_CLOCK+100))
        while :; do
          row_watch_probe
          case "$ROW_WATCH_STATE" in gone|Z) break;; mismatch) can_wait=0; break;; esac
          row_watch_clock || { can_wait=0; break; }
          [ "$ROW_WATCH_CLOCK" -lt "$until" ] || { can_wait=0; break; }
          sleep .01
        done
        break
row_begin "DUMP/RESTORE restart shutdown invariants"
shutdown_clean \
    && ok "DUMP/RESTORE restart shutdown invariants" \
    || bad "DUMP/RESTORE restart shutdown invariants"
}

job_auth(){
# ---- auth + audit DEBUG (purpose-booted; each test asserts its gate actually opened) -----------
row_begin "reject bad protected-mode"
reject_boot --protected-mode maybe 2>&1 | grep -q "protected-mode wants" \
    && ok "reject bad protected-mode" || bad "reject bad protected-mode"
row_begin "reject bad enable-debug-command"
reject_boot --enable-debug-command maybe 2>&1 | grep -q "enable-debug-command wants" \
    && ok "reject bad enable-debug-command" || bad "reject bad enable-debug-command"
boot "$CANDIDATE_BINARY" --requirepass gatepass || bad "auth purpose boot"
row_begin "AUTH/HELLO/protected state machine"
py tests/auth.py 127.0.0.1 $PORT gatepass >$TMPDIR/gate-auth.txt 2>&1 \
    && ok "AUTH/HELLO/protected state machine" || bad "AUTH/HELLO/protected state machine" "see $TMPDIR/gate-auth.txt"
stop
ACL_DIR=$(mktemp -d $TMPDIR/gate-acl.XXXXXX)
ACL_FILE="$ACL_DIR/users.acl"
: > "$ACL_FILE"
boot "$CANDIDATE_BINARY" --aclfile "$ACL_FILE" || bad "ACL purpose boot"
row_begin "ACL battery (atomic off)"
py tests/acl.py 127.0.0.1 $PORT "$ACL_FILE" >$TMPDIR/gate-acl.txt 2>&1 \
    && ok "ACL battery (atomic off)" || bad "ACL battery (atomic off)" "see $TMPDIR/gate-acl.txt"
stop
ACL_ATOMIC_FILE="$ACL_DIR/users-atomic.acl"
: > "$ACL_ATOMIC_FILE"
boot "$CANDIDATE_BINARY" --aclfile "$ACL_ATOMIC_FILE" --atomic 1 || bad "ACL atomic purpose boot"
row_begin "ACL battery (atomic on)"
py tests/acl.py 127.0.0.1 $PORT "$ACL_ATOMIC_FILE" >$TMPDIR/gate-acl-atomic.txt 2>&1 \
    && ok "ACL battery (atomic on)" || bad "ACL battery (atomic on)" "see $TMPDIR/gate-acl-atomic.txt"
stop
DEBUG_DIR=$(mktemp -d $TMPDIR/gate-debug.XXXXXX)
boot "$CANDIDATE_BINARY" --enable-debug-command local --dir "$DEBUG_DIR" --dbfilename reload.tomo \
    || bad "DEBUG purpose boot"
       "NOPERM No permissions to access a channel", "PSUBSCRIBE literal deny")
psub_bad.close()

ssub = Conn(); expect(ssub.command("AUTH", "alice", password), b"OK", "SSUBSCRIBE AUTH")
expect(ssub.command("SSUBSCRIBE", "news.a"), [b"ssubscribe", b"news.a", 1],
       "SSUBSCRIBE same namespace")
ssub.close()

# Revocation is an exact all-IO sweep: one violating subscribed client, one counted kill.
revoked = Conn(); expect(revoked.command("AUTH", "alice", password), b"OK", "revocation AUTH")
expect(revoked.command("SUBSCRIBE", "news.a"), [b"subscribe", b"news.a", 1],
       "revocation subscribe")
killed_before = stats(admin)[b"acl_pubsub_clients_killed"]
expect(admin.command("ACL", "SETUSER", "alice", "resetchannels", "&other"), b"OK",
       "channel revoke")
wait_closed(revoked)
killed_after = stats(admin)[b"acl_pubsub_clients_killed"]
expect(killed_after, killed_before + 1, "exact pubsub revocation count")

# Per-IO ACL LOG stores vanilla's ten fields, deduplicates repeats for 60 seconds, and merges.
expect(alice.command("GET", "b:1"), "NOPERM No permissions to access a key", "log repeat one")
expect(alice.command("GET", "b:1"), "NOPERM No permissions to access a key", "log repeat two")
bad_auth = Conn()
expect(bad_auth.command("AUTH", "alice", "wrong"),
       "WRONGPASS invalid username-password pair or user is disabled.", "auth log denial")
bad_auth.close()
log_entries = [map_fields(entry) for entry in admin.command("ACL", "LOG", 100)]
expected_log_fields = {b"count", b"reason", b"context", b"object", b"username",
                       b"age-seconds", b"client-info", b"entry-id",
                       b"timestamp-created", b"timestamp-last-updated"}
if not log_entries or any(set(entry) != expected_log_fields for entry in log_entries):
    raise AssertionError("ACL LOG ten-field shape: %r" % log_entries)
key_entry = next((entry for entry in log_entries
                  if entry[b"reason"] == b"key" and entry[b"context"] == b"toplevel" and
                  entry[b"object"] == b"b:1" and entry[b"username"] == b"alice"), None)
if key_entry is None or key_entry[b"count"] < 2:
    raise AssertionError("ACL LOG key dedup: %r" % key_entry)
if not any(entry[b"reason"] == b"auth" and entry[b"object"].lower() == b"auth"
           for entry in log_entries):
    raise AssertionError("ACL LOG auth entry missing: %r" % log_entries)
if not any(entry[b"reason"] == b"channel" and entry[b"object"] == b"other"
           for entry in log_entries):
    raise AssertionError("ACL LOG channel entry missing: %r" % log_entries)
if not any(entry[b"context"] == b"multi" for entry in log_entries):
    raise AssertionError("ACL LOG MULTI context missing: %r" % log_entries)
expect(admin.command("ACL", "LOG", "RESET"), b"OK", "ACL LOG RESET")
expect(admin.command("ACL", "LOG"), [], "ACL LOG empty after reset")
expect(admin.command("CONFIG", "SET", "acllog-max-len", 0), b"OK", "disable ACL LOG")
expect(alice.command("GET", "b:1"), "NOPERM No permissions to access a key", "denial with log off")
expect(admin.command("ACL", "LOG"), [], "acllog-max-len zero allocates no entries")
expect(admin.command("CONFIG", "SET", "acllog-max-len", 128), b"OK", "restore ACL LOG")

# SAVE is the LIST serializer plus one LF per sorted user, using temp+fsync+rename.
before_selector = admin.command("ACL", "GETUSER", "alice")
selector_reply = admin.command("ACL", "SETUSER", "alice", "(~persist:* +get)")
if is_tomokv:
    if not isinstance(selector_reply, RespError) or "ACL selectors are not supported" not in str(selector_reply):
        raise AssertionError("selector persistence setup must be rejected: %r" % selector_reply)
    expect(admin.command("ACL", "GETUSER", "alice"), before_selector,
           "rejected selector preserves the user before SAVE")
else:
    expect(selector_reply, b"OK", "add reference selector before ACL SAVE")
saved_selectors = fields(admin.command("ACL", "GETUSER", "alice"))[b"selectors"]
if is_tomokv:
    expect(saved_selectors, [], "unsupported selectors cannot enter persisted ACLs")
elif not saved_selectors:
    raise AssertionError("selector persistence setup did not fire")
expect(admin.command("ACL", "SAVE"), b"OK", "ACL SAVE")
with open(ACLFILE, "rb") as handle:
    saved = handle.read()
expected_save = b"".join(line + b"\n" for line in admin.command("ACL", "LIST"))
expect(saved, expected_save, "SAVE byte-identical to LIST serializer")
if glob.glob(ACLFILE + ".tmp-*"):
    raise AssertionError("ACL SAVE left a temp file")

# LOAD accepts leading comments, aggregates errors, and leaves the old registry untouched.
before_bad_load = admin.command("ACL", "LIST")
with open(ACLFILE, "wb") as handle:
    handle.write(b"# accepted comment\nuser good on nopass ~* &* +@all\n"
                 b"user broken on ~* +nosuchcommand\n")
load_error = admin.command("ACL", "LOAD")
if not isinstance(load_error, RespError) or "nosuchcommand" not in str(load_error) or not str(load_error).endswith(
        "WARNING: ACL errors detected, no change to the previously active ACL rules was performed"):
    raise AssertionError("LOAD aggregate error: %r" % load_error)
expect(admin.command("ACL", "LIST"), before_bad_load, "LOAD all-or-nothing")

if is_tomokv:
    with open(ACLFILE, "wb") as handle:
        handle.write(saved + b"user selector-invalid on nopass (+get ~*)\n")
    selector_load_error = admin.command("ACL", "LOAD")
    if not isinstance(selector_load_error, RespError) or "ACL selectors are not supported" not in str(selector_load_error):
        raise AssertionError("selector file must fail LOAD: %r" % selector_load_error)
    expect(admin.command("ACL", "LIST"), before_bad_load, "selector LOAD preserves all live users")

with open(ACLFILE, "wb") as handle:
    handle.write(b"# comments are deliberately not preserved\n" + saved)
expect(admin.command("ACL", "LOAD"), b"OK", "LOAD saved grammar")
expect(admin.command("ACL", "LIST"), before_bad_load, "SETUSER->LIST->SAVE->LOAD round trip")
expect(fields(admin.command("ACL", "GETUSER", "alice"))[b"selectors"], saved_selectors,
       "selector SAVE/LOAD round trip")

# Removing a user through LOAD closes all of that user's connections, subscribed or otherwise.
deleted_user = Conn(); expect(deleted_user.command("AUTH", "alice", password), b"OK", "LOAD delete AUTH")
default_line = next(line for line in before_bad_load if line.startswith(b"user default "))
with open(ACLFILE, "wb") as handle:
    handle.write(default_line + b"\n")
expect(admin.command("ACL", "LOAD"), b"OK", "LOAD removes user")
wait_closed(deleted_user)

for bits, chars in ((1, 1), (256, 64), (4096, 1024)):
    generated = admin.command("ACL", "GENPASS", bits)
    if len(generated) != chars or any(c not in b"0123456789abcdef" for c in generated):
        raise AssertionError("GENPASS %d: %r" % (bits, generated))
expect(admin.command("ACL", "GENPASS", 0),
       "ERR ACL GENPASS argument must be the number of bits for the output password, a positive number up to 4096",
       "GENPASS zero")

final_stats = stats(admin)
for counter in (b"acl_access_denied_auth", b"acl_access_denied_cmd", b"acl_access_denied_key",
                b"acl_access_denied_channel", b"acl_pubsub_clients_killed",
                b"acl_perm_retired"):
    if final_stats.get(counter, 0) == 0:
        raise AssertionError("ACL counter did not fire: %s=%r" % (counter, final_stats.get(counter)))

for connection in (blocked, alice, admin):
    connection.close()
print("acl: PASS (grammar, AUTH, enforcement/closure, revocation, ACL LOG, SAVE/LOAD)")
1:// main.cc — boot, thread launch, pinning, shutdown.
12:#include <atomic>
43:// Signal-handler state. A handler may only touch lock-free atomics, so the thread table is a
44:// fixed array of atomics published through an atomic count: arm() fills the slots, then stores the
54:static std::atomic<Server*> g_signal_server{nullptr};
55:static std::array<std::atomic<ThreadCtx*>, kMaxThreads> g_signal_threads{};
56:static std::atomic<uint32_t> g_signal_thread_count{0};
57:static std::atomic<bool> g_signal_armed{false};
59:static_assert(std::atomic<Server*>::is_always_lock_free);
60:static_assert(std::atomic<ThreadCtx*>::is_always_lock_free);
61:static_assert(std::atomic<uint32_t>::is_always_lock_free);
62:static_assert(std::atomic<bool>::is_always_lock_free);
123:// the cpu from Topology, which intersects with sched_getaffinity. A pin to a cpu outside the mask
125:static void pin_to(int cpu) {
130:    pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
190:            std::fprintf(stderr, "TLS configuration failed: %s\n", tls_error.c_str());
322:                " thread-mode=2s, overlap=%u, %s, alloc=%s\n", srv.nthreads(),
334:    // construction because both discovery and --place validation intersect with sched affinity.
347:    std::atomic<bool> io_boot_failed{false};
349:    auto pin_for = [&](uint32_t tid) {
350:        if (cfg.pin_threads) pin_to(srv.placement().cpu_of_thread(tid));
358:            srv.shard(static_cast<int32_t>(sid)).store().atomic_shutdown_release_records();
359:        for (IoLoop& io : ios) io.reap_atomic_deferred();
371:            pin_for(tid);
373:            self.latch_placement(srv.topo());   // after pinning: sched_getcpu is only now truthful
400:                self.bind_client_registration_hooks(
402:                        return static_cast<IoLoop*>(p)->prepare_client_registration(client);
405:                        static_cast<IoLoop*>(p)->cancel_client_registration(client);
506:            pin_for(tid);
548:            self.bind_client_registration_hooks(
550:                    return static_cast<IoLoop*>(p)->prepare_client_registration(client);
553:                    static_cast<IoLoop*>(p)->cancel_client_registration(client);
1:CXX      ?= g++
19:CXXFLAGS ?= -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread
20:LDLIBS   ?= -luring -pthread
33:LDLIBS   += -lssl -lcrypto
34:BIN      := build/tomokv
35:OBJ      := $(SRC:%.cc=build/%.o)
37:all: $(BIN)
45:build/src/cmd/t_string.o: CXXFLAGS += --param large-unit-insns=10600
47:build/%.o: %.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) $(wildcard third_party/lua/*) Makefile
88:build/config-parser-test: tests/config_parser_test.cc $(wildcard src/*/*.h) Makefile
91:build/flipctl-unit: tests/flipctl_unit.cc src/core/flipctl.cc $(wildcard src/*/*.h) Makefile
95:build/read-local-ring-unit: tests/read_local_ring_unit.cc $(wildcard src/*/*.h) Makefile
98:build/read-local-write-ring-unit: tests/read_local_write_ring_unit.cc $(wildcard src/*/*.h) Makefile
102:build/reorder-unit: tests/reorder_unit.cc $(wildcard src/*/*.h) Makefile
106:build/store-regression: $(STORE_REGRESSION_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
110:build/store-regression-sidecar: $(STORE_REGRESSION_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
114:build/store-regression-tsan: $(STORE_REGRESSION_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
119:build/waits-unit: tests/waits_unit.cc $(wildcard src/*/*.h) Makefile
133:build/rehash-waits-unit: tests/rehash_waits_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) Makefile
136:build/core-concurrency-unit: tests/core_concurrency_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h)
143:build/atomic-survivors-unit: tests/atomic_survivors_unit.cc src/cmd/xshard.cc $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) Makefile
148:build/benchtxn: tools/benchtxn.cc Makefile
151:build/broaden-bench: tests/broaden_bench.cc Makefile
165:build/tests/%.o: tests/%.cc tests/netcmd_unit.h $(wildcard src/*/*.h) $(wildcard src/*/*.cc) $(wildcard src/*/*.inc) Makefile
168:build/netcmd-unit: $(NETCMD_TEST_OBJ) $(NETCMD_LIB_OBJ)
-rwxrwxr-x 1 user user  74298512 Sep 13 11:50 build/netcmd-acl-old
-rwxrwxr-x 1 user user  73989960 Sep 13 11:43 build/netcmd-config-old
-rwxrwxr-x 1 user user  74306064 Sep 13 12:29 build/netcmd-n9-correction-old
-rwxrwxr-x 1 user user  74301984 Sep 13 12:16 build/netcmd-n9-old
-rwxrwxr-x 1 user user  74094232 Sep 13 11:45 build/netcmd-tracking-old
-rwxrwxr-x 1 user user  74304480 Sep 13 12:30 build/netcmd-unit
-rwxrwxr-x 1 user user  73985128 Sep 13 11:36 build/netcmd-zc-old
-rwxrwxr-x 1 user user 112284792 Sep 13 11:43 build/netcmd-zc-sanitized
-rwxrwxr-x 1 user user  80311728 Sep 13 12:30 build/tomokv
-rwxrwxr-x 1 user user  80311728 Sep 13 11:56 build/tomokv-deadconf-post
-rwxrwxr-x 1 user user  80283960 Sep 13 11:26 build/tomokv-deadconf-pre
-rwxrwxr-x 1 user user  80321760 Sep 13 11:46 build/tomokv-tracking-post
-rwxrwxr-x 1 user user  80305040 Sep 13 11:38 build/tomokv-zc-post
-rwxrwxr-x 1 user user  80300960 Sep 13 11:32 build/tomokv-zc-pre
 gate-iteration-1621.log | 50 +++++++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 50 insertions(+)
 M gate-iteration-1621.log
?? CODEX-OUT.round3-N9.md

codex
The server already uses Redis’s `Error in ACL SETUSER modifier '<rule>': <reason>` format. The stale assertion expects Redis’s `Syntax error` for `(on +get)`; TomoKV rejects all selectors with `ACL selectors are not supported`. I’ll make that distinction explicit and check the full rejection message.

`acl.py` has no `--help` handler; its documented interface is `HOST PORT ACLFILE`.
exec
/bin/bash -lc "sed -n '1,88p' Makefile
sed -n '153,173p' Makefile
sed -n '122,151p' tests/aclsel.py
sed -n '300,325p' src/cmd/acl.inc
rg -n -C 3 'Error in ACL SETUSER modifier' src/cmd/acl.inc
rg -n '"'^boot'"\\(' tests/gate.sh
rg -n -C 3 'ratio|thread_mode|atomic =' src/core/config.h | head -65" in /home/user/Projects/cx-deadconf-fix
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


admin = Conn()
is_tomokv = b"tomokv_version:" in admin.command("INFO", "SERVER")
if is_tomokv:
    # This is an explicit server policy, not a fallback selected by a command's success/failure.
    # The former TomoKV parser accepts (), so this branch must fail against that implementation.
    names = ("aclsel", "aclsel-bad", "aclsel-default")
    admin.command("ACL", "DELUSER", *names)
    try:
        expect(admin.command("ACL", "SETUSER", "aclsel", "on", "nopass", "~sel:root:*", "+get"),
               b"OK", "root ACL rules remain available")
        original = admin.command("ACL", "GETUSER", "aclsel")
        for rules in (("()",), ("(+get ~sel:*)",), ("(", "+get", "~sel:*", ")"),
                      ("(",), ("(+@all (~*))",)):
            for name in ("aclsel", "aclsel-bad"):
                reply = admin.command("ACL", "SETUSER", name, "reset", "on", "nopass", *rules)
                if not isinstance(reply, RespError) or "ACL selectors are not supported" not in str(reply):
                    raise AssertionError("selector was not explicitly rejected: %r -> %r" % (rules, reply))
                expect(admin.command("ACL", "GETUSER", "aclsel"), original,
                       "rejected selector preserves root permissions")
                expect(admin.command("ACL", "GETUSER", "aclsel-bad"), None,
                       "rejected selector creates no user")
        expect(fields(original)[b"selectors"], [], "root user has no stored selectors")
    finally:
        admin.command("ACL", "DELUSER", *names)
        admin.close()
    print("aclsel: PASS (%d checks; selector rejection and unchanged root permissions)" % CHECKS)
    sys.exit(0)
for username in ("aclsel", "aclsel-bad", "aclsel-default"):
            return false;
        }
        bool duplicate = false;
        for (const auto& password : image.passwords) duplicate |= acl_digest_equal(password, digest);
        if (!duplicate) image.passwords.push_back(digest);
        image.flags &= ~AclUserNoPass;
    } else if (rule.p[0] == '<' || rule.p[0] == '!') {
        std::array<uint64_t, 4> digest;
        if (rule.p[0] == '<') digest = auth_password_digest(Slice(rule.p + 1, rule.n - 1));
        else if (!acl_parse_hash(Slice(rule.p + 1, rule.n - 1), digest)) {
            error = "The password hash must be exactly 64 characters and contain only lowercase hexadecimal characters";
            return false;
        }
        auto found = std::find_if(image.passwords.begin(), image.passwords.end(),
            [&](const auto& password) { return acl_digest_equal(password, digest); });
        if (found == image.passwords.end()) {
            error = "The password you are trying to remove from the user does not exist";
            return false;
        }
        image.passwords.erase(found);
    } else if (rule.p[0] == '(' || rule.p[rule.n - 1] == ')') {
        error = "Syntax error";
        return false;
    } else if (!acl_apply_permission_rule(image.perm, rule, error)) {
        return false;
    }
1046-            AclUserImage image = acl_new_image(definition[0]);
1047-            std::string rule_error, failed;
1048-            if (!acl_apply_rules(image, definition, 1, rule_error, &failed)) {
1049:                error = "Error in ACL SETUSER modifier '" + failed + "': " + rule_error;
1050-                return false;
1051-            }
1052-            images.push_back(std::move(image));
--
1274-        if (!acl_apply_rules(image, rules, 0, error, &failed)) {
1275-            std::string message = "ERR ";
1276-            if (error.rfind("Unmatched parenthesis", 0) == 0) message += error;
1277:            else message += "Error in ACL SETUSER modifier '" + failed + "': " + error;
1278-            reply_err(op.sink(), message.c_str());
1279-            return;
1280-        }
714:boot(){ local bin=$1; shift; launch main "$bin" --ratio $GATE_RATIO "$@"; }
8-// -1 = auto; thresholds self-derive. A field in Config that nothing reads is a lie — delete it.
9-//
10-// COMPILE-TIME tunables live elsewhere on purpose (changing them is a rebuild + re-validation,
11:// not an operational act). The complete list, so nothing hides:
12-//   kRobWindow        64      net/rob.h       max in-flight ops per connection (ROB size);
13-//                                             the read-local write ring is sized FROM it
14-//   kEmbedThreshold   192     store/kvobj.h   value bytes embedded in the key's block
--
109-    else if (cfg_memory_suffix(suffix, suffix_length, "g"))  mul = 1000ull * 1000 * 1000;
110-    else if (cfg_memory_suffix(suffix, suffix_length, "gb")) mul = 1024ull * 1024 * 1024;
111-    else return false;
112:    // Redis preserves strtoull's ULLONG_MAX saturation and then performs the unsigned multiply.
113-    // The wrap for an overflowing suffixed value is odd but observable CONFIG behavior.
114-    out = value * mul;
115-    return true;
--
170-                                                  ClientOutputBufferLimits& limits,
171-                                                  const char*& error) {
172-    if (!count || count % 4) {
173:        error = "Wrong number of arguments in buffer limit configuration.";
174-        return false;
175-    }
176-    ClientOutputBufferLimits scratch = limits;
--
181-            target = &scratch.replica;
182-        else if (cfg_eq_icase(args[i], "pubsub")) target = &scratch.pubsub;
183-        if (!target || cfg_eq_icase(args[i], "master")) {
184:            error = "Invalid client class specified in buffer limit configuration.";
185-            return false;
186-        }
187-        uint64_t hard = 0, soft = 0;
188-        uint32_t seconds = 0;
189-        if (!cfg_parse_memory(args[i + 1], hard) || !cfg_parse_memory(args[i + 2], soft) ||
190-            !cfg_parse_u32(args[i + 3], seconds) || seconds > INT_MAX) {
191:            error = "Error in hard, soft or soft_seconds setting in buffer limit configuration.";
192-            return false;
193-        }
194-        *target = ClientBufferLimit{hard, soft, seconds};
--
212-
213-enum class DebugCommandMode : uint8_t { No = 0, Yes = 1, Local = 2 };
214-enum class AppendFsyncPolicy : uint8_t { Always = 0, Everysec = 1, No = 2 };
215:// One boot-latched persistence engine governs both AOF and snapshot file data/sync operations.
216-// Uring is native; epoll networking derives the syscall persistence engine (there is no ring).
217-enum class PersistIoEngine : uint8_t { Normal = 0, Uring = 1 };
218-// One boot-latched NETWORK event engine for every io thread. Uring is the native default and the
--
274-
275-struct Config {
276-    // ---- placement (boot-only) -------------------------------------------------------------
277:    const char* place       = nullptr;   // complete role@cpu list; null = --ratio / default
278:    // Whole-server role counts for even placement (--ratio); zero = unset, split mode only.
279-    uint32_t even_ifid      = 0;
280-    uint32_t even_ex        = 0;
281-    const char* shard_home  = nullptr;   // optional complete shard:executor_tid topology
282:    // Resolve before persistence recovery and shard allocation: eight migration units per EX.
283-    static constexpr uint32_t kShardsAuto = UINT32_MAX;
284-    uint32_t shards         = kShardsAuto;
285-    bool     pin_threads    = true;     // relative to the process's allowed CPU set
--
327-    std::vector<SaveClause> save{{3600, 1}, {300, 100}, {60, 10000}};
328-    bool appendonly = false;
329-    AppendFsyncPolicy appendfsync = AppendFsyncPolicy::Everysec;
330:    ThreadMode thread_mode = ThreadMode::Split;
331-    // Boot-only local-read lane; its internal winners are fixed.

exec
/bin/bash -lc "git show --stat --oneline 528cb0b15
git ls-files 'build/*' 'tests/AGENTS.md' 'src/AGENTS.md' 'src/cmd/AGENTS.md' '.gitignore'
cat .gitignore
sed -n '146,235p' src/main.cc
ls -ld build build/release 2>/dev/null" in /home/user/Projects/cx-deadconf-fix
 exited 2 in 0ms:
528cb0b15 reject ACL selectors and correct ownership and list-limit comments
 src/cmd/acl.inc      |  47 +-------------
 tests/acl.py         |  24 ++++++-
 tests/aclsel.py      |  27 +++++++-
 tests/differ.py      | 179 +++++++++++++++++----------------------------------
 tests/netcmd_unit.cc |  70 ++++++++++++++++++++
 tomokv.conf          |  14 ++--
 6 files changed, 187 insertions(+), 174 deletions(-)
.gitignore
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
    }

    Config cfg;
    ConfigParseState parse_state;
    std::vector<std::string> token_store;      // owns conf-file tokens; Config keeps views into it
    std::vector<const char*> conf_tokens, cli_tokens;

    // Redis-style optional first argument: ./tomokv tomokv.conf. Flags override that file.
    const char* conf_path = nullptr;
    for (int i = 1; i < argc; i++) {
        if (i == 1 && argv[i][0] != '-') {
            conf_path = argv[i];
        } else {
            cli_tokens.push_back(argv[i]);
        }
    }
    cfg.conf_path = conf_path;   // retained for CONFIG REWRITE; points into argv, which outlives us
    if (conf_path) {
        if (!load_conf_file(conf_path, token_store)) return 1;
        for (const std::string& t : token_store) conf_tokens.push_back(t.c_str());
        const int rc = parse_config_args(conf_tokens, cfg, parse_state, 1, argv[0]);
        if (rc != kConfigParsed) {
            if (rc == kConfigError) std::fprintf(stderr, "(while parsing %s)\n", conf_path);
            return rc == kConfigHelp ? 0 : 1;
        }
    }
    // CLI parses second so flags override the file.
    {
        const int rc = parse_config_args(cli_tokens, cfg, parse_state, 2, argv[0]);
        if (rc != kConfigParsed) return rc == kConfigHelp ? 0 : 1;
    }
    if (validate_config(cfg) != kConfigParsed) return 1;
    // THE ENGINE IS LATCHED HERE, once, before anything that reads it exists. Every Ring in the
    // process must agree (a uring ring cannot receive an eventfd doorbell and vice versa), and no
    // thread has been spawned yet, so this store needs no synchronisation.
    if (cfg.net_io == NetIoEngine::Epoll) {
        g_ring_epoll_mode = true;
        std::fprintf(stderr, "--net-io epoll: using syscall persistence (no io_uring ring)\n");
    }
    std::unique_ptr<TlsContext> tls_context;
    if (cfg.tls_port) {
        std::string tls_error;
        tls_context = TlsContext::create(cfg, tls_error);
        if (!tls_context) {
            std::fprintf(stderr, "TLS configuration failed: %s\n", tls_error.c_str());
            return 1;
        }
    }
    if (!command_registry_init(cfg.tls_port != 0, cfg.thread_mode == ThreadMode::Fused,
                               Server::read_local_enabled(cfg))) {
        std::fprintf(stderr, "command registry init failed\n");
        return 1;
    }

    Server srv;
    if (!srv.prepare_boot(cfg)) {
        std::fprintf(stderr, "placement/geometry resolution failed\n");
        return 1;
    }

    std::unique_ptr<SnapshotLoadPlan> aof_base_plan;
    std::vector<std::unique_ptr<AofReplayPlan>> aof_plans;
    if (cfg.appendonly) {
        std::string warning, error;
        if (!aof_read_recovery(cfg, cfg.shards, aof_base_plan, aof_plans, warning, error)) {
            std::fprintf(stderr, "AOF load plan failed: %s\n", error.c_str());
            return 1;
        }
        if (!warning.empty()) std::fprintf(stderr, "AOF warning: %s\n", warning.c_str());
        if (aof_base_plan) {
            g_hash_kind = static_cast<HashKind>(aof_base_plan->hash_kind);
            g_hash_seed = aof_base_plan->hash_seed;
            g_sip_k0 = aof_base_plan->sip_k0;
            g_sip_k1 = aof_base_plan->sip_k1;
        } else if (!aof_plans.empty()) {
            const AofReplayPlan& plan = *aof_plans.front();
            g_hash_kind = static_cast<HashKind>(plan.hash_kind);
            g_hash_seed = plan.hash_seed;
            g_sip_k0 = plan.sip_k0;
            g_sip_k1 = plan.sip_k1;
        }
    }

    std::unique_ptr<SnapshotLoadPlan> load_plan;
    if (!aof_base_plan && aof_plans.empty()) {
        // The recovery input derives from the existing persistence destination. AOF recovery
        // keeps precedence; a missing dump boots empty, while an unreadable/corrupt dump fails.
        // Path construction and filesystem work remain entirely behind this boot-only gate.
        const std::string load_path = std::string(cfg.dir) + "/" + cfg.dbfilename;
        struct stat dump_stat;
drwxrwxr-x 10 user user 4096 Sep 13 16:44 build

exec
/bin/bash -lc "sed -n '650,718p' tests/gate.sh
taskset -c 112-127 make -j8 build/tomokv > build/acl-gate-fix-build.log 2>&1" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
  cat "$RUN_DIR/abba.timings" >> "$TIMINGS" || return 1
  ABBA_PENDING=0
}
cleanup(){ # EXIT/INT/TERM: publication and teardown remain bounded outside normal row scopes.
  [ "$BASHPID" = "$CLEANUP_OWNER" ] || return 0
  row_unwatch
  publish_abba || return 1
  reap_children
}
CLEANUP_OWNER=$BASHPID
trap 'cleanup || exit 1' EXIT
trap 'exit 130' INT TERM

port_listeners(){ # pids bound to a port, listening or not yet accepting (ss names the owner)
  ss -H -ltnp "sport = :$1" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u \
      | paste -sd, -
}
guard_port(){ # a bound listener OR an accepting peer on the port ends the gate, naming the pid
  local owners; owners=$(port_listeners "$1")
  if [ -n "$owners" ] || (exec 3<>/dev/tcp/127.0.0.1/$1) 2>/dev/null; then
    say "port $1 pre-boot guard" \
        "FAIL (already listening${owners:+; pid=$owners} -- a leftover server; kill it and re-run)"
    exit 1
  fi
}
settle(){ # after a server is gone: wait for $PORT to stop accepting, then a short settle.
  # Replaces a fixed `sleep 5` (x55 per run, ~4.6 min). Not load-bearing: the listener sets
  # SO_REUSEADDR+SO_REUSEPORT (src/core/io_loop.h:167) and `wait` already reaped the process.
  # GATE_STOP_SETTLE=5 restores the old timing if a row ever turns out to depend on it -- which
  # would itself be a finding worth a NOTES line.
  for _ in $(seq 50); do (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null || break; sleep 0.1; done
  sleep "${GATE_STOP_SETTLE:-1}"
}
launch(){ # logtag binary args... -> pid in $SRV, log in $SRVLOG; waits up to 30 s for the port
  local tag=$1 bin=$2; shift 2
  quiet_wait
  SRV=0; SRVLOG=/dev/null
  guard_port "$PORT"
  [ -x "$bin" ] || { say "boot ($tag)" "FAIL ($bin is not an executable)"; return 1; }
  SRVLOG=$(mktemp "$TMPDIR/gate-srv-$tag.XXXXXX")
  # Every ordinary boot gets an empty persistence directory. Explicit recovery arms override it
  # through their later --dir argument; a previous battery's SAVE must not become this one's input.
  local boot_dir
  boot_dir=$(mktemp -d "$TMPDIR/gate-data-$tag.XXXXXX") || return 1
  taskset -c $CORES "$bin" --port $PORT --bind 127.0.0.1 --shards 16 --dir "$boot_dir" "$@" > "$SRVLOG" 2>&1 &
  SRV=$!
  # 30s, not 10s: the AOF replay boot replays its file BEFORE it listens, and on a box shared
  # with other lanes that overran a 10s deadline and turned six AOF rows red with no defect behind
  # them. A generous deadline costs nothing when the server is quick — the loop exits on connect.
  for _ in $(seq 150); do
    if ! kill -0 "$SRV" 2>/dev/null; then
      wait "$SRV" 2>/dev/null; boot_log_tail "$tag" "exited before it listened"; return 1
    fi
    (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && return 0; sleep 0.2; done
  boot_log_tail "$tag" "never accepted on $PORT within 30s"
  return 1
}
boot_log_tail(){ # a boot that failed is a defect report, not a filename: SHOW the server's words.
                 # Tonight three boot failures were triaged twice over because the row said only
                 # "see $SRVLOG" and the log was rotated by the next row's mktemp before anyone
                 # opened it.
  printf 'GATE: boot (%s) %s -- last 25 lines of %s:\n' "$1" "$2" "$SRVLOG" >&2
  tail -n 25 "$SRVLOG" 2>/dev/null | sed 's/^/GATE|   /' >&2
}
boot(){ local bin=$1; shift; launch main "$bin" --ratio $GATE_RATIO "$@"; }
boot_fused(){ # deliberately omits --ratio, which fused mode rejects
  local bin=$1; shift; launch fused "$bin" --thread-mode fused "$@"; }
stop(){
  if [ "$SRV" -gt 0 ]; then

exec
/bin/bash -lc "cat build/acl-gate-fix-build.log
stat -c '%y %n' src/core/io_loop.h src/cmd/acl.inc build/tomokv build/src/main.o
sed -n '88,120p' tests/aclsel.py" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
make: 'build/tomokv' is up to date.
2026-09-13 12:29:01.119286872 +0800 src/core/io_loop.h
2026-09-13 11:47:35.836091720 +0800 src/cmd/acl.inc
2026-09-13 12:30:15.045572089 +0800 build/tomokv
2026-09-13 12:29:41.988444624 +0800 build/src/main.o
def selector_fields(reply):
    result = []
    for selector in reply:
        if not isinstance(selector, list) or len(selector) != 6:
            raise AssertionError("selector shape: %r" % (selector,))
        result.append({selector[index]: selector[index + 1]
                       for index in range(0, len(selector), 2)})
    return result


def stats(conn):
    body = conn.command("INFO", "STATS")
    result = {}
    for line in body.split(b"\r\n"):
        if b":" not in line:
            continue
        key, value = line.split(b":", 1)
        if value.isdigit():
            result[key] = int(value)
    return result


def wait_closed(conn, timeout=6):
    deadline = time.time() + timeout
    while time.time() < deadline:
        readable, _, _ = select.select([conn.sock], [], [], 0.2)
        if not readable:
            continue
        try:
            if conn.sock.recv(1, socket.MSG_PEEK) == b"":
                return
        except (ConnectionError, OSError):
            return

apply patch
patch: completed
/home/user/Projects/cx-deadconf-fix/build/run-acl-gate-fix.py
diff --git a/build/run-acl-gate-fix.py b/build/run-acl-gate-fix.py
new file mode 100644
index 0000000000000000000000000000000000000000..e04c9220652eddf9fbf470eeca99a9849b6487a2
--- /dev/null
+++ b/build/run-acl-gate-fix.py
@@ -0,0 +1,60 @@
+import os
+from pathlib import Path
+import socket
+import subprocess
+import sys
+import tempfile
+import time
+
+
+root = Path(__file__).resolve().parent.parent
+label, test, mode = sys.argv[1:]
+assert os.sched_getaffinity(0) <= set(range(112, 128))
+run_dir = Path(tempfile.mkdtemp(prefix=label + "-", dir=root / "build"))
+aclfile = run_dir / "users.acl"
+aclfile.touch()
+with socket.socket() as guard:
+    guard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
+    guard.bind(("127.0.0.1", 10390))
+
+command = [str(root / "build/tomokv"), "--port", "10390", "--bind", "127.0.0.1",
+           "--shards", "16", "--ratio", "6:2", "--enable-debug-command", "yes",
+           "--atomic", mode, "--aclfile", str(aclfile), "--dir", str(run_dir)]
+print("Command:", " ".join(command), flush=True)
+with (run_dir / "server.log").open("w") as server_log:
+    server = subprocess.Popen(command, cwd=root, stdout=server_log, stderr=subprocess.STDOUT)
+    print("Server PID:", server.pid, flush=True)
+    try:
+        deadline = time.monotonic() + 30
+        while True:
+            if server.poll() is not None:
+                raise RuntimeError("server exited before listening")
+            try:
+                with socket.create_connection(("127.0.0.1", 10390), timeout=0.2):
+                    break
+            except OSError:
+                if time.monotonic() >= deadline:
+                    raise RuntimeError("server did not listen within 30 seconds")
+                time.sleep(0.1)
+        for task in Path(f"/proc/{server.pid}/task").iterdir():
+            assert os.sched_getaffinity(int(task.name)) <= set(range(112, 128))
+        print("All server threads confined to cores 112-127", flush=True)
+        result = subprocess.run([sys.executable, str(root / test), "127.0.0.1", "10390",
+                                 str(aclfile)], cwd=root, text=True, stdout=subprocess.PIPE,
+                                stderr=subprocess.STDOUT, timeout=60)
+        (run_dir / "test.log").write_text(result.stdout)
+        print(result.stdout, end="", flush=True)
+        print("Battery exit:", result.returncode, flush=True)
+    finally:
+        if server.poll() is None:
+            server.terminate()
+            try:
+                server.wait(timeout=10)
+            except subprocess.TimeoutExpired:
+                server.kill()
+                server.wait(timeout=10)
+        print("Server PID", server.pid, "reaped; exit:", server.returncode, flush=True)
+        print("Logs:", run_dir, flush=True)
+        if server.returncode:
+            print((run_dir / "server.log").read_text()[-6000:], flush=True)
+sys.exit(result.returncode)

exec
/bin/bash -lc 'taskset -c 112-127 python3 build/run-acl-gate-fix.py acl-pre-atomic0 tests/acl.py 0' in /home/user/Projects/cx-deadconf-fix
 exited 1 in 101ms:
Traceback (most recent call last):
  File "/home/user/Projects/cx-deadconf-fix/tests/acl.py", line 192, in <module>
    expect(admin.command("ACL", "SETUSER", "bad-selector", "(on +get)"),
  File "/home/user/Projects/cx-deadconf-fix/tests/acl.py", line 94, in expect
    raise AssertionError("%s: got %r, wanted %r" % (label, actual, wanted))
AssertionError: invalid selector rejected: got "ERR Error in ACL SETUSER modifier '(on +get)': ACL selectors are not supported", wanted "ERR Error in ACL SETUSER modifier '(on +get)': Syntax error"
Battery exit: 1
Server PID 2448281 reaped; exit: 0
Logs: /home/user/Projects/cx-deadconf-fix/build/acl-pre-atomic0-_or5oxni

diff --git a/build/run-acl-gate-fix.py b/build/run-acl-gate-fix.py
new file mode 100644
index 0000000000000000000000000000000000000000..e04c9220652eddf9fbf470eeca99a9849b6487a2
--- /dev/null
+++ b/build/run-acl-gate-fix.py
@@ -0,0 +1,60 @@
+import os
+from pathlib import Path
+import socket
+import subprocess
+import sys
+import tempfile
+import time
+
+
+root = Path(__file__).resolve().parent.parent
+label, test, mode = sys.argv[1:]
+assert os.sched_getaffinity(0) <= set(range(112, 128))
+run_dir = Path(tempfile.mkdtemp(prefix=label + "-", dir=root / "build"))
+aclfile = run_dir / "users.acl"
+aclfile.touch()
+with socket.socket() as guard:
+    guard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
+    guard.bind(("127.0.0.1", 10390))
+
+command = [str(root / "build/tomokv"), "--port", "10390", "--bind", "127.0.0.1",
+           "--shards", "16", "--ratio", "6:2", "--enable-debug-command", "yes",
+           "--atomic", mode, "--aclfile", str(aclfile), "--dir", str(run_dir)]
+print("Command:", " ".join(command), flush=True)
+with (run_dir / "server.log").open("w") as server_log:
+    server = subprocess.Popen(command, cwd=root, stdout=server_log, stderr=subprocess.STDOUT)
+    print("Server PID:", server.pid, flush=True)
+    try:
+        deadline = time.monotonic() + 30
+        while True:
+            if server.poll() is not None:
+                raise RuntimeError("server exited before listening")
+            try:
+                with socket.create_connection(("127.0.0.1", 10390), timeout=0.2):
+                    break
+            except OSError:
+                if time.monotonic() >= deadline:
+                    raise RuntimeError("server did not listen within 30 seconds")
+                time.sleep(0.1)
+        for task in Path(f"/proc/{server.pid}/task").iterdir():
+            assert os.sched_getaffinity(int(task.name)) <= set(range(112, 128))
+        print("All server threads confined to cores 112-127", flush=True)
+        result = subprocess.run([sys.executable, str(root / test), "127.0.0.1", "10390",
+                                 str(aclfile)], cwd=root, text=True, stdout=subprocess.PIPE,
+                                stderr=subprocess.STDOUT, timeout=60)
+        (run_dir / "test.log").write_text(result.stdout)
+        print(result.stdout, end="", flush=True)
+        print("Battery exit:", result.returncode, flush=True)
+    finally:
+        if server.poll() is None:
+            server.terminate()
+            try:
+                server.wait(timeout=10)
+            except subprocess.TimeoutExpired:
+                server.kill()
+                server.wait(timeout=10)
+        print("Server PID", server.pid, "reaped; exit:", server.returncode, flush=True)
+        print("Logs:", run_dir, flush=True)
+        if server.returncode:
+            print((run_dir / "server.log").read_text()[-6000:], flush=True)
+sys.exit(result.returncode)

exec
/bin/bash -lc 'taskset -c 112-127 python3 build/run-acl-gate-fix.py acl-pre-atomic1 tests/acl.py 1' in /home/user/Projects/cx-deadconf-fix
 exited 1 in 91ms:
Traceback (most recent call last):
  File "/home/user/Projects/cx-deadconf-fix/tests/acl.py", line 192, in <module>
    expect(admin.command("ACL", "SETUSER", "bad-selector", "(on +get)"),
  File "/home/user/Projects/cx-deadconf-fix/tests/acl.py", line 94, in expect
    raise AssertionError("%s: got %r, wanted %r" % (label, actual, wanted))
AssertionError: invalid selector rejected: got "ERR Error in ACL SETUSER modifier '(on +get)': ACL selectors are not supported", wanted "ERR Error in ACL SETUSER modifier '(on +get)': Syntax error"
Battery exit: 1
Server PID 2460040 reaped; exit: 0
Logs: /home/user/Projects/cx-deadconf-fix/build/acl-pre-atomic1-o99ztvny

diff --git a/build/run-acl-gate-fix.py b/build/run-acl-gate-fix.py
new file mode 100644
index 0000000000000000000000000000000000000000..e04c9220652eddf9fbf470eeca99a9849b6487a2
--- /dev/null
+++ b/build/run-acl-gate-fix.py
@@ -0,0 +1,60 @@
+import os
+from pathlib import Path
+import socket
+import subprocess
+import sys
+import tempfile
+import time
+
+
+root = Path(__file__).resolve().parent.parent
+label, test, mode = sys.argv[1:]
+assert os.sched_getaffinity(0) <= set(range(112, 128))
+run_dir = Path(tempfile.mkdtemp(prefix=label + "-", dir=root / "build"))
+aclfile = run_dir / "users.acl"
+aclfile.touch()
+with socket.socket() as guard:
+    guard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
+    guard.bind(("127.0.0.1", 10390))
+
+command = [str(root / "build/tomokv"), "--port", "10390", "--bind", "127.0.0.1",
+           "--shards", "16", "--ratio", "6:2", "--enable-debug-command", "yes",
+           "--atomic", mode, "--aclfile", str(aclfile), "--dir", str(run_dir)]
+print("Command:", " ".join(command), flush=True)
+with (run_dir / "server.log").open("w") as server_log:
+    server = subprocess.Popen(command, cwd=root, stdout=server_log, stderr=subprocess.STDOUT)
+    print("Server PID:", server.pid, flush=True)
+    try:
+        deadline = time.monotonic() + 30
+        while True:
+            if server.poll() is not None:
+                raise RuntimeError("server exited before listening")
+            try:
+                with socket.create_connection(("127.0.0.1", 10390), timeout=0.2):
+                    break
+            except OSError:
+                if time.monotonic() >= deadline:
+                    raise RuntimeError("server did not listen within 30 seconds")
+                time.sleep(0.1)
+        for task in Path(f"/proc/{server.pid}/task").iterdir():
+            assert os.sched_getaffinity(int(task.name)) <= set(range(112, 128))
+        print("All server threads confined to cores 112-127", flush=True)
+        result = subprocess.run([sys.executable, str(root / test), "127.0.0.1", "10390",
+                                 str(aclfile)], cwd=root, text=True, stdout=subprocess.PIPE,
+                                stderr=subprocess.STDOUT, timeout=60)
+        (run_dir / "test.log").write_text(result.stdout)
+        print(result.stdout, end="", flush=True)
+        print("Battery exit:", result.returncode, flush=True)
+    finally:
+        if server.poll() is None:
+            server.terminate()
+            try:
+                server.wait(timeout=10)
+            except subprocess.TimeoutExpired:
+                server.kill()
+                server.wait(timeout=10)
+        print("Server PID", server.pid, "reaped; exit:", server.returncode, flush=True)
+        print("Logs:", run_dir, flush=True)
+        if server.returncode:
+            print((run_dir / "server.log").read_text()[-6000:], flush=True)
+sys.exit(result.returncode)

apply patch
patch: completed
/home/user/Projects/cx-deadconf-fix/tests/acl.py
diff --git a/build/run-acl-gate-fix.py b/build/run-acl-gate-fix.py
new file mode 100644
index 0000000000000000000000000000000000000000..e04c9220652eddf9fbf470eeca99a9849b6487a2
--- /dev/null
+++ b/build/run-acl-gate-fix.py
@@ -0,0 +1,60 @@
+import os
+from pathlib import Path
+import socket
+import subprocess
+import sys
+import tempfile
+import time
+
+
+root = Path(__file__).resolve().parent.parent
+label, test, mode = sys.argv[1:]
+assert os.sched_getaffinity(0) <= set(range(112, 128))
+run_dir = Path(tempfile.mkdtemp(prefix=label + "-", dir=root / "build"))
+aclfile = run_dir / "users.acl"
+aclfile.touch()
+with socket.socket() as guard:
+    guard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
+    guard.bind(("127.0.0.1", 10390))
+
+command = [str(root / "build/tomokv"), "--port", "10390", "--bind", "127.0.0.1",
+           "--shards", "16", "--ratio", "6:2", "--enable-debug-command", "yes",
+           "--atomic", mode, "--aclfile", str(aclfile), "--dir", str(run_dir)]
+print("Command:", " ".join(command), flush=True)
+with (run_dir / "server.log").open("w") as server_log:
+    server = subprocess.Popen(command, cwd=root, stdout=server_log, stderr=subprocess.STDOUT)
+    print("Server PID:", server.pid, flush=True)
+    try:
+        deadline = time.monotonic() + 30
+        while True:
+            if server.poll() is not None:
+                raise RuntimeError("server exited before listening")
+            try:
+                with socket.create_connection(("127.0.0.1", 10390), timeout=0.2):
+                    break
+            except OSError:
+                if time.monotonic() >= deadline:
+                    raise RuntimeError("server did not listen within 30 seconds")
+                time.sleep(0.1)
+        for task in Path(f"/proc/{server.pid}/task").iterdir():
+            assert os.sched_getaffinity(int(task.name)) <= set(range(112, 128))
+        print("All server threads confined to cores 112-127", flush=True)
+        result = subprocess.run([sys.executable, str(root / test), "127.0.0.1", "10390",
+                                 str(aclfile)], cwd=root, text=True, stdout=subprocess.PIPE,
+                                stderr=subprocess.STDOUT, timeout=60)
+        (run_dir / "test.log").write_text(result.stdout)
+        print(result.stdout, end="", flush=True)
+        print("Battery exit:", result.returncode, flush=True)
+    finally:
+        if server.poll() is None:
+            server.terminate()
+            try:
+                server.wait(timeout=10)
+            except subprocess.TimeoutExpired:
+                server.kill()
+                server.wait(timeout=10)
+        print("Server PID", server.pid, "reaped; exit:", server.returncode, flush=True)
+        print("Logs:", run_dir, flush=True)
+        if server.returncode:
+            print((run_dir / "server.log").read_text()[-6000:], flush=True)
+sys.exit(result.returncode)
diff --git a/tests/acl.py b/tests/acl.py
index b5e4cb2f706371a74fbe03f8b025e6bbb6ab6e96..78c113504642de4cf9b9701dfc1990428393a95d
--- a/tests/acl.py
+++ b/tests/acl.py
@@ -189,9 +189,14 @@
 expect(admin.command("ACL", "SETUSER", "bad-rw", "%R~cache:*"),
        "ERR Error in ACL SETUSER modifier '%R~cache:*': Read/write key patterns are not supported until command key specifications are available",
        "%R rule rejected")
+# Redis 7.4 rejects user flags inside selectors with "Syntax error". TomoKV rejects
+# all selectors until enforcement exists, using the same SETUSER modifier-error grammar.
 expect(admin.command("ACL", "SETUSER", "bad-selector", "(on +get)"),
-       "ERR Error in ACL SETUSER modifier '(on +get)': Syntax error",
+       "ERR Error in ACL SETUSER modifier '(on +get)': " +
+       ("ACL selectors are not supported" if is_tomokv else "Syntax error"),
        "invalid selector rejected")
+expect(admin.command("ACL", "GETUSER", "bad-selector"), None,
+       "rejected selector creates no user")
 expect(admin.command("ACL", "SETUSER", "bad-firstarg", "+select|0"),
        "ERR Error in ACL SETUSER modifier '+select|0': Allowing first-arg of a subcommand is not supported",
        "first-arg rule rejected")
@@ -333,8 +338,9 @@
 before_selector = admin.command("ACL", "GETUSER", "alice")
 selector_reply = admin.command("ACL", "SETUSER", "alice", "(~persist:* +get)")
 if is_tomokv:
-    if not isinstance(selector_reply, RespError) or "ACL selectors are not supported" not in str(selector_reply):
-        raise AssertionError("selector persistence setup must be rejected: %r" % selector_reply)
+    expect(selector_reply,
+           "ERR Error in ACL SETUSER modifier '(~persist:* +get)': ACL selectors are not supported",
+           "selector persistence setup rejected")
     expect(admin.command("ACL", "GETUSER", "alice"), before_selector,
            "rejected selector preserves the user before SAVE")
 else:

exec
/bin/bash -lc 'taskset -c 112-127 python3 build/run-acl-gate-fix.py acl-post-atomic0 tests/acl.py 0' in /home/user/Projects/cx-deadconf-fix
 succeeded in 306ms:
acl: PASS (grammar, AUTH, enforcement/closure, revocation, ACL LOG, SAVE/LOAD)
Battery exit: 0
Server PID 2471294 reaped; exit: 0
Logs: /home/user/Projects/cx-deadconf-fix/build/acl-post-atomic0-udfusevt

diff --git a/build/run-acl-gate-fix.py b/build/run-acl-gate-fix.py
new file mode 100644
index 0000000000000000000000000000000000000000..e04c9220652eddf9fbf470eeca99a9849b6487a2
--- /dev/null
+++ b/build/run-acl-gate-fix.py
@@ -0,0 +1,60 @@
+import os
+from pathlib import Path
+import socket
+import subprocess
+import sys
+import tempfile
+import time
+
+
+root = Path(__file__).resolve().parent.parent
+label, test, mode = sys.argv[1:]
+assert os.sched_getaffinity(0) <= set(range(112, 128))
+run_dir = Path(tempfile.mkdtemp(prefix=label + "-", dir=root / "build"))
+aclfile = run_dir / "users.acl"
+aclfile.touch()
+with socket.socket() as guard:
+    guard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
+    guard.bind(("127.0.0.1", 10390))
+
+command = [str(root / "build/tomokv"), "--port", "10390", "--bind", "127.0.0.1",
+           "--shards", "16", "--ratio", "6:2", "--enable-debug-command", "yes",
+           "--atomic", mode, "--aclfile", str(aclfile), "--dir", str(run_dir)]
+print("Command:", " ".join(command), flush=True)
+with (run_dir / "server.log").open("w") as server_log:
+    server = subprocess.Popen(command, cwd=root, stdout=server_log, stderr=subprocess.STDOUT)
+    print("Server PID:", server.pid, flush=True)
+    try:
+        deadline = time.monotonic() + 30
+        while True:
+            if server.poll() is not None:
+                raise RuntimeError("server exited before listening")
+            try:
+                with socket.create_connection(("127.0.0.1", 10390), timeout=0.2):
+                    break
+            except OSError:
+                if time.monotonic() >= deadline:
+                    raise RuntimeError("server did not listen within 30 seconds")
+                time.sleep(0.1)
+        for task in Path(f"/proc/{server.pid}/task").iterdir():
+            assert os.sched_getaffinity(int(task.name)) <= set(range(112, 128))
+        print("All server threads confined to cores 112-127", flush=True)
+        result = subprocess.run([sys.executable, str(root / test), "127.0.0.1", "10390",
+                                 str(aclfile)], cwd=root, text=True, stdout=subprocess.PIPE,
+                                stderr=subprocess.STDOUT, timeout=60)
+        (run_dir / "test.log").write_text(result.stdout)
+        print(result.stdout, end="", flush=True)
+        print("Battery exit:", result.returncode, flush=True)
+    finally:
+        if server.poll() is None:
+            server.terminate()
+            try:
+                server.wait(timeout=10)
+            except subprocess.TimeoutExpired:
+                server.kill()
+                server.wait(timeout=10)
+        print("Server PID", server.pid, "reaped; exit:", server.returncode, flush=True)
+        print("Logs:", run_dir, flush=True)
+        if server.returncode:
+            print((run_dir / "server.log").read_text()[-6000:], flush=True)
+sys.exit(result.returncode)
diff --git a/tests/acl.py b/tests/acl.py
index b5e4cb2f706371a74fbe03f8b025e6bbb6ab6e96..78c113504642de4cf9b9701dfc1990428393a95d
--- a/tests/acl.py
+++ b/tests/acl.py
@@ -189,9 +189,14 @@
 expect(admin.command("ACL", "SETUSER", "bad-rw", "%R~cache:*"),
        "ERR Error in ACL SETUSER modifier '%R~cache:*': Read/write key patterns are not supported until command key specifications are available",
        "%R rule rejected")
+# Redis 7.4 rejects user flags inside selectors with "Syntax error". TomoKV rejects
+# all selectors until enforcement exists, using the same SETUSER modifier-error grammar.
 expect(admin.command("ACL", "SETUSER", "bad-selector", "(on +get)"),
-       "ERR Error in ACL SETUSER modifier '(on +get)': Syntax error",
+       "ERR Error in ACL SETUSER modifier '(on +get)': " +
+       ("ACL selectors are not supported" if is_tomokv else "Syntax error"),
        "invalid selector rejected")
+expect(admin.command("ACL", "GETUSER", "bad-selector"), None,
+       "rejected selector creates no user")
 expect(admin.command("ACL", "SETUSER", "bad-firstarg", "+select|0"),
        "ERR Error in ACL SETUSER modifier '+select|0': Allowing first-arg of a subcommand is not supported",
        "first-arg rule rejected")
@@ -333,8 +338,9 @@
 before_selector = admin.command("ACL", "GETUSER", "alice")
 selector_reply = admin.command("ACL", "SETUSER", "alice", "(~persist:* +get)")
 if is_tomokv:
-    if not isinstance(selector_reply, RespError) or "ACL selectors are not supported" not in str(selector_reply):
-        raise AssertionError("selector persistence setup must be rejected: %r" % selector_reply)
+    expect(selector_reply,
+           "ERR Error in ACL SETUSER modifier '(~persist:* +get)': ACL selectors are not supported",
+           "selector persistence setup rejected")
     expect(admin.command("ACL", "GETUSER", "alice"), before_selector,
            "rejected selector preserves the user before SAVE")
 else:

exec
/bin/bash -lc 'taskset -c 112-127 python3 build/run-acl-gate-fix.py acl-post-atomic1 tests/acl.py 1' in /home/user/Projects/cx-deadconf-fix
 succeeded in 296ms:
acl: PASS (grammar, AUTH, enforcement/closure, revocation, ACL LOG, SAVE/LOAD)
Battery exit: 0
Server PID 2473502 reaped; exit: 0
Logs: /home/user/Projects/cx-deadconf-fix/build/acl-post-atomic1-7vphbsjl

diff --git a/build/run-acl-gate-fix.py b/build/run-acl-gate-fix.py
new file mode 100644
index 0000000000000000000000000000000000000000..e04c9220652eddf9fbf470eeca99a9849b6487a2
--- /dev/null
+++ b/build/run-acl-gate-fix.py
@@ -0,0 +1,60 @@
+import os
+from pathlib import Path
+import socket
+import subprocess
+import sys
+import tempfile
+import time
+
+
+root = Path(__file__).resolve().parent.parent
+label, test, mode = sys.argv[1:]
+assert os.sched_getaffinity(0) <= set(range(112, 128))
+run_dir = Path(tempfile.mkdtemp(prefix=label + "-", dir=root / "build"))
+aclfile = run_dir / "users.acl"
+aclfile.touch()
+with socket.socket() as guard:
+    guard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
+    guard.bind(("127.0.0.1", 10390))
+
+command = [str(root / "build/tomokv"), "--port", "10390", "--bind", "127.0.0.1",
+           "--shards", "16", "--ratio", "6:2", "--enable-debug-command", "yes",
+           "--atomic", mode, "--aclfile", str(aclfile), "--dir", str(run_dir)]
+print("Command:", " ".join(command), flush=True)
+with (run_dir / "server.log").open("w") as server_log:
+    server = subprocess.Popen(command, cwd=root, stdout=server_log, stderr=subprocess.STDOUT)
+    print("Server PID:", server.pid, flush=True)
+    try:
+        deadline = time.monotonic() + 30
+        while True:
+            if server.poll() is not None:
+                raise RuntimeError("server exited before listening")
+            try:
+                with socket.create_connection(("127.0.0.1", 10390), timeout=0.2):
+                    break
+            except OSError:
+                if time.monotonic() >= deadline:
+                    raise RuntimeError("server did not listen within 30 seconds")
+                time.sleep(0.1)
+        for task in Path(f"/proc/{server.pid}/task").iterdir():
+            assert os.sched_getaffinity(int(task.name)) <= set(range(112, 128))
+        print("All server threads confined to cores 112-127", flush=True)
+        result = subprocess.run([sys.executable, str(root / test), "127.0.0.1", "10390",
+                                 str(aclfile)], cwd=root, text=True, stdout=subprocess.PIPE,
+                                stderr=subprocess.STDOUT, timeout=60)
+        (run_dir / "test.log").write_text(result.stdout)
+        print(result.stdout, end="", flush=True)
+        print("Battery exit:", result.returncode, flush=True)
+    finally:
+        if server.poll() is None:
+            server.terminate()
+            try:
+                server.wait(timeout=10)
+            except subprocess.TimeoutExpired:
+                server.kill()
+                server.wait(timeout=10)
+        print("Server PID", server.pid, "reaped; exit:", server.returncode, flush=True)
+        print("Logs:", run_dir, flush=True)
+        if server.returncode:
+            print((run_dir / "server.log").read_text()[-6000:], flush=True)
+sys.exit(result.returncode)
diff --git a/tests/acl.py b/tests/acl.py
index b5e4cb2f706371a74fbe03f8b025e6bbb6ab6e96..78c113504642de4cf9b9701dfc1990428393a95d
--- a/tests/acl.py
+++ b/tests/acl.py
@@ -189,9 +189,14 @@
 expect(admin.command("ACL", "SETUSER", "bad-rw", "%R~cache:*"),
        "ERR Error in ACL SETUSER modifier '%R~cache:*': Read/write key patterns are not supported until command key specifications are available",
        "%R rule rejected")
+# Redis 7.4 rejects user flags inside selectors with "Syntax error". TomoKV rejects
+# all selectors until enforcement exists, using the same SETUSER modifier-error grammar.
 expect(admin.command("ACL", "SETUSER", "bad-selector", "(on +get)"),
-       "ERR Error in ACL SETUSER modifier '(on +get)': Syntax error",
+       "ERR Error in ACL SETUSER modifier '(on +get)': " +
+       ("ACL selectors are not supported" if is_tomokv else "Syntax error"),
        "invalid selector rejected")
+expect(admin.command("ACL", "GETUSER", "bad-selector"), None,
+       "rejected selector creates no user")
 expect(admin.command("ACL", "SETUSER", "bad-firstarg", "+select|0"),
        "ERR Error in ACL SETUSER modifier '+select|0': Allowing first-arg of a subcommand is not supported",
        "first-arg rule rejected")
@@ -333,8 +338,9 @@
 before_selector = admin.command("ACL", "GETUSER", "alice")
 selector_reply = admin.command("ACL", "SETUSER", "alice", "(~persist:* +get)")
 if is_tomokv:
-    if not isinstance(selector_reply, RespError) or "ACL selectors are not supported" not in str(selector_reply):
-        raise AssertionError("selector persistence setup must be rejected: %r" % selector_reply)
+    expect(selector_reply,
+           "ERR Error in ACL SETUSER modifier '(~persist:* +get)': ACL selectors are not supported",
+           "selector persistence setup rejected")
     expect(admin.command("ACL", "GETUSER", "alice"), before_selector,
            "rejected selector preserves the user before SAVE")
 else:

codex
Both ACL battery runs reproduced the failure before the edit and now pass with `--atomic 0` and `--atomic 1`. The tests check the full modifier-error message and verify that rejection leaves ACL users unchanged. All server threads stayed on cores 112–127, and each server was terminated and reaped by PID. I’m committing the test correction now.
exec
/bin/bash -lc "git diff --check && git diff -- tests/acl.py && git status --short
git add -A ':"'!CODEX-OUT.md'"' ':"'!CODEX-OUT.round3-N9.md'"' ':"'!gate-iteration-1621.log'"'
git diff --cached --stat" in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
diff --git a/tests/acl.py b/tests/acl.py
index b5e4cb2f7..78c113504 100644
--- a/tests/acl.py
+++ b/tests/acl.py
@@ -189,9 +189,14 @@ expect(admin.command("ACL", "USERS"), [b"alice", b"default"], "USERS ordering")
 expect(admin.command("ACL", "SETUSER", "bad-rw", "%R~cache:*"),
        "ERR Error in ACL SETUSER modifier '%R~cache:*': Read/write key patterns are not supported until command key specifications are available",
        "%R rule rejected")
+# Redis 7.4 rejects user flags inside selectors with "Syntax error". TomoKV rejects
+# all selectors until enforcement exists, using the same SETUSER modifier-error grammar.
 expect(admin.command("ACL", "SETUSER", "bad-selector", "(on +get)"),
-       "ERR Error in ACL SETUSER modifier '(on +get)': Syntax error",
+       "ERR Error in ACL SETUSER modifier '(on +get)': " +
+       ("ACL selectors are not supported" if is_tomokv else "Syntax error"),
        "invalid selector rejected")
+expect(admin.command("ACL", "GETUSER", "bad-selector"), None,
+       "rejected selector creates no user")
 expect(admin.command("ACL", "SETUSER", "bad-firstarg", "+select|0"),
        "ERR Error in ACL SETUSER modifier '+select|0': Allowing first-arg of a subcommand is not supported",
        "first-arg rule rejected")
@@ -333,8 +338,9 @@ expect(admin.command("CONFIG", "SET", "acllog-max-len", 128), b"OK", "restore AC
 before_selector = admin.command("ACL", "GETUSER", "alice")
 selector_reply = admin.command("ACL", "SETUSER", "alice", "(~persist:* +get)")
 if is_tomokv:
-    if not isinstance(selector_reply, RespError) or "ACL selectors are not supported" not in str(selector_reply):
-        raise AssertionError("selector persistence setup must be rejected: %r" % selector_reply)
+    expect(selector_reply,
+           "ERR Error in ACL SETUSER modifier '(~persist:* +get)': ACL selectors are not supported",
+           "selector persistence setup rejected")
     expect(admin.command("ACL", "GETUSER", "alice"), before_selector,
            "rejected selector preserves the user before SAVE")
 else:
 M tests/acl.py
The following paths are ignored by one of your .gitignore files:
CODEX-OUT.md
hint: Use -f if you really want to add them.
hint: Turn this message off by running
hint: "git config advice.addIgnoredFile false"
 tests/acl.py | 12 +++++++++---
 1 file changed, 9 insertions(+), 3 deletions(-)

diff --git a/build/run-acl-gate-fix.py b/build/run-acl-gate-fix.py
new file mode 100644
index 0000000000000000000000000000000000000000..e04c9220652eddf9fbf470eeca99a9849b6487a2
--- /dev/null
+++ b/build/run-acl-gate-fix.py
@@ -0,0 +1,60 @@
+import os
+from pathlib import Path
+import socket
+import subprocess
+import sys
+import tempfile
+import time
+
+
+root = Path(__file__).resolve().parent.parent
+label, test, mode = sys.argv[1:]
+assert os.sched_getaffinity(0) <= set(range(112, 128))
+run_dir = Path(tempfile.mkdtemp(prefix=label + "-", dir=root / "build"))
+aclfile = run_dir / "users.acl"
+aclfile.touch()
+with socket.socket() as guard:
+    guard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
+    guard.bind(("127.0.0.1", 10390))
+
+command = [str(root / "build/tomokv"), "--port", "10390", "--bind", "127.0.0.1",
+           "--shards", "16", "--ratio", "6:2", "--enable-debug-command", "yes",
+           "--atomic", mode, "--aclfile", str(aclfile), "--dir", str(run_dir)]
+print("Command:", " ".join(command), flush=True)
+with (run_dir / "server.log").open("w") as server_log:
+    server = subprocess.Popen(command, cwd=root, stdout=server_log, stderr=subprocess.STDOUT)
+    print("Server PID:", server.pid, flush=True)
+    try:
+        deadline = time.monotonic() + 30
+        while True:
+            if server.poll() is not None:
+                raise RuntimeError("server exited before listening")
+            try:
+                with socket.create_connection(("127.0.0.1", 10390), timeout=0.2):
+                    break
+            except OSError:
+                if time.monotonic() >= deadline:
+                    raise RuntimeError("server did not listen within 30 seconds")
+                time.sleep(0.1)
+        for task in Path(f"/proc/{server.pid}/task").iterdir():
+            assert os.sched_getaffinity(int(task.name)) <= set(range(112, 128))
+        print("All server threads confined to cores 112-127", flush=True)
+        result = subprocess.run([sys.executable, str(root / test), "127.0.0.1", "10390",
+                                 str(aclfile)], cwd=root, text=True, stdout=subprocess.PIPE,
+                                stderr=subprocess.STDOUT, timeout=60)
+        (run_dir / "test.log").write_text(result.stdout)
+        print(result.stdout, end="", flush=True)
+        print("Battery exit:", result.returncode, flush=True)
+    finally:
+        if server.poll() is None:
+            server.terminate()
+            try:
+                server.wait(timeout=10)
+            except subprocess.TimeoutExpired:
+                server.kill()
+                server.wait(timeout=10)
+        print("Server PID", server.pid, "reaped; exit:", server.returncode, flush=True)
+        print("Logs:", run_dir, flush=True)
+        if server.returncode:
+            print((run_dir / "server.log").read_text()[-6000:], flush=True)
+sys.exit(result.returncode)
diff --git a/tests/acl.py b/tests/acl.py
index b5e4cb2f706371a74fbe03f8b025e6bbb6ab6e96..78c113504642de4cf9b9701dfc1990428393a95d
--- a/tests/acl.py
+++ b/tests/acl.py
@@ -189,9 +189,14 @@
 expect(admin.command("ACL", "SETUSER", "bad-rw", "%R~cache:*"),
        "ERR Error in ACL SETUSER modifier '%R~cache:*': Read/write key patterns are not supported until command key specifications are available",
        "%R rule rejected")
+# Redis 7.4 rejects user flags inside selectors with "Syntax error". TomoKV rejects
+# all selectors until enforcement exists, using the same SETUSER modifier-error grammar.
 expect(admin.command("ACL", "SETUSER", "bad-selector", "(on +get)"),
-       "ERR Error in ACL SETUSER modifier '(on +get)': Syntax error",
+       "ERR Error in ACL SETUSER modifier '(on +get)': " +
+       ("ACL selectors are not supported" if is_tomokv else "Syntax error"),
        "invalid selector rejected")
+expect(admin.command("ACL", "GETUSER", "bad-selector"), None,
+       "rejected selector creates no user")
 expect(admin.command("ACL", "SETUSER", "bad-firstarg", "+select|0"),
        "ERR Error in ACL SETUSER modifier '+select|0': Allowing first-arg of a subcommand is not supported",
        "first-arg rule rejected")
@@ -333,8 +338,9 @@
 before_selector = admin.command("ACL", "GETUSER", "alice")
 selector_reply = admin.command("ACL", "SETUSER", "alice", "(~persist:* +get)")
 if is_tomokv:
-    if not isinstance(selector_reply, RespError) or "ACL selectors are not supported" not in str(selector_reply):
-        raise AssertionError("selector persistence setup must be rejected: %r" % selector_reply)
+    expect(selector_reply,
+           "ERR Error in ACL SETUSER modifier '(~persist:* +get)': ACL selectors are not supported",
+           "selector persistence setup rejected")
     expect(admin.command("ACL", "GETUSER", "alice"), before_selector,
            "rejected selector preserves the user before SAVE")
 else:

exec
/bin/bash -lc 'git log -3 --oneline && git diff --cached --check && git commit -m "align ACL battery with explicit selector rejection" && git status --short && git show --stat --oneline HEAD' in /home/user/Projects/cx-deadconf-fix
 succeeded in 0ms:
3e4685adb autosave: cx-deadconf-fix 16:49 (1 files)
1e1eb2f09 autosave: cx-deadconf-fix 16:39 (1 files)
b1a0b2b64 autosave: cx-deadconf-fix 16:29 (1 files)
[cx-deadconf-fix-items 5cd9ed1f8] align ACL battery with explicit selector rejection
 1 file changed, 9 insertions(+), 3 deletions(-)
5cd9ed1f8 align ACL battery with explicit selector rejection
 tests/acl.py | 12 +++++++++---
 1 file changed, 9 insertions(+), 3 deletions(-)

diff --git a/build/run-acl-gate-fix.py b/build/run-acl-gate-fix.py
new file mode 100644
index 0000000000000000000000000000000000000000..e04c9220652eddf9fbf470eeca99a9849b6487a2
--- /dev/null
+++ b/build/run-acl-gate-fix.py
@@ -0,0 +1,60 @@
+import os
+from pathlib import Path
+import socket
+import subprocess
+import sys
+import tempfile
+import time
+
+
+root = Path(__file__).resolve().parent.parent
+label, test, mode = sys.argv[1:]
+assert os.sched_getaffinity(0) <= set(range(112, 128))
+run_dir = Path(tempfile.mkdtemp(prefix=label + "-", dir=root / "build"))
+aclfile = run_dir / "users.acl"
+aclfile.touch()
+with socket.socket() as guard:
+    guard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
+    guard.bind(("127.0.0.1", 10390))
+
+command = [str(root / "build/tomokv"), "--port", "10390", "--bind", "127.0.0.1",
+           "--shards", "16", "--ratio", "6:2", "--enable-debug-command", "yes",
+           "--atomic", mode, "--aclfile", str(aclfile), "--dir", str(run_dir)]
+print("Command:", " ".join(command), flush=True)
+with (run_dir / "server.log").open("w") as server_log:
+    server = subprocess.Popen(command, cwd=root, stdout=server_log, stderr=subprocess.STDOUT)
+    print("Server PID:", server.pid, flush=True)
+    try:
+        deadline = time.monotonic() + 30
+        while True:
+            if server.poll() is not None:
+                raise RuntimeError("server exited before listening")
+            try:
+                with socket.create_connection(("127.0.0.1", 10390), timeout=0.2):
+                    break
+            except OSError:
+                if time.monotonic() >= deadline:
+                    raise RuntimeError("server did not listen within 30 seconds")
+                time.sleep(0.1)
+        for task in Path(f"/proc/{server.pid}/task").iterdir():
+            assert os.sched_getaffinity(int(task.name)) <= set(range(112, 128))
+        print("All server threads confined to cores 112-127", flush=True)
+        result = subprocess.run([sys.executable, str(root / test), "127.0.0.1", "10390",
+                                 str(aclfile)], cwd=root, text=True, stdout=subprocess.PIPE,
+                                stderr=subprocess.STDOUT, timeout=60)
+        (run_dir / "test.log").write_text(result.stdout)
+        print(result.stdout, end="", flush=True)
+        print("Battery exit:", result.returncode, flush=True)
+    finally:
+        if server.poll() is None:
+            server.terminate()
+            try:
+                server.wait(timeout=10)
+            except subprocess.TimeoutExpired:
+                server.kill()
+                server.wait(timeout=10)
+        print("Server PID", server.pid, "reaped; exit:", server.returncode, flush=True)
+        print("Logs:", run_dir, flush=True)
+        if server.returncode:
+            print((run_dir / "server.log").read_text()[-6000:], flush=True)
+sys.exit(result.returncode)
diff --git a/tests/acl.py b/tests/acl.py
index b5e4cb2f706371a74fbe03f8b025e6bbb6ab6e96..78c113504642de4cf9b9701dfc1990428393a95d
--- a/tests/acl.py
+++ b/tests/acl.py
@@ -189,9 +189,14 @@
 expect(admin.command("ACL", "SETUSER", "bad-rw", "%R~cache:*"),
        "ERR Error in ACL SETUSER modifier '%R~cache:*': Read/write key patterns are not supported until command key specifications are available",
        "%R rule rejected")
+# Redis 7.4 rejects user flags inside selectors with "Syntax error". TomoKV rejects
+# all selectors until enforcement exists, using the same SETUSER modifier-error grammar.
 expect(admin.command("ACL", "SETUSER", "bad-selector", "(on +get)"),
-       "ERR Error in ACL SETUSER modifier '(on +get)': Syntax error",
+       "ERR Error in ACL SETUSER modifier '(on +get)': " +
+       ("ACL selectors are not supported" if is_tomokv else "Syntax error"),
        "invalid selector rejected")
+expect(admin.command("ACL", "GETUSER", "bad-selector"), None,
+       "rejected selector creates no user")
 expect(admin.command("ACL", "SETUSER", "bad-firstarg", "+select|0"),
        "ERR Error in ACL SETUSER modifier '+select|0': Allowing first-arg of a subcommand is not supported",
        "first-arg rule rejected")
@@ -333,8 +338,9 @@
 before_selector = admin.command("ACL", "GETUSER", "alice")
 selector_reply = admin.command("ACL", "SETUSER", "alice", "(~persist:* +get)")
 if is_tomokv:
-    if not isinstance(selector_reply, RespError) or "ACL selectors are not supported" not in str(selector_reply):
-        raise AssertionError("selector persistence setup must be rejected: %r" % selector_reply)
+    expect(selector_reply,
+           "ERR Error in ACL SETUSER modifier '(~persist:* +get)': ACL selectors are not supported",
+           "selector persistence setup rejected")
     expect(admin.command("ACL", "GETUSER", "alice"), before_selector,
            "rejected selector preserves the user before SAVE")
 else:

codex
The server already matched Redis 7.4’s modifier-error grammar. Corrected the stale test expectation while preserving explicit selector rejection.

| Item | File | Test result | Commit |
|---|---|---|---|
| ACL gate failure | [tests/acl.py](/home/user/Projects/cx-deadconf-fix/tests/acl.py:192) | FAIL before; PASS after in both atomic modes | `5cd9ed1f8` |

Runs used cores 112–127, port 10390, shards 16, ratio 6:2. Servers terminated and reaped by PID. Worktree clean.

CX-deadconf-fix-DONE
diff --git a/build/run-acl-gate-fix.py b/build/run-acl-gate-fix.py
new file mode 100644
index 0000000000000000000000000000000000000000..e04c9220652eddf9fbf470eeca99a9849b6487a2
--- /dev/null
+++ b/build/run-acl-gate-fix.py
@@ -0,0 +1,60 @@
+import os
+from pathlib import Path
+import socket
+import subprocess
+import sys
+import tempfile
+import time
+
+
+root = Path(__file__).resolve().parent.parent
+label, test, mode = sys.argv[1:]
+assert os.sched_getaffinity(0) <= set(range(112, 128))
+run_dir = Path(tempfile.mkdtemp(prefix=label + "-", dir=root / "build"))
+aclfile = run_dir / "users.acl"
+aclfile.touch()
+with socket.socket() as guard:
+    guard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
+    guard.bind(("127.0.0.1", 10390))
+
+command = [str(root / "build/tomokv"), "--port", "10390", "--bind", "127.0.0.1",
+           "--shards", "16", "--ratio", "6:2", "--enable-debug-command", "yes",
+           "--atomic", mode, "--aclfile", str(aclfile), "--dir", str(run_dir)]
+print("Command:", " ".join(command), flush=True)
+with (run_dir / "server.log").open("w") as server_log:
+    server = subprocess.Popen(command, cwd=root, stdout=server_log, stderr=subprocess.STDOUT)
+    print("Server PID:", server.pid, flush=True)
+    try:
+        deadline = time.monotonic() + 30
+        while True:
+            if server.poll() is not None:
+                raise RuntimeError("server exited before listening")
+            try:
+                with socket.create_connection(("127.0.0.1", 10390), timeout=0.2):
+                    break
+            except OSError:
+                if time.monotonic() >= deadline:
+                    raise RuntimeError("server did not listen within 30 seconds")
+                time.sleep(0.1)
+        for task in Path(f"/proc/{server.pid}/task").iterdir():
+            assert os.sched_getaffinity(int(task.name)) <= set(range(112, 128))
+        print("All server threads confined to cores 112-127", flush=True)
+        result = subprocess.run([sys.executable, str(root / test), "127.0.0.1", "10390",
+                                 str(aclfile)], cwd=root, text=True, stdout=subprocess.PIPE,
+                                stderr=subprocess.STDOUT, timeout=60)
+        (run_dir / "test.log").write_text(result.stdout)
+        print(result.stdout, end="", flush=True)
+        print("Battery exit:", result.returncode, flush=True)
+    finally:
+        if server.poll() is None:
+            server.terminate()
+            try:
+                server.wait(timeout=10)
+            except subprocess.TimeoutExpired:
+                server.kill()
+                server.wait(timeout=10)
+        print("Server PID", server.pid, "reaped; exit:", server.returncode, flush=True)
+        print("Logs:", run_dir, flush=True)
+        if server.returncode:
+            print((run_dir / "server.log").read_text()[-6000:], flush=True)
+sys.exit(result.returncode)
diff --git a/tests/acl.py b/tests/acl.py
index b5e4cb2f706371a74fbe03f8b025e6bbb6ab6e96..78c113504642de4cf9b9701dfc1990428393a95d
--- a/tests/acl.py
+++ b/tests/acl.py
@@ -189,9 +189,14 @@
 expect(admin.command("ACL", "SETUSER", "bad-rw", "%R~cache:*"),
        "ERR Error in ACL SETUSER modifier '%R~cache:*': Read/write key patterns are not supported until command key specifications are available",
        "%R rule rejected")
+# Redis 7.4 rejects user flags inside selectors with "Syntax error". TomoKV rejects
+# all selectors until enforcement exists, using the same SETUSER modifier-error grammar.
 expect(admin.command("ACL", "SETUSER", "bad-selector", "(on +get)"),
-       "ERR Error in ACL SETUSER modifier '(on +get)': Syntax error",
+       "ERR Error in ACL SETUSER modifier '(on +get)': " +
+       ("ACL selectors are not supported" if is_tomokv else "Syntax error"),
        "invalid selector rejected")
+expect(admin.command("ACL", "GETUSER", "bad-selector"), None,
+       "rejected selector creates no user")
 expect(admin.command("ACL", "SETUSER", "bad-firstarg", "+select|0"),
        "ERR Error in ACL SETUSER modifier '+select|0': Allowing first-arg of a subcommand is not supported",
        "first-arg rule rejected")
@@ -333,8 +338,9 @@
 before_selector = admin.command("ACL", "GETUSER", "alice")
 selector_reply = admin.command("ACL", "SETUSER", "alice", "(~persist:* +get)")
 if is_tomokv:
-    if not isinstance(selector_reply, RespError) or "ACL selectors are not supported" not in str(selector_reply):
-        raise AssertionError("selector persistence setup must be rejected: %r" % selector_reply)
+    expect(selector_reply,
+           "ERR Error in ACL SETUSER modifier '(~persist:* +get)': ACL selectors are not supported",
+           "selector persistence setup rejected")
     expect(admin.command("ACL", "GETUSER", "alice"), before_selector,
            "rejected selector preserves the user before SAVE")
 else:

tokens used
63,676
The server already matched Redis 7.4’s modifier-error grammar. Corrected the stale test expectation while preserving explicit selector rejection.

| Item | File | Test result | Commit |
|---|---|---|---|
| ACL gate failure | [tests/acl.py](/home/user/Projects/cx-deadconf-fix/tests/acl.py:192) | FAIL before; PASS after in both atomic modes | `5cd9ed1f8` |

Runs used cores 112–127, port 10390, shards 16, ratio 6:2. Servers terminated and reaped by PID. Worktree clean.

CX-deadconf-fix-DONE
