# TomoKV v6 cleanup — maintainer handoff

Base/PRE: `e4ec4dfce` (v5). This branch retires reorder, replaces the headline
tail geometry, merges `cx-tailgen` at `76265d400`, and adds the open-loop client
migration stall row. No server, benchmark, or full gate was run by this lane.
All compilation and serverless checks were pinned within CPUs 112–127, using
`make -j8` for builds.

## Arms and decisions

- PRE: `build/tomokv-v5`, built from the clean base before any edit.
- POST: `build/tomokv-v6`, the final release build of this branch.
- PAD: `build/tomokv-v6-pad`, **kind B — inverse control**: candidate behavior
  plus inert text padding restoring PRE's `.text` size. It is not a PRE-behavior
  twin. The pass deletion changes text size by more than a few hundred bytes;
  compare PAD to both PRE and POST to detect a placement/size contribution.

Frozen release arms (same compiler, flags/allocator family):

| Arm | .text bytes | SHA256 |
| --- | ---: | --- |
| PRE | 3,535,747 | `b56cdc8dc68d6a6d9abca0a805b8896e05387a7c4914d9713d1cf111f2d0ab49` |
| POST | 3,532,099 | `30f16cce0ca2b99f0873f299e08c5365d7c691d9ba20a26327ca6d37f97b84d4` |
| PAD | 3,535,747 | `d62e1c07f46ba2645a09a051023c1a83bd85a938f1a4604dace4be374325cc4f` |

POST shrinks `.text` by **3,648 bytes**. PAD adds exactly 3,648 inert NOP bytes
in an unreferenced function; it restores PRE's text size without reintroducing
the scheduler. `build/v6-audit/binaries.json` and `pad-link.json` retain the
digests, kind and exact link command. The assembly is `inverse-pad.S`.
No performance result is claimed before `MEASURE-RESULT` is supplied.

| Required comparison | PRE | POST | Decision |
| --- | --- | --- | --- |
| h01,h02,h05,h07,h17,h18 rate | pending | pending | Rate-neutral or better vs v5; no loss hidden by a different generator count |
| Same six cells cycles/op, instructions/op, IPC | pending | pending | Explain the rate result; instruction count alone is not a verdict |
| t01–t04 short and long p99.9 | pending | pending | Report only; compare with the mode's same-binary spread |
| Open-loop outstanding bound | owner records: v5 8/8, v3 fails 10/10 | pending | Strict correctness: fraction = 0 and maximum <= 64 |

Use the quiet box, one measurement lane, with the gate's instrument. Rate fixtures
pin **all six cells at 12 instances** so h05/h07 cannot repeat the 2-instance cap
confound. They retain 512 total connections, p32, 64-byte values, atomic=1 and the
original mode/read-local/overlap/reorder axes. Both balancers remain at default on.
Tail fixtures fix **16 instances**, 512 total connections, p8, GET:BITCOUNT 8:2,
65,536 blockers × 256 KiB = 16 GiB, and `--rate-limiting=1400` per connection:
716,800/s (the 717K/s, 68% rung of the 1.06M/s wall). The ordinary two-million-key
short population remains 64 B per value. `t00` is identical to `t01` and runs
first as a reported-only warmup; do not include it in the tail conclusion.

The root's `build/v6-rate-cells.txt` and `build/v6-tail-cells.txt` are extracted
from `tests/headline_cells.txt` with column 11 set to 12 and 16 respectively.
Recreate them after cleaning `build/`; do not calibrate the tail geometry back to
one generator. The t01–t04 JSON records now explicitly invalidate the old
2048-key saturation calibration instead of relabeling its observations as fresh.

Run two complete ABBA blocks per arm pair (distinct `--output` per invocation):

```sh
# PRE -> POST rates; repeat with candidate tomokv-v6-pad and distinct output.
tests/gate.sh perf --reference-binary "$PWD/build/tomokv-v5" \
  --candidate-binary "$PWD/build/tomokv-v6" \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --cells "$PWD/build/v6-rate-cells.txt" --subset full \
  --output "$PWD/build/v6-rate-1"

# PRE -> POST reported tails; t00 is first in this fixture. Repeat for PAD.
tests/gate.sh perf --reference-binary "$PWD/build/tomokv-v5" \
  --candidate-binary "$PWD/build/tomokv-v6" \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --cells "$PWD/build/v6-tail-cells.txt" --subset full \
  --output "$PWD/build/v6-tail-1"
```

Keep per-arm rates, cycles/op, instructions/op, IPC, all raw histograms, generator
CPU/pacing evidence and observed spreads. Repeat a same-binary v5 block at these
exact placements if rate spreads exceed 2%; do not widen a tolerance. The owner
measured paired v5 rate differences around ±1% on a quiet box. The valid tail
instrument's same-binary p99.9 spreads are **2–3.5% (1s)** and **6–10% (2s)**;
these are reference observations, not newly introduced gate thresholds. Tail
rows, including t00, stay reported-only under `abba_simple.py`.

## Correctness row and ledger arithmetic

The new `tailgen client-lb outstanding bound` row runs **before the quick-tier
exit**, after `join_workers`, using `boot_fused` with `--shards 256 --atomic 1
--overlap 1`, read-local at its default off, and both balancers at default on.
It uses the gate's complete tail placement (`PERF_SERVER_CORES` and
`PERF_LOAD_CORES`) because ordinary parallel correctness slots may have only two
load cores, while tailgen requires 16 distinct load cores. A smaller allocation
fails visibly; the generator is never oversubscribed or silently reduced.

The generator build runs as a dependency job without another ledger row. The
90-second row covers boot, memtier short-key population, the shared
`abba_workloads.prepare_long_keys`, 3 s warmup, 20 s measured window, JSON
validation. Teardown follows before restoring the slot placement. Its exact load is:

```sh
build/tailgen --rate 717000 --threads 16 --conns 32 --cores '<gate load cores>' \
  --mix GET:8,BITCOUNT:2 --spacing poisson --warmup 3 --duration 20 \
  --max-outstanding 64 --short-keys 2000000 --long-keys 65536
```

`--conns 32` is per thread. The outstanding witness observes, and does not cap,
open-loop submissions. Any positive `over_max_outstanding_fraction` or
`outstanding_max > 64` fails. Missing/nonfinite fields, wrong window, absent
command classes, boot/population/driver/build failures also fail. Artifacts live
under the run's `main/tailgen-stall/` (argv, population, stdout JSON, stderr).
The row's serverless controls test both bounds independently and cover failure
propagation through the real shell branch with all workloads stubbed.

Two retired rows were before the quick exit: the dedicated `reorder mechanism +
32/128-task geometry battery`, and `core concurrency scheduler`, which directly
called the deleted scheduler too. One new stall row is also before that exit.
Counted by source line: v5's core loop was at 1232 and dedicated reorder row
at 1252, before its quick exit at 2743. V6's new row is at 2746, before its
quick exit at 2758. Thus **quick 419 - 2 + 1 = 418; full 436 - 2 + 1 = 435**, excluding any optional
NIC additions. **Neither EXPECT_QUICK nor EXPECT_FULL was edited.** The maintainer
must update them before the iteration/full gate. T00 adds no correctness ledger
row; the ABBA result remains reporting-only in this gate.

After that owner count update, run `tests/gate.sh iteration` against POST on the
quiet box. Both 1s and 2s boot coverage remains in the feature matrix; requested
reorder=1 must warn exactly once and report effective reorder=0. Its old parser
grammar is unchanged, and no reorder stats sidecar is allocated.

## Offline validation and byte proof

The final audit is **555/576 identical bodies** after resolving ELF relocation
addresses and checking their target identities; **549/576** also match as raw
object bytes. The checker does not normalize instructions or ignore mismatches.
Sixteen changed bodies contain the removed executor batch path, including its
inlined drain/sweep callers. Among the other 560 bodies, **555 match and five
do not**. Thus a claim that *every* untouched body is byte-identical is **not
established**. Compiler budget retuning reduced the initial 35 mismatches to 21;
none of the remaining five is silently waived.

| Audited family | Identical / checked |
| --- | ---: |
| GET/SET/MGET/MSET emitted bodies | 5 / 5 |
| Parser/hash-dispatch bodies | 70 / 70 |
| FlatStore lookup/insert/erase bodies | 160 / 160 |
| Fused pipeline bodies | 4 / 4 |

The five exceptions are all in `core/rl2s.o` (split read-local):

| Body | PRE bytes | POST bytes |
| --- | ---: | ---: |
| `WbEngine::serve_impl<false,true,true,false,false,true>` Op lambda | 936 | 637 |
| `WbEngine::serve_impl<false,true,false,false,false,true>` Op lambda | 936 | 637 |
| `IoLoop::on_cqe<true,true,false,1>` | 1,222 | 1,206 |
| `IoLoop::run_loop<true,false,false,true,1,true>` | 4,626 | 4,618 |
| `IoLoop::run_loop<true,true,false,true,1,true>` | 4,682 | 4,665 |

The `on_cqe` specialization is a weak duplicate also emitted by the earlier
`main.o`; this audit conservatively retains the object mismatch. The two outer
loops include Unix listeners, with/without TLS. These differences require
measurement, not an instruction-count argument. In addition to the six required
rate cells, compare PRE/POST/PAD with **2s, read-local=1, overlap=1, atomic=1,
balancers on, GET/SET at p1 and p32, 512 connections, 64 B**, covering TCP, Unix,
and TLS transports plus epoll/uring where supported. Keep the ordinary required
rate cells unchanged. No zero-regression claim is made for these exceptions.

All size locks compile unchanged: **Op 336, Client 1984, ThreadCtx 1408, Shard
1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624**. Retired witness
space is padding, preserving the live overlap field's offset and 64-byte sidecar;
the sidecar is allocated only by overlap. The retired executor flag is padding
so subsequent executor fields retain their offsets. No locked structure grew.

Completed serverless checks (logs under `build/v6-audit/`):

- Release `make -j8 all unit`; all five native unit programs passed, including
  exact retirement grammar/diagnostic and CLI override controls.
- Netcmd CONFIG/INFO unit: effective zero, retirement marker, absent counters,
  null-sidecar behavior, no INFO allocation.
- Overlap prefetch unit: 1s/2s, overlap off/on, read-local/atomic/balancers armed.
- All seven surviving core concurrency rows under fully instrumented TSAN;
  the same seven rows also passed ASAN/UBSAN.
- Tailgen native, ASAN/UBSAN and TSAN units: all passed, including partial sends,
  more than 64 outstanding requests, both pacing modes and JSON contract.
- ABBA controls: 88 main + 10 saturation + 7 calibration tests passed.
- Gate harness: all 54 tests passed (`gates-complete.log`), including each
  helper's failure propagation, scheduler inventory, and both serial instruments'
  join boundaries. Tailgen stall controls: 3 passed.
- Measured-config: 10; simple comparison: 11; planner: 23 + 10 tests passed.
  Shell and Python syntax checks passed. No test-count constants were modified.

Reproduce the audit without executing a server:

```sh
taskset -c 112-127 python3 tools/lbstall_artifacts.py compare \
  build/v6-audit/pre-src build/src build/v6-audit/hot-final.json
```

This strict comparator intentionally exits nonzero for the 21 recorded changed
bodies. `hot-final.json` and `hot-final.txt` retain every selected symbol, byte
length, raw equality and relocation-aware verdict. Do not relabel that exit as a
complete byte-identity pass. Build logs include compiler warnings; TSAN runtime
logs contain no race report. Both-mode live boots, the new 16-GiB correctness row,
the full iteration gate, and all PRE/POST/PAD measurements remain the maintainer's
work on the scheduled quiet box.
