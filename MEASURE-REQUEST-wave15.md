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
- storefix5 ST5.3 + cfgfix2 SO5.1: construct the clock with nothrow allocation; count all staged nodes in a local byte total; publish the charge only after every install succeeds. A failed partial clock is destroyed without charging the store. Disable retains ST5.3’s deferred subtraction after grace. Directed allocation-failure accounting verification remains pending. Conflicting xshard budgets are provisional until compile-only trials.

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

Corrected cfgfix2 PRE gate jobs both fail on `/home/user/Projects/bins/cfgfix2-pre-81aa6c32`; receipts are in `docs/wave15/jobs/cfgfix2-corrected-pre*`. POST reruns remain pending.

### Generic error accounting

Fixed-capacity, mutex-protected cold error builders count total and prefix, with Redis's 32-wire-byte prefix search, 128-prefix disable limit, INFO escaping and RESETSTAT re-enable. Successful reply builders never enter the counter. Lua nested command/admission errors carry Redis's `ignore_error_stats_update` certificate through caught/returned/raised error tables. Direct pre-client admission writes remain outside afterErrorReply accounting, as in Redis networking.c. The new oracle row covers ordinary errors, MULTI queue/EXEC errors, caught Lua failures, EVAL/EVALSHA, arbitrary prefixes, cap and reset in both modes, engines, namespaces and atomic settings. The first complete corrected oracle matrix passes. Source instruction/cost proof remains pending.

The errorstats row is before the quick exit: current counts **1168/1185** (+75 lane rows, +3 integration rows over wave14). No EXPECT edits.

### Additional AOF witness findings

The expanded EXEC/restart matrix found stale argv indexes after blocking-pop normalization: BLMPOP emitted a postimage for the direction word under the real key's shard and restart rejected it. The normalizer now updates only key positions, preserving the classified shards. Read-only GEORADIUS/GEORADIUSBYMEMBER (without the `_RO` spelling) previously reached a STORE-only reducer and returned an internal error after the participant hang was removed. Their no-STORE form now selects its one real key before classification. This narrow key-classification correction is required for the demonstrated wrong reply; LMPOP/ZMPOP and other generic range classification remain unchanged. The same integration row checks these paths and their durable effects.

The deterministic HANG-2 POST gate matrix passes. PRE appendfsync=no acknowledges the pop and loses it on restart, now reproduced and retained in `aof-participants-pre-final`. `_RO` GEO spellings pass PRE; writable-spelling GEO reads and STORE forms hang PRE. Fresh probe boots now require exclusive listener release after waitpid, accounting for delayed io_uring cancellation after SIGKILL without relaxing any result assertion.
