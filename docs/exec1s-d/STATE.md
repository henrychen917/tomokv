exec1s-d continuation state (2026-10-29)

- Merge completed at 670dc9f19 (parents headline 393d6ceb1 and exec1s-c 0dcc10f9b); headline trackfix retained.
- Production reuse tail lookup, lazy per-EXEC allocation, and X3 hint hoist committed.
- Corrected REUSE arm now truly patches PRE: normal depth 0/16/64 = 16702/26924/57068 vs PRE 16686/29212/66460. Earlier no-op arm receipts moved to invalid-reuse-arm.
- Complete allocation scope meets design 3348/13514 = .2477 at 1s/64. Idle X3 still +7 vs X12 in both namespaces; needs explicit explanation (two load/test/branch sites plus compiler spill).
- Final ordinary MSET repair: function-local align-jumps=1,align-loops=1 in normal namespace. Compile-only trial: MSET32 950534 vs PRE951302, MGET unchanged. Full final counts must be regenerated/bound to final binary.
- Core gate attempt3 passed36/0, including all exec1s, multifix, at412-owner, woundfix, execindex. Previous crashes resolved by fixture allocator migrations.
- Families attempt1 interrupted by service stop; attempt2 deliberately cancelled before final MSET padding repair (receipt130). Must rerun final families, supplement, differ both engines.
- gates_test attempts1/2: 45-second scheduler fixture timeouts while builds/live jobs shared CPUs. Run it alone after all expensive work before deciding whether code needs repair; do NOT widen its watchdog.
- Original seed22 epoll split0 full plan passes MERGE and C-PRE, observed15 successful snapshot starts each. Native unchanged psfix22 repeated tests running in session11444 (20000/20001); must inspect. SAVE refusal unresolved unless actual same failure captured. Earlier gdb line-breakpoint focused repeats timed out, not original Busy failure.
- All frozen arms present PRE, C-PRE, MERGE, X12, X3, X5, REUSE, POST; POST is being rebuilt after final annotation. PAD pair for prior POST built successfully; must regenerate final PAD (recreate PRE-source via snapshot and make all, no need redoing PRE counts).
- Lottery copied-source binary built successfully. No lottery job exists in tests/gate.sh; its nightly runner restricts CPUs112-127/ports253xx. Run equivalent bounded gate jobs with lottery candidate or document absent interface, preserve build receipt. Other copy-build jobs in families.
- CPU64-95 only; correctness gate slots64-87/server and88-95/client; ports20010-20097, nativeSAVE20000/1, gates_test20098, idlefixture20099. Builds-j32. No performance workloads.
- Need final freshness all + literal production_unit targets; receipt aggregation; DQ/DF (+4/+4 vs headline, no EXPECT edits); MEASURE-REQUEST-exec1s-d.md section exec1s-d; small commits, no push, clean tree. Keep build<30G; delete completed copies/objects and step traces only after hashes.
