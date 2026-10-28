# Wave 9 landing request

## wave9 integration

Worktree `/home/user/Projects/cx-wave9`, branch `cx-wave9`, headline
`a214652ec262aa9a5eeaeadf129c0ef76ba6c99c`. No push. All integration builds
and correctness processes use CPUs 64–95; listeners use ports 20000–20099.
Performance measurements and the full landing iteration belong to the maintainer.
This report is updated as work completes; pending work is not a pass claim.

### Merge and row ledger

Branches are merged with `--no-ff` in the requested order. The expected net
delta is +74 quick / +74 full, from 807/824 to 881/898. The protected EXPECT
assignments are never edited in this worktree.

| Lane | Requested delta | Integration disposition |
| --- | ---: | --- |
| woundfix | +4/+4 | Merged; last-placement and independent OOM/NX wound gaps retained |
| gaterows5 | +11/+11 | Merged; inline job deferred to protofix; placement stays an explicit make target |
| protofix | +4/+4 | Merged; one four-leg inline job, with original test file |
| crlffix | +1/+1 | Merged; central builders retained; later error sites audited below |
| multifix | +24/+24 | Merged; slowlog hooks composed into wave8b timing-selected body |
| streamfix | +6/+6 | Merged; StreamNode accounting and six roots retained |
| blockfix2 | +6/+6 | Merged; six gate rows; stream-removal diagnostic and failing evidence retained |
| at412c | +18/+18 | Merged through wave8/8b; all eighteen rows retained |

### Integration findings

- Woundfix merged through wave8b's timing-selected EXEC finalizer without a
  textual conflict. Semantic checks with escalated scripts remain pending.
- Layout placement remains a non-gate diagnostic until the wave-10 lineshare
  fixes. Its original failing evidence is retained in the gaterows5 report.
- Blockfix2's stream delete/re-create boundary remains a non-gate diagnostic
  until blockfix3. Its lane evidence will remain visible rather than counted
  as a passing row.

- Multifix was based before wave8b extracted `multi_execute.inc`. Its slowlog
  hooks and commit-bracket PAUSE publication were transplanted into that shared
  body; the tracked/untracked instantiations remain intact. Retry transfers
  retain the outer latency-enabled guard; slowlog accumulation remains separate.
  Directed tracking-off/slowlog and instruction checks remain pending.

### Validation and measurement status

Pending: merged correctness matrix, placement-probe hardening, Tcl reconciliation
and planted regression, compile-only budgets, complete changed-body inventory,
serverless instruction counts, frozen PRE/POST/PAD-A arms and SHA-256s.
No throughput claims. The requested nulls, fixed-anchor race, contended-script
storm and full landing gate are NOT RUN here: maintainer-owned measurements.

### Load-sensitive correctness hardening

- MONITOR: upstream `unit/introspection` sends BLPOP on a deferred connection,
  then polls INFO on another connection. `climon_gate` feeds MONITOR at each
  connection's IO dispatch; feeds to a remote monitor owner are asynchronous.
  There is no cross-connection dispatch/delivery order establishing BLPOP before
  INFO. A global ordering mechanism would add synchronization to command dispatch.
  The runner retries **only** `MONITOR log blocked command only once` once, on a
  fresh server, only after a complete file run with that sole assertion failure.
  The original failed receipt remains `before-monitor-retry.json`. Missing,
  duplicate, timed-out, unrelated or repeated failures remain failures. Nine
  serverless runner controls pass, including planted failure and retry controls.
- Placement: `_lib.probe_keys` now brackets the complete key discovery with
  LBSIGNALS observations and repeats up to four whole probes before yielding any
  keys. Perpetual movement and malformed evidence fail. `tests/debug.py` uses the
  same helper. Atomic torn/window release and ASAN boots additionally disable
  key-LB and automatic flips; no torn-read or window assertion changes. Nine
  gaterows contract controls pass, including never-stable negative control.
- Variant builds: trackfix, notifycompat and aoforder now stage the selected
  source's `tools/assert_map.py`, including reference archives. The other three
  schedule/build consumers (publishfix, lottery, racefix) already copy it.
