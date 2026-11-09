## tornhold

The S1 implementation replaces tornread PART1's per-operation registration with
fixed, per-IO generation rings and two connection buckets. PART2's unconditional
sampling/stamping is retained. A hold also protects MGET until in-order retirement,
closing the GET-on-owner-A / MGET-on-other-owners tear in design section 2.6.

Production source is frozen at `da3fcab014`; subsequent commits add tests and
evidence. The final image is `build/tornhold/tomokv-hold`, SHA-256
`18eb7a988891a41cae24a20ae2b33378d987a07a80d031b9038ef709985ec92b`.
Requested correctness coverage is complete. Instruction accounting is running.
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
`build/tornhold/final-build.log`, `final-freshness.json`.

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

The correctness queue is complete and accounting is running. The instrument is
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
common seed; identity with historical key placement is not claimed. Extra GET
depths expose amortization without adding a production pass counter. Pipeline
128 spans at least two 64-slot ROB windows and must not be reported as one pass.

<!-- FINAL_INSTRUCTION_TABLES -->

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
`docs/tornhold-proof.json`, `docs/tornhold-endurance.json` and, after accounting,
`docs/tornhold-instructions.json`. No committed file exceeds 1 MB.
