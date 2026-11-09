## readability-p2fix

Branch `cx-readability-p2fix`, base `6cd261fe71dc973721fca44452bed2e9ffc5dd70`.
Comments only in A7-A10 sources; no performance claim or measurement request.
Audit row numbers refer to the Findings tables in
`/home/user/Projects/round6-read/readability-a{7,8,9,10}-comment-audit.md`.
Evidence locations below refer to the **base**, so later comment insertions do not
invalidate them. The report is the only non-source deliverable.

### Finding ledger

| Audit file | Row | Verdict and independently checked evidence |
| --- | ---: | --- |
| readability-a7-comment-audit.md | 1 | **fixed** in `src/core/fliplisten.cc`: `home` is the dense native IO id, with slot `3*home+kind-index`, native tags/flags and split close responsibility (`:80`, `:598-605`, `:964-968`). **outside A7-A10 source scope:** `docs/glossary/readability-a7.md:56` remains unchanged and needs the same correction. |
| readability-a7-comment-audit.md | 2 | **fixed**: half-prefix applies immediately to deep pipelines and after counted small-pipeline deferrals. Also preserved the base's `complete_visits == 0` complete-prefix exception, absent from the suggestion (`src/core/wb_rule.h:144-174`). |
| readability-a7-comment-audit.md | 3 | **fixed**: `within_error` clears move but does not set `visited`; sampling therefore continues to the cap unless externally bound (`src/core/flipctl.cc:910-978`). |
| readability-a7-comment-audit.md | 4 | **fixed**: outcome-loop reference now names the unnumbered header and `model_margin_` (`src/core/flip_policy.h:13`, `src/core/flipctl.h:482`). |
| readability-a7-comment-audit.md | 5 | **fixed**: callers must fence Done before read-first ReadyMask::set, which can return without an RMW (`src/core/signal.h:257-261`, `src/core/ex_loop.h:2971-2984`, `src/cmd/blocking.inc:453-459`). |
| readability-a7-comment-audit.md | 6 | **fixed**: the shared search also serves production `key-lb-damping 0` (`src/core/lbplanner.cc:341-350`, `:411`). |
| readability-a7-comment-audit.md | 7 | **fixed** in all six source headers: restored cold-path exclusions, qualifying weighted search and including listener boot/shutdown lifecycle callers (`src/core/io_loop.h:1060`, `:1224`, `:2305`, `:3672`; `src/cmd/blocking.inc:1854`; `src/core/server.h:1223`, `:1346`; `src/core/fliplisten.cc:581`, `:954`). |
| readability-a7-comment-audit.md | 8 | **fixed**: only ClientPrepare can set the session-preserving hold after both drains; LB uses the non-hold transfer path (`src/core/io_loop.h:377`, `:408-420`, `:2537`). |
| readability-a7-comment-audit.md | 9 | **fixed**: kept the release-store/no-ACK limitation and restored the hazard of mistaking a delayed disarm edge for a workload shift (`src/core/flipctl.cc:1349-1358`; owners refresh sampling on their passes). |
| readability-a7-comment-audit.md | 10 | **fixed**: elected save-cron IO drains before saving and after late failed-save notifications; SHUTDOWN ABORT is the cancellation exception (`src/core/io_loop.h:1156-1162`, `src/cmd/server_tail.cc:288-309`). |
| readability-a8-comment-audit.md | 1 | **fixed**: logical clear callers are FLUSH via the WATCH helper, plus DEBUG RELOAD/LOADAOF (`src/cmd/scatter_engine.inc:3617-3651`, `src/cmd/multi.inc:4101-4121`). |
| readability-a8-comment-audit.md | 2 | **fixed**: the size assertion pins FlatStore's 944-byte share of Shard's gate geometry; atomic_torn is not the size checker (`src/store/flatstore.h:3144`, `src/core/shard.h:593`). |
| readability-a8-comment-audit.md | 3 | **fixed**: restored one live slot per resident key between owner operations and the short rehash duplicate-word window; find/erase/size/SCAN rely on uniqueness (`src/store/flatstore.h:999`, `:1253-1266`, `:1849-1861`; `src/store/flatstore_impl.h:673-674`, `:1010-1014`). |
| readability-a8-comment-audit.md | 4 | **fixed**: restored FIFO posting/draining and parked same-key predecessor ordering as the epoch-repair premise, scoped to each key (`src/core/ex_loop.h:2793-2814`, `src/store/flatstore_atomic.inc:2093-2118`). |
| readability-a8-comment-audit.md | 5 | **fixed**: every in-place found-object mutation needs a size bracket or explicit delta (`src/store/flatstore.h:1243-1251`, `src/store/flatstore_impl.h:932-935`). |
| readability-a8-comment-audit.md | 6 | **fixed** for this base: cleanup floor covers registered scatter/transaction snapshots; unregistered plain-read cuts do not hold it back. Names the supplied S1 analysis without importing its future fix (`src/core/server.h:3101-3123`, `src/cmd/atomics_glue.inc:459-512`, `src/cmd/multi.inc:2742`). |
| readability-a8-comment-audit.md | 7 | **fixed** at all four sites: predecessors, collapse contract/prefix and range readiness now identify registered snapshots, strict floor versus inclusive cutoff, and plain-read exclusion (`src/store/flatstore_atomic.inc:1830-1841`, `src/store/flush.cc:76-93`). Aborted entries bypass those bounds. |
| readability-a8-comment-audit.md | 8 | **fixed**: own-child wait is a self-deadlock that hangs EXEC (`src/store/flatstore_atomic.inc:437-451`, `src/core/ex_execute.inc:44-48`). |
| readability-a8-comment-audit.md | 9 | **fixed**: header locates private definitions in flatstore_impl.h after the class (`src/store/flatstore.h:3085`, `src/store/flatstore_impl.h:1-9`). |
| readability-a8-comment-audit.md | 10 | **fixed**: default Makefile builds, including release, omit NDEBUG and retain injection/assertions; custom flags can change that (`Makefile:28`, `src/base/tomo_assert.h:24-30`). |
| readability-a8-comment-audit.md | 11 | **fixed**: hash seed is chosen before workers start, then read-only (`src/main.cc:203`, `:287`, `:293`, `:327`, `:400`). |
| readability-a8-comment-audit.md | 12 | **fixed**: restored the 8-slot/70% occupancy rationale (about 41% after doubling; under 63% after same-size migration) for the defensive full-drain backstop (`src/store/flatstore.h:149-174`, `:262`, `:320-352`). |
| readability-a8-comment-audit.md | 13 | **fixed**: retained ignored deadline parameter's GCC call-shape/inlining rationale (`src/store/flatstore.h:150`, `:363`; lane decision log). |
| readability-a8-comment-audit.md | 14 | **fixed**: restored Redis dictScan counterpart to reverse-binary traversal (`src/store/flatstore.h:509-514`). |
| readability-a8-comment-audit.md | 15 | **fixed**: separate state bytes avoid reserving any 64-bit hash as a sentinel (`src/store/flatstore.h:266-270`, `:363-404`). |
| readability-a8-comment-audit.md | 16 | **fixed**: retained clamp/count behavior and restored deliberate non-aborting policy for accounting underflow (`src/store/flatstore_atomic.inc:566-573`, `tests/bplus.py:410-413`). |
| readability-a8-comment-audit.md | 17 | **fixed**: conservative script restart is invisible to clients; no bounded-retry claim was restored (`src/store/flatstore_atomic.inc:341-362`). |
| readability-a8-comment-audit.md | 18 | **fixed**: shard handoff moves no slots/objects and rebinds the armed retire sink only at a quiescent ownership edge (`src/store/flatstore.h:770-779`). |
| readability-a9-comment-audit.md | 1 | **fixed**: handoff requires an empty source deferred queue before rebinding; reclaim consults the store's current sink (`src/core/ex_loop.h:1570-1578`, `src/core/server.h:2156-2166`, `src/store/flatstore_impl.h:794-798`). **outside source scope:** `docs/decisions/readability-a9.md:147` retains the wrong queued-retirement claim. |
| readability-a9-comment-audit.md | 2 | **fixed**: documented coordinator retirement of a disabled idle clock after sink rebind, its quiescence premise and debug-owner rejection (`src/core/server.h:2325-2338`, `src/store/flatstore.h:1555-1570`, `src/core/read_local.h:432-447`). No behavioral fix attempted. |
| readability-a9-comment-audit.md | 3 | **fixed**: commit_raw callers are IO retirement's direct/coded commits, directly or through commit_fill; joined shutdown can also retire after issuer cancellation (`src/core/shutdown.cc:169-175`). This qualifies the audit's absolute IO-only wording. Done publication orders worker bytes (`src/net/wb.h:45-47`, `:314`, `:808-810`, `src/net/conn.h:480-482`). **outside source scope:** `docs/decisions/readability-a9.md:67` and `MEASURE-REQUEST-readability-a9.md:183` remain unchanged. |
| readability-a9-comment-audit.md | 4 | **fixed**: all three measured memcmp exceptions are named with per-site rationale (`src/store/flatstore_impl.h:50-53`, `:549`, `:755-759`); namespace/length identity remains shared. |
| readability-a9-comment-audit.md | 5 | **fixed**: distinguished SORT ALPHA locale collation without STORE from binary numeric ties/ALPHA STORE (`src/cmd/t_sort.cc:172-195`). |
| readability-a9-comment-audit.md | 6 | **fixed**: scratch keys must borrow stable record/ScatterState storage, never values retired during ongoing index probes (`src/store/flush.cc:294-328`, `src/store/flatstore_atomic.inc:1228-1239`). |
| readability-a9-comment-audit.md | 7 | **fixed**: restored cleanup-masks-the-bug warning and multires detector at gate geometry; cites existing historical measurements without claiming a new run (`src/store/flush.cc:366-387`, `docs/decisions/readability-a9.md:183-191`). |
| readability-a9-comment-audit.md | 8 | **fixed**: restored missed-wake safety-net purpose and warning that 50 ms can hide missed wakes, retaining the distinction between requested wait and scheduling delay (`src/base/park_net.h:1-13`, `:25-29`). |
| readability-a9-comment-audit.md | 9 | **fixed**: factory now states non-throwing allocation failure/partial cleanup; qualified separate-block claim for empty forced-raw strings (`src/store/kvobj.h:880-922`). |
| readability-a9-comment-audit.md | 10 | **fixed**: restored modulo-zero crash hazard and optional-index guards; splice recalculation is due to ensure_space moving begin_ (`src/store/typeval.h:211-228`, `:373-377`). |
| readability-a9-comment-audit.md | 11 | **fixed**: embedded storage must retain Compact's exact ULEB128-length/payload codec (`src/store/kvobj.h:597-634`, `:701-711`, `:996-997`; `src/store/typeval.h:365-371`). |
| readability-a9-comment-audit.md | 12 | **fixed**: named the five attach points, Compact/size condition, ownership outcomes and wrapper-only field-TTL loss (`src/store/kvobj.h:1030-1099`, `src/cmd/t_hash.cc:1694-1704`). |
| readability-a9-comment-audit.md | 13 | **fixed**: restored exclusion from GET/SET dispatch; numeric users are specialized command parsers and RESP double replies (`src/base/numeric.h:20`, command includers). |
| readability-a9-comment-audit.md | 14 | **fixed**: restored copy-or-move, never shared ownership between keys, and refcount cache-line cost; retained permitted reader/send borrows (`src/store/kvobj.h:1105-1107`). |
| readability-a9-comment-audit.md | 15 | **fixed** in Compact and CompactView: logical() is the only sanctioned conversion from Entry.offset (`src/store/typeval.h:123-127`, `src/store/kvobj.h:358-361`, `:430-432`). |
| readability-a9-comment-audit.md | 16 | **fixed with narrower wording**: restored no-extra-cache-line obligation for the no-record/no-intent check. Did not claim atomic_has_records is literally the only read: find also reads live and active MVCC uses more state (`src/store/flatstore_atomic.inc:60-63`, `src/store/flatstore.h:1253-1266`). |
| readability-a9-comment-audit.md | 17 | **fixed**: UnitRef prefix preserves AtomicScriptIntent offsets for shared matching (`src/store/atomic_mvcc.h:93-120`, `src/store/flatstore_atomic.inc:200-247`). |
| readability-a9-comment-audit.md | 18 | **fixed**: arena binding failure is ignored by production callers and loses isolation; retained no rollback of an already-created arena (`src/base/alloc.h:85-99`, worker-startup callers). |
| readability-a9-comment-audit.md | 19 | **fixed**: restored LB thrash hazard when migration's cache refill is treated as free (`src/base/topology.h:18-22`, shard residency/foreign-work accounting). |
| readability-a9-comment-audit.md | 20 | **fixed**: class has no demotion operation; list handler demotes by assigning CompactValue{} then replace_compact, requiring valid default counters (`src/cmd/t_list.cc:127-139`). |
| readability-a9-comment-audit.md | 21 | **fixed**: steady-state fused SET prebuild can allocate for a foreign owner; included direct/deferred remote free and teardown paths (`src/cmd/l4prebuild.cc:142-153`, `src/core/io_loop.h:4569`). |
| readability-a9-comment-audit.md | 22 | **fixed**: dtoa path includes integral doubles outside +/-2^62 (`src/base/numeric.h:315-336`). |
| readability-a9-comment-audit.md | 23 | **fixed**: db0 header-source branch preserves code generation, with TTL-adjusted bytes equivalent to recomputation (`src/store/kvobj.h:782-800`, commit `71c7b998d5`). |
| readability-a9-comment-audit.md | 24 | **fixed**: streams also use embedded storage (`src/store/kvobj.h:1090-1097`). |
| readability-a9-comment-audit.md | 25 | **fixed**: group intent destruction finishes both owner-local claim sets before release-decrementing watch_refs (`src/cmd/txn_group.inc:573-587`). |
| readability-a9-comment-audit.md | 26 | **fixed**: grouped count has fused install updates plus standalone range increments and unlink decrements (`src/store/atomic_mvcc.h:166-175`, `src/store/flush.cc:39-40`, `src/store/flatstore_atomic.inc:1277`). |
| readability-a9-comment-audit.md | 27 | **fixed**: an invisible range-only match can return the physical value with physical=false; only value is consumed (`src/store/flush.cc:426-462`, `:523`, `src/store/flatstore_atomic.inc:1307`). |
| readability-a9-comment-audit.md | 28 | **fixed**: numeric API header names command handlers and RESP builders, not direct persistence users (source includer/caller search). |
| readability-a9-comment-audit.md | 29 | **fixed**: alloc header names its actual users; SmallBuf calls malloc itself (`src/base/slice.h:267-274`, source include search). |
| readability-a9-comment-audit.md | 30 | **fixed**: distinguished shift=8/256-second buckets from five-bit masked clock (`src/store/eviction.h:11-12`, `src/core/ex_loop.h:429`). |
| readability-a9-comment-audit.md | 31 | **fixed**: discover falls back to per-CPU domains for unreadable L3 sysfs and fails for affinity/empty-mask cases; other discovery methods have different failures (`src/base/topology.h:104-137`). |
| readability-a9-comment-audit.md | 32 | **fixed**: ThreadCtx latches sched_getcpu after optional pinning; this need not be an assigned CPU (`src/core/thread.h:482-485`). |
| readability-a10-comment-audit.md | 1 | **fixed**: Client NO-TOUCH deliberately equals Op::kNoTouch bit 4; reset copies the flag byte and maxmemory execution reads the Op snapshot (`src/exec/op.h:99`, `:205`, `:475`, `src/core/ex_execute.inc:58`, `:121`). |
| readability-a10-comment-audit.md | 2 | **fixed** in conn.h and rob.h: Done-before-notify requires the executor epoch fence and safe_to_release recheck; close retains the corpse another loop iteration (`src/core/ex_execute.inc:283-290`, `src/core/io_loop.h:392-395`, `:5597-5635`). **outside source scope:** `docs/decisions/readability-a10.md:128-134` retains the incomplete fence list. |
| readability-a10-comment-audit.md | 3 | **fixed**: receive realloc preserves the old buffer; SmallBuf/SegmentQueue output growth malloc is unchecked (`src/net/conn.h:403-408`, `:253-263`, `src/base/slice.h:267-274`). |
| readability-a10-comment-audit.md | 4 | **fixed**: unarmed returns true, but an armed overflow generation refuses precise-write marking until retirement (`src/net/rob.h:528-533`, `src/core/read_local_parse.inc:119-120`). |
| readability-a10-comment-audit.md | 5 | **fixed**: parsed argv is immutable because owner execution and read-local conflict scans can read it concurrently; alternative argv requires a separate Op (`src/net/rob.h:518-520`, `:622-643`, `src/exec/op.h:8`). |
| readability-a10-comment-audit.md | 6 | **fixed**: restored exclusive worker-access list and IO single-writer rule for remaining Client scalars; connection facts travel in the Op snapshot (`src/net/conn.h:929-936`, `src/core/ex_execute.inc:58`, `:121`). |
| readability-a10-comment-audit.md | 7 | **fixed**: restored all three provenance/licence comment lines byte-for-byte from `git show 7595a6705a:src/net/resp.h`, naming redis-7.2 / valkey (BSD-3) and the RSALv2/SSPLv1 Redis 8.6.2 fork. **outside source scope:** `docs/decisions/readability-a10.md:34-37` was not edited; this report records the restoration. |
| readability-a10-comment-audit.md | 8 | **fixed**: after owners complete, notify_multi_before may mutate only IO-owned route bits (`src/cmd/clientcompat.cc:210-216`, `src/cmd/multi.inc:2997-3000`). |
| readability-a10-comment-audit.md | 9 | **fixed**: restored warning that pure GET/SET cells miss routing-line regression paid by atomic/cross-shard work (`src/net/conn.h:958-979`). |
| readability-a10-comment-audit.md | 10 | **fixed**: live-socket probe is a deliberate stricter policy under the single-instance release rule; retained both probe/unlink and TCP boot TOCTOU limitations (`src/net/unix_listener.h:59-83`). |
| readability-a10-comment-audit.md | 11 | **fixed**: restored peer-abort classification rationale and timing-dependent send_errors==0 hazard; both plain/kTLS and memory-BIO completions preserve this split (`src/net/wb.h:568-578`, TLS completion peer-abort branch). |
| readability-a10-comment-audit.md | 12 | **fixed**: reclamation belongs to cold cron; forget also runs at close/migration, not request retirement (`src/core/io_loop.h:1884, :5383, :5593`). |
| readability-a10-comment-audit.md | 13 | **fixed**: false is not a teardown signal; TLS callers inspect failed(), while return value describes progress and also covers no-work/WANT/SQE-shortage cases (`src/net/wb.h:461-551`, `src/core/wb_rule.h:237`). |
| readability-a10-comment-audit.md | 14 | **fixed**: assertion pins TLS offset 1980; no assertion pins last_interaction_s_ at offset 12 (`src/net/conn.h:838-839`, `:954-955`). |
| readability-a10-comment-audit.md | 15 | **fixed**: coded replies apply to Fused=true instantiations in 1s and 2s SplitLocal, not plain 2s (`src/core/rl2s.cc:88-95`, `src/core/io_loop.h:5097`). |
| readability-a10-comment-audit.md | 16 | **fixed**: direct rob.h includers are conn.h and core/thread.h, for ReadLocalArmStats (source include search). |
| readability-a10-comment-audit.md | 17 | **fixed**: op_materialise_code uses the table during retirement for segment staging/borrowed MGET flush (`src/net/wb.h:290`, `:306`, `:783`, `:790`, `src/cmd/xshard_commands.inc:1983`). |

FACT LEDGER: replacements retain ownership, ordering, lifetime, failure and caller
obligations. Added qualifications follow this base's code rather than copying
suggested replacements blindly. Removed wording is either the specific false
claim named in its row or retained in the replacement with a precise scope.

All 77 source findings fixed; no finding row rejected or wholly outside A7-A10.
Five rows also mention documentation outside the allowed source-edit scope, left
unchanged as listed above. Suggestions were qualified against the actual base,
including zero-deferral writeback, per-key epoch ordering, empty-string allocation,
joined-shutdown retirement and no-record/no-intent cache-line scope.
No gate rows added or retired: EXPECT_QUICK / EXPECT_FULL remain unchanged.

### Counts and fact retention

| Audit | WRONG | DROPPED-INVARIANT | DROPPED-FACT | MISLEADING | Fixed source rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| A7 | 1 | 0 | 4 | 5 | 10 |
| A8 | 2 | 3 | 9 | 4 | 18 |
| A9 | 5 | 1 | 13 | 13 | 32 |
| A10 | 4 | 2 | 6 | 5 | 17 |
| Total | 12 | 6 | 32 | 27 | 77 |

34 source files changed, all owned by A7-A10 under
`/home/user/Projects/calib/readability-partition.py`; no code tokens, literal bytes,
includes, definition order, layouts or tool-marker bytes/boundaries changed.
The report is the only other changed file. No changed file exceeds 1 MB.

Comparing comment groups at unchanged token boundaries gives 75 rewritten groups,
one moved group (hash-seed startup note), and one new group (string factory
failure contract). Only two rewritten groups became shorter after whitespace
normalization. Their fact ledger, including the moved note, is:

| Base comment | Facts retained or corrected |
| --- | --- |
| `src/base/slice.h:144` | Length-first rejection and one-register comparison retained; inline equality retained; store/atomic/script callers retained with all three measured memcmp exceptions named; namespace/length identity and equal answers retained. Removed only the false one-exception/all-lookups claim. |
| `src/net/conn.h:838` | IO ownership, out-of-line TLS, four-byte slot, offset 1980 and its assertion retained; offset 12's last_interaction_s_ retained. Removed only the false assertion coverage for offset 12. |
| `src/store/flatstore.h:428` | Startup and persistence seed selection retained in a preceding comment; strengthened to before worker creation/read-only afterwards. Code declaration is unchanged. |

### Verification

Final source commit: `d7a468433f`. Proof commands run on CPUs 64-75 with
`LC_ALL=C`. Both builds pin `TOMO_INFO_GIT_SHA1=5c363128` and
`TOMO_INFO_GIT_DIRTY=0`.

```sh
git worktree add --detach /home/user/Projects/cx-readability-p2fix-pre 6cd261fe7
taskset -c 64-75 env LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0 \
  make -j12 -C /home/user/Projects/cx-readability-p2fix-pre all
taskset -c 64-75 env LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0 make -j12 all
taskset -c 64-75 env LC_ALL=C /home/user/Projects/calib/binary-neutral.sh \
  /home/user/Projects/cx-readability-p2fix-pre/build/tomokv build/tomokv
```

Comparator output, verbatim:

```text
IDENTICAL (11167504 bytes after stripping)
```

The comparator removes debug/symbol tables and the GNU build-ID note, then
compares all remaining bytes. This is the required production identity proof;
raw debug-bearing ELF identity is not claimed. Base build and candidate build
both succeeded. `make -q all` returned 0 after the build; plain `make -q` also
returned 0 after the final formatting and gate jobs. A base binary copy is
retained, untracked, at `build/readability-p2fix/base-tomokv`. The helper worktree was removed with
`git worktree remove /home/user/Projects/cx-readability-p2fix-pre`.

The exact three-line RESP provenance/licence note was also checked against
`git show 7595a6705a:src/net/resp.h` after formatting.

Token proof uses `tools/source_tokens.py.lex` without alias normalization on every
edited source file, against `git show 6cd261fe7:<file>`. Literal token streams
are separately compared via `LEXER`; every TOMO_TOOL_ANCHOR/TOMO_TOOL_BIND comment
is compared byte-for-byte at its original preprocessing-token boundary.

| Lane | Edited files | Identical tokens | Identical literals | Unchanged markers |
| --- | ---: | ---: | ---: | ---: |
| A7 | 12 | 37,148 | 142 | 14 |
| A8 | 3 | 35,239 | 26 | 3 |
| A9 | 12 | 29,343 | 132 | 8 |
| A10 | 7 | 26,117 | 196 | 0 |
| Total | 34 | 127,847 | 496 | 25 |

`make format` and `make format-check` passed before every commit, including the
final report commit, with pinned clang-format 18.1.8 (420 files). `tests/r7shadow_sync.py` check mode passed;
the generated R7 source stayed unchanged. `git diff --check` passed.

Selected gate jobs use the job interface, not the full quick gate. The initial
invocation was:

```sh
taskset -c 64-75 env LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0 \
  GATE_PROOF_NO_RATES=1 \
  GATE_ONLY_JOBS='source_identity reorder_sync reorder_identity abba_selftest' \
  GATE_LEDGER="$PWD/build/readability-p2fix/gate-ledger.txt" \
  tests/gate.sh quick --server-cores 64-73 --server-smt '' \
  --load-cores 74-75 --load-smt '' --ports 26800-26899
```

The selected set adds its release-build prerequisite. It uses one correctness
slot, eight server threads at 6:2 where applicable, and stays within CPUs 64-75.
`GATE_PROOF_NO_RATES=1` excludes rate measurements.

Resource correction: the initial `abba_selftest` passed functionally, but
`--ports` does not set the separate `GATE_TEST_PORT` used by socket fixtures in
`tests/abbagate.py:4729,4757`, `tests/gate_quiet.py:258` and
`tests/gates_test.py:1747`. That variable was unset, so these fixtures listened
on ephemeral ports outside the requested range. This first harness run is not
claimed as compliant proof. Only that affected job was rerun successfully with
`GATE_TEST_PORT=26899`; the source/R7 checks use no listening sockets.

The first partial invocation completed with:

```text
GATE(PARTIAL): 5 ok, 0 FAIL; no EXPECT tally, ABBA, NIC or receipt; ledger: /home/user/Projects/cx-readability-p2fix/build/readability-p2fix/gate-ledger.txt.partial
```

| Job | Result and evidence |
| --- | --- |
| `release` | PASS, release build and footprint locks. |
| `source_identity` | PASS, source identity lint across 61 C++ translation units in both database variants and 6 shared C translation units; 11 stable-assertion tests passed, including the directed-abort control. |
| `reorder_sync` | PASS, generated envelopes current; stale-envelope rejection, regeneration, 11 source-token tests and 62-site insertion-lottery controls passed. |
| `reorder_identity` | PASS, 352/352 strict no-op bodies identical; missing-symbol/parser/clone/callback/scan and changed-opcode controls all rejected. |
| `abba_selftest` | PASS in the fixed-port rerun: all 83 `tests/gates_test.py` tests and all 12 `tests/gate_ledger_fixture.py` label-fixture tests passed, as did the surrounding harness suites. The earlier functional pass is superseded for this job. |

Source/R7 artifacts: `build/gate-run.QXzxQh/jobs/`. Fixed-port rerun:

```sh
taskset -c 64-75 env LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0 \
  GATE_PROOF_NO_RATES=1 GATE_TEST_PORT=26899 GATE_ONLY_JOBS=abba_selftest \
  GATE_LEDGER="$PWD/build/readability-p2fix/gate-fixture-port-ledger.txt" \
  tests/gate.sh quick --server-cores 64-73 --server-smt '' \
  --load-cores 74-75 --load-smt '' --ports 26800-26898
```

This reserves 26899 for harness fixture listeners and the remaining requested
range for the gate interface. The harness uses negative controls and fake arms;
no performance benchmark is requested by this job. Its artifacts are in
`build/gate-run.mKfE6f/jobs/abba_selftest/`. The running `gates_test.py` process
was independently checked for `LC_ALL=C`, `GATE_TEST_PORT=26899` and CPU affinity
74-75; that check is saved in `build/readability-p2fix/fixture-resource-check.txt`.

Fixed-port rerun output, verbatim:

```text
GATE(PARTIAL): 1 ok, 0 FAIL; no EXPECT tally, ABBA, NIC or receipt; ledger: /home/user/Projects/cx-readability-p2fix/build/readability-p2fix/gate-fixture-port-ledger.txt.partial
```

All requested checks passed. The partial-job invocations do not claim a full gate
receipt, an EXPECT tally, or performance results.

Logs and per-file token hashes are retained under `build/readability-p2fix/`
(untracked). The worktree currently uses 5.6 GB, below the 30 GB limit.

### Not run and remaining scope

The full gate, live-server correctness batteries and benchmarks were NOT RUN;
they remain with the maintainer. No gate rows were added, removed or recounted.
No push was performed. The helper base worktree has been removed.

The source comments explicitly preserve this base's limitations: plain reads do
not register their cuts against cleanup, and the coordinator can reach idle-clock
retirement after sink rebinding while the debug sink still rejects non-owner
retirement. These are documented here, with no behavior change or imported S1 fix.
The five out-of-scope documentation occurrences remain listed in the finding
ledger for follow-up by their owners.
