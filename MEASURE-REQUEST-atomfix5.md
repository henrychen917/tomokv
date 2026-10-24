# Cross-shard contention compatibility and accounting

## atomfix5

Branch/worktree cx-atomfix5, base ef5204b2e9650693228cc105b34625516898b82d.
No push. This request separates delivered changes from unresolved contention
paths; it makes no throughput claim.

AT4.13 WATCH key counts are fixed. AT4.19 gains a non-vacuous exact-accounting
gate row; it already passes the named PRE and rejects the isolated broken-writer
control. AT4.11 uses the allowed documentation option. AT4.12 is reproduced and
stops at the requested design handoff because this base removed EXEC's exclusive
fallback. AT4.20 (atomic-1 retry ceiling) and AT4.21 are NOT REPRODUCED at the
recorded geometries. AT4.7 awaits maintainer measurement before implementation.
The adjacent docs/atomfix5 item reports contain the detailed evidence.

### Required maintainer merit work (NOT RUN in this lane)

Use docs/atomfix5/merit-cells.txt: the exact generic 14 from
tests/wbland_merit_cells.txt plus 96 unchanged atomic-1 multi-key cells from
tests/headline_cells.txt. Use the gate's own ABBA instrument, reviewed geometry
and offered-load calibration, PRE/PRE null, PRE versus POST, PRE versus PAD-A,
and POST versus PAD-A. Preserve CPU/SMT, NUMA, ratio, shards, pipeline depth,
connections, binary hashes, sample order and workload/key geometry. For every
cell report rate at matched offered load, cycles/op, instructions/op and IPC;
depth-1 cells also retain latency. Rate and the matched null decide regression;
instruction and IPC changes explain it. Identity alone is not acceptance.

Arms: build/tomokv-pre (ef5204b2e), build/tomokv (POST),
build/tomokv-pad-a. PAD is **kind A, behaviour twin: PRE WATCH counting with the
candidate's exact text size, function placement and data layout**. It copies the
validated relocation-free PRE leaf into each namespace's larger POST function,
NOP-fills that function's unused tail and changes no symbol address or section
size. All other instructions remain POST. tools/atomfix5_arms.py and
arms.json specify every byte. Its WATCH gate must fail like PRE. No PAD-B is
needed for this small change. The broken-writer test copy is not a merit arm.

AT4.7's separate measure-first 12-wave request (four publishers × 1/8/64 tasks)
is in docs/atomfix5/wave-cost.md. Do not infer those per-wave counts from whole-
server spinning PMU totals or from this lane's WATCH-only PAD.

### Proof status

Directed WATCH PRE/POST and exact-accounting PRE/POST/broken controls have run
through tests/gate.sh's own job interface. Broader proof, hashes, final counts
and limits will be appended after the running jobs finish. EXPECT constants
are untouched; the lane adds two rows before the quick exit (DQ=+2, DF=+2).
