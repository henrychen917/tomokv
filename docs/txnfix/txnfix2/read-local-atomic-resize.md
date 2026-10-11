# Baseline armed-fused atomic growth abort

This remains an unfixed correctness failure in merged PRE `991d48f65`, the
Stage A cost checkpoint, and the cost-rejected Stage B POST. It is not a
deadline exception or evidence that the Stage B retry lane caused the crash.

The unchanged `tests/atomic_torn.py` reaches its derived-window burst, then
loses the armed-fused server with SIGABRT. PRE and Stage A each exit -6;
POST does so in the broad proof and two debugger runs. Exact server/client
argv and binary hashes are in [controls](final-atomic-controls/runs.json).
All runs use 16 shards, 16 databases, eight fused threads on CPUs 112-119,
read-local 1, clients on 121-127, and port 22601. Split passes the full battery.

POST's stack is `xshard_execute` (MSET) →
`atomic_prepare_capacity_read_local` → `rehash_step_read_local` → abort.
The [focused debugger receipt](final-atomic-resize-full-trace/post-gdb/gdb.log)
also records:

- `read_local_extended == true`;
- a non-null `retire_sink.defer_resize` callback;
- `resize_retirement` holding a null pointer;
- `cap_[0] == 128`, `cap_[1] == 0`, after withdrawing the old table.

`src/store/flatstore.h:3250` requires the retirement record before handing the
old table to the deferred resize callback. Ordinary growth prepares that
record at line 3213. The atomic growth path at
`src/store/flatstore_atomic.inc:916` allocates/publishes its new table without
calling `prepare_resize_retirement()`. This function's source is byte-identical
in PRE and POST: [source identity](final-atomic-controls/growth-source-identity.json).
The optimized debugger's shared abort location maps to an inlined source
line; the captured state identifies the missing retirement record.

An attempted reduction to `atomicwindow.held_burst` alone on a fresh server
passes and does not reach this failure: [reduction receipt](final-atomic-resize-trace/runs.json).
Keep the full battery's preceding table history when reproducing. No test
assertion or retirement guard was weakened, and no runtime repair for this
separate baseline defect is included in txnfix2.
