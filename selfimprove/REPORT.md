# io_uring: THredis deep-uring vs Dragonfly — report

*Box: Ryzen 7 7700X (8c/16t, single CCD), kernel 6.17, loopback. Servers pinned cores 0-7,
memtier 8-15. jemalloc. 3 interleaved rounds, medians. 2026-07-07.*

---

## A. Head-to-head bench (the 2×2: each engine, uring vs epoll)

Throughput, **M ops/s**, medians of 3 tight rounds (per-round spread <3%):

| system | GET 32B (P32) | GET/SET 32B (P32) | GET 512B (P16) | GET 4KB (P16) |
| :--- | :--- | :--- | :--- | :--- |
| **THredis, epoll** (uring off) | **7.996** | **6.971** | **2.580** | **1.272** |
| **THredis, io_uring** (recv+send+zc on) | 7.567 | 6.689 | 2.499 | 1.195 |
| Dragonfly, io_uring (default) | 5.771 | 5.453 | 0.823 | 0.608 |
| Dragonfly, `--force_epoll` | 5.464 | 5.104 | 1.029 | 0.772 |

**Three findings, all sanity-gated and reproducing prior sweeps:**

1. **io_uring is neutral-to-slightly-negative on loopback — for BOTH engines.** Our uring trails our
   own epoll by 3-5% on every cell; Dragonfly's uring trails its *own* epoll on the large-value cells
   (0.82 vs 1.03 on 512B). This is exactly the published result (VLDB'26: "naive io_uring is
   net-neutral on loopback; the 2-2.3× payoff needs a real NIC"). On loopback there is no NIC latency
   or DMA to hide, so the SQE/CQE bookkeeping is pure overhead. **This is why our uring path ships
   default-off** — its value is the real-NIC/EPYC regime, not this box.

2. **THredis beats Dragonfly on every cell, every engine:** GET32 1.38×, GET/SET 1.28×, GET512 **2.5×**
   (vs Dragonfly's better engine), GET4k 1.65×. The gap widens with value size.

3. **The gap is dominated by Dragonfly's large-value collapse** (section C): its 512B pipelined-GET is
   0.82M vs our 2.58M.

---

## B. How Dragonfly implements io_uring (helio source study)

Dragonfly's IO is helio's `UringProactor` — one io_uring ring per proactor thread, fiber-per-connection.
Studied from `helio-src/util/fibers/uring_proactor.cc` + `uring_socket.cc`.

| dimension | Dragonfly / helio | THredis deep-uring | verdict |
| :--- | :--- | :--- | :--- |
| setup flags | `SINGLE_ISSUER\|DEFER_TASKRUN\|COOP_TASKRUN\|TASKRUN_FLAG\|SUBMIT_ALL`, kernel-gated, `LOG(FATAL)` if refused | `SINGLE_ISSUER\|DEFER_TASKRUN` + **runtime probe & fallback** | match on the core; **we add fallback** (more robust). Adoptable from them: `TASKRUN_FLAG` (skip-the-enter), `SUBMIT_ALL` (one bad SQE ≠ abort batch) |
| register_ring_fd | yes | yes | match |
| CQ sizing | default 2×SQ | explicit `CQSIZE` | **we do more** (justified — our multishot buf-ring bursts CQEs) |
| submit model | one `submit_and_get_events` per pass, gated by `SQ_TASKRUN`; separate idle-only blocking wait | one `submit_and_wait` per beforeSleep pass | match in spirit (batch once/pass) |
| recv | **default synchronous** `PrepRecv`; multishot+buf-ring **opt-in, off by default**; MTU buffers **+ RECVSEND_BUNDLE + incremental buffers** | provided-buffer ring + **always-on** POLL_FIRST multishot, ENOBUFS re-arm | match on core; **we miss BUNDLE + incremental buffers** (real-NIC recv efficiency) |
| **send** | **plain SEND/SENDMSG — NO zero-copy anywhere** (grep-confirmed) | **ZC send >1KiB, detach-on-submit, async F_NOTIF reaping, registered buffer pool** | **we go beyond helio** — this is the biggest divergence and the VLDB "exploited send" recipe |
| accept | single AcceptLoop, no multishot accept; `SO_INCOMING_CPU`/NAPI steering → migrate to owner | dedicated IO threads own conns | neither uses multishot accept; **their RX-CPU steering is a real-NIC locality win to consider** |
| cross-thread wake | `MSG_RING` submitted on the caller's *own* ring (never touches another ring) | main-thread cancel under pauseIOThread → forces recv ring PLAIN on 6.17 | architecture-driven; their socket-migration model sidesteps our `-EINVAL` |
| NAPI busy-poll | not used | not used | both miss it — real-NIC opportunity |

**Net:** we match or exceed helio on setup hygiene, batching, and multishot-recv, and **exceed it on the
send path** (zero-copy + registered buffers — the thing helio leaves entirely unexploited). Four concrete
things helio does that we don't and that *would matter on a real NIC*: `RECVSEND_BUNDLE`+incremental recv
buffers, `SO_INCOMING_CPU`/NAPI connection steering, the `SQ_TASKRUN` skip-the-enter micro-opt, and the
`SUBMIT_ALL`/`TASKRUN_FLAG` flags. None are blocked by our architecture — all adoptable for the EPYC eval.

---

## C. Dragonfly's ≥256B pipelined-GET collapse — root cause

Reproduced hard: 512B GET = 0.82M vs 32B GET = 5.77M (a 7× intra-engine cliff), while ours degrades
gracefully (7.99M → 2.58M). The cause is **above the io_uring layer**, in Dragonfly's reply builder —
two compounding mechanisms (`facade/reply_builder.{cc,h}`, `dragonfly_connection.cc`):

- **(A) Fundamental, compile-time.** `reply_builder.h` hard-codes `kMaxInlineSize=32` and
  `kMaxBufferSize=8192`. At ≤32B a reply is copied inline and coalesced until ~4KB → **~128 replies per
  one `SEND`**. Above 32B the value is emitted as an *external iovec* and the builder flushes every ~8
  replies (~4KB) → **~16× more `SENDMSG` syscalls**, no matter how deep the client pipelines. That send
  fragmentation is the collapse. These caps are `constexpr` — **raising them needs a recompile**.
- **(B) The io_uring send path amplifies A.** Each fragmented `SEND` is an SQE+CQE round-trip; through
  io_uring that costs more than epoll's direct `writev`, so the fragmentation hurts *more* under uring.
  (A default squashing layer, `--pipeline_squash=1`, was suspected as a third factor but the bench below
  shows it's negligible on the plain-GET borrowed-reply path.)

**Is it fixable by config? Barely — and not the obvious way.** The flag-sweep below (C.1) overturns the
first-guess: `--pipeline_squash=0` does *nothing*; `--force_epoll` is the only lever (+23%) because it
sidesteps (B). But the best config still sits **2.5× below THredis** — the real cap (`kMaxBufferSize`)
is compile-time, so the collapse is **structural**, not a tuning mistake.

### C.1 Flag-sweep — the source hypothesis was PARTLY WRONG (sanity-gate catch)

Dragonfly GET512/GET4k (M ops/s, 8 proactors):

| variant | GET 512B | GET 4KB |
| :--- | :--- | :--- |
| default (squash=1, io_uring) | 0.838 | 0.606 |
| `--pipeline_squash=0` | 0.844 | 0.587 |
| `--squashed_reply_size_limit=2048` | 0.813 | 0.602 |
| `--force_epoll` | **1.030** | **0.773** |
| `--pipeline_squash=0 --force_epoll` | 0.913 | 0.549 |

**What the bench overturns:** the source read predicted `--pipeline_squash=0` as the big lever and
`--force_epoll` as a no-op. The measurements say the **opposite**: squash=0 moves nothing (0.844 vs
0.838 — on the plain-GET *borrowed* reply path squashing was already near-zero-copy, so removing it
changes nothing), while `--force_epoll` is the only real recovery (**+23%** on 512B). So the collapse is
dominated by **Mechanism A (the compile-time 8KB coalescing cap)** — its fragmented `SENDMSG`s are simply
*more expensive through io_uring* (SQE+CQE round-trip per fragment) than through epoll's direct `writev`,
which is why removing io_uring helps and removing squash doesn't.

**And it's not config-fixable.** Even the best flag (`--force_epoll`) recovers only ~23% and stays
**2.5× below THredis** (1.03M vs 2.58M). Raising the real cap (`kMaxBufferSize`) needs a recompile. So the
large-value collapse is *structural* in the shipped build, not a tuning mistake.

**Why it matters for us:** our ZC/detached send keeps a large value as **one DMA**, never fragmenting —
this large-value regime is structurally where our design pulls ahead, and it will widen on a real NIC.

---

## D. Loop-2 status (forwarding + deep-uring, this session)

- **Forwarding — falsified a third time, honestly.** The L0 worker read-latch (version-guarded,
  no-UAF-by-construction) was implemented fully and **failed its bench gate** (extreme-hot −0.22% vs the
  +2% bar). The doctrine-grade reason: *hot keys have hot dict paths* — a latch-hittable key is already
  L1-resident, and the expensive cold/DRAM lookups are the ones that never repeat. Combined with the two
  prior walls (run-length ≈1.008; lookup-not-the-bottleneck), forwarding is thoroughly dead on this
  arch/hardware. Patches preserved for the Threadripper (cross-CCD) revisit.
- **ORDER-1 — a real correctness bug, found via the forwarding work, fixed + validated.** Inline commands
  (PING/ECHO) never set `CLIENT_EX_PENDING`, so their replies could jump up to 31 older in-flight replies
  on the wire — a RESP ordering violation visible to any pipelining client, **pre-existing in canonical
  stable**. Fixed on `2s-forwarding2-dev` (`b8ac230b4`); the 20-run repro went **4/20 → 0/20**.
  **Recommend cherry-picking to canonical stable/3-stage.**
- **Deep io_uring — complete, EPYC-ready** (`2s-deep-uring-dev`): SI|DTR + fallback probe, register_ring_fd,
  batched submit-per-pass, runtime bufring + POLL_FIRST multishot recv, and ZC send rebuilt as
  detach-on-submit with async F_NOTIF reaping + registered buffers. Loopback-neutral by design (section A);
  the payoff is the real-NIC eval, where our send path is exactly what helio lacks.

## Recommendations
1. **Cherry-pick ORDER-1** to canonical (validated, low-risk correctness).
2. **The real io_uring verdict is pending a real NIC** — on loopback it's neutral for everyone; queue the
   EPYC/25GbE eval where our ZC-send divergence from Dragonfly should finally pay.
3. Optional adoptions before that eval: `RECVSEND_BUNDLE`+incremental recv buffers, `SO_INCOMING_CPU`
   steering, `SQ_TASKRUN` skip-enter, `SUBMIT_ALL`/`TASKRUN_FLAG`.
