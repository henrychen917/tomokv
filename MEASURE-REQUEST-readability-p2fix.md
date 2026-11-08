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
| readability-a8-comment-audit.md | 2 | **fixed**: the size assertion pins FlatStore's 944-byte share of Shard's gate geometry; atomic_torn is not the size checker (`src/store/flatstore.h:3144`, `src/core/shard.h:587`). |
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

FACT LEDGER: replacements retain ownership, ordering, lifetime, failure and caller
obligations. Added qualifications follow this base's code rather than copying
suggested replacements blindly. Removed wording is either the specific false
claim named in its row or retained in the replacement with a precise scope.

A7-A8 complete: 28/28 source findings fixed; A7 row 1 also has one out-of-scope
glossary occurrence. Remaining A9-A10 findings and final verification are pending.
No gate rows added or retired: EXPECT_QUICK / EXPECT_FULL remain unchanged.
