# IO-owned RESP2 pub/sub

## Architecture

- `hash(channel) % n_io` selects the channel home from the placement's IO-thread list. The home
  IO exclusively owns the regular and shard-channel `subscriber -> (owning IO, connection id)`
  indexes. The two indexes are separate namespaces.
- SUBSCRIBE/UNSUBSCRIBE requests are IO-to-IO events. Pattern subscriptions are replicated into a
  per-home pattern list, so a PUBLISH still visits only the channel home and matches that home's
  patterns with the existing Redis-compatible glob matcher.
- PUBLISH runs at the channel home. It makes an owned event copy for each exact or pattern delivery
  and routes it to the connection's owning IO. The owning IO alone appends RESP2 `message` or
  `pmessage` frames to the connection send path.
- SPUBLISH uses the same channel-home routing and delivery path, but consults only the shard index,
  never the regular exact or pattern indexes, and emits RESP2 `smessage` frames. SSUBSCRIBE accepts
  channels on multiple homes in one command. Deliberately, this is a no-slot superset of Redis:
  there is no hash-slot validation, key-slot routing, or CROSSSLOT failure.
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
- `pubsubshard_channels`: shard channels with at least one subscriber
- `pubsubshard_subscriptions`: logical shard subscription count
- `pubsub_home_entries`: physical exact plus replicated-pattern home entries
- `pubsub_inflight`: heap-owned IO event count
- `pubsub_pending_commands`: async command count

All eight return to zero after the directed churn test. CLIENT INFO/LIST reports `ssub=N` from
out-of-line client metadata, preserving the locked Client footprint. Regular acknowledgement
counts remain `channels + patterns`; shard acknowledgements count only shard channels. Their total
controls entry to and exit from subscriber mode.

## Surface and tests

Implemented commands include SSUBSCRIBE, SUNSUBSCRIBE, SPUBLISH, PUBSUB SHARDCHANNELS, and PUBSUB
SHARDNUMSUB alongside the regular pub/sub surface. PUBSUB HELP advertises both shard introspection
arms; there is intentionally no SHARDNUMPAT. RESP2 subscriber mode permits the Redis command set:
all six subscription controls, PING, QUIT, and RESET. PING uses subscribed-mode array framing;
RESET unregisters every exact, pattern, and shard arm before leaving subscribed mode.

The owner-only transaction engine cannot execute the asynchronous home protocol as an EXEC child,
so all six subscription controls are rejected in MULTI. This matches Redis for the two shard
controls and is an explicit compatibility divergence for the four regular controls.

Run the directed test against an already-running server:

```sh
taskset -c 252-255 tests/pubsub.py 127.0.0.1 7954
```

It covers regular and shard 24-subscriber ordered fanout, namespace isolation, exact and multiple
pattern delivery arms, subscriber-mode restrictions, RESET, named/all unsubscribe variants,
CHANNELS/NUMSUB/NUMPAT, SHARDCHANNELS/SHARDNUMSUB, multi-home shard subscriptions, and 320 abrupt
shard subscribe/disconnect cycles concurrent with 500 shard publishes. It waits for every pub/sub
lifecycle gauge to drain to zero.

Validation completed on the assigned partition:

```text
release build                         pass
sizeof(Op) / sizeof(Client)           336 / 1984 bytes
ASAN directed pub/sub test            pass
tests/pubsub.py, atomic=0 and 1        pass
multi/blocking/pubsub/lua, atomic=0/1 pass
spubsub Redis 7.4.2 differential      816 checks, 0 diffs
SET loopback instructions/op          5172.224453 -> 5161.844956 (-10.379497)
GATE_PORT=7954 GATE_CORES=252-255 tests/gate.sh quick (2:2 topology)
                                      17 ok, 0 FAIL
```
