# Final-arm verification

Production source: `bcbe1650fd`; PRE: `9d6ab5526`.
These are selected gate jobs, not a full gate/iteration receipt. Repeated rows
across selections are not independent coverage. Every completed delivery
archive records the unchanged POST SHA-256 from `arms.sha256`.

| Selection | Run | Pass | Fail | Evidence |
|---|---|---:|---:|---|
| Core/sanitizer and directed units | `gate-run.3LCQyY` | 21 | 0 | [ledger](gate-units-uring-delivery.ledger), [archive manifest](gate-units-uring-delivery-archive.json) |
| New live rows; 208 armed episodes | `gate-run.FMZMQT` | 4 | 0 | [ledger](gate-new-uring-delivery.ledger), [archive manifest](gate-new-uring-delivery-archive.json) |
| Initial native regression; strict-check failures retained | `gate-run.ksydPR` | 476 | 2 | [ledger](gate-regression-uring-delivery.ledger), [archive manifest](gate-regression-uring-delivery-archive.json) |
| Corrected controls and restored stream memory assertions | `gate-run.IWv7UP` | 144 | 0 | [ledger](gate-controls-uring-delivery.ledger), [archive manifest](gate-controls-uring-delivery-archive.json) |
| Epoll regression | `gate-run.zTNT0e` | 195 | 0 | [ledger](gate-regression-epoll-delivery.ledger), [archive manifest](gate-regression-epoll-delivery-archive.json) |
| Supplementary modes, upstream Tcl and feature matrix | `gate-run.O2arLe` | 82 | 0 | [ledger](gate-scope-uring-delivery.ledger), [archive manifest](gate-scope-uring-delivery-archive.json) |
| Supplementary epoll modes and feature matrix | `gate-run.39Uwiy` | 69 | 0 | [ledger](gate-scope-epoll-delivery.ledger), [archive manifest](gate-scope-epoll-delivery-archive.json) |
| Standard differential, io_uring | `gate-run.xuUi4m` | 6 | 0 | [ledger](gate-differ-uring-delivery.ledger), [archive manifest](gate-differ-uring-delivery-archive.json) |
| Standard differential, epoll | PENDING | — | — | — |

The native regression failures were source/inventory expectations: writeback
anchors had moved into the FLIP helper, and one DB0 callback was newly outlined.
The corrected selection retains exact source guards and compares all 326
required bodies. Its negative controls include removing/changing the additional
callback and four mutations of the new FLIP source sites. See
[regression-controls.md](regression-controls.md). The original failed receipt
is retained; no failed run is relabelled green.

The final gate-harness run passed **77/77** tests plus its embedded 14 process
tests: [log](gates-test-closeout.log), [command and hash](gates-test-closeout.json).
The core fixture passed ASAN/UBSAN and TSAN with all twelve new armed state
witnesses. Main-command scopes passed **80/80** PRE/POST comparisons with no
added instructions: [full table](command-counts.md). The
[frozen-source receipt](frozen-source.json) records twenty exact PRE/POST source
equality checks, including the mask implementation, executor transitions,
listener and session handover, dispatch pause and precommit deadline.

The new live rows contain **208 armed episodes from 219 fresh boots**. Eleven
unarmed attempts triggered bounded fresh-state retries. Every attempted PING
stayed below one second; maximum PING was 53.270 ms, maximum FLIP 53.327 ms.
All 32 SIGTERM/single-SIGINT witnesses saved and reloaded 1000/1000 acknowledged
keys. See [all attempts](post-attempts.json) and [post witnesses](post-witness.md).

The feature matrix checks the selected network engine through INFO; both
engines cover its 32 switch combinations and three topology cases. Client
compatibility also selects and verifies the engine. Other directed jobs retain
their own declared leg matrices; the new FLIP rows cover the full sixteen-leg
2s engine/read-local/atomic/database product.

The io_uring standard differential plan passed 938 suite/seed legs and all 16
mode-equivalence cells, using permanent seeds 7, 19, 20, 23 and rotating seed 21.
Its four atomic-mode lifetimes and equivalence part each have a completion
receipt; [differential summary](differential.json) retains the plan and coverage.
Epoll differential, final freshness and PAD-A receipts: PENDING.

NOT RUN: performance/ABBA/full iteration, the `flip_saturated` load generator,
`atomic_floor`, and LMOVE size-ratio timing; these remain maintainer-owned.
The standard differential harness also excludes SORT in armed-fused mode
because that suite requires split 6:2; the standard plan requires it for every
seed and atomic mode in split mode on both engines. Exclusions are not passes. The upstream
Tcl job uses its unchanged passing-subset manifest, not the whole upstream suite.

**STOP:** the unconditional signal-save deadline during an arbitrary stuck
FLIP needs the frozen ownership handshake to change. Only the repaired output
wedge is claimed resolved; see [evidence and proposal](shutdown-stop.md).
