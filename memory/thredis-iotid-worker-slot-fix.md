---
name: thredis-iotid-worker-slot-fix
description: "THredis fix — worker threads ran with iotid=0, aliasing IO-thread-0's current_client slot"
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

THredis earlier crash class (pre-cursor to [[thredis-worker-argv-refcount-race]]): worker threads ran with the thread-local `iotid` left at its default 0. `ioThreadMain` sets `iotid = t->id`, but `workerThreadMain` never did — and workers call `fake->cmd->proc(fake)` directly, so every worker read/wrote `server.current_client[0]`/`executing_client[0]` (IO-thread-0's slot, a foreign client the main thread frees under churn) via `lookupKey`/`getKeySlot`/`dbSetValue`.

**Fix:** give workers a private `iotid = MY_IO_THREADS_MAX + 1 + worker->id` (server.c ~8424), resize `server.current_client`/`executing_client` to `MY_IO_THREADS_MAX + 1 + MY_WORKER_THREADS_MAX` (server.h), and publish the fake as that worker's `current_client[iotid]`/`executing_client[iotid]` around `proc()`. Workers now log `iotid=33..36` at startup. Confirmed present in the build. This fix alone was NOT sufficient — the refcount race in [[thredis-worker-argv-refcount-race]] persisted after it.
