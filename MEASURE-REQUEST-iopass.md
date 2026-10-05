# IO-pass shared-line diet (round 3)

Base: `f769efcdd764e5d93286f19f8998bfa616c1fab5`, merged from `origin/cpp` before edits.
No performance result is claimed. Mainline owns the live gate and measurement.
Implementation is complete on `cx-iopass`: IO2 `d74d8be97`, IO3 `7b4dd2f89`,
IO4 `82831193c`, IO6 `7ea2ac892`, IO7 `8cfc15509`. The resume verified that
`origin/cpp` was already merged and retained the first four implementations.
Nothing was pushed. Frozen binaries, receipts, controls and remaining mainline
checks are recorded below.

## Instruction receipts

`tools/iopass_receipts.py` derives its tracer from `tools/lbplanner_trace.cc` to single-step a serverless
boundary: the production cron predicates, writer probes, completion drain, full
parser(s), and FLIP control tail. It excludes the network, clocks, executor execution,
and the other pass consumers. These are **instructions per named work slice**, not
server instructions/op or cycles/op. Fixture setup and command execution/retirement
are outside the boundary. Every command must publish and complete successfully.
The fixture is copied verbatim from the existing core witness; no fixture is edited.

Cases: quiet non-elected IO with save enabled; 32 connections each submitting one
GET; one SET; one eight-key atomic MSET spanning eight shards/two executors. Geometry
is 16 shards, six IO/two EX. All witness execution is pinned to CPUs 112–127.
The executable-only column excludes shared-library instructions (allocator and libc).

| Item | Quiet PRE → POST | GET32 PRE → POST | SET PRE → POST | Atomic PRE → POST |
|---|---:|---:|---:|---:|
| IO2 (all instructions) | 294 → 284 | 73346 → 73336 | 11891 → 11881 | 21707 → 21670 |
| IO2 (executable only) | 294 → 284 | 37455 → 37445 | 1555 → 1545 | 7761 → 7751 |
| IO3 (all instructions) | 284 → 286 | 73336 → 73146 | 11881 → 11876 | 21670 → 21651 |
| IO3 (executable only) | 284 → 286 | 37445 → 37255 | 1545 → 1540 | 7751 → 7732 |
| IO4 (all instructions) | 286 → 285 | 73146 → 73145 | 11876 → 11875 | 21651 → 21650 |
| IO4 (executable only) | 286 → 285 | 37255 → 37254 | 1540 → 1539 | 7732 → 7731 |
| IO6 (all instructions) | 285 → 146 | 73145 → 73028 | 11875 → 11758 | 21650 → 21533 |
| IO6 (executable only) | 285 → 146 | 37254 → 37137 | 1539 → 1422 | 7731 → 7614 |
| IO7 (all instructions) | 146 → 146 | 73028 → 72772 | 11758 → 11752 | 21533 → 21072 |
| IO7 (executable only) | 146 → 146 | 37137 → 36881 | 1422 → 1416 | 7614 → 7170 |

Receipts include exact PCs and visit counts in `docs/iopass/*.sites.json.gz`, with
totals and decoded shared-load sites in the corresponding JSON. Correctness cases
compile separately from the receipt driver, so adding a witness cannot perturb its
code generation. PRE/IO2 were regenerated with that separation. Library paths in
the atomic case depend on allocator/libc paths and code placement; use executable
counts for attribution. Every row compares the preceding item to that item,
and both instruction totals include the same boundary and command inputs.
IO3's two-instruction quiet-path increase is recorded, not called a performance win.

The original tracer counts a trap for **each REP iteration**. The IO7 receipt
work corrected that accounting: one executed REP instruction counts once, while
`ptrace_steps` and `rep_iteration_steps` retain the uncollapsed counts. The table
above and all six JSON receipts use this same normalization. The dedicated
zero/one/64/128-byte REP witness has four instructions at every size and passes
(`docs/iopass/tracer-self-test.log`). For IO7's atomic case, raw steps are
29,769 → 21,117; repeated REP steps are 8,236 → 45. That large raw-step reduction
is **not** an 8,652-instruction claim. Normalized executable instructions fall
444, and normalized all-instruction counts fall 461. Re-running the IO6/IO7
receipts during resume reproduced the table exactly.

## Per-pass shared-line accounting

This table counts loads attributable to the changed sites and the distinct lines
those sites cease probing. It does not claim measured cache misses, RFOs, or that
another unchanged consumer cannot access the same line. The completion ready mask
is two contiguous 64-byte lines; placement's heap-buffer address is runtime data.

| Item | Before → after on the applicable pass | Shared lines removed from these probes | Work retained / fence |
|---|---|---|---|
| IO2 | live-save policy + Placement vector header + first owner → one IO-private election byte | Up to 3 on a default-save pass; the audit's header/buffer pair is removed | Elected IO checks live save/shutdown policy on the one-second beat; boot/CONFIG/RoleReady refresh election |
| IO3 | FLIP reads: quiet 3 → 1, GET32 131 → 1, SET/atomic 7 → 1 | 0 unique lines; respectively 2/130/6/6 repeated shared reads removed | Pass-start acquire; live coordinator and armed-tail/epoch fences |
| IO4 | Two manager probes → private binding tests when both writers are unbound | 2 per probe pair | Three call sites are covered; the main pass and its selected idle sweep may revisit the pair, not three simultaneous sweeps; real bound writers retain ID/phase checks |
| IO6 | 16 ready-word loads → `ceil(assigned-high-water / 64)` | 2 at zero slots, 1 at 1–512 slots, 0 above 512 | 1–64 slots need one word (15 word loads removed); full 1024-slot and unmasked channel fallback remain |
| IO7 | Capacity-wide zero/construction and parser-frame scratch → shard/participant-sized atomic-only work | 0 shared lines | Removes private stack writes; touched-owner demand reset, capacity-before-publication, one bundle/tail publication per owner |

## IO2: elected save-cron owner

The hot predicate reads one IO-private byte. Boot activation, a changed CONFIG
snapshot, and RoleReady refresh the election. The refresh only reads Placement
after acquiring Idle or RoleReady: activation can otherwise race the coordinator's
individual role stores. Every surviving/new IO refreshes before its RoleReady ACK.

Removed per pass on a default boot: the live-save word, Placement vector header,
and vector heap-buffer reads used by the writer probe (up to three distinct shared
lines; the vector/header pair identified by the audit is always removed).

The byte intentionally caches **election**, not the save-enabled bit. Signal shutdown
sets a bit without publishing a CONFIG mailbox version, including a race with CONFIG
disabling save. The elected IO remains a guaranteed looker; `save_cron_pass()` checks
the live policy on its existing one-second beat. With save disabled, this adds one
no-work policy check per second on the elected IO; the other IO threads remain dark.
`IO2-checks.log` covers boot, CONFIG enable/disable, pending signal, blocked role-vector
access during conversion, and election transfer at RoleReady.
Risk: the elected IO's save-disabled pass still arms the cold beat, so the
`save ""` null must include that owner. A future role transition must retain
the refresh-before-ACK edge.

## IO3: pass-start FLIP snapshot

The normal idle pass acquires stage once before any parser or cron. That decision
is reused by the cron gates, per-frame map stamping, read-local demotion gate,
ordinary dispatch, and the two backpressure-resume paths. An Idle sample permits
work until this IO acknowledges a drain; the control tail **does not ACK** a drain
that started after an Idle sample. The next pass samples the drain, fences every
parser (including later sweep/park callbacks), and can then ACK. A stale paused
sample delays ordinary work for at most that pass. Accept/role-management cold
paths retain their live stage reads.

Two live fences deliberately remain: (1) the coordinator's private `c == flip_client_`
test precedes its shared read, since a manual FLIP can begin after the sample; (2)
an armed control tail reacquires stage before checking the current epoch's ACKs and
updates the pass snapshot before any later parsing. The database control path also
retains its existing live read and `multidb_dispatch_allowed` exception. Without the
tail reacquire, an already-ACKed old stage can be applied to a newly opened epoch.
Standalone callers without a pass retain the original live fence via an unset byte.

| Snapshot consumer | Why the sample preserves its fence |
|---|---|
| Client/save cron prologue | An Idle sample runs before this IO's drain ACK; a paused sample can defer a beat until the next pass |
| Multi-DB gate before `multidb_stamp` | A paused sample stops before capturing a map even if the live stage has just become Idle; an Idle sample cannot outlive this IO's unacknowledged map-drain grace; the existing initiating-client exception remains live |
| Partial read-local demotion | The same paused sample fences publication of older owner Tasks, retaining the unconsumed current frame and its existing conflict/RYOW state |
| Ordinary per-operation dispatch | Idle-sampled work precedes this IO's ACK; a paused sample blocks new fanout in every parser invocation in the pass |
| `wb_observe` / `flush_ready` backpressure resume | Both use the same sample as parsing; clearing the connection bit cannot bypass a paused parser gate |
| Armed control tail | Keeps a live acquire for epoch/stage ACKs and updates the snapshot before any subsequent sweep or park callback |
| Manual coordinator parse gate | Keeps `c == flip_client_ && srv_->flip_dispatch_paused()` in that order so a FLIP started after the sample immediately fences its own connection |

Actual traced stage reads, IO2 → IO3: quiet 3 → 1; GET32 131 → 1; SET 7 → 1;
atomic group 7 → 1. No unique shared line disappears (the stage line is still read
once); redundant reads disappear. No new knob or changed ownership/RYOW protocol.

`IO3-checks.log` proves delayed ACK, post-ACK rejection, epoch rollover, immediate
coordinator fencing, conservative database stamping, and resume. Four throwaway
controls each fail the named assertion: no pass sample, open parser, stale tail
stage, and cached coordinator gate. These are compiled source mutations under
`build/`, never production switches. All four `flip-*.log` receipts record rejection.

Risk: snapshots trade up to one pass of control latency for fewer loads. Mainline
must exercise both FLIP directions and SWAPDB under the requested loaded geometry.

## IO4: bound writer probes

All three writer-probe pairs (ordinary pass, sweep, pipeline sweep) use the same
predicates. AOF is exactly `aof_bound_ && aof().writer_is(id)`. Binding is only set
after successful `bind_writer` under `configured()`, and remains sticky through
deactivation/reactivation. It is not a writer-election bit: configured non-writers
still check the elected ID. Neither stickiness nor reply durability gating changes.
`writer_is(id)` itself is `configured_ && id == writer_tid_`, so the full predicate
retains the reply gate's configured-state requirement after the private byte.
A real writer cannot exist without the successful binding that sets that byte.

Snapshot is `self_->snapshot_writer_bound() && snapshot().writer_is(id)`, with a
false writer check retiring the private binding. Every entry into the common
`SnapshotManager::start` arms the actual writer before any operation can leave a
snapshot needing writer progress, including failed/cancelled starts. No reliance on
`SnapshotStart` CQEs: those notify executor owners and may never arrive at a split
IO writer. SAVE/BGSAVE, scheduled save, rewrite, and shutdown all use that entry.
The byte occupies existing ThreadCtx padding; it is written only on the chosen
physical IO thread. No new allocation or per-operation branch is introduced.

Default/off savings: two manager cache lines per probe pair, including the park
backstop. When bound, the original writer-ID/phase predicates and writer passes
remain, including the unmasked sweep. A zero-work writer pass does not clear a live
epoch; only a later false `writer_is` retires its binding.

`IO4-checks.log` exercises real common-start binding via deterministic file-open
failure (no snapshot file), standalone snapshot progress, a held cancellation ACK,
rearm, AOF election, and sticky role binding. Four negative controls fail exactly:
missing start binding, incorrectly requiring AOF for snapshot progress, clearing
an active snapshot binding, and clearing AOF binding on deactivation.

Risk: any future snapshot-start bypass must arm the same private binding. The
existing common start is the sole selection point; live BGSAVE/AOF gate coverage
remains required on mainline.

## IO6: assigned-slot high water

`wb_slot_words()` derives `ceil(slots_.size()/64)` from the sender-private table.
Assignment is the only operation that grows that size. Reserve changes capacity,
and release/reuse preserve the high water. This is an exact bound maintained by
the existing assignment path, with no second counter that could get out of sync.
The completion drain computes it **after** inbound adoption, so a just-assigned
slot is included. The maximum and channel fallback are unchanged.

Zero assigned slots: 16 → 0 ready-word loads, removing both 64-byte ready-mask
lines. 1–64 assigned slots (including GET32): 16 → 1 loads, removing one of the
two lines. At 1024 assigned slots the scan is unchanged. A thread that once reached
that high water continues scanning all words after churn; it never hides a late
notification by shrinking the bound. `ReadyMask::any`, queue-depth park rechecks,
and mask-independent completion sweeps remain intact.

`IO6-checks.log` covers zero allocation/slots, reserve without assignment, every
assignment through 1024 including each 64-bit boundary, full-table channel fallback,
release, a late bit for a released slot, reuse, and the unmasked sweep. No new field
or layout change. The `slots-first-word` control fails the high-word completion
assertion (`docs/iopass/slots-first-word.log`). Risk: the high-water bound does not
shrink after churn, so savings disappear for formerly dense owners. Mainline's
2048-connection cell must confirm the full-bound regime.

## IO7: atomic scatter scratch

Only the atomic-write arm calls the non-inlined `dispatch_atomic_scatter` helper.
It reuses the IO-private, zero-on-entry `dispatch_needed_` array and visits only
the owners touched by this group. Route storage is sized to `nshards`; the dense
participant list reserves `min(nshards, kMaxThreads)` entries and initializes only
its live prefix. After every owner's queue-capacity check succeeds, Task storage
is sized to `nshards` and participant offsets to the actual `nparticipants`.
Every live Task is constructed once, including its zero enqueue timestamp.
There is no heap allocation. Work is O(shards + participants), with no capacity-wide
clear or unused Task construction. The helper's return releases dynamic stack
storage before the parser processes another group.

The plain scatter arm and its scratch remain unchanged; its body SHA-256 is
`f741f9a3798b2e44ebde5606efed367b866c6f43287563d85ceb638995ee28ba`.
Its surrounding shared parser frame loses only the atomic arm's scratch. The R7
parser is regenerated from the same source and calls the same helper.

Every helper exit preserves the shared scratch invariant:

1. Capacity refusal clears **all** participating owners, including owners after
   the refusing one, then abandons the unpublished scatter state. No frame is
   consumed and no ROB/group publication occurs; the caller retries later.
2. After building the live Tasks, all demand/fill-cursor entries are reset before
   the `cursor != nshards` invariant abort.
3. An unexpected `post_tasks_quiet` failure aborts only after the same reset.
4. Successful return retains all-zero scratch. Every owner still receives one
   ordered bundle after ROB/group publication and one queue-tail publication;
   the existing parse-pass notification fold remains in place.

`IO7-checks.log` covers split and fused eight-key MSET/DEL, interleaved plain
EXISTS, early/later participant refusal on freshly filled queues, retry, exact
reply/admission/group retirement, and all 256 shards. Both missing-reset controls
fail the intended assertion (`atomic-refusal-dirty.log`, `atomic-success-dirty.log`).
The existing sixteen atomic-survivor cases and both `plain_0`/`plain_1` witnesses
also pass, including their collapse/lost-update schedules.

Risk: this uses the existing GCC toolchain's `__builtin_alloca`. The current
256-shard/128-thread limits bound live scratch to 11,264 bytes before alignment
and helper spills at maximum fanout; the eight-shard/two-owner case uses 360 bytes
of array storage. Changing those limits requires reconsidering that stack bound.
The call boundary and changed parser placement can affect IPC or latency despite
the instruction decrease; the single-key null and full-fanout checks remain required.

## Validation and frozen artifacts

The resumed run passed **83/83** serverless validation jobs; exact commands and
results are in `docs/iopass/validation/results.json`. This includes the existing
ASAN/UBSAN core and database witnesses, both database namespaces' reorder
engagement controls, both thread modes' topology witnesses, the atomic survivors,
and source/synchronization checks. The admission witness requires exactly eight
allowed CPUs: the runner selects eight within 112–127. The old reorder logs
without `--engagement` are retained as failed invocation evidence; the final
manifest references the corrected, passing commands. `atomic-plain-checks.log`
records the additional plain-write self-test and both atomic-mode witnesses.

All fourteen groups in the gate's serverless instrument self-test row passed
(`docs/iopass/gate-self-tests.log`, final `FAILED []`); these were run directly,
without invoking `tests/gate.sh`. The IO3/IO4 controls and positive witnesses,
IO6 high-word control, IO7 positive/negative witnesses and REP tracer control
are retained separately in `docs/iopass/`. The resume reran IO7, its two negative
controls, the IO6/IO7 receipts, existing serverless validation and atomic plain
witnesses. No server, load generator, rate benchmark or live gate was started.

**Baseline build blockers remain:** the legacy `build/reorder-unit` and
`build/r7shadow-unit` targets reference removed `kGenthreadPipelineExBatchOps`
and fail to compile against unmodified PRE as well. Their source and
`genthread_pipeline.h` are unchanged from `origin/cpp`; the saved baseline
compiler failures are `docs/iopass/baseline-{reorder,r7shadow}-build.log`.
These two targets are not counted in 83/83. No fixture, expected count, or retired
constant was altered to make them pass. The working production reorder engagement
witnesses pass in both namespaces. A blanket claim that every legacy target
builds would be false.

`docs/iopass/layout.json` verifies all eight locks in both namespaces:
Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192,
AtomicEntry 144, Config 624. Every existing IoLoop, ThreadCtx and Server member
offset and total size is unchanged. New private bytes use existing padding.
Production 1s/2s paths are compiled; live boot remains part of mainline's gate.

Fixed parser stack subtraction (excluding pushed registers) is 12,896 → 1,888
bytes in split mode and 13,184 → 2,176 in the ordinary fused symbol, in both
namespaces. The receipt sums every prologue subtraction, including PRE's three
stack-clash page probes; reporting its first 4,096-byte subtraction as the whole
frame would be wrong. Compiler clones and exact symbols are also in `layout.json`.

| Arm | Source | Frozen path | SHA-256 | `.text` bytes |
|---|---|---|---|---:|
| PRE | `f769efcdd764e5d93286f19f8998bfa616c1fab5` | `build/iopass-pre/tomokv` | `25f509c90063f3694277ec7b9d2801b1628e026627385704ff6e5cde3d45ed2a` | 7,800,640 |
| POST | `8cfc15509` | `build/tomokv` | `ca14676e124b9729603d27382692fcf18323f1474286cd7f78ec57945829cf07` | 7,781,132 |

PRE was built in this worktree before edits. POST was checked current against the
production sources; documentation/tooling edits do not rebuild it. Full binary
hashes are independently recorded in the layout receipt. No binary is pushed.

**no PAD: every item changes behaviour.** Each item changes executed loads,
initialization or scratch work; none is merely a relocation. Protocol semantics
are preserved. IO7's frame movement accompanies removal of real initialization
work, and no existing object field or layout lock moves. The 19,508-byte `.text`
shrink remains a placement risk for mainline's null; instruction receipts alone
cannot attribute a cycles/op improvement to the removed shared reads.

Useful reproduction commands, all serverless (PRE objects are already frozen):

```sh
taskset -c 112-127 python3 tools/iopass_receipts.py IO7 --source . --checks
taskset -c 112-127 python3 tools/iopass_controls.py atomic-refusal-dirty --source .
taskset -c 112-127 python3 tools/iopass_controls.py atomic-success-dirty --source .
taskset -c 112-127 python3 tools/iopass_receipts.py IO6 --trace-only
taskset -c 112-127 python3 tools/iopass_receipts.py IO7 --source .
taskset -c 112-127 python3 tools/iopass_receipts.py --tracer-test
taskset -c 112-127 python3 tools/iopass_receipts.py --layout
taskset -c 112-119 python3 tools/iopass_validate.py
taskset -c 112-119 build/atomic-survivors-unit plain_0
taskset -c 112-119 build/atomic-survivors-unit plain_1
```

## Requested mainline measurement — pending

Use frozen PRE and POST with the gate's own instrument and contemporaneous
same-binary null. Record achieved rate, matched offered load, cycles/op,
instructions/op, IPC and latency per cell. **Cycles/op and rate at matched
offered load decide**; the two instruction totals above do not constitute a win.

The 14-cell null is `tests/wbland_merit_cells.txt`, SHA-256
`de0e56e4696f780543c5adea21aa7d7283c12fa22110be6064370a69a2a68dc6`:
`h05,h06,p8g,p8s,d1g_l0,d1s_l0,m8g_l0,v1g_l0,d128g_l0,d32g_l1,d8s_l1,d32s_l1,x9_32_l1,x9_32_l0`.
Retain its exact cells/pins and current saturation receipts. Run the matched-rate
cycles/op comparison on h05/h06 (1s GET/SET p32) and d32g/d8s (2s GET p32/SET p8).
The latter two names explicitly mean the split counterparts of the read-local=1
shapes here; the existing `_l1` rows in the 14-cell file themselves select **1s**.
Their requested definitions are in `docs/iopass/split-cells.txt`; validate their
split-specific load calibration rather than reusing a fused calibration.
The gate's cell reader accepts both definitions (`docs/iopass/cell-parse.log`);
they deliberately contain no invented load-instance pin.

For the existing headline/null geometry use 32 physical server cores (0–31),
load cores 32–111, no SMT, 512 connections, 2M keys, 64-byte values except v1g,
uring, atomic=1, overlap=1, reorder=0, default balancers, and disabled save.
Keep the instrument's shard/ratio derivation (fused 256 shards; split
`min(8*nexec,256)`) and its calibrated measurement windows. Correctness and
forced-fence repetitions separately use the gate's 16 shards and eight-core
6 IO + 2 EX geometry; do not treat either geometry's receipts as the other's.

| Three-regime bar | Required cells / witnessed work | Decision |
|---|---|---|
| Neutral | 14-cell null, split d32g/d8s, single-key GET/SET; save default and `save ""` subarms | Every cell stays within its contemporaneous two-sided null; compare matched-rate cycles/op, IPC and instructions/op |
| Exercised | Atomic eight-key MSET/DEL at **p8** in both modes; AOF enabled; completed BGSAVE under load | Correct atomic replies/RYOW and real writer progress, no regression; report the atomic group's cycles/op rather than inferring merit from instruction counts |
| Possible deficit | FLIP both directions and SWAPDB under 512-connection p32 single-key load; persistence cancellation/rearm; 2048 connections / fully assigned ready mask; full 256-shard atomic group at p8 | Drain/epoch/movement and persistence windows must actually open and complete; no stranded work, torn reads or lost replies, and no cycles/rate/tail regression |

Use bounded fresh-state rearming and fail an unentered window. Preserve the
existing same-binary acceptance bands; no widening or classification of missing
measurements as passing. Multi-key p32 is excluded by the owner's congestion law.
Mainline still runs `tests/gate.sh iteration`, including AOF/BGSAVE, FLIP,
multi-DB and both thread modes, before merging. All measurements requested here
remain pending.

**Gate rows added = 0** (quick +0, full +0). No collection line was added on either
side of the quick-tier exit, so `EXPECT_QUICK` / `EXPECT_FULL` need no change.
No existing fixture was edited. The split measurement definitions are requests,
not new gate rows.
