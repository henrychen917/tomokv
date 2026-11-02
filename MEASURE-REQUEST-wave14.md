# Wave 14 integration and measurement request

## wave14 integration

**Late validation correction:** the broad sweep caught a stale R7
generated owner envelope. Clientcompat changed the ordinary owner's LB freeze
condition to `ExDrain` so TRACKING acknowledgements can progress during
`IoDrain`, but its generated R7 copy still froze during both stages. The copy
is now regenerated from the ordinary owner. Both the source parity check and
the actual owner fixture reject the old condition. The new release is frozen
at `a0e4d122e8`; complete selected correctness sweeps are running again.
Earlier receipts remain historical, including the explicitly interrupted
superseded sweeps. No EXPECT or public row count changes accompany this fix.

Integrated on `cx-wave14`, based on `105c5818cc`. No push. All six
lane reports were read before integration. Merge order: witnessfix, rootcore,
blockfix4, rootcompat, clientcompat, execfifo3. The maintainer's two merit
addenda authorize every merge. Lane branches are read-only inputs.

Builds and correctness work use CPUs 0–31, builds at most `-j32`, ports
20000–20099, and `LC_ALL=C` on every boot. Only selected correctness jobs,
oracles, differential suites, and finite serverless instruction scopes run
here. Performance/load generators and the full iteration remain maintainer work.

The supplied headline path omits one hash character. The existing frozen image
is `/home/user/Projects/bench-bins/tomokv-headline-105c5818cc`.

The exact source census is **1090 quick / 1107 full**, against 1046/1063:
**DQ=DF=44**. All additions precede the quick exit at line **6820**.

| Source | Delta | Collector line(s) |
|---|---:|---|
| witnessfix | +2 | 6563–6564 |
| rootcore | +7 | 6474 |
| blockfix4 | +5 | 6626 |
| rootcompat | +9 | 6671 |
| clientcompat | +5 | 6520 |
| execfifo3, including execfifo2 | +15 | 6690–6692 |
| Integration FUNCTION capture/replay witness | +1 | 6475 |

The lane-only sum is 43, giving 1089/1106; the integration witness gives the
final 1090/1107. The label multiset has 45 additions and one removal because
`EXEC fast-lane polls` is renamed `EXEC fast-lane polls and wave6-wave10
interactions`, with no row-count change. Every declared label is in the fixture:
no missing or extra occurrences. `docs/wave14/row-inventory.json` records all
collector lines and the gate digest. EXPECT constants remain **1046/1063**,
untouched; the maintainer must set **1090/1107** at landing.

MISCONF recovery and the WAITAOF non-mutation receipt are known differences,
as required by the integration brief. Their directed checks retain
arming and exact observed behavior instead of unconditionally failing or
accepting arbitrary errors. Other lane residuals remain explicit exclusions.

Both public rows explicitly say `known difference` and name
`MISCONF-NEVER-CLEARS` / `WAITAOF-NOOP-RECEIPT`. Passing them establishes the
documented observation, not Redis parity or a completed fix.

**Release conditions still unmet:** the requested wake event/invalidation/
slowlog ordering is red against Redis, universal headline/isolated-lane
linked-body equality is not achieved, and the final epoll Tcl run found a
parked connection left after peer close. Additional half-close controls expose
queued-input loss on both headline and merged POST. Details are below. Broad
correctness validation is still running. No throughput claim is made.

### Epoll EOF finding; trial rejected

The final full Tcl run fails two required list assertions in split epoll.
Isolated assertion probes and three complete-list samples per arm/mode pass on
both the candidate and headline; those samples do not replace the failed
full-suite verdict. A bounded diagnostic then reproduces the same failure in
fused epoll: before the first fairness scenario starts, an earlier closed
BRPOPLPUSH connection remains parked. INFO reports two blocked clients where
the unchanged assertion requires one. The later failure is contaminated by
that first failure's retained clients. `tcl-fairness-original-failure.json`
and `jobs/tcl-fairness-capture-r7-1.json` retain the original and captured cases.

A native socketpair check presents data and FIN in one observed epoll edge.
The short read consumes the bytes, sets `recv_armed`, and leaves no next edge
to expose EOF. Both namespaces fail exactly at the missing teardown assertion;
both open-peer mode controls pass. `jobs/epoll-eof-before.json` records the
gate's private diagnostic job. An isolated candidate preserves FIN in the
existing deferred-close queue. That trial is **not landed**. Its native
counterexample passes, but its full Tcl run has separate, unattributed tracking-order
failures, and a further half-close control does not establish preservation of
all queued input across close. `epoll-eof-candidate.patch` records the rejected
trial; none of its source or six selected budget changes enter production.

The extra control sends 1/32/65/256/4096 INCR frames, half-closes only the write
side, waits for the exact client to retire, and checks every applied write.
Redis applies all frames. The unpatched integration and headline also discard
frames beyond the ROB window; these observations **do not attribute that
failure to the trial**. A headline leg additionally fails to retire. The first
headline attempt stopped that leg after its failure; a separate complete
attempt retains every per-case verdict. No failed attempt is replaced.
The ordinary `epoll_recv`, `epoll_pass`, and deferred-close implementations
are text-identical to the headline. This supports a pre-existing EOF defect,
not a lane interaction. `epoll-eof-decision.json` binds the source comparison,
trial decision and controls. The parked-close and half-close issues remain
unresolved release findings. Private diagnostic jobs add no public rows.

Compile-only trial receipts retain 20 initial and 38 nearby compilations plus
40 distinct linked selections. The best rejected trial preserved all ten
GET/SET/MGET/MSET groups and all parser groups relative to the frozen merged
POST, with seven other changed hot groups; those results are not evidence for
the landed image. The release's own census and identity receipts below remain
the applicable proof.

### FUNCTION rewrite interaction (confirmed and fixed)

The forced capture witness on the unmodified merge acknowledged library version 2,
then replayed version 1 after restart. It pauses immediately after the registry
image copy, replaces the library on another IO, and requires the window to open.
The old order copied libraries before `rewrite_mark()` drained the old increment;
the journaled replacement was therefore deleted with that increment. Library
capture now follows increment rotation while all shard owners remain frozen.
Every later mutation is journaled in the retained increment. Earlier duplicate
full-registry postimages replay in their original order. The scheduling wrapper
is linked only into the witness twin; the release binary contains no hook.
The negative receipt is `docs/wave14/jobs/function-capture-before.json`.

### Wake publication audit: release condition still fails

The directed single-observer test (`tests/wave14_order.py`, partial gate job
`wave14_order`) compares EVAL, EVALSHA and EXEC with a registered BLPOP waiter,
keyevents, invalidations, and slowlog. It verifies same-shard, same-owner and
cross-owner placement. The merged reply is correct (the script sees its item
before BLPOP consumes it), but the requested Redis publication order is **not
satisfied**. Invalidations are batched before events; same-shard Lua captures
wake events under the producer's notification context; deferred EXEC/staged
wakes omit pop events; slowlog may record BLPOP before the producer.

Controls use the frozen headline and all five production lane POSTs,
with ordinary read enrolment because the headline lacks EXEC enrolment. After
the initial one-geometry check, all seven arms ran all sixteen geometries:
144 command/placement cases each. The merged event/invalidation sequence equals
rootcompat in **144/144** samples, and its reply equals blockfix4 in **144/144**.
Every arm still fails Redis's event/invalidation sequence in all 144 cases.
This supports attribution to the pre-existing publication problem for those
sampled schedules; it is not a proof over every concurrent schedule.

**Slowlog attribution remains incomplete:** 6/144 merged sequences do not
exactly match any of the six sampled controls (the initial three-control
comparison had 21 unmatched cases). Relative waiter retirement
varies across samples, and these controls do not establish whether every
unmatched ordering is inherited or introduced by composition. No ordering fix
or Redis pass is claimed. `order-all-lanes-comparison.json` includes every arm's
exact sequence and all unmatched cases; `jobs/order-matched-all-*.json` binds
the complete controls. The earlier single-geometry red receipts remain too.

The corrected release's EXEC-enrolled diagnostic also runs all sixteen geometries:
**144/144 replies pass, 0/144 event/invalidation sequences pass, and 70/144
slowlog sequences pass** against Redis. `jobs/wake-order-r7.json` retains
that fixture and its oracle; the earlier arm passed 68 slowlog sequences.
These red diagnostics are not promoted,
tolerated as Redis passes, or hidden in a green gate row.

### Initial command census and budget criterion

The rebuilt PRE matches all 718 headline hot bodies and all 88 headline command
bodies; its only two linked-body differences are the cold INFO git identity
strings from the archive build. All 216 PRE scopes completed. The first merged
census exposed +35 instructions per DB0 GET and +10 per DB0 INCR, attributable
to `FlatStore::find` outlining `Slice::key_eq`. That body happens to match the
older execfifo3 binary but regresses the newer headline. Budget selection
therefore prioritizes headline identity for hot bodies unchanged by every lane;
matching an older lane's incidental compiler output is not sufficient. Initial
and rejected counts are retained, not presented as the integration cost proof.

### Other semantic interactions

- The generated R7 owner now inherits clientcompat's `ExDrain`-only LB freeze.
  An actual owner fixture arms an unacknowledged TRACKING publication, requires
  progress during `IoDrain`, requires the later publication to remain frozen
  during `ExDrain`, and checks completion in `Idle`, with read-local off/on in
  both namespaces. Replacing only the generated owner object with its old
  version fails exactly at the IO-drain receipt assertion. Source parity,
  runtime engagement, split-local checks and writeback controls pass afterward.
  The correction changes six R7 function groups and zero ordinary groups.
- `post_client` and `post_client_transfer` both publish the queue entry, execute
  the rootcore sequentially consistent fence, then set the notification mask.
  flipfix6's transfer still moves session ownership through the same queue. The
  fence does not replace its S2 or pinned-close refusal. The inbox fixture covers
  client, transfer, task, fused and FLUSH producers.
- Published, FIFO-placed EXEC is distinct from prepared/unpublished S2. A new
  core fixture stops actual fragments between placement and the execution
  barrier: it must hold IO/executor drain without taking an S2 refusal, then
  complete exactly once after FLIP rollback. The existing wave13 FLUSH/S2/close
  assertions and FIFO blocking/whole-shard FLUSH checks remain present.
- A keyless tracking overflow cancels outstanding read tokens and clears the
  cache; EXEC retirement respects the cancellation. The cap row now also
  enrols through EXEC, in every existing scan geometry. It retains fresh-state,
  bounded window arming and exact full-cache coverage; no tolerance is widened.
- New error sites were audited against crlffix. The new direct `reply_err` sites
  use static ACL/SORT, OOM, subscription and WAITAOF-disabled messages. XREADGROUP
  still uses the central NOGROUP builder; no new user-controlled error text
  bypasses the central CR/LF handling.
- The blockfix4 creator row now includes RESTORE-stream. Its existing raw
  fixture was excluded pending D9, which wave13 persistfmt supplies. The
  merged row requires two parked/woken XREAD hits and oracle-exact values
  per declared geometry, without adding a public row. Both network engines
  and namespace builds are selected in the validation plan.
- The maxmemrace Redis oracle assumed `maxmemory 1` immediately implies OOM.
  Redis's eviction time slice may instead return `EVICT_RUNNING`, admitting a
  write before a later eviction attempt reports failure. Oracle setup now waits
  at most five seconds for the actual OOM, accepting only interim `+OK` and
  recording its count. All 48 TomoKV legs are unchanged.

### Tcl reconciliation and negative control

All 22 touched named assertions were attempted three times in each mode on
both engines on the corrected release (**264 isolated attempts**).
`docs/wave14/tcl-r7-both-engines-audit.md` lists every result and the reason for
retaining a skip. All three existing lane promotions pass all twelve attempts.
No guard-only promotion is restored merely because a diagnostic sample passes;
intermittent and consistently failing assertions remain named skips. Original
receipts, including failures, are preserved. The earlier pre-budget and
pre-R7 sets of 132 uring attempts are retained separately.
The final manifest requires 1876
assertion occurrences and has 213 named skips, versus 1878/211 on headline:
three lane promotions and five witnessfix/rootcompat retirements. See
`tcl-manifest-reconcile.json`.

The normal Tcl gate job rejects a throwaway binary that discards CLIENT's
subcommand name. Both modes fail the unchanged upstream `CLIENT LIST with IDs`
assertion: actual `cmd=client`, required `cmd=client|list`. This is an assertion
failure, not a timeout or missing window. See `tcl-planted-r7-witness.json` and
`tcl-regression-r7-build.json`; the control was rebuilt from final objects. The first historical invocation was rejected by the gate's
16-physical-core resource preflight and booted nothing; the valid invocation
uses 16 of the authorized cores.

### Compile-only budgets and linked bodies

The audit compiled all 59 pinned units in PRE and POST (118 initial trials),
then 232 nearby budget choices, yielding 150 distinct linked candidates.
Twelve budgets changed. Recipes, IPA size estimates, canonical object digests,
strict linked scores and selected values are retained under
`docs/wave14/budgets/` and `budget-linked-scores.json.gz`. No trial ran a server.
The R7 correction adds two IPA size units in each affected translation unit.
Eight further compile-only trials retain the existing budgets: the derived
+2 settings emit identical functions, while the selected link changes only
six R7 bodies. `r7-budget-trials.json` records every trial and the decision.

All **10 GET/SET/MGET/MSET handler groups equal the headline**. The complete
inventory contains 10,730 groups: 8,270 equal headline, 1,721 changed groups equal
an isolated lane POST, and **739 residual groups**. Of the wider 89 command-hot
helper groups, 42 equal headline, 16 equal a lane, and 31 remain composite or
compiler differences. The inventory does not hide these behind address,
source-line, member-offset, register or opcode masking. Every changed body,
size and attribution is in `identity-release-r7/changed-bodies.md` and its JSON
companion. Single-lane mismatches and unisolated compiler changes remain
explicit; universal lane-POST equality is an **unmet criterion**, not a pass.

The rebuilt PRE is source `105c5818cc`. All 718 hot groups and 88 command-hot
groups equal the supplied headline. Its two remaining differences are cold
INFO git identity strings inherited while building the archive inside this
worktree; no command execution difference is attributed to them.

### Command-scope integration cost

There are **216 PRE and 216 POST cells**. GET/SET/INCR/MGET/MSET and idle-waiter
LPUSH/RPUSH cover batch 1/32, both modes, both namespaces and both atomic
settings. Additional scopes cover read-local GET, uncontended single/cross-owner
EXEC, warm EVAL/EVALSHA, empty/nonempty FLUSHALL and execfifo3's parser scopes.
The full PRE/POST table and every per-function delta are in
`instruction-comparison-r7.md` and `instruction-comparison-r7.json`.

| Scope | Added executable instructions per command, min…max |
|---|---:|
| GET | 0…0 |
| SET | −33…−32 |
| INCR | −27…−25 |
| MGET | −42…+16 |
| MSET | −121…+6 |
| LPUSH / RPUSH, no waiters | −21.5…−17 |
| Read-local GET | 0…0 |
| Warm EVAL / EVALSHA, single owner | −78…−38 |
| Warm EVAL / EVALSHA, cross owner | +81…+138 |
| Uncontended EXEC, single owner | +325…+451 |
| Uncontended EXEC, cross owner | +404…+522 |
| FLUSHALL, empty | +96…+454 |
| FLUSHALL, nonempty | +128…+534 |
| GET parser | −7…0 |
| SET / INCR parser | −7…−0.21875 |

GET, SET and INCR meet **zero added instructions** in every cell. Fractions
above are complete batch counts divided by batch size, not sampled rates.
This census enters executable production bodies, outlined STL and Lua code;
fixture glue, shared libraries, syscalls and synthetic clock calls are excluded.
It does not claim full network-loop cost, cycles, IPC or throughput.
All **1,243 PRE and 1,264 POST entered body/stub groups** bind to their production
arm. Actual executed clone addresses are checked, and the assembly read-local
fence retains its bytes and resolved jump targets. See `scope-binding-pre.json`
and `scope-binding-post-r7.json`. The fresh census differs from the earlier
POST census in 14 Lua cells by exactly five instructions, solely in `luaH_get`;
every other count is unchanged. Both actual observations are retained in
`r7-census-differences.json`, without rounding away the Lua variation.

The first parser attempt used an affinity subset excluding its declared CPUs
0–7 and failed before entering a measured scope. The completed attempt uses
only authorized CPUs 0–31; its failed predecessor is preserved. Initial
pre-budget counts and the initial +35 DB0 GET regression also remain recorded.
Raw step traces, probe binaries, trial objects and arm source trees were retired
after saving hashes, counts and binding receipts. Reproduction must first
restore/build source `105c5818cc` at `build/wave14/pre-source`; the frozen PRE
binary remains available independently.

### Frozen arms

| Arm | Path | SHA-256 |
|---|---|---|
| PRE | `build/wave14/pre/tomokv` | `eb46b9718b4642fc78d3139f9e903c934bd0f47f3867267ea003af3f30ef5814` |
| POST | `build/wave14/post-r7/tomokv` | `c1ed04ec304d1ef2863c37fd072a20c1bd134808cd8d0c42094dc7bb17a2763e` |
| POST-layout | `build/wave14/layout-r7/POST-layout` | `e17dfa2cc9b48e9cdbdda1dbe8cc59175d043c1a3295063ba285a4b3a9a9dbd5` |
| PAD-A | `build/wave14/layout-r7/PAD-A` | `b701dcca90283c33d42b3d71efa9f1cd65c18ea29e56edc4906b47dc6ef24077` |

POST's production source and Makefile are frozen at `a0e4d122e8`; later commits
add fixtures, receipts and reporting. PAD is **(A) behaviour twin**. POST-layout
links POST first and a symbol-isolated PRE second; PAD-A changes only the
five-byte entry jump to PRE. Their sections, symbols and every function address
are identical. Both namespaces take PRE's entry/dispatch. The common image is
larger than the release candidate, so **the exact twin of PAD-A is POST-layout,
not POST-release**. Use the pair as a separate layout control; retain the release
wave null. `pad-a-r7.json` contains the link and exact patch proof. Both PAD-A
and POST-layout passed the gate's netio checks in both modes/engines and
default-namespace checks in both modes (four public rows per arm including
release). PRE was rebuilt byte-for-byte for the replacement twin;
`pre-reproduction.json` binds that reconstruction. `arms-r7.json` and
`arms-r7.sha256` bind all four final images.

### Maintainer measurement request — NOT RUN here

Use the gate's unchanged matched-offered-load instrument and reviewed geometry,
with contemporaneous identical-arm nulls. Retain cycles/op, instructions/op,
IPC, offered load and all raw legs per cell. **Rate at matched offered load**
(and the cell's declared depth-one latency score) decides merit. Main commands
must meet the owner's zero-regression rule. Identical-arm spread above 2%
requires investigation. The instruction census cannot replace this decision.

1. **Wave null:** POST-release against the supplied `105c5818cc` headline,
   all 28 unchanged cells in `docs/wave14/cells/null28.txt`. Repeat three
   independent blocks; specifically retain d128g_l0, x9_32_l0, d32g_l1,
   d32s_l1, p8g/h05/h06 and notify_exm. The four 2s GET/SET p1/p32 cells are
   already present as h53/h54/h21/h22. Run POST-layout against **PAD-A (type A,
   PRE behaviour in the common POST-layout image)** on the same cells; compare
   rebuilt PRE with the supplied headline separately. Do not substitute the
   larger common image for the release null.
2. **Fixed-anchor race:** POST-release against
   `/home/user/Projects/bench-bins/tomokv-headline-991d48f65`, three blocks,
   `docs/wave14/cells/anchor19.txt` (deduplicated generic14 + readlocal9), plus
   EXEC below. Keep this result separate from the wave null.
3. **EXEC at 64 connections:** `/home/user/Projects/calib/exec-merit.py`,
   `--conns 64 --threads 16 --cells all --blocks 3 --secs 20`, with
   `--benchtxn /home/user/Projects/bins/benchtxn-b6e76d422`. Compare POST with
   the supplied headline and Redis 7.4.10 (`--redis-io-threads 1`). Preserve
   both modes, atomic settings, uncontended/hot cells, pipeline four, two INCR
   children and the four competing plain writers. Require zero order violations
   and retain plain-writer share separately. FIFO/D6's approved hot split-mode
   trade must remain explicit; aggregate EXEC rate cannot hide it.
4. **Contended-script storm:** `/home/user/Projects/calib/script-storm-merit.py`,
   POST against the supplied headline, `--blocks 3 --secs 30`. Keep the standard
   T6 geometry: split 6:2, 16 shards, atomic 0, databases 1, two owners, eight
   EVAL clients, four EXEC, four WATCH/EXEC and four plain writers. Require exact
   final values and zero refusals/order violations; retain each class separately.
5. **Landing:** after resolving/accepting the explicit unmet release criteria,
   the maintainer applies **1090/1107**, retains the complete label fixture and
   runs `tests/gate.sh iteration`. Selected partial jobs do not certify landing.

The ABBA entry point is `python3 tests/abbagate.py --subset full --cells FILE
--reference-binary REFERENCE --candidate-binary CANDIDATE --null-result NULL
--output UNIQUE_DIRECTORY`. Supply explicit scheduled `--server-cores`,
`--server-smt`, `--load-cores`, `--load-smt` and `--ports`; do not inherit defaults
while other lanes run. EXEC/storm use their `--reference`, `--candidate`,
`--server-cores`, `--load-cores`, `--port` and unique `--output` arguments.
Keep `LC_ALL=C`. `measurement-inputs.json` binds the cells, drivers and anchors.

Performance/load generators, saturated-FLIP, quantitative atomic floors,
stream/xmove rate checks and full iteration are **NOT RUN: maintainer-only**.
`GATE_PROOF_NO_RATES=1` preserves their correctness assertions where supported;
the standalone efficiency and saturated-load jobs are excluded. No throughput
claim is made.

### Completed directed receipts

The final POST passes the 27 forced FUNCTION-history legs (3 Redis fsync
policies plus 24 TomoKV mode/engine/namespace/policy legs), including every
restart, and all 48 maxmemrace candidate legs plus the oracle.
`directed-final-core.json` binds those completed jobs. The pre-R7 candidate
also passed the expanded keyless-tracking matrix: 80 candidate overflow legs,
including 32 EXEC-enrolment legs, each armed with zero missing invalidations;
that matrix is repeating in the final sweep.
The first stricter cap attempt used the obsolete drop counter and was stopped
as a fixture failure; the repaired predicate observes the null invalidation
emitted by the fixed overflow branch. That failed receipt is retained.

The pre-R7 full Tcl manifest passed in both modes on both uring and epoll;
these jobs are running again on the final release. Final named-skip probes
retain their red diagnostic results; all three lane promotions pass 3/3 in
each mode and engine. `MONITOR log blocked command only once`, for example, was PFP in
the earlier split-mode probes and is PPP in the final probes; the earlier
failure remains evidence against restoring its guard-only promotion.

`python3 tests/gates_test.py`: 77/77 passed. The headline's 83 becomes 77
because witnessfix removes seven tests of the retired Tcl retry and adds
one no-retry check; every other lane test method remains. The method inventory
is recorded in `gates-test-method-inventory.json`. `abba_selftest` passed again in
a fresh throwaway landing copy with 1090/1107, the final known-difference
labels and both private EOF diagnostics (`abba-r7-final-copy.json`). The final
standalone harness run again passes 77/77 tests; all 12 Tcl observer controls
pass (`gate-unit-final.json`). Source identity lint passed for all 59 C++ units in both namespaces
and six shared C units, including the stable-assertion failure checks. The
checked-in EXPECT values were never edited.

The placed/unstarted EXEC fixture passes under ASAN and TSAN, with all four
new namespace/atomic arming markers, all twelve wave13 FLUSH markers and all
54 original flipfix6 markers retained. Published placement holds the normal
ROB/executor drain; it is not unpublished S2. The unchanged S2 and pinned-close
paths still refuse immediately. `placed-exec-flip` has three passing public
rows including release.

All 55 primary `job_production_units` targets built, plus mdbqsbr live controls,
blockfix-cost and both blockfix2 units. `make -q all` and all four target-group
freshness checks returned zero; `production-freshness-r7.json` records the exact
lists. Matching native companions are bound beside the frozen POST with their
hashes in `companions-r7.json`; the release bytes remain unchanged. Two gate
launches overlapped the instrumented R7 object build. Serial recompilation
produced byte-identical objects in both namespaces and the installed TSAN image
matches its source image (`tsan-build-overlap-verification.json`).

The final POST passes the complete differential inventory on **both engines:
954 comparisons each**, with permanent seeds 7/19/20/23 and rotating seed 25
(uring) / 24 (epoll), all four seed-19 MULTI replays in each atomic-1 lifetime,
and every equivalence cell. Strict folds validate 490 split/equivalence and
464 armed comparisons per engine. `differ-final-r7.json` binds each plan,
source, ordered leg journal, completion and final binary. The earlier 954/engine
pre-R7 inventory (rotating 21/22) remains in `differ-final.json`. These are
selected-job proofs, not full-gate wall-time or landing receipts.

The broad sweep exposed a test-only compiler-launch failure in `rob_portable`: its
positive portable ROB unit passed, but the planted-control helper treated
`g++ -gz=zlib` as one executable filename. The helper now tokenizes `CXX`
with `shlex.split`, retaining direct argument execution. The same gate job
passes on rerun, including the intended missing-fence-clear assertion failure
(`jobs/portable-compiler-fixed.json`, two rows including release). The original
broad-run row remains recorded as failed; this is not a production change.
