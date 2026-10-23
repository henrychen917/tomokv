# Empty IO-pass retry signal

The first retry lane implementation increased the empty owner-pass prefix from 19 to 30 instructions and enlarged its stack frame. It failed the stated cost bar.

The revised hook keeps the existing deferred-state reap and cleanup-empty check, plus one load/branch on a dedicated worker TLS signal. The retry and cleanup implementation is noinline; its allocation/posting frame is created only with pending work. The actual MPSC inbox remains in the cold Server tail. Each 64-byte lane uses its former final eight padding bytes for a signal pointer, bound once on worker initialization in main.cc and each fused/read-local boot runner. The signal occupies a complete 64-byte TLS object, so remote producers do not write a line containing unrelated hot TLS data. Both loop headers remain unchanged.

Startup ordering: the producer publishes the inbox link by SC CAS, then SC-loads the signal pointer; the binder SC-stores its pointer, then SC-loads the head. Both cannot miss each other. A late binder signals an already queued startup fence. During draining, the consumer clears the signal before its acquire/release head exchange. A subsequent producer acquires that exchange in the head's RMW order before setting the signal. An earlier node is included in the detached list; a delayed signal for an already drained node causes only an extra empty check. Re-enqueued held attempts raise the signal normally.

Worker initialization binds dormant IOs too, so an exclusive fence can reach an IO that has never executed a transaction. The worker keeps the same TLS storage across FLIP role changes. Shutdown reads only the Server inbox after workers join; it does not dereference expired worker TLS pointers.

The deterministic txn_intents unit covers an inbox queued before binding and a new producer after the reset/exchange. Full retry/fallback and fused/split batteries are required on the resulting binary. Updated disassembly evidence is pending the build.

The first signal build initialized ordinary split workers but missed the independent fused boot runners. Its first fused battery timed out on retrying cases; the run was stopped. Startup binding was then added to genthread.cc, reorder.cc and rl2s.cc, before the IO loops can run. This failure is retained under post-io-signal/.

After binding every boot runner, all eight txniso configurations pass (split/fused × atomic 0/1 × databases 1/16). Binary SHA-256: 2a0eefaafa8eb2ce4e249c0e812140baf77d206f21e0b6b7f89fe8843552d07c. The two extended units pass. The hot hook has 14 instructions through the existing cleanup-empty branch, versus 19 in PRE's helper (plus PRE's wrapper jump); the new notification is one TLS load, test and conditional branch. Its frame reserves 8 bytes rather than PRE's 0x238. Both namespaces have the same instruction sequence. This is an empty-hook result, not a main-command throughput claim.

X1 originally completed one split/database-16 arm without an exclusive witness. The battery now re-arms the exact four-writer/200-EXEC workload on fresh keys at most four times within the original overall 15-second deadline. Exact totals and zero violation/timeout counters are asserted for every arm, and all four misses still fail.
