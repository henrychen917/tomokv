## wave3 integration

**Update 2026-10-21:** the mainline approved decisions 1 and 2. Both patches are applied and the reorder.o budgets re-derived. The final HEAD, binary and FAIL rows are in the addendum at the bottom, which supersedes the binary, gate and decision rows below.

Worktree `/home/user/Projects/cx-wave3`, branch `cx-wave3`, created at origin/cpp **f821104a9** (wave 2).
The five wave-3 lanes are merged with `--no-ff` in the requested order, and mkfix2 part C is reverted
after them. Every lane commit is kept: the five lane tips are ancestors of HEAD. The lane worktrees
were only read. Nothing was pushed and no stash entry was used. EXPECT_QUICK and EXPECT_FULL were not
edited. No ABBA, merit or other performance measurement was run.

Everything ran on CPUs 80-95 (builds `-j16`; servers 80-87, the Redis 7.4.10 oracle on 88, clients
89-95) and ports 22800-22899. The oracle binary is `/home/user/Projects/redis74/src/redis-server`.
The gate and `differ_gate.sh` need a Redis source tree, so they use `/home/user/Projects/redis`. Its
`src/redis-server` is byte-identical to the redis74 binary (SHA-256 `ac08d444...509b`).

**Result**

| Check, integrated default build `build/tomokv` (SHA-256 `07cda1d9...6909d1`) | Result |
|---|---|
| Merges | 5 lanes merged in order, then C reverted. Textual conflicts were in `Makefile` (adjacent targets, budgets), `tests/gate.sh` (`JOB_NAMES`, production-unit lists) and the label fixture `purpose`/labels. All sides were kept. mkfix2's code now equals `5b8ab21f4` (A+B) byte for byte |
| Rows declared by the source / label fixture | **DQ=+27, DF=+27: 664 quick / 681 full** over 637/654 (respresume +12, rlfix +4, mkfix +0, aoforder +3, hexpread +8). The fixture holds 681 labels with none missing or extra; the checker accepts it at 681 in memory. EXPECT stays 637/654 |
| `make all`, 32 `job_production_units` targets, `mdbqsbr-live-arms` | exit 0, 0 warnings in `all`, **32/32 `make -q` fresh**, live arms exit 0, `make -q all` fresh. The only warnings are the known `-Wmismatched-new-delete` ones in two test units |
| `tests/gates_test.py`; `abbagate.py --self-test`; nullpublish4 set | **66/66 OK** (+ nested 14/14); abbagate **156/156**; abba_instrument 7, nullpublish4 10, refreeze 1, `_nullrefresh` 27: all OK. `gate_receipt.py --self-test` refuses on this tree **only** because EXPECT_FULL is 654 while the source and fixture hold 681. The gate's entire abba_selftest chain passes on a snapshot whose only change is EXPECT 664/681 |
| **Full gate** (quick tier + the full tier's other jobs; the literal `iteration` command is refused at planning, see below) | **681 rows: 674 ok, 7 FAIL** after the store_build fix `f12ee5762`, whose 13 storage rows were re-run through the gate (13/13 ok). Three of the FAILs are rlfix's stale R7 envelope and two are rlfix vs the rltopo unit (rlfix's tip fails all five identically; **decisions 1-2**). One is the abba_selftest row (EXPECT). One is tailgen, which needs 16 distinct load cores; this allocation has 7. The PROGRAM-STATE tally reads 664/637 (EXPECT) |
| The 27 new rows, run by `tests/gate.sh` | **27/27 ok** |
| The new rows on the f821104a9 binary | **All fail for their lanes' reasons**: respresume CPU and neighbour bounds, rlfix lane hits 0, aoforder replay != live, hexpread erase/reap/notifications/OBJECT. aoforder's crossing row always uses the integrated scheduled build, so it passes |
| Redis 7.4.10 differential: 47 suites, seeds 7 19 20 23, atomic 0/1 | split **376/376**; armed fused **370/370** (368 legs plus both read-local witnesses, hits=1257 at peak); **0 differences**. The 8 armed `sort` legs SKIP by design (split-only suite). 232/245 commands diffed |
| Lane batteries | respresume limits: PRE = integrated in 4 boots. TLS fragments: epoll 4692/4692, uring 4086/4086. aoforder: 144/144 persistence cells; its hash-expiry tear probe still tears on f821104a9 (4/4) and **passes on the integrated binary (4/4)**. hexpread: notifications/INFO = Redis in 4/4, atomic batteries in both modes. rlfix: 28/28, and f821104a9 fails 8/8. mkfix2 A+B counts: 72 cells, see below |
| Selected hot bodies vs f821104a9 (1,219, incl. ExLoopT run and prepare_local_read) | 1,142 equal. **54 equal the build of the lane that changed them**: respresume 17, mkfix2 16, hexpread 15, rlfix 6. **23 are respresume+mkfix2 dispatcher composites**: both lanes edit the same `parse_and_dispatch` bodies, so neither lane's build can match; each is decomposed below. **0 unattributed** |
| All bodies vs f821104a9 | 16,704 bodies; 629 changed. **A 587** lane-identical, **B 40** composites, **D 2** (cold), **C 0**. 383 reach the binary (A 353, B 29, D 1) |
| Layout locks | Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624: unchanged in both namespaces. The only new member is respresume's `Client::multibulk_`, placed in the IO-only alignment hole |

### Decisions for the mainline

1. **rlfix's RL4.4 is missing from the R7 envelope.** rlfix edited `ReadLocalDemotionPlan::prepare` in
   `src/core/io_loop.h` but never regenerated the R7 copy that `tests/r7shadow_sync.py` generates into
   `src/core/reorder.cc`. Three rows fail: `R7 generated envelope parity`,
   `writeback policy clauses witnesses + negative controls` and
   `splitlocal template forwarding + old-argument controls` (the last two run the same parity check).
   - rlfix's tip `59ef3e4b0` fails the parity check. f821104a9, 991d48f65 and the other four lane tips
     pass ([per tree](docs/wave3/fixes/r7shadow-sync-per-tree.txt)).
   - Behaviour: with `--reorder 1` (R7, off by default), rlfix's one-key DEL witness fails on this
     branch (`read_local_hits: got 0, wanted 4`, atomic 0 and 1). The GET-miss witness passes.
   - Proposed patch: [r7-envelope-regeneration.patch](docs/wave3/fixes/proposed/r7-envelope-regeneration.patch),
     which is exactly the generator's output (+21 lines in the R7 envelope). On a scratch build of this
     branch plus the patch, these pass: the three rows, `R7 FIFO twin` (292/292), the writeback paths row,
     and the DEL witness on R7 (atomic 0/1) ([receipts](docs/wave3/fixes/r7-option)).
   - It is **not applied**. It is production code that no lane built or measured. It changes db0
     `r7_parse_and_dispatch<false,32u,false>` (hot), both demotion-plan bodies in reorder.o and a few
     cold reorder.o bodies ([list](docs/wave3/fixes/r7-option/changed-bodies-vs-cx-wave3.txt)). If
     applied, it needs a reorder.o budget pass and an R7 null.
2. **rlfix's RL4.3 vs `tests/rltopo_unit.cc`.** The rows `read-local topology demotion (1s/2s)` fail at
   `readreply GET/missing: exact final fallback reason`. The unit still expects a lane GET miss to fall
   back with `Missing`, but RL4.3 now serves it locally (nil, one keyspace miss).
   - rlfix's tip fails identically. 991d48f65 passes ([logs](docs/wave3/fixes)).
   - Proposed patch: [rltopo-rl43-expectation.patch](docs/wave3/fixes/proposed/rltopo-rl43-expectation.patch).
     The GET miss expects `None`, nil and one miss. The unit passes with it on this branch and fails
     with it on 991d48f65 ([check](docs/wave3/fixes/rltopo-proposed-patch-check.txt)).
   - It is **not applied**, because it changes an assertion.
3. **EXPECT: set 664 / 681** (DQ +27, DF +27). The fixture already holds all 681 labels. This also
   clears the abba_selftest row and the PROGRAM-STATE tally.
4. **Performance null required**, PRE = f821104a9 and POST = this binary. No lane-measured binary equals
   it: the 23 dispatcher composites exist only here, and `.text` grows by 81,557 bytes. The merit cells
   to repeat are respresume's (d32g_l1 and its 8 cells), mkfix2 A/B's (atomic-1 MSET, MGET), rlfix's,
   and the GET/SET/MGET/MSET controls. Boots need `--databases 1`.

### Merges

| # | Lane (tip) | Merge commit | Rows | Conflicts and resolution |
|---|---|---|---|---|
| 1 | `cx-respresume` (`f95da7d55`, 13 commits) | `39a4bd9b2` | +12/+12 | **`Makefile`:** adjacent new targets (wave 2's opt-in lottery arms and respresume's `build/respresume-unit`); both kept. **Auto-merged:** `tests/gate.sh`, `src/core/io_loop.h` and the rest. **Added here:** the lane had not touched the EXPECT arithmetic comment or the label fixture. The comment now states its +12/+12 and the running wave-3 total. The collection-site comment names the lane base it counted from (625/642). The fixture gains the twelve source labels after `RESP protocol error compatibility`, plus a purpose clause |
| 2 | `cx-rlfix` (`59ef3e4b0`, 5) | `d1f5fe0bc` | +4/+4 | **`Makefile` budgets** of src/db0 genthread, src rl2s and db0 reorder (wave 2 and rlfix each moved them from 991d48f65): provisional additive values with rlfix's db0 reorder `max-inline-insns-auto=14` and all comments kept; re-derived in `55527432b`. **Auto-merged:** `src/core/{ex_loop,io_loop}.h`, `tests/gate.sh` and the fixture (`rlfix_supplement`) |
| 3 | `cx-mkfix` (`c6f990023`, 11: mkfix study + mkfix2 A/B/C) | `2d2b7cefd` | +0/+0 | none |
| 3r | `git revert ba0160c0c` (mkfix2 C) | `37d19a0e5` | +0/+0 | **Conflict:** the revert conflicts in `MEASURE-REQUEST-mkfix.md`, because the later proof commit `c6f990023` builds on C's text and on the `ab-full`/`abc-*` inventories C added. **Kept:** every doc and receipt. **Removed:** C's code, i.e. `multikey_task_room()` and its call in `xshard_prepare` (`src/cmd/scatter_engine.inc`), and C's standalone room unit `tests/mkfix2_room_unit.cc` (it asserts C's refusal, fails on A+B by design, and has no Makefile or gate wiring). **Result:** `src/cmd/scatter_engine.inc` and `src/exec/op.h` equal `5b8ab21f4` (A+B) byte for byte |
| 4 | `cx-aoforder` (`bd2fb1fcb`, 15) | `0fa72333f` | +3/+3 | **`Makefile`:** adjacent targets, both kept; aof.o budgets (wave 2 34437/34840, aoforder 37300/37800) set to provisional additive values 37337/37840, later re-derived. **`tests/gate.sh`:** `job_production_units` build and freshness lists; respresume's units and `aoforder-scheduled` both kept. **Fixture:** both purpose clauses and both label groups kept |
| 5 | `cx-hexpread` (`fd61ad039`, 7) | `338602a38` | +8/+8 | **`tests/gate.sh` `JOB_NAMES`:** wave 2's `perfex_units perfex_live dbdefault`, aoforder's job, and hexpread after `atomic_batteries`; all kept. **Fixture purpose:** every clause kept. **Auto-merged:** `src/store/flatstore_atomic.inc` and the hash/server_tail sources |

| Commit after the merges | Kind | Content |
|---|---|---|
| `55527432b` | build | inlining budgets re-derived (below) and the identity receipts |
| `f12ee5762` | gate wiring, no assertion | `store_build` links `src/cmd/hexpread.cc`, as hexpread's own `Makefile` change (`STORE_REGRESSION_SRC`) does. Without it both store-regression links miss `hash_parked_reply` and all 13 `storage ... regression` rows fail, here and on hexpread's tip `fd61ad039` ([log](docs/wave3/fixes/hexpread-tip-store-build.log)). Re-run through the gate: 13/13 ok |
| `db316097b`, `7434fa7c2`, `185a06891`, `12d06a4a7`, this report | docs | receipts and tools under `docs/wave3/` |

**Boot images (dbdefault rule).**
- respresume's and rlfix's rows boot through the gate's `boot`/`boot_fused`, which insert `--databases 1`.
- `tests/aoforder.py`, `tests/hexpread.py` and `tests/objectpread.py` boot through `tests/aoffix2.py`'s
  `Server`, which now passes `--databases 1`. Each driver then appends its own explicit
  `--databases N`: aoforder uses 1 and 16 by design and 16 for its operation cells; hexpread uses 16.
- The last value wins (checked: `--databases 1 --databases 16` boots 16 databases), so these rows keep
  exactly the images their lanes proved.
- The wave-3 runners that boot TomoKV directly pass `--databases 1`.

### Rows

| Lane | Rows (all collected before the quick-tier exit) | DQ | DF |
|---|---|---:|---:|
| respresume | `RESP resumable {fragment,cpu,neighbour} ({1s,2s}, {epoll,uring})` | +12 | +12 |
| rlfix | `read-local GET miss battery (1s/2s)`, `read-local one-key delete battery (1s/2s)` | +4 | +4 |
| mkfix | none (count tooling; mkfix2's units are standalone) | +0 | +0 |
| aoforder | `AOF commit order single / crossing / rewrite` | +3 | +3 |
| hexpread | `hexpread {torn,replies,deferred,OBJECT expiry} ({1s,2s})` | +8 | +8 |
| **Total** | | **+27** | **+27** |

- Counted with the checker's own `source_labels`: f821104a9 has 637/654 and this tree 664/681. The
  diff adds exactly the 27 labels and removes none
  ([ledger-check.json](docs/wave3/ledger/ledger-check.json)).
- The fixture's 681 labels are the same multiset as the source. The unmodified
  `tests/gate_ledger_fixture.py` refuses only the count (`EXPECT_FULL=654, fixture=681, source
  declarations=681`).
- The EXPECT arithmetic comment above `EXPECT_QUICK` states each lane's rows and the total 664/681.

### Inlining budgets re-derived (`55527432b`)

**Method.** This is the docs/ttlclean identity method as wave 2 applied it, with tools in
[docs/wave3/tools](docs/wave3/tools) (`build_refs.sh`, `attribute.py`, `trial.py`, `scan1-3.sh`,
`rank.py`).

1. **Reference builds.** `git archive` builds of f821104a9 (PRE), 991d48f65 (every lane's base) and each
   lane tip with its own Makefile. mkfix's reference is `5b8ab21f4` (A+B). Each reference's loadable
   sections equal the binary that lane handed off and the mainline measured, and PRE's equal
   `bench-bins/tomokv-headline-f821104a9` ([refs-vs-lanes](docs/wave3/identity/refs-vs-lanes)).
2. **Classification.** A body is "changed by a lane" when that lane's build differs from 991d48f65, and
   "changed by wave2" when f821104a9 differs from 991d48f65.
   - A: exactly one change-set changed it, and the merged body equals that build.
   - B: several change-sets changed it.
   - C: none changed it.
   - D: one changed it, but the merged body differs from that build.
3. **Scans.** 731 compile-only trials in 3 rounds
   ([one line per trial](docs/wave3/identity/budget-trials/SUMMARY.txt)).
4. **Choice.** The order of preference was:
   1. no hot C/D body;
   2. fewest C+D;
   3. fewest changed hot bodies (equal to f821104a9 beats equal to a lane);
   4. fewest changed bodies;
   5. nearest the headroom-preserving value (f821104a9 budget + IPA unit growth), and off a plateau edge.

| Object (src / db0) | f821104a9 | Lane values | IPA unit growth | **Chosen** | Why |
|---|---|---|---|---|---|
| genthread.o | 129447 / 129704 | rlfix 129780 / 129730 | +388 / +386 | **129975 / 130179** | src: one D at every value: wave 2's `atomic_prepare_capacity_read_local`, with the same size and call targets as f821104a9 and two field preparations in the other order (a discarded COMDAT copy). The fewest changed bodies are at 129975-129976. db0: clean at 130178-130181 |
| rl2s.o | 162305 / 162334 | rlfix 162609 / - | +454 / +452 | **162716 / kept** | src: clean plateau 162672-162720. db0: identical bodies at 162334 and at the centre 162786 |
| reorder.o | (none) / 148358 | rlfix db0 148438 + auto=14 | +454 / +441 | **147794 (new) / 148772 + auto=14** | **src (first override):** GCC's default limit is 1.4 x the running minimal unit, which ends at 105268 on f821104a9 (`-fdump-ipa-inline`). The equivalent absolute limit is 147375, so 147375 + 454 = 147829 preserves f821104a9's headroom. Without an override, the merged unit gets 181 more insns, which inlined `Rob::quiesced` into `drive_tls` and `flush_xshard_commits` into the R7 `sweep` (2 hot C bodies). 147792-147795 is clean. **db0:** rlfix's `max-inline-insns-auto=14` keeps f821104a9's `r7_fused_sweep_impl`; clean at 148769-148774 |
| main.o | 147428 / 147449 + auto=18 | - | +204 / +204 | **kept** | identical bodies at the centre |
| aof.o | 34437 / 34840 | aoforder 37300 / 37800 | +1662 / +1656 | **37179 / 37578** | src: clean at 37177-37182. db0: one D at every value: aoforder's `record_post_image_impl` calls `Slice::key_eq` out of line in the merged unit (cold AOF path). 37576-37580 is chosen |
| xshard.o | 127924 / 126566 | - | +79 / +79 | **128012 / 126680** | src: clean at 128010-128014. db0: clean at 126680 (the scan is chaotic; 126682 and 126685 are also clean) |
| t_server.o | 31379 / 31776 + auto=16 | - | +23 / +23 | **31388 / 31787** | clean at 31388-31389 / 31785-31789 |

### Full gate

| Phase | Command (CPUs 80-95, ports 22800-22899) | Result |
|---|---|---|
| Literal request | `taskset -c 80-95 tests/gate.sh iteration --server-cores 80-88 --load-cores 89-95 --ports 22800-22899` | **Refused at planning, before any work** (rc=2): `no reviewed abba io:ex ratio for 9 server threads`. The iteration tier's smoke ABBA needs a reviewed geometry, and `gate_measurements.json` has only 32 threads. ABBA is a measurement and emits zero scored rows ([log](docs/wave3/gate/0-literal.log)) |
| Quick tier, every row before the quick-tier exit | `tests/gate.sh quick --server-cores 80-88 --load-cores 89-95 --load-smt '' --ports 22800-22899` (source build) | 664 rows: **644 ok, 20 FAIL**, plus PROGRAM-STATE 664/637; 3232 s ([ledger](docs/wave3/gate/quick.ledger)) |
| The full tier's remaining jobs | `GATE_ONLY_JOBS='asan_batteries replyoff zc rldbg rlcache differ-split differ-armed globcase' tests/gate.sh iteration ...` | **22 ok, 0 FAIL**: 15 full-only rows, both differential folds as their 5 parts, and the 2 build prerequisites; 2269 s ([ledger](docs/wave3/gate/fullonly.ledger)) |
| After `f12ee5762` | `GATE_ONLY_JOBS=storage_units` | **13/13 ok** ([ledger](docs/wave3/gate/storage-rerun.ledger)) |

| FAIL row (quick tier) | Cause | Evidence | Status |
|---|---|---|---|
| 13 x `storage ... regression` | hexpread put `hash_parked_reply` in `src/cmd/hexpread.cc` and added it to the Makefile's store-regression sources, but not to the gate's `store_build` mirror. The link fails | Same link error on hexpread's tip | **fixed** `f12ee5762` (wiring only); 13/13 ok |
| `R7 generated envelope parity`, `writeback policy clauses ...`, `splitlocal template forwarding ...` | Stale R7 envelope after rlfix's RL4.4 | rlfix tip fails `r7shadow_sync.py`; patch passes all three | **decision 1** |
| `read-local topology demotion (1s)`, `(2s)` | RL4.3 vs rltopo's GET/missing expectation | rlfix tip fails the same check | **decision 2** |
| `ABBA comparison + saturation negative controls` | `gate_receipt.py --self-test`: fixture 681 vs EXPECT_FULL 654 | chain passes with EXPECT 664/681 | **decision 3** |
| `PROGRAM-STATE ledger` (664/637) | EXPECT tally | - | **decision 3** |
| `tailgen client-lb outstanding bound` | `tailgen: need at least one distinct allowed core per thread` (16 threads, 7 load cores) | passes on the full box (f821104a9 landing ledger, 50 s) | geometry; not runnable in 80-95 |

The verdict-history report printed "DEFECT NEEDS FIX" for the new rows. That is noise from this
worktree's own history: the f821104a9 spot-check run recorded their expected FAILs first.

### Redis 7.4.10 differential

The unmodified `tests/differ_gate.sh` focused proof was run with every suite `tests/differ.py`
discovers (47), seeds 7 19 20 23, and atomic 0 and 1. Target 80-87, oracle 88, load 89-95
([driver](docs/wave3/tools/differ.sh)).

| Geometry | Result | Witnesses |
|---|---|---|
| split 6:2 | **pass=376 fail=0** (14m07s) | 1,703,032 comparisons, 232/245 commands ([log](docs/wave3/differ/split.log)) |
| armed fused (`--read-local 1`) | **pass=370 fail=0** (13m57s): 368 legs + `read-local lane fired` for atomic 0 and 1 (hits=1257, fallbacks=2 at peak); the 8 `sort` legs SKIP by design | 1,665,703 comparisons, 232/245 commands ([log](docs/wave3/differ/armed-fused.log)) |

The read-local witness rises from 983 hits (wave 2) to 1257. rlfix's own differential reported the
same 1,257: GET misses are now lane-served. hexpread's hash-TTL legs (hexpire, edgetime, hash) are
included: 48/48 ok.

### Lane batteries (integrated binary unless stated; [exits](docs/wave3/batteries/exits.txt))

| Lane | Battery | Result |
|---|---|---|
| respresume | Limits corpus (`tests/respresume_limits.py`): PRE f821104a9 vs integrated vs Redis, 1s/2s x uring/epoll | **4/4 boots: PRE and integrated byte-identical, with identical close behaviour in every case** |
| respresume | TLS fragment corpus (`tests/respresume.py fragment --tls`, Redis over TCP), gate shapes | **epoll 4692/4692 and uring 4086/4086** trials, in both modes. Like the lane, uring skips the 606 close-expecting trials (finding F2) |
| aoforder | Hash-expiry live-tear probe (aoforder's unfixed finding, fixed by hexpread HX-1) | f821104a9 still **tears in 4/4** cells (AOF always and off, both modes). **Integrated passes 4/4**: live `["1","1"]`, and LOADAOF and restart equal live |
| aoforder | `persist_proof.py`: primary 16, drivers 70, rewrite 16, snapshot 26, supplementary 16 | **144/144 PASS**. The F3 rows themselves are the gate rows above (single 8 + 10 operation cells, crossing 8, rewrite 8) |
| hexpread | Ordinary lazy expiry: replies, notifications and INFO deltas vs a fresh Redis 7.4.10 oracle | The fresh oracle equals the lane's committed observations; **1s/2s x atomic 0/1: 4/4 equal** |
| hexpread | Atomic batteries: torn/window `--release-build`, RYOW/mixed-write, owner-local hazards, in **both** modes | **6/6 pass**, both shutdowns clean |
| rlfix | rlfix's `check.py`: miss and delete witnesses + RYOW, atomic RYOW, B+, lane admission and MGET fence, 1s/2s x atomic 0/1 | **28/28**. On f821104a9, **8/8 fail as expected** (`read_local_hits: got 0`) |
| mkfix2 | `mkfix_counts.py`, 36 WB cells (GET/MGET-8/MSET-8 x p8/p32/p128 x 1s/2s x atomic 0/1). Allocation counts use a re-created scratch LD_PRELOAD counter ([mkcount.c](docs/wave3/tools/mkcount.c)); the lane's had been deleted | **A:** atomic-1 MSET replies/send is 1.449/2.717/4.901 (1s) and 1.278/2.373/4.444 (2s). PRE is about 1.00, the lane's A is 1.43-4.51 and its AB 1.29-4.67. **B:** common-arena allocations are **<= 0.025/cmd**; PRE and A are 0.03-0.74, the lane's AB <= 0.024. GET at both atomic settings matches PRE (0 allocations). **C reverted:** 2s atomic-0 MGET fan-out cuts/cmd are again 2.99 (p32) and 5.17 (p128), the abandoned-prepare signature of A+B ([table](docs/wave3/batteries/mkfix/table.json)) |

### Hot-body identity vs f821104a9

These are the stock docs/ttlclean tools ([identity.sh](docs/wave3/tools/identity.sh)). They exit 1,
as they must, because lane bodies change.

| Tool | Result |
|---|---|
| `tools/lbstall_artifacts.py compare` | 1210 hot: **1138 equal** with resolved targets (1122 raw); 72 DIFF |
| `tools/ccfix_audit.py` (PRE's objects; the 2 new hexpread objects are not in PRE) | 16,592 bodies: 16,075 equal, 517 changed. Hot 1215: **1142 equal**, 73 changed. Handlers 1211: 1167 equal; the 44 changed are hexpread 42 (hash readers, OBJECT, server_tail inlining) and respresume 2 (`cmd_quit`) |
| `docs/deadswitch/linked_bytes.py` | `.text` 7,647,932 -> 7,729,489 bytes (+81,557). `.rodata`, `.data` and `.bss` keep their sizes. Loadable sections differ |

**Every changed body, with its change-set** ([changed-bodies.tsv](docs/wave3/identity/changed-bodies.tsv):
object, body, class, change-sets, sizes, call targets, reason. [linked-attribution.json](docs/wave3/identity/linked-attribution.json)
records whether each object's copy reaches the binary; the relinked binaries equal the shipped ones.)

| Change-set | Bodies | Class | What they are |
|---|---:|---|---|
| respresume | 240 | A | 17 hot dispatcher bodies (`parse_and_dispatch` clones in main.o and the `.isra/.cold` clones), 108 resumable-parser bodies, 10 frontier-release paths and 105 bodies of code generation identical to respresume's own build |
| hexpread | 219 | A | 58 HX-1 parked-hash read bodies, 4 HX-2 OBJECT bodies, and 157 hash/server_tail code-generation bodies (the accepted 54-body scope, counted per namespace and COMDAT copy). The 15 hot ones are `FlatStore::find/erase*` copies in the hash and new objects |
| aoforder | 67 | A | F3 ticket-ordered staging in aof.o (both namespaces) |
| mkfix | 44 | A | 16 hot `IoLoop::init` retire lambdas (A), 14 arena-retention bodies (B) and 14 others identical to mkfix2 AB's own build |
| rlfix | 17 | A | 6 hot `prepare_local_read` (RL4.3), 6 demotion-plan bodies (RL4.4) and 5 code-generation bodies |
| respresume + mkfix | 24 | B | 23 hot dispatcher composites (decomposed below) and 1 cold body both lanes build identically |
| other B | 16 | B | cold. 11 equal one changer's own body or 991d48f65, or are built identically by every changer. The other 5 combine wave 2's and a lane's code generation: `manifest_name` x2, db0 `hash_key.isra`, `kvobj_external_bytes` x2 |
| aoforder | 1 | D | db0 `record_post_image_impl`: `Slice::key_eq` stays out of line at every scanned budget (cold; reaches the binary) |
| wave2 | 1 | D | src `atomic_prepare_capacity_read_local`: same size and call targets as f821104a9 (a discarded COMDAT copy) |

**The 23 hot composites** ([composites.json](docs/wave3/identity/composites.json)). Every one is a
`parse_and_dispatch`/`r7_parse_and_dispatch` body that respresume (parser window) and mkfix2 A
(completed-tag test) both edit.

| How it decomposes | Bodies |
|---|---:|
| Exactly respresume's own body (mkfix2's change to that clone is code generation only) | 3 |
| Exactly W + both lanes' edit scripts | 2 |
| Additive modulo register allocation | 1 |
| Call structure additive (M = R + K - W) and both lanes' marker instructions present: respresume's `Client+0x4c` pending test and `Client+0x60` frontier lea, and mkfix2's `and $0xfffffffb` / `cmp $0xfffffffa` | 14 |
| Both markers present, with one small helper inlined differently than in the lanes' builds (db0 reorder `r7_parse_and_dispatch<false,32u,false>`: `RespFrontier::finish` inlined, one `Rob::mark_current_write` out of line; src rl2s `<true,32u,false>.isra`: `ThreadCtx::note_command` inlined; `<true,32u,true>`: `mark_current_write` and `Rob::publish` inlined) | 3 |

None contains an `__assert_fail`, so no `__LINE__` shift can hide in them. Across all 629 changed
bodies, no difference traces to a line-number immediate.

### Binary

| Arm | Path | SHA-256 |
|---|---|---|
| Integrated: `src/` and `Makefile` as of `55527432b`, unchanged since (`f12ee5762` touches only `tests/gate.sh`) | `/home/user/Projects/cx-wave3/build/tomokv` | `07cda1d99e708ecd9b76edec6b677c14c26d3109a7059dc44bec41b01a6909d1` |
| PRE, f821104a9 from `git archive` | `/home/user/Projects/cx-wave3/build/wave3/refs/pre-src/build/tomokv` | `d51fa1883cc04d411a2ce7a168c870a04be906fc8f40fc9fb632a8b7f20364d0` (runtime sections = `bench-bins/tomokv-headline-f821104a9`) |
| Option 1 scratch: decision 1's patch on this branch (not a candidate until budgets are re-checked) | `/home/user/Projects/cx-wave3/build/wave3/opt-r7/build/tomokv` | `6db3322729601f1b53ece9ddd8a97a3ef1e642e15ad0886ba1c2dd277cd01196` |

### Carried open items from the lanes

None of these is a regression in this integration; each stands as its lane reported it.

| Lane | Open item |
|---|---|
| respresume | Findings F1-F6; F1-F4 are with the ntfix lane. epoll still fails the differential infofix suite (not in the uring-default gate differential) |
| rlfix | The strict local-GET byte-law note on `prepare_local_read` (the merit was accepted) |
| hexpread | `find_notify` may consider an expired foreign candidate for an `expired` notification (notification-only) |
| aoforder | The AOF is native TOMOAOF, not Redis RESP AOF. AOF-on cost cells need instrument support |
| mkfix2 B | Retains common arenas at each IO's peak; needs a long-run RSS plateau check |
| mkfix2 C | Reverted; with it, abandoned scatter prepares are back to AB's level |

### Addendum 2026-10-21: mainline decisions 1-2 applied

The mainline approved decisions 1 and 2 and left EXPECT and tailgen to the landing gate. Commits:
`7fa5cb0e0` (R7 envelope regenerated, the generator's output only), `5265b8968` (rltopo expects
RL4.3's local GET miss), `e454a79a6` (reorder.o budgets) and this report commit.

| Check on the final binary `build/tomokv` (SHA-256 `c3721065fc68d1777e63843583c5e509a673c4091c3c355e35e70718732e447a`) | Result |
|---|---|
| reorder.o budgets (the patch grows the units +82 / +80) | 171 compile-only trials (162 distinct values) vs the pre-regeneration cx-wave3 objects ([trials](docs/wave3/identity/budget-trials-r7), [tool](docs/wave3/tools/trial_r7.py)). Rule: no selected hot body may change, then fewest changed bodies. **src 147778** (147776-147779), **db0 148779** (148777-148780, `max-inline-insns-auto=14` kept) |
| Objects vs the pre-regeneration build | **109 of 111 identical**; only src/db0 reorder.o differ (4 / 6 bodies, [list](docs/wave3/identity/r7-round/objects-vs-pre-regeneration.txt)). **0 selected hot bodies changed.** Linked changes: `IoLoop::r7_ReadLocalDemotionPlan::prepare` in both namespaces (RL4.4's one-key DEL/UNLINK refinement on the R7 broad-write edge; src 6295 -> 6067 bytes, db0 6128 -> 6146), and GCC's new `read_local_commands_overlap(...) [clone .part.0]` that it calls (399 / 435 bytes). The other changed bodies are discarded COMDAT copies: reorder.o's non-R7 `ReadLocalDemotionPlan::prepare` (genthread.o's unchanged copy is linked), src `FlatStore::snapshot_prepare_write`, and db0 `snapshot_progress` / `budget_admit` / the `lb_scan_bucket_bytes` `scan_home` lambda (map check) |
| Gate jobs the patches touch, through `tests/gate.sh` (source build) | **52 ok, 0 FAIL** ([ledger](docs/wave3/r7-round/touched-jobs.ledger)). This covers the three R7 rows (`R7 generated envelope parity`, `writeback policy clauses ...`, `splitlocal template forwarding ...`), both `read-local topology demotion` rows, `R7 production engagement`, `R7 FIFO twin` (292/292), writeback paths, all 7 core_units rows, the bplus job's 8 rows (rlfix's 4 included), all 12 `RESP resumable` rows (the 1s ones boot R7) and the 16 reorder=1 feature cells |
| `tests/gates_test.py` | **66/66 OK** (+ nested 14/14) |
| Production-unit freshness | `make all` + 32 `job_production_units` targets + `mdbqsbr-live-arms`: **all `make -q` fresh**, 0 warnings ([status](docs/wave3/r7-round/production-units.status)) |
| Redis 7.4.10 differential: string hash list set zset stream multi, atomic 0/1 | split **56/56**; armed fused **58/58** (56 legs + both read-local witnesses); **0 differences**. Seeds were 7 19 20 23, because the unmodified `differ_gate.sh` refuses a proof without every permanent seed ([logs](docs/wave3/differ-r7)) |
| rlfix's witnesses on R7 (`--reorder 1`, atomic 0/1) | GET miss and one-key DEL **both pass**; before the regeneration the DEL witness failed ([receipts](docs/wave3/r7-round/rlfix-r7)) |
| rltopo PRE control | The updated unit **fails on f821104a9 and 991d48f65** (`exact final fallback reason`) and passes on this tree ([check](docs/wave3/r7-round/rltopo-pre-control.txt)) |

**Remaining FAIL rows.**
- Rows that depend on EXPECT, which the landing item sets to 664/681: the abba_selftest row
  (`ABBA comparison + saturation negative controls`) and the `PROGRAM-STATE` tally.
- `tailgen client-lb outstanding bound`: left to the full-box landing gate.
- Every other row: ok in the earlier full gate (07cda1d9), in the storage re-run, or in the 52-row
  re-run above on this binary. Rows unaffected by the patches were not re-run on c3721065, as scoped.

**Changed bodies vs f821104a9 (final binary).** 16,706 bodies; **636 changed**: A 585, B 41, C 5,
D 5 ([changed-bodies.tsv](docs/wave3/identity/changed-bodies.tsv)).

| Class | Count | Contents |
|---|---:|---|
| A | 585 | respresume 240, hexpread 219, aoforder 67, mkfix 44, rlfix 15 |
| B | 41 | the earlier 40, plus db0 `budget_admit` (a discarded copy) |
| C | 5 | all from the R7 regeneration: the two R7 demotion plans and the two `.part.0` clones (linked), and db0 `snapshot_progress` (discarded) |
| D | 5 | the two cold ones from before; reorder.o's two non-R7 demotion-plan copies and src `snapshot_prepare_write` (all discarded) |

- Bodies reaching the binary: 387 (A 353, B 29, C 4, D 1).
- **Selected hot bodies are unchanged from the report above:** 1,219 selected, 1,142 equal, 54
  lane-identical, 23 respresume+mkfix2 composites.
- `.text` 7,647,932 -> 7,730,145 bytes. Layout locks unchanged; R7 envelope parity current.
