# AT4.11 — document the existing counter precisely

Chosen option: documentation, with no counter or dispatch-path change. The
counter is an attempt count at atomic_try_admit's Full result. EXEC's earlier
atomic_can_admit refusal, snapshot barriers and script cut admission are outside
it. An EXEC can still increment it if another admission consumes the last
credit between its check and attempt. It is therefore incorrect to say it
never counts EXEC or to interpret it as all throttling.

The public CONFIGURATION.md now states those boundaries. Preserving the
pre-check avoids adding an atomic counter update to every repeated IO poll of
a blocked EXEC. A complete throttling metric would need a defined per-command
or per-attempt policy across all admission points; that is unnecessary to make
the existing metric honest.

Reproduction: PRE ef5204b2e, both modes, atomic 0/1, eight cores 48–55, shards 16,
2s ratio 6:2, 1s read-local 1, databases 16, uring, ports 34810, driver 56–63.
400 connections concurrently issue MULTI/INCR two distinct-owner keys/EXEC,
with DEBUG ATOMIC-COMMIT-DELAY=2000 us. Every leg observes pool=0, inflight=256,
stalls=0 during saturation; final values are exactly 400/400. In the 2s atomic-0
leg the final counter reaches 67, consistent with check/attempt races. The
other final counters stay zero. Full samples: reproductions-pre.json.

Documentation-only disposition; no claim that throttled EXECs now increment.
No gate row added: DQ=0, DF=0. There is no changed runtime reply to oracle-test
and no PRE-failing semantic row to claim for a documentation clarification.
