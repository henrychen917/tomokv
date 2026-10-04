# MEASURE-REQUEST-gaterows3 — landing-failure repairs

Worktree/branch: `/home/user/Projects/cx-gaterows`, `cx-gaterows`.
Launch HEAD: `d011060b029f2592915348ed6866f27ccce7ce53`.
The first command was the required `git fetch origin cpp && git merge --no-edit origin/cpp`.
It merged `cd02ecbab1502775f1c170e806971d1f7bbc3ee9` in `37a53d3d7`.
Both merge conflicts were resolved with **current origin's exact EXPECT assignments
and exact label fixture**. Their bytes remain equal to current origin; no lane count
or fixture update is included. The pre-report fetch/merge was already up to date.

No server, live battery, benchmark, load generator, or gate was run. All builds
used `taskset -c 112-127 make -j16`; serverless checks used cores 112–127.
No agents were delegated and nothing was pushed. No lane changes touch `src/`;
the launch diff includes the required upstream rlfence merge, not lane production edits.

This addendum adds **zero further rows**. The branch still adds **eight** to current
origin: **473 → 481 quick**, **490 → 498 full**. Counts come from source declaration
extraction on each side of the quick-tier exit, not from the failed landing ledger.
The existing `MEASURE-REQUEST-gaterows.md` describes the original debt work; its old
467/484 landing totals are superseded by this report.

## A — unset partial flag broke receipt shell fragments

At launch, `tests/gate.sh:146,156,173` read `$GATE_PARTIAL` in blocks extracted and
executed under `set -u` by `tests/gate_receipt.py`. Those fragments intentionally do
not run the gate's top-level initialization. This reproduced the reported unbound
variable in both `test_actual_begin_reads_explicit_previous_ledger_before_rotation`
and `test_actual_shell_receipt_blocks_do_not_short_circuit_work_or_certify_iteration`.

Every read in `tests/gate.sh` and `tests/gate_subset.sh` now uses
`${GATE_PARTIAL:-0}`. Assignments and partial behavior remain the same. An added
subset control unsets the flag under nounset and requires the complete job list to
equal the explicitly disabled selector's list byte for byte.

Current mainline also added `production_units` to `debug-*` dependencies. The
subset fixture had assumed only `release`; it now obtains the prerequisite set
from the actual planner, requires the helper to complete, and still expects exactly
the release/debug-0/debug-1 scored ledger. `_gate_path`, `only_jobs`, the temporary
scheduler script, and the >128 KiB script control all remain in `tests/gates_test.py`.

Commits: `6a6077a6a` (nounset defaults), `4975a8f81` (fixture dependency correction
alongside the persistence controls).

## B — stationary LB could never identify a connection's IO owner

The launch `tests/lb_stationary.py:88–96` sent 64 `CLIENT ID` commands and required
a 64-op increase in `DEBUG LBSIGNALS`. The connection-local CLIENT path does not
charge `LoopSignals.ops`: see `src/core/io_loop.h`'s connection-local branch versus
the `sig.ops++` at ordinary dispatch. Both retained failed LB shutdown reports
show zero loop ops despite the CLIENT probes. This is the concrete reason arming
failed; replacing an assumed thread count alone would not repair it.

`client_threads()` now cross-checks the actual serving-thread set against
LBSIGNALS `client_threads`, its role rollup, and INFO's `lb_io_threads` or
`lb_fused_threads`. Thus the gate's split shape needs six IO connections and its
fused shape eight. No range of guessed thread IDs is used.

Arming now creates the sixteen shard keys first, then probes each connection with
64 ordinary GETs covering every shard equally. In fused mode the shard owners
execute their shares; only the connection's IO owner parses the entire batch.
Acknowledged replies and bounded counter publication polling identify that owner.
Missing coverage prints wanted/armed IDs. The original 12-second stabilization,
full 30-second hold, exact zero-move assertions, traffic conservation, and three
fresh-state attempts remain. Exhausting those attempts still raises
`stationary LB assertion window never opened after three fresh-state re-arms`.

Self-tests cover noncontiguous IDs in both real gate shapes, a bad INFO owner count,
delayed counter publication, zero-op probes, all three failed re-arms, inactive
threads/shards, zero ticks, and one bucket/client move. A throwaway removal of the
probe's `conn.raw(request)` fails exactly at
`ordinary GET probe failed to identify actual IO owner`; the fixture advances
counters only after that send. Evidence: `build/gaterows3-lb{,-negative}.log`.

Commits: `661977b4e`, with the send-dependent negative control in `4975a8f81`.

## C — port audit and persistence readiness

The proposed **netio/7902 slot collision is not supported by the retained run**.
The following evidence comes from `build/gate-run.0tHsvZ/plan.sh`, each job's
`family.tsv`, and every retained `gate-srv-*` / `server-*.log` listening announcement:

| Job | Slot | Observed listener port | Family interval, epoch seconds |
| --- | --- | --- | --- |
| `netio-1s` | 0 | 7899, both engines | 1791056528.834706770–1791056534.231946825 |
| `netio-2s` | 0 | 7899, both engines | 1791056534.243561577–1791056539.614423981 |
| `aof-uring` | 1 | 7902 | 1791056505.175492319–1791056564.728155074 |

All recorded job intervals within each slot are disjoint, and every inspected
listener belongs to its job's reserved three-port interval. Slot 1's prior job,
`feature-split-1`, ended at 1791056505.164718119; its next job, `dump_restore`, began
at 1791056564.744394230. Neither overlaps the failed recovery. The slot worker PID
2309201 in the row-watchdog filenames is **not evidence of the answering server PID**.

The selector PRE is `865477fb0^`; its POST is `865477fb0`. Verification found:

* `tests/gateplan.py` is byte-identical PRE versus current, SHA-256
  `a66c0e5fd0a791bbfc827f1cfbb6c7a26a55e741735aaa10fab28992b18e8ddc`.
* `set_slot`, `launch`, `stop`, `run_job`, and the queue/claim/reuse loop are
  byte-identical. The failed run's `SLOT_PORTS` is
  `7899 7902 7905 7908 7911 7914 7917 7920 7923 7926`; each slot still owns base+0/1/2.
* Remove only the eight added collector rows, their comment, and the PARTIAL-only
  early-return block: the original PRE/POST full collector text is byte-identical.
* Against current origin, remove exactly those eight labels: all **490** existing
  labels retain their order and multiplicity. The disabled-selector control also
  compares actual planned job output bytes. Normal ledger duration fields remain
  measured values; they cannot be identical across separate timed executions.

The executable audit is retained in `build/gaterows3-port-audit.py`, with its JSON
and log beside it. It asserts each equality and every observed slot interval/port.
The scheduler continues to assign ready jobs dynamically; equal port derivation
does not claim a job must happen to receive the same slot in two separate runs.

**Historical answering PID remains unproven.** The failed `server-2.log` is empty;
`persistfix.py` recorded neither its Popen PID nor a responding `INFO process_id`.
Its traceback records a TCP reset before a RESP reply. The retained logs identify
the AOF job and port but cannot recover the peer PID for that particular connection.
An old endpoint still completing teardown or an external listener cannot be proved
or excluded from those artifacts. This report does not invent a PID or present a
TCP handshake as an application response.

There is nevertheless a demonstrated harness defect: the launch
`tests/persistfix.py:115–123` accepted a TCP connect as readiness, then immediately
opened the recovery connection and issued GET. The revised harness waits for
`INFO Server` from **its own Popen PID**, and verifies that identity again on every
workload/recovery connection. A reset/EOF before any answer remains unready inside
the existing 30-second bound. A wrong or missing PID fails immediately at
`persistence peer PID mismatch`. Rejected connections are closed.

Each boot now writes `processes.jsonl` with timestamp, owned PID, port, argv/log,
responding PID, unanswered connection errors, and reap status. It changes no gate
slot, server port, scheduler, persistence hook, kill/term condition, or recovery
assertion. `tests/gates_test.py:1414` models the empty recovery log and a successful
connection followed by reset, then a correct response. Wrong/missing identities
are negative controls for both readiness and workload clients. Removing `identify`
in a throwaway makes `self.assertFalse(run.ready())` fail (`True is not false`).
Evidence: `build/gaterows3-persistfix{,-negative}.log`. Commit: `4975a8f81`.

## Serverless proofs and the deliberately unsynchronized fixture

The direct command `python3 tests/gate_receipt.py --self-test` currently refuses
before its controls: **EXPECT_FULL=490, fixture=490, source declarations=498**,
with exactly these eight missing labels and no extras. This is expected pending
the maintainer's landing sync; it was not bypassed in production or committed code.

To exercise the receipt chain now without editing either protected file,
`build/gaterows3-receipt-view.py` supplies an explicitly synthetic, in-memory
`Path.read_text` view of the source-declared 498 labels and the corresponding
full count. All validation and mechanism-removal controls still execute. This is
a **serverless test fixture, not a receipt or a full-gate pass**. Both PRE and POST
use that same view, isolating the nounset change. PRE reproduces the named failures;
POST passes 10 fixture controls, 18 receipt controls, 27 promotion controls,
10 holdout controls, and the refreeze control. Logs:
`build/gaterows3-receipt-{pre,negative,post}.log`.

| Proof | Result / failure control |
| --- | --- |
| Required release and both R7 engagement-unit builds | PASS; `build/gaterows3-build.log` |
| R7 generated envelope | Current; stale accounting twin fails, regeneration passes |
| Both R7 production engagement units | PASS; FIFO-disabled twin run as ON fails at `binary capability differs from expected arm` |
| R7 strict identity | **396/396**; missing policy symbol, missing split-local parser, and changed opcode rejected; `build/gaterows3-reorder.log` |
| Writeback fixtures | **352** = 22 states × 2 policies × 4 counts × 2 namespaces; policy-zero always-defer mutant fails `trace decision` in both namespaces; `build/gaterows3-wb-traces.log` |
| Writeback transcript / netio controls | Wrong, missing, reordered replies and substituted/absent/inactive engine evidence rejected |
| Stationary LB / persistence ownership | Positive fixtures plus the named throwaway failures above |
| Subset controls | **8 tests**, including unset flag, unknown/ineligible/helper-only jobs, failed finalizer, and PARTIAL receipt refusal |
| Complete gate harness | **63/63 PASS**, including partial finalizers, opposite-order ledger identity, port-slot reuse, and the >128 KiB script; `build/gaterows3-gates-test-clean.log` |
| Docs drift | **85 parser spellings**, all positive/negative controls pass; `build/gaterows3-docs-drift.log` |
| Source inventories | **473/490 → 481/498**, ordered projection identical; exactly +8/+8 |
| Syntax, Python compilation, whitespace | PASS |

Two earlier whole scheduler runs are retained in `build/gaterows3-gates-test.log`
and `build/gaterows3-gates-test-final.log`, with their `scheduler-failure-*`
directories. The first exposed the stale partial prerequisite expectation and one
Bash `*** longjmp causes uninitialized stack frame ***` abort. After that expectation
was repaired, another run reached the existing 45-second bound in the one-slot and
opposite-order fixtures while other lane self-tests were active. No timeout, inventory,
ledger assertion, or CPU-affinity assertion was relaxed. The complete suite subsequently passed **63/63 in 88.100 s**, with the same 45-second fixture deadlines, after the build finished (`build/gaterows3-gates-test-clean.log`).

Repeat the ordinary serverless proofs on the permitted lane cores:

```sh
taskset -c 112-127 make -j16 all build/reorder-engagement-unit build/reorder-engagement-unit-db0 build/wb-rule-completion-unit build/wb-rule-db0-completion-unit
taskset -c 112-127 make -j16 reorder-checks
taskset -c 112-127 python3 tests/wb_policy.py --traces
taskset -c 112-127 python3 tests/wb_policy.py --self-test
taskset -c 112-127 python3 tests/netio.py --self-test
taskset -c 112-127 python3 tests/lb_stationary.py --self-test
taskset -c 112-127 python3 tests/gate_subset_test.py
taskset -c 112-127 python3 tests/gates_test.py
taskset -c 112-127 python3 tests/docs_drift.py --self-test
taskset -c 112-127 bash -n tests/gate.sh tests/gate_subset.sh
```

For a reproducible **in-memory fixture simulation only**, before the maintainer
updates the protected files, run this from the worktree. It does not certify a gate
or write those files. Remove the override after the real count/fixture sync:

```sh
taskset -c 112-127 python3 - <<'PY'
import json, re, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, 'tests')
import gate_ledger_fixture as fixture
import gate_receipt as receipt
root = Path.cwd()
read_text = Path.read_text
source = read_text(root / 'tests/gate.sh')
labels = fixture.source_labels(source)
source = re.sub(r'^EXPECT_FULL=\d+', f'EXPECT_FULL={len(labels)}', source, flags=re.M)
def view(path, *args, **kwargs):
    if path == root / 'tests/gate.sh': return source
    if path == root / fixture.FIXTURE: return json.dumps({'labels': labels})
    return read_text(path, *args, **kwargs)
print('SYNTHETIC source-declared fixture; no protected files edited; NOT A RECEIPT')
with patch.object(Path, 'read_text', view):
    raise SystemExit(receipt.self_test())
PY
```

## Rows and mainline-only live checks

All eight collection sites are at `tests/gate.sh:3017–3022 (quick exit: line 3157)`, before the quick exit.
The ABBA self-test row gains controls, and the existing eight AOF kill/term rows
gain verified readiness; neither change adds a scored row. The 32-way feature
product stays unchanged.

| Job | Exact added label | Quick/full delta |
| --- | --- | --- |
| `reorder_sync` | `R7 generated envelope parity` | +1/+1 |
| `reorder_engagement` | `R7 production engagement (both database runtimes)` | +1/+1 |
| `reorder_identity` | `R7 FIFO twin off-path identity + negative controls` | +1/+1 |
| `wb_policy` | `writeback policies 0/1: 22 standard fixtures` | +1/+1 |
| `lb-stationary-1s` | `stationary balanced LB holds still (1s)` | +1/+1 |
| `lb-stationary-2s` | `stationary balanced LB holds still (2s)` | +1/+1 |
| `netio-1s` | `epoll directed correctness (1s)` | +1/+1 |
| `netio-2s` | `epoll directed correctness (2s)` | +1/+1 |

MAINLINE, on the scheduled quiet box, can first execute the added jobs and both
AOF families with ordinary gate boot/teardown and disjoint slot ports. This uses
four eight-server-core slots, sixteen shards per boot, and split ratio 6:2:

```sh
GATE_ONLY_JOBS='reorder_sync reorder_engagement reorder_identity wb_policy lb-stationary-1s lb-stationary-2s netio-1s netio-2s aof-uring aof-epoll' \
  tests/gate.sh iteration --server-cores 0-31 --load-cores 32-111 --ports 16379-16390
```

This remains a PARTIAL ledger, never an EXPECT tally or receipt. Inspect both LB
`hold.json` files for armed coverage and the full hold, and each persistfix
`processes.jsonl` for matching spawned/responding PIDs. The assertions themselves
already enforce coverage, no moves, identity, and recovery.

After the **maintainer** updates current origin's counts to **481/498** and runs
the ordinary source-based label fixture sync, run the unmodified receipt controls
and full landing gate:

```sh
taskset -c 112-127 python3 tests/gate_ledger_fixture.py
taskset -c 112-127 python3 tests/gate_receipt.py --self-test
tests/gate.sh iteration --server-cores 0-31 --load-cores 32-111 --ports 16379-16390
```

The full gate's real live results are still for MAINLINE. No performance merit or
successful live recovery is claimed from the synthetic/serverless checks here.

## Launch diff

`git diff d011060b029f2592915348ed6866f27ccce7ce53 --stat`, including this report.
Most entries below are the required upstream rlfence merge. In particular, the
production file and generated-fixture differences relative to launch come from
that merge; `git diff origin/cpp -- src tests/fixtures/nullrefresh-ledger-labels.json`
is empty, and both EXPECT assignments equal current origin.

```text
 MEASURE-REQUEST-gaterows3.md                       |  392 +++
 MEASURE-REQUEST-rlfence.md                         |  283 ++
 MEASURE-REQUEST-rlfence2.md                        |  315 ++
 MEASURE-REQUEST-rlfence3.md                        |  285 ++
 Makefile                                           |   10 +-
 docs/rlfence2/SHA256SUMS                           |    5 +
 docs/rlfence2/alt-h05-proof.json                   |  101 +
 docs/rlfence2/alt-io-audit.json.gz                 |  Bin 0 -> 469198 bytes
 docs/rlfence2/alt-io-changes.json                  |   97 +
 docs/rlfence2/alt-pad/POST-functions.tsv.gz        |  Bin 0 -> 148632 bytes
 docs/rlfence2/alt-pad/POST-sections.tsv.gz         |  Bin 0 -> 736 bytes
 docs/rlfence2/alt-pad/closure-proof.json           |   50 +
 docs/rlfence2/alt-pad/negative-controls.json       |   17 +
 docs/rlfence2/alt-pad/planned-retargets.json       |  198 ++
 docs/rlfence2/alt-pad/proof.json                   |   38 +
 docs/rlfence2/alt-source-receipt.json              |   11 +
 docs/rlfence2/alt-unit-pad/POST-functions.tsv.gz   |  Bin 0 -> 552 bytes
 docs/rlfence2/alt-unit-pad/POST-sections.tsv.gz    |  Bin 0 -> 626 bytes
 docs/rlfence2/alt-unit-pad/negative-controls.json  |   17 +
 docs/rlfence2/alt-unit-pad/pipeline.log            |    2 +
 docs/rlfence2/alt-unit-pad/planned-retargets.json  |  241 ++
 docs/rlfence2/alt-unit-pad/proof.json              |   38 +
 docs/rlfence2/alt-unit-pad/symmetry.log            |    1 +
 docs/rlfence2/alt-unit.log                         |    4 +
 docs/rlfence2/alt-write-ring.log                   |   21 +
 docs/rlfence2/alt.patch                            |   70 +
 docs/rlfence2/generic-merit-cells.txt              |   14 +
 docs/rlfence2/harness-controls.json                |   17 +
 docs/rlfence2/harness-positive.log                 |    4 +
 docs/rlfence2/headline-pre-identity.json           |   69 +
 docs/rlfence2/io-audit.json.gz                     |  Bin 0 -> 486835 bytes
 docs/rlfence2/io-changes.json                      |  179 ++
 docs/rlfence2/io-diffs/015.diff.gz                 |  Bin 0 -> 52076 bytes
 docs/rlfence2/io-diffs/025.diff.gz                 |  Bin 0 -> 47996 bytes
 docs/rlfence2/io-diffs/059.diff.gz                 |  Bin 0 -> 31351 bytes
 docs/rlfence2/io-diffs/061.diff.gz                 |  Bin 0 -> 38616 bytes
 docs/rlfence2/io-diffs/151.diff.gz                 |  Bin 0 -> 4564 bytes
 docs/rlfence2/io-diffs/217.diff.gz                 |  Bin 0 -> 8049 bytes
 docs/rlfence2/io-diffs/265.diff.gz                 |  Bin 0 -> 3361 bytes
 docs/rlfence2/io-diffs/275.diff.gz                 |  Bin 0 -> 3298 bytes
 docs/rlfence2/io-diffs/322.diff.gz                 |  Bin 0 -> 2891 bytes
 docs/rlfence2/pad-a/POST-functions.tsv.gz          |  Bin 0 -> 148664 bytes
 docs/rlfence2/pad-a/POST-sections.tsv.gz           |  Bin 0 -> 722 bytes
 docs/rlfence2/pad-a/closure-proof.json             |   50 +
 docs/rlfence2/pad-a/negative-controls.json         |   17 +
 docs/rlfence2/pad-a/planned-retargets.json         |  154 +
 docs/rlfence2/pad-a/proof.json                     |   38 +
 docs/rlfence2/post-unit.log                        |    4 +
 docs/rlfence2/post-write-ring.log                  |   21 +
 docs/rlfence2/production/SHA256SUMS                |    6 +
 .../alt-identity/CANDIDATE-functions.tsv.gz        |  Bin 0 -> 150939 bytes
 .../alt-identity/CANDIDATE-sections.tsv.gz         |  Bin 0 -> 738 bytes
 .../alt-identity/REFERENCE-functions.tsv.gz        |  Bin 0 -> 148632 bytes
 .../alt-identity/REFERENCE-sections.tsv.gz         |  Bin 0 -> 736 bytes
 .../alt-identity/differing-functions.json.gz       |  Bin 0 -> 1004664 bytes
 .../alt-identity/differing-functions.tsv.gz        |  Bin 0 -> 206115 bytes
 .../rlfence2/production/alt-identity/identity.json | 2929 ++++++++++++++++++
 docs/rlfence2/production/alt-io-audit.json.gz      |  Bin 0 -> 546530 bytes
 docs/rlfence2/production/alt-io-changes.json       | 3229 ++++++++++++++++++++
 docs/rlfence2/production/alt-io-diffs.txt.gz       |  Bin 0 -> 2838203 bytes
 docs/rlfence2/production/closure.json              |   50 +
 docs/rlfence2/production/default-build.log.gz      |  Bin 0 -> 1409 bytes
 docs/rlfence2/production/delayed-drain.log         |   10 +
 .../production/frozen-alt-identity-limit.json      |    5 +
 docs/rlfence2/production/frozen-h05-proof.json     |  101 +
 docs/rlfence2/production/harness-and-gate.json     |   79 +
 .../headline-identity/CANDIDATE-functions.tsv.gz   |  Bin 0 -> 150939 bytes
 .../headline-identity/CANDIDATE-sections.tsv.gz    |  Bin 0 -> 738 bytes
 .../headline-identity/REFERENCE-functions.tsv.gz   |  Bin 0 -> 150914 bytes
 .../headline-identity/REFERENCE-sections.tsv.gz    |  Bin 0 -> 725 bytes
 .../headline-identity/differing-functions.json.gz  |  Bin 0 -> 554836 bytes
 .../headline-identity/differing-functions.tsv.gz   |  Bin 0 -> 116944 bytes
 .../production/headline-identity/identity.json     | 2900 ++++++++++++++++++
 docs/rlfence2/production/headline-io-audit.json.gz |  Bin 0 -> 566183 bytes
 docs/rlfence2/production/headline-io-changes.json  |  236 ++
 docs/rlfence2/production/headline-io-diffs.txt.gz  |  Bin 0 -> 51304 bytes
 docs/rlfence2/production/identity-controls.json    |   13 +
 docs/rlfence2/production/mainline-verdict.txt      |   13 +
 docs/rlfence2/production/mget-fence-old.log        |   11 +
 docs/rlfence2/production/mget-fence-stale.log      |   11 +
 docs/rlfence2/production/mget-fence-unarmed.log    |   11 +
 docs/rlfence2/production/mget-fence.log            |    4 +
 docs/rlfence2/production/negative-pipeline.log     |    2 +
 docs/rlfence2/production/negative-unit.log         |    1 +
 docs/rlfence2/production/portable-unit.log         |    4 +
 .../server-control/PAD-A-functions.tsv.gz          |  Bin 0 -> 150939 bytes
 .../server-control/PAD-A-sections.tsv.gz           |  Bin 0 -> 738 bytes
 .../server-control/POST-functions.tsv.gz           |  Bin 0 -> 150939 bytes
 .../production/server-control/POST-sections.tsv.gz |  Bin 0 -> 738 bytes
 .../server-control/negative-controls.json          |   17 +
 .../server-control/planned-retargets.json          |  198 ++
 docs/rlfence2/production/server-control/proof.json |   38 +
 docs/rlfence2/production/source-receipt.json       |    9 +
 docs/rlfence2/production/transient.log             |   10 +
 docs/rlfence2/production/unit-build.log            |    2 +
 .../production/unit-control/PAD-A-functions.tsv.gz |  Bin 0 -> 552 bytes
 .../production/unit-control/PAD-A-sections.tsv.gz  |  Bin 0 -> 628 bytes
 .../production/unit-control/POST-functions.tsv.gz  |  Bin 0 -> 552 bytes
 .../production/unit-control/POST-sections.tsv.gz   |  Bin 0 -> 628 bytes
 .../production/unit-control/negative-controls.json |   17 +
 .../production/unit-control/planned-retargets.json |  241 ++
 docs/rlfence2/production/unit-control/proof.json   |   38 +
 .../production/unit-negative-controls.json         |   12 +
 docs/rlfence2/production/unit.log                  |    4 +
 docs/rlfence2/production/write-ring.log            |   21 +
 src/net/rob.h                                      |   42 +-
 tests/fixtures/nullrefresh-ledger-labels.json      |   26 +-
 tests/gate.sh                                      |   45 +-
 tests/gate_measurements.json                       |    8 +-
 tests/gate_subset.sh                               |    2 +-
 tests/gate_subset_test.py                          |    9 +-
 tests/gates_test.py                                |   48 +-
 tests/lb_stationary.py                             |  148 +-
 tests/persistfix.py                                |   52 +-
 tests/read_local_lane.py                           |  236 +-
 tests/rlfence_unit.cc                              |  145 +
 tools/rlfence_artifacts.py                         |  490 +++
 117 files changed, 14152 insertions(+), 84 deletions(-)
```
