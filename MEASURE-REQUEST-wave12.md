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
