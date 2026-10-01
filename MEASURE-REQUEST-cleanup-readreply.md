**cleanup-readreply — source cleanup complete; landing is PENDING MAINLINE.**

PRE and POST are **not byte-identical**. A separate **kind-A PAD behavior twin**
has been built from frozen PRE source and matches POST's executable bytes,
relocations, function addresses and load layout. Mainline must supply the
PRE/POST and PRE/PAD performance null before landing. No gain is claimed.
No server, benchmark, load generator, gate, performance measurement or push was
run by this lane. All builds and serverless executions used CPUs **112–127**;
make builds used **-j16**.

**Reference and diagnosis.** The clean lane started at staging commit
`f9a1d3360e5f7b4b9f7e007958bd9024a3bd4be9`. The first merge of `origin/cpp`
fast-forwarded to **`90ba908d3aca61f2b1e79664e839a5b8093145a4`**, including
wbland3. That is this lane's frozen PRE, not f9a1d3360. PRE was built and archived
before editing. The complete source archive, tracked-input hashes, commands,
dependency inventory and history are in `build/cleanup-readreply/freeze/`.

Rechecked launch anchors in **PRE** `src/core/ex_loop.h`:

| Item | PRE lines | Finding |
|---|---:|---|
| `read_local_reply_string` | 971–974 | Calls `reply_bulk`; its only return is `true` |
| MGET false-result recovery | 1259–1263 | Unreachable helper-failure branch |
| GET retry bound and loop | 1326, 1336 | Three syntactic iterations; no reachable second attempt |
| GET false-result recovery | 1375–1378 | Only GET `continue`; unreachable |
| GET final validation / tail | 1387–1402 | Real rejection and AtomicPending-over-SeqChurn precedence |
| MGET loop / demotion | 1155, 1177, 1289–1307 | Launch source already demotes before retry in production |

**Conclusion: obsolete recovery residue, not an unwired live reply-failure
contract.** Commit `898e9c509` introduced the per-object sequence-copy variant;
`de396b3a017bcf23d51b437851903257ac8452ed` deleted its `return false` producer
but left these consumers. `freeze/history-removed-sequence.txt` retains that diff.
The current producer copies immutable raw/external bytes through
`src/net/resp.h:269` and `Op::Sink::reserve` at `src/exec/op.h:292`; neither has a
Boolean retry result. `SmallBuf::grow` at `src/base/slice.h:267` has a separate
unchecked-allocation defect: allocation failure does not return false through
this helper. Removing these branches neither fixes nor conceals an OOM protocol.

The old audit's statement that production MGET retries is superseded by
`70a4ae41c7dd40d126a420655149caab13d338b7` and the retained unconditional assembly
jump. The existing test hook can restore the retry, and its negative control
still proves that actual retry is detected. This is a **law-conflict control**,
not evidence that production now retries. The remaining per-operation topology
sequence handshake/validation (`src/store/flatstore.h:928`, `:946`, `:3253`,
`:3260`) still conflicts with the literal no-seqlock/sequence-protocol owner law.
It protects torn/topology reads and is unchanged here; this cleanup does not
resolve that separate design conflict.

**Change and boundaries.** Production implementation is only `src/core/ex_loop.h`.
The helper is void at POST line 972; MGET calls it directly at 1259 and GET at
1368. GET at 1311 has no loop, continue, snapshot reload or retry. A Churn capture
and failed final validation reach the common cleanup at 1386. Final validation
still precedes access metadata and success; the final unsafe-key test still wins
over SeqChurn. The redundant second clear on the old failed-validation path is
gone; no observation separated those clears. The object and slot assertions at
1340/1343 remain. Capture, routing, prefetch, flags, TTL/type/encoding rejection,
epoch windows, ownership, RYOW, publication and reply ordering were not redesigned.
There is no new runtime knob or production counter. The attempt counter is static
test-only state under `TOMO_CORE_CONCURRENCY_TEST`; object layouts are unchanged.

Commits before this report: `3bb2b74c0` (cleanup), `f1fe88b7c` (serverless proofs),
`c66a5d1ef` (PAD generation and complete controls). `source-proof.json` verifies
that the entire MGET implementation is byte-for-byte source-identical except for
its one removed helper conditional, and that GET retains its assertions and
single capture/final-validation sites.

**Build and machine-code evidence.** The Makefile has 42 normal and 42 db0
production objects. All 84 have the broad header prerequisite, and all 84 were
compared, including command glue. Compiler dependency resolution identifies eight
actual includers: `main.o`, `genthread.o`, `rl2s.o`, `reorder.o` in each namespace.
`freeze/object-inventory.json` records every object, command and dependency.

Compiler: GCC 13.3.0, default release flags
`-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread`, jemalloc enabled, with
all existing per-TU parameters unchanged. PRE/POST used the same absolute worktree
and relative source/output paths. `freeze/reproducibility.json` confirms identical
84 compile commands plus link command and 734 resolved inputs: only `ex_loop.h`
changed; compiler, system headers and libraries did not. Test and report changes
do not change production flags or dependencies.

Each arm below has `artifacts/` containing the linked binary and all 84 objects,
`manifest.json` with their SHA-256 hashes, and `dumps/` containing raw
`objdump -drw`, `readelf -W -h -l -S -s -r`, `nm`, every executable section dump,
section metadata, relocation targets/addends and symbol addresses. The existing
strict checker in `tools/ttlstate_proof.py` is reused by `tools/readreply_proof.py`.
It compares actual bytes without instruction normalization or relocation masking.
It covers every SHF_EXECINSTR section, including `.text` and **all** executable
`.text.*`, allocated bytes, relocation targets, entry point and program headers.
DWARF and its build ID are reported separately. Generated zero-size local `%=`
marker names may differ only with the same address and attributes; all such
renames are recorded, never used to excuse an instruction or relocation change.

| Arm | Binary under `build/cleanup-readreply/` | Bytes | SHA-256 |
|---|---|---:|---|
| PRE | `PRE/artifacts/tomokv` | 176965512 | `c311ea6cb0892d81bcee1c6e0cca5f385054a1a43da7fd3e701e8c46acb2d430` |
| POST | `POST/artifacts/tomokv` | 176985360 | `b572f6baebd70608cb0f1785af339b5345a2390c79a171ead0d0eef01288a1aa` |
| PAD **(A), behavior twin** | `PAD-A/artifacts/tomokv` | 176986320 | `fce536372fe25dbcec8ca75fa054d33f392493a8abb7238c48944095718792d8` |

| Raw code size | PRE | POST / PAD-A |
|---|---:|---:|
| Linked `.text` | 7564593 | 7564433 |
| All linked executable sections | 7574425 | 7574265 |
| Normal genthread executable bytes | 636004 | 635751 |
| Normal rl2s executable bytes | 797294 | 797435 |
| Normal reorder executable bytes | 733765 | 733870 |
| db0 genthread executable bytes | 638082 | 638064 |
| db0 rl2s executable bytes | 801271 | 801267 |
| db0 reorder executable bytes | 734042 | 734279 |

`identity.json` honestly fails PRE/POST overall: **78/85 artifacts match**, with
the six loop objects above and linked binary differing. PRE has 8582 executable
object sections; POST has 8588. Both `main.o` variants and every command object
match. `code-deltas.json` inventories every changed function size, including
23 linked function entries. GET becomes 2608→1675 bytes in both namespaces:
PRE inlines reply construction where POST calls an outlined `reply_bulk` and
decimal helper. Other compiler inlining/outline and COMDAT choices also change
in these large TUs, including split parser/writeback bodies and fused deferred
atomic handling. Their sources were not edited. Raw `PRE-GET.objdump`,
`POST-GET.objdump` and all object dumps expose the actual calls and differences;
smaller code is not claimed to be faster. Source-shape trials are retained under
`alternatives/`; none is silently substituted for the committed candidate.

**Independent PAD mapping.** `readreply_proof.py pad` starts with the frozen PRE
archive, not candidate source or an R7 control. It retains PRE's complete GET
`kRetries=3` loop, both original recovery bodies, and old cleanup. The reference
CFG proves the helper returns only true, so each `if (!emit())` is equivalently
spelled `if ((emit(), false))`; the now-unused true return is discarded to expose
void emission to GCC. These explicit constant folds preserve PRE behavior and
give the candidate's compiler decisions. `pad-source-proof.json` records the
exact mapping and header digests; `PAD-A-source/` retains generated source and
per-object build logs. Eight includers are rebuilt with the frozen commands;
the other 76 objects are copied from PRE and the frozen link command is used.
No candidate implementation body, patched executable instruction or NOP footer
is used to construct this arm.

`identity-PAD-POST.json` passes **85/85**, including all executable and allocated
bytes, target relocations, the six linked executable sections, 3786 linked
relocations, all 10618 allocated symbol entries and entry point **0x4dc10**.
All **10016 function symbol entries / 8805 unique function names** have the same
addresses and sizes. Fifteen linked local marker spellings differ, with identical
addresses and attributes. Full debug ELF hashes differ as shown above.
`identity-PRE-PAD.json` correctly fails, also 78/85 identical artifacts.

This cleanup has no intended semantic difference: an independently derived PRE
behavior twin can therefore have POST's exact code. That result does **not**
discharge PRE/POST or PRE/PAD performance parity. PAD/POST has a production-byte
identity proof; mainline may also measure that pair as the instrument control.
Kind B is not required: the linked `.text` change is **−160 bytes**, below the
specified few-hundred-byte threshold. No previous R7 PAD is reused.

**Serverless assertions and controls.** The existing `tests/rltopo_unit.cc` battery
now runs 15 states × GET/MGET × databases 1/4 × modes 1s/2s = **120 positive cases**.
The fixture has 16 shards and, for split, eight allowed cores with 6 IO + 2 EX.
These are private reply/preparation proofs; no listener or worker loop is started.
Real capture, reply, window, fallback and access-accounting code is exercised.

| Exercised state / assertion | Exact expectation | Throwaway control and result |
|---|---|---|
| Raw (embedded NUL/CRLF), external 515 bytes, empty, live TTL, persisted TTL | Exact RESP2 bulk bytes; MGET two-element framing | Omit raw emission: designated byte assertion fails in each state, both commands/modes |
| Integer `INT64_MIN` | Exact signed decimal bulk bytes | Omit integer emission: byte assertion fails |
| Wrong type / unsupported encoding | Typed fallback, no private reply | Bypass type rejection / accept unsupported encoding: reason assertion fails |
| TTL equal to command cut 1000 | Expired fallback, no private reply | Bypass expiry rejection: reason assertion fails |
| Missing | GET Missing; MGET exactly two nulls and two misses | Accept missing GET / omit MGET null: corresponding reason/byte assertion fails |
| Pending key, pending after copy, Churn capture followed by pending | AtomicPending wins over transient reason | Corrupt early or final pending classification: reason assertion fails |
| Churn bracket | SeqChurn; clean reply state | Omit bracket: explicit topology-window entry assertion fails |
| Invalid final capture/window | GET SeqChurn; MGET Generation | Accept forced invalid capture/window: reason assertion fails |
| Copy-window liveness, including late pending | Exactly one deterministic window entry | Omit callback's mutation: window assertion fails, never SKIP |
| GET emission entry | At most one attempt | Restore reachable first-attempt `continue`: count becomes two and bound fails for raw and integer |
| Stale coded reply and borrowed fields | Code zero, pointer null, length zero, shard −1 | Omit those clears: designated state assertion fails |
| Accepted hits/misses | Exact 0/1/2 counts, no accepted counts on demotion | Double hits/misses: count assertion fails |
| Access metadata | GET touches after final validation; MGET touches before outer close | Omit access touch: metadata assertion fails |
| Requested encoding | Fixture actually enters Int/Raw/Extern | Substitute raw for external setup: encoding witness fails |

**102/102 designated negative-control executions passed** across 1s/2s:
each broken process exited 1 with its specific expected assertion. Full mapping,
binary hash and exact failure strings are in `controls/results.json`; every
process has a retained log. The generated selector exists only in the throwaway
serverless source and is absent from production. Its unbroken selection passes
the complete existing battery in both modes. Windows are forced on fresh state
with a deterministic one-attempt budget; failure to enter fails the test. The
old topology/retry-restored controls remain active and passed separately.

The reference proof is static, not a claim to execute an unreachable branch:
`freeze/read_local_reply_string.cfg` has one normal return, constant true.
`reference-cfg.json` walks 93 optimized GET blocks and finds no return path to
capture consumption (bb13), stable flags (bb20), encoding dispatch (bb26), raw
emission (bb60) or final validation (bb74). Decimal formatting/buffer-growth loops
remain real loops. Raw full and extracted CFG/GIMPLE files are retained.

The byte checker was separately attacked with copied artifacts changing one
`.text` byte, one executable `.text.*` byte, a relocation addend, and a linked
function address. **4/4 rejected** at the intended checks. Corrupted files are
mode 0600, labelled `.NEVER-RUN`, and were never executed (`elf-controls/`).

Builds passed: PRE, POST, PAD-A, ASAN/UBSAN rltopo, throwaway controls,
read-local-write-ring, multidb and mdbqsbr. Executions passed: both complete
rltopo modes, controls, write-ring, multidb owners (including db0 checks), and
ASAN/UBSAN mdbqsbr. Existing size/offset assertions compiled unchanged, including
Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192,
AtomicEntry 144 and Config 624. This is not a claimed gate pass.

Reproduce the serverless checks only, on this lane's permitted CPUs:

```sh
taskset -c 112-127 make -j16 build/rltopo-unit build/read-local-write-ring-unit build/multidb-unit
taskset -c 112-127 env ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 ./build/rltopo-unit 1s
taskset -c 112-127 env ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 ./build/rltopo-unit 2s
taskset -c 112-127 ./build/read-local-write-ring-unit
taskset -c 112-127 ./build/multidb-unit
taskset -c 112-127 env ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 ./build/mdbqsbr-unit
taskset -c 112-127 python3 tools/readreply_proof.py source
taskset -c 112-127 python3 tools/readreply_proof.py cfg
taskset -c 112-127 python3 tools/readreply_proof.py controls
taskset -c 112-127 python3 tools/readreply_proof.py elf-controls
# Intentionally exits 1: PRE/POST is not identical.
taskset -c 112-127 python3 tools/readreply_proof.py identity
```

Regenerating proofs changes logs/manifests. Preserve archived arms; `capture`
refuses to overwrite one. To rebuild PAD from scratch, use a fresh artifact
destination/worktree rather than overwrite the frozen control.

**Mainline correctness and row accounting — live results PENDING MAINLINE.**
No row was added or retired, and `tests/gate.sh` is unchanged relative to launch.
The two existing topology rows at emission lines 1269/1271 now include the new checks;
both precede quick exit at **2875**. Delta: **quick +0, full +0**. Launch constants
remain **EXPECT_QUICK=446, EXPECT_FULL=463**; wbland3's +2 is already in PRE and is
not this lane's work. No gate script was added and no expected constant was edited.

| Required retained row | Launch emission/call lines in `tests/gate.sh` | Status |
|---|---:|---|
| Read-local write-ring | 1235 | Serverless executable PASS; gate unrun |
| Topology demotion 1s/2s | 1269/1271 | Serverless executable PASS; gate unrun |
| Multidb serverless owners | 1345–1350 | Both executables PASS; gate unrun |
| Read-only resize | 1469/1471 | PENDING MAINLINE |
| Atomic torn/window; RYOW/mixed-write | 1518, 1521 | PENDING MAINLINE |
| Read-local lane admission | 1584 | PENDING MAINLINE |
| Atomic ASAN counterparts | 2408, 2419 | PENDING MAINLINE |
| Armed block-cache build/churn/ownership | 2497, 2512, 2519 | PENDING MAINLINE |
| Feature matrix / mode equivalence | 2359 onwards; 2823 onwards; 2901 onwards | PENDING MAINLINE |

The physical location of each emission, not a section's old “full tier” comment,
determines quick arithmetic: the required rows listed through ownership are above
2875 at this launch. Keep the gate's own geometry/boot handling and its explicit
64-shard ownership-churn exception. Mainline may run its usual
`tests/gate.sh iteration`; to diagnose the exact archived arms, add
`--reference-binary "$PWD/build/cleanup-readreply/PRE/artifacts/tomokv"` and
`--candidate-binary "$PWD/build/cleanup-readreply/POST/artifacts/tomokv"`.
External-candidate mode cannot earn a source receipt. This gate command is not a
substitute for the independently calibrated null below. There are no new live
control binaries: all new negative controls are serverless and have been run.

**Mainline performance contract — PENDING MAINLINE.** Arms are exactly the three
SHA-bound binaries above. The unchanged base guard inventory is **h01–h64**:
512 total connections, GET/SET × p1/p32 × both modes × read-local/overlap/reorder.
Exact launch lines, per-line digests and load plans are in
`freeze/h01-h64.txt`, `freeze/h01-h64-plans.json` and the full frozen files.
Cell-file SHA-256: `d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350`.
Launch load-ledger SHA-256: `6c81d71e7db475303b340cd39cfa96929ca5bf708387a6edbf8edf555dc6582e`.
Payload/load context retains 64-byte values, 2,000,000 keys, P:P, ABBA,
3-second warmup / 20-second central / 5-second tail windows. The launch ledger
has no h33–h64 load floor; this absence is recorded, not guessed.

The launch note names **14 generic null cells** without IDs. Their exact mainline
selection remains **PENDING MAINLINE**; no guessed subset replaces h01–h64.
Append the feature regimes in `freeze/feature-regimes.json`, keeping existing
cells' bytes unchanged: both modes, databases 1/4, p1/p32, 512 connections,
GET/MGET2/MGET129; neutral read-local=0 and armed read-local=1 with raw64,
integer, external1024 and empty values; possible-deficit expiry, rehash and
atomic-conflict regimes. The JSON enumerates the coverage matrix, not new gate
rows or fabricated load plans. MGET129 also exercises the retained uncached-route
window. Freeze any regime's writers, offers and worker/pin plan independently
before looking at POST. Record local hit/fallback reasons so lower hit rate cannot
hide an owner-path regression. No benefit regime is claimed.

Use 16 shards and the reviewed eight-core 6:2 IO/EX split for 2s; cover eight-core
1s too. Establish the productive-role plateau with enough connections/workers at
both p1 and p32. A single-connection saturation result does not qualify. Compare
at matched offered loads and report cycles/op, instructions/op and IPC together
(`cycles/op = instructions/op / IPC`), rate and p99/p99.9 tails, by cell/regime.

Instrument evidence is frozen read-only, with all named source-file hashes
verified against the recorded commits:

| Instrument | Digest / stable binary | Limitation |
|---|---|---|
| Historical nullrefresh5, 23 files | Instrument `cc6c06bde1ce7939b7f001489fde7287476c4086929f51badf774811d087dd36`; stable `ef52de792f72ab8dae240fcd8194e1f14aa94b3828dc7e512eea7256b50c1133` at `9c4717da03b9340377926277f8eb99cea9f5ab5a` | 32 cores / 16:16; cannot certify reviewed eight-core cells |
| New nullpublish freeze `20261001T034327Z`, 25 files | Instrument `ef5bb5a313f566a67f70b583708bc087da217c9ec5162a3974bb3483b61617dc`; frozen campaign A=B binary `49e69e30d1d3d46f46f8e5f96dad17885511e905c98fba4a3d530814885cf1a7` at baseline `90ba908d3` | Build freeze explicitly says `measurements_run: false`; no calibration/holdout result in that campaign directory |

The newer instrument source commit is `08d1dd2dbb1d549c83eeb5a8f4792c6b9bd6230b`.
Full manifests and bytes are under `freeze/nullrefresh/` and
`freeze/nullpublish-20261001/`. These stable binaries are named independently of
this lane's PRE; differing debug hashes are not silently interchanged. Per-cell
resolution and independently validated null bands for this requested geometry
are **PENDING MAINLINE**. Freeze the instrument digest, stable reference SHA,
resolution, and separate cycle/rate/tail epsilons before any candidate measurement;
changed instrumentation needs fresh validation and independent holdout.

For every cell and pair PRE/POST, PRE/PAD and PAD/POST, require stable-reference
parity at that cell's frozen resolution and:

```text
abs(100 * (cycles_right / cycles_left - 1)) <= epsilon_cyc[cell]
100 * (1 - rate_right / rate_left)          <= epsilon_rate[cell]
100 * (tail_right / tail_left - 1)          <= epsilon_tail[cell]
```

Apply tails separately to each frozen tail metric. Do not average away a losing
cell or widen any band after POST. PAD/POST's byte identity can discharge that
pair's code null, but not qualify an unvalidated instrument or PRE/PAD result.

| Regime | PRE cycles / instr / IPC / rate / tails | POST | PAD-A | Verdict |
|---|---|---|---|---|
| Neutral read-local=0 | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE | Pending |
| Exercised armed GET/MGET, raw/integer/external/empty | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE | Pending; no gain required |
| Possible deficit: expiry / rehash / atomic conflict | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE | Pending |
| Benefit | No claim | No claim | Control only | No optimization claim |

**Artifact and diff receipts.** `build/cleanup-readreply/ARTIFACT-SHA256SUMS`
contains **30287** retained artifacts; its SHA-256 is
`d1c02a1431b1f13358318a3d411eea4cc3901879e49848cf22fb2d9d80b55756`.
All entries passed `sha256sum -c`; log is `verify-artifacts.log`.

```text
$ sha256sum build/tomokv
b572f6baebd70608cb0f1785af339b5345a2390c79a171ead0d0eef01288a1aa  build/tomokv
```

Before adding this report, `git diff 90ba908d3 --stat` was:

```text
 src/core/ex_loop.h       |  63 ++++----
 tests/rltopo_unit.cc     | 148 ++++++++++++++++++-
 tools/readreply_proof.py | 369 +++++++++++++++++++++++++++++++++++++++++++++++
 3 files changed, 539 insertions(+), 41 deletions(-)
```

Requested staging comparison, `git diff f9a1d3360 --stat`, before this report:

```text
 MEASURE-REQUEST              |   36 +-
 MEASURE-REQUEST-wbland.md    |  364 ++++++++++
 MEASURE-REQUEST-wbland2.md   |  284 ++++++++
 MEASURE-REQUEST-wbland3.md   |  285 ++++++++
 Makefile                     |   23 +
 docs/CONFIGURATION.md        |    9 +
 src/cmd/t_server.cc          |    2 +
 src/core/config.h            |   19 +-
 src/core/ex_loop.h           |   63 +-
 src/core/server.h            |    3 +
 src/core/wb_rule.h           |   23 +-
 tests/gate.sh                |   29 +-
 tests/gate_measurements.json |    8 +-
 tests/netcmd_config_unit.cc  |    7 +-
 tests/rltopo_unit.cc         |  148 +++-
 tests/wb_rule_checks.py      |   10 +-
 tests/wb_rule_phase_unit.cc  |   33 +-
 tests/wbland_4096_cells.txt  |   13 +
 tests/wbland_checks.py       |  111 +++
 tests/wbland_clause_unit.cc  |   10 +
 tests/wbland_evidence.json   | 1633 ++++++++++++++++++++++++++++++++++++++++++
 tests/wbland_merit_cells.txt |   14 +
 tests/wbland_unit.cc         |   78 ++
 tomokv.conf                  |    5 +
 tools/readreply_proof.py     |  369 ++++++++++
 tools/wbland_artifacts.py    |  161 +++++
 26 files changed, 3659 insertions(+), 81 deletions(-)
```

The extra staging-base files are the required launch merge, not bundled lane
features. Mainline owns live correctness, calibrated null, gate, receipt and merge.
