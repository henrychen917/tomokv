## blockfix2

Historical blockfix2 result; the continuation and current lane evidence are in **blockfix3** below.

Branch `cx-blockfix2`, based on `83e0b809d` (wave 8). No push. **Not merge-ready.** Six roots are implemented. Stream removal is partially fixed, with a newly exposed pipelined delete/recreate boundary still failing; two ordering roots are stopped for an owner architecture decision. The Tcl job is **not green**: the newly unblocked XGROUP DESTROY test reaches the separate, deliberately unimplemented INFO error/command statistics surface. No throughput or latency merit claim is made.

### Scope and root status

| Root | Change / disposition |
|---|---|
| BLOCK-WAKE-RENAME-SORTSTORE | Publish successful local and scatter RENAME/RENAMENX/SORT STORE results; publish EXEC mutations at the existing boundary. |
| BLOCK-STREAM-REMOVED-NO-UNBLOCK | Reprobe XREADGROUP on missing group or wrong type; signal stream retirement and XGROUP DESTROY; include phase-one atomic MSET/DEL publication. Standalone runtime/oracle assertions pass. **PARTIAL / STOPPED at command-boundary handling:** pipelined DEL, XGROUP CREATE and XADD can deliver new-stream data to the old waiter instead of NOGROUP. The directed row now asserts this boundary and remains red. Retirement runs before replacement, while the dirty sweep runs after later commands; resolving this consistently with atomic units requires a publication-boundary decision. The complete Tcl assertion also remains blocked by INFO error statistics and INFO-CMDSTAT-FIELDS. |
| BLOCK-MOVE-WRONGTYPE-STRANDS | A completed blocked move rearms the source probe, including destination WRONGTYPE. The source element remains available to the next waiter. |
| BLOCK-WAKE-ORDER-MULTI | **STOPPED, architecture decision.** The existing commit notification is a dirty-shard bit; it loses the EXEC command/key readiness sequence. Registry sweeps and cross-owner claims cannot reconstruct it. Requires carrying ordered readiness through commit and coordinating cross-owner claims. No hash-order workaround or execfifo FIFO machinery was added. |
| BLOCK-CHAIN-ASYNC | **STOPPED, architecture decision.** A claimed move resumes on its IO thread and completes a scatter before publishing the next hop. The producer has no dependency on that transitive work. Matching Redis requires a completion dependency before the producer reply / following command. No global cross-client stall was added. |
| MULTI-XREADGROUP-BLOCK-HANG | Direct XREADGROUP execution completes immediately even with BLOCK; the blocking dispatcher retains normal outside-EXEC blocking. Shared parsing and available-data replies remain in use. |
| INFO-TOTAL-BLOCKING-KEYS | A cold intrusive list of blocking lifetimes supplies distinct namespace/key counts, including the XREADGROUP deletion-sensitive subset. INFO never reads owner-only queue containers. |
| SLOWLOG-BLOCKED-NOT-LOGGED | A resumed direct waiter owns a timing frame, recording its original command before completion publication and excluding its parked interval. |
| BLOCK-SERVE-REFUSED-DROP | Direct serves retain the registry entry and lifetime pin until success; refusal restores Parked and rearms the dirty probe. Only this retention behavior from `9c95a676d` is used. The witness places an actual EXEC reservation, proves refusal, releases the claim, and checks one exact reply and one alias release. |

The immutable replacement/QSBR and owner-only queue rules are retained. The footprint locks are unchanged. The heap-only `BlockingState` grows from 216 to 240 bytes for the INFO membership links. Its keys are immutable while linked; retirement and namespace remap unlink under the observer mutex. No knob was added.

### Reproduction and directed tests

`tests/blockfix2_repro.py` replays the harness5 cases against the pinned Redis 7.4.10 oracle and both PRE modes. All eight supplied roots differed; the flaky readiness-order case was rerun on fresh state with a bounded retry. The extra refused-serve witness fails on PRE in both modes. See `docs/blockfix2/pre-repros.json`, `pre-order.json`, and `pre-refusal-*.log`. Reproduction preceded the fix in commit `cec7cceb2`; implementation commits are `1d861ed88` and `6fe190930`.

The seven new gate rows are in `job_blockfix2`. Six oracle rows each exercise 24 legs: databases 1/16, atomic 0/1, epoll/uring, split 6:2, and fused read-local 0/1. Every boot has eight workers and 16 shards. The refusal row executes the production serverless fixture in both namespaces and modes. The first complete POST run passes all seven original rows (144 oracle legs plus four refusal legs). The final stream-removal row was then strengthened with the discovered pipelined delete/recreate assertion and must remain red until that boundary is fixed; it is not skipped or accepted as an expected failure.

Eighteen named Tcl failures were promoted to mandatory assertions; their exact mapping is `docs/blockfix2/tcl-promotions.json`. Both modes executed every promoted assertion: 34/36 pass, and the two XGROUP DESTROY instances fail at INFO statistics (`tcl-promoted-results.json`). The two stopped roots remain on the named failure list. One slowlog test runs unchanged on a fresh server because an earlier required test leaves slowlog-max-len at zero and the independently failing reset test is skipped. Its name and complete assertion inventory remain mandatory; absence, skip, or failure is red.

`tools/blockfix2_controls.py` builds private POST-derived regressions, without production flags or source edits. With `GATE_BLOCKFIX2_CONTROLS=1`, the same seven gate rows must reject the controls in every vulnerable directed shape and the selected unchanged Tcl assertion in both modes. For rename/move, atomic key-reservation release already supplies an independent wake on PRE: all 12 atomic=0 legs must reject the removed publication, covering every mode/engine/database/read-local shape; all 12 atomic=1 legs still run and must either pass the complete oracle comparison or show the same defect. The other controls require all 24 rejections. The first, overly broad requirement that atomic=1 also reject this single-mechanism removal is retained as failed control evidence.

### Serverless command-scope counts

Production `exec_batch_prefetched` code is linked from the actual PRE and POST objects. Bounded GDB instruction traces count named production routines, including inlined code, excluding fixture glue and out-of-scope library bodies. Clocks are fixed for deterministic branches. These are instruction counts, not cycles/op, IPC, or throughput. Both namespaces and modes, batches 1/32, and MSET atomic 0/1 give **48 comparisons with no positive delta**.

Batch-one counts (PRE → POST):

| Namespace | Command | 1s | 2s |
|---|---|---:|---:|
| normal | GET | 939 → 939 | 1559 → 1559 |
| normal | SET | 1068 → 1068 | 1688 → 1688 |
| normal | INCR | 1531 → 1514 | 2151 → 2134 |
| normal | MGET | 10243 → 10243 | 10243 → 10243 |
| normal | MSET atomic=0 | 10894 → 10894 | 10690 → 10690 |
| normal | MSET atomic=1 | 17080 → 17049 | 16726 → 16695 |
| db0 | GET | 818 → 818 | 1051 → 1051 |
| db0 | SET | 955 → 938 | 1188 → 1171 |
| db0 | INCR | 1314 → 1313 | 1547 → 1546 |
| db0 | MGET | 10370 → 10362 | 10370 → 10362 |
| db0 | MSET atomic=0 | 11143 → 11135 | 10962 → 10954 |
| db0 | MSET atomic=1 | 16497 → 16466 | 16166 → 16135 |

Full per-function counts, object-link commands, exact probe hashes, batch-32 results, and trace digests are in `docs/blockfix2/instructions/comparison-verified.json`, `results-pre.json`, `results-verified.json`, and the `pre-*` / `verified-*` files. Intermediate `post-*` and `final-*` receipts are retained but are not final evidence. The final probe build receipts bind the server SHA below.

### Frozen binaries and PAD semantics

| Arm | Binary | SHA-256 | .text bytes |
|---|---|---|---:|
| PRE | `build/blockfix2/pre-source/build/tomokv` | `cbd6ed78f4625bcd24d6b26a1e99130de05bc552b96546271775e64307e24f1f` | 8435415 |
| POST | `build/blockfix2/post/tomokv` | `d79738936b83882fdf06de1f83f77ffa9e7674726eab8a231c9cd4eb199f48d3` | 8470039 |
| PAD-A | `build/blockfix2/pad-a/tomokv` | `82b6c78bb924015581e78e9397a2137f21ee015266d8aed2352c79e05a4e0d3d` | 8470039 |

PAD-A is **type A, behaviour twin**: frozen PRE behavior with the candidate’s 240-byte BlockingState layout and total .text size. The added fields are inert. Trailing NOPs equalize total text size, with the compiler CET note retained. It does not reproduce every POST function address or alignment. There is no PAD-B arm. `tools/blockfix2_pad.py` and `docs/blockfix2/binary-manifest.json` contain the exact construction.

### Correctness proof ledger

Correctness servers and oracle runs use CPUs 16–31 and ports 20400–20499. The initial harness-unit invocation omitted GATE_TEST_PORT; its socket-owner fixture used the default ephemeral bind. The final 73-test rerun explicitly binds that fixture to port 20499. Builds use at most 16 compile jobs. The gates use server cores 16–23, load cores 24–31, no SMT additions, 16 shards, and split ratio 6:2. Standalone focused oracle diagnostics also use eight cores inside that allocation.

- PASS: `make all`; all footprint assertions; final 48 instruction comparisons; `python3 tests/gates_test.py` (73 tests); `python3 tests/redis_tcl_test.py` (6 tests).
- PASS: first full POST directed job; storage_units, source_identity, blockfix_registry, blockfix_mkstream, blockfix_structure, release_batteries, sort, serverfix_slowlog, notify.
- FAIL, retained: the first broad run has 102 passing and 19 failing rows. Seventeen failures explicitly refuse stale/missing production-unit readiness markers after the last source rebuild; the subsequent run rebuilt and verified these prerequisites. Two failures are the Tcl modes described below.
- PASS: all 52 final make -q freshness checks (`docs/blockfix2/production-freshness.json`); rebuilt debug-0/1 (32 rows), fused-0/1 (18 rows), atomic_units (27 rows). Final storage_units and source_identity repeats also pass; frozen hashes and unchanged production sources are checked in `final-verification.json`.
- PASS: both standard differential matrices, split/fused-armed and atomic 0/1, plus mode equivalence. Fixed seeds are 7, 19, 20, 23; the gate selected rotating seed 21 for uring and 22 for epoll. The original suite skips SORT in fused parts; the separate fused SORT job passes atomic 0 and 1.
- EXPECTED RED: PRE and PAD-A each reject all seven directed rows. All 144 protocol legs reached their declared geometry: 132 show the intended defect and the 12 wrong-type atomic=1 legs already pass on PRE. All four refusal-unit legs reject at the retention assertion. PAD-A matches every PRE leg outcome (`docs/blockfix2/pre-directed.json`, `pad-directed.json`).
- PASS: all 138 feature-battery rows (split 34 + fused-armed 35, each with atomic 0/1), including shutdown and read-local mechanism witnesses.
- FINAL POST: six of seven blocking rows pass with their planted controls. All 148 directed legs reached their witnesses: 124 pass, and 24 fail specifically at the pipelined delete/recreate assertion. Rename controls reject 15/24 legs (all 12 mandatory atomic=0 legs); wrong-type controls reject 12/24 (all mandatory atomic=0 legs); MULTI, counts and slowlog controls reject all 24 each. Refusal controls reject all four unit legs. Selected unchanged Tcl tests pass POST and reject BROKEN in both modes for each completed protocol root. See `docs/blockfix2/post-directed.json`.
- NOT RUN in the final job: the strengthened stream-removal negative control, because its POST positive matrix already fails. The earlier standalone deletion control rejects all 24 directed legs and its required Tcl assertion in both modes, retained in `initial-controls.tar.gz`.
- PASS: all six compat3 rows, latencyfix_shape, serverfix_lines, and all six fused notify rows. The final combined feature job reports 153 pass / 1 fail; its sole failure is the stream boundary above.
- Gate plans, exact per-row ledgers, stdout, Tcl events and individual differential transcripts are archived with file digests in `docs/blockfix2/gate-receipts/index.json`. Red initial runs remain in that index.

The complete Tcl job ran 35 files plus one isolated required test in each mode. Each mode passed 1659/1661 required assertions. Both fail `XGROUP DESTROY should unblock XREADGROUP with -NOGROUP` at `errorrstat NOGROUP`; its later commandstats assertion also needs the documented INFO-CMDSTAT-FIELDS root. The source deliberately omits unimplemented failure/timing counters (`src/cmd/t_server.cc`), so this lane does not fabricate them. The waiter now gets the exact Redis NOGROUP reply.

The other observed Tcl failures were split `BRPOPLPUSH does not affect WATCH while still blocked` and fused `PUBLISH/SUBSCRIBE after UNSUBSCRIBE without arguments`. Both reproduced on frozen PRE in bounded fresh-server reruns (one failure in eight attempts each); Redis passed, and the eight focused POST reruns each passed. The original complete-job failures remain red. Raw transcripts and hashes are in `docs/blockfix2/tcl-extra-replay.json` and its compressed raw file.

`EXPECT_QUICK` / `EXPECT_FULL` are untouched. **DQ=+7, DF=+7**: the seven literal rows at `tests/gate.sh:3788–3801` are collected by `collect_job blockfix2` at line 5658, before the quick-tier exit at line 5822. Baseline source inventory was already 806/823 while constants still read 798/815. This lane’s source/fixture inventory is 813/830; those are the owner’s required reconciled counts. Adding only seven to the stale constants would leave an existing eight-row deficit. The static ledger checker consequently remains red solely on EXPECT_FULL’s count; labels match the source inventory.

### Maintainer merit request — NOT RUN in this lane

Run the gate’s own quiet-box ABBA instrument against the frozen binaries above. `docs/blockfix2/merit.cells.txt` preserves the current 14 generic cells from `tests/wbland_merit_cells.txt`, adds 2s GET/SET p1/p32 null cells (`h53 h54 h21 h22`), and adds MGET/MSET p1/p32 in both modes (`m01 m03 m04 m06 m49 m51 m52 m54`) for the touched scatter/atomic publication path. Keep identical geometry, connections, allocator, keyspace, instrumentation and offered load.

Collect contemporary PRE/PRE and POST/POST nulls, PRE/POST, and PRE/PAD-A. Report per-cell completed rate, cycles/op, instructions/op, IPC and the instrument’s latency scores. Apply the gate’s existing null acceptance criteria independently per cell; do not average away a regression. PAD movement limits attribution. Instruction savings alone do not establish a win.

Also measure the touched cold surfaces in both modes and engines, with atomic 0/1: (1) existing benchtxn BLPOP/LPUSH wake pairs at 1/32/512 pairs, slowlog -1 and 0; (2) RENAME and SORT STORE creating a waiting BLPOP/BLMPOP key; (3) XREADGROUP wake by XADD versus DEL, SET, MSET, FLUSH and XGROUP DESTROY; (4) a wrong-type blocked move followed by a valid waiter; (5) INFO CLIENTS with 0/1/64/1024 blocked clients, including duplicate and distinct keys; (6) EXEC containing XREADGROUP BLOCK with empty and populated streams. For the existing wake cell use `benchtxn blpop HOST PORT SECS PAIRS THREADS`, with PAIRS=1/32/512 and THREADS=1/8/8 respectively; use the gate’s duration and offered-load instrument. Count completed wake round trips separately from their two commands. For the remaining protocol cells, `tests/compat3_blockfix2.py` supplies the exact command sequences and oracle assertions. Count completed logical operations and keep producer/consumer accounting separate. PRE hangs or wrong replies are correctness failures, never throughput samples or wins. The request does not claim those custom protocol cells are already supported by the stock ABBA cell parser.

Performance benchmarks and `tests/gate.sh iteration`: **NOT RUN**, reserved to the maintainer by the task. POST acceptance rows for BLOCK-WAKE-ORDER-MULTI and BLOCK-CHAIN-ASYNC: **NOT RUN**, because their required architectural changes are stopped for the owner's design decision. The remaining stream-removal boundary was run and failed in all 24 legs; its architectural fix is also stopped. No push or merge was performed.

## blockfix3

**Implementation and requested runs complete.** Frozen POST e18acab passes all seven blocking rows with controls, both whole Tcl modes, both differential engines and all 48 exact instruction comparisons. The latest required job results are green. One initial EXEC BUSY rejection remains unclassified despite successful repeats; it is retained below. Final receipts use `land-*`; earlier 943f4ab receipts are historical evidence.

Branch `cx-blockfix3`, based on `1932367f7`. No push. This continuation addresses the deletion/recreation boundary and NOGROUP accounting. The two stopped ordering roots remain untouched. No throughput or latency merit claim is made.

### Implementation and reproduction

PRE reproduces both failures in 1s/2s and epoll/uring, at eight workers, 16 shards and split ratio 6:2. Redis 7.4.10 passes the same protocol and unchanged Tcl assertions. The first receipt commit is `4e7b4751c`; `docs/blockfix3/pre-repro/results.json` includes exact replies, counters, commands and binary hashes. PRE gives new-stream data to the old waiter and omits the NOGROUP/error/failed-call fields. The Tcl failure occurs after its NOGROUP reply assertion succeeds.

DEL/UNLINK now publish after their owner has completed deletion. The publication uses the existing EXEC/plain-MVCC deferral; it never services a queue recursively from object retirement. Non-atomic scatter deletion publishes on its mutation wave. In the existing plain-MVCC slow path, a decided predecessor is observed before the next command installs its replacement. The first full matrix exposed a second path: atomic owner cleanup could remove the last record before the successor dispatch, bypassing that slow path. Cleanup now finishes the already-pending readiness sweep immediately after materialization, outside table retirement, before returning to command dispatch. XGROUP CREATE also publishes the prior group state before borrowing a stream object. The existing owner-cycle sweep consumes the same dirty flag, so this does not add a scan to the common GET/SET/INCR/MGET/MSET path. Same-connection undecided units still park at dispatch. Registry access stays owner-only; immutable replacement, QSBR and migration ownership are unchanged.

NOGROUP accounting is attached to XREADGROUP's actual error reply, including its unblock rerun, rather than a readiness probe or the deleting producer. INFO exposes that count in errorstats, total_error_replies, and XREADGROUP failed_calls, with the existing RESETSTAT baseline. Errorstats is included in bare INFO and INFO DEFAULT, matching Redis 7.4’s default section list; both forms are checked against the oracle. XREADGROUP execution slices have measured microseconds, excluding parking; other commands' commandstats formatting and counters are unchanged. This is the requested NOGROUP surface, not an implementation of the other outstanding INFO error/timing roots. All public footprint locks and the 240-byte BlockingState remain unchanged. Only cold statistics storage grows.

The six other blockfix2 directed probes and their row definitions are unchanged. The removal probe additionally checks DEL, UNLINK and cross-shard DEL recreation through XGROUP CREATE and RENAME, with eight fresh registrations per shape, no inherited consumer or pending delivery, the contrasting EXEC boundary, two failed waiters plus a surviving group, and RESETSTAT. The existing mandatory Tcl test already contained both outstanding statistics assertions; it remains mandatory, with no new exclusion or duplicate test name.

### Cost and frozen arms

The first candidate changed db0 SET inlining and added 17 instructions per command (544 per batch of 32). That candidate was rejected. Moving the deletion-publication loop out of the string translation unit restored its original inlining. Intermediate `post-*` receipts retain that cost failure. The instruction-equal `final-*` candidate subsequently failed the rare cleanup/recreation case and was also rejected. `verified-*` binds the 943f4ab checkpoint. The final INFO-default implementation is bound by `land-*`; all 48 comparisons are exact again. All **48/48 final comparisons have zero delta**, with identical per-function counts. Production `exec_batch_prefetched` objects are linked directly into the serverless fixture; clocks are fixed, library bodies and fixture glue are excluded. Both namespaces/modes, batches 1/32, and MSET atomic 0/1 are covered. These are instructions, not cycles/op, IPC or rates. `docs/blockfix3/instructions/comparison-land.json`, `results-pre.json`, `results-land.json`, the build receipts and per-case trace digests bind the evidence to the final server hashes.

Counts below are total instructions in the production scope per batch; MGET/MSET use eight keys.

| Namespace | Command | 1s batch 1 PRE → POST | 2s batch 1 PRE → POST | 1s batch 32 PRE → POST | 2s batch 32 PRE → POST |
|---|---|---:|---:|---:|---:|
| normal | GET | 939 → 939 | 1559 → 1559 | 18578 → 18578 | 18423 → 18423 |
| normal | SET | 1068 → 1068 | 1688 → 1688 | 22706 → 22706 | 22551 → 22551 |
| normal | INCR | 1514 → 1514 | 2134 → 2134 | 37507 → 37507 | 37352 → 37352 |
| normal | MGET | 10243 → 10243 | 10243 → 10243 | 326598 → 326598 | 326598 → 326598 |
| normal | MSET atomic=0 | 10894 → 10894 | 10690 → 10690 | 348453 → 348453 | 341925 → 341925 |
| normal | MSET atomic=1 | 17049 → 17049 | 16695 → 16695 | 964030 → 964030 | 952702 → 952702 |
| db0 | GET | 818 → 818 | 1051 → 1051 | 18705 → 18705 | 18163 → 18163 |
| db0 | SET | 938 → 938 | 1171 → 1171 | 22545 → 22545 | 22003 → 22003 |
| db0 | INCR | 1313 → 1313 | 1546 → 1546 | 35074 → 35074 | 34532 → 34532 |
| db0 | MGET | 10362 → 10362 | 10362 → 10362 | 330406 → 330406 | 330406 → 330406 |
| db0 | MSET atomic=0 | 11135 → 11135 | 10954 → 10954 | 356165 → 356165 | 350373 → 350373 |
| db0 | MSET atomic=1 | 16466 → 16466 | 16135 → 16135 | 953558 → 953558 | 942966 → 942966 |

| Arm | Binary | SHA-256 | .text bytes |
|---|---|---|---:|
| PRE | `build/blockfix3/pre/tomokv` | `207adc87aaca14b4e0c9c54287a12a571bb1ed1fb00f86423e29114872fdd615` | 8470039 |
| POST | `build/blockfix3/post/tomokv` | `e18acab2bb97ff9f2d2c32901d7b50a8061e6ad15ca4c28a62b72a41a53701e1` | 8472919 |
| PAD-A | `build/blockfix3/pad-a/tomokv` | `754a9fe398e27cf7eaf267bf843d921da7794b2d2bac5cc4a4398395abd28636` | 8472919 |

PAD-A is **type A, behaviour twin**: PRE behavior with inert POST cold-statistics storage and matching total text size. POST and PAD-A both have 1,106,440 .bss bytes; PRE has 1,106,312. The 16-byte StatBaseline tail and two 8-byte stream counters per namespace are inert in PAD-A. Trailing NOPs preserve the compiler CET note. This controls total section sizes, not each function's address/alignment. `tools/blockfix3_pad.py` and `docs/blockfix3/binary-manifest.json` record construction. No PAD-B is requested. Superseded source trees and step traces are removed after their hashes/counts are recorded; `docs/blockfix3/cleanup.json` records cleanup. Source overlays can be recreated with `git archive 1932367f7` into `build/blockfix3/pre-source`, then `taskset -c 0-15 make -C build/blockfix3/pre-source -j16 all`. The rebuild has byte-identical PRE .text/.rodata/.data sections; its full-file digest differs in build metadata, recorded in `docs/blockfix3/pre-rebuild.json`. The frozen PRE binary retains its original digest.

### Correctness ledger

All lane builds, traces, correctness servers, oracles and harnesses are restricted to CPUs 0–15. Builds use at most `-j16`. Gate servers use 0–7, load uses 8–15, no SMT is added, and all listeners are within 20100–20199. The standalone reproduction uses 20190–20192; the harness socket fixture uses GATE_TEST_PORT=20199. The exact job selection is `docs/blockfix3/required-jobs.txt`; commands, environment, per-row ledgers and file digests are in the `land-*` gate receipts.

- **PASS — directed job:** all seven blockfix2 rows with controls enabled, covering 144 protocol legs plus four refusal-unit legs. The removal row passes all 24 legs and all 960 pipeline recreation attempts. Its original and boundary-only controls each reject all 24 legs. Selected NOGROUP Tcl tests pass POST and reject the statistics control in both modes. See `docs/blockfix3/removal-proof.json` and `gate-receipts/land-directed.json`.
- **PASS — complete Tcl negative control:** both full Tcl jobs run all 36 file/test executions. Each has exactly one named failure, the required XGROUP DESTROY test at its NOGROUP errorstat assertion. The control does not change the reply or remove the test. See `tcl-negative-proof.json` and `gate-receipts/land-tcl-negative.json`.
- **EXPECTED RED — PRE and PAD-A:** both complete jobs pass the same six earlier rows and reject the removal row in all 24 legs, specifically because the old waiter consumes the recreated stream. All 148 leg outcomes match: 124 pass and 24 expose the boundary defect. See `pre-pad-behavior.json` and `gate-receipts/land-{pre,pad-a}.json`.
- **PASS — hot-command cost:** all 48 final PRE/POST comparisons have identical totals and identical per-function counts.
- **PASS — build/freshness:** final `make -j16 all`, every production-unit prerequisite, and all 52 `make -q` checks. `freshness-binding.json` binds the final audit to POST e18acab.
- **PASS — harness units:** the quiet `tests/gates_test.py` rerun passes all 73 tests. The final `tests/redis_tcl_test.py` run passes all six tests, including the missing/failed/skipped assertion controls.
- **PASS — both differential engines:** io_uring and epoll each pass split and armed-fused modes, atomic 0/1, all standard seeds, repeated MULTI cases, read-local witnesses and mode equivalence. Each engine reports 235/239/231/235 successful internal checks for the four matrices, plus one equivalence check, with zero failures; each gate run reports six passing rows including release. Fixed seeds are 7, 19, 20 and 23; rotating seeds are 21 for io_uring and 22 for epoll. The standard armed matrix omits SORT; the separate cross-owner SORT job passes atomic 0 and 1. See `differ-{uring,epoll}-summary.json` and `gate-receipts/land-differ-{uring,epoll}.json`.
- **BROADER RUN — 535 passed / 4 failed:** all 67 selected/prerequisite jobs completed. This includes all 138 feature-battery rows, both engines' snapshot/AOF rows, the dedicated stream/removal/registry checks, and the blocking, notification and WATCH jobs. The four red rows are classified below; no red receipt is converted to a pass. See `gate-receipts/land-broad.json`.

The first broader POST Tcl run passed the required NOGROUP test, including its errorstats and commandstats assertions, in both modes. Split passed all 1661 required named tests. Fused passed 1660 and failed **PUSH resulting from BRPOPLPUSH affect WATCH**; fresh runs reproduce that assertion on PRE and POST, consistent with the owner-stopped asynchronous blocked-move ordering design. `compat2 autharity` was red only because it depends on the whole Tcl job: its four actual mode/engine protocol legs passed. The subsequent complete Tcl/compat2 job is green: **1661/1661 required named tests in each mode**, plus all three compatibility rows. See `tcl-positive-proof.json` and `gate-receipts/land-followup-tcl-compat2.json`.

The initial `trackfix_order` row stopped before runtime because its disposable source tree omitted `tools/assert_map.py`, now required by `make all`. The copy helper is corrected; its whole-job rerun passes all 16 legs, 30 checks each (`gate-receipts/land-followup-trackfix.json`, `tracking-schedule-proof.json`). The initial `execfair` row failed one 2s/uring/atomic=0 wave-8 leg at `BUSY Cross-shard script snapshot window is full`. Three subsequent whole-job PRE runs pass all 24 configurations, and the POST rerun passes all eight. **That original BUSY rejection remains unclassified; successful repeats do not establish its cause.** `execfair-diagnosis.json` identifies every receipt. No production change was made for these broader failures.

The bounded Tcl diagnoses establish three baseline failures without changing or excluding tests. In the original eight fresh-server repetitions per arm/mode/case, BLPOP slowlog rewriting failed PRE 1s once, POST 1s twice and POST 2s three times; Redis passed all eight. MONITOR failed POST 2s once; an additional 32 fresh PRE repetitions per mode reproduce it once in each mode, with an INFO frame preceding BLPOP. The WATCH comparison fails once in eight PRE 1s attempts and once in eight POST 1s attempts; both 2s samples and all eight oracle attempts pass. Pubsub passes all original focused attempts. These samples establish existence, not equal failure frequency. `tcl-diagnosis-summary.json`, the individual result files and the focused archives retain every result. The bounded whole Tcl/compat2 rerun subsequently passes without changing its assertions or manifest.

Historical evidence remains available. The first instruction-equal candidate failed one removal leg (2s, uring, databases 16, atomic 1), which exposed the cleanup gap and was fixed before the frozen final build. Its six earlier rows passed; the full Tcl modes passed the requested NOGROUP test but had unrelated MONITOR/pubsub/slowlog failures (`superseded-directed.tar.gz`). The 943f4ab checkpoint passed split Tcl and failed fused BLPOP slowlog rewriting; it was stopped at the INFO-default correction, leaving 46 passing and three failing/cancelled rows (`pre-default-cancelled-broad.tar.gz`). The initial gate-unit run had seven scheduler timeouts while compilation/tracing were active; its red log is retained alongside the quiet 73-test pass. An earlier gate prerequisite build was stopped after the instruction regression was found, before blocking/Tcl verdicts. An attempted DEL/RESTORE probe could not reach recreation because DUMP rejects streams (`ERR object could not be serialized`); the final extra probe uses RENAME. No serialization change or relaxed assertion was introduced.

The final artifact audit verifies all **70 latest requested job identifiers**, all 52 freshness checks, unchanged frozen hashes and production sources, and preservation of the six earlier probe bodies and Tcl inventory. `docs/blockfix3/final-verification.json` records the audit. Build usage is **22.431 GiB**; superseded source trees and instruction step traces are removed after their hashes/counts are recorded.

`EXPECT_QUICK` and `EXPECT_FULL` are unchanged. **DQ=0, DF=0** for blockfix3: the existing removal row is at line 3805, its job is collected at line 5673, and the quick-tier exit is at line 5837. The added control work stays inside that row. The inherited source inventory remains 813 quick / 830 full versus the unchanged constants 798 / 815; this continuation adds no rows and does not resolve that owner-owned reconciliation. `docs/blockfix3/preserved.json` records the line counts and unchanged blockfix2 probe functions and Tcl manifest.

### Maintainer merit request — NOT RUN in this lane

Use the frozen arms above with the gate's quiet-box ABBA instrument. `docs/blockfix3/merit.cells.txt` contains the 14 generic cells plus MGET/MSET p8 in both modes as nulls: the generic list already contains 1s MGET p8 (`m8g_l0`), so the added cells are `m05`, `m50`, `m53`, for 17 distinct cells. Keep matched geometry, offered load, connections, allocator, keyspace and instrumentation.

Collect contemporary PRE/PRE and POST/POST nulls, PRE/POST, and PRE/PAD-A. Report completed rate, cycles/op, instructions/op, IPC and the gate's latency scores per cell. Use the gate's existing per-cell null criteria; PAD movement limits attribution. Instruction identity is a cost check, not a throughput claim.

Performance benchmarks and full `tests/gate.sh iteration`: **NOT RUN**, reserved to the maintainer. The selected atomic_batteries job uses the existing `GATE_PROOF_NO_RATES=1` option: its correctness assertions run, and its pipelining speed comparison is explicitly skipped by the driver. That rate assertion is **NOT RUN** under this lane’s correctness-only authorization. The broad atomic battery also reports three inherited OFF-control assertions as SKIP because their race windows did not open: impossible SINTERSTORE image, RENAMENX losing race, and COPY losing race. Their trials ran, but those assertions are **NOT RUN / unproven**, not passing negative-control evidence (`docs/blockfix3/broad-skipped-assertions.json`). The blockfix2 controls requested for this lane have no such skipped legs. The two owner-stopped roots BLOCK-WAKE-ORDER-MULTI and BLOCK-CHAIN-ASYNC remain **NOT RUN** as acceptance work; this lane does not change their architecture or exclusions. No push or merge is performed.
