O5 is implemented as one retained receive batch in the split IO rotation. Release PRE/POST and both sanitizer regression binaries built successfully without compiler diagnostics. Final source commit: 16398f9b78bc090331d9d12354fcadc9264c4b78. Runtime correctness, amortization and performance are UNMEASURED. See MEASURE-REQUEST for the exact cells, controls and acceptance numbers.

The IO thread selects receive batch N+1 after its ordinary writeback submit/reap and retains that selection until the next call. It parses that batch while owners can execute already-published N and older ordered replies are written back. The retained state is at most 64 Client handles in the existing 520-byte buffer. Parsed Ops, owner samples, reservations, read cuts and foreign pointers do not cross this boundary. This is a schedule within the existing 2s runtime, not an additional thread mode. The 1s rotation is unchanged by O5.

The existing batch lifetime pointer now names either fused writeback or split receive, whose rotations cannot coexist. This avoids adding scans to overlap=0's lifetime checks. Placement transitions consume staging without refill; the idle sweep consumes old nominations before counting fresh active clients; shutdown clears the view before final corpse grace. A hard output-limit close may remove a handle from the shared view, so the receive loop accepts that null entry. The normal parser, read-local completion/QSBR cut, notification boundary and ROB reply order remain in their existing stages.

Regression additions exercise retained handles beyond corpse grace, migration refusal while held, cold priming, actual cross-call state, both depth-order choices, dispatch conservation, no invented progress, key/client LB and FLIP drains, the idle sweep with a wholly stale active census, routing after a drained shard changes owner, and removal of a receive handle by the output-limit lifetime view. The existing lifetime gate row carries them; EXPECT_QUICK=419 and EXPECT_FULL=436 are unchanged (row line 1231 precedes quick exit line 2742). The NOSTAGE binary must fail the retained-input assertion; it has only been built, not run.

There are no development knobs to collapse. PRE/POST isolate the single receive-staging mechanism, and the private NOSTAGE source mutation checks the detector. No mechanism is represented as measured profitable. Its incremental heap/member footprint is 0 bytes; its armed retained working set is the pre-existing 520 bytes per IO. The pointer writes, branches and nullable-client check need a dynamic instruction count. The numeric IPC threshold, depth/load break-even and cycles/op payoff are pending. Compile-only symbol sizing confirms PRE=POST for all eight layout locks, IoLoop=8384 and IfidBatch=520 bytes (build/o5-layout.json). The release size(1) text total grows by 7392 bytes; data and BSS are unchanged. That code-footprint cost is not a dynamic instructions/op count. No data-layout PAD is applicable; code placement must still be controlled before any sub-1% win claim.

The disk-full autosave was recovered first. A second shared Git-store replacement during this turn then removed the old commit objects; the maintainer reattached the source as a2891c2a9 and recorded the recovered lane as 960c276cf. Commits 611750313 and 16398f9b7 refine the lifetime view and its close regression. build/o5-recovery.patch preserves the two-file lane change against the saved PRE snapshot. The recovered branch also contains the pre-existing gate reference record from 87b88cc4e; that is not an O5 mechanism. Reports and crash transcripts remain untracked.

The prediction is a cycles/op benefit at armed split p8–p32 if earlier receive selection improves stage utilization enough to pay for its batch bookkeeping. A full local-read hit path may have little owner work to overlap. If the target does not improve cycles/op, or a required GET/SET/MGET/MSET guard regresses, this candidate has not won. No loser attribution or performance claim can be made before measurement.

Every table value below is pending; entries are command rates and per-command counters. Supplemental break-even/deep tables use the same columns when those cells are run.

| Cell | Mode / workload / depth / connections | rl / ov / ro | PRE rate | POST rate | PRE IPC | POST IPC | PRE instr/op | POST instr/op | PRE cycles/op | POST cycles/op |
|---|---|---|---|---|---|---|---|---|---|---|
| h01 | 1s GET p32 c512 | 0 / 0 / 0 | pending | pending | pending | pending | pending | pending | pending | pending |
| h07 | 1s GET p32 c512 | 0 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| h11 | 1s GET p32 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| h12 | 1s SET p32 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| h15 | 1s GET p32 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| h16 | 1s SET p32 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| h17 | 2s GET p32 c512 | 0 / 0 / 0 | pending | pending | pending | pending | pending | pending | pending | pending |
| h23 | 2s GET p32 c512 | 0 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| h27 | 2s GET p32 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| h28 | 2s SET p32 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| h31 | 2s GET p32 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| h32 | 2s SET p32 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| h43 | 1s GET p1 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| h44 | 1s SET p1 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| h47 | 1s GET p1 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| h48 | 1s SET p1 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| h59 | 2s GET p1 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| h60 | 2s SET p1 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| h63 | 2s GET p1 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| h64 | 2s SET p1 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| m31 | 1s MGET p1 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| m33 | 1s MGET p32 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| m34 | 1s MSET p1 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| m36 | 1s MSET p32 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| m43 | 1s MGET p1 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| m45 | 1s MGET p32 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| m46 | 1s MSET p1 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| m47 | 1s MSET p8 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| m48 | 1s MSET p32 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| m79 | 2s MGET p1 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| m81 | 2s MGET p32 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| m82 | 2s MSET p1 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| m84 | 2s MSET p32 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| m91 | 2s MGET p1 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| m92 | 2s MGET p8 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| m93 | 2s MGET p32 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| m94 | 2s MSET p1 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| m96 | 2s MSET p32 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| c02 | 1s GET p32 c2048 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| c04 | 2s GET p32 c2048 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| t01 | 1s REORDER p8 c512 | 0 / 1 / 0 | pending | pending | pending | pending | pending | pending | pending | pending |
| t02 | 1s REORDER p8 c512 | 0 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| t03 | 2s REORDER p8 c512 | 0 / 1 / 0 | pending | pending | pending | pending | pending | pending | pending | pending |
| t04 | 2s REORDER p8 c512 | 0 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| t05 | 1s REORDER p8 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| t06 | 1s REORDER p8 c512 | 1 / 1 / 0 | pending | pending | pending | pending | pending | pending | pending | pending |
| o5_1s_get_p8_o0 | 1s GET p8 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| o5_1s_get_p8_o1 | 1s GET p8 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| o5_1s_set_p8_o0 | 1s SET p8 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| o5_1s_set_p8_o1 | 1s SET p8 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| o5_2s_get_p8_o0 | 2s GET p8 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| o5_2s_get_p8_o1 | 2s GET p8 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| o5_2s_set_p8_o0 | 2s SET p8 c512 | 1 / 0 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| o5_2s_set_p8_o1 | 2s SET p8 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |
| o5_2s_tail_r0 | 2s REORDER p8 c512 | 1 / 1 / 0 | pending | pending | pending | pending | pending | pending | pending | pending |
| o5_2s_tail_r1 | 2s REORDER p8 c512 | 1 / 1 / 1 | pending | pending | pending | pending | pending | pending | pending | pending |

NEEDS-BOX: maintainer correctness, directed negative control and the armed PRE/POST measurement request. No server, benchmark or gate was run by this lane.
