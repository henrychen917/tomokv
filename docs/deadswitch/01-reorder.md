# 1 — Production 128-operation preset: DEAD; generic unit geometry retained

PRE: `dab740964`, `build/deadswitch/pre/tomokv`.
POST: `build/deadswitch/01-reorder/tomokv`.

`reorder_instances.py` enumerates both `nm -aC` and `objdump -tC` over **all**
production objects. It requires both queue classes in both namespaces, only
`BatchOps=32`, and fails on missing evidence or any other quantum. The production
inventory contains no 128-operation instantiation. The source/caller inventory
also finds real 128-operation **unit** instantiations: these are retained, not
silently weakened or dropped.

The two historical preset assertions become generic nonzero/no-overflow bounds;
the existing power-of-two and shadow-index capacity assertions remain. No queue
algorithm, layout, default, or production instantiation changes. Both existing
serverless queue suites pass, including their 128-operation fairness witnesses.

Proof commands (builds use the unchanged Makefile flags, GCC 13.3, jemalloc):

```
taskset -c 0-15 make -j16 BUILD_ROOT=build/deadswitch/01-reorder all
python3 docs/deadswitch/reorder_instances.py build/deadswitch/pre docs/deadswitch/01-reorder-symbols.json
python3 tools/lbstall_artifacts.py compare build/deadswitch/pre build/deadswitch/01-reorder build/deadswitch/01-hot.json
python3 tools/ccfix_audit.py build/deadswitch/pre build/deadswitch/01-reorder docs/deadswitch/01-bodies
python3 docs/deadswitch/linked_bytes.py build/deadswitch/pre/tomokv build/deadswitch/01-reorder/tomokv docs/deadswitch/01-linked.json
```

Results: **1492/1492 hot; 17078/17078 full emitted bodies; 0 changes**.
The ccfix inventory includes four additional `ExLoop::run` bodies in its hot
selection (1496/1496). All loadable sections and the **entire debug ELF** are
identical: SHA-256 `9df641b6973896cc791986921e59e795a739ca6222e1a01a4929f38ca037a752`.
No PAD or performance measurement is needed for this identity result.
Gate rows +0/+0; EXPECT constants untouched.
