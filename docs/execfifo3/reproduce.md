# Reproducing the execfifo3 proof

Use this worktree, CPUs 96–111 and ports 20600–20699. Every live runner sets
`LC_ALL=C`. The commands below are correctness/finite fixtures; none starts a
throughput benchmark. Do not overlap builds, traces or perf with the timing
sensitive harness self-tests or sustained fairness matrix.

The frozen images and their hashes are in `arms.json` and `SHA256SUMS`.
Production code is the three-value Makefile change at `4248cfd40`; later commits
contain evidence and tooling. The release candidate is `build/execfifo3/POST`.
`POST-final` in fixture filenames denotes that same final production link.

The native PRE is byte-identical to execfifo2's original; the reconstructed PRE
used to link fixtures and the common-image control is retained separately as
`PRE-rebuilt.gz`. Its text is identical, but its INFO revision strings identify
the build checkout. `pre-loadable-comparison.json` records every allocated-section
difference. The recorded fixture counters are unchanged by the native-baseline
selection.

The superseded stage-1 images, reconstructed PRE and original reference copies are retained as
`.gz` files to leave room for sanitizer builds. `image-archives.json` records
their compressed and original hashes. The five final arms remain uncompressed
and are the entries in `SHA256SUMS`. The archived original PRE also has its
separate `original-reference-SHA256SUMS` receipt.
To inspect the older images or run their original `stage1-SHA256SUMS` check:

```sh
taskset -c 96-111 python3 tools/execfifo3_archive_intermediates.py --restore
taskset -c 96-111 sha256sum -c docs/execfifo3/stage1-SHA256SUMS
taskset -c 96-111 python3 tools/execfifo3_archive_intermediates.py
```

The linked probes are retained losslessly as `probe.gz`; `probe-archives.json`
records both compressed and original digests. Restore only the needed family
to limit peak disk use. Recount the complete owner and parser scopes with:

```sh
taskset -c 96-111 python3 tools/execfifo3_probe_archive.py --restore --kind commands
taskset -c 96-111 python3 tools/execfifo3_scope.py --kind commands --arms PRE,POST-final --trace-only --fresh --workers 8
taskset -c 96-111 python3 tools/execfifo3_probe_archive.py --kind commands
taskset -c 96-111 python3 tools/execfifo3_probe_archive.py --restore --kind memory
taskset -c 96-111 python3 tools/execfifo3_scope.py --kind memory --arms PRE,FIFO,POST-final --trace-only --fresh --commands GET,SET,INCR,PARSE-GET,PARSE-SET,PARSE-INCR --batches 32 --workers 6
taskset -c 96-111 python3 tools/execfifo3_input_scope.py
taskset -c 96-111 python3 tools/execfifo3_perf.py --arms PRE,FIFO,POST-final
taskset -c 96-111 python3 tools/execfifo3_perf_summary.py
taskset -c 96-111 python3 tools/execfifo3_probe_archive.py --kind memory
taskset -c 96-111 python3 tools/execfifo3_scope_consistency.py
```

The trace counts named production Tomo routines in the linked image, including
their inline code, and excludes fixture glue and external library callees.
Memory counts are explicit x86 operands, not implicit stack accesses of calls,
returns, push or pop; prefetch hints are also excluded. Object-line identities
use actual allocation alignment. These counts do not model hardware cache fills.
The TLS diagnostic also classifies the parser's read buffer and `FS` region.
Each trace verifies the probe digest and exact fixture replies. Perf counts
the complete process, including setup and external libraries; it uses no rates.
The memory/parser fixture uses atomic 1. The original owner-command fixture
also covers both atomic settings for MSET.

Capstone 5.0.9 is installed locally in `build/execfifo3/python` for GDB's Python
interpreter. The probes use production objects first in link order, with only
the executable entry renamed; the fixture follows them so its COMDAT definitions
do not supersede production. Exact compile/link commands and production/probe
hashes are in the `*-build.json` receipts.

To rebuild probes after cleanup, first rebuild the retained PRE/FIFO source
archives with `taskset -c 96-111 make -C build/execfifo3/pre-source -j16 all`
and the corresponding `fifo-source` command, then run the scope driver without
`--trace-only`. Intermediate objects and generated symbol-range files were
deleted after proof completion to respect the disk budget; their hashes are
retained in `intermediate-cleanup.json`. Regenerating frozen release/PAD images
with `tools/execfifo3_artifacts.py` likewise requires restoring the original
reference copies, rebuilding the PRE objects and a fresh main `make all`;
it changes receipts and must not be confused with the existing
frozen images.

The live driver imports all 42 unchanged groups from `execfifo2_validate.py`.
For example:

```sh
taskset -c 96-111 python3 tools/execfifo3_validate.py fifo-contract directed fairness at412 txn-uring txn-epoll differ-uring differ-epoll
taskset -c 96-111 env LC_ALL=C GATE_TEST_PORT=20699 python3 tests/gates_test.py
taskset -c 96-111 python3 tools/execfifo3_negative.py
taskset -c 96-111 python3 tools/execfifo3_control_smoke.py
taskset -c 96-111 python3 tools/execfifo3_freshness.py
```

`validation/runs.json` records the full group list actually run, exact gate job
filters, allocation, environment, executable digest and result of every attempt.
The coverage checker requires all 42 groups and their full FIFO/C1/fairness,
AT4.12 and differential leg inventories. The proof recorder archives completed
job ledgers and result logs. The negative controls modify only a stopped GDB
inferior and require the intended assertion and exit 1; no broken binary or
source is published.

`completed-gate-cache-cleanup.json` records the hashes of discarded compiler
caches and generated exbatch control copies after their jobs completed. The
required root unit binaries remain available. The exbatch checker regenerates
missing control copies from those units; gate jobs `rldbg` and `core_tsan_build`
regenerate their compiler caches through `tests/parbuild.sh`.
After all four sanitizer groups passed, their compiler cache was also removed;
`final-cache-cleanup.json` records each discarded file. The sanitizer executable
and result logs remain. The selected `asan_batteries` job regenerates that cache.
The final five native images, all 16 archived images/probes, proof inputs and
negative-control units were rehashed in `final-integrity.json`; archived bytes
were streamed through gzip and checked without restoring duplicate files.

Captured compiler/GDB/protocol logs are retained verbatim, including meaningful
trailing spaces. Source whitespace checks exclude `docs/execfifo3/validation/`;
the archived logs are checked by their byte digests instead.

`GATE_PROOF_NO_RATES=1` leaves the quantitative atomic floor, atomic RYOW rates
and stream/xmove rate checks to the maintainer while retaining correctness
checks. `flip_saturated`, generic ABBA cells, EXEC/depth/script-storm merit,
load generators and the full iteration are not part of this runtime proof.
