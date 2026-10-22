# Network refinement merit request

## netfix

Base: `a7dfb9d2332d4c4e9d8bca983e439ba4b2bbba7e`. Branch `cx-netfix`; no push.
All execution is restricted to CPUs 64–79, builds `-j16`; correctness servers use
64–71, drivers 72–79, shards 16, split ratio 6:2, fused eight threads.
Directed new-row boots use client-lb=0 for stable ownership; every boot command
is retained beside its result. Existing batteries use their own declared knobs.

NT4.6: reproduced in all eight mode/engine/TCP-or-TLS legs. The new
`netfix_query_stats` gate job fails on PRE and passes on POST; both oracle
transports pass. Counts follow 0,1,2,3,0 across three silent limit closes and
RESETSTAT, including queued MULTI bytes. The field is in Stats immediately
before the output-limit counter. epoll deferred closes are counted once.
Evidence: `docs/netfix/evidence/{pre,post}-query/`.

The supplied oracle has no TLS support. The TLS oracle is an unmodified build
of `/home/user/Projects/redis` commit `f103d127b9747965e28f20615ef790332661fc68`,
Redis 7.4.10, `BUILD_TLS=yes MALLOC=jemalloc REDIS_CFLAGS= REDIS_LDFLAGS=`.
Its final binary is `build/redis74-tls-jemalloc-server`; digests are in
`docs/netfix/evidence/oracles.sha256`. TCP uses the supplied Redis 7.4 binary.
An earlier libc TLS build is retained as `build/redis74-tls-server`; final RSS
proofs use jemalloc on both the oracle and candidate, without allocator tuning.

Current row delta: NT4.6 DQ +1 / DF +1, collected before the quick exit.
EXPECT_QUICK / EXPECT_FULL remain unchanged. The complete five-item delta and generic 14-cell request appear below.

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

### Merit request (maintainer only; no rates measured in this lane)

Use the gate's own instrument and the frozen 14 rows in
`docs/netfix/merit-cells.txt`: h01,h02,h15,h16,h17,h18,h31,h32,h33,h34,h47,h48,h63,h64.
Keep the checked-in workload fields, mode, read-local, reorder, depth and atomic
settings exactly; use the owner's scheduled quiet-box geometry. No full iteration,
ABBA, benchmark or measurement load generator was run by this lane.

Arms (absolute worktree root `/home/user/Projects/cx-netfix`):

- PRE: `build/tomokv-pre-netfix`, baseline a7dfb9d23.
- POST: `build/tomokv`.
- PAD-A: `build/tomokv-pad-a-netfix`, **A, behavior twin of periodic reclamation**.
  Exactly six bytes differ from POST: both namespaces' cold `IdleBuffers::visit`
  return false. Section sizes and addresses are identical to POST. The memory
  row must fail on all eight target legs. Compatibility fixes and removal of the
  old request-time sheds are shared with POST; this control isolates the new
  periodic mechanism, not all five compatibility edits or the shed removal.
- PAD-B: `build/tomokv-pad-b-netfix`, **B, inverse control**. Candidate behavior
  plus unreachable NOP padding restores PRE's exact `.text` size. Included because
  the candidate changes text size by much more than a few hundred bytes.

Exact SHA-256s and section sizes: `docs/netfix/binaries.sha256` and
`docs/netfix/binaries.json`. PAD construction and byte receipts:
`tools/netfix_pad.py`, `tools/netfix_pad_b.py`, `docs/netfix/pad-{a,b}.json`.

Run PRE/POST ABBA and POST/PAD-A ABBA, with PRE/PAD-B as the size-control pair,
using the same offered load per paired cell. Use at least three complete ABBA
blocks and the instrument's reference/null checks; preserve all raw trials.
The verdict is matched-load rate for rate cells and the declared latency metric
for latency cells. Report cycles/op, instructions/op and IPC per cell alongside
those verdicts. A gain must survive the controls; any GET/SET/MGET/MSET regression
requires rejection or revision. Purging all arenas on a cold reclamation beat
may affect tail latency during a burst; include the per-cell tail readings and
do not infer its cost from instruction identity. There is no throughput claim here.

### Identity and gate accounting

Strict all-body audit: `docs/netfix/identity/changed-bodies.md` lists every changed
body with its reason; the complete strict diffs are in `changed-bodies.json.gz`.
The stock `reorder_noop.py` and `r7shadow_noop.py --inventory overlapaxe` receipts
are retained too. Identity is a proxy, not a merit verdict. GET/SET command bodies
and the multi-key inventory are unchanged; no per-unit budget edit was needed.

Five literal rows are collected before the quick-tier exit: DQ=+5, DF=+5.
The source inventory and label fixture both contain 707 rows, with no missing or
extra labels (`docs/netfix/evidence/label-inventory.json`). The strict fixture
checker rejects EXPECT_FULL=702 until the maintainer updates the constants to
EXPECT_QUICK=690 and EXPECT_FULL=707. Neither constant was edited.

### Remaining compatibility scope

NT4.7's default cipher acceptance and default session caching are fixed. Its
optional TLS key/password/client-identity/DH/cache controls and live TLS CONFIG
reload remain unimplemented; the row is therefore only partially closed. Runtime
bind/port is a design note for fliplisten, as requested. This lane does not claim
full Redis TLS/configuration parity. Architecture constraints (including IPv4-only
bind and TLS 1.3 RX staying in OpenSSL) remain as recorded by the owner.

Final correctness receipts and any residual failures are listed below after the
frozen-candidate jobs complete. Earlier failed or superseded attempts are kept
as evidence and are not counted as passes.
