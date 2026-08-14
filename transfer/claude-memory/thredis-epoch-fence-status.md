---
name: thredis-epoch-fence-status
description: "2026-07-25 stack on 2s-numa-qsbr-epoch-dev/stable-w2 — QSBR epoch VALIDATED, script-fence phase 1 fixes the EVAL crash, R1 pcmd freelist, embed192 +27% SET; plus the two pre-existing crashes found"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Commit stack (stable-w2, linear, each A/B-able vs parent): `382d2da1e` counters → `4f90a8a52` QSBR
epoch → `b5d2c684a` R1 pcmd freelist → `8201631d3` script fence phase 1.

**QSBR epoch (VALIDATED, free):** per-io-identity odd/even `flat_epoch` replaces the `in_flat` flag;
batches stamp `io_snap`+`io_pin_mask` at close behind a mandatory StoreLoad fence; ready = "same
identity still inside the SAME region". Workers byte-identical. Gates: 15/15 correctness, 10/10
numa=2, instr/op −0.59% SET / −0.08% GET (the mask walk beats 33 seq_cst loads). CONVOY (12 clients
looping DEBUG SLEEP 0.05 + churn): flag pending 598-640k, RSS 1.2-1.5GB at t=4s; epoch pending
301-11k, RSS 291MB — the unique win. STILL TRUE (spec §10.1): batches closed DURING one long region
stay pinned — `DEBUG SLEEP 6` under churn = RSS 181MB→5.9GB in 5s on BOTH builds; the OOM class
needs the follow-up mid-command quiescent point (`flatExternQuiesce`, DEBUG SLEEP's nanosleep first,
then the script yield, NEVER RM_Yield). Full spec in workflow wf_d11f4d5d-52b.

**Script fence phase 1 (`8201631d3`):** the EVAL crash (`server.c:5212 !scriptIsRunning()` assert →
SIGSEGV under any concurrent traffic; pure MULTI/EXEC was clean) is FIXED: `tomo_script_stw` gate
word ([63:16] epoch | [7:0] owner=iotid+1; **ARMED == owner byte ≠ 0**, testing the whole word
misreads post-release epochs — cost one debugging round), family serializes at a CAS (foreign →
-BUSY), release in the inline-branch epilogue after `call(fake)` (NOT the stateful branch — EVAL
never goes there; second debugging round), `scriptInterrupt`'s PEWB now main-owner-only. Validated:
20/20 crash-repro iterations, 31/31 acquire/release pairs, 10/10 sequential evals. Scripts remain
DECOY-BLIND for inner redis.call reads (pre-existing) — phase 2 = full spec wf_20da9328-f79 (park/
resume, worker drain fence, membarrier identity quiesce, single-key read repoint, foreign KILL).

**R1 pcmd freelist (`b5d2c684a`):** census wf_fee5b74c-544: GET=3, SET=5-6 alloc pairs/op; the
shared cmd_pool is asserted EMPTY whenever io threads are active, so every command paid
zmalloc+152B-memset (pcmd) + argv realloc (fresh argv_len=0 defeats the `multibulklen > argv_len`
gate). Per-io-thread freelist, argv kept attached. Functional gate 0 failures.

**embed192 (separate branch 2s-numa-embed2-dev):** kvobjSet embed 64→192 with the len≤255
SDS_TYPE_8 guard = p32 SET instr/op −13.4%, **ops +27.3% (6.93M — beats the 6M gate)**; GET +3.6%
instr (mechanism unclear; reply copy got CHEAPER, lookupKey rose — layout noise suspected). Values
≥45B arrive RAW so the outer `encoding==EMBSTR` gate keeps them 2-alloc — census rank 3 (RAW-embed
extension) generalizes it. Correctness-gated (boundary lengths 40-42/250-256, APPEND/SETRANGE,
digest, churn readback).

**Two pre-existing crashes found (tasks #37/#38):** (1) convoy segfault in
`updateClientMemUsageAndBucket`/`getClientMemoryUsage` (stock's "main pauses IO threads" invariant
absent; 0x28 = listLength(NULL reply)); (2) double-decref `object.c:608` Guru under SAVE/DIGEST
loops + flat churn (~5-8 min; attributed pre-epoch). Both repro'd on the PUSHED build.

**Trap ledger additions:** `enable-debug-command` defaults `no` — every DEBUG SLEEP "block" before
2026-07-25 was a 1ms error (void tests); `total_commands_processed` does NOT count worker-dispatched
commands (never use it as a traffic gauge — use exThreads[w].ops_total); `pkill/pgrep -f <pattern>`
self-match hit a 5th time; INFO counters sampled in TWO calls skew at 180k events/s (single call).
See [[thredis-ab-harness-traps]], [[thredis-qsbr-grace-pinning]], [[thredis-flat-alloc-anatomy]].

**UPDATE (post-review push, 52c760720):** full stack now on origin/2s-numa-shared-kv-dev:
`c996e0e23` SCRIPTFAM stamp-bit (kills the per-op compare chain) → `57d9740bc` embed192 (+29% p32
SET = 7.05M, GET 7.99M; covers ≤44B values only — RAW-embed is census rank 3) → `ea539f9ff` codex
adoption (7 verified fixes: _Atomic flat pointer, exQueuePopOrdered ring-wrap mask, pipelined set-op
>64-keys/shard truncation, retired-tables growth replacing the overflow UAF, pool-counter cache-line
padding, SetAtLink tombstone slot-reuse, loop_seq xadd→store) → `52c760720` fence fixes for ALL 15
CONFIRMED review findings (invocation-scoped cleanup-guard release — nesting-safe + covers every
reject path; family gate hoisted BEFORE getCommandFlags — lctx rehash race; foreign-safe
scriptIsRunning — returns 0 when foreign-armed, never derefs curr_run_ctx; epoch-tagged
tomo_script_kill word — foreign SCRIPT KILL works again incl. io-thread owners which never enter
timedout mode; pool-shrink raw-free). Ship gate: fixes cost +0.84%/+0.41% instr — inside budget.
Gauntlet all green (38/38, 15/15, 10/10, 200/200 EVALs under load). First stress campaign VOID
(codex session ran concurrently — his pkill SIGTERM killed two cells; also my harness misread
memtier's KB/sec column as errors); clean re-run chained → competitive sweep auto-chains if 12/12
pass. Sweep boots tomo with --tomokv-mcmd-lock yes (old-run comparability; default is off — user
question pending). Fence phase 2 (park/resume, worker drain, membarrier quiesce, decoy read
repoint) remains spec'd in wf_20da9328-f79.
