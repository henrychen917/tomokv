# Finished lane proofs

These 465 files are byte-for-byte copies from `5c3631281`. The readability-a1b caller audit restored three files missed by A1: `tests/cd13b_window_test.py`, `tests/slowlog_identity.py`, and `tools/ccfix_audit.py`. The remaining files are outside the reviewed gate/build/live-tool closure. See `docs/readability-a1b/evidence/caller-audit.json` and the `readability-a1b` section of `MEASURE-REQUEST-readability-a1.md` for the import, dynamic-name and provenance classifications.

Paths below preserve the original `tools/` or `tests/` prefix. These are historical evidence, not current build entry points. To replay a historical lane, use its original commit and original paths; relative imports and ROOT assumptions are intentionally unchanged. Gate rows, fixture labels, and expected counts are unchanged.

| Original tool | What it proved or built |
|---|---|
| `tests/abba_calibration.py` | Unwired calibration prototype: two training ABBA blocks and one independent holdout. |
| `tests/abba_saturation_controls.py` | Prepare loaded probes or capture idle controls; the campaign stays UNVALIDATED. |
| `tests/at412_diagnostics.py` | Non-gate reproductions for SNAP-STORM-1, XS-SHUT-1 and XS-NOTIFY-1. |
| `tests/atomiccollapse_controls.py` | Generate/build/run serverless collapse controls; never launches tomokv. |
| `tests/cd13b_audit.py` | CD13b full-body byte audit. Only verified address fields are normalized. |
| `tests/climonfix_artifacts.py` | Offline/serverless SV1/SV2 controls and type-A layout twin. Never starts a server. |
| `tests/flip_close_controls.py` | Serverless FLIP close/drain regression and an exact removal negative control. |
| `tests/mdbstamp_controls.py` | Build/run deterministic serverless negative controls, never a server or timer. |
| `tests/netfix2_audit.py` | Run the auditors' owned tests with confined resources and POST expectations. |
| `tests/respcompat_audit.py` | Offline RESP lane byte/instruction evidence; never executes either server. |
| `tests/respcompat_replay.py` | Replay the unchanged wire inventory through the production parser, without sockets. |
| `tests/signalacct_byte_checks.py` | Serverless positive/negative controls for the existing strict ELF body checker. |
| `tests/signalacct_controls.py` | Serverless accounting/parser negative controls. Run pinned to CPUs 112-127. |
| `tests/signalacct_core_controls.py` | Serverless negative controls of the actual model/fold/picker; never starts IO. |
| `tests/signalacct_source_checks.py` | Serverless IO scope/idle/R7 source proofs against the frozen launch reference. |
| `tests/sortstore_controls.py` | Build the fix-removed unit/server controls; only --run-units executes proofs. |
| `tests/txnfix_audit/t03_mover_replay.py` | T03: atomic-ON cross-shard movers replay phase-one images. While the mover's group is installed |
| `tools/aclkeys3_audit.py` | Account for every PRE/POST object body and type layout without running a server. |
| `tools/aclkeys3_budget.py` | Compile/byte-audit only the two changed TUs; never starts a listener or workload. |
| `tools/aclkeys3_controls.py` | Build throwaway, single-mechanism negative controls; never runs them or a server. |
| `tools/aclkeys3_link_audit.py` | Prove linker selection for changed/new weak copies; no opcode masking or execution. |
| `tools/aclkeys3_text_audit.py` | Grep tests for changed literal text and repository encodings; no server execution. |
| `tools/aclkeys4_audit.py` | Inventory mainline PRE, merged aclkeys3, and POST without executing a server. |
| `tools/aclkeys4_budget.py` | Compile only a changed TU and reject every unrelated emitted-body difference. |
| `tools/aclkeys_artifacts.py` | Offline ACL lane evidence and inverse text-size control; never runs a server. |
| `tools/aoffix2_pad.py` | PAD A: PRE behavior, POST AOF-only layouts and total linked .text size. |
| `tools/aoffix2_proof.py` | Focused aoffix2 proof runner; no gate or throughput benchmark invocation. |
| `tools/aoffix2_report.py` | Summarize recorded AOF proof timings; never starts a server. |
| `tools/aoffix_artifacts.py` | Build a kind-A P15 control offline: PRE probes in the exact POST ELF layout. |
| `tools/assert_artifacts.py` | Audit stable-assertion ELF changes and make an offline PAD-A behaviour twin. |
| `tools/at412_artifacts.py` | AT4.12 offline identity, bounded instruction counts and PAD-A artifacts. |
| `tools/at412_budget.py` | AT4.12 compile-only per-unit IPA budget trials (no server, no workload, no rates). |
| `tools/at412c_proof.py` | Run authorized correctness jobs only, on at412c's CPU and port allocation. |
| `tools/at412c_record.py` | Archive completed native correctness jobs, including every failed attempt. |
| `tools/at_recycle_analyze.py` | Strict OFFLINE window analyzer. Missing fields are errors; never drives a server. |
| `tools/at_recycle_artifacts.py` | Build-only source mirrors and audited fixed-width kind-A ELF patch; never starts a server. |
| `tools/atomfix5_arms.py` | Offline PAD-A and isolated broken-writer test control; never patch POST in place. |
| `tools/atomfix6_archive.py` | Losslessly archive large evidence files after their gate job has completed. |
| `tools/atomfix6_audit.py` | Run a copied round-5 correctness detector inside this lane's CPU/port limits. |
| `tools/atomfix6_budget.py` | Compile-only xshard budget trials to preserve the atomic-off instruction path. |
| `tools/atomfix6_compress.py` | Compress only generated unit debug sections, preserving executable sections. |
| `tools/atomfix6_counts.py` | Finite production instruction scopes, no servers, rates or PMU sampling. |
| `tools/atomfix6_final.py` | Final harness, production-target freshness, and delivered-arm identity checks. |
| `tools/atomfix6_park_pre.py` | Repeat the observed PRE park witness in both namespaces/read-local settings. |
| `tools/atomfix6_proof.py` | Selected gate jobs on the lane allocation; never run ABBA or a full iteration. |
| `tools/atomfix6_receipts.py` | Collect completed lane receipts, retaining failures and exact count denominators. |
| `tools/atomfix6_retire.py` | Retire large payloads only after their correctness job has passed. |
| `tools/atomfix6_suite.py` | Sequential selected correctness jobs; no iteration or performance driver. |
| `tools/atomfix_controls.py` | Prepare a throwaway AT1/AT2 PRE twin under build/, retaining the new bug counter/tests. |
| `tools/atomiccollapse_artifacts.py` | Raw ELF audit for atomic-collapse factoring. Never executes an audited artifact. |
| `tools/blockfix2_pad.py` | Offline PAD-A: PRE behaviour, POST BlockingState layout and .text size. |
| `tools/blockfix2_scope.py` | Bounded serverless paths in linked production routines, no rates. |
| `tools/blockfix3_pad.py` | PAD-A: PRE behaviour, inert POST cold-statistics layout and total text size. |
| `tools/blockfix3_proof.py` | Run selected whole gate jobs serially on the lane's CPUs and ports. |
| `tools/blockfix3_repro.py` | Bounded PRE/oracle reproductions and unchanged upstream Tcl assertions. |
| `tools/blockfix3_scope.py` | Bounded serverless paths in linked production routines, no rates. |
| `tools/blockfix3_tcl_compare.py` | Fresh-server, bounded PRE/POST/oracle checks for full-job Tcl failures. |
| `tools/blockfix4_budget.py` | Compile-only PRE/POST headroom survey for the two affected hot emitters. |
| `tools/blockfix4_pad.py` | PAD-A: PRE behaviour, inert POST blocking-registry layout and total text size. |
| `tools/blockfix4_proof.py` | Run whole correctness jobs on the lane CPUs/ports; retain every verdict. |
| `tools/blockfix4_scope.py` | Bounded serverless paths in linked production routines, no rates. |
| `tools/blockfix4_summary.py` | Summarize archived gate verdicts and black-box counts without changing verdicts. |
| `tools/blockfix4_verify.py` | Audit the retained final correctness receipts; never boot a server. |
| `tools/blockfix_climon.py` | Replay interrupted Climon legs through differ_gate.sh's focused-proof interface. |
| `tools/blockfix_identity.py` | Audit the actual MGET/MSET entry points as well as GET/SET handlers. |
| `tools/blockfix_pad.py` | Link a PRE-behaviour PAD-A control with POST's total .text size, without running it. |
| `tools/blockfix_ports.py` | Reserve lane ports against ephemeral clients while running the real gate job. |
| `tools/blockfix_receipts.py` | Collect completed blockfix gate receipts without starting any workload. |
| `tools/blockwake_counts.py` | blockwake: finite production instruction scopes, PRE vs POST. No server, load, timing or rates. |
| `tools/blockwake_pad.py` | blockwake PAD-A: unmodified PRE behaviour linked to POST's .text extent (kind A, behaviour |
| `tools/boot_support_artifacts.py` | Offline ELF audit and cleanup-boot PAD controls. Never executes a server ELF. |
| `tools/boot_support_controls.py` | Compile/run throwaway SERVERLESS boot-helper controls; never start a server. |
| `tools/ccfix2_prove.py` | Build/run ccfix2 serverless witnesses; never starts a server or load generator. |
| `tools/ccfix3_prove.py` | Build/run ccfix3 serverless witnesses on CPUs 112-127; never starts a server or load generator. |
| `tools/ccfix3_wire.sh` | Focused CC11/12/13/18 proof. Reuse the gate's exact listener ownership helpers; |
| `tools/ccfix4_budget.py` | Reproducible db0/main.o budget search; compile and inspect only, on CPUs 112-127. |
| `tools/ccfix4_prove.py` | Run unchanged ccfix3 witnesses against the fresh ccfix4 arms on CPUs 112-127. |
| `tools/ccfix4_server_budget.py` | Audit merged PS/CC cold emitter budgets without changing production source. |
| `tools/ccfix5_collect.py` | Retain a ccfix5 correctness receipt without converting outer gate failures to PASS. |
| `tools/ccfix5_probe.py` | Focused diagnosis on a listener owned by ccfix5_probe.sh, not a gate receipt. |
| `tools/ccfix5_probe.sh` | Import the gate's exact armed-fused boot and listener ownership helpers. |
| `tools/ccfix5_prove.py` | Run the unchanged ccfix instruction/unit/layout witnesses on ccfix5 arms. |
| `tools/ccfix_tables.py` | Supplement the linked checker with exact data/case-target proofs; never executes an arm. |
| `tools/cfgfix2_counts.py` | Serverless production command census. No server, rate, or load generator. |
| `tools/cfgfix2_gate.py` | Run selected tests/gate.sh jobs for lane cfgfix2 and archive the partial receipt. |
| `tools/cfgfix2_pad.py` | PAD-A: unmodified PRE behaviour with POST's total .text extent. No workload. |
| `tools/cfgfix2_table.py` | PRE/POST command-scope instruction table for lane cfgfix2. Reads the census JSON only. |
| `tools/cfgfix2_tcl_compare.py` | Compare tests/redis_tcl.py survey summaries (no manifest) between PRE and POST. |
| `tools/cfgfix2_units.py` | Build `make all` plus every job_production_units target, then prove freshness with make -q. |
| `tools/cfgfix_counts.py` | Serverless production command census. No server, rate, or load generator. |
| `tools/cfgfix_inventory.py` | Inventory the local Redis standardConfig table and captured CONFIG replies. |
| `tools/cfgfix_pad.py` | PAD-A: unmodified PRE behaviour with POST's total .text extent. No workload. |
| `tools/clientcompat_budgets.py` | Compile-only GCC unit-growth evidence; bounded to this lane's CPUs. |
| `tools/clientcompat_counts.py` | Finite production instruction census. No server, timing, or rates. |
| `tools/clientcompat_inline_trials.py` | Bounded compile and instruction-count trials of scatter inlining limits. |
| `tools/clientcompat_pad.py` | PAD-A: PRE compatibility behavior at POST's exact ELF/text/data layout. |
| `tools/clientcompat_pause_audit.py` | Compare every Redis metadata command/subcommand against the production classifier. |
| `tools/clientcompat_receipts.py` | Retain whole gate-job receipts without treating a partial run as a full gate. |
| `tools/clientcompat_report.py` | Validate the complete finite instruction product and attribute every changed symbol. |
| `tools/clientcompat_unit_build.py` | Rebuild required units in bounded disk batches, retaining ELF identity receipts. |
| `tools/clientcompat_verdict.py` | Check the final selected-job verdict, preserving superseded failures. |
| `tools/cmdfix2_auditors.py` | Rerun the supplied audit code, changing only lifecycle CPUs, ports and paths. |
| `tools/cmdfix2_compact_units.py` | Compress only unit-binary debug sections; assert every loaded section is unchanged. |
| `tools/cmdfix2_counts.py` | Finite serverless instruction counts; production code, no workload rate. |
| `tools/cmdfix2_evidence.py` | Summarize original receipts; archive red controls as well as green runs. |
| `tools/cmdfix2_fifo_diagnostic.py` | One serial PRE/POST diagnostic for the gate's failed FIFO latency-guard leg. |
| `tools/cmdfix2_final_main.py` | Bind the final command-family/differential gate jobs to the delivered POST. |
| `tools/cmdfix2_freshness.py` | Build every production_units target and record make -q without hand-copying its list. |
| `tools/cmdfix2_more_jobs.py` | Run the remaining mode/engine legs through the gate's selected-job interface. |
| `tools/cmdfix2_pad.py` | Serverless PAD-A (PRE behaviour, POST text extent) and inverse PAD-B. |
| `tools/cmdfix2_related_jobs.py` | Complete related command-family jobs through the gate's own interface. |
| `tools/cmdfix_artifacts.py` | Build a kind-A fingerprint control without executing a server. |
| `tools/cmdmeta_audit.py` | EX9 offline ordinary-command byte, instruction and linked-layout receipts; no ELF execution. |
| `tools/compat2_mset_control.py` | Disposable C2 state injector: give marker-valued MSET candidates a TTL. |
| `tools/compat2_pad.py` | PAD kind A: restore PRE behavior in POST's exact ELF section/symbol layout. |
| `tools/crlffix_arms.py` | Offline exact-layout PAD-A and one-helper sanitizer-bypass control. |
| `tools/crlffix_fast_scope.py` | Same command fixture and named-function scope as crlffix_scope.py, via ptrace. |
| `tools/crlffix_scope.py` | Bounded serverless paths in linked production routines, no rates. |
| `tools/ctlfix_artifacts.py` | Offline ctlfix PAD-A, linked-body audit and gate evidence archiving. |
| `tools/datafix1_pad.py` | PAD-A: link PRE objects unchanged, matching POST total executable .text size. |
| `tools/deadcode2_artifacts.py` | Serverless, complete object-function inventory for the deadcode2 cleanup. |
| `tools/deadcode2_budget.py` | Compile-only search for the touched IO translation units' PRE hot-body budgets. |
| `tools/deadcode2_linked.py` | Explain, without weakening r7shadow_noop, its three unnamed jump-table moves. |
| `tools/deadcode2_pad.py` | Offline type-A diagnostic compatibility twin at POST's exact executable layout. |
| `tools/deadfused_artifacts.py` | Offline deadfused ELF receipts and the cold INFO compatibility twin. |
| `tools/encodingfix_pad.py` | Type-A encodingfix control: PRE's intset default in POST's exact text/layout. |
| `tools/eoffix.py` | Selected correctness jobs on the eoffix allocation; never measure rates. |
| `tools/eoffix_aof.py` | Build native AOF/QSBR controls from an arm's production objects. |
| `tools/eoffix_archive_data.py` | Preserve completed correctness-job data before reclaiming build disk space. |
| `tools/eoffix_bind.py` | Bind actual entered instruction addresses to each production arm. |
| `tools/eoffix_compare.py` | Compare final production-bound instruction scopes without aggregating away a cell. |
| `tools/eoffix_counts.py` | Reuse wave14's serverless instruction instrument with eoffix source arms. |
| `tools/eoffix_dedup.py` | Share byte-identical Redis tools in completed, private Tcl checkouts. |
| `tools/eoffix_final.py` | Serialize final-arm correctness work on the lane's eight CPUs; never measure rates. |
| `tools/eoffix_receive_counts.py` | Count the ordinary epoll event plus short receive in production bodies. |
| `tools/eoffix_retire_layout.py` | Retain the verified layout twins and retire their reproducible link objects. |
| `tools/eoffix_retire_scopes.py` | Retire only completed, production-bound transient probes; keep every receipt. |
| `tools/eoffix_source_sync.py` | Repair comment-only R7 parity, rebuild, and prove the frozen runtime unchanged. |
| `tools/eoffix_summary.py` | Fold retained receipts without converting a failed or incomplete run to a pass. |
| `tools/eoffix_verify.py` | Require the complete final proof inventory; an interrupted run is not a pass. |
| `tools/exbatch_directed.py` | Mainline-only EX1/EX3/EX6 directed measurements (never part of the gate). |
| `tools/exbatch_rebuild_arms.py` | Rebuild the frozen lane arms without starting a server or load generator. |
| `tools/exbatch_source_proof.py` | Frozen PRE-source closure and static instruction receipts; executes no ELF. |
| `tools/exec1s_aux.py` | Bounded allocation and linked IO scopes, no network or rate measurements. |
| `tools/exec1s_budget.py` | Compile-only exec1s inline-budget controls; no workload/rate measurements. |
| `tools/exec1s_build.py` | Rebuild frozen arms serially; keep binaries/probes, remove source/object trees. |
| `tools/exec1s_debug.py` | Build visit-counter instruments. These are not release rate arms. |
| `tools/exec1s_directed.py` | Re-prove X2 with production helpers and throwaway, discriminating controls. |
| `tools/exec1s_finish_proof.py` | POST correctness jobs and their supplementary legs; never a complete gate. |
| `tools/exec1s_idle.py` | Exact named-production instruction counts for one quiet fused rotation. |
| `tools/exec1s_live_receipts.py` | Retain the gate's individual verdicts and hashes after the live proof ends. |
| `tools/exec1s_pad.py` | Build an exact-image type-A control pair; never starts a server. |
| `tools/exec1s_pad_scope.py` | Build command fixtures in the same two-image layout as PAD-A, no servers. |
| `tools/exec1s_proof.py` | Run the exec1s correctness inventory through the gate job interface only. |
| `tools/exec1s_retire_probes.py` | Delete only fully completed, hash-verified probes; retain their proof binding. |
| `tools/exec1s_trace.py` | Reduced re-proof: 48 ordinary scopes per PRE/POST/PAD-A, relevant lever scopes. |
| `tools/exec1sd.py` | exec1s-d frozen builds and bounded instruction scopes; no performance work. |
| `tools/exec1sd_alignment.py` | Compile-only scatter jump-padding trial, with linked production count scopes. |
| `tools/exec1sd_arms.py` | Frozen attribution arms, built serially; never starts a workload. |
| `tools/exec1sd_lottery.py` | Bounded W16 smoke for the copied-source witness image, not a nightly verdict. |
| `tools/exec1sd_pad.py` | Type-A common-image control, using headline PRE and the final production POST. |
| `tools/exec1sd_proof.py` | Lane CPU/port-bound partial gate invocations; no full iteration or load generators. |
| `tools/exec1sd_receipts.py` | Bind the lane's bounded counts, frozen images and individual-job verdicts. |
| `tools/exec1sd_retire.py` | Retire large payloads only from completed, passing private gate jobs. |
| `tools/exec1sd_save.py` | Repeat the unchanged seed-22 psfix leg and observe native SAVE refusal branches. |
| `tools/exec1sd_save_full.py` | Replay the original complete split-0 seed plan, observing SAVE's actual result. |
| `tools/exec1sd_save_native.py` | Bounded, unchanged psfix seed-22 rerolls on native frozen servers. |
| `tools/exec1sd_scatter.py` | Count true scatter children without replacing any frozen merit binary. |
| `tools/exec1sd_slowlog.py` | Replay the unchanged isolated upstream assertion on frozen PRE and POST. |
| `tools/execfifo2_attribution.py` | Account for every measured EXEC instruction delta; no residual bucket. |
| `tools/execfifo2_control_smoke.py` | Bounded correctness smoke of the exact-image control pair, no load generator. |
| `tools/execfifo2_coverage.py` | Check completed selected-job groups and explicit live-leg inventories. |
| `tools/execfifo2_freshness.py` | Query the complete gate production-unit inventory without rebuilding it. |
| `tools/execfifo2_negative.py` | Serverless process-local breaks; no broken source or binary is published. |
| `tools/execfifo2_proof_record.py` | Archive all selected-job attempts, their legs, digests and explicit failures. |
| `tools/execfifo2_scope.py` | Reproducible serverless command/EXEC counts, bound to each linked image. |
| `tools/execfifo2_storm.py` | Maintainer-only Redis adapter for the unchanged shared T6 storm workload. |
| `tools/execfifo2_validate.py` | Selected correctness jobs only; never the iteration or performance tiers. |
| `tools/execfifo3_archive_intermediates.py` | Losslessly archive superseded images; never touch the five final arms. |
| `tools/execfifo3_artifacts.py` | Freeze release arms and the explicit type-A common-image control pair. |
| `tools/execfifo3_compact.py` | Compress debug data in completed unit binaries; preserve executable text. |
| `tools/execfifo3_control_smoke.py` | Bounded correctness smoke of the exact-image control pair, no load generator. |
| `tools/execfifo3_coverage.py` | Check completed selected-job groups and explicit live-leg inventories. |
| `tools/execfifo3_freshness.py` | Query the complete gate production-unit inventory without rebuilding it. |
| `tools/execfifo3_input_scope.py` | Classify parser buffer, TLS and otherwise unlabelled load sites. |
| `tools/execfifo3_negative.py` | Serverless process-local breaks; no broken source or binary is published. |
| `tools/execfifo3_perf.py` | perf stat on bounded serverless fixtures, no servers or throughput output. |
| `tools/execfifo3_perf_summary.py` | Summarize the complete finite-counter matrix without reporting rates. |
| `tools/execfifo3_probe_archive.py` | Losslessly archive completed scope probes while retaining their identities. |
| `tools/execfifo3_proof_record.py` | Archive all selected-job attempts, their legs, digests and explicit failures. |
| `tools/execfifo3_scope.py` | Linked production instruction/memory scopes; finite fixtures, never rates. |
| `tools/execfifo3_scope_consistency.py` | Compare saved scopes, including calls outside the counted production bodies. |
| `tools/execfifo3_validate.py` | execfifo2's complete job groups, pinned to execfifo3's allocation. |
| `tools/execfifo_budget.py` | Compile-only execfifo inline-budget controls; no workload/rate measurements. |
| `tools/execindex_budget.py` | Compile-only execindex inline-budget controls; no workload/rate measurements. |
| `tools/execindex_control_smoke.py` | Bounded correctness smoke of the exact-image control pair, no load generator. |
| `tools/execindex_debug.py` | Build instrumented PRE/POST registry-visit servers; never execute workloads. |
| `tools/execindex_identity.py` | PRE identity audit including INCR and MGET/MSET's shared dispatch bodies. |
| `tools/execindex_pad.py` | Build an exact-image type-A control pair; never starts a server. |
| `tools/execindex_proof_record.py` | Archive selected-job ledgers and explicit failures, never infer a full gate pass. |
| `tools/execindex_scope.py` | Bounded serverless paths in linked production routines, no rates. |
| `tools/flipfix5_artifacts.py` | flipfix5 PAD-A: PRE behaviour in POST's exact ELF layout. No server, no load generator. |
| `tools/flipfix5_counts.py` | flipfix5 serverless instruction scopes, using the established production fixture. |
| `tools/flipfix6_artifacts.py` | PAD-A behaviour twin: POST layout with PRE's session-null FLIP predicate. |
| `tools/flipfix6_counts.py` | flipfix6 serverless instruction scopes, using the established production fixture. |
| `tools/flipfix6_diag.py` | Make an isolated PRE diagnostic source copy. Never edits production sources. |
| `tools/flipfix6_evidence.py` | Archive the lane's owned correctness evidence and classify every diagnostic refusal. |
| `tools/flipfix7_artifacts.py` | PAD-A: PRE FLIP liveness decisions with POST's exact text size and layout. |
| `tools/flipfix7_budget_counts.py` | Finite instruction scopes with the source-derived compiler budgets. |
| `tools/flipfix7_budgets.py` | Source-accurate compile-only budget derivation; no server or rates. |
| `tools/flipfix7_capture.py` | Archive gate job ledgers and raw textual correctness evidence, never build objects. |
| `tools/flipfix7_compact_build.py` | Compress completed proof binaries' debug sections; preserve every allocated byte/address. |
| `tools/flipfix7_counts.py` | flipfix7 serverless instruction scopes, using the established production fixture. |
| `tools/flipfix7_freshness.py` | Check every production-unit output via make -q, plus delivery identities. |
| `tools/flipfix7_negative.py` | Strict PRE gate rejection and PAD-A liveness witnesses; correctness only. |
| `tools/flipfix7_proof.py` | Selected gate jobs on the assigned lane only. No iteration or rate tier. |
| `tools/flipreport_proof.py` | Offline cleanup-flipreport evidence and serverless controls; pin to CPUs 112-127. |
| `tools/flipsettle_artifacts.py` | Exact ELF proof for cleanup-flipsettle. Offline only; never executes an input ELF. |
| `tools/flipsettle_controls.py` | Generate throwaway controller mutants and run the existing serverless transition checks. |
| `tools/flushfix2_budget.py` | Compile-only IPA surveys and trials; every child inherits CPUs 0-15. |
| `tools/flushfix2_budget_counts.py` | Use compile-only budget trial objects in finite serverless scopes. |
| `tools/flushfix2_counts.py` | Finite serverless command scopes, using the established production fixture. |
| `tools/flushfix2_freshness.py` | Check every literal production-unit target with its actual makefile set. |
| `tools/flushfix2_identity.py` | Extend the established exact-body inventory to the new FLUSH-only objects. |
| `tools/flushfix2_live.py` | Finite MGET scopes with eight live EXEC-format records, no listening server. |
| `tools/flushfix2_pad.py` | PAD-A behaviour twin: legacy FLUSH routing in the candidate's exact ELF layout. |
| `tools/flushfix2_receipts.py` | Retain compact, hashed correctness receipts before pruning build artifacts. |
| `tools/flushfix2_sweep.py` | Bounded correctness/oracle sweep; no rate or timing verdict. |
| `tools/flushfix2_verification_receipts.py` | Archive completed gate-job and differential receipts without changing verdicts. |
| `tools/flushfix2_verify.py` | Owned correctness jobs and standard differential seeds; never iteration/perf. |
| `tools/flushfix3_budget.py` | Compile isolated scatter budget trials and count finite MGET/MSET scopes. |
| `tools/flushfix3_counts.py` | Run the established finite command scopes against the wave 10 headline. |
| `tools/flushfix3_freshness.py` | Record make -q for every literal production-unit target and both FLUSH suites. |
| `tools/flushfix3_receipts.py` | Archive completed selected-job evidence, preserving earlier failures. |
| `tools/flushfix3_verify.py` | Run selected correctness jobs on the lane's CPUs/ports; never iteration/perf. |
| `tools/gt14fix_evidence.py` | Collect gt14fix subset evidence; never launches a server or changes test results. |
| `tools/infofields2_live.py` | Serial infofields2 proof runner on the assigned server/load CPUs. |
| `tools/infofields_artifacts.py` | SV6/SV7/SV9 offline byte, instruction, link and layout proof; never runs an ELF. |
| `tools/infofields_budget.py` | Offline, TU-local compiler-budget trials; never executes a server. |
| `tools/infofields_controls.py` | Build/run only serverless cron units, including two failing mechanism controls. |
| `tools/infofields_monitor_strict.py` | Non-gated MONITOR witnesses against two already-running peers. |
| `tools/infofix_arms.py` | Link frozen PRE objects into a behaviour-twin PAD-A and cold-root regression. |
| `tools/infofix_latency_controls.py` | Build serverless PRE, no-batch and averaged-duration falsification arms. |
| `tools/infofix_scope.py` | Infofix production-object command scopes via the existing ptrace instrument. |
| `tools/iofix3_artifacts.py` | Offline WB4.1 linked-body identity and exact-layout kind-A control. |
| `tools/iofix3_ports.py` | Keep correctness ports out of automatic client-port allocation between boots. |
| `tools/iofix_budget.py` | Compile-only IO refinement budget trials, constrained to the lane's CPUs. |
| `tools/iofix_full_pad.py` | Kind A: full PRE behavior with POST's exact .text size, not function placement. |
| `tools/iofix_identity.py` | Annotate the full byte inventory and check linked GET/SET/MGET/MSET bodies. |
| `tools/iofix_pad.py` | Offline kind-A writeback behaviour twin for the nominated merit cells. |
| `tools/iopass_controls.py` | Compile throwaway missing-fence controls and require their directed witness to fail. |
| `tools/iopass_receipts.py` | Serverless IO-pass instruction receipts, using the existing ptrace tracer. |
| `tools/iopass_validate.py` | Run existing serverless gate witnesses directly; never run gate.sh or a server. |
| `tools/iotemplates_proof.py` | Offline IO-interface proofs. Never starts a server or measures an ELF arm. |
| `tools/iowake_budgets.py` | iowake: compile-only GCC IPA unit sizes and per-function bodies; no server, no workload. |
| `tools/iowake_counts.py` | iowake zero-cost census: finite production-object command scopes, no server or rates. |
| `tools/iowake_identity.py` | iowake function-body identity between PRE and POST production objects (no server, no rates). |
| `tools/iowake_pad.py` | Build an exact-image type-A control pair; never starts a server (copied from tools/snapfix_pad.py). |
| `tools/l4prebuild_artifacts.py` | Make a kind-A prebuild control by patching a COPY of a linked ELF; never execute it. |
| `tools/lanefull_artifacts.py` | Offline LaneFull ELF proofs and schema controls. Never executes a server arm. |
| `tools/lanefull_controls.py` | Build/run serverless LaneFull controls; all throwaway edits stay under build/. |
| `tools/latencyfix_budget.py` | Compile-only IO refinement budget trials, constrained to the lane's CPUs. |
| `tools/latencyfix_count_trials.py` | Link the production command-scope witness with one compile-only budget trial. |
| `tools/latencyfix_counts.mk` | Same objects and weak-symbol order as the production normal namespace. |
| `tools/latencyfix_histogram.mk` | Only the numeric oracle witness links Redis's independently vendored HDR library. |
| `tools/latencyfix_identity.py` | Audit the actual MGET/MSET entry points as well as GET/SET handlers. |
| `tools/latencyfix_pad.py` | Build a PRE-behavior, POST-text-size PAD-A; never run a workload. |
| `tools/lbfix_artifacts.py` | Prepare serverless LB negative controls, TSan build, and a labelled text-size control. |
| `tools/lbosc3_report.py` | Read-only pooled lbosc3 judge. Scores telemetry, never the harness PASS flag. |
| `tools/lbplanner_pre_receipt.py` | Freeze launch source and emit a PRE serverless pass witness; never compile or run it. |
| `tools/lbplanner_receipts.py` | Serverless instruction/load and layout receipts; no clocks, perf events or live server. |
| `tools/lualibs_artifacts.py` | Offline CC4.7 PAD-A, identity and serverless per-state memory evidence. |
| `tools/lualibs_proof.sh` | Reproduce CC4.7 correctness via complete gate jobs, never the performance tier. |
| `tools/mdbqsbr_artifacts.py` | Offline map structural audit and size-matched type-A control. Never starts a server. |
| `tools/mdbstamp_artifacts.py` | Offline kind-A stamp control: PRE behavior in POST's exact ELF layout. |
| `tools/mkfix2_pad.py` | Build A's type-A control: PRE reply timing in A's exact linked layout. |
| `tools/mkfix_counts.py` | Fixed-command mkfix count runs. No rate or latency measurement or claims. |
| `tools/mkprobe_probe.py` | Directed multi-key diagnostics. Mainline only; NEVER a gate row. |
| `tools/mset8fix_budgets.py` | mset8fix: compile-only GCC IPA unit sizes and per-function bodies; no server, no workload. |
| `tools/mset8fix_counts.py` | mset8fix: finite production instruction scopes, PRE vs POST. No server, load, timing or rates. |
| `tools/mset8fix_identity.py` | mset8fix: linked-body inventory, PRE vs POST, with the gate's strict instruction normalizer. |
| `tools/mset8fix_latency.py` | mset8fix: the survey's hot-key MSET8 latency cell against one TomoKV binary. Correctness only. |
| `tools/mset8fix_loop.sh` | mset8fix: run tests/gate.sh GATE_ONLY_JOBS=JOBS RUNS times against BINARY on fixed CPUs and |
| `tools/mset8fix_pad.py` | mset8fix PAD-A: unmodified PRE behaviour with POST's total .text extent. No workload. |
| `tools/mset8fix_proof.py` | mset8fix: fold the gate-job proof runs into docs/mset8fix/proof/summary.json. No server. |
| `tools/multidb3_artifacts.py` | Offline DB-0 code audit and kind-A boot control. Never runs an executable. |
| `tools/netfix2_artifacts.py` | Freeze release arms and an exact-layout type-A PRE behaviour control. |
| `tools/netfix2_counts.py` | Finite production-object instruction scopes; no server or rate measurement. |
| `tools/netfix2_diagnostics.py` | PRE/POST controls for existing optional EOF and INFO diagnostic gate jobs. |
| `tools/netfix2_proof.sh` | Only the gate's selected correctness jobs; no iteration, ABBA or load generator. |
| `tools/netfix2_tls_counts.py` | 20KB TLS GET owner scopes, clean and WATCHed, with exact replies on both arms. |
| `tools/netfix_collect.py` | Retain netfix gate attempts and their verdicts without turning retries into passes. |
| `tools/netfix_identity.py` | Strict linked-body identity against PRE, using the gate's unchanged normalizer. |
| `tools/netfix_pad.py` | PAD-A for periodic reclamation: retain POST layout, restore PRE idle retention. |
| `tools/netfix_pad_b.py` | PAD-B inverse control: candidate behavior, PRE's exact .text size. |
| `tools/netfix_verify.py` | Run netfix correctness only through gate.sh's job interface, on the lane allocation. |
| `tools/notifycompat_identity.py` | Per-commit GET/SET/MGET/MSET object-code diagnostic (no runtime workload). |
| `tools/notifycompat_pad.py` | Kind A: full PRE behavior with POST's exact .text size, not function placement. |
| `tools/ntfix_proof.py` | Lane ntfix correctness receipts. Only CPUs 80-95 and ports 22800-22803. |
| `tools/overlapaxe_artifacts.py` | Overlap retirement receipts; only the explicit smoke action starts servers. |
| `tools/parkwake_budgets.py` | parkwake: compile-only GCC IPA unit sizes and per-function bodies; no server, no workload. |
| `tools/parkwake_counts.py` | parkwake: finite production instruction scopes, PRE vs POST. No server, load, timing or rates. |
| `tools/parkwake_identity.py` | parkwake: linked-body inventory, PRE vs POST, with the gate's strict instruction normalizer. |
| `tools/parkwake_loop.sh` | parkwake: run tests/gate.sh GATE_ONLY_JOBS=JOBS RUNS times against BINARY on fixed CPUs and |
| `tools/parkwake_matrix.py` | parkwake: run tests/parkwake.py over every declared case x mode x engine for one arm. |
| `tools/parkwake_pad.py` | parkwake PAD-A: unmodified PRE behaviour with POST's total .text extent. No workload. |
| `tools/parkwake_summary.py` | parkwake: one line per matrix row (tools/parkwake_matrix.py output), case-specific metric. |
| `tools/persistfix2_artifacts.py` | Offline persistfix2 PRE/control linking and identity evidence. No workloads. |
| `tools/persistfix_artifacts.py` | Offline layout audit and kind-A PS1 control; never execute/attach to a server. |
| `tools/persistfmt_counts.py` | PRE/POST bounded production instruction counts; no servers, PMU or rates. |
| `tools/persistfmt_pad.py` | Build PAD-A: PRE persistence behavior, POST headers and total .text size. |
| `tools/persistfmt_validate.py` | Run complete selected gate jobs on the lane's CPUs/ports; never run perf. |
| `tools/prefetch_artifacts.py` | EX4.1: offline disassembly witness, exact-layout PAD-A, and linked identity. |
| `tools/probeadapter_proof.py` | Offline probe adapter proofs and throwaway serverless controls; never run a server. |
| `tools/psfix_artifacts.py` | Offline PS5/PS7 function-byte and layout audit; does not execute either binary. |
| `tools/publishfix_pad.py` | PAD-A: PRE publication behaviour in an exact-layout copy of the POST ELF. |
| `tools/publishfix_schedule.py` | Full disposable build that parks one committer after loading drawn. |
| `tools/readreply_proof.py` | Offline cleanup-readreply proofs. Pin to 112-127; never execute a production ELF. |
| `tools/reorder_pad.py` | Make a kind-A R7 scheduler control by patching a COPY of a linked ELF; never execute it. |
| `tools/reorderscan_pad.py` | Build a kind-A text-size control from frozen PRE objects; never run a server. |
| `tools/respresume_artifacts.py` | Static objdump inventory, including every local/COMDAT/db0 parser clone. |
| `tools/respresume_fastpath.py` | Complete-frame parse-selection path of every dispatcher clone, from objdump. |
| `tools/respresume_fastpath_report.py` | Render docs/respresume/fastpath.md from the PRE/POST objdump inventories. |
| `tools/respresume_observer.py` | Make a throwaway incidence observer source tree; never edit production code. |
| `tools/respresume_pad.py` | PAD (A), behavior twin: discard partial argv with POST's exact text layout. |
| `tools/respresume_probe.py` | NT4.2 incidence probe: the round-4 audit's nt4_probe.py cells, re-pinned. |
| `tools/respresume_repro.py` | Run the audit's T12/T12b scripts without touching their originals. |
| `tools/respresume_t12x.py` | T12 at nanosecond CPU resolution, repeated, for the "within 3x of Redis" bound. |
| `tools/respresume_trace.cc` | Execute only an allocation-free complete-frame parser body copied from the |
| `tools/respresume_trace.py` | Count executed complete GET/SET instructions in every production parser body. |
| `tools/ringmarker_proof.py` | Serverless removal inventory, raw ELF controls, and a same-layout kind-A PAD. |
| `tools/rlfix3_info_compare.py` | Compare complete INFO RESP frames under fixed external facts; no normalization. |
| `tools/rlfix3_pad.py` | Build PAD-A: PRE behaviour at POST's exact .text size, from frozen PRE objects. |
| `tools/rlfix3_units.py` | Link the current RL4.15 witness with frozen PRE objects in both namespaces. |
| `tools/rlfix5_artifacts.py` | Offline PAD-A construction and strict linked hot-body inventory; no workloads. |
| `tools/rlfix5_refreeze_comments.py` | Synchronize R7's comment, rebuild, and require identical runtime sections. |
| `tools/rlfix5_validate.py` | Run selected gate jobs within the rlfix5 CPU/port allocation and retain receipts. |
| `tools/rltopo_artifacts.py` | Offline read-path audit and kind-A behaviour twin; never executes a server. |
| `tools/rootcompat_budget.py` | Compile-only rootcompat inline-budget controls; no workload/rate measurements. |
| `tools/rootcompat_counts.py` | Finite production command scopes for rootcompat, on the lane's CPUs only. |
| `tools/rootcompat_pad.py` | Rootcompat PAD-A exact-image pair; builds only, never starts a workload. |
| `tools/rootcore_archive_data.py` | Archive generated persistence data only after its completed proof is retained. |
| `tools/rootcore_collect_proof.py` | Preserve completed gate phases, including failures and private job logs. |
| `tools/rootcore_counts.py` | Rootcore's bounded serverless command census; no listener or rate measurement. |
| `tools/rootcore_freshness.py` | Verify every production_units build target, plus the release executable. |
| `tools/rootcore_pad.py` | PRE behavior with POST text extent; no server or workload is run. |
| `tools/rootcore_proof.py` | Selected correctness jobs only, on rootcore's CPUs/ports; no rate workloads. |
| `tools/rootcore_scheduler.py` | Compare the unchanged single-slot scheduler deadline on PRE and POST plans. |
| `tools/scriptfix2_artifacts.py` | Serverless instruction, selected-definition, layout, and binary receipts. |
| `tools/scriptfix2_counts.mk` | Link both compiled engines in the production weak-symbol order. The fixture |
| `tools/scriptfix2_mutant.py` | Build throwaway, selectable cold-path regressions using POST production objects. |
| `tools/scriptfix2_negative.py` | Independently select each planted regression and require its named Tcl witness. |
| `tools/scriptfix2_pad.py` | Relink frozen PRE objects as a size-controlled PAD-A; no workload is run. |
| `tools/scriptfix3_attribution.py` | Isolate the four scriptfix2 production commits on the landed PRE geometry. |
| `tools/scriptfix3_counts.py` | Bounded warm-call instruction census using linked production objects, no rates. |
| `tools/scriptfix3_jobs.py` | Invoke only gate.sh's whole-job interface, retain every exit and run directory. |
| `tools/scriptfix3_pad.py` | Build a PRE-behavior, POST-text-size PAD-A; never run a workload. |
| `tools/scriptfix3_proof.py` | Finish the lane's selected gate jobs serially on its one eight-core slot. |
| `tools/scriptfix3_receipts.py` | Archive completed selected-job evidence without disposable checkouts or data. |
| `tools/scriptfix4_counts.py` | scriptfix4 finite instruction census: linked production objects, no server, no rates. |
| `tools/scriptfix4_pad.py` | PAD-A (A: behaviour twin): unmodified PRE objects plus padding to POST's .text. |
| `tools/serverfix_hot_identity.py` | Audit the actual MGET/MSET entry points as well as GET/SET handlers. |
| `tools/serverfix_identity.py` | Strict linked-body identity against PRE, using the gate's unchanged normalizer. |
| `tools/serverfix_pad.py` | Build a PRE-behavior, POST-text-size PAD-A; never run a workload. |
| `tools/shutsave_artifacts.py` | Build/run serverless shutdown controls against frozen PRE and POST objects. |
| `tools/shutsave_audit.py` | Annotate the full PSFIX byte audit with shutdown-specific instruction receipts. |
| `tools/shutsave_pad.py` | Offline PAD A: PRE behavior, POST cold DatabaseMap::State layout and .text size. |
| `tools/signalacct_artifacts.py` | Prepare isolated IO accounting controls and audit ELF identities; never run servers. |
| `tools/signalacct_tail_artifacts.py` | Serverless tail controls and isolated build trees; never starts a server. |
| `tools/snapfix2_artifacts.py` | Compile/identity/serverless instruction evidence for snapfix2; no performance workloads. |
| `tools/snapfix2_nx_control.py` | Classify the supplementary fused txn_nx failure without changing its check. |
| `tools/snapfix2_verify.py` | Run snapfix2 correctness receipts on CPUs 0-15 / ports 20100-20199 only. |
| `tools/snapfix_budget.py` | Compile-only inline-budget survey/trials for the snapfix units; no workload, no rates. |
| `tools/snapfix_budget_bodies.py` | Second budget criterion: ALL function bodies (not only HOT) of kept compile-only trial objects. |
| `tools/snapfix_identity.py` | Function-body identity between the PRE and POST object sets (no server, no rates). |
| `tools/snapfix_long_storm.py` | Timeline of one tests/snapfix.py storm leg (no rates claimed): INFO sampled every --every s. |
| `tools/snapfix_pad.py` | Build an exact-image type-A control pair; never starts a server (copied from tools/execindex_pad.py). |
| `tools/snapfix_record.py` | Archive one finished tests/gate.sh run (partial ledger, per-job verdicts, small results) into |
| `tools/snapfix_reproduce.py` | Run the unmodified at412 diagnostics in the snapfix allocation (no rates). |
| `tools/snapfix_scope.py` | Bounded serverless paths in linked production routines, no rates. |
| `tools/snapfix_stacks.py` | Retain GDB stacks for one bounded at412 diagnostic cell. |
| `tools/snapfix_storm_capture.py` | Reproduce SNAP-STORM-1 and keep the stuck clients CONNECTED while capturing state. |
| `tools/splitlocal_artifacts.py` | Offline PAD-A and byte receipts for splitlocal. Never executes an ELF. |
| `tools/storefix5_append.py` | Link the same copy witness against either arm's ordinary production objects. |
| `tools/storefix5_archive.py` | Preserve gate receipts and wire transcripts, excluding executables/persistence data. |
| `tools/storefix5_arm.py` | Link an isolated arm from production objects and explicit cold-unit trials. |
| `tools/storefix5_audit.py` | Check the frozen lane artifacts and final receipts without starting a server. |
| `tools/storefix5_budgets.py` | Compile-only inlining-budget controls for unchanged command-path bodies. |
| `tools/storefix5_checks.py` | Finite correctness/footprint checks. No offered-load or throughput measurement. |
| `tools/storefix5_clock_geometry.cc` | Serverless allocation geometry control for post-freeze alternatives. This is |
| `tools/storefix5_counts.py` | Finite command-scope instruction counts; no listener, PMU, load or rate. |
| `tools/storefix5_final_proof.py` | Run the final frozen-arm proof; differential jobs own the lane CPUs serially. |
| `tools/storefix5_finish_proof.py` | Serialize the remaining PAD, falsifier and selected-job proofs. |
| `tools/storefix5_inventory_proof.py` | Complete related-job coverage after the main and quiet proof queues stop. |
| `tools/storefix5_memory.py` | Finite maxmemory footprint matrix; no throughput measurement. |
| `tools/storefix5_notification_proof.py` | Check the accounted-memory notification fixture through complete gate jobs. |
| `tools/storefix5_pad.py` | PAD-A: PRE behavior, POST's cold helper size and aggregate .text extent. |
| `tools/storefix5_proofs.py` | Collect selected gate job receipts without changing their verdicts. |
| `tools/storefix5_report.py` | Render the finite footprint/command-scope receipts, without running workloads. |
| `tools/storefix5_retirement.py` | Serverless sampler/retirement falsifiers; production sources stay unchanged. |
| `tools/storefix5_serial_proof.py` | Run the quiet-preflight and standard differential jobs serially on lane CPUs. |
| `tools/storesize_poller.py` | Maintainer-only 1 Hz bare-INFO poller for an already-running measurement arm. |
| `tools/tlsserve_proof.py` | Offline TLS staging proofs. Pin to 112-127. Never execute a production ELF. |
| `tools/trackorder_counts.py` | Reuse the production command-scope tracer on trackorder's frozen headline. |
| `tools/trackorder_pad.py` | PAD-A behaviour twin: PRE deferral at POST's exact file/text/layout. |
| `tools/trackorder_run.py` | Lane-confined correctness receipts through whole gate jobs; never perf/full gate. |
| `tools/trackorder_units.py` | Build exactly the gate's production prerequisites at lane -j16, then check freshness. |
| `tools/txnfix4_abort_site.py` | CD5.6 abort-site witness: run Z-T6's mpop-watch-then-tracking shape under gdb, no rates. |
| `tools/txnfix4_auditors.py` | Re-run the round-5 auditors' own tests for CD5.3/CD5.4/CD5.5/CD5.6/TM5.1 on one binary. |
| `tools/txnfix4_pad.py` | PAD-A (behaviour twin): PRE objects linked with inert padding to POST's total .text size. |
| `tools/txnfix4_probes.py` | txnfix4 supplementary probes (receipts only, no gate row, no rates). |
| `tools/txnfix4_proof.py` | Run whole gate jobs through tests/gate.sh's partial-job interface on the lane's CPUs and |
| `tools/txnfix4_scope.py` | Bounded serverless paths in linked production routines, no rates. |
| `tools/txnfix_admission_control.py` | Build serverless negative controls for the exclusive admission/drain proof. |
| `tools/txnfix_barrier_control.py` | Build an isolated MSETNX barrier-removed control; never starts a server. |
| `tools/txnfix_budget.py` | Compile and compare one object's hot bodies; never starts a workload. |
| `tools/txnfix_pad.py` | Link a type-A aggregate-text-size control from the unchanged merged PRE objects. |
| `tools/txnfix_path_counts.py` | Summarize paired production-object instruction traces without accepting a cost bar. |
| `tools/txnfix_scatter_audit.py` | Preserve the complete scatter function inventory and both disassemblies. |
| `tools/versionstr_artifacts.py` | Version-string lane's offline body/link/layout proof; never runs a server. |
| `tools/versionstr_smoke.py` | redis-py smoke against an existing listener; never starts a server or installs packages. |
| `tools/wave11.py` | Wave11 compile-only artifacts and bounded correctness orchestration. |
| `tools/wave11_budgets.py` | Compile-only per-unit trials and linked reference scoring; no server or workload. |
| `tools/wave11_counts.py` | Bounded warm-call instruction census using linked production objects, no rates. |
| `tools/wave12.py` | Wave12 compile-only artifacts and bounded correctness orchestration. |
| `tools/wave12_budgets.py` | Compile-only per-unit trials and linked reference scoring; no server or workload. |
| `tools/wave12_counts.py` | Bounded warm-call instruction census using linked production objects, no rates. |
| `tools/wave13.py` | Wave12 compile-only artifacts and bounded correctness orchestration. |
| `tools/wave13_budgets.py` | Compile-only per-unit trials and linked reference scoring; no server or workload. |
| `tools/wave14_arms.py` | Build-only wave14 layout twins and the Tcl planted regression. |
| `tools/wave14_budgets.py` | Compile-only per-unit trials and linked reference scoring; no server or workload. |
| `tools/wave14_cleanup.py` | Retain completed jobs' persistence data before removing their loose copies. |
| `tools/wave14_closeout.py` | Bind completed wave14 controls without replacing any original verdict. |
| `tools/wave14_counts.py` | Finite production instruction scopes, including outlined STL and Lua VM code. |
| `tools/wave14_coverage.py` | Account for every declared public row without turning failures into passes. |
| `tools/wave14_eof_budgets.py` | Link the EOF trial budgets against frozen production objects; compile-only. |
| `tools/wave14_fifo_controls.py` | Repeat the unchanged FIFO gate job with explicit client CPU controls. |
| `tools/wave14_followthrough.py` | Repeat the declared correctness jobs after the R7 integration correction. |
| `tools/wave14_r7_control.py` | Run the stale-owner native control through the unchanged gate job interface. |
| `tools/wave14_summary.py` | Summarize finite instruction scopes and bind entered bodies to each arm. |
| `tools/wave14_txnorder_diagnostics.py` | Run the unchanged transaction-order gate job with failure-only stack capture. |
| `tools/wave14_validation.py` | Audit wave14's selected gate receipts without changing their verdicts. |
| `tools/wave14_xacct_followthrough.py` | Repeat debug jobs after applying the gate's existing no-rate policy to XACCT. |
| `tools/wave15.py` | Wave15 selected gate jobs, source inventories, and linked identity receipts. |
| `tools/wave15_aof_stacks.py` | Own-child GDB checks of the two pre-fix AOF hangs; no attach permission needed. |
| `tools/wave15_bind.py` | Bind counted PCs to the frozen server bodies before pruning probe binaries. |
| `tools/wave15_budgets.py` | Compile-only per-unit trials and linked reference scoring; no server or workload. |
| `tools/wave15_counts.py` | Finite production instruction scopes, including outlined STL and Lua VM code. |
| `tools/wave15_lua_binding.py` | Verify the one anonymous Lua literal missed by the strict body normalizer. |
| `tools/wave15_refine.py` | Rebase compile-only inlining trials onto the final integration source. |
| `tools/wave15_scan_expiry.py` | SCAN's physical expiry of the keys it visits, per arm (owner decision 4, wave15 phase 2). |
| `tools/wave16_budgets.py` | wave16: compile-only GCC IPA unit sizes and per-function bodies for the merged tree; no server, |
| `tools/wave16_counts.py` | wave16: command-scope instruction census of the merged tree against the 8be4f68323 receipts. |
| `tools/wave16_identity.py` | wave16: linked-body inventory of the merged POST against PRE 8be4f68323. No server or workload. |
| `tools/wave16_pad.py` | wave16 PAD-A: unmodified PRE behaviour with the merged POST's total .text extent. No workload. |
| `tools/wave5b_trace.py` | Disposable owner-local counters and fixed-request-count mechanism runs. |
| `tools/wb_rule_2s_artifacts.py` | Offline 2s arm, byte-identity, PAD and instruction receipts. Never run tomokv. |
| `tools/wb_rule_2s_trace.cc` | Single-pass instruction audit of a serverless witness; no clock/perf events. |
| `tools/wb_rule_artifacts.py` | Offline c12 source and emitted-code receipts. No server or measurement. |
| `tools/wb_rule_receipts.py` | Audit the production writeback rule against frozen serverless witnesses. |
| `tools/wbknobs_measure.py` | Mainline-only writeback null/sweep coordinator around the existing ABBA instrument. |
| `tools/wbknobs_receipts.py` | Offline writeback knob instruction/layout receipts. Never starts a server or load. |
| `tools/wbland_artifacts.py` | Freeze policy 0/1 arms and audit every writeback-dependent object's text. |
| `tools/woundfix_gate.py` | Run named correctness jobs through gate.sh's real interface, never a full tier. |
| `tools/woundfix_live.py` | AT4-WOUND-1 correctness only: oversubscribe this lane's CPUs, measure no rates. |
