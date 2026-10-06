**cmdmeta / EX9 — remove orphan subcommand advertisements**

The candidate removes exactly 28 `cluster|*` and 5 `module|*` rows, taking the metadata
inventory from 374 to 341. All 245 existing registry commands and their dispatch IDs remain
unchanged. The only changed runtime source is `src/cmd/cmdmeta_generated.inc`, regenerated
from source; no handler or dispatch source was edited.

PRE is the merged `origin/cpp` / merge-base revision
`9d957b9fbb7a6eadace068b9615eef81b0dd6686`. The branch started at `b1d931ee2` and was
fast-forwarded before coding. Runtime POST source is commit `82811c591`; subsequent commits
add test and evidence files only. No push, server, load generator, live differential, benchmark,
or gate was run. Live behavior and performance tables below are predictions from source unless
explicitly identified as an offline result. The maintainer still owns live acceptance.

**Generator and exact data diff.** `tools/gen_cmdmeta.py` exists at the original `b1d931ee2`
baseline as well as after the merge. It originated in `4759a5cb6` and was last updated there
in `ed211db4a`. Thus the addendum's “no generator” premise does not hold in this checkout;
there is no reason to introduce a duplicate `tools/cmdmeta_gen.py`. The original generator
queried a live Redis `COMMAND` reply and explicitly retained every subcommand, even when its
parent was unsupported. It also lacked the already-registered, TomoKV-only FLIP metadata.

The generator now accepts `--redis-root` for offline Redis 7.4.10 command JSON, retaining the
live `--port` path. It applies Redis's public flag ordering, implicit ACL categories, legacy
key-range projection and normal-server exclusion of sentinel-only commands. The existing
FLIP row has an explicit local definition reproducing its old bytes. Registry membership is
the filter: an emitted row's name before `|` must be implemented. This is not a 33-name denylist.

Auxiliary flag, tip and key-spec tables are packed in the historical order, including unused
tip slots, before filtering advertised rows. This preserves every retained row's mask and
reference offset. After deleting the 33 PRE rows, all remaining generated data is byte-identical;
the only additional changes are two provenance comment lines. See
`docs/cmdmeta/source-audit.json` and the exact removed rows in `docs/cmdmeta/removed-rows.txt`.

Pinned input: `/home/user/Projects/redis`, revision `f103d127b9747965e28f20615ef790332661fc68`, clean
`src/commands/` and `src/version.h`, 401 JSON files. Their SHA inventory is
`docs/cmdmeta/redis-json-SHA256SUMS`, inventory digest
`93f81dbb106bf95ec32f285e1b0b5e70d48ccac75f3a687106a4d26bdf5b871e`.
The durable oracle binary is `/home/user/Projects/redis74/src/redis-server`, SHA-256
`ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`. That directory contains binaries, not the source checkout;
use `/home/user/Projects/redis` for the offline generator and ACL source checks.

```sh
python3 tools/gen_cmdmeta.py --redis-root /home/user/Projects/redis \
  --output src/cmd/cmdmeta_generated.inc
python3 tools/gen_cmdmeta.py --redis-root /home/user/Projects/redis \
  --check src/cmd/cmdmeta_generated.inc
python3 tests/cmdmeta_coverage.py --redis-root /home/user/Projects/redis
```

**Implemented surface and the literal parity limit.** The current baseline has 245 top-level
commands: 244 shared with normal Redis 7.4.10 plus the existing TomoKV-only `FLIP`. Normal
Redis has 250; its JSON contains 251 top-level definitions because `SENTINEL` is restricted
to sentinel mode. The prompt's 243/251 counts are historical and were not imposed on newer
mainline. The six normal-Redis top-level commands absent here are **cluster, migrate, module,
psync, replconf, sync**. Their 33 children below are also deliberately absent. Sentinel and its
children are absent from the normal Redis oracle too.

An unqualified “TomoKV advertises no name Redis lacks” statement would be false because of
FLIP in both PRE and POST. The differential prints this existing exception and permits exactly
`{flip}`, with only its four existing categories: write, admin, slow, dangerous. Every other
Redis-unknown target name fails. This lane does not remove FLIP or claim blanket Redis parity.

| Removed qualified name |
|---|
| `cluster|addslots` |
| `cluster|addslotsrange` |
| `cluster|bumpepoch` |
| `cluster|count-failure-reports` |
| `cluster|countkeysinslot` |
| `cluster|delslots` |
| `cluster|delslotsrange` |
| `cluster|failover` |
| `cluster|flushslots` |
| `cluster|forget` |
| `cluster|getkeysinslot` |
| `cluster|help` |
| `cluster|info` |
| `cluster|keyslot` |
| `cluster|links` |
| `cluster|meet` |
| `cluster|myid` |
| `cluster|myshardid` |
| `cluster|nodes` |
| `cluster|replicas` |
| `cluster|replicate` |
| `cluster|reset` |
| `cluster|saveconfig` |
| `cluster|set-config-epoch` |
| `cluster|setslot` |
| `cluster|shards` |
| `cluster|slaves` |
| `cluster|slots` |
| `module|help` |
| `module|list` |
| `module|load` |
| `module|loadex` |
| `module|unload` |

These 33 children plus the six top-level names are the complete 39-name Redis-only normal-server
inventory. `docs/cmdmeta/category-inventory.json` lists every expected missing name per category,
plus the explicit FLIP differences; none are hidden by intersecting the target reply.

**Enumerator contract — PRE / POST / vanilla Redis 7.4.10.** This table is source-derived,
not a live receipt. Redis references are `src/server.c:5120` (COUNT), `:5144`–`:5243` (LIST),
`:5247` (INFO), `:5268` (DOCS), and `src/acl.c:2764` (recursive CAT). TomoKV references are
`src/cmd/acl.inc:824`, `src/cmd/server_tail.cc:853`, and `src/cmd/t_server.cc:1351`.

| Query | PRE | POST | Redis |
|---|---:|---:|---:|
| COMMAND / COMMAND INFO, no names: top-level rows | 245 | 245 | 250 |
| COMMAND LIST | 374 | 341 | 379 |
| COMMAND LIST FILTERBY PATTERN `*` | 374 | 341 | 379 |
| COMMAND LIST FILTERBY PATTERN `cluster*` | 28 | 0 | 29 |
| COMMAND LIST FILTERBY PATTERN `module*` | 5 | 0 | 6 |
| COMMAND LIST FILTERBY MODULE nonexistent / cluster / module | 0 | 0 | 0 |
| COMMAND COUNT (top-level registry only) | 245 | 245 | 250 |
| COMMAND INFO cluster / module | one nil entry | one nil entry | populated container row |
| COMMAND DOCS cluster / module | empty | empty | populated documentation |
| COMMAND INFO each removed child | populated orphan row | one nil entry | populated row |
| COMMAND DOCS each removed child | compact documentation | empty | populated documentation |

Unknown INFO is an array containing nil; unknown DOCS is an empty array in RESP2 or empty map
in RESP3. DOCS does not return a scalar nil. MODULE filters select loaded module commands,
not the built-in MODULE administration family; the vanilla oracle has no loaded modules.

ACL CAT and COMMAND LIST FILTERBY ACLCAT share these category cardinalities:

| Category | PRE | POST | Redis |
|---|---:|---:|---:|
| keyspace | 33 | 33 | 34 |
| read | 91 | 91 | 91 |
| write | 113 | 113 | 113 |
| set | 19 | 19 | 19 |
| sortedset | 37 | 37 | 37 |
| list | 24 | 24 | 24 |
| hash | 25 | 25 | 25 |
| string | 22 | 22 | 22 |
| bitmap | 7 | 7 | 7 |
| hyperloglog | 5 | 5 | 5 |
| geo | 10 | 10 | 10 |
| stream | 23 | 23 | 23 |
| pubsub | 13 | 13 | 13 |
| admin | 63 | 42 | 65 |
| fast | 108 | 108 | 108 |
| slow | 266 | 233 | 271 |
| blocking | 12 | 12 | 12 |
| dangerous | 72 | 51 | 75 |
| connection | 38 | 38 | 38 |
| transaction | 5 | 5 | 5 |
| scripting | 21 | 21 | 21 |

For each of all 21 categories, the differential compares the whole target set with the oracle
set intersected with registry-supported families, plus the named FLIP exception. It separately
rejects unexpected target advertisements. It also checks all LIST names, duplicate names,
registry membership, 96 retained and 129 oracle pipe names, eight pattern filters including
mixed case, three MODULE filters, and registry-based COUNT. All 39 deliberately absent names
get individual INFO and DOCS checks, while the oracle must return correctly shaped populated
metadata. Generic unknown-name replies are checked on both peers. The 4,200 existing direct
INFO/key-intent comparisons remain, sampling only implemented subcommands.

One unrelated pre-existing difference found while reading: COMMAND LIST FILTERBY ACLCAT with
an unknown category returns an error here (`server_tail.cc:873`), while Redis returns an empty
list (`server.c:5156`). EX9 changes neither behavior. Valid-category agreement above covers all
21 known categories; it does not claim this invalid-category case is fixed.

**Consumers and gate rows.** `tests/cmdmeta_coverage.py` now rejects orphan parents and
regenerates/diffs the include using pinned JSON. The existing gate row passes its source root
explicitly. `tests/differ.py` replaces the former 129-subcommand expectation with the complete
surface checks above. `tests/cmdmeta.py` likewise checks 96 subcommands, registry-based COUNT,
and every removed name in RESP2 and RESP3. That standalone directed battery is not in this
baseline's `FEATURE_BATTERIES` list; the full differential discovers the existing `cmdmeta`
suite through `--list-generators`.

`tools/exbatch_source_proof.py:79`–`:80` does pin the include to its historical PRE revision
`cd02ecbab1502775f1c170e806971d1f7bbc3ee9`. No Makefile, gate, test, hook or tool invokes that
historical proof. It is unchanged, not repointed or weakened. The gate's distinct
`tests/exbatch_checks.py metadata` compares current candidate metadata against its algorithm
control using the same current table; it does not compare this table to historical PRE bytes.

Rows **+0 quick / +0 full**. The modified static row is defined at `tests/gate.sh:1778` and
collected at `:3233`, before the quick exit at `:3352`. The already-existing differential folds
at `:3380` and `:3391` are after that exit. No row was added or retired. `EXPECT_QUICK=499` and
`EXPECT_FULL=516` remain untouched and should remain those values for this lane.

**Offline validation and falsification.** Both full production builds succeeded with GCC
13.3.0, default Makefile flags, on CPUs 0–15 with `-j12`. The generator drift/coverage check,
Python compilation, shell syntax and `git diff --check` pass. Six serverless Python tests pass.
Both the differential's surface assertions and the directed absence checks reject EACH of the
33 orphans reintroduced individually. Additional controls reject a missing GET, a new phantom,
wrong category membership, counting subcommands, empty ACL filters, module leaks, scalar-nil
DOCS, empty oracle family results, error replies substituted for known oracle metadata, and a
retained GET arity corrupted in the generated file. See `docs/cmdmeta/offline-tests.log`.
These scripted peers validate the tests' ability to fail; they are not live server evidence.

```sh
REDIS74_ROOT=/home/user/Projects/redis python3 tests/cmdmeta_test.py
python3 tests/respcompat_audit.py build/cmdmeta/PRE build/cmdmeta/POST docs/cmdmeta/body-audit
python3 tools/cmdmeta_audit.py build/cmdmeta/PRE build/cmdmeta/POST docs/cmdmeta \
  --pad build/cmdmeta/PAD-A/tomokv
```

**Hot-body proof.** The existing relocation-aware tool audited 16,934 function instances
across 88 production objects. All 1,580 selected hot functions have identical raw bytes and
resolved relocation targets. The additional command-wide audit proves **1,225/1,225 `cmd_*`
object bodies byte-identical**. All executable sections in 86/88 objects are identical; only
the two `cmdmeta.o` namespace variants differ. Registry family order and all 245 IDs match
PRE (`docs/cmdmeta/registry-order.json`). Dispatch uses the name hash in `commands.cc:272`;
metadata initialization looks up each registry name and stores its pointer at `spec.id`
(`cmdmeta.cc:268`). Generated lexical row indices are not dispatch IDs.

All changed metadata bodies are listed below. Each appears in both `tomo` and `tomo_db0`.
Bytes and static instruction counts have the same PRE and POST values; the changed constants
or relocation targets are the reason for each byte difference. Static instructions are not
retired instructions/op.

| Body | PRE bytes / POST bytes | PRE instructions / POST instructions | Reason |
|---|---:|---:|---|
| child_count | 155 / 155 | 46 / 46 | Metadata scan end and index data shrink |
| reply_info_row | 4630 / 4630 | 1049 / 1049 | Metadata scan end and index data shrink |
| command_metadata_at | 35 / 35 | 10 / 10 | Bound 374 → 341 |
| command_metadata_size | 10 / 10 | 3 / 3 | Count 374 → 341 |
| command_metadata_lookup | 344 / 344 | 103 / 103 | Count 374 → 341; max name 29 → 23 |
| command_metadata_resolve | 1678 / 1678 | 389 / 389 | Derived scratch/name bounds 29 → 23 |
| command_metadata_resolve cold clone | 40 / 40 | 9 / 9 | Same derived bounds/stack cleanup |
| command_metadata_collect_keys (tomo) | 5253 / 5253 | 1207 / 1207 | Raw bytes identical; key-flag/spec/switch table relocations move |
| command_metadata_collect_keys (tomo_db0) | 5237 / 5237 | 1203 / 1203 | Raw bytes identical; key-flag/spec/switch table relocations move |
| command_metadata_key_flag_name | 25 / 25 | 8 / 8 | Raw bytes identical; key-flag table relocations move |

The complete data and disassemblies are in `docs/cmdmeta/changed-metadata-bodies.json` and the
adjacent PRE/POST `.asm` files. `ordinary-command-bodies.json` records each body hash;
`body-audit/hot-bodies.json` records the existing hot selection.

Linked binaries have the same **7,797,900-byte .text** and the same addresses/sizes for all
**10,350 functions**. Literal linked bytes are not universally identical: 2,346 functions
differ. Of these, 2,331 differ only within ELF relocation fields of otherwise byte-identical
object bodies, 14 are the metadata helpers above, and `_start` only changes its displacement
to the moved `__libc_start_main` GOT entry. This includes 252 ordinary command bodies whose
linked address fields change; every differing byte in those bodies is checked against its
object relocation fields. There are no unexplained ordinary opcode changes. The full per-body
list, offsets, targets and reasons is `docs/cmdmeta/linked-byte-changes.json.gz`.

The data layout does change: `.rodata` shrinks 163,429 → 162,661 bytes, and `.data.rel.ro`
66,808 → 63,672 bytes. **PAD-A is a kind (A) behavior twin: PRE behavior with POST text
size and every function address/size.** PRE already has that text layout, so PAD-A is a verified
byte-for-byte copy of PRE. It is a degenerate text-layout control, not a control for the smaller
metadata/data sections. There is no inverse PAD-B because .text does not change size. No rate
or cycles/op improvement is claimed from this static evidence.

**Artifacts and SHA-256.** POST was copied to `build/tomokv`; their bytes match. Full hashes:

| Arm | Path | SHA-256 |
|---|---|---|
| PRE | `build/cmdmeta/PRE/tomokv` | `843ac6ecc49061d6a21bad40200fe90f4df4445a4e1785d7a1dee6d2a62d0dd0` |
| POST | `build/cmdmeta/POST/tomokv` | `950b66364c99cea849a5f02328419b937ca23bc059b48c93fdae0625c6b79b1c` |
| POST copy | `build/tomokv` | `950b66364c99cea849a5f02328419b937ca23bc059b48c93fdae0625c6b79b1c` |
| PAD-A (kind A) | `build/cmdmeta/PAD-A/tomokv` | `843ac6ecc49061d6a21bad40200fe90f4df4445a4e1785d7a1dee6d2a62d0dd0` |

PRE source is archived at `build/cmdmeta/PRE-src`, compiled with
`taskset -c 0-15 make -C build/cmdmeta/PRE-src -j12 BUILD_ROOT=$PWD/build/cmdmeta/PRE`.
POST used `taskset -c 0-15 make -j12 BUILD_ROOT=build/cmdmeta/POST`. Build logs are retained
in `build/cmdmeta/PRE-build.log` and `POST-build.log`.

**Maintainer measurement request — not executed.** Run the gate's own oracle harness in
both split and armed-fused shapes. The split geometry is 16 shards, cores 0–7, ratio 6:2;
fused uses the same cores/shards with read-local 1 and omits the invalid fused ratio flag.
The harness covers atomic 0/1 and permanent seeds 7/19 plus its rotating seed, and owns both
server lifetimes. It discovers the modified `cmdmeta` suite without adding a gate row.

```sh
for geometry in split armed-fused; do
  REDIS74_ROOT=/home/user/Projects/redis \
  GATE_DIFFER_ORACLE_BIN=/home/user/Projects/redis74/src/redis-server \
  GATE_DIFFER_REDIS_CLI=/home/user/Projects/redis74/src/redis-cli \
  GATE_DIFFER_GEOMETRY="$geometry" \
  GATE_DIFFER_OUT="$PWD/build/cmdmeta/live-POST-$geometry" \
    tests/differ_gate.sh "$PWD/build/cmdmeta/POST/tomokv" 7899 7900 0-7 6:2
done
```

Acceptance: POST has zero cmdmeta differences, 21 categories checked, 96 retained subcommands,
78 absent-name INFO/DOCS checks, all explicit Redis-only names printed, registry COUNT 245,
and no Redis-unknown name beyond the already-existing FLIP exception. On maintainer-owned
PRE/PAD-A boots, the same cmdmeta suite must fail on the orphan advertisements and populated
orphan INFO/DOCS. Also run `tests/cmdmeta.py HOST PORT` on POST (it checks both RESP versions),
and `tests/differ.py HOST PORT ORACLE_HOST ORACLE_PORT cmdmeta 7 -3` for RESP3 differential
coverage on those harness-owned endpoints. These are assertions of required outcomes, not
recorded live passes.

Then run `tests/gate.sh iteration` from this source, with `REDIS74_ROOT=/home/user/Projects/redis`,
the durable oracle binary override above, and `--reference-binary` pointing at PRE. A normal
source build is needed for a source receipt; passing `--candidate-binary` yields only a diagnostic
receipt under the existing gate rules. No EXPECT count changes are requested.

For the ordinary-command performance null, use the existing `tests/abbagate.py` instrument:
PRE vs POST, cells **h01,h02,h09,h10,h17,h18,h25,h26,h33,h34,h41,h42,h49,h50,h57,h58**
(GET/SET × p1/p32 × both modes × read-local 0/1, overlap/reorder 0, atomic 1, 512 connections).
Use its calibrated load, matched null, and sequential ABBA arms. The instrument derives its
performance shard/ratio geometry; record it and do not confuse it with the correctness 16-shard,
6:2 shape. Rate at matched offered load and the gate's per-cell verdict decide acceptance;
retain cycles/op, IPC and instructions/op for explanation, and p1 latency scores where the
cell definition requires them. Reject an ordinary-command regression beyond the gate's measured
null resolution. A PRE-vs-PAD-A control is byte-identical by construction, not another candidate.

| Performance result | PRE | POST | Verdict |
|---|---|---|---|
| 16 ordinary-command cells above | pending maintainer | pending maintainer | pending |
| Full iteration correctness / live Redis differential | pending maintainer | pending maintainer | pending |

Append measurements and live receipts as `MEASURE-RESULT`. The source diff, all offline checks,
and the exact binaries are ready for that step.
