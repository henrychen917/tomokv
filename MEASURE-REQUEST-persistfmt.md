## persistfmt

Lane `cx-persistfmt`, based on `e32b04a445b056976abb308aa598e356fcbaae74`.
No push. Correctness runs use CPUs 96–111, ports 20500–20599 and `LC_ALL=C`.
This report is being completed while the corrected candidate's final validation
runs. The arm manifest and FINAL5 instruction receipts below describe the corrected
NOFLUSH/SWAPDB build, based on production-source commit `fd1d24ca6`.

### Changes and PRE witnesses

The first two commits add witnesses and a build-only scheduling control without
production changes. `docs/persistfmt/pre-directed.tsv` and the archived PRE gate
logs record the failures on the base binary:

| Witness | PRE result |
|---|---|
| Stream round trip, both interchange directions, RESTORE options/errors | All 12 mode/engine rows fail |
| Function SAVE, BGSAVE, SHUTDOWN SAVE, DEBUG RELOAD, AOF rewrite with preamble | All 20 mode/engine rows fail |
| AOF rewrite without preamble | Oracle completes; all four TomoKV boots reject the unsupported option |
| Scheduled always-fsync write failure | Both split-engine rows receive the forbidden `+OK`; fused rows are controls and already pass |

The S1 control uses the existing RLIMIT_FSIZE fault. A build-only rendezvous puts
the off-writer reply past its initial failure check, then a full stderr pipe holds
the writer inside `fail()`. The test requires that exact blocked diagnostic window
before checking the socket; failure to arm is a failure. No scheduling hooks enter
the production binary. The root fix moves `recording_ = false` after the fatal
`_exit(1)` branch. The reply gates gain no instructions.

DUMP now writes Redis RDB stream type 21 (stream-listpacks v3), version 12 and
Redis CRC64. RESTORE accepts types 15, 19 and 21, including listpack/LZF encodings.
Entries, tombstones, first/last IDs, entries-added, max-deleted-entry-id, consumer
groups, entries-read, consumers' seen/active times, PEL ownership, delivery times
and delivery counts survive interchange. The directed comparison uses XINFO
STREAM FULL and XPENDING. It excludes physical radix-tree statistics and elapsed
XPENDING idle milliseconds; persisted absolute times are compared exactly.

Streams use the existing REPLACE/ABSTTL/TTL/IDLETIME/FREQ command path. Envelope
failures return `ERR DUMP payload version or checksum are wrong`; CRC-valid bad
bodies return `ERR Bad data format`. The ten-byte, empty-body envelope boundary
now follows Redis too. Legacy Redis 5/7 stream fixtures, multiple listpack nodes, and signed ID-delta
boundaries run against both servers. The oracle must actually create multiple
nodes for that case to pass.

Function libraries are captured once at the snapshot cut as Redis FUNCTION2
opcode/string records. They are compiled and installed during recovery, including
the native AOF rewrite base. DEBUG RELOAD supports NOSAVE, NOFLUSH and MERGE and
applies the corresponding library replacement rules. Source review exposed an extra
NOFLUSH/SWAPDB defect: restoring the saved physical namespace map would relocate
retained keys. A directed oracle witness failed in all four TomoKV mode/engine
legs. NOFLUSH now translates incoming records into the live namespace map and
rebuckets them before owner dispatch. Retained live objects remain in place.
The ordinary save/load loops do not run this administrative preparation. FUNCTION LIST comparisons
canonicalize only outer library iteration order; code and library/function metadata
remain exact. An empty library registry
adds no serialized extension and allocates no library image.

The obsolete stream-refusal assertions in dumprestore, streamgroups and wiredump
are replaced by round trips/interchange. The AOF snapshot model now honors the
declared header length while retaining its shard-byte comparison. Three Tcl
assertions move from skips to expected passes:

- `Consumer seen-time and active-time`
- `FUNCTION - test debug reload different options`
- `FUNCTION - test debug reload with nosave and noflush`

The existing “test loading from rdb” assertions did not expose the lost-on-restart
registry: they exercised a live DEBUG RELOAD while the old registry remained in
memory. The new witnesses kill and restart the process after each persistence
operation. Upstream legacy stream/AOF tests later in `stream-cgroups.tcl` remain
blocked by its known `CONFIG SET appendonly` setup error; they are not falsely
promoted. Their type-15/type-19 payload fixtures are exercised by the new gate
interchange rows. `RESTORE fail with invalid payload size` also remains skipped
because it uses unsupported `DEBUG SET-SKIP-CHECKSUM-VALIDATION`; the new row tests
both invalid envelopes and checksum-valid malformed stream bodies directly.

### Format boundary and retained differences

TomoKV snapshot files are **not Redis RDB files**. Their magic is `TOMOSNP\0`,
with native routing/hash metadata, checksummed FRAM sections, RECD objects and a
DONE footer. The normal header is 80 bytes; a DB map adds 256 bytes; FUNCTION2
records follow that map when libraries exist. The extension checksum covers both
the map and function records. Old 80/336-byte native headers remain loadable.
Files with neither libraries nor a nonidentity DB map retain the old header.
Redis cannot load this container, and TomoKV's snapshot loader cannot load Redis's
`REDISxxxx` container. No RDB cross-load row was added. Redis compatibility here
is the DUMP object envelope and the FUNCTION2 record encoding inside the native
container, not whole-file RDB compatibility.

Retained differences and additional findings:

- `aof-use-rdb-preamble no` remains unsupported: the existing AOF format requires
  a native snapshot base and uses `TOMOAOF` increment records, not a RESP command
  log. The PRE boot rejection was witnessed. **The requested no-preamble POST
  restart leg is NOT RUN because that format does not exist.** Implementing a
  second AOF container/replayer is not included in this snapshot-library change.
- FUNCTION DUMP/RESTORE still uses the existing `TOMOFUN1`/FNV envelope, whereas
  Redis uses FUNCTION2 records plus its RDB version/CRC trailer. Each server's own
  round trip passes. Cross-restores fail in both directions with
  `ERR DUMP payload version or checksum are wrong`; transcripts are archived.
  This adjacent parity gap is reported without changing that command's format.
- FUNCTION LOAD/DELETE/FLUSH mutations after creation of an AOF base are not
  recorded in native increments. Rewrite captures the registry; an ordinary
  restart before rewrite can still lose those later mutations. This existing
  adjacent AOF gap is not fixed here.
- There is no `sanitize-dump-payload` configuration in TomoKV. The stream decoder
  always validates structure, listpack back-counts, metadata, and PEL references.
- IDLETIME/FREQ retain the existing other-type behavior: syntax/range checks and
  replies match, but the supplied idle/frequency values are not restored into
  eviction metadata. Stream radix-tree physical statistics differ because TomoKV
  has a different stream representation. Logical stream state is preserved.
- The owner's root-cause audit marks cross-shard DEBUG RELOAD/LOADAOF keyspace
  tearing (D12.6) as deferred. This lane retains that existing owner-dispatch
  protocol and does not claim to make those administrative keyspace reloads
  globally atomic. Library installation itself replaces the registry atomically.

### Validation and instruction counts

Final correctness validation is still running. These are partial job-interface runs,
never a full `iteration`, a throughput benchmark, or a push receipt. EXPECT_QUICK
and EXPECT_FULL are unchanged.

Completed on the corrected, frozen POST:

- Tcl passing-subset job in both modes: 1,820 passing assertions per mode, including
  all three promotions. Its five existing setup errors per mode remain explicitly
  inventoried; no new skip or known-failure allowance was added.
- `python3 tests/gates_test.py`: 76/76 pass on the quiet rerun. The earlier attempt
  under compilation/trace contention hit nine scheduler deadlines; both logs remain.
- `make -k -j16 all` with all 51 main `job_production_units` targets, plus the
  live-arm and supplemental cost/blockfix targets: pass. All 56 `make -q` checks
  pass, including `all`; the inherently phony live-arm target is verified by its
  successful build and inner builds. Receipts are `all-production-build.json` and
  `freshness.json`. The main binary still matches frozen POST.

The scheduler self-test covers unchanged gate code and was completed before the
last C++ namespace correction. The Tcl and build receipts above were repeated
after that correction and name the delivered POST hash.

The first debug-compression sweep changed some unit executable timestamps, leaving
three aggregate readiness markers absent. This was an artifact-handling failure,
not a green build receipt. Real make targets have since been rebuilt and checked;
the affected AOF frame-order job is included in the later complete-job rerun.
No readiness marker is manufactured.

Earlier candidate runs are retained separately from final validation. Four AOF
byte-model rows initially failed because the test assumed an 80-byte header; it
now reads the declared header length and still compares shard bytes. The new
library restart rows independently compare FUNCTION LIST WITHCODE. Two directed
fused wire-value rows initially failed because that harness passed `--ratio` to a
1s boot; fixing the boot grammar produced a complete 40-row pass. One intermediate
fused Tcl BRPOPLPUSH/WATCH assertion failed; the final complete Tcl job passed in
both modes without changing that assertion or adding an allowance. These attempts
are visible in the archived logs rather than counted as final passes.

The first final-POST AOF run exposed a misplaced test edit: the variable snapshot
header offset had been put in the AOF increment parser, where its helper was
undefined, while the snapshot model still used 80 bytes. This caused twelve
public failures across the two engines (including dependent restart/model rows).
The increment parser is restored to its fixed 80-byte header, and only the
snapshot model reads the declared metadata length. Both complete AOF jobs are
included in the later rerun, with all their mode/atomic legs. This changes no
production bytes and removes no assertion.

The instruction instrument is `tools/persistfmt_counts.py`: the existing bounded
production command scope plus a snapshot save/load-loop fixture, under ptrace.
It covers GET/SET/INCR/MGET/MSET at batch 1 and 32, 1s/2s, both namespaces, atomic
0/1 (80 cells), with eight-key MGET/MSET. The counter includes symbols naming the selected TomoKV namespace, including
C++ templates parameterized by its types. External shared libraries, standalone
STL/helper symbols outside that set, and fixture setup are excluded equally in
both arms. The generated address ranges and raw trace sites are retained for
scope auditing. The snapshot fixture covers both modes/namespaces at 1/32
keys; marginal cost is `(count32 - count1) / 31`. It measures the per-key loop,
excluding once-per-file header and function-registry work. No rates are inferred.

Final production census (`counts/FINAL5`, full table `docs/persistfmt/instructions.tsv`):

| Command | Cells | POST − PRE instructions/op |
|---|---:|---:|
| GET | 16 | 0 |
| SET | 16 | 0 |
| INCR | 16 | 0 |
| MGET | 16 | −6 to −1 |
| MSET | 16 | −8 to −2 |

The snapshot counts below are identical in 1s and 2s. `n=1/32` are whole scoped
calls; the marginal column isolates per-key work from fixed scan/call overhead.

| Namespace/loop | PRE n=1 / n=32 | POST n=1 / n=32 | PRE → POST marginal instructions/key |
|---|---:|---:|---:|
| normal save | 26373 / 46027 | 26373 / 46027 | 634 → 634 |
| db0 save | 26372 / 45995 | 26372 / 45995 | 633 → 633 |
| normal load | 1006 / 25933 | 1003 / 25899 | 804.0968 → 803.0968 |
| db0 load | 899 / 24928 | 901 / 24930 | 775.1290 → 775.1290 |

Thus no ordinary command gains instructions and neither snapshot loop gains
instructions per key. db0 loading has **two added fixed wrapper instructions per
shard**, shown explicitly above. Library capture/installation has additional
fixed per-file work; no claim of zero total save/load overhead is made. Compiler
IPA deltas and bounded budget trials are retained in `snapshot-ipa.json`,
`snapshot-budgets.json`, and the count receipts. The broad flattening trial was
discarded; production uses a small per-unit budget adjustment.

All eight locked layouts remain 336/1984/1408/1440/944/192/144/624 bytes.
SnapshotManager grows by 24 bytes and SnapshotLoadPlan by 32 bytes in both
namespaces. Server's total size is unchanged, but the following FlipController,
shard-owner array and flip-stage fields move by 24 bytes. PAD-A has the POST
offsets. This is a reason to retain the null measurements even though instruction
counts pass. Layout receipts are in `docs/persistfmt/layouts.json`.

The two new public jobs are collected before the quick-tier exit: `persistfmt`
has ten cases × two modes × two engines = 40 rows; `persistfmt_aof_error` adds
four rows. **DQ=+44, DF=+44.** From this base's 977/994, the maintainer's expected
counts become **1021/1038**. Promoted Tcl assertions and changed existing batteries
add no public gate rows.

### Maintainer measurement request

Use the PRE/POST/PAD-A paths and SHA-256s in the final `docs/persistfmt/arms.json`.
PAD-A is **kind A, behavior twin**: PRE persistence behavior with POST structure
layouts and equal total `.text`/`.rodata` sizes. Padding is unreachable. Individual
function addresses are not promised identical. `tools/persistfmt_pad.py` records
the source changes, compile/link recipes and padding sizes.

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/persistfmt/PRE/tomokv` | `f804556e1b0dc0c06d9f3cb1c6d9dbb6430797d5043d154b4f139da3e09980fc` |
| POST | `build/persistfmt/POST/tomokv` | `a5a0dc67fb584cab2b9c01ffd137f167913316dd287e338290ab9f4b3b61c41c` |
| PAD-A | `build/persistfmt/PAD-A/tomokv` | `3fb52911e2d89f41384b259a494a3fa012742ff77285569fd86b90cea2e392c7` |

PRE `.text` is 8,729,431 bytes; POST and PAD-A are 8,777,543 bytes (+48,112).
POST/PAD-A `.rodata` are both 638,348 bytes; `.data` and `.bss` also match.
PAD-A contains 35,888 unreachable text bytes and 320 read-only padding bytes.
Assertion-map sidecars accompany each binary.

Run the 18 cells frozen in `docs/persistfmt/merit.cells.txt`: the unchanged 14
from `tests/wbland_merit_cells.txt`, plus `h53,h54,h21,h22` (2s GET/SET p1/p32)
as null controls. Run all three arms. Use the gate's matched-load ABBA instrument,
with cycles/op, instructions/op and IPC retained per cell. Rate at matched load
decides; instruction reductions alone do not establish a gain. Compare POST with
both PRE and PAD-A and investigate any null spread above the standing 2% bound.
Use the maintainer's calibrated split geometry; correctness's 6:2 ratio is not
silently substituted for a performance calibration.

Also compare BGSAVE completion timing on the same populated keyspace without
streams or function libraries, same shard/mode/engine geometry and save directory
storage. Retain per-key time and total time, separating the fixed per-file work.
No throughput or BGSAVE timing claim is made by this lane. The maintainer owns
these measurements and the merge.
