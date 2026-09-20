# mdbqsbr — map lifetime only

## Launch audit (before changing lifetime semantics)

Worktree `/home/user/Projects/cx-mdbqsbr`, branch `cx-mdbqsbr`. Launch HEAD
`f3cf0fc915386fc6b692ac85a0d12ffd86d040ea` is `b8fe404e2` (landed mdbstamp)
plus a gate reference-binary update only. PRE is built from that HEAD with the
default release Makefile flags. No server, gate, load generator, counter run or
performance measurement is authorized in this lane. All compilation uses
`taskset -c 112-127 make -j16`; eight-core units use `112-119`.

Reverified: `multidb.h:33-40` increments/decrements one shared counter with SC
RMWs; its pointer load and all three publications are SC. The counter protects
only reclamation. `multidb.cc:22-92` retires only at publication and clears only
on global reader count zero. `prepare_publish` reserves before the transaction's
non-failing commit. AOF record precedes publication. The mdbstamp regular-range
specialization and both stamping overloads must remain unchanged.

### Complete reader and participant inventory

These are launch line numbers, recorded **before** implementation. `Read` retains
one raw immutable map only until its destructor; no caller exports that pointer.
`capture()` returns an owning 256-byte copy plus epoch. All other retained routing
state is copied namespace bytes, owning keys, or an owning transaction map.

| Reader / caller | Physical participant and complete lifetime | Existing coverage / planned safe point |
|---|---|---|
| `multidb.cc:42 capture`, `:95 logical`, `:157 multidb_stamp` | Synchronous stack; copy/scan/stamp must finish before quiescence | Covered by the calling coarse scope below; no per-read registration |
| Baseline parser `io_loop.h:3127` | Connection's physical IO; split IO, fused IO, overlap passes, RL2S IO; includes both COPY/MOVE endpoints | Ordinary IO has no scope today. Add one outer scope for each complete `run_loop` pass, before CQ/epoll callbacks and through idle sweep/wait callbacks |
| Reorder parser `reorder.cc:2681` (relocated by audit) | Same physical IO, including R7 fused schedules | Mirror the same outer scope in `r7_run_loop`; no changes to pause-before-stamp/admission |
| `multi.inc:587` EXEC preparation | IO dispatch stack; `state.database_map` and speculative routing map are owning copies | IO outer scope; copied map may outlive it safely |
| `multi.inc:221,2391,2457,2530,2556` WATCH logical attribution; `:2565` SWAP watch | Shard's current physical owner, ordinary commands, transactions, maintenance, expiration and blocking execution | Existing EX/fused/sweep scopes nest inside the complete owner/IO pass. Extend split EX coverage around the complete pass, including maintenance and idle sweep |
| `notify.inc:405` keyless attribution | Owner expiration/eviction/notification work, also fused control | Complete owner/IO pass; only copied DB byte retained in output |
| `blocking.inc:357` parked request remap | Owner maintenance, ordinary and reordered sweeps | Complete owner/IO pass; `Read` ends before returning; blocking registration holds owning key bytes |
| `blocking.inc:1266` resumed MOVE stamp | Connection's IO, after owner aliases are dropped | IO outer scope; preserves boundary guard and remap protocol |
| `t_server.cc:2667` INFO keyspace rendering | IO finishing scatter result or synchronous owner command; copied stats table | Whole IO/owner pass; full formatting walk completes before safe point |
| `snapshot.cc:204` snapshot/AOF rewrite admission capture | Designated physical IO, explicit SAVE/BGSAVE or save cron | IO outer scope, existing shape mutex/exclusions retained; snapshot owns its copied map |
| `snapshot.cc:945`, `aof.cc:2505` restore | Startup/recovery owners, before entering worker loops | No runtime grace acknowledgement until that physical thread reaches its first loop safe point; retained versions survive initialization |
| IO-only control, client retirement, blocking resumes, owner maintenance | Every physical worker, independent of current role and `--read-local` | Fixed participant set initialized before workers start; acknowledgements are physical-thread indexed, never IO/EX role indexed |
| Park / resume / IO↔EX conversion / teardown | Same physical participant, even while role functions return | No parked/even/self exemption. Waits already have 50ms ceilings. First next pass acknowledges only after previous stack unwinds; role changes do not reset acknowledgements |
| Startup main, serverless fixtures, standalone `DatabaseMap` | Cold lifetime domain; no concurrent loop acknowledgement permitted for an unscoped cold reader | Unbound maps retain all obsolete versions until destruction. Bound server fixtures may read outside loops only while they do not advance grace concurrently, or explicitly use the same coarse scope. No assumed tid 0 |
| Shutdown / destruction | Stop and join every worker before destroying Server/DatabaseMap | Destruction owns the final grace after joins, including any participants that exited without a final acknowledgement; no map references may escape destruction |

Existing `ClientWorkScope` uses odd/even release stores and nested scopes do not
change the outer value. Its Client lifetime reaper (`io_loop.h:5485`) relies on
the acquired ROB Done edge. That proof and implementation stay intact; its
skip-even/skip-self rule will **not** be reused for map reclamation.

## Planned publication proof and memory guarantee

Use a monotonically increasing retirement request. A writer initializes the map,
release-stores the pointer, then release-publishes the request. Every physical
participant must acquire that request at a coarse safe point with an even
`client_work_epoch`, then release-acknowledge that exact request. The reaper
acquires **every** acknowledgement before freeing that generation. Acknowledging
also makes publication happen-before the participant's next acquire map load.
Thus entry racing publication either has an old acknowledgement (cannot free),
or has acquired publication (cannot load the retired version). An even epoch
sample alone supplies no evidence. A nested safe point cannot acknowledge while
the outer scope is odd. The publishing worker is included. No execution drain is
part of this argument.

The maintenance gate must precede any cold-state dereference, argument expansion,
locking or full participant scan. Only physical worker 0 scans; all workers
acknowledge. Existing loop progress, including bounded idle waits, drives the
last retirement without another publication. Quiescence is progress based, not
time based. A permanently stopped participant can retain an unlimited queue
during unlimited publications; this lane claims no hard memory bound.

## Results and mainline work

Implementation, deterministic assertions/negative controls, layouts, hashes,
measurement cells and final diff inventory: PENDING, to be completed below.

Gate launch arithmetic: existing core rows at lines 1242–1250, multidb unit rows
1298–1308, and 16 live/serial rows collected at 2783–2786 are all before the
quick exit at 2808. Extend existing rows only: +0 quick / +0 full = **438 / 454**.
`EXPECT_QUICK` / `EXPECT_FULL` and `tests/multidb_serial.py:20-57` remain untouched.
