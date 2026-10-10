## ttlclean

TTL sidecar experiment **closed; inline TTL retained**. Worktree and branch:
`/home/user/Projects/cx-ttlclean`, `cx-ttlclean`. PRE is
`4897ca189fb54a0bd2ad2e4085ae7aacbbc3207e`; production changes are committed as
`4392f0061` and `05776d837`. No push.

The owner's 2026-10-09 mainline measurements rejected the sidecar: 6.4% slower
for TTL SET p32 and 7.8% slower for TTL GET:SET 1:1; the PAD-B inverse control
(kind B: sidecar behavior plus padding restoring inline text size) was
7.1% / 5.8% slower. All three arms were correct and ordinary traffic was
neutral. These are supplied verdicts, not new measurements from this lane.
All **140 files under `docs/deadswitch/` remain unchanged**, including the
historical arm builders and receipts.

Removed the selector macro/constant, deadline-array allocation and accounting,
deadline lookup helpers, deadline migration/stores, owner lookup selection,
and sidecar-only allocation-failure cleanup. Removed the sidecar Makefile
recipe, gate build plumbing, test arm and tool invocation. Updated the live
architecture description. No active `ttl-sidecar` or `ttl-pad-b` arm remains.
The inline sentinel and hash-only expiry attention index remain production code.

The existing insertion signatures retain their unused deadline arguments to
preserve GCC's default code generation. The raw insertion ignores the argument;
there is no deadline array or selectable implementation. Removing the unused
arguments changed GCC's inlining decisions, so that extra API cleanup was not
retained. The existing state accessor spelling and source whitespace also remain
stable; the `make_word` assertion is still at line 2280, preserving its compiled
line-number argument. Compiler flags and inlining budgets are unchanged.

**Default PRE versus POST identity** (GCC 13.3.0, normal Makefile flags/jemalloc):

| Check | PRE | POST | Result |
|---|---:|---:|---|
| Production objects, both namespaces | 100 | 100 | Same inventory |
| Hot bodies, `tomo` | 601 | 601 | 601 identical |
| Hot bodies, `tomo_db0` | 603 | 603 | 603 identical |
| Full bodies, `tomo` | 8,391 | 8,391 | 8,391 identical |
| Full bodies, `tomo_db0` | 7,902 | 7,902 | 7,902 identical |
| Full inventory's hot selection, including executor run bodies | 1,208 | 1,208 | 1,208 identical |
| Command handlers | 1,210 | 1,210 | 1,210 identical |
| `.text`, bytes | 7,582,188 | 7,582,188 | Identical contents and placement |

**Zero changed emitted bodies**, including selector plumbing. The unmodified
deadswitch checkers compare opcodes and resolved relocation targets. Every
loadable section's contents, address, size and alignment match except the GNU
build-ID note. The full debug ELF hashes differ. All named field offsets and
sizes checked by the layout tool match in both namespaces, including the eight
locks: Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944,
Rob<64> 192, AtomicEntry 144, Config 624. No PAD or performance measurement is
needed for an identical runtime image.

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/ttlclean/pre/tomokv` | `a0369acc0747141a4e097d4b6a577fd8770c7d1095fcb803cab86522c560683c` |
| POST | `build/tomokv` | `3aaec5b6814548c32fd698119f41376662d30eded6440a7b25857289cf831f59` |

Identity receipts: [hot log](docs/ttlclean/hot.log),
[full summary](docs/ttlclean/full/summary.json),
[complete body inventory](docs/ttlclean/full/bodies.json.gz),
[empty changed-body list](docs/ttlclean/full/changed-bodies.json),
[linked sections](docs/ttlclean/linked.json),
[layouts](docs/ttlclean/layouts.json), and
[source audit](docs/ttlclean/source-audit.json).

**Proof runs**, confined to CPUs 112–127 with `taskset -c 112-127`:

- `make all`: PRE and POST passed. Exact commands/compiler and compressed logs
  are indexed in [proof.json](docs/ttlclean/proof.json).
- Every target in the gate's `job_production_units` passed: **28/28** top-level
  production-unit targets, including their control prerequisites, plus both
  binaries from `mdbqsbr-live-arms`. All 28 targets passed the gate's own
  `make -q` freshness check after the build. The exact target list, commands,
  exit codes and compressed compiler logs are indexed in
  [production-units.json](docs/ttlclean/production-units.json).
- `python3 tests/gates_test.py`: **66/66 passed**, plus its nested 14/14 subset
  tests. Ledger fixture self-tests: **10/10 passed**; source declarations and
  the fixture agree on all 528 full rows. `bash -n tests/gate.sh` passed.
- The adapted inline `deadline-allocation-failure` storage regression passed.
  A throwaway control raised only ExpireIndex's growth trigger from 70% to 90%,
  preventing the fixture from opening the growth-allocation window. It failed
  at `expiry-index growth allocation failed`, as required. The production
  trigger stays 70%. [Positive](docs/ttlclean/deadline-allocation-failure.log),
  [negative control](docs/ttlclean/no-growth.json).
- TTL differential matrix: **32/32 legs passed, zero differences** against the
  pinned vanilla Redis **7.4.10** oracle: `edgetime` + `hexpire`, seeds
  **7, 19, 20, 23**, atomics **0 and 1**, split and armed fused. Both fused
  read-local execution witnesses also passed (239 / 127 peak hits).
  Split: 16 pass, 0 fail; fused: 18 pass, 0 fail including those two witnesses.
  [Matrix receipt](docs/ttlclean/differ.json),
  [split log](docs/ttlclean/differ-split-6to2.log),
  [fused log](docs/ttlclean/differ-armed-fused.log).

The historical deadswitch command supplied `--ratio 3`; the current parser
rejects that spelling before starting a split server. The initial failed
invocation and missing-coverage error are retained in
[its log](docs/ttlclean/differ-split.log). The completed split proof uses
`--ratio 6:2`, 16 shards and eight target cores (112–119). The oracle uses CPU
120 and the client uses 121–127. Fused uses eight cores with `--read-local 1`;
the ratio argument is unused by that geometry. No suite, seed, tolerance or
failure assertion was weakened. Both listeners shut down after each run.

Reproduce the completed matrix with fresh output directories:

```sh
for geometry in split armed-fused; do
  REDIS74_ROOT=/home/user/Projects/redis74 \
  GATE_LOAD_CORES=121-127 GATE_DIFFER_ORACLE_CORES=120 \
  GATE_DIFFER_GEOMETRY="$geometry" \
  GATE_DIFFER_PROOF_SUITES="$PWD/docs/deadswitch/06-differ-suites.txt" \
  GATE_DIFFER_PROOF_SEEDS="$PWD/docs/deadswitch/06-differ-seeds.txt" \
  GATE_DIFFER_OUT="$PWD/build/ttlclean/recheck-$geometry" \
    taskset -c 112-127 tests/differ_gate.sh \
      "$PWD/build/tomokv" 18790 18791 112-119 6:2
done
```

Reproduce the byte comparisons without running either binary:

```sh
taskset -c 112-127 python3 tools/lbstall_artifacts.py compare \
  build/ttlclean/pre build build/ttlclean/recheck-hot.json
taskset -c 112-127 python3 tools/ccfix_audit.py \
  build/ttlclean/pre build build/ttlclean/recheck-full
taskset -c 112-127 python3 docs/deadswitch/linked_bytes.py \
  build/ttlclean/pre/tomokv build/tomokv build/ttlclean/recheck-linked.json
```

**Gate accounting:** DQ **+0**, DF **+0**. The former
`storage deadline-sidecar regression` row is adapted to
`storage deadline-allocation-failure regression` in the ordinary storage case
loop at `tests/gate.sh:1559`. Its row emission remains before the quick-tier
exit at line 3416. The gate still has twelve storage rows. The label fixture,
timing-history label and serverless validation tool follow the adapted case.
`EXPECT_QUICK=511` and `EXPECT_FULL=528` remain untouched; the required new
EXPECT values are therefore also **511 / 528**.

No benchmark or full gate was run. This is the task's focused correctness and
build/identity proof, not a full gate receipt. The experiment is closed; no
additional TTL performance measurement is requested.
