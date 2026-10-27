## blockfix2

Branch `cx-blockfix2`, based on `83e0b809d` (wave 8). No push. Six roots are implemented. Stream removal is partially fixed, with a newly exposed pipelined delete/recreate boundary still failing; two ordering roots are stopped for an owner architecture decision. The Tcl job is **not green**: the newly unblocked XGROUP DESTROY test reaches the separate, deliberately unimplemented INFO error/command statistics surface. No throughput or latency merit claim is made.

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

Eighteen named Tcl failures were promoted to mandatory assertions; their exact mapping is `docs/blockfix2/tcl-promotions.json`. The two stopped roots remain on the named failure list. One slowlog test runs unchanged on a fresh server because an earlier required test leaves slowlog-max-len at zero and the independently failing reset test is skipped. Its name and complete assertion inventory remain mandatory; absence, skip, or failure is red.

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
- FAIL, retained: the first broad run has 102 passing and 19 failing rows. Seventeen failures explicitly refuse stale/missing production-unit readiness markers after the last source rebuild; the queued final run rebuilds and verifies these prerequisites. Two failures are the Tcl modes described below.
- PASS: all 52 make -q freshness checks (`docs/blockfix2/production-freshness.json`); rebuilt debug-0/1 (32 rows), fused-0/1 (18 rows), atomic_units (27 rows).
- PASS: both standard differential matrices, split/fused-armed and atomic 0/1, plus mode equivalence. Fixed seeds are 7, 19, 20, 23; the gate selected rotating seed 21 for uring and 22 for epoll. The original suite skips SORT in fused parts; the separate fused SORT job passes atomic 0 and 1.
- PENDING final receipt: final directed/planted-control job; PRE/PAD directed jobs; full feature batteries, compat3 and fused notify.
- Gate plans, exact per-row ledgers, stdout, Tcl events and individual differential transcripts are archived with file digests in `docs/blockfix2/gate-receipts/index.json`. Red initial runs remain in that index.

The complete Tcl job ran 35 files plus one isolated required test in each mode. Each mode passed 1659/1661 required assertions. Both fail `XGROUP DESTROY should unblock XREADGROUP with -NOGROUP` at `errorrstat NOGROUP`; its later commandstats assertion also needs the documented INFO-CMDSTAT-FIELDS root. The source deliberately omits unimplemented failure/timing counters (`src/cmd/t_server.cc`), so this lane does not fabricate them. The waiter now gets the exact Redis NOGROUP reply.

The other observed Tcl failures were split `BRPOPLPUSH does not affect WATCH while still blocked` and fused `PUBLISH/SUBSCRIBE after UNSUBSCRIBE without arguments`. Both reproduced on frozen PRE in bounded fresh-server reruns (one failure in eight attempts each); Redis passed, and the eight focused POST reruns each passed. The original complete-job failures remain red. Raw transcripts and hashes are in `docs/blockfix2/tcl-extra-replay.json` and its compressed raw file.

`EXPECT_QUICK` / `EXPECT_FULL` are untouched. **DQ=+7, DF=+7**: the seven literal rows at `tests/gate.sh:3788–3801` are collected by `collect_job blockfix2` at line 5658, before the quick-tier exit at line 5822. Baseline source inventory was already 806/823 while constants still read 798/815. This lane’s source/fixture inventory is 813/830; those are the owner’s required reconciled counts. Adding only seven to the stale constants would leave an existing eight-row deficit. The static ledger checker consequently remains red solely on EXPECT_FULL’s count; labels match the source inventory.

### Maintainer merit request — NOT RUN in this lane

Run the gate’s own quiet-box ABBA instrument against the frozen binaries above. `docs/blockfix2/merit.cells.txt` preserves the current 14 generic cells from `tests/wbland_merit_cells.txt`, adds 2s GET/SET p1/p32 null cells (`h53 h54 h21 h22`), and adds MGET/MSET p1/p32 in both modes (`m01 m03 m04 m06 m49 m51 m52 m54`) for the touched scatter/atomic publication path. Keep identical geometry, connections, allocator, keyspace, instrumentation and offered load.

Collect contemporary PRE/PRE and POST/POST nulls, PRE/POST, and PRE/PAD-A. Report per-cell completed rate, cycles/op, instructions/op, IPC and the instrument’s latency scores. Apply the gate’s existing null acceptance criteria independently per cell; do not average away a regression. PAD movement limits attribution. Instruction savings alone do not establish a win.

Also measure the touched cold surfaces in both modes and engines, with atomic 0/1: (1) existing benchtxn BLPOP/LPUSH wake pairs at 1/32/512 pairs, slowlog -1 and 0; (2) RENAME and SORT STORE creating a waiting BLPOP/BLMPOP key; (3) XREADGROUP wake by XADD versus DEL, SET, MSET, FLUSH and XGROUP DESTROY; (4) a wrong-type blocked move followed by a valid waiter; (5) INFO CLIENTS with 0/1/64/1024 blocked clients, including duplicate and distinct keys; (6) EXEC containing XREADGROUP BLOCK with empty and populated streams. For the existing wake cell use `benchtxn blpop HOST PORT SECS PAIRS THREADS`, with PAIRS=1/32/512 and THREADS=1/8/8 respectively; use the gate’s duration and offered-load instrument. Count completed wake round trips separately from their two commands. For the remaining protocol cells, `tests/compat3_blockfix2.py` supplies the exact command sequences and oracle assertions. Count completed logical operations and keep producer/consumer accounting separate. PRE hangs or wrong replies are correctness failures, never throughput samples or wins. The request does not claim those custom protocol cells are already supported by the stock ABBA cell parser.

Performance benchmarks and `tests/gate.sh iteration`: **NOT RUN**, reserved to the maintainer by the task. The two stopped ordering roots and the remaining stream-removal command boundary: further implementation and POST passing proofs **NOT RUN**, awaiting the owner’s design decision. No push or merge was performed.
