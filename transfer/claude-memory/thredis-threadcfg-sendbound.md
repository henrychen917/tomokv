---
name: thredis-threadcfg-sendbound
description: Thread-config bench — more WB threads scale 3-stage UP on send-bound (large) values while 2-stage scales DOWN; 3s +32% at 16KB/12t
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

Thread-config comparison (2026-06-28, raw in overnight_sweep/threadcfg.tsv). Server c0-7 = 8 P-cores so >8 threads OVERSUBSCRIBE; loopback; jemalloc; memtier -c32 P16; 3 reps median. 3-stage WB-count vs 2-stage thread-count.

Medians ops/s — cols: 64B/1:9 · 256B/1:1 · 1024B/1:1 · 16KB/1:1
  2s_io4ex4  ( 8t):  5.44M  3.83M  2.43M  374k
  2s_io5ex5  (10t):  5.51M  4.11M  2.30M  313k
  2s_io6ex6  (12t):  4.82M  3.54M  1.94M  262k
  3s_i4e4w2  (10t):  4.29M  3.69M  2.14M  329k
  3s_i4e4w4  (12t):  3.69M  3.25M  1.85M  346k

KEY FINDING: at 16KB (send-bound) more WB scales the 3-stage UP (w2 329k -> w4 346k) while the 2-stage scales DOWN with threads (374k@8t -> 313k@10t -> 262k@12t; its IO threads do recv+exec+send serially, so extra threads just oversubscribe the serial send). 3s_i4e4w4 (12t) = +32% over 2s_io6ex6 (346k vs 262k). Matched 3s/2s ratio CLIMBS with value size: 10t 0.78(64B)->0.90->0.93->1.05(16KB); 12t 0.77->0.92->0.95->1.32. At small values more WB HURTS (w2->w4: 64B -14%, 256B -12%, 1024B -14% — send is trivial so extra WB = pure oversubscription); 3-stage stays ~22% behind (dispatch-bound, the ifid->ex->wb hop is overhead with nothing to parallelize).

IMPLICATION: the 3-stage advantage = (value size × thread count) = how send-bound the workload is → scale WB threads with send-bound-ness, not a fixed wb=1. This shows DESPITE 8-P-core loopback stacking the deck (oversubscription + free network); the payoff regime (send costs real cycles + WB on its own core) is real-NIC + EPYC. The 16KB cells only became measurable after the large-reply wedge fix [[thredis-3stage-churn-wedge]]. See [[thredis-overnight-bench-results]], [[thredis-tiered-pool-validated]].
