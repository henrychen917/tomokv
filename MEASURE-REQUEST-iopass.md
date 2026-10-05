# IO-pass shared-line diet (round 3)

Base: `f769efcdd764e5d93286f19f8998bfa616c1fab5`, merged from `origin/cpp` before edits.
No performance result is claimed. Mainline owns the live gate and measurement.

## Instruction receipts

`tools/iopass_receipts.py` uses `tools/lbplanner_trace.cc` to single-step a serverless
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
| IO2 (all instructions) | 294 → 284 | 73496 → 73486 | 11936 → 11926 | 29916 → 29933 |
| IO2 (executable only) | 294 → 284 | 37455 → 37445 | 1555 → 1545 | 7761 → 7751 |
| IO3 (all instructions) | 284 → 286 | 73486 → 73296 | 11926 → 11921 | 29933 → 29887 |
| IO3 (executable only) | 284 → 286 | 37445 → 37255 | 1545 → 1540 | 7751 → 7732 |
| IO4 (all instructions) | 286 → 285 | 73296 → 73295 | 11921 → 11920 | 29887 → 29886 |
| IO4 (executable only) | 286 → 285 | 37255 → 37254 | 1540 → 1539 | 7732 → 7731 |

Receipts include exact PCs and visit counts in `docs/iopass/*.sites.json.gz`, with
totals and decoded shared-load sites in the corresponding JSON. Correctness cases
compile separately from the receipt driver, so adding a witness cannot perturb its
code generation. PRE/IO2 were regenerated with that separation. Library paths in
the atomic case vary by 27 instructions; use executable counts for attribution.
IO3's two-instruction quiet-path increase is recorded, not called a performance win.

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

## Artifacts and requested mainline measurement

Frozen PRE: `build/iopass-pre/tomokv`, built in this worktree before edits.
SHA-256: `25f509c90063f3694277ec7b9d2801b1628e026627385704ff6e5cde3d45ed2a`.
POST and final validation inventory will be recorded after the remaining items.

Run the 14-cell null, then matched-rate cycles/op on h05/h06 (1s) and d32g/d8s
(2s), plus the three-regime bar. Report cycles/op, instr/op, IPC, and achieved rate;
cycles/op and rate at matched offered load decide. Include save-default versus
`save ""`, AOF enabled, BGSAVE under load, FLIP/SWAPDB under 512-connection p32,
2048 connections, and atomic eight-key MSET/DEL at p8. Do not run multi-key p32.

No gate rows added; no EXPECT constants or fixtures edited. The gate and live
server/benchmark measurements have not been run by this lane.
