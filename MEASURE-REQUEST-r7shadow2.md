# r7shadow2 — fused scope, derived AUTO, cheaper live queues

Worktree/branch: `/home/user/Projects/cx-r7shadow`, `cx-r7shadow`.
Round-1 PRE: `61a7c9eb0`. Mainline explicitly opened the codex phase in
`/home/user/Projects/endgame.log` at 02:16:39 on 2026-09-18.
No server, load generator, benchmark, or gate was started by this lane.
Builds and serverless units used CPUs 112-127. The requested instruction-only
unit accounting used CPU 112. **Round-2 rates and tails are unmeasured.**

## 2s decision and what the evidence does establish

The mechanism is now **fused only**. Both executable boot and `Server::init`
resolve every split request (0, 1, -1) to `reorder=0` before role selection and
schedule-state allocation. Split IO, split read-local IO, both executor types,
and FLIP role entries consequently select the existing off bodies. INFO reports
`reorder:0`, `reorder_retired:1`, and no reorder counters in 2s. This uses the
existing capability contract understood by the gate and ABBA instrument.

The owner's previous measurements, not new lane measurements:

| Mode / offered rate | Round-1 shadow vs off p999 | Interpretation |
| --- | ---: | --- |
| 1s / 880K | null | No demonstrated payoff |
| 1s / 985K | -14% | Both classes improve; PAD controlled |
| 1s / 1030K | -20% | Both classes improve; best in each paired round |
| 2s / 880K | null | No demonstrated payoff |
| 2s / 985K | -11% | Shorts -16%, longs unchanged |
| 2s / 1030K | +84% | Unacceptable wall loss; ratio-only R7 was also worse |

Source diagnosis found a concrete drain-length-dependent defect in the old
connection index. Removing a connection set `tail=None` but retained `client`.
After enough distinct clients visited a drain, no virgin table entry remained;
each absent-client lookup walked **all 4B entries**, even with few live clients.
The table was reset only on construction of the next inbox-drain scope. Deep
queues keep that scope alive across many gathers. The instruction unit below
reproduces the resulting escalation, and the new index removes it.

The old completion refresh also walked every queued node at each output boundary,
including same-connection followers that could not be selected. It now visits
only eligible shadow heads; a follower is checked when it becomes eligible.

These observations identify avoidable work, **not a causal decomposition of the
measured +84%**. The pick-bound tests do not find starvation: the inherited bound
is B + 2B*(4+1), i.e. 352/1408 picks for B=32/128. This is not a millisecond bound.
The one-gather carry, forced-oldest turns and connection eligibility can still
change batching at saturation. Connection eligibility must not be weakened:
`L s L` must remain ordered. No new ratio or carry policy is claimed to cure 2s.

Split IO already drains/flushes independently of owner execution, whereas a fused
owner delays its own IO while executing. Combined with the supplied null/knee/
wall measurements, that supports shipping this candidate only in the demonstrated
fused scope. It does **not** prove that every conceivable split scheduler cannot
benefit: the 985K result is explicitly positive. Isolating the old 2s wall loss
further requires a mainline profile or a separately scheduled counterfactual arm;
this lane does not claim to have measured one.

## AUTO policy and remaining costs

Public grammar is `--reorder -1|0|1`; default remains **0**. `1` remains the
forced-on comparison arm, not a tunable threshold. The existing unsigned Config
slot uses a named -1 sentinel internally, as the shard auto knob does; CONFIG GET,
CONFIG REWRITE and INFO expose the signed spelling. Config stays 624 bytes.

Only the armed fused role creates a stack `PolicyScope`. Its owner-private pointer
and an atomic diagnostic occupy the existing 16-byte padding in the 64-byte
`ModeScheduleStats`; no locked structure grows and no new heap sidecar is added.

On the **existing** `sample_depth` tick (100 microseconds), AUTO observes at most
two gather capacities (64 queued handles), in producer/drain order, without
consuming them. It reads command metadata only from still-queued tasks. It counts
ordinary short and Long classes, and short **ROB heads** queued after a Long.
Barriers clear the precedence observation. A same-pipe successor is not a head
and cannot manufacture the witness. Depth includes all producer queues; class
sampling is bounded and therefore can conservatively miss a distant opportunity.

The rolling window has one sample per gather slot (32 existing ticks). The policy
engages only after that window exists and all three conditions hold:

1. The current sample contains a short head queued after a Long.
2. Current queue depth is at least the ceiling of the observed window mean depth.
3. Short heads behind Longs outnumber Longs over the window.

It disengages on the very next sampled tick if any condition fails. There is no
core-count, offered-rate, latency, byte-size or calibrated mix threshold. The
window and bounded sampling budget derive from the scheduler's gather capacity;
the depth/class cutoffs derive from observations. This is a candidate policy,
not a measured break-even estimator or a claim that these cutoffs are optimal.

Disarmed AUTO delegates owner work to the ordinary FIFO drain/batch methods.
Dispatch still stamps while AUTO is requested: the parser's own owner may be
inactive while the destination owner is engaged. Skipping those stamps based on
the parser's local policy would lose a foreign-pipe blocker. Forced-on and AUTO
therefore retain some parse-side cost even when pure GET has no payoff.

INFO, when reorder is requested in 1s, adds `reorder_auto_samples`,
`reorder_auto_engaged_owners`, and `reorder_auto_engagements`. Samples and cumulative
engagements saturate in a packed atomic diagnostic. No per-operation counters or
clocks were added. A final zero engaged-owner count after draining is expected;
the cumulative engagement count is the positive witness for the measured window.

## Queue bookkeeping and correctness

The connection index is a bucket array pointing to **live connection tails**.
Chained collisions use links in those live nodes. Removing the last task unlinks
its tail, so old client churn leaves no tombstones. Queue indices fit uint16_t.
Stack scratch falls from 6,200 to **3,360 bytes** at B=32 and from 24,632 to
**13,344 bytes** at B=128. This is not a per-client/per-shard layout change.

The armed parser scans backward and stops at the newest unfinished registered
Long. It still may scan the live ROB (up to 64 slots); a pure-short pass does not
get an O(1) cache. No persistent Client metadata or off-path field store was added.

The three ready FIFOs remain unshadowed short, Long, shadowed short. Only the first
queued task per connection is eligible. The three-pipe permutation, `L s L`,
barriers, RESP retirement, late local-read demotion, Done-before-retirement and
slot reuse remain covered. No queue or Client pointer survives `finish()` across
an ownership/control boundary. AUTO retains only aggregate samples per physical
owner, not shard structures or task pointers. Immutable replacement, QSBR,
single-owner writes, atomic deferrals and reader algorithms are unchanged.

This still exceeds a literal one-bit/one-compare envelope: ROB scanning, the live
connection index and eligible-head completion probes remain. That limitation is
separate from the strict off-path byte witness.

## Instruction-only PRE / POST unit accounting

`tests/r7shadow_instr.cc` is compiled unchanged against archived PRE headers and
POST headers, with the same GCC flags. `perf_event_open` brackets only dispatch
bookkeeping or scheduler execution; fixture/client allocation is outside each
interval. Only user instructions are counted, and multiplexed/scaled counters
are rejected. No clocks or throughput rates are collected.

Median of three processes (instructions per submitted ordinary task):

| Fixture | PRE | POST | Delta |
| --- | ---: | ---: | ---: |
| Dispatch, 32 unfinished short predecessors + 32 short stamps | 50.630 | 50.661 | +0.031 |
| Dispatch, newest predecessor Long + 32 short stamps | 55.630 | 36.192 | -19.438 |
| Two mixed gathers, B=32 | 243.034 | 226.252 | -16.781 |
| 48 mixed gathers with distinct-client churn, B=32 | 1826.632 | 222.289 | -1604.343 |
| 48 mixed gathers with distinct-client churn, B=128 | 5960.792 | 216.629 | -5744.163 |

The churn fixture intentionally holds one queue scope across 48 gathers, with an
unfinished foreign Long shadow and a queued Long in each gather. It is a mechanism
stress fixture, **not** the tailgen 8:2 workload. PRE's hash-probe instruction range
is 1599.49-1915.88 at B=32 and 5627.21-6105.83 at B=128 as addresses/collisions vary;
POST ranges are 222.24-222.31 and 216.57-216.66. This is instruction-count variation
in the synthetic index, not rate noise. Counts exclude the rest of the RESP parser,
command execution, networking, scheduler-wrapper branches and AUTO tick sampling.
They are not end-to-end instr/op, cycles/op, IPC, a speedup or a latency claim.

Evidence files: `build/r7shadow2-instr-{pre,post}-{1,2,3}.csv`.
The all-short dispatch result does not establish any reduction of the h07 tax.

## Artifacts and checks

Built code revision: `ccd3c6e52`. The later report commit changes documentation
only. PRE source/objects and the preserved round-1 executable are under
`build/r7shadow2-pre/`.

| Arm | Executable | .text bytes | SHA256 |
| --- | --- | ---: | --- |
| Round-1 PRE, `61a7c9eb0` | `build/r7shadow2-pre/build/tomokv` | 4171745 | `74721e4c4db1a64b2c83a48a8096d4e381207f5969cb604a23ee9ce33e7de216` |
| Round-2 POST | `build/tomokv` | 4190381 | `5f72057199d456a09b4145d022fa3a9e3047cba021ace8c7d92c6f0e28a5b81a` |
| Kind-A FIFO PAD | `build/tomokv-pad` | 4190381 | `58c25410b9c0ee9068781abafd974e1d7b828139133e568d098545e502d9f4d4` |

POST adds 18,636 text bytes against round 1. POST and PAD are each 91,900,008
file bytes; their only differing byte is the capability immediate at file offset
3,665,381 (`01` -> `00`). No whole-binary or whole-layout identity to round 1 is
claimed.

PAD is **kind A: behaviour twin**, explicitly **PRE FIFO (`--reorder 0`) behaviour
with POST's exact text size/layout**. It is not the old R7-ratio-without-shadow arm
and is not the round-1 forced-shadow behaviour. `make build/tomokv-pad` now patches
only the immediate in the cold `reorder_available()` predicate in a copy of POST.
Every other byte, symbol address, section header and instruction size is identical.
Use PAD with `--reorder 1`. `build/tomokv-pad.json` binds both hashes and the patch.
The historical shadow-only builder remains available with `--scope shadow`.

Final verification completed without executing a server binary:

- Default build, PAD build and all seven `make unit` binaries passed, with no
  compiler warnings/errors (`build/r7shadow2-final-build.log`).
- The final POST against the preserved round-1 executable passed the unchanged
  strict normalizer and **169/169 identical off-path bodies**. Receipt:
  `build/r7shadow2-final-off-witness/audit.json`. The witness script and its
  exclusions were not changed. Retaining the existing bodies required adjusting
  only the existing `main.cc` compiler budget from `large-unit-insns=146165` to
  `146215`; the other TU budgets are unchanged. This is a compiler code-generation
  lock, not a runtime threshold.
- Production serverless parser/inbox/handler fixtures passed for POST and the
  separately patched kind-A unit twin. They require the exact three-pipe order,
  empty carry, RESP retirement, late read-local demotion, foreign-owner shadows,
  AUTO engagement/disengagement and split FIFO resolution. Logs:
  `build/r7shadow2-final-engagement.log` and
  `build/r7shadow2-final-engagement-pad.log`.
- `netcmd-unit config` passed signed AUTO spelling, INFO capability and zero-state
  checks (`build/r7shadow2-final-config.log`). The real parser matrix includes
  -1/0/1 across modes, overlap, read-local and network-engine grammar.
- ASan/UBSan shadow units passed (`build/r7shadow2-final-asan.log`). All six
  throwaway mutants failed their required assertions: no shadow, no completion
  promotion, no fairness bound, no newly eligible follower completion, AUTO never
  engaging, and AUTO sticking on. Log: `build/r7shadow2-final-mutants.log`.
- Generated production envelopes are current; `bash -n tests/gate.sh` and
  `git diff --check` passed. These are source checks, not gate execution.
- Debug-info `sizeof` checks preserve all locks: Op 336, Client 1984, ThreadCtx
  1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624.
  ModeScheduleStats remains 64. Log: `build/r7shadow2-final-layouts.log`.
  GDB received only type queries, never run/start/attach.

The main final build/check commands were:

```sh
taskset -c 112-127 make -j8 all build/tomokv-pad build/reorder-engagement-unit build/r7shadow-unit-asan build/netcmd-unit build/r7shadow-instr unit
taskset -c 112-127 python3 tests/r7shadow_noop.py build/r7shadow2-pre/build/tomokv build/tomokv build/r7shadow2-final-off-witness
taskset -c 112-127 ./build/reorder-engagement-unit on shadow
taskset -c 112-127 python3 tests/r7shadow_pad.py build/reorder-engagement-unit build/r7shadow2-engagement-pad --scope fifo --receipt build/r7shadow2-engagement-pad.json
taskset -c 112-127 ./build/r7shadow2-engagement-pad off shadow
taskset -c 112-127 ./build/netcmd-unit config
taskset -c 112-127 ./build/r7shadow-unit-asan
taskset -c 112-127 python3 tests/r7shadow_mutants.py
taskset -c 112-127 python3 tests/r7shadow_sync.py
```

No gate row was added or retired. `tests/gate.sh` is unchanged:
`EXPECT_QUICK=419` at line 254, `EXPECT_FULL=435` at line 255, quick exit at line
2764. **Counts stay 419/435.** Added cases live in existing unit binaries.

## Mainline measurement request — do not run in this lane

Use the gate's existing ABBA instrument for **h07/h23 rates**. Keep their current
pins, population and offered-load rungs: GET, p32, 512 connections, read-local=0,
overlap=1, atomics/key-lb/client-lb armed. h07 is 1s; h23 is 2s. Compare POST and
kind-A PAD against the current v7 reference, and against round-1 PRE to attribute
the bookkeeping change. Preserve the ordinary off controls h05/h21. Record rate,
cycles/op, instr/op and IPC per version; use matched-load rate as the verdict.
For POST, h23's requested reorder=1 must resolve to FIFO via the capability field.
The current ABBA private-cell grammar accepts ro=0|1 only; do not label an override
as an AUTO rate cell without extending and verifying that instrument separately.

Required tailgen matrix, **each row with OFF / ON / AUTO / PAD A**:

| Mode | Offered ops/s | POST 0 | POST 1 | POST -1 | PAD A 1 |
| --- | ---: | --- | --- | --- | --- |
| 1s | 880000 | pending | pending | pending | pending |
| 1s | 985000 | pending | pending | pending | pending |
| 1s | 1030000 | pending | pending | pending | pending |
| 2s | 880000 | pending | pending | pending | pending |
| 2s | 985000 | pending | pending | pending | pending |
| 2s | 1030000 | pending | pending | pending | pending |

All 2s POST values select identical ordinary paths; those are explicit null arms.
Use `/home/user/Projects/calib/tailgen-run.sh` with its standing geometry: server
CPUs 0-31, 256 shards, 2M 64-byte GET keys, 65,536 256-KiB BITCOUNT keys, read-local=0,
overlap=1, atomic/key/client balancing armed; tailgen CPUs 84-111, 16 threads x
32 connections, Poisson GET:8,BITCOUNT:2, max outstanding 64. No lane runs these.

One-cell command forms (maintainer only; change mode/rate/label for every row):

```sh
TG_MODE=1s TG_INFO=SERVER /home/user/Projects/calib/tailgen-run.sh r7shadow2-off-985 /home/user/Projects/cx-r7shadow/build/tomokv 0 3 985000
TG_MODE=1s TG_INFO=SERVER /home/user/Projects/calib/tailgen-run.sh r7shadow2-on-985 /home/user/Projects/cx-r7shadow/build/tomokv 1 3 985000
TG_MODE=1s TG_INFO=SERVER /home/user/Projects/calib/tailgen-run.sh r7shadow2-auto-985 /home/user/Projects/cx-r7shadow/build/tomokv -1 3 985000
TG_MODE=1s TG_INFO=SERVER /home/user/Projects/calib/tailgen-run.sh r7shadow2-pad-985 /home/user/Projects/cx-r7shadow/build/tomokv-pad 1 3 985000
```

Interleave/balance arm order, match traffic seeds, and retain at least three paired
rounds. The command forms name individual arms; do not infer pairing from running
four whole blocks in the displayed order. Require increasing AUTO samples and an
engagement increase (or an already-engaged owner at the start) plus a permutation
increase during a purported active AUTO window. An AUTO run that never
engaged is reported as idle, not proof of a working promotion policy. Collect
INFO around the traffic window so population-phase engagements cannot satisfy it.

Decide with paired short.p999_ms and overall p999, reporting short/long p99 and
p999 alongside achieved load, per-class completions, mean/p50, outstanding maximum,
over-limit fraction, omitted arrivals, pacing lag and drain time. No lower achieved
load, omitted replies or long-class starvation counts as a gain. A credible fused
AUTO result preserves the demonstrated 985K/1030K benefit without regressing the
880K/null regime or h07 cost; compare with the per-cell standing null/spread.
2s ON/AUTO must be null against OFF; any repeatable separation is a defect or
instrument/placement issue, not an intended policy result.

The maintainer must still boot both modes, run `tests/gate.sh iteration`, and
judge GET/SET/MGET/MSET regression controls before merging. Append outcomes to
`MEASURE-RESULT`. This report makes no round-2 server performance claim.
