## wave1b integration

Worktree `/home/user/Projects/cx-wave1b`, branch `cx-wave1b`. This is a landing branch with the seven
wave-1 **correctness** lanes (scriptfix, savefix, aclfix, authfix, clientfix, racefix, flipfix) and
**without cx-perfex**. cx-wave1 failed its landing gate on `infofix battery (atomic 0)`
(`measured avg_ttl: got 3595598`), because perfex moved TTL sampling onto the millisecond beat.
perfex will be fixed and measured separately.

All builds, tests, servers and probes ran under `taskset -c 112-127`: servers on 112-119, the Redis
oracle on 120, drivers on 120-127. Ports were 25200-25299. No stash entry was created or applied,
nothing was pushed, and no benchmark or performance measurement was run.

**Result**

| Check on the final default binary (`build/tomokv`, SHA-256 `f47d319d...85c9b7d`) | Result |
|---|---|
| Rows declared by the source / label fixture | **625 quick / 642 full = +70/+70** over origin/cpp; fixture agrees (642 labels, none missing or extra, no perfex label) |
| `make -j16 all`; 29 `job_production_units` targets + `mdbqsbr-live-arms` | exit 0, 0 warnings; **29/29 + live arms built, all `make -q` fresh** |
| `python3 tests/gates_test.py` | **66/66 OK** (79 s) |
| The 70 new rows, run by `tests/gate.sh` itself | **70/70 ok** |
| `netcmd_units` job (full) | **16/16 ok** |
| R7 rows: envelope parity, FIFO twin off-path identity (+ engagement) | **3/3 ok**; the twin row keeps origin/cpp's 147 bodies per runtime (294/294) |
| Partial gate total (16 jobs + prerequisites) | **210 ok, 0 FAIL** |
| Differential smoke vs Redis 7.4.10 (4 suites x 4 seeds x atomic 0/1) | split **32/32**, armed-fused **32/32** + 2/2 read-local witnesses; **0 differences** |
| Hot bodies vs origin/cpp `1ba80bd4e` | 230 changed hot bodies (by name); **every one attributed** to a lane's intended change, an R7 regeneration of one, or the climon fix's cold drain |
| Hot bodies vs the bisection build b4 (`b959fc844`, lanes' own budgets) | 48 differ: climon fix 8, R7 regeneration 10, budget re-derivation 30. **16 of the 30 are b4 drift returned to origin/cpp's exact body** |
| **infofix battery, ten gate runs of both rows** | **0 failures in 20** (10/10 + 10/10); the direct expwide-then-infofix stress, which failed 3/10 on the perfex binaries, gives 0/10 |

### Base and cherry-picks

| # | Commit on cx-wave1b | From cx-wave1 | Content | Taken |
|---|---|---|---|---|
| base | `b959fc844` | - | cx-wave1 after the flipfix merge: merges 1-7, before perfex | yes |
| 1 | `5fe924572` | `d32c20a20` | R7 envelopes regenerated after savefix (`src/core/reorder.o` only) | yes |
| 2 | `2016a3056` | `546581bd4` | savefix BGSAVE cancellation rows use the 524288-key dataset | yes |
| 3 | `7c849c237` | `11473d968` | scriptfix lifecycle polls for the owned port to close | yes |
| 4 | `d39c7d64e` | `ec0317384` | climon fix: the suppressing drain retires plain ops only for tracking connections | **yes, except its Makefile hunk** |
| 5 | `09c31e2ce` | `8404007cd` | netcmd tracking-bound driver retires each registration | yes |
| 6 | `4ea309dbf` | - | per-object inlining budgets re-derived for this source | new |
| - | - | `d831e7f07` perfex merge; `28f6289eb` R7 inventory -1; `af6997d3c` EXPECT sync; `b8eed26c3` budgets for the perfex source; `62fdc6dc5`, `9b87020b8` reports | | **no** |

Notes on the picks:

- **`d32c20a20`.** Each commit was inspected with `git show --stat` first. The diff is exactly savefix's
  four edits mirrored into `r7_fused_pass_impl`, `r7_sweep` and `run_fused_server_reordered`. Its
  context contains no perfex hunk, so it applied cleanly. `tests/r7shadow_sync.py` reports "current",
  and `r7shadow_sync_test.py` passes.
- **`ec0317384`.** The only conflict was its Makefile hunk: climon.o budgets 26140/26085. Those values
  were derived on top of `b8eed26c3`'s budgets, i.e. for the source with perfex. The hunk was dropped;
  every other file was taken unchanged (`wb.h`, `climon.cc`, `climon.inc`, `tracking.cc`,
  `netcmd_unit.cc`, mutants). climon.o is re-derived in `4ea309dbf` with every other budgeted object.
- **No perfex content.** `git diff b959fc844 4ea309dbf` touches only the files listed above plus
  `tests/savefix.py`, `tests/scriptfix.py` and the Makefile budget lines.
  - `grep -i perfex` finds nothing in `src/`, `tests/gate.sh`, the label fixture or the Makefile.
  - `src/core/ex_loop.h`, `src/cmd/storesize.cc` and `tests/infofix.py` are byte-identical to
    `b959fc844`, i.e. to origin/cpp plus the seven lanes.
  - The perfex-only R7 inventory change (`28f6289eb`) is not taken. The R7 FIFO twin row passes at
    origin/cpp's 147 bodies per runtime.

### Gate accounting

`tests/gate.sh` keeps origin/cpp's **EXPECT_QUICK=555 / EXPECT_FULL=572**; the landing script sets
EXPECT. Rows were counted with the checker's own `source_labels`, using
[count_rows.py](docs/wave1b/tools/count_rows.py), the cx-wave1 tool. The method reproduces 555/572
on `1ba80bd4e`.

| Rows added by | scriptfix | savefix | aclfix | authfix | clientfix | racefix | flipfix | **Total** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Expected DQ/DF | 8 | 24 | 12 | 5 | 14 | 2 | 5 | **70** |
| Counted at each merge commit (quick = full) | 8 | 24 | 12 | 5 | 14 | 2 | 5 | **70** |

**DQ = +70, DF = +70: 555 -> 625 quick, 572 -> 642 full.**

- The source adds 70 labels and removes none. The cherry-picks add no rows.
- `tests/fixtures/nullrefresh-ledger-labels.json` holds 642 labels, the same multiset as the source.
  It contains none of perfex's four labels (`perfex clock binary regression`, `perfex batch binary
  regression`, `perfex TTL sampler beat (1s)` and `(2s)`): they were never merged at `b959fc844`.
- `python3 tests/gate_ledger_fixture.py` refuses only the count: `EXPECT_FULL=572, fixture=642,
  source declarations=642`, with no missing and no extra labels.

### Inlining budgets re-derived (`4ea309dbf`)

**Method.** This is the docs/ttlclean identity method, applied as in cx-wave1's `b8eed26c3`. The tools
are adapted copies in [docs/wave1b/tools](docs/wave1b/tools/): `trial.py`, `attribute.py`,
`run_trials.sh` and `additive.py`.

1. **Reference builds.** Nine default builds were made from `git archive` under
   `build/wave1b/refs` ([hashes](docs/wave1b/builds/reference-builds.txt)):
   - origin/cpp `1ba80bd4e` (PRE). All its loadable sections equal `bench-bins/tomokv-headline-1ba80bd4e`.
   - the lanes' shared base `5146b78ee`;
   - each lane head with its own Makefile.

   The bisection build b4 was frozen by copy.
2. **Unit sizes.** The GCC IPA starting unit (`-fdump-ipa-inline`, "Starting with size") of every
   budgeted object was measured for PRE and for this source
   ([unit-sizes.jsonl](docs/wave1b/identity/unit-sizes.jsonl)).
3. **Scans.** The centre is the wave1b unit plus origin's headroom (budget minus unit). **319
   compile-only trials** were run, 8-33 values per object
   ([scans](docs/wave1b/identity/budget-trials/), one line per value in [SUMMARY.txt](docs/wave1b/identity/budget-trials/SUMMARY.txt)).
4. **Classification.** Every emitted body was classified against origin/cpp, the shared base and
   each lane's own object. The classes are:
   - lane-identical;
   - multi-lane composite;
   - R7 mirror;
   - climon fix (the renamed drain bodies);
   - single lane but differs from the lane's body;
   - unattributed.
5. **Choice.** No unattributed hot body is allowed. Next, minimise unattributed and lane-differing
   bodies. Ties go to fewer changed bodies, then to call-structure additivity of the composites
   (PRE + each lane's delta), then to the value nearest the centre.

| Object (src / db0) | origin/cpp | b959fc844 (lanes' own) | IPA unit growth | Chosen | Why |
|---|---|---|---|---|---|
| main.o | 146503 / 146540 | 146891 / 146928 | +925 / +909 | **147428 / 147449** | One object across every scanned value, including b959's. Same-headroom value used |
| rl2s.o | 161715 / 161680 | 162035 / 162000 | +654 / +654 | **162300 / 162334** | src: b959's 162035 (and up to 162260) leaves one unattributed body (`cancel_client_transfer<false>`); clean from 162265; fewest non-additive dispatch call counts at 162300. db0: one object across the scan |
| genthread.o | 128865 / 128910 | 129025 / 129370 | +643 / +643 | **129420 / 129640** | src: **b959's value left 6 unattributed hot bodies** (5 `run_loop`, `FlatStore::insert_into`) and 4 single-lane hot bodies that differ from the lane's own; 129420 has none and the fewest changes. db0: fewest changes, lowest non-additivity |
| reorder.o (db0; src has no override) | 147304 | 147752 | +675 | **148258** | No unattributed hot body only inside 148150-148265 (148230 excepted); b959's 147752 has 1 unattributed and 3 lane-differing hot bodies. The 148256-148261 plateau (one object) also returns the ordinary TLS serve lambda to PRE |
| xshard.o | 127791 / 126391 | 127844 / 126421 | +73 / +73 | **127880 / 126482** | Plateaus 127878-127882 / 126480-126485: fewest changes, all lane-identical or composite |
| acl.o | 34630 / 34550 | 35377 / 35324 | +802 / +818 | **35369 / 35324** | Only the two weak-copy differences that every scanned value shows. b959's src 35377 adds one unattributed body |
| climon.o | 25735 / 25670 | 25743 / 25670 | +432 / +432 | **26145 / 26220** | Only lane bodies, the climon fix's drain, and three helper copies the fix's two callers now inline. b959's values left 5 (src) / 10 (db0) more unattributed bodies, plus 2 that differ from clientfix's own |
| t_server.o | 31297 / 31629 | unchanged | +58 / +58 | **31330 / 31725** | No unattributed body. At the old values: src `cmd_info` differs from racefix's own and `shard_owner_count` is unattributed; db0 `cfg_parse_memory` is unattributed |
| snapshot.o | 14584 / 14457 | unchanged | +130 / +130 | **14718 / 14562** | At the old src value `FlatStore::insert` (hot) changed although no lane changed it, plus 3 hot bodies of savefix's drift; db0 had 2 unattributed bodies. Here every hot body stays PRE and every change is savefix's |

The remaining budgets are kept:

| Object | Growth | Why the budget is kept |
|---|---|---|
| geo.o | +10 | Byte-identical to clientfix's own geo.o, the only lane that changes it (0 differing bodies). No src value is cleaner |
| aof.o, t_list.o, t_set.o, t_zset.o, t_string.o | 0 | Byte-identical to origin/cpp |

The final objects were checked against the chosen trial objects: 0 differing bodies for every
re-budgeted object.

### Builds and serverless checks

| Check | Result |
|---|---|
| `make -j16 all` (final budgets) | exit 0, 0 warnings, 69 s; `make -q all` fresh. [log](docs/wave1b/builds/final-build.log.gz) |
| `job_production_units`: 29 targets extracted from the current function, then `mdbqsbr-live-arms` | `make -k -j16` exit 0 (204 s); **29/29 `make -q` fresh**; live arms exit 0 (147 s). The only warnings are the known ones in `tests/atomic_survivors_unit.cc`, `tests/lbplanner_unit.cc` and the wbland-controls copy of `wb_rule.h`. [status](docs/wave1b/builds/production-units.status) |
| `python3 tests/gates_test.py` | **66/66 OK** in 79 s, on otherwise idle CPUs 112-127. [log](docs/wave1b/builds/gates-test.log) |
| `tests/r7shadow_sync.py`, `r7shadow_sync_test.py` | pass |
| Layouts (gdb, both namespaces) | All eight locks unchanged: Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. IoLoop, Server, ExLoopT, AofManager, SnapshotManager, LoopSignals and WbEngine sizes are unchanged. New fields sit only in holes: flipfix's IoLoop pin/drop counter and Server drop count, and authfix's `requirepass_size` in Config's reserved tail. No perfex ExLoopT cursor. [layouts.json](docs/wave1b/identity/layouts.json) |

### Rows: the 70 new rows, `netcmd_units`, R7

All of these ran through the gate itself, in one partial run (479 s):

```sh
GATE_ONLY_JOBS='scriptfix aclfix authfix clientfix racefix_counters racefix_climon flipfix_units snapshot-uring snapshot-epoll aof-uring aof-epoll flip netcmd_units reorder_sync reorder_engagement reorder_identity' \
REDIS74_ROOT=/tmp/claude-1000/redis74 taskset -c 112-127 tests/gate.sh iteration --server-cores 112-119 \
  --load-cores 120-127 --load-smt '' --ports 25200-25299 --candidate-binary "$PWD/build/tomokv"
```

This is cx-wave1's own row method (`MEASURE-REQUEST-wave1.md`, partial runs 1-3), so the gate's job
wiring, prerequisites, boots and labels were exercised too. The prerequisites were the release
footprint, the core and racefix TSan builds and the production units.
[ledger](docs/wave1b/rows/partial-gate-rows.ledger), [per-row table](docs/wave1b/rows/new-rows.tsv).

| Rows | Result |
|---|---|
| scriptfix: sandbox, functions, replies, dump x 1s/2s | **8/8 ok** (functions rows use the port-close poll, `11473d968`) |
| savefix: acknowledged writes 8, BGSAVE cancellation 8 (524288 keys, `546581bd4`), AOF rewrite cancellation 8 | **24/24 ok** |
| aclfix: sort, streams-name, save-load, capacity, wake-pop, wake-scatter x 1s/2s | **12/12 ok** |
| authfix: CG4.1, CG4.2, SV4.2, SV4.1 x 1s/2s | **5/5 ok** |
| clientfix: 7 cases x 1s/2s | **14/14 ok** |
| racefix: TSan INFO counters (both modes), climon armed refresh | **2/2 ok** |
| flipfix: close during FLIP (uring, epoll), signal stop + second SIGINT, two ASAN+TSAN units | **5/5 ok** |
| **`netcmd_units` job** | **16/16 ok**: 12 netcmd cases including `pubsub` (the climon fix's `suppressed_retire_scope`) and `config` (two-phase tracking bound), the build row, `encodingfix knob`/`precedence` and NET1 serverless |
| R7 generated envelope parity | **ok** |
| R7 FIFO twin off-path identity + negative controls | **ok**: `strict_noop=True: 294/294 identical bodies`. All three negative controls fail strict identity, as required |
| R7 production engagement (both runtimes) | ok |
| Every other row in these jobs (aoffix2's 44 AOF rows, snapshot rows, FLIP battery, flipfix units) | ok. Total **210 ok, 0 FAIL** |

### Differential smoke

`tests/differ_gate.sh` ran with suites `multi xshard servertail psfix`. The four required seeds were
7/19/20/23, and the harness loops atomic 0/1. Target 112-119, Redis 7.4.10 oracle
(`/tmp/claude-1000/redis74/src/redis-server`, SHA-256 `ac08d444...`) on 120, load on 121-127, ports
25220/25221. Script: [differ.sh](docs/wave1b/tools/differ.sh).

| Geometry | Legs | Differences | Read-local witnesses |
|---|---:|---:|---|
| split 6:2, 16 shards | **32/32 pass** | 0 | n/a |
| armed-fused, read-local 1 | **32/32 pass** | 0 | **2/2** (peak hits 119 at atomic 0, 100 at atomic 1) |

62 of 245 registered commands were diffed, with 111,100 comparison witnesses per geometry.
[split log](docs/wave1b/differ/differ-split.log), [armed-fused log](docs/wave1b/differ/differ-armed-fused.log).

### Hot-body identity

The stock docs/ttlclean tools were run on the final default build against two baselines:

- origin/cpp `1ba80bd4e` (a PRE rebuilt from `git archive`; its runtime sections equal the headline
  binary's);
- the bisection build b4, `/home/user/Projects/bisect-w1/b4/build` (`b959fc844` with the lanes' own
  budgets, SHA-256 `867563a6...`).

[Script](docs/wave1b/tools/identity.sh), [receipts](docs/wave1b/identity/).

| Tool | vs origin/cpp `1ba80bd4e` | vs b4 (`b959fc844`, lanes' own budgets) |
|---|---|---|
| `tools/lbstall_artifacts.py compare` (1204 hot, PRE names) | **986 equal** with relocation targets resolved (968 raw); 218 DIFF. That is 210 changed bodies plus the 8 drain bodies the climon fix renamed. Exit 1, as expected | **1156 equal** (1149 raw); **48 DIFF**. Exit 1 |
| `tools/ccfix_audit.py` | 16,479 bodies: 15,445 equal, 1,034 changed. Hot (1216, incl. executor `run`): 986 equal, **230 changed**. Handlers **1198/1211** equal. Exits at its strict hot assertion | 16,470 bodies: 16,283 equal, 187 changed, all in 16 objects. Hot 1160/1216 equal. Handlers 1206/1211 |
| `docs/deadswitch/linked_bytes.py` | `.text` 7,596,604 -> 7,646,972 (+50,368); `.rodata` +320; `.bss` +384; `.data` same size | `.text` 7,639,356 -> 7,646,972 (+7,616); `.rodata`/`.bss`/`.data` same size |

The 13 handlers changed against origin/cpp are the same lane changes cx-wave1 reported:
`cmd_function` x4 (scriptfix), `cmd_info` x4 (racefix INFO loads), and GEO sort/GEOPOS helpers x5
(clientfix's GEO TU).

**Every changed hot body against origin/cpp, attributed.** The 230 are counted by name union, so the
climon fix's 8 renamed bodies count under both their old and new names.
[hot-bodies.tsv](docs/wave1b/identity/hot-bodies.tsv) has the per-body reason.

| Hot bodies | Attribution |
|---:|---|
| 72 + 32 | `flush_ready` / `r7_flush_ready`: **clientfix**, writeback mask gains the tracking bit. Byte-equal to clientfix's body |
| 16 | `IoLoop::init` retire lambdas: **clientfix** `tracking_retire_read` hook. Byte-equal |
| 4 | `parse_and_dispatch`: **clientfix** gate after the FLIP hold. Byte-equal to clientfix's body. Two were also changed on racefix's branch; one of those, a cold part, equals racefix's too |
| 8 + 4 + 13 + 2 | `parse_and_dispatch` / `r7_parse_and_dispatch` composites: **clientfix** gate + **racefix** relaxed `note_command` counters, and on 15 also **flipfix**'s out-of-line sampled fingerprint publish. On 2 src rl2s bodies savefix's own branch had pure drift, which is not reproduced |
| 13 + 1 | `ExLoopT::execute`: **racefix** relaxed counters (byte-equal). One db0 reorder body is a racefix + **savefix** (stale-forward hold) composite |
| 11 | `IoLoop::on_cqe`: **racefix** `net_input_bytes` relaxed load/store. Byte-equal |
| 9 + 14 + 4 | `fused_pass_impl` / `sweep` / `ExLoopT::run`: **savefix** owner-loop admission behind `shutdown_snapshot_blocks_tasks`. Byte-equal |
| 3 | savefix `fused_pass_impl`, differing from savefix's own body: see the list below |
| 4 + 4 | `r7_fused_pass_impl` / `r7_sweep`: R7 mirrors of savefix's admission (`d32c20a20`) |
| 8 + 8 | climon fix: `serve_suppressing`, `serve_suppressing_impl`, its drain lambda and `Rob<64>::drain<lambda>`, in both namespaces, under the old (removed) and new signatures |

The three savefix `fused_pass_impl` bodies:

- In db0 genthread, the body is savefix's check on origin/cpp's exact call structure; savefix's own
  build had drift here.
- In the two src reorder bodies, `shutdown_snapshot_blocks_tasks()` is an out-of-line call. That TU
  has no budget, and the R7 copies double the helper's call sites.

No hot body is attributed to scriptfix, aclfix or authfix; their lanes changed none. No
`drain_tasks`/`drain_tasks_read_local_interleaved` body changed, so perfex's batch storage is absent.
Each lane's own hot drift is **not** reproduced: savefix's dispatch/writeback/FlatStore drift,
clientfix's three db0 `reorder.o` compiler changes, and racefix's collateral bodies.

Composite call structure: [composite-additivity.txt](docs/wave1b/identity/composite-additivity.txt).
The expected target multiset is PRE plus each lane's own delta, with savefix's dispatch drift
excluded. Deviations are 0 in src genthread, 1 in each main.o, 2 in db0 rl2s, 6 in each reorder.o,
8 in db0 genthread and 22 in src rl2s. They are the db0 genthread savefix body above plus a varying
count of already-present helper calls: `mark_current_write`, `now_ns`/`clock_gettime`, `note_command`,
`flip_fingerprint_note(_sampled)`, `Rob::publish`/`in_flight` and `Slice::eq_icase`. **No new call
target appears.** In src rl2s, every scanned budget shows deviations, from 22 to 40. flipfix's report
describes the same effect for its own rl2s copies.

The climon fix's drain was also compared after mapping the old names to the new ones
([receipt](docs/wave1b/identity/climonfix-drain-rename.txt)):

- `Rob<64>::drain<lambda>` is byte- and target-equal to origin/cpp's and clientfix's.
- The drain lambda has origin/cpp's size (2224 B) and call targets. Its code differs only by the
  `retire_plain` test.
- `serve_suppressing`, `prepare_suppressing` and `serve_suppressing_impl` grow by 4/4/8 B to pass
  the extra `bool`, with the same targets.

Non-hot residuals: 25 bodies against origin/cpp that are neither lane-identical nor composite. None is
unexplained ([residual-bodies.tsv](docs/wave1b/identity/residual-bodies.tsv)):

- **climon fix (6):** climon.o's copies of `IoLoop::tls_engine`, `arm_tls_socket_poll<false>` and
  `Rob<64>::quiesced` disappear. Their only callers in climon.o were the fix's two changed drain
  entries, which now inline them; other objects keep their copies.
- **Weak copies the linker discards (5):**
  - acl.o no longer emits `vector<Client*>::push_back` (x2); the linked copy is now climon.o's,
    whose normalized bytes equal origin/cpp's acl.o copy in both namespaces;
  - acl.o's `close_client` from flipfix's pin (x2); the linker takes main.o's copy;
  - db0 genthread's `flip_build_client_plan`; db0 main.o's copy is linked.
- **R7 regeneration (`d32c20a20`):** `run_fused_server_reordered` and its thread lambdas (6), and the
  out-of-line `shutdown_snapshot_blocks_tasks` in src reorder.o.
- **Unbudgeted src reorder.o:** `atomic_collapse_read_local`, as in cx-wave1, and
  `FlatStore::snapshot_prepare_write`. The latter is identical in b4, so it comes from the lane merge
  under GCC's default proportional growth, not from a budget.
- **db0 snapshot.o:** the weak `kvobj_free_with_capacity` returns to the `5146b78ee` body, reverting
  aoffix2's drift. It is the same in b4.

**Every hot body that differs from b4, attributed.**
[b4-hot-bodies.tsv](docs/wave1b/identity/b4-hot-bodies.tsv)

| Hot bodies vs b4 | Cause | Final body compared with origin/cpp |
|---:|---|---|
| 8 | climon fix (`ec0317384`): b4's old-signature drain bodies, replaced by the renamed ones | climon fix (above) |
| 7 | R7 regeneration (`d32c20a20`): `r7_fused_pass_impl` x4, `r7_sweep` x3 | R7 mirrors of savefix |
| 3 | R7 regeneration in the unbudgeted src reorder.o: `fused_pass_impl` x2, `r7_sweep` | savefix's check (out-of-line helper) |
| **16** | budget re-derivation: src genthread `run_loop` x5 and `FlatStore::insert_into`; db0 reorder `serve_impl` x2 and `serve_tls_impl` x2; snapshot.o `FlatStore::insert`/`insert_into`/`insert_read_local`/`find_in`/`erase_in` (6) | **equal to origin/cpp: b4 carried drift here that no lane intended** |
| 7 | budget re-derivation: `flush_ready` x5, db0 reorder `execute`, db0 reorder `fused_pass_impl` | now **byte-equal to the lane's own body** (clientfix, racefix, savefix) |
| 6 | budget re-derivation: src rl2s `parse_and_dispatch` x5, db0 reorder `execute` | lane composites (call-count variation above) |
| 1 | budget re-derivation: db0 genthread `fused_pass_impl` | savefix's check on PRE call structure |

Against b4, 16 of the 100 objects differ, with 187 bodies:

- climon.o and tracking.o (the fix plus the climon budget);
- reorder.o (R7 regeneration plus the db0 budget);
- the re-budgeted genthread, snapshot, src rl2s, t_server, xshard and src acl objects.

main.o, db0 rl2s.o and db0 acl.o come out identical to b4 at the new budgets. The handler changes
against b4 come from the t_server.o budget: `cmd_info` x4 (both namespaces, with cold parts) and src
`cmd_config`. At the final budget:

- `cmd_config` equals origin/cpp's;
- src `cmd_info` equals racefix's own body;
- db0 `cmd_info` is the racefix + authfix composite.

### infofix battery x10

The two rows ran exactly as `tests/gate.sh` runs them, as whole `feature-split-0` and
`feature-split-1` jobs:

- one boot per atomic mode (split 6:2, 16 shards, `--enable-debug-command yes`);
- every `FEATURE_BATTERIES` entry in order, with `expwide` (one-hour TTLs) immediately before `infofix`;
- **ten partial gates** on the final default binary (`f47d319d...85c9b7d`), one after another, with
  nothing else running on CPUs 112-127.

[infofix10.sh](docs/wave1b/tools/infofix10.sh), [summary, ledgers and both rows' outputs](docs/wave1b/infofix/).

| Run | `infofix battery (atomic 0)` | `infofix battery (atomic 1)` | All rows of the run | Seconds |
|---:|---|---|---|---:|
| 1 | ok (INFOFIX: PASS, 41 checks) | ok (INFOFIX: PASS, 41 checks) | 69 ok, 0 FAIL | 248 |
| 2 | ok (INFOFIX: PASS, 41 checks) | ok (INFOFIX: PASS, 41 checks) | 69 ok, 0 FAIL | 253 |
| 3 | ok (INFOFIX: PASS, 41 checks) | ok (INFOFIX: PASS, 41 checks) | 69 ok, 0 FAIL | 260 |
| 4 | ok (INFOFIX: PASS, 41 checks) | ok (INFOFIX: PASS, 41 checks) | 69 ok, 0 FAIL | 263 |
| 5 | ok (INFOFIX: PASS, 41 checks) | ok (INFOFIX: PASS, 41 checks) | 69 ok, 0 FAIL | 254 |
| 6 | ok (INFOFIX: PASS, 41 checks) | ok (INFOFIX: PASS, 41 checks) | 69 ok, 0 FAIL | 247 |
| 7 | ok (INFOFIX: PASS, 41 checks) | ok (INFOFIX: PASS, 41 checks) | 69 ok, 0 FAIL | 253 |
| 8 | ok (INFOFIX: PASS, 41 checks) | ok (INFOFIX: PASS, 41 checks) | 69 ok, 0 FAIL | 242 |
| 9 | ok (INFOFIX: PASS, 41 checks) | ok (INFOFIX: PASS, 41 checks) | 69 ok, 0 FAIL | 248 |
| 10 | ok (INFOFIX: PASS, 41 checks) | ok (INFOFIX: PASS, 41 checks) | 69 ok, 0 FAIL | 269 |

**infofix failures: 0 of 20** (10/10 for `(atomic 0)`, 10/10 for `(atomic 1)`). No run printed a
`measured avg_ttl` failure. Every other feature-split row also passed in all ten runs (69 ok per
run, 0 FAIL).

**Extra stress, same procedure as cx-wave1 fix2.** This is cx-wave1 fix2's direct repro: one boot
per atomic mode, then five rounds of `expwide` followed by `infofix` in the same boot. It produced
3/10 failures on both perfex-carrying cx-wave1 binaries. On this binary it gives **0/10 failures**:
every `expwide` passes its 101 checks and every `infofix` passes its 41.
[infofix_repro.py](docs/wave1b/tools/infofix_repro.py),
[summary](docs/wave1b/infofix/direct-stress-summary.json),
[logs](docs/wave1b/infofix/direct-stress-logs.tar.gz).

| Build | Gate / stress result for `infofix battery` |
|---|---|
| cx-wave1 with perfex, landing gate | FAIL `measured avg_ttl: got 3595598` |
| cx-wave1 with perfex, fix2 (both its binaries) | gate runs 2/4 and 3/4 failed under load; direct stress **3/10** failed per binary (`got=3.54e6-3.60e6`) |
| **wave1b, no perfex (this branch)** | **gate runs 0/20 failed**; direct stress **0/10** failed |

This confirms that the avg_ttl staleness came with perfex. wave1b's `src/core/ex_loop.h`,
`src/cmd/storesize.cc` and `tests/infofix.py` are byte-identical to the pre-perfex merge
`b959fc844`. Here `Shard::publish_size` republishes each shard's keyspace TTL sample whenever it
publishes its counts. perfex moved that sample to a 1 ms executor beat that refreshes at most one
volatile shard per owner per beat. A shard can then still report `expwide`'s one-hour sample when
`infofix` reads INFO. perfex's version of `infofix.py` waits only while `avg_ttl == 0`, so it cannot
wait out a stale nonzero sample. That mechanism comes from reading the source; the measured fact is
the 0/20 above. The battery was not changed or weakened.

### For the mainline

1. **EXPECT:** set **625/642** (+70/+70). The fixture already holds all 642 labels.
2. **Performance null:** PRE = `bench-bins/tomokv-headline-1ba80bd4e`, POST = this branch's default
   build (`build/tomokv`, SHA-256 `f47d319d19deca792a665ed8cdc864ad8162bf347035e760baa61adbf85c9b7d`,
   source `4ea309dbf`; later commits add only docs). The 230 hot bodies change by design. By lane,
   counting composites once per lane:
   - clientfix 151;
   - racefix 54;
   - savefix 32, plus 7 R7 mirrors;
   - flipfix 15;
   - climon fix 8 bodies (16 names).

   Every lane requested the null.
3. **perfex** is not in this branch. Its four rows, its R7 inventory delta (`28f6289eb`) and its
   budgets (`b8eed26c3`) belong to the separate perfex lane. Applied on top of this branch, perfex
   must re-derive the TUs it changes (main, genthread, rl2s, reorder) and re-measure the infofix
   battery.
4. **Carried open items, from the lane reports and cx-wave1, minus perfex:**
   - scriptfix: CC4.6 per-executor function state.
   - savefix: AOF in-flight EXEC shutdown hang.
   - aclfix: items 1-5.
   - clientfix: CC4.4, the PFMESSAG.1 table, the keyless-record cap.
   - flipfix: the LoopSignals counter race, the NotifyMask load-first skip, the `flip_coordinator_` race.
   - racefix: the two `LoopSignals::accepts` TSan reports. Its differential suites beyond servertail
     were not run here.
   - The `racefix_tsan_build` job builds a full TSan server on every gate.
   - `build/netcmd-unit-db0` `config`/`tracking-eviction` stop at the by-design `tracking map
     swapped` precondition. This dates from 09-18, and that binary is not a gate target.
