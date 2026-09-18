**cmdfix handoff — 2026-09-18.** Reference: `8a5c0ed0da868c8ae77b7402896b1bf86a03a02f`.
Branch: `cx-cmdfix`; worktree: `/home/user/Projects/cx-cmdfix`. S4 and S5 are fixed,
with regressions demonstrated failing before and passing after in both compiled
database variants. No server process, load generator, benchmark, or gate was run.
Builds used `taskset -c 112-127 make -j16`; units stayed on those CPUs. The
eight-core boundary fixture used the subset `112-119`.

**Acceptance still outstanding.** The maintainer must establish the ABBA null and
the full **454 rows / 0 gating FAIL** result. The requested broad db0 dispatch byte
identity is **not met**: GET/SET handler object bodies are byte-identical, but the compiler
changed other dispatch/execution bodies after S5. These differences are reported
below, not counted as a byte-identity pass or a performance-neutrality result.

**S4 diagnosis and fix.** At the reference, the four native collection loaders
accepted a zero-byte payload and returned an empty object. Their snapshot and AOF
callers (`src/snapshot/snapshot.cc:981`, `src/persist/aof.cc:2533`) check status and
object presence, not cardinality. Each loader now returns `Corrupt`, with a null
result, before allocating for an empty payload. This matches the existing native
conversion boundary in `src/cmd/serialize.cc:709`, `:716`, `:754`, and `:787`.
An empty string member/field/value is still a valid *one-entry* collection.

`SRANDMEMBER` and `SPOP` lacked the zero-entry check already present in
`HRANDFIELD` (`src/cmd/t_hash.cc:1386`). Without a count they emitted no reply;
negative-count SRANDMEMBER could announce members it never emitted.
`ZRANDMEMBER` dereferenced the null result of the expanded table's `random_node()`
(`src/cmd/t_zset.cc:283`). One correction to the audit's wording: `Slice` initializes
its pointer/length to null/zero (`src/base/slice.h:126`), so the compact scalar case
returned an incorrect empty bulk, not an uninitialized Slice. The failed rank
lookup also left the score uninitialized for negative-count `WITHSCORES`.

The three handlers now mirror their absent-key replies when cardinality is zero.
The guards follow argument validation/type checking and precede random selection.
No nonempty-case reply formatting was changed. Hash recovery with a **nonempty**
field-TTL payload whose fields have all expired still returns its existing
already-expired key marker (`t_hash.cc:1617`); the unit checks this explicitly.

**Redis reference actually read.** `/home/user/Projects/redis/src/version.h:1`
identifies **7.4.10**. The absent-key branches used as the reply oracle are:

| Command | Redis 7.4.10 source lines | Without count | With count |
|---|---|---|---|
| SPOP | `src/t_set.c:739-756`, `:946-960` | RESP2 nil / RESP3 null | RESP2 empty array / RESP3 empty set |
| SRANDMEMBER | `src/t_set.c:998-1025`, `:1203-1219` | RESP2 nil / RESP3 null | Empty array |
| ZRANDMEMBER | `src/t_zset.c:4217-4235`, `:4422-4447` | RESP2 nil / RESP3 null | Empty array, including WITHSCORES |
| HRANDFIELD | `src/t_hash.c:2575-2601`, `:2820-2851` | RESP2 nil / RESP3 null | Empty array |

Exact wire constants were checked in Redis `src/server.c:1855`, `:1901-1905`,
and `:1917-1920`: `$-1\r\n`, `_\r\n`, `*0\r\n`, and `~0\r\n`.
Redis `src/rdb.c:1951`, `:1972`, `:2075`, `:2147` sends zero-length list/set/zset/hash
records to `emptykey`; `:3165-3167` returns no object with `RDB_LOAD_ERR_EMPTY_KEY`.
This is a per-record observation, not a claim that Redis always aborts the entire
RDB load. TomoKV's requested native-hook rejection uses its existing `Corrupt`
status and caller error propagation.

**S5 diagnosis and fix.** `src/cmd/t_server.cc:397` registers mutable `atomic`;
`:1530-1531` applies CONFIG SET through `Server::set_atomic_enabled`. That setter
changes the enable bit in `atomic_activity_` (`src/core/server.h:2553-2557`), leaving
the boot `Config` unchanged. `IoLoop::flip_fingerprint_note_sampled` nevertheless
read `srv_->cfg().atomic`. At `src/core/io_loop.h:4297` it now calls the existing
`atomic_enabled()` acquire-load accessor, masking the enable bit rather than
mistaking outstanding atomic activity for an enabled mode.

The site is shared by `tomo` and **`tomo_db0` / `--databases 1`**; both are fixed
and directly tested. The load stays in the noinline sampled classifier and behind
`keys > 1`. This is a TomoKV-specific configuration defect; no Redis equivalence
is asserted for the atomic knob. A source-wide audit of `cfg.atomic`, `cfg_.atomic`,
and `cfg().atomic` found no other stale runtime readers. Remaining references are
boot initialization (`server.h:275`), parser validation (`config.h:1042`), and
CONFIG registry initialization (`t_server.cc:397`).

**Regression coverage.** Test commit `3de635d20` preceded all production fixes.
S4 is in `tests/netcmd_zset_unit.cc`, with standalone `empty-load` and
`empty-random` selectors. Load rejection covers set/zset/list, both hash encodings,
null and non-null zero-length buffers, result reset, valid empty-valued entries,
and the expired-field recovery control. The command test plants fresh objects
directly, bypassing the loader: absent, embedded compact, external compact, and
expanded. Its 336 calls per compiled variant cover RESP2/3, clean/notify handlers,
scalar/zero/positive/negative counts and ZRANDMEMBER WITHSCORES. Every call must
emit exactly the expected reply; each SPOP gets fresh state.

S5 is `NetcmdRegression::atomic_fingerprint` in `tests/netcmd_unit.cc`. It issues
real CONFIG SET owner fragments, validates CONFIG GET and the live enable bit,
then invokes the production IO fingerprint gate and pass-end publication. It
checks all class counters for MGET, MSET, GET, SET and BLPOP. Both boot values are
tested with three runtime toggles apiece; an activity bit remains set throughout.
The sampling window is 1, and five commands plus a closed publication window are
required, so a sample that never armed cannot pass. This is a serverless direct
unit, not a socket-level CONFIG test.

**Failing then passing transcripts.** The following commands were run on the
unmodified production tree with the new tests, then on POST. Corresponding db0
runs produced the same assertions/results. Complete per-run logs, including db0,
are in `build/cmdfix/{pre,post}[-db0]-*.log`; the original failing unit binaries
are retained as `build/cmdfix/netcmd-unit[-db0]-pre`.

```text
PRE:
$ taskset -c 112-127 ./build/netcmd-unit empty-load
FAIL: all empty collection snapshot loads must be rejected
FAIL: empty snapshot set encoding=0 rejected=0 result_null=0
FAIL: empty snapshot set encoding=0 rejected=0 result_null=0
FAIL: empty snapshot zset encoding=0 rejected=0 result_null=0
FAIL: empty snapshot zset encoding=0 rejected=0 result_null=0
FAIL: empty snapshot hash encoding=0 rejected=0 result_null=0
FAIL: empty snapshot hash encoding=0 rejected=0 result_null=0
FAIL: empty snapshot hash-ttl encoding=1 rejected=0 result_null=0
FAIL: empty snapshot hash-ttl encoding=1 rejected=0 result_null=0
FAIL: empty snapshot list encoding=0 rejected=0 result_null=0
FAIL: empty snapshot list encoding=0 rejected=0 result_null=0
exit=1
$ taskset -c 112-127 ./build/netcmd-unit empty-random
FAIL: empty random/pop handler must emit a reply
exit=1
$ taskset -c 112-127 ./build/netcmd-unit atomic-config-off
FAIL: atomic fingerprint boot=0 live=1 grouped=0 multiread=1 multiwrite=1
FAIL: fingerprint classification follows live CONFIG SET atomic
exit=1
$ taskset -c 112-127 ./build/netcmd-unit atomic-config-on
FAIL: atomic fingerprint boot=1 live=0 grouped=2 multiread=0 multiwrite=0
FAIL: fingerprint classification follows live CONFIG SET atomic
exit=1
POST:
$ taskset -c 112-127 ./build/netcmd-unit empty-load
ok: empty snapshot set encoding=0 rejected=1 result_null=1
ok: empty snapshot set encoding=0 rejected=1 result_null=1
ok: empty snapshot zset encoding=0 rejected=1 result_null=1
ok: empty snapshot zset encoding=0 rejected=1 result_null=1
ok: empty snapshot hash encoding=0 rejected=1 result_null=1
ok: empty snapshot hash encoding=0 rejected=1 result_null=1
ok: empty snapshot hash-ttl encoding=1 rejected=1 result_null=1
ok: empty snapshot hash-ttl encoding=1 rejected=1 result_null=1
ok: empty snapshot list encoding=0 rejected=1 result_null=1
ok: empty snapshot list encoding=0 rejected=1 result_null=1
ok: netcmd empty-load
exit=0
$ taskset -c 112-127 ./build/netcmd-unit empty-random
ok: empty random/pop 336 direct calls (RESP2/3, clean/notify, four shapes)
ok: netcmd empty-random
exit=0
$ taskset -c 112-127 ./build/netcmd-unit atomic-config-off
ok: atomic fingerprint boot=0, three runtime toggles with active work
ok: netcmd atomic-config-off
exit=0
$ taskset -c 112-127 ./build/netcmd-unit atomic-config-on
ok: atomic fingerprint boot=1, three runtime toggles with active work
ok: netcmd atomic-config-on
exit=0
```

**Other local checks.** All nine existing standard `netcmd-unit` gate selectors
passed: streams, zpop, notify-oom, notify-retry, flush, output, pubsub, receive,
config. The zpop/config selectors include S4/S5 respectively. `multidb-unit`
passed both variants' layout locks, native snapshot/AOF persistence, and ownership
checks. `multidb-boundary-unit` passed all eight groups in 1s/2s on `112-119`,
including read-local off/on. Final release/unit compilation and `git diff --check`
passed. Production fixes are `f309a7fed` (S4) and `1274a87c8` (S5).

Two fixture limitations encountered were kept explicit. The existing broad
`netcmd-unit-db0 config` selector also invokes a multi-database tracking test;
that test fails `tracking map swapped` in the single-database build. Its isolated
`tracking-eviction` case fails identically in PRE and POST (logs retained), while
the directed db0 S4/S5 selectors and the standard gate's config row pass. The
boundary fixture initially rejected the 16-core affinity as `exact eight-core
admission fixture`; running on eight permitted cores resolved it. No assertion
was removed or weakened.

**Code and layout evidence.** No structure fields, layout locks, runtime knobs,
or compiler budgets were changed. The final binary is byte-identical to the POST
used for the unit checks and the offline audit. `tools/lbstall_artifacts.py compare`
checked PRE objects against POST, retaining opcodes and resolved relocation
targets. Its result (`build/cmdfix/post-hot.json`, `post-hot.log`) is **1616/1696**
selected bodies equal, **1610/1696** raw equal; the audit exits 1, not PASS.

| Scope | Raw equal | Equal with relocation targets resolved |
|---|---:|---:|
| db0 selected bodies | 803 / 849 | 809 / 849 |
| namespaced selected bodies | 807 / 847 | 807 / 847 |
| GET handlers, both variants | 6 / 6 | 6 / 6 |
| SET handlers, both variants | 4 / 4 | 4 / 4 |

S5's sampled helper grows from 628 to 651 bytes in each variant. The db0 linked
`ExLoopT<false>::execute<false,false>` changes from 3288 to 3224 bytes and its
`parse_and_dispatch<false,0,true,false,false,false,false>` from 10119 to 10109 bytes.
Thus the shared S5 header has observable code-generation effects beyond the cold
helper. The object audit also includes unselected COMDAT copies; its 80 differences
must not be described as 80 independently executed paths. Local attempts using a
relaxed diagnostic load and cached flags did not restore dispatch identity and
were discarded. The committed fix retains the existing acquire accessor.

The release `.text` changes **8,215,901 -> 8,217,837 bytes (+1,936)**. `.rodata`,
`.data`, and `.bss` sizes are unchanged. These facts do not establish a rate result.

**Frozen arms.** Paths are relative to this worktree; all are already built.

| Arm | Artifact | SHA-256 |
|---|---|---|
| PRE | `build/tomokv-cmdfix-pre` | `a4beb3a581b708fbd3a08cdc15409b5c1c4754b88008178ae9505a57356bd228` |
| POST | `build/tomokv-cmdfix-post` | `e4b8a7a6fc38a43efa2b135ef2c137ab87f6718f9af3d554bf727b1136911d4f` |
| PAD, kind A | `build/tomokv-cmdfix-pad` | `221044049c2b1968242e8b4f7b65d2e3e39a3ba424896a48c857244692291dc2` |

PAD is a **kind A behaviour twin scoped to well-formed benchmark data**: PRE's
boot-atomic fingerprint classification in POST's exact text size/layout. S4's
guards remain enabled, so it is not a PRE twin for corrupt images or planted empty
objects and must not be used for correctness acceptance. For the requested
GET/SET and ordinary populated headline cells, S4 does not alter behavior.
`tools/cmdfix_artifacts.py` derives the boot-field displacement from PRE and patches
only the two sampled classifiers. The receipt `build/cmdfix/pad.json` verifies
16 changed bytes, identical section/symbol layouts, and every other byte unchanged.
Applying the same transformation to both unit binaries reproduces both S5
failures (the `pad[-db0]-atomic-config-{off,on}.log` negative controls). No inverse
control is supplied: POST is larger than PRE, so adding padding cannot restore
PRE's smaller text size.

```text
$ sha256sum build/tomokv
e4b8a7a6fc38a43efa2b135ef2c137ab87f6718f9af3d554bf727b1136911d4f  build/tomokv
```

**Maintainer measurement request.** Use the quiet box and the gate's existing
instrument, load pins, offered loads, populations, durations, core placement and
null acceptance rules without changing thresholds. Run full correctness on POST
with the gate's 16-shard / 6 IO + 2 EX / eight-core battery geometry, both thread
modes and the existing differential oracle. From this worktree:

```sh
tests/gate.sh full --reference-binary "$PWD/build/tomokv-cmdfix-pre" \
  --candidate-binary "$PWD/build/tomokv-cmdfix-post"
```

Supply the maintainer's scheduled server/load allocations through the gate's
normal options/environment. Require **454 passing correctness rows, 0 gating
FAIL**. The full tier uses all 181 defined headline cells; inspect **h01-h64**
individually for the GET/SET requirement (both modes, all read-local/overlap/reorder
combinations, p1/p32). These cells use the default `--databases 1` runtime.
Use a recent matching accepted standing null, or collect one with the instrument's
`--collect-null 1` procedure first. A missing/invalid null is not acceptance.

Also compare PRE against the scoped PAD A with the same h01-h64 cells and geometry;
POST/PAD differences must be consistent with that null. Use the instrument's
`--only` selection for this diagnostic and retain its PARTIAL status. The deciding
number is each cell's scored PRE-vs-POST difference under the instrument's
existing spread/null rules, with no average hiding a losing cell. Rate at the
matched offered load is the throughput verdict; p1 retains the instrument's
latency score. Report cycles/op, instructions/op, IPC, both arm spreads and validity
checks alongside the scored result. A common POST/PAD movement relative to PRE
would implicate code/layout changes and still fails the intended neutrality if it
regresses beyond the accepted null. No gain is claimed from these correctness fixes.
Append the actual results as `MEASURE-RESULT` in this worktree.

**Gate accounting.** `tests/gate.sh` was not edited. Existing netcmd rows are
emitted at lines 1334-1339, before the quick-tier exit at line 2808. S4 extends
`netcmd zpop regression`; S5 extends `netcmd config regression`. No row was added
or retired: **EXPECT_QUICK stays 438; EXPECT_FULL stays 454**.

**Diff against the launch reference.**

```text
$ git diff 8a5c0ed0da868c8ae77b7402896b1bf86a03a02f --stat
 MEASURE-REQUEST-cmdfix.md | 271 ++++++++++++++++++++++++++++++++++++++++++++++
 Makefile                  |  10 ++
 src/cmd/t_hash.cc         |   2 +-
 src/cmd/t_list.cc         |   2 +-
 src/cmd/t_set.cc          |  13 ++-
 src/cmd/t_zset.cc         |   7 +-
 src/core/io_loop.h        |   2 +-
 tests/netcmd_unit.cc      |  79 +++++++++++++-
 tests/netcmd_unit.h       |   2 +
 tests/netcmd_zset_unit.cc | 118 ++++++++++++++++++++
 tools/cmdfix_artifacts.py |  65 +++++++++++
 11 files changed, 565 insertions(+), 6 deletions(-)
```
