## iowake

Lane `cx-iowake`, worktree `/home/user/Projects/cx-iowake`. PRE is `origin/cpp`
**8be4f68323** (published wave 15). Nothing was pushed. Findings come from
`round5-read/bounded-queue-wake-audit.md` (F5, F4, F9, F13).

Every build, correctness runner and server ran on CPUs 64-95 (gate servers 64-79, load 80-95)
and ports 23400-23499. Every server boot set `LC_ALL=C`. No benchmark, ABBA, NIC or full
`iteration` gate was run. No park constant, locked layout, Server/SnapshotManager layout,
architecture or algorithm changed. The only throughput assertion is the F9 capture bound.

### Items

| Item | PRE witness (gate row on the PRE arm) | POST result | Mechanism changed | Residual |
| --- | --- | --- | --- | --- |
| **F5** TLS multi-unit output (SEVERE STALL) | `iowake F5 ...` FAILS in all 6 legs (2s, 1s read-local, 1s reorder x uring, epoll). A TLS 1.3 MGET of 16 x 2 KiB values takes 837-889 ms (2s, R7). With 1s read-local, an MGET of 4 x 64 KiB takes 283-284 ms. With a CBC memory BIO on epoll, an MGET of 16 x 2 KiB takes 815-867 ms (50 ms with 1s read-local). kTLS 1.2, CBC on uring and plain TCP pass on the same boots. | All 6 legs pass. Every probe (MGET 16 x 2 KiB, 16 pipelined GETs, MGET 4 x 64 KiB, GET 1 MiB) x 10 rounds x 4 transports is exact. The worst probe is 4.65 ms (CBC GET 1 MiB); TLS 1.3 is at most 1.95 ms, kTLS at most 1.73 ms and TCP at most 1.16 ms. | IO Phase 1 counts `pump_tls` progress as loop work (`io_loop.h` flush_ready; `reorder.cc` R7 envelope regenerated from it). A synchronous transport therefore cannot park while units remain. | Each plaintext unit (segment or 16 KiB record) still costs one loop pass, with no park. Looping inside `pump_tls` would be a throughput change, so it was not made. |
| **F4** AOF writer not re-woken during a large record | `iowake F4 ...` FAILS in all 4 legs (2s, 1s x uring, epoll). While a 200k-field HSET post-image is written, a gated PING on a third thread waits 50.1 ms (epoll, the park timeout) or 42-43 ms (uring: until the owner's command ends). | All 4 legs pass. Over 3 HSET (49 frames) and 3 RPUSH (230 frames, 3M-element list) writes, the worst gated PING is 0.64 ms. Each write ran at least 616 probes, the gate held the probe at least 49 times per write, and each write took 36.8-40.3 ms. Every acknowledged post-image replays on restart. | `writer_pass` large branch: take-then-drain on the owner's notify bit, restoring the other producers' bits. `drain_producer` and the snapshot writer re-set a producer's bit only when the budget is spent, so a racing post keeps its 0->1 wake edge. `AofProducer` submits the owner's ring after a mid-record frame, so the wake does not wait for the owner's next submit. | Under io_uring, a gated reply still waits for frames posted before it to be written (writer throughput), not for a timer. |
| **F9** BGSAVE owner not woken by the writer | `iowake F9 ...` FAILS: in 1s, a single-owner 128 MiB BGSAVE captures 89-90 MiB/s on both engines (64 chunks per ~50 ms park). The 2s legs pass on PRE, because the executor's 2,048-pass spin outlasts the writer lag on this box (PRE 2s/uring 242-344 MiB/s in direct runs). | All 4 legs capture 538.6-569.6 MiB/s (bound 200), with at least 3,335 owner refusals per save. Every save refused the owner at least once (anti-vacuity), and the dump reloads exactly. | `post_chunk`: on refusal, publish the producer's bit in a file-scope waiter word, fence, then re-check for room. `writer_pass`: after popping from a producer, fence, claim its bit and send an unconditional `msg_to` to that producer's ring (main loop, drain-all backstop; SAVE uses the same pass). | Only the 1s legs discriminate on this box. The waiter word is per process: one snapshot coordinator exists, and keeping it outside the struct leaves Server's layout unchanged. |
| **F13** DEBUG LOADAOF on the AOF writer's IO thread (HANG, DEBUG-only) | `iowake F13 ...` FAILS: 200 pipelined SETs then DEBUG LOADAOF on the writer thread's connection never replies on io_uring (2s and 1s), and every gated reply freezes. Both epoll legs pass (control). | All 4 legs: 3 writer-thread attempts plus 1 off-writer control each reply OK in 0.43-3.14 ms. A PING on another thread answers, and DBSIZE plus every value reloads exactly. | The writer-thread branch of `prepare_debug_loadaof` loops on the existing pumped drain (`AofManager::runtime_pump`: writer_pass, submit, reap persistence CQEs). It is bounded by 5 s and AOF failure, as the other branch is, and returns the same timeout error. | Pre-existing and also seen on PRE epoll, not fixed: a LOADAOF that races another connection's in-flight *large* record can read a partial record (`ERR Error trying to load the AOF files`), and an in-flight write can be absent after the reload. See the adjacent findings. |

Witness: `tests/iowake.py` (cases `tls`, `aof`, `bgsave`, `loadaof`), run through the gate jobs
`iowake-tls`, `iowake-aof`, `iowake-bgsave` and `iowake-loadaof`. Each job boots its own servers in
every declared mode and engine. Each one bounds the delayed operation below the 50 ms park
rescue: 25 ms for F5 and F4, 200 MiB/s for F9, 5 s for F13 against a hang. Each one also asserts
exact replies and has its own anti-vacuity checks:
- F5: the server-side `tcp-ulp-tls` rxconf/txconf state and the INFO kTLS counters prove which
  transport each connection reached.
- F4: the record is at least 1 MiB, at least 10 probes ran and the AOF gate held the probe.
- F9: the owner's channel refused a post during every save.
- F13: the PRE hang shows that chunks are still pending in this exact sequence.

PRE receipts: `docs/iowake/witnesses/pre-5ab6cada.json`.

### Commits (one per item, plus build/generated follow-ups)

| Commit | Content |
| --- | --- |
| `fdb974f217` | F5: `io_loop.h`, `reorder.cc`, `tests/iowake.py` (tls), gate job `iowake-tls` |
| `7c7c1e1f4e` | F4: `aof.cc`, `tests/iowake.py` (aof), gate job `iowake-aof` |
| `352ead67b6` | F9: `snapshot.cc`, `tests/iowake.py` (bgsave), gate job `iowake-bgsave` |
| `9749d42f43` | F13: `scatter_engine.inc`, `tests/iowake.py` (loadaof), gate job `iowake-loadaof` |
| `3c80b505db` | Makefile: re-derived `large-unit-insns` pins for the 12 grown units (`tools/iowake_budgets.py`) |
| `06b042739d` | F5: R7 envelope regenerated from `io_loop.h` (comment text only; gate row "R7 generated envelope parity") |
| final commit | This report, `tools/iowake_{counts,identity,pad}.py` and the `docs/iowake` evidence summaries (no file over 240 KB) |

### Production diff summary (`git diff 8be4f68323 -- src Makefile`: src +84/-9 lines, comments included)

The tables below summarize the hunks, so the full diff is not reproduced.

- **`src/core/io_loop.h`, `flush_ready` Phase 1 (TLS branch only).** The call that was
  `(void)wb_.pump_tls<kEp>(*c, *tls);` becomes `if (wb_.pump_tls<kEp>(*c, *tls)) work++;`.
- **`src/core/reorder.cc`, `r7_flush_ready`.** The same line, regenerated by `tests/r7shadow_sync.py --write`.
- **`src/persist/aof.cc`.**
  - `writer_pass`, large branch: take the owner's word and `restore` the other bits before
    `drain_producer`.
  - `drain_producer`: change `if (depth()) set()` to `if (!budget && depth()) set()`.
  - New file-local `submit_large_frame_wake(context)`, which runs
    `if (sq_ready()) submit_and_reap()`. It is called after the 3 mid-record `seal(0, context)`
    sites (emit x2, record_bytes x1), on large records only.
- **`src/snapshot/snapshot.cc`.**
  - File-scope `std::atomic<uint64_t> g_snapshot_room_waiters[2]`.
  - `post_chunk` refusal path: if the bit is already set, return. Otherwise `fetch_or` the bit
    (seq_cst), fence, then `producer_free_slots()` plus one retry.
  - `writer_pass`: a `wake_refused(producer)` lambda (fence, relaxed peek, `fetch_and` claim,
    `msg_to`) runs after any pop in the take loop and in the drain-all backstop.
  - The same `!budget &&` guard on the notify-bit re-set.
- **`src/cmd/scatter_engine.inc`, `prepare_debug_loadaof`.** The writer-thread loop is now
  `runtime_pump` + `yield`. It is bounded by 5 s and `failed()`, then returns
  `ERR timed out flushing AOF before reload`, the same as the existing off-writer branch.
- **`Makefile`.** Twelve `large-unit-insns` pins are re-derived. The table lists PRE, then POST:

  | Unit | src | db0 |
  | --- | --- | --- |
  | main | 152477 -> 152485 | 150687 -> 150695 |
  | genthread | 134842 -> 134874 | 135506 -> 135538 |
  | rl2s | 168119 -> 168151 | 169904 -> 169928 |
  | reorder | 152568 -> 152600 | 153552 -> 153584 |
  | aof | 38653 -> 38714 | 40597 -> 40650 |
  | snapshot | 16744 -> 16899 | 16184 -> 16339 |

  Initial IPA unit growth was +8 for main, +32 for genthread/rl2s/reorder, +53 for aof and +131
  for snapshot; xshard did not grow. Each pin is the compile-only scan point with the fewest
  changed bodies (`docs/iowake/budgets/{initial,selected}.json`).

No struct layout changed. `sizeof(SnapshotManager)` stays 816 and `sizeof(Server)` stays 141888,
with every Server member offset identical (the F9 waiter word was deliberately kept at file
scope). No hook, knob or test-only code is in the production source. Build warnings are the
same 55 as PRE's full build.

### Changed hot bodies (`tools/iowake_identity.py`, `docs/iowake/identity/changed.json`)

Normalized function-body comparison of all 128 production objects (20,888 functions), PRE vs
POST. Only 52 hot bodies changed, and all are the F5 edit itself, in the `HasTls=true`
instantiations:

- `IoLoop::flush_ready<true, ...>`:
  - main.o: 2 in src, 2 in db0;
  - genthread.o: 8 in src, 8 in db0;
  - rl2s.o: 8 in src, 8 in db0.
- `IoLoop::r7_flush_ready<true, ...>`, reorder.o: 8 in src, 8 in db0.

Every other selected hot body is PRE-identical: every `HasTls=false` `flush_ready`,
`parse_and_dispatch`, `run_loop`, `drive_tls`, `on_cqe`, the executor `execute`/`drain_tasks`/sweep
bodies, `cmd_get/set/mget/mset` and the FlatStore insert/erase/find/lookup paths. A server
without a TLS port runs no changed IO body. A TLS server's plain connections run the changed body,
but only the TLS branch changed.

Cold bodies:
- Intended: `AofManager::writer_pass`/`drain_producer`, `AofProducer::emit`/`record_bytes`,
  `submit_large_frame_wake` (added), `SnapshotManager::post_chunk`/`writer_pass` (plus its new
  lambda), and `prepare_debug_loadaof`.
- Compiler spillover in unchanged source:
  - xshard.o: `notify_reserve_chain`; two `prepare_sort_deref` lambdas;
    `FlatStore::scan<xshard_execute lambda>`; `multi_owner_pass_entry_impl<false>` (register
    allocation deep in the retry body only; its no-work entry path is identical).
  - db0 reorder.o: `atomic_prepare_capacity_read_local`, `run_fused_server_reordered` and its
    thread entry (cold-section offsets and padding).
  - db0 rl2s.o: `flip_control_pass<true>`.
  - db0 aof.o: `manifest_name`.
  - COMDAT copies of `kvobj_external_bytes` in genthread.o and snapshot.o (switch-case block
    order).

### Zero cost: command-scope instruction counts (`tools/iowake_counts.py`, `docs/iowake/counts`)

Serverless censuses link each arm's production objects to the existing owner/scatter fixture
(`tests/wave11_scope.cc`) and ptrace-count executed server instructions. The run covers
GET/SET/INCR/MGET/MSET x 1s/2s x batch 1/32 x atomic 0/1 x normal/db0.

Result: **80/80 comparisons with zero delta, and per-function totals are equal in all 80**
(`docs/iowake/counts/comparison.json`).
- The PRE census ran on the PRE export build, whose `.text` is byte-identical to the PRE arm.
- The POST census ran on `e78e055e`, whose `.text` is byte-identical to the delivered POST
  `6a091192`. The later commit changed only an R7 comment and the embedded git sha.

This is instruction accounting, not a cycles, IPC or throughput result.

### Row delta

The new collection loop is at `tests/gate.sh:7350`, and the quick-tier exit is at `:7400`. It adds
four rows, one per item, all before the quick exit: **DQ=+4, DF=+4**. `EXPECT_QUICK` and
`EXPECT_FULL` were not edited. From 1177/1194 the maintainer sets **1181/1198**.

### Arms (`docs/iowake/arms.json`, `docs/iowake/SHA256SUMS`, `docs/iowake/pad-a.json`)

| Arm | Path | SHA-256 | `.text` |
| --- | --- | --- | --- |
| PRE (8be4f68323) | `/home/user/Projects/bins/iowake-pre-5ab6cada` | `5ab6cadad35c309510c9bf45e458aeb0808823a33a5f8f3954535c6b298947d9` | 9,230,039 at 0x2dcd0 |
| POST (06b042739d) | `/home/user/Projects/bins/iowake-post-6a091192` | `6a09119276a8769a62ca289123ecc24aba25fa22038a3701b76aa801f94c7191` | 9,231,959 at 0x2dcd0 (+1,920) |
| PAD-A | `/home/user/Projects/bins/iowake-pad-3739f31f` | `3739f31f3f790952910a02c871e480841a8b6d26046b4a473ef79a8c56155861` | 18,461,607 at 0x4fcd0 |
| POST-layout (PAD-A's exact sibling) | `/home/user/Projects/bins/iowake-postlayout-c955bc65` | `c955bc658d6a919980156a1acd84fc4df459d1ff4a283cd954604ccc102fdfac` | 18,461,607 at 0x4fcd0 |

**PAD-A is type A, a behaviour twin.** It is PRE behaviour in the exact POST-layout common image
(`tools/iowake_pad.py`, copied from `tools/snapfix_pad.py`). That image links the POST objects
first and a symbol-isolated copy of the PRE objects second. PAD-A differs from POST-layout only
in main's 5-byte entry jump, and the two have identical sections and symbols. POST's `.text` grew
by 1,920 bytes, mostly from the re-derived inlining budgets. PAD-A controls layout for
POST-layout, not for the smaller release image, so measure the release null separately.

### Verification (all through `tests/gate.sh`'s job interface unless noted)

Each batch was a partial run on the CPUs given at the top: `tests/gate.sh iteration --ports 23400-23499
--server-cores 64-79 --load-cores 80-95`, with `GATE_ONLY_JOBS` and `GATE_PROOF_NO_RATES=1`. Ledgers
are in `docs/iowake/gate/` and every count includes prerequisites.

| Selection | Environment | Result |
| --- | --- | --- |
| The 4 iowake jobs, `--candidate-binary` PRE | default | 1 ok (release), **4 FAIL** (all four witnesses; per-leg receipts in `witnesses/pre-5ab6cada.json`) |
| Main batch, 66 jobs (see note 1) | default (uring, split) | **304 ok, 0 FAIL** |
| Engine batch, 24 jobs (see note 2) | `GATE_NET_IO=epoll GATE_PROOF_NET_IO=epoll` | **119 ok, 0 FAIL** |
| Fused batch: tls, aof-epoll/uring, snapshot-epoll/uring, debug-0/1, aof_frame | `GATE_TXN_FUSED=1` | **195 ok, 0 FAIL** |
| Fused epoll batch: tls, debug-0/1, aof_frame, aoforder | `GATE_TXN_FUSED=1`, epoll | **58 ok, 0 FAIL** |
| `redis_tcl` (checked-in manifest, 2s and 1s) | default | **3 ok, 0 FAIL**: 57 rows per mode, 1,949 passing assertions per mode, 0 row errors (the 5 named setup diagnostics are accounted by the manifest) |
| `redis_tcl` AOF/TLS units (see note 3), PRE and POST | `GATE_TCL_ONLY_FILES` | PRE and POST identical: 0 pass, 0 fail, 10 skipped |
| `tests/differ_gate.sh`, standalone | uring, seeds 7 19 20 23 22 44 | **pass=569, fail=0** (21m21s; 232 of 245 commands diffed) |
| `tests/differ_gate.sh`, standalone | epoll, seeds 7 19 20 23 22 45 | **pass=569, fail=0** (21m15s; 232 of 245 commands diffed) |
| `python3 tests/gates_test.py` | 72-79,88-95 | **79 tests OK** |
| `make all` + every `job_production_units` target, then `make -q` (see note 4) | | all up to date (rc 0) |
| `tests/r7shadow_sync.py` + `r7shadow_sync_test.py` | | envelopes current |

Notes:
1. The main batch covered:
   - the 4 iowake jobs;
   - TLS: tls, netfix_tls, flipfix7_tls, and netfix2 tls-watch/exclusive/fds/tls-idle/boot;
   - AOF and persistence: aof-epoll/uring, aof_frame, aoforder, notify_aof, persistfmt,
     persistfmt_aof_error, wave15_aof_participants/large, infofix_compat-loadaof;
   - snapshot/BGSAVE: snapshot-epoll/uring, snapfix shutdown/bgsave_script/bgsave_exec,
     snapfix2_tables, persistfix2 x4, persistfix_units;
   - DEBUG: debug-0/1;
   - IO loop: iofix x4, netio-1s/2s, wb_mixed, slotless, ntfix_input, netcap, the 12 respresume
     jobs, reorder_sync/engagement/identity, wave15 idle/rebind/flip_eof;
   - source_identity.
2. The engine batch reran every job above that takes its engine from the environment rather
   than enumerating both itself.
3. The units were integration/aof, aof-multi-part, aof-race, unit/aofrw and unit/tls. Upstream
   tags the AOF tests "Not supported on external server", and the harness has no TLS mode. They
   exist, but none has a runnable assertion here.
4. `make -q` covered all 61 targets, blockfix-cost, blockfix2 and both mdbqsbr twin arms. To
   keep `build/` under 15 GB, the regenerable control and twin builds (wb-rule/lbplanner controls,
   mdbqsbr twins, racefix-climon objects) and the lane's scratch images were deleted afterwards. A
   later gate run rebuilds them.

The wave15 AOF deadlock witnesses (`wave15_aof_participants`, `wave15_aof_large`, including its
writer-owner scenario) pass in the main batch.

### NOT RUN

- **Reserved to the maintainer:** benchmarks, merit or throughput cells, ABBA, NIC cells and the
  full `iteration`/`push` gate. Every gate run here was a partial `GATE_ONLY_JOBS` run with
  `GATE_PROOF_NO_RATES=1`, so no EXPECT tally or receipt was produced.
- **`eoffix_aof`:** a private partial job that needs `EOFFIX_AOF_DIRECTORY` native arms this lane
  did not build. Its subject (EOF QSBR) is untouched.
- **Redis Tcl `unit/tls`:** the Tcl harness (`tests/redis_tcl.py`) has no TLS mode. `$::tls` is
  false, so the unit has no runnable assertion. TLS is covered by the gate's TLS rows and
  `iowake-tls`.
- **System-level throttled storage for F9:** not needed. The single-owner 1s geometry opens the
  window deterministically on the box's normal disk.

### Adjacent findings (observed while building the witnesses; not fixed)

1. **DEBUG LOADAOF racing another connection's in-flight large record (DEBUG-only).** This is
   pre-existing and reproduces on PRE epoll as well as on POST.
   - With a 3M-element RPUSH post-image (230 frames) in flight on another connection, DEBUG
     LOADAOF returns `ERR Error trying to load the AOF files, check server logs.` In a direct probe
     this happened in all 4 POST legs and on PRE epoll; PRE io_uring hangs (F13) instead.
     `pending_chunks() == 0` can hold between two frames of an open large record, so the reload
     reads a record whose LargeEnd is not yet written.
   - With a 200k-field HSET in flight, LOADAOF returns OK, but the HSET acknowledged with reply 1
     is absent afterwards. The reload plan is built in `prepare_debug_loadaof`, before the owner
     finishes the write.
   - Redis serializes DEBUG LOADAOF with every command, so neither happens there.
   - Smallest proposal: wait while a large record is open on the writer branch too, using
     `stream_owner_.large_token()`, the predicate the rewrite mark uses at aof.cc:1805. The
     off-writer branch would need an atomic mirror of that state. Ordering the reload after
     in-flight owner work is a protocol change for the owner to decide. The F13 witness therefore
     uses pipelined small writes, so the drain itself is exact.
2. **The F4 audit fix alone does not cover io_uring.** With take-then-drain only, an owner's 0->1
   wake was still only *prepared* as a msg_ring SQE on its ring. It left at the owner's next submit,
   which is either when its channel filled or when its command ended. Measured on that interim
   build, a 200k-field HSET record was still written in 2-4 steps, with 33-44 ms gaps under
   io_uring, identical to PRE. Hence the `submit_large_frame_wake` in F4.
3. **A narrow lost-wake window in both persistence writers, closed as part of F4 and F9.**
   `drain_producer`, and the snapshot writer's equivalent, re-set a producer's notify bit whenever
   `depth()` was non-zero after the drain. A post landing between the last empty `recv` and that
   `depth()` check lost its 0->1 wake edge. If that happened in the writer's pre-park sweep, the
   writer slept until its timeout. The bit is now re-set only when the drain stopped on budget.
4. **The F9 2s geometry on this box.** The executor's 2,048-pass spin before parking usually
   outlasts the writer's lag. The missing wake therefore shows only partly in 2s/uring (PRE
   242-344 MiB/s against POST ~550-597 MiB/s) and not at all in 2s/epoll. The gate row
   discriminates through its 1s legs.

### Maintainer measurement request

This lane claims no throughput change except the F9 capture bound. Use the gate's own
quiet-box instrument on the unchanged standard merit cells (`docs/iowake/merit.cells.txt`: the 14
generic cells plus 2s GET/SET at p1 and p32, h53/h54/h21/h22). Use identical geometry, offered
load and keyspace for every arm. Run:
- **PRE vs POST** for the release verdict;
- **POST-layout vs PAD-A** (type A) for the layout-controlled behaviour null;
- **PRE vs PAD-A** to expose the common-image placement effect.

Record rate at matched offered load, plus cycles/op, instructions/op and IPC per cell and arm. Do
not average away a failed cell.

The only changed hot bodies are the TLS-capable IO bodies, so a TLS server sanity pair is useful:
- a TLS 1.2 kTLS GET p32 cell and a TLS 1.3 GET p32 cell on a `--tls-port` boot, PRE vs POST.

On TLS 1.3, POST is expected to differ by design: replies are no longer held for up to 50 ms. No
claim is made.
