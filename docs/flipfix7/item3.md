# Item 3: retain or refuse unmovable clients

IoDrain refuses a converting source immediately for a blocked connection, TLS connection or pending output on a socket with no POLLOUT capacity. Surviving IOs retain those clients; ClientPrepare removes their planned transfers using the existing quota-conservation adjustment. Six INFO counters distinguish skips and refusals. No blocked or TLS client migrates.

A parked blocking registry follows its shard. A wake-up after an IO acknowledgement can leave a MoveRequested continuation on that same IO, but the continuation cannot publish executor tasks until Idle. A send completion on a retained borrowed-output client uses the existing indirect WB release callback to retain the release until every executor has acknowledged ExInstall. It resumes before the existing listener-admission acknowledgement, without changing masks or listener handover. Rollback restores the callback against the original ownership map; final shutdown releases retained borrows after joins.

Fresh release smoke: 18 episodes (both engines, atomic0/db16/read-local0) cover BLPOP refusal/retention, BLMOVE retention/wake, TLS refusal/retention, owned output refusal/retention and 8 MiB GET output refusal/retention. All pass, all exact payloads/replies survive, and the maximum unrelated PING is below 23 ms. This is a correctness bound, not a throughput result. The final gate proof extends these to every requested leg.

The core fixture arms actual BLMOVE registration, a post-ack wake, zero publication while frozen, then exact completion after Idle; it also checks deferred borrow release routing after a shard move.
