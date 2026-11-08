## readability-a1

Baseline: `5c3631281815c1652b3894d1736840c8466a5015`. Branch `cx-readability-a1`; no push.

### Result and scope

Production remains binary-identical to `5c3631281`: **IDENTICAL (11,167,504 bytes after stripping)**. The 51 changed production files differ only in comments; their raw C++ preprocessing-token sequences equal PRE. `make all` produces one executable, `build/tomokv`. No server logic, layout, command, gate label or expected count was changed. No throughput measurement is requested or claimed.

A1 initially archived **468 unchanged files** (449 tools and 19 tests). That caller analysis was incomplete: the landing gate exposed two missing dynamic test paths, and A1b found an additional transitive tool import. A1b restores all three; **465 files** (448 tools and 17 tests) remain archived. The corrected caller proof is in the appended `readability-a1b` section. The source-tool matrix passes **52/52** on each of the current, fully formatted and renamed trees. The three shapes emit the same **313** normalized C++ outputs ([token manifest](docs/readability-a1/evidence/emitted-tokens.json)). Nine ELF controls pass and reject missing symbols on both the formatted and renamed fixtures; the separate linker-wrapper control also rejects a missing role in the DB-0 namespace.

The latest executions of the selected gate jobs contain **185 passing rows and zero failures** across 46 counted jobs, plus two build-only dependencies. The bounded lottery configuration row passes. The expiry lottery row remains **INSUFFICIENT**, and the historical blockfix rename builder and optional L4 fixture remain unusable; these are detailed below. This is a partial gate selection, not a full-gate certification.

### Hardening contract

`tools/source_tokens.py` supplies lexical token matching, balanced function extraction, unique replacement guards, stable identifier roles and ELF-name translation. Literal contents remain significant; comments, indentation, spacing and physical line numbers do not identify C++ operations. Explicit multi-site patches retain their reviewed exact counts (for example, the two shadow copies and six SplitLocal forwarding sites). Missing and ambiguous anchors are errors.

`TOMO_TOOL_FUNCTION`, `TOMO_TOOL_ANCHOR` and `TOMO_TOOL_BIND` comments are tool interfaces. The manifest checks their presence and uniqueness. Function/type/helper renames must preserve these comments; code snippets are translated through the bound identifiers. The rename proof changes **142 bound roles**, including both ordinary and R7 functions, classes, constants, diagnostics and PAD entry points. It does not establish unrestricted alpha-renaming of every unbound local/field name: an unbound identifier used literally in an anchor still needs a binding or a corresponding tool update. This is an explicit limit of the rename coverage, not a claim that arbitrary identifier edits are safe.

File moves must carry their Makefile prerequisites, per-object compilation budgets, marker-manifest paths and explicit caller paths in the same change. The per-object-rule test rejects a rule whose source disappeared. Files are not located by stale physical line numbers. This work does not automate arbitrary file moves.

The Makefile’s Climon mask control and L4 threshold extraction now use `tools/build_source_controls.py`, replacing unguarded `sed` commands. The Climon control checks the unique marked function and its parameter/shift expression; the threshold reader checks the marked integer macro. Make rejects an empty or invalid threshold before compilation.

Python battery controls now use AST statements selected by stable comments. The lottery driver rejects missing/duplicate section anchors and missing propagation-sleep calls. Symbol controls retain their exact expected inventories and opcode assertions. The length-prefixed symbol parser handles the digit at the end of `tomo_db0`; both namespace variants participate in the rename controls.

All PAD controls exercised here are existing **kind A behaviour twins**: PRE behaviour with the candidate's text size/layout. There is no new layout experiment or performance arm.

### Formatting and broken-anchor evidence

Installed with pip: **clang-format 18.1.8**. All **202** `.cc`, `.h` and `.inc` files under `src/` were formatted in disposable trees under `build/readability-a1/`. None of those formatted or renamed sources is committed.

```yaml
BasedOnStyle: Google
ColumnLimit: 100
SortIncludes: Never
BreakStringLiterals: false
InsertBraces: false
QualifierAlignment: Leave
```

| Fixture | Positive source cases | Broken-anchor rejections | Emitted token streams |
|---|---:|---:|---|
| Current source | 52/52 | 52/52 | 313 |
| Fully formatted source | 52/52 | 52/52 | same 313 hashes |
| Fully formatted + 142 role renames | 52/52 | 52/52 | same 313 hashes |

Each source case runs successfully, then removes a stable marker or corrupts a required token anchor and requires a nonzero exit. Positive output hashes are captured **before** the negative attempt can overwrite a copied tree. The 41 WB controls, six flush-header sites, four WBLAND controls, nine LB controls, three persistence controls and six still-applicable blockfix controls are included within those invocations. The lottery builder prepares all **62** insertion sites, and its additional test removes and duplicates the selected seam independently.

Before hardening, the frozen tools produced these results on the same source formatting transformation:

| Original tool invocation | Original source | Formatted source | Hardened formatted result |
|---|---|---|---|
| R7 sync | pass | fail | pass + broken-anchor rejection |
| reorder sync | pass | fail | pass + rejection |
| lottery preparation | fail: ambiguous existing anchor | fail | 62 sites + missing/duplicate rejection |
| command metadata coverage | pass | fail | pass + rejection |
| documentation drift | pass | fail | pass + rejection |
| LB planner PAD source proof | pass | fail | pass + rejection |
| LB oscillation PAD source proof | pass | fail | pass + rejection |
| storesize instrumentation | pass | pass | pass + rejection |
| SplitLocal emission | pass | fail | pass + rejection |

The original Makefile commands also returned zero after relevant names were changed: Climon emitted an unchanged header, and L4 emitted no threshold. Both replacements now fail on missing/duplicate anchors and pass the reformat/rename cases ([inline-command before evidence](docs/readability-a1/evidence/make-inline-before.json)).

The table’s original-tool comparison is a nine-invocation smoke slice; the complete AFTER matrix is the 52-case three-shape test above. [Exact commands and results](docs/readability-a1/evidence/source-and-symbols.json), [original-tool stdout/stderr](docs/readability-a1/evidence/before.json), and [the 142 rename roles](docs/readability-a1/evidence/rename-roles.json) are retained. The source and ELF proof drivers are `docs/readability-a1/prove_tools.py` and `prove_symbols.py`.

Additional checks:

- Stable assertion/source-identity tests: **11/11** on the formatted tree and **11/11** after the role renames, including duplicate ids, macro semantics, expanded-source lint and empty-inventory rejection.
- Shared lexer/anchor tests: **11/11**, including raw literals, spliced lines, numeric tokens, marker retention, duplicate/missing anchors, per-object rules, Makefile control failures, renamed function parameters/macros and digit-ending namespaces.
- Lottery runner/AST tests: **20/20**, including renamed/reindented expiry functions and absent/duplicate anchors.
- ELF controls: HLL, both executor checks, idle-clock allocation, both R7 capabilities, both LB controls and storesize. Renames change copied ELF symbol tables; they do not compile or boot a renamed production tree. Missing-role controls must fail. The linked-code identity assertions remain intact.
- Function-capture wrapper: positive lookup of both namespace roles, followed by rejection after deleting a required undefined symbol, also using actual renamed object symbols.

Reproduction (all source fixtures are disposable):

```sh
LC_ALL=C taskset -c 64-95 python3 -m pip install --target build/readability-a1/python clang-format==18.1.8
LC_ALL=C taskset -c 64-95 python3 docs/readability-a1/prepare_scratch.py
LC_ALL=C taskset -c 64-95 python3 docs/readability-a1/prove_tools.py --root build/readability-a1/formatted --output build/readability-a1/recheck-formatted
```

Repeat the last command for `current` and `renamed`. Preserve the unchanged frozen Redis 7.4 reference tree at the path used by the gate; generated-metadata checks deliberately use that external input. The preparation helper copies only source/test/build inputs and the two small documents needed by these checks.

### Build and binary proof

Compiler: **GCC 13.3.0**, original `-march=native` build flags. PRE was built at `5c3631281` before the lane edits. POST uses the same INFO metadata:

```sh
export LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0
taskset -c 64-95 make -j32 all
taskset -c 64-95 /home/user/Projects/calib/binary-neutral.sh build/readability-a1/PRE build/readability-a1/POST
```

The Makefile adds default-preserving overrides for these two existing INFO build values. Without pinning them, committing a change changes the advertised revision/dirty bit and therefore changes the production bytes even for comment-only work. The proof holds those build inputs fixed; it does not remove INFO fields or normalize executable sections beyond the supplied comparison script.

PRE and POST both strip to SHA-256 `555037b272faec7b4ff5bd03012485b26bb81df904f0805a0c0a298d3104a842`. [Binary receipt](docs/readability-a1/evidence/binary.json), [IDENTICAL output](docs/readability-a1/evidence/binary-neutral.log), and [comment-only source audit](docs/readability-a1/evidence/source-neutral.json).

All **61** targets listed in `job_production_units`, plus `all`, built successfully with `-j32`; all 62 passed `make -q`. The Climon positive/negative units and L4 unit also built, giving 65 successful primary targets. The supplementary multi-DB witness arms and blockfix targets also built through the gate. The final freshness sweep is **70/70**: [target list and exits](docs/readability-a1/evidence/make-freshness.json). Intentional negative-control executables are not production replacements, and are not claimed to be identical to the release server.

### Gate and fixture proof

- `LC_ALL=C GATE_TEST_PORT=25199 taskset -c 64-95 python3 tests/gates_test.py`: **83 tests, OK**.
- `LC_ALL=C taskset -c 64-95 python3 -m unittest discover -s tests -p gate_ledger_fixture.py`: **12 tests, OK**.
- `tests/fixtures/nullrefresh-ledger-labels.json` is unchanged: **1,230 rows, including NIC**.
- No added/removed counted row. `EXPECT_QUICK=1212` and `EXPECT_FULL=1229` remain unchanged; the existing quick-tier collection boundary is unchanged. The new tool tests run inside the existing R7 parity row. The individual lottery selector remains outside landing counts.

Every correctness boot inherited `LC_ALL=C`. Ordinary partial gate invocations used the gate's eight-core, 16-shard, 6:2 geometry, with `--server-cores 64-87 --load-cores 88-95 --load-smt ''` and allocated port ranges entirely inside 25100–25198. `GATE_PROOF_NO_RATES=1` excluded the optional release-rate assertions; their normal gate defaults were not changed. Oracle CPU overrides also stayed within 64–95. No full iteration, ABBA campaign or NIC benchmark ran.

The selected jobs cover source identity, config/docs and metadata, R7 sync/identity/engagement/bounds, lottery source checks, LB/WB/WBLAND/SplitLocal/flush/persistence units, both TSan counter modes, climon, tracking/AOF schedules, the function wrapper, HLL controls, idle-buffer and portable ROB negatives, both debug batteries, all eight selected multi-DB configurations, and the remaining direct callers of the hardened source controls. The exact selections and ledgers are in [gate-runs.json](docs/readability-a1/evidence/gate-runs.json).

| Gate invocation | Passed rows | Failed rows | Disposition |
|---|---:|---:|---|
| `gate-run.nRp2XT` | 82 | 16 | Units became stale while dependencies were still being edited; the gate correctly refused them. Rebuilt and rerun. |
| `gate-run.TiMLu6` | 46 | 3 | Fixed an over-specific lottery error check, DB-0 symbol lookup, and the explicit R7 prefix in the SplitLocal negative. |
| `gate-run.KEG70j` | 7 | 0 | All three failed jobs and the affected source/ROB/idle-buffer checks pass. |
| `gate-run.EzuOth` | 79 | 0 | Additional debug, persistence schedule, EX, R7 and writeback callers pass. |
| `gate-run.0aPDHf` | 7 | 0 | Final inline Makefile controls, ring, source identity, R7 and SplitLocal checks pass. |

Taking the latest execution of each selected counted job gives **185/185 passing rows**, across **46 counted jobs**, with two additional build-only dependency jobs. This union is documented separately from a full-gate result; earlier failures have not been deleted from the evidence. One additional invocation selected the build-only `production_units` job directly and was rejected before running rows; the final invocation selected its consumers instead ([selector rejection](docs/readability-a1/evidence/gate-rejected-build-only-selector.log)).

The lottery wrapper now accepts `tests/gate.sh lottery --row ID ...`, keeping its default whole-nightly invocation unchanged. It builds only the required non-ASAN witness unless row 503 is selected. Two bounded runs used 80–87 server CPUs, 92–95 client CPUs and ports 25170–25172:

- Row **149**, `--hits 1 --cap 60 --attempt-timeout 120`: **PASS**, one attempt and one required witness. This exercises the compiled lottery hooks and AST propagation observations through the gate interface.
- Row **159**, same bounds: **INSUFFICIENT**, two fresh attempts, zero complete W4 witnesses. Both batteries reported 101 checks and zero failures. Fanout and EXEC windows were observed, but the script expiry window was not. No skipped window, relaxed tolerance or passing lottery verdict was substituted. [149 receipt](docs/readability-a1/evidence/lottery-row149.json), [159 receipt](docs/readability-a1/evidence/lottery-row159.json).

The additional optional `l4prebuild-unit` runtime check **fails**, despite a successful build and extraction of the expected 512 boundary. After correcting the first invocation from 32 allowed CPUs to the required eight (64–71), all four mode/read-local combinations report `owner completes fragment`. The frozen `5c3631281` fixture/header tree, linked to the same binary-identical production objects, reproduces the same failure in all four combinations. No source/test assertion was weakened ([frozen/current comparison](docs/readability-a1/evidence/l4-frozen-comparison.json)). This optional target is not a counted gate row.

### Retirement and row-removal candidates

All **465 remaining** archived files match the frozen Git blobs byte for byte (the linked A1 audit predates the three A1b restorations) ([archive audit](docs/readability-a1/evidence/archive-audit.json)). `tools/archive/README.md` lists what each proved/built; `docs/readability-a1/retired.json` records original path, archived path and digest. Their relative import/ROOT assumptions are deliberately unchanged: replay them at their original commit and original paths, not as new build entry points.

**Rows whose only purpose is calling a retired tool: none.** The original closure missed dynamic test paths and a transitive import. After A1b restores those three files, the remaining archive is outside the reviewed live gate/build/import closure, including retained manual tool entry points. Therefore this lane proposes no row deletion and no EXPECT change. Frozen-reference PAD/identity checks still test an active invariant and remain in place. Historical CLI branches inside modules that supply live library functions are explicitly identified in the inventory; those modules were not moved wholesale.

### NOT RUN and remaining limits

- Full iteration/full gate, ABBA, NIC and throughput benchmarks; the complete nightly lottery campaign; lottery ASAN row 503; the optional L4 TSan target. Only the bounded rows above ran.
- Row 159 has no complete W4 witness and is not certified. This is a missing-window result, not an assertion pass.
- `tools/blockfix2_controls.py mutation('rename')` is a pre-existing broken historical build branch at the frozen input: it restores `83e0b809d:src/cmd/xshard_commands.inc` and then searches `blocking.inc` for command-specific publication code that has since moved/disappeared. It fails loudly. The six still-applicable mutation branches were prepared on all three source shapes and rejected broken anchors; no historical blockfix Tcl negative campaign was built or run. Its optional gate receipt/check paths remain present; no counted row was removed.
- The optional L4 unit runtime checks fail in both frozen and current fixtures as described above; they are not certified. The first 32-CPU invocation was rejected for geometry, before the eight-CPU comparison.
- Historical command-line proof branches retained alongside live utility imports (notably `ttlstate_proof.source`, wave orchestration and frozen-PRE patchers) were not replayed. The inventory distinguishes those branches from the helpers actually used by current builds/tests.
- The rename evidence covers the **142 bound roles**, plus the Python marker roles, not every possible unbound identifier or arbitrary file relocation. Preserve marker identities and update explicit build/path contracts when moving files. A blanket guarantee for arbitrary future renames remains outside the demonstrated coverage.
- No push, merge or maintainer measurement was performed. No committed file exceeds 1 MB.

### Files added by A1

These are additional to the frozen-input inventory below; archived destinations are recorded in the corresponding original-file rows.

| Tool/support file | Class | Caller | Action |
|---|---|---|---|
| `tools/build_source_controls.py` | LIVE; TEXT-MATCHER | Makefile Climon mask and L4 prebuild recipes | Checked function-body patch and integer macro reader; missing/duplicate anchors fail |
| `tools/source_tokens.py` | LIVE; TEXT-MATCHER | hardened C++/ELF tools and tests | Shared lexer, checked replacements and stable role translation |
| `tools/source_anchors.json` | LIVE | shared lexer and generated-source prerequisites | Required stable comments |
| `tests/source_tokens.py` | LIVE | directly executed tests | Import bridge to the shared implementation |
| `tests/source_tokens_test.py` | LIVE; TEXT-MATCHER | existing `reorder_sync` gate job | Lexer, marker, ELF-name, Makefile-control and per-object-rule checks |
| `tests/lottery_build_test.py` | LIVE | existing `reorder_sync` gate job | All 62 sites and absent/duplicate seam controls |
| `tests/python_anchors.py` | LIVE; TEXT-MATCHER | lottery driver and strict scriptatomic control | AST insertion at unique stable comments |

### Inventory

The actual frozen tree has 1,290 tracked files under tools/ and tests/, including 978 Python/shell/Make scripts. This supersedes the assessment’s older estimates. LIVE includes the gate, its tests and opt-in Makefile targets conservatively; TEXT-MATCHER is an additional property. MANUAL means retained standalone/support material with no proven closed-lane status. FINISHED-LANE is archived only after checking the transitive gate/build graph and all retained manual callers.

The original frozen caller graph can be reproduced with `python3 docs/readability-a1/inventory.py`; it reads the baseline directly from Git. Its retirement conclusions are superseded by the A1b executable caller graph and reviewed dynamic sites (`docs/readability-a1b/caller_inventory.py` and `prove_inventory.py`). `update_inventory.py` applies the reviewed per-file classifications recorded in `triage-overrides.json`.

Callers are source references/imports; a mention in documentation is not execution evidence. Dynamic gate paths are expanded conservatively. Full caller edges and baseline line references are included below.

| Tool / support file | Class | Callers | Action |
|---|---|---|---|
| `tests/README.md` | LIVE | `tools/execfifo3_perf_summary.py`, `tools/tailgen/main.cc` | retained |
| `tests/_abba_test_fixtures.py` | LIVE | `tests/_nullrefresh_test.py`, `tests/abba_aslr.py`, `tests/abba_experiments.py`, `tests/abbagate.py`, `tests/background_environment_test.py`, `tests/gate_measurements.py`, `tests/gate_receipt.py`, `tests/load_calibration.py`, `tests/ttlcell_test.py` | retained |
| `tests/_client_wait.py` | LIVE | `tests/acl.py`, `tests/aclfix.py`, `tests/aclreply.py`, `tests/aclsel.py`, `tests/climon2.py`, `tests/flakeaudit_test.py`, `tests/limits.py`, `tests/netio.py`, `tests/pushtear.py`, `tests/tracking.py` | retained |
| `tests/_differ_aclkeys.py` | LIVE | `tests/aclkeys_test.py`, `tests/aclkeys_wake.py`, `tests/aclkeys_wake_state.py`, `tests/differ.py` | retained |
| `tests/_differ_ccfix.py` | LIVE | `tests/differ.py` | retained |
| `tests/_differ_history.py` | LIVE | `tests/differ.py`, `tests/differ_fanout.py`, `tests/differ_fanout_test.py`, `tests/differ_gate.sh`, `tests/lottery_attempt.py`, `tests/mode_equivalence.py` | retained |
| `tests/_gate_process.py` | LIVE | `tests/abba_saturation_controls.py`, `tests/aof.py`, `tests/atomfix5.py`, `tests/atomfix6.py`, `tests/atomwake.py`, `tests/blockwake.py`, `tests/climon_128.py`, `tests/dbdefault.py`, `tests/feature_gate.py`, `tests/flushfix_checks.py`, `tests/gate_process_test.py`, `tests/gates_test.py`, `tests/legacy_reorder_witness.py`, `tests/lottery_attempt.py`, `tests/lottery_runner.py`, `tests/lottery_test_driver.py`, `tests/mode_equivalence.py`, `tests/mutants.py`, `tests/parkwake.py`, `tests/perf_gate.py`, `tests/racefix.py`, `tests/reordertrim.py`, `tests/servertail.py`, `tests/shutdown_persist.py`, `tests/trackorder.py`, `tools/mset8fix_latency.py`, `tools/overlapaxe_artifacts.py`, `tools/scriptfix3_jobs.py` | retained |
| `tests/_iofix.py` | LIVE | `tests/iofix_deferred.py`, `tests/iofix_hz.py`, `tests/iofix_signal.py`, `tests/iofix_sleep.py` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/_lib.py` | LIVE | `tests/_client_wait.py`, `tests/_differ_ccfix.py`, `tests/_gate_process.py`, `tests/_iofix.py`, `tests/_netfix.py`, `tests/abba_instrument.py`, `tests/abbagate.py`, `tests/aclfix.py`, `tests/aclkeys_wake.py`, `tests/aclkeys_wake_state.py`, `tests/aclreply.py`, `tests/aof.py`, `tests/aof_frame_order.py`, `tests/aoforder.py`, `tests/at412.py`, `tests/at412_diagnostics.py`, `tests/atomfix5.py`, `tests/atomfix5_accounting.py`, `tests/atomfix6.py`, `tests/atomic_hazards.py`, `tests/atomic_mode.py`, `tests/atomic_plain.py`, `tests/atomic_torn.py`, `tests/atomicwindow.py`, `tests/atomwake.py`, `tests/blockfix2_repro.py`, `tests/blockwake.py`, `tests/borrow_registry.py`, `tests/cd13b_checks.py`, `tests/cd13b_wire.py`, `tests/clientcompat.py`, `tests/climon_128.py`, `tests/climonfix4.py`, `tests/compat3_blockfix.py`, `tests/compat3_blockfix2.py`, `tests/compat3_functions.py`, `tests/compat3_lib.py`, `tests/compat3_lualibs.py`, `tests/compat3_pubsub.py`, `tests/compat3_streamfix.py`, `tests/compat3_streams.py`, `tests/connreset_repro.py`, `tests/contarity.py`, `tests/crlffix.py`, `tests/datafix2_idle.py`, `tests/datafix2_subkeys.py`, `tests/datafix2_watch.py`, `tests/dbdefault.py`, `tests/debug.py`, `tests/debug_load.py`, `tests/debug_load_test.py`, `tests/edgeenc.py`, `tests/encodingfix.py`, `tests/exbatch.py`, `tests/exec1s.py`, `tests/execiso.py`, `tests/expire_notify.py`, `tests/feature_atomic.py`, `tests/flip_under_load.py`, `tests/flipfix.py`, `tests/flipfix5.py`, `tests/flipfix6.py`, `tests/flipfix7.py`, `tests/flipfix_abort_probe.py`, `tests/fliplisten.py`, `tests/flushfix2.py`, `tests/flushfix2_siblings.py`, `tests/flushfix_checks.py`, `tests/gaterows_contract_test.py`, `tests/hexpire.py`, `tests/hexpread.py`, `tests/inline_protocol.py`, `tests/inline_quoted.py`, `tests/iowake.py`, `tests/knobs.py`, `tests/latencyfix.py`, `tests/lb_stationary.py`, `tests/lbsignals.py`, `tests/legacy_reorder_witness.py`, `tests/loading_ready_test.py`, `tests/lottery_test_driver.py`, `tests/mdbqsbr_live.py`, `tests/mode_lane.py`, `tests/moverfix.py`, `tests/multidb.py`, `tests/multidb_serial.py`, `tests/multifix.py`, `tests/multirace.py`, `tests/netcap.py`, `tests/netcmd.py`, `tests/netfix2.py`, `tests/notify_order.py`, `tests/notifycompat.py`, `tests/ntnew4_clock.py`, `tests/orthog.py`, `tests/parkwake.py`, `tests/perfex_checks.py`, `tests/perfio.py`, `tests/persistfix2.py`, `tests/pipeorder.py`, `tests/psfix.py`, `tests/publishfix_e2e.py`, `tests/pubtrackfix.py`, `tests/pushtear.py`, `tests/racefix.py`, `tests/read_local_lane.py`, `tests/read_local_lfu.py`, `tests/redis_tcl.py`, `tests/redisgap.py`, `tests/redisgap_atomic.py`, `tests/rehash_readonly.py`, `tests/reorder_flip.py`, `tests/replyoff_xshard.py`, `tests/resizefix.py`, `tests/respcompat.py`, `tests/respresume.py`, `tests/respresume_flip.py`, `tests/respresume_limits.py`, `tests/rl2s.py`, `tests/rlcache_churn.py`, `tests/rlfix.py`, `tests/rlfix3_info.py`, `tests/rlfix3_zc.py`, `tests/rlfix5.py`, `tests/rootcore.py`, `tests/savefix.py`, `tests/scancompact.py`, `tests/scriptatomic.py`, `tests/scriptfix2.py`, `tests/servertail.py`, `tests/session_monotonic.py`, `tests/shutdown_persist.py`, `tests/shutsave.py`, `tests/signalacct_live.py`, `tests/slotless.py`, `tests/slowlog_identity.py`, `tests/snapfix.py`, `tests/snapfix2_flush.py`, `tests/snapfix_neighbours.py`, `tests/sortstore.py`, `tests/splitlocal_live.py`, `tests/storefix5.py`, `tests/tailgen_stall.py`, `tests/trackfix.py`, `tests/tracking_redirect.py`, `tests/trackorder.py`, `tests/txn_movers.py`, `tests/txn_nx.py`, `tests/txnfix4.py`, `tests/txngroup.py`, `tests/txniso.py`, `tests/txnorder.py`, `tests/txnorder_watch.py`, `tests/wave10.py`, `tests/wave14_eof_data.py`, `tests/wave14_functions.py`, `tests/wave14_order.py`, `tests/wave15_aof.py`, `tests/wave15_block_repeat.py`, `tests/wave15_errorstats.py`, `tests/wave15_flip_eof.py`, `tests/wave15_rebind.py`, `tests/wave7.py`, `tests/wave8.py`, `tests/wave8b.py`, `tests/wave9.py`, `tests/wb_mixed.py`, `tests/wb_policy.py`, `tests/wiredump.py`, `tests/xshard_dispatch_scale.py`, `tools/blockfix3_repro.py`, `tools/ccfix5_probe.py`, `tools/exbatch_directed.py`, `tools/lb_episodes.py`, `tools/mkfix_counts.py`, `tools/mkprobe_probe.py`, `tools/mset8fix_latency.py`, `tools/ntfix_proof.py`, `tools/overlapaxe_artifacts.py`, `tools/respresume_probe.py`, `tools/setregress.py`, `tools/snapfix_long_storm.py`, `tools/snapfix_storm_capture.py`, `tools/storefix5_checks.py`, `tools/storesize_poller.py`, `tools/txnfix4_abort_site.py`, `tools/txnfix4_probes.py`, `tools/wave15_aof_stacks.py`, `tools/wave5b_trace.py`, `tools/woundfix_live.py` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/_netfix.py` | LIVE | `tests/cfgfix.py`, `tests/cfgfix2.py`, `tests/gates_test.py`, `tests/netfix2.py`, `tests/netfix_config.py`, `tests/netfix_idle_buffers.py`, `tests/netfix_query_stats.py`, `tests/netfix_tls.py`, `tests/netfix_unix.py`, `tests/wave15_rebind.py` | retained |
| `tests/_nullrefresh_test.py` | LIVE | `tests/abbagate.py`, `tests/gate_receipt.py`, `tests/nullpublish4_test.py` | retained |
| `tests/_save_timeout.py` | LIVE | `tests/differ.py`, `tests/psfix.py`, `tests/psfix_test.py` | retained |
| `tests/_serverfix.py` | LIVE | `tests/_serverfix_alloc.py`, `tests/serverfix_acllog.py`, `tests/serverfix_config.py`, `tests/serverfix_hello.py`, `tests/serverfix_hll.py`, `tests/serverfix_lines.py`, `tests/serverfix_scalar.py`, `tests/serverfix_slowlog.py`, `tests/serverfix_waitaof.py` | retained |
| `tests/_serverfix_alloc.py` | LIVE | `tests/serverfix_acllog.py`, `tests/serverfix_slowlog.py` | retained |
| `tests/_serverfix_mutant.py` | LIVE; TEXT-MATCHER | `tests/serverfix_hll.py` | Canonical stable roles for HLL symbols; requires both namespace bodies. |
| `tests/abba_aslr.py` | MANUAL | none in scoped code | retained |
| `tests/abba_binaries.py` | LIVE | `tests/abbagate.py` | retained |
| `tests/abba_calibration.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tests/abba_calibration.py` |
| `tests/abba_ceiling.py` | LIVE | `tests/abba_evidence.py`, `tests/abbagate.py`, `tests/gate_measurements.py`, `tests/load_calibration.py` | retained |
| `tests/abba_evidence.py` | LIVE | `tests/_nullrefresh_test.py`, `tests/abba_holdout.py`, `tests/abba_null_sampling.py`, `tests/abba_reorder_control.py`, `tests/abba_standing_null.py`, `tests/abba_worker_affinity.py`, `tests/abbagate.py`, `tests/background_environment_test.py`, `tests/gate_measurements.py`, `tests/gate_product_evidence.py`, `tests/gate_receipt.py`, `tests/gateprod.py`, `tests/nullpublish4_test.py`, `tests/ttlcell_test.py` | retained |
| `tests/abba_experiments.py` | LIVE | `tests/abba_aslr.py`, `tests/abba_instrument.py` | retained |
| `tests/abba_holdout.py` | LIVE | `tests/_nullrefresh_test.py`, `tests/abba_evidence.py`, `tests/abbagate.py`, `tests/gate_receipt.py`, `tests/nullpublish4_test.py` | retained |
| `tests/abba_instrument.py` | LIVE | `tests/_nullrefresh_test.py`, `tests/abba_evidence.py`, `tests/abba_profile.py`, `tests/abba_reorder_control.py`, `tests/abba_standing_null.py`, `tests/abbagate.py`, `tests/gate.sh`, `tests/gate_measurements.py`, `tests/gate_receipt.py`, `tests/gateprod.py`, `tests/gates_test.py`, `tests/nullpublish4_test.py`, `tests/nullpublish_refreeze_test.py`, `tools/nullpublish_refreeze.py` | retained |
| `tests/abba_null_sampling.py` | LIVE | `tests/_nullrefresh_test.py`, `tests/abba_evidence.py`, `tests/abbagate.py`, `tests/gate_receipt.py` | retained |
| `tests/abba_profile.py` | LIVE | `tests/abba_worker_affinity.py`, `tests/abbagate.py`, `tools/mkprobe_probe.py` | retained |
| `tests/abba_reorder_control.py` | LIVE | `tests/_nullrefresh_test.py`, `tests/abba_evidence.py`, `tests/abbagate.py`, `tests/gate_receipt.py`, `tests/load_calibration.py` | retained |
| `tests/abba_saturation.py` | LIVE | `tests/_abba_test_fixtures.py`, `tests/_nullrefresh_test.py`, `tests/abba_ceiling.py`, `tests/abba_evidence.py`, `tests/abba_saturation_controls.py`, `tests/abbagate.py`, `tests/gate_measurements.py`, `tests/gate_receipt.py`, `tools/exbatch_directed.py`, `tools/mkprobe_probe.py` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/abba_saturation_controls.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tests/abba_saturation_controls.py` |
| `tests/abba_simple.py` | LIVE | `tests/abbagate.py`, `tests/gates_test.py` | retained |
| `tests/abba_standing_null.py` | LIVE | `tests/abba_evidence.py`, `tests/abba_reorder_control.py`, `tests/abbagate.py`, `tests/gate_receipt.py`, `tests/nullpublish4_test.py` | retained |
| `tests/abba_worker_affinity.py` | LIVE | `tests/abbagate.py` | retained |
| `tests/abba_workloads.py` | LIVE | `tests/_abba_test_fixtures.py`, `tests/_nullrefresh_test.py`, `tests/abba_evidence.py`, `tests/abba_experiments.py`, `tests/abbagate.py`, `tests/gates_test.py`, `tests/tailgen_stall.py`, `tests/ttlcell_test.py`, `tools/exbatch_directed.py`, `tools/lb_episodes.py`, `tools/mkprobe_probe.py` | retained |
| `tests/abbagate.py` | LIVE | `tests/_nullrefresh_test.py`, `tests/abba_aslr.py`, `tests/abba_binaries.py`, `tests/abba_ceiling.py`, `tests/abba_evidence.py`, `tests/abba_experiments.py`, `tests/abba_holdout.py`, `tests/abba_instrument.py`, `tests/abba_null_sampling.py`, `tests/abba_reorder_control.py`, `tests/abba_saturation_controls.py`, `tests/gate.sh`, `tests/gate_history.py`, `tests/gate_measurements.py`, `tests/gate_receipt.py`, `tests/gateplan.py`, `tests/gateprod.py`, `tests/gates_test.py`, `tests/legacy_reorder_witness.py`, `tests/load_calibration.py`, `tests/nullpublish4_test.py`, `tests/ttlcell_test.py`, `tools/mkprobe_probe.py`, `tools/wbknobs_measure.py` | retained |
| `tests/acl.py` | LIVE; TEXT-MATCHER | `tests/gate.sh`, `tests/serverfix_acllog.py` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tests/acl_categories.py` | LIVE; TEXT-MATCHER | `tests/gate.sh`, `tools/gen_acl_categories.py` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tests/acl_subcommands.py` | MANUAL | none in scoped code | retained |
| `tests/aclfix.py` | LIVE | `tests/gate.sh` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/aclkeys_test.py` | MANUAL | none in scoped code | retained |
| `tests/aclkeys_unit.cc` | LIVE | `Makefile` | retained |
| `tests/aclkeys_wake.py` | MANUAL | none in scoped code | retained |
| `tests/aclkeys_wake_state.py` | LIVE | `tests/gate.sh`, `tests/gates_test.py` | retained |
| `tests/aclkeys_wake_unit.cc` | LIVE | `Makefile`, `tools/aclkeys3_controls.py` | retained |
| `tests/aclreply.py` | LIVE | `tests/gate.sh` | retained |
| `tests/aclsel.py` | MANUAL | none in scoped code | retained |
| `tests/aof.py` | LIVE | `tests/flakeaudit_test.py`, `tests/gate.sh`, `tools/eoffix_final.py`, `tools/rootcore_proof.py` | retained |
| `tests/aof_frame_order.py` | LIVE | `tests/aof_frame_order_test.py`, `tests/gate.sh` | retained |
| `tests/aof_frame_order_test.py` | LIVE | `tests/gate.sh` | retained |
| `tests/aof_frames.py` | LIVE | `tests/aof_frame_order.py`, `tests/aoforder.py`, `tests/notify_order.py`, `tests/notifycompat.py` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/aof_fsync.py` | LIVE | `tests/flakeaudit_test.py`, `tests/gate.sh`, `tools/aoffix2_proof.py` | retained |
| `tests/aof_rewrite.py` | LIVE | `tests/aof_rewrite_matrix.sh` | retained |
| `tests/aof_rewrite_matrix.sh` | LIVE | `tests/gate.sh`, `tests/gates_test.py` | retained |
| `tests/aof_rewrite_trigger_matrix.sh` | LIVE | `tests/gate.sh`, `tests/gates_test.py` | retained |
| `tests/aof_rewrite_triggers.py` | LIVE | `tests/aof_rewrite_trigger_matrix.sh` | retained |
| `tests/aof_torn_group.py` | LIVE | `tests/gate.sh` | retained |
| `tests/aoffix2.py` | LIVE | `tests/aoforder.py`, `tests/gate.sh`, `tests/hexpread.py`, `tests/objectpread.py`, `tests/persistfmt.py`, `tests/publishfix_e2e.py`, `tools/aoffix2_proof.py` | retained |
| `tests/aoforder.py` | LIVE | `tests/gate.sh`, `tests/publishfix_e2e.py` | retained |
| `tests/arity.py` | MANUAL | none in scoped code | retained |
| `tests/at15.py` | LIVE | `tests/clientcompat.py`, `tests/differ.py` | retained |
| `tests/at15_gate_test.py` | MANUAL | none in scoped code | retained |
| `tests/at15_unit.cc` | MANUAL | none in scoped code | retained |
| `tests/at412.py` | LIVE | `tests/at412_diagnostics.py`, `tests/gate.sh`, `tests/wave10.py`, `tests/wave9.py`, `tools/clientcompat_verdict.py`, `tools/snapfix_stacks.py` | retained |
| `tests/at412_diagnostics.py` | FINISHED-LANE | `tools/snapfix2_verify.py`, `tools/snapfix_reproduce.py`, `tools/snapfix_stacks.py` | moved unchanged to `tools/archive/tests/at412_diagnostics.py` |
| `tests/at412_owner.cc` | LIVE | `Makefile` | retained |
| `tests/at_recycle_checks.inc` | LIVE | `Makefile`, `tests/owner_arena_unit.cc` | retained |
| `tests/at_recycle_witness.h` | MANUAL | `tests/at_recycle_witness_alloc.cc`, `tools/at_recycle_artifacts.py` | retained |
| `tests/at_recycle_witness_alloc.cc` | MANUAL | none in scoped code | retained |
| `tests/atomfix.py` | MANUAL | none in scoped code | retained |
| `tests/atomfix5.py` | LIVE | `tests/atomfix5_accounting.py`, `tests/gate.sh` | retained |
| `tests/atomfix5_accounting.py` | LIVE | `tests/gate.sh` | retained |
| `tests/atomfix6.py` | LIVE | `tests/gate.sh` | retained |
| `tests/atomfix6_park_scope.cc` | MANUAL | `tools/atomfix6_counts.py` | retained |
| `tests/atomfix6_park_unit.cc` | LIVE | `Makefile`, `tests/gate.sh`, `tools/atomfix6.mk`, `tools/atomfix6_park_pre.py` | retained |
| `tests/atomfix6_queue_unit.cc` | LIVE | `Makefile` | retained |
| `tests/atomfix6_unit.cc` | LIVE | `Makefile` | retained |
| `tests/atomic_hazards.py` | LIVE | `tests/gate.sh`, `tools/flushfix2_verification_receipts.py` | retained |
| `tests/atomic_mode.py` | LIVE | `tests/gate.sh` | retained |
| `tests/atomic_plain.py` | LIVE | `tests/gate.sh` | retained |
| `tests/atomic_plain_checks.inc` | LIVE | `Makefile`, `tests/atomic_survivors_unit.cc`, `tools/atomfix_controls.py` | retained |
| `tests/atomic_ryow.py` | LIVE | `tests/gate.sh` | retained |
| `tests/atomic_survivors_unit.cc` | LIVE | `Makefile`, `tests/at412_owner.cc`, `tests/atomiccollapse_controls.py`, `tests/blockfix2_unit.cc`, `tests/ccfix2_atomic_unit.cc`, `tests/exec1s_unit.cc`, `tests/txnorder_chain.cc`, `tests/txnorder_episodes.cc`, `tests/txnorder_index_unit.cc`, `tests/txnorder_plain_cost.cc`, `tests/txnorder_watch_unit.cc`, `tests/txnorder_wound_window.cc`, `tests/wave15_stream_unit.cc`, `tools/atomfix_controls.py`, `tools/blockfix2.mk`, `tools/blockfix2_controls.py`, `tools/blockfix2_pad.py`, `tools/txnfix_admission_control.py` | retained |
| `tests/atomic_torn.py` | LIVE | `tests/gate.sh`, `tools/gt14fix_evidence.py` | retained |
| `tests/atomiccollapse_checks.inc` | LIVE | `Makefile`, `tests/atomic_survivors_unit.cc`, `tests/atomiccollapse_controls.py`, `tools/atomfix_controls.py` | retained |
| `tests/atomiccollapse_controls.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tests/atomiccollapse_controls.py` |
| `tests/atomicwindow.py` | LIVE | `tests/atomic_ryow.py`, `tests/atomic_torn.py`, `tests/gaterows_contract_test.py` | retained |
| `tests/atomwake.py` | LIVE | `tests/gate.sh` | retained |
| `tests/atomwake_unit.cc` | LIVE | `Makefile` | retained |
| `tests/auth.py` | LIVE | `tests/gate.sh` | retained |
| `tests/autharity.py` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/authfix.py` | LIVE | `tests/_serverfix.py`, `tests/clientcompat.py`, `tests/crlffix.py`, `tests/exec1s.py`, `tests/gate.sh`, `tests/infofix_compat.py`, `tests/latencyfix.py`, `tests/pubtrackfix.py`, `tests/rootcompat.py`, `tests/rootcompat_tracking/run.py`, `tests/rootcompat_tracking/srv.py`, `tests/wave15_errorstats.py`, `tests/wave8.py`, `tests/wave8b.py`, `tools/cmdfix2_fifo_diagnostic.py` | retained |
| `tests/background_environment_test.py` | LIVE | `tests/gate.sh`, `tests/gates_test.py` | retained |
| `tests/barrier.py` | MANUAL | none in scoped code | retained |
| `tests/benchfeat.py` | MANUAL | none in scoped code | retained |
| `tests/bitfield.py` | LIVE | `tests/gate.sh` | retained |
| `tests/blockfix2_repro.py` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/blockfix2_unit.cc` | LIVE | `tools/blockfix2.mk`, `tools/blockfix2_controls.py`, `tools/blockfix2_pad.py` | retained |
| `tests/blockfix4.py` | LIVE | `tests/gate.sh`, `tools/blockfix4_verify.py` | retained |
| `tests/blockfix4_repro/README.md` | LIVE | `tools/execfifo3_perf_summary.py`, `tools/tailgen/main.cc` | retained |
| `tests/blockfix4_repro/item1_natural.py` | LIVE | `tests/blockfix4.py` | retained |
| `tests/blockfix4_repro/item1_script_push.py` | LIVE | `tests/blockfix4.py` | retained |
| `tests/blockfix4_repro/item2_move_nil.py` | LIVE | `tests/blockfix4.py` | retained |
| `tests/blockfix4_repro/item4_creators.py` | LIVE | `tests/blockfix4.py` | retained |
| `tests/blockfix4_repro/item5_stream_removed.py` | LIVE | `tests/blockfix4.py` | retained |
| `tests/blockfix4_repro/item6_mpop_null.py` | LIVE | `tests/blockfix4.py` | retained |
| `tests/blockfix4_repro/lib/common.py` | LIVE | `tests/blockfix4_repro/item1_natural.py`, `tests/blockfix4_repro/item1_script_push.py`, `tests/blockfix4_repro/item2_move_nil.py`, `tests/blockfix4_repro/item4_creators.py`, `tests/blockfix4_repro/item5_stream_removed.py`, `tests/blockfix4_repro/item6_mpop_null.py`, `tools/txnfix4_auditors.py` | retained |
| `tests/blockfix4_repro/lib/resp.py` | LIVE | `tests/blockfix4_repro/item1_natural.py`, `tests/blockfix4_repro/item1_script_push.py`, `tests/blockfix4_repro/item2_move_nil.py`, `tests/blockfix4_repro/item4_creators.py`, `tests/blockfix4_repro/item5_stream_removed.py`, `tests/blockfix4_repro/item6_mpop_null.py`, `tests/blockfix4_repro/lib/srv.py`, `tests/netfix2_audit.py`, `tests/rootcompat_tracking/srv.py`, `tests/rootcompat_tracking/t1_xsnotify.py`, `tests/rootcompat_tracking/t3_keylesscap.py`, `tests/txnfix_audit/t01_exec_counter.py`, `tests/txnfix_audit/t02_exec_directed.py`, `tests/txnfix_audit/t02b_exec_vs_exec.py`, `tests/txnfix_audit/t03_mover_replay.py`, `tests/txnfix_audit/t04_mover_stress.py`, `tests/txnfix_audit/t05_mover_only.py`, `tests/txnfix_audit/t10_msetnx_hold.py`, `tests/txnfix_audit/t14_exec_window.py`, `tests/txnfix_audit/t15_exec_only_stress.py`, `tests/txnfix_audit/t17_queue_exec.py`, `tests/txnfix_audit/t18_watch_cas.py`, `tests/txnfix_audit/t19_crossed_watch.py`, `tools/atomfix6_audit.py`, `tools/wave15_scan_expiry.py` | retained |
| `tests/blockfix4_repro/lib/srv.py` | LIVE | `tests/blockfix4_repro/item1_natural.py`, `tests/blockfix4_repro/item1_script_push.py`, `tests/blockfix4_repro/item2_move_nil.py`, `tests/blockfix4_repro/item4_creators.py`, `tests/blockfix4_repro/item5_stream_removed.py`, `tests/blockfix4_repro/item6_mpop_null.py`, `tests/blockfix4_repro/lib/common.py`, `tests/rootcompat_tracking/run.py`, `tests/rootcompat_tracking/t1_xsnotify.py`, `tests/rootcompat_tracking/t3_keylesscap.py` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/blockfix4_scope.cc` | LIVE | `tools/blockfix4_scope.py`, `tools/blockwake_counts.py`, `tools/eoffix_counts.py`, `tools/mset8fix_counts.py`, `tools/parkwake_counts.py`, `tools/rlfix5_proof.py`, `tools/storefix5_counts.py`, `tools/wave14_counts.py`, `tools/wave15_counts.py` | retained |
| `tests/blockfix_cost.cc` | LIVE | `tools/blockfix_cost.mk` | retained |
| `tests/blocking.py` | LIVE | `tests/gate.sh` | retained |
| `tests/blockmulti.py` | MANUAL | none in scoped code | retained |
| `tests/blockwake.py` | LIVE | `tests/gate.sh` | retained |
| `tests/boot_failures.py` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/boot_support_checks.inc` | LIVE | `Makefile`, `tests/config_parser_test.cc`, `tools/boot_support_artifacts.py` | retained |
| `tests/borrow_registry.py` | LIVE | `tests/gate.sh` | retained |
| `tests/bplus.py` | LIVE | `tests/gate.sh` | retained |
| `tests/broaden_bench.cc` | LIVE | `Makefile` | retained |
| `tests/ccfix2_atomic_unit.cc` | MANUAL | `tools/ccfix2_prove.py`, `tools/ccfix3_prove.py` | retained |
| `tests/ccfix5_debug_unit.cc` | MANUAL | `tools/ccfix5_prove.py` | retained |
| `tests/ccfix_instr.cc` | MANUAL | `tools/ccfix2_prove.py`, `tools/ccfix3_prove.py` | retained |
| `tests/ccfix_unit.cc` | MANUAL | `tools/ccfix2_prove.py`, `tools/ccfix3_prove.py` | retained |
| `tests/cd13b_audit.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tests/cd13b_audit.py` |
| `tests/cd13b_checks.py` | MANUAL; TEXT-MATCHER | `tests/cd13b_oracle.sh` | retained |
| `tests/cd13b_oracle.sh` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/cd13b_unit.cc` | MANUAL | `tests/cd13b_checks.py` | retained |
| `tests/cd13b_window_test.py` | LIVE | `tests/gate.sh:6283`, `witness_contracts` via `tests/$suite.py` | A1b: restored unchanged; mandatory moved-placement/never-open-window falsification contracts. |
| `tests/cd13b_wire.py` | LIVE | `tests/cd13b_checks.py`, `tests/cd13b_window_test.py`, `tests/differ.py` | retained |
| `tests/cdfix_checks.py` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/cdfix_oracle.c` | MANUAL | `tests/cdfix_checks.py` | retained |
| `tests/cdfix_unit.cc` | MANUAL | `tests/cdfix_checks.py` | retained |
| `tests/cfgfix.py` | LIVE; TEXT-MATCHER | `tests/gate.sh` | Retained: parses the pinned Redis 7.4 reference config table; TomoKV edits do not alter that input. |
| `tests/cfgfix2.py` | LIVE; TEXT-MATCHER | `tests/gate.sh`, `tests/wave15_block_repeat.py`, `tests/wave15_flip_eof.py`, `tests/wave15_rebind.py` | Canonical stable roles for ELF allocation sites; nonempty inventory remains mandatory. |
| `tests/cfgfix2_alloc_fail.cc` | LIVE | `tests/cfgfix2.py` | retained |
| `tests/clientcompat.py` | LIVE | `tests/gate.sh`, `tests/wave14_order.py` | retained |
| `tests/clientcompat_pause_scope.cc` | MANUAL | `tools/clientcompat_pause_audit.py` | retained |
| `tests/clientcompat_scope.cc` | MANUAL | `tools/clientcompat_counts.py` | retained |
| `tests/clientcompat_session_scope.cc` | MANUAL | `tools/clientcompat_counts.py`, `tools/wave14_counts.py`, `tools/wave15_counts.py` | retained |
| `tests/clientfix.py` | LIVE | `tests/clientfix_widths.py`, `tests/cmdfix2.py`, `tests/datafix1_bitfield.py`, `tests/datafix1_common.py`, `tests/datafix1_lists.py`, `tests/gate.sh`, `tests/wave6_exec.py` | retained |
| `tests/clientfix_widths.py` | MANUAL | none in scoped code | retained |
| `tests/climon.py` | MANUAL | none in scoped code | retained |
| `tests/climon2.py` | MANUAL | none in scoped code | retained |
| `tests/climon_128.py` | MANUAL | none in scoped code | retained |
| `tests/climon_mask_unit.cc` | LIVE | `Makefile` | retained |
| `tests/climonfix4.py` | LIVE | `tests/gate.sh` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/climonfix4_scope.cc` | MANUAL | none in scoped code | retained |
| `tests/climonfix5_scope.cc` | MANUAL | none in scoped code | retained |
| `tests/climonfix_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tests/climonfix_artifacts.py` |
| `tests/cmdfix2.py` | LIVE | `tests/gate.sh` | retained |
| `tests/cmdfix2_scope.cc` | MANUAL | `tools/cmdfix2_counts.py` | retained |
| `tests/cmdgap.py` | MANUAL | none in scoped code | retained |
| `tests/cmdgap2.py` | MANUAL | none in scoped code | retained |
| `tests/cmdlookup_unit.cc` | MANUAL | none in scoped code | retained |
| `tests/cmdmeta.py` | LIVE | `tests/cmdmeta_coverage.py`, `tests/cmdmeta_test.py`, `tools/gen_cmdmeta.py` | retained |
| `tests/cmdmeta_coverage.py` | LIVE; TEXT-MATCHER | `tests/_differ_history.py`, `tests/autharity.py`, `tests/cmdmeta.py`, `tests/cmdmeta_test.py`, `tests/differ.py`, `tests/gate.sh` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tests/cmdmeta_test.py` | MANUAL | none in scoped code | retained |
| `tests/compat2_support.py` | MANUAL | `tests/acl_subcommands.py`, `tests/autharity.py`, `tests/dispatch_arity.py`, `tests/dispatch_children.py`, `tests/dispatch_errors.py`, `tests/expire_notify.py`, `tests/ktls_lifetime.py`, `tests/router_uniform.py` | retained |
| `tests/compat3_blockfix.py` | LIVE | `tests/compat3_blockfix2.py` | retained |
| `tests/compat3_blockfix2.py` | LIVE | `tests/wave15_block_repeat.py`, `tools/blockfix3_repro.py` | retained |
| `tests/compat3_functions.py` | MANUAL | none in scoped code | retained |
| `tests/compat3_lib.py` | LIVE | `tests/compat3_blockfix.py`, `tests/compat3_blockfix2.py`, `tests/compat3_functions.py`, `tests/compat3_pubsub.py`, `tests/compat3_streamfix.py`, `tests/compat3_streams.py`, `tests/datafix2_encoding.py`, `tests/datafix2_idle.py`, `tests/datafix2_notouch.py`, `tests/datafix2_subkeys.py`, `tests/datafix2_watch.py`, `tests/wave15_block_repeat.py`, `tools/blockfix3_repro.py` | retained |
| `tests/compat3_lualibs.py` | MANUAL | none in scoped code | retained |
| `tests/compat3_pubsub.py` | MANUAL | none in scoped code | retained |
| `tests/compat3_streamfix.py` | MANUAL | none in scoped code | retained |
| `tests/compat3_streams.py` | MANUAL | none in scoped code | retained |
| `tests/concur.py` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/config_parser_test.cc` | LIVE | `Makefile`, `tests/gate.sh`, `tools/boot_support_controls.py` | retained |
| `tests/connreset_harness_test.py` | LIVE | `tests/gate.sh`, `tools/iopass_validate.py` | retained |
| `tests/connreset_repro.py` | MANUAL | none in scoped code | retained |
| `tests/contarity.py` | MANUAL | none in scoped code | retained |
| `tests/core_concurrency_unit.cc` | LIVE | `Makefile`, `tests/ctlfix.mk`, `tests/ctlfix_unit.cc`, `tests/flip_close_controls.py`, `tests/gate.sh`, `tests/gates_test.py`, `tests/ktls_lifetime_unit.cc`, `tests/lbplanner_unit.cc`, `tests/respresume_migration.cc`, `tests/signalacct_core_controls.py`, `tests/txnorder_chain.cc`, `tests/wave15_flip_eof_unit.cc`, `tools/flipreport_proof.py`, `tools/flipsettle_controls.py`, `tools/iopass_receipts.py`, `tools/lanefull_controls.py`, `tools/lbfix_artifacts.py`, `tools/lbplanner_pre_receipt.py` | retained |
| `tests/crlffix.py` | LIVE | `tests/gate.sh` | retained |
| `tests/ctlfix.mk` | LIVE | `tests/gate.sh` | retained |
| `tests/ctlfix_unit.cc` | LIVE | `tests/ctlfix.mk` | retained |
| `tests/datafix1_bitfield.py` | LIVE | `tests/gate.sh` | retained |
| `tests/datafix1_common.py` | LIVE | `tests/cmdfix2.py`, `tests/datafix1_bitfield.py`, `tests/datafix1_geo.py`, `tests/datafix1_hexpire.py`, `tests/datafix1_lists.py`, `tests/datafix1_locale.py`, `tests/datafix1_randscan.py`, `tests/datafix1_spop.py`, `tools/cmdfix2_auditors.py` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/datafix1_geo.py` | LIVE | `tests/gate.sh` | retained |
| `tests/datafix1_hexpire.py` | LIVE | `tests/gate.sh` | retained |
| `tests/datafix1_lists.py` | LIVE | `tests/gate.sh` | retained |
| `tests/datafix1_locale.py` | LIVE | `tests/gate.sh` | retained |
| `tests/datafix1_randscan.py` | LIVE | `tests/gate.sh` | retained |
| `tests/datafix1_spop.py` | LIVE | `tests/gate.sh` | retained |
| `tests/datafix2_encoding.py` | MANUAL | none in scoped code | retained |
| `tests/datafix2_idle.py` | MANUAL | none in scoped code | retained |
| `tests/datafix2_notouch.py` | MANUAL | none in scoped code | retained |
| `tests/datafix2_subkeys.py` | MANUAL | none in scoped code | retained |
| `tests/datafix2_watch.py` | MANUAL | none in scoped code | retained |
| `tests/dbdefault.py` | LIVE | `tests/abbagate.py`, `tests/gate.sh` | retained |
| `tests/deadfused_checks.py` | MANUAL | none in scoped code | retained |
| `tests/debug.py` | LIVE | `tests/gate.sh` | retained |
| `tests/debug_load.py` | LIVE | `tests/aof_rewrite_matrix.sh`, `tests/gate.sh` | retained |
| `tests/debug_load_test.py` | MANUAL | none in scoped code | retained |
| `tests/differ.py` | LIVE | `tests/_differ_history.py`, `tests/cmdmeta_test.py`, `tests/differ_fanout.py`, `tests/differ_fanout_test.py`, `tests/differ_gate.sh`, `tests/differ_test.py`, `tests/encodingfix.py`, `tests/infofields_test.py`, `tests/lottery_attempt.py`, `tests/lottery_test_driver.py`, `tests/psfix.py`, `tests/respresume_differ_frag.py`, `tools/ccfix3_wire.sh`, `tools/exec1sd_save.py`, `tools/exec1sd_save_native.py`, `tools/execfifo3_coverage.py`, `tools/infofields2_live.py`, `tools/infofields_monitor_strict.py` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/differ_fanout.py` | LIVE | `tests/differ_fanout_test.py`, `tests/differ_gate.sh`, `tests/gate.sh`, `tests/gates_test.py`, `tools/ccfix5_collect.py`, `tools/flushfix3_receipts.py`, `tools/wave14_validation.py` | retained |
| `tests/differ_fanout_test.py` | MANUAL | none in scoped code | retained |
| `tests/differ_gate.sh` | LIVE | `tests/cd13b_oracle.sh`, `tests/differ_fanout_test.py`, `tests/gate.sh`, `tests/gates_test.py`, `tests/lottery_attempt.py`, `tools/aoffix2_proof.py`, `tools/blockfix_climon.py`, `tools/ccfix3_wire.sh`, `tools/ccfix5_probe.sh`, `tools/exec1sd_save_full.py`, `tools/flushfix2_verification_receipts.py`, `tools/flushfix2_verify.py`, `tools/infofields2_live.py`, `tools/lualibs_proof.sh` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/differ_seeds.txt` | LIVE | `tests/_differ_history.py`, `tools/eoffix_verify.py`, `tools/execfifo3_coverage.py` | retained |
| `tests/differ_test.py` | MANUAL | none in scoped code | retained |
| `tests/dispatch_arity.py` | MANUAL | none in scoped code | retained |
| `tests/dispatch_children.py` | MANUAL | none in scoped code | retained |
| `tests/dispatch_errors.py` | MANUAL | none in scoped code | retained |
| `tests/docs_drift.py` | LIVE; TEXT-MATCHER | `tests/gate.sh`, `tools/iopass_validate.py` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tests/doubles.py` | MANUAL | none in scoped code | retained |
| `tests/dumprestore.py` | LIVE | `tests/gate.sh` | retained |
| `tests/dumpttl.py` | MANUAL | none in scoped code | retained |
| `tests/edgeenc.py` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/edgeproto.py` | MANUAL | none in scoped code | retained |
| `tests/edgetime.py` | MANUAL | `tests/edgetime_persist.sh` | retained |
| `tests/edgetime_persist.sh` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/encodingfix.py` | MANUAL | none in scoped code | retained |
| `tests/encodingfix_unit.cc` | MANUAL | `tests/storefix5_append.cc` | retained |
| `tests/eoffix_aof.cc` | MANUAL | `tools/eoffix_aof.py` | retained |
| `tests/eoffix_receive_scope.cc` | MANUAL | `tools/eoffix_receive_counts.py` | retained |
| `tests/evict_battery.py` | LIVE | `tests/evict_battery_test.py`, `tests/gate.sh` | retained |
| `tests/evict_battery_test.py` | MANUAL | none in scoped code | retained |
| `tests/exbatch.py` | LIVE | `tests/gate.sh` | retained |
| `tests/exbatch_checks.py` | LIVE; TEXT-MATCHER | `tests/gate.sh`, `tools/iopass_validate.py` | Shared ELF role canonicalization; exact patch-table and instruction checks retained. |
| `tests/exbatch_unit.cc` | LIVE | `Makefile` | retained |
| `tests/exec1s.py` | LIVE | `tests/gate.sh` | retained |
| `tests/exec1s_alloc_scope.cc` | MANUAL | `tools/exec1s_aux.py`, `tools/exec1sd.py` | retained |
| `tests/exec1s_cq_watch.cc` | MANUAL | `tools/exec1s_finish_proof.py`, `tools/exec1sd_proof.py` | retained |
| `tests/exec1s_idle_scope.cc` | MANUAL | `tools/exec1s_build.py`, `tools/exec1s_idle.py`, `tools/exec1sd.py` | retained |
| `tests/exec1s_io_scope.cc` | MANUAL | `tools/exec1s_aux.py`, `tools/exec1s_build.py` | retained |
| `tests/exec1s_owner_scope.cc` | MANUAL | `tools/exec1s_build.py` | retained |
| `tests/exec1s_unit.cc` | LIVE | `Makefile`, `tools/exec1s_directed.py` | retained |
| `tests/exec1s_word.cc` | LIVE | `Makefile` | retained |
| `tests/exec1sd_scope.cc` | MANUAL | `tools/exec1sd.py`, `tools/exec1sd_scatter.py`, `tools/execfifo2_scope.py` | retained |
| `tests/execabort_watch_gate_test.py` | MANUAL | none in scoped code | retained |
| `tests/execabort_watch_unit.cc` | MANUAL | none in scoped code | retained |
| `tests/execatomic.py` | MANUAL | none in scoped code | retained |
| `tests/execfair.py` | LIVE | `tests/gate.sh`, `tools/cmdfix2_evidence.py`, `tools/cmdfix2_fifo_diagnostic.py` | retained |
| `tests/execfifo2_owner_scope.cc` | MANUAL | `tools/execfifo2_scope.py` | retained |
| `tests/execfifo3_scope.cc` | MANUAL | `tools/execfifo3_scope.py` | retained |
| `tests/execfix.mk` | MANUAL | none in scoped code | retained |
| `tests/execfix.py` | LIVE | `tests/txnfix4.py`, `tools/txnfix4_auditors.py` | retained |
| `tests/execfix_cells.txt` | MANUAL | none in scoped code | retained |
| `tests/execfix_unit.cc` | MANUAL | `tests/execfix.mk` | retained |
| `tests/execiso.py` | MANUAL | none in scoped code | retained |
| `tests/expire_notify.py` | MANUAL | none in scoped code | retained |
| `tests/expire_notify_unit.cc` | LIVE | `Makefile` | retained |
| `tests/expireindex.py` | LIVE | `tests/gate.sh` | retained |
| `tests/expwide.py` | MANUAL | none in scoped code | retained |
| `tests/feature_atomic.py` | LIVE | `tests/gate.sh`, `tests/gaterows_contract_test.py` | retained |
| `tests/feature_gate.py` | LIVE | `tests/gate.sh`, `tests/gates_test.py`, `tests/loading_ready_test.py`, `tests/mode_equivalence.py`, `tests/mutants.py` | retained |
| `tests/fixtures/dispatchfix-pre/appendonlydir/appendonly.aof.1.incr.tomo.gz` | MANUAL | none in scoped code | retained |
| `tests/fixtures/dispatchfix-pre/checks.json` | LIVE | `tests/lbplanner_checks.py`, `tests/router_uniform.py`, `tools/exbatch_directed.py`, `tools/flushfix2_verification_receipts.py` | retained |
| `tests/fixtures/dispatchfix-pre/commands.json` | LIVE | `tests/router_uniform.py`, `tools/aclkeys3_controls.py`, `tools/aoffix2_proof.py`, `tools/aoforder_schedule.py`, `tools/compat2_mset_control.py`, `tools/notifycompat_schedule.py`, `tools/trackfix_schedule.py` | retained |
| `tests/fixtures/dispatchfix-pre/dump.tomo.gz` | MANUAL | `tests/router_uniform.py` | retained |
| `tests/fixtures/dispatchfix-pre/origin.json` | MANUAL | `tests/router_uniform.py` | retained |
| `tests/fixtures/nullpublish-campaign6-compact.json` | LIVE | `tests/_nullrefresh_test.py` | retained |
| `tests/fixtures/nullpublish-campaign7-samples.json.gz` | LIVE | `tests/nullpublish4_test.py` | retained |
| `tests/fixtures/nullrefresh-ledger-labels.json` | LIVE | `tests/gate_ledger_fixture.py`, `tools/wave14.py`, `tools/wave15.py` | retained |
| `tests/fixtures/perfio-stream.json` | LIVE | `tests/perfio.py` | retained |
| `tests/flakeaudit_test.py` | MANUAL | none in scoped code | retained |
| `tests/flatstore_alloc_fail.py` | MANUAL | none in scoped code | retained |
| `tests/flip.py` | LIVE | `tests/gate.sh` | retained |
| `tests/flip_close_checks.inc` | LIVE | `Makefile`, `tests/core_concurrency_unit.cc`, `tests/flip_close_controls.py` | retained |
| `tests/flip_close_controls.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tests/flip_close_controls.py` |
| `tests/flip_cost_gate.py` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/flip_multikey_hold.py` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/flip_ttl.py` | LIVE | `tests/gate.sh` | retained |
| `tests/flip_under_load.py` | LIVE | `tests/gate.sh` | retained |
| `tests/flipctl.py` | LIVE | `tests/flipctl_test.py`, `tests/gate.sh`, `tests/reorder_flip.py` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/flipctl_test.py` | MANUAL | none in scoped code | retained |
| `tests/flipctl_unit.cc` | LIVE | `Makefile`, `tests/gate.sh`, `tools/flipreport_proof.py` | retained |
| `tests/flipfix.py` | LIVE | `tests/flipfix7.py`, `tests/gate.sh` | retained |
| `tests/flipfix5.py` | LIVE | `tests/gate.sh` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/flipfix5_checks.inc` | LIVE | `Makefile`, `tests/core_concurrency_unit.cc` | retained |
| `tests/flipfix5_control_scope.cc` | MANUAL | `tools/flipfix5_counts.py` | retained |
| `tests/flipfix6.py` | LIVE | `tests/flushfix2_siblings.py`, `tests/gate.sh` | retained |
| `tests/flipfix6_checks.inc` | LIVE | `Makefile`, `tests/core_concurrency_unit.cc` | retained |
| `tests/flipfix6_command_scope.cc` | MANUAL | `tools/flipfix6_counts.py`, `tools/flipfix7_counts.py` | retained |
| `tests/flipfix6_control_scope.cc` | MANUAL | `tools/flipfix6_counts.py`, `tools/flipfix7_counts.py` | retained |
| `tests/flipfix6_s2_scope.cc` | MANUAL | none in scoped code | retained |
| `tests/flipfix7.py` | LIVE | `tests/flipfix.py`, `tests/gate.sh`, `tools/flipfix7_negative.py` | retained |
| `tests/flipfix7_checks.inc` | LIVE | `Makefile`, `tests/core_concurrency_unit.cc` | retained |
| `tests/flipfix_abort_probe.py` | MANUAL | none in scoped code | retained |
| `tests/flipfix_checks.inc` | LIVE | `Makefile`, `tests/core_concurrency_unit.cc` | retained |
| `tests/fliplisten.py` | LIVE | `tests/gate.sh` | retained |
| `tests/flipreport_checks.inc` | LIVE | `Makefile`, `tests/core_concurrency_unit.cc`, `tools/flipreport_proof.py` | retained |
| `tests/flipsettle_checks.inc` | LIVE | `Makefile`, `tests/core_concurrency_unit.cc`, `tools/flipsettle_controls.py` | retained |
| `tests/flush_capture.py` | MANUAL | none in scoped code | retained |
| `tests/flushfix2.py` | LIVE | `tests/flipfix5.py`, `tests/flushfix2_siblings.py`, `tests/gate.sh` | retained |
| `tests/flushfix2_fixture.h` | LIVE | `tests/multidb_unit.cc`, `tests/storesize_unit.cc`, `tools/flushfix2_verification_receipts.py` | retained |
| `tests/flushfix2_r3.cc` | MANUAL | none in scoped code | retained |
| `tests/flushfix2_siblings.py` | LIVE | `tests/flipfix5.py`, `tests/gate.sh`, `tools/flushfix2_sweep.py` | retained |
| `tests/flushfix2_unit.cc` | MANUAL | none in scoped code | retained |
| `tests/flushfix3.py` | LIVE | `tests/gate.sh` | retained |
| `tests/flushfix3_unit.cc` | LIVE | `tools/flushfix3_work_reference.py` | retained |
| `tests/flushfix_checks.py` | LIVE; TEXT-MATCHER | `Makefile`, `tests/gate.sh`, `tools/iopass_validate.py` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tests/flushfix_unit.cc` | MANUAL | none in scoped code | retained |
| `tests/foreign_read_safety_test.cc` | LIVE | `tests/gate.sh`, `tests/mutants.py` | retained |
| `tests/gate.sh` | LIVE; TEXT-MATCHER | `tests/abba_instrument.py`, `tests/abbagate.py`, `tests/at15_gate_test.py`, `tests/cd13b_oracle.sh`, `tests/differ_fanout_test.py`, `tests/execabort_watch_gate_test.py`, `tests/gate_history.py`, `tests/gate_ledger_fixture.py`, `tests/gate_receipt.py`, `tests/gate_subset_test.py`, `tests/gateprod.py`, `tests/gates_test.py`, `tests/lottery_attempt.py`, `tests/mutants.py`, `tests/redis_tcl_test.py`, `tests/rlfix5_gate_test.py`, `tests/tailgen_stall.py`, `tools/aoffix2_proof.py`, `tools/at412c_proof.py`, `tools/atomfix6_proof.py`, `tools/blockfix3_proof.py`, `tools/blockfix4_proof.py`, `tools/blockfix4_verify.py`, `tools/blockfix_climon.py`, `tools/ccfix3_wire.sh`, `tools/ccfix5_probe.sh`, `tools/cfgfix2_gate.py`, `tools/cfgfix2_units.py`, `tools/cmdfix2_final_main.py`, `tools/cmdfix2_freshness.py`, `tools/cmdfix2_more_jobs.py`, `tools/cmdfix2_related_jobs.py`, `tools/ctlfix_artifacts.py`, `tools/eoffix.py`, `tools/eoffix_verify.py`, `tools/exec1s_finish_proof.py`, `tools/exec1s_live_receipts.py`, `tools/exec1s_proof.py`, `tools/exec1sd_proof.py`, `tools/exec1sd_save_full.py`, `tools/execfifo2_freshness.py`, `tools/execfifo2_validate.py`, `tools/execfifo3_freshness.py`, `tools/execfifo3_validate.py`, `tools/flipfix7_freshness.py`, `tools/flipfix7_negative.py`, `tools/flipfix7_proof.py`, `tools/flushfix2_freshness.py`, `tools/flushfix2_verification_receipts.py`, `tools/flushfix2_verify.py`, `tools/flushfix3_freshness.py`, `tools/flushfix3_receipts.py`, `tools/flushfix3_verify.py`, `tools/infofields2_live.py`, `tools/lualibs_proof.sh`, `tools/mset8fix_loop.sh`, `tools/netfix2_diagnostics.py`, `tools/netfix2_proof.sh`, `tools/netfix_verify.py`, `tools/parkwake_loop.sh`, `tools/persistfmt_validate.py`, `tools/rlfix5_validate.py`, `tools/rootcore_freshness.py`, `tools/rootcore_proof.py`, `tools/rootcore_scheduler.py`, `tools/scriptfix3_jobs.py`, `tools/snapfix2_artifacts.py`, `tools/snapfix2_verify.py`, `tools/storefix5_audit.py`, `tools/storefix5_final_proof.py`, `tools/storefix5_inventory_proof.py`, `tools/storefix5_notification_proof.py`, `tools/storefix5_serial_proof.py`, `tools/trackorder_run.py`, `tools/trackorder_units.py`, `tools/txnfix4_proof.py`, `tools/wave14.py`, `tools/wave14_coverage.py`, `tools/wave15.py`, `tools/woundfix_gate.py` | Existing job/label inventory retained; added source-tool tests inside the existing R7 parity row. No row or EXPECT change. |
| `tests/gate_history.py` | LIVE | `tests/abba_instrument.py`, `tests/differ_fanout.py`, `tests/gate.sh`, `tests/gate_ledger_fixture.py`, `tests/gate_receipt.py`, `tests/gates_test.py` | retained |
| `tests/gate_ledger_fixture.py` | LIVE | `tests/gate_receipt.py`, `tools/ctlfix_artifacts.py`, `tools/wave14.py`, `tools/wave14_coverage.py`, `tools/wave15.py` | retained |
| `tests/gate_measurements.json` | LIVE | `tests/_nullrefresh_test.py`, `tests/abbagate.py`, `tests/gate_measurements.py`, `tests/gate_receipt.py`, `tests/gateplan.py`, `tests/load_calibration.py`, `tests/nullpublish_refreeze_test.py`, `tools/mdbqsbr_artifacts.py`, `tools/mkprobe_probe.py`, `tools/nullpublish_refreeze.py` | retained |
| `tests/gate_measurements.py` | LIVE | `tests/_nullrefresh_test.py`, `tests/abba_ceiling.py`, `tests/abba_reorder_control.py`, `tests/abbagate.py`, `tests/flushfix_checks.py`, `tests/gate.sh`, `tests/gate_receipt.py`, `tests/gateplan.py`, `tests/gateprod.py`, `tests/gates_test.py`, `tests/ttlcell_test.py`, `tools/mkprobe_probe.py` | retained |
| `tests/gate_perf_evidence.json` | MANUAL | none in scoped code | retained |
| `tests/gate_perf_refs.json` | LIVE | `tests/perf_gate.py` | retained |
| `tests/gate_process_test.py` | LIVE | `tests/gate.sh`, `tests/gates_test.py` | retained |
| `tests/gate_product_evidence.py` | LIVE | `tests/gate_receipt.py`, `tests/gateprod.py` | retained |
| `tests/gate_quiet.py` | LIVE | `tests/abba_aslr.py`, `tests/abba_saturation_controls.py`, `tests/abbagate.py`, `tests/gate.sh`, `tests/gateprod.py`, `tests/gates_test.py`, `tests/perfex_checks.py`, `tools/exbatch_directed.py`, `tools/mkprobe_probe.py` | retained |
| `tests/gate_receipt.py` | LIVE | `tests/_nullrefresh_test.py`, `tests/abba_binaries.py`, `tests/abba_instrument.py`, `tests/abba_saturation_controls.py`, `tests/abba_standing_null.py`, `tests/abbagate.py`, `tests/gate.sh`, `tests/gate_ledger_fixture.py`, `tests/gate_product_evidence.py`, `tests/gate_subset_test.py`, `tests/gates_test.py` | retained |
| `tests/gate_refs.txt` | LIVE | `tests/gate.sh`, `tests/gates_test.py` | retained |
| `tests/gate_subset.sh` | LIVE | `tests/gate.sh`, `tests/gate_subset_test.py`, `tests/gates_test.py` | retained |
| `tests/gate_subset_test.py` | LIVE | `tests/gate.sh`, `tests/gates_test.py` | retained |
| `tests/gateplan.py` | LIVE | `tests/abba_experiments.py`, `tests/abba_reorder_control.py`, `tests/abbagate.py`, `tests/gate.sh`, `tests/gate_quiet.py`, `tests/gate_receipt.py`, `tests/gates_test.py`, `tests/mode_equivalence.py`, `tools/exbatch_directed.py`, `tools/mkprobe_probe.py` | retained |
| `tests/gateprod-evidence/SHA256SUMS` | MANUAL | `tools/atomiccollapse_artifacts.py`, `tools/boot_support_artifacts.py`, `tools/exec1s_build.py`, `tools/exec1sd.py`, `tools/exec1sd_pad.py`, `tools/execfifo3_artifacts.py`, `tools/flipsettle_artifacts.py`, `tools/netfix2_artifacts.py` | retained |
| `tests/gateprod-evidence/abba-selftest.log.gz` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/changed-text-audit.json` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/changed-text-audit.txt.gz` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/changed-text-before.txt` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/changed-text-patterns.txt.gz` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/final-merge.txt` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/floor-schema-control.txt` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/frozen-before.json` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/gate-wiring-selftest.log.gz` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/instrument-after.json` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/instrument-before.json` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/instrument-selftest.log.gz` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/ledger-proof.log.gz` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/matrix.json.gz` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/netio-selftest.log.gz` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/product-selftest.log.gz` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/production.diff` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/proof.json` | LIVE | `tests/signalacct_source_checks.py`, `tools/atomiccollapse_artifacts.py`, `tools/deadcode2_pad.py`, `tools/deadfused_artifacts.py`, `tools/exbatch_artifacts.py`, `tools/exbatch_directed.py`, `tools/exbatch_source_proof.py`, `tools/exec1s_finish_proof.py`, `tools/exec1s_live_receipts.py`, `tools/exec1sd_receipts.py`, `tools/flipreport_proof.py`, `tools/iotemplates_proof.py`, `tools/lbosc3_pad.py`, `tools/lbplanner_pad.py`, `tools/lbplanner_receipts.py`, `tools/overlapaxe_artifacts.py`, `tools/probeadapter_proof.py`, `tools/readreply_proof.py`, `tools/rlfence_artifacts.py`, `tools/rlfix3_pad.py`, `tools/scriptfix3_receipts.py`, `tools/storefix5_final_proof.py`, `tools/storefix5_finish_proof.py`, `tools/storefix5_inventory_proof.py`, `tools/storefix5_notification_proof.py`, `tools/storefix5_serial_proof.py` | retained |
| `tests/gateprod-evidence/quiet-1.json.gz` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/quiet-1.jsonl.gz` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/quiet-2.json.gz` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/quiet-2.jsonl.gz` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/quiet-3.json.gz` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/quiet-3.jsonl.gz` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/quiet-4.json.gz` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/quiet-4.jsonl.gz` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/smoke-driver.log` | MANUAL | none in scoped code | retained |
| `tests/gateprod-evidence/smoke.json` | LIVE | `tests/gateprod.py`, `tools/execfifo2_control_smoke.py`, `tools/execfifo3_control_smoke.py`, `tools/execindex_control_smoke.py`, `tools/overlapaxe_artifacts.py` | retained |
| `tests/gateprod-evidence/uring-line-sha256.json` | MANUAL | none in scoped code | retained |
| `tests/gateprod.py` | LIVE | `tests/gate.sh`, `tests/gates_test.py` | retained |
| `tests/gaterows_contract_test.py` | MANUAL | none in scoped code | retained |
| `tests/gates_test.py` | LIVE; TEXT-MATCHER | `tests/gate.sh`, `tools/atomfix6_final.py`, `tools/atomfix6_proof.py`, `tools/eoffix_final.py`, `tools/exec1s_finish_proof.py`, `tools/exec1s_proof.py`, `tools/exec1sd_proof.py`, `tools/exec1sd_receipts.py`, `tools/rootcore_scheduler.py`, `tools/storefix5_final_proof.py`, `tools/storefix5_finish_proof.py`, `tools/storefix5_report.py` | Gate shell/receipt parser tests; all current source references remain explicit and fixture-checked. |
| `tests/geo.py` | LIVE | `tests/gate.sh` | retained |
| `tests/globcase.py` | LIVE | `tests/gate.sh` | retained |
| `tests/headline_cells.txt` | LIVE | `tests/_nullrefresh_test.py`, `tests/abba_aslr.py`, `tests/abba_experiments.py`, `tests/abba_reorder_control.py`, `tests/abba_saturation_controls.py`, `tests/abbagate.py`, `tests/gate_measurements.py`, `tests/gate_receipt.py`, `tests/gateprod.py`, `tests/nullpublish_refreeze_test.py`, `tools/mkprobe_probe.py`, `tools/nullpublish_refreeze.py` | retained |
| `tests/hexpire.py` | LIVE | `tests/debug_load_test.py`, `tests/gate.sh`, `tests/hexpire_persist.sh` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/hexpire_oom_checks.inc` | LIVE | `Makefile`, `tests/netcmd_unit.cc` | retained |
| `tests/hexpire_persist.sh` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/hexpread.py` | LIVE | `tests/gate.sh`, `tests/objectpread.py` | retained |
| `tests/infofields_test.py` | MANUAL | none in scoped code | retained |
| `tests/infofields_unit.cc` | MANUAL | `tools/infofields_controls.py` | retained |
| `tests/infofix.py` | LIVE | `tests/gate.sh`, `tools/infofields2_live.py`, `tools/ntfix_proof.py` | retained |
| `tests/infofix_compat.py` | LIVE | `tests/gate.sh`, `tests/rootcompat.py`, `tests/wave15_errorstats.py` | retained |
| `tests/infofix_latency_unit.cc` | LIVE | `tools/infofix_latency.mk`, `tools/infofix_latency_controls.py` | retained |
| `tests/inline_protocol.py` | LIVE | `tests/gate.sh` | retained |
| `tests/inline_quoted.py` | LIVE | `tests/gate.sh` | retained |
| `tests/iofix_deferred.py` | LIVE | `tests/gate.sh` | retained |
| `tests/iofix_hz.py` | LIVE | `tests/gate.sh` | retained |
| `tests/iofix_signal.py` | LIVE | `tests/gate.sh` | retained |
| `tests/iofix_sleep.py` | LIVE | `tests/gate.sh` | retained |
| `tests/iopass_checks.inc` | MANUAL | `tools/iopass_receipts.py` | retained |
| `tests/iowake.py` | LIVE | `tests/gate.sh` | retained |
| `tests/knobs.py` | LIVE | `tests/gate.sh` | retained |
| `tests/known_difference.py` | LIVE | `tests/aclfix.py`, `tests/aclreply.py`, `tests/datafix1_bitfield.py`, `tests/datafix1_locale.py`, `tests/infofix_compat.py`, `tests/netcmd.py`, `tests/netfix_config.py`, `tests/psfix.py`, `tests/rootcore.py`, `tests/serverfix_config.py` | retained |
| `tests/ktls_keyupdate.cc` | LIVE | `Makefile` | retained |
| `tests/ktls_keyupdate_unit.cc` | LIVE | `Makefile` | retained |
| `tests/ktls_lifetime.py` | MANUAL | none in scoped code | retained |
| `tests/ktls_lifetime_unit.cc` | LIVE | `Makefile` | retained |
| `tests/kvobj_header_unit.cc` | LIVE | `Makefile` | retained |
| `tests/l4_cells.txt` | LIVE | `tests/abbagate.py` | retained |
| `tests/l4prebuild_unit.cc` | LIVE | `Makefile` | retained |
| `tests/lanefull_checks.inc` | LIVE | `Makefile`, `tests/core_concurrency_unit.cc` | retained |
| `tests/latencyfix.py` | LIVE | `tests/gate.sh`, `tests/wave8.py`, `tests/wave8b.py` | retained |
| `tests/latencyfix_counts.cc` | MANUAL | `tools/latencyfix_counts.mk` | retained |
| `tests/latencyfix_histogram_unit.cc` | MANUAL | `tools/latencyfix_histogram.mk` | retained |
| `tests/layout_placement.cc` | LIVE | `Makefile` | retained |
| `tests/lb_stationary.py` | LIVE | `tests/gate.sh`, `tests/gates_test.py` | retained |
| `tests/lbplanner_checks.py` | LIVE | `tests/gate.sh`, `tools/iopass_validate.py` | retained |
| `tests/lbplanner_unit.cc` | LIVE | `Makefile`, `tools/lbplanner_pre_receipt.py` | retained |
| `tests/lbsignals.py` | LIVE | `tests/gate.sh` | retained |
| `tests/lcs.py` | MANUAL | none in scoped code | retained |
| `tests/legacy_reorder_witness.py` | LIVE | `tests/abba_instrument.py`, `tests/abba_reorder_control.py`, `tests/abbagate.py` | retained |
| `tests/limits.py` | MANUAL | none in scoped code | retained |
| `tests/list_namespace.mk` | LIVE | `tests/gate.sh` | retained |
| `tests/list_namespace_unit.cc` | LIVE | `tests/list_namespace.mk` | retained |
| `tests/load_calibration.py` | LIVE | `tests/_nullrefresh_test.py`, `tests/abba_reorder_control.py`, `tests/abbagate.py`, `tests/gate_measurements.py` | retained |
| `tests/loading_ready_test.py` | MANUAL | none in scoped code | retained |
| `tests/lottery_attempt.py` | LIVE | `tests/lottery_runner.py`, `tests/lottery_runner_test.py`, `tools/exec1sd_lottery.py` | retained |
| `tests/lottery_calibration.py` | MANUAL | `tests/lottery_runner_test.py` | retained |
| `tests/lottery_evidence.py` | LIVE | `tests/lottery_attempt.py`, `tests/lottery_evidence_test.py` | retained |
| `tests/lottery_evidence_test.py` | MANUAL | none in scoped code | retained |
| `tests/lottery_hooks.h` | LIVE | `Makefile`, `tools/lottery_build.py` | retained |
| `tests/lottery_nightly.sh` | LIVE | `tests/gate.sh` | Added a single-row gate entry for bounded correctness checks; default nightly selection is unchanged. |
| `tests/lottery_rows.json` | LIVE | `tests/lottery_runner.py`, `tools/exec1sd_lottery.py` | retained |
| `tests/lottery_runner.py` | LIVE | `tests/lottery_attempt.py`, `tests/lottery_calibration.py`, `tests/lottery_evidence_test.py`, `tests/lottery_nightly.sh`, `tests/lottery_runner_test.py`, `tools/exec1sd_lottery.py` | retained |
| `tests/lottery_runner_test.py` | MANUAL | none in scoped code | retained |
| `tests/lottery_test_driver.py` | LIVE; TEXT-MATCHER | `tests/lottery_attempt.py`, `tests/lottery_runner_test.py` | AST edits at stable Python comments; unique calls and nonempty sleep inventory. |
| `tests/lru_slow.sh` | MANUAL | none in scoped code | retained |
| `tests/lua_scripting.py` | LIVE | `tests/gate.sh` | retained |
| `tests/lualibs_memory.cc` | MANUAL | `tools/lualibs_artifacts.py` | retained |
| `tests/maskflood.py` | MANUAL | none in scoped code | retained |
| `tests/matrix.sh` | LIVE | `tests/gate.sh`, `tests/gates_test.py` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/maxmemrace.py` | LIVE | `tests/clientcompat.py`, `tests/gate.sh` | retained |
| `tests/maxmemrace_run.py` | MANUAL | none in scoped code | retained |
| `tests/maxmemrace_stress.cc` | MANUAL | none in scoped code | retained |
| `tests/mdbqsbr_checks.py` | LIVE | `tests/gate.sh`, `tools/iopass_validate.py` | retained |
| `tests/mdbqsbr_live.py` | LIVE; TEXT-MATCHER | `tests/gate.sh`, `tests/gates_test.py`, `tests/mdbqsbr_live_test.py`, `tests/signalacct_live.py` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tests/mdbqsbr_live_test.py` | MANUAL | none in scoped code | retained |
| `tests/mdbqsbr_probe.cc` | MANUAL | none in scoped code | retained |
| `tests/mdbqsbr_unit.cc` | MANUAL | none in scoped code | retained |
| `tests/mdbstamp_checks.cc` | MANUAL | none in scoped code | retained |
| `tests/mdbstamp_controls.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tests/mdbstamp_controls.py` |
| `tests/mkfix2_unit.cc` | MANUAL | none in scoped code | retained |
| `tests/mkprobe_cells.txt` | LIVE | `tests/gateprod.py`, `tools/mkprobe_probe.py`, `tools/overlapaxe_artifacts.py` | retained |
| `tests/mode_equivalence.py` | LIVE | `tests/differ_fanout.py`, `tests/differ_fanout_test.py`, `tests/differ_gate.sh`, `tools/storefix5_finish_proof.py` | retained |
| `tests/mode_lane.py` | MANUAL | none in scoped code | retained |
| `tests/moverfix.py` | LIVE | `tests/gate.sh`, `tests/txn_movers.py` | retained |
| `tests/moverfix_unit.cc` | LIVE | `Makefile` | retained |
| `tests/multi_exec.py` | LIVE | `tests/gate.sh` | retained |
| `tests/multidb.py` | LIVE | `tests/gate.sh`, `tests/gates_test.py` | retained |
| `tests/multidb_boundary_unit.cc` | LIVE | `Makefile` | retained |
| `tests/multidb_cost_unit.cc` | LIVE | `Makefile` | retained |
| `tests/multidb_db0_unit.cc` | MANUAL | none in scoped code | retained |
| `tests/multidb_layout.cc` | MANUAL | `tools/ccfix3_prove.py` | retained |
| `tests/multidb_serial.py` | LIVE | `tests/gate.sh`, `tests/gates_test.py`, `tests/mdbqsbr_live.py`, `tools/iopass_validate.py` | retained |
| `tests/multidb_unit.cc` | MANUAL | `tools/flushfix2_verification_receipts.py` | retained |
| `tests/multifix.py` | LIVE | `tests/gate.sh` | retained |
| `tests/multirace.py` | MANUAL | none in scoped code | retained |
| `tests/multires.py` | MANUAL | none in scoped code | retained |
| `tests/mutants.py` | MANUAL; TEXT-MATCHER | `tests/mutants.sh` | retained |
| `tests/mutants.registry` | MANUAL | `tests/mutants.py` | retained |
| `tests/mutants.sh` | MANUAL | none in scoped code | retained |
| `tests/netcap.py` | LIVE | `tests/gate.sh`, `tests/respresume.py`, `tools/ntfix_proof.py` | retained |
| `tests/netcap_unit.cc` | MANUAL | none in scoped code | retained |
| `tests/netcmd.py` | MANUAL | none in scoped code | retained |
| `tests/netcmd_config_unit.cc` | LIVE | `Makefile` | retained |
| `tests/netcmd_stream_unit.cc` | LIVE | `Makefile` | retained |
| `tests/netcmd_unit.cc` | LIVE | `Makefile` | retained |
| `tests/netcmd_unit.h` | LIVE | `Makefile`, `tests/encodingfix_unit.cc`, `tests/netcmd_config_unit.cc`, `tests/netcmd_stream_unit.cc`, `tests/netcmd_unit.cc`, `tests/netcmd_zset_unit.cc` | retained |
| `tests/netcmd_zset_unit.cc` | LIVE | `Makefile` | retained |
| `tests/netfix2.py` | LIVE | `tests/gate.sh`, `tests/netfix_unix.py` | retained |
| `tests/netfix2.tcl` | LIVE | `tests/netfix2.py` | retained |
| `tests/netfix2_audit.py` | FINISHED-LANE | `tools/netfix2_proof.sh` | moved unchanged to `tools/archive/tests/netfix2_audit.py` |
| `tests/netfix_config.py` | LIVE | `tests/gate.sh` | retained |
| `tests/netfix_idle_buffers.py` | LIVE; TEXT-MATCHER | `tests/gate.sh` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tests/netfix_query_stats.py` | LIVE | `tests/gate.sh` | retained |
| `tests/netfix_tls.py` | LIVE | `tests/gate.sh` | retained |
| `tests/netfix_unix.py` | LIVE | `tests/gate.sh` | retained |
| `tests/netio.py` | LIVE | `tests/gate.sh`, `tests/gates_test.py` | retained |
| `tests/netio_cells.txt` | LIVE | `tests/_nullrefresh_test.py`, `tests/gate_product_evidence.py`, `tests/gate_receipt.py`, `tests/gateprod.py` | retained |
| `tests/niclib.sh` | LIVE | `tests/gate.sh`, `tests/gates_test.py` | retained |
| `tests/notify.py` | LIVE | `tests/gate.sh` | retained |
| `tests/notify_order.py` | LIVE | `tests/gate.sh` | retained |
| `tests/notify_order_checks.inc` | LIVE | `Makefile`, `tests/netcmd_unit.cc` | retained |
| `tests/notifycompat.py` | LIVE | `tests/gate.sh`, `tests/tracking_redirect.py` | retained |
| `tests/ntnew4_clock.py` | LIVE | `tests/gate.sh` | retained |
| `tests/nullpublish4_test.py` | LIVE | `tests/gate_receipt.py` | retained |
| `tests/nullpublish_refreeze_test.py` | LIVE; TEXT-MATCHER | `tests/gate_receipt.py` | Gate/receipt parser tests; unaffected by production C++ formatting. |
| `tests/objectpread.py` | LIVE | `tests/gate.sh` | retained |
| `tests/orthog.py` | MANUAL | none in scoped code | retained |
| `tests/owner_arena_unit.cc` | LIVE | `Makefile`, `tests/l4prebuild_unit.cc` | retained |
| `tests/owner_prefetch_unit.cc` | LIVE | `Makefile` | retained |
| `tests/parbuild.sh` | LIVE | `tests/gate.sh`, `tests/gate_history.py`, `tests/gates_test.py` | retained |
| `tests/parkwake.py` | LIVE | `tests/gate.sh`, `tools/parkwake_matrix.py` | retained |
| `tests/parkwake_parser_scope.cc` | MANUAL | `tools/parkwake_counts.py` | retained |
| `tests/parkwake_slowsync.c` | LIVE | `Makefile` | retained |
| `tests/parkwake_unit.cc` | LIVE | `Makefile` | retained |
| `tests/perf_gate.py` | LIVE | `tests/gates_test.py` | retained |
| `tests/perfex_checks.py` | LIVE; TEXT-MATCHER | `tests/gate.sh` | Canonical stable roles for ELF bodies and call operands; exact six/four body counts retained. |
| `tests/perfio.py` | LIVE | `tests/gate.sh` | retained |
| `tests/persistfix.py` | LIVE | `tests/gate.sh`, `tests/gates_test.py`, `tests/persistfix2.py`, `tests/psfix.py`, `tests/savefix.py`, `tests/shutsave.py`, `tools/aoffix2_proof.py` | retained |
| `tests/persistfix2.py` | LIVE | `tests/gate.sh`, `tests/rootcore.py`, `tests/wave14_eof_data.py`, `tests/wave14_functions.py`, `tests/wave14_order.py` | retained |
| `tests/persistfix_checks.py` | LIVE | `tests/gate.sh`, `tests/gates_test.py`, `tools/iopass_validate.py` | retained |
| `tests/persistfix_unit.cc` | LIVE | `Makefile` | retained |
| `tests/persistfmt.py` | LIVE | `tests/gate.sh` | retained |
| `tests/persistfmt_snapshot_scope.inc` | MANUAL | `tools/persistfmt_counts.py` | retained |
| `tests/pipeorder.py` | LIVE | `tests/gate.sh` | retained |
| `tests/probeadapter_checks.h` | LIVE | `Makefile`, `tests/multidb_db0_unit.cc`, `tests/multidb_unit.cc`, `tests/rehash_waits_unit.cc`, `tools/probeadapter_proof.py` | retained |
| `tests/psfix.py` | MANUAL; TEXT-MATCHER | `tests/psfix_test.py`, `tests/shutsave.py` | retained |
| `tests/psfix_test.py` | MANUAL | none in scoped code | retained |
| `tests/publishfix_e2e.py` | MANUAL | none in scoped code | retained |
| `tests/publishfix_model.py` | MANUAL | none in scoped code | retained |
| `tests/publishfix_unit.cc` | LIVE | `Makefile` | retained |
| `tests/pubsub.py` | LIVE | `tests/gate.sh` | retained |
| `tests/pubtrackfix.py` | LIVE | `tests/gate.sh` | retained |
| `tests/push_tear_repro.py` | MANUAL | none in scoped code | retained |
| `tests/pushtear.py` | MANUAL | none in scoped code | retained |
| `tests/r7shadow_instr.cc` | LIVE | `Makefile` | retained |
| `tests/r7shadow_mutants.py` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/r7shadow_noop.py` | LIVE; TEXT-MATCHER | `tests/reorder_receipt.py`, `tests/signalacct_byte_checks.py` | Shared ELF/name canonicalization; existing body/clone/instruction controls retained. |
| `tests/r7shadow_pad.py` | LIVE; TEXT-MATCHER | `Makefile`, `tests/reorder_receipt.py`, `tests/reordertrim.py`, `tools/deadcode2_pad.py` | Shared ELF role canonicalization; nonempty capability inventory and exact opcode checks retained. |
| `tests/r7shadow_split_unit.cc` | LIVE | `Makefile` | retained |
| `tests/r7shadow_split_witness.py` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/r7shadow_sync.py` | LIVE; TEXT-MATCHER | `Makefile`, `tests/gate.sh`, `tests/r7shadow_split_witness.py`, `tests/r7shadow_sync_test.py`, `tests/signalacct_source_checks.py`, `tests/splitlocal_checks.py`, `tests/wbland_checks.py`, `tools/eoffix_source_sync.py`, `tools/exec1s_build.py`, `tools/iopass_validate.py`, `tools/iotemplates_proof.py`, `tools/reorder_sync.py`, `tools/rlfix5_refreeze_comments.py`, `tools/signalacct_artifacts.py`, `tools/wb_rule_2s_artifacts.py` | Stable function comments, token parity, required nonempty policy inventory; rename-aware regeneration. |
| `tests/r7shadow_sync_test.py` | LIVE; TEXT-MATCHER | `Makefile`, `tests/gate.sh` | Whole-source scratch copy preserves type/callee role bindings; stale-copy and regeneration controls retained. |
| `tests/r7shadow_unit.cc` | LIVE | `Makefile`, `tests/r7shadow_mutants.py` | retained |
| `tests/r7shadow_witness.h` | LIVE | `Makefile` | retained |
| `tests/racefix.py` | LIVE; TEXT-MATCHER | `tests/gate.sh` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tests/racefix_hook.h` | LIVE | `Makefile`, `tools/racefix_build.py` | retained |
| `tests/read_local_lane.py` | LIVE | `tests/deadfused_checks.py`, `tests/gate.sh`, `tools/iopass_validate.py` | retained |
| `tests/read_local_lfu.py` | MANUAL | none in scoped code | retained |
| `tests/read_local_ring_unit.cc` | LIVE | `Makefile` | retained |
| `tests/read_local_write_ring_unit.cc` | LIVE | `Makefile`, `tests/gate.sh`, `tests/mutants.py`, `tools/rlfence_artifacts.py` | retained |
| `tests/redis_tcl.py` | LIVE | `tests/blockfix2_repro.py`, `tests/climonfix4.py`, `tests/gate.sh`, `tests/gates_test.py`, `tests/redis_tcl_test.py`, `tools/blockfix2_controls.py`, `tools/blockfix3_controls.py`, `tools/blockfix3_proof.py`, `tools/blockfix3_repro.py`, `tools/blockfix3_tcl_compare.py`, `tools/exec1sd_slowlog.py`, `tools/scriptfix2_negative.py` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/redis_tcl_passing.json` | LIVE | `tests/gate.sh`, `tests/redis_tcl.py`, `tools/blockfix2_controls.py`, `tools/blockfix3_repro.py`, `tools/blockfix3_tcl_compare.py`, `tools/scriptfix2_negative.py`, `tools/wave14_arms.py` | retained |
| `tests/redis_tcl_test.py` | LIVE | `tests/gate.sh`, `tests/gates_test.py` | retained |
| `tests/redisgap.py` | MANUAL | none in scoped code | retained |
| `tests/redisgap_atomic.py` | MANUAL | none in scoped code | retained |
| `tests/rehash_readonly.py` | LIVE | `tests/gate.sh`, `tests/resizefix.py` | retained |
| `tests/rehash_waits_unit.cc` | LIVE | `Makefile` | retained |
| `tests/reorder_batch_fixture.h` | LIVE | `Makefile`, `tests/r7shadow_unit.cc`, `tests/reorder_unit.cc` | retained |
| `tests/reorder_engagement_unit.cc` | LIVE | `Makefile`, `tests/r7shadow_split_unit.cc`, `tests/reorderscan_paths.cc`, `tests/reordertrim.py`, `tools/iotemplates_proof.py` | retained |
| `tests/reorder_flip.py` | MANUAL | none in scoped code | retained |
| `tests/reorder_noop.py` | LIVE; TEXT-MATCHER | `tests/deadfused_checks.py`, `tests/r7shadow_noop.py`, `tests/reorder_receipt.py`, `tools/ctlfix_artifacts.py`, `tools/iofix3_artifacts.py`, `tools/lualibs_artifacts.py`, `tools/netfix_identity.py`, `tools/prefetch_artifacts.py`, `tools/rlfence_artifacts.py`, `tools/rltopo_artifacts.py`, `tools/serverfix_identity.py` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tests/reorder_receipt.py` | LIVE | `Makefile`, `tests/gate.sh`, `tools/iopass_validate.py` | retained |
| `tests/reorder_scope.py` | MANUAL; TEXT-MATCHER | `tests/reorder_scope_test.py` | retained |
| `tests/reorder_scope_test.py` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/reorder_unit.cc` | LIVE | `Makefile` | retained |
| `tests/reorderscan_gate.py` | LIVE | `tests/gate.sh` | retained |
| `tests/reorderscan_paths.cc` | LIVE | `Makefile` | retained |
| `tests/reorderscan_unit.cc` | LIVE | `Makefile` | retained |
| `tests/reorderscan_witness.h` | LIVE | `Makefile`, `tests/reorderscan_paths.cc` | retained |
| `tests/reordertrim.py` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/reorderwb_cells.txt` | MANUAL | none in scoped code | retained |
| `tests/replyoff_xshard.py` | LIVE | `tests/gate.sh` | retained |
| `tests/replyschema.py` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/resizefix.py` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/resp3.py` | MANUAL | none in scoped code | retained |
| `tests/respcompat.py` | LIVE | `tests/gate.sh`, `tests/inline_protocol.py`, `tests/respcompat_replay.py`, `tests/respcompat_test.py`, `tools/ntfix_proof.py` | retained |
| `tests/respcompat_audit.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tests/respcompat_audit.py` |
| `tests/respcompat_pad.py` | MANUAL | none in scoped code | retained |
| `tests/respcompat_replay.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tests/respcompat_replay.py` |
| `tests/respcompat_test.py` | MANUAL | none in scoped code | retained |
| `tests/respcompat_unit.cc` | MANUAL | none in scoped code | retained |
| `tests/respresume.py` | LIVE | `tests/gate.sh`, `tools/ntfix_proof.py` | retained |
| `tests/respresume_cells.txt` | MANUAL | none in scoped code | retained |
| `tests/respresume_differ_frag.py` | MANUAL | none in scoped code | retained |
| `tests/respresume_flip.py` | MANUAL | none in scoped code | retained |
| `tests/respresume_limits.py` | LIVE | `tests/respcompat.py`, `tools/ntfix_proof.py` | retained |
| `tests/respresume_migration.cc` | LIVE | `Makefile` | retained |
| `tests/respresume_unit.cc` | LIVE | `Makefile` | retained |
| `tests/rl2s.py` | MANUAL | none in scoped code | retained |
| `tests/rlcache_churn.py` | LIVE | `tests/gate.sh`, `tests/mutants.py`, `tests/rlcache_churn_test.py` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/rlcache_churn_test.py` | MANUAL | none in scoped code | retained |
| `tests/rlfence_unit.cc` | LIVE | `Makefile`, `tests/rob_portable_control.py`, `tools/rlfence_artifacts.py` | retained |
| `tests/rlfix.py` | LIVE | `tests/gate.sh` | retained |
| `tests/rlfix3_info.py` | LIVE | `tests/gate.sh` | retained |
| `tests/rlfix3_info_unit.cc` | MANUAL | `tools/rlfix3_units.py` | retained |
| `tests/rlfix3_lifetime.cc` | LIVE | `tests/gate.sh` | retained |
| `tests/rlfix3_zc.py` | LIVE | `tests/gate.sh` | retained |
| `tests/rlfix5.py` | LIVE | `tests/gate.sh` | retained |
| `tests/rlfix5_gate_test.py` | LIVE | `tests/gate.sh` | retained |
| `tests/rlfix5_scope.cc` | LIVE | `tools/rlfix5.mk`, `tools/rlfix5_proof.py` | retained |
| `tests/rltopo_unit.cc` | MANUAL | `tools/readreply_proof.py` | retained |
| `tests/rob_portable_control.py` | LIVE; TEXT-MATCHER | `tests/gate.sh` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tests/rootcompat.py` | LIVE | `tests/gate.sh` | retained |
| `tests/rootcompat_proc_fault.c` | LIVE | `tests/gate.sh` | retained |
| `tests/rootcompat_tracking/resp.py` | LIVE | `tests/blockfix4_repro/item1_natural.py`, `tests/blockfix4_repro/item1_script_push.py`, `tests/blockfix4_repro/item2_move_nil.py`, `tests/blockfix4_repro/item4_creators.py`, `tests/blockfix4_repro/item5_stream_removed.py`, `tests/blockfix4_repro/item6_mpop_null.py`, `tests/blockfix4_repro/lib/srv.py`, `tests/netfix2_audit.py`, `tests/rootcompat_tracking/srv.py`, `tests/rootcompat_tracking/t1_xsnotify.py`, `tests/rootcompat_tracking/t3_keylesscap.py`, `tests/txnfix_audit/t01_exec_counter.py`, `tests/txnfix_audit/t02_exec_directed.py`, `tests/txnfix_audit/t02b_exec_vs_exec.py`, `tests/txnfix_audit/t03_mover_replay.py`, `tests/txnfix_audit/t04_mover_stress.py`, `tests/txnfix_audit/t05_mover_only.py`, `tests/txnfix_audit/t10_msetnx_hold.py`, `tests/txnfix_audit/t14_exec_window.py`, `tests/txnfix_audit/t15_exec_only_stress.py`, `tests/txnfix_audit/t17_queue_exec.py`, `tests/txnfix_audit/t18_watch_cas.py`, `tests/txnfix_audit/t19_crossed_watch.py`, `tools/atomfix6_audit.py`, `tools/wave15_scan_expiry.py` | retained |
| `tests/rootcompat_tracking/run.py` | LIVE | `tests/gate.sh` | retained |
| `tests/rootcompat_tracking/srv.py` | LIVE | `tests/blockfix4_repro/item1_natural.py`, `tests/blockfix4_repro/item1_script_push.py`, `tests/blockfix4_repro/item2_move_nil.py`, `tests/blockfix4_repro/item4_creators.py`, `tests/blockfix4_repro/item5_stream_removed.py`, `tests/blockfix4_repro/item6_mpop_null.py`, `tests/blockfix4_repro/lib/common.py`, `tests/rootcompat_tracking/run.py`, `tests/rootcompat_tracking/t1_xsnotify.py`, `tests/rootcompat_tracking/t3_keylesscap.py` | retained |
| `tests/rootcompat_tracking/t1_xsnotify.py` | LIVE | `tests/rootcompat_tracking/run.py` | retained |
| `tests/rootcompat_tracking/t3_keylesscap.py` | LIVE | `tests/rootcompat_tracking/run.py` | retained |
| `tests/rootcore.py` | LIVE | `tests/gate.sh`, `tools/rootcore_proof.py` | retained |
| `tests/rootcore_inbox.cc` | LIVE | `tools/rootcore_inbox.py` | retained |
| `tests/router_uniform.py` | MANUAL | none in scoped code | retained |
| `tests/ryow.py` | LIVE | `tests/atomic_ryow.py`, `tests/gate.sh` | retained |
| `tests/ryow_sort_repro.py` | MANUAL | none in scoped code | retained |
| `tests/s6.py` | MANUAL | none in scoped code | retained |
| `tests/savefix.py` | LIVE | `tests/gate.sh` | retained |
| `tests/scancompact.py` | MANUAL | none in scoped code | retained |
| `tests/scriptatomic.py` | LIVE | `tests/gaterows_contract_test.py`, `tests/scriptatomic_strict.py` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/scriptatomic_strict.py` | LIVE; TEXT-MATCHER | `tests/gate.sh` | AST insertion at a stable Python bootstrap comment; strict refusal assertions retained. |
| `tests/scriptfix.py` | LIVE | `tests/gate.sh` | retained |
| `tests/scriptfix2.py` | LIVE | `tests/scriptfix3.py` | retained |
| `tests/scriptfix2_counts.cc` | MANUAL | `tools/scriptfix2_counts.mk` | retained |
| `tests/scriptfix3.py` | LIVE | `tests/gate.sh` | retained |
| `tests/scriptfix3_scope.cc` | MANUAL | `tools/scriptfix3_counts.py` | retained |
| `tests/scriptfix4.py` | LIVE | `tests/gate.sh` | retained |
| `tests/scriptfix4_scope.cc` | MANUAL | `tools/scriptfix4_counts.py`, `tools/wave15_counts.py` | retained |
| `tests/scriptsurf.py` | MANUAL | none in scoped code | retained |
| `tests/serverfix_acllog.py` | LIVE | `tests/gate.sh` | retained |
| `tests/serverfix_alloc.cc` | LIVE | `tests/_serverfix_alloc.py`, `tests/latencyfix.py` | retained |
| `tests/serverfix_config.py` | LIVE; TEXT-MATCHER | `tests/gate.sh`, `tools/cfgfix_inventory.py` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tests/serverfix_hello.py` | LIVE | `tests/gate.sh` | retained |
| `tests/serverfix_hll.py` | LIVE | `tests/gate.sh` | retained |
| `tests/serverfix_lines.py` | LIVE | `tests/gate.sh` | retained |
| `tests/serverfix_scalar.py` | LIVE | `tests/gate.sh` | retained |
| `tests/serverfix_slowlog.py` | LIVE | `tests/gate.sh` | retained |
| `tests/serverfix_waitaof.py` | LIVE | `tests/gate.sh` | retained |
| `tests/servertail.py` | MANUAL | none in scoped code | retained |
| `tests/session_monotonic.py` | MANUAL | none in scoped code | retained |
| `tests/shutdown_client_checks.inc` | LIVE | `Makefile`, `tests/shutdown_unit.cc` | retained |
| `tests/shutdown_persist.py` | LIVE | `tests/gate.sh`, `tests/gates_test.py` | retained |
| `tests/shutdown_report.py` | LIVE | `tests/exec1s.py`, `tests/gate.sh`, `tests/gates_test.py`, `tests/lbsignals.py`, `tests/mutants.py`, `tests/persistfix.py`, `tests/persistfix_checks.py`, `tests/resizefix.py`, `tests/savefix.py`, `tests/signalacct_controls.py`, `tests/signalacct_live.py`, `tests/txnfix4.py`, `tools/cmdfix2_fifo_diagnostic.py` | retained |
| `tests/shutdown_unit.cc` | MANUAL | `tests/climonfix_artifacts.py` | retained |
| `tests/shutsave.py` | MANUAL | `tests/shutsave_test.py` | retained |
| `tests/shutsave_test.py` | MANUAL | none in scoped code | retained |
| `tests/shutsave_unit.cc` | MANUAL | none in scoped code | retained |
| `tests/signalacct_byte_checks.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tests/signalacct_byte_checks.py` |
| `tests/signalacct_checks.h` | LIVE | `Makefile`, `tests/flipctl_unit.cc`, `tests/signalacct_unit.cc` | retained |
| `tests/signalacct_controls.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tests/signalacct_controls.py` |
| `tests/signalacct_core_checks.inc` | LIVE | `Makefile`, `tests/core_concurrency_unit.cc`, `tests/signalacct_core_controls.py` | retained |
| `tests/signalacct_core_controls.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tests/signalacct_core_controls.py` |
| `tests/signalacct_live.py` | MANUAL | `tests/signalacct_live_test.py` | retained |
| `tests/signalacct_live_test.py` | MANUAL | none in scoped code | retained |
| `tests/signalacct_source_checks.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tests/signalacct_source_checks.py` |
| `tests/signalacct_tail_cells.txt` | MANUAL | none in scoped code | retained |
| `tests/signalacct_tail_unit.cc` | MANUAL | `tools/signalacct_tail_artifacts.py` | retained |
| `tests/signalacct_unit.cc` | MANUAL | `tests/signalacct_controls.py` | retained |
| `tests/slotless.py` | LIVE | `tests/gate.sh` | retained |
| `tests/slotless_unit.cc` | LIVE | `Makefile` | retained |
| `tests/slowlog.py` | LIVE | `tests/gate.sh` | retained |
| `tests/slowlog_completion_checks.inc` | LIVE | `Makefile`, `tests/core_concurrency_unit.cc` | retained |
| `tests/slowlog_identity.py` | LIVE | `tests/gate.sh:3604`, `bugs5` via `tests/$test.py` | A1b: restored unchanged; all eight mode/engine/atomic legs remain required. |
| `tests/snap_cut_battery.py` | LIVE | `tests/flakeaudit_test.py`, `tests/gate.sh`, `tests/lottery_attempt.py` | retained |
| `tests/snap_typed_race.py` | LIVE | `tests/gate.sh` | retained |
| `tests/snap_typed_roundtrip.py` | LIVE | `tests/gate.sh` | retained |
| `tests/snapfix.py` | LIVE | `tests/flipfix5.py`, `tests/flipfix6.py`, `tests/flipfix7.py`, `tests/flushfix2.py`, `tests/flushfix2_siblings.py`, `tests/flushfix3.py`, `tests/gate.sh`, `tests/snapfix2_flush.py`, `tests/snapfix2_rss.py`, `tests/snapfix_neighbours.py`, `tests/wave15_aof.py`, `tools/snapfix2_nx_control.py`, `tools/snapfix_long_storm.py` | retained |
| `tests/snapfix2_flush.py` | LIVE | `tests/flushfix2.py` | retained |
| `tests/snapfix2_rss.py` | MANUAL | none in scoped code | retained |
| `tests/snapfix_neighbours.py` | MANUAL | none in scoped code | retained |
| `tests/sort.py` | LIVE | `tests/gate.sh` | retained |
| `tests/sortstore.py` | LIVE | `tests/differ.py`, `tests/multidb.py` | retained |
| `tests/sortstore_cases.tsv` | LIVE | `tests/sortstore.py`, `tests/sortstore_checks.inc` | retained |
| `tests/sortstore_checks.inc` | LIVE | `Makefile`, `tests/multidb_unit.cc` | retained |
| `tests/sortstore_controls.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tests/sortstore_controls.py` |
| `tests/spinprobe.py` | LIVE | `tests/gate.sh`, `tests/lottery_attempt.py` | retained |
| `tests/splitlocal_checks.py` | LIVE; TEXT-MATCHER | `Makefile`, `tests/gate.sh`, `tools/iopass_validate.py`, `tools/overlapaxe_artifacts.py` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tests/splitlocal_live.py` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/spscmask_flip.py` | MANUAL | none in scoped code | retained |
| `tests/standing-null/3dcdaa497a4f1e2a670342e17daa27bb9c36e9a2cbc633196d134d85b65efb9a-8149f97d7e9de4718100fe77606b28d5394d2c59b5dde92a6dddc6adffd31054.json.gz` | MANUAL | none in scoped code | retained |
| `tests/standing-null/3dcdaa497a4f1e2a670342e17daa27bb9c36e9a2cbc633196d134d85b65efb9a-8a56ccba5a53802f23645efed184407954cf75e7992b3c37d0e03e735a099764.receipt.json` | LIVE | `tests/nullpublish4_test.py` | retained |
| `tests/standing-null/3dcdaa497a4f1e2a670342e17daa27bb9c36e9a2cbc633196d134d85b65efb9a.instrument.json` | MANUAL | none in scoped code | retained |
| `tests/standing-null/README.md` | LIVE | `tools/execfifo3_perf_summary.py`, `tools/tailgen/main.cc` | retained |
| `tests/standing-null/artifacts/1adfe8094f7a7dfe6834ce7d4a37d109520c052e248651bb757185c5b6ef88d8.json.gz` | MANUAL | none in scoped code | retained |
| `tests/standing-null/artifacts/71ae3cef2740d07acdc595208e8b55a561df3186b3692282daeb9e1dd49ddf2a.json.gz` | MANUAL | none in scoped code | retained |
| `tests/standing-null/artifacts/82daac5418e894ee2db39520dbc35559f54e81ee45a2c5b9f76188d2c2af0ac4.json.gz` | MANUAL | none in scoped code | retained |
| `tests/standing-null/artifacts/a59bccda91e4599d6a3364776a633af0ae9aea466e862cacb17e4bf59cc24fe7.json.gz` | MANUAL | none in scoped code | retained |
| `tests/standing-null/artifacts/d0f48a6647665894d8cff062752dd9c56cc0597bedad45f6973220f345187333.json.gz` | MANUAL | none in scoped code | retained |
| `tests/standing-null/campaign7-cx-final-match.json` | MANUAL | none in scoped code | retained |
| `tests/standing-null/campaign7-holdout-resolution.json` | MANUAL | none in scoped code | retained |
| `tests/standing-null/current.json` | LIVE | `tests/abba_standing_null.py`, `tests/nullpublish4_test.py`, `tools/flushfix2_budget.py`, `tools/flushfix2_budget_counts.py` | retained |
| `tests/store_regression.cc` | LIVE | `Makefile`, `tests/gate.sh`, `tests/wave15_idle_unit.cc`, `tools/storefix5_retirement.py` | retained |
| `tests/storefix5.py` | LIVE | `tests/gate.sh`, `tools/storefix5_checks.py` | retained |
| `tests/storefix5_append.cc` | MANUAL | `tools/storefix5_append.py` | retained |
| `tests/storeorder.py` | MANUAL | none in scoped code | retained |
| `tests/storesize_checks.py` | LIVE; TEXT-MATCHER | `Makefile`, `tests/gate.sh`, `tools/storesize_artifacts.py` | Token anchors and unique function scopes for the cold census instrumentation. |
| `tests/storesize_unit.cc` | LIVE | `tools/flushfix2_verification_receipts.py`, `tools/storesize_artifacts.py` | retained |
| `tests/stream.py` | MANUAL | none in scoped code | retained |
| `tests/streamgroups.py` | MANUAL | none in scoped code | retained |
| `tests/tailgen_stall.py` | LIVE | `tests/gate.sh`, `tests/gates_test.py` | retained |
| `tests/tailgen_unit.cc` | LIVE | `Makefile` | retained |
| `tests/tls.py` | LIVE | `tests/_netfix.py`, `tests/flipfix7.py`, `tests/fliplisten.py`, `tests/gate.sh`, `tests/iowake.py`, `tests/ktls_lifetime.py`, `tests/lottery_attempt.py`, `tests/netfix2.py`, `tools/ntfix_proof.py` | retained |
| `tests/tlsserve_checks.inc` | LIVE | `Makefile`, `tests/netcmd_unit.cc`, `tools/tlsserve_proof.py` | retained |
| `tests/tomo_assert_checks.py` | LIVE; TEXT-MATCHER | `tests/gate.sh` | Stable role names for diagnostic inventory; physical lines validate macro presence; empty-input negative added. |
| `tests/tomo_assert_fail.cc` | LIVE | `Makefile` | retained |
| `tests/torn_mset.py` | MANUAL | none in scoped code | retained |
| `tests/torture.py` | LIVE | `tests/gate.sh` | retained |
| `tests/trackfix.py` | LIVE | `tests/gate.sh`, `tests/trackorder.py` | retained |
| `tests/tracking.py` | MANUAL | none in scoped code | retained |
| `tests/tracking_redirect.py` | LIVE | `tests/gate.sh` | retained |
| `tests/trackorder.py` | LIVE | `tests/gate.sh` | retained |
| `tests/ttl_cells.txt` | LIVE | `tests/ttlcell_test.py` | retained |
| `tests/ttlcell_test.py` | LIVE | `tests/abbagate.py` | retained |
| `tests/txn_movers.py` | LIVE | `tests/gate.sh` | retained |
| `tests/txn_nx.py` | LIVE | `tests/gate.sh`, `tools/snapfix2_nx_control.py`, `tools/woundfix_live.py` | retained |
| `tests/txnfix4.mk` | LIVE | `tests/gate.sh` | retained |
| `tests/txnfix4.py` | LIVE | `tests/gate.sh` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/txnfix4_hash.cc` | LIVE | `tests/txnfix4.mk` | retained |
| `tests/txnfix4_scope.cc` | MANUAL | `tools/txnfix4_scope.py` | retained |
| `tests/txnfix_audit/resp.py` | LIVE | `tests/blockfix4_repro/item1_natural.py`, `tests/blockfix4_repro/item1_script_push.py`, `tests/blockfix4_repro/item2_move_nil.py`, `tests/blockfix4_repro/item4_creators.py`, `tests/blockfix4_repro/item5_stream_removed.py`, `tests/blockfix4_repro/item6_mpop_null.py`, `tests/blockfix4_repro/lib/srv.py`, `tests/netfix2_audit.py`, `tests/rootcompat_tracking/srv.py`, `tests/rootcompat_tracking/t1_xsnotify.py`, `tests/rootcompat_tracking/t3_keylesscap.py`, `tests/txnfix_audit/t01_exec_counter.py`, `tests/txnfix_audit/t02_exec_directed.py`, `tests/txnfix_audit/t02b_exec_vs_exec.py`, `tests/txnfix_audit/t03_mover_replay.py`, `tests/txnfix_audit/t04_mover_stress.py`, `tests/txnfix_audit/t05_mover_only.py`, `tests/txnfix_audit/t10_msetnx_hold.py`, `tests/txnfix_audit/t14_exec_window.py`, `tests/txnfix_audit/t15_exec_only_stress.py`, `tests/txnfix_audit/t17_queue_exec.py`, `tests/txnfix_audit/t18_watch_cas.py`, `tests/txnfix_audit/t19_crossed_watch.py`, `tools/atomfix6_audit.py`, `tools/wave15_scan_expiry.py` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/txnfix_audit/t01_exec_counter.py` | LIVE | `tests/txniso.py` | retained |
| `tests/txnfix_audit/t02_exec_directed.py` | MANUAL | none in scoped code | retained |
| `tests/txnfix_audit/t02b_exec_vs_exec.py` | MANUAL | none in scoped code | retained |
| `tests/txnfix_audit/t03_mover_replay.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tests/txnfix_audit/t03_mover_replay.py` |
| `tests/txnfix_audit/t04_mover_stress.py` | MANUAL | none in scoped code | retained |
| `tests/txnfix_audit/t05_mover_only.py` | MANUAL | none in scoped code | retained |
| `tests/txnfix_audit/t10_msetnx_hold.py` | MANUAL | none in scoped code | retained |
| `tests/txnfix_audit/t14_exec_window.py` | LIVE | `tests/txniso.py` | retained |
| `tests/txnfix_audit/t15_exec_only_stress.py` | LIVE | `tests/txniso.py` | retained |
| `tests/txnfix_audit/t17_queue_exec.py` | LIVE | `tests/txniso.py` | retained |
| `tests/txnfix_audit/t18_watch_cas.py` | LIVE | `tests/txniso.py` | retained |
| `tests/txnfix_audit/t19_crossed_watch.py` | MANUAL | none in scoped code | retained |
| `tests/txngroup.py` | LIVE | `tests/gate.sh` | retained |
| `tests/txniso.py` | LIVE | `tests/atomfix5_accounting.py`, `tests/gate.sh`, `tests/txngroup.py`, `tests/txnorder.py` | retained |
| `tests/txnorder.py` | LIVE | `tests/gate.sh` | retained |
| `tests/txnorder_chain.cc` | LIVE | `Makefile`, `tools/execfifo2_freshness.py`, `tools/execfifo3_freshness.py` | retained |
| `tests/txnorder_checks.inc` | LIVE | `Makefile`, `tests/atomic_survivors_unit.cc` | retained |
| `tests/txnorder_command_scope.cc` | LIVE | `tools/atomfix6_counts.py`, `tools/blockfix2_scope.py`, `tools/blockfix3_scope.py`, `tools/blockwake_counts.py`, `tools/crlffix_scope.py`, `tools/exec1s_build.py`, `tools/exec1s_pad_scope.py`, `tools/exec1s_scope.py`, `tools/exec1sd.py`, `tools/exec1sd_alignment.py`, `tools/execindex_scope.py`, `tools/flipfix5_counts.py`, `tools/flushfix2_live.py`, `tools/mset8fix_counts.py`, `tools/parkwake_counts.py`, `tools/snapfix_scope.py` | retained |
| `tests/txnorder_episodes.cc` | LIVE | `Makefile`, `tests/txnorder_fifo.cc` | retained |
| `tests/txnorder_fifo.cc` | LIVE | `Makefile`, `tools/execfifo2_freshness.py`, `tools/execfifo3_freshness.py` | retained |
| `tests/txnorder_index_unit.cc` | LIVE | `Makefile` | retained |
| `tests/txnorder_linear_oracle.inc` | LIVE | `Makefile`, `tests/txnorder_index_unit.cc` | retained |
| `tests/txnorder_plain_cost.cc` | MANUAL | none in scoped code | retained |
| `tests/txnorder_retry_unit.cc` | LIVE | `Makefile` | retained |
| `tests/txnorder_wake_unit.cc` | LIVE | `Makefile` | retained |
| `tests/txnorder_watch.py` | LIVE | `tests/gate.sh` | retained |
| `tests/txnorder_watch_unit.cc` | LIVE | `Makefile` | retained |
| `tests/txnorder_wound_window.cc` | LIVE | `Makefile` | retained |
| `tests/waits_unit.cc` | LIVE | `Makefile`, `tests/gate.sh` | retained |
| `tests/watchlive.py` | MANUAL | `tests/watchlive_gate.sh` | retained |
| `tests/watchlive_gate.sh` | MANUAL | none in scoped code | retained |
| `tests/wave10.py` | LIVE | `tests/gate.sh` | retained |
| `tests/wave10_scope.cc` | LIVE | `tools/wave10.py` | retained |
| `tests/wave11_dispatch_scope.cc` | MANUAL | none in scoped code | retained |
| `tests/wave11_gc_scope.cc` | MANUAL | none in scoped code | retained |
| `tests/wave11_scope.cc` | MANUAL | `tests/wave11_gc_scope.cc`, `tools/cfgfix2_counts.py`, `tools/cfgfix_counts.py`, `tools/iowake_counts.py`, `tools/netfix2_counts.py`, `tools/netfix2_tls_counts.py`, `tools/persistfmt_counts.py`, `tools/wave11.py`, `tools/wave11_counts.py`, `tools/wave12.py`, `tools/wave13.py`, `tools/wave16_counts.py` | retained |
| `tests/wave12_gc_scope.cc` | MANUAL | none in scoped code | retained |
| `tests/wave12_scope.cc` | LIVE | `tests/wave12_gc_scope.cc`, `tools/rootcore_counts.py`, `tools/wave12_counts.py`, `tools/wave13_counts.py`, `tools/wave14_counts.py`, `tools/wave15_counts.py` | retained |
| `tests/wave13_checks.inc` | LIVE | `Makefile`, `tests/core_concurrency_unit.cc` | retained |
| `tests/wave14_capture_hook.cc` | LIVE | `tools/wave14_capture.py` | retained |
| `tests/wave14_checks.inc` | LIVE | `Makefile`, `tests/core_concurrency_unit.cc` | retained |
| `tests/wave14_eof_data.py` | LIVE | `tests/gate.sh` | retained |
| `tests/wave14_epoll_eof.cc` | MANUAL | `tools/eoffix_aof.py`, `tools/netfix2_diagnostics.py` | retained |
| `tests/wave14_functions.py` | LIVE | `tests/gate.sh` | retained |
| `tests/wave14_order.py` | LIVE | `tests/gate.sh` | retained |
| `tests/wave14_parser_scope.cc` | MANUAL | `tools/blockwake_counts.py`, `tools/eoffix_counts.py`, `tools/mset8fix_counts.py`, `tools/wave14_counts.py`, `tools/wave15_counts.py`, `tools/wave16_counts.py` | retained |
| `tests/wave14_tcl_fairness.json` | MANUAL | none in scoped code | retained |
| `tests/wave14_tcl_probes.json` | MANUAL | none in scoped code | retained |
| `tests/wave15_aof.py` | LIVE | `tests/gate.sh`, `tools/wave15_aof_stacks.py` | retained |
| `tests/wave15_block_repeat.py` | LIVE | `tests/gate.sh` | retained |
| `tests/wave15_error_scope.cc` | MANUAL | `tools/wave15_counts.py` | retained |
| `tests/wave15_errorstats.py` | LIVE | `tests/gate.sh` | retained |
| `tests/wave15_flip_eof.py` | LIVE | `tests/gate.sh` | retained |
| `tests/wave15_flip_eof_unit.cc` | LIVE | `Makefile` | retained |
| `tests/wave15_idle_unit.cc` | LIVE | `Makefile` | retained |
| `tests/wave15_rebind.py` | LIVE | `tests/gate.sh` | retained |
| `tests/wave15_stream_unit.cc` | LIVE | `Makefile` | retained |
| `tests/wave5_dispatch_checks.inc` | LIVE | `Makefile`, `tests/core_concurrency_unit.cc` | retained |
| `tests/wave5b_client.cc` | MANUAL | `tools/wave5b_trace.py` | retained |
| `tests/wave6_exec.py` | LIVE | `tests/gate.sh` | retained |
| `tests/wave7.py` | LIVE | `tests/compat3_blockfix.py`, `tests/datafix2_watch.py`, `tests/gate.sh`, `tests/rlfix3_info.py` | retained |
| `tests/wave8.py` | LIVE | `tests/gate.sh`, `tests/wave8b.py` | retained |
| `tests/wave8b.py` | LIVE | `tests/gate.sh` | retained |
| `tests/wave8b_latency_unit.cc` | LIVE | `tools/wave8b.mk` | retained |
| `tests/wave8b_scope.cc` | LIVE | `tests/wave8b_latency_unit.cc`, `tools/wave8b.mk` | retained |
| `tests/wave9.py` | LIVE | `tests/gate.sh` | retained |
| `tests/wave9_scope.cc` | MANUAL | `tools/exec1sd.py` | retained |
| `tests/wb_mixed.py` | LIVE | `tests/gate.sh` | retained |
| `tests/wb_policy.py` | LIVE | `tests/gate.sh`, `tests/gates_test.py`, `tests/wb_mixed.py` | retained |
| `tests/wb_rule_2s_cells.txt` | MANUAL | `tools/wb_rule_2s_artifacts.py` | retained |
| `tests/wb_rule_2s_cost.cc` | MANUAL | `tools/wb_rule_2s_artifacts.py` | retained |
| `tests/wb_rule_cells.txt` | LIVE | `tests/ttlcell_test.py`, `tools/mkprobe_probe.py` | retained |
| `tests/wb_rule_checks.py` | LIVE; TEXT-MATCHER | `Makefile`, `tests/gate.sh`, `tests/wbland_checks.py`, `tools/iopass_validate.py`, `tools/wb_rule_2s_artifacts.py` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tests/wb_rule_codes.cc` | MANUAL | `tools/wb_rule_receipts.py` | retained |
| `tests/wb_rule_completion_evidence.json` | MANUAL | none in scoped code | retained |
| `tests/wb_rule_completion_unit.cc` | LIVE | `Makefile`, `tests/wb_rule_codes.cc`, `tests/wbknobs_cost.cc` | retained |
| `tests/wb_rule_phase_unit.cc` | LIVE | `Makefile`, `tools/wb_rule_2s_artifacts.py` | retained |
| `tests/wb_rule_unit.cc` | LIVE | `Makefile`, `tests/wbland_clause_unit.cc` | retained |
| `tests/wbhybrid2_cells.txt` | MANUAL | none in scoped code | retained |
| `tests/wbhybrid2_evidence.json` | MANUAL | none in scoped code | retained |
| `tests/wbhybrid2b_evidence.json` | MANUAL | none in scoped code | retained |
| `tests/wbhybrid_cells.txt` | MANUAL | none in scoped code | retained |
| `tests/wbhybrid_evidence.json` | MANUAL | none in scoped code | retained |
| `tests/wbknobs_cost.cc` | MANUAL | `tools/wbknobs_receipts.py` | retained |
| `tests/wbknobs_sweep_cells.txt` | MANUAL | `tools/wbknobs_measure.py` | retained |
| `tests/wbland_4096_cells.txt` | MANUAL | none in scoped code | retained |
| `tests/wbland_checks.py` | LIVE; TEXT-MATCHER | `Makefile`, `tests/gate.sh`, `tools/iopass_validate.py` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tests/wbland_clause_unit.cc` | LIVE | `Makefile` | retained |
| `tests/wbland_evidence.json` | MANUAL | none in scoped code | retained |
| `tests/wbland_merit_cells.txt` | MANUAL | `tools/wbknobs_measure.py` | retained |
| `tests/wbland_unit.cc` | LIVE | `Makefile` | retained |
| `tests/wiredump.py` | LIVE | `tests/persistfmt.py` | Retained protocol/log/fixture reader; no production source matching. |
| `tests/writer_atomic.py` | MANUAL | `tests/writer_atomic_campaign.py` | retained |
| `tests/writer_atomic_campaign.py` | MANUAL; TEXT-MATCHER | none in scoped code | retained |
| `tests/xacct.py` | MANUAL | none in scoped code | retained |
| `tests/xmove.py` | MANUAL | none in scoped code | retained |
| `tests/xscript.py` | LIVE | `tests/gate.sh`, `tests/mutants.py`, `tools/gt14fix_evidence.py` | retained |
| `tests/xshard_dispatch_scale.py` | LIVE | `tests/xshard_dispatch_scale.sh` | retained |
| `tests/xshard_dispatch_scale.sh` | LIVE | `tests/gate.sh` | retained |
| `tests/zc.py` | LIVE | `tests/gate.sh` | retained |
| `tests/zsetops.py` | MANUAL | none in scoped code | retained |
| `tools/90-tomokv-nic.conf` | MANUAL | none in scoped code | retained |
| `tools/README.md` | LIVE | `tools/execfifo3_perf_summary.py`, `tools/tailgen/main.cc` | retained |
| `tools/aclkeys3_audit.py` | FINISHED-LANE; TEXT-MATCHER | `tools/aclkeys4_audit.py` | moved unchanged to `tools/archive/tools/aclkeys3_audit.py` |
| `tools/aclkeys3_budget.py` | FINISHED-LANE; TEXT-MATCHER | `tools/aclkeys3_audit.py` | moved unchanged to `tools/archive/tools/aclkeys3_budget.py` |
| `tools/aclkeys3_controls.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/aclkeys3_controls.py` |
| `tools/aclkeys3_link_audit.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/aclkeys3_link_audit.py` |
| `tools/aclkeys3_text_audit.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/aclkeys3_text_audit.py` |
| `tools/aclkeys3_verify.py` | LIVE | `tests/gate.sh` | retained |
| `tools/aclkeys4_audit.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/aclkeys4_audit.py` |
| `tools/aclkeys4_budget.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/aclkeys4_budget.py` |
| `tools/aclkeys_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/aclkeys_artifacts.py` |
| `tools/aoffix2_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/aoffix2_pad.py` |
| `tools/aoffix2_proof.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/aoffix2_proof.py` |
| `tools/aoffix2_report.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/aoffix2_report.py` |
| `tools/aoffix_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/aoffix_artifacts.py` |
| `tools/aoforder_schedule.py` | LIVE; TEXT-MATCHER | `Makefile` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tools/assert_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/assert_artifacts.py` |
| `tools/assert_map.py` | LIVE; TEXT-MATCHER | `Makefile`, `tests/tomo_assert_checks.py`, `tools/aoforder_schedule.py`, `tools/crlffix_scope.py`, `tools/flipfix5_counts.py`, `tools/flipfix6_counts.py`, `tools/flipfix6_diag.py`, `tools/flipfix7_counts.py`, `tools/lottery_build.py`, `tools/notifycompat_schedule.py`, `tools/publishfix_schedule.py`, `tools/racefix_build.py`, `tools/source_identity.py`, `tools/trackfix_schedule.py` | Existing lexer retained; empty CLI assertion inventory now rejected. Physical lines remain diagnostic output only. |
| `tools/at412_artifacts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/at412_artifacts.py` |
| `tools/at412_budget.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/at412_budget.py` |
| `tools/at412c_proof.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/at412c_proof.py` |
| `tools/at412c_record.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/at412c_record.py` |
| `tools/at_recycle_analyze.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/at_recycle_analyze.py` |
| `tools/at_recycle_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/at_recycle_artifacts.py` |
| `tools/atomfix5_arms.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/atomfix5_arms.py` |
| `tools/atomfix6.mk` | LIVE | `tests/gate.sh`, `tools/atomfix6_final.py`, `tools/flushfix3_freshness.py` | retained |
| `tools/atomfix6_archive.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/atomfix6_archive.py` |
| `tools/atomfix6_audit.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/atomfix6_audit.py` |
| `tools/atomfix6_budget.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/atomfix6_budget.py` |
| `tools/atomfix6_compress.py` | FINISHED-LANE | `tools/atomfix6_proof.py` | moved unchanged to `tools/archive/tools/atomfix6_compress.py` |
| `tools/atomfix6_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/atomfix6_counts.py` |
| `tools/atomfix6_final.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/atomfix6_final.py` |
| `tools/atomfix6_park_pre.py` | FINISHED-LANE | `tools/atomfix6_proof.py` | moved unchanged to `tools/archive/tools/atomfix6_park_pre.py` |
| `tools/atomfix6_proof.py` | FINISHED-LANE; TEXT-MATCHER | `tools/atomfix6_suite.py` | moved unchanged to `tools/archive/tools/atomfix6_proof.py` |
| `tools/atomfix6_receipts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/atomfix6_receipts.py` |
| `tools/atomfix6_retire.py` | FINISHED-LANE | `tools/atomfix6_proof.py` | moved unchanged to `tools/archive/tools/atomfix6_retire.py` |
| `tools/atomfix6_suite.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/atomfix6_suite.py` |
| `tools/atomfix_controls.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/atomfix_controls.py` |
| `tools/atomiccollapse_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | `tests/atomiccollapse_controls.py` | moved unchanged to `tools/archive/tools/atomiccollapse_artifacts.py` |
| `tools/benchtxn.cc` | LIVE | `Makefile` | retained |
| `tools/blockfix2.mk` | LIVE | `tests/gate.sh`, `tools/atomfix6_final.py`, `tools/blockfix2_controls.py`, `tools/blockfix2_pad.py`, `tools/cfgfix2_units.py`, `tools/clientcompat_unit_build.py`, `tools/cmdfix2_freshness.py`, `tools/exec1sd_proof.py`, `tools/execfifo2_freshness.py`, `tools/execfifo3_freshness.py`, `tools/flipfix7_freshness.py`, `tools/flushfix2_freshness.py`, `tools/flushfix3_freshness.py`, `tools/rootcore_freshness.py`, `tools/trackorder_units.py` | retained |
| `tools/blockfix2_controls.py` | LIVE; TEXT-MATCHER | `tests/gate.sh`, `tools/blockfix3_controls.py` | Live receipt/check paths retained. Six available source-control branches use exact token guards. Historical rename build branch already fails at frozen input; see limitations. |
| `tools/blockfix2_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/blockfix2_pad.py` |
| `tools/blockfix2_receipts.py` | LIVE | `tools/blockfix3_proof.py`, `tools/blockfix4_proof.py`, `tools/cmdfix2_evidence.py`, `tools/rlfix5_validate.py`, `tools/txnfix4_proof.py`, `tools/wave14.py`, `tools/wave15.py` | retained |
| `tools/blockfix2_scope.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/blockfix2_scope.py` |
| `tools/blockfix3_controls.py` | LIVE; TEXT-MATCHER | `tests/gate.sh` | Retained live receipt/check paths; source controls delegate to the reviewed blockfix2 builder. |
| `tools/blockfix3_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/blockfix3_pad.py` |
| `tools/blockfix3_proof.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/blockfix3_proof.py` |
| `tools/blockfix3_repro.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/blockfix3_repro.py` |
| `tools/blockfix3_scope.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/blockfix3_scope.py` |
| `tools/blockfix3_tcl_compare.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/blockfix3_tcl_compare.py` |
| `tools/blockfix4_budget.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/blockfix4_budget.py` |
| `tools/blockfix4_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/blockfix4_pad.py` |
| `tools/blockfix4_proof.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/blockfix4_proof.py` |
| `tools/blockfix4_scope.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/blockfix4_scope.py` |
| `tools/blockfix4_summary.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/blockfix4_summary.py` |
| `tools/blockfix4_verify.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/blockfix4_verify.py` |
| `tools/blockfix_climon.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/blockfix_climon.py` |
| `tools/blockfix_cost.mk` | LIVE | `tests/gate.sh`, `tools/atomfix6_final.py`, `tools/cfgfix2_units.py`, `tools/clientcompat_unit_build.py`, `tools/cmdfix2_freshness.py`, `tools/exec1s_finish_proof.py`, `tools/execfifo2_freshness.py`, `tools/execfifo3_freshness.py`, `tools/flipfix7_freshness.py`, `tools/flushfix2_freshness.py`, `tools/flushfix3_freshness.py`, `tools/rootcore_freshness.py`, `tools/snapfix2_artifacts.py`, `tools/trackorder_units.py` | retained |
| `tools/blockfix_identity.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/blockfix_identity.py` |
| `tools/blockfix_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/blockfix_pad.py` |
| `tools/blockfix_ports.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/blockfix_ports.py` |
| `tools/blockfix_receipts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/blockfix_receipts.py` |
| `tools/blockwake_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/blockwake_counts.py` |
| `tools/blockwake_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/blockwake_pad.py` |
| `tools/boot_support_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/boot_support_artifacts.py` |
| `tools/boot_support_controls.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/boot_support_controls.py` |
| `tools/ccfix2_prove.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/ccfix2_prove.py` |
| `tools/ccfix3_prove.py` | FINISHED-LANE | `tools/ccfix4_prove.py`, `tools/ccfix5_prove.py` | moved unchanged to `tools/archive/tools/ccfix3_prove.py` |
| `tools/ccfix3_wire.sh` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/ccfix3_wire.sh` |
| `tools/ccfix4_budget.py` | FINISHED-LANE; TEXT-MATCHER | `tools/aclkeys3_budget.py`, `tools/aclkeys4_budget.py`, `tools/ccfix4_server_budget.py`, `tools/clientcompat_budgets.py`, `tools/deadcode2_budget.py`, `tools/infofields_budget.py`, `tools/iofix_budget.py`, `tools/latencyfix_budget.py` | moved unchanged to `tools/archive/tools/ccfix4_budget.py` |
| `tools/ccfix4_prove.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/ccfix4_prove.py` |
| `tools/ccfix4_server_budget.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/ccfix4_server_budget.py` |
| `tools/ccfix5_collect.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/ccfix5_collect.py` |
| `tools/ccfix5_probe.py` | FINISHED-LANE | `tools/ccfix5_probe.sh` | moved unchanged to `tools/archive/tools/ccfix5_probe.py` |
| `tools/ccfix5_probe.sh` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/ccfix5_probe.sh` |
| `tools/ccfix5_prove.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/ccfix5_prove.py` |
| `tools/ccfix_audit.py` | LIVE; TEXT-MATCHER | `tools/wave10.py:165` → `docs/wave9/budgets.py:13` | A1b: restored unchanged; transitive import from a retained manual tool; historical budget campaign not replayed. |
| `tools/ccfix_tables.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/ccfix_tables.py` |
| `tools/cfgfix2_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/cfgfix2_counts.py` |
| `tools/cfgfix2_gate.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/cfgfix2_gate.py` |
| `tools/cfgfix2_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/cfgfix2_pad.py` |
| `tools/cfgfix2_table.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/cfgfix2_table.py` |
| `tools/cfgfix2_tcl_compare.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/cfgfix2_tcl_compare.py` |
| `tools/cfgfix2_units.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/cfgfix2_units.py` |
| `tools/cfgfix_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/cfgfix_counts.py` |
| `tools/cfgfix_inventory.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/cfgfix_inventory.py` |
| `tools/cfgfix_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/cfgfix_pad.py` |
| `tools/clientcompat_budgets.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/clientcompat_budgets.py` |
| `tools/clientcompat_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/clientcompat_counts.py` |
| `tools/clientcompat_inline_trials.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/clientcompat_inline_trials.py` |
| `tools/clientcompat_pad.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/clientcompat_pad.py` |
| `tools/clientcompat_pause_audit.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/clientcompat_pause_audit.py` |
| `tools/clientcompat_receipts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/clientcompat_receipts.py` |
| `tools/clientcompat_report.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/clientcompat_report.py` |
| `tools/clientcompat_unit_build.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/clientcompat_unit_build.py` |
| `tools/clientcompat_verdict.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/clientcompat_verdict.py` |
| `tools/cmdfix2_auditors.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/cmdfix2_auditors.py` |
| `tools/cmdfix2_compact_units.py` | FINISHED-LANE; TEXT-MATCHER | `tools/cmdfix2_counts.py` | moved unchanged to `tools/archive/tools/cmdfix2_compact_units.py` |
| `tools/cmdfix2_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/cmdfix2_counts.py` |
| `tools/cmdfix2_evidence.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/cmdfix2_evidence.py` |
| `tools/cmdfix2_fifo_diagnostic.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/cmdfix2_fifo_diagnostic.py` |
| `tools/cmdfix2_final_main.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/cmdfix2_final_main.py` |
| `tools/cmdfix2_freshness.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/cmdfix2_freshness.py` |
| `tools/cmdfix2_more_jobs.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/cmdfix2_more_jobs.py` |
| `tools/cmdfix2_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/cmdfix2_pad.py` |
| `tools/cmdfix2_related_jobs.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/cmdfix2_related_jobs.py` |
| `tools/cmdfix_artifacts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/cmdfix_artifacts.py` |
| `tools/cmdmeta_audit.py` | FINISHED-LANE; TEXT-MATCHER | `tools/infofields_artifacts.py` | moved unchanged to `tools/archive/tools/cmdmeta_audit.py` |
| `tools/compat2_mset_control.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/compat2_mset_control.py` |
| `tools/compat2_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/compat2_pad.py` |
| `tools/crlffix_arms.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/crlffix_arms.py` |
| `tools/crlffix_fast_scope.py` | FINISHED-LANE; TEXT-MATCHER | `tools/exec1sd.py`, `tools/exec1sd_alignment.py`, `tools/exec1sd_scatter.py`, `tools/flushfix2_counts.py` | moved unchanged to `tools/archive/tools/crlffix_fast_scope.py` |
| `tools/crlffix_scope.py` | FINISHED-LANE; TEXT-MATCHER | `tools/crlffix_fast_scope.py`, `tools/flushfix2_counts.py` | moved unchanged to `tools/archive/tools/crlffix_scope.py` |
| `tools/crlffix_step.c` | MANUAL | `tools/exec1sd.py`, `tools/flipfix5_counts.py`, `tools/flipfix6_counts.py`, `tools/flipfix7_counts.py`, `tools/flushfix2_budget_counts.py`, `tools/flushfix2_counts.py`, `tools/flushfix2_live.py`, `tools/flushfix3_budget.py` | retained |
| `tools/ctlfix_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/ctlfix_artifacts.py` |
| `tools/datafix1_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/datafix1_pad.py` |
| `tools/deadcode2_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/deadcode2_artifacts.py` |
| `tools/deadcode2_budget.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/deadcode2_budget.py` |
| `tools/deadcode2_linked.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/deadcode2_linked.py` |
| `tools/deadcode2_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/deadcode2_pad.py` |
| `tools/deadfused_artifacts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/deadfused_artifacts.py` |
| `tools/encodingfix_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/encodingfix_pad.py` |
| `tools/eoffix.py` | FINISHED-LANE; TEXT-MATCHER | `tools/eoffix_final.py` | moved unchanged to `tools/archive/tools/eoffix.py` |
| `tools/eoffix_aof.py` | FINISHED-LANE; TEXT-MATCHER | `tools/eoffix_final.py` | moved unchanged to `tools/archive/tools/eoffix_aof.py` |
| `tools/eoffix_archive_data.py` | FINISHED-LANE | `tools/eoffix.py`, `tools/eoffix_final.py` | moved unchanged to `tools/archive/tools/eoffix_archive_data.py` |
| `tools/eoffix_bind.py` | FINISHED-LANE | `tools/eoffix_final.py` | moved unchanged to `tools/archive/tools/eoffix_bind.py` |
| `tools/eoffix_compare.py` | FINISHED-LANE | `tools/eoffix_final.py` | moved unchanged to `tools/archive/tools/eoffix_compare.py` |
| `tools/eoffix_counts.py` | FINISHED-LANE | `tools/eoffix_final.py`, `tools/eoffix_receive_counts.py` | moved unchanged to `tools/archive/tools/eoffix_counts.py` |
| `tools/eoffix_dedup.py` | FINISHED-LANE; TEXT-MATCHER | `tools/eoffix_final.py` | moved unchanged to `tools/archive/tools/eoffix_dedup.py` |
| `tools/eoffix_final.py` | FINISHED-LANE | `tools/eoffix_final.py` | moved unchanged to `tools/archive/tools/eoffix_final.py` |
| `tools/eoffix_receive_counts.py` | FINISHED-LANE | `tools/eoffix_final.py` | moved unchanged to `tools/archive/tools/eoffix_receive_counts.py` |
| `tools/eoffix_retire_layout.py` | FINISHED-LANE | `tools/eoffix_final.py` | moved unchanged to `tools/archive/tools/eoffix_retire_layout.py` |
| `tools/eoffix_retire_scopes.py` | FINISHED-LANE | `tools/eoffix_final.py` | moved unchanged to `tools/archive/tools/eoffix_retire_scopes.py` |
| `tools/eoffix_source_sync.py` | FINISHED-LANE; TEXT-MATCHER | `tools/eoffix_final.py`, `tools/eoffix_verify.py` | moved unchanged to `tools/archive/tools/eoffix_source_sync.py` |
| `tools/eoffix_summary.py` | FINISHED-LANE | `tools/eoffix_final.py` | moved unchanged to `tools/archive/tools/eoffix_summary.py` |
| `tools/eoffix_verify.py` | FINISHED-LANE | `tools/eoffix_final.py` | moved unchanged to `tools/archive/tools/eoffix_verify.py` |
| `tools/exbatch_artifacts.py` | LIVE; TEXT-MATCHER | `tests/exbatch_checks.py` | Shared ELF role canonicalization; numeric patch-table inventory, exact byte checks and nonempty selections retained. |
| `tools/exbatch_directed.py` | FINISHED-LANE | `tools/exbatch_rebuild_arms.py`, `tools/mkfix_counts.py`, `tools/mkprobe_probe.py` | moved unchanged to `tools/archive/tools/exbatch_directed.py` |
| `tools/exbatch_rebuild_arms.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/exbatch_rebuild_arms.py` |
| `tools/exbatch_source_proof.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/exbatch_source_proof.py` |
| `tools/exec1s_aux.py` | FINISHED-LANE; TEXT-MATCHER | `tools/exec1s_build.py` | moved unchanged to `tools/archive/tools/exec1s_aux.py` |
| `tools/exec1s_budget.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/exec1s_budget.py` |
| `tools/exec1s_build.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/exec1s_build.py` |
| `tools/exec1s_debug.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/exec1s_debug.py` |
| `tools/exec1s_directed.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/exec1s_directed.py` |
| `tools/exec1s_finish_proof.py` | FINISHED-LANE | `tools/exec1sd_proof.py` | moved unchanged to `tools/archive/tools/exec1s_finish_proof.py` |
| `tools/exec1s_idle.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/exec1s_idle.py` |
| `tools/exec1s_live_receipts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/exec1s_live_receipts.py` |
| `tools/exec1s_pad.py` | FINISHED-LANE; TEXT-MATCHER | `tools/eoffix_aof.py`, `tools/eoffix_final.py`, `tools/exec1s_aux.py`, `tools/exec1s_build.py`, `tools/exec1s_pad_scope.py`, `tools/exec1sd.py`, `tools/exec1sd_pad.py`, `tools/execfifo3_artifacts.py`, `tools/netfix2_artifacts.py`, `tools/rootcompat_pad.py`, `tools/wave14_arms.py` | moved unchanged to `tools/archive/tools/exec1s_pad.py` |
| `tools/exec1s_pad_scope.py` | FINISHED-LANE; TEXT-MATCHER | `tools/exec1s_build.py` | moved unchanged to `tools/archive/tools/exec1s_pad_scope.py` |
| `tools/exec1s_proof.py` | FINISHED-LANE | `tools/exec1s_finish_proof.py`, `tools/exec1sd_proof.py` | moved unchanged to `tools/archive/tools/exec1s_proof.py` |
| `tools/exec1s_retire_probes.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/exec1s_retire_probes.py` |
| `tools/exec1s_scope.py` | LIVE; TEXT-MATCHER | `tools/exec1s_aux.py`, `tools/exec1s_build.py`, `tools/exec1s_idle.py`, `tools/exec1s_pad_scope.py`, `tools/exec1s_retire_probes.py`, `tools/exec1s_trace.py`, `tools/exec1sd.py`, `tools/execfifo2_scope.py`, `tools/execfifo3_scope.py`, `tools/wave10.py`, `tools/wave11.py`, `tools/wave12.py`, `tools/wave13.py` | Retained instruction census helper; public main/namespace boundaries and supplied fixture paths, no C++ text patch. |
| `tools/exec1s_trace.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/exec1s_trace.py` |
| `tools/exec1sd.py` | FINISHED-LANE; TEXT-MATCHER | `tools/exec1sd_alignment.py`, `tools/exec1sd_arms.py`, `tools/exec1sd_lottery.py`, `tools/exec1sd_pad.py`, `tools/exec1sd_proof.py`, `tools/exec1sd_receipts.py`, `tools/exec1sd_retire.py`, `tools/exec1sd_save.py`, `tools/exec1sd_save_full.py`, `tools/exec1sd_save_native.py`, `tools/exec1sd_scatter.py`, `tools/exec1sd_slowlog.py` | moved unchanged to `tools/archive/tools/exec1sd.py` |
| `tools/exec1sd_alignment.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/exec1sd_alignment.py` |
| `tools/exec1sd_arms.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/exec1sd_arms.py` |
| `tools/exec1sd_lottery.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/exec1sd_lottery.py` |
| `tools/exec1sd_pad.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/exec1sd_pad.py` |
| `tools/exec1sd_proof.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/exec1sd_proof.py` |
| `tools/exec1sd_receipts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/exec1sd_receipts.py` |
| `tools/exec1sd_retire.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/exec1sd_retire.py` |
| `tools/exec1sd_save.py` | FINISHED-LANE; TEXT-MATCHER | `tools/exec1sd_save_native.py` | moved unchanged to `tools/archive/tools/exec1sd_save.py` |
| `tools/exec1sd_save_full.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/exec1sd_save_full.py` |
| `tools/exec1sd_save_native.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/exec1sd_save_native.py` |
| `tools/exec1sd_scatter.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/exec1sd_scatter.py` |
| `tools/exec1sd_slowlog.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/exec1sd_slowlog.py` |
| `tools/execfifo2_attribution.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo2_attribution.py` |
| `tools/execfifo2_control_smoke.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo2_control_smoke.py` |
| `tools/execfifo2_coverage.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo2_coverage.py` |
| `tools/execfifo2_freshness.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo2_freshness.py` |
| `tools/execfifo2_negative.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo2_negative.py` |
| `tools/execfifo2_proof_record.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo2_proof_record.py` |
| `tools/execfifo2_scope.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo2_scope.py` |
| `tools/execfifo2_storm.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo2_storm.py` |
| `tools/execfifo2_validate.py` | FINISHED-LANE; TEXT-MATCHER | `tools/execfifo2_coverage.py`, `tools/execfifo3_validate.py` | moved unchanged to `tools/archive/tools/execfifo2_validate.py` |
| `tools/execfifo3_archive_intermediates.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo3_archive_intermediates.py` |
| `tools/execfifo3_artifacts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo3_artifacts.py` |
| `tools/execfifo3_compact.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo3_compact.py` |
| `tools/execfifo3_control_smoke.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo3_control_smoke.py` |
| `tools/execfifo3_coverage.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo3_coverage.py` |
| `tools/execfifo3_freshness.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo3_freshness.py` |
| `tools/execfifo3_input_scope.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo3_input_scope.py` |
| `tools/execfifo3_negative.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo3_negative.py` |
| `tools/execfifo3_perf.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo3_perf.py` |
| `tools/execfifo3_perf_summary.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo3_perf_summary.py` |
| `tools/execfifo3_probe_archive.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo3_probe_archive.py` |
| `tools/execfifo3_proof_record.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo3_proof_record.py` |
| `tools/execfifo3_scope.py` | FINISHED-LANE | `tools/execfifo3_input_scope.py` | moved unchanged to `tools/archive/tools/execfifo3_scope.py` |
| `tools/execfifo3_scope_consistency.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execfifo3_scope_consistency.py` |
| `tools/execfifo3_validate.py` | FINISHED-LANE; TEXT-MATCHER | `tools/execfifo3_coverage.py` | moved unchanged to `tools/archive/tools/execfifo3_validate.py` |
| `tools/execfifo_budget.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/execfifo_budget.py` |
| `tools/execindex_budget.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/execindex_budget.py` |
| `tools/execindex_control_smoke.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execindex_control_smoke.py` |
| `tools/execindex_debug.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/execindex_debug.py` |
| `tools/execindex_identity.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/execindex_identity.py` |
| `tools/execindex_pad.py` | FINISHED-LANE; TEXT-MATCHER | `tools/execindex_debug.py` | moved unchanged to `tools/archive/tools/execindex_pad.py` |
| `tools/execindex_proof_record.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/execindex_proof_record.py` |
| `tools/execindex_scope.py` | FINISHED-LANE; TEXT-MATCHER | `tools/infofix_scope.py` | moved unchanged to `tools/archive/tools/execindex_scope.py` |
| `tools/flipfix5_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | `tools/flipfix6_artifacts.py`, `tools/flipfix7_artifacts.py` | moved unchanged to `tools/archive/tools/flipfix5_artifacts.py` |
| `tools/flipfix5_counts.py` | FINISHED-LANE; TEXT-MATCHER | `tools/rootcompat_counts.py`, `tools/trackorder_counts.py` | moved unchanged to `tools/archive/tools/flipfix5_counts.py` |
| `tools/flipfix6_artifacts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/flipfix6_artifacts.py` |
| `tools/flipfix6_counts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/flipfix6_counts.py` |
| `tools/flipfix6_diag.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/flipfix6_diag.py` |
| `tools/flipfix6_evidence.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/flipfix6_evidence.py` |
| `tools/flipfix7_artifacts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/flipfix7_artifacts.py` |
| `tools/flipfix7_budget_counts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/flipfix7_budget_counts.py` |
| `tools/flipfix7_budgets.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/flipfix7_budgets.py` |
| `tools/flipfix7_capture.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/flipfix7_capture.py` |
| `tools/flipfix7_compact_build.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/flipfix7_compact_build.py` |
| `tools/flipfix7_counts.py` | FINISHED-LANE; TEXT-MATCHER | `tools/flipfix7_budget_counts.py` | moved unchanged to `tools/archive/tools/flipfix7_counts.py` |
| `tools/flipfix7_freshness.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/flipfix7_freshness.py` |
| `tools/flipfix7_negative.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/flipfix7_negative.py` |
| `tools/flipfix7_proof.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/flipfix7_proof.py` |
| `tools/flipfix7_snapshot.py` | LIVE | `tests/flipfix7.py` | retained |
| `tools/flipreport_proof.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/flipreport_proof.py` |
| `tools/flipsettle_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | `tools/boot_support_artifacts.py`, `tools/lanefull_artifacts.py` | moved unchanged to `tools/archive/tools/flipsettle_artifacts.py` |
| `tools/flipsettle_controls.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/flipsettle_controls.py` |
| `tools/flushfix2.mk` | LIVE | `tests/gate.sh`, `tools/flushfix2_freshness.py`, `tools/flushfix3_freshness.py` | retained |
| `tools/flushfix2_budget.py` | FINISHED-LANE; TEXT-MATCHER | `tools/flushfix3_budget.py` | moved unchanged to `tools/archive/tools/flushfix2_budget.py` |
| `tools/flushfix2_budget_counts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/flushfix2_budget_counts.py` |
| `tools/flushfix2_counts.py` | FINISHED-LANE | `tools/flushfix2_budget_counts.py`, `tools/flushfix2_live.py`, `tools/flushfix3_counts.py` | moved unchanged to `tools/archive/tools/flushfix2_counts.py` |
| `tools/flushfix2_freshness.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/flushfix2_freshness.py` |
| `tools/flushfix2_identity.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/flushfix2_identity.py` |
| `tools/flushfix2_live.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/flushfix2_live.py` |
| `tools/flushfix2_pad.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/flushfix2_pad.py` |
| `tools/flushfix2_receipts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/flushfix2_receipts.py` |
| `tools/flushfix2_sweep.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/flushfix2_sweep.py` |
| `tools/flushfix2_verification_receipts.py` | FINISHED-LANE | `tools/flushfix3_receipts.py` | moved unchanged to `tools/archive/tools/flushfix2_verification_receipts.py` |
| `tools/flushfix2_verify.py` | FINISHED-LANE | `tools/flushfix3_verify.py` | moved unchanged to `tools/archive/tools/flushfix2_verify.py` |
| `tools/flushfix3.mk` | LIVE | `tests/gate.sh`, `tools/flushfix3_freshness.py`, `tools/flushfix3_work_reference.py` | retained |
| `tools/flushfix3_budget.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/flushfix3_budget.py` |
| `tools/flushfix3_counts.py` | FINISHED-LANE | `tools/flushfix3_budget.py` | moved unchanged to `tools/archive/tools/flushfix3_counts.py` |
| `tools/flushfix3_freshness.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/flushfix3_freshness.py` |
| `tools/flushfix3_receipts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/flushfix3_receipts.py` |
| `tools/flushfix3_verify.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/flushfix3_verify.py` |
| `tools/flushfix3_work_reference.py` | LIVE; TEXT-MATCHER | `tests/gate.sh` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tools/gen_acl_categories.py` | LIVE; TEXT-MATCHER | `tests/gate.sh` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tools/gen_cmddocs.py` | LIVE; TEXT-MATCHER | `tests/gate.sh` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tools/gen_cmdmeta.py` | LIVE; TEXT-MATCHER | `tests/cmdmeta_coverage.py`, `tests/cmdmeta_test.py`, `tools/gen_cmddocs.py` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tools/gt14fix_evidence.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/gt14fix_evidence.py` |
| `tools/infofields2_live.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/infofields2_live.py` |
| `tools/infofields_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | `tools/scriptfix2_artifacts.py`, `tools/versionstr_artifacts.py` | moved unchanged to `tools/archive/tools/infofields_artifacts.py` |
| `tools/infofields_budget.py` | FINISHED-LANE | `tools/infofields_artifacts.py` | moved unchanged to `tools/archive/tools/infofields_budget.py` |
| `tools/infofields_controls.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/infofields_controls.py` |
| `tools/infofields_monitor_strict.py` | FINISHED-LANE | `tools/infofields2_live.py` | moved unchanged to `tools/archive/tools/infofields_monitor_strict.py` |
| `tools/infofix_arms.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/infofix_arms.py` |
| `tools/infofix_latency.mk` | LIVE | `tests/gate.sh`, `tools/flushfix3_freshness.py`, `tools/infofix_latency_controls.py` | retained |
| `tools/infofix_latency_controls.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/infofix_latency_controls.py` |
| `tools/infofix_scope.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/infofix_scope.py` |
| `tools/iofix3_artifacts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/iofix3_artifacts.py` |
| `tools/iofix3_ports.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/iofix3_ports.py` |
| `tools/iofix_budget.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/iofix_budget.py` |
| `tools/iofix_full_pad.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/iofix_full_pad.py` |
| `tools/iofix_identity.py` | FINISHED-LANE | `tools/iofix3_artifacts.py` | moved unchanged to `tools/archive/tools/iofix_identity.py` |
| `tools/iofix_pad.py` | FINISHED-LANE; TEXT-MATCHER | `tools/iofix3_artifacts.py` | moved unchanged to `tools/archive/tools/iofix_pad.py` |
| `tools/iopass_controls.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/iopass_controls.py` |
| `tools/iopass_receipts.py` | FINISHED-LANE; TEXT-MATCHER | `tools/iopass_controls.py` | moved unchanged to `tools/archive/tools/iopass_receipts.py` |
| `tools/iopass_validate.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/iopass_validate.py` |
| `tools/iotemplates_proof.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/iotemplates_proof.py` |
| `tools/iowake_budgets.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/iowake_budgets.py` |
| `tools/iowake_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/iowake_counts.py` |
| `tools/iowake_identity.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/iowake_identity.py` |
| `tools/iowake_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/iowake_pad.py` |
| `tools/l4prebuild_artifacts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/l4prebuild_artifacts.py` |
| `tools/lanefull_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/lanefull_artifacts.py` |
| `tools/lanefull_controls.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/lanefull_controls.py` |
| `tools/latencyfix_budget.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/latencyfix_budget.py` |
| `tools/latencyfix_count_trials.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/latencyfix_count_trials.py` |
| `tools/latencyfix_counts.mk` | FINISHED-LANE | `tools/flushfix3_freshness.py`, `tools/latencyfix_count_trials.py` | moved unchanged to `tools/archive/tools/latencyfix_counts.mk` |
| `tools/latencyfix_histogram.mk` | FINISHED-LANE | `tools/flushfix3_freshness.py` | moved unchanged to `tools/archive/tools/latencyfix_histogram.mk` |
| `tools/latencyfix_identity.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/latencyfix_identity.py` |
| `tools/latencyfix_pad.py` | FINISHED-LANE | `tools/scriptfix2_pad.py` | moved unchanged to `tools/archive/tools/latencyfix_pad.py` |
| `tools/lb_episodes.py` | LIVE | `tests/connreset_harness_test.py`, `tools/lbosc3_report.py` | retained |
| `tools/lbfix_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/lbfix_artifacts.py` |
| `tools/lbosc3_pad.py` | LIVE; TEXT-MATCHER | `Makefile` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tools/lbosc3_report.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/lbosc3_report.py` |
| `tools/lbplanner_controls.py` | LIVE; TEXT-MATCHER | `Makefile` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tools/lbplanner_pad.py` | LIVE; TEXT-MATCHER | `Makefile`, `tools/lbosc3_pad.py`, `tools/lbplanner_receipts.py` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tools/lbplanner_pre_receipt.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/lbplanner_pre_receipt.py` |
| `tools/lbplanner_receipts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/lbplanner_receipts.py` |
| `tools/lbplanner_trace.cc` | LIVE | `Makefile`, `tools/iopass_receipts.py` | retained |
| `tools/lbstall_artifacts.py` | LIVE; TEXT-MATCHER | `Makefile`, `tests/cd13b_audit.py`, `tests/cdfix_checks.py`, `tests/climonfix_artifacts.py`, `tests/r7shadow_noop.py`, `tests/r7shadow_pad.py`, `tests/reordertrim.py`, `tests/respcompat_audit.py`, `tests/respcompat_pad.py`, `tests/signalacct_byte_checks.py`, `tests/wb_policy.py`, `tools/aclkeys_artifacts.py`, `tools/aoffix2_pad.py`, `tools/aoffix_artifacts.py`, `tools/assert_artifacts.py`, `tools/at412_artifacts.py`, `tools/at412_budget.py`, `tools/at_recycle_artifacts.py`, `tools/atomfix6_budget.py`, `tools/blockfix2_pad.py`, `tools/blockfix3_pad.py`, `tools/blockfix4_pad.py`, `tools/blockfix_identity.py`, `tools/blockfix_pad.py`, `tools/blockwake_pad.py`, `tools/boot_support_artifacts.py`, `tools/ccfix_audit.py`, `tools/cfgfix2_pad.py`, `tools/cfgfix_pad.py`, `tools/clientcompat_pad.py`, `tools/cmdfix2_compact_units.py`, `tools/cmdfix2_pad.py`, `tools/cmdfix_artifacts.py`, `tools/cmdmeta_audit.py`, `tools/crlffix_arms.py`, `tools/ctlfix_artifacts.py`, `tools/datafix1_pad.py`, `tools/deadcode2_artifacts.py`, `tools/deadcode2_linked.py`, `tools/deadcode2_pad.py`, `tools/deadfused_artifacts.py`, `tools/encodingfix_pad.py`, `tools/exbatch_artifacts.py`, `tools/exbatch_directed.py`, `tools/exbatch_source_proof.py`, `tools/exec1s_budget.py`, `tools/exec1s_pad.py`, `tools/exec1s_pad_scope.py`, `tools/execfifo3_artifacts.py`, `tools/execfifo_budget.py`, `tools/execindex_budget.py`, `tools/execindex_identity.py`, `tools/execindex_pad.py`, `tools/flipfix7_budgets.py`, `tools/flipreport_proof.py`, `tools/flipsettle_artifacts.py`, `tools/flushfix2_budget.py`, `tools/flushfix2_pad.py`, `tools/infofix_arms.py`, `tools/iofix_full_pad.py`, `tools/iofix_pad.py`, `tools/iopass_receipts.py`, `tools/iotemplates_proof.py`, `tools/iowake_budgets.py`, `tools/iowake_identity.py`, `tools/iowake_pad.py`, `tools/l4prebuild_artifacts.py`, `tools/lanefull_artifacts.py`, `tools/latencyfix_identity.py`, `tools/latencyfix_pad.py`, `tools/lbfix_artifacts.py`, `tools/lbosc3_pad.py`, `tools/lbplanner_pad.py`, `tools/lbplanner_receipts.py`, `tools/lualibs_artifacts.py`, `tools/mdbqsbr_artifacts.py`, `tools/mdbstamp_artifacts.py`, `tools/mkfix2_pad.py`, `tools/mset8fix_budgets.py`, `tools/mset8fix_pad.py`, `tools/multidb2_artifacts.py`, `tools/multidb3_artifacts.py`, `tools/multidb_artifacts.py`, `tools/netfix2_artifacts.py`, `tools/netfix2_diagnostics.py`, `tools/notifycompat_pad.py`, `tools/overlapaxe_artifacts.py`, `tools/parkwake_budgets.py`, `tools/parkwake_pad.py`, `tools/persistfix2_artifacts.py`, `tools/persistfix_artifacts.py`, `tools/prefetch_artifacts.py`, `tools/probeadapter_proof.py`, `tools/psfix_artifacts.py`, `tools/publishfix_pad.py`, `tools/readreply_proof.py`, `tools/reorder_pad.py`, `tools/reorderscan_pad.py`, `tools/rlfence_artifacts.py`, `tools/rltopo_artifacts.py`, `tools/rootcompat_budget.py`, `tools/rootcore_pad.py`, `tools/scriptfix2_artifacts.py`, `tools/scriptfix3_pad.py`, `tools/scriptfix4_pad.py`, `tools/serverfix_hot_identity.py`, `tools/serverfix_pad.py`, `tools/shutsave_audit.py`, `tools/shutsave_pad.py`, `tools/signalacct_artifacts.py`, `tools/signalacct_tail_artifacts.py`, `tools/snapfix2_artifacts.py`, `tools/snapfix_budget.py`, `tools/snapfix_pad.py`, `tools/splitlocal_artifacts.py`, `tools/storesize_artifacts.py`, `tools/tlsserve_proof.py`, `tools/trackorder_pad.py`, `tools/ttlstate_proof.py`, `tools/txnfix4_pad.py`, `tools/wave11_normalize.py`, `tools/wave14_summary.py`, `tools/wave16_budgets.py`, `tools/wave16_pad.py`, `tools/wb_rule_2s_artifacts.py`, `tools/wb_rule_artifacts.py`, `tools/wb_rule_receipts.py`, `tools/wbknobs_receipts.py`, `tools/wbland_artifacts.py` | Shared ELF name canonicalization for renamed stable roles; byte/relocation comparisons unchanged. |
| `tools/lottery_build.py` | LIVE; TEXT-MATCHER | `Makefile` | 62 checked insertion sites, token replacements, two explicit publication markers; missing/duplicate anchors reject. |
| `tools/lualibs_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/lualibs_artifacts.py` |
| `tools/lualibs_proof.sh` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/lualibs_proof.sh` |
| `tools/mdbqsbr_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/mdbqsbr_artifacts.py` |
| `tools/mdbstamp_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/mdbstamp_artifacts.py` |
| `tools/mkfix2_pad.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/mkfix2_pad.py` |
| `tools/mkfix_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/mkfix_counts.py` |
| `tools/mkprobe_probe.py` | FINISHED-LANE | `tools/mkfix_counts.py`, `tools/overlapaxe_artifacts.py` | moved unchanged to `tools/archive/tools/mkprobe_probe.py` |
| `tools/mset8fix_budgets.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/mset8fix_budgets.py` |
| `tools/mset8fix_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/mset8fix_counts.py` |
| `tools/mset8fix_identity.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/mset8fix_identity.py` |
| `tools/mset8fix_latency.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/mset8fix_latency.py` |
| `tools/mset8fix_loop.sh` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/mset8fix_loop.sh` |
| `tools/mset8fix_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/mset8fix_pad.py` |
| `tools/mset8fix_proof.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/mset8fix_proof.py` |
| `tools/multidb2_artifacts.py` | LIVE | `Makefile` | retained |
| `tools/multidb3_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/multidb3_artifacts.py` |
| `tools/multidb_artifacts.py` | LIVE | `Makefile` | retained |
| `tools/netfix2_artifacts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/netfix2_artifacts.py` |
| `tools/netfix2_counts.py` | FINISHED-LANE | `tools/netfix2_tls_counts.py` | moved unchanged to `tools/archive/tools/netfix2_counts.py` |
| `tools/netfix2_diagnostics.py` | FINISHED-LANE | `tools/netfix2_proof.sh` | moved unchanged to `tools/archive/tools/netfix2_diagnostics.py` |
| `tools/netfix2_proof.sh` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/netfix2_proof.sh` |
| `tools/netfix2_tls_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/netfix2_tls_counts.py` |
| `tools/netfix_collect.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/netfix_collect.py` |
| `tools/netfix_identity.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/netfix_identity.py` |
| `tools/netfix_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/netfix_pad.py` |
| `tools/netfix_pad_b.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/netfix_pad_b.py` |
| `tools/netfix_verify.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/netfix_verify.py` |
| `tools/nicrestore.sh` | MANUAL | none in scoped code | retained |
| `tools/notifycompat_identity.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/notifycompat_identity.py` |
| `tools/notifycompat_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/notifycompat_pad.py` |
| `tools/notifycompat_schedule.py` | LIVE; TEXT-MATCHER | `tests/gate.sh` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tools/nsrun.c` | MANUAL | none in scoped code | retained |
| `tools/ntfix_proof.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/ntfix_proof.py` |
| `tools/nullpublish_refreeze.py` | LIVE; TEXT-MATCHER | `tests/nullpublish_refreeze_test.py` | Gate/receipt text matcher; does not inspect production C++. Existing fixture/row tests retained. |
| `tools/overlapaxe_artifacts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/overlapaxe_artifacts.py` |
| `tools/parkwake_budgets.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/parkwake_budgets.py` |
| `tools/parkwake_counts.py` | FINISHED-LANE | `tools/wave16_counts.py` | moved unchanged to `tools/archive/tools/parkwake_counts.py` |
| `tools/parkwake_identity.py` | FINISHED-LANE; TEXT-MATCHER | `tools/wave16_identity.py` | moved unchanged to `tools/archive/tools/parkwake_identity.py` |
| `tools/parkwake_loop.sh` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/parkwake_loop.sh` |
| `tools/parkwake_matrix.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/parkwake_matrix.py` |
| `tools/parkwake_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/parkwake_pad.py` |
| `tools/parkwake_summary.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/parkwake_summary.py` |
| `tools/persistfix2_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/persistfix2_artifacts.py` |
| `tools/persistfix_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/persistfix_artifacts.py` |
| `tools/persistfix_controls.py` | LIVE; TEXT-MATCHER | `Makefile` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tools/persistfmt.mk` | LIVE | `tests/gate.sh`, `tools/flushfix3_freshness.py` | retained |
| `tools/persistfmt_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/persistfmt_counts.py` |
| `tools/persistfmt_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/persistfmt_pad.py` |
| `tools/persistfmt_schedule.py` | LIVE; TEXT-MATCHER | `tools/persistfmt.mk` | Token replacements with exact-one guards, including namespace insertion. |
| `tools/persistfmt_validate.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/persistfmt_validate.py` |
| `tools/prefetch_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/prefetch_artifacts.py` |
| `tools/probeadapter_proof.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/probeadapter_proof.py` |
| `tools/psfix_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | `tools/aclkeys_artifacts.py`, `tools/blockfix_identity.py`, `tools/lualibs_artifacts.py`, `tools/persistfix2_artifacts.py`, `tools/serverfix_hot_identity.py` | moved unchanged to `tools/archive/tools/psfix_artifacts.py` |
| `tools/publishfix_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/publishfix_pad.py` |
| `tools/publishfix_schedule.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/publishfix_schedule.py` |
| `tools/quietcheck.sh` | LIVE | `tests/gate.sh`, `tests/gates_test.py`, `tools/infofields2_live.py` | retained |
| `tools/racefix_build.py` | LIVE; TEXT-MATCHER | `Makefile` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tools/readreply_proof.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/readreply_proof.py` |
| `tools/reorder_pad.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/reorder_pad.py` |
| `tools/reorder_sync.py` | LIVE; TEXT-MATCHER | `Makefile`, `tests/r7shadow_sync.py`, `tests/signalacct_source_checks.py`, `tests/wbland_checks.py` | Alias to the same token-based R7 generator; exact unique generated-region markers. |
| `tools/reorderscan_pad.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/reorderscan_pad.py` |
| `tools/respresume_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/respresume_artifacts.py` |
| `tools/respresume_fastpath.py` | FINISHED-LANE | `tools/respresume_fastpath_report.py` | moved unchanged to `tools/archive/tools/respresume_fastpath.py` |
| `tools/respresume_fastpath_report.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/respresume_fastpath_report.py` |
| `tools/respresume_observer.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/respresume_observer.py` |
| `tools/respresume_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/respresume_pad.py` |
| `tools/respresume_probe.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/respresume_probe.py` |
| `tools/respresume_repro.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/respresume_repro.py` |
| `tools/respresume_t12x.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/respresume_t12x.py` |
| `tools/respresume_trace.cc` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/respresume_trace.cc` |
| `tools/respresume_trace.py` | FINISHED-LANE | `tools/respresume_fastpath.py`, `tools/respresume_fastpath_report.py` | moved unchanged to `tools/archive/tools/respresume_trace.py` |
| `tools/ringmarker_proof.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/ringmarker_proof.py` |
| `tools/rlfence_artifacts.py` | LIVE; TEXT-MATCHER | `Makefile`, `tests/respcompat_pad.py`, `tools/aclkeys_artifacts.py`, `tools/cmdmeta_audit.py`, `tools/crlffix_arms.py`, `tools/crlffix_fast_scope.py`, `tools/deadcode2_pad.py`, `tools/deadfused_artifacts.py`, `tools/exbatch_artifacts.py`, `tools/exbatch_source_proof.py`, `tools/flipfix5_artifacts.py`, `tools/flipfix5_counts.py`, `tools/flipfix6_counts.py`, `tools/flipfix7_counts.py`, `tools/infofix_scope.py`, `tools/lbosc3_pad.py`, `tools/lbplanner_pad.py`, `tools/lbplanner_receipts.py`, `tools/overlapaxe_artifacts.py` | Stable role translation for selected objdump symbol and disassembly labels; opcode checks unchanged. |
| `tools/rlfix3_info_compare.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/rlfix3_info_compare.py` |
| `tools/rlfix3_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/rlfix3_pad.py` |
| `tools/rlfix3_units.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/rlfix3_units.py` |
| `tools/rlfix5.mk` | LIVE | `tests/gate.sh`, `tools/flushfix3_freshness.py` | retained |
| `tools/rlfix5_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | `tools/rlfix5_refreeze_comments.py` | moved unchanged to `tools/archive/tools/rlfix5_artifacts.py` |
| `tools/rlfix5_elf.py` | LIVE | `tools/rlfix5_proof.py`, `tools/rlfix5_refreeze_comments.py` | retained |
| `tools/rlfix5_proof.py` | LIVE | `tools/rlfix5.mk`, `tools/rlfix5_refreeze_comments.py` | retained |
| `tools/rlfix5_refreeze_comments.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/rlfix5_refreeze_comments.py` |
| `tools/rlfix5_validate.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/rlfix5_validate.py` |
| `tools/rltopo_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/rltopo_artifacts.py` |
| `tools/rootcompat_budget.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/rootcompat_budget.py` |
| `tools/rootcompat_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/rootcompat_counts.py` |
| `tools/rootcompat_pad.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/rootcompat_pad.py` |
| `tools/rootcore_archive_data.py` | FINISHED-LANE | `tools/rootcore_proof.py` | moved unchanged to `tools/archive/tools/rootcore_archive_data.py` |
| `tools/rootcore_collect_proof.py` | FINISHED-LANE | `tools/rootcore_proof.py` | moved unchanged to `tools/archive/tools/rootcore_collect_proof.py` |
| `tools/rootcore_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/rootcore_counts.py` |
| `tools/rootcore_freshness.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/rootcore_freshness.py` |
| `tools/rootcore_inbox.py` | LIVE; TEXT-MATCHER | `tests/gate.sh` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tools/rootcore_pad.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/rootcore_pad.py` |
| `tools/rootcore_proof.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/rootcore_proof.py` |
| `tools/rootcore_scheduler.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/rootcore_scheduler.py` |
| `tools/scriptfix2_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/scriptfix2_artifacts.py` |
| `tools/scriptfix2_counts.mk` | FINISHED-LANE | `tools/flushfix3_freshness.py` | moved unchanged to `tools/archive/tools/scriptfix2_counts.mk` |
| `tools/scriptfix2_mutant.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/scriptfix2_mutant.py` |
| `tools/scriptfix2_negative.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/scriptfix2_negative.py` |
| `tools/scriptfix2_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/scriptfix2_pad.py` |
| `tools/scriptfix3_attribution.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/scriptfix3_attribution.py` |
| `tools/scriptfix3_counts.py` | FINISHED-LANE; TEXT-MATCHER | `tools/scriptfix3_attribution.py` | moved unchanged to `tools/archive/tools/scriptfix3_counts.py` |
| `tools/scriptfix3_jobs.py` | FINISHED-LANE | `tools/scriptfix3_proof.py` | moved unchanged to `tools/archive/tools/scriptfix3_jobs.py` |
| `tools/scriptfix3_pad.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/scriptfix3_pad.py` |
| `tools/scriptfix3_proof.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/scriptfix3_proof.py` |
| `tools/scriptfix3_receipts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/scriptfix3_receipts.py` |
| `tools/scriptfix3_trace.cc` | LIVE | `tools/atomfix6_counts.py`, `tools/blockwake_counts.py`, `tools/cfgfix2_counts.py`, `tools/cfgfix_counts.py`, `tools/clientcompat_counts.py`, `tools/cmdfix2_counts.py`, `tools/iowake_counts.py`, `tools/mset8fix_counts.py`, `tools/netfix2_counts.py`, `tools/parkwake_counts.py`, `tools/persistfmt_counts.py`, `tools/rlfix5_proof.py`, `tools/rootcore_counts.py`, `tools/scriptfix3_counts.py`, `tools/scriptfix4_counts.py`, `tools/storefix5_counts.py`, `tools/wave11_counts.py`, `tools/wave12_counts.py`, `tools/wave13_counts.py`, `tools/wave14_counts.py`, `tools/wave15_counts.py`, `tools/wave16_counts.py` | retained |
| `tools/scriptfix4_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/scriptfix4_counts.py` |
| `tools/scriptfix4_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/scriptfix4_pad.py` |
| `tools/serverfix_hot_identity.py` | FINISHED-LANE; TEXT-MATCHER | `tools/persistfix2_artifacts.py` | moved unchanged to `tools/archive/tools/serverfix_hot_identity.py` |
| `tools/serverfix_identity.py` | FINISHED-LANE | `tools/persistfix2_artifacts.py` | moved unchanged to `tools/archive/tools/serverfix_identity.py` |
| `tools/serverfix_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/serverfix_pad.py` |
| `tools/setregress.py` | MANUAL | none in scoped code | retained |
| `tools/shutsave_artifacts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/shutsave_artifacts.py` |
| `tools/shutsave_audit.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/shutsave_audit.py` |
| `tools/shutsave_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/shutsave_pad.py` |
| `tools/signalacct_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | `tools/signalacct_tail_artifacts.py` | moved unchanged to `tools/archive/tools/signalacct_artifacts.py` |
| `tools/signalacct_tail_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/signalacct_tail_artifacts.py` |
| `tools/snapfix2_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/snapfix2_artifacts.py` |
| `tools/snapfix2_nx_control.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/snapfix2_nx_control.py` |
| `tools/snapfix2_verify.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/snapfix2_verify.py` |
| `tools/snapfix_budget.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/snapfix_budget.py` |
| `tools/snapfix_budget_bodies.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/snapfix_budget_bodies.py` |
| `tools/snapfix_identity.py` | FINISHED-LANE; TEXT-MATCHER | `tools/iowake_identity.py`, `tools/snapfix2_artifacts.py`, `tools/snapfix_budget.py`, `tools/snapfix_budget_bodies.py` | moved unchanged to `tools/archive/tools/snapfix_identity.py` |
| `tools/snapfix_long_storm.py` | FINISHED-LANE | `tools/snapfix2_verify.py` | moved unchanged to `tools/archive/tools/snapfix_long_storm.py` |
| `tools/snapfix_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/snapfix_pad.py` |
| `tools/snapfix_record.py` | FINISHED-LANE | `tools/snapfix2_verify.py` | moved unchanged to `tools/archive/tools/snapfix_record.py` |
| `tools/snapfix_reproduce.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/snapfix_reproduce.py` |
| `tools/snapfix_scope.py` | FINISHED-LANE; TEXT-MATCHER | `tools/snapfix2_artifacts.py` | moved unchanged to `tools/archive/tools/snapfix_scope.py` |
| `tools/snapfix_stacks.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/snapfix_stacks.py` |
| `tools/snapfix_storm_capture.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/snapfix_storm_capture.py` |
| `tools/source_identity.py` | LIVE; TEXT-MATCHER | `Makefile`, `tests/tomo_assert_checks.py` | Existing lexer retained; empty production source inventory now rejected. |
| `tools/splitlocal_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/splitlocal_artifacts.py` |
| `tools/storefix5_append.py` | FINISHED-LANE; TEXT-MATCHER | `tools/storefix5_final_proof.py` | moved unchanged to `tools/archive/tools/storefix5_append.py` |
| `tools/storefix5_archive.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/storefix5_archive.py` |
| `tools/storefix5_arm.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/storefix5_arm.py` |
| `tools/storefix5_audit.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/storefix5_audit.py` |
| `tools/storefix5_budgets.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/storefix5_budgets.py` |
| `tools/storefix5_checks.py` | FINISHED-LANE | `tools/storefix5_final_proof.py`, `tools/storefix5_finish_proof.py`, `tools/storefix5_memory.py`, `tools/storefix5_report.py` | moved unchanged to `tools/archive/tools/storefix5_checks.py` |
| `tools/storefix5_clock_geometry.cc` | FINISHED-LANE | `tools/storefix5_report.py` | moved unchanged to `tools/archive/tools/storefix5_clock_geometry.cc` |
| `tools/storefix5_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/storefix5_counts.py` |
| `tools/storefix5_final_proof.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/storefix5_final_proof.py` |
| `tools/storefix5_finish_proof.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/storefix5_finish_proof.py` |
| `tools/storefix5_inventory_proof.py` | FINISHED-LANE | `tools/storefix5_finish_proof.py` | moved unchanged to `tools/archive/tools/storefix5_inventory_proof.py` |
| `tools/storefix5_memory.py` | FINISHED-LANE | `tools/storefix5_final_proof.py`, `tools/storefix5_report.py` | moved unchanged to `tools/archive/tools/storefix5_memory.py` |
| `tools/storefix5_notification_proof.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/storefix5_notification_proof.py` |
| `tools/storefix5_pad.py` | FINISHED-LANE; TEXT-MATCHER | `tools/storefix5_finish_proof.py` | moved unchanged to `tools/archive/tools/storefix5_pad.py` |
| `tools/storefix5_proofs.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/storefix5_proofs.py` |
| `tools/storefix5_report.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/storefix5_report.py` |
| `tools/storefix5_retirement.py` | FINISHED-LANE; TEXT-MATCHER | `tools/storefix5_finish_proof.py` | moved unchanged to `tools/archive/tools/storefix5_retirement.py` |
| `tools/storefix5_serial_proof.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/storefix5_serial_proof.py` |
| `tools/storesize_artifacts.py` | LIVE; TEXT-MATCHER | `tests/storesize_checks.py` | Shared ELF role canonicalization; exactly two route bodies and exact opcode/layout checks retained. |
| `tools/storesize_poller.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/storesize_poller.py` |
| `tools/tailgen/README.md` | LIVE | `tools/execfifo3_perf_summary.py`, `tools/tailgen/main.cc` | retained |
| `tools/tailgen/config.h` | LIVE | `Makefile`, `tests/config_parser_test.cc`, `tests/docs_drift.py`, `tests/ktls_keyupdate_unit.cc`, `tests/mkfix2_unit.cc`, `tests/r7shadow_unit.cc`, `tests/reorder_scope.py`, `tests/reordertrim.py`, `tests/serverfix_config.py`, `tests/tailgen_unit.cc`, `tests/waits_unit.cc`, `tests/wbland_unit.cc`, `tools/cfgfix_inventory.py`, `tools/tailgen/main.cc` | retained |
| `tools/tailgen/connection.h` | LIVE | `tests/tailgen_unit.cc`, `tools/tailgen/main.cc` | retained |
| `tools/tailgen/histogram.h` | LIVE | `tests/latencyfix_histogram_unit.cc`, `tests/tailgen_unit.cc`, `tools/tailgen/main.cc`, `tools/tailgen/report.h` | retained |
| `tools/tailgen/main.cc` | LIVE | `Makefile`, `tests/boot_failures.py`, `tests/gate.sh`, `tests/gates_test.py`, `tests/r7shadow_split_witness.py`, `tools/boot_support_artifacts.py`, `tools/ccfix4_budget.py`, `tools/iotemplates_proof.py`, `tools/lbfix_artifacts.py`, `tools/lbplanner_pad.py`, `tools/lbplanner_receipts.py`, `tools/readreply_proof.py`, `tools/tlsserve_proof.py` | retained |
| `tools/tailgen/outstanding.h` | LIVE | `tests/tailgen_unit.cc`, `tools/tailgen/main.cc` | retained |
| `tools/tailgen/pacing.h` | LIVE | `tests/tailgen_unit.cc`, `tools/tailgen/workload.h` | retained |
| `tools/tailgen/report.h` | LIVE | `tests/core_concurrency_unit.cc`, `tests/tailgen_unit.cc`, `tools/tailgen/main.cc` | retained |
| `tools/tailgen/resp.h` | LIVE | `tests/ccfix_unit.cc`, `tests/multidb_cost_unit.cc`, `tests/multidb_db0_unit.cc`, `tests/racefix_hook.h`, `tests/respcompat_replay.py`, `tests/respcompat_unit.cc`, `tests/tailgen_unit.cc`, `tests/wb_rule_unit.cc`, `tools/respresume_observer.py`, `tools/tailgen/connection.h` | retained |
| `tools/tailgen/workload.h` | LIVE | `tools/tailgen/config.h`, `tools/tailgen/connection.h` | retained |
| `tools/tlsserve_proof.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/tlsserve_proof.py` |
| `tools/tomokv-nic.service` | MANUAL | none in scoped code | retained |
| `tools/trackfix_schedule.py` | LIVE; TEXT-MATCHER | `tests/gate.sh` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |
| `tools/trackorder_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/trackorder_counts.py` |
| `tools/trackorder_pad.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/trackorder_pad.py` |
| `tools/trackorder_run.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/trackorder_run.py` |
| `tools/trackorder_units.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/trackorder_units.py` |
| `tools/ttlstate_proof.py` | LIVE; TEXT-MATCHER | `tools/boot_support_artifacts.py`, `tools/exbatch_artifacts.py`, `tools/flipreport_proof.py`, `tools/iotemplates_proof.py`, `tools/lanefull_artifacts.py`, `tools/probeadapter_proof.py`, `tools/readreply_proof.py`, `tools/ringmarker_proof.py`, `tools/splitlocal_artifacts.py`, `tools/tlsserve_proof.py` | LIVE ELF helper imports only. Historical source()/CLI fixed-line proof is not invoked by gate or make; retained with its library. |
| `tools/txnfix4_abort_site.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/txnfix4_abort_site.py` |
| `tools/txnfix4_auditors.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/txnfix4_auditors.py` |
| `tools/txnfix4_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/txnfix4_pad.py` |
| `tools/txnfix4_probes.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/txnfix4_probes.py` |
| `tools/txnfix4_proof.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/txnfix4_proof.py` |
| `tools/txnfix4_scope.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/txnfix4_scope.py` |
| `tools/txnfix_admission_control.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/txnfix_admission_control.py` |
| `tools/txnfix_barrier_control.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/txnfix_barrier_control.py` |
| `tools/txnfix_budget.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/txnfix_budget.py` |
| `tools/txnfix_pad.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/txnfix_pad.py` |
| `tools/txnfix_path_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/txnfix_path_counts.py` |
| `tools/txnfix_scatter_audit.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/txnfix_scatter_audit.py` |
| `tools/versionstr_artifacts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/versionstr_artifacts.py` |
| `tools/versionstr_smoke.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/versionstr_smoke.py` |
| `tools/wave10.py` | LIVE; TEXT-MATCHER | `tests/gate.sh` | Retained utility imports/historical receipt orchestration; frozen-reference commands are not replayed by ordinary gate. |
| `tools/wave10_normalize.py` | LIVE; TEXT-MATCHER | `tools/wave10.py`, `tools/wave11_budgets.py`, `tools/wave11_normalize.py` | Instruction/literal parser, not C++ source; its audit uses shared canonical ELF names. |
| `tools/wave11.py` | FINISHED-LANE; TEXT-MATCHER | `tools/wave11_budgets.py` | moved unchanged to `tools/archive/tools/wave11.py` |
| `tools/wave11_budgets.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/wave11_budgets.py` |
| `tools/wave11_counts.py` | FINISHED-LANE; TEXT-MATCHER | `tools/iowake_counts.py`, `tools/netfix2_counts.py`, `tools/netfix2_diagnostics.py`, `tools/persistfmt_counts.py`, `tools/wave16_counts.py` | moved unchanged to `tools/archive/tools/wave11_counts.py` |
| `tools/wave11_normalize.py` | LIVE; TEXT-MATCHER | `tools/wave11.py`, `tools/wave12_normalize.py` | Instruction/literal parser, not C++ source; its audit uses shared canonical ELF names. |
| `tools/wave12.py` | FINISHED-LANE; TEXT-MATCHER | `tools/wave12_budgets.py` | moved unchanged to `tools/archive/tools/wave12.py` |
| `tools/wave12_budgets.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/wave12_budgets.py` |
| `tools/wave12_counts.py` | FINISHED-LANE; TEXT-MATCHER | `tools/atomfix6_counts.py`, `tools/clientcompat_counts.py`, `tools/clientcompat_inline_trials.py`, `tools/clientcompat_pause_audit.py`, `tools/rootcore_counts.py`, `tools/scriptfix4_counts.py` | moved unchanged to `tools/archive/tools/wave12_counts.py` |
| `tools/wave12_normalize.py` | LIVE | `tools/mset8fix_identity.py`, `tools/parkwake_identity.py`, `tools/rlfix5_artifacts.py`, `tools/wave12.py`, `tools/wave12_budgets.py`, `tools/wave13.py`, `tools/wave13_budgets.py`, `tools/wave14.py`, `tools/wave14_budgets.py`, `tools/wave15.py`, `tools/wave15_budgets.py` | retained |
| `tools/wave13.py` | FINISHED-LANE; TEXT-MATCHER | `tools/wave13_budgets.py` | moved unchanged to `tools/archive/tools/wave13.py` |
| `tools/wave13_budgets.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/wave13_budgets.py` |
| `tools/wave13_counts.py` | LIVE; TEXT-MATCHER | `tools/blockwake_counts.py`, `tools/cfgfix2_counts.py`, `tools/cfgfix_counts.py`, `tools/cmdfix2_counts.py`, `tools/mset8fix_counts.py`, `tools/parkwake_counts.py`, `tools/rlfix5.mk`, `tools/rlfix5_artifacts.py`, `tools/rlfix5_proof.py`, `tools/rlfix5_validate.py`, `tools/storefix5_append.py`, `tools/storefix5_counts.py`, `tools/wave14_counts.py`, `tools/wave15_counts.py` | Retained instruction census helper; public main/namespace boundaries and supplied fixture paths, no C++ text patch. |
| `tools/wave14.py` | LIVE; TEXT-MATCHER | `tools/eoffix_bind.py`, `tools/wave14_arms.py`, `tools/wave14_budgets.py`, `tools/wave14_capture.py`, `tools/wave14_cleanup.py`, `tools/wave14_closeout.py`, `tools/wave14_counts.py`, `tools/wave14_coverage.py`, `tools/wave14_eof_budgets.py`, `tools/wave14_fifo_controls.py`, `tools/wave14_followthrough.py`, `tools/wave14_r7_control.py`, `tools/wave14_summary.py`, `tools/wave14_txnorder_diagnostics.py`, `tools/wave14_validation.py`, `tools/wave14_xacct_followthrough.py` | LIVE ROOT/sha/save imports only; historical source-editing CLI is not invoked by the gate. |
| `tools/wave14_arms.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/wave14_arms.py` |
| `tools/wave14_budgets.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/wave14_budgets.py` |
| `tools/wave14_capture.py` | LIVE; TEXT-MATCHER | `tests/gate.sh` | Exact unique undefined-symbol roles in both namespaces; hook receives current mangled names. |
| `tools/wave14_cleanup.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/wave14_cleanup.py` |
| `tools/wave14_closeout.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/wave14_closeout.py` |
| `tools/wave14_counts.py` | FINISHED-LANE | `tools/eoffix_counts.py`, `tools/eoffix_receive_counts.py` | moved unchanged to `tools/archive/tools/wave14_counts.py` |
| `tools/wave14_coverage.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/wave14_coverage.py` |
| `tools/wave14_eof_budgets.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/wave14_eof_budgets.py` |
| `tools/wave14_fifo_controls.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/wave14_fifo_controls.py` |
| `tools/wave14_followthrough.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/wave14_followthrough.py` |
| `tools/wave14_r7_control.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/wave14_r7_control.py` |
| `tools/wave14_summary.py` | FINISHED-LANE; TEXT-MATCHER | `tools/eoffix_bind.py`, `tools/eoffix_compare.py`, `tools/wave15_bind.py` | moved unchanged to `tools/archive/tools/wave14_summary.py` |
| `tools/wave14_txnorder_diagnostics.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/wave14_txnorder_diagnostics.py` |
| `tools/wave14_validation.py` | FINISHED-LANE | `tools/wave14_coverage.py` | moved unchanged to `tools/archive/tools/wave14_validation.py` |
| `tools/wave14_xacct_followthrough.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/wave14_xacct_followthrough.py` |
| `tools/wave15.py` | FINISHED-LANE; TEXT-MATCHER | `tools/wave15_aof_stacks.py`, `tools/wave15_bind.py`, `tools/wave15_budgets.py`, `tools/wave15_counts.py`, `tools/wave15_lua_binding.py` | moved unchanged to `tools/archive/tools/wave15.py` |
| `tools/wave15_aof_stacks.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/wave15_aof_stacks.py` |
| `tools/wave15_bind.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/wave15_bind.py` |
| `tools/wave15_budgets.py` | FINISHED-LANE; TEXT-MATCHER | `tools/wave15_refine.py` | moved unchanged to `tools/archive/tools/wave15_budgets.py` |
| `tools/wave15_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/wave15_counts.py` |
| `tools/wave15_lua_binding.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/wave15_lua_binding.py` |
| `tools/wave15_refine.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/wave15_refine.py` |
| `tools/wave15_scan_expiry.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/wave15_scan_expiry.py` |
| `tools/wave16_budgets.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/wave16_budgets.py` |
| `tools/wave16_counts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/wave16_counts.py` |
| `tools/wave16_identity.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/wave16_identity.py` |
| `tools/wave16_pad.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/wave16_pad.py` |
| `tools/wave5b_trace.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/wave5b_trace.py` |
| `tools/wave8b.mk` | LIVE | `tests/gate.sh`, `tools/flushfix3_freshness.py` | retained |
| `tools/wb_rule_2s_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/wb_rule_2s_artifacts.py` |
| `tools/wb_rule_2s_trace.cc` | FINISHED-LANE | `tools/wb_rule_2s_artifacts.py`, `tools/wb_rule_receipts.py`, `tools/wbknobs_receipts.py` | moved unchanged to `tools/archive/tools/wb_rule_2s_trace.cc` |
| `tools/wb_rule_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | `tools/wb_rule_2s_artifacts.py` | moved unchanged to `tools/archive/tools/wb_rule_artifacts.py` |
| `tools/wb_rule_receipts.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/wb_rule_receipts.py` |
| `tools/wbknobs_measure.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/wbknobs_measure.py` |
| `tools/wbknobs_receipts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/wbknobs_receipts.py` |
| `tools/wbland_artifacts.py` | FINISHED-LANE; TEXT-MATCHER | none in scoped code | moved unchanged to `tools/archive/tools/wbland_artifacts.py` |
| `tools/woundfix_gate.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/woundfix_gate.py` |
| `tools/woundfix_live.py` | FINISHED-LANE | none in scoped code | moved unchanged to `tools/archive/tools/woundfix_live.py` |
| `tools/woundfix_windows.py` | LIVE; TEXT-MATCHER | `Makefile` | Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence. |

### Gate and Makefile reference lines

Every baseline line mentioning a scoped tool or test is listed, including prerequisites, includes and comments. This is deliberately broader than runtime calls. No row is removed.

| Source line | Reference |
|---|---|
| `Makefile:84` | `ATOMFIX6_UNIT_SRC := tests/atomfix6_unit.cc src/store/flush.cc src/cmd/storesize.cc src/cmd/multidb.cc` |
| `Makefile:90` | `build/atomfix6-park-unit: tests/atomfix6_park_unit.cc $(filter-out build/src/main.o,$(OBJ)) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile` |
| `Makefile:92` | `build/atomfix6-park-db0-unit: tests/atomfix6_park_unit.cc $(filter-out build/db0/src/main.o,$(DB0_OBJ)) $(filter-out build/src/main.o,$(OBJ)) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile` |
| `Makefile:96` | `build/atomwake-unit: tests/atomwake_unit.cc $(filter-out build/src/main.o,$(OBJ)) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile` |
| `Makefile:99` | `build/atomfix6-queue-asan build/atomfix6-queue-tsan: tests/atomfix6_queue_unit.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile` |
| `Makefile:107` | `$(ASSERT_MAP): tools/assert_map.py $(ASSERT_SOURCES) $(ASSERT_DIRS) Makefile` |
| `Makefile:108` | `python3 tools/assert_map.py --output $@ --cxx "$(CXX)"` |
| `Makefile:121` | `build/lottery/tomokv: tools/lottery_build.py tools/assert_map.py tests/lottery_hooks.h $(SRC) $(SERVER_ONLY_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile` |
| `Makefile:122` | `python3 tools/lottery_build.py build/lottery/source` |
| `Makefile:132` | `build/respresume-unit: tests/respresume_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:137` | `build/aoforder-scheduled: tools/aoforder_schedule.py $(BIN)` |
| `Makefile:138` | `python3 tools/aoforder_schedule.py --objects build --output build/aoforder/scheduled` |
| `Makefile:143` | `build/racefix-climon: tools/racefix_build.py tools/assert_map.py tests/racefix_hook.h $(SRC) $(SERVER_ONLY_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile` |
| `Makefile:144` | `python3 tools/racefix_build.py build/racefix-climon-source` |
| `Makefile:160` | `build/persistfix/unit.o: tests/persistfix_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:166` | `build/persistfix-controls/%/aof.cc: tools/persistfix_controls.py src/persist/aof.cc Makefile` |
| `Makefile:168` | `python3 tools/persistfix_controls.py $* $@` |
| `Makefile:222` | `# Keep every other list body identical; tools/aclkeys4_audit.py checks all bodies.` |
| `Makefile:225` | `# for every ordinary command and storage body; tools/psfix_artifacts.py audits both variants.` |
| `Makefile:232` | `# handler outside cmd_info/cmd_debug_impl PRE-identical (tools/at412_budget.py, docs/at412/budgets2).` |
| `Makefile:262` | `# both database namespaces; tests/cdfix_checks.py audits every emitted function against PRE.` |
| `Makefile:281` | `# in both namespaces. tests/cd13b_audit.py checks every emitted body and linker selection.` |
| `Makefile:354` | `# R7's cold role selectors shift two budgets slightly. tests/reorder_noop.py locks` |
| `Makefile:429` | `# each size-compensated value (tools/mset8fix_budgets.py, docs/mset8fix/budgets) select, per unit,` |
| `Makefile:437` | `# size-compensated value (tools/iowake_budgets.py, docs/iowake/budgets/selected.json) keep every` |
| `Makefile:443` | `# tree by tools/wave16_budgets.py: PRE pin + merged IPA unit growth, then the value with the fewest` |
| `Makefile:516` | `# removed, i.e. the pre-fix behaviour. tests/rlcache_churn.py MUST fail against this binary; a` |
| `Makefile:523` | `# build except that ScriptPhase::Pin arms nothing, so tests/xscript.py counterexample MUST fail` |
| `Makefile:530` | `# runs both (neither boots a server). tests/gate.sh's parser row is the same program.` |
| `Makefile:532` | `build/ktls-keyupdate: tests/ktls_keyupdate.cc Makefile` |
| `Makefile:536` | `build/ktls-keyupdate-unit: tests/ktls_keyupdate_unit.cc src/net/tls.cc src/net/tls.h src/core/config.h Makefile` |
| `Makefile:538` | `$(CXX) $(CXXFLAGS) -I. tests/ktls_keyupdate_unit.cc src/net/tls.cc -o $@ \` |
| `Makefile:540` | `build/splitlocal-unit.cc: tests/splitlocal_checks.py tests/r7shadow_sync.py tools/reorder_sync.py src/core/io_loop.h src/core/reorder.cc src/core/genthread_pipeline.h` |
| `Makefile:542` | `python3 tests/splitlocal_checks.py emit $@` |
| `Makefile:546` | `build/config-parser-test: tests/config_parser_test.cc tests/boot_support_checks.inc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:548` | `$(CXX) $(CXXFLAGS) -I. tests/config_parser_test.cc -o $@` |
| `Makefile:549` | `build/climon-mask-unit: tests/climon_mask_unit.cc src/core/climon_mask.h Makefile` |
| `Makefile:552` | `build/climon-mask-old-unit: tests/climon_mask_unit.cc src/core/climon_mask.h Makefile` |
| `Makefile:557` | `build/flipctl-unit: tests/flipctl_unit.cc tests/signalacct_checks.h src/core/flipctl.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:559` | `$(CXX) $(CXXFLAGS) -I. tests/flipctl_unit.cc src/core/flipctl.cc -o $@` |
| `Makefile:561` | `build/read-local-ring-unit: tests/read_local_ring_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:563` | `$(CXX) $(CXXFLAGS) -I. tests/read_local_ring_unit.cc -o $@` |
| `Makefile:564` | `build/read-local-write-ring-unit: tests/read_local_write_ring_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:566` | `$(CXX) $(CXXFLAGS) -I. tests/read_local_write_ring_unit.cc -o $@` |
| `Makefile:567` | `build/rlfence-unit: tests/rlfence_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:569` | `$(CXX) $(CXXFLAGS) -I. tests/rlfence_unit.cc -o $@` |
| `Makefile:570` | `STORE_REGRESSION_SRC := tests/store_regression.cc src/cmd/t_hash.cc src/cmd/t_hash_ttl.cc src/cmd/hexpread.cc src/cmd/storesize.cc src/store/flush.cc` |
| `Makefile:571` | `build/wave15-idle-unit build/wave15-idle-db0-unit: tests/wave15_idle_unit.cc $(STORE_REGRESSION_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile` |
| `Makefile:574` | `tests/wave15_idle_unit.cc $(filter-out tests/store_regression.cc,$(STORE_REGRESSION_SRC)) $(if $(findstring db0,$@),src/cmd/multidb.cc) -Wl,--gc-sections -o $@` |
| `Makefile:584` | `build/waits-unit: tests/waits_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:586` | `$(CXX) $(CXXFLAGS) -I. tests/waits_unit.cc -o $@` |
| `Makefile:600` | `build/tomo-assert-fail: tests/tomo_assert_fail.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) Makefile` |
| `Makefile:606` | `python3 tools/source_identity.py --cxx "$(CXX)" --cc "$(CC)" --flags "$(CXXFLAGS) $(JEFLAGS)" --jobs $(ASSERT_LINT_JOBS) --sources $(SRC) $(SERVER_ONLY_SRC) --c-sources $(LUA_HELPER_SRC)` |
| `Makefile:608` | `build/rlfix3-info-unit: build/tests/rlfix3_info_unit.o $(CORE_TEST_OBJ)` |
| `Makefile:611` | `build/expire-notify-unit: tests/expire_notify_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:614` | `build/ktls-lifetime-unit: tests/ktls_lifetime_unit.cc tests/core_concurrency_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:617` | `build/respresume-migration: tests/respresume_migration.cc tests/core_concurrency_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:620` | `build/encodingfix-unit: build/tests/encodingfix_unit.o $(CORE_TEST_OBJ)` |
| `Makefile:625` | `$(BUILD_ROOT)/wave15-stream-unit: tests/wave15_stream_unit.cc tests/atomic_survivors_unit.cc $(filter-out $(BUILD_ROOT)/src/main.o $(BUILD_ROOT)/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.h) $(wildcard src/*/*.inc)` |
| `Makefile:627` | `$(BUILD_ROOT)/wave15-stream-db0-unit: tests/wave15_stream_unit.cc tests/atomic_survivors_unit.cc $(filter-out $(BUILD_ROOT)/db0/src/main.o $(BUILD_ROOT)/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ)) $(wildcard src/*/*.h) $(wildcard src/*/*.inc)` |
| `Makefile:629` | `build/wave15-flip-eof-unit build/wave15-flip-eof-db0-unit: tests/wave15_flip_eof_unit.cc tests/core_concurrency_unit.cc $(CORE_TEST_OBJ) $(DB0_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile` |
| `Makefile:631` | `build/rlfix3-info-db0-unit: build/db0/tests/rlfix3_info_unit.o $(DB0_TEST_OBJ) $(CORE_TEST_OBJ)` |
| `Makefile:635` | `$(BUILD_ROOT)/aclkeys-unit: tests/aclkeys_unit.cc $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ))` |
| `Makefile:638` | `$(BUILD_ROOT)/aclkeys-wake-unit: tests/aclkeys_wake_unit.cc $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ))` |
| `Makefile:640` | `$(BUILD_ROOT)/aclkeys-wake-db0-unit: tests/aclkeys_wake_unit.cc $(filter-out $(BUILD_ROOT)/db0/src/main.o,$(DB0_OBJ)) $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ))` |
| `Makefile:645` | `build/storesize/multidb.cc: tests/storesize_checks.py src/cmd/multidb.cc` |
| `Makefile:654` | `build/storesize-unit: build/tests/storesize_unit.o build/db0/tests/storesize_unit.o build/storesize/multidb.o build/storesize/db0-multidb.o $(STORESIZE_CORE_OBJ)` |
| `Makefile:658` | `build/at15-unit: build/tests/at15_unit.o $(CORE_TEST_OBJ)` |
| `Makefile:661` | `build/at15-db0-unit: build/db0/tests/at15_unit.o $(DB0_TEST_OBJ) $(CORE_TEST_OBJ)` |
| `Makefile:665` | `build/execabort-watch-unit: build/tests/execabort_watch_unit.o $(CORE_TEST_OBJ)` |
| `Makefile:668` | `build/execabort-watch-db0-unit: build/db0/tests/execabort_watch_unit.o $(DB0_TEST_OBJ) $(CORE_TEST_OBJ)` |
| `Makefile:672` | `build/exbatch-unit: build/tests/exbatch_unit.o $(CORE_TEST_OBJ)` |
| `Makefile:675` | `build/exbatch-db0-unit: build/db0/tests/exbatch_unit.o $(DB0_TEST_OBJ) $(CORE_TEST_OBJ)` |
| `Makefile:680` | `build/exbatch/PRE/unit.o: tests/exbatch_unit.cc Makefile` |
| `Makefile:688` | `FLUSHFIX_UNIT_OBJ := build/tests/flushfix_unit.o build/db0/tests/flushfix_unit.o` |
| `Makefile:696` | `build/flushfix/pre-source/.emitted: tests/flushfix_checks.py` |
| `Makefile:698` | `python3 tests/flushfix_checks.py emit-pre build/flushfix/pre-source` |
| `Makefile:705` | `build/kvobj-header-unit: tests/kvobj_header_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:708` | `build/kvobj-header-db0-unit: tests/kvobj_header_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:712` | `build/flushfix-header-controls/%/unit: tests/kvobj_header_unit.cc tests/flushfix_checks.py $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:714` | `python3 tests/flushfix_checks.py emit-header $* build/flushfix-header-controls/$*/source` |
| `Makefile:724` | `build/tests/multidb_unit.o: src/cmd/xshard.cc tests/sortstore_checks.inc` |
| `Makefile:725` | `build/tests/multidb_unit.o build/db0/tests/multidb_db0_unit.o build/rehash-waits-unit: tests/probeadapter_checks.h` |
| `Makefile:726` | `build/multidb-unit: build/tests/multidb_unit.o build/tests/mdbstamp_checks.o build/db0/tests/multidb_db0_unit.o $(DB0_TEST_OBJ) $(filter-out build/src/cmd/xshard.o,$(CORE_TEST_OBJ))` |
| `Makefile:751` | `build/mdbqsbr-unit: build/mdbqsbr-asan/tests/mdbqsbr_unit.o $(MDBQSBR_ASAN_OBJ)` |
| `Makefile:754` | `build/mdbqsbr-unit-tsan: build/mdbqsbr-tsan/tests/mdbqsbr_unit.o $(MDBQSBR_TSAN_OBJ)` |
| `Makefile:758` | `build/mdbqsbr-asan/tests/core_concurrency_unit.o build/mdbqsbr-tsan/tests/core_concurrency_unit.o: tests/flipfix5_checks.inc tests/flipfix6_checks.inc tests/flipfix7_checks.inc tests/wave13_checks.inc tests/wave14_checks.inc` |
| `Makefile:759` | `build/core-concurrency-mdbqsbr-asan: build/mdbqsbr-asan/tests/core_concurrency_unit.o $(MDBQSBR_ASAN_OBJ)` |
| `Makefile:762` | `build/rltopo-unit: build/mdbqsbr-asan/tests/rltopo_unit.o $(MDBQSBR_ASAN_OBJ)` |
| `Makefile:765` | `build/core-concurrency-mdbqsbr-tsan: build/mdbqsbr-tsan/tests/core_concurrency_unit.o $(MDBQSBR_TSAN_OBJ)` |
| `Makefile:787` | `build/parkwake-unit: tests/parkwake_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:790` | `# LD_PRELOAD helper of the F3 diagnostic witness (tests/parkwake.py --case swapdb).` |
| `Makefile:791` | `build/parkwake-slowsync.so: tests/parkwake_slowsync.c Makefile` |
| `Makefile:795` | `build/multidb-boundary-unit: tests/multidb_boundary_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:798` | `build/multidb-cost-unit: tests/multidb_cost_unit.cc $(CORE_TEST_OBJ) $(DB0_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:801` | `build/multidb-cost-unit-multi: tests/multidb_cost_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:804` | `build/tomokv-multidb2-pad: build/tomokv tools/multidb2_artifacts.py tools/lbstall_artifacts.py` |
| `Makefile:806` | `python3 tools/multidb2_artifacts.py $< $@ > build/multidb2-pad.json` |
| `Makefile:807` | `build/tomokv-multidb-pad: build/tomokv tools/multidb_artifacts.py tools/lbstall_artifacts.py` |
| `Makefile:809` | `python3 tools/multidb_artifacts.py $< $@ > build/multidb-pad.json` |
| `Makefile:810` | `build/rehash-waits-unit: tests/rehash_waits_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:815` | `build/owner-prefetch-unit: tests/owner_prefetch_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:834` | `$(BUILD_ROOT)/publishfix-unit: tests/publishfix_unit.cc $(PUBLISHFIX_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:838` | `build/atomic-survivors-unit: tests/atomiccollapse_checks.inc tests/atomic_plain_checks.inc tests/txnorder_checks.inc` |
| `Makefile:839` | `build/atomic-survivors-unit: tests/atomic_survivors_unit.cc src/cmd/xshard.cc $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:841` | `$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. tests/atomic_survivors_unit.cc \` |
| `Makefile:845` | `build/txnorder-wake-unit: tests/txnorder_wake_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:848` | `TXNORDER_UNIT_DEPS := tests/atomic_survivors_unit.cc tests/atomiccollapse_checks.inc tests/atomic_plain_checks.inc tests/txnorder_checks.inc $(wildcard src/*/*.inc) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:849` | `build/txnorder-episodes: tests/txnorder_episodes.cc $(TXNORDER_UNIT_DEPS) $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ))` |
| `Makefile:851` | `build/at412-owner: tests/at412_owner.cc $(TXNORDER_UNIT_DEPS) $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ))` |
| `Makefile:853` | `build/txnorder-episodes-debug: tests/txnorder_episodes.cc $(TXNORDER_UNIT_DEPS) $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ))` |
| `Makefile:855` | `build/txnorder-watch-unit: tests/txnorder_watch_unit.cc $(TXNORDER_UNIT_DEPS) $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ))` |
| `Makefile:858` | `build/txnorder-watch-db0-unit: tests/txnorder_watch_unit.cc $(TXNORDER_UNIT_DEPS) $(filter-out build/db0/src/main.o build/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out build/src/main.o,$(OBJ))` |
| `Makefile:863` | `build/woundfix-windows/stamp: tools/woundfix_windows.py $(wildcard src/*/*.cc) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile` |
| `Makefile:864` | `python3 tools/woundfix_windows.py build/woundfix-windows` |
| `Makefile:865` | `build/txnorder-wound-unit: tests/txnorder_wound_window.cc $(TXNORDER_UNIT_DEPS) build/woundfix-windows/stamp $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ))` |
| `Makefile:867` | `build/txnorder-wound-db0-unit: tests/txnorder_wound_window.cc $(TXNORDER_UNIT_DEPS) build/woundfix-windows/stamp $(filter-out build/db0/src/main.o build/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out build/src/main.o,$(OBJ))` |
| `Makefile:870` | `build/txnorder-retry-unit: tests/txnorder_retry_unit.cc $(wildcard src/*/*.h) Makefile` |
| `Makefile:875` | `build/exec1s-unit: tests/exec1s_unit.cc $(TXNORDER_UNIT_DEPS) $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ))` |
| `Makefile:878` | `build/exec1s-word-tsan: tests/exec1s_word.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile` |
| `Makefile:881` | `build/txnorder-index-unit: tests/txnorder_index_unit.cc tests/txnorder_linear_oracle.inc $(TXNORDER_UNIT_DEPS) $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ))` |
| `Makefile:883` | `build/txnorder-index-db0-unit: tests/txnorder_index_unit.cc tests/txnorder_linear_oracle.inc $(TXNORDER_UNIT_DEPS) $(filter-out build/db0/src/main.o build/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out build/src/main.o,$(OBJ))` |
| `Makefile:887` | `build/txnorder-fifo-unit: tests/txnorder_fifo.cc tests/txnorder_episodes.cc $(TXNORDER_UNIT_DEPS) $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ))` |
| `Makefile:889` | `build/txnorder-fifo-db0-unit: tests/txnorder_fifo.cc tests/txnorder_episodes.cc $(TXNORDER_UNIT_DEPS) $(filter-out build/db0/src/main.o build/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out build/src/main.o,$(OBJ))` |
| `Makefile:892` | `build/txnorder-chain-unit: tests/txnorder_chain.cc tests/core_concurrency_unit.cc $(TXNORDER_UNIT_DEPS) $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ))` |
| `Makefile:894` | `build/txnorder-chain-db0-unit: tests/txnorder_chain.cc tests/core_concurrency_unit.cc $(TXNORDER_UNIT_DEPS) $(filter-out build/db0/src/main.o build/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out build/src/main.o,$(OBJ))` |
| `Makefile:899` | `build/owner-arena-unit: tests/owner_arena_unit.cc tests/at_recycle_checks.inc src/cmd/xshard.cc $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:918` | `build/l4prebuild-unit: tests/l4prebuild_unit.cc tests/owner_arena_unit.cc src/cmd/xshard.cc $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:926` | `build/tomokv-pad: $(BIN) tests/r7shadow_pad.py tools/lbstall_artifacts.py` |
| `Makefile:928` | `python3 tests/r7shadow_pad.py $< $@ --scope fifo --receipt $@.json` |
| `Makefile:945` | `build/l4prebuild-unit-tsan: tests/l4prebuild_unit.cc tests/owner_arena_unit.cc src/cmd/xshard.cc $(L4PREBUILD_TSAN_COMMON) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:957` | `build/l4prebuild-unit build/l4prebuild-unit-tsan: tests/at_recycle_checks.inc` |
| `Makefile:960` | `build/benchtxn: tools/benchtxn.cc Makefile` |
| `Makefile:962` | `$(CXX) $(CXXFLAGS) -I. tools/benchtxn.cc -o $@` |
| `Makefile:963` | `build/broaden-bench: tests/broaden_bench.cc Makefile` |
| `Makefile:965` | `$(CXX) $(CXXFLAGS) -I. tests/broaden_bench.cc -o $@` |
| `Makefile:969` | `TAILGEN_HEADERS := $(wildcard tools/tailgen/*.h)` |
| `Makefile:972` | `build/tailgen: tools/tailgen/main.cc $(TAILGEN_HEADERS) Makefile` |
| `Makefile:975` | `build/tailgen-unit: tests/tailgen_unit.cc $(TAILGEN_HEADERS) Makefile` |
| `Makefile:978` | `build/tailgen-unit-asan: tests/tailgen_unit.cc $(TAILGEN_HEADERS) Makefile` |
| `Makefile:981` | `build/tailgen-unit-tsan: tests/tailgen_unit.cc $(TAILGEN_HEADERS) Makefile` |
| `Makefile:999` | `NETCMD_TEST_SRC := tests/netcmd_unit.cc tests/netcmd_stream_unit.cc tests/netcmd_zset_unit.cc tests/netcmd_config_unit.cc` |
| `Makefile:1000` | `NETCMD_TEST_OBJ := $(NETCMD_TEST_SRC:tests/%.cc=build/tests/%.o)` |
| `Makefile:1001` | `build/tests/netcmd_unit.o build/db0/tests/netcmd_unit.o: tests/tlsserve_checks.inc tests/hexpire_oom_checks.inc tests/notify_order_checks.inc` |
| `Makefile:1003` | `build/tests/%.o: tests/%.cc tests/netcmd_unit.h $(wildcard src/*/*.h) $(wildcard src/core/*.inc) $(filter-out $(SERVER_ONLY_SRC),$(wildcard src/*/*.cc)) $(wildcard src/*/*.inc) Makefile` |
| `Makefile:1011` | `NETCMD_DB0_TEST_OBJ := $(NETCMD_TEST_SRC:tests/%.cc=build/db0/tests/%.o)` |
| `Makefile:1012` | `build/db0/tests/%.o: tests/%.cc tests/netcmd_unit.h $(wildcard src/*/*.h) $(wildcard src/core/*.inc) $(filter-out $(SERVER_ONLY_SRC),$(wildcard src/*/*.cc)) $(wildcard src/*/*.inc) Makefile` |
| `Makefile:1025` | `build/reorderscan-unit: tests/reorderscan_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1028` | `build/reorderscan-unit-asan: tests/reorderscan_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1032` | `build/reorder-unit: tests/reorder_unit.cc tests/reorder_batch_fixture.h $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1035` | `build/reorder-unit-asan: tests/reorder_unit.cc tests/reorder_batch_fixture.h $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1039` | `build/reorder-engagement-unit: tests/reorder_engagement_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1042` | `build/reorder-engagement-unit-db0: tests/reorder_engagement_unit.cc $(DB0_TEST_OBJ) $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1052` | `python3 tests/r7shadow_sync.py` |
| `Makefile:1053` | `python3 tests/r7shadow_sync_test.py` |
| `Makefile:1054` | `python3 tests/reorder_receipt.py build/reorder-engagement-unit build/reorder-checks/multi --engagement` |
| `Makefile:1055` | `python3 tests/reorder_receipt.py build/reorder-engagement-unit-db0 build/reorder-checks/db0 --engagement` |
| `Makefile:1056` | `python3 tests/reorder_receipt.py $(BIN) build/reorder-checks/identity` |
| `Makefile:1060` | `build/r7shadow3/reorder-witness.o: src/core/reorder.cc tests/r7shadow_witness.h $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile` |
| `Makefile:1062` | `$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_R7_WITNESS -include tests/r7shadow_witness.h -I. -c $< -o $@` |
| `Makefile:1063` | `build/r7shadow-split-unit: tests/r7shadow_split_unit.cc tests/reorder_engagement_unit.cc tests/r7shadow_witness.h build/r7shadow3/reorder-witness.o $(filter-out build/src/core/reorder.o,$(CORE_TEST_OBJ)) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1066` | `-include tests/r7shadow_witness.h -I. $< build/r7shadow3/reorder-witness.o \` |
| `Makefile:1068` | `build/r7shadow3/reorder-witness-db0.o: src/core/reorder.cc tests/r7shadow_witness.h $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile` |
| `Makefile:1071` | `-DTOMO_R7_WITNESS -include tests/r7shadow_witness.h -I. -c $< -o $@` |
| `Makefile:1072` | `build/r7shadow-split-unit-db0: tests/r7shadow_split_unit.cc tests/reorder_engagement_unit.cc tests/r7shadow_witness.h build/r7shadow3/reorder-witness-db0.o $(filter-out build/db0/src/core/reorder.o,$(DB0_TEST_OBJ)) $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1076` | `-include tests/r7shadow_witness.h -I. $< build/r7shadow3/reorder-witness-db0.o \` |
| `Makefile:1079` | `build/r7shadow-unit: tests/r7shadow_unit.cc tests/reorder_batch_fixture.h $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1082` | `build/r7shadow-unit-asan: tests/r7shadow_unit.cc tests/reorder_batch_fixture.h $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1087` | `build/r7shadow-instr: tests/r7shadow_instr.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1092` | `build/mdbqsbr-asan/tests/core_concurrency_unit.o build/mdbqsbr-tsan/tests/core_concurrency_unit.o: tests/signalacct_core_checks.inc tests/flip_close_checks.inc tests/flipsettle_checks.inc tests/flipreport_checks.inc tests/flipfix_checks.inc tests/slowlog_completion_checks.inc tests/wave5_dispatch_checks.inc` |
| `Makefile:1094` | `build/signalacct-core-unit: tests/core_concurrency_unit.cc tests/signalacct_core_checks.inc tests/flip_close_checks.inc tests/flipsettle_checks.inc tests/flipreport_checks.inc tests/flipfix_checks.inc tests/flipfix5_checks.inc tests/flipfix6_checks.inc tests/flipfix7_checks.inc tests/wave13_checks.inc tests/wave14_checks.inc tests/slowlog_completion_checks.inc tests/wave5_dispatch_checks.inc $(CORE_TEST_OBJ)` |
| `Makefile:1102` | `WB_RULE_CONTROL_DEPS := tests/wb_rule_checks.py tests/wb_rule_unit.cc tests/wb_rule_phase_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1104` | `build/wb-rule-unit: tests/wb_rule_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1107` | `build/wb-rule-db0-unit: tests/wb_rule_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1110` | `build/wb-rule-phase-unit: build/tests/wb_rule_phase_unit.o $(CORE_TEST_OBJ)` |
| `Makefile:1113` | `build/wb-rule-db0-phase-unit: build/db0/tests/wb_rule_phase_unit.o $(DB0_TEST_OBJ) $(CORE_TEST_OBJ)` |
| `Makefile:1118` | `python3 tests/wb_rule_checks.py emit $* build/wb-rule-controls/$*/source` |
| `Makefile:1119` | `$(CXX) $(CXXFLAGS) $(JEFLAGS) -Ibuild/wb-rule-controls/$*/source -I. tests/wb_rule_unit.cc -o $@ $(JELIBS)` |
| `Makefile:1122` | `python3 tests/wb_rule_checks.py emit $* build/wb-rule-controls/$*/source` |
| `Makefile:1123` | `$(CXX) $(CXXFLAGS) -O0 -g0 $(JEFLAGS) -Ibuild/wb-rule-controls/$*/source -I. tests/wb_rule_phase_unit.cc $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm $(WB_RULE_WRAP)` |
| `Makefile:1132` | `WB_RULE_COMPLETION_DEPS := tests/wb_rule_completion_unit.cc tests/wb_rule_checks.py $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1142` | `python3 tests/wb_rule_checks.py emit $* build/wb-rule-completion-controls/$*/source` |
| `Makefile:1146` | `$(CXX) $(CXXFLAGS) $(JEFLAGS) -Ibuild/wb-rule-completion-controls/$*/source -I. tests/wb_rule_completion_unit.cc -o $@ $(JELIBS)` |
| `Makefile:1149` | `$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -Ibuild/wb-rule-completion-controls/$*/source -I. tests/wb_rule_completion_unit.cc -o $@ $(JELIBS)` |
| `Makefile:1153` | `build/wbland-unit: tests/wbland_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1156` | `build/wbland-db0-unit: tests/wbland_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1159` | `build/wbland-clause-unit: tests/wbland_clause_unit.cc tests/wb_rule_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1162` | `build/wbland-db0-clause-unit: tests/wbland_clause_unit.cc tests/wb_rule_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1165` | `$(addprefix build/wbland-controls/,$(addsuffix /unit,$(WBLAND_CONTROLS))): build/wbland-controls/%/unit: tests/wbland_checks.py tests/wbland_unit.cc $(WB_RULE_CONTROL_DEPS)` |
| `Makefile:1167` | `python3 tests/wbland_checks.py emit $* build/wbland-controls/$*/source` |
| `Makefile:1168` | `$(CXX) $(CXXFLAGS) $(JEFLAGS) -Ibuild/wbland-controls/$*/source -I. tests/wbland_unit.cc -o $@ $(JELIBS)` |
| `Makefile:1169` | `$(addprefix build/wbland-clause-controls/,$(addsuffix /unit,$(WB_RULE_POLICY_CONTROLS))): build/wbland-clause-controls/%/unit: tests/wbland_clause_unit.cc $(WB_RULE_CONTROL_DEPS)` |
| `Makefile:1171` | `python3 tests/wb_rule_checks.py emit $* build/wbland-clause-controls/$*/source` |
| `Makefile:1172` | `$(CXX) $(CXXFLAGS) $(JEFLAGS) -Ibuild/wbland-clause-controls/$*/source -I. tests/wbland_clause_unit.cc -o $@ $(JELIBS)` |
| `Makefile:1180` | `build/mdbqsbr-asan/tests/core_concurrency_unit.o build/mdbqsbr-tsan/tests/core_concurrency_unit.o build/signalacct-core-unit: tests/lanefull_checks.inc` |
| `Makefile:1182` | `build/lanefull-db0-unit: tests/core_concurrency_unit.cc tests/lanefull_checks.inc $(DB0_TEST_OBJ) $(CORE_TEST_OBJ)` |
| `Makefile:1189` | `$(BUILD_ROOT)/tests/shutdown_unit.o: tests/shutdown_client_checks.inc` |
| `Makefile:1191` | `$(BUILD_ROOT)/shutdown-unit: $(BUILD_ROOT)/tests/shutdown_unit.o $(SHUTDOWN_UNIT_OBJ)` |
| `Makefile:1195` | `$(BUILD_ROOT)/shutsave-unit: $(BUILD_ROOT)/tests/shutsave_unit.o $(SHUTDOWN_UNIT_OBJ)` |
| `Makefile:1199` | `build/netcap-unit: build/tests/netcap_unit.o $(CORE_TEST_OBJ)` |
| `Makefile:1205` | `build/lbplanner-unit: tests/lbplanner_unit.cc tests/core_concurrency_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1208` | `build/lbplanner-unit-tsan: tests/lbplanner_unit.cc tests/core_concurrency_unit.cc $(MDBQSBR_TSAN_OBJ) Makefile` |
| `Makefile:1214` | `build/lbplanner-controls/%/source/src/core/io_loop.h: tools/lbplanner_controls.py $(SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc)` |
| `Makefile:1216` | `python3 tools/lbplanner_controls.py $* $@` |
| `Makefile:1217` | `$(foreach arm,$(LBPLANNER_TIMING_CONTROLS),build/lbplanner-controls/$(arm)/unit): build/lbplanner-controls/%/unit: build/lbplanner-controls/%/source/src/core/io_loop.h tests/lbplanner_unit.cc tests/core_concurrency_unit.cc $(CORE_TEST_OBJ) Makefile` |
| `Makefile:1219` | `$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_CORE_CONCURRENCY_TEST -Ibuild/lbplanner-controls/$*/source -I. tests/lbplanner_unit.cc $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm $(LBPLANNER_WRAP)` |
| `Makefile:1220` | `build/lbplanner-controls/%/lbplanner.cc: tools/lbplanner_controls.py src/core/lbplanner.cc` |
| `Makefile:1222` | `python3 tools/lbplanner_controls.py $* $@` |
| `Makefile:1226` | `build/lbplanner-controls/%/unit: build/lbplanner-controls/%/lbplanner.o tests/lbplanner_unit.cc tests/core_concurrency_unit.cc $(CORE_TEST_OBJ) Makefile` |
| `Makefile:1228` | `$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_CORE_CONCURRENCY_TEST -I. tests/lbplanner_unit.cc $< $(filter-out build/src/core/lbplanner.o,$(CORE_TEST_OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm $(LBPLANNER_WRAP)` |
| `Makefile:1229` | `build/lbplanner-unit-pad: build/lbplanner-unit tools/lbplanner_pad.py tools/rlfence_artifacts.py tools/lbstall_artifacts.py` |
| `Makefile:1231` | `python3 tools/lbplanner_pad.py $< $@ build/lbplanner-unit-pad-proof > build/lbplanner-unit-pad.log` |
| `Makefile:1232` | `build/tomokv-lbplanner-pad: build/tomokv tools/lbplanner_pad.py tools/rlfence_artifacts.py tools/lbstall_artifacts.py` |
| `Makefile:1234` | `python3 tools/lbplanner_pad.py $< $@ build/lbplanner-pad-proof > build/lbplanner-pad.log` |
| `Makefile:1235` | `build/lbosc3-unit-pad: build/lbplanner-unit tools/lbosc3_pad.py` |
| `Makefile:1237` | `python3 tools/lbosc3_pad.py $< $@ build/lbosc3/unit-pad-proof > build/lbosc3/unit-pad.log` |
| `Makefile:1243` | `build/lbplanner-trace: tools/lbplanner_trace.cc Makefile` |
| `Makefile:1248` | `$(BUILD_ROOT)/moverfix-unit: tests/moverfix_unit.cc src/cmd/xshard.cc $(filter-out $(BUILD_ROOT)/src/main.o $(BUILD_ROOT)/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1250` | `$(BUILD_ROOT)/moverfix-db0-unit: tests/moverfix_unit.cc src/cmd/xshard.cc $(filter-out $(BUILD_ROOT)/db0/src/main.o $(BUILD_ROOT)/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1255` | `$(GATEROWS_SCAN_UNITS): tests/reorderscan_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1262` | `build/gaterows5/reorder.o: src/core/reorder.cc tests/reorderscan_witness.h $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile` |
| `Makefile:1264` | `$(CXX) $(CXXFLAGS) $(JEFLAGS) -include tests/reorderscan_witness.h -I. -c $< -o $@` |
| `Makefile:1265` | `build/gaterows5/reorder-db0.o: src/core/reorder.cc tests/reorderscan_witness.h $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile` |
| `Makefile:1267` | `$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -include tests/reorderscan_witness.h -I. -c $< -o $@` |
| `Makefile:1268` | `build/reorderscan-paths: tests/reorderscan_paths.cc tests/reorder_engagement_unit.cc tests/reorderscan_witness.h build/gaterows5/reorder.o $(filter-out build/src/core/reorder.o,$(CORE_TEST_OBJ)) Makefile` |
| `Makefile:1269` | `$(CXX) $(CXXFLAGS) $(JEFLAGS) -include tests/reorderscan_witness.h -I. $< build/gaterows5/reorder.o $(filter-out build/src/core/reorder.o,$(CORE_TEST_OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm` |
| `Makefile:1270` | `build/reorderscan-db0-paths: tests/reorderscan_paths.cc tests/reorder_engagement_unit.cc tests/reorderscan_witness.h build/gaterows5/reorder-db0.o $(DB0_TEST_OBJ) $(CORE_TEST_OBJ) Makefile` |
| `Makefile:1271` | `$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -include tests/reorderscan_witness.h -I. $< build/gaterows5/reorder-db0.o $(filter-out build/db0/src/core/reorder.o,$(DB0_TEST_OBJ)) $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm` |
| `Makefile:1272` | `build/rlfence-portable-unit: tests/rlfence_unit.cc $(wildcard src/*/*.h) Makefile` |
| `Makefile:1274` | `build/slotless-unit build/slotless-drop-unit: tests/slotless_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile` |
| `Makefile:1276` | `build/layout-placement: tests/layout_placement.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) Makefile` |
| `tests/gate.sh:4` | `#   tests/gate.sh         iteration (default): ALL full correctness + the smoke ABBA subset.` |
| `tests/gate.sh:5` | `#   tests/gate.sh iteration   same default tier; the subset saves only regression cells.` |
| `tests/gate.sh:6` | `#   tests/gate.sh push    full correctness + ALL regression cells, required for push/release.` |
| `tests/gate.sh:7` | `#   tests/gate.sh release same as push. full is the legacy alias for the same complete gate.` |
| `tests/gate.sh:8` | `#   tests/gate.sh perf --dry-run  print the 64-cell p32 network-IO product and argv; no CPU work.` |
| `tests/gate.sh:11` | `#   tests/gate.sh quick   legacy correctness-only diagnostic: build (release+ASAN), footprint locks, boot` |
| `tests/gate.sh:19` | `#                         + NIC regression cells vs tests/gate_refs.txt (the NIC cells need the 25GbE` |
| `tests/gate.sh:73` | `exec tests/lottery_nightly.sh "$@"` |
| `tests/gate.sh:78` | `--dry-run) exec python3 tests/gateprod.py "$@";;` |
| `tests/gate.sh:79` | `-h&#124;--help&#124;--json) exec python3 tests/gateplan.py "$@";;` |
| `tests/gate.sh:86` | `exec python3 tests/abbagate.py "$@"` |
| `tests/gate.sh:88` | `exec python3 tests/gateplan.py "$@"` |
| `tests/gate.sh:99` | `PLAN=$(python3 tests/gateplan.py "$@") &#124;&#124; exit $?` |
| `tests/gate.sh:106` | `source tests/gate_subset.sh` |
| `tests/gate.sh:157` | `exec python3 tests/gateprod.py --run "${ABBA_ARGS[@]}"` |
| `tests/gate.sh:169` | `# a gate row must run the arm it exists for, never turn green by skipping it (tests/_lib.py).` |
| `tests/gate.sh:190` | `RECEIPT_START=$(python3 tests/gate_receipt.py begin --run-id "$ROW_RUN_ID" --tier "$GATE_PURPOSE" \` |
| `tests/gate.sh:209` | `python3 tests/gate_history.py prepare --history "$ROW_HISTORY" "${HISTORY_ARGS[@]}" \` |
| `tests/gate.sh:238` | `# 239 -> 240: the flip-controller model unit test (tests/flipctl_unit.cc) as a static build row;` |
| `tests/gate.sh:255` | `# 313 -> 321 quick, 326 -> 334 full: eviction accounting rows. tests/evict_battery.py had no gate` |
| `tests/gate.sh:414` | `python3 tests/gate_history.py watch --pid "$parent_pid" --parent-start "$parent_start" \` |
| `tests/gate.sh:491` | `python3 tests/gate_history.py signal-child --pid "$ROW_WATCHDOG" --start "$ROW_WATCHDOG_START" \` |
| `tests/gate.sh:533` | `budget=$(python3 tests/gate_history.py budget --correctness --plan "$ROW_PLAN" \` |
| `tests/gate.sh:602` | `python3 tests/gate_history.py record --history "$ROW_HISTORY" --run-id "$ROW_RUN_ID" \` |
| `tests/gate.sh:654` | `if python3 tests/gate_history.py report --history "$ROW_HISTORY" > "$RUN_DIR/verdict-history.txt"; then` |
| `tests/gate.sh:722` | `dependency_identity=$(python3 tests/gate_history.py dependency-label -- "$@") &#124;&#124; return 2` |
| `tests/gate.sh:782` | `owner_start=$(python3 tests/gate_history.py identity --pid "$owner_pid") &#124;&#124; return 1` |
| `tests/gate.sh:786` | `python3 tests/gate_history.py reap-tree --pid "$owner_pid" --parent-start "$owner_start" &#124;&#124; rc=$?` |
| `tests/gate.sh:906` | `shutdown_clean(){ python3 tests/shutdown_report.py "$SRVLOG" clean; }` |
| `tests/gate.sh:907` | `shutdown_present(){ python3 tests/shutdown_report.py "$SRVLOG" present; }` |
| `tests/gate.sh:908` | `shutdown_value(){ python3 tests/shutdown_report.py "$SRVLOG" get "$1"; }` |
| `tests/gate.sh:930` | `py tests/feature_atomic.py 127.0.0.1 "$PORT" "$AT" \` |
| `tests/gate.sh:931` | `python3 tests/$t.py 127.0.0.1 "$PORT" "${FEATURE_ARGS[@]}" >$TMPDIR/gate-$t-$AT.txt 2>&1 \` |
| `tests/gate.sh:983` | `py tests/feature_atomic.py 127.0.0.1 "$PORT" "$AT" \` |
| `tests/gate.sh:984` | `python3 tests/$t.py 127.0.0.1 "$PORT" "${FEATURE_ARGS[@]}" >$TMPDIR/gate-fusedarmed-$t-$AT.txt 2>&1 \` |
| `tests/gate.sh:1075` | `if tests/differ_gate.sh "$CANDIDATE_BINARY" "$PORT" "$((PORT+1))" "$CORES" "$GATE_RATIO"; then` |
| `tests/gate.sh:1090` | `py tests/evict_battery.py "$PORT" "$section" >"$TMPDIR/battery.log" 2>&1 \` |
| `tests/gate.sh:1098` | `python3 tests/flipctl.py --host 127.0.0.1 --port "$PORT" --stable-seconds 30 \` |
| `tests/gate.sh:1273` | `python3 tests/differ_fanout.py plan --run "${ROW_RUN_ID:-$RUN_DIR}" --output "$RUN_DIR/differ-plan.json" \` |
| `tests/gate.sh:1345` | `row=$(python3 tests/differ_fanout.py fold --plan "$RUN_DIR/differ-plan.json" --group "$group" \` |
| `tests/gate.sh:1460` | `pausable taskset -c "$CORES,$LOAD_CORES" tests/parbuild.sh \` |
| `tests/gate.sh:1464` | `tests/store_regression.cc src/cmd/t_hash.cc src/cmd/t_hash_ttl.cc src/cmd/hexpread.cc src/cmd/storesize.cc src/store/flush.cc` |
| `tests/gate.sh:1483` | `python3 tests/gate_receipt.py bind --start "$RECEIPT_START" --candidate "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:1502` | `pausable taskset -c "$BUILD_CORES" tests/parbuild.sh $ASAN "$PWD/build/gate-cache/obj-asan" \` |
| `tests/gate.sh:1520` | `pausable taskset -c "$BUILD_CORES" make -f Makefile -f tools/atomfix6.mk \` |
| `tests/gate.sh:1526` | `pausable taskset -c "$BUILD_CORES" tests/parbuild.sh build/atomfix6-park-tsan \` |
| `tests/gate.sh:1530` | `tests/atomfix6_park_unit.cc "${sources[@]}" >>"$TMPDIR/build.log" 2>&1 &#124;&#124; park_sanitized=0` |
| `tests/gate.sh:1546` | `pausable taskset -c "$BUILD_CORES" tests/parbuild.sh "build/atomfix6-park-db0-$flavor" \` |
| `tests/gate.sh:1550` | `tests/atomfix6_park_unit.cc "${sources[@]}" >>"$TMPDIR/build.log" 2>&1 &#124;&#124; park_db0_sanitized=0` |
| `tests/gate.sh:1575` | `make -f Makefile -f tools/atomfix6.mk -q build/atomfix6-park-asan &#124;&#124; park_ok=0` |
| `tests/gate.sh:1603` | `if py tests/atomfix6.py --binary "$CANDIDATE_BINARY" --cores "$CORES" --port "$PORT" \` |
| `tests/gate.sh:1619` | `if py tests/atomwake.py --binary "$CANDIDATE_BINARY" --cores "$CORES" --port "$PORT" \` |
| `tests/gate.sh:1636` | `if py tests/blockwake.py cancel --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:1642` | `if py tests/blockwake.py strand --binary "$CANDIDATE_BINARY" --cores "$CORES" --port "$PORT" \` |
| `tests/gate.sh:1659` | `# parkwake: park/wake witnesses of the IO and executor loops (tests/parkwake.py), one fresh` |
| `tests/gate.sh:1669` | `# A literal case map (as job_txnfix4/job_iowake): tests/gate_ledger_fixture.py reads these` |
| `tests/gate.sh:1682` | `if py tests/parkwake.py --binary "$CANDIDATE_BINARY" --case "$case" --cores "$CORES" \` |
| `tests/gate.sh:1702` | `py tests/flushfix3.py --binary "$CANDIDATE_BINARY" --databases "$databases" \` |
| `tests/gate.sh:1711` | `pausable taskset -c "$BUILD_CORES" make -f Makefile -f tools/flushfix3.mk -j"$BUILD_JOBS" \` |
| `tests/gate.sh:1716` | `make -f Makefile -f tools/flushfix3.mk -q "build/$target" && \` |
| `tests/gate.sh:1718` | `&& pausable taskset -c "$BUILD_CORES" python3 tools/flushfix3_work_reference.py \` |
| `tests/gate.sh:1737` | `py tests/flushfix2.py --case "$case" --databases "$databases" --command "$command" \` |
| `tests/gate.sh:1750` | `pausable taskset -c "$BUILD_CORES" make -f Makefile -f tools/flushfix2.mk -j"$BUILD_JOBS" \` |
| `tests/gate.sh:1754` | `make -f Makefile -f tools/flushfix2.mk -q "build/$target" && \` |
| `tests/gate.sh:1769` | `taskset -c "$CORES" python3 tests/tomo_assert_checks.py \` |
| `tests/gate.sh:1779` | `py tests/cfgfix.py --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:1790` | `py tests/cfgfix2.py --case "$1" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:1799` | `taskset -c "$CORES" python3 tests/docs_drift.py --self-test >"$TMPDIR/docs-drift.log" 2>&1 \` |
| `tests/gate.sh:1805` | `g++ -std=c++20 -O2 -I. tests/config_parser_test.cc -o $TMPDIR/tomokv-config-parser-test \` |
| `tests/gate.sh:1815` | `g++ -std=c++20 -O2 -I. tests/flipctl_unit.cc src/core/flipctl.cc -o $TMPDIR/tomokv-flipctl-unit \` |
| `tests/gate.sh:1819` | `pausable taskset -c "$BUILD_CORES" make -f tests/ctlfix.mk -j"$BUILD_JOBS" build/ctlfix-unit \` |
| `tests/gate.sh:1821` | `if make -f tests/ctlfix.mk -q build/ctlfix-unit; then` |
| `tests/gate.sh:1946` | `py tests/flipfix7.py --binary "$CANDIDATE_BINARY" --cores "$CORES" --port "$PORT" \` |
| `tests/gate.sh:1965` | `py tests/flushfix2_siblings.py --case live-flip --databases "$databases" \` |
| `tests/gate.sh:1971` | `py tests/flipfix6.py --binary "$CANDIDATE_BINARY" --cores "$CORES" --port "$PORT" \` |
| `tests/gate.sh:1974` | `py tests/flipfix6.py --binary "$CANDIDATE_BINARY" --cores "$CORES" --port "$PORT" \` |
| `tests/gate.sh:1994` | `py tests/flipfix5.py --case row --binary "$CANDIDATE_BINARY" --cores "$CORES" --port "$PORT" \` |
| `tests/gate.sh:2002` | `g++ -std=c++20 -O2 -pthread -I. tests/foreign_read_safety_test.cc \` |
| `tests/gate.sh:2019` | `g++ -std=c++20 -O2 -march=native -pthread -I. tests/read_local_write_ring_unit.cc \` |
| `tests/gate.sh:2040` | `&& py tests/read_local_lane.py --self-test mget-fence >>$TMPDIR/gate-rlfence-unit.txt 2>&1 \` |
| `tests/gate.sh:2061` | `py tests/shutdown_persist.py --binary "$CANDIDATE_BINARY" --cores "$CORES" \` |
| `tests/gate.sh:2074` | `if py tests/connreset_harness_test.py >"$TMPDIR/connreset-harness.log" 2>&1 \` |
| `tests/gate.sh:2075` | `&& { py tests/connreset_harness_test.py --negative-control >"$TMPDIR/connreset-negative.log" 2>&1; test "$?" -eq 1; } \` |
| `tests/gate.sh:2083` | `if unit_ready lbplanner-units && taskset -c "$CORES" python3 tests/lbplanner_checks.py \` |
| `tests/gate.sh:2096` | `if taskset -c "$CORES" python3 tests/perfex_checks.py "$check" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:2112` | `if py tests/perfex_checks.py prepare --clock-file "$TMPDIR/perfex-clock" &&` |
| `tests/gate.sh:2116` | `py tests/perfex_checks.py sampler --port "$PORT" --clock-file "$TMPDIR/perfex-clock" \` |
| `tests/gate.sh:2129` | `py tests/ntnew4_clock.py prepare --clock-file "$TMPDIR/ntnew4-clock" &&` |
| `tests/gate.sh:2134` | `py tests/ntnew4_clock.py check --port "$PORT" --mode "$mode" --server-log "$SRVLOG" \` |
| `tests/gate.sh:2157` | `if unit_ready persistfix-units && taskset -c "$CORES" python3 tests/persistfix_checks.py \` |
| `tests/gate.sh:2171` | `taskset -c "$CORES" python3 tests/exbatch_checks.py "$group" \` |
| `tests/gate.sh:2189` | `py tests/exbatch.py 127.0.0.1 "$PORT" >"$TMPDIR/exbatch-$mode.log" 2>&1; then` |
| `tests/gate.sh:2201` | `py tests/atomfix5_accounting.py --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:2210` | `py tests/atomfix5.py --case watch --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:2223` | `if py tests/clientfix.py --binary "$CANDIDATE_BINARY" --port "$PORT" \` |
| `tests/gate.sh:2259` | `py tests/tls.py --generate "$TMPDIR/compat2-certs" \` |
| `tests/gate.sh:2264` | `py "tests/$case.py" --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" \` |
| `tests/gate.sh:2279` | `py "tests/$battery.py" --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" \` |
| `tests/gate.sh:2315` | `if py tests/hexpread.py --binary "$CANDIDATE_BINARY" --port "$PORT" \` |
| `tests/gate.sh:2326` | `if py tests/objectpread.py --binary "$CANDIDATE_BINARY" --port "$PORT" \` |
| `tests/gate.sh:2386` | `if unit_ready wb-rule-units && taskset -c "$CORES" python3 tests/wb_rule_checks.py check "$group" \` |
| `tests/gate.sh:2400` | `if unit_ready wbland-units && taskset -c "$CORES" python3 tests/wbland_checks.py check "$group" \` |
| `tests/gate.sh:2412` | `py tests/r7shadow_sync.py >"$TMPDIR/sync.log" 2>&1 \` |
| `tests/gate.sh:2413` | `&& py tests/r7shadow_sync_test.py >>"$TMPDIR/sync.log" 2>&1 \` |
| `tests/gate.sh:2420` | `taskset -c "$CORES" python3 tests/reorder_receipt.py build/reorder-engagement-unit "$TMPDIR/multi" \` |
| `tests/gate.sh:2422` | `taskset -c "$CORES" python3 tests/reorder_receipt.py build/reorder-engagement-unit-db0 "$TMPDIR/db0" \` |
| `tests/gate.sh:2430` | `py tests/reorder_receipt.py "$CANDIDATE_BINARY" "$TMPDIR/receipt" >"$TMPDIR/receipt.log" 2>&1 \` |
| `tests/gate.sh:2436` | `py "tests/iofix_${feature}.py" --binary "$CANDIDATE_BINARY" --port "$PORT" \` |
| `tests/gate.sh:2451` | `py tests/inline_quoted.py 127.0.0.1 "$PORT" >"$TMPDIR/$mode-$engine.log" 2>&1 &#124;&#124; failed=1` |
| `tests/gate.sh:2485` | `unit_ready wbland-units && py tests/wb_policy.py --traces >"$TMPDIR/traces.log" 2>&1 &#124;&#124; rc=1` |
| `tests/gate.sh:2492` | `py tests/wb_policy.py --port "$PORT" --policy "$policy" --output "$TMPDIR/$mode-$policy.json" \` |
| `tests/gate.sh:2505` | `py tests/netio.py 127.0.0.1 "$PORT" "$engine" --coalesced-eof >"$TMPDIR/$engine.log" 2>&1; then :; else rc=1; fi` |
| `tests/gate.sh:2514` | `py tests/perfio.py stream --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" \` |
| `tests/gate.sh:2527` | `py tests/lb_stationary.py --port "$PORT" --output "$TMPDIR/hold.json" >"$TMPDIR/hold.log" 2>&1; then` |
| `tests/gate.sh:2536` | `if unit_ready splitlocal-unit && taskset -c "$CORES" python3 tests/splitlocal_checks.py check \` |
| `tests/gate.sh:2582` | `&& taskset -c "$CORES" python3 tools/aclkeys3_verify.py "$TMPDIR/aclkeys-wake" \` |
| `tests/gate.sh:2590` | `taskset -c "$BUILD_CORES" make -f Makefile -f tests/list_namespace.mk -j"$BUILD_JOBS" build/list-namespace-unit >"$log" 2>&1 \` |
| `tests/gate.sh:2605` | `if unit_ready flushfix-units && taskset -c "$CORES" python3 tests/flushfix_checks.py check "$FLUSHFIX_CASE" \` |
| `tests/gate.sh:2615` | `&& taskset -c "$CORES" python3 tests/mdbqsbr_checks.py build/mdbqsbr-unit \` |
| `tests/gate.sh:2622` | `&& python3 tests/multidb_serial.py --self-test >>"$TMPDIR/multidb-boundary-unit.log" 2>&1 \` |
| `tests/gate.sh:2628` | `unit_ready storesize-unit && taskset -c "$CORES" python3 tests/storesize_checks.py check-all build/storesize-unit \` |
| `tests/gate.sh:2737` | `py tests/iowake.py --case "$case" --binary "$CANDIDATE_BINARY" --cores "$CORES" --port "$PORT" \` |
| `tests/gate.sh:2747` | `py tests/netfix2.py --case "$case" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:2757` | `py tests/netfix_query_stats.py --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:2768` | `py tests/netfix_unix.py --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:2779` | `py tests/netfix_config.py --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:2790` | `py tests/netfix_tls.py --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:2801` | `py tests/netfix_idle_buffers.py --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:2825` | `if [ "$booted" = 1 ] && py tests/netcap.py 127.0.0.1 "$PORT" \` |
| `tests/gate.sh:2842` | `! py tests/infofix.py 127.0.0.1 "$PORT" --input-bytes-only \` |
| `tests/gate.sh:2857` | `py tests/crlffix.py --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:2899` | `if [ "$booted" != 1 ] &#124;&#124; ! py tests/respcompat.py 127.0.0.1 "$PORT" \` |
| `tests/gate.sh:2903` | `if [ "$booted" != 1 ] &#124;&#124; ! py tests/inline_protocol.py 127.0.0.1 "$PORT" \` |
| `tests/gate.sh:2960` | `py tests/respresume.py fragment 127.0.0.1 "$PORT" --oracle-port "$oracle_port" \` |
| `tests/gate.sh:2962` | `py tests/respresume.py cpu 127.0.0.1 "$PORT" --pid "$SRV" \` |
| `tests/gate.sh:2980` | `elif [ "$booted" = 1 ] && py tests/respresume.py "$kind" 127.0.0.1 "$PORT" --pid "$SRV" \` |
| `tests/gate.sh:2989` | `python3 tools/gen_acl_categories.py --redis-root "$REDIS74_ROOT" \` |
| `tests/gate.sh:3023` | `py tests/cmdmeta_coverage.py --redis-root "$REDIS74_ROOT" >$TMPDIR/gate-cmdmeta-coverage.txt 2>&1 \` |
| `tests/gate.sh:3024` | `&& py tools/gen_cmddocs.py --redis-root "$REDIS74_ROOT" --check \` |
| `tests/gate.sh:3062` | `if [ "$WAIT_BOOTED" = 1 ] && py tests/rehash_readonly.py 127.0.0.1 "$PORT" "$WAIT_MODE" "$WAIT_LOCAL" >"$WAIT_LOG" 2>&1; then` |
| `tests/gate.sh:3078` | `py tests/torture.py 127.0.0.1 $PORT >$TMPDIR/gate-tort.txt 2>&1 \` |
| `tests/gate.sh:3081` | `py tests/ryow.py 127.0.0.1 $PORT >$TMPDIR/gate-ryow.txt 2>&1 \` |
| `tests/gate.sh:3084` | `py tests/acl_categories.py 127.0.0.1 $PORT >$TMPDIR/gate-acl-categories.txt 2>&1 \` |
| `tests/gate.sh:3087` | `py tests/acl.py 127.0.0.1 $PORT - >$TMPDIR/gate-acl-nofile.txt 2>&1 \` |
| `tests/gate.sh:3093` | `py tests/spinprobe.py "$PORT" "$SRV" --idle-only >$TMPDIR/gate-idle-signals.txt 2>&1 \` |
| `tests/gate.sh:3099` | `shutdown_clean && py tests/lbsignals.py --shutdown "$SRVLOG" \` |
| `tests/gate.sh:3108` | `R=$(py tests/shutdown_report.py "$SRVLOG" fused-work) \` |
| `tests/gate.sh:3140` | `py tests/txn_movers.py 127.0.0.1 "$PORT" --only "$family" \` |
| `tests/gate.sh:3144` | `py tests/moverfix.py 127.0.0.1 "$PORT" --only "$family" \` |
| `tests/gate.sh:3172` | `py tests/atomic_torn.py 127.0.0.1 $PORT --release-build >$TMPDIR/gate-atomic-torn.txt 2>&1 \` |
| `tests/gate.sh:3175` | `py tests/atomic_ryow.py 127.0.0.1 $PORT "${ryow_args[@]}" >$TMPDIR/gate-atomic-ryow.txt 2>&1 \` |
| `tests/gate.sh:3178` | `py tests/atomic_hazards.py 127.0.0.1 $PORT >$TMPDIR/gate-atomic-hazards.txt 2>&1 \` |
| `tests/gate.sh:3190` | `py tests/txniso.py 127.0.0.1 "$PORT" --mode "$mode" >"$log" 2>&1 &#124;&#124; passed=0` |
| `tests/gate.sh:3198` | `&& py tests/txniso.py 127.0.0.1 "$PORT" --mode "$mode" --only V4 >>"$log" 2>&1 \` |
| `tests/gate.sh:3207` | `py tests/txngroup.py 127.0.0.1 "$PORT" --mode "$mode" >"$log" 2>&1 &#124;&#124; passed=0` |
| `tests/gate.sh:3213` | `&& py tests/txngroup.py 127.0.0.1 "$PORT" --mode "$mode" --only AOF >>"$log" 2>&1 \` |
| `tests/gate.sh:3235` | `py tests/feature_atomic.py 127.0.0.1 "$PORT" "$AT" python3 "tests/$t.py" 127.0.0.1 "$PORT" >"$TMPDIR/gate-fused-$t-$AT.txt" 2>&1 \` |
| `tests/gate.sh:3240` | `py tests/spinprobe.py "$PORT" "$SRV" >"$TMPDIR/gate-fused-spinprobe-$AT.txt" 2>&1 \` |
| `tests/gate.sh:3255` | `&& py tests/txn_nx.py 127.0.0.1 "$PORT" >"$TMPDIR/gate-fused-txn-nx-$AT.txt" 2>&1 \` |
| `tests/gate.sh:3272` | `py tests/rlfix5_gate_test.py >"$TMPDIR/fixture-controls.log" 2>&1 &#124;&#124; controls=0` |
| `tests/gate.sh:3280` | `taskset -c "$BUILD_CORES" make -j"$BUILD_JOBS" -f Makefile -f tools/rlfix5.mk build/rlfix5-scopes \` |
| `tests/gate.sh:3282` | `! make -f Makefile -f tools/rlfix5.mk -q build/rlfix5-scopes; then` |
| `tests/gate.sh:3304` | `py tests/rlfix5.py 127.0.0.1 "$oracle_port" --case "$case" --oracle \` |
| `tests/gate.sh:3326` | `py tests/rlfix5.py 127.0.0.1 "$PORT" --case "$case" \` |
| `tests/gate.sh:3355` | `py tests/rlfix3_info.py 127.0.0.1 "$PORT" --unit "$unit" --unit "$db0_unit" \` |
| `tests/gate.sh:3370` | `g++ -std=c++20 -O2 -march=native -pthread -I. tests/rlfix3_lifetime.cc \` |
| `tests/gate.sh:3381` | `py tests/rlfix3_zc.py 127.0.0.1 "$PORT" \` |
| `tests/gate.sh:3401` | `py tests/bplus.py 127.0.0.1 "$PORT" >$TMPDIR/gate-bplus.txt 2>&1 \` |
| `tests/gate.sh:3409` | `py tests/read_local_lane.py 127.0.0.1 "$PORT" >$TMPDIR/gate-read-local-lane.txt 2>&1 \` |
| `tests/gate.sh:3415` | `py tests/read_local_lane.py 127.0.0.1 "$PORT" --mget-fence \` |
| `tests/gate.sh:3422` | `py tests/rlfix.py 127.0.0.1 "$PORT" --case miss >$TMPDIR/gate-rlfix-miss-1s.txt 2>&1 \` |
| `tests/gate.sh:3428` | `py tests/rlfix.py 127.0.0.1 "$PORT" --case delete >$TMPDIR/gate-rlfix-del-1s.txt 2>&1 \` |
| `tests/gate.sh:3434` | `py tests/read_local_lane.py 127.0.0.1 "$PORT" --mget-fence \` |
| `tests/gate.sh:3441` | `py tests/rlfix.py 127.0.0.1 "$PORT" --case miss >$TMPDIR/gate-rlfix-miss-2s.txt 2>&1 \` |
| `tests/gate.sh:3445` | `py tests/rlfix.py 127.0.0.1 "$PORT" --case delete >$TMPDIR/gate-rlfix-del-2s.txt 2>&1 \` |
| `tests/gate.sh:3461` | `py tests/aclreply.py 127.0.0.1 "$PORT" >$TMPDIR/gate-aclreply-2s.txt 2>&1 \` |
| `tests/gate.sh:3467` | `py tests/aclreply.py 127.0.0.1 "$PORT" >$TMPDIR/gate-aclreply-1s.txt 2>&1 \` |
| `tests/gate.sh:3474` | `# ---- round-4 ACL reproductions: each row boots its own listener (tests/aclfix.py) -------------` |
| `tests/gate.sh:3487` | `py tests/aclfix.py --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" \` |
| `tests/gate.sh:3501` | `py tests/cmdfix2.py --case "$case" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:3509` | `py tests/datafix1_geo.py --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" \` |
| `tests/gate.sh:3517` | `py tests/datafix1_spop.py --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" \` |
| `tests/gate.sh:3525` | `py tests/datafix1_lists.py --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" \` |
| `tests/gate.sh:3533` | `py tests/datafix1_locale.py --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" \` |
| `tests/gate.sh:3541` | `py tests/datafix1_bitfield.py --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" \` |
| `tests/gate.sh:3549` | `py tests/datafix1_hexpire.py --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" \` |
| `tests/gate.sh:3557` | `py tests/datafix1_randscan.py --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" \` |
| `tests/gate.sh:3577` | `py tests/sort.py 127.0.0.1 "$PORT" 17 "$sort_mode" >$TMPDIR/gate-sort-$AT.txt 2>&1 \` |
| `tests/gate.sh:3602` | `py "tests/$test.py" 127.0.0.1 "$PORT" \` |
| `tests/gate.sh:3612` | `py "tests/$battery.py" 127.0.0.1 "$PORT" \` |
| `tests/gate.sh:3623` | `# txnfix4: round-5 CD5.3/CD5.4/CD5.5/CD5.6/TM5.1. tests/txnfix4.py boots every leg itself` |
| `tests/gate.sh:3639` | `{ taskset -c "$BUILD_CORES" make -f Makefile -f tests/txnfix4.mk -j"$BUILD_JOBS" \` |
| `tests/gate.sh:3644` | `py tests/txnfix4.py --binary "$CANDIDATE_BINARY" --oracle "$REDIS74_ROOT/src/redis-server" \` |
| `tests/gate.sh:3662` | `py tests/atomic_plain.py --self-test >$TMPDIR/gate-atomic-plain-$AT.txt 2>&1 \` |
| `tests/gate.sh:3666` | `&& py tests/atomic_plain.py 127.0.0.1 $PORT --atomic "$AT" \` |
| `tests/gate.sh:3707` | `if ! py tests/atomic_mode.py 127.0.0.1 "$PORT" "$AT" \` |
| `tests/gate.sh:3718` | `py tests/$t.py 127.0.0.1 $PORT "${FEATURE_ARGS[@]}" >$TMPDIR/gate-$t-$AT.txt 2>&1 &#124;&#124; battery_ok=0` |
| `tests/gate.sh:3720` | `py tests/scriptatomic_strict.py 127.0.0.1 "$PORT" >>"$TMPDIR/gate-$t-$AT.txt" 2>&1 &#124;&#124; battery_ok=0` |
| `tests/gate.sh:3765` | `&& py tests/txnorder.py 127.0.0.1 "$PORT" --mode "$mode" >"$log" 2>&1 &#124;&#124; passed=0` |
| `tests/gate.sh:3774` | `&& py tests/txnorder.py 127.0.0.1 "$PORT" --mode "$mode" --only d >>"$log" 2>&1 &#124;&#124; passed=0` |
| `tests/gate.sh:3793` | `py tests/execfair.py 127.0.0.1 "$PORT" --witness --seconds 1 \` |
| `tests/gate.sh:3795` | `py tests/wave6_exec.py "$PORT" >"$log-wave6.log" 2>&1 &#124;&#124; passed=0` |
| `tests/gate.sh:3796` | `py tests/wave7.py "$PORT" >"$log-wave7.log" 2>&1 &#124;&#124; passed=0` |
| `tests/gate.sh:3797` | `py tests/wave8.py "$PORT" >"$log-wave8.log" 2>&1 &#124;&#124; passed=0` |
| `tests/gate.sh:3798` | `py tests/wave8b.py "$PORT" >"$log-wave8b.log" 2>&1 &#124;&#124; passed=0` |
| `tests/gate.sh:3799` | `py tests/wave9.py "$PORT" >"$log-wave9.log" 2>&1 &#124;&#124; passed=0` |
| `tests/gate.sh:3800` | `py tests/wave10.py "$PORT" >"$log-wave10.log" 2>&1 &#124;&#124; passed=0` |
| `tests/gate.sh:3840` | `py tests/execfair.py 127.0.0.1 "$PORT" --fifo --seconds 60 --clients 64 \` |
| `tests/gate.sh:3896` | `py tests/exec1s.py "$PORT" "$scenario" "${wb_args[@]}" >"$log" 2>&1 &#124;&#124; passed=0` |
| `tests/gate.sh:3900` | `py tests/exec1s.py shutdown "$SRVLOG" "$mode" "$scenario" "${wb_args[@]}" >>"$log" 2>&1 &#124;&#124; passed=0` |
| `tests/gate.sh:4022` | `py tests/txnorder_watch.py 127.0.0.1 "$PORT" --databases "$databases" --only "$case_name" >>"$log" 2>&1 &#124;&#124; passed=0` |
| `tests/gate.sh:4024` | `py tests/txniso.py 127.0.0.1 "$PORT" --mode "$mode" --only W1,W2,S5 >>"$log" 2>&1 &#124;&#124; passed=0` |
| `tests/gate.sh:4052` | `py tests/at412.py --case "$case" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:4064` | `py tests/xscript.py 127.0.0.1 $PORT "$XS_MODE" >$TMPDIR/gate-xscript-$XS_MODE.txt 2>&1 \` |
| `tests/gate.sh:4088` | `if py tests/scriptfix.py "$case" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:4113` | `py tests/scriptfix3.py --root "$root" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:4137` | `py tests/expireindex.py 127.0.0.1 $PORT --release-build >$TMPDIR/gate-expireindex.txt 2>&1 \` |
| `tests/gate.sh:4146` | `py tests/borrow_registry.py 127.0.0.1 $PORT --release-build >$TMPDIR/gate-borrow.txt 2>&1 \` |
| `tests/gate.sh:4154` | `XDS_PORT=$PORT XDS_CPUS=$CORES XDS_BIN="$CANDIDATE_BINARY" bash tests/xshard_dispatch_scale.sh \` |
| `tests/gate.sh:4163` | `taskset -c "$BUILD_CORES" make -f Makefile -f tools/persistfmt.mk -j"$BUILD_JOBS" \` |
| `tests/gate.sh:4172` | `py tests/persistfmt.py "$case" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:4188` | `py tests/persistfmt.py aof-repeat --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:4204` | `py tests/dumprestore.py 127.0.0.1 $PORT prepare_restart \` |
| `tests/gate.sh:4213` | `py tests/dumprestore.py 127.0.0.1 $PORT verify_restart \` |
| `tests/gate.sh:4228` | `py tests/serverfix_lines.py --binary "$CANDIDATE_BINARY" --oracle "$REDIS74_ROOT/src/redis-server" \` |
| `tests/gate.sh:4237` | `py tests/serverfix_scalar.py --binary "$CANDIDATE_BINARY" --oracle "$REDIS74_ROOT/src/redis-server" \` |
| `tests/gate.sh:4248` | `py tests/latencyfix.py --case grammar --binary "$CANDIDATE_BINARY" --oracle "$REDIS74_ROOT/src/redis-server" \` |
| `tests/gate.sh:4256` | `py tests/latencyfix.py --case shape --binary "$CANDIDATE_BINARY" --oracle "$REDIS74_ROOT/src/redis-server" \` |
| `tests/gate.sh:4264` | `py tests/latencyfix.py --case off --binary "$CANDIDATE_BINARY" --oracle "$REDIS74_ROOT/src/redis-server" \` |
| `tests/gate.sh:4275` | `pausable taskset -c "$BUILD_CORES" make -j"$BUILD_JOBS" -f Makefile -f tools/wave8b.mk \` |
| `tests/gate.sh:4278` | `make -q -f Makefile -f tools/wave8b.mk "build/$unit" && \` |
| `tests/gate.sh:4287` | `py tests/serverfix_config.py --binary "$CANDIDATE_BINARY" --oracle "$REDIS74_ROOT/src/redis-server" \` |
| `tests/gate.sh:4296` | `py tests/serverfix_hello.py --binary "$CANDIDATE_BINARY" --oracle "$REDIS74_ROOT/src/redis-server" \` |
| `tests/gate.sh:4305` | `py tests/serverfix_waitaof.py --binary "$CANDIDATE_BINARY" --oracle "$REDIS74_ROOT/src/redis-server" \` |
| `tests/gate.sh:4314` | `py tests/serverfix_hll.py --binary "$CANDIDATE_BINARY" --oracle "$REDIS74_ROOT/src/redis-server" \` |
| `tests/gate.sh:4323` | `py tests/serverfix_slowlog.py --binary "$CANDIDATE_BINARY" --oracle "$REDIS74_ROOT/src/redis-server" \` |
| `tests/gate.sh:4332` | `py tests/serverfix_acllog.py --binary "$CANDIDATE_BINARY" --oracle "$REDIS74_ROOT/src/redis-server" \` |
| `tests/gate.sh:4342` | `py tests/authfix.py --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" --ratio "$GATE_RATIO" \` |
| `tests/gate.sh:4347` | `py tests/authfix.py --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" --ratio "$GATE_RATIO" \` |
| `tests/gate.sh:4352` | `py tests/authfix.py --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" --ratio "$GATE_RATIO" \` |
| `tests/gate.sh:4357` | `py tests/authfix.py --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" --ratio "$GATE_RATIO" \` |
| `tests/gate.sh:4362` | `py tests/authfix.py --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" --ratio "$GATE_RATIO" \` |
| `tests/gate.sh:4378` | `py tests/acl.py 127.0.0.1 "$PORT" "$acl_file" \` |
| `tests/gate.sh:4396` | `py tests/auth.py 127.0.0.1 $PORT gatepass >$TMPDIR/gate-auth.txt 2>&1 \` |
| `tests/gate.sh:4409` | `py tests/debug.py 127.0.0.1 $PORT >$TMPDIR/gate-debug.txt 2>&1 \` |
| `tests/gate.sh:4413` | `&& py tests/snap_typed_roundtrip.py $PORT build_save \` |
| `tests/gate.sh:4414` | `&& py tests/debug_load.py 127.0.0.1 "$PORT" RELOAD \` |
| `tests/gate.sh:4415` | `&& py tests/snap_typed_roundtrip.py $PORT verify; } \` |
| `tests/gate.sh:4431` | `py tests/persistfix2.py --case "$case" --binary "$binary" "${oracle[@]}" \` |
| `tests/gate.sh:4472` | `py tests/snap_cut_battery.py "$PORT" save \` |
| `tests/gate.sh:4482` | `py tests/snap_cut_battery.py "$PORT" verify_cut \` |
| `tests/gate.sh:4499` | `py tests/snap_cut_battery.py "$PORT" atomic_groups "$GROUP_DIR/groups.tomo" mset 5 \` |
| `tests/gate.sh:4512` | `py tests/snap_cut_battery.py "$PORT" atomic_groups "$GROUP_DIR/groups.tomo" exec 3 \` |
| `tests/gate.sh:4525` | `py tests/snap_typed_roundtrip.py "$PORT" build_save \` |
| `tests/gate.sh:4535` | `py tests/snap_typed_roundtrip.py "$PORT" verify \` |
| `tests/gate.sh:4547` | `py tests/snap_typed_race.py "$PORT" race "$RACE_DIR/race.tomo" \` |
| `tests/gate.sh:4559` | `py tests/snap_typed_race.py "$PORT" verify "$RACE_DIR/race.tomo.oracle.json" \` |
| `tests/gate.sh:4570` | `py tests/savefix.py --binary "$CANDIDATE_BINARY" --cores "$CORES" --port "$PORT" \` |
| `tests/gate.sh:4581` | `py tests/savefix.py --binary "$CANDIDATE_BINARY" --cores "$CORES" --port "$PORT" \` |
| `tests/gate.sh:4629` | `if [ "$booted" != 1 ] &#124;&#124; ! py "tests/datafix2_$script.py" 127.0.0.1 "$PORT" \` |
| `tests/gate.sh:4654` | `# snapfix: three directed rows for XS-SHUT-1 and SNAP-STORM-1. Each row runs tests/snapfix.py over` |
| `tests/gate.sh:4660` | `py tests/snapfix.py --case "$1" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:4668` | `py tests/wave15_rebind.py --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:4709` | `py tests/wave15_errorstats.py --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:4717` | `py tests/wave15_aof.py --case participants --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:4725` | `py tests/wave15_aof.py --case large --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:4793` | `if [ "$booted" != 1 ] &#124;&#124; ! py "tests/compat3_$script.py" 127.0.0.1 "$PORT" \` |
| `tests/gate.sh:4823` | `py tests/blockfix4.py --binary "$CANDIDATE_BINARY" --oracle "$REDIS74_ROOT/src/redis-server" \` |
| `tests/gate.sh:4844` | `# planted regressions. Build controls first with tools/blockfix2_controls.py.` |
| `tests/gate.sh:4857` | `py tools/blockfix2_controls.py check-directed --case "$case" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:4859` | `py tools/blockfix2_controls.py check-tcl --case "$case" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:4871` | `py tools/blockfix3_controls.py check-boundary --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:4885` | `py tests/wave15_flip_eof.py --binary "$CANDIDATE_BINARY" --oracle "$REDIS74_ROOT/src/redis-server" \` |
| `tests/gate.sh:4896` | `py tests/wave15_block_repeat.py --binary "$CANDIDATE_BINARY" --oracle "$REDIS74_ROOT/src/redis-server" \` |
| `tests/gate.sh:4925` | `py tools/blockfix2_controls.py check-refusal --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:5022` | `if ! taskset -c "$BUILD_CORES" python3 tools/trackfix_schedule.py "${schedule_args[@]}" \` |
| `tests/gate.sh:5060` | `if [ "$booted" != 1 ] &#124;&#124; ! py tests/trackfix.py 127.0.0.1 "$PORT" \` |
| `tests/gate.sh:5125` | `if [ "$booted" != 1 ] &#124;&#124; ! py tests/trackfix.py 127.0.0.1 "$PORT" \` |
| `tests/gate.sh:5197` | `if [ "$booted" != 1 ] &#124;&#124; ! py tests/notifycompat.py 127.0.0.1 "$PORT" \` |
| `tests/gate.sh:5231` | `if py tests/trackorder.py --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:5250` | `if ! taskset -c "$BUILD_CORES" python3 tools/notifycompat_schedule.py "${schedule_args[@]}" \` |
| `tests/gate.sh:5289` | `if [ "$booted" != 1 ] &#124;&#124; ! py tests/tracking_redirect.py 127.0.0.1 "$PORT" \` |
| `tests/gate.sh:5355` | `if [ "$booted" != 1 ] &#124;&#124; ! py tests/notify_order.py 127.0.0.1 "$PORT" \` |
| `tests/gate.sh:5421` | `if [ "$booted" != 1 ] &#124;&#124; ! py tests/notify_order.py 127.0.0.1 "$PORT" \` |
| `tests/gate.sh:5457` | `py tests/multi_exec.py 127.0.0.1 $PORT >$TMPDIR/gate-multi.txt 2>&1 \` |
| `tests/gate.sh:5460` | `py tests/blocking.py 127.0.0.1 $PORT >$TMPDIR/gate-blocking.txt 2>&1 \` |
| `tests/gate.sh:5463` | `py tests/pubsub.py 127.0.0.1 $PORT >$TMPDIR/gate-pubsub.txt 2>&1 \` |
| `tests/gate.sh:5466` | `py tests/lua_scripting.py 127.0.0.1 $PORT >$TMPDIR/gate-lua.txt 2>&1 \` |
| `tests/gate.sh:5471` | `py tests/notify.py 127.0.0.1 "$PORT" "$notify_atomic" \` |
| `tests/gate.sh:5493` | `py tests/flip.py 127.0.0.1 $PORT >$TMPDIR/gate-flip.txt 2>&1 \` |
| `tests/gate.sh:5496` | `py tests/flip_under_load.py 127.0.0.1 $PORT 20 >$TMPDIR/gate-flip-load.txt 2>&1 \` |
| `tests/gate.sh:5499` | `py tests/flip_ttl.py 127.0.0.1 $PORT >$TMPDIR/gate-flip-ttl.txt 2>&1 \` |
| `tests/gate.sh:5502` | `py tests/spinprobe.py $PORT "$SRV" >$TMPDIR/gate-spinprobe.txt 2>&1 \` |
| `tests/gate.sh:5515` | `py tests/flipfix.py "$FLIPFIX_CASE" --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" \` |
| `tests/gate.sh:5528` | `py tests/flipfix.py "$FLIPFIX_CASE" --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" \` |
| `tests/gate.sh:5539` | `py tests/perfio.py "$CASE" --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" \` |
| `tests/gate.sh:5553` | `py tests/fliplisten.py --binary "$CANDIDATE_BINARY" --port "$PORT" --cores "$CORES" \` |
| `tests/gate.sh:5657` | `python3 tests/pipeorder.py $PORT 400 >$TMPDIR/gate-pipeorder.txt 2>&1 \` |
| `tests/gate.sh:5675` | `py tests/knobs.py 127.0.0.1 "$PORT" "$NET_IO" "$AOF_ATOMIC" "$AOF_MODE" \` |
| `tests/gate.sh:5680` | `py tests/aof.py 127.0.0.1 $PORT populate "$AOF_STATE" >$TMPDIR/gate-aof-$NET_IO-$AOF_ATOMIC.txt 2>&1 \` |
| `tests/gate.sh:5681` | `&& py tests/aof.py 127.0.0.1 $PORT loadaof "$AOF_STATE" >>$TMPDIR/gate-aof-$NET_IO-$AOF_ATOMIC.txt 2>&1 \` |
| `tests/gate.sh:5686` | `AOF_PRE_MODEL=$(py tests/aof.py 127.0.0.1 $PORT snapshot "$AOF_DIR/dump.tomo" 2>>$TMPDIR/gate-aof-$NET_IO-$AOF_ATOMIC.txt)` |
| `tests/gate.sh:5700` | `py tests/aof.py 127.0.0.1 $PORT verify "$AOF_STATE" >>$TMPDIR/gate-aof-$NET_IO-$AOF_ATOMIC.txt 2>&1 \` |
| `tests/gate.sh:5705` | `AOF_POST_MODEL=$(py tests/aof.py 127.0.0.1 $PORT snapshot "$AOF_DIR/dump.tomo" 2>>$TMPDIR/gate-aof-$NET_IO-$AOF_ATOMIC.txt)` |
| `tests/gate.sh:5726` | `py tests/aof_torn_group.py 127.0.0.1 $PORT prepare "$AOF_GROUP_STATE" \` |
| `tests/gate.sh:5736` | `py tests/aof_torn_group.py 127.0.0.1 $PORT verify "$AOF_GROUP_STATE" \` |
| `tests/gate.sh:5738` | `&& py tests/aof_torn_group.py 127.0.0.1 $PORT scan \` |
| `tests/gate.sh:5755` | `py tests/aof_fsync.py 127.0.0.1 $PORT populate "$AOF_ALWAYS_STATE" always 512 \` |
| `tests/gate.sh:5766` | `py tests/aof_fsync.py 127.0.0.1 $PORT verify "$AOF_ALWAYS_STATE" always 512 \` |
| `tests/gate.sh:5781` | `if python3 tests/persistfix.py --binary "$CANDIDATE_BINARY" --mode "$PERSIST_MODE" \` |
| `tests/gate.sh:5798` | `py tests/savefix.py --binary "$CANDIDATE_BINARY" --cores "$CORES" --port "$PORT" \` |
| `tests/gate.sh:5816` | `py tests/aof_fsync.py 127.0.0.1 $PORT populate "$AOF_EVERY_STATE" everysec 512 \` |
| `tests/gate.sh:5833` | `py tests/aof_fsync.py 127.0.0.1 $PORT verify "$AOF_EVERY_STATE" everysec 512 \` |
| `tests/gate.sh:5845` | `py tests/aof_fsync.py 127.0.0.1 $PORT populate "$AOF_NO_DIR/state.json" no 128 \` |
| `tests/gate.sh:5853` | `NET_IO=$NET_IO GATE_PORT=$PORT GATE_CORES=$CORES tests/aof_rewrite_matrix.sh \` |
| `tests/gate.sh:5860` | `NET_IO=$NET_IO GATE_PORT=$PORT GATE_CORES=$CORES tests/aof_rewrite_trigger_matrix.sh \` |
| `tests/gate.sh:5894` | `if python3 tests/aoffix2.py "$AOFFIX_CASE" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:5907` | `if python3 tests/aoffix2.py latency --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:5922` | `if python3 tests/aoffix2.py "$AOFFIX_LARGE_CASE" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:5954` | `&& py tests/aof_frame_order_test.py >>$TMPDIR/gate-aof-frameorder-$AOF_FRAME_ATOMIC.txt 2>&1 \` |
| `tests/gate.sh:5955` | `&& py tests/aof_frame_order.py 127.0.0.1 $PORT "$AOF_FRAME_DIR/appendonlydir" --engine "${GATE_PROOF_NET_IO:-epoll}" \` |
| `tests/gate.sh:5978` | `py tests/aoforder.py --case "$AOFORDER_CASE" --binary "$AOFORDER_BIN" \` |
| `tests/gate.sh:5990` | `py tests/aoforder.py --case single --operation "$AOFORDER_OPERATION" \` |
| `tests/gate.sh:6009` | `py tests/tls.py --generate "$TLS_DIR" >$TMPDIR/gate-tls-generate.txt 2>&1 \` |
| `tests/gate.sh:6076` | `py tests/tls.py 127.0.0.1 "$TLS_PORT" "$TLS_DIR" yes --plain-port "$PORT" \` |
| `tests/gate.sh:6088` | `py tests/tls.py 127.0.0.1 "$TLS_PORT" "$TLS_DIR" optional --plain-port "$PORT" \` |
| `tests/gate.sh:6141` | `py tests/tls.py 127.0.0.1 "$TLS_PORT" "$TLS_DIR" no --plain-port "$PORT" --full \` |
| `tests/gate.sh:6169` | `! py tests/tls.py 127.0.0.1 "$TLS_PORT" "$TLS_DIR" no --plain-port "$PORT" \` |
| `tests/gate.sh:6196` | `! py tests/respcompat.py 127.0.0.1 "$PORT" --ntfix "$defect" --tls-port "$TLS_PORT" \` |
| `tests/gate.sh:6209` | `py tests/feature_gate.py --cell "$FEATURE_CELL" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:6220` | `if unit_ready gaterows5-units && taskset -c "$CORES" python3 tests/reorderscan_gate.py >"$TMPDIR/scan.log" 2>&1; then` |
| `tests/gate.sh:6227` | `&& py tests/rob_portable_control.py >>"$TMPDIR/portable.log" 2>&1; then` |
| `tests/gate.sh:6245` | `py tests/slotless.py 127.0.0.1 "$PORT" >"$TMPDIR/live-$mode-$engine.log" 2>&1 &#124;&#124; failed=1` |
| `tests/gate.sh:6258` | `py tests/wb_mixed.py --self-test >"$TMPDIR/controls-$mode-$engine.log" 2>&1 &#124;&#124; failed=1` |
| `tests/gate.sh:6265` | `py tests/wb_mixed.py --port "$PORT" --policy "$policy" --small "$small" --visits "$visits" \` |
| `tests/gate.sh:6281` | `py "tests/$suite.py" >"$TMPDIR/$suite.log" 2>&1 &#124;&#124; failed=1` |
| `tests/gate.sh:6303` | `py tests/abbagate.py --self-test > $TMPDIR/gate-abbagate-unit.txt 2>&1 &#124;&#124; controls_ok=0` |
| `tests/gate.sh:6304` | `py tests/gate_quiet.py --self-test >> $TMPDIR/gate-abbagate-unit.txt 2>&1 &#124;&#124; controls_ok=0` |
| `tests/gate.sh:6305` | `py tests/gate_measurements.py --self-test >> $TMPDIR/gate-abbagate-unit.txt 2>&1 &#124;&#124; controls_ok=0` |
| `tests/gate.sh:6306` | `py tests/gate_receipt.py --self-test >> $TMPDIR/gate-abbagate-unit.txt 2>&1 &#124;&#124; controls_ok=0` |
| `tests/gate.sh:6307` | `py tests/abba_instrument.py --self-test >> $TMPDIR/gate-abbagate-unit.txt 2>&1 &#124;&#124; controls_ok=0` |
| `tests/gate.sh:6308` | `py tests/background_environment_test.py >> $TMPDIR/gate-abbagate-unit.txt 2>&1 &#124;&#124; controls_ok=0` |
| `tests/gate.sh:6309` | `py tests/gate_history.py self-test >> $TMPDIR/gate-abbagate-unit.txt 2>&1 &#124;&#124; controls_ok=0` |
| `tests/gate.sh:6310` | `py tests/gate_process_test.py >> $TMPDIR/gate-abbagate-unit.txt 2>&1 &#124;&#124; controls_ok=0` |
| `tests/gate.sh:6311` | `py tests/gates_test.py >> $TMPDIR/gate-abbagate-unit.txt 2>&1 &#124;&#124; controls_ok=0` |
| `tests/gate.sh:6312` | `py tests/gate_subset_test.py >> $TMPDIR/gate-abbagate-unit.txt 2>&1 &#124;&#124; controls_ok=0` |
| `tests/gate.sh:6313` | `py tests/redis_tcl_test.py >> $TMPDIR/gate-abbagate-unit.txt 2>&1 &#124;&#124; controls_ok=0` |
| `tests/gate.sh:6314` | `py tests/wb_policy.py --self-test >> $TMPDIR/gate-abbagate-unit.txt 2>&1 &#124;&#124; controls_ok=0` |
| `tests/gate.sh:6315` | `py tests/lb_stationary.py --self-test >> $TMPDIR/gate-abbagate-unit.txt 2>&1 &#124;&#124; controls_ok=0` |
| `tests/gate.sh:6316` | `py tests/netio.py --self-test >> $TMPDIR/gate-abbagate-unit.txt 2>&1 &#124;&#124; controls_ok=0` |
| `tests/gate.sh:6317` | `py tests/gateprod.py --self-test >> $TMPDIR/gate-abbagate-unit.txt 2>&1 &#124;&#124; controls_ok=0` |
| `tests/gate.sh:6318` | `py tests/tailgen_stall.py --self-test >> $TMPDIR/gate-abbagate-unit.txt 2>&1 &#124;&#124; controls_ok=0` |
| `tests/gate.sh:6332` | `py tests/scriptfix4.py "$case" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:6347` | `! taskset -c "$BUILD_CORES" python3 tools/wave14_capture.py --output "$TMPDIR/scheduled" \` |
| `tests/gate.sh:6354` | `py tests/wave14_functions.py --binary "$scheduled" --oracle "$REDIS74_ROOT/src/redis-server" \` |
| `tests/gate.sh:6366` | `if py tests/wave14_order.py --binary "$CANDIDATE_BINARY" --oracle "$REDIS74_ROOT/src/redis-server" \` |
| `tests/gate.sh:6391` | `py tests/wave14_eof_data.py --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:6417` | `taskset -c "$CORES" python3 tools/rootcore_inbox.py --output "$TMPDIR/inbox" --kinds "${ROOTCORE_INBOX_KINDS:-client,transfer,task,fused,flush}" "${revision[@]}" \` |
| `tests/gate.sh:6422` | `py tests/rootcore.py --case "$root" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:6441` | `py tests/multifix.py 127.0.0.1 "$PORT" --case "$root" \` |
| `tests/gate.sh:6458` | `py tests/pubtrackfix.py --case "$root" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:6472` | `py tests/maxmemrace.py --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:6492` | `py tests/storefix5.py 127.0.0.1 "$PORT" all \` |
| `tests/gate.sh:6507` | `pausable taskset -c "$BUILD_CORES" make -j"$BUILD_JOBS" -f Makefile -f tools/infofix_latency.mk \` |
| `tests/gate.sh:6509` | `make -q -f Makefile -f tools/infofix_latency.mk build/infofix-latency-unit &#124;&#124; passed=0` |
| `tests/gate.sh:6527` | `local case=$1 label="rootcompat $1 vs Redis 7.4" runner=tests/rootcompat.py` |
| `tests/gate.sh:6531` | `taskset -c "$BUILD_CORES" cc -shared -fPIC tests/rootcompat_proc_fault.c -ldl \` |
| `tests/gate.sh:6534` | `case "$case" in xsnotify&#124;tracking) runner=tests/rootcompat_tracking/run.py;; esac` |
| `tests/gate.sh:6541` | `py tests/rootcompat.py --case xsexpiry --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:6553` | `py tests/infofix_compat.py --case "$case" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:6575` | `py tests/climonfix4.py --host 127.0.0.1 --port "$PORT" --case "$root" \` |
| `tests/gate.sh:6588` | `py tests/clientcompat.py --case "$case" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:6596` | `local mode passed=1 mode_passed label manifest=${GATE_TCL_MANIFEST:-tests/redis_tcl_passing.json}` |
| `tests/gate.sh:6614` | `py tests/redis_tcl.py --redis-root "$REDIS74_ROOT" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:6618` | `py tests/netfix2.py --case tcl-fds --mode "$mode" --binary "$CANDIDATE_BINARY" \` |
| `tests/gate.sh:6639` | `py tests/torture.py 127.0.0.1 $PORT >$TMPDIR/gate-tort-asan.txt 2>&1 \` |
| `tests/gate.sh:6642` | `py tests/ryow.py 127.0.0.1 $PORT >$TMPDIR/gate-ryow-asan.txt 2>&1 \` |
| `tests/gate.sh:6647` | `py tests/atomic_torn.py 127.0.0.1 $PORT >$TMPDIR/gate-atomic-torn-asan.txt 2>&1 \` |
| `tests/gate.sh:6657` | `py tests/atomic_ryow.py 127.0.0.1 $PORT --no-rate-assertions \` |
| `tests/gate.sh:6675` | `py tests/replyoff_xshard.py 127.0.0.1 $PORT >$TMPDIR/gate-replyoff-$RA.txt 2>&1 \` |
| `tests/gate.sh:6686` | `tools/quietcheck.sh "${GATE_CORES:-192-199}" "$PORT" 2>$TMPDIR/gate-quiet.err &#124;&#124; {` |
| `tests/gate.sh:6688` | `tools/quietcheck.sh "${GATE_CORES:-192-199}" "$PORT" 2>>$TMPDIR/gate-quiet.err &#124;&#124; {` |
| `tests/gate.sh:6707` | `py tests/zc.py 127.0.0.1 $PORT >$TMPDIR/gate-zc.txt 2>&1     && ok "zc borrow battery" &#124;&#124; bad "zc borrow battery" "see $TMPDIR/gate-zc.txt"` |
| `tests/gate.sh:6714` | `py tests/zc.py 127.0.0.1 $PORT >$TMPDIR/gate-zc-asan.txt 2>&1     && ok "zc borrow battery under ASAN" &#124;&#124; bad "zc borrow battery under ASAN"` |
| `tests/gate.sh:6736` | `pausable taskset -c "$BUILD_CORES" tests/parbuild.sh $RLDBG "$PWD/build/gate-cache/obj-rlcachedbg" \` |
| `tests/gate.sh:6753` | `py tests/rlcache_churn.py 127.0.0.1 $PORT "${GATE_RLCACHE_SECONDS:-25}" 48 \` |
| `tests/gate.sh:6790` | `py tests/globcase.py 127.0.0.1 "$PORT" 127.0.0.1 "$GLOBCASE_ORACLE_PORT" \` |
| `tests/gate.sh:6815` | `pausable taskset -c "$BUILD_CORES" tests/parbuild.sh "$CORE_TSAN" \` |
| `tests/gate.sh:6818` | `'-luring -pthread -lssl -lcrypto -lm' tests/core_concurrency_unit.cc "${sources[@]}" \` |
| `tests/gate.sh:6823` | `pausable taskset -c "$BUILD_CORES" tests/parbuild.sh "$WAITS_TSAN" \` |
| `tests/gate.sh:6826` | `'-pthread' tests/waits_unit.cc >"$TMPDIR/build.log" 2>&1 \` |
| `tests/gate.sh:6861` | `py tests/racefix.py counters --binary build/tomokv-tsan --mode "$mode" \` |
| `tests/gate.sh:6877` | `py tests/racefix.py climon --binary build/racefix-climon --mode "$mode" \` |
| `tests/gate.sh:6896` | `py tests/dbdefault.py --binary "$CANDIDATE_BINARY" --cores "$CORES" --port "$PORT" \` |
| `tests/gate.sh:6918` | `pausable taskset -c "$BUILD_CORES" make -f Makefile -f tools/blockfix_cost.mk \` |
| `tests/gate.sh:6920` | `make -f Makefile -f tools/blockfix_cost.mk -q build/blockfix-cost \` |
| `tests/gate.sh:6922` | `pausable taskset -c "$BUILD_CORES" make -f Makefile -f tools/blockfix2.mk \` |
| `tests/gate.sh:6925` | `make -f Makefile -f tools/blockfix2.mk -q "build/$target" && : > "$RUN_DIR/unit-ready/$target"` |
| `tests/gate.sh:6936` | `if unit_ready mdbqsbr-live-arms && py tests/mdbqsbr_live.py \` |
| `tests/gate.sh:6945` | `py tests/multidb.py 127.0.0.1 "$PORT" --read-local "$read_local" --persistence \` |
| `tests/gate.sh:6952` | `if [ "$booted" = 1 ] && py tests/multidb_serial.py 127.0.0.1 "$PORT" \` |
| `tests/gate.sh:6963` | `py tests/aclkeys_wake_state.py 127.0.0.1 "$PORT" \` |
| `tests/gate.sh:7284` | `# tests/evict_battery.py needs one FRESH boot per section (it sets maxmemory itself and has no` |
| `tests/gate.sh:7469` | `py tests/tailgen_stall.py --port "$PORT" --cores "$LOAD_CORES" \` |
| `tests/gate.sh:7493` | `# Rationale and the full contract: the module docstring in tests/abbagate.py.` |
| `tests/gate.sh:7549` | `ABBA_HISTORY_CONTEXT=$(python3 tests/gate_history.py abba-context -- "${ABBA_ARGS[@]}") &#124;&#124; exit 2` |
| `tests/gate.sh:7556` | `python3 tests/gateprod.py --run "${ABBA_ARGS[@]}" --output "$ABBA_OUTPUT" &` |
| `tests/gate.sh:7569` | `python3 tests/gate_receipt.py resolution-summary "$ABBA_OUTPUT/results.json" &#124;&#124; :` |
| `tests/gate.sh:7604` | `if [ ! -f tests/niclib.sh ]; then` |
| `tests/gate.sh:7605` | `NIC_NOT_RUN='missing tests/niclib.sh'` |
| `tests/gate.sh:7612` | `elif [ ! -f tests/gate_refs.txt ]; then` |
| `tests/gate.sh:7613` | `NIC_NOT_RUN='missing tests/gate_refs.txt'` |
| `tests/gate.sh:7619` | `REF_KERNEL=$(sed -n 's/^# *kernel: *//p' tests/gate_refs.txt &#124; head -1)` |
| `tests/gate.sh:7627` | `. tests/niclib.sh` |
| `tests/gate.sh:7646` | `python3 - "$PERF_SERVER_CORES" "$PERF_LOAD_CORES" tests/gate_refs.txt \` |
| `tests/gate.sh:7736` | `python3 tests/gate_receipt.py coordinator "${RECEIPT_COORDINATOR_ARGS[@]}" \` |
| `tests/gate.sh:7743` | `python3 tests/gate_receipt.py finish --start "$RECEIPT_START" --gate-result "$RUN_DIR/gate-result.json" \` |

## readability-a1b

Follow-up on `a527de5d58`, on the same branch without rewriting history or pushing. The maintainer's landing run `build/gate-run.4Nvzey` had 1,230 rows and three failures. A1b restores the two missing test entry points and a further transitive import, and changes perfio's completion witness to the selected socket's destination registration. Production code and EXPECT constants are unchanged.

### Corrected caller analysis

`docs/readability-a1b/caller_inventory.py` scans the current worktree, treating archive entries at their original logical paths. Every retained test/tool entry point and Makefile is a root; imports and file dependencies are followed through helper scripts under docs as well. Python AST analysis includes imports inside functions, aliases, `from` imports, importlib, `__import__`, runpy, sys.path insertion/slicing, finite assignments/loops, Path joins, f-strings and subprocess command strings. Shell/Make analysis expands both `$name` and `${name}` and Make variables from assignments and finite case lists. Each argv word is expanded independently, so a large unrelated output-path expansion cannot erase the executable name.

Unresolved module imports conservatively retain candidates; unresolved executable script paths require explicit review. The current frontier has one generated temporary script in `tests/scriptatomic_strict.py`, derived from the live `tests/scriptatomic.py`; its producer and source hash are recorded. This is a bounded repository analysis with a reviewed frontier, not a claim of decidability for arbitrary Python or shell. Fourteen fixture tests cover the caller forms, transitive imports, comment exclusion and unresolved-input handling. The independent full-stem sweep finds all 20 supplied names, and the validation script requires their classifications and every restored/remaining archive digest.

The supplied list's claimed imports are not present at this HEAD. Two of the 20 are real calls; the remaining 18 are provenance comments, labels, external binary receipts or a C++ filename. The additional live dependency is `tools/wave10.py` → `docs/wave9/budgets.py` → `tools/ccfix_audit.py`. All three restores use `git mv` and retain their exact original bytes. There are no additional gate consumers of the third file; its caller is a manual budget phase.

| Supplied path | Reviewed disposition |
|---|---|
| `tests/at412_diagnostics.py` | Docstring and comment in tests/at412.py; no import or execution. |
| `tests/cd13b_window_test.py` | CALL: witness_contracts expands tests/$suite.py. |
| `tests/slowlog_identity.py` | CALL: bugs5 expands tests/$test.py in all eight mode/engine/atomic legs. |
| `tools/eoffix.py` | Gate row label names the eoffix lane; the job executes a supplied native binary. |
| `tools/eoffix_aof.py` | eoffix_aof is a shell job name, not a Python call; its native binary comes from EOFFIX_AOF_DIRECTORY. |
| `tools/wave13.py` | Gate greps ARMED wave13 receipt text; Makefile cites a docs/wave13 budget receipt. |
| `tools/wave15.py` | Gate row labels and inventory enum/flag/key names; no import or Python invocation. |
| `tools/wave11.py` | Comment in climonfix4.py and docstring in flipfix5.py; no imports. |
| `tools/exec1sd.py` | wave10.py dictionary key identifies an external frozen binary; no import. |
| `tools/blockfix4_scope.py` | rlfix5_proof.py selects tests/blockfix4_scope.cc, a distinct C++ fixture. |
| `tools/exec1s_pad_scope.py` | Comment in exec1s_scope.py only. |
| `tests/cd13b_audit.py` | Makefile provenance comment only. |
| `tools/aclkeys4_audit.py` | Makefile provenance comment only. |
| `tools/at412_budget.py` | Makefile provenance comment only. |
| `tools/infofields_artifacts.py` | Makefile provenance comment only. |
| `tools/psfix_artifacts.py` | Makefile provenance comment only. |
| `tools/rltopo_artifacts.py` | Makefile provenance comment only. |
| `tools/iowake_budgets.py` | Makefile provenance comment only. |
| `tools/mset8fix_budgets.py` | Makefile provenance comment only. |
| `tools/wave16_budgets.py` | Makefile provenance comment only. |

The complete line-level evidence is [caller-audit.json](docs/readability-a1b/evidence/caller-audit.json); the full graph is [caller-graph.json.gz](docs/readability-a1b/evidence/caller-graph.json.gz). The corrected archive manifest contains 465 entries. No gate row was added or removed: `EXPECT_QUICK=1212`, `EXPECT_FULL=1229`, and the 1,230-label fixture remain unchanged, including the existing quick-exit placement.

### Perfio and proof status

The destination can migrate during owner-observation retries. The accepted DEBUG CLIENT-LB request is pipelined with DEBUG IO-THREAD, and its socket registration is sampled again, so the expected destination belongs to the accepted request. The completion poll requires the selected inode's registrations to equal `[destination_ep]` within the existing deadline measured before arming. It does not send commands to that idle socket. A global move count is supplementary and may increase by more than one when other clients move. The post-move audit, selected IO-thread equality, zero stale/duplicate registrations, and exact events-per-command checks remain mandatory. Five serverless controls cover unrelated moves, missing/duplicate registration and a destination migration during observation retries. The latter runs the real epoll_lb orchestration with a deterministic transport. Removing each of the three required caller edges independently makes the inventory validator fail.

Proof is restricted to CPUs 64–95, ports 25100–25199 and `LC_ALL=C`. The initial gate selection (`witness_contracts bugs5 flip`) passed 14/14 rows, including all eight slowlog-identity legs and their legacy controls. Gate selftests passed 83 tests; label-fixture tests passed 12. The final repetition/build/binary receipts follow below.

The two pre-existing modified RL5 build receipts were preserved verbatim under `docs/readability-a1b/evidence/landing-build/`; their original tracked locations were restored to HEAD so this follow-up does not replace historical lane evidence.

### Completed A1b proof

| Check | Result |
|---|---|
| Gate jobs `witness_contracts bugs5 flip` | **14/14 rows**, zero FAIL; includes release build, all eight slowlog-identity legs and their eight legacy controls, and both perfio rows |
| `cd13b_window_test.py` through `witness_contracts` | **8 tests, OK** |
| Final `flip` job repeated 20 times | **20/20 epoll-lb passes; 200/200 total rows**, zero FAIL, one unchanged perfio source hash |
| `python3 tests/gates_test.py` | **83 tests, OK** (also runs its nested identity controls) |
| Label-fixture unittest | **12 tests, OK** after comment updates |
| Caller-form fixtures / removed-edge controls | **14 tests, OK** / **3 of 3 deleted caller edges rejected** |
| Perfio deterministic controls | **5 tests, OK**, including a destination that moves during owner-observation retries |
| Restored manual helper | Import chain `wave10 → docs/wave9/budgets → ccfix_audit` and `ccfix_audit --help` pass |
| `make all` plus all 61 primary `job_production_units` targets | Build succeeds; **62/62** `make -q` checks pass |
| Supplemental `job_production_units` targets | Both MDB witness builds, blockfix cost + digest, and both blockfix2 namespaces build; concrete freshness checks pass |
| Default `make -q` | Exit **0**, with INFO inputs pinned |
| `/home/user/Projects/calib/binary-neutral.sh` vs retained `5c36312818` PRE | **IDENTICAL (11,167,504 bytes after stripping)** |

The binary proof uses GCC 13.3.0 and `TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0`. PRE's raw SHA-256 matches A1's frozen receipt. The sole A1b production-source edit is an archive-path comment in `src/core/wb_rule.h`; its raw preprocessing tokens are unchanged. Makefile edits are comments only. No performance measurement or PAD arm is requested.

The first 20-run trial had **19 passes and one timeout** (`gate-run.wsvpFQ`); it established that waiting for the selected inode alone still encountered stale arming state. A diagnostic trial retained another timeout (`gate-run.vtcuXU`): the accepted request followed a destination connection that migrated from IO 1 to IO 2 during 89 observation attempts; the selected connection was on IO 2 at timeout, while the old expected epoll was still IO 1's. This is why the accepted request and its destination IO witness are now pipelined and the destination registration is resampled. That trial spans the fix and is retained as intermediate evidence, not counted as final proof. The final, separate 20-run cohort uses the same final perfio hash in every run and has zero failures. Every run retains selected-inode equality, selected IO equality, zero stale/duplicate registrations, and exactly one epoll event per command. The deadline remains 35 seconds; no failed window is skipped.

[Gate ledgers, resource arguments and per-run selected-client witnesses](docs/readability-a1b/evidence/gate-runs.json), [final gate transcripts](docs/readability-a1b/evidence/final-gate.log), [earlier timeout evidence](docs/readability-a1b/evidence/earlier-failures/), [build/freshness targets](docs/readability-a1b/evidence/builds.json), [binary inputs and hashes](docs/readability-a1b/evidence/binary.json), and [IDENTICAL receipt](docs/readability-a1b/evidence/binary-neutral.log). Raw compiler logs and full gate directories remain under `build/readability-a1b/` and the recorded `build/gate-run.*` paths; no large binaries/logs are committed.

Reproduction (individual correctness jobs only):

```sh
export LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0
GATE_TEST_PORT=25199 GATE_PROOF_NO_RATES=1 GATE_ONLY_JOBS='witness_contracts bugs5 flip' \
  taskset -c 64-79 tests/gate.sh iteration --server-cores 64-71 \
  --load-cores 72-79 --load-smt '' --ports 25100-25119
taskset -c 64-79 python3 docs/readability-a1b/repeat_flip.py
GATE_TEST_PORT=25199 taskset -c 80-95 python3 tests/gates_test.py
taskset -c 80-95 python3 -m unittest discover -s tests -p gate_ledger_fixture.py
taskset -c 80-95 python3 docs/readability-a1b/build_proof.py
taskset -c 80-95 /home/user/Projects/calib/binary-neutral.sh \
  build/readability-a1/PRE build/tomokv
taskset -c 80-95 python3 docs/readability-a1b/caller_inventory_test.py
taskset -c 80-95 python3 docs/readability-a1b/caller_inventory.py
taskset -c 80-95 python3 docs/readability-a1b/prove_inventory.py
taskset -c 80-95 python3 docs/readability-a1b/perfio_wait_test.py
```

All requested individual gate jobs ran. No full iteration, benchmark, ABBA, NIC measurement, push or merge was run. The historical manual budget campaign behind `wave10.py` was not replayed; its restored dependency was imported directly, and the caller graph has no path to it from a gate job or Makefile target. Gate script, expected counts and label fixture are byte-for-byte unchanged from `a527de5d58`.
