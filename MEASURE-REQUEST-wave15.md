# Wave 15 release candidate

## wave15 integration

Base: `ea48a6b2721a1d9e5964ab24a32e8b54df611bd5` (wave 14, 1090/1107 declared rows).
Branch: `cx-wave15`. All twelve lanes are included in the requested order; ST5.3 is included. No push. Work is in progress; this document is not a landing receipt.

Correctness and builds use CPUs 0–63, ports 20000–20099 and LC_ALL=C. Performance/load generators and full iteration remain maintainer work. Checked-in EXPECT_QUICK/EXPECT_FULL are never modified.

### Merge resolutions

- cfgfix: retain rootcore quarantine, bypassing it during cfgfix runtime AOF activation so the old manifest remains authoritative. Compose cfgfix retained companion sockets with wave14 FLUSH/FLIP refusal timing and counter checks. Keep both job inventories and Tcl promotions; retain wave14 D11 explanations.

- cfgfix2: combine all six job declarations with wave14 production companion jobs; ACL/config/INFO and shutdown source changes merge without textual conflict.

- eoffix: retain both new production units. Its producer progress hook does not appear in SnapshotManager wait loops; HANG-2 still needs a directed live check.
- netfix2: EOF timers and accept-backoff timers coexist as distinct kinds; process both cold branches before dereferencing a client. Keep both mode-equivalence guard controls. The guarded partial-only shared-CPU adapter accepts netfix2’s client subset; normal disjoint placement remains unchanged.

- flipfix7 and rlfix5: retain production fixes and both guarded harness interfaces.
- storefix5 ST5.3 + cfgfix2 SO5.1: construct the clock with nothrow allocation; count all staged nodes in a local byte total; publish the charge only after every install succeeds. A failed partial clock is destroyed without charging the store. Disable retains ST5.3’s deferred subtraction after grace. The serverless directed unit exercises all six allocation boundaries with and without readers, retains an old clock charge through grace, and checks that failed replacement frees exactly its uncharged allocations. Both namespace units pass; the first gate invocation exposed and corrected missing unit prerequisites. Conflicting xshard budgets are provisional until compile-only trials.

- cmdfix2, txnfix4, scriptfix4: retain every declared job and both Tcl adapter test inventories; production edits merge without conflict.
- atomfix6: retain dynamic IO-role discovery, both socket-retention approaches, and wave14’s exact refusal reasons, subsecond bounds, and counter reconciliation. Preserve every planner negative control. xshard budgets remain provisional.

### Pending work

semantic interaction audit and directed checks; generic error accounting; AOF liveness repairs and negative controls; exact row inventory; compile-only inlining trials and instruction census; required correctness jobs; frozen PRE/POST/PAD-A hashes and maintainer measurement request.

### Declared rows after the twelve merges

The lane deltas in merge order are +1,+6,0,0,+5,+4,+6,+2,+6,+5,+20,+20: **DQ=DF=+75**, hence **1165/1182** before integration rows. `docs/wave15/merge-row-inventory.json` derives both counts from collection lines; no lane row is lost. The fixture needed finite-wrapper support for flipfix7 and txnfix4 labels; EXPECT assignments remain 1046/1063.

`rootcompat-stringlimit` is a private selectable diagnostic, not a public collected row: the `rootcompat` aggregate selects only proc/password/replication/sort-acl/redact/xsnotify/tracking/hscan/setpast. Its documented 32-bit clamp assertion is left intact.

Source correction to item 3a: headline `105c5818cc` exposes the INFO fields using only its NOGROUP counter; it has no `src/net/errorstats.h`. The later rootcompat generic implementation was removed by `676ef25963`. Wave15 will supply generic Redis accounting, including nested Lua error de-duplication, while preserving the NOGROUP reply fix.

### Integration AOF repairs

HANG-1: live PRE EXEC hangs for separate real-key/direction-word shards in both modes at atomic 0/1, including an owning-IO fused control. Sibling ZUNIONSTORE and GEORADIUS also hang. Only actual EXEC task shards now enter the initial and rebuilt AOF participant lists; empty lists create no group. Registry key classification stays unchanged, as requested.

HANG-2: the merged twelve-lane binary still hangs on the deterministic 32 MiB/1 MiB rewrite trigger in both modes at atomic 0/1; disabling auto-rewrite passes, and fused writer-owner controls pass. Every snapshot-start wait and atomic-group drain now uses eoffix's existing writer-only AOF drain. No new mechanism, protocol or architecture is introduced. GDB attachment was denied by ptrace; those failed attachment receipts are not claimed as stack evidence.

Two directed rows are collected before the quick exit, bringing the current declaration to **1167/1184**. Full POST oracle/restart matrices are running through the gate job interface. Initial probe harness defects (Conn context manager, an extra close, reading a persistence counter from INFO stats) are corrected and the defective receipts are retained as such; replay loss checks continue past PRE shutdown failure.

Corrected cfgfix2 PRE gate jobs both fail on `/home/user/Projects/bins/cfgfix2-pre-81aa6c32`; receipts are in `docs/wave15/jobs/cfgfix2-corrected-pre*`. Merged POST auth and shutdown reruns pass all declared legs in `integration-directed-1` (binary SHA `8ef611bf980cd5f9afeb8909c45fb41fa0ed5b766e266c6105f80cfb8a604741`).

### Generic error accounting

Fixed-capacity, mutex-protected cold error builders count total and prefix, with Redis's 32-wire-byte prefix search, 128-prefix disable limit, INFO escaping and RESETSTAT re-enable. Successful reply builders never enter the counter. Lua nested command/admission errors carry Redis's `ignore_error_stats_update` certificate through caught/returned/raised error tables. Direct pre-client admission writes remain outside afterErrorReply accounting, as in Redis networking.c. The new oracle row covers ordinary errors, MULTI queue/EXEC errors, caught Lua failures, EVAL/EVALSHA, arbitrary prefixes, cap and reset in both modes, engines, namespaces and atomic settings. The first complete corrected oracle matrix passes. Source instruction/cost proof remains pending.

The errorstats row is before the quick exit: current counts **1168/1185** (+75 lane rows, +3 integration rows over wave14). No EXPECT edits.

### Additional AOF witness findings

The expanded EXEC/restart matrix found stale argv indexes after blocking-pop normalization: BLMPOP emitted a postimage for the direction word under the real key's shard and restart rejected it. The normalizer now updates only key positions, preserving the classified shards. Read-only GEORADIUS/GEORADIUSBYMEMBER (without the `_RO` spelling) previously reached a STORE-only reducer and returned an internal error after the participant hang was removed. Their no-STORE form now selects its one real key before classification. This narrow key-classification correction is required for the demonstrated wrong reply; LMPOP/ZMPOP and other generic range classification remain unchanged. The same integration row checks these paths and their durable effects.

The deterministic HANG-2 POST gate matrix passes. PRE appendfsync=no acknowledges the pop and loses it on restart, now reproduced and retained in `aof-participants-pre-final`. `_RO` GEO spellings pass PRE; writable-spelling GEO reads and STORE forms hang PRE. Fresh probe boots now require exclusive listener release after waitpid, accounting for delayed io_uring cancellation after SIGKILL without relaxing any result assertion.

### Listener interaction and completed AOF matrices

CONFIG's REUSEPORT replacements could join another process's listener group despite netfix2's exclusive boot check. The cold rebind path now inspects kernel listener ownership, excluding only its own descriptors, before preparing replacements. Failure retains both old listener and all multi-argument CONFIG values. The original candidate fails all eight TomoKV legs; Redis passes. The first fixed POST passes all eight legs; The expanded `rebind-v6` oracle matrix also passes dual-stack conflict and IPv6-only coexistence controls, plus same-port wildcard expansion against a foreign dual-stack listener. Own address/port transitions remain accepted.

`integration-directed-1` passes the corrected cfgfix2 auth/shutdown, mixed generic errorstats, all EXEC participant/restart siblings, and 32 MiB/1 MiB plus original 128 MiB AOF progress matrices. Defective initial harness attempts remain labelled in receipts, not counted as evidence. Runtime payloads are SHA-recorded before pruning; logs and JSON receipts remain.

Two further integration rows (idle accounting and runtime rebind exclusivity) are collected before the quick exit, for **1170/1187** currently: wave14 1090/1107 +75 lane rows +5 integration rows. EXPECT constants remain unchanged.

### Error accounting / tracking interaction

The expanded oracle found a duplicated error count for malformed XREAD under tracking: `tracking_register_read` parses a disposable Op before the real dispatch, and both error builders charged it. `ErrorStatsProbe` now suppresses only that metadata-only parse. It is thread-local, scoped, and consulted only inside the cold error recorder; successful reply builders still execute no accounting code. The oracle now also checks two NOGROUP wake errors and an uncharged surviving group. `errorstats-tracked-probe` is the failing pre-fix receipt.

### Half-close / FLIP liveness repair

A fresh 6:2/16-shard epoll probe reproduces a circular wait on the merged pre-integration-fix binary: FIN follows DEBUG SLEEP plus buffered INCRs; FLIP pauses admission and waits for the EOF timer; that timer waits for the paused suffix to execute. `flip-eof-pre2` proves the FIN/sleep window and times out waiting for FLIP. A precommit EOF now causes an explicit bounded refusal. If FIN arrives after commit on a retained IO, an execution-idle EOF timer may resume at Idle; executor barriers and borrow pins still veto that exemption. No timer or client state moves to another owner.

A new gate row combines live exact-reply and state-directed postcommit checks. The corrected live fixture fits the request inside the receive window, uses TCP_INFO FIN_WAIT2 to prove accepted FIN while the first sleep reply remains unavailable, and rerolls an unopened window on at most sixteen fresh boots. It checks the unchanged one-second FLIP bound, exact refusal reasons, overall refusal counter, every INCR reply, EOF and the final value. The first full POST matrix passes 16/16; current declaration is **1171/1188** (+75 lane rows, +6 integration rows).

### Deleted-stream S1 reproduced and repaired

The required 200-repeat run on SHA `5c04a022c6f082098369ad23df829ecb56b39ee6dce862f57f5be03f7a0b19e2` reproduced `DEL boundary other-owner` delivering the recreated group's `1-0` entry: fused io_uring/read-local 0/db16 at iteration 112, split epoll/db1 at 100, and split epoll/db16 at 78. The other nine legs completed 200. This is a production wrong reply, not an accepted flake.

The atomic epoch can become visible before `blocking_atomic_published` sets the owner's dirty flag. The existing pre-command MVCC hook skipped its sweep in that gap, then CREATE replaced the group under deferred publication. `blocking_plain_mutation_published` now forces that existing slow-path sweep. No new field, protocol, reader retry, or ordinary command branch is added. The unchanged live row passes 200/200 on every one of the twelve affected mode/engine/read-local/namespace legs on the repaired interim image (`block-repeat-stream-post`). The deterministic serverless check freezes the epoch-visible/notification-absent state and requires the old waiter to finish with NOGROUP before CREATE. The corrected fixture fails on all four pre-fix mode/namespace arms and passes on all four post-fix arms (`docs/wave15/stream-gap/corrected.json`). Its initial fixture used an invalid synthetic decision owner; that fixture crash is retained and is not a production failure or accepted proof.

Seven integration rows now bring the required quick/full counts to **1172/1189**: two AOF, generic errorstats, idle-clock accounting, CONFIG listener exclusivity, EOF/FLIP, and the decided-stream publication boundary. All seven collection lines precede the quick exit; the fixture exactly matches the declared labels. The private survey harness and twelve private 200-repeat jobs add no public rows. EXPECT remains untouched.

### Compile-only budget work

The first round compiled 228 candidates across all 59 pinned units (150 distinct object bodies) and scored linked images against wave14, the headline, and all eleven production lanes' frozen PRE/POST arms. A second round re-derived headroom after the integration fixes and compared each candidate with the selected prior object. The db0 xshard unit required a wider follow-up: the narrow headroom scan outlined `Slice::key_eq` inside `FlatStore::find`; the accepted follow-up restores the prior exact lookup body. Final linked identity and command-scope counts are the remaining acceptance checks; none of these trials ran a server or measured a rate.

### Semantic interaction findings

- **SO5.1/ST5.3:** the enable path stages allocation bytes until publication, while old disabled clocks keep their charge until QSBR reclamation. The directed native matrix covers every allocation boundary with and without readers. A throwaway control charging an incomplete clock fails `failed clock never charged` in both namespaces (`idle-negative.json`).
- **EOF/activation/backoff/FLIP:** accept retry has its own null-client timer kind and stays behind activation. EOF remains an input-drain obligation. The discovered FLIP circular wait is fixed with an exact precommit refusal and postcommit retained-client drain; neither branch waives ROB, executor barriers or borrow pins. Native negative controls and the armed live 65-command FIN pipeline cover both boundaries.
- **TLS retention/borrow/idle clock:** `client_transfer_ready` rejects owner-local TLS state. A surviving IO retains its TLS connection, engine and idle clock; conversion refuses it. Both GET TLS registry variants select the copy-only template, including WATCH/notify selection. No transport-dependent branch is added to the plaintext GET handler. The relevant lane rows are netfix2 TLS/WATCH and idle, flipfix7 TLS/output, and the TLS lifetime units.
- **WATCH/tracking/wake/keyless cap:** atomic bare pops publish their WATCH effects at decision; EXEC children defer them to the parent. EXEC enrols actual children at execution and retires aborted attempts without retaining registrations. Script receipts narrow declared KEYS to observed reads. Woken XREAD uses its owner capture certificate; only an ordinary single-owner producer may seal early, while scatter/EXEC keeps the conservative certificate. The bounded completed-key registry evicts with an invalidation rather than silently dropping a key. Metadata-only tracked XREAD parsing exposed a real interaction with restored errorstats: its temporary parse errors are now suppressed, with an oracle check for exactly one real error and exact NOGROUP wake counts.
- **Collapse/index/pop/mover/FIFO:** the collapse guard checks all retained lower-ticket overlaps before discarding a prefix. The per-connection park index preserves equal-operation source/destination siblings, removes tasks from every index before execution or forwarding, and tests older operations only on the same connection with a key overlap. This retains executor FIFO admission and the mover's source-before-destination handoff. The live deleted-stream failure exposed a separate decision/notification gap; its fix and negative control are described above.
- **Channel ACL/registry rewrite:** MULTI's subscription/publish admission uses the live ACL permissions, including the EXEC-time recheck. CONFIG REWRITE holds the ACL registry mutex and serializes the current registry only when no external ACL file owns it. It neither reuses the boot ACL list nor changes queued command permission ownership. Rootcompat's permission publication and process-lifetime retired images remain intact.
- **Read-local ordering/transfer/park:** ordering bits remain in the original Client/ROB. Transfer requires protocol and executor quiescence; pending ROB entries, atomic groups, reply borrows and barriers prevent a connection from moving. A parked task is removed from its owner-local index before forwarding. No shard ownership, read retry or per-operation seqlock rule is relaxed.
- **Runtime listener/boot probe:** runtime CONFIG replacements now reject foreign reuseport listeners before staging the new IPv4/IPv6 listener set. Own listeners are excluded by inode; rollback preserves every earlier CONFIG value and listener. The oracle check covers occupied ports, wildcard expansion, dual-stack conflict, IPv6-only coexistence and successful own-listener transitions. This is the same preflight exclusivity contract as boot, not a lifetime reservation against a listener created after the probe.

The final native/public lane jobs are still running. These source findings are not a substitute for their receipts. The final wave14 FLUSH/FLIP companion contract remains unchanged: only its named refusal reasons, bounded response and exact refusal-counter deltas are accepted.

### Instruction census and current limits

`docs/wave15/instruction-comparison.csv` and `instructions.md` retain all 328 scopes against both wave14 PRE and the headline. The 48 ordinary GET/SET/INCR scopes add zero instructions in either comparison (GET -1 per operation; SET and INCR also decrease). MGET/MSET scopes also decrease. Plain TLS GET is identical in every scope. Error accounting adds 183 linked-image instructions for WRONGTYPE and 187 for invalid INCR against wave14; shared-library mutex/allocation bodies are excluded, so these are not end-to-end error costs or cycle claims.

Separate read-local GET scopes add 51–458 instructions against wave14; parser scopes range from -29 to +644. Those scopes include the new ordering fence and changed parser/constructor inlining and are **not** covered by the ordinary-command zero-added result. Uncontended EXEC adds 507–712 instructions per scope. Full per-function evidence is retained for attribution. LPUSH/RPUSH at batch 32 add up to 64,592 instructions: the dominant new body is cfgfix commit `8bd073aa20`'s `redis_listpack_bytes`, which scans existing compact elements to reproduce Redis's growth boundary. This is preserved lane behavior, not blocking-waiter overhead. No throughput conclusion follows from these counts.

The final compiled candidate is `build/wave15/POST-1babe0d58a-final`, SHA-256 `d36e1c43dd89691747ff5714d7dfe8dec32af88d85e0afc8fd9fe29c2e4c3b0a`. A premature earlier file copy is explicitly rejected in `post-freeze-1.json`; the accepted copy was taken after `make -q all` succeeded. Parser probe objects were compiled after every production object finished and bind to this accepted image (`parser-final-provenance.json`).

The first production-unit job exposed missing `tools/wave15_stream.mk` in historical minimal source copies used by AOF-order and Climon controls. The two new native recipes are now embedded directly in Makefile, so those copies stay self-contained. This is a harness-only correction; frozen production C++ and compiler settings are unchanged. All affected make/gate checks will be rerun.
