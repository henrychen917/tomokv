# Wave 8 landing

## wave8 integration

Integration on `cx-wave8`, base `3700b51d7`; no push. All execution is pinned to CPUs 64–95, builds use `-j32`, and correctness listeners are restricted to ports 20000–20099. Performance campaigns and the full iteration remain maintainer-owned.

### Merges and row accounting

| Lane | Merge | DQ | DF |
|---|---|---:|---:|
| harness5 | `60725691c` | 0 | 0 |
| readability-a0 | `3fece28eb` | 1 | 1 |
| lualibs | `7cdc95318` | 1 | 1 |
| latencyfix | `81a7ec066` | 3 | 3 |
| iofix3 | `ea28a43a6` | 1 | 1 |
| execindex | `969b21fd3` | 2 | 2 |
| Total | | **8** | **8** |

All six reports were read before merging. Every merge is `--no-ff` in the requested order. Declared rows and the complete label fixture total 823; all eight additions precede the quick exit. The maintainer should change **798/815 → 806/823**. `EXPECT_QUICK` and `EXPECT_FULL` remain unchanged. Four missing fixture labels (readability + latencyfix) were restored without adding rows.

### Integration findings

- Execindex adds ten assertion sites. They now use TOMO_ASSERT; the destructor's repeated `!queue` condition uses salt 1. The map parser needed support for assignment operators and destructor names. A directed declarator check covers both; all 15 sites must remain unique and map to the actual enclosing functions.
- The EXEC rotation/fast lanes retain latencyfix's `execute_resumed` wrapper and execindex's intrusive queues. Both rotation and fast-poll work must be timed through that wrapper.
- Both ordinary gate engine selection and the lane proof alias survive the launcher merge; explicit job arguments still take precedence.
- WB4.1 uses hardcoded multiplier 2. The build override and executable recipes for the discarded 4/8 arms are removed. Historical lane receipts remain historical evidence, not selectable build arms.
- AT4-WOUND-1 remains the documented pre-existing non-gate diagnostic in `docs/execindex/wound-window/DEFECT.md`; this integration does not attempt the separately assigned repair.

Builds, instruction counts, directed interactions and correctness receipts are recorded below. No throughput claim is made.

### Tcl known-failure reconciliation

Nineteen named assertions are promoted: thirteen `LUA-HELPER-LIBS` and six `LATENCY-HISTOGRAM-ABSENT`. The required inventory becomes 1,643 assertions per mode, with 405 named known failures. The unchanged upstream latency-monitor file assumes Redis's default tracking=yes; its manifest explicitly enables tracking for that file only. The production default remains no, with independent default/off-allocation coverage. Arbitrary server flags and disabling tracking in that file are rejected by directed manifest controls.

Other roots were reviewed: execindex changes claim lookup and scheduling, not MULTI OOM admission, command policy, blocked-key wake order or WATCH's spurious invalidation root. IO parking changes idle work detection, not blocking command semantics. Readability and harness repairs change no command replies. Latencyfix adds histogram child samples but does not implement the pre-existing `SLOWLOG-EXEC-BODY-NOT-LOGGED` mechanism; that named failure remains. The final `compat2` job passes all six rows, including the public autharity row backed by both Tcl modes (`docs/wave8/jobs/tcl-final.json`).

The first Tcl run verified all promoted names but caught a manifest multiplicity error: each of the thirteen Lua names runs twice. The exact multiset therefore grows by 32 assertions, not 19. The first run also retained two cross-client-order failures: MONITOR saw the polling client's INFO before the blocked client's BLPOP, and an unblocking LPUSH overtook another client's EXEC, causing its WATCH to abort. Neither is hidden or newly skipped; final isolated runs will retain their own outcomes.

### EXEC timing interaction

The added `tests/wave8.py` runs inside every existing `execfair` leg (both modes, engines and atomic settings). The final check uses six contending EXEC/INCR/INCR/MGET connections and two Lua-helper connections with private cross-owner keys. It requires both fast polls and internal retries on bounded fresh cohorts, exact results, exact histogram counts, and an off transition. Sharing the same script keys initially produced legal explicit `TRYAGAIN` conflicts; private script keys isolate successful-command accounting without weakening the EXEC contention.

The pre-fix merged POST failed all eight legs: 128 EXECs and 64 successful scripts produced 394–410 INCR samples instead of 384; one leg also counted 129 MGETs instead of 128. Children were published at attempt completion before the parent could be internally wounded. Samples now retire with logical EXEC; active slices transfer to replacement child Ops using existing map nodes, excluding parked intervals and adding no allocations to the off state. The exact-count check and its red receipts are retained in `docs/wave8/jobs/execfair-private-helpers.*`. The final directed `execfair` job passes all eight legs (`execfair-directed-windows`, POST `488ad56d`).

The first direct `gates_test.py` run overlapped compile-only work and serverless traces and hit scheduler-fixture deadlines (12 failures, all timeout-led). This is failed evidence, retained at `build/wave8/gates-test.log`. The quiet rerun passes all 72 tests in 91.4 seconds, without changing tolerances (`docs/wave8/gates-test-final.{json,log}`). The gate's `abba_selftest` also passes in 346.4 seconds against a throwaway source copy with totals 806/823; its 660-second row budget is unchanged. The actual `tests/gate.sh` totals remain 798/815.

### Timing, parking and ownership review

- Latency stores belong to physical thread IDs and are never named by a shard; shard migration does not leave a histogram pointer behind. Blocked and scatter commands accumulate active slices and retire once through the existing timing-selected hooks. Their parked interval is outside those scopes. The directed latency job covers timeout, actual wake, cross-owner commands, scripts, EXEC children, RESP2/3 and tracking transitions.
- Tracking enables owner timing by disarming the local-read admission predicate at the live-config boundary (`latency_reads_local_ = read_local_enabled && !latency_tracking`). Both ordinary and R7 envelopes consume it. The shape test checks the read-local boot and same-buffer on/off transitions; the default-off path is separately checked for zero histogram allocations.
- WB4.1 observes completed replies at the IO pass boundary and retains the largest observed completion interval for the grace calculation. Its stack-local state is not transferred with a shard. Pending EXEC retries report work, including held/requeued attempts, so their IO cannot sleep with the only retry in its inbox. Executor fast polls and rotation use `execute_resumed`; ordinary owner parking retains the existing arm/recheck/wake protocol. The execfair legs require actual fast polls; IO-deferred legs require actual parking and wakeup.
- Lua helper calls stay inside the existing script sandbox and declared-key transaction machinery. The helpers add no shard ownership, claims or reader synchronization. The integration check verifies successful cross-owner Lua writes while EXEC queues contend, with helpers exercised in each script. Explicit script key conflicts remain legal TRYAGAIN replies.

### Compile-only inlining trials

The first pass surveyed all 29 pinned units in PRE and POST (58 IPA dumps), then compiled 103 candidate budgets (91 distinct object bodies) and scored linked bodies against the frozen headline and all five lane POSTs. It selected normal `main.o` 147838, db0 `rl2s.o` 167496 and db0 `xshard.o` 147307; the other incoming values were retained. The EXEC timing repair then changed both scatter translation units: a second 8-trial scan selected normal/db0 xshard budgets **148537 / 147343**. Raw commands, IPA starting sizes, every trial and linked-body scores are under `docs/wave8/budgets{,-timing}`. No rate was measured to select these budgets.

A second source was isolated: Lua OCC certification can replay scripts even on disjoint keys. Before the Lua fix, separate INCR/INCRBY counters showed EXEC at exactly 192 calls while 64 logical Lua calls produced 66–68 INCRBY samples. Nested script samples now retain command metadata and duration until outer-command retirement. A fresh activation replaces speculative child samples; EXEC retries discard old script children during normal attempt cleanup. The final script activation contributes child samples, while the parent includes active retry work. No new TLS word or locked server layout field is added.

The final directed check uses six EXEC and two script connections within the eight-command snapshot admission window. Natural contention witnesses fast polls. Separate fresh-state `TXN-PLACE-DEFER` and `SCRIPT-STAGE-DEFER` cases force the two retry mechanisms, require their counters to advance, and check exact histogram cardinality. Missing arming is retried on at most three fresh states and then fails. Earlier missing-window failures remain in the receipts; no missing window is accepted and no count tolerance is widened.

### Frozen binaries and command counts

| Arm | Path | SHA-256 |
|---|---|---|
| PRE | `/home/user/Projects/cx-wave8/build/tomokv-wave8-PRE` | `9af252ab89c4cad77787556b48bce9c41a3033cac8d79d721c02c5cadd6f6a99` |
| POST | `/home/user/Projects/cx-wave8/build/tomokv-wave8-POST` | `488ad56dd86bbb7f52c8cbf5b34070b81e3e782ef2b26adcbe788061cbc03509` |
| PAD-A | `/home/user/Projects/cx-wave8/build/tomokv-wave8-PAD-A` | `3683af2efc51666fbb2686cac26e7883fa6c86dc79e33428968c321361e86708` |

PRE is rebuilt from exactly `3700b51d7`; all 9,427 normalized function groups equal the supplied headline. POST is the integrated production build, with its 15-site map saved beside the frozen binary. PAD is **(A) behaviour twin**: unchanged PRE objects plus unreachable padding. It matches POST's `.text` address 129328 and size 8435415 bytes (156128 padding bytes). Function ordering/relative spacing and TLS/data contents come from PRE; section addresses relocate at link time. This controls aggregate text placement/size, not all cache-line/layout effects; the full link and object digests are in `docs/wave8/pad-a.json`. The only four strict PRE/PAD body differences are branches through the unsymbolized `.rlfence` section. Supplemental proof checks each fence's actual bytes, outgoing target and return target; all match (`docs/wave8/pad-identity/provenance.json`). The only new symbol is unreachable padding.

`docs/wave8/instructions/table.md` gives all 72 PRE/POST cells: GET, SET and INCR at batches 1/32, slowlog -1/10000, both modes and namespaces; MGET at batches 1/32 and MSET at batches 1/32 with both atomic settings. The 48 single-key cells add **zero** instructions (totals decrease through helper inlining). All 24 MGET/MSET cells have identical counts, with identical per-function counts. External-library call counts match throughout. Counts include named production TomoKV routines and inlined code, with exact reply/data checks; they exclude fixture glue and external library bodies and make no cycles/IPC/rate claim.

`make all`, all 45 `job_production_units` targets, both MDB parked/no-wake arms, and the blockfix cost target build successfully. All 49 concrete freshness checks pass; `docs/wave8/build/receipt.json` records commands and unchanged candidate digest.

### Complete linked-body review

The strict final inventory contains 9,868 groups: 8,151 equal headline, 1,110 changed groups equal a supplied lane POST, and 607 residual groups. Among the 78 command-hot groups, 64 equal headline and eight equal a lane. All GET/SET handlers are headline-identical. The remaining six command wrappers have identical instruction shapes; actual constant bytes, complete four-byte switch tables and ScriptWorkbench TLS fields/guards are verified separately (`docs/wave8/identity/hot-provenance.json`). The strict inventory is not relaxed to erase those differences.

Every changed group, including all clone occurrences and its reason, is listed in `docs/wave8/identity/reviewed-bodies.{md,json}`. The residual review includes 287 symbolic-reference-only differences, the six verified operand relocations, combined executor/IO dispatch, logical timing retirement, assertion diagnostics, registration/configuration and container instantiations. Seventeen remaining compiler-propagation groups retain their source location, complete instruction diff and all lane/headline call-site deltas; no single optimizer decision was isolated for those groups. The full 925-body hot selection includes every production body entered by the command traces. Identity is a proxy; these residual differences go to the maintainer's null rather than becoming a throughput claim.

The serverless probes' actual executed addresses are checked against their ordinary production links: 125/124 PRE and 122/121 POST function groups (normal/db0), with no unexplained difference. The few reference-only differences are resolved by exact constant bytes or every bounded switch destination, with opcode/target controls. PRE also resolves to the headline. Receipts: `docs/wave8/instructions/{provenance,constant-provenance,switch-provenance}.json`.

### Harness interactions found by the wider jobs

The original standalone core TSAN link omitted all six lualibs C translation units and failed with four undefined `luaopen_*` symbols. ASAN and read-local debug links shared the omission. All three now include the helper sources; `parbuild.sh` compiles C sources as C with the same sanitizer flags and includes Lua headers/amalgamated sources in its cache key. A directed C-linkage/header-invalidation check and the TSAN dependency inventory guard this integration.

Execindex's queue-specific ready path bypasses the finalizer overload patched by the old EX-batch negative control. That control still failed, but only later in OOM cleanup, so its expected witness was absent. The fixture retains the original lazy-finalization check and adds a fresh explicitly armed reservation followed by direct finalization. The planted missing cache update must fail at this new exact witness in both namespaces. These are harness changes; the frozen production POST is unchanged.
