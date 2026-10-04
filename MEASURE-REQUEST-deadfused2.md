# deadfused2 — repair the R7 receipt; production binary unchanged

The landing failure is fixed in **4317a6d06**. The exact identity-row command
passes **396/396 ordinary bodies**, with its missing-policy, missing-parser,
and changed-opcode negative controls. The requested writeback, gate-verdict,
and receipt-chain checks also pass. Production `.text`, every function address
and size, and the complete `build/tomokv` file are unchanged. Under the owner's
2026-10-04 addendum, the previously reported **14-cell null GO is retained**.
This lane ran no server, load generator, benchmark, or live gate and did not push.

The first command was `git fetch origin cpp && git merge --no-edit origin/cpp`;
it reported already up to date. Launch HEAD was **744c86d07**, already containing
`origin/cpp` **aee02e847**, including gaterows **c67edf128**. The existing cleanup
tag `deadfused-pre-cleanup-cd02ecbab` is retained; the repair baseline is tagged
`deadfused2-pre-repair-744c86d07`. All work is in `cx-deadfused`.

At launch, `tests/reorder_noop.py:375–378` expected a historical seven-argument
fused-pass spelling to normalize to six arguments. The cleanup's later rule
already maps those six arguments to the surviving four-argument signature.
The self-test consequently failed before `r7shadow_noop.py:114` opened either
binary. Its failure is captured in
[before-self-test.log](docs/deadfused2/before-self-test.log).
The arity guard also rejected an actual four-argument ordinary fused symbol;
fixing only the stale expected string would have left the row broken.

The [defined-symbol inventory](docs/deadfused2/fused-inventory.json) proves that
all fourteen ordinary/generated fused pass/sweep symbols across `tomo` and
`tomo_db0` in production and its FIFO twin have four arguments. No six- or
seven-argument fused spelling survives in either current binary. Historical
spellings remain usable for frozen inputs, but their canonical target is now
the surviving four-argument signature.

`tests/reorder_noop.py:59–70` accepts and preserves those four arguments in
ordinary and generated methods. Its self-tests at line 383 check the complete
historical-to-current mapping and current-signature idempotence for both
namespaces, both method families, and both local-read choices. Negative cases
retain distinctions for true historical policies, non-void fillers, function
parameters, and every surviving template argument; unexpected arities fail.
The instruction/operand normalizer and the expected body count are unchanged.

Both auditors already share `reorder_noop.canonical`, `Binary`, `compare`, and
`require_policies`; `r7shadow_noop.py` needs no separate copy or inventory edit.
Its existing **198 bodies per namespace** assertion remains intact, as do its
exact symbol/clone-count comparison and missing-symbol failures. The standalone
`tests/deadfused_checks.py:36` fixture now supplies all required policy symbols
and proves its intact comparison first, then removes `cmd_get`. This preserves
the intended missing-command rejection after mainline added the earlier policy
inventory check, instead of accepting a failure for the wrong reason.

`taskset -c 112-127 python3 tests/r7shadow_sync.py --write` was run against this
production tree. It reported current envelopes and produced **no diff** in
`reorder.cc`, `ex_loop.h`, or `io_loop.h`. The generator's stale-copy negative
control also passes. All production source, Makefile, gate script, and protected
label fixture match launch; see
[source-receipt.json](docs/deadfused2/source-receipt.json).

The exact production identity receipt is
[identity.json](docs/deadfused2/identity/identity.json), with compressed complete
function and section tables beside it. `build/deadfused2/PRE-REPAIR` preserves
the launch binary. `taskset -c 112-127 make -j16` reported that `all` was already
up to date. No C++ rebuild or changed executable was needed.

| Production property | Before repair | After repair |
|---|---|---|
| `.text` bytes | 7,734,273 | 7,734,273 |
| `.text` SHA-256 | `e7ca8bb65c99b5d23be752b3295f332c763e0182959d8741f84e66680f44c738` | identical |
| Full binary SHA-256 | `be91c12fbc63c6394eeb05ef4938ff493894f7979c21d829c196796f25f75660` | identical |
| Defined function-table entries | 10,258 | 10,258 |
| Function name/address/size/section table SHA-256 | `003e06e92445f2ee562d3fba0cb4768c47fc10f081cbee172a86801415d57ae7` | identical |
| Complete section-table SHA-256 | `f3c1e98fdd01416b0e537e42f510b1b1e5497c873cfabc866901a39e0332d45b` | identical |
| All executable sections, including `.rlfence` | literal identity | literal identity |

The repair changes zero executed loads, stores, branches, allocations, or RFOs
per server operation. It changes only Python audit/test code. There is no new
performance treatment or speedup claim; the existing cycles/op verdict is
preserved by literal binary identity, not inferred from instruction counts.

**No new deadfused performance PAD-A is required:** production `.text` did not
change. The identity row did regenerate its own, separate **kind-A FIFO twin**
at `build/reorder-receipt-check/fifo-twin`: inherited FIFO behavior at production
text size/layout. Its two capability immediates change from 1 to 0, one per
namespace; every other file byte is identical. The full function and section
tables are identical, and all 396 ordinary bodies pass strict instruction and
encoding comparison. The [FIFO PAD proof](docs/deadfused2/r7-fifo/proof.json),
[patch receipt](docs/deadfused2/r7-fifo/twin.json), and
[complete body audit](docs/deadfused2/r7-fifo/audit.json.gz) are archived. This
FIFO twin is the existing R7 correctness control, not a replacement for the
cleanup's INFO-compatibility performance twin.

Static GDB type inspection opened debug information without starting the
binary. [layout.json](docs/deadfused2/layout.json) verifies both namespaces:

| Type | Bytes before and after |
|---|---:|
| Op | 336 |
| Client | 1984 |
| ThreadCtx | 1408 |
| Shard | 1440 |
| FlatStore | 944 |
| Rob<64> | 192 |
| AtomicEntry | 144 |
| Config | 624 |
| ExLoop | 5848 |
| FusedExLoop | 5856 |

Every size delta in this repair is **zero**. The eight required locks remain,
and the cleanup's `FusedExLoop` lock remains at `src/core/ex_loop.h:3010`.

All following checks ran with CPU affinity **112–127**. Exact commands, log
digests, and outcomes are in
[verification.json](docs/deadfused2/verification.json); compressed logs retain
their original bytes. These are serverless checks, not a new live gate receipt.

| Command after `taskset -c 112-127` | Result |
|---|---|
| `make -j16` | PASS; up to date |
| `python3 tests/r7shadow_sync.py --write` | Current, no generated-source change |
| `python3 tests/r7shadow_sync.py` and `python3 tests/r7shadow_sync_test.py` | Parity passes; stale copy rejected and regenerated |
| `python3 tests/reorder_receipt.py build/tomokv build/reorder-receipt-check` | 396/396; missing policy, missing split-local parser, changed opcode rejected |
| `python3 tests/wbland_checks.py check clauses` | 72/72 strict outcomes, including production mutation controls |
| `python3 tests/gates_test.py` | 65 tests PASS |
| `python3 tests/gate_receipt.py --self-test` | Five suites: 10 + 18 + 27 + 10 + 1 tests PASS |
| `python3 tests/gate_ledger_fixture.py` | 506 source-declared labels agree; check only |
| `python3 tests/deadfused_checks.py` | Lane replays, window/reply controls, retired INFO keys, missing-command control, canonicalizer PASS |
| `python3 tests/reorder_receipt.py build/reorder-engagement-unit build/deadfused2/engagement-multi --engagement` | Real production engagement, FIFO control, disabled-capability rejection PASS |
| Same engagement command with `build/reorder-engagement-unit-db0` and `build/deadfused2/engagement-db0` | PASS in db0 runtime |

Gate behavior: the existing `R7 FIFO twin off-path identity + negative controls`
row at `tests/gate.sh:1410–1414` now reaches and passes its binary comparison and
negative controls. It is collected at **line 3052**, before the quick-tier exit
at **line 3190**. No row was added, removed, skipped, or renamed: **quick +0,
full +0**. `EXPECT_QUICK=489`, `EXPECT_FULL=506`, and
`tests/fixtures/nullrefresh-ledger-labels.json` are untouched.

The remaining mainline action is the normal landing correctness gate, including
the repaired existing row. The owner reported the prior 14-cell null GO; this
repair meets the stated condition for retaining it because the entire binary,
not just `.text`, is unchanged. No fresh measurement is requested for this fix.

For a later integration that changes `.text`, the original null obligation
applies again: rebuild PRE, POST, and a **kind-A PRE-behavior/POST-layout** twin,
verify its complete function table and negative controls, and use the mainline
instrument for PRE/POST, PRE/PAD-A, and PAD-A/POST. The exact fourteen cells are
`h05,h06,p8g,p8s,d1g_l0,d1s_l0,m8g_l0,v1g_l0,d128g_l0,d32g_l1,d8s_l1,d32s_l1,x9_32_l1,x9_32_l0`
in [generic-merit-cells.txt](docs/deadfused/generic-merit-cells.txt).
The three regimes and exact additional shapes remain those in
[the cleanup request](MEASURE-REQUEST-deadfused.md) and
[feature-cells.txt](docs/deadfused/feature-cells.txt): ordinary controls, active
MGET8/MSET8 at p8/p32, and the possible-deficit MIX8 p128/movement cases. Mainline
must retain its frozen two-sided per-cell null bands, matched-load rate and
cycles/op with instr/op and IPC, tail bounds, and engaged correctness witnesses;
no widening, averaging away a losing cell, or substituting instruction counts.

The repair and receipts are committed separately from this report. Nothing was
pushed. The diff from repair launch follows, including this report.

`git diff 744c86d07 --stat`:

<!-- DEADFUSED2_DIFFSTAT -->
```text
 MEASURE-REQUEST-deadfused2.md                  | 201 ++++++
 docs/deadfused2/SHA256SUMS                     |  35 +
 docs/deadfused2/before-self-test.log           |   6 +
 docs/deadfused2/build.log                      |   1 +
 docs/deadfused2/deadfused-checks.log.gz        | Bin 0 -> 750 bytes
 docs/deadfused2/engagement-db0-twin.json       |  22 +
 docs/deadfused2/engagement-db0.log             |   1 +
 docs/deadfused2/engagement-multi-twin.json     |  20 +
 docs/deadfused2/engagement-multi.log           |   1 +
 docs/deadfused2/fused-inventory.json           |  42 ++
 docs/deadfused2/fused-symbols-before.txt       |  14 +
 docs/deadfused2/gates-test.log                 |   5 +
 docs/deadfused2/identity/POST-functions.tsv.gz | Bin 0 -> 151893 bytes
 docs/deadfused2/identity/POST-sections.tsv.gz  | Bin 0 -> 742 bytes
 docs/deadfused2/identity/PRE-functions.tsv.gz  | Bin 0 -> 151893 bytes
 docs/deadfused2/identity/PRE-sections.tsv.gz   | Bin 0 -> 742 bytes
 docs/deadfused2/identity/identity.json         | 130 ++++
 docs/deadfused2/launch.json                    |  10 +
 docs/deadfused2/layout.json                    |  27 +
 docs/deadfused2/layout.log                     |   1 +
 docs/deadfused2/ledger-fixture.log             |   1 +
 docs/deadfused2/production-identity.log        |   1 +
 docs/deadfused2/r7-fifo/PAD-A-functions.tsv.gz | Bin 0 -> 151893 bytes
 docs/deadfused2/r7-fifo/PAD-A-sections.tsv.gz  | Bin 0 -> 742 bytes
 docs/deadfused2/r7-fifo/POST-functions.tsv.gz  | Bin 0 -> 151893 bytes
 docs/deadfused2/r7-fifo/POST-sections.tsv.gz   | Bin 0 -> 742 bytes
 docs/deadfused2/r7-fifo/audit.json.gz          | Bin 0 -> 19466 bytes
 docs/deadfused2/r7-fifo/proof.json             |  43 ++
 docs/deadfused2/r7-fifo/twin.json              |  22 +
 docs/deadfused2/r7-regenerate.log              |   1 +
 docs/deadfused2/r7-sync.log                    |   2 +
 docs/deadfused2/receipt-chain.log.gz           | Bin 0 -> 6020 bytes
 docs/deadfused2/reorder-receipt.log            |   3 +
 docs/deadfused2/source-receipt.json            |  19 +
 docs/deadfused2/verification.json              |  93 +++
 docs/deadfused2/wbland-clauses-proofs.json     | 855 +++++++++++++++++++++++++
 docs/deadfused2/wbland-clauses.log.gz          | Bin 0 -> 619 bytes
 tests/deadfused_checks.py                      |  20 +-
 tests/reorder_noop.py                          |  50 +-
 39 files changed, 1613 insertions(+), 13 deletions(-)
```
