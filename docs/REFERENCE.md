# TomoKV / THredis — durable reference

One file to re-enter this codebase without re-reading 20k lines of `server.c`. Assembled
2026-08-03 from the code (authoritative), cross-checked against `STABLE_PLAN.md`, `BUGS.md`,
`ARCH_BRIEF.md`, `ABCD_D_DESIGN.md` and the review docs.

**When this file and another doc disagree, the CODE wins, then this file, then the others.**
Several older docs describe work that was done "in someone's working tree" and never landed, or
was landed and later deleted. Three columns are kept strictly apart throughout: **built and live**,
**built then deleted/disproven**, **designed but never built**. Conflating them has cost real time
here more than once.

---

## 1. Fast re-entry map

| I need to understand… | Start here |
|---|---|
| slot space, maxes, bucket count | `server.h:1456-1546` |
| thread roles + identity protocol | `server.h:2816-2854`; `server.c:17902-17938` |
| QSBR epochs | `server.c:341-491`, `6975-7058` |
| per-worker reclaim | `server.c:7099-7131`; `flatstore.c:68-123` |
| flat table ops | `flatstore.h:19-46`; `flatstore.c:133-263` |
| resize state machine | `server.c:7189-7390` |
| resize vs non-worker mutators | `server.c:10906-10956` |
| SPSC ring | `server.h:2239-2294`; `server.c:16033-16207` |
| dispatch + back-pressure | `server.c:2603-2702`, `6585-6669` |
| handoff protocol | `server.h:2354-2375`; `server.c:16895-16947` |
| worker loop | `server.c:16776-17213` |
| xshard registry + gate | `server.c:7847-8189` |
| coalesced scatter | `server.c:9143-9210`, `9560-9703` |
| 2-hop (RENAME) | `server.h:1909-1951`; `server.c:8197-8250`, `10023-10420` |
| reshard | `server.c:10959-11520` |
| flip actuators + tick | `server.c:18230-18475` |
| flip controller | `server.c:19265-19870` |
| client LB / conn migration | `server.h:2856-2907`; `server.c:18477-18700` |
| reply buses (CDB) | `server.h:1569-1592`; `server.c:2313-2343`, `2725-2924` |
| zero-copy replies | `networking.c:890-961`, `1644-1700`; `server.c:16065-16101` |
| async client free (see §6 N) | `networking.c:2773-2905` |
| decoy db + node dbs | `server.c:4445-4461`, `4504-4576` |
| P0 ledger | `docs/BUGS.md` §A9, §A10, §D, §H2, §J3, §J4, §L, §N |
| what was deleted and why | `docs/STABLE_PLAN.md` §3e, §3f, §4, §5, §6 |

---

## 2. Architecture

### Thread model
Poly threads take one of three roles. **IO** ("ifid") threads own connections and run an event
loop; **EX** workers own bucket ranges and execute commands; **WB** exists in the 3-stage fork
only. `main` is **IO slot 0** and is the only thread permitted to run the resize coordinator,
`reshardCoordinatorTick()` and `tmFlipTick()`.

`iotid` is the identity. IO threads take `0..io_threads`; a **worker's `iotid` is
`TOMO_IO_THREADS_MAX + 1 + ex_slot` (≥33) — deliberately out of range** for any `[iotid]` array, so
a worker indexing an IO-thread-shaped array traps instead of aliasing. That is load-bearing: an
earlier bug had workers running `iotid=0` and aliasing IO thread 0's client slot.

### Sharding and the keyspace
`TOMO_BUCKETS = 16384`; `ex_bucket_table` maps bucket → owning worker. Real keys live in
`server.node_dbs[node][dbid]`; **`server.db` is an empty decoy**. `shared_node_dbs =
(workers_per_node > 1)`, which makes `tomokv-thread-ex` a *mode selector*, not just a count:
at `ex 1` the keyspace stays DICT-backed, at `ex ≥ 2` you get FLATSTORE, the owner lock and a
reachable reshard. **Any ablation that tests only one side of `ex ≥ 2` has tested one of two
execution models.**

`cluster-enabled` is refused: cluster and tomokv both want to define what a kvstore slot is.

### FLATSTORE
Unconditional since 2026-07-28 (the knob was retired at its ON value and folded away). Open
addressing with a 15-bit tag giving a **constant-depth** probe chain (~2 steps) — this is why AMAC
was rejected, see §4. `FLAT_LOAD_PCT 70`, `FLAT_MIN_SIZE 1<<18`.

Resize is a cooperative state machine, `IDLE → QUIESCING → COPYING → IDLE`:
- `flat_resize_active = 1` **parks every worker** at its pop point.
- Quiescence requires all workers out of `in_flat_section` **and** every non-worker identity out of
  its region (`flat_epoch` even). Non-worker mutators matter: `KEYS`/`SAVE`/`DEBUG RELOAD` execute
  inline on an IO thread and iterate the old table.
- `FLAT_RZ_QUIESCE_DEADLINE_US 200000` — coordinator aborts and retries.
- `FLAT_RZ_WATCHDOG_US 2000000` — any parked thread may abort a quiesce whose coordinator stopped
  running. **A watchdog abort means main stopped, which is usually a symptom of something else
  entirely** (this is exactly how §6 N was misdiagnosed twice).
- Only main drives the coordinator, so any main-thread spin that waits on a worker must pump it —
  `tomoFlatResizeQuiesce()` is the pattern: `if (iotid==0) coordinate(); else watchdog();`.

### QSBR
Epoch-based, reclaim runs on **worker passes**. `flatExternEnter/Exit` publish odd/even epochs per
IO slot; workers use `in_flat_section` + `loop_seq`. Retired tables are freed only once every
reader has left (`flatTableRetire` / `flatRetiredTablesTryFree`).
**The region is deliberately NOT held for ordinary dispatch** — doing so measured −17% on p32 SET
(`server.c:6208`). It brackets `performEvictions()` only.

### Dispatch
One SPSC ring per (worker, io) pair: `exThread.queues[TOMO_IO_THREADS_MAX+1]`. Depth is **always
exactly 2048** (the derived formula's floor equals its cap). Work is *staged* then *published*;
`ex_dirty_mask` (a `__thread` bitmask) is the single staging funnel and `flushExQueues()` iterates
it via `__builtin_ctzll`. Back-pressure spins rather than growing the ring.

`nq = io_threads + 1 + tm_ngrow_io` — the worker's queue scan, and it must match `freeback` and the
init loop exactly. All three agree today; if they ever diverge, a producer wedges.

### Cross-shard
The coalesced scatter builds **ONE sub per WORKER, not per key** (OPT-1), so one command stages at
most `nw ≤ 64` subs into 64 *distinct* rings and cannot overflow one. `nkeys >= 3` is load-bearing —
at k ≤ 2 the subs do not amortise the allocations. Non-owner multi-key reads are a **correctness
wall**, not a tuning question: they produced 1547/4000 ordering violations. Scatter-gather is
correct by construction in both directions.

### Resharding
O(1) bucket-ownership flip inside one shared physical kvstore — **no key copying** (the copy engine
was deleted; it had been unreachable at ex ≥ 2). Cutover is a drain fence: `migHoldIfDraining`
gates reads *and* writes (widening it to reads was a P0 fix). `mig_arm_lock` is held for the whole
resize so no migration can arm underneath.

### Flip controller
GROW-FRONT converts a worker to an IO thread, GROW-BACK the reverse; clients are re-balanced on an
even split. The controller is a momentum hill-climb with look-ahead and a deadzone.
**`io_sat` reads a batch-size signal, not utilisation** — a genuinely io-bound saturated state
reads `io_sat ≈ 0` and never triggers grow-front. Known limitation.

### Replies
One cache-line-isolated CDB bus per client per `num_cdb`, with **one atomic byte per pipeline
slot** (not a bitmask — a bitmask forced a locked RMW because other workers touch other bits).
One completer, one drainer, per slot. `num_cdb` is resolved once, topologically:
`detectL3Domains() > 1 ? num_workers : 1`.

The drain splices the **ready prefix in ring order, stopping at the first incomplete slot**. That is
the only delivery path for ring fakes — a fake reaching `clients_pending_write` writes ahead of
older in-flight replies and reorders the connection.

---

## 3. Runtime knobs (25 registered)

Authoritative: `src/config.c` `static_configs[]`. **`src/server.h` field comments state the wrong
default for four reshard knobs** (they say −1; the real default is 0) — for `cool-margin-pct` that
difference is behavioural. **`tomokv.conf` is materially out of date** (documents 16, omits 9, and
describes `tomokv-flip-rebalance`, which is not a knob — harmless only because it is commented out).

House rule is `-1 = auto, 0 = off, N = static`, but the reshard trio uses `0 = auto` because "off"
for the balancer is spelled `tomokv-key-lb 0`.

### Topology & threading
| knob | default | mut | what it does |
|---|---|---|---|
| `tomokv-nodes` | 1 | IMM | placement domains; meaning set by `pin-mode` |
| `tomokv-cores-per-node` | 0=derive | IMM | core budget/node |
| `tomokv-thread-mode` | **auto** | IMM | `auto` = flip + symmetric-pool remap; `static` = hold boot split |
| `tomokv-thread-io` | **mandatory** | IMM | IO threads per node; unset ⇒ boot FATAL |
| `tomokv-thread-ex` | **mandatory** | IMM | EX workers per node; **also the FLATSTORE selector** |
| `tomokv-pin-mode` | ccd | IMM | `float`/`ccd`/`numa`/`static` |
| `tomokv-pin-io` / `-pin-ex` | "" | IMM | explicit CPU lists; only valid with `pin-mode static` |

### Load balancing & resharding
| knob | default | what it does |
|---|---|---|
| `tomokv-key-lb` | **20000** | master switch + floor for the bucket balancer. **ON by default** |
| `tomokv-key-lb-sustain` | -1 auto | debounce ticks (alias of `reshard-sustain-ticks`) |
| `tomokv-key-lb-fine` | -1 auto | per-bucket window so the hot-KEY veto has resolution. Validated, worst arm −0.83% |
| `tomokv-client-lb` | **yes** | moves connections off a busy IO thread, within a node |
| `tomokv-reshard-chunk` | 0 auto | bucket granule |
| `tomokv-reshard-cool-margin-pct` | 0 legacy | destination bar (`0`→`<mean`, `-1`→`<0.85·mean`) |
| `tomokv-reshard-imbalance-pct` | 0 auto | outlier bar |
| `tomokv-reshard-progress-ratio` | 0 legacy | no-progress guard |
| `tomokv-reshard-fence-timeout` | 10000 ms | cutover fence watchdog; aborts exported, suite fails on non-zero |

### Dispatch, xshard, micro
| knob | default | note |
|---|---|---|
| `tomokv-strict-order` | 0 off | cross-IO ordering; non-zero forces a dense lane sweep. Per-queue FIFO holds either way |
| `tomokv-pipeline-depth` | -1 → **32** | in-flight per connection + fake ring size |
| `tomokv-prefetch-ex` | 1 | **levels 2 and 3 are accepted but inert** — only `== 0` is ever read |
| `tomokv-zerocopy-min-value` | 1024 | **effective floor is 16384** — see §5 |
| `tomokv-mset-move` | **no** | ownership handoff for xshard MSET values. Correct, never shown to pay |
| `tomokv-os-opts` | no | `TCP_QUICKACK` + `MADV_HUGEPAGE` |
| `tomokv-os-busypoll` | no | `SO_BUSY_POLL`; **suspected v12 regression** |
| `tomokv-io-uring` | **0** | one `SINGLE_ISSUER\|DEFER_TASKRUN` ring per IO owner. Double-FATAL-gated |

**`STABLE_PLAN.md` claims the io_uring backend was deleted. It was not** — `uring.c` is in
`REDIS_SERVER_OBJ`, `USE_URING` is live, and 34 `tomokv_uring_*` INFO fields exist. What landed was
the collapse of five bools into one immutable int.

---

## 4. DISPROVEN — do not re-attempt

Each of these was built or seriously attempted, measured, and rejected. The number is the point.

| thing | verdict |
|---|---|
| **Value forwarding** (Tomasulo-style read-run replay) | **Removed.** Neutral in every regime; real workloads lack the runs — **measured mean run length 1.008**. Cost 15 knobs + per-op hooks. Permanent paper negative result |
| **Cross-thread allocator ownership** | **~0.3% ceiling.** The real lever is allocation COUNT, not ownership |
| **Tiered operand pool** | Net-negative, deleted in the same commit as its A/B. The SET value operand never reaches `freePendingCommand`, so the pool cannot recycle it |
| **Non-owner multi-key reads** (worker-borrow, flat-native MGET) | **1547/4000 ordering violations.** A correctness wall, not tuning |
| **IO-side drain prefetch** | Net-negative in v11, ≈noise since; duplicated the splice loop's own walk |
| **IO-side prefetch generally ("C")** | **−3.9% p32 GET** |
| **More EX prefetch stages** | Base feature is a wash: −0.0004% / −0.43% / −0.23% with 173–356M hints issued. The worker is **overhead-bound**, not miss-bound |
| **Next-op look-ahead at distance = n** | `la = j+n` guarded by `la < n` is false for every `j` — **body unreachable**. AUTO ≡ 0 |
| **Chasing the old value on writes in the prefetch FSM** | **~35% regression** on pure-SET populate. The `CMD_READONLY` filter must stay |
| **Fixed 320 B `csGroup` inline region** | **+1.27% regression** (mset4_p32). Per-command derived sizing shipped instead |
| **`SO_BUSY_POLL`** | Regressed v12 throughput |
| **`IORING_SETUP_SQPOLL`** | Known regression for this workload class |
| **Freeing QSBR-retired values on main/bio** | **RSS 233 MB → 38 GB in 180 s → OOM.** Must free on the owning worker |
| **Walking the whole retire-batch list per pass** | **~16% of p32 SET.** FIFO oldest-first, stop at first non-ready |
| **Deriving EX queue depth below 2048** | Measurably regressed. AUTO may only add headroom |
| **AMAC for the flat table** | Structural: the probe chain is constant-depth, so the refill never fires |
| **Per-bucket LB counters for all 16384** | 1 KB → 64 KB/worker, past L1d, against a ≤3% budget |
| **Coalescing xshard at k ≤ 2** | Does not amortise; `nkeys >= 3` is load-bearing |
| **Per-node main thread** | Rejected on analysis: the problem is singleton STATE, not a singleton thread. Forking the thread without sharding the state gives N racing writers |

### Layout is load-bearing
- Inserting fields **mid-`exThread`**: **−16% p32 SET**, recorded twice independently. **Append at the end.**
- Inserting fields **mid-`client`** (reply-control cluster): **~2-5%**.
- Hinting the FLATSTORE `beforeSleep` arm UNLIKELY: it is the DEFAULT shape, so the hint laid the
  taken path out cold. The correction was to **drop** the hint, not invert it.

---

## 5. Gates that have never been shown to open

A feature behind a shut gate is untested, and a green run through one proves nothing.

- **`tomokv-zerocopy-min-value` at its 1024 default.** `isCopyAvoidPreferred` falls through to a
  16384-byte floor because `io-threads` can never reach 7 in this fork. **Nothing between 1024 and
  16383 bytes has ever taken the zero-copy path.**
- **`TOMO_PF_W_NEXTOP`** — unreachable body, see §4.
- **`fakeRingAutoTune` / `use_slim`** — reads `cmd->calls` for GET/SET, which never enter `call()`.
- **`tomokv-prefetch-ex` levels 2/3** — accepted by the validator, never read.

---

## 6. Standing rules (architecture, not process)

1. **Never add a lock to the per-connection request path.** Owner-publishes / reader-snapshots.
2. **A non-owner must never traverse another thread's structures.**
3. **Prove the test discriminates — see it FAIL pre-fix — and prove the gate OPENED.** Three
   separate instances of vacuous validation have cost real time here.
4. **A counter that cannot count certifies nothing.** Every new invariant ships with one:
   `handoff_missed`, `reshard_fence_midbatch`, `flat_rz_watchdog_aborts`, `q_full_events`,
   `tomokv_close_deferred_ring`.
5. **Sanity-gate every number.** `postmerge.sh` once reported a SEGV as "−13.9% / −50.6%".
6. **`instr/op` is polluted on this fork** — workers busy-spin, so a process-wide instruction count
   partly tracks idle time. **Use ops/s for throughput verdicts.**
7. **Test both storage regimes** (io4/ex4 p32 FLATSTORE and io7/ex1 p1 DICT).
8. **Retiring a knob means deleting the entry AND the field.** A field that outlives its config row
   falls to 0 by omission — which is how FLATSTORE was once silently turned off while the
   correctness suite stayed 15/15.

### Reference numbers (7700X, server 0-7, generator 8-15, ±2% when exclusive)
`p1 GET 826,877 · p1 SET 817,393 · p32 GET 7,943,860 · p32 SET 6,852,385`

### Measurement traps that produced false verdicts here
- Measuring a gated feature in the regime where its gate is guaranteed shut. **Always quote
  `issued` beside the throughput number.**
- Trusting a client-side timeout as evidence of a server fault (BUGS.md §M — thread-per-lane
  drivers starve on the GIL and raise the identical `TimeoutError`).
- Trusting a **PING** as a liveness control. PING is served on an IO thread and needs **no worker**,
  so it answers cheerfully through a total data-plane wedge (BUGS.md §N). Poll
  `total_commands_processed` instead — and subtract your own probes, or your polling makes the
  counter advance and a stall becomes undetectable by construction.
- Assert gate-open counters as a **delta**, never an absolute.
- A renamed binary defeats `pkill -x` and `pgrep -x`; `comm` truncates at 15 chars.

---

## 7. The next real win, per the tree's own conclusion

Per-worker throughput is pinned at **~2.0 M ops/s in every thread configuration**, while a **21×
dataset increase costs only 3.5%**. The worker is therefore limited by fixed per-command WORK, not
by cache misses — which is why every prefetch avenue in §4 came back a wash.

Nobody has decomposed the **~500 ns/command**. The prescribed next step is a `perf record` of a
worker at io5/ex3 p32, attributing that budget across fake-client setup, dispatch bookkeeping,
reply construction, allocation, and the command proc. *Two guesses have already cost −18.4% and a
deleted subsystem; a third guess is not warranted when the census is a day's work.*
