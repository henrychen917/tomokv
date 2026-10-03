**Lane flushfix — ST1 and ST10, round 3 wave A**

Worktree/branch: `/home/user/Projects/cx-flushfix`, `cx-flushfix`.
Launch HEAD: `e279aeb4cf08ae2c39f26be679388b872fed4667`.
Implementation commits: `53a4bfca4`, `2686f68f6`, `0809532f0`, `f8d371439`.
The required first `git fetch origin cpp && git merge --no-edit origin/cpp` completed:
already up to date. No push, listener, server, load generator, benchmark, or gate was run.
Builds used `taskset -c 112-127 make -j16`; the C++/Python proof programs were
serverless and pinned to 112–127. Live validation and performance remain mainline work.

**Diagnosis and implementation**

ST1 is confirmed at launch `src/cmd/t_server.cc:2688` and
`src/cmd/multidb.cc:637`: every FLUSHDB selected a vector of copied strings which
retained the entire namespace until the scan finished. `key_namespace()` at
`src/store/kvobj.h:165` is constexpr zero in the db0 image, so this includes the
default `--databases 1` boot. An allocation exception escaped the handler.

The db0 handler now reaches the existing FLUSHALL `clear()` /
`clear_during_snapshot()` arms. It keeps the old allocation-free expiry scan
before clearing: removing that walk would lose expired notifications, the
expired counter, and the scan's AOF expiry deletes. The dirty predicate is still
captured before any deletion. The directed expiry witness rejects a clear-only
implementation.

Multi-DB `multidb_flush` now materialises at most 256 borrowed `Slice` identities
in a 4,096-byte stack array, then immediately erases that batch. It keeps the
starting cursor when a scan emits more than the array can hold. SCAN COUNT bounds
homes, not emitted keys; the overflow branch is necessary even with COUNT 256.
The reverse-binary home cursor tolerates the intervening shrink/rehash.

The borrowed bytes remain valid: one owner executes this entire handler without
yielding; each physical key is present once; rehash moves slots, not records; and
an erase only releases that key's record. The buffer is drained before another
scan. Snapshot erases retain the frozen geometry, and armed erases use the
existing retirement path. No owner, retry, lock, or layout rule changes.

The referenced twin at `src/cmd/atomics_glue.inc:553` is guarded but **not chunked
in the launch tree**. Its full `flush_keys` vector is retained for resumable
snapshot preparation. This fix uses a fixed borrowed buffer instead of copying
that vector/catch pattern: there is no materialisation allocation to fail or to
recover after an earlier batch was erased. The snapshot gate remains guarded
and unchanged. The 4 KiB bound is for ordinary key materialisation, not for
snapshot preimages, existing atomic tombstones, or opportunistic table shrinking.

Completion notifications, WATCH handling, command identity, and the AOF dispatch
remain unchanged. `src/cmd/scatter_engine.inc:2183` still emits the existing one
FLUSHDB record per shard stream, with `op.physical_db`, independently of the
number of batches; the new loop emits no per-key flush records. Existing lazy
expiry effects are retained. Save dirty accounting and published size remain at
the end of `cmd_flush`; the test checks one dirty increment for a nonempty shard
and none for an empty shard.

ST10 uses the explicitly allowed header-equivalence option at **all six sites**.
`src/store/kvobj.h` is unchanged, preserving db0 instruction bytes. The shared
builder at line 734 is the test oracle; the test compares all eight header bytes
before decoding, then checks the extended length, key identity, and TTL slot.

| Site in `src/store/kvobj.h` | Disposition | Test/control selector |
| --- | --- | --- |
| `kvobj_init_raw_string`, line 790 | Kept; header-equivalence test | `raw` |
| `kvobj_init_int`, line 812 | Kept; header-equivalence test | `int` |
| `kvobj_new_string` external arm, line 851 | Kept; header-equivalence test | `string` |
| `kvobj_new_typeval`, line 877 | Kept; header-equivalence test | `typeval` |
| `kvobj_new_embedded_typeval`, line 901 | Kept; header-equivalence test | `embedded` |
| `kvobj_reheader` compact arm, line 1065 | Kept; header-equivalence test | `reheader` |

The matrix is namespaces `{0,1,15,255}` × lengths `{0,1,254,255,256,307}` ×
absent/reserved/live TTL slots, with both external ownership flags and all four
compact collection types. The db0 build runs the namespace-zero subset.
Each control changes just one builder's three identity predicates to length-only
predicates in an overlay under `build/`; production sources are never corrupted.
There are still six open-coded builders: this is a consistency guard, not a
claim that every builder now calls a single implementation.

**Executed proofs**

The ST1 test links both production images and calls the registered command
handlers directly. Each memory case first inserts 65,536 binary keys of 2,048
bytes, then sets `RLIMIT_AS` to its current mapped size plus exactly 2 MiB. The
multi-DB case also keeps a db0 sentinel. This is a real address-space cap, not
`maxmemory` accounting, and no scan list is prepared before the cap.

The PRE unit substitutes the actual launch versions of `t_server.o` and
`multidb.o` in both images. `emit-pre` recreates these sources from launch HEAD
inside this worktree, and Makefile targets compile them. The test terminate
handler writes the named failure and exits 1 rather than leaving a core dump;
the production failure would abort. Catching an error elsewhere is not accepted.

| Directed check | PRE | POST |
| --- | --- | --- |
| db0 FLUSHDB, 2 MiB extra virtual headroom | Uncaught allocation failure, exit 1 | Completes; size and publication zero |
| multi-DB FLUSHDB, same headroom rule | Uncaught allocation failure, exit 1 | Completes; other DB retained |
| db0 FLUSHALL, same headroom rule | Completes | Completes |
| Header equivalence | Six original predicates agree | 1,656 multi + 414 db0 comparisons pass |
| Six individually broken header builders | N/A | All six fail at the named assertion |

The semantics fixture covers both database images × armed/disarmed read-local ×
active/inactive capture (eight cases). It puts 400 keys in one 1,024-slot home,
asserts that geometry was reached, and checks that no overflow keys survive.
It asserts that a shrink actually started in the multi-DB non-capture cases,
and that active capture retains its table capacity after FLUSHDB. It prepares
and counts all 400 preimages before flushing, then requires capture completion.

Final serverless output (expected negative failures are followed by PASS receipts):

```text
PASS flushfix expiry: db0
PASS flushfix semantics: db0 armed=0 snapshot=0
PASS flushfix semantics: db0 armed=0 snapshot=1
PASS flushfix semantics: db0 armed=1 snapshot=0
PASS flushfix semantics: db0 armed=1 snapshot=1
PASS flushfix expiry: multi
PASS flushfix semantics: multi armed=0 snapshot=0
PASS flushfix semantics: multi armed=0 snapshot=1
PASS flushfix semantics: multi armed=1 snapshot=0
PASS flushfix semantics: multi armed=1 snapshot=1
PASS receipt flushfix-unit semantics exit=0
PASS flushfix memory: db0 FLUSHDB keys=65536 key-bytes=2048 headroom=2097152 cap=206000128 peak-rss-kib=174120->174120
PASS receipt flushfix-unit memory-db0 exit=0
PASS flushfix memory: multi FLUSHDB keys=65536 key-bytes=2048 headroom=2097152 cap=206000128 peak-rss-kib=175636->175636
PASS receipt flushfix-unit memory-multi exit=0
PASS flushfix memory: db0 FLUSHALL keys=65536 key-bytes=2048 headroom=2097152 cap=212291584 peak-rss-kib=175636->175636
PASS receipt flushfix-unit memory-all exit=0
FAIL flushfix: FLUSHDB completes under RLIMIT_AS (uncaught allocation failure)
PASS receipt flushfix-pre-unit memory-db0 exit=1
FAIL flushfix: FLUSHDB completes under RLIMIT_AS (uncaught allocation failure)
PASS receipt flushfix-pre-unit memory-multi exit=1
PASS flushfix memory: db0 FLUSHALL keys=65536 key-bytes=2048 headroom=2097152 cap=205991936 peak-rss-kib=175640->175640
PASS receipt flushfix-pre-unit memory-all exit=0
PASS flushfix flush: 7/7 strict outcomes
PASS header all: 1656 comparisons (multi)
PASS receipt kvobj-header-unit all exit=0
PASS header all: 414 comparisons (db0)
PASS receipt kvobj-header-db0-unit all exit=0
FAIL header raw: 8-byte header equals kvobj_init_header
PASS receipt unit raw exit=1
FAIL header int: 8-byte header equals kvobj_init_header
PASS receipt unit int exit=1
FAIL header string: 8-byte header equals kvobj_init_header
PASS receipt unit string exit=1
FAIL header typeval: 8-byte header equals kvobj_init_header
PASS receipt unit typeval exit=1
FAIL header embedded: 8-byte header equals kvobj_init_header
PASS receipt unit embedded exit=1
FAIL header reheader: 8-byte header equals kvobj_init_header
PASS receipt unit reheader exit=1
PASS flushfix headers: 8/8 strict outcomes
```

The additional clear-only control substitutes the db0 command object from
`0809532f0`, rebuilt with the final expiry fixture. It failed at exactly:

```text
FAIL flushfix: FLUSHDB retains lazy-expiry notification and counter
```

Its process exited 1; the check required both that exit and that assertion.
The actual launch PRE unit and final POST both pass the expiry fixture.
The throwaway binary and its local build recipe are
`build/flushfix-clear-only-unit` and `build/flushfix/expiry-control.mk`.
FLUSHDB and FLUSHALL each added **zero KiB to their process peak RSS** in
these directed POST runs; absolute RSS differs across independently seeded
processes and is not a performance comparison.


Proof receipts, including binary SHA-256s, exact required failures, stdout, and
exit statuses: `build/flushfix-flush-proofs.json` and
`build/flushfix-headers-proofs.json`. Detailed logs are in `build/flushfix/`.
`bash -n tests/gate.sh`, Python syntax compilation, and `git diff --check` pass.

Both images compile the exact locks in `tests/flushfix_unit.cc`: Op 336,
Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192,
AtomicEntry 144, Config 624. No production header or layout changed.
`io_loop.h`, `wb.h`, and `reorder.cc` are untouched, so the conditional
`wbland_checks.py check clauses` requirement does not apply.

**Gate rows**

Added `flushfix flush witnesses` and `flushfix headers witnesses` in
`tests/gate.sh:1347`. `job_atomic_units` is collected at line 2763, before the
quick-tier exit at line 2887. Therefore quick and full each gain exactly two
rows: **EXPECT_QUICK should be 448; EXPECT_FULL should be 465**, plus the
existing dynamic NIC rows. The constants at lines 261–262 remain **446 / 463**
for the maintainer to update. Builds join the existing production-unit job;
build failure makes both new rows red. No row is skipped on failure to arm.

**Artifacts and requested mainline work**

Release binaries are built and retained locally:

```text
f394b8c02c679066f018692184bfe41a743cff22152fdf242fec524e41696d21  build/flushfix/tomokv-pre
3d69d1b78f4159bcda116dbe918c107e3b44d482f2129df778105b3eda71633f  build/flushfix/tomokv-post
```

| Static artifact | PRE | POST |
| --- | ---: | ---: |
| ELF `.text` bytes | 7,554,449 | 7,563,601 |
| GNU size data bytes | 89,560 | 89,560 |
| GNU size bss bytes | 1,146,424 | 1,146,424 |


78/82 complete production objects are byte-identical to PRE, including both
`t_string.o` images. The four changed objects are `t_server.o` and `multidb.o`
in both images; the comparison is in `build/flushfix/object-identity.log`.
No PAD arm: no layout change or performance benefit is claimed. Static text
size and byte identity do not establish a rate result.

Reproduce the serverless checks on the reserved cores:

```sh
cd /home/user/Projects/cx-flushfix
taskset -c 112-127 make -j16 all build/flushfix-units build/flushfix-pre-unit
taskset -c 112-127 python3 tests/flushfix_checks.py check headers
taskset -c 112-127 python3 tests/flushfix_checks.py check flush --pre build/flushfix-pre-unit
```

Mainline only, on the quiet scheduled box: run all four live cells in sequence.
The helper uses 16 shards and the gate's recorded 8-thread correctness ratio
(6 io + 2 ex for split), pins server and client separately, and verifies the
server PID before writing. It creates and deletes only its own temporary
directory. PRE must reach the fully populated/capped window and then abort
with `std::bad_alloc`; a boot failure, unrelated abort, or surviving PRE fails
the negative control. POST must return OK, remain responsive, report DBSIZE 0,
and preserve the other database's sentinel. These live cases were **not run**.

```sh
cd /home/user/Projects/cx-flushfix
for mode in 1s 2s; do
  for databases in 1 16; do
    python3 tests/flushfix_checks.py live \
      --binary build/flushfix/tomokv-pre --expect-terminate \
      --server-cores 0-7 --load-cores 8-15 --port 17953 \
      --mode "$mode" --databases "$databases" --keys 262144 --key-bytes 4096 || exit 1
    python3 tests/flushfix_checks.py live \
      --binary build/flushfix/tomokv-post \
      --server-cores 0-7 --load-cores 8-15 --port 17953 \
      --mode "$mode" --databases "$databases" --keys 262144 --key-bytes 4096 || exit 1
  done
done
```

After the maintainer updates the row counts, run the normal correctness and
ABBA instrument, including existing notification, WATCH, multi-DB/AOF, and
snapshot coverage:

```sh
cd /home/user/Projects/cx-flushfix
tests/gate.sh iteration --reference-binary "$PWD/build/flushfix/tomokv-pre"
```

The requested PRE/POST performance cells are the current 18-cell iteration
smoke set in `tests/headline_cells.txt`: `h01,h07,h11,h15,h17,h23,h27,h31,h48`,
`m47,m92`, and `t00,t01,t02,t03,t04,t05,t06`. Use the gate's matched offered
loads and its verdict; collect rate/latency and per-cell cycles/op, IPC, and
instructions/op. This lane reports no performance result or unconditional
zero-regression claim before that run. Record the result in
`MEASURE-RESULT-flushfix.md`.

**Diff from launch HEAD**

`git diff e279aeb4cf08ae2c39f26be679388b872fed4667 --stat`:

```text
 MEASURE-REQUEST-flushfix.md | 275 ++++++++++++++++++++++++++++++++++++++++++++
 Makefile                    |  28 +++++
 src/cmd/multidb.cc          |  34 ++++--
 src/cmd/t_server.cc         |  14 ++-
 tests/flushfix_checks.py    | 198 +++++++++++++++++++++++++++++++
 tests/flushfix_unit.cc      | 211 +++++++++++++++++++++++++++++++++
 tests/gate.sh               |  14 ++-
 tests/kvobj_header_unit.cc  | 113 ++++++++++++++++++
 8 files changed, 875 insertions(+), 12 deletions(-)
```
