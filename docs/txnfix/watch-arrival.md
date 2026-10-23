# WATCH arrival ordering

The dedicated watchlive_gate.sh (six fresh boots per row) failed on the shutdown-repaired Stage A binary: split rows reported 3/6, 0/6, 1/6 WATCH wedges at 4/8/16 clients, plus 1/6 at atomic 0; fused reported 0/6, 1/6, 0/6, plus 1/6 at atomic 0. Both no-WATCH controls were 0/6. Receipts: watchlive-stage-a/.

A fresh PRE boot also wedged with four clients, atomic 1, databases 16, split 6:2 and 16 shards (pre/watchlive-failure/). Thus this liveness defect predates OCC. Parent-debugger captures are in watchlive-gdb-state2/: EXEC 14055 has 14 completed watch fragments and watch_pending=2; shards 6 and 8 have not arrived. Both executors have a foreign MSET in xshard_retries_, and the missing EXEC fragments are behind the blocked writer. This is an inbox-drain wait cycle, in addition to the W5/W2 risk documented in design section 3.12.

Design reconciliation: section 3.12 documents a remaining reservation/dispatch hazard, while S6 requires every EXEC to terminate and the proof requires watchlive_gate.sh. S6 governs. A watched EXEC now waits for all participant fragments to reach multi_execute_task (past the existing dispatch ordering checks) before placing any WATCH claim. A fragment increments the arrival count once, using an unused bit in its owner-local execution_noted byte. All subsequent validation, mutation and claim lifetime rules are unchanged. Neither loop header changes.

The deterministic txn_help unit parks a second participant before arrival: the first participant must not create a claim, so a writer remains free to run. After both arrive, both claims must block writers until the attempt decides. Removing the arrival guard makes the first assertion fail.

The first arrival-guard image passes all ten watchlive gate cells (60 fresh boots): both modes, three atomic-1 WATCH connection counts, one no-WATCH control, and the atomic-0 WATCH arm. Every armed cell records reservation contention. Receipts: watch-arrival-post/runs.json. The guard also covers exclusive attempts without WATCH; that final generalization and the deterministic unit are being rebuilt with the IO signal change.
