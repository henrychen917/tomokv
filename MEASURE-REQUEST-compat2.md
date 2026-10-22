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
edited. All three compat2 rows pass POST and fail headline through the same
gate job interface. The four standard differential matrices pass **1,882/1,882**.
The final selected-job replay is **40 pass / 1 fail**: its sole failure is the
unmodified receipt entry guard refusing owner-owned EXPECT_FULL=686 against
689 source/fixture rows. Receipts and the final audit are under `docs/compat2b`.

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
| Authorized handler | Handler grammar, such as PING's optional-argument maximum, follows authentication. Ten-argument PING therefore returns NOAUTH before AUTH; an array of eleven args instead fails at the parser. | `server.c:3963–3969`, handler call `4198` |

The merged ordinary/R7 parser applies N3 only on its parse-error exit; C1 runs
only after successful parsing. N4's conservative common-path bound and cold
frontier refinement remain intact. The gate harness honors the existing oracle
CPU override and uses all selected CPUs for single-slot prerequisite builds.

### Compile-only budgets and identity

All 29 pinned translation units were recompiled from the unmodified headline
source; all 29 reproduce every reference body. The initial merged build was
also recompiled for all 29 units. Nearby trials preserve IPA headroom and then
minimize, in order, hot bodies differing from both eligible references, all
remaining differences, and total differences. Established budgets remain when
they achieve the same body score. Exact commands, unit sizes and comparisons
are in `docs/compat2b/trials/`; selections are in `selected.json`.

| Object | 8656f9fa9 budget | Selected budget |
|---|---:|---:|
| `db0/src/cmd/acl.o` | 35324 | 35432 |
| `db0/src/cmd/climon.o` | 26220 | 26279 |
| `db0/src/cmd/t_server.o` | 31787 | 31804 |
| `db0/src/cmd/t_set.o` | 23428 | 23442 |
| `db0/src/cmd/t_zset.o` | 32970 | 32984 |
| `db0/src/cmd/xshard.o` | 126710 | 126778 |
| `db0/src/core/genthread.o` | 130316 | 130343 |
| `db0/src/core/reorder.o` | 148944 | 148983 |
| `src/cmd/acl.o` | 35369 | 35485 |
| `src/cmd/climon.o` | 26145 | 26196 |
| `src/cmd/t_list.o` | 25338 | 25352 |
| `src/cmd/t_zset.o` | 33395 | 33409 |
| `src/cmd/xshard.o` | 128042 | 128118 |
| `src/core/genthread.o` | 130084 | 130113 |
| `src/core/reorder.o` | 147950 | 147991 |

The other pinned budgets remain unchanged. All final production objects for
these 29 units equal their selected trial bodies (`final-equals-selected.json`).
The full merged inventory contains **16,753 bodies: 16,399 equal to headline,
354 changed**. Of **1,218 selected hot bodies**, **1,145 equal headline** and
**33 further bodies equal compat2**, including two copies absent in both merged
POST and compat2. **40 dispatcher bodies match neither reference**: they combine
C1's authenticated-state argument on the cold arity path with ntfix's N3 length
classifier/N4 cold frontier behavior. Strict hot-body identity is therefore
**not achieved**. It remains a merit input and did not stop correctness work.

Every changed body, including the **74 residual bodies** (40 hot, 34 other),
has object, symbol, reference/POST sizes and reason in
`docs/compat2b/identity/changed-bodies.md`; the residual hot list is separate.
Unedited bodies changed by compiler decisions are identified as such, without
claiming to have isolated each optimizer decision. No runtime layout, field,
knob, retry, or lock was added to force identity. The only new production-build
edits after the mechanical merge are the listed Makefile budgets.

One initial round-2 coordinator run accidentally submitted the same reorder
trial twice, racing its temporary IPA dump removal. Its error log is retained.
The coordinator now deduplicates trial jobs; the complete rerun uses all unique
successful receipts. This was a compile-only driver error, not a server run.

### Gate interface and resource allocation

`docs/compat2b/run_gate.py` invokes **the actual `tests/gate.sh quick` job
interface**, with `GATE_ONLY_JOBS`, separate diagnostic histories and PARTIAL
ledgers. It does not call replacement row drivers. The exact command is:

```sh
taskset -c 64-79 env GATE_ONLY_JOBS="<recorded job list>" \
  GATE_DIFFER_ORACLE_CORES=72 GATE_TEST_PORT=26899 \
  REDIS74_ROOT="$PWD/build/compat2b/oracle" \
  bash tests/gate.sh quick --server-cores 64-72 --load-cores 73-79 \
  --server-smt '' --load-smt '' --ports 26800-26899 \
  --candidate-binary "<recorded absolute binary path>"
```

The planner selects one ordinary eight-server-core slot, **64–71**, with
**16 shards / split ratio 6:2**; fused has eight unified threads and read-local
where the row declares it. The ninth selected server core, **72**, is outside
the actual server slot and is reserved for Redis. Clients/coordinator use
**73–79**. Single-slot prerequisite builds use all selected **64–79**, `-j16`.
There is no reduced server geometry, full iteration or performance tier.

The oracle directory contains symlinks to local Redis 7.4.10 source, with its
server/CLI symlinks explicitly targeting `/home/user/Projects/redis74/src`.
This supplies the source metadata checks without substituting the requested
oracle binary. `references.json` records the oracle and source hashes.

Harness changes preserve the explicit oracle affinity instead of overwriting
it; retain both C3 mode-specific deterministic failures independently; let all
15 independent ABBA self-test commands run even after one fails, retaining the
aggregate failure; and honor `GATE_TEST_PORT` in the remaining socket fixtures.
No assertion, timeout, tolerance, EXPECT constant, or row count is relaxed.

PRE uses an archive of **8656f9fa9 production source**, the same merged test
files/gate interface, and the two current compat2 witness targets appended to
its Makefile. Thus its C3 deterministic unit uses PRE headers and objects,
while the POST unit uses POST. Its C1/C2 live tests use the PRE server binary.
This avoids presenting a POST unit as a PRE failure witness.

The unmodified strict tools (`ccfix_audit.py`, `lbstall_artifacts.py compare`,
`linked_bytes.py`) each exit **1**; their exact outputs are retained under
`docs/compat2b/identity`. The full tool counts 340 differences among shared
objects; the complete inventory adds the 14 bodies from the new autharity
objects, for 354 total. Linked `.text` is **7,735,985 → 7,732,822 bytes**
(−3,163), an identity observation only. No new PAD measurement arm is requested;
the maintainer's requested comparison remains merged POST versus 8656f9fa9.

All **26 changed command-handler bodies** equal compat2 exactly; the other
**1,185 of 1,211** handlers equal headline. These counts include object copies.

The scheduler self-test's real shell fixture now initializes `ALL_BUILD_CORES`
from its permitted fixture CPU list. Previously its unused placeholder was CPU
0; the single-slot build-mask preservation makes that value active. This keeps
the existing scheduling/affinity assertions within the caller's allocation.
The fix was made before this run reached `gates_test.py`; no assertion or
deadline changed.

### Directed gate results and TLS coverage

The first POST partial gate executes **129 rows: 127 pass / 2 fail**. All seven
combined compat2/ntfix defect rows pass. The two other failures and their
corrections/replays are documented below; this first ledger is not described as
an all-green run. PRE executes the identical `job_compat2` body and test files
(`pre-post-interface.json` verifies their hashes): one release prerequisite
passes and **all three compat2 rows fail as required**.

| Defect / four mode-engine combinations | 8656f9fa9 PRE | Merged POST |
|---|---|---|
| C1 full command-table differential | 228 differences in each 1,522-comparison leg | **0 differences in all four legs** (6,088 comparisons) |
| C2 held RENAME candidate, three predecessor GETs | Three false expiry events in each leg | **Zero events**; all replies remain `old` |
| C2 MSET TTL-clearing control | Zero events in each leg | Zero events in each leg |
| C3 held reclamation, both modes | `live=0 ktls=1 tls_closed=0 retained=1`, then required failure | `live=0 ktls=0 tls_closed=1 retained=1`, then PASS |
| C3 real TLS1.2 kTLS / TLS1.3 fallback, all four legs | Eventual teardown controls pass | All pass |
| N1 exact epoll/uring byte accounting | Already fixed in headline; no negative claim | All four legs pass |
| N2 silent-peer close-after-reply | Already fixed in headline; no negative claim | All eight mode/engine/transport legs pass |
| N3 pre-AUTH length errors | Already fixed in headline; no negative claim | **23 exact cases × eight legs**, all pass |
| N4 query-buffer frontier | Already fixed in headline; no negative claim | **Four exact cases × eight legs**, plus deterministic frontier unit, all pass |

Actual interface receipts are `docs/compat2b/gate-post/` and `gate-pre/`;
`directed-summary.json` retains each C1 comparison count, C2 witnessed state and
C3 unit output. The C1 inventory still covers 245 registered top-level commands,
with explicit metadata exclusions and authenticated/unauthenticated right/wrong
arity probes. The pinned Redis oracle remains 7.4.10. Per leg, the 1,522
comparisons are 340 unauthenticated right-arity, 340 authenticated right-arity,
433 unauthenticated wrong-arity, 407 authenticated wrong-arity, and two unknown
command probes. Authenticated right-arity probes deliberately use a command-
denied ACL user; wrong-arity probes use the fully authorized default user.
This isolates arity/AUTH/ACL precedence without executing blocking or unstable
administrative handlers. The receipt explicitly lists 24 variadic entries with
no representable invalid advertised arity (their valid boundary is tested),
and `FLIP`, the local extension with no Redis oracle. No missing probe is
silently counted as a successful comparison.

All **20 rows in the actual TLS job pass**. The supplemental batteries also
pass **24/24 live commands** across both modes/engines: required and optional
client certificates, default kTLS, forced userspace fallback, and live KeyUpdate.
All **five unique serverless RX/KeyUpdate cases pass** (also repeated by the
separate `tls-units` invocation). Exact commands and return codes are retained
in `docs/compat2b/tls/results.json` and `tls-units/results.json`.

### Standard differential matrix

The unmodified `tests/differ_gate.sh` runs sequentially on POST for both engines
and both geometries, with both atomic settings and its complete standard seed
inventory. The target uses CPUs 64–71, the pinned Redis oracle uses CPU 72,
and clients use 73–79; ports are 26810/26811. Engine wrappers only prepend
`--net-io epoll` or `--net-io uring` to the frozen POST binary. Exact argv,
environment, return codes and every per-leg comparison log are under
`docs/compat2b/differ`.

| Engine / geometry | Result | Seeds |
|---|---|---|
| io_uring / split | **475 pass / 0 fail** | 7, 19, 20, 23, 21 |
| io_uring / fused with read-local armed | **466 pass / 0 fail** | 7, 19, 20, 23, 22 |
| epoll / split | **475 pass / 0 fail** | 7, 19, 20, 23, 24 |
| epoll / fused with read-local armed | **466 pass / 0 fail** | 7, 19, 20, 23, 25 |

Together these are **1,876 successful Redis-comparison legs**, four positive
read-local witnesses and two successful mode-equivalence matrices: **1,882
pass / 0 fail**. The focused suite totals are **40/40 each** for `infofix`,
`notify`, `hash`, `hexpire` and `edgetime`, covering both engines, both modes,
both atomic settings and all standard seeds. In particular, epoll's formerly
failing INFO differential passes **20/20 legs**. Full suite and seed accounting
is in `final-proof.json`.

The standard fused driver skips SORT because that suite requires split 6:2;
these skips are not passes, and SORT remains exercised in each split matrix.
The standard driver's mode-equivalence display still says “all 32,” but the
current source declares and checks **16 cells** (`mode_equivalence.py:41–42,
179`), and both engine receipts contain **16/16**: 6,137 byte-identical replies
per io_uring cell and 6,154 per epoll cell. This report uses the executed
inventory, not the stale label.

### Initial failures retained and final replay outcomes

- `storesize published monitoring` still expected the historical
  `-ERR unknown DBSIZE option` for `DBSIZE bad`. C1 intentionally follows Redis's
  advertised arity. The passing C1 oracle receipts show the exact wrong-arity
  reply in both authentication states. `storesize_unit.cc` now requires that
  exact reply; the existing `DBSIZE NOW` / `now` extension assertions remain.
  No production change was needed. The owning `atomic_units` job now passes
  **27/27 rows**, including the corrected assertion, through the same interface.
- The initial `gates_test.py` run reports **67 tests / 29 subtest failures**:
  its helper-invocation assertions still required short-circuiting after the
  first failure. They now require **all 15 helpers**, while preserving every
  assertion that any nonzero helper result makes the row fail. All **five
  focused LedgerWiring tests pass**; the whole suite now passes **67/67** in
  the actual `abba_selftest` replay. Its nested 14-test scheduler suite also
  passes. The scheduler fixture uses its permitted CPU mask, as described above.
- The initial history self-test reports **55 tests / three failures** because
  its isolated real-job fixture lacks `GATE_SLOTS` and `ALL_BUILD_CORES`, now
  read by the single-slot build-mask preservation. The fixture now declares
  one slot and uses its permitted fixture CPU for builds. Timeout, partial-ledger,
  child-reaping and inherited-finalizer assertions remain unchanged. The full
  history suite now passes **55/55** in the actual `abba_selftest` job replay.
- The initial ABBA self-test has one `KeyError: statistical_verdict` in its
  favorable-null mutation case. A scheduler-fixture source edit occurred during
  that test, whose real driver refuses a changed harness before publishing
  `statistical_verdict`. This is consistent with the change guard, not evidence
  of a server defect. The **unchanged focused test passes** with frozen sources
  (one test, 96.327 seconds); no comparator assertion or instrument behavior was
  changed to obtain that result. The complete frozen-source job replay now
  passes **121/121**, superseding the initial failure.
- The first attempt to queue that replay used a leading-hyphen label as a
  separate argparse value and exited 2 before the gate started. That usage error
  is retained at `docs/compat2b/differ/gate-final.log`. The corrected command uses
  `--label=-final` and completed after the standard matrices, with all twelve
  parser regression jobs and `atomic_units` in the same selected-job interface.
- The receipt self-test refuses **EXPECT_FULL=686 versus source/fixture=689**,
  with **zero missing and zero extra fixture labels**. The counts are owner-owned;
  this refusal is retained, not bypassed. Its internal receipt-control suite
  is **NOT RUN** because that entry guard refuses the current EXPECT value.
  All other independent helper commands completed; their test summaries pass
  and the aggregate row correctly stays failed.

### Final replay, build freshness and artifacts

The final run, `docs/compat2b/gate-post-final/`, executes the actual selected-job
interface with **40 pass / 1 fail**: one release row, **27 atomic-unit rows**,
and **12 parser rows** pass; the ABBA helper row fails only on the receipt-count
refusal above. The parser rows cover fragment, bounded CPU work and neighbour
progress for every **1s/2s × epoll/uring** combination. All 15 independent ABBA
helper commands are present. The completed unit-test summaries have no failures;
raw logs retain both the expected receipt refusal and the successful summaries.
The earlier failing ledgers are retained alongside this final replay.

`make -k -j16 all` plus **every one of the 35 `job_production_units` targets**
succeeds. Both concrete MDBQSBR witness arms also build successfully. All
**38 `make -q` freshness checks** return zero: `all`, the 35 targets and both
concrete arms with their original flags. `production/results.json` records all
40 commands and their zero return codes. Shell syntax, 12 Python AST checks and
`git diff --check` for the production/harness source changes also pass.

The final audit rehashes POST, the frozen compat2 reference, headline, the Redis
oracle and both Redis source-anchor files. Every reference still matches its
original receipt. POST is unchanged by the unit rebuilds:

| Arm | Binary | SHA-256 |
|---|---|---|
| Merged POST | `build/tomokv` | `d611f49909f254fa94e9096283c5ec4921593e8de24b549453e884c0a8a5b8c0` |
| 8656f9fa9 | `build/compat2b/headline-src/build/tomokv` | `91ae41fd2fda0738a02ee0eed50021d772985654b19f55d1296812aaafaa6426` |

`final-proof.json` records the gate ledgers, standard matrices, helper summaries,
build freshness, final source/fixture inventory and hashes. Resource snapshots
in `resource-observations.json` confirm server threads on 64–71, Redis on 72
and clients on 73–79. The final cleanup check finds **no listeners on
26800–26899 and no remaining owned correctness-server processes**.

**NOT RUN:** the receipt-control suite behind the refusing entry guard; the
20 fused SORT legs that the unchanged standard driver excludes because they
require split 6:2 (all 20 split SORT legs pass); a Redis comparison for the
local-only `FLIP` extension; and performance/null measurements and the full
landing/iteration gate reserved for the maintainer. The 24 variadic entries
without a representable invalid advertised arity are explicitly recorded by
C1, rather than fabricated as successful wrong-arity probes.

### Required counts and landing comparison

`collect_job compat2` is at **tests/gate.sh:3981**, before the quick-tier exit
at **4093–4097**. Its three labels each occur once: `compat2 autharity`,
`compat2 expire_notify`, and `compat2 ktls_lifetime`. Therefore **DQ=+3, DF=+3**:

| Tier | Headline count | compat2 addition | Required count |
|---|---:|---:|---:|
| quick | 669 | 3 | **672** |
| full | 686 | 3 | **689** |

N1 is still collected at line **3954**; the TLS job containing N2/N3/N4 is
collected at **4043**, also before the quick exit. Their four rows are already
included in headline's 669/686, so they are not added twice. The source-only
label inventory finds **672 quick / 689 full**, and the full fixture has all
689 labels with **zero missing and zero extra occurrences** (`ledger.json`).
`EXPECT_QUICK=669` and `EXPECT_FULL=686` remain byte-identical to headline at
lines **336–337**. The maintainer must update them to 672/689 before the receipt
self-test can complete; no passing full-gate receipt is claimed here.

The maintainer's pending work is the requested **null comparison of merged POST
against 8656f9fa9**, using the gate's own instrument, followed by the landing
gate. Use the full current `tests/headline_cells.txt` inventory and the two
binary arms/hashes listed above, with the instrument's existing geometry,
matched offered load, and same-binary null control. The gate's existing per-cell
acceptance rules decide: rate for throughput cells and its latency score for
depth-one cells; retain cycles/op, instructions/op and IPC to explain any change.
This compat2b request supersedes the older-base arm paths in the compat2 section;
its previously measured merit and PAD artifacts are historical evidence only.
The lane ran correctness only. No throughput, latency, cycles/op or merit
claim is made from compile identity or correctness results. No performance
benchmark, measurement load generator, full `iteration`, push or merge into
`cpp` was run by this lane.
