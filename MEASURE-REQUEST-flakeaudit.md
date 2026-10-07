# flakeaudit — gate stimulus audit and test-only repairs

Worktree `/home/user/Projects/cx-flakeaudit`, branch `cx-flakeaudit`.
The resume recovered and committed the existing audit, then started the
requested six-run campaign. Live results are being collected below; a
partial gate is not a full 517-row landing receipt or a performance result.

## Scope and inventory

[inventory.md](docs/flakeaudit/inventory.md) lists **all 517 public row
occurrences**, preserving duplicate labels, collection order, source lines
and the independent fixture's **500 quick / 517 full** split:

| Class | Rows |
|---|---:|
| DETERMINISTIC | 229 |
| BOUNDED-WITNESSED | 175 |
| LOTTERY | 113 |

A battery receives its worst remaining class: fixing one setup race does
not certify its unrelated timing checks. The source-only generator checks
the fixture without executing shell declarations or changing fixture data.
`rows.json` is the machine-readable inventory; `source-reviews.json` holds
the review reasons. The inventory also expands all **44 differential suites,
one per line**, with the same discovered order as `--list-generators`, and
records the folded mode-equivalence child. These are not additional rows.

The resumed review corrected the TLS optional auth-only classification
(that invocation does not run the full handshake/teardown battery), added
the previously missing differential expansion, and recorded that the RYOW
contention leg writes `rk*` in its workers but `own*` in the foreground.
That leg does not exercise the same-key contention its comment advertises.

## Implemented repairs

These repairs affect **34 existing public row occurrences**, listed exactly
in [changed-rows.json](docs/flakeaudit/changed-rows.json). Dependent recovery
rows are also exercised by the complete selected jobs.

| Existing row family | Occurrences | Before | After |
|---|---:|---|---|
| DEBUG toggle/reload battery | 1 | RELOAD could collide with placement movement. | Existing `debug_load` observes FLIP and LB idle; only the exact FLIP refusal gets the existing bounded retry. |
| typed snapshot round-trip incl stream | 1 | Bare CLI RELOAD after SAVE. | `tests/debug_load.py` exposes that same witnessed helper to the shell; the exact snapshot comparison remains. |
| multidb (both modes × read-local × atomic) | 8 | Bare RELOAD and LOADAOF. | Both restores use the existing placement witness; exact namespace datasets still must match. |
| AOF rewrite atomic/stage/corruption matrix, both engines | 2 | Bare CLI LOADAOF on the restarted process. | The shell entry point requires placement idle and exact successful admission. Published rewrite-stage controls remain intact. |
| limits, split and armed, both atomics | 4 | Sleep 100 ms after closing an admitted client. | Record its CLIENT ID and require that exact client to disappear before using the reclaimed slot. |
| climon2, split and armed, both atomics | 4 | Sleep 300 ms before each CLIENT UNBLOCK. | Require the exact target ID's blocked flag before the TIMEOUT and ERROR variants. Both exact wire replies remain. |
| tracking, split and armed, both atomics | 4 | Sleep 400 ms after resetting the redirect connection. | Require disappearance of the exact redirect target before the invalidating write. |
| epoll directed correctness, 1s and 2s | 2 | A five-second BLPOP was assumed parked after 50 ms. | An indefinite BLPOP must publish its blocked CLIENT ID before LPUSH. Socket bounds and the existing 25-ms wake assertion remain. |
| AOF byte-exact + script groups + DEBUG LOADAOF, both engines/atomics | 4 | Bare raw-wire LOADAOF, including corrupt-tail arms. | Same-connection placement observer and exact FLIP-only retry; successful and intentional corrupt-tail replies remain byte-exact. |
| AOF everysec write gate + idle sync fired, both engines | 2 | Sleep 1.25 seconds, then sample fsync once. | Retain the policy-age lower bound and require an actual fsync counter advance within a bound. |
| snapshot concurrent cut, both engines | 2 | BGSAVE reply was printed without checking; completion loop could silently time out. | Require idle first, exact acceptance, then valid published idle before the deadline. Post-cut mutations and exact recovered snapshot are unchanged. |

Implementation commits: `74181436f`, `0272fcbd4`, `377951b29`.
`eae4e0e86` removed the separate, failing ACL experiment from executable
tests and retained its patch/evidence. `cd91e2c39` records the campaign.
The inventory recovery is `41f49e78b`; differential expansion and corrections
are `13a6ef95e`.

## ACL witness: real defect and a vacuous old test

[acl-witness.patch](docs/flakeaudit/acl-witness.patch) is deliberately **not
applied**. Its relevant TomoKV arm cleans the key, records the client's ID,
and requires `CLIENT LIST ID` to publish `flags=b` before permissions are
revoked and the list is pushed. Both saved runs fail that requirement:

- [atomic off](docs/flakeaudit/evidence/acl-atomic-off.txt)
- [atomic on](docs/flakeaudit/evidence/acl-atomic-on.txt)

The client stays `flags=N`, `cmd=blpop`; its early reply is
`NOPERM No permissions to access a key`. This is **a production admission
defect, not an unlucky park race**. `src/cmd/acl.inc:567` expands every
negative `last_key` to `argc - 1`, and the runtime BLPOP command spec at
`src/cmd/t_list.cc:952` uses `last_key=-1`. Thus `BLPOP block:k 0` checks the
timeout `0` as a key against `~block:*`. The old test's expected post-wake
NOPERM is already present before revocation, so it passes without entering
the intended window. Generated command metadata separately records the
correct timeout-excluding `last_key=-2` at `cmdmeta_generated.inc:290`.

Mainline should assign a production correctness fix for blocking-command
key extraction, review the related blocking families, and then apply the
strict ACL witness with the fix. Require admission/parking, revoke, wake,
and the exact denied reply in both atomic modes. Do not grant the numeric
timeout as a fake key, delete the witness, or accept an unparked client.
The `aclsel.py` part is retained as the analogous Redis selector witness;
TomoKV's selector-refusal branch returns before that code.

The patch is separate because applying it alone intentionally makes two
existing gate rows red. Repairing production ACL semantics is outside the
test-only repairs, and no cold DEBUG hook is needed for this diagnosis.

## Proof command and evidence

The user's resume explicitly authorizes these gate runs on CPUs 112–127.
`git fetch origin cpp` followed by `git merge --no-edit origin/cpp` before
the campaign reported already up to date at **f053e5930**. The resumed proof
starts at `41f49e78b`; subsequent audit/report commits change no executable
test or production source. Every repetition saves its revision and mainline
revision and checks the same server SHA before/after.

```bash
bash docs/flakeaudit/repeat.sh
```

The script runs six serial selections with:

```bash
GATE_ONLY_JOBS='auth netio-1s netio-2s snapshot-epoll snapshot-uring aof-epoll aof-uring multidb-1s-0-0 multidb-1s-0-1 multidb-1s-1-0 multidb-1s-1-1 multidb-2s-0-0 multidb-2s-0-1 multidb-2s-1-0 multidb-2s-1-1 feature-split-0 feature-split-1 feature-armed-0 feature-armed-1' \
taskset -c 112-127 tests/gate.sh iteration \
  --server-cores 112-119 --load-cores 120-127 \
  --server-smt '' --load-smt '' --ports 18340-18342
```

The gate adds required builds and uses 16 shards, eight server cores,
ratio 6:2 for split boots, and one correctness slot. No ABBA/NIC measurement
is requested or claimed.

<!-- PROOF_RESULTS_BEGIN -->
Six-run live campaign: **2/6 complete; IN PROGRESS**.

Every completed clean selection includes all 34 changed row occurrences. The table counts complete selected jobs and prerequisites; it is not a full-gate receipt.

| Run | Gate artifact | Start–end (Asia/Taipei) | Rows ok / FAIL | Changed rows passed |
|---:|---|---|---:|---:|
| 1 | `gate-run.vuf9be` | 21:14:52–21:26:15 | 236 / 0 | 34 / 34 |
| 2 | `gate-run.mSjyJU` | 21:26:16–21:37:44 | 236 / 0 | 34 / 34 |

Tracked [results and provenance](docs/flakeaudit/evidence/proof/results.json) link each run to its revision, unchanged server hash, ledger, phase timestamps and geometry. The adjacent run directories retain the complete gate log and the relevant battery logs. `archive_proof.py` refuses changed executable sources and cross-checks every changed row's multiplicity.
<!-- PROOF_RESULTS_END -->

The pre-resume campaign is preserved under
`build/flakeaudit/proof-before-resume`: its first run reported 242 ok / 2
FAIL while the strict ACL witness was applied; the second has no completed
verdict. Neither counts toward the fresh sequence. The two ACL failure
logs remain tracked separately. The resume does not silently count reruns
of the unmodified ACL test as proof of blocked-client permission rechecking.

Serverless validation on the merged tree:

- `python3 tests/flakeaudit_test.py -v`: **11/11 PASS**. Missing/wrong/late
  client state, absent fsync, invalid or never-completing save state, data
  errors, and repeated load refusals fail. Exact load corruption bytes and
  the fsync minimum age stay enforced.
- `python3 tests/debug_load_test.py -v`: **13/13 PASS**. Existing placement
  and fresh-expiry-window negative controls remain intact.
- Changed Python files compile; changed shell scripts pass `bash -n`;
  `git diff --check` is clean. The source generator reproduces all 517
  fixture-checked rows and all 44 differential suite names.

The [grep audit](docs/flakeaudit/evidence/text-audit.log) covers changed
lines and load/client/persistence literals in plain and escaped encodings
across `tests/` (386 patterns, 1,716 matching lines). Remaining sleeps and
raw commands are source-classified, not blanket-deleted.

## Remaining rows and limitations

[remaining.md](docs/flakeaudit/remaining.md) maps **all 113 LOTTERY
occurrences into 41 mechanisms**, with their public row ordinals and the
required change. The inventory contains every exact row name and source
line, including residual lotteries in partially repaired batteries.
Reasons include held-command schedules, controllable expiry/configuration
publication, valid conflicting-write oracles, sampler witnesses, and
separating performance thresholds from correctness stimuli.

Two identified shell fixes remain **local follow-ups, not design blockers**:
the armed feature lifetime high-water counter after RESETSTAT (`gate.sh:816`)
and a framed RESP read for the live kTLS gauge (`gate.sh:2736`). They were
outside the recovered implementation; the resume prioritizes the requested
six-run proof of that implementation. Thus this delivery does **not** claim
that every locally repairable lottery in the original broad task is fixed.
The remaining register also records the ACL production defect and the
RYOW workload mismatch explicitly.

## Row and production identity

**+0 quick / +0 full. EXPECT stays 500 / 517.** No EXPECT or fixture edits.
The new serverless unit is standalone, not a new gate row. The in-place
typed-reload row is declared at `gate.sh:2167`; all affected job collections
are above the quick-tier exit at `gate.sh:3365` (feature 3257/3262, netio
3221, auth 3294, snapshot 3296, AOF 3307, multidb 3338).

Production sources, headers, Makefile, layout and compiler flags are
unchanged; [production.diff](docs/flakeaudit/evidence/production.diff) is
empty against fetched mainline. There is no new DEBUG hook, PRE/POST/PAD
arm, hot-body audit or performance claim.

Proof server SHA-256:

```text
070e1e958ec0f3b7ceb0ec345139a400b4144d52c49f3faf64b627950bf21ae4
```

Commits stay on `cx-flakeaudit`. No push.
