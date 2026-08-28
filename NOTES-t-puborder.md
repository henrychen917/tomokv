# t-puborder notes

Static analysis only. Per `LANE_RULES.md`, this lane never builds, starts the server, or runs a
test/load generator. Baseline: `23364e8b1` (`t-puborder`, clean worktree).

## Premise and root cause

The premise is true. `Client::append_oob` currently sends every frame produced while the ROB is
busy through `segments_` (`src/net/conn.h`, OOB section). That is a safe frame boundary, but the
segment queue is the wire source ahead of replies which have not retired yet. An `SSUBSCRIBE` can
therefore finish its async pub/sub control, erase `pubsub_pending_`, and leave its acknowledgement
`Done` but unretired in the ROB. A delivery arriving in that window misses
`PubSubPending::deferred`, takes the segment route, and is written before the earlier-issued ack.

This is distinct from the P0 fixed by `953ca0774`: no out-of-band bytes may return to `Op::reply`.
A borrowed GET stages `[bulk header][borrowed value][CRLF]`; inserting in `op.reply` puts a push
after the header but before the body. Worker-side `op.reply.clear()` sites can also destroy such a
push, and `blocking_retire` uses reply emptiness to decide whether to synthesize its timeout or
UNBLOCKED reply.

## Chosen ordering model

An OOB frame records the connection's `rob.dispatch_id()` when it is produced. That exclusive
frontier names every command issued before the frame. The write-back engine may append the frame
only after retirement has completely staged replies through that frontier, and before staging a
younger reply. Multiple connections and multiple frontiers require per-connection queues; the
existing one-string drain buffer cannot safely represent them once deferral extends outside the
one currently draining connection.

The latency bound is explicit: when a connection is marked blocked and its ROB head is still
`Issued`, the frame takes `Client::append_oob` immediately. A blocking command is a whole-connection
barrier, so that head is the only outstanding command and no partial reply bytes exist yet. Once
the head is `Done`, it is an in-flight reply rather than a parked wait, so ordinary frontier
deferral applies. A frame raised from inside the same connection's retire drain always defers,
regardless of `blocked()`, because that is the partial-staging window.

## Measurement surface

Reachable commands/features: pub/sub deliveries and subscription acknowledgements, client-tracking
invalidations, MONITOR feed, blocking commands on RESP3 subscribed clients, and replies sharing
those connections. Ordinary GET, SET, MGET, and MSET connections do not call an OOB producer;
their only source-level exposure is the existing predicted-empty deferred check in write-back.

Owner validation should retain the zero-regression GET/SET/MGET/MSET p1+p32 cells, plus pub/sub
delivery throughput and tracking/MONITOR under pipelining. Correctness geometry and exact static
line references will be completed after the narrow code change.
