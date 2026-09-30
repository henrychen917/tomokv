**cleanup-ttlstate — unused wrapper removed; production code is byte-identical.**

Reference frozen at launch: `37eeb5e90be9997805cfe2456021ad07dc0c18f9`
(`origin/cpp` and the clean worktree HEAD). Worktree/branch:
`/home/user/Projects/cx-cleanup-ttlstate`, `cx-cleanup-ttlstate`.
Production change: `459ddd77c76ae980d035424833e47aa27f8a6c95`.
Offline proof implementation: `a4053224e`, finalized in `2ce640e1b`.
All builds and serverless checks used `taskset -c 112-127`; builds used `make -j16`.
No server, benchmark, gate, performance measurement, or push was run.

The full debug ELF files differ. Their executable sections, runtime data, relocation
targets, entry point, load mappings, and function addresses do not. **No PAD is
required; the production-code identity proof discharges this lane's performance-null
requirement.** No performance gain is claimed. Live correctness and unrun measurements
are **PENDING MAINLINE**, not reported as passes.

**Diagnosis, history, and exact scope.** At the frozen reference, the complete
tracked-tree symbol inventory is:

```text
src/store/kvobj.h:228:    TtlState ttl_state() const { return TtlState{expire_at_ms(), has_ttl_slot()}; }
src/store/store_ttl.h:23:struct TtlState {
src/store/store_ttl.h:37:    constexpr TtlState with_deadline(int64_t new_deadline) const {
src/store/store_ttl.h:45:    constexpr TtlState persisted() const {
```

There are no callers of `ttl_state()`, and no use of the wrapper outside its own
definition and that accessor. The independent whole-tree search included hidden and
ignored files, excluding `.git` and generated `build/`; it found the same four lines.
The source assertion scanned all 446 text files under `src`, `tests`, and `tools`.
POST contains zero occurrences in those directories, confirmed independently by `rg`
(exit 1). References in this report and archived PRE/control fixtures are evidence,
not consumers.

Retained evidence under `build/cleanup-ttlstate/freeze/`:
`symbol-inventory-tracked.txt`, `symbol-inventory-whole-tree.txt`,
`retained-inventory.txt`, `history-wrapper.txt`, `history-introduction.txt`,
`tracked-inputs.json`, and the complete `reference.tar`.
The reachable symbol history identifies introduction in
`8b575f4fbbb766e465823044471ab4f46c99113f`, “store: retain TTL deadline slots across
key lifetime.” That change wired the physical reservation bit and deadline arguments
directly through constructors and replacement paths, independently of the unused wrapper.

**Conclusion: unused convenience residue, not an unwired live contract or a constant-return
defect.** The real producers are constructors and TTL-preserving replacements; the
consumers read the physical slot bit and deadline directly. In POST:

| Retained contract | Verified anchors |
|---|---|
| Selector, validation, deadline sentinel | `src/store/store_ttl.h:8`, `:14`, `:17`, `:18` |
| Physical slot bit and logical deadline | `src/store/kvobj.h:54`, `:115`, `:221`, `:227` |
| Physical reservation in constructors | `src/store/kvobj.h:790` onwards; `reserve_ttl_slot || expire_at_ms >= 0` at `:794` |
| Replacement preserves old slot reservation | `src/store/kvobj.h:1042` (`kvobj_reheader`) |
| KEEPTTL propagates slot and deadline | `src/cmd/t_string.cc:471`, `:472`, `:523`, `:524` |
| Owner deadline lookup, EXPIRE, PERSIST | `src/store/flatstore.h:1433`, `:1485`, `:1512` |
| Armed read-local paths retain replacement guards | `src/store/flatstore.h:1253`, `:1486`, `:1516`, `:3129` |
| Sidecar build and scored row | `Makefile:141`, `:144`; `tests/gate.sh:1321` |

Only `TtlState`, its comments, and the uncalled accessor were removed; the header
description now names its remaining sentinel and selector. The constructors begin at
PRE `kvobj.h:791`, not the older audit's `:762`. The sidecar target is now at
`Makefile:141–144`, not `:134–137`. All other production files, the Makefile, tests,
offset assertions, and gate constants are unchanged. No new knob, TTL algorithm,
type-adoption change, or live TTL-preservation assertion was added. No remaining
cleanup defect or correctness-law conflict was found in the inspected TTL paths;
this does not claim a new audit of unrelated engine paths.

**Build and object inventory.** PRE was built and frozen before either production
header was edited. Both arms used the same absolute working directory, relative
source/output paths, GCC 13 compiler, `-std=c++20 -O2 -g -Wall -Wextra -march=native
-pthread`, jemalloc, and every existing per-target compiler budget/database define.
No flags, padding, prefix maps, or inline budgets were changed.

`freeze/make-dry-run.txt` and `POST-build-commands.txt` are byte-identical.
Both production logs contain all 84 compiler invocations and zero warnings.
Compiler-discovered dependency graphs were regenerated for every POST object and
match PRE. Dependency hashes differ only for the two edited headers; compiler,
assembler, linker, selected compiler dependencies, and recorded link inputs match.
See `freeze/environment.json`, `freeze/compiler-dependencies.json`,
`freeze/link-dependencies.jsonl`, `freeze/dependency-sha256.json`,
`input-comparison.json`, and `dependency-graph-comparison.json`.

`Makefile:41–47` defines/links **42 normal + 42 db0 objects**, all declared dependent
on both headers by the wildcard prerequisite rules. **33 per variant (66 total)**
also include them transitively. Every one of the 84 objects was compared, including
the 18 declared-only dependents. Each suffix below exists under both `build/` and
`build/db0/`; `yes` means the compiler dependency graph contains both headers.

| Object suffix (both variants) | Transitive includes |
|---|---|
| `src/main.o` | yes |
| `src/net/tls.o` | yes |
| `src/cmd/commands.o` | no; declared dependency only |
| `src/cmd/glob.o` | no; declared dependency only |
| `src/cmd/xshard.o` | yes |
| `src/cmd/acl.o` | yes |
| `src/cmd/hll.o` | no; declared dependency only |
| `src/cmd/t_server.o` | yes |
| `src/cmd/t_string.o` | yes |
| `src/cmd/t_string_notify.o` | yes |
| `src/cmd/t_hash.o` | yes |
| `src/cmd/t_hash_ttl.o` | yes |
| `src/cmd/t_list.o` | yes |
| `src/cmd/t_set.o` | yes |
| `src/cmd/t_zset.o` | yes |
| `src/cmd/t_zset_ops.o` | no; declared dependency only |
| `src/cmd/geo.o` | yes |
| `src/cmd/t_stream.o` | yes |
| `src/cmd/t_stream_groups.o` | yes |
| `src/cmd/scripting.o` | yes |
| `src/cmd/functions.o` | yes |
| `src/cmd/serialize.o` | yes |
| `src/snapshot/snapshot.o` | yes |
| `src/persist/aof.o` | yes |
| `src/cmd/climon.o` | yes |
| `src/cmd/tracking.o` | yes |
| `src/cmd/server_tail.o` | yes |
| `src/cmd/slowlog.o` | yes |
| `src/cmd/lcs.o` | no; declared dependency only |
| `src/cmd/info_stats.o` | no; declared dependency only |
| `src/cmd/lbsignals.o` | yes |
| `src/core/flipctl.o` | yes |
| `src/core/genthread.o` | yes |
| `src/core/rl2s.o` | yes |
| `src/core/lbstall.o` | yes |
| `src/cmd/l4prebuild.o` | yes |
| `src/cmd/cmdgap.o` | no; declared dependency only |
| `src/cmd/pfdebug.o` | yes |
| `src/cmd/cmdmeta.o` | no; declared dependency only |
| `src/cmd/t_sort.o` | no; declared dependency only |
| `src/cmd/multidb.o` | yes |
| `src/core/reorder.o` | yes |

The complete per-object argv and dependencies are retained in
`freeze/object-inventory.json`, its readable `.tsv`, and raw compiler `.d` files.
Five supplemental artifacts were built on both arms: `store-regression`,
`store-regression-sidecar`, `store-regression-tsan`, and normal/db0
`tests/multidb_layout.o`. Their code/data/relocations were also compared. Optional
server/sanitizer configurations not built here are not presented as independent
build results.

**Raw-byte proof and artifacts.** All paths below are relative to the worktree.

| Arm / artifact | Bytes | SHA-256 |
|---|---:|---|
| PRE: `build/cleanup-ttlstate/PRE/artifacts/tomokv` | 177052944 | `fcbdb5e9c94ce6ea9bd685683bee5a9bfc550fac6d36105f4b7a148fa2470c00` |
| POST: `build/cleanup-ttlstate/POST/artifacts/tomokv` | 177036592 | `cbd332905eea669f9c7b3bd8ffdd8d105a4e43cc14400cec2362875968a608fa` |
| PRE and POST `.text` | 7576545 each | `4cc92507f649aeb5185c4009e67713f9d597c88716e18f932535a73c1471e0d7` |
| PRE and POST inspection-only stripped ELF | 8667912 each | `4072dc24218e80134318150ac7954b95017054121b0833377179d75c2371f37d` |
| PAD | — | Not needed; no executable-byte, text-size, or address/alignment change |

`PRE/` and `POST/` each retain all 90 artifacts, their SHA-256 manifest, raw
`objdump -drw`, `readelf -W -h -l -S -s -r`, `nm -anSC`, individual executable-section
binary dumps, resolved relocation records, and allocated symbol addresses. Section
manifests map dump filenames to exact ELF section names, addresses, and alignment.

| Compared state | Result |
|---|---|
| Production: all 84 objects + linked server | **85/85 PASS** |
| Production executable sections, including empty `.text` and all `.text.*` | **8536/8536 byte-for-byte equal**, including **8446 `.text.*`** sections |
| Total production executable bytes compared, counting objects and linked image | **19678186 equal** |
| Production allocated relocation records | **201541 equal targets/types/offsets/addends**; non-debug raw relocation sections also equal |
| Production allocated symbol records | **46672 unchanged addresses/attributes**, with local marker spellings accounted for below |
| Linked executable | All **7586377 executable bytes**, **3786 relocations**, and **10626 allocated symbol addresses/attributes** equal |
| Allocated data, zero-fill layout, entry point and program headers | Equal, except the explicitly identified debug-dependent GNU build ID |
| Supplemental artifacts | **5/5 PASS**; complete audit **90/90**, **8559 executable sections** |

The full ELF size falls by 16352 bytes solely in non-executable metadata. Stored
section differences across the audit are DWARF/debug relocations, `.strtab`, and
linked `.note.gnu.build-id`. Every raw `.symtab` remains byte-identical. GCC renumbered
51 linked local zero-size marker names: 49 `tomo_multidb2_pad_%=` markers from
`src/store/kvobj.h:200`, and two `tomo_rltopo_demote_%=` markers from
`src/core/ex_loop.h:1295`. Their sections, addresses, sizes, binding, and visibility
are unchanged. No function name/address comparison is relaxed. The checker permits
only the numeric spelling change for these two local marker families; it still
rejects a moved marker. Raw executable bytes are never masked or normalized, and
relocation-target comparisons retain exact symbol identities.

`identity-marker-name-review.json` retains the initial stricter name mismatch;
`symbol-metadata-difference.json` records the linked names before/after. The final
`identity.json`, `production-identity.json`, and `summary.json` record the complete
address-preserving result. As an additional whole-file check, inspection copies
made with `objcopy --strip-all --remove-section=.note.gnu.build-id` compare equal.
Those non-executable-permission copies were never run; the original arms are intact.
No existing R7 PAD was reused. Kind A/B padding is inapplicable: `.text` delta is zero.

Artifact ledger: `build/cleanup-ttlstate/SHA256SUMS`, **19113 files**, SHA-256
`7038772e56db6a674b83793701cef6bcb2038e0ddbf59d27595a476525e9f68b`.
The checker itself has SHA-256
`393989dad3e8bdaae68ad0ee31d63acf32f5a5a49cdca9d363abc895952a3660`.

**Assertions and throwaway negative controls.** Results are in `controls.json`,
with individual JSON/logs and copied fixtures under `controls/`. All deliberately
modified ELF copies have mode 0600 and were never executed.

| Assertion and exercised state | Exact failure / throwaway control | Observed result |
|---|---|---|
| PRE inventory has only the definition/self-return types and unused accessor; POST has none in source/test/tool text | Restore the exact PRE accessor line into a copied POST source tree | Source check **exit 1**, exactly one offending accessor line; positive PRE/POST checks exit 0 |
| Linked `.text` bytes are identical | Flip one byte in a copied linked executable | **exit 1**, `executable .text: bytes differ` |
| Object `.text.*` bytes are also covered | Flip one byte in `.text._ZN4tomoL12atomic_epochERKNS_11AtomicEntryE` in a copied string object | **exit 1**, named executable subsection bytes differ |
| Relocation targets remain identical even if opcode bytes do | Increment one executable-section RELA addend in the copied string object | **exit 1**, `allocated relocation targets differ` |
| Linked function addresses remain identical even if opcode bytes do | Increment one linked function symbol value | **exit 1**, `allocated symbol addresses/identities differ` |
| Permitting GCC marker renumbering cannot hide a moved marker | Increment one local patch-marker symbol value | **exit 1**, `allocated symbol addresses/identities differ` |
| Positive control for the ELF checker | Compare POST to itself | **exit 0** |

The restored-accessor fixture is a lexical source-inventory control, not a compiled
runtime fixture. It does **not** claim runtime coverage of the removed accessor or
of retained TTL propagation. Existing runtime storage assertions were not changed;
there is no newly asserted timing window or live TTL assertion needing a new control.

Recheck the archived arms without executing them:

```bash
cd /home/user/Projects/cx-cleanup-ttlstate
taskset -c 112-127 sha256sum -c build/cleanup-ttlstate/SHA256SUMS
taskset -c 112-127 python3 tools/ttlstate_proof.py source . --expect absent \
  --output build/cleanup-ttlstate-source-recheck.json
taskset -c 112-127 python3 tools/ttlstate_proof.py compare \
  build/cleanup-ttlstate/PRE build/cleanup-ttlstate/POST \
  --output build/cleanup-ttlstate-identity-recheck.json
# Use a fresh destination for another isolated negative-control run.
taskset -c 112-127 python3 tools/ttlstate_proof.py controls . \
  build/cleanup-ttlstate/freeze/files/src/store/kvobj.h \
  build/cleanup-ttlstate/POST/artifacts/tomokv \
  build/cleanup-ttlstate/POST/artifacts/src/cmd/t_string.o \
  build/cleanup-ttlstate-controls-recheck \
  --output build/cleanup-ttlstate-controls-recheck.json
```

**Serverless validation and remaining mainline correctness.** Both arms passed
all 11 ordinary storage cases (`unlinked`, `randomkey`, `rehash`, `rollback`,
`snapshot-eviction`, `flags`, `aof-eviction`, `intents`, `imported-hash`,
`field-index-failure`, `hash-bytes`), the sidecar deadline regression, and
`setarch x86_64 -R ./build/store-regression-tsan flags`: **13/13 per arm**.
Logs and results are `PRE-*` / `POST-*` under the artifact root. Production builds
had zero warnings. Supplemental builds emitted the same 17 warnings per arm:
existing non-standard-layout `offsetof` diagnostics and GCC's TSan
`atomic_thread_fence` diagnostic. TSan execution itself returned 0.

Existing compile-time locks and both exported `multidb_layout_values` arrays match:
Op **336**, Client **1984**, ThreadCtx **1408**, Shard **1440**, FlatStore **944**,
Rob&lt;64&gt; **192**, AtomicEntry **144**, Config **624** bytes. All 21 exported size/offset
values per database variant match PRE; `PRE-layout.json` and `POST-layout.json`
retain them. Both database implementations and both thread modes' production code
are included in the byte proof. Real boots are **PENDING MAINLINE**.

Mainline must retain the existing storage/sidecar rows, multidb serverless owners
and QSBR checks, DUMP/RESTORE TTL/restart coverage, and FLIP TTL. The owner row and
live batteries were not run by this lane. Run the normal mainline gate with these
exact arms, on the maintainer's scheduled box:

```bash
cd /home/user/Projects/cx-cleanup-ttlstate
tests/gate.sh iteration \
  --candidate-binary "$PWD/build/cleanup-ttlstate/POST/artifacts/tomokv" \
  --reference-binary "$PWD/build/cleanup-ttlstate/PRE/artifacts/tomokv"
```

The unchanged planner supplies each correctness slot's eight server cores,
`--shards 16`, and reviewed `6:2` split; preserve the 1s/2s, read-local 0/1,
databases 1/16 coverage. For the explicit TTL wire battery on each mainline-owned
boot, use `python3 tests/dumpttl.py 127.0.0.1 "$PORT"` and
`python3 tests/dumprestore.py 127.0.0.1 "$PORT"`. FLIP remains the existing split-mode
gate boot and `python3 tests/flip_ttl.py 127.0.0.1 "$PORT"`. These commands are requests,
not lane execution results. Gate-native ABBA reporting is not a substitute for the
separate frozen-instrument contract below; this lane relies on byte identity.

**Frozen mainline A/B contract.** PRE is the launch reference, POST is the single
production deletion above, PAD is absent. The exact h01–h64 lines are frozen in
`freeze/h01-h64.txt` (SHA-256
`3e9746718872cd80fb1c710c29430d78b85669b9231392685d137294b85747de`), with the entire
launch cell file at `freeze/files/tests/headline_cells.txt` (SHA-256
`d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350`).
The complete launch ledger, payload sources, and per-cell load-plan copies are
retained; `freeze/mainline-contract.json` maps each of the 64 IDs without modifying
any cell. Ledger SHA-256:
`e54dd9ba11efc5a989c62191c5875af8fcf19e04ac1d2bc0d417b53432634587`.

The cells retain 512 **total** connections, GET/SET, p1/p32, both modes, all
read-local/overlap/reorder combinations, atomic=1, 2,000,000 keys, 64-byte payload,
P:P key pattern, ABBA order, 3-second warmup, 20-second central window, and 5-second
tail. No candidate-dependent changes to payloads, offers, load-worker counts, or
placement were made.

Read-only copies of the nullrefresh5 freeze and instrument manifest are under
`freeze/nullrefresh/`. Recorded instrument fingerprint:
`cc6c06bde1ce7939b7f001489fde7287476c4086929f51badf774811d087dd36`;
manifest SHA-256:
`ce0967f2e8b932367c3da15f276eec21b561cb8d7ddc11ca31b954671378f683`.
Its frozen stable binary SHA-256 is
`ef52de792f72ab8dae240fcd8194e1f14aa94b3828dc7e512eea7256b50c1133`, based on
`9c4717da03b9340377926277f8eb99cea9f5ab5a`, distinct from this lane's PRE.
The launch ledger separately names stable binary SHA-256
`84ddb8abba4d8c32196edadb860da45114379490432a900dfee76efb71bfdd72` at that older commit.
Neither identity is silently substituted for the lane's frozen reference.

**Per-cell measured resolution is unavailable, not fabricated.** The available
nullrefresh freeze is for 32 server cores / 16:16; its recorded promoted
`full-null.json` path was absent. The launch ledger has no h33–h64 load floors and
no reviewed eight-core ABBA geometry/null bands. The contract records missing plans
and null epsilons explicitly. No candidate measurement was started against these
unqualified plans. This does not block this cleanup's null proof: raw production
identity discharges it. Measurements below remain **PENDING MAINLINE** if requested.

| Regime | PRE / POST cycles/op, instr/op, IPC, rate, tails | Null disposition |
|---|---|---|
| Neutral: GET without TTL | PENDING MAINLINE; unmeasured | Discharged by code/data/address identity |
| Touched semantics: TTL SET / EXPIRE / PERSIST / KEEPTTL | PENDING MAINLINE; unmeasured | Same production identity; no gain presumed |
| Possible deficit: expiry churn / sidecar-enabled storage | PENDING MAINLINE; unmeasured | Production identity plus byte-identical sidecar regression executable code |
| Benefit | None claimed | No optimization claim |

If any rebuilt/rebased candidate changes executable bytes or layout, this proof no
longer applies. Before measuring that candidate, mainline must freeze the validated
instrument digest, stable-reference SHA, each cell's resolution and separate
`epsilon_cyc`, `epsilon_rate`, and `epsilon_tail`; establish the productive-role
plateau with enough connections/workers at p1 **and** p32; use matched offered
loads, 16 shards, reviewed eight-core 6:2 split, 1s too, read-local 0/1, and databases
1/16. Preserve the frozen generic cells and append the three named regimes above.
No single-connection saturation or reuse of 32-core floors as eight-core evidence.

A changed-code candidate requires a separately justified **kind-A PAD behavior
twin: PRE behavior with POST text size/layout**, including hot-function
addresses/alignment. A footer of NOPs is insufficient; add kind B only if `.text`
changes by more than a few hundred bytes. Run the mainline's frozen 14 generic
null cells plus feature regimes; retain the h01–h64 guard contract. No prior R7 PAD
is a control for this cleanup.

For **each** cell and applicable pair PRE/POST, PRE/PAD, PAD/POST, require
`abs(100 * (Y_cycles / X_cycles - 1)) <= epsilon_cyc[cell]`, rate loss
`100 * (1 - Y_rate / X_rate) <= epsilon_rate[cell]`, and each relevant tail increase
`100 * (Y_tail / X_tail - 1) <= epsilon_tail[cell]`. Bands must be independently
validated and fixed before POST; no averaging away a losing cell or widening a
band. Report cycles/op together with instr/op and IPC
(`cycles/op = instr/op / IPC`), achieved rate and tails, separately by regime.

**Gate arithmetic and final source state.** No row was added, retired, or modified.
Storage cases emit at `tests/gate.sh:1302` (results `:1316/:1318`), sidecar at `:1321`
(`:1325/:1326`), owners at `:1330` (`:1335/:1336`), DUMP/RESTORE feature rows at `:757`
and `:790`, restart rows at `:1707/:1716/:1722`, and FLIP TTL at `:1920`. All are
before the actual quick exit at **`:2854`** (the older `:2808` anchor moved).
Storage/owner collection is at `:2728/:2730`.
**Quick 441 + 0 = 441; full 461 + 0 = 461.** `EXPECT_QUICK` at `:260` and
`EXPECT_FULL` at `:261` are untouched. The reference's maintainer-reported 461 rows /
0 gating FAIL is provenance, not a gate run by this lane.

Requested `sha256sum build/tomokv`:

```text
cbd332905eea669f9c7b3bd8ffdd8d105a4e43cc14400cec2362875968a608fa  build/tomokv
```

`git diff 37eeb5e90 --stat` (`origin/cpp` at launch), including this report:

```text
 MEASURE-REQUEST-cleanup-ttlstate.md | 363 ++++++++++++++++++++++++++++++++++++
 src/store/kvobj.h                   |   1 -
 src/store/store_ttl.h               |  32 +---
 tools/ttlstate_proof.py             | 362 +++++++++++++++++++++++++++++++++++
 4 files changed, 726 insertions(+), 32 deletions(-)
```

All intended source/proof/report changes are committed on this lane; nothing was
pushed. Live batteries, boots, full gate, and unrun measurements: **PENDING MAINLINE**.
