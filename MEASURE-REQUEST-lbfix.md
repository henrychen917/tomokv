# lbfix: floored admission and deferred evidence

Reference: `705cddec205e30ff5d4a163f38e5db7949207050`, the HEAD of `cx-lbfix` at launch.
This reference differs from the landed `197e3d598` only in the gate reference pointer.
All edits and generated artifacts are inside `/home/user/Projects/cx-lbfix`. No push.

**Builds completed; runtime correctness and performance are not certified.** The task says
“PROOFS TO BUILD (the mainline runs them).” No server, benchmark, gate, unit proof, or negative
control was executed. The negative-control results below are explicitly pending mainline,
not claimed failures. Builds and offline binary inspection used `taskset -c 112-127`; builds
used `make -j16`. No gate count was edited.

## Confirmed diagnosis

Line numbers in this paragraph refer to the reference commit, not the candidate.

* C1: `src/core/weighted_lb.h:54-64` measures the absolute difference of successive
  imbalance levels, updates the quiet EWMA, and returns only `2*jitter`.
  `src/core/server.h:1221-1243` computes `(max-min)/mean * 100`, passes that level to
  the learner, and uses its band for both fire and 0.8 release. A constant nonzero
  level makes the adjacent difference zero, which is always learnable, so the band
  decays to zero. A plan with no candidate leaves its streak at three. The per-step
  tests at `server.h:1309-1312` repeat the same unbounded threshold. The minimum
  cooldown in `weighted_lb.h:89-95` is one tick, shorter than three-tick admission.
* C2: `server.h:1197` folds before admission at `server.h:1303`. The fold at
  `server.h:517-541`, dominant-bucket walk at `1258-1264`, weight/byte walks called
  at `1269-1270`, and cooldown walk at `1273-1279` traverse five bucket arrays when
  nothing is cooling. The `last_move` assignment at `1258` allocates and copies
  16384 eight-byte timestamps under the signal mutex. One detail of the diagnosis
  needs precision: `lb_shard_weight` takes a mutex per shard; `lb_shard_bytes` does
  not. The reference therefore takes about `nshards + 2` signal-lock round trips,
  not two locks per shard. Both bucket walks are still repeated per shard.
  `server.h:733-738` elects the first Ifid, tid 0 at the gate geometry, and
  `src/core/io_loop.h:637-645` runs the beat in the serving loop. Fused placement
  makes all threads Ifid (`src/core/placement.h:57-61`).

These mechanisms explain needless admission and work on the serving IO thread. This lane
did not measure causality for the production CPU/churn symptom.

## Candidate behavior and derivation

`LbAutotune::sampling_floor` in `src/core/weighted_lb.h` derives a percentage from the
existing decision budget, `N = kSamplesPerDecision = 4096`, and the actual owner count M.
Under balanced sampling, each owner has expected count N/M. A fixed pair's difference
has variance 2N/M, so the difference divided by the mean has standard error
`sqrt(2M/N)`. Start with flipctl's two-error margin. Since max/min selects among
`P = M(M-1)/2` pairs, account for that selection with `z² = 4 + 2 ln(P)` (the
Gaussian tail-bound factor P cancels the added exponent). Thus:

```
floor_pct = 100 * sqrt((4 + 2*ln(P)) * 2*M/N)
band_pct  = max(2*jitter, floor_pct)
```

The floor is 6.25% for the gate's two split owners and 20.410254% for eight fused
owners. It is a sampling-resolution floor, not a machine-specific percentage or a
confidence guarantee for correlated samples. Sparse traffic or unusual multi-key/retry
mixes need the live validation below; the target sample budget is not an observed count.
Measured jitter can widen the floor. Quiet-level learning and the existing excursion
exclusion remain; an imbalance step cannot teach itself a wider admission threshold.

The controller uses this same owner-count-aware band at admission, the dominant-bucket
veto, and every incremental demand/byte step. An admitted attempt consumes its streak
before gathering, including no-improvement, cooldown and indivisible candidates; client
attempts do the same. Minimum cooldown now covers one whole three-tick decision window.

The cheap fold reads existing `Shard::stats().ops` counters with the existing relaxed
read convention and keeps three tick rates per physical shard. The admission byte
signal reads `published_obj_bytes()`. Histories stay attached to physical shards across
moves. The sampling-rate estimator uses shard executions as a cheap **proxy** for key
visits, rather than doing a bucket census to tune itself. Multi-key fragments can yield
more key visits per execution, and retries can do the reverse. The request-path sampler,
latched rate weighting, countdown and owner byte-census cadence are unchanged. Include
the multi-key cells below to check the achieved cost of this proxy; no sampling-rate
accuracy claim is inferred from the uniform unit fixtures.

Detailed bucket data is still the planner's evidence. `Server::lb_gather_key_evidence`
is reached only after sustained key admission, or by an already-admitted FLIP shard plan.
It folds sampled demand, sums shard demand/bytes, finds the dominant bucket and reads
cooldown timestamps in **one bucket pass under one signal lock**. Rates are normalized
by elapsed time since the previous detailed gather, and EWMA retention is
`pow(0.75, elapsed_ticks)`, so deferred samples are not mistaken for a one-tick burst.

The cooldown table is now `nshards` entries, not `kNumBuckets`; a whole physical shard
is the transfer unit. Both successful commit (`server.h`) and refused/expired shard
plans (`lbstall.cc`) update the same per-shard timestamp. There is no vector copy.
FLIP uses the same gather, removing its repeated weight/byte walks too. Client admission
reads the existing owner-weight publications; the client map and candidate vector are
visited only after client admission.

An admitted gather can legitimately find **no executable move**. The no-gather assertion
means a tick rejected by admission does no full-bucket gather, not that the planner can
know its eventual result without collecting evidence. A stationary uniform suffix must
have neither admission gathers nor moves.

| Work on a quiet controller tick | PRE | POST |
| --- | --- | --- |
| Full bucket-array passes before key admission | 5 | 0 |
| Full bucket passes when key planning is admitted | 5 overall | 1 overall |
| Copied last-move timestamps | 128 KiB | 0 |
| Last-move table at 16 shards | 128 KiB | 128 B |
| Per-shard admission history | none | 16 × 40 B, in LB-only heap state |
| Signal-lock acquisitions on a quiet tick | about nshards + 2, plus client gather | 2 total |
| Quiet tick time complexity | O(16384 + clients + threads) | O(shards + threads) |
| New per-operation stores, atomics, locks, epochs | — | 0 |

POST still takes the transition admission lock, folds O(shards + threads) counters,
builds the small owner-id vectors, aggregates O(shards) publications under a second
signal lock, checks hysteresis and updates cold telemetry. It makes no candidate
allocation, bucket walk, 128 KiB copy, or client-map walk without admission. The existing
owner-id vectors can allocate; this is not an allocation-free-tick claim. When both LB
knobs are zero, no LB policy or new window is allocated. Client-only mode leaves the
new shard vector empty.

The source read side is const: the controller changes only its own histories and cold
counters, never owner samples, objects or expiry state. The existing owner byte census
retains `/*expire_on_visit=*/false` in `Shard::lb_scan_bucket_bytes`. The proof plants
an actually expired object, proves the census callback visits it, checks preservation,
then proves an ordinary owner lookup really expires it.

**Router owner half-word: skipped.** There is one external reader in the conservation
check, but `Router::begin_transfer` also validates the source against these entries
(`src/core/shard.h:624-629`). Deletion would require reworking that validation and the
three-phase representation. It is not needed for C1/C2. Router, per-key routing,
`Idle -> IoDrain -> ExDrain -> commit`, producer drains, and ownership installation are
unchanged. No DatabaseMap handshake, reader retry, seqlock or in-place-write rule changed.
The locked Op/Client/ThreadCtx/Shard/FlatStore/ROB/AtomicEntry/Config layouts still compile.

## Proofs built for mainline

The existing `core concurrency route` selection now includes the directed LB cases in
`tests/core_concurrency_unit.cc`. All run split 16-shard 6:2 geometry and fused eight-owner
geometry, except the arithmetic-only floor case, which covers 2, 8 and 64 owners. They
open no listener, run no server loop and use no sleeps. Every hazardous state is asserted.

| Assertion / standalone selector | Negative control | Actual result |
| --- | --- | --- |
| (a) `lbfix-stationary`: 96 ticks of nonzero stationary residual produce no plan; learner is primed and jitter has decayed. A tiny movable shard makes removing the floor actionable. | `no-floor`: return `2*jitter` | Built; execution pending mainline (expect assertion failure) |
| (a,b) `lbfix-hot`: after 96 quiet ticks, induce a hot physical shard; plan and commit within 9 ticks. Allow 96 settling ticks, then require a 48-tick zero-move suffix. | `no-hot`: suppress key controller admission | Built; execution pending mainline (expect bounded-fire assertion failure) |
| (c) `lbfix-floor`: 256 constant-level observations for each owner count; band >= independently calculated floor even when jitter == 0. Also require a full-window cooldown. | `no-floor` | Built; execution pending mainline (expect floor assertion failure) |
| (d) `lbfix-gather`: 96 non-admitted ticks leave gather count and both bucket-history arrays unchanged. Then a hot input must advance the witness and sample fold. | `eager-gather`: gather immediately after cheap fold, before admission | Built; execution pending mainline (expect zero-gather assertion failure) |
| (e) `lbfix-read-only`: expired sentinel, completed census, full evidence gather, unchanged object/TTL/bytes/owner counter, followed by an ordinary lookup that expires it | `census-expiry`: enable expire-on-visit; independently `fold-expiry`: add a mutating store scan to the evidence gather | Both built; executions pending mainline (expect preservation/visit assertion failure) |
| `lbfix-no-move`: indivisible shard admits no beneficial move, consumes streak, waits two ticks, and reconsiders on the third | `no-reset`: remove the attempt's streak reset | Built; execution pending mainline (expect streak assertion failure) |
| `lbfix-step`: cheap evidence admits planning, detailed evidence has a small movable residual below the floor, and no move occurs | `step-no-floor`: use raw jitter only in the per-step tests | Built; execution pending mainline (expect no-move assertion failure) |

There are seven negative binaries; `no-floor` is exercised by two independent selectors.
Mutations are written only beneath `build/lbfix-controls/` by `tools/lbfix_artifacts.py`.
They are compile-time throwaways, not production options. `build/lbfix-controls.json`
lists every binary, selector and expected exit code; a build success is not a successful
negative control. Require the intended `FAIL core concurrency:` assertion and exit 1,
not an ASAN startup error or an unrelated sanitizer failure.

Built artifacts:

* `build/core-concurrency-unit`: existing ASAN/UBSAN fixture linked with release libraries,
  matching the existing Makefile target's instrumentation scope.
* `build/lbfix-tsan/unit`: all unit dependencies rebuilt with TSan and uniform test hooks,
  without jemalloc, matching the gate's full-dependency instrumentation approach.
* `build/config-parser-test`: updated floor/cooldown expectations in the existing unit.
* All seven `build/lbfix-controls/<control>/unit` ASAN/UBSAN negative binaries.

Mainline proof commands (use its scheduled quiet box; the examples keep this lane's affinity):

```sh
taskset -c 112-127 ./build/config-parser-test
ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 taskset -c 112-127 ./build/core-concurrency-unit route
taskset -c 112-127 setarch x86_64 -R ./build/lbfix-tsan/unit route
```

Also run the existing `watch lifetime drain snapshot config notify` selections with both
instruments, each negative binary with its listed selector, the live `lbsignals` battery
in both thread modes, and the normal iteration gate. `tests/lbsignals.py` now requires
the `tomokv_keylb_bucket_gathers` INFO field and zero gathers when key-lb is disabled.
Directed arming of the counter is in the route row, not an unprovable live assertion.

**Gate ledger: unchanged, quick 438 / full 454.** The core selection loop is at
`tests/gate.sh:1242`; the `lbsignals` collection is at line 1615. Both are before the
quick-tier exit at line 2812. This change extends existing rows; it adds/removes none.
`EXPECT_QUICK` / `EXPECT_FULL` were not edited.

Rebuild artifact inputs after rebuilding release objects:

```sh
taskset -c 112-127 python3 tools/lbfix_artifacts.py
taskset -c 112-127 make -j16 -f build/lbfix-artifacts.mk lbfix-controls lbfix-tsan lbfix-pad
```

## Measurement arms and verdict

| Arm | Binary / settings | Purpose |
| --- | --- | --- |
| PRE | `build/lbfix-pre/tomokv`, key-lb=1 | exact launch reference |
| POST | `build/tomokv`, key-lb=1 | candidate |
| PAD | `build/tomokv-lbfix-pad`, key-lb=1 | **A: behavior twin — PRE behavior with POST .text size** |
| OFF-PRE | PRE, key-lb=0 | reference cost baseline |
| OFF-POST | POST, key-lb=0 | detect unrelated code-generation cost |

PAD appends unused NOP bytes to PRE. Offline checks require PRE's entire .text to be a
byte-identical prefix of PAD, matching CET properties and text base, and PAD's .text
size to equal POST. It controls text extent, **not POST's internal function addresses or
new cold heap allocations**. It is not an exact internal-layout twin. No inverse-control
arm is requested: the candidate's total text increase is only 192 bytes.

Use the gate geometry first: `--shards 16 --ratio $GATE_RATIO`, `GATE_CORES` (default 0-7),
both `--thread-mode 1s` and `2s`, fixed role split/flip-auto off. Mainline owns all launches
and offered-load calibration. Keep other settings identical. First isolate key LB with
client-lb=0; repeat GET and mixed cells with client-lb=1 (production defaults).

Cells per mode: GET, SET and 50:50 GET/SET; pipeline depths 1 and 128; 128 persistent
connections; 64-byte values; one million prepopulated uniformly selected keys. Also run
8-key MGET and 8-key MSET at both depths with the same per-key population and value size
to check the execution-count sampling proxy. Reuse the gate's own client/instrument and
25GbE two-netns rig for write/send-path conclusions. No ad-hoc timing harness.

For each cell: 60 seconds fixed-load warmup, then 180 seconds observation, ABBA arm order.
Choose one offered load at 75% of the OFF-PRE sustainable rate for that cell and hold it
identical across arms. Also collect the instrument's saturation-throughput cell; matched
load alone can hide spare-capacity regressions. Record completed rate, cycles/op, IPC,
instructions/op, p99 and p99.9, per-thread CPU, `lb_bucket_moves`, and admitted gathers.

**The stationary-load assertion is `lb_bucket_moves == 0` after stabilization:** the
measured suffix must contain exactly zero shard moves (zero delta of
`tomokv_keylb_bucket_moves` across that suffix), with **NO throughput or tail loss versus
`--key-lb 0`**. Do not accept “fewer moves” or a percentage tolerance on the move count.
For the uniform stationary case, require zero delta of `tomokv_keylb_bucket_gathers` too.
No periodic full-gather CPU spike should remain on tid 0 in that suffix.

After the stationary cell, keep aggregate offered load fixed and give one physical shard
37.5% of key visits, distributing them across many buckets so no single bucket carries
half of all traffic. Place it on an already-loaded owner. Require a beneficial plan within
9 controller ticks, drain/commit progress, and then a zero-move suffix after settling.
Check both thread modes. A single dominant key is intentionally a refused, indivisible
case; relocating that bottleneck is not a successful hot-shard proof.

The always-on machinery must remain <=3% versus OFF, and any repeatable main-command rate
or tail regression rejects the candidate even inside that ceiling. PRE/PAD staying flat
while POST improves is supporting evidence for a real controller gain; all claims still
need cycles/op = instructions/op / IPC and matched-load rate/tail evidence.

| Performance result | PRE | POST | PAD / OFF |
| --- | --- | --- | --- |
| Rate, cycles/op, instructions/op, IPC, p99, p99.9 | Not measured | Not measured | Not measured |
| Stationary move/gather suffix | Not run | Not run | Not run |
| <=3% always-on acceptance | Pending mainline | Pending mainline | Pending mainline |

Offline release-object audit: 827/847 selected function bodies match after resolving
relocations. GET/SET command bodies match in both database variants (four bodies). Twenty selected functions differ, including
IO run/flush/TLS paths, two R7 pipeline instantiations, and one read-local erase body;
some equal-size differences are assertion locations. See `build/lbfix-hot-bodies.json`
and `.log`. This is **not** a full byte-identity pass or a zero-regression performance
claim. No request-path source instrumentation was added, but compiler decisions changed.

## Artifact identity and diff

Release source commit: `cb89d97f5` (plus the earlier artifact/proof commits listed by `git log`).
The report commit adds documentation only.

```text
9a5382cd6b5721c04f3320c07bdfa058d1b6b7a2dd00c74aebd528c8b76e9838  build/lbfix-pre/tomokv
1673bc13549b0bdf50f3cf46ca241c54e8475ec33b021020ab13b88e11c90b71  build/tomokv
ab1d7ce47b9e571d21020debc177ea009e5db3e1441639eb7ad6337ca1055d85  build/tomokv-lbfix-pad
```

`sha256sum build/tomokv` is the POST line above. Build logs: `build/lbfix-pre-build.log`,
`build/lbfix-final-build.log`, `build/lbfix-artifacts-final-build.log`. Release, ASAN/UBSAN
unit, config-unit, full TSan unit and all negative-control **builds** succeeded. Python
syntax checks and offline PAD/CET checks succeeded. Runtime proof results remain pending.

```text
$ git diff 705cddec205e30ff5d4a163f38e5db7949207050 --stat
 MEASURE-REQUEST-lbfix.md       | 281 +++++++++++++++++++++++++++++++++++++
 src/cmd/lbsignals.cc           |   1 +
 src/core/lbstall.cc            |   7 +-
 src/core/server.h              | 304 +++++++++++++++++++++++------------------
 src/core/weighted_lb.h         |  36 ++++-
 tests/config_parser_test.cc    |   6 +-
 tests/core_concurrency_unit.cc | 210 +++++++++++++++++++++++++++-
 tests/lbsignals.py             |  10 ++
 tools/lbfix_artifacts.py       | 157 +++++++++++++++++++++
 9 files changed, 869 insertions(+), 143 deletions(-)
```
