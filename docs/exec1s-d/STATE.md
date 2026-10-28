exec1s-d continuation state (2026-10-29)

Production revised at cf3bdaa9e, POST SHA 4111f5c6ad1784fc6b95fceedc9efe361cf715dbad97f912e130811ab7544f18.
Prior POST22d failed the existing EXECABORT/WATCH directed row: queue-error EXEC skipped prepare_commands and lazy database_map stayed null. Production cold error path now captures the map when watched. All24 direct variants pass; original test unchanged.

Active sessions:
- Final POST counts/allocations/retirements completed. Ordinary48 maxdelta0; readlocal4 exact; allocation.247743; idle+7 both. Final PAD completed too.
- New PAD hashes: POST-layout9d99271b..., PAD-A1b1a7372...; all metadata in arms.json. PRE sources/objects retired.
- 63818: watch-fix passed32/0; families-attempt4 active at build/gate-run.q0JfME, then supplement/differ/harness sequentially. No full iteration. Current57/57 freshness passed on4111 hash.
- Old86621 stopped after family-attempt3 exit130 (candidate unchanged); old22d proof contains the one real EXECABORT failure. Preserve it; no longer final proof.
- Native original full plan passed235/0 on C-PRE, MERGE and old POST22d. The oldPOST session66083 then refused stale lottery build (make-q1), correctly. Final lottery rebuilt; lottery-copy-smoke, POST-layout-smoke and PAD-A-smoke each passed execfair (2rows including release).

Report MEASURE-REQUEST-exec1s-d.md is drafted/tracked but must update final commit/hash/counts/table and PROOF_STATUS_PENDING.
After final counts, run tools/exec1sd_receipts.py. Re-run make-q freshness after production_units completes.
Final counts preserve ordinary48 max0/readlocal4 exact/alloc.247743. X3 idle +7 is confirmed; budget remainsmiss.
SAVE Busy historical failure remains unresolved. Native repeat6 timeout is a separate older-code failure, not Busy.
Disk near30G: retired large successful oldgate payloads/disassemblies with digests; retiring old exbatch/checks copies. Keep only final arm binaries, smalllogs/receipts; remove completed copies and steptraces.
CPU64-95 only, ports20000-20099, builds-j32. No rates/loadgenerators/fullgate. Commit small steps, no push, clean at finish.

Latest diagnosis: final4111 redis_tcl has 1 real fused isolated slowlog failure. Five unnamed setup errors are expected manifest errors, not failures. Bounded unchanged Tcl replay: POST1s2/8fail; PRE1s5/64fail (plus initial8passes); both2s8passes. Exact assertion newest BLPOP versus SLOWLOG RESET. Pre-existing source commit-to-IO-retirement gap; leave row red, no manifest/retry/assertion changes. Receipts and tools committed. Final idle assembly regenerated both namespaces and bound to4111; benchtxn built/hash recorded, never executed.
