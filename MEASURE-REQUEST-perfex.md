## perfex

Worktree `/home/user/Projects/cx-perfex`, branch `cx-perfex`; no push.
PRE: `5146b78ee89b64748dd46db970efa8086f653fa0` after the required initial
fetch/merge (already current). Production fixes: `97411ff12`, `43b454f87`,
`8880c47c7`, `3aa525fd9`; compiler budgets: `2da33be5e`.
**Code and focused correctness proof are committed. Performance proof is blocked
by the unchanged quiet screen. This is not a full-gate or merge approval.**

The early, self-contained pfconfirm compatibility commit for perfio is
`d867a1073` (`pfconfirm: runnable on the current tree`), following the requested
merge of `cx-pfconfirm`. Its 28 serverless tests pass. It removes the retired
`--overlap` argv, sets cells to ov=0, pins the PRE headline by default, supplies
`--databases 1` unless srv= overrides it, and shares `--port` with quiet screening.
Caps, verdict rules, workloads and guards remain unchanged.

| Arm | Binary | SHA-256 |
|---|---|---|
| Built PRE | `build/perfex/pre/tomokv` | `bafacf2dc91dc3e16e53724bcd7733f6119be9447636d7d5094b85d1b809e48e` |
| Mainline PRE headline | `/home/user/Projects/bench-bins/tomokv-headline-5146b78ee` | `29637fabb42ed4ac9c5b663572c75aa3ae7f6d2745befbc3134a9c59cb5a01fc` |
| POST | `build/tomokv` | `81b0b26dceaea4d78201fd26b84c3af9929613467549710a53c1915b8e759d54` |
| PAD B | `build/perfex/pad-b/tomokv` | `1e15bc3ef66baf627c2e3fc1410db2d1597059f83872bafa860fa1e799f0dcf7` |

### Findings and rows

| Finding | PRE result (before production edits) | POST | Files / new row |
|---|---|---|---|
| EX4.2 / ST4.2 / PFKEYSPA.1 | At fixed realtime, 16/16 unrelated batches advance avg_ttl in both split and fused | 0/16 unrelated batches advance the sampler in either mode; 128-window mean error 0.306% fused / 1.976% split (limit 10%); all-shard coverage and counts pass | `src/cmd/storesize.cc`, `src/core/ex_loop.h`; `perfex TTL sampler beat (1s)` and `(2s)` |
| EX4.12 | CPU clock reachable on sample_depth(false) in all four linked executor run bodies | All four linked run bodies sample on the beat only; diagnostics remain present | `src/core/ex_loop.h`; `perfex clock binary regression` |
| EX4.13 | All six ordinary linked drain bodies call memset before receiving a task | All six linked drain bodies have no batch zero-fill | `src/core/ex_loop.h`; `perfex batch binary regression` |

PRE failing output is retained in `docs/perfex/pre-{clock,batch,sampler-1s,sampler-2s}.log`.
The sampler regression uses an isolated LD_PRELOAD realtime fixture. A production
PTTL result proves the frozen clock actually opened the window before checking
that unrelated GET batches leave avg_ttl unchanged. Explicit clock steps then
prove refresh with active expiry disabled, accuracy (128 windows within 10% of
the known exact mean), rotating coverage of all shards, exact key/expiry counts,
DBSIZE, and zero avg_ttl after PERSIST. The fixture adds no production hook.
An earlier wall-time fixture was discarded because it could not reliably open
its sub-millisecond window; no tolerance was widened and no case was skipped.

Only the monitoring sample moves to the existing owner beat: inspect at most
eight owned shards and sample at most one volatile shard (16 index slots) per
beat. Active expiry, index maintenance, batch count/bytes/expires/evicted and
hash-field TTL attention publication remain unchanged. The sampler respects
owner freezes and snapshot blocking, uses cached time, and holds no shard pointer
across ownership changes. Its owner-vector cursor occupies existing padding;
per-store index cursors still travel with their stores. No new shared atomic.

The CPU-time sample now shares sample_depth's existing 100 us beat. Consumers:
`src/cmd/lbsignals.cc` copies it to per-thread DEBUG LBSIGNALS rows and sums role
rollups; `src/core/shutdown_report.h` snapshots and emits final text/JSON reports.
The placement/demand model in `src/core/server.h` uses busy/idle, not cpu_ns.
These consumers retain monotone cumulative diagnostics, now sampled like IO and
fused IO (not a per-pass value).
External consumers are `tests/_lib.py`'s LBSIGNALS parser, the live checks in
`tests/lbsignals.py`, `tests/abba_saturation.py` and its saturation controls
(CPU deltas/lower-bound occupancy), and `tools/lb_episodes.py` (occupancy deltas).
Their field names, units and cumulative-counter meaning are unchanged.

The first POST placement exposed stale cached wall time in split HPTTL replies:
the unchanged deadline checker failed all eight hexpire legs, while PRE passed
8/8. Moving the one existing wall-clock read after the sampled CPU-clock syscall
made the diagnostic link pass 8/8; no tolerance changed. The final default build
independently passes the complete requested matrix: 24/24 split legs and
26/26 armed-fused outcomes (24 legs plus two arming witnesses). See
`docs/perfex/clock-order-proof.json` and `docs/perfex/final/differ-*.log`.

Task itself is unchanged. [C++20 implicit-lifetime byte-array storage](https://www.open-std.org/jtc1/sc22/wg21/docs/papers/2020/p0593r6.html)
and construct_at copy each received slot; existing batch lengths gate every read. The ordinary and
read-local interleaved drains reuse trivially destructible slots. The separate
`Task posts[256]` arrays in `src/cmd/scatter_engine.inc` (AT4.7), and the opt-in R7
queue's scratch array, remain outside this change.

### Counts and ledger

Merged base: EXPECT_QUICK=511, EXPECT_FULL=528. The two binary rows in
job_perfex_units and the two live rows in job_perfex_live are collected at
`tests/gate.sh:3296` and `:3297`, before the quick-tier block at `:3452`
(and its exit at `:3456`): **DQ=4, DF=4; 511+4=515, 528+4=532**. Arithmetic is documented
above the unchanged constants. The source inventory and label fixture both have
532 rows with no missing/extra labels. The raw ledger validator necessarily
refuses EXPECT_FULL=528 until the maintainer changes the constant. Its refusal
is retained; neither the constants nor the checker are weakened.

### Merit commands (mainline schedules the quiet box)

The full 0-111 commands below are requests, not coding-lane executions. All lane
execution is pinned under taskset -c 112-127; server/listener ports are 25100-25124.

```
PRE=/home/user/Projects/cx-perfex/build/perfex/pre/tomokv
POST=/home/user/Projects/cx-perfex/build/tomokv
REF=/home/user/Projects/bench-bins/tomokv-headline-5146b78ee

# Functional only; both arms must report SMOKE_OK. Choose new output directories.
taskset -c 112-127 docs/pfconfirm/run.sh --smoke --only PFKEYSPA.1 --binary "$PRE" --sha256 "$(sha256sum "$PRE" | cut -d' ' -f1)" --port 25120 --output docs/perfex/pfconfirm-smoke-pre-rerun
taskset -c 112-127 docs/pfconfirm/run.sh --smoke --only PFKEYSPA.1 --binary "$POST" --sha256 "$(sha256sum "$POST" | cut -d' ' -f1)" --port 25120 --output docs/perfex/pfconfirm-smoke-post-rerun

# Full confirmation: PRE CONFIRMED, POST NOT CONFIRMED; preserve all cells/caps/verdict rules.
taskset -c 0-111 docs/pfconfirm/run.sh --only PFKEYSPA.1 --binary "$PRE" --sha256 "$(sha256sum "$PRE" | cut -d' ' -f1)" --port 25000 --output docs/perfex/pfconfirm-full-pre
taskset -c 0-111 docs/pfconfirm/run.sh --only PFKEYSPA.1 --binary "$POST" --sha256 "$(sha256sum "$POST" | cut -d' ' -f1)" --port 25000 --output docs/perfex/pfconfirm-full-post

# Zero main-command regression required in every selected generic cell.
taskset -c 0-111 python3 tests/abbagate.py --cells /tmp/claude-1000/generic_merit_cells.txt --only h05,h06,p8g,p8s,d1g_l0,d1s_l0,d32s_l1,d8s_l1,d32g_l1,x9_32_l1,x9_32_l0,m8g_l0,v1g_l0,d128g_l0 --candidate-binary "$POST" --reference-binary "$REF" --build-reference 0 --server-cores 0-31 --load-cores 32-111 --load-smt '' --ports 25010-25019 --output build/perfex/generic-merit
# Isolate split executor gains at GET/SET p8/p32; unchanged abbagate verdict rules.
taskset -c 0-111 python3 tests/abbagate.py --cells docs/perfex/split-cells.txt --candidate-binary "$POST" --reference-binary "$REF" --build-reference 0 --server-cores 0-31 --load-cores 32-111 --load-smt '' --ports 25020-25029 --output build/perfex/split-merit

# Short executor-only perf stat; 64,000 offered ops/s in both arms, plus idle second.
taskset -c 112-127 python3 docs/perfex/perf_stat.py --binary "$PRE" --sha256 "$(sha256sum "$PRE" | cut -d' ' -f1)" --port 25110 --output docs/perfex/perf-stat-pre-rerun
taskset -c 112-127 python3 docs/perfex/perf_stat.py --binary "$POST" --sha256 "$(sha256sum "$POST" | cut -d' ' -f1)" --port 25110 --output docs/perfex/perf-stat-post-rerun

# TTL behavior, original ttls cell (20M keys); identical population in both arms.
taskset -c 112-127 python3 tests/abbagate.py --cells tests/ttl_cells.txt --only ttls --candidate-binary "$POST" --reference-binary "$PRE" --build-reference 0 --server-cores 112-119 --load-cores 120-127 --load-smt '' --ports 25112-25119 --output docs/perfex/ttl-local-rerun
# Full geometry: compare INFO active_expire_reap_lag_ms_max and expired_keys delta / window_seconds.
taskset -c 0-111 python3 tests/abbagate.py --cells tests/ttl_cells.txt --only ttls --candidate-binary "$POST" --reference-binary "$PRE" --build-reference 0 --server-cores 0-31 --load-cores 32-111 --load-smt '' --ports 25030-25039 --output build/perfex/ttl-full
```

Both generic and split cell files parse with --list-cells; retained JSON is in
`docs/perfex/{generic,split}-cells.json`. Split shapes are explicitly databases 1.
Rate at the same offered load decides merit; cycles/op, instructions/op and IPC
explain it. perf_stat.py retains the PMU/command endpoint envelope, so those short
ratios are diagnostics rather than an ABBA verdict.

**PAD kind B (inverse control): candidate behavior plus padding restoring PRE's
total .text size.** PRE is 7,582,188 bytes; POST is 7,580,604; PAD B adds 1,584
unused NOP bytes. This controls total text size, not every PRE function address
or internal instruction layout. No padding enters the POST binary. Build recipe,
exact link command and digest are in `docs/perfex/pad-b.json`; rebuild with
`taskset -c 112-127 python3 docs/perfex/pad_text.py`. Measure PAD B as a third arm
for the generic/split cells above, replacing `--candidate-binary "$POST"` with
`--candidate-binary "$PWD/build/perfex/pad-b/tomokv"` and choosing new output
directories. POST and PAD B should move together against PRE; a split result
requires investigation before attributing a gain to the mechanisms.

### Smoke and measurement evidence

Every final attempt was **REFUSED before boot** by the unchanged quiet screen,
after this lane's builds, correctness tests and scheduler fixtures had exited.
The first one-second sample already exceeded the 20-second rolling budget;
the monitor did not need to wait the full 20 seconds to reject it.

| Attempt | Selected-core CPU seconds at refusal | Budget | Receipt |
|---|---:|---:|---|
| PFKEYSPA.1 PRE smoke | 16.27 | 0.48 | `docs/perfex/pfconfirm-smoke-pre-final/` |
| PFKEYSPA.1 POST smoke | 16.49 | 0.48 | `docs/perfex/pfconfirm-smoke-post-final/` |
| Executor perf-stat PRE | 16.30 | 0.48 | `docs/perfex/perf-stat-pre/` |
| Executor perf-stat POST | 16.36 | 0.48 | `docs/perfex/perf-stat-post/` |
| TTL ttls ABBA | 16.10 | 0.48 | `docs/perfex/ttl-local/` |

Neither pfconfirm arm reached SMOKE_OK. No PMU window or TTL workload ran, so no
rates, cycle savings, expired_keys rate, or non-regression claim can be reported.
The perf-stat driver is prepared but its post-preflight execution is unverified.
Earlier PRE quiet-screen and parent-affinity refusals remain retained separately.
The TTL driver also reports that the standing null's instrument fingerprint is
stale; mainline needs a current standing null before trusting an ABBA verdict.
No cap, quiet rule, standing null, or verdict rule was altered.

| Shape | PRE cycles/op | POST cycles/op | PRE instructions/op | POST instructions/op | IPC PRE / POST |
|---|---:|---:|---:|---:|---|
| GET p8, 64K offered | N/A | N/A | N/A | N/A | N/A |
| SET p8, 64K offered | N/A | N/A | N/A | N/A | N/A |
| GET p32, 64K offered | N/A | N/A | N/A | N/A | N/A |
| SET p32, 64K offered | N/A | N/A | N/A | N/A | N/A |
| Idle, executor cycles/s | N/A | N/A | — | — | — |

| TTL ttls | PRE | POST |
|---|---|---|
| active_expire_reap_lag_ms_max | Not measured: quiet refusal | Not measured: quiet refusal |
| expired_keys/s | Not measured: quiet refusal | Not measured: quiet refusal |

Mainline must still obtain both SMOKE_OK results, PRE CONFIRMED / POST NOT
CONFIRMED for PFKEYSPA.1, the 14-cell generic null and four split cells (plus PAD B),
and an expiry comparison that does not get worse. The full gate was not run.
Use fresh output directories when rerunning the exact commands above. Actual
attempt argv, status and log paths are retained in `docs/perfex/final/commands.jsonl`;
`summary.json` gives the final result inventory.

### Correctness/build/identity proof

Normal `make -j16 all` passed and `make -q all` confirmed freshness. The required
fetch/merge before this proof remained at origin/cpp `5146b78ee`; the build's
source commit is `2da33be5e`. Source-boundary checks pass, including the shared
counter/channel files, capture/admission and AOF regions, and untouched EXPECT
constants. The final freshness receipt also verifies the three binary digests
and no remaining owned server, load generator or compiler process
(`docs/perfex/final/final-freshness.json`). All 28 job_production_units targets
build and pass their individual make -q checks; mdbqsbr-live-arms builds. Storesize positive/negative controls pass
in both namespaces. Exbatch publication/watch/metadata pass 4/20/8 checks;
wbland clauses pass 83/83. Receipts: `docs/perfex/final/production-units.json`,
`commands.jsonl` and the corresponding logs. The differential matrix passes all
48 requested legs and both read-local arming witnesses. Final LBSIGNALS passes 59 checks in split and 47 in fused (the existing
seven fused inapplicable checks remain reported as skipped). The final scheduler
harness passes 66/66 in 88.49 seconds without this lane's compilers running. The pfconfirm unit suite passes 28/28.
PRE make -j16 BUILD_ROOT=build/perfex/pre all passed. The first two gates_test runs under build contention timed out 14 and 7 scheduler
fixtures; the final run without this lane's compilers passes 66/66. Those failures
remain retained. No scheduler timeout or test outcome was weakened.

The standalone INFO test exposed an immediate-after-SET avg_ttl assumption once
sampling became periodic (split: 1/41 failed, fused: 41/41 passed). It now waits
at most one second for a nonzero estimate, then applies its original range check.
A missing sampler still fails; the dedicated sampler row additionally requires
explicit clock-step progress. The original failure is retained as
`docs/perfex/final/infofix-2s.log`; the bounded-wait reruns pass 41/41 in
both modes (`infofix-beat-{1s,2s}.log`). PAD B passes the clock and batch binary
rows. Gate shell syntax also passes.

The unmodified ttlclean-method checkers retain every difference. The lane classifier
then verifies that all changed bodies in the supplied hot inventory are directly
explained by this change, and that every command handler is identical.

| Identity inventory | Total | Identical | Changed |
|---|---:|---:|---:|
| lbstall tomo | 601 | 594 | 7 |
| lbstall tomo_db0 | 603 | 593 | 10 |
| Combined hot inventory including four executor run bodies | 1,208 | 1,187 | 21 |
| Command handlers | 1,210 | 1,210 | 0 |
| Complete object-body inventory | 16,297 | 16,221 | 76 |

The 21 selected hot changes are ordinary drains/receive lambdas, executor run,
and db0 fused pass/R7 fused pass/sweep callers of the changed drains or owner
maintenance. The complete 76-body list gives each symbol, object, size and reason
in `docs/perfex/final/changed-body-reasons.json`. It includes publish_size, the
monitoring sampler, owner tail, inline copies, and cold cursor initialization.
**25 additional compiler changes lie outside the supplied hot selection**, including
pub/sub, client adoption, a writeback pump instantiation and FlatStore helpers.
They are retained, not described as whole-binary identity. The main-command merit
run remains necessary. Raw byte checkers exit 1 because intended differences are
present; `identity.py` passes with zero unexplained selected hot changes and
1,210/1,210 identical handlers.

DWARF confirms all eight locked sizes (336/1984/1408/1440/944/192/144/624), every
existing member offset in both namespaces, and both executor layouts unchanged.
The new cursor occupies existing padding. See `docs/perfex/final/layouts.json`.
`linked.json` retains section/address differences; PAD B is the size control,
not a claim of identical linked placement.


Focused proof can be rerun in a **new** output directory (never overwrite retained
failures). The stage runs are sequential so this lane does not compile during
live deadline checks or measure during tests:

```sh
taskset -c 112-127 make -j16 all
taskset -c 112-127 python3 docs/perfex/proof.py units --output docs/perfex/reproof
taskset -c 112-127 python3 docs/perfex/proof.py correctness --output docs/perfex/reproof
taskset -c 112-127 python3 docs/perfex/proof.py wiring --output docs/perfex/reproof
```

`units` extracts the exact 28 production targets from gate.sh, builds each,
checks each with make -q, then builds mdbqsbr-live-arms and runs the focused unit
controls. `correctness` runs the four new rows, INFO and LBSIGNALS in both modes,
then the unchanged differential harness with suites edgetime/hexpire/infofix,
seeds 7/19/20/23 and both atomic settings. It pins target 112-119, Redis 7.4 oracle
120, and differential load 121-127; ports 25103/25104. `wiring` retains the raw
ledger refusal until the maintainer updates EXPECT.

## perfex2

Worktree `/home/user/Projects/cx-perfex`, branch `cx-perfex`; no push. Required
`git fetch origin cpp && git merge --no-edit origin/cpp` completed as `04a9a0cce`,
with `origin/cpp` at `991d48f65`. Merge resolution retains the landed wave-1
compiler settings and all correctness rows, then adds perfex's four rows.
The maintainer-owned EXPECT assignments remain exactly origin's 625 / 642.

The old POST (`d8085684f`, binary SHA-256
`81b0b26dceaea4d78201fd26b84c3af9929613467549710a53c1915b8e759d54`) is preserved,
including its object files, under `build/perfex2/previous-post/`.
The direct negative reproduction failed on round 3, atomic 0, with
`measured avg_ttl: got 3591111`; the unchanged predicate requires
`0 < avg_ttl <= 60000` after FLUSHALL and SET PX 60000. The run was stopped
after that witness; the interrupted fourth pair is not counted as a result.
Raw logs are in `docs/perfex2/pre-direct/`. The first complete gate feature
sequence reproduced the same failure at atomic 1 (`avg_ttl=3547376`):
68 passed, one failed; both shutdown-invariant rows passed. See
`docs/perfex2/pre-gate-1/`. The frozen-clock regression independently fails
on the original POST in both modes with `avg_ttl=3599989`, after all of the
old sampler checks pass (`docs/perfex2/pre-rows/`).

Root cause: single-DB `FlatStore::clear()` / `clear_during_snapshot()` skip
`storesize_clear()`, which itself only clears the multi-DB census. The old
single-DB sampled deadline survives FLUSHALL, and the new expiry count attaches
it to the replacement population until the next owner sampler beat. Waiting
only for a nonzero estimate in infofix cannot repair a stale nonzero estimate.

Redis 7.4 maintains an estimate in its active-expiry loop, smoothing fresh
samples and resetting the value when there are no volatile keys; its cold
`emptyDbStructure` path also resets the average and sampling cursor on both
synchronous and asynchronous flush. This does not promise an instantaneous
exact mean after arbitrary TTL mutations. Sources:
[Redis 7.4 expiry](https://github.com/redis/redis/blob/7.4/src/expire.c) and
[Redis 7.4 database clear](https://github.com/redis/redis/blob/7.4/src/db.c).
The locally executed oracle is `/tmp/claude-1000/redis74/src/redis-server`.

The freshness regression extends the existing sampler rows: arm a witnessed
long estimate on every shard, freeze realtime, flush, add one 60-second key,
and reject any inherited long estimate immediately. Advance the clock and
require a positive fresh estimate. Re-arm from fresh state for FLUSHALL,
FLUSHALL ASYNC, FLUSHDB and FLUSHDB ASYNC. Both pre-existing no-batch-sampling
and beat-progress checks remain. No assertion or tolerance in infofix changes.

Rows remain **DQ=+4 / DF=+4** relative to landed wave 1: no new ledger row.
Required totals are **629 quick / 646 full**; only the maintainer changes EXPECT.
Collection is at `tests/gate.sh:3577` and `:3578`, above the quick-tier exit
at `:3743`. The freshness cases extend those existing sampler rows.

The final production change is `93a14e81a` (following `6e234700c` and
`9d94fc5c4`). The two cold single-DB clear paths reset their existing owner-private
sample cursor and atomically clear the sampled deadline. The next millisecond
beat supplies the replacement estimate. The monitoring state definition moves
beside these inline clears; its fields, size, allocation and pointer slot stay
unchanged. Multi-DB census behavior stays unchanged. There is no new work in
ordinary GET/SET, batch publication, INFO, or the sampler.

| Arm | Binary | SHA-256 |
|---|---|---|
| Historical perfex POST, before required wave-1 merge | `build/perfex2/previous-post/tomokv` | `81b0b26dceaea4d78201fd26b84c3af9929613467549710a53c1915b8e759d54` |
| Perfex2 PRE: merged perfex POST, production sources at `04a9a0cce` | `build/perfex2/pre/tomokv` | `081b66cc1d69ae7e6027eedb6d928540d6709828fb2d568c8a24d80c2fe8a2fd` |
| Perfex2 POST: production sources at `93a14e81a` | `build/tomokv` | `e1d6258f0f74ffc5b2bb237bef81bb2a115070dbae1c434d400e2188010cf0c4` |

The final POST passes all four perfex rows and the eight flush-freshness cases
(four forms in each mode): zero immediately, then 59988 ms after explicit beats,
versus historical POST's stale 3599989 ms. Redis 7.4.10 independently passes all
four forms, reporting zero immediately and a fresh value on active expiry.
Receipts: `docs/perfex2/final-rows/` and `docs/perfex2/post-oracle/`.

The complete object-body audit compares the **merged** prior POST against
perfex2: 16,431 / 16,439 bodies equal, 1,208 / 1,208 selected hot bodies equal,
1,210 / 1,211 command handlers equal. Equality preserves every instruction,
member offset, constant and relocation target; only relocation placement is
canonicalized by the unchanged `tools/ccfix_audit.py`. Its raw exit is 1 because
the generic cold-handler allowlist omits FLUSH. `docs/perfex2/identity.py` checks
the complete changed inventory against the following explicit cold functions;
that classifier passes. It neither changes nor suppresses the raw audit.

| Object (all db0) | Changed body | PRE / POST bytes | Reason |
|---|---|---:|---|
| `src/cmd/t_server.o` | `cmd_flush` | 1802 / 1834 | Inlined snapshot-time clear reset |
| `src/cmd/t_server.o` | `FlatStore::clear` | 840 / 856 | Ordinary clear reset |
| `src/cmd/t_server.o` | `command_client_migration_extract` | 608 / 592 | Unedited cold role-migration metadata extraction; compiler allocation |
| `src/cmd/xshard.o` | `FlatStore::clear` | 840 / 856 | Ordinary clear reset |
| `src/persist/aof.o` | `FlatStore::clear` | 840 / 856 | Replay clear reset |
| `src/persist/aof.o` | `AofManager::~AofManager` (two aliases) | 1435 / 1403 each | Unedited cold teardown; compiler inlining |
| `src/persist/aof.o` | `manifest_name` | 1698 / 1698 | Unedited cold manifest-path construction; compiler allocation |

The mandatory historical POST -> wave-1 merge is a separate comparison:
15,286 / 16,485 bodies equal, 983 / 1,216 selected hot bodies equal. Those seven
landed correctness lanes change hot bodies. Claiming literal identity to the
unmerged historical binary would be false. Its full inventory is retained in
`docs/perfex2/merge-identity/`; the perfex2-only inventory is in `identity/`.

Compiler budgets are db0 `t_server.o` 31737 (was 31725) and db0 `xshard.o`
126492 (was 126482). The initial out-of-line reset and first inline build
perturbed unrelated helpers; both failed inventories remain in
`initial-identity/` and `inline-identity/`. The compile-only complete-body trials
in `budget-trials/` selected the final settings. No ordinary helper differences
remain in the final audit.

All layout locks and every inspected field offset remain equal in both
namespaces: Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944,
Rob<64> 192, AtomicEntry 144, Config 624. StoreSizeState stays 24 bytes with the
same three fields. `.text` is exactly 7,645,932 bytes in both merged PRE and POST;
`.rodata`, `.data` and `.bss` also remain equal. See `layouts.json` and
`sections.json`. Perfex2 introduces no layout or total-text-size change and
therefore requests no new PAD arm. The earlier perfex PAD B belongs only to
the historical comparison above.

`make -j16 all` passed. All 29 current `job_production_units` targets build and
pass `make -q`; `mdbqsbr-live-arms` builds and the storesize positive/negative
controls pass. After the last compiler-budget edit, the park control's xshard
object was forcibly rebuilt with 126492 and the controls relinked. The final
36 build/freshness/control commands all exit zero (`final-units/summary.json`).
The superseded unit run's stale-build checks remain recorded in `units/`.

The repeated live campaign is in progress; its final results and the quiet-box
measurement handoff will be recorded here before completion.

The maintainer's performance comparison for this follow-up is merged perfex PRE
against perfex2 POST, using the digests above. This isolates the freshness repair
from the seven-lane merge. Run the gate's unchanged ABBA instrument at its
declared matched loads: the four GET/SET p8/p32 split cells and the existing
14 generic guard cells. Rate decides non-regression in each cell; cycles/op,
instructions/op and IPC explain it. No measured performance claim is made by
the coding lane.

```sh
PERFEX2_PRE=/home/user/Projects/cx-perfex/build/perfex2/pre/tomokv
PERFEX2_POST=/home/user/Projects/cx-perfex/build/tomokv
taskset -c 0-111 python3 tests/abbagate.py --cells docs/perfex/split-cells.txt --candidate-binary "$PERFEX2_POST" --reference-binary "$PERFEX2_PRE" --build-reference 0 --server-cores 0-31 --load-cores 32-111 --load-smt '' --ports 25020-25029 --output build/perfex2/split-merit
taskset -c 0-111 python3 tests/abbagate.py --cells /tmp/claude-1000/generic_merit_cells.txt --only h05,h06,p8g,p8s,d1g_l0,d1s_l0,d32s_l1,d8s_l1,d32g_l1,x9_32_l1,x9_32_l0,m8g_l0,v1g_l0,d128g_l0 --candidate-binary "$PERFEX2_POST" --reference-binary "$PERFEX2_PRE" --build-reference 0 --server-cores 0-31 --load-cores 32-111 --load-smt '' --ports 25010-25019 --output build/perfex2/generic-merit
taskset -c 0-111 docs/pfconfirm/run.sh --only PFKEYSPA.1 --binary "$PERFEX2_POST" --sha256 e1d6258f0f74ffc5b2bb237bef81bb2a115070dbae1c434d400e2188010cf0c4 --port 25000 --output build/perfex2/pfconfirm-full-post
```

The requested full PFKEYSPA.1 POST verdict remains **NOT CONFIRMED** (the TTL
tax must stay absent), using the branch-local tool's unchanged trigger, caps,
quiet screen and verdict rules. These are maintainer commands, not lane
executions. The lane executes only the explicitly requested `--smoke`.

| Follow-up cells | Merged PRE rate / cycles / instructions / IPC | POST rate / cycles / instructions / IPC | Verdict |
|---|---|---|---|
| GET/SET p8/p32, split | Not measured | Not measured | Maintainer ABBA required |
| Fourteen generic guards | Not measured | Not measured | Maintainer ABBA required |
