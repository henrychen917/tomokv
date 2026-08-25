# IO-owned RESP2 pub/sub

## Architecture

- `hash(channel) % n_io` selects the channel home from the placement's IO-thread list. The home
  IO exclusively owns that channel's `subscriber -> (owning IO, connection id)` index.
- SUBSCRIBE/UNSUBSCRIBE requests are IO-to-IO events. Pattern subscriptions are replicated into a
  per-home pattern list, so a PUBLISH still visits only the channel home and matches that home's
  patterns with the existing Redis-compatible glob matcher.
- PUBLISH runs at the channel home. It makes an owned event copy for each exact or pattern delivery
  and routes it to the connection's owning IO. The owning IO alone appends RESP2 `message` or
  `pmessage` frames to the connection send path.
- The payload inbox is cold until pub/sub is used. One `nullptr` token in the existing `client_in`
  IO-to-IO channel wakes and drains a whole inbox burst, retaining the established notify-mask and
  park/wake protocol. No pub/sub queue or index is scanned by the plain IO loop.
- Async command replies keep their ROB slot live until every required home answers. This closes the
  acknowledgement race: after a SUBSCRIBE acknowledgement is observable, every home required for
  that subscription has installed it. The connection's existing scatter barrier prevents younger
  pipelined commands from crossing the async pub/sub command.
- Spontaneous deliveries name connections by owning IO plus process-unique connection id, never by
  a cross-thread `Client*`. The owner either appends them behind the newest local reply or defers
  them into the pending subscription command, preserving RESP wire order.

The owner rule remains literal: "db shards need to only be touched by their ex threads." Pub/sub
does not route through, read, or mutate a shard. `sizeof(Op)==336` and `sizeof(Client)==1984` remain
compile-time locks; the subscriber-mode bit consumes existing `Client` alignment padding.

## Lifecycle and reporting

Disconnect sends an idempotent cleanup request to every home IO. The owning IO keeps the client
alive until all cleanup acknowledgements return, then releases the connection through the existing
ROB/kernel-reference fence. This also covers disconnects while SUBSCRIBE or PUBLISH is in flight.

`INFO STATS` exposes the churn invariants:

- `pubsub_channels`: exact channels with at least one subscriber
- `pubsub_subscriptions`: logical exact subscription count
- `pubsub_patterns`: logical pattern subscription count
- `pubsub_home_entries`: physical exact plus replicated-pattern home entries
- `pubsub_inflight`: heap-owned IO event count
- `pubsub_pending_commands`: async command count

All six return to zero after the directed churn test.

## Surface and tests

Implemented commands are SUBSCRIBE, UNSUBSCRIBE, PSUBSCRIBE, PUNSUBSCRIBE, PUBLISH, PUBSUB
CHANNELS, PUBSUB NUMSUB, and PUBSUB NUMPAT. RESP2 subscriber mode permits only the Redis command
set: subscription controls, PING, QUIT, and RESET. PING uses subscribed-mode array framing; RESET
unregisters every exact and pattern arm before leaving subscribed mode.

Run the directed test against an already-running server:

```sh
taskset -c 232-239 tests/pubsub.py 127.0.0.1 7952
```

It covers 24-subscriber ordered fanout, exact and multiple pattern delivery arms, command
restrictions, RESET, named/all unsubscribe variants, CHANNELS/NUMSUB/NUMPAT, and 320 abrupt
subscribe/disconnect cycles concurrent with 500 publishes. It waits for every pub/sub lifecycle
gauge to drain to zero.

Validation completed on the assigned partition:

```text
release build                         pass
ASAN/UBSAN directed pub/sub test      pass
tests/pubsub.py                       pass
GATE_PORT=7952 GATE_CORES=232-239 tests/gate.sh quick
                                      17 ok, 0 FAIL
```
