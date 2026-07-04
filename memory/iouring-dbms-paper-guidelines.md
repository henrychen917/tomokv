---
name: iouring-dbms-paper-guidelines
description: "Jasny et al. VLDB'26 \"io_uring for High-Performance DBMSs\" — guidelines + tuning that validate/steer THredis's io_uring integration (v12-G/H/J/K)"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

Paper: "io_uring for High-Performance DBMSs: When and How to Use It", Jasny/El-Hindi/Ziegler/Leis/Binnig,
VLDB'26 (arXiv 2512.04859). PDF in uploads. Artifacts: github.com/mjasny/vldb26-iouring. Directly informs
THredis's io_uring work [[thredis-v12-sweep-results]].

CENTRAL THESIS (matches our findings exactly): NAIVE io_uring = net-neutral (1.06x buffer-mgr / 1.10x net
shuffle); a design that FULLY EXPLOITS it = 2.05x / 2.31x. "Treating io_uring as a drop-in replacement in a
traditional I/O-worker design is inadequate." → THredis's shallow io_uring being loopback-neutral (and our
v12 full-stack measuring 0.93-0.95x epoll) is the expected naive result.

4 GUIDELINES:
GL1 WHEN: io_uring only helps when I/O is the bottleneck; for CPU-bound/cache-resident workloads gains are
  small. → THredis small-KV on LOOPBACK is dispatch/CPU-bound, not network-I/O-bound → io_uring stays neutral
  there even with a perfect design. The win needs a REAL NIC + high connection count + larger payloads. (cf.
  [43] Zhou/Leis/Stonebraker CIDR'25 "Communication is the new bottleneck".)
GL2 ALIGN ARCHITECTURE: the recommended network design is RING-PER-THREAD with each worker owning a
  thread-local io_uring ring, co-locating compute + send/recv IN THE SAME THREAD (avoids I/O-worker handoff
  sync overhead + improves cache locality). PostgreSQL CAN'T use the best mode because its multi-process model
  shares rings (no exclusive single-issuer). → THredis's per-worker-thread model with exclusive ring ownership
  is BETTER positioned than PG. v12-K (worker-direct in-order send-back, per-worker ring) IS this guideline —
  it's the REQUIRED design, not just the ambitious one. The current CDB-notify→IO-thread-drain→writeToClient
  is exactly the "I/O-worker handoff" anti-pattern the paper warns against.
GL3 EXECUTION MODE: use DEFER_TASKRUN (DeferTR) + IORING_SETUP_SINGLE_ISSUER for predictable completion
  reaping + no preemption/IPI jitter. SQPoll only when a dedicated polling core is justified; avoid io_worker
  fallback. NAPI busy-poll + DeferTR = best latency (SQPoll wins only WITHOUT NAPI). → EXPLAINS our SQPoll
  regression. Switch THredis rings to DeferTR + single-issuer (per-worker rings have exclusive ownership, so
  DeferTR is usable — unlike PG). Re-eval SQPoll only with a spare core.
GL4 OPTIMIZATIONS (size-thresholded, Fig 16):
  - SEND zero-copy threshold ~1KiB: below it ZC is WORSE than plain io_uring send; above, ZC + REGISTERED
    BUFFERS = up to 2.90x fewer cycles/byte. (We used 4K in v12-H — align toward ~1-4K + add regbufs for the
    large send path.) Registered FDs: negligible benefit.
  - RECV: MULTISHOT best for SMALL messages (= THredis GET/SET keys + small values → v12-G multishot-recv is
    RIGHT for the common case); ZC-recv takes over >~1KiB; for very large (>~13KiB) plain single-shot recv
    beats multishot → recv path should be size-adaptive. Best config 3.54x fewer cycles.
  - RECVSEND_POLL_FIRST flag: skip the speculative inline attempt, go straight to the poll set — for RPC-style
    comms where the reply is only expected after the request (THredis is exactly RPC-style) → up to 1.5x fewer
    CPU instructions / less kernel work. ADD to the recv path.
  - Registered buffers: negligible for small messages (skip for small THredis replies).
ALSO: batching one io_uring_enter for N ops → 5-6x fewer cycles/op at batch 16-32 (the batched send-back
  lever, v12-J/K). Chen et al. [12] already applied io_uring to Redis (gains for medium/large payloads).

THredis honest position: small-KV loopback will stay ~neutral (GL1); v12-K's real value = (a) removes the
IO-thread reply-drain serialization (architectural, can help under high fan-in even on loopback), (b) the
ring-per-thread+DeferTR design is what the literature says is required for the real-NIC/large-payload win.
Frame the paper's compare (naive vs fully-exploited) as our template; CITE it.
