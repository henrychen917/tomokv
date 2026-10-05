# reorderscan: RO1 / RO2

Status: implementation and serverless checks complete; live gate and performance
are **pending mainline**. No server, load generator, benchmark, or gate was run.
No performance claim follows from the visit counts below.

Merged `origin/cpp` before editing: `f769efcdd764e5d93286f19f8998bfa616c1fab5`.
The task's `464704b07` starting point fast-forwarded to that revision.

* RO1: `cb510e877` — one older-prefix index per demotion commit.
* RO2: `60a1dcab1` — lazy construction backed by an IO-owned Long index.

## Implementation and invariants

RO1 leaves selection, selected-id order, reservations, scatter/error lowering,
publication, and partial-plan handling unchanged. `ShadowDemotionDispatch`
indexes the prefix older than the last selected read once. Each query masks out
its own id and all younger ids, checks the newest eligible Long's atomic state,
and permanently removes observed Done predecessors for this commit. IO owns
recycling throughout. Work is O(ROB window + demotion count), with at most one
classification visit per prefix slot and monotone removal of completed Longs.
It does not scan each selected read's prefix anew.

RO2 adds two **uninitialized** words at Client offsets 80 and 88, inside the
existing 80..127 padding. They are initialized only by the engaged parser while
`dispatch_id == 0`, before its first publication. Only R7 reads/writes them.
Client remains 1984 bytes, Rob remains 192 bytes, and existing member offsets
stay fixed; the default constructor's executable bytes remain unchanged.
There is no allocation, new knob, owner table, or retirement hook. Migration
carries the index with the Client and ROB, without a separately owned sidecar.

The index records eligible static Longs at all twelve explicit parser
publication sites, including scatter. Refused publication removes its entry;
retirement and Done are pruned lazily. Publication helpers for local errors
complete locally; transaction/special classes are excluded as before.
The generator checks the publication-site inventory. A stack-only lazy holder
constructs `ShadowDispatch` at the ordinary stamp consumer only after observing
a pending preceding Long. It also rejects a same-pass Long that completed before
its first short follower. The initial search keeps the original pass boundary;
later ordinary Long stamps retain their existing within-pass behavior.

No executor metadata write, ownership transfer, read retry, seqlock, in-place
write, or change to the scheduler's per-connection ordering is introduced.

## Serverless work counts

Counts are deterministic visits/constructions, **not instructions or timings**.
PRE uses the original `ShadowDispatch` scan; POST executes the production helper.
The index's classification visits and its Long-state probes both count as visits.

| Witness | PRE | POST |
|---|---:|---:|
| 8 pure-short demotions: visits/commit | 28 | 7 |
| 32 pure-short demotions: visits/commit | 496 | 31 |
| 64 pure-short demotions: visits/commit | 2016 | 63 |
| 8 real parser passes without a Long: constructions | 8 | 0 |
| Same real parser passes: prefix visits | 0 | 0 |
| Real foreign-owner Long control: constructions | 3 | 1 |
| Real foreign-owner Long control: visits | 3 | 2 |
| Existing one-read/one-Long demotion fixture, including parser visits | 1 | 2 |

The tight pure-short count is `N*(N-1)/2`, rather than the review's loose 4096
bound: a selected read scans only its strictly older prefix. The last row is
deliberately retained: this change does not reduce every individual commit's work.

`tests/reorderscan_unit.cc` also checks 1000 mixed commits with exact task ids,
order and shadow payloads, selective prefixes, special commands, completions
between queries and real ROB recycling. Its 52 no-Long synthetic passes make
zero constructions and zero scan visits. Done without retirement, completion
within the same pass, refused publish/reparse, and scatter Longs are covered.
Release and ASan/UBSan runs pass.

`tests/reorderscan_paths.cc` reuses the existing production parser fixtures
without changing them. `tests/reorderscan_witness.h` supplies counters only to
instrumented test TUs. The PRE production TU was read from the frozen base and
instrumented at its actual constructor/loop, not replaced with a model.
The restored per-read demotion scan fails the linear-work assertion. The PRE
production executable also fails POST's zero-construction assertion. Both
negative controls fail for the expected assertion, with no skip or tolerance.

## Byte identity and checks

All 84 non-R7 TUs were rebuilt after adding the Client declarations. Their 7553
executable sections (10,773,024 object bytes, including COMDAT copies) are raw
byte-identical to PRE. The existing `tools/lbstall_artifacts.py compare`, run on
object views excluding only the two `core/reorder.o` objects, passes **1221/1221**
selected hot bodies, both raw bytes and resolved relocation targets.

| Check and comparison | Result |
|---|---|
| `r7shadow_noop.py PRE POST --inventory splitlocal` | 396/396 off-path bodies identical |
| `reorder_noop.py PRE PAD-A --literal-pools --expected-functions 424` | 424/424 bodies identical, including armed bodies |
| `reorder_sync`: generator parity and stale-copy negative control | PASS |
| `reorder_engagement`: production and FIFO negative controls, both database runtimes | PASS |
| `reorder_identity`: candidate/FIFO twin, missing-symbol and changed-opcode controls | PASS |
| Existing `reorder-unit` / `r7shadow-unit` with legacy test-only alias | PASS |

The legacy unit fixtures refer to the removed `kGenthreadPipelineExBatchOps`.
Their initial build exposed that pre-existing missing identifier. Their four
release/sanitizer recipes now supply `-DkGenthreadPipelineExBatchOps=128`, retaining
the historical 128-task cases. Normal unit targets pass without caller-supplied
flags. Neither those fixtures nor their production geometry header was edited.
Production compilation and engagement checks use ordinary flags without the alias.

Reproduce the helper and existing unit checks with:

```sh
make -j2 build/reorderscan-unit build/reorderscan-unit-asan build/reorder-unit build/r7shadow-unit
build/reorderscan-unit
build/reorderscan-unit-asan
build/reorder-unit
build/r7shadow-unit
python3 tests/r7shadow_sync.py
python3 tests/r7shadow_sync_test.py
```

The linked-binary audit normalizes addresses while retaining instruction
operands, widths, literal values and resolved targets. This is not a claim that
the complete PRE/POST ELF files or linked addresses are identical. R7's code
size changes, so the default 14-cell null is still required.

The three gate row **bodies** were run independently as serverless checks; the
gate itself and both live boot modes remain maintainer-owned. **Zero gate rows
added or retired.** `tests/gate.sh` is unchanged: `EXPECT_QUICK=496`,
`EXPECT_FULL=513`; collection lines 3110–3112 remain above the quick exit at 3250.
No EXPECT or fixture edits were made.

## Frozen artifacts

| Arm | Path | `.text` bytes |
|---|---|---:|
| PRE | `build/reorderscan-pre/tomokv` | 7800640 |
| POST | `build/tomokv` | 7803216 |
| PAD-A | `build/reorderscan-padA/tomokv` | 7803216 |

SHA-256:

```text
b4400a927387580462cb8c4c55f6dfc653710c47a95dfaee2a44b666438b6643  build/reorderscan-pre/tomokv
eabe54591859a4a47e5a4597326536799dad919e1165e87e754bfe223548a37c  build/tomokv
140827c9edefcd8334a1ecf7f17df94b4dc24d41c4cc54c4afe59d532fba0dc4  build/reorderscan-padA/tomokv
```

**PAD kind A: PRE behavior with POST aggregate `.text` size.**
`tools/reorderscan_pad.py` links frozen PRE objects in their original order and
adds NOP padding. It does **not** match internal R7 function addresses; it is a
text-size control, with that limitation recorded in its receipt. The 424-body
audit proves preservation of PRE's audited instructions and literal operands.
The FIFO twin used by `reorder_identity` is a separate diagnostic artifact and
is not substituted for the engaged PRE/PAD comparison.

The compact receipt, binary digests and serverless logs are in
`docs/reorderscan/`. Full build logs, audit JSON/diffs, object views and witness
executables remain under `build/reorderscan-evidence/` and
`build/reorderscan-witness-{pre,post}/` in this worktree.

## Mainline measurement request

Use the gate's instrument at matched offered load, paired seeds and balanced
PRE/POST arm order. Add the labelled PAD-A arm to separate aggregate text-growth
effects; a flat PAD-A does not rule out all internal R7 placement effects.
Record achieved rate, cycles/op, instructions/op and IPC together. Do not judge
the lane from the visit counts or instructions alone.

All **server CPUs must be within 112–127**, per this task. Load generators must
use separate CPUs. The historical `calib/tailgen-run.sh` hard-codes server CPUs
0–31 and must not be invoked unchanged. Bind a fresh matching null to the actual
allowed geometry; historical 32-core measurements are not its control.

| Regime | Cells / arms | Required decision |
|---|---|---|
| Engaged standing curves | 1s, `--reorder 1`, GET:BITCOUNT 8:2 and 98:2, each at 880K/985K/1030K offered ops/s; PRE/POST/PAD-A | Matched achieved rate; short p99.9 and cycles/op improve or stay null; long-class p99/p99.9 and completion counts do not regress |
| RO2 no-Long floor | 1s `--reorder 1`, pure GET/SET p1/p8/p32, read-local 0 and 1; PRE/POST | No regression at matched load; explain cycles with instructions and IPC |
| RO1 demotion pressure | 1s `--reorder 1 --read-local 1`, GET p32 and MGET8 plus same-connection conflicting writes / enough lane pressure; PRE/POST | Nonzero `ReadLocalFallback*` deltas must prove actual demotion in both arms; no read/write or tail regression |
| Shipped default null | All 14 unchanged cells in `docs/lbplanner/generic-cells.txt`, `--reorder 0`; PRE/POST/PAD-A | Every cell stays within its matched same-binary band |
| Mode and command guard | Both modes; GET/SET/MGET/MSET p1/p32; gate reorder rows and `tests/gate.sh iteration` | Both modes boot; main commands and correctness carry zero regression |

Standing-curve population/settings remain those in the r7shadow program:
2M 64-byte short keys, 65,536 256-KiB BITCOUNT keys, 512 connections, Poisson
arrivals, max outstanding 64, overlap/atomic/key-LB/client-LB armed, initially
read-local 0. Preserve class-split tails, offered/achieved rates, omitted
arrivals, outstanding bound, pacing lag and drain time. An overloaded or
under-driven cell is not evidence of a win. The separate armed demotion cells
must actually open their intended window.

For correctness reproduction keep `--shards 16 --ratio $GATE_RATIO` and eight
CPUs (for example `GATE_CORES=112-119`), preserving the gate's 6 IO + 2 EX split
geometry. Do not replace it with a default boot.

Risks to resolve by measurement: an extra class test at engaged publication;
IO-only stores for Longs; added stack state; more metadata visits on a small
Long-rich demotion than PRE's early-breaking scan; and text placement despite
unchanged default-path instructions. Lazy sampling can observe a completion
later than the old pass-entry scan and omit that already-cleared hint. Task
selection, per-connection order and memory ownership remain unchanged.

Write the results to this worktree as `MEASURE-RESULT`; all rate/latency verdicts
are currently pending. No push was performed.
