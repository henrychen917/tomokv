## readability-a5

Branch `cx-readability-a5`, based on `9a09e5919092cc5e33aaf1e49e55994bdf8439b5`.
Production reference: the maintainer's frozen `5c3631281815c1652b3894d1736840c8466a5015`
binary at `/home/user/Projects/bins/readability-pre-5c363128/tomokv`.
No push, throughput measurement, new measurement arm, or gate-row change.

### Changes

The nine owned files describe current behavior, ownership, publication ordering,
preconditions and failure handling. Configuration comments give actual defaults,
units and the parser's 0/-1 meanings, including exceptions to the general knob
convention. Contracts distinguish checked failures, exceptions, partial state,
retry/back-pressure and invariant aborts. Plain read-local statistics do not
establish a general race-free concurrent snapshot; the comment says so.

Historical evidence and decisions are retained in
[the dated decision log](docs/decisions/readability-a5.md). These are source
provenance, not newly verified performance results. String literals, generated
blocks, includes, definitions, field layouts and tool markers are unchanged.

| Owned file | Rewritten comment groups | Contracts | Phase landmarks | File header |
|---|---:|---:|---:|---:|
| `cfgfix.cc` | 2 | 3 | 0 | 1 |
| `cfgfix.h` | 0 | 0 | 0 | 1 |
| `config.h` | 71 | 11 | 5 | 1 |
| `live_config.h` | 3 | 5 | 0 | 1 |
| `server.h` | 81 | 19 | 8 | 1 |
| `shard.h` | 19 | 5 | 0 | 1 |
| `thread.h` | 34 | 8 | 0 | 1 |
| `version.cc` | 2 | 0 | 0 | 1 |
| `version.h` | 0 | 0 | 0 | 1 |
| **Total** | **212** | **51** | **13** | **9** |

A comment group is all comments at one preprocessing-token boundary. Rewrites
count existing groups whose text changed; new groups do not inflate that count.
Contracts/headers can replace an existing group, so columns are not additive.
The [contract inventory](docs/readability-a5/evidence/contracts.json) contains
38 class/struct contracts and 13 function contracts. The eleven functions over
50 non-comment lines are `cfgfix_process_boot`, `parse_config_args`,
`validate_config`, `cfg_split_args`, `load_conf_file`, `ReadLocalStats::note_fallback`,
and Server's `init`, `flip_build_client_plan`, `flip_reserve_shard_plan`,
`flip_begin`, and `transfer_bucket_range_quiesced` (51 including its signature).
`parse_config_args`, `Server::init` and `Server::flip_begin` have phase landmarks.
Rename count: **0**. Interface-first splits kept/reverted: **0/0**.

### Interface-first scope

No split is kept. The requested topic header would add a tenth production file,
outside the explicit nine-file ownership list (whose only stated exception is R7
regeneration). A scope question was submitted; no exception has been granted.
No class body was moved and no split candidate was built or reverted. All tool
path anchors and PAD sites remain in their original files. The comments and
contracts provide the interface documentation within the allowed files.

### A19 rename proposals

No renames were applied. These names cross this lane's boundary:

| Existing name | Proposed name | Reason and coordination |
|---|---|---|
| `Role::Ifid` | `Role::Io` | Match the runtime's IO/EX terminology; update all users and tool expectations together. |
| `Config::even_ifid` | `Config::even_io` | Name the IO count directly; coordinate placement/parser callers. |
| `cfgfix_process_boot`, `cfgfix_process_ready` | `process_services_boot`, `process_services_ready` | Describe the lifetime hooks rather than a historical fix; coordinate main/CONFIG callers. |
| `Server::climon_armed()` / `climon_armed_` | `client_observers_armed()` / `client_observers_armed_` | Describe the shared CLIENT/MONITOR/TRACKING gate; preserve the stable binding and update source controls. |

### Verification

Verification is restricted to CPUs 64–95 and ports 25300–25399, with `LC_ALL=C`.
The build also pins `TOMO_INFO_GIT_SHA1=5c363128` and `TOMO_INFO_GIT_DIRTY=0`.
The reference binary is never rebuilt. The binary comparator strips debug/symbol
information and the build-id note before comparing executable artifacts.

```sh
export LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0
taskset -c 64-95 make -j32 all
taskset -c 64-95 /home/user/Projects/calib/binary-neutral.sh \
  /home/user/Projects/bins/readability-pre-5c363128/tomokv build/tomokv
```

Output from the final source build:

```text
IDENTICAL (11167504 bytes after stripping)
```

[Token proof](docs/readability-a5/source_proof.py) compares the raw preprocessing
tokens against both the lane base and frozen release. It also checks byte-exact
literal spellings and exact tool-marker text/placement at token boundaries.
[Build proof](docs/readability-a5/build_proof.py) derives the 61 primary targets
from `job_production_units`, builds its supplemental targets and queries each
concrete output with `make -q`.

Final results:

- **68/68 build/freshness checks:** `all`, all 61 primary production-unit targets,
  both MDB witness builds, blockfix cost plus its binary digest, and both blockfix2
  namespaces. Every concrete `make -q` query also passes after the gate jobs;
  default `make -q` passes. [Target inventory](docs/readability-a5/evidence/builds.json).
- **19 passing gate rows, zero failures:** 6 source/instrument rows, 6
  configuration/identity rows and 7 production-unit rows. The release-build row
  appears in both latter selections. Every selected job exits zero.
  [Per-job results](docs/readability-a5/evidence/gate-results.json) and
  [exact commands/environment](docs/readability-a5/evidence/gate-commands.json).
- `tests/gates_test.py`: **83 tests, OK**. Label-fixture unittest:
  **12 tests, OK**, invoked by the gate's receipt self-test.
  [Recorded unittest output](docs/readability-a5/evidence/gate-unittest-summary.txt).
- Source identity: **61 C++ translation units in both database variants plus
  six shared C units**, pass; **11 assertion/identity tests**, pass, including
  directed abort-to-source mapping. R7 reports **352/352 identical bodies** and
  passes generated synchronization, negative controls and engagement in both
  database runtimes.
- Pinned clang-format **18.1.8**, **418 files** checked; `make format` and
  `make format-check` pass before every commit.
  [Formatter output](docs/readability-a5/evidence/format-check.log).
- All nine raw token streams match both PRE revisions, literal spellings are
  byte-identical, and all tool comments retain their exact token boundaries.
  [Token/literal proof](docs/readability-a5/evidence/tokens.json).

The first production-unit build was interrupted to finish the boundary-length
transfer contract. The complete build/freshness audit above was then rerun on
the final source; no interrupted result is counted as passing evidence.

The source-tool matrix uses A2's CPU-restricted adapter for A1's 52 cases. All 52
positive cases pass and all 52 broken-anchor controls are rejected. The 313
emitted normalized token streams match A1's recorded manifest exactly. The
temporary source copies are removed after recording evidence.

Relevant A1 LIVE text-matching coverage:

| Input or tool | Gate job / evidence |
|---|---|
| `cfgfix.cc` / `tests/cfgfix.py` | `cfgfix`: CONFIG oracle parity across modes and engines |
| `config.h` / docs/parser checks | `config_unit`: documentation inventory and parser tests |
| `config.h` / `tests/serverfix_config.py` | `serverfix_config`: CONFIG validation inventory and runtime matrix |
| `server.h` / LB controls | `lbplanner_units` and its `production_units` builders; offline PAD source proof in the 52-case matrix |
| `server.h` / Climon witness builder | `racefix_climon` and its `production_units` prerequisite |
| `server.h` / writeback source checks | `wbland_units`: clause/path witnesses and planted controls |
| `thread.h` / inbox extraction | `rootcore-inbox`: five extracted production inbox controls |
| `server.h`, `thread.h` / lottery builder | `reorder_sync`: lottery insertion-site and absent/duplicate seam tests; source-only matrix |
| All owned source / assertion and token tooling | `source_identity`, release assertion map, `reorder_sync` lexer/marker tests |
| R7 generated envelopes and executable identity | `reorder_sync`, `reorder_identity`, `reorder_engagement` |
| Gate scheduler and label fixture | `abba_selftest`, which invokes `tests/gates_test.py` and `gate_receipt.py --self-test`; the latter invokes all `gate_ledger_fixture.py` unittests |
| Metadata generators | `acl_metadata`, `cmd_metadata`, and the 52-case matrix |

The generators' `version.h`/`server.h` input paths belong to the Redis oracle
tree, not the owned TomoKV files. `tools/blockfix3_controls.py` contains the C++
expression `shard.has_blocking_waiters()` rather than an input path to `shard.h`.
These distinctions avoid treating a substring hit as a dependency.

The three selected gate invocations use this common command and environment:

```sh
export LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0
export GATE_TEST_PORT=25399 GATE_PROOF_NO_RATES=1
for jobs in \
  'config_unit acl_metadata cmd_metadata abba_selftest reorder_sync' \
  'cfgfix serverfix_config source_identity rootcore-inbox reorder_identity' \
  'lbplanner_units wbland_units racefix_climon reorder_engagement'; do
  GATE_ONLY_JOBS="$jobs" taskset -c 64-95 tests/gate.sh iteration \
    --server-cores 64-79 --load-cores 80-95 --load-smt '' --ports 25300-25398
done
```

Each selection runs separately with a separate partial ledger. The gate retains
its eight-core, 16-shard, 6:2 correctness geometry. Selecting `abba_selftest`
executes serverless instrument tests, not ABBA measurements. These partial jobs
do not certify a full release gate.

NOT RUN: full iteration/release gate, benchmarks, throughput/latency measurements,
interface-first split experiment. No PAD arm is requested. Existing offline PAD
source checks use kind A behavior twins (PRE behavior with candidate layout).
`EXPECT_QUICK` and `EXPECT_FULL` are unchanged; the row delta is zero on each side
of the quick-tier exit (counts remain 1212/1229).
