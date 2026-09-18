# r7shadow4 — restore the gate's core TSAN unit link

Worktree `/home/user/Projects/cx-r7shadow`, branch `cx-r7shadow`, launch revision
`0766e7700`; link fix committed as `5913a0869`. All builds and serverless units
ran within CPUs 112-127. No server, benchmark, load generator or gate was run.
No performance claim is made.

The only implementation change is in `tests/gate.sh:job_core_tsan_build`:
remove the exclusion of `src/core/genthread.cc`. That TU defines the
`run_fused_server` called by the round-3 selector in `src/core/reorder.cc:4172`.
The gate now instruments and links all 40 production TUs in the Makefile's
`CORE_TEST_OBJ`, plus `tests/core_concurrency_unit.cc`. `src/main.cc` remains
outside the unit. The source-set comparison is recorded in
`build/r7shadow4/core-tsan-sources.json`.

Production source, Makefile, compiler budgets, role selection, test assertions
and sanitizer options are unchanged. The rebuilt release and PAD are each
**byte-identical to their respective frozen `43b695119` binaries**, including
debug information. This preserves both armed and disarmed behavior on every
path; it does not depend only on the sampled FIFO bodies.

| Check | Result | Evidence under `build/r7shadow4/` |
| --- | --- | --- |
| Original gate TSAN recipe | Exit 1: the reported undefined `run_fused_server` at `reorder.cc:4172`; no ready marker | `core-tsan-pre/build.log`, `core-tsan-pre.sh` |
| Corrected gate TSAN recipe | Exit 0; ready marker written; fused entry defined and TSAN runtime linked | `core-tsan-post/build.log`, `core-tsan-post.sh`, `artifact-identity.json` |
| TSAN watch/lifetime/drain/route/snapshot/config/notify | **7/7 pass**, expected state witnesses present, no runtime TSAN reports | `core-tsan-rows.log`, `core-tsan-post/tsan-core-concurrency-tsan-*.log` |
| Strict no-op witness | **169/169 identical FIFO bodies**, normalizer self-checks pass | `off-witness.log`, `off-witness/audit.json` |
| Split witnesses | **12/12 cells: 0 R7 operational paths, 0 reorder allocations**; complete allocation traces match; positive control and all 16 forbidden-path/allocation controls pass | `split-witness.log`, `split-witness.json` |
| AUTO depth unit, native and ASan/UBSan | Depths 16/32/64 (0.5x/1x/2x gather), warmup, engagement, immediate shallow release and no re-engagement after mean decay all pass | `auto-unit.log`, `auto-asan.log` |
| Scheduler/policy negative controls | All **8 mutants rejected**, including removed/inclusive depth floor, never-engage and sticky-engagement controls | `auto-mutants.log` |
| Production parser/inbox/handler fixtures | Default and separately patched kind-A unit twin pass; default exercises AUTO priority followed by FIFO disengagement | `engagement.log`, `engagement-pad.log`, `engagement-pad.json` |

The strict audit uses the same round-2 PRE as round 3:
`build/r7shadow3-pre/tomokv`, SHA256
`5f72057199d456a09b4145d022fa3a9e3047cba021ace8c7d92c6f0e28a5b81a`.
Its normalizer and exclusions are unchanged. Split tests pass raw reorder
`0/1/-1` with overlap `0/1` and read-local `0/1`, at 8 threads, 6 IO + 2 EX,
16 shards. Both owner template types are covered. The TSAN fixture uses the
same geometry and also exercises its existing fused ownership cases.

To test the actual build function without invoking the gate, the PRE and POST
`job_core_tsan_build` definitions were extracted verbatim into the saved shell
wrappers. Only their scheduling wrapper was replaced by direct execution;
`BUILD_CORES=112-127`, `PARBUILD_JOBS=8`, and logs/ready markers use this lane's
receipt directory. Output binary, cache directory, source order, compile flags
and link flags are the gate's own. The corrected compile/link invocation is:

```sh
taskset -c 112-127 env PARBUILD_JOBS=8 tests/parbuild.sh \
  "$PWD/build/gate-cache/core-concurrency-tsan" \
  "$PWD/build/gate-cache/obj-core-tsan" \
  '-std=c++20 -O1 -g -march=native -pthread -fsanitize=thread -fno-omit-frame-pointer -no-pie -DTOMO_CORE_CONCURRENCY_TEST -I.' \
  '-luring -pthread -lssl -lcrypto -lm' \
  tests/core_concurrency_unit.cc src/net/tls.cc src/core/*.cc src/cmd/*.cc \
  src/snapshot/*.cc src/persist/*.cc
```

`core-tsan-rows.sh` similarly uses the gate's verbatim `tsan_unit` helper with
`CORES=112-119`: `TSAN_OPTIONS=halt_on_error=1:exitcode=66`, `setarch x86_64 -R`,
the 60-second bound and exact state-witness checks. All seven selections pass
on their first invocation. These are serverless unit runs, not a gate run.

GCC emits 21 `-Wtsan` warnings from the added instrumented TU saying
`atomic_thread_fence` is unsupported with ThreadSanitizer. The diagnostics are
preserved in `core-tsan-genthread-diagnostics.log`; no suppression or flag change
was introduced. Compilation and linking succeed. The release/witness rebuild
has no compiler warnings or errors. Generated envelopes, `bash -n tests/gate.sh`
and `git diff --check` also pass.

The forced rebuild used the default release flags, including all existing
per-TU compiler budgets:

```sh
taskset -c 112-127 make -B -j8 all build/tomokv-pad \
  build/r7shadow-split-unit build/reorder-engagement-unit \
  build/r7shadow-unit build/r7shadow-unit-asan
taskset -c 112-127 python3 tests/r7shadow_noop.py \
  build/r7shadow3-pre/tomokv build/tomokv build/r7shadow4/off-witness
taskset -c 112-127 python3 tests/r7shadow_split_witness.py \
  build/r7shadow-split-unit --receipt build/r7shadow4/split-witness.json
taskset -c 112-127 ./build/r7shadow-unit
ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 \
  taskset -c 112-127 ./build/r7shadow-unit-asan
taskset -c 112-127 python3 tests/r7shadow_mutants.py
taskset -c 112-127 ./build/reorder-engagement-unit on shadow
taskset -c 112-127 python3 tests/r7shadow_pad.py \
  build/reorder-engagement-unit build/r7shadow4/engagement-pad \
  --scope fifo --receipt build/r7shadow4/engagement-pad.json
taskset -c 112-127 ./build/r7shadow4/engagement-pad off shadow
```

| Rebuilt artifact | SHA256 |
| --- | --- |
| Default `build/tomokv` | `e79aeea3f0008c37022ab8f3db720d450b8ed108736f02c217cf6a2781d8613e` |
| Kind-A PAD `build/tomokv-pad` | `a1b9a51cf758c34de6d98137e9c5484cdfc3d9b59cc43553509db80819e2d990` |
| Gate unit `build/gate-cache/core-concurrency-tsan` | `dadc05f319bbcd47f2bc58ab8443076ddebad430fc2a9a0fc59463ee9659036c` |

The frozen references are
`/home/user/Projects/bench-bins/tomokv-r7shadow3-43b695119` and
`/home/user/Projects/bench-bins/tomokv-r7shadow3-pad-43b695119`.
Both SHA256 comparison and `cmp` pass for each respective pair. Launch copies
are retained as `build/r7shadow4/pre-tomokv{,-pad}`. Full artifact evidence is in
`build/r7shadow4/artifact-identity.json`; build output is in `rebuild.log` and
the witness commands/exit codes are in `witness-results.json`.

**PAD kind A means a behavior twin: PRE FIFO (`--reorder 0`) behavior with
POST's exact text size and layout.** Run this control with `--reorder 1`.
Default and PAD each contain 4,190,557 `.text` bytes and 91,896,336 file bytes.
They differ only at file offset 3,665,589: the `reorder_available` return
immediate changes `01` to `00`. Every other byte, symbol and section matches;
receipt `build/tomokv-pad.json`. This is the same kind-A control as `43b695119`.

Mainline follow-up is `tests/gate.sh iteration` on the committed tree, at the
gate's ordinary geometry and pins. No new performance measurement is requested
for this link repair. The full gate remains unrun by this lane. No row was
added or retired: the seven existing core rows at lines 1235-1236 remain above
the quick-tier exit at line 2759. `EXPECT_QUICK=419` and `EXPECT_FULL=435`
(lines 254-255) are unchanged; no count adjustment is needed.
