# gt14fix — directed gate negative controls

Base: `ea177342dd9ce181488f0954fe436d5f25d78fe5` (merged `origin/cpp` before edits).
Implementation: `b3ac9f38d`, script watchdog bound `62266eb95`, and independent ON hammer witness `7641c85ca`, on `cx-gt14fix`. No push.

## What was probabilistic

* Atomic OFF RENAME previously offered up to four timed hammers, scaled toward 76,443 reads per roll. A read count did not establish that any reader sampled between the source and destination mutations.
* Script contention previously offered up to four rounds of two threads completing 40 opposite-order scripts each and required an OCC retry somewhere in those rounds. A legal collision-free schedule failed the detector.

## Directed mechanisms

`DEBUG ATOMIC-OFF-HOP-HOLD 1` arms the next cross-owner RENAME, in either atomic mode. The source proceeds and the destination parks in the existing deferred-task queue. `DEBUG ATOMIC-OFF-HOP-STATUS` returns 0 (off), 1 (armed/waiting), 2 (source complete, destination held), or 3 (expired). `DEBUG ATOMIC-OFF-HOP-HOLD 0` releases it. The existing hop-delay ceiling of one second is retained as a watchdog. An expired or never-opened window fails the test.

The deadline is also a generation token, so release/rearm cannot trap an older task. The hook stores no arena pointer, adds no allocation, and changes no structure layouts. Only DEBUG can arm it; DEBUG command permission checking still applies. Existing ATOMIC-OFF-HOP-DELAY and ATOMIC-COMMIT-DELAY semantics remain intact.

`rename_held` waits for source completion, reads while the destination is held, verifies that the hold is still active after the read, releases, and checks the exact final destination value and successful RENAME reply. OFF requires `[nil, nil]`; ON requires `[rename-value, nil]`. The existing ON repeated-RENAME hammer also remains.

The script detector uses the existing `DEBUG SCRIPT-STAGE-DEFER 1000000`: one script gathers its coordinator key and pins its cut while the other gathers are deferred. Counter polling proves that stage. Disarming the knob leaves that activation's captured deadline intact and prevents the opposite-order script from also deferring. The competing script commits, and exact stage/run/retry counters prove the first script has still not advanced. It then resumes, detects the changed read set, retries at least once, and both scripts must leave every key at 2. The ordinary 2×40 loop now asserts only termination, successful completions, and every key at 80. There is no retry-on-miss or skip-on-miss in either directed detector.

## Sites and ordinary-command audit

* `src/cmd/t_server.cc:1085`: `cmd_debug_impl` parses HOLD and STATUS behind existing DEBUG permission checks.
* `src/cmd/debug.h`: declarations only.
* `src/cmd/scatter_engine.inc:1140–1183`: `arm_debug_off_hop_delay` arms the one-shot latch; new `debug_hop_pending`, `debug_atomic_off_hop_hold`, and `debug_atomic_off_hop_status` implement it.
* `src/cmd/atomics_glue.inc:611`: the existing nonzero debug-hop branch in `xshard_task_should_defer` calls the cold latch/deadline helper.
* `tests/atomic_torn.py:405`: new directed helper and replacement of the OFF discovery loop; ON additionally exercises the held hop.
* `tests/xscript.py:583`: only `contention_and_deadlock` changes.

PRE/POST objects were built with the same default Makefile flags and compiler, on cores 112–127. Existing `tools/lbstall_artifacts.py compare` reports **1,482/1,482 selected ordinary hot bodies raw-byte identical and relocation-target identical**, in both linked database variants. This is an object-code statement, not a claim that linked addresses are unchanged. Full function and section tables use `tools/rlfence_artifacts.py`'s `tables` helper. A broader inventory also records compiler-generated differences outside that selected hot set (including INFO, RANDOMKEY, cross-shard/transaction helpers, notification/configuration helpers, and a read-local poison helper); full ordinary-command byte identity is therefore **not** established by the selected-hot audit. All differences within the two modified translation units (both database variants) are enumerated in `docs/gt14fix/changed-functions.json`.

| Artifact | PRE | POST |
| --- | ---: | ---: |
| `.text` bytes | 7,796,224 | 7,797,376 |
| Defined functions in table | 10,279 | 10,285 |
| Selected ordinary hot bodies identical | — | 1,482/1,482 |

This is a correctness-hook change, with no performance claim or PAD measurement arm. Binary hashes and source-scope checks are in `docs/gt14fix/artifacts.json`; binaries remain under `build/gt14fix/tomokv-PRE` and `build/tomokv`.

## Validation

Directed initial smoke passed at 16 shards, 6 io + 2 ex, server cores 112–119, clients 120–127: OFF held RENAME tears once; ON never tears; script retries +1; both liveness/count checks pass.

The following exact subset command was run 30 times, with the gate's own prerequisites, boots, watchdogs, finalizers, and full job bodies:

```bash
GATE_ONLY_JOBS='atomic_batteries debug-1' taskset -c 112-127 bash tests/gate.sh quick \
  --server-cores 112-119 --load-cores 120-127 --load-smt '' --ports 19900-19902 \
  --candidate-binary "$PWD/build/tomokv"
```

The campaign completed all 30 repetitions. Results are deliberately separated by target battery and containing job:

| Scope | Campaign result |
| --- | ---: |
| `atomic torn/window battery` (full `atomic_torn.py`) | **30/30 PASS** |
| `xscript battery (atomic 1)` (full `xscript.py`) | **30/30 PASS** |
| Complete `debug-1` job | **30/30 PASS** |
| Complete `atomic_batteries` job | **29/30 PASS** |
| All campaign gate rows | **569 PASS / 1 FAIL** |

Every OFF RENAME witness was `invalid=1 reads=1`; every ON arm was torn-free; every directed script collision reported exactly `retries=+1`. Repetition 30 failed the separate, unchanged `pipelined atomic groups beat the serial round-trip rate` check in `atomic_ryow.py`: pipeline 39,508/s, serial 40,747/s, ratio 0.97. This result is retained, not called noise or removed from the denominator. Therefore the requested **30/30 for both entire jobs was not achieved**, although both target files and both repaired controls passed all 30 times.

The campaign used test revision `62266eb95`. Final review then kept the ON hammer's read count independent of the additional held read (`7641c85ca`), preserving the original nonempty-hammer assertion. The collector subtracts the one held read from each campaign ON count and verifies the final stricter predicate for all 30 observations: the minimum original hammer count was **46,225**. The server binary and directed schedules did not change. A fresh complete subset run on `7641c85ca` then passed **19/19 rows**, including both full target batteries and the RYOW rate check. This supplementary pass does not erase the campaign failure.

Per-run ledgers, compressed complete target-test logs, the failed RYOW log, source/binary hashes, and counters are in `docs/gt14fix/repeat/summary.json` and its adjacent files. The final run is in `docs/gt14fix/final-gate.log`, `final-gate.ledger`, `final-verification.json`, and the two `final-*.log` target logs. These subsets are diagnostic, not full gate receipts.

Reproduce the evidence collection with:

```bash
taskset -c 120-127 python3 tools/gt14fix_evidence.py --test-revision 62266eb95
```

The collector verifies all 30 original ON hammer witnesses, both target-file PASS trailers, every containing job's real pass/fail tally, every subset exit code, the CPU/ratio plan, and equality with the byte-audited POST binary hash.

## Scope and remaining nondeterminism

Gate delta **0 quick / 0 full**. `tests/gate.sh`, `tests/gate_subset.sh`, EXPECT constants, and fixtures are unchanged. AST checks verify every existing `atomic_torn.py` helper and every `xscript.py` helper except `contention_and_deadlock` is unchanged, and all literal check labels are preserved. Unrelated top-level atomic checks are unchanged.

OS scheduling, connection progress, and watchdog deadlines still bound liveness. The directed windows fail loudly if the debugger cannot establish or retain them; they do not rely on two independent operations happening to collide. Existing unrelated hammers, conditional/store controls, live-flip checks, and latency budgets retain their original nondeterminism and intent. The script defer still has its existing timer-based release, but counter witnesses require the competing commit to occur entirely inside the captured stage window.

The first prerequisite build took nine minutes. The 60-minute lane target was exceeded; the work ran from 15:50 UTC to approximately 17:15 UTC (about 84 minutes), including the full repetition campaign, additional fused/fault controls, and final corrected-file verification. Measured job durations in repetition 1: debug-1 73.266 s, atomic_batteries 35.876 s. Thirty unmodified complete repetitions cannot fit inside the original 60-minute lane target including setup/builds; that conflict was reported while validation continued.

Additional full batteries were run serially between subset repetitions, on server CPUs 112–119 and client CPUs 120–127. `tests/xscript.py` passed in 1s mode. The full 1s `tests/atomic_torn.py` passed both new RENAME arms but failed its unchanged `atomic reconfiguration preserves derived bound and reclaims leases` check: `CONFIG exceeded the lease hold's arm budget` (`arm_s=5.007`, limit 256, groups 641, peak 256). A fresh 1s boot of PRE, running the original PRE test file, passed that full battery. A subsequent fresh candidate 1s boot also passed the complete current atomic battery (`full-atomic-fused-repeat.log`). These runs do **not** establish that the earlier fused failure predates the change; it is retained as an unresolved intermittent result outside the two directed controls. Both logs are retained, and no timing threshold or other check was edited.

The throwaway `build/gt14fix/tomokv-no-hold` patches only the two DEBUG HOLD setters to return immediately. The directed RENAME runner exits 1 with `source-complete hold not witnessed: status=0 replies=[b'OK']`, proving that a missing hold cannot pass. Patch offsets, original/replacement bytes, and binary hashes are in `docs/gt14fix/no-hold-control.json`. This is a fault-control binary, not a PAD or performance arm.

Final source checks: `git diff --check` and Python compilation pass. `src/`, `tests/gate.sh`, `tests/gate_subset.sh`, and fixtures are unchanged between the campaign revision and final code revision; only the ON test counter bookkeeping differs. The original source-scope checks still hold. No fixture, EXPECT, row label, or threshold was edited. No server or load generator remains from this lane.
