# Shard-and-fold the node-shared write counters (stall register item 3)

CONTEXT (register item 3, verified sites): kvstore.c key_count (__atomic_add_fetch at ~1116)
and flatstore.c used/tombs (atomic_fetch_add/sub at ~252-287) are lock-prefixed RMWs on lines
SHARED by every worker of a node, 2-3 per insert/delete — the one genuinely CONTENDED atomic
class on the write path (overwrite SET skips them; insert/churn pays).

TASK: convert each to per-worker sharded counters folded on read:
- key_count: per-worker cache-line-isolated deltas; kvstoreSize() and every reader folds
  (audit ALL readers first — dbsize, INFO, resize sizing, defrag, iterators — and route them
  through one fold helper; sizing decisions may tolerate slight staleness, EXCEPT the flat
  resize trigger arithmetic in flatstore.c which reads used+tombs per insert: for THAT, keep
  the trigger exact per-table but make used/tombs per-worker-sharded per TABLE with the
  trigger comparing the folded value only every K inserts (K derived from headroom: at 70%
  trigger and 30% headroom, checking every 64th insert cannot overshoot the panic-wait path
  given per-worker rate bounds — show the arithmetic in a comment).
- The flatstore insert-full WAIT path (dbSetAtLinkWithFlatRetry) must still see exact-enough
  state to make progress — verify its diagnostics read folded values.
WITNESS: fold-call counter + max observed skew, in INFO. notifyguard must stay honest.
WRITE CODE ONLY. Never run make/compile/servers/benchmarks. If a reader requires exactness
that folding breaks, SAY SO per-reader and leave that reader on a folded-with-fence path
rather than weakening it silently. Commit clean.
