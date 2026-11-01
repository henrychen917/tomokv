# Wave 13 integration and measurement request

## wave13 integration

Work in progress on `cx-wave13`, based on headline `7d2f8a205`. No push.
The three lane reports were read before their two-parent merges:
`1bfbeaef3` (flipfix6), `397e32db0` (persistfmt), `5c499a736` (surveytools).
Lane branches are unchanged. The maintainer's merit addendum excludes both
execfifo2 and execfifo3; their FIFO behavior and fifteen rows are absent.

All builds and authorized correctness work use CPUs 0–15, builds `-j16`,
ports 20000–20099, and `LC_ALL=C` for every server/oracle boot. No performance
benchmark, load generator or full gate iteration is authorized in this lane.

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
  fragments that leave keys unchanged.
- Persistence restart rows now compare FUNCTION FLUSH versus FLUSHALL against
  Redis before SAVE/BGSAVE/SHUTDOWN SAVE/DEBUG RELOAD/AOF rewrite. The scheduled
  PS4.4 row retains SET and additionally fails FLUSHALL and FLUSHDB writes at the
  exact increment-file boundary, requiring the blocked diagnostic window and
  no reply before/after the fatal exit. These are subchecks, not new public rows.
  The same restart rows now require a real tracked-key invalidation from
  FLUSHALL and no invalidation from FUNCTION FLUSH, fenced by a subscriber PING.
- The new error-site inventory is `docs/crlffix/wave13-added-sites.json`; all
  public errors still reach central reply builders. Internal snapshot/compiler
  strings reach existing persistence diagnostics, not raw RESP line writes.
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
instruction diffs against headline, flipfix6 and persistfmt. Of the 88 command
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

### Maintainer measurement request

After the correctness and artifact receipts below are complete, use the gate's
own instrument on the quiet box for the wave null against the supplied headline
(watch **h05**), the fixed-anchor race, EXEC at 64 connections against both the
headline and Redis 7.4, the contended-script storm, and the landing gate.
Retain matched-load rate, cycles/op, IPC and instructions/op for every arm/cell.
Identity and instruction counts are proxies; the maintainer's merit decides.
No throughput claim is made here.
