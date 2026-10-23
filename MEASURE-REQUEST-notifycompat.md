## notifycompat

Branch `cx-notifycompat`, PRE `ef5204b2e`. Eight requested items have implementation
commits. The final directed POST run passes all eight rows in all 108 declared legs
(1320 scenarios); PRE rejects all eight in every leg. Broader proof is still
running; the final receipt index below will be updated before handoff. No push, throughput claim, benchmark, ABBA run, NIC
measurement, or full gate iteration is part of this lane's execution.

Builds and correctness processes are pinned to CPUs 48–63. Gate servers use
48–55 and clients 56–63; the independent POST differential queue reverses those
two eight-core sets. Directed boots use 16 shards, split 6 io + 2 ex or eight fused
threads; historical jobs retain their own declared geometries. Server/oracle/battery listener ports are configured within 32800–32899. Redis oracle:
`/home/user/Projects/redis74/src/redis-server`, version 7.4.10; reference source:
`/home/user/Projects/redis/src`. The requested external trackfix report path was
absent; the same REDIRECT finding was read in this worktree's existing
`MEASURE-REQUEST-trackfix.md` (trackfix2 section).

### Changes and exact oracle outcomes

`tests/notifycompat.py` records every command, reply, decoded frame, and raw RESP
bytes. Lists are compared in arrival order, never sorted. With `KEAm`, each event
below means the keyspace `pmessage` first and the keyevent `pmessage` second.
Both use their actual DB number. A subscriber PING barrier and quiet interval
reject extra events; absence is an assertion. Oracle logs precede the fixes.

| Item / first commit | Exact event result and directed controls |
| --- | --- |
| CD4.8 / `6a8658605` | Unchanged raw and integer SETBIT: silence, dirty delta 0. Changed bit, growth with zero, and new zero bit: one `setbit` each, dirty delta 3 total. The raw fixture is 4096 bytes and both encodings are asserted. Integer materialization remains permitted. |
| CD4.22 / `9469b0388` | SET EXAT/PXAT 1, absent or live destination: `set, expire`; subsequent lazy GET: `expired, keymiss`. With active expiry enabled: `set, expire, expired`. NX/XX controls retain their reply/event behavior. GETEX PXAT 1 already matches Redis: the old value is returned and `del` is emitted. **GETEX defect NOT REPRODUCED**, retained as a control in all 12 geometries. |
| CC4.20 / `09f6b9ecc` | Empty BITOP and set-algebra STORE: source `keymiss` events in Redis lookup order; absent destination has no `del`, live destination adds one trailing `del`. Local and cross-owner routes, atomic 0/1; a 300-source BITOP control crosses the old fixed destination-order band. |
| NO-A1 / `6cf687ea5` | Missing SET GET / GETSET: `keymiss, set`; GETDEL / GETEX: `keymiss`. Expired input adds preceding `expired`. SET XX GET still emits its read miss; ordinary SET does not. |
| NO-A2 / `b78f7653b` | OBJECT ENCODING, REFCOUNT, IDLETIME and FREQ: no missing-key event. Lazy expiry emits only `expired`. Missing keys return null before LFU/LRU policy errors. All four use a no-touch, non-notifying lookup. |
| NO-A7 / `dcb954dfe` | An empty STORE removes an elapsed resident with `del`, not `expired`, and expired_keys does not increase. Eleven STORE forms, local/cross-owner routes, and absent-destination controls. MEMORY USAGE proves the elapsed destination is still physically resident before the command. |
| SO4.1 / `67e9ee971` | FLUSHDB and FLUSHALL: no per-key event, expired_keys increment, or per-key AOF DEL/UNLINK (Tomo DEL/GDEL). Covers databases=1 and 16, DB 0 and DB 1 where available. AOF is enabled at boot, always-fsync; raw record receipts are retained. |
| TRK-REDIR-1 / `2550ad91b` | Failed REDIRECT delivery marks `[on, broken_redirect]`. RESP3 emits exactly `>2\r\n$21\r\ntracking-redir-broken\r\n:<target-id>\r\n`; RESP2 emits no push. OFF/ON before the failed-delivery acknowledgment leaves `[on]` and no push. |

Oracle receipts: `docs/notifycompat/oracle-{setbit-raw4096,setpast,
setpast-active,emptystore,wide-store,writemiss,objectmiss,expiredstore,flush,
redirect,legacy}.log`. Each log includes exact inputs and wire bytes.

Followup `bb8ccf8b2` adds an armed-only causal fence for an already-elapsed SET:
active expiry can reap normally, but its keyless publication waits for the SET
notification chain's final delivery acknowledgment. It neither postpones data
expiry nor stalls readers/writers. The pending state belongs to the shard and
moves with it. Followup `d0382418f` retains source keymiss when the atomic MVCC
probe encounters absence/tombstones. `4d654cff5` places STORE mutation events
after the actual argument count, repairs the FLUSH AOF launch, and preserves
both historical notification atomic legs even when PRE rejects the first.

The clean, unobserved SET specialization remains PRE-identical, including its
existing elapsed-deadline shortcut. The notification/save-observer specialization
installs the elapsed value. This lane does not claim a new equivalence result for
unobserved SET's physical resident/expiry accounting.

Tracking uses a failure acknowledgment routed to the source connection's current
owner, with a tracking-configuration generation to reject obsolete acknowledgments.
The generation is appended to allocated ClimonConn state; it introduces no new
locked Client/Op/ThreadCtx/Shard field. No foreign Client pointer is retained.
`tests/tracking_redirect.py` and `tools/notifycompat_schedule.py` hold a real
cross-IO TrackingDeliver in a disposable binary, close its target, and replay the
original event through the production handler. Atomic-renamed held/replayed
receipts prove this window. Re-arming uses fresh connections/keys, at most 64
attempts; failure to open the window fails. Redis has no cross-IO queue, so its
oracle projection closes the target before attempting delivery. Both endpoints
compare exact RESP2/3 results, using each endpoint's own target ID.

### Gate rows and proof

Eight new rows are collected by `notifycompat` (seven) and `tracking_redirect`
(one), at `tests/gate.sh:5018` and `:5019`, before the quick exit at `:5087`. **DQ=+8, DF=+8; proposed counts 747 quick /
764 full**, from 739/756. `EXPECT_QUICK` and `EXPECT_FULL` are unchanged.
The label fixture's multiset is exactly the source's 764 labels. Its protected
count guard consequently refuses EXPECT_FULL=756, as recorded in
`docs/notifycompat/label-fixture.json`; this is not presented as a green receipt.

Every new row declares epoll/uring × atomic 0/1 × (1s read-local 0, 1s read-local 1,
2s read-local 0): 12 legs. FLUSH adds databases=1/16: 24 legs. The full directed
product is 108 legs, including 48 scheduled tracking scenarios. PRE, POST and
PAD-A use the actual `tests/gate.sh` job interface. No custom acceptance driver
substitutes for a gate job. `docs/notifycompat/proof.py` records exact commands,
source hashes, candidate SHA, ledger, boot logs, oracle bytes and hook receipts.
It freezes a content-addressed binary before booting. Its `full` argument selects
the standard correctness definitions; `GATE_ONLY_JOBS` explicitly excludes full
iteration, EXPECT tally, performance, NIC and ABBA phases.

PRE directed receipt `pre-r3-directed` rejects all eight rows; the coverage audit
confirms all 108 legs and 1320 scenarios, with a semantic wire/reply mismatch
in every notification leg and all four tracking subcases attempted per leg.
POST `post-r3-directed` passes the same 108 legs and 1320 scenarios, verified
against oracle wire bytes by `audit-directed.py`; both `.coverage.json` files
are retained. Final broader gate receipt index: **PENDING**. During broader runs, Linux
automatically selected even listener ports as client source ports. Captured
TIME_WAIT sockets included 32800→32840 and 32800→another lane's 30800; subsequent
boots failed EADDRINUSE. Noninteractive sudo cannot reserve the range, and
unprivileged network namespaces are disabled. The affected whole jobs are
rerun on odd bases, with port-band locks preventing our own runner overlap.
Odd bases alone did not protect the oracle's adjacent even port. Subsequent
runs hold three SO_REUSEADDR sockets bound without listening. This prevents
automatic ephemeral allocation between boots while allowing both servers' real
listeners; it neither accepts traffic nor joins the REUSEPORT listener group.
The eight-listener probe is in `port-guard-probe.json`. No host setting changed.
`proof-superseded.json` retains the replacement map; no failed boot is counted
as semantic proof. The post fused/uring notification rerun is already green. Standard differential seeds run through
`differ-split-0`, `differ-split-1`, `differ-armed-0`, `differ-armed-1` and
`differ-equivalence`, for epoll and uring, without a reduced suite/seed override.
The affected historical job selections include notify_order, notify_aof,
trackfix_order, trackfix_accounting, notify, all four split/armed feature jobs,
AOF epoll/uring, aof_frame, aoforder, climonfix, racefix_climon, clientfix,
atomic_units, netcmd_units, compat2/3, hexpread, ntnew4_live and readonly.
`event-sequence-search.txt` and `event-proof-map-search.txt` retain the tests grep.
The feature jobs include tracking, climon/climon2, hash TTL, pushtear, scriptsurf,
edgeproto/edgetime and other command batteries. Notification batteries also run
through supplemental fused/engine wrappers, preserving their gate job body.

The changed historical assertions are limited to Redis-backed behavior:
`tests/notify.py` expects `expire` for the generic-mask past SET, and silence for
six empty stores whose destination never existed; `tests/flushfix_unit.cc`
expects no expiry side effects from FLUSH. The legacy oracle commands and bytes
are in `docs/notifycompat/legacy_oracle.py` and `oracle-legacy.log`. PRE production
units are compiled from archived PRE sources/Makefile plus the current test files
in `build/notifycompat-pre-proof`; their gate jobs do not substitute POST units.

Early failures remain as evidence, superseded by the final receipts: a missing
armed-string source dependency; an 80-byte value that was embstr rather than raw;
a duplicate source/destination in key selection; active expiry overtaking SET's
chain; missing atomic source misses; AOF enabled too late or attached to the wrong
launch; and a partially written scheduled receipt. These led to code/harness
repairs, not tolerance changes. The first supplemental epoll feature run also
exposed a wrapper grammar error: prepending an engine option moved the config
file out of argv[1]. The corrected wrapper preserves that position, and the
whole feature jobs are rerun. Early `gates_test.py` runs are also retained;
the first was stopped after an ephemeral-port configuration was noticed, and a
port-bound run had two scheduler timeouts during builds. Final run with builds finished and `GATE_TEST_PORT=32891`: PASS, exit 0
(`gates-test-final.log` and `.rc`). The initial unbound-port attempt is an
explicit exception to the intended port restriction, not hidden by this rerun.

### Build and identity

`make all` completed. Every target from `job_production_units`, including its
mdbqsbr live arms, is inventoried in `production-targets.json`; final build and
`make -q` receipts are in `production-final.json`: build exit 0 and all 44 checks
(`all`, 42 file targets, and the recursive mdbqsbr target) returned 0. Required layout assertions remain enabled.

The source-accurate xshard IPA growth is +2531/+2526 instructions by namespace.
Bounded compile-only trials select budgets 144904/143890. The classifier and
numeric observer avoid adding callers to hot parser helpers. All selected clean
GET/SET bodies are identical. **The broader GET/SET/MGET/MSET routing audit is
not fully identical: 58/67 bodies match.** Shared xshard_execute and its cold/
scan helpers change, and DB0 xshard_prepare still differs (18724→18665 bytes;
cold 578→558). The normal-namespace prepare and the local MGET routing helpers
match. `identity-selected.json` names every difference. The full ccfix inventory
has 18,206 bodies, 17,549 identical, 657 changed; 1296/1322 classified hot bodies
match. Both identity tools return their expected nonzero mismatch verdicts.
These are explicit merit risks, not performance conclusions or reasons to skip
correctness proof. Per-commit diagnostics and all budget trials are retained.

### Frozen merit arms

| Arm | Binary | SHA-256 | .text bytes |
| --- | --- | --- | ---: |
| PRE | `build/tomokv-pre` | `a1953bcbd75e9dd5f468ea2340c5f26fb855864148cd5efd1fac806751bff54e` | 8124983 |
| POST | `build/tomokv` | `76f313519a120bf5b65efe74338ce0ba142dc5a4f441590fc1e995c61b308b59` | 8132311 |
| PAD-A | `build/tomokv-pad-a` | `638ecff86821cb4d84916382ae0f6baac9fe78e4b41e1fa660130196e81b94af` | 8132311 |

**PAD kind A: behavior twin.** Every captured PRE object is reused verbatim. The
original link is first reproduced with exactly the PRE SHA. One unreachable
ENDBR64/RET/NOP function appends 7328 bytes to match POST's total .text size;
all existing PRE text function addresses/sizes are unchanged and the GNU IBT
property note is preserved. `tools/notifycompat_pad.py` and `pad-a.json` retain the
commands, input hashes and structural checks. This is a total-text-size control;
**it does not reproduce POST's per-function placement or inlining decisions**.
Earlier compact-cold-unit/PAD-B exploratory artifacts were superseded; final
PAD-A uses no cold recompilation. Its directed negative proof (`pad-a-directed.coverage.json`) rejects all eight
rows in all 108 legs and 1320 scenarios, matching the PRE negative control.

### Maintainer merit request

Run the gate's own quiet-box instrument on the frozen PRE/POST and PRE/PAD-A arms,
using `docs/notifycompat/merit-cells.txt`: the generic 14 cells plus notify_exm.
The actual abbagate parser accepts all 15 cells (`merit-cells-parsed.json`). Use
matched placements, offered loads, repetitions and ABBA order; record rate,
cycles/op, instructions/op and IPC per cell, with the depth-1 latency verdicts.
The verdict is measured rate/latency at matched load. A candidate improvement
should move POST while PAD-A stays flat; PAD's placement limitation remains part
of the interpretation. Any main-command regression must be resolved before merge.
The notify_exm cell arms `--notify-keyspace-events Exm`; it has no subscriber or
controlled expiry/miss workload, so it cannot establish a delivery-throughput
claim. Append measured results to this worktree; no throughput result is asserted
by this request.

Performance benchmarks/load generators, ABBA measurements, the full iteration
and NIC measurements: **NOT RUN**, reserved for the maintainer. Remaining required
correctness/build items: **PENDING**, to be resolved in the final receipt update.
