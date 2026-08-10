# Cross-shard scatter-gather — implementation design (deferred from overnight run)

DECISION: deferred to attended implementation. Reason: this rewires the §4.8 concurrent
reply path (group completion + reassembly). Concurrency bugs there are probabilistic and
cannot be assured by unattended overnight testing; the correctness bar ("we CANNOT break
that") makes shipping it unvalidated unacceptable. RDB (deterministic, roundtrip-tested)
WAS landed; cross-shard needs careful, reviewed, attended work. Integration points are all
identified below, so implementation is straightforward to pick up.

## Scope (single source of cross-shard need)
Multi-key single-command-with-many-keys: MGET, MSET, multi-key DEL/UNLINK, EXISTS, MSETNX.
(Keep MULTI/EXEC and scripts out of scope — separate problem.)

## Where keys -> shards
`workerIndexForKey(keyptr, len)` (server.c, added for RDB) = xxh64(key) & my_worker_dispatch_mask.
Single source of truth — use it for the split.

## Dispatch split (server.c, the per-command dispatch ~line 4930, the `client *fake = ...` path)
Add a branch BEFORE the single-fake path: if `isCrossShardCommand(c->cmd)`:
1. Group keys by shard: for each key arg, w = workerIndexForKey(key). Build, per touched shard,
   a sub-argv (the command verb + that shard's keys), remembering each key's ORIGINAL position.
2. The ring slot's primary fake becomes a GROUP HEAD holding:
   - `int pending` (atomic) = number of distinct shards touched,
   - per-sub: a sub-fake (own argv = the per-shard subcommand) + the original-position map,
   - the command type (for reassembly).
3. Dispatch each sub-fake to its shard worker (workerQueuePush), each with its own cdb.
4. Do NOT set the slot ready bit yet.

## Completion (worker side, server.c workerThreadMain signal sites)
A sub-fake's completion must NOT directly set the parent slot bit. Instead:
- atomic_fetch_sub(&group->pending, 1, release); if it was the LAST (result==1), set the
  parent real's reply_cdb[slot] bit (release) so the IO drain picks up the slot.
- This is the ONLY new concurrent rule. Use release on the decrement, acquire on the drain's
  combined-mask read (already there). The last decrementer's release publishes all sub-replies.

## Reassembly (IO drain, server.c handleWorkerReplies, when the slot bit is a GROUP)
When draining a group slot: gather the sub-fakes' replies and assemble ONE reply for the real
client, in ORIGINAL key order:
- MGET: emit `*n\r\n` then, for original position i, the value from the sub-fake that owns key i
  (parse each sub-fake's array reply, or have sub-fakes write values into a positional buffer).
- MSET: all sub OKs -> `+OK`. DEL/EXISTS: sum the integer replies. MSETNX: AND of the sub results
  (note: MSETNX is not atomic across shards — document as best-effort or refuse).
- Then retire all sub-fakes (commandProcessed each), advance flushid, clear the slot bit.

## Cleanest implementation choice
Reuse the EXISTING fake machinery: allocate the sub-fakes from a small per-real pool (or the
ring's spare slots), give each its own fake_slot-equivalent completion via the group counter
(NOT the parent bit). Keep the assembly buffer on the group head. This avoids a second reply ring.

## Edge cases to test (with a dedicated multi-key correctness oracle)
- all keys in one shard (pending==1, fast path), empty key list, duplicate keys,
- a sub-shard error (propagate), MGET with some-missing (nils in correct positions),
- pipeline interaction (group slot vs single-key slots interleaved), churn/free during a group,
- ASAN + invariant oracle that checks MGET returns each key's self-ID value at the right position.

## Validation gate before shipping
ASAN-clean + a multi-key self-ID oracle (extend thredis-trace-replay or thredis-stress with
MGET/MSET that verify positional correctness) + toggle-storm + churn. Default-OFF toggle until
clean, like multi-cdb was.
