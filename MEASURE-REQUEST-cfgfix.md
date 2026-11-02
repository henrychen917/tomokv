## cfgfix

Lane: `cx-cfgfix`, frozen PRE `105c5818cc20e3ede50fbe4849915ef72ee1732e`.
No push. Correctness boots/builds use CPUs 32–47, eight-thread gate server
geometry with 16 shards and 6:2 for split, ports 20100–20199, and `LC_ALL=C`.
The main jobs use server CPUs 32–39. The independent epoll control jobs overlap
the long clock waits on server CPUs 40–47 and ports 20150–20199; client work
uses the opposite eight CPUs. All are correctness jobs, with no rate scoring.
No performance workload or full `iteration` gate was run.

This is a partial compatibility implementation, not a claim of complete Redis
configuration parity. The unresolved requirements are listed below and in the
[212-name inventory](docs/cfgfix/inventory.md), with machine-readable replies in
[the inventory JSON](docs/cfgfix/inventory.json). Of those names/aliases, 80 are
exposed, 61 belong to the excluded cluster/replication/module surface, and 71
remain absent with individual reasons recorded. Existing knobs can also retain
the semantic differences listed below.

### Implemented

- CONFIG SET validates the complete argument list and every value before apply.
  Listener sockets and locale state are prepared before scalar publication.
  A shared per-command verdict reaches every CONFIG fragment and its final reply.
  Port-in-use, bind-address and AOF-open failures retain previous values and
  listeners. Actual address changes, including after FLIP, are oracle checked.
  TCP may not reuse a live TLS port: the new oracle witness failed in all four
  predecessor legs, and the guard rejects that collision before resource preparation.
- CONFIG GET supports multiple patterns, aliases and exact hidden-name queries;
  exact queries retain caller capitalization, with case-insensitive deduplication.
- Runtime port/bind replacement uses the physical listener issuers and preserves
  listener homes transferred by FLIP. CONFIG admission, FLIP, snapshot and LB
  admission share the cold control exclusion; the existing FLIP handover remains.
  TCP rebind preserves terminal UNIX accept completions after a FLIP handover;
  a deterministic 18-case production-filter check is part of knob_matrix’s job.
- Runtime appendonly ON opens an unpublished increment, binds owner-local
  producers and starts the initial rewrite. Its old manifest remains authoritative
  until the replacement base/manifest is durable. OFF drains producers and replies,
  fsyncs/closes on the writer, unbinds producers, and frees channels. Reply sequence
  floors survive OFF/ON. A restart witness covers existing keys, later writes,
  deletion, updates and SWAPDB namespace remapping during an OFF gap.
- Runtime tls-auth-clients changes new TLS admission (yes/optional/no), preserving
  existing sessions. The TLS oracle row covers TLS 1.2/1.3 and client certificates.
- daemonize, logfile, syslog-enabled, syslog-ident, syslog-facility, pidfile,
  supervised, loglevel and hidden key-load-delay have shared boot/runtime metadata.
  Negative key-load-delay values implement Redis’s probabilistic one-microsecond
  sleeps, checked deterministically through the production loader hook.
  Redis immutability and grammar are used; logging, daemon and supervisor actions
  are in the cold process helper. Existing stdout diagnostics are notice and stderr
  diagnostics warning; Redis's exact log-line formatting is not reproduced.
- Full multiword shutdown-on-sigint/sigterm config-file grammar is accepted.
  AKEn keeps the n event bit even though Redis's GET serialization is AKE.
  List growth uses Redis listpack byte boundaries, including negative size -6.

### PRE witnesses and Tcl disposition

PRE directed CONFIG receipts: `docs/cfgfix/pre/`; original gate runs
`build/gate-run.wOuYIB`, `build/gate-run.ULJcof`, `build/gate-run.UvQxjR`.
The focused manifest is `docs/cfgfix/pre-tcl-manifest.json`.

| Requested assertion | PRE | Disposition |
|---|---|---|
| CONFIG sanity | FAIL | Still excluded: it attempts SET on TomoKV-specific boot-only knobs absent from Redis's immutable skip list; HLL/tracking mutability also differs. |
| CONFIG SET rollback on apply error | FAIL | Fixed and promoted. |
| CONFIG SET rollback on set error | FAIL | Still excluded: maxmemory-clients eviction/percent policy is absent. Directed rollback uses implemented knobs. |
| CONFIG SET set immutable | FAIL | Fixed and promoted. |
| CONFIG SET with multiple args | FAIL | Still excluded: upstream uses repl-backlog-size, inside the excluded replication surface. Supported-knob multi-SET is oracle checked. |
| CONFIG GET hidden configs | FAIL | Fixed and promoted. |
| CONFIG GET multiple args | FAIL | Still excluded: upstream requires replicaof/slaveof and maxmemory-clients. Supported multi-pattern/alias queries are oracle checked. |
| MULTI with config error | PASS | Already promoted on PRE; no new assertion claimed. |
| List invalid list-max-listpack-size config | FAIL | Fixed encoding boundary and promoted. |
| stream-cgroups appendonly setup | Immutable error | Activation now succeeds; the next setup option, aof-use-rdb-preamble no, reaches the existing native-format refusal. The exact known setup signature changed; the same 50 assertions remain required. |

The final POST Tcl job passes in both 1s and 2s: each records 39 file
executions and 1,882 passing assertions, with no unexpected manifest errors.
The five raw setup failures per mode match the explicit existing manifest
signatures (two scripting debug controls, two list compression setups, and the
native AOF preamble boundary). The four fixed assertions above are promoted;
no assertion count or tolerance was relaxed. Raw summaries and binary identities
are in `docs/cfgfix/post/`.

The directed CONFIG job matches 79 ordered oracle results in each of its four
1s/2s × epoll/uring legs, including bind replacement and failed-bind rollback.

### Outstanding compatibility requirements

Runtime AOF switches currently refuse an active atomic command, snapshot/rewrite,
FLIP or LB transition. Redis cancels/schedules persistence work; this refusal is
an unresolved semantic difference, chosen to avoid switching owner bindings
through an undecided atomic unit. Runtime bind still accepts one IPv4 address;
Redis address lists, optional addresses and IPv6 are absent. TLS context/certificate
replacement remains boot-only; only tls-auth-clients became mutable.

Apply resources are prepared in locale/listener/AOF order. When several apply
functions would fail, error attribution can differ from Redis argument order;
that simultaneous-failure case is not covered by the directed single-failure
rollback rows. Full INFO persistence text/conditional-field equivalence is also
unproven: the oracle row compares enabled/rewrite state, last statuses and rewrite
count, while native persistence counters and file formats remain.

The inventory names missing process-title, crash-reporting, watchdog, THP,
OOM-score, socket-mark and warning controls; client memory eviction; native
storage/expiry policy differences; protected-config policy and retained boot
persistence paths; HLL/tracking mutability; and the excluded cluster/replication/
module settings. Missing controls are rejected, not accepted as ineffective knobs.
Logfile append/filter behavior, pidfile lifetime and daemon parent/child lifetime
are oracle checked in every cfgfix mode/engine leg. Syslog ident/facility/severity and live filtering are checked against Redis at
the libc boundary. Native filesystem/abstract supervisor notifications are checked
on private sockets. Host syslog delivery and Upstart integration are NOT RUN; no
host services are reconfigured. The supplied Redis oracle lacks libsystemd. Native AOF/snapshot files do not become Redis RDB/RESP files.

### Regression fixture correction

The original maxmemrace oracle leg failed during setup: under allkeys-lru, Redis
may return EVICT_RUNNING and accept SET while incremental eviction continues. All
48 candidate legs passed. The test now waits boundedly for the oracle eviction
cycle to finish before asserting the old limit; candidate setup, reply assertions
and non-vacuous busy windows remain unchanged. This is the exact test-only fix
from integration commit `b4b63b97c3`, including keeper-thread cleanup on failure.

### Verification and artifacts

Serverless command census: **0 added instructions in 48/48 cells**. Forty cells
are identical; eight db0 MGET/non-atomic MSET cells remove one instruction per
command. [PRE/POST table](docs/cfgfix/instructions/table.md) and raw function/site
receipts are checked in. Both modes, both namespaces and batch 1/32 are covered.
No new per-operation config synchronization was introduced.

| Arm | Path | SHA-256 |
|---|---|---|
| PRE | `build/cfgfix/arms/tomokv-PRE` | `97f0d76e3782485ae2e2f797805484ef09eb52752a5019935d1bc409d4fb4fd1` |
| POST | `build/cfgfix/arms/tomokv-POST` | `01813fe2a5534ffcce92bb03992d648c74125e7281949c53dad6b125b69526a3` |
| PAD-A | `build/cfgfix/arms/tomokv-PAD-A` | `ba567335d4633b8d3ab150389864ca1f570eda5e496bf1736547534271de9c94` |

PAD-A starts .text at 0x2cc30 with 8,924,055 bytes, matching POST. PRE .text is 8,896,071 bytes. Full linker receipt: `docs/cfgfix/arms.json`.

Final regression job receipts are pending. The selected matrix is being rerun
on the final binary after the UNIX completion, negative load-delay and TCP/TLS collision corrections. PRE was rebuilt with
only a debug-directory prefix map and reproduces its original SHA-256 exactly. All 57 production targets pass `make -q` after rebuilding the TCP/TLS collision
guard; `docs/cfgfix/freshness-provenance.json` binds the receipt to the final source
and binary. The preceding receipt is archived separately. These final arms are built from source through
`80a7559fda` (later commits change tests/documentation only). `tests/gate.sh` EXPECT constants remain untouched.
One public cfgfix row is collected at `tests/gate.sh:6336`, before the quick-tier
exit at line 6574: DQ=+1, DF=+1.
From PRE 1046/1063, the maintainer should set 1047/1064. Tcl promotions and expanded
existing rows add no public rows. Counts follow collection lines, not job names.

### Not run in this lane

- `flip_saturated`: its gate job launches `memtier_benchmark`; load generators
  remain with the maintainer under this lane’s runtime authorization.
- Full `tests/gate.sh iteration` and the 18 performance cells: maintainer-owned.
- Host syslog delivery and Upstart integration: only isolated libc and private
  supervisor-socket checks ran, as described above.

### Maintainer measurement request

Use [the 18 cells](docs/cfgfix/merit.cells.txt): the unchanged 14 generic cells plus
2s GET/SET at p1 and p32 (`h53 h54 h21 h22`) as null checks. Use the gate's own ABBA
instrument, matched offered load and identical geometry/allocator/keyspace.
Collect contemporaneous PRE/PRE and POST/POST nulls, PRE/POST and PRE/PAD-A.
Retain per-cell cycles/op, IPC, instructions/op, completed rate and the existing
latency score; acceptance is no main-command regression under the gate's current
per-cell rules. Do not average away a failing cell. No throughput claim is made.

PAD-A is type **A, behaviour twin**: PRE behavior linked to POST's total .text
start/size. It controls aggregate text extent only; internal function placement
and data layout remain PRE. It is not an exact symbol-layout twin and cannot
isolate all layout effects. This limitation must accompany any attribution.
