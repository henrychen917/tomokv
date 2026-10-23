# Transaction ordering constants ledger

The authoritative `scratchpad/constants-ledger.html` is absent from this
worktree. These are the reviewable addendum rows for design-txnfix appendix B,
approved by the owner on 2026-10-11. They are correctness and liveness bounds;
no measured optimum is claimed.

| Constant | File | Value / unit | Verdict | Reason and falsifier |
|---|---|---|---|---|
| `kTxnWriterDoomBound` / `DEBUG TXN-OCC-LIMIT` | deleted | formerly 8 | DELETE, txnorder D8 | Executing units are immune; plain writers wait. No writer-doom fallback remains. |
| `kTxnIntentsPerShard` | `src/cmd/multi.h` | 256 | Legacy test/API constant | EXEC no longer registers intents; Stage B uses one lifetime anchor per participant. Generic intent-store tests retain this bound. |
| `kTxnClaimsPerShard` | same | 256 keys | KEEP, design §2.3 | Larger key sets take one whole-shard hold in the strongest required mode. The directed claim fixture checks mode upgrade and cap. |
| `kTxnRetryBackoffMin` | same | 1 IO pass | KEEP, owner approved | A cancelled attempt returns through the IO inbox before re-dispatch, rather than spinning within its final owner task. |
| `kTxnRetryBackoffMax` | same | 1,000,000 ns | KEEP, owner approved | Caps backoff for conflicts with already admitted groups; no new per-operation timer or shared increment. |
| `kTxnExclusiveDrainMax` | deleted | formerly 1 s | DELETE, txnorder D8 | There is no exclusive token, admission bit, fence or drain timeout. |
| Script restages | existing server bound | 8 | KEEP, D4 | Claim conflicts yield the APPLY wave and use the existing TRYAGAIN contract. |
| `TxnPhase` | `src/cmd/multi.h` | Placing=0, Executing=1, Wounded=2 | KEEP | Only Placing can be wounded; executing holders are immune. |
| EXEC started mask / group started mask | `multi.inc` / `txn_group.inc` | 8 / 4 | KEEP | Owner-local start distinguishes an ordinary writer's predicate from a blind group's predicate. |
| Placement widener | `DEBUG TXN-PLACE-DEFER` | 0..10,000,000 µs | Test only | One-shot, first attempt only; non-lead shards park before claims. Zero allocates no hook state. |
