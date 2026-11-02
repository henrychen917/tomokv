# Item 2: socket-output liveness

IoDrain retains the existing serve/lifetime pin until the weighted plan decides which clients move. Those clients stage late replies without starting a send on their source ring. Destination adoption releases that pin after installing ownership, catalog and WB slot. Remaining clients send normally. ClientInstall waits for execution, ROB, borrow and barrier state, not owned socket output. No executor mask, listener protocol or deadline changed.

The source active-set pointer is removed at final handoff as well as reversible detach: late fan-out can reinsert it between those points. A newly activated IO refreshes its cached clock before serving an inherited output-limit timestamp.

Release build and the serverless flipfix7 row pass. Fresh 6:2/16-shard live checks on both engines, db16/atomic0/read-local0, pass for late output, actual output transfer, and SIGTERM during FLIP. All 1,024 notification payloads survive each non-shutdown episode. Both shutdown episodes exit cleanly and reload 1,000/1,000 acknowledged keys. See item2-summary.json and the raw evidence archive. Broader proof is recorded in the final lane report.

The unconditional signal-save fallback is STOPPED under the frozen-protocol rule; see shutdown-stop.md. Passing the repaired output witness does not establish a universal post-commit shutdown bound.
