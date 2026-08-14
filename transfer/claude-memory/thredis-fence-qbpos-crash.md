---
name: thredis-fence-qbpos-crash
description: "FIXED 2026-07-28 (fa9aca003) — the networking.c 'c->qb_pos == 0' assert was a real defect: processInputBuffer blanked the current_client slot, breaking nested-frame save/restore under processEventsWhileBlocked"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**FIXED** by `fa9aca003` (2026-07-28), which is in the pushed `2s-numa-stable-dev` HEAD. The earlier
"OPEN, reproduces on production" status in this file was recorded on 2026-07-25 against
`52c760720` and was stale for ~3 days — `git merge-base --is-ancestor` confirms `52c760720` is an
ancestor of the fix, so the memory described a genuinely pre-fix tree.

**Root cause (the assert was RIGHT, and is untouched).** `processCommandAndResetClient()` detects
"my client was freed underneath me" by testing `server.current_client[iotid].p` for NULL. Upstream
documents this as sound *only because nested frames put back what they found*. This fork's
`processInputBuffer()` — where stock Redis does not touch the slot at all — hard-wrote `= NULL`
after every command. Then:

`processEventsWhileBlocked` re-enters `processInputBuffer` **on the same thread**, so the nested
frame's trailing NULL is what the OUTER frame reads → false `C_ERR` → `readQueryFromClient` sets
`c = NULL` → the whole `done:` epilogue is skipped (**both** the querybuf trim *and*
`resetReusableQueryBuf`) → a live client keeps `qb_pos != 0` and holds the thread's reusable
buffer → the next read that leaves by an early `goto done` (EAGAIN, or `nread == 0` on close) trips
`serverAssert(c->qb_pos == 0)`.

Fix = save/restore the slot instead of blanking it (plus not restoring a freed client). That the
mechanism runs through `processEventsWhileBlocked` explains the observed regime exactly: slow script
on an io thread + concurrent traffic + SCRIPT KILL is precisely when that re-entry happens.

**Still worth knowing:**
- Historical rate was ~20-30% per fence-suite run (1/6 on production, 3/9 and 2/9 on two other
  arms — all within noise of each other, which is what proved it pre-existing rather than a
  regression from the wave/TASK#43 work).
- **A single green fence run is therefore luck, not evidence.** Ship gate #1 once reported
  "fence FAILs=0" and that green was sampling noise. Confirming this fix needs REPEATED runs; at the
  time of writing the fix is verified by mechanism and by the fence suite passing, but not yet by a
  high-repetition post-fix campaign. If the assert ever returns, do not assume this cause.
- One crash cascades into 3 suite failures (post-kill epoch clear, reject-path gate release, crash
  markers) — ONE defect, not three.
- Crash logs under `$JOB/crashlogs/`; `fs.log` is truncated by the next boot, so always copy it
  before the next run.

General lesson: a memory recording a bug as OPEN is a snapshot, not a live status. Re-check the
tree before acting on one — see [[thredis-vacuous-validation-trap]],
[[thredis-epoch-fence-status]], [[thredis-preflight-contract]].
