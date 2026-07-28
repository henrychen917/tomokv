# controller_sweep — controller/allocator conformance suite

Target tree: `/shared/Projects/.claude/jobs/fd085c8e/tmp/stable-w2` (2s-numa-shared-kv fork @ 52c760720;
the working tree is LIVE — code citations give current line numbers, anchor by symbol/log string if they drift).
Binary under test: `stable-w2/src/redis-server`. All knob names/semantics below were read from
`src/config.c` + `src/server.c` of THIS tree — the code is the truth, not the docs.

## Spec

> Test every controller/allocator — shifts based on workload/command/throughput/latency/memory/size;
> memory must not climb beyond expected numbers; throughput no regression; AUTO modes must equal
> STATIC mode for the same workload.

**Spec rev 2** (user refinements, applied on top of the reviewed suite): (1) settle-first —
every AUTO==STATIC and NOREG measurement on a shifting controller waits for that controller's
settle signal, with the convergence time reported as its own bounded row; (2) systematic
anti-thrash — after settle, on the unchanged workload, shift events counted over ≥3 consecutive
windows for EVERY shifting controller, graded 0 = PASS / 1 = SUSPECT / >1 = FAIL; (3) a client
load-balancing family (controller 14), built from the mechanisms that actually exist in code.

Check types, built per controller where applicable:

| type | meaning | gate |
|---|---|---|
| SHIFT | stimulus → documented response via the controller's observable; reverse stimulus reverses it | observable seen (log line / INFO field / used_memory delta) within its window |
| ENVELOPE | RSS/used_memory sampled through the stimulus | peak + settled within stated bounds; memory RETURNS after stimulus; return time bounded |
| NOREG | throughput **after settle** (see CONVERGENCE) | settled ≥ floor stated per check; windows measured across a shift can never PASS (demoted SUSPECT) |
| AUTO==STATIC | knob −1 vs the static value auto resolves to, same workload | interleaved ABBA, medians of ≥3 fresh-boot reps, within 3% (the LB budget rule); 3–5% ⇒ SUSPECT. **SMOKE (1 rep) can never report PASS on these — demoted to SUSPECT** (medians-of-≥3 ledger rule; the box drifts ~15%). On shifting controllers the measured window opens only after settle (warmup / probe ladder) |
| CONVERGENCE | time from stimulus to the controller's settle signal — flip: a full 0-flip probe window; balancer: conversion-complete log; ring/buf: used_memory stable (3 consecutive 2 s samples within 256 KB); reshard: `DONE` + a 10 s quiet window; client-lb: a 5 s zero-migration window | settle within the stated bound ⇒ PASS with `convergence_time=…s`; timeout ⇒ FAIL **and** any dependent AUTO==STATIC/NOREG PASS demotes to SUSPECT |
| ANTI-THRASH | after settle, shift events on the UNCHANGED workload over ≥3 consecutive windows (flip completions; balancer conversions; reshard AUTO+DIFFUSE actuations; ring/buf growth events; client-lb executed migration batches) | 0 = PASS, 1 = SUSPECT, >1 = FAIL; controllers with no shift observable (express-slim) get a KNOWN row, never a fake 0 |

## Running

```
cd /shared/Projects/.claude/jobs/fd085c8e/tmp
SMOKE=1 ./controller_sweep.sh          # ~20–25 min: 1 rep, short windows, seed 400k
./controller_sweep.sh                  # full: ~2h30–3h, 3-rep ABBA medians, seed 2M
CONTROLLERS="1 9 14" ./controller_sweep.sh  # subset by controller number
```

SMOKE runs **all 14 controllers** (nothing is skipped) but any throughput-comparison row
(AUTO==STATIC parity, flip AUTO-vs-STATIC) reports at most SUSPECT — 1-rep comparisons are
smoke-signal only. Shift/envelope/log-observable rows keep full PASS/FAIL meaning in smoke.
Only the full run produces shippable parity verdicts.

Preconditions (the script enforces all of them and refuses to start otherwise):

* **Box free.** No `redis-server` and no `memtier_benchma` (comm-truncated) alive. The suite
  never pkills anything — it only ever kills its own booted PID and `wait`s on it.
* flock single-instance (`csweep/.lock`).
* `memtier_benchmark` in PATH, `redis-cli` at `/shared/Projects/redis/src/redis-cli` (falls back
  to the tree's own cli), python3 (for the persistent-connection driver).
* Server pinned to cores 0–7, load-gen to 8–15 (methodology rule; degrades to a half-split on
  smaller boxes).

Outputs:

* `controller_sweep.tsv` — `controller ⟶ check ⟶ stimulus ⟶ observed ⟶ expected ⟶ result`,
  result ∈ {PASS, FAIL, SUSPECT, KNOWN}. SUSPECT = implausible/gray-zone number (never promoted
  to PASS — sanity-gate rule). KNOWN = expected-by-design or project-memory-known condition.
* `csweep/logs/` — every cell's server log, memtier log, RSS trace, INFO snapshots, preserved.
* `csweep/logs/summary_failures.txt` + a stdout summary histogram.

## Controller inventory and how each is checked

### 1. tomoFlipController (momentum hill-climb; `tomokv-thread-mode auto`)
* **Code truth (flip floor):** grow-back can only reclaim **grown** io slots — `tomoGrowBack`
  rejects at base config (`server.c:16341-16343`, "no grown io thread to convert back") and the
  controller's `can_back` (`server.c:17752`) has the same floor. From boot ioN/exM the reachable
  range is io ∈ [N .. N+M−1]. An io-heavy boot (io6ex2) can therefore NEVER shift ex-ward below
  io6 — the original plan's "p32 from io6ex2 ⇒ io4ex4" was untestable by design.
* Static curve first: p1 GET on io4ex4 / io6ex2 / io7ex1 (+ p32 SET on io4ex4), arms cycled per
  pass so box drift interleaves. Best static arm is picked from the measured curve, not assumed.
* AUTO arm boots **io4ex4** (reachable range io4..io7) with the controller on:
  * Phase A: p1 GET ⇒ expect ≥1 `GROW-FRONT complete` and `io_threads_live > 4` (io-ward),
  * Phase B: p32 pure-SET ⇒ expect ≥1 `GROW-BACK complete` (ex-ward reclaim of the grown slots),
  * CONVERGENCE (each phase, settle-first): after the conversion load, a bounded 5-probe ladder
    of 10 s same-workload windows runs until one FULL window shows **0 new flips** — that is the
    settle signal; `convergence_time` (stimulus start → first 0-flip window) is its own row,
    timeout ⇒ FAIL. The measurement windows open ONLY after this,
  * ANTI-THRASH (each phase): flip count across the 3 settled measure windows on the unchanged
    workload, graded 0 PASS / 1 SUSPECT / >1 FAIL (deadzone pins),
  * AUTO==STATIC: settled median ≥ 97% of the best static arm (p1) and of static io4ex4 (p32);
    in SMOKE these demote PASS→SUSPECT (1-rep static side); an unsettled phase (CONVERGENCE
    FAIL) also demotes a PASS to SUSPECT,
  * ENVELOPE: RSS peak ≤ boot + 1.5 GB across both phases (derivation: workload footprint
    ~30–60 MB; the gated leak class grew ~210 MB/s ⇒ multi-GB over the run — bound sits an order
    above footprint, an order below leak).
* Design assert: on this fork the spare/quorum balancer is **mutually exclusive** with the flip
  pool (`server.c:15795-15800`, spare only when `tm_ngrow_io == 0`) — the `[balance] no
  EX-capable spare` warning must appear.
* NOTE (comparability): a static io7ex1 boot runs 1 worker ⇒ non-shared db (dict store), while the
  AUTO arm converged to io7ex1 keeps the 4-worker shared FLATSTORE. There is no bootable static
  twin of the converged state — the ≥97%-of-best-bootable-static gate deliberately covers that
  whole delta (that IS the user-facing question).

### 2. Quorum pressure balancer (spare PARKED↔EX)
Only reachable with `ex_threads == 1` (else `tm_ngrow_io > 0` suppresses the spare). Boots io2ex1.
* Positive control (balance off): `CONFIG SET tomokv-modeshift-test 2` ⇒ `MODESHIFT PARKED->EX
  complete`; `... 3` ⇒ `EX->PARKED complete`; `/proc/PID/task` count unchanged (conversion, not
  creation — conservation exact).
* Autonomous: sustained p32×16-conn write pressure ⇒ conversion within the pressure window
  (quorum log + completion). CONVERGENCE rows both ways: pressure start → `PARKED->EX complete`
  (bound `T_CONV1−5`) and load stop → `EX->PARKED complete` (bound 90 s), each with
  `convergence_time`. ANTI-THRASH: after the forward conversion the SAME pressure keeps running
  and conversions are counted over 3×`AT_WIN` windows (0/1/>1). No-flap: exactly one conversion
  each way across pressure+idle (Schmitt sustain — counted before the NOREG windows, which may
  legitimately re-trigger); NOREG pre-vs-post round trip ≥ 95% (**medians of 3×10 s windows each
  side** — ledger rule; miss ⇒ SUSPECT, not FAIL). Settle-first: pre windows are the boot-settled
  state and post windows open only after the reverse-completion settle signal; conversions
  observed DURING either side (`pre_dirty`/`post_dirty`) demote a NOREG PASS to SUSPECT.

### 3. Per-connection fake-ring controller (`tomokv-fake-ring-depth -1`)
* AUTO==STATIC 32 on p32 mixed; AUTO==STATIC 1 on p1 (no over-provisioning cost). No
  growth counter exists — parity with static-32 IS the growth evidence. Both parities are
  **warmed** (`T_WARM` of the same workload before the measured window; settles global state).
  Ring state is per-connection and dies with memtier's conns, so the AUTO arm regrows rings in
  the first requests of every measured window — that transient is sub-second vs a ≥8 s window,
  is AUTO's genuine fresh-conn cost (STATIC preallocates at accept, `initFakeRing`; AUTO grows
  at the dispatch site, `server.c:~5998`), and is deliberately inside the window; its bounded
  convergence and post-settle stability are proven by the persistent-conn cell below.
* CONVERGENCE + ANTI-THRASH (persistent conns, spec rev 2): the AUTO decay cell's burst now
  runs `FR_BURST` s. Settle signal = `used_memory` stable (3 consecutive 2 s samples within a
  256 KB band, bound `MEMSET_MAX`) ⇒ CONVERGENCE row with `convergence_time`. Then 3×`AT_WIN`
  windows on the UNCHANGED burst count **growth events** (window max > settled base + 512 KB):
  0/1/>1. Growth after settle == thrash. (Proxy note: no grow counter exists; 512 KB catches
  multi-conn oscillation — a single conn's ring re-grow is below the proxy's floor.)
* Decay (the part memtier can't test — it disconnects): the same driver then **holds the
  connections open idle**. AUTO must give back ≥ 1 MB of `used_memory` during the hold (rings
  decay to 1, `fakeRingClientCron`); the STATIC-32 arm is the positive control (short burst,
  no decay path ⇒ < 1 MB movement).

### 4. Fake-buf demand-grow (`tomokv-fake-buf -1`)
* SHIFT: 20 conns × p8 GET of 32 KB values ⇒ `used_memory` grows ≥ 3 MB (bufs 1 KB → up to 64 KB cap).
* ENVELOPE-return: **code truth — there is no "window reset"** in this tree (D1 is demand-pull
  only; the dead pressure counters were removed, `networking.c` ~:894). The return path is D3 ring
  decay / client free, so the check holds connections idle and requires ≥ 50% of the grow back.
* AUTO==STATIC 4096 on the 64 B workload.

### 5. ex-queue depth AUTO (`tomokv-ex-queue-depth -1`)
* Boot-log derivation must match the formula in `server.c:3702-3738`:
  `want = 4×(io_threads+1)×pipeline_depth`, floored at 2048, capped at `TOMO_EX_QUEUE_SIZE_MAX`
  (=2048 ⇒ **auto always resolves to 2048** on any config; io4 logs `want 640, floored`).
  INFO `tomokv_ex_queue_depth` must read 2048.
* Exhaustion counter: the positive control runs **first** — static depth **64** (256 was 4×5×256
  of ring capacity, more than any burst holds in flight) under an 8-key skewed p64×16-conn burst
  (deliberately NOT single-key — the known dropped-dispatch wedge; the cell is isolated and the
  server discarded). Then `tomokv_ex_queue_full` must stay 0 under normal p32 load at auto depth —
  and that 0 only earns PASS **if the positive control proved the counter fires** (else SUSPECT:
  an absence-check with an unproven observable is no evidence).
* AUTO==STATIC 2048 throughput parity.

### 6. Express-slim Schmitt (`tomokv-express-slim -1`)
* AUTO==STATIC 70 and AUTO==STATIC 0 parity on 1:1 GET/SET p4.
* Live-set 0/50/100/−1 under traffic (MODIFIABLE knob) with traffic surviving each value.
* Engage/disengage is **not observable** — `server.express_hit_ewma` is exported nowhere
  (KNOWN + coverage gap; export `tomokv_express_hit_ewma` in INFO to close it).

### 7. Allocator pools + decays
Caps read from code: retire-node pool `FLAT_NODE_POOL_CAP` 4096/worker (64 KB), flat batch spare
`FLAT_BATCH_SPARE_MAX` 8/worker, pcmd pool `PCMD_POOL_CAP` 128/io-thread (argv ≤ 64), xsub pool
`XSUB_POOL_CAP` 96/io-thread, operand pool `OPERAND_POOL_CAP` 256/io-thread (knob-gated, default off).
* ENVELOPE: overwrite churn then idle — settled `used_memory` ≤ baseline + 16 MB (the caps sum
  to single-digit MB; a leak dwarfs them). The baseline is taken after a **memtier prefill of the
  same keyspace the churn writes** — seeding only `k:*` keys left the churn to add ~100k new
  memtier keys (~10–18 MB) inside the 16 MB envelope, a built-in false FAIL. Retire-node trim
  (`flatNodePoolTrim` every 4096 worker passes) is subsumed by this bound — occupancy has
  **no counters** (KNOWN).
* Operand pool: functional only (overwrite + GET correctness + traffic); perf marked KNOWN
  (project memory: regression on this fork).
* xsub pool: 16-conn MGET×16 storm via the persistent driver; MGET correctness (checked AFTER the
  storm, against a **unique sentinel value** on k:0 — seedkeys writes identical values everywhere,
  which would let a wrong-key return pass) + bounded memory.

### 8. FLATSTORE resize coordinator (`tomokv-flat-store yes`, shared node dbs ⇒ needs ex ≥ 2)
* SHIFT-grow: seed 2 M keys (400 k smoke) **with a concurrent memtier write load** ⇒ ≥ 2
  `FLATSTORE resize: … rebuilt A -> B` lines, every grow line B == 2A (doubling); then traffic
  must still serve (no wedge, 0 crash markers).
* SHIFT-shrink: DEL 95% + write trickle ⇒ ≥ 1 rebuild with B < A. Code truth: `flatDelete` itself
  flags `resize_needed` when live ≤ load_pct/4 of table (`flatstore.c:217`), and `flatTableAllocFor`
  genuinely halves toward FLAT_MIN_SIZE (`flatstore.c:241` — its header comment "never shrink below
  old->size" is stale). ENVELOPE: settled RSS ≤ 75% of peak, sampled **20 s after** the shrink —
  the binary is jemalloc 5.3 (`dirty_decay_ms` ≈ 10 s), sampling at +5 s races the purger.
* `tomokv-flat-load-pct` has **no AUTO** (range 40–90, no −1 — `config.c:3287`) ⇒ the task's
  "auto/static equivalence if auto exists" resolves to N/A (KNOWN); 40/90 boot spot-checks in #13.

### 9. QSBR reclaim (the 38 GB-class regression gate)
* 60 s overwrite churn on a fixed 100 k-key working set: `tomokv_flat_batches_pending` sampled
  every 2 s must stay < 10 000 (bounded, not monotonic — healthy steady state is tens; 10 000 is
  ~2 orders above healthy, well below the incident's unbounded growth; the shape gate). RSS peak
  ≤ base + 1.5 GB and settled ≤ base + 300 MB is the hard byte gate (incident rate ~210 MB/s ⇒
  a real leak clears 1.5 GB in <10 s of churn).
* Churn stop ⇒ pending ≤ 16 within 30 s (return time recorded).

### 10. Reshard auto-tune (`tomokv-reshard-min-ops`)
* Code truth: there are **two** actuation paths — the k-sigma outlier path (`reshard AUTO:`,
  `server.c:11000`) and the diffusion-leveling path (`reshard DIFFUSE:`, `server.c:10808`). Both
  count as movement in both arms (a diffusion flap is a flap; a diffusion-handled skew is a fire).
* Anti-flap arm FIRST: uniform R:R 100 k keys at default min-ops 20 000 ⇒ **zero** AUTO+DIFFUSE
  lines. Positive control for that grep is the skew arm.
* Skew arm: gaussian over 16 keys at min-ops 1000 ⇒ AUTO or DIFFUSE fires AND `reshard DONE:`
  completes; NOREG: during vs pre (pre = median of 3×10 s): ≥80% PASS, 60–80% SUSPECT (drift
  gray), <60% FAIL — the during-window is inherently single (the reshard happens once).
* Deliberately NOT single-key saturation: the dropped-dispatch wedge (hot sites ignoring
  `exQueuePush` −1) is fixed on the 3s dev branch only — out of scope here (KNOWN).

### 11. Worker pop batch / num-cdb / pipeline-depth
* pop batch: −1 resolves to `WORKER_POP_BATCH` = 16 (`server.c:294`) ⇒ AUTO==STATIC 16 parity.
* num-cdb: auto = multi-L3 ? num_workers : 1 (`server.c:3970`); the resolved value is **neither
  logged nor in INFO**, so the suite recomputes `detectL3Domains()` from sysfs and runs parity
  against that static arm (single-L3 box ⇒ 1). KNOWN gap: the multi-L3 branch is untestable here.
* pipeline-depth: auto → 32 (max) with a boot log; INFO `tomokv_pipeline_depth` equality in both
  arms is the exact check, plus throughput parity.

### 12. pf-w-* prefetch widths
* Flat store: `kvstoreGetDict` NULL retires `PFS_HASH` ⇒ hash/entry/value(+nextop feed) stages
  inert. NOTE the blanket "pf inert on flat" is overbroad — struct/argv/keyobj/keybytes still
  issue prefetches (`server.c:14690-14740`). Check: all 8 knobs cycled 8/0/−1 live under traffic,
  no crash ⇒ KNOWN (wave-engine successor owns flat prefetch).
* Dict mode (`tomokv-flat-store no`): same cycle must survive; **firing has no counter** in either
  mode, so "does fire" is asserted only as reachable-and-harmless (coverage gap).

### 13. Knob −1/0/N normalization spot-checks (knob_matrix.sh pattern)
Boot + `CONFIG GET` echo + 5 s traffic + crash-scan for: fake-ring-depth −1/0/8 (0 = OFF depth 1
in this tree — `networking.c:590` — the old knob_matrix "0=eager" note is stale), fake-buf −1/0/4096,
express-slim −1/0, pipeline-depth 0/8, ex-queue-depth 0 (must warn + auto)/1024, worker-pop-batch 0,
num-cdb 0/4, flat-load-pct 40/90, flat-store no. The ex-queue-0 documented warning is asserted.

## Harness-trap immunity (each burned a real run once)

Encoded in the script: kill-own-PID only + `wait $PID`; preflight refuses a busy box (comm
truncation handled: `memtier_benchma`); flock; exactly-one-server assert after every boot;
memtier `Totals` col 2 = ops/sec (last col is KB/sec, not errors); worker-dispatched commands are
invisible in `total_commands_processed` so all throughput comes from memtier ops; one INFO call
per sample; per-cell logs preserved; every absence-check paired with a positive control;
plausibility gate 1 k–20 M ops/s (nonsense ⇒ SUSPECT, never PASS); ABBA interleave with fresh
boots per rep; medians of ≥3 in full mode.

## Coverage gaps (also listed per-row as KNOWN/SUSPECT in the TSV)

1. Quorum-balancer p99-veto path not exercised (needs a latency-degradation injector).
2. Express-slim engage/disengage unobservable (no INFO/log export of the hit EWMA).
3. num-cdb resolved value unobservable; multi-L3 auto branch untestable on a single-L3 box.
4. Fake-ring growth has no counter — inferred from static-32 parity.
5. Fake-buf has no window reset in this tree — ENVELOPE tests the decay-return path instead.
6. pf-w firing has no counter; dict-mode check is reachability-only; flat inertness is per-stage,
   not blanket.
7. `tomokv_ex_queue_full` positive control may not fire even at depth 64 (SUSPECT if so — and the
   nofull absence-check is then also capped at SUSPECT, never PASS-by-silence).
8. Pool occupancy/trim transitions have no counters — envelope-bounded only.
9. Single-key saturation reshard excluded (known dropped-dispatch wedge, fixed on 3s dev only).
10. Flip AUTO-vs-STATIC cannot be truly ABBA-interleaved (controller needs convergence time);
    mitigated by cycling the static arms across passes before the auto run.
11. Operand pool perf is KNOWN-regression per project memory; verified functionally only.
12. `tomokv-flat-load-pct` has no AUTO mode — equivalence check N/A by code.
13. Flip floor: io_threads_live can never go below the boot io_threads (grow-back reclaims grown
    slots only). Ex-ward shift is therefore tested as a RECLAIM from a grown state (io>4 → back),
    never from an io-heavy boot — "shift below boot config" does not exist in this build.
14. The balancer p99-veto and the flip look-ahead/coast branches are not separately exercised
    (no latency injector); they ride along in the no-thrash windows only.
