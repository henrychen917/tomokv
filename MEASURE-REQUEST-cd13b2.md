Lane cd13b2 — integrate cd13b's differential properties with landed cmdmeta

Started from `cx-cd13b` at `4184ed3f20f9c450971bef2a620b2e55cc87980d`.
The required `git log --oneline origin/cpp | head -n 12` contained
`ca4eeb371 Merge cmdmeta (324bf529f) into cx-final`; origin/cpp was
`08a68fcba`. Read both `MEASURE-REQUEST-cd13b.md` and the landed
`MEASURE-REQUEST-cmdmeta.md`. No push.

`git merge origin/cpp` produced one conflicted file, `tests/differ.py`, with
two conflict regions: the ACLCAT insertion and cmdmeta's final coverage guard.
The merge is `8c8ffd6f0c8a0b4243a3706f4b8a1dd4ffedbd94`. Final test placement
is committed in `f32b2b2c6`.

The landed `run_cmdmeta_suite` is **byte-for-byte unchanged**. It retains the
whole-surface set comparisons, explicit FLIP exception, every category check,
the INFO/DOCS checks for all 39 absent names, direct INFO/key-intent comparisons,
and every coverage guard. The raw-wire `aclcat_property` now runs in the existing
`geo` leg, using its target/oracle connections and selected RESP version. This
keeps cmdmeta's parsed-reply offline fixture intact without editing that fixture.
It still requires exact `*0\r\n` for an unknown category, identical command sets
for `string`, `STRING`, and `StRiNg`, and exactly eight completed probes across
the two peers. Failure to execute all eight remains a failure.

All original GEO properties remain, including the cross-owner STORE, STOREDIST,
and GEOSEARCHSTORE LFU/encoding assertions. `tests/cd13b_wire.py`,
`tests/cd13b_checks.py`, and `tests/cd13b_unit.cc` are unchanged from cd13b.
The source comparison and suite-inventory proof are recorded in
[docs/cd13b2/source-proof.log](docs/cd13b2/source-proof.log).

Production identity:

| Build | SHA-256 |
| --- | --- |
| Starting cd13b POST | `ff37e6c4c1d6a192161b1b8e314a46413beb97e3cb02e01d60c6b9b0c6d02e87` |
| Merged `build/tomokv` | `eda318b9e356d172ce116fc7d48db491d4260d6eb286b7a229a7ed83ce2f1d45` |

`taskset -c 112-127 make -j12` passed with the default release settings; its log
is `build/cd13b2/make.log`. The hash legitimately changes because the merge brings
in landed psfix, storesize5, and cmdmeta's generated metadata, including their
Makefile changes. This lane made no production edits after that merge:

```sh
git diff 8c8ffd6f0c8a0b4243a3706f4b8a1dd4ffedbd94..HEAD -- src Makefile
# EMPTY
```

The empty output is retained as
[docs/cd13b2/production-after-merge.diff](docs/cd13b2/production-after-merge.diff).
The original POST artifacts are preserved at `build/cd13b2/cd13b-original-POST`.
`build/cd13b/POST` now contains copies of the merged production objects and binary;
the serverless fixtures were rebuilt against those objects, so the following
checks exercise the merged code rather than stale cd13b binaries.

Proofs, all confined to CPUs 112–127:

- `python3 tests/differ.py --list-generators`: **43 unique suites**, one per line;
  every previous cd13b suite is retained, with the landed `psfix` suite added.
  [Inventory](docs/cd13b2/generators.log).
- `python3 tools/gen_cmdmeta.py --redis-root /home/user/Projects/redis --check
  src/cmd/cmdmeta_generated.inc`: **exit 0**.
  [Receipt](docs/cd13b2/cmdmeta-generated-check.log).
- `python3 tests/cmdmeta_coverage.py --redis-root /home/user/Projects/redis`:
  **245 registered commands, 341 generated rows, no orphans, byte-identical
  regeneration**. [Receipt](docs/cd13b2/cmdmeta-coverage.log).
- `REDIS74_ROOT=/home/user/Projects/redis python3 tests/cmdmeta_test.py`:
  **6/6 pass**, including rejection of every orphan and the other deliberate
  corruptions. [Receipt](docs/cd13b2/cmdmeta-offline.log).

The live proofs reused `tests/differ_gate.sh`'s guarded boot, vanilla-oracle
identity check, exact-PID ownership and cleanup verbatim. The narrow runner is
[docs/cd13b2/run-live.sh](docs/cd13b2/run-live.sh); it invokes the requested legs
without the gate matrix or seed-history writes. Target CPUs are **112–119**,
oracle CPUs **120–123**, and client CPUs **124–127**. Both target shapes use
16 shards, 16 databases, and atomic=1; split uses ratio 6:2, and fused uses
`--thread-mode fused --read-local 1`. Every leg uses seed 7.

The oracle was `/home/user/Projects/redis74/src/redis-server`, confirmed vanilla
**Redis 7.4.10**, SHA-256
`ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`.
Target and oracle stopped cleanly; both ports were free afterward.
[Boot, identity, eight verdicts and cleanup](docs/cd13b2/live.log).

| Shape | Protocol | cmdmeta | geo |
| --- | --- | --- | --- |
| split | RESP2 | 4,475 ops, 0 diffs, PASS | 4,951 ops, 0 diffs, PASS |
| split | RESP3 | 4,475 ops, 0 diffs, PASS | 4,951 ops, 0 diffs, PASS |
| armed-fused | RESP2 | 4,475 ops, 0 diffs, PASS | 4,951 ops, 0 diffs, PASS |
| armed-fused | RESP3 | 4,475 ops, 0 diffs, PASS | 4,951 ops, 0 diffs, PASS |

Each cmdmeta receipt records **96 retained pipe names, 21 categories, 78
absent-name INFO/DOCS checks, 8 pattern filters, 3 module filters, 2,125 INFO
and 2,075 key-intent comparisons**. Each GEO receipt shows both peers returning
the exact unknown-category frame and matching 22-command mixed-case string
sets, plus all three cross-owner GEO witnesses. GEO reports zero clock
tolerances. Individual logs and executed-command coverage JSON are under
`docs/cd13b2/{split,armed-fused}-{cmdmeta,geo}-resp{2,3}.*`.

The requested representative serverless cells both passed with zero failures:

```sh
taskset -c 112-127 python3 tests/cd13b_checks.py run \
  --namespace multi --mode split --atomic 1 --resp3 0 --notify 0
taskset -c 112-127 python3 tests/cd13b_checks.py run \
  --namespace db0 --mode fused --atomic 0 --resp3 1 --notify 1
```

Receipts: [split](docs/cd13b2/unit-split.log),
[fused](docs/cd13b2/unit-fused.log). Each proves different source/destination
owners for all three GEO operations and preserves the warmed FREQ value 31.
Python compilation, proof-runner shell syntax, and `git diff --check` passed.

Rows **+0 quick / +0 full**. The existing differential rows are collected at
`tests/gate.sh:3387` and `:3398`, both after the quick-tier exit at `:3355`.
No suite or row was added by this lane. `tests/gate.sh` is identical to landed
origin/cpp: **EXPECT_QUICK=500 / EXPECT_FULL=517 remain unchanged**. No fixture
edits. No benchmark or full gate was run, and no performance conclusion is
claimed; the maintainer retains full-gate acceptance. This test-only integration
adds no measurement arm or PAD requirement.
