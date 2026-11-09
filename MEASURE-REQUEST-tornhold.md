## tornhold

The S1 implementation replaces tornread PART1's per-operation registration with
fixed, per-IO generation rings and two connection buckets. PART2's unconditional
sampling/stamping is retained. A hold also protects MGET until in-order retirement,
closing the GET-on-owner-A / MGET-on-other-owners tear in design section 2.6.

Production source is frozen at `da3fcab014`; subsequent commits add tests and
evidence. The final image is `build/tornhold/tomokv-hold`, SHA-256
`18eb7a988891a41cae24a20ae2b33378d987a07a80d031b9038ef709985ec92b`.
Requested correctness coverage and all 420 primary instruction repeats are complete.
Default atomic-0 GET p32 costs **+2.16% instructions versus PRE in 2s** and
**+2.51% in 1s**, while saving **7.37% / 6.49% versus tornread PART2**.
The design's approximately 1% instruction estimate is not met by this image.
No throughput result is claimed. No push was made.

### Integration prerequisite

The branch started at `a293b32d83`, the tornread tip. On 2026-11-09,
`git fetch origin cpp`, `git merge --no-commit origin/cpp`, and a subsequent
`git ls-remote origin refs/heads/cpp` all identified `7595a6705a`, already an
ancestor. The requested origin merge was therefore a no-op; the two dependencies
in the task were absent from that remote ref.

The named dependencies were available locally, both based on `7595a6705a`:
readability phase 2 `6cd261fe71` and aofblock `17348b0387`. They were merged,
without rebasing, as `40c33d8edc` and `9c2222cbd7`. The sole readability conflict,
in `src/exec/op.h`, kept tornread's code and readability's comment text. Aofblock's
existing EXPECT and fixture changes came through its merge; this lane did not
edit those files by hand.

Before hold implementation, R7 envelopes were regenerated, the combined tree
built, directed units and R7 checks passed, and the integration gate passed
**34/34**: tornread's 32 rows, release/layout and R7. Evidence:
`docs/tornhold-integration.json`, `build/gate-run.fUiNsk/ledger.partial`.

### Implementation and invariant

`src/core/plain_read_holds.h` has 512 fixed, 16-byte generations plus 16 bytes of
ring cursors: **8,208 bytes per IO**, with no runtime allocation. The eight-byte
`PlainReadHold` occupies Rob's existing hole at offset 120. All layout locks hold:
Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob 192,
AtomicEntry 144 and Config 624. Op's reply-eligibility byte returns to its PRE
representation; PART1's per-op registration and retirement machinery is removed.

Phase 6 acquires the hold before the scatter/local/owner split, including MGET.
Only the scatter path carries its confirmed snapshot cut into subsequent stamps.
The three covered publication sites update the pass end; Phase 8 commits it.
Each WB drain has one post-drain retirement hook. Client release and both transfer
edges abort if a hold remains live. Joined shutdown discards residual holds.
`src/core/reorder.cc` was generated only by `tests/r7shadow_sync.py --write`.

Every stamped read published with an older operation in flight is protected,
before publication, by a cleanup floor no greater than its read cut plus one,
until in-order retirement passes its bucket end. A new generation publishes
before confirming the commit watermark. Joining an older generation uses
protection already established before this pass. The published floor is the
minimum of unresolved scatter snapshots and hold generations.

A remains fixed while B accepts newer passes. When A's end retires, B becomes A;
a later pass can acquire a newer B. A continuously nonempty ROB therefore cannot
extend the original A forever. The 64-slot window keeps low-16-bit end comparisons
unambiguous. MGET may release its scatter snapshot on completion, but its hold
remains until retirement, which requires the earlier GET to finish. PART2 keeps
this argument valid with atomic MSET disabled and atomic EXEC enabled.

### Proven correction to the proposed zero sentinel

Design section 4.3 guarded Phase 8 cover with `pass_hold_end != 0`. Counterexample:
a hold is acquired at dispatch `UINT64_MAX`, with older operations outstanding.
Its initial low-16 end is 65535. The covered read publishes and dispatch wraps to
zero. The guard skips the update. A drain retiring older operations up to flush
`UINT64_MAX`, while leaving that read unfinished, can release the hold early.

The implemented correction initializes the pass marker from the selected bucket's
existing end immediately after acquisition, then covers whenever `pass_hold` is
true, including end zero. Without a covered publication the marker stays at the
existing end. With one, it becomes the exclusive id after the latest covered
operation, including wrap. No retirement occurs during this parse pass, so the
64-slot bound makes the comparison safe. Existing B also retains its previous end
when publication fails; an unrelated local command is not accidentally covered.
Bucket zero remains a no-op for the PAD. Actual parser/WB units cover both the
2^16 and 2^64 boundaries. The counterexample was identified before production edits.

### Tests that prove the relevant windows

The rewritten normal/db0 unit covers ring-full joining, dead interior generations,
zero allocation, monotonic-cut rejection, publish/confirm advancement, mixed
snapshot floors, early completion, normal/suppressed/closing drains, shutdown,
all layout locks and both ROB wrap boundaries.

Its actual-parser `GET; MGET; GET` schedule uses an existing B and an older ROB
entry. A unit-only allocation observer advances commit after the first GET
publishes and before MGET publishes; the test requires that exact window to open.
The confirmed MGET cut must reach the younger GET's stamp. A disposable `no-carry`
header overlay fails exactly `rob.at(3).read_cut(confirmed) == confirmed`, with
SIGABRT. Production has no observation hook. Both namespaces pass through the
gate (`build/gate-run.iSToxF`, 2/2 including release).

A directed sliding-window schedule keeps 8–56 operations outstanding for 3,000
passes and requires more than 100 floor advances. Each live continuous-progress
row runs it before a 30-second TCP probe. The TCP probe keeps at least 4,088
commands outstanding at the client, requires freed versions in every two-second
interval, bounds pending entries and observes changing values. Client backlog
alone does not prove a continuously nonempty server ROB; the directed component
does. The matching `always-a` mutant server/unit fails all four progress rows at
`advances > 100`, before the TCP component. Its normal-unit and release
prerequisites pass (`build/gate-run.Sw0DbV`: 2 PASS, 4 intended FAIL).

WAIT and FLIP are `OrderedLocal`: Phase 5 prevents the design's suggested
`GET; GET; WAIT/FLIP` same-pass schedule while older ROB entries remain. The actual
parser unit proves those barriers. A separate WB unit leaves an uncovered
coordinator unfinished after the covered reads and requires hold release. This
proves the end-marker contract without claiming the unreachable parser schedule.

Live WAIT rows confirm `WAIT 1 0` is parked through CLIENT LIST and absence of a
reply while cleanup advances. Live FLIP rows use a read-only debugger witness of
a live A bucket and nonempty ROB on the chosen reader, then require that reader
to migrate IO threads while cleanup continues. A missed arming window triggers
fresh issued reads, bounded to eight tries; exhaustion fails. Only the test-owned
child opts into sibling inspection through `PR_SET_PTRACER`. Both engines pass
(`build/gate-run.qm0WEs`, 4/4 including unit and release).

### Gate proof

All lane builds and correctness processes use CPUs **0–19**, listening ports
**26500–26599**, and `LC_ALL=C`. Selected jobs run through `tests/gate.sh` with
`GATE_ONLY_JOBS` and `GATE_PROOF_NO_RATES=1`. This is correctness coverage, not a
full iteration or throughput run. Each job retains its declared modes, engines,
databases and other geometry; ordinary split boots use eight cores, 16 shards,
6 IO plus 2 executors.

| Selection | Result | Artifact |
|---|---|---|
| Read matrix, reorder 0 | 77/77 PASS | `build/gate-run.kiGt6g` |
| Read matrix, reorder 1 | 65/65 PASS | `build/gate-run.tS5hE0` |
| Tornread's exact native 132-label selection | 132/132 PASS | `build/gate-run.8JwTsx` |
| Remaining selected regression jobs | 549 PASS; one pre-boot setup refusal | `build/gate-run.ZAYpOE` |
| Isolated FIFO fairness rerun | 2/2 PASS, including all 16 live legs | `build/gate-run.gb7PoN` |
| Redis differential matrix plus release | 6/6 PASS | `build/gate-run.OzIKMA` |

Both read settings include all 32 inherited rows and all 32 GET/MGET rows.
Reorder 0 also includes the ten cleanup/coordinator rows, normal/db0 unit and R7.
The regression selections cover tornread's original 403-label broad set, its 104 supplemental rows, all 35 feature-interaction cells, 17
storage/filter/ring rows, seven shutdown rows plus release, the requested
atomics/MVCC/read-local/multi/flip/LB families and both aofblock engines.
The native selection matches the old 132 labels; it uses each current job's
native settings rather than claiming the historical external overrides were
identical.

All five differential children pass: split atomic 0/1, armed read-local atomic
0/1 and the 16-cell mode-equivalence aggregate. Their respective comparison
counts are 235, 239, 231 and 235, all with zero mismatches. Commands unobserved by
the differential suite are listed in its raw logs; this is not a claim that the
suite observed every registered command.

The FIFO row refused before any server boot because a shared slot had two load
CPUs and the row requires eight. The initial refusal remains in the ledger and
is not counted green. The isolated rerun uses server CPUs 0–7 and load CPUs 8–15,
retaining all sixteen 60-second mode/atomic/engine/database legs and assertions.
All sixteen pass with exact final values and zero transaction-order violations;
the aggregate row takes 988.64 seconds.
No production or gate source change was made for this allocation correction.

`make all unit` passes. R7 sync and its stale-envelope falsifier pass.
`tests/gates_test.py` passes **83/83** after the final progress-row composition
(431.826 seconds). Logs: `build/tornhold/all-unit-final.log`,
`gates-test-after-progress.log`. The final `make -j20 all` is a no-op; `make -q` and `make -q all` both return zero.
Native and frozen images retain the candidate digest above. Evidence:
`build/tornhold/final-build-after-accounting.log`,
`final-freshness-after-accounting.json`.

### Falsifiers

All **88 pipelined hunts detect tears**, while all **88 sequential controls pass**,
with changing values, zero worker errors and no vacuity. Six release prerequisites
also pass. `tools/tornhold_controls.py` creates disposable overlays under build/
and does not change production sources or objects.

| Deliberately incorrect arm | Reorder | Hunts detecting tears / sequential controls passing | Artifact |
|---|---:|---:|---|
| Release | 0 | 20 / 20 | `build/gate-run.TVIeXE` |
| Release | 1 | 16 / 16 | `build/gate-run.R9qH8k` |
| PAD(A) | 0 | 20 / 20 | `build/gate-run.Rkrf7Z` |
| PAD(A) | 1 | 16 / 16 | `build/gate-run.d6Z1a0` |
| Supplied tornread PART2, GET/MGET | 0 | 4 / 4 | `build/gate-run.Uq9Us5` |
| Generated priority parser without holds | 1 | 12 / 12 | `build/gate-run.4n7Kkv` |

Release and PAD each cover all inherited rows in both reorder settings. Their
reorder-0 runs also cover GET/MGET with both engines and atomic 0/1. The generated
parser mutant affects the relevant fused priority path; its ordinary-parser
control passes 5/5, including release (`build/gate-run.PP2LD1`). No-carry and
always-A directed failures are described above.

The PAD is **(A), behaviour twin**: PRE cleanup protection with the candidate's
text/data layout; PART2 stamping remains. Replacing each namespace's
`plain_hold_begin` entry by `mov %rcx,%rax; ret` returns the supplied cut without
acquiring a bucket. Exactly eight ELF bytes differ, preserving file size,
section sizes, addresses and data layout. SHA-256:
`fd2555b316217d7142bdc89cf423bc5fa7c126382733fdb5951b8dfde87b84ce`.
It is deliberately incorrect and only a falsifier/measurement control.

### Endurance

All **13 arms, each at least 180 seconds, pass** on the final frozen production
image: the original eleven Phase B definitions plus atomic-1 GET/MGET and
EXEC-backed atomic-0 GET/MGET. They check **327,459,498 read pairs/triples**, observe
**15,808,642 value changes** (minimum 655,074 in every arm), and report **zero
violations, zero worker errors and no vacuity**. Only CPUs, ports and durations
were adapted in the inherited runner. Servers use CPUs 0–7, clients 16–17 and
ports 26590/26591. Evidence: `docs/tornhold-endurance.json`,
`build/tornread/endurance-20261109-075419/`.

### Instruction accounting

All **420/420 primary repeats** completed: 28 cells × five arms × three repeats.
The instrument is
`tools/tornread_instructions.py --place-io --arms pre part1 part2 merged-part2 hold
--get-depths 1 8 32 128 --repeats 3 --port 26595`, under `LC_ALL=C`, pinned to CPUs
0–11. The four requested arms are accompanied by merged PART2, the verified
integration image saved before hold edits, to isolate the integration difference.
Their exact paths and hashes are recorded in the evidence.

Each repeat completes 524,288 public commands (eight connections × 65,536), checks
every reply and the exact commandstats delta, and records perf's acknowledged
boundaries and at least 99.9% counter coverage. Servers use CPUs 0–7, clients
8–11, 16 shards, 6:2 split or fused, uring, one DB, and read-local/key-LB/client-LB/
automatic-FLIP off. IO placement is witnessed before and after every repeat.
Counts for MGET-8/MSET-8 are per public command, not per key.

The historical seed digest
`78bb25654d20f7e1b017c4d5b363e41b1c4887a7b133dfaea0fff844981bf829`
was not found in the available worktrees or scratchpad. All arms use one new
common seed, SHA-256
`55cf94266505e132ad6da898b1f8163222633b54f1e393d10611bd1e43ffb780`;
identity with historical key placement is not claimed. Extra GET
depths expose amortization without adding a production pass counter. Pipeline
128 spans at least two 64-slot ROB windows and must not be reported as one pass.

Raw primary results are in `build/tornread/instructions-20261109-110708/`;
compact per-repeat totals, binary digests, geometry and all 28 cells are in
`docs/tornhold-instructions.json`. The before/after process snapshots show no
other active server or measurement workload. Every repeat has the required
command count, IO placement and counter coverage.

Instructions per public command: median [minimum–maximum], three repeats per arm.

| Mode | Atomic | Command/depth | PRE | PART1 | PART2 | Merged PART2 | HOLD | HOLD/PRE | HOLD/merged PART2 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 2s | 0 | GET p1 | 39,485 [39,419–39,703] | 39,921 [39,280–39,990] | 39,232 [38,404–39,759] | 39,290 [39,085–39,301] | 39,541 [39,359–39,663] | +0.14% | +0.64% |
| 2s | 0 | GET p32 | 2,362 [2,358–2,372] | 2,405 [2,405–2,408] | 2,605 [2,602–2,617] | 2,610 [2,594–2,611] | 2,413 [2,396–2,416] | +2.16% | -7.54% |
| 2s | 0 | SET p32 | 2,491 [2,485–2,491] | 2,511 [2,502–2,514] | 2,509 [2,504–2,513] | 2,501 [2,495–2,509] | 2,518 [2,504–2,521] | +1.10% | +0.70% |
| 2s | 0 | MGET-8 p8 | 17,547 [17,488–17,588] | 17,579 [17,556–17,587] | 17,630 [17,577–17,631] | 17,683 [17,666–17,711] | 17,633 [17,350–17,703] | +0.49% | -0.28% |
| 2s | 0 | MSET-8 p8 | 19,136 [19,080–19,179] | 19,075 [19,055–19,102] | 19,094 [19,067–19,101] | 19,077 [19,032–19,085] | 19,159 [18,653–19,170] | +0.12% | +0.43% |
| 2s | 1 | GET p1 | 39,525 [39,056–39,759] | 39,833 [39,699–39,949] | 39,456 [39,399–39,736] | 39,444 [38,737–39,514] | 39,160 [33,530–39,275] | -0.92% | -0.72% |
| 2s | 1 | GET p32 | 2,370 [2,367–2,375] | 2,621 [2,621–2,627] | 2,611 [2,607–2,617] | 2,607 [2,606–2,609] | 2,415 [2,411–2,425] | +1.86% | -7.37% |
| 2s | 1 | SET p32 | 2,480 [2,466–2,492] | 2,498 [2,489–2,507] | 2,495 [2,485–2,502] | 2,503 [2,495–2,505] | 2,504 [2,422–2,507] | +0.97% | +0.03% |
| 2s | 1 | MGET-8 p8 | 17,689 [17,654–17,704] | 17,683 [17,646–17,694] | 17,700 [17,598–17,739] | 17,752 [17,727–17,774] | 17,786 [17,784–17,806] | +0.55% | +0.19% |
| 2s | 1 | MSET-8 p8 | 82,807 [82,689–82,979] | 82,732 [82,241–83,284] | 83,207 [83,086–83,489] | 83,474 [83,445–84,529] | 82,758 [82,242–83,143] | -0.06% | -0.86% |
| 1s | 0 | GET p1 | 17,437 [17,433–17,454] | 17,424 [17,410–17,438] | 17,454 [17,418–17,456] | 17,487 [17,436–17,500] | 17,487 [17,481–17,491] | +0.29% | +0.00% |
| 1s | 0 | GET p32 | 2,330 [2,330–2,339] | 2,363 [2,357–2,364] | 2,554 [2,554–2,554] | 2,543 [2,538–2,544] | 2,388 [2,383–2,391] | +2.51% | -6.09% |
| 1s | 0 | SET p32 | 2,520 [2,516–2,522] | 2,515 [2,506–2,517] | 2,509 [2,508–2,510] | 2,520 [2,515–2,532] | 2,523 [2,517–2,525] | +0.09% | +0.11% |
| 1s | 0 | MGET-8 p8 | 18,069 [18,048–18,085] | 18,302 [18,294–18,311] | 18,350 [18,339–18,367] | 18,331 [18,309–18,331] | 18,358 [18,335–18,364] | +1.60% | +0.15% |
| 1s | 0 | MSET-8 p8 | 20,050 [20,041–20,054] | 20,013 [19,997–20,023] | 20,033 [19,993–20,036] | 20,006 [20,003–20,009] | 20,008 [20,005–20,015] | -0.21% | +0.01% |
| 1s | 1 | GET p1 | 17,449 [17,445–17,463] | 17,440 [17,438–17,446] | 17,466 [17,461–17,485] | 17,479 [17,465–17,494] | 17,489 [17,467–17,503] | +0.23% | +0.06% |
| 1s | 1 | GET p32 | 2,351 [2,346–2,351] | 2,558 [2,550–2,559] | 2,555 [2,551–2,563] | 2,547 [2,542–2,554] | 2,392 [2,388–2,393] | +1.77% | -6.07% |
| 1s | 1 | SET p32 | 2,523 [2,522–2,534] | 2,524 [2,515–2,526] | 2,523 [2,514–2,526] | 2,515 [2,513–2,537] | 2,528 [2,526–2,538] | +0.19% | +0.50% |
| 1s | 1 | MGET-8 p8 | 18,198 [18,187–18,208] | 18,417 [18,411–18,417] | 18,428 [18,413–18,442] | 18,425 [18,403–18,428] | 18,472 [18,466–18,480] | +1.50% | +0.26% |
| 1s | 1 | MSET-8 p8 | 63,823 [63,795–64,097] | 63,830 [63,688–63,878] | 64,069 [63,917–64,070] | 63,967 [63,872–64,019] | 63,444 [63,110–63,823] | -0.59% | -0.82% |

GET depth sensitivity; these are per-command counts, not measured parser-pass costs.

| Mode | Atomic | Depth | HOLD instructions/GET | HOLD − PRE instructions/GET | HOLD/PRE |
|---|---:|---:|---:|---:|---:|
| 2s | 0 | 1 | 39,541 [39,359–39,663] | +55.48 | +0.14% |
| 2s | 0 | 8 | 5,757 [5,713–5,775] | +53.52 | +0.94% |
| 2s | 0 | 32 | 2,413 [2,396–2,416] | +51.01 | +2.16% |
| 2s | 0 | 128 | 1,799 [1,798–1,805] | +51.03 | +2.92% |
| 2s | 1 | 1 | 39,160 [33,530–39,275] | -364.69 | -0.92% |
| 2s | 1 | 8 | 5,760 [5,718–5,767] | +38.15 | +0.67% |
| 2s | 1 | 32 | 2,415 [2,411–2,425] | +44.19 | +1.86% |
| 2s | 1 | 128 | 1,810 [1,807–1,820] | +35.94 | +2.03% |
| 1s | 0 | 1 | 17,487 [17,481–17,491] | +50.15 | +0.29% |
| 1s | 0 | 8 | 4,694 [4,694–4,699] | +66.44 | +1.44% |
| 1s | 0 | 32 | 2,388 [2,383–2,391] | +58.36 | +2.51% |
| 1s | 0 | 128 | 1,919 [1,919–1,920] | +40.22 | +2.14% |
| 1s | 1 | 1 | 17,489 [17,467–17,503] | +40.79 | +0.23% |
| 1s | 1 | 8 | 4,697 [4,691–4,702] | +63.10 | +1.36% |
| 1s | 1 | 32 | 2,392 [2,388–2,393] | +41.51 | +1.77% |
| 1s | 1 | 128 | 1,920 [1,920–1,932] | +32.76 | +1.74% |

The four GET p32 cells have at most **0.683%** deviation from their median within
any arm. The measured excess is 51–58 instructions/GET at atomic 0 and 42–44 at
atomic 1. These whole-process measurements exceed the static hold-cost estimate;
without a parser-pass counter they do not isolate the hold routine's own cost.
The table supplies depth sensitivity at p8/p32/p128, not a measured per-pass
amortization claim.

Four of 140 arm/cell groups exceed 2% deviation from their median: split PART2
GET p1/atomic 0 (2.11%), HOLD MSET-8 p8/atomic 0 (2.64%), HOLD GET p1/atomic 1
(14.38%), and HOLD SET p32/atomic 1 (3.26%). All raw samples remain in the table.
**The negative p1 delta is not evidence of a gain.** These deviations are not
classified as box noise.

Investigation used 60 additional finite repeats, five per selected cell, with
cycles, task-clock, context-switch and migration counters plus before/after
thread-affinity and INFO observations. Reply totals, IO placement, server affinity
and counter availability remain correct. The three initially variable candidate
cells stay below 2% in this diagnostic run, while historical PART2 GET p1 still
varies by 3.32%. Added counters perturb the workload; their instruction totals are
kept separate from the primary table.

Six separately controlled instruction-sampling profiles cover PRE/PART2/HOLD at
split GET p1 and p32. They show substantial executor-loop and vDSO work at p1
(roughly 26–28% in ExLoop::run and 20–22% in vDSO alone), demonstrating that the
whole-process count includes much more than the read body. They do not establish
the cause of the original 14.38% low repeat, which remains unresolved. No throughput
or p1 improvement claim follows. Evidence and exact diagnostic scripts are in
`docs/tornhold-instruction-diagnostics.json`. An initial unacknowledged sampling
attempt missed the short p32 interval and failed with empty data; it is retained
and excluded, then replaced by fresh captures with acknowledged record controls.


### Maintainer ABBA request

Use the gate's own instrument on a quiet box for the 20 required cells: GET
p1/p32, SET p32, MGET-8 p8 and MSET-8 p8, each at atomic 0/1 and modes 1s/2s.
Compare supplied PRE/PART1/PART2, merged PART2, HOLD, and the **PAD (A) behaviour
twin** above. Preserve geometry and IO placement; report rate at matched offered
load, cycles/public command, instructions/public command and IPC. Matched-load
rate decides the result. Instruction savings alone do not establish the expected
approximately 1% default-config overhead. Check p1 and writes for regressions;
HOLD versus the same-layout PAD separates mechanism cost from layout effects.
Also run default atomic-0 GET p1/p32 with concurrent cross-owner EXEC writers,
and record retained versions and cleanup counters during continuous pipelining.
Holds may retain records up to roughly two ROB windows longer than per-read
registration. This lane runs no throughput benchmarks or full iteration.

### Landing inventory and explicit limits

New collection sites add 32 GET/MGET hunt/control rows, one normal/db0 unit row,
four continuous-progress rows, four WAIT rows and two FLIP rows: **+43 quick and
full beyond tornread**, or **+75 against the merged fixture**. They are collected
at `tests/gate.sh:7378,7383,7385,7386,7388`, before quick exit at line 7629;
inherited tornread collects at line 7377. Landing counts are
**EXPECT_QUICK=1323**, **EXPECT_FULL=1340**. The maintainer owns these constants and
the label fixture. The real fixture unittest therefore has 10 passes, one failure
and one error from the 75 missing labels. A temporary source-derived projection
with the proposed counts passes 12/12; it is an inventory check, not gate proof.
Tracked constants and fixture were not edited by this lane.

The complete design was read. Section 2.7's immediate XREAD hole remains an
explicit follow-up: `GET x; XREAD STREAMS s 0` can bypass both the Phase 6 stamp
and the blocking barrier, because XREAD carries Blocking without actually
blocking in this case. A single-stream immediate XREAD resolves at "now", so
EXEC updating x and s can still expose that distinct tear. The design marks it
outside this lane; this report does not claim every read command is covered.
The pre-existing owner-side 32-bit read-cut reconstruction limit is also unchanged.

Initial live-probe failures were test defects: a cumulative counter used instead
of `atomic_pending_entries`, an assumed FLIP destination and missing test-child
ptrace opt-in. Logs are retained; none prompted a production fix. An initial
endurance arm was stopped to allocate whole CCXs and is excluded. The first
one-slot native proof run (`build/gate-run.1caOJm`) was stopped after its companion
build to use two disjoint correctness slots; its partial ledger is excluded.
Native rlfix5 jobs regenerated historical build-metadata files; lane copies and
hashes are retained under build/, and the tracked historical files are restored.

Compact, committed evidence is in `docs/tornhold-integration.json`,
`docs/tornhold-proof.json`, `docs/tornhold-endurance.json`,
`docs/tornhold-instructions.json` and `docs/tornhold-instruction-diagnostics.json`. No committed file exceeds 1 MB.
