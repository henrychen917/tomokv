---
name: tomokv-topology-and-compute-findings
description: "DRAM-regime \"Redis wins\" is a config artifact; compute-bound worker-parallelism win is real (1.5-2.8x) but bandwidth-gated"
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

Bench investigation 2026-07-04 (1-CCD 7700X desktop, dual-channel DRAM ~50GB/s, 32MB L3), backing the README "Configurable execution topology" section.

**DRAM-resident regime-2 "Redis wins" = a config artifact, NOT architecture.** The acceptance table fixed `io4w4` (8 threads = 4 ingress + 4 exec). That cell (512B 1:9, 8M keys) is I/O-bound (syscall+parse throughput, scales with INGRESS thread count). At MATCHED ingress the two are a wash: Tomo io4w4 = 2.48M vs Redis `io-threads 4` = 2.45M; both scale identically as I/O threads rise. Tomo's split knob recovers the whole gap on the same 8 cores: **io6w2 = 3.26M ≈ Redis io-8 peak 3.22M**. io7w1 collapses (1.80M) = real tradeoff. So "Redis leads DRAM" was just Redis getting 8 ingress threads while Tomo used 4.

**Compute-bound (L3-resident BITCOUNT, same 8 cores) — Tomo beats Redis, win GROWS with command weight:** io4w4 vs redis-io8 = 1.54x @16KB, **2.83x @64KB, 2.80x @128KB**. Redis executes on ONE main thread (io-threads only parallelize I/O); Tomo runs N workers in parallel. Dragonfly far behind on BITCOUNT. This is the half fixed-model engines structurally can't answer. Matches the paper's mechanism (heavier cmd → bigger multi-core win; paper BITCOUNT-1MB 3.46x on server HW).

**"More ex than io" split nuance (user's claim):** on THIS box, BALANCED io4w4 beats worker-heavy io2w6 at every BITCOUNT size — io2w6 starves on ingress (2 io threads can't feed 6 workers for a tiny-reply cmd: 138 vs 218 GB/s L3). BUT the crossover toward worker-heavy is visibly approaching (io2w6 gap 1.86x→1.57x from 16KB→128KB) and ARRIVES on a multi-channel server where each worker commands its own memory channel (6 workers = 6x bandwidth). So worker-heavy pays when compute >> dispatch OR on bandwidth-rich HW — re-test the split-optimum on the [[thredis-final-server-specs]] Threadripper.

**SANITY-GATE CATCH (per [[thredis-sanity-gate-benching]]):** first compute bench (64KB/1MB, whole-DRAM working set) showed Redis WINNING + more-workers-not-helping = impossible for real compute parallelism ⇒ it was memory-BANDWIDTH-bound (807K×64KB≈51GB/s = DRAM ceiling; popcount trivial vs streaming). Thrown out, re-run L3-resident (≤16MB working set) to isolate popcount throughput. Lesson: BITCOUNT/large-value "compute" tests on a dual-channel desktop are bandwidth-bound unless kept L3-resident.
