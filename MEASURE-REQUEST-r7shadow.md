# r7shadow: shadow priority over R7

Branch/worktree: `cx-r7shadow`, `/home/user/Projects/cx-r7shadow`.
PRE: `f139a1a34` (rebased R7 on v7). No server, benchmark, load generator, gate,
or measurement was run. Builds and executable unit checks used CPUs 112-127.
All performance cells below are pending; there is no performance claim.
Implementation/witness commits: `3fa91eb6d`, `aad7ee89a`; PAD builder: `d57018f91`.

**Cost qualification:** this is a correctness-tested candidate, not a claim that
the requested one-bit/one-compare cost envelope has been met. The dispatch range
comparison and shadow-bit test are present, but the implementation also needs a
bounded ROB scan at each armed parse pass, a connection index for mixed owner
runs, and completion probes at output-batch boundaries. Those additional costs
must be judged explicitly; they must not be described as one extra instruction
or zero instructions/op. The disabled-path byte witness is a separate result.

## Design and scope

`--reorder 0` uses the inherited ordinary parser/executor bodies. `--reorder 1`
uses the isolated R7 envelopes and the new shadow policy. There is no new knob.

The IO parser tracks the newest unfinished registered-Long command for the
connection. At a parse boundary it reconstructs that id from the connection's
live ROB, then updates it as it dispatches Long commands. An ordinary short task
captures its preceding Long as a distance in the existing negative `Task::shard`
payload, with a SHADOW bit. All negative values still mean “use Op::shard”; the
ordinary handle, inbox stride, and every locked layout are unchanged. Distance
is bounded by the 64-slot ROB. Special/scatter tasks retain their old handles.
No executor-written reply marker or route-flag byte is read by the IO scan;
only immutable command metadata and atomic completion states are inspected.

The stamp belongs to the short, so a later `L` cannot overwrite an earlier
short's blocker (`L0 s1 L2 s3` keeps blocker 0 for s1 and blocker 2 for s3).
An observed Done clears the shadow before retirement is required. Executors
inspect only the predecessor's atomic state and the ROB retirement frontier,
never a predecessor's recycled command metadata. There are no retries or
seqlocks. Completion is sampled at output-batch boundaries; an in-progress
selection of at most one batch is not restarted when a foreign owner completes.

Each executor keeps three ready FIFOs: unshadowed short, Long, shadowed short.
Only the first queued task of a connection is eligible. Picking it makes its
successor eligible in output order. Thus an ordinary `L s L` cannot turn into
`L L s`, and writes retain the owner's established per-connection execution order. For the
requested three pipes, all six leading shorts are selected before the three
Longs, followed by the seven shadowed shorts. The unit asserts the complete
deterministic permutation at both production batch capacities.

R7's empty-queue homogeneous and single-client bypasses remain. The connection
index is initialized only when a mixed run actually queues work. Capacity stays
two gathers; at most one gather is retained across admissions. No scheduler
state survives an inbox drain, ownership acknowledgement, local-read phase,
snapshot/control phase, or return to IO. Stamped tasks follow the existing task
transport/forwarding; there is no new shard-ownership sidecar to migrate.

LONG for the stamp means the registered command class. Atomic-hazard operations
keep R7's conservative Long **execution rank** and existing deferral checks.
Clean read-local service retains its existing scheduling. Ordinary owner tasks
synthesized by read-local demotion also receive a stamp, reconstructed from that
read's **older** ROB prefix, never from a Long dispatched after the read. The
isolated armed demotion plan preserves all original reservations and barriers.
Its EX callback is selected once at armed IO role entry in both modes. An older
read can legally arrive after a later independent operation through this existing
mechanism; the scheduler preserves that admitted owner order rather than sorting
or asserting increasing ROB ids. Real parser/demotion/handler tests cover that
window in both modes and PAD. The requested tailgen matrix uses read-local=0.

## Bound and barriers

Let B be the inherited gather capacity (32 or 128), C=2B its queue capacity, and
Q=4 the inherited service ratio constant. A new barrier scope gets B priority
picks; thereafter, each Q priority picks is followed by a forced pick of the
oldest queued task. That task is necessarily an eligible connection head.

An admitted task has at most C-1 older tasks. New admissions cannot precede it
on forced turns. Including its own pick, the conservative bound is

    K = B + C * (Q + 1) = 11B = 352 (B=32), 1408 (B=128).

This bounds scheduler picks, not time inside handlers or existing atomic waits.
The initial B-pick allowance accommodates the exact six-short example; a literal
4:1 class interleave would select a Long after the fourth leading short instead.
After the allowance, the ratio budgets forced oldest-task service rather than
only Long service, so shadowed shorts also cannot starve. The unit admits 48
gathers under continuous unshadowed arrivals and checks every task against K.
Removing the bound must fail that assertion.

The candidate predicate retains R7's thirteen special-command exclusions and
scatter/blocking/null/invalid exclusions. Encountering a barrier drains all
three queues, emits that barrier, then opens a fresh scope. MULTI/EXEC and real
atomic scatter fragments therefore cannot be crossed. If a barrier parks, the
existing `xshard_retries_`/`ordered_deferred_` path retains later selected work;
existing atomic hazard, parked-predecessor, and transaction dispatch checks are
unchanged. Reply retirement remains the same in-order ROB operation. No change
was made to reader algorithms, immutable replacement, QSBR, ownership, or writes.

## Armed-path costs

| Place | Work added/changed |
| --- | --- |
| Cold role entry | Select isolated IO/executor bodies; split read-local selector lives outside its baseline translation unit. |
| Armed parse pass | Capability selection; scan at most the live 64-slot ROB window for the newest unfinished Long; no allocation. |
| Ordinary dispatch | Immutable class check; compare current ROB id with newest Long; store/update the distance tag when relevant. |
| Mixed owner admission | Bounded open-addressed connection lookup, task copy and FIFO/dependency links; no heap allocation. |
| Output boundary | Check shadow-tagged pending entries for Done/retirement, promoting cleared ready heads. |
| Read-local demotion | Reconstruct the demoted read's older prefix and stamp its ordinary owner task inside the armed demotion plan. |
| Pick | Select ready tier or forced oldest task, advance the existing-ratio budget, activate the connection successor using its cached shadow bit. |
| Homogeneous/single-client bypass | Original span emission; no task queue insertion or connection-index initialization. |
| Disabled path | No shadow scan, scratch, table initialization, tag store, or per-operation policy branch. |

Static/source accounting is not dynamic instructions/op. Mainline should collect
cycles/op, instructions/op and IPC with its own instrument; rate at a matched
offered load and class-split tails decide merit. In particular, pure-GET/SET
regression controls are needed because parser scanning is armed even when a run
has no blocker. This candidate does **not** satisfy a literal “only one bit test
and one comparison of extra work” acceptance condition.

At B=32 the queue object is 6,200 bytes versus R7's 4,648 bytes; at B=128 the
shadow object is 24,632 bytes. This is stack scratch behind the armed drain, not
an addition to Client/Op/ThreadCtx/Shard. Homogeneous bypass leaves its table and
task slots uninitialized. These footprint/copy costs belong in the armed-path
judgment alongside the parser scan.

## Artifacts and PAD semantics

| Arm | Path | SHA256 |
| --- | --- | --- |
| PRE R7 | `build/r7shadow-pre/build/tomokv` | `e1c6c6dd1b7afecd24c53f088af809a87183be41c8e16cbb29392e69c06c3af1` |
| POST shadow | `build/tomokv` | `74721e4c4db1a64b2c83a48a8096d4e381207f5969cb604a23ee9ce33e7de216` |
| PAD A, R7 without shadow | `build/tomokv-pad` | `f7949d2a343e4757cb8ef9c8ecb8958decb60416580f3892e312e27da768b972` |

PRE .text = 3,749,267 bytes; POST/PAD .text = 4,171,745 bytes, +422,478 bytes.
PRE .rodata = 118,144 bytes; POST/PAD .rodata = 126,181 bytes. Much of the text
growth is the isolated armed parser/IO/demotion call graph required to keep the
ordinary translation units unchanged. This is material placement change, which
is why the exact-layout behaviour twin and PRE comparison are necessary.

PAD is kind **A, behaviour twin**: PRE **R7** scheduling behaviour in POST's exact
text size/layout. It disables only `tomo::r7::shadow_available()`, changing the
immediate of `mov $1,%eax` to zero in a copy of the linked ELF. Every other byte,
symbol address, section header, instruction size and padding byte is identical.
It does not disable `reorder_available()` or retire R7. Run PAD with `--reorder 1`.
INFO reports `reorder_shadow:1` in POST's armed policy and `0` in PAD's; the usual
R7 batch/permutation witnesses remain. The receipt is `build/tomokv-pad.json`.

`make -j8 build/tomokv-pad` now produces this control. The inherited
`tools/reorder_pad.py` is not the shadow PAD builder: it disables all of R7.

## Verification

All requested executable checks ran pinned to CPUs 112-127:

- Default `make -j8` and kind-A PAD build: PASS.
- `make -j8 unit`: PASS, including inherited R7's 205 exact permutations, the
  shadow unit, and flipctl's existing rows plus 12/12 rate-band rows.
- Shadow unit under ASAN+UBSAN: PASS. Both B=32 and B=128, exact three-pipe order,
  multiple Long stamps, Done before retirement, actual ROB reuse, same-owner
  dependencies, all thirteen special flags, atomic-hazard rank, queued foreign
  completion, and 48 gathers with immediate Client destruction. Observed maximum
  scheduler wait in that constructed stream: 64/256 picks, within K=352/1408;
  those are unit outcomes, not latency/throughput measurements.
- Production serverless engagement: **27 PASS checks per binary** for POST and
  its one-byte-patched PAD twin. Real parsers, inboxes, ROBs and handler dispatch;
  both modes, overlap off/on, reorder off/on, split readers armed/unarmed. Includes
  the three-pipe permutation, a Long on another executor across parser passes,
  and the late read-local demotion window in both modes. No listener, ring setup,
  server worker loop or server boot is involved.
- Deliberately broken throwaway units: removing shadow arming, completion clearing,
  or the fairness bound each exits 1 on its required assertion. None is a server
  binary or a committed source mutation.
- Strict no-op witness: **169/169 identical**, `build/r7shadow-off-witness/audit.json`.
- Generated-envelope check, `bash -n tests/gate.sh`, and `git diff --check`: PASS.
- Locked sizes read from the built executable without running it: Op 336,
  Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192,
  AtomicEntry 144, Config 624. All unchanged.

Final evidence: `build/r7shadow-final-build.log`, `build/r7shadow-unit-asan.log`,
`build/r7shadow-engagement.log`, `build/r7shadow-engagement-pad.log`,
`build/r7shadow-mutants.log`, `build/r7shadow-off-witness/audit.json`,
`build/r7shadow-layouts.log`, `build/tomokv-pad.json`, and
`build/r7shadow-engagement-pad.json`. The engagement PAD receipt binds the unit
binary separately from the server PAD receipt.

Reproduction commands (all are builds, serverless units or offline checks):

```sh
taskset -c 112-127 make -j8 all build/tomokv-pad build/r7shadow-unit-asan build/reorder-engagement-unit unit
taskset -c 112-127 ./build/r7shadow-unit-asan
taskset -c 112-127 ./build/reorder-engagement-unit on shadow
taskset -c 112-127 python3 tests/r7shadow_pad.py build/reorder-engagement-unit \
  build/r7shadow-engagement-pad --receipt build/r7shadow-engagement-pad.json
taskset -c 112-127 ./build/r7shadow-engagement-pad on r7
taskset -c 112-127 python3 tests/r7shadow_mutants.py
taskset -c 112-127 python3 tests/r7shadow_noop.py \
  build/r7shadow-pre/build/tomokv build/tomokv build/r7shadow-off-witness
taskset -c 112-127 python3 tests/r7shadow_sync.py
taskset -c 112-127 bash -n tests/gate.sh
taskset -c 112-127 sha256sum build/tomokv build/tomokv-pad
git diff --check
```

The PRE was built by archiving `f139a1a34` into `build/r7shadow-pre` and running
`taskset -c 112-127 make -C build/r7shadow-pre -j8`. The lane also ran GDB only on
a serverless unit during fixture setup, and used GDB `sizeof` on executable
files without run/start/attach for the layout witness.

The original byte normalizer is unchanged. Comparing against R7 itself exposes
173 broadly selected PRE bodies: the original 169 disabled-path bodies, two R7
ThreadCtx callback specializations, and two local parser clones in reorder.cc.
`tests/r7shadow_noop.py` excludes explicit R7 specializations and proves the two
local clones' armed provenance from ELF STB_LOCAL/STT_FILE information plus all
incoming code references. It fails if an excluded local clone is reachable from
a non-R7 external entry. It then requires all **169** disabled-path bodies to
match with the original strict instruction/encoding/literal checks. No register,
field offset, immediate, internal branch, instruction width, or layout operand
was normalized away. An initial genuine split read-local loop difference was
fixed by moving its cold selector out of the baseline translation unit; it was
not added to an exception list.

`tests/r7shadow_sync.py` replaces the old generator for this lane, checking the
armed parser's complete IO caller chain, including both modes, split read-local,
pipeline reparsing, TLS and epoll. It preserves the source envelopes except for
renamed armed calls, the parse-pass shadow tracker and the ordinary dispatch stamp.

Gate ledger: **zero rows added or retired**. `tests/gate.sh` is unchanged.
`EXPECT_QUICK=419` (line 254) and `EXPECT_FULL=435` (line 255) remain unchanged;
the quick-tier exit is at line 2764. The new unit is in the existing Makefile
`unit` target, not a new `gate.sh` row. flipctl.cc/.h are unchanged.

## Mainline measurement request — do not run in this lane

Use `/home/user/Projects/calib/tailgen-run.sh` and its current standing population
and geometry: server CPUs 0-31, 256 shards, 2M 64-byte short keys, 65,536 256-KiB
BITCOUNT blocker keys, tailgen CPUs 84-111, 16 generator threads × 32 connections,
Poisson arrivals, max outstanding 64, read-local=0, overlap=1, atomic/key/client
balancing armed. Keep placement and all other settings identical between arms.
These are maintainer-scheduled measurements, not the unit-test affinity.

Every cell has three required arms: POST `--reorder 1`, POST `--reorder 0`, and
PAD A `--reorder 1`. Run at least three paired rounds with matched traffic seeds
and balanced arm order. Include a PRE R7 `--reorder 1` comparison when attributing
a signal: PRE-versus-PAD exposes placement cost, and POST-versus-PAD tests the
shadow policy at identical ELF layout.

| Mode | Short:Long mix | Offered ops/s | PRE R7 | POST 0 | POST 1 | PAD A 1 |
| --- | --- | ---: | --- | --- | --- | --- |
| 2s | 8:2 | 880000 | pending | pending | pending | pending |
| 2s | 8:2 | 985000 | pending | pending | pending | pending |
| 2s | 8:2 | 1030000 | pending | pending | pending | pending |
| 2s | 98:2 | 880000 | pending | pending | pending | pending |
| 2s | 98:2 | 985000 | pending | pending | pending | pending |
| 2s | 98:2 | 1030000 | pending | pending | pending | pending |
| 1s | 8:2 | 880000 | pending | pending | pending | pending |
| 1s | 8:2 | 985000 | pending | pending | pending | pending |
| 1s | 8:2 | 1030000 | pending | pending | pending | pending |
| 1s | 98:2 | 880000 | pending | pending | pending | pending |
| 1s | 98:2 | 985000 | pending | pending | pending | pending |
| 1s | 98:2 | 1030000 | pending | pending | pending | pending |

One-cell command shapes (maintainer only; change mode, mix, rate and labels for
the other rows; interleave arms using the mainline runner):

```sh
TG_MODE=2s TG_MIX=GET:98,BITCOUNT:2 TG_INFO=SERVER \
  /home/user/Projects/calib/tailgen-run.sh r7shadow-on-2s-98-985 \
  /home/user/Projects/cx-r7shadow/build/tomokv 1 3 985000
TG_MODE=2s TG_MIX=GET:98,BITCOUNT:2 TG_INFO=SERVER \
  /home/user/Projects/calib/tailgen-run.sh r7shadow-off-2s-98-985 \
  /home/user/Projects/cx-r7shadow/build/tomokv 0 3 985000
TG_MODE=2s TG_MIX=GET:98,BITCOUNT:2 TG_INFO=SERVER \
  /home/user/Projects/calib/tailgen-run.sh r7shadow-pad-2s-98-985 \
  /home/user/Projects/cx-r7shadow/build/tomokv-pad 1 3 985000
```

The deciding metric is paired **short.p999_ms**, with short.p99_ms and both long
class quantiles reported alongside it. The driver prints class-split short/long
p99 and p999; retain its full per-rate JSON. Also retain achieved rates, class
counts, mean/p50, outstanding maximum, over-limit fraction, pacing lag, omitted
arrivals and drain time. Lower achieved load, omitted responses or long-class
starvation cannot count as a win. Compare the spread/standing null at each rate,
especially the 985K/1030K knee, before attributing a difference.

Mainline must also run GET/SET/MGET/MSET p1/p32 regression controls in both modes,
armed read-local/atomic/LB correctness coverage, and `tests/gate.sh iteration`
before deciding whether to merge. The lane has not boot-verified either mode.
