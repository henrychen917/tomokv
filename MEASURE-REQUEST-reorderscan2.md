# reorderscan2: iopass merge and frozen replacement arms

Merged source: `447003122` (parent merge `94d4303b7`). New base/PRE2:
`b38916d8884e3d620a9cda85e0a2fec4363173bf`. This supersedes the artifact
and identity section of `MEASURE-REQUEST-reorderscan.md`; it makes no new
performance claim. The previous lane approval remains mainline's measurement
verdict. All work here is serverless on CPUs 112–127. No push was performed.

## Conflict resolution and generation

`git fetch origin cpp && git merge origin/cpp` found exactly one textual
conflict: `src/core/reorder.cc`, at the atomic-scatter publication arm. IO7
replaced the inline atomic bundle with `dispatch_atomic_scatter`; RO2 had
inserted a Long-index update before the former inline publication.
`src/core/io_loop.h`, `src/net/conn.h` and `Makefile` did not conflict. The
final ordinary `io_loop.h` is identical to the new base; Client's two
uninitialized words remain at offsets 80 and 88 in existing padding, with
Client 1984 bytes and ROB 192 bytes. The existing four test-only legacy batch
aliases and both reorderscan unit recipes remain in the Makefile.

The authoritative generator is `tests/r7shadow_sync.py`; its extraction,
renaming and marked-envelope replacement helpers live in
`tools/reorder_sync.py`. IO3 arrives through the merged `io_loop.h`, including
`flip_pass_begin()` in the generated `r7_run_loop`. RO1's demotion-prefix index
and RO2's lazy dispatcher/publication instrumentation remain generator edits.
The generator now recognizes the helper's noinline signature and inventories
**eleven inline publications plus one delegated atomic publication**. Before
the helper call it records the current Long; on refusal it removes that entry
while `dispatch_id` is unchanged. The index is IO-private; the helper's
capacity checks, publication, owner bundles and scratch cleanup remain intact.

The merge commit `94d4303b7` resolves the generated file to the untouched
upstream version and integrates the generator inputs. The separate commit
`447003122` runs `python3 tests/r7shadow_sync.py --write` and changes only the
regenerated `src/core/reorder.cc`. No generated C++ body was hand-merged.
Review the two commits together: the second restores generated-source parity.
Both `python3 tests/r7shadow_sync.py` and
`python3 tests/r7shadow_sync_test.py` pass, including stale-copy rejection.

## IO3 and RO2 interaction

IO3 samples FLIP stage once before an IO pass's parsing/cron work. All
per-frame map, demotion and publication gates use that decision. An Idle
snapshot defers a newly opened drain ACK until the next pass; armed control
reacquires the live stage before ACK work, and the coordinator keeps its
immediate live fence. These functions are unchanged from PRE2.

RO2 captures the connection's ROB boundary at parser entry, then constructs
`ShadowDispatch` only at an admitted ordinary task with a pending older Long.
Its delayed reads are atomic predecessor completion states, not FLIP stage.
Neither the lazy holder nor the Long index acknowledges a drain, changes the
snapshot, or bypasses a dispatch gate. A Long that completes before the first
consumer needs no shadow hint. IO3's admission decision and RO2's hint sampling
therefore remain independent; the combined witnesses below exercise them in
the actual generated parser.

## Serverless checks

| Check | Result |
|---|---|
| `build/reorderscan-unit` | PASS: linear RO1 visits, 1000 mixed commits, RO2 lazy/Done/refusal/scatter/recycling cases |
| `build/reorderscan-unit-asan` | PASS with ASan/UBSan, leak detection and UB halt enabled |
| `build/reorder-unit`, `build/r7shadow-unit` | PASS with the inherited test-only batch alias |
| Generator check and stale-copy negative control | PASS |
| `reorder_engagement` row body, both database runtimes | PASS: production shadow, FIFO twin, disabled-capability rejection |
| `reorder_identity` row body | PASS: 396/396 FIFO-twin bodies; missing-policy, missing-parser and changed-opcode controls rejected |
| `r7shadow_noop.py PRE2 POST2 --inventory splitlocal` | PASS: 396/396 off-path bodies |
| `reorder_noop.py PRE2 PAD-A2 --literal-pools --expected-functions 424` | PASS: 424/424 bodies, including armed bodies and literal operands |
| `tests/iopass_checks.inc` | PASS: IO2 election; IO3 ACK/epoch/coordinator/database fences; IO4 writer binding/cancellation; IO6 slot bounds; IO7 refusal/retry/scratch in both modes and 256-shard split geometry |
| Generated-parser IO3/IO7 witnesses | PASS: existing fence assertions through R7; fused atomic refusal/retry at 16 and 256 shards |
| Delegated atomic Long-index witness | PASS: actual capacity refusal leaves no ghost Long; successful MSET/DEL publication indexes the Long; retired entries disappear |
| Missing delegated-index rollback control | Rejected by the ghost-Long assertion on actual refusal |
| RO1 old per-read scan control | Rejected by the linear-work assertion |
| PRE2 instrumented production parser | Eight no-Long constructions; rejected by POST's zero-construction assertion |
| POST2 instrumented production parser | Eight no-Long passes: zero constructions; Long control: one construction/two probes; demotion fixture: two visits |
| Default operation-path witness | Zero R7 envelope/helper entries and zero R7 allocations across both modes, overlap/read-local variants and database dispatch; armed positive and deliberate-entry negative controls fire |

The three gate row bodies were invoked directly; `tests/gate.sh` was not run.
The iopass tool emits the existing core fixture and includes the unchanged
`tests/iopass_checks.inc`. Additional disposable wrappers reuse its fence and
atomic assertions with the generated fused parser. The Long-index witness
uses the real read-local command classification (MSET/DEL become Long), and
checks both refusal and success. Its negative control removes only the new
rollback in a disposable copy, never the production file.

**Cold-entry qualification:** `--reorder 0` does not enter the R7 operation
path in these witnesses. An absolute claim that it never enters any code in
that TU is false for both PRE2 and POST2: inherited `src/main.cc:197` and
`src/core/server.h:279` call the cold `reorder_available()` capability predicate
defined in `reorder.cc`. This unchanged boot probe is outside the operation
path counters; no zero-entry claim is made for the entire process lifecycle.

## Identity and frozen artifacts

PRE2 was compiled from an untouched `git archive b38916d88` extracted inside
this worktree at `build/reorderscan-pre2-source`, with output in
`build/reorderscan-pre2`. PRE2 and POST2 each rebuilt all 86 production objects
with the ordinary Makefile flags and identical compiler. The comparison omits
only the two database variants of `src/core/reorder.o`.

* **84/84 non-R7 translation units:** all **7580 executable sections**,
  **10,765,734 bytes**, raw byte-identical. This compares executable sections,
  not entire `.o` files containing differing source/debug metadata.
* **1221/1221 hot bodies:** raw bytes and resolved relocation targets identical
  using the unchanged `tools/lbstall_artifacts.py compare`.
* Linked-binary normalization preserves opcodes, operand widths, layout
  operands, literal values and resolved targets. Whole ELF/address identity
  is not claimed; the new mainline null is still required.

| Arm | Frozen path | `.text` bytes | SHA-256 |
|---|---|---:|---|
| PRE2 | `build/reorderscan-pre2/tomokv` | 7781132 | `7cc26e0e6d85f897604a7b30c65c26d9ea086c723ec584438c3783ff16cb899d` |
| POST2 | `build/tomokv` | 7783004 | `62796fe469e5fe822fd5181f666aa084f81a63db6db8bfe0906bddff9b004277` |
| PAD-A2 | `build/reorderscan-padA2/tomokv` | 7783004 | `1817ea2d5f6c1aba63a60023218a922555d04f229bb23e4ca2f8b9f71b6b6cdd` |

**PAD kind A: PRE2 behavior with POST2 aggregate `.text` size.**
`tools/reorderscan_pad.py` relinked the frozen PRE2 objects in their original
order and added 1872 NOP bytes. This controls aggregate text size; it does not
match internal R7 addresses. The full 424-body audit verifies retained PRE2
instructions and literal operands. The FIFO diagnostic twin is a separate
artifact and is not this measurement arm.

Compact logs, SHA manifest, receipts and reproduction drivers are in
`docs/reorderscan2/`. Full compile logs, object comparisons, disassembly audits,
witnesses and throwaway controls are in `build/reorderscan2-evidence/`.

Reproduction, without running a server:

```sh
taskset -c 112-127 make -j8 all build/reorderscan-unit build/reorderscan-unit-asan \
  build/reorder-unit build/r7shadow-unit build/reorder-engagement-unit build/reorder-engagement-unit-db0
taskset -c 112-127 python3 tests/r7shadow_sync.py
taskset -c 112-127 python3 tests/r7shadow_sync_test.py
taskset -c 112-127 python3 docs/reorderscan2/object_identity.py
taskset -c 112-127 python3 docs/reorderscan2/reproduce_witnesses.py
taskset -c 112-127 python3 docs/reorderscan2/pre_witness.py
```

The drivers require the frozen PRE2 build/source and the merged POST2 objects
at the paths above. They build/run only serverless units and disposable
controls. Release and sanitizer unit logs and all three row-body commands
are recorded in the receipt.

## Mainline requeue

First run the shipped-default **14-cell null**, `--reorder 0`, from
`docs/lbplanner/generic-cells.txt`, comparing frozen merged POST2 against the
mainline headline at `b38916d88`. Record the headline digest; PRE2 is the
in-tree rebuild of that source, not a claim of whole-ELF identity with the
headline. Preserve the gate's instrument, matched offered load, paired seeds
and balanced arm order. Add the labelled PAD-A2 size control where useful.
Every cell must stay inside its matched same-binary band. Record achieved
rate, cycles/op, instructions/op and IPC together. A failed merged null
requires investigation before requeueing landing; these serverless counts
are not a performance verdict.

The earlier engaged-cell nulls/approval are in the prior lane record; this
merge does not relabel them as new POST2 measurements. After the null,
mainline owns its landing gate and both live mode boots. Reproduce correctness
with 16 shards, the gate ratio (6 IO + 2 EX) and eight cores, such as 112–119.
Do not substitute a default server geometry. No measurements or live boots
were run by this lane.

**Zero gate rows added or retired.** `tests/gate.sh` and all inherited fixture
files are unchanged. `EXPECT_QUICK=496`, `EXPECT_FULL=513` remain unchanged;
the three collection lines 3110–3112 are above the quick exit at line 3250.
No EXPECT or fixture edits, and no push.
