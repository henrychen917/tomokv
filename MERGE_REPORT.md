# True-stable integration report

Date: 2026-07-30

Integration base: `7880fd0eb`

Integrated code tip before this report: `dc09e15f9b35b29c028ee250686f5c745bd4a971`

## Result

The true-stable code tip is green and contains ten separately gated changes: nine
verified-safe deletions and the two mechanical allocation removals carried together
by `alloc`. No correctness, observability, load-balancing, or knob-gated feature fork
met every admission and scope rule.

The cumulative source change is 20 files, 287 insertions, and 1,103 deletions. No
configuration parameter, command, INFO field, or DEBUG subcommand was removed. No
merged change adds a knob.

`LB_REPORT.md` was not present anywhere under the supplied job directory, so there
was no LB `DO-NOT-MERGE` or `NEEDS-WORK` verdict to apply. If an LB report is produced
before push, the maintainer must check it against this tip.

## Merged changes

The gate columns below are the merged-position deltas against the supplied reference,
in this order: io7/ex1 p1 GET, io7/ex1 p1 SET, io4/ex4 p32 GET, io4/ex4 p32 SET.

| Fork | Commit | Review / deletion audit | Merged-position gate |
|---|---|---|---|
| `dead01-sampler` | `232279734fae92c2d34f7c01424f723777ce81ff` | SOUND / SAFE-TO-DELETE | +1.2%, +0.9%, +0.1%, +0.9% |
| `dead02-polythreads` | `d7708e69b34f6d6f5668b36edcce494ba79c05e2` | SOUND / SAFE-TO-DELETE | +1.4%, +0.8%, +0.3%, +0.2% |
| `dead04-copyengine` | `3000ed14165ebcf706c6ac179038d3ea3e6d8dfd` | SOUND / SAFE-TO-DELETE | +1.7%, +0.7%, +0.6%, +1.4% |
| `dead05-nextop` | `f1329bbdf65cf552b09293bdbae4297d3fd1c437` | SOUND-WITH-NITS / SAFE-TO-DELETE | +1.6%, +1.1%, +1.1%, -0.4% |
| `dead06-retiredknobs` | `9ae0636e3617cd3bbeb351af7ff71782d37bb2fc` | SOUND / SAFE-TO-DELETE | +1.5%, +0.9%, +0.5%, +0.0% |
| `dead07-fields` | `7b8375f5656a80be996ec2c6822507f05882e719` | SOUND-WITH-NITS / SAFE-TO-DELETE | +0.8%, -0.2%, +1.3%, +1.7% |
| `dead08-nocaller` | `6d18f5dca6fcaec9ff7ae0e8ff30b1c1fc7e37df` | SOUND-WITH-NITS / SAFE-TO-DELETE | +1.4%, +1.0%, +0.7%, +0.1% |
| `dead09-evictbuckets` | `6050c134e25bfadbb907e3359e80cda266ae76f8` | SOUND-WITH-NITS / SAFE-TO-DELETE | +1.7%, +1.3%, +2.2%, +2.1% |
| `dead10-cluster` | `942d5c186b9f4dc43c1787e0e044a91b33729b85` | SOUND / SAFE-TO-DELETE | +1.5%, +1.8%, +2.6%, +1.9% |
| `alloc` | `dc09e15f9b35b29c028ee250686f5c745bd4a971` | SOUND; no feature deletion | +1.3%, +1.5%, +2.7%, +1.7% |

Each deletion was rechecked after application against the original integration-base
binary. The CONFIG parameter set, command names/count, INFO field names, and DEBUG
subcommands were identical. DICT static, FLATSTORE static, FLATSTORE auto, DICT auto,
and two-node shapes all booted and passed SET/GET, and the shipped `redis.conf` booted.
`redis-full.conf` failed identically on the base and candidates because this fork
intentionally does not support its `loadmodule` directive; that is pre-existing and
not a regression.

The `alloc` change received the full correctness acceptance in its merged position:
15 passed, 0 failed. This covered ordering, cross-shard pipelines, MGET arity,
MSET/MSETNX behavior, binary safety, expiry/reallocation, non-string rename,
load, and crash-marker checks.

Every change built before its gate and was committed only after the gate returned
zero. The only build warning was the explicitly allowed, pre-existing
`kvstore.c:73` incompatible-pointer-type warning.

## Conflict resolution

There was one apply conflict, in `src/server.c` while applying `dead07-fields` after
`dead02-polythreads`. `dead02-polythreads` had made poly-thread pool initialization
unconditional while removing obsolete entry points; `dead07-fields` removed the
write-only `server.ioThreadsNum` assignment in the same `initIOThreads` region.

This was resolved mechanically: retain the unconditional poly-thread context
initialization from `dead02-polythreads`, and delete only the write-only
`server.ioThreadsNum` assignment from `dead07-fields`. No behavior choice was
invented. All other patches applied cleanly.

## Not merged: admission failures

| Fork(s) | Exclusion |
|---|---|
| `dead03-modules` | Original was superseded by `fix-dead03`; it was also reviewed DEFECTIVE and audited PARTIALLY-UNSAFE. Never merge original and fix together. |
| `fix-dead03` | Tester PASS and SAFE-TO-DELETE were insufficient because its available review verdict is DEFECTIVE. The SOUND/SOUND-WITH-NITS admission rule failed. |
| `dead12-staledocs` | Original was superseded by `fix-dead12`; it was also reviewed DEFECTIVE and audited PARTIALLY-UNSAFE. |
| `fix-dead12` | Tester PASS, but review is DEFECTIVE and no SAFE-TO-DELETE audit exists for this deleting fork. Its diff is the same unsafe deletion presented by the original, and it has no author `RESULT.md`. |
| `fix-hotkeys` | Tester PASS, but review is DEFECTIVE. Shared result/client state and CHK-sketch races remain reachable, so the proposed replacement does not earn admission. |
| `iosat-cheap` | Tester PASS, but review is DEFECTIVE. Default `1` preserves the per-pass CPU-clock syscall, while sampled/off settings can feed delayed or false utilization to the live controller. It therefore does not provide the claimed safe default-path removal. |
| `task-expiry`, `task-parked`, `task-preflight`, `guard-prefetch-invariant` | Tester PASS, but no adversarial `REVIEW.md` exists. Missing is not SOUND, so each fails admission. |
| `task-observability` | Tester PASS, but no adversarial review exists. The owner allowed this large change only with a SOUND review and no removed surface; in doubt it must be deferred. |
| `test-armrace`, `test-h2fence` | Tester recorded EMPTY-DIFF, not PASS. Their author accounts say the intended fixes were already in the base, so there was no fork change to merge. |

The explicit `hotkeys` fork was not merged under any circumstance: the owner rejected
its 787-line rework. Its proposed replacement, `fix-hotkeys`, independently failed
the review rule above.

## Not merged: stable-scope deferrals

The owner explicitly deferred `prefetch`, `prefetch2`, `prefetch-io`,
`prefetch-mget`, `alloc-arena`, `alloc-mset`, `sched-impl`, `hotkeys`, `mega`, and
`mega2`, plus all other knob-gated performance work. `TEST_REPORT.md` measured only
default-setting ordinary GET/SET paths, so dormant knob-off behavior did not validate
the corresponding enabled paths. A paired knob-on measurement was started but did
not finish.

Two mixed-default details make the lack of feature acceptance even more important:
`alloc-mset` changes `tomokv-mset-move` to default `yes`, but the tester ran no MSET
acceptance workload; `prefetch2` leaves its next-op arm on while its storage-prefetch
knobs are off. Neither received a controlled off/on validation of its intended
feature behavior. These are unvalidated feature changes and do not belong in the
stable release.

Several have additional blockers, but the owner scope ruling is sufficient:
`prefetch` introduced a new compiler warning; `prefetch`, `prefetch2`, and
`prefetch-mget` were reviewed DEFECTIVE; `mega` and `mega2` were EMPTY-DIFF rather
than PASS.

The other non-empty tester forks—`errstat`, `flipctx`, `iosat`, and `mbox`—were not
in the owner's true-stable merge list and have no required SOUND adversarial review,
so they were deferred rather than expanding release scope. `dead11-buckethash`,
`fix-prefetch`, and all remaining audit/review/worklog rows were EMPTY-DIFF, which is
not a tester PASS and therefore cannot satisfy admission.

## Final clean build and combined gate

After all code commits, `make clean && make -j8` completed successfully. Its only
warning was the permitted pre-existing `kvstore.c:73` warning.

The final box-locked combined run used `tools/preflight/correctness_suite.sh` as the
acceptance phase and passed 15/15 cases with zero crash markers. The required
2-million-key, depth-32 cells were:

| Cell | Reference | Final | Delta |
|---|---:|---:|---:|
| io7/ex1 p1 GET | 826,877 | 831,404 | +0.5% |
| io7/ex1 p1 SET | 817,393 | 818,029 | +0.1% |
| io4/ex4 p32 GET | 7,943,860 | 8,109,454 | +2.1% |
| io4/ex4 p32 SET | 6,852,385 | 6,877,029 | +0.4% |

No cell was worse than -4%, so the combination passed and no interaction bisection
was required.

## Maintainer checks before push

- No push was attempted. HEAD is detached; point the intended integration branch at
  the final report commit before pushing.
- Confirm that no later `LB_REPORT.md` contains a negative verdict for a mechanism
  touched here. No LB report was available during integration.
- Treat the `redis-full.conf` `loadmodule` boot failure and `kvstore.c:73` warning as
  known pre-existing conditions, not new failures.
- Review the retained SOUND-WITH-NITS follow-ups: nearby next-op comments overstate
  hash/width behavior; the grow-back flip comment is imprecise; readless
  `sync_read`/`rio.tell` callback residue remains; and client-eviction DEBUG HELP
  text lacks a focused compatibility cleanup/test.
- The harness's printed `Killed` lines are its deliberate server teardown. The final
  correctness suite reported zero crash markers.

The integration tree is buildable, gated, and in a state suitable for maintainer
verification. It has intentionally not been pushed.
