# txnorder implementation and proof status

This is a source/build handoff, not a runtime acceptance report. The maintainer
owns server runs, measurements, gate execution and merging. No server, load
generator, benchmark or gate was started by this lane. Serverless owner-turn
fixtures initialize storage and call the real handlers without worker threads
or listeners. Build and test commands are confined to CPUs 48–63.

The authoritative register is outside this worktree at
`/home/user/Projects/round4-read/REGISTER.md`; it was read but not edited.
These are proposed register status lines:

| Item | Source status | Remaining proof |
|---|---|---|
| TX4 / version-ordered EXEC | Implemented: retained version, placement wound/wait, executing immunity, writer/waiter marks, one-cut read-only EXEC | Runtime txniso/EXEC/Redis differential families and merit null |
| AT4.2 / AT4.3 / TO-B | Implemented with the existing watch_refs bit-31 sidecar lifetime; atomic-0 mover fix and MSETNX barrier witness retained | G1–G6, both modes and database counts; static cost audit and merit |
| F1, F4, F6 | Directed serverless PRE failures and POST passes recorded | Live directed companions |
| F2 | Reproduced before APPLY-yield change; serverless POST passes | Live script/APPLY and full script batteries |
| F5, F8 | Loader wait and WATCH candidate/started-claim checks implemented; directed fixtures added | PRE/POST receipts and live companions |
| F7 | First-attempt age uses now_ns; retries retain the original tuple | Storm/starvation receipts |
| F3 | Unchanged, separate aoforder lane | Blind-group AOF-order fix |
| Expiry / eviction | OPEN design §6 decision: maintenance does not consult read claims | Owner decision and a separate proof of maintenance stability |
| Read-only snapshot wording | Existing MGET cut implemented; general snapshot against unversioned plain writes is not established | Owner decision if the stronger contract is intended |

The four new rows use four executor owners for the section 9.1 stress. Their
split boot uses 4 io + 4 ex on eight cores; existing batteries keep the standard
6 io + 2 ex geometry. Fused rows arm read-local, with databases=16 for atomic=1.
The geometry question was sent to the owner; this follows the design's stated
four-owner stress requirement pending a contrary instruction.

No ex_loop.h, io_loop.h, AOF staging order, EXPECT_QUICK or EXPECT_FULL edits
are part of this change. Configuration documentation records the D1 writer
stall and D3 blind-crossing residual. Notification/tracking retirement order is
unchanged. The exclusive machinery and its DEBUG/counter surface are removed.

Runtime proof cannot be inferred from static identity or these owner-turn
fixtures. Each new row still needs an actual failing PRE receipt and passing
POST receipt. Missing receipts are pending, not passes. The original EXEC
expected-old timing issue in the upstream register is not silently waived.
