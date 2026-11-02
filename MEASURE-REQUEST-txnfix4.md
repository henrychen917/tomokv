# Round-5 multi-key, WATCH and capture fixes

## txnfix4

All five items are fixed or repaired, plus one more CD5.4 data-loss path this lane found and
closed. GET, SET, INCR, MGET and MSET execute exactly PRE's instructions in all 48 serverless
command-scope cases. Two pre-existing server-wide hangs outside the brief were found and are
reported below, not fixed. This is a selected-job proof, not a full-gate receipt.

Branch `cx-txnfix4`, PRE `9d6ab5526` (wave-14 integration), POST = HEAD of the branch. No push.
Correctness work ran on CPUs 61-73 (servers 61-68, load 69-73), ports 21400-21499,
`LC_ALL=C`, 16 shards, split ratio 6:2. Builds used `-j13`.

### Items

Each witness row is one `tests/gate.sh` job (`txnfix4-*`) that boots eight TomoKV legs itself
(2s and 1s, atomic 0 and 1, 1 and 16 databases; the 1s 16-database legs arm read-local) plus
the Redis 7.4 oracle, and proves its placements with `DEBUG SHARDS` on the final key names.
PRE counts are per engine (uring and epoll were identical).

| Item / gate row | PRE witness | POST result | Mechanism changed | Residual |
|---|---|---|---|---|
| CD5.4 data loss / `txnfix4-oom` | 1 of 9 legs pass (only Redis): 856 of 1,208 checks fail, 80 of them the new `record` shapes. Auditor L-T3: 9 lost elements per atomic-0 leg, 3 (same-shard) per atomic-1 leg; L-T3b 6 and 6 | 9 of 9 legs on uring and epoll: 1,208 checks, 0 failures, including all 80 `record` shapes with the window proved. Auditor L-T3 0 lost; L-T3b 0 and 0 | Non-DENYOOM movers (SMOVE, RENAME, RENAMENX, MOVE) are never refused for memory: every mover install runs under `MoverMemoryScope` (the owner's shard budget lifted for that owner task, the FUNCTION precedent). This covers the atomic-0 element-mover hop two, the atomic-0 RENAME/RENAMENX/MOVE hop two including its MVCC clone (new cold `execute_plain_image_hop`), the same-shard local lowering and the atomic-1 group apply. DENYOOM movers (LMOVE, RPOPLPUSH, BLMOVE, BRPOPLPUSH) are admitted on every participating owner before any change: in atomic-0 hop one (cold `admit_denyoom_mover`), and in atomic 1 before the undecided group installs, where a refusal aborts it whole | A lifted install may overshoot the budget by one move; the eviction cycle and the next gated write pay it back, as for FUNCTION. L-T3b under allkeys-lru reports the same 3 same-shard "losses" on PRE and POST: its fill evicts the source before the command runs (see auditors) |
| CD5.5 lost update / `txnfix4-watch` | 5 of 9 legs: every atomic-1 leg fails 8 scenarios (32 per engine). Auditor L-T4 2 lost updates per atomic-1 variant, L-T5 10, Z-T5 10 of 25 differences | 9 of 9 legs on uring and epoll: 600 checks, 0 failures. Auditor L-T4 0, L-T5 0, Z-T5 0 of 25 | `watch_execute_scatter`: a bare atomic multi-key pop's phase two reports its WATCH effect at once, as LPOP does. EXEC children still decide with their parent; other atomic groups keep the deferred reservation | None |
| CD5.6 crash / `txnfix4-crash` | Headline 105c5818cc aborts on iteration 1. PRE has no abort but 5 of 9 legs pass: each atomic-1 leg fails all six shapes (24 per engine; watched EXEC commits over the pop and reservations leak) | 9 of 9 legs on uring and epoll: 9,612 checks (six shapes x 200 iterations x 8 legs), 0 failures, 0 coexisting reservations. Abort-site witness 200 of 200 per mode, no abort, 0 watched EXECs committed | No new code: the root is CD5.5's never-decided pop reservation (see below) | None |
| CD5.3 stale read, lost write / `txnfix4-hash` | 1 of 9 legs (all TomoKV legs fail). Serverless fixture 2 of 16 commands match an uncaptured shard. Auditor H-T6 stale hits 51/92/1 | 9 of 9 legs on uring and epoll; serverless fixture 16 of 16 in both namespaces. Auditor H-T6 0 stale hits | `hash_ttl_on_access`: during a capture, a read-only hash command answers from hexpread's filtered reply-only view (`hash_capture_reply`), and a write reaps (the capture gate pre-images its key first). AOF rewrite shares the snapshot capture (snapshot.cc:329) | The AOF-rewrite capture probe could not run to completion (AOF large-value hang below) |
| TM5.1 test gap / `txnfix4-placement` | Test-only: with PRE's `tests/execfix.py` the final witness passes 0 of 8 legs (planted single owner accepted; live "two-owner" pair on one owner). Auditor T1 reproduces it on the first boot | 8 of 8 legs on uring and epoll. Auditor T1 finds no single-owner pair in 16 fresh boots | `execfix.py` proves two owners (DEBUG SHARDS) on the final names and refuses a planted single-owner geometry (`--self-test`) | None |

### Additional CD5.4 path (found and fixed here)

98463e5328 documented a narrow residual; it is real and deterministic. When the destination or
the source of a two-hop RENAME, RENAMENX or MOVE at atomic 0 holds a decided MVCC record at hop
two, `begin_plain_version` admits a clone of that key against the budget before `apply_image`
runs. Under maxmemory the clone is refused: the command replies `ERR out of memory` while the
other owner has already erased the source (value lost) or installed the destination (value
duplicated). The oom row's new `record` sub-case produces that state on demand: a committed
MULTI/EXEC write leaves the record, and a cross-shard read parked with DEBUG
ATOMIC-FANOUT-DEFER pins the read floor, so the record cannot collapse. The window is proved
with execiso's pinned-old oracle (the same EXEC rewrites both keys of the parked read). The
previous POST failed all 12 shapes (8 with one database) on every atomic-0 leg, 2s and 1s.
Fix: the atomic-0 phase two of RENAME, RENAMENX, MOVE and COPY now runs in the cold,
out-of-line `execute_plain_image_hop`, reached through `execute_plain_element_mover` by one
contiguous kind range. For the renames the whole owner pass, clone included, runs under
`MoverMemoryScope`; COPY keeps every budget check. Three other placements moved DB0 MSET by
+8 to +15 instructions per command (`docs/txnfix4/placement-trials`).

### The stalled WIP variant (kept)

The WIP at 2b09a6f765 moves the atomic-0 DENYOOM admission out of `xshard_execute`'s phase-one
probe loop into the cold `admit_denyoom_mover`. It is needed: the 98463e5328 tree without it
runs DB0 MSET at atomic 1 with +744 instructions per 32-command batch (both modes), and the
normal namespace with -24/-768 (`docs/txnfix4/instructions-novariant`). With it, all 48 cases
equal PRE. Behaviour is the same except precedence: a refusal now reports Maxmemory even if the
probe also failed an allocation, which matches Redis's refusal before running. Its compile-only
budget trials were retired; no Makefile budget changed.

### CD5.6: abort site and root

`tools/txnfix4_abort_site.py` runs Z-T6's `mpop-watch-then-tracking` under gdb. On the audited
headline 105c5818cc it aborts on iteration 1 in both modes at `tracking.cc:69`. There
`tracking_read_marker` is a sentinel handler whose body is `std::abort()`. It is reached
through `watch_execute_handler` (`watch_modified.inc:45`) from `ex_execute.inc:239`, which
routes any command through `handler_notify` while `has_watches()` is true. CD5.5's
never-decided pop reservation kept `has_watches()` true after the watcher's EXEC, so a tracked
read on that shard ran the sentinel. Wave 14 (clientcompat 4cd88019ec) turned the sentinel into
a forwarder, so PRE no longer aborts but still commits every watched EXEC over the pop and
leaks reservations.

Confirmation, 200 iterations of each scenario:

* Abort-site witness: POST and the headline plus only the CD5.5 change run 200 of 200
  iterations per mode with no abort, and every watched EXEC aborts (0 committed). The headline
  alone dies on iteration 1.
* Six-shape crash case (`tests/txnfix4.py --case crash`) on the headline plus only CD5.5: the
  two post-EXEC shapes pass 200 iterations on every leg, where the plain headline dies on
  iteration 1 at atomic 1. `mpop-watch-noexec-tracking` still aborts there on every leg,
  because its WATCH is still live, so `has_watches()` is legitimately true and reaches the same
  sentinel without any leaked reservation. That second root is the one PRE already removed.
* POST, with both fixes, passes all six shapes x 200 iterations on every leg with no
  coexisting reservations (crash row above).

### Auditor reruns

`tools/txnfix4_auditors.py` runs the auditors' own scripts from `round5-read/tests/cmd-data`
and `testmap`, unchanged except ports, CPUs and the binary under test. Receipts are in
`docs/txnfix4/auditor-reruns/{pre,post,pre-t1,post-t1}`.

| Auditor test | PRE | POST |
|---|---|---|
| L-T3 lost elements (2s a0, 2s a1, 1s a0, 1s a1) | 9, 3, 9, 3 | 0, 0, 0, 0 |
| L-T3b lost elements (noeviction, volatile-lru) | 6, 6 | 0, 0 |
| L-T3b allkeys-lru | 3 same-shard | the same 3: the 600-key fill evicts the least-recently-used source before the command (BLMOVE nil, RENAME `no such key`, SMOVE 0), as in the auditor's own headline receipt |
| L-T4 lost updates, 129 cases per variant (atomic-1 variants) | 2, 2, 2 | 0, 0, 0 |
| L-T5 mismatches (atomic-1 variants) | 10, 10 | 0, 0 |
| Z-T5 differences of 25 (atomic-1 variants) | 10, 10 | 0, 0 |
| Z-T6 (19 scenarios) and G-X1 (6 boots): server deaths | 0 of 25 (PRE already has the wave-14 forwarder) | 0 of 25 |
| H-T6 stale hits (1s, 2s, 1s atomic 1 192 MiB); Redis 0 | 51, 92, 1 | 0, 0, 0 |
| T1: execfix "two-owner" pair on one owner, battery still passing | reproduced on boot 1 (shards 2 and 14, owner 6) | none in 16 fresh boots |

### Command-scope instruction counts (zero cost)

`tools/txnfix4_scope.py` links the PRE objects and the POST objects to the same serverless
fixture (`tests/txnfix4_scope.cc`) and counts executed in-image instructions of the production
routines under gdb, with deterministic clocks, slowlog -1 and read-local 0. There is no socket,
load generator or rate. Receipts, per-function counts and probe/server SHA-256s are in
`docs/txnfix4/instructions` (`comparison.json`).

| Command | Paired cases | PRE total range | POST | Added instructions |
|---|---:|---:|---|---:|
| GET | 8 | 783 - 18,482 | identical in every case | 0 |
| SET | 8 | 894 - 21,394 | identical in every case | 0 |
| INCR | 8 | 1,244 - 36,547 | identical in every case | 0 |
| MGET | 8 | 9,995 - 322,822 | identical in every case | 0 |
| MSET (atomic 0 and 1) | 16 | 10,379 - 959,774 | identical in every case | 0 |

Cases: normal and DB0 namespaces, 1s and 2s, batch 1 and 32 (MGET/MSET over eight shards).
Per-function counts are equal too. Quantified scopes (atomic 0 and 1 give the same values):

| Scope | Namespace | Batch 1, PRE -> POST (1s / 2s) | Batch 32 change |
|---|---|---|---:|
| Uncontended EXEC (MULTI/INCR/EXEC) | normal | 23,315 -> 23,316 / 23,270 -> 23,271 | +1 |
| Uncontended EXEC | DB0 | 22,024 -> 22,023 / 21,966 -> 21,965 | -63 |
| Two-owner EXEC | normal | +1 / +1 | +8 |
| Two-owner EXEC | DB0 | -1 / -1 | -56 |
| Two-key LMPOP (atomic 0; atomic 1) | normal | 3,246 -> 3,250; 3,544 -> 3,548 | n/a |
| Two-key LMPOP | DB0 | 3,279 -> 3,283; 3,576 -> 3,580 | n/a |
| Two-shard SMOVE (atomic 0; atomic 1) | normal | 2,515 -> 2,519; 3,637 -> 3,641 | n/a |
| Two-shard SMOVE | DB0 | 2,553 -> 2,526; 3,670 -> 3,643 | n/a |

Instruction counts do not establish rate or cycles/op changes; no throughput claim is made.

### Gate selections, differential, Tcl, units and freshness

Every selection ran through `tests/gate.sh full` with `GATE_ONLY_JOBS`
(`tools/txnfix4_proof.py`: server CPUs 61-68, load 69-73, ports 21400-21499,
`GATE_PROOF_NO_RATES=1`) against POST `e23c2fb37cd0`. Logs, ledgers, JSON summaries and
tarballs are in `docs/txnfix4/gate-receipts`; the job lists are in
`docs/txnfix4/required-jobs-*.txt`. These are selected jobs, not a full-gate receipt.

| Selection (receipt) | Engine | Jobs | Rows passed | Rows failed |
|---|---|---:|---:|---:|
| The five witness rows (`post-final-witness-*`) | uring, epoll | 6 each | 6, 6 | 0, 0 |
| Lane: multi, WATCH, txnorder (all), debug-0/1 (execfix, multirace), execfair, exec1s, atomics, maxmemrace, movers, list/set/hash-TTL, tracking, notify/keyspace, flush, blocking, rootcompat, release batteries (`post-lane-uring`) | uring | 61 | 224 | 3, explained below |
| Unit rows re-run after 1db9f6a650: atomic_units, wait_units (`post-units-rerun-uring`) | uring | 5 | 30 | 0 |
| Wide: at412 T1-T16 and owner, evict lruclock/lfu, multidb, snapfix/snapfix2, persistfix2, aof_frame, aoforder, notify_aof, persistfmt, feature split/armed, fused, atomic batteries (`post-wide-uring`) | uring | 56 | 269 | 0 |
| Engine-named jobs (multifix and climonfix4 for 1s/2s x uring/epoll; snapshot and aof for both engines), redis_tcl, differ (`post-engine-oracle-uring`) | uring | 19 | 200 | 0 |
| redis_tcl and differ (`post-oracle-epoll`) | epoll | 7 | 8 | 0 |

The three lane failures:

* atomic_units "armed resize retirement: atomic-growth" and "...: flush-prepared". CD5.3
  changed `hash_ttl_on_access` to an in/out object and a bool, and the earlier agents left
  `tests/rehash_waits_unit.cc` on the old API. That unit stopped building, which also breaks
  wait_units' "reads never wait for retirement quiescence". Fixed test-side in 1db9f6a650 (its
  ungated `maintenance` case also needed a write spec: since 10-12 it dereferenced a null
  `op.spec`, on PRE too). The re-run passes 30 of 30.
* flipfix6 "FLIP MULTI WATCH session storm (all legs)": in one FLUSHALL/FLIP storm sub-leg,
  `tests/flushfix2_siblings.py`'s flipper rejects the legitimate refusal `ERR FLIP refused: a
  pinned connection closed`, which `flipfix.py` and `flipfix6.py` accept. It failed again on a
  POST re-run and fails the same way on PRE (`pre-flipfix6-uring`, another leg). This is a
  pre-existing test gap outside this lane and is left unchanged; the fix would be to accept
  that refusal there too.

The earlier witness runs (`pre-final-witness-*`, `post-witness-*`, `pada-witness-*`) are kept.
Their POST oom rows failed only the record window proof on the three atomic-1 legs without
read-local; the proof was corrected in 06388338d4.

**Differential:** both engines complete the standard seeds 7, 19, 20 and 23 plus the rotating
seed (21 on uring, 22 on epoll), 941 rows each with 0 failures: split atomic 0 235, split
atomic 1 239, armed atomic 0 231, armed atomic 1 235, and 1 mode-equivalence row.

**Tcl:** `redis_tcl` passes in both modes on both engines. Each mode and engine runs 1,876
passing assertions in 39 files, with only the manifest's named setup errors. On promotion, the
six skip-listed assertions nearest this lane were probed in isolation, three fresh attempts
per mode, on PRE and POST: both BRPOPLPUSH/WATCH tests, Linked LMOVEs, LMOVE on plain nodes,
SMOVE wrong dst key type, and DISCARD during OOM. Results are identical on both arms and the
assertions still fail, so nothing is promoted (`pre-/post-tcl-probes-uring`).

**Units and freshness:** `python3 tests/gates_test.py` passes 77 tests. `make all` builds, as
do every one of the 55 `job_production_units` targets, `mdbqsbr-live-arms`, blockfix-cost, the
blockfix2 units and the txnfix4 hash units. After that, `make -q all` returns 0, 0 of the 55
targets are stale, and both mdbqsbr live-arm roots (`make BUILD_ROOT=... -q all`), blockfix-cost,
blockfix2 and the txnfix4 hash units are fresh. Regenerable gate build products were deleted
afterwards to keep `build/` at 3.4 GB (`make -q all` still 0).

### Arms and measurement request

The arms are copied to `build/txnfix4/arms/`; SHA-256s are also in `docs/txnfix4/arms.sha256`
and `docs/txnfix4/binary-manifest.json`. POST is the binary every POST receipt names.

| Arm | Path | SHA-256 |
|---|---|---|
| PRE (9d6ab5526, `git archive` build) | `build/txnfix4/arms/PRE` | `737dd31040e35a371456af6775ebb07f001e719b7102cd12d6c188be9649e1fb` |
| POST | `build/txnfix4/arms/POST` (= `build/tomokv`) | `e23c2fb37cd0137a9287bcc7330ebb61d19796e0b7299b1d7e107e9018376198` |
| PAD-A | `build/txnfix4/arms/PAD-A` | `f1114465a039fcdbd4b9ae07b1731069d48cc985633bf944b2585fafd15e9bd4` |

POST `.text` is 9,025,351 bytes, PRE 9,021,623 (+3,728). **PAD-A is kind A, a behaviour
twin**: PRE's objects byte for byte, plus one never-executed NOP `.text` section (3,728 bytes:
POST's `.text` extent and `.rodata` start) and 1,000 unreferenced bytes appended to
`.gcc_except_table` (POST's unwind tables grew by that much). As a result `.text`, `.rodata`,
`.tdata`, `.tbss`, `.data` and `.bss` all start at POST's addresses (the tool asserts it). It
does not control individual function addresses or alignment. PAD-A reproduces PRE's witness
failures exactly. A PAD-B inverse control is not constructible for a text growth by padding.
No struct, layout lock, TLS or global data changed.

Maintainer: please run the **14 generic cells plus 2s GET/SET at p1 and p32, and EXEC at 64
connections**, with the gate's own instrument on the quiet box, for PRE, POST and PAD-A. Use the
same geometry for every arm (eight server CPUs, 16 shards, split 6:2) and matched offered load.
Start with a PRE/PRE null and keep the gate's ABBA ordering and per-cell acceptance bands. Rate
at matched offered load (or the cell's declared latency score) decides; cycles/op, IPC and
instructions/op explain. The serverless counts above show zero added instructions on the main
commands only. These measurements are NOT RUN by this lane.

### Gate row accounting

**DQ = +5, DF = +5.** The five `txnfix4-*` rows are collected at `tests/gate.sh` line 6706,
before the quick-tier exit at line 6842; each contributes one row whatever its legs. Starting
from PRE's counts, the owner should set **EXPECT_QUICK 1046 -> 1051** and **EXPECT_FULL
1063 -> 1068**. This lane does not edit either constant. The `record` sub-case lives inside the
oom row (no new row). The `gateplan.py` change admits selected correctness jobs on one 8+2
slot (copied from cx-cmdfix2) and changes no complete-gate budget.

### Additional findings outside the brief (reported, not fixed)

Both are pre-existing server-wide hangs and are S1 under the release rule. They need their own
lane: both sit in AOF/EXEC machinery outside this lane's items.

1. **MULTI/EXEC with a multi-key pop under AOF.** With `appendonly yes`,
   `MULTI; LMPOP 1 k LEFT; EXEC` (or ZMPOP) never replies, and the server stops answering new
   connections. Seen in 1s and 2s, atomic 0 and 1, on the headline 105c5818cc, PRE and POST
   alike. It happens whenever the connection's thread does not own the key's shard (4 of 4
   such boots; the one same-thread boot replied). LPOP and BLMPOP in the same position are
   fine, and waiting for the initial AOF rewrite changes nothing. After the hang every thread
   sits idle in `io_uring_submit_and_wait_timeout`: a decision or wake-up that never arrives,
   not a spin. Receipts: `docs/txnfix4/probes/exec-mpop-aof-*`. Suggested start: the EXEC AOF
   group (`multi_aof_emit_fragment` under the per-shard join guard in `multi_execute.inc`)
   against a two-stage pop child that runs on a remote owner.
2. **AOF with one value of 128 MiB.** With `appendonly yes`, a SETRANGE that grows one value
   to 128 MiB never replies (300 s), and new connections stop getting PONG within 15 s. 8, 32
   and 64 MiB reply at once. PRE and POST alike. Receipts: `docs/txnfix4/probes/aof-large-value*`.
   Not investigated further; it may be related to the GCMT channel-full retry that
   `round5-read/persist.md` lists as UNTESTED-NEEDS-RUN.

### Commits

Production changes: a66cc6e462, 98463e5328, 2b09a6f765 (the outlined admission, kept by
44bff4a277) and 8a250edef5 for CD5.4; c2b4b6e955 for CD5.5; 360d3cb162 for CD5.3. Test-side:
1cf612872b and 06388338d4 (witness rows), e968222546 (TM5.1), 1db9f6a650 (rehash_waits_unit),
and the gateplan.py selected-job allocation. Everything else adds tools and receipts. The
production diff from PRE is 9 files in `src/cmd`: xshard_movers.inc, scatter_engine.inc,
xshard_commands.inc, atomics_glue.inc, watch_modified.inc, t_hash_ttl.cc, t_hash_ttl.h,
t_hash.cc and hexpread.cc. No layout lock, ownership protocol, claim, version or scatter-engine
algorithm changed.

### NOT RUN

* Performance benchmarks, load generators, ABBA and throughput cells, and the full gate
  iteration: reserved for the maintainer. No throughput claim is made.
* The lane and wide selections on epoll. Epoll covered the witness rows, the engine-named jobs
  (multifix, climonfix4, snapshot, aof), `redis_tcl` and the differential; many lane jobs
  already run both engines internally.
* PRE runs of the broad selections. PRE comparisons exist for the witness rows, the Tcl
  probes, flipfix6, the instruction scopes and the auditor reruns.
* A PAD-B inverse control: POST grows `.text`, which padding cannot undo.
* The supplementary CD5.3 AOF-rewrite probe (`tools/txnfix4_probes.py --probe aofrw`): it
  stops at its 128 MiB setup value on PRE and POST alike (AOF large-value hang above). CD5.3
  is proven through BGSAVE captures, which share the capture path.
* ASAN/UBSAN or TSAN runs of this lane's changes: not requested by this brief; the TSAN builds
  ran only as gate prerequisites.
* Fixes for the two pre-existing hangs and the flushfix2_siblings refusal gap: outside this
  lane, reported above.
