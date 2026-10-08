# flakeaudit3 — landing-driven test lottery audit

Worktree/branch: `/home/user/Projects/cx-flakeaudit3`, `cx-flakeaudit3`.
Merged `origin/cpp` at `dab740964` before implementation and again before proof.
Implementation: `368f92df7`; audit/control evidence: `5be719018`.

**Status: test repair implemented; selected live proof REFUSED; full admission pending.**
No compiler, server or gate has started. The proof table records admission separately
from gate verdicts.
This is test-only work: no performance, binary-layout or PRE/POST/PAD claim.

| Changed public rows | PRE mechanism | POST witness and preserved assertions | Proof IDs |
|---|---|---|---|
| Redis 7.4 differential matrix: original 515, current 517; gate.sh collection line 3434 | CD13b GEO assumes unchanged source/destination owners after STORE; key balancing can move the source during the window | All three verbs check exact `:2`, integer FREQ greater than the measured initial FREQ, listpack encoding, and now exact destination members. Only unarmed setup or a changed route re-arms fresh keys. Acceptance still requires distinct owners with unchanged before/after owner and migration tuples. One 30-second failure budget per side/verb; no semantic failure is retried. | `geo-controls`; `mutation-controls`; selected campaign below |
| Redis 7.4 differential matrix (armed fused + read-local): original 516, current 518; collection line 3445 | Same helper and lottery, including the observed atomic=1 seed=23 source move 0→6 | Same repaired helper; default balancers stay enabled. `key-lb` is immutable at runtime, as verified in the current CONFIG registry and setter. | Same controls; both armed differential jobs below |

The tests retain the 4096-read priming ceiling, 4096-candidate route-search ceiling,
LFU arming increase of at least three, all original STORE result assertions, and
cleanup/configuration restoration. Valid data from a moved arm is still inspected;
it cannot satisfy the stable cross-owner route witness. Exhaustion fails, including
an otherwise valid STORE whose checks finish after the budget. The arbitrary
three-attempt limit is replaced by the shared deadline, following landed GT16.

## Live lotteries and register

- **GEO, 2026-10-08 09:24, armed-fused a1 seed 23: A, repaired here.** The exact
  incident is maintainer-supplied. The archived mkprobe landing log retains the
  `gate-run.I4MSGw` failure transition, but no original GEO per-suite transcript
  was present in the specified archives. The report distinguishes those sources.
- **PSFIX, 2026-10-08 05:08, split a0 seed 91: B/W14, unchanged.** Both-peer
  `rdb_bgsave_in_progress:0` polling already exists. Current snapshot admission
  also returns Busy for placement transitions and draining shutdown-snapshot
  holds; the command maps these to the background-save error. A completion poll
  cannot distinguish the rejected request's reason or reserve admission. A
  generic Busy retry could conceal an admission defect. Exact SAVE/BGSAVE replies,
  `rdb_saves + 1`, stable second read and completion status remain unchanged.
  [Original transcript](docs/flakeaudit3/evidence/psfix-a0-s91-original.txt),
  [current source evidence](docs/flakeaudit3/evidence/psfix-admission-source.txt).
- **GT16: A, already landed.** Retained its quiescence-gated, time-budgeted hold;
  the 21 current controls pass. The refused OPRDHt gate's old three-arm failure is
  archived, not counted as a new defect in the landed implementation.
- **ACL admitted-wake failures: D, excluded as requested; aclkeys3 owns them.**
  Both refused gates and every supplied per-seed receipt are committed. The earlier
  ACL key-extraction failure is also a production defect, not a timing repair.
- **Withdrawn held-EXEC repair: excluded as requested.** The restored battery
  remains B/W16; this pass does not revive the incorrect scatter-latch premise.
- Other history labels are dispositioned in the
  [complete register](docs/flakeaudit3/remaining-v3.md): already-landed LRU,
  tracking and AOF witnesses; servertail B/W1; lane build/PRE-control failures;
  and explicitly unidentified history-only failures. No unexplained assertion
  is silently waived. The 18 final copied landing ledgers themselves contain
  zero FAIL rows; their historical failure summaries are preserved separately.

The original 42 mechanisms retain occurrence counts **A=35 / B=58 / C=22 / D=2**
(117 distinct rows). Including GT16: **A=36 / B=58 / C=22 / D=2** (118).
GEO and PSFIX overlap the B differential aggregate rows and are not counted twice.
Mechanism counts for the original 42: **15 / 18 / 8 / 1**. Including the three
explicit, overlapping addenda: **17 / 19 / 8 / 1** (45 entries).
[Machine-readable triage](docs/flakeaudit3/triage.json). All W1–W16 requirements
and unchanged mixed-family thresholds remain in the register.

## Proof and receipts

Required: six serial runs of these **whole** gate jobs, with all suites/seeds:

```text
differ-split-0
differ-split-1
differ-armed-0
differ-armed-1
```

Then one full `iteration`. Server CPUs **112–119**, load CPUs **120–127**,
build CPUs **112–127**, no SMT, ports **18340–18342**, gate geometry **16 shards,
6 io + 2 ex**. One slot keeps the jobs serial. No focused suite/seed filter is
used. The [wrapper](docs/flakeaudit3/proof.py) refreshes the binary after admission,
preserves every gate log/ledger/text artifact, stops on any failed run, and
checks the binary digest before/after each gate. Quiet refusal gets only the
requested initial screen plus three retries spaced over ten minutes.

```sh
python3 docs/flakeaudit3/proof.py selected
python3 docs/flakeaudit3/proof.py full
```

| Campaign | Admission / live result | Run IDs |
|---|---|---|
| `selected-20261008T234356Z` (six requested) | **REFUSED** after four screens over ten minutes; **0/6 runs**, wrapper rc=3, no gate verdict | None |
| `full-20261008T235415Z` (one requested) | Admission in progress; first screen refused | None |

[Machine-readable proof summary](docs/flakeaudit3/evidence/proof-summary.json).
Selected screens observed 16.16, 16.31, 16.30 and 16.32 CPU-seconds against the
unchanged 0.48-second quiet budget. These are failed preconditions, not gate FAIL
rows; a refusal does not count as a test run. The raw selected admission records
were committed in `08c095d6e`. Mainline was merged again before full admission
(`f7fc7ea1a`).

Serverless receipts, separate from the required live proof:

- [GEO](docs/flakeaudit3/evidence/geo-controls.log): 8 tests pass, including
  more-than-three invalid arms, never-open windows, source moves, same-owner
  collapse, migration-counter ABA and semantic errors on stable/moved routes.
- [Falsification](docs/flakeaudit3/evidence/control-results.json): PRE rejects
  legitimate movement; six in-memory guard-removal controls fail their intended
  assertions. No production or live mutant binary was built or run.
- [Differential controls](docs/flakeaudit3/evidence/differ-controls.log): 24 pass,
  including PSFIX exact save/count and admission-error controls.
- [GT16 controls](docs/flakeaudit3/evidence/gt16-controls.log): 21 pass.
- [Changed-text grep](docs/flakeaudit3/evidence/changed-text-search.json): old/new
  source lines and decoded, unicode-escaped, JSON-escaped and repr spellings
  searched throughout tests/. [46 suite names, one per line](docs/flakeaudit3/evidence/suites.txt).

**Rows +0/+0; EXPECT_QUICK=502 / EXPECT_FULL=519 unchanged.** The source inventory
counts rows before/after the actual quick-tier exit at line 3402; it is not a
partial-run tally. [Row-count receipt](docs/flakeaudit3/evidence/row-counts.json).

**Production diff against origin/cpp: empty (0 bytes), committed.**
[production.diff](docs/flakeaudit3/evidence/production.diff),
[base/digest/path receipt](docs/flakeaudit3/evidence/production-receipt.json).
Only two executable test files changed; the rest is audit/proof material.
