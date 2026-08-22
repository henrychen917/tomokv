# Retired write-back designs

TomoKV now has one live request/reply pipeline: `IO -> EX -> IO`. The executor write-back and
dedicated write-back-stage implementations are retained in the source only as readable `#if 0`
references for a ground-up replacement. Their selectors and runtime state are intentionally gone.

## Executor write-back (ex-wb)

Ex-wb let the EX worker that completed an ordered command claim the real connection and send its
own contiguous ready prefix. The reference includes the connection claim, prefix gather, partial
write cursor, IO fallback, and terminal cross-shard gather path.

It lost best-versus-best throughput by 10.5–22.2% on loopback on both transports, including after a
fire-and-forget submit ring removed syscall batching as an explanation. On 25GbE the deficit narrowed
to 0.8–6.4%. The measured p1 throughput for both designs was flat at approximately
`threads issuing sends * 90k`: the two-stage design gets send width from IO threads that both receive
and send, while ex-wb must purchase receive width and send width in separate stages from one fixed
thread budget.

## Dedicated write-back stage (3s/WB)

The three-stage design assigned each connection a sticky WB owner:

1. IO accepted, received, parsed, and dispatched.
2. EX executed and built replies.
3. WB consumed ordered completions, advanced post-EX cross-shard work, and performed socket writes.

Decoupling did not improve the clean throughput path. Its only win was backpressure tail latency
(p99 improved 13%). On the 25GbE NIC it crashed with `server.c:32318 'before > 0'`, SIGILL, in
several threads at once. `tomoWbLockClient` and `tomoWbUnlockClient` independently re-derived
`wc = clientTail(c)->wb`; if that pointer changed from NULL to non-NULL between the calls, unlock
decremented a counter that lock had never incremented and unlocked a mutex it had never acquired.
The defect did not reproduce on loopback at matched conditions, making it a NIC-only defect class.

The disabled reference preserves the sticky owner, fenced head-ready bitmap, ordered drain,
cross-shard continuation, lifetime protocol, and optional SENDMSG ring. It must not be interpreted
as a supported mode or re-enabled piecemeal.

## Source locations

- `src/server.c`: disabled ex-wb and three-stage coordination, scheduling, and topology bodies.
- `src/networking.c`: disabled WB client ownership, input, reply, and lifetime bodies.
- `src/wb_uring.c` and `src/wb_uring.h`: disabled WB sender-ring implementation.

The former WB=0 parity suite was removed from preflight because there is no longer a selectable WB
mode: its comparison premise cannot fail meaningfully once the former WB=0 path is the sole path.
