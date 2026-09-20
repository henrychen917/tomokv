# SORT STORE namespace fix — mainline handoff

Worktree `/home/user/Projects/cx-sortstore`, branch `cx-sortstore`. Implementation and regression commit: `75c45f1a7`. Launch HEAD was `f3cf0fc91`, whose parent is the requested `b8fe404e2`; the intervening commit only rebaselines `tests/gate_measurements.json`. That inherited change is included in the requested base diff below and was not edited by this lane.

The candidate, PRE server, and fix-removed server/unit controls are built. All builds and Python syntax compilation were pinned to cores 112–127; make used `-j16`. **The proof binaries, live checks, Redis differ, gate, servers, benchmarks, and performance measurements were not run**, following “PROOFS TO BUILD (mainline runs them).” Runtime positive and negative results below are explicitly PENDING. This report makes no gate-green or performance claim.

**Verified diagnosis and the scoped change**

Before editing, `src/cmd/cmdmeta.cc` scanned every argv word for STORE. The actual execution parser at `src/cmd/xshard_commands.inc:233–283` consumes BY/GET pattern operands and LIMIT's two operands. Consequently `SORT src STORE dst BY STORE LIMIT 0 2` gives metadata indexes `[1,6]` instead of execution indexes `[1,3]`; the stamp fallback at `src/cmd/multidb.cc:148–153` then namespaces LIMIT rather than dst. With logical 1 mapped to physical 9, source gets 9, destination incorrectly stays 0, and LIMIT gets 9.

The requested `/home/user/Projects/cx-mdbstamp/build/mdbstamp-controls/` and its parent worktree no longer exist; searching the project tree found neither `sort-oracle.cc` nor `sort-existing-defect.log`. The retained [mdbstamp report](MEASURE-REQUEST-mdbstamp.md:234) contains the exact oracle initializer and its recorded PRE/POST failures:

```text
sort-pattern-store-word argv[3]: ns=0 expected=9, bytes/pointer=same
sort-pattern-store-word argv[6]: ns=9 expected=0, bytes/pointer=same
FAIL mdbstamp: sort-pattern-store-word
```

That is inherited evidence from the previous lane, not a run performed here. The new shared corpus recreates exactly that input and expected key indexes.

Only the SORT branch of `src/cmd/cmdmeta.cc` changes in production: skip one operand after BY/GET and two after LIMIT. Preserve case-insensitivity, the final STORE selection, key intent flags, SORT_RO handling, and permissive GETKEYS behavior on malformed execution syntax. No stamp, boundary, execution parser, layout, or other metadata case changes. Sharing the full execution parser would import validation/reply behavior into metadata; instead, the unit includes the actual execution parser through the existing `multidb_unit.cc` fixture and cross-checks it without a production test hook.

**Redis source matched**

Local Redis source is 7.4.10 (`src/version.h`), git HEAD `f103d127b`:

| Source | Matched behavior |
| --- | --- |
| `/home/user/Projects/redis/src/commands/sort.json:9` | SORT delegates key extraction to `sortGetKeys`. |
| `src/commands/sort.json:20–64` | Source is RO/access; BY/GET and STORE searches are unknown in the declarative specs; destination intent is OW/update. |
| `/home/user/Projects/redis/src/db.c:2575–2578` | Source key is argv[1], with RO/access. |
| `src/db.c:2580–2598` | Skip list: LIMIT consumes 2, GET consumes 1, BY consumes 1; comparisons ignore case. |
| `src/db.c:2599–2611` | Last recognized STORE supplies destination with OW/update. |
| `src/db.c:2548–2558` | SORT_RO exposes only source argv[1]. |
| `/home/user/Projects/redis/src/server.c:5056–5093` | COMMAND GETKEYS/GETKEYSANDFLAGS use this extraction after command/arity checks; they do not run SORT's syntax parser. |

**Built proofs and negative controls**

`tests/sortstore_cases.tsv` is shared by the C++ parser/stamp unit, the Redis comparison, and the SORT differ. It has 61 valid shapes plus 4 deliberately malformed shapes that execution must reject while metadata follows Redis's permissive extraction. Valid shapes include plain SORT, BY, GET(s), STORE, both STORE placements, BY+GET+STORE, repeated STORE/BY, SORT_RO, mixed case, and every requested keyword used as a BY/GET pattern: STORE, BY, GET, LIMIT, ASC, DESC, ALPHA. Malformed LIMIT operands exercise the additional Redis skip rule directly.

`tests/sortstore_controls.py` verifies that removing exactly the new SORT skip block reproduces `b8fe404e2:src/cmd/cmdmeta.cc`. It compiles that source in both namespaces and relinks with the candidate's remaining objects, including the identical positive test object. Production files are never mutated by the control builder. All four compile/link steps completed with exit 0. The default invocation builds only; `--run-units` is reserved below for mainline execution.

| Assertion | Positive proof | Negative control and required result | Actual runtime result |
| --- | --- | --- | --- |
| (a) Exact argv key indexes `[1,3]`, metadata agrees with the real execution parser | `build/multidb-unit --sortstore-check oracle-keys`; also checks COMMAND wrapper offsets and intent flags | `build/multidb-unit-sortstore-nofix --sortstore-check oracle-keys` must exit 1 with `FAIL sortstore: oracle: metadata/execution key indexes` | PENDING mainline; both binaries built |
| (a) Only argv[1]/argv[3] have namespace 9; LIMIT and all other operands retain 0; bytes/pointers unchanged | `build/multidb-unit --sortstore-check oracle-stamp`; tests published and explicitly supplied 1→9 maps | Same selection on the nofix unit must exit 1 with `FAIL sortstore: oracle: only actual keys stamped; LIMIT untouched`; expected diagnostics show argv[3]=0 and argv[6]=9 | PENDING mainline; prior mdbstamp report records the same failure on both its PRE and POST |
| (b) All 61 valid shapes agree with execution; all 65 metadata/stamp cases match explicit expected indexes, flags, and namespaces | `build/multidb-unit --sortstore-check battery` | Same selection on nofix must exit 1 at the exact oracle's metadata/execution assertion | PENDING mainline |
| (b) Both COMMAND GETKEYS and GETKEYSANDFLAGS agree with Redis 7.4 for those same 65 inputs | `tests/sortstore.py ... --check keys --oracle-port PORT`; validates Redis version and expected replies as well as target/reference equality | Nofix server must fail `oracle target GETKEYS`: expected `[src,dst]`, old result `[src,LIMIT]` | PENDING mainline |
| (c) SELECT 1/populate/SORT/immediate destination read on one pipelined connection; destination absent in DB 0 | `tests/sortstore.py ... --check live`; also integrated into `tests/multidb.py` | Nofix server must fail the first oracle's DB-1 LRANGE assertion, expected `[3,1]`; DB 0 must never contain the destination on POST | PENDING mainline |
| Existing SORT Redis differ, including exact oracle command and all 130 key-metadata commands | `tests/differ.py TARGET PORT REDIS PORT sort 7` (and `-3`) at split 6:2 geometry | Same differ against nofix must report a mismatch for COMMAND GETKEYS/GETKEYSANDFLAGS on the oracle | PENDING mainline |

SORT STORE produces a **list**. GET dst therefore must return WRONGTYPE, not a sorted array. The live proof checks LRANGE contents, TYPE=list, GET=WRONGTYPE, and EXISTS/LRANGE absence in DB 0. Also, a globless `BY STORE` suppresses sorting: with source `[3,1,2]` and LIMIT 0 2 the correct oracle result is `[3,1]`. A separate `BY sortstore:weight:*` shape produces `[1,2,3]`; a GET pattern literally STORE checks the second affected grammar branch. Every shape starts with absent destinations in both databases, so stale results cannot conceal a misplaced write. The fixture drains all pipeline replies before asserting.

**Mainline execution commands**

Run from the worktree root. The unit control driver executes no server and checks each required failure signature, not merely a nonzero status:

```sh
taskset -c 112-127 make -j16 all build/multidb-unit
taskset -c 112-127 python3 tests/sortstore_controls.py --run-units
```

Logs and actual unit results will be written under `build/sortstore-controls/`, including `unit-results.json`. There is currently no `unit-results.json`, because the assertions have not run.

For the live proof, mainline should boot each server arm separately on eight cores (for example 112–119) using `--thread-mode 2s --shards 16 --ratio 6:2 --databases 16 --enable-debug-command yes`. Use its own quiet-box scheduling and a Redis 7.4 oracle. The helper checks the reported eight threads, sixteen shards, six IO/two executor roles, and configured database count. With candidate/nofix listening on port 6395 and Redis on 6396:

```sh
taskset -c 120-127 python3 tests/sortstore.py 127.0.0.1 6395 --check keys --oracle-port 6396
taskset -c 120-127 python3 tests/sortstore.py 127.0.0.1 6395 --check live
taskset -c 120-127 python3 tests/differ.py 127.0.0.1 6395 127.0.0.1 6396 sort 7
taskset -c 120-127 python3 tests/differ.py 127.0.0.1 6395 127.0.0.1 6396 sort 7 -3
```

POST requires exit 0 throughout. Reboot with `build/tomokv-sortstore-nofix` and repeat: each command must fail on the corresponding oracle assertion/difference described above. The live checker intentionally uses a separate invocation so a GETKEYS failure cannot substitute for demonstrating the namespace failure. Repeat the live proof on the fused eight-core boot with `--thread-mode 1s` supplied to both server and checker. The existing multidb gate matrix additionally runs the live regression in both thread modes, both atomic settings, and both read-local settings. Mainline owns both-mode boots, the Redis differ verdict, and `tests/gate.sh iteration`; none have been claimed green here.

**Gate accounting**

No gate rows were added or retired; `tests/gate.sh` and its EXPECT constants were not changed. By actual line position: the existing multidb unit row is at line 1298 and collected at 2684; the live multidb rows are collected at 2785; both are before the quick-tier exit block at 2808–2813. The existing split differential row is collected at 2840, after that exit. Assertions were added inside those existing rows. Therefore the expected counts remain **QUICK 438, FULL 454** (delta 0 in each tier).

**db0 code generation and static PRE/POST evidence**

Yes, the db0 variant's code generation changes: it also implements COMMAND key introspection, so its cold metadata extractor contains the corrected scan. The compiled-out stamp remains unchanged. `cmp` confirmed the entire `build/db0/src/cmd/multidb.o` is byte-identical to the saved PRE object; both `multidb_stamp` overloads are exactly `f3 0f 1e fa c3` (`endbr64; ret`). That identical object's SHA-256 is `de8a3a8a624f12692d6fd4aa2e0a7d8a46fa9a9e6349f2b97af0ef4c6eaebeca`.

| Static artifact (bytes) | PRE | POST | Delta |
| --- | ---: | ---: | ---: |
| Multi-DB `command_metadata_collect_keys` symbol | 5,017 | 5,253 | +236 |
| db0 `command_metadata_collect_keys` symbol | 4,997 | 5,237 | +240 |
| Linked binary `.text` | 7,426,003 | 7,426,483 | +480 |
| Each db0 `multidb_stamp` overload | 5 | 5 | 0 |

The static audit is saved as `build/sortstore-controls/codegen.json` and per-overload `.asm` files. No data structure/layout changes or PAD arm are part of this correctness fix. These byte counts are not timing, cycles/op, or rate evidence; linked placement changes and runtime effects remain for mainline to assess.

Build logs: `build/sortstore-controls/build-pre.log`, `build-post.log`, `build-proof.log`, and `build-controls.log`. Both namespaces compile and link. Existing compile-time layout assertions compile as part of the multidb unit. Python syntax compilation and `git diff --check` passed; `make -q all build/multidb-unit` returned 0. No proof assertions were executed.

```text
sha256sum build/tomokv
f25702987da600f3bee903e884d4a10f47b758dcffcb7498fbecc1261dd52e11  build/tomokv

0e9c9ea2070d1d4c5274cba6db9b8819502e12a423474b10f3eb71a6a561c99f  build/tomokv-sortstore-pre
0587a2f4d270e4731456c2d26ff98afe9fb919ea8fa04d04bb133561831efbf4  build/tomokv-sortstore-nofix
c72452f542fac8aa0daba26f5b055528cdc7fc9b0d0e37579632c76d43a81296  build/multidb-unit
87c9498f28251aa8797ecee06411d481cd1f36587969cc52c5ddcdb281b008ea  build/multidb-unit-sortstore-nofix
```

**Additional remaining correctness path (source inspection, not a live result)**

Redis 7.4's extractor does not consume the STORE destination operand. For valid `SORT src STORE STORE LIMIT 0 2`, both Redis's metadata scan and TomoKV's corrected metadata still select indexes `[1,4]`, while execution selects `[1,3]`. The selected-DB stamp can consequently leave the actual destination named STORE in physical DB 0 and stamp LIMIT instead. This separate pre-existing destination-keyword case is outside the requested BY/GET fix; changing the extractor to consume STORE operands would diverge from the explicitly required Redis 7.4 GETKEYS behavior. It is reported because it can violate the namespace/RYOW law, and is not included in a claim that all possible SORT argv are fixed. Resolving it needs a separate decision about execution-key stamping versus compatibility metadata.

**Requested diff statistic**

Command: `git diff b8fe404e2 --stat` (includes the inherited reference rebaseline and this tracked report).

```text
 MEASURE-REQUEST-sortstore.md | 126 ++++++++++++++++++++++++++++++++++++++
 Makefile                     |   2 +-
 src/cmd/cmdmeta.cc           |  10 ++-
 tests/differ.py              |   9 +++
 tests/gate_measurements.json |   8 +--
 tests/multidb.py             |   2 +
 tests/multidb_unit.cc        |   6 ++
 tests/sortstore.py           | 129 +++++++++++++++++++++++++++++++++++++++
 tests/sortstore_cases.tsv    |  67 ++++++++++++++++++++
 tests/sortstore_checks.inc   | 142 +++++++++++++++++++++++++++++++++++++++++++
 tests/sortstore_controls.py  |  93 ++++++++++++++++++++++++++++
 11 files changed, 588 insertions(+), 6 deletions(-)
```
