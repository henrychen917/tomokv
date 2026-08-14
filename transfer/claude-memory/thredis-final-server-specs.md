---
name: thredis-final-server-specs
description: "Final eval server specced (NOT yet purchased): Threadripper 9965WX/7965WX, 8x16GB ECC DDR5 (8-ch), WRX90, 25GbE — the multi-CCD + real-NIC + NUMA-mode target"
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

Final eval server specs chosen 2026-07-03 (NOT yet bought): **AMD Threadripper 9965WX or 7965WX (24c/48t, MULTI-CCD)**, 8×16GB ECC DDR5 = 128GB on **8 channels**, **WRX90** board, **25GbE NIC**.

**Why it matters / what it unlocks:**
- **Multi-CCD**: the actual payoff regime for the de-contention work (#4 perthread-dirty, #75 multi-cdb, #A1 batched-clear, #A2 netstat shards) that washes on the 1-CCD 7700X ([[thredis-endgame-two-versions]]).
- **NUMA-ish testing**: WRX90 BIOS NPS modes / L3-as-NUMA expose per-CCD domains — test worker/ifid placement, exBindNumaLocal, cross-CCD SPSC costs.
- **25GbE real NIC**: the deep-uring backend's regime (loopback showed naive uring −4..−9%; VLDB guidance says fully-exploited uring wins only when I/O-bound). Also unlocks SO_INCOMING_CPU / RSS steering, busy-poll (needs NAPI), SEND_ZC+registered buffers.
- **8-ch DDR5**: DRAM-bound prefetch verdicts (stage ablation, #3 nextop, adaptive gate) must be re-measured — single-channel-starved conclusions from the 7700X may flip.
- 24c/48t: thread-scaling sweeps far beyond the 8-core configs; loadgen can live on dedicated cores WITHOUT SMT-sibling contention.

**How to apply:** keep EPYC/multi-CCD-gated TODOs framed as "Threadripper eval" now; plan bench harness for client on separate machine or dedicated CCD; the 25GbE tests need a load-gen box on the same link.
