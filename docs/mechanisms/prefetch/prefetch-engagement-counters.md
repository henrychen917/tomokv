# Storage-prefetch engagement counters

## Exact counters

The retained owner-side storage mechanism has four per-worker counters:

| Field | Unit | INFO field |
| --- | --- | --- |
| `exThread.pf_batches` | One `exPrefetchBatch` invocation, counted before the L3 gate. | `tomo_prefetch_batches` |
| `exThread.pf_gated` | One invocation returned before storage lookahead because its footprint estimate was below the L3-derived threshold. | `tomo_prefetch_gated` |
| `exThread.pf_issued_slot` | One FLAT home-slot hint. | `tomo_prefetch_issued_slot` |
| `exThread.pf_issued_kvobj` | One live, tag-matched FLAT kvobj hint. | `tomo_prefetch_issued_kvobj` |

The entry/gate fields are in the worker control region; the two FLAT proof counters live at the end of `exThread`, outside its tuned hot block. (`src/server.h:2544-2549`, `src/server.h:2655-2667`)

`pf_batches` increments once at entry and `pf_gated` increments only on a gate return. (`src/server.c:23977-23980`, `src/server.c:24036-24039`) FLAT slot and kvobj counts are accumulated locally during the storage passes, then folded into the worker totals once at function exit. (`src/server.c:24072-24098`, `src/server.c:24127-24135`, `src/server.c:24154-24155`)

DICT bucket, entry, and value hints deliberately have no individual issue counters. There is also no generic stage-issue counter and no EX/IO cross-node counter: those belonged to the removed operand-pipeline and message/reply-prefetch experiments.

## INFO folding

`genRedisInfoString` sums all workers' four plain counters into local totals and emits exactly the four INFO fields listed above. (`src/server.c:21755-21763`, `src/server.c:22395-22398`) The worker is the sole writer; INFO's unsynchronized reads are acceptable because these values are diagnostic statistics, not protocol state. (`src/server.h:2544-2549`)

Useful interpretations are:

- `gated / batches`: fraction of calls stopped before storage lookahead.
- `issued_slot / batches`: FLAT home-slot hint density.
- `issued_kvobj / issued_slot`: fraction of hinted FLAT home slots that were live and tag-matched when the dependent pass consumed them.

These ratios are engagement evidence, not performance claims; the hints can still be useful, late, redundant, or compiled to no-ops depending on platform and workload.
