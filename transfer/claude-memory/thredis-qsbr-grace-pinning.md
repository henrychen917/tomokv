---
name: thredis-qsbr-grace-pinning
description: Top open FLATSTORE defect — any long inline command pins the QSBR grace for every worker (OOM class); plus the resize-quiesce starvation it causes
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Max-effort adversarial review (2026-07-25) of `4b3731f7a^..52cb11a0f` returned 15 distinct defects.
Four low-risk ones were fixed and pushed in `d1a411971`. These remain OPEN and are the highest
severity — all CONFIRMED unless noted:

1. **`FLAT_EXTERN_REGION()` wraps the whole of `call()`** (server.c:4707). Any long inline command on
   any io identity — `DEBUG SLEEP`, a Lua script, `KEYS *`, `SAVE` — holds `tm_io_sig[i].in_flat` for
   its entire duration, so `flatBatchReady` returns 0 for EVERY worker and nothing is reclaimed
   meanwhile. Same OOM class already hit once (233MB → 38GB in 180s, see
   [[thredis-flat-reclaim-capacity]]). **Proper fix: make `in_flat` an EPOCH, not a flag**, so a batch
   closed before a reader entered its region can still be freed. A flag cannot distinguish
   "entered before the retire" from "entered after".
2. **Resize quiesce requires every io identity's `in_flat` clear** (server.c:6327). Self-blocks the
   main-thread pump (main is inside `call()` when it pumps), and a long inline command starves the
   resize into a repeated arm/abort loop that PARKS EVERY WORKER 200ms at a time while the table keeps
   filling toward the full-table panic.
3. **`flatTableRetire` overflow fallback frees inline** (server.c:6212, PLAUSIBLE) — the exact unsafe
   free the RCU deferral exists to prevent, no reader check, no log, no counter.
4. **Flip-converted EX→IO poly thread parks its whole event loop** during a rebuild (server.c:14658):
   the park is keyed on worker identity but such a thread also owns a live io identity with clients.
5. **COPYING assumes an immutable old table** (server.c:6359, PLAUSIBLE) but io identities are
   deliberately never parked on `flat_resize_active`, so a non-worker can mutate it mid-copy.

Also open, needs measurement not a blind edit: **flip-controller gain band weakened**
(server.c:17488). Band is `max(2σ, 2% of best)` where σ is only WITHIN-window tick noise; the deleted
comment recorded between-window drift as 3-10× larger. The `null_abs` field that carried that term
still exists (server.c:17237) but **is never computed anywhere**, so restoring it to the band
multiplies by zero — the drift EWMA has to be re-established first. A 5-min stress run logged 51
front / 49 back flips (~one per 3s), consistent with a too-tight band accepting noise as gain.
See [[thredis-flip-controller-momentum]].

**UPDATE 2026-07-25 (after implementation):** defect 1 is FIXED by the epoch conversion (`4f90a8a52`,
see [[thredis-epoch-fence-status]]) for the CONVOY case; a single long region still pins batches
closed during it (sound; needs flatExternQuiesce follow-up). The earlier note "OOM consequence not
reachable" was WRONG — it was based on DEBUG SLEEP being silently rejected (enable-debug-command
defaults no) and total_commands_processed not counting dispatched commands. With the block real:
RSS 181MB→5.9GB in 5s. Defects 2-5 remain open as written.
