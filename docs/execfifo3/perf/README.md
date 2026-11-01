# Finite perf counter results

Three blocks, 8,192 turns × 32 commands per owner; 378 counter runs. All counters ran at 100%. The two-owner fixture uses disjoint shards on CPUs 96 and 104 (different L3 domains). No EXEC, sockets or load generator.

Counts include fixture setup, allocation, exact-reply checks and teardown. They are not isolated command costs or server throughput. The parser cells also execute and check the dispatched commands after parsing. All cells use the single-database namespace; both namespaces have linked instruction/access proofs.

Every entry below is PRE / FIFO / POST, in millions of events. Do not infer zero regression from restored instruction counts: the cycle medians are not uniformly at PRE, and these short process-level fixtures do not replace the maintainer’s matched-load cells.

| Fixture | Mode | Read-local | Owners | Instructions (M) | Cycles (M) |
| --- | --- | ---: | ---: | --- | --- |
| SET | 1s | 0 | 1 | 288.746 / 288.746 / 288.743 | 73.438 / 72.674 / 73.851 |
| SET | 1s | 0 | 2 | 571.376 / 571.368 / 571.364 | 234.951 / 227.280 / 153.863 |
| SET | 1s | 1 | 1 | 420.497 / 420.497 / 420.497 | 102.589 / 100.970 / 102.570 |
| SET | 1s | 1 | 2 | 834.310 / 834.294 / 834.314 | 218.377 / 222.535 / 219.598 |
| INCR | 1s | 0 | 1 | 515.729 / 515.729 / 515.739 | 122.705 / 122.067 / 122.564 |
| INCR | 1s | 0 | 2 | 1034.264 / 1034.268 / 1034.294 | 438.052 / 442.694 / 442.659 |
| INCR | 1s | 1 | 1 | 559.635 / 559.636 / 559.650 | 134.215 / 133.774 / 133.602 |
| INCR | 1s | 1 | 2 | 1113.121 / 1113.117 / 1113.141 | 293.705 / 293.046 / 295.310 |
| SET | 2s | 0 | 1 | 284.166 / 284.166 / 284.163 | 75.017 / 76.314 / 74.274 |
| SET | 2s | 0 | 2 | 562.213 / 562.207 / 562.207 | 217.719 / 210.599 / 149.823 |
| PARSE-SET | 1s | 0 | 1 | 475.083 / 486.356 / 475.081 | 124.306 / 127.518 / 122.637 |
| PARSE-SET | 1s | 1 | 1 | 638.322 / 649.594 / 638.322 | 154.299 / 159.296 / 157.204 |
| PARSE-INCR | 1s | 0 | 1 | 680.384 / 690.870 / 680.394 | 169.055 / 175.222 / 170.893 |
| PARSE-INCR | 1s | 1 | 1 | 755.594 / 766.080 / 755.609 | 185.174 / 189.135 / 187.342 |

The [complete CSV](medians.csv) and [block counts](summary.json) include L1 load misses, L2 data-request misses, combined instruction/data L2 misses, instruction-cache misses, remote-CCX cache fills, local-CCX fills and requests to obtain exclusive state. The last three are the available coherence-related proxies used here; they do not identify dirty HITM transfers. Their process-level counts include startup and cannot attribute a transfer to a FIFO cache line.

`cache-misses` maps to `cpu/event=0x64,umask=0x09/` on this kernel: the same event as `l2_cache_req_stat.ic_dc_miss_in_l2`. It is not an LLC measurement. Direct LLC counts are **NOT RUN** because the kernel exposes no AMD L3 PMU and rejects both the generic LLC-miss event and the named L3-miss event. The [availability audit](../pmu-audit/README.md) retains the mappings and failed probes. No system module or PMU configuration was changed.

The exact commands, event runtimes, probe hashes, CSVs and assertion logs are retained in [results.json](results.json). Event descriptions and the two CPUs’ L3 topology are recorded in the parent directory.
