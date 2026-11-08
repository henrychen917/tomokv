# IO-loop decisions

These entries preserve rationale and historical observations removed from source comments.
Dates below are the documentation review date; they do not invent dates for the original
experiments. Historical numbers are not new measurements or throughput claims.

## 2026-11-08 — Per-IO listening sockets (`IoLoop::init`)

Use one SO_REUSEPORT listener per IO thread and transfer that listener intact during FLIP.
The previous comment records a shared-listener observation with six IO threads and 577
connections: thread 5 accepted every connection, with about 3.5 ms depth-one latency.
It also records a separate two-process reuseport incident that appeared as missing data.
The lasting requirements are kernel distribution across per-thread listeners and excluding
another server process from the listening port. Successful reuseport bind alone is insufficient.

## 2026-11-08 — Keep `IoLoop` definitions at their tool-owned locations

An interface-first split is not eligible under this lane's combined constraints. The R7
input list in `tests/r7shadow_sync.py`, `tools/source_anchors.json`, lottery hooks, and PAD
builders bind interleaved methods to `src/core/io_loop.h`. Moving the other member bodies
into a header after the class would place them after the retained definitions, changing
translation-unit definition order. Moving every body would break the path constraints.
No class split was attempted or kept; there is no DIFFERENT binary accepted as readability.
The six-file ownership partition also provides no new topic-header destination.

## 2026-11-08 — Shared parser feature gate (`IoLoop::parse_and_dispatch`, `climon_refresh_armed`)

CLIENT/MONITOR/TRACKING arming is folded into the notification decision once per IO
batch. The parser chooses handler specializations before dispatch. Keep per-feature
state outside the fixed Client layout and retain pending MONITOR records through ROB
retirement; the private refresh bit is not part of the published server feature mask.
This preserves the reason for the former “Lane F” comments without claiming a new cost.

## 2026-11-08 — Select transport at role entry (`IoLoop::run_split`, `on_cqe`)

Choose Unix/TLS/epoll template variants at loop entry. The no-TLS completion switch
handles plain transport and shared controls. These are compile-time specialization
contracts, not a promise that epoll never uses the ring abstraction for control traffic.

## 2026-11-08 — A wake implies another drain (`IoLoop::epoll_pass`, `run_loop`)

Count an epoll doorbell as progress even if the preceding mailbox drain found nothing.
The producer can enqueue between the two drains. The removed comment compared the
resulting timeout stall to an earlier roughly 3.9 ms/operation DEFER_TASKRUN observation.
Credit-window waiters likewise announce themselves after arm_blocked and recheck, rather
than relying on a retired credit to appear as ordinary inbound work.

## 2026-11-08 — Allocate the RYOW sidecar on demand (`IoLoop::admit_retained_fd`)

Allocation belongs to the first write after a local read arms the connection, not to
accept. The source recorded 1,216 bytes in a 1,280-byte jemalloc size class for the eager
sidecar. Pure-read and idle connections need no write-ring allocation. Failure at the
lazy allocation site falls back to the unarmed contract instead of rejecting the client.

## 2026-11-08 — Keep the load-balancer control patch site (`IoLoop::lb_parse_paused`)

The ordinary path reads the IO-private pause snapshot. The offline PAD is kind A, a
behaviour twin that redirects the patch site to the comparison gate while preserving
candidate text layout. The metadata belongs to the enclosing COMDAT group so discarded
copies cannot leave orphan sites. This lane neither moves the site nor requests a PAD.

## 2026-11-08 — Retry FLIP preflight within its deadline (`IoLoop::flip_control_pass`)

The source records that a one-shot readiness check refused FLIP under 512-connection,
depth-16 traffic while eight-connection tests passed. Once dispatch is held, readiness
is retried until the FLIP deadline (described there as five seconds). Do not claim the
prepare epoch until preparation runs, or an empty migration list can falsely look like
a changed connection set. Stage acknowledgements must also match the live epoch.

## 2026-11-08 — Abort reversible FLIP for shutdown (`IoLoop::flip_control_pass`)

Save cron serves pending SIGTERM/SIGINT stops but is paused during a live FLIP. A
reversible FLIP therefore enters rollback for a pending stop; after ownership commit
it finishes installation. Serialize the irreversible listener/ownership edge with
close refusal, and preserve the connection-set pin through the relevant stages.

## 2026-11-08 — Keep arming transient distinct (`IoLoop::read_local_write_fallback_reason`)

Writes published before the first local read have no RYOW descriptors. Their one-time
arming fence must be distinguishable from steady-state explicit-key conflicts in the
fallback counters. Repeated transient attribution on an already-armed connection is
an arming diagnostic, not evidence that unrelated writes should obstruct reads.

## 2026-11-08 — Keep constant parser limits (`IoLoop::parse_and_dispatch`)

The removed comment cited an earlier +83 instructions/operation observation when parser
limits were passed dynamically. The common authenticated/default-limit path uses the
constant-folded parser; pre-AUTH and nondefault bulk limits use explicit bounds. No
instruction or rate measurement is repeated or inferred in this lane.

## 2026-11-08 — Fence both sides of second-wave scatter (`IoLoop::parse_and_dispatch`)

EX-generated destination/apply tasks and ordinary IO tasks enter different producer
channels, which drain by producer ID. The source records ZDIFFSTORE returning :1 followed
by ZCARD returning :2, and an older DEL landing after a younger destination store. Wait
for the ROB head before starting these scatters and block younger parsing afterward.
Read-only and single-wave scatters retain their single-IO publication order.

## 2026-11-08 — Publish before dispatch (`IoLoop::parse_and_dispatch`)

The source records three stranded replies in 87 million operations when task posting
preceded ROB publication. A completion could spend its notification before dispatch_
included the operation. The incident involved deleted remote-sender modes; those modes
are not proposed here. The current invariant is independent of them: publish, then post.

## 2026-11-08 — Check direct-reply eligibility once (`IoLoop::parse_and_dispatch`)

Only the first dispatch of a pass can qualify as the empty-buffer ROB head. The removed
comment records a 2–4% depth-32 regression when every operation read the retirement-written
flush_ line for an eligibility check that later operations could not pass. Preserve the
single check; these are historical observations, not a performance verdict for this diff.

## 2026-11-08 — Refused publication preserves input (`IoLoop::parse_and_dispatch`)

On a full owner inbox, undo ROB publication and leave the parse cursor untouched. The
source records a hang within seconds at six IO/two EX when bytes were consumed despite
refusal. Retry reachability must survive queue saturation; no frame may lose its reply.

## 2026-11-08 — Sample fingerprint work (`IoLoop::flip_fingerprint_note`)

The source records 63–86 instructions/operation for walking argv and updating five
counters on every frame. The owner-private sampling word gates that body per parse
pass. With --flip-auto 0 (including 1s boots), the body remains inactive.

## 2026-11-08 — Target serving from completion signals (`IoLoop::collect_retire_work`)

The removed comment records 93% empty serves at eight nodes and 526 million drain checks
when every active connection polled its remote completion line. The ready mask and
claimed-post channel instead enqueue serving for completed-work bursts. Read activity
alone does not require a serving poll on every pass.

## 2026-11-08 — Rearm reads before serving (`IoLoop::flush_ready`)

The source records a 7.5-fold loop-iteration collapse at 2,048 connections, passes walking
about 100 connections, and 113k park/wake round trips versus 22k when receive arming
interleaved with serving. It also compared the then-existing three-stage path (−3.7%)
with a 21% two-stage loss. Those numbers are archived only; the deleted three-stage mode
is not proposed. The live requirement is receive progress before reply backlog work.

## 2026-11-08 — Idempotent, reachable close (`IoLoop::close_client`, `reap_dead`)

The source describes an ASAN double delete when receive and send errors both queued the
same dead client, and a roughly 137 KB/client leak when a quiescence wait lost its active-set
retry. Epoll's owed-edge bit also has to clear on close, including KILL-self after its reply.
Keep dead-state idempotence, retry registration, kernel/ROB/executor fences, and delayed
inbox reclamation together. Pending serving entries can extend grace beyond two prologues.

## 2026-11-08 — Index active-set traversal (`IoLoop::PtrSet`, `flush_ready`)

The source records an ASAN heap-buffer-overflow when a close/retry appended to the vector
under an iterator-based walk. Use indices and recheck the current occupant after callbacks:
append can reallocate, and swap-with-back erase can replace that occupant. This container
borrows clients and is not the authority for deleting them.

## 2026-11-08 — Preserve whole push frames (`IoLoop::pubsub_emit`)

Appending a push to the newest live Op reply could place it between a borrowed bulk header
and body. The send engine's out-of-band frontier and Client::append_oob preserve complete
frame boundaries and live direct-reply regions. Subscriber acknowledgements precede their
deliveries; a parked blocking head is the documented bounded-latency exception.

## 2026-11-08 — Flush deliveries before publisher results (`IoLoop::pubsub_flush_outboxes`)

Deliveries enter the ordered destination inboxes before any publish reply leaves the home.
This preserves order when a publisher waits for each reply across different channel homes.
A pipeline spanning homes has no cross-channel order guarantee; one home orders its channel.
The source described a depth-64 burst coalescing into one event per destination IO.

## 2026-11-08 — Use protocol bounds for publish backlog (`IoLoop::pubsub_start_publish`)

The removed comment describes former caps of ten regular/eleven shard publishes forcing
home round trips and sends about every ten frames. The ROB bounds publisher operations;
client-output-buffer-limit pubsub bounds subscriber output. Drain at the pass boundary
so a pipeline can coalesce without an extra publish cap.

## 2026-11-08 — Count distinct patterns and preserve syntax replies (`IoLoop::pubsub_handle_home_request`, `pubsub_reply_bad_subcommand`)

The source records Redis 7.4 probes establishing distinct-pattern NUMPAT counts (two
subscribers on one pattern count once), and PUBSUB syntax errors echoing the client-spelled
subcommand. Pattern replication lets one home count the distinct set. These are retained
compatibility decisions; this lane does not rerun an external Redis semantic study.

## 2026-11-08 — Separate write precision from descriptor capacity (`IoLoop::parse_and_dispatch`, `read_local_parse.inc`)

The source records 164,000 of 164,000 reads falling back with 59% writes at depth 32 when
full RYOW descriptor capacity forced demotion of every pending read. Eviction policy
establishes the write's key precision; descriptor capacity governs only later-read
tracking. Older reads must be selected by key overlap even when the ring is full.

## 2026-11-08 — Skip empty demotion plans (`ReadLocalDemotionPlan::prepare`, `read_local_parse.inc`)

The point-write gate duplicates the planner's early-exit predicates for that call shape:
no owner reservation and no possibly overlapping pending read means no plan. The source
records −108 instructions/operation and −23 cycles/operation for armed single-thread SET.
Keep the exact pending-filter absence proof; no new optimization or measurement is claimed.

## 2026-11-08 — Validate transient store mutation at execution (`read_local_parse.inc`, `IoLoop::parse_and_dispatch`)

The source describes the table-mutation bit as an approximately 200 ns bracket and records
about 11% unnecessary MGET fallbacks when sampled during parse. The open-group pending-key
filter can remain relevant through execution; transient mutation is checked by the executor's
probe/validation. This does not weaken the executor's read correctness checks.

## 2026-11-08 — Pressure requires a real full-lane observation (`read_local_parse.inc`, `IoLoop::parse_and_dispatch`)

The source records quota deferrals feeding their own pressure window indefinitely: 0.8%
read deferrals versus 0.00008% actual full-lane refusals. Only real full-lane events rearm
the window; the admission actuator cannot sustain its own signal.

## 2026-11-08 — Defer capacity pressure without owner demotion (`read_local_parse.inc`, `IoLoop::parse_and_dispatch`)

The source attributes depth-128/2,048-connection pure-read collapse to demoting full-lane
reads: seven-eighths of those tasks crossed threads and delayed local-lane draining,
feeding further demotion. Keep the current frame unpublished and retry from active_ after
the lane drains. Explicit conflicts continue to use the owner/demotion protocol.

## 2026-11-08 — Diagnose duplicate retirement at insertion (`ReadLocalDeferredQueue::defer`)

The debug check names double retirement before it can insert the same block twice into
an owner cache and create a free-list cycle. The removed P0 wording is incident history;
the lasting invariant is single-owner, exactly-once retirement after unlink and before
grace-delayed reuse. Readers do not retry and writers do not overwrite armed records.

## 2026-11-08 — Preserve cold-tail layout (`IoLoop` state, `ClimonConn`)

Cold caches, notification queues, fused-executor binding, forwarding state, and FLIP pins
keep their positions or use padding so hot member offsets stay fixed. Climon connection
state remains outside the 1,984-byte Client. This lane changes no layout or definition
order and introduces no alternate text/layout arm.
