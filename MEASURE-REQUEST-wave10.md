# Wave 10 landing request

## wave10 integration

Integrated on `cx-wave10` in `/home/user/Projects/cx-wave10`, from headline
`393d6ceb129d8c99dffd70959d6a19267c525fe0`. No push. Production integration and
instruction proofs are complete; the remaining correctness campaign is still
running. This report will receive its final verification inventory before delivery.
No throughput claim is made.

All builds and correctness work use CPUs 64–95; servers use ports 20000–20099.
Direct builds use `taskset -c 64-95 make -j32`. Gate workers use their own assigned
CPU subsets and job interfaces. The main correctness geometry remains eight
server threads, 16 shards, split ratio 6:2; jobs that declare another geometry
retain it. Correctness servers, Redis 7.4, Tcl and differential jobs were run under
the explicit lane authorization. Performance and full gate iteration remain with
the maintainer.

### Merges and exact row arithmetic

Each branch was merged, in the requested order, with a `--no-ff` merge commit.
The lane branches were not edited. The blockfix3 report is the `## blockfix3`
section of [MEASURE-REQUEST-blockfix2.md](MEASURE-REQUEST-blockfix2.md); the separately
named blockfix3 report does not exist on that branch.

| Lane | Merge | Added quick/full rows | Collector line(s) |
|---|---|---:|---|
| snapfix2, including snapfix | `f146fdbca` | 4/4 | 6181, 6182, 6183, 6185 |
| blockfix3 | `047ccf869` | 1/1 | 6083 |
| scriptfix2 | `8fe881fa2` | 48/48 | 6152 |
| exec1s-d, including exec1s-c | `30a83e4d7` | 4/4 | 6143 |
| pubtrackfix | `87e964b71` | 4/4 | 6189 |
| infofix, excluding global slowlog | `d47af69b2` | 4/4 | 6124, 6125 |
| rlfix4, merged last | `d53549aa4` | 0/0 | — |
| Total | | **65/65** | |

The landing counts are **946 quick / 963 full**, from 881/898. Every added
collector is before the quick-tier exit at **line 6263**. Blockfix3 adds zero
relative to its lane base but restores the headline's one parked stream-removal
row. Infofix contributes four instead of five because its global-ring row is
excluded. The EXEC and pubtrack lanes each omitted their four declared labels
from the fixture; all eight are now listed. Interaction checks extend existing
rows. The complete declaration multiset, including duplicates, exactly equals
the fixture. See [row-inventory.json](docs/wave10/row-inventory.json) and its
source-line counter [inventory.py](docs/wave10/inventory.py).

**The real EXPECT_QUICK/EXPECT_FULL assignments remain 881/898.** Only the
explicitly authorized throwaway selftest copy uses 946/963.

LAT-HIST-2 is included under the owner's 2026-10-29 ruling. Individual command
timers remain exact; no outlier averaging was added. Commit `e98831c81` removes
only the global slowlog-ring portion of `7c50db206`; `src/cmd/slowlog.cc` is
byte-for-byte headline. Its formatter/global synchronization could obstruct a
GET behind another owner's SET, so it is not part of this landing. The omitted
public row is `infofix_compat-slowlog`. These seven Tcl names return to their
headline skips and reasons:

- `SLOWLOG - GET optional argument to limit output len works`
- `SLOWLOG - can clean older entries`
- `SLOWLOG - commands with too many arguments are trimmed`
- `SLOWLOG - get all slow logs`
- `SLOWLOG - logged entry sanity check`
- `SLOWLOG - max entries is correctly handled`
- `SLOWLOG - too long arguments are trimmed`

climonfix4, flushfix2, execfifo and lineshare-a/b are not merged.

### Semantic interactions and directed checks

1. **Prepared tables, sparse EXEC versions and X2.** Snapshot preparation retains
   at least the old capacity, using `max(old, 2*min(live, old))`. X2 reads its
   commit cutoff before the reader floor and refuses collapse during capture.
   New `exec1s` subcases run 64 two-INCR transactions, pin their actual pending
   versions, and cut a snapshot while eager cleanup operates. Both modes,
   atomic 0/1, prepared/capturing stages, and ordinary/armed-read-local retirement
   are covered. They require a real capture, exact values and actual reclamation.
2. **Eviction and snapshots/pins.** The same cases require zero eviction while
   versions are pinned and during active capture, complete the snapshot stream,
   then require exactly two evictions after pins/capture end. This checks the
   pubtrack maintenance path against both snapshot sizing and X2 retirement.
3. **Shutdown, EXEC retirement and escalated scripts.** The merge retains
   wave 9's stronger at412 APPLY witness and its existing owner-side
   `xshard_complete_script_final` close. Snapfix's redundant close is omitted;
   each Final closes once. Shutdown releases abandoned PIN ownership before
   records can retire. Complete snapfix, snapshot, shutdown, at412 T11a/T11b,
   EXEC and AOF jobs retain their declared legs and exact-data checks.
4. **Scripting with escalation, handoff and wound publication.** scriptfix2's
   invocation environment stays inside each optimistic attempt; at412c's claims,
   handoff and wound machinery remain intact. [tests/wave10.py](tests/wave10.py),
   attached to all eight execfair mode/engine/atomic legs, forces nine conflicts
   for shebang EVAL, uppercase EVALSHA and uppercase FCALL with numeric child
   arguments. It requires eight retries, one escalation, an APPLY writer wait,
   exact replies and balanced pins. The existing owner/wound witnesses remain.
5. **NOGROUP accounting.** Blockfix3 increments its dedicated error counter at
   the actual XREADGROUP error reply. INFO reads that counter and RESETSTAT's
   baseline. Infofix adds no generic formatter accounting hook; there is no
   second error-accounting path.
6. **LAT-HIST-2 with EXEC retirement.** The exact batched histogram implementation
   is retained. The existing wave8b disabled-timing witness and latency jobs check
   the unarmed path; the serverless EXEC scopes show no integration-only additions.
7. **rlfix4 with X2 readers.** Armed collapse still selects
   `atomic_free_entry_read_local` and QSBR retirement. rlfix4 changes admission
   and hashing, not that selection. The complete exec1s job includes the
   concurrent word/byte-wrap reader TSan falsifier; new snapshot subcases require
   deferred retirement. No reader retry or seqlock is introduced.
8. **Central CR/LF replies — real interaction repaired.** scriptfix2 sanitized
   FUNCTION LOAD's unknown-option argument before crlffix could trim its trailing
   CR/LF. The existing job rejected 32 exact comparisons. Commit `5e57bbdfd`
   passes the raw length-bearing argument to the central builder. The complete
   job passes after repair, including following PING/ECHO framing. Two Lua
   error/status API checks extend that job. All 16 new/moved sites are recorded
   in [the CR/LF audit](docs/crlffix/audit.md) and
   [wave10-added-sites.json](docs/crlffix/wave10-added-sites.json).
9. **Tcl promotion union.** The reconciled manifest removes 87 headline skips and
   introduces none; the seven exclusions above remain. XGROUP DESTROY's NOGROUP
   assertion is promoted. JSON remains `indent=1, ensure_ascii=True`.
   [tcl-manifest-union.json](docs/wave10/tcl-manifest-union.json) records the union.
   The planted SCRIPT-ERROR-WORDING mutant fails the promoted no-arguments
   redis.call/pcall assertion in both modes, while POST passes it. The named
   failure is retained separately from the mutant's later GC timeout and CLI
   failure; see [tcl-final-proof.json](docs/wave10/tcl-final-proof.json).

### harness

- `ba2130b37` adds exactly `SLOWLOG - Rewritten commands are logged as their original command`
  to ORDER_TESTS, citing REGISTER `SLOWLOG-EXEC-BLOCKED-ORDER`. Its sole retry is
  the existing named, fresh-server retry. `64ce11477` restores headline slowlog
  isolated setup after excluding the global ring and applies that same bounded
  retry to isolated assertions. The zero-maxlen predecessor otherwise leaves
  capacity zero. Ten Tcl harness tests pass; no blanket retry is used.
- `5cf54663a` adds the directed snapshot/eviction/escalation/CRLF checks above.
  `b286c5070` fixes their private fixture cleanup: drain QSBR before disarming
  and destroying the sidecar. Its original eight read-local cleanup crashes are
  retained. This changes no production retirement behavior.
- `093d2b650` adds the eight missing fixture labels and extends partial-only
  `GATE_PROOF_NO_RATES=1` to omit stream/xmove release timing ratios. Data and
  mechanism assertions remain. A non-partial invocation with this flag is
  rejected. The atomic throughput floor and efficiency measurements remain
  with the maintainer; the full gate's behavior is unchanged.
- `435cc32f1` updates the lottery disposable-source builder's exact-count anchor
  for pubtrack's new `tracking_emit_invalidation(..., bool batched)` signature.
  The initial zero-anchor failure is retained. Lottery and publishfix schedule
  builds then succeed, are fresh, and pass whole gate netio jobs.
- `14fe9b924` removes the stale `infofix_compat-slowlog` scheduler entry as well as
  its already removed collector. The initial scheduler failures are preserved.
  The repaired real-tree `tests/gates_test.py` passes all 73 tests.
- `9bacbe2d6` replaces exec1s metric-name stringification with explicit labels,
  satisfying the headline's source-identity rule. Its whole source-identity job
  passes. All executable bytes, symbols/addresses and data layouts remain exact;
  only two INFO git strings, build-id and debug information differ after rebuild.
- `75cb895ab` repairs a stale DEBUG battery expectation for offline LOADAOF. It
  requires Redis's exact missing-file error, deletion of a seeded key and
  appendonly staying disabled. No assertion or row is removed.

- The broad whole-job campaign exposed two stale atomic-survivor assertions: the
  registration closure now uses scriptfix2's Redis-compatible error, and pcall is
  absent during FUNCTION LOAD. The repaired fixture checks that public boundary,
  rollback after a partial registration, and the caught-timeout terminal rule
  through the real internal library-call seam. No production code changes.
- The reorder identity inventory still named snapfix's four removed unbounded
  snapshot drains. The wave10 inventory substitutes all eight actual capped
  masked/unmasked bodies, comparing 326 bodies and adding eight missing-body
  negative controls. The snapfix POST has the same substitutions. The complete
  repaired atomic-unit and reorder-identity jobs pass 29/0 including prerequisites;
  all 326 compared bodies are identical. See `harness-composition-proof.json`.

- Blockfix3 adds the default/explicit ERRORSTATS heading while infofix adds CPU.
  The INFO section-union fixture now includes both; its exact-set equality and
  protected-memory native checks remain intact. The initial eight section-union
  failures are retained. The complete INFO and rebuilt exec1s jobs pass 13/0;
  no generic error-accounting hook is introduced.

### Compile-only budgets and remaining bodies

All 31 budgeted units were compiled at inherited values and at headline budget
plus measured IPA-size delta, with ±8 trials. Only DB0 `t_server.o` changes
further, **33883 → 33911** (`11f52599c`). Recipes, sizes, digests and scoring are
in [budgets](docs/wave10/budgets/).

The linked inventory has **10,109 groups: 8,411 headline-identical, 1,310 changed
groups matching a supplied lane POST, and 388 composite/compiler-propagated
remainders**. The hot inventory includes all counted scope bodies: 1,212 groups,
770 headline-identical, 323 lane-identical, 119 remaining. Every remaining body
and reason is listed in [changed-bodies.md](docs/wave10/identity-final/changed-bodies.md)
and its JSON companion.

The exact-all-hot-body target is **not fully met**. Direct GET/SET/MGET/MSET
handler variants match headline except normal-namespace notification-enabled,
no-borrow GET (`cmd_get<true,false>`), 799 → 792 bytes. That body exactly matches
four supplied lane POSTs; the missing-key sink advance is outlined. Additional
notification-budget trials restored it while changing ordinary notification
GET/SET bodies, so those trials were not selected. Ordinary requested scopes add
no instructions; TLS/notification misses are outside that instruction scope.
Identity remains a proxy and the maintainer decides merit. See the
[identity inventory's limits](docs/wave10/identity-final/README.md).

### Serverless integration-cost proof

[comparison.md](docs/wave10/instructions/comparison.md) and
[comparison.json](docs/wave10/instructions/comparison.json) contain all **116 paired
cases**: 48 ordinary command/batch cells; 48 EXEC cells; 16 EVAL cells; four
read-local GET cells. Both namespaces and modes are covered; EXEC/EVAL and MSET
include atomic 0/1. Counts are native production-namespace instructions, REP
counted once, excluding fixture code and shared libraries. The clock is fixed.
Each case has fresh initialized state; only EVAL warms one invocation and counts
its second. Exact replies are checked.

| Scope | Normal namespace POST−PRE | DB0 POST−PRE |
|---|---:|---:|
| GET / SET, batches 1 and 32 | 0 | 0 |
| INCR, batch 1 / 32 | −11 / −352 | 0 / 0 |
| MGET / MSET | no positive total | no positive total |
| EXEC, 1/2/4 children, all placements | −1,924 to −4,044 overall | included in overall range |
| EVAL, two INCRs on one shard | +686 | +637 |
| EVAL, two INCRs across shards | +283 | +266 |
| Read-local GET, batch 1 / 32 | −10 / −320 | −23 / −612 |

EXEC-same repeats one key. EXEC-cross uses distinct shards; its one-child case
is necessarily a degenerate one-shard control. Two/four children use two/four
shards. MGET/MSET use eight keys on eight shards. EVAL uses actual routing to
choose same/cross-shard keys.

All 47 positive EXEC/EVAL/read-local body subtotals have lane/commit attribution
in the JSON, including signature/outline movements. EVAL additions principally
come from scriptfix2's normalized SHA lookup and protected environment. No
integration-only instruction additions remain. PRE's 547/547 and POST's 551/551
counted bodies bind to their same-arm server with zero mismatches; PRE binds to
the supplied headline binary, not merely a local source rebuild. The normalizer
resolves exact literal bytes and checked switch destinations, preserving opcodes,
registers, immediates, offsets and padding. The explicit-label rebuild is bridged
by [source-labels-identity.json](docs/wave10/source-labels-identity.json): every
executable byte is identical, with only two eight-byte INFO git metadata changes
in other allocated data.

### Correctness receipts and visible failures

The active campaigns use [run_jobs.py](docs/wave10/run_jobs.py), which invokes
whole `GATE_ONLY_JOBS` jobs, retains every exit, binary hash and artifact path,
and never emits a full-gate receipt. The planned mode/engine expansion is
[correctness-matrix.json](docs/wave10/correctness-matrix.json); the completed-run
index is [correctness-jobs.json](docs/wave10/correctness-jobs.json). The final rebuilt candidate passes all 70 rows in the complete new-lane,
execfair interaction, disabled-latency, CRLF and netio job set. The repaired
whole AUTH job also passes in uring 1s. Final remaining coverage is pending.

Both complete standard differential matrices pass. Each engine runs all 47
suites, permanent seeds 7/19/20/23 and rotating seed **22**, split and fused armed,
atomic 0/1, plus mode equivalence and the normal MULTI repeats. Separate histories
reserve unused rotation 21 without claiming a run, so 22 is explicitly exercised
without removing any standard seed. Seed 22 includes **32 SAVE comparisons**
across eight mode/engine/atomic geometries and passes them all. The historical
SAVE failure is **not reproduced**, not declared fixed. See
[differential-final.json](docs/wave10/differential-final.json).

The first complete POST Tcl run has one unexpected failure in each mode:
`Non-interactive non-TTY CLI: Test command-line hinting - latest server`, because
MIGRATE is absent. Infofix itself documents that promoted failure. A later full
compat2 prerequisite run also fails the known rewritten-slowlog ordering
assertion in 1s, including its one permitted fresh retry. Both attempts are
retained; no new skip or retry was added. The Tcl/compat2 job is **not green**.

The complete staged-copy **abba_selftest job passes** (`final-abba-selftest-complete-copy`, 1/0). Earlier attempts are retained. The first exposed the
removed-ring scheduler entry and a concurrent selftest port collision; the
corrected attempt also had one scheduler fixture fail with Bash aborting while
interpreting an EXIT trap. All three early throwaway attempts additionally
omitted `.githooks/pre-push`, causing 21 receipt-fixture setup errors. That staging
omission is repaired; no production test is changed. These failures remain
recorded; the complete staged-copy rerun passes every control, including the 21
receipt fixtures. The real-tree standalone scheduler
suite also passes 73/73. EXPECT was changed only in the throwaway copy.

`make all` passes its footprint locks. All 56 production-unit target freshness
checks and `make -q all` pass again after the telemetry-label rebuild; see
[freshness-after-labels.json](docs/wave10/freshness-after-labels.json). Three initial attempted names
were parbuild readiness markers, not Makefile targets; their lookup errors remain
in `freshness-discovery.json`. Disposable lottery/publishfix build hashes and
freshness are in [variant-builds.json](docs/wave10/variant-builds.json). All six
original arms and both variants pass netio jobs in 1s/2s and uring/epoll.

The epoll 2s matrix had one directed client-LB destination assertion fail. Whole
FLIP jobs then pass on both headline and final POST. This is an **unreproduced
observation**, not a declared fix or noise. Commit `d9ed7de01` adds exact selected
socket/epoll/IO destination diagnostics while preserving the assertions.

Two blocking companion checks initially failed because the frozen arm directory
had no matching unit executables/cost binding. Their live protocol legs, including
the restored stream-removal row, passed. The remaining campaign now uses the
byte-verified `build/tomokv` with its fresh native companions. The original serial
campaign was explicitly stopped and every unfinished/failed whole job was
rescheduled; completed jobs and the cancellation are retained in
`main-campaign-restart.json` and `remaining-uring-plan.json`.

### owner-visible

- rlfix4 keeps `no_stack_protector` on `FlatStore::hash_key`: an explicit hardening
  relaxation. Its inclusion still needs the integrated-layout merit comparison.
- The global slowlog ring is excluded for the no-write-obstructed-read law;
  per-thread slowlog behavior and its named failures remain visible.
- exec1s-d's X3 idle rotation still has its documented +7 instructions. The
  historical seed-22 SAVE discrepancy remains an unreproduced item despite the
  passing standard seed-22 matrices here.
- The notification/no-borrow GET identity exception and common-image PAD limit
  are explicit above; neither is used to claim performance.

### Frozen arms and storage

The delivery binaries are frozen under `build/wave10/arms/`. Full SHA-256s and
paths are also in [arms.json](docs/wave10/arms.json) and [arms.sha256](docs/wave10/arms.sha256).

| Arm | SHA-256 |
|---|---|
| `PRE` | `80e48ae961e1e290b46bbbace613509aaefc9a59a6c9df5ec68ea972ddca938e` |
| `POST` | `844cf188071bae335a80e8ae15c2acaec2d1f583f235edf4bf4496421299660e` |
| `POST-minus-rlfix4` | `890ef8f74f30f830ee5a64fd8f55f8d200a60b0e61ce7bfc1752341fe69217a3` |
| `POST-without-rlfix4-current` | `d18d9e64d3e8f5ac2f9ec35f1f1b4e3d1f539218f18bc5c7972fc9a2693d4ed7` |
| `POST-layout` | `3e893b618c154c1b38963c1e95944f28d9639ef2dad204be07eba16315174fd1` |
| `PAD-A` | `7b6ffed04ddb2f689e479d1bc4e4107c2accad49b60b3689eacb74f57f94cc16` |

Historical POST receipts bind `ed88bd64…`, now retained as
`POST-before-source-labels`; the delivered `POST` is `844cf188…`. Their strict
executable/data bridge is recorded above and path history is retained.

The required literal pre-rlfix4 arm is commit `ba2130b37`
(production-identical to `e98831c81`). It predates the later cold CRLF repair and
DB0 budget selection. `POST-without-rlfix4-current` additionally reverses only
rlfix4's production diff from integrated POST, giving a fair current-layout
inclusion control.

**PAD-A is kind A, a behavior twin of POST-layout:** PRE behavior in the common
image with candidate code linked first and symbol-isolated PRE second. A five-byte
entry jump selects the implementation; sections, symbols and function addresses
are identical between the pair. This controls the larger common image, not the
smaller release POST. Measure POST-layout/PAD-A separately from the release null.
No PAD-B is supplied.

Superseded trial objects, arm source trees and step traces were removed only after
hashes/counts were recorded. Digests are retained in `pruned-artifacts.json.gz`,
`pruned-trial-receipts.json.gz` and `pruned-traces.json.gz`. Counts and final binding
receipts remain. Build storage remains below the 40G limit; the final size will be recorded after cleanup.

### Verification boundaries — NOT RUN

- Performance benchmarks, the full gate iteration and all ABBA/NIC merit cells
  remain with the maintainer. In partial correctness jobs, the atomic MGET/MSET
  throughput floor, RYOW rate assertions and stream/xmove release timing ratios
  are explicitly omitted. Data, window and mechanism checks still run.
- Lottery nightly has no public landing-gate job. Its disposable server was
  built and smoke-checked through the netio jobs; the nightly campaign was not run.
- The legacy `tests/publishfix_e2e.py` hard-codes CPUs 96–111 and ports 258xx,
  outside this lane allocation. Its scheduler builder and public atomic unit
  were exercised; that standalone driver was not run.
- `tools/exec1s_build.py` targets historical frozen revisions and hard-codes CPUs
  48–63; it has no landing-gate consumer. Wave10 arms were built with the
  allocation-correct integration helpers instead.

All `_schedule.py`/`_build.py` entry points and their gate/Makefile consumers
are listed in [builder-consumers.json](docs/wave10/builder-consumers.json).

### Maintainer measurement plan — NOT RUN

Use final arm hashes and the gate's existing instrument, load plans and acceptance
rules. Keep latency tracking off for the null and fixed-anchor races. Record the
actual geometry; do not substitute correctness geometry for a reviewed ABBA
geometry. Include contemporaneous byte-identical null controls. Rate at matched
offered load decides merit; cycles/op, instructions/op, IPC and latency explain it.
No failing cell may be averaged away.

1. Wave null: POST versus headline PRE, the unchanged 28 cells in
   `docs/wave10/cells/null28.txt`, with three blocks for `notify_exm`. Retain the
   TTL 20M-key expiry witnesses, split GET/SET and p8 MGET/MSET cells. Also compare
   POST-layout with PAD-A; PAD-A is **kind A: PRE behavior in the common candidate
   control image**, not a same-size twin of the smaller release POST.
2. EXEC merit: `/home/user/Projects/calib/exec-merit.py`, all eight
   `x{1,2}s_a{0,1}_{unc,hot}` cells, `--conns 64 --threads 16 --cells all
   --blocks 3 --secs 20`. Pipeline remains 4, with four plain INCR writers on hot
   cells; databases=1, 1s read-local=1/64 shards, 2s ratio=6:2/16 shards. Key/client
   balancing and automatic FLIP remain off as the driver specifies. Compare
   POST/PRE and POST-layout/PAD-A. Report EXEC and competing plain-write rates
   separately, plus retries, claim visits, eager collapses, extra passes,
   kernel entries, WB sends/retirements, cycles/op, instructions/op and IPC.
3. Depth sweep: `/home/user/Projects/calib/exec-depth-sweep.py`, PRE and POST; both
   modes, atomic 0/1, placements `cross,same-owner,same-shard`, depths
   `16x1,16x4,32x4,64x4,128x4`, `--blocks 3 --secs 10`. Retain cross/same-owner
   64x4/16x4 >=0.90 and 128x4/16x4 >=0.85, and X2's stricter same-shard
   64x4/16x4 >=0.95 in each mode. Exact order violations must remain zero.
4. Fixed-anchor race against `/home/user/Projects/bench-bins/tomokv-headline-991d48f65`
   (hash in `fixed-anchor.json`): `cells/generic14.txt`, the nine explicit
   `rl=1` cells in `cells/readlocal9.txt` with three blocks, and the EXEC matrix
   above. Retain this independently of the wave null. For rlfix4 inclusion, also
   compare POST against `POST-without-rlfix4-current` on those read-local cells
   and the null; this holds the other integrated code and selected budgets fixed.
   The required literal `POST-minus-rlfix4` is delivered too, with its older
   budget/cold-error difference documented.
5. Contended-script storm: `/home/user/Projects/calib/script-storm-merit.py`,
   POST/PRE, `--blocks 3 --secs 30`; its T6 shape is 2s ratio 6:2, 16 shards,
   atomic 0, databases=1, two keys on distinct owners, eight EVAL clients, four
   EXEC clients, four WATCH/EXEC clients and four plain writers. Require exact
   final data, zero POST script refusals and zero atomic order violations; report
   successful scripts, EXEC, plain writes and WATCH aborts separately.
6. Sixteen-save BGSAVE curve: PRE/POST, both modes and engines, atomic 1, 16
   shards, databases=16, read-local 1 in 1s/0 in 2s, balancing/automatic FLIP off,
   idle one-key fixture, save rules disabled. Use `tests/snapfix.py --case
   bgsave-loop --saves 16 --stall 300 --atomics 1 --no-oracle`, supplying each
   frozen `--binary`, the Redis `--oracle`, assigned `--cores`/`--port`, and
   distinct `--output` directories. Each `rss.json` must record all 16 saves
   even if PRE exits at the RSS assertion. Compare the full RSS and command-send
   to BGSAVE-acceptance latency curves; POST must meet the existing RSS bound.
7. Landing `tests/gate.sh iteration`, after the owner updates EXPECT to
   **946/963** and resolves the documented CLI-hint compatibility policy. The
   real worktree's protected assignments remain **881/898**.

For the external EXEC/depth/storm drivers, an explicitly scoped placement is
`--server-cores 64-71 --load-cores 72-95 --port 20000`; the maintainer schedules
the quiet box and may use its established wider instrument placement. Use
`/home/user/Projects/cx-exec1s-d/build/benchtxn` for EXEC/depth and record its hash.
Do not run the two snapshot arms concurrently. The measurement cell files and
fixed anchor are hashed; append results as MEASURE-RESULT.
