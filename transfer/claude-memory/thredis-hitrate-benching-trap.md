---
name: thredis-hitrate-benching-trap
description: "GET benchmarks were inflated ~40% because memtier's warmup never populated the keyspace — most GETs were cheap misses; hit rate is a hidden axis that must be pinned to 100% and reported with every read number"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

2026-08-04. Every GET number in this project's history is suspect unless it reports `dbsize`.

## What happened

`memtier_benchmark --key-maximum=100000` with a `--ratio=1:0 -n <small>` warmup populates only a
RANDOM SUBSET of the keyspace. Measured: `dbsize` 22,124 of 100,000 (and 8,856 of 40,000). The
measurement phase then reads uniformly over the full `--key-maximum`, so **~78% of GETs were
MISSES** — which return nil with no value fetch, no reply body, and no allocation. That is a much
cheaper command than a hit.

### The exact mechanism: identical client seeds

Not "the warmup was too short" — `-c 8 -t 4 -n 25000` is 32 clients x 25,000 = 800k writes, which
by coupon-collector should cover 100k keys ~100%. It covered 22%. **Without
`--distinct-client-seed`, every client uses the SAME RNG seed and therefore writes the SAME key
sequence**, so the distinct-key count is `-n` (25,000), not `-n x clients`. Coupon-collector on
25,000 draws predicts `100000*(1-e^-0.25)` = 22,120 keys; measured 22,124. Exact.

Consequence: adding clients or threads to a warmup does NOT populate more of the keyspace. Only
raising `-n`, or using a sequential pattern, does. This is also why the flag matters on the
MEASUREMENT phase for a different reason (all clients hammering one key sequence is not the
uniform load anyone intends).

Effect on p32 GET (io6ex2, `-t8 -c25 -d32`, same binary, same box, minutes apart):

| keyspace state | ops/s |
|---|---|
| partially populated (22% of 100k) | 9.54M |
| **fully populated (100% hit rate)** | **6.94M** |

A 37% inflation. It also made "identical" arms disagree by 6% (8.98M vs 9.54M) purely because the
warmup `-n` differed between two harness scripts — which by [[thredis-box-noise-truth]] (±2% when
exclusive) reads as a bug, and was one.

## Why it fooled us for so long

SET is unaffected — it never reads — so `p32 SET 7.3M` stayed rock stable across every harness and
matched the owner's recollection exactly. Only the GET side moved, which looks like "a GET-path
regression" rather than "a harness difference". The historical 9.8M GET was REAL but measured on a
mostly-empty DB; the honest fully-populated peak is 9.0M at io5ex3.

The config RANKING also changes: partially populated made io6ex2 (8.98M) look competitive with
io5ex3 (9.23M); fully populated it is not close (6.94M vs 9.00M). So a mis-populated keyspace can
move the measured OPTIMUM, not just the magnitude — which matters because those optima are the
ground truth the flip controller is validated against.

## The rule

Populate the keyspace EXPLICITLY and prove it:

```sh
memtier_benchmark --ratio=1:0 -n $((KEYMAX/8)) -c 1 -t 8 \
    --key-minimum=1 --key-maximum=$KEYMAX --key-pattern=P:P --pipeline=32
redis-cli dbsize            # MUST equal KEYMAX
```

then report `dbsize` and the measured `keyspace_hits/(hits+misses)` alongside every read number. A
read benchmark without a stated hit rate is not a comparable number. Same family as
[[thredis-vacuous-validation-trap]]: the run "succeeded" and produced a plausible figure, so nobody
checked what it was actually measuring.

Related: [[thredis-sanity-gate-benching]], [[thredis-benchmarking-methodology]],
[[thredis-ab-harness-traps]], [[thredis-box-noise-truth]].
