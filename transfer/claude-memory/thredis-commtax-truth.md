---
name: thredis-commtax-truth
description: "Comm-tax program TRUTH 2026-08-11: ~400ns/cmd IO<->EX handoff = INSTRUCTION/protocol volume, NOT stalls — three independent line-warming/moving mechanisms all neutral (forwarding, in-node prefetch, CDB inline replies); the only live lever is instruction diet (the 64B ring)"
metadata:
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

# MAJOR SCOPE CORRECTION 2026-08-11 (later the same day)

The Opus census challenged the decomposition below and its zero-cost check VINDICATED the
challenge: at io4ex4 p32 the workers are only **~27% busy** (tomokv_ex_busy_us 32.9s/120
thread-s at 7.84M ops/s) — the wall-clock worker IPC was spin-diluted, the "~400ns worker
handoff" was mostly STARVATION, and true worker busy-cost is ~140ns/op (rig 95ns). The
BINDING side is IO (1.96M/thread vs 5.69M pure ceiling, IPC 1.65, low stalls = instruction
volume — for THAT side the instruction-diet law below stands fully). The three neutral
line-warming verdicts stay valid but their explanation sharpens: they optimized the STARVED
side. Full correction in [[thredis-worker-overhead-bound]]. The census also notes the
inline-reply round-2 design was cross-core-TRANSFER-neutral by construction (payload line
replaces fake-buf line 1:1), so its wash does not falsify a transfer-count model; the
remaining transfer-reduction candidate is batching CDB completions (one word per batch vs
per-op bytes) — relevant to the IO DRAIN side, worth one codex round.

# The decomposition (as originally measured — worker line now known spin-diluted)

- WORKER: pure-EX rig 10.5M ops/s/worker @ IPC 3.29 vs real 2.0M @ 1.17 => ~400ns/cmd handoff.
- IO: pure-IO rig 5.69M/s/thread (full parse->route->dispatch->reply-format) vs real p32
  ~2.0M/thread @ IPC 1.65 with LOW stall rate and a FLAT profile => the gap is INSTRUCTIONS
  (socket syscalls, epoll, CDB drain+copy), not misses. p1: 119K/thread @ IPC 0.65 =
  syscall/SRSO-bound => uring2 is the p1 answer (validated +7-15%).

# Three line-warming/moving mechanisms, three independent NEUTRAL verdicts

1. **Value forwarding** — wash in every regime, permanently abandoned
   ([[thredis-forwarding-abandoned]], 3 physics walls).
2. **In-node handoff prefetch** (cxinnodepf, 2026-08-11): engagement proven to 203M issues/20s,
   yet EX carrier warm +1.1% GET / -0.8% SET mirror-pattern, IO reply warm wash — NOT shipped
   ([[thredis-prefetch-truth]] 2026-08-11 section).
3. **CDB inline replies** (cxinlinereply rounds 1+2, 2026-08-11): round-1 taxes (-11/-13%
   worker-bound io7ex1, -2.2% 40M SET line-footprint) were REAL and both FIXED in round 2
   (split packed-status/payload lines restored PTR cost bit-exact; batch-granular worker-slack
   gate, witness cdb_inline_skipped_busy — measured ptr==skipped EXACTLY under saturation).
   With taxes gone the win is ALSO gone: io4ex4 wash, io7ex1 parity-in-noise, 40M GET wash /
   SET +0.2%, p1 wash, and the engineered BENEFIT regime io2ex6 (IO-bound, workers slack)
   GET wash / SET +0.4% weak. PARKED as a clean negative result — branch preserved on gh as
   `2s-cdb-inline-reply` (audited defect-free; do not re-attempt without new physics).

**The law these three agree on: on this box the handoff lines are cheap enough that hiding,
warming, or relocating them buys ~nothing; the tax is the INSTRUCTIONS executed per handoff
(protocol bookkeeping, drain branches, copies, syscalls).** Matches the IO census (flat profile,
low stalls). Cross-NODE (real NUMA silicon) is explicitly untested for all three — re-open only
there ([[thredis-final-server-specs]]).

# WORKER-CONCENTRATED DIET FAMILY (2026-08-12 overnight — the productive lane)

Measured, isolated A/B, the pattern that generalized: IO-side instruction diets win BIGGEST at
io7ex1 (1 worker / 7 IO), the write-heavy regime the flip controller flips TOWARD, because each
per-command cost multiplies by the one saturated worker's command rate:
- **clockdiet** (2 getMonotonicUs/cmd -> reciprocal-mult + raw-delta + batch-boundary clock):
  io7ex1 +11% GET/SET, io4ex4 wash. MERGED dev @063e790b0.
- **lockdiet** (per-command owner-lock CAS -> asymmetric: 1 relaxed store + 1 SC plain load;
  real CAS only on published foreign intent): io7ex1 +5% GET/+4.5% SET, io4ex4 +0.5-0.7%,
  foreign path proven 14.3M engagements no-deadlock. STRONG candidate, branch
  `2s-owner-lock-biased` @6643b04c2; daylight = memory-order line audit + exSlice stack-merge.
- **cxcdbword** (batch the EX->IO completion signal: 1 release-store summary word/pop batch vs
  1 status byte/completion): io7ex1 +15% GET/SET (3/3) but io4ex4 SET -0.6% / 40M GET -0.7% —
  MIXED. Round-2 = self-gate summary-word to large batches. Branch `2s-cdb-batch-word`.
- **pendiet** (IO pendingCommand reset/acquire diet): the exception — +1.6% at io4ex4 (wins the
  balanced config too). MERGED dev @30e1aea07.
LAW: the remaining IO-side headroom is worker-concentrated; measure candidates at io7ex1 not just
io4ex4 (a worker-concentrated win is INVISIBLE at io4ex4 — the harness must include io7ex1 or it
misses the whole family). PGO (+10-15% everywhere, layout) is orthogonal and stacks on all of it,
held for build-parity ([[thredis-benchmarking-methodology]] owner rule). Parks that reorganize
memory traffic on the STARVED worker side stay parked (inline-reply, in-node prefetch, embed,
qsbr, ring's FAST-exec double-touch).

# The one (former) live lever: dispatch-side instruction diet

The 64B tagged ring (cxinlinering, 4 commits, recovered after a codex filter kill) attacks the
instruction side directly: FAST GET/SET execute from a self-contained 64B queue entry — no fake
stamping on dispatch, no carrier deref before reply. Audit 60% done 2026-08-11, zero defects,
strong signs: queue-full spin preserved (dropped-dispatch trap), FAST gated OFF under
atomic/reorder/strict-order (RYOW excluded by construction), IO-owned route line, lookupKey
refactor zero-cost for the ordinary path, version-bag resolver keeps reader identity. REMAINING
AUDIT: moveExecutionStateFast pending retirement (argv-refcount-race class), worker execute +
reply publish, SET semantics equivalence (notify/dirty/expire), witnesses. Then: REBASE onto
843235366 (fork base predates the flatstore fix — its 40M fills roll the old ~10% crash dice),
build, three-regime battery. If the ring is ALSO neutral, the comm-tax program closes with
"run-to-completion handoff cost is protocol-irreducible on single-CCD" and the remaining
instruction levers are PGO/BOLT (#116) and syscall reduction (uring2).
