# Wave8b correctness evidence

Whole jobs use the gate partial-job interface. Row executions include repeated prerequisites; this is not a full-gate receipt.

| Invocation | Passing rows | Failed attempt rows | Result |
|---|---:|---:|---|
| [final-abba-selftest-count-repair](jobs/final-abba-selftest-count-repair.json) | 1 | 0 | PASS |
| [final-abba-selftest](jobs/final-abba-selftest.json) | 0 | 1 | setup repaired |
| [final-aof-1s](jobs/final-aof-1s.json) | 109 | 0 | PASS |
| [final-aof-2s](jobs/final-aof-2s.json) | 109 | 0 | PASS |
| [final-debug-epoll-1s](jobs/final-debug-epoll-1s.json) | 41 | 0 | PASS |
| [final-debug-epoll-2s](jobs/final-debug-epoll-2s.json) | 41 | 0 | PASS |
| [final-debug-uring-1s](jobs/final-debug-uring-1s.json) | 41 | 0 | PASS |
| [final-debug-uring-2s](jobs/final-debug-uring-2s.json) | 41 | 0 | PASS |
| [final-differ-epoll](jobs/final-differ-epoll.json) | 6 | 0 | PASS |
| [final-differ-uring](jobs/final-differ-uring.json) | 6 | 0 | PASS |
| [final-engine-epoll](jobs/final-engine-epoll.json) | 166 | 0 | PASS |
| [final-engine-uring](jobs/final-engine-uring.json) | 166 | 0 | PASS |
| [final-lanes](jobs/final-lanes.json) | 146 | 3 | source checks repaired |
| [final-multidb-epoll](jobs/final-multidb-epoll.json) | 25 | 0 | PASS |
| [final-multidb-uring](jobs/final-multidb-uring.json) | 25 | 0 | PASS |
| [final-replyoff-fused-epoll](jobs/final-replyoff-fused-epoll.json) | 3 | 0 | PASS |
| [final-replyoff-fused-uring](jobs/final-replyoff-fused-uring.json) | 3 | 0 | PASS |
| [final-script-aof](jobs/final-script-aof.json) | 2 | 0 | PASS |
| [final-source-repair](jobs/final-source-repair.json) | 7 | 0 | PASS |
| [final-tcl](jobs/final-tcl.json) | 6 | 0 | PASS |
| [final-watch-blocking-epoll](jobs/final-watch-blocking-epoll.json) | 5 | 0 | PASS |
| [final-watch-blocking-uring](jobs/final-watch-blocking-uring.json) | 5 | 0 | PASS |

Standalone gates_test exit: 0. Make freshness: 49/49.

The pre-comment and final POST binaries have identical runtime sections, program headers, entry point and symbols; only non-runtime debug/linker metadata and GNU build-id may differ. See comment-sync.json.

The original three source-check failures remain in final-lanes. The final-source-repair job reruns their complete owning jobs.

The initial ABBA self-test copy missed the FULL constant's trailing comment, omitted required fixtures, and symlinked build/, breaking exact-path controls. Its failed attempt is retained but is not accepted as proof. A complete new copy uses a real build directory, verifies 807/824, and passes the whole job; see selftest-setup-error.json and selftest-copy-count-repair.json.

NOT RUN: performance benchmarks, load generators and the full gate iteration are reserved to the maintainer.
