## scriptfix3

PRE is `e2b237926`; the instruction headline is `393d6ceb1`. Production changes end
at `6277e7313` on `cx-scriptfix3`. No push. **DQ=0, DF=0**: no gate rows or
`EXPECT_QUICK` / `EXPECT_FULL` constants changed. The original scriptfix2 battery,
Tcl manifest and assertions are unchanged.

All **192 scripting comparisons are at or below the headline**, and all **96 ordinary
command comparisons are exactly PRE**. These are serverless instruction counts within
the scopes described below, not throughput measurements. The main selected-job proof passes 249 rows; the remaining engine and persistence
receipts are still being collected.

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
`LC_ALL=C` is
inherited by every server and oracle. Selected jobs use gate.sh's `GATE_ONLY_JOBS`
interface with `GATE_PROOF_NO_RATES=1`; no full iteration or performance job is selected.
The wrapper records argv, environment, binary hash, source state, exit and original ledger.

* Main selected-job run: **249 passed rows, zero failures**. This includes all five
  io_uring differential parts and the full scripting/compatibility selection.
* Original scriptfix2 rows: **48/48 pass**, **192 geometry legs**, **3,584 exact wire
  comparisons**, zero differences. The gate and original battery files match PRE.
* `python3 tests/gates_test.py`: **73/73 pass**.
* Additional warm spelling/environment/flush oracle witnesses: **32/32 legs**, **1,360
  exact wire comparisons**, no differences; both modes, engines, namespaces and atomic settings.
* `make all` and every `job_production_units` target built; **56 make -q invocations
  pass**, including the recursive mdbqsbr alias and both extra makefiles.
* Final Tcl job: **37 files and 1,803 passed assertions per mode**, including 130 scripting
  and 86 FUNCTION assertions. Each mode retains five exact, manifest-approved setup
  exceptions (two in scripting). Remaining selected gate jobs are **PENDING**.

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
rebuild PAD-A. Current build usage is about 17 GiB.

### Maintainer measurement request — NOT RUN in this lane

Run the contended-script storm **POST versus PRE, three blocks**, at the existing
20-client/two-hot-key geometry with eight EVAL clients. Include the existing EXEC cells.
Run PRE/POST/PAD-A on all fourteen generic cells exactly as specified in
`docs/compat3/merit-cells.txt`:
`h05 h06 p8g p8s d1g_l0 d1s_l0 m8g_l0 v1g_l0 d128g_l0 d32g_l1 d8s_l1 d32s_l1 x9_32_l1 x9_32_l0`.
Add the four **null** 2s GET/SET cells at p1/p32, eight server cores, 16 shards, 6:2,
with the corresponding generic cell's matched client/offered-load geometry.

Use the gate's own matched-offered-load instrument on the quiet box; retain all
repetitions and per-cell rate, cycles/op, IPC and instructions/op. Rate at matched load
is the verdict under the gate's existing decision rule. Ordinary and EXEC cells are
regression controls; a PAD shift remains a layout confound. No throughput claim is made.
Performance benchmarks/load generators, the storm, ABBA and full `tests/gate.sh iteration`
are **NOT RUN**, as assigned to the maintainer.
