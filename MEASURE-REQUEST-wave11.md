# Wave11 landing request

## wave11 integration

Integration on `cx-wave11`, from `e2b237926`, without pushing. Merged in order:
`cx-flipfix5`, `cx-scriptfix3`, `cx-climonfix5` (including climonfix4), and
`cx-flushmerit`, with separate no-fast-forward commits. The shared source cache
owns the original bytes, lowercase SHA, parsed flags and body offset. PAUSE
borrows cached flags on warm EVAL/EVALSHA; no-writes compiled closures use those
same flags. Persistent protected EVAL/FUNCTION interpreters and library
runtime environments survive the merge.

The source-declaration inventory is **977 quick / 994 full**, exactly +31/+31
from 946/963. All added collectors are before the quick-tier exit; see
[collector lines and labels](docs/wave11/row-inventory.json). The prepared [landing fixture](docs/wave11/landing-label-fixture.json) lists
every declaration. Its installation and the EXPECT repair are confined to a
throwaway copy for `abba_selftest`, as requested; the tracked fixture stays at
the headline until the maintainer lands the count update. `EXPECT_QUICK=946` and `EXPECT_FULL=963` remain untouched;
the maintainer must set 977/994 at landing. Tcl promotions are the union of
both histories; [reconciliation](docs/wave11/tcl-reconciliation.json) retains
all named compatibility skips without adding any.

No throughput claim is made. Performance loads and full iteration remain
maintainer-owned. The separate FLIP-EXEC-TRANSFER-TIMEOUT, flushfix2, execfifo,
rlfix4 and lineshare variants are outside this wave.

### Frozen arms and the cache integration

All production source and build flags in POST are at
`510e826117fc4d1d5a67ebef1dd011f686f74244`; subsequent commits contain evidence
and proof tooling. [Build receipt](docs/wave11/final-build.json).

| Arm | Path in this worktree | SHA-256 |
|---|---|---|
| PRE, rebuilt `e2b237926` | `build/wave11/tomokv-PRE` | `68c714d4059033b967dbd6d1fa8ce056e60b5988bdbf3c3f510c7f584b746edb` |
| POST | `build/wave11/tomokv-POST` | `8d9ec2439f25dbcf8e638d5d9eec1a612da96bd1b6265f33cf6e5f9d5c42cec9` |
| PAD-A | `build/wave11/tomokv-PAD-A` | `d101ece1fb44e1e9d232e50eafd2b879d2a795f34e3bf49fbd803d20e641b79b` |

**PAD-A is kind A, a behaviour twin:** headline behaviour with inert candidate
fields in ClientMeta, NotifyBatch, ClimonConn, ScriptContext and LuaEngine,
inert FUNCTION-engine and activation-slot TLS, and unreachable text padding.
POST and PAD-A have `.text` origin 182960 and size 8729431, and identical TLS
extent, alignment and every named TLS symbol coordinate. All eight locked
sizes pass in both namespaces in all three arms. Individual function offsets
and other data sections retain PRE placement; this control does not reproduce
every POST address. A real gain should move POST while PAD-A stays flat.
[Construction](docs/wave11/pad-a.json), [DWARF layouts](docs/wave11/layouts.json),
[TLS coordinates](docs/wave11/tls-layout.json).

The cache retains immutable source metadata. Compiled chunks use the metadata
pointer as their private Lua-table key; the interpreter retains shared owners
until its SCRIPT FLUSH reset, preventing address reuse for concurrent/private
cache entries. The cold compile helper builds a no-writes closure from the
same cached flags read by PAUSE. Its single body upvalue and a POD TLS pointer
to the persistent engine's current activation avoid a warm registry lookup.
FUNCTION has its separate persistent protected interpreter and library
environment. Cold reset work stays out of the warm interpreter lookup, and
normal-namespace Lua stack rotation keeps scriptfix3's inlining. Redis's bad
shebang grammar and error text are retained.

Directed extensions to existing rows cover writable/read-only alternation
under PAUSE, nested MONITOR records from EVAL and FUNCTION environments,
independent SCRIPT/FUNCTION FLUSH lifetimes, repeated compiled-cache retirement,
and command identity/close cleanup during a positively witnessed held FLIP stage.
The connection migration path extracts and installs the complete ClientMeta map
node, so the new command identity and PAUSE fields travel with it. The climon
merge retains wave10's tracking refresh together with monitor refresh during
the existing transfer. No shard-owner structure was moved independently.
The added/moved error sites use the central builders; see the wave11 supplement
in [the CRLF audit](docs/crlffix/audit.md) and its
[site inventory](docs/crlffix/wave11-added-sites.json).

### Instruction proof

The command census traverses the complete production call tree and counts the
selected namespace plus its C++ instantiations. It walks Lua callbacks rather
than skipping their nested command work. The supplementary Lua census also
counts VM internals. Fixture glue and external library bodies are excluded;
clocks are fixed and REP counts as one instruction. These are serverless
instruction counts, not cycles or rates.

| Scope | Cells | POST minus reference |
|---|---:|---:|
| GET, SET, INCR, MGET, MSET; batch 1/32, both modes and namespaces | 80 | **0** in every cell |
| Read-local GET, batch 1/32, both namespaces | 4 | **0** |
| EXEC, 1/2/4 INCR, same/cross shard, atomic 0/1, both modes/namespaces | 48 | −136 to −31 vs headline |
| Warm EVAL/EVALSHA/FCALL, plain/no-writes, same/cross shard | 96 | −39 to 0 vs scriptfix3 POST |
| Same scripting matrix through parser/dispatcher | 96 | −39 to 0 vs scriptfix3 POST |
| Session PING/WATCH/EXEC success/abort, batch 1/32 | 96 | −2176 to 0 vs headline |
| Warm scripting including Lua, matched pre-call collection | 96 | −381 to −7 vs scriptfix3 POST |
| FLIP idle / active stages | 20 | idle 0; active +15 to +19 vs headline, exactly flipfix5 POST |

One-child EXEC necessarily touches one shard; the two/four-child cross cases
span owners. In the Lua-inclusive census, both arms collect immediately before
the measured warm call and keep GC enabled during it. This controls bootstrap
GC debt without suppressing collection inside the call.
An earlier integer-registry trial (`a204da4a`, not the delivered POST) crossed
a GC boundary in the uncollected warmup fixture and counted +3308 Lua
instructions on FCALL. Its counts are retained in
`docs/wave11/archived-count-details.json.gz`. The final Lua-inclusive statement
is limited to the explicitly matched collection boundary above; arbitrary GC
phases are not claimed equal. The primary native census retains its original
warmup.

Unarmed PAUSE/MONITOR helper entries and warm SHA/header/compile-helper entries
are all zero. The only positive complete-scope deltas are the intended active
FLIP checks (`586b2304c`, with the off-by-default hook from `bec4a1e20`); there
is no positive integration residue. Signed per-function deltas are retained in
[instruction-functions.csv](docs/wave11/instruction-functions.csv), with every
cell in [instruction-cells.csv](docs/wave11/instruction-cells.csv) and
[the summary](docs/wave11/instruction-summary.json).

Every counted physical body and visited assembly instruction was bound to the
frozen POST; PRE probes also bind to the supplied headline, and scripting probes
bind to the supplied scriptfix3 POST. The supplemental Lua probe predates only
the INFO build metadata freeze; its counted bodies bind to the final POST too.
See `docs/wave11/binding-*.json`. No measured body was accepted on source
similarity alone.

### Compile-only budgets and linked bodies

All 31 per-unit pins were re-derived with compile-only trials. The linked
scoring used an immutable object base: 111 candidate records, 101 unique
linked scores; 13 initial canonical objects were already unchanged. Ten pins
changed; the other 21 remained after trials.

| Unit | Old | Selected |
|---|---:|---:|
| climon normal / db0 | 26419 / 26932 | 28716 / 29229 |
| t_server normal | 33142 | 33326 |
| xshard normal / db0 | 153471 / 152280 | 153728 / 152544 |
| acl db0 | 35705 | 35708 |
| genthread normal | 131260 | 131361 |
| fliplisten normal / db0 | 46744 / 46512 | 46749 / 46517 |
| reorder normal | 149153 | 149272 |

[Trial selection](docs/wave11/budgets/selected.json) records the compiler
commands, unit estimates, canonical object digests and all retained scores;
`docs/wave11/budgets/frozen-scores.json.gz` holds the linked trials.
The final strict inventory compares against all three supplied lane POSTs and
the supplied headline. It retains instruction widths, registers, immediates,
member offsets and local branches. Every remaining changed body is listed in
[changed-bodies.md](docs/wave11/identity/changed-bodies.md), with separate TLS
operand explanations and residual disassembly. Identity differences remain
visible for merit review; they are not converted into throughput conclusions.

Of 10208 function groups, 9467 are strictly unchanged, 286 match an isolated
lane POST, and 455 remain strict differences. The supplementary audit identifies
155 of those as direct TLS-address changes only. For the 86 GET/SET/MGET/MSET
hot-body groups, 74 match headline and one matches climonfix5; the remaining
eleven are two direct TLS relocations, five TLS relocations with the matching
base-address LEAs, and four generated CSWTCH symbol renames. The four lookup
tables have identical full bytes and instruction encodings; their ordinal
names remain visible in the strict inventory. See
[table-byte receipts](docs/wave11/identity/switch-tables.json). The TLS growth is
covered by PAD-A. Other remaining bodies retain their source origin and exact
nearest-reference diff rather than attributing a specific GCC decision without
evidence.

### Correctness receipts

The correctness campaign uses `GATE_ONLY_JOBS` whole jobs on the frozen POST,
with their declared legs intact, CPUs 64–95 and ports 20000–20099. Partial
receipts are indexed under `docs/wave11/jobs/`; none is a landing-gate pass.
Final coverage and any unresolved failures are recorded below when the campaign
finishes. No tracked EXPECT constant or label fixture has been repaired.

**NOT RUN (maintainer-owned performance work):** `flip_saturated` (memtier),
`atomic_floor` (throughput floor), `efficiency` (perf comparison), the inline
`tailgen client-lb outstanding bound` row (open-loop load generator and no
whole-job selector), atomic RYOW rate assertions (`GATE_PROOF_NO_RATES=1`,
permitted only for selected partial jobs), ABBA/NIC/EXEC/storm/flushmerit
performance loads, and full
`tests/gate.sh iteration`. The ABBA decision self-test and the flushmerit
instrument self-tests are correctness work and are recorded separately.

### Maintainer queue — NOT RUN here

Use the frozen arm hashes below, the gate's existing offered-load instrument,
acceptance rules and reviewed CPU geometry. Include contemporaneous identical-arm
nulls. Record rate at matched offered load, cycles/op, instructions/op, IPC and
latency; these serverless instruction counts do not decide throughput merit.
The deciding numbers remain each cell's declared rate/latency score against
the same-session reference, within the established null envelope, with zero
main-command regression. PAD-A must stay flat for a change to be attributed to
candidate behavior. Identical-arm scatter above 2% invalidates the run for
contention/defect investigation; it is not a wider acceptance band.

1. Wave null: merged POST against headline `e2b237926`, the unchanged
   [28 cells](docs/wave11/cells/null28.txt). Use **three blocks for p8g, h05 and
   h06**; retain the standing three-block notify_exm control and all remaining
   cell settings. Compare PRE/PAD-A as the labelled layout control.
2. Fixed-anchor race: POST against
   `/home/user/Projects/bench-bins/tomokv-headline-991d48f65`, the
   [generic fourteen](docs/wave11/cells/generic14.txt), the
   [nine read-local cells](docs/wave11/cells/readlocal9.txt), and the EXEC
   matrix below; retain three blocks and this comparison independently of the
   wave null.
3. EXEC: `/home/user/Projects/calib/exec-merit.py`, PRE/POST,
   `--conns 64 --threads 16 --cells all --blocks 3 --secs 20`.
   All eight `x{1,2}s_a{0,1}_{unc,hot}` cells keep pipeline 4, two INCR children,
   four competing plain writers in hot cells, databases=1, 1s read-local=1 with
   64 shards, and split ratio 6:2 with 16 shards. Preserve the driver's balancing
   and automatic-FLIP settings. Use one pinned benchtxn executable and record its
   SHA. Require zero order violations; retain EXEC and competing writes separately.
4. Contended-script storm: `/home/user/Projects/calib/script-storm-merit.py`,
   PRE/POST, `--blocks 3 --secs 30`. Preserve T6: 2s 6:2, 16 shards, atomic 0,
   databases=1, two keys on distinct owners, eight EVAL clients, four EXEC,
   four WATCH/EXEC and four plain writers. Require exact final values, zero
   script refusals and zero atomic-order violations; retain each class and
   WATCH aborts separately.
5. Landing gate: the maintainer applies **977/994** and the prepared label
   fixture, then runs `tests/gate.sh iteration`. No partial correctness receipt
   here is represented as that landing gate.

[Measurement inputs and anchor hashes](docs/wave11/measurement-inputs.json)
bind the cells and driver sources. The maintainer schedules the quiet box and
appends results as MEASURE-RESULT. No performance workload has been started by
this integration lane.
