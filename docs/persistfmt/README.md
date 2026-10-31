# persistfmt evidence index

The lane report is [MEASURE-REQUEST-persistfmt.md](../../MEASURE-REQUEST-persistfmt.md).
`arms.json` / `arms.sha256` bind the three delivered binaries. The final instruction
receipts are **`counts/PRE` versus `counts/FINAL4`**, summarized without dropped
cells in `instructions.tsv` and checked by `count-verdict.json`.

Earlier census directories are retained as rejected/superseded experiments:

| Label | Disposition |
|---|---|
| POST | Initial implementation; db0 MSET and snapshot-load instruction regressions |
| FINAL | Outlined teardown in both namespaces; normal MGET/MSET regressions |
| FINAL2 | Counts pass, but broad loader flattening adds excessive text; discarded |
| FINAL3 | Smaller loader, but omitted budget adjustment makes production load cost regress |
| FINAL4 | Final production Makefile and source; all 80 command cells and both snapshot per-key slopes pass |
| TRIAL, outline, tuned-budget | Bounded dispatcher/compiler experiments, not delivered arms |
| loader2-* | Loader experiments under default compiler budgets, not production receipts |
| budget-* | Bounded trials with explicit production-style compiler budgets |

The initial concurrent loader trial shared a temporary ranges filename and is
invalid. Its count files were deleted; `loader-trials.json` records the reason.
The corrected loader2 trials used a separate real directory for each executable.
The final PRE/FINAL4 instruments always use distinct directories per arm and
namespace. No invalid trial contributes to the final verdict.

`snapshot-ipa.json` records compiler-estimated unit growth; `snapshot-budgets.json`
records the selected budgets and hashes of discarded compile trials.
`layouts.json` reads the locked types and persistence/Server layout from all three
frozen binaries. `pad-build.json` records the build-only behavior twin.

Correctness receipts are `validation.json`, `validated-*.log` and the named gate
archives in `validation-archives.json`. `tools/persistfmt_validate.py` invokes
whole jobs through the real gate interface and preserves all later phases after
a failure. No performance phase, full iteration, load generator or throughput
claim is included. Earlier `post-*` and `final-directed*` logs are intermediate
receipts; their failures/retries remain visible. The intentionally aborted
`final-matrix-uring` run stopped during rebuilding and is not a correctness result.

`gates-test.log` is the first scheduler self-test attempt under compilation/trace
contention; `gates-test-final.log` is the quiet 76/76 pass. PRE witnesses and the
original 960-run S1 result are retained in the archived gate runs. Final validation
repeats those S1 rows on the delivered POST bytes.

`deleted-*.json`, archive manifests, and debug-compression receipts account for
disk cleanup. Only completed-job data and superseded arms were removed. Fresh
unit executables may have compressed debug sections; their code sections are
unchanged. Delivered PRE/POST/PAD-A binaries are not debug-rewritten. The first
compression sweep changed executable mtimes and invalidated three aggregate
readiness checks (wb-rule, wbland, persistfix). `freshness-initial.json` records
that artifact problem. The extra gate phases rebuild the real targets and rerun
the affected AOF framing job; no readiness marker is manufactured. Further
cleanup removes completed data only and does not rewrite unit executables.
