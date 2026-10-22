# Bounded MGET diagnostic

One verified batch per cell after one warmup command; 8 keys / 8 shards, 64-byte values, 16 shards, databases 1, read-local 0. 1s uses eight fused threads; 2s uses six IO + two executors. Commands are finite, without a timed loop or load generator.

The scopes include preparation, gather, completion and retirement with inclusive callees. They exclude parsing, scheduling, networking and idle time. Instructions subtract one return-breakpoint instruction per scope, verified by the 129/131 instruction calibration. Raw scope values and non-multiplexed PMU running/enabled times are retained in the input JSONs. Cycles are measured under debugger serialization and cache disruption; they are not latency, throughput, or an acceptance metric.

| Mode | Atomic | Batch | Arm | Instructions/command | Debugger cycles/command |
|---|---:|---:|---|---:|---:|
| 1s | 0 | 1 | headline | 10335 | 79534 |
| 1s | 0 | 8 | headline | 14341.6 | 41068.4 |
| 1s | 1 | 1 | headline | 10339 | 75249 |
| 1s | 1 | 8 | headline | 14369.8 | 43844.2 |
| 2s | 0 | 1 | headline | 10373 | 61258 |
| 2s | 0 | 8 | headline | 14328.4 | 35610.9 |
| 2s | 1 | 1 | headline | 10329 | 59597 |
| 2s | 1 | 8 | headline | 14360.1 | 35762.4 |
| 1s | 0 | 1 | moverfix | 10239 | 67854 |
| 1s | 0 | 8 | moverfix | 14317.9 | 42969 |
| 1s | 1 | 1 | moverfix | 10315 | 74982 |
| 1s | 1 | 8 | moverfix | 14297.6 | 40950.2 |
| 2s | 0 | 1 | moverfix | 10301 | 68027 |
| 2s | 0 | 8 | moverfix | 14328.5 | 38487.5 |
| 2s | 1 | 1 | moverfix | 10353 | 58629 |
| 2s | 1 | 8 | moverfix | 14309.2 | 47853.6 |
| 1s | 0 | 1 | merged | 10311 | 70847 |
| 1s | 0 | 8 | merged | 14293.5 | 41809.6 |
| 1s | 1 | 1 | merged | 10393 | 68543 |
| 1s | 1 | 8 | merged | 14345.6 | 41771.1 |
| 2s | 0 | 1 | merged | 10301 | 76526 |
| 2s | 0 | 8 | merged | 14306.4 | 45555.5 |
| 2s | 1 | 1 | merged | 10329 | 64457 |
| 2s | 1 | 8 | merged | 14332.2 | 42724.4 |
| 1s | 0 | 1 | post | 10263 | 83160 |
| 1s | 0 | 8 | post | 14270.4 | 38207.6 |
| 1s | 1 | 1 | post | 10339 | 59106 |
| 1s | 1 | 8 | post | 14369.8 | 42884.2 |
| 2s | 0 | 1 | post | 10349 | 60797 |
| 2s | 0 | 8 | post | 14305.2 | 37370.4 |
| 2s | 1 | 1 | post | 10353 | 72181 |
| 2s | 1 | 8 | post | 14285.1 | 37516 |

`instruction-summary.json` breaks each cell into the four scopes. `instructions-references.json` and `instructions-post.json` retain every individual scope, setup witness, command, executable digest and reply validation. `trace-calibration.json` is the known-count control.

Gather is ordinarily 3724 instructions/command for headline and 3700 for the three subsequent arms; completion is ordinarily 446. Allocator and ordering variation in preparation/retirement dominates the small total differences here. These single finite batches do not explain or refute the maintainer’s rate results. No throughput claim follows.
