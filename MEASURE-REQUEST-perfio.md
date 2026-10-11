## perfio

Lane `cx-perfio`, worktree `/home/user/Projects/cx-perfio`; no push. **Fixes committed; quiet-box pfconfirm and the maintainer count update remain pending.**
PRE is merged `origin/cpp` **991d48f651d3c6e1324c061bd9ea801ac085afe8**,
built with `make -j16 BUILD_ROOT=build/perfio/pre all`. The requested pfconfirm
branch was merged and perfex commit `d867a1073` cherry-picked; this lane has not
edited `docs/pfconfirm`. Production changes are confined to the migration commit
in `src/core/io_loop.h`, stream metadata/delivery in `src/cmd/t_stream_groups.cc`,
and two existing compiler inlining budgets in `Makefile`. `origin/cpp` was fetched
and merged again after source commit `58f8f3188`; it remained at `991d48f65`
before the final proof. Tests and receipts were committed afterward without
further production changes.

All lane commands and children use CPUs 112–127; focused tests use target 112–119, oracle 120,
load 121–127, ports 25125–25149. The unchanged pfconfirm smoke helper assigns its load to 120–127. The task-specific PROOF authorizes these focused
live tests. No full gate or mainline merit run is being performed by this lane.

| Finding | PRE | POST | Gate row |
|---|---|---|---|
| IO4.19 FLIP | Stale interests 0 -> 145 -> 245 -> 311 -> 379 -> 479; up to 2.234 events/command; sixth FLIP refuses rollback reservation | 12 moving FLIPs, 201 connections: zero stale/duplicate interests; events/command 1.000 | `perfio stale epoll registration (epoll-flip)` |
| IO4.19 client-lb | Witnessed natural skew-driven move leaves a stale, duplicate interest | Natural move witnessed; 97 connections, zero stale/duplicate interests; events/command 1.000 | `perfio stale epoll registration (epoll-lb)` |
| PFDATATY.1 | Both modes fail the fixed 3 ms GET-after-XREADGROUP bound at 100k entries; metadata also differs from Redis | All 160 oracle checkpoints match. Fused row passes; split passes three fresh rechecks with the fixed 3 ms bound | `perfio XREADGROUP bounded delivery + Redis metadata (1s)` and `(2s)` |
| NT4.2 | Report only | No production parser change; counter-build patch and incidence driver under `docs/perfio` | None |

The same parameterized `tests/perfio.py` supplies PRE negatives and POST rows.
It derives from audit T16/T16b and shape T5/T13, owns its child PID and port, and
requires actual migration before inspecting `/proc/<pid>/fdinfo`. Socket inode
matching catches fd reuse; exact registration totals prevent vacuous audits.
FLIP collection retains every failed assertion while collecting event amplification,
then fails the row. Client-lb must move within 35 seconds; no missing window is skipped.
PRE receipts: `docs/perfio/pre-epoll-{flip,lb}-final.log`. Final POST receipts:
`docs/perfio/complete-epoll-{flip,lb}.log` (0.576 s / 5.157 s, respectively).
The same final stream row fails on PRE in both modes:
`docs/perfio/complete-pre-{1s,2s}.log`. Its metadata differences are logged before
the fixed latency assertion fails. POST receipts are `complete-post-1s.log` and
`split-row-recheck-{1,2,3}.log` (0.360 s fused; 0.428–0.643 s split).
All four new rows have a retained PRE failure and final-POST pass.

| Stream row stopwatch | 1k entries, median ms | 100k entries, median ms | 100k entries, maximum ms |
|---|---:|---:|---:|
| PRE fused | 0.132 | 22.928 | 33.506 |
| POST fused | 0.033 | 0.033 | 0.050 |
| PRE split | 0.126 | 24.905 | 36.523 |
| POST split, three fresh runs | 0.029–0.031 | 0.029–0.031 | 0.252 worst of three |

Each maximum is over 33 paired XREADGROUP/GET samples (99 across the split rechecks).
These are reproduction receipts, not a matched-load performance campaign. A prior
final-binary split trial **failed** at 3.245 ms; its 1k-entry control also stalled
at 3.357 ms. The failed trial is retained in `complete-post-2s.log`; subsequent
passes do not erase it. No assertion or threshold was relaxed.

The epoll fix explicitly DELs the reserved source interest before closing its dup.
Rollback already DELs the destination interest before closing the original fd and
adopts the still-registered source backup as the live fd. Removing that adopted
registration would break rollback. The wave-1 lifetime/pinning scheme is unchanged.

Stream delivery now advances the existing entries-read counter for delivered entries
only when the cursor and max-deleted ID make it usable. Otherwise it infers a value
only at known first/tail boundaries or returns unknown, using cached first ID,
entries-added and live length. XINFO GROUPS and XINFO STREAM FULL use the same guarded
lag semantics. No collection of every record remains in delivery or lag inference.
The stream seek still costs O(log macro-nodes), with bounded node decoding and work
proportional to delivered payload; the removed cost was O(total stream records).
There is no new state, layout or persistence format. Persisted existing counters are
validated by the same metadata guards after native DEBUG RELOAD.

`tests/fixtures/perfio-stream.json` was recorded from the pinned vanilla Redis
7.4.10 (`f103d127`) oracle. Controls cover ordinary delivery, XDEL ahead/at the cursor,
XTRIM including empty, XSETID, XCLAIM LASTID, XAUTOCLAIM deleted PEL entries,
explicit ENTRIESREAD, arbitrary/tail group cursors and native reload. Numeric controls cover INT64_MAX ENTRIESREAD, and XSETID ENTRIESADDED INT64_MAX followed by appends, including inferred negative counters at the new tail. Both XINFO
forms must agree with the fixture at all 160 checkpoints. DUMP of streams with groups
is unsupported by PRE; reload proof therefore uses each server's native snapshot (DEBUG RELOAD).

Gate accounting: DQ **+4**, DF **+4**. Two rows are emitted by `job_flip`,
two by `job_perfio_stream`; both collection sites precede the quick-tier exit at `tests/gate.sh:3733`.
The stream `row_begin` is at line 1595 (two MODE values), collected at line 3590;
the epoll `row_begin` is at line 2554 (two CASE values), collected through `flip`
at line 3672.
Starting values **625 / 642** require **629 / 646**. The arithmetic comment
is above the unchanged EXPECT assignments. All **646** fixture labels match the
source inventory. The unmodified `python3 tests/gate_ledger_fixture.py` refuses
solely because EXPECT_FULL remains 642, as the owner-only count rule requires.
The stream timing job waits for ordinary jobs, before the existing atomic timing
job, to preserve its fixed 3 ms bound without a dependency cycle.

Initial reserved-core runs overlapped other compilers and lane servers; even XLEN
controls had millisecond scheduling stalls. Later pfconfirm screens also reported
excess selected-core CPU activity. A quiet window was requested. The strict timing
failures are retained, and mainline quiet-box confirmation remains required.

**NT4.2 static inventory** (16,384-byte initial receive buffer):

| Cell file | Cells | Largest scored frame: arguments / bytes | Largest pipeline bytes |
|---|---:|---:|---:|
| `tests/headline_cells.txt` | 181 | 17 / 759 (8-key MSET) | 97,152 |
| `/tmp/claude-1000/generic_merit_cells.txt` | 14 | 9 / 190 (8-key MGET) | 4,480 |
| `tests/netio_cells.txt` | 32 | 3 / 106 (SET) | 3,392 |
| `tests/ttl_cells.txt` | 2 | 4 / 117 (wire SETEX) | 3,744 |
| `tests/mkprobe_cells.txt` | 19 | 17 / 759 (8-key MSET) | 97,152 |
| `docs/pfconfirm/cells.txt` | 12 | 17 / 735 (8-key MSET) | 3,392 |

Sizes use the maximum generated key length and describe requests. `GET:1024`
and TLS `GET:4096`/`GET:16384` remain two-argument GET requests. The
`tracking-mset1024` cell has 1024 resident keys, not 1024 arguments.
The additional requested SET:1024 probe has 3 arguments / 1,068 bytes
(34,176 bytes at p32). The TLS GET probes have 2 arguments / at most 32 bytes
(1,024 bytes at p32); their 4/16 KiB payloads are replies.
REORDER's 256 KiB values and TLS 4/16 KiB population SETs exceed the initial
receive buffer during setup, outside scored traffic. A pipeline consists of
separate frames. Remaining buffer space can be smaller than capacity and TCP/TLS
can fragment any frame. No supplied scored cell resembles the audit's 2M-argument
frame. File hashes and every cell: `docs/perfio/nt4-frame-inventory.json`.
The temporary generic cell file is copied to `docs/perfio/generic_merit_cells.txt`.

`docs/perfio/nt4-counters.patch` is applied only in `build/perfio/nt4-source`;
no production parser change. It counts multibulk Incomplete results and completed
arguments discarded in those attempts, which successful drained commands must
parse again. This conservative argument count excludes unfinished bulk-header
work. Counters occupy separate cache lines per IO owner; INFO snapshots bracket
load, after population. `docs/perfio/nt4_probe.py` drives SET:1024 p32, eight-key
MSET p8, and TLS GET 4/16 KiB p32 with 1/512 connections, both modes, at least one
million completed commands per cell. A forced-split MSET must fire the observer.
Observed incidences below are normalized per one million completed commands.
These are request-shape probes on the reserved CPUs: eight server cores, 16
shards, 6:2 split or fused, read-local 0, atomic 1, default-on key/client balancing,
io_uring; seven separate load cores. They are not a replay of the full paper
campaign (the checked-in ABBA geometry pin is 32 cores, outside this lane's allowed
CPU range). The six listed frozen files contain no TLS or SET:1024 row; those
additional shapes were explicitly requested for this investigation.
Each cell completed 1,000,000 commands (one connection) or 1,000,448 (512 connections).
The forced-split MSET observer control passed in both modes. Full command lines,
denominators and raw JSON: `docs/perfio/nt4-counts/results.json`;
memtier console logs are retained byte-for-byte as `.load.log.gz`.

| Request shape | Mode | Connections | Incomplete attempts / 1M commands | Completed arguments re-parsed / 1M commands |
|---|---|---:|---:|---:|
| SET-1024-p32-c512 | 1s | 512 | 3,435,280.99 | 6,790,557.83 |
| MSET-64-p8-c512 | 1s | 512 | 27,034.89 | 195,364.48 |
| GET-4096-p32-c1-tls | 1s | 1 | 0.00 | 0.00 |
| GET-16384-p32-c1-tls | 1s | 1 | 0.00 | 0.00 |
| GET-4096-p32-c512-tls | 1s | 512 | 0.00 | 0.00 |
| GET-16384-p32-c512-tls | 1s | 512 | 0.00 | 0.00 |
| SET-1024-p32-c512 | 2s | 512 | 18,777,242.80 | 37,554,356.65 |
| MSET-64-p8-c512 | 2s | 512 | 407,866.28 | 2,458,386.64 |
| GET-4096-p32-c1-tls | 2s | 1 | 0.00 | 0.00 |
| GET-16384-p32-c1-tls | 2s | 1 | 0.00 | 0.00 |
| GET-4096-p32-c512-tls | 2s | 512 | 0.00 | 0.00 |
| GET-16384-p32-c512-tls | 2s | 512 | 0.00 | 0.00 |

**NT4.2 answer: yes.** Eight-key MSET p8 is present in the frozen headline
inventory (`m05`/`m53` and other mode/lane variants), and its request shape fires
the incomplete-frame path in both modes. SET:1024 p32 was specifically requested
as a stress cell; it is absent from the six supplied frozen files (the generic
file contains GET:1024). Its counts must not be attributed to a nonexistent paper
SET cell. TLS 4/16 KiB are response payloads: the scored GET requests remain tiny;
all eight measured TLS cases had zero incomplete attempts.

**Recommend a separate resumable-multibulk fix:** the owner's paper-path condition
is met. This lane makes no production parser change. These counts establish path
reachability and redundant argument work, not a throughput or latency improvement.
The observer adds atomic stores, can perturb scheduling, and counts repeated
Incomplete returns even without a new packet when a buffered tail is retried during
other progress. Ratios exceeding one attempt per completed command are therefore
possible. A subsequent fix still needs matched-load cycles/op, IPC and rate proof;
none of these paper cells establishes the audit's million-argument neighbor stall.



**Reproduction and mainline handoff:**

```sh
# Repeat these identical rows for PRE build/perfio/pre/tomokv and POST build/tomokv.
taskset -c 112-127 taskset -c 121-127 python3 tests/perfio.py epoll-flip --binary build/tomokv \
  --port 25125 --cores 112-119 --output docs/perfio/recheck-flip
taskset -c 112-127 taskset -c 121-127 python3 tests/perfio.py epoll-lb --binary build/tomokv \
  --port 25125 --cores 112-119 --output docs/perfio/recheck-lb
# Repeat for both --mode 1s and 2s.
taskset -c 112-127 taskset -c 121-127 python3 tests/perfio.py stream --mode 2s --net-io uring \
  --binary build/tomokv --port 25125 --cores 112-119 --output docs/perfio/recheck-stream

taskset -c 112-127 docs/pfconfirm/run.sh --smoke --only PFDATATY.1 \
  --binary build/perfio/pre/tomokv --sha256 2df27d40b773ddbfc46f9bd68518d2f3adc98eabc66422c3b7d0e2be3c695f52 --port 25145 \
  --output docs/perfio/pfconfirm-smoke-pre-quiet-retry
taskset -c 112-127 docs/pfconfirm/run.sh --smoke --only PFDATATY.1 \
  --binary build/tomokv --sha256 d8c2bb2d5488c6fa6b09618aac1fae24d716f20ed78c2b8b5c5b491e90daef35 --port 25145 \
  --output docs/perfio/pfconfirm-smoke-post-quiet-retry
# Maintainer's full quiet-box merit run, outside lane authorization:
docs/pfconfirm/run.sh --only PFDATATY.1 --binary build/tomokv \
  --sha256 d8c2bb2d5488c6fa6b09618aac1fae24d716f20ed78c2b8b5c5b491e90daef35 --output docs/perfio/pfconfirm-full-post-d8c2bb2d-quiet
# Required full verdict: NOT CONFIRMED on POST; mainline also runs a performance null.
```

**Default-build identity (final production source `58f8f3188`):**

| Inventory | Equal / compared | Result |
|---|---:|---|
| `lbstall_artifacts.py compare`, `tomo` | 601 / 601 | Instructions and resolved targets equal |
| Same, `tomo_db0` | 603 / 603 | Instructions and resolved targets equal |
| `ccfix_audit.py` extended hot set, both namespaces | 1,208 / 1,208 | No changed hot body |
| Full function inventory | 16,376 / 16,444 | 68 changes listed individually |
| Command handlers (including stream handlers) | 1,187 / 1,211 | All 24 differences are stream-group handlers |
| Eight layout locks, both namespaces | 16 / 16 | Sizes and every named field offset equal |
| Expanded layout inventory | 32 / 32 | Sizes and fields equal |
| Linked `.text` | 7,646,972 -> 7,647,452 bytes | +480 bytes; linked runtime sections differ |

Of the 1,204 lbstall hot bodies, 1,196 are also raw-byte identical; the other
eight differ only in encoded addresses whose resolved targets remain identical.
Every changed function and its reason is in
`docs/perfio/identity/changed-bodies.tsv`; `hot-changes.tsv` has no data rows.
47 changes are in the two stream-group objects. 21 are in IO/core objects: the
explicit epoll cleanup and compiler inlining/code-generation effects. Those
include unchanged-source pubsub, atomic-collapse and snapshot-write helpers
outside the tools' HOT set; the inventory does not hide those differences.
The raw `ccfix_audit.py` exit is **1**, because its hard-coded handler whitelist
permits only ACL/CONFIG/INFO edits, not this requested stream edit. Its hot-body
assertion passes. `linked_bytes.py` exits **1** because changed production code
and its relocations make linked runtime sections differ. Neither is reported as
an all-bodies/all-sections identity pass.

Initial epoll cleanup changed three ordinary hot bodies through GCC inlining.
Compile-only probes restored all three by adding 12 to the existing rl2s(src)
and genthread(db0) `large-unit-insns` budgets; the cold DEL adds 8 IPA instructions.
No runtime knob was added. Probe receipts: `docs/perfio/inline-probe.json`.
No data-layout change or PAD arm is submitted. The +480 bytes of text and remaining
non-HOT code-generation changes are why the mainline performance null is still
required; hot-body identity alone is not a throughput result.

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE, `991d48f651d3c6e1324c061bd9ea801ac085afe8` | `build/perfio/pre/tomokv` | `2df27d40b773ddbfc46f9bd68518d2f3adc98eabc66422c3b7d0e2be3c695f52` |
| POST, source `58f8f3188` | `build/tomokv` | `d8c2bb2d5488c6fa6b09618aac1fae24d716f20ed78c2b8b5c5b491e90daef35` |

**Completed build proof:** `make -j16 all`, all 29 targets from
`job_production_units`, and `mdbqsbr-live-arms` build successfully. `make -q`
reports current for all 29, `all`, park and no-wake arms. Exact target list and
return codes: `docs/perfio/production-targets.json` and
`docs/perfio/production-complete-results.json`. `wbland_checks.py check clauses`
passes 83/83 (`wbland-complete.log`). Shell syntax, Python compilation and `git diff --check` for source/harness files
also pass. The raw patch and captured console logs retain their original whitespace.
Earlier overlapping builds and deadline-only scheduler failures remain in historical receipts; the final serial proof below
supersedes them only where it actually passes.

**Focused final proof:**

| Check | Result / receipt |
|---|---|
| `python3 tests/gates_test.py` | **66/66 PASS**, `gates-test-complete.log` |
| `python3 tests/wbland_checks.py check clauses` | **83/83 PASS**, `wbland-complete.log` |
| Redis differential, split 6:2 / 16 shards | **24/24 PASS**, `differ/complete-split.log` |
| Redis differential, armed fused | **32/32 legs + 2/2 lane witnesses PASS**, `differ/complete-armed-fused.log` |
| `tests/flip_close_controls.py` | Positive and deliberate-removal negative both expected, `flip-close-complete.log` |
| `netio.py`, both modes × epoll/uring | **4/4 PASS**, `batteries/results.json` |
| `flip.py` and `flip_under_load.py`, epoll/uring | **4/4 PASS**, same receipts |
| `lb_stationary.py`, both modes × epoll/uring | **4/4 PASS on fresh boots**, `isolated-lb/all-results.json` |
| Four added gate rows | All fail PRE and pass POST; receipts above |
| Ledger inventory | **646 source labels = 646 fixture labels**; CLI refuses unchanged EXPECT_FULL=642 |

Differential commands used seeds **7, 19, 20, 23**, atomics **0/1**, target
**112–119**, oracle **120**, load **121–127**, ports **25130/25131**, and the
unmodified focused interface of `tests/differ_gate.sh`. Requested suites were
`stream`, `streamgrp`, `blocking`; armed fused also ran `string` to fire the
mandatory read-local witness, since the three requested suites alone produce no
lane-eligible reads. No witness was disabled. Suite/seed files are under
`docs/perfio/differ/`. Reproduction:

```sh
taskset -c 112-127 env REDIS74_ROOT=/home/user/Projects/redis74 \
  GATE_LOAD_CORES=121-127 GATE_DIFFER_ORACLE_CORES=120 \
  GATE_DIFFER_GEOMETRY=split \
  GATE_DIFFER_PROOF_SUITES="$PWD/docs/perfio/differ/suites.txt" \
  GATE_DIFFER_PROOF_SEEDS="$PWD/docs/perfio/differ/seeds.txt" \
  GATE_DIFFER_OUT="$PWD/build/perfio/differ-recheck-split" \
  bash tests/differ_gate.sh "$PWD/build/tomokv" 25130 25131 112-119 6:2
# Armed twin: GEOMETRY=armed-fused, suites=armed-suites.txt, a fresh OUT directory.
```

The first scheduler run under compiler contention failed six deadline checks;
a later four-core run passed 65/66 and hit the one-slot fixture deadline. The final
16-core run passed 66/66 with unchanged assertions. One earlier stationary-LB
trial moved a bucket after the proof helper reused the server after `netio.py`.
The helper now boots each battery separately, as the gate does. The stationary
checks were repeated on fresh boots with their full 12-second stabilization and
30-second assertion windows; no move was admitted or window shortened.

**Pfconfirm smoke is not complete.** The unmodified quiet-box precondition refused
all attempted runs, before any candidate workload. Initial PRE / POST screens
reported **1.420 / 0.540 CPU seconds**, against **0.480 per 20 seconds**. The first final-binary PRE / POST attempts reported **4.630 / 5.120 CPU seconds**
against the same budget. After this lane's other work stopped, one final bounded
attempt still measured **16.350 / 16.400 CPU seconds** and refused both arms.
All exits are **3 / REFUSED**, in
`docs/perfio/pfconfirm-smoke-{pre,post}.log` and
`docs/perfio/pfconfirm-smoke-{final,quiet}-{pre,post}.log` and their `quiet.json` /
`campaign-error.json`. There is **no SMOKE_OK** receipt, and **no full NOT CONFIRMED
verdict** yet. The concrete retry and mainline commands above use the final digests
and fresh output paths. `docs/pfconfirm` is unchanged after the requested merge and
perfex cherry-pick.

Maintainer handoff: obtain SMOKE_OK on both arms on a quiet box; run full
PFDATATY.1 and require **NOT CONFIRMED on POST**; run the main-command performance
null; change EXPECT to **629 / 646** and run the full gate. This lane has not run
the full gate or mainline merit campaign and has not pushed.
