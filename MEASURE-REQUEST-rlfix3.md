## rlfix3

Base: `05a5e01a9d8f1236e11cdbe4f2f7d490eb40edba`. Worktree/branch:
`/home/user/Projects/cx-rlfix3`, `cx-rlfix3`. No push. Builds and correctness runs use CPUs 96–111; server/oracle bind ports are
38800–38899. One initial gate-self-test attempt omitted `GATE_TEST_PORT`
(the mock-listener default is ephemeral); it was stopped and excluded. All
subsequent self-test attempts set an explicit in-range mock port.

Item commits (folded locally, one per item):
`62e2e9553` — RL4.11 lifetime/documentation/capability;
`a00bf8765` — RL4.15 selective INFO collection and maintained gauges.
The following proof commit records the final receipts and measurement request.

### RL4.11: explicit lifetime constraint

Used the task's permitted documentation/capability alternative. Lane replies
still copy. `CONFIG GET zc-min-read-local` now returns `0` (read-only, no CLI or
config-file knob); `CONFIG GET zc-min*` reports both it and the live owner
threshold. Owner GETs and owner fallbacks retain their exact >= threshold rule.

Why a direct lane borrow is unsafe: the reader's immutable pointer is protected
until its next rotation publishes a QSBR tick (`ThreadCtx` rotation/park
publication). Replacement retires the old object in `ReadLocalRetireRing`;
`drain_below` releases it once all ticks pass its stamp. Neither the ring nor
tick publication consults pending sends. `tests/rlfix3_lifetime.cc` exercises
the real ring: the next rotation permits reclamation while an `Op::zc_ptr`
descriptor is still live. The separate owner borrow vector/index retains owner
GET values until writeback sends a release back to that owner. Foreign writes
to that registry would violate single-owner mutation and race vector growth,
index updates, retirement and release. A send-lifetime pin or registration
handshake would be a new lifetime protocol, outside the fixed lane design.
Source anchors: `src/core/ex_loop.h:844` (copying lane reply),
`src/core/thread.h:899` (tick publication), `src/core/read_local.h:207`
(retire-ring grace test), `src/store/flatstore.h:1392` (owner borrow registry),
`src/net/wb.h:321` (send retirement/release), `src/cmd/t_string.cc:350`
(owner >= threshold). CONFIG REWRITE deliberately omits the GET-only capability;
the new native rewrite witness checks a real rewrite round trip in both images.

PRE reproduction: `docs/rlfix3/pre-zc-ledger.tsv` and
`docs/rlfix3/pre-zc-reproduction.log`. All eight new gate rows run every threshold
and venue assertion, then fail on the missing capability. Both modes, both
engines, read-local 0/1; value sizes 1024/16384/262144; thresholds 0/N/N+1.
The existing zero-copy job passes all release/ASAN legs on PRE. No timing or
throughput estimates are taken by these witnesses.

RL4.5 and RL4.6 (read in full with the scope report) do not change: eviction
still makes writes conservative for RYOW, and split read-local still enables
coded replies. A split rl=0/1 comparison includes that coded-reply effect.

### RL4.15: selective collection and maintained counts

PRE reproduction uses the actual INFO handler linked with PRE production
objects. Readable-page controls return successfully; making the filter pages
unreadable makes `INFO server` fault in both modes at 16 and 256 shards
(`docs/rlfix3/pre-info-reproduction.json`). This proves the walk, without
claiming a latency result. INFO latency remains NEEDS-RUN with the maintainer.

POST resolves STATS/MEMORY/KEYSPACE/COMMANDSTATS selection before gathering.
Unrequested statistics, command-call totals and RESETSTAT baselines are not
collected. Existing output formatting, order and selection rules are retained,
including default/all/everything, case folding and multiple-section unions.

`ForeignReadSafety` maintains occupancy/wildcard gauges on cell transitions.
The two atomic words fit existing tail padding: sizeof remains 49216, and all
locked enclosing layouts are unchanged. The disabled lane allocates nothing.
Counts are exact after owner transitions complete, with the usual independent
INFO sampling of in-progress updates; no periodic cache or reader retries.
Saturation drain and permanent poison explicitly publish their final counts.
`tests/rlfix3_info_unit.cc` tests collisions, sticky wildcard/nested poison,
saturation/rebuild, permanent poison, protected cell pages and protected store
state for metadata-only requests. External identity/time/allocator facts are
fixed in this serverless executable only for exact reply comparisons.

The first POST directed gate selection passes 28/28 rows, including both new
jobs, B+, read-local admission/fence/miss/delete, filter and configuration jobs
(`docs/rlfix3/post-directed-initial-ledger.tsv`). The completed final proof receipts below supersede that preliminary run.

### Build and identity proof

`docs/rlfix3/freshness.json`: 47/47 `make -q` checks pass: `all`, every
`job_production_units` target, both concrete `mdbqsbr-live-arms` binaries, and
both INFO native witnesses. The phony live-arms aggregate is built by the gate;
its concrete outputs are checked for freshness. Builds use `-j16`.

`docs/rlfix3/info-byte-comparison.json`: 160/160 complete INFO RESP frames
identical on PRE and POST, with nonzero foreign-filter counts. Both namespace
implementations, 1s/2s, 16/256 shards, all twelve individual sections and eight
selection combinations. Only external facts (clock, process identity, executable
path, RNG and allocator totals) are fixed by test-only link wrappers. No reply
field is removed, masked or normalized. Live RESP2/RESP3 section union tests also
run in each new gate row.

Identity is a proxy, not a merit verdict. `ccfix_audit.py` reports 18,147/18,366
object bodies equal; 1,216/1,224 command handlers and 1,354/1,374 selected hot
bodies equal. Its strict assertion exits 1, and work continues. Changed handlers
include INFO/config plus compiler changes to QUIT/RESET; hot differences include
read-local filter callers, dispatch/inlining and FlatStore insertion/deletion.
`lbstall_artifacts.py` finds 1,350/1,370 selected object bodies relocation-equal.
`reorder_noop.py --expected-functions 340 --report-only --literal-pools` finds
329/340 linked bodies identical: scheduler 72/72, envelope 119/120, dispatch
82/92, retirement 8/8, commands 16/16, multi-key commands 32/32. Both normalizer
self-checks and the report-only run pass; `strict_noop=false` is retained.
Raw/normalized comparisons and changed-body inventories are under
`docs/rlfix3/{object-identity,hot-identity*,linked-identity*}`.

### Maintainer merit request — NOT RUN

The task reserves performance measurements for the maintainer. **INFO latency
NEEDS-RUN**, including the requested first PRE cost measurement: source/access
reproduction precedes the fix, but no latency result has been substituted for it.
Large-GET instructions/copy bytes and generic-cell merit are also NOT RUN.
There is no throughput or latency improvement claim in this lane.

The binary hashes and `.text` sizes are in `docs/rlfix3/binaries.json`.

| Arm | Binary | SHA-256 | .text bytes |
| --- | --- | --- | --- |
| pre | `build/tomokv-pre` | `2906fb8cf8279b880d64103dc1a70d89c9b88b54079f61edce0c7f59c7cdca4a` | 8217911 |
| post | `build/tomokv` | `d00d4c6ba6dba4d76b5a07fbdce632a22b4bf5aac9eb8138d45391daa9181997` | 8214279 |
| pad-a | `build/tomokv-pad-a` | `f586bb6a31eaf61e02af89bf186cc171abfdb8f5c3691efbc6f11c481263f757` | 8214279 |
| pad-b | `build/tomokv-pad-b` | `0af2046d94987870a881b0b71738ba33dd9711efb9c7cfa97585a401674a9ccc` | 8217911 |

PAD-A is explicitly **(A) behaviour twin**: PRE behavior at POST's exact total
`.text` size. Because POST shrank by 3,632 bytes, PRE's two INFO/config objects
use compact code alignment, then unreferenced NOPs fill to POST's size. This
controls total text size; individual function addresses do not match POST.
PAD-B is **(B) inverse control**: POST behavior plus 3,632 unreferenced NOP bytes
restoring PRE's total `.text` size. Neither control changes a data structure.
Construction and hashes are in `docs/rlfix3/pad-{a,b}.json`; reproduce with
`tools/rlfix3_pad.py`. No control is presented as a full address-layout match.

Generic 14: `docs/rlfix3/merit-cells.txt` is a verbatim copy of the maintainer's
`/tmp/claude-1000/generic_merit_cells.txt`, also byte-identical to
`tests/wbland_merit_cells.txt`; provenance and source SHA are recorded. It keeps
all 14 fused cells and their 8/4-instance pins: h05,h06,p8g,p8s,d1g_l0,d1s_l0,
m8g_l0,v1g_l0,d128g_l0,d32g_l1,d8s_l1,d32s_l1,x9_32_l1,x9_32_l0. Optional
`headline-controls.txt` adds the fourteen ordinary headline mode/knob controls
(h01,h02,h15,h16,h17,h18,h31,h32,h33,h34,h47,h48,h63,h64), including split mode;
it is not a replacement for the generic set. Private large GET cells in `docs/rlfix3/large-get-cells.txt` use the supported `GET:BYTES`
grammar: both modes, read-local 1, 1024/16384/262144 bytes, p1, 512 connections,
4096 keys, `zc-min=1`; six rl=0 owner controls accompany the six requested lane
cells. All three files pass `abbagate.py --list-cells`. Calibrate private cells and
obtain a matched null before scoring; do not reuse a 64-byte cell's load floor.

On a quiet scheduled box, run the gate's instrument for PRE versus POST, PRE
versus PAD-A, and POST versus PAD-B (the latter isolates inverse padding):

```sh
taskset -c 96-111 python3 tests/abbagate.py \
  --reference-binary build/tomokv-pre --candidate-binary build/tomokv \
  --build-reference 0 --cells docs/rlfix3/merit-cells.txt --subset full \
  --server-cores 96-103 --server-smt '' --load-cores 104-111 --load-smt '' \
  --ports 38881-38883 --output build/rlfix3/merit-post
```

Use the same private cells and matched offered load for each pair. Generic
verdict: the gate's per-cell regression criterion at the same offered load;
report cycles/op, instructions/op and IPC together. PAD-A staying near PRE while
POST changes supports a behavior effect; PAD-B tests the aggregate text-size
alternative. Any hot-path regression remains grounds to reject/revise RL4.15.
For large GETs report **instructions and copied payload bytes per completed GET**,
with lane-hit and zc-send deltas proving the venue; do not make throughput claims.
For the separate PMU diagnostic use the existing delegating wrapper
`tools/wbknobs_measure.py --experiment null --profile 1` with the same binary,
cell, core and port arguments (and a distinct output directory). In this mode
it leaves both boot settings at their cell defaults and delegates to
`abbagate.main`; profiling is permanently marked untrusted for gate/null
scoring. `tests/abba_profile.py` explicitly labels counts divided by central
operations as approximate because PMU and command windows differ. Retain raw
counts/window endpoints and that qualification; do not promote the diagnostic
to a merit pass. The instrument supports value sizes and instruction counting
but has no payload-copy byte counter. Count actual payload-copy sites in a separate diagnostic build
(including reply materialization and writeback staging; excluding protocol
headers), validate that the counter fires on copying controls, and do not use
that instrumented build for instruction or merit results. Expected, unmeasured:
this documentation alternative leaves the lane's copying behavior unchanged.

INFO cost cells: PRE/POST (and PAD controls), INFO SERVER and INFO ALL, 16/256
shards, both modes, rl=0/1, gate geometry 8 cores / ratio 6:2. Report request
latency distribution and instructions per INFO separately with identical
sampling/load. Establish PRE's shard-scaling cost first. POST SERVER must avoid
store aggregation (proven by protected-state witness); INFO ALL may walk shards
but must not read filter-cell arrays (proven by protected-cell witness).

| Requested measurement | PRE | POST | PAD-A / PAD-B |
| --- | --- | --- | --- |
| Generic 14 matched-load merit | NOT RUN | NOT RUN | NOT RUN |
| Large GET instructions/payload copy bytes | NOT RUN | NOT RUN | NOT RUN |
| INFO SERVER / ALL latency, 16/256 shards | NOT RUN | NOT RUN | NOT RUN |

Each item adds eight rows (mode × engine × read-local), all collected before
the quick-tier exit: **DQ=+16, DF=+16**, required **784 quick / 801 full** from
768/785. `EXPECT_QUICK` and `EXPECT_FULL` remain untouched. The explicit label
fixture includes the 16 additions; the source-label check must still report the
maintainer-owned EXPECT mismatch until those constants are updated. The collection
sites are `tests/gate.sh:5282` and `:5283`, above the quick exit at `:5402`.
The fixture's source multiset is exactly 801/801 with no missing/extra labels.
`gate_ledger_fixture.py` and its current-inventory self-test therefore fail ONLY
on EXPECT_FULL=785; the other nine fixture controls pass. This refusal is
intentional evidence of the outstanding maintainer count update.

### Correctness receipts

All new rows use `GATE_ONLY_JOBS` through the gate's own scheduler. Each new
job runs 1s/2s × epoll/io_uring × read-local 0/1. INFO additionally runs both
namespace implementations and 16/256 shards. PRE native witnesses link the
frozen PRE production objects (`tools/rlfix3_units.py`); PRE's ASAN binary is
also frozen separately. No missed arming window is skipped. Re-run both directed POST jobs with:

```sh
taskset -c 96-111 env GATE_ONLY_JOBS='rlfix3_zc rlfix3_info' \
  tests/gate.sh quick --candidate-binary build/tomokv \
  --server-cores 96-103 --server-smt '' --load-cores 104-111 --load-smt '' \
  --ports 38891-38893
```

For PRE, select `build/tomokv-pre` and explicitly set
`GATE_RLFIX3_INFO_UNIT=$PWD/build/rlfix3/info-pre-multi` plus
`GATE_RLFIX3_INFO_DB0_UNIT=$PWD/build/rlfix3/info-pre-db0`. Their production
objects and headers are frozen under `build/pre-source`.

| Directed job | PRE | POST | Additional control |
| --- | --- | --- | --- |
| `rlfix3_zc` | 8 expected failures | 8 pass | PAD-A: 8 expected failures; PAD-B: 8 pass |
| `rlfix3_info` | 8 expected failures | 8 pass | Unpaired PRE/local-native configuration: refused |
| Existing `zc`, both modes and engines | All 4 invocations pass | All 4 invocations pass | Release, fired-counter, ASAN battery and ASAN-clean legs |

All 32 capability rows execute nine value/threshold cases, the WATCH owner
fallback and all four capability observations before reporting failure.
PRE/PAD-A fail the four capability checks; POST/PAD-B pass. All 16 paired INFO
rows execute 52 native calls each (832 total), plus RESP2/RESP3 wire-union
checks. Each PRE row has 34 expected protected-access faults; every accessible
and CONFIG REWRITE control succeeds. POST has zero faults. Full final directed
logs are retained in `docs/rlfix3/directed-final-logs.tar.gz`, with leg audits
and gate ledgers beside it.

The INFO gate job requires a fresh, byte-identical local candidate when using
its default native witnesses. An external PRE/PAD binary must explicitly name
matching witnesses. The unpaired-PRE negative control is refused; the paired
PRE run then executes every leg and fails on the original mechanism. This
prevents a POST helper from falsely validating an unfixed external handler.

The field/reply search receipts are `field-test-inventory.txt`,
`info-counts-test-inventory.txt` and `capability-test-inventory.txt` under
`docs/rlfix3/`. Existing foreign-filter INFO assertions are in B+; those rows
run on both arms. Feature split/armed × atomic 0/1 jobs cover INFO, limits,
edge encodings, servertail/CONFIG REWRITE and pushtear. B+ includes read-local
admission, MGET fence, GET-miss and delete batteries. Zero-copy, netcmd/config,
reply-off, input-bytes/query-statistics and filter jobs also run. INFO field
names, formatting and section selection remain unchanged.

The broad POST selection initially reported 202 pass / 18 fail: twelve unit
rows lacked freshness markers after the CONFIG REWRITE edit, and six zero-copy
results followed a busy-core boot refusal (including two unplanned boot-failure
rows). After relinking, the owning unit jobs pass **56/56**, including core/TSAN
witnesses and armed block-cache migration churn; the complete zero-copy matrix
above also passes. Broad PRE reported 154 pass / 18 fail: sixteen intentional
new-row failures and two servertail throwaway boot-port collisions. Its armed
feature rerun on odd listener/control ports passes **71/71**. The original
failed ledgers are retained; none is described as a full gate receipt.

Differentials use `tests/differ_gate.sh`, the Redis **7.4.10** oracle, all 47
standard generators, permanent seeds **7,19,20,23**, rotating seed **21**, both
atomic modes and four MULTI repeats. The same run ID fixes rotation across arms.

| Geometry / engine | PRE original run | POST original run |
| --- | --- | --- |
| Split / io_uring | 474 pass, 2 fail | 473 pass, 3 fail |
| Split / epoll | 471 pass, 5 fail | 475 pass, 0 fail |
| Armed fused / io_uring | 466 pass, 0 fail | 466 pass, 0 fail |
| Armed fused / epoll | 466 pass, 0 fail | 466 pass, 0 fail |

Every original split failure is a climon reader-control bind refusal or its
resulting missing-coverage summary. Focused reruns through the same differential
interface retain all five seeds and both atomic modes: PRE io_uring, PRE epoll
and POST io_uring each pass **10/10**. No Redis reply difference was observed.
TIME_WAIT evidence showed other lanes' outbound connections selecting even
source ports in this lane's range. Retries use odd listener/control ports;
private network namespace creation was refused by the host. Global networking
was not changed. One initial POST epoll armed attempt also failed to bind its
oracle; its failed startup log is retained separately from the completed run.

The armed harness deliberately skips its ten SORT legs because that generator
requires split 6:2 geometry; all ten run in each corresponding split matrix.
All eight armed lane-fired witnesses pass (four runs × two atomic modes), with
per-leg hit/fallback TSVs retained. Every split mode-equivalence check passes.
Successful complete runs observe **232/245 registered commands** in compared
replies/properties: the receipt records that coverage limit, not universal
command compatibility. `differential-summary.json` and the complete run logs
preserve the exact counts. `differential-evidence.tar.gz` retains per-leg
coverage, climon transcripts, seeds and directed gate plans. DIFF-TRK-1's redundant-invalidation-frame mismatch
was **not observed on PRE or POST** in this matrix; the bind refusals are a
different failure. This is not a statistical proof that the flake is absent.

The final `GATE_TEST_PORT=38891 python3 tests/gates_test.py` run passes
**72/72**, after the INFO pairing guard and after all lane servers/oracles stop
(`gates-test-final-quiet.txt`). Its 14 nested persistfix identity controls also
pass. Earlier attempts retain busy-scheduler deadline failures and mock-port
collisions; no timeout or assertion was relaxed. The separate fixture audit
still refuses only the unchanged maintainer-owned EXPECT count.

Debug sections were stripped from 45 disposable unit/helper executables,
saving **5,088,158,320 bytes**. Every SHF_ALLOC section is checked byte-identical
before/after, the four measured artifacts are preserved, and all 47 freshness
checks still pass (`build-cleanup.json`).

`efficiency` is **NOT RUN**: its release-build growth-time bounds and
`xshard_dispatch_scale.sh` measure performance, reserved for the maintainer.
The full `tests/gate.sh iteration`, ABBA, INFO latency and large-GET instruction/
copy-byte measurements are likewise **NOT RUN** for that authorization boundary.
All requested correctness work described above has run; no threshold,
tolerance or EXPECT constant is weakened to produce a pass.
