# Lua helper compatibility — CC4.7

## lualibs

Lane `cx-lualibs`, base `05a5e01a9d8f1236e11cdbe4f2f7d490eb40edba`.
No push. Implementation and directed proof are committed; the broader proof
results below are updated as their complete gate jobs finish.

**Implemented:** Redis 7.4.10's `cjson`, `cmsgpack`, `bit`, `struct`, and
`redis.sha1hex` in every lazily created executor Lua state, in both database
variants and both thread modes. The existing recursive read-only protection
freezes the exported tables. `cjson.new()` creates a mutable, independent
instance; the singleton's C-backed configuration methods remain callable.
FUNCTION callbacks see the helpers, while FUNCTION LOAD registration bodies
cannot access them, matching the oracle. Registration temporarily hides and
then restores the four globals on both success and error. No main command,
locked layout, ownership, read-local or per-operation synchronization mechanism changes.

EVAL and FUNCTION use independent CJSON configuration objects, matching Redis's
separate engines. SCRIPT FLUSH resets only EVAL configuration; FUNCTION FLUSH
SYNC/ASYNC resets only FUNCTION configuration. The function flush epoch is
captured with the library snapshot under its existing mutex, including a flush
followed immediately by a new LOAD. LOAD/DELETE/RESTORE do not reset settings.
The directed battery caught the initial shared-configuration defect; its
[reproduction](docs/lualibs/cjson-state-repro.tar.gz) is retained. Configuration
remains local to each executor Lua state, as with the existing interpreter
architecture; cross-executor configuration propagation is not implemented.

The four helper implementations, strbuf and fpconv are imported with their
original notices; [LICENSES.md](docs/lualibs/LICENSES.md) records each file,
origin and original SHA-256. The Redis Solaris shim is not imported. The fpconv
locale is initialized with `pthread_once` so concurrent Lua-state creation
cannot race; conversion calls use the published immutable cache. No TLS is
added. SHA1 reuses TomoKV's existing implementation, with Redis's argument
coercion and error-table convention.

**Execution-policy limitation, explicitly retained:** TomoKV's existing
100,000-instruction limit aborts scripts; SCRIPT KILL and FUNCTION KILL always
answer NOTBUSY. It has no Redis-style `lua-time-limit` busy window. The helper
addition does not implement that separate execution-control mechanism. The
battery executes 240 loop controls per arm, spanning every helper, EVAL and
FCALL. POST proves the instruction hook still fires. The oracle proves its
busy window opened before accepting SCRIPT/FUNCTION KILL. These observations
are recorded separately from byte-equivalence assertions. Native helper calls
run to completion between VM hooks, as do Redis's native helpers; this is not
an elapsed-time bound on a single large C call. Full Redis scripting-control
compatibility is **not claimed**.

### Directed oracle and PRE proof

`tests/gate.sh` job `lualibs` owns the unchanged `compat3_case` lifetime matrix:
24 legs = databases {1,16} × atomic {0,1} × engine {epoll,uring} ×
{split/read-local 0, fused/read-local 0, fused/read-local 1}. Every boot has
16 shards and eight threads; split has ratio 6:2. A DEBUG topology witness
requires all two split or eight fused owners, and concurrent first EVAL calls
initialize every owner state. FUNCTION calls and post-SCRIPT-FLUSH calls cover
those same owners. No leg is skipped after a failure.

The [battery](tests/compat3_lualibs.py) contains 205 directed cases invoked
through both EVAL and FUNCTION callbacks: exported names, JSON empty tables,
null/boolean/binary/UTF-8/numbers, sparse arrays, depth 999/1000/1001, cycles,
NaN/Inf controls and number precision; MessagePack scalar/table types,
multiple returns and nil counts, string/array/map boundaries, depth truncation,
malformed input, offsets, limits and the C-stack return limit; every BitOp
function; struct endianness/alignment/integers/floats/strings/sizes/errors;
SHA1 binary/numeric/non-string arguments and arity; and direct/raw/metatable/C
mutator attempts against each protected table. It compares complete RESP
frames without normalizing errors. Logs retain byte lengths, SHA-256 and the
full small replies (long replies retain a prefix plus full-frame digest).

| Arm | Exact frame comparisons | Frame mismatches | Execution-control failures | Gate row |
|---|---:|---:|---:|---|
| PRE 05a5e01a9 | 10,992 | 10,416 | 240 (helpers absent) | FAIL in all 24 legs |
| POST | 10,992 | 0 | 0 | PASS in all 24 legs |
| PAD-A | 10,992 | 10,416 | 240 (helpers absent) | FAIL in all 24 legs |

[Directed summary](docs/lualibs/directed-summary.json),
[POST receipts](docs/lualibs/post-complete.tar.gz),
[PRE receipts](docs/lualibs/pre-complete.tar.gz),
[PAD-A receipts](docs/lualibs/pad-a-complete.tar.gz).
PRE and PAD-A return identical frames in every compared case in all 24 legs.
PRE's missing globals produce `Script attempted to access nonexistent global
variable 'cjson'` (likewise cmsgpack/bit/struct); sha1hex produces
`attempt to call field 'sha1hex' (a nil value)`. Redis returns the helper results.
The initial PRE reproduction and its source-time receipts are retained too.

The only new row is `lualibs CC4.7 vs Redis 7.4`. Its **collection line 5254**
is before the quick exit at **line 5351**, so **DQ=+1, DF=+1**. Maintainer-owned
EXPECT remains **768/785**; required counts are **769/786**. The label fixture
and source declare exactly the same 786-label multiset, including duplicates.
The fixture command correctly refuses the unchanged EXPECT_FULL=785;
[receipt](docs/lualibs/label-fixture.log). No EXPECT constant was edited.

### Broad correctness proof

`python3 tests/gates_test.py`: **72/72 PASS**, with the explicit fixture port
and port guard, after compilation finished. A concurrent-build attempt hit
eight scheduler-fixture 45-second timeouts; its failed receipt is retained as
`docs/lualibs/gates-test-contended.log.gz`, followed by the successful unchanged
[rerun](docs/lualibs/gates-test-quiet.log). No assertion or timeout was changed.
The label-fixture refusal above is separate and solely the maintainer EXPECT
count mismatch.

`make all` and every target listed by `job_production_units` built successfully.
Independent `make -q` checks report **45/45 fresh**: `all`, 42 unit/control
targets, and both underlying mdbqsbr live-arm build roots. The wrapper
`mdbqsbr-live-arms` is phony, so freshness is checked on its real outputs.
[Freshness receipt](docs/lualibs/production-freshness.json).

Complete gate jobs used the gate's own `GATE_ONLY_JOBS` interface, preserving
all their other controls and declared legs. These are row **executions**, not
new ledger rows; repeated mode passes include their release prerequisite.

| Whole-job invocation | POST passed / failed | PRE passed / failed |
|---|---:|---:|
| Four feature jobs, split debug 0/1, compat3, script_bounds, scriptfix, notify, notify_aof | 194 / 0 | 193 / 1 |
| Fused debug 0/1 + script_bounds | 35 / 0 | 35 / 0 |
| Additional atomic-0 script_bounds, split | 3 / 0 | 3 / 0 |
| Additional atomic-0 script_bounds, fused | 3 / 0 | 3 / 0 |
| AOF epoll + uring, split replay | 109 / 0 | 109 / 0 |
| AOF epoll + uring, fused replay | 109 / 0 | 109 / 0 |
| Initial total | **453 / 0** | **452 / 1** |
| Whole-job PRE feature-armed-1 rerun on fresh ports | — | **36 / 0** |

Every scripting, FUNCTION and script-atomicity row passed on both arms and
both thread modes, with atomic 0/1. All eight scriptatomic runs report zero
failures and **zero vacuous checks**. The AOF jobs include script-group logging,
DEBUG LOADAOF, process-restart script replay and their full recovery controls.
[Summary](docs/lualibs/regression-summary.json),
[POST receipts](docs/lualibs/post-regression.tar.gz),
[PRE receipts](docs/lualibs/pre-regression.tar.gz).

The sole initial failure was PRE's armed/fused atomic-1 `servertail` row:
its two nested boots hit `EADDRINUSE` on port 40822. No listener remained
when inspected, so the collision's source is not attributed. The corresponding
POST row passed. The original
[failure receipt](docs/lualibs/pre-servertail-bind-conflict.tar.gz) is retained;
the unchanged whole-job rerun on ports 40860-40869 passed. No assertion changed.

Commands are in [tools/lualibs_proof.sh](tools/lualibs_proof.sh). Final differential
execution uses its fixed copy `build/lualibs-proof-driver-final.sh`. Editing the
original recipe while its jobs invocation was active caused an unintended PRE
differential leg to start and overlap the end of AOF correctness. The queued
eight matrices then refused the occupied 40840/40841 ports. The original runner
and its owned descendants were stopped. These partial/guard-refused attempts
are **invalid and excluded**, with [receipts retained](docs/lualibs/invalid-differ-starts.tar.gz).
The full standard sequence is being rerun sequentially from the fixed driver;
its final results will replace this pending statement. No performance run
occurred. A partial gate is not a full-gate receipt.

The first corrected split/uring POST matrix then encountered nine `climon`
reader-control bind failures on port 40842; its summary also rejected the
missing comparison witnesses (466 passed, 10 failed). Those are setup errors,
not DIFF-TRK-1 reply differences. The allocated lane range lies inside this
host's ephemeral range, 32768-60999, with an empty reserved-port list. Concurrent
client sockets to other lanes were observed using nearby allocated ports as
source ports; ephemeral use is the inferred cause of these collisions.
[The local lease](docs/lualibs/port_guard/lease.py) holds non-listening
SO_REUSEADDR sockets for 40840-40842, preventing ephemeral allocation between
boots while allowing the real Redis/TomoKV/control listeners to bind normally.
Its listener compatibility was checked with a real command-byte exchange.
It changes no sysctl, comparison, deadline or protocol. The whole first matrix
is queued for a standard-seed rerun under this reservation; original failures
remain retained. The lease will be closed after verification.

PRE split/epoll's atomic-1 seed-7 PSFIX leg also refused a target SAVE reply:
`ERR Background save already in progress` after its both-peer idle barrier.
The test explicitly classifies this as a harness race and refuses comparison.
POST's matching full-matrix leg passed. A full PRE split/epoll rerun is queued
after the other matrices, preserving the preceding suites and accumulated
state as well as the same seeds. The original failure remains in the receipts;
no test, barrier or timeout is changed.


### Binary identity, size and per-state memory

Binaries: `build/tomokv-lualibs-pre`, `build/tomokv` (POST),
`build/tomokv-lualibs-pad-a`. [SHA-256 inventory](docs/lualibs/binaries.sha256)
includes the Redis 7.4.10 oracle. [Reproduction tool](tools/lualibs_artifacts.py)
builds the PAD-A and performs the serverless memory and identity audits.

**PAD-A is kind (A), a behaviour twin:** PRE helper availability with POST's
exact section sizes and symbol layout. Only the first byte of each namespace's
cold helper-registration seam is changed to x86 RET (two bytes total).
[Patch inventory](docs/lualibs/pad-a.json). Every other byte, including the
helper code, is retained. There is no production runtime selector.

The existing PSFIX relocation normalizer finds **74/74 GET/SET/MGET/MSET hot
object bodies identical**, including the actual xshard execution entry points.
The strict linked normalizer compares 9,432 groups and reports 470 changed or
added groups, with complete differences retained. Five hot groups differ only
in the rendered reference to three moved constant-pool values; their instruction
encodings apart from relocation fields are identical, and all referenced eight
bytes are identical. See [hot object audit](docs/lualibs/hot-identity.json),
[strict summary](docs/lualibs/identity.json),
[constant attribution](docs/lualibs/hot-literal-attribution.json), and
[all differences](docs/lualibs/linked-differences.json.gz).
The strict differences are not discarded or treated as a merit verdict.
All 22 audited type layouts, including both namespaces' eight required locks,
are byte/field identical to PRE: [layouts](docs/lualibs/layouts.json).

| Quantity | PRE | POST | Added |
|---|---:|---:|---:|
| ELF file, including debug data | 209,924,960 B | 210,118,280 B | 193,320 B |
| .text | 8,217,911 B | 8,247,031 B | 29,120 B |
| .rodata | 163,585 B | 167,394 B | 3,809 B |
| Fresh sandbox jemalloc allocation | 20,208 B | 32,256 B | 12,048 B/state |
| Retained allocation after full GC | 18,720 B | 30,944 B | 12,224 B/state |
| Lua GC-accounted bytes | 17,487 B | 26,805 B | 9,318 B/state |

[Memory census](docs/lualibs/memory.json) calls the actual sandbox constructors
with frozen PRE or POST scripting objects. The PRE harness has an unused weak
abort stub for the new FUNCTION helper-sync seam required by current linkage;
the constructor never calls it. Four repetitions in each database
variant agree; closing each state returns its entire allocation. Jemalloc's
net thread-allocation counter reports live size-class bytes, not RSS, and
includes both CJSON configurations and their malloc-backed buffers, which
Lua GC's count excludes. These are fresh-state costs before script/function
caches or user data; persistent JSON encoding buffers can grow with use. Unused
executors still allocate no Lua state. TLS sizes are unchanged. PAD-A has POST's
file/section sizes. [Section inventory](docs/lualibs/size.json).

### Maintainer merit request — generic 14 cells

Measure **PRE vs POST** and **PRE vs PAD-A (kind A behaviour twin)** using the
gate's own ABBA instrument on the quiet box, at the matched geometry/offered
load for these unchanged generic cells:

`h05 h06 p8g p8s d1g_l0 d1s_l0 m8g_l0 v1g_l0 d128g_l0 d32g_l1 d8s_l1 d32s_l1 x9_32_l1 x9_32_l0`

Record rate, cycles/op, instructions/op, IPC and depth-1 latency scores for
all arms and the null control. The per-cell deciding number is the existing
assessor's `margin_pct = loss_pct - threshold_pct`: require **margin <= 0**
with a valid, resolving comparison in every requested cell. Rate loss is the
negative paired percentage delta; latency loss is the positive delta. Retain
the instrument's recorded reference/null/read-local threshold and its source;
do not widen it for this lane. Report raw rates and latency scores even if the
instrument cannot resolve a verdict. Instructions and IPC explain the result.
PAD-A separates code placement effects from helper availability. Identity is a
proxy, merit decides. The current gate reports ABBA separately from its
correctness tally; this is the requested maintainer merit decision.
**No throughput or latency claim is made by this lane.** No PAD-B is supplied.

### Resources and exclusions

All builds use `taskset -c 48-63` and `-j16`. Gate targets use 48-55, clients
56-63; oracle processes remain within 48-63. Service ports are 40800-40899.
The lane-only Python port guard allocates disposable bind-zero fixtures from
40890-40898, with gates_test explicitly on 40899. It changes port allocation
only, not comparisons or deadlines. One early, superseded gates_test run used
its default ephemeral fixture listener port before this guard was enabled.
The later runs use the explicit allocation and guard. Generated persistence
payloads (about 4.8 GB) were removed after archiving logs, models, witnesses and
ledgers; their [size inventory](docs/lualibs/removed-persistence-payloads.json)
is retained. PRE keeps only its binary and six frozen objects; PAD-A is one
additional binary, without another full build tree.

**NOT RUN:** full `tests/gate.sh iteration`, performance benchmarks, load
generators for measurement, generic 14-cell ABBA merit and NIC performance
work — reserved to the maintainer. Correctness runs above use the explicit
runtime authorization. Remaining proof gaps, if any, will be listed with their
reasons before this lane is handed off.
