# Wave 12 integration and measurement request

## wave12 integration

Work in progress on `cx-wave12`, based on headline `e32b04a44`. No push.
Owner approval D12 authorizes design A. The three lane reports, including
flushfix2's inherited findings and the design review, were read before merging.

Merge order: `15acf5102` (cx-flushfix3), `83b29aaa5` (cx-trackorder),
`3adae5254` (cx-maxmemrace), all with two-parent `--no-ff` merges.
Only the FLUSH merge conflicted, in five Makefile inline budgets. Initial
resolution preserves both source changes and applies the additive budget
deltas pending compile-only re-derivation. Lane branches remain untouched.

All builds and authorized correctness work use CPUs 64–95 and ports
20000–20099. Performance measurements, load generators and the full iteration
are reserved for the maintainer. No throughput claim is made.

Pending: semantic interaction checks, complete row accounting, named Tcl-skip
sweep (three isolated attempts in each mode), compile-only body audit, command
instruction scopes, selected-job correctness coverage, production freshness,
PRE/POST/PAD-A delivery and SHA-256 receipts. Pending work is NOT RUN until a
receipt below establishes otherwise. EXPECT_QUICK/EXPECT_FULL remain unchanged.

### Exact source-declared rows

The headline declares 977/994. The merged source declares **999/1016**, DQ=DF=+22,
with no removed label. `docs/wave12/row-inventory.json` records every row against
its collector LINE and the quick exit. Flushfix2 adds 14 directed + 2 lifecycle
rows, flushfix3 adds 4, trackorder +1, maxmemrace +1. All are before the quick exit.
The owner should set EXPECT_QUICK=999 and EXPECT_FULL=1016 at landing.

The initial source census falsely reported 1001/1018: gate_ledger_fixture ignored
conditional assignments in job_flushfix2, inventing ASYNC legs for three cases
and omitting FLUSHDB. The integration writes the same seven case/command/mode
combinations explicitly, extends the static parser's finite split grammar to
colon-separated cells, and adds a directed 14-label product check. Runtime
coverage and row count are unchanged; no test was removed. The checked-in label
fixture now matches the actual declarations, including FLUSHDB. The earlier
incorrect inventory remains visible in commit 787fd64ae.

### Semantic audit, before runtime proof

- R3 range conflict detection remains on the script validation path. Cached
  script metadata owns immutable source/flags; the persistent interpreter's
  activation context is rebound for each run. Neither cache substitutes for
  the current activation cut, so a retained compiled body cannot hide FLUSH.
  PAUSE classifies scripts from the same no-writes metadata before execution;
  FLUSH is classified as a write and its range does not mutate script flags.
- The FLUSH unit retains atomic admission through collapse. FLIP/LB drains
  therefore wait for its admission to retire. Wave11's stage actions still
  use flip_stage_owed; the FLUSH continuation wake remains unconditional.
  The live eight-leg witness remains required; this source argument is not
  an abort-free runtime result.
- climon_flush_completed still runs at ROB retirement after all shard effects
  finish, before reply assembly, with the originating Op still Done. Thus the
  trackorder helper sees the intended SYNC/default boundary; ASYNC retains
  deferred OOB emission. Separate REDIRECT streams have no total byte order.
- CONFIG remains an AllShards operation, separate from Kind::Flush. Every
  fragment applies the latest memory configuration on its current owner;
  configure_maxmemory changes admission/eviction settings, not range records,
  floor eligibility or poison lifetime. Existing MVCC guards keep eviction
  from destroying retained FLUSH preimages. No added fragment discriminator
  reaches ordinary GET/SET/INCR.
- The central reply-builder audit is extended in docs/crlffix/audit.md and
  wave12-added-sites.json. No new raw error/status writer was found.
