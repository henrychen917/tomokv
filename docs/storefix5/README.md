The current result and measurement request is [MEASURE-REQUEST-storefix5.md](../../MEASURE-REQUEST-storefix5.md).
All paths below are relative to this directory. Binary identity, rather than a
filename containing “final” or “release”, determines which candidate a receipt tests.

| Evidence | Current receipt |
|---|---|
| Frozen PRE, POST and PAD-A | `ARMS.sha256`, `pad-a.json` |
| Fresh root executable matches frozen POST code | `release-code-identity.json` |
| Production builds and freshness | `production-units-release.json`, `freshness-final.json`, `final-audit.json` |
| No added maxmemory-off instructions | `counts/pre`, `counts/pre-insert`, `counts/retirement168000-full`, `counts/retirement168000-insert` |
| Enabled maxmemory GET-hit / SET-insert costs | `counts/pre-memory`, `counts/retirement168000-memory` |
| Finite RANDOMKEY and APPEND curves | `curves-release` |
| Final 32-boot RANDOMKEY distributions and idle-accounting observations | `randomkey-final-distribution.json` |
| Finite memory matrix | `memory/pre`, `memory/release`, `memory/redis` |
| APPEND PRE failure / POST pass | `append/pre-frozen-result.json`, `append/post-retirement-result.json` |
| Shared correctness affinity rejection and fix | `harness-pin-review.json`, `mode-equivalence-pin-final.log` |
| Full-retirement-ring PRE failure / POST pass | `retirement-pre-result.json`, `retirement-after.json` |
| Independent sampler visibility and retirement negative controls | `retirement/controls.json` |
| Cold helper layout in both namespaces | `cold-layout-final.json` |
| Revised notification fixture on PRE/POST, both modes | `notification-proof.json`, `gate-notify-*-final.log` |
| FIFO deadline PRE/POST comparison | `fifo-pre-post-final.json` |
| PAD-A retains PRE defects | `pad-final-1s.json`, `pad-final-2s.json` |
| Gate jobs, Tcl assertion failures and public row ledgers | `gate-summary.json`, `gate-*-final*.log` |
| Full proof orchestration | `final-proof.json`, `quiet-final-retry.json`, `finish-proof.json`, `inventory-proof.json`, `notification-proof.json` |

Historical failed and superseded trials are retained. In particular, `final-1s.json`
and `final-2s.json` are the earlier two-item candidate before idle accounting, and
their idle witness failures are expected. `*-before-retirement` receipts and the
`09367b85…` candidate precede the full-ring expiry correction. Duplicate log copies
name the same artifact directory and are not additional tests. Stopped differential
runs are not complete matrix passes.

`gate-receipts.tar.gz` preserves raw logs, receipts and wire transcripts under their original worktree
relative paths; `gate-receipts.json` lists their hashes. Binaries and preloaded
test data are excluded. `data-cleanup.json` records deletion of completed jobs'
persistence data. The frozen executables remain in `build/storefix5/`.
