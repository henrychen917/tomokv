# AUDIT-CLEANUP — night lane t-night-cleanup (2026-09-03)

Base: mainline `775aeea48`. Scope: stability + code cleanliness, implementation level only, ZERO
performance risk. No server was booted, no memtier/perf ran; the only binaries executed were the
pinned release build (`taskset -c 48-55,176-183 make -j8`) and the server-less unit binaries
(`tests/config_parser_test.cc`, `tests/flipctl_unit.cc`). Hot-path functions (parse_and_dispatch,
resp_parse, command_lookup, exec_batch, read_local_*, flatstore probe/insert/prefetch, rob
acquire/retire, WB/send, SPSC, ex-sched) were read but not edited. Files owned by other lanes
tonight (command.h/commands.cc, io_loop.h, ex_loop.h, flatstore*.h/.inc, rob.h, read_local*.h,
thread.h, atomics_glue.inc, scatter_engine.inc, net/*) were not edited; every finding that lands in
one of them is LISTED (§5).

Baseline facts (pre-change, all measured on this tree):

| fact | value |
|---|---|
| `-Wall -Wextra` warnings, release build | **1** — `src/core/ex_loop.h:1066` unused variable `store` (other lane) |
| `tests/config_parser_test.cc` | compiles clean with `-Wall -Wextra`, passes |
| orphan TUs (no build recipe anywhere) | `tests/flipctl_unit.cc`, `tests/broaden_bench.cc`, `tools/benchtxn.cc` — all three still compile clean with `-Wall -Wextra` |
| layout locks | Op=336, Client=1984, Config=624, ThreadCtx=1408, Shard=1440, FlatStore=944, Rob<64>=192, AtomicEntry=144, Task=32, KvObj=8, CommandSpec=48, ExLoop=5848, AtomicPendingState=1352, StreamHeader=56 — all hold; none moved by this lane |
| parser knobs | 97 `--flags`; `--help` covers all (compact-encoding family via brace shorthand; `--genthread-schedule` deliberately hidden) |
| `tomokv.conf` coverage | every knob present EXCEPT the eight AOF knobs (D2) |
| `Config` fields with no reader outside config.h + the CONFIG table | none (`databases` is read only by the table, intentionally: config.h:318) |
| `Server`/`Shard` private DATA members referenced only at their declaration | none |
| preprocessor selectors | `TOMO_JEMALLOC`, `TOMO_XSCRIPT_NO_RESERVE`, `TOMO_STRING_NOTIFY_TU` (live); `TOMO_READ_LOCAL_SET_TAX_VARIANT` (study, stays); `TOMO_WEDGE_FORENSICS` (see X1); `NDEBUG` never defined by any target; no `#if 0/1` anywhere |
| `TODO`/`FIXME` in src/ | 1 (`kvobj.h:21`, scoped, actionable) |
| ODR | none — every `.inc` lands in one TU (pubsub.inc/climon.inc are class-body fragments, implicitly inline); every header has `#pragma once` |
| strict aliasing / punning | none — every reinterpretation is `memcpy`; the one raw `__atomic_load_n` through `reinterpret_cast` (kvobj.h:783/804) is preceded by `std::construct_at` (kvobj.h:1166-1196) and is legal |

---

## 1. RANKED FINDINGS

Severity: **S** stability/correctness · **D** docs/comments contradicting code · **C** duplicated code ·
**X** dead code / dead selectors · **H** header/include hygiene · **B** build/tools/tests ·
**F** feature-file structure. Disposition: **FIXED** (commit in §2) or **LISTED** (§5: other lane's
file, owner decision, or needs a battery this lane may not run).

### 1a. Stability / correctness

| # | file:line | finding | disposition |
|---|---|---|---|
| S1 | `src/core/genthread.cc:208-224` vs `:275-279` | **Fused boot hang.** A worker that observes `stop_flag` at the serve gate (`:214`) returns WITHOUT incrementing `runners_ready`; main waits at `:277` for `runners_ready == nthreads` with no stop term in the predicate → SIGTERM/SIGINT that lands after a thread finished loading but before the gate opens (any long `--load`/AOF replay with uneven shard sizes, or the µs window between the last loader and `serve_start`) parks main forever. `on_signal` never notifies `boot_cv`, so main itself opens the trap at `:272`. Split mode has no such handshake. | FIXED — stopped threads report at the gate; main's predicate counts them (C2) |
| S2 | `src/main.cc:180-182` vs `:258,:288`; `:38-43` | `on_signal` iterates `g_threads` (a `std::vector`) but the handlers are installed BEFORE the vector is populated (`push_back` at :258/:288) — a signal inside a reallocation reads a torn vector from a handler (UB); the handler is never disarmed, so a signal during `~Server` (after `:638`) dereferences a destroyed `Server`. Also: a SIGINT during `Server::init`/ACL init/table allocation is silently swallowed (flags exist, threads don't) — the operator must Ctrl-C twice. | FIXED — fixed-capacity array + lock-free atomic count, handlers installed after population, disarmed before teardown (C3) |
| S3 | `src/main.cc:428-429` | Io-thread lambda: `if (!exs[tid].init(...)) return;` / `if (!ios[tid].init(...)) return;` — no message, no stop flag. That thread vanishes, every other thread keeps serving, and `main.cc:482` joins forever. The sibling failure two lines up (`:420-423`) does it right. | FIXED (C3) |
| S4 | `src/core/config.h:750` | `--shards` is the only knob parsed with bare `std::atoi`: `--shards abc` → 0 → misleading "shards must be between 1 and 256"; `--shards -5` → 4294967291 → same message; `--shards 16x` silently accepted as 16. Every other knob goes through `cfg_parse_u32/u64/i64`. | FIXED — `cfg_parse_u32` + range at parse time; unit test (C5) |
| S5 | `src/core/server.h:3187` vs `:3340`; `src/snapshot/snapshot.cc:151,729` | `~Server` destroys members in reverse order: `snapshot_atomic_barrier_` (`:3340`) dies BEFORE `snapshot_` (`:3187`), whose destructor calls `abort_file()` → `server_->set_snapshot_atomic_barrier(false)` — a store into a member whose lifetime has ended (formal UB; harmless today because the atomic is trivially destructible). | FIXED — `~SnapshotManager` nulls `server_` before `abort_file()` (which already tolerates null); no layout change (C4) |
| S6 | `src/persist/aof.h:360` | `std::atomic<AppendFsyncPolicy> fsync_policy_;` — the only atomic in the tree without an initialiser; indeterminate until `AofManager::init` (`aof.cc:879`). Unreachable today (init is unconditional in `Server::init`, readers gated by `recording()`), but one early `CONFIG GET` away from an indeterminate read. | FIXED — initialised to the Config default (C4) |
| S7 | `src/main.cc:559-637` vs `src/core/genthread.cc:302-335` | Split and fused shutdown reports drifted: the gate-asserted `stuck:` loop is duplicated byte-for-byte; fused omits the per-thread table, the `wb:` line, the `tls:` line (even with `--tls-port`) and the `epoll:` line (even with `--net-io epoll`) — a fused TLS/epoll run ends with no evidence for those subsystems. main.cc's copy also shadows the outer loop variable `i` (`:562` vs `:588`; invisible without `-Wshadow`). | FIXED — one home `src/core/shutdown_report.h`; both paths call it; `stuck:` line byte-identical to what `tests/gate.sh:156…856` greps (C8) |
| S8 | `src/main.cc:216-217,:371-372` vs `:252` | Comments: "no listener may exist until every owner has decoded its shard sections" / "No listener exists until all owners report success" — but the unix listener is `listen(2)`'d at `:252` BEFORE the boot load; unix connects succeed into its backlog during load (`genthread.cc:119` same shape). TCP honours the rule (probe after load, per-thread SO_REUSEPORT listeners after that). Fused cannot honour it for unix without an IoLoop late-bind (io_loop.h is another lane's). | FIXED comment; late-bind idea in §4 (C8) |
| S9 | `src/main.cc:483`, `src/core/genthread.cc:288` vs `main.cc:381,394,405`, `genthread.cc:249,267` | The unix socket file is unlinked only after a SUCCESSFUL join; every boot-failure path (load failed, bind probe failed) leaves the stale file on disk. Self-healing on the next boot (the connect probe at `:235-248` unlinks it), so cosmetic. | FIXED — main owns the file's lifetime with an RAII guard covering every return (C8) |
| S10 | `src/core/ex_loop.h:1066` | `FlatStore& store = ...` unused — the tree's only `-Wall -Wextra` warning. | LISTED (ex_loop.h) — one-line delete |
| S11 | `src/core/io_loop.h:149-159` (`~IoLoop`) | Destructor closes listeners and frees `pending_handoffs_` but never `self_->clients()`/`dead_ready_`/`dead_next_`: at exit every live connection leaks its `Client` (~137 KB), fd and `TlsConn`/`SSL`/`BIO`. Kernel reclaims at `_exit`, so benign in production, but it is not commented as intentional and it makes LSAN permanently noisy and an in-process restart impossible. | LISTED (io_loop.h) |
| S12 | `src/core/server.h:2506,2516` vs `t_server.cc:2039-2040,2162,2164` | `note_sort_deref_refusal()`/`note_sort_deref_escape()` are never called, so INFO's `sort_deref_refusals`/`sort_deref_escapes` can only ever print 0 — the "literal placeholder" class the previous audit removed, in disguise. Either the SORT engine (scatter_engine.inc, other lane) forgot to count refusals/escapes (the constant-return-is-the-defect rule) or the rows should go. | LISTED for the SORT owner (needs the engine's intent) |
| S13 | `src/core/server.h:856` | `uint32_t lanes[kMaxThreads][kMaxThreads] = {}` — a 64 KiB stack object zeroed on every FLIP client-plan build to hold at most `nthreads²` counters. Not UB (8 MiB stacks); a smell on the FLIP path. | LISTED (FLIP owner) |
| S14 | `src/core/server.h:1489-1499` | The FLIP io→ex candidate filter excluding `aof_.writer_tid()` (and its SMT peer) is LOAD-BEARING: without it a role flip would strand the AOF writer in Ex state, where `~AofManager` closes without fsync and `discard_chunks()` drops buffered records. The code is right; nothing says why. | FIXED — comment (C6) |

### 1b. Docs / comments that contradict the code

| # | file:line | claim | truth | disposition |
|---|---|---|---|---|
| D1 | `tomokv.conf:174` | `# lb-age-sample-rate 1024` under "defaults shown" | `Config::lb_age_sample_rate = 0` since `43cfede8b` (zero-loss-when-stable law); 1024 is the measured cost point, not the default | FIXED (C7) |
| D2 | `tomokv.conf` PERSISTENCE section | "annotated reference for every runtime knob" | no line at all for `appendonly appendfsync appendfilename appenddirname auto-aof-rewrite-percentage auto-aof-rewrite-min-size aof-use-rdb-preamble aof-timestamp-enabled` (parser config.h:929-995; CONFIG GET exposes all) | FIXED — AOF block added with the code defaults and boot-only markers (C7) |
| D3 | `tomokv.conf:35-36` | `tls-ciphers DEFAULT`, `tls-ciphersuites TLS_AES_256_GCM_SHA384:…` as defaults | `src/net/tls.cc:152,159`: defaults are `ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256` and `TLS_AES_128_GCM_SHA256` — which `tomokv.conf:41` itself asserts | FIXED (C7) |
| D4 | `tomokv.conf:138` | `# ratio 18:14` with no "unset" prose (every other example-valued knob has one) | default is unset (`even_ifid = even_ex = 0`) = even split over all allowed cpus | FIXED — prose added (C7) |
| D5 | `tomokv.conf:242-254`, new AOF block | `tracking-table-max-keys` unmarked although immutable (`t_server.cc:413`); `appendonly` immutable here (`t_server.cc:311`) though Redis allows CONFIG SET | tag both `[boot-only]` | FIXED (C7) |
| D6 | `src/core/config.h:1164` | `--help`: "atomic-window N (default 256; 0=unlimited)" | default `-1` = AUTO = `min(16*shards, 1024)` (config.h:344-351, server.h:172-175); the comment 800 lines above says so | FIXED (C6) |
| D7 | `src/core/config.h:14`, `tomokv.conf:11` | `ValueSlot::kInline 1024 cmd/xshard.cc` | the constant is `src/cmd/scatter_engine.inc:60` (others verified: kRobWindow conn.h:59, kEmbedThreshold kvobj.h:51, kCommonBytes xshard.h:106) | FIXED (C6, C7) |
| D8 | `src/core/server.h:202` | "--place and --node-cpus are mutually exclusive" | knob renamed `--l3-domains` on 2026-08-25 (config.h:1093) | FIXED (C6) |
| D9 | `src/core/config.h:227,:1095`; `server.h:201-207` | field `Config::node_cpus` named after the deleted knob | it holds the `--l3-domains` string; same type, same slot → layout-neutral rename `l3_domains` | FIXED (C6) |
| D10 | `src/core/config.h:229` | "Unlike the per-node fields above" | no per-node fields exist (died with 3s) | FIXED (C6) |
| D11 | `src/core/server.h:272-273` | "Every thread still gets a channel from every other regardless of role" | task lanes are a role-partitioned `MaskedQueue` re-masked at each role change (`masked_queue.h:190-225`, `thread.h:313`); only client/release/transfer channels are uniform | FIXED (C6) |
| D12 | `src/main.cc:270-273` | third role arm `: "wb"`; two-`printf` `send=` … `"self\n"` | `Role` is `{Idle, Ifid, Ex}` (thread.h:59) — the "wb" arm prints for `Idle`; the `send=` column died with the 3s sender thread | FIXED (C8) |
| D13 | `docs/COMPLEXITY-AUDIT.md` (2026-08-24, present tense) | "CRITICAL RISK: invalid above 61.36M slots" (`:125-138,:294`); "no periodic expiry scan" (`:100`); "command names capped at 8 bytes, table linearly scanned" (`:37`); `Client` 1408 B (`:222`); 16-byte `TaskChan` tasks (`:156,:258`) | load-factor products are `uint64_t` (flatstore.h:166-175); `active_expire(budget)` exists (flatstore.h:1294, server.h:2259); command lookup is open-addressed (commands.cc:252-260); Client=1984 (conn.h:823); Task=32 (thread.h:88), `TaskChan` no longer exists | FIXED — dated status preface, body left as history (C10) |
| D14 | `docs/INSPIRATION.md:42,58,85,104,109` | "no max-client/RSS/store-memory gate", "no AUTH state … idle timeout", "no borrow lifetime", "no multi-key commands", "no connection-memory counter" | all shipped: `maxclients`/`maxmemory` (config.h:280,330), `cmd_auth`+`timeout` (t_server.cc:685, config.h:281), `zc-min` borrowed sends default-on (config.h:325), MGET/MSET scatter engine, `ClientOutputBufferLimits` (config.h:46) | FIXED — status preface (C10) |
| D15 | `docs/specs/AUDIT-{ACL,AOF,TLS,SMALLS}.md`, `SPEC-WAVEA.md` | planned homes `src/core/acl.h`, `src/journal/*`, `src/net/tls_ctx.h`/`tls_conn.h`, `src/cmd/geohash.cc`/`t_geo.cc`; planned tests `aof_replay.py`, `dump_roundtrip.py`, `hfe.py`, `monitor.py`, `client_cmds.py`, `gen-certs.sh`; planned knobs `--aof-image-max`, `--aof-writer-tid`, `--hash-field-expire`, `--function-heap-max`, `--monitor-buffer`, `--monitor-arg-max`, `tls-bio-size` | shipped as `src/cmd/acl.*`, `src/persist/aof.*`, `src/net/tls.*`, `src/cmd/geo.*`; tests `aof.py`/`aof_frames.py`, `dumprestore.py`, `hexpire.py`, `climon.py`/`climon2.py`, `tls.py`; none of those knobs exist | FIXED — "where it landed" preface per spec (C10) |
| D16 | `DESIGN-SNAPSHOT.md:10` | "`docs/shard-serialization.md`" | it is a path in the Dragonfly tree, not ours — reads as a dangling local link | FIXED — qualified (C10) |
| D17 | `src/store/flatstore.h:86-88,107`, `t_server.cc:862` | "compiled out when assertions are disabled … no request-path tax" (`#ifndef NDEBUG`) | no build target ever defines `NDEBUG`, so the DEBUG table-alloc fault injection and the one `assert` (flatstore.h:1957, cold) are ALWAYS compiled in. Cold paths, so no hot-path tax — but the premise "release disables it" is false for every binary the gate has ever measured | LISTED (flatstore.h; owner: decide whether release should define NDEBUG — there are only 2 `assert`s in src/, both cold) |
| D18 | `src/core/ex_loop.h:1` | "a sender (io in 2s, wb in 3s)" presents the deleted design as current | 3s deleted 2026-08-24 | LISTED (ex_loop.h) |
| D19 | `src/core/config.h:4` vs `t_server.cc:364` | "the CONFIG table is built FROM this struct" | `aof-use-rdb-preamble` is a hardcoded `"yes"` row with no Config field (deliberate per AUDIT-AOF §711-720); 13 Config fields have no CONFIG GET row: `port bind unixsocket l3-domains place ratio shard-home shards pin load lru-clock-shift user conf_path` — `port`/`bind`/`unixsocket`/`shards`/`lru-clock-shift` are the Redis-visible gaps | LISTED (knob-compat feature lane; see idea I1) |
| D20 | `src/core/config.h:694-703` | `--genthread-schedule streams` still parses and maps to `overlap=2`, which now selects the three-way schedule, not streams (the comment admits it) | stale spelling with a live, different effect; kept as an alias for pinned scripts | LISTED (owner: keep alias or retire) |

### 1c. Duplicated code

| # | file:line | finding | disposition |
|---|---|---|---|
| C1 | `src/core/server.h:245` vs `main.cc:411`, `genthread.cc:96` | Unix-listener owner tid derived three times as `ifid_threads().front()`; Server latches it as `unix_owner_tid_` for FLIP exclusion (server.h:1490,1498). | FIXED — `Server::unix_owner_tid()` accessor used by both boot paths (C8) |
| C2 | `src/core/config.h:588-595` vs `:173` | `--client-output-buffer-limit` stages a `scratch`, then `cfg_parse_client_output_buffer_limit` stages its own; the outer copy is redundant. | FIXED (C5) |
| C3 | `src/persist/aof.cc:152`, `src/snapshot/snapshot.cc:58` (also `ex_loop.h:1663`) | `realtime_ms()` re-implemented three times, byte-identical to `now_realtime_ms()` in `src/core/signal.h:59` — whose own comment says "ANYTHING compared against a deadline must come from here". Both TUs already include signal.h. | FIXED for aof.cc/snapshot.cc (C11); ex_loop.h LISTED |
| C4 | `src/cmd/t_stream.cc:37,45,57,67,121,129` vs `src/cmd/t_stream_groups.cc:29,102,39,55,113,121` | `id_compare`, `id_increment`, `parse_u64_exact`, `parse_i64_option`, `reply_id_to`, `reply_id` byte-identical across two files that already share `t_stream.h`. | LISTED — cold command code, but a 60-line move at night without the stream battery running is not this lane's call |
| C5 | 12 sites: `t_string.cc:62 t_list.cc:42 t_zset.cc:104 t_hash.cc:829 t_hash_ttl.cc:41 slowlog.cc:143 server_tail.cc:72 xshard_commands.inc:26 t_set.cc:211 t_stream.cc:67 t_stream_groups.cc:55` and **`t_server.cc:87`** | `parse_i64(Slice)` implemented 12×; eleven agree (canonical string2ll: no `+`, no leading zeros) and **`t_server.cc:87 parse_i64_slice` accepts `+` and leading zeros** — `WAIT +5 1` / `WAIT 05 0` parse there and are rejected by the identical-purpose helper in `server_tail.cc`. A parity divergence, not just duplication. | LISTED — needs a compatibility battery (idea I5) |
| C6 | `t_server.cc:60 server_tail.cc:45 slowlog.cc:130 t_string.cc:47 pfdebug.cc:23` (+`acl.inc:53`, `tls.cc:27`) | `eq_icase(Slice, const char*)` ×5 byte-identical (+2 variants). Hazard: `Slice::eq_icase(string_view)` at `base/slice.h:37` folds only the LEFT side and silently requires a lowercase literal — two contracts under one name (zero violations today). | FIXED — contract documented at slice.h:37 (C6); consolidation LISTED with C5 |
| C7 | `lcs.cc:24 server_tail.cc:58 t_server.cc:73 xshard_commands.inc:13`; `t_stream.cc:57 t_stream_groups.cc:39` | `parse_u64(Slice)` ×4 + `parse_u64_exact` ×2. | LISTED with C5 |
| C8 | `server_tail.cc:104 t_zset.cc:1029 xshard_commands.inc:147` (+`t_list.cc:35 t_string.cc:242 t_set.cc:239`, literal ×53) | `reply_invalid_integer` under six names; `reply_maxmemory_oom` (t_string.cc:308, forward-declared per TU) shows the one-definition pattern already in use. | LISTED |
| C9 | `base/alloc.h:48` vs `store/atomic_mvcc.h:146`, `core/read_local.h:315` | jemalloc size-class closed form (`63 - clzll(n-1)`, `9 + 4*(k-7) + …`) derived three times under a comment demanding it be "identical everywhere or boot fails". | LISTED (read_local.h other lane; atomic_mvcc.h is the atomics lane's neighbourhood tonight) |
| C10 | `net/tls.cc:90` vs `cmd/acl.inc:86` | `hex_nibble` accepts `A-F`; `acl_hex_nibble` lowercase only — same job, different grammar; encode table `"0123456789abcdef"` ×3 (`scripting.cc:108`, `acl.inc:106,1468`). | LISTED (net/*) |
| C11 | `t_hash.cc:1194`/`t_set.cc:992` `parse_scan_options`; `t_hash.cc:1229`/`t_zset.cc:2145` `reply_scan`; `t_zset.cc:2227 t_list.cc:930 t_hash_ttl.cc:350 t_stream.cc:1348 t_hash.cc:1458 t_set.cc:1090` `#define TOMO_HANDLER_PAIR` (6 identical + a 4-arg variant in `t_string.cc:1438`) | scan helpers and the handler-pair macro re-spelled per type file. | LISTED |
| C12 | `src/core/server.h:147-154` vs `config.h:857,:1242` | `Server::init` re-validates `shards` and `maxmemory_samples` after the parser/validator did. Defensive for non-main callers. | LISTED as intentional (idea I2 removes the need) |
| C13 | `tools/gen_cmdmeta.py:16`, `tools/gen_acl_categories.py:17`, `Makefile:19`, `tests/gate.sh:72` | four source inventories (two `COMMAND_SOURCES` lists, `SRC`, the gate's ASAN glob). Protected only by the gate's cmdmeta-coverage row. | LISTED |

### 1d. Dead code / dead selectors

| # | file:line | finding | disposition |
|---|---|---|---|
| X1 | `src/net/conn.h:47,731-735`; `main.cc:575`; `wb.h:729,807`; `ex_loop.h:2852` | `TOMO_WEDGE_FORENSICS` is defined nowhere AND can no longer be defined: its three `std::atomic<uint32_t>` counters sit before `private:` in `Client`, so arming adds 12 bytes and trips `connection_flags_offset()==55`, `tls_slot_offset()==1980` and `sizeof(Client)==1984` (conn.h:813-823). An armable-by-design diagnostic that is now un-armable. NOTES-WAVED.md:126 reserves its fate for the owner. | LISTED (conn.h) — new fact for the owner; idea I9 keeps it armable |
| X2 | `src/core/io_loop.h:972-1913`, `ex_loop.h:303,338,509`, `genthread_pipeline.h:40-70` | `run_fused_streams_loop()` (~940 lines), `fused_pass()`, `fused_streams_pass()`, `fused_sweep()`, `kGenthreadIfidContexts/kGenthreadWbContexts/GenthreadMicrostage/kGenthreadStreamsSchedule` — the deleted "streams" arm's body; `--overlap 2` now dispatches the three-way schedule (config.h:698, genthread.cc:63). The largest dead block in the tree. | LISTED (io_loop.h/ex_loop.h) |
| X3 | `src/core/server.h:434,440,447,491,617,604,775,776,1397,1605,1610,2734` | zero-caller accessors: `lb_client_last_move_ms lb_note_client_move lb_client_owner_weight lb_bucket_weight lb_shard_moves placement_dispatch_paused flip_surviving_io_count flip_surviving_io flip_set_incoming_clients flip_all_candidates_acked flip_all_surviving_io_acked debug_barrier_hold` (getter; `set_`/`_armed` are live). Verified: exactly one reference tree-wide each (the definition). Not in NOTES-WAVED's reserved set. | FIXED — deleted (C12) |
| X4 | `src/core/flipctl.h:129,133,134` | `has_signature()`, `smoothed()`, `anchored_signature()` — unused, even by `tests/flipctl_unit.cc`. | FIXED (C12) |
| X5 | `src/core/shard.h:335` | `Shard::lb_signals_enabled()` — zero callers (`Server::key_lb_signals_enabled` is the live gate). | FIXED (C12) |
| X6 | `src/cmd/multi.h:39`/`multi.inc:1179` `multi_queueing`; `notify.h:220`/`notify.inc:606` `notify_abort_op`; `blocking.inc:776` `remove_front_from_shard`; `t_sort.h:42` `SortSpec::source_is_list` (write-only); `climon.inc:145` `climon_monitor_clock_ms_`; `scatter_engine.inc:436,487` `arena_bytes`/`geo_store_distance` (write-only); `placement.h:488` `MigrationPlan`; `shard.h:448,296,403` `foreign_ratio`/`migration_cost_bytes`/`Stats::migrated_bytes`; `exec/op.h:139` `Op::rbuf_off` (write-only) | all zero-reader or zero-caller — and ALL explicitly reserved by `NOTES-WAVED.md:120-135` ("needs-verification tier", "future-LB contract from V11", "later layout decision"). | LISTED — still pending the owner's decision; nothing new except that they remain |
| X7 | `src/cmd/command.h:176`/`commands.cc:349` | `SubcommandArityError::Syntax` is never assigned (every table row uses `UnknownOrWrong` or the default), so the `else if (… == Syntax)` arm is unreachable. | LISTED (command.h/commands.cc) |
| X8 | `src/core/io_loop.h:359-373`; `flatstore_atomic.inc:265-266`; `thread.h:923`; `conn.h:69,647`; `masked_queue.h:35` | zero-caller: prepared-client-transfer commit/cancel API (4 fns), `atomic_read_epoch/origin_conn_id`, `read_local_retire_sink()` getter, `kRbufHardCap`, `Client::has_atomic_groups_io`, `arena_occupancy_at_lane_full`. | LISTED (other lanes' files) |
| X9 | `src/core/server.h:1839` | `#if !defined(NDEBUG) && !defined(__OPTIMIZE__)` bounds check — no Makefile target is unoptimised, but `CXXFLAGS ?=` allows `make CXXFLAGS="-O0 -g"`, so the hook is reachable by hand. | no action (works as designed) |

### 1e. Header / include hygiene

| # | file:line | finding | disposition |
|---|---|---|---|
| H1 | `src/main.cc:5-7` | `<arpa/inet.h>`, `<netinet/in.h>`, `<netinet/tcp.h>` — zero uses (listener creation lives in IoLoop). Transitive-only: `<memory>`, `<atomic>`, `<cstdint>`, `<pthread.h>`, `<sched.h>`. | FIXED (C9) |
| H2 | `src/core/config.h:31-33` | uses `Slice` and `parse_notify_flags` (`cmd/notify.h:66`) only through `store/flatstore.h`. `notify.h` depends on nothing but `base/slice.h`. | FIXED — direct includes (C9) |
| H3 | `src/core/config.h:33` | pulls all of `store/flatstore.h` (3457 lines) for `HashKind`/`g_hash_kind` (flatstore.h:414-417). | LISTED (idea I4: `store/hash_kind.h`) |
| H4 | `src/core/server.h:15,18` | `<array>`, `<climits>` — zero uses (`UINT32_MAX` is `<cstdint>`). | FIXED (C9) |
| H5 | `tools/benchtxn.cc:26,38` | `<arpa/inet.h>`, `<cstring>` — zero uses. | FIXED (C9) |
| H6 | `src/store/atomic_mvcc.h:137,142,146` | `static` (not `inline`) functions in a header reaching every TU via flatstore.h → config.h → server.h: a private copy per TU. | LISTED (atomics lane's neighbourhood tonight) |
| H7 | `src/core/pubsub.inc`, `src/cmd/climon.inc` | included inside `class IoLoop` from io_loop.h and therefore reach 6 TUs; safe only because every line is a member (implicitly inline). Neither file says so. | LISTED (io_loop.h) |

### 1f. Build / tools / tests

| # | file:line | finding | disposition |
|---|---|---|---|
| B1 | `Makefile` | no target builds `tests/config_parser_test.cc`, `tests/flipctl_unit.cc`, `tests/broaden_bench.cc`, `tools/benchtxn.cc`; the gate (`gate.sh:75`) and `NOTES-HYGIENE.md:394` hardcode one g++ line (without `-Wall -Wextra`); the other three bit-rot silently. | FIXED — `make unit` (config + flipctl unit tests, run) and `make tools` (drivers), neither in `all` (C13) |
| B2 | `Makefile:52` | `asan: BIN := build/tomokv-asan` — target-specific variable never read (recipe hardcodes the path). | FIXED (C13) |
| B3 | `tests/gate.sh:137` | `python3 tests/../tests/torture.py` — path noise. | LISTED (gate shared tonight) |
| B4 | `tests/gate.sh:71-73` vs `Makefile:19-31` | gate ASAN build via directory globs vs Makefile explicit `SRC`; `make asan` exists. | LISTED |
| B5 | `tests/gate.sh:41-45` | ledger comment: two "211 -> 213" rows, a dangling fragment, undocumented 213→224 step. | LISTED |
| B6 | `tools/tomokv-nic.service:8` | `ExecStart` pinned to `/home/user/Projects/tomokv-cpp-perthread/tools/nicrestore.sh` — an installed unit bound to one worktree's path. | LISTED (owner) |
| B7 | `tests/evict_battery.py:3` | cites `evict_drive.sh`; `tests/evict_drive.sh` does not exist (carried from NOTES-HYGIENE, still open). | LISTED |
| B8 | `tests/config_parser_test.cc:115-120` | `rejects` lambda leaks every rejection message to the real stderr (50+ lines of noise per gate run) while `rejection_text` captures. | FIXED (C5) |

### 1g. Feature-file structure

| # | where | finding | disposition |
|---|---|---|---|
| F1 | repo root | 89 `NOTES-*.md` + `DESIGN*.md`/`EVIDENCE-*`/`AUDIT-*` at the root vs 5 files in `docs/`; 55 references to `NOTES-*.md` paths in src/tests (many in other lanes' files). | LISTED — proposal §5 |
| F2 | `scratchpad/` (committed) | probe sources committed in-tree; `docs/specs/AUDIT-ACL.md` cites `scratchpad/aclprobe/probe.cc`, absent (only `holes.cc`). | LISTED (owner: archive policy) |
| F3 | `src/main.cc`, `src/core/genthread.cc` | the end-of-run report: a 100-line inline block in main plus a partial copy in genthread — one feature, two half-homes. | FIXED — `src/core/shutdown_report.h` (C8) |
| F4 | `src/cmd/hll.cc:1-6` | "representation-faithful port of Redis src/hyperloglog.c" while the project rule forbids copying the RSALv2/SSPLv1 tree (carried from NOTES-HYGIENE; provenance is an owner call). | LISTED |
| F5 | naming | `ifid_*` (placement API) vs `io`/`owner_io`/`nio`/`n_io` (77+ sites) for the same lane; `ex`/`executor`/`worker_*` (io_loop.h:4981-5041, shard.h:373-378) for the same role; `NOTIFY_*` masks (notify.h:29-55) in a `kFoo` tree. All coexist. | LISTED (renames cross io_loop.h/thread.h) |

---

## 2. COMMITS (one category each; `taskset -c 48-55,176-183 make -j8` green after every one)

| # | category | what |
|---|---|---|
| C1 | docs(audit) | this file (findings) |
| C2 | core(genthread) | fused boot gate: stopped threads report at the gate; main's wait counts them (S1) |
| C3 | main(signals/boot) | signal-handler safety + install-after-populate + disarm before teardown (S2); io-thread init failure stops the server instead of hanging the join (S3) |
| C4 | persist/snapshot | `~SnapshotManager` does not reach into a mid-destruction Server (S5); `fsync_policy_` initialised (S6) |
| C5 | config(parser) | `--shards` via `cfg_parse_u32` (S4); redundant obuf scratch (C2); parser test: shards grammar + silent rejects (B8) |
| C6 | config/server(text) | stale text (D6-D11, D8), `node_cpus`→`l3_domains` (D9), AOF-writer exclusion comment (S14), `Slice::eq_icase` contract (C6) |
| C7 | conf | tomokv.conf: D1-D5, D7 |
| C8 | core(shutdown report) | `src/core/shutdown_report.h` shared by split and fused (S7, F3); `unix_owner_tid()` (C1); "idle" role, `send=` vestige (D12); listener comment truth (S8); unix socket RAII (S9) |
| C9 | includes | H1, H2, H4, H5 |
| C10 | docs | status prefaces: COMPLEXITY-AUDIT, INSPIRATION, specs (D13-D16) |
| C11 | dedup | `realtime_ms` forks → `now_realtime_ms()` (C3) |
| C12 | dead code | zero-caller accessors (X3, X4, X5) |
| C13 | build | `make unit`, `make tools`, asan var (B1, B2) |
| C14 | docs(audit) | ledger + ideas closed out |

(The table is updated as commits land; see `git log --oneline 775aeea48..t-night-cleanup`.)

---

## 3. STABILITY DEFECTS

| # | defect | status | repro idea (not run tonight) |
|---|---|---|---|
| S1 | fused boot gate hang on SIGTERM during/after load | FIXED | `--thread-mode 1s --load <multi-GB dump>` with uneven shard sizes; `kill -TERM` at ~half the load time. Pre-fix: after "persistence load" finishes, the process never prints `stuck:` and never exits; `gdb -p` shows main in `boot_cv.wait` at genthread.cc:277 with `runners_ready < nthreads`. Deterministic variant: `sleep` injected between `:234` and `:272` |
| S2 | signal handler vs boot population / teardown | FIXED | TSAN build; `for i in $(seq 200); do ./build/tomokv-tsan --shards 256 & sleep 0.0$RANDOM; kill -INT $!; wait; done` — pre-fix TSAN reports the `g_threads` race when the signal lands inside `push_back`; a SIGINT during `Server::init` was silently swallowed (second Ctrl-C needed) |
| S3 | io-thread init failure hangs the join | FIXED | force `ios[tid].init` to fail (e.g. `ulimit -n 40` with `--maxclients 10000` after the rlimit adjust, or a bind failure on a per-thread reuseport listener); pre-fix: one thread returns silently, the rest serve, SIGTERM then exits — but main never printed why |
| S4 | `--shards` grammar | FIXED | `./build/tomokv --shards 16x` boots with 16 shards silently (pre-fix); `--shards abc` reports the range message |
| S5 | `~Server` member-lifetime order | FIXED | UBSAN cannot see this one (trivial dtor); reasoning only: server.h:3187 vs :3340 |
| S6 | uninitialised `fsync_policy_` | FIXED | MSAN/valgrind on a path reading it before `AofManager::init` (none exists today) |
| S7 | fused shutdown report lacks wb/tls/epoll | FIXED | `--thread-mode 1s --tls-port …`, SIGTERM, compare tail with a 2s run |
| S8 | unix listener accepts into backlog before load | LISTED (comment fixed) | `--unixsocket /tmp/t.sock --load <big dump>`; `redis-cli -s /tmp/t.sock PING` connects immediately and blocks until load ends; TCP refuses until then |
| S9 | stale unix socket file after boot failure | FIXED | `--unixsocket /tmp/t.sock --port <busy port>`; pre-fix leaves `/tmp/t.sock` |
| S10 | unused variable warning in ex_loop.h | LISTED | `make 2>&1 \| grep warning` |
| S11 | live Clients/TLS leaked at exit | LISTED | LSAN run with one idle connection at SIGTERM |
| S12 | INFO rows that can only print 0 | LISTED | `redis-cli INFO \| grep sort_deref_refusals` after any SORT battery — always 0 |
| X1 | `TOMO_WEDGE_FORENSICS` un-armable | LISTED | `make CXXFLAGS="… -DTOMO_WEDGE_FORENSICS"` → three static_assert failures in conn.h |

---

## 4. ARCHITECTURAL / ALGORITHMIC IDEAS (not implemented)

Each idea states how it respects the owner's design philosophy: single-owner writes (no shared-writer
index — "no garnet 2.0"); reads never obstructed by writes (no reader retries/seqlocks; immutable
replacement + QSBR); no in-place overwrite while read-local is armed; numeric knobs with 0=off /
-1=auto and self-derived thresholds; main commands zero-regression; hardcode-or-delete; one file per
feature.

| # | idea | rationale | philosophy fit |
|---|---|---|---|
| I1 | **One knob table, four surfaces generated.** A `constexpr KnobSpec[]` (name, kind, default, range, live/boot, off-value, doc line) from which `parse_config_args`, `--help`, the CONFIG GET/SET table (`t_server.cc:init_config`) and `tomokv.conf` (via `tools/gen_conf.py --check`, gate row) are all derived. | Tonight found drift in three of the four hand-maintained surfaces (D1, D2, D3, D6) and 13 Config fields with no CONFIG GET row (D19). `config.h:4` already claims this single-source property; it is not true today. | Hardcode-or-delete applied to duplication; the knob philosophy becomes checkable (a spec with `off_value=0` can assert its feature allocates nothing when 0 — a gate row rather than a comment). Boot-only code; zero hot-path effect. One file: `core/config.h` stays the home. |
| I2 | **`ValidatedConfig` strong type.** `validate_config` returns a wrapper only it can construct; `Server::init` and `run_fused_server` take it. | Removes the duplicated range checks in `Server::init` (C12) and makes every future boot path (tests, embedding, a fuzz driver) go through one validator. | Hardcode-or-delete; boot-only; no layout change (wrapper holds the same 624-byte struct). |
| I3 | **Offset locks for the boot-latched Config fields executor code loads directly** (`read_local`, `overlap`, `thread_mode`, `ex_sched`, `read_local_interleave`, `read_local_prefetch_capture`): a `static_assert(offsetof(Config, x) == N)` table beside the `sizeof==624` lock. | Five comments (config.h:246,285,310,376,409) describe a "consume the existing padding hole so no established offset moves" discipline that the sizeof lock alone cannot enforce (a same-size shuffle passes). | The layout locks are the owner's instrument; this makes the stated invariant compiler-checked at zero runtime cost. |
| I4 | **`store/hash_kind.h`** holding `HashKind`, `g_hash_kind`, `g_hash_seed`, `g_sip_k0/k1` (flatstore.h:414-417). | config.h, main.cc, snapshot/aof (seed restore) need 4 symbols and today pay 3457 lines of flatstore.h for them; every TU includes config.h via server.h. | One file per feature (the hash seed IS a feature: it is part of the persisted format, main.cc:172). Zero runtime change; faster rebuilds. |
| I5 | **`base/strnum.h`**: one canonical `parse_i64/parse_u64(Slice)` + one `eq_icase`. | 12 `parse_i64` copies with one divergent grammar (`t_server.cc:87` accepts `+`/leading zeros → WAIT/CLIENT PAUSE parity deviation), 4 `parse_u64`, 6 `eq_icase` (C5-C7). | Main commands zero-regression: the canonical copies are `inline` and compile identically; the divergent one is a parity FIX that needs the differential battery first (reproduce → fix). |
| I6 | **Late-bound listeners.** `IoLoop::attach_listener(fd)` callable before `activate()`, so main creates the unix listener AFTER the load barrier in both modes. | S8: the "no listener before load" invariant is honoured for TCP but not unix; fused mode cannot honour it today because `IoLoop::init` consumes the fd per thread before the shared barrier. | Boot-only; single-owner (the owning io thread still binds/accepts alone); no hot-path change. |
| I7 | **Fused boot handshake as an explicit 3-state gate** (`Loaded → Ready → Running`, each wait with a stop escape and a `gave_up` count) instead of two counters, two bools and one cv. | S1 was exactly a missing stop edge on one of four waits; the split path has no handshake and no such bug. | Boot-only; zero runtime effect. |
| I8 | **Vacuous-telemetry gate row**: a static check that every `note_*`/`*_added` setter on `Server` has ≥1 call site, and every INFO row's source is written somewhere. | S12: two INFO rows can only print 0 — the class of defect the vacuous-validation rule exists for. The previous audit removed literal placeholders; these are placeholders by control flow. | Hardcode-or-delete; the gate's "mechanism FIRED" doctrine applied to telemetry. |
| I9 | **Forensics counters as an armed sidecar**, not `Client` members: `TOMO_WEDGE_FORENSICS` counters keyed by client id in a side table (the same "armed-only state sidecars + layout locks" pattern t-rlmerge used for read-local). | X1: the diagnostic is un-armable because arming moves locked offsets. | Explicit-ARM-only diagnostics (tripwire law); layout locks hold; zero cost disarmed. |
| I10 | **Signal doorbell.** `on_signal` also `write(2)`s one byte to a per-process eventfd that every ring/epoll set has registered, so stop is observed immediately instead of at the next 50 ms park timeout. | Shutdown latency today is bounded by the park timeout ×1; harmless, but a one-shot doorbell is free and makes the gate's `stop()` deterministic. | Never on the hot path — a single write at shutdown; `write(2)` is async-signal-safe. |
| I11 | **`IoLoop::close_all_clients()` on the exit path** (S11). | LSAN can never be clean for the connection lifecycle; an in-process restart test is impossible. | Shutdown-only; reads never obstructed (no live readers exist after the joins). |
| I12 | **NDEBUG policy.** Decide once whether release defines `NDEBUG`. Today every "compiled out when assertions are disabled" comment (flatstore.h:86-88,107; t_server.cc:862) is false for every binary ever benchmarked; only 2 `assert`s exist (both cold), so the perf effect is nil — the point is that comments and builds should agree. | D17. | Hardcode-or-delete: either define it and keep the DEBUG surface behind `--enable-debug-command`, or drop the `#ifndef NDEBUG` wrappers. |
| I13 | **`docs/notes/` with a redirect policy** for the 89 root NOTES (F1): move, then leave a one-line `NOTES-X.md → docs/notes/X.md` stub for the 55 code references until the referencing lanes update their comments. | The root is the first thing a reader sees; today it is a lane ledger. | One file per feature applies to docs too; zero code effect. |

(§4b — status of the 2026-08-24 complexity findings and which of its recommendations remain
open — is appended in the closing commit once the re-verification against today's code lands.)

---

## 5. ITEMS DELIBERATELY LEFT FOR OTHER LANES / OWNER

| owner / file | item |
|---|---|
| ex_loop.h lane | S10 unused `store` (ex_loop.h:1066); D18 "wb in 3s" banner; C3 `realtime_ms` fork (:1663); X2 dead `fused_pass`/`fused_streams_pass`/`fused_sweep` |
| io_loop.h lane | X2 `run_fused_streams_loop` (~940 dead lines) + `genthread_pipeline.h` constants; S11 client teardown at exit; X8 prepared-client-transfer API; H7 pubsub.inc/climon.inc "member-only" contract comment; F5 `worker_*` naming |
| conn.h / net lane | X1 `TOMO_WEDGE_FORENSICS` un-armable (three layout locks); X8 `kRbufHardCap`, `has_atomic_groups_io`; C10 `hex_nibble` grammar split with acl.inc |
| command.h / commands.cc lane | X7 unreachable `SubcommandArityError::Syntax` arm; `command_client_migration_discard` zero callers |
| flatstore / store lane | H3 `hash_kind.h` split; D17 `#ifndef NDEBUG` premise; X8 `atomic_read_epoch/origin_conn_id`; H6 `static`→`inline` in atomic_mvcc.h; C9 `pool_class` triplication |
| thread.h lane | X8 `read_local_retire_sink()` getter; F5 `ifid` vs `io` naming |
| SORT lane (scatter_engine.inc) | S12 `note_sort_deref_refusal/escape` never called — wire or delete the INFO rows |
| knob-compat feature lane | D19 CONFIG GET gaps (`port bind unixsocket shards lru-clock-shift`); C5 `parse_i64_slice` parity divergence (needs battery) |
| stream lane | C4 six byte-identical helpers → `t_stream.h` |
| owner decisions | X6 the NOTES-WAVED reserved tier; D20 `--genthread-schedule streams` alias; B6 systemd unit path; F1 NOTES relocation; F2 `scratchpad/` archive; F4 hll.cc provenance wording; I12 NDEBUG policy |
| gate maintainers | B3 `tests/../tests/`; B4 glob vs SRC; B5 ledger comment; B7 `evict_drive.sh` |
