# execfifo3 verification record

All **42/42 selected-job groups passed** on the frozen POST image, with
**1,375 passing public row executions and zero failures**. All 42 selected-job
attempts passed. Repeated mode/engine/release rows are included in that count;
this is not a full iteration receipt.

[Runs](validation/runs.json) bind commands, environments, allocations and the
production digest. [Evidence](validation/evidence.json) links job plans,
ledgers, raw results and file digests. The [coverage check](validation/coverage.json)
requires all 42 groups on the final POST SHA, checks exact FIFO/C1/fairness,
AT4.12 and differential inventories, and audits recorded boot allocation.

| Group | Passing public rows | Evidence |
| --- | ---: | --- |
| `aof-extra-epoll-0` | 60 | [ledger](validation/34-aof-extra-epoll-0/ledger.partial), [output](validation/34-aof-extra-epoll-0/output.log) |
| `aof-extra-epoll-1` | 60 | [ledger](validation/38-aof-extra-epoll-1/ledger.partial), [output](validation/38-aof-extra-epoll-1/output.log) |
| `aof-extra-uring-0` | 60 | [ledger](validation/20-aof-extra-uring-0/ledger.partial), [output](validation/20-aof-extra-uring-0/output.log) |
| `aof-extra-uring-1` | 60 | [ledger](validation/24-aof-extra-uring-1/ledger.partial), [output](validation/24-aof-extra-uring-1/output.log) |
| `asan-epoll-0` | 6 | [ledger](validation/35-asan-epoll-0/ledger.partial), [output](validation/35-asan-epoll-0/output.log) |
| `asan-epoll-1` | 6 | [ledger](validation/39-asan-epoll-1/ledger.partial), [output](validation/39-asan-epoll-1/output.log) |
| `asan-uring-0` | 6 | [ledger](validation/21-asan-uring-0/ledger.partial), [output](validation/21-asan-uring-0/output.log) |
| `asan-uring-1` | 6 | [ledger](validation/25-asan-uring-1/ledger.partial), [output](validation/25-asan-uring-1/output.log) |
| `at412` | 18 | [ledger](validation/03-at412/ledger.partial), [output](validation/03-at412/output.log) |
| `atomic-controls-epoll` | 3 | [ledger](validation/29-atomic-controls-epoll/ledger.partial), [output](validation/29-atomic-controls-epoll/output.log) |
| `atomic-controls-uring` | 3 | [ledger](validation/15-atomic-controls-uring/ledger.partial), [output](validation/15-atomic-controls-uring/output.log) |
| `batteries-epoll-0` | 47 | [ledger](validation/36-batteries-epoll-0/ledger.partial), [output](validation/36-batteries-epoll-0/output.log) |
| `batteries-epoll-1` | 47 | [ledger](validation/40-batteries-epoll-1/ledger.partial), [output](validation/40-batteries-epoll-1/output.log) |
| `batteries-uring-0` | 47 | [ledger](validation/22-batteries-uring-0/ledger.partial), [output](validation/22-batteries-uring-0/output.log) |
| `batteries-uring-1` | 47 | [ledger](validation/26-batteries-uring-1/ledger.partial), [output](validation/26-batteries-uring-1/output.log) |
| `boundary-extra` | 21 | [ledger](validation/12-boundary-extra/ledger.partial), [output](validation/12-boundary-extra/output.log) |
| `broad-epoll` | 209 | [ledger](validation/32-broad-epoll/ledger.partial), [output](validation/32-broad-epoll/output.log) |
| `broad-uring` | 209 | [ledger](validation/18-broad-uring/ledger.partial), [output](validation/18-broad-uring/output.log) |
| `core` | 45 | [ledger](validation/05-core/ledger.partial), [output](validation/05-core/output.log) |
| `differ-epoll` | 6 | [ledger](validation/33-differ-epoll/ledger.partial), [output](validation/33-differ-epoll/output.log) |
| `differ-uring` | 6 | [ledger](validation/19-differ-uring/ledger.partial), [output](validation/19-differ-uring/output.log) |
| `directed` | 43 | [ledger](validation/01-directed/ledger.partial), [output](validation/01-directed/output.log) |
| `fairness` | 3 | [ledger](validation/02-fairness/ledger.partial), [output](validation/02-fairness/output.log) |
| `features` | 36 | [ledger](validation/13-features/ledger.partial), [output](validation/13-features/output.log) |
| `fifo-contract` | 11 | [ledger](validation/00-fifo-contract/ledger.partial), [output](validation/00-fifo-contract/output.log) |
| `flip` | 16 | [ledger](validation/08-flip/ledger.partial), [output](validation/08-flip/output.log) |
| `headline` | 84 | [ledger](validation/06-headline/ledger.partial), [output](validation/06-headline/output.log) |
| `notify-fused-epoll` | 7 | [ledger](validation/31-notify-fused-epoll/ledger.partial), [output](validation/31-notify-fused-epoll/output.log) |
| `notify-fused-uring` | 7 | [ledger](validation/17-notify-fused-uring/ledger.partial), [output](validation/17-notify-fused-uring/output.log) |
| `ownership-extra-epoll` | 33 | [ledger](validation/28-ownership-extra-epoll/ledger.partial), [output](validation/28-ownership-extra-epoll/output.log) |
| `ownership-extra-uring` | 33 | [ledger](validation/14-ownership-extra-uring/ledger.partial), [output](validation/14-ownership-extra-uring/output.log) |
| `readlocal` | 5 | [ledger](validation/07-readlocal/ledger.partial), [output](validation/07-readlocal/output.log) |
| `readlocal-extra-epoll` | 15 | [ledger](validation/30-readlocal-extra-epoll/ledger.partial), [output](validation/30-readlocal-extra-epoll/output.log) |
| `readlocal-extra-uring` | 15 | [ledger](validation/16-readlocal-extra-uring/ledger.partial), [output](validation/16-readlocal-extra-uring/output.log) |
| `script-blocking-extra` | 15 | [ledger](validation/11-script-blocking-extra/ledger.partial), [output](validation/11-script-blocking-extra/output.log) |
| `scriptbounds-epoll-0-a0` | 3 | [ledger](validation/37-scriptbounds-epoll-0-a0/ledger.partial), [output](validation/37-scriptbounds-epoll-0-a0/output.log) |
| `scriptbounds-epoll-1-a0` | 3 | [ledger](validation/41-scriptbounds-epoll-1-a0/ledger.partial), [output](validation/41-scriptbounds-epoll-1-a0/output.log) |
| `scriptbounds-uring-0-a0` | 3 | [ledger](validation/23-scriptbounds-uring-0-a0/ledger.partial), [output](validation/23-scriptbounds-uring-0-a0/output.log) |
| `scriptbounds-uring-1-a0` | 3 | [ledger](validation/27-scriptbounds-uring-1-a0/ledger.partial), [output](validation/27-scriptbounds-uring-1-a0/output.log) |
| `scripts` | 58 | [ledger](validation/04-scripts/ledger.partial), [output](validation/04-scripts/output.log) |
| `txn-epoll` | 5 | [ledger](validation/10-txn-epoll/ledger.partial), [output](validation/10-txn-epoll/output.log) |
| `txn-uring` | 5 | [ledger](validation/09-txn-uring/ledger.partial), [output](validation/09-txn-uring/output.log) |

FIFO F1–F10 passed **160/160 legs** across both modes, compiled namespaces,
atomic settings and network engines. C1 passed **16/16 legs** (local, boundary,
serve and hot). Sustained FIFO progress passed **16/16 full 60-second legs**:
every one-second window records progress from all 68 clients, exact final data
match, and FIFO-wait counters are positive. The inherited writer-share and
latency assertions also passed. These are bounded correctness witnesses.

AT4.12 passed **423/423 live/oracle legs** across T1–T16, including T11a/T11b.
The selected groups also cover txnorder, execfair, multirace, WATCH, scripting,
xscript, atomics, FLIP/stage obligations, read-local ownership, tracking,
blocking, notifications, persistence and sanitizer checks. The Redis Tcl job
runs its checked-in passing subset; tests excluded by that manifest are not
claimed as coverage of the complete upstream suite.

Both standard `tests/differ_gate.sh` matrices passed **938/938 suite legs per
engine**, plus **16/16 mode-equivalence cells per engine**. Permanent seeds are
7, 19, 20 and 23; rotating seeds are 21 for io_uring and 22 for epoll. Each
matrix runs all 47 generators in split mode and the standard armed inventory
excluding SORT. Each atomic=1 arm includes all four extra accumulated-state
MULTI repeats at seed 19. The checker compares the exact suite/atomic/seed/repeat
tuples and the checked-in generator/seed manifests. All 16 mode-equivalence
cells reached their required state and returned one identical reply digest
within each engine.

`python3 tests/gates_test.py` passed every test group, including the final
**76/76** group, on its [quiet rerun](gates-test.log). The first attempt timed
out one scheduler fixture at its existing 45-second deadline while this lane's
diagnostics, debug compression and bounded controls were also active. Both
[attempts](selftest-attempts.json), the [failure log](gates-test-attempt1.log)
and the scheduler artifact remain. No test deadline or assertion was weakened.

All **12/12 negative controls** in [negative/results.json](negative/results.json)
detected the intended FIFO-admission, same-turn-chain or boundary-service
break, in both modes and namespaces. Each required a fired GDB breakpoint,
the exact expected assertion and inferior exit 1. The changes existed only in
a stopped inferior; no broken source or executable is published. All **16/16
common-image smoke cells** passed EXEC, WATCH, EVAL and FCALL checks across the
two images, modes, engines and database counts. [Final integrity](final-integrity.json)
rechecks the units and images used by those receipts.

`make all` and every `job_production_units` target were [built](production-build.json).
Final [freshness queries](freshness.json) passed **60/60**: `all`, all 55 direct
production-unit targets, both recursive MDB/QSBR arms and the two blockfix target
groups. The phony MDB target is checked through its real recursive builds.
All eight structure-size assertions compile. Debug-only compression preserved
unit `.text`; the initial stale aggregate stamps and their subsequent rebuild
are retained in `freshness-before-stamp-refresh.json`. The final queries also
passed after removing completed sanitizer compiler caches.

The production change is the three Makefile budgets at `4248cfd40`; all `src/`
files and `tests/gate.sh` remain byte-identical to execfifo2. [Scope consistency](scope-consistency.json)
checks **48/48 owner-command** and **36/36 extended parser/owner** comparisons
against PRE, including per-function instruction counts and excluded-callee
call counts. Explicit classified and unclassified memory operands match, with
no added traced stack lines. The [access audit](accesses.md) records the added
FIFO parser stack/TLS accesses and their removal. These finite fixtures have no
WATCH/EXEC state; the active-reservation path is audited separately. Traces do
not count external library bodies, implicit call/return/push/pop stack accesses
or prefetch hints, and do not model hardware cache fills.

All **378/378 finite perf runs** completed with events running at 100%, using
one or two owners and no EXEC/socket load. [Raw counters and medians](perf/README.md)
retain setup, allocation and teardown costs. Some cycle/coherence medians vary
substantially; these measurements do not establish server throughput or
zero regression. The identified compiler-generated work is removed; the
maintainer's matched-load cells decide whether that resolves the reported
server regressions and preserves FIFO's merit.

All work used CPUs 96–111. The selected-job driver uses one slot, server CPUs
96–103 and client CPUs 104–111, normally eight server threads, 16 shards and
ratio 6:2; jobs retain their own explicit geometry. Every correctness/oracle
boot inherits `LC_ALL=C`. The banner audit found 3,333 logs with allocation
information and only server CPUs 96–103 and ports 20600–20602. Separate PAD
controls use port 20690; the self-tests use 20699. All are within the assigned
range.

[SHA256SUMS](SHA256SUMS) identifies the five runnable native arms. PRE and FIFO
match execfifo2's originals exactly. The reconstructed PRE used by linked
fixtures has identical `.text` but differs in the build ID and two INFO
revision strings; [the comparison](pre-loadable-comparison.json) retains the
exact byte differences. PAD-A is a type-A PRE-behaviour twin of the combined
POST-layout image, not of the smaller native POST image. The pair has the same
ELF layout and differs only in its entry jump; the selected PRE/POST bodies
still execute at different addresses.

Final integrity verified all **five native images**, all **16 lossless archives**
by compressed and decompressed hashes, eight proof inputs and four negative-control
units. Build storage is **21,437,095,936 allocated bytes (19.965 GiB)**. Only
regenerable caches/control copies were discarded; [reproduction instructions](reproduce.md)
record their restoration paths. No worktree executable or listener on
20600–20699 remains running.

**DQ=0, DF=0 relative to execfifo2.** No gate row or expectation constant was
changed. The inherited ten FIFO, one live FIFO and four C1 rows are collected
at gate lines 6299–6301, before the quick-tier exit at line 6423. The inherited
maintainer count request remains 992 quick / 1009 full versus source 977/994.

**NOT RUN:** all throughput/load-generator cells, generic ABBA comparisons,
EXEC/depth/script-storm merit and the full `iteration` remain maintainer work.
`flip_saturated` invokes memtier and is excluded by the runtime authorization.
`GATE_PROOF_NO_RATES=1` leaves the quantitative atomic floor, atomic RYOW rates
and stream/xmove rate checks unrun while retaining their correctness checks.
Direct LLC counts are unavailable: this kernel exposes no AMD L3 PMU and rejects
the named and generic LLC events. Its generic `cache-misses` alias counts L2,
not LLC misses. The [PMU audit](pmu-audit/README.md) retains availability failures;
available cross-core fill/exclusive-request events are proxies, not dirty-HITM
counts or FIFO-line attribution.

The approved FIFO contract is unchanged, including D-F3=no: a refused writer
may pass after the older EXEC places but before it starts on that shard. F4
checks that exception. This lane introduces no stronger arrival-to-completion
guarantee, reader retry, seqlock or ownership rule.
