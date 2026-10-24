# AT4.12 — escalation requires an owner design decision

Status: REPRODUCED; DESIGN ONLY, as directed when the named existing exclusive
path cannot carry scripts. Neither refusal is fixed. Existing txnorder/xscript
accept-and-count assertions remain because changing them to success assertions
would make the current implementation fail, not implement Redis behaviour.

## Reproduction

PRE is ef5204b2e. `reproduce.py` uses CPUs 48–55 for the eight server threads,
56–63 for drivers, ports 34810, shards 16, databases 16, uring, LB/auto-FLIP off;
split uses 6:2, fused read-local 1. DEBUG SHARDS proves two distinct owners.
EVAL and FCALL each run eight clients × 50 batches × pipeline 16 = 6,400 calls.
Acknowledged increments are accounted exactly on both keys. Results:

| Mode | Atomic | EVAL TRYAGAIN | FCALL TRYAGAIN |
|---|---:|---:|---:|
| 1s | 0 | 3754 | 3724 |
| 1s | 1 | 3748 | 3739 |
| 2s | 0 | 3830 | 3818 |
| 2s | 1 | 3830 | 3816 |

Redis 7.4.10: 6,400/6,400 successes for each command, zero refusals, exact data.
The authoritative numbers are `reproductions-pre.json` (and its complete log).
For the cut limit, 64 clients each submit one read-only two-owner EVAL with
SCRIPT-STAGE-DEFER=250000 us. Fused returns 32 BUSY/32 OK at both atomic values;
split returns 40 BUSY/24 OK at both values. See `script-window-pre.json`.
No throughput was measured.

## Why the requested fallback is unavailable at this base

`docs/txnorder/STATUS.md` explicitly records removal of the exclusive mechanism.
The live source agrees: `multi.inc::execute_watch_phase` places version-ordered
claims and changes Placing to Executing; there is no EXEC exclusive escalation
entry. `txn_group.inc::txn_group_prepare` explicitly excludes Kind::Script.
Scripts have their own PIN/READ/RUN/VALIDATE/UNPIN/APPLY state machine in
`scatter_engine.inc::xshard_complete_script`.

`Server::script_try_certification` is not an EXEC fallback. It serializes only
script certification; plain writers still run, and APPLY still validates each
owner. Holding it longer cannot prevent plain-writer conflicts. Retrying its
CAS indefinitely supplies no bounded fairness guarantee.

A failed APPLY may already have installed entries naming this ScatterState's
epoch/abort words and owner record counters. Clearing those words and rerunning
on the same arena could make cancelled candidates visible or invalidate live
reference counts. The existing group IO retry path assumes a TxnGroupAttempt
sidecar, version-ordered claims, placement arrivals and retirement on every
participant; simply removing the script exclusion does not establish them.

## Proposed integration for owner review (not implemented)

Use the current version-ordered claim protocol, rather than recreate the removed
exclusive controller. Before staging an escalated script, place write claims for
all unique declared physical keys, retain the original admission age across
retries, and join all owners before the newest committed read. This uses the
same writer episodes and wound/wait order as EXEC. Readers continue resolving
immutable predecessors through QSBR; only conflicting writers wait.

Escalation must release any live certification ticket and PINs in owner waves,
decide the old attempt, and retain that arena until records, snapshots and WATCH
references drain. A fresh attempt must keep the connection's existing barrier,
reply identity, ACL/function admission and AOF/notification ordering. The claim
set needs to cover the actual script/function key contract; an EXEC-lowered
child also needs the parent's ownership identity. It cannot acquire claims
behind a started foreign unit while retaining another resource that unit needs.

The four-cut limit needs IO-owned FIFO admission for waiting script connections
(or a demonstrated bound from an existing scheduler), with completion/retirement
continuing while parse admission is stopped. Keeping a refused command in the
connection input is necessary but by itself does not prove bounded fairness.

Before implementation: specify the resource order between claims, script cuts,
certification and queue slots; prove no cyclic waits against earlier same-
connection units or older writers; specify teardown and migrated-owner state.
Then direct tests must force >8 conflicts and >4 cuts, require both mechanisms
to fire, compare exact EVAL/FCALL replies/data to Redis, and forbid both refusal
texts while retaining zero-refusal counts in txnorder and both xscript loops.
Tests must include APPLY cancellation after a partial install, read-only scripts,
wrong-type/OOM cleanup, disconnect, AOF, both modes/engines and atomic 0/1.

No source change or gate row for this design: DQ=0, DF=0. This is an unresolved
compatibility item, not a claimed completion of cross-shard script escalation.
