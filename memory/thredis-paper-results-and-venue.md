---
name: thredis-paper-results-and-venue
description: THredis paper already beats baselines on a 7800X; publication-venue strategy and the two comparison axes
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

The THredis paper's headline result (BASE THredis, no today's opts), on a Ryzen 7
7800X (8-core, SINGLE-CCD Zen4), matched core count/config, ON PIPELINED WORKLOADS:
  - ~1.6x vs default Redis at 8 IO cores
  - ~1.4x vs DragonflyDB at 8 shards
Beating Dragonfly (the strong shared-nothing multithreaded SOTA) 1.4x clears the
"beat SOTA" bar. CRITICAL caveat: the win is ONLY on pipelined workloads (the
architecture amortizes per-op dispatch across the pipeline); off the pipelined path
the advantage shrinks/ties — frame pipelined as the target throughput regime, and
characterize the crossover honestly. Win is from the ARCHITECTURE (topology-
independent, shown on single CCD); today's opts are incremental on top.

KEY DISTINCTION — two different comparison axes, do not conflate:
1. THredis-vs-baseline (the paper's headline): big win, even on single-CCD 7800X
   => the win comes from the ARCHITECTURE (execution pipelining, shard-per-core,
   single-writer-per-key) + the UNIVERSAL opts (prefetch, hash-carry, value-forward,
   zero-copy). Topology-INDEPENDENT. This is the real result.
2. opt-vs-opt ablation (the 2026-06 single-NUMA laptop sweep): the CCD-targeted
   opts (S3 mask-isolate, S6 per-thread stats, S4 batch-push, coalesce-signal) are
   within noise there because a single-NUMA box has no cross-CCD traffic to cut.
   Expected, NOT a weakness. See [[thredis-opt-and-testers]].

ROLE OF THE EPYC/XEON BENCH (planned): not to prove a win exists (already shown on
7800X) but to produce the two figures that elevate a parallel-systems paper —
(a) the scaling curve (throughput vs cores 8 -> 64/96/128), and (b) the incremental
benefit of the CCD-targeted opts at 8-16 CCDs (where naive shard-per-core loses to
coherence traffic). Hardware spec'd: ideal = single-socket EPYC Genoa/Turin (many
CCDs, 12-ch DDR5); min = Threadripper (>=4 CCDs); Intel Xeon also valid (tiled
Sapphire/Emerald/Granite + SNC) for a cross-vendor generality result.

AUTHOR/ADVISOR CONTEXT (decisive for venue): author is an MS EE/computer-arch student
at USC; advisor is ALGORITHMS-leaning; the project started as a PARALLEL-COMPUTING class
project. Author is doing Taiwan mandatory military service, weekends-only, finishes
~Sept 2026.

VENUE VERDICT (web-grounded scout, 2026-06): best fit = PPoPP (#1, parallel-programming
flagship), SPAA (#2, parallel algorithms, theory-credible), USENIX ATC (#3, artifact
home). DaMoN = low-variance workshop. DEPRIORITIZE the arch flagships (ISCA/MICRO/HPCA/
ASPLOS) — WRONG DOOR: they score hardware mechanisms and THredis runs on stock silicon
with no proposed HW. DB venues (SIGMOD/PVLDB) are off-community for this author.
REFRAME for PPoPP/SPAA: pitch a single-writer-per-key partitioned concurrent KV OBJECT
whose novelty is the REPLY PATH (atomic reply-ready bitmask = CDB analog + reply-ring ROB
recovering in-order causally-consistent emission from out-of-order parallel exec, with
per-key linearizability) — NOT "a faster Redis"; harden correctness past oracles toward a
linearizability/TLA+/Spin argument. Precedent lineage: CPHASH (2012, cache-partitioned
hash table, ~1.6x via cutting coherence misses — near-identical structure & multiplier).
PRECONDITION for any top venue: the multi-CCD EPYC + SNC-Xeon SCALING study with hardware
perf-counter coherence-traffic data is the load-bearing experiment (currently only planned).

DEADLINES (verified 2026-06; POSTED unless noted): NO good-fit venue lands in Nov/Dec 2026.
Nov/Dec only has low-fit options (PVLDB Nov1/Dec1 POSTED off-community; ISCA 2027 ~Nov,
OSDI'27 ~Dec, both INFERRED + low fit). Good-fit dates: PPoPP 2027 = Aug 3 2026 (POSTED,
too tight/during service); EuroSys'27 fall = Sep 24 2026 (POSTED); SPAA 2027 ~Feb 2027
(INFERRED); ATC 2027 ~Jun 2027 (INFERRED).
PLAN: (1) arXiv NOW (~1 weekend) to lock priority / kill scoop fear; (2) target SPAA ~Feb
2027 (best fit + ~5mo post-service runway for the EPYC study + theorem hardening), SPAA
Brief Announcement as the peer-reviewed flag-plant option; ATC ~Jun 2027 systems backup.
Do NOT submit to a Nov/Dec 2026 venue.
