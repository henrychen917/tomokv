---
name: thredis-ownread-wedge-rootcause
description: "ownread P0 wedge fully diagnosed — dispatch-lifetime read pins freeze the QSBR epoch (depth-nest ⇒ eternal odd), unbudgeted reclaim avalanche freezes worker pop loops; fixes = generation-counted pins + budgeted drain"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

2026-08-10, dev-ownread-replay @96102135d (ownread 3f4cea426 replayed onto dev 2f80ef045).

**Symptom** (gauntlet payoff cells): MGET8:MSET8 1:1 p32 keymax-64 wedges <1s — `tomokv_atomic_inflight` pins at window (512, or 64/128 — window-size INDEPENDENT), soak EMPTY. Correctness section ALL-ZERO (resolver semantics right). pure_mset healthy 527K. Reproduces IDENTICALLY on the pure fork binary ⇒ inherited, introduced by 46b490d78 (hold removal); merge-base 83e0600c7 completes fine (rc=0). This IS the session-close "EMPTY + inflight 512" signal.

**Verified chain** (gdb-parent + SIGTRAP at wedge, since ptrace_scope=1 blocks attach; `exec_tail` is a flexible array — `c['exec_tail'][0]`; `server.clients` is per-iotid array):
1. Every stuck group: `pending=1` (ONE sub never finishes), installs 3–7/8, commit_ready=1, abort=0. The last write sub sits in a worker's SPSC ring, published but unpopped (witnessed h=1580 t=1612, 32 entries).
2. Reads take a QSBR pin at dispatch (server.c ~8104, `flatQsbrRegionEnter` + commit_seq snapshot) released only at csReassemble (`tomoReleaseReadSnapshot`). Pin PREDATES ownread (same at 83e0600c7, "I7" comment) — ownread made it DENSE (holds used to park overlapping reads pre-dispatch, pre-pin).
3. flatExtern epoch design (per-slot `tm_io_sig[s].flat_epoch`, odd=inside) is DEFEATED by depth-nesting: only depth 0→1 publishes odd, only depth→0 publishes even. Overlapping group pins ⇒ depth never 0 ⇒ ONE eternal odd value ⇒ `flatBatchReady` clause (ii) ("epoch unchanged since close") blocks EVERY batch ⇒ `flat_batches_pending` 55K+, `flat_io_pinned:4` continuously.
4. When epoch finally moves, `flatWorkerReclaim` drains the ready prefix UNBUDGETED inside exSlice; payloads include `tomoVersionPruneAfterGrace` full-bag triple walks (bags ~64+ deep because commits stalled) ⇒ worker pop loop frozen seconds ⇒ stuck subs ⇒ more pinned groups. Post-load unwind ~35 groups/s; perf 56.8% process-wide in prune during unwind (NOTE: I profiled the unwind, not the load phase — apparatus lesson).

**Falsified en route**: bag-depth/window feedback (window=64 still wedges); EX-queue starvation (`tomokv_ex_queue_full:0`; `ex_queue_depth:2048` is a CONFIG ECHO not congestion).

**Fix set**: (A) generation-counted dispatch pins — per-slot outstanding-pin generation accounting so a batch is blocked only by pins taken BEFORE its close; inline command regions keep the epoch scheme. (B) budget flatWorkerReclaim/flatReclaimAll per pass (bounded pop-latency). (C) per-bag prune-callback coalescing = #102 perf follow-up, NOT needed for the P0 once A+B land.

**Gate for the fix**: wedge cell completes (rc=0) + batches_pending bounded + gauntlet correctness all-zero + payoff ≥ pre-fix 172K (target: kill the crater, OFF ceiling 958K) + 40s soak non-EMPTY with inflight draining.

**RESOLVED 2026-08-10 overnight** (dev-ownread-replay @f78b51409): A (cxpins gen-counted pins) +
B (cxdrain budgeted drain) merged, both witnessed (pin_backlog engages/drains, budget_trips 174K,
batches_pending bounded ~1.6K vs 67K runaway, wrap_blocks 0). THEN the decisive extra finding:
**tomokv-atomic-window default 512→64** — pile depth ∝ window, and window 64 beats 512 in EVERY
mixed regime AND beats PRE-ownread everywhere: 64-key 1to1 781K (4.8x the 162K crater — #101
DELIVERED), 9to1 1.19M (+21%), 1111 1.48M (+30%), 2M 1to1 774K (+28%), 2M 9to1 1.17M (+10%),
40s soak 782K/s clean. Only loser: pure_mset −6% (2M) to −13% (64-key) — window caps pure-write
pipelining; knob stays for write-heavy. Correctness all-zero on 4 consecutive full gauntlets.
Resolver own-scan gate (ea52b765a) also merged: sound (two-load: mset_pending_count + owner
stamp_pending) but a wash at p32 (every conn structurally has pending writes); helps count==0
regimes only. Residual perf item: the own-scan pile walk itself (was 26.7% of cycles at w512;
window 64 shrinks the pile ~8x) — real fix if ever needed = per-client own-install key index.

Related: [[thredis-qsbr-grace-pinning]] (the OOM-class warning that predicted this), [[thredis-epoch-fence-status]] (epoch was validated but its group-pin blind spot is this bug), [[thredis-flat-reclaim-capacity]] (per-worker reclaim origin), [[thredis-session-2026-08-09-close]].
