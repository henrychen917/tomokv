## tornhold

S1 scope: replace tornread PART1's per-operation references with connection holds,
retain PART2's unconditional sampling/stamping, and protect pipelined GET/MGET
against early scatter-snapshot release. Started at `a293b32d83` on `cx-tornhold`.
No push. All lane builds and correctness processes are restricted to CPUs 0–19;
listeners use ports 26500–26599 and server boots inherit `LC_ALL=C`.

### Integration prerequisite

The supplied origin description differs from the available remote. On 2026-11-09,
`git fetch origin cpp`, `git merge --no-commit origin/cpp`, and a subsequent
`git ls-remote origin refs/heads/cpp` all identified `7595a6705a`. It was already
an ancestor of the lane, so the requested origin merge was a no-op. Neither
readability phase 2 nor aofblock was reachable from that remote ref.

The two explicitly named dependencies were available locally, each based on
`7595a6705a`: readability phase 2 `6cd261fe71` and aofblock `17348b0387`.
They are integrated through merge commits, without rebasing. The readability
merge is `40c33d8edc`. Its sole conflict, in `src/exec/op.h`, retains tornread's
two bitfields together with readability's corrected arming comment.
The aofblock integration is `9c2222cbd7` and carries its existing EXPECT and label-fixture changes;
this lane has not edited either by hand.

The combined tree was regenerated with `tests/r7shadow_sync.py --write`.
Integration validation is recorded below before hold implementation begins.

### Validation receipts

- Initial build and directed tornread unit passed, including all eight layout
  locks. Logs: `build/tornhold/baseline-build.log`, `baseline-unit.log`.
- Combined dependency build passed: `build/tornhold/merge-build.log`.
- Combined dependency directed unit, R7 check and R7 falsifier passed:
  `build/tornhold/merge-unit.log`, `merge-r7.log`.
- Combined dependency gate: **34/34 PASS**, consisting of all 32 tornread rows,
  the release build/layout row and R7 parity. Ledger:
  `build/gate-run.fUiNsk/ledger.partial`. No hold implementation was present.
- Final hold implementation, negative controls, endurance and instruction
  accounting: in progress; completed receipts follow below.

### Review boundaries

The complete cheaper-registration design was read, including its rejected
variants and section 2.6. Immediate XREAD (section 2.7) and the pre-existing
32-bit owner cut reconstruction limitation remain outside this lane's scope.
No throughput benchmark or full iteration gate is run by this lane.

### Design correction before implementation: zero is a valid ROB end

Section 4.3 initializes `pass_hold_end` to zero and guards the Phase 8 cover with
`pass_hold_end != 0`. Counterexample: a hold is acquired at dispatch id
`UINT64_MAX`, with older operations still in flight. Its initial 16-bit end is
65535. The covered read publishes, wrapping dispatch to zero. The proposed
guard skips its end update. A drain that retires the older operations up to
flush `UINT64_MAX`, but leaves that read unfinished, can release its hold early.

Correction: immediately after `plain_hold_begin`, initialize the pass marker
from the chosen bucket's current end. The three covered publication sites
replace the marker as specified. Phase 8 calls `plain_hold_cover` whenever
`pass_hold` is true, including when the marker is zero. No additional per-read
branch or publication site is needed.

Proof: without a subsequent covered publication, the marker equals the existing
bucket end, so cover cannot extend it. With a covered publication, it equals the
exclusive id after the latest covered operation, even when that id wraps.
No retirement occurs during the parse pass and the ROB window is 64, so the
16-bit forward comparison remains unambiguous. An existing B bucket retains its
previous end on a failed publication; this avoids accidentally covering an
unrelated intervening local command. Bucket zero remains a no-op for the PAD.
The integer counterexample was checked before production edits; the directed
unit will cover the actual parser/drain boundary.

### Hold implementation checkpoint

PART2 sampling and stamping stay enabled throughout. `PlainReadHolds` replaces
`PlainReadCuts` with 512 fixed generations (8 KiB per IO); `PlainReadHold` occupies
Rob offset 120. Op's reply eligibility byte returns to its PRE representation.
The parser acquires before the scatter/local/owner split, carries confirmed
scatter cuts only on the scatter path, and commits the covered end in Phase 8.
Both WB paths invoke one post-drain hook, with no ordinary per-op callback.
Release and both transfer edges abort on a live hold. Joined shutdown discards
residual buckets. R7 is regenerated exclusively with the sync script.

The first implementation build and adapted directed unit pass. The unit drives
the production parser and actual WB drains at both ROB wrap boundaries, and
covers ring-full joining, dead interior generations, zero allocation, monotonic
cut rejection, two-bucket rotation with a continuously nonempty window, mixed
snapshot floors, early completion, publish/confirm advancement, normal/suppressed/
closing drains and shutdown discard. All eight size locks and offset 120 pass.
Logs: `build/tornhold/hold-build.log`, `hold-unit-build.log`, `hold-unit.log`.
Live integration, negative controls and pricing are still pending at this checkpoint.

### Coordinator qualification and directed liveness proof

The design's concrete `GET a; GET b; WAIT 1 0` / `FLIP` same-pass example is
unreachable in this tree: both commands have `OrderedLocal`, and Phase 5 stops
before publishing them while older ROB operations remain. The hold design is
still safe; its end excludes these publications as specified. The actual parser
unit now proves both barriers at both wrap boundaries. A separate WB unit leaves
an uncovered coordinator unfinished after the last covered read and requires
the hold to disappear while that coordinator remains in flight. This exercises
the end-marker contract without claiming an unreachable parser schedule.

The live FLIP rows use a read-only debugger witness of a live A bucket and a
nonempty ROB on the selected reader before FLIP, then require that same client
to change IO threads, with cleanup advancing in every observation interval.
Only the test-owned server opts into sibling debugger inspection via
`PR_SET_PTRACER`; production sources and the binary are unchanged. Empty-window
observations are retried against freshly issued reads, at most eight times;
exhaustion fails the row. Parked WAIT is independently verified through CLIENT
LIST and absence of a reply while versions continue to be freed.

`build/gate-run.qm0WEs/ledger.partial`: **4/4 PASS**, including both FLIP engines,
the normal/db0 directed unit row and the release row. Both readers had a witnessed
live hold and migrated; the unit includes the parser barriers above.

The sliding-window unit keeps 8–56 operations outstanding across 3,000 passes.
An isolated `always-a` source-overlay control fails exactly `advances > 100`;
the production unit passes. The live progress rows keep at least 4,088 commands
outstanding at the client, assert cleanup progress every two seconds, and bound
`atomic_pending_entries`. They do not infer an always-nonempty server ROB from
TCP backlog; that stronger property belongs to the directed unit.

Initial probe failures were test defects, retained in the build logs: use of the
cumulative `atomic_entries` counter instead of the pending gauge, an assumed
FLIP destination IO, and a sibling debugger without the test-child ptrace opt-in.
No production fix was made in response to those failures. An initial endurance
launch was deliberately stopped during its first arm to give both concurrent
correctness servers a complete CCX; it is excluded from final evidence.

### Row accounting

The existing 32 tornread rows remain. New collection sites add 32 GET/MGET hunt
and sequential-control rows (four mode/read-local shapes × two engines × two
atomic settings × two read shapes), one normal/db0 unit row, four continuous
pipeline rows, four parked-WAIT rows and two FLIP rows: **+43 quick / +43 full**
beyond tornread, or **+75 / +75** against the merged maintainer fixture.
All collection lines occur before the quick-tier exit. Source inventory is
**1,340** full rows; landing counts should be **EXPECT_QUICK=1323** and
**EXPECT_FULL=1340**. The maintainer owns those constants and the label fixture;
this lane does not edit either.

### Safety argument

Every stamped read published with an older operation in flight has protection
established before publication, at a floor no greater than its read cut plus one,
until in-order retirement passes the bucket end. Creating a generation publishes
the floor before confirming the commit watermark. Joining an older generation
uses protection that already predates the pass. The combined publisher takes
the minimum of unresolved scatter snapshots and hold generations.

A stays fixed while B accepts newer passes. Once A's end retires, B becomes A;
the next pass can acquire a newer B. Thus a continuously nonempty ROB cannot
extend the original A indefinitely. The 64-slot ROB also keeps low-16-bit end
comparisons within their unambiguous half-range. A completed MGET may release its
own scatter snapshot early, but its connection hold remains until retirement,
which requires the older GET on the other owner to finish first. PART2's
unconditional pass sampling and read stamping preserve the same argument with
atomic MSET disabled and atomic EXEC still enabled.

### Build and harness checkpoint

- `LC_ALL=C taskset -c 8-15,18-19 make -j10 all unit`: PASS.
  `build/tornhold/all-unit-final.log` records the standard unit target.
- Normal and db0 tornhold units, including all eight layout locks and Rob offset
  120: PASS through `tornhold_units`; see the FLIP witness ledger above.
- R7 sync check and stale-envelope falsifier: PASS. No generated parser was
  hand-edited; the deliberately broken priority parser exists only under build/.
- `GATE_TEST_PORT=26598 python3 tests/gates_test.py`, pinned inside CPUs 0–19:
  **83/83 PASS** in 485.215 seconds; `build/tornhold/gates-test-final.log`.
- Real label-fixture unittest: **10 passed, one failure, one error**, all caused
  by the intentionally unchanged count/fixture missing 75 declared rows.
  A temporary projection with exactly those source-declared labels and proposed
  counts passes **12/12**. This projection is an inventory check, not execution
  evidence; tracked EXPECT and fixture files remain untouched.
- `make -q` and `make -q all` both return zero after `make all unit`.
  `build/tornhold/make-q.json` records their exit codes.
- Native and frozen candidate binaries are byte-identical:
  SHA-256 `18eb7a988891a41cae24a20ae2b33378d987a07a80d031b9038ef709985ec92b`.

### Negative controls prepared

`tools/tornhold_controls.py` builds isolated overlays without changing production
sources or objects. `always-a` extends A forever and fails the nonempty-window
unit at its required floor-advancement assertion. `old-priority` removes only the
generated parser's hold acquisition; ordinary parsing keeps its protection.

The PAD is **(A), behaviour twin**: PRE cleanup behaviour with the candidate's
text/data layout. It replaces each namespace's `plain_hold_begin` entry with
`mov %rcx,%rax; ret`, returning the supplied cut without acquiring a bucket.
PART2 stamping and the candidate parser remain. Exactly eight ELF bytes change;
file size, section sizes, addresses and data layout are preserved. Its SHA-256 is
`fd2555b316217d7142bdc89cf423bc5fa7c126382733fdb5951b8dfde87b84ce`.
This PAD is deliberately incorrect and is only a falsifier/measurement control.

The new GET/MGET hunt already rejects the specified PART2 binary at atomic 0
(29 violations / 6,792 triples) and atomic 1 (89 / 6,032), both within 0.3 s;
both 15-second sequential controls pass. These failures have no worker errors
or vacuity flags. Ledger: `build/gate-run.VOzAxs/ledger.partial`.
The complete release/PAD/priority falsifier runs and final instruction tables
will be recorded after the queued correctness work finishes.

### Parser carry and first complete matrix

The reordered-off selection passes **77/77** in
`build/gate-run.kiGt6g/ledger.partial`: all 32 inherited tornread rows, all 32 new
GET/MGET rows, ten cleanup/coordinator rows, the directed unit, release and R7.

The directed unit now also drives the actual normal parser through
`GET; MGET; GET` with an older ROB entry and an existing B bucket. Its unit-only
allocation observer advances the commit watermark after the first GET publishes
and before MGET publishes; an assertion requires that exact window to open.
MGET's snapshot confirmation must then reach the younger GET's stamp in the same
parse pass. Both namespaces pass. An isolated `no-carry` header overlay fails
exactly `rob.at(3).read_cut(confirmed) == confirmed` (SIGABRT). No production
observation hook was added. The updated unit row passes through the gate in
`build/gate-run.iSToxF/ledger.partial` (**2/2**, including release).

### Endurance and continuous-window falsifier

All **13 arms × at least 180 seconds PASS** on the frozen final production image:
the original eleven Phase B arms plus GET/MGET at atomic 1 and EXEC-backed
GET/MGET at atomic 0. They checked 327,459,498 read pairs/triples, observed
15,808,642 value changes (at least 655,074 in every arm), and reported **zero
violations, zero worker errors and no vacuity flags**. The inherited runner's
arm definitions are preserved, with the lane's authorized CPUs/ports and
180-second durations. Server CPUs were 0–7, clients 16–17, ports 26590/26591.
Full logs: `build/tornread/endurance-20261109-075419/`; compact evidence:
`docs/tornhold-endurance.json`.

Each continuous-progress row now runs the exact nonempty-ROB schedule before its
30-second live cleanup probe. This is necessary because client-side outstanding
commands alone cannot exclude brief server ROB quiescence. The isolated always-A
image and its unit are linked from the same mutated owner objects; the control
receipt records both hashes. With that matching unit selected through
`GATE_TORNHOLD_PROGRESS_UNIT`, **all four continuous-progress rows FAIL** exactly
at `advances > 100`, before the live leg. The release and normal/db0 unit
prerequisites pass. Ledger: `build/gate-run.Sw0DbV/ledger.partial` (2 PASS,
4 intended FAIL). This is a deterministic falsifier of the nonempty-window
component; the standalone TCP probe is not claimed to falsify always-A by itself.

### Final read matrices and harness rerun

Reorder-on now also passes **65/65** in `build/gate-run.tS5hE0/ledger.partial`: all
32 inherited rows, all 32 GET/MGET rows and release. Together with the reordered-off
77/77 selection, both parser settings cover the full read matrix.

After composing the deterministic continuous-window check into the progress rows,
`tests/gates_test.py` passes **83/83** again (431.826 seconds). The unchanged real
label-fixture self-test still reports exactly one failure and one error caused
by the 75 deferred labels; the temporary projected inventory passes **12/12**.
Final logs are `build/tornhold/gates-test-after-progress.log`,
`label-fixture-final.log` and `label-fixture-projected-final.log`. Compact gate
receipts are being collected in `docs/tornhold-proof.json`; its pending status
will be replaced only after the broader regression and negative-control queue
finishes.

### Instruction-accounting plan and maintainer ABBA request

The four requested historical images are preserved under `build/tornread/` as
`tomokv-{pre,part1,part2,hold}` symlinks. An additional `tomokv-merged-part2`
control points to the verified integration image saved before hold changes;
comparing it with HOLD isolates this change from readability/aofblock integration.
Exact paths and digests are in `build/tornhold/pricing-arms.json`.

After correctness work and companion builds finish, run the unchanged finite
workload through `tools/tornread_instructions.py --place-io --arms pre part1 part2
merged-part2 hold --get-depths 1 8 32 128 --repeats 3 --port 26595`, with its parent
pinned to CPUs 0–11 and LC_ALL=C. Each repeat completes exactly 524,288 public
commands (eight connections × 65,536), checks every reply and the commandstats
count, and records perf's acknowledged boundaries and counter coverage. The
geometry remains eight server cores, 16 shards, 6:2 in split mode, uring, one DB,
read-local/key-LB/client-LB/automatic-FLIP off. Client connections are witnessed
on the same numbered IO threads in every arm. The additional GET depths expose
amortization; pipeline 128 spans at least two 64-slot ROB windows, so it cannot
be reported as one parser pass. No parser-pass counter is added to production.

The prior seed digest was
`78bb25654d20f7e1b017c4d5b363e41b1c4887a7b133dfaea0fff844981bf829`.
That snapshot is absent from the available worktrees and scratchpad. All arms
will therefore use a single newly saved seed, with its digest recorded; no claim
of identity with the historical key placement is made.

Maintainer ABBA request: use the gate's own instrument on a quiet box for the
20 required cells: GET p1/p32, SET p32, MGET-8 p8 and MSET-8 p8, each with atomic
0/1 and modes 1s/2s. Compare the supplied PRE/PART1/PART2 images, merged PART2,
HOLD, and the **PAD (A) behaviour twin** described above. Preserve the same
geometry and connection placement, and report per-cell rate at matched offered
load, cycles/public command, instructions/public command and IPC. The deciding
number is the matched-load rate; instruction savings alone do not establish the
expected approximately 1% default-config overhead. Check p1 and writes for
regressions, and use HOLD versus the same-layout PAD to distinguish mechanism
cost from text/data layout effects. No throughput result is claimed by this lane.

### Broad 132-row selection complete

`build/gate-run.8JwTsx/ledger.partial`: **132/132 PASS** on the final native image.
Its label multiset exactly equals tornread's original 132-row receipt. This covers
ASAN, atomics/MVCC, FLUSH, blocking, BGSAVE/EXEC, read-local ordering, transaction
ordering, WB rules and the complete FLIP/MULTI/WATCH storm. Every declared mode
inside each job ran. `GATE_PROOF_NO_RATES=1` retains the correctness assertions
and leaves rate-only checks to the maintainer.

The initial one-slot invocation `build/gate-run.1caOJm` was stopped after its
companion build completed, once both CCX slots became available. Its partial
ledger is excluded from pass totals; the full selection then ran in two disjoint
8-core, 6:2 slots. `build/tornhold/reschedule.json` records that scheduling change.
The remaining selected regression jobs, including all 35 feature-interaction
cells, are now running separately.
