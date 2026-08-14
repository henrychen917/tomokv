---
name: thredis-soak-harness-truth
description: "stress_validation soak: 6 runs. N is SOLVED — freeClientsInAsyncFreeQueue re-queued the client it was freeing; plus the PING-is-not-liveness rule and the 7 harness defects found along the way"
metadata:
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

2026-08-03. Six `stress_validation` runs at `2s-numa-stable-dev`.

## N — SOLVED. The drain re-queued the client it was freeing

**Not a FLATSTORE resize bug, and not DEBUG RELOAD.** Both were symptoms, and I chased each for a
full run before the stack settled it.

`freeClient()` returns early through `freeClientAsync(c)` when a real client still has worker
commands in flight (`dispatchid != flushid`). `freeClientsInAsyncFreeQueue()` clears
`CLIENT_CLOSE_ASAP` immediately before that call — it must, because `freeClient()` deletes the list
node itself when the flag is set and the drain deletes it again — and clearing it disarms the
re-entry guard at the top of `freeClientAsync()`. The client is re-appended to the **tail of the
list the drain is walking**; `listNext()` reaches it, retries, re-appends, forever, one `zmalloc`
per turn. The pass never returns to the event loop, so `handleWorkerReplies()` never advances
`flushid`, so the condition can never clear.

The drain already skipped `CLIENT_PROTECTED` and `CLIENT_EX_PENDING` for exactly this reason. It did
not skip ring-not-drained — and **`CLIENT_EX_PENDING` is only ever set on FAKES**
(`fake->flags`/`sub->flags`), never on a real client, so it protects nothing here. Fixed in
`networking.c` (skip + bound the pass to entry length) with counter
`INFO tomokv_close_deferred_ring`.

**The window needs workers that CANNOT drain**, which is what a FLATSTORE resize park gives you.
That is the entire reason it always appeared next to a resize event and looked like a resize bug:
the livelocked thread allocates flat out, starves main on the **allocator lock**, main stops driving
the resize coordinator, and that subsystem's 2 s watchdog fires and writes the only log line.

## The rule this cost the most to learn: PING is not liveness

PING is served on an IO thread and needs **no worker**, so it answers cheerfully through a total
data-plane wedge. A PING-based control called the server healthy across a ten-minute wedge. Poll
`total_commands_processed` instead — and subtract your own probes, or your polling makes the counter
advance and a stall is undetectable by construction (that was a real defect in my watcher).

Related and opposite: [[thredis-vacuous-validation-trap]] — M was the mirror image, trusting a
*client* timeout as evidence of a server fault when it was GIL starvation.

## How to catch a wedge on this box

`gdb -p` **cannot attach** — yama `ptrace_scope=1` and the server is a sibling, not a descendant;
raising it needs a sudo password. Use the server's own facility instead: `kill -ALRM <pid>`.
`debug.c`'s handler documents the explicitly-sent alarm and calls
`logStackTrace(..., current_thread=0)` → `writeStacktraces()`, which walks **every** thread into the
server log. Verified 11/11.

**Blocked vs spinning is the diagnosis.** Take 3+ samples: main sat at an identical PC every time
(`pthread_mutex_lock` ← `afterSleep`) while the IO thread's PC moved through
`freeClientsInAsyncFreeQueue` → `freeClientAsync` → `zmalloc`. One sample would have proved nothing.

## Reproducing it needs BOTH ingredients

Mass closes alone do **not** reproduce it: 40 rounds / 2560 connections killed mid-pipeline against
the known-bad binary, clean — because `beforeSleepIO` runs `handleWorkerReplies()` just before the
drain and `flushid` has normally caught up. Add continuous keyspace growth to force table rebuilds
(so workers are parked) and the known-bad binary wedges at round 4.
`tools/preflight/close_asap_livelock.sh` — pre-fix FAIL, fixed PASS with
`tomokv_close_deferred_ring=155602`.

## Harness defects found (7, all mine)

Calibration not exclusive; quiescence measured as a headcount (unreachable by construction); MEMORY
compared unmatched samples; a port guard that fired on other people's ports; the watcher's own INFO
polls hiding the stall; `gdb -p` failing silently and writing captures with no stacks; and the worst
one — the "INFO did not answer" branch `continue`d **past** the capture block, so a genuine
ten-minute wedge logged 18 lines and captured nothing.

## What the server keeps proving

numa1 phase, run 5: 1.59 B commands, `ratio=0.969` (floor 0.85), `handoff_missed` 0.028/M vs a 5/M
ceiling, `ex_queue_full=0`, and **all five ENGAGED gates open** — 4 flips, 75 bucket moves, 4 table
rebuilds, 282,113 connect/disconnect cycles, 268,338 scenario executions across 21 families.

Related: [[thredis-preflight-contract]], [[thredis-ab-harness-traps]], [[thredis-sanity-gate-benching]].
