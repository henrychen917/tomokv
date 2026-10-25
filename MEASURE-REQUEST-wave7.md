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
