# Lane clockcut

## clockcut

Worktree `/home/user/Projects/cx-clockcut`, branch `cx-clockcut`, base `origin/cpp`
**8656f9fa924fc06aa128504fca8aa99436aa9e41**. Nothing pushed. A first coding agent wrote the
reproduction, the fix and the budget commit and was then stopped by its provider; this lane
re-verified that work, finished every step and added the optional NT-new-7 commit.

| Commit | What it changes |
|---|---|
| `e6f872f03` | `tests/ntnew4_clock.py` (frozen-clock shim plus a one-shot stall right after the executor's realtime read) and `job_ntnew4_live` with three rows; PRE receipts |
| `a0ac6b40a` | **Fix option A** in `src/core/ex_loop.h` (the only production change for NT-new-4) |
| `1d1fba77c` | Makefile: four per-unit `large-unit-insns` budgets re-derived for IO-unit spillover |
| `5cd136502` | **Optional NT-new-7**, separate commit: a key is still live at now == deadline, as in Redis |
| `831ef3b14` | `tests/gate.sh` comment only: DQ/DF +3/+3 for the maintainer |
| `a32e2a1f4` | NT-new-7 follow-up: two boundary-sensitive test fixtures (rltopo unit, notify battery) and the offline readreply mutant pattern |
| `d7d73adf8` | R7 off-path receipt counts the split `exec_batch_prefetched` body the clock refresh keeps out of line |
| last commit | receipts under `docs/clockcut/` and this request |

### Results first

| Question | Answer |
|---|---|
| Fix as landed | `refresh_command_clock()` (the pass-cut body: `cached_now_ms_ = realtime_ms()`, plus `cached_lru_clock_` when maxmemory is on; `ex_loop.h:1731`) runs at the top of `exec_batch_prefetched` right after the `xshard_retries_` deferral return (`ex_loop.h:2330`) and once per task in `drain_tasks_snapshot`'s take lambda (`ex_loop.h:2181`). Every existing pass cut stays (`ex_loop.h:377/536/626`, `rl2s.cc:49`, `reorder.cc:513/676`). |
| PRE (8656f9fa9) on the new rows, through `tests/gate.sh` | **FAIL in all three rows** (2s io_uring, 1s io_uring, 2s epoll): PTTL 1000000 instead of 999950 (50 ms high), GET of an expired key served, EXISTS 1, HPEXPIREAT [1] instead of [2]; non-vacuity checks and the post-release control pass. With the NT-new-7 assertions present, PRE also fails 14/22 of them. |
| POST on the new rows, through `tests/gate.sh` | **PASS 3/3 rows**, 29/29 checks in every leg (7 NT-new-4 + 22 NT-new-7). |
| PAD-A on the new rows | **FAIL 3/3 rows on exactly the four NT-new-4 probes**, NT-new-7 22/22 pass: the POST pass comes from the moved clock read, not from layout. |
| Can the row pass vacuously? | No. A shim that never freezes fails "frozen clock non-vacuity" in all three legs; a shim that never stalls fails "stall non-vacuity" ("window did not open") in all three legs. Both run through the gate job on POST. |
| NT-new-7 (optional) | **Oracle-confirmed.** Redis 7.4.10 under the same frozen clock answers PTTL 0, serves GET/EXISTS/TYPE/KEYS/SCAN/RANDOMKEY at the exact deadline and aborts a WATCH armed at the deadline once it passes (22/22 boundary assertions). PRE fails 14/22; POST passes 22/22 in 2s, 1s and 1s with the read-local lane armed (there an extra witness shows the lane itself served the deadline GET). Implemented in 14 predicates; hash fields unchanged. |
| Cost of the added read (serverless) | **85.5 cycles and 100.5 instructions per executed batch** with maxmemory off, 93.5 and 108.5 with it on; identical in 1s and 2s. Per command: the same at batch size 1, 2.67 cycles and 3.14 instructions at 32. Idle passes add nothing. No throughput claim. |
| Gate accounting | **DQ = +3, DF = +3.** Required counts become **672 quick / 689 full** (headline 669/686). EXPECT lines untouched. |
| Identity (proxy only) | Final vs PRE: 16,089/16,691 bodies equal; 602 changed, all explained: 93 by the clock fix (74 on the executor batch path by design, 19 compiler spillover, one of which NT-new-7 also touches) and 509 more by NT-new-7. Every one of NT-new-7's 510 changed bodies differs **only** in strict/non-strict condition codes; linked symbol tables of POST with and without NT-new-7 are identical and only 165 `.text` bytes differ. |
| Merit (maintainer) | Generic 14 cells (all 1s, including depth-1 GET/SET latency), PRE vs POST and PRE vs PAD-A; four optional 2s cells. |

| Proof (lane prompt step 6) | Result on POST |
|---|---|
| Unchanged `tests/differ_gate.sh`, standard seeds 7/19/20/23 + rotating 21, all 47 suites, atomic 0 and 1, split and armed-fused, **io_uring and epoll** | **1,882/1,882 rows, 0 FAIL**: uring split 475, uring armed 466, epoll split 475, epoll armed 466 (hexpire passes in all 40 of its legs; read-local lane fired in both armed runs; 32-cell mode equivalence ok) |
| Expiry/TTL, hash-TTL, MULTI/EXEC, script and blocking batteries in 2s, 1s and 1s+read-local | all ok through the gate (`feature-split-*`, `feature-armed-*`, `fused-*`, `hexpread`, `scriptfix`, `script_bounds`, `notify`, `dump_restore`; section 3) |
| `perfex_checks` (`perfex_units`, `perfex_live`) | 2/2 and 2/2 |
| `python3 tests/gates_test.py` | 67/67 OK (plus the nested 14) |
| `make all` + every `job_production_units` target, `make -q` | 36/36 fresh |
| Optional R3: hexpire differential legs with a busy loop on each executor CPU | **PRE 7/144 legs fail, POST 0/144** (all seven: target HPTTL whose cut is 1-2 ms before the client's pre-send clock) |

### 1. Re-verification of the committed work

**Anchors.** The anchors the fix and the rows depend on were re-checked in a clean
`git archive 8656f9fa9` tree (`build/clockcut/pre-clean`): the pass cut `ex_loop.h:626`, the drain at
667, the sweep at 726, `exec_batch_prefetched` at 2314, the install at 2464, the fused cut at 377,
the snapshot take lambda at 2172-2176, `Shard::set_cached_now_ms` at `shard.h:114-118`,
`deadline_elapsed` (`at <= now_ms`) at `flatstore.h:1466-1469`; Redis 7.4.10 `call_timer = ustime()`
at `server.c:3558-3559` and `keyIsExpired`'s `now > when` at `db.c:1941`, all as the investigation
states. The first agent's resolution of all 129 explicit anchors is `docs/clockcut/anchors.json.gz`.

**The fix against option A.** The refresh sits after the deferral return, so a deferred batch keeps
its tasks for `service_ordered_deferred` (whose tasks were dequeued before that later pass's own
cut). Callers covered: `drain_tasks` (2s owner, fused cross-thread tasks, RL2S owners, the frozen
drain, `sweep()`), `drain_tasks_read_local_interleaved` (fused armed lane), the R7 scheduler
(`reorder.cc:69`) and the slowlog arm (`exec_batch_timed` reads `cached_now_ms_` after the refresh).
`drain_tasks_snapshot` executes per task without `exec_batch`, hence its per-task refresh. Tasks
serviced from `xshard_retries_`, `atomic_deferred_`, `multi_retries_` and `stale_tasks_` were all
dequeued in an earlier pass, so the current pass cut already follows their arrival.

| Invariant (lane prompt) | Holds because |
|---|---|
| One time per command | The refresh runs only between batches, never inside `execute()`. |
| MULTI/EXEC/WATCH and cross-shard pins | Untouched: `PinnedNowMs` from the IO stamps (`multi.inc:1845/2084`, `scatter_engine.inc:2018/2740`) still overrides the member per fragment. |
| Frozen script time | A single-shard EVAL is one task with one install; cross-shard scripts keep the prepare stamp. |
| Non-decreasing time per executor | Every refresh reads the realtime clock after the previous cut or refresh on the same thread; the next pass cut is later again. Wall-clock steps behave exactly as in PRE. |
| Read-local lanes | Their own pass cuts are unchanged (reads are parsed before them). Lane reads that run after an owner batch in the same pass inherit the newer member, never an older one. |
| Layouts | No `Op`/`Client`/`ThreadCtx`/`Shard`/`FlatStore`/`Rob<64>`/`AtomicEntry`/`Config` change; the build's footprint asserts (336/1984/1408/1440/944/192/144/624) pass. |

Not closed by design: two pipelined commands on one connection that go to two different owners can
still see times in either order (each is at or after its own arrival). Only option C (dispatch-time
stamps in `Op`) closes that; it changes the time model and the `Op` layout, so it is the owner's
decision and was not implemented.

**The reproduction against vacuity.** The shim (`tests/ntnew4_clock.py`) reads the frozen value
first and then holds the first realtime read of every target CPU after arming, exactly as if the
executor were preempted right after a successful vDSO read. The row requires: the exact frozen
PTTL (1000000) before arming; `stalled` equal to the number of target executors within one second
("window did not open" otherwise); no shim timeout; and a post-release control PTTL at T1 on every
binary. The 1s leg resolves the probe connection's thread from `LBSIGNALS` client deltas and picks
keys on a different owner, so the probes are cross-thread inbox tasks. Both mutant shims above
fail the row at their non-vacuity assertion.

### 2. Step results, PRE vs POST

**Step 1, reproduction (R1), through `tests/gate.sh` job `ntnew4_live`:**

| Leg (row) | Probe | PRE 8656f9fa9 | POST | PAD-A |
|---|---|---|---|---|
| all three | frozen clock non-vacuity (PTTL a) | 1000000, pass | 1000000, pass | 1000000, pass |
| all three | stall non-vacuity (held executors) | 2 / 1 / 2 of 2 / 1 / 2, pass | same, pass | same, pass |
| all three | PTTL a after T1 (expect 999950) | **1000000: FAIL, 50 ms high** | 999950 | **1000000: FAIL** |
| all three | GET b, deadline T0+20 < T1 (expect nil) | **"v": FAIL, served** | nil | **"v": FAIL** |
| all three | EXISTS b (expect 0) | **1: FAIL** | 0 | **1: FAIL** |
| all three | HPEXPIREAT h T0+30 (expect [2]) | **[1]: FAIL, set instead of delete** | [2] | **[1]: FAIL** |
| all three | post-release control PTTL (expect 999950) | 999950, pass | 999950, pass | 999950, pass |
| all three | NT-new-7 exact-deadline assertions | 8/22 pass, **14 FAIL** | 22/22 pass | 22/22 pass |

R3 (CPU hog on the EX cores during hexpire differential legs), **done:** `docs/clockcut/r3.sh` runs
the unchanged `tests/differ_gate.sh` as a focused proof (suite `hexpire`, split 6:2, atomic 0 and 1,
seeds 7/19/20/23 plus 101-104, then 101-160) with one busy loop pinned to each executor CPU (70,
71) for the whole run. **PRE: 1/16 and 6/128 legs fail (7/144); POST: 0/16 and 0/128.** Every PRE
failure is the NT-new-4 signature on the target only: HPTTL implies a server "now" 1-2 ms before
the client read its clock to send the chunk (`final/r3/*-pre-hexpire-*.txt`). Without a hog the
investigation counted about one failing leg in 230.

**Step 2, fix:** option A as above; option C not implemented.

**Step 3, cost of the added read** (`docs/clockcut/cost.cc`, built by `cost-build.py` from a copy of
`ex_loop.h` with only the access label changed; it calls the production `refresh_command_clock()`;
no server, ring, socket or workload). CPU 64, user-mode hardware counters, 21 alternating
with/without pairs of 1,000,000 batches each; medians:

| Thread mode | Batch size | maxmemory | Added cycles per batch | Added instructions per batch | Added cycles per command | Added instructions per command |
|---|---:|---|---:|---:|---:|---:|
| 2s | 1 | off | 85.53 | 100.50 | 85.53 | 100.50 |
| 1s | 1 | off | 85.53 | 100.50 | 85.53 | 100.50 |
| 2s | 32 | off | 85.53 | 100.50 | 2.67 | 3.14 |
| 1s | 32 | off | 85.53 | 100.50 | 2.67 | 3.14 |
| 2s | 1 | on | 93.53 | 108.50 | 93.53 | 108.50 |
| 1s | 1 | on | 93.53 | 108.50 | 93.53 | 108.50 |
| 2s | 32 | on | 93.53 | 108.50 | 2.92 | 3.39 |
| 1s | 32 | on | 93.53 | 108.50 | 2.92 | 3.39 |

All 21 samples per cell lie within ±0.05 cycles of the median (`docs/clockcut/cost.jsonl`). The
per-command columns divide by the batch size; they are not end-to-end measurements and make no
throughput or latency claim.

**Step 4, gate rows:** see section 3.

**Step 5, NT-new-7 (optional, oracle-confirmed, commit `5cd136502`).** `tests/ntnew4_clock.py`'s
`boundary` action runs unchanged against both servers; its shim also freezes `gettimeofday()`
(Redis's `ustime()`). Oracle receipt: `docs/clockcut/nt7/oracle-redis74.log` (Redis sha256
`ac08d444…09b`, 22/22). The same assertions run inside every `ntnew4_live` leg.

| Boundary assertion (now == deadline unless noted) | Redis 7.4.10 | PRE 2s / 1s / 1s+RL | POST 2s / 1s / 1s+RL |
|---|---|---|---|
| PTTL, TTL; PEXPIRETIME | 0, 0; deadline | -2, -2; -2 | 0, 0; deadline |
| GET, EXISTS, TYPE | "v", 1, string | nil, 0, none | "v", 1, string |
| read-local lane served that GET (1s+RL only) | n/a | no (Expired fallback) | yes |
| relative PX 10 and PEXPIREAT-armed keys: PTTL | 0, 0 | -2, -2 | 0, 0 |
| KEYS and full SCAN list the five live keys | yes | [] | yes |
| WATCH + EXEC within the deadline ms | ["v"] | [nil] | ["v"] |
| SET PXAT now: EXISTS | 1 | 0 | 1 |
| PEXPIREAT now / GETEX PXAT now still delete | 1 then 0 / "v" then 0 | same | same |
| WATCH armed at the deadline, EXEC 1 ms later | nil (aborted) | [nil] (not aborted) | nil (aborted) |
| 1 ms past: PTTL, GET, KEYS, SET-at-now key | -2, nil, [], 0 | same | same |
| RANDOMKEY with only volatile keys: at / 1 ms past | a key / nil | nil / nil | a key / nil |

Predicates changed (every one, each now "expired iff now > deadline"):

| Site | Covers |
|---|---|
| `FlatStore::deadline_elapsed` `flatstore.h:1468` | lazy-expiry notifications, insert/erase expired accounting, SCAN/KEYS (`scan_visit`), RANDOMKEY (`random_live`), eviction notification, snapshot-capture cut filters |
| `FlatStore::live_or_expire` `flatstore.h:2648` | every key lookup (`find`, `find_without_touch`, random walk) |
| `FlatStore::active_expire` `flatstore.h:1586` | active expiry |
| `FlatStore::watch_deadline` `flatstore.h:1478` | WATCH capture; GEO*STORE previous-destination check |
| `atomic_live_value` `flatstore_atomic.inc:1242` | atomic MVCC resolver |
| `prepare_captured_local_mget` `ex_loop.h:1111`, `prepare_local_read` `ex_loop.h:1208` | read-local lane MGET and GET probes (1s and RL2S) |
| `watch_validate_and_reserve` `multi.inc:2566`, `watch_database_swap` `multi.inc:2691` | EXEC and SWAPDB WATCH expiry checks |
| SET elapsed-deadline shortcut `t_string.cc:476`, `t_string.cc:525`, `l4prebuild.cc:97` | SET PXAT/EXAT/KEEPTTL at now == deadline stores a key that stays live for that ms (Redis `setGenericCommand` never deletes) |
| `snapshot_load_shard` `snapshot.cc:1110`, `aof_load_shard` `aof.cc:3098` | load filters (Redis `rdbLoad`: `expiretime < now`) |

Kept on purpose: EXPIRE/EXPIREAT/PEXPIREAT `when <= now` deletes (`t_string.cc:1332`), GETEX
EXAT/PXAT (`t_string.cc:584`) and RESTORE ABSTTL (`serialize.cc:1016`), all Redis
`checkAlreadyExpired`; positive-TTL-only samplers (`storesize.cc:82`, INFO avg_ttl), as Redis's
`ttl > 0`; the active-expiry lag metric (`flatstore.h:1430`). **Hash fields are unchanged.** The
oracle shows Redis is itself inconsistent at the field's exact millisecond: a listpack hash answers
HPTTL -2 but HGET still serves the field and HLEN counts it; a hashtable hash answers HPTTL 0 and
serves it; TomoKV (PRE and POST) treats the field as expired for all of them. NT-new-7 moves no
source line (`flatstore.h` embeds `__LINE__` in a release assert inlined into every insert). `tests/edgetime.py`'s
`wait_deadline` now waits until the server clock is past the deadline (`<=` instead of `<`); its
assertions are unchanged. Without that, an EXEC landing in the deadline millisecond would see the
key live, as Redis would.

**Step 6, proofs:** see section 3.

**Step 7, identity:** see section 4.

### 3. Gate rows and proof batteries

All runs use CPUs 64-79 only (builds `-j16`; servers 64-71; Redis 7.4 on 72; clients 73-79) and
ports 24800-24899. The gate planner demands sixteen physical cores, so the gate commands declare
load 72-79 and the lane adapter `build/clockcut/bin/taskset` narrows exactly that mask to 73-79 at
execution, keeping 72 free; jobs, arguments, assertions and results are unchanged. Invocation:
`GATE_ONLY_JOBS='<jobs>' REDIS74_ROOT=/home/user/Projects/redis bash tests/gate.sh quick
--server-cores 64-71 --load-cores 72-79 --load-smt '' --ports 24800-24899
[--candidate-binary <PRE or PAD-A>]`; POST is built by the gate's own release job.

**New rows** (`ntnew4_live_leg` and `job_ntnew4_live`, `tests/gate.sh:1482-1508`, `row_begin` at
1498 (2s, 1s loop) and 1504 (2s epoll), collected at 3913, before the quick-tier exit at 4087):

| Row | PRE (`--candidate-binary` PRE) | POST (gate's own release build) | PAD-A |
|---|---|---|---|
| NT-new-4 command clock after dequeue (2s) | FAIL (4/4 stale, 14/22 NT-new-7) | ok (29/29) | FAIL (4/4 stale; NT-new-7 22/22) |
| NT-new-4 command clock after dequeue (1s) | FAIL (same) | ok (29/29) | FAIL (same) |
| NT-new-4 command clock after dequeue (2s, epoll) | FAIL (same) | ok (29/29) | FAIL (same) |
| same rows, POST with a shim that never freezes | — | FAIL, "frozen realtime window did not open" in all three | — |
| same rows, POST with a shim that never stalls | — | FAIL, "window did not open" (0 of 2/1/2 held) in all three | — |

The first agent's PRE receipts with the original test (before the NT-new-7 assertions existed) are
kept at the top of `docs/clockcut/` (`pre-live.*`, `pre-*-uring.log`, `pre-2s-epoll.log`) and show
the same four failures. Final receipts: `docs/clockcut/final/{post,pre,pad}-ntnew4*`,
`final/no-{freeze,stall}*`.

**DQ/DF:** three rows, all before the quick-tier exit: **DQ = +3, DF = +3**, so
`EXPECT_QUICK` 669 → **672** and `EXPECT_FULL` 686 → **689**. Both lines are unchanged in this
branch (only a comment above them, commit `831ef3b14`). **Label fixture against the source**
(`tests/gate_ledger_fixture.py`): PRE tree 686 = 686 agree; this branch refuses with source 689,
fixture 686, EXPECT 686 and exactly the three new labels missing, no extra label. The fixture is
left to the maintainer. Labels to add (after `perfex TTL sampler beat (2s)`):
`NT-new-4 command clock after dequeue (2s)`, `NT-new-4 command clock after dequeue (1s)`,
`NT-new-4 command clock after dequeue (2s, epoll)`. Because `gate_receipt.py --self-test` validates
that fixture, the `abba_selftest` row fails in this branch until then. In a throwaway copy of HEAD
with only those landing edits applied (EXPECT 672/689 and the three labels), the fixture check
reports "689 source-declared rows agree" and the **`abba_selftest` job passes through
`tests/gate.sh`** (`final/landing-sim-abba.*`), including its nested `gates_test.py`.

**Proof run: 51 gate jobs on POST through the job interface** (`final/post-proof.*`): 486 rows,
**481 ok, 5 FAIL**, then the three affected jobs rerun after the fixes below (`final/post-rerun.*`):
**17/17 ok**.

| Job(s) | Rows ok / total | Covers |
|---|---|---|
| `feature-split-0`, `feature-split-1` | 34/34, 34/34 | 2s, atomic 0/1: s6 (expiry/TTL), edgetime, expwide, hexpire (hash TTL), multi_exec, blocking, blockmulti, lua_scripting, scriptsurf, dumprestore, tracking, streams, … |
| `feature-armed-0`, `feature-armed-1` | 35/35, 35/35 | the same 33 batteries on 1s with the read-local lane armed |
| `fused-0`, `fused-1` | 7/7, 7/7 | 1s: s6, multi_exec, edgeproto, atomfix, spinprobe, shutdown |
| `hexpread`, `script_bounds`, `scriptfix`, `dump_restore` | 8/8, 2/2, 8/8, 3/3 | hash-field TTL reads 1s/2s; cross-shard/scripts; DUMP/RESTORE |
| `notify` | 5/6 → **6/6** after fix | MULTI/blocking/pubsub feature batteries and keyspace notifications |
| `atomic_batteries`, `release_batteries`, `debug-0`, `debug-1` | 4/4, 8/8, 14/14, 14/14 | atomic torn/RYOW/hazards, torture, RYOW, ACL, debug toggles |
| `snapshot-epoll`, `snapshot-uring`, `aof-epoll`, `aof-uring` | 16/16, 16/16, 54/54, 54/54 | persistence and load filters (both changed by NT-new-7) |
| `multidb-{1s,2s}-{0,1}-{0,1}` (8 jobs) | 3/3 each | SWAPDB/WATCH (`watch_database_swap` changed) |
| `perfex_units`, `perfex_live`, `ntnew4_live` | 2/2, 2/2, 3/3 | the neighbouring frozen-clock rows and the new rows |
| `exbatch_units`, `exbatch_live`, `reorder_sync`, `reorder_engagement` | 3/3, 2/2, 1/1, 1/1 | executor batch path and R7 (both call `exec_batch_prefetched`) |
| `reorder_identity` | 0/1 → **1/1** after fix | R7 FIFO-twin off-path byte identity |
| `core_units` | 7/9 → **9/9** after fix | core concurrency (TSAN) and read-local topology units |
| `config_unit`, `flip_unit`, `filter_unit`, `ring_unit`, `storage_units`, `flipfix_units`, `lbplanner_units`, `persistfix_units`, `wb_rule_units`, `wbland_units`, `splitlocal_units`, `atomic_units`, `netcmd_units`, `wait_units` | 2, 1, 1, 3, 13, 2, 2, 1, 4, 2, 1, 27, 16, 2 — all ok | the serverless unit jobs that compile the changed headers |
| `abba_selftest` | 0/1 (fixture, see above) → 1/1 in the landing copy | ABBA/gate self-tests |

The four fixed failures were boundary assumptions, not defects, and are fixed in the tests (commits
`a32e2a1f4`, `d7d73adf8`):

* `read-local topology demotion (1s/2s)`: the rltopo unit's "expired" read-local fixture used a
  deadline equal to its clock (1000 at now 1000). Now 999; the expected Expired fallback is
  unchanged and still holds on PRE. The offline `tools/readreply_proof.py` mutant pattern follows
  the new `<` predicate.
* `keyspace notification battery`: its lazy-expiry cell waited until server TIME reached the
  deadline, then expected GET to reap. It now waits until TIME is past it. Unchanged assertions;
  the updated battery passes on PRE too (`final/pre-notify.*`).
* `R7 FIFO twin off-path identity`: the clock refresh makes GCC keep
  `ExLoopT<false>::exec_batch_prefetched<false>` out of line in both runtimes (PRE inlined it into
  `drain_tasks`), so the off-path inventory is 147 instead of 146 per runtime. The receipt now
  requires that exact body in both arms; every off-path body still compares byte for byte, and
  PRE vs POST differ in no other inventory entry. The same out-of-line body is in PAD-A.

`python3 tests/gates_test.py` on this branch: **67/67 OK** plus the nested 14 persistence tests
(`final/gates-test.log`). `make all` and every `job_production_units` target: built by the gate
job, and **36/36 `make -q` checks return 0** (`all`, 33 unit targets, both `mdbqsbr-live-arms`
binaries through their own flags; `final/production-freshness.tsv`). The server build has no
warnings; the unit builds keep the 13 pre-existing allocator-mismatch warnings in
`atomic_survivors_unit.cc`/`lbplanner_unit.cc` and one jobserver notice.

**Differential matrix** (`docs/clockcut/differ.sh`: the unchanged `tests/differ_gate.sh` with its
standard seeds 7/19/20/23 plus rotating seed 21, 47 suites, atomic 0 and 1, oracle Redis 7.4.10 on
CPU 72; epoll is selected only by a wrapper that execs `build/tomokv --net-io epoll`, confirmed by
the target banner): **uring split 475/475, uring armed-fused 466/466, epoll split 475/475, epoll
armed-fused 466/466, 0 FAIL**, no tolerance change. `hexpire` (with its deadline-bounded HPTTL
checks) passes in all 40 legs; the armed runs prove the read-local lane fired (1,256-1,257 hits at
peak); mode equivalence passes all 32 execution/knob combinations in each run.
`final/differ/status.tsv`, `final/differ/*.log.gz`.

### 4. Identity inventory (proxy; the merit run decides)

Tool: `tools/ccfix_audit.py` (normalized emitted bodies of every production object, both
namespaces) against PRE, plus `docs/clockcut/cc_classify.py` for the instruction-level kind.

| Comparison | Bodies equal | Changed | Command handlers equal | Selected hot bodies equal |
|---|---|---|---|---|
| Clean `git archive 8656f9fa9` rebuild vs the PRE arm (provenance) | 16,683 / 16,683 | 0 | 1,211 / 1,211 | 1,218 / 1,218 |
| Clock fix vs PRE, before the budget trials (first agent) | 16,587 / 16,694 | 107 | 1,211 / 1,211 | 1,148 / 1,224 |
| Clock fix (`1d1fba77c`) vs PRE, selected budgets | 16,598 / 16,691 | 93 | 1,211 / 1,211 | 1,149 / 1,224 |
| NT-new-7 (`5cd136502`) vs clock fix | 16,178 / 16,688 | 510, **all condition-code-only** | 1,190 / 1,211 | 958 / 1,222 |
| **Final POST vs PRE** | **16,089 / 16,691** | **602** | **1,190 / 1,211** | **885 / 1,224** |

Every changed body with its reason: `docs/clockcut/identity/total-changed-bodies.json.gz`
(602 rows; categories clockcut 92, NT-new-7 509, both 1 — the db0 `scan_home` lb lambda; none unexplained).

* **Clock fix, by design (74 bodies):** `exec_batch_prefetched` (8 copies: the refresh and
  its register allocation), `drain_tasks_snapshot` and its `ThreadCtx::drain_tasks[_unmasked]`
  instantiations (20: the per-task refresh), and 46 callers that inline those bodies:
  `ThreadCtx::drain_tasks*`/`drain_task_producer_chunks` lambdas, `ExLoopT::run`, `sweep`,
  `fused_pass_impl`, `snapshot_control_pass`, R7 `ExReorderQueues::submit`/`ShadowReorderQueues::submit`.
* **Clock fix, compiler spillover in unedited bodies (19, after budgets):** `IoLoop::parse_and_dispatch`
  copies in `src/core/rl2s.o` (6 incl. clones) and `db0/src/core/reorder.o` (2) plus
  `r7_parse_and_dispatch` (db0), `adopt_client`/`r7_adopt_client` (src reorder), `pubsub_deliver_one`,
  `pubsub_shutdown_events`, `pubsub_start_command`, `u64_to_dec` (now inlined), a `hash_key` clone,
  `scan_home` (lb bucket bytes), the WB `serve_impl` lambda, `atomic_prepare_capacity_read_local`.
  Each IO IPA unit grew by 23 instructions; compile-only trials at +0/−18/+23/+64/+128/+256/+384/+512
  chose `src genthread 130212`, `src rl2s 162972`, `db0 genthread 130380`, `db0 reorder 149072`
  (107 → 93 changed, 31 → 19 spillover). Accepted for merit review, never a stop.
  `docs/clockcut/budget-selected.json`, `budgets.py`, `budget-units.json`, `budget-*.json.gz`.
* **NT-new-7 (510 bodies vs the clock fix):** 413 + 97 = 510 `cc-only`: the instructions are identical
  once strict/non-strict condition codes are equated (`jl/jle`, `jg/jge`, `setl/setle`,
  `setg/setge`, …), i.e. only `<` versus `<=` flipped. No size, inlining or layout change: the two
  linked binaries have identical symbol tables (every address and size) and 165 differing `.text`
  bytes. The 21 changed command handlers are all of this kind (SET, SET prebuilt, EXISTS, DEL
  notify, HDEL notify, RESTORE notify, GEO xshard local, SCAN/FLUSH scan_home lambdas, both namespaces).
* `.text`: PRE 7,735,985 bytes; POST and PAD-A 7,741,457 (+5,472, all from the clock fix). In the 2s
  executor GCC no longer inlines `ExLoopT<false>::exec_batch_prefetched<false>` into `drain_tasks`
  (`main.o`: `drain_tasks` 1,467 → 468 bytes, `exec_batch_prefetched` 0 → 1,180, both runtimes): one
  more call per executed batch, by design and present in PAD-A.
* The linked-binary tool (`tools/rlfence_artifacts.py identity`, adapted in
  `identity/linked-identity.py`) reports executable identity false for the clock fix, as expected
  once `.text` grows: 9,203 function entries move (`identity/stage1-linked-identity.*`).

### 5. Binaries (SHA-256) and the PAD

| Arm | Path in this worktree | SHA-256 |
|---|---|---|
| PRE 8656f9fa9 | `build/clockcut/pre/tomokv` | `708c53c42ad9555f617a1deaa238226b72c58f7fe194d72731af9e7f58ddcab3` |
| **POST** (HEAD source, `make -q all` fresh) | `build/tomokv` | `bc0f63619139fdee1b08f7fb3a3e2a47648f2d2f49b5379c9b24f4339ba1fa76` |
| **PAD-A** | `build/clockcut/tomokv-pad-a` | `976255cd77c79e70ad48aab0efcd1c11d8fc73c839327238a4d0b3f7f2e0e106` |
| optional: POST without NT-new-7 (`1d1fba77c`) | `build/clockcut/stage1/tomokv` | `1ad9e39198b9f928e531f667a3794e25a6d5f7c88050b2c02a8ab80882e75da1` |

PRE provenance: the arm was built from this worktree at 8656f9fa9 before any edit; a clean
`git archive 8656f9fa9` rebuild (`build/clockcut/pre-clean`, sha `d3d1748d…172`, differs only in
DWARF paths) has 16,683/16,683 equal bodies.

**PAD kind: (A), behaviour twin** — PRE clock placement with POST's exact text size and layout.
`docs/clockcut/pad.py` finds all 35 added refresh calls (including inlined copies) through DWARF
inline stacks and turns each five-byte `call clock_gettime` into a jump past the millisecond
arithmetic, the `cached_now_ms_` store and the maxmemory/LRU update. Restoring those 35×5 bytes
reproduces POST exactly (sections, symbols, every other byte; `pad.json`). `pad_liveness.py` walks
every path from each landing point and finds no read of a skipped register or of the skipped flags
(`pad-liveness.json`: 0 failures; the 66 call-site notes are callees whose arity excludes the listed
registers). PAD-A keeps NT-new-7's condition codes, which no TTL-free generic cell executes (the
TTL checks short-circuit on `expire < 0` / no TTL slot first). It reproduces exactly the four PRE
NT-new-4 failures in all three rows.

### 6. Merit request (maintainer)

Run the **generic 14 cells** in `docs/clockcut/merit-cells.txt` (verbatim copy of
`docs/lbplanner/generic-cells.txt`, sha256 `ac371976…`; all 1s; they include `d1g_l0` and `d1s_l0`,
the depth-1 GET/SET latency cells where one added read per batch is a whole read per command).
Arms: **PRE vs POST** and **PRE vs PAD-A** (plus the usual PRE/PRE null), with the gate's own
quiet-box instrument and its matched-load rules. Report rate or p1 latency, cycles/op, instr/op
and IPC per cell; no averaging away a losing cell. Reading: a cell where POST loses and PAD-A does
not is the clock read's cost; one where both lose is placement or inlining, which PAD-A shares with
POST (including the split `exec_batch_prefetched<false>` body that is now out of line).

Optional targeted cells (the change sits on the 2s executor batch path):
`docs/clockcut/merit-cells-2s.txt` — 2s GET/SET at p1 (latency) and p32 (rate); parsed with no
pending pins (`merit-cells-2s.json`). If NT-new-7 should be judged separately, the clock-fix-only
binary above is the extra arm.

### 7. NOT RUN, with reasons

| Item | Why it was not run |
|---|---|
| Performance benchmarks, memtier or any load generator, ABBA/null/merit campaigns | Maintainer-owned; this lane's authorization covers correctness only. No throughput, latency, cycles/op or IPC claim is made. |
| `tests/gate.sh iteration` / push / full tier, and gate jobs outside the 51 selected (for example `flip`, `flip_saturated`, `evict-*`, `feature-cell-*`, `netio-*`, `lb-stationary-*`, `respresume-*`, `tls`, `aclfix`, `auth`, `bplus`, `sort`, `aof_frame`, `aoforder`, `climonfix`, `racefix_*`, `clientfix`, `netcap`, `respcompat`, `readonly`, `efficiency`, `atomic_floor`, `wb_policy`, `ntfix_input`; full tier `asan_batteries`, `replyoff`, `zc`, `rlcache`, `globcase`) | The full iteration is the maintainer's. The selection covers every job whose test files this lane changed, every serverless unit job that compiles the changed headers, and the requested expiry, hash-TTL, MULTI/EXEC, script, blocking, persistence and SWAPDB batteries in both modes. The one other TTL-timing battery, `tests/flip_ttl.py` (job `flip`), was read: it already treats a live read at the deadline millisecond as an invalid cohort, so it does not depend on the boundary. |
| `tools/readreply_proof.py` (offline read-local mutant proof whose pattern this lane updated) | The tool asserts it runs on CPUs 112-127, the maintainer's cores. Its `rltopo` contract runs in `core_units` (9/9). |
| PAD kind (B), inverse control | The candidate grows `.text` by 5,472 bytes; an inverse control would have to remove bytes from POST, which padding cannot do. PAD-A carries POST's exact layout. |
| Option C (dispatch-time stamp per `Op`) | Changes the time model and the `Op` layout: owner decision (lane prompt). |
| Hash-field exact-deadline change | Out of scope by instruction; Redis is encoding-dependent there (documented above). |
| Linked-binary identity tool on the final POST | NT-new-7 leaves every symbol address and size unchanged versus the clock-fix binary (165 differing `.text` bytes); the clock-fix run is recorded. |

### 8. Receipts (`docs/clockcut/`, all small text or gzip; no binaries or objects)

| Path | Content |
|---|---|
| `pre-live.*`, `pre-{2s,1s}-uring.log`, `pre-2s-epoll.log`, `pre.sha256`, `pre-perfex-selftest.*` | first agent's PRE reproduction with the original test, and PRE perfex rows through the gate |
| `final/{post,pre,pad}-ntnew4*`, `final/no-{freeze,stall}*` | the three new rows on POST, PRE, PAD-A and with both mutant shims (ledgers, gate logs, per-leg JSON observations) |
| `final/post-proof.*`, `final/post-rerun.*`, `final/pre-notify.*`, `final/landing-sim-abba.*` | 51-job proof run, the rerun after the fixture fixes, notify on PRE, abba_selftest with the landing bookkeeping |
| `final/gates-test.log`, `final/production-freshness.tsv` | `gates_test.py` and the 36 `make -q` checks |
| `final/differ/` | status and per-geometry logs of the four differential matrices |
| `final/r3/` | R3 status, seeds, logs and the seven PRE failure records |
| `nt7/` | Redis 7.4 oracle receipt, PRE and POST `boundary` runs (2s, 1s, 1s+RL) and the POST no-freeze control |
| `identity/` | summaries and the 602-body reason table; NT-new-7 classification; PRE provenance; stage-1 linked identity |
| `budgets.py`, `budget-*.json*` | per-unit budget trials and the selection |
| `cost.cc`, `cost-build.py`, `cost.jsonl` | serverless cost harness and samples |
| `pad.py`, `pad.json`, `pad_liveness.py`, `pad-liveness.json`, `text-layout.json`, `binaries.sha256` | PAD-A construction, verification and layout facts |
| `boundary_oracle.sh`, `differ.sh`, `r3.sh`, `cc-control.py`, `cc_classify.py` | the lane's drivers (oracle boundary runs, differential matrix, R3, shim mutants, identity classifier) |
| `merit-cells.txt/.json`, `merit-cells-2s.txt/.json` | merit cells for the maintainer |
| `anchors.json.gz` | the first agent's resolution of the investigation's 129 anchors |
