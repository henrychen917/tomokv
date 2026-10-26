## readability-a0

Baseline: origin/cpp 3700b51d7fb3074f32330dd81f138efbf1ddd980. Worktree and branch:
/home/user/Projects/cx-readability-a0, cx-readability-a0. No push. Builds use
GCC 13.3.0, GNU ld 2.42, the unchanged release flags, per-TU budgets and link order.

**The source-location removal works, but the design's narrow PRE/POST proof fails.**
POST-A0 -> FINAL is IDENTICAL after deleting all four #line directives and the
flatstore blank-line pads. All allocated section addresses and sizes match PRE.
However, final padding cannot restore individual constants' positions within
.rodata. Do not describe this candidate as changing only assertion failure blocks.
It needs the requested merit run with the layout control below.

### Implementation

- src/base/tomo_assert.h preserves glibc's conditional expression and four-argument,
  noreturn/nothrow __assert_fail call. All five runtime sites use stable FNV-1a ids;
  whitespace is ignored and the top bit is set. The NDEBUG branch retains glibc's
  original unevaluated-condition behavior (the sample design omitted this case).
- tools/assert_map.py runs from make all, writes build/tomokv.asserts.tsv, rejects
  duplicate/zero/low-bit-only pins, and compiles static_assert checks comparing
  Python and C++ hashes. Salts/pins are uint32 integer literals. --pin FILE:LINE
  prints the old id for an identifier rename inside a condition. The map uses
  physical locations, qualified enclosing function names, condition text and
  salt/pin. Source-directory dependencies cover file additions/removals too.
- The lexer handles comments, escaped newlines, raw/ordinary literals, digit
  separators and preprocessor digraphs. Assertion wrapper macros are rejected:
  sites must remain visible to the map generator. Both database namespaces and
  NDEBUG behavior are tested.
- The source_identity gate row scans src/ outside trace-only branches, then
  preprocesses all 55 production TUs in both database variants. Compiler built-in
  sentinels catch alias/token-pasting expansions at in-tree call sites. In
  addition to the requested list it rejects #line, __COUNTER__, GCC's alternate
  file macros and source-location builtin, and non-assembly stringification
  except the two compile-time assertion hashing macros. It conservatively checks
  other conditional branches; comments and literal text are not violations.
- Copied witness builds carry the new map tool. AOF/notification schedule command
  extractors request the binary target, since their minimal copies only need
  compile/link commands. EXPECT_QUICK and EXPECT_FULL are unchanged.

### Binary proof and design defect

| Check | Observed result |
|---|---|
| PRE .text vs FINAL .text size | 8,279,287 bytes in both |
| PRE .rodata / unpadded POST .rodata | 164,737 / 163,585 bytes |
| Measured shrink and used padding array | 1,152 bytes, last-linked version.cc variant, alignment 1 |
| Allocated section addresses, sizes and alignment | Identical |
| Instruction addresses and lengths | Identical |
| __assert_fail calls | 41, same call instructions/addresses |
| Changed assertion arguments | 41 immediates + 105 RIP-relative operands = 146 instructions |
| Other changed instructions | 15,721 |
| binary-neutral PRE -> FINAL | DIFFERENT: .text, .rodata, .rela.dyn, .data.rel.ro, .data |
| binary-neutral POST-A0 -> FINAL | IDENTICAL, 9,474,960 bytes after stripping |

The 18 original diagnostic strings occupy 1,089 bytes, but section shrink is
1,152 bytes because of merging/alignment. Removing the original assertion
literals changes the linked placement of mergeable constant pools: other strings,
numeric constants and their references move *inside* .rodata. Restoring its total size
therefore fixes later section addresses, without fixing those internal offsets.
18 function-string operands happen to keep their old address (their bytes now
hold the shared message), explaining 105 changed RIP operands rather than 123.
The audit preserves raw instruction differences and exits nonzero for the failed
narrow proof; it does not normalize them into a pass.

readelf's non-allocated DWARF/symbol sections necessarily differ after source
changes. The identical address/size claim is for allocated sections. The supplied
binary-neutral.sh removes debug/symbol data and the build-id before comparison.
Full raw readelf/objdump outputs are in build/readability-a0; compact receipts are
in docs/readability-a0. This is a defect in section 4.3's proposed proof, not a
throughput result. No extra linker script or frozen-baseline postprocessor was
introduced to force the proof to pass.

### Artifacts

All binaries are unstripped and remain under build/readability-a0 for the owner.
POST and POST.asserts.tsv are aliases of FINAL and FINAL.asserts.tsv.
Archive FINAL.asserts.tsv with FINAL; POST-A0.asserts.tsv matches the intermediate
source lines. PRE uses glibc's original diagnostics. The final map is also tracked
in docs/readability-a0/tomokv.asserts.tsv as evidence for this revision.

| Arm | SHA-256 |
|---|---|
| PRE | 423784a9a01995d004f2c0a9a6977822514589531fe4d4e1f582356adc857337 |
| POST-A0 | a5c35ca45a20bcbe6c66c57f21212af1d34f36ff27f5c68d228633a988554c14 |
| POST = FINAL | 423ba683d71492ab638d325ae6ea95069678716beb799fec826f7f7b1dcd8144 |
| PAD-A | a9b260abd30dc04d11c1645d64b830d68890c66baba3a57374127557be382b83 |

**PAD kind A: behaviour twin.** PRE assertion diagnostics at POST's layout.
tools/assert_artifacts.py pad places the 18 original strings (1,089 bytes) in
POST's 1,152-byte unused array, restores the 41 original line immediates and points
the same 123 LEAs at those strings. It verifies each restored string/line against
PRE, all section/symbol metadata against POST, and that no other file bytes change.
The normal execution path and POST constant layout are untouched. This control is
useful despite unchanged section boundaries, because constants moved within the
section. No kind-B control is needed: .text size did not change.

Reproduce the offline audits (no server):

    taskset -c 48-63 /home/user/Projects/calib/binary-neutral.sh build/readability-a0/PRE build/readability-a0/FINAL
    taskset -c 48-63 python3 tools/assert_artifacts.py audit build/readability-a0/PRE build/readability-a0/FINAL
    taskset -c 48-63 /home/user/Projects/calib/binary-neutral.sh build/readability-a0/POST-A0 build/readability-a0/FINAL
    taskset -c 48-63 python3 tools/assert_artifacts.py pad build/readability-a0/PRE build/readability-a0/FINAL --output build/readability-a0/PAD-A

The first two commands are expected to exit 1 with the failed narrow-diff proof.

### Correctness evidence

PASS: 69 rows, zero failures, through the gate's whole-job interface with all
legs retained. Final run: build/gate-run.3Ydk6c; ledger and job counts are tracked
under docs/readability-a0. Selection (plus automatic prerequisites):

    GATE_TEST_PORT=41899 GATE_NOTIFY_ORACLE_CORES=48-55 GATE_DIFFER_ORACLE_CORES=48-55 \
    GATE_ONLY_JOBS='source_identity storage_units atomic_units core_units ring_unit config_unit dbdefault boot_grammar aoforder racefix_climon tracking_redirect' \
    taskset -c 48-63 tests/gate.sh quick --server-cores 48-55 --load-cores 56-63 --load-smt '' --ports 41800-41898

This uses the gate's 8-thread, 16-shard, 6:2 correctness geometry. The counts are
release 1, config 2, rings 3, storage 13, source identity 1, core 9, Climon 1,
atomic/storesize 27, boot grammar 7, both-mode default boot 1, tracking REDIRECT 1,
and AOF order 3. Core units retain both ASAN/UBSAN and TSAN legs; storesize retains
both database namespaces and its negative control. This is a PARTIAL correctness
ledger, not a full gate or a release receipt.

- The new row rejects PRE through the same job interface (one expected failed
  lint row; the external-PRE prerequisite row passes), and passes FINAL. See
  pre-row-final.log and the final source_identity row in the receipts.
- GATE_TEST_PORT=41899 taskset -c 48-63 python3 tests/gates_test.py: 72/72 passed.
  An earlier run during compilation had two 45-second scheduler-fixture timeouts;
  the subsequent run passed with lane builds stopped. Both raw logs remain in
  build/readability-a0. No timeouts or expectations were relaxed.
- make all and every job_production_units target built. All **42 named production
  targets** pass make -q; the full **48-query freshness audit** also covers all,
  the directed-assert binary, the recursive mdbqsbr-live-arms target, both variant
  all targets, and the blockfix-cost executable/binary-binding receipt. Every
  query returned 0. See freshness.json; reproduce with taskset -c 48-63 python3
  docs/readability-a0/check_freshness.py.
- The first selected run passed 57 public rows but exposed two failed build-only
  witness targets (minimal copies omitted the map tool). Those were fixed; the
  final run built all targets and also passed the affected AOF, Climon and tracking
  jobs. A green public row tally was not used as a substitute for freshness.
- The final build/tomokv SHA-256 still equals the preserved FINAL arm above.

The new row is collected at tests/gate.sh:5362, before the quick exit at :5631:
DQ +1 / DF +1. Maintainer changes EXPECT_QUICK 798 -> 799 and EXPECT_FULL 815 -> 816.
No constants or historical receipt-label fixtures were edited.

The directed binary constructs a real Shard and calls init with invalid bucket
bounds. It must die from SIGABRT, emit glibc's id message, and resolve to the unique
map entry src/core/shard.h:67 / tomo::Shard::init. It passed with id 2184563561
(0x8235cb69). Normal exit, wrong signal/message, a missing/duplicate id or wrong
physical location fails the check. Separate controls reject duplicate sites,
invalid pins, invisible wrapper macros and macro-pasted forbidden identifiers.

### Disposable readability demonstration

PASS: clang-format 18.1.8 reformatted the entire 3,902-line flatstore.h (4,034
lines afterward), with include sorting, string splitting and brace insertion
disabled and qualifier alignment left alone. The private static make_word
helper moved before round_pow2 in the same class/TUs and was renamed to
pack_slot_word at every use, including flatstore_atomic.inc. Rebuilding from that
copy produced IDENTICAL (9,474,960 bytes after stripping) against FINAL; all five
assertion ids stayed equal. The map reflected the renamed enclosing function.

The modified source copy was deleted. No formatter configuration, source
reformatting, function move or rename from this demonstration is committed.
The binary/sidecar remain as build/readability-a0/SCRATCH-DEMO and
SCRATCH-DEMO.asserts.tsv; the raw source diff is uncommitted under build/.
SCRATCH-DEMO SHA-256: 4a63aeaec5c8af39ad633fce6c590fe4477d970c21bbd27728806ca3cc49f2a1.

Identity of these selected edits does not imply arbitrary definition moves or
renames preserve compiler output. Later readability lanes must run the supplied
binary-neutral.sh on every rebuilt executable. A rename *inside* an assertion
condition needs TOMO_ASSERT_ID with the prior id; a rename of its enclosing helper
has no assertion-id effect.

### Maintainer merit request — expected result: null

Run the gate's ABBA instrument on the quiet box for these eight quick-check cells,
using its existing geometry, matched offered load, measured floors and null
controls. Compare PRE/POST and PAD-A/POST in the same session; retain every cell.

| Mode | Command | Depth | Existing all-off headline cell |
|---|---|---:|---|
| 2s | GET | 1 | h49 |
| 2s | SET | 1 | h50 |
| 2s | GET | 32 | h17 |
| 2s | SET | 32 | h18 |
| 1s | GET | 1 | h33 |
| 1s | SET | 1 | h34 |
| 1s | GET | 32 | h01 |
| 1s | SET | 32 | h02 |

Use the gate's own cell definitions (rl=0, ro=0, atomic=1, 512 connections for
these ids), not a newly chosen workload. The matched-load rate/latency verdict
per cell decides; report cycles/op, instructions/op and IPC alongside it. The
expected null is a hypothesis. A PRE/POST movement shared by PAD-A implicates the
constant layout; a POST/PAD-A movement must be investigated despite their identical
normal-path bytes. No averaging across cells and no throughput claim in this lane.

Performance benchmarks and full tests/gate.sh iteration: **NOT RUN**, reserved to
the maintainer. The selected correctness jobs use CPUs 48-63 and ports 41800-41899;
all lane builds use taskset -c 48-63 and make -j16.

### Additional limits

The lottery copier already fails on a missing multi.inc read_kind text anchor on
PRE and POST; both errors are retained in build/readability-a0/*lottery-copy.log.
Its map-tool staging was updated, but a full lottery witness build is **NOT RUN**
because generation stops at that pre-existing anchor; it has no landing gate row.
The standalone publishfix_schedule.py builder is **NOT RUN** because it hard-codes
CPUs 96-111, outside this lane's allocation. Its copy now includes the map tool;
the gate's own publishfix production unit remains part of the requested checks.
