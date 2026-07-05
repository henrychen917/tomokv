All confirmed, server killed, benchmark port 6399 untouched.

---

# MULTI/EXEC silent data loss — investigation report (THredis-2s-improve)

## 1. Reproduction — CONFIRMED (port 6402, `--tomokv-io-threads 4 --tomokv-ex-threads 4`, existing `src/redis-server` binary)

- Interactive/pipelined: `MULTI` → +OK, `SET mk1 v1` → +QUEUED, `SET mk2 v2` → +QUEUED, `EXEC` → array of `OK OK` (client sees full success). `GET mk1` / `GET mk2` → **nil**.
- Via `--pipe` (as the applier ran it): `errors: 0, replies: 3`, then `GET pipek1` → **nil**.
- **Smoking gun:** `INFO keyspace` (reads the decoy `server.db`) grows by exactly one key per EXEC'd SET (`db0:keys=3` → `4`), while `DBSIZE` (shard-aware, sums worker dbs — db.c:2184-2199) stays at 1 (only the non-MULTI key). The "lost" keys are all sitting in the decoy.
- Control `--tomokv-ex-threads 0`: EXEC'd SET lands in `server.db` which IS the real db in that mode — `DBSIZE`=1, key present. No transaction loss with sharding off. (See side-finding B below: that mode has its own unrelated GET/SET wedge.)

## 2. Root cause (exact mechanism, verified)

EXEC executes its queued commands **inline on the IO thread against the empty decoy `server.db`**, while normal reads/writes dispatch to per-worker shard dbs. Two keyspaces; transactions live in the invisible one.

Chain, with file:lines:
1. Commands inside MULTI queue on the real client: `processCommand` gate at **src/server.c:5107-5124** → `queueMultiCommand(c, cmd_flags)` (benign — just stores argv in `c->mstate`).
2. `EXEC` is stamped `TOMO_R_STATEFUL` (**server.c:3808**, list at **server.c:9628-9648** includes `multiCommand/execCommand/discardCommand/watchCommand`), so it hits the stateful gate at **server.c:5126-5137**: waits for ring drain (`c->dispatchid == c->flushid`, else `CLIENT_PIPELINE_STALLED`) then runs `call(c, CMD_CALL_FULL)` **on the real client, on the IO thread**. Answer to Q3: yes — stateful commands stall-until-quiesced then run inline, and the db they run against is whatever `c->db` points to.
3. Inside `execCommand` (**src/multi.c:127**), each queued command runs via direct `call(c, CMD_CALL_FULL)` (**multi.c:225-227**) — command procs invoked directly, **never re-entering processCommand's classification**, so no `TOMO_R_EXPRESS` lane, no `canDispatchToWorker`/`exQueuePush`, no db repoint.
4. The real client's `c->db` is `&server.db[id]` (`selectDb`, **src/db.c:1206**) — the decoy that is empty by design (RP-1 comment, **server.c:3302-3308**: "real dataset lives in per-worker shard DBs... upstream machinery still operates on the empty decoy"). The ONLY places a command ever sees a shard db are the dispatch repoints `fake->db = &server.exThreads[ex_id].db[...]` (**server.c:5179** express, **:5201** whitelist path) — EXEC's inner `call()` bypasses both.
5. So EXEC's SETs write the decoy (client gets +OK), and subsequent GETs dispatch to shard dbs → nil. The RP-1 startup gate (**server.c:3309-3321**) rejects AOF/replicaof/maxmemory for exactly this decoy-blindness reason but does not cover MULTI/EXEC/WATCH.

## 3. Severity: CRITICAL — silent acknowledged data loss + broken CAS

- Every write inside any transaction is ACK'd then invisible forever. No error at any point. Violates the fork's own RP-1 "fail loud rather than corrupt silently" principle.
- **WATCH is silently broken too (verified live):** WATCH w1 → another connection SET w1 changed → EXEC **committed** (stock Redis must abort with nil-array). WATCH registers in the decoy's `watched_keys`; shard writes signal the shard db's `watched_keys` → never fires. Wrong concurrency decisions, worse than loss.
- Transactions read a parallel empty world (verified): inside EXEC, `GET t1` after an in-transaction SET returns tv1 (decoy self-consistency), but `GET out1` for a real shard-resident key returns nil.
- Unbounded decoy memory growth: EXEC'd writes accumulate in `server.db` where nothing reads or evicts them.
- Blast radius beyond explicit MULTI: client libraries that wrap pipelines as transactions by default (e.g. redis-py `pipeline(transaction=True)`) hit this invisibly.

## 4. Same-mechanism family + side findings

- **A. Inline-fallback commands share the decoy hole:** any command not whitelisted in `canDispatchToWorker` (**server.c:5256+**) and not cross-shard falls to the inline branch (**server.c:5209+**) where `fake->db = real->db` = decoy. Verified: `SET r1 rv1; RENAME r1 r2` → "ERR no such key" for an existing key (RENAME isn't whitelisted). At least that one errs visibly; non-whitelisted writes would vanish silently like EXEC's. Note: SETEX/expire-family and INCRBYFLOAT ARE whitelisted on this fork and work (the "intentionally excluded" comments at server.c:5279/5292 are stale — v5 expire fix was ported).
- **B. Separate bug, ex-threads 0 control:** with `--tomokv-io-threads 4 --tomokv-ex-threads 0`, plain GET/SET **wedge forever** (no reply; PING/ECHO/DBSIZE/INFO fine). `TOMO_R_EXPRESS` (stamped unconditionally, server.c:3809) makes the express lane (**server.c:5176-5182**) `exQueuePush` to `server.exThreads[...]` queues that no worker consumes when ex-threads=0. The io>0/ex=0 configuration is effectively unusable for GET/SET.

## 5. Fix options (DO NOT FIX YET — estimates only)

1. **Honest-unsupported gate (recommended near-term, ~1-2h):** in processCommand or in `multiCommand`/`watchCommand`, when `server.num_workers > 0` reject with `-ERR MULTI/EXEC/WATCH not supported with tomokv sharding (tomokv-ex-threads>0)`. Matches the existing RP-1 gate philosophy at server.c:3309. Zero correctness risk; converts silent loss into a loud client error. Optionally same gate for non-whitelisted write commands on the inline path (finding A).
2. **Single-shard EXEC dispatch (~1-2 days):** at EXEC time, extract keys from all queued commands (getKeysResult); if ALL map to one worker w, ship the whole transaction as one unit to worker w's queue (new "multi-envelope" fake carrying mstate; worker loops `call()` against its shard db; reply is the assembled nested array). Cross-shard transactions still rejected loudly. Preserves per-shard atomicity with no fences (single-writer shard invariant holds since the worker itself executes). Caveats: WATCH must register on the shard db (and only for keys on that shard); abort paths (DIRTY_EXEC/ACL) need handling on the worker; do NOT run it inline on the IO thread against the shard db — that races the owning worker.
3. **Per-command dispatch under a global fence (~2-4 days):** EXEC stalls until its ring is drained (already done), then fences ALL IO threads' dispatch and drains all worker queues (v8d migration drain-fence machinery is a precedent — `migHoldIfDraining`/`server.migration_active`), then executes queued commands one-by-one through the normal classification (each dispatched-and-awaited to its shard, or inline for decoy-safe ops), then releases. Full cross-shard atomicity; slow per EXEC, fine if transactions are rare. Needs a new synchronous dispatch-and-wait primitive on the IO thread plus shard-aware WATCH.

Recommendation: ship option 1 immediately (it also un-blocks trusting benchmark results — anything driving MULTI today gets fake numbers against the decoy), keep option 2 as the real feature if transaction support is ever needed.

Server on 6402 shut down; no redis-server processes left from this investigation. Logs at /tmp/claude-1000/-shared-Projects/192d33d7-f025-4e9c-82b2-54335e52614f/scratchpad/thredis6402*.log.
