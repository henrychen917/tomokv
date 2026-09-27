TomoKV wbrule2s — mainline handoff, 2026-09-25

Base: `32d27ee7562ed5a17ff889c0fe5cf250f3fdc63c`, branch `cx-wbrule2s`.
Production changes: `6fd3abc53`, `7343d0a32`, `92a866037`.
`build/tomokv` hard-codes the landed **1/2** composite policy in both physical
thread modes. `build/tomokv-2s34` is an isolated **2s-only 3/4** measurement arm;
its physical fused path remains 1/2. The second constant exists only under
`build/wbrule2s34-src`, with the exact overlay in `build/wbrule2s34.patch`.
There is no new production knob, selector, field, sidecar, timer or counter.

All compilation and executable witnesses used `taskset -c 112-127`; make used
`-j16`. No listener, server worker loop, benchmark, load generator, boot, or gate
was run. Nothing was pushed. Live correctness and performance remain with the
maintainer. The supplied w5-split34 measurements motivate this work; they are
**not measurements of these new binaries**.

**Diagnosis and publication.** PRE applies the composite only in physical 1s.
Coarse 2s PHASE 2 serves at most 16 live connections. With overlap enabled,
`run_split<1>()` uses `pipeline_pass`/`wb_gather` instead; that schedule gathers
at most 64 FIFO entries. A PHASE 2-only port would leave the supplied 16:16,
overlap=1 measurements' path unchanged. This port covers both schedules, as
required by window5's “2s paths and publication” section and w5-split34 patch.

`src/core/wb_rule.h` owns the common rule and FIFO selection. Coarse PHASE 2
calls the same `Phase2::serve` as fused, preserving each caller's existing coded
reply capability. The overlap adapter uses the same `defer` walk, retains its
first chunk's natural/shallow weave, IFID quantum, prefetch and send boundaries,
then continues in existing scratch-sized chunks through the captured set.
Deferred pointers rotate once and retain their lifetime/deduplication pin.
Callback arrivals cannot extend the pass. AOF refusal precedes selection;
a refusal before capture does not cause an immediate continuation loop.
Deferred work keeps the IO loop active and can complete without another enqueue.

The staging accessor, byte encodings and **entire acquire walk are unchanged
from the landed rule**. For n>1, open at 512 staged/prefix bytes or ceil(n/2)
contiguous Done commands. Acquire each Done before reading its reply descriptor;
stop at the first hole. Submitted send/segment bytes and negative retire-state
payload lengths remain excluded. n<=1 enters ordinary writeback, which still
must acquire Done before retirement. The 3/4 study changes only the split
fraction to ceil(3n/4), including physical 2s read-local.

IO owns the ROB frontiers and staged buffers in 2s. Ordinary owner-routed GET/SET
Done publications in the requested read-local=0 cells come from executors.
The literal claim that IO *never* produces Done is too broad: parser errors and
local special replies also publish Done (`src/core/io_loop.h:3672`, `:3732`,
`:3774`, `:3808`), and optional read-local execution is another exception.
The rule requires no exception to acquire/release publication for these paths.

The split-specific hazards are a dormant PHASE 2-only port, counting the scratch
capacity as a pass limit, releasing deferred pins, extending capture across
callbacks, parking with deferred work, bypassing AOF, and confusing the reader
capability with physical fused ownership. Directed controls cover these paths.
The port adds no IO execution of owner commands. The W4 witness that invokes
**the default** `ExLoop::drain_tasks<>` remains, with masked, unmasked and timed
variants and a doubled-default negative control. Its real GET handler observes
notification-batch boundaries at 32; an explicit test-only batch width cannot
make a widened production default pass. Parser widths remain fused 32/split 64.
No write ownership, migration, QSBR, atomic execution or read ordering code changed.

Cross-shard MGET still occupies one ROB slot. Before its retire hook assembles
output, a negative scatter marker contributes no borrowed payload bytes. An
8-key/64-byte MGET eventually encodes 572 bytes, but its pre-retirement estimate
can be zero. A partial p8 command prefix may wait for four completions with 1/2,
or six with 3/4. No speculative ScatterState read or reply-size publication was
added. This undercount and the longer walk are reasons to measure MGET and tails,
not evidence assigning a live regression to either mechanism.

**Artifacts.** The PRE is rebuilt from an archive of exactly the base commit;
its unpadded relink reproduces the full SHA-256. Both PADs are **A: behaviour
twins**: PRE behavior plus unreachable padding matching the corresponding
candidate's aggregate `.text` size. Individual function addresses/internal
placement are not matched. A gain also reproduced by PAD is not attributable
to the rule. All arms retain `.tdata=112`, `.tbss=480`.

| Artifact | .text bytes | Delta vs PRE | SHA-256 |
|---|---:|---:|---|
| `build/wbrule2s-pre/tomokv` | 7,550,604 | +0 | `61006776bdac2a47bf06465e008f82f550b964f0f487a84cc355e1002a530b05` |
| `build/tomokv` | 7,561,708 | +11,104 | `7cf45fbd74b45db6616e226857830155884bf0430833436fc1e7c78ad575d098` |
| `build/tomokv-pad` | 7,561,708 | +11,104 | `828260b446cb42c091a9135c3bbc59b002c3cb1aa8f9a08a6615ae05d18a57b1` |
| `build/tomokv-2s34` | 7,562,444 | +11,840 | `31fb0f797e0ab134e6877da0a0698e2df48670099e8bf7696474a28ff10a636e` |
| `build/tomokv-2s34-pad` | 7,562,444 | +11,840 | `71e342f55cedf57403b8e09735ffe696cf2ffa335ffbcd85be34685ec71d15f6` |

PAD receipts: `build/tomokv-pad.json`, `build/tomokv-2s34-pad.json` and
`build/wbrule2s-pads.json`. Both candidates grow; no inverse B control is included.

**Fused byte proof.** Both arms match PRE on every emitted function in
`core/genthread.o` and `core/reorder.o`, in both database namespaces:
**3,031/3,031 per arm**. The additional GET/SET audit matches **16/16 per arm**.
Total: **6,094/6,094** function comparisons. The proof compares opcode bytes
and resolved relocation targets, including complete fused PHASE 2 bodies;
only address displacements/debug information are excluded. It does not assert
identical whole-executable addresses. No compiler-budget adjustment was needed.
The split gather is a dependent template so it does not perturb fused template
instantiation order. All eight requested structure-size locks compile in both
namespaces, with no layout changes.

Canonical object-function inventory digests below are identical in PRE, 1/2 and
3/4. They hash sorted function symbols and code-plus-relocation digests, not ELF
debug sections. Every function and its PRE/POST digest is listed in
`build/wbrule2s-identity.json`.

| Fused object | Canonical SHA-256 |
|---|---|
| `src/core/genthread.o` | `2a1c239e760e1ec71aea5d5022ad46732881124ff4c4b899730690213879882f` |
| `src/core/reorder.o` | `eed643fa60a044f880acb158af2d538b5cb06b0bfba9d40ed49a300b2874aae1` |
| `db0/src/core/genthread.o` | `b5909e8712caebab712dcb3c7df9547e187a903aa163463a48bec60fdd08152a` |
| `db0/src/core/reorder.o` | `9e51925656c508bd8600226d04f50d938556a1e29e041cc3b1adc298c0d4969c` |

**Witnesses and negative controls.** Mainline 1/2: **179/179 strict outcomes**,
120 positives and 59 expected failures. The isolated 3/4 arm passes the same
**120 positive invocations**, with its independent split-fraction expectation
changed to 3/4. Negative controls belong to the production 1/2 gate suite; no
claim of 3/4-specific mutation testing is made. Every negative must exit 1 and
print its exact assertion; crashes, timeouts, missing markers and unexpected
successes fail the checker. Controls mutate production headers under `build/`,
then compile the same test and unchanged expected answer.

| Checker group | Positive | Required negative failures |
|---|---:|---:|
| policy | 18 | 18 |
| fused phase | 24 | 8 |
| stages | 10 | 2 |
| split-phase | 24 | 11 |
| split-overlap | 44 | 20 |

The policy suite retains exhaustive n=1..64/prefix checks with real ROB wrap,
511/512/513-byte thresholds, staged fill/send remainder/segments, submitted-byte
exclusion, coded/direct/spill/borrow+CRLF lengths, holes, poisoned markers and
observed acquire-before-field-read assertions. Its controls remove each clause,
use floor/whole fractions, cross holes, relax the acquire or pre-read fields.

Physical split fixtures check the fraction and byte boundaries through actual
PHASE 2 and both actual overlap orders. They also cover armed read-local and
its idle sweep; staged-only/p1; dead clients; stable rotation and deduplication;
completion without fresh arrival; a partial head plus 96 eligible followers
crossing scratch capacity; and 65 callback-producing originals whose callbacks
cannot extend the captured chunks. The tiny intercepted SQ forces multiple
submissions. AOF refusal is explicitly armed and must block retirement until
the durable frontier advances. Fixtures declare eight in-memory threads and
16 shards (split 6 IO + 2 EX), with no live ring submissions or server loop.

| New/retargeted control | Required failing assertion |
|---|---|
| split-policy; gather-policy, both orders | 2s uses exact composite fraction |
| split-local | 2s reader capability shares composite writeback |
| split-budget | exact mode-specific budget |
| split-aof; gather-aof, both orders | AOF refusal precedes composite selection |
| rotation / gather-rotation | deferred rotation preserves order |
| head / gather-head | younger eligible passes deferred head |
| pin / gather-pin | deferred lifetime pins kept |
| capture | callback cannot extend captured visit count |
| gather-capture | 2s callback cannot extend captured chunks |
| visit / gather-visit | deferred rotation preserves order |
| dead / gather-dead | dead entry removed and unpinned |
| work / gather-work | deferral alone is positive work |
| gather-chunks | 2s captured pass crosses scratch bound |
| retained split-ex | default split EX chunk remains 32 |

**Deletions.** File:line addresses here name the base `32d27ee75`, so removed
lines remain unambiguous. There is no `kServeBudget` reference in production.

| Deleted item | Replacement |
|---|---|
| `src/core/io_loop.h:5570`, `kServeBudget=16`, and stale allowance comments at `:5566` | Captured FIFO policy; no connection-count allowance. |
| `src/core/io_loop.h:5157` physical-fused-only policy selector and `:5160` split serve loop | Shared `Phase2::serve`, preserving encoding capability. |
| `src/core/reorder.cc:1317` generated selector and `:1320` split loop | Regenerated shared serve call. |
| `src/core/io_loop.h:4548` one-chunk gather visit bound | Shared eligibility selection with captured count carried across scratch chunks. |
| Old “2s never applies fused eligibility”, reader exclusion and fixed split-budget test expectations | Positive shared-policy expectations and controls for the new behavior; no gate row retired. |

**Selection cost at 16/128 pending connections.** These are single deterministic
serverless x86 instruction-step traces, with no clock or PMU counter. They are
not cycles/op, IPC, live instructions/op or performance measurements. `walk`
counts eligibility only; `select` additionally instantiates the production
FIFO/scratch selector on a fixture deque, including pop/rotation, pin changes,
chunking and any deque housekeeping. Neither includes AOF, IFID, retirement,
reply assembly or SEND. The wrapper/layout is a fixture, not the whole IO pass.
Repeat-string tracing can differ from a PMU's retired-instruction definition.

The p32 fixture repeats Done prefixes 8/16/24/32 with five reply bytes per Done;
MGET has eight Done command descriptors with unknown marker payload length.

| Fraction / scope | p32, 16 pending | p32, 128 pending | MGET p8, 16 pending | MGET p8, 128 pending |
|---|---:|---:|---:|---:|
| 1/2 eligibility walk | 6,988 | 55,764 | 2,820 | 22,420 |
| 3/4 eligibility walk | 8,772 | 70,036 | 3,796 | 30,228 |
| 1/2 FIFO selection | 7,334 | 58,511 | 3,166 | 25,167 |
| 3/4 FIFO selection | 9,118 | 72,843 | 4,142 | 32,975 |

For p32 this is 228/1,824 acquire probes with 1/2 versus 296/2,368 with 3/4.
For the full MGET p8 pipes it is 64/512 versus 96/768. The rule adds no persistent
allocation or scratch proportional to the captured set: overlap reuses its
64-entry batch. Existing deque rotation/block recycling can allocate/free.
Receipts and executable digests: `build/wbrule2s-costs.json`.

**Gate accounting.** Exactly **two added rows**, `split-phase` and
`split-overlap`, are emitted by `tests/gate.sh:1263`, collected at **line 2709**,
before the quick-tier exit at **line 2838**. No rows are retired or added after
that exit. The maintainer should change **EXPECT_QUICK 441 → 443** and
**EXPECT_FULL 457 → 459** (including iteration correctness). This lane did not
edit either constant. Gate shell syntax and generated R7 synchronization pass.
The iteration gate has not been run; required acceptance remains zero gating FAIL.

**Mainline cells and decision.** Run both candidates and their respective PAD A
against `build/wbrule2s-pre/tomokv` in 2s. The committed
`tests/wb_rule_2s_cells.txt` contains 16 cells:

- GET/SET p1/p8/p32, 512 connections: h53/h54, w2g8/w2s8, h21/h22.
- GET/SET p1/p8/p32, 4096 connections: w2c4kg1/w2c4ks1,
  w2c4kg8/w2c4ks8, w2c4kg32/w2c4ks32.
- MGET/MSET p8, 512 connections, eight keys per command: m62/m65.
- 8:2 GET:BITCOUNT latency tails: exact t03/t04, p8, 512 connections,
  16 generators and the instrument's 716,800/s total offered load.

Use 32 physical server cores / **16 IO : 16 EX**, overlap=1, read-local=0,
atomic=1, flip=0; throughput cells explicitly pin eight load instances. The
existing ABBA geometry supplies 128 shards at this ratio. Tail 8:2 is the
operation mix, not an IO:EX ratio. Keep key/client LB and offered load matched.
Record rates, cycles/op, instructions/op, IPC, commands/send, short/long
p50/p99/p999 and CDF attainment, with pacing/drain validity and identical-arm
spread. Rate at matched load and latency decide; instruction counts explain.
Do not import the older 3/4 result as the new arm's verdict, and do not call
identical-arm spread above 2% box noise. Compare each PAD's movement too.

The supplied historical result was GET/SET p32 +5.6/+5.0%, p8 +3.4/+4.4% at
512 connections; it establishes no result for 1/2 or the broader cells. Choose
1/2 only if the new breadth supports it. 3/4 is a study arm for the maintainer's
policy decision, not a second shipped constant. After selection, run the
iteration gate at its correctness geometry (16 shards, eight threads, 6:2),
including both boots, overlap 0/1 and read-local/reorder coverage.

Exact mainline commands below are a request only; none were executed by this lane.
Selected diagnostics/nulls report PARTIAL/exit 3; inspect their cell/null verdicts
rather than mistaking that for a full gate PASS. Keep runs serial on the quiet box.

```sh
cd /home/user/Projects/cx-final
wbrule2s_lane=/home/user/Projects/cx-wbrule2s
wbrule2s_pre=$wbrule2s_lane/build/wbrule2s-pre/tomokv
wbrule2s_common=(
  --cells "$wbrule2s_lane/tests/wb_rule_2s_cells.txt"
  --only h53,h54,w2g8,w2s8,h21,h22,w2c4kg1,w2c4ks1,w2c4kg8,w2c4ks8,w2c4kg32,w2c4ks32,m62,m65,t03,t04
  --reference-binary "$wbrule2s_pre" --build-reference 0
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt ''
  --max-instances 16 --ports 7933-7940
)
taskset -c 0-111 python3 tests/abbagate.py "${wbrule2s_common[@]}" \
  --candidate-binary "$wbrule2s_pre" --collect-null 1 \
  --output "$wbrule2s_lane/build/merit-wbrule2s-null"
for wbrule2s_arm in tomokv tomokv-pad tomokv-2s34 tomokv-2s34-pad; do
  taskset -c 0-111 python3 tests/abbagate.py "${wbrule2s_common[@]}" \
    --candidate-binary "$wbrule2s_lane/build/$wbrule2s_arm" \
    --null-result "$wbrule2s_lane/build/merit-wbrule2s-null/results.json" \
    --output "$wbrule2s_lane/build/merit-wbrule2s-$wbrule2s_arm"
done
# Mainline then adjusts the two expected row counts, and gates the selected landing.
# Use the mainline's normal tests/gate.sh iteration invocation and PMU instrument.
```

**Offline reproduction and bound evidence.** `build/wbrule2s-artifacts.json`
binds source clauses, reference documents, arm/PAD digests, witness receipts,
code identity and the cost traces. No file outside this worktree was edited.

```sh
cd /home/user/Projects/cx-wbrule2s
mkdir -p build/wbrule2s-pre-src
git archive 32d27ee75 | tar -x -C build/wbrule2s-pre-src
taskset -c 112-127 make -j16 -B -C build/wbrule2s-pre-src \
  BUILD_ROOT=../wbrule2s-pre all > build/wbrule2s-pre-build.log 2>&1
taskset -c 112-127 make -j16 all wb-rule-units
for group in policy phase stages split-phase split-overlap; do
  taskset -c 112-127 python3 tests/wb_rule_checks.py check "$group"
done
taskset -c 112-127 python3 tools/wb_rule_2s_artifacts.py prepare34
for action in identity pads costs audit; do
  taskset -c 112-127 python3 tools/wb_rule_2s_artifacts.py "$action"
done
taskset -c 112-127 python3 tests/r7shadow_sync.py
bash -n tests/gate.sh
```
