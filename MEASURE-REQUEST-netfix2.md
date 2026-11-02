## netfix2

Base/PRE: `ea48a6b2721a1d9e5964ab24a32e8b54df611bd5`. Branch/worktree:
`cx-netfix2`, `/home/user/Projects/cx-netfix2`. No push. The five S1 mechanisms
are fixed in separate commits. No architecture, ownership protocol, or locked
structure layout changed. Correctness work uses CPUs 8–15, ports 21100–21199,
`LC_ALL=C`, eight-thread 16-shard 6:2 split geometry unless an original auditor
test explicitly chooses another geometry. No throughput measurement was run.

### Directed witnesses

The five `netfix2-*` gate jobs each cover 1s/2s × uring/epoll × databases 1/16.
The scripts assert that kTLS, descriptor exhaustion and suppression actually
occur; absent windows fail. Raw gate results are in
[`docs/netfix2/witnesses`](docs/netfix2/witnesses).

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

The TLS registry audit found GET is the only ordinary command with a
FlatStore-borrowing special TLS row; both rows are changed. Other handlers
copied into TLS registries are copy-only. Existing normal TLS serve paths
already copy borrows; suppressing serve was the missing arm.

Redis 7.4 refuses occupied TCP ports. Its Unix listener unlinks even a live
socket: this lane deliberately follows the task's stricter requirement to
refuse live Unix sockets. `tests/netfix_unix.py` retains the Redis oracle result
and requires the new TomoKV refusal; stale paths and normal cleanup retain
their existing coverage. TCP error text starts `Could not create server TCP
listening socket ...: Address already in use`, exit 1. Maxclients rejection
uses Redis's `ERR CONFIG SET failed (possibly related to argument 'maxclients')
- The operating system is not able to handle the specified number of clients,
try with N` text, where N includes TomoKV's worker reserve.

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
| NET T12 | Redis: 268 PONG + 112 maxclients errors. TomoKV uring: 252 + 128; epoll: 247 + 133. Each totals 380, zero hung. Impossible CONFIG SET rejected, old cap retained. |
| NET T12b | Five descriptor inventories completed: split/fused × engines plus split epoll TLS. |
| NET T12c | Epoll+TLS: 119 PONG + 11 errors out of 130; uring: 135 + 11 out of 146; zero hung. |
| NET T01 | Plain/TLS 1.2/TLS 1.3 stay connected under busy timeout traffic, on both engines; idle samples all zero. |
| NET T21 | All five oracle/plain/TLS byte paths complete; TomoKV application input is +100240 and output +100109/+100110 including the audit INFO overhead. The promoted gate witness subtracts the actual preceding INFO wire length and asserts exact equality. |
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
stamp activity and add application bytes; the plaintext path is unchanged.

### Arms and maintainer measurement

| Arm | SHA-256 | .text bytes |
| --- | --- | ---: |
| `build/netfix2/PRE` | `bf7a8a616072d0c238117c0361cb189f7ed50ecc9232546c51c175c048b32c51` | 9021623 |
| `build/netfix2/POST` | `54b135f7fe662e0561bb0c34e1a45d9281bf802543418b811f40722de1c07a7a` | 9028871 |
| `build/netfix2/POST-layout` | `736bdcff0d827c730448d7eca43f2cd584e7549c1b2fe394a11ca13af5d05e38` | 18050119 |
| `build/netfix2/PAD-A` | `ebb6d767398bebf99bd0d35dab956839e96439d59980903ad0677543cd9c5233` | 18050119 |

**PAD-A is type A, a behaviour twin: PRE behaviour with the common-image
candidate's text size/layout.** The existing common-image linker places POST
first and symbol-isolated PRE second. POST-layout and PAD-A differ only in the
five-byte entry jump selecting the implementation; symbols and sections have
identical layout. PAD-A is the exact twin of POST-layout, **not** the smaller
production POST. [Link receipt](docs/netfix2/pad-a.json) records this limitation.
Production .text grows 7248 bytes; no claim that plain instruction counts rule
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

### Gate arithmetic and broader proof

`DQ = +5`, `DF = +5`. The five-row collection loop is before the quick-tier
exit (`tests/gate.sh`, collection near line 6597; quick exit near 6841).
The base constants are 1046/1063, so the maintainer's new counts should be
1051/1068. `EXPECT_QUICK` and `EXPECT_FULL` were not edited. The maxclients Tcl
promotion adds six assertions per mode/engine/namespace inside the existing
Tcl job, not another public row.

The standard gate planner requires disjoint server/load CPU sets, unavailable
inside this lane's eight-CPU allocation. Its explicit
`GATE_CORRECTNESS_SHARED_CPUS=1` mode requires selected jobs plus
`GATE_PROOF_NO_RATES=1`, permits only the eight physical server CPUs and their
load subset, and cannot issue a full-gate receipt or run ABBA. No gate geometry
or failure expectation was weakened. Partial ledgers are reported as partial.

The reproducible selected-job driver is
[`tools/netfix2_proof.sh`](tools/netfix2_proof.sh). Broader job ledgers, Tcl and
differential results, production target freshness, and the final disk size
will be appended after those checks finish. Current completed harness check:
`python3 tests/gates_test.py`: 77/77 tests pass; gateplan self-tests pass.
