# IO refinement correctness proof

All runs use the gate's own job interface, server CPUs 80–87, load CPUs 88–95,
16 shards and ports 19800–19899. Split is 6:2; fused uses eight workers.
Each linked receipt gives the exact invocation and binary hash. These partial
job runs are not full-gate or performance receipts.

| Run | Arm | Passed / failed rows | Interpretation |
| --- | --- | ---: | --- |
| [pre-release-witnesses](proof/pre-release-witnesses/manifest.json) | pre | 39 / 7 | Intended PRE failures: four new rows, two stronger writeback rows and corrected DEBUG row |
| [final-directed](proof/final-directed/manifest.json) | post | 72 / 0 | PASS |
| [final-uring](proof/final-uring/manifest.json) | post | 204 / 2 | Two launch-tool failures; both complete jobs pass in final-native-checks on the same ELF |
| [final-native-checks](proof/final-native-checks/manifest.json) | post | 56 / 0 | PASS |
| [final-epoll](proof/final-epoll/manifest.json) | post | 51 / 0 | PASS |
| [final-forced-epoll](proof/final-forced-epoll/manifest.json) | post | 17 / 0 | PASS |
| [final-fused-uring](proof/final-fused-uring/manifest.json) | post | 46 / 0 | PASS |
| [final-fused-epoll](proof/final-fused-epoll/manifest.json) | post | 14 / 0 | PASS |
| [pad-a-witnesses](proof/pad-a-witnesses/manifest.json) | pad-a | 1 / 4 | Intended negative witnesses; causes audited in raw logs |
| [pad-a-wb-deferred](proof/pad-a-wb-deferred/manifest.json) | pad-a-wb | 1 / 1 | Intended negative witnesses; causes audited in raw logs |
| [pre-late-wake](proof/pre-late-wake/manifest.json) | pre | 16 / 1 | Intended negative witnesses; causes audited in raw logs |
| [pre-existing-epoll](proof/pre-existing-epoll/manifest.json) | pre | 14 / 1 | Intended negative witnesses; causes audited in raw logs |
| [pre-notify-uring](proof/pre-notify-uring/manifest.json) | pre | 7 / 0 | PASS |
| [pre-fused-uring](proof/pre-fused-uring/manifest.json) | pre | 13 / 1 | Intended negative witnesses; causes audited in raw logs |
| [pre-fused-epoll](proof/pre-fused-epoll/manifest.json) | pre | 13 / 1 | Intended negative witnesses; causes audited in raw logs |

The two failures in `final-uring` occurred before the intended server/ELF checks:
the launch logger exceeded an injected file-size limit, and an ELF tool received
the adapter script. `final-native-checks` reran both complete gate jobs with the
real ELF and passed 56 rows. The original failed records remain available.

Each engine's standard differential jobs passed 940 legs and all 32
execution/knob equivalence combinations. See [the exact plans and totals](differ-final-summary.json).
The standard plan excludes fused SORT; FLIP itself is split-only.

[The directed audit](directed-witness-audit.json) verifies all 16 intended PRE
failures and final POST passes. [Full PRE PAD-A](pad-a-witness-audit.json) retains
all 16 defects; [the exact-layout WB PAD-A](pad-a-wb-witness-audit.json) retains
all four deferred-IO failures. The added late-wake unit fails all six dispatch
variants on PRE and on the interim implementation, then passes them on final POST.

Every archive is verified against its manifest before redundant detailed copies
are removed. Ledgers and per-job summaries remain readable beside the archive.
Launch journals are consolidated only after the job exits, with each original
record checked and hashed in the corresponding `*-launches-receipt.json`.
Earlier gate diagnostics are retained in
`proof/legacy-build-diagnostics.tar.gz`, with their file hashes in
`proof/legacy-build-diagnostics.json`. Original `build/gate-run.*` paths in
receipts identify the historical run; use the archived evidence after cleanup.
