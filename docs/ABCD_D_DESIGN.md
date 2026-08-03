# D — cost/latency-aware scheduling, split IO ⇄ EX

Owner rulings 2026-08-02. Supersedes the D section of `abcd_brief.txt`, which put the whole
reorder on the EX side. Everything the brief says about fences, knob count and the hot-path
budget still stands.

---

## 1. Where the work happens, and why it is split

Not "move D from EX to IO" — **split it by what each side can actually know**.

| stage | owns | because |
|---|---|---|
| **IO** | cost classification, dependency guard, topology weighting, head-of-pipe flag, admission + the SEDA window | it is the **admission point**, and it already resolves `c->cmd` and the target worker during parse, so classification is nearly free |
| **EX** | cache-readiness reordering, command **age**, the starvation backstop | residency is a property of *that worker's* L1/L2, and true waited-time is only measurable at the consumer |

**Why IO is the right place for admission.** Reordering at EX is post-hoc: by the time a worker
pops a prefix, the head-of-line decision was already made when the command entered *that specific
queue*. IO can do the one thing EX cannot — **not enqueue yet**, or enqueue elsewhere in the batch
order. That is strictly more powerful than permuting after commitment.

**Why readiness stays at EX.** IO cannot know what is resident in worker W's cache. Any
readiness-driven policy that pretends otherwise is guessing.

---

## 2. The enabling fact (checked, not assumed)

Execution order is **already** decoupled from reply order:

* `c->dispatchid` / `c->flushid` sequence every dispatch per client;
* `cdbSlotPublish()` publishes into a per-slot ring indexed by `dispatchid & PIPELINE_QUEUE_MASK`;
* a pipelined batch already fans out across workers and executes concurrently.

And cross-key order within a client is **explicitly not guaranteed** (owner ruling 2026-07-27).
So reordering execution is not fighting an invariant — the reply ROB reassembles.

---

## 3. Correctness metrics that must hold (the whole permission slip)

1. **Per-connection same-key order.** Same key → same worker → that queue is FIFO. Preserved *by
   construction* if we only permute **across** workers and keep each worker's own run in arrival
   order. This is why the first operation is a **stable partition by target worker** rather than a
   sort: it makes the invariant structural instead of something a guard has to catch.
2. **Per-connection reply order.** Already held by the dispatchid ROB. Untouched.
3. **Bounded starvation.** §6.
4. **Fences, never candidates:** multi-key/scatter, module/unknown, rewritten key, FLUSH and
   migration sentinels. Command identity is re-checked at execution time so a rewrite or a stale
   classification degrades to a fence (D4).

### Cross-client and cross-batch reordering is permitted — and here is why it is safe

Redis guarantees ordering **per connection**, not globally; two concurrent connections have no
defined relative order. The sharper argument, which is what makes cross-client reordering safe
rather than merely conventional:

> Any causal dependency between two clients is **mediated by a reply**. If client B's request was
> caused by something B learned from A, then A's reply had already been sent — so A's command had
> already executed and is not in the window. A command whose reply has not been sent cannot have
> influenced another client's request.

Therefore two commands that are simultaneously in the reorder window are, by definition, causally
independent between clients, and may be permuted. The **same-key guard is still required**, but
only to protect the *same-connection* case and to keep concurrent same-key writes from interleaving
inside a single worker's run.

---

## 4. Signals (owner-specified)

Ranked by where they are known and what they cost.

### 4.1 Topology: EX node vs IO node (shared L3 or not) — IO side
`tmNodeOfIoSlot()` / `tmNodeOfWorker()` already exist. Same node ⇒ the handoff lands in a shared
L3; cross-node ⇒ argv/operand lines cross an interconnect.

Use: **issue same-node work first, and group cross-node dispatches** so interconnect transfers are
batched rather than interleaved. Cost: one comparison against a value computed once per (io,ex)
pair at boot — not per command.

> **On this box this signal is constant** (single node, one shared L3) and can only cost. It is
> for the multi-CCD 24-core and the 96-core target. Measure it there; expect nothing here.

### 4.2 Head-of-pipeline — IO side
Whether this command is at the head of its client's ring. A stalled head **gates reply emission**
for that whole client, because the ROB flushes in `dispatchid` order — delaying a head costs the
client's entire pipeline, delaying a non-head costs approximately nothing extra (the head is
already the constraint). Strong, cheap, and the IO owner already stamps a head flag once it has
proved the ring was empty (D3).

**Rule: a head-of-pipe command is never demoted.** It may be promoted.

### 4.3 Command processing latency — IO classifies, EX measures
Two parts:
* **static class** from the command table (O(1) vs O(N)) — free at parse, already holding `c->cmd`;
* **dynamic correction**: a per-command-class EWMA of observed execution time, written by EX and
  read by IO. Read-mostly, one cache line, no synchronisation on the request path.

Static alone mis-ranks `GET` on a 64 B value versus a 64 KB one, so the dynamic term matters for
exactly the large-value regime where reordering has something to win.

### 4.4 Cache readiness — EX side only
Inferred, never probed: touching a line to test residency **is** the miss. Scoreboard: record when
a prefetch was issued and treat the target as ready after enough intervening work (measured in
commands executed, not wall clock). Needs an abandon rule so a long-issued prefetch is not treated
as readiness after eviction.

### 4.5 Command age — EX side
See §6. Cheap monotonic counter, never a clock read on the dispatch path.

### 4.6 Dependency — IO side, cheap because the common case is empty
A small key-hash set over the current window. Only has to cover collisions **within one worker's
run** (the stable partition already separates workers). The owner's observation — two commands on
the same key have the same cache readiness, so a readiness policy has no *incentive* to reorder
them — explains why the guard almost never fires, but it is not a correctness argument, so the
guard is unconditional and hard.

---

## 5. The SEDA window controller

Take SEDA's **controller**, not its staging. Welsh's own retrospective found the per-stage
queue-plus-thread-pool boundaries added latency and that stages should be merged. We have exactly
**one** boundary (IO→EX) and must not add a second: the reorder is a permutation of an
already-parsed batch *before* the push — transient, no new queue. This is also what D1 demands
("two transient lanes over ONE ALREADY-POPPED prefix, **not persistent admission queues**").

* **actuator**: parse batch size — which *is* the reorder window (one knob, not two)
* **observables**: per-worker queue depth (`tomokv_ex_queue_depth`, exists), ROB occupancy,
  the per-class latency EWMA of §4.3
* **objective**: hold a p99 target while maximising amortisation

The tension is real and must be stated in the controller, not hidden: a bigger window gives the
scheduler more to work with and amortises polling, but adds queueing delay **before the first item
runs**. A constant cannot be right across regimes; that is the whole reason this is a feedback
loop.

### 5.1 It is built exactly like the load balancers — owner ruling, and the hot path pays almost nothing

Copy the `lb_grp_ops` idiom. That signal is described in-tree as *"already paid for … one L1
increment … reading it here costs one 1 Hz main-thread pass and adds **NOTHING** to the data
path."* The batch controller gets the same three-part shape and no more:

**1. Hot path — one load, zero arithmetic.**
The parse loop reads the window as a **single relaxed load of one published `int`**. It does not
average, compare EWMAs, inspect queues, or read a clock. Every decision was already made off the
hot path; the hot path only consumes the answer. On x86 a relaxed load is a plain `MOV`.

**2. Signals — per-thread, single-writer, non-atomic, on a line the thread already owns.**
Reuse what exists (`tomokv_ex_queue_depth`, the ROB occupancy the reply path already maintains).
Anything new is a plain `uint32`/`uint64` counter in the thread's **own** struct, incremented
non-atomically like `worker->lb_grp_ops[TOMO_LB_GROUP(bkt)]++` — no LOCK prefix, no shared line,
no false sharing with another thread's counter. The §4.3 latency EWMA is accumulated this way by
each worker into its own row.

**3. Controller — 1 Hz, main thread, off the data path.**
Runs at the existing periodic site, next to `reshardCoordinatorTick()` / `tmFlipTick()` /
`flatResizeCoordinate()`. It sweeps the per-thread counters, folds them into EWMAs, decides, and
**publishes one value with a single release store**. Deltas are computed against a `_last`
snapshot with **unsigned subtraction so counter wrap is safe** — the same reason `mig_grp_last`
exists.

**Level 0 means the machinery does not exist**, not that it is skipped: state is **lazily
allocated on the first tick the controller actually runs**, exactly as the bucket balancer does for
`tomokv-key-lb 0`. At level 0 there is no allocation, no tick work, and the parse loop uses the
compile-time constant — so the load itself disappears.

**Budget.** At ~7.9M ops/s, 1% ≈ 1.3 ns/op, and always-on machinery must stay ≤3%. The steady-state
cost here is one L1-resident load per parse batch (not per command) plus one non-atomic increment
per command on a line the thread is already writing. That is inside the noise floor by
construction, which is the point of copying this pattern rather than inventing one.

**Do not** put the controller on a worker or IO thread, and do not let the hot path recompute the
window "just in case it changed" — a stale window for up to one second is completely acceptable,
which is precisely why 1 Hz is enough for the balancers too.

---

## 6. D5 — starvation bound (required)

Aging in the spirit of Shinjuku. We do **not** preempt, so the portable half is the aging, not the
multi-level feedback queue's preemption.

* age from a **cheap monotonic counter** — the ring sequence the queue already maintains, or a
  coarse epoch bumped by an existing periodic tick. `getMonotonicUs()` is vDSO (~20 ns) but at
  ~7.9M ops/s that is ~15% of a 1.3 ns/op budget-percent. Age must be an integer subtraction.
* **stated bound**: a request is promoted to the head after at most **N intervening promotions or
  one epoch**, whichever comes first, so it runs within a bounded number of dispatches. *A bound
  you cannot state is not a bound.*
* expose **worst observed age** as a counter, so the bound is checked rather than assumed.

---

## 7. Order of operations on the IO side

Per parse batch, after each command's target worker is known:

1. **stable partition by target worker** (preserves same-key order structurally)
2. within each worker's run: promote head-of-pipe; then bounded short-job-first by §4.3,
   **subject to** the §4.6 dependency guard
3. order the runs themselves by §4.1 (same-node first, cross-node grouped)
4. push

Steps 2–3 are skipped entirely at knob level 0 — the machinery must not exist on the hot path.

---

## 8. What I expect to measure, stated in advance

Reorder needs **mixed command costs**; on uniform GET it can only cost. So: flat-to-slightly-
negative on the four reference cells, with any real result showing up in `tail_mix` per-class
p50/p99/p99.9 — judged **alongside the long-request maximum**, because improving short-request p99
by starving long requests is not a win. That is what §6 exists to prevent, and the worst-age
counter is how we check it actually did.

The topology signal (§4.1) is untestable on this host and must be re-measured on multi-CCD.

---

# B — EX prefetch: the residency gate, measured

**Measured 2026-08-02, before writing any B code.** The brief's B3 assumes prefetch was inert
because of a flat-regime hole. The first thing to establish is whether the gate opens at all, since
memory recorded "the gate had NEVER opened".

Static server, io4/ex4, seed then 12 s of GET, reading `tomo_prefetch_{batches,gated,issued}`:

| regime | batches | gated | issued | verdict |
|---|---|---|---|---|
| **2M keys × 32 B** | 11,088,850 | **11,088,850** | **0** | **gate 100% SHUT** |
| 8M keys × 32 B | 11,343,132 | 245,096 | 302,154,165 | gate open (97.8% of batches) |
| 2M keys × 512 B | 10,313,372 | 372,288 | 139,350,765 | gate open (96.4% of batches) |

**The gate does open.** "It never opens" is false. The precise and more useful statement is that it
is **exactly 100% shut at 2M × 32 B** — which is the standard apparatus, the one all four reference
cells use and the one every previous prefetch A/B was run on. So every historical "prefetch is
neutral" result measured **disabled machinery**, and neither the neutral verdicts nor the
0.3–1.2% cost figure can be attributed to the prefetch itself without knowing which regime produced
them.

The gate is behaving as designed: `budget = detected_l3_bytes / (2 × num_workers)`, and it refuses
to prefetch while the worker's share of the keyspace still fits in its share of L3. Prefetching a
cache-resident working set is pure overhead, so shutting there is correct. The defect was never the
gate; it was measuring a gated feature in the one regime where the gate is guaranteed shut.

**Consequence for B: any B measurement must be taken at ≥8M × 32 B or ≥512 B values**, and must
report `issued` alongside the throughput number so the reader can tell an engaged run from a gated
one. A B result quoted at 2M × 32 B is meaningless by construction.
