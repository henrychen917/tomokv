# Load-Balance Imbalance Model — TomoKV / THredis

A closed-form model for when the three load balancers (client LB, key LB, flip LB) have
anything to correct, how much, and when balance is *structurally impossible*.

All architecture claims below were verified against the source at `22713766a`; file:line
citations are given. Numbers marked **MEASURED** come from artifacts on disk; **DERIVED** are
arithmetic on measured inputs; **INFERRED** are model predictions not yet tested.

---

## 1. Notation

| symbol | meaning |
|---|---|
| `N` | NUMA nodes |
| `W` | worker (ex) threads **per node** |
| `I`, `E`, `T` | IO threads, ex threads, `T = I + E` |
| `B = 16384` | buckets (`TOMO_BUCKETS`, `server.h:1474`) |
| `K` | key count; `f_k` = request rate of key `k`; `R = Σ f_k` |
| `C` | client count; `g_c` = request rate of client `c` |
| `p` | pipeline depth |
| `L_w` | load of worker `w` = `Σ_{k∈w} f_k` |

Two shape parameters, both coefficients of variation:

- `c_f = σ_f / μ_f` — spread of per-**key** access rate
- `c_g = σ_g / μ_g` — spread of per-**client** request rate

---

## 2. The core result

A key reaches a worker through `bucket = xxh64(key) & 16383` then
`worker = ex_bucket_table[bucket]` (`server.h:2781`). The hash makes the assignment
effectively independent with probability `1/W`, so

```
E[L_w]   = R / W
Var(L_w) = (1/W)(1 - 1/W) · Σ_k f_k²
```

Define the **effective key count** (inverse Simpson index / participation ratio):

```
K_eff = R² / Σ_k f_k²
```

Everything collapses to:

```
CV_load ≈ sqrt( W / K_eff )
```

**Imbalance is governed by the *effective* key count, not the raw key count.** That single
substitution absorbs all skew.

### 2.1 K_eff for common distributions

| distribution | `K_eff` | `CV_load` |
|---|---|---|
| uniform | `K` | `sqrt(W/K)` |
| Gaussian rates, CV `c_f` | `K / (1 + c_f²)` | `sqrt( W(1+c_f²) / K )` |
| one hot key, fraction `h` | `→ 1/h²` | `≈ h·sqrt(W)` |
| Zipf(α≳1) | `O(1)` in the head | dominated by the head |

Real KV workloads are Zipf, not Gaussian. **Gaussian is the optimistic case**; treat its
predictions as a lower bound on imbalance.

---

## 3. Probability of imbalance

With `K_eff / W ≫ 1` the CLT applies. With `Φ̄` the standard normal tail:

```
P( max_w L_w > (1+τ)·R/W )  ≈  W · Φ̄( τ · sqrt(K_eff / W) )
```

### 3.1 Worked values (K = 2M, our standard cell)

| case | `CV_load` | P(>10% imbalance) |
|---|---|---|
| uniform, `W=4` | 0.14% | ~0 |
| Gaussian `c_f=1`, `W=4` | 0.20% | ~0 |
| hot key `h=5%`, `W=4` | 10% | ~0.5 |
| hot key `h=5%`, `W=24` | 24% | ≈1 |

**Statistical imbalance is negligible at our key counts.** Under uniform-ish access the key LB
has nothing to correct. All real imbalance is head-of-distribution.

---

## 4. When balance is impossible

The LB relocates **buckets**; a key is atomic. If the hottest key exceeds a fair share, no
assignment balances:

```
h > 1/W   ⇒  unbalanceable,  residual overload ≥ hW - 1
```

| `W` | impossible when a single key exceeds |
|---|---|
| 4 | 25% of traffic |
| 8 | 12.5% |
| **24** (Threadripper) | **4.2%** |

**This gets harder as workers increase.** On a 24-worker part any key holding >4.2% of traffic
makes perfect balance structurally impossible. This is the quantitative statement of
*hot key ≠ hot bucket*: a bucket flip **relocates** load, it never **divides** it.

Additional floors:

- **bucket granularity** — `max_bucket_load · W` relative to mean
- **cross-node** — LB is in-node only, so `CV_node = sqrt(N(1+c_f²)/K)` is **uncorrectable**

---

## 5. Client axis

Identical algebra, different scale. `C_eff = (Σ g_c)² / Σ g_c²`:

```
CV_io = sqrt( I / C_eff ),    C_eff = C / (1 + c_g²)   (Gaussian)
```

**Assignment policy changes the exponent, not merely the constant.** Our client LB balances
*connection count*, which removes the Poisson term but not the heterogeneity term:

| policy | `CV_io` |
|---|---|
| random assignment | `sqrt( I(1+c_g²) / C )` |
| **count-balanced** (current) | `c_g · sqrt( I / C )` |

Count-balancing is **exact** at `c_g = 0` and buys nothing as `c_g` grows. Improving on it
requires balancing by **load**, not connections.

### 5.1 Client vs key imbalance

`C ~ 10²` while `K ~ 10⁶` — same formula, four orders of magnitude apart:

| axis | config | CV |
|---|---|---|
| **client** | `I=4, C=200, c_g=1` | **14.1%** |
| client | `I=4, C=200, c_g=0.5` | 7.9% |
| key/worker | `W=4, K=2M, c_f=1` | **0.20%** |

**Client imbalance is ~70× larger than key imbalance** at realistic counts, purely because
there are far fewer clients than keys.

Connections are atomic too, so the same hardness criterion applies:

```
h_c > 1/I  ⇒ unbalanceable ;  count-balancing floor ≈ I / (2C)
```

`I=4, C=200` → 1% floor (fine). `I=4, C=8` → **25% floor** — with few fat connections the
client LB is structurally too coarse and no policy fixes it.

---

## 6. Front/back split (flip LB)

Per command: front cost `a + s/p` (per-command parse + syscall amortised over depth `p`),
back cost `b`. With `c = b/a` and `σ_s = s/a`, the back-heaviness fraction is

```
β(p) = c / ( c + 1 + σ_s/p )
```

monotonically increasing in `p` — **pipelining is back-heavier**. The optimum split is
`E/T = β(p)`; integer thread counts impose a quantisation error `≤ 1/(2T)`.

### 6.1 Calibration against our own measurements

Two measured optima (**MEASURED**, `thredis-flip-controller-momentum`): `p=1` best near
io7/ex1–io6/ex2 (`E/T ≈ 0.15`); `p=32` best io4/ex4 (`E/T = 0.5`). Solving:

```
c ≈ 1.18      (execution ≈ 1.2× per-command front work)
σ_s ≈ 5.7     (a syscall ≈ 5.7 commands' worth of front work)
```

Predictions (**INFERRED**):

| `p` | `β` | `E` at `T=8` | measured |
|---|---|---|---|
| 1 | 0.15 | 1 | io7/ex1 ✔ |
| 8 | 0.41 | 3 | — |
| 16 | 0.47 | 4 | — |
| 32 | 0.50 | 4 | io4/ex4 ✔ |

Two parameters fitted to two points: this **fits**, it is not yet **validated**. `p=8` and
`p=16` are the falsifiable predictions.

---

## 7. Composite

Throughput is capped by the busiest thread on either axis, so by union bound:

```
P(imbalance > τ) ≈ I·Φ̄( τ·sqrt(C_eff/I) ) + W·Φ̄( τ·sqrt(K_eff/W) )
```

plus the flip axis quantisation `≤ 1/(2T)` around `β(p)`.

---

## 8. Architectural constraints (verified in source)

These bound what the model's recommendations can actually be implemented as.

### 8.1 The bucket table permits arbitrary mapping — but contiguity is assumed

`ex_bucket_table[TOMO_BUCKETS]` is a full `uint8_t` table (`server.h:2781`), so an arbitrary
bucket→worker mapping is *physically* representable. **However** `ex_bucket_end[]` is
maintained alongside it (`server.h:2779`: "worker i owns buckets
`[i? ex_bucket_end[i-1]:0, ex_bucket_end[i])`") and multiple consumers compute a worker's span
as `ex_bucket_end[w] - ex_bucket_end[w-1]`:

| site | use |
|---|---|
| `server.c:6846`, `:6857` | RANDOMKEY size-weighted worker choice |
| `server.c:7878-7879` | CS_KEYS sub bucket range |
| `server.c:10011-10020` | migration / reshard range |
| prefetch gate | per-worker footprint estimate |

**⇒ Buckets cannot currently be balanced without neighbours.** Non-contiguous ownership
requires fixing every consumer above.

### 8.2 The balancer is adjacent-pair boundary shifting

`server.c:10877` compares `mig_load_ewma[w]` against `mig_load_ewma[w+1]` — **adjacent**
workers — and moves the boundary between them. A hot bucket in the middle of a worker's range
can only be relocated by cascading. The tree records the cost: a `[8k,4k,2k,2k]` layout ran
uniform load at **75% of even-split capacity** (`server.c:10790`).

### 8.3 EWMA is still live

`mig_load_ewma[]` and `mig_load_ewma_fast[]` drive auto-reshard (`server.c:10679`, `:10877`,
`:10895`, `:10900`, `:10960`). A *different* EWMA bucket balancer was deleted previously for
breaching the ≤3% budget; this one remains.

### 8.4 Auto-reshard is on by default

`tomokv-reshard-min-ops` defaults to 20000 (`config.c:3305`) and `reshardAutoTune` runs at
1 Hz from `serverCron` (`server.c:2117`).

---

## 9. Consequences

1. **The key LB should be near-silent.** At `CV = 0.2%` it should essentially never fire;
   firing on statistical noise spends the ≤3% always-on budget for nothing. Its trigger belongs
   on head-of-distribution skew, with `h > 1/W` as an explicit *give up, this is unfixable*
   cutoff rather than an unbounded chase.

2. **The client LB deserves the budget and needs a load-weighted variant.** Count-balancing is
   provably exact only at `c_g = 0`.

3. **Our benchmarks cannot observe client imbalance.** `memtier -t8 -c25` creates 200
   *identical* connections assigned round-robin — precisely `c_g ≈ 0`, the one regime where
   count-balancing is optimal by construction. Every client-LB number we hold was taken in a
   regime where the mechanism cannot fail. A heterogeneous-client generator is required before
   any claim about client LB means anything.

4. **Client LB can safely go cross-node; key LB cannot.** A client's keys are spread across all
   buckets — and therefore all nodes — by the hash, regardless of which IO thread serves it. So
   no client→IO-thread placement avoids cross-node dispatch, which means client placement is
   **not** constrained by data locality the way bucket placement is. Cross-node client
   rebalancing is therefore legal, and it enlarges the pool from `C/N` to `C`, cutting
   `CV_io` by `sqrt(N)`. (Verify the reply-path cost before shipping: a worker on node *n*
   replying to an IO thread on node *m ≠ n* is a cross-node transfer — but by the argument
   above that already happens for most of a client's traffic.)

5. **The flip LB has a closed form.** `β(p)` gives the target split directly from the measured
   pipeline depth, so the controller can jump to it rather than hill-climbing — with
   quantisation `1/(2T)` as the irreducible error.

---

## 10. Open items

- Validate `β(p)` at `p=8` and `p=16` (the model's falsifiable predictions).
- Measure `c_f` and `c_g` from a real trace; all current values are assumed.
- Decide whether non-contiguous bucket ownership is worth the consumer fixes in §8.1 — it is
  the prerequisite for relocating an isolated hot bucket without cascading.
