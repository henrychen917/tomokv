# Atomic commit publication repair

## publishfix

Lane `cx-publishfix` (branch `cx-publishfix`), base `cx-wave3` `98c69316d` (integrated, not yet
landed wave 3). Correctness only, on CPUs 96-111 (servers and oracle 96-103, clients 104-111),
ports 25800-25899. Nothing was pushed, no stash was used, and `tests/gate.sh`, performance
benchmarks and measurement load generators were not run. **No throughput claim is made.**

| Item | Result | Receipt |
| --- | --- | --- |
| **Fix** (`205a7dd81`) | `Server::atomic_commit_publish` (`src/core/server.h:2574-2602`). After its release CAS, the last decrementer re-reads `commit_seq_`. While the sequence has moved and `atomic_commit_inflight_` reads 0, it adopts the newer value and publishes it again (loop). No new member, no layout change. Reserve, the non-last path and the readers are unchanged. | `git show 205a7dd81` |
| **Fix compared with investigation 5.1** | **Matches.** Same statements in the same order, same memory orders: seq_cst `drawn` load before the acq_rel decrement, relaxed load plus release CAS, seq_cst re-load of the sequence, then seq_cst load of the count. Only the comment wording differs, plus R1's compiled-out `TOMO_PUBLISHFIX_TEST` hook. The POST machine code implements exactly this sequence; the non-last path adds no memory access (section 1). **No flaw found.** | section 1; `docs/publishfix/anchors.md` |
| **Gate rows** | **DQ=+1, DF=+1.** One row: "atomic commit publication catches up at quiescence" (`tests/gate.sh:1751-1756`, `job_atomic_units`; collected at `:3838`, before the quick-tier exit at `:3985`). With wave 3's +27/+27 the totals are **665 quick / 682 full**. EXPECT_QUICK and EXPECT_FULL are **not edited** (still 637/654). The label fixture holds 682 labels, equal to the source. | section 2 |
| R0 logic model (Appendix A, extended) | Current code: 2 orphaned final states with 2 committers, 36 with 3. Fixed code: 0 and 0. Literal 5.1 code: 0 and 0 (180 and 8675 states). 0 safety violations in every variant. | `docs/publishfix/pre/r0-exact.log`, `post/r0.log` |
| R1 serverless unit, PRE (98c69316d's publisher plus only the compiled-out hook, as in 7e4a1af0d) | **FAILS as predicted:** `safe=1 drawn=2` with 2 committers, `safe=1 drawn=3` with 3 committers (windows 1 and 2). The hand-off case passes. | `pre/r1.log`; rerun `post/unit-final.log` |
| R1 serverless unit, POST | **PASSES:** `safe=2 drawn=2`, `safe=3 drawn=3`, hand-off `safe=2`. | `post/r1.log`; rerun `post/unit-final.log` |
| R1 unit, PAD-A twin (POST ELF with the catch-up edge disabled) | **FAILS exactly like PRE** (`safe=1 drawn=2`, `safe=1 drawn=3`). | `post/unit-pad-a.log`, `post/unit-final.log` |
| R2 parked committer, real server, 10 fresh boots per arm | PRE: **10 of 10 lose the publication.** B reads `[nil, nil]` right after its OK and still after 1 s. It reads `[B, B]` only after an unrelated kick, after LOADAOF and after restart (windows=1, held reads=1). POST: **10 of 10 pass**, `[B, B]` at every step (windows=1, held reads=0). | `pre/reproductions.tar.gz`, `post/reproductions.tar.gz` |
| R3 aoforder crossing, fused / 16 DBs / always | PRE: **23 of 300 runs fail** (7.7%). The race window opened in 180 runs and 23 live reads were held; every failure classifies itself as visibility (live2 ≠ live, live2 = reloaded = restarted). POST: **0 of 300 fail.** The window opened in 223 runs; 0 held reads; live = live2 in all 300. | `pre/r3-summary.jsonl`, `post/r3-summary.jsonl` |
| R3 aoforder crossing, split / 1 DB / everysec | PRE: **6 of 100 fail** (window in 80, 6 held reads). POST: **0 of 100 fail** (window in 78, 0 held reads). | same |
| PAD-A behaviour twins of the two server controls (same patch tool and branch sites as PAD-A) | Behave like PRE. Parked twin, R2: **10 of 10 lose the publication**, with PRE's exact signature (windows=1, held reads=1). Scheduled twin, R3: fused/16/always **21 of 300 fail** (window in 180; PRE 23 of 300), and split/1/everysec **4 of 100 fail** (PRE 6 of 100). All are visibility-classified. | `post/pad-a-controls.tar.gz`, `post/pad-a-r3-summary.jsonl` |
| aoforder gate job (3 rows, 34 legs) | **3 of 3 rows ok** (34 of 34 legs: single 18, crossing 8, rewrite 8). Crossing witnessed the window in 7 of 8 legs with 0 held reads. | `post/aoforder-rows.jsonl` |
| Atomic batteries: torn/window, RYOW/mixed-write, owner-local hazards | **12 of 12 ok** (thread mode 1s and 2s × boot atomic 0 and 1 × 3 batteries), plus **4 of 4 clean shutdowns**. | `post/batteries.jsonl` |
| EXEC batteries: execatomic, execiso, execfix, multires, multirace, session_monotonic | **24 of 24 ok** (1s and 2s × atomic 0 and 1), plus **4 of 4 clean shutdowns**. session_monotonic: 0 violations, 0 torn, 0 acknowledged-but-invisible writes. | same |
| Redis 7.4.10 differential, suites multi and string, seeds 7 19 20 23, atomic 0 and 1 | Split: **16 of 16 pass.** Armed fused: **18 of 18 pass** (16 legs plus "read-local lane fired" for atomic 0 and 1). 0 diffs. | `post/differ-split.log`, `post/differ-armed-fused.log` |
| `python3 tests/gates_test.py` | **66 of 66 OK** (plus the nested 14 of 14). | `post/gates-test.log.gz` |
| `make all` + every `job_production_units` target | All builds rc=0. `make -q` reports `all`, all 33 targets and both mdbqsbr arms fresh. Rechecked on the final HEAD. | `post/production-build-results.json`, `post/freshness-final.json` |
| Identity (proxy only; the maintainer's merit run decides) | 16,631 of 16,641 object bodies equal. Command handlers 1,211 of 1,211 equal; selected hot bodies 1,218 of 1,218; lbstall hot bodies 1,214 of 1,214. The **10 changed bodies** are listed with reasons in section 4. | `docs/publishfix/identity/final/` |
| SHA-256 | PRE `ebcfbe92762d4a1b35c7f53284980afbf6568ca83b01506a92a38e0b43264d92`; POST `4ba570b00c999ccf870a73f4665eac3609d5075682e8b10e5e03619a3f162b88`; PAD-A `00618bdf924ab09208a8c979b8a050eb088ce57cc92999aad3df1e5f74470f5b` | section 5 |
| **Merit request** | The generic 14 cells plus 12 atomic=1 cells: MSET, SET and MGET at p1 and p32 in 1s and 2s. 26 cells; the instrument parses all of them, with no pending pins. | section 6; `docs/publishfix/merit-cells.txt` |

### 1. The fix compared with investigation 5.1

The protocol is the one in investigation 5.1, line for line. The receipts above cover its three
claims:

- **Safety.** A ticket t ≤ `newer` was drawn by a committer D whose `inflight.fetch_add` (seq_cst)
  is sequenced before its `commit_seq_.fetch_add` (seq_cst, a release RMW). The last decrementer's
  seq_cst re-load reads that RMW or a later one in the same release sequence (every write to
  `commit_seq_` is an RMW). So D's increment happens-before the following in-flight load. If that
  load reads 0, D's acq_rel decrement precedes it in the counter's modification order. Every counter
  write is an RMW, so the load synchronizes with that decrement, and D's epoch store happens-before
  the release CAS. A reader that acquires `atomic_commit_safe_` then sees the epoch.
- **Liveness at quiescence.** The decrement that is last in the counter's modification order reads,
  through the release sequence, every earlier decrement. Its re-load therefore sees every draw, and
  its loop exits only with `safe == commit_seq_`. The model, R1, R2 and R3 all show this.
- **Unchanged paths.** The non-last source path is unchanged. In machine code it keeps the same
  memory operations in both arms: one `commit_seq_` load, `lock decq`, `jne`, then `lock incq
  atomic_commit_windows_`. Register allocation differs, but no memory access is added:
  - the out-of-line POST copy computes three addresses with `lea` before the decrement;
  - the inlined MSET copy in `xshard_flush_commits` keeps `commit_seq_`'s address in a register
    (one stack reload fewer than PRE) and hoists one `lea` above the branch.

  On the last path only, POST adds after `lock cmpxchg`: `mov commit_seq_; cmp; jb →` (a
  separate block) `mov atomic_commit_inflight_; test; jne return; loop`. That is one extra load,
  compare and branch per last-decrementer publication. The second load runs only when the sequence
  moved. All three words share the commit line.
- The hook (`#ifdef TOMO_PUBLISHFIX_TEST`, a static function pointer) does not exist in production.
  `post/no-hooks.log` confirms that no `test_after_drawn` symbol and no park string are in
  `build/tomokv`.

Classification under the owner rules: this is a defect fix inside an existing algorithm. The
algorithm was disproved on liveness, not redesigned; there is no semantic, knob or layout change.
Investigation 5.1 asks that the owner be told before landing.

### 2. Rows

- `tests/gate.sh:1751-1756`: `row_begin "atomic commit publication catches up at quiescence"` →
  `unit_ready publishfix-unit && taskset -c "$CORES" ./build/publishfix-unit`, in `job_atomic_units`.
  The job is collected at `:3838`, before the quick-tier exit (`:3985`): **DQ=+1, DF=+1**. On PRE
  the row fails with `safe=1 drawn=2`; on POST it passes.
- `tests/gate.sh:3635,3642`: `job_production_units` builds `build/publishfix-unit` and
  freshness-checks it. This adds no row. The Makefile rule is at `Makefile:597-606`: every linked
  object is built with the hook in its own `BUILD_ROOT` subtree, so no COMDAT copy is mixed with a
  release object.
- `tests/aoforder.py` `crossing()` gains the 5.2 diagnostics inside the existing "AOF commit order
  crossing" row (0 new rows). These are the counter deltas around the live read, a cross-owner kick,
  live2, and the native AOF ticket/payload order. It asserts `live2 == live` with the 5.2 message,
  then keeps the replay assertion unchanged. No assertion was loosened.
- `tests/gate.sh:329-330`, the EXPECT arithmetic comment, states the lane's +1/+1: with wave 3,
  EXPECT_QUICK=664+1=**665** and EXPECT_FULL=681+1=**682**. **EXPECT_QUICK=637 and EXPECT_FULL=654
  are untouched** and remain maintainer-owned.
- `tests/fixtures/nullrefresh-ledger-labels.json`: the new label sits at its source position, with a
  `publishfix_supplement` note (`bca2b822d`). `tests/gate_ledger_fixture.py` now reports fixture
  682 = source 682, none missing, none extra. It refuses only on EXPECT_FULL=654, as it already does
  on the wave-3 base (681 = 681 vs 654).

### 3. Proof detail

- **Arms.** PRE is `build/publishfix/pre/objects/tomokv`, built from a frozen copy of 98c69316d.
  That copy equals `git archive 98c69316d src third_party Makefile`, rechecked today, with the
  default release flags. POST is the HEAD build `build/tomokv`. Commits after `2aec62c32` touch only
  docs, the label fixture, a comment in `tests/gate.sh` and the lane runner, so the binaries are
  unchanged.
- **Controls (never performance arms).** R2 uses full disposable builds with a park after the
  `drawn` load (`tools/publishfix_schedule.py`). R3 and the crossing row use the aoforder
  fragment-scheduled build. R1 is a serverless re-entrant unit.
- **The parked POST build was rebuilt from the final tree** (`build/publishfix/sched-post-final`).
  The earlier `sched-post` copy predated the inlining-budget commit `300b9749a`. Only the park hook
  differs from HEAD's src, and the Makefile is identical.
- **Battery geometry.** Both groups use 16 shards and ratio 6:2 in 2s. The atomic group runs with
  default balancers, as `job_atomic_batteries` does. The EXEC group runs with key/client balancing
  and FLIP off, as `job_debug` does. Each battery restarts from the requested initial `atomic`.
  `tests/txniso.py` exists only on the unlanded EXEC lane, so this tree's EXEC set is the
  `job_debug` list above.
- **Harness fix** (`29ebe49b4`). The runner's battery phase held one admin connection per battery,
  so the first pass reported 8 dirty shutdowns. `live_conns` equalled the runner's own connections
  (3 and 6) in every boot, while all 36 batteries passed. The runner now closes that connection;
  both passes are in `post/batteries.tar.gz`.
- **Lane-local paths.** The differential history went to `build/publishfix/differ/history`, so the
  durable corpus was not touched. gates_test's one ephemeral listener was pinned to lane port
  25890.
- **Defect predates wave 3.** `atomic_commit_publish` is byte-identical on PRE and on cx-aoforder's
  tip `bd2fb1fcb` (`pre/historical-source-equality.json`). The investigation's optional PRE loop on
  cx-aoforder's scheduled binary was **not run**; source equality is shown instead.

### 4. Identity: every changed body against PRE

`docs/publishfix/identity/final/` holds the output of `tools/lbstall_artifacts.py compare`,
`tools/ccfix_audit.py` and `docs/deadswitch/linked_bytes.py`. The linked-bytes tool reports that
runtime sections differ (`linked.json`); addresses necessarily move.

The xshard.o inlining budgets were re-derived by 16 compile-only trials
(`docs/publishfix/identity/budgets/trials.json`): src 128012→**128042**, db0 126680→**126710**.

| Object | Body | Bytes PRE → POST | Reason |
| --- | --- | --- | --- |
| `src/cmd/xshard.o`, `db0/src/cmd/xshard.o` | `Server::atomic_commit_publish()` | 57 → 86 | The fix: last-decrementer recheck and catch-up loop |
| both xshard.o | `xshard_flush_commits(...)` | 1494 → 1530 | Inlines the repaired publisher for the commit batch |
| both xshard.o | `xshard_flush_commits(...) [clone .cold]` | 15 → 15 | Cleanup target offsets follow the changed parent |
| `src/main.o`, `db0/src/main.o` | `Server::init(...)::{lambda(void*)#1}::_FUN` | 106 → 121 | The shard-clear callback calls `atomic_commit()`, which inlines the publisher |
| `src/cmd/xshard.o` | `normalize_multi_blocking_pop(MultiCommand&)` | 3308 → 3454 | Unedited cold MULTI helper. This is GCC inlining/partition spillover that remains after the trials; it is not a command handler or a selected hot body. Accepted for merit review. |
| `src/cmd/xshard.o` | `normalize_multi_blocking_pop(...) [clone .cold]` | 45 → 45 | Cold companion of the body above |

### 5. Binaries

| Arm | Path | SHA-256 |
| --- | --- | --- |
| PRE | `build/publishfix/pre/objects/tomokv` | `ebcfbe92762d4a1b35c7f53284980afbf6568ca83b01506a92a38e0b43264d92` |
| POST | `build/tomokv` | `4ba570b00c999ccf870a73f4665eac3609d5075682e8b10e5e03619a3f162b88` |
| PAD-A | `build/tomokv-publishfix-pad-a` | `00618bdf924ab09208a8c979b8a050eb088ce57cc92999aad3df1e5f74470f5b` |

All three report `TomoKV 1.0-cpp (Redis 7.4.10 compatible)`. No knob, default or `--help` text
differs, so PRE and POST take identical argv.

**PAD kind (A), behaviour twin.** PAD-A is POST's exact ELF with the catch-up edge disabled
(`tools/publishfix_pad.py`, receipt `post/pad-a-final.json`). There are six `newer <= drawn`
branches: one `jb` per publisher copy, in `atomic_commit_publish`, `xshard_flush_commits` and the
`Server::init` lambda, in both namespaces. Each is replaced by NOPs of the same length. Sections
and symbols are identical, and exactly 20 bytes differ from POST (rechecked with `cmp`). PAD-A
behaves like PRE: the same patch applied to the R1 unit and to both server controls loses the
publication (table above). It still executes POST's extra sequence load and compare, so:

- POST vs PAD-A isolates only the catch-up iterations, which run only when a ticket would have
  been orphaned;
- PRE vs PAD-A contains layout plus the extra load and compare.

No PAD-B (PRE instructions in POST layout) is claimed.

Correctness controls, never performance arms:

| Control | SHA-256 |
| --- | --- |
| parked PRE `build/publishfix/sched-pre/tomokv` | `d01a68ca6168391297756a5d66a713df486efaae676ad42c70c5c8ecd5496c1b` |
| parked POST `build/publishfix/sched-post-final/tomokv` | `5e5205e1bc7f80ade96105f061136321f7a5d7d72c169e5be4b98492a653d062` |
| scheduled PRE `build/publishfix/pre/aoforder-scheduled/tomokv` | `086f682e8b6783a49c6d2329c03d30f9120d686cea8bd8e6c96557dee0aa8638` |
| scheduled POST `build/aoforder-scheduled` | `3551e57a61edfdc2e3926f19f1eec570bf5dcbc290a9653ae137e045cafd600f` |
| unit PRE / POST / PAD-A | `a07bf44c…` / `a81c2947…` / `c909ebcb…` (`docs/publishfix/pre/arms.json`, `post/arms.json`, `post/unit-pad-a.json`) |
| parked PAD-A twin `build/publishfix/pad-a-parked/tomokv` | `6762def250c5f7f65c6982dee03d593b572a4c62c26259f21e63214d357e5414` (`post/pad-a-parked.json`) |
| scheduled PAD-A twin `build/publishfix/pad-a-scheduled/tomokv` | `7fca7285fe624329df65d63c4d5f243cd83056ae7969da99dc8a25b27821a2dd` (`post/pad-a-scheduled.json`) |

### 6. Merit request (maintainer)

Use the 26 cells in `docs/publishfix/merit-cells.txt`.

- **Generic 14.** These come verbatim from `docs/lbplanner/generic-cells.txt` (sha256 `ac371976…`).
- **12 publication cells.** atomic=1 MSET, SET and MGET at p1 (latency score) and p32 (rate score),
  in 1s and in 2s.
- **Parse check.** `tests/abbagate.py --list-cells` parses all 26 with no pending pins
  (`docs/publishfix/merit-cells-parsed.json`).
- **Overlap with the generic set.** `pub_1s_set_p32` repeats `h06` field for field.
  `pub_1s_set_p1` differs from `d1s_l0` only in pinned load instances (8 vs 4). Keep or drop them as
  the instrument budget allows.

Use the gate's own instrument and correctness geometry (8 server cores, 16 shards, split 6:2), ABBA
arms at matched offered load, and a contemporaneous same-binary null. Record rate, cycles/op,
instructions/op, IPC, p99 and p99.9.

Compare in this order:

1. PRE/POST.
2. PRE/PAD-A.
3. POST/PAD-A, for any cell that moved.

Also record the INFO deltas of `atomic_groups`, `atomic_localfast`, `atomic_commit_windows` and
`atomic_commit_holds` per cell. These show which cells enter the commit bracket at all:

- MSET publishes once per commit batch: `xshard_flush_commits` → `atomic_commit_batch`, one or
  more cross-shard groups under one bracket.
- SET publishes only for plain versions with live records (`atomic_commit()`).
- GET and MGET never publish.

The only added work is the one load, compare and branch per last-decrementer publication (section
1). No throughput claim is made here.

### 7. Notes for the mainline

- **Owner notice.** Tell the owner before landing (investigation 5.1 classification). This lane
  changes no other server code.
- **Register.** The investigation proposes a BUG row (server-atomics, T1): "acknowledged atomic
  commits can stay invisible to other clients until the next commit". This lane disproves the
  premise of `design-txnfix.md` Rule P, "lasts nanoseconds outside DEBUG". The txnorder design
  should account for this.
- **Not run.** `tests/gate.sh` iteration, performance cells, the cx-aoforder PRE loop (see
  section 3).
