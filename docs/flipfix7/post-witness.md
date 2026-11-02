# Final connection liveness witnesses

POST SHA-256: 603b92f52daca1cc71dac2bd1815846be13ebb810f275c1e4110f0d23579e8bf.
Gate run DlCRxK: release and three live rows, 4 passed / 0 failed.
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
| uring | 0 | 0 | 1 | 23.644 | 26.124 | 0.093 | 0.836 | 26.080 | 1000 / 1000 |
| uring | 0 | 0 | 16 | 38.343 | 22.095 | 0.423 | 0.845 | 38.307 | 1000 / 1000 |
| uring | 0 | 1 | 1 | 27.386 | 22.559 | 20.817 | 17.901 | 27.293 | 1000 / 1000 |
| uring | 0 | 1 | 16 | 71.948 | 63.748 | 0.296 | 0.159 | 71.815 | 1000 / 1000 |
| uring | 1 | 0 | 1 | 26.926 | 23.989 | 0.363 | 0.827 | 26.868 | 1000 / 1000 |
| uring | 1 | 0 | 16 | 30.399 | 82.468 | 0.169 | 0.250 | 82.437 | 1000 / 1000 |
| uring | 1 | 1 | 1 | 28.199 | 27.867 | 2.319 | 0.131 | 28.180 | 1000 / 1000 |
| uring | 1 | 1 | 16 | 59.481 | 59.284 | 0.146 | 0.199 | 59.442 | 1000 / 1000 |
| epoll | 0 | 0 | 1 | 64.581 | 25.280 | 1.618 | 0.600 | 64.465 | 1000 / 1000 |
| epoll | 0 | 0 | 16 | 55.133 | 82.161 | 0.595 | 0.117 | 82.116 | 1000 / 1000 |
| epoll | 0 | 1 | 1 | 27.277 | 25.830 | 0.199 | 0.433 | 27.229 | 1000 / 1000 |
| epoll | 0 | 1 | 16 | 68.583 | 33.226 | 0.510 | 8.243 | 68.520 | 1000 / 1000 |
| epoll | 1 | 0 | 1 | 43.229 | 24.970 | 0.214 | 0.100 | 43.107 | 1000 / 1000 |
| epoll | 1 | 0 | 16 | 63.186 | 60.002 | 0.125 | 0.027 | 63.149 | 1000 / 1000 |
| epoll | 1 | 1 | 1 | 25.711 | 25.965 | 0.113 | 1.789 | 46.034 | 1000 / 1000 |
| epoll | 1 | 1 | 16 | 60.056 | 81.354 | 0.401 | 1.961 | 81.331 | 1000 / 1000 |

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
[gate ledger](gate-new-final.ledger) retain all counters and replies.
