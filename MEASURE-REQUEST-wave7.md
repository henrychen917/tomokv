# Wave 7 landing

## wave7 integration

Integration and offline proof are complete on `cx-wave7`, headline `05a5e01a9`; correctness verification is in progress. No push. All commands and correctness children are constrained to CPUs 64–95 and listeners to ports 26800–26899. Performance measurements and the full iteration remain with the maintainer.

All six lane reports were read before merging their branches in the requested order with `--no-ff`. Each merge is committed separately. AT4.12 remains design-only.

### Row accounting

Headline 768/785 + rlfix3 16 + ctlfix 0 + blockfix 3 + persistfix2 4 + atomfix5 2 + datafix2 5 gives **DQ=+30, DF=+30; required counts 798/815**. The explicit fixture contains all 815 declared labels with multiplicities, including datafix2’s five previously missing labels. `docs/wave7/rows.json` counts collection lines relative to the quick exit. `EXPECT_QUICK=768` and `EXPECT_FULL=785` remain untouched.

### Merge decisions

- Keep all scheduler registrations and collections from every lane and wave 6.
- Atomic apply retains notifycompat’s empty-destination presence witness and adds datafix2’s effect-based WATCH signal.
- MULTI scatter execution retains execfair’s `retry()` scheduling and uses datafix2’s effect-aware scatter wrapper; the retired unconditional WATCH completion callback stays removed.
- Lua retains persistfix2’s AOF-error admission and adds datafix2’s effect scope, including partial effects before an error.
- OBJECT retains wave 6’s single no-touch/non-notifying lookup, missing-key precedence and physical expiry notification, plus datafix2’s idle-clock result.
- XGROUP keeps dispatchfix’s early validation and blockfix’s macro-node MKSTREAM, adding WATCH dirtiness only when the stream is created.
- SETBIT keeps notifycompat’s changed-bit notification rule, while datafix2 materializes embedded strings as raw even for an unchanged bit.
- INFO retains selective collection; `expired_subkeys` is computed from the collected lifetime field counter and RESETSTAT baseline only for STATS.

Final build, compiler trials, command-scope instruction counts and PAD construction are complete; the current correctness status is below. No throughput claim.

### Directed interaction checks

`tests/wave7.py` extends existing jobs without adding rows: cross-owner no-op/real writes both ordinary and in writer EXEC preserve exact CLIENT INFO/LIST watch counts and clear them on both EXEC outcomes; unchanged SETBIT still materializes raw without dirtying WATCH; blocking BLMOVE dirties its watched destination when served; selective INFO asserts each changed field appears exactly once in its owning section and requires a nonzero expired-subkeys transition followed by RESETSTAT. Persistfix2 shutdown adds observed BLPOP+XREAD waiters at SAVE/NOSAVE shutdown, EOF on every peer, clean exit and exact recovery.

The first merged interaction selection exposed an RL4.15 fixture integration error: its serverless eight-worker topology inherited the gate client's two-CPU mask in a three-slot run and failed `selected == 8`. The helper now runs native witnesses on the gate's own eight-CPU `GATE_CORES` allocation. This retains all protected-page, exact-count and rewrite assertions; the failed first invocation is retained. Live selective INFO, the complete CD4.9 table, execfair interaction checks and blocked SAVE/NOSAVE recovery passed their first invocations.

### Interaction audit

- WATCH count is session metadata, independent of dirty claims: atomfix5 counts the unique ns=0 alias for each logical watched key; datafix2 preserves aliases and generations until EXEC/DISCARD/UNWATCH while changing only mutation evidence. Wave 6 `retry()` still releases/requeues executable units through execfair; it was not reverted to the older bare retry result. The directed cross-owner writer-EXEC cases and the full CD4.9 command table exercise the composition.
- Lua composes PS4.15 admission with CD4.9 effect tracking: a refused nested write never calls its handler, while a partial effect retains its mutation witness. The vendored interpreter is compiled as C++ (`LUAI_THROW` throws), so the nested effect scopes unwind on Lua errors; no dangling scope is introduced by the merge. The persistence error and complete WATCH-table jobs retain these cases.
- INFO: `expired_subkeys` and its lifetime/reset companions belong to STATS; RDB/AOF attempt/time/status fields belong to PERSISTENCE. Selective collection computes the field-expiry counter only when STATS is requested. CLIENT INFO/LIST watch counts are client metadata, not a new INFO section field. Nonzero expiry and reset witnesses cover RESP2/3 and section unions.
- FLIP admission and controller completion attribution share the existing cold transition mutex. No retry or lock was added to a reader. RL4.11 keeps read-local values copied through migration; its read-only capability stays zero while owner GET zero-copy remains separately configurable. The directed two-completion migration check extends every declared 2s RL4.11 leg.
- Blocking queues retain owner-local state and FIFO order; the new hash lookup includes hash, physical namespace and full key equality. The registry remains attached to the Shard, so ownership migration moves the same registry. Datafix2 mutation evidence is emitted by the served command, not registration or lookup; the BLMOVE watcher test observes a real park before waking and validates destination encoding.
- Registry destruction still follows owner/IO join. Wave 5's shutdown writeback retirement discards undeliverable notification batches and retires blocked operations before shard-owned registry references are released. Directed SAVE/NOSAVE shutdown arms require two observed blocked clients, peer EOF and exact reload contents. Persistfix2's admission policy does not alter dispatchfix's v2 snapshot routing reader/writer; the existing router-uniform old-file recovery job is included in the sweep.

### Offline inventory and trials

The merged link has **156 R7 bodies in `tomo`, 156 in `tomo_db0`**, with exactly the headline's names and multiplicities. Older atomfix5 contributes no inventory delta; datafix2's one extra normal-namespace body already exists in the wave 6 headline. `docs/wave7/r7-inventory` records each frozen input and the empty merged/headline delta. The final R7 job, including its negative controls, remains required after tuning.

`docs/wave7/budgets` records PRE/POST IPA sizes, compile-only budget trials and linked-body scoring against all six frozen POSTs. The final inventory and call-site review are below. No instructions, registers, member offsets or opcode differences are masked.

The whole `atomic_batteries` release job is **NOT RUN**: it contains an explicit pipelined-versus-serial throughput measurement, which this lane is not authorized to run. Its non-rate correctness cases will run through the gate's ASAN battery in both modes. Efficiency, saturated FLIP, atomic throughput floor, ABBA measurements, NIC measurements and full iteration are also reserved to the maintainer. This limitation is separate from ordinary correctness failures, which remain visible in receipts.

The first broad job selection was rejected before any job ran because it explicitly named a build-only prerequisite (`core_tsan_build`). The campaign manifest now selects consuming correctness jobs and lets the gate add prerequisites. The rejected selection remains in its receipt; it is not passing evidence. The independent differential and repeated transaction selections continue through the same gate interface.

### Final build and offline proof

POST is `build/tomokv`, SHA-256 `177c93bea5aaa797a847de9eeffb9f8eb1f995f5eb9194c2b34ab6565af288ee`. PAD-A is `build/tomokv-wave7-PAD-A`, SHA-256 `d00e327ca81e3c7708b6f2f6e71ac56388f50a747c503689715971fcbf296d12`. Production source last changed in `f941716b1`; subsequent work is verification/reporting. [PAD construction](docs/wave7/pad-a.json) records every input object hash. Kind **A, behaviour twin**: unchanged headline behaviour with POST's `.text` start `0x1f8b0` and size 8,278,199 bytes, using 60,288 trailing unreachable bytes. It controls section origin/size, not individual function addresses or data layout. No PAD-B. The locally rebuilt PRE matches all 9,320 frozen headline groups; PAD retains all 565 historical hot groups exactly, with four cold local-closure relocation mismatches and its added unreachable pad body left visible.

There were 58 baseline/merged IPA compilations, 112 budget trials over all 29 pinned units (96 distinct scored objects), then 60 call-site trials over six dispatcher units. The source fix keeps GET's exact small argc/argv key expression at its use site, restoring the armed GET body; it does not alter access semantics. [Budget choices](docs/wave7/budgets/selected.json), [dispatch call-site choices](docs/wave7/budgets-dispatch/selected.json), and [every remaining changed body with its reason](docs/wave7/identity-expanded/changed-bodies.md) are retained. The expanded audit includes every body actually entered by the command scopes: **787 hot groups, 697 headline-equal, 25 lane-equal, 65 residual**. All 65 have [full call-site comparisons](docs/wave7/callsites-expanded/summary.json) against every supplied frozen reference. Ten of twelve selected command-body groups match headline; the two armed SET bodies compose datafix2 effect notifications with wave 6's expired-SET handling. This is not a claim that all bodies became identical. Remaining composites, cold inlining changes and constant-pool/switch references stay explicit merit inputs; no opcodes, member offsets or register differences were masked.

[Complete instruction table](docs/wave7/instructions/table.md): **48/48 GET/SET/INCR cells add zero instructions**, at batches 1/32, both modes, both database runtimes, slowlog 10000/-1. The unarmed SET handler is byte-identical, and no WATCH callback or watch-key lookup runs on these no-watcher paths. The full CD4.9 command table retains SET/NX/XX and MSET/MSETNX present/absent-key cases, including writer EXEC. The cost is in shared scatter selection: 8-key MSET adds **40/56** instructions at atomic 0/1 in the normal runtime, **48/40** in db0, in either mode; batch 8 scales these to **320/448** and **384/320**. `xshard_execute` contributes +40/+64 (normal) or +48/+48 (db0); atomic admission removes eight instructions. MGET shares the predicate and adds +40 normal / +48 db0 per 8-key command. These are named production instruction counts, excluding fixture setup, external library bodies and networking; the scatter batch repeats completed groups. External library call counts match in all 80 cells. [Provenance](docs/wave7/instructions/provenance.json) verifies every actually entered body: 125 normal and 124 db0 groups per arm, with exact constant-byte and switch-destination proofs plus negative controls. No throughput/cycle/IPC claim.

Both uring and epoll differential selections pass, including standard seeds, atomic modes, both geometries and mode equivalence. Two complete repetitions of all four transaction-order cells and the fused legacy/ASAN selection pass. All 46 production build/freshness checks pass with POST unchanged. The broad final job sweep and gate self-tests remain pending; final receipts will replace this status.

### Maintainer measurement request

The full iteration, null and landing gate are **NOT RUN here**. Use the gate's own instrument and declared cell geometry, matched offered load, arm balance and null rejection rules. PRE is `/home/user/Projects/bench-bins/tomokv-headline-05a5e01a9`, SHA-256 `ff538ad1bebb30a7272e5396ef7daca90df14f2a84db3dd6f3cfc2acc8c1acd8`; POST and PAD-A are bound above. Run PRE/PRE null, PRE/POST landing and PRE/PAD-A size/origin control. Keep the normal landing [headline cells](tests/headline_cells.txt) and [multi-key cells](tests/mkprobe_cells.txt), including both modes, read-local states, atomic settings and pipeline depths declared there. Check the 2s SET depth-1 cells and 8-key MSET depth 1/8 separately; the maintainer's isolated datafix2 leans are not an integration verdict. Include the established [multi-DB cells](docs/lbplanner/multidb-cells.txt) for the full database runtime.

| Comparison | PRE | POST / PAD-A | Deciding evidence |
|---|---|---|---|
| PRE/PRE null | NOT RUN | NOT RUN | Gate's validity/noise rules |
| PRE/POST landing | NOT RUN | NOT RUN | Per-cell rate at matched load and declared depth-1 latency score |
| PRE/PAD-A control | NOT RUN | NOT RUN | Whether section-size/origin movement explains any result |

Report cycles/op, instructions/op and IPC with each cell. Rate and latency decide; the instruction counts and identity inventory explain and localize changes. Do not average away a regressed SET/MSET cell. PAD-A is a **behaviour twin**, with the section-layout limitation stated above; it is not an inverse control. No throughput, latency or cycle improvement is claimed by this integration.
