# Rootcore correctness and measurement handoff

## rootcore

Baseline: `7d2f8a2051961a1942735fb6dc9b507d778e09d1`. Branch: `cx-rootcore`.
Worktree: `/home/user/Projects/cx-rootcore`. No push. This report is being completed
as the remaining correctness jobs finish; no throughput result is claimed.

### Item 10 — STOP under the algorithm freeze

MISCONF-NEVER-CLEARS reproduced in all eight declared PRE legs: `1s`/`2s`,
`uring`/`epoll`, `appendfsync everysec`/`no`. Each leg observed one real failed AOF
write and a subsequent MISCONF reply. The test restored the process's file-size
limit and waited five seconds: none recovered. Redis 7.4 recovered in both policy
legs, accepted a later write, and recovered the write that originally encountered
the failure after restart. Witness: `docs/rootcore/pre/misconf-verified.log.gz`.
The job is `rootcore-misconf`, run through the ordinary gate job selector.

The present writer cannot safely implement a cron retry by clearing `failed_`:

- `AofManager::drain_producer` deletes a normal-engine failed chunk and retires
  its channel entry. `write_frame_normal` has already advanced the shard sequence
  and truncates to the last complete logical-record boundary, potentially before
  successfully written prefixes of a large value.
- `on_io_complete` destroys failed io_uring requests, their remaining iovecs and
  owned chunks. After outstanding requests drain it truncates to a safe boundary.
  A later successful write cannot reconstruct those discarded bytes.
- `fail()` clears `recording_`. `record_bytes`, `seal`, `resolve_groups` and the
  group-post loop may abandon serialization of an already installed value. A
  writer-only retry therefore does not cover records spanning multiple chunks.

Smallest proposed change: a recoverable-write-error state distinct from a fatal
format/allocation error; retain failed normal frames and io_uring requests with
exact remaining offsets; keep admitted owners' serialization/posting alive;
retry retained work on the existing writer's cron service; clear MISCONF only
once the retained writes succeed. The normal stream sequence must advance only
on success. Recovery must preserve the existing large-record token, GCMT
ordering, shutdown refusal and fsync receipt rules. New witnesses must force a
failure partway through a multi-chunk record and between grouped fragments and
GCMT, then verify replay after recovery on both engines and policies.

This adds an error-recovery state machine across producer serialization and
writer ownership. Per the task's explicit architecture/algorithm freeze, that
change is **STOPPED, not implemented**. The S1 refusal remains on POST. Clearing
the flag or retrying only later chunks would introduce acknowledged record loss.
The final proof will retain the failing POST row rather than relabel it a pass.
