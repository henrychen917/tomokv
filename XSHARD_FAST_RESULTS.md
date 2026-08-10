# Cross-shard-faster: test & bench results (fork `2s-shared-keyspace-dev`)

Box: 16-core laptop, server pinned 0-7 (io4/ex4), client 8-15, 16384 buckets, loopback.
All timings are 20-iteration loops via redis-cli unless noted; ~1.3 ms/iter of that is
client-process spawn (PING control), quoted "op cost" is spawn-corrected. Laptop absolute
numbers drift — deltas/interleaved comparisons are the signal (final numbers → Threadripper).

## Verdict table

| # | Suggestion | Status | Result |
|---|-----------|--------|--------|
| 0 | **Localfast: single-owner read-only multi-key → real proc** *(discovered by these benches)* | **IMPLEMENTED + SHIPPED** (`ab72fbe69`, default on, 16/16 differential gate) | co-located SINTER 10k-pair **~2.5 → ~0.7 ms/op (~3.6×)**; MGET neutral (coalesce already good) |
| 1 | Semi-join probe shipping (INTER family) | baseline measured; prototype **in progress** | gather curve is linear ~74 ns/member: 1k=1.45ms → 500k=36.9ms/op vs near-flat predicted for probes → **~25× headroom at 500k/10 skew** |
| 2 | Owner-compute (ship small inputs to big owner) | subsumed | k=2 case ≡ semi-join round 1; covered by #1 |
| 3 | Co-access affinity migration (co-locate hot pairs) | quantified; policy = S1 follow-up | worth **~3.5× op-level** *after* #0 (before #0 it bought nothing — same-worker paid full gather; that's why #0 exists). Needs S1's O(1) handoff + Schmitt-banded affinity score |
| 4 | O(1) value ownership transfer for 2-hop moves | quantified; needs shared kvstore (S0.2b) | DUMP+RESTORE gap is size-linear: **90 µs @64KB, 1.66 ms @1MB, 5.97 ms @4MB** per op (cross-shard RENAME of 4MB = 5.4× same-shard). Transfer ≈ erases it |
| 5 | Worker→worker HOP2 mesh | measured; **parked** | 2-hop adds only **~1 µs/op** over same-shard on loopback SPSC — nothing to win here; revisit on real NIC/NUMA only |
| 6 | Bloom pre-filter (big∩big) | analytic; parked | only pays when the *smallest* input is also large; fold into #1 later if big∩big shows up in traces |

## Raw numbers

**A) Co-location delta (SINTER 10k∩10k, 1k overlap, ms/20):**
- pre-localfast: same-worker 76, cross-worker 70 (≈ none — gather paid either way)
- post-localfast: same-worker **40** (on) vs 76 (off), cross-worker unchanged ~70

**B) Value-transfer opportunity (RENAME ping-pong, ms/100 ops, SETRANGE-built values):**
| size | same-shard | cross-shard | gap/op |
|---|---|---|---|
| 64 KB | 138 | 147 | 90 µs |
| 1 MB | 135 | 301 | 1.66 ms |
| 4 MB | 137 | 734 | 5.97 ms |

**C) Hop latency (sequential, single socket, µs/op):** GET 15.3 · RENAME same-shard 17.1 ·
RENAME cross-shard (2-hop) 17.9 → marginal 2-hop cost ≈ 1 µs.

**D) Gather-volume curve (SINTER big×10, µs/op):** 1k=1450 · 10k=2000 · 100k=7500 · 500k=36900.

## Bench-hygiene notes (sanity-gate catches during this campaign)
- First value-transfer run showed a zero gap at 1 MB — the CLI silently refused a >128KB arg,
  so both sides measured error latency. Values now built with SETRANGE and length-verified.
- Raw loop timings include ~1.3 ms/iter redis-cli spawn; always subtract the PING control.
- An unpinned run read 2× the pinned throughput — pinning per the methodology is mandatory.
