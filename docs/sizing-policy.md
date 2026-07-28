# Sizing & allocation policy

What auto-resizes, what doesn't, and why — plus which structures the new allocation path can
legally touch.

No novelty is claimed here. Each policy is the standard practice for its situation, named and
cited so the paper can reference prior art rather than describe an invention.

---

## 1. The rule that decides everything

**Size by what actually drives the size.** Three drivers, three policies:

| driver | policy | standard practice |
|---|---|---|
| **data volume** (unbounded, runtime-dependent) | **auto-resize** — grow on a load/occupancy signal, amortised | hash-table load factor; `std::vector` geometric growth |
| **the common case, with a bounded tail** | **fixed inline capacity + heap fallback** | SSO: LLVM `SmallVector<T,N>`, `folly::small_vector`, `absl::InlinedVector` |
| **hardware / topology / concurrency** | **derive once at boot** from measured machine state | jemalloc arena-per-thread; DPDK ring sizing |

The failure mode to avoid is applying policy 1 to a policy-3 quantity: auto-growing something whose
size is set by *thread count* or *pipeline depth* produces a controller that hunts against noise
and never converges — the `≤3%` budget then gets spent on machinery that only subtracts.

---

## 2. MUST auto-resize (data-driven)

| structure | signal | notes |
|---|---|---|
| **flat table** (`flatstore`) | occupancy vs `tomokv-flat-load-pct` | `resize_needed` set by the inserting worker at high load; the **main-thread coordinator** performs the grow, so the resize is cooperative and never blocks a worker mid-probe. Standard open-addressing practice. Load factor matters more here than usual: at α≈0.48 a hit costs ~1.06 cache lines, but unsuccessful search (insert) degrades sharply above α≈0.85. |
| **reply buffer → reply list** | reply size | A reply is unbounded (`HGETALL` on a large hash), so the inline `buf` must spill to a list. This is upstream Redis behaviour and must stay. |
| **per-key collections** (listpack→hashtable etc.) | element count / element size | Upstream encoding-conversion thresholds. Untouched. |

---

## 3. MUST NOT auto-resize (fixed capacity + explicit fallback)

| structure | why fixed | fallback |
|---|---|---|
| **`csGroup` inline arrays** (the new SSO work) | Inline storage lives *inside the parent object*; "auto-resizing inline storage" is a contradiction — growing it means it is no longer inline. `SmallVector<T,N>` has a fixed `N` for exactly this reason. | heap allocation above the threshold |
| **arena block size** (if the per-command arena lands) | A region allocator uses a **fixed chunk** and chains a new one on overflow; it does not resize a live chunk, because outstanding pointers into it must stay valid. | chain another block (nginx `ngx_pool_t`, APR, PostgreSQL `MemoryContext`) |
| **`WORKER_POP_BATCH` (16), `TOMO_MWAVE` (32), `TOMO_MSUBWAVE` (8)** | These are *pipelining widths*, not capacities. They trade prefetch-to-use distance against register/cache pressure and are properties of the microarchitecture. | none needed |

**Choosing the inline threshold** is the one real decision: it should cover the common case and no
more, because every unused inline slot is dead weight in *every* instance. Pick it from the measured
distribution of `nkeys`/`nsub`, not by intuition — and record the distribution alongside the number,
so a future reader can re-derive it when the workload changes.

---

## 4. Derive once at boot (topology / concurrency), do NOT auto-grow

| structure | correct driver | current state |
|---|---|---|
| **ex queue depth** (`tomokv-ex-queue-depth`) | producers x pipeline depth — a *concurrency* quantity | **Fixed 2048 in practice. See the correction below — my earlier "do not fix" note here was half wrong.** |
| **pool caps** (`XSUB_POOL_CAP 96`, `OPERAND_POOL_CAP 256`, `PCMD_POOL_CAP 128`) | per-thread working set | Fixed is right. These are per-thread free lists; unbounded growth would just hoard. |
| **prefetch widths / gate** | L3 size ÷ workers-per-L3-domain | Correct in shape (`-1` = derive from measured L3). The units bug that made the gate never open is fixed; see `docs/BUGS.md` A6. |
| **fake ring / fake buf** (`-1` = auto) | client pipeline depth | Derived, then bounded. Reasonable as-is. |

---

## 5. What the new allocation path can and cannot touch

The inline/arena work changes *where* per-command scratch lives. The governing constraint:

> **An object may move into inline storage or a per-command arena only if its lifetime ends when
> the command retires.**

| object | lifetime | arena/inline legal? |
|---|---|---|
| `csGroup` itself | one command | **yes** — inline in the parent, or arena |
| `g->subs`, `g->mget_pos`, per-sub posmaps | one command | **yes** |
| `g->mget_vals` (the sds value copies) | worker writes → drain reads → freed at teardown | **yes**, *but* the region must outlive the drain, not just the worker. A per-command arena freed at retire satisfies this; a per-*worker* arena would not. |
| **reply blocks** (`clientReplyBlock` on the reply list) | handed to the client, can outlive the command | **NO** — these are consumed by `_writevToClient` after the command is gone |
| **values stored into the keyspace** (adopted sds, embedded kvobj) | live until overwritten/expired | **NO** — unbounded lifetime |
| pcmd / argv operands | parse → `freePendingCommand` on the same IO thread | already pooled; leave alone |

Getting this wrong produces a use-after-free that only manifests under reply spill or overwrite —
i.e. exactly the regime least covered by fast unit tests. **The reply-block row is the trap**: it is
per-command *scratch* by appearance and *client-owned* in fact.

---

## 6. Interaction with cross-thread ownership

Independent of resizing: several per-command objects are allocated on one thread and freed on
another (IO parse → worker execute, or worker execute → IO drain). Stock Redis cannot have this,
because it executes commands on one thread; this fork can.

Inline storage **removes the problem for anything it absorbs** — an object inside `csGroup` is not
separately allocated at all, so there is no cross-thread free to account for. That makes the SSO
work the preferred fix over routing frees back to their owner: it eliminates the transfer rather
than managing it.

Where inline cannot absorb (the reply blocks, the SET value operand), the options in order of
preference are: **eliminate the transfer** (serialise into a buffer the consumer already owns) →
**free-on-owner** (route the free back; already implemented for zero-copy replies via
`str_ref.owner_ex`) → **same-arena reclaim** (already used for the FLATSTORE retire path).

Note this whole area is currently **unmeasured** — see `docs/BUGS.md` §I2 for the profile
attribution that turned out to be wrong. Measure before optimising.

---

## 7. References

- Small-size optimisation: LLVM `SmallVector`; `folly::small_vector`; `absl::InlinedVector`
- Region/arena allocation: nginx `ngx_pool_t` (per request); Apache APR `apr_pool_t`;
  PostgreSQL `MemoryContext` (per query); LLVM `BumpPtrAllocator`; Hanson, *Fast allocation and
  deallocation of memory based on object lifetimes* (Software P&E, 1990)
- Why **not** per-type pools: Berger, Zorn & McKinley, *Reconsidering Custom Memory Allocation*
  (OOPSLA 2002) — custom freelists generally do not beat a good general-purpose allocator; regions
  are the exception. Corroborated locally by commit `52200d263` (kvobj recycle pool: negative
  result, p32 SET 5.263M vs 5.307M, allocator profile unchanged).
- Thread-caching allocation: jemalloc `tcache` (already a per-thread pool — this is why adding
  another pool layer above it does not pay).


---

## 8. A note on auditing sized structures

While writing this document I nearly filed the ex-queue-depth floor as a defect, on the strength of
an audit finding that described the widen loop as dead. Reading the code showed the opposite: the
floor is intentional, measured, and documented, and the growth path above it works.

The general lesson, since it has now recurred several times in this project: **an audit finding is a
hypothesis about the code, not a fact about it.** A "dead" branch may be a deliberate floor; a
"missing" guarantee may be unnecessary (see `docs/BUGS.md` H1, where a fence with no incrementer
turned out to guard a path that cannot execute). Before changing a sizing policy, read the comment
that explains it — in this codebase the reasoning is usually recorded at the site, and it usually
cites a measurement.

---

# Part II — the pooling audit (2026-07-28)

Owner's directive: *"I want all the pooling system, resizing system of basically everything to be
replaced with industry standard or just plain better solutions as I don't plan on claiming novelty
there."* This part inventories every pool and every resize policy in the fork and assigns each one a
standard mechanism — or deletes it.

## The rule that decides every row

**jemalloc's `tcache` is already a per-thread, size-class-bucketed free list.** So a custom pool that
only recycles same-sized objects is a second thread cache stacked on the first: it cannot beat it on
allocation speed, and it adds a cap, a refill policy and a decay policy to get wrong. Berger, Zorn &
McKinley (OOPSLA'02) is the canonical measurement of exactly this.

A custom allocator therefore has to justify itself on something *other* than allocation speed. There
are only three such justifications, and each has a standard name:

| # | justification | standard name / prior art |
|---|---|---|
| **R1** | many objects, **one shared lifetime**, all freed at once | **region / arena** — nginx `ngx_pool_t`, APR `apr_pool_t`, Postgres `MemoryContext`, LLVM `BumpPtrAllocator`. *This is the documented exception to Berger et al.* |
| **R2** | **initialisation** is expensive, not allocation | **object pool** — Boost.Pool, game-engine entity pools. Recycling skips constructor work, not `malloc` |
| **R3** | reuse must be **deferred until no reader can hold a pointer** | **EBR / QSBR free list** — Fraser; Michael; Hart, McKenney & Brown. The constraint is *when* memory may be reused, not how fast it is obtained |

If a pool fits none of R1–R3, it is deleted and the call goes straight to the allocator.

## Pools

| pool | cap | fits? | disposition |
|---|---|---|---|
| **operand pool** (`OPERAND_POOL_CAP 256`, `MAX_SDS 512`) | 256 | **none** | **DELETED** (landed with the alloc merge). Measured net-negative: instr/op +2.18…+4.13%, allocs/op **+6.6…+15.7%** — structural, because a poolable operand had to be RAW, so every miss cost robj+sds (2 allocations) where the normal path allocates ONE embstr |
| **`csGroup` arrays** (`g->subs`, `mget_pos`, posmaps, `mget_vals`) | — | **R1** | **DONE** — inline/SSO bump region inside the group allocation, sized per command by `csInlineWant`; spill to `zmalloc` above capacity. mget4 −5.21% instr/op, allocs 26.0→20.3 |
| **xsub pool** (`XSUB_POOL_CAP 96`) | 96 | **R1** | **REPLACE** — subs are strictly per-command; fold into the same region rather than a per-type freelist |
| **pcmd pool** (`PCMD_POOL_CAP 128`, `MAX_ARGV 64`) | 128 | **partly R1** | **SPLIT** — it recycles a struct *and* a separately-allocated argv array. Inline the argv array (SmallVector/SSO) so the second allocation disappears; then re-measure whether recycling the struct still pays |
| **pooled fake clients** (`createPooledFakeClient`) | — | **R2** | **KEEP** — justified by construction cost, not allocation. Must be *stated* as R2 at the site, so it is not deleted later by someone applying the R1 rule |
| **flat node pool** (`FLAT_NODE_POOL_CAP 4096`, `_lowat`) | 4096 | **R3** | **KEEP** — this is textbook epoch-based reclamation for a lock-free table. Deleting it would be a correctness bug, not a simplification |
| **`cmd_pool`** (`PENDING_COMMAND_POOL_SIZE 16`, `MAX 1024`) | 16→1024 | **R2?** | **MEASURE** — decide against R2 explicitly rather than by habit |

## Resize policies

Part I's three-way rule stands. Two entries need correcting against it:

| structure | policy | status |
|---|---|---|
| flat table | grow on load factor | **correct** — standard open addressing |
| ex queue depth | derive at boot, `max(want, 2048)` | **correct, do not "fix"** (Part I §4) |
| fake ring / fake buf | `-1` derive from pipeline depth | correct |
| reply buffer → list | spill on size | correct (upstream) |
| **`tomokv-worker-pop-batch`** | `-1` → the constant 16 | **ALREADY CORRECT — the comment was the defect.** I filed this as "a PID auto-resize that contradicts our own width policy" on the strength of its config comment. Reading `tomoPopBatch()` shows three lines and **no controller of any kind**: `-1` returns `WORKER_POP_BATCH`. The claimed "PID-style grow/decay" never existed. A fixed width is exactly what Linux NAPI (weight 64) and DPDK (burst 32) do. Comment corrected; no code change |
| **`tomokv-drain-tail-skip`** | `-1` ≡ `1` | **no "auto" arm exists** — the test is `!= 0`, so it is a boolean in a tri-state costume. Comment corrected |
| `tomokv-worker-spin` | ×1.5 grow (cap 256) / ÷2 shrink (floor 4) | **REAL, and standard.** Multiplicative-increase/multiplicative-decrease is *the* canonical adaptive-spin form — Linux adaptive mutexes, HotSpot adaptive spinning, exponential backoff (CSMA/CD, TCP RTO). Keep |
| `tomokv-io-drain-userpoll` | `-1` picks poll-vs-syscall from `replyWorking` | **REAL, and standard** — this is NAPI's interrupt↔poll switch. Keep |
| `tomokv-express-slim` | `-1` = EWMA + Schmitt band [0.60, 0.80] | **REAL, and standard** — hysteresis on a smoothed signal is textbook (and the double-read race in it was already fixed). Keep |

### Are PID controllers standard here? No — and they would be the wrong tool

The question was asked directly, so it is worth recording the answer. **There is no PID controller anywhere in this fork.** The only knob that claimed one had no controller at all; the three real adaptive arms are MIMD backoff, NAPI-style poll switching, and EWMA+hysteresis — all standard families.

That is also the *right* design, not a lucky one. **A PID regulates a measured value toward a setpoint.** Batch width, thread split and spin budget have no setpoint — the goal is to *maximise* throughput, which is an optimisation problem, not a regulation problem. Applying PID where no setpoint exists is a category error: the integral term has nothing to integrate toward and the loop hunts. The correct families are the ones already in use: a **fixed constant** where the quantity is microarchitectural (pop batch), **multiplicative backoff** where the cost is wasted spinning, **hysteresis** where the risk is flapping, and **extremum seeking / hill-climbing** where you genuinely must find a maximum — which is what `tomoFlipController` does, and the one place a bespoke mechanism is warranted.

PID does appear in systems software, but for continuous quantities with real inertia — CPU frequency governors (`intel_pstate`), thermal/fan control, GC heap sizing. None of those describe a 1–16 integer width.

## Sequencing

Each step is separately measurable and separately revertible:

1. ✅ delete the operand pool (done — alloc merge)
2. ✅ `csGroup` region (done — alloc merge)
3. inline the pcmd argv array (SSO), re-measure the struct recycle
4. fold xsub allocation into the per-command region
5. settle `worker-pop-batch`: auto vs fixed, delete the loser
6. state R2 at the fake-client and `cmd_pool` sites, or delete them

**Measurement note.** These are 1–5% effects and the box's exclusive noise floor is ±2%
(`docs/BUGS.md` E-extra2), so every step needs `withbox.sh` + interleaved reps, and `instr/op` is the
verdict metric — not wall-clock ops/s.


---

# Part III — the SPSC ring, and a correction I owe this file (2026-07-28)

## The double correction

This entry has now been wrong twice, in opposite directions:

1. An early audit called the widen loop **"provably dead"** because `want < 2048` in the common case.
2. I recorded that as **wrong** — "the floor is deliberate, measured and documented; do not fix" —
   after reading the comment and the floor, and stopped there.

The truth is both, and neither. Reading the loop itself:

```c
long want = 4L * (server.io_threads + 1) * server.pipeline_ring_depth;
long p2 = 2048;                                  /* floor */
while (p2 < want && p2 < TOMO_EX_QUEUE_SIZE_MAX) p2 <<= 1;
```

`TOMO_EX_QUEUE_SIZE_MAX` **is 2048**, and `p2` *starts* at 2048. So `p2 < TOMO_EX_QUEUE_SIZE_MAX` is
false on entry, always. **The loop can never execute for any input.** The derivation is decorative:
auto resolves to exactly 2048 on every configuration. The floor genuinely is deliberate and measured
(deriving below it regressed throughput) — that part of my correction stands — but the widen path is
dead, for a structural reason neither previous claim identified.

## Is the mechanism itself standard? Yes.

A **fixed, power-of-two, boot-sized ring** is the universal choice for SPSC queues: LMAX Disruptor,
DPDK `rte_ring`, io_uring SQ/CQ, kernel `kfifo`. Nobody resizes a lock-free ring at runtime, because
doing so requires quiescing both ends. So "fixed at boot, sized for worst-case burst, exhaustion
counted" is correct by prior art, and `INFO tomokv_ex_queue_full` plus the CLAMPED warning are the
right instrumentation.

**The defect is the story, not the structure** — the same failure as the "PID-style grow/decay"
comment: a knob advertising a derivation it does not perform.

## The one real usability bug

The clamp warning tells the operator the ring is undersized... and the knob's own maximum is
`TOMO_EX_QUEUE_SIZE_MAX` = 2048, so **they cannot act on the warning.** Advice with no reachable
remedy. Reachable at io>=16 with p32 (`4 x 17 x 32 = 2176 > 2048`).

Why the cap is low: `exQueue.jobs[]` is a **static inline array of `TOMO_EX_QUEUE_SIZE_MAX`
pointers per (worker, io) pair**, so the maximum is paid by every pair whether used or not:

| workers | io | MAX | jobs[] memory |
|---|---|---|---|
| 4 | 4 | 2048 | 0.3 MB |
| 16 | 16 | 2048 | 4.2 MB |
| 16 | 16 | 8192 | 17.0 MB |
| 64 | 32 | 8192 | 132.0 MB |

The array is inline deliberately — it saves a pointer chase on a hot structure.

## Options, with the honest trade

- **A. Allocate `jobs[]` dynamically at `ex_queue_size`.** Standard (Disruptor/DPDK allocate the ring
  at its chosen size); memory becomes proportional to need, and the cap can rise. Costs one
  indirection on a hot path — the pointer shares a line with head/tail and should stay L1-resident,
  but that is a *prediction*, and this project does not ship predictions as facts. **Measure it.**
- **B. Keep the inline array, raise `TOMO_EX_QUEUE_SIZE_MAX` to 8192.** Zero hot-path change; costs
  17 MB at 16x16, 132 MB at the (unrealistic) 64x32 ceiling.
- **C. Keep 2048, delete the dead loop, and say plainly that it is fixed.** Honest and standard, but
  leaves the unreachable-remedy bug for large configs.

Recommendation: **C now** (it is a comment fix and removes a false claim), then **A measured** — with
B as the fallback if the indirection costs anything. Do not do A on the assumption it is free.

## The other three sizings — all already standard

| structure | mechanism | prior art | verdict |
|---|---|---|---|
| **fake client ring** (`-1`) | EWMA of per-window high-water x1.25, rounded to a power of two, decays only when idle, with a decay-skip hysteresis | watermark sizing with hysteresis — Linux `tcp_moderate_rcvbuf` receive-window autotuning, JVM adaptive heap sizing, HikariCP pool sizing | **correct, and correctly auto.** Per-client pipeline depth genuinely varies per connection, so this is a *data-driven* quantity — Part I policy 1 applies and auto-resize is right |
| **CDB / reply-bus count** (`-1`) | `detectL3Domains() > 1 ? num_workers : 1`, capped at `num_workers` and 256 | stripe-per-thread contention reduction — `LongAdder`, `ConcurrentHashMap` striping, kernel per-CPU counters | **correct** — topology-derived at boot, Part I policy 3 |
| **batch widths** (`WORKER_POP_BATCH 16`, `TOMO_MWAVE 32`, `TOMO_MSUBWAVE 8`) | fixed constants | NAPI weight 64, DPDK burst 32 | **correct** — fixed is the standard, see Part II |

`TOMO_PIPELINE_DEPTH_MAX 32` is not a tuning choice at all: `reply_ready_mask` is a `uint32_t`, so 32
is a structural bound. Correctly documented at the definition.
