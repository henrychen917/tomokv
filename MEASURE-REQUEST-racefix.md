## racefix

**WIP; stopped at the owner's hot-body identity condition. No push.** Both
findings reproduce on PRE and their directed checks pass on POST, but the
candidate changes 57 selected hot bodies. It is not ready to merge. The task
requires: “if any hot body changes, list it and stop for an owner decision
instead of landing it.” No exception to that rule is assumed.

Worktree/branch: `/home/user/Projects/cx-racefix`, `cx-racefix`.
PRE is `5146b78ee89b64748dd46db970efa8086f653fa0`; both requested fetch/merges
reported already up to date. The second merge preceded candidate production
changes and POST proof. Production changes are in WIP commit `4514190b2`;
later commits add test wiring, evidence, and this report. Compiler: GCC 13.3.0.
All shell commands were confined to CPUs 112–127. Directed servers used
112–119, 16 shards, split ratio 6:2 or fused mode, and ports 25175–25176.

| Binary | SHA-256 |
|---|---|
| PRE `build/racefix/pre/tomokv` | `3542d37f28967ea9fc0084ce1425d700b67bbd8deb3ce35fc65708ce17b449ed` |
| POST `build/tomokv` | `3f5017677808471a8aae0951c7bc8743f28a418ba8325df874714f022943b493` |
| PRE `build/racefix/pre/tomokv-tsan` | `64e88def88e7e40f9286b661e5134b3d6d6fd9cf25bbb824627f6b9526e27ae9` |
| POST `build/tomokv-tsan` | `7ddb57006757a2d6f1ca2744ccc1928b365d63fae7e06bb32a9e9e7f87e1fab4` |
| PRE `build/racefix/pre/climon` | `ec426b34da4257fe6dc8807076725affa8dc3a3e5af583cd77f0966b1f76b31c` |
| POST `build/racefix-climon` | `1aa087ffe91dfcadcfbc22638342e67371d887bb309ecf7c46c37fa41846cf6f` |

**SV4.9 — confirmed before production edits.** The bounded T6 client performs
64 SET/GET pairs and fails if the sampler never reports a nonzero rate.
PRE's TSan reports pair `info_stats_tick:113–115` with the command increment
at `thread.h:436`, receive bytes at `io_loop.h:2318`, and send bytes at
`wb.h:587`. GCC's sanitizer omitted some large-template inline locations;
`addr2line` against the exact hashed ELF recovered them. Raw and symbolized
logs remain separate; an unrelated warning never counts as confirmation.

| T6 mode | PRE sampler witness | PRE counter reports / cron-writer pairs | POST sampler witness | POST counter reports |
|---|---:|---:|---:|---:|
| split 6:2 | 75 | 5 / 4 | 75 | 0 |
| fused | 80 | 6 / 4 | 73 | 0 |

These rates witness the sampler, not benchmark throughput. PRE fails the
counter check in both modes; POST passes the same scoped check in both modes.
**POST is not globally TSan-clean:** both runs still report two other INFO
races, on `LoopSignals::accepts` and `plain_accepts` (INFO reads at
`t_server.cc:1931/1939`, writer `IoLoop::admit_fd`). They are not suppressed.
The server exits 66 for those diagnostics; the counter-specific driver reports
zero races for its selected family. PRE also exposed plain writeback-stat
reads, including `sends_submitted` and `bytes_sent`; their absence from the
POST sample is not a claim that they were fixed.

The candidate changes total commands, all three command-count arrays, and
socket-byte counters to relaxed atomics, with single-owner load/store updates.
All INFO/cron readers of that family use relaxed loads. No counter update
uses a lock-prefixed RMW or a fence. Files: `src/core/thread.h`, `signal.h`,
`io_loop.h`, `reorder.cc`, `src/net/wb.h`, `src/cmd/info_stats.cc`, and INFO
aggregation in `src/cmd/t_server.cc`. Only counter-increment sites changed in
`io_loop.h`; no flip fingerprint or clientfix gate/pause code was edited.

Receipts: [PRE split](docs/racefix/pre-counters-2s/result.json),
[PRE fused](docs/racefix/pre-counters-1s-retry/result.json),
[POST split](docs/racefix/post-counters-2s/result.json),
[POST fused](docs/racefix/post-counters-1s/result.json).

**SV4.10 — confirmed before production edits.** A parks holding zero, B opens
its MONITOR and publishes an armed value, then A publishes zero after B.
In both modes PRE has `monitor_clients=1`, `armed_word=0`, no exact marker
within 1 second, and no feed-counter advancement. Suppressing only A's stale
publication delivers the marker in both modes. Serial witnesses are park=2,
B arm=3, and A's forced stale publication/suppression=4.

The final identical PRE/POST client also waits for a PING reply from A after
that publication. PING cannot refresh the global word; it proves A has
completed its cold refresh, including POST's repair. The client then requires
the exact marker and a settled armed word of 1. PRE fails and POST passes in
both modes; all four suppression-control runs pass. POST's four cases took
3.15–3.47 seconds each, about 13 seconds for the new gate row.

The candidate edits only `Server::refresh_climon_armed` in `server.h` for this
finding. An acquire/release exchange observes preceding refreshes' mutations;
a fresh counter snapshot repairs a stale publication before the refresh
returns. Only this cold writer retries. The per-batch reader's source remains
its original relaxed load, and the eight locked layouts remain identical.
The full hot-body comparison nevertheless fails and is not waived.

`tools/racefix_build.py` inserts the hook immediately before the publication,
and the DEBUG parser, into a copied witness source tree. The separate Makefile
target is `build/racefix-climon`; no hook symbols exist in the default ELF.
The hook's release command changes only test state and never refreshes the word.

Receipts: [PRE split](docs/racefix/final-pre-climon-2s-store/result.json),
[PRE fused](docs/racefix/final-pre-climon-1s-store/result.json),
[POST split](docs/racefix/final-post-climon-2s-store/result.json),
[POST fused](docs/racefix/final-post-climon-1s-store/result.json).
Corresponding `final-{pre,post}-climon-{2s,1s}-suppress` directories contain
every suppression control. All owned children were reaped and their ports
closed. Initial fused attempts supplied `--ratio` and failed before boot;
those logs remain recorded. Completed fused runs omit that split-only option.
The actual INFO field is `monitor_feed_lines`.

**Default-build identity — FAIL.** The unmodified prescribed checkers compare
opcodes and resolved relocation targets. Layout inspection covers both
namespaces, all eight locked sizes, and every named member offset.

| Check | PRE / inspected | POST equal | Changed |
|---|---:|---:|---:|
| Selected hot bodies, `tomo` | 601 | 575 | 26 |
| Selected hot bodies, `tomo_db0` | 603 | 572 | 31 |
| Full bodies, `tomo` (PRE / POST) | 8,391 / 8,398 | 8,234 | 164 |
| Full bodies, `tomo_db0` (PRE / POST) | 7,902 / 7,907 | 7,753 | 154 |
| Full checker's hot selection, including executor run bodies | 1,208 | 1,151 | 57 |
| Command handlers | 1,210 | 1,205 | 5, all INFO/CONFIG |
| Layout locks and member offsets | 8 per namespace | all equal | 0 |
| `.text` bytes | 7,582,188 | 7,587,532 | +5,344 |

`ThreadCtx::note_command` changes from **31 to 54 bytes** in both namespaces,
in each of the three emitting loop objects. PRE has two memory `incq`
instructions; POST has explicit MOV/INC/MOV sequences, address calculation,
and different branches. No counter LOCK or fence appears. This directly
violates the requested identity condition even though the layout is unchanged.

**Every changed emitted body is listed with its reason** in
[changed-bodies.md](docs/racefix/changed-bodies.md) and
[changed-body-reasons.json](docs/racefix/changed-body-reasons.json).
Compiler collateral is explicitly identified and not claimed to be an allowed
cold delta. The two fixes were not separately built to isolate every propagated
compiler difference. Original checker output is retained in
[hot.json](docs/racefix/hot.json),
[full summary](docs/racefix/full/summary.json),
[full body inventory](docs/racefix/full/bodies.json.gz),
[linked sections](docs/racefix/linked.json), and
[layouts](docs/racefix/layouts.json).
[PRE disassembly](docs/racefix/pre/note-command.txt) and
[POST disassembly](docs/racefix/post-note-command.txt) show the counter change.
No performance verdict, PAD arm, benchmark, or full gate run is claimed.

**Gate accounting:** DQ **+2**, DF **+2**. New labels are
`INFO command/socket counters (TSan, both modes)` and
`Climon armed refresh + stale-store suppression control`.
Their `collect_job` calls are at `tests/gate.sh:3292/3293`, before the quick-tier
exit at line 3460 (row declarations at 3100/3113). The TSan build has a separate
readiness job; the Climon witness joins `job_production_units` and its `make -q`
list. Both labels are in the fixture, and scheduler fixtures register the new
build-only helper.

Required EXPECT values from the merged base: **511 + 2 = 513 quick;
528 + 2 = 530 full**. The arithmetic comment is above the untouched constants.
The literal `python3 tests/gate_ledger_fixture.py` command currently fails:
source=530, fixture=530, EXPECT_FULL=528, with no missing or extra labels.
Its original checker passes with 530 in an in-memory string only; this is a
projected count check, not a passing check of the actual gate. The owner must
update the constants. [Projection](docs/racefix/ledger-projection.json).

**Completed proof and remaining work:**

The machine-readable [proof manifest](docs/racefix/proof.json) links build
commands, binary hashes, directed receipts, and failed or pending checks.

- PRE and POST `make -j16 all` (PRE with `BUILD_ROOT=build/racefix/pre`) and
  `make -j16 tsan` passed. Both isolated Climon builds passed. Binary hashes,
  commands and logs are retained; no source/compiler flag relaxation was made.
- `build/wb-rule-units`, `build/wbland-units`, and `build/racefix-climon` are
  fresh: **3/29** production-unit targets. Both Climon mask units are also
  fresh. All target freshness results are in
  [unit-freshness.json](docs/racefix/unit-freshness.json).
- `python3 tests/wbland_checks.py check clauses`: **83/83 strict outcomes**
  after building its prerequisites. The first attempted check failed because
  `build/wbland-unit` did not yet exist; both logs are retained.
- Climon mask unit passes tracking and monitor checks for all 64 owner pairs,
  in both disarm directions. Its old-code control exits 1 as required.
- `python3 tests/gates_test.py` **did not pass**. The last run, after this
  lane's builds ended, ran 66 tests and had 12 scheduler-fixture failures
  associated with the unchanged 45-second timeout (exit 124). Earlier runs
  had 14 failures. The new helper was added to the fixture registry, but the
  final timeout cause remains unisolated; this is not called noise or a pass.
  The [last log](docs/racefix/gates-test-quiet.log.gz), earlier logs, and the
  `build/scheduler-failure-*` artifacts remain available.
- `bash -n tests/gate.sh` and `git diff --check` passed. The ledger validator's
  count failure is recorded separately above.
- Both directed row drivers fail on PRE for the intended reason and pass on
  POST; Climon suppression controls pass. TSan's unrelated reports remain
  explicit. The rows were exercised directly, not by running the full gate.
- The remaining **26 production-unit targets**, `mdbqsbr-live-arms`, the
  Redis-7.4 differential matrix, and live `climon.py`, `climon2.py`,
  `climon_128.py`, `tracking.py`, and `infofix.py` batteries remain **unrun**
  at the identity stop. No full regression or merge-readiness claim is made.

The pending differential matrix is `climon monitor infofix servertail
compatintro`, seeds **7, 19, 20, 23**, split 6:2/16 shards and armed fused,
both atomic modes as provided by `tests/differ_gate.sh`. Target CPUs 112–119,
oracle CPU 120, driver CPUs 121–127, ports 25177/25178, oracle root
`/home/user/Projects/redis74`. The suites and seeds are recorded under
`docs/racefix/differ-{suites,seeds}.txt`; it was not launched.

Recheck the already completed directed witnesses with fresh output directories:

```sh
taskset -c 112-127 python3 tests/racefix.py counters \
  --binary build/tomokv-tsan --mode 2s --cores 112-119 --port 25175 \
  --output build/racefix/recheck-counters-2s
taskset -c 112-127 python3 tests/racefix.py climon \
  --binary build/racefix-climon --mode 2s --cores 112-119 --port 25176 \
  --output build/racefix/recheck-climon-2s
```

Repeat with `--mode 1s`; add `--suppress-stale` for the Climon control. The
same client against the saved PRE binaries supplies the negative controls.
The owner decision concerns accepting changed hot instructions; the WIP
has not been presented as satisfying that condition.
