## scriptfix

Implemented CC4.3, CC4.25, CC4.27, and the CC4.6 reset fix. **CC4.6 is partial:
mutable function state still lives per executor.** The permitted owner-decision
fallback, including its FCALL cost estimate, is retained in
[single-state-design.md](docs/scriptfix/single-state-design.md).

**Landing still requires a quiet rerun of `tests/gates_test.py` and the owner
EXPECT update below.** The scheduler suite did not pass under shared CPU
contention; all three failures are retained. The Lua-specific checks, differential
proof, required builds and hot-body identity checks passed. The consolidated
receipt is [proof.json](docs/scriptfix/proof.json).

Worktree `/home/user/Projects/cx-scriptfix`, branch `cx-scriptfix`; no push.
PRE is `5146b78ee89b64748dd46db970efa8086f653fa0`, built with default production
flags into `build/scriptfix/pre/tomokv`; POST is `build/tomokv`. Fetching
`origin/cpp` before the final proof still returned that base, so no merge was
needed. All commands ran within CPUs 112–127. Live proofs used target 112–119,
oracle 120, clients 121–127, and ports within 25056–25069. No benchmark or full
gate was run; the live correctness proofs were explicitly requested for this lane.

| Finding | PRE reproduction, before production edits | POST result | Implementation and new rows |
|---|---|---|---|
| CC4.3 | Assigning `redis.call` returns `armed`; another client's script returns `changed` instead of the stored `real`. Global/library writes and reachable metatable writes also succeed. | Assignment produces the exact Redis readonly error; the other client returns `real`. All sandbox checks pass, including raw writes, C mutators, globals, string metatable, and FCALL. | `src/cmd/scripting.cc` recursively freezes the static environment using the existing vendored VM readonly flag; `src/cmd/functions.cc` freezes the registration table. Rows `scriptfix sandbox (1s)` and `(2s)`. |
| CC4.6, reset | Counter returns 1,2,3, then 1 after SCRIPT FLUSH and 1 after unrelated LOAD. | Same-key counter returns 1,2,3,4,5. Unrelated LOAD/DELETE/REPLACE/RESTORE and failed mutations preserve it; replacing its own library resets it, including identical-source replacement. | `functions.cc` retains callbacks by library revision; `scripting.cc` invalidates only EVAL chunks on SCRIPT FLUSH. `scripting.h` documents the revised lifetime/counters. Rows `scriptfix functions (1s)` and `(2s)`. |
| CC4.25 | Depth-five map and set replies escape the shared element bound, while arrays return the guard error. | Arrays, maps and sets return `ERR Error running script: script reply has too many elements`; PING answers afterwards. Exact budget 100000 passes and 100001 fails for all three shapes, in RESP2 and RESP3; FCALL map conversion is covered too. | `scripting.cc` charges map keys and values, and set keys, to the existing shared counter. Rows `scriptfix replies (1s)` and `(2s)`. |
| CC4.27 | 4096-library restore succeeds; the server's own 313269-byte, 4097-library dump returns `ERR DUMP payload version or checksum are wrong`, leaving all functions callable. | Both dumps restore successfully and all 4097 functions remain callable. Corrupt checksum still returns the original error. | `functions.cc` bounds source count by available frame bytes before allocation instead of imposing an undocumented 4096 limit. Rows `scriptfix dump (1s)` and `(2s)`. |

The readonly error for the original assignment is
`ERR user_script:1: Attempt to modify a readonly table script: <sha>, on @user_script:1.`
Raw API/C-library errors use the oracle's exact form without that first
`user_script:1:` prefix. Host setup briefly restores write access when installing
KEYS/ARGV or the registration table; ordinary user-created tables remain mutable.
The environment replacement APIs getfenv/setfenv are absent, as on the oracle.
Missing helper libraries are outside this change.

The reply bound remains 100000 with the existing array accounting, including a
terminating scan for each aggregate. A map entry charges two children; a set
entry charges its key. Map keys that are themselves aggregates share the same
counter. The set witness is a set-only DAG, so it cannot pass by relying on an
array wrapper's guard. Depth 32, instruction limit 100000, and hook interval
1000 are unchanged. No new LOAD library-count limit was added.

For CC4.6, a mutex around shared Lua execution alone would allow another FCALL
to observe new closure state before staged key effects publish. Retrying a
scatter attempt can also execute mutable Lua state more than once. Holding the
mutex through publication can block an executor needed by the holder. The
retained design therefore needs dispatch admission/parking and a once-only
state/effects commit rule beyond the allowed files. It changes one hot library's
parallelism from roughly E/T to at most 1/(T + stage + validate + apply +
scheduling); this is a structural estimate, not a measured cycle claim. No
scheduler or executor-loop changes are included.

The separate `functions --single-state` witness **still fails on POST**, with
exactly one failing assertion in each mode; its reset assertions all pass.
Redis returns 6..21 across the 16 routed keys. POST's recorded 1s sequence is
`[1,1,6,1,7,1,2,2,1,1,2,8,1,2,3,9]`; its 2s sequence is
`[1,6,7,2,3,4,5,8,9,6,10,11,12,13,7,8]`. See
[1s witness](docs/scriptfix/post-single-state-1s.log),
[2s witness](docs/scriptfix/post-single-state-2s.log), and
[oracle](docs/scriptfix/oracle-functions.log). The ordinary functions gate row
asserts only the implemented reset semantics; it logs the unresolved split.

All eight new rows fail on PRE and pass on POST. Full assertion values and
per-row log paths are in [rows.json](docs/scriptfix/rows.json). Each POST row is
under 4.4 seconds here; the longest PRE negative control is under 10.4 seconds.

| Row | PRE failing assertions | POST passed assertions | POST seconds |
|---|---:|---:|---:|
| scriptfix sandbox (1s) | 18 | 37/37 | 0.470 |
| scriptfix functions (1s) | 10 | 26/26 | 0.407 |
| scriptfix replies (1s) | 10 | 52/52 | 3.364 |
| scriptfix dump (1s) | 1 | 8/8 | 4.128 |
| scriptfix sandbox (2s) | 18 | 37/37 | 0.390 |
| scriptfix functions (2s) | 10 | 26/26 | 0.480 |
| scriptfix replies (2s) | 10 | 52/52 | 2.830 |
| scriptfix dump (2s) | 1 | 8/8 | 4.379 |

The four probes also pass their Redis expectations against Redis 7.4.10
(`/tmp/claude-1000/redis74/src/redis-server`, version sha `f103d127:0`). Redis
returns both large reply shapes because it has no corresponding element guard.
Oracle receipts are `docs/scriptfix/oracle-{sandbox,functions,replies,dump}.log`.

`tests/scriptfix.py` is the reusable, self-booting row adapted from the supplied
audit probes. It accepts binary, port, CPU mask, engine and mode arguments,
refuses an occupied port, reaps only its own child, verifies listener shutdown,
and has a 55-second deadline. Example for either arm (substitute each case and
mode); this is the same geometry used for the row proofs:

```sh
taskset -c 112-127 taskset -c 121-127 python3 tests/scriptfix.py sandbox \
  --binary build/scriptfix/pre/tomokv --port 25056 --cores 112-119 --mode 2s \
  --output build/scriptfix/runtime
taskset -c 112-127 taskset -c 121-127 python3 tests/scriptfix.py sandbox \
  --binary build/tomokv --port 25056 --cores 112-119 --mode 2s \
  --output build/scriptfix/runtime
```

`job_scriptfix` stops the gate slot's preboot before running the rows. Its
`row_begin` is at `tests/gate.sh:2114`, collection is at line 3362, and the
quick-tier exit starts at line 3435. All eight therefore count in both tiers:
**DQ=+8, DF=+8; EXPECT_QUICK should be 511+8=519 and EXPECT_FULL 528+8=536.**
The arithmetic comment is immediately above the unchanged constants at lines
290–291. The explicit fixture includes every label in collector order.

**The unmodified `python3 tests/gate_ledger_fixture.py` exits 1** because
EXPECT_FULL remains 528 while both source and fixture contain 536 rows. Their
order and multiplicity agree exactly, recorded in
[ledger-inventory.json](docs/scriptfix/ledger-inventory.json); the refusal is
[ledger-check.log](docs/scriptfix/ledger-check.log). Satisfying that check requires
the maintainer-owned EXPECT update above. Neither the constants nor the checker
was changed to conceal this conflict.

Build and correctness proof:

- PRE `make -j16 BUILD_ROOT=build/scriptfix/pre all` and POST `make -j16 all`
  succeeded, under `taskset -c 112-127`. Logs:
  [PRE](docs/scriptfix/pre-build.log.gz), [POST](docs/scriptfix/post-build.log.gz).
- The exact **28/28 targets** extracted from `job_production_units` built and
  passed their individual `make -q` checks. **`mdbqsbr-live-arms` passed**, building
  both park and no-wake variants. [Commands, target list, exit codes and archived
  build logs](docs/scriptfix/production-units.json). Final `make -q all` also passes.
- **`python3 tests/gates_test.py` did not pass.** Three full runs had 9, 14 and
  11 scheduler fixture deadline failures, respectively; their nested 14 tests
  passed each time. The final run used CPUs 124–127 after this lane's compilation
  ended, while other lanes continued compiling on the allowed CPUs. All 11 final
  failures trace to timeout exit 124. More than 100 compiler processes were
  observed during the earlier attempts; the final run still overlapped dozens.
  [All run commands/results](docs/scriptfix/gates-test-runs.json),
  [final full output](docs/scriptfix/gates-test.log),
  [initial output](docs/scriptfix/gates-test-initial-timeout.log.gz), and
  [second output](docs/scriptfix/gates-test-serialized-timeout.log.gz).
  The two narrower runs serialized complete fixture scenarios by affinity.
  No assertions, deadlines, or job inventory were changed. **Rerun the unchanged
  full suite on quiet CPUs 112–127 before landing; this proof remains unresolved.**
- Differential `script` suite: **16/16 legs, 80896 comparisons, zero differences**;
  seeds 7/19/20/23, atomic 0/1, split 6:2 with 16 shards and armed-fused with
  read-local enabled. Every leg has nonzero cross-owner activations and
  stage/validate/apply counters. Both fused read-local witnesses fire.
  [differ.json](docs/scriptfix/differ.json),
  [split log](docs/scriptfix/differ-split.log),
  [armed-fused log](docs/scriptfix/differ-armed-fused.log).
- POST `lua_scripting.py`, `scriptsurf.py`, `xscript.py`, and `scriptatomic.py`
  all pass in both split and armed-fused: **8/8 runs**. scriptsurf also uses the
  live Redis oracle. [Commands and results](docs/scriptfix/batteries.json).
  Its former interpreter-rebuild assertion now proves chunk-cache invalidation:
  a same-key cache hit before FLUSH and exactly one new compile miss after it.
- `bash -n tests/gate.sh`, Python byte-compilation, and `git diff --check` pass.

The differential recipe used the existing harness, including its automatic
atomic 0/1 loop and cross-owner activation checks:

```sh
taskset -c 112-127 bash -c 'for geometry in split armed-fused; do
  REDIS74_ROOT=/tmp/claude-1000/redis74 \
  GATE_LOAD_CORES=121-127 GATE_DIFFER_ORACLE_CORES=120 \
  GATE_DIFFER_GEOMETRY="$geometry" \
  GATE_DIFFER_PROOF_SUITES="$PWD/docs/scriptfix/differ-suites.txt" \
  GATE_DIFFER_PROOF_SEEDS="$PWD/docs/scriptfix/differ-seeds.txt" \
  GATE_DIFFER_OUT="$PWD/build/scriptfix/differ-$geometry" \
  tests/differ_gate.sh "$PWD/build/tomokv" 25060 25061 112-119 6:2 \
    >"docs/scriptfix/differ-$geometry.log" 2>&1 || exit
done'
```

Default-binary identity, using the ttlclean method:

| Namespace | PRE bodies | POST bodies | Unchanged full-inventory bodies | Changed/added/removed union | lbstall hot bodies identical |
|---|---:|---:|---:|---:|---:|
| tomo | 8391 | 8393 | 8354 | 41 | 601/601 |
| tomo_db0 | 7902 | 7905 | 7868 | 38 | 603/603 |

`tools/lbstall_artifacts.py compare` passes: **1204/1204 hot bodies have identical
bytes and relocation targets**. The broader `tools/ccfix_audit.py` inventory
confirms **1208/1208 hot bodies identical**, with **no changed hot bodies** to
explain. Its only four changed command-handler bodies are `cmd_function` and
its cold clone in both namespaces, due to library revisions and dump decoding.
All other 1206 handler bodies match. Every one of the 79 full-inventory changes
is confined to `functions.o` or `scripting.o`; the complete list and individual
reasons are in [changed-bodies-explained.json](docs/scriptfix/changed-bodies-explained.json).
Compiler inlining accounts for changed helpers whose source did not change.

The stock ccfix audit exits 1 at its final fixed CONFIG/INFO/ACL handler whitelist
because the intentional FUNCTION changes are outside that whitelist; its
preceding hot-body assertion passes. This is recorded explicitly in
[identity.json](docs/scriptfix/identity.json), with the unmodified tool output
in [full.log](docs/scriptfix/full.log). The stock linked-image comparison also
exits 1: `.text` grows from 7582188 to 7584476 bytes (+2288), and linked addresses
move. `.data` 19008, `.bss` 1146912, and `.tbss` 480 are unchanged.
[Linked comparison](docs/scriptfix/linked.json). No full linked-image identity
or performance result is claimed.

All locked structure sizes **and member offsets** match in both namespaces:
Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192,
AtomicEntry 144, Config 624. Additional Server, AofManager, and SnapshotManager
layouts also match. [Layout receipt](docs/scriptfix/layouts.json).

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/scriptfix/pre/tomokv` | `400d44aba36c90ade1fddace91eb2d8ee59b06f228219e1f6c3f41d7fe87e12f` |
| POST | `build/tomokv` | `31c1c264c3089ea90d5b99830e4bb1d14fc108cd1ba106df13dd74feade95612` |

Mainline measurement request: run the gate's performance null/comparison with
these exact PRE and POST arms, after correctness review and the owner EXPECT
update, on the scheduled quiet box. Use `tests/abbagate.py --subset smoke
--reference-binary build/scriptfix/pre/tomokv --candidate-binary build/tomokv`
with the owner's current geometry, load calibration and matched null receipt.
The 18 selected cells in `tests/headline_cells.txt` are t00 (warmup), h01, h07,
h11, h15, h17, h23, h27, h31, h48, m47, m92, and t01–t06. Retain each cell's
existing score and decision bounds: rate or latency at matched offered load is
the verdict; cycles/op, IPC, and instructions/op explain it. No instruction-only
verdict and no threshold relaxation. This correctness change requests no
default-path regression. No locked or hot structure layout changes; the new
revision field is private `LibraryDef` control-plane metadata. The requested
mainline null uses PRE/POST; no PAD result is claimed.
