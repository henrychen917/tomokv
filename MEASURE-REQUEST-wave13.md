# Wave 13 integration and measurement request

## wave13 integration

Work in progress on `cx-wave13`, based on headline `7d2f8a205`. No push.
The three lane reports were read before their two-parent merges:
`1bfbeaef3` (flipfix6), `397e32db0` (persistfmt), `5c499a736` (surveytools).
Lane branches are unchanged. The maintainer's merit addendum excludes both
execfifo2 and execfifo3; their FIFO behavior and fifteen rows are absent.

Builds and authorized correctness work are confined to CPUs 0–15, builds `-j16`,
and ports 20000–20099. The gate is invoked with `LC_ALL=C`. A historical
datafix1 helper overrode it for 120 boots before the exception was discovered;
those seven jobs are excluded from the valid-pass tally and documented below.
No performance benchmark, load generator or full gate iteration is run here.

### Row and Tcl reconciliation

The source census is **1046 quick / 1063 full**, against 999/1016 on the
headline: **DQ=DF=47**, comprising flipfix6 +3, persistfmt +44, surveytools +0.
No label is removed. `docs/wave13/row-inventory.json` records every declaration
and collector line relative to the quick exit. The complete label fixture is
updated; EXPECT_QUICK/EXPECT_FULL are unchanged and remain maintainer-owned.
The owner should set them to **1046 / 1063** at landing.

The Tcl manifest retains every wave12 promotion and adds persistfmt's three:
consumer seen/active times and the two DEBUG RELOAD options assertions. It now
requires **1878 assertion occurrences**, with **211 named skips**. No allowance
is added. `docs/wave13/tcl-manifest-reconcile.json` records the union.

### Interaction audit

- FLUSH preparation is transient inside one IO dispatch invocation. On older
  ROB work or insufficient owner capacity, it calls
  `xshard_abandon_unpublished`, releasing admission/apply credits before the
  next control pass; successful dispatch publishes the whole unit before
  returning. It therefore has no persistent S2 like `MultiSession::pending`.
  The headline still rejects FLUSH inside MULTI under its existing owner
  group-5 engine policy. An EXECABORT with WATCH cleanup can retain session S2
  after this queue error, and uses flipfix6's refusal.
  Published FLUSH remains protected by the unchanged IO/EX drain fences.
- The existing flipfix6 unit row now also requires twelve armed wave13 cases:
  FLUSHALL/FLUSHDB refusal at each owner capacity boundary (db1/db16, atomic
  0/1), and WATCH-cleanup EXECABORT after a rejected FLUSH child in S2 on
  surviving/converting sources. The
  original 54 armed cases remain required. The live row includes flushfix2's
  live-FLIP witness in both namespaces, with its oracle and all engine/atomic
  legs, plus the original PING-probed storm and scaled storm.
- Moved WATCH sessions receive FLUSHALL/FLUSHDB invalidation without losing
  physical alias pins. Added core checks inspect exact alias counts; live checks
  require nil EXEC after those FLUSHes and successful EXEC after CONFIG memory
  fragments that leave keys unchanged. Design A's `Shard::watch_flush` captures
  key existence and sets the dirty bit without removing registrations or alias
  pins. CONFIG memory fragments do not create WATCH pins: their public Op,
  scatter barrier and ROB must drain before `flip_drain_idle` permits transfer.
  The last CONFIG fragment removes its publication claim before reply retirement,
  and each owner applies the memory configuration before the barrier replies.
  The WATCH alias exception therefore does not bypass CONFIG completion.
- Persistence restart rows now compare FUNCTION FLUSH versus FLUSHALL against
  Redis before SAVE/BGSAVE/SHUTDOWN SAVE/DEBUG RELOAD/AOF rewrite. The scheduled
  PS4.4 row retains SET and additionally fails FLUSHALL and FLUSHDB writes at the
  exact increment-file boundary, requiring the blocked diagnostic window and
  no reply before/after the fatal exit. These are subchecks, not new public rows.
  The same restart rows now require a real tracked-key invalidation from
  FLUSHALL and no invalidation from FUNCTION FLUSH, fenced by a subscriber PING.
- The error audit records all 17 new/moved literal lines, including multiline
  branches, in `docs/crlffix/wave13-added-sites.json`. The companion
  `wave13-error-flow.json` traces their sinks and dynamic compiler/decoder error
  propagation. Public errors reach central reply builders; internal
  snapshot/compiler strings reach existing persistence diagnostics. No new raw
  RESP error writer is present.
- An early serverless development check failed because it incorrectly expected
  an EXEC containing FLUSH to execute; the existing headline explicitly refuses
  this at queue time. The check now requires that error and tests the ensuing
  WATCH-cleanup S2. No production behavior is changed to accommodate the fixture.
- FIFO integration requests are inapplicable to the excluded execfifo lanes;
  the headline script admission and transaction ordering must remain covered.
- Persistfmt's documented FUNCTION increment-AOF gap, native snapshot/AOF
  container format, unsupported no-preamble AOF and deferred administrative
  keyspace reload atomicity remain existing limitations. No new claim of Redis
  parity is made for those surfaces.

### Compile-only budgets and identity

The trials cover all 59 pinned production objects in both PRE and POST (118
initial compilations), 195 nearby budget trials, 138 distinct linked candidate
audits, and 24 additional bounded fanout trials. Recipes, unit instruction
estimates and decisions are in `docs/wave13/budgets/` and
`docs/wave13/fanout-trials/`. Final changes from the initially merged Makefile:
normal xshard 156257 → 156641 (auto 14 retained); normal snapshot 16860 → 16732;
db0 t_server 34177 → 34212; db0 AOF 39102 → 39117. Other budgets remain unchanged.

**Unconditional linked-body identity was not achieved.** The strict inventory
has 10,342 function groups: 9,038 equal headline, 1,021 changed groups equal an
isolated lane POST, and 283 residual groups. Every changed group and its reason
is listed in `docs/wave13/identity/changed-bodies.md`; every residual has exact
instruction diffs against headline, flipfix6 and persistfmt. Independent field
offsets/sizes and literal bytes explain 137 residual groups as displacement or
switch-table-label changes, including scale-4 shard-owner index arithmetic;
146 retain other compiler/composition differences.
Function snapshot save/load and AofManager::fail equal persistfmt in both
namespaces; normal stream decoding equals it too. db0 stream decoding remains
a compiler exception. The normal FLIP S2 helper differs from flipfix6 only in
verified member displacements; its db0 body also changes compiler structure.
Of the 88 command
hot groups, 62 equal headline and four equal persistfmt. Of the remaining 22,
ten differ only in verified Server member displacements, four only in compiler
switch-table labels with identical complete table bytes, and eight are the
normal/db0 xshard_prepare/xshard_execute bodies and cold clones with compiler
propagation. These exceptions are retained, not normalized away. The requested
universal headline/lane-body equality is therefore an explicit unmet criterion
for the maintainer's merit decision.

Persistfmt grows SnapshotManager by 24 bytes (792 → 816 normal; 528 → 552 db0),
moving 136 trailing Server fields by 24 bytes. Server grows by 64 bytes in each
namespace after alignment and flipfix6's diagnostic tail. All eight locked
types retain their required sizes. `docs/wave13/layouts.json` and
`reference-layouts.json` bind every field offset to the actual binaries.

### Command-scope integration cost

`docs/wave13/instruction-comparison.md` gives the full PRE/POST table, backed by
244 native cells and 96 Lua-inclusive warm-script cells. Every nonzero delta is
decomposed by executed function in the JSON companion. This is a bounded
serverless command activation/completion census; it excludes network syscalls,
shared-library bodies and idle scheduling. It measures no rate, cycles or IPC.

GET, SET and INCR execute **zero added instructions** at batch 1 and 32, in both
modes, both namespaces and both atomic settings. Read-local GET also has zero
delta. Normal MGET ranges from 0 to −4 per command; normal non-atomic MSET adds
two instructions per command in xshard_prepare (batch 32: +64), while atomic
MSET is equal. db0 MGET/MSET are below headline. Native EXEC deltas are −2..+1
normal and −6..0 db0 per complete activation. Native EVAL/EVALSHA add one
instruction normal, one to five db0; normal FLUSHALL adds one, db0 is equal.
These are instruction observations, not throughput claims.

All 696 counted native body/stub entries and 432 Lua-inclusive entries match
their production binary; PRE additionally binds to the supplied headline.
PRE .text and .data exactly equal that supplied binary; .rodata differs only in
two eight-byte INFO build IDs (`docs/wave13/pre-binding.json`).

### Frozen artifacts and validation status

| Arm | Path | SHA-256 |
|---|---|---|
| PRE (7d2f8a205) | build/wave13/tomokv-PRE | 589be7469cdadcac827fa88588001e71342244e48e37aae9ca91098509272d79 |
| POST (production source 68f85e5d5) | build/wave13/tomokv-POST | af2ed7e267f11f610b78a38abed942873dd2d1c1a0f303f8fd482cf9e66fc0ee |
| PAD-A | build/wave13/tomokv-PAD-A | 2d1abf4553feb009d9f9f6d07f13996f39cc68f7cf7695f4bad598465663f9db |

PAD is **(A) behavior twin**: headline behavior with POST's private structure
offsets, .text origin/extent and .rodata size. It has inert new storage and
unreachable padding. Individual function/data addresses are not matched;
notably its writable sections start 8 KiB earlier. This aggregate control
cannot isolate every placement effect. The recipe and exact section comparison
are in `docs/wave13/pad-a.json`. PRE and PAD source builds passed `make -q all`.

The authorized correctness job matrix is running. No full-gate pass is claimed.
The first build-only job selection was rejected by the gate interface; its
consuming unit job now builds all prerequisites. The durable Redis directory
contained binaries without headers; subsequent jobs use the complete checkout
at `/home/user/Projects/redis`, whose 7.4.10 binary has the identical SHA-256
`ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`.
Completed and failed attempts remain in `docs/wave13/jobs/`.

The primary attempt also exposed candidate packaging omissions: blockfix2 could
not find its two serverless refusal units beside the frozen POST, and the
following registry row could not find its candidate-specific cost checksum.
All six blockfix2 live rows and all 24 registry live legs passed, but neither
whole job is credited from that attempt. Ten matching production companions
and the checksum binding are now staged with hashes in
`docs/wave13/candidate-companions.json`; both complete jobs await rerun.
`docs/wave13/job-issues.json` preserves the failures and their causes.

The initial seven datafix1 jobs returned passing verdicts but their shared
helper forced `LC_ALL=en_US.UTF-8` for 120 target/oracle boots. These outcomes
**do not satisfy the requested C boot environment**;
`docs/wave13/locale-pin-exception.json` records them without crediting coverage.
Six locale-independent jobs will be rerun after pinning their helper to C and
checking the owned server process environment. The seventh, `datafix1_locale`,
deliberately requires a non-C inherited default to differ from C. Its assertion
is retained: **NOT RUN under the required C environment**, because that
precondition conflicts with the task constraint.

### Maintainer measurement request

**NOT RUN here: maintainer-owned performance work and full iteration.** Use the
frozen artifacts above, the gate's matched-offered-load instrument and reviewed
geometry, with contemporaneous identical-arm nulls. Require zero main-command
regression. Rate at matched load decides; cycles/op, IPC and instructions/op
explain it. Investigate identical-arm spread above 2%. PAD-A should stay flat
when attributing a POST change to behavior, subject to its stated layout limit.

1. Wave null: POST against the supplied headline
   `/home/user/Projects/bench-bins/tomokv-headline-7d2f8a205`, all unchanged
   28 cells in `docs/wave13/cells/null28.txt`. Use three blocks for p8g, **h05**
   and h06; retain the standing three-block notify_exm control and other cell
   settings. Include rebuilt PRE/PAD-A as the labelled layout comparison.
   The h05 watch is the maintainer's persistfmt merit addendum.
2. Fixed-anchor race: POST against
   `/home/user/Projects/bench-bins/tomokv-headline-991d48f65`, three blocks,
   `docs/wave13/cells/generic14.txt` plus `readlocal9.txt` and EXEC below.
   Keep this comparison distinct from the wave null.
3. EXEC: `/home/user/Projects/calib/exec-merit.py`, with POST as candidate in
   two comparisons: supplied headline, then Redis 7.4.10. Use
   `--conns 64 --threads 16 --cells all --blocks 3 --secs 20`, the same hashed
   benchtxn, all eight mode/atomic/uncontended-hot cells, pipeline four, two
   INCR children and four competing plain writers in hot cells. For Redis,
   select `--redis-io-threads 1` explicitly. Require zero order violations;
   retain EXEC and plain-writer results separately. Neither FIFO lane is present.
4. Contended script: `/home/user/Projects/calib/script-storm-merit.py`, POST
   against the supplied headline, `--blocks 3 --secs 30`. Preserve T6: 2s 6:2,
   16 shards, atomic 0, databases=1, two owners, eight EVAL clients, four EXEC,
   four WATCH/EXEC and four plain writers. Require exact final values and zero
   refusals/order violations. Retain each participant class separately.
5. Landing: maintainer applies **1046/1063**, retains the prepared label fixture,
   and runs `tests/gate.sh iteration`. Partial correctness jobs do not certify it.

Select scheduled CPU and port arguments explicitly for every instrument; never
inherit defaults while other lanes run. `docs/wave13/measurement-inputs.json`
binds the cell files, drivers and reference binaries. No throughput claim is
made here. Identity and instruction counts are proxies; merit decides.
