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

FACT LEDGER: replacements retain ownership, ordering, lifetime, failure and caller
obligations. Added qualifications follow this base's code rather than copying
suggested replacements blindly. Removed wording is either the specific false
claim named in its row or retained in the replacement with a precise scope.

A7 complete: 10/10 source findings fixed; row 1 also has one out-of-scope glossary
occurrence. Remaining A8-A10 findings and final verification are pending.
No gate rows added or retired: EXPECT_QUICK / EXPECT_FULL remain unchanged.
