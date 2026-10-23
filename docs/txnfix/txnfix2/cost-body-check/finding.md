# Stage B cost-bar failure

The default POST destructor adds `mov 0x310(%r13),%rbx`, `test %rbx,%rbx`,
`je ...` to load and skip a null `group_attempt`. Every ordinary cross-shard
MGET reaches this destructor through xshard_destroy. PRE has no such check.
These are three new executed instructions even with no transaction in flight,
not merely an address/layout difference. Moving cold helper bodies or changing
inlining budgets cannot remove this ownership check from the current design.

Therefore this Stage B candidate fails the specified zero-new-instruction bar.
Per design section 5 / original prompt, stop Stage B implementation and keep
its commits for review. No throughput result or Stage B acceptance is claimed.
A different lifetime representation is required before it can be accepted.
The 12 additional ordinary hot-body differences are also retained in the full
identity inventory, rather than called intended changes.
