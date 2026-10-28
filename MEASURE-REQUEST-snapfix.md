# snapfix measurement and proof record

## snapfix

Worktree `/home/user/Projects/cx-snapfix`, branch `cx-snapfix`, PRE `a214652ec`
(origin/cpp, wave 8 + 8b). Not pushed. Everything in this lane ran on CPUs 16–31
(servers 16–23, drivers and load 24–31, builds `-j16`) and ports 20200–20299.
This report makes **no throughput claim**; every performance measurement is in
the merit request for the maintainer (section 10).

### 1. Result

| Defect | Reproduced on PRE (geometry in section 2) | Root cause | Fix (final commit; first shape) | New gate row: PRE vs POST |
|---|---|---|---|---|
| **XS-SHUT-1** — SHUTDOWN NOSAVE (or SIGTERM) with cross-owner scripts in flight aborts, rc −6 | 4 of 4 mode×engine cells, each on its first attempt | Post-join teardown released abandoned EXEC/group *unit* intents (6ea8d4291) but never the PIN references of abandoned cross-owner script activations, so the unchanged empty-list check in `atomic_destroy_pending` aborted | `09ad61cf5` (first shape `1929d0cac`) | PRE: FAIL on every TomoKV leg. POST: ok on every leg. Redis oracle: ok |
| **SNAP-STORM-1, script storm** — BGSAVE/SAVE never returns | 4 of 4 cells (attempts 1–3) | A script activation's snapshot apply window was closed only at reply retirement on its admitting IO thread — the very thread a BGSAVE/SAVE blocks in `drain_atomic_groups` waiting for that window | `580521c82` (first shape `6732008ae`) | same |
| **SNAP-STORM-1, EXEC + writer storm** — units and some writers stall for seconds, clears only when load stops | 3 of 4 cells; **1s / io_uring NOT REPRODUCED** in 5 × 30 s | Livelock: during a capture the owner's snapshot-mode inbox drain emptied each lane "until empty", and closed-loop writers refilled one lane as fast as it drained (each write slower while MVCC chains grow, collapse being refused during capture), so the owner never returned to its capture, its parked EXEC/WATCH retries or any other lane | `0c5dec1f3` (first shape `fb9aaad3e`) | same |
| **SNAP-STORM-1, any BGSAVE loop — OPEN, follow-up** — after ~10 saves each BGSAVE start takes seconds (cuts armed = saves, units held, writers progress); RSS doubles per save | still present in the delivered POST: the at412 script + writer diagnostic reproduces in 4 of 4 cells; an idle one-key server goes 20 MB → 13 GB RSS in 16 BGSAVEs (PRE identical) | Every snapshot sizes its post-cut table at twice the *current* capacity and nothing shrinks it after the merge, so each BGSAVE doubles every shard's table; the next Preparing must first finish merging the previous doubled table, 8 slots per step, while the armed atomic barrier holds every new unit | **not in POST** (frozen at the maintainer's request): fix written and measured (`3dd076c29`, reverted in `93520fcc9`), kept as `docs/snapfix/followup/table-sizing.patch` | follow-up row part (c) in `docs/snapfix/followup/row-part-c.patch`: PRE FAIL (19 MB → 960 MB), POST + patch ok |

Delivered POST = HEAD source = `build/tomokv` SHA-256 `ee7461ab…`; `make all` at HEAD reproduces it
byte for byte, so every receipt below binds it.

### 2. Reproduction

PRE binary `build/snapfix/pre/tomokv` (SHA-256 `7e7d8034…`), at412's diagnostics
(`tests/at412_diagnostics.py`, copied unchanged from `cx-at412c` 59bfde06a,
provenance in `docs/snapfix/provenance/`) under an outer watchdog
(`tools/snapfix_reproduce.py`). Geometry: server on 8 physical CPUs (16–23),
16 shards, `--databases 16`, `--atomic 1`, key/client balancing and automatic
FLIP off, `--save ''`; 1s = `--thread-mode 1s --read-local 1`; 2s =
`--ratio 6:2 --read-local 0`; both engines (`--net-io uring|epoll`); driver on
24–31; 5 attempts × 30 s per cell. Receipts: `docs/snapfix/pre/runs.json` and
one log per cell.

| Defect / storm | 1s io_uring | 1s epoll | 2s io_uring | 2s epoll |
|---|---|---|---|---|
| XS-SHUT-1 / cross-owner scripts | reproduced, attempt 1 | reproduced, attempt 1 | reproduced, attempt 1 | reproduced, attempt 1 |
| SNAP-STORM-1 / EXEC + plain writers | **NOT REPRODUCED** (5 × 30 s at this geometry) | reproduced, attempt 1 | reproduced, attempt 1 | reproduced, attempt 2 |
| SNAP-STORM-1 / scripts + plain writers | reproduced, attempt 1 | reproduced, attempt 3 | reproduced, attempt 1 | reproduced, attempt 3 |

The directed reproductions of section 4 (`tests/snapfix.py`) make all three
deterministic: PRE fails every one of their 8 TomoKV legs (1s/2s × io_uring/epoll ×
atomic 0/1), including 1s / io_uring for the EXEC + writer storm.

### 3. Root causes and fixes

**XS-SHUT-1.** Core of the PRE abort (`docs/snapfix/rootcause/xs-shut-1/`):
the coordinator is in `atomic_destroy_pending` (reached from
`atomic_shutdown_release_records` → `atomic_promote_all_for_shutdown`) with
`live = 0`, `script_intent_count = 1` and one kind-0 PIN node with `refs = 8` —
eight activations parked between their PIN and UNPIN waves. GCC emits one shared
`abort` call for the whole function, so gdb attributes it to line 232 (a check inside
the inlined `atomic_remove_unit_intents`, the at412 report's "line 232"); with one
PIN node left only the final `live || script_intent_count` check can fire. Ownership and
lifetime: a cross-owner activation takes one PIN reference per declared key in its
PIN wave and only its own UNPIN wave (or the APPLY owner's `ScriptApplyPins`)
drops it. SHUTDOWN NOSAVE or a signal stops the owners between those waves; the
activation was never acknowledged and no wave can run after the join, so nothing
ever drops the references. EXEC and RENAME storms take no PINs, which is why they
shut down cleanly. **Fix:** `IoLoop::shutdown_release_abandoned_script_pins()`
(`src/core/shutdown.cc`) runs in all four coordinator teardown sequences
(`main.cc`, `genthread.cc`, `rl2s.cc`, `reorder.cc`) after every owner has joined
and before `atomic_shutdown_release_records()`; on each shard it calls
`FlatStore::atomic_release_abandoned_script_pins()`, which frees the PIN prefix of
the intent list and balances `script_intent_count`, the server's script-intent
shard count and the activity count. The empty-list abort is unchanged and still
guards every other leak. Teardown does *more* work, never less. Every post-run exit
passes through those sequences; the boot-failure exits happen before a client can
connect. NOSAVE semantics: the abandoned activations were never acknowledged; every
acknowledged write is in the AOF (the row checks it).

**SNAP-STORM-1, script storm.** PRE stack (`docs/snapfix/stacks/pre-snapshot/1/server.log`):
the BGSAVE's IO thread is in `SnapshotManager::start` → `drain_atomic_groups`
waiting for `atomic_apply_inflight() == 0`, with one cross-owner activation's
window open. That window was closed only by `xshard_destroy()` at reply
retirement, which runs on the activation's admitting IO thread — the thread that is
waiting. Self-wait. **Fix:** `script_snapshot_done()`, which runs at exactly the
three `ScatterFinish::Final` sites of `xshard_complete_script()` (owner side, last
wave done; APPLY is the only record-installing wave), now also closes the window,
as the ordinary group arm's `final()` already does. The retirement-time close
stays as the idempotent backstop.

**SNAP-STORM-1, EXEC + writer storm.** Live evidence from servers stopped while the
storm still ran (`docs/snapfix/rootcause/snap-storm-exec-core1|2/`, captured by
`tools/snapfix_storm_capture.py` under gdb because yama blocks attach): the
capturing owner (a 2s executor) is inside `drain_tasks_snapshot` →
`ThreadCtx::drain_tasks` executing a task, in both cores; its inbox (`inbox-lanes.txt`)
holds full eight-entry lanes, one with its notify bit already taken; the parked EXEC
units are all in `Placing`, each blocked behind another's epoch (`place-blockers.txt`);
in core 2 three of the eight EXEC clients reached 1.23–1.30 s while the plain writers
kept going, and the live INFO delta over that second is 344 EXECs executed against
88,323 writer waits and 4.97 M fast-retry polls (`live-delta.json`); the stall
cleared only after the storm stopped (the watchdog stops the server at 1.0 s so the
cores show it live; `ss-live.txt` holds the socket queues at that moment).
Mechanism: while a shard captures,
`atomic_collapse()` refuses to run, so each plain-version write to the hot key walks
a chain that grows with every write; the capture advances only in
`snapshot_control_pass()` between drains; a drain "until empty" therefore stopped
returning once a few closed-loop clients refilled one lane as fast as the slowing
walk emptied it. Capture, retry queues and every other lane starved; nothing ended
it but the load stopping. It also explains at412c's POST signature (cuts = saves,
BGSAVE in progress: the Preparing acknowledgement was stuck behind the same drain).
**Fix:** in snapshot mode only, the owner takes at most `BatchOps` (32) tasks per
producer lane per call (`ThreadCtx::drain_tasks_capped` /
`drain_tasks_unmasked_capped`, instantiated only by
`ExLoopT::drain_tasks_snapshot`), and a capped lane's flag goes back through the
new `NotifyMask::restore()` so the next pass resumes it. No timeout, no dropped
work, per-lane FIFO order kept; an owner with no snapshot armed keeps the unbounded
drains, compiled as before.

**SNAP-STORM-1, any BGSAVE loop (found after the first POST).** The at412 diagnostics run on the
first POST (`docs/snapfix/post-ee7461ab/`) no longer reproduced XS-SHUT-1 or the EXEC + writer
storm, but the script + writer storm still failed in all four cells, always after about ten
BGSAVEs, with the BGSAVE reply itself timing out. A live core of that state
(`docs/snapfix/rootcause/snap-storm-prepare/`) shows BGSAVE #12 in `Preparing` with 7 of 8 owners
ready; the eighth is still merging shard 11's previous 1,048,576-slot table into a 2,097,152-slot
one for a shard with no keys — every shard of the server held 2M slots. Cause:
`FlatStore::snapshot_prepare` sized the post-cut table at twice the *current* capacity, and after
the capture the frozen table merges into it with nothing shrinking it again, so every snapshot
doubled every shard's table for good. An idle one-key server goes from 20 MB to 13 GB RSS in 16
BGSAVEs on PRE and on the first POST alike (`table-doubling.json`); each next `Preparing` first
finishes the previous merge at eight slots per rehash step, one step per control pass, while the
armed atomic barrier holds every new EXEC/script unit and plain writers keep going — at412's
"cuts armed = saves, units stuck while writers progress". It also drove the growing waits seen
in long storms (section 11). **Proposed fix (follow-up, not in POST):** size the fresh table at twice the capacity the
ordinary resize policy needs for the live set (smallest power of two from `kMinCap` with load below
`kLoadPct`), never more than the old rule. A table already at that size gets exactly the old
size; a sparser one gets less but still at least 1.86 × its live set of post-cut room; the
post-cut insert gate and the merge are unchanged. Measured with the patch (binary `742acc78…`):
idle BGSAVE loop RSS flat at 21 MB; at412 script + writer diagnostic 0 of 20 attempts; long
storms flat (section 11). Not yet through the gate, identity or command-scope steps.

None of the fixes adds a timeout, hides a wake-up, or skips teardown work. The fourth is NOT in
the delivered POST (see section 11, follow-up 1).

**Final shapes.** The first shapes (`1929d0cac`, `6732008ae`, `fb9aaad3e`) fixed the
same causes but moved hot code: the PIN release lived in a FlatStore member
instantiated in every IO unit (+48 IPA size), the script close added a wrapper
inside `xshard_complete_script`, and the bounded drain reused
`drain_task_producer_chunks` (−24 IPA size, other instantiations moved). The
reshape commits keep the behaviour and move the code out of the hot units; see
section 8.

### 4. New gate rows (DQ = +3, DF = +3)

Three jobs in `tests/gate.sh` (`job_snapfix_shutdown`, `job_snapfix_bgsave_script`,
`job_snapfix_bgsave_exec`), each one row that runs `tests/snapfix.py` over 1s/2s ×
io_uring/epoll × atomic 0/1 (8 TomoKV legs) plus the Redis 7.4 oracle leg, on the
slot's cores and `PORT`/`PORT+1`, every boot required to exit 0 without a forced
kill. They are collected right after `snapshot-epoll`/`snapshot-uring`, before the
quick-tier exit; labels are in `tests/fixtures/nullrefresh-ledger-labels.json`.
`EXPECT_QUICK`/`EXPECT_FULL` are not edited: **DQ = +3, DF = +3** over a214652ec's
807/824, so the maintainer's counts become 810/827.

| Row label | What must hold on every leg |
|---|---|
| `snapfix XS-SHUT-1 SHUTDOWN NOSAVE in script storm (both modes, both engines, atomic 0/1)` | appendonly yes / appendfsync always; script storm plus eight activations parked in flight (`DEBUG SCRIPT-STAGE-DEFER`, vacuity-checked: owner tasks rose and keys armed > released); SHUTDOWN NOSAVE → exit 0, not forced; restart from the AOF has both keys equal (no partial activation) and ≥ every acknowledged reply (Redis NOSAVE keeps the AOF) |
| `snapfix SNAP-STORM-1 BGSAVE under script storm (both modes, both engines, atomic 0/1)` | (a) BGSAVE sent on the IO thread that admitted a parked activation returns within the stall bound (5 s); (b) script + writer storm under a BGSAVE loop: no operation waits past 5 s, every activation completes, exact accounting, the storm-time snapshot reloads with the witness pair equal |
| `snapfix SNAP-STORM-1 BGSAVE under EXEC + writer storm (both modes, both engines, atomic 0/1)` | 30,000-key dataset (capture length), pipelined writers of one hot key on one IO lane into its owner, an EXEC (+WATCH) storm on the hot key and a cross-owner pair, a BGSAVE loop and a probe from another IO lane into the same owner: no operation waits past 5 s, every EXEC completes, exact accounting, `snapshot_cuts_armed` advanced, the snapshot reloads consistently |

Gate-interface receipts (`tests/gate.sh iteration` with `GATE_ONLY_JOBS`, CPUs 16–31,
ports 20200–20299): POST (`docs/snapfix/proof/proof-main/`, 51 jobs incl. the three rows): **ok on every leg**,
including the Redis oracle legs. PRE a214652ec with the same tests
(`docs/snapfix/proof/rows-pre/`, `--candidate-binary`): **3 FAIL**, every one of the 8 TomoKV legs
red in each row, oracle legs ok. Worst observed waits in the POST rows: script storm 0.05 s,
EXEC + writer storm 1.71 s (EXEC) / 2.95 s (64-INCR burst), against the 5 s bound.

Teardown unit check: `tests/atomic_survivors_unit.cc txn_intents` gained an
abandoned-PIN block (two activations sharing one key's PIN plus another key) that
makes the same two calls as `main.cc`'s teardown and requires every record, intent
and activity count released. POST passes; the same source without the
`shutdown_release_abandoned_script_pins` line, linked against the same POST
objects, aborts (rc 134) — `docs/snapfix/unit/txn_intents.json`. The gate runs it in
the txniso battery rows (debug-0/1, fused-0/1).

### 5. Which fix closes which defect (single-fix arms)

Run on the **first shapes** of the three delivered fixes (`1929d0cac`, `6732008ae`,
`fb9aaad3e`), each applied alone to a214652ec, atomic 1, 1s/2s × io_uring/epoll
(`docs/snapfix/attribution/`): the shutdown case passes only with fix 1, the script-storm case
only with fix 2, the EXEC + writer case only with fix 3 (4 of 4 legs each; every other
combination fails). Not re-run for the final shapes (NOT RUN, section 11); the reshape commits
move the same operations to the same points.

### 6. Neighbours (`tests/snapfix_neighbours.py`, not gate rows)

On the delivered POST, 1s/2s × io_uring/epoll × atomic 0/1 plus the Redis oracle
(`docs/snapfix/neighbours/post-ee7461ab/`):

| Neighbour | Legs passing | What is checked |
|---|---|---|
| SHUTDOWN SAVE during a script storm with parked activations | 9 / 9 | exit 0; restored pair equal and ≥ every acknowledgement |
| SIGTERM, same storm, appendfsync always | 9 / 9 | exit 0; AOF restart equal and ≥ every acknowledgement |
| BGSAVE loop + FLIP 6:2 ↔ 4:4 every second (2s; 1s legs skip) | 9 / 9 | no stall, a FLIP completes, exact accounting, consistent snapshot |
| BGREWRITEAOF loop under the EXEC + writer storm | 9 / 9 | no stall, exact accounting, DEBUG LOADAOF and restart reproduce the data |
| BGREWRITEAOF loop under the script + writer storm | 9 / 9 | same |
| FLUSHALL every 300 ms + BGSAVE loop + script/EXEC/writer storm, MGET pair observer | **7 / 9** | 1s io_uring atomic 0 and atomic 1 saw torn pairs in the MGET observer (follow-up 2) |

### 7. Proof through the gate's job interface

All on POST `ee7461ab…`, CPUs 16–31, ports 20200–20299, `REDIS74_ROOT=/home/user/Projects/redis`,
archived by `tools/snapfix_record.py` (ledgers and per-job verdicts kept; `record.json` binds the
command line, the binary SHA-256 and the SHA-256 of every evidence file):

| Receipt | Command (GATE_ONLY_JOBS iteration unless noted) | Result |
|---|---|---|
| `proof/proof-main` | the three snapfix rows; snapshot-epoll/uring, persistfix2_lastsave/shutdown/commands/errors, persistfix_units, dump_restore, debug-0/1 (xscript, scriptatomic, execatomic, txniso + teardown unit check); aof-epoll/uring, aof_frame, aoforder, notify_aof, serverfix_waitaof; iofix-signal, climonfix (shutdown unit); txnorder-fused/split-0/1, txnorder2, txnorder_wake, txnorder_index, execfair, txn_group_fused/split; script_bounds, scriptfix, lualibs; flip, fliplisten, flipctl, flip_saturated, flip_unit, flipfix_units; atomic_units, atomic_batteries, atomfix5_watch/accounting, moverfix, fused-0/1; source_identity; prerequisites release, core_tsan_build, production_units | **51 jobs, 315 ok, 0 FAIL** |
| `proof/differ-uring` | differ-split-0/1, differ-armed-0/1, differ-equivalence (`tests/differ_gate.sh`, 235 legs per job) | 5 ok; seeds 7 19 20 23 21 |
| `proof/differ-epoll` | same with `GATE_DIFFER_NET_IO=epoll` | 5 ok; seeds 7 19 20 23 22 |
| `proof/rows-pre` | the three rows with `--candidate-binary` PRE | 3 FAIL (expected) |
| `python3 tests/gates_test.py` | — | 73 tests OK |
| `make -q all`, every `job_production_units` target (45) and `build/blockfix-cost` | after the final build | all fresh at HEAD (rebuilt after the revert; `make -q` exit 0 for every target) |
| `docs/snapfix/unit/txn_intents.json` | `atomic-survivors-unit txn_intents` | pass; negative control without the release aborts (rc 134) |

### 8. Cost

**Serverless command-scope counts** (`tools/snapfix_scope.py`, the
`tools/execindex_scope.py` probe and rules; `docs/snapfix/instructions/comparison.json`):

| Commands | Batch | Modes | Namespaces | Cells | POST vs PRE executed instructions (total and per function) |
|---|---|---|---|---|---|
| GET, SET, INCR, MGET | 1 and 32 | 1s, 2s | `tomo`, `tomo_db0` | 32 | equal in all 32 (zero added) |
| MSET (atomic 0 and 1) | 1 and 32 | 1s, 2s | `tomo`, `tomo_db0` | 16 | equal in all 16 (zero added) |

All 48 cells equal, totals and per-function counts. No snapshot is armed in these
scopes; the only new code on an owner's loop is reached through
`snapshot_owner_state_ != None`, which these commands never take.

**Body identity and inline budgets.** The final shapes were chosen so that no
non-snapshot hot body changes. Compile-only trials for every IO unit and `xshard.o`,
both namespaces, a214652ec + (15 … 123) (`tools/snapfix_budget.py`,
`tools/snapfix_budget_bodies.py`, receipts in `docs/snapfix/budgets/`): rule = no
PRE hot body (`tools/lbstall_artifacts.HOT` + xshard prepare/execute) may change except
the intended capped snapshot drains, then fewest changed bodies of any kind, then
nearest a214652ec + 23 (the IO units' IPA growth). Selected budgets
(`docs/snapfix/budgets/selected.json`): src genthread 131218 → 131241, db0 genthread
132012 → 132035, src rl2s 164621 → 164644, src reorder 149103 → 149134, db0 reorder
150092 → 150113, src xshard 148585 → 148608, db0 xshard 147391 → 147426; main.o ×2 and
db0 rl2s.o unchanged. Whole-link identity of the final POST against PRE
(`tools/snapfix_identity.py`, `docs/snapfix/identity/functions.json`):

| Functions in the 118-object link | Identical | Differ only in alignment NOP encoding | Intended changes | Residual changed bodies (all cold) | Unintended hot changes |
|---|---|---|---|---|---|
| 17,944 | 17,891 | 3 (`select_zrange` ×2, one db0 `xshard_execute` lambda) | 34: capped snapshot drains, `drain_tasks_snapshot` where out of line, `script_snapshot_done` (+ cold part), the post-join teardown functions and the new `shutdown.cc` function | 16: `classify_keys`, `reply_err` ×2, `kvobj_external_bytes` ×2, `atomic_prepare_capacity_read_local` ×3, `txn_group_retry.cold` ×2, `read_local_pending_unpublish.cold` ×2, `atomic_tombstone_all`, `pubsub_reply_ping.isra`, `pubsub_notification_send`, db0 `snapshot_control_pass` | 0 |

`classify_keys` differs at every trial budget: two `append_key_span` edges with
equal (zero) badness are taken in a different tie order. Identity is a proxy; the
command-scope counts above and the maintainer's merit decide.

### 9. Arms and SHA-256

| Arm | Path | SHA-256 | Source |
|---|---|---|---|
| PRE | `build/snapfix/pre/tomokv` | `7e7d803448478ecf8ff4d225c8751421d31a096044f62ea29b2ba1bac1db99c3` | a214652ec |
| POST (release candidate) | `build/tomokv` | `ee7461abce1ac998eb361236388c0afa2b242d1a908d52b1da89d6b547b3236c` | HEAD (fixes 09ad61cf5, 580521c82, 0c5dec1f3; budgets 53e293729) |
| POST-layout | `build/snapfix/POST-layout` | `ef6ef547fda92ef5f2db71ae13bd961d17ca32ad0be2896145cea13cd76e0f65` | POST objects + symbol-isolated PRE objects, runs POST (`docs/snapfix/pad-a.json`) |
| PAD-A | `build/snapfix/PAD-A` | `01befa83ab8b07646c0e8e5aaa964c72be1d52fd0ab877dca16de32f25815330` | same image, main's 5-byte jump to PRE's entry; sections and symbols match |
| (evidence only) POST + table-sizing patch | not kept | `742acc787496c92421bb8c35226ff5fc2f171f088c5dec10afaa22b953a37f9c` | follow-up 1, not delivered |

POST-layout and PAD-A both boot, answer PING/SET/GET and exit 0 on SHUTDOWN NOSAVE.

### 10. Merit request (maintainer; no throughput claim here)

Run each set as ABBA with the harness defaults:

1. **14 generic cells** — `docs/execfair/cells/generic14.txt` (SHA-256 `ac371976…`):
   PRE vs POST-release, and POST-layout vs PAD-A (the layout control for the
   larger common image).
2. **2s GET/SET null** — `tests/headline_cells.txt` (SHA-256 `f62b7a4c…`) h17 (2s GET
   p32), h18 (2s SET p32), h49 (2s GET p1), h50 (2s SET p1): PRE vs POST-release.
   Expected null: these commands execute PRE's instructions (section 8).
3. **EXEC merit, 8 cells** — `/home/user/Projects/calib/exec-merit.py` (SHA-256
   `efe613ea…`), `x2s_a0_unc`, `x2s_a0_hot`, `x2s_a1_unc`, `x2s_a1_hot`, `x1s_a0_unc`,
   `x1s_a0_hot`, `x1s_a1_unc`, `x1s_a1_hot`: PRE vs POST-release. No BGSAVE runs in
   these cells, so the capped drain is not reached; this is a null for the EXEC path.

### 11. NOT RUN, and notes for the owner

**NOT RUN**
- Performance benchmarks, the merit cells and the full `tests/gate.sh` iteration: maintainer only.
- `atomic_floor` (a throughput-floor assertion, i.e. a performance measurement).
- A `GATE_NET_IO=epoll` pass over the jobs that have no engine legs of their own: the changed code
  is engine-independent, and the new rows, snapshot-*, aof-* and the differential run both engines.
- `asan_batteries` (full-tier only).
- Attribution for the final (reshaped) fixes; it was run on the first shapes (section 5).
- The FLUSHALL neighbour on PRE, so follow-up 2 is not yet classified as pre-existing.
- The table-sizing patch through the gate, identity and command-scope steps (follow-up 1).

**Follow-up 1 — BGSAVE-loop table doubling (SNAP-STORM-1, open in the delivered POST).** What:
every BGSAVE doubles every shard's hash table permanently; after ~10 back-to-back saves each
BGSAVE start spends seconds in `Preparing` merging the previous doubled table while the armed
atomic barrier holds new EXEC/script units, and RSS doubles per save (20 MB → 13 GB over 16 saves
on an idle one-key server; PRE identical). Evidence: `docs/snapfix/post-ee7461ab/` (at412 script +
writer diagnostic reproduces in 4 of 4 cells on the delivered POST),
`docs/snapfix/rootcause/snap-storm-prepare/` (live gdb state, stacks, `table-doubling.json`),
`docs/snapfix/long-storm/before-table-fix/`. Cause: `FlatStore::snapshot_prepare` sizes the
post-cut table as `cap_[0] * 2` and nothing shrinks the table after the merge. Proposed fix and
row: `docs/snapfix/followup/table-sizing.patch` (size from the live set, ≤ old rule) and
`row-part-c.patch` (12 back-to-back BGSAVEs, RSS bounded); measured with it: RSS flat, at412
diagnostic 0 of 20, long storms flat (`long-storm/after-table-fix/`). It changes the IO units'
IPA size (+14) and needs its own budget, identity, scope and gate pass.

**Follow-up 2 — FLUSHALL torn pairs, 1s io_uring.** In the FLUSHALL neighbour, an MGET observer
saw unequal pairs in both 1s io_uring legs (atomic 0: the EXEC pair 2 apart, and one key present
while the other was flushed; atomic 1: the script pair torn by a FLUSHALL, one key reset while the
other was not). The other 7 legs and the oracle were clean. None of the delivered fixes touches
FLUSHALL or read visibility (the apply window is read only by the snapshot cut and FLIP
quiescence), but PRE was not run; `tests/snapfix_neighbours.py --flushall-bgsave 0
[--flushall-flush 0]` isolates the ingredients.


**Long storms (not a gate row).** The EXEC + writer storm was also run for 6, 30 and 60 s with
the stall bound raised to 30 s so slow operations are measured rather than failed
(`docs/snapfix/long-storm/`, atomic 1). On the delivered POST the slowest operation grows with
the storm in 2s mode, because every BGSAVE doubles the tables and so takes longer than the last
(follow-up 1); with the follow-up table-sizing patch the waits are flat:

| Leg (atomic 1) | Delivered POST: slowest EXEC / slowest 64-INCR burst at 6, 30, 60 s | With the follow-up patch: same | BGSAVEs started in 60 s, POST → patch |
|---|---|---|---|
| 2s io_uring | 1.15/2.88, 1.10/3.35, 3.07/7.31 s | 0.61/0.83, 0.59/0.86, 0.61/0.83 s | 7 → 104 |
| 2s epoll | 0.94/2.54, 3.34/7.15, 4.64/11.04 s | 0.21/0.50, 0.51/0.84, 0.61/0.85 s | 6 → 120 |
| 1s io_uring | 0.12/0.50, 0.62/0.83, 0.36/0.53 s | 0.05/0.06, 0.05/0.07, 0.06/0.08 s | 7 → 597 |
| 1s epoll | 0.24/0.13, 0.61/0.31, 0.28/0.45 s | 0.02/0.05, 0.06/0.07, 0.05/0.07 s | 7 → 597 |

Every leg passed in both columns and the probe from another IO lane into the same owner never
waited more than 0.11 s. What remains with the patch is the designed capture-time cost (while a shard captures,
`atomic_collapse()` refuses and each hot-key write adds and walks a version), now bounded by the
capture length; in 2s mode under back-to-back BGSAVEs it costs up to ~0.9 s for a 64-command
pipelined burst on the one hot key. Whether versions may collapse during a capture is an
algorithm question for the owner.

**Owner note 2 — overlap with cx-at412c.** at412c's `d06cfb01d` closes the same script apply
window at the same point (after `xshard_complete_script` returns Final, `owner_io` slot, with
extra abort checks). Both closes are idempotent, so merging both is harmless but redundant;
keep one. at412c does not contain the XS-SHUT-1 or the EXEC + writer fix, and the EXEC +
writer livelock is what produced its POST signature "cuts = saves, BGSAVE in progress".
