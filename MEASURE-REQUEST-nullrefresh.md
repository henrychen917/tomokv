# nullrefresh — PENDING MAINLINE

Reference: `3e734cf2e00c087604fcaf145459522e6fa81f05`, branch `cx-nullrefresh`.
PRE frozen before edits in `build/nullrefresh-PRE/` (git archive of reference).
PRE executable instrument fingerprint: `a3ae63c61e908a696235a364c8068e7b046b457f382e2c107c20593ccefef7af`.
Full manifest: `build/nullrefresh-PRE.instrument.json`; transitive dependency graph:
`build/nullrefresh-PRE.dependencies.json`.

Launch diagnosis (rechecked in this worktree):
- `gate_receipt.py:403-421,439,459`: receipt-only standing-null publication depends on completed
  trusted comparison/rc=0; `abbagate.py:1858-1863,2084-2096` needs that standing null.
- `abbagate.py:1872-1881,2071-2079` already collects identical-arm null without prior null;
  PARTIAL/false/rc=3 is correct for collection (`abba_evidence.py:280-298`).
- `gate_measurements.py:234,268,310,318` disagrees with existing
  `abbagate.saturation_exempt`; `abba_evidence.py:215` still floors p999 occupancy.
- `gate_receipt.py:27,284-285,483-484` requires a nonexistent headline scored row;
  current gate correctness control row is `gate.sh:2334-2344`, quick exit 2808-2813,
  reporting-only headline 2887-2903. EXPECT_QUICK=438, EXPECT_FULL=454 remain untouched.
- Instrument scope is transitive code + Python identity; measured runtime inputs need a
  separate freeze. Existing null resolution covers rate/latency/tails, NOT cycles/op.

Old dependency graph:
```
calibrate -> select EXEMPT -> import PIN-only refusal (p999)
collect full null (independent, PARTIAL) -> receipt-only publication
standing null -> trusted comparison rc=0 -> full gate receipt -> standing null
current correctness ledger -> obsolete headline-row requirement -> receipt refusal
```
Planned repaired graph:
```
frozen code/runtime/inventory/geometry -> calibrate -> replay/import rate floors
freeze imported runtime inputs -> collect full null -> explicit local promotion
promoted null -> independent same-binary holdout -> ordinary comparison -> full receipt
```
Promotion alone will not prove independent resolution or mint a comparison/full receipt.
All live measurements, gates, full receipt workflow, holdout and cycles/op qualification:
PENDING MAINLINE. No server or generator will be started by this lane.
