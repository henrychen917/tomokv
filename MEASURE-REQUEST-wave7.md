# Wave 7 landing

## wave7 integration

Work in progress on `cx-wave7`, headline `05a5e01a9`; no push. All commands and correctness children are constrained to CPUs 64–95 and listeners to ports 26800–26899. Performance measurements and the full iteration remain with the maintainer.

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

Build, interaction checks, compiler trials, command-scope instruction counts, final correctness receipts and PAD construction are pending. No throughput claim.

### Directed interaction checks

`tests/wave7.py` extends existing jobs without adding rows: cross-owner no-op/real writes both ordinary and in writer EXEC preserve exact CLIENT INFO/LIST watch counts and clear them on both EXEC outcomes; unchanged SETBIT still materializes raw without dirtying WATCH; blocking BLMOVE dirties its watched destination when served; selective INFO asserts each changed field appears exactly once in its owning section and requires a nonzero expired-subkeys transition followed by RESETSTAT. Persistfix2 shutdown adds observed BLPOP+XREAD waiters at SAVE/NOSAVE shutdown, EOF on every peer, clean exit and exact recovery.

Initial serverless plain singleton counts (slowlog disarmed) add no instructions in any of the twelve mode/runtime/command cells. The complete batch and slowlog matrix and MSET causes are still pending. These are instruction counts, not performance measurements.

The first merged interaction selection exposed an RL4.15 fixture integration error: its serverless eight-worker topology inherited the gate client's two-CPU mask in a three-slot run and failed `selected == 8`. The helper now runs native witnesses on the gate's own eight-CPU `GATE_CORES` allocation. This retains all protected-page, exact-count and rewrite assertions; the failed first invocation is retained. Live selective INFO, the complete CD4.9 table, execfair interaction checks and blocked SAVE/NOSAVE recovery passed their first invocations.

### Interaction audit

- WATCH count is session metadata, independent of dirty claims: atomfix5 counts the unique ns=0 alias for each logical watched key; datafix2 preserves aliases and generations until EXEC/DISCARD/UNWATCH while changing only mutation evidence. Wave 6 `retry()` still releases/requeues executable units through execfair; it was not reverted to the older bare retry result. The directed cross-owner writer-EXEC cases and the full CD4.9 command table exercise the composition.
- INFO: `expired_subkeys` and its lifetime/reset companions belong to STATS; RDB/AOF attempt/time/status fields belong to PERSISTENCE. Selective collection computes the field-expiry counter only when STATS is requested. CLIENT INFO/LIST watch counts are client metadata, not a new INFO section field. Nonzero expiry and reset witnesses cover RESP2/3 and section unions.
- FLIP admission and controller completion attribution share the existing cold transition mutex. No retry or lock was added to a reader. RL4.11 keeps read-local values copied through migration; its read-only capability stays zero while owner GET zero-copy remains separately configurable. The directed two-completion migration check extends every declared 2s RL4.11 leg.
- Blocking queues retain owner-local state and FIFO order; the new hash lookup includes hash, physical namespace and full key equality. The registry remains attached to the Shard, so ownership migration moves the same registry. Datafix2 mutation evidence is emitted by the served command, not registration or lookup; the BLMOVE watcher test observes a real park before waking and validates destination encoding.
- Registry destruction still follows owner/IO join. Wave 5's shutdown writeback retirement discards undeliverable notification batches and retires blocked operations before shard-owned registry references are released. Directed SAVE/NOSAVE shutdown arms require two observed blocked clients, peer EOF and exact reload contents. Persistfix2's admission policy does not alter dispatchfix's v2 snapshot routing reader/writer; the existing router-uniform old-file recovery job is included in the sweep.

### Offline inventory and trials (initial evidence)

The merged initial link has **156 R7 bodies in `tomo`, 156 in `tomo_db0`**, with exactly the headline's names and multiplicities. Older atomfix5 contributes no inventory delta; datafix2's one extra normal-namespace body already exists in the wave 6 headline. `docs/wave7/r7-inventory` records each frozen input and the empty merged/headline delta. The final R7 job, including its negative controls, remains required after tuning.

`docs/wave7/budgets` records PRE/POST IPA sizes, compile-only budget trials and linked-body scoring against all six frozen POSTs. Combined selected budgets improve initial strict identity from 482/567 headline-identical hot groups to 501/567; residual call-site review and local source controls are in progress. No instructions, registers, member offsets or opcode differences are masked.

The whole `atomic_batteries` release job is **NOT RUN**: it contains an explicit pipelined-versus-serial throughput measurement, which this lane is not authorized to run. Its non-rate correctness cases will run through the gate's ASAN battery in both modes. Efficiency, saturated FLIP, atomic throughput floor, ABBA measurements, NIC measurements and full iteration are also reserved to the maintainer. This limitation is separate from ordinary correctness failures, which remain visible in receipts.
