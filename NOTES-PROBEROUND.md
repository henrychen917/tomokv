# Two-round EX probe prefetch

## Result

Implemented behind the compile-time `TOMO_PROBE_ROUND2` pin, default `1`. The measurement is a
positive **null** against the stated acceptance rule: all three rate medians improved, and no rate
cell regressed, but the best median rate gain was only **+1.53%**. IPC improved by more than 2% in
all cells only by executing **+1.62% to +3.79% instructions/op**, so it does not satisfy the
alternative ">=2% IPC at flat instructions/op" clause.

| cell (median of 4 arms) | OFF rate | ON rate | rate delta | OFF IPC | ON IPC | IPC delta | OFF instr/op | ON instr/op | instr/op delta |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GET, 2M keys, 32 B, p32 | 18,364,637 | 18,457,787 | **+0.51%** | 0.587755 | 0.600071 | +2.10% | 3,177.42 | 3,228.82 | **+1.62%** |
| GET, 10M keys, 32 B, p32 | 18,176,441 | 18,347,152 | **+0.94%** | 0.576408 | 0.595528 | +3.32% | 3,147.92 | 3,216.45 | **+2.18%** |
| SET:GET 1:9, 2M keys, 512 B, p32 | 11,147,813 | 11,318,194 | **+1.53%** | 0.481707 | 0.503941 | +4.62% | 4,275.34 | 4,437.43 | **+3.79%** |

The two ABBA block mean deltas were:

| cell | block 1 rate / IPC / instr-op | block 2 rate / IPC / instr-op |
|---|---:|---:|
| GET 2M × 32 B | +0.46% / +2.16% / +1.69% | +0.59% / +2.10% / +1.50% |
| GET 10M × 32 B | +1.08% / +3.55% / +2.44% | +0.94% / +3.27% / +2.30% |
| mixed 2M × 512 B | +1.79% / +5.41% / +3.57% | +0.56% / +4.07% / +3.49% |

The mixed cell's second block is why the +1.53% median is not rounded into a win. The complete
per-arm INFO and perf reduction is in `scratchpad/proberound/results.tsv`.

## Implementation

The existing whole-batch pass still issues `FlatStore::prefetch(hash)` for the current and old home
slots. With `TOMO_PROBE_ROUND2=1` and `n >= 8`, a second pass calls
`FlatStore::probe_candidate(hash)`. That helper walks packed slot words, compares only their 15-bit
hash tags, and returns the first encoded `KvObj*` without reading any object field. The executor
prefetches that object's first line, then runs the unchanged execute loop. `FlatStore::find()` still
does the authoritative table walk, key length check/memcmp, expiry/MVCC resolution, and value read.

A tag collision can prefetch the wrong object. A handoff or rehash can make a hint stale. Neither
result escapes the prefetch pass or changes a reply. This deliberately has the same hint-only
contract as the existing bucket prefetch.

`TOMO_PROBE_ROUND2=0` preprocesses the candidate pass away. Batches below eight retain the previous
bucket-prefetch plus execute path. The Makefile passes the pin to release, ASAN, TSAN, and the
no-reservation control target; an out-of-Makefile compilation defaults it to on in `ex_loop.h`.

## Measurement

- Source commit: `d075b1dbd78addf3e2efc21c0237d6883e3897bd`.
- OFF binary SHA-256: `e6e7407d272fc683ea5047ab6ad81b253ab6ef8ebe2384012507e2fbfdff98b7`.
- ON binary SHA-256: `3ba41e4318092a5736cefd3a8f89a6acc5c1e9c5440093c31caad97eeadc92c3`.
- AMD EPYC 9754; server CPUs 32-63; load generator CPUs 96-127; loopback port 7861.
- 64 shards, IO:EX `18:14`, atomic off, p32, 32 memtier threads × 8 clients.
- Every arm used a fresh server and complete population verified by exact `DBSIZE`.
- Order per cell: OFF, ON, ON, OFF, OFF, ON, ON, OFF (ABBA ×2).
- The load ran 14 seconds. After a two-second lead-in, `perf stat -C 32-63 -e
  cycles,instructions` covered 10 seconds. INFO `total_commands_processed` snapshots bracketed that
  counter window; rate is the INFO delta / 10. Every GET delta reported zero misses.
- Control and experiment came from clean builds of the same tree using
  `make TOMO_PROBE_ROUND2=0` and `=1`.

Two unmeasured population/warmup processes were externally SIGKILLed on the shared host. Neither
produced a row. The listener-checked harness stopped only its own recorded server PID, then resumed
at the missing ordinal; the intended sequence and all 24 measured arms are complete. The exact
runner, including its PID-only cleanup and resume mode, is `scratchpad/proberound/abba.sh`.

## Verification

- Default-ON release build: pass, with no compiler warnings.
- Clean OFF build and clean ON build: pass; hashes above differ.
- `tests/gate.sh quick`: **238/239** rows passed. The only failure was the rate-sensitive FLIP
  controller stable-hold row: the main run triggered `anchor-rate-collapse`; an isolated rerun
  triggered the opposite `anchor-rate-surge`. All executor ordering, rehash/growth, snapshot,
  atomic, AOF, TLS, ASAN-build, shutdown, and 100%-hit floor rows passed. This is reported as a gate
  failure, not silently called green.

## Verdict

Keep the requested default-on worktree implementation and its clean OFF pin, but record the
performance outcome as **null under the supplied bar**. The second round converts some stalls into
useful overlap (positive rate and IPC direction at every scale), but its extra tag walk and batch
metadata work are visible in instructions/op, and the resulting throughput gain does not reach 2%.
