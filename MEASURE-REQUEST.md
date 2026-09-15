# cx-lbstall-s3 — bounded balancer drains on stack3

**Maintainer execution only. This lane ran serverless units on CPUs 112–127;
no server, benchmark, load generator or gate was started.**

Worktree: `/home/user/Projects/cx-lbstall-s3`; branch: `cx-lbstall-s3`.
PRE is stack3 `3baa74799` (product source `147ac24b7`: v3 + L1 + O1 + O6).
The cx-lbstall commits `42d54d7e2`, `ad1542013`, `d0a565b32` are replayed,
with O1/O6 retained and the regression adapted to stack3. See [LBSTALL.md](LBSTALL.md).
Busy client moves refuse immediately; destination and shard drains retain the
original fix's shared three-pass bound, counters, cooldown and lifetime fences.

## Arms and control semantics

All paths are relative to this worktree. The final manifest appears below.
Builds use GCC 13.3, jemalloc, `taskset -c 112-127 make -j8`, and the release
Makefile's per-translation-unit code-generation locks. No runtime knob changed.

- **A / PRE:** `build/tomokv-lbstall-s3-pre`, freshly built from frozen stack3.
- **B / POST:** `build/tomokv-lbstall-s3`, the bounded-refusal candidate.
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

Product commit: `6b7e90c83`; later commits update only verification documentation.
Compiler: `g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`.
All arms use the same release flags/allocator. POST's three GCC budget locks are
`main.o:146670`, `genthread.o:129860`, `rl2s.o:162350`, each with
`inline-unit-growth=0`. No experimental extra compiler parameter survives.

| Arm | File | .text bytes | SHA256 |
| --- | --- | ---: | --- |
| PRE | `build/tomokv-lbstall-s3-pre` | 3531171 | `bce51ed313fce228eca285801484091466bdbd0448cad7adfb6ea506cc25945b` |
| POST | `build/tomokv-lbstall-s3` | 3535763 | `b857b7288197d5cb66f6854c59754dc38fde479e53341087f8c7b71e76032d6a` |
| PAD-A | `build/tomokv-lbstall-s3-pad` | 3535763 | `9c9b90a9d1e98179a00ebaf3ccb628f2929b8a2040f7859ebb78e6b6bd98b9fa` |

POST grows .text by **4,592 bytes**.
PAD-A has exactly POST's section sizes, symbol addresses and file size. Only the
three bytes starting at file offset **3560324** differ. Receipt:
`build/lbstall-s3-proof/artifacts.json`, `pad.json`. Both release arms remain executable.

## Completed offline verification

| Check | PRE / negative control | POST |
| --- | --- | --- |
| Busy client, continuous arrivals, empty ROB | Frozen stack3 fails the four-pass bound | First-tail refusal; both modes, destination ACK present/absent; same frames answered once |
| PAD patched from the unit executable | Fails the same four-pass assertion | Unpatched unit passes |
| Ready source / missing destination ACK | Original timeout policy | Exactly third-tail refusal |
| Shard drain and movement | Original timeout policy | Shared three-tail bound; both modes, ownership and RYOW, non-coordinator and commit/refusal race |
| Native units | Two existing defects below reproduced | **64/66 pass**; identical two existing failures |
| TSAN | Not claimed for PRE | **11/11 pass**: eight core selections, overlap, waits, storage flags |
| Debug park / INFO | Not a live server measurement | Real parked bytes and refusing predicate asserted |
| Expanded byte comparison | Stack3 release objects | **573/576 match**, raw bytes and resolved relocation targets |
| Live gate / rate / IPC / tails | Maintainer's reference | Pending mainline execution |

All executions stayed on CPUs **112–127**. Owner-arena selections used **112–119**
because that fixture requires exactly eight allowed CPUs. Core units use ASAN/UBSAN.
The core and overlap TSAN builds instrument all linked production dependencies,
without jemalloc, with `-O1 -fsanitize=thread -fno-omit-frame-pointer -no-pie`.
Runs used `setarch x86_64 -R`, `TSAN_OPTIONS=halt_on_error=1:exitcode=66`, no
suppressions. Existing GCC atomic_thread_fence instrumentation warnings remain.

Every named unit selection ran. After the final compiler locks, every affected
production-linked native selection and the changed core TSAN route were rechecked;
unchanged independent selections retain their initial passing receipts. The complete
inventory is `build/lbstall-s3-proof/units/results-final.json` (75/77 including TSAN),
with `results-initial.json`, per-selection logs, `final-directed.json`, and the
PRE/POST/PAD/debug directed logs. Build recipes and logs are under the same proof
directory: `checks.mk`, `extra.mk`, `build-POST-units-retry.log`, `build-final.log`,
`build-final-make.log`; no server or gate target was executed.

**Known defects, reproduced on frozen stack3 PRE and final POST:**

- `atomic-survivors-unit post_apply_probe`: first-owner APPLY plus two successful
  APPENDs gives lengths 2/2 and final `BW`, an illegal serial outcome.
- `netcmd-unit collection-oom`: failed multi-field HSET retains the changed first
  field and old TTL (OPEN F05).

These existing nongating diagnostics remain failing; no assertion or expected gate
count was changed. Receipts: `pre-existing-probes.json`, `pre-post_apply_probe.log`,
`pre-collection-oom.log`, and their final POST logs in `units/`.

### Sizes and source preservation

All eight PRE/POST locks hold: **Op 336, Client 1984, ThreadCtx 1408, Shard 1440,
FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624**. Also unchanged:
IoLoop **7136**, ExLoop **5856**, Server **105088**. The optional LB policy grows
**80 → 8448 bytes**; both LB knobs at zero allocate none of it (unit asserted).
GDB read DWARF without starting an inferior: `layout-PRE.txt`, `layout-POST.txt`.

`source-proof.json` confirms the L1 layout, O1 pipeline/window, O6 executor/prefetch
code, read-local code, configuration, overlap witnesses and gate source match stack3.
All of `io_loop.h` outside the LB control tail and debug-only park hook is identical.
`lbstall.h` / `lbstall.cc` match cx-lbstall `d0a565b32` exactly.

### Strict byte-proof limit

**Full byte identity is not achieved.** The checker deliberately returns **1** for
the three exceptions below. No exception is masked or converted to success.
The expanded 576-body set includes the original cx-lbstall coverage plus O1's
individual stages, executor sweeps, store insert/erase/find paths, completion
handlers and loop wrappers. Callee and constant identities are compared when
address relocations are normalized. All three mismatches are in `core/rl2s.o`:

| Function / specialization | PRE bytes | POST bytes | Difference |
| --- | ---: | ---: | --- |
| ROB callback in `WbEngine::serve_impl<false,true,true,true,false,true>` | 936 | 637 | TLS/no-borrow, epoll, coded replies: segment append is outlined |
| `IoLoop::on_cqe<true,true,false,1>` | 1206 | 1222 | TLS/epoll completion handling: TLS-slot lookup inlining moves between event arms |
| `IoLoop::run_loop<true,true,false,true,1,true>` | 4665 | 4682 | TLS+Unix, uring, read-local loop: inlining/register/branch layout differs |

These are actual code-generation differences, beyond the predecessor's two commuted
CMP encodings. No instruction-count neutrality or measured zero tax is inferred.
Parser, O1 stages, executor/sweep, store and GET/SET/MGET/MSET bodies match; plain
transport completion/loop bodies also match. Complete names, disassembly and raw
results: `encoding-exceptions.json`, `tls-exception-*-{pre,post}.txt`,
`hot-bodies.{json,txt}`. Experimental compiler settings that changed an executor
sweep or read-local store helpers were rejected; their receipts remain in the proof
directory for review.

The intended IO LB control-tail body changes **3137 → 3411 bytes**, with stack
reservation **0x268 → 0x278** and corresponding prologue/epilogue changes. Its idle
branch returns before new accounting, but that wrapper has no byte-identity claim.
See `lb-control-bodies.txt` and `lb-control-summary.json`. No whole-program identity
or measured performance claim follows from the 573 matching bodies.

Reproduce the strict check, without executing either server:

```sh
taskset -c 112-127 python3 tools/lbstall_artifacts.py compare \
  build/lbstall-s3-proof/pre-src/build/src build/src \
  build/lbstall-s3-proof/hot-bodies.json
```

No fresh throughput, cycles/op, IPC or live-tail improvement is claimed by this lane.
Append the maintainer's results and decision to `MEASURE-RESULT` in this worktree.
