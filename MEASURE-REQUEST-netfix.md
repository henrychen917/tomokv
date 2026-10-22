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
