# Wave 7 landing

## wave7 integration

All six lanes are merged on `cx-wave7` from headline `05a5e01a9`, with a separate `--no-ff` commit for each lane in the requested order. A real cross-wave WATCH/prebuilt-SET defect was found, fixed and given a directed regression check. Offline proof is complete; the complete correctness campaign is rerunning on the final executable. No push. AT4.12 remains design-only.

Every invocation uses CPUs 64–95, builds use `-j32`, and correctness listeners use ports 26800–26899. Gate entry starts with `LANG=en_US.UTF-8` and `LC_ALL` unset; the real gate pins collation to C. No performance load generator or full iteration was run.

### Merges and row accounting

| Lane | Merge commit | DQ | DF |
|---|---|---:|---:|
| cx-rlfix3 | `abff31819` | 16 | 16 |
| cx-ctlfix | `ee1aec4ea` | 0 | 0 |
| cx-blockfix | `e452caa92` | 3 | 3 |
| cx-persistfix2 | `f0d647b37` | 4 | 4 |
| cx-atomfix5 | `033be1114` | 2 | 2 |
| cx-datafix2 | `7fe467f66` | 5 | 5 |
| Total | | **30** | **30** |

The maintainer should change **768/785 → 798/815**. The actual `EXPECT_QUICK=768` and `EXPECT_FULL=785` are untouched. [Row accounting](docs/wave7/rows.json) derives each lane's delta against its own base and counts every collection by its **line relative to the quick exit at line 5610**. All 30 added rows precede that exit. The explicit fixture contains all 815 declared labels with multiplicities, including the five datafix2 labels missing from its lane fixture. Directed integration checks extend existing jobs and add no rows.

All six reports were read before their merge. Shared files compose additively: scheduler registrations/collections, Makefile targets, label fixture, all four unique-key scans in the R7 check, and lane-specific implementations remain present. Older atomfix5/datafix2 code retains wave 6 scheduling, notification and routing changes.

### Semantic interactions and fixes

**WATCH counts, actual effects and execfair.** atomfix5 counts the unique ns=0 alias of each logical watched key; datafix2 changes mutation evidence without clearing aliases or generations early. Wave 6's `retry()` and `service_multi_retries` remain. The integration check runs same/cross-owner no-op and real writes, both ordinary and inside the writer's EXEC, verifies CLIENT INFO/LIST counts before and after both EXEC outcomes, and checks that unchanged SETBIT materializes raw without dirtying WATCH. Atomic scatter keeps notifycompat's empty-destination presence witness plus CD4.9 effects. Lua keeps PS4.15 AOF admission and CD4.9 partial-effect tracking; the vendored C++ interpreter unwinds the effect scope on errors.

**Diagnosed prebuilt-SET defect, fixed in `9cbe15382`.** datafix2's WATCH dispatch selects `op.spec->handler_notify` when any watched key exists on the shard. Wave 6's prebuilt SET specifications had copied ordinary SET's notification handler. A remote large SET could therefore leave its prebuilt `KvObj` pointer and -6 marker attached; writeback interpreted that marker as scatter state and attempted snapshot retirement on the value. This caused the persistence error job's fused aborts. The [captured debugger state](docs/wave7/persistence-abort-stop-7-138742-gdb.log) contains `durability-window` key bytes in the supposed snapshot header.

Both specifications now set `handler_notify = cmd_set_prebuilt<true>`, consuming the same sidecar before recording effects. This changes cold specification initialization only: ordinary no-watcher SET gains no branch, callback, key lookup or layout change. The directed CD4.9 extension proves a same-shard pair and selects two distinct IO producers, then checks 513/1024/200000-byte values, sibling-only WATCH, replacement, no-op NX, missing XX and SET GET under empty and K$ notification masks, against Redis. All 24 fixed-binary legs pass. The initial whole-job faulty-binary control failed 15 of 16 fused legs; a single producer missed one leg. The strengthened witness alternates two producers for real watched-key modifications, verifies their IO identities, and is queued for the final whole-job faulty-binary control. Split legs exercise ordinary SET because prebuilding is fused-only.

**Selective INFO.** `expired_subkeys` and its lifetime/reset companions appear only in STATS; changed RDB/AOF time, attempt and status fields appear only in PERSISTENCE. Selective collection computes the field counter when STATS is requested. CLIENT INFO/LIST `watch=` is client metadata, not an INFO section field. Directed RESP2/RESP3 tests cover each selected section, default/all/everything/unions, exactly-once membership, a nonzero expiry, RESETSTAT and equality of the RDB time with LASTSAVE.

**FLIP and read-local.** ctlfix's completion-qualified admission and completion attribution retain the cold transition mutex. RL4.11's lane copying remains valid through migration and its read-only `zc-min-read-local` stays zero; owner GET zero-copy remains separately configurable. The two-completion migration witness extends every declared 2s RL4.11 leg. No reader retry, seqlock or per-operation reader lock was added.

**Blocking lookup, effects and teardown.** blockfix's registry remains Shard-owned, including hash, physical namespace and full-key comparison, so it migrates with the shard. FIFO order is unchanged. A directed BLMOVE check requires an observed park, validates the served destination's listpack encoding and WATCH abort, and requires the blocked count to return to zero. Wave 5's owner/IO join, notification-batch discard and blocked-operation retirement still precede registry destruction.

**Persistence, blocked shutdown and old files.** SAVE/NOSAVE shutdown checks require observed BLPOP and XREAD waiters, EOF for every peer, clean exit and exact reload contents. PS4.15 error admission composes with the WATCH table and scripts. Dispatchfix's v2 non-divisor snapshot reader/writer is unchanged; router-uniform old-file recovery remains in the campaign. XGROUP retains early error precedence, blockfix MKSTREAM structure/counts and WATCH dirtiness only on creation. OBJECT retains wave 6's single no-touch lookup, missing-key precedence and physical-expiry notification plus datafix2 IDLETIME.

[Directed checks](tests/wave7.py) run only through their owning gate jobs. [Coverage mapping](docs/wave7/coverage.json) sweeps touched files and changed reply text, INFO fields, encodings and precedence into complete gate selections.

### Fixture findings

- RL4.15's eight-worker native witness inherited the gate client's two-CPU mask. It now uses that job's eight-CPU `GATE_CORES`; all protected-page, exact-count and rewrite assertions remain.
- SV4.6's mutable-knob inventory omitted RL4.11's deliberate immutability. `zc-min-read-local` is now in the immutable inventory; duplicate, rollback, type and oracle checks remain.
- The WATCH eviction witness could see no victim in one bounded sparse-store sample. It now requires all 128 seeds, at most 32 pressure writes to the same unwatched key per cohort, and exactly three fresh cohorts. An actual watched-key removal and aborted EXEC remain mandatory. A whole-job target-only noeviction control must fail all 24 legs; no skip or tolerance was added.
- RLIMIT_FSIZE also suppressed the persistence child's diagnostic file. The parent now drains a pipe into its own log; AOF limit, commands and verdicts are unchanged. The resulting diagnostic work found the real prebuilt defect above. The new large-value test client uses buffered reads so multi-packet replies are read exactly.
- `gates_test.py`'s one-slot fixture had pinned coordinator and worker together on one CPU, unlike the real gate. The coordinator now keeps the fixture's existing four-CPU allocation; its sole worker must still be observed on exactly one CPU. All 72 tests, jobs, planted controls and the 45-second bound remain. Extracted fixtures retain the real gate's C collation pin.
- Configuration documentation now includes `shutdown-on-sigint` and `shutdown-on-sigterm` with Redis grammar/defaults; generated source anchors are refreshed. The docs checker covers all 93 spellings and its negative controls.

Historical failed jobs, the initial harness artifact and diagnostic-preload runs remain archived. Diagnostic runs cannot count as final passing evidence.

### R7 inventory, inlining and linked-body review

The merged ELF has **156 bodies in `tomo`, 156 in `tomo_db0`**, with exactly the headline's names and multiplicities. [Frozen inventories](docs/wave7/r7-inventory/summary.json) show atomfix5 152/153 against its 152/153 base, and datafix2 153/153 against 152/153. That extra normal body already exists in wave 6; additive composition does not double-count it. The owning R7 job retains every negative control.

Compile-only work covered all 29 pinned units: 58 baseline/merged IPA compilations, 112 budget trials (96 distinct scored objects), followed by 60 call-site trials over six dispatcher units. [Budget choices](docs/wave7/budgets/selected.json) and [dispatcher choices](docs/wave7/budgets-dispatch/selected.json) retain exact commands, input sizes and scores against headline and all six frozen POSTs. GET's small argc/argv key expression stays at its call site to restore its armed body without changing semantics.

| Unit | Headline budget → merged budget |
|---|---|
| normal t_list | 25352 → 25608 |
| db0 t_server; aof | 33074 → 33448; 37572 → 39024 |
| normal snapshot | 14818 → 15191 |
| normal/db0 t_set | 26200 → 26451 / 26400 → 26651 |
| db0 t_zset; geo | 32984 → 33229; 16457 → 16462 |
| normal/db0 xshard | 145327 → 147163 / 144177 → 145970 |
| normal genthread; rl2s; reorder | 132011 → 132454; 165332 → 165831; 149814 → 150313 |
| db0 genthread; rl2s; reorder | 132813 → 133256; 163824 → 164323; 150803 → 151302 |

Other pinned budgets retain headline values. The final strict inventory has **9,478 groups: 8,083 headline-equal, 833 equal to a supplied lane POST, 562 residual**. All **1,395 changed groups** have a [per-body reason](docs/wave7/identity-expanded/changed-bodies.md). The expanded hot inventory includes actual instruction-trace bodies: **787 groups, 697 headline-equal, 25 lane-equal, 65 residual**. Every residual group's clones and call sites were compared against every frozen input in the [call-site receipts](docs/wave7/callsites-expanded/summary.json).

Ten of twelve selected GET/SET/MGET/MSET groups match headline. The two armed SET bodies combine CD4.9 effect metadata with wave 6's `notify_elapsed_set`, which the older lane POST lacks. Remaining scheduler/parser composites, clone-specific cold inlining changes, register/branch changes and strict constant/switch reference differences stay listed; **this is not a claim of complete body identity**. No opcode, register or member-offset difference is masked. Identity explains the candidate; the maintainer's landing merit decides it.

The prebuilt pointer fix changes only four linked groups (two functions × two namespaces); [its exact comparison](docs/wave7/prebuilt-fix-identity.json) proves every other group unchanged. The retained command traces were rebound to the final production ELF, including exact constant bytes and switch destinations. No counted body changed.

### Serverless command-scope instructions

[Complete PRE/POST table](docs/wave7/instructions/table.md) covers 80 cells. All **48 GET/SET/INCR cells add zero instructions** at batch 1/32, both modes, both database runtimes and slowlog 10000/-1. The plain SET body is headline-identical; no WATCH callback or key lookup executes when no client watches. Counts are exact named production instructions, excluding setup, external library bodies, parser/network and queues. Each cell verifies reply/data; clock reads are deterministic to exclude debugger pauses from slowlog admission. Multi-key batch 8 repeats completed scatter groups rather than an overlapped parser pipeline.

| Eight-key command | Normal runtime delta, atomic 0 / 1 | db0 delta, atomic 0 / 1 |
|---|---:|---:|
| MGET, batch 1 | +40 / +40 | +48 / +48 |
| MGET, batch 8 | +320 / +320 | +384 / +384 |
| MSET, batch 1 | +40 / +56 | +48 / +40 |
| MSET, batch 8 | +320 / +448 | +384 / +320 |

These deltas hold in both modes. The shared `xshard_execute` notification-selection predicate now includes shard watches: +40/+64 in normal or +48/+48 in db0 across eight fragments; atomic admission removes eight instructions. MGET shares the predicate. The full CD4.9 table retains SET/NX/XX and MSET/MSETNX present/absent-key cases, including writer EXEC. [Provenance](docs/wave7/instructions/provenance.json) covers all 125 normal and 124 db0 entered groups per arm, with constant-byte and switch-destination proofs and negative controls. External library call counts match in every cell. Instructions are not a cycles or throughput verdict.

### Correctness status

The broad final sweep **passed 208 jobs and 797 rows, with zero failures**, on POST `02e1a1a2…`. This includes all six lanes, all 16 rlfix3 rows, all 24 strengthened WATCH legs, persistence errors, blocked shutdown, execfair, R7 negative controls and non-divisor old-file recovery. Both-engine differential suites, additional txnorder rounds, fused batteries and quiet harness/control verification are IN PROGRESS. The earlier superseded-executable campaign remains historical evidence. Final [selection receipts](docs/wave7/correctness/summary.json) and [job coverage](docs/wave7/coverage-results.json) will be refreshed after those remaining checks.

The final campaign includes every allowed new/touched/matching job, R7 negative controls, both-engine differential standard seeds and both geometries, all four txnorder cells at least three times, blocking/streams/persistence/old-file recovery/FLIP/read-local/INFO/scripts/data types in both modes, standalone `gates_test.py`, complete `abba_selftest` and all production unit builds/freshness checks. Only the throwaway self-test source copy changes EXPECT to 798/815.

**NOT RUN:** full `tests/gate.sh iteration`, ABBA/NIC measurements, `efficiency`, `flip_saturated`, `atomic_floor`, and whole release `atomic_batteries`. These include performance benchmarks or measurement load generators reserved to the maintainer. The latter's non-rate correctness cases run through both declared ASAN battery modes. `tailgen` is compile-only through `make all`; the direct `tailgen client-lb outstanding bound` row is NOT RUN because it invokes the open-loop measurement generator and a 2M-key / 16 GiB population outside the individual-job interface.

### Final artifacts and measurement request

| Arm | Path | SHA-256 |
|---|---|---|
| PRE | `/home/user/Projects/bench-bins/tomokv-headline-05a5e01a9` | `ff538ad1bebb30a7272e5396ef7daca90df14f2a84db3dd6f3cfc2acc8c1acd8` |
| POST | `build/tomokv` | `02e1a1a2cd0925d6dfa8deb3510febd0df745badbb03c95d2d8e41683f51c753` |
| PAD-A | `build/tomokv-wave7-PAD-A` | `900b797991bce0bf12c4c8e2ed92a270281f023f30b784faefaa8e4b1cbcfc68` |

PAD is kind **A, behaviour twin**: unchanged headline behaviour with final POST's `.text` start `0x1f8b0` and size **8,278,231 bytes**, using **60,320 trailing unreachable bytes**. It controls section origin/size, not individual function offsets or data layout. [Construction](docs/wave7/pad-a.json) hashes every object; [PAD audit](docs/wave7/pad-identity-final/summary.json) retains all 785 expanded headline hot groups and all 12 command groups exactly. Four cold local-closure relocation mismatches and the added unreachable pad body remain visible. No PAD-B. The locally rebuilt PRE matches all 9,320 frozen headline groups.

The maintainer runs the null and landing gate with the gate's own instrument, geometry, matched offered load, arm balance and validity rules. Run PRE/PRE null, PRE/POST landing and PRE/PAD-A section-size/origin control. Retain all [headline cells](tests/headline_cells.txt), [multi-key cells](tests/mkprobe_cells.txt) and established [multi-DB cells](docs/lbplanner/multidb-cells.txt). Check **2s SET depth 1** and **eight-key MSET depth 1/8** separately; the isolated datafix2 lean is not an integration verdict.

| Comparison | PRE | POST / PAD-A | Deciding evidence |
|---|---|---|---|
| PRE/PRE null | NOT RUN | NOT RUN | Gate validity/noise rules |
| PRE/POST landing | NOT RUN | NOT RUN | Rate at matched offered load and declared depth-1 latency score |
| PRE/PAD-A control | NOT RUN | NOT RUN | Whether section origin/size movement explains the result |

Record cycles/op, instructions/op and IPC for every cell. Rate and latency decide; do not average away a regressed SET/MSET cell. No throughput, latency or cycle improvement is claimed here.
