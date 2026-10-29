## scriptfix3

PRE is `e2b237926`; the instruction headline is `393d6ceb1`. Production changes end
at `6277e7313` on `cx-scriptfix3`. No push. **DQ=0, DF=0**: no gate rows or
`EXPECT_QUICK` / `EXPECT_FULL` constants changed. The original scriptfix2 battery,
Tcl manifest and assertions are unchanged.

All **192 scripting comparisons are at or below the headline**, and all **96 ordinary
command comparisons are exactly PRE**. These are serverless instruction counts within
the scopes described below, not throughput measurements. The final selected-job proof
has **775 passing POST row executions and zero failures**; PRE and PAD-A each pass
their nine-row behavior check.

### Production change

Immutable cached entries retain the original script, lowercase SHA, parsed flags and
body offset. Warm EVAL finds the original source without recomputing SHA-1 or parsing
the header. Warm EVALSHA finds its already cached spelling without normalization or a
source copy. A new mixed-case spelling is normalized and inserted once; aliases neither
inflate SCRIPT's script count nor survive SCRIPT FLUSH. A concurrent flush cannot make
an owner publish a source out of order: the fallback compiles private metadata only.
Hashing still uses the original bytes, including the header; retaining the header newline
preserves Redis's source line numbers and diagnostic SHA.

EVAL and FUNCTION receive separate lazy, persistent interpreters. Their protected
globals, blocked functions and redis API are selected once at interpreter creation.
FUNCTION library environments acquire immutable runtime globals once after registration
permissions are revoked. The mutable CJSON root continues to resolve through its VM so
FUNCTION FLUSH resets it correctly. SCRIPT FLUSH leaves function closures and helper
state alive. FCALL caches each normalized name spelling on first lookup and borrows the
registry-rooted registered name for diagnostics. Library revision sync discards aliases.

Call-dependent readonly, no-writes, allow-oom and memory-admission checks remain.
The numeric-argument lifetime fix, deep replies, API behavior, original errors and all
other implemented scriptfix2 behavior remain. The pre-existing compatibility boundaries
listed in `cx-scriptfix2:MEASURE-REQUEST-scriptfix2.md` are not expanded by this lane.
The cost moved to cold work is a second lazy VM on threads that use both APIs (and
its thread-local handle), immutable cache metadata/source indexes, and aliases for
observed SHA/function-name spellings.
No public configuration or locked object layout changes.

### Instruction evidence and attribution

[Full matrix](docs/scriptfix3/instructions/comparison.md),
[signed function comparisons](docs/scriptfix3/instructions/comparison.json),
[commit attribution](docs/scriptfix3/instructions/attribution.md), and
[all 480 signed commit/function decompositions](docs/scriptfix3/instructions/attribution.json)
retain both increases and decreases. The four scriptfix2 production commits are
`370210cfc`, `18191bcc1`, `6bc147d2c`, and `cdd2c4673`. Controls reverse these commits
while fixing other objects at e2b237926; an explicit integration bridge accounts for
headline-to-base changes. Two overlapping later cold LIST/LOAD diagnostic hunks are
held fixed in every control and recorded in `retained-cold-conflicts.json`.

Representative namespace counts, normal namespace, 1s, atomic=1, no header:

| Call | Headline | PRE | POST | POST − headline |
|---|---:|---:|---:|---:|
| EVAL, single shard | 19,693 | 20,379 | 4,209 | −15,484 |
| EVAL, cross shard | 10,349 | 10,632 | 5,196 | −5,153 |
| EVALSHA, single shard | 4,209 | 5,518 | 4,056 | −153 |
| EVALSHA, cross shard | 5,141 | 5,425 | 5,140 | −1 |
| FCALL, single shard | 3,923 | 4,093 | 3,823 | −100 |
| FCALL, cross shard | 5,106 | 5,104 | 5,098 | −8 |

The atomic=0 cross-shard EVAL reproduces the prompt's 10,351 → 10,634 (+283).
The db0 recount at e2b237926 is 19,169 → 19,834 (+665) for single-shard EVAL and
10,310 → 10,590 (+280) for atomic=0 cross-shard EVAL; the report uses these freshly
counted values rather than copying the earlier wave10 db0 deltas. The ordinary-command
headline-to-PRE changes, including db0 atomic=0 MSET's +1 per operation in 1s, predate
this lane: every POST ordinary count equals PRE, and every selected ordinary hot body
is unchanged.

The fixture warms each case once, validates exact replies, then counts the production
owner/dispatch and scatter path with no listener or worker threads. It uses 16 shards,
eight cores, split 6:2, and both compiled namespaces. The 96 scripting geometries are
EVAL/EVALSHA/FCALL × single/cross shard × header/plain × 1s/2s × atomic 0/1 × namespace.
EVAL/EVALSHA's header is plain `#!lua`, also accepted by the headline. FCALL necessarily
has a library shebang in both legs; the header-labelled FCALL leg adds the `allow-oom`
registration flag. GET/SET/INCR/MGET/MSET have 48 control geometries, including batches
1/32 and both atomic settings for MSET. Each geometry is counted in two scopes:

* **namespace** preserves wave10's method. It excludes Lua and skips fixture wrappers,
  so it also omits later scatter callbacks reached through those wrappers.
* **lua** traverses all in-image executable functions, including Lua and later scatter
  phases, while excluding the fixture's own instructions. This scope confirms the
  result across the complete production callback path that the narrow scope misses.

Both instruments count executed native instructions with ptrace, count REP once, fix
clock answers, and exclude shared-library internals. In particular, the source index's
standard-library hash body is outside the image, whereas the removed SHA-1 code was
inside it. These are matched command-scope counts, not a claim about every process-wide
retired instruction or cycles. Small address-dependent Lua table-probe deltas are
retained. No positive scripting residue remains in either measured scope.

`tools/scriptfix3_counts.py`, `tools/scriptfix3_attribution.py`,
`tools/scriptfix3_trace.cc`, and `tests/scriptfix3_scope.cc` reproduce the census.
Each arm retains its original build command, link order and binary/probe/tracer SHA.
Raw instruction visits are compressed under each arm's `traces.tar.gz`; their hashes
are in `docs/scriptfix3/instruction-archives.json`. Matching visited-site disassembly
is in `docs/scriptfix3/instruction-sites/`.

### Correctness proof

All work uses CPUs 32–47. Builds use `-j16`; gate jobs use server CPUs 32–39 and
load/oracle CPUs 40–47, ports 20300–20309, 16 shards and ratio 6:2. The oracle is
Redis 7.4.10, SHA-256 `ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`.
The additional oracle witnesses use ports 20320/20321; the gate self-tests use 20398.
`LC_ALL=C` is inherited by every server and oracle. Selected jobs use gate.sh's `GATE_ONLY_JOBS`
interface with `GATE_PROOF_NO_RATES=1`; no full iteration or performance job is selected.
The wrapper records argv, environment, binary hash, source state, exit and original ledger.

The [final verification receipt](docs/scriptfix3/proof.json) binds every run to its
unchanged delivered binary and rechecks source preservation and build freshness.
[Archived raw logs and inventories](docs/scriptfix3/proof-archives.json) retain every
selected job's exact arguments and assertions. These are repeated row executions,
including release-build checks, rather than a full-gate EXPECT tally.

| POST selection | Passed row executions | Failures |
|---|---:|---:|
| Main io_uring jobs | 249 | 0 |
| Main epoll jobs | 184 | 0 |
| Fused debug/bounds/notify, io_uring | 41 | 0 |
| Fused debug/bounds/notify, epoll | 41 | 0 |
| Atomic=0 bounds, both modes and engines | 12 | 0 |
| Script persistence, split boot | 139 | 0 |
| Script persistence, fused boot | 109 | 0 |
| **Total** | **775** | **0** |

The selections include `lua_scripting`, `scriptsurf`, `scriptatomic` and its strict
witness, `xscript`, SCRIPT bounds, FUNCTION flags, scriptfix/scriptfix2, Lua libraries,
notifications, replay and snapshot script paths. Debug and feature batteries cover
both atomic settings; the supplemental runs complete the fused/engine bounds matrix.
PRE and PAD-A separately pass all nine `scriptfix`/release rows each.

* Differential jobs: **all five parts pass on both io_uring and epoll**, 1,908 seeded
  suite/equivalence runs. Permanent seeds 7/19/20/23 plus rotating 21 (uring) and
  22 (epoll); stock fused SORT exclusion unchanged.
* Original scriptfix2 rows: **48/48 pass**, **192 geometry legs**, **3,584 exact wire
  comparisons**, zero differences. The gate and original battery files match PRE.
* `python3 tests/gates_test.py`: **73/73 pass**.
* Additional warm spelling/environment/flush oracle witnesses: **32/32 legs**, **1,360
  exact wire comparisons**, no differences; both modes, engines, namespaces and atomic settings.
* `make all` and every `job_production_units` target built; the closing verification
  confirms **56 make -q invocations pass**, including the recursive mdbqsbr alias and
  both extra makefiles.
* Final Tcl job: **37 files and 1,803 passed assertions per mode**, including 130 scripting
  and 86 FUNCTION assertions. Coverage follows the unchanged gate manifest. Each mode
  records 116 scripting skips and 14 FUNCTION skips, plus five exact approved setup
  exceptions: two unsupported DEBUG commands in scripting, two list-compression
  configuration failures and one immutable appendonly configuration failure.

Tcl assertions excluded by the existing manifest or upstream skip conditions are
**NOT RUN** for those existing compatibility reasons; no exclusions were added.
[Coverage limits and exact setup errors](docs/scriptfix3/tcl-coverage-limits.json)
record the counts and replies. Full per-test events remain in the raw archive.

The earlier candidate's compatibility run passed 65 rows and failed the fused Tcl row
on a `unit/tracking` timeout after ten assertions. This was not a scripting/FUNCTION
assertion failure. Its log and receipt are retained and do not count as final passes.
The final binary's complete Tcl job passed both modes. The manifest-owned exact setup
exceptions and assertion exclusions remain unchanged; no deadline or tolerance was widened.

[Layout proof](docs/scriptfix3/layouts.json) shows all eight locked sizes and all member
offsets identical in both namespaces. The object audit finds **1,591/1,591 ordinary hot
bodies identical** and 19,731/19,957 total bodies identical. Only scripting, functions and
INFO's Git identification objects change. The generic ccfix audit exits nonzero because
its allowlist excludes expected EVAL/FCALL/SCRIPT/FUNCTION changes; the raw rejection
and explicit scripting verdict are retained in `docs/scriptfix3/object-audit/`.

### Delivered arms

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE, e2b237926 | `build/scriptfix3/pre/tomokv` | `c9bbca0a9b578889f9d20514be543db45f2758e0cffa0ef726d6970d28b8d946` |
| POST, 6277e7313 production source | `build/scriptfix3/tomokv-post` | `d9f883e8babf349d9d7f3435bb0e27b0a2973cdd307fd67830923b18475abe01` |
| PAD-A, PRE behavior | `build/scriptfix3/tomokv-pad-a` | `b6f8cef931a3d68867b8dc5cd8458ae947f38e33d4c0da3eeaceec4659797e6f` |

`build/tomokv` is identical to delivered POST. PAD-A is **A: behaviour twin**, unmodified
PRE objects plus 18,912 unreachable padding bytes matching POST's `.text` address
182,960 and size 8,678,887. **It controls total text size/start, not exact function placement
or data layout.** Do not interpret it as eliminating every layout effect.
`tools/scriptfix3_pad.py` and `docs/scriptfix3/pad-a.json` record its construction.

Superseded arm trees/probes were removed after preserving hashes, counts and visited-site
disassembly (`pruned-arms.json`, `pruned-probes.json`). PRE objects remain available to
rebuild PAD-A. Archived persistence run directories were removed after every archived
file hash was verified. Final build usage is 17.0 GiB. All proof processes have exited,
and no listeners remain on the lane's ports 20300–20399.

### Maintainer measurement request — NOT RUN in this lane

Run `/home/user/Projects/calib/script-storm-merit.py` with POST as candidate and PRE
as reference, **`--blocks 3 --secs 30`**. Preserve its T6 shape: 2s, 6:2, 16 shards,
atomic=0, databases=1, two keys on distinct owners, eight EVAL clients, four EXEC
clients, four WATCH/EXEC clients and four plain writers. Require exact final data,
zero script refusals and zero atomic order violations. Successful scripts/s is the
storm verdict; retain EXEC/s, plain writes/s and WATCH aborts separately.

Run `/home/user/Projects/calib/exec-merit.py` POST/PRE with
`--conns 64 --threads 16 --cells all --blocks 3 --secs 20`, all eight cells:
`x1s_a0_unc,x1s_a0_hot,x1s_a1_unc,x1s_a1_hot,x2s_a0_unc,x2s_a0_hot,x2s_a1_unc,x2s_a1_hot`.
Keep pipeline=4, two children/transaction, four plain INCR writers on hot cells,
databases=1, 1s read-local=1/64 shards, and 2s ratio=6:2/16 shards. Keep the driver's
disabled balancing/automatic FLIP posture. Retain EXEC and competing plain-write
rates separately and require zero atomic order violations. Record the chosen
`--benchtxn` binary hash and use the same executable for both arms.

Run PRE/POST/PAD-A on the 18 rows in `docs/scriptfix3/merit-cells.txt`: the first
fourteen are exact copies of `docs/compat3/merit-cells.txt`, followed by four **null**
2s GET/SET p1/p32 rows with the corresponding generic row's client layout and score.
The generic IDs are
`h05 h06 p8g p8s d1g_l0 d1s_l0 m8g_l0 v1g_l0 d128g_l0 d32g_l1 d8s_l1 d32s_l1 x9_32_l1 x9_32_l0`.
The split controls are `scriptfix3_2s_get_p1`, `scriptfix3_2s_set_p1`,
`scriptfix3_2s_get_p32`, and `scriptfix3_2s_set_p32`; use eight server cores,
16 shards and ratio 6:2. Preserve each cell's rate/latency score and existing null rule.

The driver and cell-file hashes are in `docs/scriptfix3/measurement-inputs.json`.
The maintainer schedules the quiet box and supplies explicit server/load CPU masks,
owned port and distinct output directories; keep these identical across arms and
pin `LC_ALL=C` for every boot. These drivers were only read in this lane.

Use the gate's own matched-offered-load instrument on the quiet box; retain all
repetitions and per-cell rate, cycles/op, IPC and instructions/op. Rate at matched load
is the verdict under the gate's existing decision rule. Ordinary and EXEC cells are
regression controls; a PAD shift remains a layout confound. No throughput claim is made.
Performance benchmarks/load generators, the storm, ABBA and full `tests/gate.sh iteration`
are **NOT RUN**, as assigned to the maintainer.
