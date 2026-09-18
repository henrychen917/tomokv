**r7shadow7 — merge cx-final and verify both database variants**

Worktree `/home/user/Projects/cx-r7shadow`, branch `cx-r7shadow`. Launch was
`356539abddf2be2a4b27e3383afdef8b90cee88b`. Merged
`e3eb887b3` (`cx-final`, containing landed reference `004a02ddf`) in
`e02fc3d17`. Follow-up commits are `f8620a0b9` (variant-aware PAD and database
parser coverage), `227358087` (materialize the fixture's coded replies), and
`90df89a32` (make the missing-stamp negative control fail its assertion).

All requested build recipes and current functional/sanitizer checks pass.
**This is not an all-green historical audit:** the old 169-body byte witness
and the superseded round-1 shadow-only PAD invocation fail. Both failures were
reproduced on their pre-merge controls, as detailed below. Neither assertion
was relaxed. The normal round-4 FIFO PAD checks pass.

Every build and executable check ran under `taskset -c 112-127`; make used
`-j16`, and the gate's parallel compiler used `PARBUILD_JOBS=16`. The multidb
boundary fixture additionally selected `112-119` inside that mask because it
requires exactly eight visible CPUs. The core/reorder fixtures declare eight
threads and 16 shards themselves (6 IO + 2 EX in split mode). No server,
benchmark, load generator, gate, instruction counter, or performance
measurement was run. Nothing was pushed. Evidence is under `build/r7shadow7/`.

The three conflicts were resolved as follows. Line ranges refer to this tree.

| File | Resolution and final lines |
| --- | --- |
| `MEASURE-REQUEST` | Lines 1–4 are ours verbatim; line 5 separates the records; lines 6–16 are theirs verbatim. Verified byte-for-byte against both parents. No later edit was made to this root record. |
| `Makefile` | Lines 35–47 include both `multidb.cc` and the last-linked `reorder.cc`, and link both `OBJ` and `DB0_OBJ`. Lines 52–82 retain the multidb `BUILD_ROOT`, namespace/variant compilation, `override` flags, and L4 source dependencies. The r7shadow compiler budgets (main 146255, genthread 128880, rl2s 161715) apply to both variants; the normal main also retains `TOMO_DUAL_DATABASE`. Lines 84–112 retain the landing's recursive instrumented build rules. Lines 157–170 retain all multidb unit/PAD targets and include `genthread.o` in **both** unit object sets, excluding only each main. |
| `src/main.cc` | Lines 133–143 preserve both boot entries and the `databases > 1` selector. Lines 187–192 select the database runtime after validation, then apply reorder capability/mode resolution. Lines 323–326 retain `run_fused_server_selected`. Split role entries remain direct baseline calls. |

The round-4 `job_core_tsan_build` change merged automatically in
`tests/gate.sh:2515–2525`: its production source list includes `genthread.cc`.
The matching source-set assertion survives in `tests/gates_test.py:1382`.
The public grammar/default survive in `src/core/config.h:384–388,836–842`:
`--reorder -1|0|1`, default 0, with split requests resolved to 0.
`Server::init` also resolves the raw knob before allocation
(`src/core/server.h:245,361–368`).

The non-conflicting generated `src/core/reorder.cc` needed a real merge repair.
The unchanged envelope check initially rejected it as stale. Running
`python3 tests/r7shadow_sync.py --write` regenerated the armed wrappers from
the merged ordinary parser/IO code. This brought over the SWAPDB accept and
backpressure checks, the pre-stamp pause fence, immutable database stamping,
and the SELECT/RESET pass boundary. In particular, the stamp now appears at
`src/core/reorder.cc:2665–2680`, before key hashing/routing and shadow dispatch.
The final generator check passes. Without this repair, armed multidb requests
could use the wrong database identity despite the ordinary parser being fixed.

**Variant answer: the scheduler is shared source, instantiated in both runtimes.**
`src/core/reorder.cc` belongs to the common `SRC` list (`Makefile:37`), from
which both object lists are derived (`Makefile:41–42`). The DB-0 rule compiles
it with `TOMO_SINGLE_DATABASE=1` and `tomo=tomo_db0` (`Makefile:76–78`);
the other rule compiles the same file in `tomo` (`Makefile:80–82`). The fused
selector and generated fused pass are therefore instantiated once per runtime.
The policy is not guarded out of either variant:

| Shared mechanism | Source |
| --- | --- |
| SHADOW bit, predecessor distance, parser stamp | `src/core/reorder.h:55–124`; production dispatch `src/core/reorder.cc:3742` |
| Three ready FIFOs and short/Long/shadow priority | `src/core/reorder.h:429–430,462–465,517–518` |
| Sampled AUTO policy and role-local policy scope | `src/core/reorder.h:174–228` |
| AUTO wiring on the existing depth tick | `src/core/reorder.cc:995,1083–1085` |
| Fused boot policy selection | `src/core/reorder.cc:4183–4195` |

The linked executable contains both namespaces' capability predicates, fused
selectors, armed loops, and shadow queues. `variant-symbols.json` records equal
symbol-family inventories in both namespaces. This establishes identical
scheduler source/policy, **not byte identity of all database-dependent machine
code**. The same production engagement and split-isolation fixtures were also
compiled against the DB-0 objects and passed, including AUTO engagement and
same-tick disengagement. DB-0 fixture links also include the regular objects
because the landing emits shared third-party Lua only once.

The new directed case in `tests/reorder_engagement_unit.cc:292–376` covers raw
0/1/-1 requests, SELECT ending a parser pass, a mandatory open SWAPDB boundary,
resumption against a changed physical mapping, exact hash/shard/namespace
identity, the own-pipe Long shadow, real handlers, and RESP retirement. The DB-0
instantiation covers SELECT 0 and the same scheduler path. A throwaway object
with only the armed parser's `multidb_stamp` removed exits 1 at the required
`database stamp/hash/shard must use the post-boundary map` assertion. It is not
linked into any production artifact.

The old PAD builder only patched `tomo::reorder_available`, leaving the default
DB-0 runtime armed. `tests/r7shadow_pad.py:18–51` now patches every linked
runtime and verifies each original predicate and all other bytes. The current
PAD is **kind A, behavior twin: PRE FIFO (`--reorder 0`) behavior with POST's
exact text size/layout**. It changes exactly two bytes in the dual executable,
at file offsets 3685141 and 7726501, and passes both variants' unit controls.
The historical `--scope shadow` control is also kind A, but represents old R7
without shadow; its obsolete AUTO invocation is recorded below.

`sha256sum build/tomokv`:

```text
ea77b6196292d507278f9cdcf13fa75addad6c286b9d29d368f938134d9d0122  build/tomokv
```

The current FIFO PAD SHA256 is
`1b0051bc754b44e192e7cf34db8c0a819b3d72acb3aa30f8ea4a89fca5b04a1a`.
Both have 8,215,901 `.text` bytes and 184,866,816 file bytes. This is an artifact
receipt, not a performance result. See `build/tomokv-pad.json` and
`build/r7shadow7/final-sha256.txt`.

Build coverage follows the actual merged `tests/gate.sh` recipes:

| Build | Result / evidence |
| --- | --- |
| Default `make -j16` and both database variants | PASS; `release-unit-build.log`, `final-release-build.log` |
| All `job_production_units` targets: core concurrency, atomic survivors, netcmd, waits, rehash waits, multidb, multidb boundary | PASS; `release-unit-build.log`; final `make -q` verifies current prerequisites |
| `job_tailgen_build` target `build/tailgen` | PASS, build only; never executed |
| Exact gate `job_asan` and `job_rldbg` compile/link recipes | PASS; `gate-asan.log`, `gate-rldbg.log`, `recipe-asan/`, `recipe-rldbg/` |
| Exact `job_core_tsan_build` and `job_waits_tsan_build` | PASS; ready markers present; `gate-core-tsan.log`, `gate-waits-tsan.log`, corresponding `recipe-*/build.log` |
| All three `store_build` variants: normal, TSAN, deadline sidecar | PASS; `gate-store*.log` |
| Exact direct compiler recipes for config, flip, foreign-read filter, write ring | PASS, followed by their units; `gate-config.log`, `gate-flip.log`, `gate-filter.log`, `gate-ring.log` |
| Native/ASan reorder units, engagement and instrumented split fixtures, FIFO PAD | PASS; `variant-unit-build.log`, `final-fixture-build.log` |
| Additional DB-0 engagement, instrumented split, and shadow ASan/UBSan fixtures | PASS; `db0-final-build.log`, `final-fixture-build.log` |

`gate-recipes.sh` contains verbatim extracted build/unit helper definitions,
not a sourced or executed gate. Only the scheduling/logging wrappers are local;
compiler flags, source ordering, output/cache paths and TSAN witness checks are
the gate's. Core TSAN instruments every production dependency, including
genthread. As inherited from mainline, the gate's ASAN/RLDBG recipes compile the
regular namespace; the release build includes both. GCC's existing
`atomic_thread_fence`/TSAN warnings are retained in cache `.err` files; no
suppression or sanitizer-option weakening was introduced.

The executable/offline checks below all used the CPU prefix stated above.
Results are final results unless explicitly marked historical or preliminary.

| Invocation / selection | Result / evidence |
| --- | --- |
| `python3 tests/gates_test.py` | PASS, 56 tests; `gates-test.log` |
| `make -j16 unit` | PASS: reorder unit (205 exact permutations), shadow unit, config parser, flip controller, read-local reclaim ring, read-local write ring, waits; `make-unit.log` |
| `ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 ./build/core-concurrency-unit ROW` for watch/lifetime/drain/route/snapshot/config/notify | PASS, 7/7 with state witnesses; `core-asan-results.tsv`, `core-asan-ROW.log` |
| Same core ASan/UBSan binary, `lbstall` and `lbshard` | PASS, 2/2; same evidence |
| `bash build/r7shadow7/gate-recipes.sh core-tsan-run ROW`, all seven core rows plus lbstall/lbshard | PASS, 9/9; exact gate `TSAN_OPTIONS=halt_on_error=1:exitcode=66`, 60-second limit, `setarch x86_64 -R`, state witness and no-runtime-report checks; `core-tsan-results.tsv`, `recipe-core-tsan-run/` |
| `./build/multidb-unit` | PASS, DB-0 layout/identity/armed reads and multidb identity, snapshot/AOF, SELECT/MOVE/COPY/SWAPDB/WATCH; `multidb-unit.log` |
| `taskset -c 112-119 ./build/multidb-boundary-unit` | PASS, accept/stamp/publication/serial boundary fixtures in both modes; `multidb-boundary-unit.log` |
| `python3 tests/multidb_serial.py --self-test` | PASS, both legal serial orders accepted and stale-stamp control rejected; `multidb-serial-self-test.log` |
| `tests/read_local_write_ring_unit.cc`, both Makefile and exact gate compiler recipes | PASS, including bounded arming and 200k-frame soaks; `make-unit.log`, `recipe-ring/gate-ring-unit.txt` |
| `python3 tests/legacy_reorder_witness.py --self-test` | PASS, 10 tests; `legacy-reorder-self-test.log`; no live server mode invoked |
| `ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 ./build/r7shadow-unit-asan` | PASS, shadow order/completion/reuse/barriers/fairness/AUTO depth floor; `shadow-asan.log` |
| Same sanitizer options, `./build/reorder-unit-asan` | PASS, inherited R7 scheduler assertions; `reorder-asan.log` |
| Same sanitizer options, `./build/r7shadow7/shadow-db0-asan` | PASS, same shadow/AUTO suite in DB-0 namespace; `shadow-db0-asan.log` |
| `python3 tests/r7shadow_mutants.py` | PASS: all 8 defects rejected at their required assertions; `shadow-mutants.log` |
| `./build/reorder-engagement-unit on shadow` | PASS, production parser/inbox/handler fixtures, AUTO and three new database cases; `engagement-final.log` |
| `./build/r7shadow7/engagement-db0 on shadow` | PASS, same fixture in DB-0; `engagement-db0-final.log` |
| `python3 tests/r7shadow_pad.py SOURCE PAD --scope fifo --receipt RECEIPT`, then `PAD off shadow`, for both engagement binaries | PASS, current kind-A controls; `engagement-final-pad*.log`, `engagement-db0-final-pad*.log` |
| `python3 tests/r7shadow_split_witness.py BINARY --receipt RECEIPT`, for `build/r7shadow-split-unit` and `build/r7shadow7/split-db0` | PASS in each variant: 12 raw-knob cells, zero R7 operational entries/allocations, matching complete allocation traces, positive control and 16 negative controls; `split-witness-final.*`, `split-db0-final.*` |
| `./build/r7shadow7/engagement-no-database-stamp on shadow` | Required negative result: exit 1 on the exact namespace assertion; `database-stamp-mutant-final.log`, `final-witness-results.json` |
| `./build/netcmd-unit config` | PASS, signed AUTO spelling/capability/config checks; `netcmd-config.log` |
| `bash build/r7shadow7/gate-recipes.sh waits-tsan-run` | PASS, exact gate witness and TSAN checks; `recipe-waits-tsan-run/tsan-waits-unit-tsan.log` |
| `python3 tests/reorder_scope_test.py` | PASS, 8 tests; `reorder-scope-test.log` |
| `python3 tests/abbagate.py --self-test` | PASS, 112 tests (95 ABBA + 10 saturation + 7 calibration), synthetic controls only; `abba-self-test.log` |
| `python3 tests/r7shadow_sync.py`, `bash -n tests/gate.sh`, `git diff --check` | PASS; `sync-final.log` |
| GDB type queries on `build/tomokv`, without run/start/attach | PASS in both namespaces: Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624; ModeScheduleStats 64; `layouts.log` |

The legacy witness self-test exercises its actual protocol/verdict logic with
the server/transport replaced. Its live criterion is an admitted SETRANGE
before GET in MONITOR, GET returning the old value, and the final value showing
the write: an execution inversion. OFF must reject inversions; ON must witness
one within bounded fresh-state attempts. An unopened window, missing/duplicate
events, hidden mutation, changed producer/owner/client assignment, full queues,
migration, or MVCC history cannot pass. The ten controls include disabled ON and
broken OFF cases. This run certifies those self-tests, not a live legacy server.

Historical failures retained for the owner:

1. `python3 tests/r7shadow_noop.py build/r7shadow3-pre/tomokv build/tomokv
   build/r7shadow7/historical-off-witness` exits **1**, 29/169 identical.
   Running the exact same script/PRE against the frozen landing reference
   `/home/user/Projects/bench-bins/tomokv-headline-004a02ddf` also exits **1**,
   29/169, with the **same failure set**. The reference SHA256 was verified as
   `fe4affc0158969922b10f0930e947ca7a8e3814c7cf8456294f4a95517657904`, matching
   `tests/gate_measurements.json`. The old witness compares pre-multidb `tomo`
   bodies to the new namespaced runtime; the multidb landing itself documented
   changed code generation. No normalizer, exclusions, or expected count was
   changed. See both `*-historical-off-witness` receipts/logs and
   `historical-noop-attribution.json`.

   Comparing the already-normalized POST bodies in these two audits gives
   **165/169 equal between landing and this merge**. The four differing bodies
   are `ExLoopT<true>::run`, split-local `parse_and_dispatch<false,0,true,false,
   false,false,true>`, the constprop FlatStore scan clone used by
   `xshard_execute`, and `IoLoop::run_loop<true,true,false,false,0,false>`.
   Those differences are retained in the evidence. This report does not claim
   full off-path byte identity or infer a performance verdict from it.

2. The round-1 `--scope shadow` unit twin invoked as `on r7` exits **1** at
   `AUTO engagement did not select the actual shadow scheduler`. Rounds 2–4
   had already superseded it with the FIFO twin. To attribute this without
   changing tests, the saved round-4 FIFO unit twin was restored by reversing
   its one recorded capability byte; its SHA256 exactly matches the original
   round-4 POST receipt. That restored unit passes `on shadow`; its shadow-only
   twin fails the **same** AUTO assertion. See `historical-shadow-pad.json` and
   `round4-engagement-*.log`. The current FIFO twins pass in both variants.

Preliminary fixture/setup failures were also retained: the first generator
check caught stale merged envelopes (`sync-pre.log`); a core unit invocation
without its required ROW exited 1 with `select one regression row`
(`core-asan-all.log`), before the successful named runs. The new database
fixture initially read only `op.reply` and missed fused coded replies; it now
uses the production `op_materialise_code` before the exact reply assertion.
The first DB-0-only supplemental link omitted shared Lua; adding the normal
object set, as the landing's dual-variant unit does, fixed that test link.
The first missing-stamp mutant reached an uninitialized foreign fixture inbox
and faulted; the final bounded key selection makes both correct and deliberately
wrong namespaces route to the initialized owner, yielding the exact required
assertion instead. These fixes affect test setup/oracles, not server behavior.

The supplemental DB-0/negative-control build rules and exact invocations are
saved in `build/r7shadow7/variant-tests.mk`. They compile the existing fixture
with `-DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0`, linking `DB0_TEST_OBJ` and
`CORE_TEST_OBJ`; the split unit substitutes an equivalently compiled
`TOMO_R7_WITNESS` reorder object. Reproduction uses
`taskset -c 112-127 make -f Makefile -f build/r7shadow7/variant-tests.mk -j16`
with the named `build/r7shadow7/` targets above. No tracked production source
was modified to produce a negative control. `final-witness-results.json`
records the final commands, actual/expected exit codes, and all nine results.

No gate row was added or retired. The inherited landing counts remain
`EXPECT_QUICK=438` / `EXPECT_FULL=454` at `tests/gate.sh:257–258`; the quick
exit is at line 2812. No lane edit touched either constant. The maintainer owns
the full `tests/gate.sh iteration` run and landing; no new measurement is
requested by this report.

The following is the literal output of `git diff cx-final --stat -- src tests`.
Every entry belongs to the reorder scheduler, its boot/config/INFO plumbing,
queue observation, or its tests/instrument integration. There is no residual
diff to multidb implementation, storage/persistence, or unrelated commands.

```text
 src/cmd/t_server.cc              |   14 +-
 src/core/config.h                |   28 +-
 src/core/ex_loop.h               |   32 +
 src/core/genthread.h             |    8 +
 src/core/io_loop.h               |   64 +
 src/core/orthog.h                |   33 +-
 src/core/reorder.cc              | 4196 ++++++++++++++++++++++++++++++++++++++
 src/core/reorder.h               |  618 ++++++
 src/core/rl2s.cc                 |    7 +-
 src/core/server.h                |    6 +-
 src/core/signal.h                |    4 +
 src/core/thread.h                |    2 +
 src/exec/masked_queue.h          |   12 +
 src/main.cc                      |    6 +-
 tests/abba_workloads.py          |    7 +
 tests/config_parser_test.cc      |   35 +-
 tests/feature_gate.py            |   21 +-
 tests/gate.sh                    |    7 +-
 tests/gates_test.py              |   29 +-
 tests/netcmd_unit.cc             |   20 +-
 tests/orthog.py                  |   29 +-
 tests/r7shadow_instr.cc          |  134 ++
 tests/r7shadow_mutants.py        |   48 +
 tests/r7shadow_noop.py           |   98 +
 tests/r7shadow_pad.py            |   68 +
 tests/r7shadow_split_unit.cc     |   84 +
 tests/r7shadow_split_witness.py  |   71 +
 tests/r7shadow_sync.py           |  146 ++
 tests/r7shadow_unit.cc           |  321 +++
 tests/r7shadow_witness.h         |   60 +
 tests/reorder_engagement_unit.cc |  589 ++++++
 tests/reorder_flip.py            |  225 ++
 tests/reorder_noop.py            |  396 ++++
 tests/reorder_scope.py           |  417 ++++
 tests/reorder_scope_test.py      |  103 +
 tests/reorder_unit.cc            |  428 ++++
 36 files changed, 8285 insertions(+), 81 deletions(-)
```
