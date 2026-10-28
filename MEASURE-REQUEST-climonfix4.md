## climonfix4

Base: `393d6ceb1`, branch `cx-climonfix4`. No push. Correctness work is confined to CPUs 16–31 and ports 20200–20299. No performance benchmark or full `gate.sh iteration` was run.

### Disposition

Seven assigned roots have complete fixes; PAUSE-BLOCKED-COUNT has local fixes but two remaining Tcl obligations need owner decisions. `PAUSE-CLIENT-EXEMPT` is stopped for the owner: the base explicitly documents the CLIENT/RESET/MONITOR exemption as a deliberate divergence, so this lane preserves that policy and its named Tcl failure. It also preserves replacement of ALL by WRITE. The original reproduction still differs from Redis in both modes.

| Root | PRE reproduction, 1s / 2s | Change and directed witness |
|---|---|---|
| PAUSE-BLOCKED-COUNT — partial | MATCH / MATCH | Base already counts postponed clients. Fix the remaining `flags=b` omission and release the count synchronously when a paused connection is killed. The directed row fails PRE on the missing flag. A planted removal of pause accounting makes the promoted Tcl assertion fail. Two named assertions remain excluded for the ordering/timer issues below. |
| PAUSE-CLIENT-EXEMPT | DIFFERENT / DIFFERENT | Deliberate restriction; owner decision required. No change or promoted assertion for this root. |
| PAUSE-MAY-REPLICATE | DIFFERENT / DIFFERENT | Hold PFCOUNT and PUBLISH/SPUBLISH under PAUSE WRITE; use the same classifier for EXEC children. Check both clients actually become blocked and return exact results after UNPAUSE. |
| PAUSE-SCRIPT-FLAGS | DIFFERENT / DIFFERENT | Parse Redis's Lua shebang, retain original source hashing and line numbers, enforce `no-writes`, and classify EVAL/EVALSHA/FCALL dynamically for PAUSE, including MULTI. |
| MONITOR-SCRIPT-CMDS | DIFFERENT / DIFFERENT | Carry nested records back through the existing notification retirement carrier. Preserve script/next-command and transaction-child order; buffer log records while work runs. Include no-call scripts, DISCARD and aborted EXEC. |
| RESET-CLEARS-LIBNAME | DIFFERENT / DIFFERENT | Retain library name/version across RESET; still clear the connection name. |
| RESET-MONITOR-ECHO | DIFFERENT / DIFFERENT | Exclude the RESET issuer from its monitor record, including forwarded events; preserve the record for other monitors. |
| CLIENT-LIST-CMD-NAME | DIFFERENT / DIFFERENT | Capture full child metadata in the existing cold container/local dispatch branch. Check INFO, LIST, SETNAME, CONFIG GET, ordinary PING fallback and ROB wrap. |
| CONNECTED-CLIENTS-LAG | DIFFERENT / DIFFERENT | Decrement live connections at close admission, separately from deferred reclamation. An idempotent existing-byte flag also protects self-KILL and shutdown cleanup. Check immediate INFO and maxclients admission. |

The exact original cases are replayed without modifying `docs/harness5/redis-tcl-repros.json`. PRE transcripts are in [pre-repro/results.json](docs/climonfix4/pre-repro/results.json); final and PAD receipts are under `docs/climonfix4/final-repro/` and `docs/climonfix4/pad-repro/`. The PAUSE-BLOCKED-COUNT exception above is explicit: its original counter-only reproduction cannot honestly be called red on this baseline.

The Tcl function-monitor assertion remains excluded for its separately classified `SCRIPT-UNDECLARED-KEY` restriction: upstream calls FCALL with zero declared keys and then writes `foo`. Declared-key FCALL monitoring was checked against the oracle. The assigned scripting-engine assertion is promoted.

Two formerly masked parts of PAUSE-BLOCKED-COUNT are stopped rather than weakening their assertions. `CLIENT UNBLOCK is not allow to unblock client blocked by CLIENT PAUSE` gets the correct zero while paused, but an immediate UNBLOCK after acknowledged UNPAUSE can still return zero in 2s: the target IO has not resumed its postponed BLPOP. Matching Redis requires coordinating UNPAUSE completion with resumed work across owners, beyond the counter/catalog correction. `Blocking timeout following PAUSE should honor the timeout` now reaches the correct blocked count of one; its second wait, for zero after UNPAUSE, expires while the ordinary one-second BLPOP is still counted. A diagnostic observed 1,029 ms elapsed and one real blocking key. PRE fails that same full-file assertion in both modes. [Timer receipts](docs/climonfix4/pause-open/timer-evidence.json) preserve the phase and PRE/POST failures. The [fresh-state UNPAUSE diagnostic](docs/climonfix4/open-pause-results.json) found 10/10 early acknowledgements on both PRE and POST in 2s, versus 0/10 on Redis and either 1s arm; every trial first proved both clients were postponed. The two original named exclusions are retained; no assertion, retry budget or timeout tolerance was relaxed.

### Implementation boundaries

The fixed layouts remain `Op=336`, `Client=1984`, `ThreadCtx=1408`, `Shard=1440`, `FlatStore=944`, `Rob<64>=192`, `AtomicEntry=144`, `Config=624`. Added data lives in existing cold ClientMeta, ClimonConn and NotifyBatch structures, except one unused connection flag bit. No reader retry, seqlock, in-place read-local overwrite or new execution wait was introduced.

Monitor records follow the ordinary ROB retirement carrier. Queued MULTI records are released in child order with their nested script records; discarded/aborted commands do not produce execution records. Pending records invalidate the existing per-batch feature cache with a private bit, so empty/error scripts also release subsequent records. The existing client-routing extraction/install transfers the whole ClimonConn in the ownership commit, and install restores pending refresh work. The unarmed parse/dispatch path has no new call.

### Gate accounting and negative controls

`job_climonfix4` has eight independently scored rows per mode/engine job. Each row runs fresh boots for databases 1/16, atomic 0/1 and read-local 0/1. That is 32 public rows and 256 directed configurations. A clean shutdown is required for each boot.

The four collection sites expand at `tests/gate.sh:5835`, before the quick exit at line 6118: **DQ=+32, DF=+32**. Relative to this branch's protected 881/898 counts, the owner should set **913/930**. Neither EXPECT constant nor the historical row fixture was changed. Promoting 15 upstream assertions changes the contents of the existing two Tcl rows, not their row count.

[tcl-promotions.json](docs/climonfix4/tcl-promotions.json) lists all 15 promotions. [tcl-control-results.json](docs/climonfix4/tcl-control-results.json) records one named witness per directed root, both modes, with POST and a negative arm. Seven negative arms use PRE; PAUSE-BLOCKED-COUNT uses a POST counter-removal mutant because PRE already includes the counter fix. The focused RESET control also enables its upstream SETINFO prerequisite. The connected-client control retains the normal introspection file's prologue after a narrowed run raced a bootstrap peer's FIN between INFO and KILL; both exact count assertions remain enabled. Timeout controls must reach the named assertion and fail its deadline; they cannot pass by omitting it.

`GATE_TCL_MANIFEST` is accepted only by the partial-job interface for these focused controls. The complete Tcl gate continues to require the full checked-in manifest. No upstream assertion body is modified.

### Validation

The final affected-job and differential campaigns are running. Their receipts will be appended here. The 92 instruction comparisons, final original reproductions, and all 16 paired Tcl controls are complete. Superseded runs are retained as diagnostic evidence and are not counted as final passes.

Required affected job selection:

```text
climonfix4-1s-uring climonfix4-1s-epoll climonfix4-2s-uring climonfix4-2s-epoll
redis_tcl climonfix clientfix scriptfix script_bounds lualibs
multifix-1s-uring multifix-1s-epoll multifix-2s-uring multifix-2s-epoll
notify notifycompat notify_order notify_aof tracking_redirect trackfix_order trackfix_accounting
netcmd_units racefix_climon dispatch_arity dispatch_errors dispatch_children
cmd_metadata release_batteries fused-0 fused-1
feature-split-0 feature-split-1 feature-armed-0 feature-armed-1 flip
```

The prerequisite `production_units` builds every target in that job; its readiness markers and independent `make -q` checks must all succeed. Differential runs select `differ-split` and `differ-armed`, which also include mode equivalence, with the standard seed allocator and no suite/seed overrides, separately for uring and epoll. Redis source/Tcl root is `/home/user/Projects/redis`; the differential oracle is `/home/user/Projects/redis74/src/redis-server` (Redis 7.4.10).

### Command-scope instruction proof

[instruction-counts.md](docs/climonfix4/instruction-counts.md) contains PRE/POST owner/scatter counts for GET/SET/INCR/MGET/MSET, both namespaces and modes, batches 1/32, atomic 1 plus MSET atomic 0, and read-local GET. Dispatch-only counts additionally exercise the production fused and split parsers for all five commands and both namespaces at batches 1/32. They complement the owner/scatter fixture's reply and data assertions.

These are finite serverless fixtures linked to production objects. Counts include executed instructions, including NOPs, in the selected production namespace; fixture glue and external libraries are excluded equally and clock_gettime is frozen. This is an instruction-scope result, not cycles/op, IPC, throughput or latency evidence. Raw step logs are removed after hashes and counts are recorded.

### Arms

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/climonfix4/tomokv-PRE` | `935c31459c919abf3ed74b78895ea36349b39129f22105620aa5189019f558ac` |
| POST | `build/climonfix4/tomokv-POST` | `3e5ab385e48e0189f8dada5af44e0d1792b403cbd50c85cb41e5e73332a488e8` |
| PAD-A | `build/climonfix4/pad-a/tomokv` | `9d5a27dfa78bc29844aeb1ce72cce2862459d02a9f7170352ce55f4751fd3dea` |

POST production source is commit `f86022ba4`; later commits record tests and evidence. PRE is the original `393d6ceb1` binary; source identities are recorded in [pre-source-identity.json](docs/climonfix4/pre-source-identity.json). POST is frozen in `build/climonfix4/tomokv-POST`. PAD-A is `build/climonfix4/pad-a/tomokv`.

**PAD-A means (A), behaviour twin:** PRE behaviour with inert candidate cold-structure layouts and POST's `.text` origin/total size. It does not reproduce every POST function offset or data-section address. [pad-a.json](docs/climonfix4/pad-a.json) records the exact construction, link-input hashes and text extents. The unchanged harness reproductions verify PRE behaviour. Source/object trees are removed after the final binaries, identities and counts are recorded.

### Maintainer merit request — NOT RUN here

Use the gate's own instrument on the quiet box, with PRE/PRE null, PRE/POST and PRE/PAD-A arms, matching offered loads and affinity. Run the 14 generic cells and four required split GET/SET p1/p32 null companions exactly as listed in [measure-cells.txt](docs/climonfix4/measure-cells.txt). Keep the instrument's defaults for key/value distribution, concurrency, atomic mode and read-local mode specified there.

Also request these affected cold-path comparisons in both thread modes, with each engine checked separately:

| Cell | Setup / workload | Record |
|---|---|---|
| Script flags | EVAL, cached EVALSHA and FCALL, plain and `no-writes`; standalone and inside EXEC; PAUSE off | Matched offered-load rate, cycles/op, instructions/op, IPC and reply latency |
| Monitor script delivery | One draining monitor; EVAL/FCALL with one and eight nested commands; standalone and two-script EXEC | Client-command rate, monitor records delivered, cycles/op, IPC and delivery latency; require correct record count/order |
| Client introspection | CLIENT INFO and CLIENT LIST ID/all, at 1/64/512 connections | Matched-load rate, cycles/op and latency |
| Close accounting | Connect/PING/close and CLIENT KILL churn, including self-KILL and a postponed client | Correct live/blocked counts, admission latency and cycles per completed close |
| Pause classification/release | Bounded PAUSE WRITE episodes with SET, PFCOUNT, PUBLISH, readonly EVAL/FCALL and mixed EXEC | Held-client count, exact release order/results, release latency and cycles per episode |
| Reset | CLIENT SETINFO; RESET; CLIENT INFO, and MONITOR; RESET; PING | Exact replies/identity/echo behavior; cycles per complete sequence |

PRE has different semantics in several cold cells. Do not score missing work, missing monitor records, or incorrectly unblocked commands as a performance win. The generic unarmed cells and split companions are null expectations. The verdict is rate at matched offered load, with cycles/op, instructions/op and IPC explaining it. A claimed effect needs POST to move while PAD-A stays flat, and repeatability beyond the identical-arm spread. No throughput claim is made by this lane.
