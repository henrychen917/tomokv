# Transaction OCC constants ledger

The authoritative `scratchpad/constants-ledger.html` is absent from this
worktree. These are the reviewable addendum rows for design-txnfix appendix B,
approved by the owner on 2026-10-11. They are correctness and liveness bounds;
no measured optimum is claimed.

| Constant | File | Value / unit | Verdict | Reason and falsifier |
|---|---|---|---|---|
| `kTxnWriterDoomBound` | `src/cmd/multi.h` | 8 writer-caused cancellations | KEEP, owner approved | Matches the existing script OCC/pop retry bound. `DEBUG TXN-OCC-LIMIT` overrides it; zero requests exclusive execution immediately. X1 forces fallback after one cancellation. Age wounds and publication waits do not consume the bound. |
| `kTxnIntentsPerShard` | same | 256 exact intents per unit per shard | KEEP, owner approved | Promotes to one wildcard intent to bound an individual unit's writer-side list footprint. The aggregate list can contain more than 256 intents when several units overlap. `txn_intents` checks the PIN-prefix invariant and wildcard accounting. |
| `kTxnRetryBackoffMin` | same | 1 IO pass | KEEP, owner approved | A cancelled attempt returns through the IO inbox before re-dispatch, rather than spinning within its final owner task. |
| `kTxnRetryBackoffMax` | same | 1,000,000 ns | KEEP, owner approved | Caps backoff for conflicts with already admitted groups; no new per-operation timer or shared increment. |
| `kTxnExclusiveDrainMax` | same | 1,000,000,000 ns | KEEP, owner decision on fallback remains open | A valve lowers the exclusive admission bit if pre-existing work cannot drain. `atomic_txn_exclusive_drain_timeouts` must remain zero in proof. This is not permission to declare a wedged attempt successful. |
