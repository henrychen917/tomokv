# Wave 8 landing

## wave8 integration

Work in progress on `cx-wave8`, base `3700b51d7`; no push. All execution is pinned to CPUs 64–95, builds use `-j32`, and correctness listeners are restricted to ports 20000–20099. Performance campaigns and the full iteration remain maintainer-owned.

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

Builds, instruction counts, directed interactions and correctness receipts will be recorded below. No throughput claim is made.

### Tcl known-failure reconciliation

Nineteen named assertions are promoted: thirteen `LUA-HELPER-LIBS` and six `LATENCY-HISTOGRAM-ABSENT`. The required inventory becomes 1,643 assertions per mode, with 405 named known failures. The unchanged upstream latency-monitor file assumes Redis's default tracking=yes; its manifest explicitly enables tracking for that file only. The production default remains no, with independent default/off-allocation coverage. Arbitrary server flags and disabling tracking in that file are rejected by directed manifest controls.

Other roots were reviewed: execindex changes claim lookup and scheduling, not MULTI OOM admission, command policy, blocked-key wake order or WATCH's spurious invalidation root. IO parking changes idle work detection, not blocking command semantics. Readability and harness repairs change no command replies. Latencyfix adds histogram child samples but does not implement the pre-existing `SLOWLOG-EXEC-BODY-NOT-LOGGED` mechanism; that named failure remains. Passing names will be confirmed through the merged gate Tcl job and its planted regression control.

The first Tcl run verified all promoted names but caught a manifest multiplicity error: each of the thirteen Lua names runs twice. The exact multiset therefore grows by 32 assertions, not 19. The first run also retained two cross-client-order failures: MONITOR saw the polling client's INFO before the blocked client's BLPOP, and an unblocking LPUSH overtook another client's EXEC, causing its WATCH to abort. Neither is hidden or newly skipped; final isolated runs will retain their own outcomes.
