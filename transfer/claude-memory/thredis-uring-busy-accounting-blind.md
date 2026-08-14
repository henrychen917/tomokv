---
name: thredis-uring-busy-accounting-blind
description: "io_uring made the flip controller's io_sat signal read ~0.17 on threads pegged at 99.5% CPU, so the controller never actuated and uring servers stranded at their boot config (-23%); DEFER_TASKRUN runs work INSIDE io_uring_enter so wall-span accounting is structurally unfixable -- fixed by sampled CLOCK_THREAD_CPUTIME_ID"
metadata:
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

2026-08-03. The single worst uring defect, and it was invisible to every throughput test.

## The defect

`io_sat` (the flip controller's ONLY view of IO load) read **0.17 while the kernel measured those
threads at 99.5% CPU**. The controller therefore saw a near-idle server, made **0 flip decisions**
under uring versus 12 on epoll, and left the server at its boot config forever.

Cost: a uring server booted at io4ex4 sits at **640k ops/s** instead of the **828k** it reaches
once the controller climbs to io6. The *backend* is worth +0.2% to +6.4%; the *config the
controller finds* is worth **+37%**. The bug was ~6x more expensive than the feature it rode on.

## Why wall-clock bracketing cannot work here

The retired numerator was CLOCK_MONOTONIC "active wall spans, minus any potentially-blocking
poll". Under `IORING_SETUP_DEFER_TASKRUN` **the kernel runs completion work INSIDE
`io_uring_enter`** — so the syscall that model must treat as sleep is exactly where the CPU goes.
No placement of the brackets fixes it. Two failed attempts, both worth remembering:

1. Moved the bracket to close before `tomoUringReapAe` (reaping IS work — it parses and
   dispatches). io_sat 0.065 -> 0.10. Necessary, nowhere near sufficient.
2. Made the backend REPORT whether it actually blocked (under load `deferred_owner_work` is true
   nearly every pass, so the enter takes the non-blocking `submit_and_get_events` and the loop
   spins). **Zero change** — because the CPU is burned inside the syscall either way.

Only the scheduler knows the difference. Ask the scheduler.

## The fix (and it is CHEAPER than what it replaced)

`ioSlice()` publishes sampled `CLOCK_THREAD_CPUTIME_ID`, gated to ~16ms off the vDSO monotonic
read. The consumer takes a delta across a 250ms controller tick, so 16ms granularity is far finer
than needed. ~60 syscalls/s/thread vs **2-3 vDSO clock reads PER EVENT-LOOP PASS**. `aeIoTiming`,
the `timing` param of `aeProcessEventsIO`, and the whole wall-span block are DELETED (net -15
lines). `tmIoBusyBegin` re-baselines on role entry so a thread's previous-role CPU never lands in
the IO numerator.

Result: uring 632k -> 823k, 0 -> 12 flip decisions, converges to io=6 exactly like epoll; steady
io_sat 1.15-1.20 vs epoll's 1.16-1.24 (agreement between backends is the acceptance test). epoll
unchanged (808.8k vs 811.1k).

`server.h` documented `tomokv-io-busy-clock` with `thread-cpu` as "the default" long after the
knob was deleted from config.c in the 55->11 retirement — the retirement dropped the only mode
that survives uring, and the stale header hid it. **A knob retirement can silently delete a
correctness property; the comment outlived the code by months.**

## Two measurement traps this exposed (both bit me)

- **Never compare arms that ended at different thread configs.** I twice reported a "uring is 22%
  slower / burns 37% more CPU per op" finding that was purely epoll@io6 vs uring@io4. At MATCHED
  config uring never loses: +6.0% / +2.5% / -0.3% at io4ex4 / io6ex2 / io7ex1, and it uses LESS
  CPU per op everywhere. Corollary: uring's headline number is the *rescue-a-bad-config* number.
- **A signal averaged over a window that includes ramp-up lies.** `tail -30` of the flip log gave
  io_sat=0.634 post-fix; the steady-state tail gave 1.185. Nearly re-opened a closed bug.

Related: [[thredis-vacuous-validation-trap]], [[thredis-flip-signal-and-qdepth-truncation]],
[[thredis-ab-harness-traps]], [[thredis-sanity-gate-benching]], [[thredis-knob-philosophy]].
