## netfix2

Base/PRE: `ea48a6b2721a1d9e5964ab24a32e8b54df611bd5`. Branch/worktree:
`cx-netfix2`, `/home/user/Projects/cx-netfix2`. No push. The five S1 mechanisms
are fixed in separate commits. No architecture, ownership protocol, or locked
structure layout changed. Correctness work uses CPUs 8–15, ports 21100–21199,
`LC_ALL=C`, eight-thread 16-shard 6:2 split geometry unless an original auditor
test explicitly chooses another geometry. No throughput measurement was run.

The requested S1 witnesses pass. **The broader proof is not entirely green:**
existing EOF/retirement and INFO error-stat diagnostics fail on PRE and POST,
and one CLIENT KILL count mismatch did not reproduce in bounded repeats.
Those results are retained below; they are not waived or represented as passes.

### Directed witnesses

The five `netfix2-*` gate jobs each cover 1s/2s × uring/epoll × databases 1/16.
The scripts assert that kTLS, descriptor exhaustion and suppression actually
occur; absent windows fail. The byte-counter witness covers plaintext, TLS 1.3 fd BIO, TLS 1.2 kTLS, and
TLS 1.2 CBC memory BIO (32 exact byte-accounting legs). Stepwise PRE/negative
receipts are in [`docs/netfix2/witnesses`](docs/netfix2/witnesses). Final frozen-arm
receipts, including both common-image controls, are in
[`docs/netfix2/regressions/final`](docs/netfix2/regressions/final).

| Item | PRE witness | POST result | Mechanism changed | Residual |
| --- | --- | --- | --- | --- |
| EX5.2 | All 8 configurations crash in the first watched TLS tracking arm. | 32/32 TLS 1.3/userspace and TLS 1.2/kTLS tracking/SKIP arms return exact 20 KB data, survive, and take no FlatStore borrow. | Both TLS GET registry rows use `cmd_get_tls_notify`; suppressing writeback copies and releases an unexpected TLS borrow. | Copy cost is intentional. The defensive writeback arm also has a poisoned-release unit witness. |
| NT5.3 | All 8 configurations admit a second TCP instance. | 24/24 occupied TCP/TLS/Unix endpoints refuse the second instance with exit 1; the first retains its data. | Boot TCP/TLS probes bind without SO_REUSEPORT; Unix probes a live socket before unlinking. | TCP probe close → worker bind and Unix connect → unlink remain simultaneous-start TOCTOU windows. No process-wide lock or listener architecture change. |
| NT5.2 | All 8 configurations accept impossible maxclients; forced inherited-FD pressure produces millions of immediate accept errors. | All 8 reserve-cap/CONFIG/refusal legs pass; all 8 forced EMFILE legs observe bounded retries, responsive existing clients, and recovery after FDs free. | Per-worker descriptor reserve plus Redis's 32 shared reserve; cold CONFIG validation; 100 ms EMFILE/ENFILE retry through existing deferred timers. | Unexpected inherited FDs or external limit reductions can still exhaust descriptors; new accepts wait for capacity, without busy-spin. |
| NT5.1 | All 8 busy TLS 1.3 clients are disconnected by timeout 1. | All 8 survive four seconds of busy traffic; exact application-byte accounting matches plaintext. | Stamp successful TLS plaintext reads/writes and count application bytes there; remove ciphertext double counting. | TLS transport/control bytes are deliberately excluded from Redis-style net byte counters. |
| IO5.2 / IO15 | All 4 plain 2s AOF activation failures abort after a ready banner; 4 fused controls already exit 1. | All 8 exit 1 without a banner; 40/40 immediate banner connections succeed. | Reuse the existing loaded/ready/running boot gate for split IO activation; replace activation aborts with clean worker stop/join. | Simultaneous process port-probe race remains as above; no wider IO15 change. |

All five public rows fail on frozen PRE and PAD-A. The common-image
POST-layout arm passes all five (6 ok including release, 0 FAIL).
PRE AOF reproduction initially used an invalid appenddirname and was replaced
with a genuinely unwritable directory. An initial FD stress attempt lowered
RLIMIT after io_uring submission; that did not arm its captured-limit path.
The final witness passes held FDs at exec time and requires nonzero EMFILE on
every engine. Those initial attempts are not counted as proof.
An earlier byte-counter witness subtracted two asynchronous INFO samples and
once included a late seven-byte readiness PONG. The final witness instead uses
a fresh server per transport, no readiness PING, and exact absolute wire-byte
accounting with bounded convergence; it neither skips nor widens a tolerance.

A follow-up boot injection fails the elected AOF writer's reuseport bind after
its exclusive probe. The initial IO5.2 candidate hung in 2/8 legs because peer
IO workers waited for a writer that could never publish ready. The boot-only
AOF wait now checks its worker stop flag. All 8 injected failures exit 1,
with no ready banner, in addition to the 8 unwritable-directory checks and
40 banner connections. This is cancellation of an existing wait, not a new
persistence protocol. The negative and corrected gate receipts are retained.

The broader source-consistency job caught a stale generated R7/fused IO envelope.
Regeneration carries the same TLS input accounting, accept retry and exclusive
boot probes into that existing call graph. The gate also runs the five witnesses
with `--reorder 1` in fused mode on both engines/namespaces. This adds no public
rows and introduces no new scheduling algorithm.

The TLS registry audit found GET is the only ordinary command with a
FlatStore-borrowing special TLS row; both rows are changed. Other handlers
copied into TLS registries are copy-only. Existing normal TLS serve paths
already copy borrows; suppressing serve was the missing arm.
The borrowing inventory also checks scatter MGET (`scatter_engine.inc` /
`xshard_commands.inc`), which already copies/releases TLS value slots, and
MULTI/EXEC (`multi.inc`), which has its own TLS borrow conversion. Scripting
consumes and releases nested GET borrows before returning its copied reply.
The `l4prebuild.cc` use of `op.zc_ptr` is a tagged SET construction sidecar
with zero length, not a reply borrow. No other ordinary TLS registry row
needs a handler substitution.

Redis 7.4 refuses occupied TCP ports. Its Unix listener unlinks even a live
socket: this lane deliberately follows the task's stricter requirement to
refuse live Unix sockets. `tests/netfix_unix.py` retains the Redis oracle result
and requires the new TomoKV refusal; stale paths and normal cleanup retain
their existing coverage. TCP error text starts `Could not create server TCP
listening socket ...: Address already in use`, exit 1. Maxclients rejection
uses Redis's `ERR CONFIG SET failed (possibly related to argument 'maxclients')
- The operating system is not able to handle the specified number of clients,
try with N` text, where N includes TomoKV's worker reserve.

The canonical oracle is `/home/user/Projects/redis/src/redis-server` (7.4.10).
Existing TLS-specific gate oracle jobs additionally use the gate's TLS-enabled
7.4.10 build at `/home/user/Projects/redis74-tls/src/redis-server`; both versions
and digests are recorded in [oracles.json](docs/netfix2/oracles.json).

### Auditor reruns

[`tests/netfix2_audit.py`](tests/netfix2_audit.py) copies, confines, and reruns
the original scripts without editing round5-read. Original/adapted hashes,
exact adaptation diffs, commands, exit statuses and logs are retained in
[`docs/netfix2/auditors`](docs/netfix2/auditors). PRE-crash assertions alone are
promoted to POST success/liveness assertions; exact data and kTLS assertions
remain. T02b's shell now records the server's PIPESTATUS, not grep's status.

| Auditor script | POST result |
| --- | --- |
| EX T2 / T20 / T20b / T20d | 28/28, 15/15, 4/4, 2/2 assertions. |
| NET T17 | All four Redis/TomoKV first/second combinations reject the second TCP server, exit 1. |
| NET T12 | Redis: 268 PONG + 112 maxclients errors. TomoKV uring: 252 + 128; epoll: 246 + 134. Each totals 380, zero hung. Impossible CONFIG SET rejected, old cap retained. |
| NET T12b | Five descriptor inventories completed: split/fused × engines plus split epoll TLS. |
| NET T12c | Epoll+TLS: 119 PONG + 11 errors out of 130; uring: 136 + 10 out of 146; zero hung. |
| NET T01 | Plain/TLS 1.2/TLS 1.3 stay connected under busy timeout traffic, on both engines; idle samples all zero. |
| NET T21 | All five oracle/plain/TLS byte paths complete; TomoKV application input is +100240 and output +100109/+100110 including the audit INFO overhead. The promoted gate witness starts a fresh server per transport and requires exact absolute application-byte totals, including each preceding INFO wire reply, within a bounded wait. |
| IO T02 / T02b | Oracle plus four TomoKV configurations exit 1; shell reproduction exits 1, no ready banner, port closed. |
| IO T03 / NET T08 | 60/60 and 40/40 immediate banner connections succeed; zero refusals. |

### Command-scope zero cost

[`tools/netfix2_counts.py`](tools/netfix2_counts.py) links each arm's actual
production objects to the existing serverless owner/scatter fixture. Ptrace
counts executed server instructions, including slow out-of-line server bodies,
excluding system/library bodies and fixture setup/teardown. No server or rate
benchmark is involved. [All 80 comparisons](docs/netfix2/counts/comparison.json)
are exactly zero delta: GET/SET/INCR/MGET/MSET × 1s/2s × batch 1/32 × atomic
0/1 × normal/db0 namespaces. Raw scope traces, ranges, hashes and build
receipts are retained. Compressed fixture binaries remain under build/netfix2.

[TLS counts](docs/netfix2/counts/tls-comparison.json) use a 20 KB GET, clean or
watched, both modes/namespaces/depths (16 comparisons). Clean TLS GET is exactly
unchanged. Watched TLS GET deltas are:

| Namespace | Batch 1, either mode | Batch 32, either mode |
| --- | ---: | ---: |
| normal | -49 instructions/batch | -204 instructions/batch |
| db0 | -54 instructions/batch | -364 instructions/batch |

These are server instruction counts only: POST replaces a borrow with a 20 KB
copy. Library memcpy/encryption and TLS send/clock/counter work lie outside
this command scope. The negative counts are **not a throughput or total CPU
cost claim**. Successful userspace TLS read/write operations now additionally
stamp activity and add application bytes. The plaintext suppression slow path
also gains a TLS-kind test when an operation already holds a store borrow;
writeback/IO loops are outside the command scope. Thus this proves the requested
ordinary-command instruction null, not whole-loop byte identity or a rate null.

### Arms and maintainer measurement

| Arm | SHA-256 | .text bytes |
| --- | --- | ---: |
| `build/netfix2/PRE` | `bf7a8a616072d0c238117c0361cb189f7ed50ecc9232546c51c175c048b32c51` | 9021623 |
| `build/netfix2/POST` | `f9c45811063331942f58bc927aa6a1a343e201041e55b1f60b44b504a3020838` | 9029159 |
| `build/netfix2/POST-layout` | `7966cfd05ad29704d349fb0b675a9ea4aced172978ff789db2ef2d3b1e33d18f` | 18050407 |
| `build/netfix2/PAD-A` | `e26d2dab5b22c2df49a990bea8a49460fee8824d1adac0222e80a16c005dc810` | 18050407 |

**PAD-A is type A, a behaviour twin: PRE behaviour with the common-image
candidate's text size/layout.** The existing common-image linker places POST
first and symbol-isolated PRE second. POST-layout and PAD-A differ only in the
five-byte entry jump selecting the implementation; symbols and sections have
identical layout. PAD-A is the exact twin of POST-layout, **not** the smaller
production POST. [Link receipt](docs/netfix2/pad-a.json) records this limitation.
Production .text grows 7536 bytes; no claim that plain instruction counts rule
out instruction-cache/layout effects. [Hashes](docs/netfix2/SHA256SUMS).

Maintainer: use the gate's quiet-box instrument on the unchanged
[14 generic cells plus 2s GET/SET p1/p32](docs/netfix2/merit.cells.txt).
The additional IDs are h53/h54/h21/h22; use 16 shards and 6:2 on eight server
cores for those 2s guards. Preserve each cell's normal connections, payload,
offered load and score. Run PRE versus production POST for the release verdict,
then POST-layout versus PAD-A for the common-image behaviour control; compare
PRE versus PAD-A to expose the common-image placement effect. Record rates at
matched offered load, cycles/op, instructions/op and IPC per cell and arm.
Apply the maintainer's existing per-cell regression rule; do not average away
a failed cell. Performance benchmarks, load generators, full iteration and
these measurements are **NOT RUN: reserved to the maintainer**.
System-wide ENFILE exhaustion is **NOT RUN**: it would require host-wide
pressure outside this lane's resource allocation. The shared retry branch is
exercised with real process-local EMFILE on both engines.

### Gate arithmetic and broader proof

`DQ = +5`, `DF = +5`. The five-row collection loop is before the quick-tier
exit (`tests/gate.sh`, collection line 6605; quick exit line 6849).
The base constants are 1046/1063, so the maintainer's new counts should be
1051/1068. `EXPECT_QUICK` and `EXPECT_FULL` were not edited. The maxclients Tcl
promotion adds six directed checks per mode/engine/namespace, plus a restore
check, inside the existing Tcl job, not another public row.

The standard gate planner requires disjoint server/load CPU sets, unavailable
inside this lane's eight-CPU allocation. Its explicit
`GATE_CORRECTNESS_SHARED_CPUS=1` mode requires selected jobs plus
`GATE_PROOF_NO_RATES=1`, permits only the eight physical server CPUs and their
load subset, and cannot issue a full-gate receipt or run ABBA. No gate geometry
or failure expectation was weakened. The equivalence and shared process helpers
use the same guarded exception, with negative controls for every required guard.
The first io_uring equivalence invocation rejected CPU overlap before boot; its
corrected selected-job rerun is reported separately. Partial ledgers are reported
as partial.

The standard Redis differential suites completed four legs per engine:
938 comparison rows on io_uring and 938 on epoll, **1,876 total with zero
differences**. Permanent seeds were 7, 19, 20 and 23, with rotating seed 21
on io_uring and 22 on epoll. Mode equivalence passed all 16 cells on each
engine; the corrected io_uring selected-job rerun took 21.67 seconds and
replaces only the earlier pre-boot CPU-plan rejection.

The pre-existing epoll closed-blocking-pipeline retirement check (`netio.py`
F5) remains intermittent: four bounded repeats failed in 3/4 PRE runs and
1/4 POST runs, in either mode. These are correctness incidences, not rates or
a performance comparison. Each failing connection remained visible to CLIENT
LIST after peer closure. The [unchanged PRE/POST logs](docs/netfix2/regressions/netio-repeats)
are retained; this row is not reported green or suppressed. It lies outside the
five audited mechanisms fixed by this lane.

Final partial-ledger counts follow. The first batch contains jobs that enumerate
both engines themselves; the epoll batch repeats the environment-selected jobs.
These counts include prerequisites and optional diagnostics, not a full-gate
landing inventory. [Raw ledgers and job logs](docs/netfix2/regressions/final).

| Selection | Passing / failing collected rows | Result |
| --- | ---: | --- |
| Main batch, 102 jobs | 360 / 21 | Failures classified below; original ledger retained. |
| Epoll follow-up, 13 jobs | 62 / 2 | Both failures came from one ASAN boot refused by the quiet-CPU preflight. |
| [Core units + corrected Unix/transaction jobs](docs/netfix2/regressions/core-units) | 27 / 0 | ASAN/UBSAN and TSAN core checks, Unix pathname cases, all transaction WATCH rows pass. |
| [Epoll split zero-copy rerun](docs/netfix2/regressions/zc-epoll-rerun) | 6 / 0 | Quiet preflight unchanged; ordinary and ASAN borrow batteries pass. |
| Fused TLS/zero-copy/reply suppression, each engine | 28 / 0 each | Both selections pass, including ASAN. |
| Five witnesses with fused reorder enabled | 6 / 0 | Both engines and namespaces pass; engagement checked. |
| Common-image POST-layout | 6 / 0 | All five S1 witnesses pass. |
| Common-image PAD-A | 1 / 5 | All five S1 witnesses fail as required; release prerequisite passes. |

Three setup problems in the main batch are accounted for explicitly. The
legacy Unix adapter omitted the new helper's `reorder` setting; it now supplies
zero and passes all 20 pathname cases. Fifteen transaction rows could not find
native units beside the frozen POST copy; all 16 transaction rows pass using
`build/tomokv`, verified byte-identical to POST, beside the matching production
units. The native EOF diagnostic initially lacked its required fixture directory;
the fixtures are now built from each arm's own headers and production objects.
Its valid PRE/POST results remain failures, as described below. The earlier
io_uring equivalence setup rejection and the epoll ASAN preflight refusal also
have passing reruns. No original failed ledger was rewritten.

The [optional PRE/POST diagnostics](docs/netfix2/regressions/optional-diagnostics)
each collect 1 passing prerequisite and 4 failed diagnostic rows:

| Existing diagnostic | PRE | POST | Residual |
| --- | --- | --- | --- |
| Native epoll coalesced EOF | 4 open-peer controls pass; 4 EOF checks fail. | Same, both modes/namespaces. | A short read sharing EPOLLRDHUP can lose the parked client's teardown edge; consistent with F5. |
| Accepted input followed by FIN | Redis 5/5; TomoKV 18 truncated-input cases and 1 retirement timeout out of 40. | Redis 5/5; TomoKV 15 truncated-input cases out of 40. | Input sent before FIN can be discarded before execution. These finite incidences are not an improvement claim. |
| INFO error statistics | 56 failed counter checks. | Same 56 failed checks. | Missing total/prefix error counters; INFO belongs to cfgfix2. |

The native EOF fixture keeps the original assertions and runs each case in a
fresh child so the first failure cannot hide the other mode. The EOF defects
are outside the five requested mechanisms. A separate fix must preserve EOF
state through a short read and drain already accepted input/operations before
retiring a half-closed client; this lane does not change that lifetime algorithm.

The main batch's CLIENT KILL failure was `5` killed versus `4` expected in the
first iteration of `1s-uring-db1-a1-r0`. The server accepted six connections,
including the readiness probe. That suggests a fixture boundary issue but does
not establish the cause. [Four unchanged PRE and four unchanged POST repeats](docs/netfix2/regressions/disconnect-repeats)
all pass. The initial observation remains unresolved and is retained with its
exact failed leg and server log; it is not classified as a proven baseline issue.

Tcl passes in all four mode/engine runs: each has 37 manifest files, 39 validated
rows including two isolated cases, and 1,876 passing assertions with zero
unexpected failures. Each retains the existing five named setup diagnostics
and 431 skips. The manifest was unchanged. The new maxclients Tcl checks pass
in all eight mode/engine/namespace configurations, repeated by both engine
selections. The earlier pre-R7 Tcl socket-bind setup failures also cleared on
these complete reruns.

`python3 tests/gates_test.py` passes 78/78; gateplan and mode-equivalence helper
self-tests pass. `make all` and every `job_production_units` target build;
[all 60 final freshness checks](docs/netfix2/production-freshness.json) return zero.
Locked layouts remain unchanged. Final build usage is `14G` by `du -sh`
(14,884,536,320 allocated bytes): completed test executables had debug
information stripped with identical `.text`, and large
completed test data/objdumps were losslessly compressed with verified hashes.
The four frozen arm hashes remain unchanged; [final checks](docs/netfix2/final-checks.json)
record their verification and the unchanged production source tree.

The reproducible selected-job driver is
[`tools/netfix2_proof.sh`](tools/netfix2_proof.sh); native EOF and optional
diagnostic controls are prepared by
[`tools/netfix2_diagnostics.py`](tools/netfix2_diagnostics.py). The driver verifies
that the colocated production binary equals frozen POST before using its units.
No performance benchmark, load generator, full iteration, push, or merge was run.
