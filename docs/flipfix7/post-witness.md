# Final connection liveness witnesses

POST SHA-256: d443b95831da51c41d8095a529d4e1d3db8ec3fd7dd802c1a3ef34926c47fd21.
Gate run FMZMQT: release and three live rows, 4 passed / 0 failed.
Thirteen episodes per leg, 208 total, with fresh 6:2 / 16-shard boots.
The original signal-stop campaign was expanded to single SIGINT as well as SIGTERM.

All non-signal PINGs returned exact PONG. All late windows acknowledged the initial
drain without an output skip and then observed owned output. The moving-output
case requires an actual transferred-output counter. Every non-draining output
case reads and verifies every notification or every borrowed byte after FLIP.
Both borrow cases require BORROWCOUNT > 0 before FLIP and zero after release;
read-local legs use WATCH to force the existing owner fallback, then UNWATCH.

Durations below are correctness stall observations in milliseconds, not rates.

| Engine | RL | Atomic | DBs | Late FLIP | Moving-output FLIP | BLPOP refusal | TLS refusal | Worst PING | SIGTERM / SIGINT recovered |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| uring | 0 | 0 | 1 | 22.267 | 20.666 | 0.026 | 0.029 | 25.230 | 1000 / 1000 |
| uring | 0 | 0 | 16 | 27.108 | 24.063 | 0.026 | 0.027 | 27.044 | 1000 / 1000 |
| uring | 0 | 1 | 1 | 20.457 | 27.724 | 17.101 | 13.940 | 27.686 | 1000 / 1000 |
| uring | 0 | 1 | 16 | 28.711 | 24.597 | 0.026 | 0.026 | 28.675 | 1000 / 1000 |
| uring | 1 | 0 | 1 | 27.290 | 28.424 | 0.027 | 0.026 | 28.377 | 1000 / 1000 |
| uring | 1 | 0 | 16 | 28.749 | 24.726 | 0.024 | 0.026 | 28.642 | 1000 / 1000 |
| uring | 1 | 1 | 1 | 22.826 | 24.812 | 14.014 | 0.025 | 24.741 | 1000 / 1000 |
| uring | 1 | 1 | 16 | 24.263 | 22.737 | 0.024 | 0.027 | 41.183 | 1000 / 1000 |
| epoll | 0 | 0 | 1 | 39.033 | 35.518 | 0.023 | 0.024 | 38.935 | 1000 / 1000 |
| epoll | 0 | 0 | 16 | 27.749 | 26.472 | 0.024 | 0.023 | 27.717 | 1000 / 1000 |
| epoll | 0 | 1 | 1 | 24.233 | 25.597 | 0.023 | 0.024 | 25.558 | 1000 / 1000 |
| epoll | 0 | 1 | 16 | 28.142 | 51.849 | 0.023 | 0.024 | 51.799 | 1000 / 1000 |
| epoll | 1 | 0 | 1 | 34.601 | 41.104 | 0.025 | 0.025 | 41.057 | 1000 / 1000 |
| epoll | 1 | 0 | 16 | 27.581 | 27.182 | 0.024 | 0.024 | 27.529 | 1000 / 1000 |
| epoll | 1 | 1 | 1 | 53.327 | 26.132 | 0.023 | 0.023 | 53.270 | 1000 / 1000 |
| epoll | 1 | 1 | 16 | 38.140 | 37.499 | 0.024 | 0.024 | 38.106 | 1000 / 1000 |

Every blocked/TLS/output conversion refusal is issued from the production IoDrain
call site with its exact class-specific error; its client retains the original IO.
Surviving-source cases complete and retain the connection. Late BLMOVE wake-up
publication, exact borrow routing, held-send rollback and coordinator-deferred
frames additionally have deterministic core-fixture assertions under ASAN/UBSAN
and TSAN. No socket-output drain condition is waived for a moving kernel pointer.

Signal arming observes FLIP moving immediately before sending the signal. A missed
window reboots and retries, bounded. Successful save/restart after these repaired
episodes does not prove a universal shutdown deadline for an independently stuck
FLIP install; see [shutdown-stop.md](shutdown-stop.md).

[Raw episode summaries](post-summary.json) and
[gate ledger](gate-new-uring-delivery.ledger) retain all counters and replies.

The readiness-cut fixture additionally passed under both sanitizer configurations; see [readiness-cut.md](readiness-cut.md).
