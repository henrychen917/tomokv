---
name: thredis-worker-argv-refcount-race
description: THredis crash root cause — worker/IO non-atomic refcount race on DB values; fix releases argv on the worker
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

THredis (`/home/henry/Projects/THredis-stable`) crashed under memtier connection churn (heap corruption / SIGSEGV / "smallbin double linked list corrupted"). **Confirmed via AddressSanitizer**: heap-use-after-free in `dbSetValue` (db.c:628 read, db.c:621 free), all on one worker thread.

**Root cause:** a non-atomic refcount data race on DB value objects. A write like SET leaves `argv[2]` aliasing the just-installed keyspace value at refcount 2 (one ref for the DB, one for the argv slot — see t_string.c `setGenericCommand` "1->2" incrRefCount). THredis dispatches the command to a worker (`fake->cmd->proc(fake)`, bypassing `call()`), but the command's argv was retired **on the IO-thread drain** (`handleWorkerReplies` → `commandProcessed` → `reclaimPendingCommand`). Meanwhile the same worker (same key → same shard → same worker) runs the NEXT command on that key, doing incr/decrRefCount inside `dbSetValue`. The IO-thread `decrRefCount(argv[2])` and the worker's RMW race on the non-atomic `refcount`; a lost update drops the live value to 0, the worker's own `decrRefCount` frees it in place, and the next overwrite reads freed memory.

**Fix (in scope, single-key cache only):** release argv references **on the worker thread**, immediately after `proc()` in `workerThreadMain` (server.c ~8483), mirroring inline `call()`/`freeClientArgv` which always frees argv on the execution thread. Loop over `fake->current_pending_cmd->argv`, `decrRefCount` + NULL each, before setting the reply-ready bit. This makes each worker the SOLE mutator of its shard's value refcounts. The IO-thread retirement then finds argv already NULL (existing NULL guards in `reclaimPendingCommand`/`freePendingCommand` handle it) and only splices the reply + frees the pcmd struct. Marked `//ee451`.

This is distinct from and stacked on top of the earlier [[thredis-iotid-worker-slot-fix]] (workers aliasing IO-thread-0's `current_client[0]`). Validated: full populate-with-overwrites + 40 connection-churn benchmark cycles under ASAN with 0 errors (pre-fix build crashed during the first populate).
