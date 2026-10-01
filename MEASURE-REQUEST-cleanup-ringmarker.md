**cleanup-ringmarker: empty marker removed; two production instruction bytes differ.**

The source cleanup is committed. **Production byte identity did not pass.** A
separate **kind-A PAD behavior twin** is supplied and has exactly POST's function
address table and executable layout. Landing requires the mainline-controlled
PRE/POST/PAD null. No rate gain is claimed. Live batteries, boots, gate results,
and performance results are **PENDING MAINLINE**.

Worktree/branch: `/home/user/Projects/cx-cleanup-ringmarker`,
`cx-cleanup-ringmarker`. At launch, the clean worktree was at staging reference
`f9a1d3360e5f7b4b9f7e007958bd9024a3bd4be9`. The required first merge fast-forwarded
to launch `origin/cpp` **`90ba908d3aca61f2b1e79664e839a5b8093145a4`**, including
wbland3 and mainline's gate-count corrections. **PRE is that launch reference**,
not the older f9 staging tree. Both revisions and their intervening diff are
frozen under `build/cleanup-ringmarker/freeze/`.

Production change: `bfb1c9981` (five files, sixteen deletions). Source/byte controls:
`3f2c44414`; same-layout PAD tooling: `d280f7287`. All builds and serverless
executions used `taskset -c 112-127`; builds used `make -j16`. No server,
load generator, benchmark, gate, performance measurement, or push was run.

**Diagnosis and scope.** The launch inventory contains **one declaration and
twelve calls**, not eleven calls:

| Launch source | Marker locations |
|---|---|
| `src/net/uring.h` | Empty declaration `:331`, obsolete explanation `:329-330`, wake producer call `:367` |
| `src/core/io_loop.h` | `:828`, `:859`, `:934`, `:961`, `:1230`, `:1686` |
| `src/core/reorder.cc` | Generated TLS receive call `:1535` |
| `src/persist/aof.cc` | `:98`, `:111` |
| `src/snapshot/snapshot.cc` | `:95`, `:617` |

History is decisive: `833568d2b2db26367129e596e60582d14a805b95`, “perf(uring):
drop dead pending-SQE bookkeeping,” removed `pending_`, its resets and accessor,
and made the marker empty. Searching that commit's parent for `pending()` finds
only the accessor declaration, no consumer. Retained evidence:
`freeze/history-removal.txt`, `history-marker.txt`, `history-pending-consumers.txt`,
and both tracked-scope and whole-tree marker inventories.

**Conclusion: deliberate obsolete residue, not a constant-return defect or an
unwired live submission contract.** The real producer is liburing's
`_io_uring_get_sqe`: the frozen system header increments `sqe_tail` at
`freeze/liburing.h:1363`. `io_uring_sq_ready` consumes tail/head state at `:1171`.
The marker owns no state, publishes nothing, and has no consumer.

The following POST operations and their source order are retained:

| Live contract | POST anchors |
|---|---|
| SQE allocation/full-queue submission | `src/net/uring.h:182-203` |
| Real submit/reap/wait paths | `src/net/uring.h:206`, `:223`, `:234` |
| SEND classification, separate from generic pending state | `src/net/uring.h:333`, `:336`; producers `src/net/wb.h:418`, `:958`, `:1035` |
| Real pending query and inter-owner wake | `src/net/uring.h:350`, `:357` |
| Accept, receive, TLS receive/poll, migration cancellation | `src/core/io_loop.h:808`, `:844`, `:890`, `:942`, `:1208`, `:1675` |
| AOF write/sync preparation and actual submit consumers | `src/persist/aof.cc:89`, `:101`, `:684`, `:982`, `:1026` |
| Snapshot write/sync and actual submit consumers | `src/snapshot/snapshot.cc:89`, `:605`, `:285`, `:350`, `:368` |

Only the empty declaration, its two obsolete comment lines, the separating blank
line, and its calls were removed. The active generator is
`tests/r7shadow_sync.py:4,17-20`. Its `--write` regenerated the R7 envelope;
the resulting generated change is the single call deletion at POST
`src/core/reorder.cc:1534`. No generated body was hand-edited and no generator
policy changed. `source-removal.diff` retains the complete production diff.

POST's independent inventory scans all **460** text files under `src`, `tests`,
and `tools`, and finds zero marker occurrences. Reports and archived PRE/control
fixtures are evidence, outside that production/source-tool scope. No new semantic
submission test was added: neither the old empty call nor its absence witnesses
an SQE reaching the real submit path.

No ownership, migration, QSBR, RYOW, atomicity, reply-ordering, submission, wake,
or safety-guard change was made. No conflict with the stated correctness laws was
identified in the touched paths; this is not a claim of a new whole-tree audit.
Both database namespaces and both mode implementations remain compiled. Existing
footprint/offset assertions remain intact: Op 336, Client 1984, ThreadCtx 1408,
Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624.

**Build and byte evidence.** PRE was built and captured before POST compilation;
its build finished before any tracked source edit. Both arms used the same worktree
source paths and `build/` output paths, GCC 13.3.0, the unmodified Makefile,
`-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread`, jemalloc, and all existing
per-object budgets/namespace flags. PRE and POST production builds exited zero
with no warnings. `freeze/make-dry-run.txt` and `POST-build-commands.txt` are
byte-identical.

Compiler `-M` inventories cover **84 production objects: 42 normal and 42 db0**.
**68 include `uring.h` (34 per namespace)**. The byte checker deliberately covers
all 84 plus the final executable, including the 16 non-includers. The inventory
includes `main.o`, `core/genthread.o`, `core/rl2s.o`, `core/reorder.o`, AOF,
snapshot, and every other compiler-discovered includer in both namespaces.
This follows Makefile `:43-49,84-90`, not just direct include searches.

`PRE-inputs/inventory.json` and `POST-inputs/inventory.json` retain every TU,
compiler argv, dependency and inclusion flag, with raw `.d` files beside them.
The graphs are identical. All **722 distinct dependency paths** and **33
compiler/toolchain/link files** were hashed. Only the five intended production
source dependencies differ. Compiler, system/Lua headers, libraries, Makefile and
other dependencies match (`input-comparison.json`). The reproducible inventory
driver is `build/cleanup-ringmarker/dependencies.py`.

The unchanged `tools/ttlstate_proof.py` supplies the raw ELF checker. It compares
all SHF_EXECINSTR sections, including every `.text` and executable `.text.*`,
without masking bytes or normalizing instructions. It also compares allocated
data and layout (excluding the debug-dependent GNU build-ID payload), relocation
targets/types/offsets/addends, allocated symbol addresses, ELF entry point and
program headers. Raw objdump/readelf, section dumps and symbol tables are saved.
Instruction counts and the narrower R7 normalized audit are not substitutes.

| Check | PRE versus POST result |
|---|---|
| Object `.text` bytes | **84/84 identical** |
| Objects including every executable `.text.*` | **76/84 identical**, eight exceptions below |
| All executable sections, objects plus executable | **8579/8588 identical**; all 8588 layouts identical |
| Final six executable sections | Five identical; `.text` has exactly two changed bytes |
| Final `.text` size/address | Both **7,564,593 bytes**, start `0x1d660` |
| Relocation targets and allocated data except build ID | Identical for all 85 ELF artifacts |
| Final allocated relocation records / symbol records | 3,786 / 10,618 audited |
| Function table | All **10,327** name/address/size entries identical |
| Entry point / program headers / loaded layout | Identical; entry **`0x4dc10`** |
| Whole production-identity checker | **FAIL, exit 1**, retained in `byte-identity.json` |

The eight object exceptions are `main.o`, `core/genthread.o`, `core/rl2s.o`, and
`core/reorder.o` in **both** namespaces. Each changes one byte in its 448-byte
`IoLoop::arm_recv<false>` COMDAT section. At function offset `0x2e`, GCC emits
`48 39 d0` (`cmp %rdx,%rax`) in PRE and `48 39 c2` (`cmp %rax,%rdx`) in POST,
followed by the same `jne`. This is a reversed symmetric equality comparison;
the source removed no real operation. It still is a code-generation difference,
and no performance equivalence is inferred from that explanation.

The final ModR/M byte changes are `d0 -> c2` at **`0x8fea0`** (`tomo_db0`) and
**`0x40b710`** (`tomo`). Function starts stay `0x8fe70` and `0x40b6e0` respectively.
See `PRE-arm-recv.txt`, `POST-arm-recv.txt`, `arm-recv.diff`, and
`linked-byte-differences.json`. Other full-ELF differences are DWARF/string data
and build ID. The checker records 185 spelling-only local assembler-label renames
across all artifacts; each retains its address/attributes and none is a function
rename or an executable-byte exemption.

**PAD-A mapping.** PAD-A is a separately saved, **unmodified copy of PRE**, not an
existing R7 PAD. Its whole-file hash equals PRE. This is a valid **(A) behavior
twin: PRE behavior with POST text size/layout**, because the full function table,
all executable section sizes/addresses/alignment, entry point and load mappings
already match POST. `PAD-A-proof.json` verifies this independently. There is no
footer padding or inferred hot-function alignment. Kind B is unnecessary: the
`.text` size delta is **zero**, although the debug ELF shrinks by 2,480 bytes.

| Arm | Artifact under `build/cleanup-ringmarker/` | Full ELF bytes | SHA-256 |
|---|---|---:|---|
| PRE, launch `90ba908d3` | `PRE/artifacts/tomokv` | 176965520 | `1c5e48dfdfdf2595199786a264916c02c2bf3aafca6e016f3c0a2889bcccb385` |
| POST, production `bfb1c9981` | `POST/artifacts/tomokv` | 176963040 | `3fbe347fff4cdf6aaf65ab4593bdf46e822789dcf9cc6be8e9ee27743a66cf75` |
| PAD-A, PRE behavior / POST layout | `PAD-A/artifacts/tomokv` | 176965520 | `1c5e48dfdfdf2595199786a264916c02c2bf3aafca6e016f3c0a2889bcccb385` |

Each arm has `manifest.json` and `dumps/`. PRE/POST retain all 84 object files;
PAD object provenance is exactly PRE. For each retained ELF, the dump directory
contains `objdump.txt`, `readelf.txt`, `nm.txt`, `sections.json`, raw executable
section `.bin` files, `relocations.json` and `addresses.json`. For example:
`PRE/dumps/db0/src/core/reorder.o/` and `POST/dumps/tomokv/`.
`proof-receipts.sha256` hashes the primary receipts, manifests and arm binaries.
`working-artifacts-check.json` verifies all 85 working POST artifacts still match
the frozen arm after the serverless builds.

Required working binary hash:

```text
$ sha256sum build/tomokv
3fbe347fff4cdf6aaf65ab4593bdf46e822789dcf9cc6be8e9ee27743a66cf75  build/tomokv
```

**Assertions and negative controls.** The final driver is
`tools/ringmarker_proof.py`; all **14 control cases passed their expected
outcomes** in `controls-final.json`. Changed ELF copies have mode 0600 and names
ending `.NEVER-RUN`; none was executed.

| Exercised state / assertion | Throwaway negative control and exact rejection |
|---|---|
| Source has no marker; unchanged POST is the positive arm | Restore PRE's declaration inside a copied `Ring`; inventory exits 1 with that exact occurrence |
| Generated source is also in the removal inventory | Restore PRE's R7 TLS receive call in a source copy; inventory exits 1 with that exact occurrence |
| Identical ELF is accepted | Original against itself exits 0; establishes the positive byte-check arm |
| Linked `.text` bytes must match | Flip one executable byte in a copied linked ELF; `executable .text: bytes differ`, exit 1 |
| Every normal executable `.text.*` must match | Flip one byte in a normal `main.o` subsection; exact named executable-section byte mismatch, exit 1 |
| Every db0 executable `.text.*` must match | Same control in db0 `main.o`; exact subsection byte mismatch, exit 1 |
| Relocations must still target the same operation/data | Change an executable relocation addend by one; `allocated relocation targets differ`, exit 1 |
| Linked addresses must match even when code bytes do | Move one function symbol by one byte; `allocated symbol addresses/identities differ`, exit 1 |
| Entry point must match | Increment copied ELF entry point; `ELF kind/machine/entry or program headers differ`, exit 1 |
| Runtime allocated data must match | Flip one `.rodata` byte; `allocated .rodata: bytes differ`, exit 1 |
| PRE-copy PAD construction must reject incompatible POST artifacts | Each of the address, entry-point and data controls above also rejects PAD construction with its exact diagnostic; no arm is created (three cases) |

These are inventory/artifact assertions, not kernel submission witnesses. Existing
core and live battery assertions are retained; no unentered live window is
treated as a pass or skip. Mainline must retain bounded fresh-state rearming and
FAIL when the required state never occurs.

Reproduce the artifact controls without running a server (use a fresh destination):

```bash
cd /home/user/Projects/cx-cleanup-ringmarker
taskset -c 112-127 python3 tools/ringmarker_proof.py source . --expect absent \
  --output build/cleanup-ringmarker/source-recheck.json
taskset -c 112-127 python3 tools/ringmarker_proof.py controls . \
  build/cleanup-ringmarker/freeze/reference.tar \
  build/cleanup-ringmarker/PRE/artifacts/tomokv \
  build/cleanup-ringmarker/PRE/artifacts/src/main.o \
  build/cleanup-ringmarker/PRE/artifacts/db0/src/main.o \
  build/cleanup-ringmarker/controls-recheck \
  --output build/cleanup-ringmarker/controls-recheck.json
taskset -c 112-127 python3 tools/ttlstate_proof.py compare \
  build/cleanup-ringmarker/PRE build/cleanup-ringmarker/POST \
  --output build/cleanup-ringmarker/byte-identity-recheck.json
# The last command correctly exits 1 for the documented two linked-byte changes.
```

**Existing checks and live obligations.**

| Check | Result / receipt |
|---|---|
| Production PRE and POST builds; footprint/offset locks | PASS; `PRE-build.log`, `POST-build.log` |
| R7 canonical generator check | PASS; `r7-sync.log` |
| R7 off-path noop, `--inventory wbrule` | PASS, **368/368**; `r7-noop.log`, `r7-noop/audit.json`; narrower than the raw ELF check |
| R7 serverless unit | PASS, 13 witnesses; `r7-unit.log` |
| Core drain and notify, ASAN/UBSAN | PASS, both selected rows; `core-asan.json` and logs |
| Core drain and notify, TSAN | PASS, both selected rows; `core-tsan.json` and logs; existing fence instrumentation warnings retained in `serverless-build.log` |
| Gate-harness serverless suite | Initial **FAIL**: 57 tests, three 45-second scheduler subcase timeouts across two methods; `gates-test.log` |
| Those two methods after this lane's builds finished | PASS at unchanged deadlines, 2 tests; `gates-test-targeted.log`; failed initial evidence remains retained |
| Eight-core quick correctness resource plan | PASS (planning only), 6:2; `mainline-quick-plan.json` |
| Eight-core iteration/ABBA resource plan | REFUSED: reviewed eight-core ABBA ratio is absent; `gate-iteration-8core-refusal.txt` |
| AOF byte-exact/reply gate, typed snapshot, TLS send/cleanup, shutdown, both modes and database runtimes | **PENDING MAINLINE**; no live result claimed |

The harness timeout methods were
`SchedulerWiring.test_completion_is_not_visible_before_its_record_is_written`
and `test_empty_fragment_and_explicit_failure_cannot_turn_green` (empty/red
subcases). Original scheduler failure artifacts remain under
`build/scheduler-failure-{faat_3l0,j3odszm_,pzriglpp}/`. No harness source, deadline,
test selection inside either method, or tolerance was changed. The full 57-test
suite was not rerun or relabelled green.

Core commands actually run after building the existing targets:

```bash
ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 \
  taskset -c 112-127 ./build/core-concurrency-unit drain
ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 \
  taskset -c 112-127 ./build/core-concurrency-unit notify
TSAN_OPTIONS=halt_on_error=1:exitcode=66 \
  setarch x86_64 -R taskset -c 112-127 ./build/core-concurrency-mdbqsbr-tsan drain
TSAN_OPTIONS=halt_on_error=1:exitcode=66 \
  setarch x86_64 -R taskset -c 112-127 ./build/core-concurrency-mdbqsbr-tsan notify
```

Mainline-only live command for the requested quick-tier rows, **not run here**:

```bash
cd /home/user/Projects/cx-cleanup-ringmarker
tests/gate.sh quick --server-cores 0-7 --server-smt '' \
  --load-cores 8-111 --load-smt '' \
  --reference-binary "$PWD/build/cleanup-ringmarker/PRE/artifacts/tomokv" \
  --candidate-binary "$PWD/build/cleanup-ringmarker/POST/artifacts/tomokv"
```

The normal mainline iteration command can use `--server-cores 0-31 --load-cores
32-111` with those same arms and empty SMT selections (`mainline-iteration-plan.json`).
That plan retains eight-core **6:2 correctness slots**, but its 32-core/16:16 ABBA
results do not discharge this request's separate eight-core null contract.

Rechecked gate emission lines: core drain/notify use `tests/gate.sh:1254` through
the loop at `:1245`; typed snapshot round-trip `:1782`; AOF byte-exact `:2073`,
always-fsync/reply gate `:2122`; TLS battery `:2336`, shutdown `:2340`, send error
check `:2343`, connection cleanup `:2350`. They are all **before the quick exit
at `:2875`** (the old `:2808` anchor moved). No row was added, removed or renamed
on either side of that exit. **Row delta 0: EXPECT_QUICK 446 + 0 = 446;
EXPECT_FULL 463 + 0 = 463.** Both constants and `tests/gate.sh` are unchanged
relative to launch. The f9-to-launch count changes belong to mainline, not this lane.

**Frozen mainline A/B contract.** Preserve h01-h64, exactly as copied to
`freeze/inputs/tests/headline_cells.txt`, SHA-256
`d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350`.
The frozen launch load ledger hash is
`6c81d71e7db475303b340cd39cfa96929ca5bf708387a6edbf8edf555dc6582e`.
`freeze/h01-h64-plans.json` retains each exact row including its newline and
digest, 64-byte payload, two-million-key population, and its launch load plan or
explicit absence. No standing cell was edited: 512 total connections, GET/SET,
p1/p32, both modes, all read-local/overlap/reorder combinations.

The concrete 14-cell generic null request follows the prior atomiccollapse cleanup:
**h01,h02,h15,h16,h17,h18,h31,h32,h33,h34,h47,h48,h63,h64**. Their exact original
lines are `freeze/generic14.cells.txt`. They do not replace the h01-h64 base guard.

`freeze/feature-regimes.json` appends 112 named requests: seven regimes times
1s/2s, read-local 0/1, databases 1/16, p1/p32. Use DB 0 for databases=1 and
SELECT 15 for databases=16. Each retains 512 connections, 64-byte values,
2,000,000 keys, `--shards 16`, eight server cores, and `--ratio 6:2` for 2s;
overlap/reorder/atomic/key-lb/client-lb=1, flip-auto=0, wb-policy=1, net-io=uring.
These are measurement requests, not additional gate rows.

| Regime IDs (`rm-<regime>-<mode>-rl<N>-db<N>-p<N>`) | Workload / required engagement |
|---|---|
| `neutral-get` | GET without persistence/TLS pressure |
| `small-reply-submission` | SET with small acknowledgements; real submits/completions must occur |
| `aof-always` | SET, appendonly yes / appendfsync always / auto-aof-rewrite-percentage 0; acknowledged-prefix/reply-gate progress |
| `aof-everysec` | Same with appendfsync everysec; written and synced frontiers must advance |
| `bgsave` | SET plus one BGSAVE at central-window T0+5s; independently validate/freeze that trigger schedule and observe completed capture/output |
| `tls-get`, `tls-set` | Corresponding operation; freeze separate kTLS and userspace fallback subarms with active traffic/send/cleanup witnesses |

For userspace TLS, retain the existing gate's cipher selection at
`tests/gate.sh:2330-2331` and its `--expect-ktls no` check. Connections, load-worker
floors, offers, snapshot schedule and transport/subarm settings must be fixed
before candidate measurements. Generic warmup/central/tail windows remain
3/20/5 seconds. Any unsupported workload adapter remains PENDING, never replaced
by an unrelated cell or an unentered-window pass.

The nullrefresh5 instrument is frozen under `freeze/nullrefresh/`:

- Instrument fingerprint: `cc6c06bde1ce7939b7f001489fde7287476c4086929f51badf774811d087dd36`.
- Manifest-file SHA: `ce0967f2e8b932367c3da15f276eec21b561cb8d7ddc11ca31b954671378f683`.
- All 23 dependency files match that manifest, recovered from recorded code
  commit `64fec17603a5a3f9c69c95dfd5efc8e4204caf6d`; the current nullrefresh worktree
  has changed and was not silently substituted.
- Its stable binary is `ef52de792f72ab8dae240fcd8194e1f14aa94b3828dc7e512eea7256b50c1133`,
  based on `9c4717da03b9340377926277f8eb99cea9f5ab5a`, distinct from this lane's PRE.
- The launch ledger separately names reference `5b3d9c429` /
  `76854108e8e5080ae1a8e42e362cb8e071d5796ec29a66ca869397a999ced068`.
  This request's actual stable arm is launch PRE `90ba908d3` and its hash above.

**Instrument qualification and per-cell resolution remain PENDING MAINLINE.**
The retained campaign is 32 server cores/16:16, has no available promoted full-null
or holdout-resolution artifact at the inspected campaign location, and the launch
ledger has no h33-h64 load plans. The frozen launcher derives **64 shards** for
eight-core 1s (`source/tests/abbagate.py:1440`) and exempts p1 from throughput
plateau proof (`source/tests/abba_saturation.py:25-34`). Those facts cannot certify
the requested sixteen-shard geometry or p1 productive-role plateau. The observed
eight-core iteration planning refusal corroborates the missing reviewed geometry.
No missing epsilon or worker floor has been invented, and no candidate measurement
was started against these unqualified settings.

Before measuring POST, mainline must independently validate/freeze the instrument
digest, stable SHA, each cell's resolution, and separate `epsilon_cyc`,
`epsilon_rate`, `epsilon_tail`; establish productive-role plateaus at **both p1
and p32** with sufficient connections/workers; and preserve the reviewed
eight-core/6:2, sixteen-shard geometry. A single connection is not saturation proof.

Run **PRE/POST, PRE/PAD-A, PAD-A/POST** using the named frozen arms and matched
offered loads. For every cell and pair X/Y, require stable-reference parity and:

```text
abs(100 * (Y_cycles / X_cycles - 1)) <= epsilon_cyc[cell]
100 * (1 - Y_rate / X_rate)         <= epsilon_rate[cell]
100 * (Y_tail / X_tail - 1)         <= epsilon_tail[cell]  # each relevant tail
```

No averaging away losing cells or widening a band after POST. Report cycles/op
with instructions/op and IPC together (`cycles/op = instructions/op / IPC`),
rate, p99 and p99.9. The exact PRE/PAD identity supplies a clean instrument null;
it does not turn the two changed POST bytes into a byte-identity pass.

| Required PRE/POST table | PRE cycles/op, instr/op, IPC, rate, tails | POST values | Verdict |
|---|---|---|---|
| Benefit | No gain claimed | No gain required | Cleanup only |
| Neutral GET / generic guards | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |
| Touched: submission-heavy small replies | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |
| Possible deficit: AOF / BGSAVE | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |
| Possible deficit: TLS | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |

**Diff accounting.** The staging-base diff includes the upstream fast-forward;
the launch-base diff isolates this lane. Reported below after staging this report.

```text
$ git diff f9a1d3360 --stat
 MEASURE-REQUEST                       |   36 +-
 MEASURE-REQUEST-cleanup-ringmarker.md |  412 +++++++++
 MEASURE-REQUEST-wbland.md             |  364 ++++++++
 MEASURE-REQUEST-wbland2.md            |  284 ++++++
 MEASURE-REQUEST-wbland3.md            |  285 ++++++
 Makefile                              |   23 +
 docs/CONFIGURATION.md                 |    9 +
 src/cmd/t_server.cc                   |    2 +
 src/core/config.h                     |   19 +-
 src/core/io_loop.h                    |    6 -
 src/core/reorder.cc                   |    1 -
 src/core/server.h                     |    3 +
 src/core/wb_rule.h                    |   23 +-
 src/net/uring.h                       |    5 -
 src/persist/aof.cc                    |    2 -
 src/snapshot/snapshot.cc              |    2 -
 tests/gate.sh                         |   29 +-
 tests/gate_measurements.json          |    8 +-
 tests/netcmd_config_unit.cc           |    7 +-
 tests/wb_rule_checks.py               |   10 +-
 tests/wb_rule_phase_unit.cc           |   33 +-
 tests/wbland_4096_cells.txt           |   13 +
 tests/wbland_checks.py                |  111 +++
 tests/wbland_clause_unit.cc           |   10 +
 tests/wbland_evidence.json            | 1633 +++++++++++++++++++++++++++++++++
 tests/wbland_merit_cells.txt          |   14 +
 tests/wbland_unit.cc                  |   78 ++
 tomokv.conf                           |    5 +
 tools/ringmarker_proof.py             |  225 +++++
 tools/wbland_artifacts.py             |  161 ++++
 30 files changed, 3757 insertions(+), 56 deletions(-)
```

```text
$ git diff 90ba908d3 --stat
 MEASURE-REQUEST-cleanup-ringmarker.md | 412 ++++++++++++++++++++++++++++++++++
 src/core/io_loop.h                    |   6 -
 src/core/reorder.cc                   |   1 -
 src/net/uring.h                       |   5 -
 src/persist/aof.cc                    |   2 -
 src/snapshot/snapshot.cc              |   2 -
 tools/ringmarker_proof.py             | 225 +++++++++++++++++++
 7 files changed, 637 insertions(+), 16 deletions(-)
```

Remaining work belongs to mainline: the live correctness batteries/boots/gate and
qualified PAD-controlled null. This lane stops after this committed report.
