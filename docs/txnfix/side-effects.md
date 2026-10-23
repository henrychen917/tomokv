# EXEC effects and replay classification

This is a source audit of `classify_multi_command`, `prepare_commands`,
`multi_engine_policy_refusal`, generated command metadata, and the command
registries. It describes the Stage A candidate, not a claim that the complete
requested proof has passed.

| ConfigRoute/Admin command | Execution and replay class |
|---|---|
| CONFIG GET | Owner-side Admin command; read-only, replayable. |
| CONFIG SET | All-shards child; exclusive from the first attempt. Live configuration changes are not rolled back. |
| CONFIG RESETSTAT / REWRITE | Owner-side Admin commands; exclusive from the first attempt. |
| CONFIG HELP / invalid subcommands | Conservatively exclusive from the first attempt; no handler effects need rollback. |
| DEBUG SLEEP | Deferred owner command; replayable. Each attempt has its own deadline. |
| DEBUG other than SLEEP | Exclusive from the first attempt, including the all-shards BORROWCOUNT child. RELOAD and LOADAOF are rejected in MULTI by the existing engine policy. |
| INFO | Read-only Admin or DatabaseInfo child; replayable. The child census registers wildcard read intents. |
| DBSIZE / DBSIZE NOW | Read-only Admin or DbsizeExact child; replayable. The owner census registers wildcard read intents. |
| SWAPDB | Exclusive from the first attempt. Its prepared database map publishes only with the successful transaction decision. |
| KEYS | Read-only child, replayable; wildcard protection. |
| OBJECT / MEMORY keyed forms | Owner read, replayable; exact read intent. |
| OBJECT / MEMORY keyless forms | IoLocal handler, executed only for the successful attempt at retirement. |
| PFDEBUG | Owner write to the transaction's private image; replayable. |
| BGSAVE / BGREWRITEAOF / LASTSAVE | IoLocal, successful retirement only. SAVE is rejected by the generated no_multi metadata. |
| CLIENT / PUBSUB / COMMAND / MONITOR | IoLocal, successful retirement only, subject to existing per-subcommand no_multi metadata. This audit does not change existing handler routing outside PUBLISH/SPUBLISH. |
| SCRIPT / FUNCTION | IoLocal, successful retirement only, subject to existing per-subcommand no_multi metadata. |
| SLOWLOG / LATENCY | IoLocal, successful retirement only; discarded attempts do not execute RESET. |
| FAILOVER / REPLICAOF / SLAVEOF / PFSELFTEST | IoLocal, successful retirement only, subject to existing generated no_multi metadata. |
| SHUTDOWN | Rejected by generated no_multi metadata. |
| FLIP | Rejected by generated no_multi metadata/registry policy. |
| FLUSHALL / FLUSHDB / ACL | Rejected by existing MULTI engine policy; there is no private whole-store replacement or ACL protocol. |

Other relevant effects:

| Effect | Candidate behavior |
|---|---|
| Keyspace notifications | Per-attempt batch; discarded when the attempt is destroyed. Successful retirement transfers the winning batch. |
| PUBLISH / SPUBLISH | The existing IoLocal handler is a routing stub, contrary to design section 3.9's assumption. The candidate submits one serialized publication chain after a successful decision and waits for its receiver counts before retiring EXEC. |
| AOF | New group per attempt; cancelled group aborts, only the winner commits. V4 checks reload on its own appendonly boot. |
| Blocking wake-ups | Suppressed during fragments; the successful finalizer marks participant waiters dirty and wakes their owners. |
| Random draws / SPOP | Replayable; only winning replies/images escape. V3 checks member conservation. |
| Expiry time | Re-stamped once per attempt; held constant within that attempt. |
| Keyspace hits/misses | May include discarded attempts, as approved by owner decision 6. |
| CLIENT TRACKING invalidations | Advisory; a discarded attempt may cause a conservative invalidation. |

The cancelled decision is visible to foreign readers immediately. A running
collection handler retains its owner-local private image until its fragment
finishes; otherwise a remote cancellation could redirect the handler's second
lookup to a committed predecessor and mutate it in place. The candidate uses a
per-shard abort latch for this purpose without changing the shared resolver.
