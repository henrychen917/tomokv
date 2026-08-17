# `exPrefetchBatch` — always-on owner-side storage lookahead

## Scope

`exPrefetchBatch(client **batch, int n)` warms storage lines for a batch already owned by one EX worker. It has no runtime knob and is called once, immediately before that worker executes the popped batch. (`src/server.c:23961-23966`, `src/server.c:25054-25055`)

This is deliberately a storage mechanism. It reads command operands normally and never prefetches the fake client, `argv`, key object, or key bytes. It also has no per-operation state machine, rotating scoreboard, future-message carrier, next-run ring hint, or reply-buffer hint. (`src/server.c:24075-24122`)

The hints are advisory only. The function returns no lookup result; command execution remains authoritative. A usable DICT hash is carried forward solely through the existing execution-time hash-hint path. (`src/server.c:23961-23965`, `src/server.c:24112-24119`, `src/server.c:24239-24245`)

## Ordered storage passes

The fixed scratch arrays hold one FLAT slot or DICT pointer, one tag/index, one DICT entry, and one branch tag per position in the worker's bounded pop batch. (`src/server.c:23967-23972`, `src/server.c:24067-24073`)

1. **Slot or bucket.** For every command with a normal key operand, the worker selects the owner-side storage. A valid FLAT pointer proof uses the carried hash to select and prefetch the home slot. Otherwise the worker selects the DICT, computes and records the hash and bucket index, and prefetches the bucket-head cell. Both reads and writes receive this first storage hint; only read-only commands are marked for a dependent pass. (`src/server.c:24075-24122`)
2. **KV object or entry.** A FLAT read acquire-loads the hinted slot, checks live state and tag, then prefetches the decoded `kvobj`. A DICT read consumes the hinted bucket-head cell and prefetches its first entry. The full first scan separates these dependent accesses from their predecessor hints. (`src/server.c:24124-24144`)
3. **DICT value.** For the adaptively bounded prefix `j < w4`, a non-null DICT entry is decoded and its unified key/value object is prefetched. FLAT is already complete after pass two. (`src/server.c:24146-24152`)

The storage pass order is therefore FLAT slot -> tag-matched kvobj, or DICT bucket -> entry -> value. There is no operand-prefetch prefix around it.

The ordinary input lane passed to `exSlice()` has exactly one producing I/O identity and one consuming worker. The structure's field order separates cache-line-aligned atomic `head`, cache-line-aligned atomic `tail`, and cache-line-aligned `client *jobs[2048]`; consumer-private `cached_tail` and atomic execution frontier `retired` share the head region, while producer-private `cached_head` and `staged_tail` share the tail region. `retired` is not part of job publication: the worker release-stores the post-pop `head` there only after executing the batch, for the reshard quiescence test. Atomic version publication uses owner-private records, not an `exQueue`, and never reaches `exPrefetchBatch()`. (`src/server.c`, `src/server.h`)

## Engagement and safety

The L3-derived footprint gate can skip all storage hints for a cache-resident shard; see [the L3 footprint gate](l3-footprint-gate.md). The worker still clears stale DICT hash validity before either returning at the gate or scanning an engaged batch. (`src/server.c:24013-24039`, `src/server.c:24078-24083`)

The FLAT dependent load uses `memory_order_acquire`, matching the table's release/acq_rel publication. (`src/server.c:24127-24135`, `src/flatstore.c:250-251`, `src/flatstore.c:274-285`) `exSlice` enters the FLAT quiescence section before touching the table and leaves it after the batch, so resize cannot replace a retained slot pointer between passes. (`src/server.c:24688-24707`, `src/server.c:25415`)

On supported compilers `redis_prefetch_read` is a high-locality read hint; otherwise it is a no-op expression. (`src/config.h:130-136`)

## Observability

The function records entries, gate returns, FLAT slot hints, and tag-matched FLAT kvobj hints. Those four counters and their INFO names are documented in [prefetch engagement counters](prefetch-engagement-counters.md). (`src/server.c:23979`, `src/server.c:24037`, `src/server.c:24154-24155`)
