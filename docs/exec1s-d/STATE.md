exec1s-d continuation state (2026-10-29)

Production revised at cf3bdaa9e, POST SHA 4111f5c6ad1784fc6b95fceedc9efe361cf715dbad97f912e130811ab7544f18.
Prior POST22d failed the existing EXECABORT/WATCH directed row: queue-error EXEC skipped prepare_commands and lazy database_map stayed null. Production cold error path now captures the map when watched. All24 direct variants pass; original test unchanged.

Active sessions:
- 27282 regenerates all final POST scopes/counts/allocation/retirements.
- 4965 rebuilds PRE objects and final common-image PAD, then deletes PRE source and PAD objects.
- 63818 runs selected watch-fix gate (atomic_units+exec1s), then families, supplement, differ and harness. No full iteration.
- Old86621 stopped after family-attempt3 exit130 (candidate unchanged); old22d proof contains the one real EXECABORT failure. Preserve it; no longer final proof.
- Native original full plan passed235/0 on C-PRE, MERGE and old POST22d. The oldPOST session66083 then refused stale lottery build (make-q1), correctly. Need rebuild final lottery and run lottery phase, then controls phase for final POST-layout/PAD-A.

Report MEASURE-REQUEST-exec1s-d.md is drafted/tracked but must update final commit/hash/counts/table and PROOF_STATUS_PENDING.
After final counts, run tools/exec1sd_receipts.py. Re-run make-q freshness after production_units completes.
Old counts met ordinary48 max0/readlocal4 exact/alloc.247743; new counts pending. X3 idle budget previously+7 remains likelymiss; do not claim before finalcheck.
SAVE Busy historical failure remains unresolved. Native repeat6 timeout is a separate older-code failure, not Busy.
Disk near30G: retired large successful oldgate payloads/disassemblies with digests; retiring old exbatch/checks copies. Keep only final arm binaries, smalllogs/receipts; remove completed copies and steptraces.
CPU64-95 only, ports20000-20099, builds-j32. No rates/loadgenerators/fullgate. Commit small steps, no push, clean at finish.
