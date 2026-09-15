# cx-lbstall-s3 — client-only balancer drain limit on stack3

**Correction to rejected v5 `29486b6a6`. Builds and units use CPUs 112–127.
The owner authorized the specific churn battery on server CPUs 112–119; its
receipts are recorded below. The full gate and performance measurements remain
mainline-scheduled.**

Worktree: `/home/user/Projects/cx-lbstall-s3`; branch: `cx-lbstall-s3`.
PRE is stack3 `3baa74799` (product source `147ac24b7`: v3 + L1 + O1 + O6).
The cx-lbstall commits `42d54d7e2`, `ad1542013`, `d0a565b32` are replayed,
with O1/O6 retained and the regression adapted to stack3. See [LBSTALL.md](LBSTALL.md).
Busy client moves still refuse immediately, and a ready client waiting for its
destination retains the three-pass bound. Shard publication/executor drains now
use v4's barriers and timeout guard: they do not consume the client pass budget.
The client counters, cooldown, lifetime fences and pending-IFID fix are unchanged.

## Arms and control semantics

All paths are relative to this worktree. The final manifest appears below.
Builds use GCC 13.3, jemalloc, `taskset -c 112-127 make -j8`, and the release
Makefile's per-translation-unit code-generation locks. No runtime knob changed.

- **A / PRE:** `build/tomokv-lbstall-s3-pre`, retained frozen stack3 build from the original integration.
- **B / POST:** `build/tomokv-lbstall-s3`, the client-only bounded-refusal candidate.
- **C / PAD-A:** `build/tomokv-lbstall-s3-pad`.

PAD is **kind (A), behaviour twin**, with the same scope as cx-lbstall's control:
PRE's wait-until-timeout busy-drain policy for ordinary tail-cell clients in POST's
exact text/state layout. Only three bytes at the out-of-line `lb_refuse_stalled`
entry become `xor eax,eax; ret` in a COPY of POST, preserving CET. Section sizes,
function addresses and every other file byte remain POST's. The same patch on the
unit executable makes the bounded-arrivals assertion fail.

PAD retains the candidate's cold safety mutexes, control-tail polling cadence,
cooldown scaffolding and INFO schema. It is a control for the refusal mechanism,
not a recreation of all PRE control-flow instructions. No kind (B) arm is requested.

## 1. Correctness gate — mainline schedules it

The maintainer's v5 gate reported **435/436**, with the armed block-cache churn
row failing because it observed **zero shard moves**. The new serverless shard
regression fails against that rejected implementation. It now requires the SAME
plan to survive eight publication tails and four executor-drain tails, execute its
queued SET, then commit and preserve RYOW in both modes. No client bound was relaxed.

Run `tests/gate.sh iteration` against POST at the gate's own geometry: 16 shards,
`GATE_RATIO`, `GATE_CORES`, with both thread modes and the armed read-local legs.
Do not substitute the 256-shard tail geometry for a correctness row.
Keep the gate's registered reference and ledger; the separate stack3 marginal
comparison below uses arm A explicitly. A version pass requires the full gate.

No gate source or EXPECT constant changed. The existing `core concurrency route`
row is emitted at `tests/gate.sh:1233` and collected at line 2640, before the quick
exit at line 2747. Row delta **0 quick / 0 full**; counts stay **419 / 436**.

## 2. Stack3 marginal rate protection

Use the gate's ABBA instrument at matched offered load. Run A/B/B/A, with at least
two independent blocks per cell and the existing engagement/overload witnesses.
Run A/C/C/A and C/B/B/C for any changed cell before attributing a difference.

| Cells | Purpose / fixed setup |
| --- | --- |
| `h01,h02,h05,h07` | 1s GET/SET p32, including overlap/reorder controls |
| `h17,h18,h21,h23` | The corresponding 2s controls |
| Remaining gate ABBA smoke cells | Armed read-local, multi-key, atomic and tail coverage in the gate's unchanged 17-cell set |
| GET/SET p8, 1s and 2s, read-local=0, overlap=0/1, reorder=0/1 | Preserve stack3's depth-8 behavior; same connection count and allocator |

Use the exact cell definitions in `tests/headline_cells.txt`, 512 total connections
for the named h-cells, and the gate's calibrated pins, key/value sizes and command
denominators. Pin ALL 1s GET comparisons (`h01,h05,h07`) at the same 12-generator
rung; the prior 2-vs-12-instance comparison hit a load-generator ceiling. Keep each
cell's offered load identical across arms. Other cells use their validated rung.
Leave client-lb and key-lb at their normal on settings, then repeat any differing
cell with both zero to distinguish movement from the stable control tail/layout.

**Decision:** zero main-command regression under the gate's existing acceptance
rule at matched offered load. Report rate, cycles/op, instructions/op and IPC for
every arm/cell. Rate is the verdict; instructions and IPC explain it together.
Resolve identical-arm spread above 2% as contention or a bug; do not widen a limit.
A/B alone cannot establish the cause of a text-layout-sensitive difference.

## 3. Tail / movement checks

Use mainline's frozen tailgen and population/boot scripts; record their digests,
full commands, warmup boundary, seeds and CPU mappings in `MEASURE-RESULT`.
Run A/B/B/A and C/B/B/C for the cells below. Keep 16 generator threads × 32
connections = 512, Poisson arrivals, GET:BITCOUNT = 8:2, read-local=0, atomic=1,
overlap=1, and both balancers on unless the cell says otherwise.

| Cells | Arms / repetitions / geometry |
| --- | --- |
| Original client-stall shape | 1s reorder=0/1, 717,000 ops/s, 256 shards, 2M short 64-byte keys + 2,048 long 256-KiB keys; 3 ABBA blocks, 3s warmup + 20s measured windows |
| Uniform-heavy instrument `t01–t04` | Both modes, reorder=0/1; 65,536 uniformly selected long keys, 717,000 and 900,000 ops/s, 16 generator instances; 2 ABBA blocks per rung, mainline's warmup cell and cold-first-run policy |
| Movement-off controls | Repeat any changed tail cell with client-lb=0 only, then both balancers=0; preserve offered load and all other settings |

At the 900K/s rung use paired deltas and the instrument's established same-binary
floor. Preserve pacing lag, unsent bytes, achieved rate, backlog and drain time so
overload cannot masquerade as one stalled connection. Save short and long latency
histograms separately: p50/p99/p99.9/p99.99/max, per-connection maximum outstanding,
and the any-connection-over-64 fraction. Take release INFO snapshots outside the
measured window: client/shard move counts, `lb_client_refused`, the refusal reasons
and `tomokv_lbstall_pending_ns_max` (publication-to-refusal, not end-to-end latency).

**Decision:** no new multi-second holds or short/long latency regression on POST;
ready moves remain possible, and busy candidates produce bounded refusals.
Stack3 already had two clean live rounds in the maintainer's evidence. A finite
PRE/PAD run with no stall is therefore expected to be possible and establishes
no latency gain for this fix. Only an armed PRE/PAD hold with a clean POST can
support a live stall-removal claim. The directed PRE/PAD unit failures independently
prove the new refusal behavior without claiming stack3's old IFID self-hold exists.

## 4. TLS exception follow-up

The strict byte proof below has three TLS exceptions. In addition to the named
plain-transport cells, run TLS GET/SET at p1/p32, 512 connections, 64-byte values,
read-local=0/1, both thread modes, and `--net-io uring` / `--net-io epoll`.
Repeat the TLS runs with the gate's Unix listener configured to visit the
TLS+Unix loop specialization. Use the gate's existing certificates/TLS client
plumbing and matched offered loads, with A/B/B/A and A/C/C/A controls.
Profile any changed cell before accepting a zero-regression claim. Live measurements
cannot turn a differing instruction sequence into a byte-identity pass.

## Final artifact manifest

Product commit: `73ddb263b`; regression commit: `85059ae74`.
Compiler: `g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`.
All arms use the same release flags/allocator. POST's unchanged GCC budget locks
are `main.o:146670`, `genthread.o:129860`, `rl2s.o:162350`, each with
`inline-unit-growth=0`.

| Arm | File | .text bytes | SHA256 |
| --- | --- | ---: | --- |
| PRE | `build/tomokv-lbstall-s3-pre` | 3531171 | `bce51ed313fce228eca285801484091466bdbd0448cad7adfb6ea506cc25945b` |
| POST | `build/tomokv-lbstall-s3` | 3535747 | `fadf6ed53714e3c89478ae0d1a224338d4105fcb0e94fedfad74092302b81ea6` |
| PAD-A | `build/tomokv-lbstall-s3-pad` | 3535747 | `c28cb23c1351820b80607eb18aa412546000f758e980fdd161768cce5899b370` |

POST grows .text by **4,576 bytes** versus stack3 and shrinks it by **16 bytes**
versus rejected v5. PAD-A has exactly POST's section sizes, symbol addresses and
file size. Only the three bytes starting at file offset **3560324** differ.
Receipts: `build/lbstall-s3-repair/artifacts.json`, `pad.json`.
Both delivered release arms remain executable.

## Completed verification

| Check | Negative / reference | Corrected POST |
| --- | --- | --- |
| Busy client, continuous arrivals, empty ROB | Frozen stack3 and PAD fail the four-pass assertion | **4/4**, first-tail refusal in both modes, destination ACK present/absent; same frames answered once |
| Ready source / missing destination ACK | PRE's timeout policy | Exactly third-tail refusal |
| Delayed shard publication/execution | Rejected v5 fails `shard publication drain MUST survive more than three IO passes` | Both modes commit the same delayed plan; owner, queued SET, RYOW and timeout guard asserted |
| Native units | Same two existing defects reproduced previously on frozen stack3 | **64/66 pass**, all rerun; unchanged two failures below |
| TSAN | No suppressions or waived failures | **11/11 pass**: eight core selections, overlap, waits, storage flags |
| Debug park / INFO | Real buffered input and executor scope | Four witnesses and parked-byte/refusal counters pass |
| Stable hot bodies vs rejected v5 | Release objects captured before the repair | **576/576** raw bytes AND resolved relocation targets match |
| Stable hot bodies vs stack3 | Frozen stack3 release objects | **573/576** match; same three TLS exceptions below |
| Full gate / rate / IPC / tails | Maintainer schedules these | Pending mainline execution |

Build command:

```sh
taskset -c 112-127 make -j8 -f Makefile \
  -f build/lbstall-s3-repair/checks.mk lbstall-repair-build
```

This rebuilt release, all named unit binaries, the park/INFO debug unit, and the gate's
`TOMO_RL_CACHE_DEBUG` server. The latter uses the exact compile/link flags and
source order from `job_rldbg` in `tests/gate.sh`, with eight compiler jobs.
No gate target was executed.

Every unit selection reran on CPUs **112–127**; owner-arena selections use
**112–119** because the fixture requires exactly eight allowed CPUs. Core units
use ASAN/UBSAN. The core and overlap TSAN builds instrument all linked production
dependencies, without jemalloc, with `-O1 -fsanitize=thread`,
`-fno-omit-frame-pointer -no-pie`. Runs use `setarch x86_64 -R`,
`TSAN_OPTIONS=halt_on_error=1:exitcode=66`, no suppressions. GCC's existing
atomic_thread_fence instrumentation warnings remain.

Fresh receipts live under **`build/lbstall-s3-repair/`**: `build.log`,
`checks.mk`, `run-units.py`, `units/results.json` (**75/77**, including TSAN),
per-selection logs, `directed.json`, `POST-shard.log`, `POST-debug.log`,
`PRE-client.log`, `PAD-client.log`, and `shard-negative.log`.
`core-concurrency-shard-negative` links the new test against rejected v5's
unchanged production objects. `core-concurrency-pad` patches only the refusal
entry in a copy of the corrected unit binary; it fails the intended client assertion.

**Known defects outside this repair, reproduced on frozen stack3 PRE during the
original integration and again on corrected POST:**

- `atomic-survivors-unit post_apply_probe`: first-owner APPLY plus two successful
  APPENDs gives lengths 2/2 and final `BW`, an illegal serial outcome.
- `netcmd-unit collection-oom`: failed multi-field HSET retains the changed first
  field and old TTL (OPEN F05).

These nongating diagnostics remain failing; no assertion or expected gate count
was changed. PRE receipts remain in `build/lbstall-s3-proof/`; corrected POST
receipts are in `build/lbstall-s3-repair/units/`.

### Authorized armed block-cache churn

**3/3 fresh boots pass**, with **16 / 10 / 18 bucket moves** measured by the
unchanged battery itself. Every boot ran the gate's ownership-assertion build:
`build/lbstall-s3-repair/tomokv-rlcachedbg`, SHA256
`2d82f35df857ba8c3196c4b474f01c8d0c6c50bd6ac80975df989f366d9b67ab`.

| Trial | Bucket moves | Armed read hits | Peak block cache, bytes | Result |
| --- | ---: | ---: | ---: | --- |
| 1 | 16 | 3991436 | 2752 | PASS, 5 checks, 0 skips |
| 2 | 10 | 3925813 | 2304 | PASS, 5 checks, 0 skips |
| 3 | 18 | 3865993 | 2768 | PASS, 5 checks, 0 skips |

All 48 workers completed in each 25-second battery. Every owned server exited
with status 0, a final shutdown report, and no `RLSINK-VIOLATION`,
`RLCACHE-VIOLATION` or `RLRING-VIOLATION`. All sampled server thread affinities
were subsets of **112–119**; the Python driver was pinned to **120–127**.
Each boot used a fresh empty persistence directory and an unused loopback port:

```sh
taskset -c 112-119 build/lbstall-s3-repair/tomokv-rlcachedbg \
  --port "$PORT" --bind 127.0.0.1 --shards 16 --dir "$FRESH_DIR" \
  --thread-mode fused --shards 64 --atomic 1 --read-local 1 \
  --enable-debug-command yes
taskset -c 120-127 python3 tests/rlcache_churn.py 127.0.0.1 "$PORT" 25 48
```

The base `--shards 16` followed by the `--shards 64` override matches
`launch` / `boot_fused` exactly; no `--ratio` is passed. INFO confirms
`thread_mode=1s`, `shards=64`, `atomic=1`, `read_local=1` before every battery.
Receipt: `build/lbstall-s3-repair/churn/results.json`, with exact argv, PID,
affinities, INFO snapshots, battery output and server logs. The harness is
`build/lbstall-s3-repair/run-churn.py`; all three owned server PIDs are gone.
No full gate or performance measurement was run.

### Sizes and source preservation

All eight PRE/POST locks hold: **Op 336, Client 1984, ThreadCtx 1408, Shard 1440,
FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624**. Also unchanged:
IoLoop **7136**, ExLoop **5856**, Server **105088**. The optional LB policy remains
**8448 bytes** (stack3: 80); both LB knobs at zero allocate none of it (unit asserted).
GDB read DWARF without starting an inferior: `build/lbstall-s3-repair/layout-POST.txt`.

`source-proof.json` confirms the L1 layout, O1 pipeline/window, O6 executor/prefetch
code, read-local code, configuration, overlap witnesses, gate source and churn
battery match stack3. `io_loop.h` is byte-for-byte unchanged from rejected v5,
including the client-move path and O1's removal of the pending-IFID self-hold.
The production repair is one additional stage guard in the existing out-of-line
`lb_drain_pass_expired`, plus comments. No new field, knob or per-operation branch.

### Strict byte-proof limit

**Full byte identity versus stack3 is still not achieved.** The strict checker
returns **1** for the same three inherited exceptions; none is masked or waived.
The repair matches **576/576** hot bodies versus rejected v5, and all six emitted
IO/EX LB control bodies are identical to rejected v5, including their prologues.
The expanded body set includes O1 stages, executor sweeps, store helpers,
completion handlers and loop wrappers. Callee and constant identities are compared
when address relocations are normalized. All three stack3 mismatches are in
`core/rl2s.o`:

| Function / specialization | PRE bytes | POST bytes | Difference |
| --- | ---: | ---: | --- |
| ROB callback in `WbEngine::serve_impl<false,true,true,true,false,true>` | 936 | 637 | TLS/no-borrow, epoll, coded replies: segment append is outlined |
| `IoLoop::on_cqe<true,true,false,1>` | 1206 | 1222 | TLS/epoll completion handling: TLS-slot lookup inlining moves between event arms |
| `IoLoop::run_loop<true,true,false,true,1,true>` | 4665 | 4682 | TLS+Unix, uring, read-local loop: inlining/register/branch layout differs |

These are actual code-generation differences beyond the predecessor's two
commuted CMP encodings. No instruction-count neutrality or measured zero tax is
inferred. Parser, O1 stages, executor/sweep, store and GET/SET/MGET/MSET bodies
match stack3; plain transport completion/loop bodies also match.

Fresh receipts: `hot-v5.{json,txt}`, `hot-stack3.{json,txt}`, `lb-control-v5.json`
in `build/lbstall-s3-repair/`. The unchanged TLS disassemblies and baseline control
comparison remain in `build/lbstall-s3-proof/`. The inherited IO LB control-tail
body is **3137 → 3411 bytes** relative to stack3, with stack reservation
**0x268 → 0x278** and corresponding prologue/epilogue differences. Its idle branch
returns before accounting; that wrapper has no byte-identity claim versus stack3.
This correction adds no further hot-body alias, encoding or prologue difference.

Reproduce the comparisons without executing either server:

```sh
taskset -c 112-127 python3 tools/lbstall_artifacts.py compare \
  build/lbstall-s3-repair/rejected-src build/src \
  build/lbstall-s3-repair/hot-v5.json
taskset -c 112-127 python3 tools/lbstall_artifacts.py compare \
  build/lbstall-s3-proof/pre-src/build/src build/src \
  build/lbstall-s3-repair/hot-stack3.json
```

No fresh throughput, cycles/op, IPC or live-tail improvement is claimed by this
lane. Append the maintainer's full-gate and measurement verdict to `MEASURE-RESULT`.
