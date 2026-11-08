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
  accounting: pending.

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
