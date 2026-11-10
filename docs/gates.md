# Testing and publication gates

Run commands from the repository root. Unit programs, correctness batteries,
reference fixtures, and publication instruments are maintained in `tests/`.
`tests/gate.sh` is the publication entry point. Full gates start servers and
load generators, so schedule them on a quiet machine with the required
reference tools and CPU/network resources.

## Serverless checks

```sh
make -j16 unit
python3 tests/docs_drift.py --self-test
python3 tests/gateplan.py --self-test
python3 tests/gate_ledger_fixture.py
```

`make unit` runs the parser, reorder, controller, read-local ring, fence, and
wait-state units. It also builds supplementary scan/fence controls used by the
gate. Individual serverless correctness programs have Makefile targets such
as `build/store-regression` and `build/netcmd-unit`; their section selectors are
listed in their source files. The full gate supplies those selectors and runs
additional sanitizer and negative-control variants.

A standalone protocol battery usually expects an already running server;
other batteries own their test servers. Inspect each program's help and the
gate invocation before running it.

## Gate tiers

| Command | Scope |
| --- | --- |
| `tests/gate.sh iteration` | All full correctness checks and the smoke performance subset; the default tier |
| `tests/gate.sh push` | Full correctness and all regression cells, with release receipt requirements |
| `tests/gate.sh release` | Same complete requirements as `push`; `full` is a legacy alias |
| `tests/gate.sh quick` | Legacy correctness diagnostic; does not replace the publication gate |
| `tests/gate.sh perf --dry-run` | Print the network-IO product and command arguments without starting workloads |

`--help` describes resource options. The planner accepts separate server/load
CPU lists and SMT lists, a port range, and reference/candidate binary paths.
For example, to inspect the reviewed 32-thread performance geometry without
running workloads:

```sh
tests/gate.sh perf --dry-run \
  --server-cores 0-31 --server-smt '' \
  --load-cores 32-127 --load-smt '' --ports 27400-27499
```

Correctness slots use eight physical server cores and an explicitly derived
IO/executor geometry, ordinarily six IO plus two executor threads and 16
shards. Reproduce a failed row with its recorded geometry. Tests exercise
split/fused execution, both atomic modes, local reads, and the applicable
network engines. Partial job selection via `GATE_ONLY_JOBS` produces a separate
partial ledger and cannot earn a release receipt.

## Dependencies and reference data

Besides the server build dependencies, individual batteries require Python 3,
Redis CLI, a pinned Redis 7.4 source tree and built server, and tools used by
the selected row. `REDIS74_ROOT` supplies the ordinary oracle;
`REDIS74_TLS_ROOT` supplies the TLS oracle. The gate preflight identifies
missing reference components. Performance tiers require their load generators
and the NIC rows require the configured 25GbE network-namespace rig; this
infrastructure is external to the repository.

Keep the gate's reference and expectation data with its scripts:

- `tests/fixtures/` contains Redis reproduction inputs, source/command
  expectations, assertion pins, reorder inventories, and ledger labels.
- `tests/headline_cells.txt` and `tests/netio_cells.txt` define the performance
  cell inventories; `tests/gate_refs.txt` contains NIC references.
- `tests/standing-null/` and its registry carry the content-addressed control
  data read by the publication instrument.
- `tests/survey/` contains the native survey client and Python entry points
  whose self-tests are a publication-gate row. These remain gate dependencies
  even though they can also collect measurements.
- `tools/` holds build helpers, source-control generators, and drivers used by
  the Makefile or retained tests. Disposable control builds remain under
  `build/`; they do not modify server sources.

Generated run artifacts belong in `build/`. Local gate timing/receipt history
lives in `.gate-history/`, which survives `make clean` and is ignored by Git.

## What a passing gate means

Correctness checks require witnesses that the intended mechanism ran. Missing
arming, denied required DEBUG hooks, or absent reference data must not silently
become passing rows. Negative controls check that selected detectors reject
broken mechanisms. `EXPECT_QUICK` and `EXPECT_FULL` are maintainer-owned ledger
counts; they are not values to adjust merely to obtain a green run.

The performance instrument compares candidate and reference in the same
session. It binds measurements to the current instrument, cell inventory,
binaries, placement, and standing-null evidence. A push/release additionally
requires a source/binary-bound local receipt and trusted baseline/null inputs.
Source or harness changes require fresh applicable evidence; historical
results are not a receipt for a changed tree. See
[gate_receipt.py](../tests/gate_receipt.py) and
[abbagate.py](../tests/abbagate.py) for the executable contracts.

The optional pre-push hook delegates to the receipt validator:

```sh
git config core.hooksPath .githooks
```

The gate's own module documentation and `--help` describe explicit baseline
and null promotion. Promotion is a maintainer action after reviewing the
completed evidence; cleanup does not promote or refresh any reference data.
