# Lane trackfix

## trackfix

Work in progress from `a7dfb9d2332d4c4e9d8bca983e439ba4b2bbba7e`.

Scope: DIFF-TRK-1 (delayed tracking invalidations) and CC4.4 (false notification
drop accounting). Correctness runs use CPUs 96–103 for TomoKV, 104 for the
Redis 7.4 oracle, 105–111 for clients, and ports 22800–22899. Builds use
`taskset -c 96-111 make -j16`. No performance measurements or push.

The bugs5 DIFF-TRK-1 report and tracing receipts were read, as were the full
CC4.4 entries in `round4-read/REGISTER.md` and `round4-read/cmd-complex.md`.

Pending design clarification: `Op::read_cut` exists only while atomic tracking
is active, and `NotifyRecordImpl::sequence` is local to its `NotifyBatch`.
Neither orders an atomic=0/read-local=0 read against a foreign notification.
Any new ordering metadata must remain confined to armed tracking operations.

Validation receipts and the final merit request will be recorded here.
