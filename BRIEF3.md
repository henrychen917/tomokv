# ROUND 3: FAST entries must join the storage prefetch (40M regression root cause)

Your ring delivery measured: io7ex1 p32 SET +3.6% (3/3), qc44 SET +0.5% (3/3), p1 wash — but
**40M-key p32 SET -7.3% (3/3) and 40M GET -0.9% (3/3)**. Root cause CONFIRMED in your code:
exSlice batch-prefetches a filtered pointer_batch only (server.c:22421,22424), so FAST entries
receive NO storage prefetch (the shipped level-1 flat SLOT+KVOBJ warm is worth +2-3% exactly
in the 40M DRAM-bound regime), and the pop-loop nextop lookahead also skips them
(server.c:22461: `kind==POINTER ? client_id : NULL`).

FIX:
1. Add a FAST-entry storage prefetch stage to the batch warm: for each FAST entry, the flat
   slot line is computable from entry->key_hash alone (per-db flat table pointer + mask + the
   same slot arithmetic flatFindForWrite uses) — issue the slot-line prefetch in the same
   staged/AMAC-shaped pass exPrefetchBatch uses, and the kvobj line as its second stage after
   the tag gate, mirroring the existing PFS_SLOT/PFS_KVOBJ semantics and the SAME L3 footprint
   gate (prefetching a cache-resident set is pure overhead — reuse the existing gate state,
   never re-derive it). Bump the existing prefetch engagement counters so gate cells still
   witness engagement.
2. Include FAST entries in the TOMO_PF_W_NEXTOP lookahead: the useful analogue of
   prefetch_dict/bucket for a FAST entry is its flat slot line; write it as a small helper
   shared with (1).
3. Do not touch anything else — the rest of the delivery is audited clean and its io7ex1/qc44
   wins must survive byte-identical.
WRITE CODE ONLY. Never run make/compile/servers/benchmarks — I re-run the same 10-cell battery;
acceptance = 40M SET/GET at parity-or-better with the qc44/io7ex1 wins intact. Commit clean.
