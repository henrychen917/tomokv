## wave2 integration

Worktree `/home/user/Projects/cx-wave2`, branch `cx-wave2`, created from origin/cpp **991d48f65**
(`git -C /home/user/Projects/cx-final worktree add -b cx-wave2 /home/user/Projects/cx-wave2 991d48f65`).
It lands the five finished wave-2 lanes with `--no-ff` merge commits in the requested order. Every
lane commit is kept: the five lane tips are ancestors of HEAD. The five lane worktrees were only
read. Nothing was pushed, no stash entry was used, and no benchmark or performance measurement was
run.

All builds, servers, oracles and load generators ran on CPUs 80-95: servers 80-87, the Redis
7.4.10 oracle 88, load 89-95. Ports were 22800-22899. `tests/gate.sh` requires 16 physical cores,
so gate runs used `--server-cores 80-88 --load-cores 89-95`. Its slot takes servers 80-87, so 88
stays idle there.

**Result**

| Check, integrated default build `build/tomokv` (SHA-256 `f7e597bf...91f5fa`) | Result |
|---|---|
| Rows declared by the source / label fixture | **DQ=+12 DF=+12: 637 quick / 654 full** over origin's 625/642; fixture holds 654 labels, none missing or extra. EXPECT stays 625/642 |
| `make -j16 all`; 29 `job_production_units` targets + `mdbqsbr-live-arms` | exit 0, no warnings in `all`; **29/29 `make -q` fresh**, live arms exit 0, `make -q all` fresh |
| `python3 tests/gates_test.py` | **66/66 OK** plus the nested 14/14, twice: after the budget commit (82 s) and on the final tree (82 s) |
| The 12 new lane rows, run by `tests/gate.sh` itself | **12/12 ok** |
| The other rows of those 14 gate jobs | 76 ok, including rows 310/324 (`xmove battery`); **1 FAIL: `R7 FIFO twin off-path identity`**. This is perfex x the R7 inventory, below; it needs a maintainer decision |
| Lottery unit tests; witness build | **34/34 OK**; all 60 witness anchors apply to the integrated source; `build/lottery/tomokv` and its ASAN twin build with no warnings |
| INFO rows exactly as the gate runs them, 20 runs | **0 failures in 40**: `infofix battery (atomic 0)` 20/20 and `(atomic 1)` 20/20, each `INFOFIX: PASS (41 checks)` right after `expwide`. All 20 runs: 69 ok, 0 FAIL |
| Direct `expwide` -> `infofix` stress, 20 pairs per atomic setting | **0 failures in 40 pairs**: 40/40 `INFOFIX: PASS (41 checks)` and 40/40 `expwide: 101 checks, 0 failures`; both servers shut down clean |
| dbdefault row audit after all merges | 637 / 654, DQ +12 / DF +12, fixture labels match, in-memory check at 654 passes |
| Redis 7.4.10 differential, 47 suites, seeds 7 19 20 23, atomic 0/1 | split **376/376 legs**; armed fused **368/368 legs + 2/2 read-local witnesses fired** (hits 983 at atomic 0 and 1); **0 differences**. The 8 armed `sort` legs are the harness's by-design SKIP (split-only suite) |
| Selected hot bodies vs 991d48f65 | **Identical except perfex's 18 executor bodies, each byte- and target-identical to perfex's own build** (old selector 1190/1208 ccfix, 1190/1204 lbstall; new selector 1196/1214, 1196/1210) |
| All bodies vs 991d48f65 | 16,283 / 16,455 equal; **172 changed, every one attributed to a lane** (155 lane-identical, 14 multi-lane composites, 2 rlresize bodies with rlresize's call targets, 1 register-allocation copy the linker discards) |

### Merges

| # | Lane (tip) | Merge commit | Rows | Textual conflicts and resolution |
|---|---|---|---|---|
| 1 | `cx-perfio` (`96bcf62cf`, 17 commits incl. the 7 `cx-pfconfirm` commits) | `aa37854fe` | +4/+4 | none |
| 2 | `cx-perfex` (`2b15e0328`, perfex + perfex2) | `2f81a7105` | +4/+4 | `tests/gate.sh` EXPECT arithmetic comment and the label fixture `purpose` string: both lanes' text kept. `docs/pfconfirm` merged clean: perfio's cherry-pick `c8fc2d147` is byte-identical to perfex's `d867a1073` |
| 3 | `cx-lottery` (`456be6c49`) | `7316a97f2` | +0/+0 | none (opt-in Makefile targets only) |
| 4 | `cx-rlresize` (`f2a8a3d46`) | `2dadd8058` | +3/+3 | Makefile budgets of db0 `t_server.o`, db0 `xshard.o`, src `rl2s.o`, db0 `genthread.o` (moved by perfio/perfex2 and by rlresize): provisional additive values, all lane comments kept, re-derived in `5219dae1c`. EXPECT comment and fixture `purpose`: all kept |
| 5 | `cx-dbdefault` (`18c847f07`), last | `b1d996d8f` | +1/+1 | `JOB_NAMES` (`perfex_units perfex_live` and `dbdefault` both kept); EXPECT comment now states the wave-2 total; fixture `purpose`: all kept |

`src/store/flatstore.h` (perfex2 and rlresize) merged without a conflict. perfex2's `#line` directives
restore 991d48f65's numbering after its inserted lines. rlresize's own +8/+11 shift below line 2483
is unchanged, so every compiled `__LINE__` equals the one in the build of the lane that edited that region.

Follow-up commits, each separate:

| Commit | Kind | Content |
|---|---|---|
| `c55f25cab` | fix (a), test only | perfio stream row: median < 3 ms AND max < 12 ms over the 100k-entry samples |
| `0d859e218` | merge semantics, test only | `tests/perfio.py` passes `--databases 1` to its own TomoKV boots (dbdefault policy; below) |
| `9f4cb3c90` | tooling fix | `ExLoopT<true>::prepare_local_read` selected as hot in both selectors |
| `5219dae1c` | build | inlining budgets re-derived for the integrated source |
| `e35cdbfad` | fix (b), test only | gate row 310: `tests/xmove.py` accepts every legal serial order and picks cross-owner keys |

### Semantic conflicts found after the textual merge

1. **dbdefault x perfio (resolved, `0d859e218`).** dbdefault makes 16 databases the flagless default.
   It pins every existing correctness boot to its prior DB0 image: `launch`/`boot*` and
   `_gate_process.server()` insert `--databases 1`, and direct drivers pass it explicitly.
   `tests/perfio.py` arrived with its own `boot()` and no database option, so its four gate rows would
   have switched to the multi-DB image. It now passes `--databases 1` to TomoKV only; the Redis oracle
   boot is unchanged. This is the change dbdefault made in `aclfix.py` and `clientfix.py`; no assertion
   changes. Every other new driver already pins DB0 or boots nothing:
   [direct-boots.tsv](docs/wave2/dbdefault-audit/direct-boots.tsv).
2. **perfex x R7 FIFO twin inventory (NOT resolved, maintainer decision).** The row `R7 FIFO twin
   off-path identity + negative controls` fails: `off-path inventory changed: tomo 146, tomo_db0 146,
   expected 147`.
   - Cause: perfex's drain without zero-fill lets GCC inline `ExLoopT<false>::exec_batch<false, 32ul>`
     into the split `drain_tasks` in both runtimes. The attribution shows exactly that one removed body
     per runtime (`src/main.o`, `db0/src/main.o`); perfex's own build has the same effect.
   - Fix: `28f6289eb`, the cx-wave1 commit recorded as a mainline-approved explicit delta (147 -> 146).
     The wave1b report assigned it to perfex. It applies cleanly to `cx-wave2`.
   - With it, a scratch copy of the row's own driver passes on this binary: `strict_noop=True: 292/292
     identical bodies`, and all three negative controls fail strict identity as required
     ([log](docs/wave2/rows/r7-delta-scratch.log)).
   - It is **not committed**. It changes an assertion, and this integration may change assertions
     only for fixes (a)/(b). Mainline: `git cherry-pick 28f6289eb`, or decide otherwise.

### Gate accounting

| Lane | Rows (all collected before the quick-tier exit) | DQ | DF |
|---|---|---:|---:|
| perfio | `perfio stale epoll registration (epoll-flip / epoll-lb)`, `perfio XREADGROUP bounded delivery + Redis metadata (1s / 2s)` | +4 | +4 |
| perfex / perfex2 | `perfex clock / batch binary regression`, `perfex TTL sampler beat (1s / 2s)` (perfex2's flush-freshness cases extend the sampler rows) | +4 | +4 |
| lottery | none (nightly tier outside the landing gate) | +0 | +0 |
| rlresize | `storage flush-prepared-capacity regression`, `armed resize retirement: atomic-growth / flush-prepared` | +3 | +3 |
| dbdefault | `Redis default databases 16 (both modes)` | +1 | +1 |
| **Total** | | **+12** | **+12** |

- **DQ = +12, DF = +12: 625 -> 637 quick, 642 -> 654 full.** EXPECT_QUICK/EXPECT_FULL stay
  625/642. The arithmetic comment above them states the per-lane values and the total.
- Counted with the checker's own `source_labels` on the source and on 991d48f65 (625/642). The source
  adds exactly these 12 labels and removes none.
- `tests/fixtures/nullrefresh-ledger-labels.json` holds 654 labels, the same multiset: no missing, no
  extra. The unmodified `python3 tests/gate_ledger_fixture.py` refuses only the count
  (`EXPECT_FULL=642, fixture=654, source declarations=654`); the checker accepts the fixture at 654 in
  memory. [ledger-check.json](docs/wave2/ledger/ledger-check.json),
  [checker log](docs/wave2/ledger/gate_ledger_fixture.log).
- dbdefault's `docs/dbdefault/row_audit.py`, re-run after all merges, agrees: 637/654, DQ +12/DF +12,
  `fixture_labels_match`, `proposed_count_check_passes_in_memory`. The regenerated
  `docs/dbdefault/gate-rows.tsv` (654 rows) and `gate-counts.json` are committed;
  [stdout](docs/wave2/dbdefault-audit/row_audit.stdout.json). The audit gives `perfex_units` its
  generic "explicit 1 via launch" label; those two rows boot nothing (binary analysis).

### Inlining budgets re-derived (`5219dae1c`)

**Method.** This is the docs/ttlclean identity method, applied as wave1b applied it, with adapted
tools in [docs/wave2/tools](docs/wave2/tools/) (`trial.py`, `attribute.py`, `run_trials.sh`,
`scan1-3.sh`, `rank.py`).

1. **Reference builds** from `git archive` under `build/wave2`
   ([hashes](docs/wave2/identity/reference-builds.txt)):
   - 991d48f65, the PRE and every lane's base. Its loadable sections equal
     `bench-bins/tomokv-headline-991d48f65`'s ([receipt](docs/wave2/identity/pre-vs-headline-991d48f65.json)).
   - Each lane tip with its own Makefile: perfio, perfex, rlresize, dbdefault. cx-lottery changes no
     production source or compile line, so it needs none.
2. **Unit sizes.** The GCC IPA starting unit was measured for PRE, the integrated source and each
   lane ([unit-sizes.jsonl](docs/wave2/identity/unit-sizes.jsonl)).
3. **Scans.** 226 compile-only trials in three rounds
   ([one line per value](docs/wave2/identity/budget-trials/SUMMARY.txt)).
4. **Classification.** Every emitted body was classified against PRE and each lane's own object:
   A lane-identical, B multi-lane composite, C unattributed, D single lane but different from that
   lane's body.
5. **Choice.** No selected hot body may differ from 991d48f65 except perfex's executor bodies
   (`drain_tasks*`, `ExLoopT::run`), and those must equal perfex's own. Then the fewest C and D
   bodies, the fewest changed bodies, and the value nearest the headroom-preserving centre
   (991d48f65 budget + unit growth).

| Object (src / db0) | 991d48f65 | Lane values | Merge (provisional) | IPA unit growth | **Chosen** | Why |
|---|---|---|---|---|---|---|
| t_server.o | 31330 / 31725 | rlresize 31379 / 31766; perfex2 db0 31737 | 31379 / 31778 | +37 / +51 | **31379 / 31776** | Its one selected hot body is identical at every value; chosen for no C/D body. db0: perfex2's 31737 and rlresize's 31766 leave 7 and 3 unattributed bodies in the merged unit; 31776 is the centre (one object with 31778) |
| aof.o | 34400 / 34800 | rlresize 34437 / 34813 | 34437 / 34813 | +37 / +44 | **34437 / 34840** | db0: `FlatStore::make_room_for` differs from 991d48f65 at every scanned value (34700-35100, C). At 34805-34950 it differs only in register allocation, with the same size and call targets. 34840 is nearest the centre among the fewest-change values. The linker discards this object's copy |
| xshard.o | 127880 / 126482 | rlresize 127924 / 126542; perfex2 db0 126492 | 127924 / 126552 | +44 / +51 | **127924 / 126566** | db0 is chaotic (40 values scanned). 126566 is the only value with 3 changed bodies: rlresize's own cold `prepare_commands` drift returns to 991d48f65. The provisional 126552 left an unattributed `atomic_collapse_read_local` |
| genthread.o | 129420 / 129640 | rlresize 129453 / 129655; perfio db0 129652 | 129453 / 129667 | -2 / +43 | **129447 / 129704** | db0: every value below 129698, including the lane and provisional values, reproduces perfex's own dispatch drift (`parse_and_dispatch<true,0u,false>`). 129698-129706 is hot-clean; only 129704-129706 also has no unattributed body. src: 2 D bodies at every value; at 129447-129448 both have rlresize's exact call targets |
| rl2s.o | 162300 / 162334 | perfio src 162312; rlresize src 162311 | 162323 / 162334 | -3 / +42 | **162305 / 162334** | src: every lane and provisional value left 1-2 dispatch bodies changed. 162305-162306 is the only clean plateau. db0 emits one object at every value |
| reorder.o (db0; src has no override) | 148258 | rlresize 148269 | 148269 | +43 | **148358** | Below 148339, and at the lane and provisional values, perfex's own `WbEngine::serve_impl` lambda drift stays (`append_fill` out of line). Hot-clean at 148339-148341, 148350, 148357-148365 and 148370. 148357-148361 has the fewest changed bodies (14) |
| main.o | 147428 / 147449 | unchanged | unchanged | +6 / +51 | **kept** | One object at every scanned value (cmpobj: 0 differing) |

Each final object equals its chosen trial object: 0 differing bodies in all 13
([receipt](docs/wave2/identity/final-vs-trials.json)). The provisional merge values had 20 changed
lbstall hot bodies against 991d48f65. Six were not perfex's executor changes: perfex's own dispatch
drift in db0 genthread and src rl2s, its serve-lambda drift in db0 reorder, a src rl2s dispatch body
(D), and an unattributed `FlatStore::erase` in db0 aof
([provisional](docs/wave2/identity/provisional-hot.log)). All six are back to 991d48f65's body.

### The three fixes

**(a) perfio stream timing row (`c55f25cab`, `tests/perfio.py` + one `tests/gate.sh` comment).**
The old check was `assert max(samples[100000, "xreadgroup"]) < 3_000_000`. Now the 33 paired
GET-after-XREADGROUP samples at 100k entries must have a **median below 3 ms AND a maximum below
12 ms**. Every failed bound is named in the assertion, and a `latency-bounds` event records both
statistics.

The PRE-fail receipt logic is unchanged. Metadata differences are still emitted before the latency
check, every raw sample is still emitted, and the latency bounds are asserted before the metadata
comparison. The `perfio_stream` job dependency comment names both bounds. Receipts:
[docs/wave2/perfio-stream](docs/wave2/perfio-stream/), driver
[perfio_stream_arms.sh](docs/wave2/tools/perfio_stream_arms.sh).

| Gate row arguments (uring, 6:2), 100k entries | median ms | max ms | Result |
|---|---:|---:|---|
| PRE 991d48f65 (`d4ddbcad...`), 1s | 11.639 | 17.616 | **FAIL, both bounds named**; metadata differs from Redis at the 160 checkpoints, logged first |
| PRE 991d48f65, 2s | 11.769 | 17.360 | **FAIL, both bounds named** |
| Integrated, 1s | 0.033 | 0.051 | PASS; 160 checkpoints, 0 differences |
| Integrated, 2s | 0.029 | 0.044 | PASS |
| Integrated, the gate's own rows (`perfio_stream` job) | 0.034 / 0.031 | 0.048 / 0.045 | PASS (1s / 2s) |

**(b) Gate row 310 (`e35cdbfad`, `tests/xmove.py`).**

- **Row.** Public ordinal 310 is `xmove battery (atomic 0)`, job `debug-0`, `tests/xmove.py 127.0.0.1
  PORT --release-build`. The lottery failure is in `concurrent_push_cell`'s same-edge cell: the LPUSH,
  sent 0.5 ms after the LMOVE on another connection, ran before LMOVE's first hop. The reply
  `new-edge` is correct for that order.
- **Legal orders.** Commands on different connections have no serial order until a reply has been
  read. Each of the three concurrent cells (detector negative control, forced inter-hop window,
  same-edge window) now reads the order the server chose from its replies: push before hop one,
  between the hops, or after hop two. It checks the replies and **both** lists against exactly that
  order; a mismatch still fails at once. The destination list is newly checked.
- **Witness.** A cell passes only when an attempt witnesses its interleaving with every original
  check: pushed length, readiness probe, move reply, hold reply and source list. Other legal orders are
  retried from a fresh setup, at most 20 attempts. A cell that never witnesses its interleaving fails.
- **Owner geometry.** `find_geometry` now requires source and destination on different **owners**
  (`DEBUG SHARDS` returns `[shard, owner]`), not merely on different shards. The cells hold the
  destination owner with an LREM scan. Shard placement follows the boot-randomized hash, so a few
  percent of split boots pick two shards of one owner (e.g. shards 0 and 4, or 1 and 3). The push then queues behind
  the hold and no window can open. The old battery failed every such boot with `destination hold did
  not open the inter-hop window`.
- Test file only; no check the battery makes about the server was removed.

Receipts: [docs/wave2/xmove](docs/wave2/xmove/), driver [xmove_orders.py](docs/wave2/tools/xmove_orders.py).
Every run boots the integrated binary fresh in the gate's `debug-AT` shape (6:2, 16 shards,
`--key-lb 0 --client-lb 0 --flip-auto 0`) and runs the gate's invocation. "Old" is the
991d48f65 `tests/xmove.py`. "Contended" adds one busy loop per server CPU (80-87), the way the
shared CPUs of the lottery calibration preempted the server; it runs without the release-only timing
cell.

| xmove battery, atomic 0 unless noted | Old battery | Fixed battery |
|---|---|---|
| Uncontended, 30 fresh boots | 28/30 pass; 2x `window not opened`, both on same-owner boots (shards 0/4, 3/15) | **30/30**, no retry needed; every boot cross-owner |
| Contended, 100 fresh boots | 86/100 pass; **9x `got new-edge, wanted moved`** (the lottery failure, all on cross-owner boots); 5x `window not opened`, all on same-owner boots | **100/100**; 46 legal-order attempts verified and retried (43 push before hop one, 3 push after hop two) |
| atomic 1, 10 fresh boots | 10/10 (concurrent cells skip by design) | 10/10 |
| Serial-order table: each order produced deterministically, replies + lists vs what the battery accepts | | **6/6 match** at atomic 0 and at atomic 1 |

In the gate's own `debug-0` job, `xmove` runs after batteries that leave the live `atomic` setting at
1 (testmap TM4.1: batteries mutate the shared setting). This run's row 310 therefore printed
`PASS xmove atomic=1` and skipped the concurrent cells. The lottery runner boots row 310 fresh, so
`atomic=0` holds there and these cells run, as in the receipts above.

**(c) Hot-body selectors (`9f4cb3c90`).** `tools/lbstall_artifacts.py` `HOT` now names
`ExLoopT<true>::prepare_local_read`, the read-local GET hit resolver (round-4 rlfix). The hot
inventory in `tools/ccfix_audit.py` names it beside the `ExLoopT` run bodies; it also inherits `HOT`.
One instantiation exists per fused object: genthread.o, rl2s.o and reorder.o, in both namespaces.

| Selected hot bodies | Before the fix | After |
|---|---:|---:|
| `lbstall_artifacts.py compare` | 1204 | **1210** (+6) |
| `ccfix_audit.py` hot inventory | 1208 | **1214** (+6) |
| The 6 `prepare_local_read` bodies, integrated vs 991d48f65 | not selected | **6/6 identical** |

Lane-era audits that reuse `HOT` (`respcompat_audit`, `cd13b_audit`, `aclkeys3/4_audit`,
`ccfix4_budget`, `infofields_artifacts`) widen the same way. None is a gate row.

### Verification (CPUs 80-95)

| Check | Result | Receipt |
|---|---|---|
| `make -j16 all`, final budgets | exit 0, no warnings, 70 s; `make -q all` fresh | [log](docs/wave2/builds/final-build.log.gz) |
| `job_production_units`: 29 targets taken from the current function, then `mdbqsbr-live-arms` | `make -k -j16` exit 0 (194 s); **29/29 `make -q` fresh**; live arms exit 0 (139 s); `make -q all` 0. Only the known `-Wmismatched-new-delete` warnings in `tests/lbplanner_unit.cc` and `tests/atomic_survivors_unit.cc` | [status](docs/wave2/builds/production-units.status) |
| `python3 tests/gates_test.py` | **66/66 OK** + nested 14/14 (82.1 s), then again on the final tree after fix (b): **66/66 OK** + 14/14 (81.9 s). No deadline failure in either run | [first](docs/wave2/gates-test/gates-test.log), [final](docs/wave2/gates-test/gates-test-final.log) |
| Ledger: source labels / fixture / totals | 637 / 654 declared = 654 fixture labels; DQ +12, DF +12; no missing or extra label | [ledger-check.json](docs/wave2/ledger/ledger-check.json) |
| The 12 new rows, `tests/gate.sh` itself (14 jobs: `perfex_units perfex_live perfio_stream flip storage_units atomic_units dbdefault debug-0 debug-1 reorder_sync reorder_engagement reorder_identity netio-1s netio-2s`) | **12/12 ok**: perfio x4, perfex x4 (TTL sampler rows run all four flush forms in both modes: armed avg_ttl 3599989 -> 0 immediately -> 59988 fresh), rlresize x3, dbdefault x1. The run: 88 ok, 1 FAIL (R7 FIFO twin, above) | [ledger](docs/wave2/rows/partial-gate.ledger), [row logs](docs/wave2/rows/logs/) |
| Lottery unit tests (`cd tests && python3 -m unittest -v lottery_runner_test lottery_evidence_test`) | **34/34 OK**. `tools/lottery_build.py` applies all 60 reviewed anchors to the integrated source, and `make -j16 build/lottery/tomokv build/lottery/tomokv-asan` (the nightly tier's witness build and its ASAN twin) exits 0 with no warnings | [units](docs/wave2/lottery/unit-tests.log), [witness build](docs/wave2/lottery/witness-build.log.gz) |
| INFO rows exactly as the gate runs them: whole `feature-split-0` + `feature-split-1` jobs (expwide immediately before infofix), 20 runs | **20/20 runs exit 0**; infofix atomic 0: 20/20 ok, atomic 1: 20/20 ok, no `measured avg_ttl` failure; every run 69 ok / 0 FAIL (241-268 s per run) | [docs/wave2/infofix](docs/wave2/infofix/) ([summary](docs/wave2/infofix/summary.json), [driver](docs/wave2/tools/infofix20.sh)) |
| Direct `expwide` -> `infofix` stress, one boot per atomic setting, 20 pairs each | **20/20 pairs at atomic 0 and 20/20 at atomic 1**: no battery failure, no `avg_ttl` failure; each boot (split 6:2, 16 shards, gate shape with `--databases 1`) alive to the end and shut down clean (rc 0, shutdown report clean) | [docs/wave2/infofix-direct](docs/wave2/infofix-direct/) ([driver](docs/wave2/tools/infofix_direct.py)) |
| dbdefault `row_audit.py`, after all merges | 637/654, +12/+12, fixture match; the new drivers' boots reviewed | [stdout](docs/wave2/dbdefault-audit/row_audit.stdout.json), [direct boots](docs/wave2/dbdefault-audit/direct-boots.tsv) |
| Redis 7.4.10 differential, `tests/differ_gate.sh` focused proof, all 47 suites, seeds 7 19 20 23, atomic 0 and 1 | Split 6:2: `pass=376 fail=0` (14 min). Armed fused (`--read-local 1`): `pass=370 fail=0` = 368 legs + both `read-local lane fired` witnesses (atomic 0 and 1: hits=983, fallbacks=276 at peak); the 8 `sort` legs SKIP by design. 232 of 245 registered commands diffed, 1.70M / 1.67M comparison witnesses. Target 80-87, oracle 88 (`/home/user/Projects/redis`, `ac08d444...`), load 89-95 | [split](docs/wave2/differ/split.log), [armed fused](docs/wave2/differ/armed-fused.log), [driver](docs/wave2/tools/differ.sh) |

### Hot-body identity: integrated default build vs the 991d48f65 default build

These are the stock docs/ttlclean tools, run twice: with the selector as it was at 991d48f65 (tools
copied from that commit) and with this branch's selector
([identity.sh](docs/wave2/tools/identity.sh), [receipts](docs/wave2/identity/)). Every tool exits 1,
as it must: perfex's executor bodies are intended changes.

| Tool | Selector at 991d48f65 | Selector after fix (c) |
|---|---|---|
| `tools/lbstall_artifacts.py compare` | 1204 hot: **1190 equal** with resolved relocation targets (1174 raw); 14 DIFF | 1210 hot: **1196 equal** (1180 raw); the same 14 DIFF |
| `tools/ccfix_audit.py` | 16,455 bodies: 16,283 equal, 172 changed. Hot (incl. executor `run`) 1208: **1190 equal, 18 changed**. Handlers 1186/1211 | Hot 1214: **1196 equal, 18 changed**; everything else identical |
| `docs/deadswitch/linked_bytes.py` | `.text` 7,646,972 -> 7,647,932 bytes (+960); `.rodata`, `.data` and `.bss` the same size; loadable sections differ | same |

**The 18 changed hot bodies are all perfex's, and each is byte- and target-identical to perfex's
own build:**

- `drain_tasks<32u, false>` and `drain_tasks_read_local_interleaved<false>` (EX4.13 byte storage,
  no batch zero-fill): 14 bodies in genthread, rl2s, reorder and main, both namespaces.
- `ExLoopT<false>::run` and `ExLoopT<true>::run` (EX4.12: CPU clock on the beat): 4 bodies.

No dispatch, writeback, IO, FlatStore or read-local (`prepare_local_read`, 6/6) body changes. The 25
changed handlers are perfio's stream-group handlers (12 per namespace, PFDATATY.1) and perfex2's
db0 `cmd_flush`.

**Every changed body, with its lane** ([changed-bodies.tsv](docs/wave2/identity/changed-bodies.tsv):
object, body, class, lane, sizes, call-target identity and reason;
[linked-attribution.json](docs/wave2/identity/linked-attribution.json): whether that object's copy
reaches the binary). Classification uses [attribute.py](docs/wave2/tools/attribute.py) against
991d48f65 and each lane tip's own default build.

| Lane(s) | Bodies | Class | What they are |
|---|---:|---|---|
| perfio | 57 | A, lane-identical | 47 in the stream-group TU (PFDATATY.1 delivery/lag and XINFO; the rest are TU code generation, as perfio lists them) and 10 `IoLoop::commit_client_transfer<true>` copies (IO4.19 epoll DEL) |
| perfex | 49 | A | 18 hot executor bodies above; `keyspace_sample_cycle` (new) x4, `owner_control_tail` x3, `ExLoopT` constructors x16 (cursor in padding), `publish_size` / `publish_keyspace_sample` x3, db0 `cmd_flush` (perfex2), `exec_batch<false, 32ul>` x2 removed (inlined into the drain), db0 `main` and `main.cold` |
| rlresize | 45 | A | `atomic_prepare_capacity_read_local` x9, `clear` / `clear_read_local` x9, the outlined `prepare_resize_retirement` `.isra` clones x8, `maybe_start_shrink` / `snapshot_control_pass` x7, and the 12 cold collateral bodies rlresize lists (AOF manifest, client migration, MULTI/SORT prep, LB scan, COMDAT helpers) |
| dbdefault | 4 | A | `Config::Config()` C1/C2 in both namespaces (default 1 -> 16) |
| perfex + rlresize | 8 | B, composite | db0 `FlatStore::clear` x3 (both lanes edit it), `~AofManager` x2, db0 `manifest_name`, db0 `command_client_migration_extract`, src genthread `pubsub_start_publish`: each lane changes the body in its own build |
| perfio + perfex (+ rlresize) | 6 | B | db0 `hash_key.isra`, db0 `budget_admit`, src rl2s `flip_control_pass<true>`; in the unbudgeted src reorder.o: `atomic_collapse`, `atomic_collapse_read_local`, `snapshot_prepare_write` |
| rlresize | 2 | D | src genthread `snapshot_control_pass<32u, false>` and `atomic_prepare_capacity_read_local`: rlresize's exact call targets, code generation of the merged unit. D at every scanned src genthread budget |
| none | 1 | C | db0 aof.o `FlatStore::make_room_for`: same size and call targets as 991d48f65, register allocation only. **The linker discards this copy** (COMDAT) |

Of the 172 changed object bodies, **104 reach the binary**: A 97, B 6, D 1, C 0. 58 are COMDAT copies
the linker discards, and 10 are removed. The maps come from re-running each build's own link with
`-Wl,-Map`. The relinked binaries equal the shipped ones in every loadable section.

**Layouts** (gdb, both namespaces): all eight locks unchanged: Op 336, Client 1984, ThreadCtx 1408,
Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. The only new member is perfex's
`ExLoopT::keyspace_shard_cursor_`, in existing padding (ExLoopT sizes unchanged).
[layouts.json](docs/wave2/identity/layouts.json).

### Binary

| Arm | Path | SHA-256 |
|---|---|---|
| Integrated: `src/` and `Makefile` as of `5219dae1c`, unchanged since (later commits touch only `tests/xmove.py` and docs) | `/home/user/Projects/cx-wave2/build/tomokv` | `f7e597bf67e7d768ccf1f3d226f998def8bbea794b72e4a29d9529ad1991f5fa` |
| PRE, 991d48f65 from `git archive` | `/home/user/Projects/cx-wave2/build/wave2/pre-src/build/tomokv` | `d4ddbcad16f7fa67fd47e47329fdf4a702c245c4d763f35bd61899de690f7a19` (runtime sections = `bench-bins/tomokv-headline-991d48f65`) |

### For the mainline

1. **EXPECT**: set **637 / 654** (DQ +12, DF +12). The fixture already holds all 654 labels.
2. **R7 FIFO twin inventory**: decide on `28f6289eb` (147 -> 146, perfex's inlined `exec_batch`).
   Without it, the full gate fails that row.
3. **Performance null required.** Selected hot bodies are identical to 991d48f65 except perfex's 18
   executor bodies, but `.text` grows by 960 bytes and moves code placement. PRE = 991d48f65,
   POST = this binary.
   - perfex: PFKEYSPA.1 smoke and full run, the 14-cell generic null, the four split cells (+ PAD B).
   - perfio: PFDATATY.1 smoke and full run and the main-command null.
   - rlresize: the standard null or PAD A/B.
   - dbdefault: ABBA cells must record `configured_databases=1`.
   - None of the lanes ran these.
4. **Row 310 in the gate itself** runs at `atomic=1` (TM4.1). The lottery tier is where the atomic-0
   concurrent cells actually run.
5. **Carried open items from the lanes.** None of these is a correctness regression; all stand as
   the lanes reported them.
   - perfio: no SMOKE_OK yet; the quiet screen refused. NT4.2 recommends a separate
     resumable-multibulk parser fix.
   - perfex/perfex2: no PFKEYSPA.1 SMOKE_OK yet; the quiet screen refused.
   - rlresize: `rehash_counter_` does not count atomic resizes (statistic only).
   - lottery: rows that cannot reach K=20 in 10 minutes are expwide 159/193/242/277 (W4), xmove 324
     (W6), TLS 443 (W12), and 126/503/515/516 (attempt length).
   - dbdefault: six `/home/user/Projects/*.sh` launchers outside the tree still boot without
     `--databases`.
