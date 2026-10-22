# Network refinement merit request

## netfix

Base: `a7dfb9d2332d4c4e9d8bca983e439ba4b2bbba7e`. Branch `cx-netfix`; no push.
All execution is restricted to CPUs 64–79, builds `-j16`; correctness servers use
64–71, drivers 72–79, shards 16, split ratio 6:2, fused eight threads.

NT4.6: reproduced in all eight mode/engine/TCP-or-TLS legs. The new
`netfix_query_stats` gate job fails on PRE and passes on POST; both oracle
transports pass. Counts follow 0,1,2,3,0 across three silent limit closes and
RESETSTAT, including queued MULTI bytes. The field is in Stats immediately
before the output-limit counter. epoll deferred closes are counted once.
Evidence: `docs/netfix/evidence/{pre,post}-query/`.

The supplied oracle has no TLS support. The TLS oracle is an unmodified build
of `/home/user/Projects/redis` commit `f103d127b9747965e28f20615ef790332661fc68`,
Redis 7.4.10, `BUILD_TLS=yes MALLOC=libc REDIS_CFLAGS= REDIS_LDFLAGS=`.
Its binary is `build/redis74-tls-server`; digests are in
`docs/netfix/evidence/oracles.sha256`. TCP uses the supplied Redis 7.4 binary.

Current row delta: NT4.6 DQ +1 / DF +1, collected before the quick exit.
EXPECT_QUICK / EXPECT_FULL remain unchanged. Further item proofs and the
generic 14-cell PRE/POST/PAD-A request will be appended when ready.

NT4.11: both registers and the round-3 owner paper-constraint list contain no
ruling to retain path refusal. PRE refuses regular files, symlinks and live
sockets in all four mode/engine legs; Redis replaces all three. POST matches
Redis and retains the stale-socket, permissions, serve and exit-cleanup checks.
`netfix_unix` fails on PRE and passes on POST; evidence in
`docs/netfix/evidence/{pre,post}-unix/`. Adds DQ +1 / DF +1 before quick exit.

NT4.8: exact oracle error payloads now cover network immutable names (including
original request spelling), integer/memory/bool grammar and ranges, output-limit
parser diagnostics, and duplicate parameters. The directed job runs TCP/TLS in
both modes/engines, fails on PRE and passes on POST. proto-max-bulk-len's
configuration range now matches Redis through LONG_MAX at boot and runtime;
the independent uint32 receive/Slice frame bound remains enforced.
Evidence: `docs/netfix/evidence/{pre,post}-config/`. DQ +1 / DF +1.
Runtime bind/port machinery is deliberately not implemented: the handoff and
rollback requirements are in `docs/netfix/runtime-bind-port.md`.

NT4.7: default cipher acceptance and session caching now match Redis's defaults.
All four mode/engine legs accept the same 23 suites as the TLS oracle with the
RSA test certificate, and TLS 1.2 sessions resume. PRE accepts only two suites.
The entire installed OpenSSL default set is retained, with AES-GCM moved first.
TLS 1.2 AES-128/256-GCM and ChaCha20 offload on this kernel/OpenSSL; CBC falls
back to userspace. TLS 1.3 remains RX-userspace, with eligible TX offload; the
active kTLS gauge measures the two-direction TLS 1.2 engine, not TX-only TLS 1.3.
The default-acceptance proof is not a claim of full TLS configuration parity:
optional key-password/client-identity/DH/cache controls and live TLS reload from
NT4.7(b/c) remain absent. Cluster/replication stay outside the architecture.
Evidence: docs/netfix/evidence/{pre,post}-tls/. DQ +1 / DF +1.

NT4.19: periodic owner cron applies Redis's 4 KiB spare, >2 second idle,
32 KiB active-query threshold, half-capacity peak comparison and five-second
output-peak window. Existing cursors and capacity growth provide conservative
peak samples without request-path peak stores. Input retains the established
16 KiB floor; two 512-byte inline outputs provide the 1 KiB floor. Output shrinking retains max(inline floor, recent peak + 1), including
active clients. Only empty outputs shrink, under ROB/send/TLS-pointer fences. io_uring cancels a pinned
recv and waits for the ORIGINAL recv CQE before moving input. Migration and
close retire owner-local peak records. Freed jemalloc pages are purged on the
cold beat, coalesced across owners, so silent clients do not depend on later
allocation traffic to drive decay. Existing layout locks still compile.

The 10,000-client matrix passed TCP and TLS on both modes and both engines.
Every client stays silent during the idle interval, then must answer PING.
POST resident memory settled 9–12 MiB above the warmed baseline, after peaks
of roughly 2–3 GiB; PRE retains burst input on all eight legs. The oracle also
passes. The RSS bound is baseline + max(32 MiB, 5%); the test performs no
MEMORY PURGE and changes no allocator settings. Additional stream-preservation
and PAD-A negative-control runs are recorded separately below when complete.
Evidence: docs/netfix/evidence/{pre,post}-idle/. DQ +1 / DF +1.

All five rows are collected at tests/gate.sh's netcap block, before the quick
exit: total DQ +5 / DF +5. Proposed EXPECT_QUICK=690, EXPECT_FULL=707.
Neither constant was edited.
