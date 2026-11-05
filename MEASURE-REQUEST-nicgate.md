# NIC regression tier repair

## nicgate

Worktree `/home/user/Projects/cx-nicgate`, branch `cx-nicgate`, based on published
main `db697f25d4e1d46824d5ee2f2372d5bfda63e053`. Implementation commit:
`6282ecaf00`.

`tests/gate.sh` now selects an explicit `GATE_NIC_CLI`, otherwise an executable
`/usr/bin/redis-cli`, otherwise an executable `$REDIS74_ROOT/src/redis-cli`.
An explicitly set but missing, nonexecutable, directory, or empty override is
reported as invalid; unset it to enable automatic discovery. Paths with spaces
are covered. The NIC section no longer reads `GATE_SCRATCH` or a session path.

The supplied baseline already prints a generic `SKIPPED (no rig/refs)` note.
It now uses the same informational `say` printer for a visible `NOT RUN` note
that names the missing helper, client, or reference file. A failed link check
names that check and retains the helper's detailed `LINK-FAIL` output.

The existing -3% comparison, kernel-pin WARN, reference geometry, cleanup, and
conditional ledger behavior are unchanged. `tests/gate_refs.txt` is unchanged;
re-pinning remains an owner decision. No `src/` files changed.

Counting: `EXPECT_QUICK=1212` and `EXPECT_FULL=1229` remain unchanged. The existing
NIC row at `tests/gate.sh:7624` is after the quick-tier exit at line 7478. It still
adds one optional row only when `NIC_CHECKED=1`; the full total remains
`EXPECT_FULL+NIC_CHECKED`. Missing prerequisites and failed link checks add no
ledger row. This lane has DQ=0 and DF=0; no count or fixture update is needed.

Proof commands were pinned to CPUs 96-111 where applicable:

| Check | Result |
| --- | --- |
| `python3 tests/gates_test.py NICPrerequisites NICOwnership -v` | PASS, 6 tests |
| `python3 tests/gates_test.py` | PASS, 83 tests in 199.432 s |
| `python3 tests/gate_ledger_fixture.py --self-test` | PASS, 12 tests |
| `python3 tests/gate_ledger_fixture.py` | PASS, 1229 source-declared rows agree |
| `bash -n tests/gate.sh` | PASS |
| `git diff --check` | PASS |

The full harness output is retained in `build/nicgate-gates-test.log`.

Four new `NICPrerequisites` tests execute the actual NIC section with a temporary
helper, filesystem fixtures, and stubbed NIC operations. They cover precedence,
unusable candidates, explicit override failure, each missing prerequisite,
link failure, kernel match/mismatch, and the existing optional row count. The
production comparison runs on synthetic values: 970 against 1000 passes,
969 fails, and absent rate output fails. These are not measured rates.

As a negative control, the missing-prerequisite test was given the baseline
`gate.sh` text through a temporary Python mock. All six assertions failed on
the old generic `SKIPPED` output, as expected. The checkout was not modified.
The log is `build/nicgate-baseline-control.log`.

A file-only evaluation of the production resolver on this host, with
`GATE_NIC_CLI` unset and an unavailable Redis tree, produced:

```text
Host file-only resolution: client=/usr/bin/redis-cli; reason=ready
```

It stopped before the kernel/link checks or any NIC operation. Separately,
the offline fixture demonstrated these production notes (spacing compacted):

```text
NIC regression cells NOT RUN (no NIC client binary; set GATE_NIC_CLI)
NIC regression cells NOT RUN (missing tests/niclib.sh)
NIC regression cells NOT RUN (missing tests/gate_refs.txt)
LINK-FAIL fixture link unavailable
NIC regression cells NOT RUN (NIC link check failed; see LINK-FAIL above)
```

All four cases left `NIC_CHECKED=0` and produced no ledger rows. Reproduce the
offline demonstration with `python3 tests/gates_test.py NICPrerequisites -v`.

No live NIC measurement is requested from this harness repair. The section has
no standalone invocation, and its unchanged matrix needs up to 32 server cores
plus 64 load cores, which cannot fit CPUs 96-111. No server was built or started,
and no gate, benchmark, or load generator was run. No PRE/POST/PAD binaries were
created. Nothing was pushed.
