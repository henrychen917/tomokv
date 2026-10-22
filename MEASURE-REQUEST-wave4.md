# Wave 4 landing request

## wave4 integration

Lane wave4b resumes clean branch `cx-wave4` at `cd1423c97`. The four no-ff
merges are `2d276e45c` (compat2), `8bce7c3da` (moverfix), `4c692daf4`
(clockcut), and `7c054dbad` (notifyorder), on headline `8656f9fa9`.
`0350c7b33` retains the three clockcut labels. No push is requested.

The maintainer's compat2 EXPECT update and fixture sync remain intact.
DQ=DF=+16 (+3 compat2, +8 moverfix, +3 clockcut, +2 notifyorder), all collected
before the quick exit. Required landing counts are **685/702** from headline
669/686. Current constants remain **672/689**; this lane does not edit them.

Correctness uses CPUs 64–111 only and ports 26800–26899. Performance benchmarks,
measurement load generators and the full iteration gate remain with the maintainer.

### Oracle and sweep

`docs/wave4/oracle/auth-redis74.json` identifies Redis 7.4.10 (`f103d127`) and
records pre-AUTH `XGROUP x` as `ERR unknown subcommand 'x'. Try XGROUP HELP.`.
`acl-redis74.json` records `NOPERM User alice has no permissions to run the
'acl|whoami' command`. The corresponding TomoKV auth and atomic-0/atomic-1 ACL
receipts agree. Thus the retained evidence covers all three corrected rows in
`cd1423c97`, not just one ACL mode. No further assertion change is assumed.

The initial whole-test-tree textual sweep is retained in `docs/wave4/sweep-hits.json`.
Final job coverage, interaction findings, identity trials and proof outcomes
will be appended here after execution.

### Merge composition and semantic checks

The earlier merge resolutions retain the four gate jobs and all their legs,
compose the R7 inventory additively, and preserve every lane's production
change. The Makefile's provisional additive budgets have now been replaced
where compile-only trials improve identity. `docs/wave4/row-inventory.json`
confirms **702 source labels = 702 fixture labels**, with multiplicities.
Collection lines are ntnew4 4124, moverfix 4184, compat2 4189, notify_order 4237,
and notify_aof 4238; the quick exit is line 4303. No label/count was dropped.

`docs/wave4/interactions.md` records the C2/R1/NT-new-7 composition, physical
versus logical expiry, raw-overwrite observation, mover carrier/claim routing,
clock pins, script retry/AOF routing, and the exact-deadline fixtures.
Plain SET in fused/read-local mode executes **none** of moverfix's five
PAD-patched sites; the enclosing dispatch kinds are element movers or LMPOP/ZMPOP.
This reachability result does not explain away the lane's measured SET result.

### Compile-only identity

All **29** pinned translation units were recompiled with IPA dumps. **102**
budget trials produce **85** distinct object-body sets; each distinct set was
linked and compared using the gate's strict instruction/address normalizer
against the five supplied binaries. No reference rebuild was needed.
`docs/wave4/budgets/{initial,scan,selected}.json` retain commands and selections.

| Unit | Provisional merge | Selected |
|---|---:|---:|
| src/persist/aof.o | 37179 | 37173 |
| db0/src/persist/aof.o | 37578 | 37572 |
| src/cmd/t_set.o | 23568 | 23582 |
| src/cmd/xshard.o | 129016 | 128705 |
| src/core/reorder.o | 147991 | 148006 |
| db0/src/core/genthread.o | 130407 | 130360 |
| db0/src/core/reorder.o | 149111 | 149000 |

Final linked inventory: **8,649 function groups**, **7,932 headline-identical**;
of **717 changed groups**, **604 equal a lane POST** and **113 remain different**.
All **12** directly named GET/SET/MGET/MSET-related groups equal headline (6)
or an intentional lane POST (6). The broader hot inventory is **489** groups:
394 headline-identical, 78 lane-identical, **17 residual**. Strict universal
identity is therefore **not achieved** and is not presented as a performance result.

Every changed group is named with sizes, matching lanes and reason in
`docs/wave4/identity/changed-bodies.{json,md}`. The residuals include **73**
resolved-target/literal-only differences with identical instruction encodings,
**38** instruction-byte differences, and **2** symbol/clone emission changes;
strict diffs are retained in `residual-diffs.json.gz`. Composite changes and
unedited compiler propagation remain explicit merit inputs.

The gate's `reorder_identity` job passes the merged candidate, including all
negative controls: **293/293 = 146 normal + 147 DB0**. Missing policy symbols,
missing split-local parser and changed-opcode controls fail as required.
Receipt: `docs/wave4/proof/r7-final` (`build/gate-run.bzQ8Hu`).

### Scope of existing findings

The moverfix lane's broader concurrent EXEC conservation counterexample failed
both headline and isolated POST. Its atomic-0 claim protocol does not establish
EXEC conservation; passing the standard MULTI/EXEC battery cannot erase that
reported counterexample. This integration does not silently broaden the claim.
