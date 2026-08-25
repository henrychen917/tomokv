# Lua scripting: single-owner V1

## Scope and ownership

Owner law (verbatim): **"db shards need to only be touched by their ex threads."**

`EVAL` and `EVALSHA` parse `numkeys` on the connection's IO thread. Every declared `KEYS[]` entry
is hashed with the normal `FlatStore::hash_key` path and resolved through the server router. A
zero-key script is assigned to shard 0. A keyed script is accepted only when every declared key
maps to the same shard; otherwise it receives:

```
CROSSSLOT Keys in request don't hash to the same slot
```

This is deliberately an owner check, not Redis Cluster's 16,384-slot equality check. It is the V1
single-owner limitation. The accepted request becomes one ordinary task for that shard's current
EX owner. Lua execution and every nested command handler therefore run in that same task and on
that same EX thread. The interpreter never sends work to a second owner.

`redis.call` and `redis.pcall` accept only registry commands that are deterministic, non-blocking,
and have one fixed key position. `DEL`, `UNLINK`, `EXISTS`, and `TOUCH` are additionally admitted
only in their one-key form. Admin, connection-local, all-shard, cursor/random-route, scripting,
general multi-key, `SPOP`, and `SRANDMEMBER` calls are rejected. The command key must exactly match
one of the script's declared keys. Accepted calls invoke the existing `CommandSpec::handler`
directly, including the normal maxmemory admission gate and normal store write paths.

The outer operation is marked as owner-local multi-key work without growing `Op`. This lets the
existing MVCC pending-record checks, same-connection hazard checks, and snapshot write gate walk
the complete declared key list. `sizeof(Op)==336` and `sizeof(Client)==1984` remain unchanged.

## Lua dependency and sandbox

The machine inspection found runtime-only `liblua5.3-0` and `liblua5.4-0`, but no Lua development
headers and no Lua `pkg-config` package. A complete offline Lua 5.1.5 source tree was available in
the local Valkey checkout, so the required library core and safe standard-library sources are
vendored under `third_party/lua/`, together with the upstream MIT `LICENSE`.

`third_party/lua/lua_amalgamation.c` is the single textual build input. It contains the core,
auxiliary API, and base/table/string/math libraries. The package, filesystem, OS, IO, and debug
libraries are absent. The sandbox also removes dynamic loaders, output, coroutine creation,
bytecode dumping/loading, garbage-collector controls, and random-number APIs. Binary chunks are
rejected. Source is capped at 1 MiB. Every evaluation receives a fresh Lua state, so globals do not
leak between requests.

The build performs no network access.

## Replies, cache, and limits

Lua/RESP conversion follows Redis' RESP2 scripting shape:

- Lua strings become bulk strings; finite numbers become integer replies.
- `false` and `nil` become nil bulk replies; `true` becomes integer 1.
- Sequential Lua tables become arrays; `{ok=...}` and `{err=...}` become status/error replies.
- Nested command status/error replies become Lua `ok`/`err` tables, bulk nil becomes `false`, and
  arrays recurse with bounded depth and element count.

Scripts have a 100,000-instruction budget. A Lua count hook runs every 1,000 VM instructions and
aborts at the next hook after the budget. The reply uses `BUSY` semantics. V1 needs no cross-thread
kill or `SCRIPT KILL`: the owner itself reaches the hook and unwinds the protected Lua call.

The process-wide cache maps lowercase SHA1 to source and is protected by a mutex; no shard state is
behind that mutex. Successful `EVAL` compilation arms `EVALSHA`. `SCRIPT LOAD`, `SCRIPT EXISTS`,
and `SCRIPT FLUSH [SYNC|ASYNC]` operate on the same cache. SHA1 is implemented locally and checked
against `sha1sum`; no `std::hash` or placement hash is reused.

## Error and atomic behavior

With atomics off, a runtime error or instruction-limit abort preserves effects already performed by
earlier `redis.call`s. This matches Redis pre-7 scripting behavior and is intentionally documented
as partial-effect semantics.

With `--atomic 1`, the owner captures deep rollback images for the unique declared keys before Lua
runs. No other task can enter that owner while the script is executing. On a runtime error, result
conversion error, or instruction-limit abort, the owner removes the script versions and restores
the captured objects before publishing the error reply. A successful script drops the images.
Thus the whole single-owner task is all-or-nothing and externally indivisible. All nested effects
still go through their ordinary command handlers; the images are only the failure undo arm.
While the undo arm is live, maxmemory admission remains enabled but its eviction policy is
temporarily treated as `noeviction` on that owner. This prevents a failed script from evicting an
undeclared bystander that the declared-key undo log could not restore.

V1 intentionally does not offer cross-owner scripts, external `SCRIPT KILL`, replication/AOF
effects, Lua debugger/package facilities, or Redis Functions.

## Directed test

Against an already running server:

```
taskset -c 240-247 python3 tests/lua_scripting.py 127.0.0.1 7954
```

The battery covers status/integer/bulk/array/nil conversion, both cache-arm paths, flush/exists,
cross-owner rejection, instruction abort and liveness, nested error propagation, undeclared-key
rejection, atomics-off partial effects, and atomics-on rollback for both errors and killed scripts.
