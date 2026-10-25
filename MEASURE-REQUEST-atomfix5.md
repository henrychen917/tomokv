# Cross-shard contention compatibility and accounting

## atomfix5

Branch/worktree cx-atomfix5, base ef5204b2e9650693228cc105b34625516898b82d.
No push. This request separates delivered changes from unresolved contention
paths; it makes no throughput claim.

AT4.13 WATCH key counts are fixed. AT4.19 gains a non-vacuous exact-accounting
gate row; it already passes the named PRE and rejects the isolated broken-writer
control. AT4.11 uses the allowed documentation option. AT4.12 is reproduced and
stops at the requested design handoff because this base removed EXEC's exclusive
fallback. AT4.20 (atomic-1 retry ceiling) and AT4.21 are NOT REPRODUCED at the
recorded geometries. AT4.7 awaits maintainer measurement before implementation.
The adjacent docs/atomfix5 item reports contain the detailed evidence.

### Required maintainer merit work (NOT RUN in this lane)

Use docs/atomfix5/merit-cells.txt: the exact generic 14 from
tests/wbland_merit_cells.txt plus 96 unchanged atomic-1 multi-key cells from
tests/headline_cells.txt. Use the gate's own ABBA instrument, reviewed geometry
and offered-load calibration, PRE/PRE null, PRE versus POST, PRE versus PAD-A,
and POST versus PAD-A. Preserve CPU/SMT, NUMA, ratio, shards, pipeline depth,
connections, binary hashes, sample order and workload/key geometry. For every
cell report rate at matched offered load, cycles/op, instructions/op and IPC;
depth-1 cells also retain latency. Rate and the matched null decide regression;
instruction and IPC changes explain it. Identity alone is not acceptance.

Arms: build/tomokv-pre (ef5204b2e), build/tomokv (POST),
build/tomokv-pad-a. PAD is **kind A, behaviour twin: PRE WATCH counting with the
candidate's exact text size, function placement and data layout**. It copies the
validated relocation-free PRE leaf into each namespace's larger POST function,
NOP-fills that function's unused tail and changes no symbol address or section
size. All other instructions remain POST. tools/atomfix5_arms.py and
docs/atomfix5/arms.json specify every byte. Its WATCH gate must fail like PRE. No PAD-B is
needed for this small change. The broken-writer test copy is not a merit arm.

AT4.7's separate measure-first 12-wave request (four publishers × 1/8/64 tasks)
is in docs/atomfix5/wave-cost.md. Do not infer those per-wave counts from whole-
server spinning PMU totals or from this lane's WATCH-only PAD.

### Completed proof and its limits

All new rows ran through tests/gate.sh's own GATE_ONLY_JOBS interface, with every
declared mode/engine/database/atomic leg present on PRE and POST:

| Directed row | PRE | POST | Additional control |
|---|---|---|---|
| AT4.13 WATCH count | Eight databases-16 legs fail; eight databases-1 controls pass | 16/16 legs pass | PAD-A reproduces all eight PRE failures |
| AT4.19 exact accounting | 32/32 schedules pass | 32/32 schedules pass | Broken writer fails all eight legs on 128 lost acknowledged elements |

AT4.19 cannot honestly supply PRE-fails evidence: ef5204b2e already has the
writer-ordering mechanism. Its isolated broken control proves the new row is
not vacuous. This is a test-gap delivery, not a new writer-ordering fix.

The broader POST jobs also ran through the gate's own interface. These are
partial selections including prerequisites, not a full-gate receipt; counts
are per run and include repeated labels across engines and rechecks.

| POST selection | Passing gate rows | Failing gate rows |
|---|---:|---:|
| io_uring families | 280 | 2 |
| epoll-default families | 207 | 2 |
| io_uring standard differential + mode equivalence | 6 | 0 |
| epoll standard differential + mode equivalence | 6 | 0 |
| io_uring startup recheck, ports 34860–34899 | 70 | 0 |
| epoll startup recheck, ports 34880–34899 | 71 | 0 |

All four initial failures were servertail child-server startup failures with
`bind: Address already in use`: io_uring split/armed atomic-0, and epoll armed
atomic-0/1. The same four gate jobs passed on the rechecks. No assertion was
weakened. Both original failures and reruns are retained. Their exact bind cause
was not established; the socket-state watchers saw no recurrence on the rechecks.

Each engine passed **938 differential suite executions** (930 standard seed/suite
combinations plus eight atomic-1 repeats), both armed read-local witnesses, and
all **32 mode-equivalence configurations**. Standard permanent seeds were
7, 19, 20, 23; the planner selected rotating seed 21 for io_uring and 22 for
epoll. The epoll adapter supplies `--net-io epoll` only when a job leaves the
engine unspecified; it preserves every explicitly declared engine.

NOT RUN: the differential script's ten fused SORT combinations per engine,
because that existing suite explicitly requires split 6:2. They were skipped by
the gate's standard matrix and were never counted as passes. Split SORT passed.
No declared leg of either new row was skipped.

`python3 tests/gates_test.py`: final **70/70 PASS**, with
`GATE_TEST_PORT=34811 taskset -c 48-63`. An earlier run had two scheduler-fixture
subprocess timeouts during compilation; its rerun also passed all 70. Those
logs remain alongside the final constrained run.

`make all` plus every job_production_units target completed on CPUs 48–63 with
-j16. Final `make -q` checks report **44/44 targets fresh**, including all and
mdbqsbr-live-arms. The production build enforces all eight locked layouts.

The script refusal issue remains real on POST. The four io_uring txnorder case-c
legs counted 8,830 / 3,217 TRYAGAINs in fused atomic 0/1 and 2,455 / 12,040 in split
atomic 0/1 (BUSY=0 in these particular runs). The separate PRE cut-slot test
reproduced BUSY in both modes at both atomic values. Existing accept-and-count
assertions remain because no escalation implementation was delivered. These
liveness passes are not evidence of Redis-compatible refusal-free completion.

Additional observed issue: atomic-0 LMPOP/ZMPOP returned null with a populated
fallback key. It is recorded separately from the unreproduced atomic-1 ceiling;
see docs/atomfix5/pop-retries.md. No fix is claimed for AT4.20 or AT4.21.

The exact selected job map and refusal-text grep are in
[affected-jobs.md](docs/atomfix5/affected-jobs.md) and
[refusal-expectations.txt](docs/atomfix5/refusal-expectations.txt).
[proof-runs.json](docs/atomfix5/proof-runs.json) inventories every broader job,
verdict, seed plan, skip and archive hash. Archives retain logs, receipts and
replay inputs; generated database images remain in build/ and are inventoried
with sizes/hashes instead of being duplicated in the committed archives.
Directed PRE/POST/control logs and ledgers are adjacent. The oracle's actual
version, binary digest and source checkout identity are in
[oracle.json](docs/atomfix5/oracle.json).

### Identity, binaries and owner count update

Object identity: 1,213/1,213 registered command handlers and 1,316/1,316 selected
hot bodies unchanged. The linked normalizer has 331/333 selected bodies
unchanged; generic xshard_prepare and its cold split differ. The 12 specifically
named GET/SET and captured-local-MGET bodies match. The complete MGET/MSET
preparation path is not byte-identical because it shares xshard_prepare.
See [identity.md](docs/atomfix5/identity.md) and the complete inventories. Merit
decides this compiler drift; it was neither hidden nor used to stop the lane.

.text is 8,124,983 bytes on PRE and 8,125,079 on POST/PAD-A (+96 bytes).
PAD-A is the type-A behaviour twin described above and preserves every POST
symbol address and size. Its full CLIENT INFO/CLIENT LIST traces reproduce PRE.
The broken-writer control is separate and is never a merit arm.

| Binary | SHA-256 |
|---|---|
| build/tomokv-pre | `adaa817d5be4fb08cc433a25c981af2dedb950fba102faed797f90e2acc47487` |
| build/tomokv | `6388844742d94aaa373064dab3a2aedd18b2f03c9e58b36728a6283b75513b4f` |
| build/tomokv-pad-a | `f205bbbb3d97e6b8f1f9cc757b236768b6027475407e5dc4a0f37392042afa93` |

All four recorded binary digests, including the broken control, were verified
after the differential runs. The PRE object snapshot was removed after the
completed object audits; the three merit binaries and requested production
build targets remain. No extra full checkout was created.

Source and label fixture both enumerate 758 labels, with no missing/extra
labels. New collections are at tests/gate.sh lines **4751 and 4753**, before
the quick-tier exit at **4950**: **DQ=+2, DF=+2**. The owner should change
EXPECT_QUICK **739 -> 741** and EXPECT_FULL **756 -> 758**. Neither constant was
edited. Consequently gate_ledger_fixture.py exits 1 on the protected full-count
mismatch; its source/fixture label comparison matches exactly.

NOT RUN: performance measurements, AT4.7's per-wave instruction experiment,
and full tests/gate.sh iteration. These remain with the maintainer under this
lane's runtime authorization. AT4.7 has no optimization implementation pending
those measurements. The merit and 12-wave requests above specify the work.
This report makes no throughput or performance-improvement claim.
