| Workload | **tomo-2s** | rank | redis | valkey | dragonfly | garnet |
|---|---|---|---|---|---|---|
| #1 GET-only, P1 (CDN/read cache) | **0.83** (io6ex2) | 1 ⭐ | 0.79 | 0.80 | 0.80 | 0.66 |
| #2 95/5, P1 (web/API cache) | **0.83** (io6ex2) | 1 ⭐ | 0.79 | 0.81 | 0.80 | 0.68 |
| #3 90/10 256B P8 (general) | **3.18** (io4ex4) | 2 ⭐ | 3.15 | 2.84 | 0.87 | 3.93 |
| #4 80/20 512B P8 (sessions) | **2.89** (io4ex4) | 3 | 2.94 | 2.71 | 0.91 | 3.77 |
| #5 50/50 P8 (game state) | **3.35** (io5ex3) | 2 ⭐ | 2.64 | 2.45 | 1.31 | 3.80 |
| #6 20/80 P4 (logging) | **1.82** (io4ex4) | 4 | 2.19 | 1.88 | 1.37 | 2.29 |
| #7 100% SET P4 (bulk load) | **2.17** (io5ex3) | 3 | 2.27 | 1.84 | 1.98 | 2.23 |
| #8 GET/SET/EXPIRE P4 (TTL/OAuth) | **1.90** (io4ex4) | 4 | 2.24 | 2.10 | 0.89 | 2.26 |
| #9 90/10 32B **64M keys** | **3.51** (io4ex4) | 1 ⭐ | 2.90 | 2.66 | 2.98 | n/a |
| #10 90/10 128B (DNS/HTTP) | **3.18** (io4ex4) | 2 ⭐ | 3.09 | 2.86 | 2.83 | 4.04 |
| #11 90/10 256B (app cache) | **3.71** (io5ex3) | 2 ⭐ | 3.12 | 2.92 | 0.87 | 3.91 |
| #12 90/10 1KB (JSON docs) | **0.82** (io4ex4) | 4 | 1.31 | 1.37 | 0.79 | 1.37 |
| #13 90/10 4KB (ML features) | **0.59** (io6ex2) | 5 | 0.61 | 0.67 | 0.61 | 0.68 |
| #14 hotspot uniform | **3.18** (io4ex4) | 3 | 3.21 | 2.91 | 0.83 | 4.00 |
| #15 hotspot Gaussian-light | **3.16** (io4ex4) | 3 | 3.23 | 2.92 | 0.83 | 3.94 |
| #16 hotspot Gaussian-med | **3.17** (io4ex4) | 2 ⭐ | 3.15 | 2.96 | 0.83 | 3.89 |
| #17 hotspot Gaussian-heavy | **3.75** (io5ex3) | 2 ⭐ | 3.22 | 2.93 | 0.83 | 3.93 |
| #18 HASH (accounts/carts) | **1.88** (io4ex4) | 2 | 1.89 | 1.70 | 1.87 | n/a |
| #19 LIST (job queues) | **1.95** (io4ex4) | 2 | 1.72 | 1.70 | 1.98 | n/a |
| #20 ZSET (leaderboards) | **1.91** (io4ex4) | 3 | 2.09 | 1.82 | 2.07 | n/a |
| #21 COUNTER (rate-limit) | **0.59** (io4ex4) | 5 | 0.78 | 0.80 | 0.79 | 0.66 |
| #22 STREAM (event/IoT) | **0.87** (io4ex4) | 2 | 0.49 | 0.52 | 1.11 | n/a |
| #23 MGET k=8 (aggregation) | **0.34** (io4ex4) | 5 | 0.48 | 0.54 | 0.50 | 0.51 |
| #24 MSET k=8 (atomic multi) | **0.48** (io4ex4) | 5 | 0.63 | 0.62 | 0.53 | 1.11 |

<!-- tomo-2s beats-or-ties the entire Redis family (redis+valkey+dragonfly) on 9/24 workloads; ranks #2 overall on 9/24 -->
<!-- garnet inapplicable (n/a) on 5/24 workloads (data structures + 64M keyspace) -->
