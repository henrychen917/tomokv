---
name: thredis-ex-expire-fix
description: How the SET..EX/SETEX/expire-family was made to work in THredis-opt-v5 (was crashing / out-of-scope)
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

THredis historically listed SET..EX/TTL as unsupported/crashing. Fixed in THredis-opt-v5
(2026-06). Two root causes, both from the sharded worker model:

1. CRASH (SETEX segfault): `createFakeClient` (networking.c) uses zmalloc and deliberately
   skipped `initClientMultiState`, so a fake's `c->mstate.executing_cmd` was GARBAGE. The
   SET..EX/SETEX propagation rewrite (setGenericCommand -> replaceClientCommandVector)
   branches on executing_cmd; a garbage >=0 took the MULTI path and tripped
   `serverAssert(executing_cmd < count)` -> abort. FIX: call initClientMultiState(c) in
   createFakeClient (scalars only: count=0, executing_cmd=-1; no alloc, no extra free).

2. WRONG DB (value/expire diverged): the expire-family commands were NOT in the
   `canDispatchToWorker` whitelist, so TTL/EXPIRE/PERSIST/SETEX ran INLINE on server.db[0]
   (main) while GET/SET ran on the worker shard db. => value in shard, expire in main:
   SET..EX gave GET=ok but TTL=-2; SETEX gave TTL=ok but GET=nil; EXPIRE returned 0.
   FIX: added the SINGLE-KEY expire family to the whitelist (ttl,pttl,expire,pexpire,
   expireat,pexpireat,expiretime,pexpiretime,persist,setex,psetex,getex,getdel) so they
   route to the key's shard. ALL single-key (single-shard) — NO cross-shard commands added
   (user constraint: cross-shard unsupported; multi-key MSET/MGET/multi-DEL stay off).

3. SAFETY: the AOF/repl propagation rewrite is a THredis non-goal and mutating a fake's argv
   desyncs it from current_pending_cmd->argv. Guarded the three rewrite fns
   (rewriteClientCommandVector / replaceClientCommandVector / rewriteClientCommandArgument)
   with `if (c->isFake) return;` (replaceClientCommandVector frees its caller-owned argv to
   avoid a leak). Covers SET..EX/SETEX/EXPIRE->PEXPIREAT/GETEX/GETDEL/incrbyfloat etc. at once.

Value-forwarding stays correct: readFwdCanReplay already disarms on volatile (TTL) values,
so forwarding never bypasses lazy expiry. Validated: functional (all expire cmds correct),
STRESS_TTL=1 invariant oracles 0-fail/0-ASAN, SETEX burst 1.72M ops/s 0-ASAN.
See [[thredis-v4-tunable-apparatus]].
