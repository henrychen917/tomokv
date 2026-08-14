---
name: thredis-prefetch-truth
description: "prefetch: the units-bug gate fix (652deda9b) WORKED — but the gate is still 100% shut at d=32, which is what the reference cells use; with it open prefetch is a WASH because the worker is overhead-bound, not memory-bound"
metadata:
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**Supersedes the optimistic parts of [[thredis-prefetch-status]] and
[[thredis-prefetch-stage-verdicts-provisional]].** Gate fix landed `652deda9b`.

## UPDATE 2026-08-02 — the gate fix worked, and value size is the hidden variable

The 2026-07-27 entry below was correct for its apparatus (2M keys **at 64 B**, where it recorded
issued 228M). Re-measured at the size the REFERENCE CELLS actually use (`-d 32`), static io4/ex4,
seed + 12 s GET:

    2M x 32B    batches 11088850  gated 11088850  issued 0            SHUT (100%)
    8M x 32B    batches 11343132  gated   245096  issued 302154165    OPEN (97.8%)
    2M x 512B   batches 10313372  gated   372288  issued 139350765    OPEN (96.4%)

The gate keys off FOOTPRINT (keys x (overhead + value size)), so **2M is open at 64 B/512 B and
shut at 32 B**. Consequence: **the four reference cells (d=32, 2M) never engage prefetch at all**,
so no verdict taken from them says anything about it. The gate itself is correct —
`budget = detected_l3_bytes / (2 * num_workers)`, and prefetching a cache-resident set is pure
overhead.

## With the gate genuinely open it is a WASH — and the reason is the real finding

`tomokv-prefetch-ex` added (levels; 0 returns before `pf_batches++` so DISABLED and GATED are
distinguishable in INFO). It is `MODIFIABLE_CONFIG`, so arms run on **one server / one dataset /
knob flipped live** — no seed or build variance:

    8M x 32B     OFF 7890151  ON 7890123  -0.0004%  pair spread 1.77%
    2M x 512B    OFF 3866214  ON 3849531  -0.43%    pair spread 1.52%
    24M io5/ex3  OFF 6322718  ON 6307965  -0.23%    OFF spread 1.43%  (4 pairs)

Engagement proven every arm: `issued` 0 on every OFF, 173–356 M on every ON.

**Why it is a wash: the worker is OVERHEAD-bound, not memory-bound** —
see [[thredis-worker-overhead-bound]]. Prefetch hides memory latency, which is not the constraint.
This also means the old "operand stages cost 0.9–1.2%" figure below is not reproducible at these
sizes; treat it as apparatus-specific.

## Rules

* **Never quote a prefetch number without `issued` beside it.**
* Gate-open regimes: **≥8M × 32 B, or ≥64 B values at 2M** (512 B is comfortably open).
* **Do not build B2/B3/B4** on this evidence — stages that hide a latency which is not costing
  anything. Ten `tomokv-pf-*` knobs were already retired for exactly that.
* B3's premise ("inert in flat because it retires at `kvstoreGetDict()==NULL`") is doubtful: these
  runs ARE FLATSTORE (ex=4 ⇒ shared node db) and issued 352 M.
* Re-run the same A/B on **multi-CCD / cross-NUMA** before extending B; if it cannot beat noise
  there either, B is a negative result.

---

## Original entry, 2026-07-27 (accurate as written)

1. **THE GATE HAD NEVER OPENED.** `auto_min` compared a PER-WORKER footprint against the WHOLE
   shared L3 ⇒ real criterion `8*W x L3`. On 4 workers = **32x L3**, gate SHUT. Fixed by dividing
   L3 by workers-per-L3-domain.
2. **THE THREE TABLE STAGES ARE DEAD UNDER FLATSTORE** — `PFS_HASH` → `kvstoreGetDict` →
   `kvs->dicts[didx]`, never populated when `KVSTORE_FLAT`. `flatstore.c` contains ZERO prefetch
   instructions.
3. **NO OBSERVABILITY** existed before `tomo_prefetch_batches/_gated/_issued`.

First A/B (2M keys **64B** p32, ON issued 1.31e9 vs OFF 0): get −0.9%, set −1.2%, r9to1 −0.3%.

**instr/op is the WRONG verdict metric for prefetch** — it ADDS instructions to REMOVE stalls. Use
cycles/op or `cycle_activity.stalls_l3_miss`/op. instr/op stays right for allocation work.

**AMAC: no.** `exPrefetchBatch` is already AMAC-shaped; the flat chain is constant-depth (15-bit
tag gates the kvobj deref), ~1.06 cache lines/hit at α≈0.48 — GP's precondition, AMAC's worst case.

**NEVER BUILD:** SIMD tag gather · cross-batch pipelining · residency-ordered OOO selection ·
node-local pools under NPS1 · AMAC refill · per-descriptor ring padding.
**PREFETCHW may have ZERO safe sites** — prove one before writing code.

## CORRECTION 2026-08-09 — THE "PREFETCH IS A WASH" CONCLUSION DOES NOT MEAN WHAT IT SAYS

The gate-open A/B **never prefetched storage at all**, so it cannot support "the worker is
overhead-bound, not memory-bound".

Under `KVSTORE_FLAT` the per-bucket dicts are UNUSED (kvstore.c says so verbatim at the
kvstoreEmpty and kvstoreRelease sites: *"dicts are unused"*). So `kvstoreGetDict()` returns NULL and
`exPrefetchBatch` retires at
    `if (!d || dictSize(d) == 0 || !d->ht_table[0]) { st[j] = PFS_DONE; break; }`  (server.c:20280)
**before** `PFS_ENTRY` (bucket->entry) or `PFS_VALUE` (entry->kvobj/value). The only stages that ever
issue are the request-side ones: `PFS_STRUCT`, `PFS_ARGV`, `PFS_KEYOBJ`. That matches the recorded
counter exactly — 352-356M `pf_issued` per 15s 8M-key arm is ~3 issues per GET, not a storage chase.

WHAT THE WASH ACTUALLY PROVES: there is no headroom in prefetching the request OPERANDS.
WHAT IT DOES NOT PROVE: anything about flat-slot / kvobj / value residency.

Also weaker than previously claimed: 21x dataset costing 3.5% rules out a GROWING capacity/bandwidth
cliff, but NOT a fixed serialized miss on every GET — a random GET pays roughly the same one
table+object chain at 2M and at 48M keys.

CONSEQUENCE: the cache-residency question ([[thredis-no-crmr-split]], the uTPS hot-set idea) is
UNPROVEN, not refuted. I twice cited this wash as evidence against it; that was wrong. The decisive
measurement is the per-command cost census (lookupgate) plus a prefetch A/B that actually reaches
the FLAT slot. EX-side footprint is ~23.1 MiB per worker at 2M keys against 1 MiB L2 and a nominal
4 MiB L3 share, so the working set is genuinely NOT resident.

# RESOLVED 2026-08-09 — storage prefetch PROVEN and SHIPPED; per-key skip REJECTED

The flat-slot A/B the correction demanded was run (owner-spec workloads, flatpf 1d3fe3375):

**hot30/cold70 @40M keys** (30% ops on a resident hot set, 70% on true-DRAM cold — first genuinely
memory-bound prefetch test on this box): STG(lvl3) 7.937/7.930M vs OFF 7.779/7.804M = **+1.6-2.0%,
reproduced to 0.1%**, witnesses 317M slot + 241M kvobj hints/30s; pays +7% instr/op for +9% IPC
(1.100→1.202). Merged-dev confirm at 40M UNIFORM: **+3.1%** (7.765 vs 7.534M). instr/op is indeed
the wrong metric here, as the 2026-07-27 entry said — ops + IPC judged it.

**SHIPPED dev @ac8283bbb**: stages cherry-picked (WITHOUT the perkey parent), default
`tomokv-prefetch-ex` 1→3. Safe because the L3 gate self-selects the regime — confirm cell at 2M:
issued 0, gated 30.1M, ops 7.747M (zero small-data tax).

**Per-key residency skip (cb621b2f6) REJECTED at its engineered best case**: hot set sized exactly
to its 4096-tag table, 12M tag hits engaging, and SKIP≡STG (−0.4%/+0.4% discordant pair). Ceiling
is zero: prefetching an L3-resident line was already free, and the check taxes every key. Mild-skew
case (2x gaussian 40M: hit rate 0.057%, +0.5% instr tax) agrees from the other side. The uTPS
hot-set/residency idea is now REFUTED for prefetch-skip purposes on this box.

**Operand prefetch (lvl1 alone): still a wash** — consistent with everything above.
Remaining open on the Threadripper target only: re-verify the +2-3% scales with channels/CCDs.

# 2026-08-11 — IN-NODE handoff (message/reply) prefetch: measured, NOT a ship

The cxinnodepf fork (audited clean, witnesses per side) un-gated the mode-2 message/reply warm
machinery for SAME-node producer/consumer pairs (symmetric knobs: level 1 = base + in-node,
2 = +cross-node). Interleaved A/B on the 09774330d base, engagement proven every ON arm:

- EX carrier warm (cross-binary, defaults): p32 GET io4ex4 **+1.1% (3/3 pairs)** but p32 SET
  io4ex4 **−0.8% (3/3)** with 30-50x higher engagement (15-27M warms vs 0.5M — deep backlog);
  p1 wash (engagement ~0, correct); io7ex1 unreadable (A-arm ±5% noise); 40M both patterns wash.
- IO reply warm (same binary, io 0v1): engagement MASSIVE (148-203M issues/20s) yet 100K cells
  wash-to-−0.6%, 40M GET −0.6%, 40M SET +0.5-1.5% (3/3) — the one clean win, tiny.

Three-regime pattern = weak/mixed mechanism (win in one regime, mirror-loss in its sibling):
per [[thredis-three-regime-testing]] and hardcode-or-delete, in-node handoff prefetch does NOT
ship on this box. Consistent with the operand-wash truth: the handoff lines are L3-shared and
already warm enough in-node; the 400ns comm tax is instruction volume + protocol, not stalls
(see the IO census). Mode-2 cross-node semantics kept for real-NUMA silicon, where the same A/B
must be re-run (remote lines are the regime this mechanism was actually built for).
NOTE: the battery also exposed the flatstore insert-full P0 (task #117) — 2 stable crashes
during 40M fills, unrelated to prefetch (fill-phase, base code both arms).
