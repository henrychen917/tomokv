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

## Offline verification and final artifact manifest

Final results and reproducible receipts are appended here after the release rebuild.
No fresh throughput, cycles/op, IPC or live-tail improvement is claimed by this lane.
Append the maintainer's results and decision to `MEASURE-RESULT` in this worktree.
