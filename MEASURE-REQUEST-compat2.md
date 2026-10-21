## compat2

Lane `cx-compat2`, based on `bce4eb0aa6ab5b855903e201f6f19b321e09cba0`. No push.
Correctness work uses server CPUs 64–71, oracle CPU 72, client CPUs 73–79,
builds on CPUs 64–79 with `-j16`, and ports 26800–26899. No performance workload
or `tests/gate.sh iteration` is run by this lane.

### Changes and reverified anchors

- **C1 / NT-new-6:** reproduced on PRE in 1s/2s × epoll/io_uring. Redis's
  advertised arity precedes NOAUTH; PING's optional-argument maximum is handler
  grammar and follows NOAUTH. PRE returns an arity error for the ten-argument
  unauthenticated PING; Redis 7.4.10 returns `-NOAUTH Authentication required.\r\n`.
  The new cold helper uses the generated Redis metadata for command/subcommand
  existence and advertised arity. It also preserves EXEC's error prefix, AUTH's
  syntax error, QUIT's variadic behavior, and the fully qualified child name in
  ACL denials. The existing unauthenticated output-limit check remains in place.
  `DBSIZE NOW`, a deliberate TomoKV extension, remains available after AUTH.
  Anchors: `src/core/io_loop.h` outer arity branch, `src/cmd/acl.inc` dispatch,
  `/home/user/Projects/redis/src/server.c` `processCommand`; the pinned oracle is
  `/home/user/Projects/redis74/src/redis-server` (7.4.10).
- **C2 / HX-3:** reproduced on PRE in all four geometries with `--atomic 1`,
  16 shards, two distinct owners, a held RENAME carrying an expired candidate
  TTL, and a persistent live predecessor. GET returns `old` but emits `expired`.
  `FlatStore::find_notify` now suppresses physical-expiry notifications while
  `find` takes its logical MVCC resolver. Keymiss still follows the returned
  version; ordinary physical expiration still emits exactly one expiry event.
  The guard uses the exact `atomic_pending_->live != 0` predicate in `find`,
  not `atomic_has_records()` (which also includes script reservations). A
  deterministic reservation-only unit proves real expiry still emits `expired`
  then `keymiss`; its broader-guard negative control fails as intended.
  **The plain-MSET expired-candidate shape is NOT REPRODUCED:** MSET clears TTL.
  The production row proves that control, then uses RENAME's retained TTL.
  `tools/compat2_mset_control.py` also constructs the requested exact MSET state
  in a disposable allocator-only source copy: two marker-valued candidates get
  witnessed deadlines. No MVCC, notification, hold, or production code is
  replaced in this control. Its results are recorded separately.
- **C3 / NT-new-5:** reproduced as bounded gauge lag, not a persistent kTLS
  socket leak. On PRE fused epoll, `CLIENT LIST` already loses the closed TLS1.2
  client while `tls_ktls_active` and `tls_current_connections` remain one; later
  reclamation returns them to zero. `close_client` now releases the TLS sidecar
  and its gauges at the socket-release/quiescence fence. Client reclamation
  remains deferred. The deterministic fixture holds that exact interval and
  checks both modes; the live control checks real default-cipher TLS1.2 kTLS
  and TLS1.3 OpenSSL fallback on both engines.
  The original ntfix `databases 1` / fused read-local geometry was also checked
  on both engines for PRE/POST/PAD-A: all six live teardown controls pass
  ([receipts](docs/compat2/ktls-db0-anchor/results.json)). They check eventual
  teardown; the held-reclamation fixture is what distinguishes the gauge timing.

The register's 2026-10-12 HX-3 and 2026-10-20 NT-new-5/6 entries, the ntfix
AUTH-versus-arity receipt, and hexpread's adjacent-notification note were reread.
The current registry has **245** top-level entries, including local `FLIP`;
the old background's 243 is not the inventory used by the new differential.

### Gate rows and correctness proof

`job_compat2` contributes one row per item. Each row covers 1s/2s and both engines;
the TLS row additionally requires the deterministic deferred-reclamation unit.
Collection is at `tests/gate.sh:3904`, before the quick-tier exit at line 4016.
**DQ = +3, DF = +3**. Owner counts should become **668 / 685** from **665 / 682**.
`EXPECT_QUICK` and `EXPECT_FULL` are untouched.

The C1 differential performs 1,522 comparisons, including all registered Redis
parents and their advertised children, both authentication states, generated
arity boundaries, local maximum/NOAUTH boundaries, unknown commands, and
ten-argument PING. Fully authorized wrong-arity probes run on requirepass alone;
only afterward does a restricted user make right-arity commands such as SHUTDOWN
safe and deterministic to compare. Variadic commands with no representable bad
advertised arity and the local FLIP extension are explicitly inventoried.

Final proof receipts use the `*-complete` directories under `docs/compat2`.
Intermediate failed/aborted runs remain recorded: an initial launcher incorrectly
passed `--ratio` to fused mode; a preliminary scheduler self-test timed out while
compilation occupied its CPUs; and initial differential/build runs were stopped
to refine the default-user C1 coverage and the script-reservation guard. An
initial PAD comparison assumed stable Redis COMMAND subcommand order; comparing
the unique command/arguments/authentication keys proves the exact reply bytes
agree. These intermediate attempts are not counted as final passes.
They are retained in `docs/compat2/intermediate-evidence.tar.xz`; the adjacent
manifest records each original path and SHA-256. Extract from this worktree's
root to recover the original logs. Initial anchor reproductions remain unpacked.

| Directed result (each of four mode/engine geometries) | PRE | POST | PAD-A |
|---|---:|---:|---:|
| C1 differences in 1,522 comparisons | 228 | 0 | 228 (all PRE replies identical) |
| C2 false expiry events across three predecessor GETs | 3 | 0 | 3 |
| C3 kTLS gauge after socket release, while Client is retained (each mode) | 1 | 0 | 1 |

The injected MSET state gives the same C2 PRE/POST result in all four geometries.
The ordinary MSET TTL-clearing control emits zero events on all arms. Every C2
GET still returns the live predecessor, and `expired_keys` stays flat while the
group is held. [Directed summary](docs/compat2/directed-summary.json),
[final expiry controls](docs/compat2/expiry-complete/results.json).

`make -j16 all` and all **35** named `job_production_units` targets pass; `make -q`
passes for `all`, each target, and both additional `mdbqsbr-live-arms` variants.
All **40** recorded build/freshness commands return zero:
[build receipt](docs/compat2/units-complete/results.json).
The final audit repeats all **38** freshness checks, verifies unchanged frozen
binary hashes and EXPECT definitions, and checks generated-code synchronization:
[final audit](docs/compat2/final-audit.json).

All **24** live TLS battery/KeyUpdate commands pass across both modes and engines,
including required/optional client certificates, default kTLS and forced
userspace fallback. All **five** serverless RX/KeyUpdate cases pass with the
correct arguments: [live receipt](docs/compat2/tls-complete/results.json),
[unit receipt](docs/compat2/tls-units-complete/results.json). The live receipt also
retains the separate incorrect invocation described below.

`python3 tests/gates_test.py` passes **66/66**, including **14/14** nested
persistence-identity checks, with `GATE_TEST_PORT=26899` and no deadline changes:
[final self-test log](docs/compat2/selftest-port-complete/gates-test.log).

Standard `tests/differ_gate.sh` uses its unmodified suite/seed inventory and
`--atomic 0/1`, server CPUs 64–71, oracle CPU 72, clients 73–79, ports 26810/26811.
The split geometry is 16 shards / 6 io + 2 ex; the fused geometry arms read-local.

| Engine / geometry | Standard matrix result |
|---|---|
| io_uring / split | 475 checks, 0 failures; all 32 mode/knob equivalence combinations pass |
| io_uring / fused read-local | 466 checks, 0 failures; read-local execution witnessed |
| epoll / split | 465 checks passed, 10 INFO accounting failures; all 32 mode/knob equivalence combinations pass |
| epoll / fused read-local | 546 checks passed, 12 INFO accounting failures; read-local execution witnessed |

Receipts: `docs/compat2/differ-complete/`; its durable history retains every
suite/seed/atomic verdict and the executed comparison-coverage files.
Total: **1,952 passed / 22 failed**, with every failure in the PRE-reproduced
epoll INFO accounting check below. All **168** notification/hash/hash-TTL legs
(`notify`, `hash`, `hexpire`, `edgetime`) pass across both modes, engines and
atomic settings. Every matrix includes permanent seeds 7/19/20/23; rotating
seeds are 21 (uring split), 22 (uring fused), 24 (epoll split), and 24/25
(epoll fused, retaining the prior failed seed). The standard harness's
command-coverage report and explicit fused `sort` exclusion remain in the logs.
[Machine-readable proof summary](docs/compat2/proof-summary.json).

### Frozen arms and identity

| Arm | Path within this worktree | SHA-256 |
|---|---|---|
| PRE (`bce4eb0aa`) | `build/compat2/pre-source/build/tomokv` | `cedd6d07c8a274b71fe76fc4ef28f2bbfb0381e1ad8705a1bb880cb8290ee607` |
| POST | `build/compat2/tomokv-post` (identical to `build/tomokv`) | `b8a21b0f8e880877b46a71b27e89a86ee5071c766da459417d773ba8a52c0596` |
| PAD-A | `build/compat2/tomokv-pad-a` | `5c830403b32304512fe6b72ecf8d5d47e4e5f506cd7e294101798acc78b94ac1` |

All three identity tools completed and reported differences (exit 1), as
expected for these behavior changes. The full object audit reports 380 changed
bodies among 16,701 inventoried bodies, including 35 command handlers and 70 hot
bodies. The additional-object inventory contributes 14 new emitted bodies:
**394 changed/new bodies**, each named with its reason in
[body-reasons.md](docs/compat2/identity-complete/body-reasons.md), with the exact
mangled symbol and object in [JSON](docs/compat2/identity-complete/body-reasons.json).
Unedited source bodies affected by compiler code generation are explicitly
identified; their individual compiler decision was not isolated.

PRE `.text` is 7,730,449 bytes; POST is 7,724,374 bytes (−6,075). PAD-A changes
58 bytes in POST's `.text`; every section header and symbol address/size remains
identical, and every other section is byte-identical. See
[layout proof](docs/compat2/pad-layout-complete.json) and
[checked patches](docs/compat2/pad-a-complete.json). All eight layout locks compile
unchanged. These are identity observations, not performance results.

### Adjacent finding and proof corrections

**Existing epoll INFO failure (NT-new-1 / NT-new-1b, ntfix pending landing).**
The standard epoll `infofix` suite fails its `instantaneous_input_kbps > 0`
property; input/output byte totals and rates stay zero after real traffic.
Frozen PRE and POST reproduce this in both modes with atomic 0/1: all eight
epoll controls fail at the same property; all eight matching io_uring controls
pass. The standard failures are retained, not relabeled green.
This lane does not include the separate ntfix accounting patch.
Receipts: [PRE/POST controls](docs/compat2/infofix-control/results.json),
`docs/compat2/differ-complete/epoll-*/infofix-*.txt`.

**OPEN: ordinary expiry/keymiss delivery order.** With active expiry disabled,
one ordinary expired GET may deliver `keymiss` before `expired`. PRE reproduced
this in all four geometries (reversed in 19/24 fused-epoll, 6/24 fused-uring,
6/24 split-epoll, 24/24 split-uring trials); POST also reproduces it. Redis 7.4.10
delivered `expired` first in 24/24 trials. `notify_flat_emit` routes `Expired`
through the keyless queue and `Keymiss` through the command's notification batch,
which explains the independent delivery paths. This existing compatibility
concern is not fixed by C2. Receipts: [notification-order](docs/compat2/notification-order/results.json).

The first final C2 run had exactly this failure in its positive control
(`post-expire_notify-2s-epoll`); its held-version assertions passed. The final row
uses separate `Ex` and `Em` positive controls with exact event/count assertions,
and still requires zero notifications and a flat emitted counter during the held
foreign candidate. The reservation-only unit separately verifies the store's
`Expired`-then-`Keymiss` emission order. Final C2 receipts are in `expiry-complete`.

The initial final KeyUpdate-unit invocation omitted its required certificate
directory and case name, so it returned its usage error. The 24 live TLS checks
completed successfully; the corrected five serverless cases have separate
`tls-units-complete` receipts. No assertion or timeout was relaxed.

Port audit found that the existing nested persistence fixture still bound its
socket-only listener to port 0 (an OS-selected ephemeral port) in the earlier
self-test runs. It now honors the same `GATE_TEST_PORT=26899` override as the outer fixture.
Those short-lived listeners had already closed. The final self-test rerun passes
66/66 plus 14/14 nested checks in 318.978 seconds, with both fixtures constrained
to the assigned port range; no assertion or deadline was changed.

### Maintainer merit request

Run the **generic 14 cells**, verbatim in `docs/compat2/merit-cells.txt`, with the
gate's instrument, 8 server cores / 16 shards, matched offered load, and a
contemporaneous same-binary null. Retain the instrument's `--databases 1` paper
geometry. Compare PRE/POST, PRE/PAD-A, and POST/PAD-A for
any cell that moves. Rate decides throughput cells; the instrument's latency
score decides depth-one cells. Record cycles/op, instructions/op, IPC, p99 and
p99.9, and apply the gate's existing acceptance rules. No throughput claim is made.

**PAD kind (A), behavior twin:** `tools/compat2_pad.py` restores the corrected PRE
behaviors by checked ELF patches while retaining POST's exact section sizes,
symbol addresses and code layout. It disables the arity helper, restores the
old denial spelling and QUIT bound, bypasses the versioned-expiry guard, and
defers TLS release to the existing reclamation call. The PAD unit must retain
PRE's deterministic TLS failure. There is no PAD-B arm.

Identity is a proxy, not a merit verdict. The three identity tools run against
the frozen PRE object tree; every changed/new emitted body is listed with its
reason in the final identity inventory. Compiler changes in otherwise untouched
functions remain part of the requested merit comparison.

**NOT RUN:** the full gate/iteration, performance benchmarks, measurement load
generators, and merit cells are maintainer-owned. Correctness runs are authorized
and executed in this lane. The standard harness excludes the `sort` suite in
fused geometry because that suite requires split 6:2; it runs in both split-engine
matrices. No new row skips an unobserved window.


## compat2b

Integration starts from `c72768985` and merges `origin/cpp` at `8656f9fa9`
with merge commit `640a11b42`. Git reports no textual conflicts. Both lanes'
production changes and all seven combined rows remain. No EXPECT constant is
edited. Validation and compile-only derivation receipts follow under
`docs/compat2b`; this section will be completed with final outcomes.

### Redis 7.4.10 precedence after composition

Anchors below refer to `/home/user/Projects/redis/src` (the local source oracle).
Order is by stage, not by an error ranking independent of socket-read boundaries.

| Stage | First applicable result | Redis anchor |
|---|---|---|
| Successful socket read, before parsing that read | Queued MULTI argument bytes plus remaining query buffer strictly above configured limit, or above 1 MiB while unauthenticated: close without a protocol reply. Equality is legal. Previously consumed headers/arguments are excluded; new bytes are still counted. | `networking.c:2759–2778`; previous-pass trim `2659–2662` |
| RESP array header | Invalid integer/signed overflow or count above INT_MAX gives invalid multibulk length; otherwise count above 10 while unauthenticated gives unauthenticated multibulk length. | `networking.c:2337–2345` |
| Each RESP bulk header | Invalid integer/negative length/configured bulk ceiling gives invalid bulk length; otherwise length above 16384 while unauthenticated gives unauthenticated bulk length. These errors close after the reply. | `networking.c:2388–2397` |
| Fully parsed command | Unknown command or unknown advertised subcommand before arity and AUTH. | `server.c:3806`, `3919–3922` |
| Known command/subcommand | Advertised arity error before AUTH (EXEC preserves EXECABORT prefix). | `server.c:3838`, `3923–3926` |
| Protected command policy | Redis checks protected DEBUG/MODULE policy after arity, before AUTH. The oracle differential explicitly enables DEBUG on both servers. | `server.c:3929–3941` |
| Valid advertised arity | NOAUTH unless the command permits unauthenticated use; ACL checks follow. | `server.c:3963–3990` |
| Authorized handler | Handler grammar, such as PING's optional-argument maximum, follows authentication. Ten-argument PING therefore returns NOAUTH before AUTH; an array of eleven args instead fails at the parser. | `server.c:3963` and subsequent command execution |

The merged ordinary/R7 parser applies N3 only on its parse-error exit; C1 runs
only after successful parsing. N4's conservative common-path bound and cold
frontier refinement remain intact. The gate harness honors the existing oracle
CPU override and uses all selected CPUs for single-slot prerequisite builds.
