# snapfix evidence

Base: `a214652ec` on branch `cx-snapfix`. All commands use CPUs 16–31;
correctness servers use 16–23, drivers 24–31, and ports 20200–20299.
There are no performance measurements in this lane. The report is
`MEASURE-REQUEST-snapfix.md` at the worktree root.

`tests/at412.py` and `tests/at412_diagnostics.py` are copied unchanged from
`cx-at412c`, whose resolved commit is in `provenance/at412c-commit.txt`.
The historical shutdown stack, snapshot-storm results and diagnostic README
are copied from that same commit. The upstream report's section 6 and the
2026-10-27 REGISTER addendum assign XS-SHUT-1 and SNAP-STORM-1 to this lane.
These diagnostics remain separate from the directed gate assertions.

`tools/snapfix_reproduce.py` runs the diagnostics under an outer process-group
watchdog and records every command, return code and binary SHA-256. Geometry:
eight physical CPUs, 16 shards, databases 16, atomic 1, balancing and auto-FLIP
off; 1s has read-local 1, 2s has ratio 6:2 and read-local 0. Both engines run.
Zero means NOT REPRODUCED at the recorded geometry and attempt count, not proof
of absence. Failures retain the original exception and process exit.

| Directory | Contents | Produced by |
|---|---|---|
| `pre/`, `post/` | at412 diagnostics, 5 × 30 s per cell, on PRE and on the final POST | `tools/snapfix_reproduce.py` |
| `stacks/` | PRE stacks of the shutdown abort, the snapshot wait and an EXEC storm | `tools/snapfix_stacks.py` |
| `rootcause/` | gdb scripts and their output: intents at the XS-SHUT-1 abort; two live SNAP-STORM-1 EXEC cores (stall state, inbox lanes, placement blockers, live INFO deltas, socket queues) | `tools/snapfix_storm_capture.py`, `rootcause/gdb/` |
| `rows-pre-post/` | `tests/snapfix.py` results per case, PRE and the first POST | `tests/snapfix.py` |
| `attribution/` | the three cases against single-fix arms | `build/snapfix/attr-*.sh` (scripts recorded in the report) |
| `proof/<run>/` | gate-interface receipts: partial ledger, per-job verdicts, command line, binary SHA-256 | `tools/snapfix_record.py` |
| `neighbours/<arm>/` | SHUTDOWN SAVE, SIGTERM, FLUSHALL, BGSAVE + FLIP and AOF-rewrite storms | `tests/snapfix_neighbours.py` |
| `instructions/` | serverless command-scope traces, PRE vs POST | `tools/snapfix_scope.py` |
| `budgets/` | compile-only inline-budget trials, survey, all-body scores, selection | `tools/snapfix_budget.py`, `tools/snapfix_budget_bodies.py` |
| `identity/` | whole-link function-body identity, PRE vs final POST | `tools/snapfix_identity.py` |
| `unit/` | the teardown unit check and its negative control | `build/atomic-survivors-unit txn_intents` |
| `pad-a.json` | PAD-A twin and POST-layout image digests | `tools/snapfix_pad.py` |
