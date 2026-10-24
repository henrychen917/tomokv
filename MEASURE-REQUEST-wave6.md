# Wave 6 landing

## wave6 integration

Integration branch `cx-wave6`, headline `ef5204b2e`; no push. Work is in progress.
All builds and correctness work are restricted to CPUs 64–95, ports 26800–26899.
No performance generator or full iteration is authorized or run by this lane.

The six reports were read before their branches were merged, in the requested order,
with `--no-ff`: execfair, notifycompat, serverfix, dispatchfix, datafix1, prefetch.
Final branch states, including maintainer commits, are retained.
The writers-first information switch and executable POST-ALT plumbing are deleted;
historical receipts remain attributable. The supplied prefetch DELETE patch applies
without modification. Full-file equality to its isolated source conflicts with
retaining execfair/serverfix changes in the same files; prefetch-only equality is
being checked while preserving the integration (clarification pending).

### Row accounting

Headline 739/756 plus execfair 1, notifycompat 8, serverfix 8, dispatchfix 5,
datafix1 7, prefetch 0 gives **DQ=+29, DF=+29; required counts 768/785**.
`EXPECT_QUICK` and `EXPECT_FULL` remain 739/756, untouched. The fixture has all
785 declared full labels with their multiplicities; dispatchfix's five missing
fixture entries were added explicitly. Final collection line numbers and the
quick-tier exit will be recorded after the integration changes.

### Merge decisions and interaction audit

- OBJECT: retain notifycompat's non-touching/non-notifying lookup for all children;
  it also preserves dispatchfix's missing-key-before-policy precedence.
- XGROUP: dispatchfix moves option validation before lookup; its moved parser already
  contains wave 5's canonical ENTRIESREAD parser and exact negative-value error.
  The duplicate old parser was removed; wave 5's other stream fixes remain.
- CONFIG: retain serverfix's whole-parameter-list validation and enum parser;
  add datafix1's locale validation and publication. `Config::locale_collate` consumes
  eight additional reserved bytes after wave 5's hz fields; existing fields stay put.
- First merged build caught datafix1's static BITFIELD bound referring to the
  configuration range widened by wave 5/netfix. The storage bound remains separate;
  a directed repair and proof are pending.
- Slowlog: recorder creation already follows the threshold. Serverfix additionally
  moved a max-length atomic load onto every exact recording attempt; moving that
  load after the threshold is the targeted fix. Counts and directed proof pending.

### Validation status

NOT RUN yet: final merged correctness jobs, instruction matrix, budget trials,
PAD-A, and final freshness. The initial compile failure is retained in
`build/wave6/build-initial.log`; it is not a validation pass.
