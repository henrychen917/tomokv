---
name: thredis-saturated-benching-rule
description: "USER RULE — a single connection never saturates the server; bench throughput with memtier 8t x 25c at p1 AND p32, and investigate any command past -3%"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

A single-connection driver (one conn, one in-flight batch) measures the DRIVER, not the server —
it leaves the server ~idle, so throughput "regressions" and "wins" in that regime are meaningless
and the numbers drift +-15%. **Bench throughput at saturation: memtier_benchmark -t 8 -c 25 (200
connections), at BOTH pipeline 1 and pipeline 32.** That is the authoritative method (it's what the
fast-path gate uses); it drives SET p32 to ~7M ops/s and GET to ~8M, versus ~0.5M for one Python
connection (14x understated). **Then investigate every command worse than -3%** — re-measure 4x
interleaved to separate signal from box noise, and root-cause the survivors.

**Why:** two real throughput regressions in the queued/pre-audit work were INVISIBLE to a
single-connection bench and only appeared under saturation:
- HMGET one-pass (commit a40b3bad7): builds a per-call dict for >=4 fields. p1 flat, **p32 -20%**
  under load. DELETED (5b1763075) back to the stock naive loop. [[thredis-hashbytes-oN-regression]]
  is the sibling (byte-bounding, also delete).
- The per-call heap-churn pattern (malloc/dict/zcalloc per command) is the classic offender: free at
  low load, dominant at saturation.

**How to apply:** for a per-command before/after table, drive each command via memtier `--command`
(=value form; `--command-key-pattern=R` must FOLLOW its `--command`), pre/post interleaved so drift
cancels, parse the `Totals` line (ops = field 2; p50/p99/p99.9 = fields 6/7/8, in ms). Reserve any
single-connection number for pure round-trip LATENCY at idle, never for throughput. Extends
[[thredis-benchmarking-methodology]] and [[thredis-box-noise-truth]]; harness lives at
tmp/mt_bench.py.
