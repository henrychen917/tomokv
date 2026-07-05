# Polymorphic Thread Modes — design (v1)

Threads are not born io/ex/wb — they HOLD A MODE and shift by load. Total threads fixed
(= populated cores or configured N); the balancer moves the MODE MIX, never the count.
CPU-architecture framing: morphable execution units; mode shifts are DVFS-like state
transitions with asymmetric latencies.

## Modes & transitions
| transition | mechanism | cost |
| :-- | :-- | :-- |
| EX-exit | migrate own buckets away (v8d effect-log + drain-fence — EXISTS) | ms, bounded |
| EX-entry | wake + migrate buckets in (same machinery) | ms, bounded |
| WB<->any (3s) | fenced client->wb re-partition | cheap |
| IO-entry | start accepting on own SO_REUSEPORT listener | INSTANT |
| IO-exit | stop accepting; pinned conns drain naturally; HYBRID io-drain + ex-warmup meanwhile | gradual |

## Balancer (micro-arch controller, current-signal only)
Signals: io busy% EWMA, ex queue-depth EWMAs (exist in reshard controller), wb backlog EWMA.
Decision: hysteresis band + settle window (reshard patterns); shift ONE thread per settle.
Knobs: tomokv-io-threads-min/max, tomokv-ex-threads-min/max (0=auto: min 1, max=cores);
static mode (current mandatory counts) remains the default until dynamic proves itself.
Pin modes: 0 pure-float, 1 manual, 2 pure arch-aware, 3 dynamic-float, 4 dynamic-arch-aware
(re-derive placement on shift events).

## Danger zones (from this codebase's history)
- iotid TLS aliasing when a thread changes role (the historic worker-slot crash class):
  mode-scoped identity must swap iotid/worker-id ATOMICALLY at the checkpoint, and
  current_client[]/queues[producer]/freeback[producer] indexing must be valid for BOTH
  roles during the transition window.
- All per-role structures sized for total-N at boot (any thread can hold any role).
- Transitions only at safe checkpoints: EX = post-drain-fence (no in-flight on own shard);
  IO = empty-event-loop pass; WB = post-retire fence.

## V1 scope
1. Unified thread main: `while(1) switch(atomic mode){IO: ioSlice(); EX: exSlice(); WB: wbSlice();}` —
   refactor ioThreadMain/exThreadMain bodies into single-pass slice functions.
2. EX<->WB shifting (3s) + IO-entry / gradual IO-exit (both forks).
3. Balancer v1: ex-queue-depth vs io-busy EWMA ratio, one shift per settle window.

## V1 status (steps 1-3 landed, 2s fork)
Legal transitions are SPARE-ONLY: PARKED->IO (step 2, instant listener join),
PARKED->EX and EX->PARKED (step 3, migration-backed on the v8d effect-log engine;
go-live/delist keyed to the bucket-table FLIP via num_workers_live, spare slot
pre-allocated via num_workers_alloc, parked shard asserted EMPTY). Rejected until
built: IO-exit (gradual conn drain) — so IO->PARKED and any direct IO<->EX swap
refuse at both the config layer and the poly checkpoint; WB is unreachable in the
2s fork (modeshift value 3 is repurposed as the explicit park verb). Non-spare
threads never shift. Driver: CONFIG SET tomokv-modeshift-test (balancer pending).

## Balancer pressure signals (user spec, step 4)
Shift decisions read PRESSURE, not guesses — each signal a cheap current-value/EWMA, micro-arch style:

| signal | source | Tomasulo analog |
| :-- | :-- | :-- |
| ingress queue backlog | epoll-ready count + unparsed querybuf bytes per io thread | fetch-queue occupancy |
| worker queue backlog | SPSC queue depths (head-tail), EWMA per worker (reshard controller has these) | reservation-station occupancy |
| reply ROB occupancy | per-conn in-flight (dispatchid - flushid) aggregated per io thread | ROB occupancy |
| socket write backlog | clients_pending_write length + pending reply bytes (+ kernel sndbuf if cheap) | retire/writeback pressure |
| per-role CPU idle/spin ratio | idle-episode ticks vs busy slices per thread (adaptive-spin state already tracks episodes) | port utilization |
| p99 command latency | sampled latency ring / hdr histogram (guardrail, not a trigger) | pipeline stall indicator |

Decision shape: shift TOWARD the role with sustained high pressure ONLY when a donor role shows
headroom (high idle/spin ratio + low backlog) — pressure differential with hysteresis band + settle
window, one shift per window. p99 latency is the GUARDRAIL: if p99 degrades during/after a transition,
back off and extend settle (transitions are DVFS-like states; the balancer must respect their costs:
EX shifts = migration ms, IO-exit = gradual drain). All signals current-value or leaky EWMA — no
history accumulation, shifts re-evaluate on a dime.

## Shift confidence (user): expensive transitions need SIGNAL CONSENSUS
EX<->IO transitions cost real work (bucket migration / connection drain). The balancer must not act
on one hot signal: require a QUORUM — e.g. >= 3 of the role's pressure signals beyond the hysteresis
band, ALL sustained across the full settle window, AND the donor role showing headroom on >= 2 of its
signals — before an expensive shift. Cheap transitions (WB repartition, PARKED->IO) may act on fewer.
Micro-arch analog: confidence estimation before costly speculation — mispredicted shifts are the
expensive recovery, so bias strongly toward NOT shifting (p99 guardrail can veto and extend settle).

## Demoting the main thread (user proposal, step 5 candidate)
Abolish "main is special" past startup/shutdown: main becomes an ordinary io-mode poly thread holding
a transferable **CRON TOKEN** (serverCron/persistence-triggers/control-plane duties attach to the token,
not the thread). If main ever shifts roles, the token passes to another io-mode thread at a checkpoint.
Supported by the role-purity audit: main already IS io thread 0 + cron; upstream "am I main?" guards
(running_tid) are systematically defeated today — a formal token FIXES that class instead of faking it.
Watch items: fork() points (BGSAVE — token holder forks at a quiesced checkpoint), signal handling
thread, config-apply execution context (control plane = token holder). Startup/shutdown remain main's.

### Cron token: performance framing (user hypothesis — confirmed with nuance)
Cron work is CONSERVED (it still runs), so the aggregate win is not "cron disappears" — it is:
(1) tail-latency fairness: main's 1/N connections stop eating serverCron/beforeSleep/INFO pauses
    (today main is a degraded io thread; every tick is a p99 spike for its clients);
(2) PRESSURE-AWARE TOKEN PLACEMENT: the token itself follows the balancer's idle/spin signal —
    prefer the least-loaded holder, ideally a PARKED spare, so cron cost leaves the serving path
    entirely (true throughput gain ≈ cron's full cost + zero cron jitter on any served connection);
(3) uniform packing: the balancer can allocate main's core like any other (io1exN where the "1"
    is merely the current token holder).

### Cron DECOMPOSITION (user, supersedes the fat token): duties follow data ownership
Deprecate the obsolete, distribute the local, and shrink the token to the truly-global rump.
Sourced from the role-purity audit's duty inventory:

**DEPRECATE (obsolete under tomokv — delete, don't relocate):**
- databasesCron/activeExpire/defrag on the DECOY server.db (scans an empty keyspace every tick)
- upstream io-threads cron apparatus (IOThreadClientsCron etc. — dead code, io_threads_num==1)
- eviction/AOF/replication/cluster cron paths (config-gated off by RP-1; delete the tick checks)

**IO-MODE LOCAL (each io thread crons ITS OWN, in its slice, ~100ms cadence):**
- clientsCron for own clients: timeouts, qbuf shrink, output-buffer limits (fixes RP-3's orphan —
  today only main's 1/N slice is cron'd)
- cached-time refresh for its own loop; TLS-pending sweep

**EX-MODE LOCAL (each worker, in its idle/backoff slice — fixes RP-2's orphans, zero locks since
the owner is the sole shard writer):**
- activeExpireCycle over OWN shard; incremental rehash/resize of OWN shard dicts; (defrag later)
- operand-pool decay (already op-clocked per-owner — the existing pattern to copy)

**CRON TOKEN (the global rump — small, pressure-placed per the token spec):**
- persistence triggers + fork points; reshardAutoTune (1Hz control plane); stat folds/INFO cache;
  LRU clock/unixtime single-writer; signals/shutdown; config-apply context.

Result: cron cost mostly vanishes from serving threads not by relocation but by LOCALITY — shard
housekeeping runs on the shard's owner in otherwise-idle slices; client housekeeping on the client's
owner; the token carries only what is genuinely singular. Absorbs tasks RP-2 (#18) and RP-3 (#19).

### Deletion criteria (user): if it doesn't need to exist in Tomo KV, DELETE the task
A duty is deleted (not relocated) when any of:
 (a) its OBJECT doesn't exist here — e.g. every keyspace cron aimed at the DECOY server.db
     (expire/rehash/defrag/eviction sampling of an empty-by-design keyspace);
 (b) its FEATURE is unsupported by design (RP-1 boot-gates it) — replication cron, AOF-rewrite
     scheduling, cluster/failover/ASM ticks, maxmemory eviction hooks: their per-tick checks are
     dead branches burned every cycle;
 (c) its MACHINERY was replaced wholesale — the upstream io-threads apparatus (IOThreadClientsCron,
     pauseIOThread, handoff) which also carries the misleading am-I-main guards the audit flagged.
Candidates pending a support decision (delete OR implement properly, never half-exist):
 slowlog/latency-monitor for worker-executed commands (today they silently see nothing — the audit's
 observability hole); CSC/tracking invalidation broadcast paths.
Note: per-tick dead branches are themselves cron cost — deletion IS the perf fix. Consistent with the
project's measured history: every deletion wave to date was perf-neutral-or-positive and shrank the
audit surface.

### Shard-local rehash (user: yes — each shard rehashes when needed)
Op-driven incremental rehash already works (owner-only, lock-free). The EX-local idle slice adds the
two orphaned triggers: (1) COLD-DICT DRAIN — finish in-progress rehash on idle shards (today a cold
mid-rehash dict holds both tables forever); (2) SHRINK-WHEN-SPARSE — fill < ~10% -> resize (today
nothing ever shrinks a shard dict). Budgeted micro-arch style: steps scale with observed idleness
(adaptive-spin state is the signal), yield instantly on real work — rehash cost MOVES from serving
ops (upstream Redis's latency-spike model) into idle gaps. Caveat: dictPauseRehashing while the
shard is a live v8d migration endpoint (bucket copy iterates the dict).

### Refinement (user): RELOCATE-TO-RECOVER-BENEFIT first; delete only the truly void
The decision test per duty: would moving it (io->ex, main->owner) RECOVER the benefit the original
Redis design intended? If yes — move it; the duty survives, better-placed (e.g. active expiry: the
decoy-pointed instance is void, but the BENEFIT is real and the shard-local version delivers it
lock-free — that is a relocation, not a deletion; same for rehash/shrink, clientsCron, defrag-later).
Only features truly useless/unsupported by design — replication, cluster, failover/ASM, maxmemory
eviction — get deleted, and "at least from the loop": strip their per-tick checks from serverCron/
beforeSleep (the recurring cost); the dormant code may remain compiled for optionality.

### Integration matrix (user): housekeeping x migration x load balancing
| interaction | hazard | rule |
| :-- | :-- | :-- |
| active expire x migration COPYING | A expires a key in a range mid-copy to B -> B resurrects it | expiry deletes in the migrating range MUST emit effect-log tombstones (verify existing lazy-expire delete already routes through effect-capture); else pause expire over that range until DONE |
| rehash x migration endpoint | bucket copy iterates the dict | dictPauseRehashing on the endpoint shard until DONE (already specced) |
| shrink x migration IN | shrink right before buckets arrive -> immediate re-expand | skip shrink while self is a migration dst |
| housekeeping x EX->PARKED | wasted work + park asserts empty | park checkpoint quiesces housekeeping first; no new cycles once target_mode=PARKED |
| housekeeping x pressure signals | idle-slice work masks idleness -> balancer thinks worker is busy | count housekeeping time as IDLE-EQUIVALENT for shift decisions (separate tick counter); serving-busy and housekeeping-busy are different signals |
| expire storms x reshard EWMAs | synchronized mass expiry shifts shard sizes -> spurious migrations | existing significance floor + relative bar + settle window are the guard (verified once under storm test); expiry-driven size change is a REAL signal, just rate-limited |
| reshardAutoTune x mode transitions | migration endpoint mid-transition | already enforced (step 3): live-- precedes deactivation arm; dormant spare never an endpoint; single control-plane writer |
