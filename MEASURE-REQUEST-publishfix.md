# Atomic commit publication repair

## publishfix

Lane `cx-publishfix`, baseline `98c69316d5bfccfc35d4aeff8537cbdde00646d5`
(integrated wave 3). No push. This is a liveness repair inside the existing commit
bracket: a last decrementer catches tickets drawn after its first sequence load
by reading the sequence again, then checking for zero in-flight commits before
republishing. The non-last path and reader path are unchanged. No production
member or layout change. The only hook is compiled out of production and all
unit objects use the same hook macro. The parked server is a disposable full build.

The fix implements investigation 5.1 without changing protocol. The AOF F3
ordering fix stays intact. `crossing()` now records commit/read counter deltas,
does a fresh cross-owner kick, records live2 and the native AOF ticket/payload
order, then checks visibility before the original, unchanged replay assertion.

PRE receipts are committed in `docs/publishfix/pre/`, including all 410 live
reproductions in `reproductions.tar.gz`. Source anchors and the memory-order
argument are in `docs/publishfix/anchors.md`.

| Proof | PRE |
| --- | --- |
| R0, Appendix A | 2 / 36 orphaned final states for 2 / 3 committers; zero safety failures |
| R0, literal 5.1 variant | 180 / 8675 states, zero safety failures or orphans |
| R1, real Server, reentrant peers | FAIL: safe=1 drawn=2, windows=1; safe=1 drawn=3, windows=2 |
| R2, parked committer, 10 fresh boots | 10/10 visibility failures; nil after OK, still nil after 1 s, B after kick and replay |
| R3, fused/db16/always, 300 runs | 23/300 failures (7.67%); 180 windows, 23 held reads; all failures visibility-classified |
| R3, split/db1/everysec, 100 runs | 6/100 failures (6%); 80 windows, 6 held reads; all failures visibility-classified |

The gate addition is one deterministic row in `job_atomic_units`, collected
before the quick-tier exit: **DQ=+1, DF=+1**. EXPECT constants are untouched.
This branch retains wave 3's old 637/654 literals and its already-documented
+27/+27 pending adjustment; the integrated counts including publishfix become
**665 quick / 682 full** (664/681 wave 3 plus this row). The isolated delta
against the literal constants would be 638/655 and would omit wave 3's rows.

Merit remains with the maintainer. Use the existing generic 14 cells plus
atomic=1 MSET/SET/MGET at p1 and p32 in both modes. The 26 explicit rows are in
`docs/publishfix/merit-cells.txt`; the generic source is
`docs/lbplanner/generic-cells.txt`, SHA-256
`ac3719760fcd07f05a090bcba536162c4d713cdbef3f24e52d886e8d83880311`.
Use the gate's own instrument, the same eight-core/16-shard geometry (split 6:2),
matched offered loads, equal payload/key populations, ABBA arms, and a
contemporaneous same-binary null. Retain rate, cycles/op, instructions/op, IPC,
p99 and p99.9. Read instructions and IPC together; the matched-load rate decides.
Pure SET/MGET need not enter a commit bracket unless live versioning/group work
is exercised; preserve the traffic definitions and record the mechanism counters.
The added sequence load belongs only to last atomic commit publishers.

No throughput claim is made. The lane runs correctness only, on CPUs 96–111
(servers/oracle 96–103, clients 104–111), ports 25800–25899. It does not run
`tests/gate.sh`, performance benchmarks, or measurement load generators.
