Lane lbplanner — CT1, CT2, CT3 — 2026-10-04

**Implementation and serverless proofs complete; mainline measurements pending.**
CT1–CT3, the hand-off gate row, PRE/POST binaries and the mandatory **PAD-A
behaviour twin** are committed. POST/PAD have identical complete function and
section tables; all bytes outside the recorded retargets are identical. The
hand-off, restored PRE behaviour, negative controls and instruction receipts
pass. No throughput, cycles/op, latency, convergence or live-gate result is
claimed. Mainline owns those acceptance checks before landing.

Worktree/branch: `/home/user/Projects/cx-lbplanner`, `cx-lbplanner`. Initial launch
HEAD was `12fe9f8ad`; the required first fetch/merge fast-forwarded to
`cd02ecbab1502775f1c170e806971d1f7bbc3ee9`. That synchronized commit is PRE.
Implementation/proof commits: `c8bb410da`, `5d5d97c62`, `51ee76982`. Nothing was pushed. No server,
benchmark, gate, or live test was run. Builds, serverless witnesses, ptrace
instruction counting and binary inspection used CPUs 112–127.

The defects and change

The scope is section C of `/home/user/Projects/round3-read/controllers.md`,
REGISTER TIER 1 #2/#19 and the always-on controller law. On synchronized PRE:

| Item | PRE anchor | Change |
|---|---|---|
| CT1 | `src/core/io_loop.h:654-662`, generated `src/core/reorder.cc:946-954`; `src/core/server.h:1273-1532` | Admission, gather, allocations and complete search run on the existing main/monitor thread. IO consumes a finished result. |
| CT2 | `src/core/io_loop.h:1833-1836,2965-2966`; `src/core/server.h:832-837` | One shared acquire in the IO control tail; subsequent connection parse gates read an IO-private cached pause ID. |
| CT3 | `src/core/server.h:1394`; `src/core/weighted_lb.h:117-128` | Read `move_cap(nshards())` once before the step loop. |

The implementation is in `src/core/lbplanner.cc`. The existing boot paths in
`main.cc`, `genthread.cc`, `rl2s.cc`, and the regenerated R7 envelope all call
`Server::monitor_controllers()`. LB retains its one-second cadence; FLIP retains
its own `flipctl_wait_ms()` deadline. Multi-DB supervision can wake the monitor
at `Ring::kWaitTimeoutMs` without sampling either controller more frequently.
The monitor also exits when a worker's stop flag records a failed boot.

This chooses the monitor over sliced IO computation because the whole
item × destination × owner search, including allocation and reclamation, leaves
connection service. Its work remains proportional to the configured shard,
owner and connection counts. There is no new budget knob or machine constant.
Observation windows, sampling density, Schmitt band, three-tick streak,
per-item cooldown, dominant-bucket refusal, count constraint, objective and
key/client preference rule are retained. CT4/CT5/CT6 are unchanged.

`PlanReady` (stage value 5) is published through the existing `lb_stage_` word.
It does not pause dispatch. A cold slot owns IDs, scalar evidence and the shard
move vector; it is allocated only when either balancer is enabled. A short
shape lock captures roles and both LB/FLIP generations. Gather rechecks the
generations, search holds neither the shape lock nor the signal lock, and
publication rechecks them again. Only the designated IO coordinator can consume
under a try-lock. A changed generation, active shape transition, snapshot or
load drops the plan before starting a drain. A coordinator that became EX is
rejected before folding; otherwise its ready plan could be stranded forever.

Consumption swaps vector ownership; previous storage returns to the monitor
for reclamation. It starts the unchanged IO/EX or client drain and starts the
existing move timeout at that point, as PRE did after search. The monitor
cannot overwrite a pending slot. The shape lock serializes consumption and
explicit FLIP cancellation. Shard transfer, per-owner state adoption, QSBR,
record replacement, ROB ordering and client readiness fences are unchanged.

The tail caches the pause decision for the *next* parse/post pass. When a drain
appears during a pass, that pass publishes its old-route work before its tail
acknowledges IO drain. The next pass is already cached as paused before EX drain
can open. The cache uses the former IO cron deadline's eight bytes, so no IO
member moves. Client refusal clears that cache immediately; the existing
continuous-arrival witness requires the same buffered frames to resume.
The client-ID operand is evaluated only inside the nonzero-cache branch.

The zero-allocation witness covers **plan consumption and retired plan storage**.
Existing client-observation publication and actuator capacity preflight remain
unchanged; this is not a claim that all networking, signals or migration code
allocates nothing. Manual FLIP's separate gather is also unchanged.

Cycles/op argument and receipts

For N connections in an otherwise idle-stage IO pass:

| Work | PRE | POST |
|---|---:|---:|
| Shared LB-stage loads | N + 1 | 1 |
| Private cached gate loads | 0 | N |
| Cache publication by the IO owner | none | one store per pass |
| Planner search/temporary-vector allocation on serving IO | on admitted beats | none |
| Repeated cap reads within search | up to two atomics per loop-condition evaluation | one cap evaluation before the loop |

There is no new per-operation shared producer store. Ready-stage publication is
an admitted-plan event. The cache store belongs to the serving IO and replaces
no locked layout or peer publication line. This is a load/branch/hosting argument,
not measured RFO or IPC evidence. Stable-load verdicts must still be null inside
the same-binary bands, especially given the changed code placement.

[Instruction receipt](docs/lbplanner/instructions.json), produced by
`tools/lbplanner_receipts.py`, single-steps a serverless fixture through the real
IO control tail and repeated isolated production parse gates. LB stage is pinned
to Idle. PRE compiles the corresponding code from synchronized PRE source.
Both fixtures use the same noinline gate boundary; these counts include that
fixture boundary and **are not whole-command instr/op**. No perf events or wall
rate were measured.

| Connections/pass | PRE retired instructions | POST retired instructions | PRE shared loads | POST shared loads | POST private loads |
|---:|---:|---:|---:|---:|---:|
| 1 | 77 | 73 | 2 | 1 | 1 |
| 32 | 852 | 507 | 33 | 1 | 32 |
| 4096 | 102452 | 57403 | 4097 | 1 | 4096 |

The negative fixture restores a per-connection stage acquire: shared-load
counts become 2, 33 and 4097. PAD-A independently restores those same shared-load
counts (87 / 893 / 106557 retired fixture instructions) with no cached parse
loads. The receipt records each retired load's instruction
address and disassembly. Source checks cover both ordinary and R7 parsers,
all four boot hosts, the cap hoist, independent controller deadlines, unchanged
`weighted_lb.h`, and exact normalized admission/search blocks. See
[source.json](docs/lbplanner/source.json).

`cycles/op = instr/op / IPC`; the fixture cannot supply IPC or cycle merit.
Mainline must collect rate, cycles/op, instructions/op and IPC at matched offered
and achieved load, with productive occupancy alongside them. Whole-process spin
must not be presented as command instruction cost.

Proofs actually run

| Proof | Result |
|---|---|
| `build/lbplanner-unit` | Both thread modes, key and client branches; real monitor thread publishes and IO tail consumes before monitor join; duplicate consumption rejected; both stale epochs dropped; zero IO new/delete calls; disabled state absent; publication-tail pause fence; invalid coordinator refused before fold |
| Five hand-off mutants | No publication, ignored FLIP generation, ignored LB generation, duplicate success, and IO copy/reclamation each fail their named assertion |
| `build/signalacct-core-unit route` | Pass, including existing LB policy, ownership, stalls, signal accounting, FLIP and lane regressions |
| Existing `lbfix` and `lbstall` selections | Pass; both modes refuse busy clients on the first tail with and without destination ACK |
| Legacy LB negative controls | All 16 prescribed failing invocations rejected their broken mechanisms |
| PAD-A behaviour | Both modes and branches: IO cron gathers/searches and allocates, directly publishes the PRE drain, retains the three-tick streak/deadline, and reads each connection's live stage; monitor performs no LB beat with FLIP off |
| PAD-A identity controls | Missing IO-tail, monitor or parser retarget, moved function symbol and unrelated byte change are each rejected; unpatched POST fails the PRE-behaviour witness |
| Source, shell and generated-envelope checks | Pass |
| GDB layout checks | All locks hold in both namespaces; every pre-existing Server/IO member offset preserved |

The scheduling relay in the hand-off witness is relaxed; the monitor remains
alive until consumption. The real mailbox acquisition/shape lock publishes the
payload. The negative no-publication arm must fail rather than skipping an
unarmed window. Stale-generation cases inject the corresponding generation
change at the hand-off boundary; existing route/LB witnesses separately execute
real quiesced ownership moves. The new hand-off binary uses release objects;
legacy negative controls instrument their unit/planner with ASAN/UBSAN. A fully
instrumented hand-off TSan run was not performed.

Logs and outcomes: [handoff.log](docs/lbplanner/handoff.log),
[handoff-controls.json](docs/lbplanner/handoff-controls.json),
[route-unit.log](docs/lbplanner/route-unit.log),
[lbfix-controls.json](docs/lbplanner/lbfix-controls.json).
The legacy negative generator was updated to compile the outlined planner from
its mutated overlay, rather than accidentally linking the unmodified planner.

All eight locks remain: Op 336, Client 1984, ThreadCtx 1408, Shard 1440,
FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. No checked sizeof moved.
Additional checks: IoLoop 7144 in both variants; Server 108672 (`tomo`) and
108288 (`tomo_db0`), also unchanged. The new pointer fits existing tail padding.
[Full layout receipt](docs/lbplanner/layout.json) contains both member inventories.

Frozen binaries and PAD-A proof

| Arm | Artifact | SHA-256 | .text bytes |
|---|---|---|---:|
| PRE | `build/lbplanner-pre/tomokv` | `33f07418205817e93d5d759d4cab78480f77c5aa9fa51618dc89aa3e3828f8a2` | 7729345 |
| POST | `build/tomokv-lbplanner-post` (identical to `build/tomokv`) | `571fa4ab3e81f1d231941be82f22950644e0ed437a85d50d6111e5545354e0f1` | 7791376 |
| PAD-A | `build/tomokv-lbplanner-pad` | `bdda99b8c96438cfa60637279c886827cc1a6d78370a5c9a5053e73a79d634c8` | 7791376 |

.text grows **62031 bytes**, including the unreachable PRE comparison bodies.
The complete PRE/POST function and section inventories are under
`docs/lbplanner/*-functions.tsv.gz` and `*-sections.tsv.gz`. The normalized
PRE/POST IO/GET audit finds **135/362** comparisons identical and **622** symbol
size/inventory changes. This is not a claim of PRE/POST hot-path byte identity:
[io-audit.json.gz](docs/lbplanner/io-audit.json.gz),
[io-diffs.txt.gz](docs/lbplanner/io-diffs.txt.gz).

The twin is **kind A: PRE behaviour with POST text layout**. Comparison code
lives in `lbplanner.cc`; there is no runtime mode or configuration knob. The
ordinary POST gate executes its private cache load. An inline-assembly record
marks that instruction and the unreachable PRE gate, without emitting an extra
POST branch or shared load. Metadata inherits the enclosing COMDAT group and is
not mapped at runtime. The IO control tail remains out of line so its complete
call inventory can be checked.

`tools/lbplanner_pad.py` writes a plan before modifying a separate ELF copy.
Its independent inventories cover **all 96 IO-loop bodies, all 34 parser bodies,
and all 8 monitor calls** across both namespaces and ordinary/R7 hosts. The
138 retargets restore the old per-IO cron, complete IO-hosted admission/gather/
search, repeated loop-condition cap reads and fresh connection-stage gates.
PAD bypasses monitor LB; split boots retain their old FLIP loop and fused boots
join workers directly. The old actuator is inlined into the retained tail to
avoid adding a second control-tail call. The existing eight-byte cache field
again holds PRE's per-IO cron deadline in PAD. The unused POST mailbox and object
layouts remain present in both twins.

The verifier compares the retained planner, actuator, writer election, parse
gate and client-move getter against synchronized PRE source, as well as its
cron and boot-monitor policy. Both ELFs have the same **10254 function entries**,
addresses, sizes, sections and alignment. Exactly **629 bytes** differ, all
inside the approved retargets. Every other ELF byte is equal. Function-table
SHA-256 in both arms is
`9663a8b7ea6ff9d77bc9125ed20da33f3c98b022d295121e4c8c4399614f8ee3`.

Receipts: [identity proof](docs/lbplanner/pad-a/proof.json),
[complete retarget inventory](docs/lbplanner/pad-a/planned-retargets.json),
[PRE source closure](docs/lbplanner/pad-a/closure-proof.json),
[negative controls](docs/lbplanner/pad-a/negative-controls.json).
The same builder patches the serverless unit ELF; its behavioural witness and
instruction trace exercise the restored path. Unpatched POST fails that PRE
witness. The corresponding unit identity receipt is
[pad-a-unit/proof.json](docs/lbplanner/pad-a-unit/proof.json).

PAD is behaviour-equivalent, not instruction-identical to PRE: the recorded gate
jump contributes one instruction per connection in the isolated receipt, and
hosting/placement also change its fixed cost. PAD must still stay flat against
PRE in the matched mainline measurements before a placement-independent gain
can be claimed. Neither an exact address table nor these instruction counts
substitute for that verdict.

Reproduce the serverless proofs only:

```sh
taskset -c 112-127 make -j16 all build/lbplanner-units build/tomokv-lbplanner-pad build/lbplanner-trace build/signalacct-core-unit
taskset -c 112-127 python3 tests/lbplanner_checks.py
taskset -c 112-127 build/signalacct-core-unit route
taskset -c 112-127 python3 tools/lbplanner_pre_receipt.py
taskset -c 112-127 make -j16 -f build/lbplanner-extra.mk build/lbplanner-pre-pass
taskset -c 112-127 python3 tools/lbplanner_receipts.py
```

PRE objects must first exist from a `cd02ecbab` source build; the frozen PRE
binary and objects are already present here. `docs/lbplanner/SHA256SUMS` binds
all binaries and witness/tracer artifacts. Compressed build logs include the
final production/control build and the successful PAD generation. The remaining work is the explicitly mainline-owned measurement and live gate.

Mainline measurement request

Use the frozen PRE, POST and verified PAD-A in the same quiet-box ABBA protocol, with the
current matched same-binary null and saturation receipts. Do not widen a band
or interpret a missing/unsaturated run as success. The following are all
requirements, not results:

| Regime/check | Cells or stimulus | Pass condition |
|---|---|---|
| Stable balanced | `h05,h06,p8g,p8s,d1g_l0,d1s_l0,d32s_l1,d8s_l1,d32g_l1,x9_32_l1,x9_32_l0,m8g_l0,v1g_l0,d128g_l0` | Each of the 14 cells is null within its same-binary bands; PAD-A must establish placement attribution. |
| Split CT2 breadth | `h53,h54,h21,h22` | p1/p32 GET/SET: no loss; matched-load cycles/op, instructions/op and IPC together. |
| Admitted imbalance | Existing `tests/lbsignals.py` battery in both modes, plus matched key-skew and client-skew episodes with a demonstrated admitted/moved plan | **Converges no slower than PRE, no more moves than PRE.** A no-admission/no-move episode cannot prove this. |
| 4096 connections | `c4kg,c4ks`; split breadth `w2c4kg1,w2c4ks1,w2c4kg8,w2c4ks8,w2c4kg32,w2c4ks32` | Must not lose; include stationary load and the client imbalance episode. |
| Stationary hold | gaterows3's stationary-hold row **once it lands** | No moves after stabilization; row must pass. It is not counted as a proof already run here. |

The cell files are [generic-cells.txt](docs/lbplanner/generic-cells.txt),
[split-cells.txt](docs/lbplanner/split-cells.txt), and
[4096-cells.txt](docs/lbplanner/4096-cells.txt). Use the gate's instrument and its
reviewed ratio/shard derivation: at 32 server cores the fused cells use 256
shards; split cells use `min(8*nexec,256)`. Use server cores 0–31, load cores
32–111 and no SMT for these comparisons, unless mainline's existing matched
null declares a different geometry. Do not reuse an unmatched null. Correctness
reproduction separately uses the gate's 16-shard, `--ratio $GATE_RATIO`,
`GATE_CORES=0-7` geometry (the fixture's split shape is 6 IO + 2 EX).

Example mainline-only command, repeated for POST and the verified PAD-A, then
for the other two cell files with separate output directories:

```sh
lane=/home/user/Projects/cx-lbplanner
python3 tests/abbagate.py --subset full --build-reference 0 \
  --reference-binary "$lane/build/lbplanner-pre/tomokv" \
  --candidate-binary "$lane/build/tomokv-lbplanner-post" \
  --cells "$lane/docs/lbplanner/generic-cells.txt" \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --output "$lane/build/lbplanner-mainline-generic-post"
```

**Instrument gap:** current `tests/lbsignals.py` validates conservation, schema
and gather counters; it does not time balancing or score move counts. Running
it alone cannot satisfy the imbalance requirement. Mainline must also capture
`INFO LB` and `DEBUG LBSIGNALS` through each matched imbalance episode. Keep the
same physical-key/client stimulus and offered load across arms; capture a
pre-stimulus baseline, the induced imbalance, each controller beat, convergence,
and a stationary suffix of at least a complete decision window.

Read `tomokv_keylb_ticks`, `tomokv_keylb_stage`,
`tomokv_keylb_bucket_gathers`, `tomokv_keylb_bucket_moves`,
`tomokv_keylb_client_moves`, and the corresponding cross-domain move counters.
Read `tomokv_keylb_bucket_weight_spread_current`,
`tomokv_keylb_bucket_bytes_spread_current`,
`tomokv_keylb_client_weight_spread_current` plus their before/after fields.
Capture hysteresis/cooldown/no-candidate/transition/capacity/client/hot-bucket
refusals to explain missing progress. `DEBUG LBSIGNALS` supplies physical owner
rows and per-thread busy/idle counters, including the coordinator.

Use the same convergence criterion derived from the PRE balanced episode for
all arms. Record elapsed time from the identical induced change to sustained
return to that envelope and deltas of each move counter. Count all moves through
the stationary suffix. Compare key and client movement separately as well as
the total; do not let a slower convergence or extra moves disappear in a sum or
wider tolerance. Record coordinator latency separately when the loader can
attribute connections, to test CT1's stated obstruction directly.

After PAD and the three regimes, mainline still runs `tests/gate.sh iteration`,
including both thread modes and the forthcoming stationary-hold row once it lands. Until those
results exist the no-regression and convergence requirements remain unverified.

Gate count and diff

One new row: `LB monitor plan handoff + negative controls`. Its definition is at
`tests/gate.sh:1256`; collection is at line **2909**, before the quick-tier block at
line **3051** and its exit at **3055**. Delta is therefore **+1 quick / +1 full**: from this base,
473→474 and 490→491. `EXPECT_QUICK`, `EXPECT_FULL` and
`tests/fixtures/nullrefresh-ledger-labels.json` were not edited; mainline owns
both count and label synchronization.

`git diff 12fe9f8ad --stat` is captured in
[diff-launch.stat](docs/lbplanner/diff-launch.stat), including the required
upstream fast-forward and this final report. The lane-only
`git diff cd02ecbab --stat` is
[diff-synced-base.stat](docs/lbplanner/diff-synced-base.stat).
The final production code and binaries are frozen at `51ee76982`; the report
commit also strengthens the PAD verifier to inventory duplicate local parser
symbols individually. Its retargets and binary hashes are unchanged. Nothing was pushed.
