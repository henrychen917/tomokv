# Thread modes and overlap schedules

`--thread-mode 2s|1s` and `--overlap 0|1|2` select TomoKV's thread architecture and fixed
amortization schedule at boot. The defaults are `2s` and `0`, so an existing command line or
configuration keeps the ordinary separated-loop behavior. `split` and `fused` remain accepted as
aliases for `2s` and `1s`; the new names are the values reported by `INFO Server` and immutable
`CONFIG GET` entries. `CONFIG GET overlap` is canonical. For one compatibility release,
`INFO Server` also emits the old `thread_pipeline` field beside `overlap`.

`--read-local 0|1` is also boot-only and defaults to `0`. A value of `1` arms the local read lane
described below only for `1s` overlap 0. Every other legal mode/overlap cell accepts the setting but
keeps reads on the ordinary owner-task path and logs one notice at boot. The setting is exposed by
`CONFIG GET` and refused by `CONFIG SET`.

`--read-local-interleave 0|1` is the boot-only internal scheduling selector for that armed cell and
defaults to `1`. It serves bounded local-read chunks before and between owner-task chunks. Each
captured owner producer gets one bounded quantum per rotation and is re-notified if work remains,
so no producer can be stranded behind the local lane and queued depth cannot stretch the rotation
without bound. `0` retains the original single positional local drain for A/B. The selector is
inert when read-local is not active, is exposed by `CONFIG GET`, and is refused by `CONFIG SET`.
Snapshot, placement, and pre-existing retry/deferred turns retain the legacy total ordering.

`--read-local-prefetch-capture 0|1` is the boot-only A/B selector for an armed lane and defaults to
`1`. At `1`, a prefetch walk captures the exact slot and immutable object it found and execute serves
that object without reloading the slot. At `0`, the legacy path only hints the table home slots and
performs a fresh lookup at execute. The selector is accepted but inert when read-local is inactive.

`--read-local-atomic-filter 0|1` is the boot-only pending-atomic selector and defaults to `1`. At
`1`, each shard publishes a fail-closed 4096-cell counting-fingerprint filter: a read falls back only
when its key might belong to an unsafe atomic group. At `0`, any pending atomic work retains the old
whole-shard refusal for A/B. The selector is accepted but inert when read-local is inactive, is
exposed by `CONFIG GET`, and is refused by `CONFIG SET`.

| mode | overlap 0 | overlap 1 | overlap 2 |
| --- | --- | --- | --- |
| `2s` | ordinary separated IO/executor loops | `t-iopipe` interwoven WB/IFID schedule | rejected |
| `1s` | coarse generalized-thread rotation | `t-genthread` `iofused` schedule | gated `iofused` three-way schedule |

Overlap 2 prints a boot warning identifying it as an experimental research schedule. Unified
overlap 1 and 2 require `--net-io uring` because their measured schedules share a single explicit
submission boundary. The shipped `--thread-pipeline` spelling remains a numeric alias for
`--overlap`. The compatibility knob `--genthread-schedule` accepts only `coarse`, `iofused`, or
`streams` and selects the corresponding `1s` overlap value. `streams` is now only the legacy name
for overlap 2; it does not select the retained streams implementation.

## 2s: separated threads

Mode `2s` assigns each physical thread one live role. IO (`ifid`) threads receive, parse, route,
retire, and send; executor (`ex`) threads own shards and execute commands. With no placement knob,
TomoKV makes the same even IO/ex split across the allowed CPUs as before.

Overlap 0 is the unchanged plain-loop baseline. Overlap 1 is the exact measured `t-iopipe`
schedule: it interweaves bounded WB and IFID batches inside each IO thread while retaining separate
executor threads. Its shallow order, depth-selected natural order, prefetch walks, and submission
boundary are fixed rather than tunable. Overlap 2 is rejected because the three-way schedule
requires unified ownership.

Use `2s` when you need `--ratio`, explicit IO/ex role placement, manual `FLIP`, or the automatic
flip controller. It also remains the conservative choice outside the unified architecture bench's
tested core-count and overlap regimes.

## 1s: unified generalized threads

Mode `1s` gives every selected physical thread both an IO loop object and an executor loop object.
Overlap 0 rotates three coarse streams in this order:

1. maintain connections and parse/route at most 32 operations per connection pass;
2. consume an executor batch of at most 32 operations;
3. collect completions and serve at most 16 connections.

With `--read-local 0`, local commands take the same self SPSC task lane as remote commands and are
consumed during the executor phase; they are not executed inline. With `--read-local 1`, eligible
plain GETs and MGETs instead enter a parsing-thread-local queue. With the default interleave
selector, the overlap-0 executor phase drains one bounded chunk immediately after parsing and more
bounded chunks between owner-task chunks. The selector's `0` control retains the original single
drain slot. In both cases replies still retire through one connection ROB slot and the normal
write-back path. Parsing never waits for that local queue to retire: a later hash-precise write
first moves the unresolved reads in its transitive key-overlap component to ordinary owner queues,
then publishes behind them; a conservative write moves the whole unresolved set. An unfinished
precise owner-path operation fences only younger reads whose key hashes overlap, so unrelated reads
may still execute locally while the ROB retires every reply in connection order. A broad owner
route remains a conservative fence and is reported separately as route context. MGET applies the
write-ring and store-publication gates to every key/touched shard and is all-or-nothing: any failure
lowers the whole command through the existing scatter path.

Reads with an outstanding conflicting connection write (or a conservatively overflowed write
ring), WATCH or MULTI state, script/scatter context, an unsafe-key filter hit, a typed or expiry-due
value, table-generation churn, or a full local lane fall back to the ordinary owner path. Pending
atomic work on another key in the same shard no longer refuses the read. A filter fingerprint
collision may conservatively refuse an unrelated key; saturation, bookkeeping overflow, or an
unenumerable write set fail the complete shard closed. Filter references remain published through
abort restoration or committed cleanup, not merely until the group decision. A single GET also
falls back on missing so its owner can perform lazy-expiry side effects. MGET applies the filter to
every key and falls back as one command on any positive; it serves a stable missing key as a nil
array element. An expiry-due entry and an armed key-miss notification still fall back.

A local MGET validates its command-wide window with two rules chosen per touched shard from the
table word it already loads. A shard with no open group must keep an even, equal table generation
(advanced by every group install, topology move, ownership handoff, and bulk clear, never by a plain
immutable SET). A shard with an open group is validated per queried key by the touch epoch of that
key's filter cell, a monotonic counter the owner advances after every add, close, poison, or rebuild
of that cell; unrelated group installs on the same shard do not move it, and a cell that went
0 -> 1 -> 0 inside the window still reads +2. The reader loads epochs only for keys on a pending
shard, copies all values into a private reply, then re-reads the same words. Any change retries the
complete command once; a second failure falls back through the existing owner/scatter path. FLUSH
clears poison the filter for their duration so every epoch moves. One-key GET needs no shard sweep:
its filter check stays inside the existing before/after point-probe sequence validation. Plain
writes publish nothing beyond their slot store when read-local is armed.

With prefetch capture enabled, a point-only batch first hints all home words, then performs complete
key-verified probes in program order. Each probe retains the observed slot address and decoded
immutable `KvObj` pointer on the stack, and execute copies directly from that object. Mixed GET/MGET
batches capture and consume one command at a time to preserve connection order; MGET handles any key
count in bounded prefetch, capture, and execute windows and recaptures all windows on its one retry.
Every later drain pass captures afresh, and all captures are consumed before the rotation publishes
its next QSBR tick. GET misses still demote and MGET misses still emit nil.

`read_local_fallback_context` remains the compatibility aggregate. INFO also reports its exhaustive
`_owner_key`, `_connection_state`, `_route`, and `_keymiss_notify` sub-reasons (and matching MGET
rows): precise owner-key overlap, blocked/subscriber state, special or broad routing, and the MGET
key-miss notification gate, respectively. The `foreign_read_*` gauges expose current unsafe
references, occupied/wildcard/saturated cells, and poisoned shards. MGET separately reports local
hits, generation retries, and pending-filter or generation fallback counts.

Overlap 1 selects the fork's exact `iofused` schedule, which overlaps its WB dependency stream and
network work around a 128-operation coarse executor turn. Overlap 2 reuses the same ready lists,
fixed private task lanes, whole batches, and SEND-sensitive outer submission boundary. On a deep
pass it freezes and prefetches the ready WB batch, runs the targeted IFID batch, then gathers,
schedules, and prefetches one whole EX batch. The existing WB prepare/pump work fills that EX load
gap; the prefetched EX batch executes afterward, followed by ordinary whole EX batches. No kernel
submit/reap occurs inside the gap. A single gate bit, recomputed from work actually completed in the
pass, returns the next rotation to coarse IFID → EX → WB after thin work. There is no residual
carry, unpublished IFID state, reservation credit, or delayed EX retirement in this path. The old
streams loop remains in source for branch comparison but is unreachable from overlap-2 dispatch.

Read-local is not woven into either interwoven schedule in this version, so enabling its knob there
retains the task path. Overlap 2 is exposed for research rather than as a production recommendation.

With no `--place`, `1s` uses every CPU in the process affinity mask. `--place` can select a subset;
its `ifid@CPU` and `ex@CPU` labels are treated only as CPU selectors because every selected thread
has both responsibilities. `--ratio` is rejected because there are no separate role counts.
`--flip-auto` is also rejected, the flip controller does not start, and `FLIP` returns a clear
mode-unavailable error. Existing key load-balancing bucket movers remain available.

## Choosing a cell

The architecture bench found unified mode strongest through 16 cores: it led tuned separated mode
by 9–21% at 8 cores, and at 16 cores with a client request-pipeline depth of 128 it led by 2.4% for
GET and 10% for SET. Those results should not be extrapolated to larger core counts or different
workloads without a separate measurement.

Use overlap 0 when the purpose is ordinary operation or a study baseline. Overlaps 1 and 2 are
fixed measurement cells: select them only when the schedule itself is the variable under study.
Choose `2s` when runtime role reshaping or ratio tuning matters, or when deploying beyond the
measured unified envelope.
