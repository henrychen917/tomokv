ACL key extraction delivery, 2026-10-08 (Asia/Taipei).

Worktree `/home/user/Projects/cx-aclkeys`, branch `cx-aclkeys`. The resume preserves
the four existing commits through `354d3a54e`; it changes no production source,
test assertion, build flag, or gate row. `git merge origin/cpp` returned
`Already up to date.` before the fresh proof. PRE is the merge base
`d81b6d3a2b095224d59049dc60342a6ca1574674`; POST's production sources are those
of `354d3a54e` (unchanged from `e931f1c0f`). No rebuild was needed: all four
recorded binary hashes verified, and POST and `build/tomokv` compare equal.

**This is not an all-green landing receipt.** The fresh serverless unit checks
all 245 registered specs and still exits **1: 27 metadata/routing-range
mismatches**, down from PRE's 31. Its independent 142 ACL admission/denial
assertions pass. The remaining mismatches are printed in full below; they are
not suppressed or converted into passes. The original requirement to eliminate
every runtime-spec mismatch is not fulfilled by these commits. The wake review
also identifies paths not covered by the BLPOP witness. The mainline's full gate
and 14-cell performance null remain outstanding.

<!-- LIVE_RESULTS_BEGIN -->
**Fresh live proofs: REFUSED by the quiet preflight; neither server was started.**
The initial attempt plus all three permitted retries failed over ten minutes.
The unchanged selected-core budget was 0.480 CPU-seconds per 20-second window;
failure is latched as soon as that budget is exceeded. These are environmental
refusals, not passing or failing ACL replies. CPU screening establishes activity,
not its owner; a process snapshot also showed compiler processes on the box, but
does not attribute the sampled activity to them.

| Attempt | Start UTC (2026-10-07) | Refusal UTC | Observed CPU-seconds | Verdict |
|---:|---|---|---:|---|
| 1 | 2026-10-07T17:25:22.053696+00:00 | 2026-10-07T17:25:27.063621+00:00 | 1.390 | REFUSED |
| 2 | 2026-10-07T17:28:42.053784+00:00 | 2026-10-07T17:28:57.070139+00:00 | 1.320 | REFUSED |
| 3 | 2026-10-07T17:32:02.053796+00:00 | 2026-10-07T17:32:06.062902+00:00 | 0.930 | REFUSED |
| 4 | 2026-10-07T17:35:22.053786+00:00 | 2026-10-07T17:35:35.069242+00:00 | 0.560 | REFUSED |

All timestamps are UTC; add eight hours for October 8 in Taipei.
The fresh campaign completed at `2026-10-07T17:35:35Z` (01:35:35 Taipei).

| Required proof | Fresh result |
|---|---|
| Registry cross-check | FAIL: 27 mismatches out of 245; exit 1 |
| Independent ACL permission assertions within that unit | PASS: 142 assertions |
| Strict BLPOP admission/parking/revoke/wake, atomic 0 | NOT RUN: quiet preflight refused |
| Strict BLPOP admission/parking/revoke/wake, atomic 1 | NOT RUN: quiet preflight refused |
| Vanilla Redis 7.4.10 differential, both atomics | NOT RUN: quiet preflight refused; no fresh oracle identity or reply comparison |

Raw [results.json](docs/aclkeys/delivery-proof/results.json) and the four
`quiet-*.json` / `quiet-*-samples.jsonl` files preserve every attempt.
No saved successful live witness or differential result was found in the prior
`docs/aclkeys/` evidence, so this report makes **no live-pass claim** from the
previous session either. The maintainer must run those proofs on a quiet box.
<!-- LIVE_RESULTS_END -->

**Production change and limits.** Restricted-key ACL checks now resolve the
command/subcommand with `command_metadata_resolve` and collect arguments with
`command_metadata_collect_keys`, the same generated rich key specs used by
`COMMAND GETKEYS`. `src/cmd/aclkeys.cc` owns the scratch argument view and key
walk. Admission, queued-command checks, and the existing blocking-retire recheck
reach this shared extraction. A failed argument-view allocation or caught
`std::bad_alloc` denies access. The existing unrestricted-key fast return and
ordinary dispatch remain outside this helper.

BLPOP, BRPOP, BZPOPMIN and BZPOPMAX additionally change their runtime last-key
field from `-1` to `-2`. This excludes the final timeout. The generated metadata
already had the correct value. Counted-key commands, scripts/functions,
destination keys, stream ID halves, subcommand HELP arms, and `not_key` pubsub
channel specs are handled by the shared metadata extractor instead of treating
their trailing arguments as keys. Existing SORT BY/GET restrictions and script
command restrictions are retained; this is not a claim of complete Redis ACL
feature parity or malformed-argument/error-precedence parity.

The 27 remaining legacy triplet differences are real failures of the requested
cross-check. Rich metadata can express counted keys and subcommands that its
legacy `first,last,step` summary cannot; several runtime fields also serve
routing. ACL no longer consumes those triplets. That explains why permission
assertions can pass while the triplet audit is red; it does not satisfy or waive
the requested zero-mismatch criterion. No further production repair was made
in this delivery-only resume.

<!-- MISMATCHES_BEGIN -->
Full triplet inventory (`first_key,last_key,key_step`), in registry order:

| Command | PRE runtime | Generated | POST runtime | POST mismatch |
|---|---|---|---|---|
| BLPOP | `1,-1,1` | `1,-2,1` | `1,-2,1` | fixed |
| BRPOP | `1,-1,1` | `1,-2,1` | `1,-2,1` | fixed |
| BLMPOP | `3,-1,1` | `0,0,0` | `3,-1,1` | YES |
| LMPOP | `2,-1,1` | `0,0,0` | `2,-1,1` | YES |
| SINTERCARD | `2,-1,1` | `0,0,0` | `2,-1,1` | YES |
| BZPOPMIN | `1,-1,1` | `1,-2,1` | `1,-2,1` | fixed |
| BZPOPMAX | `1,-1,1` | `1,-2,1` | `1,-2,1` | fixed |
| BZMPOP | `3,-1,1` | `0,0,0` | `3,-1,1` | YES |
| ZMPOP | `2,-1,1` | `0,0,0` | `2,-1,1` | YES |
| ZUNION | `2,-1,1` | `0,0,0` | `2,-1,1` | YES |
| ZINTER | `2,-1,1` | `0,0,0` | `2,-1,1` | YES |
| ZDIFF | `2,-1,1` | `0,0,0` | `2,-1,1` | YES |
| ZUNIONSTORE | `1,-1,1` | `1,1,1` | `1,-1,1` | YES |
| ZINTERSTORE | `1,-1,1` | `1,1,1` | `1,-1,1` | YES |
| ZDIFFSTORE | `1,-1,1` | `1,1,1` | `1,-1,1` | YES |
| ZINTERCARD | `2,-1,1` | `0,0,0` | `2,-1,1` | YES |
| GEORADIUS | `1,-1,1` | `1,1,1` | `1,-1,1` | YES |
| GEORADIUSBYMEMBER | `1,-1,1` | `1,1,1` | `1,-1,1` | YES |
| XGROUP | `2,2,1` | `0,0,0` | `2,2,1` | YES |
| XINFO | `2,2,1` | `0,0,0` | `2,2,1` | YES |
| SSUBSCRIBE | `0,0,0` | `1,-1,1` | `0,0,0` | YES |
| SUNSUBSCRIBE | `0,0,0` | `1,-1,1` | `0,0,0` | YES |
| SPUBLISH | `0,0,0` | `1,1,1` | `0,0,0` | YES |
| EVAL | `3,-1,1` | `0,0,0` | `3,-1,1` | YES |
| EVALSHA | `3,-1,1` | `0,0,0` | `3,-1,1` | YES |
| EVAL_RO | `3,-1,1` | `0,0,0` | `3,-1,1` | YES |
| EVALSHA_RO | `3,-1,1` | `0,0,0` | `3,-1,1` | YES |
| FCALL | `3,-1,1` | `0,0,0` | `3,-1,1` | YES |
| FCALL_RO | `3,-1,1` | `0,0,0` | `3,-1,1` | YES |
| OBJECT | `2,2,1` | `0,0,0` | `2,2,1` | YES |
| MEMORY | `2,2,1` | `0,0,0` | `2,2,1` | YES |

PRE: **245 checked, 31 mismatches, exit 1**. Fresh POST at
`2026-10-07T17:25:22.048946+00:00` (01:25:22 on October 8 in Taipei):
**245 checked, 27 mismatches, 142 permission assertions PASS, exit 1**.
Complete fresh stdout: [registry-and-permissions.txt](docs/aclkeys/delivery-proof/registry-and-permissions.txt).
<!-- MISMATCHES_END -->

**Permission unit coverage.** `tests/aclkeys_unit.cc` includes the generated
metadata directly, initializes the real command registry without listeners or
workers, requires exactly 245 entries, and returns nonzero for any triplet
difference. Its permission checks use independent expected key indexes and
replace every actual key in turn with `outside:denied`, checking both denial
and the denied argument index. They cover both timeout values for
BLPOP/BRPOP/BZPOPMIN/BZPOPMAX, BLMPOP/BZMPOP, BLMOVE/BRPOPLPUSH,
XREAD/XREADGROUP, and keyless WAIT/WAITAOF; they also cover counted script and
function keys, set/zset combinations, GEO/SORT destinations, subcommands and
keyless HELP, sharded pubsub channels, and alternating MSET key/value arguments.
The fresh run uses the final POST objects. Earlier PRE and both namespace
variant evidence remains in `docs/aclkeys/*registry.txt` and `*permissions.txt`;
PRE's permission control fails immediately on `BLPOP`, denied argument 3.
The retained metadata coverage check reports 245 commands in 341 generated
rows, 18 covered generator sources, no orphans, and byte-identical regeneration.

**Strict witness and differential scope.** The existing
`docs/flakeaudit/acl-witness.patch` is applied by the production lane's earlier
commits. `tests/acl.py` cleans `block:k`, records the authenticated client's
ID, requires that exact `CLIENT LIST ID` row to contain `flags=b`, then revokes
`~block:*`, pushes a value, and asserts the exact post-wake denial. A missing
parking window remains a failure. The delivery wrapper runs that unchanged
battery and only traces its observed CLIENT LIST replies and assertions,
including the blocked client's raw wire reply; it does not replace assertions.

`tests/_differ_aclkeys.py` verifies that its oracle identifies as vanilla Redis
7.4.10. For `~block:* +@all`, each of BLPOP, BRPOP, BLMPOP, BZPOPMIN and
XREAD BLOCK with timeout `0` and `1` must return seeded data on both servers.
The outside-pattern variant must return exactly
`-NOPERM No permissions to access a key\r\n` on both, and both allowed and
outside-pattern `COMMAND GETKEYS` replies must match byte-for-byte and match
independently constructed RESP arrays. The timeout matrix tests admission with
ready data: XREAD's `1` is one millisecond, not one second. A separate zero-timeout
loop requires each of the five commands to park on **both** servers and then
return the same wake result, followed by an exact PONG to detect extra replies.
One successful leg therefore reports 10 admitted cases, 10 denied cases,
20 GETKEYS comparisons and 10 witnessed parks (five per server).

The focused differential harness runs the single suite `aclkeys`, one name per
line. Its current permanent-seed policy requires `7`, `19`, `20`, `23`; the
suite itself is deterministic. An entire successful focused invocation has
eight legs: four seeds under each atomic mode. The old
`docs/aclkeys/focused-seeds.txt` contains only `7` and is not used for this
resume because it no longer satisfies that harness policy.

**Wake-path review: remaining limits, not passing claims.**

| Family | Source review |
|---|---|
| BLPOP/BRPOP/BLMPOP, BZPOPMIN/BZPOPMAX/BZMPOP, XREAD/XREADGROUP | An op retaining `BlockingState` reaches `blocking_retire` (`src/cmd/blocking.inc:1419`), which invokes `acl_recheck_blocking` at line 1431. The latter reloads current permissions, clears the existing reply, and writes a denial. The strict live revoke/wake witness is BLPOP only. |
| BLMOVE/BRPOPLPUSH | `blocking_resume_move_impl` transfers the blocking state to `ScatterState::blocking_origin` and detaches the original blocking state (`src/cmd/blocking.inc:1347`). The IO retire callback selects its scatter branch; `xshard_retire` invokes `blocking_scatter_retire`, which has **no ACL recheck**. This is a source-identified revocation gap, unchanged by this lane, not a demonstrated live pass. |
| WAIT | Keyless admission is covered by the unit. `IoLoop::deferred_timer_pass` (`src/core/io_loop.h:5359`) writes the reply and clears blocked state without invoking the ACL recheck, so command-permission revocation during the wait lacks the collection commands' recheck. This is a source finding, not a live differential result. |
| WAITAOF | Keyless admission is covered. The current handler (`src/cmd/server_tail.cc:186`) returns immediately for `numlocal=0` and explicitly rejects the unimplemented `numlocal>0` wait; there is no implemented WAITAOF parked wake path to certify. |

The collection-command ACL recheck is at reply retirement, after owner-side
completion. The strict witness verifies parking and the denied reply; it does
**not** establish that revocation prevented a pop, destination mutation, or
consumer-group side effect. The resumed move path and WAIT path above must not
be represented as fixed by the BLPOP result. No live tests of those additional
revocation/side-effect cases were added in this delivery-only resume.

**Body audit.** The saved final audit compares PRE/POST object bodies in both
`tomo` and `tomo_db0` namespaces. All **1,496/1,496 selected hot bodies** and
**1,213/1,213 command handlers** have identical **raw object bytes**, as well
as equal resolved relocation identities. Thus the ordinary default-user
dispatch has no changed body in that inventory. Across all 17,015 inventoried
bodies, 16,994 are equal after relocation resolution; 21 are changed/added/removed
within the existing ACL objects. Six further bodies live in the new ACL-key
objects. Every one is listed below. Counts are static instruction counts,
not instructions/op or a performance verdict.

There are also **54 object bodies whose only raw differences are address
displacements**, all in the two ACL objects. These include `acl_dispatch_entry`,
`acl_check_queued`, and `acl_recheck_blocking` in both namespaces. Their opcodes
and resolved targets compare equal. The complete symbol-level list and reason
is in [delivery-body-details.md](docs/aclkeys/delivery-body-details.md); the
original evidence is [bodies.json.gz](docs/aclkeys/final-body-audit/bodies.json.gz).
This is an object-body proof, not a claim that final linked addresses or all
bytes in the two ELF files are identical.

Seven of the 21 changed bodies are cold code-generation drift outside key
extraction. This means the stronger requirement that **only** ACL key-extraction
bodies change is not fully satisfied. The changed DB0 `pubsub_finish_pending`
copy is discarded by the linker; the retained copy comes from the unchanged
`db0/src/main.o`, as established by the SHA-identical relink/map in
[pubsub-link-selection.txt](docs/aclkeys/final-body-audit/pubsub-link-selection.txt).
The other cold differences are retained as unresolved code-generation drift,
not relabeled as improvements. Only the modified `acl.cc` namespace variants
receive new compiler-budget overrides: 34630 and 34550, with inline-unit-growth
0. Existing budgets on other translation units were not changed.

<!-- BODY_TABLES_BEGIN -->
All 21 differences in existing `acl.o` objects:

| Namespace | Body | Bytes PRE → POST | Instructions PRE → POST | Reason |
|---|---|---:|---:|---|
| tomo_db0 | `acl_check_keys<acl_check_queued lambda> (.constprop.0)` | 1296 → 568 | 331 → 157 | ACL key extraction and its argument-view callback |
| tomo_db0 | `acl_check_keys<acl_dispatch_entry lambda> (.constprop.0)` | 1393 → 609 | 345 → 161 | ACL key extraction and its argument-view callback |
| tomo_db0 | `acl_check_keys<acl_recheck_blocking lambda> (.constprop.0)` | 1393 → 609 | 345 → 161 | ACL key extraction and its argument-view callback |
| tomo_db0 | `acl_pattern_allowed (old anonymous-namespace body)` | 93 → 0 | 38 → 0 | ACL key-pattern predicate moved to aclkeys.cc |
| tomo_db0 | `IoLoop::pubsub_finish_pending` | 3398 → 3398 | 765 → 769 | Unresolved cold code-generation drift in the changed ACL TU; this object copy is discarded at link |
| tomo_db0 | `std::__adjust_heap<AclLogEntry, acl_reply_log comparator> (.isra.0)` | 2816 → 2815 | 667 → 665 | Unresolved cold code-generation drift in the changed ACL TU |
| tomo_db0 | `acl_check_keys<acl_check_queued lambda> argument callback ::_FUN` | 0 → 23 | 0 → 8 | ACL key extraction and its argument-view callback |
| tomo_db0 | `acl_check_keys<acl_dispatch_entry lambda> argument callback ::_FUN` | 0 → 70 | 0 → 20 | ACL key extraction and its argument-view callback |
| tomo_db0 | `acl_check_keys<acl_recheck_blocking lambda> argument callback ::_FUN` | 0 → 70 | 0 → 20 | ACL key extraction and its argument-view callback |
| tomo | `acl_check_keys<acl_check_queued lambda> (.constprop.0)` | 1101 → 513 | 291 → 142 | ACL key extraction and its argument-view callback |
| tomo | `acl_check_keys<acl_dispatch_entry lambda> (.constprop.0)` | 1261 → 577 | 318 → 156 | ACL key extraction and its argument-view callback |
| tomo | `acl_check_keys<acl_recheck_blocking lambda> (.constprop.0)` | 1261 → 577 | 318 → 156 | ACL key extraction and its argument-view callback |
| tomo | `acl_pattern_allowed (old anonymous-namespace body)` | 93 → 0 | 38 → 0 | ACL key-pattern predicate moved to aclkeys.cc |
| tomo | `acl_apply_command_rule (.constprop.0 .isra.0)` | 2234 → 2253 | 500 → 506 | Unresolved cold code-generation drift in the changed ACL TU |
| tomo | `acl_apply_command_rule (.constprop.0 .isra.0) cold clone` | 63 → 63 | 13 → 13 | Unresolved cold code-generation drift in the changed ACL TU |
| tomo | `acl_command_entry` | 12700 → 12700 | 2517 → 2517 | Unresolved cold code-generation drift in the changed ACL TU |
| tomo | `acl_command_entry cold clone` | 685 → 685 | 129 → 129 | Unresolved cold code-generation drift in the changed ACL TU |
| tomo | `std::swap<AclLogEntry>` | 851 → 851 | 204 → 204 | Unresolved cold code-generation drift in the changed ACL TU |
| tomo | `acl_check_keys<acl_check_queued lambda> argument callback ::_FUN` | 0 → 23 | 0 → 8 | ACL key extraction and its argument-view callback |
| tomo | `acl_check_keys<acl_dispatch_entry lambda> argument callback ::_FUN` | 0 → 68 | 0 → 19 | ACL key extraction and its argument-view callback |
| tomo | `acl_check_keys<acl_recheck_blocking lambda> argument callback ::_FUN` | 0 → 68 | 0 → 19 | ACL key extraction and its argument-view callback |

All six bodies in new `aclkeys.o` objects (PRE has no such body):

| Namespace | Body | POST bytes | POST instructions | Reason |
|---|---|---:|---:|---|
| tomo_db0 | `acl_check_metadata_keys cold clone` | 135 | 31 | Exception cleanup for metadata extraction |
| tomo_db0 | `acl_pattern_allowed` | 109 | 40 | Moved key-pattern predicate |
| tomo_db0 | `acl_check_metadata_keys` | 990 | 214 | Shared metadata-backed ACL key extraction |
| tomo | `acl_check_metadata_keys cold clone` | 132 | 31 | Exception cleanup for metadata extraction |
| tomo | `acl_pattern_allowed` | 109 | 40 | Moved key-pattern predicate |
| tomo | `acl_check_metadata_keys` | 958 | 206 | Shared metadata-backed ACL key extraction |
<!-- BODY_TABLES_END -->

All audited struct sizes/member layouts are equal PRE/POST, including both
database variants, per
[layouts.json](docs/aclkeys/final-body-audit/layouts.json). `.text` changes from
7,812,565 to 7,811,022 bytes (POST is 1,543 bytes smaller). A size change is not a
measured speedup.

**Mainline measurement request.** Run the gate's existing 14-cell null and
matched-load sequential ABBA PRE/POST comparison with its current cell matrix
and instrumentation, covering both thread modes and the ordinary default-user
workload. Rate and cycles/op at matched offered load decide; IPC and retired
instructions/op explain any difference. No rate, cycles/op, or latency result
was collected by this delivery. Do not infer no regression from static counts.

`build/aclkeys/PAD-B/tomokv` is explicitly **kind (B), inverse control**:
candidate behavior plus 1,543 bytes of padding restoring PRE's total `.text`
size. It is **not** a kind (A) PRE-behavior twin. It preserves POST's GNU
properties and all 9,194 existing text-symbol addresses/sizes; it does not
restore PRE's per-function addresses or data layout. Use it as an additional
size control if the PRE/POST result moves. The bytes/layout evidence and control
limits are in [artifacts.json](docs/aclkeys/final-body-audit/artifacts.json).
There is no PAD-A artifact and no measurement acceptance claim for PAD-B.

**Rows: +0 quick / +0 full (+0/+0).** No gate row was added, renamed, or retired;
`git diff d81b6d3a2 HEAD -- tests/gate.sh` is empty. The strict witness repairs
the existing `ACL battery (atomic off)` / `(atomic on)` rows at lines 2150/2157,
collected by `auth` at line 3294 before the quick exit at 3361. The new `aclkeys`
differential suite is a child of the existing differential folds at lines
3393/3404, after the quick exit, not a new public row. The `aclsel` battery
already appears in `FEATURE_BATTERIES` at line 769. The serverless cross-check
has a build target but is **not** added as a gate row. `EXPECT_QUICK=500` and
`EXPECT_FULL=517` at lines 279/280 were inherited from the merged baseline and
were not edited by this lane; those counts remain unchanged.

**SHA-256, verified in the fresh delivery.**

```text
431d3d2d8da4d7a4f633ae7a2594f15b046eef1e93d5341ad4093eb62247915a  build/aclkeys/PRE/tomokv
833685b6244322188b5412af343b355fc0347aed00a755776389be0f73a38651  build/aclkeys/POST/tomokv
833685b6244322188b5412af343b355fc0347aed00a755776389be0f73a38651  build/tomokv
e94e8fdf8a2fa7507b9ffb097fe2dbbea0cb3816f3af1a9c86f7af9ba6e303ce  build/aclkeys/PAD-B/tomokv
```

**Exact delivery commands and evidence.** Commands run from the worktree root:

```sh
git merge origin/cpp
sha256sum -c docs/aclkeys/SHA256SUMS
cmp build/aclkeys/POST/tomokv build/tomokv
taskset -c 120-127 python3 docs/aclkeys/run-delivery-proof.py
git diff --exit-code d81b6d3a2 HEAD -- tests/gate.sh
grep -n -E 'ACL battery \(atomic|ACL recheck one-reply|FEATURE_BATTERIES=|^EXPECT_(QUICK|FULL)|if \[ "\$TIER" = quick|^collect_job (auth|differ)' tests/gate.sh
```

The delivery script records UTC start/end timestamps, full argument arrays,
explicit environment overrides and exit statuses in
[commands.jsonl](docs/aclkeys/delivery-proof/commands.jsonl). Its source records
the exact quiet-monitor API and retry schedule: the initial attempt plus up to
three retries at 200-second intervals, with each preflight using the existing
20-second CPU budget and ports 18540/18541. The unit runs on CPUs 112–127;
live target servers use CPUs 112–119, 16 shards and ratio 6:2. Battery clients
and the Redis oracle use CPUs 120–127. The owned-server harness verifies the
listening process and cleans up only its own children. Each witness boot has a
private data directory and ACL file.

For reproduction, these are the script's proof entry points. Only the unit ran;
the two witness commands and differential command below were **NOT EXECUTED**
because all quiet preflights refused:

```sh
taskset -c 112-127 build/aclkeys/POST/aclkeys-unit
# For each atomic mode, the recorded owned boot is followed by:
taskset -c 120-127 python3 docs/aclkeys/trace-witness.py 127.0.0.1 18540 /home/user/Projects/cx-aclkeys/build/aclkeys/delivery-proof/witness-atomic-0/users.acl
taskset -c 120-127 python3 docs/aclkeys/trace-witness.py 127.0.0.1 18540 /home/user/Projects/cx-aclkeys/build/aclkeys/delivery-proof/witness-atomic-1/users.acl
# With GATE_LOAD_CORES=120-127, GATE_DIFFER_ORACLE_CORES=120-127,
# GATE_DIFFER_OUT=/home/user/Projects/cx-aclkeys/build/aclkeys/delivery-proof/differ,
# GATE_DIFFER_PROOF_SUITES=/home/user/Projects/cx-aclkeys/docs/aclkeys/delivery-proof/suites.txt,
# GATE_DIFFER_PROOF_SEEDS=/home/user/Projects/cx-aclkeys/docs/aclkeys/delivery-proof/seeds.txt:
taskset -c 120-127 bash tests/differ_gate.sh build/aclkeys/POST/tomokv 18540 18541 112-119 6:2
```

The commands file distinguishes commands actually executed from any live branch
refused by preflight. A refused live branch is not a passing witness or
differential result. The runner intentionally returns nonzero when any recorded
proof is red, including the 27 registry mismatches.

The prior literal audit searched `tests/` with **grep**, using 807 patterns for
literal/lowercase/uppercase, Python escapes, hexadecimal escapes and octal
escapes; it retained 134,043 matched lines compressed in
`docs/aclkeys/text-audit-after.txt.gz`. Its command and inventory are in
`docs/aclkeys/text-audit.json`; no production reply text changed. This resume
edits delivery documentation/tracing only and leaves every existing test string
and assertion unchanged. The retained serverless controls report 6 witness
tests, 24 differential controls and 11 flakeaudit controls passing; they are
earlier evidence, not fresh live results. No push was performed.
