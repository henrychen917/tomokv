#!/usr/bin/env python3
"""Render the wave7b addendum from completed correctness receipts."""
import json
from pathlib import Path
import statistics
ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/wave7b'
e=json.loads((DOC/'evidence.json').read_text())
f=json.loads((DOC/'final-checks/receipt.json').read_text())
assert e['abba_statistics']['passed']==10 and e['epoll_statistics']['passed']==10
assert f['standalone']['exit']==f['perfio_owner']['exit']==0
assert all(r['exit']==0 for r in f['freshness'])
a=e['abba_statistics']; b=e['epoll_statistics']
records=[r for r in e['records'] if r['name']=='abba-smoke' or r['name'].startswith('repeat-abba-')]
def span(values): return f"{min(values):.3f}–{max(values):.3f}"
def suite(name): return span([r['suite_seconds'][name] for r in records])
def fixture(options):
    return span([row['seconds'] for r in records for row in r['fixtures'] if row['fixture']==options])
standalone=next(s for s in f['standalone_summary'] if s.startswith('Ran 72 '))
post=f['binary_sha256_after']
instrument=json.loads((DOC/'instrument.json').read_text())['sha256']
report=f"""## wave7b

Completed from `f974e5c50` on branch `cx-wave7`. Both maintainer commits (`b7d6b42da`, `f974e5c50`) remain ancestors. **DQ/DF = 0/0**; `tests/gate.sh` is byte-identical to the supplied HEAD, including **EXPECT 798/815** and the **1620-second ABBA row budget**. No push. All execution uses CPUs **64–95**; correctness listeners use **26800–26899**.

### ABBA diagnosis and fix

The unchanged row reproduced the landing failure through the job interface: **1246.230 s, FAIL**, with the same inner `timeout` return **124**. Its `gates_test.py` ran 72 tests in **517.796 s**, with five failing assertions. The ABBA control process consumed **567.308 s**, including **261.194 s** in the real null-collection/comparison/subset control. The receipt self-test process took **131.704 s**. [Baseline receipt](docs/wave7/correctness/wave7b-before/receipt.json), [per-test timings](docs/wave7b/before-timings), and the [complete archived job](docs/wave7b/archives/wave7b-before.tar.gz) retain the evidence.

Two separate costs explain the approximately 1250-second row:

1. `harness_fingerprint` hashed **82,379** repository paths, then discarded everything except **588** harness entries. The new implementation applies the **same path predicate before reading bytes**. On the same tree under contention, the old and new algorithms returned the identical 588-entry digest in **8.538 s versus 0.467 s**. Full-source release receipts still hash all source bytes. The new internal control checks byte changes with preserved size/mtime, executable modes, symlink targets, untracked inputs, tracked ignored inputs, deletions, and the unchanged full-source scope. [Fingerprint comparison](docs/wave7b/fingerprint-comparison.json).
2. SchedulerWiring launched roughly 220 real shell workers on the gate job's **two client CPUs**. Their all-started polling and later dependency polling contended with serialized row-start Python processes, so the fixture ran out of its own 45 seconds. It now uses only the job's explicit, otherwise idle server allocation plus its client CPUs, divides that allocation into four-CPU fixture groups, and bounds each fixture's workers by its CPUs. Ordered fixtures register the actual inventory in the requested order, wait only for the first worker wave, and start each real row watchdog before waiting for its FIFO completion turn. Every original job and helper still executes; missing registrations, forward/reverse canonical-ledger equality, empty/red fragments, nonzero returns, crashes, dependency/atomic-publication mutants, one-slot behavior, and cleanup checks remain. The inner **45-second timeout**, outer **50-second guard**, and all real row watchdogs are unchanged. Per-row `gate_history.py` CLI commands also avoid importing unittest; imported discovery and the self-test CLI retain real TestCase classes and all 55 history controls.

The one-slot change from wave 7 was helpful: it stopped pinning the coordinator onto its single worker CPU. It did not address the gate's inherited two-CPU client mask or the other fixtures' worker explosion. Commit `6496c622c` changes only `docs/wave7/prebuilt_validation.py` and `docs/wave7/watch_validation.py`; neither is on these rows' execution path.

The fixed job ran **10/10 PASS** while other whole correctness jobs ran. Three active slots used server CPUs **64–71 / 72–79 / 80–87** and client CPUs **88–89 / 90–91 / 92–93**. Each slot received **eight server CPUs and two client CPUs**, with the split-server defaults **6:2 and 16 shards**. Independent invocations each selected 16 physical CPUs to satisfy the planner minimum; surplus selected CPUs were unused by that invocation's worker slot, and prerequisite builds were already fresh. The third slot ran ten complete `flip` jobs, then complete `feature-split-0` and `feature-armed-0` jobs throughout the remaining ABBA work. No full iteration ran.

| Timed scope | PRE under contention | POST under contention, 10 whole rows |
|---|---:|---:|
| ABBA scored row | 1246.230 s, FAIL | {a['minimum']:.3f}–{a['maximum']:.3f} s; median {a['median']:.3f} s, all PASS |
| `abbagate.py --self-test` process | 567.308 s | {suite('abbagate')} s |
| `gates_test.py` process | 517.796 s, five failures | {suite('gates_test')} s, 72/72 each |
| `gate_receipt.py --self-test` process | 131.704 s | {suite('gate_receipt')} s |
| Forward completion fixture | timeout 124 at 46.073 s | {fixture({})} s |
| Reverse completion fixture | timeout 124 at 45.408 s | {fixture(dict(reverse=True))} s |
| Empty fragment fixture | timeout 124 at 45.407 s | {fixture(dict(failure='flipctl',behavior='empty'))} s |
| Explicit red fragment fixture | timeout 124 at 45.248 s | {fixture(dict(failure='flipctl',behavior='red'))} s |
| Nonzero-return fixture | timeout 124 at 45.498 s | {fixture(dict(failure='flipctl',behavior='return'))} s |
| Crash-before-done fixture | timeout 124 at 45.469 s | {fixture(dict(failure='globcase',behavior='crash'))} s |
| One-slot fixture | maintainer's idle suite passed; no individual PRE timer | {fixture(dict(slots=1))} s |

PRE's suite-level observer could not serialize a Path in the SchedulerWiring options; the raw 517.796-second unittest log is retained. The six individual PRE fixture timings above come from a supplemental execution of the **frozen f974e5c50 fixture source** on the same two client CPUs under owned contention. They include process startup/cleanup around the unchanged 45-second inner timeout. [Frozen fixture timings](docs/wave7b/scheduler-before-timed.json). POST has both per-test and per-fixture timings for every whole-row repetition in [the evidence index](docs/wave7b/evidence.json). The maintainer re-derives the row budget from the next landing; this lane changes no budget.

### epoll-lb diagnosis and deterministic witness

This is **(a), timing-dependent test arming**, for the reproduced failure. The old natural-skew test was alternated against frozen headline `05a5e01a9` and the supplied wave-7 binary at identical 8-thread / 6:2 / 16-shard geometry. Two campaigns ran 3 + 5 repetitions per arm. Wave 7 failed one move witness at **35.210 s**; headline also failed one at **35.333 s**. In the stronger campaign, one owned SHA-256 CPU worker occupied each CPU **64–87**, both servers used **64–71**, and both test clients used **94–95**. [First campaign](docs/wave7b/lb-before/summary.json), [stronger contention campaign](docs/wave7b/lb-contended/summary.json).

The already-read INFO counters show ordinary executor, protocol and destination readiness refusals, with zero committed moves. A sampled load plan is allowed to refuse; hot traffic cannot promise an idle selected client or a destination ACK within three source passes. `lbplanner.cc`, `lbstall.cc` and `weighted_lb.h` are byte-identical between headline and f974e5c50 ([source digests](docs/wave7b/lb-source-comparison.json)). ctlfix's completion-qualified admission governs automatic FLIP, while this test boots with `--flip-auto 0`. No wave-7 lane's ordinary LB behavior was changed to make this row pass.

There was no existing directed client-LB trigger. The new cold **`DEBUG CLIENT-LB <client-id>`** runs on the requesting destination's IO, prepares destination capacity there, publishes the epoch/stage-tagged ACK, and admits the existing source-side ClientDrain. It keeps the topology mutex, cancelled-reader record-reuse fence, source executor/readiness checks, single-owner transfer, ordinary deadline and normal refusal policy. It adds no layout fields or per-operation work; disabled client-LB still allocates no state. The directed unit holds an actual old reader through cancellation and rejects record reuse, rejects missing/same-owner observations, verifies destination preparation, and proves an unfinished executor still refuses even after a reply has retired. The existing no-publish mutation anchor was narrowed to the real monitor publication so the new debug publication cannot make it ambiguous.

The test chooses a source socket, a separate source waker, and a different destination owner by their real epoll registrations. It requests the move from the destination, leaves the selected socket idle, and requires **exactly one committed move within the original 35 seconds**. Subsequent replies prove destination installation. It then requires the selected inode to belong to the chosen destination, exactly **97** total registrations, no stale/duplicate registrations, and exactly one epoll event per command.

All **10 complete `flip` jobs passed under contention**; the epoll-LB row took **{b['minimum']:.3f}–{b['maximum']:.3f} s**, median **{b['median']:.3f} s**. A throwaway port-scoped preload that reports success without deleting the old epoll registration fails **after the move counter advances**: stale=1, duplicate inode=1, registrations=99 instead of 97. It exits 1 at `lb-moved`, proving that the new trigger does not make the stale-registration check vacuous. [Fault source](docs/wave7b/stale_epoll.c), [negative-control log](docs/wave7b/diagnostics/perfio-stale-negative.log).

### Validation and final artifacts

- Ten complete `abba_selftest` jobs: **10 PASS**. Ten complete `flip` jobs: **10 PASS**. Receipts retain prerequisites, full ledgers, commands, allocated CPUs/ports and unchanged executable hashes. Per-file source hashes were added after the initial `abba-smoke` run; that first run retains its commit/gate/binary binding and complete timing/log evidence.
- Final standalone `taskset -c 64-79 python3 tests/gates_test.py`: **{standalone}; OK**. `perfio_stream` used disjoint CPUs 80–95 after the background contention jobs finished. [Standalone receipt](docs/wave7b/final-checks/receipt.json).
- Complete owning jobs `lbplanner_units`, `flip_unit`, `debug-0`, `debug-1`, `perfio_stream`, and `reorder_identity`: **PASS**, as did every background `feature-split-0` / `feature-armed-0` job. The feature/stream owners exercise both thread modes. [All finished jobs and archives](docs/wave7b/evidence.json).
- `make all`, every literal `job_production_units` target, `mdbqsbr-live-arms`, and the custom blockfix-cost makefile targets: **PASS**. All **46 make -q freshness checks pass**, including concrete outputs of both MDBQSBR live arms. Freshness was checked again after the correctness campaign. [Build commands and results](docs/wave7b/build-proof/receipt.json), [final freshness](docs/wave7b/final-checks/receipt.json).
- R7's full off-path identity and every negative control pass. The strict linked comparison against the supplied wave-7 executable has **85 changed groups**, including the two new debug methods. Every selected GET/SET/MGET/MSET group is unchanged. Of **247 command-counted groups**, 245 are strict-identical; the other two differ only in switch-table offsets, with every instruction encoding and bounded case destination verified equal, including changed-branch/destination negative controls. The raw differences remain visible. [Linked inventory](docs/wave7b/identity.json), [exact two-body diffs](docs/wave7b/counted-body-diffs.txt), [switch proof](docs/wave7b/switch-provenance.json).

**`build/tomokv` changed** because of the DEBUG-only trigger: before `02e1a1a2cd0925d6dfa8deb3510febd0df745badbb03c95d2d8e41683f51c753`, after `{post}`. It stayed unchanged throughout the final validation campaign. The `.text` section grew **1,056 bytes**, with the layout locks unchanged. No runtime performance improvement is claimed.

| Arm | Path | SHA-256 |
|---|---|---|
| PRE | `/home/user/Projects/bench-bins/tomokv-headline-05a5e01a9` | `ff538ad1bebb30a7272e5396ef7daca90df14f2a84db3dd6f3cfc2acc8c1acd8` |
| POST | `build/tomokv` | `{post}` |
| PAD-A | `build/tomokv-wave7b-PAD-A` | `98780c486c3578810a498e836888075ce3e944e85801393b952c1af0f2e5ff4a` |

PAD is **kind A, behaviour twin**: unmodified headline behavior with final POST's `.text` origin **0x1f8b0** and total size **8,279,287 bytes**, using **61,376 trailing unreachable bytes**. It controls section origin/size; individual function offsets and data sections retain PRE layout, so it is **not an exact per-symbol/data-layout twin**. [Construction and input digests](docs/wave7b/pad-a.json). The rebuilt PAD retains all **785** audited headline hot groups and all **12** main-command groups exactly; four cold local-closure reference differences and the new unreachable padding body remain in the [PAD audit](docs/wave7b/pad-identity/summary.json). The local PRE linked to construct PAD has SHA `d57665a5879a415b049e5faacbc643432ab18223a16ce0cf5966e858f17da065`; the measurement PRE remains the frozen headline executable listed above.

### Maintainer measurement request

The instrument closure includes `gate_history.py` and `gate_receipt.py`; their changed bytes require fresh instrument/null provenance even though fingerprint scope and verdict rules are preserved. The final [instrument manifest](docs/wave7b/instrument.json) has SHA-256 `{instrument}`. Using the gate's own instrument, rerun the affected **PRE/PRE null**, then **PRE/POST landing** and **PRE/PAD-A** section-origin/size control. Retain every existing [headline cell](tests/headline_cells.txt), [multi-key cell](tests/mkprobe_cells.txt), and [multi-DB cell](docs/lbplanner/multidb-cells.txt), including separate **2s SET depth 1** and **eight-key MSET depth 1/8** decisions. Record rate at matched offered load, declared depth-1 latency, cycles/op, IPC and instructions/op for every cell. Rate/latency decide; do not average away a regressed SET/MSET cell. The ordinary server path must stay within the established null floor.

[Final cleanup audit](docs/wave7b/final-audit.json): no remaining owned correctness servers, CPU contenders, or listeners on ports 26800–26899.

**NOT RUN:** the 112-physical-core, 10-slot full `tests/gate.sh iteration`; all performance benchmarks, ABBA/NIC measurements, null campaigns and performance-only jobs. These remain with the maintainer under this lane's runtime authorization. The correctness reproduction uses the authorized 32 CPUs with matching per-slot geometry, not the full landing allocation. The next landing supplies the new whole-row budget.
"""
path=ROOT/'MEASURE-REQUEST-wave7.md'
old=path.read_text(); prefix,marker,_=old.partition('## wave7b\n'); assert marker
path.write_text(prefix+report)
