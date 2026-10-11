## rlfix

Both fixes and four discriminating gate rows are committed on `cx-rlfix`, based
on `991d48f651d3c6e1324c061bd9ea801ac085afe8`. **Not merge-ready: the strict
GET-hit byte-identity law is not satisfied inside `prepare_local_read`.** The
standard hot selectors pass, but omit that resolver. No throughput claim is
made; merit remains for the maintainer on the quiet box. No push, benchmark,
or full gate was run.

Feature commits: `3676d3cae` (RL4.3), `8015c1b53` (RL4.4). PRE reproduction:
`b2f323f3b`. Compiler-budget preservation and bounded fresh RYOW witnesses:
`2062b382e`.

RL4.3 changes `ExLoopT<true>::prepare_local_read` in `src/core/ex_loop.h`:
a Missing capture is accepted after final topology validation, with nil,
zero keyspace hits and one keyspace miss. Existing chunk commit accounting
counts it once. Keymiss notifications use the same cached permission bit as
MGET; an armed bit demotes the GET miss through `ContextKeymissNotify`.
The check occurs on the already-taken miss edge. Typed and expired keys keep
their owner path, lazy deletion and notifications. A changed capture demotes
through the existing AtomicPending/SeqChurn decision, without retrying.
The parser and MGET implementation are unchanged.

RL4.4 changes `IoLoop::ReadLocalDemotionPlan::prepare` in `src/core/io_loop.h`.
On its existing broad InflightWrite edge, argc==2 DEL/UNLINK refines the staged
ROB generation to the exact hash and selects older pending reads by that hash.
Refinement happens before the no-pending-read early-out, so younger reads also
see it. The ordinary point-write precision permission, including its eviction
policy guard, remains in force. Marking the Op precise also retains the
executor's no-eviction guard if policy changes after parsing. Multi-key
deletion stays broad. The executor/scatter's
existing single-key lowering is unchanged. Neither fix adds an allocation,
runtime knob, retry, or layout field.

**Reproductions and new rows.** The round-4 originals were read-only;
[venues.py](docs/rlfix/venues.py) copies them into this worktree and adapts only
paths, affinity, ports and explicit gate geometry. Original hashes and exact
commands are in [PRE receipts](docs/rlfix/pre-venues/receipt.json).
T2 passed 44 reproduction checks, T4b 50, and T4c 12. Both modes reproduced
GET missing: one `fallback_missing`, zero lane completions; and
`GET z1; GET z2; GET z3; DEL a; GET z4`: all four GETs demoted, compared with
zero for SET a. UNLINK behaved like DEL.

| Observable, both modes | PRE | POST |
|---|---:|---:|
| Stable GET miss: `read_local_hits` | 0 | 1 |
| Stable GET miss: `read_local_keyspace_misses` | 0 | 1 |
| Stable GET miss: `read_local_fallback_missing` | 1 | 0 |
| Stable GET miss: global `keyspace_misses` | 1 | 1 |
| Four disjoint GETs around one-key DEL/UNLINK: local | 0 | 4 |
| Appended same-connection GET of deleted key | nil | nil |
| Appended same-key GET: InflightWrite fallback | 1 | 1 |
| Multi-key DEL/UNLINK control: four disjoint GETs local | 0 | 0 |

[tests/rlfix.py](tests/rlfix.py) checks exact replies and counters. The delete
witness chooses distinct actual shards, avoiding unrelated table churn. It
covers DEL/UNLINK and mixed case, older and younger reads of the deleted key,
and a multi-key broad control. A too-short write window is retried on fresh
connection/state, at most three times; no window is a failure. The final
same-connection GET must return nil even on an attempt that will be retried.

The latest test revision fails on PRE in **8/8** case/mode/atomic combinations
at the local-hit assertion, and passes on POST in **8/8**. Receipts:
[negative](docs/rlfix/pre-bounded-final/receipt.json),
[positive](docs/rlfix/post-bounded-final/receipt.json). Earlier receipts remain
as history, including the draft fixture's same-shard churn failure.

All four declarations precede the quick-tier exit at `tests/gate.sh:3722`:

| Row | Source line | DQ | DF |
|---|---:|---:|---:|
| GET miss, 1s | 2045 | +1 | +1 |
| One-key delete, 1s | 2051 | +1 | +1 |
| GET miss, 2s | 2064 | +1 | +1 |
| One-key delete, 2s | 2068 | +1 | +1 |

**DQ=+4, DF=+4.** Maintainer-owned EXPECT values should become **629 / 646**
from 625 / 642. Neither constant was edited. The label fixture has all 646
source rows, no missing/extra labels; validation fails solely on unchanged
`EXPECT_FULL=642` ([receipt](docs/rlfix/ledger.log)).

**Build and identity proof.** PRE and POST use normal GCC 13.3.0 production
flags and jemalloc. `make all` and all 30 top-level targets from
`job_production_units` built successfully, including `mdbqsbr-live-arms` and
its two binaries. All 30 pass `make -q` freshness. These are build checks, not
claims that every unit binary was executed. Exact command and targets:
[production-units.json](docs/rlfix/production-units.json); logs:
[all](docs/rlfix/release-build.log.gz),
[units](docs/rlfix/production-units.log.gz).

| Check | Result |
|---|---|
| Unmodified `lbstall_artifacts.py compare` | 1,204/1,204 opcode + resolved-relocation identity |
| Full audit hot selection, including executor run | 1,208/1,208 identical |
| Command handlers | 1,211/1,211 identical |
| Complete emitted-body inventory | 16,407 identical; 34 changed |
| Local GET resolver, omitted by the hot selectors | **Hit-path bytes differ** |
| `.text` bytes | 7,646,972 PRE; 7,649,404 POST (+2,432) |
| Locked layouts and named field offsets, both namespaces | Identical |

Locks: Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944,
Rob<64> 192, AtomicEntry 144, Config 624. Receipts:
[hot](docs/rlfix/hot.log), [full](docs/rlfix/full/summary.json),
[every changed function and size](docs/rlfix/changed-functions.md),
[complete inventory](docs/rlfix/full/bodies.json.gz),
[linked sections](docs/rlfix/linked.json), [layouts](docs/rlfix/layouts.json).
The 34-body list includes compiler-induced changes outside the two edited
source functions; none are suppressed or called identical. Four existing
Makefile inlining budgets, including the db0 reorder auto-inline cap, are
adjusted to preserve the selected hot bodies.

The unresolved evidence is explicit: in `src/core/genthread.o`, the common
return block of `prepare_local_read` loads its aggregate at `%rsp+0xb0/0xb8`
in PRE and `%rsp+0x90/0x98` in POST. Successful GET hits use this block too.
Internal branch displacements also differ. A noinline miss helper restored
those stack slots but introduced an extra integer-hit move. Cold,
output-reference, return-reason, register, return-barrier and noipa variants
also failed exact identity and were not adopted. The strict law remains a
blocker regardless of future rate results. Evidence:
[byte-check record](docs/rlfix/local-get-byte-check.json),
[PRE disassembly](docs/rlfix/local-get-pre.asm),
[POST disassembly](docs/rlfix/local-get-post.asm),
[unmasked diff](docs/rlfix/local-get.diff).

**Correctness proof.** Commands were confined to CPUs 48–63: targets 48–55,
oracle 56, clients 57–63; ports 25600–25699. Focused servers used 16 shards,
split ratio 6:2 or eight fused cores, and read-local 1. The oracle is the
unmodified Redis 7.4.10 build under `/home/user/Projects/redis74`.

- GET/MGET missing, wrong-type and expired cases pass against the oracle with
  active expiry disabled, RESP2/RESP3, and keymiss notifications off/on.
  Compared replies, keyspace hit/miss and expired counters, exact keymiss
  messages, and applicable TomoKV local/fallback counters. Duplicate MGET
  misses count per key. Wrong-type GET counts as a keyspace hit; MGET's
  wrong-type element is nil and still a hit.
- RYOW, atomic RYOW, lane admission and MGET fence passed in both modes.
  The combined runner's a0/a1 labels denote initial boot state;
  `atomic_ryow.py` enables atomic=1 before later B+ and lane batteries.
  [Combined results](docs/rlfix/final-correctness/receipt.json).
- One B+ run on a reused fused boot returned the new value instead of the
  expected pinned old value during a timed hold while compilation was active.
  This remains an assertion failure, not a proven deadline failure. Fresh
  PRE/POST runs at B+'s required atomic=1 geometry passed in both modes after
  compilation finished: [recheck](docs/rlfix/bplus-recheck/receipt.json).
  An extra atomic=0 recheck was inapplicable: both arms immediately reject
  that configuration (`B+ test needs CONFIG atomic=1`);
  [receipt](docs/rlfix/bplus-a0-recheck/receipt.json).
- `python3 tests/gates_test.py`: 66/66 passed, plus the nested 14/14 subset.
  No assertion changed. [Log](docs/rlfix/gates-test.log).
  `bash -n tests/gate.sh` passed.
- Redis differential: **744/744 executed legs passed**, seeds 7/19/20/23,
  both modes, atomics 0/1. All 47 discovered suites were selected: split
  376/376; armed fused 368/368, with the script's eight sort legs skipped
  because that suite requires split 6:2. Both mandatory fused lane witnesses
  fired (1,257 peak hits each); fused reports 370 passes including them.
  The script calls explicit suite/seed selection focused proof; it omits its
  additional rotating seeds, repeated multi stress and mode-equivalence tier.
  It observed 232/245 registered commands, not complete command coverage.
  [Matrix receipt](docs/rlfix/differ.json),
  [split log](docs/rlfix/differ-split.log),
  [fused log](docs/rlfix/differ-armed-fused.log).

The focused runner once observed port 25610 briefly accepting after its owned
PRE process exited. It now requires closure within two seconds before reuse;
the completed negative rerun passed. Initial cleanup failure logs remain under
`docs/rlfix/pre-bounded-regressions/`.

**Arms and PAD semantics.** `build/rlfix/post/tomokv` is an exact copy of
`build/tomokv`. Hashes and oracle digest:
[binaries.json](docs/rlfix/binaries.json).

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/rlfix/pre/tomokv` | `7775c8c27ffaa18ccad76bfb425c7ad3c741a204888d903123c04d1199d77468` |
| POST | `build/rlfix/post/tomokv` | `d3880ba6d766c80b0b296c5eb99590d8c25b0f02a32aeefdf234ca55077a97a6` |
| PAD-A | `build/rlfix/pad-a/tomokv` | `63715fbe03430c2b86ab8abfa3caab062b8bf858c4bcdeb124c6913aaabf87be` |

PAD-A is **kind (A), behavior twin: PRE behavior with candidate text size and
layout**. The offline, SHA-bound [builder](docs/rlfix/pad_a.py) patches four
ranges in a POST copy: Missing returns the original fallback after clearing
the reply, and delete refinement is bypassed, in both namespaces. All section
and symbol addresses/sizes and non-text bytes remain identical to POST.
It preserves POST's local GET hit bytes, including the unresolved stack-slot
change. This is a layout control, not a fix for the byte-law violation.
[Patch receipt](docs/rlfix/pad-a.json). T2/T4b/T4c all pass their original
PRE-behavior assertions on PAD-A:
[venue receipts](docs/rlfix/pad-a-venues/receipt.json).

**Maintainer merit request, not executed here.** Resolve the byte-law blocker
before accepting this candidate. Use the gate's ABBA instrument, CPUs 48–63
only (server 48–55, load 57–63), 16 shards, eight server cores, split 6:2 where
applicable, ports 25600–25699. No oracle or compilation during merit. Keep all
non-varied settings identical to the instrument's hit-control cells and
record them with results.

| Cell | Modes / lane | Pipeline | Arms |
|---|---|---:|---|
| GET, exactly 50% stable absent keys | 1s, read-local 1 | 32 | PRE, POST, PAD-A |
| 9 GET : 1 single-key DEL, disjoint GET/delete key sets | 1s and 2s, read-local 1 | 8, 32 | PRE, POST, PAD-A |
| GET, 100% existing string hits | 1s and 2s, read-local 0 and 1 | 8, 32 | PRE, POST, PAD-A |
| SET, overwrite existing strings | 1s and 2s, read-local 0 and 1 | 8, 32 | PRE, POST, PAD-A |

Use identical seeded traces, connections, key/value sizes and offered load
across arms. Reset/reload the delete set before every arm and record successful
DEL fraction, preventing unequal depletion. GET keys in the mixed cell stay
present and disjoint from delete keys. Record lane hits/misses, fallback reasons
and keyspace deltas; a non-firing lane or incorrect mix invalidates a cell.

Run matched PRE/POST ABBA and PRE/PAD-A ABBA. The deciding number is
matched-load ops/s change: intended cells should improve beyond quiet-box
±0.15% repeatability, PAD-A should stay flat, and GET/SET hit controls must
show no regression. Report cycles/op, instructions/op and IPC together, plus
the instrument's latency columns. Identical-arm disagreement above 2%
invalidates the run; it is not noise. Rate results cannot waive the byte-law
failure. Append owner results as `MEASURE-RESULT`; this lane supplies none.

Reproduce byte audits offline:

```sh
taskset -c 48-63 python3 tools/lbstall_artifacts.py compare \
  build/rlfix/pre build build/rlfix/recheck-hot.json
taskset -c 48-63 python3 tools/ccfix_audit.py \
  build/rlfix/pre build build/rlfix/recheck-full
taskset -c 48-63 python3 docs/deadswitch/linked_bytes.py \
  build/rlfix/pre/tomokv build/tomokv build/rlfix/recheck-linked.json
```

Reproduce the differential matrix with fresh output directories:

```sh
for geometry in split armed-fused; do
  REDIS74_ROOT=/home/user/Projects/redis74 \
  GATE_LOAD_CORES=57-63 GATE_DIFFER_ORACLE_CORES=56 \
  GATE_DIFFER_GEOMETRY="$geometry" \
  GATE_DIFFER_PROOF_SUITES="$PWD/docs/rlfix/differ-suites.txt" \
  GATE_DIFFER_PROOF_SEEDS="$PWD/docs/rlfix/differ-seeds.txt" \
  GATE_DIFFER_OUT="$PWD/build/rlfix/recheck-$geometry" \
    taskset -c 48-63 tests/differ_gate.sh \
      "$PWD/build/rlfix/post/tomokv" 25620 25621 48-55 6:2
done
```
