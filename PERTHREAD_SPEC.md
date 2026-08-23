# Task: per-THREAD locality, replacing per-CCX node granularity

## What exists (read these first)
- `src/core/placement.h` — Node = one L3 domain (CCX) holding ifid/ex/wb thread groups + a
  contiguous shard range. `--spread io:ex[:wb]` is PER NODE. `cpu_of_thread` picks distinct cpus
  within the node's domain.
- `src/base/topology.h` — self-discovery (one domain per shared-L3 group ∩ affinity) plus
  `declare()` for operator-declared domains (`--node-cpus "0-7,8-15"`, `+` glues ranges).
- `src/core/shard.h` — `Router`: `worker_of_shard[shard]` is ONE atomic load; shards carry
  `note_execution(domain)` local/foreign accounting and `note_migration`.
- `src/core/server.h` — builds placement, assigns `worker_of_shard`, wires sender targets
  (exwb/3s: per-node round robin over the node's ex/wb threads).
- `src/main.cc` — flags; boot printout of nodes/threads.

## What to build
Locality resolution becomes the INDIVIDUAL THREAD, not the CCX:

1. **Per-thread placement spec.** A new flag `--place` giving every thread its role and cpu
   explicitly, e.g. `--place "ifid@0,ifid@1,ex@2,ex@3,wb@4"` (role@cpu, comma-separated, order =
   thread id). Threads may sit on ANY cpu the affinity mask allows — same CCX, across CCX, across
   CCD, SMT siblings. When `--place` is given it is the whole truth: `--nodes/--spread/--node-cpus`
   are rejected alongside it (loud error, no silent precedence).
2. **Existing knobs become sugar.** `--nodes N --spread a:b[:c]` must keep working EXACTLY as
   today by lowering to the same internal per-thread representation the new flag produces. One
   representation, two front-ends.
3. **Locality identity per thread.** Each thread knows its cpu's L3 domain (from topology);
   `Shard::note_execution` keeps working unchanged — it already takes the executing thread's
   domain. Foreign/local accounting therefore becomes per-thread-resolution automatically.
4. **Shard homing per thread.** Shards are assigned to EX threads directly (round robin over ex
   threads by default; optionally `--shard-home "0:2,1:2,..."` shard:thread pairs for full manual
   control). The contiguous-range-per-node property is dropped; what must be preserved is
   `worker_of_shard[]` = one atomic load on the dispatch path.
5. **Sender assignment per thread.** exwb/3s: each ifid thread's send target comes from the
   per-thread spec — default round robin over ALL ex (exwb) / wb (3s) threads; optional explicit
   `--send-target "ifid_tid:sender_tid,..."`.
6. **PRESERVE THE MIGRATION CONTRACT — this is load-bearing for later work.** Shard/bucket handoff
   must remain: (a) one release store into `worker_of_shard[]`, (b) wait for the old owner's
   channel-quiesce (the retired frontier), (c) new owner touches the store. Nothing in the refactor
   may add a second synchronization point to that path, because single-pointer bucket handoff
   (O(1) reshard, ownership flip without key copies) builds directly on it later. Do not touch
   `src/store/flatstore.h`.
7. **Boot printout** shows per-thread lines: tid, role, cpu, L3 domain, shard count, send target.

## Constraints
- Boot-time only: no new hot-path work. Runtime lookups stay flat array loads.
- `WbProto`/ready-mask/slot machinery untouched.
- Keep every existing flag working; `--help` updated.
- Comments explain WHY at decision points, matching the file style you see.
- Code must COMPILE (`make -j8` in this worktree; JE=1 default). Do NOT run the server, do NOT run
  benchmarks, do NOT run any test scripts — implementation and compile only; validation happens
  elsewhere.
- Commit your work in this worktree in reviewable commits with real messages.

## AMENDMENT (owner rule — read before finishing item 5)
wb count ≠ ifid count in general, so the conn→sender binding is PER-CONNECTION state stored at
accept (never derived from ratios) — that part already exists. What your per-thread sender map MUST
preserve: the DEFAULT pairing round-robins only over wb/ex threads **in the accepting ifid's L3
domain** (this is the one surviving node rule: ConnIn/ConnOut/ROB form a seam that must not cross a
CCX). Fall back to nearest-domain only when the ifid's domain has no sender role at all. An explicit
--send-target that pairs across L3 domains is allowed (topology experiments want it) but must print
a loud per-pair WARNING at boot with both domains named. Boot printout: show each ifid's sender and
whether the pair is same-L3.
