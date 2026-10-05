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
| IO2 (all instructions) | 294 → 284 | 73496 → 73582 | 11936 → 11928 | 29915 → 29889 |
| IO2 (executable only) | 294 → 284 | 37455 → 37541 | 1555 → 1547 | 7760 → 7734 |

Receipts include exact PCs and visit counts in `docs/iopass/PRE.json` and `IO2.json`.
The GET count increase is recorded, not treated as a performance improvement.

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
