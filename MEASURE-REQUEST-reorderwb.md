TomoKV reorderwb — 2026-09-25

Verdict: **witness defect; R7 is unobserved in t05, not globally inert in 1s.**
The composite writeback rule does not disable the scheduler. The premise that R7
needs a RUNNING same-owner blocker is incorrect. In the failing armed workload,
clean GETs bypass the owner queues; BITCOUNT alone cannot supply a cost-class
permutation. No production scheduling or writeback change is justified by these
receipts. The instrument fix is commit **`a9e705d8b`**, on `cx-reorderwb`, based on
`32d27ee7562ed5a17ff889c0fe5cf250f3fdc63c`.

All builds and serverless checks used cores 112–127; make used `-j16`. No server,
load generator, benchmark, live control, or gate was run. Nothing was pushed.
Live validation of the new directed control remains with the maintainer. It
fails closed if its bounded fresh-state attempts never establish engagement.

**Read the diagnostic as an aborted comparison.**

`/home/user/Projects/endgame.log:7071` records the command, and `:7073` records the
t05 failure. `cx-final/build/reo-witness-t05.log` says `n=16 1:A`, then aborts;
there is no B t05 measurement. The receipt's reference is
`cx-nullrefresh/build/tomokv-nullrefresh-POST`, SHA-256
`77a5f58d5258544246bb3746ece88474c222368f068412f24dcb71a47eab925c`.
`cx-nullrefresh/MEASURE-REQUEST-nullrefresh.md:3` identifies that unchanged server
as `3e734cf2e`; its binary table at `:77` binds the same digest. Thus **the old
bytes failed too**. The fact that the earlier calibration stopped elsewhere did
not establish that t05 had passed there.

The failing measurement is
`/home/user/Projects/cx-final/build/reo-witness-t05/t05/n16-1-A/measurement.json`,
SHA-256 `ee9229aea0385cd56b79c5d16b238cecce4c453cc663322e9cc249ea0508d307`.
Its retained facts are:

| Fact | Observed value |
|---|---:|
| Server geometry | physical 1s, 32 threads, 256 shards, rl=1, ov=1, ro=1 |
| Loader geometry | 16 instances, 512 total connections, p8 |
| Central command rate | 716,743.01/s |
| Legacy busy / process CPU | 11.1108% / 17.1876% |
| Read-local hits delta | 11,468,850 |
| Read-local fallbacks delta | 14, all sequence churn |
| Blocker population | 65,536 × 262,144 bytes = 16 GiB |
| Preparatory BITCOUNT service sample | median 10 microseconds |
| Scored permutation observation | delta=0, reported by the raised witness |

The original instrument did not save its central INFO SERVER or COMMANDSTATS
endpoints before raising. Do not invent their absolute counts, a missing-opportunity
count, or a running-blocker count. `build/reorderwb-diagnostic.json` preserves the
compact extraction above. The fix saves both endpoint pairs before judging them
(`tests/abbagate.py:1538`, `:1588`).

t06 completed ABBA with reorder off on both binaries
(`endgame.log:7074`; `cx-final/build/reo-witness-t06.log`), but the short-tail
reference/candidate spreads were 2.2493%/2.3188%, with long-tail spread failures
as well. This is not valid evidence for a performance improvement. No t05
PRE/POST performance result exists from that session.

**1. Exact permutation and shadow conditions.**

`src/exec/op.h:32` has only Free, Issued, Done. There is no Running state and no
predicate that establishes that a handler is executing when IFID dispatches.
The implementation of ShadowDispatch is in `src/core/reorder.h:79`, instantiated
by the armed parser at `src/core/reorder.cc:2131`.

At parse-pass entry, ShadowDispatch scans the live older ROB interval backward
from `dispatch_id()` toward `flush_id()`, ignores Done, and remembers the newest
eligible **registered Long** (`reorder.h:92`). During the pass, an ordinary Long
updates that ID and a later ordinary non-Long task receives a distance/SHADOW
tag in its negative shard payload (`:107`). Issued/queued is sufficient. Neither
scan nor stamp checks the predecessor's owner. Different-owner and same-owner
predecessors both qualify. A completed predecessor can be stamped within a pass,
but selection refreshes the hint using only its Done/retirement state (`:62`,
`:387`, `:401`). Completion clears a shadow before IO retirement; retirement
also makes it irrelevant. No spin, retry, seqlock, or mutable predecessor reply
inspection is added.

The class byte is `CommandSpec::length_class`, read by
`src/cmd/command.h:162`: Point=0, SmallMulti=1, Long=2 (`:29`). Registry setup
stamps BITCOUNT and SETRANGE Long (`src/cmd/commands.cc:89`, `:158`). Armed
read-local raises ordinary write classes, so INCR becomes SmallMulti (`:107`).
Candidate ranking also conservatively raises an atomic-hazard task to Long
(`reorder.h:39`); that hazard **does not** manufacture a registered-Long shadow
predecessor (`:81`). Scatter/special tasks are barriers (`:19`, `:27`).

The enabled shadow scheduler selects connection heads from three FIFO ranks:
unshadowed non-Long, Long, shadowed non-Long (`reorder.h:298`, `:363`). It promotes
useful independent work across connections; it does not move a short ahead of
its own admitted predecessor. A queued own Long is selected first; a shadowed
short on another owner can wait behind other useful work. Ready-head activation
and bounded oldest-task turns retain the admitted connection order and fairness
(`:379`, `:414`, `:427`).

The actual counted event is **any selected node other than the oldest queued
node**, `witness = ReorderResult{1,1}` (`reorder.h:424`). This is at most one
permutation witness per emitted span, not one per displaced operation, Long,
connection, or parse pass. `r7_drain_tasks_impl` records it before execution
(`reorder.cc:64`); `ModeScheduleStats::note_reorder` adds it to the per-thread
counter (`src/core/orthog.h:48`). INFO sums those counters (`reorder.cc:19`).
The older non-shadow two-queue policy has its separate exact pick witness at
`reorder.h:203`; normal release `shadow_available()` is true (`reorder.cc:16`).

For an empty scheduler, one-client or homogeneous unshadowed-class runs bypass
the queues with a zero witness (`reorder.h:452`, especially `:472`). Mixed work
must share an owner's gathered scope, survive barriers, and actually change a
pick to count. An already priority-ordered mixed scope can also have zero.
`reorder_multi_client_runs` is set by the same shadow non-oldest pick; it is not
an independent opportunity counter. `reorder_batches` proves traversal, not an
opportunity. No running Long is necessary for an ordinary cross-client
short-before-queued-Long permutation, and a running Long alone is not sufficient.

**2. What the composite can change, and the dominant t05 distinction.**

The production changes in `6a234de1f..a2bf90a7c` affect PHASE 2, its physical-mode
template plumbing, and the old fused connection allowance. `reorder.h`, registry
classification, the parser body, owner queues, and the counter update are unchanged
between `3e734cf2e` and `32d27ee75`.

The exact policy serves ordinarily for `in_flight <= 1`, or sufficient staged
bytes, or a contiguous **Done but not yet retired** prefix reaching bytes/ceil-half
(`src/core/wb_rule.h:49`). This is slightly more precise than "nothing in flight"
or "retired prefix". Deferred entries rotate with their pin retained (`:80`),
and pending work prevents parking (`:126`).

Candidate (a): there is no direct parse veto tied to PHASE 2 deferral. PHASE 1
visits active connections first (`reorder.cc:1093`), reparses available input
(`:1193`), and preserves active/stuck connections (`:1246`). Fused execution and
completion collection follow (`:1288`), then composite serving (`:1318`). A
deferred connection remains pending/active. Serving can indirectly change when
ROB capacity becomes free and when later requests are parsed; it cannot erase
already admitted owner work or introduce a Running prerequisite.

Candidate (b): reply coalescing can change closed-loop client arrivals and hence
batch composition. This is a possible timing effect, not established as the cause
by these receipts. At t05's fixed 716,800/s offer, below saturation, and p8 below
the 64-slot ROB window, it is particularly unsafe to infer a scheduler regression
from the absence of a pick.

Candidate (c): rejected as a direct mechanism. The counter is recorded by owner
queue emission, before the handlers execute, not by serve/WB or its connection
budget (`reorder.cc:64`, `:1288`). The composite does not remove that path.

The concrete distinction is **rl=1**. An eligible GET publishes to the local
read lane and continues before Task creation/stamping/posting
(`reorder.cc:3402` through `:3440`, versus `:3479`). BITCOUNT is not
ReadLocalEligible (`src/cmd/t_string.cc:1433`). Thus an 8:2 wire mix is not an
8:2 owner-queue mix. The retained 11,468,850 local hits with only 14 fallbacks
support a nearly homogeneous Long owner population. They do not prove that no
Long was ever executing, or that no mixed opportunity occurred. **Unobserved** is
the defensible classification, not a fabricated zero-opportunity proof.

**3. Inertness and the Window6 result.**

Physical 1s still boots into the R7 runtime when enabled (`reorder.cc:3821`),
binds its armed local-read demotion callback (`:785`), drains the shadow queues
(`:43`, `:87`), and runs that execution phase before composite serving. Current
serverless production engagement checks pass with rl=1 and ov=0/1, including
parser stamping, cross-owner/pass shadows, demotion, and the idle sweep, in both
database namespaces. This refutes global 1s inertness. It does not measure how
often a particular live load engages, or certify retention of a tail percentage.

The supplied Window6 composition result is compatible with this: its saved
`build/drainall/burst91r-w6-both12-r1-1-PRE/manifest.json` under `cx-drainall-test`
explicitly runs **read-local=0, reorder=1**, 32 server cores, 512 connections,
16 loader threads, and the burst generator. Both GET and BITCOUNT therefore reach
owner execution. The mean offer is 930,000/s (observed 930,998/s, conventionally
931K), with 100 ms at twice the rate alternating with 100 ms off, max outstanding
64. That differs materially from the armed, rate-limited p8 t05.

There is also a units mismatch in the launch description: this saved driver
populates **256 KiB per blocker, 16 GiB total**, not 16 MiB per blocker
(`cx-drainall-test/tools/drainall_measure.py:166`). The directed engagement control
uses a 16 MiB blocker; that is a different fixture. The commands below reproduce
the saved Window6 burst geometry. Its old PRE and W6 candidate binaries are not
identical to this lane's two reference binaries, so its gains are supporting
composition evidence, not a substitute for the requested recheck. Its driver
records send/rate/tail metrics, not a scored permutation counter.

**4. Witness fix and negative controls.**

`tests/abbagate.py:1288` now runs the existing bounded directed-control machinery
on each distinct modern binary used by an armed 1s REORDER cell. Both OFF and ON
boots keep read-local armed. CONFIG plus effective INFO identity must agree.
`tests/legacy_reorder_witness.py:204` and `:269` use a fresh numeric "0", an
earlier-dispatched SETRANGE key 0 1 (Long), and a later-dispatched INCR (SmallMulti).
INCR result/final value 1 proves the inversion; 2 proves ordinary order. These
are different clients at one stable producer/owner, with LB off only in this
unscored control. MONITOR proves exact admitted dispatch order; queue-full,
migration, extra writes, duplicates, changed clients, and MVCC state invalidate
the attempt. Sixteen fresh keys bound re-arming. Failure to open a window is red.

OFF must open an admitted window and never invert. ON must invert and increase
its available permutation counter. Missing/reset counters or an inert ON arm
fail. Successful receipts are cached only within the Runner, keyed by binary
digest/mode/read-local; failures cannot be retried into success. Artifact and
binary hashes travel with the workload evidence. The legacy unarmed GET control
retains its old protocol and missing-counter behavior.

`tests/abba_workloads.py:135` accepts delta=0 only for modern armed shadow 1s,
with a passing directed receipt and progressing scored scheduler batches. It
records the literal zero and says **"unobserved in scored window; directed armed
OFF/ON control passed"**. This is explicitly narrower than scored engagement.
It does not claim the batch counter counts opportunities. The unarmed t02/l9 ON
witness still requires a positive scored permutation delta. Disabled-mode,
missing-command, disappearing-counter, reset-counter, rate, accounting, load,
spread, and tail checks remain in force. No new server telemetry, hot-path work,
allocation, knob, layout change, or dispatch change was introduced.

The serverless negatives include an ON control that never inverts, an OFF
control that does invert, an unarmed window, missing ON telemetry, wrong final
value, duplicate/missing admissions, mode mismatch, and stalled/reset scored
counters. The transport simulator drives the real bounded protocol loop for both
GET and INCR controls; it does not replace their judgment functions. The added
real-scheduler test (`tests/r7shadow_unit.cc:64`) establishes pending Longs on two
clients and requires unchanged FIFO plus zero permutations. Existing three-pipe
tests establish permutations with Issued predecessors, without a running handler.

Five throwaway production-header defects fail their exact required assertions
(`tests/r7shadow_mutants.py:10`): remove the permutation counter; omit shadow
stamping; omit Done clearing; remove oldest-task fairness turns; omit successor
clearing. Crashes or an unexpectedly green control are not accepted. No altered
production source or altered server binary is committed.

| Serverless validation | Result |
|---|---:|
| `make -j16 all build/r7shadow-unit build/reorder-engagement-unit build/reorder-engagement-unit-db0` | built |
| `tests/abbagate.py --self-test` | 100 + 10 + 7 tests passed |
| `tests/legacy_reorder_witness.py --self-test` | 11 tests passed |
| Production engagement unit, `on shadow`, both namespaces | 30 + 30 PASS lines |
| Shadow unit including Long-only scope | 13 PASS lines |
| `tests/r7shadow_mutants.py` | 5/5 exact expected failures |
| `tests/r7shadow_sync.py`; `git diff --check` | passed |

Logs are `build/reorderwb-{build,abba-self-test,control-self-test,engagement,engagement-db0,shadow-unit,mutants,sync}.log`.
No gate rows were added/removed. `tests/gate.sh` and EXPECT_QUICK/EXPECT_FULL are
untouched; their counts should remain unchanged. `tests/reorderwb_cells.txt` is a
separate six-cell diagnostic inventory.

**Artifacts and PRE/POST boundary.**

PRE here means the older pre-composite server, POST the composite reference under
investigation. The witness patch itself leaves the server bytes unchanged. PRE
is a frozen copy of the exact diagnostic A binary, not a newly relinked estimate
of it. POST was built in this worktree and frozen. `build/reorderwb-binaries.json`
binds the files and .text sections. No new performance PAD is needed for this
instrument-only patch; no PAD arm is requested.

| Artifact | SHA-256 |
|---|---|
| `build/tomokv` and `build/tomokv-reorderwb-POST` | `2e00e82d8a96c6b53b0f0bd78547b3a3e005948175a1b20c9d3bc77d6c7ecb5f` |
| `build/tomokv-reorderwb-PRE` | `77a5f58d5258544246bb3746ece88474c222368f068412f24dcb71a47eab925c` |
| Diagnostic B, mainline new bytes | `39665db02bfb147bb33866d47962aeae37ebe648fe51312dbc8bcaba346c3d7d` |

POST .text is **byte-for-byte identical** to diagnostic B: 7,550,604 bytes,
SHA-256 `926d6e62b1aebb66491fec3d4393cde140904e41bc19ce4536153cf650521587`.
PRE .text is 7,445,436 bytes,
SHA-256 `fca3ad2635d76f685a086f6f86f2e23741db0d4744a237574747973d1f1f7fdc`.
Different complete binary digests are not silently treated as identical files.

**Maintainer measurement request — not executed by this lane.**

Run on the scheduled quiet box. This request uses the established measurement
geometry, server 0–31 / loaders 32–111; coding/build checks above used 112–127.
Use the fixed witness instrument for both binaries and preserve all failed
controls/receipts. Refresh the instrument fingerprint/calibration receipt before
using these results as a standing gate baseline.

```sh
cd /home/user/Projects/cx-reorderwb
LANE="$PWD"
MEASURE_RUN=$(mktemp -d "$LANE/build/reorderwb-mainline.XXXXXX")
PRE="$LANE/build/tomokv-reorderwb-PRE"
POST="$LANE/build/tomokv-reorderwb-POST"
sha256sum "$PRE" "$POST"

# t05 is reorder=1; t06 is the exact same geometry with reorder=0.
# Both binaries run in each ABBA cell. The armed OFF/ON controls run automatically.
taskset -c 0-111 python3 tests/abbagate.py \
  --cells tests/reorderwb_cells.txt --only t05,t06 \
  --candidate-binary "$POST" --reference-binary "$PRE" --build-reference 0 \
  --server-cores 0-31 --load-cores 32-111 --load-smt '' --ports 7933-7940 \
  --output "$MEASURE_RUN/t05-t06"

# Exact historical l9 rows plus ON companions, to establish scored owner engagement.
taskset -c 0-111 python3 tests/abbagate.py \
  --cells tests/reorderwb_cells.txt --only l9_8,l9_32,l9_8_on,l9_32_on \
  --candidate-binary "$POST" --reference-binary "$PRE" --build-reference 0 \
  --server-cores 0-31 --load-cores 32-111 --load-smt '' --ports 7933-7940 \
  --output "$MEASURE_RUN/l9"

# Reproduce the saved 9:1 Window6 burst: raw offer 930000, observed about 931K.
# Run ON as required and OFF as the matched behavioral control, two ABBA rounds.
# This existing driver resolves its burst-generator path from cx-drainall-test.
cd /home/user/Projects/cx-drainall-test
for reorder in 0 1; do
  for round in 1 2; do
    sequence=0
    for arm in PRE POST POST PRE; do
      sequence=$((sequence + 1))
      case "$arm" in PRE) binary="$PRE";; POST) binary="$POST";; esac
      taskset -c 0-111 python3 tools/drainall_measure.py \
        --stage burst --mix GET:9,BITCOUNT:1 --reorder "$reorder" \
        --binary "$binary" --mode 1s --rate 930000 --seed 1 --databases 1 \
        --server-cpus 0-31 --load-cpus 32-111 --port 7933 --warmup 5 --duration 20 \
        --out "$MEASURE_RUN/burst-r${reorder}-${round}-${sequence}-${arm}"
    done
  done
done
```

The t05 acceptance decision is: both exact binaries pass the independent armed
OFF/ON control; commands and scheduler batches progress; zero scored permutations
are reported as unobserved, never as engagement. If a control cannot open its
window, stop and inspect it; do not waive it. The l9 ON rows must retain positive
scored permutation deltas and the OFF rows FIFO. Save all raw mode endpoints,
local hits/fallbacks, command accounting, and both short/long tails. None of these
counts alone certifies latency merit.

For burst merit, compare short p99/p99.9 and long p99.9 at the matched achieved
rate, separately for reorder OFF and ON. POST/ON versus PRE/ON decides whether
the composite still compounds with R7; ON versus OFF within each reference
checks the reorder benefit on that geometry. Preserve commands/send and any
gate-instrument cycles/op, instr/op and IPC; instructions alone are not a verdict.
Do not merge the burst and memtier histograms or accept unstable repeats as a
gain. Append results to `MEASURE-RESULT`; no performance win or live gate pass is
claimed by this report.
