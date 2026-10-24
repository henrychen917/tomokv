## serverfix

Lane `cx-serverfix`, based on `ef5204b2e9650693228cc105b34625516898b82d`.
No push. Correctness processes and builds use CPUs 96–111 only; listener ports
are 31800–31899. Gate geometry is 16 shards, eight server CPUs (96–103), split
6 IO + 2 EX, or eight fused threads. Clients use 104–111. Directed reproductions
use `--databases 1`, explicit `--thread-mode 1s/2s`, and `--net-io uring/epoll`;
the standard differential matrix uses 16 databases and split or armed-fused
(`--read-local 1`). Every boot command is retained in its lifecycle receipt.
No throughput claim.

### Findings and implementation

| Register item | PRE finding at the above geometry, both engines | Change |
|---|---|---|
| CG4.3 | REPRODUCED: a long comment becomes a directive at a read-buffer boundary. | Assemble physical input before splitting lines, including Redis's 1024-byte C-string input behavior for literal NUL; preserve quoting, comment and no-continuation rules. |
| CG4.4 | REPRODUCED: empty/bare-unit memory values and file integer/boolean grammar differ. Live `maxclients 00020` and `protected-mode 1` are **NOT REPRODUCED** on this PRE: the earlier network adapter already rejects them in all four mode/engine legs. | Canonical integer parsing and Redis boolean/memory grammar at file and live boundaries; decoded NUL lengths follow the appropriate Redis type parser. |
| SV4.6 | REPRODUCED for generic boolean, integer, enum and duplicate/error-order cases. The specifically reported repeated `timeout`, numeric `protected-mode`, and `tcp-keepalive 01` cases are **NOT REPRODUCED** on this PRE; its network adapter already rejects them. `aof-timestamp-enabled 1` remains accepted on PRE. | Inventory-driven type table; parameter-list validation before value parsing; duplicate rejection and atomic failure; exact Redis diagnostics on the compatible surface. Preserve Tomo-only immutable-control errors. |
| SV4.7 | REPRODUCED: `HELLO 02` changes protocol successfully. | Canonical signed Redis integer parser, exact integer/NOPROTO replies, no name/protocol side effects on failure. |
| SV4.5 | REPRODUCED: AOF-disabled local=0/replicas>0 returns immediately. | Reuse the existing deferred WAIT lifecycle, including finite/infinite deadlines, CLIENT UNBLOCK TIMEOUT/ERROR and disconnect cleanup; MULTI remains nonblocking. |
| SV4.8 | REPRODUCED: PRE returns OK even after the production estimator is forced to return zero. | Deterministic six-bit register tests, sparse/dense agreement and conversion checks, ten-million-element six-sigma error checks, Redis success/failure replies. |
| SV4.14 | REPRODUCED: disabled slowlog constructs recorders and client identity storage. | Lazy recorder/directory pointers; existing client metadata supplies an immutable snapshot when logging is enabled after connect. Lifecycle locking protects cross-owner snapshots. |
| CC4.26 | REPRODUCED: 512 attributed log-store allocations before enable in the dual-runtime binary. | Lazy per-owner ACL log stores, safely published once and reclaimed after worker shutdown. |

Each item has a separate `tests/serverfix_*.py` directed battery and one gate
row. The scripts retain oracle replies, assertions, SHA-256s, exact process
arguments and teardown receipts. Every candidate battery declares both 1s/2s
and uring/epoll legs. HLL also patches a disposable copy of the oracle and each
candidate image: the broken estimator must produce the exact oracle error,
`ERR TESTFAILED Too big error. card:10 abserr:10`.

The CONFIG matrix exercises every registered name and alias, valid/current,
invalid, duplicate, invalid-head and invalid-tail updates. Existing documented
boot-only controls and representation limits remain explicit deviations; this
is not a claim that every Redis setting is implemented. In the frozen inventory,
90 distinct case replies across 15 existing boot-only controls still differ from Redis;
17 Tomo-only names have no oracle counterpart. Their PRE/POST/oracle replies
are [listed explicitly](docs/serverfix/proof/config-existing-deviations.json).
Local fsync waits
(`WAITAOF numlocal=1` with AOF enabled) remain explicitly unsupported. Lazy
recorders are retained after their first enable until worker shutdown, avoiding
unsafe reclamation while a concurrent recorder can hold a pointer. A cold off
boot creates none, and disabled requests allocate no log entries.

### Proof receipts

The complete directed runs on the frozen binaries returned **POST 50 ok / 0 FAIL**, and **PRE 41 ok /
9 expected FAIL**: all eight new rows plus the corrected DEBUG reply assertion
fail on PRE. Both debug job variants also ran in each arm. All four mode/engine
legs are present for every new row. The current batteries executed 8,396 candidate
assertions and 870 oracle assertions without failure on POST. [Receipts and counts](docs/serverfix/proof/directed-summary.json),
[POST archive](docs/serverfix/proof/post-directed.tar.gz),
[PRE archive](docs/serverfix/proof/pre-directed.tar.gz).

The scalar row additionally compares every live reply, including errors, with
the exact oracle reply. The slowlog and ACL-log rows also take RSS snapshots on
separate fresh processes with the allocation tracer absent. The CONFIG row also records every invalid notification flag against the oracle and compares compatible immutable/protected errors exactly.
The four updated directed rows and the corrected legacy notification row passed
on POST and failed on PRE and PAD-A through the gate; both notification atomic
legs are present in every arm. Assertion totals above use the current version
of each directed row. Supplemental totals are **POST 11 ok / 0 FAIL**, **PRE
6 ok / 5 expected FAIL**, and **PAD-A 6 ok / 5 expected FAIL**. PRE and PAD-A
each fail the same 1,004 assertions across the current eight directed rows.
[Supplemental gate receipts](docs/serverfix/proof/extra-runs.json).

`python3 tests/gates_test.py`: **70/70 passed again after the final supplemental
rows**, in 111.219 seconds. [Final harness receipt](docs/serverfix/proof/gates-test-final.json).
`make all`,
all **42** `job_production_units` targets, and `mdbqsbr-live-arms` built; all
44 freshness queries returned zero. [Build/freshness results](docs/serverfix/proof/final-build-results.json).
After history consolidation and cleanup, all 44 targets were still fresh, all
three binary hashes matched, and the lane's listener ports were clear.
[Final validation](docs/serverfix/proof/final-validation.json).

The linked audit lists **622** changed/added bodies with reasons and retained
normalized diffs. All **12** selected GET/SET and captured-MGET symbol groups are
identical. The expanded audit follows the actual MGET/MSET scatter entry points:
**73 execution bodies** are identical under the existing object relocation
normalizer. The strict linked audit still records a TLS-displacement change in
the db0 scatter executor; it is not hidden by the object result. The existing broader object audit compares 1,312 bodies: 1,261 are
identical, including all ten selected GET/SET bodies; its 51 dispatch/inlining
changes are listed with reasons, rather than hidden by treating the guard as a
performance verdict. No budget adjustment was needed for the required command
bodies. Both runtime namespaces retain every field offset and size of all 22
inspected types. [Linked audit](docs/serverfix/identity/summary.json),
[changed bodies](docs/serverfix/identity/changed-bodies.md),
[full local diff descriptor](docs/serverfix/identity/full-diff.json),
[broad object differences](docs/serverfix/hot-object-differences.md),
[layouts](docs/serverfix/layouts.json),
[actual command bodies](docs/serverfix/command-hot-identity.json).
TLS section sizes and alignments also match PRE: `.tdata` is 224 bytes and
`.tbss` is 480 bytes, each aligned to 16 bytes. The existing client catalog owns
its registration lifetime, so disabled logging adds no second TLS destructor
registration. [TLS footprint](docs/serverfix/tls-layout.json).

PAD-A passes its build/footprint check and reproduces the complete PRE assertion
verdict inventory in all eight new gate rows. Its `.text` starts at 0x1e7f0 and
has 8,137,591 bytes, matching POST, with 12,608 bytes of unreachable padding.
CET properties are preserved. [PAD description](docs/serverfix/pad-a.json),
[behavior comparison](docs/serverfix/proof/pad-pre-verdict-identity.json).
After archiving the PRE unit proof, temporary PRE trees and disposable gate
data were removed, reclaiming 14,057,165,478 bytes. The three frozen arms,
required POST unit products and normalized instruction diffs remain available.
[Cleanup inventory](docs/serverfix/proof/build-cleanup.json).

The broader run completed **66 jobs: 435 ok / 1 FAIL**. Its only failure was
the stale notification error assertion described below. After correction to
the recorded oracle reply, the whole notification job passed **6/6** on the
same frozen POST binary; PRE and PAD-A retain its expected failure.

The standard differential matrix passed **2,248 comparisons**: 568 split and
556 armed-fused comparisons per engine, covering both atomic settings, seeds
7, 19, 20, 23, 21 and 22, and all four repeated MULTI cases. The existing driver
skips SORT in armed-fused geometry; those skips are retained explicitly.
Mode equivalence also passed on both engines: **16 cells and 32 fresh boots
per engine** (replay plus mechanism witness), 64 boots total. The driver's
existing “32 combinations” label is not the cell count.
[Complete job and differential inventory](docs/serverfix/proof/post-existing-jobs.json).
All **48 climon legs passed**; **DIFF-TRK-1 was not observed**, so no conditional
PRE tracking-failure comparison was needed.
[Tracking inventory](docs/serverfix/proof/tracking-baseline.json).

The separate PRE source-unit gate returned **16 ok / 1 expected FAIL**. Only
`netcmd config regression` failed, on the corrected integer-NUL oracle reply.
Its receipt verifies all 225 archived production-source blobs against PRE and
records the unit executable's SHA-256.
[PRE unit proof](docs/serverfix/proof/pre-unit-proof.json).

The initial broader run `build/gate-run.6U7K1u` was intentionally stopped after
the last enum refinement; it is not a completed proof. Its config docs row
identified stale generated anchors, which were regenerated. The intermediate run `build/gate-run.69zhVq` then found a real regression:
uppercase CONFIG value errors used the input spelling instead of Redis's
lowercase name. All five selected seeds caught it. The implementation and
inventory battery were corrected before freezing the final binary; this
interrupted run is not counted as completed proof.
[Failure and exact oracle replies](docs/serverfix/proof/uppercase-regression.tar.gz),
[run receipt](docs/serverfix/proof/uppercase-regression.json). The initial
`gates_test.py` run had four scheduler deadline failures during concurrent
compilation; both logs are retained and the quiet retry passed all 70 tests.

Existing assertions changed only to oracle behavior: `tests/notify.py` now
requires the exact invalid-event-class CONFIG error (its old `Invalid argument`
substring caused the original broader run's single failed row);
[original failure and oracle witness](docs/serverfix/proof/notify-assertion-correction.json).
`tests/debug.py` now
expects the exact immutable `enable-debug-command` error;
`tests/netcmd_config_unit.cc` distinguishes integer rejection of an embedded NUL
from memory-value C-string acceptance. Both exact oracle witnesses are retained
in the CONFIG/scalar receipts. The unit PRE proof uses archived PRE production
sources, not a POST unit executable beside a PRE server.
[Reference-to-job coverage](docs/serverfix/proof/job-coverage.md).

### Row accounting

**DQ=+8, DF=+8.** All eight `collect_job serverfix_*` calls are at lines 4927–4934 of
`tests/gate.sh`, before the quick-tier exit at line 5009. `EXPECT_QUICK=739` and `EXPECT_FULL=756` are untouched. The maintainer
should set **747 / 764**. The reviewed fixture and source declare 764 labels,
with no missing or extra occurrences. The fixture's overall guard deliberately
refuses the unchanged EXPECT_FULL=756; no count was edited to hide that.

### Disabled-feature memory

Both timing knobs and ACL logging are off at boot. RSS comes from fresh
processes with no allocation tracer loaded; C++ allocation attribution uses a
separate matched process. These are snapshots for 24 named/denied connections,
not throughput measurements. Feature-byte totals sum live `operator new`
requests and exclude allocator size-class slack; RSS includes that slack, code
pages and network buffers. These are single-run RSS snapshots for each arm. The
allocation tracer excludes the independent ACL user-ID free list, whose static
initializer shares a symbol with ACL logging. Full stack attribution is retained
in the directed receipts.

| Probe / leg | PRE RSS boot / 24 clients (KiB) | POST RSS boot / 24 clients (KiB) | PRE feature heap at boot (bytes) | PRE marginal feature bytes/client | POST feature bytes at boot / per client |
|---|---:|---:|---:|---:|---:|
| slowlog / 1s-uring | 23828 / 24452 | 23604 / 24160 | 145512 | 177.00 | 0 / 0 |
| slowlog / 1s-epoll | 19500 / 20136 | 19636 / 20148 | 145512 | 177.00 | 0 / 0 |
| slowlog / 2s-uring | 23412 / 23904 | 23236 / 23704 | 145512 | 177.00 | 0 / 0 |
| slowlog / 2s-epoll | 19396 / 19900 | 18916 / 19424 | 145512 | 177.00 | 0 / 0 |
| acllog / 1s-uring | 23772 / 24568 | 23616 / 24312 | 120832 | 0.00 | 0 / 0 |
| acllog / 1s-epoll | 19744 / 20528 | 19340 / 20040 | 120832 | 0.00 | 0 / 0 |
| acllog / 2s-uring | 23240 / 23916 | 23188 / 23772 | 120832 | 0.00 | 0 / 0 |
| acllog / 2s-epoll | 19076 / 19692 | 18968 / 19560 | 120832 | 0.00 | 0 / 0 |

The marginal per-client count includes hash-table bucket growth. Both logging
features have zero attributed allocations before first enable in every POST leg.
The slowlog 1s/epoll RSS snapshot rose by 136 KiB at boot and 12 KiB with clients;
these single snapshots do not establish a stable RSS reduction.
[Machine-readable snapshots](docs/serverfix/disabled-memory.json).

### Maintainer merit request

Use exactly the generic 14 cells in `docs/lbplanner/generic-cells.txt`: `h05`,
`h06`, `p8g`, `p8s`, `d1g_l0`, `d1s_l0`, `m8g_l0`, `v1g_l0`, `d128g_l0`,
`d32g_l1`, `d8s_l1`, `d32s_l1`, `x9_32_l1`, `x9_32_l0`.

Frozen arms ([SHA256SUMS](docs/serverfix/SHA256SUMS)):

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/tomokv-serverfix-pre` | `a09ba396bfaa2f103173c374d641228af7a42a7eaa26fc9fa48204b95c11ebbd` |
| POST | `build/tomokv` | `c0b527316c39ec407c530105ca9d3ce76f65f60b3d284cd96dfa75ae128a6e57` |
| PAD-A | `build/tomokv-serverfix-pad-a` | `641a7d0205248f5f028dbbe121d10684240f2123f343545e483a637a68151c12` |

 **PAD kind A, behavior twin:** unmodified PRE
behavior with padding matching POST's `.text` start and total size. It is a
text-size control; individual function placement and data sections are not an
exact POST layout twin. `tools/serverfix_pad.py` records that limitation and
checks the sizes. It is not an inverse control.

On the maintainer's quiet box, run the gate's own paired PRE/POST and PRE/PAD-A
ABBA instrument, including a contemporaneous same-binary null. Keep offered
load, placement, connections, pipeline and allocator matched. Report rate at
matched offered load, cycles/op, instructions/op, IPC and the instrument's
depth-1 latency score. A gain requires POST to move while PAD-A remains within
the null band; ambiguous placement effects require further controls. Any
regression in a main-command cell rejects the candidate pending refinement.

Performance benchmarks, load generators, NIC merit measurements and the full
`tests/gate.sh iteration` are **NOT RUN**, as reserved for the maintainer.
