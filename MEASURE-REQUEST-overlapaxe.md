# overlapaxe: remove the split overlap experiment

Code and scoped proofs are complete on `cx-overlapaxe`; no push, benchmark, or gate run.
The maintainer still owns correctness gating and the matched null measurements below.
PRE is `6b50f447fcc5be467e9314d7c602b688755957b9`, reached by the requested
`git fetch -q origin cpp && git merge --no-edit origin/cpp` before inventory or edits.

Three qualifications are material:

1. **Hot-body identity fails.** The deletion changes generated fused and ordinary split bodies.
   Complete body receipts and a default-behavior PAD-A are supplied; no performance neutrality
   or improvement is claimed.
2. **The protected mkprobe campaign must use frozen PRE inputs.** Its native POST-root self-test
   refuses the changed headline hash. The unmodified tool passes its full self-test and recipe
   dry run from `build/overlapaxe/campaign-proof`, against the specified staged PRE server.
   The dedicated campaign recipe and everything under `build/mkprobe-mainline` remain untouched.
3. **PAD-A has a limited interpretation.** It restores the PRE overlap=0 observable data-plane
   behavior and zero INFO rows at POST addresses. It does not restore the retired CLI/CONFIG
   surface or create an independent old-instruction treatment. Thus it cannot by itself separate
   compiler instruction changes from address-layout effects. Only a null verdict is admissible;
   a non-null result requires investigation, not attribution of a gain to this cleanup.

## Inventory and removal

The inventory was committed first as `e7f22af1c`, before source changes:
[original inventory](docs/overlapaxe/inventory.md),
[every original reference, including archived gzip receipts](docs/overlapaxe/references-before.txt.gz).
[Edit anchors](docs/overlapaxe/edit-anchors.md) index every source/test/harness edit hunk by
PRE and POST file:line. Coordinates for deleted material below refer to PRE; surviving anchors
refer to POST. The retired aliases `x-overlap` and `thread-pipeline` were already rejected on PRE;
there was only one live server knob to remove.

| Surface | Removal / surviving anchor |
| --- | --- |
| Boot knob | PRE `src/core/config.h:357,840,1151,1240`: field/accessor, parser, help, validation deleted. POST `config.h:354` reserves the same four bytes; all following offsets stay fixed. |
| CONFIG | PRE `src/cmd/t_server.cc:338`: registration deleted; GET is `[]`, SET is the ordinary unknown-option error, and REWRITE emits no overlap directive. Registration remains around POST `t_server.cc:334`. |
| INFO | PRE `t_server.cc:2103,2155`: `overlap`, `overlap_enabled`, `overlap_schedule`, `overlap_passes`, `overlap_interleaved_passes` removed. POST INFO format `t_server.cc:2101` and reorder-only reporting remain. |
| IO schedule | PRE `src/core/io_loop.h:409,505,902,2277,3063,4190,5354,5528`: Pipeline/IoPipe selector, interleaved pass, IFID/WB stage helpers, depth gating, scratch and deferred pipeline callbacks deleted. POST `io_loop.h:408,432,502` uses the ordinary split loop and its existing fused specialization. |
| Owner execution | PRE `src/core/ex_loop.h:2230,2251,2305`: split opt-in and overlap witness removed. POST `ex_loop.h:2207,2230,2249,2301` retains ordinary split prefetch and unconditional eligible fused owner prefetch. |
| Generated reorder path | PRE `src/core/reorder.cc:67,728,1296,2067,3068`: mirrored overlap template arguments/helpers removed with `tests/r7shadow_sync.py --write`; generation check passes. Fused R7 remains. |
| Read-local split | PRE `src/core/rl2s.cc:75`: optional schedule choice removed; POST `rl2s.cc:72` preserves the ordinary read-local split schedule and fused-capable owner executor. |
| Fused launch | POST `src/core/genthread.cc:40`: ordinary IO loop, no Pipeline selector. Eligible owner prefetch remains independent of read-local and reorder. |
| Schedule storage | PRE `src/core/orthog.h:25` and `server.h:402`: overlap enum/counters/note method removed; POST `orthog.h:25` keeps reserved bytes and surviving reorder offsets/64-byte stride; `server.h:405` allocates only for reorder. |
| Header / writeback | `src/core/iopipe_pipeline.h` deleted entirely. `src/core/wb_rule.h:130` retains ordinary serve logic; overlap-only gather wrapper removed. `src/net/wb.h` loses only the obsolete caller comment. |
| Boot / configuration docs | `src/core/boot_support.h:26`, `tomokv.conf:117`, `docs/CONFIGURATION.md:50`, README, ARCHITECTURE, FINDINGS and GATES current descriptions no longer advertise the feature. Docs regenerated with `tests/docs_drift.py --write`. |
| Tests / active drivers | Removed feature axes/flags/witnesses from feature_gate, orthog, mode_equivalence, knobs, boot/config/INFO fixtures, reorder_flip, signalacct_live, splitlocal_live, tailgen_stall, bplus, resizefix, read_local_lane, rl2s, saturation controls, exbatch_directed and iopass validation. `tests/overlap.py` becomes `tests/mode_lane.py`, retaining read-local correctness. All exact hunks are in edit-anchors.md. |
| Harness probes | `tests/abbagate.py:1429,1442,2452`, abba_experiments, load_calibration and gateprod: overlap/x-overlap capability probes and alias translation removed. Dedicated negative tests retain the retired names. |

Unrelated range/key/version/barrier overlap is **NOT TOUCHED**. The inventory lists each such
source use separately, including `src/base/slice.h`, `src/store/flatstore_atomic.inc`,
`read_local*`, `tracking.cc`, `atomics_glue.inc`, and barrier-owner counters. Their synchronization,
ownership, immutable replacement, QSBR, RYOW and read-local conflict rules are unchanged in source.
The remaining `kGenthreadPipelineExBatchOps` test constant belongs to fused batch geometry.

Historical reports, recorded argv, patches and binary receipts continue to describe the experiment
as explored. They are not rewritten into false past measurements. In particular the three
`docs/gt13split2/run-*/feature-cells.json` files are execution receipts, not runnable cell recipes;
`docs/encodingfix/threshold-fixture-search.txt.gz`, `tests/gateprod-evidence/*.gz`, and the existing
`tests/standing-null/artifacts/*.json.gz` remain archived evidence. The old
`tools/boot_support_artifacts.py:227,231` overlap fields describe its frozen legacy formatter
fixture; that historical proof is not a current launch recipe and must be replayed on its frozen
source. No production overlap selector remains.

## Fused prefetch and gate coverage

`prefetch_owner_batch` retains the exact original ownership, scatter/cursor/random eligibility
and bucket/value hint walk, with `noinline, flatten`. The runtime selector still requires fused
placement, a batch larger than one, and no exact-slowlog escalation. A read-local-capable split
executor is not mistaken for a fused placement. No schedule counter or allocation is needed.
The release body has no test-witness storage or call.

`tests/owner_prefetch_unit.cc` exercises read-local 0 and 1, both modes, reorder 0, batch lengths
0/1/2/3/31/32/127/128, order, WATCH blocking/suffix parking, and slowlog eligibility. Its test-only
body-entry witness rejects a throwaway build with only the prefetch call removed:
[prefetch negative control](docs/overlapaxe/prefetch-control.json).
Both linked namespaces still contain **two prefetcht0 instructions** in the retained body.
[Body inventory](docs/overlapaxe/prefetch-bodies.json).

Only `writeback c12 split-overlap witnesses + negative controls` was removed from the gate.
The emitting loop is now `tests/gate.sh:1447`; its job is collected at **line 3256**, before the
quick exit at **line 3408**. Exact delta **-1 quick / -1 full**:
**EXPECT_QUICK 504 → 503; EXPECT_FULL 521 → 520**, changed in removal commit `0b54616a5`,
as specifically authorized by this task. The expected-label fixture documents this derivation;
its old source digest is provenance, not evidence that this lane ran a gate.

Every ordinary split correctness row remains. The 32-entry feature matrix plus three topology
rows remains 35 rows: the old overlap bit also selected client-lb and atomic parity, so it is now
explicitly the client-lb axis, retaining `atomic = read-local XOR client-lb` and `key-lb = reorder`.
The independent mode-equivalence driver's redundant overlap dimension collapses 32 → 16 boots,
preserving every thread-mode/read-local/reorder/atomic combination; this is not a ledger-row change.

## Cells and strict arm compatibility

The `ov` field stays in the shared grammar/receipt schema, fixed at **ov=0**. Removing a column
would change the protected campaign parser and historical receipt format. It is an assertion of
the surviving default, not a server flag. Historical IDs remain stable even where former pairs
now duplicate a schedule. There are 348 changed ov values in 25 text files, plus 15 removed argv
pairs in the unexecuted exbatch plan (26 files total); no measured result values were rewritten.

| File | Rows | ov=1 → 0 / argv pairs removed |
| --- | ---: | ---: |
| `docs/ccfix/generic14.cells.txt` | 14 | 8 |
| `docs/deadcode2/generic-merit-cells.txt` | 14 | 14 |
| `docs/deadfused/feature-cells.txt` | 32 | 14 |
| `docs/deadfused/generic-merit-cells.txt` | 14 | 14 |
| `docs/deadswitch/06-null14-cells.txt` | 14 | 2 |
| `docs/exbatch/generic-plus-cells.txt` | 23 | 23 |
| `docs/exbatch/measurement-cells.json` | 15 argv plans | 15 |
| `docs/iopass/split-cells.txt` | 2 | 2 |
| `docs/lbplanner/4096-cells.txt` | 8 | 8 |
| `docs/lbplanner/generic-cells.txt` | 14 | 14 |
| `docs/lbplanner/multidb-cells.txt` | 8 | 8 |
| `docs/lbplanner/multidb-info-cells.txt` | 4 | 4 |
| `docs/lbplanner/split-cells.txt` | 4 | 4 |
| `docs/rlfence2/generic-merit-cells.txt` | 14 | 14 |
| `tests/headline_cells.txt` | 181 | 101 |
| `tests/netio_cells.txt` | 32 | 16 |
| `tests/reorderwb_cells.txt` | 6 | 6 |
| `tests/signalacct_tail_cells.txt` | 8 | 8 |
| `tests/ttl_cells.txt` | 2 | 2 |
| `tests/wb_rule_2s_cells.txt` | 16 | 16 |
| `tests/wb_rule_cells.txt` | 7 | 7 |
| `tests/wbhybrid2_cells.txt` | 14 | 14 |
| `tests/wbhybrid_cells.txt` | 21 | 21 |
| `tests/wbknobs_sweep_cells.txt` | 2 | 2 |
| `tests/wbland_4096_cells.txt` | 12 | 12 |
| `tests/wbland_merit_cells.txt` | 14 | 14 |

The exbatch plan's generic source digest is refreshed. gateprod's frozen h01–h32 digest is
explicitly re-frozen to `575e12a3a3b737d3f149e8cf6d2dc8d2b5785e548df60088374449be65a4682d`;
its exact epoll-twin check and unsupported-input controls still pass.

[generic_merit_cells.txt](docs/overlapaxe/generic_merit_cells.txt) is the exact 14-line `/tmp`
source with only `ov=1` changed to `ov=0`; the `/tmp` source was never written.
[null-cells.txt](docs/overlapaxe/null-cells.txt) adds `s32g`, `s32s`, `s8g`, `s8s`: 2s GET/SET,
pipeline 32/8, rl=0, ro=0, ov=0, atomic=1, 512 total connections, eight load instances.
The resulting null has **18 cells**, all ov=0.

ABBA raises **KNOB_NOT_ACCEPTED**, naming the arm, knob and requested value, when any required
live knob is unsupported, including an explicit zero. It never drops that flag for one arm.
Explicit legacy reorder spelling remains mapped and reported. **RETIRED_KNOB** rejects ov!=0;
**RETIRED_OVERLAP_ENABLED** rejects a boot reporting any nonzero/invalid retired value before
population. For ov=0 neither arm receives `--overlap`; each must report absent or zero fields.
These failures remain counted FAIL rows, with no assessment. Unit tests exercise both arms,
off/on values, retired recipes/boot echoes, and the explicit reorder alias.

## Protected multi-key campaign

`tools/mkprobe_probe.py` and `tests/mkprobe_cells.txt` are byte-identical to PRE; the dedicated
recipe keeps its original five ov=1 rows. Nothing under `build/mkprobe-mainline`, including
`/home/user/Projects/cx-final/build/mkprobe-mainline`, was changed. The tool's `--overlap` emission
at **line 262** and INFO expectation at **line 476** are **left for the campaign; remove after it**.

There is a real conflict between converting active headline/wb recipes and the protected tool's
frozen hashes/imported instrument fingerprint. Running `python3 tools/mkprobe_probe.py --self-test`
from the POST root correctly fails with `frozen headline changed; re-audit recipes`. This failure
was not hidden or patched around. Instead the entire baseline `tests/` and `tools/` input tree
was archived under `build/overlapaxe/campaign-proof`; **544 files** match PRE byte for byte.
[Campaign input hashes and staged-binary digest](docs/overlapaxe/campaign-proof.json).

The requested equivalent proofs both **PASS**, with no server or load generator started:

```sh
cd /home/user/Projects/cx-overlapaxe/build/overlapaxe/campaign-proof
taskset -c 112-127 python3 tools/mkprobe_probe.py --self-test
taskset -c 112-127 python3 tools/mkprobe_probe.py --dry-run --mode null \
  --binary /home/user/Projects/cx-final/build/mkprobe-mainline/server/tomokv \
  --output /home/user/Projects/cx-overlapaxe/build/overlapaxe/campaign-dry-run
```

The snapshot can be reconstructed with `git archive 6b50f447fcc5be467e9314d7c602b688755957b9 tests tools`
into an empty directory. Run the upcoming campaign from its existing frozen input tree or this
snapshot, not the POST checkout. This preserves the old inputs; it is not a claim that an old
null matches the newly changed ABBA instrument. No campaign measurements were executed here.

## Builds, functional proofs and body audit

All builds use CPUs 112–127 and `make -j16`. PRE was built from an archived source tree under
`build/overlapaxe/PRE-src`, with `BUILD_ROOT=.../build/overlapaxe/PRE`. A full POST `make all`
compiled and linked both `tomo` and `tomo_db0`; `build/tomokv` is byte-identical to POST below.
[Proof commands, results, log digests and failed-attempt disclosure](docs/overlapaxe/proofs.json),
[passing logs](docs/overlapaxe/proof-logs.json.gz).

- Full `python3 tests/gates_test.py`: **66/66**, 76.071 s after compilation completed.
- ABBA self-test: **116/116**, plus imported 10/9/16-test suites; gateprod: **8/8**.
- Docs/knob drift: **88 spellings**, positive and negative controls; regenerated envelopes match.
- **70** serverless native/source-control invocations: both namespace CONFIG knob/INFO/rewrite
  fixtures, owner prefetch, reorder engagement and split witnesses, ordinary split writeback,
  completion rules, forwarding/parking source mutants. No test assertion was relaxed.
- **8 smoke boots**: POST and PAD-A × 1s/2s × databases 1/16, pinned 112–119 with shards=16;
  split uses 6 io + 2 ex. PING, SET/GET, MSET/MGET and retired CONFIG behavior pass.
  Every owned process was reaped with a clean shutdown report. CLI overlap/x-overlap/thread-pipeline
  diagnostics match a wholly unknown option in both modes/namespaces. These short boots follow
  task step 6's explicit exception; no benchmark or gate was run.
- Offline gdb checks: all eight required size locks and every surviving member offset in
  Op/Client/ThreadCtx/Shard/FlatStore/AtomicEntry/Config/IoLoop/ModeScheduleStats match in both
  namespaces. Config's four-byte reserved slot and the schedule sidecar's reserved regions are
  intentional layout preservation, not live knobs. [Layout receipt](docs/overlapaxe/layout.json).

The earlier-lane `tools/ccfix_audit.py` was used unchanged against every PRE/POST object, including
both namespaces. It records raw bytes separately from relocation-aware identity (opcodes, member
offsets and callee identities retained). **17,578 bodies: 15,016 equal; 2,562 changed/new/removed**.
The hot inventory has **1,771 bodies, 666 equal**. This includes renamed and removed template
specializations; it is not a count of 1,105 semantic regressions. All **10 GET/SET/MGET/MSET
handler bodies are raw-byte-identical**. The generic `cmd_*` regex also counts three removed
`Op::cmd_name` emissions; the only changed actual command handler is INFO (two namespaces/cold clones).

Every changed body has its object, full symbol/name, PRE/POST size and reason in
[changed-bodies.json](docs/overlapaxe/changed-bodies.json); [complete body inventory](docs/overlapaxe/bodies.json.gz)
and [hot subset / summary](docs/overlapaxe/body-summary.json) retain the audit evidence.
Some unchanged-source helpers are re-inlined or re-emitted after the large template deletion.
Those compiler consequences remain explicitly unresolved byte-level differences; they are not
silently declared neutral. There were no source edits to the store/read-local/tracking/atomic
implementations that this instruction audit also sees re-emitted in affected translation units.

| Object | Changed / added / removed bodies |
| --- | ---: |
| `db0/src/cmd/t_server.o` | 11 |
| `db0/src/core/genthread.o` | 143 |
| `db0/src/core/reorder.o` | 206 |
| `db0/src/core/rl2s.o` | 537 |
| `db0/src/main.o` | 359 |
| `src/cmd/t_server.o` | 11 |
| `src/cmd/xshard.o` | 2 |
| `src/core/genthread.o` | 143 |
| `src/core/reorder.o` | 205 |
| `src/core/rl2s.o` | 557 |
| `src/main.o` | 388 |

The linked fused prefetch body shrinks from 409 bytes (`tomo`) / 393 (`tomo_db0`) to 333 bytes,
because its optional overlap witness is removed. Its two prefetch hints and guarded owner walk
remain. Removing split selector branches/templates also changes default-path code generation;
therefore the original hot-body identity assertion fails and the null is mandatory.

## Artifacts and PAD interpretation

| Arm | Path | SHA-256 | .text bytes |
| --- | --- | --- | ---: |
| PRE | `build/overlapaxe/PRE/tomokv` | `d139f5ae1101bd19c9f35940fbd55d9d8f8c3ec7e53ae157cd86360e8b335b30` | 7,844,389 |
| POST | `build/overlapaxe/POST/tomokv` | `b692d35058948d20949870ef827d3118f7cd3479e2a4eb55544a22ce4cb110fe` | 7,580,741 |
| PAD-A | `build/overlapaxe/PAD-A/tomokv` | `d8b8d2c280c8094a147883a756555cc252f07a83bc23df99d415a10850b342ec` | 7,580,741 |

POST removes **263,648 .text bytes** relative to PRE; this is a binary size observation, not a
performance result. PAD-A is explicitly **kind A, default-behavior twin**: PRE overlap=0 semantics
in the requested 18 cells, at POST function/object layout. The prior-lane cold-INFO ELF technique
restores `overlap:0` and `overlap_enabled:0` through two INFO format-reference changes and an
appended read-only mapping. All original bytes otherwise match POST, and all **10,016 function
records** and section tables match exactly. Missing-retarget, moved-symbol and one-byte negative
controls are all rejected. [PAD proof and limitations](docs/overlapaxe/pad-proof.json).

The twin deliberately has the same default data-path instructions as POST; it is **not** a
restoration of PRE instruction overhead. This limits the requested layout-versus-behavior
separation, even though the observable default behavior and exact POST addresses are established.
No inverse PAD-B is supplied, and no claim is based on a text-size-only padding argument.

## Mainline measurement request — not executed

Use the gate's current instrument, immutable arm digests above, and
`docs/overlapaxe/null-cells.txt` (18 cells). Obtain a **fresh matched reference-versus-itself null**
for this exact instrument, cell source, geometry, load plan and reference binary; do not reuse the
protected multi-key campaign null or an earlier instrument's floors without its normal validation.

Then request these paired comparisons:

1. Matched headline vs **POST** (`build/overlapaxe/POST/tomokv`).
2. The same headline vs **PAD-A, kind A default-behavior twin** (`build/overlapaxe/PAD-A/tomokv`).
3. PRE vs the same headline is the baseline check if mainline has no already matched PRE receipt.

The configured reference in `tests/gate_measurements.json` is
`/home/user/Projects/bench-bins/tomokv-headline-82f266a62`, expected digest
`32b36ceed785c10a5daa52698ea0d6f3d13dee78a49f98e10c2e8d80cd803ec3`.
Use mainline's matched headline identity if it has advanced; record the actual digest.
Do not silently substitute a different binary or drop a rejected knob. A binary that reports
nonzero overlap under its default is not comparable with these no-overlap-flag recipes.

For the inherited generic shape, use the same reviewed 32-physical-core server / 80-core load
geometry as its matched mainline headline (normally server 0–31, load 32–111, no SMT, split 16:16,
fused 256 shards / split 128 shards), with the instrument validating it. The smoke's 8-core 6:2,
16-shard geometry is a correctness proof, not a substitute measurement geometry.
Keep keyspace/value sizes, offered load, connections and all surviving knobs identical between
arms. Preserve each cell's explicit generator count and rate/latency scoring; use the gate's own
PIN/ceiling/null rules if that offered load cannot be validated.

Record rate, cycles/op, instructions/op, IPC and the existing latency/starvation metrics per cell
with its matched null band. **The decision is no regression beyond the matched null**, not fewer
instructions or smaller text. Any significant change, or disagreement between POST and PAD-A,
blocks a neutrality claim and needs investigation. These artifacts cannot attribute an improvement
to removed overlap overhead independently of compiler/layout changes.

| Comparison | Rate / latency | cycles/op | instructions/op | IPC | Verdict |
| --- | --- | --- | --- | --- | --- |
| Headline → PRE | mainline pending | pending | pending | pending | unmeasured |
| Headline → POST | mainline pending | pending | pending | pending | unmeasured |
| Headline → PAD-A (A) | mainline pending | pending | pending | pending | unmeasured |

Commit sequence: `e7f22af1c` inventory; `0b54616a5` removal and exact row-count delta;
`47d6cd442` cells/harness; `70a1b99a2` scoped proofs/artifacts; final report commit follows.

## overlapaxe2

Continued on `cx-overlapaxe` from `2b61a1fec`. Fetched and merged
`origin/cpp` at `165d268bed1bae72947263fa951985d8a83eb0c8`; no push.
The owner has judged the earlier 18-cell POST and PAD-A (kind A, default-behavior
twin) nulls without regression and ruled "axe overlap". This follow-up is merge
maintenance and scoped correctness verification, not a new performance claim.

Resolved two conflicts: `tests/gate.sh` and
`tests/fixtures/nullrefresh-ledger-labels.json`. Both retain all eight aclkeys4
SWAPDB/XREAD wake rows and remove only
`writeback c12 split-overlap witnesses + negative controls`. The complete
`job_multidb` function and its collecting loop are byte-identical to `origin/cpp`:
`1s/2s × read-local 0/1 × atomic 0/1`. They never used the overlap feature axis.
The separate 32-cell feature product still uses client-lb with
`atomic = read-local XOR client-lb` and `key-lb = reorder`.
The fixture retains upstream's source digest and documents the one-row derivation.
As explicitly requested, the merge sets **EXPECT_QUICK=511; EXPECT_FULL=528**
(`512 - 1 = 511; 529 - 1 = 528`), retaining the upstream WAKE_RC LedgerWiring checks.

Merge commit: `56618ef9b`, parents `2b61a1fec` and `165d268be`.
The removed WB row's emitting loop is now at `tests/gate.sh:1449`, collected at
line **3269**; the eight multidb jobs are collected at line **3398**. Both precede
the quick exit beginning at line **3421** (count check at **3424**), so the exact
delta remains **-1 quick / -1 full**, with all eight new wake rows in both tiers.

Completed proofs on the merged tree, all drivers pinned with
`taskset -c 112-127`:

- `make -j16 all`: PASS; full release build compiles and links both `tomo` and
  `tomo_db0`, including the footprint static assertions.
- `python3 tests/gates_test.py`: **66/66 PASS**, 75.778 s, including the unchanged
  upstream LedgerWiring multidb cases for WAKE_RC 0/1/3 in both thread modes.
- `python3 tests/docs_drift.py --self-test`: **88 spellings PASS**, including all
  ten positive/negative self-test cases. `python3 tests/r7shadow_sync.py` and
  `bash -n tests/gate.sh` also pass. An initial optional envelope check used an
  unsupported `--check` flag and exited 2; the correct default check above passed.
- [Reproducible live driver](docs/overlapaxe2/run-live.py): **12/12 owned boots
  PASS**, `databases=1/16 × 1s/2s × read-local=0/1`, plus both atomic settings
  for db16. Every boot answered **PING, SET/GET, MSET/MGET**. The eight server
  CPUs are 112–119 (within the assigned 112–127); shards=16, split ratio=6:2,
  fused=8 threads, uring, key-lb/client-lb=1, reorder/flip-auto=0. INFO checks the
  exact PID/geometry and active reader threads whenever read-local is armed.
- Unmodified `tests/aclkeys_wake_state.py`: **8/8 PASS**, exactly
  `1s/2s × read-local 0/1 × atomic 0/1`, db16, a fresh map per boot. This includes
  split and armed-fused with both atomic settings. Owner registration, the exact
  reply, and the original two-second wake deadline remain mandatory.
- Unmodified `tests/knobs.py`: **3/3 PASS**, split/read-local=0 with db1 atomic=1
  and db16 atomic=0/1, including retired knob rejection, live encoding controls,
  and actual geometry checks. Every owned PID was reaped with rc=0, no forced
  kill, a clean shutdown report, and the listener confirmed closed.

[Live results](docs/overlapaxe2/live-results.json) and
[complete proof logs](docs/overlapaxe2/proof-logs.json.gz) retain the evidence.
`tools/mkprobe_probe.py` and `tests/mkprobe_cells.txt` are byte-identical to
`2b61a1fec`; `build/mkprobe-mainline` is absent in this worktree and was never
created or written. [Protected-input hashes](docs/overlapaxe2/protected.json).
No gate, benchmark, or load generator was run; the short live proofs are the
explicit exception requested by this task.

`build/tomokv` and refreshed `build/overlapaxe/POST/tomokv` are byte-identical,
SHA-256 **`3ec6574798039760af4fd6497eb3e08d72f4c16a0f0ebaade66ac611efd3be79`**.
The earlier POST digest above now refers to the saved premerge binary at
`build/overlapaxe2/premerge-POST/tomokv`; the old PRE/PAD-A remain historical
artifacts, not rebuilt arms for this merge.

The [merge checks](docs/overlapaxe2/merge-checks.json) also compare all **35**
feature-cell configurations and refusal decisions with upstream: every surviving
knob and geometry matches after deleting only `overlap`. Both `job_multidb` and
its collecting loop, the wake script, and the WAKE_RC unit-test method are
byte-identical to upstream.

Repeated body audit, against an isolated archive of `165d268be` under
`build/overlapaxe2/BASE-src`: the base's full `make -j16 all` build passes on
CPUs 112–127, and all **213** archived files match upstream Git blobs.
[Build/source identities](docs/overlapaxe2/build-identity.json) record GCC 13.3.0,
commands, hashes and text sizes. Base `.text` is 7,845,932 bytes and POST is
7,582,188 bytes, a reduction of 263,744 bytes; this is not a rate measurement.

The unchanged checker was run as:

```sh
taskset -c 112-127 python3 tools/ccfix_audit.py \
  build/overlapaxe2/BASE build build/overlapaxe2/body-audit
taskset -c 112-127 python3 docs/overlapaxe2/summarize-bodies.py
```

**Hot-body identity still FAILS**, exactly as disclosed in the original report;
the checker exits 1 with `ordinary hot-path bytes changed`. It inventories
**17,600 bodies: 15,036 equal; 2,564 changed/new/removed**. The hot inventory is
**1,771 bodies: 666 equal; 1,105 changed/new/removed**. Every hot record has the
same symbol, equality/raw-equality verdict and PRE/POST size as the original
audit: **zero hot inventory signature differences**. This reproduces the earlier
audit outcome, not a claim that all fused code is byte-identical.

Both fused `genthread.o` objects together have **1,638 bodies: 1,352 equal,
286 changed** (143 per namespace). Their hot subset is **296: 108 equal,
188 changed**. All **10 GET/SET handler bodies remain raw-byte-identical** to
the merged base. The linked fused prefetch bodies retain two `prefetcht0`
instructions each: BASE 409 bytes (`tomo`) / 393 (`tomo_db0`), POST 333 / 333;
the overlap witness is removed, and no split prefetch body survives in POST.

Every changed body has its object, mangled symbol, full name, sizes, equality
flags, and reason in [changed-bodies.json.gz](docs/overlapaxe2/changed-bodies.json.gz).
The [fused-only list](docs/overlapaxe2/changed-fused-bodies.json.gz) contains all
286 changed fused-object bodies with their reasons; the
[complete inventory](docs/overlapaxe2/bodies.json.gz) and
[summary](docs/overlapaxe2/body-summary.json) preserve the full result.
Renamed/deleted overlap templates, retired CONFIG/INFO rows, the prefetch witness,
and compiler re-emission of unchanged helpers account for these recorded
differences; unresolved compiler differences are not silently counted as equal.

Four non-hot records are newly unequal compared with the earlier audit:

| Body (`tomo` namespace) | BASE → POST bytes | Reason |
| --- | ---: | --- |
| `cmd_config` in `src/cmd/t_server.o` | 7,347 → 7,393 | Retired CONFIG registration changes cold table/dispatch code generation. |
| `command_client_migration_extract` in `src/cmd/t_server.o` | 624 → 640 | Function source unchanged; re-emitted after overlap CONFIG/INFO deletion in the same translation unit. |
| `normalize_multi_blocking_pop` in `src/cmd/xshard.o` | 3,454 → 3,308 | `xshard.cc` is identical to upstream; included-header/template reduction changes compiler emission/inlining of retained ACL/blocking normalization. |
| Its `.cold` clone in `src/cmd/xshard.o` | 45 → 45 | Compiler stack slots change: LEA `0x50 → 0x40`, saved canary `0x148 → 0x138`; equal size is not byte identity. |

`snapshot_command` and `reply_err<Op::Sink>` in `src/cmd/t_server.o`, previously
unequal, are now equal. The only unequal actual command handlers are CONFIG
(`tomo`) and INFO (both namespaces and cold clones); the generic handler regex
also includes three removed `Op::cmd_name` emissions. No normalization, assertion,
or deadline was weakened to obtain these results. An initial report-generator
assertion counted split prefetch symbols as fused; filtering the explicit
`ExLoopT<true>` symbols corrected the report only, without changing the auditor.

The earlier owner-judged 18-cell null remains the landing decision. These are
merge correctness/body receipts, with no new performance result or fresh PAD arm.
All requested work is committed on `cx-overlapaxe`; no push.

## overlapaxe3

Continued from `61cb3771417cce25df6d1eecfb6a161d6cf93739` on `cx-overlapaxe`.
First ran `git fetch origin && git merge --no-edit origin/cpp`; the branch already
contained upstream `165d268bed1bae72947263fa951985d8a83eb0c8`.
All requested builds and proofs used **`taskset -c 112-127`**.
The three failed landing rows now pass their exact underlying commands.
No server, load generator, measurement, or full gate was started; no push.

The fixes and their assertions:

1. **FIFO identity.** `tests/reorder_noop.py` now recognizes
   `run_loop<HasUnix, HasTls, kEp, Fused, SplitLocal>` and
   `parse_and_dispatch<NoBorrow, BatchOps, SplitLocal>`, including the generated
   R7 envelopes in both `tomo` and `tomo_db0`. Historical disabled Pipeline/IoPipe
   arguments map to the surviving signatures; enabled historical policies and
   every surviving argument remain distinct. Self-checks cover those mappings,
   argument changes, and unexpected loop arities.

   The first rerun exposed further stale parser/body inventory expectations.
   `r7shadow_noop.py` now has an explicit `overlapaxe` inventory, selected by
   `reorder_receipt.py`; historical inventory choices remain available. The new
   inventory requires all surviving split-local parser families, their ordinary
   parser clones, all 16 split-local writeback specializations per namespace,
   and the renamed fused `prefetch_owner_batch`. The comparison still checks
   registers, operands, instruction encodings, clone counts, and off-path call graphs.

   The independently inspected upstream and current binaries give this physical
   body derivation **per namespace**:

   | Audited category | Before removal | After removal |
   | --- | ---: | ---: |
   | IO envelopes | 92 | 60 |
   | Parser bodies and closures | 42 | 28 |
   | Scheduler bodies, including owner prefetch | 32 | 31 |
   | Retirement helpers | 8 | 4 |
   | GET/SET commands | 8 | 8 |
   | Multi-key commands | 16 | 16 |
   | **Total** | **198** | **147** |

   The IO delta is 16 overlap loop specializations plus 16 pipeline passes;
   retirement loses four `wb_retire_prepare` helpers. The split owner-prefetch
   specialization is removed and its fused counterpart remains required under
   its new name. Split-local parser families retain two conflict closures and
   one filler closure per NoBorrow value. Full symbol/clone inventories are in
   [identity.json.gz](docs/overlapaxe3/identity.json.gz).

   Final result: **294/294 identical bodies**, 147 in each namespace.
   Removing policy symbols, removing a split-local parser, and changing an opcode
   all fail the existing negative controls. The offline FIFO twin is **PAD kind A:
   FIFO behavior at candidate text size/layout**; it is a correctness witness.

2. **Multidb unit build.** The failure at `src/core/io_loop.h:503` was
   `static_assert(!SplitLocal || Fused)`, a template-policy assertion. **No layout
   assertion or member offset shifted.** `tests/mdbqsbr_unit.cc` still supplied
   the removed fifth Pipeline argument: its old `1` became `SplitLocal=true`
   while `Fused=false`. Removed the retired overlap axis and supplied the current
   calls with default `SplitLocal=false`. Both modes, both reorder request values,
   and both IO/EX role transitions retain their original scope, acknowledgement,
   reclamation, and fresh-window assertions. The production assertion is unchanged.

   Reproduced the original ASAN/UBSAN compilation failure first (make exit 2).
   The full production build then passed, including the ASAN dependency of
   `multidb-unit`; all **28/28** gate readiness checks (`make -q`) passed. Both
   `mdbqsbr-live-arms` binaries also build successfully. This was an incremental
   build: unaffected targets were verified up to date. The serverless owners row
   passes, including all **18 rejected fault controls** and the production
   deadline control's expected SIGABRT/participant diagnostic.

3. **Full receipt inventory.** `tests/gate_receipt.py` independently requires
   the surviving `mode × read-local × reorder` products with `ov=0`, plus the
   mixed, connection-count, atomic-off, and reorder-tail regimes. It requires
   **98 geometries**; the unchanged 181-row file contains 100 distinct geometries.
   The remaining two are supplemental read-local reorder-tail geometries; every
   current row remains part of the receipt.

   `test_full_inventory_cannot_retire_a_multikey_geometry` first accepts the
   complete fixture, then replaces **both** duplicate MGET IDs `m01/m13`, and
   separately both MSET IDs `m04/m16`, with single-key rows. Each control preserves
   the 181-row count and fails with **`retired 1 required cell geometries`**.
   The full receipt self-test passes: 18 primary controls, plus its 10/27/10/1
   fixture, promotion, holdout, and refreeze suites.

Exact row commands, each exit 0:

```sh
taskset -c 112-127 python3 tests/reorder_receipt.py build/tomokv build/overlapaxe3/reorder_identity/receipt
taskset -c 112-127 ./build/multidb-unit
taskset -c 112-127 python3 tests/mdbqsbr_checks.py build/mdbqsbr-unit
```

The ABBA row ran **all 15 Python commands** from `job_abba_selftest`, in gate order,
each prefixed with `taskset -c 112-127 python3`: `abbagate.py --self-test`,
`gate_quiet.py --self-test`, `gate_measurements.py --self-test`,
`gate_receipt.py --self-test`, `abba_instrument.py --self-test`,
`background_environment_test.py`, `gate_history.py self-test`,
`gate_process_test.py`, `gates_test.py`, `gate_subset_test.py`,
`wb_policy.py --self-test`, `lb_stationary.py --self-test`, `netio.py --self-test`,
`gateprod.py --self-test`, and `tailgen_stall.py --self-test` (all under `tests/`).
Every command exits 0. ABBA's primary suite is **116/116**, plus 10/9/16 imported
tests. **`python3 tests/gates_test.py`: 66/66**, 74.964 seconds, with its embedded
14-test suite also passing.

The complete production build commands were:

```sh
taskset -c 112-127 make -k -j16 \
  build/at15-unit build/at15-db0-unit build/execabort-watch-unit build/execabort-watch-db0-unit \
  build/core-concurrency-unit build/atomic-survivors-unit build/netcmd-unit build/encodingfix-unit build/netcap-unit \
  build/waits-unit build/rehash-waits-unit build/multidb-unit build/multidb-boundary-unit build/storesize-unit \
  build/exbatch-unit build/exbatch-db0-unit build/wb-rule-units build/wbland-units build/rltopo-unit \
  build/lbplanner-units build/shutdown-unit build/persistfix-units build/ktls-keyupdate build/ktls-keyupdate-unit \
  build/flushfix-units build/splitlocal-unit build/reorder-engagement-unit build/reorder-engagement-unit-db0
taskset -c 112-127 make -j16 mdbqsbr-live-arms
```

[Commands, exit codes, timings, readiness checks, and hashes](docs/overlapaxe3/proofs.json)
and [complete proof logs](docs/overlapaxe3/proof-logs.json.gz) include the original
ASAN failure and the intermediate identity failure before the parser inventory
repair. Raw outputs remain under `build/overlapaxe3/`.

`src/`, `Makefile`, `tests/gate.sh`, the ledger-label fixture, and the headline
cell file are unchanged from the starting commit. **Rows and EXPECT remain
511 quick / 528 full.** `tools/mkprobe_probe.py` and `tests/mkprobe_cells.txt` are
byte-identical to the starting commit. `build/tomokv` still has the overlapaxe2
SHA-256 `3ec6574798039760af4fd6497eb3e08d72f4c16a0f0ebaade66ac611efd3be79`.
No new performance measurement is requested for these harness-only repairs.

Code commits: `8610565df` (QSBR fixture), `9a921c481` (FIFO identity),
`cb25f1ad3` (receipt inventory). The report and proof archive are committed
separately; the worktree is left clean.
