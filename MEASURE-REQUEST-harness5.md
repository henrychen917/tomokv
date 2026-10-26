## harness5

Lane base `3700b51d7`, branch `cx-harness5` (no push). Codex produced a2bf829f2, 2ce654576 and b29331e59 and stopped
on a content filter (WIP a21813aa9); an Opus continuation finished the lane. No production code changed: the branch
touches no `src/` or `Makefile` line, and `build/tomokv` is binary-neutral **IDENTICAL** to
`bench-bins/tomokv-headline-3700b51d7`. Every process ran on CPUs 32–47 and listener ports 45800–45899; no performance
benchmark, measurement load generator or full `tests/gate.sh` iteration was run.

| Item | Result |
|---|---|
| CG4.6 optional workload axes in floor/ceiling DATA validators | **FIXED** (codex). Red with the repair reverted / green, through `GATE_ONLY_JOBS=abba_selftest` |
| CG4.6 epoll freeze/current-campaign/promotion workflow | **FIXED** (codex): `freeze-null --cells`, own-inventory replay, `baselines/epoll-null.json`. Red/green via the gate job |
| CG4.7 smoke/iteration comparison binds a promoted full null | **FIXED** (codex). Red/green via the gate job |
| CG4.8 receipt retains and replays both product passes | **FIXED** (codex) **+ writer hardening** (this continuation: no stale `product.json` survives an interrupted run). Red/green |
| WB4.8, WB4.9, CL4.3, CL4.4 | Documents corrected to what code and receipts establish; no claim strengthened (codex; re-checked) |
| Redis 7.4.10 Tcl suite, 135 files, both modes | 2s 1649 / 1s 1645 passed (Redis 2219 with the same skips); **510 failing tests: 161 unsupported by design, 33 Redis-internal, 316 REAL in 72 root causes**, every REAL root reproduced on both servers |
| Tcl-subset gate job `redis_tcl` | **35 files, 1611 assertions per mode**, 424 named known failures; ok on this branch (both modes), **FAIL on a planted regression**; **DQ = 0, DF = 0** |
| ABBA self-test row | landing-like geometry **430.98 → 403.06 s** (median, 27.9 s faster); isolated 371.46 → 333.44 s (38.0 s faster); row budget 1620 → **660 s** (newest landing 442.80 s × 1.4, rounded up) |
| Builds | `make all` and all 42 `job_production_units` targets + `mdbqsbr-live-arms` + `blockfix-cost` built; `make -q` fresh for every one |
| `python3 tests/gates_test.py` | **72 tests OK** (85.3 s) |
| Instrument fingerprint | changes 936cc050… → 04518427… (abbagate and its imports changed); the only standing null on the box (cx-final, 2026-09-12) binds 219de131… and already did not match the base. A fresh frozen/promoted null is required before a certified comparison, as for any harness landing |


### 1. CG4.6, CG4.7, CG4.8 — harness repairs (codex commits 2ce654576, b29331e59; verified here)

| Register row | Defect (round-4 T5) | Repair | Regression test(s) |
|---|---|---|---|
| CG4.6 (a) | `server_flags`, `dbs`, `poll`, `keys`, `client_flags` are emitted by `shape()` but the floor and ceiling DATA validators accepted only the ten base fields (+`data_bytes`), so a measured new-axis floor could not be imported | `gate_measurements.validate_shape()`: exactly the `shape()` axes, typed, and the cell grammar re-parsed through `abbagate.cell_options`; used by `load()` and `abba_ceiling.validate_ceiling_plan()` | `gate_measurements` `test_optional_axes_round_trip_floor_and_ceiling_data` (5 single axes + all combined; 6 refusals) |
| CG4.6 (b) | freeze / current-campaign / promotion hard-coded the 181-cell headline inventory, so the 32-cell epoll pass had no standard frozen/promoted null | `inventory()` accepts exactly the 32 `h01–h32` epoll twins for `tests/netio_cells.txt`; `freeze-null --cells`; `current_campaign` re-reads the campaign's own inventory path; promotion of an epoll campaign writes `baselines/epoll-null.json`, never `full-null.json` | `_nullrefresh_test` `test_epoll_companion_calibrates_freezes_and_checks_its_own_inventory` |
| CG4.7 | matching a promoted full null ran full-campaign validation on the comparison itself, which refuses `subset=smoke` / `only` | `_match_null` replays every raw block of the comparison with `full=False` unless it is a holdout; the control stays fully validated and exact cell coverage is still required afterwards | `abbagate` `test_real_null_collection_comparison_and_subset_controls` (promoted control: full 8 calls PASS, smoke 4 calls PASS; `only=n1` stays PARTIAL and `validate_comparison` refuses it) |
| CG4.8 | the 213-cell product contributed one combined exit code; the receipt retained/replayed only the headline report and null | `gateprod.run_gate` writes `product.json` (each pass's exit code + sha256-bound report and null); `gate_receipt finish/validate_receipt` require both passes rc 0, the headline pass identical to the receipt's report/null, the epoll inventory unchanged since `begin`, and replay the epoll report and null through the unchanged validators; `evidence.json` retains the product | `gate_receipt` `test_full_product_retains_and_replays_both_passes` (7 mutations + recomputed-digest forgery), `test_aggregate_zero_without_product_cannot_issue_receipt` |

**Verification: fail before, pass after, through `GATE_ONLY_JOBS=abba_selftest bash tests/gate.sh quick`.**
"Before" = scratch worktree at a21813aa9 with ONE repair's hunks replaced by the 3700b51d7 text and every new test kept
([cg-red/revert_fixes.py](docs/harness5/cg-red/revert_fixes.py); a hunk that does not apply exactly once is an error).

| Repair | Row with that repair reverted (new tests kept) | Failing tests in that red run | Row on this branch |
|---|---|---|---|
| CG4.6 (a) DATA validators | **FAIL** 329.06 s | `test_optional_axes_round_trip_floor_and_ceiling_data` (all 6 axis subtests) and 22 receipt tests, whose fixtures load the epoll companion floors (`server_flags` axis) | **ok** (333.44 s isolated; 403.34 / 402.79 s landing-like) |
| CG4.6 (b) epoll freeze/promotion | **FAIL** 378.82 s | exactly `test_epoll_companion_calibrates_freezes_and_checks_its_own_inventory` | **ok** (333.44 s isolated; 403.34 / 402.79 s landing-like) |
| CG4.7 promoted-null subset match | **FAIL** 357.34 s | exactly `test_real_null_collection_comparison_and_subset_controls` (smoke vs promoted control: `(3, 4, PARTIAL)` instead of `(0, 4, PASS)`) | **ok** (333.44 s isolated; 403.34 / 402.79 s landing-like) |
| CG4.8 receipt product evidence | **FAIL** 352.97 s | exactly `test_full_product_retains_and_replays_both_passes`, `test_aggregate_zero_without_product_cannot_issue_receipt` | **ok** (333.44 s isolated; 403.34 / 402.79 s landing-like) |
| all four reverted | **FAIL** 310.87 s | the union of the above | — |
| CG4.8 writer (this continuation) | base `run_gate` spliced in, direct `gateprod.py --self-test`: **ERROR** | exactly `test_product_record_binds_both_passes_and_refuses_changed_or_interrupted_evidence` | 9/9 gateprod tests ok |

The same reverts run directly through each owning suite isolate the same tests ([cg-red/](docs/harness5/cg-red/)).
"Without changing any measurement result for existing cells": the serverless census of every tracked `*cells*.txt`
(66 files, 1,230 cells, both arms, every ladder rung to 24 plus the pin: 14,670 server and 106,370 load argv) on the
final tree is byte-identical to the base (sha256 `de21c0e5…`, [argv-comparison.json](docs/harness5/argv-comparison.json)).


### 2. WB4.8, WB4.9, CL4.3, CL4.4 — documentation (codex commit a2bf829f2 + WIP; re-checked here)

| Row | Correction | Basis |
|---|---|---|
| WB4.8 | `MEASURE-REQUEST-wbknobs.md` no longer says the verdict is pending; a dated **MEASURE-RESULT** transcribes the maintainer's 2026-10-09 record: CLEAN 14-cell **1s-only** default null; one same-binary A/B/B/A p8 block, half rule vs 16/3: GET 14.83→16.13 Mops/s (+8.72%, higher is better), SET 14.79→15.96 (+7.90%), recorded **rc=3 PARTIAL** (untrusted standing null); landed 6b50f447f after a 521/521 gate | PLAN-SERIAL.md 2026-10-09 15:35 / 16:13–16:17 / 17:55 entries, bound with hashes in `docs/harness5/historical-claim-sources.json`; explicitly **not** a current-binary, 2s or merit certification |
| WB4.9 | S (`kSmallPipe=16`) and D (`kCompleteVisits=3`) are boot-knob **defaults** (`--wb-small-pipe 0..64`, `--wb-complete-visits 0..255`), not hard-coded rule inputs; ledger §16 "pending" → landed | `src/core/wb_rule.h:14,18,22-23`, `src/core/config.h:514-515,1006-1017,1284-1285,1349` (re-read in this continuation) |
| CL4.3 | 109 B/key, eight-core node optimum, "Dragonfly already optimally tuned": each marked **unsupported for the current binary** (no current executable binding; the four-core collapse is retracted in the note itself) | `docs/harness5/claims-and-constants.md` |
| CL4.4 | "every other hot-path constant derived for free or inert within ±1.7%" marked **unsupported** as a universal claim; limited to the named 45-arm GET/SET p32 screen | same |

No claim was strengthened; no production code changed.


### 3. Redis 7.4.10 Tcl suite against TomoKV (owner item 2026-10-25)

Full report and every classified test: [docs/harness5/redis-tcl-suite.md](docs/harness5/redis-tcl-suite.md);
machine-readable: [redis-tcl-summary.json](docs/harness5/redis-tcl-summary.json) (passed/failed/skipped per file and
server, survey and reach, every failing test with class/root/basis, every root with its reproduction verdict).

| Server (external mode, `--singledb`, fresh server per file) | Passed | Failed | Skipped | Files interrupted |
|---|---:|---:|---:|---:|
| TomoKV 2s, full-file survey | 1423 | 459 | 228 | 7 of 135 |
| TomoKV 1s, full-file survey | 1420 | 462 | 228 | 7 of 135 |
| Redis 7.4.10, full-file survey | 2252 | 78 | 251 | 4 of 135 (all `unit/moduleapi`: the test modules are not built) |
| TomoKV 2s, interrupted files reached (hung tests skipped) | 1649 | 550 | 280 | 0 |
| TomoKV 1s, interrupted files reached | 1645 | 554 | 280 | 0 |
| Redis 7.4.10, same skip list | 2219 | 79 | 282 | 0 |

Counts are assertion events, not defects. Seven files never completed on TomoKV (a test waited forever, or
`unit/type/stream`'s file-level `CONFIG SET appendonly yes`); `docs/harness5/reach_tcl.py` reran each with every hung
test named in `--skipfile` until it completed, then ran 2s, 1s and Redis with the same union skip list.

| Class (owner's definitions) | Failing tests | Independent (not a cascade) | Root causes |
|---|---:|---:|---:|
| unsupported by design (replication, cluster, modules, DEBUG internals, keyspace layout) | 161 | 158 | 5 |
| Redis-internal assumption (memory, encoding thresholds, timing, persistence counters, external-mode test needs) | 33 | 26 | 10 |
| **REAL compatibility defect** | **316** | **232** | **72** |
| total | 510 | 416 | 87 |

Every REAL root has a minimal command-level reproduction replayed on fresh TomoKV 2s, TomoKV 1s and Redis servers
([cases](docs/harness5/redis-tcl-repro-cases.json), [results](docs/harness5/redis-tcl-repros.json), runner
`docs/harness5/repro_tcl.py`): all 79 cases are DIFFERENT in both modes; the one boot-dependent root has a per-boot
probe instead ([watch_probe.py](docs/harness5/watch_probe.py), [results](docs/harness5/redis-tcl-watch-probe.json)).
14 REAL roots carry a design note (deliberate TomoKV restrictions outside the owner's unsupported list — script
whitelist/declared keys, instruction limit / no busy window, immutable appendonly / tracking-table-max-keys / port,
MULTI refusals, ACL for scripts, ...; and LUA-HELPER-LIBS, implemented on the unmerged branch `cx-lualibs`).

**Read first** (details, subsystems and reproductions in the suite report):
- `FUNCTION-LIST-CRLF` — `FUNCTION LIST "X\r\n+INJECTED"` (an unknown argument) echoes the raw CR/LF in its error, so the
  connection's next command reads `+INJECTED`: a forged reply / desynchronised connection.
- Hangs (an expected reply, push, block or wake never arrives): `BLOCK-MOVE-WRONGTYPE-STRANDS`,
  `BLOCK-WAKE-RENAME-SORTSTORE` and `BLOCK-STREAM-REMOVED-NO-UNBLOCK` (a blocked client is never served),
  `MULTI-XREADGROUP-BLOCK-HANG` (EXEC never returns; hangs on a fresh server), `PUBSUB-REPLY-OFF-PUSH`,
  `MONITOR-SCRIPT-CMDS`, `PUBSUB-EVICT-ON-MAXMEMORY`, `PAUSE-EXEC-NOT-HELD`, `PAUSE-MAY-REPLICATE`,
  `PAUSE-SCRIPT-FLAGS`, `TRACK-BCAST-BATCH`, `TRACK-MAXKEYS-IMMUTABLE`.
- Data / ordering: `STREAM-TRIM-APPROX-LIMIT` (`~` trims past LIMIT), `BLOCK-WAKE-ORDER-MULTI`, `BLOCK-CHAIN-ASYNC`,
  `SCRIPT-NUMBER-ARG` (Lua number arguments stored as `%.14g`), `RESTORE-IDLETIME-FREQ-IGNORED`, `DUMP-STREAM-REFUSED`,
  `WATCH-SPURIOUS-INVALIDATION` (an SMOVE that leaves `dstset` unchanged aborts a transaction watching `dstset` on
  3/30 fresh 2s and 5/60 fresh 1s boots, every iteration within such a boot; never on Redis 0/30).
- Out-of-memory gating gaps: `MULTI-OOM-QUEUE`, `MULTI-OOM-EXEC`, `PUBSUB-SUBSCRIBE-NO-DENYOOM`,
  `FUNCTION-LOAD-DENYOOM`, `PUBSUB-EVICT-ON-MAXMEMORY`.

Not a compatibility defect, reported as observed: a transaction writing the **same key** N times is **O(N²) at EXEC**
on TomoKV in both modes (XADD one stream: 0.20 s / 0.82 s / 3.39 s for N = 1000/2000/4000; RPUSH one list
0.05/0.22/0.96 s; distinct-key SETs stay linear, 0.002-0.011 s; Redis 0.001-0.013 s for all three). This is why
`unit/type/stream`'s "XADD mass insertion and XLEN" (10,000 XADDs in one MULTI) takes ~24 s instead of < 1 s.
Diagnostic only, one transaction per size: [multi_samekey_probe.py](docs/harness5/multi_samekey_probe.py),
[output](docs/harness5/multi-samekey-probe.txt).

**What codex's run "exposed".** Codex's log (CODEX-OUT.md line 17904, while fixing CG4.6/CG4.7): "The Redis run has also
exposed command-level differences that need separate reproductions, including RESET behavior" — i.e. the
command-level differences catalogued above (RESET inside MULTI is queued, a MONITOR client sees its own RESET).
Codex's 139 `R` entries were mechanical (any exact-name selection failing on TomoKV and passing on Redis); this
continuation replaced its keyword classifier with a reviewed per-test triage (four groups in
[docs/harness5/triage](docs/harness5/triage/), root causes merged across groups) and removed `classify_tcl.py`,
`protocol_repros.py` and their outputs. 94 failures are cascades (they pass on a fresh server or follow from an
earlier test's leftover state, including the builder's skip lists) and carry their root test's class.

**Coverage limits.** 42 scripting tests behind `DEBUG SET-DISABLE-DENY-SCRIPTS`, 6 list and 5 list-3 tests behind
`list-compress-depth`, 10 stream-cgroups tests behind an `appendonly yes` block and the `needs:debug` appendonly blocks
of `unit/type/stream` never run on TomoKV: their block setup is refused (classified as the setup entry). External
mode skips tests that need to own the server process (both servers).


### 4. The Tcl-subset gate job (`redis_tcl`)

| Check, through `GATE_ONLY_JOBS=… bash tests/gate.sh quick --server-cores 32-39 --load-cores 40-47 --ports 45800-45819` | Result |
|---|---|
| `GATE_ONLY_JOBS=redis_tcl`, this branch's release build (`build/tomokv` ef368a64…, made by the job's release row) | **ok** both rows: `Redis 7.4.10 Tcl passing subset (2s)` 228.85 s, `(1s)` 233.74 s; 35/35 files, 1611/1611 required passes per mode |
| `GATE_ONLY_JOBS=redis_tcl --candidate-binary` planted regression (GEODIST/GEOSEARCH `km` uses the mile factor; `.text`/`.rodata` change only) | **FAIL** both rows (223.07 s / 227.23 s): exactly `unit/geo` fails (16 of 64 assertions), the other 34 files pass |
| `GATE_ONLY_JOBS=compat2`, this branch's build (pulls `redis_tcl` as prerequisite) | **ok** all rows: both Tcl rows (227.98 / 231.58 s), `compat2 autharity` 1.77 s, `compat2 expire_notify` 6.75 s, `compat2 ktls_lifetime` 2.09 s |
| `GATE_ONLY_JOBS=compat2 --candidate-binary` planted | Tcl rows **FAIL**; **`compat2 autharity` FAIL** — detail "Redis 7.4.10 Tcl passing subset did not pass; see …/jobs/redis_tcl and …"; its own legs pass; `compat2 expire_notify` and `compat2 ktls_lifetime` **ok** |

**What it covers, exactly.** [tests/redis_tcl_passing.json](tests/redis_tcl_passing.json) (schema 2) lists, per upstream
file, the sha256 of the file, the exact multiset of the **1611 required passing assertions** (identical in both modes),
the **424 named known failures** it skips (each with the reason it was added: failed or hung on TomoKV in the survey,
a reach pass or a builder round), the exact `(command, reply)` of the 4 block-setup errors `--durable` reports without
a test name, and the only extra argument (`--tags -needs:debug`, `unit/type/stream`). It also binds the support files
(`test_helper.tcl`, `support/*.tcl`, `runtest`, `version.h`). A row passes only if every file completes, its passing
multiset is exactly the manifest's, the named setup errors occur exactly as listed and nothing else fails or hangs;
a changed upstream byte, a skip replacing a pass, a renamed or duplicate assertion, a hang, or a regression in any covered assertion fails it.
Codex's first version gated the 7 files without any failure (115 assertions); widening it to every passing assertion
is this continuation's change (`docs/harness5/build_tcl_manifest.py`: 2s and 1s concurrently at ratio 6:2 until two
consecutive clean rounds agreed; the builder named one flaky test, `WATCH-SPURIOUS-INVALIDATION` above).

**Rows and counts: DQ = 0, DF = 0.** The two rows are private (not collected); their verdict reaches the gate only
through the existing public row `compat2 autharity`, which fails when the job's completion marker is missing and now
prints the job's own rows and names its directory in the FAIL detail. No `EXPECT_*` constant or label fixture changes.

**Cost.** 229 + 234 s of one slot, sequential, in both quick and full tiers; `compat2` starts only after it (it was
86 s with the 7-file subset). The four slowest files are `unit/type/stream` 52 s (two 10,000-command same-key
transactions, see the O(N²) note), `unit/hyperloglog` 49 s (slow on Redis too), `unit/geo` 32 s and `unit/scripting`
21 s. If slot time matters more than coverage, splitting the job by mode into two slots halves its latency.


### 5. ABBA self-test row runtime (`abba_selftest`, "ABBA comparison + saturation negative controls")

| Geometry | Tree | Row seconds, each run | Median |
|---|---|---|---:|
| landing-like: the slot's 8 server (32–39) + 2 load (46–47) CPUs, the 6 neighbour cores 40–45 busy (owned burners; wave7b's method) | before, 3700b51d7 | 431.70 †, 430.98 †, 430.80 | 430.98 |
| same | after, this branch (e72dcd8bc) | 403.34, 402.79 | **403.06** (27.9 s / 6.5 % faster) |
| isolated: 8 server (32–39) + 8 load (40–47), idle | before (codex's run, `docs/harness5/before`) | 371.46 | 371.46 |
| same | after (also the green gate run of this branch) | 333.44 | **333.44** (38.0 s / 10.2 % faster) |
| reference: the wave-7 landing (`cx-final/build/gate-ledger-iteration.txt`) | 3700b51d7 | 442.80 | — |

† FAIL: 3–4 real-socket controls (`test_real_socket_owner_reports_pid_cmdline_and_refuses_boot`, two `PersistfixWiring`
tests, once gate_quiet's `test_idle_listener_blocks_only_intended_port`) got EADDRINUSE on `GATE_TEST_PORT` 45800. A
0.5 s port watch during the third run shows 45800 in TIME-WAIT toward 127.0.0.1:46812: another lane's client used it
as an ephemeral source port. The row still ran every suite; the third run passed. The after runs passed 3/3.

| Suite (landing-like medians) | Before | After | Change (loss classification) |
|---|---:|---:|---|
| `abbagate.py --self-test` | 115.67 | 72.59 | 43.1 s faster: Git/fingerprint reads computed once per class |
| `gate_receipt.py --self-test` (+ `_nullrefresh_test`, `nullpublish4_test`, `gate_ledger_fixture`) | 132.12 | 146.48 | 14.4 s slower — MECHANISM: every receipt `finish()` now replays the epoll report and null (CG4.8), plus the 3 new controls |
| `gates_test.py` | 154.77 | 154.73 | unchanged (85 s isolated: its scheduler fixtures get 10 CPUs here, 16 isolated) |
| `gate_history.py self-test` | 20.65 | 20.65 | unchanged |
| `gate_measurements.py --self-test` | 2.74 | 3.39 | 0.65 s slower — MECHANISM: the new CG4.6 axis control |
| the other 11 suites | 4.00 | 4.18 | gateprod 1.90 → 2.04 (the new product-record control), abba_instrument 1.25 → 1.24, the other 9 at most 0.5 s each (new: `redis_tcl_test.py` 0.02 s) |

An earlier attempt burned the slot's own server cores; the scheduler fixtures, which run on the slot's `GATE_CORES`,
starved and hit their inner timeout (exit 124, the wave-7 re-land signature). It was discarded as unrealistic
(`docs/harness5/abba-timing/invalid-own-slot-burned`). Evidence: [docs/harness5/abba-timing](docs/harness5/abba-timing/)
(per-run ledgers, gate logs, per-test observer timings, tree heads/status, burner and port-watch logs, scripts).

**Where the time goes.** The row is 15 serverless suites in the base (16 on this branch: `redis_tcl_test.py`), run
back to back on the slot's load CPUs (2 in the landing slot geometry). In the landing-like geometry the base spends 154.8 s in gates_test, 132.1 s in the gate_receipt chain, 115.7 s in abbagate and 20.7 s in gate_history; the other 11 suites take 6.7 s together. History: ~340 s in the September gate
ledgers (7 suites); the base runs 15, including the gate_receipt chain (`_nullrefresh_test`,
`nullpublish4_test`, `gate_ledger_fixture`: 63 tests, ~133 s isolated), abbagate 87 → 107 tests and gates_test
52 → 72 tests (counts at 7b959e7f6, 2026-09-14, vs 3700b51d7). The 851 s / 1128.59 s / TIMEOUT landings were
contention pathologies that wave7b already removed in this base (harness_fingerprint hashing 82k paths to keep 588;
~220 SchedulerWiring shell workers on 2 CPUs); the wave-7 landing then measured the row at **442.80 s**. No suite
waits for a quiet box: `quiet_wait` runs before `row_begin` starts the row clock, and the serverless suites start no
measurement loop (their "real loops" are fake-runner orchestration fixtures).

**Change (codex, verified here).** Repeated Git metadata reads in the abbagate ABBA fixtures: every orchestration
test recomputed `harness_fingerprint(ROOT)` (`git ls-files --cached --others` over 82,872 paths + hashing 592
harness files, 0.20 s), `instrument_fingerprint(ROOT)` (0.38 s) and `git rev-parse HEAD` / `git status --short`, twice
per fake campaign. They are now computed once per class and patched in `setUp`; production `main()` still computes
both fingerprints before **and** after every campaign. Safe because: (1) the dedicated controls nest their own
patches over the class patch and still drive the detection path (`test_changed_harness_invalidates_the_real_measurement_loop`,
`test_changed_instrument_invalidates_the_real_measurement_loop`, side_effect sequences), (2) `workspace_commit` /
`workspace_status` are recorded in reports but asserted by no test, (3) every test name that ran before still runs and passes (431 tests before, 441 after, 0 failures; the 10 new
names are this lane's controls). Receipt-suite git calls are left alone: they build real temporary
repositories for hooks/commits (16 calls, 0.015 s in the slowest receipt test); its time is deliberate full replay
(56 promotions, 22 s of campaign validation per mutation test). A second fixture change drops JSON indentation in
three serverless fixture classes (`compact_json_fixture`); every byte comparison in those tests compares two values
written under the same patch, and no test mutates indented JSON text.

**Budget.** `tests/gate.sh` row budget 1620 → **660 s**: the same rule (measured landing runtime +40%, rounded up to a
minute) applied to the newest landing measurement, 442.80 s × 1.4 = 619.92 s → 660 s (`gates_test.py` asserts the
value and basis label). The emulated base (430.98 s) is within 3 % of the real wave-7 landing; the branch's 403 s is 61 % of the new budget. The next landing ledger is the real value to re-derive from.


### 6. Verification runs

| Check | Result |
|---|---|
| `python3 tests/gates_test.py` (final tree) | **72 tests OK** (85.3 s, CPUs 32–47) |
| `GATE_ONLY_JOBS=abba_selftest` (final tree; also the isolated after-timing run) | **ok**: 333.44 s isolated; 403.34 s and 402.79 s landing-like |
| `GATE_ONLY_JOBS=redis_tcl` / `compat2`, good and planted binaries | see §4 (4 runs, all as expected) |
| `make all`; the 42 `job_production_units` targets; `mdbqsbr-live-arms`; `build/blockfix-cost` (`-j12`, CPUs 32–43, niced) | all built (exit 0); `make -q` fresh for every target afterwards |
| `calib/binary-neutral.sh bench-bins/tomokv-headline-3700b51d7 build/tomokv` | **IDENTICAL** (9,474,960 bytes after stripping); `build/tomokv` sha256 ef368a64… |
| Branch diff in `src/` and `Makefile` | 0 lines |

Touched gate jobs and how each was run: `abba_selftest` (self-test suites, CG4.6–4.8 controls, gates_test budget and
wiring) — through the job interface, red and green; `redis_tcl` (new) and `compat2` (marker fold, FAIL detail) —
through the job interface with this branch's and the planted binary. `tests/gate.sh`'s receipt `finish` call gained
`--product-result`; it runs only in a full/push gate with a receipt and is exercised here by the receipt self-tests.

**NOT RUN** (with reason): the full `tests/gate.sh` iteration and a push/receipt gate (maintainer-only per the lane
rules), so a real two-pass product receipt and the full-iteration collection order of `compat2` after `redis_tcl` are
covered only by serverless controls and the partial job runs; any performance benchmark, measurement load generator
or ABBA campaign, and the live CG4.6/CG4.7 follow-ups R6/R7 (calibrate, freeze and promote an epoll null; a smoke
comparison against a genuinely fresh promoted null). The landing-time runtime of the new self-test row is measured
only under the emulated landing geometry (§5); the next landing ledger is the real value for the next budget.

**Environment note.** The lane's ports 45800–45899 lie inside the kernel's ephemeral range (32768–60999): another
lane's connections to 127.0.0.1:46860 left TIME-WAIT sockets on local ports 45880–45884, and both TomoKV and Redis
then failed to bind there ("Address already in use"); 45850 was briefly unbindable too (cause not identified, free a
minute later). Those probes were moved to free ports; no gate verdict above was affected.


### 7. Commits (branch `cx-harness5`, no push)

- `a2bf829f2` docs: qualify historical writeback and portability claims
- `2ce654576` harness: validate optional axes and retain both product passes
- `b29331e59` harness: gate the verified Redis Tcl subset in both modes
- `a21813aa9` harness5: WIP at the codex content-filter stop (Tcl survey evidence, classifier, protocol repros, gates_test additions; partial)
- `e948147a3` harness: Tcl driver names known failures; reach and repro tools
- `3e502e96f` harness: compat2 autharity shows the Tcl subset's own rows on failure
- `23e6e55dd` harness: ABBA self-test row budget 1620 -> 660 s from the wave-7 landing
- `8a1df3b9f` harness: product record survives an interrupted coordinator (CG4.8)
- `d8805b29a` harness: gate the whole passing Redis Tcl subset (35 files, 1611 assertions/mode)
- `46c53da09` harness: Tcl manifest names required passes as the observer reports them
- `56395a8d9` docs(harness5): reviewed Redis Tcl triage, minimal repros, reach evidence
- `027859718` docs(harness5): Tcl-subset gate job verification through the job interface
- `e72dcd8bc` docs(harness5): CG4.6-CG4.8 red runs through the abba_selftest job interface
- `4b3155b28` docs(harness5): ABBA self-test row timings before/after (landing-like and isolated)
- this report: `MEASURE-REQUEST-harness5.md` (final commit; worktree clean afterwards)
