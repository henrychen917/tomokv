# Parked wave9 diagnostics

These tests remain strict, explicit diagnostics. They do not emit landing gate
rows and are not passing correctness evidence.

* `tests/layout_placement.cc`, built with
  `taskset -c 64-95 make -j32 build/layout-placement`: run
  `taskset -c 64-95 build/layout-placement`. Gaterows5's frozen evidence records
  14 shared IoLoop boundaries, 8 ExLoop boundaries, 14 FusedExLoop boundaries,
  8 StoreSizeState sharing pairs and 128/512 straddling ROB argv slices.
  See `MEASURE-REQUEST-gaterows5.md` and `docs/gaterows5/receipts.tar.gz`.
  The wave-10 lineshare lanes own the fixes. Removed from the gate's plan,
  collection and label inventory; the native source and target remain.
* `tests/compat3_blockfix2.py`, `removed` case: the exact pipelined DEL,
  XGROUP CREATE, XADD boundary remains asserted. Blockfix2's final POST fails
  all 24 mode/engine/atomic/database/read-local legs at that boundary:
  `docs/blockfix2/post-directed.json`, with archived raw receipts indexed by
  `docs/blockfix2/gate-receipts/index.json`. An old waiter can receive new-stream
  data instead of NOGROUP. Blockfix3 owns the wave-10 fix. Only this row is
  omitted from `job_blockfix2`; the five other live roots and refusal unit remain.

The lane reports also retain their original failing development and unrelated
root evidence. None of those receipts is relabelled as an integration pass.
