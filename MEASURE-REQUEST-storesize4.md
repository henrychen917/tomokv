# storesize4 — link storage regression units with the cold storesize boundary

Worktree `/home/user/Projects/cx-storesize`, branch `cx-storesize`, 2026-10-06.
Entry HEAD was `848fb3977`. `git merge origin/cpp` reported already up to date:
`b1d931ee2` was already merged by `f2a927f9b`. Implementation: `080a83f3f`.
No push. This lane changes test build inputs only.

**Complete:** all 12 existing storage regression rows passed, and the
`storesize published monitoring` row passed within a 24/24 selected gate run,
both using the requested CPUs and ports. Production bytes are unchanged.

## Failure and fix

The landing run `build/gate-run.BTFBOD/jobs/storage_units/` failed to link
`FlatStore::init_storesize`, `destroy_storesize`, `storesize_clear`, and
`storesize_replace`; the sidecar variant also missed `storesize_deadline`.
`tests_store_regression.o` and `src_cmd_t_hash_ttl.o` reference definitions
that storesize3 moved to `src/cmd/storesize.cc`. The small regression build
still linked only the fixture, `t_hash.cc`, and `t_hash_ttl.cc`.
The [original linker logs](docs/storesize4/before-gate-store-build.txt) and
[sidecar linker log](docs/storesize4/before-gate-store-sidecar.txt) retain that
negative evidence.

Exactly two source lists changed:

- `tests/gate.sh:1186`, the shared `store_build` source list: append
  `src/cmd/storesize.cc`. This fixes `store-objects`, `store-tsan-objects`, and
  `store-sidecar-objects`, preserving each variant's existing compile flags.
- `Makefile:205`, `STORE_REGRESSION_SRC`: append the same source for
  `build/store-regression`, `build/store-regression-tsan`, and
  `build/store-regression-sidecar`.

The gate uses its existing per-source object cache and `--gc-sections`, just
as for the hash cold translation units. No implementation, flags, assertions,
fixtures, production object order, or EXPECT assignments changed.
The [link proof](docs/storesize4/storage-link-proof.txt) finds all five
definitions in every new cached object and no unresolved storesize symbols
in any of the three regression executables. The
[Makefile recipe expansion](docs/storesize4/make-storage-recipes.txt) includes
the same source in all three direct build recipes.

## Other gate build lists

The [expanded dependency audit](docs/storesize4/unit-link-audit.txt) covers
26 targets, including the named multidb, atomic, netcap, and sidecar units.
No additional missing source list was found.

| Existing list / recipe | Why it already links storesize |
| --- | --- |
| `SRC`, `OBJ`, `DB0_OBJ` | `SRC` already contains `src/cmd/storesize.cc` at Makefile:37 |
| `CORE_TEST_OBJ`, `DB0_TEST_OBJ` | Remove only `main.o`; both retain their storesize object |
| multidb and namespace-boundary units | Use those common objects; the multidb exclusion removes only `xshard.o` |
| atomic survivors, EXECABORT/WATCH, flushfix | Use `OBJ` or the common test lists; none excludes storesize |
| netcap and `NETCMD_LIB_OBJ` | Use common/filtered production objects that retain storesize |
| `MDBQSBR_SRC`, ASAN/TSan objects, core and rltopo units | Derive from `SRC` with only `main.cc` removed |
| storesize, exbatch, rehash, writeback-phase, planner, persistence, shutdown, reorder units | Common/filtered lists retain storesize, including both database images where required |
| Gate ASAN, read-local debug, core TSan source lists | `src/cmd/*.cc` includes storesize automatically |
| Standalone config, flip, foreign-read filter, ring, waits, and policy fixtures | Do not instantiate FlatStore; no new link dependency |

The selected storesize, multidb, namespace-boundary, EXECABORT/WATCH,
atomic-survivor, flushfix, and netcap targets were also rebuilt successfully
on CPUs 112–127; `make -q` returned 0 for all of them. Their
[build log](docs/storesize4/selected-unit-build.log) and
[symbol audit](docs/storesize4/other-unit-link-proof.txt) show no unresolved
storesize references. The gate subsequently rebuilt its broader prerequisites
and marked all 25 shared unit targets ready, plus its alternate-binary helper:
[ready markers](docs/storesize4/shared-unit-ready.txt).

`dump_restore` (`tests/gate.sh:2035`) boots the production binary and uses
`tests/dumprestore.py`; it does not use any storage regression unit. Its
conditional rerun is therefore unnecessary for this link-input fix.

## Gate proof

The requested count of 14 storage rows does not match this checkout or the
landing failure ledger: both contain **12**, namely eleven loop cases and
one deadline-sidecar case. All twelve existing rows passed; no row was added,
removed, skipped, or relabeled. See the
[original failed inventory](docs/storesize4/before-ledger) and
[new partial ledger](docs/storesize4/storage-ledger.partial).

```bash
GATE_ONLY_JOBS=storage_units \
GATE_LEDGER="$PWD/build/storesize4-proof/storage-ledger" \
taskset -c 112-127 tests/gate.sh iteration \
  --server-cores 112-119 --load-cores 120-127 \
  --server-smt '' --load-smt '' --ports 18340-18342
```

Run `build/gate-run.6Zoh4S`: **exit 0, 12 ok, 0 FAIL**. This includes the
actual TSan `flags` binary and the deadline-sidecar binary. The
[gate output](docs/storesize4/storage-gate.log) and
[CPU plan](docs/storesize4/storage-plan.sh) preserve the requested CPUs,
eight server threads, ratio 6:2, no SMT, and port range. These fixtures are
serverless; the gate's live boot helpers retain their 16-shard geometry.

`storesize published monitoring` belongs to `atomic_units`. Its final run used
the exact requested flags:

```bash
GATE_ONLY_JOBS=atomic_units \
GATE_LEDGER="$PWD/build/storesize4-proof/atomic-exact-ledger" \
taskset -c 112-127 tests/gate.sh iteration \
  --server-cores 112-119 --load-cores 120-127 \
  --server-smt '' --load-smt '' --ports 18340-18342
```

Run `build/gate-run.6enFqB`: **exit 0, 24 ok, 0 FAIL** (one release row plus
all 23 atomic-unit rows). The
[partial ledger](docs/storesize4/atomic-exact-ledger.partial),
[gate output](docs/storesize4/atomic-exact-gate.log), and
[CPU plan](docs/storesize4/atomic-exact-plan.sh) preserve that exact geometry.
The [monitoring log](docs/storesize4/atomic-exact-storesize-unit.log) covers
db0/multi × split/fused × read-local off/on and records the passing negative
control: restoring the census route fails the exact monitor-route assertion.

The first attempt, `build/gate-run.T1IT2E`, stopped at the
[port guard](docs/storesize4/atomic-port-guard.log) before jobs began because
`cx-respcompat` was actively listening on ports 18340–18341. No process from
that worktree was stopped. An intermediate serverless run on free ports
18350–18352, `build/gate-run.evgHZg`, also exited 0 with
[24 ok, 0 FAIL](docs/storesize4/atomic-ledger.partial). Once the requested
ports cleared, the final warm run above repeated the proof on 18340–18342;
the alternate-port run is not the sole evidence.

## Production identity and row accounting

`taskset -c 112-127 make -j16` completed with exit 0 after the Makefile edit.
It rebuilt the production objects because Makefile is their prerequisite.
The [build log](docs/storesize4/release-build.log) and
[SHA receipt](docs/storesize4/production-sha256.txt) retain the evidence.
`cmp build/tomokv build/storesize3/POST` also exited 0.
The SHA and byte comparison were checked again after both selected gate runs.

| Binary | SHA-256 before and after make |
| --- | --- |
| `build/tomokv` | `30035c48fed39833b82041232230ed535d556821ae45adc47e633ff9b7265807` |

This lane's row delta is **0 quick / 0 full**. The existing storesize row is
still at `tests/gate.sh:1587`, collected with `atomic_units` at line 3151,
before the quick-tier exit block at line 3279. `storage_units` is collected
at line 3149. The lane's earlier contribution remains **+1 / +1**; the
maintainer had already set EXPECT to **498 / 515** before this lane began.
Neither those assignments nor the ledger fixture was edited here.
`bash -n tests/gate.sh`, `git diff --check`, and the source/fixture/EXPECT
preservation checks passed. The repaired storage ledger preserves the exact
12 labels and order from the failed landing ledger.

These are selected correctness runs, not a full gate receipt or a performance
claim; no ABBA/NIC measurements or PAD arm are involved. Storesize3's separate
hot-body identity limitations remain as documented in its report.

The session's higher-priority search instruction required `rg`, so the
grep-only request could not be followed; this conflict was disclosed before
editing. All changes are confined to this worktree.
