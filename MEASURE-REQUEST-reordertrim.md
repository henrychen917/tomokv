# reordertrim: numeric 0/1, fused shadow priority only

Owner-directed cleanup, not a performance proposal. Branch `cx-reordertrim`.
PRE source is `9f5ec71ed`; its only difference from the requested `7cc0607da`
is the already-present gate reference metadata commit. No server, load generator,
benchmark, gate, or performance measurement was run by this lane. Builds and
serverless/static checks were pinned with `taskset -c 112-127`; make used `-j16`.
Nothing was pushed.

## Changes and surviving selectors

Deletion locations below refer to **PRE** (`7cc0607da`); replacement locations
refer to the final source.

| Removed | PRE location | Result |
| --- | --- | --- |
| AUTO sentinel, parser arm, validation exception, help spelling | `src/core/config.h:386`, `:835`, `:1073`, `:1142` | Numeric 0/1 only; default 0. Both parsing and validation report `--reorder wants 0 or 1`. Help at final `:1071`; config example updated. |
| QueueSample, InboxProbe, AutoPolicy, PolicyScope, policy lookup | `src/core/reorder.h:133`, `:141`, `:174`, `:214`, `:230` | Only `priority_enabled(uint32_t)` remains at final `:133`, returning `requested != 0`. |
| Policy pointer and packed AUTO diagnostics | `src/core/orthog.h:36` | Named `reorder_reserved[16]` at final `:36`; no surviving member moves. |
| AUTO INFO aggregation and its three fields | `src/core/reorder.cc:21` | Removes `reorder_auto_samples`, `reorder_auto_engaged_owners`, `reorder_auto_engagements`. Ordinary reorder counters stay. |
| Armed role scope and sampled-depth policy tick | `src/core/reorder.cc:995`, `:1084`; `tests/r7shadow_sync.py:78`, `:90` | Regenerated from the edited generator. The ordinary depth/CPU/age sampling beat stays. |
| Dead split entry envelopes and declarations | `src/core/reorder.cc:3923`, `:4173`; `src/core/io_loop.h:5762` | Neither split reordered entry remains, in either database variant. |
| Exclusive split owner/pipeline emission roots | `tests/r7shadow_sync.py:17`, `:125`, `:128`, `:131`; `tools/reorder_sync.py:12`, `:86` | Removes copied executor `run`, interleaved-read drain, batch wrapper, both explicit `r7_run` instantiations, IO `run_split`, collect-retire and pipeline/WB copies. |
| AUTO-only queue observation helpers and friendship | `src/core/signal.h:537`, `src/exec/masked_queue.h:550`, `src/core/thread.h:52`, `:1141` | No observer, forward declaration or friend remains. No queue data fields changed. |

The **shared fused owner sweep stays** (`src/core/reorder.cc:737`): fused idle
and parking passes still reach the shadow drain. A new direct sweep witness
protects that shared dependency, with a throwaway FIFO-sweep negative control.
`tools/reorder_sync.py` now delegates to `tests/r7shadow_sync.py`, retaining only
shared extraction/renaming helpers. Both check commands pass. All generated
changes came from `tests/r7shadow_sync.py --write`.

The selectors are unchanged:

```cpp
// src/core/config.h:435
return mode == ThreadMode::Fused ? requested : 0;
// src/main.cc:192, after validation and capability resolution
cfg.reorder = reorder_for_mode(cfg.reorder, cfg.thread_mode);
// src/core/server.h:245, also covers serverless initialization
cfg_.reorder = reorder_available() ? reorder_for_mode(cfg_.reorder, cfg_.thread_mode) : 0;
```

`IoLoop::run()` still selects ordinary split code; split read-local calls
`run_split_read_local_baseline()` directly (`src/core/reorder.cc:3792`). The
fused boot selector (`:3797`) still selects its armed TU only for nonzero reorder.
Schedule storage is still allocated only for overlap or effective reorder
(`src/core/server.h:361`). With both off, no schedule allocation exists; overlap's
independent storage is not attributed to reorder.

**`reorder_retired` stays.** It is not structurally constant: the expression at
`src/cmd/t_server.cc:2044` returns 0 for the fused-capable release and 1 for split,
absent server context, or the FIFO capability PAD. It reports capability, not
whether the requested knob is off. Existing instrument consumers still need it.

## Layout and code generation

| Type | PRE sizeof | POST sizeof |
| --- | ---: | ---: |
| Op | 336 | 336 |
| Client | 1984 | 1984 |
| ThreadCtx | 1408 | 1408 |
| Shard | 1440 | 1440 |
| FlatStore | 944 | 944 |
| Rob<64> | 192 | 192 |
| AtomicEntry | 144 | 144 |
| Config | 624 | 624 |
| ModeScheduleStats | 64 | 64 |

| ModeScheduleStats member | PRE offset | POST offset |
| --- | ---: | ---: |
| overlap_passes | 0 | 0 |
| overlap_interleaved_passes | 8 | 8 |
| reorder_batches | 16 | 16 |
| reorder_multi_client_runs | 24 | 24 |
| reorder_permuted_runs | 32 | 32 |
| reorder_max_batch | 40 | 40 |
| overlap_schedule | 44 | 44 |
| reorder_policy | 48 | removed; reserved bytes 48–55 |
| reorder_auto | 56 | removed; reserved bytes 56–63 |
| reorder_reserved[16] | — | 48 |

Config.reorder remains at offset 420. No locked struct size or surviving hot
offset moves. Static assertions now lock every surviving stats offset as well
as its size. Evidence: `build/reordertrim-layout-{pre,post}.txt` and the final
`build/reordertrim-dwarf-{pre,post}.txt` receipts for `tomo` and `tomo_db0`.

The exact shadow-stamp/candidate prefix (6,004 bytes) and queue/service/batch
scheduler suffix (17,732 bytes) of `reorder.h` match PRE byte for byte. Receipt:
`build/reordertrim-scheduler-source.json`. No shadow bit, FIFO, eligibility,
service-ratio, completion, barrier or atomic-hazard rule changed.

Compiled `-O2 -march=native` predicate probes, with the same ABI on both sides:

```asm
# PRE dynamic request (excluding CET/alignment)
cmp $-1, %esi
je auto
 test %esi, %esi
 setne %al
 ret
auto:
 mov 48(%rdi), %rdx
 xor %eax, %eax
 test %rdx, %rdx
 je done
 movzbl 544(%rdx), %eax
done: ret

# POST dynamic request
 test %esi, %esi
 setne %al
 ret
# POST constant 0: xor %eax,%eax; ret
# POST constant 1: mov $1,%eax; ret
```

Evidence: `build/reordertrim-priority-{pre,post}.{cc,s}`. The dynamic predicate
lost both AUTO conditional jumps and both policy loads. Constant-zero code was
already branch-free in PRE and stays so: the default serving loops never called
the armed predicate. There is no new default-path branch or per-operation work.

The linked-binary no-op audit passes **336/336 bodies**, **168/168 per
namespace**, including the surviving default command, parser, owner, IO and
read-local envelopes. See `build/reordertrim-final-noop/{audit.json,*.diff}`
and `build/reordertrim-final-noop.log`. The default db0 serving code generation
is unchanged. db0's cold config parsing and armed R7 code generation do change
as intended by removing AUTO and unreachable split code; the complete runtime
is not claimed byte-identical.

The actual linked `r7_drain_tasks<32,false,void>` wrapper is 127 bytes in each
namespace. It loads Config.reorder at offset `0x1a4`, tests zero, and chooses
FIFO or the unchanged shadow-capability arm. There is no -1 comparison or
policy-state access. Linked PRE/POST disassembly is retained in
`build/reordertrim-drain-{pre,post}-{multi,db0}.asm`.
`build/reordertrim-symbol-proof.json` confirms all retired split R7 symbols
are absent and the shared fused sweep survives.

The first audit caught two unrelated main-TU inlining changes. The existing
compiler-budget locks now use `large-unit-insns=146400` for multidb main and
`146214` for db0 main (both were 146255). No serving-path source was changed to
repair those differences. The witness now explicitly requires 168 bodies in
each database namespace and identical symbol/clone inventories. Its former
169-only assertion predated the dual runtime; no comparison, byte normalizer,
operand or exclusion was relaxed.

## Built arms and completed checks

| Arm | Path | .text bytes | SHA256 |
| --- | --- | ---: | --- |
| PRE | `build/pre/tomokv` | 8,215,789 | `1c9b2ed306bdc1262a6bc3367fb36880ca3cfc9c590b63b4972a4704c3b98375` |
| POST | `build/tomokv` | 7,425,795 | `b7b2edc9b8e61c57d4c4757ec1160e82d6d61cfec6a06d5be60bebf3103bdd47` |
| PAD-A | `build/tomokv-reordertrim-pad-a` | 7,425,795 | `93743c3f6379a645792fa27d23013dbec795ca5c387f89053e255ba42f0fedef` |
| PAD-B | `build/tomokv-reordertrim-pad-b` | 8,215,789 | `c22eca0c88992ad2e85cd0145007560859d24806578d0c1cdbfc86eb595fb3ec` |

POST deletes **789,994 bytes of .text**. Both variants built with the release
flags, without compiler warnings. The PAD receipts and complete arm hashes are
in `build/tomokv-reordertrim-pad-{a,b}.json` and `build/reordertrim-arms.json`.

PAD A is a **behaviour twin**: PRE FIFO (`--reorder 0`) serving behaviour with
POST's exact text size/layout. Run it with `--reorder 1`; both runtime capability
immediates are patched off. Every other byte, symbol and section matches POST.
It is not a PRE AUTO control. Its INFO capability is deliberately retired.

PAD B is an **inverse control**: candidate behaviour plus unreachable padding
restoring PRE's `.text` size. It preserves the compiler's CET note. It matches
text extent, not the removed functions' internal placement. It is included
because the deletion shrinks text by much more than a few hundred bytes.
The request does not treat it as an exact internal-layout twin.

| Check | Result / evidence |
| --- | --- |
| Release, both variants and all listed unit binaries | PASS; `build/reordertrim-verified-build.log` |
| Numeric parser/config controls | PASS, 47 cases per namespace and 16 source mutants; `build/reordertrim-config-controls.log` |
| Shadow unit and legacy reorder unit | PASS; `build/reordertrim-r7shadow-unit.log`, `build/reordertrim-reorder-unit.log` (205 batch permutations plus continuous service) |
| Production engagement including fused idle sweep, shadow demotion, database dispatch | PASS in multidb and db0; `build/reordertrim-engagement{,-db0}.log` |
| FIFO PAD and shadow-only PAD through production engagement | PASS for both variants and both controls; `build/reordertrim-engagement{,-db0}-pad-{fifo,shadow}.log`, adjacent binary receipts |
| Split no-op/allocation witnesses | PASS in each variant: eight numeric cells, positive instrumentation control, eight parse/transient-allocation controls; `build/reordertrim-split{,-db0}.json` |
| Four surviving shadow-mechanism mutants | All rejected at their required assertions; `build/reordertrim-shadow-mutants.log` |
| New sweep-to-FIFO mutant | Required exit 1: `fresh production shadow drain did not engage`; `build/reordertrim-sweep-negative.log` |
| INFO/config, multidb | PASS; `build/reordertrim-netcmd.log` |
| INFO/config, db0 | Reorder INFO assertions pass, then the composite test fails at the existing unrelated tracking-map assertion; see attribution below |
| Legacy witness serverless self-test | PASS, 10 tests; `build/reordertrim-legacy-selftest.log` |
| Reorder scope harness self-test | PASS, 8 tests; `build/reordertrim-scope.log` |
| Both sync commands, Python syntax, gate shell syntax, diff whitespace | PASS |
| Layouts and default-path code | PASS in both namespaces; DWARF receipts and 336/336 byte audit above |
| PAD generation and inverse text extent | PASS: A changes exactly two capability bytes; B restores PRE .text and keeps all POST function addresses/sizes; `build/reordertrim-symbol-proof.json` |

**Existing db0 composite-test failure, retained:** `build/netcmd-unit-db0 config`
exits 1 at `FAIL: tracking map swapped` (`tests/netcmd_unit.cc:532`). The fixture
tries to swap databases 0 and 1 in a single-database runtime. A separate binary
built from original `7cc0607da` test sources and production headers, linked
against frozen PRE core objects, fails at the same assertion. See
`build/reordertrim-pre-source/{proof.mk,build.log,config.log}` and
`build/reordertrim-netcmd-db0-attribution.json`. No tracking behaviour or test
expectation was changed by this lane, and this composite test is not reported
as green. Its preceding reorder INFO checks ran successfully in both PRE/POST.

During development, the byte audit rejected the initial two default-path
inlining changes; the final budgets resolve them. Removing the split instantiations
also exposed a test fixture that had modeled a fused owner with `ExLoopT<false>`;
it now uses the production fused executor with a bound completion callback.
The shared fused sweep was retained after call-graph review and is now covered
by the directed negative control. These preliminary failures are not waived
final checks.

No live boot, gate, live legacy witness, throughput, latency, instructions/op,
IPC or cycles/op result is claimed. The legacy witness's serverless self-test
covers its actual verdict/protocol logic with mocked transport; its live
execution-order proof remains a mainline run.

## Boot proofs and negative controls for mainline

`tests/reordertrim.py build` compiles the production parser/validator/selector
into probes for both namespaces. `check` runs 47 checks per variant: 0/1 and
mode aliases, default, invalid values/words/missing tokens, canonical diagnostic,
and direct validation of 2 and UINT32_MAX. All 94 positive-contract checks pass.
Sixteen compiled source mutants are caught at their designated assertions:

| Assertion | Mechanism removed in the control |
| --- | --- |
| Reject -1 with accepted values named | Reintroduce the -1 parser arm, mapping it to 1 |
| Reject 2 | Raise both parse and validation ceilings to 2 |
| Fused 0 accepted | Reject 0 in the production parser |
| Fused 1 accepted | Reject 1 in the production parser |
| Split 1 resolves to FIFO | Make `reorder_for_mode` return the request in split mode |
| Fused 1 remains enabled | Make the selector always return 0 |
| Rejection names accepted values | Replace the diagnostic with `invalid reorder` |
| Post-parse validation rejects invalid stored values | Remove the validator's range guard |

Each control runs in both namespaces and must fail for the intended semantic
reason; crashes and unrelated diagnostics cannot count. These are real config
source mutations in throwaway probes, not claimed full-server mutant boots.
Receipts: `build/reordertrim-controls/{manifest,results}.json`.

Mainline should run the real executable matrix (32 accepted boots plus eight
refusals), with gate geometry: eight cores, shards 16, split ratio 6:2. It covers
`--databases 1/16`, both modes, both read-local and overlap values, and verifies
INFO's effective mode/reorder/capability/storage, no AUTO diagnostics, SET/GET,
child PID and clean shutdown. Its acceptance/diagnostic/value checks share the
same oracle as the source-mutant controls. Run only on the maintainer's quiet box:

```sh
taskset -c 112-127 python3 tests/reordertrim.py check
taskset -c 112-127 python3 tests/reordertrim.py boot \
  --binary build/tomokv --cores 112-119 --port 8894 \
  --output build/reordertrim-mainline-boots
```

Use an unused output directory; a busy port, unopened server, wrong INFO value,
missing stats or unclean shutdown fails. There are no skips or relaxed windows.
The separate production split witness checks allocation traces, and engagement
fixtures exercise actual parser/inbox/handler ordering in both database variants.

## Every retired test case

No row in `tests/gate.sh` was added or removed. Its quick exit is at line 2808;
there are **zero row changes on either side of that line**. Counts remain
**EXPECT_QUICK=438 / EXPECT_FULL=454** (lines 257/258); neither constant nor the
gate script was edited. These standalone/unit subcases were retired:

| Test | Removed rows/cases | Reason |
| --- | --- | --- |
| `tests/config_parser_test.cc:437` (PRE) | 32 accepted `reorder=-1` cells: four mode spellings × two overlaps × two read-local values × two engines | -1 must now reject; explicit rejection and negative controls replace acceptance. |
| `tests/r7shadow_unit.cc:212` (PRE) | `PASS AUTO occupancy 0.5x/1x/2x...`; `PASS derived AUTO thresholds, engage/disengage, role lifetime, 2s no-op` | Controller/window/lifetime gone. The surviving 0/1 and split resolution assertions moved into `numeric_policy`. |
| `tests/reorder_engagement_unit.cc:374`, `:581` (PRE) | One production AUTO probe/tick/engage/disengage row; two split -1 rows (read-local on/off); one database-parser -1 row, per runtime | No AUTO controller or accepted AUTO boot. Existing 0/1 order/database cases stay; a fused sweep case was added. |
| `tests/r7shadow_mutants.py:23` (PRE) | `auto-no-floor`, `auto-inclusive-floor`, `auto-never`, `auto-sticky` | Their controller no longer exists. All four shadow-mechanism mutants stay. |
| `tests/r7shadow_split_witness.py:57` (PRE) | Four raw -1 cells (overlap × read-local) and eight policy/sample leak controls | No accepted -1 or policy/sampler to leak. Eight numeric cells and eight parse/transient-allocation controls stay, in each runtime. |
| `tests/netcmd_unit.cc:410` (PRE) | Two forced raw -1 INFO cells (overlap 0/1), per runtime | Invalid stored boot state no longer represents a supported mode. Numeric INFO and retired capability cases stay; AUTO field absence is asserted. |

The existing no-op witness, FIFO PAD generator, shadow units, legacy witness and
sync commands remain. Live legacy inversion tests must use the capable fused
arm; split's contract is FIFO. The standalone legacy self-test remains intact.

## Exact measurement request — mainline only

Required outcome: **`--reorder 1` engaged tail behaviour UNCHANGED versus landed
PRE**, preserving the shipped roughly -12% to -17% fused p99.9 improvement at
880K–985K offered ops/s. **`--reorder 0` must be a pad-controlled null.** The
historical percentages are context, not measurements made in this lane.

| Arm label | Binary | --reorder | Purpose |
| --- | --- | ---: | --- |
| RT-PRE0 | `build/pre/tomokv` | 0 | Landed default reference |
| RT-PRE1 | `build/pre/tomokv` | 1 | Landed engaged reference |
| RT-POST0 | `build/tomokv` | 0 | Candidate default |
| RT-POST1 | `build/tomokv` | 1 | Candidate engaged |
| RT-PADA | `build/tomokv-reordertrim-pad-a` | 1 | Type A FIFO behaviour, candidate layout |
| RT-PADB0 | `build/tomokv-reordertrim-pad-b` | 0 | Type B candidate default, PRE text extent |
| RT-PADB1 | `build/tomokv-reordertrim-pad-b` | 1 | Type B candidate engaged, PRE text extent |

Run fused standing tail cells at **880K, 930K, 985K ops/s**, with the landed
32-owner tailgen geometry/mix, matched arrival seeds and balanced/interleaved
fresh boots. At least three boots per arm/cell; retain individual boots rather
than averaging away a bimodal failure. Primary comparison RT-PRE1 vs RT-POST1;
use RT-PRE0/RT-POST0/RT-PADA and both B controls to separate a scheduler change
from layout/size effects. Decide on paired overall and short-class p99.9 at the
same achieved load, retaining long-class progress and p99/p99.9. Collect INFO
before and after the window; permutations must increase in engaged arms.
An unopened engagement window fails and gets bounded fresh-state rearming.

Run split **985K** with PRE0/PRE1/POST0/POST1/PADA/PADB0/PADB1, read-local 0/1:
all requests must resolve to FIFO, and requested 1 must remain indistinguishable
from requested 0. Repeated per-boot separation is a failure, not box noise.

Run the gate's ABBA rate instrument on **h05/h07/h21/h23** and the zero-knob
regression cells **p8g0/p8g1/p8s0/p8s1/f8g1**, at each cell's qualified matched
offered load, preserving its normal geometry/knobs. Compare PRE to POST, PAD A
and PAD B; h07 supplies the engaged fused throughput control. Record rate,
cycles/op, instructions/op and IPC for every arm. Require POST0 to track PRE0
and the controls within the instrument's standing null; do not infer a gain
from fewer instructions or deleted text. Do not modify measurements/pins to
force a verdict. Repeat db0 and multidb boot correctness; prioritize db0 for
headline rate comparisons.

| Verdict | PRE | POST | PAD A/B |
| --- | --- | --- | --- |
| Engaged fused p99.9 and short-class tail | mainline pending | mainline pending | mainline pending |
| Default matched-load rate/cycles/IPC | mainline pending | mainline pending | mainline pending |
| Split requested 0/1 null | mainline pending | mainline pending | mainline pending |

Finally run the existing `tests/gate.sh iteration`, existing reordered feature
batteries and the appropriate live legacy witness. The maintainer tests, gates
and merges; this lane stops with the committed diff and these artifacts.

## Reproduce artifact preparation

```sh
# PRE was built before edits: taskset -c 112-127 make -j16 BUILD_ROOT=build/pre
# Rebuilding PRE later requires the recorded PRE source/Makefile, not POST sources.
taskset -c 112-127 make -j16 all build/reorder-engagement-unit \
  build/reorder-engagement-unit-db0 build/r7shadow-split-unit build/r7shadow-split-unit-db0
taskset -c 112-127 python3 tests/reordertrim.py build
taskset -c 112-127 python3 tests/reordertrim.py artifacts
taskset -c 112-127 make -j16 -f Makefile -f build/reordertrim-pad-b.mk \
  build/tomokv-reordertrim-pad-b build/reordertrim-sweep-fifo
# The sweep mutant must exit 1 at the production permutation/order assertion.
taskset -c 112-127 build/reordertrim-sweep-fifo on shadow
```

## Diff from requested base

The stat includes the inherited eight-line gate-reference metadata diff from
`9f5ec71ed`; this lane did not change that file.

```text
 MEASURE-REQUEST-reordertrim.md   | 372 +++++++++++++++++++++++++++++++++++
 Makefile                         |  18 +-
 src/core/config.h                |  16 +-
 src/core/ex_loop.h               |   6 -
 src/core/io_loop.h               |  13 --
 src/core/orthog.h                |  17 +-
 src/core/reorder.cc              | 412 ++-------------------------------------
 src/core/reorder.h               | 105 +---------
 src/core/signal.h                |   4 -
 src/core/thread.h                |   2 -
 src/exec/masked_queue.h          |  12 --
 tests/config_parser_test.cc      |   6 +-
 tests/gate_measurements.json     |   8 +-
 tests/netcmd_unit.cc             |   5 +-
 tests/r7shadow_mutants.py        |  14 +-
 tests/r7shadow_noop.py           |  13 +-
 tests/r7shadow_split_unit.cc     |  10 +-
 tests/r7shadow_split_witness.py  |  10 +-
 tests/r7shadow_sync.py           |  26 +--
 tests/r7shadow_unit.cc           |  53 +----
 tests/reorder_engagement_unit.cc | 112 +++--------
 tests/reordertrim.py             | 237 ++++++++++++++++++++++
 tomokv.conf                      |   4 +-
 tools/reorder_sync.py            |  59 +-----
 24 files changed, 738 insertions(+), 796 deletions(-)
```
