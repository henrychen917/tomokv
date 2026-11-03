# Script, function-persistence and tracking release fixes

## scriptfix4

Base/PRE: `9d6ab5526f` (the wave-14 integration). Worktree/branch:
`/home/user/Projects/cx-scriptfix4`, `cx-scriptfix4`. No push. The final production
source is commit `af326b1cc0`; later commits contain only tests, tools and documentation.
Every POST receipt below uses the frozen POST arm. Builds, servers, oracles and tests ran
only on CPUs 87-99 (builds `-j13`) and ports 21200-21299, with `LC_ALL=C` on every boot.
No performance benchmark, load generator or full iteration was run. The oracle is Redis
7.4.10 at `/home/user/Projects/redis/src/redis-server`
(`ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`).

This lane continues the codex lane that stopped on a content-filter false positive. Its
WIP commit `216a414e45` held an unreviewed 4-line edit to the instruction-cap hook that
switched the tripping Lua thread to `LUA_MASKLINE`, as Redis's `luaMaskCountHook` does
after SCRIPT KILL. Review found it incomplete, and a throwaway build of exactly that edit
confirmed both gaps (`xpcall-handler-loop` and `error-handler-loop` hung; the stale
coroutine call returned the cap error instead of `[1, 125250]`): an xpcall message handler
invoked from inside the hook runs with hooks disabled, so a looping handler is still
unbounded; and a function-library coroutine keeps the line hook into later activations,
which then charged 1000 instructions per line. `1dc55f9de5` completes the edit.

### Mechanisms and witnesses

The witnesses are the auditors' round-5 probes (T1/T8b, T6 and codex T5, T31b, T6-T9,
T19-T21), promoted into `tests/scriptfix4.py` and widened here. Gate job `scriptfix4-<case>`
emits one row per mode and engine (1s/2s x io_uring/epoll), and every row first runs the
Redis 7.4 oracle on the same probe. PRE and PAD-A fail all 20 rows; POST passes all 20.

| Item | PRE witness (4 rows each) | POST (4 rows each) | Mechanism changed | Residual |
|---|---|---|---|---|
| 1 CC5.1 hang | The first TomoKV `EVAL` of `while true do pcall(function() while true do end end) end` never returns (3 s socket timeout); SIGTERM cannot stop the server, the harness SIGKILLs it | EVAL, EVALSHA, EVAL_RO, EVALSHA_RO, FCALL and FCALL_RO, plus 8 more catch forms (xpcall with a returning or a looping handler, `error()` under a looping handler, `coroutine.resume`, `coroutine.wrap` under pcall, pcall inside a coroutine, recursive pcall, a caught normal return) and a library coroutine that kept the capped activation's hook: each replies `-BUSY script exceeded the 100000 instruction limit`; `EVAL return 42` and a bounded 5,000-iteration loop still succeed; the stale coroutine resumes and returns `[1, 125250]` | `scripting.cc:481` `instruction_hook`: on trip, switch the tripping Lua thread to `LUA_MASKLINE` and raise on every later line, loop and call until the activation unwinds; drop the pending message handler (`:51`) so no xpcall handler runs with hooks disabled (luaD_pcall restores the enclosing one); only COUNT events charge; a line event in an untripped activation restores counting | SCRIPT KILL / FUNCTION KILL still answer NOTBUSY (68d-3, out of scope); a single long C library call is not interruptible, as in Redis. Redis 7.4 itself cannot stop the xpcall-handler form after SCRIPT KILL (oracle: SCRIPT KILL `+OK`, then PING times out) |
| 2 CC5.2 stale cache | 3/9 script forms deliver an invalidation (the three `_RO` forms); EVAL, EVALSHA, both `#!lua flags=no-writes` EVAL forms, FCALL and FCALL of a no-writes function deliver none. Round-5 T6: EVAL_RO with one key and one ARGV value enrolls both | 9/9 forms; writable `EVAL GET KEYS[1]` invalidates `[key]`; `EVAL_RO return 1` with a key and an ARGV value invalidates `[]`; identical to the oracle on every leg. Separate oracle probe: MULTI/EXEC with EVAL and with EVAL_RO, NOLOOP read-then-write and read-then-write are identical to Redis | `tracking.cc:206`: every script command registers its declared KEYS at dispatch (pending obligations and filter bits as for any read; nested commands may name only declared keys); `scripting.cc:763` marks each key a read-only nested command read, on the armed path every tracked activation takes; `tracking.cc:318` enrolls only those keys at retirement; ARGV never | A script that reads a key after its own write to it: TomoKV delivers one invalidation right after the reply and leaves the key unenrolled; Redis keeps it enrolled (frames after the script/after a later foreign write: Redis `[]`/`[key]`, TomoKV `[key]`/`[]`). Conservative: the client is told to drop the key. The skipped Redis Tcl test cannot be promoted: its first EVAL writes an undeclared key (68d-2) |
| 3 CC5.10 stale cache | 3/3 rounds per leg: the waking invalidation arrives, the later XADD sends none | 3/3 rounds per leg: the later XADD invalidates; the waking invalidation also arrived in every round, as Redis's park-time enrolment does. trackfix_order (DIFF-TRK-1), trackfix_accounting, trackorder, tracking_redirect, rootcompat tracking, pubtrackfix and clientcompat multi-tracking stay green | `blocking.inc:1049` calls `tracking.cc:136` `tracking_observe_wake` where the owner's readiness probe captures a parked XREAD's reply: a per-shard wake certificate for tracked stream reads, after sealing a complete single-owner waking batch (the waking command serves readers from its own handler, before its epilogue seals); retirement (`tracking.cc:314`) enrolls with it; the park-time minimum still decides the waking delivery | A reader woken by an EXEC or cross-owner atomic-group write, or by a plain write executed beside pending atomic records, keeps PRE behaviour (no re-enrolment; the waking invalidation follows the reply). Smallest follow-up: seal a decided EXEC/scatter batch's tracking certificate at its commit decision, before the participant sweep (a certificate-protocol change: owner decision) |
| 4 PS5.1 data loss | Late commands acknowledged then lost, of 12 per kind (1s-uring / 1s-epoll / 2s-uring / 2s-epoll): LOAD 11/11/9/9, LOAD REPLACE 12/10/7/9, DELETE 8/11/10/11, RESTORE 11/10/11/9, FLUSH 11/11/11/7: 199 of 240 | 0 of 240 acknowledged; restart keeps the anchor key and the pre-cut registry; the oracle acknowledges none. Refused-save round (the delayed call also fails with EIO): all 12 held loads complete once the save fails, and persist after a second stop | `snapshot.cc:507` takes a registry cut (`functions.cc:239`) under the registry lock immediately before the final shutdown save copies the registry; LOAD/DELETE/FLUSH/RESTORE meeting the cut (`:260`) wait without applying (`:314`; a fused thread keeps its own executor's capture moving); exit closes the connection unacknowledged; a failed save clears `shutdown_snapshot_active` and they apply. The cut names its snapshot epoch | None observed |
| 5 PS5.6 data loss | `rdb_changes_since_last_save` delta 0 for every mutation (7 of 12 steps expect 1); no scheduled save; restart loses the library | All 12 deltas equal Redis's `server.dirty` rule and the oracle's (LOAD, REPLACE, DELETE, RESTORE, REPLACE-RESTORE, FLUSH and empty FLUSH +1; refused LOAD/DELETE/RESTORE, DUMP, LIST 0); `save 1 1` saves; SIGKILL then restart returns `FCALL cronfn` = 777 | `functions.cc:306`: each successful registry command adds one change to shard 0's existing atomic save counter, after the registry change and therefore before any later change cut; `save_change_total()` and the inlined save schedule are unchanged | None |
| 6 PS5.3 verify | Not reproduced: 87/87 legs (72 certified TomoKV capture windows, 15 oracle legs) | 87/87 legs | None; the wave-14 witness row now also covers a new LOAD, DELETE, RESTORE and FLUSH in the held window, both modes, both engines, all three fsync policies, with restart replay. A throwaway twin with the pre-wave-14 capture order fails 10/10 sampled legs, all five kinds | None |

Receipts: `docs/scriptfix4/receipts/witness-pre.ledger`, `witness-pre-observations.json`,
`witness-pad-a.ledger`, `touched-post.ledger`, `ps53-capture-witness.json`.

### Validation

Touched jobs only, through `tests/gate.sh`'s partial-job interface (`GATE_ONLY_JOBS`,
`GATE_PROOF_NO_RATES=1`), 37 jobs (`docs/scriptfix4/receipts/touched-jobs.txt`): scripting
(scriptfix4 x5, scriptfix, scriptfix2, lualibs, rootcore eval, snapfix BGSAVE script),
xscript (`script_bounds`: xscript limit and window), functions (rootcore functions,
wave14_functions), tracking, trackorder, trackfix, blocking (blockfix4, blockfix2,
blockfix registry/mkstream/structure), streams (streamfix), AOF (aof-uring, aof-epoll),
snapshot (snapshot-uring/epoll, snapfix shutdown), shutdown and persistence (persistfix2
x4, persistfmt, dump_restore) and the Tcl job. Result on POST: **304 ok, 1 FAIL**. Each job
runs its own mode/engine matrix (for example 54 AOF rows per engine, 40 persistfmt rows,
48 scriptfix2 rows, 24 legs per blockfix2 case).

The one failure is `blockfix2 BLOCK-STREAM-REMOVED-NO-UNBLOCK`: 3 of its 24 legs, all
atomic 1, in the `DEL boundary other-owner` window (a deleted group's XREADGROUP waiter
received the recreated stream's entry instead of NOGROUP). It did not recur: the same row
passed on POST, PRE and PAD-A in a rerun, and 36/36 repeated atomic-1 legs passed on both PRE
and POST (it also passed in the broad run stopped at the maintainer's request, whose directory
was removed, so that run is not a receipt). That path (atomic cross-owner DEL against a
group waiter) never reaches code this lane changed: the only blocking edit is in the XREAD
branch, behind the tracking flag the test never sets. It is reported as an intermittent,
unattributed failure, not as passing evidence. Receipts: `blockfix2-*.ledger`, the failing
leg's log and `blockfix2-removed-atomic1-repeats.txt`.

The Tcl job passed both modes: 37 manifest files and 1,874 passing assertions per mode; the
5 "fail" entries per mode are the manifest's predeclared setup errors. New promotions: zero.
The only skipped Redis test aimed at these fixes ("Tracking only occurs for scripts when a
command calls a read-only command") was probed through the job's probe interface (three
attempts per mode): it fails at its first EVAL with "Script attempted to access an undeclared
key" (68d-2) before reaching the assertions CC5.2 fixed (`tcl-probe-attempts.txt`).

`tests/differ_gate.sh` with its standard seeds against POST, both engines and both target
geometries (split 6:2, and armed fused with `--read-local 1`): **1,882 comparisons, 0 failures**.
io_uring split 475/0 and epoll split 475/0 (47 suites x 5 seeds x atomic 0/1, the four MULTI
repetitions and mode equivalence); io_uring armed-fused 466/0 and epoll armed-fused 466/0 (46
suites, MULTI repetitions, read-local lane fired at atomic 0 and 1). Seeds 7, 19, 20, 23 plus the
rotating seed (21, 22, 24, 25). Command coverage: 232 of 245 registered commands compared.
Receipts: `docs/scriptfix4/receipts/differ-*.txt`.

`python3 tests/gates_test.py` (fixtures pinned to port 21270): **77 tests OK** in 178.5 s
(`receipts/gates_test.txt`), including the gateplan change below.

`make all` and every `job_production_units` target built through the job's prerequisite.
At the final tree, `make -q all` and `make -q` on each of the job's 55 unit targets return 0.
`make -q mdbqsbr-live-arms` also returned 0, before its two regenerable live-arm trees (1.8G)
were removed to keep `build/` at 15G; the production_units job rebuilds them. The PRE object
tree was removed for the same reason (the PRE and PAD-A binaries remain; building
`build/scriptfix4/pre-source` with `BUILD_ROOT=build/scriptfix4/pre` restores it for
`tools/scriptfix4_pad.py` and the PRE census).

Auditors' round-5 witnesses re-run on POST (copies retargeted to CPUs 87-99 and ports
21220-21299, otherwise unchanged; `receipts/round5-post/`):

| Witness | Round-5 result (headline) | POST |
|---|---|---|
| T1 `probes.py hook`, 1s and 2s | EVAL and same-key GET time out, KILL = NOTBUSY, SIGKILL needed | EVAL replies the BUSY cap error, same-key GET answers, KILL = NOTBUSY (68d-3), SIGTERM stops the server (exit 0) |
| T8b `fcall_hang.py` | FCALL times out, FUNCTION KILL = NOTBUSY | FCALL replies the cap error, same-key GET answers, exit 0 |
| T6 `script_tracking_overreg.py` | Case A no invalidation; Case B key and ARGV | Case A `[key]`, Case B `[]`, both modes, equal to Redis |
| T5 `script_tracking.py` | writable forms not enrolled | 9/9 forms invalidated, both modes, equal to Redis |
| T31b `streams_track_blocked.py` | later XADD: no invalidation, 3/3 rounds | later XADD invalidates, 3/3 rounds, both modes, equal to Redis |
| T6/T7/T9 `audit.py shutdown_functions` | 9/9, 2/2, 8/8 acknowledged libraries lost | 0 acknowledged, 0 lost (window certified by the delayed fdatasync); the auditors' own assertion, which expects the loss, now fails |
| T8 (oracle) | none acknowledged | none acknowledged |
| T19/T21 `audit.py function_cron` | dirty 0, no scheduled save | dirty 1, rdb_saves 1 -> 2, 5 cron checks; the auditors' assertion "rdb_saves unchanged" now fails (restart recovery is covered by the scriptfix4 dirty row) |
| T20 (oracle) | dirty 1, save, 777 | unchanged |

### Cost and arms

`tools/scriptfix4_counts.py` drives the wave12/scriptfix3/clientcompat census engine
(`tools/wave12_counts.py`, ptrace tracer `tools/scriptfix3_trace.cc`) over
`tests/scriptfix4_scope.cc`, a serverless fixture linked from each arm's own production
objects that asserts exact replies. These are bounded instruction counts, not rates.

**Zero added instructions: 80/80 ordinary-command pairs equal.** GET, SET, INCR, MGET and
MSET at batch 1 and 32, 1s and 2s, atomic 0 and 1, normal and DB0 namespaces, in the
`complete` domain: every POST count equals PRE.

Warm activations (one warm-up, then one counted activation; `lua` domain, VM included; ranges
over 1s/2s and atomic 0/1). The plain body INCRs both declared keys; the `-header` body is a
no-writes script that GETs them. With tracking off, every delta is a few `luaH_get` table-probe
instructions (address dependent) and one vector destructor; no new code runs on that path.
With tracking on, POST does the enrolment PRE skipped (PRE enrolled nothing for writable
scripts): registering two declared keys and, for the GET body, enrolling both.

| Warm activation (2 declared keys) | Namespace | PRE, tracking off | POST - PRE, off | PRE, tracking on | POST - PRE, on |
|---|---|---:|---:|---:|---:|
| EVAL single shard | normal | 13,715-14,259 | -5..+5 | 15,176-15,715 | +2,024..+2,029 |
| EVAL single shard | db0 | 14,335-14,561 | -5..+5 | 15,668-15,889 | +2,032..+2,037 |
| EVAL single shard, GET body | normal | 11,596-12,140 | -5..0 | 12,351-12,895 | +2,853..+2,863 |
| EVAL single shard, GET body | db0 | 12,481-12,707 | 0..+5 | 13,164-13,385 | +2,878..+2,883 |
| EVALSHA single shard | normal | 13,538-14,082 | -5..0 | 14,977-15,521 | +2,019..+2,024 |
| EVALSHA single shard | db0 | 14,168-14,394 | -5..+5 | 15,479-15,705 | +2,027..+2,037 |
| EVALSHA single shard, GET body | normal | 11,424-11,963 | -5..+5 | 12,152-12,696 | +2,853..+2,858 |
| EVALSHA single shard, GET body | db0 | 12,314-12,540 | 0..+5 | 12,975-13,196 | +2,878..+2,883 |
| FCALL single shard | normal | 17,355-17,906 | -12..+7 | 18,796-19,335 | +2,012..+2,036 |
| FCALL single shard | db0 | 17,616-17,837 | 0..+5 | 18,929-19,150 | +2,032..+2,044 |
| FCALL single shard, GET body | normal | 11,711-12,250 | 0 | 12,446-12,990 | +2,853..+2,870 |
| FCALL single shard, GET body | db0 | 12,192-12,413 | 0..+12 | 12,855-13,088 | +2,866..+2,878 |
| EVAL cross owner | normal | 40,398-40,417 | -11..-1 | 42,128-42,149 | +2,150..+2,160 |
| EVAL cross owner | db0 | 38,729-38,746 | -13..0 | 40,348-40,360 | +2,161..+2,169 |
| EVAL cross owner, GET body | normal | 29,624-29,648 | -5..0 | 30,584-30,606 | +2,952..+2,962 |
| EVAL cross owner, GET body | db0 | 28,381-28,406 | -8..+5 | 29,282-29,307 | +2,969..+2,982 |
| EVALSHA cross owner | normal | 40,306-40,317 | -6..-1 | 42,014-42,030 | +2,150..+2,160 |
| EVALSHA cross owner | db0 | 38,637-38,649 | -3..0 | 40,239-40,249 | +2,156..+2,174 |
| EVALSHA cross owner, GET body | normal | 29,524-29,549 | -5..+5 | 30,465-30,489 | +2,952..+2,957 |
| EVALSHA cross owner, GET body | db0 | 28,289-28,312 | -8..+5 | 29,170-29,191 | +2,969..+2,977 |
| FCALL cross owner | normal | 44,188-44,204 | -6..+6 | 45,898-45,914 | +2,155..+2,167 |
| FCALL cross owner | db0 | 42,160-42,167 | -13..0 | 43,754-43,766 | +2,161..+2,181 |
| FCALL cross owner, GET body | normal | 29,880-29,904 | 0 | 30,820-30,854 | +2,945..+2,962 |
| FCALL cross owner, GET body | db0 | 28,233-28,253 | -8..+12 | 29,114-29,134 | +2,969..+2,977 |

All 272 pairs: `docs/scriptfix4/instructions/totals.json`; per-function deltas:
`instructions/comparison.json.xz`; per-case receipts (counts, logs, build and probe hashes):
`instruction-receipts.tar.xz`; the per-site traces stay in `build/scriptfix4/instructions-raw`
with their SHA-256 list in `instruction-sites.sha256`.

| Arm | Binary | SHA-256 | .text bytes |
|---|---|---|---:|
| PRE | `build/scriptfix4/PRE` | `ee4c28a56abdc852fa49701943649772d95d592fa1b46b10597d3b892bf5fe87` | 9,021,623 |
| POST | `build/scriptfix4/POST` | `851149ad447a35899f50ed3a56975f276e7bc31e8f4507ff6c6a3183b86d95a5` | 9,025,543 |
| PAD-A | `build/scriptfix4/PAD-A` | `91d96ba8caccbab980da794516ccccc23f452b796a768e01c7fcc592880cfc1a` | 9,025,543 |

PRE is built from the unmodified base source (`build/scriptfix4/pre-source`, identical to
`git archive 9d6ab5526`). POST is `build/tomokv` at `af326b1cc0`. `.data` (19,321), `.bss`
(1,189,384) and `.tbss` (768) are identical in all three. PAD-A is **(A) behaviour twin**:
the unmodified PRE objects linked with one padding function so its `.text` start and size
equal POST's (`tools/scriptfix4_pad.py`, `docs/scriptfix4/pad-a.json`). It controls total
text size only, not function placement. Its negative control holds: it fails all 20
witness rows.

### Maintainer measurements

Please run PRE, POST and PAD-A with the gate's own instrument on the quiet box: the 14 generic
cells (`docs/compat2/merit-cells.txt`), 2s GET and SET at p1 and p32, and the contended-script
storm, recording cycles/op, instructions/op and IPC for every arm. Rate at matched offered
load (or the cell's latency score) decides; PAD-A against PRE separates layout effects. This
lane makes no throughput claim. Tracking-on script costs above are the only intended additions.

### Gate arithmetic, harness changes and exclusions

DQ = +20, DF = +20: five `scriptfix4-*` jobs x four rows, collected at `tests/gate.sh:6482`,
before the quick-tier exit at `:6828`. The wave14_functions row is extended in place (DQ=DF=0).
`EXPECT_QUICK=1046` and `EXPECT_FULL=1063` are untouched. With wave 14's recorded census
(1090/1107), the maintainer's values become 1110/1127.

Harness changes: `tests/gateplan.py` lets a partial `GATE_ONLY_JOBS` correctness run use one
8-server + 2-load slot (10 cores); complete and performance gates keep the 16-core minimum.
New: `tests/scriptfix4.py` and its gate job, `tests/scriptfix4_scope.cc`,
`tools/scriptfix4_counts.py`, `tools/scriptfix4_pad.py`; `tests/wave14_functions.py` is extended.

### NOT RUN, with reasons

- Performance cells, load generators, ABBA and the full iteration: maintainer-owned (brief).
- A separate `GATE_NET_IO=epoll` pass of the touched jobs: the maintainer asked for the touched
  jobs only; jobs whose matrices declare both engines ran them (the scriptfix4 rows,
  wave14_functions, trackorder/trackfix legs, aof-epoll/aof-uring, snapshot-epoll/uring,
  blockfix2/blockfix4, scriptfix2, rootcore), and the differential ran on both engines. The
  Tcl job ran on the default engine only.
- The feature-split/feature-armed matrices (which also carry the xscript battery): not in the
  touched set; `script_bounds` covers the xscript limit and window controls. A broader 62-job
  run that included them was stopped at the maintainer's request after 51 jobs; its directory
  was removed, so none of its results are claimed.
- SCRIPT KILL / FUNCTION KILL and busy scripts (68d-3) and undeclared script keys (68d-2):
  out of scope. 68d-2 blocks the only candidate Tcl promotion for CC5.2.
- Additional observation, untested: the tracking table keeps one certificate per enrolled
  key, and a newer read of the same key replaces it. If a write lands between two reads and its
  invalidation reaches the owner only after the second read retires, the frame owed to the first
  read's cached reply is skipped; this matters only when the second read's reply does not
  refresh that cache (for example EXISTS after GET, or a script after GET). This lane did not
  build a witness for it; it applies to all reads and predates this lane.
- Throwaway builds used only as negative controls, never committed: the original WIP hook edit
  (CC5.1) and the pre-wave-14 capture order (PS5.3).
