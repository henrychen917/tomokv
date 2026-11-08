## tornread

S1: retain pipelined plain-read cuts, including reads parsed before a default-mode EXEC starts.
Base: `7595a6705a` on branch `cx-tornread`. No push. No edits to the parallel lane's
`src/persist/aof.cc`, `src/cmd/blocking.inc`, or `src/cmd/multi.inc`.

### Separately reviewable parts

| Arm | Source | Binary |
|---|---|---|
| PRE | `7595a6705a` | `build/tornread/tomokv-pre` |
| PART1 | `f417f6211b` + `6fa209107f` + `9169f5e4e8` | `build/tornread/tomokv-part1-r7` |
| PART2 | `5df760dfe5` + `4520adb478` (on PART1) | `build/tornread/tomokv-part2-r7` |
| PAD1 | **(A) behaviour twin**: PRE cleanup behavior in PART1's exact text/data layout | `build/tornread/tomokv-pad1-r7` |

The two late commits apply the same PART1 and PART2 changes to the generated fused priority
parser in `src/core/reorder.cc`; the normal parser lives in `src/core/io_loop.h`.
`tests/r7shadow_sync.py` and its falsifier pass, and the `reorder_sync` gate job passes
(`build/gate-run.M3quIf/ledger.partial`). The final arm names carry `-r7` to distinguish
them from the earlier images used for the completed normal-path endurance and broad
correctness run. Both sets remain available; no binary was replaced during a running job.

PART1 adds an IO-private, refcounted list of ordinary read cuts to `ScatterArenaPool`.
An ordinary stamped read with any older ROB operation registers before either local-lane
or owner publication. Treating every older operation as a possible read is conservative
and avoids a second per-connection read counter. Repeated cuts share one list entry.
Finished entries are removed, including holes between other connections' live cuts.
The vector allocates only on the first registered pipeline; an empty pool allocates nothing.

The pool's single floor publisher now combines scatter/transaction snapshots with plain
reads, including registration, explicit unregister and early-completion refresh. A
scatter that confirms a newer cut advances later ordinary reads in the same parse pass.
No owner execution, resolver, promotion, or cleanup code changed. There are no reader
retries, seqlocks, new blocking rules, or changes to single-owner writes and RYOW.

PART2 removes the activity test and samples `atomic_snapshot()` once per parse pass.
Every nonblocking readonly owner/scatter operation is stamped, even at `--atomic 0`.
The activity-word load is replaced, not retained alongside the snapshot load. Testing
activity at parse or dispatch cannot prove that an EXEC will not start before execution.
Leaving the first unregistered read unstamped also fails: after a later read registers,
that first read could still select a retained committed version above the later cut.
Sampling lazily at the first read would add a per-read first-sample test; the implementation
uses the single existing pass-level sampling point.

All eight layout locks pass: Op 336, Client 1984, ThreadCtx 1408, Shard 1440,
FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. The reference marker shares
Op's existing reply-code-eligibility byte as a bitfield. The only new storage is
per IO pool (vector and last confirmed scatter cut), plus live cut/refcount entries.

### Floor and lifetime proof

The floor is **exclusive**: cleanup may collapse a committed version T only if
`T < floor` and `T <= cleanup_cutoff`. Thus the safety inequality is
`published_floor <= oldest_live_cut + 1`; publishing a *lower* floor delays cleanup.
The dangerous direction in the task's wording is above that bound.

1. `src/cmd/atomics_glue.inc:459` publishes exactly
   `min(unresolved_snapshot_floor_, plain_read_cuts_.floor())`. All four former
   snapshot publication sites use it. Only the owning IO thread mutates the list.
2. Registration reserves capacity before publishing. It inserts the proposed cut,
   publishes the combined floor with the existing seq_cst store, then confirms the
   seq_cst snapshot. A cleanup that missed this publication loaded its cutoff before
   that store, hence at or below the confirmation. Only this unpublished read moves
   to the confirmed cut; older references remain. Confirmation cannot allocate.
3. Reusing the newest equal cut needs only an increment: its protection was already
   published and confirmed. On a new cut, append order follows IO snapshot order.
   A scatter confirmation is carried into the next ordinary registration, preventing
   GET/MGET/GET from restoring an earlier pass cut.
4. Every dispatch has exactly one owner of its reference: IO before publication,
   the ROB afterward. Registration OOM leaves neither a marker nor a floor change.
   Cursor/arity/security/scatter errors precede ordinary registration. A refused
   queue post unpublishes and unregisters (`io_loop.h:4579`, `reorder.cc:3103`). A successful local or
   owner publication transfers the reference to the ordinary retirement path.
5. Both ordinary and reply-suppressing WB drains invoke the retirement callback for
   marked reads (`src/net/wb.h:329,832`). The IO callback releases the reference
   before recycling the Op (`io_loop.h:129`). Done acquire precedes retirement;
   copied replies no longer read store versions, and borrowed replies retain their
   independent borrow references.
6. Disconnect retains the Client until its ROB is quiescent (`conn.h:800`,
   `io_loop.h:5576`), so completed requests still drain through that callback.
   Client LB requires `migration_protocol_idle()` and ROB quiescence (`conn.h:806`,
   `io_loop.h:375`). FLIP movers and stayers require quiescence too
   (`src/cmd/flip_liveness.inc:13,168,241`); exceptions retain only a FLIP/blocking/WAIT
   coordinator, which cannot carry a plain-read reference. No live reference can
   move to another IO or survive removing its old floor slot from placement.
7. Post-join shutdown rebinds the retire callback with the same release and explicitly
   releases any residual unretired references (`src/core/shutdown.cc:73,192`).
   Workers have joined before that final discard.
8. The registry does not depend on the current commit watermark when releasing an
   Op's low word. It widens against its retained newest cut; if epochs span a full
   low-word wrap, equal low words share the oldest cut conservatively until the last
   reference retires. This prevents ambiguous removal, leaking entries, and premature
   cleanup. The directed unit covers this alias case.

Why the first read need not register: before a younger read publishes, an older
unregistered read may see a base above its original cut. Any cleanup that produced
that base has a cutoff at or below the younger read's confirmed cut. After the
publication, cleanup cannot promote a newer group while the younger reference lives.
The older read's retained-record resolver also uses a cut no greater than that younger
cut. It therefore cannot observe an atomic group newer than the younger read's cut.
ROB retirement cannot release the younger reference before the older read has finished.
For a strict round trip, the subsequent parse samples after the earlier reply, so the
existing round-trip argument applies. This is why registration is needed only when
an older ROB operation exists, while stamping is needed even for the first read.

Existing limitation, not silently claimed fixed: owner `Op::read_cut(now)` still uses
the pre-existing less-than-2^32-intervening-commits assumption documented in `op.h`.
The reference registry remains conservative across that wrap, but this change does not
extend the owner's timestamp representation. That separate old-cut reconstruction issue
is described in the supplied analysis's referenced read-cut-wrap report.

Retaining a cut until IO retirement is conservative: reply backpressure can keep version
cleanup pinned after execution has completed. This follows the requested lifetime and
adds no owner-side completion channel.

### Regression rows and negative controls

The final `--reorder 0` and requested `--reorder 1` matrices are complete. Both pass all 32 rows.
Priority scheduling is effective only in 1s; the 2s legs normalize to FIFO and are controls.

`tests/tornread.py` checks and records the effective thread mode, read-local setting and
reorder setting through CONFIG GET; a mismatched requirement fails setup. It preserves Phase B's writer-tagged serial-order oracle, owner geometry
proof, worker errors, writes/read pairs/value-change checks, MGET-noise oracle, and
post-run placement check. Both within-pair and cross-pair regressions fail; zero
violations are allowed. The 15-second gate rows use atomic MSET writers at atomic 1,
and EXEC writers at atomic 0, each with strict round-trip controls.

Matrix: both `2s`/`1s` × both read-local settings × both atomic settings × both
epoll/uring engines, matching the current atomics/read-local rows (including the split
read-local runtime). Sixteen whole jobs, two counted rows each.
**DQ=+32, DF=+32**, counted at the `collect_job "tornread-..."` loop at `tests/gate.sh:7277`, BEFORE the quick
exit at `tests/gate.sh:7519`, not at the job definition. At this base EXPECT_QUICK must become **1244**
(1212+32), EXPECT_FULL **1261** (1229+32). The maintainer must add the 32 corresponding
labels; neither EXPECT nor `tests/fixtures/nullrefresh-ledger-labels.json` was edited.

- Specified release `/home/user/Projects/bins/readability-pre-5c363128/tomokv`:
  all **16 pipelined rows FAIL**, each at the first ~0.3-second check;
  all **16 round-trip controls PASS**. Original twelve-shape ledger:
  `build/gate-run.RNyIRh/ledger.partial`; the four added split read-local shapes:
  `build/gate-run.STc8Fz/ledger.partial`. Every falsifier has zero worker errors
  and no vacuity flags; failures are observed torn replies.
- PART1 at atomic 1: both network engines' hunts and controls passed.
  `build/gate-run.yt0k43/ledger.partial` (initial PART1 build before the scatter-cut followup).
- PART1 at atomic 0 still FAILS as expected: uring 7 violations / 211,456 pairs in
  0.3 s; epoll 2 / 413,392 in 0.5 s. Both round-trip controls pass.
  `build/gate-run.7BVM6s/ledger.partial`. This is why PART2 is required.
- Initial PART2: **24/24 rows PASS** (plus external-binary/footprint row: 25/25).
  Pipelined: **112,463,736 pairs**, **12,480,617 value changes**, zero violations.
  Round-trip: **15,594,280 pairs**, **19,058,118 value changes**, zero violations.
  Ledger: `build/gate-run.vb6MT1/ledger.partial`; each job retains JSON and server logs.
- Final PART2-r7, priority scheduling off: **32/32 rows PASS**, plus build/footprints.
  Pipelined: **123,513,424 pairs**, **6,966,123 value changes**; round-trip:
  **14,611,024 pairs**, **8,667,647 changes**. Every row ran at least 15 s with zero
  violations, errors or vacuity flags. `build/gate-run.qJ1lUC/ledger.partial`.
- Final PART2-r7, requested `--reorder 1`: **32/32 rows PASS**, plus build/footprints.
  This means 16 fused priority rows and 16 split FIFO control rows (`reorder_for_mode`).
  Pipelined: **121,687,296 pairs**, **6,802,473 value changes**, zero violations.
  Round-trip: **14,320,936 pairs**, **8,566,052 value changes**, zero violations.
  Every row ran at least 15 s; `build/gate-run.3f63cJ/ledger.partial`.
- PAD1(A) is a falsifier: 22,591 violations / 178,368 pairs in 0.3 s; its round-trip
  control passes. `build/gate-run.ziWzev/ledger.partial`.

Final PART1-r7 also passes all 16 atomic-1 rows with effective-mode assertions:
eight fused priority rows and eight split FIFO controls (`build/gate-run.9TtDVs/ledger.partial`).
Final PART2-r7 default-mode guard checks pass in split read-local epoll and fused
read-local priority uring, four rows (`build/gate-run.SoA55J/ledger.partial`).
These include the added CONFIG-based setup checks; they do not add ledger labels.

The generated-parser falsifier is the initial PART2 image (normal parser fixed,
generated parser still old) with fused `--reorder 1`: both atomic settings tear within
0.3 s; both controls pass (`build/gate-run.nDa3Pq/ledger.partial`). The final PAD1-r7(A)
fused priority arm also tears, with its control clean (`build/gate-run.OdY527/ledger.partial`).
An earlier split-mode attempt stayed clean because `reorder_for_mode()` normalizes
2s to FIFO; its receipt is retained as an inactive control (`build/gate-run.QPaywi/ledger.partial`),
not represented as a falsifier. The gate now checks effective settings explicitly. A live negative control requiring
reorder 1 on the split FIFO server exits 2 at setup, before starting workers
(`build/tornread/effective-reorder-negative.log`).

`tools/tornread_pad.py` copies PART1 and replaces only the two out-of-line registration
entries (normal and DB0 namespace) with `return true`. It leaves the Op's original
stamp in place, takes no reference, and changes only 12 ELF bytes, preserving section
sizes, addresses, all other text, data layout and file length. `build/tornread/pad1-r7.json`
records the final sites and digests (`pad1.json` retains the initial image). PAD retains dispatch/callback guard overhead and the helper
call/return; it is a layout control, not instruction-identical PRE.

### Validation status

- Builds: PRE, PART1, PART2, production `make all`, and `build/tornread-unit` succeeded.
- `make unit`: PASS; `build/tornread/make-unit.log`.
- Shutdown policy/signal/persistence gate jobs: **8/8 PASS**;
  `build/gate-run.gYPAED/ledger.partial`.
- Directed unit: reference reuse/removal, low-word wrap alias, registration OOM rollback,
  mixed plain/scatter floors, early completion, same-pass scatter ordering,
  publish/confirm advancement, real normal/suppressed/closing WB drains (including an
  unfinished-read hold), final UINT64_MAX floor, and all locked sizes pass.
- `python3 tests/gates_test.py`: final **83 tests PASS**, 241.198 s
  (`build/tornread/gates-test-final.log`); the earlier run also passed.
- `python3 tests/gate_ledger_fixture.py --self-test`: **12 tests, 1 failure + 1 error**,
  both due to the explicitly deferred fixture/EXPECT update. The final check reports
  source declarations **1261**, unchanged fixture/EXPECT_FULL **1229**, exactly the 32
  tornread labels missing and no extra labels. Its synthetic future-loop test adds
  `writeback policy new-group`; its anchored message expectation is displaced by those
  existing missing labels. Log: `build/tornread/label-fixture-unittest-final.log`.
- Supplemental transaction/eviction/multidb/snapshot/executor/migration jobs:
  **104/104 PASS**, `build/gate-run.WfPjrS/ledger.partial`.
- Existing storage/filter/read-local ring jobs: **17/17 PASS**;
  `build/gate-run.LvyVcg/ledger.partial`.
- `make -q all`: 0 after `make all`.
- Broad selected atomics/MVCC/read-local/MULTI run: **373 PASS, 30 FAIL** across
  83 jobs (`build/gate-run.YYggSe/ledger.partial`). All 30 failures are retained:
  INFO selective collection (8) and rlfix5 (6) refuse native witnesses after the
  source/parser change; txnorder2 (15) and txnorder_wake (1) cannot find companion
  executables beside the frozen external image. The live WATCH-flush row passes.
  These are rerun with the final native build and colocated witnesses; no failed
  row is counted as passing on the strength of this run.
  Exact selections: `build/tornread/proof-jobs.txt`, `proof-supplement-jobs.txt`,
  and `proof-final-jobs.txt`. The fused transaction boot is running with epoll.
  `GATE_PROOF_NO_RATES=1` leaves throughput-only checks to the maintainer: the atomic
  MGET/MSET throughput floor is NOT RUN, and the RYOW rate assertion is disabled;
  their correctness witnesses retain their original assertions.
- Endurance: all 11 arms complete, zero violations; table below.
- Finite-work instruction accounting: **180/180 cells complete**; raw repeats and ranges below.
  No throughput benchmark or ABBA has been run.

All correctness servers use LC_ALL=C. Our builds/clients/servers are pinned within
CPUs 0-27 and listeners within 26000-26099. The endurance runner uses server 0-7,
clients 8-11, ports 26090/26091; concurrent gate correctness uses 12-19/20-27.

### Endurance

To repeat the recorded binary, use `TORNREAD_BIN=$PWD/build/tornread/tomokv-part2 LC_ALL=C
taskset -c 0-11 tools/tornread_endurance.sh tomo1 tomo0`. The runner adapts the supplied
full `run_phase_b.sh` matrix to the authorized resources and fixed binary. All 11
original TomoKV arms run for 180 seconds each (unless a violation/error fails early).
Artifacts: `build/tornread/endurance-20261108-212512/`.

| Arm | Seconds | Pairs | Value changes | Violations |
|---|---:|---:|---:|---:|
| tomo0-pipe-exec-lag | 180.1 | 20,242,168 | 2,514,468 | 0 |
| tomo0-pipe-exec | 180.2 | 98,727,896 | 5,435,798 | 0 |
| tomo0-seq-exec-control | 180.2 | 12,164,120 | 8,536,205 | 0 |
| tomo1-pipe-exec | 180.0 | 93,065,952 | 5,059,014 | 0 |
| tomo1-pipe-lag | 180.1 | 20,235,544 | 2,499,737 | 0 |
| tomo1-pipe-mgetnoise | 180.0 | 71,509,360 | 3,505,039 | 0 |
| tomo1-pipe-multiwriter | 180.2 | 60,476,272 | 6,004,889 | 0 |
| tomo1-pipe-readdelay20 | 180.1 | 8,828,856 | 1,103,757 | 0 |
| tomo1-pipe | 180.1 | 68,947,144 | 3,098,502 | 0 |
| tomo1-seq-control | 180.0 | 10,978,880 | 4,662,897 | 0 |
| tomo1-split | 180.2 | 17,184,464 | 5,899,122 | 0 |

Total: **482,360,656 pairs**, **48,319,428 value changes**, zero violations, zero worker errors. Every arm proved distinct owners before the run and stable placement afterward; every arm ended by duration with no vacuity flags.

Exact endurance image: initial PART2 `build/tornread/tomokv-part2`, SHA-256
`60ba613ade3987fa7a50fb6ea6d6697328d1c9b59391c83520c9d256bd583ce0`.
These arms leave priority scheduling off. The subsequent source changes only correct
the separate priority parser; the normal parser and the floor/retirement code exercised
here are unchanged. Final-image normal and priority matrices are recorded separately.


### Instructions per operation

Instrument: `tools/tornread_instructions.py`, perf `instructions:u` on the server PID,
acknowledged enable/disable boundaries after boot/population/warmup, fixed command count,
a finite native client checking exact reply bytes, and exact commandstats deltas. All arms load the same saved keyspace
and hash seed, recorded by digest. No throughput verdict. GET p1/p32,
SET p32, MGET-8 p8, MSET-8 p8, atomic 0 and 1, both 2s and 1s (read-local 0), PRE /
PART1 / PART2. Each reported operation is one public command, not one MGET/MSET key.

Eight connections × 65,536 measured commands = **524,288 commands per repeat**, after
4,096 warmup commands per connection. Three repeats per cell/arm, alternating arm order;
180 completed cells. Every counter ran 100%; all cells restored the same seed snapshot
(SHA-256 `a60fff7f8e2d845d2db76e1829e0c841b00e0c8a0573fcfe947f4e7b76e637af`).

Each entry below is **median [minimum–maximum] instructions/public command**. These are
whole-process counts, including idle polling and scheduling paths. Wide repeat ranges
(on unchanged cells too) prevent attributing small differences to the fix. They are not
box noise, confidence intervals, or proof of a speedup/regression. The fixed request
count and key placement do not fix connection-to-IO assignment or interleaving. In the
three PRE 2s/atomic-0/GET-p1 repeats, the busiest IO held 5, 4 and 3 readers respectively;
executor lifetime loop counts were 40.1M, 30.4M and 24.7M, accompanying 67,211, 52,959
and 43,712 instructions/op. Those lifetime counters include warmup and are diagnostic,
not the perf interval denominator. A second run with `--place-io` verifies each worker’s
IO both before and after its finite workload; its results will be reported separately. The
maintainer’s matched-load ABBA remains necessary for an attributable cost/merit verdict.

| Mode | Atomic | Command | Pipeline | PRE | PART1 | PART2 |
|---|---:|---|---:|---:|---:|---:|
| 2s | 0 | GET | 1 | 52,959 [43,712–67,211] | 43,375 [40,820–55,802] | 43,920 [43,373–44,097] |
| 2s | 0 | GET | 32 | 2,375 [2,352–2,611] | 3,258 [2,586–3,266] | 2,813 [2,799–3,466] |
| 2s | 0 | SET | 32 | 2,777 [2,714–3,288] | 2,789 [2,779–3,341] | 2,748 [2,578–2,815] |
| 2s | 0 | MGET-8 | 8 | 21,686 [17,427–21,713] | 21,909 [21,870–26,320] | 17,670 [17,603–21,827] |
| 2s | 0 | MSET-8 | 8 | 19,092 [18,960–21,553] | 21,089 [19,240–25,216] | 25,261 [19,135–25,306] |
| 2s | 1 | GET | 1 | 39,665 [39,115–55,069] | 42,786 [40,807–44,793] | 43,241 [43,181–43,253] |
| 2s | 1 | GET | 32 | 2,594 [2,406–3,289] | 2,816 [2,611–2,841] | 2,618 [2,603–2,866] |
| 2s | 1 | SET | 32 | 2,603 [2,594–2,758] | 2,715 [2,511–2,789] | 2,723 [2,522–2,750] |
| 2s | 1 | MGET-8 | 8 | 22,041 [17,809–26,299] | 22,010 [17,890–22,030] | 21,854 [17,690–25,799] |
| 2s | 1 | MSET-8 | 8 | 71,710 [66,628–72,275] | 75,470 [69,870–82,819] | 74,898 [61,416–83,344] |
| 1s | 0 | GET | 1 | 14,794 [13,938–16,023] | 15,077 [15,027–15,865] | 15,717 [13,161–16,290] |
| 1s | 0 | GET | 32 | 2,383 [2,379–2,489] | 2,415 [2,407–2,509] | 2,591 [2,590–2,601] |
| 1s | 0 | SET | 32 | 2,654 [2,574–2,669] | 2,570 [2,566–2,692] | 2,684 [2,580–2,712] |
| 1s | 0 | MGET-8 | 8 | 19,105 [18,882–19,329] | 19,284 [18,907–19,546] | 19,563 [19,448–19,566] |
| 1s | 0 | MSET-8 | 8 | 20,861 [20,648–20,898] | 20,949 [20,601–21,082] | 20,426 [20,351–20,520] |
| 1s | 1 | GET | 1 | 14,999 [13,310–16,052] | 14,489 [14,250–16,713] | 15,548 [14,333–15,912] |
| 1s | 1 | GET | 32 | 2,487 [2,404–2,518] | 2,699 [2,588–2,711] | 2,599 [2,595–2,687] |
| 1s | 1 | SET | 32 | 2,675 [2,586–2,688] | 2,653 [2,579–2,689] | 2,678 [2,593–2,686] |
| 1s | 1 | MGET-8 | 8 | 19,339 [19,039–19,361] | 19,221 [19,075–19,485] | 19,248 [19,066–19,610] |
| 1s | 1 | MSET-8 | 8 | 75,140 [74,959–76,049] | 74,796 [74,762–75,326] | 86,552 [86,301–87,657] |

Raw aggregate receipts: `docs/tornread-instructions.json`. Per-repeat argv, perf CSV,
server log, checked worker logs and result JSON: `build/tornread/instructions-20261108-220246`. Discarded smoke runs
calibrated perf 7.0.12’s NUL-terminated acknowledgement and SIGINT exit status.

### Binary identity and layout

Final `sha256sum` receipts are in `build/tornread/SHA256SUMS-final`; original-image
receipts remain in `build/tornread/SHA256SUMS`. Compact correctness receipts are
committed in `docs/tornread-proof.json`. The table below names the final review arms;
the original PART1/PART2 digests remain attached to their earlier proof artifacts.

| Arm | ELF .text bytes | SHA-256 |
|---|---:|---|
| PRE | 9,251,911 | `83d1cda87db19a4c7b1ba281812ced448d589cd98aa4a661c5449658014d6a46` |
| PART1-r7 | 9,251,831 | `2be78502f18cfc76cc0a84ab88d4d2145a0d364d692ecf2592ff8a979bb6759e` |
| PART2-r7 | 9,253,751 | `b30bc3bba310e2854221e4da0a3fc13a1d601bf2f990ee2f514510f27387fb55` |
| PAD1-r7(A) | 9,251,831 | `0e7834cfeafbd52aae2980676da1df37351ae989797358e8b63b3331d62a4b1a` |

### Maintainer ABBA request

Use the gate's instrument and matched offered-load/null controls. Compare PRE→PART1
and PART1→PART2 independently; also compare PRE→PAD1(A) and PART1→PAD1(A). Minimum
cells are GET p1/p32 at atomic 0/1, SET p32, MGET-8/MSET-8 p8 at atomic 0/1, both thread
modes, plus the armed read-local twins and the established headline regression cells.
Add default-mode GET p1/p32 with concurrent cross-owner EXEC writers. That cell
prices the now-unconditional load while commits modify its shared watermark line;
read-only instruction cells cannot expose that coherence cost. Include retained-record
and cleanup progress counters under the pipelined read/write mix, since read retirement
now extends the protected version window.
Record rate, cycles/op, instructions/op and IPC. Rate at matched load is the merit
verdict; instruction counts above only price work. No weakening of the correctness
oracle is an acceptable way to avoid PART2's cost.
