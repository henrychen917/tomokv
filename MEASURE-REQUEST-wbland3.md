TomoKV wbland3 — fixed writeback handoff, 2026-09-30

Live results: **PENDING MAINLINE**. Adaptive writeback is deleted. Production
accepts `--wb-policy 0|1`, default **1**. This report supersedes the active
wbland/wbland2 adaptive measurement requests; their dated reports remain history.

Worktree `/home/user/Projects/cx-wbland`, branch `cx-wbland`, launch
`bd4f68e97`, REF `37eeb5e90`. Implementation: `b86bde4f7`; frozen arms and
object audit: `956c54410`. Builds and every serverless execution used cores
**112-127**, with `taskset -c 112-127` and `make -j16`. No server, benchmark,
load generator, gate, performance measurement, push, or merge was run.

The mainline's supplied results decide the deletion: adaptive burst p99 did
not improve reproducibly beyond the ±2.5% twin spread, while p50 worsened;
the 256K/p32 low-load cell fragmented pipes; floored bursts worsened p99.
These are owner-supplied results from the launch prompt, not measurements by
this lane. No adaptive gain is claimed or requested for acceptance again.

The authoritative production rule stays in `src/core/wb_rule.h`. Policy 1
retains REF's exact composite: ordinary serve for zero/one in flight;
otherwise serve on a contiguous Done prefix of `ceil(n/2)`, staged plus
acquired Done reply bytes reaching 512 B, or the Done MGET scatter exit.
Submitted send bytes stay excluded. Policy 0 bypasses deferral and serves
every ready head on every captured pass. Both policies apply to FIFO/R7
fused and ordinary/overlap/read-local split schedules, in both database
namespaces. Neither allocates policy state. There is no policy stack state,
publication array, per-pass detector work, new clock, synchronization, or
completion-side store. The existing acquire walk and FIFO lifetime pins remain.

The removal inventory below uses **launch-commit line numbers** (`bd4f68e97`)
so deleted ranges remain identifiable.

| File / old lines | Removal or retained replacement |
| --- | --- |
| `src/core/wb_rule.h:9-115` | Removed scale/dynamic fraction, all of `Window`, `Published`, `State`, detector close/pass/publication paths, split-AUTO bit 8 and PAD bit 31, and adaptive INFO rows. Replaced the bitfield selector with a cold 0/1 default-policy immediate used only to freeze the pol0 artifact. |
| `src/core/wb_rule.h:151-164,192,216` | Removed adaptive threshold arithmetic and state-pointer selection; restored REF's `std::ratio<1,2>` expression and added only the static policy-0 exit/read. |
| `src/core/io_loop.h:507-509,533,591,783-784,5739-5740` | Removed tenure state, detector pass, publications, and `wb_policy_` pointer. Entire file now equals REF source. |
| `src/core/reorder.cc:800-802,826,884,1076-1077` | Removed the same R7 envelope machinery. Entire file now equals REF source. |
| `src/core/server.h:276-277,479-484,3749` | Removed publication allocation, signal accessor, and ownership. Retained only the thin static INFO helper. |
| `src/core/config.h:843-850,1083-1084,1145-1146` | Removed `-1` grammar/help/validation; default changed to 1. |
| `tests/wbland2_replay.cc:1-149` | Deleted the complete detector replay. |
| `tests/wbland2_checks.py:1-142` | Deleted the complete detector replay/check/cost helper. |
| `tests/wbland2_evidence.json:1-370` | Deleted the detector evidence file. |
| `Makefile:425,444,447-452` | Removed detector-only controls and all wbland2 replay/reference targets and prerequisites. |
| `tests/gate.sh:1292` | Removed `detector` from `job_wbland_units`; retained `clauses paths`. |
| `tests/wbland_unit.cc:19-118,157-169` | Removed detector sampling/ramp/window/fixed-probe/publication witnesses. Retained exhaustive 0/1 endpoints, exits, strict grammar and static INFO checks. |
| `tests/wbland_checks.py`, `tests/wbland_clause_unit.cc`, `tests/wb_rule_phase_unit.cc` | Removed adaptive/probe cases; retained clause/path witnesses, 96-connection chunk traversal, and strict negative controls for policies 0/1. Basic policy/grammar/INFO checks now run inside `clauses`, without a third gate row. |
| `tests/wbland_evidence.json` | Replaced obsolete adaptive evidence with the current fixed-policy artifacts, per-object hashes, strict outcome counts, and the inherited CONFIG fixture failure. |
| `tools/wbland_artifacts.py` | Removed AUTO/probe/PAD selector bits and old-baseline assumptions. Freezes 0/1 arms and audits the full compiler dependency closure. Retires the obsolete generated `build/tomokv-auto2s-probe`. |
| `docs/CONFIGURATION.md`, `tomokv.conf` | Removed adaptive settings, diagnostics and gain claims; documented fixed policies and existing boot-only CONFIG behavior. |

`src/net/wb.h` is unchanged from REF. `tests/wbland_4096_cells.txt` and
`tests/wbland_merit_cells.txt` are retained unchanged. Every existing footprint
and offset assertion compiled, including Op 336 / Client 1984 / ThreadCtx 1408 /
Shard 1440 / FlatStore 944 / Rob<64> 192 / AtomicEntry 144 / Config 624.
`Config::wb_policy` continues to occupy four reserved bytes; earlier offsets
and the remaining 76 reserved bytes are unchanged.

The final public surface is:

| Surface | Behavior |
| --- | --- |
| CLI / config file | Exactly `0` or `1`; default `1`. `-1`, aliases, signs, leading zeros, fractions, junk and missing values fail. Error: `--wb-policy wants 0 or 1`. |
| `CONFIG GET wb-policy` | Returns the boot policy. |
| `CONFIG REWRITE` | Preserves `wb-policy 0` or `wb-policy 1` through the existing binding. |
| `CONFIG SET wb-policy` | Remains boot-only and rejected. The inherited wbland code had **no runtime 0/1 switch**, for either fixed or adaptive policies. No runtime switch was removed. The test retains rejection and now checks attempted values 0, 1, -1 and 2 leave GET unchanged. |
| `INFO WRITEBACK` | `# Writeback` and `wb_policy:<0 or 1>` only. No adaptive, fixed-fraction, probe, PAD or per-thread busy/fraction/window fields. |

PRE was rebuilt from REF source **inside this worktree**, not taken from the
older wbland/wbland2 reference binary:

```sh
mkdir -p build/wbland3/pre-src
git archive 37eeb5e90 | tar -x -C build/wbland3/pre-src
taskset -c 112-127 make -C build/wbland3/pre-src -j16 CXX='g++ -MMD -MP' all
```

All **765 archived tracked blobs** were verified against the REF Git blob
hashes after the build. PRE and POST used the same GCC 13.3.0 compiler and REF
Makefile optimization budgets (`-std=c++20 -O2 -g -Wall -Wextra -march=native
-pthread`, jemalloc enabled). `-MMD -MP` only emits dependency receipts for
coverage; no optimization flag, namespace, or linker order was changed.
Logs: `build/wbland3/pre-build.log` and `build/wbland3/post-build.log`.

The default path is **not fully byte-identical** to REF after the knob read:
**25/40** relevant objects have identical raw `.text`; **23/40** have identical
`.text` plus every `.text.*` section. This is the requested PAD-fallback case,
not a default-path identity pass. Linked `.text` is **7,576,545 B PRE** and
**7,578,753 B POST/PAD**, a **+2,208 B** difference. `.tdata=112` and `.tbss=480`
in every arm. GET/SET clean, TLS and notify command bodies remain **16/16
identical in opcodes and relocation targets** across the two namespaces.

Coverage is the union of PRE/POST compiler `-MMD` dependency closures for
`src/core/wb_rule.h`, `src/net/wb.h`, `src/core/io_loop.h`, and
`src/core/reorder.cc`, including the reorder translation unit itself. Every
production object has a dependency receipt. The table reports exact raw
section bytes, without normalizing relocations or hiding cold sections;
`SAME` here is section equality, not a whole-object identity claim. Detailed
PRE/POST section sizes, hashes, dependency membership and differing section
names are in `build/wbland3/text-identity.json` and the committed
`tests/wbland_evidence.json`. PAD is linked from the same objects as POST.

| Object | PRE `.text` B | POST `.text` B | Exact `.text` | Exact all `.text.*` | PAD |
| --- | ---: | ---: | --- | --- | --- |
| `db0/src/cmd/acl.o` | 98268 | 98300 | DIFF | DIFF | POST |
| `db0/src/cmd/climon.o` | 39621 | 39621 | SAME | SAME | POST |
| `db0/src/cmd/functions.o` | 65858 | 65858 | SAME | SAME | POST |
| `db0/src/cmd/lbsignals.o` | 8682 | 8682 | SAME | SAME | POST |
| `db0/src/cmd/multidb.o` | 18786 | 18786 | SAME | SAME | POST |
| `db0/src/cmd/scripting.o` | 37099 | 37099 | SAME | SAME | POST |
| `db0/src/cmd/server_tail.o` | 41098 | 41098 | DIFF | DIFF | POST |
| `db0/src/cmd/slowlog.o` | 36278 | 36278 | SAME | SAME | POST |
| `db0/src/cmd/t_server.o` | 94865 | 95585 | DIFF | DIFF | POST |
| `db0/src/cmd/tracking.o` | 45667 | 45667 | SAME | SAME | POST |
| `db0/src/cmd/xshard.o` | 353148 | 353148 | DIFF | DIFF | POST |
| `db0/src/core/flipctl.o` | 34617 | 34617 | SAME | SAME | POST |
| `db0/src/core/genthread.o` | 55092 | 55092 | SAME | DIFF | POST |
| `db0/src/core/lbstall.o` | 3983 | 3983 | SAME | SAME | POST |
| `db0/src/core/reorder.o` | 56965 | 56965 | SAME | DIFF | POST |
| `db0/src/core/rl2s.o` | 63335 | 63240 | DIFF | DIFF | POST |
| `db0/src/main.o` | 43362 | 43362 | DIFF | DIFF | POST |
| `db0/src/net/tls.o` | 14623 | 14623 | SAME | SAME | POST |
| `db0/src/persist/aof.o` | 92602 | 92602 | SAME | SAME | POST |
| `db0/src/snapshot/snapshot.o` | 28752 | 28752 | SAME | SAME | POST |
| `src/cmd/acl.o` | 97596 | 97612 | DIFF | DIFF | POST |
| `src/cmd/climon.o` | 39477 | 39477 | DIFF | DIFF | POST |
| `src/cmd/functions.o` | 65733 | 65733 | SAME | SAME | POST |
| `src/cmd/lbsignals.o` | 8682 | 8682 | SAME | SAME | POST |
| `src/cmd/multidb.o` | 27699 | 27699 | SAME | SAME | POST |
| `src/cmd/scripting.o` | 174299 | 174299 | SAME | SAME | POST |
| `src/cmd/server_tail.o` | 41392 | 41366 | DIFF | DIFF | POST |
| `src/cmd/slowlog.o` | 36278 | 36278 | SAME | SAME | POST |
| `src/cmd/t_server.o` | 93297 | 93969 | DIFF | DIFF | POST |
| `src/cmd/tracking.o` | 43744 | 43744 | SAME | SAME | POST |
| `src/cmd/xshard.o` | 345516 | 345564 | DIFF | DIFF | POST |
| `src/core/flipctl.o` | 34617 | 34617 | SAME | SAME | POST |
| `src/core/genthread.o` | 54459 | 54459 | DIFF | DIFF | POST |
| `src/core/lbstall.o` | 3983 | 3983 | SAME | SAME | POST |
| `src/core/reorder.o` | 56405 | 56421 | DIFF | DIFF | POST |
| `src/core/rl2s.o` | 63075 | 63075 | DIFF | DIFF | POST |
| `src/main.o` | 58075 | 58075 | DIFF | DIFF | POST |
| `src/net/tls.o` | 14623 | 14623 | SAME | SAME | POST |
| `src/persist/aof.o` | 92730 | 92730 | SAME | SAME | POST |
| `src/snapshot/snapshot.o` | 29200 | 29200 | SAME | SAME | POST |

**PAD kind A — behaviour twin:** `build/tomokv-pad` uses REF's fixed-half
behavior with the candidate's exact knob read, constant half fraction, text
layout and addresses. Since POST is now also fixed half, **PAD is an exact
copy of POST**, including its SHA-256. There is no surviving PAD selector bit
and no separate adaptive mechanism to isolate. The meaningful cost comparison
is POST/PAD versus REF; POST versus PAD is an identical-binary null. Do not
interpret their identical behavior as measured neutrality versus REF.

`tools/wbland_artifacts.py arms` creates `build/tomokv-pol0` by patching only
the two namespaces' cold `default_policy()` immediates from 1 to 0, at file
offsets 4,085,525 and 413,797. The tool verifies every other byte is unchanged.
It also refreshes the `tomokv-pol1` alias to POST. Named arms must run without
a conflicting `--wb-policy` override or config-file directive. The patched
pol0 image deliberately retains the linked ELF build ID; identify arms by
SHA-256. No inverse-control PAD B is supplied.

The requested `sha256sum build/tomokv build/tomokv-pol0 build/tomokv-pad`,
with PRE included for provenance, is:

```text
5e1850d9b45183100d37328023ec5de2a6ddee72c4ad78aff3f9903f5cf24465  build/wbland3/pre-src/build/tomokv
44117ee5e096c0b88acdbd5823f4fd7d879b7d78a058d284c0bb3132b9ad9bb3  build/tomokv
5123c714340768b587423862d80b0c1f53cc70cec68fc6be2eed6bf224482c7f  build/tomokv-pol0
44117ee5e096c0b88acdbd5823f4fd7d879b7d78a058d284c0bb3132b9ad9bb3  build/tomokv-pad
```

Serverless validation completed **248/248 strict outcomes**, including **86
negative controls** that failed with exit 1 and their required assertion;
crashes, timeouts and unrelated failures do not count as successful controls.

| Serverless group | Strict outcomes passed | Negative controls rejected as required |
| --- | ---: | ---: |
| wbland-clauses | 49/49 | 23 |
| wbland-paths | 19/19 | 3 |
| wb-rule-policy | 37/37 | 19 |
| wb-rule-phase | 32/32 | 8 |
| wb-rule-stages | 12/12 | 2 |
| wb-rule-split-phase | 35/35 | 11 |
| wb-rule-split-overlap | 64/64 | 20 |

The config parser and ordinary `build/netcmd-unit config` passed. Source checks
prove REF envelope equality and R7 synchronization; `bash -n tests/gate.sh`
and Python syntax checks passed. Production compilation had no warnings;
the deliberately broken `empty` header overlay emitted one indentation warning.
The rule/path fixtures execute both namespace builds and policies 0/1 through
fused FIFO/R7 and split ordinary/natural/shallow overlap/read-local schedules.
These are in-memory fixtures, not boot or live throughput evidence.

One additional check **failed identically on PRE and POST**:
`build/netcmd-unit-db0 config` exits 1 at `FAIL: tracking map swapped`.
The unchanged fixture `tests/netcmd_unit.cc:532` requests `swap(0,1)` in a
single-database build, before it reaches the CONFIG/REWRITE witnesses.
REF's rebuilt `build/wbland3/pre-src/build/netcmd-unit-db0 config` has the
same exit and identical output. No assertion was weakened and no test was
silently skipped. Logs are `build/wbland3/config-db0.log` and
`build/wbland3/pre-config-db0.log`. Thus the extra db0 CONFIG suite is **not
claimed green**; db0 writeback clauses, grammar, INFO and scheduling passed.

Reproduction commands for the completed offline work (all on 112-127):

```sh
taskset -c 112-127 make -j16 CXX='g++ -MMD -MP' all wbland-units build/config-parser-test build/netcmd-unit build/netcmd-unit-db0
taskset -c 112-127 python3 tests/wbland_checks.py check clauses
taskset -c 112-127 python3 tests/wbland_checks.py check paths
for group in policy phase stages split-phase split-overlap; do
  taskset -c 112-127 python3 tests/wb_rule_checks.py check "$group"
done
taskset -c 112-127 build/config-parser-test
taskset -c 112-127 build/netcmd-unit config
taskset -c 112-127 python3 tools/wbland_artifacts.py arms
taskset -c 112-127 python3 tools/wbland_artifacts.py text
taskset -c 112-127 python3 tools/wbland_artifacts.py identity
```

The gate-row arithmetic is counted by **emission and collection line**:
`tests/gate.sh:1292` now iterates `clauses paths`; `row_begin` is line 1294,
`ok` line 1297, and `bad` line 1299. `collect_job wbland_units` is line **2742**,
before the actual quick-tier exit at line **2871** in this worktree (the launch
prompt's 2808 is not this revision's exit). Removing `detector` is **-1 quick /
-1 full** from wbland2. The cumulative wbland contribution is therefore exactly
**+2 quick / +2 full**, reduced from +3/+3. No new gate row was added.

`EXPECT_QUICK=441` and `EXPECT_FULL=461` at lines 260-261 are **untouched**.
Preserving the already documented mainline topology correction of +2 quick,
the maintainer-owned totals should become **445 = 441 + 2 topology + 2 wbland**
and **463 = 461 + 2 wbland**, plus the existing optional NIC adjustment.
Gate edits introduce no `rg`; the existing grep-based gate conventions remain.

The mainline measurement request is the **14-cell pad-controlled null** in
`tests/wbland_merit_cells.txt`, with IDs `h05,h06,p8g,p8s,d1g_l0,d1s_l0,m8g_l0,
v1g_l0,d128g_l0,d32g_l1,d8s_l1,d32s_l1,x9_32_l1,x9_32_l0`. Use the gate's
`tests/abbagate.py` instrument, the same offered load/placement for every arm,
and a fresh matched identical-binary null. All rates, cycles/op, IPC,
instructions/op, latency quantiles and send behavior are **PENDING MAINLINE**.

| Mainline comparison | Cells / purpose | Deciding number | Status |
| --- | --- | --- | --- |
| POST policy 1 vs rebuilt REF | All 14 generic cells; cost of the static knob and resulting codegen | Per-cell rate at matched offered load; the latency-scored p1 cells must retain their latency within the fresh matched null envelope. No aggregate hides a losing cell. | PENDING MAINLINE |
| PAD A vs rebuilt REF | Same 14 cells and settings | Same per-cell verdict; PAD must track POST, since their bytes are identical. | PENDING MAINLINE |
| POST vs PAD A | Same 14 cells, identical binaries | Establish the contemporaneous per-cell null spread. No policy gain is claimed from this comparison. | PENDING MAINLINE |
| pol0 LATENCY arm | Supplied for the owner's fixed-policy latency comparisons | Matched-load latency and commands/send; no adaptive fraction remains. | PENDING MAINLINE |
| Both modes and database variants | Mainline's correctness/boot gate; retain the unchanged 4096-connection cells for its scheduled merit work | Zero command regressions; 1s and 2s boot and preserve ordering/lifetime behavior. | PENDING MAINLINE |

Use the mainline's scheduled quiet-box geometry for the 14 cells (the retained
merit request uses 0-31 server and 32-111 load pools). The lane did not use
those CPUs. Keep both `tests/wbland_merit_cells.txt` and
`tests/wbland_4096_cells.txt` as supplied. The gate's own correctness geometry
remains 16 shards, `GATE_CORES` default 0-7, and its 6 IO + 2 EX split;
reproduce failures at that geometry before attribution. The mainline owns
EXPECT updates, live testing, the gate, and merge. Append live results as
`MEASURE-RESULT`. Performance acceptance remains **PENDING MAINLINE**.

The complete requested `git diff 37eeb5e90 --stat` follows (including this
report and historical lane reports, with no build binaries tracked):

```text
 MEASURE-REQUEST              |   36 +-
 MEASURE-REQUEST-wbland.md    |  364 ++++++++++
 MEASURE-REQUEST-wbland2.md   |  284 ++++++++
 MEASURE-REQUEST-wbland3.md   |  285 ++++++++
 Makefile                     |   23 +
 docs/CONFIGURATION.md        |    9 +
 src/cmd/t_server.cc          |    2 +
 src/core/config.h            |   19 +-
 src/core/server.h            |    3 +
 src/core/wb_rule.h           |   23 +-
 tests/gate.sh                |   25 +-
 tests/netcmd_config_unit.cc  |    7 +-
 tests/wb_rule_checks.py      |   10 +-
 tests/wb_rule_phase_unit.cc  |   33 +-
 tests/wbland_4096_cells.txt  |   13 +
 tests/wbland_checks.py       |  111 +++
 tests/wbland_clause_unit.cc  |   10 +
 tests/wbland_evidence.json   | 1633 ++++++++++++++++++++++++++++++++++++++++++
 tests/wbland_merit_cells.txt |   14 +
 tests/wbland_unit.cc         |   78 ++
 tomokv.conf                  |    5 +
 tools/wbland_artifacts.py    |  161 +++++
 22 files changed, 3114 insertions(+), 34 deletions(-)
```
