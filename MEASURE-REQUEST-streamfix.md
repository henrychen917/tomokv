# Redis 7.4 stream compatibility lane

## streamfix

Six assigned roots are implemented. Three are stopped for the owner decisions below.
This is a correctness candidate; no throughput result or merge-readiness claim is made.
Base: `83e0b809d0fdeb4bf43647bd0cada7a4f14f241d`; branch `cx-streamfix`; no push.
All lane commands use CPUs 96–111. Live correctness uses ports 20600–20699, 16 shards,
eight server CPUs 96–103, and split ratio 6:2; builds use `-j16`. Source/oracle are
`/home/user/Projects/redis/src` and `/home/user/Projects/redis74/src/redis-server`.

All nine exact harness5 reproductions differed from Redis 7.4.10 on PRE in
1s/2s × uring/epoll. POST matches all six active roots on all four legs; the three
stopped roots still differ. Raw typed replies and server argv:
[PRE](docs/streamfix/reproductions-pre.json), [POST](docs/streamfix/reproductions-post.json).
No reproduction was replaced by a weaker assertion.

| Active root | Resulting behavior |
| --- | --- |
| STREAM-TRIM-APPROX-LIMIT | `~` removes whole macro nodes, LIMIT counts live entries, omitted LIMIT caps at 100 × node-max-entries (bounded as Redis does), explicit 0 is unlimited. Byte and entry boundaries follow Redis even with tombstones and exact trims. Fully deleted nodes no longer consume later append capacity. |
| XREAD-PLUS-LAST | `+` reads the last live entry, including after XDEL, and correctly parks/wakes on missing or empty streams. Numeric maximal IDs remain literal. RESP2/3, mixed streams and COUNT are covered. |
| XRANGE-EXCLUSIVE-SENTINEL | `(-` and `(+` return Redis's invalid-stream-ID error in both range directions. |
| STREAM-GROUP-ID-DASH | XGROUP SETID and XAUTOCLAIM accept `-`/`+` sentinels with Redis cursor semantics. |
| XAUTOCLAIM-COUNT-RANGE | Signed canonical parsing and `INT64_MAX / sizeof(StreamID)` bound; Redis's distinct transient-allocation error occurs before consumer metadata changes. |
| MPOP-ARG-ERROR-TEXT | LMPOP, ZMPOP, BLMPOP and BZMPOP use Redis's count/numkeys errors for invalid and out-of-range values. |

Owner decisions required (stopped under the task's architecture/restriction rule):

- **OBJECT-IDLETIME-ZERO:** intentional zero-cost default. `FlatStore::configure_maxmemory`
  enables the idle clock only with maxmemory; both installation and accesses are inside
  maxmemory branches. Tracking idle time from creation without maxmemory requires newly
  executed metadata work on GET/SET/INCR/MGET/MSET, conflicting with this lane's zero-added-
  instructions requirement. Returning a fabricated age or enabling tracking only after
  OBJECT would not implement Redis semantics. No change to this root or its known failures.
- **RESTORE-IDLETIME-FREQ-IGNORED:** the supplied reproduction does not enable maxmemory,
  so faithful IDLETIME needs the tracking decision above. FREQ is also architectural:
  `KvObj::eviction_meta()` has five bits, `set_eviction_meta` masks to 31, and both owner
  and read-local LFU paths saturate at 31; Redis accepts 0–255 plus a decay clock. Merely
  storing FREQ 100 in that field yields 4. A cold reply-only override would misrepresent
  actual eviction/access behavior. The owner must choose full-width LFU metadata and its
  hot-path/layout budget. No partial fix or known-failure removal is claimed.

- **DUMP-STREAM-REFUSED:** stopped for an owner ruling on an explicit restriction.
  `tests/dumprestore.py:292–293` requires the refusal and calls it the “stream DUMP scope
  cut”; `MEASURE-REQUEST-perfio.md` also documents unsupported stream DUMP. The owner was
  asked whether to replace that restriction with a stream RDB codec. It remains unchanged
  pending that decision; its named Tcl failure remains on the list.


The implementation remains in the existing stream/group/blocking/MPOP files. A stream node
caches Redis listpack byte accounting while keeping native Compact records; no Redis
storage implementation is imported. The first implementation rescanned external nodes on
append and failed the Tcl mass-insertion window. The cache removes that unbounded append
work. The failed attempt and successful replacement are retained in the evidence.

All locked layouts remain PRE=POST in both namespaces: Op 336, Client 1984, ThreadCtx 1408,
Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624.
StreamNode is 112→120 bytes. Its two counters are owned inside StreamVal, so ownership
migration carries them with the value; no per-owner side table or new hot-path guard exists.
[Layout evidence](docs/streamfix/layouts.json).

The directed `streamfix` job has six literal rows, each running 24 legs:
databases 1/16 × atomic 0/1 × (1s read-local 0/1, 2s read-local 0) × epoll/uring.
Twenty-one named Tcl failures are now required passes:
[exact promotions](docs/streamfix/tcl-promotions.json). The three stopped roots keep their
known-failure entries. Blocking tests require an observed registered waiter before publishing;
no skipped window or widened tolerance counts as a pass.

Proof status and all failed/intermediate attempts are recorded in
[proof-summary.json](docs/streamfix/proof-summary.json), the full-job receipts under
[docs/streamfix/jobs](docs/streamfix/jobs), and compressed Tcl transcripts under
[docs/streamfix/proof-tcl](docs/streamfix/proof-tcl). `run_jobs.py` uses only gate.sh's
`GATE_ONLY_JOBS` interface; `full` selects the job inventory, while PARTIAL forbids the
full iteration/ABBA measurement flow. Final proof results are being collected. On the final candidate, both modes passed all
21 promoted Tcl assertions; the first 2s whole-job attempt failed the pre-existing
MONITOR blocked-command ordering assertion during concurrent verification. The whole
Tcl job is queued for an otherwise idle allocated-CPU rerun, without assertion changes.

PRE and PAD-A fail all six directed rows. The throwaway mutant restores one or more
wrong decisions for each active root, while retaining the final candidate layout and all
other code. Its source substitutions, exact candidate comparison and binary hash are in
[mutant-rebuild.json](docs/streamfix/mutant-rebuild.json). It is a correctness negative
control, never a measurement arm. The Tcl job must report a named promoted failure for
each active root in both modes; absence of a terminal test result is not accepted as proof.
That check passes: 20 of the 21 promoted names fail in each mode, covering all six roots.
The default-cap Tcl check remains green because this mutant retains the outer default-cap
stop while breaking node granularity and explicit LIMIT handling. PRE/PAD-A/mutant each
fail all 144 directed legs after geometry and oracle checks; final POST passes 144/144.

`make all`, every production-unit target, the concrete mdbqsbr live arms and the paired
blockfix witness pass, with 49 successful `make -q` checks and an unchanged candidate
hash: [build receipt](docs/streamfix/build/receipt.json). The first standalone
`python3 tests/gates_test.py` run had nine scheduler timeout failures during concurrent
verification. Its original log is retained; a quiet allocated-CPU rerun is queued after the other verification jobs finish.
The first feature-split-0 run also exposed the old netcmd expectation that an oversized
XAUTOCLAIM COUNT succeeds on an empty PEL. That test now requires the exact Redis
error and no consumer creation. Its whole owning job is queued for a fresh run; later
feature-mode jobs use the corrected test. No production code changed after freezing POST.

Command-scope proof uses linked production objects, preserving production link order and
placing the fixture object last. It opens no server or load generator. GET/SET/INCR/MGET/MSET
are traced in both modes, both namespaces, batches 1/32; single-key cases include slowlog
-1/10000, and MSET includes atomic 0/1. The 72 PRE/POST pairs count named production code
including inlines; external-library bodies and fixture callbacks are excluded, with their
call counts retained. Clock answers are deterministic in both arms. This is a bounded
command-scope instruction comparison, not a throughput or cycles/op measurement.
All **72/72 final pairs have exactly zero added instructions**, equal per-function counts,
and equal external/fixture-call counts. [Counts summary](docs/streamfix/instructions/counts-summary.json),
[full comparisons](docs/streamfix/instructions/comparison.json), and
[production linkage](docs/streamfix/instructions/linkage.json).

Instruction counts below are the normal namespace, one command per scope, atomic=1,
slowlog disabled. The linked JSON retains all batch/database/threshold variants.

| Command | 1s PRE | 1s POST | 2s PRE | 2s POST |
| --- | ---: | ---: | ---: | ---: |
| GET | 939 | 939 | 1559 | 1559 |
| SET | 1068 | 1068 | 1688 | 1688 |
| INCR | 1531 | 1531 | 2151 | 2151 |
| MGET | 10243 | 10243 | 10243 | 10243 |
| MSET | 17080 | 17080 | 16726 | 16726 |

DQ=+6, DF=+6. Row declarations are at tests/gate.sh lines 3801, 3804, 3807, 3810,
3813 and 3816; collection is line 5617, before the quick exit at line 5785.
Wave8's actual inventory was 806/823, so the required totals are **812/829**.
The standing EXPECT_QUICK=798 and EXPECT_FULL=815 remain unchanged and are already behind
wave8. The fixture matches all 829 source labels. Its total-constant check remains red until
the maintainer updates the constants; a partial job run cannot discharge that check.
[Source-line inventory](docs/streamfix/gate-inventory.json).

| Arm | Frozen executable | SHA-256 |
| --- | --- | --- |
| PRE, base 83e0b809d | `build/streamfix/pre/tomokv` | `41921f7270da1f141e0f6a85316cac965258dfad28fbeb3516d9d08607522647` |
| POST | `build/streamfix/post-final/tomokv` | `c671ede82505dda0c62da963e5230ba8aea8cd0edd08d1c5accf8948ed95ccf1` |
| PAD-A | `build/streamfix/PAD-A` | `31a7dd6d82480f2ec07e29d4a86a57a04639c34afc719f9830315df292e8a642` |

PAD is **kind A, behaviour twin**: PRE semantics with unused StreamNode fields matching
POST's 120-byte node, plus unreachable text padding. It matches POST's aggregate `.text`
origin (129328) and size (8,454,935 bytes), with 19,520 padding bytes. Individual function
offsets and data sections retain PRE layout; this is not an exact per-symbol layout twin
and cannot alone rule out all placement effects. Source, link inputs and digests:
[pad-a.json](docs/streamfix/pad-a.json), [pad-layout build](docs/streamfix/pad-layout-build.json).
No PAD runtime knob is added.

Maintainer measurement request — **NOT RUN in this lane**:

- Use the unchanged generic fourteen from `tests/wbland_merit_cells.txt`: h05, h06,
  p8g, p8s, d1g_l0, d1s_l0, m8g_l0, v1g_l0, d128g_l0, d32g_l1, d8s_l1, d32s_l1,
  x9_32_l1, x9_32_l0.
- Add split GET/SET p1/p32 null cells h53, h54, h21, h22. All eighteen exact existing
  cell lines are in [null-cells.txt](docs/streamfix/null-cells.txt).
- Add bounded stream append/trim, XREAD last-entry, XAUTOCLAIM, range/SETID and all four
  MPOP paths using the explicit shapes and entry witnesses in
  [feature-cells.json](docs/streamfix/feature-cells.json). Existing cell files have no
  stream/MPOP load adapter; the maintainer must freeze that adapter and offered loads before
  comparison. Changed PRE semantics are not an equal-work throughput baseline.

Run PRE/POST and PRE/PAD-A with the gate's own ABBA instrument on the quiet box, including
contemporaneous identical-arm controls and matched offered loads. Record per-cell rate,
cycles/op, instructions/op and IPC, and depth-1 latency. The deciding result is the
existing per-cell main-command null criterion; averaging across cells or instruction
identity alone cannot waive a regression. Preserve the PAD-A limitation with any result.

Full `tests/gate.sh iteration`, performance benchmarks, throughput/null measurements and
push are **NOT RUN**, reserved to the maintainer. No throughput claim is made.
