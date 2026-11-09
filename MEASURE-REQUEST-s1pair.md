## s1pair

Two S1 fixes against `7595a6705a`, branch `cx-s1pair`, worktree `/home/user/Projects/cx-s1pair`.
No push. Every build, test and server ran on CPUs 20-55 with `LC_ALL=C`; ports 27200-27299.
This is a takeover after codex stopped on a content-filter flag (transcript
`scratchpad/evidence/s1pair-CODEX-OUT-filter-1053.md`); codex's commits were reviewed, kept where
correct and changed where not (details below).

### Summary

| Item | Reproduced on the release (`readability-pre-5c363128`, sha256 `0de6bbde…`) | Fixed on POST `fdc637ff` | Rows |
|---|---|---|---|
| FIX 1: legacy EVAL/EVALSHA OOM decided on every nested write (triage5 item 5) | **Yes**, 32/32 legs: RPOP/LPUSH script answers OOM and loses the element (`q` = `a b`, Redis: `c a b`); 16 x APPEND stops at 3 MiB with OOM (Redis completes 16 MiB); cross-owner scripts abort at APPLY with OOM | **Yes**, 32/32 legs, replies and keyspace equal to the Redis 7.4 oracle | `s1pair EVAL-ROTATE`, `s1pair EVAL-GROW`, `s1pair EVAL-ADMISSION` (all modes) |
| FIX 2: CONFIG SET owner refusal writes a second reply (triage6 item 1) | **Yes**, 32/32 legs: `CONFIG SET` answers `-LOADING`, the following `PING` receives a second `-LOADING` (desync) | **Yes**, 32/32 legs: exactly one reply, then `PONG`; a SET already applied by an earlier fragment answers `+OK` | `s1pair CONFIG-OWNER (all modes)` |

* Row delta: **+4 quick / +4 full** (all four rows are collected before the quick-tier exit), so
  EXPECT_QUICK 1212 -> 1216 and EXPECT_FULL 1229 -> 1233 relative to the base. EXPECT and the
  label fixture are untouched (maintainer-owned).
* GET/SET/MGET/MSET/INCR: all 142 main-command function groups are instruction-identical
  (release -> POST and PRE -> POST).
* The t_server.o inline budgets were re-derived (src 34174 -> 34338, db0 34348 -> 34515).
* WIP 4c4d1d9de9: **kept** (test-only, correct), then extended by f3808785a6.
* Merit arms: `s1pair-PRE-bd12fc84` and `s1pair-POST-fdc637ff` (table at the end).

### Commits (oldest first)

| Commit | Author | Content | Verdict |
|---|---|---|---|
| ec2d7fade9 | codex | rows `tests/s1pair.py`, gdb schedule `tests/s1pair_loading.py`, gate wiring, `tools/s1pair_identity.py` | kept; reviewed |
| c55ff882c7 | codex | FIX 1 (`src/cmd/scripting.cc`) | kept; correct (see FIX 1) |
| a6feb312b2 | codex | FIX 2 v1: every `collect_config_updates` error site through a deferred-error lambda | superseded by f9b98f3143 + 732c0eff67 (see FIX 2) |
| 4c4d1d9de9 | retry wrapper (WIP) | label `(Redis 7.4, all modes)` -> `(all modes)` (CONFIG-OWNER has no oracle), assert after logging both EVAL and EVALSHA, assert `loading_ == 0` at the IO check | **kept**; all three are correct test-only changes |
| f9b98f3143 | this lane | first owner fragment decides loading/RLIMIT for the whole SET | production |
| f3808785a6 | this lane | CONFIG-OWNER phase 2 (reload begins after the first fragment applied the SET) | test |
| 6d7d3d3f82 | this lane | xscript `maxmemory_pressure` and at412 T14 expect the start-time rule | test (expectation change, reasons below) |
| 732c0eff67 | this lane | FIX 2 final shape: private Op on the owner side, base `collect_config_updates` body | production |
| 807d67b349 | this lane | t_server.o budgets 34338 / 34515; `tools/s1pair_budgets.py` | Makefile + tool |
| 95d60b5101 | this lane | CONFIG-OWNER also asserts one LOADING errorstat | test |

The untracked `tools/s1pair_budgets.py` was needed (it is the reproducible budget scan the Makefile
comment cites), so it is committed (5.5 KB). It was rewritten to be self-contained: codex's version
compared against an unversioned `build/s1pair/pre-objects`, while this one compiles its PRE
reference from the base commit with the base Makefile's own command.

`src/` and the Makefile are identical from 807d67b349 to the branch tip (later commits touch tests and this report only).

### FIX 1: legacy EVAL/EVALSHA take the OOM decision once, at script start

| | Redis 7.4 | Release | POST |
|---|---|---|---|
| Start of an activation | `performEvictions()` then `pre_command_oom_state` (server.c:4030, :4052) | legacy EVAL: no start decision | every EVAL/EVALSHA: `FunctionMemoryScope::admit` = `budget_admit` on KEYS[1]'s owner under the live policy (evicts first) |
| Limit while the script runs | none (a script may overshoot) | legacy: the live per-shard cap, eviction suspended; `budget_admit` on every DenyOom call and `make_room_for` on every insert | cap lifted for every activation (as FUNCTION and shebang EVAL already were); eviction stays suspended |
| Nested DENYOOM command | refused only if OOM at start and no write yet (`scriptVerifyOOM`, script.c:438-458) | refused whenever the shard is over its slice | refused only if `oom_at_start && !write_dirty` |
| What marks the script dirty | every `CMD_WRITE` command that passed the check, before `call()`, even if it then errors (script.c:608-615) | n/a | every `CmdFlags::Write` command that passed the check, before its handler |
| Cross-owner APPLY | n/a (single thread) | legacy writes installed under the live cap: refusal aborts the whole script with OOM | every completed write carries `kScriptFunctionAdmitted`; APPLY groups only written keys, so every APPLY runs uncapped |

Why this is Redis 7.4 behaviour:

* `CmdFlags::Write` equals Redis's `write` metadata for every command a script can call. I compared
  every command row with `cmdmeta_generated.inc`: the only Write mismatches are EVAL/EVALSHA/FCALL
  (noscript) and the XGROUP container (CursorShard, refused inside scripts).
* FCALL is unchanged: it is still admitted at start (`reply_maxmemory_oom` without allow-oom/no-writes),
  its activation was already uncapped, and `oom_at_start` is false for it, so nothing inside a
  function is refused, as in Redis (`SCRIPT_ALLOW_OOM` or a start refusal). Shebang EVAL keeps its
  order: `*_ro` check, then admission, `allow-oom`/`no-writes` skip admission, and `no-writes` makes
  the activation read-only.
* The cross-owner workbench takes the same decision: `FunctionMemoryScope::admit` inspects the real
  owner of the workbench's shard id (KEYS[1]'s owner).
* There is no `mustObeyClient` to keep: the AOF journals script post-images, so scripts are never
  re-executed during load.
* Data-loss check: the RPOP/LPUSH rotate keeps `c a b` (also on a one-element list, where LPUSH
  recreates the key), and a pcall'd WRONGTYPE HDEL dirties the script like Redis.

Pre-existing deviations seen while reviewing (not changed; not S1; for the owner):

1. Shebang EVAL without `allow-oom`/`no-writes` over the limit answers `-OOM allow-oom flag is not
   set on the script, can not run it when used memory > 'maxmemory'`. Redis 7.4 rejects it earlier,
   in `processCommand` (`evalGetCommandFlags` makes it DENYOOM), with the standard
   `-OOM command not allowed when used memory > 'maxmemory'.`; FCALL already uses that text.
   EVAL-ADMISSION compares only the `-OOM ` prefix for this one case.
2. XSETID is DENYOOM in Redis but has no `DenyOom` flag here, so an over-limit script's first write
   XSETID is accepted (same on the release).
3. Shebang `allow-oom` scripts skip admission, so no pre-script eviction under `allkeys-*`.
4. The start decision is per shard ("KEYS[1]'s owner over its slice"), the documented per-shard
   threshold difference (docs/compat3/source-review.md:20). With `maxmemory 1` the release, POST and
   Redis refuse a script's first SET identically, also on an empty shard (probe run).
5. Comments now stale and left for the readability programme (rule: only changed lines):
   `scripting.h` "admitted FUNCTION=4" and "shebang EVAL uses FUNCTION-style OOM admission".

Existing-test expectations that encoded the release behaviour (commit 6d7d3d3f82):

* `tests/xscript.py maxmemory_pressure` (in `debug-0`/`debug-1`) asserted "cross-script APPLY OOM
  aborts atomically" for a legacy EVAL. Its filler fills KEYS[1]'s owner with inserts, which can
  never cross the slice (`make_room_for` projects), so the owner is full but not over it: the start
  decision admits the script, and it may overshoot like Redis. It now asserts three Redis rules on
  the cross-owner path: admitted at start completes past maxmemory (reply 1, both 8 KiB values, 0
  APPLY aborts); over the limit at start refuses the first DENYOOM write inside the script, with
  Redis's ` script: <sha>, on @user_script:1.` suffix, nothing written, 0 aborts; a non-DENYOOM
  first write (DEL) lets the later SETs run. The release fails all three (`aborts=+1` each), POST
  passes.
* `tests/at412.py` T14 expected one escalation for EVAL/EVALSHA ("meet maxmemory only at APPLY
  admission"). They now decide at script start like FCALL, so 0 escalations; the OOM text matches
  the oracle including the suffix, so the registered deviation XS-OOM-1 (round4-read/REGISTER.md:495,
  outside this worktree, not edited) no longer occurs. 24/24 legs + oracle pass.

### FIX 2: CONFIG SET owner refusal answers exactly once

Final design (t_server.cc):

* `collect_config_updates` keeps the base body. One added parameter, `environment` (default true),
  guards its two environmental re-checks: `appendonly` while `loading()`, and the maxclients
  RLIMIT_NOFILE check.
* `config_collect_owner` (owner side, under `ConfigLock`):
  1. a verdict with an error for this Op: return (another fragment refused);
  2. no scatter state (EXEC child or direct call, one fragment): collect directly, it replies itself (unchanged);
  3. scattered fragment: collect into a stack `Op` holding the same arguments, inside
     `ErrorStatsProbe` (errorstats are counted once, by the assembly's `reply_err`), and move the
     error text into the verdict. The unchanged assembly (`command_config_apply_reply`) replies the
     error once and suppresses `+OK`.
* First fragment decides: `config_apply_listeners` reserves the verdict before it applies
  listeners/AOF/locale. A later fragment that finds an empty verdict knows the SET was applied and
  re-runs collection with `environment=false`, so a reload that begins between fragments cannot
  turn an applied SET into an error.
* `config_reserve_result` is the one `push_back` site for both verdict writers.

| Path | Release | POST |
|---|---|---|
| IO validation refuses | one error | one error (same code path) |
| EXEC child / direct owner call refuses | one error | one error (same code path) |
| First scattered fragment refuses (reload already began) | every refusing fragment writes an error into the shared reply, then `+OK`: up to 17 frames | one error; later fragments return before collecting |
| Earlier fragment applied, later fragment sees the reload | `-LOADING` frames + `+OK` (and applied state) | `+OK`, applied (all fragments re-collect, 16 owner checks) |
| Apply failure (port/bind/AOF/locale) | one error (existing verdict) | unchanged |

Why codex's v1 (a6feb312b2) was replaced: it routed all 12 error sites through a deferred-error
lambda. It did produce one reply, but (a) a later fragment's loading re-check still turned an applied
SET into `-LOADING`: the AOF switch and shard 0's publication could already have happened, and the
codex variant relinked into the POST tree fails CONFIG-OWNER phase 2 (single `-LOADING`, 2 owner
checks); (b) the rewrite changed inlining in unrelated t_server.o bodies (cmd_info, cmd_client,
command_client_connected, command_client_slowlog_identity, flipctl_debug_dump), and no budget in
33800-35000 restored them.

Not chosen: keeping the re-checks on IO only. Enabling AOF (`runtime_enable`) while a DEBUG
RELOAD/LOADAOF is loading is exactly what the owner re-check prevents, so that is not provably
equivalent.

Residual (theoretical): a SET of only maxclients reserves no verdict, so an external `prlimit` that
lowers RLIMIT_NOFILE between two fragments of one such SET can still refuse a later fragment after
shard 0 published the value. The client still gets one reply and no desync.

### New rows (job `s1pair`, `tests/s1pair.py`)

Each row boots a fresh server per leg: `--shards 16`, {1s, 2s with `--ratio 6:2`} x {uring, epoll} x
atomic {0,1} x read-local {0,1} x databases {1,16} = 32 legs. The three EVAL rows first run the same
scripts on the Redis 7.4.10 oracle and require byte-equal replies and an equal keyspace image
(LRANGE / string length + sha256) for EVAL and EVALSHA.

| Row | Asserts | Release (gate-run.YfsdGs) | POST (gate-run.ccwwkM) |
|---|---|---|---|
| `s1pair EVAL-ROTATE (all modes)` | maxmemory 1, noeviction: the RPOP/LPUSH rotate on `[a,b,c]` and on `[c]`; a pcall'd WRONGTYPE HDEL, then LPUSH (a caught error still dirties) | **FAIL** 32/32: `-OOM … script: <sha>, on @user_script:1.` and `q` = `a b` | ok 32/32 |
| `s1pair EVAL-GROW (all modes)` | noeviction, start below the limit (Redis 8 MiB total; TomoKV 64 MiB = 4 MiB per shard), 16 x APPEND 1 MiB crosses it part-way: reply 16777216 and the 16 MiB value | **FAIL** 32/32: OOM with 3 MiB written | ok 32/32 |
| `s1pair EVAL-ADMISSION (all modes)` | maxmemory 1: first DENYOOM write refused (also after a read) with Redis's exact frame (via pcall); refused writes do not dirty, a later RPOP does and unlocks LPUSH; shebang none/allow-oom/no-writes and FCALL none/allow-oom/no-writes vs Redis | **FAIL** 32/32 at the refused-then-rotate script (element lost). The pure first-write refusals match Redis on the release as well (triage5 case D) | ok 32/32 |
| `s1pair CONFIG-OWNER (all modes)` | gdb schedule (`tests/s1pair_loading.py`) on the unmodified ELF, phase 1: loading before every owner re-check: one `-LOADING`, PING -> PONG, `slowlog-max-len` unchanged, `errorstat_LOADING:count=1`. Phase 2: loading only after the first owner fragment: `+OK`, PONG, value applied, 16 owner checks, count still 1 | **FAIL** 32/32 phase 1: the PING receives a second `-LOADING` | ok 32/32 |

* Negative control for phase 2: codex's v1 `t_server.cc` (a6feb312b2) relinked into the POST tree
  passes phase 1 and fails phase 2 in every leg (`-LOADING` for an applied SET, 2 owner checks).
* No test-only hook exists in the production binary: `git diff 7595a6705a..HEAD -- src` is the two
  fixes only, and the CONFIG schedule is an external gdb script (breakpoints on
  `collect_config_updates` / `command_config_apply_reply`, a write of `Server::loading_` while all
  threads are stopped). There is therefore nothing for `calib/binary-neutral.sh` to compile out; it
  was used on the arms instead (next section).
* Row delta **+4 quick / +4 full**. The label-fixture unittest
  (`tests/gate_ledger_fixture.py --self-test`) refuses exactly these four labels ("source
  declarations=1233", fixture 1229); its control `test_future_loop_row_names_missing_label` fails
  for the same reason (the four labels sort before its injected one).

### Binary identity and inline budgets

`tools/s1pair_identity.py` (gate normalizer `tests/reorder_noop.py`, literal pools resolved):
release -> POST arm and PRE arm -> POST arm both compare 11294 function groups, **54 changed**;
**all 142 GET/SET/MGET/MSET/INCR groups are instruction-identical** (cmd_get/set/incr/decr variants,
cmd_set_prebuilt, cmd_get_tls, the xshard MGET/MSET scatter engine, prepare_captured_local_mget).
Apart from the INFO git sha text (info_stats.o), no function outside t_server.o and scripting.o
changed.

| Changed group | Functions (src and db0 unless noted) |
|---|---|
| CONFIG, t_server.o | cmd_config (+cold), collect_config_updates (+clone), config_collect_owner (new), config_reserve_result (new), command_validate_config_set, cfg_client_output_buffer_limit_string |
| scripting, scripting.o | run_eval (both instantiations), redis_dispatch, script_execute, script_nested_notified, script_pcall_library, open_helper_libraries (src), redis_sha1hex (src), validate_source (db0) |
| INFO text only | info_stats_build_fields: only the rodata address/content of the INFO git sha string |
| other | **db0 `Server::flipctl_debug_dump`** (DEBUG FLIPCTL text; a server.h inline emitted only by t_server.o). The IPA inline dump shows the same inlining decisions in another order (equal-badness tie order), so registers and stack frame differ. It changed at every scanned db0 budget and in every source variant tried |
| other | src `kvobj_external_bytes<false> [clone .isra.0]` local to scripting.o: **0 callers** in both the release and the POST binary (only scripting.o's COMDAT copies call it, and the linker keeps main.o's copies) |

Budgets: with `inline-unit-growth=0` the `large-unit-insns` value is an absolute unit cap, and the
CONFIG change grows both t_server.o units by about 205 GCC size units. `tools/s1pair_budgets.py`
compiles the base unit with the base Makefile's command and each candidate with -g0, then compares
every body (`tools/archive/tools/ccfix4_budget.py`).

* src t_server.o, scan 34250-34600: the best budgets (14 changed bodies; the only non-CONFIG bodies
  are the weak `kvobj_external_bytes<true>` and `FlatStore::read_local_reclaim_object` copies,
  discarded at link) form the runs 34330-34332, 34337-34339, 34345-34347, 34354-34356, 34362-34364.
  **34338** (was 34174).
* db0 t_server.o, scan 34400-34750: best runs 34513-34517, 34521-34524, 34528-34531 (flipctl plus
  one discarded weak copy). **34515** (was 34348).
* scripting.o (10013 / 10020) does not bind: both values are below the unit's initial size, so GCC's
  cap is 1.4 x initial. They are unchanged.
* For comparison, codex's v1 shape (with the `environment` flag) left at best 6 (src) / 7 (db0)
  non-CONFIG bodies at object level anywhere in 33800-35000. Removing flipctl was tried and failed
  with: helpers inlined, no `environment` parameter, helpers at the end of the namespace, and a
  `cold` helper.

### Merit arms (owner runs; no performance claim here)

| Arm | Path | SHA-256 | Source / INFO |
|---|---|---|---|
| PRE | `/home/user/Projects/bins/s1pair-PRE-bd12fc84` | `bd12fc848944b9da9a30b063f4cf9ca2e8f18ba6309a667122e04b14cc28c6e0` | base 7595a6705a, clean, `make -B all` in this worktree (INFO 7595a670/0); reproduces codex's earlier PRE bit for bit |
| POST | `/home/user/Projects/bins/s1pair-POST-fdc637ff` | `fdc637fff14543427ef67ebd7e7b3be35dd2b4e24a2906fffd33d10cbd1cb0ca` | 807d67b349, clean, `make -B all` (INFO 807d67b3/0); same src/Makefile as the tip |
| release negative control | `/home/user/Projects/bins/readability-pre-5c363128/tomokv` | `0de6bbdea50caf4f90f797c4e52a4e86be30e2c554fb544f257f5148bf4016cd` | 5c363128 |

* `calib/binary-neutral.sh` release vs PRE: only `.rodata` differs, and only in the 16 bytes of the
  INFO `redis_git_sha1` text (5c363128 -> 7595a670, both namespaces). Codex's PRE built with
  `TOMO_INFO_GIT_SHA1=5c363128` (`s1pair-PRE-f14afc2d`) was IDENTICAL to the release; I removed it
  from bins/ so that `s1pair-PRE-*` names one arm.
* POST arm vs the identity-audited dev build: only `.rodata`, 14 bytes of INFO sha/dirty text.
* Suggested measurement: the gate's matched-load ABBA cells for GET, SET, MGET, MSET and INCR in 1s
  and 2s at the standard 16-shard geometry, PRE vs POST. CONFIG SET is cold. EVAL/EVALSHA now make
  one `budget_admit` call per activation (one predicted branch with maxmemory 0) instead of one per
  nested DenyOom command, so an EVALSHA cell is optional.

### Other required checks

| Check | Result |
|---|---|
| `make -q` after `make all` (POST tip) | rc 0 |
| `python3 tests/gates_test.py` | OK (14 + 83 tests) |
| label fixture unittest | refuses exactly the 4 new labels (above) |
| build warnings in the two changed files | none |

### Existing rows through the gate job interface (POST arm; stopped early on request)

One partial run (`tests/gate.sh quick`, `GATE_ONLY_JOBS`, `GATE_PROOF_NO_RATES=1`, server 20-43, load
44-49, `build/gate-run.xp9JAs`) was stopped at 12:54 when the coordinator reclaimed the machine.
Every job that finished passed, with no FAIL and no SKIP:

| Finished, all rows ok | Rows |
|---|---|
| cfgfix, cfgfix2-acl/-auth/-file/-latency/-maxmemory | 6 |
| climonfix4-1s-uring/-1s-epoll/-2s-uring/-2s-epoll (MONITOR inside scripts) | 28 |
| config_unit, datafix1_locale, maxmemrace, storefix5, txnfix4-oom | 7 |
| rootcore-eval, rootcore-functions, wave14_functions | 3 |
| scriptfix4-cap/-tracking/-blocked | 12 |

Run directly, not through the gate job interface (POST passes, release fails where noted):
xscript `all` battery (the `debug-*` battery) on POST (passes) and on the release (fails the three
new cross-owner checks); at412 T14 (24 legs + oracle, passes).

### NOT RUN / remaining

1. **Existing rows not finished** (stopped, or never started): cfgfix2-shutdown and
   scriptfix4-shutdown (interrupted), scriptfix4-dirty, scriptfix, scriptfix2, script_bounds
   (xscript limit/window), lualibs, compat3, debug-0, debug-1 (through the gate), at412-T1..T16,
   T11a, T11b and owner (through the gate), parkwake-script-2s-{uring,epoll},
   snapfix_bgsave_script, feature-split-{0,1}, feature-armed-{0,1}, persistfix2_commands,
   persistfix2_errors, notify, crlffix, evict-{lruclock,lfu}-{split,armed}-{0,1}, netfix_config,
   serverfix_config, wave15_rebind, fliplisten, aof-epoll, aof-uring, latencyfix_grammar. The
   prepared command is `scratchpad/s1pair/run_existing.sh`.
2. **The `s1pair` job after 95d60b5101.** The gate runs above (release 4 FAIL in
   `build/gate-run.YfsdGs`, POST 4 ok in `build/gate-run.ccwwkM`) used the rows as of 807d67b349.
   The added errorstats assertion passed 32/32 in a direct POST run (CPUs 50-55, ratio 4:2), not
   through the gate, and was not run on the release. The prepared command is
   `scratchpad/s1pair/run_final.sh`.
3. The Redis 7.4 differential matrix (`differ-split`, `differ-armed`; full tier) was not run.
   The prepared command is in `run_final.sh`.
4. Not run by rule: throughput benchmarks, ABBA, the full gate iteration. EXPECT_QUICK/EXPECT_FULL
   (+4/+4) and the label fixture (+4 labels) are for the maintainer.
5. No dedicated row for triage5 case C (allkeys-lru full cache: the script now evicts at start and
   then runs uncapped, like Redis); it shares the mechanism the three EVAL rows test.

### s1pair-land

Paper-build integration base: `origin/cpp` = `79ce7ee1320f48b26f0979a0ad3893cbc4e84843`.
Fetched and merged (never rebased) into `cx-s1pair` from `829755960348`; the merge applied
without conflicts. Both sides' gate rows and the paper build's comments are retained. The
production diff against the paper build remains only the two existing S1 fixes in
`src/cmd/scripting.cc` and `src/cmd/t_server.cc`. No new production behaviour.
All builds and correctness processes use CPUs 96-111, reserved ports 26300-26499 and
`LC_ALL=C`; no throughput benchmark, ABBA, NIC or complete gate iteration is run.

Compiler budgets were re-derived against the actual paper-build source and its own Makefile
commands with `tools/s1pair_land_budgets.py` (GCC 13, `-g0` for compile-only trials).
`docs/s1pair-land/budget-inventory.json` inventories **all 59 pinned rows**: preprocessed code
and flags (apart from the cap itself) are identical for 55, so their paper-build caps remain.
All four changed units and both xshard units were freshly compiled with IPA inline dumps and
compared using s1pair's full-body comparator (`ccfix4_budget`). Full trial evidence is in
`docs/s1pair-land/budget-trials.json`.

| Unit | Paper PRE initial IPA size -> merged | PRE budget -> merged | Decision |
|---|---|---|---|
| src t_server.o | 28799 -> 29005 (+206) | 34174 -> **34338** | Reconfirmed 34337/34338/34339: 14 changed bodies; only CONFIG plus discarded weak helpers. Old cap changes 21 bodies; additive 34380 changes 17 and disturbs INFO. |
| db0 t_server.o | 28515 -> 28718 (+203) | 34348 -> **34515** | Reconfirmed 34514/34515/34516: 14 changed bodies, including the previously disclosed cold flipctl helper. Old cap changes 19; additive 34551 changes 15. |
| src scripting.o | 37509 -> 37475 (-34) | **10013 unchanged** | Cap is below initial size and nonbinding; scripting changes plus weak/dead helper copies. |
| db0 scripting.o | 16249 -> 16215 (-34) | **10020 unchanged** | Same nonbinding cap; only scripting bodies change. |
| src xshard.o | 137420 -> 137420 | **168498 unchanged** | Every object function identical to paper PRE. |
| db0 xshard.o | 137125 -> 137125 | **171965 unchanged** | Every object function identical to paper PRE. |

Relative to the old s1pair branch, the only changed budget values are xshard's
168538 -> 168498 and 172012 -> 171965: aofblock adds 16 IPA units and blockrace removes
56 / 63, respectively. The merged paper build also contains tornhold; freshly measured
sizes above, rather than the old blockrace sizes, are the reference. No other pin needs a
new value. The two t_server pins remain s1pair's previously selected values after the new
paper-build comparisons.

R7 envelopes were regenerated with `python3 tests/r7shadow_sync.py --write`; the subsequent
check passes and regeneration introduces no difference from the merged paper envelopes.

Maintainer-owned tally/fixture: **+4 quick / +4 full**. The four s1pair rows are collected
at `collect_job s1pair` before the quick-tier exit. Keep the paper values 1325 / 1342 in
this branch; landing values should be **1329 / 1346**. The label-fixture unittest fails
with exactly these four missing labels (12 tests, one failure and one error); paper PRE's
unmodified fixture unittest passes. No fixture or EXPECT edit was made.

Correctness proof so far:

- `python3 tests/gates_test.py`: **14/14 + 83/83 pass**, 312 seconds for the outer suite.
- PRE `s1pair` through the current merged `tests/gate.sh` job interface, including commit
  95d60b5101's errorstats assertion: **four FAIL rows, 32/32 failing legs per row**, exactly
  the expected lost-element / partial APPEND / refused-then-rotate / second LOADING failures.
  The CONFIG negative stops at the wrong PING reply before its later errorstats assertion.
  Run `build/gate-run.YGlbzS`; the separate release prerequisite passed. Per-leg receipts are
  retained in `docs/s1pair-land/pre-s1pair-results.json`.

Build proof before the merge commit: paper PRE and merged POST `make all` both pass;
`make -q all` returns **0** on each. No new compiler warnings relative to paper PRE.
The two production files have no new warning. Commands and logs are retained under
`docs/s1pair-land/` (POST rebuild on CPUs 106-111 with `make -j6`).

POST runtime and symbol proof follows.
