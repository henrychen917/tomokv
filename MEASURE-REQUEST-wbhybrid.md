wbhybrid study — 2026-10-01. Performance verdict: PENDING MAINLINE.

Built REF, hyb8/hyb16/hyb32 and three exact-layout PAD A twins. The checkout's
production source and default `build/tomokv` retain policy 1's composite half
rule. No runtime S selector was added. Study copies change only
`src/core/wb_rule.h`; patches are `build/wbhybrid/hyb{8,16,32}.patch`.
No server, load generator, gate, timing experiment, PMU measurement or wire
operation was run. Compilation and serverless execution used CPUs 112–127;
make invocations used `-j16`. No push was made.

Launch HEAD was `e49471fa5620b747c18f4364ce990441bfe0ea64`. The required first
merge fast-forwarded to `5b3d9c4292bf8b332d493beb485266ecc5a289aa` (BASE).
The merge included mainline atomiccollapse, ttlstate and flipsettle changes.
Use this worktree's rebuilt REF for matched-base comparisons. Literal identity
against launch has two outside-rule exceptions from that merge, detailed below;
it is not reported as a pass. An independently built launch binary is supplied
for provenance, not as the study's matched REF.

**Rule definition and derivation.** The task's prose, proof (a), and
PLAN-SERIAL's 2026-09-30 20:54 entry specify the piecewise rule:

```diff
--- a/src/core/wb_rule.h
+++ b/src/core/wb_rule.h
@@ -7,6 +7,9 @@
 #include "../net/conn.h"

 namespace tomo::wb_rule {
+// STUDY ARM: measured per-connection reply count, not a runtime knob.
+// No honest derivation from a connection batch, RYOW capacity, or variable reply size.
+inline constexpr unsigned kSmallPipe = 16;
 // Dimensionless POLICY fraction, not a byte/count/time bound. Competition record
 // section 39 (2026-09-23/24), w4-c12: parse 32 / EX 32 / composite 1/2.
 inline constexpr std::ratio<1, 2> kPolicyFraction{};
@@ -71,7 +74,7 @@
     size_t bytes = staged_bytes(c);
     if (bytes >= kWbufInline) return false;
     const auto head = rob.flush_id();
-    const unsigned threshold = (n * kPolicyFraction.num + kPolicyFraction.den - 1) / kPolicyFraction.den;
+    const unsigned threshold = n <= kSmallPipe ? n : (n * kPolicyFraction.num + kPolicyFraction.den - 1) / kPolicyFraction.den;
     unsigned prefix = 0;
     // Both counters belong to IO, but Done can have holes. Neither head/tail nor
     // the threshold slot alone proves a contiguous prefix. At most ROB slots,
```

This replaces only the existing `const unsigned threshold = ...` statement,
with the constant declared in the same header. The task's alternative formula
`max(ceil(n/2), min(n,S))` is NOT equivalent: at n=17, S=16 it gives 16,
whereas the requested piecewise table gives 9. The supplied arms use the
piecewise definition. The clarification was raised during the work; absent a
correction, the explicit proof table and mainline ledger determine the arms.

| n | REF | hyb8 | hyb16 | hyb32 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | bypass | bypass | bypass | bypass |
| 8 | 4 | 8 | 8 | 8 |
| 9 | 5 | 5 | 9 | 9 |
| 16 | 8 | 8 | 16 | 16 |
| 17 | 9 | 9 | 9 | 17 |
| 31 | 16 | 16 | 16 | 31 |
| 32 | 16 | 16 | 16 | 32 |
| 33 | 17 | 17 | 17 | 17 |
| 64 | 32 | 32 | 32 | 32 |

No honest derivation from the proposed existing sizings was found. The current
`genthread_pipeline.h:10` and `:11` contain 32-operation parse/EX quanta;
`kGenthreadWbBatchConns` does not exist in either launch or BASE. Phase2's
budget is the captured FIFO size (`wb_rule.h:121`); split scratch holds 64
CLIENTS (`iopipe_pipeline.h:25`), not replies of one client. RYOW's current
write ring is `kRobWindow = 64`, with `kWriteRingCapacity = kRobWindow`
(`net/rob.h:53`, `:81`); the historical sixteen-slot description is stale.
Its safety capacity bounds unretired writes and does not specify send batching.
`kWbufInline = 512` (`net/conn.h:71`) is a real byte bound, but division by a
“typical” reply size introduces a workload-dependent constant: OK is 5 bytes,
whereas a 64-byte GET bulk reply is 71 bytes. There is no single reply size
from which 8/16/32 follow.

Therefore these are explicitly **measured constants requiring their own ledger
row**, as permitted by the task. No artificial ratio to the ROB or connection
batch is presented as a derivation. If ROB capacity changes, regenerate the
oracle's depth coverage; if inline byte capacity or reply shapes change, the
byte exit's crossover changes and this study must be repeated. A connection
batch-size change affects revisit latency, so it also calls for remeasurement,
but does not mechanically rescale S. No correctness law relies on these S values.

**Mechanism reading.** The partial-send blocking hypothesis is supported by
the code; fixed send counts and an obligatory extra FIFO pass are not.

1. `wb_rule.h:65–90` first bypasses policy 0 and n<=1, counts only IO-owned
   staged bytes, then acquires Done slots in ROB order. It exits on 512 bytes,
   a Done scatter marker, or the selected contiguous prefix. Submitted bytes
   are excluded (`:32–34`). An executing slot's reply lengths are never read.
   The rule is admission, not a retirement limit.
2. `Phase2::gather` (`:98–113`) and `serve` (`:117–167`) capture one visit
   count, pop FIFO entries, rotate deferred clients with `serve_pending` still
   set, and clear that lifetime pin only on selection/dead-entry removal.
   Callbacks cannot extend the captured visit budget. `io_loop.h:4595` and
   `:5203`, plus `reorder.cc:1354`, remain thin calls into this single rule.
3. Once admitted, `WbEngine::serve_impl` (`net/wb.h:787–872`) drains the whole
   currently contiguous Done prefix, including replies beyond the admission
   threshold. It can retire and stage additional replies while a previous
   send is outstanding. Double buffering keeps those bytes in `fill_buf`
   (`net/conn.h:388–437`); borrowed payloads use the existing segment queue.
4. `pump` immediately returns while `send_inflight` is true (`wb.h:398`).
   Thus an eligible-again client can be popped, unpinned and drained, yet its
   new output cannot get a second socket send. This is the completion dependency
   that completing a small pipe can avoid. The client need not remain in the
   serve FIFO merely because bytes are waiting for SEND completion.
5. `on_send_complete` clears the in-flight flag, advances the completed-byte
   frontier, and calls `pump` when there is staged output or an unfinished send
   (`wb.h:585–630`). Pump handles a legacy remainder first, then segments, then
   promotes the fill buffer (`:400–437`). A partial CQE therefore continues the
   old ordered output before the later replies. This handler constructs an SQE;
   the loop's normal submit boundary still determines kernel submission.
6. `on_plain_send_cqe` (`io_loop.h:1060–1075`) supplies `ImmediateProgress`.
   `on_cqe` defines it as `!(Fused && Pipeline != 0)` (`:1096`). Active fused
   and R7 fused entry points select Pipeline=0 (`genthread.cc:66`,
   `reorder.cc:3577`). Ordinary split uses Fused=false; split overlap, including
   split read-local, harvests CQEs through `ifid_rx` with Fused=false, Pipeline=1
   (`io_loop.h:4646`). Consequently the active study paths pump staged output
   **in the CQE handler**, without requeueing it to `pending_serve_` or requiring
   an extra Phase2 visit. If replies have not yet retired, their normal completion
   hint/FIFO visit is still needed (`io_loop.h:4536–4554`). A client already
   deferred remains pinned in that FIFO for its next captured visit.
7. The template's `ImmediateProgress=false` branch does requeue nonempty output
   and mark the client active (`io_loop.h:1070–1073`); deduplication is at
   `:5206–5209`. That branch is not selected by the active entries above. Even
   there it means the next eligible WB stage after enqueue, not necessarily a
   complete extra outer pass; capture timing and defer() govern eligibility.

Thus min(n,16) can admit a deep partially completed pipe earlier than half,
but “four sends versus two at depth 64” does not follow from this code. Drain
may consume more than the threshold, byte/scatter exits can preempt it, and n
is recomputed after retirement/new dispatch. Likewise, hybrid's half rule above
S is not proof of burst-tail neutrality: a draining deep pipe can cross into
the complete-small-pipe region. hyb32 also intentionally differs from REF at
n=32 (especially small SET replies); p32 parity is a measurement requirement.
No ownership, QSBR, per-operation retry, in-place-write or RYOW behavior changed.

**Arms and PAD method.** All study builds use the exact BASE Makefile compile
and link commands, including each namespace's compiler budgets, jemalloc and
object order. Compiler `-MMD -MP` files identify 12 objects including the rule:
main, flipctl, genthread, rl2s, lbstall and reorder, each in `tomo` and `tomo_db0`.
Only those are recompiled; the other 72 input objects are reused immutably and
checked by whole-object SHA-256. Candidate copies contain no other changed
production file. `build/wbhybrid/dependencies.json` and `identity.json` record it.

PADs are **kind A: behaviour twins**, REF half-rule behavior in each candidate's
exact code shape and layout. `tools/wbhybrid_artifacts.py pads` identifies the
threshold compare using DWARF file/line information and decoded instruction
boundaries, verifies its unsigned conditional selection, and patches S to 1.
Since n<=1 has already returned, this selects half for every remaining visit.
Exactly two immediate bytes change per server ELF, one per database namespace.
Every other byte, function address, instruction size and section size is identical
to that candidate. This is stronger than wbabs's aggregate text-size padding.
The linked build ID is deliberately retained; identify the artifacts by SHA-256.
PADs pay the candidate selector work; PAD-versus-REF prices that codegen/layout
cost, while candidate-versus-PAD isolates changed admission behavior. Native
candidate text is only 160 bytes smaller than REF; no PAD B is needed.

| Arm | SHA-256 |
| --- | --- |
| `build/tomokv` | `9517886811efa53a269f1fd08b431357b6035100c5f3cccfce23718fd0bc919c` |
| `build/tomokv-hyb8` | `4b6e076b107d808d70625901c92dacfd49e3c3cdd5aee4308804addf161e6f4e` |
| `build/tomokv-hyb8-pad` | `9cfb160ae378c4ca627811502672ae0e5a9f5bf8151d8da320ceaa9270d2bde0` |
| `build/tomokv-hyb16` | `4a1546643215f03ccf4024b23eb03ebee9cedff1cb083f91e5551ebc0c3c01e9` |
| `build/tomokv-hyb16-pad` | `f80d56bb31e2632aad74ac9d5f9dfa7f60068756b21fc8a2db71a9b28c100738` |
| `build/tomokv-hyb32` | `317647381cb1ce62d7a6f8b8f6337832626ac6cc36df8ed2edd2e3994950c9ea` |
| `build/tomokv-hyb32-pad` | `86e92333dcb86e77c560ea1ff2a71c7013743c6146875a123a6280e7d900d1b2` |

All seven measurement arms have `.tdata=112`, `.tbss=480`. REF `.text=7,564,593`
bytes; each hybrid and its PAD `.text=7,564,433`. Layout assertions for Op 336,
Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192,
AtomicEntry 144 and Config 624 compile in both path-test namespace variants.
Use policy 1 (the unchanged default) on every measurement arm; policy 0 bypasses
the study entirely. No config-file override should silently change the arm.

**Proof receipts (a)–(f).** Machine-readable receipts are in
`build/wbhybrid/`; `tests/wbhybrid_evidence.json` records the final digest ledger.

| Proof | Completed offline evidence |
| --- | --- |
| (a) Thresholds and exits | For REF, all hybrids and all PADs, both database compilations: every n=0..64, every Done prefix, fresh start and ROB wrap at 61, policies 0/1. 4,290 table cells per binary, two policy assertions per cell. For every n=2..64: staged 511/512 boundary, submitted-byte exclusion, Done-byte 511/512 boundary and scatter Done/Issued exit. 28 positive invocations. |
| (b) Existing witnesses | Unchanged REF wb_rule/wbland suites: 248 strict outcomes, 162 positive and 86 intended assertion failures. Runtime policies 0/1, fused FIFO/R7 and split ordinary/natural/shallow/read-local paths retained. No assertion or legacy test source changed. |
| Additional arm paths | 96 positive schedule invocations, each sweeping n=8/16/17/32/33/64 and policies 0/1 over 96 clients plus staged-only output (larger than scratch capacity). Real Phase2/ROB/WB and synthetic SQ, no worker loops/listener/kernel SEND. Six candidate/PAD arms × two namespace builds × eight schedules. Single-db initializes databases=1; multi-db initializes databases=4. Only fixture depth/oracle/configuration differ from the existing wbland path witness. |
| (c) Off-by-one controls | S changed to S+1 in production header copies, oracle held fixed: six required exit-1 failures (three arms × two namespaces). hyb8 fails at n=9, Done=5; hyb16 at n=17, Done=9; hyb32 at n=33, Done=17. Every failure names `piecewise threshold table`; crashes/timeouts/unrelated failures do not count. |
| (d) Identity | BASE REF versus each hybrid: 72/72 objects outside the include closure byte-identical; only wb_rule.h changed in production source copies. PAD: exactly two bytes differ from candidate; all other ELF bytes identical. Launch-versus-BASE has the merge exceptions below. |
| (e) SHA-256 | Every delivered arm appears above and in `binaries.json`; final audit rehashes all arms and every executed witness. |
| (f) defer instruction receipt | 22 identical fixtures × REF/three hybrids = 88 single-step receipts. Setup excluded, one named `wbhybrid_defer` call, no clocks or PMU. Equal-prefix selector overhead is at most +1 instruction; intentional longer prefix scans are included explicitly below. |

The seven unchanged legacy groups report respectively: policy 37/37 (19
controls), phase 32/32 (8), stages 12/12 (2), split-phase 35/35 (11),
split-overlap 64/64 (20), wbland-clauses 49/49 (23), wbland-paths 19/19 (3).
Production builds have no compiler warnings; the existing deliberately broken
`empty` control emits its expected misleading-indentation warning.

Literal launch identity is **not a pass**. Rebuilt launch versus BASE differs in
runtime sections of `src/cmd/xshard.o` and `db0/src/cmd/xshard.o`, both outside
the wb_rule.h closure, due to the mandatory atomiccollapse merge. Ten objects
inside the closure also differ across that merge. The other 72/84 runtime
objects match launch; within the outside-rule set this is 70/72. This audit
compares allocated-section bytes/sizes plus relocation identities, excluding
cwd-dependent DWARF. Each study arm then reuses BASE's outside-rule objects
exactly. This isolates the experiment without undoing required mainline work.
`launch-identity.json` records every changed section. The rebuilt launch binary
is `build/tomokv-wbhybrid-launch`, SHA-256
`cd7916150ac1f4a2398563bc8c4f748c364960fa72340e18bc147347c9651c30`.

Instruction counts below are per **single defer invocation**, including its
uniform wrapper boundary; they are not server instructions/op or throughput.
Empty replies keep the byte clause inactive in count-only fixtures.

| Fixture n / Done / staged bytes / policy / scatter | REF | hyb8 | hyb16 | hyb32 |
| --- | ---: | ---: | ---: | ---: |
| 1 / 0 / 0 / 1 / 0 | 12 | 12 | 12 | 12 |
| 64 / 1 / 0 / 0 / 0 | 7 | 7 | 7 | 7 |
| 64 / 0 / 512 / 1 / 0 | 34 | 34 | 34 | 34 |
| 8 / 0 / 0 / 1 / 0 | 66 | 65 | 65 | 65 |
| 8 / 1 / 0 / 1 / 0 | 92 | 91 | 91 | 91 |
| 8 / 8 / 0 / 1 / 0 | 160 | 263 | 263 | 263 |
| 16 / 0 / 0 / 1 / 0 | 66 | 67 | 65 | 65 |
| 16 / 1 / 0 / 1 / 0 | 92 | 93 | 91 | 91 |
| 16 / 16 / 0 / 1 / 0 | 264 | 265 | 471 | 471 |
| 17 / 0 / 0 / 1 / 0 | 66 | 67 | 67 | 65 |
| 17 / 1 / 0 / 1 / 0 | 92 | 93 | 93 | 91 |
| 17 / 17 / 0 / 1 / 0 | 290 | 291 | 291 | 497 |
| 32 / 0 / 0 / 1 / 0 | 66 | 67 | 67 | 65 |
| 32 / 1 / 0 / 1 / 0 | 92 | 93 | 93 | 91 |
| 32 / 32 / 0 / 1 / 0 | 472 | 473 | 473 | 887 |
| 33 / 0 / 0 / 1 / 0 | 66 | 67 | 67 | 67 |
| 33 / 1 / 0 / 1 / 0 | 92 | 93 | 93 | 93 |
| 33 / 33 / 0 / 1 / 0 | 498 | 499 | 499 | 499 |
| 64 / 0 / 0 / 1 / 0 | 66 | 67 | 67 | 67 |
| 64 / 1 / 0 / 1 / 0 | 92 | 93 | 93 | 93 |
| 64 / 64 / 0 / 1 / 0 | 888 | 889 | 889 | 889 |
| 64 / 1 / 0 / 1 / 1 | 70 | 71 | 71 | 71 |

For an identical visited prefix, short-pipe selection saves one instruction;
large-pipe selection adds one net instruction: compare+conditional branch
replace one REF register move. The policy-0, n<=1 and already-staged-512 exits
have zero delta. A fully Done small pipe intentionally scans more slots: e.g.
p8 is 263 versus 160 instructions, and hyb32 at p32 is 887 versus 472. These
are required consequence of completing the pipe, not hidden selector overhead.
If “no more than one instruction” were intended to include these additional
ROB visits, that stronger requirement is not met and conflicts with the
requested acquire-prefix walk. No instruction delta is treated as a rate gain.

**Mainline measurement request.** All results below are pending. Run sequentially
on the mainline's quiet box, with matched-base `REF=build/tomokv`, each hybrid
and its paired PAD A. PAD means all three named twins, not an unspecified
aggregate-size arm. Preserve the existing test population, harness and geometry.
Keep both candidate-versus-REF and candidate-versus-PAD comparisons; price
PAD-versus-REF against a contemporaneous same-binary null.

| Class | Exact cells and repetitions | Deciding evidence |
| --- | --- | --- |
| Low load | Closed-loop GET p32@256K, p8@256K, p8@512K offered; existing 512-connection/24-memtier-instance MIDLOAD geometry and per-connection rate limit; REF/hyb8/hyb16/hyb32 plus each PAD, three rounds per cell/arm. | Share at <=0.2 ms, higher better, with achieved/offered rates and each round's spread. Keep <=0.5/1 ms as diagnostics. Retain S=16's low-load improvement, including the observed +4–7 point p32 and +7.1 point p8@512K gains within the matched run's spread. |
| Saturation | `tests/wbhybrid_cells.txt`: unchanged 14 generic cells plus h05r1/h06r1/p8gr1/p8sr1/x9_32_l0r1, plus c4kg/c4ks (GET/SET p32, 4096 connections). Every candidate and PAD versus REF with the gate's ABBA instrument and fresh null. | Per-cell matched-load rate, p1 latency, cycles/op, IPC and instructions/op; commands/send explains batching. Retain the p8 gain (~8–9% loopback), p32 parity, and no losing cell class. Read-local/mixed/large-value/deep-pipe rows remain part of acceptance. |
| Bursts | GET:BITCOUNT 9:1, open-loop mean 931K/s, 64 max outstanding; floors 0/0.4/0.7; reorder 0 and 1; REF, every hybrid, every paired PAD; four samples per arm/cell. Use the existing FLOOR-BURST waveform/duty, population and seeds. | Report p50/p99/p99.9 and achieved rate, separately by floor and reorder. No consistent floor-0.4/0.7 tail loss versus half; idle-to-flood p50 also cannot be traded away. Existing 5–7% burst resolution is not a reason to claim a smaller win or excuse a repeatable loss. |
| NIC-AB | `calib/nic-ab.sh`, GET/SET × p8/p32; REF, every hybrid and paired PAD; existing ABBA ×2 (four samples per arm/pair), 25GbE two-netns rig. | Rate and commands/send. Retain S=16's p8 wire throughput gain (~13–16%); p32 stays within the matched null. |
| NIC-LAT | `calib/nic-latency.sh`, GET/SET × p8/p32 × 60%/80% of the same fixed wire saturation reference; 512 connections, per-connection rate limit; all candidate/PAD arms, ABBA ×2. | p50/p99/p99.9 at matched achieved load. Retain GET p8's measured p99 improvements −16.3%/−13.8% at 60%/80%, within this run's approximately ±3% p99 spread, plus the rest of the distribution. No p32 loss. Do not recompute a different offered rate from each arm's own saturation. |

The 14 generic IDs are h05, h06, p8g, p8s, d1g_l0, d1s_l0, m8g_l0,
v1g_l0, d128g_l0, d32g_l1, d8s_l1, d32s_l1, x9_32_l1, x9_32_l0.
The supplied 21-row file was parsed offline by `abbagate.read_cells`.
Saturation geometry remains server 0–31/load 32–111, without SMT, as the
mainline instrument specifies. The NIC scripts own their 0–31/64–127 geometry;
this lane did not invoke them. The report requests the full matrix above even
if a provisional mainline queue initially samples fewer arms/floors.

Pass bar: never worse than half on ANY cell class, retain the small-pipe low-load,
p8 saturation and p8 wire-latency gains, and retain p32 behavior. A consistently
losing class means DELETE/TRADE, not a new runtime mode. If an arm passes the
whole map and the maintainer's gate, hardcode the winning measured S under
existing policy 1 and remove the study selectors. This lane does not select a
winner. Mainline boot/correctness coverage must include 1s/2s and databases=1/>1;
gate failures must be reproduced at 16 shards and the gate's 6-IO/2-EX geometry.
No gate rows were added or retired: row delta is 0 quick / 0 full, and both
EXPECT constants remain untouched (current source: 441/463).

**Offline reproduction and inventory.** From a clean BASE production build:

```sh
mkdir -p build/wbhybrid
taskset -c 112-127 make -j16 CXX='g++ -MMD -MP' all > build/wbhybrid/ref-build.log 2>&1
taskset -c 112-127 python3 tools/wbhybrid_artifacts.py builds
taskset -c 112-127 python3 tools/wbhybrid_artifacts.py pads
taskset -c 112-127 python3 tools/wbhybrid_artifacts.py identity
taskset -c 112-127 python3 tools/wbhybrid_artifacts.py proofs
taskset -c 112-127 python3 tools/wbhybrid_artifacts.py costs
taskset -c 112-127 make -j16 CXX='g++ -MMD -MP' wbland-units
taskset -c 112-127 python3 tools/wbhybrid_artifacts.py legacy
taskset -c 112-127 python3 tools/wbhybrid_artifacts.py paths
taskset -c 112-127 python3 tools/wbhybrid_artifacts.py audit
```

The reference build log must contain all 84 compilation commands and the link,
not an incremental “nothing to do” run. For the optional historical audit,
extract `git archive e49471fa5620b747c18f4364ce990441bfe0ea64` under
`build/wbhybrid/launch-src`, build there with the same taskset/make/CXX command,
then run `launch_identity`. The delivered tree already contains those artifacts.
The requested `MEASURE-REQUEST` index points to this report. Live results belong
in `MEASURE-RESULT`; performance, gate and merge remain with the maintainer.

Requested `git diff e49471fa5620b747c18f4364ce990441bfe0ea64 --stat`
(includes the required mainline merge):

```text
 MEASURE-REQUEST                           |  40 +--
 MEASURE-REQUEST-cleanup-atomiccollapse.md | 203 +++++++++++++
 MEASURE-REQUEST-cleanup-flipsettle.md     | 159 +++++++++++
 MEASURE-REQUEST-cleanup-ttlstate.md       | 363 ++++++++++++++++++++++++
 MEASURE-REQUEST-wbhybrid.md               | 335 ++++++++++++++++++++++
 Makefile                                  |   5 +-
 src/core/flipctl.cc                       |  31 +-
 src/core/flipctl.h                        |   1 +
 src/store/flatstore_atomic.inc            | 429 ++--------------------------
 src/store/kvobj.h                         |   1 -
 src/store/store_ttl.h                     |  32 +--
 tests/atomic_survivors_unit.cc            |  18 +-
 tests/atomiccollapse_checks.inc           | 306 ++++++++++++++++++++
 tests/atomiccollapse_controls.py          | 184 ++++++++++++
 tests/core_concurrency_unit.cc            |   5 +-
 tests/flipsettle_checks.inc               | 172 +++++++++++
 tests/gate_measurements.json              |   8 +-
 tests/wbhybrid_cells.txt                  |  22 ++
 tests/wbhybrid_evidence.json              | 456 ++++++++++++++++++++++++++++++
 tests/wbhybrid_unit.cc                    | 103 +++++++
 tools/atomiccollapse_artifacts.py         | 304 ++++++++++++++++++++
 tools/flipsettle_artifacts.py             | 244 ++++++++++++++++
 tools/flipsettle_controls.py              | 183 ++++++++++++
 tools/ttlstate_proof.py                   | 362 ++++++++++++++++++++++++
 tools/wbhybrid_artifacts.py               | 441 +++++++++++++++++++++++++++++
 25 files changed, 3927 insertions(+), 480 deletions(-)
```
