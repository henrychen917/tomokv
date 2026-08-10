FRONTEND/ICACHE LEVER (untried; measured motivation): on dev @2f80ef045,
get_p32 2M saturated shows FRONTEND STALLS = 21.4% of cycles (perf topdown),
while the hot path is spread across very large functions (exSlice,
readQueryFromClient, processInputBuffer, addReply*, call, lookupKey*,
flatFindForWrite) with error/slow paths inlined into them. The worker is
overhead-bound (~2.0M ops/s/worker in every config), so retiring more
instructions per cycle is a direct lever.
DELIVERABLE — minimal, mechanical, zero-behavior-change layout work:
1. Cold-split the hot path: __attribute__((cold, noinline)) on error/rare
   branches reachable from the per-command hot loop (protocol errors, OOM
   paths, DEBUG/assert bodies, log-and-abort arms, resize/migration slow arms,
   first-time init arms). Target the functions above plus the atomic slow arms
   (tomoVersionPruneAfterGrace stays as-is — it is cold already).
2. likely/unlikely (__builtin_expect) ONLY where the direction is structurally
   certain (flag-off fast paths, error checks) — no guesses on data-dependent
   branches.
3. Where a hot function contains a large rarely-run block that cannot be
   attribute-split (goto tails etc.), extract it to a static noinline helper.
4. NO semantic changes, NO new state, NO reordering of side effects. Every
   hunk must be provably behavior-identical by inspection.
5. Scope: src/server.c, src/networking.c, src/db.c, src/t_string.c,
   src/object.c. Stay OUT of: flatExternEnter/Exit, flatBatchReady,
   flatWorkerReclaim/flatReclaimAll, csStampDrain, tomoVersionPruneAfterGrace,
   and anything the notifyguard invariants cover.
The coordinator will measure with perf topdown (frontend-bound %) and the
8-cell quick-check; the deliverable is judged on measured frontend-stall
reduction at unchanged ops — commit granular so a regressing hunk can be
dropped alone.
